"""Flye — de novo assembly of long reads (Oxford Nanopore, PacBio) with repeat graphs.

Verified against `flye --help`, the 2.9.3 USAGE.md and README, the source of Flye 2.9.3 (Ubuntu package
2.9.3+dfsg2-1: flye/main.py, config/configurator.py, assembly/assemble.py, utils/sam_parser.py) and real runs:

* Argument ranges are Flye's own (main.py): threads 1-128, iterations 0-10, min overlap 1,000-10,000.
  --asm-coverage requires --genome-size and is incompatible with --meta; --read-error is only accepted
  with the corrected, nano-hq and hifi read types.
* --genome-size is optional since 2.9. When given, Flye logs the coverage it implies (and warns when it is
  below 5 or above 1,000), passes it to its disjointig assembler, and uses it with --asm-coverage to keep
  only the longest reads for that stage. Without --min-overlap Flye derives the minimum overlap from the
  reads' N90 and logs the value; ARVA records it.
* Flye chooses each input's format from its file name (.fastq/.fq/.fasta/.fa, optionally .gz) and refuses
  paths that contain spaces; it creates --out-dir with os.mkdir, so the parent folder must exist.
* Stages, each announced in the log as ">>>STAGE: <name>": configure, assembly, consensus, repeat,
  contigger, polishing (only with iterations > 0), finalize.
* Debian's and Ubuntu's flye package calls `flye-samtools` (utils/sam_parser.py) but does not ship it, as
  upstream does; without it the consensus is empty and the run aborts. ARVA then links flye-samtools to
  samtools for the run and records the link and samtools' version.
* The output depends on the number of threads: on the synthetic 150 kb genome, runs with 4 threads differed
  from each other in sequence, runs with 2 threads were identical but assembled the plasmid as a dimer, and
  --deterministic (single-threaded disjointigs only) did not make 4-thread runs identical. ARVA records the
  thread count and does not offer --deterministic.
"""
from __future__ import annotations

import csv
import io
import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from arva_tools.base import DetectedTool, ToolAdapter, ToolInfo, ToolStatus, resolve_executable
from arva_tools.runner import isolated_home, tool_environment

READ_TYPES = ("nano-raw", "nano-corr", "nano-hq", "pacbio-raw", "pacbio-corr", "pacbio-hifi")
READ_ERROR_TYPES = frozenset({"nano-corr", "nano-hq", "pacbio-corr", "pacbio-hifi"})
STAGES = ("configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize")
GENOME_SIZE_BASES = ("entered", "expected_genome_size", "reads_over_depth")
OUTPUTS = ("assembly.fasta", "assembly_graph.gfa", "assembly_info.txt", "flye.log")
SAMTOOLS_HELPER = "flye-samtools"
INFO_COLUMNS = ("seq_name", "length", "cov.", "circ.", "repeat", "mult.", "graph_path")

_STAGE = re.compile(r">>>STAGE: (\S+)")
_READ_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fastq|fq)(\.gz)?")
_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
_ERROR = re.compile(r"ERROR: (.+)")
_LOG_INT = {
    "total_read_length": re.compile(r"Total read length: (\d+)"),
    "input_genome_size": re.compile(r"Input genome size: (\d+)"),
    "estimated_coverage": re.compile(r"Estimated coverage: (\d+)"),
    "min_overlap": re.compile(r"(?:Minimum overlap set to|Selected minimum overlap:) (\d+)"),
    "asm_coverage_longest_reads": re.compile(r"Using longest (\d+)x reads for contig assembly"),
    "overlap_based_coverage": re.compile(r"Overlap-based coverage: (\d+)"),
    "mean_edge_coverage": re.compile(r"Mean edge coverage: (\d+)"),
    "total_length": re.compile(r"^\s*Total length:\s*(\d+)", re.M),
    "fragments": re.compile(r"^\s*Fragments:\s*(\d+)", re.M),
    "fragments_n50": re.compile(r"^\s*Fragments N50:\s*(\d+)", re.M),
    "largest_fragment": re.compile(r"^\s*Largest frg:\s*(\d+)", re.M),
    "scaffolds": re.compile(r"^\s*Scaffolds:\s*(\d+)", re.M),
    "mean_coverage": re.compile(r"^\s*Mean coverage:\s*(\d+)", re.M),
}
_READS_NX = re.compile(r"Reads N50/N90: (\d+) / (\d+)")
_ERROR_RATE = re.compile(r">>>STAGE: (\S+)|Alignment error rate: ([\d.]+)")
_COVERAGE_WARNING = re.compile(r"WARNING: (Expected read coverage is \d+, .+?)$", re.M)


