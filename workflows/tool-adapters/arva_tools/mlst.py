"""mlst — Torsten Seemann's MLST caller: BLAST of the contigs against the PubMLST typing schemes it bundles.

Verified against mlst 2.35.0 (Bioconda mlst-2.35.0-hdfd78af_1, ARVA's lock docker/conda-locks/mlst/) from its
`--help`, its README and its source (bin/mlst, perl5/MLST/Scheme.pm), and real runs (tests/fixtures/mlst):

* `bin/mlst` starts with `#!/usr/bin/env perl` and calls blastn and any2fasta from PATH, so the environment's bin/
  must come first in PATH. It reads MLST_DBDIR (default <RealBin>/../db) and stops if that folder does not exist;
  ARVA sets it to the bundled database and also passes --blastdb and --datadir.
* Defaults (--help): --minid 95, --mincov 50, --minscore 50, --threads 1, --exclude
  ecoli,abaumannii,vcholerae_2,senterica_achtman_2. With --scheme, mlst sets the minimum score to 0 and ignores
  --exclude; ARVA passes --minscore 0 then and no --exclude, so the recorded options are the ones applied.
* mlst runs `blastn -ungapped -dust no -word_size 32 -perc_identity <minid> -evalue 1E-20`; a hit counts when
  identical bases / allele length >= mincov. Full length and 100 % identity: exact `n`; full length otherwise:
  `~n`; shorter: `n?`; nothing: `-`; several exact alleles: `n,m`. The n of `~n` and `n?` is the first such allele
  in BLAST's output, not necessarily the closest. For an ST whose profile lacks a locus, mlst writes `0`.
* Scores: 90 points shared by the loci (exact 1, novel 0.7, partial 0.5, missing 0 each), +10 when the
  combination is a known ST. Best score wins; ties are broken by Perl's hash order and only reported as
  `WARNING: <scheme>(<ST>)==<scheme>(<ST>) score=<n> <file>` on standard error.
* --full: FILE SCHEME ST STATUS SCORE ALLELES (`locus(call);…`); STATUS is PERFECT, NOVEL, NONE, MIXED, MISSING,
  BAD or OK (the README marks MISSING, BAD and OK as unstable). No scheme: SCHEME and ST `-`, STATUS NONE.
* Scheme files: pubmlst/<scheme>/<scheme>.txt (ST and one column per locus; mlst ignores the columns mlst_clade,
  clonal_complex, species, CC and Lineage), <locus>.tfa and <scheme>_info.json (download_date, last_updated,
  source, API, authenticated). db/VERSION.txt holds a date; blast/mlst.fa.njs the index's build time.
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus, help_options, read_help

DEFAULT_EXCLUDE = ("ecoli", "abaumannii", "vcholerae_2", "senterica_achtman_2")
DEFAULTS = {"minid": "95", "mincov": "50", "minscore": "50", "threads": "1", "exclude": ",".join(DEFAULT_EXCLUDE)}
OUTPUTS = {"tsv": "mlst.tsv", "json": "mlst.json", "novel": "novel_alleles.fasta", "log": "mlst.stderr.log"}
REQUIRED_OUTPUTS = ("tsv", "json")
SCHEME_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")
# Columns of a scheme's profile file that are not loci (MLST::Scheme); ARVA reads the clonal complex from them.
EXTRA_COLUMNS = ("mlst_clade", "clonal_complex", "species", "CC", "Lineage")
CC_COLUMNS = ("clonal_complex", "CC")
# PubMLST terms (pubmlst.org/terms-conditions, updated 2026-05-13): data submitted on or before this date may be
# redistributed with citation; data submitted from 1 January 2025 is restricted.
PUBMLST_OPEN_UNTIL = "2024-12-31"
# Perl reads these to find modules and options; a value from the user's shell would change which modules load.
_PERL_VARIABLES = {"PERL5LIB": "", "PERLLIB": "", "PERL5OPT": ""}

_ALLELE = re.compile(r"(.+)\(([^()]*)\)")
_NUMBER = r"\d+(?:\.\d+)?"
_TIE = re.compile(r"^WARNING: (\w+)\(([^)]*)\)==(\w+)\(([^)]*)\) score=(\d+) ")
_EXTRA_EXACT = re.compile(r"^WARNING: found additional exact allele match (\w+)\.(.+)-(" + _NUMBER + r")$")
_EXACT = re.compile(r"^Found exact allele match (\w+)\.(.+)-(" + _NUMBER + r")$")
_EXCLUDED = re.compile(r"^Excluding \d+ schemes: (.*)$")
_BLASTN = re.compile(r"^Running:\s+(blastn .*)$")
_NOVEL_COUNT = re.compile(r"^Found (\d+) novel alleles$")
_ERROR = re.compile(r"^ERRPR: (.*)$")
_DEFAULT = re.compile(r"^\s+--(\w+)\s.*\(default '([^']*)'\)\s*$")


@dataclass
class MlstParams:
    scheme: str | None = None
    minid: float = 95.0
    mincov: float = 50.0
    minscore: float = 50.0
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    threads: int = 1

    def validate(self) -> None:
        errors = []
        if self.scheme is not None and not SCHEME_NAME.fullmatch(self.scheme):
            errors.append("scheme must be a scheme name (letters, digits and _)")
        if bad := [s for s in self.exclude if not SCHEME_NAME.fullmatch(s)]:
            errors.append(f"exclude has names that are not scheme names: {', '.join(bad[:5])}")
        if len(set(self.exclude)) != len(self.exclude):
            errors.append("exclude lists a scheme twice")
        if self.scheme is not None and (self.minscore != 0 or self.exclude):
            errors.append("with a chosen scheme mlst uses minimum score 0 and no excluded schemes")
        if not 0 < self.minid <= 100:
            errors.append("minid must be greater than 0 and at most 100 (%)")
        if not 0 < self.mincov <= 100:
            errors.append("mincov must be greater than 0 and at most 100 (%)")
        if not 0 <= self.minscore <= 100:
            errors.append("minscore must be between 0 and 100")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def flags(params: MlstParams) -> list[str]:
    used = ["--full", "--outfile", "--json", "--novel", "--threads", "--minid", "--mincov", "--minscore", "--blastdb",
            "--datadir"]
    return used + (["--scheme"] if params.scheme else ["--exclude"])


def help_defaults(text: str) -> dict[str, str]:
    """The defaults --help prints ("  --minid NUM  … (default '95')"), for the options ARVA passes."""
    out = {}
    for line in text.splitlines():
        if (m := _DEFAULT.match(line)) and m.group(1) in DEFAULTS:
            out[m.group(1)] = m.group(2)
    return out


def database_dir(executable: str) -> Path:
    """The database mlst bundles: <folder of the real bin/mlst>/../db."""
    return Path(os.path.realpath(executable)).parent.parent / "db"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def profile_header(path: Path) -> list[str]:
    with open(path, errors="replace") as fh:
        return fh.readline().rstrip("\r\n").split("\t")


def database_info(db: Path) -> dict[str, Any]:
    """The bundled schemes as their own files describe them: loci, the profile file's extra columns, each scheme's
    info file (download date, last update, source), db/VERSION.txt and the BLAST index's build time."""
    pubmlst, njs = db / "pubmlst", db / "blast" / "mlst.fa.njs"
    schemes = []
    if pubmlst.is_dir():
        for folder in sorted(p for p in pubmlst.iterdir() if p.is_dir() and not p.name.startswith(".")):
            profile = folder / f"{folder.name}.txt"
            if not profile.is_file():
                continue
            header = profile_header(profile)
            info = _read_json(folder / f"{folder.name}_info.json")
            schemes.append({
                "name": folder.name, "loci": [c for c in header[1:] if c not in EXTRA_COLUMNS],
                "extra_columns": [c for c in header[1:] if c in EXTRA_COLUMNS],
                "download_date": info.get("download_date"), "last_updated": info.get("last_updated"),
                "source": info.get("source"), "api": info.get("API"), "authenticated": info.get("authenticated"),
            })
    blast = _read_json(njs)
    version_file = db / "VERSION.txt"
    downloads = sorted({s["download_date"] for s in schemes if s["download_date"]})
    dated = [s for s in schemes if s["last_updated"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["last_updated"])]
    blast_files = [db / "blast" / f for f in blast.get("files", [])]
    return {
        "path": str(db),
        "ready": bool(schemes) and njs.is_file() and bool(blast_files) and all(f.is_file() for f in blast_files),
        "schemes": schemes,
        "scheme_count": len(schemes),
        "version_txt": version_file.read_text(errors="replace").strip() if version_file.is_file() else None,
        "download_dates": downloads,
        "blast_last_updated": blast.get("last-updated"),
        "blast_files": [f"blast/{f}" for f in blast.get("files", [])],
        "blast_sequences": blast.get("number-of-sequences"),
        "sources": {src: sum(1 for s in schemes if s["source"] == src) for src in sorted({str(s["source"])
                                                                                        for s in schemes})},
        "authenticated": sorted({str(s["authenticated"]) for s in schemes}),
        "updated_after_open_terms": sorted(s["name"] for s in dated if s["last_updated"] > PUBMLST_OPEN_UNTIL),
        "without_update_date": sorted(s["name"] for s in schemes if s not in dated),
    }


