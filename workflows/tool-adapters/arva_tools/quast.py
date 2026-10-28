"""QUAST — quality assessment of genome assemblies, with or without a reference genome.

Verified against `quast.py --help`, the source of QUAST 5.2.0 (PyPI sdist quast-5.2.0.tar.gz, sha256
23649fbd93253c6da982c0b67d719f9262461deecdc6dffbd690b75dfd790ad7: quast.py and quast_libs/options_parser.py,
qutils.py, N50.py, basic_stats.py, fastaparser.py, log.py, ca_utils/misc.py) and real runs, offline, with
Python 3.12, joblib 1.5.2, simplejson 3.20.2 and minimap2 2.26 on assemblies derived from the synthetic genome:

* Every metric except "# contigs (>= 0 bp)" and "Total length (>= 0 bp)" counts only the contigs of at least
  --min-contig bp (default 500). Nx/Lx: the contig at which the cumulative length of the contigs sorted by
  decreasing length first reaches x % of the total (N50.py). GC (%) divides G + C by every base except N, after
  QUAST has replaced the IUPAC codes M K R Y W S V B H D with N; any other character makes it refuse the file.
* An assembly without a contig of at least --min-contig bp is skipped with a warning, and QUAST still exits with
  status 0 when another assembly remains, so the report must be checked for every label.
* --labels is split at commas, with quotes and surrounding spaces removed; ARVA's labels use letters, digits,
  spaces and . _ ( ) + - only.
* --ambiguity-score, even at its default 0.99, switches --ambiguity-usage to "all", so ARVA never passes it.
* When a contig's best alignment covers more than 99 % of it (a fixed threshold, ca_utils/analyze_contigs.py), QUAST
  keeps that alignment and those scoring at least 0.99 times as well, and skips the others as insignificant: a chromosome
  identical to the reference but starting 1,000 bp later (of 300,000) had a genome fraction of 99.683 %.
* With a reference, QUAST aligns the contigs with minimap2: its bundled copy (quast_libs/minimap2/minimap2) when
  that was compiled, else minimap2 2.19 or later on PATH; failing both, it compiles the bundled source (2.24) into
  its own installation folder during the run. ARVA requires one of the first two, so nothing is compiled during a
  job, and records the minimap2 executable and version QUAST's alignment log names.
* QUAST chooses gzip from the .gz extension, so ARVA links every input with an explicit extension.
* QUAST sets the locale en_US.UTF-8 when it exists and otherwise warns; only the dates written in report.html
  depend on it. Without matplotlib (ARVA does not install it) QUAST draws no static plots; ARVA passes --no-plots.
* QUAST 5.2.0 leaves quast.log empty under CPython 3.13.15 and later 3.13 releases (seen with 3.13.17): its
  console set-up loop also removes the log's file handler once Logger.removeHandler no longer changes the list in
  place. ARVA therefore keeps QUAST's console output (quast.console.log) in every case.
* report.html and the Icarus pages carry their scripts inline and reference nothing on the network.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus
from arva_tools.nanoplot import python_of
from arva_tools.runner import isolated_home, tool_environment

OUT_DIR = "quast"
CONSOLE_LOG = "quast.console.log"
REPORT_TSV = "report.tsv"
TRANSPOSED_TSV = "transposed_report.tsv"
REPORT_HTML = "report.html"
ICARUS_HTML = "icarus.html"
ICARUS_DIR = "icarus_viewers"
LOG = "quast.log"
REQUIRED_OUTPUTS = (REPORT_TSV, TRANSPOSED_TSV, REPORT_HTML, ICARUS_HTML)
DEFAULT_MIN_CONTIG = 500
MAX_MIN_CONTIG = 1_000_000
MAX_ASSEMBLIES = 10
CONTIG_THRESHOLDS = (0, 1_000, 5_000, 10_000, 25_000, 50_000)
X_FOR_NX = 90
# QUAST's defaults for reference-based metrics, passed explicitly; --ambiguity-score is left out (see above).
REFERENCE_OPTIONS = (("--min-alignment", "65"), ("--min-identity", "95.0"), ("--ambiguity-usage", "one"),
                     ("--extensive-mis-size", "1000"), ("--local-mis-size", "200"),
                     ("--scaffold-gap-max-size", "10000"), ("--unaligned-part-size", "500"))
MINIMAP2_MIN = (2, 19)
STAGE_LINES = {
    "Running Basic statistics processor...": "basic_stats",
    "Running Contig analyzer...": "contig_analyzer",
    "Running NA-NGA calculation...": "na_nga",
    "Running Genome analyzer...": "genome_analyzer",
    "Creating large visual summaries...": "visual_summaries",
}
REFERENCE_STAGES = frozenset({"contig_analyzer", "na_nga", "genome_analyzer"})

_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,79}")
_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()+-]+")
_FASTA_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fasta|fa|fna)(\.gz)?")
_FLAG = re.compile(r"(?<![\w-])(--?[A-Za-z][A-Za-z0-9-]*)")
_PARTS = re.compile(r"(\d+) \+ (\d+) part")
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?\d+\.\d+")
_VERSION = re.compile(r"^Version: (\S+)", re.M)
_PYTHON = re.compile(r"^\s*Python version: (\S+)", re.M)
_WARNING = re.compile(r"^\s*WARNING: (.+?)\s*$", re.M)
_ERROR = re.compile(r"ERROR! (.+?)\s*$", re.M)
_NON_ACGTN = re.compile(r"Skipping (.+?) because it contains non-ACGTN characters")
_SKIPPED = re.compile(r"Skipping (.+?) because it doesn't contain contigs >= (\d+) bp\.")
_ALIGNER_VERSION = re.compile(r"^\[M::main\] Version: (\S+)", re.M)
_ALIGNER_CMD = re.compile(r"^\[M::main\] CMD: (\S+)", re.M)
_MINIMAP2_VERSION = re.compile(r"(\d+)\.(\d+)")
_LIBS_CHECK = "import os, quast_libs; print(os.path.dirname(os.path.realpath(quast_libs.__file__)))"


@dataclass
class QuastParams:
    min_contig: int = DEFAULT_MIN_CONTIG
    threads: int = 1

    def validate(self) -> None:
        errors = []
        if not 0 <= self.min_contig <= MAX_MIN_CONTIG:
            errors.append(f"min_contig must be between 0 and {MAX_MIN_CONTIG:,}")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assembly_label(assembler: str, version: str, assembly_id: str) -> str:
    """A label QUAST keeps as it is: no commas or quotes, unique through the assembly id."""
    text = _LABEL_UNSAFE.sub("_", f"{assembler} {version}").strip(" _")[:60] or "assembly"
    return f"{text} {assembly_id[:8]}"


def input_name(kind: str, index: int, compressed: bool) -> str:
    stem = f"{kind}_{index:02d}" if kind == "assembly" else kind
    return f"{stem}.fasta" + (".gz" if compressed else "")


def stages(reference: bool) -> tuple[str, ...]:
    return tuple(s for s in STAGE_LINES.values() if reference or s not in REFERENCE_STAGES)


def flags(reference: bool, features: bool) -> list[str]:
    """Every QUAST option the command uses, so each can be checked against the installed version's --help."""
    used = ["--output-dir", "--threads", "--min-contig", "--labels", "--contig-thresholds", "--x-for-Nx", "--no-plots"]
    if reference:
        used += ["-r", *(flag for flag, _ in REFERENCE_OPTIONS)]
    if features:
        used.append("--features")
    return used


