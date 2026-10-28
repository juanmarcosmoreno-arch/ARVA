"""Bakta — annotation of bacterial genomes, plasmids and MAGs with a versioned database.

Verified against Bakta 1.12.2 (PyPI wheel bakta-1.12.2-py3-none-any.whl, sha256 1b3725a3b4bc1c7c…): its --help, the
source of bakta/main.py, config.py, utils.py, constants.py, io/*.py and features/*.py, and real runs with the light
database 6.0 on SYNTHETIC genomes (Python 3.12.3, Ubuntu 24.04):

* At start-up Bakta checks a program for each workflow step that will run (utils.test_dependencies, see
  DEPENDENCIES) and exits when one is missing, fails or is older than it requires, naming the --skip-* options of
  the steps that need it. CDS annotation needs AMRFinderPlus >= 4.2.7 (and its database in
  <db>/amrfinderplus-db/latest), Pyrodigal, PyHMMER and DIAMOND >= 2.2.0; ARVA runs the same checks before a run
  and passes the skip options of the steps that cannot run, recording why.
* PILER-CR: when it fails during the run, Bakta prints "WARNING: PILER-CR crashed (error code=N). No CRISPR arrays
  will be reported!" and continues (features/crispr.py), so that run's CRISPR count would mean nothing. Ubuntu
  24.04's pilercr 1.06+dfsg-5 passes Bakta's version check but crashes (SIGSEGV) on every non-empty input, so ARVA
  also runs PILER-CR on a short test sequence and skips the CRISPR step when it fails.
* With the light database Bakta itself skips the UPS/IPS lookup and pseudogene detection (main.py).
* Bakta reads completeness, topology and replicon type from words in FASTA descriptions ("circular=true",
  "complete", "chromosome", "plasmid"; utils.qc_sequences). ARVA passes contigs without descriptions, so only
  --complete marks replicons complete; with it Bakta calls every sequence circular and types it by length
  (>= 2.8 Mb chromosome, < 112 kb plasmid, otherwise contig).
* Without --keep-contig-headers Bakta names the sequences contig_1, contig_2, … and keeps the original names in
  its JSON (sequences[].orig_id).
* --tmp-dir must exist; Bakta makes a temporary folder inside it and removes it at exit. The output folder must not
  exist. Stage lines go to standard output, which Python buffers when it is a file (hence PYTHONUNBUFFERED=1).
* Bakta's "coding_ratio" statistic counts the bases of every feature, gaps included (utils.calc_genome_stats); ARVA
  shows it as Bakta's and computes coding density from CDS only.
* --gram only sets metadata in 1.12.2, so ARVA does not pass it. The circular plot (pyCirclize) is drawn offline.
* For CDS, Bakta's GFF3 writes "ab initio prediction:Pyrodigal:3.5" whatever Pyrodigal version ran (io/gff.py);
  ARVA records the version its dependency check found.
"""
from __future__ import annotations

import random
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_core.annotation import new_feature, sort_xrefs, span_length

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help
from arva_tools.nanoplot import python_of
from arva_tools.runner import isolated_home, tool_environment

PREFIX = "annotation"
OUT_DIR = "bakta"
TMP_DIR = "bakta-tmp"
CONSOLE_LOG = "bakta.console.log"
ENVIRONMENT = {"PYTHONUNBUFFERED": "1"}
TRANSLATION_TABLES = (11, 4, 25)
STEPS = ("trna", "tmrna", "rrna", "ncrna", "ncrna_region", "crispr", "cds", "pseudo", "sorf", "gap", "ori", "plot")
SKIP_FLAGS = {"trna": "--skip-trna", "tmrna": "--skip-tmrna", "rrna": "--skip-rrna", "ncrna": "--skip-ncrna",
              "ncrna_region": "--skip-ncrna-region", "crispr": "--skip-crispr", "cds": "--skip-cds",
              "pseudo": "--skip-pseudo", "sorf": "--skip-sorf", "gap": "--skip-gap", "ori": "--skip-ori",
              "plot": "--skip-plot"}
