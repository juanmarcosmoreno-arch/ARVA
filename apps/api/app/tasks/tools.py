"""Worker tasks that run external tools through their ARVA adapters.

Each task records the resolved executable, detected version, exact argument
vectors and tool logs. Filtering tasks register their outputs as *derived*
files linked to the input file and job, then queue ARVA statistics for them so
the before/after comparison uses identical methods on both sides.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path

from arva_core.assembly_stats import AssemblyFormatError, ContigAnnotation, min_length_summary
from arva_core.formats import is_gzip
from arva_core.seqstats import SequenceFormatError, StatsParameters, quick_validate
from arva_tools import (
    SIGKILL_STATUSES,
    ToolExecutionError,
    ToolStatus,
    ToolTimeoutError,
    nice_prefix,
    run_command,
)
from arva_tools.fastp import FastpAdapter, FastpParams, removed_reads
from arva_tools.fastqc import DATA_JSON as FASTQC_DATA_JSON
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import ENVIRONMENT as FILTLONG_ENVIRONMENT
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams, plain_counts
from arva_tools.flye import OUTPUTS as FLYE_OUTPUTS
from arva_tools.flye import (
    SAMTOOLS_HELPER,
    STAGE_DIRS,
    FlyeAdapter,
    FlyeParams,
    helper_version,
    read_checkpoint,
    read_link_name,
    samtools_helper,
)
from arva_tools.multiqc import (
    DATA_DIR,
    DATA_JSON,
    ENVIRONMENT,
    REPORT_FILENAME,
    SOURCES_FILE,
    VERSIONS_FILE,
    MultiqcAdapter,
    ReportInput,
    staged_name,
)
from arva_tools.nanoplot import (
    NanoplotAdapter,
    browser_traces,
    input_name,
    output_names,
    output_prefix,
)
from arva_tools.quast import (
    CONSOLE_LOG,
    ICARUS_DIR,
    ICARUS_HTML,
    LOG,
    OUT_DIR,
    REPORT_HTML,
    REPORT_TSV,
    REQUIRED_OUTPUTS,
    TRANSPOSED_TSV,
    QuastAdapter,
    QuastParams,
    aligner,
)
from arva_tools.quast import input_name as quast_input_name
from arva_tools.quast import stages as quast_stages
from arva_tools.registry import detect
from arva_tools.seqkit import SeqkitAdapter
from arva_tools.spades import OUTPUTS as SPADES_OUTPUTS
from arva_tools.spades import PLAN_FILE as SPADES_PLAN
from arva_tools.spades import SpadesAdapter, SpadesParams, parse_node_name
from arva_tools.unicycler import OUTPUTS as UNICYCLER_OUTPUTS
from arva_tools.unicycler import SPADES_DIR, UnicyclerAdapter, UnicyclerParams, helper_paths

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import (
    AnalysisJob,
    Assembly,
    AssemblyMode,
    FileFormat,
    FileOrigin,
    JobStatus,
    Project,
    RawFile,
)
from app.services.assemblies import MAX_CONTIG_ROWS, register_assembly
from app.services.imports import header_metadata
from app.services.quast import crosscheck
from app.services.short_hybrid import ROLES, library_layout
from app.tasks.common import JobCancelled, JobContext, JobFailure, now, run_job

# How often a running tool's log is read and the job's progress saved.
MONITOR_SECONDS = 5.0


def _resolve_tool(ctx: JobContext, tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available or not d.path:
        raise JobFailure(f"{d.info.name} is not available on this worker ({d.status.value}): {d.message}",
                         "tool_unavailable", tool=d.info.name, status=d.status.value, message=d.message)
    if d.version != ctx.job.tool_version:
        ctx.log(f"Note: version detected at run time is {d.version} (was {ctx.job.tool_version} when queued)")
        ctx.job.tool_version = d.version or "unknown"
    ctx.job.tool_path = d.path
    if not d.version_validated:
        ctx.log(f"WARNING: {d.message}")
    ctx.log(f"Executable: {d.path} (version {d.version})")
    return d.path


def _priority(ctx: JobContext) -> int:
    """The CPU priority the job was given (its profile's nice value), noted in the log and in job.resources at the
    first command; 0 when the job records none or `nice` is not installed."""
    resources = ctx.job.resources or {}
    nice = resources.get("nice") or 0
    if not nice:
        return 0
    if "nice_executable" not in resources:
        prefix = nice_prefix(nice)
        resources = ctx.job.resources = {**resources, "nice_executable": prefix[0] if prefix else None}
        ctx.log(f"CPU priority: tools start through {shlex.join(prefix)} ({resources.get('profile')} performance "
                "profile); the commands below are the tools' own" if prefix else
                f"CPU priority: the nice executable was not found, so tools run at normal priority (the "
                f"{resources.get('profile')} profile asks for nice {nice})")
    return nice if resources["nice_executable"] else 0


def _run(ctx: JobContext, argv: list[str], workdir: Path, log_name: str, stdout: Path | None = None,
         extra_env: Mapping[str, str] | None = None, log_dir: Path | None = None, home: Path | None = None,
         monitor: Callable[[], None] | None = None) -> Path:
    nice = _priority(ctx)
    ctx.job.commands = [*(ctx.job.commands or []), argv]
    inherited = os.environ.get("PATH", "")
    env_note = "".join(f"{k}={v.replace(inherited, '$PATH') if k == 'PATH' and inherited else v} "
                       for k, v in (extra_env or {}).items())
    ctx.log("Command: " + env_note + shlex.join(argv) + (f" > {stdout.name}" if stdout else ""), flush=True)
    ctx.check_cancelled()
    log_path = (log_dir or workdir) / log_name

    def watch() -> None:
        ctx.check_cancelled()
        if monitor is not None:
            monitor()

    try:
        result = run_command(argv, cwd=workdir, stderr_path=log_path, stdout_path=stdout,
                             timeout_seconds=get_settings().tool_timeout_seconds, extra_env=extra_env, home=home,
                             monitor=watch, monitor_seconds=MONITOR_SECONDS, nice=nice)
    except ToolExecutionError as exc:
        # ARVA's own stops (cancellation, time limit) raise other exceptions; a SIGKILL from outside is most often the
        # kernel's out-of-memory killer.
        if not isinstance(exc, ToolTimeoutError) and exc.returncode in SIGKILL_STATUSES:
            ctx.killed_tool = Path(argv[0]).name
        raise
    ctx.log(f"{Path(argv[0]).name} finished in {result.duration_seconds:.1f}s")
    return log_path


def _stem(raw: RawFile) -> str:
    name = re.sub(r"\.(gz)$", "", raw.original_filename, flags=re.I)
    name = re.sub(r"\.(fastq|fq|fasta|fa|fna|fas)$", "", name, flags=re.I)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "reads"


def _rel(ctx: JobContext, path: Path) -> str:
    return str(path.relative_to(ctx.storage.root))


def _register_derived(ctx: JobContext, parent: RawFile, rel: str, name: str, description: str) -> RawFile:
    stored = ctx.storage.seal(rel)
    check = quick_validate(ctx.path(rel))
    derived = RawFile(
        id=new_uuid(),
        sample_id=parent.sample_id,
        original_filename=name,
        stored_path=rel,
        file_format=FileFormat.fastq_gz if check.compressed else FileFormat.fastq,
        read_mate=parent.read_mate,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.sha256,
        is_valid=check.is_valid,
        validation_message=check.message,
        validation_detail={"code": check.code, "params": check.params},
        header_metadata=header_metadata(check.headers),
        origin=FileOrigin.derived,
        parent_file_id=parent.id,
        produced_by_job_id=ctx.job.id,
        description=description,
    )
    ctx.db.add(derived)
    ctx.log(f"Derived file: {name} ({stored.size_bytes} bytes, sha256 {stored.sha256})")
    return derived


def _queue_stats_after(ctx: JobContext, parents: list[RawFile], derived: list[RawFile]) -> None:
    """Create ARVA statistics jobs for the outputs (and for inputs lacking them) in the same
    transaction that completes this job, then enqueue them once it is committed. Clients
    therefore never observe a moment where the filter is done but no follow-up work exists."""
    from app.services.jobs import (
        enqueue_sequence_stats,
        files_without_stats,
        new_sequence_stats_job,
    )

    ctx.db.flush()
    params = StatsParameters().as_dict()
    targets = files_without_stats(ctx.db, ctx.job.sample_id, parents) + derived
    jobs = [new_sequence_stats_job(ctx.job.sample, f.id, params, ctx.job.id) for f in targets]
    ctx.db.add_all(jobs)
    ctx.after_commit.append(lambda: enqueue_sequence_stats(jobs))


def _log_inputs(ctx: JobContext, files: list[RawFile]) -> None:
    for f in files:
        ctx.log(f"Input: {f.original_filename} ({f.size_bytes} bytes, sha256 {f.checksum_sha256})")


# --- SeqKit -------------------------------------------------------------------

def _seqkit_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "seqkit")
    (f,) = ctx.input_files()
    _log_inputs(ctx, [f])
    workdir = ctx.path(ctx.results_rel)
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "seqkit_stats.tsv"
    threads = int((ctx.job.parameters or {}).get("threads", 2))
    log = _run(ctx, SeqkitAdapter.stats_argv(exe, [ctx.path(f.stored_path)], threads), workdir,
               "seqkit.stderr.log", stdout=out)
    rows = SeqkitAdapter.parse_stats(out.read_text())
    if len(rows) != 1:
        raise JobFailure(f"expected one row from seqkit stats, got {len(rows)}")
    ctx.job.result_summary = {"seqkit_stats": rows[0]}
    ctx.job.output_paths = [_rel(ctx, out), _rel(ctx, log)]


def run_seqkit_job(job_id: str) -> str:
    return run_job(job_id, _seqkit_body)


# --- FastQC -------------------------------------------------------------------

def _fastqc_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "fastqc")
    (f,) = ctx.input_files()
    _log_inputs(ctx, [f])
    workdir = ctx.path(ctx.results_rel)
    tmp = workdir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    # FastQC names its report after the input file; a symlink carries the user's filename
    # instead of ARVA's internal storage name.
    link_dir = workdir / "input"
    link_dir.mkdir(exist_ok=True)
    src = link_dir / re.sub(r"[^A-Za-z0-9._-]+", "_", f.original_filename)
    src.symlink_to(ctx.path(f.stored_path))
    log = _run(ctx, FastqcAdapter.argv(exe, src, workdir, tmp), workdir, "fastqc.log")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(link_dir, ignore_errors=True)
    html_name, zip_name = FastqcAdapter.output_names(src.name)
    html, zipf = workdir / html_name, workdir / zip_name
    if not html.exists() or not zipf.exists():
        raise JobFailure("FastQC finished but its report files were not found")
    try:
        summary = FastqcAdapter.parse_zip(zipf)
        data = FastqcAdapter.read_data(zipf)
    except ValueError as exc:
        raise JobFailure(f"FastQC exited without an error but its results could not be read: {exc}",
                         "output_unreadable", tool="FastQC", detail=str(exc)) from exc
    if data["unrecognised"]:
        ctx.log("FastQC modules whose columns ARVA does not recognise (not charted): " + ", ".join(data["unrecognised"]))
    data_json = workdir / FASTQC_DATA_JSON
    data_json.write_text(json.dumps(data))
    ctx.job.result_summary = {**summary, "data_summary": FastqcAdapter.summarize(data)}
    ctx.job.output_paths = [_rel(ctx, html), _rel(ctx, zipf), _rel(ctx, data_json), _rel(ctx, log)]


def run_fastqc_job(job_id: str) -> str:
    return run_job(job_id, _fastqc_body)


# --- NanoPlot -------------------------------------------------------------------

def _nanoplot_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "nanoplot")
    (f,) = ctx.input_files()
    _log_inputs(ctx, [f])
    results = ctx.path(ctx.results_rel)
    prefix = output_prefix(f.original_filename)
    names = output_names(prefix)
    # nanoget picks its reader from the file extension only; ARVA detects gzip from the content.
    link = results / "input" / input_name(prefix, f.file_format is FileFormat.fastq_gz)
    work, home = results / "work", results / "home"
    for d in (link.parent, work, home):
        d.mkdir(parents=True)
    link.symlink_to(ctx.path(f.stored_path))
    argv = NanoplotAdapter.argv(exe, link, results, prefix, int((ctx.job.parameters or {}).get("threads", 1)))
    try:
        stderr_log = _run(ctx, argv, work, "nanoplot.stderr.log", log_dir=results, home=home)
    except ToolExecutionError as exc:
        fatal = next((line.strip() for line in exc.stderr_tail.splitlines() if line.startswith("FATAL")), None)
        if fatal is None:
            raise
        raise ToolExecutionError(f"{exc}: {fatal}", exc.returncode, exc.stderr_tail) from None
    finally:
        shutil.rmtree(link.parent, ignore_errors=True)

    traces = browser_traces(home)
    if traces:
        raise JobFailure("NanoPlot created web-browser files in its home folder (" + ", ".join(traces[:5]) + "). "
                         "ARVA runs it with --no_static so that it never downloads or starts Chrome; the results "
                         "were discarded")
    if other := sorted(p.name for p in home.iterdir()):
        ctx.log(f"Note: NanoPlot wrote to its empty home folder: {', '.join(other)}")
    shutil.rmtree(work)
    shutil.rmtree(home)

    stats, report, post_path = results / names.stats, results / names.report, results / names.post_filtering
    logs = sorted(results.glob(names.log_glob))
    if not stats.is_file() or not report.is_file() or len(logs) != 1:
        raise JobFailure("NanoPlot exited without an error but did not write NanoStats.txt, its HTML report and "
                         "one log file; see the log")
    try:
        pre = NanoplotAdapter.parse_stats(stats.read_text())
        post = NanoplotAdapter.parse_stats(post_path.read_text()) if post_path.is_file() else None
    except ValueError as exc:
        raise JobFailure(f"NanoPlot's statistics could not be read: {exc}",
                         "output_unreadable", tool="NanoPlot", detail=str(exc)) from exc
    removed = NanoplotAdapter.artefact_reads_removed(logs[0].read_text(errors="replace"))
    ctx.log(f"NanoPlot: {pre['number_of_reads']:,} reads, {pre['number_of_bases']:,} bases in NanoStats.txt "
            "(every read nanoget kept; it drops zero-length reads)")
    if post is not None:
        ctx.log(f"NanoPlot then removed {removed} artefactual read(s) (length < 20 and mean quality > 30); "
                f"{names.post_filtering} describes the remaining {post['number_of_reads']:,}")
    if pre["unparsed"]:
        ctx.log("NanoStats.txt rows ARVA does not interpret (kept in the file): " + ", ".join(pre["unparsed"]))
    ctx.job.result_summary = {
        "nanoplot_version": ctx.job.tool_version,
        "stats": pre,
        "post_filtering": post,
        "artefact_reads_removed": removed,
    }
    ctx.job.output_paths = [_rel(ctx, p) for p in (report, stats, post_path, logs[0], stderr_log) if p.is_file()]


def run_nanoplot_job(job_id: str) -> str:
    return run_job(job_id, _nanoplot_body)


# --- fastp --------------------------------------------------------------------

def _fastp_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "fastp")
    files = ctx.input_files()
    _log_inputs(ctx, files)
    params = FastpParams(**(ctx.job.parameters or {}))
    results = ctx.path(ctx.results_rel)
    processed = ctx.path(ctx.processed_rel)
    results.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    r1 = files[0]
    r2 = files[1] if len(files) > 1 else None
    out1 = processed / f"{_stem(r1)}.fastp.fastq.gz"
    out2 = processed / f"{_stem(r2)}.fastp.fastq.gz" if r2 else None
    json_path, html_path = results / "fastp.json", results / "fastp.html"
    argv = FastpAdapter.argv(
        exe, params, ctx.path(r1.stored_path), out1, json_path, html_path,
        in2=ctx.path(r2.stored_path) if r2 else None, out2=out2,
        title=f"ARVA fastp report — {ctx.job.sample.sample_code}",
    )
    log = _run(ctx, argv, results, "fastp.log")
    summary = FastpAdapter.parse_report(json_path)
    ctx.job.result_summary = summary
    before, after = summary["before_filtering"], summary["after_filtering"]
    ctx.log(f"fastp: reads {before['total_reads']:,} → {after['total_reads']:,}; "
            f"bases {before['total_bases']:,} → {after['total_bases']:,}")
    removed = removed_reads(summary["filtering_result"], params.length_limit)
    if removed:
        ctx.log(f"fastp removed: {removed}")
    # fastp exits with status 0 and writes 0-byte .fq.gz files when no read passes.
    if after["total_reads"] == 0:
        raise JobFailure(f"fastp kept no reads with these thresholds; nothing was registered (removed: {removed})",
                         "fastp_no_reads", removed=str(removed))
    for out in (out1, out2):
        if out is not None and not (check := quick_validate(out)).is_valid:
            raise JobFailure(f"fastp wrote {out.name}, which cannot be read ({check.message}); nothing was registered",
                             "output_unreadable", tool="fastp", detail=check.message)

    label = f"Reads kept by fastp {ctx.job.tool_version}"
    derived = [_register_derived(ctx, r1, _rel(ctx, out1), out1.name, label)]
    if r2 and out2:
        derived.append(_register_derived(ctx, r2, _rel(ctx, out2), out2.name, label))
    ctx.job.output_paths = [*(d.stored_path for d in derived), _rel(ctx, json_path), _rel(ctx, html_path),
                            _rel(ctx, log)]
    _queue_stats_after(ctx, files, derived)


def run_fastp_job(job_id: str) -> str:
    return run_job(job_id, _fastp_body)


# --- Filtlong -----------------------------------------------------------------

def _filtlong_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "filtlong")
    (f,) = ctx.input_files()
    _log_inputs(ctx, [f])
    params = FiltlongParams(**(ctx.job.parameters or {}))
    results = ctx.path(ctx.results_rel)
    processed = ctx.path(ctx.processed_rel)
    results.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    out = processed / f"{_stem(f)}.filtlong.fastq.gz"
    if params.genome_size_bp is not None:
        ctx.log(f"Target: {params.target_bases:,} bases = round({params.target_coverage_x:g}× × "
                f"{params.genome_size_bp:,} bp genome size); Filtlong receives only --target_bases")
    log = _run(ctx, FiltlongAdapter.argv(exe, params, ctx.path(f.stored_path)), results, "filtlong.log",
               stdout=out, extra_env=FILTLONG_ENVIRONMENT)
    ctx.job.result_summary = summary = FiltlongAdapter.parse_log(log.read_text(errors="replace"))
    if summary.get("not_enough_reads_for_target") or summary.get("below_target_after_filtering"):
        ctx.log("Filtlong: the target is not below the bases available, so no reads were removed to meet it")
    check = quick_validate(out)
    if check.records_checked == 0:
        raise JobFailure("Filtlong kept no reads with these thresholds; nothing was written", "filtlong_no_reads")
    derived = _register_derived(ctx, f, _rel(ctx, out), out.name,
                                f"Reads kept by Filtlong {ctx.job.tool_version}")
    ctx.job.output_paths = [derived.stored_path, _rel(ctx, log)]
    _queue_stats_after(ctx, [f], [derived])


def run_filtlong_job(job_id: str) -> str:
    return run_job(job_id, _filtlong_body)


# --- MultiQC (project level) -----------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_multiqc_inputs(ctx: JobContext, planned: list[dict], staged_dir: Path) -> list[ReportInput]:
    """Copy each chosen output under a name that becomes its sample name (renamed exactly by a TSV)."""
    staged_dir.mkdir(parents=True)
    inputs = []
    for n, item in enumerate(planned, 1):
        source = ctx.db.get(AnalysisJob, item["job_id"])
        if source is None or source.status is not JobStatus.completed or item["output_path"] not in (source.output_paths or []):
            raise JobFailure(f"The {item['module']} result {item['job_id']} of sample {item['sample_code']} "
                             "is no longer available; start the report again")
        src = ctx.path(item["output_path"])
        if not src.is_file():
            raise JobFailure(f"{item['output_path']} is missing on disk")
        dst = staged_dir / staged_name(n, item["module"])
        shutil.copyfile(src, dst)
        ctx.log(f"Input {n}: '{item['name']}' = {item['module']} result of {', '.join(item['file_names'])} "
                f"(job {item['job_id']}, {item['tool_name']} {item['tool_version']}; {dst.name}, sha256 {_sha256(dst)})")
        if item["module"] == "filtlong":
            # Logs of runs made before ARVA set LC_ALL=C may group digits (1,362,402), which MultiQC cannot read.
            text = dst.read_bytes().decode("latin-1")
            if (plain := plain_counts(text)) != text:
                dst.write_bytes(plain.encode("latin-1"))
                ctx.log(f"Input {n}: Filtlong wrote its counts with digit grouping; the staged copy has the "
                        f"separators removed (sha256 {_sha256(dst)})")
        inputs.append(ReportInput(item["module"], dst, item["name"]))
    return inputs


def _tool_versions(planned: list[dict]) -> dict[str, list[str]]:
    versions: dict[str, set[str]] = {}
    for item in planned:
        versions.setdefault(item["tool_name"], set()).add(item["tool_version"])
    return {tool: sorted(v) for tool, v in sorted(versions.items())}


def _multiqc_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "multiqc")
    params = ctx.job.parameters or {}
    planned: list[dict] = params.get("inputs") or []
    if not planned:
        raise JobFailure("No tool results were selected for the report")
    # MultiQC joins rows by sample name, so a shared name would merge the values of different files.
    owners: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for item in planned:
        owners[item["name"]].add((item["sample_id"], *item["file_ids"]))
    if shared := sorted(name for name, keys in owners.items() if len(keys) > 1):
        raise JobFailure("These report names would each hold results of different samples or files: "
                         + ", ".join(shared))
    project = ctx.db.get(Project, ctx.job.project_id)
    results = ctx.path(ctx.results_rel)
    inputs = _stage_multiqc_inputs(ctx, planned, results / "inputs")
    modules = [m for m in ("fastqc", "fastp", "seqkit", "filtlong") if any(i.module == m for i in inputs)]
    file_list, config, names = results / "inputs.txt", results / "arva_multiqc_config.yaml", results / "sample_names.tsv"
    file_list.write_text("".join(f"{i.path}\n" for i in inputs))
    config.write_text(MultiqcAdapter.config(modules))
    names.write_text(MultiqcAdapter.replace_names(inputs))
    argv = MultiqcAdapter.argv(
        exe, file_list=file_list, outdir=results, config=config, names=names,
        title=f"{project.name} - ARVA project QC report",
        comment=f"ARVA analysis job {ctx.job.id}", modules=modules,
    )
    # An empty working directory: MultiQC would read a multiqc_config.yaml found there.
    work = results / "work"
    work.mkdir()
    log = _run(ctx, argv, work, "multiqc.stderr.log", extra_env=ENVIRONMENT, log_dir=results)
    shutil.rmtree(work, ignore_errors=True)

    report, data_dir = results / REPORT_FILENAME, results / DATA_DIR
    sources = data_dir / SOURCES_FILE
    if not report.is_file() or not (data_dir / DATA_JSON).is_file() or not sources.is_file():
        raise JobFailure("MultiQC exited without an error but did not write its report and data files "
                         "(it does this when it recognises none of the inputs); see the log")
    problems = MultiqcAdapter.check_sources(inputs, MultiqcAdapter.parse_sources(sources.read_text()))
    if problems:
        raise JobFailure("MultiQC did not report every input exactly once: " + "; ".join(problems[:8])
                         + (f" (and {len(problems) - 8} more)" if len(problems) > 8 else ""))
    parsed = MultiqcAdapter.parse_data(data_dir)
    if parsed["multiqc_version"] != ctx.job.tool_version:
        ctx.log(f"WARNING: the report says MultiQC {parsed['multiqc_version']}; detected {ctx.job.tool_version}")
    stats = parsed["general_stats"]
    if stats["unmapped"]:
        ctx.log("General-statistics columns ARVA does not interpret for this MultiQC version (not stored): "
                + ", ".join(stats["unmapped"]))
    ctx.log(f"MultiQC report: {len(inputs)} input(s), modules {', '.join(modules)}; every input found once")
    samples = {i["name"]: {"name": i["name"], "sample_id": i["sample_id"], "sample_code": i["sample_code"]}
               for i in planned}
    ctx.job.result_summary = {
        "multiqc_version": parsed["multiqc_version"],
        "report_creation_date": parsed["report_creation_date"],
        "modules": modules,
        "samples": sorted(samples.values(), key=lambda s: s["name"]),
        "versions": {"reported_by_multiqc": parsed["software_versions"], "arva_jobs": _tool_versions(planned)},
        "general_stats": stats,
    }
    extra = [data_dir / n for n in (DATA_JSON, SOURCES_FILE, VERSIONS_FILE, "multiqc.log")]
    ctx.job.output_paths = [_rel(ctx, p) for p in (report, *extra, file_list, config, names, log) if p.is_file()]


def run_multiqc_job(job_id: str) -> str:
    return run_job(job_id, _multiqc_body)


# --- Flye (long-read assembly) ----------------------------------------------------------

class _StageMonitor:
    """Follows a tool's log while it runs: each new stage goes to the job log, and job.progress (stage, elapsed
    time, live log path) is committed on every call so clients polling the job see it. `plan`, when given, returns
    the stages the tool itself announces it will run (None until it has written them); they replace `stages`."""

    def __init__(self, ctx: JobContext, tool: str, log_path: Path, stages: tuple[str, ...], stage_of,
                 plan: Callable[[], tuple[str, ...] | None] | None = None, done: tuple[str, ...] = ()):
        self.ctx, self.tool, self.log_path, self.expected, self.stage_of = ctx, tool, log_path, list(stages), stage_of
        self.plan = plan
        # `done`: stages completed by an earlier run this one resumes.
        self.offset, self.partial, self.seen = 0, b"", list(done)
        self.started, self.started_at, self.stage_started_at = time.monotonic(), now(), None

    def _read_plan(self) -> None:
        if self.plan is None:
            return
        planned = self.plan()
        if planned:
            self.expected, self.plan = list(planned), None
            self.ctx.log(f"{self.tool} planned {len(planned)} stages: {', '.join(planned)}")

    def _read(self) -> None:
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except FileNotFoundError:
            return
        self.offset += len(data)
        *lines, self.partial = (self.partial + data).split(b"\n")
        for line in lines:
            stage = self.stage_of(line.decode("utf-8", "replace"))
            if stage is None:
                continue
            self.seen.append(stage)
            self.stage_started_at = now()
            total = max(len(self.expected), len(self.seen))
            note = "" if stage in self.expected or not self.expected else " (a stage ARVA does not expect for this run)"
            self.ctx.log(f"{self.tool} stage {len(self.seen)}/{total}: {stage}{note}")

    def __call__(self, finished: bool = False) -> None:
        self._read_plan()
        self._read()
        self.ctx.job.progress = {
            "tool": self.tool,
            "stage": self.seen[-1] if self.seen else None,
            "stage_index": len(self.seen) or None,
            "stages_total": max(len(self.expected), len(self.seen)),
            "stages": self.expected,
            "started_at": self.started_at.isoformat(),
            "stage_started_at": self.stage_started_at.isoformat() if self.stage_started_at else None,
            "updated_at": now().isoformat(),
            "elapsed_seconds": round(time.monotonic() - self.started, 1),
            "finished": finished,
            "log": _rel(self.ctx, self.log_path),
        }
        self.ctx.log.flush()


def _flye_samtools(ctx: JobContext, exe: str, results: Path) -> tuple[dict[str, str] | None, dict]:
    """The PATH Flye needs to find flye-samtools, linking it to samtools when the installation lacks it."""
    h = samtools_helper(exe)
    if h["provided_by"] == "missing":
        raise JobFailure("Flye calls flye-samtools, which neither this Flye installation nor PATH provides, and "
                         "samtools was not found to stand in for it. Install samtools", "samtools_missing")
    record = {"name": SAMTOOLS_HELPER, "provided_by": h["provided_by"], "executable": h["samtools"],
              "samtools_version": helper_version(h["samtools"])}
    prepend = h["path_prepend"]
    if h["provided_by"] == "arva_link":
        bindir = results / "helper-bin"
        bindir.mkdir()
        (bindir / SAMTOOLS_HELPER).symlink_to(h["samtools"])
        prepend = str(bindir)
        ctx.log(f"Flye calls {SAMTOOLS_HELPER}, which this Flye installation does not provide (Debian's and Ubuntu's "
                f"flye package lack it); ARVA linked it to {h['samtools']} (samtools {record['samtools_version']}) "
                "for this run")
    else:
        ctx.log(f"Flye's {SAMTOOLS_HELPER}: {h['samtools']} (samtools {record['samtools_version']})")
    env = {"PATH": prepend + os.pathsep + os.environ.get("PATH", "")} if prepend else None
    return env, record


def _kept_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def _take_flye_checkpoint(ctx: JobContext, resume: dict, out_dir: Path, stages: tuple[str, ...]) -> dict:
    """Move the work folder kept by the job this one resumes into this job's results (committed at once, so the
    folder belongs to one job only), and delete the folder of the stage Flye reruns."""
    original = ctx.db.get(AnalysisJob, resume.get("of_job_id"))
    kept = original.checkpoint if original is not None else None
    if not kept or kept.get("path") != resume.get("checkpoint_path"):
        raise JobFailure(f"the Flye work folder kept by job {resume.get('of_job_id')} is no longer available "
                         "(discarded, or taken by another resumed run); start a new assembly")
    src = ctx.path(kept["path"])
    found = read_checkpoint(src, stages) if src.is_dir() else None
    if found is None or found["resume_stage"] != kept["resume_stage"]:
        raise JobFailure(f"the Flye work folder kept by job {original.id} is missing or no longer matches what ARVA "
                         "recorded; start a new assembly")
    src.rename(out_dir)
    with contextlib.suppress(OSError):
        src.parent.rmdir()
    original.checkpoint = None
    ctx.log(f"Resuming job {original.id}: its Flye work folder moved here. Flye {kept['tool_version']} completed "
            f"{', '.join(found['completed_stages'])} there; this run continues with --resume from "
            f"{found['resume_stage']}, with the same reads and options", flush=True)
    stage_dir = STAGE_DIRS.get(found["resume_stage"])
    if stage_dir and (out_dir / stage_dir).exists():
        shutil.rmtree(out_dir / stage_dir)
        ctx.log(f"Removed {stage_dir}, written by the interrupted {found['resume_stage']} stage, so Flye reruns it "
                "from the start")
    return found


def _keep_flye_checkpoint(ctx: JobContext, out_dir: Path, stages: tuple[str, ...], exc: BaseException,
                          stopped: dict) -> None:
    """Keep Flye's work folder for --resume when the run was stopped from outside (cancelled, time limit, killed by
    a signal or by the system running out of memory) after a stage beyond configure had completed."""
    if not out_dir.is_dir():
        return
    if isinstance(exc, JobCancelled):
        reason = "cancelled"
    elif isinstance(exc, ToolTimeoutError):
        reason = "time_limit"
    elif stopped.get("returncode") is not None and FlyeAdapter.resumable_failure(stopped.get("log", ""),
                                                                               stopped["returncode"]):
        reason = "stopped"
    else:
        ctx.log("Flye's work folder was not kept for resuming: Flye stopped with an error of its own (or after it "
                "had finished), which resuming with the same reads and options would repeat")
        return
    found = read_checkpoint(out_dir, stages)
    if found is None:
        ctx.log("Flye's work folder was not kept for resuming: no stage after configure had completed")
        return
    target = ctx.path(ctx.checkpoint_rel) / "flye"
    stage_dir = STAGE_DIRS.get(found["resume_stage"])
    try:
        if stage_dir and (out_dir / stage_dir).exists():
            # Flye 2.9.3 appends to files of an interrupted polishing stage when resumed (see arva_tools.flye).
            shutil.rmtree(out_dir / stage_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        out_dir.rename(target)
    except OSError as err:
        ctx.log(f"Flye's work folder could not be kept for resuming: {err}")
        return
    size = _kept_bytes(target)
    ctx.job.checkpoint = {
        "tool": "Flye", "tool_version": ctx.job.tool_version, "path": _rel(ctx, target), "reason": reason,
        "resume_stage": found["resume_stage"], "completed_stages": found["completed_stages"],
        "stages": list(stages), "size_bytes": size, "kept_at": now().isoformat(timespec="seconds"),
    }
    ctx.log(f"Kept Flye's work folder ({size:,} bytes, completed stages: {', '.join(found['completed_stages'])}) "
            f"so the run can resume from {found['resume_stage']}" +
            (f" (removed {stage_dir}, written by the interrupted stage)" if stage_dir else ""))


def _flye_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "flye")
    files = ctx.input_files()
    _log_inputs(ctx, files)
    params = FlyeParams.from_dict(ctx.job.parameters or {})
    resume = (ctx.job.parameters or {}).get("resume")
    results = ctx.path(ctx.results_rel)
    links, out_dir = results / "input", results / "flye"
    links.mkdir(parents=True)
    reads = []
    for n, f in enumerate(files, 1):
        if f.file_format not in (FileFormat.fastq, FileFormat.fastq_gz):
            raise JobFailure(f"{f.original_filename} is not a FASTQ file", "not_fastq", file=f.original_filename)
        # Flye reads the format from the file name and refuses paths with spaces.
        link = links / read_link_name(n, f.original_filename, f.file_format is FileFormat.fastq_gz)
        link.symlink_to(ctx.path(f.stored_path))
        reads.append(link)
    env, helper = _flye_samtools(ctx, exe, results)
    try:
        supported = FlyeAdapter.help_options(exe)
        argv = FlyeAdapter.argv(exe, params, reads, out_dir, supported, resume=resume is not None)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"Flye's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="Flye", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"Flye cannot run with these settings: {exc}",
                         "settings_rejected", tool="Flye", detail=str(exc)) from exc
    if params.genome_size_bp is not None:
        basis = {"entered": "entered by the user", "expected_genome_size": "the sample's expected genome size",
                 "reads_over_depth": f"total read bases ÷ an assumed depth of {params.assumed_depth_x:g}×"}
        ctx.log(f"Genome size {params.genome_size_bp:,} bp ({basis[params.genome_size_basis or 'entered']})")
    if params.threads > 1:
        ctx.log(f"Flye runs with {params.threads} threads; its output can differ between runs and thread counts")

    stages = params.stages()
    stopped: dict = {}
    ctx.before_cleanup.append(lambda exc: _keep_flye_checkpoint(ctx, out_dir, stages, exc, stopped))
    done = tuple(_take_flye_checkpoint(ctx, resume, out_dir, stages)["completed_stages"]) if resume else ()
    stderr_log = results / "flye.stderr.log"
    monitor = _StageMonitor(ctx, "Flye", stderr_log, stages, FlyeAdapter.stage, done=done)
    monitor()
    try:
        _run(ctx, argv, results, stderr_log.name, extra_env=env, monitor=monitor)
    except ToolExecutionError as exc:
        monitor(finished=True)
        text = stderr_log.read_text(errors="replace") if stderr_log.is_file() else exc.stderr_tail
        stopped.update(returncode=exc.returncode, log=text)
        if isinstance(exc, ToolTimeoutError):
            raise
        reason = FlyeAdapter.failure_reason(text, exc.returncode)
        if reason is None:
            raise
        ctx.log("Flye output (last lines):\n" + exc.stderr_tail.strip())
        raise JobFailure(reason) from None
    finally:
        shutil.rmtree(links, ignore_errors=True)
    monitor(finished=True)

    if missing := [n for n in FLYE_OUTPUTS if not (out_dir / n).is_file()]:
        raise JobFailure("Flye exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="Flye", files=", ".join(missing))
    for name in FLYE_OUTPUTS:
        (out_dir / name).rename(results / name)
    shutil.rmtree(out_dir)
    shutil.rmtree(results / "helper-bin", ignore_errors=True)
    ctx.log("Removed Flye's intermediate stage folders; kept " + ", ".join(FLYE_OUTPUTS))

    try:
        rows = FlyeAdapter.parse_assembly_info((results / "assembly_info.txt").read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"Flye's assembly_info.txt cannot be read: {exc}",
                         "output_unreadable", tool="Flye", detail=str(exc)) from exc
    log_summary = FlyeAdapter.parse_log((results / "flye.log").read_text(errors="replace"))
    if params.min_overlap is None and "min_overlap" in log_summary:
        ctx.log(f"Flye chose a minimum overlap of {log_summary['min_overlap']:,} bp (from the reads' N90, "
                f"{log_summary.get('reads_n90', 0):,} bp)")
    for warning in log_summary["warnings"]:
        ctx.log(f"Flye warning: {warning}")
    annotations = {r["name"]: ContigAnnotation(coverage=r["coverage"], circular=r["circular"], repeat=r["repeat"])
                   for r in rows}
    assembly = register_assembly(
        ctx, assembler="Flye", mode=AssemblyMode.long, read_type=params.read_type, contigs=results / "assembly.fasta",
        graph=results / "assembly_graph.gfa", info=results / "assembly_info.txt", annotations=annotations,
    )
    lengths = {r["name"]: r["length"] for r in rows}
    if assembly.stats["contig_count"] != len(rows) or any(lengths.get(c["name"]) != c["length"] for c in assembly.contigs):
        raise JobFailure("Flye's assembly_info.txt does not describe the contigs in assembly.fasta (names or lengths "
                         "differ); nothing was registered")
    ctx.db.flush()
    ctx.job.result_summary = {
        "flye_version": ctx.job.tool_version,
        "assembly_id": assembly.id,
        "read_type": params.read_type,
        "log": log_summary,
        "contigs": rows[:MAX_CONTIG_ROWS],
        "contig_rows": {"stored": min(len(rows), MAX_CONTIG_ROWS), "total": len(rows),
                        "truncated": len(rows) > MAX_CONTIG_ROWS},
        "helpers": [helper],
        **({"resumed": {"from_job_id": resume["of_job_id"], "stage": resume["stage"],
                        "completed_stages": list(done)}} if resume else {}),
    }
    ctx.job.output_paths = [_rel(ctx, results / n) for n in (*FLYE_OUTPUTS, stderr_log.name)]


def run_flye_job(job_id: str) -> str:
    return run_job(job_id, _flye_body)


# --- SPAdes and Unicycler (short-read and hybrid assembly) ---------------------------------------------------

def _link_roles(ctx: JobContext, links: Path) -> dict[str, Path]:
    """Link each input, by role (r1, r2, unpaired, long), under a space-free name ending in .fastq(.gz): SPAdes
    recognises reads by their name, and Debian's SPAdes launcher splits paths with spaces."""
    roles = (ctx.job.parameters or {}).get("inputs") or {}
    files = {f.id: f for f in ctx.input_files()}
    _log_inputs(ctx, list(files.values()))
    links.mkdir(parents=True)
    out = {}
    for n, role in enumerate(ROLES, 1):
        if not (file_id := roles.get(role)):
            continue
        f = files.get(file_id)
        if f is None:
            raise JobFailure(f"the {role} file {file_id} is not one of this job's inputs")
        if f.file_format not in (FileFormat.fastq, FileFormat.fastq_gz):
            raise JobFailure(f"{f.original_filename} is not a FASTQ file", "not_fastq", file=f.original_filename)
        link = links / read_link_name(n, f.original_filename, f.file_format is FileFormat.fastq_gz)
        link.symlink_to(ctx.path(f.stored_path))
        out[role] = link
        ctx.log(f"Reads as {role}: {f.original_filename}")
    return out


