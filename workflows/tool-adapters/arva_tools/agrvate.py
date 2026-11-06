"""AgrVATE — agr typing of Staphylococcus aureus assemblies (agr group I-IV from group-specific k-mers) and agr operon
variants (frameshifts and other disruptive changes in agrB, agrD, agrC, agrA).

Verified against AgrVATE 1.0.2 (Bioconda agrvate-1.0.2-hdfd78af_0, ARVA's lock docker/conda-locks/agrvate/; no
linux-aarch64 lock: snippy's dependencies cannot be solved there, see linux-aarch64.unavailable) from `agrvate -h`,
`agrvate -v`, its bash script bin/agrvate and real runs (tests/fixtures/agrvate):

* `agrvate -i <fasta> [-m] [-d <databases>]` writes <name>-results/ and <file>-error-report.tab into the working
  folder (<name> is the file name without its extension). Typing: blastn of the k-mers of
  agrvate_databases/gp1234_all_motifs.fna (100 % identity and query coverage); the number of matching k-mers is the
  match score; 0 is untypeable (then nhmmer looks for a possibly non-canonical agrD), 1-4 is "low confidence", and
  k-mers of several groups mean several agr types (the most frequent is reported).
* Operon extraction: by default an in-silico PCR with usearch11.0.667_i86linux32, a 32-bit binary that is not part of
  the package (AgrVATE asks the user to download it from drive5.com; without it the run ends after typing with
  frameshifts "u"). With -m (help: "Uses mummer instead of usearch (May not perform frameshift detection)") MUMmer's
  dnadiff aligns a group-I reference operon (references/mummer_ref_operon.fna, 3,482 bp) and samtools extracts the
  aligned regions. ARVA never downloads usearch and always runs with -m; the extracted fraction of the reference is
  reported, because a group II-IV operon aligns only in part to the group-I reference.
* Variants: snippy (--minqual 1 --mincov 2) calls variants of the extracted operon against the group's reference
  GenBank file; <name>-agr_operon_frameshifts.tab lists the CDS variants AgrVATE keeps (frameshifts and other effects
  it does not filter out), columns #filename position type effect gene.
* <name>-summary.tab: #filename agr_group (gp1-gp4, u) match_score canonical_agrD (1 canonical, 0 possible
  non-canonical agrD found by nhmmer, u unknown) multiple_agr (s single, m multiple, u unknown) frameshifts (a count,
  or u when not determined). The error report's columns are #input_name input_check databases_check outdir_check
  agr_typing operon_check snippy_check (pass/fail). Some failures exit with status 1 after writing the summary.
* Input checks: uncompressed FASTA whose sequences hold only ATCGNWSMKRY (any case).
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

INPUT = "contigs.fasta"
NAME = "contigs"
LOG = "agrvate.log"
MODE = "mummer"
SUMMARY_COLUMNS = ("#filename", "agr_group", "match_score", "canonical_agrD", "multiple_agr", "frameshifts")
REPORT_COLUMNS = ("#input_name", "input_check", "databases_check", "outdir_check", "agr_typing", "operon_check",
                  "snippy_check")
VARIANT_COLUMNS = ("#filename", "position", "type", "effect", "gene")
GROUPS = {"gp1": "I", "gp2": "II", "gp3": "III", "gp4": "IV"}
LOW_CONFIDENCE_MAX = 4
_OPTION = re.compile(r"^\s+(-\w) \| (--[\w-]+)")


@dataclass
class AgrParams:
    mode: str = MODE
    threads: int = 1

    def validate(self) -> None:
        if self.mode != MODE:
            raise ValueError("only the MUMmer mode (-m) runs here: the usearch mode needs a 32-bit usearch binary "
                             "that ARVA does not install")

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "typing_only": False}


def flags(_params: AgrParams | None = None) -> list[str]:
    return ["--input", "--mummer", "--databases"]


def env_for(executable: str) -> dict[str, str]:
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def databases_dir(executable: str) -> Path:
    return Path(os.path.realpath(executable)).parent / "agrvate_databases"


def database_files(executable: str) -> list[Path]:
    root = databases_dir(executable)
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("README"))


def database_checksum(files: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for p in files:
        digest.update(str(p.relative_to(root)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode()
                      + b"\n")
    return "sha256:" + digest.hexdigest()


def parse_help_options(text: str) -> frozenset[str]:
    found: set[str] = set()
    for line in text.splitlines():
        if m := _OPTION.match(line):
            found.update(m.groups())
    return frozenset(found)


def outputs(workdir: Path) -> dict[str, Path]:
    res = workdir / f"{NAME}-results"
    return {"summary": res / f"{NAME}-summary.tab", "kmers": res / f"{NAME}-agr_gp.tab",
            "operon": res / f"{NAME}-agr_operon.fna", "variants": res / f"{NAME}-agr_operon_frameshifts.tab",
            "coords": res / f"{NAME}-mummer" / "out.1coords", "snps": res / f"{NAME}-snippy" / "snps.tab",
            "error_report": workdir / f"{INPUT}-error-report.tab"}


def _rows(text: str, columns: tuple[str, ...], name: str, *, at_least: bool = False) -> list[list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{name} is empty")
    rows = list(csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE))
    if tuple(rows[0]) != columns:
        raise ValueError(f"{name} has other columns than AgrVATE 1.0.2 writes: {', '.join(rows[0])}")
    for n, cols in enumerate(rows[1:], 2):
        if len(cols) < len(columns) if at_least else len(cols) != len(columns):
            raise ValueError(f"row {n} of {name} has {len(cols)} fields instead of {len(columns)}")
    return rows[1:]


def parse_summary(text: str) -> dict[str, Any]:
    rows = _rows(text, SUMMARY_COLUMNS, "AgrVATE's summary")
    if len(rows) != 1:
        raise ValueError(f"AgrVATE's summary has {len(rows)} result rows instead of 1")
    _name, group, score, canonical, multiple, frameshifts = rows[0]
    if group != "u" and group not in GROUPS:
        raise ValueError(f"unknown agr group {group!r}")
    if canonical not in ("0", "1", "u") or multiple not in ("s", "m", "u"):
        raise ValueError(f"unexpected canonical_agrD {canonical!r} or multiple_agr {multiple!r}")
    if not score.isdigit() or not (frameshifts.isdigit() or frameshifts == "u"):
        raise ValueError(f"unexpected match_score {score!r} or frameshifts {frameshifts!r}")
    return {"agr_group": GROUPS.get(group), "agr_group_code": group, "match_score": int(score),
            "canonical_agrD": {"1": "canonical", "0": "possible_non_canonical", "u": "unknown"}[canonical],
            "multiple_agr": {"s": "single", "m": "multiple", "u": "unknown"}[multiple],
            "frameshifts": int(frameshifts) if frameshifts.isdigit() else None}


def parse_error_report(text: str) -> dict[str, str]:
    rows = _rows(text, REPORT_COLUMNS, "AgrVATE's error report")
    if not rows:
        raise ValueError("AgrVATE's error report has no result row")
    return dict(zip(REPORT_COLUMNS[1:], rows[-1][1:], strict=True))


def parse_variants(text: str) -> list[dict[str, Any]]:
    """AgrVATE 1.0.2 writes snippy's columns 1, 2, 3, 11 (EFFECT) and 13 (GENE), then turns every space into a tab
    (`sed 's/ /\t/g'` in bin/agrvate), so an effect such as "frameshift_variant c.67delA p.Lys23fs" spans several
    fields: the effect is everything between the type and the last field (the gene), joined again with spaces."""
    out = []
    for cols in _rows(text, VARIANT_COLUMNS, "AgrVATE's frameshift table", at_least=True):
        p, t, g = cols[1], cols[2], cols[-1]
        out.append({"position": int(p) if p.isdigit() else p, "type": t, "effect": " ".join(cols[3:-1]), "gene": g})
    return out


def parse_coords(text: str) -> dict[str, Any]:
    """dnadiff's out.1coords (reference start, end, query start, end, aligned lengths, identity, reference and query
    lengths, coverages, reference and query names): the fragments of the reference operon found and the share of its
    length they cover."""
    fragments, ref_length, covered = [], None, []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) != 13:
            continue
        s1, e1, s2, e2 = (int(c) for c in cols[:4])
        ref_length = int(cols[7])
        covered.append((min(s1, e1), max(s1, e1)))
        fragments.append({"ref_start": s1, "ref_end": e1, "contig": cols[12], "start": min(s2, e2),
                          "end": max(s2, e2), "identity": float(cols[6])})
    merged: list[list[int]] = []
    for a, b in sorted(covered):
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    bases = sum(b - a + 1 for a, b in merged)
    return {"fragments": fragments, "reference_length": ref_length, "covered_bases": bases,
            "covered_fraction": round(bases / ref_length, 4) if ref_length else None}


def interpret(summary: dict[str, Any]) -> dict[str, Any]:
    """ARVA's reading of AgrVATE's call: typed, low_confidence (match score 1-4, AgrVATE's own limit), multiple or
    untypeable."""
    if summary["agr_group"] is None:
        status = "untypeable"
    elif summary["multiple_agr"] == "multiple":
        status = "multiple"
    elif summary["match_score"] <= LOW_CONFIDENCE_MAX:
        status = "low_confidence"
    else:
        status = "typed"
    return {"status": status, "call": summary["agr_group"] if status in ("typed", "low_confidence") else None}


class AgrvateAdapter(ToolAdapter):
    info = ToolInfo(
        id="agrvate",
        name="AgrVATE",
        description="agr typing of Staphylococcus aureus assemblies (agr group I-IV) and variants of the agr operon, "
        "run with MUMmer for the operon extraction.",
        homepage="https://github.com/VishnuRaghuram94/AgrVATE",
        license="MIT",
        citation="Raghuram V. et al. Species-wide phylogenomics of the Staphylococcus aureus agr operon revealed "
        "convergent evolution of frameshift mutations. Microbiology Spectrum 2022;10(1), doi:10.1128/spectrum.01334-21.",
        citation_url="https://doi.org/10.1128/spectrum.01334-21",
        executable="agrvate",
        categories=("typing",),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="1.0.2",
        tested_versions=("1.0.2",),
        install={"conda_lock": "python3 scripts/conda_locks.py install agrvate ~/.arva-tools/conda/agrvate  # then "
                               "ARVA_TOOL_AGRVATE=~/.arva-tools/conda/agrvate/bin/agrvate"},
        conda_platforms=("linux-64",),
    )
    version_args = ("-v",)
    version_pattern = re.compile(r"agrvate v(\d+\.\d+\.\d+)")

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("-h",), env_for(executable))

    @staticmethod
    def help_options(executable: str) -> frozenset[str]:
        return parse_help_options(AgrvateAdapter.help_text(executable))

    @staticmethod
    def argv(executable: str, params: AgrParams, supported: frozenset[str]) -> list[str]:
        params.validate()
        if missing := [f for f in flags(params) if f not in supported]:
            raise ValueError(f"this AgrVATE version does not offer {', '.join(missing)} (not in its help)")
        return [executable, "--input", INPUT, "--mummer", "--databases", str(databases_dir(executable)) + "/"]

    @staticmethod
    def failure_reason(log: str) -> str | None:
        for pattern in (r"Seqence has non-standard nucleic acid characters", r"Input file not in FASTA format",
                        r"is not a valid databases directory", r"Error running mummer.*",
                        r"Agr group typing kmer search failed"):
            if m := re.search(pattern, log):
                return f"AgrVATE stopped: {m.group(0)}"
        return None
