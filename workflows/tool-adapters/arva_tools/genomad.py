"""geNomad — identification of plasmids and viruses (proviruses inside host contigs included) in assembled contigs,
with gene-based markers and a neural network, against geNomad's database.

Written from geNomad 1.13.0's source (genomad/cli.py, genomad/_paths.py, genomad/modules/summary.py and
find_proviruses.py at tag v1.13.0) and ARVA's lock (docker/conda-locks/genomad/); NOT VALIDATED HERE: neither the
environment (about 1 GB to download) nor database 1.9 (842 MB archive, 1.5 GB unpacked) fit the test machine's disk,
so the parsers are tested on constructed files in those formats (tests/fixtures/genomad, labelled CONSTRUCTED):

* `genomad end-to-end [OPTIONS] INPUT OUTPUT DATABASE`. Defaults (cli.py): --threads all CPUs, --splits 0,
  --sensitivity 4.2, --min-score 0.7, --max-fdr 0.1 (used only with --enable-score-calibration),
  --min-number-genes 1, --min-plasmid-marker-enrichment 0.1, --min-virus-marker-enrichment 0.0,
  --min-plasmid-hallmarks 0, --min-plasmid-hallmarks-short-seqs 1, --min-virus-hallmarks 0,
  --min-virus-hallmarks-short-seqs 1, --max-uscg 4; --conservative/--relaxed are presets that cannot be combined with
  those filters, so ARVA passes the filters themselves. --cleanup removes intermediate files.
* Outputs (_paths.py): <OUTPUT>/<prefix>_summary/<prefix>_plasmid_summary.tsv and <prefix>_virus_summary.tsv, where
  prefix is the input file's name without its extension. Plasmid columns (summary.py): seq_name, length, topology,
  n_genes, genetic_code, plasmid_score, fdr, n_hallmarks, marker_enrichment, conjugation_genes, amr_genes. Virus
  columns: seq_name, length, topology, coordinates, n_genes, genetic_code, virus_score, fdr, n_hallmarks,
  marker_enrichment, taxonomy. A provirus is named <contig>|provirus_<start>_<end> and its coordinates are
  "<start>-<end>" (find_proviruses.py); "NA" marks an empty value, and fdr is NA without score calibration.

geNomad's scores are classifier outputs, not proof: a plasmid call says the contig's genes resemble plasmid genes.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

DEFAULTS = {"splits": "0", "sensitivity": "4.2", "min-score": "0.7", "min-number-genes": "1",
            "min-plasmid-marker-enrichment": "0.1", "min-virus-marker-enrichment": "0.0",
            "min-plasmid-hallmarks": "0", "min-plasmid-hallmarks-short-seqs": "1", "min-virus-hallmarks": "0",
            "min-virus-hallmarks-short-seqs": "1", "max-uscg": "4"}
OUTDIR = "genomad"
LOG = "genomad.stderr.log"
PLASMID_COLUMNS = ("seq_name", "length", "topology", "n_genes", "genetic_code", "plasmid_score", "fdr", "n_hallmarks",
                   "marker_enrichment", "conjugation_genes", "amr_genes")
VIRUS_COLUMNS = ("seq_name", "length", "topology", "coordinates", "n_genes", "genetic_code", "virus_score", "fdr",
                 "n_hallmarks", "marker_enrichment", "taxonomy")
_INTS = ("length", "n_genes", "genetic_code", "n_hallmarks")
_FLOATS = ("plasmid_score", "virus_score", "fdr", "marker_enrichment")
_LISTS = ("conjugation_genes", "amr_genes")
_PROVIRUS = re.compile(r"^(?P<contig>.+)\|provirus_(?P<start>\d+)_(?P<end>\d+)$")
_COORDS = re.compile(r"(\d+)-(\d+)")


@dataclass
class GenomadParams:
    min_score: float = 0.7
    min_number_genes: int = 1
    min_plasmid_marker_enrichment: float = 0.1
    min_virus_marker_enrichment: float = 0.0
    min_plasmid_hallmarks: int = 0
    min_plasmid_hallmarks_short_seqs: int = 1
    min_virus_hallmarks: int = 0
    min_virus_hallmarks_short_seqs: int = 1
    max_uscg: int = 4
    sensitivity: float = 4.2
    splits: int = 0
    threads: int = 4

    def validate(self) -> None:
        errors = []
        if not 0 <= self.min_score <= 1:
            errors.append("min_score must be from 0 to 1")
        if not 0 < self.sensitivity <= 7.5:
            errors.append("sensitivity must be greater than 0 and at most 7.5 (MMseqs2's range)")
        for k in ("min_number_genes", "min_plasmid_hallmarks", "min_plasmid_hallmarks_short_seqs",
                  "min_virus_hallmarks", "min_virus_hallmarks_short_seqs", "max_uscg", "splits"):
            if not 0 <= getattr(self, k) <= 1000:
                errors.append(f"{k} must be a whole number from 0 to 1000")
        for k in ("min_plasmid_marker_enrichment", "min_virus_marker_enrichment"):
            if not -100 <= getattr(self, k) <= 100:
                errors.append(f"{k} must be between -100 and 100")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _option(key: str) -> str:
    return "--" + key.replace("_", "-")


_FILTERS = ("min_score", "min_number_genes", "min_plasmid_marker_enrichment", "min_virus_marker_enrichment",
            "min_plasmid_hallmarks", "min_plasmid_hallmarks_short_seqs", "min_virus_hallmarks",
            "min_virus_hallmarks_short_seqs", "max_uscg", "sensitivity", "splits")


def flags(_params: GenomadParams) -> list[str]:
    return ["--threads", "--cleanup", *(_option(k) for k in _FILTERS)]


def env_for(executable: str) -> dict[str, str]:
    """PATH with the environment's bin/ first (geNomad runs mmseqs, aragorn and its own helpers from PATH)."""
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def help_options(text: str) -> frozenset[str]:
    """The options rich-click prints in `genomad end-to-end --help` (inside its boxes: "│ --min-score  FLOAT ...")."""
    return frozenset(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", text))


def outputs(out_dir: Path, contigs: Path) -> dict[str, Path]:
    prefix = contigs.name.rsplit(".", 1)[0]
    summary = out_dir / OUTDIR / f"{prefix}_summary"
    return {"plasmid": summary / f"{prefix}_plasmid_summary.tsv", "virus": summary / f"{prefix}_virus_summary.tsv"}


def _value(key: str, raw: str) -> Any:
    if raw in ("NA", ""):
        return [] if key in _LISTS else None
    if key in _LISTS:
        return raw.split(";")
    if key in _INTS:
        return int(raw)
    if key in _FLOATS:
        return float(raw)
    return raw


def _parse(text: str, columns: tuple[str, ...], what: str) -> list[dict[str, Any]]:
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows or tuple(rows[0]) != columns:
        raise ValueError(f"geNomad's {what} summary does not have the columns geNomad 1.13.0 writes")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if not cols:
            continue
        if len(cols) != len(columns):
            raise ValueError(f"line {n} of geNomad's {what} summary has {len(cols)} fields instead of {len(columns)}")
        try:
            out.append({k: _value(k, v) for k, v in zip(columns, cols, strict=True)})
        except ValueError as exc:
            raise ValueError(f"line {n} of geNomad's {what} summary: {exc}") from None
    return out


def parse_plasmids(text: str) -> list[dict[str, Any]]:
    return [{**r, "contig": r["seq_name"]} for r in _parse(text, PLASMID_COLUMNS, "plasmid")]


def parse_viruses(text: str) -> list[dict[str, Any]]:
    """Virus calls with the contig and, for a provirus, its coordinates on the contig (1-based, inclusive)."""
    out = []
    for r in _parse(text, VIRUS_COLUMNS, "virus"):
        m = _PROVIRUS.match(r["seq_name"])
        c = _COORDS.fullmatch(r["coordinates"] or "")
        if m:
            out.append({**r, "contig": m.group("contig"), "provirus": True,
                        "start": int(c.group(1)) if c else int(m.group("start")),
                        "end": int(c.group(2)) if c else int(m.group("end"))})
        else:
            out.append({**r, "contig": r["seq_name"], "provirus": False, "start": None, "end": None})
    return out


class GenomadAdapter(ToolAdapter):
    info = ToolInfo(
        id="genomad",
        name="geNomad",
        description="Plasmids and viruses (proviruses inside host contigs included) in assembled contigs, from "
        "gene markers and a neural network, against geNomad's database.",
        homepage="https://github.com/apcamargo/genomad",
        license="MIT",
        citation="Camargo AP, Roux S, Schulz F, et al. Identification of mobile genetic elements with geNomad. Nat "
        "Biotechnol 2024;42:1303-1312.",
        citation_url="https://doi.org/10.1038/s41587-023-01953-y",
        executable="genomad",
        categories=("plasmid", "virus", "mobile_element"),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="1.13.0",
        tested_versions=(),
        install={"conda_lock": "python3 scripts/conda_locks.py install genomad ~/.arva-tools/conda/genomad"
                               "  # then ARVA_TOOL_GENOMAD=~/.arva-tools/conda/genomad/bin/genomad"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"geNomad, version (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("end-to-end", "--help"), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(GenomadAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: GenomadParams, contigs: Path, out_dir: Path, db: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this geNomad version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, "end-to-end", "--threads", str(params.threads), "--cleanup"]
        for k in _FILTERS:
            v = getattr(params, k)
            a += [_option(k), str(v) if isinstance(v, int) else f"{v:g}"]
        return [*a, str(contigs), str(out_dir / OUTDIR), str(db)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        lines = [ln.strip() for ln in log.splitlines() if "Error" in ln or "error:" in ln]
        return f"geNomad stopped: {lines[-1]}" if lines else None
