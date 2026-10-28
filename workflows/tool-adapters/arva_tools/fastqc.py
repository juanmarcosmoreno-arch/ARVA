"""FastQC — per-file quality control report.

Options verified against `fastqc --help` of FastQC v0.12.1 and v0.11.9.
FastQC's PASS/WARN/FAIL flags are heuristics designed for whole-genome
shotgun Illumina libraries; ARVA reports them as FastQC's flags, not verdicts.
fastqc_data.txt was verified for 0.12.1: modules are '>>Name<TAB>status' ... '>>END_MODULE',
position labels are 1-based inclusive 'a-b' or 'a', and Duplication Levels has one value column.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from arva_tools.base import ToolAdapter, ToolInfo

DATA_JSON = "fastqc_data.json"
OVERREPRESENTED_ROWS = 20


def parse_position(label: str) -> tuple[int, int]:
    """'a-b' or 'a' -> (start, end), 1-based inclusive. Each module bins positions its own way."""
    start, sep, end = label.strip().partition("-")
    first = int(start)
    last = int(end) if sep else first
    if first < 1 or last < first:
        raise ValueError(f"invalid FastQC position label {label!r}")
    return first, last


@dataclass
class _Module:
    status: str
    comments: list[list[str]] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    def comment(self, key: str) -> list[str] | None:
        return next((c for c in self.comments if c[0] == key), None)


def _modules(text: str) -> dict[str, _Module]:
    modules: dict[str, _Module] = {}
    current = None
    for line in text.splitlines():
        if line.startswith(">>END_MODULE"):
            current = None
        elif line.startswith(">>"):
            name, _, status = line[2:].partition("\t")
            current = modules[name.strip()] = _Module(status.strip().upper())
        elif current is not None and line.startswith("#"):
            current.comments.append(line[1:].split("\t"))
        elif current is not None and line.strip():
            current.rows.append(line.split("\t"))
    return modules


def _adapter_content(m: _Module) -> dict:
    header = m.comment("Position")
    names = header[1:] if header else []
    positions: list[dict] = []
    values: list[list[float]] = [[] for _ in names]
    for row in m.rows:
        start, end = parse_position(row[0])
        positions.append({"label": row[0], "start": start, "end": end})
        for i in range(len(names)):
            values[i].append(float(row[i + 1]))
    return {"status": m.status, "positions": positions,
            "adapters": [{"name": n, "percent": v} for n, v in zip(names, values, strict=True)]}


def _duplication(m: _Module) -> dict:
    total = m.comment("Total Deduplicated Percentage")
    header = m.comment("Duplication Level")
    if total is None or header is None:
        raise ValueError("no 'Total Deduplicated Percentage' or 'Duplication Level' header")
    # 0.11.x wrote 'Percentage of deduplicated' before 'Percentage of total'.
    col = header.index("Percentage of total")
    remaining = float(total[1])
    return {"status": m.status, "total_deduplicated_percent": remaining, "duplicate_percent": 100 - remaining,
            "bins": [{"level": r[0], "percent_of_total": float(r[col])} for r in m.rows]}


def _overrepresented(m: _Module, total_sequences: int | None) -> dict:
    header = m.comment("Sequence")
    if header is None and m.rows:
        raise ValueError("rows without a header")
    # FastQC writes no header row when it finds nothing.
    col = {name: i for i, name in enumerate(header or [])}
    rows = [{"sequence": r[col["Sequence"]], "count": int(r[col["Count"]]), "percent": float(r[col["Percentage"]]),
             "possible_source": r[col["Possible Source"]]} for r in m.rows]
    return {"status": m.status, "total": len(rows), "rows": rows[:OVERREPRESENTED_ROWS],
            "every_read_listed": bool(rows) and len(rows) == total_sequences}


def _zip_texts(zip_path: Path) -> tuple[str, str]:
    """summary.txt and fastqc_data.txt of a FastQC zip; ValueError if it does not open or lacks them."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            summary = next((n for n in names if n.endswith("/summary.txt")), None)
            data = next((n for n in names if n.endswith("/fastqc_data.txt")), None)
            if summary is None or data is None:
                raise ValueError(f"{Path(zip_path).name} has no summary.txt or fastqc_data.txt")
            return z.read(summary).decode("utf-8", "replace"), z.read(data).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"{Path(zip_path).name} could not be opened: {exc}") from exc