def _value(raw: str) -> Any:
    text = raw.strip()
    if text == "-":
        return None
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    if m := _PARTS.fullmatch(text):
        return {"full": int(m.group(1)), "partial": int(m.group(2))}
    return text


def _table(labels: list[str], rows: list[tuple[str, list[str]]], source: str) -> dict[str, Any]:
    if not labels or any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError(f"{source}: missing, empty or repeated assembly labels")
    seen: set[str] = set()
    out = []
    for field, values in rows:
        if not field or field in seen:
            raise ValueError(f"{source}: missing or repeated field {field!r}")
        if len(values) != len(labels):
            raise ValueError(f"{source}: field {field!r} has {len(values)} values for {len(labels)} assemblies")
        seen.add(field)
        out.append({"field": field, "values": [_value(v) for v in values]})
    if not out:
        raise ValueError(f"{source}: no metrics")
    return {"labels": labels, "rows": out}


class QuastAdapter(ToolAdapter):
    info = ToolInfo(
        id="quast",
        name="QUAST",
        description="Quality assessment of genome assemblies: contiguity (N50, L50, contig lengths) for every "
        "assembly, and with a reference genome also genome fraction, misassemblies, mismatches and indels; "
        "compares several assemblies in one report with Icarus contig viewers.",
        homepage="https://github.com/ablab/quast",
        license="GPL-2.0",
        citation="Mikheenko A, Prjibelski A, Saveliev V, Antipov D, Gurevich A. Versatile genome assembly evaluation "
        "with QUAST-LG. Bioinformatics 2018;34(13):i142–i150 (QUAST 5). Gurevich A, Saveliev V, Vyahhi N, Tesler G. "
        "QUAST: quality assessment tool for genome assemblies. Bioinformatics 2013;29(8):1072–1075.",
        citation_url="https://doi.org/10.1093/bioinformatics/bty266",
        executable="quast.py",
        categories=("assembly", "quality"),
        input_formats=("fasta", "fasta.gz"),
        output_formats=("html", "tsv", "txt"),
        min_version="5.2.0",
        tested_versions=("5.2.0",),
        install={
            "pip": 'python3 -m venv ~/.arva-tools/quast && ~/.arva-tools/quast/bin/pip install "setuptools==80.9.0" '
            '&& ~/.arva-tools/quast/bin/pip install --no-build-isolation "quast==5.2.0" "joblib==1.5.2" '
            '"simplejson==3.20.2"\nexport ARVA_TOOL_QUAST=~/.arva-tools/quast/bin/quast.py\n'
            "sudo apt install minimap2  # the aligner QUAST uses with a reference",
        },
    )
    version_pattern = re.compile(r"QUAST v(\d+\.\d+(?:\.\d+)?)")

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available or d.path is None:
            return d
        a = aligner(d.path)
        if a["provided_by"] == "missing":
            d.reason = "minimap2_missing"
            note = ("Reference-based evaluation needs minimap2 2.19 or later on PATH (or QUAST's own compiled copy); "
                    + (f"{a['found']} is version {a['version']}" if a.get("found") else "none was found")
                    + ". Evaluation without a reference works")
            d.message = f"{d.message}. {note}" if d.message else note
        return d

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        """The short and long options listed by this QUAST's own --help."""
        with isolated_home() as home:
            proc = subprocess.run([executable, "--help"], capture_output=True, text=True, timeout=60,
                                  env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(f"quast.py --help exited with status {proc.returncode}")
        return frozenset(_FLAG.findall(proc.stdout + proc.stderr))

    @staticmethod
    def argv(executable: str, params: QuastParams, assemblies: Sequence[tuple[Path, str]], out_dir: Path,
             supported: frozenset[str], reference: Path | None = None, features: Path | None = None) -> list[str]:
        params.validate()
        if not 1 <= len(assemblies) <= MAX_ASSEMBLIES:
            raise ValueError(f"QUAST evaluates between 1 and {MAX_ASSEMBLIES} assemblies per run")
        labels = [label for _, label in assemblies]
        if len(set(labels)) != len(labels) or not all(_LABEL.fullmatch(label) for label in labels):
            raise ValueError("assembly labels must be unique and use letters, digits, spaces and . _ ( ) + - only")
        for path in (*(p for p, _ in assemblies), *([reference] if reference else [])):
            if not _FASTA_NAME.fullmatch(path.name):
                raise ValueError(f"QUAST reads compression from the file name; unsafe or unrecognised name: {path.name}")
        if features is not None:
            if reference is None:
                raise ValueError("genomic features are coordinates in the reference: they need a reference")
            if ":" in str(features):
                raise ValueError("QUAST reads 'type:path' from --features, so the path cannot contain ':'")
        if missing := [f for f in flags(reference is not None, features is not None) if f not in supported]:
            raise ValueError(f"this QUAST version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable, *(str(p) for p, _ in assemblies), "--output-dir", str(out_dir),
             "--threads", str(params.threads), "--min-contig", str(params.min_contig), "--labels", ",".join(labels),
             "--contig-thresholds", ",".join(map(str, CONTIG_THRESHOLDS)), "--x-for-Nx", str(X_FOR_NX), "--no-plots"]
        if reference is not None:
            a += ["-r", str(reference)]
            for flag, value in REFERENCE_OPTIONS:
                a += [flag, value]
        if features is not None:
            a += ["--features", str(features)]
        return a

    @staticmethod
    def stage(line: str) -> str | None:
        return STAGE_LINES.get(line.strip())

    @staticmethod
    def parse_report(text: str) -> dict[str, Any]:
        """report.tsv: one row per metric (field name first), one column per assembly label."""
        rows = [r for r in csv.reader(io.StringIO(text), delimiter="\t") if r]
        if not rows or rows[0][:1] != ["Assembly"]:
            raise ValueError("report.tsv: line 1 is not the 'Assembly' header")
        return _table(rows[0][1:], [(r[0], r[1:]) for r in rows[1:]], "report.tsv")

    @staticmethod
    def parse_transposed_report(text: str) -> dict[str, Any]:
        """transposed_report.tsv: one row per assembly, one column per metric (field names in the header)."""
        rows = [r for r in csv.reader(io.StringIO(text), delimiter="\t") if r]
        if not rows or rows[0][:1] != ["Assembly"]:
            raise ValueError("transposed_report.tsv: line 1 is not the 'Assembly' header")
        fields = rows[0][1:]
        for n, r in enumerate(rows[1:], start=2):
            if len(r) != len(rows[0]):
                raise ValueError(f"transposed_report.tsv: line {n} has {len(r)} columns, the header has {len(rows[0])}")
        return _table([r[0] for r in rows[1:]], [(f, [r[i + 1] for r in rows[1:]]) for i, f in enumerate(fields)],
                      "transposed_report.tsv")

    @staticmethod
    def parse_console(text: str) -> dict[str, Any]:
        """Facts from QUAST's console output: versions, warnings, skipped assemblies, errors and stages."""
        warnings = list(dict.fromkeys(m.group(1) for m in _WARNING.finditer(text)))
        return {
            "quast_version": m.group(1) if (m := _VERSION.search(text)) else None,
            "python_version": m.group(1) if (m := _PYTHON.search(text)) else None,
            "warnings": warnings,
            "skipped": [{"label": m.group(1), "min_contig": int(m.group(2))} for m in _SKIPPED.finditer(text)],
            "errors": [m.group(1) for m in _ERROR.finditer(text)],
            "stages_seen": [s for line in text.splitlines() if (s := STAGE_LINES.get(line.strip()))],
        }

    @staticmethod
    def parse_aligner(text: str) -> dict[str, str] | None:
        """The minimap2 executable and version in one of QUAST's contigs_report_<label>.stderr files."""
        version, cmd = _ALIGNER_VERSION.search(text), _ALIGNER_CMD.search(text)
        if not version or not cmd:
            return None
        return {"name": "minimap2", "executable": cmd.group(1), "version": version.group(1)}

    @staticmethod
    def failure_reason(console: str, returncode: int | None, names: Mapping[str, str] | None = None) -> str | None:
        """A plain-language reason for a failed run, from QUAST's own error lines; None when none is recognised.
        `names` maps input paths to the names to show (e.g. assembly labels)."""
        errors = [m.group(1) for m in _ERROR.finditer(console)]
        if "Critical! Tried to use minimap2" in console:
            return ("QUAST could not run minimap2 to align the contigs to the reference. Install minimap2 2.19 or "
                    "later (for example the minimap2 package)")
        for e in errors:
            if e.startswith("None of the assembly files contains correct contigs"):
                return ("QUAST found no contig at least as long as the minimum contig length in any assembly; lower "
                        "the minimum contig length")
            if m := _NON_ACGTN.match(e):
                name = (names or {}).get(m.group(1), m.group(1))
                return (f"QUAST refused {name}: it accepts only A, C, G, T, N and the IUPAC codes M, K, R, Y, W, S, V, "
                        "B, H, D")
            if e.startswith("Reference file"):
                return f"QUAST could not read the reference: {e}"
        if errors:
            return f"QUAST failed: {errors[-1]}"
        if returncode in (-9, 137):
            return "QUAST was stopped by the operating system (out of memory)"
        return None


def quast_libs_dir(executable: str) -> Path | None:
    """The quast_libs folder of the Python package the executable runs, or None when it cannot be found."""
    python = python_of(executable)
    if python is None:
        return None
    try:
        with isolated_home() as home:
            proc = subprocess.run([*python, "-c", _LIBS_CHECK], capture_output=True, text=True, timeout=60,
                                  env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    path = Path(proc.stdout.strip())
    return path if proc.returncode == 0 and path.is_dir() else None


def minimap2_version(executable: str) -> str | None:
    try:
        with isolated_home() as home:
            proc = subprocess.run([executable, "--version"], capture_output=True, text=True, errors="replace",
                                  timeout=60, env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None


def aligner(executable: str) -> dict[str, Any]:
    """Which minimap2 QUAST would use for a reference, found the way QUAST looks for it (ca_utils/misc.py):
    its compiled bundled copy first, then minimap2 2.19 or later on PATH. "missing" means QUAST would try to
    compile the bundled source during the run, which ARVA does not allow."""
    libs = quast_libs_dir(executable)
    bundled = libs / "minimap2" / "minimap2" if libs else None
    if bundled is not None and bundled.is_file() and os.access(bundled, os.X_OK):
        return {"provided_by": "quast_bundled", "executable": str(bundled), "version": minimap2_version(str(bundled))}
    found = shutil.which("minimap2", path=os.environ.get("PATH", ""))
    if found is None:
        return {"provided_by": "missing", "found": None, "version": None}
    version = minimap2_version(found)
    m = _MINIMAP2_VERSION.match(version or "")
    if m and int(m.group(1)) == MINIMAP2_MIN[0] and int(m.group(2)) >= MINIMAP2_MIN[1]:
        return {"provided_by": "path", "executable": found, "version": version}
    return {"provided_by": "missing", "found": found, "version": version}
