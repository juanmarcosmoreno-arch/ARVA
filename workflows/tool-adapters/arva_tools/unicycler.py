"""Unicycler — assembly pipeline for bacterial isolates from short reads, long reads, or both (hybrid).

Verified against Unicycler 0.5.0 (Ubuntu package 0.5.0+dfsg-1, the same upstream release as Debian bookworm's):
`unicycler --help_all`, its source (unicycler.py, spades_func.py, misc.py, assembly_graph.py,
assembly_graph_segment.py, string_graph.py, miniasm_assembly.py, blast_func.py), the 0.5.0 README and real runs on
ARVA's synthetic genome:

* Inputs: -1/-2 (both or neither), -s unpaired short reads, -l long reads. Short reads only: SPAdes over a range of
  k-mer sizes (from the median read length unless --kmers gives them: odd, 11-127, distinct), keeping the best
  graph. Long reads only: miniasm (built into Unicycler) and Racon polishing. Both: short-read-first hybrid
  assembly, the short-read graph bridged with the long reads. The README (2022 update) recommends long-read-first
  assembly over Unicycler when long reads are deep, and Unicycler's hybrid mode when they are not.
* Helpers: SPAdes ≥ 3.13.1 with short reads (Unicycler runs it with --isolate and `-m 1024`, GB, unless -m is in
  --spades_options), racon with long reads, makeblastdb and tblastn to rotate completed circular replicons to a
  dnaA/repA start. Unicycler checks them at start and prints a dependency table (program, version, status). Pilon,
  bowtie2 and bcftools, which Debian's package still depends on, are not called by 0.5.0. ARVA passes each helper's
  path, and `--spades_options=-m <GB>` so that SPAdes keeps to ARVA's memory limit.
* --mode conservative|normal|bold is the bridging mode (minimum bridge quality 25, 10, 1); --keep 0-3 is how much is
  kept (0: final files only; 1, the default: also graphs at main checkpoints; 2-3 add alignments and temporary
  files); --min_fasta_length (100) leaves shorter sequences out of assembly.fasta only; --depth_filter (0.25)
  removes contigs below that fraction of the chromosomal depth; --linear_seqs (0) is the expected number of linear
  sequences.
* Log: each section starts with "<Title> (YYYY-MM-DD HH:MM:SS)" over a dashed line; the console copy is coloured
  with ANSI escapes, unicycler.log in the output folder is plain. Many sections only appear when there is work for
  them. Errors are "Error: <message>" with exit status 1; when SPAdes fails, Unicycler's message omits SPAdes'
  reason, which stays in <out>/spades_assembly/spades.log.
* Outputs: assembly.fasta, assembly.gfa, unicycler.log. With short reads (short-read and hybrid modes) each FASTA
  header is ">N length=<bp> depth=<d>x", plus " circular=true" for a completed circular replicon: one segment whose
  only links join its end to its start. Depth is relative: read depth divided by the length-weighted median depth
  of the 10 longest segments, so the chromosome is near 1.00x. In long-read-only mode Unicycler 0.5.0 writes bare
  names (">1"); its assembly.gfa still holds each segment's depth (dp:f, relative to the length-weighted median
  depth of all segments) and the links, so ARVA reads depth from the dp tag and applies Unicycler's own definition
  of a completed circular replicon to the links.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from arva_tools.base import (
    DetectedTool,
    ToolAdapter,
    ToolInfo,
    ToolStatus,
    help_options,
    read_help,
    resolve_executable,
)
from arva_tools.spades import check_paths

MODES = ("conservative", "normal", "bold")
ASSEMBLY_MODES = ("short", "long", "hybrid")
KEEP_LEVELS = (0, 1)
VERBOSITY = 1
MIN_KMER, MAX_KMER = 11, 127
OUTPUTS = ("assembly.fasta", "assembly.gfa", "unicycler.log")
SPADES_DIR = "spades_assembly"
# (ARVA tool id, executable) of each program Unicycler calls.
HELPERS = {"spades": ("spades", "spades.py"), "racon": ("racon", "racon"),
           "makeblastdb": ("makeblastdb", "makeblastdb"), "tblastn": ("tblastn", "tblastn")}
# Sections seen in ARVA's validation runs (0.5.0, --verbosity 1); some only appear when there is work for them.
STAGES = {
    "short": ("Starting Unicycler", "Choosing k-mer range for assembly", "SPAdes assemblies",
              "Determining graph multiplicity", "Cleaning graph", "Creating SPAdes contig bridges",
              "Creating loop unrolling bridges", "Applying bridges", "Bridged assembly graph",
              "Rotating completed replicons", "Assembly complete"),
    "hybrid": ("Starting Unicycler", "Choosing k-mer range for assembly", "SPAdes assemblies",
               "Determining graph multiplicity", "Cleaning graph", "Creating SPAdes contig bridges",
               "Creating loop unrolling bridges", "Loading reads", "Assembling contigs and long reads with miniasm",
               "Polishing miniasm assembly with Racon", "Creating miniasm/Racon bridges",
               "Creating simple long read bridges", "Determining low score threshold", "Aligning reads",
               "Read alignment summary", "Building long read bridges", "Applying bridges", "Bridged assembly graph",
               "Rotating completed replicons", "Assembly complete"),
    "long": ("Starting Unicycler", "Loading reads", "Assembling contigs and long reads with miniasm",
             "Polishing miniasm assembly with Racon", "Rotating completed replicons", "Assembly complete"),
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_READ_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fastq|fq)(\.gz)?")
_SECTION = re.compile(r"^(\S.*?) \(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\)\s*$")
_HEADER = re.compile(r"(\S+) length=(\d+) depth=(\d+(?:\.\d+)?)x( circular=true)?")
_ERROR = re.compile(r"^Error: (.*)$", re.M)
_VERSION = re.compile(r"^Unicycler version: v(\S+)", re.M)
_KMER_RANGE = re.compile(r"^K-mer range: ([\d, ]+)$", re.M)
_BEST_KMER = re.compile(r"^\s*(\d+)\s+\d+\s+\d+\s+\S+\s+← best", re.M)
_DEPENDENCY = re.compile(r"^  (spades|racon|makeblastdb|tblastn)\s+(\S*)\s+(good|not used|not found|too old|too new|bad)",
                         re.M)
_COMPONENT = re.compile(r"^\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(complete|incomplete)\s*$", re.M)


@dataclass
class UnicyclerParams:
    assembly_mode: str
    mode: str = "normal"
    keep: int = 1
    kmers: list[int] | None = None
    depth_filter: float = 0.25
    min_fasta_length: int = 100
    linear_seqs: int = 0
    threads: int = 1
    spades_memory_gb: int = 16

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> UnicyclerParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    @property
    def short(self) -> bool:
        return self.assembly_mode in ("short", "hybrid")

    @property
    def long(self) -> bool:
        return self.assembly_mode in ("long", "hybrid")

    def validate(self) -> None:
        errors = []
        if self.assembly_mode not in ASSEMBLY_MODES:
            errors.append(f"assembly_mode must be one of {', '.join(ASSEMBLY_MODES)}")
        if self.mode not in MODES:
            errors.append(f"mode must be one of {', '.join(MODES)}")
        if self.keep not in KEEP_LEVELS:
            errors.append("keep must be 0 (final files only) or 1 (also the graphs at main checkpoints)")
        if self.kmers is not None:
            if not self.short:
                errors.append("kmers only apply to the SPAdes step, which needs short reads")
            elif not self.kmers or not all(isinstance(k, int) and not isinstance(k, bool) for k in self.kmers):
                errors.append("kmers must be a non-empty list of whole numbers")
            elif any(k % 2 == 0 or not MIN_KMER <= k <= MAX_KMER for k in self.kmers):
                errors.append(f"every k-mer size must be odd and between {MIN_KMER} and {MAX_KMER}")
            elif any(b <= a for a, b in zip(self.kmers, self.kmers[1:], strict=False)):
                errors.append("kmers must be ascending and distinct")
        if isinstance(self.depth_filter, bool) or not isinstance(self.depth_filter, int | float) \
                or not math.isfinite(self.depth_filter) or not 0 <= self.depth_filter <= 1:
            errors.append("depth_filter is a fraction of the chromosomal depth and must be between 0 and 1")
        if not isinstance(self.min_fasta_length, int) or self.min_fasta_length < 1:
            errors.append("min_fasta_length must be a whole number of bp, at least 1")
        if not isinstance(self.linear_seqs, int) or self.linear_seqs < 0:
            errors.append("linear_seqs must be a whole number, at least 0")
        if not 1 <= self.threads <= 128:
            errors.append("threads must be between 1 and 128")
        if not isinstance(self.spades_memory_gb, int) or self.spades_memory_gb < 1:
            errors.append("spades_memory_gb must be a whole number of GB, at least 1")
        if errors:
            raise ValueError("; ".join(errors))

    def flags(self, paired: bool, unpaired: bool) -> list[str]:
        """Every Unicycler option the command uses, to check each against the installed version's --help_all."""
        used = ["-o", "-t", "--mode", "--keep", "--verbosity", "--min_fasta_length", "--linear_seqs",
                "--makeblastdb_path", "--tblastn_path"]
        if paired:
            used += ["-1", "-2"]
        if unpaired:
            used.append("-s")
        if self.short:
            used += ["--spades_path", "--spades_options", "--depth_filter"] + (["--kmers"] if self.kmers else [])
        if self.long:
            used += ["-l", "--racon_path"]
        return used

    def stages(self) -> tuple[str, ...]:
        stages = STAGES[self.assembly_mode]
        if self.kmers:
            stages = tuple(s for s in stages if s != "Choosing k-mer range for assembly")
        return stages

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(v: float | int) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def helper_paths() -> dict[str, str | None]:
    """Where each program Unicycler calls is found (ARVA_TOOL_<ID>, ARVA_TOOLS_PATH, then PATH)."""
    return {name: resolve_executable(tool_id, exe) for name, (tool_id, exe) in HELPERS.items()}


