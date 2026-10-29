"""MOB-suite — plasmid reconstruction (mob_recon) and typing (mob_typer, which mob_recon runs on each plasmid it
reconstructs) from assembled contigs, against MOB-suite's plasmid and biomarker databases.

Verified against MOB-suite 3.1.9 (Bioconda mob_suite-3.1.9-pyhdfd78af_1, ARVA's lock docker/conda-locks/mobsuite/)
from `mob_recon --help`, its source (mob_recon.py, mob_typer.py, mob_init.py, utils.py, constants.py, blast/,
wrappers/) and real runs with database 3.1.8 (tests/fixtures/mobsuite):

* `mob_recon -d <folder>`: with a folder other than the package's own, mob_recon reads ncbi_plasmid_full_seqs.fas
  (its BLAST index), ncbi_plasmid_full_seqs.fas.msh, clusters.txt, rep.dna.fas, mob.proteins.faa, mpf.proteins.faa,
  orit.fas, repetitive.dna.fas (its BLAST index), host_range_literature_plasmidDB.txt and taxa.sqlite from it, and
  does not run mob_init. The FASTA of the reference plasmids is only searched through its BLAST index (blastn -db);
  the query sequences (replicons, relaxases, MPF, oriT) are read as FASTA. With the package's own folder mob_recon
  runs mob_init when status.txt is missing, and the Bioconda package runs mob_init in its post-link script: mob_init
  downloads the database with TLS verification turned off (pycurl SSL_VERIFYPEER 0) and the NCBI taxonomy, latest
  release, through ete3. ARVA never runs mob_init: it prepares the folder itself (below) and always passes -d.
* Preparing a folder, as mob_init does it: `makeblastdb -in repetitive.dna.fas -dbtype nucl`, `makeblastdb -in
  ncbi_plasmid_full_seqs.fas -parse_seqids -dbtype nucl`, `mash sketch -p <n> -i -o ncbi_plasmid_full_seqs.fas.msh
  -k 21 -s 1000 ncbi_plasmid_full_seqs.fas`, and ete3's NCBITaxa(dbfile=taxa.sqlite), which builds taxa.sqlite (and
  taxa.sqlite.traverse.pkl) from names.dmp, nodes.dmp and merged.dmp of an NCBI taxdump tar (ete3 3.1.3
  ncbi_taxonomy/ncbiquery.py update_db, writing taxa.tab, syn.tab and merged.tab in the working folder).
  ete3 downloads the taxonomy itself only when no taxdump is given; ARVA always gives one.
* Defaults (--help): --min_length 1000; --min_rep_ident, --min_mob_ident, --min_con_ident, --min_rpp_ident 80;
  --min_rep_cov, --min_mob_cov, --min_rpp_cov 80; --min_con_cov 60; the four e-values 1e-05; --min_overlap 10;
  --max_contig_size and --max_plasmid_size 450000; --primary_cluster_dist 0.06, --secondary_cluster_dist 0.025;
  --num_threads 1. ARVA passes each of them explicitly. The identity and coverage options are integers (argparse
  type=int).
* Outputs in --outdir (which must not exist unless --force): contig_report.txt (one row per contig: sample_id,
  molecule_type, primary_cluster_id, secondary_cluster_id, contig_id, size, gc, md5, circularity_status, rep_type(s),
  rep_type_accession(s), relaxase_type(s), relaxase_type_accession(s), mpf_type, mpf_type_accession(s),
  orit_type(s), orit_accession(s), predicted_mobility, mash_nearest_neighbor, mash_neighbor_distance,
  mash_neighbor_identification, repetitive_dna_id, repetitive_dna_type, filtering_reason), mobtyper_results.txt
  (one row per reconstructed plasmid, MOB_TYPER_REPORT_HEADER, with the predicted host range), mge.report.txt
  (MOB-suite's repetitive elements on the contigs: IS, transposons, ...), biomarkers.blast.txt, chromosome.fasta and
  plasmid_<cluster>.fasta. Temporary files go to <outdir>/__tmp, removed unless --keep_tmp.
* molecule_type starts as 'chromosome' for every contig and becomes 'plasmid' only when the contig is assigned to a
  plasmid cluster: 'chromosome' is MOB-suite's call "not assigned to a plasmid", not a proof of a chromosome.
  --min_length is the shortest BLAST alignment kept in the contig searches (utils.blastn filters hits on their
  alignment length), not a contig filter. circularity_status is 'not tested' unless -c (overhang
  detection) or -u (Unicycler's circular=true flags) is given; ARVA shows the assembler's own circularity instead.
* predicted_mobility (utils.py): conjugative (relaxase and MPF), mobilizable (relaxase or oriT, no MPF), or
  non-mobilizable. Empty values are '-'; several values are joined with ','.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

DEFAULTS = {
    "min_length": "1000", "min_rep_ident": "80", "min_mob_ident": "80", "min_con_ident": "80",
    "min_rpp_ident": "80", "min_rep_cov": "80", "min_mob_cov": "80", "min_con_cov": "60", "min_rpp_cov": "80",
    "min_rep_evalue": "1e-05", "min_mob_evalue": "1e-05", "min_con_evalue": "1e-05", "min_rpp_evalue": "1e-05",
    "min_overlap": "10", "max_contig_size": "450000", "max_plasmid_size": "450000", "primary_cluster_dist": "0.06",
    "secondary_cluster_dist": "0.025", "num_threads": "1",
}
OUTDIR = "mob_recon"
OUTPUTS = {"contig_report": "contig_report.txt", "mobtyper": "mobtyper_results.txt", "mge": "mge.report.txt",
           "biomarkers": "biomarkers.blast.txt", "chromosome": "chromosome.fasta"}
LOG = "mob_recon.stderr.log"
SAMPLE_ID = "sample"
CONTIG_COLUMNS = (
    "sample_id", "molecule_type", "primary_cluster_id", "secondary_cluster_id", "contig_id", "size", "gc", "md5",
    "circularity_status", "rep_type(s)", "rep_type_accession(s)", "relaxase_type(s)", "relaxase_type_accession(s)",
    "mpf_type", "mpf_type_accession(s)", "orit_type(s)", "orit_accession(s)", "predicted_mobility",
    "mash_nearest_neighbor", "mash_neighbor_distance", "mash_neighbor_identification", "repetitive_dna_id",
    "repetitive_dna_type", "filtering_reason",
)
TYPER_COLUMNS = (
    "sample_id", "num_contigs", "size", "gc", "md5", "rep_type(s)", "rep_type_accession(s)", "relaxase_type(s)",
    "relaxase_type_accession(s)", "mpf_type", "mpf_type_accession(s)", "orit_type(s)", "orit_accession(s)",
    "predicted_mobility", "mash_nearest_neighbor", "mash_neighbor_distance", "mash_neighbor_identification",
    "primary_cluster_id", "secondary_cluster_id", "predicted_host_range_overall_rank",
    "predicted_host_range_overall_name", "observed_host_range_ncbi_rank", "observed_host_range_ncbi_name",
    "reported_host_range_lit_rank", "reported_host_range_lit_name", "associated_pmid(s)",
)
MGE_COLUMNS = (
    "sample_id", "molecule_type", "primary_cluster_id", "secondary_cluster_id", "contig_id", "size", "gc", "md5",
    "mge_id", "mge_acs", "mge_type", "mge_subtype", "mge_length", "mge_start", "mge_end", "contig_start",
    "contig_end", "length", "sstrand", "qcovhsp", "pident", "evalue", "bitscore",
)
BIOMARKER_COLUMNS = ("qseqid", "sseqid", "qlen", "slen", "qstart", "qend", "sstart", "send", "length", "mismatch",
                     "pident", "qcovhsp", "qcovs", "sstrand", "evalue", "bitscore", "biomarker")
_LISTS = ("rep_type(s)", "rep_type_accession(s)", "relaxase_type(s)", "relaxase_type_accession(s)", "mpf_type",
          "mpf_type_accession(s)", "orit_type(s)", "orit_accession(s)", "associated_pmid(s)")
_INTS = ("size", "num_contigs", "mge_length", "mge_start", "mge_end", "contig_start", "contig_end", "length")
_FLOATS = ("gc", "mash_neighbor_distance", "qcovhsp", "pident", "evalue", "bitscore")
MOBILITY = ("conjugative", "mobilizable", "non-mobilizable")

# --- Database ---------------------------------------------------------------------------------------------------

# The files of the Zenodo archive (data/ of MOB-suite database 3.1.8) mob_recon reads; the archive also holds macOS
# metadata (._* and .DS_Store) and an empty __init__.py, which ARVA leaves out.
DB_FILES = ("clusters.txt", "host_range_literature_plasmidDB.txt", "mob.proteins.faa", "mpf.proteins.faa",
            "orit.fas", "rep.dna.fas", "repetitive.dna.fas")
PLASMID_FASTA = "ncbi_plasmid_full_seqs.fas"
MASH_SKETCH = f"{PLASMID_FASTA}.msh"
TAXA = "taxa.sqlite"
TAXA_EXTRA = "taxa.sqlite.traverse.pkl"
# What makeblastdb writes for a nucleotide database with -parse_seqids (BLAST+ 2.15.0), and without it.
PLASMID_INDEX = tuple(f"{PLASMID_FASTA}.{s}" for s in ("ndb", "nhr", "nin", "njs", "nog", "nos", "not", "nsq",
                                                         "ntf", "nto"))
REPETITIVE_INDEX = tuple(f"repetitive.dna.fas.{s}" for s in ("ndb", "nhr", "nin", "njs", "not", "nsq", "ntf", "nto"))
TAXDUMP_MEMBERS = ("names.dmp", "nodes.dmp", "merged.dmp")
MASH_K, MASH_S = 21, 1000
_ETE3_BUILD = "import sys; from ete3 import NCBITaxa; NCBITaxa(dbfile=sys.argv[1], taxdump_file=sys.argv[2])"

_OPTION = re.compile(r"^\s{2}(-\w)?(?:\s[A-Z_]+)?,?\s?(--[\w-]+)")
_DEFAULT = re.compile(r"\(default:\s*([^)]*?)\s*\)")
_ERROR = re.compile(r"ERROR:\s*(.+)$|\berror:\s*(.+)$", re.M)


def bin_dir(executable: str) -> Path:
    return Path(os.path.realpath(executable)).parent


def env_for(executable: str, tmp_dir: Path | None = None) -> dict[str, str]:
    """PATH with the environment's bin/ first (mob_recon runs blastn, tblastn, makeblastdb and mash from PATH), and
    the temporary folder."""
    env = {"PATH": f"{bin_dir(executable)}{os.pathsep}{os.environ.get('PATH', '')}"}
    if tmp_dir is not None:
        env["TMPDIR"] = str(tmp_dir)
    return env


def database_state(folder: Path) -> dict[str, Any]:
    """What a prepared MOB-suite folder holds: the files mob_recon reads, the plasmid FASTA (optional, since only its
    BLAST index is searched), the indexes, the Mash sketch and the taxonomy database."""
    def present(names: tuple[str, ...]) -> list[str]:
        return [n for n in names if (folder / n).is_file()]

    missing = [n for n in (*DB_FILES, *PLASMID_INDEX, *REPETITIVE_INDEX, MASH_SKETCH, TAXA, TAXA_EXTRA)
               if not (folder / n).is_file()]
    return {"ready": not missing, "missing": missing, "plasmid_fasta": (folder / PLASMID_FASTA).is_file(),
            "status_txt": (folder / "status.txt").is_file(), "index": present(PLASMID_INDEX)}


def makeblastdb_repetitive(executable: str, folder: Path) -> list[str]:
    return [str(bin_dir(executable) / "makeblastdb"), "-in", str(folder / "repetitive.dna.fas"), "-dbtype", "nucl"]


def makeblastdb_plasmids(executable: str, folder: Path) -> list[str]:
    """mob_init's index of the reference plasmids, built from the FASTA on standard input (streamed from the
    verified archive), under the name mob_init gives it."""
    return [str(bin_dir(executable) / "makeblastdb"), "-in", "-", "-parse_seqids", "-dbtype", "nucl", "-title",
            PLASMID_FASTA, "-out", str(folder / PLASMID_FASTA)]


def mash_sketch(executable: str, folder: Path, threads: int) -> list[str]:
    """mob_init's Mash sketch of the reference plasmids (one sketch per sequence), from standard input."""
    return [str(bin_dir(executable) / "mash"), "sketch", "-p", str(threads), "-i", "-o", str(folder / MASH_SKETCH),
            "-k", str(MASH_K), "-s", str(MASH_S), "-"]


