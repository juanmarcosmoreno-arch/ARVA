"""AMRFinderPlus — NCBI's search for antimicrobial resistance, stress response and virulence genes and point mutations
against its Reference Gene Catalog, by BLAST and HMMs.

Verified against AMRFinderPlus 4.2.7 (Bioconda ncbi-amrfinderplus-4.2.7, ARVA's lock docker/conda-locks/amrfinderplus/)
from its `--help`, its source at tag amrfinder_v4.2.7 (amrfinder.cpp, amr_report.cpp, dna_mutation.cpp,
amrfinder_index.cpp, amrfinder_update.cpp, columns.hpp), the ncbi/amr wiki (Running-AMRFinderPlus,
Interpreting-results, Curated-organisms) and real runs with database 2026-08-07.1 (tests/fixtures/amrfinderplus):

* Input decides the search (amrfinder.cpp): --nucleotide alone is a translated nucleotide search; --protein alone a
  protein-only search; --protein with --nucleotide needs --gff (the "combined" search, where hits are tied to the
  annotated proteins and their contig coordinates); --organism adds the point-mutation search.
  --annotation_format tells how the GFF names the proteins (bakta, prokka, ... ; default genbank).
* Defaults (--help): --ident_min -1 (the curated threshold where one exists, otherwise 0.9), --coverage_min 0.5,
  --translation_table 11, --threads 4. ARVA passes each one explicitly, and --blast_bin and --hmmer_bin, so the BLAST
  and HMMER of the tool's own environment run.
* Database: --database <folder>; amrfinder stops when <folder>/AMRProt.fa.phr (the BLAST index) is missing, when the
  software is older than database_format_version.txt, or when version.txt is older than the data version the
  software requires (4.2.7: 2025-09-22.2, `dataVer_min`). `--database_version` prints the version and runs these
  checks. The Bioconda build's default database is $CONDA_PREFIX/share/amrfinderplus/data/latest; ARVA always
  passes --database. -u/--update and amrfinder_update download NCBI's latest data; ARVA never runs them.
* --mutation_all needs --organism (PD-3437): it lists every position screened for point mutations, wild type
  included, so a point-mutation search that found nothing is told apart from one that did not run.
* Report columns (amr_report.cpp report(); the contig columns only when a nucleotide or GFF file is given): Protein
  id, Contig id, Start, Stop, Strand, Element symbol, Element name, Scope, Type, Subtype, Class, Subclass, Method,
  Target length, Reference sequence length, % Coverage of reference, % Identity to reference, Alignment length,
  Closest reference accession, Closest reference name, HMM accession, HMM description, then Hierarchy node with
  --print_node. "NA" marks an empty value; Start is 1-based.
* Methods (amr_report.cpp getMethod, dna_mutation.cpp, wiki Interpreting-results): EXACT, ALLELE, BLAST, PARTIAL
  (50 to 90 % of the reference by default), PARTIAL_CONTIG_END (partial, ending within two bases of a contig end, so
  the gene may continue on another contig), POINT, each with suffix P (protein), X (translated nucleotide) or N
  (nucleotide, POINTN); INTERNAL_STOP (a stop codon before the end of the reference) and HMM without a suffix. With
  --organism Escherichia, --nucleotide and --plus, StxTyper's operon status (COMPLETE, COMPLETE_NOVEL, PARTIAL,
  PARTIAL_CONTIG_END, EXTENDED, INTERNAL_STOP, FRAMESHIFT, AMBIGUOUS) is the Method of stx rows.
* Type is AMR, STRESS or VIRULENCE; Subtype is the type again or POINT, POINT_DISRUPT, BIOCIDE, METAL, HEAT, ACID,
  ANTIGEN, TOXIN, ... (from the database); Scope is core or plus (plus rows only with --plus).
* Temporary files go to $TMPDIR. Messages go to standard error; a failure prints "*** ERROR ***" then the reason.

The wiki's note applies to every result: the presence of a gene or mutation does not mean the isolate is resistant
(AMRFinderPlus does not predict phenotype).
"""
from __future__ import annotations

import csv
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help
from arva_tools.runner import isolated_home, tool_environment

