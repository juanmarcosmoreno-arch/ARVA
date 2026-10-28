"""Sequence tracks for the Genome Explorer: windowed GC content and GC skew, sequence slices (reverse complement on
the minus strand), a read-depth profile in fixed bins, and a check of an annotator's protein against the genome.

Definitions (docs/scientific-methods.md, "Genome Explorer"):

* The API uses 1-based inclusive coordinates, as GFF3 does; the functions here take 0-based half-open ranges unless
  they say otherwise.
* Windows lie on a grid fixed to the sequence start: window k covers bases [k*step, k*step + window), so a value does
  not change when the view is panned. A window running past the sequence end is cut there (it has fewer bases);
  windows do not wrap around the origin of a circular sequence.
* GC = (G + C) / (A + C + G + T) over unambiguous bases (as in arva_core.assembly_stats); None for a window without
  any. GC skew = (G - C) / (G + C); None for a window without G or C.
* When more windows overlap the view than points are asked for, g consecutive windows form one point, which gives the
  mean, minimum and maximum of their values (windows without a value are left out).
* Read depth: the per-base depths of an alignment are summed in bins of a fixed number of bases; a point's depth is
  the sum of its bins divided by the bases they span (minimum and maximum: of the bins' mean depths).
* Proteins are never translated for display: the annotator's own protein is shown. `protein_check` only says whether
  the annotator's protein equals the translation of the genome at the feature's coordinates.
"""
from __future__ import annotations

import json
import math
import warnings
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

MAX_WINDOWS = 2_000_000
MAX_POINTS = 5_000
MIN_AUTO_WINDOW = 20
PROFILE_FORMAT = "arva-depth-profile"
PROFILE_VERSION = 1

_CLASS = np.zeros(256, dtype=np.uint8)
for _base, _cls in ((b"G", 1), (b"g", 1), (b"C", 2), (b"c", 2), (b"A", 3), (b"a", 3), (b"T", 3), (b"t", 3)):
    _CLASS[_base[0]] = _cls

_COMPLEMENT = bytes.maketrans(b"ACGTUMRWSYKVHDBNacgtumrwsykvhdbn", b"TGCAAKYWSRMBDHVNtgcaakywsrmbdhvn")

# NCBI genetic codes (gc.prt) as Biopython 1.88 distributes them (Bio.Data.CodonTable), checked 2026-10-28: amino
# acids and start codons for the 64 codons in TCAG order (TTT, TTC, TTA, TTG, TCT, ...). These are the tables Bakta
# and Prokka accept (11 bacteria and archaea, 4 Mycoplasma/Spiroplasma, 25 SR1 and Gracilibacteria).
_GENETIC_CODES = {
    11: ("FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
         "---M---------------M------------MMMM---------------M------------"),
    4: ("FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
        "--MM---------------M------------MMMM---------------M------------"),
    25: ("FFLLSSSSYY**CCGWLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
         "---M-------------------------------M---------------M------------"),
}
TRANSLATION_TABLES = tuple(_GENETIC_CODES)
_TCAG = "TCAG"


def _codon_table(table: int) -> tuple[dict[str, str], frozenset[str]]:
    if table not in _GENETIC_CODES:
        raise ValueError(f"translation table must be one of {', '.join(map(str, TRANSLATION_TABLES))}")
    aas, starts = _GENETIC_CODES[table]
    codons = [a + b + c for a in _TCAG for b in _TCAG for c in _TCAG]
    return dict(zip(codons, aas, strict=True)), frozenset(c for c, s in zip(codons, starts, strict=True) if s == "M")


# --- Windows ---------------------------------------------------------------------------------------------------

def _check_range(length: int, start: int, end: int) -> None:
    if not 0 <= start < end <= length:
        raise ValueError(f"the range must lie within the sequence (0 <= start < end <= {length})")


