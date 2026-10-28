"""NanoPlot — summary statistics and an interactive HTML report for long reads.

Verified against `NanoPlot --help` and real runs of NanoPlot 1.48.0 (PyPI wheel with nanoget 1.19.6 and
plotly 6.9.0, Python 3.13) on the synthetic nanopore reads. Without --no_static NanoPlot downloads and
runs Chrome for Testing to export PNG images; ARVA always passes --no_static and --only-report (which
skips that code path as well and the per-plot copies of the 4.9 MB embedded plotly.js).

Definitions differ from ARVA's: nanoget drops zero-length reads; N50 is the first length at which the
cumulative sum of lengths sorted *ascending* reaches half the bases; "Reads >QN" counts reads with mean
quality strictly above N; the mean read quality averages per-read qualities in error-probability space
(unweighted by length). NanoStats.txt describes every read; NanoStats_post_filtering.txt, when present,
excludes the reads NanoPlot itself removed (length < 20 and quality > 30, "artefactual").

NanoPlot ships its own modified nanomath (with ave_qual_floats). Installing nanomath into the same
environment replaces it silently and changes mean_qual while --version still says 1.48.0, so detection
imports nanomath with NanoPlot's own interpreter and checks for it.
"""
from __future__ import annotations

import csv
import io
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus
from arva_tools.runner import isolated_home, tool_environment

# nanoget chooses its reader from the file extension only.
_EXTENSIONS = (".fastq", ".fq", ".fastq.gz", ".fq.gz")
_PREFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,80}_")
REQUIRED = ("number_of_reads", "number_of_bases", "median_read_length", "mean_read_length", "read_length_stdev",
            "n50", "mean_qual", "median_qual")
_COUNTS = {"number_of_reads", "number_of_bases", "n50"}
_ABOVE_KEY = re.compile(r"Reads >Q(\d+):")
_ABOVE_VALUE = re.compile(r"(\d+) \(([\d.]+)%\) ([\d.]+)Mb")
_TOP_KEY = re.compile(r"(longest_read_\(with_Q\)|highest_Q_read_\(with_length\)):(\d+)")
_PAIR = re.compile(r"([\d.]+) \(([\d.]+)\)")
_ARTEFACTS = re.compile(r"Removed (\d+) artefactual reads")
_BROWSER = re.compile(r"choreographer|chrom", re.IGNORECASE)
_SHEBANG = re.compile(r"#!\s*(\S+)(?:[ \t]+(\S+))?")
# pip's launcher when the interpreter path is long or has spaces: "#!/bin/sh", then this line.
_PIP_LAUNCHER = re.compile(r"""'''exec' "?(.+?)"? "\$0" "\$@"$""")
_NANOMATH_CHECK = ("import nanomath; print(nanomath.__file__); "
                   "raise SystemExit(0 if hasattr(nanomath, 'ave_qual_floats') else 3)")


@dataclass(frozen=True)
class OutputNames:
    stats: str
    post_filtering: str
    report: str
    log_glob: str