def modes_available(paths: dict[str, str | None]) -> list[str]:
    if not (paths["makeblastdb"] and paths["tblastn"]):
        return []
    return [m for m, needs in (("short", ("spades",)), ("long", ("racon",)), ("hybrid", ("spades", "racon")))
            if all(paths[n] for n in needs)]


def plain(text: str) -> str:
    return _ANSI.sub("", text)


class UnicyclerAdapter(ToolAdapter):
    info = ToolInfo(
        id="unicycler",
        name="Unicycler",
        description="Assembly pipeline for bacterial isolates: short reads (an optimised SPAdes run), long reads "
        "(miniasm and Racon) or both (short-read-first hybrid assembly); circularises and rotates complete replicons.",
        homepage="https://github.com/rrwick/Unicycler",
        license="GPL-3.0-or-later",
        citation="Wick RR, Judd LM, Gorrie CL, Holt KE. Unicycler: Resolving bacterial genome assemblies from short "
        "and long sequencing reads. PLoS Comput Biol 2017;13(6):e1005595.",
        citation_url="https://doi.org/10.1371/journal.pcbi.1005595",
        executable="unicycler",
        categories=("assembly", "short reads", "long reads", "hybrid"),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("fasta", "gfa"),
        min_version="0.5.0",
        tested_versions=("0.5.0",),
        install={"apt": "unicycler", "conda": "bioconda::unicycler"},
    )
    # `unicycler --version` prints "Unicycler v0.5.0".
    version_pattern = re.compile(r"Unicycler v(\d+\.\d+\.\d+)")

    def detect(self) -> DetectedTool:
        d = super().detect()
        if d.status is not ToolStatus.available:
            return d
        paths = helper_paths()
        missing = [n for n in ("makeblastdb", "tblastn") if not paths[n]]
        if missing:
            d.status, d.reason = ToolStatus.failed, "blast_missing"
            d.message = (f"Unicycler needs {' and '.join(missing)} (NCBI BLAST+) to rotate circular replicons to a "
                         "standard start gene; install ncbi-blast+")
            return d
        notes = []
        if not paths["spades"]:
            d.reason = "spades_missing"
            notes.append("SPAdes was not found, so only long-read assembly is possible")
        if not paths["racon"]:
            d.reason = "racon_missing" if paths["spades"] else "helpers_missing"
            notes.append("Racon was not found, so only short-read assembly is possible")
        if notes:
            d.message = ". ".join(filter(None, [d.message, *notes]))
        return d

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(read_help(executable, ("--help_all",)))

    @staticmethod
    def argv(executable: str, params: UnicyclerParams, out_dir: Path, supported: frozenset[str],
             helpers: dict[str, str | None], *, r1: Path | None = None, r2: Path | None = None,
             unpaired: Path | None = None, long: Path | None = None) -> list[str]:
        params.validate()
        if (r1 is None) != (r2 is None):
            raise ValueError("paired-end reads need both the R1 (-1) and the R2 (-2) file")
        has_short, has_long = r1 is not None or unpaired is not None, long is not None
        if (has_short, has_long) != (params.short, params.long):
            needs = {"short": "short reads and no long reads", "long": "long reads and no short reads",
                     "hybrid": "both short and long reads"}
            raise ValueError(f"a {params.assembly_mode}-read Unicycler assembly needs {needs[params.assembly_mode]}")
        reads = [p for p in (r1, r2, unpaired, long) if p is not None]
        check_paths([*reads, out_dir])
        for r in reads:
            if not _READ_NAME.fullmatch(r.name):
                raise ValueError(f"unsafe or unrecognised read file name for Unicycler: {r.name}")
        needed = ["makeblastdb", "tblastn"] + (["spades"] if params.short else []) + (["racon"] if params.long else [])
        if missing := [n for n in needed if not helpers.get(n)]:
            raise ValueError(f"Unicycler needs {', '.join(missing)} for this assembly, and it was not found")
        if missing := [f for f in params.flags(r1 is not None, unpaired is not None) if f not in supported]:
            raise ValueError(f"this Unicycler version does not offer {', '.join(missing)} (not in its --help_all)")
        a = [executable]
        if r1 is not None and r2 is not None:
            a += ["-1", str(r1), "-2", str(r2)]
        if unpaired is not None:
            a += ["-s", str(unpaired)]
        if long is not None:
            a += ["-l", str(long)]
        a += ["-o", str(out_dir), "-t", str(params.threads), "--mode", params.mode, "--keep", str(params.keep),
              "--verbosity", str(VERBOSITY), "--min_fasta_length", str(params.min_fasta_length),
              "--linear_seqs", str(params.linear_seqs)]
        if params.short:
            a += ["--depth_filter", _num(params.depth_filter)]
            if params.kmers:
                a += ["--kmers", ",".join(map(str, params.kmers))]
            a += ["--spades_path", str(helpers["spades"]), f"--spades_options=-m {params.spades_memory_gb}"]
        if params.long:
            a += ["--racon_path", str(helpers["racon"])]
        a += ["--makeblastdb_path", str(helpers["makeblastdb"]), "--tblastn_path", str(helpers["tblastn"])]
        return a

    @staticmethod
    def stage(line: str) -> str | None:
        m = _SECTION.match(plain(line))
        return m.group(1) if m else None

    @staticmethod
    def parse_headers(names: list[str]) -> dict[str, dict[str, Any]]:
        """FASTA header lines (without '>') of a short-read or hybrid assembly → length, relative depth and
        circularity by contig name. Raises ValueError for a header without Unicycler's tags."""
        out: dict[str, dict[str, Any]] = {}
        for header in names:
            m = _HEADER.fullmatch(header.strip())
            if not m:
                raise ValueError(f"not a Unicycler contig header (expected 'N length=… depth=…x'): {header[:80]!r}")
            out[m.group(1)] = {"length": int(m.group(2)), "depth": float(m.group(3)), "circular": bool(m.group(4))}
        return out

    @staticmethod
    def parse_gfa_annotations(text: str) -> dict[str, dict[str, Any]]:
        """Per segment of Unicycler's assembly.gfa: length (LN or sequence), relative depth (dp:f) and whether it is
        a completed circular replicon by Unicycler's definition (its only links join its end to its start)."""
        segments: dict[str, dict[str, Any]] = {}
        touching: dict[str, list[tuple[str, str, str, str]]] = {}
        for n, line in enumerate(text.splitlines(), start=1):
            f = line.rstrip("\r").split("\t")
            if f[0] == "S":
                if len(f) < 3:
                    raise ValueError(f"line {n}: segment line without a sequence field")
                tags = {t[:2]: t[5:] for t in f[3:] if len(t) > 5 and t[2] == ":" and t[4] == ":"}
                if "dp" not in tags:
                    raise ValueError(f"line {n}: segment {f[1]} has no dp tag")
                try:
                    length = int(tags["LN"]) if "LN" in tags else len(f[2])
                    depth = float(tags["dp"])
                except ValueError:
                    raise ValueError(f"line {n}: segment {f[1]} has a non-numeric LN or dp tag") from None
                segments[f[1]] = {"length": length, "depth": depth}
            elif f[0] == "L":
                if len(f) < 5:
                    raise ValueError(f"line {n}: link line needs two segments and their orientations")
                link = (f[1], f[2], f[3], f[4])
                touching.setdefault(f[1], []).append(link)
                if f[3] != f[1]:
                    touching.setdefault(f[3], []).append(link)
        for name, seg in segments.items():
            own = touching.get(name, [])
            seg["circular"] = bool(own) and all(a == b == name and ao == bo for a, ao, b, bo in own)
        return segments

    @staticmethod
    def parse_log(text: str) -> dict[str, Any]:
        """What Unicycler reports in unicycler.log: its version, the helpers it found, the k-mer range and the best
        k-mer, the completeness of each graph component, the sections it went through."""
        text = plain(text)
        version = _VERSION.search(text)
        k_range = _KMER_RANGE.search(text)
        best = _BEST_KMER.search(text)
        components = [{"component": int(m.group(1)), "segments": int(m.group(2)), "links": int(m.group(3)),
                       "length": int(m.group(4).replace(",", "")), "status": m.group(7)}
                      for m in _COMPONENT.finditer(text)]
        return {
            "version": version.group(1) if version else None,
            "dependencies": [{"program": m.group(1), "version": m.group(2) or None, "status": m.group(3)}
                             for m in _DEPENDENCY.finditer(text)],
            "kmer_range": [int(k) for k in k_range.group(1).split(",")] if k_range else None,
            "best_kmer": int(best.group(1)) if best else None,
            "components": components,
            "stages_seen": [m.group(1) for line in text.splitlines() if (m := _SECTION.match(line))],
        }

    @staticmethod
    def failure_reason(console_text: str, returncode: int | None, spades_log: str | None = None,
                       spades_memory_gb: int | None = None) -> str | None:
        """A plain-language reason for a failed run, from Unicycler's "Error:" lines and, when SPAdes failed inside
        Unicycler, from the SPAdes log it left; None when none is recognised."""
        from arva_tools.spades import SpadesAdapter

        text = plain(console_text)
        errors = [e.strip() for e in _ERROR.findall(text)]
        sections = [m.group(1) for line in text.splitlines() if (m := _SECTION.match(line))]
        where = f" during '{sections[-1]}'" if sections else ""
        if any(e.startswith("SPAdes encountered an error") for e in errors) and spades_log:
            reason = SpadesAdapter.failure_reason(spades_log, None, spades_memory_gb)
            if reason:
                return f"Unicycler stopped because SPAdes failed: {reason}"
        if returncode in (-9, 137):
            return (f"Unicycler was stopped by the operating system{where}, most likely because the computer ran out "
                    "of memory")
        if errors:
            return f"Unicycler failed{where}: {errors[-1] or 'see the log'}"
        return None
