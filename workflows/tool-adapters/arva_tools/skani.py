"""skani — average nucleotide identity and aligned fraction from sparse approximate alignments (sparse chaining of
sampled k-mers), for genomes against reference genomes.

Verified against skani 0.4.0 (Bioconda skani-0.4.0-hec9b1f2_0, ARVA's lock docker/conda-locks/skani/) from
`skani dist --help` and real runs (tests/fixtures/species):

* `skani dist -q QUERY --rl LIST` compares the query with every genome of the list (one path per line); the
  references are sketched in memory on each run.
* Defaults (--help): -t 3, -c 125 (compression factor, k-mer subsampling rate), -m 1000 (marker k-mer compression),
  -s 80 ("screen out pairs with *approximately* < % identity"), --min-af 15 ("only output ANI values where one genome
  has aligned fraction > than this value"). ARVA passes each one explicitly.
* skani's learned ANI (a regression model trained on MAGs) is on by default "for c >= 70 and >= 150,000 bases
  aligned and not on individual contigs"; ARVA keeps it and records the log line "Learned ANI mode detected".
* Output (-o): a header Ref_file, Query_file, ANI, Align_fraction_ref, Align_fraction_query, Ref_name, Query_name;
  aligned fractions are percentages; the names are each file's first sequence header. A query with no reported pair
  writes only the header.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

DEFAULTS = {"threads": "3", "c": "125", "m": "1000", "s": "80", "min_af": "15"}
FLAGS = ("-q", "--rl", "-o", "-t", "-c", "-m", "-s", "--min-af")
OUTPUT = "skani.tsv"
LOG = "skani.log"
HEADER = ["Ref_file", "Query_file", "ANI", "Align_fraction_ref", "Align_fraction_query", "Ref_name", "Query_name"]
LEARNED = "Learned ANI mode detected"
_DEFAULT = re.compile(r"\[default:\s*([^\]]+)\]")


@dataclass
class SkaniParams:
    threads: int = 3
    c: int = 125
    m: int = 1000
    s: float = 80.0
    min_af: float = 15.0

    def validate(self) -> None:
        errors = []
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if self.c < 1 or self.m < 1:
            errors.append("-c and -m must be positive")
        if not 0 <= self.s <= 100 or not 0 <= self.min_af <= 100:
            errors.append("-s and --min-af are percentages (0 to 100)")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def help_defaults(text: str) -> dict[str, str]:
    """The defaults `skani dist --help` states for the options ARVA passes."""
    names = {"-t": "threads", "-c": "c", "-m": "m", "-s": "s", "--min-af": "min_af"}
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            flag = stripped.split()[0].rstrip(",")
            current = names.get(flag)
        if current and (d := _DEFAULT.search(line)) and current not in out:
            out[current] = d.group(1).strip()
    return out


def _percent(text: str, what: str, n: int) -> float:
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"skani output line {n}: {what} is not a number") from None
    if not 0 <= v <= 100:
        raise ValueError(f"skani output line {n}: {what} is out of range")
    return v


def parse_output(text: str) -> list[dict[str, Any]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].split("\t") != HEADER:
        raise ValueError("skani's output does not start with " + " ".join(HEADER))
    rows = []
    for n, line in enumerate(lines[1:], 2):
        cols = line.split("\t")
        if len(cols) != len(HEADER):
            raise ValueError(f"skani output line {n} has {len(cols)} columns instead of {len(HEADER)}")
        af_ref, af_query = _percent(cols[3], "Align_fraction_ref", n), _percent(cols[4], "Align_fraction_query", n)
        rows.append({"reference": cols[0], "query": cols[1], "ani": _percent(cols[2], "ANI", n),
                     "af_reference": af_ref / 100, "af_query": af_query / 100, "af": min(af_ref, af_query) / 100,
                     "reference_name": cols[5], "query_name": cols[6]})
    return rows


class SkaniAdapter(ToolAdapter):
    info = ToolInfo(
        id="skani",
        name="skani",
        description="Average nucleotide identity and aligned fraction of a genome against reference genomes, from "
        "sparse approximate alignments (species identification against a reference genome collection).",
        homepage="https://github.com/bluenote-1577/skani",
        license="MIT",
        citation="Shaw J., Yu Y.W. Fast and robust metagenomic sequence comparison through sparse chaining with "
        "skani. Nat Methods 2023;20:1661-1665.",
        citation_url="https://doi.org/10.1038/s41592-023-02018-3",
        executable="skani",
        categories=("species",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="0.4.0",
        tested_versions=("0.4.0",),
        install={"conda_lock": "python3 scripts/conda_locks.py install skani ~/.arva-tools/conda/skani  # then "
                               "ARVA_TOOL_SKANI=~/.arva-tools/conda/skani/bin/skani"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"skani (\d+\.\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("dist", "--help"))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(SkaniAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: SkaniParams, query: Path, ref_list: Path, out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this skani version does not offer {', '.join(missing)} (not in its dist --help)")
        return [executable, "dist", "-q", str(query), "--rl", str(ref_list), "-o", str(out_dir / OUTPUT),
                "-t", str(params.threads), "-c", str(params.c), "-m", str(params.m), "-s", f"{params.s:g}",
                "--min-af", f"{params.min_af:g}"]
