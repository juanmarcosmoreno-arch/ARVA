"""Mash — MinHash distance estimates between a genome and the genomes of a sketch file (.msh), such as the RefSeq
sketches on the Mash data page.

Verified against Mash 2.3 (Bioconda mash-2.3-hf85e966_11, ARVA's lock docker/conda-locks/mash/) from `mash dist -h`,
`mash info -h`, the Mash documentation (Distance Estimation) and real runs (tests/fixtures/species):

* `mash dist [options] <reference> <query>`: "The output fields are [reference-ID, query-ID, distance, p-value,
  shared-hashes]" (tab-separated, one line per reference; with the defaults -v 1.0 and -d 1.0 every reference is
  reported). The distance is Mash's estimate of the mutation rate between the two k-mer sets (Poisson model of the
  Jaccard index; Mash documentation), not an ANI value.
* With a sketch as the reference, the k-mer size is inherited from it: `-k` is refused ("The option -k cannot be
  used when a sketch is provided; it is inherited from the sketch"). ARVA therefore reads the sketch's k-mer size,
  sketch size and hash seed with `mash info -H` and records them, and passes only -p.
* `mash info -t` lists each sketch as #Hashes, Length, ID and Comment (tab-separated, after a "#Hashes…" header
  line, although -h says "with no header"); for sketches of FASTA files the comment is "[n seqs] <first header>
  [...]". ARVA takes the organism from that first header (its words after the sequence accession) — a heuristic.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

FLAGS = ("-p",)
OUTPUT = "mash.tsv"
LOG = "mash.log"
INFO_OUTPUT = "mash_info.tsv"
TOP = 25
_ACCESSION = re.compile(r"GC[AF]_\d{9}\.\d+")
_HEADER = {"seed": re.compile(r"Hash function \(seed\):\s+(.+?)\s+\((\d+)\)"),
           "kmer": re.compile(r"K-mer size:\s+(\d+)"),
           "alphabet": re.compile(r"Alphabet:\s+(.+)"),
           "sketch_size": re.compile(r"Target min-hashes per sketch:\s+(\d+)"),
           "sketches": re.compile(r"Sketches:\s+(\d+)")}


@dataclass
class MashParams:
    threads: int = 1

    def validate(self) -> None:
        if not 1 <= self.threads <= 256:
            raise ValueError("threads must be between 1 and 256")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_info_header(text: str) -> dict[str, Any]:
    """`mash info -H`: hash function and seed, k-mer size, alphabet, sketch size and number of sketches."""
    out: dict[str, Any] = {}
    for key, pattern in _HEADER.items():
        if m := pattern.search(text):
            if key == "seed":
                out["hash_function"], out["seed"] = m.group(1), int(m.group(2))
            else:
                out[key] = int(m.group(1)) if key != "alphabet" else m.group(1).strip()
    if "kmer" not in out or "sketch_size" not in out:
        raise ValueError("mash info -H did not state the k-mer size and sketch size")
    return out


def organism_from_comment(comment: str) -> str | None:
    """The organism in a sketch comment "[2 seqs] NC_000913.3 Escherichia coli str. K-12 …, complete genome [...]"
    (ARVA's reading: the words after the first sequence's accession, up to a comma)."""
    text = re.sub(r"^\[\d+ seqs?\]\s*", "", comment).replace("[...]", "").strip()
    words = text.split(None, 1)
    if len(words) < 2:
        return None
    return words[1].split(",")[0].strip()[:300] or None


def parse_info_table(text: str) -> dict[str, dict[str, Any]]:
    """`mash info -t`: ID → length and comment."""
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            raise ValueError("a mash info -t line has fewer than 3 columns")
        comment = cols[3] if len(cols) > 3 else ""
        out[cols[2]] = {"hashes": int(cols[0]), "length": int(cols[1]), "comment": comment,
                        "organism": organism_from_comment(comment)}
    return out


def parse_dist(text: str) -> list[dict[str, Any]]:
    """mash dist: one line per reference with the distance, p-value and shared hashes ("931/1000")."""
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 5 or not re.fullmatch(r"\d+/\d+", cols[4]):
            raise ValueError(f"mash dist line {n} is not reference, query, distance, p-value, shared-hashes")
        shared, total = (int(x) for x in cols[4].split("/"))
        try:
            distance, p = float(cols[2]), float(cols[3])
        except ValueError:
            raise ValueError(f"mash dist line {n} has a value that is not a number") from None
        acc = _ACCESSION.search(cols[0])
        rows.append({"reference": cols[0], "query": cols[1], "distance": distance, "p_value": p, "shared": shared,
                     "hashes": total, "accession": acc.group(0) if acc else None})
    return rows


class MashAdapter(ToolAdapter):
    info = ToolInfo(
        id="mash",
        name="Mash",
        description="MinHash distance estimates between a genome and a sketch file such as the RefSeq sketches "
        "(a fast screen; the distance is not an ANI value).",
        homepage="https://github.com/marbl/Mash",
        license="BSD-3-Clause",
        citation="Ondov B.D. et al. Mash: fast genome and metagenome distance estimation using MinHash. Genome Biol "
        "2016;17:132.",
        citation_url="https://doi.org/10.1186/s13059-016-0997-x",
        executable="mash",
        categories=("species",),
        input_formats=("fasta", "msh"),
        output_formats=("tsv",),
        min_version="2.3",
        tested_versions=("2.3",),
        install={"conda_lock": "python3 scripts/conda_locks.py install mash ~/.arva-tools/conda/mash  # then "
                               "ARVA_TOOL_MASH=~/.arva-tools/conda/mash/bin/mash"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"^(\d+\.\d+(?:\.\d+)?)\s*$", re.M)

    @staticmethod
    def help_text(executable: str) -> str:
        # mash dist -h exits with status 0 and prints to stdout.
        return read_help(executable, ("dist", "-h"))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(MashAdapter.help_text(executable))

    @staticmethod
    def info_argv(executable: str, sketch: Path, table: bool) -> list[str]:
        return [executable, "info", "-t" if table else "-H", str(sketch)]

    @staticmethod
    def argv(executable: str, params: MashParams, query: Path, sketch: Path, supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this Mash version does not offer {', '.join(missing)} (not in its dist -h)")
        return [executable, "dist", "-p", str(params.threads), str(sketch), str(query)]