def output_prefix(filename: str) -> str:
    stem = re.sub(r"\.(gz|bgz|bz2)$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"\.(fastq|fq)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_")[:80]
    return f"{stem or 'reads'}_"


def input_name(prefix: str, compressed: bool) -> str:
    return prefix.rstrip("_") + (".fastq.gz" if compressed else ".fastq")


def output_names(prefix: str) -> OutputNames:
    return OutputNames(f"{prefix}NanoStats.txt", f"{prefix}NanoStats_post_filtering.txt",
                       f"{prefix}NanoPlot-report.html", f"{prefix}NanoPlot_*.log")


def browser_traces(home: Path) -> list[str]:
    """What a static-image export leaves in HOME: choreographer's Chrome download, Chrome's profile."""
    return sorted(str(p.relative_to(home)) for p in home.rglob("*") if _BROWSER.search(p.name))


def python_of(executable: str) -> list[str] | None:
    """The interpreter command of a Python entry-point script, or None if it is not one."""
    try:
        with open(executable, encoding="utf-8", errors="replace") as fh:
            first, second = fh.readline(), fh.readline()
    except OSError:
        return None
    m = _SHEBANG.match(first)
    if not m:
        return None
    command = [g for g in m.groups() if g]
    if Path(command[0]).name == "sh" and (launcher := _PIP_LAUNCHER.match(second)):
        command = [launcher.group(1)]
    interpreter = command[1] if Path(command[0]).name == "env" and len(command) > 1 else command[0]
    return command if Path(interpreter).name.startswith("python") else None


def _number(key: str, raw: str) -> float | int:
    value = float(raw.replace(",", ""))
    return int(value) if key in _COUNTS and value.is_integer() else value


class NanoplotAdapter(ToolAdapter):
    info = ToolInfo(
        id="nanoplot",
        name="NanoPlot",
        description="Summary statistics and an interactive HTML report for long reads (Oxford Nanopore, PacBio): "
        "read length and quality distributions, yield by length, and length against quality.",
        homepage="https://github.com/wdecoster/NanoPlot",
        license="MIT (its nanoget dependency is GPL-3.0)",
        citation="De Coster W, Rademakers R. NanoPack2: population-scale evaluation of long-read sequencing data. "
        "Bioinformatics 2023;39(5):btad311.",
        citation_url="https://doi.org/10.1093/bioinformatics/btad311",
        executable="NanoPlot",
        categories=("qc", "report", "long reads"),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("html", "tsv"),
        min_version="1.48.0",
        tested_versions=("1.48.0",),
        install={
            "pip": 'python3 -m venv ~/.arva-tools/nanoplot && ~/.arva-tools/nanoplot/bin/pip install '
            '"NanoPlot==1.48.0" "nanoget==1.19.6"\nexport ARVA_TOOL_NANOPLOT=~/.arva-tools/nanoplot/bin/NanoPlot',
        },
    )
    version_pattern = re.compile(r"NanoPlot\s+v?(\d+\.\d+(?:\.\d+)?)")

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available or d.path is None:
            return d
        python = python_of(d.path)
        if python is None:
            d.version_validated, d.reason = False, "nanomath_unchecked"
            d.message = ("ARVA could not check which nanomath module NanoPlot uses (its executable is not a Python "
                         "script), so its mean and median read quality are not validated")
            return d
        try:
            with isolated_home() as home:
                proc = subprocess.run([*python, "-c", _NANOMATH_CHECK], capture_output=True, text=True, timeout=60,
                                      env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            d.status, d.message = ToolStatus.failed, f"Could not check NanoPlot's nanomath module: {exc}"
            return d
        if proc.returncode == 3:
            d.status, d.reason = ToolStatus.failed, "nanomath_replaced"
            d.message = (f"NanoPlot {d.version} imports a nanomath module without ave_qual_floats "
                         f"({proc.stdout.strip()}), not the modified copy NanoPlot ships, so its mean and median "
                         "read quality would be computed differently. Reinstall NanoPlot in its own environment "
                         "(see the install command) and do not install nanomath into it")
        elif proc.returncode != 0:
            d.status, d.reason = ToolStatus.failed, "nanomath_missing"
            d.message = f"NanoPlot's Python could not import nanomath: {proc.stderr.strip()[-300:]}"
        return d

    @staticmethod
    def argv(executable: str, fastq: Path, outdir: Path, prefix: str, threads: int) -> list[str]:
        if not fastq.name.lower().endswith(_EXTENSIONS):
            raise ValueError(f"NanoPlot recognises FASTQ only by its extension ({', '.join(_EXTENSIONS)}): {fastq.name}")
        if not _PREFIX.fullmatch(prefix):
            raise ValueError(f"unsafe NanoPlot output prefix: {prefix!r}")
        if not 1 <= threads <= 256:
            raise ValueError("threads must be between 1 and 256")
        return [
            executable,
            "--fastq", str(fastq),
            "--outdir", str(outdir),
            "--prefix", prefix,
            "--threads", str(threads),
            # Never omit: without it NanoPlot downloads Chrome to export PNG images.
            "--no_static",
            "--only-report",
            "--include-js", "embedded",
            "--tsv_stats",
        ]

    @staticmethod
    def parse_stats(text: str) -> dict:
        """NanoStats.txt written with --tsv_stats: rows of `key<TAB>value`, read by key."""
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        if not rows or rows[0][:1] != ["Metrics"]:
            raise ValueError("not a NanoPlot --tsv_stats file (no 'Metrics' header)")
        values = {r[0]: r[1] for r in rows[1:] if len(r) >= 2}
        missing = [k for k in REQUIRED if k not in values]
        if missing:
            raise ValueError(f"NanoStats.txt lacks {', '.join(missing)}")
        out: dict = {k: _number(k, values[k]) for k in REQUIRED}
        above, longest, best, unparsed = [], [], [], []
        for key, raw in values.items():
            if key in REQUIRED:
                continue
            if (m := _ABOVE_KEY.fullmatch(key)) and (v := _ABOVE_VALUE.fullmatch(raw.strip())):
                above.append({"threshold": int(m.group(1)), "reads": int(v.group(1)), "percent": float(v.group(2)),
                              "megabases": float(v.group(3))})
            elif (m := _TOP_KEY.fullmatch(key)) and (v := _PAIR.fullmatch(raw.strip())):
                rank, a, b = int(m.group(2)), float(v.group(1)), float(v.group(2))
                if m.group(1).startswith("longest"):
                    longest.append({"rank": rank, "length": int(a), "quality": b})
                else:
                    best.append({"rank": rank, "quality": a, "length": int(b)})
            else:
                unparsed.append(key)
        out["reads_above_quality"] = sorted(above, key=lambda r: r["threshold"])
        out["longest_reads"] = sorted(longest, key=lambda r: r["rank"])
        out["highest_quality_reads"] = sorted(best, key=lambda r: r["rank"])
        out["unparsed"] = unparsed
        return out

    @staticmethod
    def artefact_reads_removed(log_text: str) -> int:
        m = _ARTEFACTS.search(log_text)
        return int(m.group(1)) if m else 0
