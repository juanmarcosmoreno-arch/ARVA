"""Racon — consensus polishing of an assembly with long reads aligned to it.

Verified against Racon 1.5.0 (Ubuntu package 1.5.0-3; Debian bookworm ships the same upstream release): `racon
--help` (fixtures/polishing) and real runs on the synthetic genome with minimap2 2.26 overlaps:

* `racon [options] <sequences> <overlaps> <target sequences>` writes the polished targets to stdout. The reads can
  be FASTA/FASTQ, gzip-compressed; overlaps PAF, MHAP or SAM. Racon picks each format from the file name.
* Defaults (--help): -m 3 (match), -x -5 (mismatch), -g -4 (gap; must be negative), -w 500 (window length), -q 10.0
  (minimum average base quality of a window's reads), -e 0.3 (maximum overlap error rate), -t 1. ARVA passes all of
  them explicitly.
* Without -u Racon leaves out every target it could not polish (no overlaps), which would silently remove contigs;
  ARVA always passes -u (--include-unpolished).
* Racon builds the consensus window by window and by default trims each window's consensus where few reads support
  it. At the ends of a contig fewer reads align, so trimming shortens contigs: on the synthetic genome one round
  removed 8 bp from the start and 17 bp from the end of a 100 kb circular chromosome, a second round 5 bp more.
  --no-trimming avoids that but left 60 spurious single-base insertions at window boundaries (every 500 bp) in the
  same test, so ARVA keeps Racon's default and reports the bases lost at contig ends (MUMmer dnadiff coordinates).
* Each output header is "<name> LN:i:<length> RC:i:<reads> XC:f:<fraction>": the contig keeps its name; RC is the
  number of reads (overlaps) Racon used for it and XC the fraction of its windows Racon polished.
* Racon is a generic consensus tool: it uses no model of a sequencing technology's errors (unlike Medaka for
  Oxford Nanopore data, which needs a model matching the basecaller).
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help
from arva_tools.mapping import LONG_READ_PRESETS

MAX_ROUNDS = 5
_READ_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fastq|fq)(\.gz)?")
_FASTA_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fasta|fa)")
_HEADER = re.compile(r"(\S+)(?: LN:i:(\d+))?(?: RC:i:(\d+))?(?: XC:f:([\d.]+))?\s*")
_ERROR = re.compile(r"\[racon::[\w:]+\] error: (.+?)\s*$", re.M)


@dataclass
class RaconParams:
    read_type: str
    rounds: int = 1
    match: int = 3
    mismatch: int = -5
    gap: int = -4
    window_length: int = 500
    quality_threshold: float = 10.0
    error_threshold: float = 0.3
    threads: int = 1

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> RaconParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def validate(self) -> None:
        errors = []
        whole = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
        number = lambda v: isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)  # noqa: E731
        if self.read_type not in LONG_READ_PRESETS:
            errors.append(f"read_type must be one of {', '.join(LONG_READ_PRESETS)} (the minimap2 preset)")
        if not whole(self.rounds) or not 1 <= self.rounds <= MAX_ROUNDS:
            errors.append(f"rounds must be between 1 and {MAX_ROUNDS}")
        if not whole(self.match) or self.match < 1:
            errors.append("match must be a positive whole number")
        if not whole(self.mismatch) or self.mismatch > -1:
            errors.append("mismatch must be a negative whole number")
        if not whole(self.gap) or self.gap > -1:
            errors.append("gap must be a negative whole number (Racon requires a negative gap penalty)")
        if not whole(self.window_length) or not 100 <= self.window_length <= 10_000:
            errors.append("window_length must be between 100 and 10,000 bp")
        if not number(self.quality_threshold) or not 0 <= self.quality_threshold <= 60:
            errors.append("quality_threshold must be between 0 and 60")
        if not number(self.error_threshold) or not 0 < self.error_threshold <= 1:
            errors.append("error_threshold must be above 0 and at most 1")
        if not whole(self.threads) or not 1 <= self.threads <= 128:
            errors.append("threads must be between 1 and 128")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


FLAGS = ("-m", "-x", "-g", "-w", "-q", "-e", "-t", "-u")


def _num(v: float | int) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


class RaconAdapter(ToolAdapter):
    info = ToolInfo(
        id="racon",
        name="Racon",
        description="Consensus polishing of an assembly with long reads (Oxford Nanopore or PacBio) aligned to it; "
        "generic, with no model of a technology's errors. Unicycler also uses it.",
        homepage="https://github.com/lbcb-sci/racon",
        license="MIT",
        citation="Vaser R, Sović I, Nagarajan N, Šikić M. Fast and accurate de novo genome assembly from long "
        "uncorrected reads. Genome Res 2017;27(5):737-746.",
        citation_url="https://doi.org/10.1101/gr.214270.116",
        executable="racon",
        categories=("polishing", "long reads"),
        input_formats=("fasta", "fastq", "fastq.gz", "paf"),
        output_formats=("fasta",),
        min_version="1.4.0",
        tested_versions=("1.5.0",),
        install={"apt": "racon", "conda": "bioconda::racon"},
    )
    # `racon --version` prints "1.5.0" (some builds "v1.5.0").
    version_pattern = re.compile(r"^v?(\d+\.\d+\.\d+)", re.M)

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(read_help(executable))

    @staticmethod
    def argv(executable: str, params: RaconParams, reads: Path, overlaps: Path, target: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if not _READ_NAME.fullmatch(reads.name):
            raise ValueError(f"unsafe or unrecognised read file name for Racon: {reads.name}")
        if overlaps.suffix != ".paf" or not _FASTA_NAME.fullmatch(target.name):
            raise ValueError("Racon needs overlaps in a .paf file and targets in a .fasta file")
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this Racon version does not offer {', '.join(missing)} (not in its --help)")
        return [executable, "-m", str(params.match), "-x", str(params.mismatch), "-g", str(params.gap),
                "-w", str(params.window_length), "-q", _num(params.quality_threshold),
                "-e", _num(params.error_threshold), "-t", str(params.threads), "-u",
                str(reads), str(overlaps), str(target)]

    @staticmethod
    def parse_headers(headers: list[str]) -> dict[str, dict[str, Any]]:
        """Racon's output header lines (without '>') → length, reads used and fraction of windows polished, by
        contig name; values are None when Racon wrote no tag."""
        out: dict[str, dict[str, Any]] = {}
        for header in headers:
            m = _HEADER.fullmatch(header.strip())
            if not m:
                raise ValueError(f"not a Racon output header: {header[:80]!r}")
            out[m.group(1)] = {"length": int(m.group(2)) if m.group(2) else None,
                               "reads": int(m.group(3)) if m.group(3) else None,
                               "windows_polished": float(m.group(4)) if m.group(4) else None}
        return out

    @staticmethod
    def failure_reason(stderr: str, returncode: int | None) -> str | None:
        errors = _ERROR.findall(stderr.replace("\r", "\n"))
        if any(e.startswith("empty overlap set") for e in errors):
            return ("Racon found no overlaps: no read aligned to the assembly with minimap2. Check that the reads are "
                    "from this isolate and that the read type matches them")
        if returncode in (-9, 137):
            return "Racon was stopped by the operating system, most likely because the computer ran out of memory"
        if errors:
            return f"Racon failed: {errors[-1]}"
        return None
