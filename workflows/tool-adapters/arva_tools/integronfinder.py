"""IntegronFinder — integrons (integron integrase intI, attC recombination sites, and optionally the Pc promoter and
attI site) in assembled contigs, with HMMER, Infernal and Prodigal and the models bundled in its package.

Verified against IntegronFinder 2.0.6 (Bioconda integron_finder-2.0.6-pyhdfd78af_0, ARVA's lock
docker/conda-locks/integronfinder/) from `integron_finder --help`, its source at tag v2.0.6
(integron_finder/scripts/finder.py, config.py, results.py, topology.py) and real runs (tests/fixtures/integronfinder):

* `integron_finder [options] <replicon FASTA>`; results go to <outdir>/Results_Integron_Finder_<file name without
  extension>/: <name>.integrons (one row per element of every integron), <name>.summary (complete, In0 and CALIN
  counts per replicon) and integron_finder.out (the log). ARVA passes --cmsearch, --hmmsearch and --prodigal (the
  environment's own) and --mute.
* Defaults (--help): --local-max off, --cpu 1, --distance-thresh 4000, --evalue-attc 1, --calin-threshold 2,
  --max-attc-size 200, --min-attc-size 40, --promoter-attI off, --union-integrases off, --keep-palindromes off.
  ARVA passes the values explicitly (and --local-max or --promoter-attI when chosen; the two flags it never sets
  are recorded as off).
* Topology (topology.py): with no option a replicon is circular when it is the only sequence of the file, otherwise
  linear; --topology-file gives one "<seq id> circ|lin" per line. ARVA writes that file from the assembler's own
  circularity (Flye, Unicycler), linear when unknown.
* .integrons columns (results.py integrons_report): ID_integron, ID_replicon, element, pos_beg, pos_end, strand (1 or
  -1), evalue, type_elt (protein, attC, Promoter, attI), annotation (intI, attC, Pc_int1, ...), model, type
  (complete: intI and attC sites; In0: intI without attC; CALIN: attC sites without intI, kept only with at least
  --calin-threshold sites), default (Yes/No), distance_2attC, considered_topology. Lines starting with # are
  comments; "NA" marks an empty value.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

# The defaults --help states (--cpu states none; finder.py's default is 1).
DEFAULTS = {"distance-thresh": "4000", "evalue-attc": "1", "calin-threshold": "2", "max-attc-size": "200bp",
            "min-attc-size": "40bp"}
INPUT = "contigs.fna"
TOPOLOGY = "topology.txt"
OUTDIR = "integron_finder"
LOG = "integron_finder.stderr.log"
COLUMNS = ("ID_integron", "ID_replicon", "element", "pos_beg", "pos_end", "strand", "evalue", "type_elt", "annotation",
           "model", "type", "default", "distance_2attC", "considered_topology")
TYPES = ("complete", "In0", "CALIN")
_OPTION = re.compile(r"^\s{2}(-\w+)?(?:,\s)?(--[\w-]+)?")
_DEFAULT = re.compile(r"\(default:\s*([^)]*?)\s*\)|\[(\d+)\]bp")


@dataclass
class IntegronParams:
    local_max: bool = True
    promoter_attI: bool = False
    distance_thresh: int = 4000
    evalue_attc: float = 1.0
    calin_threshold: int = 2
    max_attc_size: int = 200
    min_attc_size: int = 40
    threads: int = 4

    def validate(self) -> None:
        errors = []
        if not 1 <= self.distance_thresh <= 100_000:
            errors.append("distance_thresh must be between 1 and 100,000 bp")
        if not 0 < self.evalue_attc <= 10:
            errors.append("evalue_attc must be greater than 0 and at most 10")
        if not 1 <= self.calin_threshold <= 100:
            errors.append("calin_threshold must be between 1 and 100 attC sites")
        if not 1 <= self.min_attc_size < self.max_attc_size <= 1000:
            errors.append("the attC sizes must satisfy 1 <= min_attc_size < max_attc_size <= 1000")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "union_integrases": False, "keep_palindromes": False}


def flags(params: IntegronParams) -> list[str]:
    used = ["--cpu", "--distance-thresh", "--evalue-attc", "--calin-threshold", "--max-attc-size", "--min-attc-size",
            "--outdir", "--topology-file", "--cmsearch", "--hmmsearch", "--prodigal", "--mute"]
    return used + (["--local-max"] if params.local_max else []) + (["--promoter-attI"] if params.promoter_attI else [])


def bin_dir(executable: str) -> Path:
    return Path(os.path.realpath(executable)).parent


def env_for(executable: str) -> dict[str, str]:
    return {"PATH": f"{bin_dir(executable)}{os.pathsep}{os.environ.get('PATH', '')}"}


def parse_help_options(text: str) -> frozenset[str]:
    found: set[str] = set()
    for line in text.splitlines():
        if m := _OPTION.match(line):
            found.update(o for o in m.groups() if o)
    return frozenset(found)


def help_defaults(text: str) -> dict[str, str]:
    """The defaults --help states for the options ARVA passes ("(default: 1)", "DISTANCE_THRESH [4000]bp")."""
    out, option, buffer = {}, None, ""
    for line in [*text.splitlines(), "  --end"]:
        m = _OPTION.match(line)
        if m and m.group(2):
            if option in DEFAULTS and (d := _DEFAULT.search(" ".join(buffer.split()))):
                out[option] = d.group(1) or d.group(2)
            option, buffer = m.group(2)[2:], line
        else:
            buffer += " " + line.strip()
    return out


def models(executable: str) -> list[Path]:
    """The models IntegronFinder bundles (attC covariance model, intI and phage integrase HMMs), in the package's
    data folder, for the run's record."""
    root = Path(os.path.realpath(executable)).parent.parent
    found = sorted(root.glob("lib/python3*/site-packages/integron_finder/data/Models/*"))
    return [p for p in found if p.is_file() and p.suffix != ".py"]


