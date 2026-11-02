"""Pangenome tools: Panaroo (validated) and PPanGGOLiN (adapter only, not validated).

Panaroo, verified against Panaroo 1.8.1 (ARVA's Bioconda lock docker/conda-locks/panaroo): its --help
(fixtures/pangenome/panaroo_help.txt), its source (panaroo/__main__.py, set_default_args.py, generate_output.py) and
real runs on five NCBI S. aureus genomes annotated with Bakta (fixtures/pangenome/README.md):

* Input: GFF3 files with the genome sequence after ##FASTA (Bakta's .gff3 and Prokka's .gff are). Each genome is
  named after its file name without extension, so ARVA stages them as input/g1.gff3, g2.gff3 ... ARVA passes the
  files themselves, not a list file: with a list file, set_default_args counts one input when it sets the
  mode-dependent defaults.
* --clean-mode sets, unless given: -c 0.98, -f 0.7, --len_dif_percent 0.98 in every mode; --min_trailing_support
  max(2, ceil(0.05 n)) strict / max(2, ceil(0.01 n)) moderate / 2 sensitive; --trailing_recursive 99999999 / 99999999
  / 0; --edge_support_threshold max(2, ceil(0.01 n)) / same / 0.0; --remove_by_consensus True / False / False;
  --min_edge_support_sv max(2, ceil(0.01 n)) / same / 2. ARVA computes these for the number of genomes and passes
  them all.
* --length_outlier_support_proportion: the help says "default=0.01" but the code's default is 0.1 (__main__.py);
  ARVA passes 0.1 explicitly. --family_len_dif_percent has no default in the code (None reaches cd-hit as "-s None",
  which cd-hit reads as 0); ARVA passes 0.0, the value the help states. --search_radius 5000, --refind_prop_match 0.2,
  --refind-mode default, --high_var_flag 5, --core_threshold 0.95, --codon-table 11 are the code's defaults, passed.
* -a core|pan aligns the families with --aligner (ARVA offers mafft, in Panaroo's environment) into
  aligned_gene_sequences/<family>.aln.fas (headers "<genome>;<clustering id>") and, for core, core_gene_alignment.aln.
  Without -a nothing is aligned.
* Outputs: gene_presence_absence.Rtab (1/0), gene_presence_absence.csv (Gene, Non-unique Gene name, Annotation, one
  column per genome with the member gene IDs joined by ";", followed by "_len" when a member's length is far from
  the family's mode and "_pseudo" when it is not a valid gene), gene_presence_absence_roary.csv, gene_data.csv
  (gff_file, scaffold_name, clustering_id "<genome>_<contig>_<gene>" or "<genome>_refound_<n>", annotation_id,
  prot_sequence, dna_sequence, gene_name, description), summary_statistics.txt (core / soft core / shell / cloud at
  Panaroo's fixed 99 / 95 / 15 %), pan_genome_reference.fa, struct_presence_absence.Rtab, final_graph.gml. Panaroo
  removes commas from the GFF3 text before reading it, so these CSV files hold no quoted fields.
* Panaroo runs cd-hit and the aligners through shell command strings built from the output folder; ARVA runs it in
  the job's results folder with relative paths only.

PPanGGOLiN 2.3.2 (docker/conda-locks/ppanggolin; not installed here: graph-tool, GTK and Boost add about 1 GB): read
from the package source (ppanggolin/workflow/all.py, annotate/annotate.py, formats/writeFlatPangenome.py, utils.py)
but never run, so not validated:

* `ppanggolin workflow --anno <list> -o <dir> --basename pangenome -c <n> --translation_table 11 --kingdom bacteria
  --mode 1 --coverage 0.8 --identity 0.8 -K -1 --tmpdir <dir>`; the list is "<name><TAB><gff path>" per genome
  (GFF3 with ##FASTA). Families are realigned to link fragments unless --no_defrag.
* With no config file the workflow writes matrix.csv (Roary-like; column 2 is the family's partition: persistent,
  shell or cloud), gene_presence_absence.Rtab and gene_families.tsv (family, gene ID, local ID, "F" for a fragment;
  no header) in the output folder.
"""
from __future__ import annotations

import csv
import io
import math
import os
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

CLEAN_MODES = ("strict", "moderate", "sensitive")
REFIND_MODES = ("default", "strict", "off")
ALIGNMENTS = ("none", "core", "pan")
ALIGNERS = ("mafft",)
METHODS = ("panaroo", "ppanggolin")
PANAROO_FLAGS = ("-i", "-o", "--clean-mode", "--remove-invalid-genes", "-c", "-f", "--len_dif_percent",
                 "--family_len_dif_percent", "--merge_paralogs", "--search_radius", "--refind_prop_match",
                 "--refind-mode", "--min_trailing_support", "--trailing_recursive", "--edge_support_threshold",
                 "--length_outlier_support_proportion", "--remove_by_consensus", "--high_var_flag",
                 "--min_edge_support_sv", "-a", "--aligner", "--core_threshold", "-t", "--codon-table")
