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
  also runs PILER-CR on a short test sequence and skips the CRISPR step when it fails. Bioconda's piler-cr 1.06
  (in ARVA's Bakta environment, docker/conda-locks/bakta/) passes that test.
* Bakta calls every program by name from PATH (and AMRFinderPlus with TMPDIR), so ARVA puts the bin/ folder of
  Bakta's own environment first in PATH for the checks and the run (env_for).
* The AMR expert system runs `amrfinder --database <db>/amrfinderplus-db/latest --protein ... --plus`
  (expert/amrfinder.py) and raises an error when amrfinder fails; Bakta's start-up check only looks for "No valid
  AMRFinder database found". AMRFinderPlus 4.2.7 refuses data older than 2025-09-22.2, such as the 2024-12-18.1
  copy inside the light database 6.0, so ARVA checks the copy with `amrfinder --database_version` and, when it is
  refused, gives Bakta a view of the database (compose_database) whose amrfinderplus-db/latest is an AMRFinderPlus
  database ARVA installed; without one the CDS step is skipped.
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

import datetime as dt
import os
import random
import re
import shutil
import struct
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

# Standard library and arva_tools.{base,runner,nanoplot,amrfinderplus,native_common} only at import time: ARVA.app
# runs this module on the Mac (the native entry, below) without arva_core, which parse_json imports when it runs.
from arva_tools.base import (
    DetectedTool,
    ToolAdapter,
    ToolInfo,
    ToolStatus,
    conda_platform,
    help_options,
    read_help,
)
from arva_tools.nanoplot import python_of
from arva_tools.native_common import (
    NativeRefusal,
    NativeStopped,
    check_storage,
    conda_package,
    mac_facts,
    native_folder,
    native_path,
    native_program,
    native_relative,
    sha256_file,
)
from arva_tools.runner import ToolExecutionError, isolated_home, run_command, tool_environment

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
# Bakta 1.12 runs DIAMOND itself (bakta/psc.py, pscc.py: "--block-size 3") and, when it fails, raises
# Exception(f'diamond error! error code: {proc.returncode}'); -9 is the kernel's SIGKILL (out of memory).
_DIAMOND_KILLED = re.compile(r"diamond error! error code: (?:-9|137)\b")
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


def env_for(executable: str) -> dict[str, str]:
    """PATH with the bin/ folder of Bakta's own environment first: Bakta runs its programs by name."""
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def _run(argv: list[str], timeout: int = 60, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess | None:
    try:
        with isolated_home() as home:
            return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                                  env={**tool_environment(home), **(extra_env or {})}, cwd=home,
                                  stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_dependency(dep: Dependency, python: list[str], extra_env: dict[str, str] | None = None) -> dict[str, Any]:
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
                                  timeout=60, env={**tool_environment(home), **(extra_env or {})}, cwd=home,
                                  stdin=subprocess.DEVNULL)
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


def pilercr_test(executable: str = "pilercr", extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Runs PILER-CR as Bakta does on a random 2,000 bp sequence: a working PILER-CR exits with status 0 and writes
    its report (finding nothing)."""
    rng = random.Random(0)
    with tempfile.TemporaryDirectory(prefix="arva-pilercr-") as tmp:
        fasta, report = Path(tmp) / "test.fasta", Path(tmp) / "test.txt"
        fasta.write_text(">arva_test\n" + "".join(rng.choice("ACGT") for _ in range(2000)) + "\n")
        proc = _run([executable, "-in", str(fasta), "-out", str(report), "-noinfo", "-quiet"], extra_env=extra_env)
        if proc is None:
            return {"works": False, "returncode": None}
        return {"works": proc.returncode == 0 and report.is_file(), "returncode": proc.returncode}


def amrfinder_data(db_path: Path) -> Path:
    """The AMRFinderPlus database Bakta's AMR expert system reads."""
    return db_path / "amrfinderplus-db" / "latest"


def amrfinder_database_check(folder: Path, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    """amrfinder's own check of the AMRFinderPlus data Bakta would read (`--database_version`): missing (Bakta's
    "No valid AMRFinder database found"), refused (data too old for this AMRFinderPlus, or not indexed) or ok."""
    from arva_tools.amrfinderplus import failure

    proc = _run(["amrfinder", "--database", str(folder), "--database_version"], timeout=300, extra_env=extra_env)
    if proc is None:
        return {"status": "failed", "version": None, "error": None}
    text = proc.stdout + "\n" + proc.stderr
    version = re.search(r"^Database version:\s*(\S+)", text, re.M)
    if proc.returncode == 0:
        return {"status": "ok", "version": version.group(1) if version else None, "error": None}
    if _AMRFINDER_NO_DB in text:
        return {"status": "database_missing", "version": None, "error": failure(text)}
    return {"status": "database_refused", "version": version.group(1) if version else None, "error": failure(text)}


def check_dependencies(executable: str, db_path: Path | None, amr_data: Path | None = None) -> list[dict[str, Any]]:
    """Bakta's start-up checks with the programs of Bakta's environment; the AMRFinderPlus data checked are those of
    the database (amrfinderplus-db/latest) unless `amr_data` names the folder ARVA will put there instead."""
    python = python_of(executable)
    if python is None:
        raise RuntimeError(f"{executable} is not a Python entry point, so its Python packages cannot be checked")
    env = env_for(executable)
    report = [check_dependency(d, python, env) for d in DEPENDENCIES]
    for r in report:
        if r["name"] == "PILER-CR" and r["status"] == "ok":
            test = pilercr_test(shutil.which("pilercr", path=env["PATH"]) or "pilercr", env)
            if not test["works"]:
                r.update(status="crashed", returncode=test["returncode"])
        if r["name"] == "AMRFinderPlus" and r["status"] == "ok" and db_path is not None:
            check = amrfinder_database_check(amr_data or amrfinder_data(db_path), env)
            r["database"] = {**check, "path": str(amr_data or amrfinder_data(db_path)), "replaced": amr_data is not None}
            if check["status"] != "ok":
                r["status"] = check["status"]
    return report


def compose_database(db_path: Path, amr_data: Path, dest: Path) -> Path:
    """A folder Bakta reads as its database: a link to every entry of `db_path` but amrfinderplus-db, and
    amrfinderplus-db/<version> linking to `amr_data` with latest -> <version>. Nothing in either database changes."""
    version = (amr_data / "version.txt").read_text(errors="replace").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", version):
        raise ValueError(f"{amr_data} has no AMRFinderPlus version.txt")
    dest.mkdir(parents=True)
    for entry in sorted(db_path.iterdir()):
        if entry.name != "amrfinderplus-db":
            os.symlink(entry, dest / entry.name)
    (dest / "amrfinderplus-db").mkdir()
    os.symlink(amr_data, dest / "amrfinderplus-db" / version)
    os.symlink(version, dest / "amrfinderplus-db" / "latest")
    return dest


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
        install={"conda_lock": "python3 scripts/conda_locks.py install bakta ~/.arva-tools/conda/bakta  # then "
                               "ARVA_TOOL_BAKTA=~/.arva-tools/conda/bakta/bin/bakta (Bakta and every program it runs)"},
        conda_platforms=("linux-64", "osx-arm64"),
    )
    version_pattern = re.compile(r"bakta (\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available or d.path is None:
            return d
        try:
            deps = check_dependencies(d.path, None)
        except RuntimeError as exc:
            d.message = f"{d.message}. {exc}" if d.message else str(exc)
            return d
        steps = plan_steps(deps, None, skip_plot=False)
        off = [s for s in STEPS if not steps[s]["run"] and steps[s]["reason"] == "dependency"]
        if off:
            d.reason = "bakta_steps_skipped"
            names = sorted({x["name"] for s in off for x in steps[s]["dependencies"]})
            note = (f"Steps that cannot run on this computer: {', '.join(off)} (programs missing, too old or crashing: "
                    f"{', '.join(names)}); ARVA skips them with Bakta's own options and records why")
            d.message = f"{d.message}. {note}" if d.message else note
        return d

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
    def failure_reason(console: str, returncode: int | None, native: bool = False) -> str | None:
        """Bakta's own reason for a failed run. `native`: the run was on the Mac (ARVA.app), not in Docker."""
        if _DIAMOND_KILLED.search(console):
            if native:
                return ("DIAMOND, the protein search Bakta runs against its database, was stopped by macOS (out of "
                        "memory) although Bakta ran directly on this Mac. Bakta sets DIAMOND's block size itself (3), "
                        "so its memory cannot be lowered from ARVA: close other applications (Docker Desktop's "
                        "virtual machine keeps its memory while it is open), or annotate with Bakta's light database")
            return ("DIAMOND, the protein search Bakta runs against its database, was stopped by the operating system "
                    "(out of memory). Bakta sets DIAMOND's block size itself (3), so its memory cannot be lowered from "
                    "ARVA: give Docker Desktop more memory, or annotate with Bakta's light database, which is much "
                    "smaller")
        errors = [m.group(1) for m in _ERROR.finditer(console)]
        if errors:
            return f"Bakta stopped: {errors[-1]}"
        if returncode in (-9, 137):
            return "Bakta was stopped by the operating system (out of memory)"
        return None

    @staticmethod
    def out_of_memory(console: str, returncode: int | None) -> bool:
        """Whether Bakta, or the DIAMOND search it runs, was killed by the operating system."""
        return bool(_DIAMOND_KILLED.search(console)) or returncode in (-9, 137)

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
    from arva_core.annotation import (  # not on the Mac (see the imports)
        new_feature,
        sort_xrefs,
        span_length,
    )

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


# --- Memory: DIAMOND's reference block (log item 49) ------------------------------------------------------------------
#
# Bakta 1.12.2 runs DIAMOND itself with "--block-size 3" (psc.py, pscc.py, features/s_orf.py) and has no option to
# change it. DIAMOND processes the reference in blocks of up to block-size billion letters ("Block size in billions of
# sequence letters to be processed at a time. This is the main parameter for controlling the program's memory";
# DIAMOND wiki, "3. Command line options"), so one search needs memory for one block: the whole database when it has
# fewer than 3 billion letters. Each .dmnd file says how many letters it holds in its header (DIAMOND's
# ReferenceHeader: magic number, build, database version, sequences, letters; checked against the sequences and
# letters DIAMOND 2.2.8 prints for the light database 6.0). Bakta runs its searches one after another, so the largest
# block decides.
#
# Bytes per letter: measured by ARVA, not documented. DIAMOND 2.2.8 (linux-64, ARVA's Bakta lock) with Bakta's exact
# pscc arguments (--fast --block-size 3, --id 50, --query-cover 80, --subject-cover 80, --max-target-seqs 1) on the
# light database 6.0 pscc.dmnd (1,245,018,838 letters, one block) and the 2,646 proteins of S. aureus N315
# (GCF_000011265.1): peak resident memory 2,933,644 KiB with 2 threads and 2,932,388 KiB with 4 (identical hits), so
# about 2.41 bytes per reference letter, independent of the thread count. DIAMOND's documentation gives a rougher
# upper figure, "roughly six times this number of memory (in GB)" for a block-size, which ARVA does not use: it would
# say the light database cannot run in 5.9 GB, and on the user's Mac it did (log item 53).
# Checked against the user's Mac (Docker with 5.9 GB): the light database 6.0 ran (item 53; estimate 2.8 GB); the
# full database 6.0 had DIAMOND killed for lack of memory (item 49; its psc.dmnd is not here to read, but a block of 3
# billion letters gives 6.7 GB). GB here are of 1024^3 bytes, like the container memory ARVA shows.
DIAMOND_BLOCK_LETTERS = 3_000_000_000
DIAMOND_DATABASES = ("psc.dmnd", "pscc.dmnd", "sorf.dmnd", "expert-protein-sequences.dmnd")
DIAMOND_MAGIC = 0x24AF8A415EE186D
DIAMOND_MEASUREMENT = {"diamond": "2.2.8", "platform": "linux-64", "database": "Bakta light 6.0 pscc.dmnd",
                       "letters": 1_245_018_838, "peak_rss_bytes": 3_004_051_456, "threads": [2, 4],
                       "query": "2,646 proteins of S. aureus N315 (GCF_000011265.1)"}
DIAMOND_BYTES_PER_LETTER = round(DIAMOND_MEASUREMENT["peak_rss_bytes"] / DIAMOND_MEASUREMENT["letters"], 2)
# Room for Bakta's own process (it stays alive while DIAMOND runs) and the rest of the container. An allowance, not a
# measurement: within it the verdict is "tight".
MEMORY_HEADROOM_GB = 1.0
# Memory in GB of 1024^3 bytes, the unit ARVA's container memory is in (app.services.performance); letters in billions.
GIB = 1024**3


def diamond_header(path: Path) -> dict[str, int] | None:
    """Sequences and letters of a DIAMOND database (.dmnd) from its header; None when it is not one."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(32)
    except OSError:
        return None
    if len(raw) < 32:
        return None
    magic, build, db_version, sequences, letters = struct.unpack("<QIIQQ", raw)
    if magic != DIAMOND_MAGIC:
        return None
    return {"build": build, "db_version": db_version, "sequences": sequences, "letters": letters}


def memory_estimate(db_path: Path | None, container_gb: float | None) -> dict[str, Any]:
    """Whether Bakta's DIAMOND searches with this database fit the memory the container (or computer) has, by ARVA's
    estimate: the largest reference block (letters of the largest .dmnd Bakta searches, at most 3 billion) times the
    bytes per letter ARVA measured (DIAMOND_MEASUREMENT). verdict: "fits" (with MEMORY_HEADROOM_GB to spare), "tight"
    (fits without that room), "may_not_fit" (the estimate exceeds the container's memory), or "unknown" (no DIAMOND
    database readable, or no memory known)."""
    databases = []
    for name in DIAMOND_DATABASES:
        header = diamond_header(db_path / name) if db_path is not None else None
        if header is not None:
            databases.append({"file": name, "sequences": header["sequences"], "letters": header["letters"],
                              "block_letters": min(header["letters"], DIAMOND_BLOCK_LETTERS)})
    out: dict[str, Any] = {"databases": databases, "block_size": DIAMOND_BLOCK_LETTERS // 1_000_000_000,
                           "block_letters": None, "largest": None, "bytes_per_letter": DIAMOND_BYTES_PER_LETTER,
                           "measurement": DIAMOND_MEASUREMENT, "headroom_gb": MEMORY_HEADROOM_GB,
                           "estimate_gb": None, "container_gb": container_gb, "verdict": "unknown"}
    if not databases:
        return out
    largest = max(databases, key=lambda d: d["block_letters"])
    estimate = round(largest["block_letters"] * DIAMOND_BYTES_PER_LETTER / GIB, 1)
    out.update(block_letters=largest["block_letters"], largest=largest["file"], estimate_gb=estimate)
    if container_gb is None:
        return out
    out["verdict"] = ("may_not_fit" if estimate > container_gb else
                      "tight" if estimate + MEMORY_HEADROOM_GB > container_gb else "fits")
    return out


# --- Native run on the user's Mac (ARVA.app; docs/plan-flye-nativo.md, "Contrato implementado" and "Bakta") ----------
#
# The full database's DIAMOND block does not fit Docker Desktop's VM on an 8 GB Mac (log item 49), and Bakta has no
# option for it; natively macOS compresses and swaps memory (the user's own Bakta 1.11.4 ran with the full database
# 6.0 on the same Mac, item 51). ARVA.app then runs this module with the Python of the osx-arm64 Bakta environment
# (created only from NATIVE_LOCK's lock file) through arva_tools/native.py. The work record carries structured
# parameters, paths relative to the data folder or to a database folder named in arva.conf, the skip options the user
# confirmed and the argument vector the API built for the Mac. This module checks the programs of the Mac's Bakta
# environment again (the same start-up checks as in Docker), refuses to run when the steps that can run differ from
# the confirmed ones, builds the argument vector itself with the same BaktaAdapter.argv, and runs only an identical
# one. Nothing in the work record is executed as given.

# The lock ARVA.app installs from (scripts/conda_locks.py update bakta --platform osx-arm64, 2026-11-06: 140 packages,
# 296.2 MB): its SHA-256 and the Bakta package it pins (noarch, the same file as the Linux lock). A test checks both
# against docker/conda-locks/bakta/osx-arm64.lock.
NATIVE_LOCK = {
    "platform": "osx-arm64",
    "lock": "docker/conda-locks/bakta/osx-arm64.lock",
    "lock_sha256": "8a302d44802fc18019bef6e81d46adc4228c8bcf66d1a40605f0e6978b21205b",
    "package": "bakta-1.12.2-pyhdfd78af_0.conda",
    "version": "1.12.2",
    "build": "pyhdfd78af_0",
    "package_sha256": "8bc71bb2ac0e302263deaebb49c3e37b05455f882e1c156da64f6393297d615d",
    "subdir": "noarch",
}
# Inside the job's tmp-dir: the database view whose amrfinderplus-db/latest is the AMRFinderPlus data ARVA chose
# (compose_database), made on the Mac with the Mac's paths.
COMPOSED_DB = "database"
DATABASE_TYPES = ("light", "full")
NATIVE_WORK_KEYS = ("tool", "storage_id", "data_dir", "executable", "params", "genome", "out_dir", "tmp_dir",
                    "results_dir", "console_log", "database", "amr_data", "database_type", "skip_options", "argv")


def native_data_dir(path: Any) -> str:
    """The data folder as given (absolute, normalised, without spaces)."""
    return native_folder(path, "Bakta")


def native_executable(path: Any) -> str:
    return native_program(path, "bakta")


def native_database(ref: Any, database_dirs: list[str] | None) -> str:
    """The Mac path of a database given as {"root": a database folder of arva.conf, "rel": a path inside it}: the root
    must be one of `database_dirs` (ARVA.app's arva.conf), the path must exist and stay inside it once links are
    resolved. With database_dirs None (the API's side, which cannot see the Mac's folders), the form only."""
    if not isinstance(ref, dict) or set(ref) != {"root", "rel"}:
        raise NativeRefusal("work_incomplete", "a database must be given as its folder and a path inside it")
    root = native_folder(ref["root"], "Bakta", "a database folder")
    rel = native_relative(ref["rel"])
    if database_dirs is None:
        return f"{root}/{rel}"
    if root not in {os.path.normpath(d) for d in database_dirs}:
        raise NativeRefusal("database_folder_unknown", f"{root} is not a database folder of this Mac's ARVA "
                                                       "(arva.conf: ARVA_DATABASES_DIR, ARVA_ADD_DATABASES)")
    try:
        return native_path(root, rel, what="the database folder")
    except NativeRefusal as exc:
        raise NativeRefusal("outside_database_dir" if exc.code == "outside_data_dir" else exc.code, str(exc)) from None


def _inside(rel: str, results_dir: str) -> None:
    if not rel.startswith(results_dir + "/"):
        raise NativeRefusal("unsafe_path", f"{rel} is not inside the job's folder {results_dir}")


def native_expected_argv(params: BaktaParams, data_dir: str, executable: str, genome: str, database: dict[str, str],
                         amr_data: dict[str, str] | None, out_dir: str, tmp_dir: str, skips: list[str],
                         supported: frozenset[str]) -> list[str]:
    """The argument vector of a native run, built by the API for the work record (paths checked for form only): the
    Docker run's BaktaAdapter.argv with the Mac's paths; --db is the database itself, or the composed view inside
    tmp-dir when AMRFinderPlus data replaces the database's own copy."""
    data_dir, executable = native_data_dir(data_dir), native_executable(executable)
    db = native_database(database, None)
    if amr_data is not None:
        native_database(amr_data, None)
        db = f"{data_dir}/{native_relative(tmp_dir)}/{COMPOSED_DB}"
    return BaktaAdapter.argv(executable, params, Path(f"{data_dir}/{native_relative(genome)}"), Path(db),
                             Path(f"{data_dir}/{native_relative(out_dir)}"), Path(f"{data_dir}/{native_relative(tmp_dir)}"),
                             skips, supported)


def _bakta_version(executable: str) -> str | None:
    with isolated_home() as home:
        proc = subprocess.run([executable, "--version"], capture_output=True, text=True, errors="replace",
                              timeout=120, env={**tool_environment(home), **env_for(executable)}, cwd=home,
                              stdin=subprocess.DEVNULL)
    text = (proc.stdout + proc.stderr).strip()
    return text.splitlines()[0] if proc.returncode == 0 and text else None


def native_facts(executable: str, lock: str | None = None) -> dict[str, Any]:
    """What ARVA.app reports about its Bakta when it registers: version (bakta --version), the installed package's
    build and SHA-256, the SHA-256 of the lock it was created from, the options of its --help, Bakta's start-up checks
    of the programs of its environment (without a database), and the Mac."""
    native_executable(executable)
    try:
        dependencies = [{k: d.get(k) for k in ("name", "status", "found", "minimum", "steps")}
                        for d in check_dependencies(executable, None)]
    except RuntimeError:
        dependencies = []
    return {
        "tool": "bakta",
        "executable": executable,
        "version": _bakta_version(executable),
        "package": conda_package(executable, "bakta"),
        "lock_sha256": sha256_file(Path(lock)) if lock else None,
        "help_options": sorted(BaktaAdapter.help_options(executable)),
        "dependencies": dependencies,
        **mac_facts(conda_platform()),
    }


def _params(work: dict[str, Any]) -> BaktaParams:
    try:
        return BaktaParams(**{f.name: work["params"][f.name] for f in fields(BaktaParams)})
    except (KeyError, TypeError) as exc:
        raise NativeRefusal("settings_rejected", f"the work's Bakta settings are incomplete: {exc}") from None


def _check_work(work: Any, data_dir: str, executable: str) -> None:
    if not isinstance(work, dict) or work.get("tool") != "bakta":
        raise NativeRefusal("not_bakta_work", "the work record is not a Bakta run")
    if missing := [k for k in NATIVE_WORK_KEYS if k not in work]:
        raise NativeRefusal("work_incomplete", f"the work record lacks {', '.join(missing)}")
    if work["data_dir"] != data_dir:
        raise NativeRefusal("other_data_dir", f"the work is for the data folder {work['data_dir']}, this Mac's "
                                              f"ARVA uses {data_dir}")
    if work["executable"] != executable:
        raise NativeRefusal("other_executable", f"the work names {work['executable']}, this Mac's Bakta is "
                                                f"{executable}")
    if not isinstance(work["params"], dict) or not isinstance(work["argv"], list) \
            or not isinstance(work["skip_options"], list) or work["database_type"] not in (*DATABASE_TYPES, None):
        raise NativeRefusal("work_incomplete", "the work record's params, argv, skip options or database type are "
                                               "malformed")
    if work["console_log"] != CONSOLE_LOG:
        raise NativeRefusal("unsafe_path", f"unexpected log name {work['console_log']!r}")
    results_dir = native_relative(work["results_dir"])
    for key in ("genome", "out_dir", "tmp_dir"):
        _inside(native_relative(work[key]), results_dir)
    check_storage(data_dir, work["storage_id"])


def prepare_native(work: Any, data_dir: str, executable: str, database_dirs: list[str]
                   ) -> tuple[list[str], Path, dict[str, str], list[dict[str, Any]]]:
    """Every check before a native run, then (argv, results folder, extra environment, Bakta's start-up checks as
    found on this Mac). The composed database view (when AMRFinderPlus data replaces the database's own copy) is made
    only once everything else passed. Raises NativeRefusal."""
    data_dir, executable = native_data_dir(data_dir), native_executable(executable)
    _check_work(work, data_dir, executable)
    params = _params(work)
    db = native_database(work["database"], database_dirs)
    amr = native_database(work["amr_data"], database_dirs) if work["amr_data"] is not None else None
    genome = native_path(data_dir, work["genome"])
    out_dir = native_path(data_dir, work["out_dir"], must_exist=False)
    tmp_dir = native_path(data_dir, work["tmp_dir"])
    results = Path(native_path(data_dir, work["results_dir"]))
    if os.path.lexists(out_dir):
        raise NativeRefusal("work_incomplete", f"{work['out_dir']} exists already (Bakta writes a new folder)")
    composed = Path(tmp_dir) / COMPOSED_DB
    if amr is not None and os.path.lexists(composed):
        raise NativeRefusal("work_incomplete", f"{work['tmp_dir']}/{COMPOSED_DB} exists already")
    try:
        supported = BaktaAdapter.help_options(executable)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise NativeRefusal("help_unreadable", f"bakta --help could not be read: {exc}") from exc
    try:
        dependencies = check_dependencies(executable, Path(db), Path(amr) if amr else None)
    except RuntimeError as exc:
        raise NativeRefusal("dependencies_unreadable", str(exc)) from exc
    skips = skip_options(plan_steps(dependencies, work["database_type"], params.skip_plot))
    if skips != work["skip_options"]:
        raise NativeRefusal("programs_changed", f"Bakta's programs on this Mac would skip {', '.join(skips) or 'nothing'}"
                                                f", not {', '.join(work['skip_options']) or 'nothing'} as confirmed")
    try:
        argv = BaktaAdapter.argv(executable, params, Path(genome), composed if amr is not None else Path(db),
                                 Path(out_dir), Path(tmp_dir), skips, supported)
    except ValueError as exc:
        raise NativeRefusal("settings_rejected", str(exc)) from exc
    if argv != work["argv"]:
        raise NativeRefusal("argv_mismatch", "the argument vector built here differs from the API's; nothing was run")
    if amr is not None:
        try:
            compose_database(Path(db), Path(amr), composed)
        except (OSError, ValueError) as exc:
            raise NativeRefusal("amr_data_unreadable", f"the database view for AMRFinderPlus could not be made: {exc}"
                                ) from exc
    return argv, results, {**ENVIRONMENT, **env_for(executable)}, dependencies


def run_native(work: Any, data_dir: str, executable: str, database_dirs: list[str],
               timeout_seconds: float = 7 * 24 * 3600) -> dict[str, Any]:
    """Check the work and run Bakta as the Docker run does (no shell, its own process group, cleaned environment,
    temporary HOME, standard output and error to <results>/bakta.console.log, which the worker reads for progress,
    Bakta's own bin/ first on PATH). Returns the report ARVA.app sends to the API's finish endpoint: outcome "exited"
    (with Bakta's exit code, negative for a signal), "refused" (nothing was run, with a code), "stopped" (by ARVA.app,
    or the time limit) or "not_started"; with Bakta's start-up checks as found on this Mac."""
    report: dict[str, Any] = {"tool": "bakta", "outcome": "refused", "exit_code": None, "argv": None,
                              "executable": executable, "outputs": [], "started_at": None, "finished_at": None,
                              "duration_seconds": None, "code": None, "detail": None, "dependencies": []}
    try:
        argv, results, env, dependencies = prepare_native(work, data_dir, executable, database_dirs)
    except NativeRefusal as exc:
        report.update(code=exc.code, detail=str(exc))
        return report
    except NativeStopped:
        # Stopped by ARVA.app while the checks ran: nothing was started.
        report.update(outcome="not_started", code="stopped_by_app", detail="stopped before the run started")
        return report
    report.update(argv=argv, started_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                  dependencies=[{k: d.get(k) for k in ("name", "status", "found", "minimum")} for d in dependencies])
    start = time.monotonic()
    try:
        run_command(argv, cwd=results, stderr_path=results / CONSOLE_LOG, timeout_seconds=timeout_seconds,
                    extra_env=env)
        report.update(outcome="exited", exit_code=0)
    except NativeStopped:
        report.update(outcome="stopped", code="stopped_by_app")
    except ToolExecutionError as exc:
        outcome = "exited" if exc.returncode is not None else \
            "stopped" if exc.code == "tool_timeout" else "not_started"
        report.update(outcome=outcome, exit_code=exc.returncode, code=exc.code, detail=str(exc)[:2000])
    report.update(finished_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                  duration_seconds=round(time.monotonic() - start, 1))
    out_dir = work["out_dir"]
    report["outputs"] = [f"{out_dir}/{PREFIX}.{suffix}" for suffix in OUTPUTS.values()
                         if os.path.isfile(f"{data_dir}/{out_dir}/{PREFIX}.{suffix}")]
    return report


def native_outputs(out_dir: str) -> set[str]:
    """The files a native report may name: Bakta's outputs in the job's out-dir."""
    return {f"{out_dir}/{PREFIX}.{suffix}" for suffix in OUTPUTS.values()}