@dataclass
class FlyeParams:
    read_type: str
    genome_size_bp: int | None = None
    iterations: int = 1
    min_overlap: int | None = None
    asm_coverage: int | None = None
    read_error: float | None = None
    meta: bool = False
    keep_haplotypes: bool = False
    no_alt_contigs: bool = False
    scaffold: bool = False
    threads: int = 1
    # Provenance of the genome size; never passed to Flye.
    genome_size_basis: str | None = None
    assumed_depth_x: float | None = None

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> FlyeParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def validate(self, supported: frozenset[str] | None = None) -> None:
        errors = []
        if self.read_type not in READ_TYPES:
            errors.append(f"read_type must be one of {', '.join(READ_TYPES)}")
        if self.genome_size_bp is not None and not 1_000 <= self.genome_size_bp <= 10_000_000_000:
            errors.append("genome_size_bp must be between 1,000 and 10,000,000,000")
        if not 0 <= self.iterations <= 10:
            errors.append("iterations must be between 0 and 10")
        if self.min_overlap is not None and not 1_000 <= self.min_overlap <= 10_000:
            errors.append("min_overlap must be between 1,000 and 10,000")
        if self.asm_coverage is not None:
            if self.asm_coverage < 1:
                errors.append("asm_coverage must be ≥ 1")
            if self.genome_size_bp is None:
                errors.append("asm_coverage requires genome_size_bp (Flye selects the longest reads up to "
                              "asm_coverage × genome size)")
            if self.meta:
                errors.append("asm_coverage cannot be combined with meta (Flye refuses the combination)")
        if self.read_error is not None:
            if not 0 < self.read_error < 1:
                errors.append("read_error is a fraction and must be in (0, 1)")
            if self.read_type not in READ_ERROR_TYPES:
                errors.append(f"read_error can only be used with {', '.join(sorted(READ_ERROR_TYPES))}")
        if not 1 <= self.threads <= 128:
            errors.append("threads must be between 1 and 128")
        basis, depth = self.genome_size_basis, self.assumed_depth_x
        if self.genome_size_bp is None and (basis is not None or depth is not None):
            errors.append("genome_size_basis and assumed_depth_x describe a genome size; none was given")
        elif self.genome_size_bp is not None:
            if basis not in GENOME_SIZE_BASES:
                errors.append(f"a genome size needs its basis: one of {', '.join(GENOME_SIZE_BASES)}")
            elif (basis == "reads_over_depth") != (depth is not None):
                errors.append("assumed_depth_x is required with, and only with, genome_size_basis 'reads_over_depth'")
            elif depth is not None and not 0 < depth <= 100_000:
                errors.append("assumed_depth_x must be in (0, 100000]")
        if supported is not None and not errors:
            if missing := [f for f in self.flags() if f not in supported]:
                errors.append(f"this Flye version does not offer {', '.join(missing)} (not in its --help)")
        if errors:
            raise ValueError("; ".join(errors))

    def flags(self) -> list[str]:
        """Every Flye option the command uses, so each can be checked against the installed version's --help."""
        used = [f"--{self.read_type}", "--out-dir", "--threads", "--iterations"]
        for flag, value in (("--genome-size", self.genome_size_bp), ("--min-overlap", self.min_overlap),
                            ("--asm-coverage", self.asm_coverage), ("--read-error", self.read_error)):
            if value is not None:
                used.append(flag)
        for flag, on in (("--meta", self.meta), ("--keep-haplotypes", self.keep_haplotypes),
                         ("--no-alt-contigs", self.no_alt_contigs), ("--scaffold", self.scaffold)):
            if on:
                used.append(flag)
        return used

    def stages(self) -> tuple[str, ...]:
        return tuple(s for s in STAGES if s != "polishing" or self.iterations > 0)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_link_name(index: int, filename: str, compressed: bool) -> str:
    """A space-free name with the extension Flye needs (it reads the format from the name only)."""
    stem = re.sub(r"\.(gz|bgz)$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"\.(fastq|fq)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:80] or "reads"
    return f"{index:02d}_{stem}.fastq" + (".gz" if compressed else "")


