"""SNP-sites — the variable columns of a multiple alignment (a SNP alignment for SNP-based trees).

Verified against SNP-sites 2.5.1 (Ubuntu snp-sites 2.5.1-2): its usage text (snp-sites with no argument, exit status
0; fixtures/phylogeny/snp_sites_usage_2.5.1.txt), `-V` ("snp-sites 2.5.1") and runs on a constructed alignment and on
Panaroo's core-genome alignment (fixtures/phylogeny/README.md):

* `snp-sites -m -o <out> <aln>`: a FASTA alignment of the columns holding at least two of A, C, G and T (gaps and N
  are not counted as a state, and a column with them stays in when it is variable among the others).
* `-c` keeps only those columns made exclusively of A, C, G and T: no column is then constant in any sense, as
  IQ-TREE's +ASC requires.
* `-C -o <out> <aln>` writes only "a,c,g,t": the number of constant columns of each base (columns with gaps or N
  whose bases all agree count as constant), the counts IQ-TREE's -fconst takes.
"""
from __future__ import annotations

import re

from arva_tools.base import ToolAdapter, ToolInfo, read_help

HELP_FLAGS = ("-m", "-c", "-C", "-o")


class SnpsitesAdapter(ToolAdapter):
    info = ToolInfo(
        id="snp-sites",
        name="SNP-sites",
        description="Extracts the variable columns of a multiple alignment (a SNP alignment) and counts its constant "
        "columns; ARVA uses it for SNP-based trees from a core-genome alignment.",
        homepage="https://github.com/sanger-pathogens/snp-sites",
        license="GPL-3.0-only",
        citation="Page AJ, Taylor B, Delaney AJ, et al. SNP-sites: rapid efficient extraction of SNPs from "
        "multi-FASTA alignments. Microb Genom 2016;2(4):e000056.",
        citation_url="https://doi.org/10.1099/mgen.0.000056",
        executable="snp-sites",
        categories=("phylogeny", "variants"),
        input_formats=("fasta",),
        output_formats=("fasta",),
        min_version="2.5",
        tested_versions=("2.5.1",),
        install={"apt": "snp-sites", "conda": "bioconda::snp-sites"},
    )
    version_args = ("-V",)
    version_pattern = re.compile(r"snp-sites (\d+\.\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ())

    @staticmethod
    def missing_flags(help_text: str) -> list[str]:
        return [f for f in HELP_FLAGS if not re.search(rf"^\s*{re.escape(f)}\s", help_text, re.M)]

    @staticmethod
    def snp_argv(executable: str, alignment: str, out: str, acgt_only: bool) -> list[str]:
        return [executable, "-m", *(["-c"] if acgt_only else []), "-o", out, alignment]

    @staticmethod
    def constant_argv(executable: str, alignment: str, out: str) -> list[str]:
        return [executable, "-C", "-o", out, alignment]


def parse_constant_counts(text: str) -> tuple[int, int, int, int]:
    m = re.fullmatch(r"\s*(\d+),(\d+),(\d+),(\d+)\s*", text)
    if not m:
        raise ValueError("snp-sites -C did not write four comma-separated counts")
    a, c, g, t = (int(x) for x in m.groups())
    return a, c, g, t
