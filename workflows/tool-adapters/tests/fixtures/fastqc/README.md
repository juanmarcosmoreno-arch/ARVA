# FastQC fixtures

Written by FastQC 0.12.1 (Ubuntu package 0.12.1+dfsg-3) with ARVA's command
(`fastqc --outdir <dir> --noextract --quiet --threads 1 --dir <tmp> <file>`) and copied unchanged
from `<stem>_fastqc.zip` (`<stem>_fastqc/fastqc_data.txt` and `summary.txt`).

| Fixture | Input |
|---|---|
| `SYNTHETIC_illumina_R1_001_*` | `examples/synthetic/SYNTHETIC_illumina_R1_001.fastq.gz` (sha256 3fb45355…) |
| `SYNTHETIC_illumina_R2_001_*` | `examples/synthetic/SYNTHETIC_illumina_R2_001.fastq.gz` (sha256 43707cd0…) |
| `SYNTHETIC_nanopore_reads_*` | `examples/synthetic/SYNTHETIC_nanopore_reads.fastq.gz` (sha256 292a2ae3…) |
| `DERIVED_R1_dups_dimers_fastqc_data.txt` | A test file, not a dataset: the 2,000 R1 reads, plus 100 copies of the first read and 30 reads of FastQC's "TruSeq Adapter, Index 1" contaminant padded with A to 150 bp |

The synthetic reads have no duplicates and no overrepresented sequences, so the derived file is what
exercises non-empty duplication bins and an overrepresented table with a "Possible Source" hit.
