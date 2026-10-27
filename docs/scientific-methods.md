# Scientific methods

This document describes exactly how ARVA computes every value it reports. Implementation:
`scientific-core/arva_core/seqstats.py` (tool name `arva-core.seqstats`, version recorded per run).

## Input handling

- **Format detection** is content-based: after transparent gzip decompression (detected by magic
  bytes `1f 8b`), the first non-whitespace byte must be `@` (FASTQ) or `>` (FASTA).
- **FASTQ** must be strict four-line records: header beginning with `@`; sequence; separator
  beginning with `+`; quality string of equal length. Multi-line FASTQ is rejected.
- **FASTA** may wrap sequences over multiple lines; blank lines and `;` comment lines are ignored.
- Sequence characters must be IUPAC nucleotide codes (`ACGTUNRYKMSWBDHV`, either case).
  Gaps (`-`) and protein letters are rejected.
- Qualities must be in the Phred+33 range (`!`–`~`). Files whose observed range suggests legacy
  Phred+64 encoding (min ≥ Q31 and 45 < max ≤ Q72 under Phred+33) produce a warning; they are not
  silently converted.
- The first structural error stops processing and is reported with its line number. A corrupt
  or truncated gzip stream is reported as such. **No partial results are stored.**

At import, only the first 1,000 records are checked (fast feedback); the whole file is validated
during the statistics run, and the file's validation status is updated with the outcome.

## Length statistics

All read lengths are tallied exactly (as a length → count map).

- Mean = total bases / reads. Median uses the standard definition (mean of the two middle values
  for an even count).
- **Nx** (N50, N90): lengths sorted in descending order; Nx is the length of the read at which the
  cumulative sum first reaches *x* × total bases. **Lx** is the number of reads needed.
- **Length histogram**: equal-width integer bins between min and max (default 50 bins). When
  max/min ≥ 10, a second histogram with logarithmically spaced bins is produced. Each bin reports
  both reads and bases.
- **Yield by minimum length**: for each distinct length *L*, the reads and bases with length ≥ *L*
  (down-sampled to ≤ 200 points for plotting), plus fixed thresholds (100 bp … 100 kb).

## Composition

- **GC %** = (G + C) / (A + C + G + T + U) over unambiguous bases, for the file and for each read
  (per-read values are rounded to the nearest integer percent for the histogram).
- **Ambiguous bases** = all other IUPAC symbols (including N), reported as count and % of all bases.

## Quality (FASTQ only)

Phred: Q = −10 log₁₀ P(error) (Ewing & Green, 1998).

- **Per-read mean quality**: per-base error probabilities are averaged, then converted back:
  `Q_read = −10·log10(mean(10^(−Q_i/10)))`. This matches NanoPlot/NanoStat (De Coster et al.,
  2018). Arithmetic means of Phred values are *not* used because they overestimate accuracy.
- **Mean / median read quality**: mean of `Q_read` over reads with length > 0; median at 0.1 Q
  resolution.
- **Mean base quality**: the same error-probability average taken over all bases.
- **Q20 / Q30 bases**: percentage of all bases with Q ≥ 20 / Q ≥ 30.
- **Reads above Q** (7, 10, 12, 15, 20, 30): reads whose `Q_read` ≥ threshold.
- **Quality by position**: arithmetic mean Phred per position for positions 1–1,000 across the
  reads covering each position (as in FastQC); the number of covering reads is reported.

## Sampling

Summary statistics always use every record. Only the quality-vs-length scatter plot uses a sample:
uniform reservoir sampling of 2,000 reads with a fixed, recorded seed (default `20240501`), so the
figure is reproducible.

## Depth estimate

Reported only when the user supplies an expected genome size *G*: depth ≈ total bases / *G*. This
assumes all bases derive from the target genome and is an upper bound on effective chromosomal depth.

## What ARVA does not do in Phase 1

- No pass/fail thresholds: suitability depends on technology, chemistry and purpose.
- No read filtering or trimming (planned with fastp / Filtlong in Phase 2; ARVA never filters silently).
- No duplicate-read detection, adapter detection or k-mer analysis.
- No taxonomic or biological interpretation.

## Validation

`scientific-core/tests/test_seqstats.py` checks every metric against values computed by hand
(lengths, Nx/Lx, GC, Phred error averaging, Q20/Q30, per-position means, histograms conserving
counts, reproducible sampling) and checks that malformed inputs fail with the correct line numbers.

## References

- Ewing B, Green P. Base-calling of automated sequencer traces using phred. II. Error probabilities. *Genome Res* 1998;8:186–194. doi:10.1101/gr.8.3.186
- Cock PJA et al. The Sanger FASTQ file format for sequences with quality scores, and the Solexa/Illumina FASTQ variants. *Nucleic Acids Res* 2010;38:1767–1771. doi:10.1093/nar/gkp1137
- De Coster W et al. NanoPack: visualizing and processing long-read sequencing data. *Bioinformatics* 2018;34:2666–2669. doi:10.1093/bioinformatics/bty149
- Gurevich A et al. QUAST: quality assessment tool for genome assemblies. *Bioinformatics* 2013;29:1072–1075. doi:10.1093/bioinformatics/btt086
- Lander ES, Waterman MS. Genomic mapping by fingerprinting random clones: a mathematical analysis. *Genomics* 1988;2:231–239. doi:10.1016/0888-7543(88)90007-9
- Cornish-Bowden A. Nomenclature for incompletely specified bases in nucleic acid sequences. *Nucleic Acids Res* 1985;13:3021–3030. doi:10.1093/nar/13.9.3021