def taxonomy_build(executable: str, folder: Path, taxdump_tar: Path) -> list[str]:
    """ete3's NCBITaxa building taxa.sqlite from a local taxdump tar (it then downloads nothing); run it with a
    temporary working folder, where ete3 writes its intermediate tables."""
    return [str(bin_dir(executable) / "python"), "-I", "-c", _ETE3_BUILD, str(folder / TAXA), str(taxdump_tar)]


# --- Run ----------------------------------------------------------------------------------------------------------

@dataclass
class MobParams:
    min_length: int = 1000
    min_rep_ident: int = 80
    min_mob_ident: int = 80
    min_con_ident: int = 80
    min_rpp_ident: int = 80
    min_rep_cov: int = 80
    min_mob_cov: int = 80
    min_con_cov: int = 60
    min_rpp_cov: int = 80
    min_rep_evalue: float = 1e-05
    min_mob_evalue: float = 1e-05
    min_con_evalue: float = 1e-05
    min_rpp_evalue: float = 1e-05
    min_overlap: int = 10
    max_contig_size: int = 450000
    max_plasmid_size: int = 450000
    primary_cluster_dist: float = 0.06
    secondary_cluster_dist: float = 0.025
    threads: int = 4

    def validate(self) -> None:
        errors = []
        for k in ("min_rep_ident", "min_mob_ident", "min_con_ident", "min_rpp_ident", "min_rep_cov", "min_mob_cov",
                  "min_con_cov", "min_rpp_cov"):
            if not 1 <= getattr(self, k) <= 100:
                errors.append(f"{k} must be a whole percentage from 1 to 100")
        for k in ("min_rep_evalue", "min_mob_evalue", "min_con_evalue", "min_rpp_evalue"):
            if not 0 < getattr(self, k) <= 10:
                errors.append(f"{k} must be greater than 0 and at most 10")
        for k in ("primary_cluster_dist", "secondary_cluster_dist"):
            if not 0 <= getattr(self, k) <= 1:
                errors.append(f"{k} must be a Mash distance from 0 to 1")
        if not 1 <= self.min_length <= 1_000_000:
            errors.append("min_length must be between 1 and 1,000,000 bp")
        if not 0 <= self.min_overlap <= 10_000:
            errors.append("min_overlap must be between 0 and 10,000 bp")
        for k in ("max_contig_size", "max_plasmid_size"):
            if not 1_000 <= getattr(self, k) <= 10_000_000:
                errors.append(f"{k} must be between 1,000 and 10,000,000 bp")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_OPTIONS = tuple(k for k in DEFAULTS if k != "num_threads")


