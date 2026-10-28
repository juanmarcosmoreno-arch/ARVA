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
  `Q_read = −10·log10(mean(10^(−Q_i/10)))`. NanoPlot/NanoStat compute their per-read values the same
  way (De Coster et al., 2018). Arithmetic means of Phred values are *not* used per read because they
  overestimate accuracy.
- **Mean / median read quality**: arithmetic mean of `Q_read` over reads with length > 0; median at
  0.1 Q resolution. NanoPlot's dataset "Mean read quality" instead averages the `Q_read` values again
  in error-probability space, so it is never higher than ARVA's value; the two are different quantities.
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

## Read-header metadata

Implementation: `scientific-core/arva_core/header_meta.py` (schema `arva.header_meta/1`).

- **What is read**: the header lines of the records checked at import (the first 1,000; collection
  stops earlier once 8 MiB of header text has been read, e.g. with Dorado move tables). Files
  registered before this feature get them when their read statistics are next computed.
- **Grammars**: each header is matched against documented layouts only, and every value keeps its
  documentation source: Illumina CASAVA 1.8+ / bcl2fastq / BCL Convert
  (`@instrument:run:flowcell:lane:tile:x:y[:UMI] read:Y|N:control:index|sample`), pre-1.8 Illumina
  names (community-documented), Element bases2fastq (recognised only by an `_AVITI` instrument suffix),
  ONT MinKNOW `key=value` attributes and Dorado tab-separated SAM tags, PacBio
  `{movie}/{hole}/ccs[/fwd|rev][/{qs}_{qe}]` and subread names, and NCBI SRA deflines. Tokens that no
  documented grammar explains are kept verbatim and never interpreted.
- **Confidence**: per header, *high* needs a complete documented grammar with several independent
  elements, *medium* a partial one (capped at medium inside SRA deflines), *low* a single weak cue
  (e.g. a UUID read ID), *none* nothing platform-specific. One exception: for Dorado SAM-tag headers a
  single `RG:Z` read group that starts with a UUID or a 40-hex run ID followed by `_` is enough for
  *high*, with or without other tags or a UUID read ID; the basecalling model after the run ID is not
  validated (an unclear model boundary only adds a parser warning). A file is *high* only when no
  header points elsewhere and ≥ 90 % are high; *medium* when ≤ 5 % disagree and ≥ 80 % are medium or
  better; otherwise *low* (ties between platforms go to the alphabetically last one).
- **Sample suggestion**: the weakest file-level confidence among files with evidence, capped at
  *medium* when some files have none; Illumina together with one long-read platform is suggested as
  *hybrid*; Nanopore together with PacBio gives no suggestion, also when Illumina files are present.
  The suggestion is shown next to the recorded technology with the number of files that carry
  evidence. "Use this" writes it to the sample, and is offered only while the technology is unset, the
  confidence is *medium* or *high* and every analysed file carries evidence; otherwise the suggestion
  is only a hint. When some files carry no evidence, a single-platform suggestion does not contradict a
  sample recorded as *hybrid* (`agrees` is null).
- **R1/R2 check**: the base read names (without `/1`, `/2`, or the `.1`, `.2` read number of
  `fastq-dump --readids` SRA names) and mate markers of the first 200 records are stored per file. For R1/R2 files paired by file name, the files look like mates when ≥ 99 % of
  names match position by position and no R1 read is marked 2 (or R2 read marked 1). A failed check
  is a warning only.
- **Limits**: read names are opaque identifiers that tools may rewrite (NCBI SRA replaces most of
  them), so a header without platform information is not evidence about the platform. Illumina read
  number 1 means "single-end or R1". Parsing never fails an import: lines are bounded (1,000,000
  characters, 512 tokens, values clipped to 256 characters), control characters are replaced (lines
  with more than 10 % of them are ignored) and any parser error stores no header metadata.

## POD5 raw-signal files

Detection: `scientific-core/arva_core/formats.py` (`check_pod5`). Run metadata:
`apps/api/app/tasks/pod5_summary.py` (job type `pod5_summary`, schema `arva.pod5_summary/1`), using
Oxford Nanopore's `pod5` library 0.3.49 (MPL-2.0) when it is installed, in a separate process
(`app/tasks/pod5_reader.py`) that validates each Arrow batch before reading it.

