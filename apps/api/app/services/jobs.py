"""Creation and dispatch of analysis jobs.

Jobs are created in the request (status `pending`, with the tool version
detected at that moment) and executed by the worker.
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from arva_core.seqstats import TOOL_NAME, TOOL_VERSION
from arva_tools import DetectedTool, ToolStatus
from arva_tools.bakta import BaktaAdapter, BaktaParams
from arva_tools.bakta import flags as bakta_flags
from arva_tools.fastp import FastpParams
from arva_tools.filtlong import FiltlongParams
from arva_tools.flye import FlyeAdapter, FlyeParams, read_checkpoint
from arva_tools.mlst import MlstAdapter, MlstParams
from arva_tools.mlst import flags as mlst_flags
from arva_tools.pilon import FLAGS as PILON_FLAGS
from arva_tools.pilon import PilonAdapter, PilonParams, java_executable
from arva_tools.prokka import ProkkaAdapter, ProkkaParams
from arva_tools.prokka import flags as prokka_flags
from arva_tools.quast import QuastAdapter, QuastParams, aligner
from arva_tools.quast import flags as quast_flags
from arva_tools.racon import FLAGS as RACON_FLAGS
from arva_tools.racon import RaconAdapter, RaconParams
from arva_tools.registry import detect
from arva_tools.spades import SpadesAdapter, SpadesParams
from arva_tools.unicycler import UnicyclerAdapter, UnicyclerParams, helper_paths
from redis.exceptions import RedisError
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job as RqJob
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.models import AnalysisJob, Assembly, JobStatus, Project, RawFile, ReferenceDatabase, Sample
from app.services.annotation import assembly_record
from app.services.performance import Resources, effective_resources
from app.services.queue import get_queue
from app.services.raw_signal import POD5_INSTALL, is_raw_signal, pod5_versions
from app.storage import get_storage

FASTQ_STATS_JOB = "sequence_stats"
SEQKIT_JOB = "seqkit_stats"
FASTQC_JOB = "fastqc"
FASTP_JOB = "fastp"
FILTLONG_JOB = "filtlong"
SERVER_IMPORT_JOB = "server_import"
SERVER_IMPORT_TOOL = "arva-import"
POD5_JOB = "pod5_summary"
POD5_TOOL = "pod5"
MULTIQC_JOB = "multiqc"
NANOPLOT_JOB = "nanoplot"
FLYE_JOB = "flye_assembly"
SPADES_JOB = "spades_assembly"
UNICYCLER_JOB = "unicycler_assembly"
ASSEMBLY_JOBS = (FLYE_JOB, SPADES_JOB, UNICYCLER_JOB)
QUAST_JOB = "quast_evaluation"
RACON_JOB = "racon_polish"
PILON_JOB = "pilon_polish"
POLISHING_JOBS = (RACON_JOB, PILON_JOB)
BAKTA_JOB = "bakta_annotation"
PROKKA_JOB = "prokka_annotation"
ANNOTATION_JOBS = (BAKTA_JOB, PROKKA_JOB)
MLST_JOB = "mlst_typing"
SPECIES_JOB = "species_identification"


class ToolUnavailableError(RuntimeError):
    pass


class JobStateError(RuntimeError):
    """The job is not in a state that allows the request (e.g. cancelling a finished job)."""


def _rq_id(job_id: str) -> str:
    return f"arva-{job_id}"


def _enqueue(jobs: list[AnalysisJob], func) -> None:
    queue = get_queue()
    for job in jobs:
        queue.enqueue(func, job.id, job_id=_rq_id(job.id))


def require_tool(tool_id: str) -> DetectedTool:
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available:
        raise ToolUnavailableError(f"{d.info.name} is not available ({d.status.value}): {d.message}")
    return d


def new_sequence_stats_job(sample: Sample, raw_id: str, parameters: dict, parent_job_id: str | None = None) -> AnalysisJob:
    return AnalysisJob(
        project_id=sample.project_id,
        sample_id=sample.id,
        job_type=FASTQ_STATS_JOB,
        tool_name=TOOL_NAME,
        tool_version=TOOL_VERSION,
        parameters=parameters,
        input_raw_file_ids=[raw_id],
        status=JobStatus.pending,
        log_text="",
        parent_job_id=parent_job_id,
    )


def enqueue_sequence_stats(jobs: list[AnalysisJob]) -> None:
    from app.tasks.seqstats import run_sequence_stats_job

    _enqueue(jobs, run_sequence_stats_job)


def create_sequence_stats_jobs(
    db: Session,
    sample: Sample,
    raw_files: list[RawFile],
    parameters: dict,
    parent_job_id: str | None = None,
) -> list[AnalysisJob]:
    """Create one ARVA statistics job per input file and enqueue them."""
    jobs = [new_sequence_stats_job(sample, raw.id, parameters, parent_job_id) for raw in raw_files]
    db.add_all(jobs)
    db.commit()
    enqueue_sequence_stats(jobs)
    for job in jobs:
        db.refresh(job)
    return jobs


def files_without_stats(db: Session, sample_id: str, files: list[RawFile]) -> list[RawFile]:
    """Read files with no pending, running or completed ARVA statistics job."""
    existing = db.scalars(
        select(AnalysisJob).where(
            AnalysisJob.sample_id == sample_id,
            AnalysisJob.job_type == FASTQ_STATS_JOB,
            AnalysisJob.status.in_([JobStatus.pending, JobStatus.running, JobStatus.completed]),
        )
    ).all()
    covered = {fid for j in existing for fid in (j.input_raw_file_ids or [])}
    return [f for f in files if f.id not in covered and not is_raw_signal(f)]


def _tool_job(sample: Sample, job_type: str, tool: DetectedTool, parameters: dict, inputs: list[str],
              resources: dict | None = None) -> AnalysisJob:
    return AnalysisJob(
        project_id=sample.project_id,
        sample_id=sample.id,
        job_type=job_type,
        tool_name=tool.info.name,
        tool_version=tool.version or "unknown",
        tool_path=tool.path,
        parameters=parameters,
        input_raw_file_ids=inputs,
        status=JobStatus.pending,
        log_text="",
        resources=resources,
    )


def _ran_threads(tool_id: str, threads: int) -> int:
    # ARVA runs FastQC on one file per job, with --threads 1 (its threads are files processed at once).
    return 1 if tool_id == "fastqc" else threads


def create_per_file_tool_jobs(
    db: Session, sample: Sample, files: list[RawFile], tool_id: str, parameters: dict | None = None
) -> list[AnalysisJob]:
    from app.tasks.tools import run_fastqc_job, run_nanoplot_job, run_seqkit_job

    job_type, func = {
        "seqkit": (SEQKIT_JOB, run_seqkit_job),
        "fastqc": (FASTQC_JOB, run_fastqc_job),
        "nanoplot": (NANOPLOT_JOB, run_nanoplot_job),
    }[tool_id]
    tool = require_tool(tool_id)
    res = effective_resources(db)
    jobs = [_tool_job(sample, job_type, tool, {"threads": res.threads, **(parameters or {})}, [f.id],
                      res.record(_ran_threads(tool_id, res.threads))) for f in files]
    db.add_all(jobs)
    db.commit()
    _enqueue(jobs, func)
    for job in jobs:
        db.refresh(job)
    return jobs


def create_batch_qc_jobs(db: Session, runs: dict[str, list[tuple[Sample, RawFile]]]) -> list[AnalysisJob]:
    """The jobs of a project batch, created together (one commit, each tool detected once): `runs` maps
    sequence_stats, seqkit and fastqc to the (sample, file) pairs to analyse. Each job is an ordinary per-sample job
    with the same parameters as one started from the sample's page."""
    from arva_core.seqstats import StatsParameters

    from app.tasks.tools import run_fastqc_job, run_seqkit_job

    tools = {tool_id: require_tool(tool_id) for tool_id in ("seqkit", "fastqc") if runs.get(tool_id)}
    res = effective_resources(db)
    stats = [new_sequence_stats_job(sample, f.id, StatsParameters().as_dict()) for sample, f in runs.get("sequence_stats", [])]
    by_tool = {tool_id: [_tool_job(sample, job_type, tools[tool_id], {"threads": res.threads}, [f.id],
                                   res.record(_ran_threads(tool_id, res.threads)))
                         for sample, f in runs.get(tool_id, [])]
               for tool_id, job_type in (("seqkit", SEQKIT_JOB), ("fastqc", FASTQC_JOB))}
    jobs = stats + by_tool["seqkit"] + by_tool["fastqc"]
    db.add_all(jobs)
    db.commit()
    enqueue_sequence_stats(stats)
    _enqueue(by_tool["seqkit"], run_seqkit_job)
    _enqueue(by_tool["fastqc"], run_fastqc_job)
    for job in jobs:
        db.refresh(job)
    return jobs


