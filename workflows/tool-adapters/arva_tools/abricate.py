"""ABRicate — Torsten Seemann's nucleotide BLAST screen of assembled contigs against the gene databases it bundles.

Verified against ABRicate 1.4.0 (Bioconda abricate-1.4.0-h05cac1d_0, ARVA's lock docker/conda-locks/abricate/) from
its `--help`, its source (bin/abricate, bin/abricate-get_db), the README and real runs (tests/fixtures/abricate):

* `bin/abricate` starts with `#!/usr/bin/env perl` and calls blastn, blastdbcmd and any2fasta from PATH, so the
  environment's bin/ must come first in PATH.
* Databases are folders <datadir>/<name>/ with a FASTA file `sequences` and its BLAST index (default datadir
  <RealBin>/../db). ARVA uses two of the bundled ones: `vfdb` (VFDB's core set A nucleotides,
  VFDB_setA_nt.fas.gz, per abricate-get_db) and `plasmidfinder` (the plasmidfinder_db repository of the Center for
  Genomic Epidemiology, per abricate-get_db). `abricate --list` prints DATABASE, SEQUENCES, DBTYPE and DATE, where
  DATE is the BLAST index's own date (`blastdbcmd -info`), i.e. when the package indexed the files, not a release
  date of VFDB or PlasmidFinder; the files record no such release or commit. ARVA never runs abricate-get_db or
  --setupdb (they fetch the latest data, unpinned).
* Defaults (--help): --minid 80, --mincov 80, --threads 1, --db ncbi. ARVA passes --datadir, --db, --minid,
  --mincov and --threads explicitly, and --nopath.
* Search: `blastn -task blastn -dust no -perc_identity <minid> -evalue 1E-20 -culling_limit 1 -max_target_seqs
  10000` (nucleotide databases); %COVERAGE = 100 x (alignment length - gaps) / reference length, and a hit is kept
  when it reaches --mincov. A gene in two pieces (split across contigs, or interrupted) appears as two partial rows.
* Report (tab-separated, on standard output): #FILE SEQUENCE START END STRAND GENE COVERAGE COVERAGE_MAP GAPS
  %COVERAGE %IDENTITY DATABASE ACCESSION PRODUCT RESISTANCE. COVERAGE is <ref start>-<ref end>/<ref length>;
  COVERAGE_MAP draws the covered part of the reference in 15 characters ('=' covered, '.' not); GAPS is <gap
  openings>/<gap positions>. Sequence names are <db>~~~<gene>~~~<accession>~~~<resistance>; VFDB's product reads
  "(<gene>) <description> [<VF name> (<VF id>) - <VF category> (<VFC id>)] [<organism>]".

ABRicate reports sequence similarity only: a virulence gene found is not evidence of virulence, and a replicon found
does not by itself place a contig on a plasmid.
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

DATABASES = ("vfdb", "plasmidfinder")
DEFAULTS = {"minid": "80", "mincov": "80", "threads": "1", "db": "ncbi"}
OUTPUTS = {"report": "abricate.tsv", "log": "abricate.stderr.log"}
COLUMNS = {
    "#FILE": "file", "SEQUENCE": "contig", "START": "start", "END": "end", "STRAND": "strand", "GENE": "gene",
    "COVERAGE": "coverage_range", "COVERAGE_MAP": "coverage_map", "GAPS": "gaps", "%COVERAGE": "coverage",
    "%IDENTITY": "identity", "DATABASE": "database", "ACCESSION": "accession", "PRODUCT": "product",
    "RESISTANCE": "resistance",
}
# A partial hit whose alignment ends this close to a contig end may continue on another contig (ARVA's reading of
# the coordinates; ABRicate does not say).
CONTIG_END_BP = 10
_DEFAULT = re.compile(r"^\s+--(\w+)\s.*\[([^\]]*)\]\.?\s*$")
_RANGE = re.compile(r"(\d+)-(\d+)/(\d+)")
_GAPS = re.compile(r"(\d+)/(\d+)")
_VF = re.compile(r"^\((?P<gene>[^)]*)\)\s*(?P<description>.*?)\s*\[(?P<vf_name>.+) \((?P<vf_id>VF\d+)\) - "
                 r"(?P<vf_category>.+) \((?P<vfc_id>VFC\d+)\)\]\s*\[(?P<organism>[^\]]*)\]\s*$")
_REPLICON = re.compile(r"^(.+?)_\d+[a-z]?(?:_|$)")
_USING = re.compile(r"Using (\w+) database (\S+):\s+(\d+) sequences -\s+(\S+)")
_FOUND = re.compile(r"Found (\d+) genes in")
_ERROR = re.compile(r"^ERROR: (.*)$", re.M)
_PERL_VARIABLES = {"PERL5LIB": "", "PERLLIB": "", "PERL5OPT": ""}


@dataclass
class AbricateParams:
    database: str = "vfdb"
    minid: float = 80.0
    mincov: float = 80.0
    threads: int = 4

    def validate(self) -> None:
        errors = []
        if self.database not in DATABASES:
            errors.append(f"database must be one of {', '.join(DATABASES)}")
        if not 0 < self.minid <= 100:
            errors.append("minid must be a percentage greater than 0 and at most 100")
        if not 0 <= self.mincov <= 100:
            errors.append("mincov must be a percentage from 0 to 100")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def flags(_params: AbricateParams) -> list[str]:
    return ["--datadir", "--db", "--minid", "--mincov", "--threads", "--nopath"]


def help_defaults(text: str) -> dict[str, str]:
    """The [default] --help prints after each option ARVA passes."""
    return {m.group(1): m.group(2) for line in text.splitlines() if (m := _DEFAULT.match(line))
            and m.group(1) in DEFAULTS}


def env_for(executable: str) -> dict[str, str]:
    """PATH with the environment's bin/ first (bin/abricate runs `env perl`, blastn, blastdbcmd and any2fasta from
    PATH) and no Perl settings from the user's shell."""
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}",
            **_PERL_VARIABLES}


