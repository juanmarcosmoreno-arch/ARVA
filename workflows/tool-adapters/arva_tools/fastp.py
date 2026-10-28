"""fastp — short-read quality control, adapter trimming and filtering.

Every option below was checked against `fastp --help` of fastp 0.23.4 and 0.23.2.
ARVA always passes every filtering option explicitly — including values equal
to fastp's defaults — so the recorded command fully describes what was removed.
fastp.json was verified for 0.23.4: numbers have 6 significant digits and zeros may be integers;
duplication holds only 'rate'; the insert-size histogram comes from worker thread 0 alone.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from arva_tools.base import ToolAdapter, ToolInfo

# fastp's insertSizeMax: pairs without a detected overlap and inserts of 512 bp or more are 'unknown'.
INSERT_SIZE_MAX = 512
# fastp's own limits (options.cpp, 0.23.2 and 0.23.4): it exits with an error outside them.
TRIM_FRONT_MAX = 30
TRIM_TAIL_MAX = 100
# fastp reads lengths as a C int; adapters must be longer than 3 bases of A, C, G, T (ARVA caps the length).
LENGTH_MAX = 2**31 - 1
ADAPTER_PATTERN = re.compile(r"[ACGT]{4,200}")
READ2_OPTIONS = ("trim_front2", "trim_tail2", "max_len2", "adapter_sequence_r2")
REMOVAL_REASONS = {
    "low_quality_reads": "low quality",
    "too_many_N_reads": "too many N",
    "too_short_reads": "too short",
    "too_long_reads": "too long",
    "low_complexity_reads": "low complexity",
}
_QUALITY_CURVES = ("mean", "A", "T", "C", "G")
_CONTENT_CURVES = ("A", "T", "C", "G", "GC", "N")


def _curves(section: dict) -> dict:
    quality, content = section.get("quality_curves") or {}, section.get("content_curves") or {}
    return {
        "total_reads": section.get("total_reads"),
        "total_cycles": section.get("total_cycles"),
        "quality": {k: [float(v) for v in quality[k]] for k in _QUALITY_CURVES if k in quality},
        "content": {k: [float(v) for v in content[k]] for k in _CONTENT_CURVES if k in content},
    }


def _adapter_cutting(block: dict) -> dict:
    def counts(name: str) -> list[dict]:
        return [{"sequence": seq, "count": int(n)} for seq, n in (block.get(name) or {}).items()]

    return {
        "adapter_trimmed_reads": block.get("adapter_trimmed_reads"),
        "adapter_trimmed_bases": block.get("adapter_trimmed_bases"),
        "read1_adapter_sequence": block.get("read1_adapter_sequence"),
        "read2_adapter_sequence": block.get("read2_adapter_sequence"),
        "read1_adapter_counts": counts("read1_adapter_counts"),
        "read2_adapter_counts": counts("read2_adapter_counts"),
    }


def removed_reads(filtering_result: dict, length_limit: int = 0) -> str:
    """fastp's removal counts in words; 'too long' is always in the JSON but can be non-zero only with a length limit."""
    parts = []
    for key, n in filtering_result.items():
        if key == "passed_filter_reads" or (key == "too_long_reads" and not length_limit and not n):
            continue
        parts.append(f"{REMOVAL_REASONS.get(key, key.replace('_', ' '))} {n:,}")
    return ", ".join(parts)


def _insert_size(block: dict) -> dict:
    histogram = [int(v) for v in block.get("histogram") or []]
    unknown = int(block.get("unknown") or 0)
    overlapping = sum(histogram)
    evaluated = overlapping + unknown
    return {
        # fastp reports peak 0 when no pair overlapped.
        "peak": block.get("peak") if overlapping else None,
        "unknown": unknown,
        "overlapping_pairs": overlapping,
        "evaluated_pairs": evaluated,
        "histogram": histogram,
        "histogram_percent": [100 * v / evaluated for v in histogram] if evaluated else [],
        "unknown_percent": 100 * unknown / evaluated if evaluated else None,
        "insert_size_max": INSERT_SIZE_MAX,
    }