def create_fastp_job(db: Session, sample: Sample, r1: RawFile, r2: RawFile | None, params: FastpParams) -> AnalysisJob:
    from app.tasks.tools import run_fastp_job

    res = effective_resources(db)
    # fastp's own default thread count, lowered to the profile's.
    params.threads = min(params.threads, res.threads)
    params.validate(paired=r2 is not None)
    tool = require_tool("fastp")
    inputs = [r1.id] + ([r2.id] if r2 else [])
    job = _tool_job(sample, FASTP_JOB, tool, params.as_dict(), inputs, res.record(params.threads))
    db.add(job)
    db.commit()
    _enqueue([job], run_fastp_job)
    db.refresh(job)
    return job


def create_filtlong_job(db: Session, sample: Sample, f: RawFile, params: FiltlongParams) -> AnalysisJob:
    from app.tasks.tools import run_filtlong_job

    params.validate()
    tool = require_tool("filtlong")
    job = _tool_job(sample, FILTLONG_JOB, tool, params.as_dict(), [f.id], effective_resources(db).record(1))
    db.add(job)
    db.commit()
    _enqueue([job], run_filtlong_job)
    db.refresh(job)
    return job


def create_flye_job(db: Session, sample: Sample, files: list[RawFile], params: FlyeParams,
                    provenance: dict) -> AnalysisJob:
    """One assembly job; `provenance` (request evidence such as ARVA's read-type suggestion) is stored with the
    parameters and never passed to Flye."""
    from app.tasks.tools import run_flye_job

    tool = require_tool("flye")
    try:
        supported = FlyeAdapter.help_options(tool.path or "flye")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailableError(f"Flye's --help could not be read to check its options: {exc}") from exc
    res = effective_resources(db)
    params.threads = res.cap_threads(params.threads)
    params.validate(supported)
    job = _tool_job(sample, FLYE_JOB, tool, {**params.as_dict(), **provenance}, [f.id for f in files],
                    res.record(params.threads))
    db.add(job)
    db.commit()
    _enqueue([job], run_flye_job)
    db.refresh(job)
    return job


