"""sccmec — SCCmec typing of Staphylococcus aureus assemblies (Robert A. Petit III), through camlhmp's BLAST engine.

Verified against sccmec 1.2.0 (Bioconda sccmec-1.2.0-hdfd78af_0 with camlhmp 1.1.4, ARVA's lock
docker/conda-locks/sccmec/) from `sccmec --help`, `sccmec --version`, its scripts bin/sccmec and bin/sccmec-main, its
schema files share/sccmec/*.yaml and real runs (tests/fixtures/sccmec):

* bin/sccmec is a bash wrapper that sets the four schema files as environment defaults and runs `sccmec-main` from
  PATH, so the environment's bin/ goes first on PATH. ARVA passes the four files explicitly (--yaml-targets,
  --yaml-regions, --targets, --regions) and every threshold (--min-targets-pident 90, --min-targets-coverage 80,
  --min-regions-pident 85, --min-regions-coverage 83: the values of the schemas' engine params, which sccmec-main uses
  only when an option is absent from the command line, and the --help defaults).
* Two searches: targets (ccr, mec and IS genes; schema sccmec_targets 1.2.0, types I-XV defined as a ccr complex plus
  a mec class, some with exclusions) and regions (whole reference cassettes; schema sccmec_regions 1.2.0, subtypes Ia,
  Ib, IIa-IIe, III, IVa-IVd, IVg, IVi-IVn, Va-Vc, VI-XV). The "mecA" target includes the mecC sequence of type XI
  (FR821779.1).
* <outdir>/<prefix>.tsv: one row, columns sample, type, subtype, mecA (+/-), targets, regions, coverage, hits,
  target_schema, target_schema_version, region_schema, region_schema_version, camlhmp_version, params,
  target_comment, region_comment, comment; "-" means none. <prefix>.targets.details.tsv and
  <prefix>.regions.details.tsv: one row per type with status True/False and the targets found and missing (their
  params column swaps the labels of identity and coverage; ARVA reads the thresholds from the main table);
  <prefix>.targets.blastn.tsv and <prefix>.regions.blastn.tsv: BLAST hits (qseqid sseqid pident qcovs qlen slen
  length nident mismatch gapopen qstart qend sstart send evalue bitscore).
* --version prints "camlhmp, version X" and "schema sccmec_targets, version Y"; the package's version is the
  schemas' version.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help
from arva_tools.runner import isolated_home, tool_environment

DEFAULTS = {"min-targets-pident": "90", "min-targets-coverage": "80", "min-regions-pident": "85",
            "min-regions-coverage": "83"}
PREFIX = "sccmec"
LOG = "sccmec.stderr.log"
OUTDIR = "sccmec"
RESULT_COLUMNS = ("sample", "type", "subtype", "mecA", "targets", "regions", "coverage", "hits", "target_schema",
                  "target_schema_version", "region_schema", "region_schema_version", "camlhmp_version", "params",
                  "target_comment", "region_comment", "comment")
BLAST_COLUMNS = ("qseqid", "sseqid", "pident", "qcovs", "qlen", "slen", "length", "nident", "mismatch", "gapopen",
                 "qstart", "qend", "sstart", "send", "evalue", "bitscore")
SCHEMA_FILES = ("sccmec-targets.yaml", "sccmec-regions.yaml", "sccmec-targets.fasta", "sccmec-regions.fasta")
_DEFAULT = re.compile(r"\[default:\s*(\d+)\]")


@dataclass
class SccmecParams:
    min_targets_pident: int = 90
    min_targets_coverage: int = 80
    min_regions_pident: int = 85
    min_regions_coverage: int = 83
    threads: int = 1

    def validate(self) -> None:
        values = (self.min_targets_pident, self.min_targets_coverage, self.min_regions_pident,
                  self.min_regions_coverage)
        if not all(1 <= v <= 100 for v in values):
            raise ValueError("the identity and coverage thresholds must be between 1 and 100 %")

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if k != "threads"}


def flags(_params: SccmecParams | None = None) -> list[str]:
    return ["--input", "--yaml-targets", "--yaml-regions", "--targets", "--regions", "--min-targets-pident",
            "--min-targets-coverage", "--min-regions-pident", "--min-regions-coverage", "--prefix", "--outdir"]


def bin_dir(executable: str) -> Path:
    return Path(os.path.realpath(executable)).parent


def env_for(executable: str) -> dict[str, str]:
    return {"PATH": f"{bin_dir(executable)}{os.pathsep}{os.environ.get('PATH', '')}"}


def schema_dir(executable: str) -> Path:
    return bin_dir(executable).parent / "share" / "sccmec"


def schema_files(executable: str) -> list[Path]:
    return [schema_dir(executable) / name for name in SCHEMA_FILES]


def schema_checksum(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for p in files:
        digest.update(p.name.encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
    return "sha256:" + digest.hexdigest()


def read_schema(executable: str, path: Path) -> dict[str, Any]:
    """A schema YAML read by the environment's own Python and PyYAML (as sccmec reads it), returned as JSON."""
    code = "import json, sys, yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))"
    with isolated_home() as home:
        proc = subprocess.run([str(bin_dir(executable) / "python"), "-I", "-c", code, str(path)], capture_output=True,
                              text=True, timeout=60, env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL,
                              check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{path.name} could not be read: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout)


