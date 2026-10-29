"""sylph — containment ANI of the genomes of a sylph database (.syldb, such as the GTDB databases) in a sample,
from sampled k-mers; built for metagenomic reads.

Verified against sylph 1.0.0 (Bioconda sylph-1.0.0-hb42e459_0, ARVA's lock docker/conda-locks/sylph/) from
`sylph profile --help`, `sylph inspect`, and real runs on a three-genome database built for the tests
(tests/fixtures/species); not checked against the published GTDB databases (5 to 24 GB):

* `sylph profile DB -r FILE` treats FILE as single-end reads ("Raw single-end fastq/fasta are allowed"); a FASTA given
  without -r would be sketched as a database genome instead. ARVA passes the assembly with -r.
* Defaults (--help): -t 3, -m 95 for profile ("Smaller than 95 for profile will give inaccurate results"), -M 10,
  --min-contain 7, --min-count-correct 3, -c 200 and -k 31 (sketching of raw input; "Does nothing for pre-sketched
  files"). ARVA reads the database's c and k with `sylph inspect` and sketches the assembly with the same values.
* Output: Sample_file, Genome_file, Taxonomic_abundance, Sequence_abundance, Adjusted_ANI, Eff_cov,
  ANI_5-95_percentile, Eff_lambda, Lambda_5-95_percentile, Median_cov, Mean_cov_geq1, Containment_ind, Naive_ANI,
  kmers_reassigned, Contig_name. A sample with no genome above the threshold writes only the header.
* On an assembly every k-mer is seen about once, so sylph cannot estimate coverage (Eff_lambda "LOW") and its
  coverage adjustment does not apply; in ARVA's runs a reference sharing only 10 % of its k-mers got Adjusted_ANI
  100.00 with Naive_ANI 92.80. ARVA therefore reads Naive_ANI (containment ANI without adjustment) and the containment
  index (shared / sampled k-mers of the reference) as the aligned-fraction analogue — ARVA's choice, shown as such.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

FLAGS = ("-r", "-o", "-t", "-m", "-M", "--min-contain", "--min-count-correct", "-c", "-k")
OUTPUT = "sylph.tsv"
LOG = "sylph.log"
INSPECT_OUTPUT = "sylph_inspect.yaml"
HEADER = ["Sample_file", "Genome_file", "Taxonomic_abundance", "Sequence_abundance", "Adjusted_ANI", "Eff_cov",
          "ANI_5-95_percentile", "Eff_lambda", "Lambda_5-95_percentile", "Median_cov", "Mean_cov_geq1",
          "Containment_ind", "Naive_ANI", "kmers_reassigned", "Contig_name"]
_ACCESSION = re.compile(r"GC[AF]_\d{9}\.\d+")
_KEY = re.compile(r"^\s*-?\s*([A-Za-z_]+):\s*(.*)$")


@dataclass
class SylphParams:
    threads: int = 3
    minimum_ani: float = 95.0
    min_number_kmers: int = 10
    min_contain: int = 7
    min_count_correct: int = 3
    c: int = 200
    k: int = 31

    def validate(self) -> None:
        errors = []
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if not 95 <= self.minimum_ani <= 100:
            errors.append("minimum ANI must be between 95 and 100 (sylph: smaller than 95 for profile gives "
                          "inaccurate results)")
        if self.k not in (21, 31):
            errors.append("k must be 21 or 31 (the values sylph supports)")
        if min(self.min_number_kmers, self.min_contain, self.min_count_correct, self.c) < 1:
            errors.append("-M, --min-contain, --min-count-correct and -c must be positive")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_inspect(text: str) -> dict[str, Any]:
    """`sylph inspect DB` (YAML): the database's c, k and min-spacing, and each genome's file, sampled k-mers, first
    contig name and size. Read line by line (the format sylph 1.0.0 writes), without a YAML library."""
    out: dict[str, Any] = {"genomes": []}
    genome: dict[str, Any] | None = None
    for line in text.splitlines():
        m = _KEY.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1].replace("''", "'") if value[0] == "'" else value[1:-1]
        if key == "file_name":
            genome = {"file_name": value}
            out["genomes"].append(genome)
        elif key in ("genome_kmers_num", "genome_size") and genome is not None:
            genome[key] = int(value)
        elif key == "first_contig_name" and genome is not None:
            genome[key] = value
        elif key in ("c", "k", "min_spacing_parameter"):
            out[key] = int(value)
        elif key == "database_file":
            out[key] = value
    if "c" not in out or "k" not in out:
        raise ValueError("sylph inspect did not state the database's c and k")
    return out


def parse_profile(text: str) -> list[dict[str, Any]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].split("\t") != HEADER:
        raise ValueError("sylph's output does not start with " + " ".join(HEADER[:5]) + " …")
    rows = []
    for n, line in enumerate(lines[1:], 2):
        cols = line.split("\t")
        if len(cols) != len(HEADER):
            raise ValueError(f"sylph output line {n} has {len(cols)} columns instead of {len(HEADER)}")
        v = dict(zip(HEADER, cols, strict=True))
        if not re.fullmatch(r"\d+/\d+", v["Containment_ind"]):
            raise ValueError(f"sylph output line {n}: unexpected Containment_ind {v['Containment_ind']!r}")
        shared, sampled = (int(x) for x in v["Containment_ind"].split("/"))
        try:
            naive, adjusted = float(v["Naive_ANI"]), float(v["Adjusted_ANI"])
            abundance = float(v["Taxonomic_abundance"])
        except ValueError:
            raise ValueError(f"sylph output line {n} has a value that is not a number") from None
        acc = _ACCESSION.search(v["Genome_file"])
        rows.append({"reference": v["Genome_file"], "query": v["Sample_file"], "ani": naive, "naive_ani": naive,
                     "adjusted_ani": adjusted, "eff_cov": v["Eff_cov"], "eff_lambda": v["Eff_lambda"],
                     "containment_shared": shared, "containment_sampled": sampled,
                     "af": shared / sampled if sampled else None, "taxonomic_abundance": abundance,
                     "reference_name": v["Contig_name"], "accession": acc.group(0) if acc else None})
    return rows


class SylphAdapter(ToolAdapter):
    info = ToolInfo(
        id="sylph",
        name="sylph",
        description="Containment ANI of the genomes of a sylph database (such as GTDB) in a genome or sample, from "
        "sampled k-mers (built for reads; ARVA reads its unadjusted ANI for an assembly).",
        homepage="https://github.com/bluenote-1577/sylph",
        license="MIT",
        citation="Shaw J., Yu Y.W. Rapid species-level metagenome profiling and containment estimation with sylph. "
        "Nat Biotechnol 2025;43:1348-1359.",
        citation_url="https://doi.org/10.1038/s41587-024-02412-y",
        executable="sylph",
        categories=("species",),
        input_formats=("fasta", "syldb"),
        output_formats=("tsv",),
        min_version="1.0.0",
        tested_versions=("1.0.0",),
        install={"conda_lock": "python3 scripts/conda_locks.py install sylph ~/.arva-tools/conda/sylph  # then "
                               "ARVA_TOOL_SYLPH=~/.arva-tools/conda/sylph/bin/sylph"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"sylph (\d+\.\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("profile", "--help"))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(SylphAdapter.help_text(executable))

    @staticmethod
    def inspect_argv(executable: str, database: Path) -> list[str]:
        return [executable, "inspect", str(database)]

    @staticmethod
    def argv(executable: str, params: SylphParams, query: Path, database: Path, out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this sylph version does not offer {', '.join(missing)} (not in its profile --help)")
        return [executable, "profile", str(database), "-r", str(query), "-o", str(out_dir / OUTPUT),
                "-t", str(params.threads), "-m", f"{params.minimum_ani:g}", "-M", str(params.min_number_kmers),
                "--min-contain", str(params.min_contain), "--min-count-correct", str(params.min_count_correct),
                "-c", str(params.c), "-k", str(params.k)]
