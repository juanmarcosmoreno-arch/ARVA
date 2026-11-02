"""MUMmer NUCmer and show-coords — whole-genome nucleotide alignment of two assemblies.

Verified against NUCmer 3.1 and show-coords of MUMmer 3.23 (Ubuntu package mummer 3.23+dfsg-8): `nucmer -h`,
`show-coords -h` (fixtures/comparative) and real runs on NCBI genomes (fixtures/comparative/README.md):

* `nucmer [options] <Reference> <Query>` writes <prefix>.delta (-p, default "out") in the working folder. Anchors:
  --mumreference ("default behavior": unique in the reference), --mum (unique in both) or --maxmatch (all matches,
  what dnadiff uses). Defaults: -b 200 (breaklen), -c 65 (mincluster), -g 90 (maxgap), -l 20 (minmatch). ARVA passes
  the anchor mode and the four values explicitly.
* nucmer is a Perl script that runs its programs through shell command strings built from its arguments, so ARVA
  runs it in a folder holding both files and passes only plain file names it chose itself.
* `show-coords -rclTH <delta>`: one tab-separated row per alignment, sorted by reference, no header: S1 E1 S2 E2
  (1-based, inclusive; S2 > E2 for an alignment to the query's reverse strand), LEN1 LEN2, % IDY, LENR LENQ, COVR
  COVQ, reference and query names. No filter is applied: every alignment nucmer kept is listed, repeats included.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
ANCHORS = ("mumreference", "mum", "maxmatch")
HELP_FLAGS = ("--mum", "--mumreference", "--maxmatch", "-b|breaklen", "-c|mincluster", "-g|maxgap", "-l|minmatch",
              "-p|prefix")
DEFAULTS = {"anchors": "mumreference", "breaklen": 200, "mincluster": 65, "maxgap": 90, "minmatch": 20}


@dataclass
class NucmerParams:
    anchors: str = "mumreference"
    breaklen: int = 200
    mincluster: int = 65
    maxgap: int = 90
    minmatch: int = 20

    def validate(self) -> None:
        errors = []
        if self.anchors not in ANCHORS:
            errors.append(f"anchors must be one of {', '.join(ANCHORS)}")
        for name in ("breaklen", "mincluster", "maxgap", "minmatch"):
            if not 1 <= getattr(self, name) <= 100_000:
                errors.append(f"{name} must be between 1 and 100000")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def missing_help_flags(text: str) -> list[str]:
    return [f for f in HELP_FLAGS if f not in text]


def show_coords_path(nucmer: str) -> str | None:
    """show-coords from the same MUMmer installation as nucmer."""
    sibling = Path(nucmer).with_name("show-coords")
    return str(sibling) if sibling.is_file() else shutil.which("show-coords")


def parse_coords(text: str) -> list[dict[str, Any]]:
    """show-coords -rclTH rows as alignment blocks (1-based, inclusive; strand from the query's direction)."""
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        f = line.split("\t")
        if len(f) != 13:
            raise ValueError(f"show-coords line {n} has {len(f)} columns instead of 13 (show-coords -rclTH)")
        try:
            s1, e1, s2, e2, len1, _len2 = (int(x) for x in f[:6])
            idy = float(f[6])
            lenr, lenq = int(f[7]), int(f[8])
        except ValueError:
            raise ValueError(f"show-coords line {n} has a value that is not a number") from None
        if not (0 < s1 <= e1 <= lenr and 0 < min(s2, e2) and max(s2, e2) <= lenq and 0 <= idy <= 100):
            raise ValueError(f"show-coords line {n} has values out of range")
        rows.append({"ref": f[11], "ref_length": lenr, "ref_start": s1, "ref_end": e1, "query": f[12],
                     "query_length": lenq, "query_start": min(s2, e2), "query_end": max(s2, e2),
                     "strand": "+" if s2 <= e2 else "-", "identity": idy, "length": len1, "primary": True})
    return rows


class NucmerAdapter(ToolAdapter):
    info = ToolInfo(
        id="nucmer",
        name="MUMmer NUCmer",
        description="Aligns two whole genomes (maximal unique matches extended into alignments); ARVA uses it with "
        "show-coords for dot plots, synteny and conservation in comparative genomics.",
        homepage="https://mummer.sourceforge.net",
        license="Artistic-1.0",
        citation="Kurtz S, Phillippy A, Delcher AL, et al. Versatile and open software for comparing large genomes. "
        "Genome Biol 2004;5(2):R12.",
        citation_url="https://doi.org/10.1186/gb-2004-5-2-r12",
        executable="nucmer",
        categories=("comparative genomics", "alignment"),
        input_formats=("fasta",),
        output_formats=("delta", "coords"),
        min_version="3.1",
        tested_versions=("3.1",),
        install={"apt": "mummer", "conda": "bioconda::mummer"},
    )
    # `nucmer --version` prints "NUCmer (NUCleotide MUMmer) version 3.1".
    version_pattern = re.compile(r"NUCmer \(NUCleotide MUMmer\) version (\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("-h",))

    @staticmethod
    def argv(executable: str, params: NucmerParams, prefix: str, reference: str, query: str) -> list[str]:
        params.validate()
        for name in (prefix, reference, query):
            if not _SAFE.fullmatch(name):
                raise ValueError(f"nucmer builds shell commands from its arguments; unsafe name: {name!r}")
        return [executable, f"--{params.anchors}", "-b", str(params.breaklen), "-c", str(params.mincluster),
                "-g", str(params.maxgap), "-l", str(params.minmatch), "-p", prefix, reference, query]

    @staticmethod
    def coords_argv(show_coords: str, delta: str) -> list[str]:
        if not _SAFE.fullmatch(delta):
            raise ValueError(f"unsafe delta file name: {delta!r}")
        return [show_coords, "-rclTH", delta]
