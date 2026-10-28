"""Read mapping for polishing: minimap2 (long reads), BWA-MEM (short reads) and samtools (sorting, statistics).

Verified against minimap2 2.26 (Ubuntu 2.26+dfsg-1build1; Debian bookworm ships 2.24), bwa 0.7.17-r1188 (Ubuntu
0.7.17-7, as bookworm) and samtools 1.19.2 (Ubuntu 1.19.2-1build2; bookworm ships 1.16.1): their usage texts
(fixtures/polishing) and real runs on the synthetic genome.

* minimap2: -x map-ont / map-pb / map-hifi are the presets for Nanopore, PacBio CLR and PacBio HiFi reads against a
  reference (map-hifi since 2.19). Threads default to 3, so ARVA passes -t. Without -a it writes PAF (the overlaps
  Racon takes); with -a it writes SAM with NM tags.
* bwa mem: -K fixes how many input bases are processed per batch "regardless of nThreads (for reproducibility)":
  without it the insert-size statistics, and so the pairing, depend on the thread count. ARVA passes -K 100000000.
  bwa mem writes SAM to stdout; ARVA gzips it and samtools reads the gzip-compressed SAM directly.
* samtools stats: "raw total sequences" excludes secondary and supplementary alignments. Its "mismatches" are
  summed from the NM tags, i.e. the edit distance (mismatched, inserted and deleted bases), and "error rate" is that
  sum divided by "bases mapped (cigar)". The ID lines count insertions and deletions by length. samtools coverage
  reports each contig's covered bases and mean depth over reads that are mapped, primary, not QC-failed and not
  duplicates (its default --ff), with no mapping-quality threshold (-q 0).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo

LONG_READ_PRESETS = ("map-ont", "map-pb", "map-hifi")
BWA_BATCH_BASES = 100_000_000
_SN = re.compile(r"^SN\t([^:]+):\t([^\t]+)")
_ID = re.compile(r"^ID\t(\d+)\t(\d+)\t(\d+)")
SN_FIELDS = {
    "raw total sequences": "reads",
    "reads mapped": "reads_mapped",
    "reads unmapped": "reads_unmapped",
    "reads properly paired": "reads_properly_paired",
    "reads paired": "reads_paired",
    "supplementary alignments": "supplementary_alignments",
    "bases mapped (cigar)": "bases_mapped_cigar",
    "mismatches": "nm_sum",
    "error rate": "error_rate",
    "average length": "average_length",
    "average quality": "average_quality",
    "insert size average": "insert_size_average",
}


class Minimap2Adapter(ToolAdapter):
    info = ToolInfo(
        id="minimap2",
        name="minimap2",
        description="Aligns long reads to an assembly; ARVA uses it for Racon's overlaps and to measure how well the "
        "reads agree with an assembly before and after polishing.",
        homepage="https://github.com/lh3/minimap2",
        license="MIT",
        citation="Li H. Minimap2: pairwise alignment for nucleotide sequences. Bioinformatics 2018;34(18):3094-3100.",
        citation_url="https://doi.org/10.1093/bioinformatics/bty191",
        executable="minimap2",
        categories=("alignment", "long reads"),
        input_formats=("fasta", "fastq", "fastq.gz"),
        output_formats=("paf", "sam"),
        min_version="2.19",
        tested_versions=("2.26-r1175",),
        install={"apt": "minimap2", "conda": "bioconda::minimap2"},
    )
    # `minimap2 --version` prints "2.26-r1175".
    version_pattern = re.compile(r"^(\d+\.\d+(?:-r\d+)?)", re.M)

    @staticmethod
    def argv(executable: str, preset: str, threads: int, target: Path, reads: Path, out: Path | None,
             sam: bool = False) -> list[str]:
        """PAF (or SAM with `sam`) to `out`, or to stdout when `out` is None."""
        if preset not in LONG_READ_PRESETS:
            raise ValueError(f"preset must be one of {', '.join(LONG_READ_PRESETS)}")
        return [executable, *(["-a"] if sam else []), "-x", preset, "-t", str(threads),
                *(["-o", str(out)] if out is not None else []), str(target), str(reads)]


class BwaAdapter(ToolAdapter):
    info = ToolInfo(
        id="bwa",
        name="BWA",
        description="Aligns short reads to an assembly (BWA-MEM); ARVA uses it to give Pilon its alignments and to "
        "measure how well the reads agree with an assembly before and after polishing.",
        homepage="https://github.com/lh3/bwa",
        license="MIT and GPL-2.0-or-later (bwt_gen), per Debian's copyright file",
        citation="Li H. Aligning sequence reads, clone sequences and assembly contigs with BWA-MEM. "
        "arXiv:1303.3997 [q-bio.GN], 2013.",
        citation_url="https://arxiv.org/abs/1303.3997",
        executable="bwa",
        categories=("alignment", "short reads"),
        input_formats=("fasta", "fastq", "fastq.gz"),
        output_formats=("sam",),
        min_version="0.7.17",
        tested_versions=("0.7.17-r1188",),
        install={"apt": "bwa", "conda": "bioconda::bwa"},
    )
    # `bwa` alone prints its usage with "Version: 0.7.17-r1188" and exits with status 1.
    version_args = ()
    version_pattern = re.compile(r"Version: (\d+\.\d+\.\d+(?:-r\d+)?)")

    @staticmethod
    def index_argv(executable: str, fasta: Path, prefix: Path) -> list[str]:
        return [executable, "index", "-p", str(prefix), str(fasta)]

    @staticmethod
    def mem_argv(executable: str, prefix: Path, reads: list[Path], threads: int) -> list[str]:
        if len(reads) not in (1, 2):
            raise ValueError("bwa mem takes one file of unpaired reads or the two files of a pair")
        return [executable, "mem", "-t", str(threads), "-K", str(BWA_BATCH_BASES), str(prefix), *map(str, reads)]


class SamtoolsAdapter(ToolAdapter):
    info = ToolInfo(
        id="samtools",
        name="samtools",
        description="Sorts and indexes read alignments and summarises them (mapped reads, edit distance, depth); "
        "Flye also calls it, and ARVA uses it for polishing.",
        homepage="https://www.htslib.org",
        license="MIT",
        citation="Danecek P, Bonfield JK, Liddle J, et al. Twelve years of SAMtools and BCFtools. GigaScience "
        "2021;10(2):giab008.",
        citation_url="https://doi.org/10.1093/gigascience/giab008",
        executable="samtools",
        categories=("alignment",),
        input_formats=("sam", "bam"),
        output_formats=("bam", "text"),
        min_version="1.10",
        tested_versions=("1.19.2",),
        install={"apt": "samtools", "conda": "bioconda::samtools"},
    )
    # `samtools --version` starts with "samtools 1.19.2".
    version_pattern = re.compile(r"^samtools (\d+\.\d+(?:\.\d+)?)", re.M)

    @staticmethod
    def sort_argv(executable: str, sam: Path, bam: Path, threads: int, temp_prefix: Path) -> list[str]:
        # -@ is the number of threads besides the main one.
        return [executable, "sort", "-@", str(max(threads - 1, 0)), "-T", str(temp_prefix), "-o", str(bam), str(sam)]

    @staticmethod
    def index_argv(executable: str, bam: Path) -> list[str]:
        return [executable, "index", str(bam)]

    @staticmethod
    def stats_argv(executable: str, bam: Path) -> list[str]:
        return [executable, "stats", str(bam)]

    @staticmethod
    def coverage_argv(executable: str, bam: Path) -> list[str]:
        return [executable, "coverage", str(bam)]

    @staticmethod
    def parse_stats(text: str) -> dict[str, Any]:
        """The summary numbers (SN lines) and indel counts (ID lines) of `samtools stats`, with derived rates.
        Raises ValueError when the summary lacks the numbers ARVA reports."""
        raw: dict[str, str] = {}
        insertions = deletions = 0
        for line in text.splitlines():
            if m := _SN.match(line):
                raw[m.group(1)] = m.group(2).strip()
            elif m := _ID.match(line):
                insertions += int(m.group(2))
                deletions += int(m.group(3))
        missing = [k for k in ("raw total sequences", "reads mapped", "bases mapped (cigar)", "mismatches") if k not in raw]
        if missing:
            raise ValueError("samtools stats did not report " + ", ".join(missing))
        out: dict[str, Any] = {}
        for key, name in SN_FIELDS.items():
            if key in raw:
                value = float(raw[key])
                out[name] = int(value) if value.is_integer() and key != "error rate" else value
        aligned = out["bases_mapped_cigar"]
        out["insertion_events"], out["deletion_events"] = insertions, deletions
        out["mapped_percent"] = 100 * out["reads_mapped"] / out["reads"] if out["reads"] else None
        out["properly_paired_percent"] = (100 * out["reads_properly_paired"] / out["reads_paired"]
                                          if out.get("reads_paired") else None)
        out["edit_distance_per_100_bases"] = 100 * out["nm_sum"] / aligned if aligned else None
        out["indel_events_per_100kb"] = 1e5 * (insertions + deletions) / aligned if aligned else None
        return out

    @staticmethod
    def parse_coverage(text: str) -> list[dict[str, Any]]:
        """Rows of `samtools coverage`: contig, length, reads, covered bases, % covered and mean depth."""
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines or not lines[0].startswith("#rname"):
            raise ValueError("samtools coverage output has no header line")
        rows = []
        for line in lines[1:]:
            f = line.split("\t")
            if len(f) < 9:
                raise ValueError(f"samtools coverage row has {len(f)} columns, expected 9")
            rows.append({"contig": f[0], "length": int(f[2]), "reads": int(f[3]), "covered_bases": int(f[4]),
                         "covered_percent": float(f[5]), "mean_depth": float(f[6]), "mean_base_quality": float(f[7]),
                         "mean_mapq": float(f[8])})
        return rows
