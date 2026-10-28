"""Prokka — rapid annotation of prokaryotic genomes (Prodigal gene calls, similarity search of the proteins, tRNA,
tmRNA and rRNA prediction).

Prokka's README states that its author can no longer maintain it and recommends Bakta; ARVA offers Prokka as the
alternative annotator of spec §11. Verified against Ubuntu 24.04's prokka 1.14.6+dfsg-6 (`prokka --help`, the
`/usr/bin/prokka` script, Debian's changelog and copyright) and real runs on SYNTHETIC genomes:

* Debian's package keeps the databases unindexed under /usr/share/prokka/db (kingdom protein sets built from
  UniProt release 2023_04 under CC BY 4.0, Rfam 14.1 models, three genus sets) and looks for them in
  $PROKKA_DBDIR or ~/.local/lib/prokka/db; Prokka refuses to annotate until `--setupdb` has indexed them
  (makeblastdb, cmpress) in a writable folder. ARVA links the package's files into the job's folder and runs
  `prokka --dbdir <folder> --setupdb` there (about 1 s and 150 MB, removed after the run). --setupdb presses the
  Archaea, Bacteria and Viruses models, so all three must be linked.
* Debian removed upstream's db/hmm (HAMAP), so there is no HMM step; bookworm's 1.14.6+dfsg-4 also lacks
  db/kingdom (restored in 1.14.6+dfsg-6), so Prokka cannot annotate there without other databases.
* Optional programs Prokka uses only when found: barrnap (rRNA), MinCED (CRISPR arrays), SignalP (with --gram),
  RNAmmer; cmscan with --rfam. Without MinCED Prokka says nothing and writes no CRISPR features.
* Genomes shorter than 100,000 bp make Prokka run Prodigal in metagenome mode ("Contigs total N bp, so using meta
  mode"); ARVA records the mode from the log.
* Contig names longer than 37 characters are refused (a GenBank rule) unless --centre renames them; ARVA can instead
  give Prokka contig_1, contig_2, … and keep the mapping.
* Without --genus/--species/--strain Prokka writes "Genus species strain" into its GenBank files.
* Prokka builds shell commands from its options: file names are quoted, but genus is part of a database path and
  organism names are written into tbl2asn's FASTA description, so ARVA allows only letters, digits and . _ : / -.
* GFF3 values are percent-encoded; EC numbers are in `eC_number`, COG identifiers in `db_xref` (COG:COGnnnn), and
  the evidence in `inference` ("ab initio prediction:Prodigal:002006", "similar to AA sequence:UniProtKB:P04395",
  "COORDINATES:profile:Aragorn:001002"). Proteins without a hit are "hypothetical protein".
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_core.annotation import gff3_attributes, new_feature, sort_xrefs, span_length

from arva_tools.bakta import GENUS, LOCUS_TAG, MAX_MIN_CONTIG, SPECIES, STRAIN, TRANSLATION_TABLES
from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus, help_options, read_help
from arva_tools.pilon import debian_package_version

PREFIX = "annotation"
OUT_DIR = "prokka"
DB_DIR = "prokka-db"
CONSOLE_LOG = "prokka.console.log"
KINGDOM = "Bacteria"
MAX_CONTIG_NAME = 37
# Files Prokka writes as <prefix>.<suffix>, by ARVA's name for them.
OUTPUTS = {"gff3": "gff", "genbank": "gbk", "fna": "fna", "ffn": "ffn", "faa": "faa", "tsv": "tsv", "tbl": "tbl",
           "sqn": "sqn", "summary": "txt", "log": "log", "errors": "err"}
REQUIRED_OUTPUTS = ("gff3", "genbank", "fna", "ffn", "faa", "tsv", "summary", "log")
# Programs Prokka stops without (its %tools table, NEEDED => 1), and makeblastdb/cmpress for --setupdb.
REQUIRED_PROGRAMS = ("aragorn", "prodigal", "blastp", "hmmscan", "hmmpress", "parallel", "tbl2asn", "java",
                     "prokka-genbank_to_fasta_db", "makeblastdb", "cmpress")
OPTIONAL_PROGRAMS = {"barrnap": "rrna", "minced": "crispr", "cmscan": "ncrna", "signalp": "signal_peptides",
                     "rnammer": "rrna"}
# ARVA's names for Prokka's steps; "trna" is Aragorn's search for tRNA and tmRNA genes together.
STEPS = ("trna", "rrna", "ncrna", "crispr", "cds", "similarity", "genus", "hmm", "signal_peptides", "pseudo")
_DB_GLOBS = ("kingdom/*/sprot", "kingdom/*/IS", "kingdom/*/AMR", "genus/*", "hmm/*.hmm")
_DB_MODELS = ("cm/Archaea", "cm/Bacteria", "cm/Viruses")

_TS = re.compile(r"^\[\d\d:\d\d:\d\d\] ")
_STAGE_LINES = {
    "Predicting tRNAs and tmRNAs": "trna",
    "Predicting Ribosomal RNAs": "rrna",
    "Scanning for ncRNAs... please be patient.": "ncrna",
    "Skipping ncRNA search, enable with --rfam if desired.": "ncrna",
    "Searching for CRISPR repeats": "crispr",
    "Predicting coding sequences": "cds",
    "Annotating CDS, please be patient.": "cds_annotation",
    "Generating annotation statistics file": "statistics",
    "Generating Genbank and Sequin files": "genbank",
    "Annotation finished successfully.": "done",
}
STAGES = ("trna", "rrna", "ncrna", "crispr", "cds", "cds_annotation", "statistics", "genbank", "done")
_FOUND_PROGRAM = re.compile(r"Looking for '([^']+)' - found (\S+)")
_PROGRAM_VERSION = re.compile(r"Determined (\S+) version is (\S+) from '(.*)'")
_MODE = re.compile(r"Contigs total (\d+) bp, so using (\w+) mode")
_COUNTS = {"trna": re.compile(r"Found (\d+) tRNAs"), "rrna": re.compile(r"Found (\d+) rRNAs"),
           "ncrna": re.compile(r"Found (\d+) ncRNAs"), "crispr": re.compile(r"Found (\d+) CRISPRs"),
           "cds": re.compile(r"Found (\d+) CDS")}
_SIMILAR = re.compile(r"similar to (?:AA|nucleotide) sequence:([A-Za-z][\w/.-]*):(\S+)")
TYPES = {"CDS": "cds", "tRNA": "trna", "tmRNA": "tmrna", "rRNA": "rrna", "misc_RNA": "ncrna",
         "repeat_region": "crispr"}
# Children or companions of features Prokka writes only with --addgenes/--addmrna (not passed) or SignalP.
_SKIP_TYPES = frozenset({"gene", "mRNA", "sig_peptide"})


@dataclass
class ProkkaParams:
    locus_tag: str
    translation_table: int = 11
    genus: str | None = None
    species: str | None = None
    strain: str | None = None
    use_genus: bool = False
    rfam: bool = False
    evalue: float = 1e-09
    coverage: float = 80.0
    min_contig_length: int = 1
    rename_contigs: bool = False
    threads: int = 1

    def validate(self) -> None:
        errors = []
        if not LOCUS_TAG.fullmatch(self.locus_tag or ""):
            errors.append("locus_tag must be 3-12 capital letters or digits, starting with a letter")
        if self.translation_table not in TRANSLATION_TABLES:
            errors.append(f"translation_table must be one of {', '.join(map(str, TRANSLATION_TABLES))}")
        for name, pattern in (("genus", GENUS), ("species", SPECIES), ("strain", STRAIN)):
            value = getattr(self, name)
            if value is not None and not pattern.fullmatch(value):
                errors.append(f"{name} has characters ARVA does not pass to annotators")
        if self.species is not None and self.genus is None:
            errors.append("a species needs a genus")
        if self.use_genus and self.genus is None:
            errors.append("use_genus needs a genus")
        if not 0 < self.evalue <= 1:
            errors.append("evalue must be greater than 0 and at most 1")
        if not 0 < self.coverage <= 100:
            errors.append("coverage must be greater than 0 and at most 100 (%)")
        if not 1 <= self.min_contig_length <= MAX_MIN_CONTIG:
            errors.append(f"min_contig_length must be between 1 and {MAX_MIN_CONTIG:,}")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def flags(params: ProkkaParams) -> list[str]:
    used = ["--outdir", "--prefix", "--dbdir", "--kingdom", "--gcode", "--locustag", "--increment", "--cpus",
            "--evalue", "--coverage", "--mincontiglen"]
    used += [f for f, v in (("--genus", params.genus), ("--species", params.species), ("--strain", params.strain),
                            ("--usegenus", params.use_genus), ("--rfam", params.rfam)) if v]
    return used


def database_source(executable: str) -> Path:
    """Where Debian's package keeps Prokka's databases: <prefix>/share/prokka/db next to bin/prokka."""
    return Path(os.path.realpath(executable)).parent.parent / "share" / "prokka" / "db"


def database_files(src: Path) -> list[str]:
    """The database files --setupdb indexes (relative to src)."""
    found = sorted({p.relative_to(src).as_posix() for g in _DB_GLOBS for p in src.glob(g) if p.is_file()})
    return found + [m for m in _DB_MODELS if (src / m).is_file()]


def database_info(src: Path) -> dict[str, Any]:
    """What a Prokka database folder offers, and whether ARVA can index it: the Bacteria protein set and the three
    Rfam model files --setupdb presses must be there."""
    files = database_files(src) if src.is_dir() else []
    package = debian_package_version(str(src / "kingdom" / KINGDOM / "sprot")) if files else None
    ready = f"kingdom/{KINGDOM}/sprot" in files and all(m in files for m in _DB_MODELS)
    return {"path": str(src), "ready": ready, "files": files, "package": list(package) if package else None,
            "kingdoms": sorted({f.split("/")[1] for f in files if f.startswith("kingdom/")}),
            "genera": sorted(f.split("/", 1)[1] for f in files if f.startswith("genus/")),
            "hmm": [f for f in files if f.startswith("hmm/")]}


def link_database(src: Path, dest: Path, files: list[str]) -> None:
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(src / rel)


def programs_found() -> dict[str, str | None]:
    return {p: shutil.which(p) for p in (*REQUIRED_PROGRAMS, *OPTIONAL_PROGRAMS)}


def missing_programs(programs: dict[str, str | None]) -> list[str]:
    return [p for p in REQUIRED_PROGRAMS if not programs.get(p)]


def plan_steps(programs: dict[str, str | None], db: dict[str, Any], rfam: bool, use_genus: bool,
               genus: str | None) -> dict[str, dict[str, Any]]:
    """For every step: whether Prokka will run it and, when not, a reason code and the programs behind it."""
    steps: dict[str, dict[str, Any]] = {s: {"run": True, "reason": None, "dependencies": []} for s in STEPS}

    def off(step: str, reason: str, *missing: str) -> None:
        steps[step].update(run=False, reason=reason,
                           dependencies=[{"name": m, "status": "missing", "found": None, "minimum": None}
                                         for m in missing if not programs.get(m)])

    if not programs.get("barrnap") and not programs.get("rnammer"):
        off("rrna", "dependency", "barrnap")
    if not rfam:
        off("ncrna", "option_off")
    elif not programs.get("cmscan"):
        off("ncrna", "dependency", "cmscan")
    if not programs.get("minced"):
        off("crispr", "dependency", "minced")
    if not use_genus:
        off("genus", "option_off")
    elif genus not in db.get("genera", []):
        off("genus", "database_lacks")
    if not db.get("hmm"):
        off("hmm", "database_lacks")
    off("signal_peptides", "not_offered", "signalp")
    off("pseudo", "not_supported")
    return steps


def contig_name_problem(names: list[str]) -> str | None:
    long = [n for n in names if len(n) > MAX_CONTIG_NAME]
    if long:
        return (f"{len(long)} contig name(s) are longer than {MAX_CONTIG_NAME} characters (e.g. {long[0][:60]}), "
                "which Prokka refuses")
    return None


def _first(attrs: dict[str, list[str]], key: str) -> str | None:
    return (attrs.get(key) or [None])[0] or None


class ProkkaAdapter(ToolAdapter):
    info = ToolInfo(
        id="prokka",
        name="Prokka",
        description="Annotation of prokaryotic genomes: Prodigal gene calls with similarity search of the proteins, "
        "tRNA and tmRNA (Aragorn) and rRNA (barrnap). Its README states that it is no longer maintained by its "
        "author, who recommends Bakta; ARVA offers it as an alternative.",
        homepage="https://github.com/tseemann/prokka",
        license="GPL-3.0-or-later",
        citation="Seemann T. Prokka: rapid prokaryotic genome annotation. Bioinformatics 2014;30(14):2068–2069.",
        citation_url="https://doi.org/10.1093/bioinformatics/btu153",
        executable="prokka",
        categories=("annotation",),
        input_formats=("fasta",),
        output_formats=("gff3", "genbank", "fasta", "tsv"),
        min_version="1.14.6",
        tested_versions=("1.14.6",),
        install={"apt": "sudo apt install prokka  # Debian/Ubuntu: 1.14.6+dfsg-6 or later ships its databases"},
    )
    version_pattern = re.compile(r"prokka (\d+\.\d+\.\d+)")

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available or d.path is None:
            return d
        db = database_info(database_source(d.path))
        if not db["ready"]:
            d.reason = "prokka_db_missing"
            note = (f"Prokka's databases were not found in {db['path']} (Debian's prokka 1.14.6+dfsg-6 or later ships "
                    "them there; earlier packages lack the protein sets), so Prokka cannot annotate")
            d.message = f"{d.message}. {note}" if d.message else note
        return d

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(read_help(executable, ("--help",)))

    @staticmethod
    def setupdb_argv(executable: str, db_dir: Path) -> list[str]:
        return [executable, "--dbdir", str(db_dir), "--setupdb"]

    @staticmethod
    def argv(executable: str, params: ProkkaParams, genome: Path, db_dir: Path, out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this Prokka version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, str(genome), "--outdir", str(out_dir), "--prefix", PREFIX, "--dbdir", str(db_dir),
             "--kingdom", KINGDOM, "--gcode", str(params.translation_table), "--locustag", params.locus_tag,
             "--increment", "1", "--cpus", str(params.threads), "--evalue", f"{params.evalue:g}",
             "--coverage", f"{params.coverage:g}", "--mincontiglen", str(params.min_contig_length)]
        for flag, value in (("--genus", params.genus), ("--species", params.species), ("--strain", params.strain)):
            if value is not None:
                a += [flag, value]
        if params.use_genus:
            a.append("--usegenus")
        if params.rfam:
            a.append("--rfam")
        return a

    @staticmethod
    def stage(line: str) -> str | None:
        return _STAGE_LINES.get(_TS.sub("", line).strip())

    @staticmethod
    def parse_log(text: str) -> dict[str, Any]:
        """Programs Prokka found (path and version as it determined them), the Prodigal mode, the counts it printed,
        and the stages seen."""
        programs: dict[str, dict[str, Any]] = {}
        for m in _FOUND_PROGRAM.finditer(text):
            programs.setdefault(m.group(1), {})["path"] = m.group(2)
        for m in _PROGRAM_VERSION.finditer(text):
            programs.setdefault(m.group(1), {}).update(version=m.group(2), reported=m.group(3))
        mode = _MODE.search(text)
        lines = [_TS.sub("", ln).strip() for ln in text.splitlines()]
        return {
            "programs": programs,
            "prodigal_mode": mode.group(2) if mode else None,
            "total_bp": int(mode.group(1)) if mode else None,
            "counts": {k: int(m.group(1)) for k, rx in _COUNTS.items() if (m := rx.search(text))},
            "stages_seen": [s for ln in lines if (s := _STAGE_LINES.get(ln))],
            "ncrna_searched": "Scanning for ncRNAs... please be patient." in lines,
            "crispr_searched": "Searching for CRISPR repeats" in lines,
            "finished": "Annotation finished successfully." in lines,
        }

    @staticmethod
    def failure_reason(log: str, returncode: int | None) -> str | None:
        if "The sequence databases have not been indexed" in log:
            return "Prokka's databases are not indexed (prokka --setupdb did not complete)"
        if m := re.search(r"Contig ID must <= \d+ chars long: (\S+)", log):
            return (f"Prokka refuses contig names longer than {MAX_CONTIG_NAME} characters ({m.group(1)}); annotate "
                    "with renamed contigs")
        if m := re.search(r"Can't find required '([^']+)' in your \$PATH", log):
            return f"Prokka needs {m.group(1)}, which is not installed"
        if m := re.search(r"Prokka needs (\S+) (\S+) or higher", log):
            return f"Prokka needs {m.group(1)} {m.group(2)} or later"
        # Prokka's err() prints its message as an ordinary log line and exits with status 2.
        last = next((_TS.sub("", ln).strip() for ln in reversed(log.splitlines()) if ln.strip()), None)
        if returncode == 2 and last:
            return f"Prokka stopped: {last}"
        if returncode in (-9, 137):
            return "Prokka was stopped by the operating system (out of memory)"
        return None

    @staticmethod
    def parse_gff(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Sequences (##sequence-region) and features (arva_core.annotation shape) of Prokka's GFF3."""
        sequences: list[dict[str, Any]] = []
        rows = []
        for line in text.splitlines():
            if line.startswith("##FASTA"):
                break
            if line.startswith("##sequence-region"):
                parts = line.split()
                if len(parts) != 4:
                    raise ValueError(f"unexpected ##sequence-region line: {line[:80]}")
                sequences.append({"id": parts[1], "original_id": parts[1], "length": int(parts[3])})
                continue
            if not line.strip() or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) != 9:
                raise ValueError(f"a GFF3 line has {len(cols)} columns instead of 9: {line[:80]}")
            if cols[2] not in _SKIP_TYPES:
                rows.append(cols)
        lengths = {s["id"]: s["length"] for s in sequences}
        features = []
        for i, cols in enumerate(rows, 1):
            attrs = gff3_attributes(cols[8])
            kind = TYPES.get(cols[2], "other")
            start, end = int(cols[3]), int(cols[4])
            xrefs = [*attrs.get("db_xref", []), *(f"EC:{e}" for e in attrs.get("eC_number", attrs.get("EC_number", [])))]
            inference = attrs.get("inference", [])
            if cols[1].startswith("barrnap") and not inference:
                inference = [f"barrnap {cols[1].split(':', 1)[-1]}" + (f", E-value {cols[5]}" if cols[5] != "." else "")]
            product = _first(attrs, "product")
            features.append(new_feature(
                id=i, tool_id=_first(attrs, "ID"), locus_tag=_first(attrs, "locus_tag"), type=kind, tool_type=cols[2], contig=cols[0],
                start=start, end=end, strand=cols[6], length=span_length(start, end, False, lengths.get(cols[0])),
                gene=_first(attrs, "gene"), product=product, db_xrefs=xrefs, **sort_xrefs(xrefs),
                hypothetical=product == "hypothetical protein" if kind == "cds" else None,
                inference=inference,
                accessions=[f"{m.group(1)}:{m.group(2)}" for x in inference if (m := _SIMILAR.search(x))],
            ))
        return sequences, features