def _num(v: float | int) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


class FlyeAdapter(ToolAdapter):
    info = ToolInfo(
        id="flye",
        name="Flye",
        description="De novo assembler for long reads (Oxford Nanopore, PacBio) based on repeat graphs; writes "
        "contigs, the assembly graph and per-contig coverage, circularity and repeat flags.",
        homepage="https://github.com/mikolmogorov/Flye",
        license="BSD-3-Clause",
        citation="Kolmogorov M, Yuan J, Lin Y, Pevzner PA. Assembly of long, error-prone reads using repeat graphs. "
        "Nat Biotechnol 2019;37(5):540–546.",
        citation_url="https://doi.org/10.1038/s41587-019-0072-8",
        executable="flye",
        categories=("assembly", "long reads"),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("fasta", "gfa", "tsv"),
        min_version="2.9",
        tested_versions=("2.9.3",),
        install={"apt": "flye samtools", "conda": "bioconda::flye"},
    )
    # `flye --version` prints e.g. "2.9.3-b1797".
    version_pattern = re.compile(r"^\s*(\d+\.\d+(?:\.\d+)?)", re.M)

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available or d.path is None:
            return d
        helper = samtools_helper(d.path)
        if helper["provided_by"] == "missing":
            d.status, d.reason = ToolStatus.failed, "samtools_missing"
            d.message = ("Flye needs samtools: it calls flye-samtools, which neither this Flye installation nor "
                         "PATH provides, and samtools was not found to stand in for it. Install samtools")
        elif helper["provided_by"] == "arva_link":
            d.reason = "samtools_linked"
            note = (f"This Flye calls flye-samtools, which its installation does not provide (as in Debian's and "
                    f"Ubuntu's flye package); ARVA links it to {helper['samtools']} for each run")
            d.message = f"{d.message}. {note}" if d.message else note
        return d

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        """The long options listed by this Flye's own --help."""
        with isolated_home() as home:
            proc = subprocess.run([executable, "--help"], capture_output=True, text=True, timeout=60,
                                  env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError(f"flye --help exited with status {proc.returncode}")
        return frozenset(_FLAG.findall(proc.stdout + proc.stderr))

    @staticmethod
    def argv(executable: str, params: FlyeParams, reads: list[Path], out_dir: Path,
             supported: frozenset[str]) -> list[str]:
        params.validate(supported)
        if not reads:
            raise ValueError("Flye needs at least one read file")
        for path in (*reads, out_dir):
            if any(c.isspace() for c in str(path)):
                raise ValueError(f"Flye refuses paths that contain spaces: {path}")
        for r in reads:
            if not _READ_NAME.fullmatch(r.name):
                raise ValueError(f"unsafe or unrecognised read file name for Flye: {r.name}")
        a = [executable, f"--{params.read_type}", *map(str, reads), "--out-dir", str(out_dir),
             "--threads", str(params.threads), "--iterations", str(params.iterations)]
        for flag, value in (("--genome-size", params.genome_size_bp), ("--min-overlap", params.min_overlap),
                            ("--asm-coverage", params.asm_coverage), ("--read-error", params.read_error)):
            if value is not None:
                a += [flag, _num(value)]
        for flag, on in (("--meta", params.meta), ("--keep-haplotypes", params.keep_haplotypes),
                         ("--no-alt-contigs", params.no_alt_contigs), ("--scaffold", params.scaffold)):
            if on:
                a.append(flag)
        return a

    @staticmethod
    def stage(line: str) -> str | None:
        m = _STAGE.search(line)
        return m.group(1) if m else None

    @staticmethod
    def parse_assembly_info(text: str) -> list[dict[str, Any]]:
        """assembly_info.txt: one row per contig or scaffold, columns read by their header names."""
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        if not rows or not rows[0] or not rows[0][0].startswith("#"):
            raise ValueError("line 1: not a Flye assembly_info.txt (no '#seq_name' header)")
        header = [rows[0][0].lstrip("#"), *rows[0][1:]]
        if missing := [c for c in INFO_COLUMNS if c not in header]:
            raise ValueError(f"line 1: assembly_info.txt lacks the column(s) {', '.join(missing)}")
        col = {name: i for i, name in enumerate(header)}
        out, seen = [], set()
        for n, row in enumerate(rows[1:], start=2):
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise ValueError(f"line {n}: {len(row)} columns, the header has {len(header)}")
            get = {name: row[i].strip() for name, i in col.items()}
            name = get["seq_name"]
            if not name or name in seen:
                raise ValueError(f"line {n}: missing or repeated contig name {name!r}")
            seen.add(name)
            try:
                length, coverage, multiplicity = int(get["length"]), float(get["cov."]), int(get["mult."])
            except ValueError:
                raise ValueError(f"line {n}: length, cov. and mult. must be numbers") from None
            if length < 1 or coverage < 0 or not math.isfinite(coverage) or multiplicity < 0:
                raise ValueError(f"line {n}: impossible length, coverage or multiplicity")
            flags = {}
            for key, column in (("circular", "circ."), ("repeat", "repeat")):
                if get[column] not in ("Y", "N"):
                    raise ValueError(f"line {n}: {column} must be Y or N, not {get[column]!r}")
                flags[key] = get[column] == "Y"
            alt = get.get("alt_group", "*")
            out.append({"name": name, "length": length, "coverage": coverage, **flags, "multiplicity": multiplicity,
                        "alt_group": None if alt in ("*", "") else alt, "graph_path": get["graph_path"]})
        if not out:
            raise ValueError("assembly_info.txt lists no contigs")
        return out

    @staticmethod
    def parse_log(text: str) -> dict[str, Any]:
        """Values Flye reports in its log (flye.log): read totals, chosen minimum overlap, coverage, final summary."""
        out: dict[str, Any] = {}
        for key, pattern in _LOG_INT.items():
            if m := pattern.search(text):
                out[key] = int(m.group(1))
        if m := _READS_NX.search(text):
            out["reads_n50"], out["reads_n90"] = int(m.group(1)), int(m.group(2))
        stage, rates = None, {}
        for m in _ERROR_RATE.finditer(text):
            if m.group(1):
                stage = m.group(1)
            elif stage:
                rates[stage] = float(m.group(2))
        if rates:
            out["alignment_error_rate"] = rates
        out["warnings"] = [m.group(1).strip() for m in _COVERAGE_WARNING.finditer(text)]
        out["stages_seen"] = [m.group(1) for m in _STAGE.finditer(text)]
        return out

    @staticmethod
    def failure_reason(log_text: str, returncode: int | None) -> str | None:
        """A plain-language reason for a failed run, from Flye's own error lines; None when none is recognised."""
        errors = [m.group(1).strip() for m in _ERROR.finditer(log_text)]
        errors = [e for e in errors if e != "Pipeline aborted" and not e.startswith("Command '")]
        stages = _STAGE.findall(log_text)
        where = f" during the {stages[-1]} stage" if stages else ""
        if f"{SAMTOOLS_HELPER}: not found" in log_text:
            return (f"Flye could not run {SAMTOOLS_HELPER}{where}, so its consensus was empty. Install samtools "
                    "(ARVA links flye-samtools to it when the Flye installation lacks it)")
        if "Looks like the system ran out of memory" in log_text or returncode in (-9, 137):
            return (f"Flye ran out of memory{where} (the operating system stopped it). Free memory, or for large "
                    "genomes use --asm-coverage with a genome size to assemble the first stage from the longest "
                    "reads only")
        for e in errors:
            if e.startswith("No reads above minimum length threshold"):
                return (f"Flye found no read longer than the minimum overlap ({e}). The reads may be too short for "
                        "Flye, or the minimum overlap too high")
            if e.startswith(("No disjointigs were assembled", "No contigs were assembled")):
                return (f"Flye could not assemble the reads{where}: {e}. There may be too few reads or too little "
                        "coverage, or the read type may not match the data")
        if errors:
            return f"Flye failed{where}: {errors[-1]}"
        return None


def samtools_helper(flye_path: str) -> dict[str, Any]:
    """How the flye-samtools that Flye calls through the shell is provided: on PATH, next to the flye executable
    (that folder must then be put on Flye's PATH), by an ARVA link to samtools, or not at all."""
    on_path = shutil.which(SAMTOOLS_HELPER, path=os.environ.get("PATH", ""))
    if on_path:
        return {"provided_by": "installation", "samtools": on_path, "path_prepend": None}
    beside = shutil.which(SAMTOOLS_HELPER, path=str(Path(flye_path).parent))
    if beside:
        return {"provided_by": "installation", "samtools": beside, "path_prepend": str(Path(flye_path).parent)}
    samtools = resolve_executable("samtools", "samtools")
    if samtools:
        return {"provided_by": "arva_link", "samtools": samtools, "path_prepend": None}
    return {"provided_by": "missing", "samtools": None, "path_prepend": None}


def helper_version(executable: str) -> str | None:
    """The version samtools prints on its first --version line ("samtools 1.19.2"), or None."""
    try:
        with isolated_home() as home:
            # samtools also prints its compiler flags, which can hold non-UTF-8 bytes.
            proc = subprocess.run([executable, "--version"], capture_output=True, text=True, errors="replace",
                                  timeout=60, env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"\S+ (\S+)", proc.stdout)
    return m.group(1) if m else None


# --- Read-type suggestion (heuristic) ----------------------------------------------------------------------

HQ_MAX_ERROR = 0.05  # Flye: --nano-hq is for reads with < 5% error (--help, README release 2.9)
Q20_ERROR = 0.01


def pooled_error_rate(files: list[tuple[float, int]]) -> float | None:
    """Mean error probability over all bases of several files, from each file's error-averaged base quality
    (mean_base_quality = -10 log10(mean error probability)) weighted by its number of bases."""
    total = sum(b for _, b in files)
    if not total:
        return None
    return sum(10 ** (-q / 10) * b for q, b in files) / total


def suggest_read_type(platform: str | None, error_rate: float | None, basecall_models: list[str],
                      pacbio_read_types: list[str]) -> dict[str, Any]:
    """A heuristic suggestion for Flye's read type; the user decides.

    platform: "nanopore" or "pacbio" from the sample's metadata or the read headers, else None.
    error_rate: mean error probability implied by the base qualities (an estimate written by the basecaller).
    """
    q = None if error_rate is None else -10 * math.log10(max(error_rate, 1e-12))
    out: dict[str, Any] = {"heuristic": True, "value": None, "basis": None, "platform": platform,
                           "mean_error_rate": error_rate, "mean_base_quality": q,
                           "q20_read_error_note": False, "sup_model_but_low_quality": False}
    if platform == "nanopore":
        sup = any(re.search(r"(^|[_@-])sup([_@-]|$)", m, re.IGNORECASE) for m in basecall_models)
        if error_rate is not None:
            hq = error_rate <= HQ_MAX_ERROR
            out["value"] = "nano-hq" if hq else "nano-raw"
            out["basis"] = "error_at_most_5_percent" if hq else "error_above_5_percent"
            out["q20_read_error_note"] = error_rate <= Q20_ERROR
            out["sup_model_but_low_quality"] = sup and not hq
        elif sup:
            out["value"], out["basis"] = "nano-hq", "sup_basecall_model"
        else:
            out["basis"] = "no_quality_or_model"
    elif platform == "pacbio":
        if error_rate is not None and error_rate <= Q20_ERROR:
            out["value"], out["basis"] = "pacbio-hifi", "quality_at_least_q20"
        elif error_rate is None and "ccs" in pacbio_read_types:
            out["value"], out["basis"] = "pacbio-hifi", "ccs_read_names"
        elif "subread" in pacbio_read_types:
            out["value"], out["basis"] = "pacbio-raw", "subread_read_names"
        else:
            out["basis"] = "no_quality_or_read_names"
    else:
        out["basis"] = "platform_unknown"
    return out
