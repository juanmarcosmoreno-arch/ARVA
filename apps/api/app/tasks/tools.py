"""Worker tasks that run external tools through their ARVA adapters.

Each task records the resolved executable, detected version, exact argument
vectors and tool logs. Filtering tasks register their outputs as *derived*
files linked to the input file and job, then queue ARVA statistics for them so
the before/after comparison uses identical methods on both sides.
"""
from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path

from arva_core.seqstats import StatsParameters, quick_validate
from arva_tools import ToolStatus, run_command
from arva_tools.fastp import FastpAdapter, FastpParams
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams
from arva_tools.registry import detect
from arva_tools.seqkit import SeqkitAdapter

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import FileFormat, FileOrigin, RawFile
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


def _run(ctx: JobContext, argv: list[str], workdir: Path, log_name: str, stdout: Path | None = None) -> Path:
    ctx.job.commands = [*(ctx.job.commands or []), argv]
    ctx.log("Command: " + shlex.join(argv) + (f" > {stdout.name}" if stdout else ""), flush=True)
    log_path = workdir / log_name
    result = run_command(argv, cwd=workdir, stderr_path=log_path, stdout_path=stdout,
                         timeout_seconds=get_settings().tool_timeout_seconds)
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
    jobs = [new_sequence_stats_job(ctx.job.sample_id, f.id, params, ctx.job.id) for f in targets]
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
    ctx.job.result_summary = FastqcAdapter.parse_zip(zipf)
    ctx.job.output_paths = [_rel(ctx, html), _rel(ctx, zipf), _rel(ctx, log)]


def run_fastqc_job(job_id: str) -> str:
    return run_job(job_id, _fastqc_body)


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
    log = _run(ctx, FiltlongAdapter.argv(exe, params, ctx.path(f.stored_path)), results, "filtlong.log",
               stdout=out)
    ctx.job.result_summary = FiltlongAdapter.parse_log(log.read_text(errors="replace"))
    check = quick_validate(out)
    if check.records_checked == 0:
        raise JobFailure("Filtlong kept no reads with these thresholds; nothing was written")
    derived = _register_derived(ctx, f, _rel(ctx, out), out.name,
                                f"Reads kept by Filtlong {ctx.job.tool_version}")
    ctx.job.output_paths = [derived.stored_path, _rel(ctx, log)]
    _queue_stats_after(ctx, [f], [derived])


def run_filtlong_job(job_id: str) -> str:
    return run_job(job_id, _filtlong_body)
