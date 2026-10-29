"""FastANI — fragment-based average nucleotide identity (ANI) of a genome against a list of reference genomes.

Verified against FastANI 1.34 (Bioconda fastani-1.34-hb66fcc3_7, ARVA's lock docker/conda-locks/fastani/) from its
`--help`, its README (tag v1.34) and real runs (tests/fixtures/species):

* The query is cut into fragments of --fragLen bases (default 3,000); each fragment is mapped to the reference with
  MashMap's MinHash mapping, and ANI is the mean identity of the reciprocal (orthologous) mappings.
* `--rl FILE` takes one reference genome path per line. Defaults (--help): -k 16 (at most 16), -t 1, --fragLen 3,000,
  --minFraction 0.2 (the share of the smaller genome that must be shared for FastANI to report ANI),
  --maxRatioDiff 10.0. ARVA passes each one explicitly.
* Output (README, "Output format"): tab-separated query, reference, ANI, count of bidirectional fragment mappings and
  total query fragments; the alignment fraction with respect to the query is mappings / total fragments (ARVA ranks
  the lines itself). "No ANI output is reported for a genome pair if ANI value is much below 80%" (README); a query
  with no reported pair leaves the file empty.
* FastANI's options start at the beginning of their --help line ("-r, --ref <value>"), so ARVA reads them with its
  own pattern rather than the indented-options one.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

DEFAULTS = {"kmer": "16", "threads": "1", "fragLen": "3,000", "minFraction": "0.2", "maxRatioDiff": "10.0"}
FLAGS = ("-q", "--rl", "-o", "-t", "-k", "--fragLen", "--minFraction", "--maxRatioDiff")
OUTPUT = "fastani.tsv"
LOG = "fastani.log"
_OPTION = re.compile(r"^(--?[A-Za-z][\w-]*)(?:,\s+(--[A-Za-z][\w-]*))?(?=[\s,]|$)")
_DEFAULT = re.compile(r"\[default\s*:\s*([^\]]+)\]")


@dataclass
class FastaniParams:
    threads: int = 1
    kmer: int = 16
    frag_len: int = 3000
    min_fraction: float = 0.2
    max_ratio_diff: float = 10.0

    def validate(self) -> None:
        errors = []
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if not 1 <= self.kmer <= 16:
            errors.append("kmer must be between 1 and 16 (FastANI: kmer size <= 16)")
        if self.frag_len < 1:
            errors.append("fragLen must be positive")
        if not 0 <= self.min_fraction <= 1:
            errors.append("minFraction must be between 0 and 1")
        if self.max_ratio_diff <= 0:
            errors.append("maxRatioDiff must be positive")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def help_options(text: str) -> frozenset[str]:
    found: set[str] = set()
    for line in text.splitlines():
        if m := _OPTION.match(line):
            found.update(o for o in m.groups() if o)
    return frozenset(found)


def help_defaults(text: str) -> dict[str, str]:
    """The default --help states for each option ARVA passes ("--fragLen <value>" … "[default : 3,000]")."""
    names = {"-k": "kmer", "-t": "threads", "--fragLen": "fragLen", "--minFraction": "minFraction",
             "--maxRatioDiff": "maxRatioDiff"}
    out, current = {}, None
    for line in text.splitlines():
        if m := _OPTION.match(line):
            current = names.get(m.group(1)) or names.get(m.group(2) or "")
        elif current and (d := _DEFAULT.search(line)):
            out[current] = d.group(1).strip()
            current = None
    return out


def parse_output(text: str) -> list[dict[str, Any]]:
    """FastANI's output: one line per reported pair (query, reference, ANI, mapped fragments, total fragments)."""
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 5:
            raise ValueError(f"FastANI output line {n} has {len(cols)} tab-separated columns instead of 5")
        try:
            ani, mapped, total = float(cols[2]), int(cols[3]), int(cols[4])
        except ValueError:
            raise ValueError(f"FastANI output line {n} has a value that is not a number") from None
        if not 0 <= ani <= 100 or mapped < 0 or total <= 0 or mapped > total:
            raise ValueError(f"FastANI output line {n} has values out of range")
        rows.append({"query": cols[0], "reference": cols[1], "ani": ani, "fragments_mapped": mapped,
                     "fragments_total": total, "af": mapped / total})
    return rows


class FastaniAdapter(ToolAdapter):
    info = ToolInfo(
        id="fastani",
        name="FastANI",
        description="Average nucleotide identity of a genome against reference genomes, from reciprocal mappings "
        "of 3 kb fragments (species identification against a reference genome collection).",
        homepage="https://github.com/ParBLiSS/FastANI",
        license="Apache-2.0",
        citation="Jain C., Rodriguez-R L.M., Phillippy A.M., Konstantinidis K.T., Aluru S. High throughput ANI "
        "analysis of 90K prokaryotic genomes reveals clear species boundaries. Nat Commun 2018;9:5114.",
        citation_url="https://doi.org/10.1038/s41467-018-07641-9",
        executable="fastANI",
        categories=("species",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="1.34",
        tested_versions=("1.34",),
        install={"conda_lock": "python3 scripts/conda_locks.py install fastani ~/.arva-tools/conda/fastani  # then "
                               "ARVA_TOOL_FASTANI=~/.arva-tools/conda/fastani/bin/fastANI"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"version (\d+\.\d+(?:\.\d+)?)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(FastaniAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: FastaniParams, query: Path, ref_list: Path, out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this FastANI version does not offer {', '.join(missing)} (not in its --help)")
        return [executable, "-q", str(query), "--rl", str(ref_list), "-o", str(out_dir / OUTPUT),
                "-t", str(params.threads), "-k", str(params.kmer), "--fragLen", str(params.frag_len),
                "--minFraction", f"{params.min_fraction:g}", "--maxRatioDiff", f"{params.max_ratio_diff:.1f}"]