def help_defaults(text: str) -> dict[str, str]:
    """The defaults --help states for the thresholds ("--min-targets-pident INTEGER ... [default: 90]")."""
    out, option = {}, None
    for line in text.splitlines():
        if m := re.search(r"--(min-[\w-]+)", line):
            option = m.group(1)
        if option in DEFAULTS and option not in out and (d := _DEFAULT.search(line)):
            out[option] = d.group(1)
    return out


def parse_help_options(text: str) -> frozenset[str]:
    """sccmec's --help is a rich-click table ("│ *  --input  -i  TEXT ..."): every --option or -o in it."""
    found = set(help_options(text))
    for line in text.splitlines():
        found.update(re.findall(r"(?<![\w-])(--[a-z][\w-]*)", line))
    return frozenset(found)


def outputs(out_dir: Path) -> dict[str, Path]:
    base = out_dir / OUTDIR
    return {"result": base / f"{PREFIX}.tsv", "targets_details": base / f"{PREFIX}.targets.details.tsv",
            "regions_details": base / f"{PREFIX}.regions.details.tsv",
            "targets_blast": base / f"{PREFIX}.targets.blastn.tsv",
            "regions_blast": base / f"{PREFIX}.regions.blastn.tsv"}


def _table(text: str, columns: tuple[str, ...] | None, name: str) -> list[dict[str, str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{name} is empty")
    rows = list(csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE))
    header = tuple(rows[0])
    if columns is not None and header != columns:
        raise ValueError(f"{name} has other columns than sccmec 1.2.0 writes: {', '.join(header)}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if len(cols) != len(header):
            raise ValueError(f"row {n} of {name} has {len(cols)} fields instead of {len(header)}")
        out.append(dict(zip(header, cols, strict=True)))
    return out


def _names(value: str) -> list[str]:
    return [v for v in (value or "").split(",") if v and v != "-"]


def _each(value: str, kind: type) -> list[Any]:
    return [kind(v) for v in (value or "").split(",") if v not in ("", "-")]


def _single(value: str, kind: type) -> Any:
    values = _each(value, kind)
    return values[0] if len(values) == 1 else None


def parse_result(text: str) -> dict[str, Any]:
    rows = _table(text, RESULT_COLUMNS, "the sccmec result table")
    if len(rows) != 1:
        raise ValueError(f"the sccmec result table has {len(rows)} rows instead of 1")
    r = rows[0]
    if r["mecA"] not in ("+", "-"):
        raise ValueError(f"the mecA column holds {r['mecA']!r} instead of + or -")
    return {"type": None if r["type"] in ("", "-") else r["type"],
            "subtype": None if r["subtype"] in ("", "-") else r["subtype"],
            "mecA": r["mecA"] == "+", "targets": _names(r["targets"]), "regions": _names(r["regions"]),
            # With several matching subtypes sccmec lists one coverage and one hit count per region, comma-separated.
            "coverage": _single(r["coverage"], float), "hits": _single(r["hits"], int),
            "region_coverage": _each(r["coverage"], float), "region_hits": _each(r["hits"], int),
            "target_schema": r["target_schema"], "target_schema_version": r["target_schema_version"],
            "region_schema": r["region_schema"], "region_schema_version": r["region_schema_version"],
            "camlhmp_version": r["camlhmp_version"], "params": r["params"], "target_comment": r["target_comment"],
            "region_comment": r["region_comment"], "comment": r["comment"]}


def parse_target_details(text: str) -> list[dict[str, Any]]:
    return [{"type": r["type"], "status": r["status"] == "True", "targets": _names(r["targets"]),
             "missing": _names(r["missing"]), "comment": r["comment"]}
            for r in _table(text, None, "the targets details table")]


def parse_region_details(text: str) -> list[dict[str, Any]]:
    return [{"subtype": r["type"], "status": r["status"] == "True",
             "coverage": float(r["coverage"]) if r["coverage"] not in ("", "-") else None,
             "hits": int(r["hits"]) if r["hits"].isdigit() else None, "comment": r["comment"]}
            for r in _table(text, None, "the regions details table")]


def parse_blast(text: str) -> list[dict[str, Any]]:
    rows = _table(text, BLAST_COLUMNS, "the BLAST hits table")
    ints = ("qcovs", "qlen", "slen", "length", "nident", "mismatch", "gapopen", "qstart", "qend", "sstart", "send")
    return [{k: int(v) if k in ints else float(v) if k in ("pident", "evalue", "bitscore") else v
             for k, v in r.items()} for r in rows]


def target_hits(blast: list[dict[str, Any]], min_pident: float, min_coverage: float) -> list[dict[str, Any]]:
    """The best BLAST hit of each target (highest bitscore), and whether it passes sccmec's thresholds."""
    best: dict[str, dict[str, Any]] = {}
    for h in blast:
        if h["qseqid"] not in best or h["bitscore"] > best[h["qseqid"]]["bitscore"]:
            best[h["qseqid"]] = h
    return [{"target": t, "contig": h["sseqid"], "start": min(h["sstart"], h["send"]),
             "end": max(h["sstart"], h["send"]), "strand": "+" if h["send"] >= h["sstart"] else "-",
             "identity": h["pident"], "coverage": h["qcovs"],
             "passes": h["pident"] >= min_pident and h["qcovs"] >= min_coverage}
            for t, h in sorted(best.items())]


def complexes(targets: list[str], schema: dict[str, Any]) -> dict[str, list[str]]:
    """The ccr complexes and mec classes whose targets (the schema's aliases) were all found."""
    found = set(targets)
    present = [a["name"] for a in schema.get("aliases") or [] if set(a["targets"]) <= found]
    return {"ccr": [n for n in present if n.startswith("ccr ")], "mec": [n for n in present if n.startswith("mec ")]}


def interpret(result: dict[str, Any]) -> dict[str, Any]:
    """ARVA's reading of sccmec's call: typed (type and subtype), type_only, multiple_subtypes (the type, with
    several of its subtypes above the threshold), multiple (several types), mec_without_type (mecA found, no type)
    or not_typeable."""
    t, sub = result["type"], result["subtype"]
    if t == "multiple":
        status = "multiple"
    elif t and sub == "multiple":
        status = "multiple_subtypes"
    elif t and sub and sub != "-":
        status = "typed"
    elif t:
        status = "type_only"
    elif result["mecA"]:
        status = "mec_without_type"
    else:
        status = "not_typeable"
    call = None if status in ("multiple", "mec_without_type", "not_typeable") else t if status == "multiple_subtypes" \
        else (sub or t)
    return {"status": status, "call": call}


class SccmecAdapter(ToolAdapter):
    info = ToolInfo(
        id="sccmec",
        name="sccmec",
        description="SCCmec typing of Staphylococcus aureus assemblies: the type (I-XV) from ccr and mec targets and "
        "the subtype from coverage of reference cassettes, through camlhmp.",
        homepage="https://github.com/rpetit3/sccmec",
        license="MIT",
        citation="Petit RA III. sccmec: typing SCCmec cassettes in assemblies (https://github.com/rpetit3/sccmec); "
        "SCCmec nomenclature: International Working Group on the Classification of Staphylococcal Cassette "
        "Chromosome Elements (IWG-SCC) (2009) Antimicrob Agents Chemother 53(12):4961-4967.",
        citation_url="https://github.com/rpetit3/sccmec",
        executable="sccmec",
        categories=("typing",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="1.2.0",
        tested_versions=("1.2.0",),
        install={"conda_lock": "python3 scripts/conda_locks.py install sccmec ~/.arva-tools/conda/sccmec  # then "
                               "ARVA_TOOL_SCCMEC=~/.arva-tools/conda/sccmec/bin/sccmec"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"schema sccmec_targets, version (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), {**env_for(executable), "COLUMNS": "120", "TERM": "dumb"})

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return parse_help_options(SccmecAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: SccmecParams, contigs: Path, out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this sccmec version does not offer {', '.join(missing)} (not in its --help)")
        yt, yr, t, r = schema_files(executable)
        return [executable, "--input", str(contigs), "--yaml-targets", str(yt), "--yaml-regions", str(yr),
                "--targets", str(t), "--regions", str(r),
                "--min-targets-pident", str(params.min_targets_pident),
                "--min-targets-coverage", str(params.min_targets_coverage),
                "--min-regions-pident", str(params.min_regions_pident),
                "--min-regions-coverage", str(params.min_regions_coverage),
                "--prefix", PREFIX, "--outdir", str(out_dir / OUTDIR)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        lines = [ln.strip() for ln in log.splitlines() if re.search(r"error|Error|ERROR", ln)]
        return f"sccmec stopped: {lines[-1]}" if lines else None
