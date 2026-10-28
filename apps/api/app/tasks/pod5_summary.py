"""Worker task: run metadata of one POD5 raw-signal file, read with the official pod5 library.

Only the run-information table and the read table's num_samples, run_info and channel columns are
read. Signal is never decoded, so memory does not grow with the file size.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np

from app.services.raw_signal import POD5_INSTALL, is_raw_signal, pod5_versions
from app.tasks.common import JobContext, JobFailure, run_job

SCHEMA = "arva.pod5_summary/1"
MAX_RUN_INFOS = 50
MAX_ACQUISITIONS = 10_000
MAX_CHANNELS = 100_000
MAX_TEXT = 1024
MAX_MAP_ENTRIES = 200
SHOWN_FIELDS = (
    "acquisition_id", "acquisition_start_time", "protocol_start_time", "sample_id", "experiment_name",
    "flow_cell_id", "flow_cell_product_code", "sequencing_kit", "protocol_name", "protocol_run_id",
    "sample_rate", "software", "system_type", "sequencer_position_type",
)
# Host names, device serials and free-form maps (POD5 specification, run_info table).
IDENTIFYING_FIELDS = ("system_name", "sequencer_position", "context_tags", "tracking_id")
IDENTIFYING_NOTE = (
    "These run-information fields can identify people, computers or devices. ARVA keeps them only in this "
    "file and does not show them in the interface or in reports."
)


class _Values:
    """JSON-safe, bounded copies of values read from the file."""

    def __init__(self) -> None:
        self.clipped = False

    def __call__(self, v: Any) -> Any:
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, str):
            if len(v) > MAX_TEXT:
                self.clipped = True
                return v[:MAX_TEXT]
            return v
        if isinstance(v, list):  # Arrow map<utf8, utf8> rows arrive as (key, value) pairs
            if len(v) > MAX_MAP_ENTRIES:
                self.clipped = True
            return {self(k): self(x) for k, x in v[:MAX_MAP_ENTRIES]}
        return v


def _run_info_rows(reader) -> list[dict[str, Any]]:
    table = reader.run_info_table
    rows: list[dict[str, Any]] = []
    for i in range(table.num_record_batches):
        batch = table.get_batch(i)
        if len(rows) + batch.num_rows > MAX_ACQUISITIONS:
            raise JobFailure(f"The file lists more than {MAX_ACQUISITIONS:,} acquisitions; ARVA does not read it.")
        rows.extend(batch.to_pylist())
    return rows


def _scan_reads(reader) -> dict[str, Any]:
    per_acq: dict[str | None, list[int]] = {}
    channels: set[int] | None = set()
    reads = samples = 0
    lo: int | None = None
    hi: int | None = None
    for batch in reader.read_batches():
        cols = batch.columns
        # channel_32bit: the 16-bit field is 0 above channel 65535; the library falls back to it in older files.
        ns_col, acq_col, ch_col = cols.num_samples, cols.run_info, cols.channel_32bit
        if ns_col.null_count or acq_col.null_count or ch_col.null_count:
            raise JobFailure("The read table has reads without a sample count, run information or channel.")
        if len(ns_col) == 0:
            continue
        ns = ns_col.to_numpy()
        idx = acq_col.indices.to_numpy()
        names = acq_col.dictionary.to_pylist()
        for i in np.unique(idx):
            sel = idx == i
            entry = per_acq.setdefault(names[i], [0, 0])
            entry[0] += int(sel.sum())
            entry[1] += int(ns[sel].sum())
        if len(per_acq) > MAX_ACQUISITIONS:
            raise JobFailure(f"Reads refer to more than {MAX_ACQUISITIONS:,} acquisitions; ARVA does not read the file.")
        reads += len(ns)
        samples += int(ns.sum())
        lo = int(ns.min()) if lo is None else min(lo, int(ns.min()))
        hi = int(ns.max()) if hi is None else max(hi, int(ns.max()))
        if channels is not None:
            channels.update(np.unique(ch_col.to_numpy()).tolist())
            if len(channels) > MAX_CHANNELS:
                channels = None
    return {"per_acquisition": per_acq, "channels": channels, "reads": reads, "samples": samples, "min": lo, "max": hi}


def summarise_pod5(pod5, path) -> dict[str, Any]:
    """Everything ARVA records about one POD5 file; `pod5` is the imported library module."""
    value = _Values()
    warnings: list[str] = []
    with pod5.Reader(path) as reader:
        batch_count = int(reader.batch_count)
        file_info = {
            "writing_software": value(reader.writing_software),
            "file_identifier": str(reader.file_identifier),
            "file_version": str(reader.file_version),
            "original_file_version": str(reader.original_file_version),
            "is_vbz_compressed": bool(reader.is_vbz_compressed),
            "batch_count": batch_count,
            # Reader.num_reads raises on a file without read batches.
            "num_reads": int(reader.num_reads) if batch_count > 0 else 0,
        }
        rows = _run_info_rows(reader)
        scan = _scan_reads(reader)

    rates: dict[str | None, int] = {}
    for row in rows:
        rates.setdefault(row.get("acquisition_id"), int(row.get("sample_rate") or 0))
    if len(rates) < len(rows):
        warnings.append(f"{len(rows) - len(rates):,} acquisition ID(s) appear more than once in the run information; "
                        "the first entry of each is used.")

    per_acq = scan["per_acquisition"]
    duration = 0.0
    unknown_rate_reads = 0
    for acq, (n_reads, n_samples) in per_acq.items():
        rate = rates.get(acq, 0)
        if rate > 0:
            duration += n_samples / rate
        else:
            unknown_rate_reads += n_reads
    if unknown_rate_reads:
        warnings.append(
            f"{unknown_rate_reads:,} read(s) belong to acquisitions without run information or sample rate, so the "
            "signal duration is not reported."
        )
    if scan["reads"] == 0:
        warnings.append("The file contains no reads.")
    elif file_info["num_reads"] != scan["reads"]:
        warnings.append(
            f"pod5 reports {file_info['num_reads']:,} reads (it assumes equally sized batches); ARVA counted "
            f"{scan['reads']:,} reads in the read table."
        )
    if scan["channels"] is None:
        warnings.append(f"More than {MAX_CHANNELS:,} distinct channels; they were not counted.")

    run_infos, identifying = [], []
    for row in rows[:MAX_RUN_INFOS]:
        n_reads, n_samples = per_acq.get(row.get("acquisition_id"), (0, 0))
        rate = int(row.get("sample_rate") or 0)
        run_infos.append({
            **{f: value(row.get(f)) for f in SHOWN_FIELDS},
            "reads": n_reads,
            "samples": n_samples,
            "signal_duration_s": round(n_samples / rate, 3) if rate > 0 else None,
        })
        identifying.append({"acquisition_id": value(row.get("acquisition_id")),
                            **{f: value(row.get(f)) for f in IDENTIFYING_FIELDS}})
    if value.clipped:
        warnings.append(f"Some run-information values were longer than {MAX_TEXT:,} characters or "
                        f"{MAX_MAP_ENTRIES} entries and were shortened.")

    return {
        "schema": SCHEMA,
        "signal_decoded": False,
        "file": file_info,
        "reads": {
            "count": scan["reads"],
            "total_samples": scan["samples"],
            "min_samples": scan["min"],
            "max_samples": scan["max"],
            "distinct_channels": None if scan["channels"] is None else len(scan["channels"]),
            "acquisitions": len(per_acq),
            "total_signal_duration_s": None if unknown_rate_reads else round(duration, 3),
        },
        "run_info_count": len(rows),
        "run_infos": run_infos,
        "run_infos_truncated": len(rows) > MAX_RUN_INFOS,
        "warnings": warnings,
        "potentially_identifying": {"fields": list(IDENTIFYING_FIELDS), "note": IDENTIFYING_NOTE, "run_infos": identifying},
    }


def _body(ctx: JobContext) -> None:
    (raw,) = ctx.input_files()
    if not is_raw_signal(raw):
        raise JobFailure(f"{raw.original_filename} is not a POD5 file")
    try:
        import pod5
        import pyarrow
    except ImportError as exc:
        raise JobFailure(f"The pod5 library is not installed on this worker. Install it with: {POD5_INSTALL}") from exc

    versions = {**pod5_versions(), "pyarrow": pyarrow.__version__, "numpy": np.__version__}
    ctx.log("Libraries: " + ", ".join(f"{k} {v}" for k, v in versions.items()))
    if versions["pod5"] != ctx.job.tool_version:
        ctx.log(f"Note: pod5 {versions['pod5']} is installed now ({ctx.job.tool_version} when queued)")
        ctx.job.tool_version = versions["pod5"] or "unknown"
    params = ctx.job.parameters or {}
    if params.get("lib_pod5_version") != versions["lib_pod5"]:
        ctx.job.parameters = {**params, "lib_pod5_version": versions["lib_pod5"]}
    ctx.log(f"Input: {raw.original_filename} ({raw.size_bytes} bytes, sha256 {raw.checksum_sha256})", flush=True)

    try:
        doc = summarise_pod5(pod5, ctx.path(raw.stored_path))
    except (RuntimeError, pyarrow.ArrowException) as exc:
        raise JobFailure(f"pod5 {versions['pod5']} could not read this file: {exc}") from exc
    doc = {"input": {"file_id": raw.id, "filename": raw.original_filename, "sha256": raw.checksum_sha256,
                     "size_bytes": raw.size_bytes}, "software": versions, **doc}

    reads = doc["reads"]
    ctx.log(f"Read {reads['count']:,} reads in {doc['file']['batch_count']:,} batch(es) and "
            f"{doc['run_info_count']:,} run-information entr{'y' if doc['run_info_count'] == 1 else 'ies'}; "
            "signal was not decoded")
    for warning in doc["warnings"]:
        ctx.log(f"WARNING: {warning}")
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