MODES = ("nucleotide", "combined")
ANNOTATION_FORMATS = ("bakta", "prokka")
DEFAULTS = {"ident_min": "-1", "coverage_min": "0.5", "translation_table": "11", "threads": "4"}
OUTPUTS = {"report": "amrfinder.tsv", "mutation_all": "mutation_all.tsv", "nucleotide_hits": "nucleotide_hits.fna",
           "protein_hits": "protein_hits.faa", "log": "amrfinder.stderr.log"}
COLUMNS = {
    "Protein id": "protein_id", "Contig id": "contig", "Start": "start", "Stop": "stop", "Strand": "strand",
    "Element symbol": "element_symbol", "Element name": "element_name", "Scope": "scope", "Type": "type",
    "Subtype": "subtype", "Class": "class", "Subclass": "subclass", "Method": "method",
    "Target length": "target_length", "Reference sequence length": "reference_length",
    "% Coverage of reference": "coverage", "% Identity to reference": "identity",
    "Alignment length": "alignment_length", "Closest reference accession": "closest_accession",
    "Closest reference name": "closest_name", "HMM accession": "hmm_accession", "HMM description": "hmm_description",
    "Hierarchy node": "hierarchy_node",
}
REQUIRED_COLUMNS = ("Protein id", "Element symbol", "Element name", "Type", "Subtype", "Class", "Subclass", "Method",
                    "% Coverage of reference", "% Identity to reference")
_INTS = ("start", "stop", "target_length", "reference_length", "alignment_length")
_FLOATS = ("coverage", "identity")
# The data version AMRFinderPlus requires (amrfinder.cpp dataVer_min), by software version.
DATA_VERSION_MIN = {"4.2.7": "2025-09-22.2"}
DATA_VERSION = re.compile(r"\d{4}-\d{2}-\d{2}\.\d+")
ORGANISM_NAME = re.compile(r"[A-Z][a-z]+(?:_[a-z]+)?")
# The files amrfinder_update downloads into a release folder (amrfinder_update.cpp), before the AMR_DNA-<taxgroup>
# pairs of every taxgroup.tsv line with nucleotide reference genes, and changes.txt.
RELEASE_FILES = ("AMR.LIB", "AMRProt.fa", "AMRProt-mutation.tsv", "AMRProt-suppress.tsv", "AMRProt-susceptible.fa",
                 "AMRProt-susceptible.tsv", "AMR_CDS.fa", "database_format_version.txt", "fam.tsv", "taxgroup.tsv",
                 "version.txt")
RELEASE_LAST = "changes.txt"

_STX = {"COMPLETE": "complete", "COMPLETE_NOVEL": "complete", "AMBIGUOUS": "ambiguous", "EXTENDED": "extended",
        "FRAMESHIFT": "frameshift"}
_BASES = {"EXACT": "complete", "ALLELE": "complete", "BLAST": "complete", "PARTIAL": "partial",
          "PARTIAL_CONTIG_END": "contig_end", "POINT": "point"}
_METHOD = re.compile(r"(EXACT|ALLELE|BLAST|PARTIAL_CONTIG_END|PARTIAL|POINT)([PXN])")
_DEFAULT_LINE = re.compile(r"^\s+Default:\s*(\S+)\s*$")
# Option lines of amrfinder --help start at the first column: "-i MIN_IDENT, --ident_min MIN_IDENT", "--plus".
_OPTION_LINE = re.compile(r"^(?:(-\w)(?: [A-Z][A-Z0-9_]*)?, )?(--\w+)(?=\s|$)")
_ORGANISMS = re.compile(r"^Available --organism options:\s*(.*)$", re.M)
_DB_VERSION = re.compile(r"^Database version:\s*(\S+)", re.M)
_SOFTWARE = re.compile(r"^Software version:\s*(\S+)", re.M)
_SEARCH = re.compile(r"^AMRFinder (.+) search$", re.M)
_ERROR = re.compile(r"\*\*\* ERROR \*\*\*\s*\n(.+?)(?:\n\n|\Z)", re.S)
# amrfinder's advice after some errors; ARVA never runs the update it suggests.
_UPDATE_ADVICE = re.compile(r"\s*To download the latest version to the default directory run: amrfinder -u\s*")