def database_version(info: dict[str, Any]) -> str | None:
    """The date the schemes were downloaded, when every scheme's info file gives the same one."""
    dates = info["download_dates"]
    return dates[0] if len(dates) == 1 and all(s["download_date"] for s in info["schemes"]) else None


def clonal_complex(db: Path, scheme: str, st: str) -> dict[str, Any]:
    """The clonal complex the scheme's profile file gives for an ST: `available` False when the file has no
    clonal_complex or CC column, `value` None when the ST's row leaves it empty."""
    profile = db / "pubmlst" / scheme / f"{scheme}.txt"
    header = profile_header(profile)
    column = next((c for c in CC_COLUMNS if c in header), None)
    if column is None:
        return {"available": False, "column": None, "value": None}
    i = header.index(column)
    with open(profile, errors="replace") as fh:
        next(fh)
        for line in fh:
            cols = line.rstrip("\r\n").split("\t")
            if cols[0] == st:
                value = cols[i].strip() if i < len(cols) else ""
                return {"available": True, "column": column, "value": value or None}
    return {"available": True, "column": column, "value": None}


def parse_call(call: str) -> dict[str, Any]:
    """One allele call of mlst's notation, with its type."""
    if call == "-":
        return {"call": call, "type": "missing", "alleles": [], "similar_to": None}
    if call == "0":
        return {"call": call, "type": "null", "alleles": [], "similar_to": None}
    if re.fullmatch(_NUMBER, call):
        return {"call": call, "type": "exact", "alleles": [call], "similar_to": None}
    if m := re.fullmatch(r"~(" + _NUMBER + ")", call):
        return {"call": call, "type": "novel", "alleles": [], "similar_to": m.group(1)}
    if m := re.fullmatch("(" + _NUMBER + r")\?", call):
        return {"call": call, "type": "partial", "alleles": [], "similar_to": m.group(1)}
    if re.fullmatch(_NUMBER + "(?:," + _NUMBER + ")+", call):
        return {"call": call, "type": "multiple", "alleles": call.split(","), "similar_to": None}
    return {"call": call, "type": "unrecognised", "alleles": [], "similar_to": None}