def window_range(length: int, start: int, end: int, window: int, step: int) -> tuple[int, int]:
    """First and last index k of the grid windows [k*step, k*step + window) that overlap [start, end)."""
    if window < 1 or not 1 <= step <= window:
        raise ValueError("window must be at least 1 bp and step 1 bp to window (no gaps between windows)")
    _check_range(length, start, end)
    first = max(0, -(-(start - window + 1) // step))
    last = min((end - 1) // step, (length - 1) // step)
    return first, last


def auto_window(span: int, points: int, minimum: int = MIN_AUTO_WINDOW) -> int:
    """The smallest 1-2-5 number of bases (at least `minimum`) that covers `span` in at most `points` windows."""
    target = max(minimum, math.ceil(span / max(points, 1)))
    magnitude = 10 ** max(0, math.floor(math.log10(target)))
    for m in (1, 2, 5, 10):
        if m * magnitude >= target:
            return m * magnitude
    return 10 * magnitude


def _group(values: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(values)
    rows = -(-n // size)
    padded = np.full(rows * size, np.nan)
    padded[:n] = values
    padded = padded.reshape(rows, size)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(padded, axis=1), np.nanmin(padded, axis=1), np.nanmax(padded, axis=1)


def _values(a: np.ndarray, digits: int = 6) -> list[float | None]:
    return [None if math.isnan(v) else round(float(v), digits) for v in a]


def gc_windows(seq: bytes, start: int, end: int, window: int, step: int, max_points: int = MAX_POINTS) -> dict[str, Any]:
    """GC and GC skew of the grid windows overlapping [start, end) of `seq`, in at most `max_points` points.

    Returns 1-based inclusive `start`/`end` of each point (the first window's start, the last window's end), the
    mean (`gc`, `skew`), minimum and maximum of its windows' values, and `windows` (windows computed) and `group`
    (windows per point)."""
    if not 1 <= max_points <= MAX_POINTS:
        raise ValueError(f"points must be 1-{MAX_POINTS}")
    first, last = window_range(len(seq), start, end, window, step)
    n = last - first + 1
    if n > MAX_WINDOWS:
        raise ValueError(f"{n:,} windows would be computed (at most {MAX_WINDOWS:,}): use a larger step or a "
                         "smaller region")
    ws = np.arange(first, last + 1, dtype=np.int64) * step
    we = np.minimum(ws + window, len(seq))
    lo, hi = int(ws[0]), int(we.max())
    classes = _CLASS[np.frombuffer(seq, dtype=np.uint8, count=hi - lo, offset=lo)]
    bounds = np.unique(np.concatenate((ws, we))) - lo
    at_start, at_end = np.searchsorted(bounds, ws - lo), np.searchsorted(bounds, we - lo)

    def counts(cls: int) -> np.ndarray:
        prefix = np.concatenate(([0], np.cumsum(np.add.reduceat(classes == cls, bounds[:-1], dtype=np.int64))))
        return prefix[at_end] - prefix[at_start]

    g, c, at = counts(1), counts(2), counts(3)
    acgt, gc = g + c + at, g + c
    with np.errstate(invalid="ignore", divide="ignore"):
        gc_frac = np.where(acgt > 0, gc / np.where(acgt > 0, acgt, 1), np.nan)
        skew = np.where(gc > 0, (g - c) / np.where(gc > 0, gc, 1), np.nan)
    size = -(-n // max_points)
    gc_mean, gc_min, gc_max = _group(gc_frac, size)
    sk_mean, sk_min, sk_max = _group(skew, size)
    starts = ws[::size] + 1
    ends = we[np.minimum(np.arange(len(starts)) * size + size, n) - 1]
    return {"window": window, "step": step, "windows": n, "group": size, "start": starts.tolist(),
            "end": ends.tolist(), "gc": _values(gc_mean), "gc_min": _values(gc_min), "gc_max": _values(gc_max),
            "skew": _values(sk_mean), "skew_min": _values(sk_min), "skew_max": _values(sk_max)}


def gc_fraction(seq: bytes) -> float | None:
    """(G + C) / (A + C + G + T) of the whole sequence, None without unambiguous bases."""
    counts = np.bincount(_CLASS[np.frombuffer(seq, dtype=np.uint8)], minlength=4)
    acgt = int(counts[1:].sum())
    return round(int(counts[1] + counts[2]) / acgt, 6) if acgt else None


# --- Sequence slices and proteins -------------------------------------------------------------------------------

def reverse_complement(seq: bytes) -> bytes:
    """Reverse complement with the IUPAC codes (M<->K, R<->Y, B<->V, D<->H; W, S, N unchanged), case kept."""
    return seq.translate(_COMPLEMENT)[::-1]


def slice_sequence(seq: bytes, start: int, end: int, strand: str = "+", circular: bool = False) -> bytes:
    """Bases start..end (1-based, inclusive) of `seq`, reverse complemented for strand "-". On a circular sequence a
    range with start > end runs across the origin (start..length, then 1..end)."""
    if strand not in ("+", "-"):
        raise ValueError("strand must be + or -")
    n = len(seq)
    if not (1 <= start <= n and 1 <= end <= n):
        raise ValueError(f"coordinates must lie within 1-{n}")
    if start > end and not circular:
        raise ValueError("start must not be after end on a linear sequence")
    part = seq[start - 1:end] if start <= end else seq[start - 1:] + seq[:end]
    return reverse_complement(part) if strand == "-" else part


def translate(nt: str, table: int, first_is_start: bool = True) -> str:
    """Amino acids of the codons of `nt` (a multiple of 3) with an NCBI genetic code; a start codon of the table in
    the first position reads M when `first_is_start`; a codon with any base other than A, C, G or T reads X."""
    if len(nt) % 3:
        raise ValueError("the length is not a multiple of 3")
    codons, starts = _codon_table(table)
    nt = nt.upper().replace("U", "T")
    out = [codons.get(nt[i:i + 3], "X") for i in range(0, len(nt), 3)]
    if first_is_start and out and nt[:3] in starts:
        out[0] = "M"
    return "".join(out)


def protein_check(genome_nt: str, protein: str, table: int, partial: str | None, pseudo: bool) -> dict[str, Any]:
    """Whether the annotator's protein equals ARVA's translation of the genome at the feature's coordinates.

    Not checked for pseudogenes (their reading frame is broken by definition) or a length that is not a multiple of
    3. A CDS truncated at its 5' end does not begin with a start codon, so its first codon is read as an ordinary
    codon. One stop codon at the end is ignored on both sides."""
    base = {"table": table, "status": "not_checked", "reason": None, "first_difference": None}
    if pseudo:
        return {**base, "reason": "pseudogene"}
    if len(genome_nt) % 3:
        return {**base, "reason": "length"}
    ours = translate(genome_nt, table, first_is_start=partial not in ("5'", "both", "unknown"))
    ours, theirs = ours.removesuffix("*"), protein.strip().upper().removesuffix("*")
    if ours == theirs:
        return {**base, "status": "match"}
    diff = next((i for i, (a, b) in enumerate(zip(ours, theirs, strict=False)) if a != b), min(len(ours), len(theirs)))
    return {**base, "status": "differs", "first_difference": diff + 1, "translated_length": len(ours),
            "protein_length": len(theirs), "internal_stops": ours.count("*")}


# --- Read-depth profile ----------------------------------------------------------------------------------------

def depth_bins(rows: Iterable[tuple[str, int, int]], lengths: Mapping[str, int], resolution: int) -> dict[str, list[int]]:
    """The sum of per-base depths (contig, 1-based position, depth) in bins of `resolution` bases of each contig;
    positions that are not listed count as depth 0."""
    if resolution < 1:
        raise ValueError("resolution must be at least 1 bp")
    sums = {name: [0] * -(-length // resolution) for name, length in lengths.items()}
    for contig, pos, depth in rows:
        bins = sums.get(contig)
        if bins is None:
            raise ValueError(f"depth reported for {contig!r}, which is not a sequence of the assembly")
        if not 1 <= pos <= lengths[contig] or depth < 0:
            raise ValueError(f"position {pos} or depth {depth} out of range on {contig!r}")
        bins[(pos - 1) // resolution] += depth
    return sums


def parse_depth_lines(lines: Iterable[str]) -> Iterable[tuple[str, int, int]]:
    """(contig, position, depth) of `samtools depth` output with one alignment file (three columns)."""
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3:
            raise ValueError(f"line {n} of the depth output has {len(parts)} columns, expected 3")
        yield parts[0], int(parts[1]), int(parts[2])


def depth_points(sums: list[int], length: int, resolution: int, start: int, end: int,
                 max_points: int = MAX_POINTS) -> dict[str, Any]:
    """Mean read depth of the profile's bins that overlap [start, end), in at most `max_points` points."""
    if not 1 <= max_points <= MAX_POINTS:
        raise ValueError(f"points must be 1-{MAX_POINTS}")
    _check_range(length, start, end)
    first, last = start // resolution, (end - 1) // resolution
    s = np.asarray(sums[first:last + 1], dtype=np.float64)
    bs = np.arange(first, last + 1, dtype=np.int64) * resolution
    be = np.minimum(bs + resolution, length)
    size = -(-len(s) // max_points)
    rows = -(-len(s) // size)
    pad = rows * size - len(s)
    total = np.concatenate((s, np.zeros(pad))).reshape(rows, size).sum(axis=1)
    bases = np.concatenate((be - bs, np.zeros(pad, dtype=np.int64))).reshape(rows, size).sum(axis=1)
    _, low, high = _group(s / (be - bs), size)
    return {"resolution": resolution, "group": size, "start": (bs[::size] + 1).tolist(),
            "end": be[np.minimum(np.arange(rows) * size + size, len(s)) - 1].tolist(),
            "mean": _values(total / bases, 3), "min": _values(low, 3), "max": _values(high, 3)}


def write_depth_profile(path: Path, sums: Mapping[str, list[int]], lengths: Mapping[str, int], resolution: int,
                        source: Mapping[str, Any]) -> None:
    contigs = [{"name": name, "length": lengths[name], "mean_depth": round(sum(b) / lengths[name], 3) if lengths[name]
                else None, "sums": b} for name, b in sums.items()]
    path.write_text(json.dumps({"format": PROFILE_FORMAT, "version": PROFILE_VERSION, "resolution": resolution,
                                "source": dict(source), "contigs": contigs}, separators=(",", ":")))


def read_depth_profile(path: Path) -> dict[str, Any]:
    """A profile written by write_depth_profile, checked for shape; ValueError when it is not one."""
    data = json.loads(path.read_text())
    if data.get("format") != PROFILE_FORMAT or data.get("version") != PROFILE_VERSION:
        raise ValueError("not an ARVA depth profile of a known version")
    resolution = data.get("resolution")
    if not isinstance(resolution, int) or resolution < 1:
        raise ValueError("the profile has no valid resolution")
    for c in data.get("contigs", []):
        if not isinstance(c.get("length"), int) or len(c.get("sums", [])) != -(-c["length"] // resolution):
            raise ValueError(f"the profile of {c.get('name')!r} does not match its length")
    return data
