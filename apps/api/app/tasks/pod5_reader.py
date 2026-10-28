"""Run metadata of one POD5 file, read with the official pod5 library in a short-lived child process.

Run as `python -I -m app.tasks.pod5_reader FILE`: a damaged file can crash the native code in lib_pod5 or
pyarrow, and only this process dies then. Prints one JSON line, {"document": …} or {"error": message}.
Only the run-information table and the read table's num_samples, run_info and channel columns are read;
signal is never decoded, so memory does not grow with the file size. No database or web imports here.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

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


# English text of the summary's warnings; the interface translates them by code (pod5.msg.<code>).
WARNINGS = {
    "duplicate_acquisitions": "{count} acquisition ID(s) appear more than once in the run information; the first "
                              "entry of each is used.",
    "unknown_sample_rate": "{count} read(s) belong to acquisitions without run information or sample rate, so the "
                           "signal duration is not reported.",
    "no_reads": "The file contains no reads.",
    "read_count_differs": "pod5 reports {reported} reads (it assumes equally sized batches); ARVA counted {counted} "
                          "reads in the read table.",
    "channels_not_counted": "More than {limit} distinct channels; they were not counted.",
    "values_shortened": "Some run-information values were longer than {chars} characters or {entries} entries and "
                        "were shortened.",
}


def _warning(code: str, **params: str | int) -> dict[str, Any]:
    return {"code": code, "params": params, "text": WARNINGS[code].format(**params)}


class Pod5ReadError(Exception):
    """ARVA declines to summarise the file; the message is shown to the user."""


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
        # Converting unvalidated Arrow data from a damaged file can crash the process instead of raising.
        batch.validate(full=True)
        if len(rows) + batch.num_rows > MAX_ACQUISITIONS:
            raise Pod5ReadError(f"The file lists more than {MAX_ACQUISITIONS:,} acquisitions; ARVA does not read it.")
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
        for col in (ns_col, acq_col, ch_col):
            col.validate(full=True)
        if ns_col.null_count or acq_col.null_count or ch_col.null_count:
            raise Pod5ReadError("The read table has reads without a sample count, run information or channel.")
        if len(ns_col) == 0:
            continue
        if not hasattr(acq_col, "indices"):
            acq_col = acq_col.dictionary_encode()
        ns = ns_col.to_numpy()
        idx = acq_col.indices.to_numpy()
        names = acq_col.dictionary.to_pylist()
        for i in np.unique(idx):
            sel = idx == i
            entry = per_acq.setdefault(names[i], [0, 0])
            entry[0] += int(sel.sum())
            entry[1] += int(ns[sel].sum())
        if len(per_acq) > MAX_ACQUISITIONS:
            raise Pod5ReadError(f"Reads refer to more than {MAX_ACQUISITIONS:,} acquisitions; ARVA does not read the file.")
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
    warnings: list[dict[str, Any]] = []
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
        warnings.append(_warning("duplicate_acquisitions", count=f"{len(rows) - len(rates):,}"))

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
        warnings.append(_warning("unknown_sample_rate", count=f"{unknown_rate_reads:,}"))
    if scan["reads"] == 0:
        warnings.append(_warning("no_reads"))
    elif file_info["num_reads"] != scan["reads"]:
        warnings.append(_warning("read_count_differs", reported=f"{file_info['num_reads']:,}", counted=f"{scan['reads']:,}"))
    if scan["channels"] is None:
        warnings.append(_warning("channels_not_counted", limit=f"{MAX_CHANNELS:,}"))

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
        warnings.append(_warning("values_shortened", chars=f"{MAX_TEXT:,}", entries=MAX_MAP_ENTRIES))

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


def main(argv: list[str]) -> int:
    import pod5
    import pyarrow

    version = metadata.version("pod5")
    try:
        result: dict[str, Any] = {"document": summarise_pod5(pod5, Path(argv[1]))}
    except Pod5ReadError as exc:
        result = {"error": str(exc)}
    except pyarrow.ArrowInvalid as exc:
        result = {"error": f"The POD5 file is damaged (pod5 {version}: {exc}). Compare it with the original copy."}
    except (RuntimeError, OSError, ValueError, OverflowError, pyarrow.ArrowException) as exc:
        result = {"error": f"pod5 {version} could not read this file: {exc}"}
    sys.stdout.write("\n" + json.dumps(result, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
