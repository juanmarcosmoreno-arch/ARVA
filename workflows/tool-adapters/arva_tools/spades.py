"""SPAdes — de Bruijn graph assembler for short reads; ARVA runs it on bacterial isolates.

Verified against SPAdes 3.15.5 (Ubuntu package 3.15.5+dfsg-7, the same upstream release as Debian bookworm's
3.15.5+dfsg-2): `spades.py --help`, its pipeline source (spades_pipeline/options_parser.py, options_storage.py,
stages/, executors/executor_local.py), the 3.15.5 README and real runs on ARVA's synthetic genome:

* Modes. --isolate ("highly recommended for high-coverage isolate and multi-cell data") skips read error
  correction (it implies --only-assembler) and is refused together with --careful, --mismatch-correction or
  --only-error-correction. --careful runs BayesHammer read correction and the mismatch corrector. With no mode
  SPAdes warns and runs read correction, then assembly ("standard" here).
* -k takes a comma-separated list of odd values from 1 to 127, used in the order given (SPAdes does not sort them);
  ARVA requires them ascending and distinct. Without -k SPAdes chooses them from the longest read: 21,33,55 below
  150 bp, 21,33,55,77 from 150 bp, 21,33,55,77,99,127 from 250 bp; it drops values not below the read length,
  also user-given ones, and says so in its log. Each value runs as a stage "K<k>", so ARVA reads the values used
  from the log.
* --cov-cutoff is a positive number, 'auto' or 'off' (SPAdes' default). -m is a memory limit in GB that SPAdes
  enforces (a program that exceeds it stops with "Cannot allocate memory"); without it SPAdes takes
  min(250, available memory). Threads default to 16. ARVA passes all three explicitly.
* Every stage is announced as "===== <name> started."; the planned stages are written to run_spades.yaml in the
  output folder before the first starts (entries whose short_name ends in "_finish" announce no start).
* Contig and scaffold names are NODE_<n>_length_<bp>_cov_<coverage>. The coverage is the k-mer coverage of the
  largest k: how many times, on average, each of the contig's k-mers occurs in the reads (the GFA's KC count over
  the segment's k-mers). It is not read depth: for reads of length L, read depth ≈ k-mer coverage x L / (L - k + 1),
  less where reads have errors. SPAdes does not report circularity.
* Debian's /usr/bin/spades.py is a /bin/sh wrapper that expands its arguments unquoted: a path with white space or
  a glob character would be split or expanded, so ARVA refuses such paths. SPAdes recognises read files by their
  name (.fastq or .fq, optionally .gz).
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

MODES = ("isolate", "careful", "standard")
OUTPUT_CHOICES = ("contigs", "scaffolds")
COV_CUTOFF_WORDS = ("off", "auto")
MIN_K, MAX_K = 1, 127
OUTPUTS = ("contigs.fasta", "scaffolds.fasta", "assembly_graph_with_scaffolds.gfa", "spades.log", "params.txt")
PLAN_FILE = "run_spades.yaml"
WRAPPER_UNSAFE = re.compile(r"[\s*?\[\]]")

_READ_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fastq|fq)(\.gz)?")
_STAGE = re.compile(r"^===== (.+?) started\.\s*$")
_K_STAGE = re.compile(r"^===== K(\d+) started\.", re.M)
_K_MESSAGE = re.compile(r"^(?:Default k-mer sizes were set to|K-mer sizes were set to) .+$", re.M)
_WARNING = re.compile(r"^== Warning ==\s+(.+?)\s*$", re.M)
_ERROR = re.compile(r"^== Error ==\s+(.+?)\s*$", re.M)
_CORE_ERROR = re.compile(r"\sERROR\s+\S.*?\)\s+(.+?)\s*$", re.M)
_MODE_LINE = re.compile(r"^Mode: (.+?)\s*$", re.M)
_NODE = re.compile(r"NODE_(\d+)_length_(\d+)_cov_(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_PLAN_STAGE = re.compile(r"^- STAGE: (.+?)\s*$")
_PLAN_SHORT = re.compile(r"^\s+short_name: (\S+)\s*$")
_OUT_OF_MEMORY = ("Cannot allocate memory", "std::bad_alloc", "Not enough memory",
                  "too many k-mers to fit into available memory", "out of memory when allocating")


@dataclass
class SpadesParams:
    mode: str = "isolate"
    k: list[int] | None = None
    cov_cutoff: str | float = "off"
    memory_gb: int = 16
    threads: int = 1
    output: str = "contigs"

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> SpadesParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def validate(self) -> None:
        errors = []
        if self.mode not in MODES:
            errors.append(f"mode must be one of {', '.join(MODES)}")
        if self.output not in OUTPUT_CHOICES:
            errors.append(f"output must be one of {', '.join(OUTPUT_CHOICES)}")
        if self.k is not None:
            if not self.k or not all(isinstance(k, int) and not isinstance(k, bool) for k in self.k):
                errors.append("k must be a non-empty list of whole numbers")
            elif any(k % 2 == 0 or not MIN_K <= k <= MAX_K for k in self.k):
                errors.append(f"every k must be odd and between {MIN_K} and {MAX_K}")
            elif any(b <= a for a, b in zip(self.k, self.k[1:], strict=False)):
                errors.append("k values must be ascending and distinct (SPAdes uses them in the order given)")
        cutoff = self.cov_cutoff
        if isinstance(cutoff, str):
            if cutoff not in COV_CUTOFF_WORDS:
                errors.append("cov_cutoff must be 'off', 'auto' or a positive number")
        elif isinstance(cutoff, bool) or not isinstance(cutoff, int | float) or not math.isfinite(cutoff) or cutoff <= 0:
            errors.append("cov_cutoff must be 'off', 'auto' or a positive number")
        if not isinstance(self.memory_gb, int) or self.memory_gb < 1:
            errors.append("memory_gb must be a whole number of GB, at least 1")
        if not 1 <= self.threads <= 128:
            errors.append("threads must be between 1 and 128")
        if errors:
            raise ValueError("; ".join(errors))

    def flags(self, paired: bool, unpaired: bool) -> list[str]:
        """Every SPAdes option the command uses, to check each against the installed version's --help."""
        used = ["-o", "-t", "-m", "--cov-cutoff"]
        if self.mode != "standard":
            used.append(f"--{self.mode}")
        if paired:
            used += ["-1", "-2"]
        if unpaired:
            used.append("-s")
        if self.k:
            used.append("-k")
        return used

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(v: float | int) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def check_paths(paths: list[Path]) -> None:
    for p in paths:
        if WRAPPER_UNSAFE.search(str(p)):
            raise ValueError(f"paths with white space or the characters * ? [ ] cannot be passed to SPAdes (its "
                             f"Debian launcher would split or expand them): {p}")