def _check_memory(res: Resources, name: str, gb: int) -> None:
    if gb > res.max_memory_gb:
        raise ValueError(f"{name} is {gb} GB, more than the {res.max_memory_gb} GB ARVA may give a tool here (the "
                         "memory ARVA can use, or ARVA_TOOL_MEMORY_GB)")


def _cap_resources(params: SpadesParams | UnicyclerParams, memory_field: str, res: Resources) -> None:
    params.threads = res.cap_threads(params.threads)
    _check_memory(res, memory_field, getattr(params, memory_field))


def _supported(read_options, tool: DetectedTool, name: str) -> frozenset[str]:
    try:
        return read_options(tool.path or name)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailableError(f"{tool.info.name}'s help could not be read to check its options: {exc}") from exc


def create_spades_job(db: Session, sample: Sample, inputs: dict[str, RawFile | None], params: SpadesParams,
                      provenance: dict) -> AnalysisJob:
    """One SPAdes run; `inputs` maps the roles r1, r2 and unpaired to their files (recorded with the parameters, in
    that order as the job's inputs)."""
    from app.tasks.tools import run_spades_job

    tool = require_tool("spades")
    supported = _supported(SpadesAdapter.help_options, tool, "spades.py")
    res = effective_resources(db)
    _cap_resources(params, "memory_gb", res)
    params.validate()
    paired, unpaired = inputs.get("r1") is not None, inputs.get("unpaired") is not None
    if missing := [f for f in params.flags(paired, unpaired) if f not in supported]:
        raise ValueError(f"this SPAdes version does not offer {', '.join(missing)} (not in its --help)")
    roles = {r: f.id if f else None for r, f in inputs.items()}
    job = _tool_job(sample, SPADES_JOB, tool, {**params.as_dict(), "inputs": roles, **provenance},
                    [f.id for f in inputs.values() if f is not None], res.record(params.threads, params.memory_gb, "-m"))
    db.add(job)
    db.commit()
    _enqueue([job], run_spades_job)
    db.refresh(job)
    return job


