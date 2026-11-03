"""Sanger reads of one gene: chromatograms (.ab1), quality trimming, the forward + reverse consensus with its
evidence, and ARVA's reading of the similarity hits of the result (what gene or organism it is, and whether it is
what the user suspected).

The verified facts and design decisions behind every step are in docs/sanger-design-notes.md (Part 0); in short:

* Reading .ab1 (ABIF) files: Biopython 1.88 (`Bio.SeqIO.read(handle, "abi")`, `Bio/SeqIO/AbiIO.py`). The base calls
  are tag PBAS2, the Phred qualities PCON2 (Biopython's `phred_quality`), the scan position of each called base's
  peak PLOC2 and the processed trace of the four dye channels DATA9 to DATA12, whose bases are given in order by
  FWO_1 (checked on real reads: the highest channel at PLOC2 was the called base at 560 of 560 positions in each).
  A file whose qualities are all 0 (Biopython's ABI 310 test file) has no usable qualities.
* Trimming: the modified Mott algorithm, implemented here as the maximum-scoring segment: each base scores
  `limit - 10^(-Q/10)`, and the kept region is the one ending at the highest value of the running sum (reset to 0
  when it is not positive) and starting after the last zero before it, as the current CLC Genomics Workbench manual
  describes it (https://resources.qiagenbioinformatics.com/manuals/clcgenomicsworkbench/current/index.php?manual=
  Quality_trimming.html). Biopython's own "abi-trim" fixes the limit at 0.05 and starts at the first positive
  value instead, so it is not used; 0.05 is the default limit here (Biopython's value) and it can be changed.
* Consensus: the reverse read is reverse-complemented and aligned to the forward read with Biopython's
  PairwiseAligner in global mode with free end gaps; every column keeps both reads' evidence (base, Phred quality,
  the four channel heights at the peak and the peak's scan position). Columns where the reads differ inside their
  overlap are conflicts, resolved by quality only when ARVA's rule (below) allows it, and always listed.
* Identification: BLAST+ HSPs (arva_tools.blast.parse_tabular) of the consensus against local databases and
  genomes, chained per subject (arva_core.region.chain_matches), ranked, and read with the 16S criteria below.

Thresholds, and where each comes from (SOURCES):

* 16S rRNA (CLSI_16S): species at >= 99 % identity with >= 0.8 % separation from the next species, genus at >= 97 %,
  query coverage >= 98 % and an aligned length above 440 bp. These are CLSI MM18's criteria as quoted by three
  open-access papers (the guideline itself is sold by CLSI and was not read): Frickmann H. et al. (2015) PLoS One
  10:e0135923, Locher K. et al. (2022) Microbiol Spectr 10:e0040822 (Table 5) and Campodonico V.L. et al. (2025)
  J Clin Microbiol 63:e0167024, who note that they were set for Sanger sequencing of the first 500 bp of the gene.
* 16S in Staphylococcus: Kosecka-Strojek M. et al. (2019) Front Cell Infect Microbiol 9:278 (S. aureus,
  S. argenteus and S. schweitzeri, among other groups, have identical or nearly identical 16S; sodA and rpoB were
  the most discriminative targets) and Ghebremedhin B. et al. (2008) J Clin Microbiol 46:1019-1025 (gap, rpoB,
  hsp60, sodA and tuf separate species that 16S cannot always separate).
* Any other gene (GENE_DEFAULTS): 80 % identity and 80 % coverage, ABRicate 1.4.0's defaults (`--minid`,
  `--mincov`, from `abricate --help`); there is no published universal threshold for "this is gene X".

ARVA's own rules (heuristics, labelled so wherever results are shown):

* Conflict resolution: the higher-quality base wins only when it is at least `min_winner_quality` (Q20, a 1 %
  error probability, by default) and at least `min_quality_difference` (10) above the other; for a base against a
  gap, the gap read's quality is the lower of its two neighbouring bases' qualities. Otherwise the column is
  unresolved: an IUPAC code for two different bases, N for a base against a gap. A no-call (N) in one read takes the
  other read's base. Without qualities nothing is resolved by quality.
* Mixed peaks: a base is flagged for review when the second-highest channel at its peak is at least
  `min_ratio` (0.33) of the highest. tracy 0.9.1 uses 0.33 as its default peak ratio (`-p`) for calling a second
  base; here it is only a flag, never a call.
* Genus separation: a genus is named only when no hit of another genus lies within the species separation (0.8 %)
  of the best hit, the same separation CLSI asks between species.
* A suspected gene or species "matches" when it is among the best hits, alone, and meets the thresholds; it is
  "ambiguous" when other names tie with it; it does "not match" when it is absent, below the thresholds or a hit
  with another name is better. Better hits with other names are always returned.

Nothing here reads or writes files other than the .ab1 or text given, and nothing is sent anywhere.
"""
from __future__ import annotations

import io
import math
import re
import struct
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from arva_core.region import chain_matches, union_length
from arva_core.species import species_of

# --- Constants and sources ----------------------------------------------------------------------------------------

DNA_LETTERS = frozenset("ACGTNRYSWKMBDHV")
COMPLEMENT = str.maketrans("ACGTNRYSWKMBDHV", "TGCANYRSWMKVHDB")
IUPAC_PAIR = {frozenset("AG"): "R", frozenset("CT"): "Y", frozenset("CG"): "S", frozenset("AT"): "W",
              frozenset("GT"): "K", frozenset("AC"): "M"}
CHANNEL_TAGS = ("DATA9", "DATA10", "DATA11", "DATA12")

DEFAULT_TRIM_LIMIT = 0.05
DEFAULT_MIXED_RATIO = 0.33
DEFAULT_TRACE_POINTS = 2000
MAX_TRACE_POINTS = 20_000
Q20 = 20

CLSI_16S = {"species_identity": 99.0, "species_separation": 0.8, "genus_identity": 97.0,
            "min_query_coverage": 98.0, "min_aligned_length": 440}
GENE_DEFAULTS = {"min_identity": 80.0, "min_coverage": 80.0}
STAPH_HIGHER_RESOLUTION = ("rpoB", "sodA", "tuf", "gap")
FIRST_REGION = 500
SPLIT_MAX_GAP = 50_000
# Identities are ratios of whole numbers (identical bases / aligned columns), compared unrounded; this tolerance only
# absorbs floating-point error (100 - 99.2 is 0.79999999999999716 in binary floating point).
EPSILON = 1e-9

