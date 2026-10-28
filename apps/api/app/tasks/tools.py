"""Worker tasks that run external tools through their ARVA adapters.

Each task records the resolved executable, detected version, exact argument
vectors and tool logs. Filtering tasks register their outputs as *derived*
files linked to the input file and job, then queue ARVA statistics for them so
the before/after comparison uses identical methods on both sides.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from arva_core.seqstats import StatsParameters, quick_validate
from arva_tools import ToolExecutionError, ToolStatus, run_command
from arva_tools.fastp import FastpAdapter, FastpParams, removed_reads
from arva_tools.fastqc import DATA_JSON as FASTQC_DATA_JSON
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import ENVIRONMENT as FILTLONG_ENVIRONMENT
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams, plain_counts
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
from arva_tools.registry import detect
from arva_tools.seqkit import SeqkitAdapter

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import AnalysisJob, FileFormat, FileOrigin, JobStatus, Project, RawFile
from app.services.imports import header_metadata
from app.tasks.common import JobContext, JobFailure, run_job


def _resolve_tool(ctx: JobContext, tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available or not d.path:
        raise JobFailure(f"{d.info.name} is not available on this worker ({d.status.value}): {d.message}")
    if d.version != ctx.job.tool_version:
        ctx.log(f"Note: version detected at run time is {d.version} (was {ctx.job.tool_version} when queued)")
        ctx.job.tool_version = d.version or "unknown"
    ctx.job.tool_path = d.path
    if not d.version_validated:
        ctx.log(f"WARNING: {d.message}")
    ctx.log(f"Executable: {d.path} (version {d.version})")
    return d.path


def _run(ctx: JobContext, argv: list[str], workdir: Path, log_name: str, stdout: Path | None = None,
         extra_env: Mapping[str, str] | None = None, log_dir: Path | None = None, home: Path | None = None) -> Path:
    ctx.job.commands = [*(ctx.job.commands or []), argv]
    env_note = "".join(f"{k}={v} " for k, v in (extra_env or {}).items())
    ctx.log("Command: " + env_note + shlex.join(argv) + (f" > {stdout.name}" if stdout else ""), flush=True)
    log_path = (log_dir or workdir) / log_name
    result = run_command(argv, cwd=workdir, stderr_path=log_path, stdout_path=stdout,
                         timeout_seconds=get_settings().tool_timeout_seconds, extra_env=extra_env, home=home)
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
        raise JobFailure(f"FastQC exited without an error but its results could not be read: {exc}") from exc
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
        raise JobFailure(f"NanoPlot's statistics could not be read: {exc}") from exc
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
        raise JobFailure(f"fastp kept no reads with these thresholds; nothing was registered (removed: {removed})")
    for out in (out1, out2):
        if out is not None and not (check := quick_validate(out)).is_valid:
            raise JobFailure(f"fastp wrote {out.name}, which cannot be read ({check.message}); nothing was registered")

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
        raise JobFailure("Filtlong kept no reads with these thresholds; nothing was written")
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
