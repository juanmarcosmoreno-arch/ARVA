"""BLAST+ — local similarity searches: makeblastdb, blastn, tblastn and blastp.

Verified against BLAST+ 2.12.0 (Ubuntu ncbi-blast+ 2.12.0+ds-4build2): the `-help` texts (fixtures/region) and real
runs on NCBI genomes (fixtures/region/README.md):

* `makeblastdb -in <fasta> -dbtype nucl|prot -out <name>` writes the database files next to <name>.
* blastn's -task is one of blastn, blastn-short, dc-megablast, megablast (default) and rmblastn; tblastn's tblastn
  (default) or tblastn-fast; blastp's blastp (default), blastp-fast or blastp-short.
* -evalue defaults to 10. -max_target_seqs defaults to 500. -max_hsps has no default: every HSP of a subject is kept,
  which ARVA needs to see second copies and matches split in pieces, so it is never set.
* Low-complexity filters: blastn -dust (default '20 64 1'), tblastn -seg (default '12 2.2 2.5'), blastp -seg
  (default 'no'); 'yes' or 'no' are accepted. ARVA passes the choice explicitly.
* tblastn translates the subject with -db_gencode (default 1, the standard code); ARVA passes 11, the bacterial code.
  tblastn and blastp take -comp_based_stats (default 2); ARVA passes it explicitly.
* `-outfmt "6 <fields>"` writes one tab-separated row per HSP with the named fields. Coordinates are 1-based and
  inclusive; sstart > send when the subject's minus strand aligned (blastn) or a negative frame did (tblastn).
"""
from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help

FIELDS = ("qseqid", "sseqid", "pident", "length", "mismatch", "gapopen", "qstart", "qend", "sstart", "send", "evalue",
          "bitscore", "qlen", "slen", "nident")
OUTFMT = "6 " + " ".join(FIELDS)
PROGRAMS = {"blastn": ("blastn", "blastn-short", "dc-megablast", "megablast"), "tblastn": ("tblastn", "tblastn-fast"),
            "blastp": ("blastp", "blastp-fast")}
FILTER_FLAG = {"blastn": "-dust", "tblastn": "-seg", "blastp": "-seg"}
SEARCH_FLAGS = ("-query", "-db", "-subject", "-out", "-outfmt", "-task", "-evalue", "-max_target_seqs", "-num_threads")
PROGRAM_FLAGS = {"blastn": ("-dust", "-strand"), "tblastn": ("-seg", "-db_gencode", "-comp_based_stats"),
                 "blastp": ("-seg", "-comp_based_stats")}
MAKEBLASTDB_FLAGS = ("-in", "-dbtype", "-out")
BACTERIAL_CODE = 11


@dataclass
class BlastParams:
    program: str = "blastn"
    task: str = "blastn"
    evalue: float = 1e-10
    max_target_seqs: int = 500
    low_complexity_filter: bool = True
    threads: int = 1

    def validate(self) -> None:
        errors = []
        if self.program not in PROGRAMS:
            errors.append(f"program must be one of {', '.join(PROGRAMS)}")
        elif self.task not in PROGRAMS[self.program]:
            errors.append(f"{self.program} task must be one of {', '.join(PROGRAMS[self.program])}")
        if not 0 < self.evalue <= 10:
            errors.append("evalue must be above 0 and at most 10")
        if not 1 <= self.max_target_seqs <= 100_000:
            errors.append("max_target_seqs must be between 1 and 100000")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sibling(blastn: str, program: str) -> str | None:
    """Another BLAST+ program from the same installation as blastn."""
    p = Path(blastn).with_name(program)
    return str(p) if p.is_file() else shutil.which(program)


def missing_flags(program: str, help_text: str) -> list[str]:
    opts = help_options(help_text)
    wanted = MAKEBLASTDB_FLAGS if program == "makeblastdb" else (*SEARCH_FLAGS, *PROGRAM_FLAGS[program])
    return [f for f in wanted if f not in opts]


