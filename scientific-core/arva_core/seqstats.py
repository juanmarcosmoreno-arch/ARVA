"""Streaming validation and statistics for FASTQ and FASTA files.

Every number produced here is computed directly from the records in the input
file. Files are streamed record by record, so memory use depends on the number
of distinct read lengths, not on file size.

Quality conventions
-------------------
* Phred+33 encoding is assumed (Sanger / Illumina 1.8+ / ONT / PacBio).
* Per-read mean quality averages the read's per-base *error probabilities*
  and converts the average back to the Phred scale (NanoPlot computes its
  per-read values the same way). An arithmetic mean of base Phred scores
  would overestimate read accuracy.
* The file-level ``mean_read_quality`` is the arithmetic mean of those
  per-read values over reads with length > 0. It is not NanoPlot's "Mean read
  quality", which averages the per-read values again in error-probability
  space and so is never higher than this arithmetic mean.
"""
from __future__ import annotations

import gzip
import math
import random
import zlib
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from arva_core import __version__
from arva_core.formats import FormatInfo, SequenceFormat, open_sequence_file, sniff_format

TOOL_NAME = "arva-core.seqstats"
TOOL_VERSION = __version__
SCHEMA_VERSION = 1

PHRED_OFFSET = 33
MAX_PHRED = 93
_ERROR_PROB = 10.0 ** (-np.arange(MAX_PHRED + 1) / 10.0)

_IUPAC = b"ACGTUNRYKMSWBDHVacgtunrykmswbdhv"
_QUAL_CHARS = bytes(range(PHRED_OFFSET, PHRED_OFFSET + MAX_PHRED + 1))

READ_QUALITY_THRESHOLDS = (7, 10, 12, 15, 20, 30)
LENGTH_THRESHOLDS = (100, 500, 1_000, 5_000, 10_000, 20_000, 50_000, 100_000)
MAX_CUMULATIVE_POINTS = 200
# Header text kept by quick_validate; very long headers (e.g. Dorado move tables) end the collection early.
MAX_HEADER_BYTES = 8 * 1024 * 1024

Record = tuple[bytes, bytes, bytes | None, int]


class SequenceFormatError(ValueError):
    """Raised when a file does not conform to the expected sequence format."""

    def __init__(self, message: str, line_number: int | None = None):
        self.line_number = line_number
        self.reason = message
        super().__init__(f"line {line_number}: {message}" if line_number else message)


@dataclass
class StatsParameters:
    length_bins: int = 50
    position_limit: int = 1000
    sample_size: int = 2000
    random_seed: int = 20240501
    expected_genome_size_bp: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Parsers ------------------------------------------------------------------

def iter_fastq(handle: BinaryIO) -> Iterator[Record]:
    """Yield (header, sequence, quality, line_number) from strict 4-line FASTQ."""
    readline = handle.readline
    line_no = 0
    while True:
        header = readline()
        if not header:
            return
        line_no += 1
        header = header.rstrip(b"\r\n")
        if not header.strip():
            blank_at = line_no
            for extra in handle:
                if extra.strip():
                    raise SequenceFormatError("blank line inside FASTQ content", blank_at)
            return
        start = line_no
        if header[:1] != b"@":
            raise SequenceFormatError("FASTQ record header must start with '@'", start)

        seq = readline()
        plus = readline()
        qual = readline()
        if not seq or not plus or not qual:
            raise SequenceFormatError(
                "truncated FASTQ record (expected 4 lines: header, sequence, '+', quality)", start
            )
        line_no += 3
        if plus[:1] != b"+":
            raise SequenceFormatError(
                "expected '+' separator line; multi-line FASTQ is not supported", start + 2
            )
        seq = seq.rstrip(b"\r\n")
        qual = qual.rstrip(b"\r\n")
        if len(seq) != len(qual):
            raise SequenceFormatError(
                f"sequence length ({len(seq)}) differs from quality length ({len(qual)})", start + 3
            )
        if seq.translate(None, _IUPAC):
            bad = sorted(set(seq.translate(None, _IUPAC).decode("latin-1")))
            raise SequenceFormatError(f"invalid nucleotide characters {bad}", start + 1)
        if qual.translate(None, _QUAL_CHARS):
            raise SequenceFormatError("quality string contains characters outside Phred+33 range", start + 3)
        yield header, seq, qual, start