def create_unicycler_job(db: Session, sample: Sample, inputs: dict[str, RawFile | None], params: UnicyclerParams,
                         provenance: dict) -> AnalysisJob:
    """One Unicycler run; `inputs` maps the roles r1, r2, unpaired and long to their files."""
    from app.tasks.tools import run_unicycler_job

    tool = require_tool("unicycler")
    supported = _supported(UnicyclerAdapter.help_options, tool, "unicycler")
    res = effective_resources(db)
    _cap_resources(params, "spades_memory_gb", res)
    params.validate()
    paths = helper_paths()
    needed = ["makeblastdb", "tblastn"] + (["spades"] if params.short else []) + (["racon"] if params.long else [])
    if missing := [n for n in needed if not paths[n]]:
        raise ToolUnavailableError(f"Unicycler needs {', '.join(missing)} for a {params.assembly_mode}-read assembly, "
                                   "and it was not found. Install it (spades, racon, ncbi-blast+)")
    paired, unpaired = inputs.get("r1") is not None, inputs.get("unpaired") is not None
    if missing := [f for f in params.flags(paired, unpaired) if f not in supported]:
        raise ValueError(f"this Unicycler version does not offer {', '.join(missing)} (not in its --help_all)")
    roles = {r: f.id if f else None for r, f in inputs.items()}
    memory = (params.spades_memory_gb, "--spades_options -m") if params.short else (None, None)
    job = _tool_job(sample, UNICYCLER_JOB, tool, {**params.as_dict(), "inputs": roles, **provenance},
                    [f.id for f in inputs.values() if f is not None], res.record(params.threads, *memory))
    db.add(job)
    db.commit()
    _enqueue([job], run_unicycler_job)
    db.refresh(job)
    return job


def new_quast_job(sample: Sample, assemblies: list[Assembly], labels: dict[str, str], reference: RawFile | None,
                  params: QuastParams, res: Resources, parent_job_id: str | None = None) -> AnalysisJob:
    """A pending QUAST job over the sample's chosen assemblies (and reference), not yet added to a session; the
    assemblies and their labels are recorded in the parameters, the reference file as the job's input."""
    tool = require_tool("quast")
    try:
        supported = QuastAdapter.help_options(tool.path or "quast.py")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailableError(f"QUAST's --help could not be read to check its options: {exc}") from exc
    params.threads = res.cap_threads(params.threads)
    params.validate()
    if missing := [f for f in quast_flags(reference is not None, False) if f not in supported]:
        raise ValueError(f"this QUAST version does not offer {', '.join(missing)} (not in its --help)")
    if reference is not None and aligner(tool.path or "quast.py")["provided_by"] == "missing":
        raise ToolUnavailableError("QUAST needs minimap2 2.19 or later on PATH to align contigs to a reference (ARVA "
                                   "does not let QUAST compile its own copy during a run). Install minimap2, or "
                                   "evaluate without a reference")
    parameters = {
        **params.as_dict(),
        "reference_file_id": reference.id if reference else None,
        "assemblies": [{"assembly_id": a.id, "label": labels[a.id], "assembler": a.assembler,
                        "assembler_version": a.assembler_version, "assembly_job_id": a.job_id,
                        "contigs_sha256": a.stats["files"]["contigs"]["sha256"]} for a in assemblies],
    }
    job = _tool_job(sample, QUAST_JOB, tool, parameters, [reference.id] if reference else [], res.record(params.threads))
    job.parent_job_id = parent_job_id
    return job


def enqueue_quast(jobs: list[AnalysisJob]) -> None:
    from app.tasks.tools import run_quast_job

    _enqueue(jobs, run_quast_job)


def create_quast_job(db: Session, sample: Sample, assemblies: list[Assembly], labels: dict[str, str],
                     reference: RawFile | None, params: QuastParams) -> AnalysisJob:
    """One QUAST run over the sample's chosen assemblies (and reference)."""
    job = new_quast_job(sample, assemblies, labels, reference, params, effective_resources(db))
    db.add(job)
    db.commit()
    enqueue_quast([job])
    db.refresh(job)
    return job


def create_server_import_job(db: Session, sample: Sample, root: Path, paths: list[str]) -> AnalysisJob:
    """One job copies every selected file of a server folder into the sample."""
    from app.tasks.server_import import run_server_import_job

    job = AnalysisJob(
        project_id=sample.project_id,
        sample_id=sample.id,
        job_type=SERVER_IMPORT_JOB,
        tool_name=SERVER_IMPORT_TOOL,
        tool_version=__version__,
        parameters={"root": str(root), "paths": paths},
        input_raw_file_ids=[],
        status=JobStatus.pending,
        log_text="",
    )
    db.add(job)
    db.commit()
    _enqueue([job], run_server_import_job)
    db.refresh(job)
    return job