# Files Bakta writes as <prefix>.<suffix> (main.py), by ARVA's name for them.
OUTPUTS = {"json": "json", "tsv": "tsv", "gff3": "gff3", "genbank": "gbff", "embl": "embl", "fna": "fna",
           "ffn": "ffn", "faa": "faa", "inference": "inference.tsv", "hypotheticals": "hypotheticals.tsv",
           "hypotheticals_faa": "hypotheticals.faa", "summary": "txt", "log": "log", "plot_png": "png",
           "plot_svg": "svg"}
REQUIRED_OUTPUTS = ("json", "tsv", "gff3", "genbank", "fna", "ffn", "faa", "summary")
_PY = "{python}"


@dataclass(frozen=True)
class Dependency:
    name: str
    command: tuple[str, ...]
    minimum: tuple[int, int, int]
    steps: tuple[str, ...]


# bakta/utils.py of Bakta 1.12.2: the command, minimum version and steps of every start-up check.
DEPENDENCIES = (
    Dependency("tRNAscan-SE", ("tRNAscan-SE", "-h"), (2, 0, 12), ("trna",)),
    Dependency("Aragorn", ("aragorn", "-h"), (1, 2, 41), ("tmrna",)),
    Dependency("Infernal (cmscan)", ("cmscan", "-h"), (1, 1, 5), ("rrna", "ncrna", "ncrna_region")),
    Dependency("PILER-CR", ("pilercr", "-options"), (1, 6, 0), ("crispr",)),
    Dependency("Pyrodigal", (_PY, "-c", "import pyrodigal; print(pyrodigal.__version__)"), (3, 7, 0), ("cds",)),
    Dependency("AMRFinderPlus", ("amrfinder", "--version"), (4, 2, 7), ("cds",)),
    Dependency("PyHMMER", (_PY, "-c", "import pyhmmer; print(pyhmmer.__version__)"), (0, 12, 0), ("cds", "sorf")),
    Dependency("DIAMOND", ("diamond", "help"), (2, 2, 0), ("cds", "sorf")),
    Dependency("BLAST+ (blastn)", ("blastn", "-version"), (2, 17, 0), ("ori",)),
    Dependency("pyCirclize", (_PY, "-c", "import pycirclize; print(pycirclize.__version__)"), (1, 7, 0), ("plot",)),
)
_DEP_VERSION = re.compile(r"(\d+)\.(\d+)(?:[.-](\d+))?")
_AMRFINDER_NO_DB = "No valid AMRFinder database found"

# Stage lines on Bakta's standard output (main.py): the step they start or skip.
_STAGE_LINES = {
    "Parse genome sequences...": "parse",
    "predict tRNAs...": "trna", "skip tRNA prediction...": "trna",
    "predict tmRNAs...": "tmrna", "skip tmRNA prediction...": "tmrna",
    "predict rRNAs...": "rrna", "skip rRNA prediction...": "rrna",
    "predict ncRNAs...": "ncrna", "skip ncRNA prediction...": "ncrna",
    "predict ncRNA regions...": "ncrna_region", "skip ncRNA region prediction...": "ncrna_region",
    "predict CRISPR arrays...": "crispr", "skip CRISPR array prediction...": "crispr",
    "predict & annotate CDSs...": "cds", "skip CDS prediction...": "cds",
    "detect & annotate sORF...": "sorf", "skip sORF prediction...": "sorf",
    "detect gaps...": "gap", "skip gap annotation...": "gap",
    "detect oriCs/oriVs...": "ori", "skip oriC/T annotation...": "ori",
    "apply feature overlap filters...": "filter", "skip feature overlap filters...": "filter",
    "select features and create locus tags...": "locus_tags",
    "improve annotations...": "improve",
}
STAGES = ("parse", "trna", "tmrna", "rrna", "ncrna", "ncrna_region", "crispr", "cds", "sorf", "gap", "ori", "filter",
          "locus_tags", "improve", "export")
_FOUND = re.compile(r"^\t(?:found|predicted|detected): (\d+)\s*$")
_CRISPR_CRASH = re.compile(r"PILER-CR crashed \(error code=(-?\d+)\)")
_ERROR = re.compile(r"^(?:ERROR|Error): ?(.+?)\s*$", re.M)
_WARNING = re.compile(r"^\s*WARNING: ?(.+?)\s*$", re.M)

