"""spaTyper — spa typing of Staphylococcus aureus assemblies from the repeats of the spa gene's X region, with the
Ridom SpaServer's repeat and type files.

Verified against spaTyper 0.3.3 (Bioconda spatyper-0.3.3-pyhdfd78af_3, ARVA's lock docker/conda-locks/spatyper/) from
`spaTyper --help`, its source (bin/spaTyper, spaTyper/spa_typing.py, utils.py, enricher.py) and real runs
(tests/fixtures/spatyper):

* `spaTyper -r sparepeats.fasta -o spatypes.txt -f <fasta> --output <file>`. Without -r or -o it falls back to
  copies next to its script or downloads them from spa.ridom.de; ARVA always passes the files the user downloaded and
  registered, and the copies the Bioconda package bundles are deleted at installation
  (docker/conda-locks/spatyper/remove-after-install.txt).
* --help says "Version: 0.3.3" (the package's version); --version prints "spaTyper 0.2.1" (a string left in the
  script). ARVA reads the version from --help.
* Without -e (the default, which ARVA keeps) every sequence of the file is scanned on both strands for exact matches
  to the repeats; matches that are not adjacent are joined by "xx". --output gets "Sequence name\tRepeats\tType", one
  row per sequence with at least one repeat: Repeats is the repeat succession (Ridom repeat numbers joined by "-"),
  Type the spa type of spatypes.txt with exactly that succession, or the succession itself when none has it. With
  -e (PCR enrichment with the spa primers) results go to standard output only and a file with more than one amplicon
  stops on an undefined name in enricher.py, so ARVA does not offer it.
* Query sequences are compared as they are written (the repeats are upper-cased, the query is not): ARVA stages the
  contigs in upper case.
* The help names the licence GPLv3; the package's metadata classifier and Bioconda say LGPL-3.0.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

OUTPUT = "spatyper.tsv"
LOG = "spatyper.stdout.log"
COLUMNS = ("Sequence name", "Repeats", "Type")
RIDOM_FILES = ("sparepeats.fasta", "spatypes.txt")
_TYPE = re.compile(r"^t\d+$")
_REPEAT = re.compile(r"^(\d+|xx)$")


@dataclass
class SpaParams:
    do_enrich: bool = False
    threads: int = 1

    def validate(self) -> None:
        if self.do_enrich:
            raise ValueError("PCR enrichment (-e) is not offered: spaTyper 0.3.3 prints its results to standard "
                             "output only")

    def as_dict(self) -> dict[str, Any]:
        return {"do_enrich": self.do_enrich}


def flags(_params: SpaParams | None = None) -> list[str]:
    return ["--repeat_file", "--repeat_order_file", "--fasta", "--output"]


def env_for(executable: str) -> dict[str, str]:
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def ridom_files(folder: Path) -> dict[str, Path]:
    return {name: folder / name for name in RIDOM_FILES}


def file_checksums(folder: Path) -> dict[str, str]:
    return {name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in ridom_files(folder).items()}


def count_entries(folder: Path) -> dict[str, int]:
    files = ridom_files(folder)
    repeats = sum(1 for ln in files["sparepeats.fasta"].read_text(errors="replace").splitlines() if ln.startswith(">"))
    types = sum(1 for ln in files["spatypes.txt"].read_text(errors="replace").splitlines() if "," in ln)
    return {"repeats": repeats, "types": types}


def parse_output(text: str) -> list[dict[str, Any]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("spaTyper's output file is empty (no header)")
    rows = list(csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE))
    if tuple(rows[0]) != COLUMNS:
        raise ValueError(f"spaTyper's output has other columns than spaTyper 0.3.3 writes: {', '.join(rows[0])}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if len(cols) != 3:
            raise ValueError(f"row {n} of spaTyper's output has {len(cols)} fields instead of 3")
        contig, repeats, spa_type = cols
        parts = repeats.split("-")
        if not all(_REPEAT.match(p) for p in parts):
            raise ValueError(f"row {n}: {repeats!r} is not a repeat succession")
        known = bool(_TYPE.match(spa_type))
        if not known and spa_type != repeats:
            raise ValueError(f"row {n}: the type {spa_type!r} is neither a spa type nor the repeat succession")
        out.append({"contig": contig, "repeats": repeats, "repeat_count": len([p for p in parts if p != "xx"]),
                    "type": spa_type if known else None, "gap_or_unknown_repeat": "xx" in parts})
    return out


def interpret(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """ARVA's reading: typed (one contig, a known type), new_repeat_succession (one contig, all repeats known, no type
    with that succession), unknown_repeat (non-adjacent matches: a repeat not in the repeat file or a gap), multiple
    (repeats on several contigs) or not_found."""
    if not rows:
        return {"status": "not_found", "call": None, "repeats": None}
    if len(rows) > 1:
        return {"status": "multiple", "call": None, "repeats": None}
    r = rows[0]
    if r["gap_or_unknown_repeat"]:
        return {"status": "unknown_repeat", "call": None, "repeats": r["repeats"]}
    if r["type"] is None:
        return {"status": "new_repeat_succession", "call": None, "repeats": r["repeats"]}
    return {"status": "typed", "call": r["type"], "repeats": r["repeats"]}


class SpatyperAdapter(ToolAdapter):
    info = ToolInfo(
        id="spatyper",
        name="spaTyper",
        description="spa typing of Staphylococcus aureus assemblies: the repeat succession of the spa X region and "
        "its spa type, with the Ridom SpaServer files you download and register.",
        homepage="https://github.com/JFsanchezherrero/spa_typing",
        license="LGPL-3.0 (Bioconda and the package classifier; its help says GPLv3)",
        citation="Sanchez-Herrero JF, Sullivan M. spaTyper 0.3.3 (Zenodo, doi:10.5281/zenodo.4063625; the DOI its "
        "package metadata gives); spa types: Harmsen D. et al. (2003) J Clin Microbiol 41(12):5442-5448.",
        citation_url="https://doi.org/10.5281/zenodo.4063625",
        executable="spaTyper",
        categories=("typing",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="0.3.3",
        tested_versions=("0.3.3",),
        install={"conda_lock": "python3 scripts/conda_locks.py install spatyper ~/.arva-tools/conda/spatyper  # then "
                               "ARVA_TOOL_SPATYPER=~/.arva-tools/conda/spatyper/bin/spaTyper"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_args = ("--help",)
    version_pattern = re.compile(r"Version: (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(SpatyperAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: SpaParams, contigs: Path, ridom: Path, out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this spaTyper version does not offer {', '.join(missing)} (not in its --help)")
        files = ridom_files(ridom)
        return [executable, "--repeat_file", str(files["sparepeats.fasta"]), "--repeat_order_file",
                str(files["spatypes.txt"]), "--fasta", str(contigs), "--output", str(out_dir / OUTPUT)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        for pattern in (r"FASTA contains multiple entries with the same name", r"\w+Error: .*"):
            if m := re.search(pattern, log):
                return f"spaTyper stopped: {m.group(0)}"
        return None