def create_pod5_jobs(db: Session, sample: Sample, files: list[RawFile]) -> list[AnalysisJob]:
    """One run-metadata job per POD5 file, read by the worker with the optional pod5 library."""
    from app.tasks.pod5_summary import run_pod5_summary_job

    versions = pod5_versions()
    if versions["pod5"] is None:
        raise ToolUnavailableError(
            f"The optional pod5 library is not installed in ARVA's Python environment. Install it with: {POD5_INSTALL}"
        )
    jobs = [
        AnalysisJob(
            project_id=sample.project_id,
            sample_id=sample.id,
            job_type=POD5_JOB,
            tool_name=POD5_TOOL,
            tool_version=versions["pod5"],
            parameters={"lib_pod5_version": versions["lib_pod5"], "signal_decoded": False},
            input_raw_file_ids=[f.id],
            status=JobStatus.pending,
            log_text="",
        )
        for f in files
    ]
    db.add_all(jobs)
    db.commit()
    _enqueue(jobs, run_pod5_summary_job)
    for job in jobs:
        db.refresh(job)
    return jobs


def create_multiqc_job(db: Session, project: Project, parameters: dict, file_ids: list[str]) -> AnalysisJob:
    """One project-level job: the inputs were chosen in the request and are recorded in `parameters`."""
    from app.tasks.tools import run_multiqc_job

    tool = require_tool("multiqc")
    job = AnalysisJob(
        project_id=project.id,
        sample_id=None,
        job_type=MULTIQC_JOB,
        tool_name=tool.info.name,
        tool_version=tool.version or "unknown",
        tool_path=tool.path,
        parameters=parameters,
        input_raw_file_ids=file_ids,
        status=JobStatus.pending,
        log_text="",
        # MultiQC takes no thread count.
        resources=effective_resources(db).record(None),
    )
    db.add(job)
    db.commit()
    _enqueue([job], run_multiqc_job)
    db.refresh(job)
    return job


# --- Polishing ------------------------------------------------------------------------------------------------

def draft_record(a: Assembly) -> dict:
    """What a polishing job records about the assembly it polishes (checked again before the run)."""
    return {"assembly_id": a.id, "kind": a.kind.value, "assembler": a.assembler,
            "assembler_version": a.assembler_version, "job_id": a.job_id, "mode": a.mode.value,
            "contigs_sha256": a.stats["files"]["contigs"]["sha256"]}


def _check_flags(read_options, tool: DetectedTool, flags: tuple[str, ...], *args) -> None:
    try:
        supported = read_options(*args)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailableError(f"{tool.info.name}'s --help could not be read to check its options: {exc}") from exc
    if missing := [f for f in flags if f not in supported]:
        raise ValueError(f"this {tool.info.name} version does not offer {', '.join(missing)} (not in its --help)")


def new_racon_job(sample: Sample, draft: Assembly, reads: RawFile, params: RaconParams, extra: dict, res: Resources,
                  parent_job_id: str | None = None) -> AnalysisJob:
    """A pending Racon polishing job (minimap2 overlaps, Racon rounds, comparisons), not yet added to a session."""
    tool = require_tool("racon")
    for helper in ("minimap2", "samtools"):
        require_tool(helper)
    _check_flags(RaconAdapter.help_options, tool, RACON_FLAGS, tool.path or "racon")
    params.threads = res.cap_threads(params.threads)
    params.validate()
    # Racon and minimap2 take no memory limit; samtools sort gets one per thread from memory_gb in the worker.
    job = _tool_job(sample, RACON_JOB, tool, {**params.as_dict(), "draft": draft_record(draft),
                                              "inputs": {"long": reads.id}, **extra}, [reads.id],
                    res.record(params.threads))
    job.parent_job_id = parent_job_id
    return job


def new_pilon_job(sample: Sample, draft: Assembly, inputs: dict[str, RawFile | None], params: PilonParams, extra: dict,
                  res: Resources, parent_job_id: str | None = None) -> AnalysisJob:
    """A pending Pilon polishing job (BWA-MEM alignments, Pilon rounds, comparisons); `inputs` maps r1, r2 and
    unpaired to their files."""
    tool = require_tool("pilon")
    for helper in ("bwa", "samtools"):
        require_tool(helper)
    java = java_executable()
    if java is None or not tool.path:
        raise ToolUnavailableError("Pilon needs Java, which was not found")
    _check_flags(PilonAdapter.help_options, tool, PILON_FLAGS, java, tool.path)
    params.threads = res.cap_threads(params.threads)
    _check_memory(res, "heap_gb", params.heap_gb)
    params.validate()
    roles = {r: f.id if f else None for r, f in inputs.items()}
    job = _tool_job(sample, PILON_JOB, tool, {**params.as_dict(), "draft": draft_record(draft), "inputs": roles, **extra},
                    [f.id for f in inputs.values() if f is not None], res.record(params.threads, params.heap_gb, "-Xmx"))
    job.parent_job_id = parent_job_id
    return job