def flags(_params: MobParams) -> list[str]:
    return ["--infile", "--outdir", "--num_threads", "--sample_id", "--database_directory",
            *(f"--{k}" for k in _OPTIONS)]


def _number(value: float | int) -> str:
    return str(value) if isinstance(value, int) else f"{value:g}"


def parse_help_options(text: str) -> frozenset[str]:
    """The options argparse lists in `mob_recon --help` ("  -o OUTDIR, --outdir OUTDIR", "  --min_length ...")."""
    found: set[str] = set()
    for line in text.splitlines():
        if m := _OPTION.match(line):
            found.update(o for o in m.groups() if o)
    return frozenset(found)


def help_defaults(text: str) -> dict[str, str]:
    """The "(default: …)" argparse prints for each option ARVA passes (help texts wrap over several lines)."""
    out, option, buffer = {}, None, ""
    for line in [*text.splitlines(), "  --end"]:
        if m := _OPTION.match(line):
            if option in DEFAULTS and (d := _DEFAULT.search(" ".join(buffer.split()))):
                out[option] = d.group(1)
            option, buffer = m.group(2)[2:], line
        else:
            buffer += " " + line.strip()
    return out


def _value(key: str, raw: str) -> Any:
    raw = raw.strip()
    if raw in ("-", "", "nan"):
        return [] if key in _LISTS else None
    if key in _LISTS:
        return [v.strip() for v in re.split(r"[,;]", raw) if v.strip() and v.strip() != "-"]
    if key in _INTS:
        return int(float(raw))
    if key in _FLOATS:
        return float(raw)
    return raw