SOURCES = {
    "trim": "Modified Mott algorithm as the maximum-scoring segment (CLC Genomics Workbench manual, Quality "
            "trimming); default limit 0.05 as in Biopython 1.88's abi-trim (Bio/SeqIO/AbiIO.py)",
    "abi": "Biopython 1.88 Bio.SeqIO 'abi' format: PBAS2 calls, PCON2 qualities, PLOC2 peaks, DATA9-12 traces, "
           "FWO_1 base order",
    "alignment": "Biopython 1.88 Bio.Align.PairwiseAligner, global mode with free end gaps",
    "clsi_16s": "CLSI MM18 as quoted by Frickmann H. et al. (2015) PLoS One 10:e0135923, doi:10.1371/journal.pone."
                "0135923; Locher K. et al. (2022) Microbiol Spectr 10:e0040822, doi:10.1128/spectrum.00408-22 "
                "(Table 5); Campodonico V.L. et al. (2025) J Clin Microbiol 63:e0167024, doi:10.1128/jcm.01670-24",
    "first_500": "Campodonico V.L. et al. (2025) J Clin Microbiol 63:e0167024: the CLSI MM18 criteria are for Sanger "
                 "sequencing of the first 500 bp of the 16S rRNA gene",
    "staphylococcus_16s": "Kosecka-Strojek M. et al. (2019) Front Cell Infect Microbiol 9:278, doi:10.3389/fcimb."
                          "2019.00278; Ghebremedhin B. et al. (2008) J Clin Microbiol 46:1019-1025, doi:10.1128/JCM."
                          "02058-07",
    "gene_defaults": "ABRicate 1.4.0 defaults --minid 80 --mincov 80 (abricate --help)",
    "conflicts": "ARVA's heuristic",
    "mixed_peaks": "ARVA's heuristic (0.33 is tracy 0.9.1's default peak ratio -p for calling a second base)",
    "genus_separation": "ARVA's heuristic (the CLSI species separation applied between genera)",
    "suspected": "ARVA's rule",
}


def _code(code: str, **params: Any) -> dict[str, Any]:
    return {"code": code, "params": params}


# --- Reads --------------------------------------------------------------------------------------------------------

@dataclass
class SangerRead:
    """One read: base calls with, when the source has them, Phred qualities, peak positions and the four traces.

    `origin[i]` is the 0-based index of base i among the file's base calls, so a trimmed or reverse-complemented read
    still points into its chromatogram; `peaks[i]` is the scan of that base's peak in `traces`, which always stay in
    the instrument's orientation (a reverse-complemented read reads them with the complementary bases).
    """

    name: str
    bases: str
    source_format: str
    qualities: list[int] | None = None
    peaks: list[int] | None = None
    traces: dict[str, list[int]] | None = None
    sample: str | None = None
    instrument: dict[str, str] = field(default_factory=dict)
    strand: str = "+"
    origin: list[int] = field(default_factory=list)
    trim: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.origin:
            self.origin = list(range(len(self.bases)))
        n = len(self.bases)
        for label, values in (("qualities", self.qualities), ("peaks", self.peaks), ("origin", self.origin)):
            if values is not None and len(values) != n:
                raise ValueError(f"{label} has {len(values)} values for {n} bases")

    @property
    def has_qualities(self) -> bool:
        return bool(self.qualities) and any(q > 0 for q in self.qualities)

    @property
    def has_trace(self) -> bool:
        return self.traces is not None and self.peaks is not None

    def summary(self) -> dict[str, Any]:
        q = self.qualities if self.has_qualities else None
        return {"name": self.name, "sample": self.sample, "source_format": self.source_format, "length": len(self),
                "strand": self.strand, "has_qualities": self.has_qualities, "has_trace": self.has_trace,
                "mean_quality": round(sum(q) / len(q), 1) if q else None,
                "q20_percent": round(100 * sum(1 for x in q if x >= Q20) / len(q), 1) if q else None,
                "instrument": dict(self.instrument), "trim": self.trim, "warnings": list(self.warnings)}

    def __len__(self) -> int:
        return len(self.bases)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).replace("\x00", "").strip()
    return text or None


def read_abi(source: str | Path | bytes, name: str | None = None) -> SangerRead:
    """An ABIF chromatogram (.ab1) read with Biopython. Raises ValueError for a file that is not ABIF, has no base
    calls (a fragment-analysis .fsa file) or whose tags do not fit together."""
    from Bio import SeqIO

    if isinstance(source, bytes | bytearray):
        handle: Any = io.BytesIO(bytes(source))
        default_name = name or "read"
    else:
        path = Path(source)
        handle = path.open("rb")
        default_name = name or (path.name[:-4] if path.name.lower().endswith(".ab1") else path.stem)
    try:
        record = SeqIO.read(handle, "abi")
    except (ValueError, struct.error, UnicodeDecodeError, IndexError, KeyError, EOFError, OverflowError) as exc:
        raise ValueError(f"not a readable ABIF (.ab1) file: {exc}") from None
    finally:
        handle.close()
    raw = record.annotations.get("abif_raw", {})
    bases = str(record.seq).upper()
    if not bases:
        raise ValueError("the file has no base calls (PBAS2): it may be a fragment-analysis file")
    bad = sorted(set(bases) - DNA_LETTERS)
    if bad:
        raise ValueError(f"the base calls contain characters that are not DNA: {''.join(bad)}")
    warnings: list[dict[str, Any]] = []
    qualities = record.letter_annotations.get("phred_quality")
    qualities = [int(q) for q in qualities] if qualities else None
    if not qualities or not any(qualities):
        warnings.append(_code("no_qualities"))
    peaks = list(raw["PLOC2"]) if isinstance(raw.get("PLOC2"), tuple | list) else None
    if peaks is not None and len(peaks) != len(bases):
        warnings.append(_code("peaks_mismatch", peaks=len(peaks), bases=len(bases)))
        peaks = None
    traces = None
    order = _text(raw.get("FWO_1"))
    channels = [raw.get(t) for t in CHANNEL_TAGS]
    if order and sorted(order.upper()) == list("ACGT") and all(isinstance(c, tuple | list) for c in channels) \
            and len({len(c) for c in channels}) == 1:
        traces = {b: [int(v) for v in c] for b, c in zip(order.upper(), channels, strict=True)}
        n_scans = len(channels[0])
        if peaks is not None and any(not 0 <= p < n_scans for p in peaks):
            warnings.append(_code("peaks_outside_trace", scans=n_scans))
            peaks = None
    else:
        warnings.append(_code("no_trace"))
    if traces is None:
        peaks = None
    sample = record.id if record.id and record.id != "<unknown id>" else None
    instrument = {k: v for k, v in {
        "model": _text(raw.get("MODL1")), "basecaller": _text(raw.get("SVER2")), "mobility": _text(raw.get("PDMF1")),
        "run_date": _text(raw.get("RUND1")), "well": _text(raw.get("TUBE1")), "base_order": order,
        "dye": _text(raw.get("DySN1")), "polymer": _text(raw.get("GTyp1")),
    }.items() if v}
    return SangerRead(name=default_name, bases=bases, source_format="abi", qualities=qualities, peaks=peaks,
                      traces=traces, sample=sample, instrument=instrument, warnings=warnings)