TYPES = {"cds": "cds", "sorf": "sorf", "tRNA": "trna", "tmRNA": "tmrna", "rRNA": "rrna", "ncRNA": "ncrna",
         "ncRNA-region": "ncrna_region", "crispr": "crispr", "gap": "gap", "oriC": "oric", "oriV": "oriv",
         "oriT": "orit"}
# The program behind each feature type: the source column of Bakta's GFF3 (io/gff.py).
METHODS = {"trna": "tRNAscan-SE", "tmrna": "Aragorn", "rrna": "Infernal", "ncrna": "Infernal",
           "ncrna_region": "Infernal", "crispr": "PILER-CR", "cds": "Pyrodigal", "sorf": "Bakta", "gap": "Bakta",
           "oric": "BLAST+", "oriv": "BLAST+", "orit": "BLAST+"}
_PARTIAL = {"5-prime": "5'", "3-prime": "3'", "both": "both", "?": "unknown"}

# Locus-tag prefixes that both Bakta (--compliant rule) and INSDC accept; organism names without characters that
# would end a FASTA header field or a file path.
LOCUS_TAG = re.compile(r"[A-Z][A-Z0-9]{2,11}")
GENUS = re.compile(r"[A-Za-z]{2,50}")
SPECIES = re.compile(r"[A-Za-z][A-Za-z.-]{0,49}")
STRAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,39}")
MAX_MIN_CONTIG = 1_000_000


@dataclass
class BaktaParams:
    locus_tag: str
    translation_table: int = 11
    genus: str | None = None
    species: str | None = None
    strain: str | None = None
    complete: bool = False
    keep_contig_headers: bool = False
    min_contig_length: int = 1
    skip_plot: bool = False
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
                errors.append(f"{name} has characters ARVA does not pass to annotators (letters, digits and "
                              f"{'. -' if name == 'species' else '. _ : / - and spaces' if name == 'strain' else 'no others'})")
        if self.species is not None and self.genus is None:
            errors.append("a species needs a genus")
        if not 1 <= self.min_contig_length <= MAX_MIN_CONTIG:
            errors.append(f"min_contig_length must be between 1 and {MAX_MIN_CONTIG:,}")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _version(text: str) -> tuple[int, int, int] | None:
    m = _DEP_VERSION.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def _fmt(v: tuple[int, int, int] | None) -> str | None:
    return ".".join(map(str, v)) if v else None


