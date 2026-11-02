"""BCFtools — variant calling from read alignments (mpileup + call), normalisation, hard filters and consequence
annotation (csq).

Verified against bcftools 1.19 (Ubuntu bcftools 1.19-1build2, htslib 1.19): its usage texts (fixtures/variants;
`bcftools mpileup` with no argument and `bcftools <command> -h` exit with status 1 or 255), the online manual and the
1.19 source of csq.c, and real runs (fixtures/variants/README.md):

* mpileup: `-X/--config` profiles are shorthands for options: illumina = the defaults, ont = `-B -Q5 --max-BQ 30 -I`,
  pacbio-ccs = `-D -Q5 --max-BQ 50 -F0.1 -o25 -e1 --delta-BQ 10 -M99999`. ARVA never passes -X: it writes every
  option out. Defaults in 1.19's usage: -q 0, -Q 1, --max-BQ 60, --delta-BQ 30, -d 250, -F 0.05, -m 2, -o 40, -e 20,
  -h 500, -M 500, BAQ on in problematic regions. Reads of a pair that is not properly paired are skipped unless -A is
  given (ARVA keeps that default), as are unmapped, secondary, QC-failed and duplicate reads (--ns default).
* call: `--ploidy 1` makes every site haploid (bacteria); without it bcftools assumes diploid. -m is the
  multiallelic caller, -P its prior (default 1.1e-3), -v keeps variant sites only.
* norm: `-f` left-aligns indels against the reference, `-m -any` splits multiallelic records, `-c e` stops when a
  REF allele does not match the reference.
* filter: `-s NAME -e EXPR` writes NAME in FILTER where EXPR is true (soft filter, the record stays); `-m +` adds to
  the FILTER of earlier passes instead of replacing it.
* csq: needs an Ensembl-style GFF3 (gene ID=gene:..;biotype=..; transcript ID=transcript:..;Parent=gene:..;
  biotype=..; CDS Parent=transcript:..), writes INFO/BCSQ "Consequence|gene|transcript|biotype|strand|
  amino_acid_change|dna_change". It translates with the standard genetic code only (csq.c `gencode`) and reports
  start_lost only when the reference's first codon is ATG: in bacterial genes starting with GTG or TTG (code 11) a
  change of the start codon is reported as missense or synonymous. `-p a` takes genotypes as they are (haploid calls
  have no unphased heterozygotes); -n caps the per-haplotype consequences (default 15).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo
from arva_tools.runner import isolated_home, tool_environment

TECHNOLOGIES = ("illumina", "ont", "pacbio_hifi")
SOFT_FILTERS = ("LowQual", "LowDepth", "LowAltFraction")
COMMANDS = ("mpileup", "call", "norm", "filter", "csq", "index")
# The options ARVA passes, per command, as each usage text lists them.
HELP_FLAGS = {
    "mpileup": ("-f", "-q", "-Q", "--max-BQ", "--delta-BQ", "-d", "-B", "-D", "-I", "-F", "-m", "-o", "-e", "-h",
                "-M", "-a", "-O", "--threads"),
    "call": ("--ploidy", "-m", "-P", "-v", "-O", "-o"),
    "norm": ("-f", "-m", "-c", "-O", "-o"),
    "filter": ("-s", "-e", "-m", "-O", "-o"),
    "csq": ("-f", "-g", "-p", "-n", "-O", "-o"),
    "index": ("-t", "-f"),
}

# Per technology: the values of bcftools' own -X profiles (illumina = its defaults), written out, and the mapping
# quality and base quality floors ARVA proposes.
PROFILES: dict[str, dict[str, Any]] = {
    "illumina": {"baq": "partial", "min_baseq": 13, "max_baseq": 60, "delta_baseq": 30, "gap_fraction": 0.05,
                 "min_gapped_reads": 2, "gap_open": 40, "gap_extend": 20, "tandem_qual": 500, "max_read_len": 500,
                 "call_indels": True},
    "ont": {"baq": "off", "min_baseq": 5, "max_baseq": 30, "delta_baseq": 30, "gap_fraction": 0.05,
            "min_gapped_reads": 2, "gap_open": 40, "gap_extend": 20, "tandem_qual": 500, "max_read_len": 500,
            "call_indels": False},
    "pacbio_hifi": {"baq": "full", "min_baseq": 5, "max_baseq": 50, "delta_baseq": 10, "gap_fraction": 0.1,
                    "min_gapped_reads": 2, "gap_open": 25, "gap_extend": 1, "tandem_qual": 500,
                    "max_read_len": 99999, "call_indels": True},
}
# Snippy 4.6.0's defaults (bin/snippy: --mapqual 60, --mincov 10, --minqual 100; README: "Values of 10 and 0.9 are
# commonly used" for --mincov and --minfrac). Snippy's QUAL comes from FreeBayes; bcftools' QUAL is another model
# (it rarely exceeds ~228), so the same number is not an equivalent threshold.
FILTER_DEFAULTS = {"min_mapq": 60, "min_qual": 100.0, "min_depth": 10, "min_alt_fraction": 0.9}
# bcftools' own default is -d 250; ARVA reads up to 1000 per position so that ordinary bacterial depths are not
# subsampled (and the DP it reports is not capped at 250).
MAX_DEPTH_DEFAULT = 1000
CALL_PRIOR_DEFAULT = 1.1e-3
CSQ_MAX_CONSEQUENCES = 15


@dataclass
class VariantParams:
    technology: str = "illumina"
    min_mapq: int = FILTER_DEFAULTS["min_mapq"]
    min_baseq: int | None = None
    max_depth: int = MAX_DEPTH_DEFAULT
    call_indels: bool | None = None
    prior: float = CALL_PRIOR_DEFAULT
    min_qual: float = FILTER_DEFAULTS["min_qual"]
    min_depth: int = FILTER_DEFAULTS["min_depth"]
    min_alt_fraction: float = FILTER_DEFAULTS["min_alt_fraction"]
    threads: int = 4

    def __post_init__(self) -> None:
        profile = PROFILES.get(self.technology)
        if profile is not None:
            if self.min_baseq is None:
                self.min_baseq = profile["min_baseq"]
            if self.call_indels is None:
                self.call_indels = profile["call_indels"]

    def validate(self) -> None:
        if self.technology not in TECHNOLOGIES:
            raise ValueError(f"technology must be one of {', '.join(TECHNOLOGIES)}")
        if not 0 <= self.min_mapq <= 60:
            raise ValueError("the minimum mapping quality must be between 0 and 60")
        if self.min_baseq is None or not 0 <= self.min_baseq <= 60:
            raise ValueError("the minimum base quality must be between 0 and 60")
        if not 10 <= self.max_depth <= 100_000:
            raise ValueError("the maximum depth per position must be between 10 and 100000")
        if not 0 < self.prior < 1:
            raise ValueError("the prior must be between 0 and 1")
        if not 0 <= self.min_qual <= 10_000:
            raise ValueError("the minimum QUAL must be between 0 and 10000")
        if not 0 <= self.min_depth <= 10_000:
            raise ValueError("the minimum depth must be between 0 and 10000")
        if not 0 <= self.min_alt_fraction <= 1:
            raise ValueError("the minimum alternative-allele fraction must be between 0 and 1")
        if not 1 <= self.threads <= 256:
            raise ValueError("threads must be between 1 and 256")

    def profile(self) -> dict[str, Any]:
        return {**PROFILES[self.technology], "min_baseq": self.min_baseq, "call_indels": self.call_indels}

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "mpileup": self.profile(), "ploidy": 1, "caller": "multiallelic (-m)",
                "count_orphans": False, "skip_flags": "UNMAP,SECONDARY,QCFAIL,DUP"}


def _num(v: float) -> str:
    return format(v, "g")


def filter_expressions(p: VariantParams) -> list[tuple[str, str]]:
    """The soft filters, in order: (FILTER name, bcftools expression that sets it). The alternative-allele fraction is
    AD[alt] / (AD[ref] + AD[alt]) of the (split, biallelic) record, written without a division so that a site
    with no reads in AD is not divided by zero."""
    return [
        ("LowQual", f"QUAL<{_num(p.min_qual)}"),
        ("LowDepth", f"FORMAT/DP<{p.min_depth}"),
        ("LowAltFraction", f"FORMAT/AD[0:1] < {_num(p.min_alt_fraction)}*(FORMAT/AD[0:0]+FORMAT/AD[0:1])"),
    ]


class BcftoolsAdapter(ToolAdapter):
    info = ToolInfo(
        id="bcftools",
        name="BCFtools",
        description="Calls SNPs and small indels from read alignments against a reference (mpileup + call, haploid), "
        "normalises and soft-filters them and annotates their effects on coding sequences (csq).",
        homepage="https://samtools.github.io/bcftools/",
        license="MIT (with GPL-3.0-or-later parts, per Debian's copyright file)",
        citation="Danecek P, Bonfield JK, Liddle J, et al. Twelve years of SAMtools and BCFtools. GigaScience "
        "2021;10(2):giab008.",
        citation_url="https://doi.org/10.1093/gigascience/giab008",
        executable="bcftools",
        categories=("variants",),
        input_formats=("bam", "fasta", "gff3"),
        output_formats=("vcf.gz",),
        min_version="1.16",
        tested_versions=("1.19",),
        install={"apt": "bcftools", "conda": "bioconda::bcftools"},
    )
    # `bcftools --version` starts with "bcftools 1.19".
    version_pattern = re.compile(r"^bcftools (\d+\.\d+(?:\.\d+)?)", re.M)

    @staticmethod
    def help_text(executable: str, command: str) -> str:
        """The usage of one subcommand: `bcftools mpileup` with no argument (its -h takes a value), `-h` for the
        others; they print to stderr and exit with status 1 or 255."""
        if command not in COMMANDS:
            raise ValueError(f"unknown bcftools command {command}")
        args = [command] if command == "mpileup" else [command, "-h"]
        with isolated_home() as home:
            proc = subprocess.run([executable, *args], capture_output=True, text=True, errors="replace", timeout=60,
                                  env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
        text = proc.stdout + proc.stderr
        if proc.returncode not in (0, 1, 255) or "Usage:" not in text:
            raise RuntimeError(f"bcftools {' '.join(args)} exited with status {proc.returncode}")
        return text

    @staticmethod
    def missing_flags(command: str, help_text: str) -> list[str]:
        return [f for f in HELP_FLAGS[command]
                if not re.search(rf"(^|[\s,]){re.escape(f)}([\s,]|$)", help_text, re.M)]

    @staticmethod
    def mpileup_argv(executable: str, reference: Path, bam: Path, out: Path, p: VariantParams) -> list[str]:
        pr = p.profile()
        baq = {"partial": [], "off": ["-B"], "full": ["-D"]}[pr["baq"]]
        return [executable, "mpileup", "-f", str(reference), "-q", str(p.min_mapq), "-Q", str(pr["min_baseq"]),
                "--max-BQ", str(pr["max_baseq"]), "--delta-BQ", str(pr["delta_baseq"]), "-d", str(p.max_depth),
                *baq, *([] if pr["call_indels"] else ["-I"]), "-F", _num(pr["gap_fraction"]),
                "-m", str(pr["min_gapped_reads"]), "-o", str(pr["gap_open"]), "-e", str(pr["gap_extend"]),
                "-h", str(pr["tandem_qual"]), "-M", str(pr["max_read_len"]), "-a", "FORMAT/AD,FORMAT/DP",
                "--threads", str(p.threads), "-O", "u", "-o", str(out), str(bam)]

    @staticmethod
    def call_argv(executable: str, pileup: Path, out: Path, p: VariantParams) -> list[str]:
        return [executable, "call", "--ploidy", "1", "-m", "-P", _num(p.prior), "-v", "-O", "u", "-o", str(out),
                str(pileup)]

    @staticmethod
    def norm_argv(executable: str, reference: Path, calls: Path, out: Path) -> list[str]:
        return [executable, "norm", "-f", str(reference), "-m", "-any", "-c", "e", "-O", "u", "-o", str(out),
                str(calls)]

    @staticmethod
    def filter_argv(executable: str, name: str, expression: str, src: Path, out: Path, add: bool,
                    compressed: bool) -> list[str]:
        return [executable, "filter", "-s", name, "-e", expression, *(["-m", "+"] if add else []),
                "-O", "z" if compressed else "u", "-o", str(out), str(src)]

    @staticmethod
    def csq_argv(executable: str, reference: Path, gff: Path, src: Path, out: Path) -> list[str]:
        return [executable, "csq", "-f", str(reference), "-g", str(gff), "-p", "a", "-n", str(CSQ_MAX_CONSEQUENCES),
                "-O", "z", "-o", str(out), str(src)]

    @staticmethod
    def index_argv(executable: str, vcf: Path) -> list[str]:
        return [executable, "index", "-t", "-f", str(vcf)]


def flags_used(p: VariantParams) -> dict[str, list[str]]:
    pr = p.profile()
    mp = [f for f in HELP_FLAGS["mpileup"] if f not in ("-B", "-D", "-I")]
    mp += {"partial": [], "off": ["-B"], "full": ["-D"]}[pr["baq"]] + ([] if pr["call_indels"] else ["-I"])
    return {**HELP_FLAGS, "mpileup": mp}