def enqueue_polishing(jobs: list[AnalysisJob]) -> None:
    from app.tasks.polishing import run_pilon_job, run_racon_job

    for job in jobs:
        _enqueue([job], run_racon_job if job.job_type == RACON_JOB else run_pilon_job)


def create_polishing_job(db: Session, sample: Sample, draft: Assembly, strategy: str, inputs: dict[str, RawFile | None],
                         racon: RaconParams | None, pilon: PilonParams | None, extra: dict) -> AnalysisJob:
    """The first job of a polishing strategy: Racon (long reads), Pilon (short reads), or Racon whose completion
    queues Pilon on its result (hybrid; the Pilon settings and reads are stored in the Racon job as `then_pilon`).
    Every tool of the strategy is checked now, so a hybrid run does not stop half-way for a missing Pilon."""
    short = {r: inputs.get(r) for r in ("r1", "r2", "unpaired")}
    long = inputs.get("long")
    if (strategy != "pilon" and (racon is None or long is None)) or (strategy != "racon" and pilon is None):
        raise ValueError(f"the {strategy} strategy needs its settings and reads")
    extra = {**extra, "strategy": strategy}
    res = effective_resources(db)
    pilon_job = new_pilon_job(sample, draft, short, pilon, extra, res) if pilon is not None and strategy != "racon" else None
    if strategy == "pilon":
        job = pilon_job
    else:
        then = None
        if strategy == "hybrid":
            then = {"params": pilon.as_dict(), "inputs": {r: f.id if f else None for r, f in short.items()}}
        job = new_racon_job(sample, draft, long, racon, {**extra, "then_pilon": then}, res)
    db.add(job)
    db.commit()
    enqueue_polishing([job])
    db.refresh(job)
    return job


# --- Annotation -----------------------------------------------------------------------------------------------

def create_bakta_job(db: Session, sample: Sample, assembly: Assembly, params: BaktaParams, record: ReferenceDatabase,
                     plan: dict, provenance: dict) -> AnalysisJob:
    """One Bakta run of an assembly with an installed database. `plan` is the preview the user confirmed: the
    worker checks the programs again and refuses to run if the steps that can run have changed since."""
    from app.services.databases import record_use
    from app.tasks.annotation import run_bakta_job

    tool = require_tool("bakta")
    res = effective_resources(db)
    params.threads = res.cap_threads(params.threads)
    params.validate()
    _check_flags(BaktaAdapter.help_options, tool, tuple(bakta_flags(params, plan["skip_options"])), tool.path or "bakta")
    parameters = {**params.as_dict(), "assembly": assembly_record(assembly), "steps": plan["steps"],
                  "skip_options": plan["skip_options"], "dependencies": plan["dependencies"], **provenance}
    # Bakta has no memory option.
    job = _tool_job(sample, BAKTA_JOB, tool, parameters, [], res.record(params.threads))
    record_use(job, record)
    db.add(job)
    db.commit()
    _enqueue([job], run_bakta_job)
    db.refresh(job)
    return job


def create_prokka_job(db: Session, sample: Sample, assembly: Assembly, params: ProkkaParams, plan: dict,
                      provenance: dict) -> AnalysisJob:
    """One Prokka run of an assembly with the databases of Debian's package (indexed in the job's folder)."""
    from app.tasks.annotation import run_prokka_job

    tool = require_tool("prokka")
    res = effective_resources(db)
    params.threads = res.cap_threads(params.threads)
    params.validate()
    _check_flags(ProkkaAdapter.help_options, tool, tuple(prokka_flags(params)), tool.path or "prokka")
    database = plan["database"]
    parameters = {**params.as_dict(), "assembly": assembly_record(assembly), "steps": plan["steps"],
                  "database": {k: database.get(k) for k in ("path", "package", "files", "genera", "hmm")},
                  "programs": plan["programs"], **provenance}
    job = _tool_job(sample, PROKKA_JOB, tool, parameters, [], res.record(params.threads))
    job.database_key, job.database_name = database["key"], database["name"]
    job.database_version, job.database_checksum = database["version"], database["checksum"]
    db.add(job)
    db.commit()
    _enqueue([job], run_prokka_job)
    db.refresh(job)
    return job


