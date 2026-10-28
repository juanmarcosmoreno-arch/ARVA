# Polishing fixtures

Written on Ubuntu 24.04 by Racon 1.5.0 (package 1.5.0-3), Pilon 1.24 (1.24-3, run as `java -Xmx2g -jar
/usr/share/java/pilon.jar` with OpenJDK 21.0.12 and no JAVA_TOOL_OPTIONS), minimap2 2.26-r1175, BWA 0.7.17-r1188,
samtools 1.19.2 and MUMmer 3.23 (dnadiff 1.3, NUCmer 3.1). Inputs: `scripts/make_synthetic_genome.py` with
`--chromosome-length 100000 --plasmid-length 8000 --repeat-length 2000 --ont-depth 30 --illumina-depth 40` (default
seed), and a draft made from its reference.fasta with 16 known edits (the edits of `scripts/make_polishing_draft.py`
at slightly different positions): 7 substitutions, insertions of A, G, TT and C (5 bases), deletions of 1, 1, 3, 1
and 1 bases (7 bases), with the replicons renamed contig_1 and contig_2. All data are SYNTHETIC.

| Fixture | Run |
|---|---|
| `*_help_*.txt`, `*_usage_*.txt` | `racon --help`, `java -jar pilon.jar --help`, `minimap2 --help`, `bwa index`, `bwa mem`, `samtools sort/stats/coverage/index/depth` without arguments or with `--help`, `dnadiff -h` |
| `known_edits.{report,snps,1coords}` | `dnadiff -p known_edits reference.fasta round0.fasta` (reference → draft: the 16 known edits) |
| `racon_round1.{report,snps,1coords}`, `racon_round1.headers.txt` | `minimap2 -x map-ont -t 2 -o round1.paf round0.fasta reads`, `racon -m 3 -x -5 -g -4 -w 500 -q 10 -e 0.3 -t 2 -u reads round1.paf round0.fasta > round1.fasta`, then `dnadiff -p racon_round1 round0.fasta round1.fasta`; the header lines of round1.fasta. Racon trimmed 8 + 17 bp at the ends of contig_1 and 12 + 10 bp at the ends of contig_2 |
| `racon_empty_overlaps.stderr.log` | Racon with an empty PAF file (exit status 1); carriage returns replaced by line breaks |
| `pilon_round1.{changes,log}`, `pilon_round1.{report,snps,1coords}` | `bwa index`, `bwa mem -t 2 -K 100000000` of the Illumina-like pairs, `samtools sort` and `index`, then `pilon --genome round0.fasta --frags pe.bam --output pilon1 --outdir . --changes --fix snps,indels,gaps,local --mindepth 0.1 --minmq 0 --minqual 0 --flank 10 --defaultqual 10 --gapmargin 100000 --mingap 10 --K 47 --chunksize 10000000` (stdout and stderr in the .log); `dnadiff -p pilon_round1 round0.fasta pilon1.fasta` |
| `pilon_oom.log` | the same Pilon run with `-Xmx8m` (exit status 1) |
| `illumina_pe.samtools_stats.txt`, `illumina_pe.samtools_coverage.tsv` | the SN and ID lines of `samtools stats pe.bam`; `samtools coverage pe.bam` |
| `ont.samtools_stats.txt`, `ont.samtools_coverage.tsv` | the same for `minimap2 -a -x map-ont -t 2` of the Nanopore-like reads to round0.fasta, sorted |

The local folder was replaced with `/job` in the first line of the dnadiff reports and in the Pilon log; nothing else
was changed.