def parse_full(text: str) -> list[dict[str, Any]]:
    """mlst --full: one row per input file."""
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quotechar='"'))
    if not rows or rows[0] != ["FILE", "SCHEME", "ST", "STATUS", "SCORE", "ALLELES"]:
        raise ValueError("mlst's --full output does not start with FILE SCHEME ST STATUS SCORE ALLELES")
    out = []
    for cols in rows[1:]:
        if not cols:
            continue
        if len(cols) != 6:
            raise ValueError(f"an mlst --full line has {len(cols)} columns instead of 6")
        alleles = []
        for part in filter(None, cols[5].split(";")):
            m = _ALLELE.fullmatch(part)
            if m is None:
                raise ValueError(f"unexpected allele entry {part[:60]!r}")
            alleles.append({"locus": m.group(1), **parse_call(m.group(2))})
        out.append({"file": cols[0], "scheme": None if cols[1] == "-" else cols[1],
                    "st": None if cols[2] == "-" else cols[2], "status": cols[3], "score": int(cols[4]),
                    "alleles": alleles})
    return out


def check_json(rows: list[dict[str, Any]], text: str) -> None:
    """mlst --json must say what --full says (scheme, ST and every call)."""
    data = json.loads(text)
    if not isinstance(data, list) or len(data) != len(rows):
        raise ValueError("mlst's JSON does not have one entry per input")
    for row, entry in zip(rows, data, strict=True):
        alleles = entry.get("alleles") or {}
        if (entry.get("scheme"), entry.get("sequence_type")) != (row["scheme"] or "-", row["st"] or "-") or \
                alleles != {a["locus"]: a["call"] for a in row["alleles"]}:
            raise ValueError(f"mlst's JSON and --full output disagree for {row['file']}")