- **Recognition** is content-based and needs no library: a file is POD5 when its first eight bytes are
  the specification's signature `8B 50 4F 44 0D 0A 1A 0A`. It is complete only if it is at least 16
  bytes long and its last eight bytes repeat the signature (the specification places it there "to
  quickly check whether the file is complete"); otherwise it is registered as invalid with "Incomplete
  or truncated POD5 — the end signature is missing; copy the file again". A gzip FASTQ renamed
  `.pod5` is still a FASTQ; an empty file is not POD5. POD5 files never get an R1/R2 mate and have no
  read-header metadata.
- **No read-level analysis uses POD5**: read statistics, SeqKit, FastQC, fastp, Filtlong, the SeqKit
  cross-check and the before/after comparison refuse POD5 files (HTTP 400), and they are not listed in
  the read statistics of reports. POD5 holds signal, not bases: ARVA does not basecall. Basecalling
  (Dorado or MinKNOW) happens outside ARVA, and the resulting FASTQ is imported.
- **Run metadata**: the file is opened with `pod5.Reader`. ARVA records the file attributes
  (writing software, file identifier, file version before and after the library's migration, VBZ
  compression, batch count; `num_reads` only when there are batches, because the library raises
  otherwise), the run-information table (at most 50 entries are kept) and, from the read table, only
  `num_samples`, `run_info` and `channel_32bit`. Signal is never decoded, so memory does not grow
  with the file size. The read count is counted from the read table; pod5's own `num_reads` assumes
  equally sized batches and a disagreement is reported as a warning.
- **Signal duration** = Σ over acquisitions of (samples of its reads ÷ its sample rate). It is summed
  over all channels that recorded at the same time, so it is far longer than the run's wall-clock
  duration. If any read belongs to an acquisition without run information or sample rate, no
  duration is reported.
- **Potentially identifying fields** (`system_name`, `sequencer_position`, `context_tags`,
  `tracking_id`: host names, device serials and free-form maps) are written only to the job's JSON
  output and are not shown in the interface or in reports. Text values are cut at 1,024 characters
  and maps at 200 entries, with a warning; files listing more than 10,000 acquisitions are refused.
- **Limits**: validated with synthetic POD5 files written by the pod5 library, not with files from
  every MinKNOW version. POD5 bytes are not reproducible (random file identifier and section marker),
  so provenance is checked by content, not by the checksum of a regenerated file.

## Sample metadata tables (CSV / Excel)

Implementation: `apps/api/app/services/metadata_table.py` (pure functions) and
`apps/api/app/services/metadata_import.py` (preview, apply, export), with openpyxl 3.1.5 for `.xlsx`
and Python's `csv` module for text tables.

- **Reading**: every cell becomes text or empty; nothing is converted to a number, so `35,5` stays
  `35,5`. Text files are decoded as UTF-8 with BOM, UTF-16 with BOM, UTF-8, or else Windows-1252 with a
  warning (no catch-all Latin-1); NUL bytes refuse the file. The delimiter is the user's choice, a tab
  for `.tsv`, Excel's `sep=` first line, or `csv.Sniffer` restricted to `, ; TAB |`, falling back to the
  most frequent of these in the header line (a tie is an error). Row numbers are those a spreadsheet
  shows (the hidden `sep=` line is not counted). Workbooks are opened read-only with cached values:
  native dates become `YYYY-MM-DD` (time kept only when it is not midnight; 1904 workbooks are
  converted by openpyxl), whole floats below 2^53 become integers, numbers whose display format is
  only zeros (`000`) are padded as Excel shows them, with a warning; error cells (`#N/A`, …) become
  empty with a warning; formulas contribute only the value stored by the program that saved the file,
  and cells without one are reported; merged ranges are reported but never filled; the stored sheet
  dimensions are ignored (they can truncate the sheet). openpyxl's own warnings are passed on. The
  header row is the first row (of the first 20) that contains a sample-ID name, else the first with two
  or more cells; it can be chosen. Columns without a header are named `column_<letter>`, repeated
  headers get ` (2)`.
- **Mapping** is exact after normalisation (Unicode NFKD, accents removed, case folded, punctuation and
  text in brackets ignored) against English and Spanish names; there is no fuzzy matching (a bare
  `ID` stays a custom column). When two columns would map to the same field, the first wins and the
  other becomes custom metadata with a warning; the user's choices always win and may not assign one
  field twice.
- **Values**: `sample_code` is required, at most 255 characters, without tabs or line breaks and unique
  within the file ignoring letter case; a code that Excel stored as a non-integer number (`1.5`,
  `1.23E+19`) is a row error because the original cannot be recovered. Technology names map to
  Illumina, Oxford Nanopore, PacBio or hybrid (several families or "hybrid"/"híbrido"); other platforms
  and unknown text keep the original in custom metadata with a warning. "N/A", "unknown" and similar
  leave the technology unchanged. Dates are never guessed: accepted are ISO dates, `YYYY/MM/DD`,
  `D/M/YYYY` or `M/D/YYYY` when the value proves the order (a part > 12, or day = month), English or
  Spanish month names, an order written in the header (`Fecha (dd/mm/aaaa)`) or chosen by the user.
  Ambiguous, impossible, two-digit-year, serial-number and unrecognised dates block their row; partial
  dates (`2024`, `2024-03`) only warn and are kept as text. Evidence from other rows is reported but
  never applied. Control characters in a cell block the row.
- **Matching and writing**: a row updates the sample with the same ID, else the only sample whose ID
  matches ignoring case (several such samples are a row error); otherwise it creates one. Only
  mapped, non-empty cells are written; empty cells never clear stored values; custom columns are
  merged into `custom_metadata`; the sample ID itself is never changed. Apply recomputes the preview
  on the server from the uploaded file, refuses it if its SHA-256 differs from the previewed one,
  parses it, then locks the project row and writes all rows in one transaction (rows with errors are skipped and
  listed). `metadata_imports` records the file name, SHA-256, kind, sheet, encoding, delimiter, header
  row, mapping, date order, mode and the created/updated/unchanged/skipped counts; the table file
  itself is not stored.
- **Limits and hostile files**: 10 MiB, 10,000 rows, 256 columns, 10,000 characters per cell and
  20 million characters in total (configurable, except the last). Before a workbook is opened its zip
  container must have at most 2,000 parts and 100 MiB uncompressed, no part above 1 MiB may expand
  more than 250 times, no XML part outside the worksheets may exceed 16 MiB and the shared-strings
  table may hold at most 250,000 texts; entity-expansion XML is refused by the parser (expat ≥ 2.4).
  The chosen sheet's XML is then scanned once, as a stream, before it is read: at most 200,000 row and
  3,000,000 cell elements (empty formatted ones included), row numbers in ascending order and within
  Excel's 1,048,576, no value beyond the column limit, and values within 4 million cells of A1 (rows ×
  columns). Rows are then read only up to the last row and column that hold a value, so empty
  formatted cells far to the right cost nothing.