@dataclass
class AmrParams:
    mode: str = "nucleotide"
    organism: str | None = None
    plus: bool = True
    ident_min: float = -1.0
    coverage_min: float = 0.5
    translation_table: int = 11
    annotation_format: str | None = None
    threads: int = 4

    def validate(self) -> None:
        errors = []
        if self.mode not in MODES:
            errors.append(f"mode must be one of {', '.join(MODES)}")
        if self.mode == "combined" and self.annotation_format not in ANNOTATION_FORMATS:
            errors.append(f"the combined search needs the annotation's format ({', '.join(ANNOTATION_FORMATS)})")
        if self.mode == "nucleotide" and self.annotation_format is not None:
            errors.append("a nucleotide search reads no annotation")
        if self.organism is not None and not ORGANISM_NAME.fullmatch(self.organism):
            errors.append("organism must be an AMRFinderPlus organism name such as Staphylococcus_aureus")
        if self.ident_min != -1 and not 0 < self.ident_min <= 1:
            errors.append("ident_min must be -1 (curated thresholds) or a proportion greater than 0 and at most 1")
        if not 0 < self.coverage_min <= 1:
            errors.append("coverage_min must be a proportion greater than 0 and at most 1")
        if not 1 <= self.translation_table <= 33:
            errors.append("translation_table must be an NCBI genetic code from 1 to 33")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def flags(params: AmrParams) -> list[str]:
    used = ["--nucleotide", "--database", "--output", "--nucleotide_output", "--ident_min", "--coverage_min",
            "--translation_table", "--threads", "--blast_bin", "--hmmer_bin", "--print_node"]
    if params.mode == "combined":
        used += ["--protein", "--gff", "--annotation_format", "--protein_output"]
    if params.organism:
        used += ["--organism", "--mutation_all"]
    return used + (["--plus"] if params.plus else [])


def help_defaults(text: str) -> dict[str, str]:
    """The "Default:" line --help prints under each option ARVA passes."""
    out, option = {}, None
    for line in text.splitlines():
        if m := _OPTION_LINE.match(line):
            option = m.group(2)[2:]
        elif (m := _DEFAULT_LINE.match(line)) and option in DEFAULTS:
            out[option] = m.group(1)
    return out


def env_for(executable: str, tmp_dir: Path | None = None) -> dict[str, str]:
    """PATH with the environment's bin/ first (amrfinder runs amr_report, fasta_check, gff_check, stxtyper and others
    from its own folder and BLAST/HMMER from --blast_bin/--hmmer_bin), and the temporary folder."""
    env = {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    if tmp_dir is not None:
        env["TMPDIR"] = str(tmp_dir)
    return env


def bin_dir(executable: str) -> Path:
    return Path(os.path.realpath(executable)).parent


def _run(argv: list[str], executable: str, timeout: int = 300) -> subprocess.CompletedProcess:
    with isolated_home() as home:
        return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                              env={**tool_environment(home), **env_for(executable, home)}, cwd=home,
                              stdin=subprocess.DEVNULL)


def failure(text: str) -> str | None:
    """The reason after amrfinder's "*** ERROR ***" line, if it printed one."""
    m = _ERROR.search(text)
    return " ".join(_UPDATE_ADVICE.sub(" ", m.group(1)).split()) if m else None


def parse_help_options(text: str) -> frozenset[str]:
    """The options amrfinder --help lists, short and long."""
    found: set[str] = set()
    for line in text.splitlines():
        if m := _OPTION_LINE.match(line):
            found.update(o for o in m.groups() if o)
    return frozenset(found)


def database_check(executable: str, db: Path) -> dict[str, Any]:
    """amrfinder's own checks of a database folder (`--database_version`): the version it reads and, when it refuses
    the folder, its reason (missing index, data too old for this software, software too old for the data)."""
    try:
        proc = _run([executable, "--database", str(db), "--database_version"], executable, 60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "version": None, "software": None, "error": str(exc)}
    text = proc.stdout + "\n" + proc.stderr
    version, software = _DB_VERSION.search(text), _SOFTWARE.search(text)
    return {"ok": proc.returncode == 0, "version": version.group(1) if version else None,
            "software": software.group(1) if software else None,
            "error": None if proc.returncode == 0 else failure(text) or f"exit status {proc.returncode}"}