def parse_node_name(name: str) -> dict[str, Any] | None:
    """NODE_<n>_length_<bp>_cov_<k-mer coverage> → its parts; None for another name."""
    m = _NODE.fullmatch(name)
    if not m:
        return None
    return {"node": int(m.group(1)), "length": int(m.group(2)), "kmer_coverage": float(m.group(3))}


class SpadesAdapter(ToolAdapter):
    info = ToolInfo(
        id="spades",
        name="SPAdes",
        description="De Bruijn graph assembler for short reads (Illumina); in isolate mode it assembles bacterial "
        "isolates and writes contigs, scaffolds and the assembly graph, each sequence with its k-mer coverage.",
        homepage="https://github.com/ablab/spades",
        license="GPL-2.0-only",
        citation="Prjibelski A, Antipov D, Meleshko D, Lapidus A, Korobeynikov A. Using SPAdes de novo assembler. "
        "Curr Protoc Bioinformatics 2020;70(1):e102.",
        citation_url="https://doi.org/10.1002/cpbi.102",
        executable="spades.py",
        categories=("assembly", "short reads"),
        input_formats=("fastq", "fastq.gz"),
        output_formats=("fasta", "gfa"),
        min_version="3.14",
        tested_versions=("3.15.5",),
        install={"apt": "spades", "conda": "bioconda::spades"},
    )
    # `spades.py --version` prints "SPAdes genome assembler v3.15.5".
    version_pattern = re.compile(r"SPAdes(?: genome assembler)? v(\d+\.\d+(?:\.\d+)?)")

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return help_options(read_help(executable))

    @staticmethod
    def argv(executable: str, params: SpadesParams, out_dir: Path, supported: frozenset[str], *,
             r1: Path | None = None, r2: Path | None = None, unpaired: Path | None = None) -> list[str]:
        params.validate()
        if (r1 is None) != (r2 is None):
            raise ValueError("paired-end reads need both the R1 (-1) and the R2 (-2) file")
        if r1 is None and unpaired is None:
            raise ValueError("SPAdes needs paired-end reads, unpaired reads or both")
        reads = [p for p in (r1, r2, unpaired) if p is not None]
        check_paths([*reads, out_dir])
        for r in reads:
            if not _READ_NAME.fullmatch(r.name):
                raise ValueError(f"unsafe or unrecognised read file name for SPAdes: {r.name}")
        if missing := [f for f in params.flags(r1 is not None, unpaired is not None) if f not in supported]:
            raise ValueError(f"this SPAdes version does not offer {', '.join(missing)} (not in its --help)")
        a = [executable]
        if params.mode != "standard":
            a.append(f"--{params.mode}")
        if r1 is not None and r2 is not None:
            a += ["-1", str(r1), "-2", str(r2)]
        if unpaired is not None:
            a += ["-s", str(unpaired)]
        a += ["-o", str(out_dir), "-t", str(params.threads), "-m", str(params.memory_gb),
              "--cov-cutoff", params.cov_cutoff if isinstance(params.cov_cutoff, str) else _num(params.cov_cutoff)]
        if params.k:
            a += ["-k", ",".join(map(str, params.k))]
        return a

    @staticmethod
    def stage(line: str) -> str | None:
        m = _STAGE.match(line)
        return m.group(1) if m else None

    @staticmethod
    def planned_stages(plan_text: str) -> tuple[str, ...] | None:
        """The stages SPAdes will announce, from the run_spades.yaml it writes before starting; None if unreadable."""
        names, current = [], None
        for line in plan_text.splitlines():
            if m := _PLAN_STAGE.match(line):
                current = m.group(1)
            elif (m := _PLAN_SHORT.match(line)) and current is not None:
                if not m.group(1).endswith("_finish"):
                    names.append(current)
                current = None
        return tuple(names) or None

    @staticmethod
    def parse_log(text: str) -> dict[str, Any]:
        """What SPAdes reports in spades.log: the k-mer sizes it ran (and why, when it changed them), its mode
        line, its warnings and the stages it announced."""
        k_values: list[int] = []
        for k in _K_STAGE.findall(text):
            if int(k) not in k_values:
                k_values.append(int(k))
        mode = _MODE_LINE.search(text)
        return {
            "k_values": k_values,
            "k_messages": _K_MESSAGE.findall(text),
            "mode_line": mode.group(1) if mode else None,
            "warnings": list(dict.fromkeys(_WARNING.findall(text))),
            "stages_seen": [m.group(1) for line in text.splitlines() if (m := _STAGE.match(line))],
            "finished": "======= SPAdes pipeline finished." in text,
        }

    @staticmethod
    def failure_reason(log_text: str, returncode: int | None, memory_gb: int | None = None) -> str | None:
        """A plain-language reason for a failed run, from SPAdes' own error lines; None when none is recognised."""
        stages = [m.group(1) for line in log_text.splitlines() if (m := _STAGE.match(line))]
        where = f" during the {stages[-1]} stage" if stages else ""
        limit = f" (memory limit -m {memory_gb} GB)" if memory_gb else ""
        core = _CORE_ERROR.findall(log_text)
        if any(s in log_text for s in _OUT_OF_MEMORY):
            detail = next((e for e in core if any(s in e for s in _OUT_OF_MEMORY)), None)
            return (f"SPAdes ran out of memory{where}{limit}" + (f": {detail}" if detail else "") +
                    ". Give SPAdes more memory if the computer has it, or assemble fewer reads")
        if returncode in (-9, 137):
            return (f"SPAdes was stopped by the operating system{where}, most likely because the computer ran out of "
                    f"memory before SPAdes' own limit{limit} was reached. Set the memory limit to the memory that is "
                    "actually free")
        errors = _ERROR.findall(log_text)
        for e in errors:
            if e.startswith("file with reads has unsupported format"):
                return f"SPAdes did not accept a read file: {e}"
            if "finished abnormally" in e:
                status = re.search(r"OS return value: (-?\d+)", e)
                program = re.search(r"/(spades-[\w-]+)", e)
                name = program.group(1) if program else "a SPAdes program"
                return (f"SPAdes failed{where}: {name} stopped" + (f" with status {status.group(1)}" if status else "")
                        + (f" ({core[-1]})" if core else ""))
        if errors:
            return f"SPAdes failed{where}: {errors[-1]}"
        return None
