"""GTDB-Tk — classification of a genome in the Genome Taxonomy Database (GTDB): ANI screen with skani against the
GTDB species representatives, then marker genes, alignment and placement in the GTDB reference tree.

NOT VALIDATED WITH ARVA: the reference data (release R232) need about 100 GB of disk and, for bacteria, about 140 GB
of memory, so no real classification was run. The facts below come from GTDB-Tk 2.8.0 (Bioconda
gtdbtk-2.8.0-pyhdfd78af_0, ARVA's lock docker/conda-locks/gtdbtk/linux-64.lock; no linux-aarch64 lock because
Bioconda has no pplacer 1.1.alpha19 for it): its `classify_wf -h`, its source (gtdbtk/config/common.py,
gtdbtk/config/output.py, gtdbtk/files/classify_summary.py, gtdbtk/classify.py) and its documentation (Installing
GTDB-Tk, Hardware requirements):

* `classify_wf (--genome_dir DIR | --batchfile FILE) --out_dir DIR`; -x (default fna), --prefix (default gtdbtk),
  --cpus (default 1), --pplacer_cpus, --min_af (default 0.5, "minimum alignment fraction to assign genome to a
  species cluster"), --min_perc_aa (default 10), --tmpdir (default /tmp). ARVA passes each one; --pplacer_cpus 1
  because, per the documentation, the memory used varies with the number of pplacer threads. -f/--full_tree (more
  than 950 GB of memory) is never used.
* GTDBTK_DATA_PATH names the reference data; GTDB-Tk 2.8.0 accepts release r232 only (COMPATIBLE_REF_DATA_VERSIONS).
* Hardware requirements (documentation of 2.8.0): bacteria about 140 GB of memory (950 GB with --full_tree),
  archaea about 100 GB, storage about 100 GB. ARVA refuses to start when the performance profile's memory for a run
  is below 140 GB.
* Results: classify/<prefix>.bac120.summary.tsv and classify/<prefix>.ar53.summary.tsv (also linked from the output
  folder), columns as in ClassifySummaryFile.get_col_order; "N/A" for missing values; other related references as
  "GCF_123, s__Name, radius, ANI, AF; …"; classification as d__…;p__…;…;s__<species>, with s__ empty when no species
  was assigned.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

FLAGS = ("--genome_dir", "--out_dir", "--extension", "--prefix", "--cpus", "--pplacer_cpus", "--min_af",
         "--min_perc_aa", "--tmpdir")
PREFIX = "gtdbtk"
SUMMARIES = {"bacteria": f"classify/{PREFIX}.bac120.summary.tsv", "archaea": f"classify/{PREFIX}.ar53.summary.tsv"}
LOG = "gtdbtk.log"
# GTDB-Tk 2.8.0 documentation, Installing GTDB-Tk → Hardware requirements (memory in GB).
MEMORY_GB = {"bacteria": 140, "archaea": 100}
REQUIRED_MEMORY_GB = max(MEMORY_GB.values())
STORAGE_GB = 100
COMPATIBLE_DATA = ("r232",)
SUMMARY_COLUMNS = ["user_genome", "classification", "closest_genome_reference", "closest_genome_reference_radius",
                   "closest_genome_taxonomy", "closest_genome_ani", "closest_genome_af",
                   "closest_placement_reference", "closest_placement_radius", "closest_placement_taxonomy",
                   "closest_placement_ani", "closest_placement_af", "pplacer_taxonomy", "classification_method",
                   "note", "other_related_references(genome_id,species_name,radius,ANI,AF)", "msa_percent",
                   "translation_table", "red_value", "warnings"]


@dataclass
class GtdbtkParams:
    threads: int = 1
    min_af: float = 0.5
    min_perc_aa: float = 10.0

    def validate(self) -> None:
        errors = []
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if not 0 < self.min_af <= 1:
            errors.append("min_af must be greater than 0 and at most 1")
        if not 0 <= self.min_perc_aa <= 100:
            errors.append("min_perc_aa must be between 0 and 100")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _value(text: str) -> str | None:
    return None if text in ("N/A", "", "None") else text


def _number(text: str) -> float | None:
    v = _value(text)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def species_of_classification(classification: str) -> str | None:
    """The species of a GTDB classification string (the s__ rank), None when GTDB-Tk left it empty."""
    for rank in classification.split(";"):
        if rank.startswith("s__"):
            return rank[3:].strip() or None
    return None


def parse_related(text: str | None) -> list[dict[str, Any]]:
    out = []
    for entry in (text or "").split(";"):
        parts = [p.strip() for p in entry.split(",")]
        if len(parts) >= 5:
            out.append({"accession": parts[0], "species": parts[1].removeprefix("s__") or None,
                        "radius": _number(parts[2]), "ani": _number(parts[3]), "af": _number(parts[4])})
    return out


def parse_summary(text: str, domain: str) -> list[dict[str, Any]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].split("\t") != SUMMARY_COLUMNS:
        raise ValueError("GTDB-Tk's summary does not have the columns of GTDB-Tk 2.8.0")
    rows = []
    for n, line in enumerate(lines[1:], 2):
        cols = line.split("\t")
        if len(cols) != len(SUMMARY_COLUMNS):
            raise ValueError(f"GTDB-Tk summary line {n} has {len(cols)} columns instead of {len(SUMMARY_COLUMNS)}")
        v = dict(zip(SUMMARY_COLUMNS, cols, strict=True))
        rows.append({
            "domain": domain, "user_genome": v["user_genome"], "classification": v["classification"],
            "species": species_of_classification(v["classification"]),
            "closest_reference": _value(v["closest_genome_reference"]),
            "closest_radius": _number(v["closest_genome_reference_radius"]),
            "closest_taxonomy": _value(v["closest_genome_taxonomy"]),
            "closest_ani": _number(v["closest_genome_ani"]), "closest_af": _number(v["closest_genome_af"]),
            "classification_method": _value(v["classification_method"]), "note": _value(v["note"]),
            "related": parse_related(_value(v["other_related_references(genome_id,species_name,radius,ANI,AF)"])),
            "msa_percent": _number(v["msa_percent"]), "translation_table": _value(v["translation_table"]),
            "red_value": _number(v["red_value"]), "warnings": _value(v["warnings"]),
        })
    return rows


class GtdbtkAdapter(ToolAdapter):
    info = ToolInfo(
        id="gtdbtk",
        name="GTDB-Tk",
        description="Classification in the Genome Taxonomy Database (ANI screen, marker genes, placement in the GTDB "
        "tree). Needs the GTDB reference data (about 100 GB) and about 140 GB of memory. Not validated with ARVA.",
        homepage="https://github.com/Ecogenomics/GTDBTk",
        license="GPL-3.0-or-later",
        citation="Chaumeil P.-A., Mussig A.J., Hugenholtz P., Parks D.H. GTDB-Tk v2: memory friendly classification "
        "with the genome taxonomy database. Bioinformatics 2022;38(23):5315-5316.",
        citation_url="https://doi.org/10.1093/bioinformatics/btac672",
        executable="gtdbtk",
        categories=("species",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="2.8.0",
        tested_versions=(),
        install={"conda_lock": "python3 scripts/conda_locks.py install gtdbtk ~/.arva-tools/conda/gtdbtk  # linux-64 "
                               "only; then ARVA_TOOL_GTDBTK=~/.arva-tools/conda/gtdbtk/bin/gtdbtk"},
        conda_platforms=("linux-64",),
    )
    version_pattern = re.compile(r"gtdbtk: version (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("classify_wf", "-h"), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(GtdbtkAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: GtdbtkParams, genome_dir: Path, out_dir: Path, tmp_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this GTDB-Tk version does not offer {', '.join(missing)} (not in its classify_wf -h)")
        return [executable, "classify_wf", "--genome_dir", str(genome_dir), "--out_dir", str(out_dir),
                "--extension", "fna", "--prefix", PREFIX, "--cpus", str(params.threads), "--pplacer_cpus", "1",
                "--min_af", f"{params.min_af:g}", "--min_perc_aa", f"{params.min_perc_aa:g}", "--tmpdir",
                str(tmp_dir)]


def env_for(executable: str, data_path: Path | None = None) -> dict[str, str]:
    """PATH with the environment's bin/ first (GTDB-Tk runs prodigal, hmmsearch, hmmalign, pplacer, guppy, skani
    and FastTree from PATH: gtdbtk/misc.py check_install) and GTDBTK_DATA_PATH."""
    env = {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    if data_path is not None:
        env["GTDBTK_DATA_PATH"] = str(data_path)
    return env