PPANGGOLIN_FLAGS = ("--anno", "-o", "--basename", "-c", "--translation_table", "--kingdom", "--mode", "--coverage",
                    "--identity", "-K", "--tmpdir")
PANAROO_KEEP = ("gene_presence_absence.Rtab", "gene_presence_absence.csv", "gene_presence_absence_roary.csv",
                "gene_data.csv", "summary_statistics.txt", "pan_genome_reference.fa", "struct_presence_absence.Rtab",
                "final_graph.gml", "core_gene_alignment.aln", "core_gene_alignment_filtered.aln",
                "alignment_entropy.csv")
PPANGGOLIN_KEEP = ("gene_presence_absence.Rtab", "matrix.csv", "gene_families.tsv", "genomes_statistics.tsv",
                   "pangenome.h5")
_FLAGS = re.compile(r"(_len|_pseudo)+$")


def env_for(executable: str) -> dict[str, str]:
    """The tool's own environment bin/ first in PATH: Panaroo calls cd-hit and the aligners by name."""
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


@dataclass
class PanarooParams:
    clean_mode: str = "strict"
    identity: float = 0.98
    family_threshold: float = 0.7
    length_difference: float = 0.98
    family_length_difference: float = 0.0
    merge_paralogs: bool = False
    remove_invalid_genes: bool = False
    search_radius: int = 5000
    refind_prop_match: float = 0.2
    refind_mode: str = "default"
    length_outlier_support_proportion: float = 0.1
    high_var_flag: int = 5
    alignment: str = "none"
    aligner: str = "mafft"
    core_threshold: float = 0.95
    codon_table: int = 11
    threads: int = 1

    def validate(self) -> None:
        errors = []
        if self.clean_mode not in CLEAN_MODES:
            errors.append(f"clean_mode must be one of {', '.join(CLEAN_MODES)}")
        if self.refind_mode not in REFIND_MODES:
            errors.append(f"refind_mode must be one of {', '.join(REFIND_MODES)}")
        if self.alignment not in ALIGNMENTS:
            errors.append(f"alignment must be one of {', '.join(ALIGNMENTS)}")
        if self.aligner not in ALIGNERS:
            errors.append(f"aligner must be one of {', '.join(ALIGNERS)}")
        for name, lo, hi in (("identity", 0.5, 1.0), ("family_threshold", 0.3, 1.0), ("length_difference", 0.0, 1.0),
                             ("family_length_difference", 0.0, 1.0), ("refind_prop_match", 0.0, 1.0),
                             ("length_outlier_support_proportion", 0.0, 1.0), ("core_threshold", 0.5, 1.0)):
            if not lo <= getattr(self, name) <= hi:
                errors.append(f"{name} must be between {lo:g} and {hi:g}")
        if not 0 <= self.search_radius <= 100_000:
            errors.append("search_radius must be between 0 and 100000")
        if not 1 <= self.high_var_flag <= 100:
            errors.append("high_var_flag must be between 1 and 100")
        if self.codon_table not in (4, 11, 25):
            errors.append("codon_table must be 11, 4 or 25")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def mode_settings(mode: str, n: int) -> dict[str, Any]:
    """The values Panaroo 1.8.1's set_default_args gives the mode-dependent options for n genomes."""
    if mode == "sensitive":
        return {"min_trailing_support": 2, "trailing_recursive": 0, "edge_support_threshold": 0.0,
                "remove_by_consensus": False, "min_edge_support_sv": 2}
    frac = 0.05 if mode == "strict" else 0.01
    one = max(2, math.ceil(0.01 * n))
    return {"min_trailing_support": max(2, math.ceil(frac * n)), "trailing_recursive": 99999999,
            "edge_support_threshold": float(one), "remove_by_consensus": mode == "strict", "min_edge_support_sv": one}


def _num(v: float) -> str:
    return format(v, "g")