def parse_tabular(text: str) -> list[dict[str, Any]]:
    """`-outfmt "6 <FIELDS>"` rows as HSPs: positions as reported plus `sstrand` (+/-) and s_lo <= s_hi."""
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        f = line.split("\t")
        if len(f) != len(FIELDS):
            raise ValueError(f"BLAST line {n} has {len(f)} columns instead of {len(FIELDS)}")
        try:
            r: dict[str, Any] = {"qseqid": f[0], "sseqid": f[1], "pident": float(f[2]), "evalue": float(f[10]),
                                 "bitscore": float(f[11])}
            for i, name in enumerate(FIELDS):
                if name in ("length", "mismatch", "gapopen", "qstart", "qend", "sstart", "send", "qlen", "slen",
                            "nident"):
                    r[name] = int(f[i])
        except ValueError:
            raise ValueError(f"BLAST line {n} has a value that is not a number") from None
        if not (0 <= r["pident"] <= 100 and 1 <= r["qstart"] <= r["qend"] <= r["qlen"]
                and max(r["sstart"], r["send"]) <= r["slen"] and min(r["sstart"], r["send"]) >= 1):
            raise ValueError(f"BLAST line {n} has values out of range")
        r["sstrand"] = "+" if r["sstart"] <= r["send"] else "-"
        r["s_lo"], r["s_hi"] = min(r["sstart"], r["send"]), max(r["sstart"], r["send"])
        rows.append(r)
    return rows


class BlastAdapter(ToolAdapter):
    info = ToolInfo(
        id="blast",
        name="BLAST+",
        description="Local similarity search (blastn, tblastn, blastp) against databases made with makeblastdb; ARVA "
        "uses it to find a gene in genomes and the homologous region around it, and to link genes and regions.",
        homepage="https://blast.ncbi.nlm.nih.gov/doc/blast-help/downloadblastdata.html",
        license="Public Domain",
        citation="Camacho C, Coulouris G, Avagyan V, et al. BLAST+: architecture and applications. BMC Bioinformatics "
        "2009;10:421.",
        citation_url="https://doi.org/10.1186/1471-2105-10-421",
        executable="blastn",
        categories=("comparative genomics", "similarity search"),
        input_formats=("fasta",),
        output_formats=("tsv",),
        min_version="2.10.0",
        tested_versions=("2.12.0",),
        install={"apt": "ncbi-blast+", "conda": "bioconda::blast"},
    )
    version_args = ("-version",)
    # `blastn -version` prints "blastn: 2.12.0+".
    version_pattern = re.compile(r"blastn: (\d+\.\d+\.\d+)\+")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("-help",))

    @staticmethod
    def makeblastdb_argv(executable: str, fasta: str, dbtype: str, out: str) -> list[str]:
        if dbtype not in ("nucl", "prot"):
            raise ValueError("dbtype must be nucl or prot")
        return [executable, "-in", fasta, "-dbtype", dbtype, "-out", out]

    @staticmethod
    def search_argv(executable: str, params: BlastParams, query: str, out: str, db: str | None = None,
                    subject: str | None = None) -> list[str]:
        params.validate()
        if (db is None) == (subject is None):
            raise ValueError("search a database or a subject file, not both")
        target = ["-db", db] if db is not None else ["-subject", subject]
        argv = [executable, "-task", params.task, "-query", query, *target, "-out", out, "-outfmt", OUTFMT,
                "-evalue", f"{params.evalue:g}", "-max_target_seqs", str(params.max_target_seqs),
                FILTER_FLAG[params.program], "yes" if params.low_complexity_filter else "no"]
        if params.program == "blastn":
            argv += ["-strand", "both"]
        else:
            argv += ["-comp_based_stats", "2"]
        if params.program == "tblastn":
            argv += ["-db_gencode", str(BACTERIAL_CODE)]
        if subject is None:
            # BLAST+ ignores -num_threads when searching a subject file and says so on stderr.
            argv += ["-num_threads", str(params.threads)]
        return argv