def _fasta_headers(path: Path) -> list[str]:
    with open(path, errors="replace") as fh:
        return [line[1:].strip() for line in fh if line.startswith(">")]


def _spades_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "spades")
    params = SpadesParams.from_dict(ctx.job.parameters or {})
    roles = (ctx.job.parameters or {}).get("inputs") or {}
    results = ctx.path(ctx.results_rel)
    links, out_dir = results / "input", results / "spades"
    reads = _link_roles(ctx, links)
    try:
        argv = SpadesAdapter.argv(exe, params, out_dir, SpadesAdapter.help_options(exe), r1=reads.get("r1"),
                                  r2=reads.get("r2"), unpaired=reads.get("unpaired"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"SPAdes' --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="SPAdes", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"SPAdes cannot run with these settings: {exc}",
                         "settings_rejected", tool="SPAdes", detail=str(exc)) from exc
    ctx.log("k-mer sizes: " + (", ".join(map(str, params.k)) + " (set by the user)" if params.k else
                                "chosen by SPAdes from the read length (read from its log after the run)"))
    ctx.log(f"Memory limit {params.memory_gb} GB (-m), {params.threads} threads; registered as the assembly: "
            f"{params.output}.fasta")

    console = results / "spades.console.log"
    plan = out_dir / SPADES_PLAN
    monitor = _StageMonitor(ctx, "SPAdes", console, (), SpadesAdapter.stage,
                            plan=lambda: SpadesAdapter.planned_stages(plan.read_text(errors="replace"))
                            if plan.is_file() else None)
    monitor()
    try:
        _run(ctx, argv, results, console.name, monitor=monitor)
    except ToolExecutionError as exc:
        monitor(finished=True)
        if isinstance(exc, ToolTimeoutError):
            raise
        log = out_dir / "spades.log" if (out_dir / "spades.log").is_file() else console
        text = log.read_text(errors="replace") if log.is_file() else exc.stderr_tail
        reason = SpadesAdapter.failure_reason(text, exc.returncode, params.memory_gb)
        if reason is None:
            raise
        ctx.log("SPAdes output (last lines):\n" + exc.stderr_tail.strip())
        raise JobFailure(reason) from None
    finally:
        shutil.rmtree(links, ignore_errors=True)
    monitor(finished=True)

    if missing := [n for n in SPADES_OUTPUTS if not (out_dir / n).is_file()]:
        raise JobFailure("SPAdes exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="SPAdes", files=", ".join(missing))
    for name in SPADES_OUTPUTS:
        (out_dir / name).rename(results / name)
    shutil.rmtree(out_dir)
    ctx.log("Removed SPAdes' working folders (per-k assemblies, temporary files); kept " + ", ".join(SPADES_OUTPUTS))
    summary = SpadesAdapter.parse_log((results / "spades.log").read_text(errors="replace"))
    if not summary["k_values"]:
        raise JobFailure("SPAdes' log names no k-mer size that it ran; the run cannot be recorded")
    source = "user" if params.k else "spades"
    ctx.log(f"SPAdes ran k = {', '.join(map(str, summary['k_values']))} "
            f"({'set by the user' if params.k else 'chosen by SPAdes'})")
    if params.k and summary["k_values"] != params.k:
        ctx.log(f"Note: SPAdes ran k = {', '.join(map(str, summary['k_values']))}, not the k given "
                f"({', '.join(map(str, params.k))}); its messages follow")
    for message in summary["k_messages"]:
        ctx.log(f"SPAdes: {message}")
    for warning in summary["warnings"]:
        ctx.log(f"SPAdes warning: {warning}")

    contigs = results / f"{params.output}.fasta"
    nodes = {}
    for name in _fasta_headers(contigs):
        node = parse_node_name(name)
        if node is None:
            raise JobFailure(f"SPAdes wrote a sequence name without its length and k-mer coverage: {name[:80]!r}")
        nodes[name] = node
    annotations = {n: ContigAnnotation(coverage=node["kmer_coverage"]) for n, node in nodes.items()}
    assembly = register_assembly(
        ctx, assembler="SPAdes", mode=AssemblyMode.short, read_type=library_layout(roles), contigs=contigs,
        graph=results / "assembly_graph_with_scaffolds.gfa", annotations=annotations,
    )
    if any(nodes[c["name"]]["length"] != c["length"] for c in assembly.contigs):
        raise JobFailure(f"The lengths in SPAdes' sequence names differ from the sequences in {contigs.name}; nothing "
                         "was registered")
    ctx.log(f"Per-contig coverage is SPAdes' k-mer coverage (k = {summary['k_values'][-1]}), not read depth; SPAdes "
            "reports no circularity")
    ctx.db.flush()
    ctx.job.result_summary = {
        "spades_version": ctx.job.tool_version,
        "assembly_id": assembly.id,
        "output": params.output,
        "k_values": summary["k_values"],
        "k_source": source,
        "coverage_kind": "kmer_coverage",
        "log": summary,
    }
    ctx.job.output_paths = [_rel(ctx, results / n) for n in (*SPADES_OUTPUTS, console.name)]


def run_spades_job(job_id: str) -> str:
    return run_job(job_id, _spades_body)


def _unicycler_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "unicycler")
    params = UnicyclerParams.from_dict(ctx.job.parameters or {})
    roles = (ctx.job.parameters or {}).get("inputs") or {}
    results = ctx.path(ctx.results_rel)
    links, out_dir = results / "input", results / "unicycler"
    reads = _link_roles(ctx, links)
    helpers = helper_paths()
    for name, path in helpers.items():
        ctx.log(f"Unicycler helper {name}: {path or 'not found'}")
    try:
        argv = UnicyclerAdapter.argv(exe, params, out_dir, UnicyclerAdapter.help_options(exe), helpers,
                                     r1=reads.get("r1"), r2=reads.get("r2"), unpaired=reads.get("unpaired"),
                                     long=reads.get("long"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"Unicycler's --help_all could not be read to check its options: {exc}",
                         "help_unreadable", tool="Unicycler", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"Unicycler cannot run with these settings: {exc}",
                         "settings_rejected", tool="Unicycler", detail=str(exc)) from exc
    if params.short:
        ctx.log(f"SPAdes inside Unicycler: memory limit {params.spades_memory_gb} GB, passed with --spades_options "
                "(Unicycler's own default, -m 1024, sets no practical limit); k-mer sizes "
                + (", ".join(map(str, params.kmers)) + " (set by the user)" if params.kmers else "chosen by Unicycler"))

    console = results / "unicycler.console.log"
    monitor = _StageMonitor(ctx, "Unicycler", out_dir / "unicycler.log", params.stages(), UnicyclerAdapter.stage)
    monitor()
    try:
        _run(ctx, argv, results, console.name, monitor=monitor)
    except ToolExecutionError as exc:
        monitor(finished=True)
        if isinstance(exc, ToolTimeoutError):
            raise
        text = console.read_text(errors="replace") if console.is_file() else exc.stderr_tail
        spades_log = out_dir / SPADES_DIR / "spades.log"
        reason = UnicyclerAdapter.failure_reason(
            text, exc.returncode, spades_log.read_text(errors="replace") if spades_log.is_file() else None,
            params.spades_memory_gb if params.short else None)
        if reason is None:
            raise
        ctx.log("Unicycler output (last lines):\n" + exc.stderr_tail.strip())
        raise JobFailure(reason) from None
    finally:
        shutil.rmtree(links, ignore_errors=True)

    if missing := [n for n in UNICYCLER_OUTPUTS if not (out_dir / n).is_file()]:
        monitor(finished=True)
        raise JobFailure("Unicycler exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="Unicycler", files=", ".join(missing))
    for name in UNICYCLER_OUTPUTS:
        (out_dir / name).rename(results / name)
    monitor.log_path = results / "unicycler.log"
    monitor(finished=True)
    kept = sorted(p for p in out_dir.rglob("*") if p.is_file())
    if kept:
        ctx.log(f"Kept {len(kept)} file(s) Unicycler saved at its checkpoints (--keep {params.keep}) in unicycler/")
    else:
        shutil.rmtree(out_dir)
    summary = UnicyclerAdapter.parse_log((results / "unicycler.log").read_text(errors="replace"))
    for d in summary["dependencies"]:
        ctx.log(f"Unicycler's dependency check: {d['program']} {d['version'] or ''} ({d['status']})")

    headers = _fasta_headers(results / "assembly.fasta")
    try:
        if params.assembly_mode == "long":
            graph = UnicyclerAdapter.parse_gfa_annotations((results / "assembly.gfa").read_text(errors="replace"))
            names = [h.split()[0] if h.split() else "" for h in headers]
            if absent := [n for n in names if n not in graph]:
                raise ValueError(f"assembly.fasta names {', '.join(absent[:5])}, which assembly.gfa does not define")
            rows, source = {n: graph[n] for n in names}, "assembly_graph"
            ctx.log("Unicycler 0.5.0 writes no length, depth or circularity in long-read-only FASTA headers; ARVA "
                    "read each contig's depth (dp tag) and circularity (only links joining its end to its start, "
                    "Unicycler's definition of a completed replicon) from assembly.gfa")
        else:
            rows, source = UnicyclerAdapter.parse_headers(headers), "fasta_headers"
    except ValueError as exc:
        raise JobFailure(f"Unicycler's output cannot be read: {exc}",
                         "output_unreadable", tool="Unicycler", detail=str(exc)) from exc
    annotations = {n: ContigAnnotation(coverage=r["depth"], circular=r["circular"]) for n, r in rows.items()}
    assembly = register_assembly(
        ctx, assembler="Unicycler", mode=AssemblyMode(params.assembly_mode), read_type=library_layout(roles),
        contigs=results / "assembly.fasta", graph=results / "assembly.gfa", annotations=annotations,
    )
    if any(rows[c["name"]]["length"] != c["length"] for c in assembly.contigs):
        raise JobFailure("The lengths Unicycler reports differ from the sequences in assembly.fasta; nothing was "
                         "registered")
    ctx.log("Per-contig depth is Unicycler's relative depth (1 = the typical depth of the main replicons), not read "
            "depth")
    versions = {d["program"]: d for d in summary["dependencies"]}
    ctx.db.flush()
    ctx.job.result_summary = {
        "unicycler_version": ctx.job.tool_version,
        "assembly_id": assembly.id,
        "assembly_mode": params.assembly_mode,
        "annotation_source": source,
        "coverage_kind": "relative_depth",
        "helpers": [{"name": n, "path": p, "version": (versions.get(n) or {}).get("version"),
                     "status": (versions.get(n) or {}).get("status")} for n, p in helpers.items()],
        "log": summary,
    }
    ctx.job.output_paths = [_rel(ctx, p) for p in (*(results / n for n in UNICYCLER_OUTPUTS), console, *kept)]


def run_unicycler_job(job_id: str) -> str:
    return run_job(job_id, _unicycler_body)


# --- QUAST (assembly evaluation) ----------------------------------------------------------

def _quast_inputs(ctx: JobContext, links: Path) -> tuple[list[tuple[Path, str]], list[Path], dict[str, str]]:
    """Link each planned assembly's contigs under the name QUAST needs, after checking it is the file recorded.
    Returns the (link, label) pairs, the contigs files, and the label of each link path."""
    assemblies, sources, names = [], [], {}
    for n, item in enumerate((ctx.job.parameters or {}).get("assemblies") or [], 1):
        a = ctx.db.get(Assembly, item["assembly_id"])
        if a is None or a.sample_id != ctx.job.sample_id:
            raise JobFailure(f"Assembly {item['assembly_id']} ({item['label']}) no longer exists",
                             "assembly_missing", assembly=item["label"])
        src = ctx.path(a.contigs_path)
        if not src.is_file():
            raise JobFailure(f"The contigs file of {item['label']} is missing on disk",
                             "contigs_missing", assembly=item["label"])
        if (digest := _sha256(src)) != item["contigs_sha256"]:
            raise JobFailure(f"The contigs file of {item['label']} changed since it was registered (sha256 {digest}, "
                             f"recorded {item['contigs_sha256']})", "contigs_changed", assembly=item["label"])
        link = links / quast_input_name("assembly", n, is_gzip(src))
        link.symlink_to(src)
        assemblies.append((link, item["label"]))
        sources.append(src)
        names[str(link)] = item["label"]
        ctx.log(f"Assembly {n}: '{item['label']}' = {a.assembler} {a.assembler_version} assembly {a.id} (job {a.job_id}; "
                f"contigs sha256 {digest}; linked as {link.name})")
    if not assemblies:
        raise JobFailure("No assemblies were selected")
    return assemblies, sources, names


def _quast_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "quast")
    params = ctx.job.parameters or {}
    qp = QuastParams(min_contig=params["min_contig"], threads=params["threads"])
    reference_files = ctx.input_files()
    _log_inputs(ctx, reference_files)
    results = ctx.path(ctx.results_rel)
    links, out = results / "input", results / OUT_DIR
    links.mkdir(parents=True)
    assemblies, sources, names = _quast_inputs(ctx, links)
    reference = None
    if reference_files:
        (f,) = reference_files
        if f.file_format not in (FileFormat.fasta, FileFormat.fasta_gz):
            raise JobFailure(f"{f.original_filename} is not a FASTA file", "not_fasta", file=f.original_filename)
        reference = links / quast_input_name("reference", 1, f.file_format is FileFormat.fasta_gz)
        reference.symlink_to(ctx.path(f.stored_path))
        names[str(reference)] = f.original_filename
        found = aligner(exe)
        if found["provided_by"] == "missing":
            raise JobFailure("QUAST needs minimap2 2.19 or later on PATH to align contigs to the reference; ARVA does "
                             "not let QUAST compile its own copy during a run. Install minimap2")
        ctx.log(f"Reference {f.original_filename} (linked as {reference.name}); QUAST will align with minimap2 "
                f"{found['version']} ({found['executable']})")
    try:
        argv = QuastAdapter.argv(exe, qp, assemblies, out, QuastAdapter.help_options(exe), reference=reference)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"QUAST's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="QUAST", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"QUAST cannot run with these settings: {exc}",
                         "settings_rejected", tool="QUAST", detail=str(exc)) from exc
    ctx.log(f"Minimum contig length {qp.min_contig:,} bp: QUAST leaves shorter contigs out of every metric except "
            "'# contigs (>= 0 bp)' and 'Total length (>= 0 bp)'")

    console = results / CONSOLE_LOG
    monitor = _StageMonitor(ctx, "QUAST", console, quast_stages(reference is not None), QuastAdapter.stage)
    monitor()
    try:
        _run(ctx, argv, results, console.name, monitor=monitor)
    except ToolExecutionError as exc:
        monitor(finished=True)
        if isinstance(exc, ToolTimeoutError):
            raise
        reason = QuastAdapter.failure_reason(console.read_text(errors="replace") if console.is_file() else
                                             exc.stderr_tail, exc.returncode, names)
        if reason is None:
            raise
        ctx.log("QUAST output (last lines):\n" + exc.stderr_tail.strip())
        raise JobFailure(reason) from None
    finally:
        shutil.rmtree(links, ignore_errors=True)
    monitor(finished=True)

    if missing := [n for n in REQUIRED_OUTPUTS if not (out / n).is_file()]:
        raise JobFailure("QUAST exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="QUAST", files=", ".join(missing))
    run = QuastAdapter.parse_console(console.read_text(errors="replace"))
    expected = [label for _, label in assemblies]
    try:
        report = QuastAdapter.parse_report((out / REPORT_TSV).read_text(errors="replace"))
        transposed = QuastAdapter.parse_transposed_report((out / TRANSPOSED_TSV).read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"QUAST's report cannot be read: {exc}",
                         "output_unreadable", tool="QUAST", detail=str(exc)) from exc
    if report["labels"] != expected:
        left_out = [s["label"] for s in run["skipped"]] or sorted(set(expected) - set(report["labels"]))
        raise JobFailure(f"QUAST left out {', '.join(left_out)} (no contig of at least {qp.min_contig:,} bp, or "
                         "unreadable); nothing was recorded")
    if report != transposed:
        raise JobFailure("QUAST's report.tsv and transposed_report.tsv do not hold the same values")
    if run["quast_version"] and run["quast_version"] != ctx.job.tool_version:
        ctx.log(f"WARNING: QUAST reports version {run['quast_version']}; detected {ctx.job.tool_version}")
    for warning in run["warnings"]:
        ctx.log(f"QUAST warning: {warning}")
    log_empty = not (out / LOG).is_file() or (out / LOG).stat().st_size == 0
    if log_empty:
        ctx.log(f"Note: QUAST left quast.log empty (QUAST 5.2.0 does so under CPython 3.13.15 and later 3.13 releases; "
                f"this run used Python {run['python_version']}); its console output is kept as {CONSOLE_LOG}")

    used = None
    if reference is not None:
        for stderr in sorted((out / "contigs_reports").glob("contigs_report_*.stderr")):
            if used := QuastAdapter.parse_aligner(stderr.read_text(errors="replace")):
                break
        ctx.log(f"QUAST aligned with {used['name']} {used['version']} ({used['executable']})" if used else
                "Note: QUAST's alignment logs do not name the minimap2 it ran")

    values = {label: {r["field"]: r["values"][i] for r in report["rows"]} for i, label in enumerate(report["labels"])}
    checks = []
    for item, src, (_, label) in zip(params["assemblies"], sources, assemblies, strict=True):
        try:
            arva = min_length_summary(src, qp.min_contig)
        except (AssemblyFormatError, SequenceFormatError, OSError) as exc:
            raise JobFailure(f"ARVA could not read the contigs of {label} for its cross-check: {exc}") from exc
        rows = crosscheck(values[label], arva)
        disagree = [r["metric"] for r in rows if r["agrees"] is False]
        ctx.log(f"Cross-check '{label}': {sum(r['agrees'] is True for r in rows)}/{len(rows)} QUAST metrics equal ARVA's "
                f"at {qp.min_contig:,} bp" + (f"; differ: {', '.join(disagree)}" if disagree else ""))
        checks.append({"assembly_id": item["assembly_id"], "label": label, "arva": arva, "rows": rows,
                       "all_agree": not disagree})

    viewers = sorted((out / ICARUS_DIR).glob("*.html"))
    ctx.job.result_summary = {
        "quast_version": run["quast_version"] or ctx.job.tool_version,
        "python_version": run["python_version"],
        "min_contig": qp.min_contig,
        "reference": None if not reference_files else {
            "file_id": reference_files[0].id, "name": reference_files[0].original_filename,
            "sha256": reference_files[0].checksum_sha256, "size_bytes": reference_files[0].size_bytes},
        "assemblies": params["assemblies"],
        "report": report,
        "crosscheck": checks,
        "aligner": used,
        "warnings": run["warnings"],
        "quast_log_empty": log_empty,
        "html": {"report": REPORT_HTML, "icarus": ICARUS_HTML,
                 "viewers": [f"{ICARUS_DIR}/{p.name}" for p in viewers]},
    }
    kept = [out / n for n in (REPORT_HTML, ICARUS_HTML, REPORT_TSV, TRANSPOSED_TSV, "report.txt", LOG)]
    kept += viewers + [out / "contigs_reports" / n for n in ("misassemblies_report.tsv", "unaligned_report.tsv")]
    ctx.job.output_paths = [_rel(ctx, p) for p in (*kept, console) if p.is_file()]


def run_quast_job(job_id: str) -> str:
    return run_job(job_id, _quast_body)