def iter_fasta(handle: BinaryIO) -> Iterator[Record]:
    """Yield (header, sequence, None, line_number) from (multi-line) nucleotide FASTA."""
    header: bytes | None = None
    chunks: list[bytes] = []
    start = 0
    for line_no, raw in enumerate(handle, start=1):
        line = raw.strip()
        if not line or line[:1] == b";":
            continue
        if line[:1] == b">":
            if header is not None:
                yield header, b"".join(chunks), None, start
            header, chunks, start = line, [], line_no
            continue
        if header is None:
            raise SequenceFormatError("sequence data found before the first '>' header", line_no)
        if line.translate(None, _IUPAC):
            bad = sorted(set(line.translate(None, _IUPAC).decode("latin-1")))
            raise SequenceFormatError(
                f"invalid nucleotide characters {bad} (protein or aligned FASTA is not supported here)",
                line_no,
            )
        chunks.append(line)
    if header is not None:
        yield header, b"".join(chunks), None, start


def iter_records(handle: BinaryIO, fmt: SequenceFormat) -> Iterator[Record]:
    if fmt is SequenceFormat.fastq:
        return iter_fastq(handle)
    if fmt is SequenceFormat.fasta:
        return iter_fasta(handle)
    raise SequenceFormatError("unrecognised format: expected FASTQ ('@') or FASTA ('>') content")


# --- Accumulation -------------------------------------------------------------