def models_checksum(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for p in files:
        digest.update(p.name.encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
    return "sha256:" + digest.hexdigest()


def topology_text(circular: dict[str, bool | None]) -> str:
    return "".join(f"{name} {'circ' if c else 'lin'}\n" for name, c in circular.items())


def outputs(out_dir: Path) -> dict[str, Path]:
    result = out_dir / OUTDIR / f"Results_Integron_Finder_{INPUT.rsplit('.', 1)[0]}"
    name = INPUT.rsplit(".", 1)[0]
    return {"integrons": result / f"{name}.integrons", "summary": result / f"{name}.summary",
            "log": result / "integron_finder.out"}


def _value(key: str, raw: str) -> Any:
    if raw in ("NA", ""):
        return None
    if key in ("pos_beg", "pos_end", "strand"):
        return int(raw)
    if key in ("evalue", "distance_2attC"):
        return float(raw)
    return raw


def parse_integrons(text: str) -> list[dict[str, Any]]:
    """The element rows of a .integrons file (comment lines dropped; a file without integrons has no table)."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if not lines:
        return []
    rows = list(csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE))
    if tuple(rows[0]) != COLUMNS:
        raise ValueError(f"the .integrons file has other columns than IntegronFinder 2.0.6 writes: "
                         f"{', '.join(rows[0])}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if len(cols) != len(COLUMNS):
            raise ValueError(f"row {n} of the .integrons file has {len(cols)} fields instead of {len(COLUMNS)}")
        try:
            out.append({k: _value(k, v) for k, v in zip(COLUMNS, cols, strict=True)})
        except ValueError as exc:
            raise ValueError(f"row {n} of the .integrons file: {exc}") from None
    return out


def integrons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per integron: its replicon, type, span (from its first to its last element), strand of the
    integrase, and its elements."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault((r["ID_replicon"], r["ID_integron"]), []).append(r)
    out = []
    for (replicon, integron), elements in sorted(by.items()):
        intI = next((e for e in elements if e["annotation"] == "intI"), None)
        out.append({"replicon": replicon, "integron": integron, "type": elements[0]["type"],
                    "start": min(e["pos_beg"] for e in elements), "end": max(e["pos_end"] for e in elements),
                    "strand": {1: "+", -1: "-"}.get(intI["strand"]) if intI else None,
                    "attc_sites": sum(1 for e in elements if e["type_elt"] == "attC"),
                    "integrase": intI["element"] if intI else None,
                    "topology": elements[0]["considered_topology"],
                    "cassette_proteins": sum(1 for e in elements if e["type_elt"] == "protein"
                                             and e["annotation"] != "intI"),
                    "elements": elements})
    return out


class IntegronfinderAdapter(ToolAdapter):
    info = ToolInfo(
        id="integronfinder",
        name="IntegronFinder",
        description="Integrons in assembled contigs: the integron integrase (intI), attC recombination sites, and "
        "optionally the Pc promoter and attI site, as complete integrons, In0 (intI without attC) or CALIN (attC "
        "sites without intI).",
        homepage="https://github.com/gem-pasteur/Integron_Finder",
        license="GPL-3.0",
        citation="Néron B, Littner E, Haudiquet M, Perrin A, Cury J, Rocha EPC. IntegronFinder 2.0: identification and "
        "analysis of integrons across Bacteria, with a focus on antibiotic resistance in Klebsiella. Microorganisms "
        "2022;10(4):700.",
        citation_url="https://doi.org/10.3390/microorganisms10040700",
        executable="integron_finder",
        categories=("mobile_element",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="2.0.6",
        tested_versions=("2.0.6",),
        install={"conda_lock": "python3 scripts/conda_locks.py install integronfinder ~/.arva-tools/conda/"
                               "integronfinder  # then ARVA_TOOL_INTEGRONFINDER=~/.arva-tools/conda/integronfinder/bin/"
                               "integron_finder"},
        conda_platforms=("linux-64",),
    )
    version_pattern = re.compile(r"integron_finder version (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return parse_help_options(IntegronfinderAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: IntegronParams, contigs: Path, out_dir: Path, topology: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this IntegronFinder version does not offer {', '.join(missing)} (not in its --help)")
        tools = bin_dir(executable)
        a = [executable, "--cpu", str(params.threads), "--distance-thresh", str(params.distance_thresh),
             "--evalue-attc", f"{params.evalue_attc:g}", "--calin-threshold", str(params.calin_threshold),
             "--max-attc-size", str(params.max_attc_size), "--min-attc-size", str(params.min_attc_size),
             "--topology-file", str(topology), "--outdir", str(out_dir / OUTDIR),
             "--cmsearch", str(tools / "cmsearch"), "--hmmsearch", str(tools / "hmmsearch"),
             "--prodigal", str(tools / "prodigal"), "--mute"]
        if params.local_max:
            a.append("--local-max")
        if params.promoter_attI:
            a.append("--promoter-attI")
        return [*a, str(contigs)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        lines = [ln.strip() for ln in log.splitlines() if "ERROR" in ln or "Error" in ln]
        return f"IntegronFinder stopped: {lines[-1]}" if lines else None
