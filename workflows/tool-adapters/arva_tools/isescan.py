"""ISEScan — insertion sequence (IS) elements in assembled contigs, complete and partial, with profile HMMs of IS
transposases (bundled in its package), FragGeneScan and HMMER, and terminal inverted repeat (TIR) detection.

Written from ISEScan 1.7.3's source (isescan.py, isPredict.py, pred.py outputIS4multipleSeqOneFile, tools.py of
xiezhq/ISEScan, version string 1.7.3) and ARVA's lock (docker/conda-locks/isescan/, linux-64 only); NOT VALIDATED
HERE: its environment (342 MB to download, about 0.9 GB unpacked) did not fit the test machine's disk next to
MOB-suite's database, so the parser is tested on a constructed file in that format (tests/fixtures/isescan,
labelled CONSTRUCTED). MOB-suite's own repetitive-element search (mge.report.txt) reports known IS elements and is
validated.

* `isescan.py --seqfile <FASTA> --output <folder> --nthread <n>`; --removeShortIS drops partial IS elements (length
  < 400 bp, or a single copy without a perfect TIR); --no-FragGeneScan (experimental) reads GenBank proteins instead.
  Defaults (isescan.py argparse): --nthread 1, --removeShortIS off, FragGeneScan on.
* Outputs (pred.py): <output>/<input folder name>/<input file name>.tsv (and .csv, .raw, .sum, .gff, .is.fna,
  .orf.fna, .orf.faa); the .tsv columns are seqID, family, cluster, isBegin, isEnd, isLen, ncopy4is, start1, end1,
  start2, end2, score, irId, irLen, nGaps, orfBegin, orfEnd, strand, orfLen, E-value, E-value4copy, type, ov, tir;
  type is c (complete) or p (partial); start1..end2 are the TIR's two arms (0 when no TIR was found).
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

DEFAULTS = {"nthread": "1"}
INPUT_FOLDER = "input"
INPUT = "contigs.fna"
OUTDIR = "isescan"
LOG = "isescan.stderr.log"
COLUMNS = ("seqID", "family", "cluster", "isBegin", "isEnd", "isLen", "ncopy4is", "start1", "end1", "start2", "end2",
           "score", "irId", "irLen", "nGaps", "orfBegin", "orfEnd", "strand", "orfLen", "E-value", "E-value4copy",
           "type", "ov", "tir")
_INTS = ("isBegin", "isEnd", "isLen", "ncopy4is", "start1", "end1", "start2", "end2", "score", "irId", "irLen",
         "nGaps", "orfBegin", "orfEnd", "orfLen", "ov")
_FLOATS = ("E-value", "E-value4copy")
TYPES = {"c": "complete", "p": "partial"}


@dataclass
class IsescanParams:
    remove_short_is: bool = False
    threads: int = 4

    def validate(self) -> None:
        if not 1 <= self.threads <= 256:
            raise ValueError("threads must be between 1 and 256")

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fraggenescan": True}


def flags(params: IsescanParams) -> list[str]:
    return ["--seqfile", "--output", "--nthread", *(["--removeShortIS"] if params.remove_short_is else [])]


def env_for(executable: str) -> dict[str, str]:
    """PATH with the environment's bin/ first (ISEScan runs FragGeneScan, hmmsearch, phmmer and blastn from PATH)."""
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def help_options(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"(?<![\w-])(--[A-Za-z][\w-]*)", text))


def tsv_path(out_dir: Path) -> Path:
    return out_dir / OUTDIR / INPUT_FOLDER / f"{INPUT}.tsv"


def _value(key: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return None
    if key in _INTS:
        return int(float(raw))
    if key in _FLOATS:
        return float(raw)
    return raw


def parse_tsv(text: str) -> list[dict[str, Any]]:
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        return []
    if tuple(c.strip() for c in rows[0]) != COLUMNS:
        raise ValueError(f"ISEScan's .tsv has other columns than ISEScan 1.7.3 writes: {', '.join(rows[0])}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if not cols:
            continue
        if len(cols) != len(COLUMNS):
            raise ValueError(f"line {n} of ISEScan's .tsv has {len(cols)} fields instead of {len(COLUMNS)}")
        try:
            r = {k: _value(k, v) for k, v in zip(COLUMNS, cols, strict=True)}
        except ValueError as exc:
            raise ValueError(f"line {n} of ISEScan's .tsv: {exc}") from None
        r["completeness"] = TYPES.get(r["type"] or "", "unknown")
        r["has_tir"] = bool(r["irLen"])
        out.append(r)
    return out


class IsescanAdapter(ToolAdapter):
    info = ToolInfo(
        id="isescan",
        name="ISEScan",
        description="Insertion sequence elements in assembled contigs, complete and partial, with transposase profile "
        "HMMs and terminal inverted repeats.",
        homepage="https://github.com/xiezhq/ISEScan",
        license="GPL-3.0",
        citation="Xie Z, Tang H. ISEScan: automated identification of insertion sequence elements in prokaryotic "
        "genomes. Bioinformatics 2017;33(21):3340-3347.",
        citation_url="https://doi.org/10.1093/bioinformatics/btx433",
        executable="isescan.py",
        categories=("mobile_element",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="1.7.3",
        tested_versions=(),
        install={"conda_lock": "python3 scripts/conda_locks.py install isescan ~/.arva-tools/conda/isescan"
                               "  # then ARVA_TOOL_ISESCAN=~/.arva-tools/conda/isescan/bin/isescan.py"},
        conda_platforms=("linux-64",),
    )
    version_pattern = re.compile(r"isescan (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(IsescanAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: IsescanParams, contigs: Path, out_dir: Path, supported: frozenset[str]) -> list[str]:
        params.validate()
        if contigs.parent.name != INPUT_FOLDER or contigs.name != INPUT:
            raise ValueError(f"ISEScan names its outputs after the input's folder and file: stage it as "
                             f"{INPUT_FOLDER}/{INPUT}")
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this ISEScan version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, "--seqfile", str(contigs), "--output", str(out_dir / OUTDIR), "--nthread", str(params.threads)]
        return a + (["--removeShortIS"] if params.remove_short_is else [])

    @staticmethod
    def failure_reason(log: str) -> str | None:
        lines = [ln.strip() for ln in log.splitlines() if "Error" in ln or "error" in ln]
        return f"ISEScan stopped: {lines[-1]}" if lines else None