def parse_sequence_text(text: str, name: str = "sequence") -> list[SangerRead]:
    """Reads from FASTA text, or from a plain sequence (.seq: the bases alone, over any number of lines). There are
    no qualities or traces: such reads cannot be quality-trimmed and their conflicts are never resolved by quality."""
    text = text.lstrip("﻿")
    records: list[tuple[str, list[str]]] = []
    if any(line.startswith(">") for line in text.splitlines()):
        for line in text.splitlines():
            if line.startswith(">"):
                header = line[1:].strip()
                records.append((header.split()[0] if header else f"{name}_{len(records) + 1}", []))
            elif records:
                records[-1][1].append(line)
            elif line.strip():
                raise ValueError("text before the first FASTA header")
        source = "fasta"
    else:
        records = [(name, text.splitlines())]
        source = "seq"
    reads = []
    for rec_name, lines in records:
        seq = re.sub(r"\s+", "", "".join(lines)).upper()
        if not seq:
            raise ValueError(f"{rec_name}: no sequence")
        bad = sorted(set(seq) - DNA_LETTERS)
        if bad:
            raise ValueError(f"{rec_name}: characters that are not DNA bases (IUPAC): {''.join(bad)}")
        reads.append(SangerRead(name=rec_name, bases=seq, source_format=source, warnings=[_code("no_qualities")]))
    return reads


# --- Peaks and the chromatogram -------------------------------------------------------------------------------------

def peak_heights(read: SangerRead, i: int) -> dict[str, int] | None:
    """The four channels' signal at base i's peak, keyed by base in the read's orientation."""
    if not read.has_trace:
        return None
    scan = read.peaks[i]
    heights = {b: read.traces[b][scan] for b in "ACGT"}
    if read.strand == "-":
        heights = {b.translate(COMPLEMENT): v for b, v in heights.items()}
    return heights


def mixed_peaks(read: SangerRead, min_ratio: float = DEFAULT_MIXED_RATIO) -> list[dict[str, Any]]:
    """Bases to review: an IUPAC (non-ACGT) call, or a second channel at least `min_ratio` of the highest at the
    peak. Positions are 1-based in the read as given (after any trimming)."""
    if not 0 < min_ratio <= 1:
        raise ValueError("min_ratio must be above 0 and at most 1")
    out = []
    for i, base in enumerate(read.bases):
        h = peak_heights(read, i)
        ratio = second = None
        if h is not None:
            ranked = sorted(h.items(), key=lambda kv: -kv[1])
            if ranked[0][1] > 0:
                ratio = ranked[1][1] / ranked[0][1]
                second = ranked[1][0]
        if base not in "ACGT" or (ratio is not None and ratio >= min_ratio):
            out.append({"position": i + 1, "origin": read.origin[i] + 1, "base": base,
                        "quality": read.qualities[i] if read.qualities else None,
                        "second_base": second, "ratio": round(ratio, 3) if ratio is not None else None})
    return out