@dataclass
class FastpParams:
    # Adapter trimming (fastp default: enabled; auto-detection for SE, overlap analysis for PE)
    adapter_trimming: bool = True
    detect_adapter_for_pe: bool = True
    # Quality filtering (fastp defaults: enabled, Q15, 40 % unqualified bases allowed)
    quality_filtering: bool = True
    qualified_quality_phred: int = 15
    unqualified_percent_limit: int = 40
    n_base_limit: int = 5
    average_qual: int = 0
    # Length filtering (fastp default: enabled, 15 bp); length_limit DISCARDS longer reads (0 = off)
    length_filtering: bool = True
    length_required: int = 15
    length_limit: int = 0
    # Fixed trimming; max_len TRIMS the 3' end to that length (0 = off). Read-2 values None follow read 1.
    trim_front1: int = 0
    trim_tail1: int = 0
    max_len1: int = 0
    trim_front2: int | None = None
    trim_tail2: int | None = None
    max_len2: int | None = None
    # Adapter sequences instead of auto-detection (None = fastp's automatic behaviour)
    adapter_sequence: str | None = None
    adapter_sequence_r2: str | None = None
    # Low-complexity filter (fastp default: off; 30 % of bases must differ from the next base)
    low_complexity_filter: bool = False
    complexity_threshold: int = 30
    # Sliding-window trimming (fastp default: off)
    cut_front: bool = False
    cut_tail: bool = False
    cut_window_size: int = 4
    cut_mean_quality: int = 20
    # PolyG trimming: fastp enables it automatically for NextSeq/NovaSeq data
    poly_g: Literal["auto", "force", "disable"] = "auto"
    # Deduplication (fastp default: off)
    dedup: bool = False
    threads: int = 3

    def validate(self, paired: bool | None = None) -> None:
        """`paired` False rejects read-2 options for single-end input; None leaves the layout unchecked."""
        checks = [
            (0 <= self.qualified_quality_phred <= 93, "qualified_quality_phred must be 0–93"),
            (0 <= self.unqualified_percent_limit <= 100, "unqualified_percent_limit must be 0–100"),
            (self.n_base_limit >= 0, "n_base_limit must be ≥ 0"),
            (0 <= self.average_qual <= 93, "average_qual must be 0–93"),
            (self.length_required >= 0, "length_required must be ≥ 0"),
            (1 <= self.cut_window_size <= 1000, "cut_window_size must be 1–1000"),
            (1 <= self.cut_mean_quality <= 30, "cut_mean_quality must be 1–30"),
            (1 <= self.threads <= 16, "threads must be 1–16"),
            (self.poly_g in ("auto", "force", "disable"), "poly_g must be auto, force or disable"),
            (0 <= self.length_limit <= LENGTH_MAX, "length_limit must be ≥ 0 (0 = no limit)"),
            (self.length_limit == 0 or self.length_filtering,
             "length_limit needs length filtering: fastp's --disable_length_filtering also turns --length_limit off"),
            (self.length_limit == 0 or not self.length_filtering or self.length_limit >= self.length_required,
             "length_limit must be 0 (off) or ≥ length_required, otherwise every read is discarded"),
            (0 <= self.complexity_threshold <= 100, "complexity_threshold must be 0–100"),
        ]
        for mate in ("1", "2"):
            front, tail, max_len = (getattr(self, f"{name}{mate}") for name in ("trim_front", "trim_tail", "max_len"))
            checks += [
                (front is None or 0 <= front <= TRIM_FRONT_MAX, f"trim_front{mate} must be 0–{TRIM_FRONT_MAX}"),
                (tail is None or 0 <= tail <= TRIM_TAIL_MAX, f"trim_tail{mate} must be 0–{TRIM_TAIL_MAX}"),
                (max_len is None or 0 <= max_len <= LENGTH_MAX, f"max_len{mate} must be ≥ 0 (0 = no limit)"),
            ]
        for name in ("adapter_sequence", "adapter_sequence_r2"):
            seq = getattr(self, name)
            checks += [
                (seq is None or ADAPTER_PATTERN.fullmatch(seq) is not None,
                 f"{name} must be 4–200 bases of A, C, G and T (upper case)"),
                (seq is None or self.adapter_trimming, f"{name} needs adapter trimming"),
            ]
        if paired is False:
            given = [name for name in READ2_OPTIONS if getattr(self, name) is not None]
            checks.append((not given, f"{', '.join(given)} apply to read 2, but this run is single-end"))
        errors = [msg for ok, msg in checks if not ok]
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict:
        return asdict(self)


