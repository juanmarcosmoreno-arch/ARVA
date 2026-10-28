"""MultiQC — one project-level report built from FastQC, fastp, SeqKit and Filtlong outputs.

Verified against `multiqc --help` and real runs of MultiQC 1.35 (PyPI wheel, Python 3.13, plotly
5.24.1) on outputs of FastQC 0.12.1, fastp 0.23.4, SeqKit 2.3.0 and Filtlong 0.2.1. MultiQC only
re-displays those tools' values (plus a few percentages it derives), and exits 0 even when it found
nothing or silently dropped an input, so callers must check its outputs with `check_sources`.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus

REPORT_FILENAME = "arva_multiqc_report.html"
# MultiQC names the data directory after --filename.
DATA_DIR = "arva_multiqc_report_data"
DATA_FORMAT = "tsv"
SOURCES_FILE = "multiqc_sources.txt"
DATA_JSON = "multiqc_data.json"
VERSIONS_FILE = "multiqc_software_versions.txt"
# Second guard besides --no-version-check and the config key.
ENVIRONMENT = {"MULTIQC_NO_VERSION_CHECK": "true"}

# Module id -> its name in multiqc_sources.txt and the file-name suffix its search pattern finds.
MODULES: dict[str, tuple[str, str]] = {
    "fastqc": ("FastQC", "_fastqc.zip"),
    "fastp": ("fastp", ".fastp.json"),
    "seqkit": ("SeqKit", ".seqkit_stats.tsv"),
    "filtlong": ("Filtlong", ".filtlong.log"),
}

# MultiQC 1.35 general-stats key -> (unit of the raw value, "tool" or "multiqc" as its origin); the
# headers describe the displayed value (fastp rates x100), so they cannot give units.
GENERAL_STATS: dict[tuple[str, str], tuple[str, str]] = {
    ("fastqc", "total_sequences"): ("reads", "tool"),
    ("fastqc", "percent_gc"): ("%", "tool"),
    ("fastqc", "avg_sequence_length"): ("bp", "multiqc"),
    ("fastqc", "median_sequence_length"): ("bp", "multiqc"),
    ("fastqc", "percent_duplicates"): ("%", "multiqc"),
    ("fastqc", "percent_fails"): ("%", "multiqc"),
    ("fastp", "before_filtering_read1_mean_length"): ("bp", "tool"),
    ("fastp", "before_filtering_read2_mean_length"): ("bp", "tool"),
    ("fastp", "filtering_result_passed_filter_reads"): ("reads", "tool"),
    ("fastp", "pct_surviving_reads"): ("%", "multiqc"),
    ("fastp", "pct_surviving_bases"): ("%", "multiqc"),
    ("fastp", "pct_adapter"): ("%", "multiqc"),
    ("fastp", "pct_duplication"): ("%", "multiqc"),
    ("fastp", "after_filtering_q30_rate"): ("fraction", "tool"),
    ("fastp", "after_filtering_q30_bases"): ("bases", "tool"),
    ("fastp", "after_filtering_gc_content"): ("fraction", "tool"),
    ("seqkit", "num_seqs"): ("sequences", "tool"),
    ("seqkit", "sum_len"): ("bases", "tool"),
    ("seqkit", "avg_len"): ("bp", "tool"),
    ("seqkit", "N50"): ("bp", "tool"),
    ("seqkit", "Q30_pct"): ("%", "tool"),
    ("seqkit", "GC_pct"): ("%", "tool"),
    ("seqkit", "AvgQual"): ("Phred", "tool"),
    ("filtlong", "Target bases"): ("bases", "tool"),
    ("filtlong", "Bases kept"): ("bases", "tool"),
}

# MultiQC 1.35 does not HTML-escape sample names or the title, so user text loses markup characters.
_UNSAFE = re.compile(r"[^\w .,:;+#()\-]")

_OLD_VERSIONS = (
    "Older releases such as the Ubuntu/Debian 1.18 package cannot be used: they have no "
    "--no-version-check option and contact multiqc.info over plain HTTP on every run, their reports "
    "miss a JavaScript asset (jszip), and they have no SeqKit module."
)


def report_text(text: str, limit: int = 120) -> str:
    return _UNSAFE.sub("_", " ".join(text.split()))[:limit].strip() or "_"


def staged_name(index: int, module: str) -> str:
    return f"arva-{index:04d}{MODULES[module][1]}"


@dataclass(frozen=True)
class ReportInput:
    module: str
    path: Path
    name: str


class MultiqcAdapter(ToolAdapter):
    info = ToolInfo(
        id="multiqc",
        name="MultiQC",
        description="Gathers the FastQC, fastp, SeqKit and Filtlong results of a project's samples into one "
        "interactive HTML report. It shows the values those tools computed; it measures nothing new.",
        homepage="https://multiqc.info",
        license="GPL-3.0",
        citation="Ewels P, Magnusson M, Lundin S, Käller M. MultiQC: summarize analysis results for multiple "
        "tools and samples in a single report. Bioinformatics 2016;32(19):3047–3048.",
        citation_url="https://doi.org/10.1093/bioinformatics/btw354",
        executable="multiqc",
        categories=("qc", "report"),
        input_formats=("FastQC zip", "fastp json", "SeqKit stats tsv", "Filtlong log"),
        output_formats=("html", "tsv", "json"),
        min_version="1.35",
        tested_versions=("1.35",),
        install={
            "pip": 'python3 -m venv ~/.arva-tools/multiqc && ~/.arva-tools/multiqc/bin/pip install '
            '"multiqc==1.35" "plotly==5.24.1"\nexport ARVA_TOOL_MULTIQC=~/.arva-tools/multiqc/bin/multiqc',
        },
    )
    version_pattern = re.compile(r"multiqc,?\s+version\s+v?(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is ToolStatus.incompatible:
            d.message, d.reason = f"{d.message}. {_OLD_VERSIONS}", "multiqc_too_old"
        return d

    @staticmethod
    def config(modules: Sequence[str]) -> str:
        """The --config file (JSON is valid YAML)."""
        return json.dumps({
            "no_version_check": True,
            "no_ai": True,
            "show_analysis_paths": False,
            # Raw counts with matching labels (the default shows millions with an "M" suffix).
            "read_count_multiplier": 1,
            "read_count_prefix": "",
            "read_count_desc": "count",
            "long_read_count_multiplier": 1,
            "long_read_count_prefix": "",
            "long_read_count_desc": "count",
            "base_count_multiplier": 1,
            "base_count_prefix": "bp",
            "base_count_desc": "bp",
            "sample_names_replace_exact": True,
            # An empty DOI list removes the badges whose hover looks the DOI up on api.crossref.org.
            "module_order": [{m: {"doi": []}} for m in modules],
            # Filtlong 0.2.1 writes \r progress lines that push its marker past the default 5 lines.
            "sp": {"filtlong": {"contents": "Scoring long reads", "contents_re": ".*Filtering long reads.*",
                                "num_lines": 20}},
        }, indent=1)

    @staticmethod
    def replace_names(inputs: Iterable[ReportInput]) -> str:
        return "".join(f"{i.path.name}\t{i.name}\n" for i in inputs)

    @staticmethod
    def argv(
        executable: str,
        *,
        file_list: Path,
        outdir: Path,
        config: Path,
        names: Path,
        title: str,
        comment: str,
        modules: Sequence[str],
    ) -> list[str]:
        unknown = [m for m in modules if m not in MODULES]
        if unknown or not modules:
            raise ValueError(f"unsupported or missing MultiQC modules: {unknown}")
        a = [
            executable,
            "--file-list", str(file_list),
            "--outdir", str(outdir),
            "--filename", REPORT_FILENAME,
            "--force",
            "--no-version-check",
            "--no-ai",
            "--no-ansi",
            "--no-megaqc-upload",
            "--interactive",
            "--data-format", DATA_FORMAT,
            "--title", report_text(title),
            "--comment", report_text(comment),
            "--config", str(config),
            # Sample names come from the staged file names, renamed exactly by the TSV.
            "--fn_as_s_name",
            "--fullnames",
            "--replace-names", str(names),
        ]
        for m in modules:
            a += ["--module", m]
        a.append("--require-logs")
        return a

    @staticmethod
    def parse_sources(text: str) -> list[dict[str, str]]:
        return [
            {"module": r["Module"], "section": r["Section"], "sample": r["Sample Name"], "source": r["Source"]}
            for r in csv.DictReader(io.StringIO(text), delimiter="\t")
        ]

    @staticmethod
    def check_sources(expected: Sequence[ReportInput], sources: Sequence[dict[str, str]]) -> list[str]:
        """Every input must appear exactly once, under its own name; nothing else may appear."""
        found: dict[tuple[str, str], set[str]] = defaultdict(set)
        names: dict[tuple[str, str], set[str]] = defaultdict(set)
        for s in sources:
            source = str(Path(s["source"]).resolve())
            found[(s["module"], source)].add(s["sample"])
            names[(s["module"], s["sample"])].add(source)
        problems = []
        wanted = set()
        for i in expected:
            module = MODULES[i.module][0]
            key = (module, str(i.path.resolve()))
            wanted.add(key)
            got = found.get(key, set())
            if not got:
                problems.append(f"{module}: '{i.name}' ({i.path.name}) is missing from the report")
            elif got != {i.name}:
                problems.append(f"{module}: {i.path.name} was reported as {sorted(got)} instead of '{i.name}'")
        for (module, sample), paths in names.items():
            if len(paths) > 1:
                problems.append(f"{module}: sample '{sample}' was built from {len(paths)} files")
        for key in found.keys() - wanted:
            problems.append(f"{key[0]}: unexpected input {Path(key[1]).name}")
        return problems

    @staticmethod
    def parse_general_stats(data: dict) -> dict:
        """Raw general-statistics values with the unit of each value (never the scaled TSV)."""
        values: dict = data.get("report_general_stats_data") or {}
        headers: dict = data.get("report_general_stats_headers") or {}
        columns, unmapped = [], []
        rows: dict[str, dict[str, dict]] = defaultdict(dict)
        for module, cols in headers.items():
            for key, header in cols.items():
                spec = GENERAL_STATS.get((module, key))
                if spec is None:
                    unmapped.append(f"{module}:{key}")
                    continue
                columns.append({
                    "module": module, "key": key, "title": header.get("title") or key,
                    "description": header.get("description") or "", "unit": spec[0], "origin": spec[1],
                    "hidden": bool(header.get("hidden")),
                })
                for sample, metrics in (values.get(module) or {}).items():
                    value = metrics.get(key)
                    if isinstance(value, int | float):
                        rows[sample].setdefault(module, {})[key] = value
        return {
            "columns": columns,
            "rows": [{"name": name, "values": vals} for name, vals in sorted(rows.items())],
            "unmapped": unmapped,
        }

    @staticmethod
    def parse_software_versions(text: str) -> dict[str, str]:
        """multiqc_software_versions.txt: one row per module, one column per program."""
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        if not rows:
            return {}
        out = {}
        for row in rows[1:]:
            for program, version in zip(rows[0][1:], row[1:], strict=False):
                if version.strip():
                    out[program] = version.strip()
        return out

    @staticmethod
    def parse_data(data_dir: Path) -> dict:
        data = json.loads((data_dir / DATA_JSON).read_text())
        versions = data_dir / VERSIONS_FILE
        return {
            "multiqc_version": data.get("config_version"),
            "report_creation_date": data.get("report_creation_date"),
            "general_stats": MultiqcAdapter.parse_general_stats(data),
            "software_versions": MultiqcAdapter.parse_software_versions(versions.read_text())
            if versions.is_file() else {},
        }
