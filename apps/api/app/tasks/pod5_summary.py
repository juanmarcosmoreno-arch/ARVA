"""Worker task: run metadata of one POD5 raw-signal file, read with the official pod5 library.

The library runs in a child process (app.tasks.pod5_reader), so a damaged file that crashes native
code fails this job with a clear reason instead of killing the worker and leaving the job 'running'.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.raw_signal import POD5_INSTALL, installed_version, is_raw_signal, pod5_versions
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.pod5_reader import IDENTIFYING_FIELDS

STDERR_TAIL_LINES = 20


def reader_command(path: Path) -> list[str]:
    # -I: the child imports only installed packages, never modules from the working directory.
    return [sys.executable, "-I", "-m", "app.tasks.pod5_reader", str(path)]


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-STDERR_TAIL_LINES:])


def read_in_child(path: Path, timeout: int) -> tuple[dict[str, Any], str]:
    """(summary document, the child's stderr); raises JobFailure with a user-facing reason."""
    try:
        proc = subprocess.run(reader_command(path), capture_output=True, text=True, errors="replace",
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise JobFailure(f"Reading the POD5 file took longer than {timeout:,} s and was stopped "
                         "(ARVA_TOOL_TIMEOUT_SECONDS).", "pod5_timeout", seconds=timeout) from exc
    if proc.returncode < 0:
        try:
            name = signal.Signals(-proc.returncode).name
        except ValueError:
            name = f"signal {-proc.returncode}"
        raise JobFailure(f"The pod5 library crashed while reading this file ({name}); the file is probably damaged. "
                         "Compare it with the original copy. The file itself was not changed.",
                         "pod5_crashed", file=name)
    lines = proc.stdout.strip().splitlines()
    try:
        result = json.loads(lines[-1]) if proc.returncode == 0 and lines else None
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict) or not ("document" in result or "error" in result):
        raise JobFailure(f"Reading the POD5 file failed unexpectedly (exit code {proc.returncode}):\n"
                         f"{_tail(proc.stderr) or '(no output)'}")
    if "error" in result:
        raise JobFailure(str(result["error"]))
    return result["document"], proc.stderr


def _body(ctx: JobContext) -> None:
    (raw,) = ctx.input_files()
    if not is_raw_signal(raw):
        raise JobFailure(f"{raw.original_filename} is not a POD5 file", "not_pod5", file=raw.original_filename)
    versions = {**pod5_versions(), "pyarrow": installed_version("pyarrow"), "numpy": installed_version("numpy")}
    if versions["pod5"] is None:
        raise JobFailure(f"The pod5 library is not installed on this worker. Install it with: {POD5_INSTALL}",
                         "pod5_missing", install=POD5_INSTALL)
    ctx.log("Libraries: " + ", ".join(f"{k} {v}" for k, v in versions.items()))
    if versions["pod5"] != ctx.job.tool_version:
        ctx.log(f"Note: pod5 {versions['pod5']} is installed now ({ctx.job.tool_version} when queued)")
        ctx.job.tool_version = versions["pod5"] or "unknown"
    params = ctx.job.parameters or {}
    if params.get("lib_pod5_version") != versions["lib_pod5"]:
        ctx.job.parameters = {**params, "lib_pod5_version": versions["lib_pod5"]}
    ctx.log(f"Input: {raw.original_filename} ({raw.size_bytes} bytes, sha256 {raw.checksum_sha256})", flush=True)

    doc, stderr = read_in_child(ctx.path(raw.stored_path), get_settings().tool_timeout_seconds)
    if stderr.strip():
        ctx.log("pod5 messages (last lines):\n" + _tail(stderr))
    doc = {"input": {"file_id": raw.id, "filename": raw.original_filename, "sha256": raw.checksum_sha256,
                     "size_bytes": raw.size_bytes}, "software": versions, **doc}

    reads = doc["reads"]
    ctx.log(f"Read {reads['count']:,} reads in {doc['file']['batch_count']:,} batch(es) and "
            f"{doc['run_info_count']:,} run-information entr{'y' if doc['run_info_count'] == 1 else 'ies'}; "
            "signal was not decoded")
    for warning in doc["warnings"]:
        ctx.log(f"WARNING: {warning['text']}")
    out_rel = f"{ctx.results_rel}/pod5_summary.json"
    ctx.storage.write_text(out_rel, json.dumps(doc, indent=1, allow_nan=False))
    ctx.job.output_paths = [out_rel]
    ctx.job.result_summary = {
        **{k: doc[k] for k in ("schema", "file", "reads", "run_info_count", "run_infos", "run_infos_truncated", "warnings")},
        "withheld_fields": list(IDENTIFYING_FIELDS),
    }
    ctx.log(f"Result written to {out_rel}; {', '.join(IDENTIFYING_FIELDS)} are kept only there")


def run_pod5_summary_job(job_id: str) -> str:
    return run_job(job_id, _body)

