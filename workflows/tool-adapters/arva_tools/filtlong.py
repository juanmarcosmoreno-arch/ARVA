"""Filtlong — quality filtering of long reads (Nanopore, PacBio).

Options verified against `filtlong --help` and the v0.2.1 README.
Important: --min_mean_q and --min_window_q are percent identities (0-100)
derived from Phred scores, NOT Phred values (README, "Read scoring").
Filtlong writes the kept reads to stdout; ARVA gzip-streams them to a file.
Filtlong formats the counts in its log with the process locale (en_US writes 1,362,402, es_ES
1.362.402, and a locale that is not installed makes it abort), so ARVA runs it with LC_ALL=C.
A coverage target is ARVA's own derivation: target_bases = round(coverage * genome size); Filtlong
only ever receives --target_bases, and keeps reads while its running total is below it (main.cpp),
so it may overshoot by up to one read.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from arva_tools.base import ToolAdapter, ToolInfo

ENVIRONMENT = {"LC_ALL": "C"}
_GROUPED = re.compile(r"\b\d{1,3}([,.])\d{3}(?:\1\d{3})*\b")
NOT_ENOUGH_READS = "not enough reads to reach target"
BELOW_TARGET = "reads already fall below target after filtering"


def target_bases_for_coverage(genome_size_bp: int, coverage_x: float) -> int:
    # Half up, like the interface's Math.round, so both sides compute the same target.
    return math.floor(coverage_x * genome_size_bp + 0.5)


def identity_to_phred(identity_percent: float) -> float:
    """Filtlong mean identity (%) -> equivalent mean-error Phred value."""
    if identity_percent >= 100:
        return math.inf
    return -10 * math.log10(1 - identity_percent / 100)


@dataclass
class FiltlongParams:
    min_length: int | None = None
    max_length: int | None = None
    min_mean_q: float | None = None
    min_window_q: float | None = None
    keep_percent: float | None = None
    target_bases: int | None = None
    length_weight: float = 1.0
    mean_q_weight: float = 1.0
    window_q_weight: float = 1.0
    window_size: int = 250
    # Provenance of a coverage target; never passed to Filtlong.
    genome_size_bp: int | None = None
    target_coverage_x: float | None = None

    def validate(self) -> None:
        thresholds = (self.min_length, self.max_length, self.min_mean_q, self.min_window_q,
                      self.keep_percent, self.target_bases)
        errors = []
        if all(t is None for t in thresholds):
            errors.append("set at least one threshold (otherwise Filtlong keeps every read)")
        if self.min_length is not None and self.min_length < 1:
            errors.append("min_length must be ≥ 1")
        if self.max_length is not None and self.max_length < 1:
            errors.append("max_length must be ≥ 1")
        if self.min_length and self.max_length and self.max_length < self.min_length:
            errors.append("max_length must be ≥ min_length")
        for name in ("min_mean_q", "min_window_q"):
            v = getattr(self, name)
            if v is not None and not 0 <= v < 100:
                errors.append(f"{name} is a percent identity and must be in [0, 100)")
        if self.keep_percent is not None and not 0 < self.keep_percent <= 100:
            errors.append("keep_percent must be in (0, 100]")
        if self.target_bases is not None and self.target_bases < 1:
            errors.append("target_bases must be ≥ 1")
        for name in ("length_weight", "mean_q_weight", "window_q_weight"):
            if getattr(self, name) < 0:
                errors.append(f"{name} must be ≥ 0")
        if self.window_size < 1:
            errors.append("window_size must be ≥ 1")
        genome, depth = self.genome_size_bp, self.target_coverage_x
        if (genome is None) != (depth is None):
            errors.append("a coverage target needs both genome_size_bp and target_coverage_x")
        elif genome is not None and depth is not None:
            if genome < 1 or depth <= 0:
                errors.append("genome_size_bp must be ≥ 1 and target_coverage_x > 0")
            elif self.target_bases != (target := target_bases_for_coverage(genome, depth)):
                errors.append(f"target_bases must be round(target_coverage_x × genome_size_bp) = {target}")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict:
        return asdict(self)


class FiltlongAdapter(ToolAdapter):
    info = ToolInfo(
        id="filtlong",
        name="Filtlong",
        description="Filters long reads by length and quality, keeping the best reads; outputs a "
        "subset of the input reads (it never edits read sequences unless trimming is requested).",
        homepage="https://github.com/rrwick/Filtlong",
        license="GPL-3.0-or-later",
        citation="Wick RR. Filtlong. https://github.com/rrwick/Filtlong",
        citation_url="https://github.com/rrwick/Filtlong",
        executable="filtlong",
        categories=("filtering",),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("fastq.gz",),
        min_version="0.2.0",
        tested_versions=("0.2.1",),
        install={"conda": "bioconda::filtlong", "apt": "filtlong"},
    )
    version_pattern = re.compile(r"filtlong\s+v?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)

    @staticmethod
    def argv(executable: str, params: FiltlongParams, input_path: Path) -> list[str]:
        params.validate()
        a = [executable]
        for flag, value in (
            ("--min_length", params.min_length),
            ("--max_length", params.max_length),
            ("--min_mean_q", params.min_mean_q),
            ("--min_window_q", params.min_window_q),
            ("--keep_percent", params.keep_percent),
            ("--target_bases", params.target_bases),
        ):
            if value is not None:
                a += [flag, _num(value)]
        a += [
            "--length_weight", _num(params.length_weight),
            "--mean_q_weight", _num(params.mean_q_weight),
            "--window_q_weight", _num(params.window_q_weight),
            "--window_size", str(params.window_size),
            str(input_path),
        ]
        return a

    @staticmethod
    def parse_log(text: str) -> dict:
        """The totals Filtlong prints to stderr and, with a target, which of its three outcomes applied."""
        text = plain_counts(text)
        out = {}
        scoring = text.split("Filtering long reads")[0]
        counts = re.findall(r"(\d+) reads \((\d+) bp\)", scoring)
        if counts:
            reads, bases = counts[-1]
            out["input_reads"] = int(reads)
            out["input_bases"] = int(bases)
        m = re.search(r"target: (\d+) bp", text)
        if m:
            out["target_bases_reported"] = int(m.group(1))
            # Either outcome means the target removed no reads (hard thresholds still apply).
            out["not_enough_reads_for_target"] = NOT_ENOUGH_READS in text
            out["below_target_after_filtering"] = BELOW_TARGET in text
        m = re.search(r"keeping (\d+) bp", text)
        if m:
            out["kept_bases_reported"] = int(m.group(1))
        return out


def plain_counts(log: str) -> str:
    """The log with digit grouping removed from its counts (all integers), as the C locale writes them."""
    return _GROUPED.sub(lambda m: m.group(0).replace(m.group(1), ""), log)


def _num(v: float | int) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