def create_mlst_job(db: Session, sample: Sample, assembly: Assembly, params: MlstParams, record: ReferenceDatabase,
                    provenance: dict) -> AnalysisJob:
    """One mlst run of an assembly with the PubMLST schemes mlst bundles (recorded as a read-only database)."""
    from app.services.databases import record_use
    from app.tasks.mlst import run_mlst_job

    tool = require_tool("mlst")
    res = effective_resources(db)
    params.threads = res.cap_threads(params.threads)
    params.validate()
    _check_flags(MlstAdapter.help_options, tool, tuple(mlst_flags(params)), tool.path or "mlst")
    parameters = {**params.as_dict(), "assembly": assembly_record(assembly), **provenance}
    job = _tool_job(sample, MLST_JOB, tool, parameters, [], res.record(params.threads))
    record_use(job, record)
    db.add(job)
    db.commit()
    _enqueue([job], run_mlst_job)
    db.refresh(job)
    return job


def create_species_job(db: Session, sample: Sample, assembly: Assembly, method: str, threads: int | None,
                       record: ReferenceDatabase, provenance: dict) -> AnalysisJob:
    """One species identification of an assembly with one method against one database (record_use keeps its kind,
    version, version source, checksum and path on the job)."""
    from arva_tools import gtdbtk as gtdbtk_tool

    from app.services.databases import record_use
    from app.services.species import METHODS
    from app.tasks.species import ADAPTERS, FLAGS, PARAMS, run_species_job

    tool_id = METHODS[method]["tool"]
    tool = require_tool(tool_id)
    res = effective_resources(db)
    if method == "gtdbtk" and res.memory_gb < gtdbtk_tool.REQUIRED_MEMORY_GB:
        raise ValueError(f"GTDB-Tk needs about {gtdbtk_tool.REQUIRED_MEMORY_GB} GB of memory; the performance profile "
                         f"gives a run {res.memory_gb} GB")
    params = PARAMS[method](threads=res.cap_threads(threads or res.threads))
    params.validate()
    _check_flags(ADAPTERS[method].help_options, tool, FLAGS[method], tool.path or tool_id)
    parameters = {"method": method, "settings": params.as_dict(), "assembly": assembly_record(assembly),
                  **provenance}
    job = _tool_job(sample, SPECIES_JOB, tool, parameters, [], res.record(params.threads))
    record_use(job, record)
    db.add(job)
    db.commit()
    _enqueue([job], run_species_job)
    db.refresh(job)
    return job


# --- Cancellation and resuming ---------------------------------------------------------------------------------

ACTIVE = (JobStatus.pending, JobStatus.running)
# RQ statuses of a task no worker is executing any more.
_NOT_EXECUTING = {"finished", "failed", "stopped", "canceled"}


def task_status(rq_id: str) -> str | None:
    """RQ's status of a task, "missing" when Redis no longer holds it, None when Redis cannot be asked."""
    try:
        status = RqJob.fetch(rq_id, connection=get_queue().connection).get_status()
        return str(getattr(status, "value", status)) if status else "missing"
    except NoSuchJobError:
        return "missing"
    except (RedisError, InvalidJobOperation):
        return None


def cancel_task(rq_id: str) -> None:
    try:
        RqJob.fetch(rq_id, connection=get_queue().connection).cancel()
    except (NoSuchJobError, InvalidJobOperation, RedisError):
        pass


def _rq_status(job_id: str) -> str | None:
    return task_status(_rq_id(job_id))


def _write_log(job: AnalysisJob, line: str) -> None:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    job.log_text = ((job.log_text + "\n") if job.log_text else "") + f"[{stamp}] {line}"


def _finish_without_worker(db: Session, job: AnalysisJob, note: str) -> None:
    from app.tasks.common import cancellation_note

    storage = get_storage()
    scope = f"{job.project_id}/{job.sample_id or '_project'}/{job.id}"
    for rel in (f"results/{scope}", f"processed/{scope}"):
        storage.remove_tree(rel)
    job.status = JobStatus.cancelled
    job.finished_at = datetime.now(UTC)
    if job.started_at is not None:
        job.duration_seconds = round((job.finished_at - job.started_at).total_seconds(), 3)
    _write_log(job, f"{cancellation_note(job)}; {note}")
    _write_log(job, "Finished with status 'cancelled'")
    db.commit()
    storage.write_text(f"logs/{job.id}.log", job.log_text or "")