class FastpAdapter(ToolAdapter):
    info = ToolInfo(
        id="fastp",
        name="fastp",
        description="All-in-one FASTQ preprocessor for short reads: quality control, adapter "
        "trimming, quality/length filtering and an HTML/JSON report.",
        homepage="https://github.com/OpenGene/fastp",
        license="MIT",
        citation="Chen S, Zhou Y, Chen Y, Gu J. fastp: an ultra-fast all-in-one FASTQ "
        "preprocessor. Bioinformatics 2018;34(17):i884–i890.",
        citation_url="https://doi.org/10.1093/bioinformatics/bty560",
        executable="fastp",
        categories=("qc", "filtering", "trimming"),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("fastq.gz", "json", "html"),
        min_version="0.23.0",
        tested_versions=("0.23.2", "0.23.4"),
        install={"conda": "bioconda::fastp", "apt": "fastp"},
    )
    version_pattern = re.compile(r"fastp\s+v?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)

    @staticmethod
    def argv(
        executable: str,
        params: FastpParams,
        in1: Path,
        out1: Path,
        json_path: Path,
        html_path: Path,
        in2: Path | None = None,
        out2: Path | None = None,
        title: str = "ARVA fastp report",
    ) -> list[str]:
        params.validate(paired=in2 is not None)
        a = [executable, "--in1", str(in1), "--out1", str(out1)]
        if in2 is not None:
            if out2 is None:
                raise ValueError("paired-end input requires out2")
            a += ["--in2", str(in2), "--out2", str(out2)]
        a += ["--json", str(json_path), "--html", str(html_path), "--report_title", title]
        a += ["--thread", str(params.threads), "--compression", "6"]

        if not params.adapter_trimming:
            a.append("--disable_adapter_trimming")
        else:
            if in2 is not None and params.detect_adapter_for_pe:
                a.append("--detect_adapter_for_pe")
            if params.adapter_sequence:
                a += ["--adapter_sequence", params.adapter_sequence]
            if in2 is not None and params.adapter_sequence_r2:
                a += ["--adapter_sequence_r2", params.adapter_sequence_r2]

        a += ["--trim_front1", str(params.trim_front1), "--trim_tail1", str(params.trim_tail1),
              "--max_len1", str(params.max_len1)]
        if in2 is not None:
            # fastp makes unset read-2 values follow read 1; ARVA writes them out so the command says so.
            a += ["--trim_front2", str(_or(params.trim_front2, params.trim_front1)),
                  "--trim_tail2", str(_or(params.trim_tail2, params.trim_tail1)),
                  "--max_len2", str(_or(params.max_len2, params.max_len1))]

        if params.quality_filtering:
            a += [
                "--qualified_quality_phred", str(params.qualified_quality_phred),
                "--unqualified_percent_limit", str(params.unqualified_percent_limit),
                "--n_base_limit", str(params.n_base_limit),
                "--average_qual", str(params.average_qual),
            ]
        else:
            a.append("--disable_quality_filtering")

        if params.low_complexity_filter:
            a += ["--low_complexity_filter", "--complexity_threshold", str(params.complexity_threshold)]

        if params.length_filtering:
            a += ["--length_required", str(params.length_required), "--length_limit", str(params.length_limit)]
        else:
            a.append("--disable_length_filtering")

        if params.cut_front or params.cut_tail:
            if params.cut_front:
                a.append("--cut_front")
            if params.cut_tail:
                a.append("--cut_tail")
            a += ["--cut_window_size", str(params.cut_window_size),
                  "--cut_mean_quality", str(params.cut_mean_quality)]

        if params.poly_g == "force":
            a.append("--trim_poly_g")
        elif params.poly_g == "disable":
            a.append("--disable_trim_poly_g")

        if params.dedup:
            a.append("--dedup")
        return a

    @staticmethod
    def parse_report(json_path: Path) -> dict:
        d = json.loads(Path(json_path).read_text())
        s = d["summary"]
        adapters = d.get("adapter_cutting") or {}
        insert = d.get("insert_size")
        return {
            "fastp_version": s.get("fastp_version"),
            "sequencing": s.get("sequencing"),
            "before_filtering": s["before_filtering"],
            "after_filtering": s["after_filtering"],
            "filtering_result": d.get("filtering_result", {}),
            "adapter_trimmed_reads": adapters.get("adapter_trimmed_reads"),
            "adapter_trimmed_bases": adapters.get("adapter_trimmed_bases"),
            "read1_adapter_sequence": adapters.get("read1_adapter_sequence"),
            "read2_adapter_sequence": adapters.get("read2_adapter_sequence"),
            "duplication_rate": (d.get("duplication") or {}).get("rate"),
            "insert_size_peak": (insert or {}).get("peak"),
            "insert_size": {k: v for k, v in _insert_size(insert).items() if not k.startswith("histogram")}
            if isinstance(insert, dict) else None,
            "command": d.get("command"),
        }

    @staticmethod
    def parse_data(json_path: Path) -> dict:
        """Per-cycle curves, adapter trimming, duplication rate and insert sizes for charts. Each block may be
        absent: adapter_cutting without adapter trimming (or when single-end detection finds no adapter),
        duplication with --dont_eval_duplication, insert_size for single-end data."""
        d = json.loads(Path(json_path).read_text())
        s = d.get("summary") or {}
        reads = {}
        for mate in ("read1", "read2"):
            stages = {stage: _curves(d[key]) for stage in ("before", "after")
                      if isinstance(d.get(key := f"{mate}_{stage}_filtering"), dict)}
            if stages:
                reads[mate] = stages
        adapters, insert = d.get("adapter_cutting"), d.get("insert_size")
        rate = (d.get("duplication") or {}).get("rate")
        return {
            "fastp_version": s.get("fastp_version"),
            "sequencing": s.get("sequencing"),
            "reads": reads,
            "adapter_cutting": _adapter_cutting(adapters) if isinstance(adapters, dict) else None,
            "duplication_rate": None if rate is None else float(rate),
            "insert_size": _insert_size(insert) if isinstance(insert, dict) else None,
        }


def _or(value: int | None, fallback: int) -> int:
    return fallback if value is None else value