@dataclass
class PpanggolinParams:
    identity: float = 0.8
    coverage: float = 0.8
    clustering_mode: str = "1"
    partitions: int = -1
    translation_table: int = 11
    kingdom: str = "bacteria"
    threads: int = 1

    def validate(self) -> None:
        errors = []
        for name in ("identity", "coverage"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                errors.append(f"{name} must be between 0 and 1")
        if self.clustering_mode not in ("0", "1", "2", "3"):
            errors.append("clustering_mode must be 0, 1, 2 or 3")
        if self.partitions != -1 and not 2 <= self.partitions <= 20:
            errors.append("partitions must be -1 (automatic) or between 2 and 20")
        if self.kingdom not in ("bacteria", "archaea"):
            errors.append("kingdom must be bacteria or archaea")
        if self.translation_table not in (4, 11, 25):
            errors.append("translation_table must be 11, 4 or 25")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def missing_flags(method: str, help_text: str) -> list[str]:
    flags = PANAROO_FLAGS if method == "panaroo" else PPANGGOLIN_FLAGS
    return [f for f in flags if not re.search(rf"(^|[\s,\[]){re.escape(f)}([\s,=\]]|$)", help_text, re.M)]


class PanarooAdapter(ToolAdapter):
    info = ToolInfo(
        id="panaroo",
        name="Panaroo",
        description="Graph-based pangenome clustering of annotated prokaryote genomes, correcting annotation errors "
        "(fragmented, missing and contaminant genes) through the gene graph.",
        homepage="https://gthlab.au/panaroo",
        license="MIT",
        citation="Tonkin-Hill G, MacAlasdair N, Ruis C, et al. Producing polished prokaryotic pangenomes with the "
        "Panaroo pipeline. Genome Biol 2020;21:180.",
        citation_url="https://doi.org/10.1186/s13059-020-02090-4",
        executable="panaroo",
        categories=("pangenome",),
        input_formats=("gff3",),
        output_formats=("rtab", "csv", "fasta", "gml"),
        min_version="1.3",
        tested_versions=("1.8.1",),
        install={"conda": "bioconda::panaroo"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    # `panaroo --version` prints "panaroo 1.8.1".
    version_pattern = re.compile(r"panaroo (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), extra_env=env_for(executable))

    @staticmethod
    def argv(executable: str, params: PanarooParams, inputs: list[str], out_dir: str) -> list[str]:
        params.validate()
        if len(inputs) < 2:
            raise ValueError("Panaroo needs at least two genomes")
        mode = mode_settings(params.clean_mode, len(inputs))
        a = [executable, "-i", *inputs, "-o", out_dir, "--clean-mode", params.clean_mode,
             "-c", _num(params.identity), "-f", _num(params.family_threshold),
             "--len_dif_percent", _num(params.length_difference),
             "--family_len_dif_percent", _num(params.family_length_difference),
             "--search_radius", str(params.search_radius), "--refind_prop_match", _num(params.refind_prop_match),
             "--refind-mode", params.refind_mode,
             "--min_trailing_support", str(mode["min_trailing_support"]),
             "--trailing_recursive", str(mode["trailing_recursive"]),
             "--edge_support_threshold", _num(mode["edge_support_threshold"]),
             "--length_outlier_support_proportion", _num(params.length_outlier_support_proportion),
             "--remove_by_consensus", str(mode["remove_by_consensus"]),
             "--high_var_flag", str(params.high_var_flag),
             "--min_edge_support_sv", str(mode["min_edge_support_sv"]),
             "--core_threshold", _num(params.core_threshold), "-t", str(params.threads),
             "--codon-table", str(params.codon_table)]
        if params.merge_paralogs:
            a.append("--merge_paralogs")
        if params.remove_invalid_genes:
            a.append("--remove-invalid-genes")
        if params.alignment != "none":
            a += ["-a", params.alignment, "--aligner", params.aligner]
        return a


class PpanggolinAdapter(ToolAdapter):
    info = ToolInfo(
        id="ppanggolin",
        name="PPanGGOLiN",
        description="Partitioned pangenome graphs: gene families split into persistent, shell and cloud by a "
        "statistical model of presence and neighbourhood (adapter not validated with ARVA).",
        homepage="https://github.com/labgem/PPanGGOLiN",
        license="CeCILL-2.1",
        citation="Gautreau G, Bazin A, Gachet M, et al. PPanGGOLiN: Depicting microbial diversity via a partitioned "
        "pangenome graph. PLoS Comput Biol 2020;16(3):e1007732.",
        citation_url="https://doi.org/10.1371/journal.pcbi.1007732",
        executable="ppanggolin",
        categories=("pangenome",),
        input_formats=("gff3",),
        output_formats=("rtab", "csv", "hdf5"),
        min_version="2.0",
        tested_versions=(),
        install={"conda": "bioconda::ppanggolin"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"ppanggolin (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("workflow", "--help"), extra_env=env_for(executable))

    @staticmethod
    def argv(executable: str, params: PpanggolinParams, anno_list: str, out_dir: str, tmp_dir: str) -> list[str]:
        params.validate()
        return [executable, "workflow", "--anno", anno_list, "-o", out_dir, "--basename", "pangenome",
                "-c", str(params.threads), "--translation_table", str(params.translation_table),
                "--kingdom", params.kingdom, "--mode", params.clustering_mode, "--coverage", _num(params.coverage),
                "--identity", _num(params.identity), "-K", str(params.partitions), "--tmpdir", tmp_dir]


# --- Parsers ------------------------------------------------------------------------------------------------------

def parse_summary(text: str) -> dict[str, int]:
    """Panaroo's summary_statistics.txt: '<name><TAB>(<range>)<TAB><count>' per line."""
    keys = {"Core genes": "core", "Soft core genes": "soft_core", "Shell genes": "shell", "Cloud genes": "cloud",
            "Total genes": "total"}
    out = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] in keys:
            out[keys[parts[0]]] = int(parts[2])
    if set(out) != set(keys.values()):
        raise ValueError("summary_statistics.txt does not list the five Panaroo categories")
    return out


def parse_presence_csv(text: str) -> dict[str, Any]:
    """Panaroo's gene_presence_absence.csv: per family its name, gene names, annotation and, per genome, the member
    gene IDs and flags ("len", "pseudo")."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Gene,Non-unique Gene name,Annotation,"):
        raise ValueError("gene_presence_absence.csv does not have Panaroo's header")
    genomes = lines[0].split(",")[3:]
    families = []
    for n, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cells = line.split(",")
        if len(cells) != len(genomes) + 3:
            raise ValueError(f"gene_presence_absence.csv line {n} has {len(cells)} columns")
        members = {}
        for g, cell in zip(genomes, cells[3:], strict=True):
            if not cell:
                continue
            m = _FLAGS.search(cell)
            flags = [f for f in ("len", "pseudo") if m and f"_{f}" in m.group(0)]
            ids = (cell[:m.start()] if m else cell).split(";")
            members[g] = {"ids": [i for i in ids if i], "flags": flags}
        families.append({"family": cells[0], "gene_names": [x for x in cells[1].split(";") if x],
                         "annotation": cells[2], "members": members})
    return {"genomes": genomes, "families": families}


GENE_DATA_HEADER = "gff_file,scaffold_name,clustering_id,annotation_id,prot_sequence,dna_sequence,gene_name,description"


def iter_gene_data(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    """(byte offset, row) for each gene of Panaroo's gene_data.csv."""
    with path.open("rb") as fh:
        header = fh.readline().decode().rstrip("\r\n")
        if header != GENE_DATA_HEADER:
            raise ValueError("gene_data.csv does not have Panaroo's header")
        keys = header.split(",")
        while True:
            offset = fh.tell()
            raw = fh.readline()
            if not raw:
                return
            cells = raw.decode(errors="replace").rstrip("\r\n").split(",")
            if len(cells) != len(keys):
                raise ValueError(f"gene_data.csv has a row with {len(cells)} columns at byte {offset}")
            yield offset, dict(zip(keys, cells, strict=True))


def read_gene_data_row(path: Path, offset: int) -> dict[str, str]:
    with path.open("rb") as fh:
        fh.seek(offset)
        cells = fh.readline().decode(errors="replace").rstrip("\r\n").split(",")
    keys = GENE_DATA_HEADER.split(",")
    if len(cells) != len(keys):
        raise ValueError("gene_data.csv changed since the job indexed it")
    return dict(zip(keys, cells, strict=True))


def gene_position(clustering_id: str) -> tuple[int, int] | None:
    """(contig index, gene index) from a clustering id "<genome>_<contig>_<gene>"; None for refound genes."""
    parts = clustering_id.split("_")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return int(parts[1]), int(parts[2])
    return None


def refound_location(description: str) -> dict[str, Any] | None:
    """Panaroo writes 'location:<start>-<end>;strand:<+|->' as the description of a gene it refound."""
    m = re.fullmatch(r"location:(\d+)-(\d+);strand:([+-])", description.strip())
    return {"start": int(m.group(1)), "end": int(m.group(2)), "strand": m.group(3)} if m else None


def parse_ppanggolin_matrix(text: str) -> dict[str, str]:
    """Family -> partition (persistent, shell, cloud) from PPanGGOLiN's matrix.csv (quoted, Roary-like)."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or header[:2] != ["Gene", "Non-unique Gene name"]:
        raise ValueError("matrix.csv does not have PPanGGOLiN's header")
    out = {}
    for row in reader:
        if row:
            if row[1] not in ("persistent", "shell", "cloud"):
                raise ValueError(f"matrix.csv gives family {row[0]} the partition {row[1]!r}")
            out[row[0]] = row[1]
    return out


def parse_ppanggolin_families(text: str) -> dict[str, list[dict[str, Any]]]:
    """Family -> members from gene_families.tsv (family, gene ID, local ID, "F" for a fragment; no header)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        cells = line.split("\t")
        if len(cells) != 4:
            raise ValueError(f"gene_families.tsv line {n} has {len(cells)} columns")
        out.setdefault(cells[0], []).append({"id": cells[1], "local_id": cells[2], "fragment": cells[3] == "F"})
    return out