def datadir(executable: str) -> Path:
    """The databases the package installed: <prefix>/db (bin/abricate's default, $FindBin::RealBin/../db)."""
    return Path(os.path.realpath(executable)).parent.parent / "db"


def database_info(folder: Path) -> dict[str, Any]:
    """One bundled database: its sequence file, the BLAST index files and what the index's .njs states."""
    seq = folder / "sequences"
    njs = folder / "sequences.njs"
    meta: dict[str, Any] = {}
    if njs.is_file():
        try:
            meta = json.loads(njs.read_text())
        except (OSError, ValueError):
            meta = {}
    index = [n for n in meta.get("files") or [] if (folder / n).is_file()]
    return {"name": folder.name, "sequences_file": seq.is_file(), "index_files": index,
            "ready": seq.is_file() and bool(index) and len(index) == len(meta.get("files") or []),
            "sequences": meta.get("number-of-sequences"), "letters": meta.get("number-of-letters"),
            "indexed": meta.get("last-updated"), "description": meta.get("description"),
            "dbtype": meta.get("dbtype")}


def parse_list(text: str) -> list[dict[str, Any]]:
    """`abricate --list`: DATABASE SEQUENCES DBTYPE DATE."""
    out = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) == 4 and cols[0] != "DATABASE" and cols[1].isdigit():
            out.append({"name": cols[0], "sequences": int(cols[1]), "dbtype": cols[2], "date": cols[3]})
    return out


def replicon_type(gene: str) -> str:
    """PlasmidFinder's replicon family from its allele name: the text before the first _<number>
    (Col(BS512)_1 -> Col(BS512), IncFIB(K)_1_Kpn3 -> IncFIB(K), rep22_1b_repB(pAMalpha1) -> rep22)."""
    m = _REPLICON.match(gene)
    return m.group(1) if m else gene


def parse_vfdb_product(product: str) -> dict[str, str | None]:
    m = _VF.match(product or "")
    if not m:
        return {"description": product or None, "vf_name": None, "vf_id": None, "vf_category": None,
                "vfc_id": None, "organism": None}
    return {k: (v or None) for k, v in m.groupdict().items() if k != "gene"}


def _int(text: str, line: int, column: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"line {line} of the ABRicate report: {column} is not a number ({text!r})") from None