def cancel_job(db: Session, job_id: str) -> AnalysisJob:
    """Cancel a queued or running job. A queued job is cancelled at once and removed from the task queue. For a
    running one the request is recorded and the worker stops the tool (its whole process group) within a few
    seconds, then removes partial outputs as for a failure; the job stays 'running' until then. A 'running' job
    that, according to the task queue, no worker executes any more (the worker died) is cancelled at once."""
    job = db.get(AnalysisJob, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        raise LookupError(job_id)
    if job.status not in ACTIVE:
        raise JobStateError(f"This job has already finished (status '{job.status.value}'); there is nothing to cancel")
    if job.cancel_requested_at is None:
        job.cancel_requested_at = datetime.now(UTC)
    if job.status is JobStatus.pending:
        _finish_without_worker(db, job, "it was cancelled before a worker started it, so nothing was run")
        cancel_task(_rq_id(job.id))
        return job
    state = _rq_status(job.id)
    if state in _NOT_EXECUTING or state == "missing":
        _finish_without_worker(db, job, f"no worker was running it any more (task queue status: {state}), so ARVA "
                                        "ended the record and removed its partial outputs; no work folder was kept")
        return job
    db.commit()
    return job


def _active_resume(db: Session, job: AnalysisJob) -> AnalysisJob | None:
    jobs = db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == job.sample_id,
                                                AnalysisJob.job_type == FLYE_JOB, AnalysisJob.status.in_(ACTIVE)))
    return next((j for j in jobs if ((j.parameters or {}).get("resume") or {}).get("of_job_id") == job.id), None)


def _checkpoint_of(db: Session, job: AnalysisJob) -> dict:
    kept = job.checkpoint
    if job.job_type != FLYE_JOB or job.status not in (JobStatus.failed, JobStatus.cancelled) or not kept:
        raise JobStateError("This job kept no Flye work folder to resume from")
    if other := _active_resume(db, job):
        raise JobStateError(f"Job {other.id} is already resuming this run")
    return kept


def resume_flye_job(db: Session, job: AnalysisJob) -> AnalysisJob:
    """A new Flye job that continues a stopped run from its kept work folder with Flye's own --resume: the same
    reads, options and thread count, and the same Flye version (Flye does not check either)."""
    from app.tasks.tools import run_flye_job

    kept = _checkpoint_of(db, job)
    found = read_checkpoint(get_storage().resolve(kept["path"]), tuple(kept["stages"]))
    if found is None or found["resume_stage"] != kept["resume_stage"]:
        raise JobStateError("The kept Flye work folder is missing or has changed on disk; discard it and start a "
                            "new assembly")
    tool = require_tool("flye")
    if tool.version != kept["tool_version"]:
        raise JobStateError(f"The work folder was written by Flye {kept['tool_version']} and Flye {tool.version} is "
                            "installed now. Flye does not check this, and one run made by two versions could not be "
                            "described by either, so ARVA resumes only with the same version; start a new assembly")
    try:
        supported = FlyeAdapter.help_options(tool.path or "flye")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ToolUnavailableError(f"Flye's --help could not be read to check its options: {exc}") from exc
    if "--resume" not in supported:
        raise ToolUnavailableError("this Flye version does not offer --resume (not in its --help)")
    params = FlyeParams.from_dict(job.parameters or {})
    params.validate(supported)
    res = effective_resources(db)
    if params.threads > res.max_threads:
        raise JobStateError(f"The run used {params.threads} threads, more than ARVA may now give a tool "
                            f"({res.max_threads}: the CPUs ARVA can use, or ARVA_TOOL_THREADS). Flye's output can "
                            "depend on the thread count, so ARVA resumes only with the same one")
    files = [db.get(RawFile, fid) for fid in job.input_raw_file_ids or []]
    if not files or any(f is None for f in files):
        raise JobStateError("A read file of the stopped run no longer exists, so it cannot be resumed")
    sample = db.get(Sample, job.sample_id)
    parameters = {k: v for k, v in (job.parameters or {}).items() if k != "resume"}
    parameters["resume"] = {"of_job_id": job.id, "checkpoint_path": kept["path"], "stage": kept["resume_stage"],
                            "completed_stages": kept["completed_stages"]}
    new = _tool_job(sample, FLYE_JOB, tool, parameters, list(job.input_raw_file_ids or []), res.record(params.threads))
    db.add(new)
    db.commit()
    _enqueue([new], run_flye_job)
    db.refresh(new)
    return new


def discard_checkpoint(db: Session, job: AnalysisJob) -> AnalysisJob:
    """Delete the Flye work folder a stopped run kept for resuming."""
    kept = _checkpoint_of(db, job)
    storage = get_storage()
    storage.remove_tree(kept["path"])
    try:
        storage.resolve(kept["path"]).parent.rmdir()
    except OSError:
        pass
    job.checkpoint = None
    _write_log(job, f"Discarded the kept Flye work folder ({kept['size_bytes']:,} bytes); this run can no longer be "
                    "resumed")
    db.commit()
    storage.write_text(f"logs/{job.id}.log", job.log_text or "")
    return job