def _run(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess | None:
    try:
        with isolated_home() as home:
            return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                                  env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_dependency(dep: Dependency, python: list[str]) -> dict[str, Any]:
    """Bakta's own check of one program: found, runs with status 0, and prints a version >= the minimum."""
    argv = [part for a in dep.command for part in (python if a == _PY else [a])]
    out: dict[str, Any] = {"name": dep.name, "minimum": _fmt(dep.minimum), "steps": list(dep.steps),
                           "command": argv if dep.command[0] != _PY else [Path(python[0]).name, *argv[len(python):]],
                           "found": None}
    # One stream, as Bakta reads it (check_output with stderr=STDOUT): tRNAscan-SE prints its version on stderr
    # before a usage text on stdout that holds other numbers.
    try:
        with isolated_home() as home:
            proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                  timeout=60, env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return {**out, "status": "missing"}
    except (OSError, subprocess.TimeoutExpired):
        return {**out, "status": "failed"}
    if proc.returncode != 0:
        return {**out, "status": "failed", "returncode": proc.returncode}
    version = _version(proc.stdout)
    if version is None:
        return {**out, "status": "unreadable"}
    return {**out, "found": _fmt(version), "status": "ok" if version >= dep.minimum else "too_old"}


def pilercr_test(executable: str = "pilercr") -> dict[str, Any]:
    """Runs PILER-CR as Bakta does on a random 2,000 bp sequence: a working PILER-CR exits with status 0 and writes
    its report (finding nothing)."""
    rng = random.Random(0)
    with tempfile.TemporaryDirectory(prefix="arva-pilercr-") as tmp:
        fasta, report = Path(tmp) / "test.fasta", Path(tmp) / "test.txt"
        fasta.write_text(">arva_test\n" + "".join(rng.choice("ACGT") for _ in range(2000)) + "\n")
        proc = _run([executable, "-in", str(fasta), "-out", str(report), "-noinfo", "-quiet"])
        if proc is None:
            return {"works": False, "returncode": None}
        return {"works": proc.returncode == 0 and report.is_file(), "returncode": proc.returncode}


def amrfinder_database_ok(db_path: Path) -> bool:
    """Bakta's check (utils.test_dependencies) that AMRFinderPlus finds its database in <db>/amrfinderplus-db/latest."""
    proc = _run(["amrfinder", "--debug", "--database", str(db_path / "amrfinderplus-db" / "latest")], timeout=300)
    return proc is not None and _AMRFINDER_NO_DB not in proc.stderr


def check_dependencies(executable: str, db_path: Path | None) -> list[dict[str, Any]]:
    python = python_of(executable)
    if python is None:
        raise RuntimeError(f"{executable} is not a Python entry point, so its Python packages cannot be checked")
    report = [check_dependency(d, python) for d in DEPENDENCIES]
    for r in report:
        if r["name"] == "PILER-CR" and r["status"] == "ok":
            test = pilercr_test()
            if not test["works"]:
                r.update(status="crashed", returncode=test["returncode"])
        if r["name"] == "AMRFinderPlus" and r["status"] == "ok" and db_path is not None \
                and not amrfinder_database_ok(db_path):
            r["status"] = "database_missing"
    return report


def plan_steps(dependencies: list[dict[str, Any]], db_type: str | None, skip_plot: bool) -> dict[str, dict[str, Any]]:
    """For every step: whether it runs and, when not, a reason code and the programs behind it."""
    steps: dict[str, dict[str, Any]] = {s: {"run": True, "reason": None, "dependencies": []} for s in STEPS}
    for d in dependencies:
        if d["status"] != "ok":
            for s in d["steps"]:
                steps[s].update(run=False, reason="dependency")
                steps[s]["dependencies"].append({k: d.get(k) for k in ("name", "status", "found", "minimum",
                                                                       "returncode")})
    if skip_plot and steps["plot"]["run"]:
        steps["plot"].update(run=False, reason="user")
    if not steps["cds"]["run"]:
        steps["pseudo"].update(run=False, reason="needs_cds")
    elif db_type == "light":
        steps["pseudo"].update(run=False, reason="light_database")
    return steps


def skip_options(steps: dict[str, dict[str, Any]]) -> list[str]:
    """The --skip-* options for steps that do not run. Pseudogene detection is left to Bakta when it follows from
    the CDS step or the light database (Bakta skips it itself)."""
    return [SKIP_FLAGS[s] for s in STEPS if not steps[s]["run"] and steps[s]["reason"] in ("dependency", "user")]


def flags(params: BaktaParams, skips: list[str]) -> list[str]:
    used = ["--db", "--output", "--prefix", "--tmp-dir", "--threads", "--min-contig-length", "--translation-table",
            "--locus-tag", "--locus-tag-increment", *skips]
    used += [f for f, v in (("--genus", params.genus), ("--species", params.species), ("--strain", params.strain),
                            ("--complete", params.complete), ("--keep-contig-headers", params.keep_contig_headers))
             if v]
    return used


class BaktaAdapter(ToolAdapter):
    info = ToolInfo(
        id="bakta",
        name="Bakta",
        description="Annotation of bacterial genomes and plasmids with a versioned database: tRNA, tmRNA, rRNA, "
        "ncRNA, CRISPR arrays, CDS and small ORFs with functional annotation by alignment-free identification and "
        "protein clusters, pseudogenes (full database), gaps and origins of replication/transfer.",
        homepage="https://github.com/oschwengers/bakta",
        license="GPL-3.0",
        citation="Schwengers O, Jelonek L, Dieckmann MA, Beyvers S, Blom J, Goesmann A. Bakta: rapid and "
        "standardized annotation of bacterial genomes via alignment-free sequence identification. Microb Genom "
        "2021;7(11). doi:10.1099/mgen.0.000685",
        citation_url="https://doi.org/10.1099/mgen.0.000685",
        executable="bakta",
        categories=("annotation",),
        input_formats=("fasta",),
        output_formats=("gff3", "genbank", "embl", "fasta", "tsv", "json"),
        min_version="1.12.2",
        tested_versions=("1.12.2",),
        install={
            "pip": 'python3 -m venv ~/.arva-tools/bakta && ~/.arva-tools/bakta/bin/pip install "bakta==1.12.2" '
            '"pyrodigal==3.7.1" "pyhmmer==0.12.3" "biopython==1.88" "pycirclize==1.10.1" "xopen==2.1.0"\n'
            "export ARVA_TOOL_BAKTA=~/.arva-tools/bakta/bin/bakta\n"
            "sudo apt install trnascan-se aragorn infernal pilercr diamond-aligner ncbi-blast+  # Bakta's programs",
        },
    )
    version_pattern = re.compile(r"bakta (\d+\.\d+\.\d+)")

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(read_help(executable))

    @staticmethod
    def argv(executable: str, params: BaktaParams, genome: Path, db: Path, out_dir: Path, tmp_dir: Path,
             skips: list[str], supported: frozenset[str]) -> list[str]:
        params.validate()
        if unknown := [s for s in skips if s not in SKIP_FLAGS.values()]:
            raise ValueError(f"unknown skip options: {', '.join(unknown)}")
        if missing := [f for f in flags(params, skips) if f not in supported]:
            raise ValueError(f"this Bakta version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, str(genome), "--db", str(db), "--output", str(out_dir), "--prefix", PREFIX,
             "--tmp-dir", str(tmp_dir), "--threads", str(params.threads),
             "--min-contig-length", str(params.min_contig_length), "--translation-table", str(params.translation_table),
             "--locus-tag", params.locus_tag, "--locus-tag-increment", "1"]
        for flag, value in (("--genus", params.genus), ("--species", params.species), ("--strain", params.strain)):
            if value is not None:
                a += [flag, value]
        if params.complete:
            a.append("--complete")
        if params.keep_contig_headers:
            a.append("--keep-contig-headers")
        return a + [f for f in SKIP_FLAGS.values() if f in skips]

    @staticmethod
    def stage(line: str) -> str | None:
        text = line.strip()
        return "export" if text.startswith("Export annotation results to:") else _STAGE_LINES.get(text)

    @staticmethod
    def parse_console(text: str) -> dict[str, Any]:
        """Steps Bakta ran or skipped (in order), the count it printed after each, warnings and errors."""
        ran, skipped, found, current = [], [], {}, None
        for line in text.splitlines():
            if (stage := _STAGE_LINES.get(line.strip())) is not None:
                current = stage
                (skipped if line.strip().startswith("skip") else ran).append(stage)
            elif current and (m := _FOUND.match(line)) and current not in found:
                found[current] = int(m.group(1))
        crash = _CRISPR_CRASH.search(text)
        return {"ran": ran, "skipped": skipped, "found": found,
                "warnings": list(dict.fromkeys(m.group(1) for m in _WARNING.finditer(text))),
                "errors": [m.group(1) for m in _ERROR.finditer(text)],
                "crispr_crashed": int(crash.group(1)) if crash else None,
                "finished": "Annotation successfully finished" in text}

    @staticmethod
    def failure_reason(console: str, returncode: int | None) -> str | None:
        errors = [m.group(1) for m in _ERROR.finditer(console)]
        if errors:
            return f"Bakta stopped: {errors[-1]}"
        if returncode in (-9, 137):
            return "Bakta was stopped by the operating system (out of memory)"
        return None

    @staticmethod
    def parse_json(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Sequences, features (arva_core.annotation shape) and run facts from Bakta's JSON."""
        try:
            raw_sequences, raw_features = data["sequences"], data["features"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Bakta JSON lacks {exc}") from None
        sequences = [{"id": s["id"], "original_id": s.get("orig_id", s["id"]), "length": int(s["length"]),
                      "topology": s.get("topology"), "replicon_type": s.get("type"), "complete": s.get("complete")}
                     for s in raw_sequences]
        lengths = {s["id"]: s["length"] for s in sequences}
        features = [_feature(i, f, lengths) for i, f in enumerate(raw_features, 1)]
        meta = {"genome": data.get("genome"), "stats": data.get("stats"), "version": data.get("version"),
                "run": data.get("run")}
        return sequences, features, meta


def _num(value: Any, fmt: str) -> str | None:
    return format(value, fmt) if isinstance(value, int | float) else None


def _hit(label: str, hit: dict[str, Any], ident: str | None) -> str:
    parts = [f"{label}{f' {ident}' if ident else ''}"]
    for key, name, fmt in (("identity", "identity", ".3f"), ("query_cov", "query coverage", ".3f"),
                           ("subject_cov", "subject coverage", ".3f"), ("evalue", "E-value", ".2g"),
                           ("score", "score", ".1f")):
        if (v := _num(hit.get(key), fmt)) is not None:
            parts.append(f"{name} {v}")
    return ", ".join(parts)


def _evidence(kind: str, f: dict[str, Any]) -> list[str]:
    method = METHODS.get(kind, "Bakta")
    if kind in ("cds", "sorf"):
        out = ["ab initio prediction: Pyrodigal" if kind == "cds" else "Bakta sORF detection"]
        for hit in f.get("expert") or []:
            out.append(_hit(f"expert system {hit.get('type', '?')} (rank {hit.get('rank', '?')})", hit, None))
        if ups := f.get("ups"):
            out.append(f"UPS: identical sequence in UniParc {ups.get('uniparc_id', '?')}")
        if ips := f.get("ips"):
            out.append(f"IPS: identical sequence in UniRef100 {ips.get('uniref100_id', '?')}")
        if psc := f.get("psc"):
            out.append(_hit("PSC: protein sequence cluster UniRef90", psc, psc.get("uniref90_id")))
        if pscc := f.get("pscc"):
            out.append(_hit("PSCC: protein sequence cluster of clusters UniRef50", pscc, pscc.get("uniref50_id")))
        if f.get("hypothetical"):
            out.append("no function assigned (hypothetical)")
        return out
    if kind == "trna":
        detail = [f"amino acid {f['amino_acid']}"] if f.get("amino_acid") else []
        detail += [f"anticodon {f['anti_codon']}"] if f.get("anti_codon") else []
        return [_hit(method, f, None) + (f", {', '.join(detail)}" if detail else "")]
    if kind in ("rrna", "ncrna", "ncrna_region"):
        rfam = next((x.split(":", 1)[1] for x in f.get("db_xrefs") or [] if x.startswith("RFAM:")), None)
        text = _hit(f"{method}: Rfam model {rfam}" if rfam else method, {**f, "query_cov": None}, None)
        return [text + (f", model coverage {_num(f['coverage'], '.3f')}" if _num(f.get("coverage"), ".3f") else "")]
    if kind == "crispr":
        return [f"{method}: {len(f.get('repeats') or [])} repeats, {len(f.get('spacers') or [])} spacers"]
    if kind == "gap":
        return ["Bakta: run of N in the sequence"]
    return [_hit(method, f, None)]


def _feature(index: int, f: dict[str, Any], lengths: dict[str, int]) -> dict[str, Any]:
    kind = TYPES.get(f.get("type", ""), "other")
    contig = f.get("sequence", f.get("contig", ""))
    start, end, edge = int(f["start"]), int(f["stop"]), bool(f.get("edge"))
    xrefs = [str(x) for x in f.get("db_xrefs") or []]
    return new_feature(
        id=index, tool_id=f.get("id"), locus_tag=f.get("locus"), type=kind, tool_type=f.get("type"),
        contig=contig, start=start, end=end, strand=f.get("strand", "."), edge=edge,
        length=span_length(start, end, edge, lengths.get(contig)),
        gene=f.get("gene") or None, product=f.get("product") or None, db_xrefs=xrefs, **sort_xrefs(xrefs),
        pseudo="pseudogene" in f, partial=_PARTIAL.get(f["truncated"], "unknown") if f.get("truncated") else None,
        hypothetical=bool(f.get("hypothetical")) if kind in ("cds", "sorf") else None,
        inference=_evidence(kind, f),
    )
