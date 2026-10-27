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

## External tools (Phase 2)

All external tools are run through adapters (`workflows/tool-adapters/arva_tools`). For each run
ARVA records the resolved executable path, the version reported by the binary itself (package
metadata is not trusted: Ubuntu's `seqkit` package 2.3.1 reports `v2.3.0`), the exact argument
vector, input checksums, tool logs and outputs. Versions are marked *validated* only after ARVA's
test suite has run against them; other versions run with a recorded warning.

| Tool | Validated versions | Used for |
|---|---|---|
| SeqKit | 2.3.0 | Independent cross-check of ARVA statistics (`seqkit stats --all --tabular`) |
| FastQC | 0.11.9, 0.12.1 | Per-file QC report (unmodified) and module flags |
| fastp | 0.23.2, 0.23.4 | Short-read adapter trimming and filtering |
| Filtlong | 0.2.1 | Long-read filtering |

### Independent cross-check (SeqKit)

ARVA compares its own statistics with SeqKit's for the same file. Counts and lengths (reads, total
bases, minimum, maximum, N50) must match exactly; mean length is allowed 0.05 bp and percentages
(Q20, Q30, GC) 0.005 percentage points, which is SeqKit's output rounding and nothing more.
Quartiles are **not** compared: SeqKit 2.3.0 reports Q1 = Q3 = 75 for a file of uniform 150 bp
reads, which is incorrect. GC is compared only when the file has no ambiguous bases. Disagreements are
displayed, never hidden. On the synthetic example data all compared metrics agree.

### FastQC

FastQC is run unchanged (`--outdir --noextract --quiet --threads 1 --dir <tmp>`); its HTML and ZIP
outputs are stored, and `summary.txt`/`fastqc_data.txt` are parsed for module flags and basic
statistics. The flags are FastQC's heuristics for whole-genome shotgun libraries and are shown as such.

### Filtering policy

- Filtering is never automatic. The user chooses the tool and sees every threshold, including values
  equal to the tool's own defaults, plus a plain-language summary of what will be removed, and must
  confirm before running.
- Every threshold is passed explicitly on the command line, so the recorded command fully defines the
  run even if a future tool version changes its defaults.
- Originals are never modified. Kept reads are written to a new **derived** file (read-only, with its
  own SHA-256) linked to its parent file and to the producing job.
- When a filter finishes, ARVA statistics for the derived file (and for the original if missing) are
  created in the same database transaction and then executed, so the before/after comparison always
  uses identical methods on both sides.

### fastp (short reads)

Options verified against `fastp --help` of 0.23.4 and 0.23.2. Defaults shown to the user and passed
explicitly: adapter trimming on (`--detect_adapter_for_pe` added for pairs), `--qualified_quality_phred 15`,
`--unqualified_percent_limit 40`, `--n_base_limit 5`, `--average_qual 0` (off), `--length_required 15`;
sliding-window trimming (`--cut_front/--cut_tail`, window 4, Q20) and deduplication are off; poly-G
trimming is fastp's automatic behaviour unless forced (`--trim_poly_g`) or disabled
(`--disable_trim_poly_g`). For paired-end data, a pair is removed when either mate fails. ARVA shows
fastp's own counts of reads removed per reason, adapter-trimmed reads, insert-size peak and
duplication estimate.

### Filtlong (long reads)

Options verified against `filtlong --help` and the v0.2.1 README. `--min_mean_q` and `--min_window_q`
are **percent identities (0–100), not Phred scores**: Filtlong's mean quality is the mean per-base
accuracy implied by the Phred scores. Identity *X* therefore corresponds to an error-averaged quality
Q = −10·log₁₀(1 − X/100), the same definition ARVA uses for per-read mean quality (90 ≈ Q10,
95 ≈ Q13.0, 99 ≈ Q20). The interface shows this conversion next to each value and warns when a value
below 50 looks like a Phred score. `--keep_percent` and `--target_bases` are measured in bases. At
least one threshold is required. Kept reads (written to stdout by Filtlong) are gzip-compressed by ARVA.

### Before/after comparison

Both sides are ARVA read statistics computed by the same version of `arva-core`. Overlays use axes
on which both distributions are exactly defined: yield by minimum read length (exact points;
each curve equals its total below its own shortest read), per-read mean quality (integer Phred bins)
and per-read GC (integer percent). Length histograms are not overlaid because each file's bins
depend on its own length range.

## What ARVA does not do yet

- No pass/fail thresholds: suitability depends on technology, chemistry and purpose.
- No duplicate-read detection or k-mer analysis by ARVA itself (fastp reports a duplication estimate).
- No taxonomic or biological interpretation.

## Validation

`scientific-core/tests/test_seqstats.py` checks every metric against values computed by hand
(lengths, Nx/Lx, GC, Phred error averaging, Q20/Q30, per-position means, histograms conserving
counts, reproducible sampling) and checks that malformed inputs fail with the correct line numbers.
`workflows/tool-adapters/tests/` checks command construction for every option, output parsing,
safe execution (no shell, no secrets in the tool environment, timeouts) and runs each real tool on
the synthetic data; `apps/api/tests/test_tools_api.py` runs complete jobs, lineage and reports.

## References

- Ewing B, Green P. Base-calling of automated sequencer traces using phred. II. Error probabilities. *Genome Res* 1998;8:186–194. doi:10.1101/gr.8.3.186
- Cock PJA et al. The Sanger FASTQ file format for sequences with quality scores, and the Solexa/Illumina FASTQ variants. *Nucleic Acids Res* 2010;38:1767–1771. doi:10.1093/nar/gkp1137
- De Coster W et al. NanoPack: visualizing and processing long-read sequencing data. *Bioinformatics* 2018;34:2666–2669. doi:10.1093/bioinformatics/bty149
- Gurevich A et al. QUAST: quality assessment tool for genome assemblies. *Bioinformatics* 2013;29:1072–1075. doi:10.1093/bioinformatics/btt086
- Lander ES, Waterman MS. Genomic mapping by fingerprinting random clones: a mathematical analysis. *Genomics* 1988;2:231–239. doi:10.1016/0888-7543(88)90007-9
- Chen S, Zhou Y, Chen Y, Gu J. fastp: an ultra-fast all-in-one FASTQ preprocessor. *Bioinformatics* 2018;34:i884–i890. doi:10.1093/bioinformatics/bty560
- Shen W, Le S, Li Y, Hu F. SeqKit: a cross-platform and ultrafast toolkit for FASTA/Q file manipulation. *PLoS ONE* 2016;11:e0163962. doi:10.1371/journal.pone.0163962
- Wick RR. Filtlong. https://github.com/rrwick/Filtlong
- Andrews S. FastQC: a quality control tool for high throughput sequence data. https://www.bioinformatics.babraham.ac.uk/projects/fastqc/
- Cornish-Bowden A. Nomenclature for incompletely specified bases in nucleic acid sequences. *Nucleic Acids Res* 1985;13:3021–3030. doi:10.1093/nar/13.9.3021