def parse_organisms(text: str) -> list[str]:
    m = _ORGANISMS.search(text)
    return [o.strip() for o in m.group(1).split(",") if o.strip()] if m else []


def list_organisms(executable: str, db: Path) -> list[str]:
    """`amrfinder --list_organisms`: the --organism values this database supports."""
    proc = _run([executable, "--database", str(db), "--list_organisms"], executable, 60)
    if proc.returncode != 0:
        raise RuntimeError(failure(proc.stdout + proc.stderr) or f"amrfinder --list_organisms exited with "
                           f"{proc.returncode}")
    return parse_organisms(proc.stdout + proc.stderr)


def data_version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def data_compatible(software: str | None, data_version: str | None, data_format: str | None) -> dict[str, Any]:
    """Whether this AMRFinderPlus reads a database, by the two rules amrfinder applies: data version at least the one
    the software requires (known for the versions in DATA_VERSION_MIN) and software at least the database's format."""
    from arva_tools.base import parse_version

    needed = DATA_VERSION_MIN.get(software or "")
    if not software or not data_version or not DATA_VERSION.fullmatch(data_version):
        return {"status": "unknown", "needs_data": needed, "needs_software": data_format}
    if data_format and parse_version(software) < parse_version(data_format):
        return {"status": "software_too_old", "needs_data": needed, "needs_software": data_format}
    if needed is None:
        return {"status": "unknown", "needs_data": None, "needs_software": data_format}
    if data_version_key(data_version) < data_version_key(needed):
        return {"status": "data_too_old", "needs_data": needed, "needs_software": data_format}
    return {"status": "compatible", "needs_data": needed, "needs_software": data_format}


def method_kind(method: str) -> dict[str, Any]:
    """What a Method value says about a hit: its kind (complete, partial, contig_end, internal_stop, point, hmm, and
    StxTyper's ambiguous, extended, frameshift), the search it came from (protein, translated, nucleotide) and
    whether the gene's coverage of the reference is complete."""
    if method == "HMM":
        return {"kind": "hmm", "search": None, "full_length": None}
    if method == "INTERNAL_STOP":
        return {"kind": "internal_stop", "search": "translated", "full_length": None}
    if method in _STX or method in ("PARTIAL", "PARTIAL_CONTIG_END"):
        kind = _STX.get(method) or ("partial" if method == "PARTIAL" else "contig_end")
        return {"kind": kind, "search": "nucleotide", "full_length": kind == "complete", "stx": True}
    if m := _METHOD.fullmatch(method):
        kind = _BASES[m.group(1)]
        return {"kind": kind, "search": {"P": "protein", "X": "translated", "N": "nucleotide"}[m.group(2)],
                "full_length": None if kind == "point" else kind == "complete", "exact": m.group(1) in
                ("EXACT", "ALLELE")}
    return {"kind": "other", "search": None, "full_length": None}


def _value(key: str, raw: str) -> Any:
    if raw in ("NA", ""):
        return None
    if key in _INTS:
        return int(raw)
    if key in _FLOATS:
        return float(raw)
    return raw


def parse_report(text: str) -> list[dict[str, Any]]:
    """The rows of an amrfinder report (--output or --mutation_all), with ARVA's names and numbers parsed."""
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows:
        raise ValueError("the AMRFinderPlus report is empty (no header)")
    header = rows[0]
    if missing := [c for c in REQUIRED_COLUMNS if c not in header]:
        raise ValueError(f"the AMRFinderPlus report lacks the columns {', '.join(missing)}")
    if unknown := [c for c in header if c not in COLUMNS]:
        raise ValueError(f"the AMRFinderPlus report has columns ARVA does not know: {', '.join(unknown)}")
    out = []
    for n, cols in enumerate(rows[1:], 2):
        if not cols:
            continue
        if len(cols) != len(header):
            raise ValueError(f"line {n} of the AMRFinderPlus report has {len(cols)} fields instead of {len(header)}")
        try:
            row = {COLUMNS[h]: _value(COLUMNS[h], v) for h, v in zip(header, cols, strict=True)}
        except ValueError as exc:
            raise ValueError(f"line {n} of the AMRFinderPlus report: {exc}") from None
        row.update(method_info=method_kind(row["method"] or ""))
        out.append(row)
    return out