def trace_view(read: SangerRead, scan_start: int = 0, scan_end: int | None = None,
               max_points: int = DEFAULT_TRACE_POINTS) -> dict[str, Any]:
    """The chromatogram between two scans for display, downsampled to at most `max_points` points per channel by
    keeping the highest value of each block of `step` scans (so peaks are not lost). Base markers are the read's
    bases whose peak falls in the window, with their 1-based position in the read and in the file's calls."""
    if not read.has_trace:
        raise ValueError("this read has no chromatogram")
    if not 10 <= max_points <= MAX_TRACE_POINTS:
        raise ValueError(f"max_points must be between 10 and {MAX_TRACE_POINTS}")
    n = len(read.traces["A"])
    end = n if scan_end is None else min(scan_end, n)
    start = max(0, scan_start)
    if start >= end:
        raise ValueError("empty scan window")
    step = max(1, math.ceil((end - start) / max_points))
    channels = {b: [max(read.traces[b][j:min(j + step, end)]) for j in range(start, end, step)] for b in "ACGT"}
    markers = []
    for i, scan in enumerate(read.peaks):
        if start <= scan < end:
            markers.append({"position": i + 1, "origin": read.origin[i] + 1, "base": read.bases[i],
                            "quality": read.qualities[i] if read.qualities else None, "scan": scan,
                            "point": (scan - start) // step})
    return {"scan_start": start, "scan_end": end, "scans": n, "step": step, "channels": channels,
            "markers": markers, "strand": read.strand}


# --- Trimming -----------------------------------------------------------------------------------------------------

def mott_trim(qualities: Sequence[int], limit: float = DEFAULT_TRIM_LIMIT) -> dict[str, Any]:
    """The modified Mott maximum-scoring segment of a read's qualities (module docstring). start and end are
    1-based and inclusive; both are None when no base scores above the limit."""
    if not 0 < limit < 1:
        raise ValueError("the trimming limit (error probability) must be above 0 and below 1")
    best = run = 0.0
    run_start = 0
    best_start = best_end = None
    for i, q in enumerate(qualities):
        run += limit - 10 ** (-q / 10)
        if run <= 0:
            run, run_start = 0.0, i + 1
        elif run > best:
            best, best_start, best_end = run, run_start, i
    kept = qualities[best_start:best_end + 1] if best_start is not None else []
    return {"method": "modified_mott", "limit": limit, "original_length": len(qualities),
            "start": best_start + 1 if best_start is not None else None,
            "end": best_end + 1 if best_end is not None else None, "length": len(kept),
            "score": round(best, 4), "mean_quality": round(sum(kept) / len(kept), 1) if kept else None,
            "q20_percent": round(100 * sum(1 for q in kept if q >= Q20) / len(kept), 1) if kept else None,
            "source": SOURCES["trim"]}


def _slice(read: SangerRead, lo: int, hi: int, trim: dict[str, Any], warnings: list[dict[str, Any]]) -> SangerRead:
    return replace(read, bases=read.bases[lo:hi], qualities=read.qualities[lo:hi] if read.qualities else None,
                   peaks=read.peaks[lo:hi] if read.peaks is not None else None, origin=read.origin[lo:hi],
                   trim=trim, warnings=[*read.warnings, *warnings])


def trim_read(read: SangerRead, limit: float = DEFAULT_TRIM_LIMIT,
              manual: tuple[int, int] | None = None) -> SangerRead:
    """The read cut to its kept region: the Mott segment at `limit`, or `manual` (1-based, inclusive, on the read as
    given). A read without qualities is kept whole unless a manual range is given, and says so."""
    if read.trim is not None:
        raise ValueError("the read is already trimmed")
    n = len(read)
    if manual is not None:
        lo, hi = manual
        if not 1 <= lo <= hi <= n:
            raise ValueError(f"the manual range must be within 1-{n}")
        trim = {"method": "manual", "limit": None, "original_length": n, "start": lo, "end": hi,
                "length": hi - lo + 1}
        return _slice(read, lo - 1, hi, trim, [])
    if not read.has_qualities:
        trim = {"method": "none", "limit": None, "original_length": n, "start": 1 if n else None,
                "end": n or None, "length": n}
        return _slice(read, 0, n, trim, [_code("not_trimmed_no_qualities")])
    trim = mott_trim(read.qualities, limit)
    if trim["start"] is None:
        return _slice(read, 0, 0, trim, [_code("nothing_kept", limit=limit)])
    return _slice(read, trim["start"] - 1, trim["end"], trim, [])


def reverse_complement(read: SangerRead) -> SangerRead:
    """The read on the other strand: complemented bases, and qualities, peaks and origins in reverse order. The
    traces are not changed (they stay as the instrument recorded them)."""
    return replace(read, bases=read.bases.translate(COMPLEMENT)[::-1],
                   qualities=read.qualities[::-1] if read.qualities else None,
                   peaks=read.peaks[::-1] if read.peaks is not None else None, origin=read.origin[::-1],
                   strand="-" if read.strand == "+" else "+", warnings=list(read.warnings))


# --- Consensus ----------------------------------------------------------------------------------------------------

@dataclass
class ConsensusParams:
    match: float = 2.0
    mismatch: float = -3.0
    gap_open: float = -5.0
    gap_extend: float = -2.0
    min_winner_quality: int = Q20
    min_quality_difference: int = 10
    min_overlap: int = 25
    min_overlap_identity: float = 90.0
    reverse_complement_second: bool = True

    def validate(self) -> None:
        errors = []
        if self.match <= 0:
            errors.append("match must be positive")
        if self.mismatch >= 0 or self.gap_open >= 0 or self.gap_extend >= 0:
            errors.append("mismatch and gap scores must be negative")
        if not 0 <= self.min_winner_quality <= 99 or not 0 <= self.min_quality_difference <= 99:
            errors.append("quality thresholds must be between 0 and 99")
        if not 1 <= self.min_overlap <= 100_000:
            errors.append("min_overlap must be between 1 and 100000")
        if not 0 <= self.min_overlap_identity <= 100:
            errors.append("min_overlap_identity must be between 0 and 100")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _aligner(p: ConsensusParams):
    from Bio.Align import PairwiseAligner

    return PairwiseAligner(mode="global", match_score=p.match, mismatch_score=p.mismatch,
                           open_gap_score=p.gap_open, extend_gap_score=p.gap_extend, end_gap_score=0,
                           wildcard="N")


def _evidence(read: SangerRead, i: int) -> dict[str, Any]:
    return {"base": read.bases[i], "position": i + 1, "origin": read.origin[i] + 1,
            "quality": read.qualities[i] if read.has_qualities else None,
            "scan": read.peaks[i] if read.has_trace else None, "heights": peak_heights(read, i)}


def _gap_quality(read: SangerRead, before: int | None, after: int | None) -> int | None:
    """The quality of 'no base here' in a read: the lower of the qualities of the bases on each side of the gap."""
    if not read.has_qualities:
        return None
    sides = [read.qualities[k] for k in (before, after) if k is not None and 0 <= k < len(read)]
    return min(sides) if sides else None


def _resolve(a: str | None, qa: int | None, b: str | None, qb: int | None,
             p: ConsensusParams) -> tuple[str, str, str]:
    """(base, status, rule) for a conflict column; a None base is a gap, "" in the result drops the column."""
    if a is not None and b is not None:
        if (a == "N") != (b == "N"):
            return (b if a == "N" else a), "resolved", "no_call_in_other_read"
        unresolved = IUPAC_PAIR.get(frozenset((a, b)), "N")
    else:
        unresolved = "N"
    if qa is not None and qb is not None:
        if qa >= p.min_winner_quality and qa - qb >= p.min_quality_difference:
            return (a or ""), "resolved", "higher_quality"
        if qb >= p.min_winner_quality and qb - qa >= p.min_quality_difference:
            return (b or ""), "resolved", "higher_quality"
        return unresolved, "unresolved", "qualities_too_close"
    return unresolved, "unresolved", "no_qualities"


def consensus(forward: SangerRead, reverse: SangerRead, params: ConsensusParams | None = None) -> dict[str, Any]:
    """The consensus of a forward and a reverse read (each already trimmed), with the evidence of every alignment
    column and every conflict. status: ok, or no_overlap (then `sequence` is empty: the reads do not overlap by
    `min_overlap` columns, or the overlap is below `min_overlap_identity`)."""
    p = params or ConsensusParams()
    p.validate()
    if not len(forward) or not len(reverse):
        raise ValueError("both reads must have bases")
    second = reverse_complement(reverse) if p.reverse_complement_second else reverse
    aligner = _aligner(p)
    alignment = aligner.align(forward.bases, second.bases)[0]
    other_orientation = aligner.score(forward.bases, reverse.bases if p.reverse_complement_second
                                      else reverse_complement(reverse).bases)
    idx = alignment.indices
    both = [k for k in range(idx.shape[1]) if idx[0][k] >= 0 and idx[1][k] >= 0]
    warnings: list[dict[str, Any]] = []
    if other_orientation > alignment.score:
        warnings.append(_code("orientation_suspect", score=float(alignment.score),
                              other_score=float(other_orientation)))
    first, last = (both[0], both[-1]) if both else (None, None)
    overlap_cols = range(first, last + 1) if both else range(0)
    identical = sum(1 for k in overlap_cols if idx[0][k] >= 0 and idx[1][k] >= 0
                    and forward.bases[idx[0][k]] == second.bases[idx[1][k]])
    overlap_identity = round(100 * identical / len(overlap_cols), 2) if both else 0.0
    overlap = {"columns": len(overlap_cols), "identical": identical,
               "mismatches": sum(1 for k in overlap_cols if idx[0][k] >= 0 and idx[1][k] >= 0
                                 and forward.bases[idx[0][k]] != second.bases[idx[1][k]]),
               "gaps": sum(1 for k in overlap_cols if idx[0][k] < 0 or idx[1][k] < 0),
               "identity": overlap_identity, "consensus_start": None, "consensus_end": None}
    base = {"params": p.as_dict(), "score": float(alignment.score), "other_orientation_score": float(other_orientation),
            "overlap": overlap, "forward": forward.summary(), "reverse": reverse.summary(),
            "source": SOURCES["alignment"], "conflict_rule": SOURCES["conflicts"]}
    if len(overlap_cols) < p.min_overlap or overlap_identity < p.min_overlap_identity:
        warnings.append(_code("no_overlap", columns=len(overlap_cols), identity=overlap_identity,
                              min_overlap=p.min_overlap, min_identity=p.min_overlap_identity))
        return {**base, "status": "no_overlap", "sequence": "", "length": 0, "columns": [], "conflicts": [],
                "counts": {}, "warnings": warnings}
    columns: list[dict[str, Any]] = []
    seq: list[str] = []
    counts = {"agree": 0, "forward_only": 0, "reverse_only": 0, "resolved": 0, "unresolved": 0}
    for k in range(idx.shape[1]):
        fi, ri = int(idx[0][k]), int(idx[1][k])
        f = _evidence(forward, fi) if fi >= 0 else None
        r = _evidence(second, ri) if ri >= 0 else None
        inside = first <= k <= last
        rule = kind = None
        if not inside:
            out, status = (f or r)["base"], "forward_only" if f else "reverse_only"
        elif f and r and f["base"] == r["base"]:
            out, status = f["base"], "agree"
        else:
            kind = "mismatch" if f and r else "gap"
            qf = f["quality"] if f else _gap_quality(forward, _prev(idx[0], k), _next(idx[0], k))
            qr = r["quality"] if r else _gap_quality(second, _prev(idx[1], k), _next(idx[1], k))
            out, status, rule = _resolve(f["base"] if f else None, qf, r["base"] if r else None, qr, p)
        counts[status] += 1
        col = {"column": k + 1, "position": len(seq) + 1 if out else None, "base": out, "status": status,
               "kind": kind, "rule": rule, "forward": f, "reverse": r}
        if out:
            seq.append(out)
        columns.append(col)
    starts = [c["position"] for c in columns[first:last + 1] if c["position"]]
    overlap["consensus_start"], overlap["consensus_end"] = (starts[0], starts[-1]) if starts else (None, None)
    conflicts = [c for c in columns if c["kind"] is not None]
    if counts["unresolved"]:
        warnings.append(_code("unresolved_conflicts", count=counts["unresolved"]))
    if not forward.has_qualities or not second.has_qualities:
        warnings.append(_code("conflicts_without_qualities"))
    return {**base, "status": "ok", "sequence": "".join(seq), "length": len(seq), "columns": columns,
            "conflicts": conflicts, "counts": counts, "warnings": warnings}


def _prev(row: Any, k: int) -> int | None:
    for j in range(k - 1, -1, -1):
        if row[j] >= 0:
            return int(row[j])
    return None


def _next(row: Any, k: int) -> int | None:
    for j in range(k + 1, len(row)):
        if row[j] >= 0:
            return int(row[j])
    return None


# --- Names from database titles --------------------------------------------------------------------------------------

_16S_SUFFIX = re.compile(r"\s+16S ribosomal RNA\b.*$")
_SUBGENUS = re.compile(r"\s+\(subgen\.\s+[^)]*\)")


def ncbi_accession(sseqid: str) -> str:
    """The accession in a BLAST subject id of an NCBI database ("gi|310975040|ref|NR_036904.1|" ->
    "NR_036904.1"); any other id unchanged."""
    parts = sseqid.strip("|").split("|")
    for tag in ("ref", "gb", "emb", "dbj"):
        if tag in parts[:-1]:
            return parts[parts.index(tag) + 1]
    return sseqid


def parse_16s_title(title: str) -> dict[str, Any]:
    """Organism, species and strain from a title of NCBI's 16S_ribosomal_RNA BLAST database ("Staphylococcus
    epidermidis strain NBRC 100911 16S ribosomal RNA, partial sequence"). A bracketed genus ("[Clostridium]
    cellulosi", a name NCBI marks as misplaced) stays bracketed, so it is not taken for the genus Clostridium."""
    organism = _16S_SUFFIX.sub("", title or "").strip()
    strain = None
    if " strain " in organism:
        organism, strain = (x.strip() for x in organism.split(" strain ", 1))
    clean = _SUBGENUS.sub("", organism)
    prefix = ""
    if clean.startswith("Candidatus "):
        prefix, clean = "Candidatus ", clean[len("Candidatus "):]
    sp = species_of(clean)
    words = clean.split()
    subspecies = words[3] if sp and len(words) > 3 and words[2] == "subsp." else None
    return {"organism": organism or None, "species": prefix + sp if sp else None,
            "genus": prefix + sp.split()[0] if sp else None, "subspecies": subspecies,
            "strain": strain}


def parse_abricate_id(sseqid: str, title: str | None = None) -> dict[str, Any]:
    """Gene, accession and description of a sequence in an ABRicate database (header "<db>~~~<gene>~~~<accession>~~~
    <description>", as in ABRicate 1.4.0's bundled VFDB and PlasmidFinder files). A gene field equal to the accession
    means the database gives no gene name. For VFDB the description also gives the product, the virulence factor and
    its category, and the organism."""
    parts = sseqid.split("~~~")
    if len(parts) < 3:
        return {"database": None, "gene": None, "accession": None, "product": None, "factor": None,
                "category": None, "organism": None}
    db, gene, accession = parts[0], parts[1], parts[2]
    desc = (title or "")
    if desc.startswith(sseqid):
        desc = desc[len(sseqid):]
    desc = desc.strip()
    out = {"database": db, "gene": gene if gene and gene != accession else None, "accession": accession or None,
           "product": None, "factor": None, "category": None, "organism": None}
    m = re.fullmatch(r"\((?P<g>[^)]*)\)\s*(?P<product>.*?)\s*\[(?P<vf>[^\]]*)\]\s*\[(?P<org>[^\]]*)\]", desc)
    if m:
        out["product"] = m["product"] or None
        out["organism"] = m["org"] or None
        vf = re.fullmatch(r"(?P<f>.*?)\s+-\s+(?P<c>.*)", m["vf"])
        out["factor"], out["category"] = (vf["f"], vf["c"]) if vf else (m["vf"], None)
    elif desc:
        out["product"] = desc
    return out


def gene_aliases(gene: str | None) -> list[str]:
    """The names a database gene field stands for: VFDB writes alternatives with a slash ("hly/hla")."""
    return [g for g in (gene or "").split("/") if g]


def parse_mlst_allele(sseqid: str) -> dict[str, Any] | None:
    """Scheme, locus and allele of an mlst allele ("saureus.arcC_1" in mlst's BLAST database, "arcC_1" in a PubMLST
    .tfa file)."""
    m = re.fullmatch(r"(?:(?P<scheme>[^.\s]+)\.)?(?P<locus>[^_\s]+(?:_[^_\s]+)*?)_(?P<allele>\d+)", sseqid)
    if not m:
        return None
    return {"scheme": m["scheme"], "locus": m["locus"], "allele": m["allele"]}


# --- Hits ---------------------------------------------------------------------------------------------------------

def hits_from_hsps(hsps: Sequence[dict[str, Any]], source: dict[str, Any],
                   name_of: Callable[[dict[str, Any]], dict[str, Any]] | None = None, *,
                   max_gap: int = SPLIT_MAX_GAP, complete_coverage: float = 90.0) -> list[dict[str, Any]]:
    """One row per subject from BLAST HSPs of one query against one source: the subject's best chained match
    (arva_core.region.chain_matches; a match of several HSPs is "split"), with the number of separate matches
    (`copies`) on that subject. `name_of(hsp)` gives the row's names (gene, species, product, ...) from the subject's
    id and title; `source` (kind, name, version, ...) is copied into every row."""
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for h in hsps:
        by_subject.setdefault(h["sseqid"], []).append(h)
    rows = []
    for subject, group in by_subject.items():
        matches = chain_matches(group, min_identity=0, min_coverage=0, complete_coverage=complete_coverage,
                                max_gap=max_gap)
        if not matches:
            continue
        m = matches[0]
        key = {(h["qstart"], h["qend"], h["s_lo"], h["s_hi"]): h for h in group}
        used = [key[(p["qstart"], p["qend"], p["s_lo"], p["s_hi"])] for p in m["pieces"]]
        aligned = sum(h["length"] for h in used)
        identical = sum(h["nident"] for h in used)
        names = name_of(used[0]) if name_of else {}
        # Identity and coverages are kept unrounded, so that a threshold is never passed by rounding (593 of 599
        # bases is 98.998 %, below 99 %); round them only to display them.
        rows.append({
            "source": dict(source), "subject": subject, "title": used[0].get("stitle"),
            "identity": 100 * identical / aligned, "identical": identical,
            "query_coverage": 100 * union_length((h["qstart"], h["qend"]) for h in used) / m["query_length"],
            "subject_coverage": 100 * union_length((h["s_lo"], h["s_hi"]) for h in used) / m["subject_length"],
            "aligned_length": aligned, "query_start": m["query_start"], "query_end": m["query_end"],
            "query_length": m["query_length"], "subject_start": m["start"], "subject_end": m["end"],
            "subject_length": m["subject_length"], "strand": m["strand"], "kind": m["kind"],
            "evalue": m["evalue"], "bitscore": m["bitscore"], "copies": len(matches), "pieces": m["pieces"],
            "gene": None, "species": None, "genus": None, "product": None, **names,
        })
    return rows


def _rank_key(r: dict[str, Any]) -> tuple:
    return (-r["bitscore"], -r["identity"], -r["query_coverage"], str(r["source"].get("name", "")), r["subject"])


def rank_hits(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows of every source in one list, best first: bit score, then identity, then query coverage. `rank` is the
    position; `tied_with_best` marks rows whose identity and query coverage equal the best row's (never hidden)."""
    ranked = sorted((dict(r) for r in rows), key=_rank_key)
    if ranked:
        b = ranked[0]
        for n, r in enumerate(ranked, 1):
            r["rank"] = n
            r["tied_with_best"] = abs(r["identity"] - b["identity"]) <= EPSILON \
                and abs(r["query_coverage"] - b["query_coverage"]) <= EPSILON
    return ranked


def _feature_intervals(f: dict[str, Any], contig_length: int) -> list[tuple[int, int]]:
    if f.get("edge") and f["start"] > f["end"]:
        return [(f["start"], contig_length), (1, f["end"])]
    return [(min(f["start"], f["end"]), max(f["start"], f["end"]))]


def _overlap_bp(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> int:
    return union_length((max(x[0], y[0]), min(x[1], y[1])) for x in a for y in b if min(x[1], y[1]) >= max(x[0], y[0]))


def name_by_features(row: dict[str, Any], features: Iterable[dict[str, Any]], contig: str | None = None,
                     types: Sequence[str] = ("cds", "sorf", "rrna", "trna", "tmrna", "ncrna")) -> list[dict[str, Any]]:
    """The annotated features a genome hit overlaps (a Bakta or Prokka annotation in ARVA's feature shape), each
    with the share of the feature the hit covers and the share of the hit inside the feature, most covered first. A
    split hit (one gene interrupted, as hlb by a prophage) lists the features of every piece; `contig` is the
    feature's sequence name when it differs from the BLAST subject id."""
    name = contig or row["subject"]
    pieces = [(p["s_lo"], p["s_hi"]) for p in row["pieces"]]
    hit_len = union_length(pieces)
    out = []
    for f in features:
        if f["contig"] != name or f["type"] not in types:
            continue
        iv = _feature_intervals(f, row["subject_length"])
        bp = _overlap_bp(iv, pieces)
        if bp:
            flen = sum(hi - lo + 1 for lo, hi in iv)
            out.append({"id": f.get("id"), "locus_tag": f.get("locus_tag"), "gene": f.get("gene"),
                        "product": f.get("product"), "type": f["type"], "start": f["start"], "end": f["end"],
                        "strand": f.get("strand"), "length": flen, "pseudo": bool(f.get("pseudo")),
                        "feature_coverage": round(100 * bp / flen, 2), "hit_inside": round(100 * bp / hit_len, 2)})
    out.sort(key=lambda x: (-x["hit_inside"], -x["feature_coverage"], x["start"]))
    return out


# --- Interpretation -------------------------------------------------------------------------------------------------

def _below(value: float, threshold: float) -> bool:
    return value < threshold - EPSILON


def _first_region_covered(row: dict[str, Any]) -> float:
    lo, hi = row["subject_start"], min(row["subject_end"], FIRST_REGION)
    return round(100 * max(0, hi - lo + 1) / FIRST_REGION, 1)


def _species_row(r: dict[str, Any]) -> dict[str, Any]:
    keys = ("subject", "species", "strain", "identity", "query_coverage", "aligned_length", "bitscore", "evalue",
            "subject_start", "subject_end")
    return {k: r.get(k) for k in keys}


def interpret_16s(rows: Sequence[dict[str, Any]], thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """ARVA's reading of 16S rRNA hits (rows with `species`, from NCBI's 16S database or any named source) with the
    CLSI MM18 criteria as quoted (module docstring). level: species, genus, inconclusive or no_hits. Every species
    at or above the species threshold, and every one within the separation of the best, is listed."""
    t = {**CLSI_16S, **(thresholds or {})}
    base = {"thresholds": t, "sources": {k: SOURCES[k] for k in ("clsi_16s", "first_500", "staphylococcus_16s",
                                                                 "genus_separation")},
            "species": None, "genus": None, "best": None, "next_species": None, "separation": None,
            "within_separation": [], "above_species_threshold": [], "reasons": [], "caveats": []}
    # Rows with the CLSI query coverage come first (a short partial hit at higher identity does not decide).
    named = sorted((r for r in rows if r.get("species")),
                   key=lambda r: (_below(r["query_coverage"], t["min_query_coverage"]), -r["identity"],
                                  -r["query_coverage"], -r["bitscore"], r["subject"]))
    if not named:
        return {**base, "level": "no_hits"}
    best = named[0]
    # The other species are compared among the rows with enough coverage (all rows when none has it).
    pool = [r for r in named if not _below(r["query_coverage"], t["min_query_coverage"])] or named
    reasons: list[dict[str, Any]] = []
    caveats: list[dict[str, Any]] = [_code("criteria_quoted")]
    span = best["query_end"] - best["query_start"] + 1
    if _below(best["query_coverage"], t["min_query_coverage"]):
        reasons.append(_code("low_query_coverage", coverage=best["query_coverage"], minimum=t["min_query_coverage"]))
    if span <= t["min_aligned_length"]:
        reasons.append(_code("short_alignment", length=span, minimum=t["min_aligned_length"]))
    if _below(best["identity"], t["genus_identity"]):
        reasons.append(_code("below_genus_identity", identity=best["identity"], minimum=t["genus_identity"]))
    nxt = next((r for r in pool if r["species"] != best["species"]), None)
    separation = best["identity"] - nxt["identity"] if nxt else None
    window = [r for r in pool if _below(best["identity"] - r["identity"], t["species_separation"])]
    within: dict[str, dict[str, Any]] = {}
    for r in window:
        within.setdefault(r["species"], _species_row(r))
    above: dict[str, dict[str, Any]] = {}
    for r in pool:
        if not _below(r["identity"], t["species_identity"]):
            above.setdefault(r["species"], _species_row(r))
    genera = sorted({r["genus"] or r["species"].split()[0] for r in window})
    covered = _first_region_covered(best)
    if covered < 50:
        caveats.append(_code("not_first_500", subject_start=best["subject_start"], subject_end=best["subject_end"],
                             covered=covered))
    out = {**base, "best": _species_row(best), "next_species": _species_row(nxt) if nxt else None,
           "separation": separation, "within_separation": list(within.values()),
           "above_species_threshold": list(above.values())}
    best_genus = best.get("genus") or best["species"].split()[0]
    if best_genus == "Staphylococcus":
        caveats.append(_code("staphylococcus_16s_limit", genes=list(STAPH_HIGHER_RESOLUTION)))
    caveats.append(_code("closest_type_strain"))
    if reasons:
        return {**out, "level": "inconclusive", "reasons": reasons, "caveats": caveats}
    species_identity = not _below(best["identity"], t["species_identity"])
    if species_identity and (separation is None or not _below(separation, t["species_separation"])):
        return {**out, "level": "species", "species": best["species"], "genus": best_genus, "caveats": caveats}
    if species_identity:
        reasons.append(_code("species_not_separated", separation=separation, minimum=t["species_separation"],
                             species=len(within)))
    else:
        reasons.append(_code("below_species_identity", identity=best["identity"], minimum=t["species_identity"]))
    if len(genera) > 1:
        reasons.append(_code("genera_not_separated", genera=genera))
        return {**out, "level": "inconclusive", "reasons": reasons, "caveats": caveats}
    return {**out, "level": "genus", "genus": best_genus, "reasons": reasons, "caveats": caveats}


def _names(row: dict[str, Any], kind: str, genus_only: bool) -> set[str]:
    if kind == "species":
        value = row.get("genus") if genus_only else row.get("species")
        if genus_only and not value and row.get("species"):
            value = row["species"].split()[0]
        return {value.casefold()} if value else set()
    return {g.casefold() for g in gene_aliases(row.get("gene"))}


def _gene_coverage(row: dict[str, Any]) -> float:
    return max(row["query_coverage"], row.get("subject_coverage") or 0)


def _query_coverage(row: dict[str, Any]) -> float:
    return row["query_coverage"]


def _brief(r: dict[str, Any] | None) -> dict[str, Any] | None:
    keys = ("source", "subject", "title", "gene", "species", "product", "identity", "query_coverage",
            "subject_coverage", "aligned_length", "bitscore", "evalue")
    return {k: r.get(k) for k in keys} if r is not None else None


def compare_suspected(rows: Sequence[dict[str, Any]], suspected: str, kind: str, *,
                      min_identity: float | None = None, min_coverage: float | None = None,
                      tie_window: float | None = None, max_listed: int = 20) -> dict[str, Any]:
    """Whether the hits support what the user suspected: a gene (kind "gene", compared with the rows' gene names and
    their aliases, case-insensitively) or a species (kind "species"; a single word is a genus). outcome: match,
    ambiguous or no_match, with the best row of that name, the best row overall, and every row with another name
    that is better (`better_other`) or tied (`tied_other`), up to `max_listed` each with their total counts.

    Genes: rows rank by bit score, then identity and query coverage; two rows tie when their identities differ by
    at most `tie_window` (0) and their query coverages are equal. Thresholds GENE_DEFAULTS, where coverage is the
    larger of query and subject coverage (a read inside a longer gene, or a gene inside a longer read, both count).
    Species: only rows with the CLSI query coverage are compared; they rank by identity, and tie when their
    identities differ by less than the CLSI species separation (0.8; 0 for a genus); the suspected name needs the
    CLSI species (or genus) identity."""
    if kind not in ("gene", "species"):
        raise ValueError("kind must be gene or species")
    wanted = " ".join(suspected.split())
    if not wanted:
        raise ValueError("nothing suspected")
    genus_only = kind == "species" and len(wanted.split()) == 1
    if kind == "gene":
        min_identity = GENE_DEFAULTS["min_identity"] if min_identity is None else min_identity
        min_coverage = GENE_DEFAULTS["min_coverage"] if min_coverage is None else min_coverage
        window = 0.0 if tie_window is None else tie_window
        ranked = rank_hits(r for r in rows if _names(r, kind, False))
        coverage_of = _gene_coverage

        def tied(a: dict[str, Any], b: dict[str, Any]) -> bool:
            return abs(a["identity"] - b["identity"]) <= window + EPSILON \
                and abs(a["query_coverage"] - b["query_coverage"]) <= EPSILON

        def above(a: dict[str, Any], b: dict[str, Any]) -> bool:
            return _rank_key(a) < _rank_key(b)
    else:
        min_identity = (CLSI_16S["genus_identity"] if genus_only else CLSI_16S["species_identity"]) \
            if min_identity is None else min_identity
        min_coverage = CLSI_16S["min_query_coverage"] if min_coverage is None else min_coverage
        window = (0.0 if genus_only else CLSI_16S["species_separation"]) if tie_window is None else tie_window
        ranked = sorted((r for r in rows if _names(r, kind, genus_only) and not _below(r["query_coverage"], min_coverage)),
                        key=lambda r: (-r["identity"], -r["query_coverage"], -r["bitscore"], r["subject"]))
        coverage_of = _query_coverage

        def tied(a: dict[str, Any], b: dict[str, Any]) -> bool:
            diff = abs(a["identity"] - b["identity"])
            return _below(diff, window) if window else diff <= EPSILON

        def above(a: dict[str, Any], b: dict[str, Any]) -> bool:
            return a["identity"] > b["identity"] + EPSILON
    target = wanted.casefold()
    out: dict[str, Any] = {
        "suspected": wanted, "kind": "genus" if genus_only else kind, "source": SOURCES["suspected"],
        "thresholds": {"min_identity": min_identity, "min_coverage": min_coverage, "tie_window": window},
        "best": _brief(ranked[0]) if ranked else None, "best_suspected": None, "better_other": [],
        "better_other_count": 0, "tied_other": [], "tied_other_count": 0, "reasons": []}
    mine = next((r for r in ranked if target in _names(r, kind, genus_only)), None)
    if mine is None:
        excluded = kind == "species" and any(target in _names(r, kind, genus_only) for r in rows)
        return {**out, "outcome": "no_match",
                "reasons": [_code("below_coverage" if excluded else "not_found", min_coverage=min_coverage)]}
    others = [r for r in ranked if target not in _names(r, kind, genus_only)]
    better = [r for r in others if above(r, mine) and not tied(r, mine)]
    level = [r for r in others if tied(r, mine)]
    out.update({"best_suspected": _brief(mine), "better_other": [_brief(r) for r in better[:max_listed]],
                "better_other_count": len(better), "tied_other": [_brief(r) for r in level[:max_listed]],
                "tied_other_count": len(level)})
    if better:
        return {**out, "outcome": "no_match", "reasons": [_code("better_hit_other_name", count=len(better))]}
    if _below(mine["identity"], min_identity) or _below(coverage_of(mine), min_coverage):
        return {**out, "outcome": "no_match",
                "reasons": [_code("below_thresholds", identity=mine["identity"], coverage=coverage_of(mine),
                                  min_identity=min_identity, min_coverage=min_coverage)]}
    if level:
        return {**out, "outcome": "ambiguous", "reasons": [_code("tied_with_other_names", count=len(level))]}
    return {**out, "outcome": "match"}