class FastqcAdapter(ToolAdapter):
    info = ToolInfo(
        id="fastqc",
        name="FastQC",
        description="Widely used quality-control report for high-throughput sequencing reads "
        "(per-base quality, sequence content, duplication, adapter content…).",
        homepage="https://www.bioinformatics.babraham.ac.uk/projects/fastqc/",
        license="GPL-3.0-or-later",
        citation="Andrews S. FastQC: a quality control tool for high throughput sequence data. "
        "Babraham Bioinformatics, 2010.",
        citation_url="https://www.bioinformatics.babraham.ac.uk/projects/fastqc/",
        executable="fastqc",
        categories=("qc", "report"),
        input_formats=("fastq", "fastq.gz", "bam", "sam"),
        output_formats=("html", "zip"),
        min_version="0.11.0",
        tested_versions=("0.11.9", "0.12.1"),
        install={"conda": "bioconda::fastqc", "apt": "fastqc"},
    )
    version_pattern = re.compile(r"FastQC\s+v?(\d+\.\d+(?:\.\d+)?)")

    @staticmethod
    def argv(executable: str, input_path: Path, outdir: Path, temp_dir: Path) -> list[str]:
        return [
            executable, "--outdir", str(outdir), "--noextract", "--quiet",
            "--threads", "1", "--dir", str(temp_dir), str(input_path),
        ]

    @staticmethod
    def output_names(input_name: str) -> tuple[str, str]:
        """FastQC names outputs after the input minus .gz/.bz2 and the format extension."""
        stem = re.sub(r"\.(gz|bz2)$", "", input_name)
        stem = re.sub(r"\.(fastq|fq|txt|sam|bam)$", "", stem)
        return f"{stem}_fastqc.html", f"{stem}_fastqc.zip"

    @staticmethod
    def parse_zip(zip_path: Path) -> dict:
        summary, data = _zip_texts(zip_path)
        modules = []
        for line in summary.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                modules.append({"status": parts[0], "module": parts[1]})
        basic = {}
        in_basic = False
        for line in data.splitlines():
            if line.startswith(">>Basic Statistics"):
                in_basic = True
                continue
            if in_basic:
                if line.startswith(">>END_MODULE"):
                    break
                if not line.startswith("#") and "\t" in line:
                    k, v = line.split("\t", 1)
                    basic[k] = v
        version = re.search(r"##FastQC\s+(\S+)", data)
        return {"fastqc_version": version.group(1) if version else None, "modules": modules,
                "basic_statistics": basic}

    @staticmethod
    def read_data(zip_path: Path) -> dict:
        return FastqcAdapter.parse_data(_zip_texts(zip_path)[1])

    @staticmethod
    def parse_data(text: str) -> dict:
        """Adapter content, duplication levels and overrepresented sequences from fastqc_data.txt.
        A module that is absent is None; one whose columns are not recognised is listed in 'unrecognised'."""
        modules = _modules(text)
        basic = {r[0]: r[1] for r in modules["Basic Statistics"].rows if len(r) >= 2} \
            if "Basic Statistics" in modules else {}
        total = basic.get("Total Sequences", "")
        total_sequences = int(total) if total.isdigit() else None
        # 'Sequence length' is '150' or a range such as '273-26593'.
        longest = basic.get("Sequence length", "").split("-")[-1].strip()
        unrecognised: list[str] = []

        def module(name, parse, *args):
            m = modules.get(name)
            if m is None:
                return None
            try:
                return parse(m, *args)
            except (ValueError, IndexError, KeyError):
                unrecognised.append(name)
                return None

        version = re.search(r"##FastQC\s+(\S+)", text)
        return {
            "fastqc_version": version.group(1) if version else None,
            "total_sequences": total_sequences,
            "max_read_length": int(longest) if longest.isdigit() else None,
            "modules": [{"module": name, "status": m.status} for name, m in modules.items()],
            "adapter_content": module("Adapter Content", _adapter_content),
            "duplication": module("Sequence Duplication Levels", _duplication),
            "overrepresented_sequences": module("Overrepresented sequences", _overrepresented, total_sequences),
            "unrecognised": unrecognised,
        }

    @staticmethod
    def summarize(data: dict) -> dict:
        """Compact figures for the job summary and the sample report; the tables stay in fastqc_data.json."""
        ac, dup, over = data["adapter_content"], data["duplication"], data["overrepresented_sequences"]
        adapters = None
        if ac is not None:
            highest = []
            for a in ac["adapters"]:
                peak = max(a["percent"], default=0.0)
                first = ac["positions"][a["percent"].index(peak)]["label"] if peak > 0 else None
                highest.append({"name": a["name"], "max_percent": peak, "first_position": first})
            adapters = {"status": ac["status"], "adapters": highest}
        return {
            "max_read_length": data["max_read_length"],
            "adapter_content": adapters,
            "duplication": None if dup is None else
            {k: dup[k] for k in ("status", "total_deduplicated_percent", "duplicate_percent")},
            "overrepresented_sequences": None if over is None else
            {k: over[k] for k in ("status", "total", "every_read_listed")},
        }