def parse_report(text: str) -> list[dict[str, Any]]:
    """The rows of an ABRicate report with ARVA's names, numbers parsed and the reference range split out."""
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        raise ValueError("the ABRicate report is empty (no header)")
    header = rows[0]
    if header != list(COLUMNS):
        raise ValueError(f"the ABRicate report's columns are not the ones ABRicate 1.4.0 writes: {', '.join(header)}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if not cols:
            continue
        if len(cols) != len(header):
            raise ValueError(f"line {n} of the ABRicate report has {len(cols)} fields instead of {len(header)}")
        r: dict[str, Any] = {COLUMNS[h]: v for h, v in zip(header, cols, strict=True)}
        rng, gaps = _RANGE.fullmatch(r["coverage_range"]), _GAPS.fullmatch(r["gaps"])
        if not rng or not gaps:
            raise ValueError(f"line {n} of the ABRicate report: COVERAGE or GAPS is not in ABRicate's format")
        try:
            coverage, identity = float(r["coverage"]), float(r["identity"])
        except ValueError:
            raise ValueError(f"line {n} of the ABRicate report: %COVERAGE or %IDENTITY is not a number") from None
        r.update(start=_int(r["start"], n, "START"), end=_int(r["end"], n, "END"), coverage=coverage,
                 identity=identity, ref_start=int(rng.group(1)), ref_end=int(rng.group(2)),
                 ref_length=int(rng.group(3)), gap_openings=int(gaps.group(1)), gap_positions=int(gaps.group(2)),
                 resistance=r["resistance"] or None, accession=r["accession"] or None)
        out.append(r)
    return out


def classify(rows: list[dict[str, Any]], contig_lengths: dict[str, int]) -> list[dict[str, Any]]:
    """Each hit with ARVA's reading of its coordinates: complete (the whole reference, without gaps), complete
    with gaps, partial, or partial at a contig end; and the number of pieces when the same reference is found
    more than once in partial hits (a gene split across contigs or interrupted)."""
    pieces: dict[tuple[str, str], int] = {}
    for r in rows:
        if r["ref_start"] != 1 or r["ref_end"] != r["ref_length"]:
            key = (r["database"], f"{r['gene']}~{r['accession']}")
            pieces[key] = pieces.get(key, 0) + 1
    out = []
    for r in rows:
        whole = r["ref_start"] == 1 and r["ref_end"] == r["ref_length"]
        length = contig_lengths.get(r["contig"])
        at_end = length is not None and (min(r["start"], r["end"]) <= CONTIG_END_BP
                                         or max(r["start"], r["end"]) > length - CONTIG_END_BP)
        kind = ("complete" if r["gap_positions"] == 0 else "complete_gaps") if whole else \
            ("contig_end" if at_end else "partial")
        n = 0 if whole else pieces[(r["database"], f"{r['gene']}~{r['accession']}")]
        out.append({**r, "hit_kind": kind, "pieces": n if n > 1 else None})
    return out


def parse_stderr(text: str) -> dict[str, Any]:
    using, found = _USING.search(text), _FOUND.search(text)
    return {"dbtype": using.group(1) if using else None, "database": using.group(2) if using else None,
            "sequences": int(using.group(3)) if using else None, "date": using.group(4) if using else None,
            "found": int(found.group(1)) if found else None,
            "errors": [m.group(1).strip() for m in _ERROR.finditer(text)]}


def warnings(params: AbricateParams, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ARVA's coded warnings about one run (the interface translates them)."""
    out: list[dict[str, Any]] = [{"code": f"{params.database}_meaning", "params": {}}]
    by: dict[str, list[str]] = {}
    for r in rows:
        by.setdefault(r["hit_kind"], []).append(r["gene"])
    for kind in ("partial", "contig_end", "complete_gaps"):
        if genes := by.get(kind):
            out.append({"code": f"hits_{kind}", "params": {"count": len(genes), "genes": ", ".join(sorted(set(genes)))}})
    if split := sorted({r["gene"] for r in rows if r["pieces"]}):
        out.append({"code": "hits_split", "params": {"count": len(split), "genes": ", ".join(split)}})
    if params.minid < 80 or params.mincov < 80:
        out.append({"code": "low_thresholds", "params": {"minid": f"{params.minid:g}", "mincov": f"{params.mincov:g}"}})
    return out


class AbricateAdapter(ToolAdapter):
    info = ToolInfo(
        id="abricate",
        name="ABRicate",
        description="Nucleotide BLAST screen of assembled contigs against the databases ABRicate bundles; ARVA uses "
        "its VFDB (virulence factors) and PlasmidFinder (plasmid replicons) databases.",
        homepage="https://github.com/tseemann/abricate",
        license="GPL-2.0",
        citation="Seemann T. ABRicate. https://github.com/tseemann/abricate (software, unpublished). Cite the database "
        "too: VFDB (Liu B. et al. 2022, Nucleic Acids Res 50:D912) or PlasmidFinder (Carattoli A. et al. 2014, "
        "Antimicrob Agents Chemother 58:3895).",
        citation_url="https://github.com/tseemann/abricate",
        executable="abricate",
        categories=("virulence", "plasmid"),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="1.4.0",
        tested_versions=("1.4.0",),
        install={"conda_lock": "python3 scripts/conda_locks.py install abricate ~/.arva-tools/conda/abricate"
                               "  # then ARVA_TOOL_ABRICATE=~/.arva-tools/conda/abricate/bin/abricate"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"abricate (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(AbricateAdapter.help_text(executable))

    @staticmethod
    def list_text(executable: str) -> str:
        return read_help(executable, ("--list",), env_for(executable))

    @staticmethod
    def argv(executable: str, params: AbricateParams, contigs: Path, db_root: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this ABRicate version does not offer {', '.join(missing)} (not in its --help)")
        return [executable, "--datadir", str(db_root), "--db", params.database, "--minid", f"{params.minid:g}",
                "--mincov", f"{params.mincov:g}", "--threads", str(params.threads), "--nopath", str(contigs)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        errors = parse_stderr(log)["errors"]
        return f"ABRicate stopped: {errors[-1]}" if errors else None