def point_mutation_screen(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """--mutation_all rows: which genes were screened for point mutations and which positions were wild type."""
    genes = sorted({(r.get("closest_name") or r["element_symbol"].split("_")[0]) for r in rows
                    if r["subtype"] in ("POINT", "POINT_DISRUPT")})
    wildtype = sum(1 for r in rows if (r.get("element_name") or "").endswith("[WILDTYPE]"))
    unknown = sum(1 for r in rows if (r.get("element_name") or "").endswith("[UNKNOWN]"))
    return {"rows": len(rows), "genes": genes, "wildtype_positions": wildtype, "unknown_changes": unknown,
            "mutations": len(rows) - wildtype - unknown}


def parse_stderr(text: str) -> dict[str, Any]:
    software, version, search = _SOFTWARE.search(text), _DB_VERSION.search(text), _SEARCH.search(text)
    return {"software_version": software.group(1) if software else None,
            "database_version": version.group(1) if version else None,
            "search": search.group(1) if search else None,
            "includes": [ln.strip()[len("- include "):] for ln in text.splitlines()
                         if ln.strip().startswith("- include ")],
            "warnings": [ln.strip()[len("WARNING: "):] for ln in text.splitlines()
                         if ln.strip().startswith("WARNING: ")],
            "error": failure(text)}


def warnings(params: AmrParams, rows: list[dict[str, Any]], screen: dict[str, Any] | None) -> list[dict[str, Any]]:
    """ARVA's coded warnings about one run (the interface translates them)."""
    out: list[dict[str, Any]] = [{"code": "genotype_not_phenotype", "params": {}}]
    kinds: dict[str, list[str]] = {}
    for r in rows:
        kinds.setdefault(r["method_info"]["kind"], []).append(r["element_symbol"])
    for kind in ("partial", "contig_end", "internal_stop", "hmm", "frameshift", "extended", "ambiguous", "other"):
        if found := kinds.get(kind):
            out.append({"code": f"hits_{kind}", "params": {"count": len(found),
                                                             "genes": ", ".join(sorted(set(found)))}})
    if params.organism is None:
        out.append({"code": "point_mutations_not_searched", "params": {}})
    elif screen is not None and not screen["genes"]:
        out.append({"code": "point_mutation_genes_not_found", "params": {"organism": params.organism}})
    if not params.plus:
        out.append({"code": "plus_not_searched", "params": {}})
    if params.ident_min != -1:
        out.append({"code": "curated_thresholds_overridden", "params": {"ident_min": f"{params.ident_min:g}"}})
    return out


# --- Organism ---------------------------------------------------------------------------------------------------

# The wiki's organism table (Running-AMRFinderPlus, "--organism option", checked 2026-10-29): species other than the
# option's own that its notes name. Members of the species complexes the notes mention are not listed there, so
# ARVA does not choose those options by itself.
ORGANISM_NOTES = {
    "Klebsiella aerogenes": "Klebsiella_pneumoniae",
    "Enterococcus hirae": "Enterococcus_faecium",
    "Streptococcus mitis": "Streptococcus_pneumoniae",
    "Campylobacter coli": "Campylobacter",
    "Campylobacter jejuni": "Campylobacter",
}
# Options for a whole genus in the wiki's table ("Escherichia": "Use for Shigella and Escherichia").
GENUS_OPTIONS = {"Escherichia": "Escherichia", "Shigella": "Escherichia", "Salmonella": "Salmonella"}
COMPLEX_NOTES = {
    "Acinetobacter_baumannii": "A. baumannii-calcoaceticus species complex",
    "Burkholderia_cepacia": "Burkholderia cepacia species complex",
    "Burkholderia_pseudomallei": "Burkholderia pseudomallei species complex",
    "Klebsiella_pneumoniae": "K. pneumoniae species complex",
}


def organism_for(species: str | None, available: list[str]) -> dict[str, Any]:
    """The --organism option for a species name ("Genus species"), by the wiki's table, among the options this database
    lists: the species itself, a species the table's notes name, or a genus option; None otherwise."""
    if not species:
        return {"organism": None, "rule": "no_species", "complex_note": None}
    words = species.replace("_", " ").split()
    if len(words) < 2 or not all(w.isalpha() for w in words[:2]):
        return {"organism": None, "rule": "not_a_species_name", "complex_note": None}
    name = f"{words[0]} {words[1]}"
    candidates = [(name.replace(" ", "_"), "species"), (ORGANISM_NOTES.get(name), "wiki_note"),
                  (GENUS_OPTIONS.get(words[0]), "genus")]
    for organism, rule in candidates:
        if organism and organism in available:
            return {"organism": organism, "rule": rule, "complex_note": COMPLEX_NOTES.get(organism)}
    nearby = next((c for c in COMPLEX_NOTES if c.split("_")[0] == words[0] and c in available), None)
    return {"organism": None, "rule": "not_curated", "complex_note": COMPLEX_NOTES[nearby] if nearby else None,
            "complex_option": nearby}


class AmrfinderplusAdapter(ToolAdapter):
    info = ToolInfo(
        id="amrfinderplus",
        name="AMRFinderPlus",
        description="Antimicrobial resistance, stress response and virulence genes and point mutations in "
        "assembled contigs (and the annotated proteins), against NCBI's Reference Gene Catalog with BLAST and HMMs.",
        homepage="https://github.com/ncbi/amr",
        license="Public domain (United States Government Work)",
        citation="Feldgarden M, Brover V, Gonzalez-Escalona N, et al. AMRFinderPlus and the Reference Gene Catalog "
        "facilitate examination of the genomic links among antimicrobial resistance, stress response, and "
        "virulence. Sci Rep 2021;11:12728.",
        citation_url="https://doi.org/10.1038/s41598-021-91456-0",
        executable="amrfinder",
        categories=("amr", "virulence"),
        input_formats=("fasta", "gff3"),
        output_formats=("tsv", "fasta"),
        min_version="4.2.7",
        tested_versions=("4.2.7",),
        install={"conda_lock": "python3 scripts/conda_locks.py install amrfinderplus ~/.arva-tools/conda/amrfinderplus"
                               "  # then ARVA_TOOL_AMRFINDERPLUS=~/.arva-tools/conda/amrfinderplus/bin/amrfinder"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    version_pattern = re.compile(r"^(\d+\.\d+\.\d+)\s*$", re.M)

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("--help",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return parse_help_options(AmrfinderplusAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: AmrParams, nucleotide: Path, out_dir: Path, db: Path, supported: frozenset[str],
             protein: Path | None = None, gff: Path | None = None) -> list[str]:
        params.validate()
        if (params.mode == "combined") != (protein is not None and gff is not None):
            raise ValueError("the combined search needs the annotation's proteins and GFF, the nucleotide search none")
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this AMRFinderPlus version does not offer {', '.join(missing)} (not in its --help)")
        tools = bin_dir(executable)
        a = [executable, "--nucleotide", str(nucleotide)]
        if protein is not None and gff is not None:
            a += ["--protein", str(protein), "--gff", str(gff), "--annotation_format", str(params.annotation_format),
                  "--protein_output", str(out_dir / OUTPUTS["protein_hits"])]
        a += ["--database", str(db), "--output", str(out_dir / OUTPUTS["report"]),
              "--nucleotide_output", str(out_dir / OUTPUTS["nucleotide_hits"]),
              "--ident_min", f"{params.ident_min:g}", "--coverage_min", f"{params.coverage_min:g}",
              "--translation_table", str(params.translation_table), "--threads", str(params.threads),
              "--blast_bin", str(tools), "--hmmer_bin", str(tools), "--print_node"]
        if params.organism:
            a += ["--organism", params.organism, "--mutation_all", str(out_dir / OUTPUTS["mutation_all"])]
        return a + (["--plus"] if params.plus else [])

    @staticmethod
    def index_argv(executable: str, folder: Path) -> list[str]:
        """amrfinder_index (next to amrfinder): hmmpress of AMR.LIB and makeblastdb of AMRProt.fa, AMR_CDS.fa and
        every AMR_DNA-<taxgroup>.fa (amrfinder_index.cpp), with this environment's BLAST and HMMER."""
        tools = bin_dir(executable)
        return [str(tools / "amrfinder_index"), str(folder), "--blast_bin", str(tools), "--hmmer_bin", str(tools)]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        reason = failure(log)
        return f"AMRFinderPlus stopped: {reason}" if reason else None
