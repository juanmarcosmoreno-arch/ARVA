"""MUMmer dnadiff — base-level differences between two assemblies (here: before and after polishing).

Verified against dnadiff 1.3 with NUCmer 3.1 (Ubuntu package mummer 3.23+dfsg-8, the same version as Debian
bookworm's): `dnadiff -h` (fixtures/polishing), the dnadiff Perl script and real runs on the synthetic genome with
known edits (fixtures/polishing/known_edits.*: 7 substitutions, 4 insertions of 5 bases, 5 deletions of 7 bases):

* `dnadiff -p <prefix> <reference> <query>` runs `nucmer --maxmatch`, `delta-filter -1` (one-to-one) and `-m`,
  `show-snps -rlTHC` on the one-to-one alignments, `show-coords -rclTH` and `show-diff`. It builds each command
  as a shell string from its arguments, so ARVA passes only relative file names it chose itself.
* <prefix>.report: [Bases] aligned and unaligned bases of each side; [Alignments] 1-to-1 count, length and average
  identity; [Feature Estimates] breakpoints, relocations, inversions, inserted (unaligned) regions; [SNPs]
  TotalSNPs (substituted bases) and TotalIndels (inserted plus deleted bases, one per base) in the one-to-one
  alignments.
* <prefix>.snps: one row per differing base, reference base "." for a base only in the query (an insertion in the
  query) and query base "." for a base only in the reference (a deletion). An indel of several bases is one row
  per base: the rows of an insertion share the reference position, those of a deletion the query position. ARVA
  groups them into events.
* <prefix>.1coords: one row per one-to-one alignment (reference start/end, query start/end, lengths, identity,
  contig lengths, names), from which ARVA reads the reference bases left unaligned at each contig end.
* Differences outside the one-to-one alignments (unaligned ends, rearrangements) are not in the .snps file; they
  appear as unaligned bases and breakpoints in the report.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo
from arva_tools.runner import isolated_home, tool_environment

OUTPUT_SUFFIXES = ("report", "snps", "1coords")
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
_ROW = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s*$")
_VALUE = re.compile(r"^(-?\d+(?:\.\d+)?)(?:\(([\d.]+)%\))?$")
_BIN_DIR = re.compile(r'^my \$BIN_DIR\s*=\s*"([^"]+)";', re.M)
REPORT_KEYS = {
    ("Sequences", "TotalSeqs"): "sequences",
    ("Sequences", "AlignedSeqs"): "aligned_sequences",
    ("Sequences", "UnalignedSeqs"): "unaligned_sequences",
    ("Bases", "TotalBases"): "bases",
    ("Bases", "AlignedBases"): "aligned_bases",
    ("Bases", "UnalignedBases"): "unaligned_bases",
    ("Alignments", "1-to-1"): "one_to_one_alignments",
    ("Alignments", "1-to-1/TotalLength"): "one_to_one_length",
    ("Alignments", "1-to-1/AvgIdentity"): "one_to_one_identity",
    ("Feature Estimates", "Breakpoints"): "breakpoints",
    ("Feature Estimates", "Relocations"): "relocations",
    ("Feature Estimates", "Translocations"): "translocations",
    ("Feature Estimates", "Inversions"): "inversions",
    ("Feature Estimates", "Insertions"): "inserted_regions",
    ("Feature Estimates", "InsertionSum"): "inserted_region_bases",
    ("SNPs", "TotalSNPs"): "substituted_bases",
    ("SNPs", "TotalIndels"): "indel_bases",
}


def _value(text: str) -> int | float:
    m = _VALUE.match(text)
    if not m:
        raise ValueError(f"not a dnadiff value: {text!r}")
    return float(m.group(1)) if "." in m.group(1) else int(m.group(1))


def nucmer_version(dnadiff: str) -> str | None:
    """The version of the nucmer dnadiff calls (the BIN_DIR written in the dnadiff script), e.g. '3.1'."""
    try:
        text = Path(dnadiff).read_text(errors="replace")
    except OSError:
        return None
    m = _BIN_DIR.search(text)
    if not m:
        return None
    try:
        with isolated_home() as home:
            proc = subprocess.run([str(Path(m.group(1)) / "nucmer"), "--version"], capture_output=True, text=True,
                                  errors="replace", timeout=60, env=tool_environment(home), cwd=home,
                                  stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    v = re.search(r"version (\S+)", proc.stdout + proc.stderr)
    return v.group(1) if v else None


class DnadiffAdapter(ToolAdapter):
    info = ToolInfo(
        id="dnadiff",
        name="MUMmer dnadiff",
        description="Aligns two assemblies with NUCmer and lists their differences base by base; ARVA uses it as "
        "the direct evidence of what polishing changed.",
        homepage="https://mummer.sourceforge.net",
        license="Artistic-1.0",
        citation="Kurtz S, Phillippy A, Delcher AL, et al. Versatile and open software for comparing large genomes. "
        "Genome Biol 2004;5(2):R12.",
        citation_url="https://doi.org/10.1186/gb-2004-5-2-r12",
        executable="dnadiff",
        categories=("assembly comparison",),
        input_formats=("fasta",),
        output_formats=("report", "snps", "coords"),
        min_version="1.3",
        tested_versions=("1.3",),
        install={"apt": "mummer", "conda": "bioconda::mummer"},
    )
    # `dnadiff --version` prints "DNAdiff version 1.3".
    version_pattern = re.compile(r"DNAdiff version (\d+\.\d+)")

    @staticmethod
    def argv(executable: str, prefix: str, reference: str, query: str) -> list[str]:
        """dnadiff run in the folder holding both files; every name must be a plain, shell-safe file name."""
        for name in (prefix, reference, query):
            if not _SAFE.fullmatch(name):
                raise ValueError(f"dnadiff builds shell commands from its arguments; unsafe name: {name!r}")
        return [executable, "-p", prefix, reference, query]

    @staticmethod
    def parse_report(text: str) -> dict[str, dict[str, int | float]]:
        """Selected [Sequences], [Bases], 1-to-1 [Alignments], [Feature Estimates] and [SNPs] totals of the
        .report file, for the reference and the query side."""
        out: dict[str, dict[str, int | float]] = {"reference": {}, "query": {}}
        section = sub = None
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                section, sub = s[1:-1], None
                continue
            m = _ROW.match(s)
            if not m or section is None:
                continue
            key, ref, qry = m.groups()
            if section == "Alignments" and key in ("1-to-1", "M-to-M"):
                sub = key
            elif sub:
                key = f"{sub}/{key}"
            name = REPORT_KEYS.get((section, key))
            # TotalSNPs/TotalIndels appear once; the per-type rows after them are not read.
            if name is None or name in out["reference"]:
                continue
            out["reference"][name], out["query"][name] = _value(ref), _value(qry)
        missing = [n for n in ("bases", "aligned_bases", "substituted_bases", "indel_bases") if n not in out["reference"]]
        if missing:
            raise ValueError("dnadiff report lacks " + ", ".join(missing))
        return out

    @staticmethod
    def parse_snps(text: str) -> dict[str, Any]:
        """The .snps rows (show-snps -rlTHC) as events: substitutions (one per base), insertions and deletions
        (consecutive bases of one indel counted once, with their bases), overall and by reference contig."""
        totals = {"substitutions": 0, "insertions": 0, "inserted_bases": 0, "deletions": 0, "deleted_bases": 0}
        by_contig: dict[str, dict[str, int]] = {}
        last: tuple | None = None
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            f = line.split("\t")
            if len(f) < 12:
                raise ValueError(f"line {n}: a .snps row has 12 tab-separated columns (show-snps -rlTHC)")
            p1, ref, qry, p2, tag_r, tag_q = int(f[0]), f[1], f[2], int(f[3]), f[10], f[11]
            row = by_contig.setdefault(tag_r, dict.fromkeys(totals, 0))
            if ref == "." and qry == ".":
                raise ValueError(f"line {n}: a difference without bases")
            if ref == ".":
                kind, key = "insertion", (tag_r, tag_q, "ins", p1)
                new_event = not (last and last[:4] == key and abs(p2 - last[5]) == 1)
                current = (*key, p1, p2)
                if new_event:
                    totals["insertions"] += 1
                    row["insertions"] += 1
                totals["inserted_bases"] += 1
                row["inserted_bases"] += 1
            elif qry == ".":
                kind, key = "deletion", (tag_r, tag_q, "del", p2)
                new_event = not (last and last[:4] == key and p1 - last[4] == 1)
                current = (*key, p1, p2)
                if new_event:
                    totals["deletions"] += 1
                    row["deletions"] += 1
                totals["deleted_bases"] += 1
                row["deleted_bases"] += 1
            else:
                kind, current = "substitution", None
                totals["substitutions"] += 1
                row["substitutions"] += 1
            last = current if kind != "substitution" else None
        return {**totals, "by_contig": by_contig}

    @staticmethod
    def parse_coords(text: str) -> list[dict[str, Any]]:
        """Per reference contig with a one-to-one alignment (.1coords, show-coords -rclTH): its length, the span its
        alignments cover and the bases left unaligned before the first and after the last alignment."""
        spans: dict[str, dict[str, Any]] = {}
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            f = line.split("\t")
            if len(f) < 13:
                raise ValueError(f"line {n}: a .1coords row has 13 tab-separated columns (show-coords -rclTH)")
            s1, e1, length, tag_r, tag_q = int(f[0]), int(f[1]), int(f[7]), f[11], f[12]
            span = spans.setdefault(tag_r, {"contig": tag_r, "length": length, "start": s1, "end": e1,
                                            "aligned_bases": 0, "query_contigs": []})
            span["start"], span["end"] = min(span["start"], s1, e1), max(span["end"], s1, e1)
            span["aligned_bases"] += abs(e1 - s1) + 1
            if tag_q not in span["query_contigs"]:
                span["query_contigs"].append(tag_q)
        for span in spans.values():
            span["unaligned_start"] = span["start"] - 1
            span["unaligned_end"] = span["length"] - span["end"]
        return list(spans.values())