- **Messages**: every preview warning and row error has a stable code and parameters next to its
  English text; the interface shows it in the chosen language (EN/ES) and falls back to the English
  text for codes it does not know.
- **Export** (metadata CSV/Excel and the report CSV): CSV is UTF-8 with BOM, CRLF and every field
  quoted; text that starts with `=`, `+`, `-`, `@`, tab, CR or LF (or full-width `＝＋－＠`) gets a
  leading `'` as OWASP recommends, except plain numbers such as `-34.6`; text that already starts with
  apostrophes before such a character gets one more. Importing a CSV removes exactly one such
  apostrophe (with a row warning), so exporting and re-importing gives back the stored values. In `.xlsx` every cell is a text
  cell, so `=…` never becomes a formula and `#N/A` never an error; characters that XML cannot hold are
  replaced by U+FFFD. The report CSV applies the same prefix to its text columns only.

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
- No basecalling: POD5 raw signal must be basecalled outside ARVA (Dorado or MinKNOW).

## Validation

`scientific-core/tests/test_seqstats.py` checks every metric against values computed by hand
(lengths, Nx/Lx, GC, Phred error averaging, Q20/Q30, per-position means, histograms conserving
counts, reproducible sampling) and checks that malformed inputs fail with the correct line numbers.
`workflows/tool-adapters/tests/` checks command construction for every option, output parsing,
safe execution (no shell, no secrets in the tool environment, timeouts) and runs each real tool on
the synthetic data; `apps/api/tests/test_tools_api.py` runs complete jobs, lineage and reports.

## References

POD5: Oxford Nanopore Technologies, POD5 file format specification (pod5-file-format 0.3.49,
`docs/SPECIFICATION.md` and `docs/tables/run_info.toml`),
https://raw.githubusercontent.com/nanoporetech/pod5-file-format/0.3.49/docs/SPECIFICATION.md.

Metadata tables: openpyxl 3.1 documentation (Gazoni E, Clark C; https://openpyxl.readthedocs.io/en/stable/);
Python `csv` module documentation (https://docs.python.org/3/library/csv.html); OWASP Foundation,
"CSV Injection" (https://owasp.org/www-community/attacks/CSV_Injection).

Read-header grammars: Illumina BaseSpace Help "FASTQ files"; bcl2fastq2 v2.20 Software Guide
(15051736 v03, Table 7); DRAGEN v4.2 BCL Convert output files; Element Biosciences bases2fastq output
files; ONT output specifications (FASTQ v0.1) and Dorado SAM specification; PacBio BAM format
specification 13.1 (QNAME convention); NCBI sra-tools wiki "HowTo: fasterq-dump" and "Read-Names".

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