class _Accumulator:
    def __init__(self, params: StatsParameters, has_quality: bool):
        self.params = params
        self.has_quality = has_quality
        self.read_count = 0
        self.total_bases = 0
        self.zero_length = 0
        self.length_counts: Counter[int] = Counter()
        self.gc_bases = 0
        self.at_bases = 0
        self.ambiguous_bases = 0
        self.gc_hist = np.zeros(101, dtype=np.int64)
        self.rng = random.Random(params.random_seed)
        self.reservoir: list[list[float | int | None]] = []
        if has_quality:
            self.base_q_hist = np.zeros(MAX_PHRED + 1, dtype=np.int64)
            self.read_q_hist: Counter[int] = Counter()  # key = floor(meanQ * 10)
            self.read_q_sum = 0.0
            self.reads_above = {t: 0 for t in READ_QUALITY_THRESHOLDS}
            self.total_error = 0.0
            self.pos_sum = np.zeros(params.position_limit, dtype=np.float64)
            self.pos_count = np.zeros(params.position_limit, dtype=np.int64)

    def add(self, seq: bytes, qual: bytes | None) -> None:
        length = len(seq)
        self.read_count += 1
        self.total_bases += length
        self.length_counts[length] += 1
        if length == 0:
            self.zero_length += 1
            return

        upper = seq.upper()
        gc = upper.count(b"G") + upper.count(b"C")
        at = upper.count(b"A") + upper.count(b"T") + upper.count(b"U")
        self.gc_bases += gc
        self.at_bases += at
        self.ambiguous_bases += length - gc - at
        gc_pct: float | None = None
        if gc + at:
            gc_pct = 100.0 * gc / (gc + at)
            self.gc_hist[round(gc_pct)] += 1

        mean_q: float | None = None
        if self.has_quality and qual is not None:
            q = np.frombuffer(qual, dtype=np.uint8) - PHRED_OFFSET
            self.base_q_hist += np.bincount(q, minlength=MAX_PHRED + 1)
            err_sum = float(_ERROR_PROB[q].sum())
            self.total_error += err_sum
            mean_q = -10.0 * math.log10(err_sum / length)
            self.read_q_hist[int(mean_q * 10)] += 1
            self.read_q_sum += mean_q
            for t in READ_QUALITY_THRESHOLDS:
                if mean_q >= t:
                    self.reads_above[t] += 1
            n = min(length, self.params.position_limit)
            self.pos_sum[:n] += q[:n]
            self.pos_count[:n] += 1

        point = [
            length,
            round(mean_q, 2) if mean_q is not None else None,
            round(gc_pct, 2) if gc_pct is not None else None,
        ]
        k = self.params.sample_size
        if len(self.reservoir) < k:
            self.reservoir.append(point)
        else:
            j = self.rng.randrange(self.read_count)
            if j < k:
                self.reservoir[j] = point

    # --- finalisation ---------------------------------------------------------

    def finalize(self, info: FormatInfo) -> dict[str, Any]:
        if self.read_count == 0:
            raise SequenceFormatError("file contains no sequence records")

        asc = sorted(self.length_counts.items())
        desc = asc[::-1]
        n = self.read_count
        total = self.total_bases
        acgt = self.gc_bases + self.at_bases

        n50, l50 = _nx(desc, total, 0.5)
        n90, l90 = _nx(desc, total, 0.9)
        warnings: list[str] = []
        messages: list[dict[str, Any]] = []
        if self.zero_length:
            warnings.append(f"{self.zero_length} record(s) have zero length.")
            messages.append({"code": "zero_length", "params": {"count": self.zero_length}, "text": warnings[-1]})

        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "parameters": self.params.as_dict(),
            "file": {"format": info.format.value, "compressed": info.compressed},
            "read_count": n,
            "zero_length_reads": self.zero_length,
            "total_bases": total,
            "min_length": asc[0][0],
            "max_length": asc[-1][0],
            "mean_length": total / n,
            "median_length": _median_from_counts(asc, n),
            "n50": n50,
            "l50": l50,
            "n90": n90,
            "l90": l90,
            "gc_percent": (100.0 * self.gc_bases / acgt) if acgt else 0.0,
            "ambiguous_bases": self.ambiguous_bases,
            "ambiguous_percent": (100.0 * self.ambiguous_bases / total) if total else 0.0,
            "length_histogram": _linear_histogram(asc, self.params.length_bins),
            "length_histogram_log": _log_histogram(asc, self.params.length_bins),
            "gc_histogram": [
                {"gc_percent": i, "reads": int(c)} for i, c in enumerate(self.gc_hist) if c
            ],
            "cumulative_yield": _cumulative_yield(desc),
            "length_thresholds": _length_thresholds(desc, total),
            "quality": self._quality_section(asc[-1][0], warnings, messages) if self.has_quality else None,
            "sample_points": {
                "description": "Uniform random sample of reads (reservoir sampling) for scatter plots.",
                "fields": ["length", "mean_quality", "gc_percent"],
                "seed": self.params.random_seed,
                "size": len(self.reservoir),
                "points": self.reservoir,
            },
            "coverage_estimate": None,
            "warnings": warnings,
            # The warnings with stable codes (zero_length, phred64_suspected) and their values.
            "messages": messages,
        }

        genome = self.params.expected_genome_size_bp
        if genome:
            result["coverage_estimate"] = {
                "expected_genome_size_bp": genome,
                "estimated_depth": total / genome,
                "note": (
                    "Total bases divided by the expected genome size supplied by the user. "
                    "Assumes every base derives from the target genome; host DNA, contamination "
                    "or high-copy plasmids make this an over-estimate of chromosomal depth."
                ),
            }
        return result

    def _quality_section(self, max_length: int, warnings: list[str],
                         messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        total_q_bases = int(self.base_q_hist.sum())
        if total_q_bases == 0:
            return None
        nonzero_reads = self.read_count - self.zero_length
        observed = np.nonzero(self.base_q_hist)[0]
        q_min, q_max = int(observed.min()), int(observed.max())
        if q_min >= 31 and 45 < q_max <= 72:
            warnings.append(
                f"Quality values look shifted (minimum Q{q_min}, maximum Q{q_max}); the file may use "
                "legacy Phred+64 encoding. ARVA interprets qualities as Phred+33."
            )
            messages.append({"code": "phred64_suspected", "params": {"min": q_min, "max": q_max}, "text": warnings[-1]})

        read_q_bins: Counter[int] = Counter()
        for key, count in self.read_q_hist.items():
            read_q_bins[key // 10] += count

        limit = self.params.position_limit
        covered = int(np.count_nonzero(self.pos_count))
        positions = {
            "position_limit": limit,
            "truncated": max_length > limit,
            "positions": list(range(1, covered + 1)),
            "mean_quality": [round(float(v), 3) for v in self.pos_sum[:covered] / self.pos_count[:covered]],
            "reads_covering": [int(v) for v in self.pos_count[:covered]],
        }

        return {
            "encoding": "phred+33",
            "min_base_quality": q_min,
            "max_base_quality": q_max,
            "mean_read_quality": self.read_q_sum / nonzero_reads,
            "median_read_quality": _median_from_counts(sorted(self.read_q_hist.items()), nonzero_reads)
            / 10.0,
            "mean_base_quality": -10.0 * math.log10(self.total_error / total_q_bases),
            "q20_bases_percent": 100.0 * float(self.base_q_hist[20:].sum()) / total_q_bases,
            "q30_bases_percent": 100.0 * float(self.base_q_hist[30:].sum()) / total_q_bases,
            "read_quality_histogram": [
                {"quality": q, "reads": c} for q, c in sorted(read_q_bins.items())
            ],
            "base_quality_histogram": [
                {"quality": int(q), "bases": int(self.base_q_hist[q])} for q in observed
            ],
            "reads_above_quality": [
                {
                    "threshold": t,
                    "reads": self.reads_above[t],
                    "percent": 100.0 * self.reads_above[t] / self.read_count,
                }
                for t in READ_QUALITY_THRESHOLDS
            ],
            "per_position": positions,
            "notes": [
                "Per-read mean quality averages per-base error probabilities, then converts to Phred.",
                "Median read quality is reported at a resolution of 0.1 Q.",
            ],
        }


# --- Helpers ------------------------------------------------------------------

def _median_from_counts(items: list[tuple[int, int]], n: int) -> float:
    """Median of a value->count distribution (items sorted ascending by value)."""
    if n <= 0:
        return 0.0
    lo_idx, hi_idx = (n - 1) // 2, n // 2
    lo_val = hi_val = None
    seen = 0
    for value, count in items:
        seen += count
        if lo_val is None and seen > lo_idx:
            lo_val = value
        if seen > hi_idx:
            hi_val = value
            break
    return (lo_val + hi_val) / 2.0


def _nx(desc: list[tuple[int, int]], total: int, fraction: float) -> tuple[int, int]:
    """Return (Nx length, Lx read count) for lengths sorted descending."""
    if total == 0:
        return 0, 0
    target = total * fraction
    cum_bases = 0
    cum_reads = 0
    for length, count in desc:
        needed = math.ceil((target - cum_bases) / length) if length else count
        if cum_bases + length * count >= target:
            return length, cum_reads + max(needed, 1)
        cum_bases += length * count
        cum_reads += count
    return desc[-1][0], cum_reads


def _linear_histogram(asc: list[tuple[int, int]], bins: int) -> dict[str, Any]:
    lo, hi = asc[0][0], asc[-1][0]
    span = hi - lo + 1
    width = max(1, math.ceil(span / bins))
    nbins = math.ceil(span / width)
    reads = [0] * nbins
    bases = [0] * nbins
    for length, count in asc:
        idx = (length - lo) // width
        reads[idx] += count
        bases[idx] += length * count
    return {
        "scale": "linear",
        "bin_width": width,
        "bin_edges": [lo + i * width for i in range(nbins + 1)],
        "reads": reads,
        "bases": bases,
    }


def _log_histogram(asc: list[tuple[int, int]], bins: int) -> dict[str, Any] | None:
    lo, hi = asc[0][0], asc[-1][0]
    if lo <= 0:
        positive = [(length, c) for length, c in asc if length > 0]
        if not positive:
            return None
        lo = positive[0][0]
        asc = positive
    if hi / lo < 10:
        return None
    edges = np.logspace(math.log10(lo), math.log10(hi + 1), bins + 1)
    lengths = np.array([length for length, _ in asc], dtype=np.float64)
    counts = np.array([c for _, c in asc], dtype=np.float64)
    reads, _ = np.histogram(lengths, bins=edges, weights=counts)
    bases, _ = np.histogram(lengths, bins=edges, weights=counts * lengths)
    return {
        "scale": "log10",
        "bin_edges": [round(float(e), 2) for e in edges],
        "reads": [int(v) for v in reads],
        "bases": [int(v) for v in bases],
    }


def _cumulative_yield(desc: list[tuple[int, int]]) -> list[dict[str, int]]:
    """Reads and bases retained when keeping only reads >= each length."""
    points = []
    cum_reads = cum_bases = 0
    for length, count in desc:
        cum_reads += count
        cum_bases += length * count
        points.append({"min_length": length, "reads": cum_reads, "bases": cum_bases})
    if len(points) <= MAX_CUMULATIVE_POINTS:
        return points
    step = (len(points) - 1) / (MAX_CUMULATIVE_POINTS - 1)
    idx = sorted({round(i * step) for i in range(MAX_CUMULATIVE_POINTS)})
    return [points[i] for i in idx]


def _length_thresholds(desc: list[tuple[int, int]], total: int) -> list[dict[str, Any]]:
    max_len = desc[0][0]
    out = []
    for t in LENGTH_THRESHOLDS:
        if t > max_len:
            break
        reads = sum(c for length, c in desc if length >= t)
        bases = sum(length * c for length, c in desc if length >= t)
        out.append(
            {
                "min_length": t,
                "reads": reads,
                "bases": bases,
                "bases_percent": 100.0 * bases / total if total else 0.0,
            }
        )
    return out


# --- Public API ---------------------------------------------------------------

_DECOMPRESSION_ERRORS = (gzip.BadGzipFile, EOFError, zlib.error)


def compute_sequence_stats(
    path: Path,
    params: StatsParameters | None = None,
    progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Validate and compute statistics for an entire FASTQ/FASTA file.

    Raises SequenceFormatError on the first structural problem, reporting the
    offending line number, so a partial or corrupt file never yields results.
    """
    params = params or StatsParameters()
    info = sniff_format(Path(path))
    if info.decompression_error:
        raise SequenceFormatError(
            f"compressed stream is corrupt or truncated ({info.decompression_error})"
        )
    if info.format is SequenceFormat.unknown:
        raise SequenceFormatError("unrecognised format: expected FASTQ ('@') or FASTA ('>') content")

    acc = _Accumulator(params, has_quality=info.format is SequenceFormat.fastq)
    try:
        with open_sequence_file(Path(path)) as fh:
            for i, (_header, seq, qual, _line) in enumerate(iter_records(fh, info.format), start=1):
                acc.add(seq, qual)
                if progress is not None and i % 100_000 == 0:
                    progress(i)
    except _DECOMPRESSION_ERRORS as exc:
        raise SequenceFormatError(f"compressed stream is corrupt or truncated ({exc})") from exc
    return acc.finalize(info)


@dataclass
class QuickValidation:
    format: SequenceFormat
    compressed: bool
    records_checked: int
    is_valid: bool
    message: str
    headers: list[bytes] = field(default_factory=list)
    # Stable code of the message, with its values, so an interface can show it in its own language.
    code: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def quick_validate(path: Path, max_records: int = 1000) -> QuickValidation:
    """Check format and the structure of the first `max_records` records.

    Intended for immediate feedback at import time; the full file is validated
    when statistics are computed. The header lines of the records read are
    returned (up to MAX_HEADER_BYTES) so the file is read only once.
    """
    info = sniff_format(Path(path))
    if info.decompression_error:
        return QuickValidation(
            info.format, info.compressed, 0, False,
            f"Compressed stream is corrupt or truncated ({info.decompression_error}).",
            code="corrupt", params={"detail": info.decompression_error},
        )
    if info.format is SequenceFormat.unknown:
        return QuickValidation(
            info.format, info.compressed, 0, False,
            "Unrecognised content: expected FASTQ (records starting with '@') or FASTA ('>').", code="unrecognised",
        )
    checked = 0
    headers: list[bytes] = []
    header_bytes = 0
    try:
        with open_sequence_file(Path(path)) as fh:
            for header, _seq, _qual, _line in iter_records(fh, info.format):
                checked += 1
                header_bytes += len(header)
                if header_bytes <= MAX_HEADER_BYTES:
                    headers.append(header)
                if checked >= max_records:
                    break
    except SequenceFormatError as exc:
        return QuickValidation(info.format, info.compressed, checked, False, str(exc), headers, "format_error",
                               {"detail": str(exc)})
    except _DECOMPRESSION_ERRORS as exc:
        return QuickValidation(
            info.format, info.compressed, checked, False, f"Compressed stream is corrupt ({exc}).", headers,
            "corrupt", {"detail": str(exc)},
        )
    if checked == 0:
        return QuickValidation(info.format, info.compressed, 0, False, "File contains no records.", code="no_records")
    return QuickValidation(
        info.format,
        info.compressed,
        checked,
        True,
        f"{info.format.value.upper()} structure verified on the first {checked} record(s); "
        "the whole file is validated when statistics are computed.",
        headers,
        "verified",
        {"format": info.format.value.upper(), "count": checked},
    )