def parse_stderr(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {"ties": [], "additional_exact": [], "exact_by_scheme": {}, "excluded": None,
                           "blastn": None, "novel_alleles": None, "errors": [], "minscore_forced": False}
    for line in text.splitlines():
        line = line.rstrip()
        if m := _TIE.match(line):
            out["ties"].append({"scheme": m.group(1), "st": m.group(2), "other_scheme": m.group(3),
                                "other_st": m.group(4), "score": int(m.group(5))})
        elif m := _EXTRA_EXACT.match(line):
            out["additional_exact"].append({"scheme": m.group(1), "locus": m.group(2), "allele": m.group(3)})
        elif m := _EXACT.match(line):
            loci = out["exact_by_scheme"].setdefault(m.group(1), [])
            if m.group(2) not in loci:
                loci.append(m.group(2))
        elif m := _EXCLUDED.match(line):
            out["excluded"] = sorted(m.group(1).split())
        elif m := _BLASTN.match(line):
            out["blastn"] = m.group(1)
        elif m := _NOVEL_COUNT.match(line):
            out["novel_alleles"] = int(m.group(1))
        elif m := _ERROR.match(line):
            out["errors"].append(m.group(1))
        elif line.startswith("Setting --minscore=0 because user chose --scheme"):
            out["minscore_forced"] = True
    return out


def parse_novel(text: str) -> list[dict[str, Any]]:
    """--novel FASTA: >scheme.locus-md5 file, one record per novel full-length allele."""
    out = []
    for line in text.splitlines():
        if line.startswith(">"):
            ident = line[1:].split()[0]
            m = re.fullmatch(r"(\w+)\.(.+)-([0-9a-f]{32})", ident)
            out.append({"id": ident, "scheme": m.group(1) if m else None, "locus": m.group(2) if m else None,
                        "md5": m.group(3) if m else None, "length": 0})
        elif out:
            out[-1]["length"] += len(line.strip())
    return out


def warnings(row: dict[str, Any], log: dict[str, Any], scheme_forced: bool) -> list[dict[str, Any]]:
    """ARVA's warnings about one result, each with a code and its values (the interface translates them)."""
    out: list[dict[str, Any]] = []
    if row["scheme"] is None:
        out.append({"code": "no_scheme", "params": {}})
        return out
    by_type: dict[str, list[str]] = {}
    for a in row["alleles"]:
        by_type.setdefault(a["type"], []).append(a["locus"])
    for kind in ("novel", "partial", "missing", "multiple", "null", "unrecognised"):
        if loci := by_type.get(kind):
            out.append({"code": f"{kind}_alleles", "params": {"count": len(loci), "loci": ", ".join(loci)}})
    if row["st"] is None:
        out.append({"code": "st_not_assigned", "params": {}})
    if log["ties"]:
        others = sorted({t["other_scheme"] for t in log["ties"]} | {t["scheme"] for t in log["ties"]})
        out.append({"code": "tied_schemes", "params": {"schemes": ", ".join(others), "score": log["ties"][0]["score"]}})
    if scheme_forced:
        out.append({"code": "scheme_forced", "params": {"scheme": row["scheme"]}})
    return out


class MlstAdapter(ToolAdapter):
    info = ToolInfo(
        id="mlst",
        name="mlst",
        description="MLST from assembled contigs: BLAST against the PubMLST typing schemes mlst bundles, with "
        "automatic scheme detection or a chosen scheme.",
        homepage="https://github.com/tseemann/mlst",
        license="GPL-2.0",
        citation="Seemann T. mlst. https://github.com/tseemann/mlst (software, unpublished). The bundled schemes "
        "come from PubMLST: Jolley KA, Bray JE, Maiden MCJ. Open-access bacterial population genomics: BIGSdb "
        "software, the PubMLST.org website and their applications. Wellcome Open Res 2018;3:124.",
        citation_url="https://doi.org/10.12688/wellcomeopenres.14826.1",
        executable="mlst",
        categories=("typing",),
        input_formats=("fasta",),
        output_formats=("tsv", "json", "fasta"),
        min_version="2.35.0",
        tested_versions=("2.35.0",),
        install={"conda_lock": "python3 scripts/conda_locks.py install mlst ~/.arva-tools/conda/mlst  # then "
                          "ARVA_TOOL_MLST=~/.arva-tools/conda/mlst/bin/mlst"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"mlst (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available or d.path is None:
            return d
        db = database_dir(d.path)
        if not database_info(db)["ready"]:
            d.reason, d.reason_params = "mlst_db_missing", {"path": str(db)}
            note = f"mlst's bundled database was not found in {db} (pubmlst/ schemes and the blast/ index)"
            d.message = f"{d.message}. {note}" if d.message else note
        return d

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(MlstAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: MlstParams, genome: Path, out_dir: Path, db: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this mlst version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, "--full", "--outfile", str(out_dir / OUTPUTS["tsv"]), "--json", str(out_dir / OUTPUTS["json"]),
             "--novel", str(out_dir / OUTPUTS["novel"]), "--threads", str(params.threads),
             "--minid", f"{params.minid:g}", "--mincov", f"{params.mincov:g}", "--minscore", f"{params.minscore:g}"]
        a += ["--scheme", params.scheme] if params.scheme else ["--exclude", ",".join(params.exclude)]
        return [*a, "--blastdb", str(db / "blast" / "mlst.fa"), "--datadir", str(db / "pubmlst"), str(genome)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        errors = parse_stderr(log)["errors"]
        return f"mlst stopped: {errors[-1]}" if errors else None


def env_for(executable: str, tmp_dir: Path | None = None) -> dict[str, str]:
    """PATH with the environment's bin/ first (bin/mlst runs `env perl`, blastn and any2fasta from PATH), the
    bundled database as MLST_DBDIR, no Perl settings from the user's shell, and the temporary folder."""
    env = {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}",
           "MLST_DBDIR": str(database_dir(executable)), **_PERL_VARIABLES}
    if tmp_dir is not None:
        env["TMPDIR"] = str(tmp_dir)
    return env
