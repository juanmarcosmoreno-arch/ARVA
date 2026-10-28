"""Pilon — improves an assembly with short-read alignments (base errors, small indels, gaps, local misassemblies).

Verified against Pilon 1.24 (Ubuntu package 1.24-3, the same upstream release as Debian bookworm's 1.24-2): `pilon
--help` (fixtures/polishing), the bytecode of its jar (Pilon$.class, Pilon$$anonfun$parseFixList$1.class,
Assembler$.class; javap) and real runs on the synthetic genome:

* Defaults read from the bytecode: --fix snps,indels,gaps,local ("all": the default fix list is exactly these four
  categories; a list without a leading + or - replaces it), --mindepth 0.1 (a fraction of the mean coverage, at
  least 5), --minmq 0, --minqual 0, --flank 10, --defaultqual 10, --gapmargin 100000, --mingap 10, --K 47 (its
  internal assembler), --chunksize 10000000, stray-pair scanning on. ARVA passes all of them explicitly.
* Pilon 1.24 has no thread option. Debian's /usr/bin/pilon runs `java -Xms128M -Xmx16384m -jar
  /usr/share/java/pilon.jar`, fixing the Java heap at 16 GB, so ARVA runs the jar with java and its own -Xmx, and
  removes JAVA_TOOL_OPTIONS, _JAVA_OPTIONS and JDK_JAVA_OPTIONS from the environment (they could change the heap).
  A heap that is too small ends the run with "java.lang.OutOfMemoryError: Java heap space".
* Debian's build prints "Pilon version [COMMIT] [DATE]": the version placeholders were never filled in. ARVA then
  takes the version from the Debian package that installed the jar (dpkg), and says so.
* --changes writes one line per change: "<contig>:<from>[-<to>] <contig>_pilon:<from>[-<to>] <old> <new>", "." for
  no bases. Each round appends "_pilon" to the contig names. A round that changes nothing writes an empty file.
* Pilon's own log line per contig "Corrected N snps; ...; corrected N small insertions totaling N bases, N small
  deletions totaling N bases" counts insertions and deletions in the new sequence, as the .changes file does.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from arva_tools.base import (
    DetectedTool,
    ToolAdapter,
    ToolInfo,
    ToolStatus,
    help_options,
    parse_version,
    resolve_executable,
)
from arva_tools.runner import isolated_home, tool_environment

FIX_CHOICES = ("snps", "indels", "gaps", "local")
MAX_ROUNDS = 5
FIXED_OPTIONS = (("--flank", "10"), ("--defaultqual", "10"), ("--gapmargin", "100000"), ("--mingap", "10"),
                 ("--K", "47"), ("--chunksize", "10000000"))
FLAGS = ("--genome", "--frags", "--unpaired", "--output", "--outdir", "--changes", "--fix", "--mindepth", "--minmq",
         "--minqual", *(f for f, _ in FIXED_OPTIONS))
_VERSION = re.compile(r"Pilon version (\d+\.\d+(?:\.\d+)?)")
_LAUNCHER_JAR = re.compile(r"-jar\s+[\"']?(/[^\s\"']+\.jar)")
_JAVA_VERSION = re.compile(r"version \"([^\"]+)\"")
_LOCATION = re.compile(r"(.+):(\d+)(?:-(\d+))?")
_PROCESSING = re.compile(r"^Processing (.+):(\d+)-(\d+)$")
_CONFIRMED = re.compile(r"^Confirmed (\d+) of (\d+) bases")
_CORRECTED = re.compile(r"^Corrected (\d+) snps; (\d+) ambiguous bases; corrected (\d+) small insertions totaling "
                        r"(\d+) bases, (\d+) small deletions totaling (\d+) bases")
_MEAN = re.compile(r"^Mean (frags|unpaired|total) coverage: (\d+)", re.M)
_FASTA_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fasta|fa)")
_SAFE_PREFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}")


@dataclass
class PilonParams:
    rounds: int = 1
    fix: list[str] = field(default_factory=lambda: list(FIX_CHOICES))
    mindepth: float = 0.1
    minmq: int = 0
    minqual: int = 0
    heap_gb: int = 8
    threads: int = 1
    stop_when_unchanged: bool = True

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> PilonParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def validate(self) -> None:
        errors = []
        whole = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
        if not whole(self.rounds) or not 1 <= self.rounds <= MAX_ROUNDS:
            errors.append(f"rounds must be between 1 and {MAX_ROUNDS}")
        if not self.fix or any(f not in FIX_CHOICES for f in self.fix) or len(set(self.fix)) != len(self.fix):
            errors.append(f"fix must list one or more of {', '.join(FIX_CHOICES)}, each once")
        if isinstance(self.mindepth, bool) or not isinstance(self.mindepth, int | float) \
                or not math.isfinite(self.mindepth) or self.mindepth <= 0 or self.mindepth > 1000:
            errors.append("mindepth must be above 0: a fraction of the mean coverage below 1, or a depth from 1")
        if not whole(self.minmq) or not 0 <= self.minmq <= 60:
            errors.append("minmq must be between 0 and 60")
        if not whole(self.minqual) or not 0 <= self.minqual <= 60:
            errors.append("minqual must be between 0 and 60")
        if not whole(self.heap_gb) or self.heap_gb < 1:
            errors.append("heap_gb must be a whole number of GB, at least 1")
        if not whole(self.threads) or not 1 <= self.threads <= 128:
            errors.append("threads must be between 1 and 128")
        if not isinstance(self.stop_when_unchanged, bool):
            errors.append("stop_when_unchanged must be true or false")
        if errors:
            raise ValueError("; ".join(errors))

    def fix_list(self) -> str:
        return ",".join(f for f in FIX_CHOICES if f in self.fix)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(v: float | int) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def locate_jar() -> tuple[str | None, str | None]:
    """(jar, launcher): ARVA_TOOL_PILON may name the jar itself; otherwise the jar a `pilon` launcher script runs
    with `-jar <path>.jar` (Debian's /usr/bin/pilon)."""
    override = os.environ.get("ARVA_TOOL_PILON")
    if override and override.endswith(".jar"):
        return (override if Path(override).is_file() else None), None
    launcher = resolve_executable("pilon", "pilon")
    if launcher is None:
        return None, None
    try:
        with open(launcher, "rb") as fh:
            head = fh.read(65536)
    except OSError:
        return None, launcher
    if b"\0" in head:
        return None, launcher
    m = _LAUNCHER_JAR.search(head.decode("utf-8", "replace"))
    return (m.group(1) if m and Path(m.group(1)).is_file() else None), launcher


def java_executable() -> str | None:
    return resolve_executable("java", "java")


def _run_quiet(argv: list[str]) -> subprocess.CompletedProcess | None:
    try:
        with isolated_home() as home:
            return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=120,
                                  env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


def java_version(java: str) -> str | None:
    """The version `java -version` prints ('openjdk version "21.0.12.1" ...'), or None."""
    proc = _run_quiet([java, "-version"])
    m = _JAVA_VERSION.search(proc.stdout + proc.stderr) if proc else None
    return m.group(1) if m else None


def debian_package_version(path: str) -> tuple[str, str] | None:
    """(package, version) of the Debian package that installed `path`, from dpkg; None elsewhere."""
    dpkg = shutil.which("dpkg-query")
    if dpkg is None:
        return None
    owner = _run_quiet([dpkg, "-S", os.path.realpath(path)])
    if owner is None or owner.returncode != 0 or ":" not in owner.stdout:
        return None
    package = owner.stdout.split(":", 1)[0].strip()
    version = _run_quiet([dpkg, "-W", "-f=${Version}", package])
    if version is None or version.returncode != 0 or not version.stdout.strip():
        return None
    return package, version.stdout.strip()


def upstream_version(debian_version: str) -> str:
    """'1.24-3' → '1.24' (no epoch, Debian revision or +dfsg suffix)."""
    v = debian_version.split(":", 1)[-1]
    v = v.rsplit("-", 1)[0] if "-" in v else v
    return re.split(r"[+~]", v)[0]


class PilonAdapter(ToolAdapter):
    info = ToolInfo(
        id="pilon",
        name="Pilon",
        description="Improves an assembly with short-read alignments: corrects bases and small insertions or "
        "deletions, fills gaps and fixes local misassemblies, and lists every change.",
        homepage="https://github.com/broadinstitute/pilon",
        license="GPL-2.0",
        citation="Walker BJ, Abeel T, Shea T, et al. Pilon: an integrated tool for comprehensive microbial variant "
        "detection and genome assembly improvement. PLoS One 2014;9(11):e112963.",
        citation_url="https://doi.org/10.1371/journal.pone.0112963",
        executable="pilon",
        categories=("polishing", "short reads"),
        input_formats=("fasta", "bam"),
        output_formats=("fasta", "changes"),
        min_version="1.23",
        tested_versions=("1.24",),
        install={"apt": "pilon", "conda": "bioconda::pilon"},
    )
    version_pattern = _VERSION

    def detect(self) -> DetectedTool:
        jar, launcher = locate_jar()
        if jar is None:
            if launcher is None:
                return DetectedTool(self.info, ToolStatus.not_installed, message="Executable not found")
            return DetectedTool(self.info, ToolStatus.failed, launcher, reason="jar_not_found",
                                message=f"ARVA runs Pilon's jar with java and its own heap size, and {launcher} does "
                                "not name the jar it runs; set ARVA_TOOL_PILON to the path of pilon.jar")
        java = java_executable()
        if java is None:
            return DetectedTool(self.info, ToolStatus.failed, jar, reason="java_missing",
                                message="Java was not found; Pilon needs a Java runtime (default-jre-headless)")
        proc = _run_quiet([java, "-jar", jar, "--version"])
        m = _VERSION.search(proc.stdout + proc.stderr) if proc else None
        note, reason = "", None
        if m:
            version = m.group(1)
        elif (package := debian_package_version(jar)) is not None:
            version = upstream_version(package[1])
            note = (f"This Pilon prints no version number ('Pilon version [COMMIT] [DATE]', Debian's build); the "
                    f"version comes from its Debian package {package[0]} {package[1]}")
            reason = "version_from_package"
        else:
            return DetectedTool(self.info, ToolStatus.failed, jar, message="Version could not be determined")
        if parse_version(version) < parse_version(self.info.min_version):
            return DetectedTool(self.info, ToolStatus.incompatible, jar, version,
                                message=f"Version {version} is older than the minimum supported {self.info.min_version}")
        validated = version in self.info.tested_versions
        messages = [note] + ([] if validated else [f"Version {version} has not been validated with ARVA (validated: "
                                                   f"{', '.join(self.info.tested_versions)})"])
        return DetectedTool(self.info, ToolStatus.available, jar, version, validated,
                            ". ".join(m for m in messages if m), reason)

    @staticmethod
    def help_options(java: str, jar: str) -> frozenset[str]:
        proc = _run_quiet([java, "-jar", jar, "--help"])
        if proc is None or proc.returncode != 0:
            raise RuntimeError("java -jar pilon.jar --help failed")
        return help_options(proc.stdout + proc.stderr)

    @staticmethod
    def argv(java: str, jar: str, params: PilonParams, genome: Path, out_dir: Path, prefix: str,
             supported: frozenset[str], *, frags: Path | None = None, unpaired: Path | None = None) -> list[str]:
        params.validate()
        if frags is None and unpaired is None:
            raise ValueError("Pilon needs paired-end (--frags) or unpaired (--unpaired) alignments")
        if not _FASTA_NAME.fullmatch(genome.name) or not _SAFE_PREFIX.fullmatch(prefix):
            raise ValueError("unsafe genome file name or output prefix for Pilon")
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this Pilon version does not offer {', '.join(missing)} (not in its --help)")
        a = [java, f"-Xmx{params.heap_gb}g", "-jar", jar, "--genome", str(genome)]
        if frags is not None:
            a += ["--frags", str(frags)]
        if unpaired is not None:
            a += ["--unpaired", str(unpaired)]
        a += ["--output", prefix, "--outdir", str(out_dir), "--changes", "--fix", params.fix_list(),
              "--mindepth", _num(params.mindepth), "--minmq", str(params.minmq), "--minqual", str(params.minqual)]
        for flag, value in FIXED_OPTIONS:
            a += [flag, value]
        return a

    @staticmethod
    def parse_changes(text: str) -> dict[str, Any]:
        """Pilon's .changes file → counts by kind (SNP, insertion, deletion, substitution of several bases, other
        replacement), in events and bases, overall and per contig. Insertions and deletions are relative to the
        input: an insertion adds bases to the new sequence."""
        kinds = ("snp", "insertion", "deletion", "substitution", "replacement")
        totals = {k: {"events": 0, "bases": 0} for k in kinds}
        by_contig: dict[str, dict[str, int]] = {}
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            f = line.split()
            if len(f) != 4 or not _LOCATION.fullmatch(f[0]) or not _LOCATION.fullmatch(f[1]):
                raise ValueError(f"line {n}: not a Pilon change ('<old location> <new location> <old> <new>')")
            old, new = ("" if s == "." else s for s in f[2:])
            if not old and not new:
                raise ValueError(f"line {n}: a change without bases")
            if not old:
                kind, bases = "insertion", len(new)
            elif not new:
                kind, bases = "deletion", len(old)
            elif len(old) == len(new) == 1:
                kind, bases = "snp", 1
            elif len(old) == len(new):
                kind, bases = "substitution", len(old)
            else:
                kind, bases = "replacement", max(len(old), len(new))
            totals[kind]["events"] += 1
            totals[kind]["bases"] += bases
            contig = _LOCATION.fullmatch(f[0]).group(1)
            row = by_contig.setdefault(contig, dict.fromkeys(kinds, 0))
            row[kind] += 1
        return {"totals": totals, "changes": sum(t["events"] for t in totals.values()), "by_contig": by_contig}

    @staticmethod
    def parse_log(text: str) -> dict[str, Any]:
        """Per processed region of Pilon's log: confirmed bases and the corrections Pilon reports; and its mean
        coverage lines."""
        regions: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if m := _PROCESSING.match(line):
                regions.append({"contig": m.group(1), "start": int(m.group(2)), "end": int(m.group(3))})
            elif regions and (m := _CONFIRMED.match(line)):
                regions[-1].update(confirmed_bases=int(m.group(1)), bases=int(m.group(2)))
            elif regions and (m := _CORRECTED.match(line)):
                regions[-1].update(snps=int(m.group(1)), ambiguous=int(m.group(2)), insertions=int(m.group(3)),
                                   inserted_bases=int(m.group(4)), deletions=int(m.group(5)),
                                   deleted_bases=int(m.group(6)))
        keys = ("confirmed_bases", "bases", "snps", "insertions", "inserted_bases", "deletions", "deleted_bases")
        totals = {k: sum(r.get(k, 0) for r in regions) for k in keys}
        return {"regions": regions, "totals": totals,
                "mean_coverage": {k: int(v) for k, v in _MEAN.findall(text)},
                "finished": bool(regions) and all("confirmed_bases" in r for r in regions)}

    @staticmethod
    def failure_reason(log_text: str, returncode: int | None, heap_gb: int | None = None) -> str | None:
        if "java.lang.OutOfMemoryError" in log_text:
            limit = f" (-Xmx{heap_gb}g)" if heap_gb else ""
            return f"Pilon ran out of Java heap memory{limit}. Give it a larger heap if the computer has the memory"
        if returncode in (-9, 137):
            return "Pilon was stopped by the operating system, most likely because the computer ran out of memory"
        for line in log_text.splitlines():
            if line.startswith("Exception in thread") or line.startswith("Error"):
                return f"Pilon failed: {line.strip()}"
        return None