def _parse(text: str, columns: tuple[str, ...], what: str) -> list[dict[str, Any]]:
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        raise ValueError(f"MOB-suite's {what} is empty (no header)")
    header = rows[0]
    if tuple(header) != columns:
        raise ValueError(f"MOB-suite's {what} has other columns than MOB-suite 3.1.9 writes: {', '.join(header)}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if not cols:
            continue
        if len(cols) != len(header):
            raise ValueError(f"line {n} of MOB-suite's {what} has {len(cols)} fields instead of {len(header)}")
        try:
            out.append({k: _value(k, v) for k, v in zip(header, cols, strict=True)})
        except ValueError as exc:
            raise ValueError(f"line {n} of MOB-suite's {what}: {exc}") from None
    return out


def parse_contig_report(text: str) -> list[dict[str, Any]]:
    return _parse(text, CONTIG_COLUMNS, "contig report")


def parse_mobtyper(text: str) -> list[dict[str, Any]]:
    return _parse(text, TYPER_COLUMNS, "MOB-typer report")


def parse_mge_report(text: str) -> list[dict[str, Any]]:
    return _parse(text, MGE_COLUMNS, "MGE report")


def parse_biomarkers(text: str) -> list[dict[str, Any]]:
    """biomarkers.blast.txt: where each replicon, relaxase, MPF and oriT hit lies on the contigs (qseqid is
    <reference>|<type>)."""
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        return []
    if tuple(rows[0]) != BIOMARKER_COLUMNS:
        raise ValueError(f"MOB-suite's biomarker report has other columns than MOB-suite 3.1.9 writes: "
                         f"{', '.join(rows[0])}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if not cols:
            continue
        if len(cols) != len(BIOMARKER_COLUMNS):
            raise ValueError(f"line {n} of MOB-suite's biomarker report has {len(cols)} fields")
        r = dict(zip(BIOMARKER_COLUMNS, cols, strict=True))
        reference, _, name = r["qseqid"].partition("|")
        start, end = sorted((int(r["sstart"]), int(r["send"])))
        out.append({"biomarker": r["biomarker"], "name": name or reference, "reference": reference,
                    "contig": r["sseqid"], "start": start, "end": end,
                    "strand": {"plus": "+", "minus": "-"}.get(r["sstrand"]), "identity": float(r["pident"]),
                    "coverage": float(r["qcovhsp"]), "evalue": float(r["evalue"])})
    return out


def plasmid_id(row: dict[str, Any]) -> str | None:
    """mob_typer's sample_id of a reconstructed plasmid is <sample>:<primary cluster>; the contig report gives the
    cluster on each contig."""
    sid = row.get("sample_id") or ""
    return sid.split(":", 1)[1] if ":" in sid else row.get("primary_cluster_id")


def summarise(contigs: list[dict[str, Any]], plasmids: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for c in contigs:
        by_type[c["molecule_type"] or "unknown"] = by_type.get(c["molecule_type"] or "unknown", 0) + 1
    return {"contigs": len(contigs), "plasmid_contigs": by_type.get("plasmid", 0),
            "chromosome_contigs": by_type.get("chromosome", 0), "plasmids": len(plasmids),
            "mobility": {m: sum(1 for p in plasmids if p["predicted_mobility"] == m) for m in MOBILITY}}


def warnings(contigs: list[dict[str, Any]], plasmids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"code": "chromosome_means_unassigned", "params": {}}]
    if any(p["predicted_host_range_overall_name"] for p in plasmids):
        out.append({"code": "host_range_is_prediction", "params": {}})
    rep_only = [c["contig_id"] for c in contigs if c["molecule_type"] == "chromosome" and c["rep_type(s)"]]
    if rep_only:
        out.append({"code": "replicon_on_unassigned_contig", "params": {"count": len(rep_only),
                                                                        "contigs": ", ".join(rep_only[:10])}})
    return out


def failure(text: str) -> str | None:
    found = [m.group(1) or m.group(2) for m in _ERROR.finditer(text)]
    return found[-1].strip() if found else None


class MobsuiteAdapter(ToolAdapter):
    info = ToolInfo(
        id="mobsuite",
        name="MOB-suite",
        description="Plasmid reconstruction and typing from assembled contigs (mob_recon, with mob_typer on each "
        "reconstructed plasmid): each contig's chromosome or plasmid call, replicon and relaxase types, MPF, oriT and "
        "predicted mobility, against MOB-suite's plasmid database.",
        homepage="https://github.com/phac-nml/mob-suite",
        license="Apache-2.0",
        citation="Robertson J, Nash JHE. MOB-suite: software tools for clustering, reconstruction and typing of "
        "plasmids from draft assemblies. Microb Genom 2018;4(8):e000206. Robertson J, Bessonov K, Schonfeld J, Nash "
        "JHE. Universal whole-sequence-based plasmid typing and its utility to prediction of host range and "
        "epidemiological surveillance. Microb Genom 2020;6(10):mgen000435.",
        citation_url="https://doi.org/10.1099/mgen.0.000206",
        executable="mob_recon",
        categories=("plasmid", "mobile_element"),
        input_formats=("fasta",),
        output_formats=("tsv", "fasta"),
        min_version="3.1.9",
        tested_versions=("3.1.9",),
        install={"conda_lock": "python3 scripts/conda_locks.py install mobsuite ~/.arva-tools/conda/mobsuite"
                               "  # then ARVA_TOOL_MOBSUITE=~/.arva-tools/conda/mobsuite/bin/mob_recon"},
        conda_platforms=("linux-64",),
    )
    version_pattern = re.compile(r"mob_recon (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return parse_help_options(MobsuiteAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: MobParams, contigs: Path, out_dir: Path, db: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this MOB-suite version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, "--infile", str(contigs), "--outdir", str(out_dir / OUTDIR), "--num_threads",
             str(params.threads), "--sample_id", SAMPLE_ID, "--database_directory", str(db)]
        for k in _OPTIONS:
            a += [f"--{k}", _number(getattr(params, k))]
        return a

    @staticmethod
    def failure_reason(log: str) -> str | None:
        reason = failure(log)
        return f"MOB-suite stopped: {reason}" if reason else None
