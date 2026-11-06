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
| MultiQC | 1.35 | Project-level report gathering the four tools' results |
| NanoPlot | 1.48.0 | Long-read statistics and interactive report (with nanoget 1.19.6) |
| Flye | 2.9.3 | Long-read de novo assembly (Phase 3; with samtools for its `flye-samtools` helper) |
| SPAdes | 3.15.5 | Short-read de novo assembly of bacterial isolates (Phase 3) |
| Unicycler | 0.5.0 | Short-read, long-read-only and hybrid assembly (Phase 3; with SPAdes 3.15.5, Racon 1.5.0 and BLAST+ 2.12.0) |
| Medaka | 2.1.1 (Bioconda) | Oxford Nanopore polishing with the model for the reads' basecaller model (see *Polishing*) |

### Independent cross-check (SeqKit)

ARVA compares its own statistics with SeqKit's for the same file. Counts and lengths (reads, total
bases, minimum, maximum, N50) must match exactly; mean length is allowed 0.05 bp and percentages
(Q20, Q30, GC) 0.005 percentage points, which is SeqKit's output rounding and nothing more.
Quartiles are **not** compared: SeqKit 2.3.0 reports Q1 = Q3 = 75 for a file of uniform 150 bp
reads, which is incorrect. GC is compared only when the file has no ambiguous bases. Disagreements are
displayed, never hidden. On the synthetic example data all compared metrics agree.

### FastQC

FastQC is run unchanged (`--outdir --noextract --quiet --threads 1 --dir <tmp>`). When FastQC 0.12 or later stops
with a Java `OutOfMemoryError` at its default 512 MB heap (seen on Nanopore reads up to 228 kb), ARVA runs it once
more with `--memory 2048` (at most half the job's memory limit) and logs why; its HTML and ZIP
outputs are stored, and `summary.txt`/`fastqc_data.txt` are parsed for module flags and basic
statistics. The flags are FastQC's heuristics for whole-genome shotgun libraries and are shown as such.

Charts from `fastqc_data.txt` (format verified for FastQC 0.12.1). The zip is read only when FastQC
exited with status 0 and the zip opens; the parsed modules are stored as `fastqc_data.json` next to the
report, and the job summary keeps only the figures used in the sample report. Older FastQC jobs are
parsed from their stored zip on request (`GET /jobs/{id}/fastqc-data`). Modules are read by column
name; a module that is absent is reported as absent, and one whose columns are not recognised is listed
rather than guessed.

- **Adapter content**: one curve per adapter column of the module (FastQC's adapter list, 12-base
  sequences), the cumulative % of reads in which the adapter has been seen at or before each position.
  Position labels `a` or `a-b` are 1-based and inclusive and are parsed per module: FastQC groups
  positions above 75 bp into bins (for 150 bp reads, 2 bp bins in Adapter Content but 5 bp in the
  per-base modules; 500 bp bins for the 26 kb synthetic long reads) and each binned value is the mean over its positions, so ARVA draws it at
  the bin's centre. FastQC's WARN (> 5 %) and FAIL (> 10 %) thresholds are drawn as labelled lines.
- **Duplication levels**: the 16 fixed bins (1–9 copies, 10–50, 51–100, 101–500, 501–1,000,
  1,001–5,000, 5,001–10,000, more; from `DuplicationLevel.java`) with FastQC's "Percentage of total".
  "Total Deduplicated Percentage" is shown as the share of reads remaining if deduplicated, and
  duplicates as 100 minus it. FastQC tracks only sequences first seen in the first 100,000 reads,
  truncates every read longer than 50 bp to 50 bp (FastQC 0.12.1 source, `OverRepresentedSeqs.java`;
  the documentation says reads over 75 bp) and reports corrected estimates. The chart is greyed out for
  long reads (a Nanopore/PacBio sample, or reads longer than 1,000 bp).
- **Overrepresented sequences**: sequence, count, % and FastQC's possible source, first 20 rows. An
  empty module has no header row and is an empty table. When FastQC lists every read (a file of fewer
  than 1,000 reads, where one read is > 0.1 %), ARVA says so instead of implying contamination.

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

Length, trimming and complexity options (behaviour checked in the fastp 0.23.4 source and on the
synthetic data; the same options and limits exist in 0.23.2). Each is passed explicitly, also at its
default, so the recorded command is complete:

| ARVA option | fastp option | What it does |
|---|---|---|
| Discard reads shorter than | `--length_required` (15) | Removes reads shorter than N after trimming |
| Discard reads longer than | `--length_limit` (0 = off) | **Removes** reads longer than N after trimming (`rlen > N`, so N bp is kept). In pairs, the pair goes when either mate is too long, and `too_long_reads` counts reads, both mates included. `--disable_length_filtering` also turns it off, so ARVA rejects a limit without length filtering, and a limit below the minimum length (fastp would accept it and discard every read) |
| Cut from the 5′ start / 3′ end | `--trim_front1/--trim_tail1` (`-F/-T` for read 2) | Removes a fixed number of bases from every read; fastp accepts 0–30 and 0–100 |
| Trim reads longer than | `--max_len1` (`--max_len2`) (0 = off) | **Shortens** longer reads to N bp from the 3′ end; no read is removed |
| Remove low-complexity reads | `--low_complexity_filter --complexity_threshold` (off; 30) | Complexity = share of positions whose base differs from the next one, diff ÷ (length − 1); a read below the threshold % is removed. `low_complexity_reads` appears in fastp.json only when the filter is on |
| Adapter sequence, read 1 / read 2 | `--adapter_sequence`, `--adapter_sequence_r2` | Single end: replaces auto-detection. Paired end: used only where the mates do not overlap; an unset read-2 adapter is auto-detected with `--detect_adapter_for_pe`, otherwise it is the read-1 adapter. fastp requires more than 3 bases of A/C/G/T; ARVA allows 4–200 |

fastp makes unset read-2 trims and `--max_len2` follow read 1 (`main.cpp`); ARVA writes the read-2
values out for pairs and rejects read-2 options for single-end input. `--reads_to_process` is not offered:
it takes the first N reads in file order, which is neither a random subsample nor a number of bases.
fastp's single-end adapter auto-detection found no adapter in the synthetic R1 file although FastQC
shows the Illumina Universal Adapter rising to 7.4 % of reads; given the sequence, fastp trimmed 149
reads. The filter dialog therefore warns when the latest FastQC report of a file shows an adapter
(other than its PolyA/PolyG rows) above 5 % of reads and the previous fastp run on that file, with
adapter trimming on, trimmed none. When no read passes, fastp writes 0-byte `.fq.gz` files and exits
with status 0; ARVA fails the job ("fastp kept no reads with these thresholds; nothing was
registered", with the counts per reason) and registers no derived file. An output that does not open
as FASTQ fails the job the same way.

The insert-size peak is an estimate: fastp measures inserts only in the pairs its worker thread 0 reads
(packs of 1,000 pairs dealt to the threads in turn), so the peak depends on `--thread` and on which
pairs overlap. ARVA labels it as an estimate everywhere and gives it with the number of pairs evaluated
and the share that overlapped, in the interface and in the sample report.

Charts from the stored `fastp.json` (format verified for fastp 0.23.4; `GET /jobs/{id}/fastp-data`):
per-cycle mean quality (arithmetic mean of the Phred scores at each cycle) and GC/N content (fractions,
shown as %) of read 1 and read 2 before and after filtering, on the axis 1…`total_cycles`, with shorter
curves left empty beyond their last cycle; numbers may be written as integers (`0`) and are read as
floats. Adapter trimming (`adapter_trimmed_reads/bases` and the sequences found in at least 1 % of the
trimmed reads, plus "others") is optional: fastp omits the block when trimming is off or when it detects
no adapter in single-end reads. The duplication rate is a single fraction and is absent with
`--dont_eval_duplication`. The insert-size histogram (paired-end only) is collected by fastp's worker
thread 0 alone, so it covers a subset of the pairs and depends on `--thread`; "unknown" counts pairs
without a detected overlap and inserts of 512 bp or more. ARVA shows it as a % of the pairs evaluated,
with the peak, the share that overlapped and the thread count, and labels it an estimate.

### Filtlong (long reads)

Options verified against `filtlong --help` and the v0.2.1 README. `--min_mean_q` and `--min_window_q`
are **percent identities (0–100), not Phred scores**: Filtlong's mean quality is the mean per-base
accuracy implied by the Phred scores. Identity *X* therefore corresponds to an error-averaged quality
Q = −10·log₁₀(1 − X/100), the same definition ARVA uses for per-read mean quality (90 ≈ Q10,
95 ≈ Q13.0, 99 ≈ Q20). The interface shows this conversion next to each value and warns when a value
below 50 looks like a Phred score. `--keep_percent` and `--target_bases` are measured in bases. At
least one threshold is required. Kept reads (written to stdout by Filtlong) are gzip-compressed by ARVA.
Filtlong formats the counts in its log with the process locale (en_US writes 1,362,402, es_ES
1.362.402, and a locale that is not installed makes it abort), so ARVA runs it with `LC_ALL=C`; logs
of earlier runs are read with either separator.

**Target bases and target coverage.** `--target_bases N` keeps the best-scoring reads while the running
total is still below N (`main.cpp`), so the kept bases lie between N and N − 1 + the longest read; on the
synthetic long reads (400 reads, 1,513,780 bp) `--target_bases 500000` keeps 504,167 bp. With
`--keep_percent` as well, Filtlong uses the smaller of the two targets. Filtlong logs one of three
outcomes, which ARVA parses and shows: `keeping N bp`; `not enough reads to reach target` (the target is
at or above the input bases); `reads already fall below target after filtering` (the reads passing the
hard thresholds hold no more bases than the target). In the last two, no read is removed to meet the
target; reads failing the hard thresholds are still removed.

A coverage target is ARVA's own derivation, not a Filtlong option: target bases = round(depth × genome
size), rounded half up (the interface and the server compute the same value). The genome size is
pre-filled only from the size the user gave for the file's read statistics, otherwise typed by the user;
ARVA never assumes one. The request carries `genome_size_bp` and `target_coverage_x`; the server
recomputes the target, rejects a `target_bases` that does not match, and records all three in the job
parameters, while Filtlong receives only `--target_bases`. Before running, the dialog shows the target
and the expected kept bases from ARVA's statistics of the input: between the target and the target plus
one read (capped at the input), or everything when the input is not larger than the target. After the
run, ARVA's statistics of the output give the bases actually kept and, with the genome size, the depth
achieved (bases ÷ genome size), shown in the before/after comparison.

### Before/after comparison

Both sides are ARVA read statistics computed by the same version of `arva-core`. Overlays use axes
on which both distributions are exactly defined: yield by minimum read length (exact points;
each curve equals its total below its own shortest read), per-read mean quality (integer Phred bins)
and per-read GC (integer percent). Length histograms are not overlaid because each file's bins
depend on its own length range. When a genome size is known (entered for a Filtlong coverage target,
otherwise given for the input's read statistics), the table adds the approximate depth before and after
(total bases ÷ genome size, the same estimate as in the read statistics).

### MultiQC (project report)

MultiQC reads the outputs of other tools; it measures nothing itself. ARVA uses it as a project-level
view, never as the source of QC numbers and never as an independent check.

- **Inputs.** For each selected sample: the most recent completed FastQC and SeqKit result of each file
  and the most recent completed fastp and Filtlong result of each input file or read pair, only for
  files ARVA has read in full with its own read statistics and found valid (import checks only the
  start of a file, so a result on a file that later fails full validation, or was never fully read, is
  left out with the reason). Results on derived (filtered) files are used only when the user asks for
  them. Filtlong runs without
  `--target_bases` or `--keep_percent` are left out: only with a target does Filtlong log the totals
  MultiQC reads. The selection and every exclusion with its reason are shown before running and stored
  in the job's parameters.
- **Run.** The chosen files are copied into the job folder as `arva-NNNN<suffix>` and passed as an
  exact list (`--file-list`), never as a folder to search. Sample names are the staged file names
  (`--fn_as_s_name --fullnames`) renamed exactly (`--replace-names` with `sample_names_replace_exact`)
  to `<sample ID> <file>`, where the file is R1/R2 or its name (plus "after fastp/Filtlong" for derived
  files). One name belongs to one sample and file set in every module, because MultiQC joins
  general-statistics rows by name: when two samples or files would get the same name after the markup
  characters MultiQC does not escape are replaced (for example sample IDs `A/1` and `A_1`), the first 8
  characters of their ARVA IDs are added, and the job refuses a name shared by different samples or
  files. Filtlong logs with digit grouping, which MultiQC 1.35 cannot read, are staged without the
  separators (logged). The configuration disables MultiQC's version check (also `--no-version-check` and
  `MULTIQC_NO_VERSION_CHECK=true`), AI features and analysis paths, keeps counts unscaled and removes
  DOI badges whose hover queries api.crossref.org. Filtlong's search window is widened to 20 lines
  because its progress output hides the marker MultiQC looks for.
- **Checks.** MultiQC exits with status 0 even when it finds nothing or silently drops one of two
  inputs that received the same name, so ARVA requires the report and its data folder to exist and
  every input to appear exactly once, under its own name, in `multiqc_sources.txt`; otherwise the job
  fails and lists the problem. `--require-logs` makes MultiQC itself fail when a requested module
  finds no file.
- **Values.** ARVA reads the general statistics from `multiqc_data.json`
  (`report_general_stats_data`), which holds values before display scaling, and records the unit of each
  key for MultiQC 1.35: fastp Q30 rate and GC content are fractions (0–1), MultiQC shows them × 100;
  fastp % passing filter, % adapter and % duplication, FastQC % duplicates, % failed modules, mean and
  median length are computed by MultiQC and labelled so. Keys ARVA does not know are listed, not
  parsed. `multiqc_general_stats.txt` (scaled) and `multiqc_fastp.txt` (Python object text, not JSON)
  are never parsed. Metrics with similar names from different tools (FastQC's integer %GC, SeqKit's
  GC(%), fastp's GC fraction after filtering) are shown side by side with their own definitions and are
  not compared.
- **Provenance.** The job records ARVA's own argument vector (MultiQC's `report_multiqc_command` drops
  shell quoting), the source job, tool and version of every input and the SHA-256 of each staged copy.
  SeqKit and Filtlong outputs carry no version, so the versions come from ARVA's job records.

### NanoPlot (long reads)

NanoPlot summarises one long-read FASTQ file. ARVA keeps its numbers as NanoPlot's, with NanoPlot's
definitions, and compares with its own statistics only what both define identically.

- **Run.** `NanoPlot --fastq <link> --outdir <job> --prefix <name>_ --threads <n> --no_static
  --only-report --include-js embedded --tsv_stats`, in an empty working folder with HOME and the XDG
  folders pointing at an empty job folder that is checked afterwards for browser files (without
  `--no_static` NanoPlot downloads and runs Chrome for Testing). nanoget picks its reader from the file
  extension only, so the input is a link named `<name>.fastq` or `<name>.fastq.gz` after ARVA's
  content-based format. `--downsample` (unseeded) and `--info_in_report` (writes folder paths into the
  report) are never used. NanoPlot is only offered for long reads: the sample's technology must be
  Nanopore or PacBio, or the user confirms it.
- **Checks.** Exit status 0 *and* NanoStats.txt, the report and one log file. NanoPlot writes
  NanoStats.txt before it can stop with "No reads left after filtering" (exit status 1); that message
  becomes the job's error.
- **Values.** NanoStats.txt (`--tsv_stats`) is read by row name. It describes every read nanoget kept;
  nanoget silently skips zero-length records. After writing it NanoPlot removes reads shorter than 20
  bases with mean quality above 30 as basecaller artefacts and, if there were any, describes the rest in
  NanoStats_post_filtering.txt (shown as a second column).
- **Cross-check.** Reads and total bases have identical definitions and are compared exactly; a read
  count lower by exactly ARVA's number of zero-length records (now reported as `zero_length_reads`) is
  shown as explained, any other difference as a difference.
- **Not compared.** NanoPlot's N50 takes the first length at which the cumulative sum of lengths sorted
  in *ascending* order reaches half the bases (lengths 2, 3, 5: NanoPlot 3, ARVA and SeqKit 5);
  "Reads >QN" uses a strict `>` where ARVA uses `≥`; the mean read quality averages the per-read
  qualities again as error probabilities, unweighted by length (ARVA's mean read quality is their
  arithmetic mean). N50 and the shared quality thresholds are shown side by side with these
  definitions; NanoPlot's mean and median read quality are shown only on their own. NanoPlot computes
  them with the modified copy of nanomath its wheel ships (`ave_qual_floats`); a stock nanomath
  installed into the same environment replaces it silently (same `--version`, mean quality 9.8 instead
  of 10.2 on the synthetic reads), so detection imports nanomath with NanoPlot's own interpreter and
  reports NanoPlot as failed when that function is missing.
- **Report.** The plots are drawn from unseeded random subsets of at most 10,000 reads (2,000 for the
  density plot), so for larger files they are not byte-reproducible; NanoStats.txt is. The report is
  served with the standard sandboxed CSP; `scripts/check_nanoplot_report.cjs` (run by the API tests)
  confirms in headless Chromium that all plots render, no request leaves the page and the page cannot
  reach ARVA's origin.

## Sequencing overview and project QC overview

Both tables only show results of completed jobs, always the latest completed one per file; a missing
value is shown as "—" with its reason (not computed, being computed, failed, not applicable). Nothing
is recomputed from the files.

- **Sample sequencing overview** (QC tab). One row per file in lineage order: imported files, each
  followed by the files derived from it, labelled with the parent and the producing tool and version.
  Reads, bases, mean length, N50, mean read quality, bases ≥ Q30 and GC are ARVA's read statistics of
  that file (arva-core version shown); mean read quality is ARVA's arithmetic mean of per-read
  qualities, not NanoPlot's dataset mean (see Quality). For a derived file the share of its parent's
  bases is given, both from ARVA statistics. POD5 files show the read count and the summed signal
  duration of their latest pod5 job. The bar chart has one value axis (bases); imported and derived
  files are told apart by colour, by an arrow and indentation under their parent, and in the tooltip.
- **Project QC overview** (`GET /projects/{id}/qc-overview`, `…/qc-overview.csv`). One row per sample.
  *Read files* are the imported FASTQ/FASTA files; POD5 and unrecognised files are counted as imported
  files but hold no reads.
  - Reads and bases: sums over the read files. They, bases ≥ Q30, GC and depth are reported only when
    every read file has ARVA statistics, so a partial sum is never presented as a total.
  - N50 and mean read quality: those of the read file with the most bases (on a tie, the one imported
    first). Neither can be combined exactly across files, so they are not averaged.
  - Bases ≥ Q30: Σ(Q30%ᵢ × basesᵢ) ÷ Σ basesᵢ over the FASTQ read files; GC:
    Σ(GC%ᵢ × (basesᵢ − ambiguousᵢ)) ÷ Σ(basesᵢ − ambiguousᵢ). Both equal ARVA's value for the
    concatenated files. In a hybrid sample they are dominated by the technology with more bases.
  - Depth: total bases ÷ the expected genome size the user entered when computing the statistics,
    only if the same size was entered for every read file (otherwise "no genome size" or "genome
    sizes differ"). ARVA never assumes a genome size.
  - Filtering: the latest completed fastp or Filtlong run of the sample and the number of runs; reads
    and bases kept = ARVA statistics of its output files ÷ those of its input files (empty until both
    exist). On the synthetic paired-end data this reproduces fastp's own read counts exactly.
  - FastQC: PASS/WARN/FAIL module flags summed over the latest report of each imported FASTQ file,
    labelled as FastQC heuristics.
  - SeqKit check: per imported read file, the comparison of the SeqKit cross-check; *agree* when every
    read file was checked and agrees, *partial* when only some were checked, *differs* when any metric
    of any checked file differs (the metrics are listed), *not run* otherwise.
  - The rows come from four queries whatever the number of samples. The CSV is UTF-8 with BOM, CRLF,
    every field quoted and text cells neutralised against formula injection (the same sanitiser as the
    metadata export); column names state the source and the rule (e.g.
    `n50_bp_largest_file_arva`, `fastqc_heuristics_fail_modules`).

## Assembly statistics (Phase 3)

Implementation: `scientific-core/arva_core/assembly_stats.py` (tool name `arva-core.assembly_stats`,
version recorded with every assembly). Statistics are computed by ARVA from the assembler's contigs
FASTA, so the same definitions apply whatever the assembler.

- **Ranking**: contigs are sorted by length, longest first. Contigs of equal length keep their order
  in the FASTA file (stable sort); Nx and Lx do not depend on that order, because tied contigs have the
  same length.
- **Nx / Lx** (N50, N90): Nx is the length of the ranked contig at which the cumulative length first
  reaches *at least* x % of the total length; Lx is that contig's rank, i.e. the smallest number of
  contigs whose lengths add up to at least x % (the definitions used by QUAST; Gurevich et al., 2013).
  The comparison is made in integers (100 × cumulative ≥ x × total), so there is no rounding at the
  boundary. Example: lengths 5, 3, 2 give N50 = 5 and L50 = 1 (5 is exactly half of 10).
- **GC %** = (G + C) ÷ (A + C + G + T) × 100 over unambiguous bases only, for the assembly and for each
  contig (soft-masked lower-case bases count). N and the other IUPAC codes are counted separately
  (`n_count`, `N per 100 kb`, `other_iupac_count`) and never enter the denominator. QUAST first turns the
  IUPAC codes M, K, R, Y, W, S, V, B, H, D into N and then divides by all bases except N, so its GC is the
  same; it does count those codes in its "# N's per 100 kbp" (checked with QUAST 5.2.0, see below).
- **Also reported**: number of contigs, total length, largest and smallest contig; contigs and total
  length at or above 1 kb and 10 kb (configurable); a length histogram with fixed 1-2-5 bins (0, 100,
  200, 500 bp, 1 kb, 2 kb, … — lower edge inclusive, upper edge exclusive — from the bin of the
  shortest contig to that of the longest), so assemblies can be compared bin by bin; the sorted lengths
  with their cumulative length (all contigs up to 1,000; above that the 500 longest, then evenly spaced
  ranks up to the last contig, marked as down-sampled).
- **Assembler annotations**: per-contig coverage, circularity and repeat flags are what the assembler
  reports (e.g. Flye's `assembly_info.txt`); ARVA does not recompute them. The assemblers define coverage
  differently, and every assembly carries its `coverage_kind`: Flye's is a mean **read depth**
  (`read_depth`), SPAdes' a **k-mer coverage** (`kmer_coverage`), Unicycler's a **depth relative** to the
  main replicons (`relative_depth`). The interface, reports and exports label values by kind, format them
  in the assembler's terms, and never compare values of different kinds (the comparison view says so when
  assemblies of different kinds are shown together). SPAdes reports no circularity: such assemblies show
  "not reported", and the chromosome-circularity check is listed as not evaluated. The coverage summary is the
  **length-weighted median**: the coverage of the contig holding the middle base when the contigs with
  a coverage are ordered by coverage.
- **Storage**: one row per contig is kept for the 2,000 longest contigs (the statistics always use every
  contig; the record says how many rows were left out). The contigs FASTA, graph (GFA) and assembler
  information file are checksummed (SHA-256), made read-only and kept in the job's `results/` folder;
  they are never registered as read files. The record lists the exact read files (imported or derived)
  the assembler used.

### Assembly warnings (heuristics)

Each warning is labelled as a heuristic and states its threshold; it marks a result worth checking, not
a verdict. Every check is listed with the assembly, including those that could not be evaluated and
why, so a missing warning is never mistaken for a passed check.

| Code | Rule (fixed thresholds) | Possible meanings |
|---|---|---|
| `many_contigs` | more than 10 contigs per Mb (long-read and hybrid assemblies) or 100 per Mb (short-read); assemblies under 1 Mb count as 1 Mb | fragmented assembly |
| `genome_size_mismatch` | total length more than 20 % above or below the expected genome size; only when a size is known | incomplete genome, contamination, duplicated sequence |
| `low_coverage_contigs` | coverage below 0.25 × the length-weighted median; needs coverage for at least two contigs | contamination, sequence present in only part of the cells |
| `high_coverage_contigs` | coverage above 4 × the length-weighted median; same condition | plasmids or other multi-copy elements, collapsed repeats |
| `chromosome_not_circular` | a contig of at least 50 % of the expected genome size (else of the total assembly length) that the assembler reported as not circular; skipped when it reports no circularity | incomplete chromosome or misassembly |
| `gc_outlier_contigs` | a contig of at least 1 kb whose GC differs from the assembly's by more than 10 percentage points; needs two such contigs | contamination; plasmids and other mobile elements often differ in GC |

**Expected genome size**: the size the user gives for the assembly itself; otherwise the size entered
for the sample's read statistics, taking the newest completed statistics of each read file and only
when all those that have a size agree (different sizes make it "inconsistent", i.e. unknown). ARVA
never assumes a genome size; which source was used is stored with the assembly.

### Assembly graph

`GET /assemblies/{id}/graph` reads the assembler's GFA 1 file (`arva_core/gfa.py`; GFA 1 specification):
segments with their length and numeric tags, links with orientations and overlap, and paths (P lines)
with the segments they run through. Tags are returned as written, because assemblers define them
differently (Flye's `dp` is a mean read depth; Unicycler's `dp` is relative to the chromosome; SPAdes'
`KC` is a k-mer count); the API names the tag that holds each assembler's segment coverage
(`coverage_tag`: Flye `dp`, mean read depth; SPAdes `DP`, k-mer coverage — its `KC` is the segment's k-mer
count and DP = KC ÷ (segment length − k); Unicycler `dp`, relative depth) and leaves it empty for assemblers
it does not know. SPAdes' P lines are scaffold paths named after the scaffold with a part suffix (`_1`,
`_2`…), so they are listed as written and not matched to contig rows; Unicycler writes no P lines.
Above `max_nodes` (default 2,000) the longest segments are kept and only links between them are
returned, at most `max_edges` (default 5,000), with `truncated: true`. GFA 2 files and malformed
records (including path steps without an orientation) are rejected with the line number.

Contig membership comes from the P lines: Flye 2.9 and later write one P line per contig (Flye's
release notes; checked on real Flye 2.9.3 output, e.g. `P contig_1 edge_1+ *`). Each segment lists the
paths through it (at most 20, in file order). Its `circular` and `repeat` flags are derived from the
assembler's flags of those contigs as stored with the assembly: true when any of them has the flag,
false when all that report it do not, and null when none reports it (no path, or a contig whose row is
not stored). These are the assembler's calls about contigs, transferred to segments; ARVA does not
infer circularity or repeats from the graph topology.

The interface draws the graph with ECharts' force layout from at most the 500 longest segments and
2,000 links (a truncation notice states how many of each the file has). Node size is 6 + 34 × √(segment
length ÷ longest drawn segment) px; colour is the segment's class (in a circular contig, in a repeat
contig, in another contig, no contig information), in that order of precedence; layout positions carry
no meaning. A link from a segment to itself (Flye writes them for circular contigs) cannot be drawn by
ECharts 5.5 (both ends are at the same point), so self-links are listed in the tooltip and table and
counted in a note. For the full graph, the GFA can be downloaded and opened in Bandage (Wick et al., 2015).

### Assembly views, comparison and reports

All values below come from the stored assembly record (ARVA's statistics and the assembler's per-contig
annotations); nothing is recomputed in the browser except sorting and the chart geometry.

- **Summary tiles**: contigs, total length, largest contig, N50, L50, N90, L90, GC %, circular contigs
  (of those with a circularity flag, as reported by the assembler) and the length-weighted median of
  the assembler's coverage. The contig N50 is not the read N50: the definition is the same, the objects
  (contigs, reads) are not, and the two are never compared.
- **Contig table**: sortable by rank, name, length, coverage, GC, circular and repeat; contigs without a
  value always sort last, ties keep the length rank. Flye's multiplicity, alternative group and graph
  path are shown as Flye wrote them.
- **Charts** (each with its data table and SVG/PNG export): the length histogram with the 1-2-5 bins of
  the statistics (weighted by contigs or bases); the Nx curve, where each ranked contig is a horizontal
  step at its length from 100 × (cumulative length before it) ÷ total to 100 × (cumulative length
  including it) ÷ total, with N50 and N90 marked (logarithmic length axis when the longest contig is at
  least 100 × the shortest); the cumulative length by rank, with the expected genome size marked when
  it is known; coverage against length and GC against coverage, one point per stored contig with a
  coverage value, split by the assembler's circularity flag, the tooltip naming the contig.
- **Comparison**: with two or more assemblies of a sample, a table of the same statistics side by side
  and their cumulative curves on shared axes, for the six newest assemblies (one colour each from the
  validated categorical palette). Contiguity is compared, not correctness; QUAST with a reference of the
  same strain addresses correctness.
- **Project page**: one row per assembly of the project's samples (`GET /projects/{id}/assemblies`),
  ordered by sample ID and then newest first.
- **Reports**: the sample report's JSON has an `assemblies` list (inputs with their lineage and SHA-256,
  the job's exact command, tool path, parameters and timings, the statistics, the 20 longest contigs,
  the output files with SHA-256, the warnings and every check, and the metrics of each completed QUAST
  evaluation that included the assembly, with its minimum contig length and reference); the HTML report
  shows the same in an Assembly section; the CSV adds one row per assembly (`record_type` = `assembly`)
  with assembly-specific columns (`contig_n50`, `contig_l50`, …) and leaves the read columns empty, so a
  contig N50 never lands in the read `n50` column. Every text cell of the CSV is neutralised against
  formula injection (OWASP).

### Flye (long-read assembly)

Implementation: `workflows/tool-adapters/arva_tools/flye.py` (command, option checks, output and log
parsing, read-type suggestion), `apps/api/app/tasks/tools.py` (job), `apps/api/app/services/flye.py`
(request checks, suggestion inputs, genome-size options). Options, ranges and behaviour were verified
against `flye --help`, the Flye 2.9.3 manual and README, and the source of the installed Flye 2.9.3
(`flye/main.py`, `config/configurator.py`, `assembly/assemble.py`, `utils/sam_parser.py`).

- **Inputs.** One or more FASTQ files of the sample, imported or derived (e.g. Filtlong output),
  recorded by id with their SHA-256. Refused with a reason (HTTP 400): POD5, non-FASTQ and invalid
  files; files marked R1/R2 (paired-end, short reads); files whose read headers identify Illumina with
  high or medium confidence; samples whose technology is Illumina; selections whose files have
  confidently different long-read platforms (Flye takes one read type per run); selections in which no
  file has a read longer than 1,000 bp according to ARVA's statistics (Flye only uses reads longer than
  its minimum overlap, which is at least 1,000 bp, and otherwise stops with "No reads above minimum
  length threshold"); a read type for one platform when the sample's technology, or a high-confidence
  header platform, is the other. A sample whose technology is neither Nanopore, PacBio nor hybrid
  needs the user's confirmation that the files hold long reads. A filtered file and a file it was filtered from
  cannot be selected together (the interface blocks it and the API refuses it): they hold the same reads under the
  same names, and Flye stops on duplicated read IDs (seen with Filtlong's output of SRR21386012).
- **Command.** `flye --<read type> <reads…> --out-dir <job>/flye --threads <n> --iterations <n>`, plus
  `--genome-size`, `--min-overlap`, `--asm-coverage`, `--read-error`, `--meta`, `--keep-haplotypes`,
  `--no-alt-contigs` and `--scaffold` when chosen. Threads and polishing iterations are always passed.
  Every option used must appear in the installed Flye's own `--help` (checked when the job is created
  and again in the worker), so an option a version lacks is refused instead of being guessed. Flye's
  own ranges are enforced: threads 1–128 (capped by `ARVA_TOOL_THREADS`), iterations 0–10, minimum
  overlap 1,000–10,000 bp; `--asm-coverage` requires `--genome-size` and cannot be combined with
  `--meta`; `--read-error` (a fraction) only with the corrected, nano-hq and hifi read types. Reads are
  passed as links named `NN_<name>.fastq[.gz]`, because Flye takes the format from the file name and
  refuses paths with spaces. `--deterministic` is not offered (see Reproducibility).
- **Read type: ARVA's suggestion (heuristic).** Flye 2.9.6's descriptions (`--help` and docs/USAGE.md,
  "Oxford Nanopore"): `--nano-hq` for R10 (Q20) reads with < 3 % error ("R10 ONT parameters (3% error)
  are now default for --nano-hq", docs/NEWS.md 2.9.6), `--nano-hq --read-error 0.05` for R9 Guppy 5+
  reads with < 5 % error, `--nano-raw` for older ONT reads (10–20 %), `--pacbio-hifi` < 1 %, corrected
  reads < 3 %. ARVA suggests a value, labelled as a heuristic and never applied by itself:
  the platform comes from the sample's technology, else from the read headers when every file
  identifies the same long-read platform with high or medium confidence. For Nanopore reads the mean
  error probability over all bases of the selected files, `Σ_files bases × 10^(−Q̄/10) ÷ Σ bases`
  where `Q̄` is each file's error-averaged mean base quality, gives `--nano-hq` at ≤ 3 %, `--nano-hq`
  with `--read-error 0.05` above 3 % and up to 5 %, and `--nano-raw` above 5 %; without ARVA
  statistics, a SUP basecall model in the read headers gives `--nano-hq`, otherwise there is no
  suggestion. At ≤ 1 % the interface notes that Flye 2.9.6's `--nano-hq` defaults already are its R10
  (3 %) parameters, so no `--read-error` is needed. For PacBio, ≤ 1 % gives
  `--pacbio-hifi`; without statistics CCS read names give `--pacbio-hifi` and subread names
  `--pacbio-raw`. Qualities are the basecaller's estimates; the suggestion and its basis are stored
  with the job (`arva_read_type_suggestion`), next to the read type the user chose.
- **`--nano-hq` or `--nano-raw` for reads under 3 % error.** ARVA follows Flye's manual: Nanopore reads under
  3 % error get `--nano-hq` (Flye 2.9.6 `--help`: "ONT R10 reads, aka Q20 (<3% error)"; docs/USAGE.md: "For
  R10 data, use --nano-hq. Expected error rate is <3%"; `--nano-raw` is for "ONT reads with odler [sic] chemistries,
  pre R9 Guppy5 (10-20% error)"). Some published pipelines run `--nano-raw` on the same reads. What the choice changes, from
  Flye 2.9.6's own files: flye/main.py sets the read type and flye/config/py_cfg.py (`bin_cfg`) picks
  `asm_nano_hq.cfg` for `--nano-hq` and `asm_raw_reads.cfg` for `--nano-raw`. Compared with the raw-read file,
  the nano-hq file uses minimizers (`use_minimizers = 1`, `minimizer_window = 10`), base-level read alignment
  (`reads_base_alignment = 1`) and homopolymer-compressed scoring (`hpc_scoring_on = 1`), and accepts much
  less divergence between overlapping reads (`assemble_ovlp_divergence` 0.03 instead of 0.10,
  `repeat_graph_ovlp_divergence` 0.03 instead of 0.08, `read_align_ovlp_divergence` 0.10 instead of 0.25).
  Both use `kmer_size = 17`, so the memory floor below is the same. Flye's manual does not compare the two
  modes on the same reads, and ARVA does not claim that one gives a better assembly of reads with < 3 % error;
  the choice is the user's. To compare, run both on the same reads (one job each) and compare the assemblies
  with QUAST or the comparison view.
- **Genome size.** Optional in Flye 2.9; when given, Flye logs the coverage it implies and warns below
  5× or above 1,000×, passes it to its disjointig assembler, and uses it with `--asm-coverage` to keep
  only the longest reads for that stage. ARVA offers three sources and records which one was used
  (`genome_size_basis`): the sample's expected genome size (from its read statistics, as in "Assembly
  warnings"), an estimate `round(total read bases ÷ assumed depth)` (half up; needs ARVA statistics
  for every selected file, and the server recomputes it), or a value typed by the user. ARVA never
  assumes a size. The same size is used for the assembly's genome-size warning, with its basis shown.
- **Memory estimate before a run (ARVA's, from Flye's documentation and its source).** Flye documents no
  formula for its memory. **A fixed floor comes first.** At its first stage Flye 2.9.6 counts k-mers in a flat
  array with 4 bits for every possible k-mer, which it allocates and fills with zeros before reading any read:
  4^k ÷ 2 bytes, "in case of k=17, takes 8Gb" (src/sequence/vertex_index.cpp, `KmerCounter::count`;
  `VertexIndex::countKmers` always passes `useFlatCounter = true`). k is `kmer_size = 17` in every
  `asm_*.cfg` Flye 2.9.6 ships for the read types (flye/config/bin_cfg: `asm_raw_reads.cfg`,
  `asm_corrected_reads.cfg`, `asm_hifi.cfg`, `asm_nano_hq.cfg`; only `asm_subasm.cfg` uses 31), and no
  command-line option changes it, so every run needs 8 GiB for that array whatever the reads, and
  `--asm-coverage` does not lower it. Measured for ARVA: Flye 2.9.6 `--nano-raw` on 413 Mb of simulated
  reads with `--genome-size 2800000 --asm-coverage 40` (112 Mb used) peaked at 8787 MB of resident memory
  during "Counting k-mers", and Flye logged "Peak RAM usage: 8 Gb"; on a Mac whose Docker container had
  5.9 GB, Flye was killed for lack of memory with and without `--asm-coverage`. ARVA therefore uses a
  floor of **8.6 GB** (the 8 GiB array plus the overhead measured beside it; `KMER_COUNTER_FLOOR` in
  `arva_tools.flye`). Above the floor, Flye's manual (docs/USAGE.md of Flye 2.9.6, "Flye benchmarks") gives one bacterial figure: *E. coli*, PacBio 50×,
  4.6 Mb, **2 GB** of RAM; the same page ("Reducing RAM consumption") says the disjointig stage is usually the
  memory bottleneck, that `--asm-coverage` limits that stage to the longest reads up to the given coverage
  ("Typically, 40x longest reads is enough"), that all reads are still used in the later stages, and the
  benchmarks of the large human genomes were run "with `--asm-coverage 50`". ARVA's estimate is
  `max(8.6 GB, 2 GB × bases ÷ 230 Mb)`, where *bases* is every read base
  (ARVA read statistics) or, with `--asm-coverage` and a genome size, `min(read bases, asm-coverage × genome
  size)`. Flye takes no memory limit, so the estimate is compared with the memory the container (or computer)
  actually has, as measured (cgroup limit or `MemTotal`; never a profile's share, and no verdict when it cannot be
  read). The verdict is shown in the dialog: "below the floor" when the container has less than the floor
  (the dialog then says that Flye needs about 9 GB inside Docker and cannot run on this computer as configured,
  that `--asm-coverage` does not lower that floor, and offers no `--asm-coverage`), "tight" when the run fits but
  the container has less than the floor plus **1 GB** (`FLOOR_HEADROOM_GB`: ARVA's database, queue, API and worker
  use the same memory, about 1 GB at rest, and the measured peak, 8787 MB, is already above the floor; the dialog
  warns that Flye may still be stopped while counting k-mers), "fits", "may not fit", or no
  estimate without read statistics; when it may not fit only because of the reads, the dialog offers Flye's
  documented way to use less memory (`--asm-coverage 40`, the coverage
  Flye's manual calls typically enough; it requires `--genome-size` and cannot be combined with `--meta`, and it
  is not offered when 40× of the genome size is not below the read bases, since it would then use every read),
  applied only when the user clicks it; the API
  records the estimate with the job (`memory_estimate`) and never changes the request. Example: the 413 Mb of
  filtered reads (≈148× of 2.8 Mb) scale to ≈3.6 GB, and with `--asm-coverage 40` and 2.8 Mb (112 Mb) to
  ≈0.97 GB, but both are below the floor, so the estimate is 8.6 GB either way; in the 5.9 GB container of that
  Mac the verdict is "below the floor" (before the floor ARVA said "fits", and Flye was killed both ways). The
  scaled part is a rough guide, not a measurement: repeats, read error and the later stages also use memory, and
  Flye's figure is for PacBio reads. The floor was confirmed in the source and measured for Flye 2.9.6 only.
- **Monitoring.** The worker reads Flye's stderr every 5 s while it runs. Each `>>>STAGE: <name>` line
  (configure, assembly, consensus, repeat, contigger, polishing — only with iterations > 0 — and
  finalize, confirmed on real runs) is written to the job log and to `AnalysisJob.progress` (stage,
  index, expected stages, elapsed time, live log path), which is committed on every read.
  `GET /jobs/{id}/log?tail=N` (N ≤ 5,000, from the last MiB) returns the live log while it exists and
  the ARVA job log otherwise; it reads only a log inside the job's own results folder.
- **Outputs and checks.** Kept: `assembly.fasta`, `assembly_graph.gfa`, `assembly_info.txt`,
  `flye.log` and `flye.stderr.log`; Flye's stage folders, the read links and `params.json` are removed.
  `assembly_info.txt` is read by column name (contig, length, coverage, circular, repeat, multiplicity,
  alternative group, graph path); every contig of `assembly.fasta` must appear there with the same
  length, or the job fails and nothing is registered. Coverage, circularity and repeat flags go into
  the assembly record as Flye's; multiplicity, alternative group and graph path are kept per contig in
  the job's result summary. From `flye.log` ARVA records the total read length, read N50/N90, the
  minimum overlap Flye chose (when the user set none), the alignment error rates of the consensus and
  polishing stages, Flye's final summary and its coverage warnings. Statistics and heuristic warnings
  are then computed as in "Assembly statistics".
- **Failures.** Flye's own error lines become the job's reason: "No reads above minimum length
  threshold" (reads too short or minimum overlap too high), "No disjointigs/contigs were assembled"
  (too few reads or too little coverage, or a read type that does not match the data), out of memory
  ("Looks like the system ran out of memory", or the process killed by signal 9; the reason names the
  floor above). Each known reason has a code (`flye_out_of_memory`, `flye_no_long_reads`,
  `flye_nothing_assembled`, `flye_samtools_not_run`, `flye_error`) with the stage and Flye's own error line
  as parameters (`error_detail`), so the interface shows it in its language. The failed run's card shows the
  memory the container had and the run's read type, genome size and `--asm-coverage`, and a "Retry with…"
  button opens "New assembly" with that run's files and settings (and, after a lack of memory, the memory
  explanation). Flye's last log lines go into the job log; partial outputs are removed.
- **`flye-samtools`.** Flye calls a helper named `flye-samtools` (`utils/sam_parser.py`), which
  upstream installs next to `flye` but Debian's package 2.9.3+dfsg2-1 (also in Ubuntu 24.04) does not
  ship. Without it the consensus is empty and Flye stops in the repeat stage ("parse error … empty
  sequence"). When neither `PATH` nor the folder of the `flye` executable provides it, ARVA links
  `flye-samtools` to `samtools` in the job folder for that run, puts it first on Flye's `PATH`, and
  records the link and samtools' version in the job log and result summary; detection reports Flye as
  failed when samtools is missing too.
- **Reproducibility.** Flye's output can depend on the number of threads and, with more than one
  thread, differ between runs; ARVA always records the thread count and the job log says so. Measured
  with Flye 2.9.3 on synthetic genomes: 150 kb chromosome + 15 kb plasmid at two copies (50×): two
  4-thread runs gave the plasmid at 15 kb (multiplicity 2) with different bytes, while 1-thread and
  2-thread runs (each pair byte-identical) and two `--deterministic` 4-thread runs (which only make the
  disjointig stage single-threaded; their bytes still differed) gave a 30 kb circular plasmid dimer at
  about half coverage. Default genome (300 kb, 50×), 2 threads: two runs with identical chromosome
  sequence and the plasmid rotated (same sequence, different start).
- **Recorded result on the synthetic genome.** `make_synthetic_genome.py --ont-depth 30` (default
  layout: 300 kb chromosome with two 5 kb repeat copies, 15 kb plasmid at two copies), `--nano-hq`
  (ARVA's suggestion: mean base error 4.08 %), 2 threads, one polishing iteration: contig 1 300,000 bp,
  circular, 31×; contig 2 15,000 bp, circular, 53×, multiplicity 2; both identical to the reference
  (minimap2 `-x asm5`, NM 0; reverse strand and rotated start), no heuristic warning; two runs gave
  identical bytes; 38 s on 2 threads. Tests: `workflows/tool-adapters/tests/test_real_tools.py` and
  `apps/api/tests/test_flye_api.py` (skipped without Flye).

### SPAdes (short-read assembly)

Implementation: `workflows/tool-adapters/arva_tools/spades.py` (parameters, command, stage plan, log,
contig names, failure reasons), the `spades_assembly` job in `apps/api/app/tasks/tools.py`, and
`apps/api/app/services/short_hybrid.py` (input roles and checks, shared with Unicycler). Verified against
`spades.py --help`, the SPAdes 3.15.5 README and pipeline source (`spades_pipeline/options_parser.py`,
`options_storage.py`, `stages/`, `executors/executor_local.py`) of the Ubuntu 24.04 package
3.15.5+dfsg-7 (the same upstream release as Debian bookworm's), and real runs on the synthetic genome.
Licence GPL-2.0-only (upstream `assembler/LICENSE`: GPL version 2; Debian's copyright file says GPL-2+);
citation: Prjibelski et al., Curr Protoc Bioinformatics 2020;70:e102.

- **Inputs by role.** An R1/R2 pair (`-1`/`-2`, both or neither), unpaired reads (`-s`), or both; one file
  per role, original or filtered copy, recorded as the job's inputs in the order R1, R2, unpaired. Checks
  (HTTP 400, each with its reason): FASTQ only, valid files, not POD5; R1 not marked as mate R2 and the
  reverse; no file whose read headers identify Nanopore or PacBio reads (high or medium confidence); no
  file with a read longer than 1,000 bp in ARVA's statistics (short-read platforms write at most a few
  hundred bases); a pair whose statistics show different read counts is refused (the files must hold the
  same reads in the same order); a sample whose technology is `nanopore` or `pacbio` is refused, `illumina`
  and `hybrid` are accepted, `unknown` needs the user's confirmation. Unknown request fields are refused
  (HTTP 422). The tool missing gives HTTP 409.
- **Command.** `spades.py [--isolate|--careful] [-1 R1 -2 R2] [-s U] -o <job>/spades -t <threads> -m <GB>
  --cov-cutoff <off|auto|x> [-k k1,k2,…]`. The mode is explicit: `--isolate` (default; SPAdes' recommendation
  for high-coverage isolates; implies `--only-assembler`), `--careful` (BayesHammer read correction and the
  mismatch corrector), or no mode flag (SPAdes then warns). SPAdes refuses `--isolate` with `--careful`,
  `--mismatch-correction` or `--only-error-correction`; ARVA's modes are exclusive. Threads are capped by
  `ARVA_TOOL_THREADS`; `-m` defaults to min(250 GB, ARVA's memory cap) — SPAdes' own rule — and may not exceed
  the cap (`ARVA_TOOL_MEMORY_GB`, else the computer's physical memory). `--cov-cutoff` is passed explicitly
  (`off` is SPAdes' default). `-k` is passed only when the user gives k-mer sizes (odd, 1–127, ascending and
  distinct, because SPAdes uses them in the given order); otherwise SPAdes chooses them from the longest
  read (21,33,55 below 150 bp; 21,33,55,77 from 150 bp; 21,33,55,77,99,127 from 250 bp; values not below the
  read length are dropped, also user-given ones, with a log message) and ARVA records the values it ran
  from the `===== K<k> started.` stages of `spades.log`, with SPAdes' own message about them. When the k
  given and the k run differ, the job log says so. Every option used must appear in the installed SPAdes'
  `--help`. Reads are linked as `NN_<name>.fastq[.gz]`: SPAdes recognises reads by their file name, and
  Debian's `/usr/bin/spades.py` is a `/bin/sh` wrapper that expands its arguments unquoted, so ARVA refuses
  paths with white space or `* ? [ ]`.
- **Monitoring.** SPAdes writes its plan to `run_spades.yaml` before the first stage; ARVA reads it (the
  entries whose short name ends in `_finish` announce no start) and follows the `===== <stage> started.`
  lines of SPAdes' console output, so the progress shows SPAdes' own stage list (for example Before start,
  Assembling, K21, K33, K55, K77, Copy files, Breaking scaffolds, Terminate in isolate mode; `--careful`
  adds read error correction — announced twice — and mismatch correction).
- **Outputs.** Kept: `contigs.fasta`, `scaffolds.fasta`, `assembly_graph_with_scaffolds.gfa`, `spades.log`,
  `params.txt` and the console log; the per-k folders, corrected reads and temporary files are removed. The
  user chooses which FASTA is registered as the assembly (contigs by default; scaffolds join contigs with
  runs of N); the choice is recorded.
- **Coverage.** Contig names are `NODE_<n>_length_<bp>_cov_<coverage>`. ARVA parses them, checks that the
  length in each name equals the sequence length (otherwise nothing is registered), and stores the value as
  **k-mer coverage**: how many times, on average, each of the contig's k-mers (largest k) occurs in the
  reads. It is lower than read depth (for reads of length L, read depth ≈ k-mer coverage × L / (L − k + 1),
  and errors lower it further); ARVA does not convert it. SPAdes reports no circularity; ARVA records none.
- **Failures.** From SPAdes' own lines: exceeding `-m` ("mmap(2) failed. Reason: Cannot allocate memory",
  `std::bad_alloc`, "Not enough memory") becomes "SPAdes ran out of memory during the K21 stage (memory
  limit -m 1 GB): …"; a process killed by the operating system (signal 9) is reported as likely memory
  exhaustion before SPAdes' limit; an unsupported read file and a crashed SPAdes program are named with
  their stage. Recorded: on a 6 Mb synthetic genome at 60× with `-m 1`, spades-core stopped in K21 and
  spades.py exited with status 12 (fixture `memory_limit.spades.log`).
- **Recorded result on a small synthetic genome.** `make_synthetic_genome.py --chromosome-length 100000
  --plasmid-length 8000 --repeat-length 2000 --illumina-depth 40` (150 bp pairs), `--isolate`, 2–4
  threads: k 21,33,55,77 chosen by SPAdes; contig 1 98,152 bp (the 2 kb repeat collapsed) at k-mer coverage
  13.4, contig 2 8,077 bp (the 8,000 bp plasmid plus the k − 1 bases its circular graph repeats) at 26.8,
  about twice the chromosome's; two short contigs below 1×; 6 s. Tests:
  `workflows/tool-adapters/tests/test_spades_unicycler.py`, `test_real_tools.py` and
  `apps/api/tests/test_short_hybrid_api.py` (real runs skipped without SPAdes).

### Unicycler (short-read, long-read-only and hybrid assembly)

Implementation: `workflows/tool-adapters/arva_tools/unicycler.py`, the `unicycler_assembly` job in
`apps/api/app/tasks/tools.py`, `apps/api/app/services/short_hybrid.py`. Verified against
`unicycler --help_all`, the Unicycler 0.5.0 README and source (`unicycler.py`, `spades_func.py`, `misc.py`,
`assembly_graph.py`, `assembly_graph_segment.py`, `string_graph.py`, `miniasm_assembly.py`, `blast_func.py`)
of the Ubuntu 24.04 package 0.5.0+dfsg-1 (the same release as Debian bookworm's), and real runs. Licence
GPL-3.0-or-later; citation: Wick, Judd, Gorrie & Holt, PLoS Comput Biol 2017;13(6):e1005595.

- **Modes from the roles.** R1/R2 and/or unpaired short reads only: short-read assembly (SPAdes over a range
  of k-mer sizes; Unicycler keeps the graph scoring best by 1/(c × (d + 2)) for c contigs and d dead ends).
  One long-read file only: long-read-only assembly (Unicycler's built-in miniasm, then Racon polishing).
  Both: short-read-first hybrid assembly. The short-read checks are those of SPAdes; the long-read file must
  not be a mate of a pair, nor have Illumina headers, nor lack any read longer than 1,000 bp; a sample whose
  technology is `illumina` cannot be given long reads, and one whose technology is `nanopore` or `pacbio`
  cannot be given short reads (set `hybrid`). Long-read-only Unicycler is offered as a second strategy; Flye
  remains ARVA's main long-read assembler, and the README's 2022 update recommends long-read-first assembly
  when long reads are deep.
- **Helpers.** Unicycler calls SPAdes (≥ 3.13.1; short reads), Racon (long reads, unless `--no_miniasm`),
  and makeblastdb/tblastn (rotation of completed circular replicons to a dnaA/repA start, unless
  `--no_rotate`, which ARVA does not offer). Debian's package also depends on Pilon, Bowtie 2 and BCFtools,
  which 0.5.0 does not call. ARVA resolves each helper (`ARVA_TOOL_SPADES`, `_RACON`, `_MAKEBLASTDB`,
  `_TBLASTN`, `ARVA_TOOLS_PATH`, `PATH`), passes its path explicitly (`--spades_path`, `--racon_path`,
  `--makeblastdb_path`, `--tblastn_path`), refuses a mode whose helpers are missing (HTTP 409), and records
  Unicycler's own dependency table (program, version, status) from its log.
- **Command.** `unicycler [-1 R1 -2 R2] [-s U] [-l L] -o <job>/unicycler -t <threads> --mode
  <conservative|normal|bold> --keep <0|1> --verbosity 1 --min_fasta_length <n> --linear_seqs <n>`, plus with
  short reads `--depth_filter <x> [--kmers k1,k2,…] --spades_path … --spades_options=-m <GB>`, plus `--racon_path`
  with long reads, plus the BLAST paths. Unicycler runs SPAdes with `--isolate` and `-m 1024` (GB) unless
  `-m` is in `--spades_options`, i.e. with no practical limit; ARVA passes its memory limit so SPAdes keeps
  to it. `--keep` 2 and 3 (alignments, temporary files) are not offered. `--kmers` must be odd, 11–127,
  ascending and distinct (Unicycler's own rule); without it Unicycler chooses a range from the median read
  length, and ARVA records the range and the best k-mer from the log. Every option used must appear in the
  installed Unicycler's `--help_all`.
- **Monitoring.** Each section of `unicycler.log` starts with `<Title> (YYYY-MM-DD HH:MM:SS)`; the console
  copy is coloured (ANSI escapes, removed when parsed). ARVA follows the log and shows the sections seen in
  its validation runs for the mode; sections that only appear when there is work for them (e.g. rotation)
  may be absent, and others are logged as unexpected.
- **Outputs.** Kept: `assembly.fasta`, `assembly.gfa`, `unicycler.log`, the console log and, with `--keep 1`,
  the graphs Unicycler saves at its checkpoints (in `unicycler/`). In short-read and hybrid modes each FASTA
  header is `N length=<bp> depth=<d>x` plus ` circular=true` for a completed circular replicon (one segment
  whose only links join its end to its start); ARVA parses them and checks the lengths. In long-read-only
  mode Unicycler 0.5.0 writes bare names (`>1`): ARVA reads each contig's depth from the GFA's `dp:f` tag and
  its circularity from the GFA's links with Unicycler's own definition (only self-links, same orientation at
  both ends), and records that the values come from the graph. The two sources agree on the short-read
  fixture.
- **Depth.** Relative, not a read depth: in short-read and hybrid modes each segment's depth divided by the
  length-weighted median depth of the 10 longest segments (`AssemblyGraph.normalise_read_depths`); in
  long-read-only mode, divided by the length-weighted median depth of all segments
  (`StringGraph.normalise_read_depths`). The chromosome is therefore near 1.00×.
- **Failures.** Unicycler reports `Error: <message>` with exit status 1. When SPAdes fails inside it,
  Unicycler's message ("SPAdes encountered an error:") omits the reason, which stays in
  `<out>/spades_assembly/spades.log`; ARVA reads that log and reports, e.g., "Unicycler stopped because
  SPAdes failed: SPAdes ran out of memory (memory limit -m 1 GB): …" (recorded on the 6 Mb genome with
  `--spades_options=-m 1`).
- **Recorded results on the small synthetic genome** (as for SPAdes, Nanopore-like reads at 30×,
  `--mode normal`, 2 threads): hybrid — two complete circular replicons, 100,000 bp at 1.00× and 8,000 bp at
  2.04×, 74 s (45–65 s with `--kmers 27,53,77`); short reads only — four contigs (57,998 and 37,998 bp split
  at the repeat, the 8,000 bp plasmid circular at 2.05×, and the 2,002 bp repeat at 1.81×), 43 s; long reads
  only — `>1` 99,996 bp and `>2` 8,000 bp, both circular by the graph, depth 1.00 and 1.84, 26 s.

### QUAST (assembly evaluation)

Implementation: `workflows/tool-adapters/arva_tools/quast.py`, `apps/api/app/services/quast.py`, the
`quast_evaluation` job in `apps/api/app/tasks/tools.py`. Verified against `quast.py --help`, the source of
QUAST 5.2.0 (PyPI sdist) and real runs on assemblies with known differences from the synthetic genome
(`workflows/tool-adapters/tests/fixtures/quast/`).

- **Inputs.** One to ten assemblies of the sample and, optionally, a reference genome chosen among the
  sample's valid FASTA files. Each assembly's contigs file is checked against the SHA-256 recorded when it
  was registered and linked as `assembly_NN.fasta[.gz]` (QUAST reads compression from the extension);
  the label QUAST prints is the assembler, its version and the first 8 characters of the assembly id
  (letters, digits, spaces and `. _ ( ) + -` only, because QUAST splits `--labels` at commas).
- **Command.** `quast.py <assemblies> --output-dir <job>/quast --threads <n> --min-contig <bp> --labels
  <labels> --contig-thresholds 0,1000,5000,10000,25000,50000 --x-for-Nx 90 --no-plots`, and with a
  reference `-r <reference> --min-alignment 65 --min-identity 95.0 --ambiguity-usage one
  --extensive-mis-size 1000 --local-mis-size 200 --scaffold-gap-max-size 10000 --unaligned-part-size 500`
  (QUAST's defaults, passed explicitly). Every option must appear in the installed QUAST's `--help`.
  `--ambiguity-score` is never passed: QUAST switches `--ambiguity-usage` to `all` whenever it is given,
  even at its default 0.99 (`options_parser.py`; observed in a run). `--no-plots` only stops the static
  matplotlib plots, which ARVA does not install; the HTML report draws its own.
- **Minimum contig length.** QUAST's metrics describe only contigs of at least `--min-contig` bp
  (default 500), except `# contigs (>= 0 bp)` and `Total length (>= 0 bp)`, which count every contig. An
  assembly with no such contig is skipped with a warning while QUAST still exits with status 0 when
  another assembly remains, so ARVA refuses such a request and fails a run whose report lacks a label.
- **Definitions compared with ARVA's.** Nx/Lx: identical (contigs sorted by decreasing length; QUAST
  compares in floating point, ARVA in integers). GC: QUAST replaces the IUPAC codes M, K, R, Y, W, S, V,
  B, H, D with N and divides G + C by all bases except N, which equals ARVA's (G + C) ÷ (A + C + G + T);
  files with other characters are refused (exit status 4). `# N's per 100 kbp` counts those IUPAC codes
  as N, so ARVA compares it with its count of N plus other IUPAC codes per 100 kbp of the kept contigs
  (`ambiguous_per_100kb`), not with the `N per 100 kb` of the assembly card (a contig of
  `ACGTRYKMSWN` × 100: QUAST 63,636.36, ARVA ambiguous 63,636.36, ARVA N only 9,090.91).
- **Cross-check.** For each assembly ARVA computes `arva_core.assembly_stats.min_length_summary` on the
  same contigs file at the same minimum length and compares `# contigs`, `Total length`, `Largest
  contig`, N50, L50, N90, L90, GC and N's per 100 kbp (values QUAST prints with two decimals count as
  equal when ARVA's rounds to them) and the two `(>= 0 bp)` rows. Agreement and every difference are
  shown and logged; a difference does not fail the job. On the fixture assemblies all eleven agree.
- **Reference mode.** QUAST aligns with minimap2: its compiled bundled copy when present, else minimap2
  2.19 or later on PATH; failing both it compiles the bundled source (2.24) into its installation during
  the run, which ARVA refuses before starting. The minimap2 executable and version QUAST ran are read
  from `contigs_reports/contigs_report_*.stderr`. Reference-based values count every difference from the
  reference, including real differences between strains. When a contig's best alignment covers more than
  99 % of it (a fixed threshold in `ca_utils/analyze_contigs.py`), QUAST keeps it alone (with any
  alignment scoring at least 0.99 times as well) and skips the rest: a chromosome identical to the
  reference but starting 1,000 bp later (of 300,000) gets a genome fraction of 99.683 %.
- **Outputs and checks.** QUAST's `report.tsv` and `transposed_report.tsv` are read by field name ("-"
  as no value, "X + Y part" as full and partial counts) and must hold the same values; the labels must be
  exactly those requested. Kept and registered: `report.html`, `icarus.html` and `icarus_viewers/*.html`
  (scripts inline, nothing loaded from the network; served with the sandboxing policy and the storage
  shim used for MultiQC, because `report.html` reads `document.cookie`), `report.tsv`,
  `transposed_report.tsv`, `report.txt`, `quast.log`, the misassembly and unaligned reports, and QUAST's
  console output (`quast.console.log`); QUAST's other files stay in the job folder. Progress follows
  QUAST's "Running …" lines (basic statistics, contig analyzer, NA-NGA, genome analyzer, visual
  summaries). Two runs on the same inputs gave identical `report.tsv` files.
- **Environment.** Runs are offline (checked in a network namespace and with a proxy that records any
  connection) with an empty HOME, and write nothing outside the job folder or into QUAST's installation.
  QUAST 5.2.0 leaves `quast.log` empty under CPython 3.13.15 and later 3.13 releases (Logger.removeHandler
  stopped changing the handler list in place, and QUAST's console set-up loop then also removes its file
  handler); the job notes it and the console log is kept. QUAST's locale warning (no `en_US.UTF-8`)
  affects only the dates in the HTML report.

### Polishing (Racon, Medaka, Pilon) and the before/after comparison

A polished assembly is a new assembly record (`kind` "polished") linked to the draft it was made from
(`parent_assembly_id`); the draft is never changed. The strategy follows the reads, not one recipe for
every technology: long reads → Racon or, for Oxford Nanopore reads, Medaka (the user's choice), short reads →
Pilon, both → Racon then Pilon on Racon's result (the Pilon job is queued when Racon's result is registered). Every tool, version, parameter, command, input
checksum and log is recorded per round; the draft's contigs checksum is checked again before the run.
Verified with Racon 1.5.0, minimap2 2.26, Pilon 1.24 (OpenJDK 21), BWA 0.7.17, samtools 1.19.2 and
MUMmer 3.23 (dnadiff 1.3, NUCmer 3.1) on Ubuntu 24.04, using their help texts, Pilon's bytecode (javap) for its
defaults, and real runs on the synthetic genome with a draft carrying 16 known errors
(`scripts/make_polishing_draft.py`: 7 substitutions, 4 insertions of 5 bases, 5 deletions of 7 bases).

- **Racon round.** `minimap2 -x map-ont|map-pb|map-hifi -t <threads> -o roundN.paf <current> <reads>`, then
  `racon -m 3 -x -5 -g -4 -w 500 -q 10 -e 0.3 -t <threads> -u <reads> roundN.paf <current>` (Racon's defaults,
  passed explicitly, or the user's values). `-u` keeps contigs without overlaps, which Racon otherwise drops.
  Racon trims each window's consensus where few reads support it; at contig ends fewer reads align, so each
  round can shorten contigs (8 + 17 bp of a 100 kb circular chromosome in one round on the synthetic data, 5 bp
  more in a second). `--no-trimming` instead left 60 spurious insertions at window boundaries (every 500 bp), so
  ARVA keeps the default and reports the bases lost at each end. One round fixed all 7 substitutions and all
  but 2 indel bases of the known errors; a second fixed the rest.
- **Medaka (one run).** Verified with Medaka 2.1.1 (ARVA's Bioconda lock `docker/conda-locks/medaka/`, spec
  `medaka=2.1.1`, 128 packages for linux-64 with PyTorch 2.3.1 CPU, 124 for linux-aarch64; 1.63 GB installed on
  linux-64) from `medaka_consensus -h`, `medaka tools list_models`, `medaka tools resolve_model -h`, the package's
  README and sources (fixtures in `workflows/tool-adapters/tests/fixtures/medaka/`). ARVA runs
  `medaka_consensus -i <reads> -d draft.fasta -o medaka -m <model> -t <threads> -b <batch size>` in the job's work
  folder on a copy of the draft (medaka writes the draft's `.fai` and `.map-ont.mmi` next to it), with the
  environment's `bin/` first on PATH (the script runs `medaka`, `mini_align`, `python`, `samtools` and `minimap2` by
  name). `-b` is medaka's batch size (default 100, "controls memory use"); `-t` is used for the alignment, the
  inference and the stitching (README: inference "may been seen to use resources equivalent to <threads> + 4" and
  scales poorly beyond 2 threads). Gap filling from the draft (medaka's default) keeps every contig's name; the
  regions copied unpolished are read from `consensus.fasta.gaps_in_draft_coords.bed` (kept as
  `medaka_unpolished_regions.bed`) and the log's "Copying contig '<name>' verbatim from input." lines.
  - *Model.* The README: "it is important to specify the correct inference model, according to the basecaller
    used". Medaka's own mapping from basecaller models to its models is `basecaller_models` in medaka/options.py
    (e.g. `dna_r10.4.1_e8.2_400bps_sup@v5.2.0` → `r1041_e82_400bps_sup_v5.2.0`), the same table
    `medaka tools resolve_model --model <basecaller>:consensus` and automatic selection use. ARVA reads that table
    in the environment's own Python (`python -I`; options.py imports only the standard library) and applies it to
    the basecall model ARVA read from the FASTQ headers (Dorado's `RG:Z:<run id>_<model>_<barcode>` or MinKNOW's
    `basecall_model_version_id=`, the fields medaka's `_model_from_fastq` reads). Without a model in the request
    ARVA uses the mapped model only when the package ships it, and otherwise refuses with the reason (no basecall
    model in the headers, several, a 'fast' model, which medaka does not support, or a model medaka's mapping does
    not know); the user may then choose one of the shipped models. A choice that differs from the mapped model must
    be confirmed (`accept_model_mismatch`) and is noted in the result. `-m` always receives the model shown to the
    user (without `-m`, medaka_consensus would try the same selection and fall back to its default with only a
    warning).
  - *Where the models come from (decision).* Medaka 2.1.1's package ships four model files in `medaka/data/`
    (`<model>_model_pt.tar.gz`): the consensus models `r1041_e82_400bps_sup_v5.2.0` and
    `r1041_e82_400bps_hac_v5.2.0` and their two variant-calling models (options.py: "current models are those
    included in PyPI packages"). Any other model, including the bacterial methylation model behind `--bacteria`,
    is downloaded by medaka on first use (models.resolve_model) from
    `https://github.com/nanoporetech/medaka/raw/master/medaka/data/<file>`, the repository's master branch, with no
    checksum, into the package folder or `~/.medaka/data`. ARVA therefore uses only the shipped consensus models:
    their files are part of a package pinned by its sha256 in the lock, and before every run ARVA checks each file's
    sha256 against conda's record of the package (`conda-meta/medaka-*.json`) and the job's recorded sha256, and
    after the run that the log's "Using model: <file>" is that file. The user's model (sup v5.2.0, Dorado v5.2.0
    basecalling, R10.4.1) is one of them, so a Database Manager entry for models was not needed; older basecaller
    models (medaka maps them to models it would download) are polished with Racon instead. `--bacteria` is not
    offered.
  - *Test.* On the synthetic draft (7 substitutions, 12 indel bases) one run with `r1041_e82_400bps_sup_v5.2.0`
    and 2 threads gave a sequence identical to the reference (dnadiff: 0 SNPs, 0 indels), kept both contig names
    and copied nothing unpolished, in about 20 s; HOME stayed empty (no download). The synthetic reads' errors are
    random, not a basecaller's, so this checks ARVA's handling, not Medaka's accuracy on real data. A draft contig
    no read aligns to is copied verbatim and listed (fixture `run_unrelated`). Medaka's README: it "has been trained
    to correct draft sequences output from the Flye assembler" and "should be used directly on the output of
    Flye"; ARVA notes a draft that is not an unpolished Flye assembly. Medaka runs on the CPU (PyTorch's CPU
    build); in the amd64 image on Apple silicon it runs under Rosetta, which was not measured.
- **Pilon round.** `bwa index`, `bwa mem -t <threads> -K 100000000` per library (the fixed batch size makes the
  result independent of the thread count; the SAM is streamed gzip-compressed and read by samtools), `samtools
  sort` and `index`, then `java -Xmx<heap>g -jar pilon.jar --genome <current> --frags <pairs.bam> [--unpaired
  <se.bam>] --output roundN --outdir <work> --changes --fix <list> --mindepth 0.1 --minmq 0 --minqual 0 --flank 10
  --defaultqual 10 --gapmargin 100000 --mingap 10 --K 47 --chunksize 10000000`. The defaults were read from the
  jar's bytecode: the default fix list is exactly snps, indels, gaps and local; mindepth 0.1 is a fraction of
  the mean coverage with a floor of 5. Debian's launcher would fix the heap at 16 GB, so ARVA runs the jar with
  its own `-Xmx` and removes `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS` and `JDK_JAVA_OPTIONS` from every tool's
  environment. Pilon 1.24 has no thread option. Debian's build prints `Pilon version [COMMIT] [DATE]`; ARVA
  records the version of the Debian package that owns the jar (dpkg) and says so. With "stop after a round
  that changes nothing" (default), the run stops after a round with an empty `.changes` file. One round
  corrected all 16 known errors; its `.changes` file (7 SNPs, 5 insertions of 7 bases, 4 deletions of 5
  bases) and dnadiff agreed exactly, and the result equalled the reference.
- **Depth profiles (4C).** The draft and polished alignments are also summarised with `samtools depth` in 25 bp
  bins for the Genome Explorer's coverage track before the alignments are deleted (see *Genome Explorer*).
- **Direct evidence.** MUMmer dnadiff (`dnadiff -p <prefix> <before> <after>`, run in the work folder on
  file names ARVA chooses, because dnadiff passes its arguments to a shell) between the input and output of
  every round and between the draft and the final result. From `.snps` (show-snps -rlTHC on the one-to-one
  alignments) ARVA counts substituted bases and groups consecutive indel bases into events (insertion rows
  share the reference position, deletion rows the query position); from `.1coords` the draft bases left
  unaligned at each contig end; from `.report` aligned/unaligned bases, breakpoints and one-to-one identity.
  On the known edits dnadiff reported exactly 7 substitutions, 4 insertions (5 bases) and 5 deletions (7
  bases). Differences outside one-to-one alignments are not in `.snps`; they appear as unaligned bases and
  breakpoints. Pilon's own `.changes` list is kept and counted by type (SNP; insertion or deletion relative to
  the input; equal-length multi-base substitution and other replacements as "other"). Without MUMmer, Racon's
  rounds have no direct evidence and are shown as such, never as zero changes.
- **Indirect indicators.** The polishing reads are aligned with the polisher's aligner (`minimap2 -a -x
  <preset>` or `bwa mem -K 100000000`) to the draft and to the result; `samtools stats` gives reads mapped,
  the sum of the NM tags (edit distance: mismatched, inserted and deleted bases) per 100 aligned bases
  ("error rate" in samtools), indels in the alignments per 100 kb aligned and properly paired reads;
  `samtools coverage` the per-contig mean depth. These are labelled indirect: read errors dominate them (3.92 →
  3.90 per 100 bases for the Nanopore-like reads of the test), and the same reads drove the polishing.
- **Polished assembly record.** Contig statistics are ARVA's; per-contig coverage is the mean depth of the
  mapped polishing reads (`mapped_read_depth`, not comparable with Flye's, SPAdes' or Unicycler's values);
  circularity is the draft assembler's flag for the draft contig (Pilon's `_pilon` suffixes removed to match).
  Notes record bases trimmed at contig ends (with a note on circular contigs, which polishers treat as linear),
  draft contigs with no alignment, a round without changes, and an edit distance that rose; for Medaka also the
  regions and contigs copied unpolished, a confirmed model mismatch and a draft that is not an unpolished Flye
  assembly.
- **A change is not proof of a correction:** Racon also changed a Flye draft that
  was already identical to the reference (5 substitutions, 4 indel bases, 36 bases trimmed at the ends); only a
  trusted reference (QUAST with one) can show which version is closer to the truth.

### Imported genomes (public references)

A finished genome FASTA uploaded to a sample (for example an NCBI RefSeq genome downloaded by the user) can be
registered as an assembly (`POST /samples/{id}/assembly/import`, the Assembly tab's *Register a genome FASTA…*), so
it can be annotated, typed, compared, put in a pangenome and in a tree like ARVA's own assemblies. ARVA did not build
it and records that: mode `imported`, assembler `Imported genome`, version = the source as the user states it (not
checked), the FASTA's SHA-256 and no reads. The contig-count heuristic is not evaluated for it (its threshold depends
on the reads an assembly was built from), and it cannot be polished. Imported genomes are the usual way to bring
reference strains into a comparison set; a reference uploaded for QUAST is a separate use of the same kind of file.

**Registered drafts.** When registering, the user may instead declare that the FASTA is a *draft assembled outside
ARVA from this sample's reads* (for example a Flye draft from their own pipeline), stating the assembler and its
version as free text (`draft` in the request; stored as `declared_assembler` and `declared_assembler_version`,
migration `b8e4d2a6f1c3`). ARVA records the declaration as stated and cannot check it. Such a draft, and only such a
registered genome, can be polished with the sample's reads like ARVA's own assemblies (Racon or Medaka with long
reads, Pilon with short reads); its polished versions keep the registered lineage (mode `imported`). The assembly
card, the sample report (HTML and JSON `provenance`) and the polishing summary state that the draft was assembled
outside ARVA as declared by the user. Coverage and circularity stay unknown: ARVA reads neither from a FASTA, so the
polished contigs have no circularity either. Medaka's models were trained on unpolished Flye drafts (medaka's
README); a declared draft is not taken as one, and the run notes that ARVA cannot check it.

### Evidence levels across assembly and polishing

Every value ARVA shows for an assembly belongs to one of these levels, and the interface, reports and exports
keep them apart:

1. **Computed by ARVA** from the files, with stated definitions (`arva_core.assembly_stats`): contig counts and
   lengths, Nx/Lx, GC, the length histogram, cumulative curves. Identical definitions for every assembler.
2. **Reported by the tool**, recorded as the tool wrote it and labelled with its meaning: Flye's mean read depth,
   SPAdes' k-mer coverage, Unicycler's relative depth, the polished assembly's mapped read depth
   (`coverage_kind`), the assemblers' circularity and repeat flags, QUAST's metrics. Values of different kinds
   are never compared; SPAdes' missing circularity is "not reported", never "linear".
3. **Heuristics**: the assembly warnings and ARVA's suggestions (Flye read type, polishing strategy), each
   labelled as such with its rule; the user decides.
4. For polishing, **direct evidence** (what changed in the sequence: dnadiff between versions, Pilon's change
   list) is shown apart from **indirect indicators** (how the same reads align to each version), which read
   errors dominate. A change is not proof of a correction; only a trusted reference (QUAST with one) shows which
   version is closer to the truth.

### Job cancellation, recovery and resume

Implementation: `apps/api/app/tasks/common.py` (job lifecycle), `apps/api/app/services/jobs.py` (cancel, resume,
discard), `workflows/tool-adapters/arva_tools/runner.py` (process groups), `arva_tools/flye.py` (checkpoints).

- **Cancelling a queued job** (`POST /jobs/{id}/cancel`): the job is marked `cancelled` and removed from the task
  queue at once. The job row is locked while this happens, and the worker locks it before starting a job and
  runs only jobs still `pending`, so a job cancelled while a worker picks it up never runs.
- **Cancelling a running job**: the request is recorded (`cancel_requested_at`); the job stays `running` until
  the worker acts. The worker reads the request from the database every 5 s while a tool runs (the monitor
  callback of `run_command`, also with gzip-streamed output such as Filtlong's), before each tool command, every
  100,000 records of ARVA's read statistics and between the files of a server import. It then kills the tool's
  process group with SIGKILL (every tool runs in its own session, so its child processes stop too), rolls back the
  database changes, removes the partial outputs under `results/` and `processed/` exactly as for a failure, and
  records `cancelled` with the log kept (`logs/<job>.log`). Before a job is recorded as completed, the worker
  checks the request once more with the row locked, so a cancellation is either honoured or answered with "already
  finished", never lost. ARVA does not use RQ's stop-job command: it kills the worker's work horse only, so a tool
  in its own process group would keep running, ARVA's clean-up would not run, and it is not available with the
  macOS worker (`SimpleWorker`).
- **A job no worker runs any more** (the worker was killed, e.g. by the system when memory ran out): cancelling it
  ends the record at once when the task queue reports that its task is no longer executing (failed, stopped,
  cancelled, finished or gone); partial outputs are removed and no work folder is kept, because ARVA cannot
  confirm that the tool's processes stopped.
- **Flye resume.** Verified in Flye 2.9.3's source (`flye/main.py`) and with real runs. Flye writes
  `params.json` in its output folder before each stage, naming the stage it starts; `--resume` reruns that
  stage after checking only that the previous stage's output files exist, and it does not check that the reads,
  options or version match the first run. The stage folders are found from `--out-dir`, so a moved folder
  resumes. Its polishing stage appends to `40-polishing/bubbles_<n>.fasta` (`polishing/bubbles.py` opens it
  with mode "a"): on the default synthetic genome (2 threads), a run killed 2 s into polishing and resumed gave a
  30,000 bp plasmid where the uninterrupted run gives 15,000 bp, without any error. With the interrupted stage's
  folder deleted first, runs killed during assembly, consensus, repeat and polishing, moved to another folder
  and resumed gave `assembly.fasta`, `assembly_info.txt` and `assembly_graph.gfa` byte-identical to the
  uninterrupted run. ARVA therefore:
  - keeps Flye's work folder (in `checkpoints/`, outside the results) only when the run was cancelled, reached
    the time limit or was killed from outside (a negative exit status or 137, or Flye's "ran out of memory"
    message) after a stage beyond configure had completed, and deletes the interrupted stage's folder; when Flye
    stopped with an error of its own, resuming with the same reads and options would repeat it, so nothing is
    kept and the log says why;
  - resumes in a new job (`POST /jobs/{id}/resume`) with the original job's reads, parameters and thread count,
    only with the Flye version that wrote the folder and only when the installed Flye's `--help` lists
    `--resume`; the new job moves the folder into its own results, runs the original command plus `--resume`,
    records the run it continued and the stages completed there, and counts each stage once in the
    progress and in its summary of Flye's log (Flye appends the resumed run to the same `flye.log`);
  - deletes a kept folder on request (`DELETE /jobs/{id}/checkpoint`).
  Resuming is not offered for SPAdes (`--continue`, `--restart-from`) or Unicycler: not validated in ARVA.

### Batch QC (project)

`POST /projects/{id}/analyses/batch` runs ARVA's read statistics, SeqKit and/or FastQC on the files of every
sample (or of the chosen samples). With `dry_run` (the default) it returns the plan only: for every file and
analysis either `run` or the reason no job is created, checked in this order — a derived file when only
imported files are chosen, POD5 raw signal, not FASTQ/FASTA, FASTA for FastQC (it needs FASTQ), a file that
failed validation, a queued or running job of the same analysis (always skipped, also with recompute), a
completed result (skipped unless `recompute`). Failed and cancelled jobs are not results. The plan has a
`plan_id`, a hash of the selection and of every planned (analysis, sample, file); creating the jobs requires
it, and if anything changed since the preview the request is refused (409) with the new plan, so exactly the
jobs that were shown are created. The jobs are ordinary per-sample jobs with the same parameters as from the
sample's page (statistics: ARVA's defaults, 50 length bins, no genome size; SeqKit and FastQC: ARVA's thread
setting), created in one transaction with each tool's version detected once.

### Synthetic genome for assembly

`scripts/make_synthetic_genome.py` writes a SYNTHETIC genome with known structure (circular 300 kb
chromosome with two identical 5 kb repeat copies, circular 15 kb plasmid at two copies) and simulated
Nanopore-like and Illumina-like reads; `examples/synthetic-genome/README.md` documents the model,
parameters and realised statistics. Qualities are calibrated by construction: every base is in error
with the probability its own Phred value states. With Flye 2.9.3 (`--nano-hq`) the default data
assemble into the two replicons at their exact lengths, both circular, the plasmid at about twice the
chromosome's coverage.

## Reference databases (Phase 4)

Annotation results depend on the database as much as on the tool, so a database is treated like a tool
version: identified exactly, checked, and recorded on every job that reads it.

- **Catalogue facts** (`apps/api/app/services/database_catalogue.py`) are copied from the official source
  and dated: for Bakta database 6.0, Zenodo record 14916843 (file names, byte sizes, MD5s, licence
  `cc-by-4.0`, publication date 2025-02-24, versions of the external databases it was built from), the
  same MD5s in Bakta's README and in the record's `db-versions.json` (which also gives Bakta 1.11 as the
  oldest compatible software), and Bakta 1.12.2's source (`bakta/db.py`) for the folder layout and the
  checks. The unpacked sizes are the README's approximate "3.9 Gb" and "84 Gb"; ARVA reserves them read as
  GiB (the larger reading) and records the real size after unpacking. Since part 5B the other kinds
  (AMRFinderPlus, GTDB-Tk, skani, sylph, Mash, Kraken 2, CheckM2, BUSCO, PlasmidFinder, MOB-suite, VFDB, geNomad,
  InterProScan, spa types, reference genome collections) have their own recognition and versioning rules, each
  cited in [databases/README.md](../databases/README.md); a version their files do not state is declared by the
  user and recorded as declared, never guessed.
- **Identity of a download**: the archive's MD5 must equal the published one before anything is unpacked.
  MD5 is what the publisher provides; it detects transfer errors and a different file, but is not
  collision-resistant, so ARVA also downloads only from the record's URL over HTTPS.
- **Validity of the folder**: Bakta's own check, re-implemented from `bakta/db.py`: `version.json` with
  `date`, `major`, `minor` and `type`; schema `major` 6 (the schema Bakta 1.12.2 requires); every
  required file (`bakta.db`, the HMM, Infernal and Diamond files, `oric.fna`, `orit.fna`, `rfam-go.tsv`,
  plus `psc.dmnd` for full or `pscc.dmnd` for light). A download must also contain the catalogue's exact
  version and type.
- **Integrity later**: ARVA records the path, size and SHA-256 of every file (the manifest) and a content
  checksum, `sha256:` over the canonical JSON of that manifest. *Verify* recomputes it: a changed or
  missing file marks the database failed; added files are reported but do not change the recorded
  database. A registered folder gets its manifest when it is registered; there is no published checksum
  for an unpacked folder, so that manifest proves only that the folder has not changed since, not that it
  equals the publisher's release.
- **Provenance on jobs**: a job that reads a database stores its catalogue key, name, version and content
  checksum (`analysis_jobs.database_key`, `database_name`, `database_version`, `database_checksum`) and a
  link that is cleared, not cascaded, when the database is deleted, so the record of what was used
  survives. A database cannot be deleted while a queued or running job uses it.
- **AMRFinderPlus data**: Bakta's AMR expert system reads `amrfinderplus-db/latest`. The light 6.0
  archive contains release 2024-12-18.1 (database format 4.0.1), the one its `version.json` lists; ARVA
  records the release and format found there. Bakta's installer would replace it with NCBI's current
  release (`amrfinder_update --force_update`); ARVA does not, so results stay tied to the release the
  database was built with. Updating it would be a separate, recorded step.

## Genome annotation (Phase 4B)

Annotation is **prediction**: gene calls come from models, and names from similarity to sequences whose functions
were themselves mostly inferred. ARVA runs the annotator, records exactly what it ran and what it did not, and
shows the annotator's own calls; it never adds, renames or "improves" a function. A CDS the annotator calls
*hypothetical protein* stays hypothetical.

**Input.** One assembly of the sample, chosen from its lineage (a draft or an assembly polished from it). ARVA
copies its contigs into the job as `input/genome.fna` without FASTA descriptions (Bakta reads completeness,
topology and replicon type from words in descriptions, which ARVA does not want to depend on), records the copy's
SHA-256 and the contigs file's checksum, and for Prokka can rename the contigs `contig_1`, `contig_2`, … (kept as a
mapping) when names exceed the 37 characters Prokka accepts. The worker refuses to run when the contigs file no
longer has the checksum recorded when the job was created. When the contig names or descriptions say SYNTHETIC (ARVA's test data), the dialog, the result and the
reports say that the results describe the tools on test data, not an organism.

### Bakta

Bakta 1.12.2 (Bioconda, in its own pinned environment with every program it runs) with a database from the Database
Manager, whose status and content checksum ARVA re-checks, together with Bakta's folder check, when the job starts.

- **Dependencies and skipped steps.** At start-up Bakta checks a program for each step that will run
  (`bakta/utils.py`, `test_dependencies`) and exits when one is missing, fails or is older than it requires. ARVA
  runs the same checks first, reading each version the way Bakta does (its regular expression on the program's
  combined standard output and error), and passes Bakta's own `--skip-*` option for each step that cannot run:

  | Step | Program (minimum, from Bakta 1.12.2's source) |
  |---|---|
  | tRNA | tRNAscan-SE 2.0.12 |
  | tmRNA | Aragorn 1.2.41 |
  | rRNA, ncRNA genes, ncRNA regions | Infernal (cmscan) 1.1.5 |
  | CRISPR arrays | PILER-CR 1.6 (Debian's 1.06 reads as 1.6) |
  | CDS | Pyrodigal 3.7.0, AMRFinderPlus 4.2.7 (and its database in `<db>/amrfinderplus-db/latest`), PyHMMER 0.12.0, DIAMOND 2.2.0 |
  | sORF | PyHMMER 0.12.0, DIAMOND 2.2.0 |
  | oriC/oriV/oriT | BLAST+ (blastn) 2.17.0 |
  | circular plot | pyCirclize 1.7.0 |

  Pseudogene detection needs the CDS step and the full database (Bakta skips it with the light one). The job
  records, per step, whether it ran and why not (program missing, too old, failing, needs CDS, light database, or
  switched off), and the interface and reports show a step that did not run as *not searched*, never as 0. The
  skip options are part of the confirmed request: if the programs change between the preview and the start, the
  request is refused (409) and the plan is shown again; the worker repeats the check and fails the job rather than
  running with other skips than the ones confirmed.
- **PILER-CR.** When PILER-CR fails during the run, Bakta prints `WARNING: PILER-CR crashed (error code=N). No
  CRISPR arrays will be reported!` and continues (`features/crispr.py`). ARVA therefore runs PILER-CR on a short
  random test sequence before each run, skips the CRISPR step when it fails, and marks the step *failed* (not 0
  arrays) when the warning appears in a run. Ubuntu 24.04's `pilercr 1.06+dfsg-5` passes Bakta's version check but
  crashes (SIGSEGV) on every non-empty input; Bioconda's `piler-cr 1.06` in Bakta's environment passes the test.
- **AMRFinderPlus data for the CDS step.** Bakta's AMR expert system runs `amrfinder --database
  <db>/amrfinderplus-db/latest --protein ... --plus` and stops the run when amrfinder fails
  (`bakta/expert/amrfinder.py`); Bakta's start-up check only looks for "No valid AMRFinder database found". The
  light database 6.0 ships AMRFinderPlus data 2024-12-18.1 (format 4.0.1), which AMRFinderPlus 4.2.7 refuses
  ("Software requires database version at least 2025-09-22.2"). ARVA checks the copy with `amrfinder
  --database_version` (the AMRFinderPlus of Bakta's environment); when it is refused and an AMRFinderPlus database
  ARVA installed is read, Bakta reads its database through a view made in the job's temporary folder: a link to
  every entry of the Bakta database except `amrfinderplus-db`, and `amrfinderplus-db/<version>` linking to the
  AMRFinderPlus database with `latest` → `<version>`. Neither database changes; the job records the Bakta database
  and the AMRFinderPlus database used (name, version, checksum, path) and why. Without one, the CDS step is
  skipped (status `database_refused`) and the dialog says how to fix it.
- **Memory of the protein search (DIAMOND).** Bakta 1.12.2 runs DIAMOND itself with `--block-size 3`
  (`bakta/psc.py`, `pscc.py`, `features/s_orf.py`) and has no option to change it. DIAMOND processes the reference in
  blocks of up to that many billion letters (DIAMOND wiki, "3. Command line options"), so one search needs memory for
  one block: the whole database when it has fewer than 3 billion letters. Before a run ARVA reads the letters of each
  `.dmnd` file Bakta searches from its header (`psc.dmnd` of the full database, `pscc.dmnd`, `sorf.dmnd`,
  `expert-protein-sequences.dmnd`), takes the largest block and multiplies it by 2.41 bytes per letter, a factor ARVA
  measured, not a documented one: DIAMOND 2.2.8 with Bakta's exact pscc arguments on the light database 6.0
  (1,245,018,838 letters) and the 2,646 proteins of *S. aureus* N315 peaked at 2.93 GB of resident memory with 2 and
  with 4 threads. The estimate (light 6.0: about 2.8 GB; a full block of 3 billion letters: about 6.7 GB, in GB of
  1024³ bytes) is compared with the memory the container has: *fits* (with 1 GB to spare for Bakta itself, an
  allowance), *tight*, or *may not fit*; on the user's 8 GB Mac (Docker with 5.9 GB) the light database ran and the
  full one had DIAMOND killed, as the estimate says. When it may not fit, the dialog offers the light database (with
  its own estimate) and, on a Mac where ARVA.app has "Bakta for this Mac", running the same Bakta release natively,
  where macOS compresses and swaps memory (docs/plan-flye-nativo.md, "Bakta nativo"). A native run is recorded as
  such (platform, build, lock and package checksums, the Mac's programs) and its steps are checked again with the
  Mac's programs before it starts.
- **Options.** Always passed: `--db`, `--output`, `--prefix annotation`, `--tmp-dir` (inside the job folder),
  `--threads`, `--min-contig-length`, `--translation-table` (11, 4 or 25, the tables Bakta offers),
  `--locus-tag` (suggested from the sample code, editable; 3–12 capital letters and digits, starting with a
  letter) and `--locus-tag-increment 1`. When given: `--genus`, `--species`, `--strain` (letters, digits and a few
  punctuation marks). `--complete` only after the user confirms that every sequence is a complete replicon; ARVA
  suggests it only when the assembler reported every contig circular, and explains that Bakta then treats every
  sequence as circular and types it by length (≥ 2.8 Mb chromosome, < 112 kb plasmid). `--keep-contig-headers`
  when the user keeps the contig names; otherwise Bakta names them `contig_1`, … and keeps the originals in its
  JSON, which ARVA shows next to them. The circular plot (pyCirclize) is drawn offline; `--skip-plot` is used when
  pyCirclize is missing or the user does not want it. `--gram` only sets metadata in 1.12.2, so ARVA does not pass
  it. Each option is checked against the installed Bakta's `--help` before the command is built.
- **Outputs read.** Bakta's JSON (`annotation.json`) is the source of the features; its GFF3, GenBank, EMBL,
  FASTA, TSV, inference and hypotheticals files are kept unchanged for download. Bakta's own statistics (for
  example its *coding ratio*, which counts the bases of every feature including gaps) are shown as Bakta's. For
  CDS Bakta's GFF3 writes `ab initio prediction:Pyrodigal:3.5` whatever Pyrodigal version ran; ARVA records the
  version its check found.
- **Light database.** With the light database Bakta skips the exact-sequence lookup (UPS/IPS) and pseudogene
  detection, and CDS get only the annotations of UniRef50 clusters (PSCC) (Bakta README, "Database"); expect fewer
  specific names and more hypothetical CDS than with the full database.

### Prokka

Prokka 1.14.6 from the Debian/Ubuntu package (`1.14.6+dfsg-6` validated), offered as the alternative. Its README
states that its author can no longer maintain it and recommends Bakta; ARVA says so in the dialog and the Guide.

- **Database.** Debian keeps Prokka's databases unindexed under `/usr/share/prokka/db` (a Swiss-Prot protein set per
  kingdom built from UniProt release 2023_04, Rfam models, genus sets for *Enterococcus*, *Escherichia* and
  *Staphylococcus*; no HMM, IS or AMR sets). Prokka refuses unindexed databases, so for each run ARVA links the
  package's files into the job's `prokka-db` folder, runs `prokka --dbdir <folder> --setupdb` there and removes the
  folder after the run (about 150 MB while the job runs). The job records the package version and a SHA-256
  manifest checksum of the package's database folder.
- **Options.** Always passed: `--outdir`, `--prefix annotation`, `--dbdir`, `--kingdom Bacteria`, `--gcode`,
  `--locustag`, `--increment 1`, `--cpus`, `--evalue` (default 1e-09, Prokka's), `--coverage` (default 80,
  Prokka's), `--mincontiglen`. When given or chosen: `--genus`, `--species`, `--strain`, `--usegenus`, `--rfam`.
- **Steps.** Prodigal (CDS; metagenome mode for genomes shorter than 100 kb, which ARVA reads from the log), Aragorn
  (tRNA and tmRNA), barrnap (rRNA, when installed), Infernal (`--rfam` only), MinCED (CRISPR, when installed;
  Prokka says nothing when it is absent, so ARVA shows the step as not searched), and BLAST+ against the protein
  sets in Prokka's order (genus set first with `--usegenus`, then Swiss-Prot). Proteins without a hit are labelled
  *hypothetical protein* by Prokka.
- **Outputs read.** Prokka's GFF3 (percent-encoded values decoded; EC numbers from `eC_number`, COG identifiers
  from `db_xref`, evidence from `inference`); its GenBank, FASTA, TSV, TXT and log are kept unchanged.

### Feature index, summary and links

- **Features file, not database rows.** ARVA writes the annotator's features, normalised to one shape (type,
  coordinates, strand, locus tag, gene, product, EC, COG, GO, other cross-references, evidence, pseudo, partial,
  hypothetical), to `features.jsonl` in the job's results. A bacterial genome has a few thousand features; they are
  written once and never edited, are always read per annotation, and belong with the annotator's files they come
  from. Storing them as rows would grow the database by every annotation without any query that needs SQL; the
  API reads the file into memory once (cached by path, modification time and size) for filtering, sorting and
  paging. Queries are bounded (at most 1,000 features per page; detail sequences up to 500,000 characters;
  exports of at most 10,000 selected features).
- **Summary.** Counts per feature type as reported; *hypothetical share* = hypothetical CDS / CDS; *coding
  density* = bases inside at least one CDS (overlaps counted once, features across the origin of a circular
  sequence counted on both sides) / bases of the annotated sequences that are not N. Neither is computed when the
  CDS step did not run. The numbers of CDS with an EC number or a COG, and of features with a GO term or a gene
  symbol, come from the annotator's cross-references.
- **Links.** Cross-references become links only for identifier types whose resolver URL pattern ARVA checked
  (EC → ENZYME, GO → QuickGO, SO → identifiers.org, COG and COG categories → NCBI COG, KEGG orthology → KEGG, Rfam,
  Pfam → InterPro, UniRef, UniParc, UniProtKB, RefSeq proteins → NCBI Protein), and only when the identifier
  matches that database's format. Every other cross-reference is shown as text. The interface renders only
  `https:` links and opens them with `rel="noreferrer noopener"`.
- **Exports.** Downloads of the annotator's files are byte-for-byte. Exports of selected features (or all) are
  cut from the annotator's own files: GFF3 lines with the `##sequence-region` lines they need (no `##FASTA`
  section), GenBank records with only the chosen features (plus each record's source feature), nucleotide or protein FASTA records; the TSV is ARVA's table, with cells that a spreadsheet
  would read as formulas prefixed so they stay text.
- **Escaping.** Product names and every other string from the databases are shown as text in the interface and
  HTML-escaped in reports.

### Validation on this system

Ubuntu 24.04 (4 CPUs), Bakta 1.12.2 from its Bioconda environment with the light database 6.0 and the AMRFinderPlus
database 2026-08-07.1 in place of the database's own copy, and Prokka 1.14.6+dfsg-6:

- **SYNTHETIC annotation genome** (`scripts/make_synthetic_annotation_genome.py`; 18,960 bp with planted random
  ORFs, three back-translated Swiss-Prot proteins, RNA sequences sampled from covariance models with Infernal's
  `cmemit`, a CRISPR-like array and 100 N): every step ran. Bakta called 18 CDS — the three back-translated
  proteins with their names (DNA-3-methyladenine glycosylase II and I, catabolic 3-dehydroquinate dehydratase, from
  UniRef50 clusters) and the planted ORFs as hypothetical proteins — 2 tRNAs, the 5S and 16S rRNA, the RNase P RNA,
  the CRISPR-like array (Bioconda's PILER-CR) and the gap. Prokka found 18 CDS (alkA, tag, quiB and 15 hypothetical
  proteins), a tRNA (`tRNA-SeC(tca)`) and the 16S rRNA. ARVA's dependency versions equal Bakta's own
  `read_tool_output` for every program.
- **A real genome**: *Staphylococcus aureus* N315, NCBI RefSeq NC_002745.2 (chromosome, 2,814,816 bp, FASTA sha256
  `d662a3eaad8dffa393e1686a1cbfe3361b7a959669045824b9ebbc28ba1522f4`) and NC_003140.1 (plasmid pN315, 24,653 bp,
  `68f63fcc7e1c3823bc44edfb11af8aee5e761e1106aef6aece586091eca7ac4d`), downloaded from NCBI E-utilities and deleted
  after the runs. Bakta called **2,592 CDS** (plus 4 sORFs, 63 tRNAs, 1 tmRNA, 16 rRNAs, 0 CRISPR arrays; 179
  hypothetical) in 5 min 12 s with 4 threads. NCBI's RefSeq annotation of the same assembly (GCF_000009645.1,
  annotation GCF_000009645.1-RS_2025_03_15, PGAP 6.9) lists 2,735 CDS, 2,657 of them with a protein and 78
  pseudogenes: Bakta's count is 65 (2.4 %) below PGAP's protein-coding CDS. Bakta detects no pseudogenes with the
  light database and the two pipelines use different gene finders (Pyrodigal; GeneMarkS-2+), so a few percent
  difference is expected; the counts are not a measure of which is right. On the plasmid alone Bakta called 29 CDS
  (RefSeq: 30 CDS, 6 of them pseudogenes; `test_real_bakta_cds_on_ncbi_plasmid_matches_refseq`). Bakta's AMR expert
  system reported 49 AMRFinderPlus hits on the genome.

These results show that the tools ran and that ARVA reads them correctly; the synthetic genome says nothing about
any organism.

## Genome Explorer (Phase 4C)

A linear browser of one annotation (`/explorer/<annotation>`; `arva_core.genome_view`, `app/services/genome_explorer.py`).
Coordinates are 1-based and inclusive, as in GFF3.

- **Sequence.** Every track reads the annotator's own copy of the annotated sequences (its `.fna` file), the sequence
  the features' coordinates refer to; the response names the file and its SHA-256. Prokka's `.fna` equalled the input
  contigs and Bakta's equalled them under Bakta's names (`contig_1`, …), which ARVA maps back to the assembly's
  (both checked by the API tests on the synthetic annotation genome). Sequence slices are bounded to 1,000,000 bp
  and are reverse complemented with the IUPAC codes (M↔K, R↔Y, B↔V, D↔H; W, S, N unchanged) on the minus strand.
- **GC and GC skew.** GC = (G + C) / (A + C + G + T) over unambiguous bases (as in the assembly statistics), GC skew =
  (G − C) / (G + C); a window without unambiguous bases (or without G or C) has no value rather than 0. Windows lie on
  a grid fixed to the start of the sequence: window k covers bases k·step + 1 to k·step + window, so values do not
  change when the view moves; a window running past the end of a sequence is cut there; windows do not wrap around
  the origin of circular sequences. By default the window fits the view (the smallest 1-2-5 size, at least 20 bp,
  giving at most two points per pixel, step = window); the user can choose 100 bp–50 kb windows and a step of the
  window, half, a fifth or a tenth of it (step ≤ window, so no base is skipped). When more windows overlap the view
  than points are asked for, g consecutive windows form one point with the mean, minimum and maximum of their values
  (drawn as a line with a min–max band). At most 2,000,000 windows are computed per request (numpy prefix sums at
  the window boundaries; a 5 Mb sequence with 1 kb windows and a 100 bp step takes about 0.06 s). The sequence's own
  GC is drawn as a reference line. Values were checked against counts made by hand and by the test itself.
- **Read coverage.** Drawn only from an alignment of reads to exactly the annotated contigs. ARVA makes such
  alignments when it polishes: the polishing reads aligned to the draft (`before`) and to the polished result
  (`after`). For every polishing run after 4C, ARVA runs `samtools depth -aa -Q 0 -q 0 -l 0 -G
  UNMAP,SECONDARY,QCFAIL,DUP` on those alignments (every position of every sequence; samtools' defaults written out —
  checked in samtools 1.19.2's usage and by identical output with and without them; deletions are not counted, no
  `-J`, and both reads of a pair count where they overlap, no `-s`), sums the depths in 25 bp bins and keeps them as
  `comparison/{draft,polished}.depth_profile.json` (SHA-256 in the job's summary); the per-base output is deleted.
  The profile's mean per contig equalled `samtools coverage`'s mean depth on the synthetic data (Racon test). The
  explorer uses the polished assembly's own profile, or the draft profile of a run that polished the annotated
  assembly (newest first), checks the file's checksum and the contig's name and length, and states the polishing
  job, aligner, reads and command. Otherwise it says why there is none (no alignment to these contigs; a polishing run
  older than the profiles; a name or length mismatch). Assemblers' per-contig depths are not drawn as a track.
- **Features.** Arrows point 5′→3′: forward strand above the axis, reverse below, features without a strand on the
  axis; overlapping features are packed into up to three lanes per strand. A feature across the origin of a
  circular sequence is drawn as two pieces. Colours group types: protein-coding (CDS, sORF), RNA genes (tRNA, tmRNA,
  rRNA, ncRNA), other elements (ncRNA regions, CRISPR arrays, origins, other) — the first three slots of ARVA's chart
  palette, which pass the dataviz validator's all-pairs checks in both modes (worst colour-vision-deficiency ΔE 10.1
  light / 12.5 dark, normal vision 21.0 / 19.4, all ≥ 3:1 against the chart surface) — and assembly gaps in the
  neutral grey with a hatch. Hypothetical proteins are drawn as outlines and pseudogenes dashed, so these properties
  never rely on colour. The GC-skew track uses the validated blue/red diverging pair. *Intergenic* regions are bases
  outside every CDS, sORF, tRNA, tmRNA, rRNA and ncRNA gene (regulatory regions, CRISPR arrays and origins lie in
  intergenic space).
- **Rendering.** SVG, so glyphs have native hit-testing, focus and accessible titles, text stays crisp and the view
  can be saved as an SVG figure. Only the view is drawn: up to 600 feature pieces one by one; above that, per strand,
  each 2 px column shows the feature group that covers most of its bases (a few hundred rectangles regardless of
  genome size). Intergenic regions are merged per pixel; each line track is one path with at most two points per
  pixel. Track data are requested in power-of-two tiles at least twice the view, aligned to half a tile, so panning
  within a tile and small zooms reuse cached data.
- **Feature detail.** Identifier (locus tag, the annotator's ID, ARVA's number), coordinates in the assembly's and
  the annotator's names, orientation, the predicted function as reported (product, gene, EC, COG, GO; a hypothetical
  protein stays hypothetical), the evidence the annotator reported, cross-reference links as in 4B, the annotator's
  nucleotide and protein sequences (with copy), and the tool, version, database (name, version, checksum) and
  translation table of the run. ARVA also *checks* — never replaces — the sequences: the annotator's gene sequence
  against the genome at the feature's coordinates, and for CDS the annotator's protein against ARVA's translation of
  that genome slice with the translation table given to the annotator (NCBI genetic codes 11, 4 and 25 as
  distributed with Biopython 1.88; a start codon of the table at the first position reads M unless the CDS is
  truncated at its 5′ end; one terminal stop ignored on both sides; pseudogenes and lengths that are not a multiple
  of 3 are not checked). On the synthetic genome every gene sequence of Prokka and Bakta matched the genome, and all
  18 Prokka proteins matched the table-11 translation.
- **Search and exports.** The search box takes a gene name, locus tag, product text or identifier (the feature query
  of 4B over every sequence), a sequence name, or coordinates `contig:start-end` / `contig:position` (either name of
  the sequence; thousands separators `,` `.` or spaces) and `start-end` on the current sequence. A region selected
  on the ruler can be saved as FASTA of either strand (from the annotator's sequence file, header with the
  coordinates, strand, sample and annotation) or as the features that overlap it — whole features, cut from the
  annotator's files (GFF3, FASTA of genes or proteins) or ARVA's TSV; genes marked one by one export the same way.
- **Limits.** The linear view shows one sequence at a time; at most 50,000 features per sequence in the layout. On
  ARVA's synthetic genomes nothing the explorer shows is biology.

## Double helix view

A base-level view of one position of an annotation (`apps/web/src/lib/helix.ts`, `components/explorer/DoubleHelix.tsx`;
data from `GET /annotations/{id}/helix`, `app/services/genome_explorer.helix`).

- **Schematic geometry, cited.** Every pair gets the same rise and twist: 10.5 bp per turn (helical repeat in
  solution 10.4 ± 0.1, Wang 1979, PNAS 76:200, doi:10.1073/pnas.76.1.200; 10.6 ± 0.1, Rhodes & Klug 1980, Nature
  286:573, doi:10.1038/286573a0; 10.5 in the B-DNA column of Rich, Nordheim & Wang 1984, Annu Rev Biochem 53:791),
  0.34 nm per pair and phosphorus atoms 10 Å from the axis (Watson & Crick 1953, Nature 171:737), so 3.57 nm per turn
  and ~2 nm across, drawn to one scale. The second backbone is drawn 360° × 12 / (22 + 12) ≈ 127° round from the
  first, from the groove widths usually quoted for B-DNA, 22 Å and 12 Å (Wing et al. 1980, Nature 287:755); those
  widths depend on how they are measured and only set the drawing's proportions. Turn number, pair in turn and
  distance from the start count from base 1 of the sequence file. Real DNA varies (a B-DNA dodecamer had 9.8 bp
  per turn at its centre, Drew et al. 1981, PNAS 78:2179), bends and supercoils; the view says it is schematic.
- **Pairs.** A·T with two hydrogen bonds and G·C with three (Pauling & Corey 1956, Arch Biochem Biophys 65:164);
  purines (two rings) drawn longer than pyrimidines (one ring). An assembly stores one strand; the other is shown as
  its complement, so no mismatch is ever drawn. N and the other IUPAC codes (Cornish-Bowden 1985) are shown as
  unknown, not paired; lower case (soft-masking) is the same base.
- **Codons.** `arva_core.genome_view.feature_codons` reads a CDS or sORF on its strand from its 5′ end (start on +,
  end on −; across the origin when `edge`), or from its 3′ end for a CDS truncated at its 5′ end (no codon numbers);
  pseudogenes and CDSs truncated at both ends get none; a codon cut by a truncated end is left out. Translation uses
  the annotation's NCBI table (`translate`; a start codon of the table reads M only as codon 1; N or an IUPAC code
  gives X).
- **Polishing changes.** Only the tools' own per-base records: dnadiff's `.snps` (show-snps -rlTHC) of the whole run
  (or of its only round), else Pilon's `.changes` of its only round (later rounds' coordinates differ from the
  draft's). Positions are in the polished sequence when the annotated assembly is a polishing result, in the draft
  when it was polished later; for an alignment in reverse orientation the bases are not placed. Differences outside
  dnadiff's one-to-one alignments are not in the record.
- **Context.** AMRFinderPlus, VFDB and mobile-element calls from the assembly's most recent runs (as on the tracks),
  MOB-suite's call for the contig, and read depth as the mean of the depth profile's 25 bp bin that holds the base.

## Circular genome map and annotation charts (Phase 4D)

### Circular map

The Genome Explorer's second view (`apps/web/src/lib/circular.ts`, `components/explorer/CircularMap.tsx`; data from
`GET /annotations/{id}/map`, `app/services/genome_explorer.genome_map`; the report's static copy in
`app/services/circular_svg.py`).

- **Geometry.** Angles run clockwise from 12 o'clock. Each sequence starts at its first base; on one circle of several
  sequences they follow the annotator's order, separated by gaps of 0.02 rad (all gaps together at most a tenth of
  the circle, so hundreds of contigs still leave room for sequence), with the circle's top in the middle of a gap.
  A feature across the origin of a circular sequence (start > end) is two arcs, start..end of its sequence and
  1..end, at both ends of its own sequence's segment; on a circle of one sequence they meet at the top. Every
  sequence is drawn on a circle whatever its topology, which is stated separately (Bakta's, else the assembler's
  flag); on a draft assembly, contigs drawn next to each other are not known to be neighbours.
- **Rings** (outside in): the sequence (alternating shades between sequences, with features that have no strand —
  CRISPR arrays, gaps — drawn on it); genes on strand +; genes on strand −; an optional custom ring (features of one
  type, pseudogenes, or features whose locus tag, ID, gene or product contains a text); read coverage, when an
  alignment to exactly these contigs exists (as in 4C); GC content; GC skew. Rings for antimicrobial resistance,
  virulence factors and mobile genetic elements are listed and disabled with the explanation that the searches come
  in Phase 5; they are never filled from product names. Rings can be switched off; the remaining rings share the space.
- **Genes.** Coloured as in the linear view (protein-coding, RNA genes, other elements: the first three validated
  palette slots; gaps neutral), hypothetical proteins at 40 % opacity of the protein-coding colour. Per ring and kind,
  arcs are widened to at least 0.9 px and arcs of the same sequence closer than 0.6 px are merged into one sector, so
  a genome of thousands of genes is a few hundred sectors; this level of detail is also why a 5 Mb chromosome (about
  2.6 kb per pixel at a 300 px radius) is not drawn gene by gene. Pointing at a ring finds the feature from the
  angle and radius (within 3 px), not from drawn elements.
- **GC content and GC skew.** As defined for the explorer (4C), in windows of one length on every sequence: by
  default the smallest 1-2-5 length (at least 20 bp) giving at most about 1,440 windows around the whole circle
  (720 in the report's figure and for each of several circles side by side); a window at the end of a sequence is
  cut there. GC bars go outward where a window's GC is above the mean GC of the drawn sequences ((G + C) / (A + C +
  G + T) over all their bases) and inward below it, scaled so the largest difference fills half the ring; skew bars
  go outward (blue) where G > C and inward (red) where C > G, scaled to the largest absolute skew (at least 0.05).
  Circles side by side share these scales; the legend states the window, the mean and each full height.
- **Coverage.** The mean read depth of the polishing alignment's 25 bp bins grouped into about the GC window, from 0
  to the largest window mean.
- **Export.** SVG and PNG (3×) of the whole figure, with the legend and a caption (sample, annotator and version,
  database, "features are the annotator's predictions", SYNTHETIC note) inside it. Text in the SVG comes from
  sequence and feature names and is set as text nodes (escaped in the report's figure).

### Annotation charts

`arva_core.annotation_stats`, `GET /annotations/{id}/charts`, shown in the Annotation tab and as numbers in the
reports. All count the annotator's features; a chart whose step did not run (CDS not searched) says so instead of
drawing zeros.

- **Genes** are features of type CDS, sORF, tRNA, tmRNA, rRNA and ncRNA (regulatory ncRNA regions, CRISPR arrays,
  origins and gaps are not genes), as in the explorer's intergenic definition.
- **Features by type** and, per sequence, the same counts.
- **Hypothetical and characterised CDS**, per sequence and in total. *Hypothetical* is the annotator's call: the CDS
  has no function assigned (product "hypothetical protein"). *Characterised* means only that the annotator gave
  another product, transferred from a database match; it is still a prediction.
- **Gene length distribution** by class (characterised CDS, hypothetical CDS, RNA genes, small ORFs). A gene's length
  is the bases it spans (both parts for a gene across the origin). Bins of a 1-2-5 width (at least 10 bp) giving about
  40 bins up to the 99th percentile of the lengths (nearest rank); longer genes go to a last, open bin, so one very
  long gene does not compress the rest. The width can be chosen. Each class's n, minimum, median, mean and maximum are
  given.
- **Gene orientation**: genes per strand of the sequence as written, per type and per sequence. Leading and lagging
  strand are not computed: they need the replication origin and terminus, which ARVA does not locate.
- **Gene density**: genes per window along each sequence, by strand. Windows of a 1-2-5 length giving the longest
  sequence about 100 windows, at least 1 kb (or a chosen length), on a grid from each sequence's first base; a gene
  counts once, in the window that holds its middle base (for an even length, the base before the middle; for a gene
  across the origin, along the gene). The last window of a sequence is shorter when the length is not a multiple of
  the window; it is shown with its length and left out of the min/median/max summary.
- **COG functional categories**: CDS per category letter the annotator reported (`COG:` cross-references with
  letters; a CDS with several letters counts in each), in the order of NCBI's COG 2020 table, with the names from
  that table (`fun-20.tab`, retrieved 2026-10-28 from `https://ftp.ncbi.nih.gov/pub/COG/COG2020/data/fun-20.tab`;
  26 letters, English names shown in both languages). ARVA does not map COG identifiers to categories: Prokka reports
  COG identifiers without categories, so for Prokka the chart states that no categories were reported and how many
  CDS carry an identifier.
- **Palette and form.** Single-series charts use the primary slot; series keep a fixed slot (characterised 1,
  hypothetical 2, RNA genes 3, small ORFs 4; strand + 1, strand − 2, no strand 3), so the common case uses the first
  three validated slots. Every chart has a table view and SVG/PNG export.

### Reports

The sample's HTML report adds, per annotation, the circular map as inline SVG (sequence names escaped), a table of
the sequences (length, GC, topology and who reported it, genes, CDS, hypothetical share), and the charts' numbers:
gene lengths per class with a histogram, gene orientation per type, gene density per sequence (with a chart for the
longest sequence) and the COG categories or the statement that none were reported. When the annotation's features
or sequence file are missing, the report says which figure could not be drawn and why. The JSON report carries the
same numbers (`charts`, and `map` with the window, mean GC, coverage availability and each sequence's length, GC
and topology), without the drawing; the CSV report is unchanged.

### Validation

`scientific-core/tests/test_annotation_stats.py` checks every count against hand-worked values (middle bases across
the origin, open last bins, shorter last windows, strand and COG counts); `apps/api/tests/test_annotation_charts_api.py`
checks the numbers on Prokka's real output for the synthetic genome (18 CDS, 3 characterised, 15 hypothetical; 13
genes on strand +, 7 on −; COG identifiers but no categories) and the report's figure, tables and escaping;
`test_genome_explorer_api.py` checks the map's windows against counts of the bases, the mean GC and the coverage
windows; `apps/web/src/test/circular.test.tsx` checks the ring geometry (angles, arc flags, whole rings, features
across the origin, merging, hit-testing, scales, ticks) and the chart helpers. On ARVA's synthetic genomes these
figures describe the tools, not biology.

## MLST (Phase 5C1)

MLST (Maiden et al. 1998) names an isolate by the alleles of a few housekeeping loci and the sequence type (ST) of
their combination. ARVA runs mlst 2.35.0 (Seemann, https://github.com/tseemann/mlst) on one assembly of the
sample's lineage (draft or polished), written as `input/genome.fna` without FASTA descriptions, with the PubMLST
schemes bundled in mlst's package. What mlst does was read in its source (`bin/mlst`, `perl5/MLST/Scheme.pm`) and
README:

- **Search**: `any2fasta`, then `blastn -ungapped -dust no -word_size 32 -max_target_seqs 100000 -perc_identity
  <minid> -evalue 1E-20` against every allele of every scheme. A hit counts when identical bases / allele length ≥
  `--mincov` (%). Full length and 100 % identity: exact allele `n`; full length otherwise: `~n` (novel); shorter:
  `n?` (partial); none: `-`; several exact alleles: `n,m`. The `n` of `~n` and `n?` is the first such hit in BLAST's
  output, not necessarily the closest allele (a fixture shows a partial `gmk(725?)` for a gene cut inside allele 1).
  Because the search is ungapped, an allele with an insertion or deletion is at best partial.
- **Scheme and ST**: each scheme scores int(90 × (exact + 0.7 novel + 0.5 partial) / loci) + 10 when the exact
  combination is in its profile file (an ST); the best scheme is reported when its score reaches `--minscore`
  (default 50, an *ad hoc* value according to the README). With equal best scores mlst reports one of them in Perl's
  hash order and prints `WARNING: a(ST)==b(ST) score=n`; ARVA turns that line into the *tied schemes* warning. With
  `--scheme`, mlst sets the minimum score to 0 and ignores `--exclude`; ARVA then passes `--minscore 0` and no
  `--exclude`, so the recorded options are those applied. mlst excludes `ecoli`, `abaumannii`, `vcholerae_2` and
  `senterica_achtman_2` by default; ARVA passes that list explicitly (the user may clear it).
- **Clonal complex**: mlst ignores the profile file's `clonal_complex`/`CC` columns; ARVA reads the column for the
  reported ST when the scheme has one (e.g. `ecoli_achtman_4`: ST10 → "ST10 Cplx") and otherwise shows "not
  available from the scheme" (e.g. `saureus` has no such column).
- **Recorded**: tool path and version; every option and mlst's defaults as its `--help` states them; the bundled
  database's name, download date (the schemes' `<scheme>_info.json`), `db/VERSION.txt`, BLAST index date and the
  SHA-256 over every file (checked again before the run); input and output SHA-256; mlst's log, including the exact
  `blastn` command it ran and the other schemes with exact allele matches.
- **Warnings (ARVA's)**: no scheme; novel, partial, missing, several or null (`0`) alleles by locus; ST not
  assigned; tied schemes; a chosen (not detected) scheme; a scheme updated after 31 December 2024 (PubMLST's terms);
  SYNTHETIC input. mlst's STATUS (PERFECT, NOVEL, NONE, MIXED, MISSING, BAD, OK — the last three marked unstable in
  its README) and score are shown as mlst's.

Validation on this system (real mlst 2.35.0, BLAST+ 2.16.0): NC_007795.1 (S. aureus NCTC 8325) → saureus ST8,
PERFECT, score 100; NC_000913.3 (E. coli K-12 MG1655) → ecoli_achtman_4 ST10 (Achtman), and ST262 with
`--scheme ecoli` (Pasteur); ARVA's SYNTHETIC genome → no scheme. Derived test inputs (documented in
`workflows/tool-adapters/tests/fixtures/mlst/README.md`) show the novel, partial, missing and several-allele calls
and a tie between saureus and ecoli_achtman_4 in a two-genome mixture. The genomes were downloaded from NCBI with
their accessions and checksums recorded and deleted after the runs.

## Species identification (Phase 5C2)

ARVA identifies the species of one assembly of the sample's lineage (draft or polished, written as
`input/genome.fna` without FASTA descriptions) by comparing it with a database registered in the Database Manager,
and reads the ranked hits with fixed, cited rules. It names a species only when the evidence supports it. Every
option is passed explicitly and recorded with the tool, its version and path, the database (kind, version, how the
version is known, checksum when computed, path), the SHA-256 of every reference genome read, the input's and outputs'
SHA-256, the commands and the logs.

### Methods

- **FastANI 1.34** (Jain et al. 2018) against a reference genome collection (NCBI Datasets package, FastANI list or
  FASTA folder): `fastANI -q <genome> --rl <list> -o fastani.tsv -t <threads> -k 16 --fragLen 3000 --minFraction
  0.2 --maxRatioDiff 10.0` (every value is FastANI's own default, from its `--help`). FastANI cuts the query into
  3 kb fragments, maps them with MashMap's MinHash mapping and averages the identity of reciprocal mappings; its
  output (README) is query, reference, ANI, bidirectional fragment mappings and total query fragments. ARVA's
  aligned fraction is mappings / total fragments. "No ANI output is reported for a genome pair if ANI value is much
  below 80%" (README), so a genome with no close reference gives an empty file.
- **skani 0.4.0** (Shaw & Yu 2023) against the same collections: `skani dist -q <genome> --rl <list> -o skani.tsv -t
  <threads> -c 125 -m 1000 -s 80 --min-af 15` (its defaults, from `--help`). skani estimates ANI from sparse chains
  of sampled k-mers and reports the aligned fraction of both genomes (percent); ARVA uses the smaller of the two.
  Its learned ANI model is on by default (for c ≥ 70 and ≥ 150,000 aligned bases); ARVA records when skani's log
  says it was used. Pairs below about 80 % identity are screened out (`-s 80`) and a pair is reported only when one
  genome has more than 15 % aligned.
- **Mash 2.3** (Ondov et al. 2016) against a registered sketch file (.msh, e.g. RefSeq): `mash info -H` and `mash
  info -t` record the sketch's k-mer size, sketch size, seed and each sketch's first header, then `mash dist -p
  <threads> <sketch> <genome>`. With a sketch as reference, `-k` is refused ("inherited from the sketch"), so ARVA
  passes only `-p`. The distance estimates a k-mer mutation rate (Mash documentation, *Distance Estimation*); it is
  not ANI, and ARVA ranks the sketches by distance (references sharing no hash are not a hit) without a species
  call. The organism is read from each sketch's first FASTA header (ARVA's reading).
- **sylph 1.0.0** (Shaw & Yu 2025) against a registered .syldb: `sylph inspect` gives the database's c and k, then
  `sylph profile <db> -r <genome> -o sylph.tsv -t <threads> -m 95 -M 10 --min-contain 7 --min-count-correct 3 -c <c>
  -k <k>`. The assembly is passed with `-r`, as reads; on an assembly every k-mer is seen about once, so sylph cannot
  estimate coverage (Eff_lambda LOW) and its coverage adjustment does not apply — in ARVA's runs a reference sharing
  10 % of its k-mers got Adjusted_ANI 100.00 with Naive_ANI 92.80. ARVA therefore reads **Naive_ANI** and uses the
  containment index (shared / sampled k-mers of the reference) as the aligned-fraction analogue (ARVA's choice).
- **GTDB-Tk 2.8.0** (Chaumeil et al. 2022) against registered GTDB reference data (release R232, the only one 2.8.0
  accepts): `gtdbtk classify_wf --genome_dir input --out_dir gtdbtk --extension fna --prefix gtdbtk --cpus <threads>
  --pplacer_cpus 1 --min_af 0.5 --min_perc_aa 10 --tmpdir tmp` with GTDBTK_DATA_PATH. ARVA reads
  `classify/gtdbtk.bac120.summary.tsv` (and `ar53`) as laid out in GTDB-Tk's source and reports GTDB-Tk's own call
  (s__ filled: species; empty: no species within GTDB's radius). GTDB-Tk's documentation (2.8.0, *Hardware
  requirements*) gives about 140 GB of memory for bacteria (950 GB with `--full_tree`, never used), about 100 GB for
  archaea and about 100 GB of disk: ARVA refuses to start it when the performance profile's memory for a run is
  below 140 GB, and never runs it silently. One pplacer thread because the documentation notes that memory varies
  with the number of pplacer threads.

### ARVA's reading and its thresholds

`arva_core.species.interpret` reads the hits of FastANI, skani and sylph the same way:

| Threshold | Value | Source |
|---|---|---|
| Species boundary | 95 % ANI | Jain C. et al. (2018) Nat Commun 9:5114, doi:10.1038/s41467-018-07641-9: 99.8 % of 8 billion genome pairs conform to >95 % intra-species and <83 % inter-species ANI |
| Minimum aligned fraction | 0.5 | GTDB-Tk 2.8.0 `classify_wf --min_af` default ("minimum alignment fraction to assign genome to a species cluster"); applied by ARVA to every method |
| Margin | 0.5 percentage points | ARVA's heuristic, not a literature value |

- **Same species as X**: the best hit's ANI ≥ boundary + margin, its aligned fraction ≥ 0.5, it has a species name,
  and no other species is ≥ 95 % or within the margin of it.
- **Ambiguous**, with every reason shown: the best ANI within the margin of the boundary; a second species also ≥ 95 %
  (e.g. *E. coli* and *Shigella flexneri*, which a collection cannot separate by ANI); another species within the
  margin; an aligned fraction below 0.5 or unknown; a best reference without a species name.
- **No reference in this collection within the species boundary**: the best ANI is below boundary − margin, or no
  reference was reported. This is not a new species: it may not be in the collection.
- **Caveats always shown**: the result can only be as good as the collection; a single-genus collection cannot
  identify other genera; the closest reference is not type material (when the collection says so); FastANI's 80 %
  floor; sylph on an assembly; Mash's distance is not ANI; GTDB names can differ from NCBI's.

Varghese et al. (2015, Nucleic Acids Res 43:6761, doi:10.1093/nar/gkv657) showed that ANI should be read together
with the alignment fraction; ARVA's 0.5 is GTDB-Tk's default, not a universal threshold.

### Consistency checks

`arva_core.species.consistency` compares the ANI species (only when ARVA's reading is *same species*) with the most
recent MLST result of the same assembly and with the genus/species given for its most recent annotation (Bakta or
Prokka `--genus`/`--species`). The MLST comparison uses the scheme's name only, after PubMLST's habit of genus
initial + epithet (`saureus`, `ecoli_achtman_4`), the genus (`listeria_2`) or a prefix + epithet
(`staphlugdunensis`): *agrees*, *agrees at genus level* or *differs — check*; a scheme can cover related species
(S. argenteus is typed with the saureus scheme) or a complex (`bcc`), so a difference is flagged, never resolved.
No scheme, or no ANI species, is *not comparable*.

### Reference collections from NCBI Datasets

The Database Manager builds a collection for a taxon with the NCBI Datasets v2 API (endpoints and parameters from
its OpenAPI document and requests made on 2026-10-29): `GET /taxonomy/taxon/{name}` (only nodes whose lineage holds
2, Bacteria; "Bacillus" is also a stick-insect genus), `GET /genome/taxon/{tax_id}/dataset_report` with
`filters.assembly_source`, `filters.is_type_material`, `filters.reference_only`, `filters.exclude_atypical`,
`tax_exact_match`, `page_size=1000` and `page_token`, then `POST /genome/download_summary` for NCBI's size estimate.
ARVA shows the number of genomes, species and type-material genomes, NCBI's estimate and its own estimate of the
unpacked FASTA (bases + one newline per 80 bases + ~120 bytes of header per sequence) and the free space, and
downloads (`POST /genome/download`, genomic FASTA only) only after the user confirms that exact list (its
fingerprint is checked again when the download starts). The package is extracted with ARVA's zip checks, every file
compared with `md5sum.txt`, and the accessions must be the confirmed ones; the collection's version is "NCBI
Datasets <download date> #<accession fingerprint>", recorded by ARVA (version source *download*). Only the taxon,
the filters and the accession list are sent: no API key, e-mail or personal data. At most 2,000 genomes.

### Validation on this system

Real FastANI 1.34 and skani 0.4.0 on NCBI RefSeq genomes downloaded with the Datasets API (accessions and SHA-256 in
`workflows/tool-adapters/tests/fixtures/species/README.md`, deleted after the runs): *S. aureus* NCTC 8325
(GCF_000013425.1) against the type strains of *S. aureus* (ATCC 12600), *S. argenteus* (MSHR1132) and
*S. epidermidis* (ATCC 14990): FastANI 99.9171 % (900/940 fragments), 88.85 % and 79.1388 %; skani 99.87 % (AF
97.81/96.46 %) and 89.51 % → *same species as S. aureus*, consistent with mlst's saureus ST8. Without the *S.
aureus* reference → *no reference within the boundary* (best *S. argenteus* 88.85 %). *E. coli* O157:H7 Sakai
against K-12 MG1655 and *S. flexneri* 2a 301: 97.7623 % and 96.9917 % → *ambiguous* (two species above 95 %).
ARVA's SYNTHETIC genome → no reference reported. Mash and sylph were run on three-genome test databases built from
the same genomes (best *S. aureus*: Mash 931/1000 shared hashes; sylph Naive_ANI 99.60) and in the API on synthetic
databases; they were **not** checked against the published RefSeq sketches or GTDB databases (0.25 to 24 GB).
**GTDB-Tk was not validated**: its environment was installed from the lock only to record `--version` and
`classify_wf -h`; no classification ran (no reference data, not enough memory).

## Antimicrobial resistance and virulence genes (Phase 5D1)

ARVA runs AMRFinderPlus 4.2.7 (Feldgarden et al. 2021; NCBI, public domain) on one assembly of the sample's lineage
against a dated release of NCBI's AMRFinderPlus database. What AMRFinderPlus does was read in its `--help`, its
source at tag `amrfinder_v4.2.7` (`amrfinder.cpp`, `amr_report.cpp`, `dna_mutation.cpp`, `amrfinder_index.cpp`,
`amrfinder_update.cpp`, `columns.hpp`) and its wiki (*Running AMRFinderPlus*, *Interpreting results*, *Curated
organisms*):

- **Search.** *Nucleotide*: the contigs as `input/genome.fna` (`--nucleotide`; translated search with tblastn/
  blastx, and blastn for nucleotide point mutations). *Combined*: the contigs, proteins and GFF3 of one of the
  assembly's Bakta or Prokka annotations (`--nucleotide --protein --gff --annotation_format bakta|prokka`), checked
  unchanged by their recorded SHA-256; hits then carry the annotated protein's id. AMRFinderPlus requires the GFF
  whenever both sequence files are given. AMRFinderPlus runs its HMMs on proteins only, so a nucleotide search finds a
  gene only when it reaches the BLAST identity threshold to a reference protein; ARVA warns (`hmm_not_searched`) and
  states the search and the organism in the project report's `amr_tool` column and in a batch step's metrics (on
  N315, the combined search with Bakta adds a chromosomal arsB found by HMM at 81.35 % that the nucleotide search does
  not report). The template "assembled genomes, characterisation" searches the assembly alone (nucleotide), without
  an organism.
- **Options, all passed explicitly**: `--ident_min -1` (the curated identity threshold of each family, 0.9 where
  none is curated; a value overrides them all and ARVA warns), `--coverage_min 0.5`, `--translation_table 11`,
  `--plus` (stress response and virulence genes; on by default), `--threads`, `--database <release folder>`,
  `--blast_bin`/`--hmmer_bin` (the environment's BLAST+ 2.16.0 and HMMER 3.4), `--print_node`, `--output`,
  `--nucleotide_output` (and `--protein_output`), and with an organism `--organism` and `--mutation_all`. The
  defaults stated by the installed `--help` are recorded and compared.
- **Organism.** Point mutations are searched only with `--organism`, and only for the options the database lists
  (`amrfinder --list_organisms`; 32 for release 2026-08-07.1). ARVA proposes one from the assembly's most recent
  species identification that named a species, by the wiki's organism table: the species itself
  (`Staphylococcus aureus` → `Staphylococcus_aureus`), a species its notes name (*K. aerogenes* →
  `Klebsiella_pneumoniae`, *E. hirae* → `Enterococcus_faecium`, *S. mitis* → `Streptococcus_pneumoniae`, *C. coli*
  and *C. jejuni* → `Campylobacter`) or a genus option (*Escherichia* and *Shigella* → `Escherichia`,
  *Salmonella*). Members of the species complexes the table mentions (A. baumannii-calcoaceticus, B. cepacia,
  B. pseudomallei, K. pneumoniae) are not assigned automatically; the dialog names the option and leaves the choice
  to the user. The proposal, its rule and the user's change are recorded with the job.
- **Database.** A release downloaded from NCBI's folder for the software minor version (`database/4.2/<YYYY-MM-
  DD.N>/`) with the files `amrfinder_update` fetches, indexed with `amrfinder_index` (see *Installation*); NCBI
  publishes no checksums, so ARVA records each file's size and SHA-256 and the folder's content checksum. Before a
  run the worker checks the record, its checksum and `amrfinder --database_version` again, and after it that the
  report names the same release. The copy inside a Bakta database is used only when the installed AMRFinderPlus
  accepts it and it holds `AMRProt.fa`, `AMR_CDS.fa` and `AMR.LIB` (Bakta's archives keep only the protein index
  and HMMs, enough for Bakta's protein search but not for AMRFinderPlus's tblastn search of contigs).
- **Results.** Every row of AMRFinderPlus's report is stored as it was written — element symbol and name, scope,
  type (AMR, STRESS, VIRULENCE) and subtype (AMR, POINT, POINT_DISRUPT, BIOCIDE, METAL, …), class and subclass,
  method, target and reference lengths, % coverage and % identity of the closest reference, its accession and name,
  the HMM, the hierarchy node, the contig, coordinates and strand — with the assembly's own contig name and, when
  possible, the annotated feature it belongs to (by protein id in a combined search; otherwise the CDS of the most
  recent annotation that overlaps the hit most on the same strand, with the overlap recorded). ARVA's reading of the
  method: EXACT/ALLELE/BLAST → *complete*; PARTIAL (50–90 % of the reference) → *partial*; PARTIAL_CONTIG_END →
  *partial, at contig end*; INTERNAL_STOP; HMM → *HMM only*; POINT → *point mutation*; StxTyper's operon statuses
  (`--organism Escherichia`) kept as reported. `--mutation_all` lists every curated position checked, so a run that
  found no point mutation is told apart from one that did not search.
- **Wording.** Results are genes and mutations found, never "resistant" or "susceptible" (the wiki: "AMRFinderPlus
  does not predict phenotypic resistance"). A sample without a completed run is *not searched*; a run without rows
  found nothing with those settings and that database; without an organism point mutations are *not searched*;
  without `--plus` stress and virulence genes are *not searched*. ARVA's coded warnings name partial, contig-end,
  internal-stop and HMM-only hits.
- **Views.** The sample's Genomic analysis tab (summary by class, the elements with method badges, point mutations
  apart, the files), the project's presence/absence matrix (found, found only partly, searched and not found, not
  searched; CSV), the AMR and virulence rings of the circular map and an AMR/virulence track in the Genome
  Explorer (hollow for incomplete hits), and the report's section with methods and limitations.

Validation on this system (AMRFinderPlus 4.2.7, database 2026-08-07.1; fixtures in
`workflows/tool-adapters/tests/fixtures/amrfinderplus`): *S. aureus* N315 (accessions and checksums above), with
`--organism Staphylococcus_aureus --plus`, gives 49 elements in 36 s with 4 threads: 21 AMR (mecA, mecR1, mecI,
aadD1, bleO, fosB, tet(38), mepA, five erm(A) and five ant(9)-Ia copies on the chromosome; blaZ, blaR1, blaI on
pN315), 5 stress (cadD, arsR, arsB, arsC, lmrS) and 23 virulence genes (tst, sec3, sel, seo, sep, hlgABC, lukDE,
…), and no point mutation. These match the genes NCBI's RefSeq annotation of N315 names (mecA, erm(A), aadD1, fosB,
tet(38), mepA, blaZ, blaI, blaR1, cadD, tst, sec3, sel, hlgABC). One enterotoxin is INTERNAL_STOP (sen) and two
hits are partial (seu, sasG). A derived input (`derive_inputs.py`: gyrA codon 84 TCA→TTA, the chromosome cut inside
mecA, a stop codon in blaZ; a test construct) gives gyrA_S84L (POINTX), mecA as PARTIAL_CONTIG_ENDX (59.88 %
coverage) and blaZ as INTERNAL_STOP. The combined search with Bakta's proteins and GFF3 of N315 gives 50 elements
(EXACTP/BLASTP for annotated proteins, EXACTX where the annotation lacks the protein, an HMM-only arsB). ARVA's
SYNTHETIC genome gives no element. A constructed release (subsets of the real files; `apps/api/tests/fixtures/
amrfinder_release`) is downloaded from a local stand-in of NCBI's folder, indexed with the real `amrfinder_index`
and searched in the API tests.

## Plasmids, mobile elements and virulence factors (Phase 5D2)

ARVA runs each method on one assembly of the sample's lineage, as its own job (`mobile_elements` for plasmids and
mobile elements, `virulence_screen` for VFDB), with the tool, its version, every result-changing option, the
database (kind, version, how the version is known, checksum, path) or the bundled models (file names and content
checksum), and the SHA-256 of the input contigs and of every output file. Every option is passed explicitly and the
defaults stated by the installed `--help` are recorded and compared with ARVA's. What each tool does was read in its
`--help`, its source and real runs (module docstrings in `workflows/tool-adapters/arva_tools/`).

- **MOB-suite 3.1.9** (Robertson & Nash 2018; Apache-2.0). `mob_recon` assigns each contig to a known plasmid
  cluster (MOB-cluster, by Mash distance to the reference plasmids and BLAST of the contigs) or leaves it as
  'chromosome', reconstructs each plasmid and types it with `mob_typer`: replicon (rep_cluster or Inc type),
  relaxase (MOB family), mating-pair formation (MPF), oriT, predicted mobility (*conjugative*: relaxase and MPF;
  *mobilizable*: relaxase or oriT without MPF; *non-mobilizable*), the nearest reference plasmid and the predicted
  host range. ARVA passes `--database_directory` with every threshold (`--min_length` is the shortest BLAST
  alignment kept, not a contig filter) and stores each contig's call, each plasmid, each biomarker hit and MOB-suite's
  repetitive elements (`mge.report.txt`). 'chromosome' means *not assigned to a plasmid*: a contig that carries a
  replicon or relaxase without being assigned (an integrated plasmid, or a plasmid missing from the database) is
  named in a warning. The host range is a prediction from the reference plasmids and the literature.
- **MOB-suite's database 3.1.8** (Zenodo record 10304948, the one `mob_init` of 3.1.9 downloads; CC BY 4.0) is
  downloaded by the Database Manager over HTTPS and its MD5 compared with Zenodo's. ARVA never runs `mob_init` (it
  downloads with TLS verification turned off and then the latest NCBI taxonomy over plain HTTP): it streams the
  reference plasmids from the verified archive into `makeblastdb -parse_seqids` and `mash sketch -k 21 -s 1000`
  (mob_init's commands), indexes `repetitive.dna.fas`, and builds `taxa.sqlite` with ete3 from a dated NCBI
  taxonomy archive (`taxdmp_YYYY-MM-DD.zip`) that the user confirms; NCBI publishes no checksum for it, so its
  SHA-256 is recorded. The 1.6 GB FASTA of the reference plasmids is kept only on request (mob_recon 3.1.9 searches
  its BLAST index only). The folder is then read-only, and `ARVA_DATABASE.json` records all of this.
- **PlasmidFinder replicons through ABRicate 1.4.0** (Seemann; GPL-2.0) and **VFDB through ABRicate**. ABRicate's
  bundled copies are recorded read-only in the Database Manager (kinds *PlasmidFinder* and *VFDB*, variant
  `abricate`), with the SHA-256 of their files; their version is the day ABRicate's package indexed them
  (`sequences.njs`, 2026-04-03 in 1.4.0), because the files name no PlasmidFinder commit or VFDB release. ARVA never
  runs `abricate-get_db` (it fetches unpinned data, VFDB over plain HTTP). Search: `abricate --datadir <db> --db
  plasmidfinder|vfdb --minid 80 --mincov 80 --threads <n> --nopath` (ABRicate's defaults, passed explicitly; a lower
  threshold is named in a warning). ABRicate runs `blastn -task blastn -dust no -evalue 1E-20 -culling_limit 1`,
  so it is nucleotide similarity only. Each hit keeps its reference coordinates, coverage map, gaps, identity and
  coverage; ARVA reads it as *complete*, *complete with gaps*, *partial* or *partial at a contig end* (within 10 bp
  of the end), and names references found in several partial pieces. A gene split across contigs is reported only
  where each piece reaches `--mincov`. VFDB's download page states no licence for its files: ARVA says so and asks
  for VFDB's citation (Liu B. et al. 2022). A replicon found is not a plasmid call (replicons lie in chromosomes too,
  and small plasmids may carry none); a virulence-factor gene found is not evidence of virulence.
- **IntegronFinder 2.0.6** (Néron et al. 2022; GPL-3.0) with the models it bundles (their content checksum is
  recorded): integron integrases (HMMER), attC sites (Infernal), complete integrons, In0 (integrase without attC)
  and CALIN (attC sites without integrase). ARVA passes `--local-max` (on), `--distance-thresh 4000`,
  `--evalue-attc 1`, `--calin-threshold 2`, `--max-attc-size 200`, `--min-attc-size 40`, the environment's
  cmsearch, hmmsearch and prodigal, and a topology file: contigs the assembler reported circular (Flye, Unicycler)
  are searched as circular, all others as linear.
- **ISEScan 1.7.3** and **geNomad 1.13.0** (database 1.9): adapters and locks are in ARVA, written from their source
  code, but **not validated here**: neither environment (nor geNomad's database) fitted the test machine's disk, so
  their parsers are tested on constructed files only and every run says that the tool was not validated with ARVA.
  ISEScan's partial elements (type p) are named; geNomad's scores are classifier outputs, not proof.
- **Not searched is not none found.** A method that has not run on an assembly is *not searched* in the contig
  table, the project's columns, the circular map and the reports; a run without rows found nothing with those
  settings and that database. A contig's size is never taken as evidence that it is a plasmid.
- **Virulence from two sources.** VFDB hits (ABRicate) and AMRFinderPlus's virulence genes (`--plus`) are shown side
  by side, each row with its source and that source's own method, never merged into one call; a row found by both
  names the other source. A source that did not run (or AMRFinderPlus without `--plus`) is *not searched*. A VFDB hit
  on the region (at least half of the shorter hit) where AMRFinderPlus found a different gene with a higher identity
  is flagged as probably that gene (real N315 case: VFDB lukF-PV at 82.37 % on AMRFinderPlus's lukD at 94.19 %, and
  N315 has no lukS-PV). The project report (CSV `virulence_cross_hits`, JSON `virulence.cross_hits`, HTML) and a batch
  run's consolidated table (`vfdb.cross_hits`) list such a gene apart as a cross-hit with the gene it probably is,
  instead of among the VFDB genes; nothing is dropped.
- **Views.** The sample's Genomic analysis tab (a contig table with MOB-suite's call, replicons, relaxase, mobility,
  PlasmidFinder's replicons with identity and coverage, integrons, IS elements and viruses, and the assembler's
  circularity side by side; each run's calls by category; the virulence card), the project's columns, the circular
  map's VFDB and mobile-element rings (filled when complete, hollow when partial) with MOB-suite's plasmid contigs
  coloured on the sequence ring, VFDB and mobile-element tracks in the Genome Explorer, and the report's sections
  with methods and limitations.

Validation on this system (fixtures and their READMEs in `workflows/tool-adapters/tests/fixtures/abricate`,
`mobsuite`, `integronfinder`): NCBI RefSeq *S. aureus* N315 (NC_002745.2 and NC_003140.1, the genome of the AMR
validation above) and *E. coli* plasmid R388 (NC_028464.1, sha256 of the staged FASTA in the README), plus ARVA's
SYNTHETIC genome; the downloaded genomes were deleted afterwards.

- MOB-suite with database 3.1.8 as ARVA prepared it: pN315 a plasmid (cluster AA409, rep_cluster_1017/1733/2214,
  MOBV, mobilizable, host range genus *Staphylococcus*); the N315 chromosome 'chromosome' although it carries a
  replicon (rep_cluster_1018) and a MOBV relaxase (pUB110 integrated in SCCmec), which ARVA's warning names;
  eight repetitive elements (IS1181, ...). R388: a plasmid (AD768, IncW, MOBF, MPF_T, conjugative).
- PlasmidFinder: rep19, rep5a and rep16 on pN315 and rep22 on the chromosome (the same integrated pUB110).
- VFDB: 86 hits on N315 (59 complete, 14 complete with gaps, 13 partial, e.g. hlb 170–993 of 993, the
  β-haemolysin gene, which a prophage interrupts in N315). A derived input (`derive_inputs.py`, a test construct:
  the chromosome cut 10 % into adsA and halfway into cap8D) gives adsA at a contig start (90.04 % coverage) and no
  cap8D at all at `--mincov 80` (each half covers 50 %), and the two cap8D halves as a split gene at `--mincov 40`:
  the reason for the split-gene warning.
- IntegronFinder: R388's class 1 integron, complete, 29,666–32,156 with two attC sites; none in N315.
- ARVA's SYNTHETIC genome: nothing from any of them (MOB-suite calls both sequences 'chromosome').

## Species-specific typing: Staphylococcus aureus (Phase 5E)

**When it runs.** A typing module declares the taxa it applies to. For the S. aureus module these are the species
*Staphylococcus aureus* (as species identification names it) and the MLST scheme `saureus`. For each assembly ARVA
reads the most recent species identification that named a species and the most recent MLST call with a scheme:
*applicable* when one matches and neither names another taxon; *conflicting* when one matches and the other does
not; *not applicable* when the evidence names another taxon only; *no evidence* when there is none. Only an
applicable module runs without more; otherwise the user must confirm an override, and the result records the
evidence it overrode and carries a warning. Each step (SCCmec, spa, agr) is its own job on the assembly's contigs,
staged with descriptions removed and in upper case; tool, version, every option, the data read (with their
checksums) and the SHA-256 of the input and of every output are recorded.

- **SCCmec: sccmec 1.2.0** (R.A. Petit III; MIT; through camlhmp 1.1.4 and BLAST+ 2.16.0). Two searches against the
  schemas it ships: *targets* (ccr genes ccrA1–4, ccrB1–4, ccrB6, ccrC1–2; mecA, mecI, mecR1, blaZ; IS431, IS1272,
  IS12960D), where a type I–XV is the ccr complex and mec class (the schema's aliases) whose targets are all found,
  with the schema's exclusions; and *regions* (32 reference cassettes), where the subtype is the cassette covered over
  the threshold. ARVA passes the four schema files and the thresholds explicitly (targets: 90 % identity, 80 %
  coverage; regions: 85 % and 83 %, the schemas' own values and the `--help` defaults) and reads sccmec's result
  table, its per-type and per-cassette tables and the targets' BLAST hits (best hit per target). ARVA's reading:
  *typed* (type and subtype), *type only*, *several types*, *mec gene without a type* (mecA found, no type: a novel,
  composite or fragmented cassette) or *not typeable*. sccmec's "mecA" target includes the mecC sequence of type XI
  (FR821779.1), so its mecA + means mecA or mecC. Nomenclature: IWG-SCC (2009).
- **spa: spaTyper 0.3.3** (Sanchez-Herrero & Sullivan; LGPL-3.0 per Bioconda). spaTyper scans each contig, on both
  strands, for exact matches to the repeats of the Ridom file `sparepeats.fasta`, writes the succession of repeat
  numbers (non-adjacent matches joined by "xx") and looks it up in `spatypes.txt`. ARVA passes the two files the user
  downloaded from the Ridom SpaServer and registered (`-r`, `-o`), never lets spaTyper fall back to its own copies
  or download them (the copies in its Bioconda package are deleted at installation), and does not offer `-e` (PCR
  enrichment), whose results spaTyper 0.3.3 writes to standard output only. spaTyper compares the contigs as written
  (a lower-case genome finds no repeat), hence the upper-case staging. ARVA's reading: *typed* (one contig, a known
  t-number), *new repeat succession* (every repeat known, no type has the succession), *gap or unknown repeat*
  ("xx" in the succession), *several contigs* or *no spa repeats*; only *typed* gives a spa type. spa nomenclature:
  Harmsen et al. 2003; Ridom SpaServer policy: non-commercial use, acknowledgement and citation.
- **agr: AgrVATE 1.0.2** (Raghuram et al. 2022; MIT). The agr group is the group of the k-mers
  (`gp1234_all_motifs.fna`) found with blastn at 100 % identity and 100 % query coverage; the number found is the
  match score: 0 is untypeable (nhmmer then looks for a non-canonical agrD), 1–4 is AgrVATE's "low confidence". With
  k-mers of several groups AgrVATE reports the group with the most hits ("multiple"; its README: "the displayed agr
  group is the majority/highest confidence") and types the operon against that group. ARVA reads `<name>-agr_gp.tab`
  (one blastn hit per k-mer and contig; the k-mers are named after their group, so these count hits) and keeps that
  call, shown with "?" and each group's hits and contigs; it reports no group when the two largest counts tie
  (AgrVATE then picks by `sort` order) or the top count is 4 or less (AgrVATE's own stop). Real run: USA300_FPR3757 and
  N315 in one FASTA give agr II, 15 hits on the N315 chromosome and 13 agr-I hits on the USA300 one. The operon is then extracted and its variants called with snippy
  (`--minqual 1 --mincov 2`) against the group's reference GenBank file; AgrVATE keeps the CDS variants that its
  filter does not remove (frameshifts and some other effects). AgrVATE's default extraction is an in-silico PCR with
  `usearch11.0.667_i86linux32`, a 32-bit binary not distributed with it; ARVA runs the documented MUMmer mode (`-m`):
  dnadiff aligns a group-I reference operon (3,482 bp) and samtools extracts the aligned parts. ARVA records the mode
  and reports the share of the reference operon that aligned: on N315 (agr II) two fragments covering 64 %, on
  USA300 (agr I) the whole operon.
- **Summary card.** Beside the three calls: the MLST call (mlst, Phase 5C1), and from the assembly's most recent
  AMRFinderPlus run (Phase 5D1) mecA and mecC, PVL (lukS-PV and lukF-PV), tst, the genes whose AMRFinderPlus name
  contains "staphylococcal enterotoxin" and those named "exfoliative toxin" (database 2026-08-07.1: eta and etb; no
  etd); toxin genes are "not searched" when that run was made without `--plus`. Each part keeps its tool, version and
  job. mecA/mecC is cross-checked between sccmec and AMRFinderPlus (agree, disagree, unavailable). The shorthand is
  built only from determined parts: STn from a `saureus` call; MRSA when mecA or mecC is found (by either tool), MSSA
  only when AMRFinderPlus searched and found neither; the SCCmec type or subtype after MRSA; the spa type; agr I–IV;
  PVL+ when both PVL genes are found complete, PVL- when the `--plus` run found neither. A part whose evidence is
  partial or disputed carries "?" and is listed with the reason (an mlst status other than PERFECT, a type without
  subtype, a disagreement on mecA/mecC, a mec gene found only in part, a low-confidence agr call or one with k-mers of several
  groups, one PVL gene only or
  a partial one). MRSA and MSSA name the genotype, not a susceptibility test.

**Validation.** Real runs on NCBI genomes, downloaded from E-utilities and deleted afterwards (accessions and
checksums in `workflows/tool-adapters/tests/fixtures/{sccmec,spatyper,agrvate}/README.md`):

| Genome | sccmec | spaTyper (Ridom files of 2026-11-02) | AgrVATE (MUMmer mode) | mlst / AMRFinderPlus | Published |
|---|---|---|---|---|---|
| S. aureus N315 (GCF_000009645.1) | II, IIa (cassette 100 % covered) | t002 (26-23-17-34-17-20-17-12-17-16) | agr II, score 15, 0 variants | ST5 / mecA, tst, no PVL | SCCmec II (Ito et al. 1999; Kuroda et al. 2001), ST5; agr II (used as the agr-II prototype, Frontiers in Microbiology 2022, doi:10.3389/fmicb.2022.700894); t002 matches the SpaServer's table, no N315-specific publication checked |
| S. aureus USA300_FPR3757 (GCF_000013465.1) | IV, IVa (94.12 %) | t008 (11-19-12-21-17-34-24-34-22-25) | agr I, score 13, 0 variants | ST8 / mecA, lukS-PV, lukF-PV | ST8, SCCmec IVa, PVL+ (Diep et al. 2006); t008 and agr I are those reported for the USA300 clone |
| ARVA's SYNTHETIC genome | not typeable | no repeats | untypeable | — | untypeable by construction |

The summary card gives "ST8-MRSA-IVa, t008, agr I, PVL+" for USA300 and "ST5-MRSA-IIa, t002, agr II, PVL-" for
N315 from these outputs (API tests replay them). spa typing was also run with CONSTRUCTED Ridom-format files (three
made-up repeats, one made-up type) to test a known type, a new succession, a gap, two contigs and a lower-case genome.

**Limitations.** The schemas, k-mers and reference operons are those shipped with sccmec 1.2.0 and AgrVATE 1.0.2;
subtypes IVe, IVf and IVh are not in sccmec's regions schema. Cassettes or spa regions split across contigs, and
repeats collapsed in short-read assemblies, lower or prevent typing. spa types are as current as the user's Ridom
files. In MUMmer mode AgrVATE may miss frameshifts outside the aligned fragments (its own warning); no agr-defective
genome was tested here. Typing a genome of another species (after an override) gives calls without meaning.

## Comparative genomics (Phase 6A)

**Comparison sets.** A set lists assemblies (any project, polished or not) in an order with a label each. Every job
records the genomes it compared: assembly id, label, sample, contigs SHA-256 (checked again by the worker before the
run) and the SHA-256 of the staged copy (`stage_genome`: names kept, descriptions removed, sequences unchanged).

**ANI.** skani 0.4.0 `skani triangle -l <list> -o <out> -t <threads> -c 125 -m 1000 -s 80 --min-af 15 -E`
(`skani triangle --help`: -E writes sparse rows "in the same form as `skani dist`"; only pairs with aligned fraction
above --min-af; no self rows without --diagonal). FastANI 1.34 `fastANI --ql <list> --rl <list> -o <out> -t -k 16
--fragLen 3000 --minFraction 0.2 --maxRatioDiff 10.0` (each ordered pair and the self pairs). ARVA keeps the values as
reported: a pair a tool did not report is empty, never estimated. The heatmap order is ARVA's average-linkage (UPGMA)
clustering of 100 − ANI (`arva_core.comparative.similarity_order`; unreported pairs at distance 100 and FastANI's two
directions averaged, for the order only). It is **similarity clustering, not a phylogeny**.

**Alignment.** The first genome of the chosen order is the reference; every other genome is aligned to it, and each
genome to the next one. minimap2 2.26: `minimap2 -x asm5|asm10|asm20 -c -t <threads> -o <pair>.paf <reference>
<query>` (presets "for ~0.1/1/5% sequence divergence", usage text; -c gives base-level alignments, so PAF column 10 is
matching bases and column 11 the block length including gaps; identity = column 10 / column 11; the `tp` tag marks
primary alignments). NUCmer 3.1: `nucmer --mumreference|--mum|--maxmatch -b 200 -c 65 -g 90 -l 20 -p pair ref.fna
qry.fna` (defaults from `nucmer -h`, passed explicitly) and `show-coords -rclTH pair.delta` (all alignments, % IDY).
NUCmer and dnadiff build shell strings from their arguments, so they run in a folder holding links named `ref.fna`
and `qry.fna`. Per pair ARVA reports the bases of each genome covered by at least one (primary) block, overlaps counted
once, and the block-length-weighted mean identity.

**Conservation along the reference** (ARVA, `arva_core.comparative.conservation`): windows of at least 1 kb (at most
2,000 per genome); per window, the share of reference bases covered by a primary block and the mean, over those
bases, of the highest identity of a block covering each base.

**Structural differences.** dnadiff 1.3 (`dnadiff -p dnadiff ref.fna qry.fna`) runs NUCmer --maxmatch, delta-filter
-1 and -m and `show-diff -rH` / `-qH` on the M-to-M alignments. Each `.rdiff`/`.qdiff` row is a feature located on
that genome: GAP, DUP, BRK, JMP, INV, SEQ (`show-diff -h`). ARVA classifies the rows exactly as dnadiff's report
counts them (a row inserts max(length, GAP difference) bases when positive: "Insertions"; INV: inversions; JMP:
relocations; SEQ: translocations); on N315 vs Mu50 the recount equals the report (29/40 insertions, 59,724/123,208
bases, 5/8 relocations, 4/2 inversions). Sequence "absent from the other genome" on a genome's side is an insertion in
that genome, i.e. a deletion in the other; the comparison alone does not tell which happened, nor any horizontal
transfer.

**Limits.** ANI and alignment identity measure similarity; they say nothing about ancestry, direction of change or
transfer. Repeats (IS elements, rRNA operons), assembly gaps, collapsed repeats and contig ends produce alignment
breaks that are not rearrangements. minimap2's and NUCmer's identities are computed differently and are not
comparable.

## Genome Region Explorer and Custom Gene Investigation (Phase 6B)

**Finding the homologous region.** In each genome other than the gene's own, the homologue is the best blastp hit
(BLAST+ `-task blastp -seg yes -comp_based_stats 2`, e-value threshold given) of the gene's protein among that
genome's annotated proteins, accepted when its identity and the covered share of both proteins reach the thresholds
(ARVA default 70 % and 70 %, chosen to keep paralogues of a gene family out; lower them to follow the family). When the
gene is not a CDS, the genome is not annotated, or the anchor is a coordinate range, blastn (`-task blastn -dust yes
-strand both`) of the gene's nucleotides against the genome's contigs is used and the best chained match (below) is
taken. BLAST+ rather than DIAMOND: these are a few searches of one protein against a few thousand and a few hundred
proteins all against all, where BLAST's full sensitivity costs seconds (DIAMOND is designed for millions of queries);
minimap2 is designed for long, near-identical sequences and gives no reliable alignment of one divergent gene. Only
the best homologue is drawn; the number of homologues passing the thresholds is reported.

**Neighbourhoods.** Each window is `flank` bp on each side of the homologue, read linearly (a window at a contig end is
clipped and flagged). Features are placed so that the gene of interest starts at 0 and points right (tracks whose
homologue is on the minus strand are read reversed). Homology groups are single-linkage clusters of all-against-all
blastp HSPs among the windows' proteins with at least the given identity over the given share of both proteins
(default 30 % and 50 %); groups found in at least two genomes are coloured (Okabe-Ito, then Tol's muted palette),
others are grey. A colour is shared similarity above the thresholds, not orthology. Bands between neighbouring tracks
are blastn HSPs between the two window sequences (default ≥ 70 % identity, ≥ 100 bp), as Easyfig draws comparisons;
their shade scales with identity. AMR (AMRFinderPlus), virulence (ABRicate VFDB) and mobile-element calls (MOB-suite,
PlasmidFinder, IntegronFinder, ISEScan, geNomad) of each genome's latest runs are marked under the gene they overlap.

**Gene investigation.** A query is one sequence of 30-50,000 bp or 10-10,000 aa, checked against the nucleotide (IUPAC)
or protein alphabet; it is saved with its SHA-256 and its source. Nucleotide queries are searched with blastn
(`-task blastn` by default; megablast, dc-megablast or blastn-short on request), protein queries with tblastn
(`-task tblastn -db_gencode 11 -seg yes -comp_based_stats 2`) against a BLAST database of each genome's contigs;
`-evalue` and `-max_target_seqs 500` are passed, `-max_hsps` is not (every HSP is kept). ARVA's chaining
(`arva_core.region.chain_matches`): HSPs below the identity threshold are dropped; the remaining ones, best first,
join an existing match of the same sequence and strand when they continue it in the same order on query and genome,
overlap it by at most 20 % of the shorter piece and lie at most `max_gap` bp away; an HSP over bases a better match
already uses is not counted. A match is *complete* (one piece covering at least the complete-coverage share of the
query), *partial* (less) or *split* (several pieces: an insertion such as an IS element, a frameshift or stop codon, or
an assembly break; the HSPs alone do not say which), and is reported when the union of its pieces covers at least the
minimum coverage. Identity is identical positions over aligned columns of all pieces. A match within 20 bp of a
sequence end is flagged. Mobile elements are those of the genome's latest runs on the same contig within the given
distance; MOB-suite's plasmid call of the contig is shown. These are observations, not evidence of mobility.

**Alignment and gene tree.** The matched sequences (pieces of a split match joined in query order, reverse-complemented
on the minus strand; optionally the nucleotide query) are aligned with MAFFT 7.505 (`--nuc` and L-INS-i
`--localpair --maxiterate 1000`, which its usage text recommends for up to about 200 sequences, or FFT-NS-2
`--retree 2 --maxiterate 0`; gap penalties are MAFFT's defaults). ARVA does not switch strategy by itself: more than
200 sequences with L-INS-i is refused with a note. Trees need at least four sequences: IQ-TREE 3.0.1 (`--seqtype DNA
-m MFP` (ModelFinder Plus, BIC) or a given model, `-B 1000` UFBoot, `--seed`, `-T`) or FastTree 2.1.11 (`-nt -gtr
-gamma -boot 1000 -seed`, SH-like local supports). Sequences are renamed s1..sN for the tools (both refuse duplicate
names) and the names are mapped back in the Newick file. The tree is unrooted and drawn from the file's base node.
Identical sequences are reported, since a tree cannot resolve them.

**Interpretation.** Presence of a similar gene in several genomes, a conserved neighbourhood, a nearby IS element or
an incongruent gene tree do not by themselves show horizontal transfer: common descent, gene loss, convergent
assembly artefacts and sampling explain the same patterns. Gene names come from the annotator: Prokka's Debian
database names the S. aureus seh locus "sep_1" (enterotoxin P), while NCBI's annotation calls it seh; a curated query
sequence avoids depending on names.

## Pangenome (Phase 7A)

**Input.** Each genome's latest annotation (Bakta or Prokka GFF3 with the sequence after ##FASTA), checked by
SHA-256 when the job runs. Gene families are only as good as these annotations: genomes annotated with different
annotators, versions or databases call genes differently, so the plan lists each genome's annotator and the result
warns when they differ.

**Panaroo 1.8.1** clusters the proteins (cd-hit at the sequence identity `-c` and length difference
`--len_dif_percent`, then families at `-f`), builds the gene graph and, depending on `--clean-mode`, merges
fragmented genes, re-finds genes the annotator missed (`--refind-mode`, `--search_radius`, `--refind_prop_match`) and
removes likely contaminants. ARVA passes every result-changing option, including the values the clean mode would set
for the number of genomes (strict: `--min_trailing_support` max(2, ceil(0.05 n)), `--edge_support_threshold` and
`--min_edge_support_sv` max(2, ceil(0.01 n)), `--trailing_recursive` 99999999, `--remove_by_consensus True`; moderate
and sensitive as in Panaroo's `set_default_args`). Panaroo's help gives 0.01 as the default of
`--length_outlier_support_proportion`; its code uses 0.1, which ARVA passes.

**Categories** are ARVA's: the share of genomes holding a family against the thresholds chosen — core ≥ core,
soft core ≥ soft core, shell ≥ shell, cloud below. The defaults (99, 95, 15 %) are those of Panaroo's
summary_statistics.txt (after Roary), which ARVA keeps and shows beside its own counts. With few genomes the
categories are coarse (with five genomes a family is core or in at most four, so soft core is empty).

**Accumulation curves**: for R random orders of the genomes (numpy `default_rng(seed)`; R and the seed stated), the
number of families in at least one of the first k genomes (pan) and in all of them (core, strict), with the mean,
SD, minimum and maximum at each k. A curve still rising at the last genome means more genomes would add families; ARVA
does not fit a model or call the pangenome open or closed.

**Heatmap ordering**: average-linkage (UPGMA) clustering of the Jaccard distance between genomes' family sets, to
place similar gene repertoires together; it is not a phylogeny. Families are ordered by genome count, then by their
pattern along the genome order.

**Family explorer**: members are Panaroo's (gene_presence_absence.csv), with the flags it writes (`_len`: length far
from the family's mode; `_pseudo`: not a valid gene), the sequences from its gene_data.csv, the location from ARVA's
annotation feature with the same ID (or Panaroo's location for a refound gene), neighbouring families (genes next to
the members on the same contig, counted in genomes) and Panaroo's alignment when one was made.

**Associations with metadata** (exploratory): for a field (sample type, host, origin, organism, collection year, MLST
type or a custom field), each group against the other genomes with a value, for families whose presence varies among
them: Fisher's exact test (two-sided, the sum of the probabilities of tables no more probable than the observed one,
relative tolerance 1e-7), Benjamini-Hochberg q-values over all tests of the field, Wilson 95 % intervals for the
shares and the odds ratio with a Woolf 95 % interval (0.5 added to every cell when one is 0). Sample sizes are shown;
genomes without a value are left out. Genomes are not independent: related genomes share families by descent, so
lineage alone produces associations, and ARVA makes no correction for population structure. An association is a
hypothesis, not a cause.

## Phylogeny (Phase 7B)

**Sources.** A tree is built from a file another result of the set holds, re-checked against its SHA-256: Panaroo's
core-genome alignment (`core_gene_alignment.aln`: for each core gene, meaning a family in at least Panaroo's
`--core_threshold` share of the genomes, 0.95 unless changed in the pangenome's settings and recorded with it, which is
not ARVA's ≥ 99 % "core" category, and genome, the copy with the fewest gaps; a
missing gene is gaps; or `core_gene_alignment_filtered.aln`, without the genes whose alignment entropy is above
Panaroo's automatic threshold Q3 + 1.5 IQR, at least 0.01), the SNPs of that alignment, one family alignment, a gene
investigation's MAFFT alignment, or an ANI matrix.

**SNP alignments.** SNP-sites 2.5.1 keeps the columns with at least two of A, C, G, T (`-m`; gaps and N are not a
state), or only columns made of A, C, G and T (`-c`). A tree on variable columns alone overestimates branch lengths,
so ARVA either adds the constant columns back as constant patterns (`-fconst a,c,g,t` with SNP-sites' `-C` counts,
in which a constant column with gaps counts as constant) or applies ascertainment bias correction (`+ASC` on `-c`
output, with a stated model because IQ-TREE 3.0.1 aborts when ModelFinder runs with +ASC). "No correction" is
allowed, with a warning that branch lengths are per variable site.

**Maximum likelihood.** IQ-TREE 3.0.1: `-m MFP` (ModelFinder Plus, BIC) or a stated model, UFBoot (`-B`, ≥ 1000
replicates) and/or SH-aLRT (`--alrt`, ≥ 1000), `--seed`, `-T`; nodes labelled "SH-aLRT/UFBoot" when both are run.
FastTree 2.1.11: `-nt -gtr -gamma`, SH-like local supports from 1000 resamples (`-boot 1000`), `-seed`. IQ-TREE's
documentation reads UFBoot ≥ 95 % and SH-aLRT ≥ 80 % as strong support; ARVA shows the values and does not classify
branches.

**Distance trees.** Neighbour joining (Saitou & Nei 1987, Studier & Keppler's formulas) computed by ARVA on p-distances
or Jukes-Cantor distances (−3/4 ln(1 − 4p/3), refused for p ≥ 0.75), both with pairwise deletion (only columns with
A, C, G or T in both sequences), or on 1 − ANI/100 (the mean of both directions when a tool reported both; a missing
pair stops the job). Negative branch-length estimates are set to 0 and counted. These are labelled distance trees;
the ANI one is a similarity dendrogram and is never presented as a phylogeny.

**Rooting.** The tools infer unrooted trees; ARVA keeps them as inferred and roots only the drawing: midpoint (the
middle of the longest leaf-to-leaf path, ties broken by leaf names; it assumes roughly equal rates) or an outgroup
(the branch whose one side is exactly the outgroup's leaves; otherwise refused as not monophyletic). The root is
placed at the middle of that branch: its position is not estimated. Supports belong to bipartitions and move with them
when the tree is re-rooted.

**Tree comparison.** Robinson-Foulds distance (Robinson & Foulds 1981) on unrooted bipartitions with at least two
leaves on each side, over the leaves both trees share (or matched by genome when each genome has one leaf),
normalised by the number of bipartitions of both trees; tested against IQ-TREE's `-rf`. Branch lengths and supports
are not compared.

**Reading the tree.** A tree describes the aligned sequences under the method's assumptions. Recombination and
horizontal transfer make parts of bacterial genomes follow different histories; a core-genome tree averages them and
leaves out the accessory genome. Gene trees may differ from the genome tree. Metadata drawn on a tree show patterns,
not causes; closeness on a tree does not establish transmission or horizontal transfer.

## Variant analysis (Phase 8A)

**Reference.** An assembly in ARVA (any sample or project) or a genome of a registered reference collection. ARVA
copies it (uncompressing if needed), checks its SHA-256 against the value recorded when the job was queued and
indexes it (`samtools faidx`). Variants are differences from this reference: their number depends on how close it is,
and regions absent from it cannot show variants.

**Alignment.** Short reads: BWA-MEM 0.7.17 (`-K 100000000` so that results do not depend on the thread count), pairs
or unpaired reads; long reads: minimap2 2.26 `-a -x map-ont` or `-x map-hifi`. A read group names the sample
(`-R @RG\tID:…\tSM:<sample>`, letters, digits, `.`, `_`, `-` only). samtools sorts and indexes; `samtools stats` and
`coverage` give the mapped reads and the mean depth, and a depth profile is kept.

**Calling.** bcftools 1.19 `mpileup -f ref -q MAPQ -Q BQ --max-BQ --delta-BQ -d 1000 [-B|-D] [-I] -F -m -o -e -h -M
-a FORMAT/AD,FORMAT/DP` with the values of bcftools' own `-X` profile for the technology written out (illumina: its
defaults; ont: `-B -Q5 --max-BQ 30 -I`, i.e. no BAQ and no indels; pacbio-ccs: `-D -Q5 --max-BQ 50 -F0.1 -o25 -e1
--delta-BQ 10 -M99999`), ARVA's minimum base quality 13 for Illumina (Snippy's), and minimum mapping quality 60
(Snippy's; both aligners give 60 to uniquely placed reads). Reads of pairs that are not properly paired, unmapped,
secondary, QC-failed and duplicate reads are skipped (bcftools' defaults, kept). `call --ploidy 1 -m -P 1.1e-3 -v`
(haploid; the multiallelic caller with its default prior). `norm -f ref -m -any -c e` left-aligns indels, splits
multiallelic records and stops if a REF allele does not match the reference.

**Filters.** Soft (`bcftools filter -s NAME -e EXPR`, later ones with `-m +`): LowQual `QUAL < 100`, LowDepth
`FORMAT/DP < 10`, LowAltFraction `AD[alt] < 0.9 × (AD[ref] + AD[alt])`. The values are Snippy 4.6.0's defaults
(bin/snippy: --mapqual 60, --mincov 10, --minqual 100; its README: "Values of 10 and 0.9 are commonly used" for
--mincov and --minfrac); the user can change them and they are recorded. Snippy's QUAL comes from FreeBayes;
bcftools' QUAL is another model (it rarely exceeds about 228), so the same number is not an equivalent threshold.

**Effects.** When the reference is an ARVA assembly with an annotation, ARVA writes its CDS (and sORFs) as an
Ensembl-style GFF3 (`ID=gene:`, `transcript:` with `biotype=protein_coding`, CDS phase 0), leaving out and counting
pseudogenes, features crossing a circular origin, lengths not a multiple of three and unknown sequences, and runs
`bcftools csq -f ref -g gff -p a -n 15`. csq is haplotype-aware (the variants of one codon are evaluated together;
the others point to it with `@position`) and translates with the standard genetic code only (csq.c): it reports
start_lost only for ATG starts, so a change in a GTG or TTG start codon (bacterial code 11) is reported as missense or
synonymous; ARVA marks those records with the reference start codon.

**Callable positions.** `samtools depth -aa -Q MAPQ -q BQ` counts, at each position, the reads and bases above the
caller's quality floors; positions with depth below the minimum depth are stored as low-depth intervals. The
callable fraction is the share of the reference at or above the minimum depth.

**SNP matrix and distances.** For the samples of a project, each sample's most recent run against the same reference
(same SHA-256). The sites are those where at least one sample has a passing SNP (one REF and one ALT base). At each
site a sample has its ALT base (passing SNP), the reference base (callable and no record there) or N (low depth, a
record that failed a filter, or inside a passing indel or complex record). The SNP distance of two samples counts the
sites where both have a base and they differ (pairwise deletion); the number of sites compared is reported, as are the
sites with a base in every sample. The heatmap orders samples by nearest neighbour for display only. SNP distances are
not a phylogeny; indels, recombination and regions absent from the reference are not counted, and runs with different
filters are flagged.

**Validation.** Simulated reads (labelled SIMULATED; error-free pairs and long reads from a constructed genome with
planted SNPs and indels, and the synthetic polishing draft with 7 substitutions, 4 insertions and 5 deletions) recover
every planted variant; real public Illumina runs (ENA DRR250760, DRR257875, DRR272507) against S. aureus
USA300_FPR3757 were cross-checked with Snippy 4.6.0 (`workflows/tool-adapters/tests/fixtures/variants/README.md`).

## Consolidated mobilome (Phase 8A)

For each assembly searched for mobile elements, ARVA gathers the most recent run of each method (MOB-suite plasmids
and repetitive elements, PlasmidFinder replicons, ISEScan IS elements, IntegronFinder integrons, geNomad plasmid,
virus and provirus calls) and the most recent AMRFinderPlus and VFDB (ABRicate) genes on that assembly. A gene is
"inside" an element when their coordinates overlap, "near" when it lies on the same contig within the chosen distance
(10 kb by default, the flanks of the Region Explorer, spec §16), and "on plasmid" when its contig was assigned by
MOB-suite to that plasmid. Whole-contig calls (geNomad plasmids and viruses) relate by contig. These are statements
about coordinates on the assembly only: co-location is not evidence of mobilisation or horizontal transfer, a
fragmented assembly can separate a gene from its element, and an element not searched is absent, not "none".

## Workflows and batch runs (Phase 8B)

- A workflow node runs exactly the analysis it names, through the same API action and checks as its dialog; nothing
  about a tool's options or outputs changes inside a workflow. Every result-changing option is stored explicitly in
  the version (the request model's defaults are written out when the workflow is saved) and recorded in each job.
- Options that depend on the data are not chosen for the user: Flye's read type and Racon's minimap2 preset stay
  unset in the predefined workflows that may receive any long reads; the Nanopore workflow sets Racon's map-ont.
  Filtlong's `--min_length 1000 --keep_percent 90` in the predefined long-read workflows is the example of Filtlong's
  README, shown and editable; on small read sets it can remove too much for Flye (seen on ARVA's 5x example reads).
- Sources follow stated rules (one valid R1/R2 pair; one valid FASTQ without a mate, never for an Illumina sample;
  the newest assembly or newest polished one; the newest annotation of that assembly); ambiguous or missing data
  make the sample's steps fail or be skipped with the reason rather than guessing. The run preview lists what each
  sample's sources picked.
- Bakta's skipped steps are those its preview reports when the step is launched; the locus-tag prefix is ARVA's
  suggestion from each sample's code unless set (the dialog's suggestion).
- Concurrency, threads and memory per job are ARVA's scheduling settings and estimates within the performance
  profile's budget, not measurements. Run times are the jobs' recorded durations.
- A branch re-runs the changed step and everything downstream as new jobs and reuses only completed upstream results
  whose kind, parameters and upstream graph are identical (compared by signature). Comparing two runs lists
  parameter, version, time and recorded-value differences; it does not attribute a difference to a cause.
- No Nextflow DSL2 file is exported: a node is not only a command but ARVA's input checks against its database,
  choices made at launch and the parsing of outputs into its records, which a Nextflow process could not reproduce
  faithfully. The run export (JSON) lists every job's tool, version, parameters, inputs, outputs and the exact
  argument vectors it executed.


### S. aureus typing, run options and Flye's memory guard in workflows

- **S. aureus typing node (`staph_typing`).** One step of the typing module (method `sccmec`, `spa` or `agr`) on an
  assembly, launched through the typing route, so its checks (tools, Ridom files for spa, bundled data) apply
  unchanged. Before launching, the node reads the assembly's species identification and MLST call with the
  module's own rule (`typing_modules.applicability`): anything but `applicable` (`conflicting`, `not_applicable`,
  `no_evidence`) **skips** the step with the code `wf_typing_not_applicable`, the status and the species and MLST
  scheme found, unless the node sets `override_applicability` (which the result then records, as the route does).
  A skip for this reason is not an error: a run whose other steps completed is `completed`. Two optional input
  ports, `species` (type `species_call`) and `mlst` (type `mlst_call`), connect the species and MLST steps so the
  typing runs after them; they carry no data the node uses (the evidence is read from ARVA's records). The
  "Complete bacterial genome" template runs SCCmec, spa and agr after the polished assembly, each fed by the species
  and MLST steps. spa needs the user's Ridom SpaServer files (Database Manager); without them the spa step fails
  with the route's reason. AgrVATE has no linux-aarch64 build (its `.unavailable` lock note), so on an arm64 image
  the template is not runnable until the agr step is removed.
- **Run options.** The run dialog offers, for one run, the polishing strategy of every polishing node (for example
  Medaka) and Flye's memory guard. The run's definition is the saved version with these values set; the run
  records the options (`settings.run_options`) and each parameter they changed (`settings.option_changes`), and the
  saved version is not changed.
- **Flye's memory guard (`memory_guard`, per Flye node).** `off` by default; the long-read templates set `auto`.
  With `auto`, before the Flye job is queued ARVA computes the memory estimate above for the sample's reads (the
  Filtlong step waits for the ARVA statistics of its output, which the estimate reads; if that statistics job's
  task is lost, the Filtlong step still completes and the estimate has no read statistics). In a run the estimate
  is checked in two parts. The part that depends on the reads is compared with the memory the run reserves per job
  (`memory_per_job_gb`, which with the memory budget sets how many jobs run at once), capped by the memory the
  container has, because other jobs may run beside Flye. Flye's fixed k-mer floor (8.6 GB) is compared with the
  container's memory only: Flye allocates it whatever share the run reserves, so a memory per job below 8.6 GB in a
  larger container is not "below the floor". Only when the container itself has less than the floor does the guard
  add nothing, since `--asm-coverage` does not lower it, and record `below_kmer_floor`. When it may
  not fit, the guard adds `--asm-coverage 40` and, when the node sets no genome size, the sample's expected genome
  size (basis `expected_genome_size`). It never changes a value the node sets itself: it does not apply when the
  node sets `asm_coverage` or `meta`, and it cannot apply without a genome size or read statistics, or when the
  reads are already below 40× of the genome size (`--asm-coverage` would then use every read and change nothing
  but the parameters); in those cases the job runs as configured. What it decided (estimate before and after, options added, or why not) is recorded on the
  run's item (`inputs.notes.flye_memory`) and shown in the run view.

## ARVA Discover (Phase 8C)

Exploratory analyses of a project's stored results; every result is labelled "exploratory, not confirmatory".

- **Data**: one row per sample. Fields: species, ST (scheme:ST), clonal complex, origin, host, sample type, collection
  year, organism, custom metadata columns. Features (0/1): AMRFinderPlus genes (type AMR), VFDB genes and PlasmidFinder
  replicons from the latest completed run of each source per sample; a sample without a run is *not searched* and is
  left out of every test of that feature. Samples whose features come from different assemblies are listed.
- **Associations**: for each group of a field (against the other samples with a value; with two values only one of
  the two mirror comparisons is tested) and each feature that varies among the samples used, the 2×2 table, Fisher's
  exact test (two-sided, R's tolerance 1e-7), Benjamini-Hochberg q over all tests of the run, shares with Wilson 95 %
  intervals, the difference with Newcombe's hybrid score interval (method 10), and the sample odds ratio with Woolf's
  interval (0.5 added to every cell when one is 0). Groups below the minimum size are listed, not tested.
- **Lineage stratification**: the same tables within each value of a lineage field (ST, clonal complex or any field),
  the Cochran-Mantel-Haenszel test with continuity correction (as R's `mantelhaen.test`), the Mantel-Haenszel common
  odds ratio and the Robins-Breslow-Greenland 95 % interval; strata with fewer than 2 samples are left out, and when
  no stratum varies in both group and feature ARVA reports that group and lineage coincide instead of a test. This is
  a coarse correction for population structure, not a phylogenetic comparative method.
- **Co-occurrence**: Fisher's exact test for each pair of features over the samples where both were searched, BH q over
  all pairs, odds ratio (Woolf), phi and Jaccard; network edges are pairs with q ≤ alpha, solid when the odds ratio is
  ≥ 1 and dashed otherwise. At most 150 features.
- **Distribution by lineage**: carriers among the lineage's searched samples with Wilson intervals.
- **Heatmap**: samples and features ordered by average linkage (UPGMA) on Jaccard distances (similarity clustering,
  not a phylogeny); samples with an unsearched feature are left out.
- **PCA**: SVD of the centred 0/1 matrix of complete samples and varying features, run only with at least 3 samples
  and 2 features; signs fixed so each component's largest loading is positive. A descriptive projection.
- **Verification**: `scientific-core/tests/test_discover.py` compares with SciPy 1.18.1 (`fisher_exact`,
  `false_discovery_control`, `binomtest(...).proportion_ci(method="wilson")`, `contingency.odds_ratio(kind="sample")`,
  `chi2.sf`, `linkage(method="average")`), with R's documented `mantelhaen.test(UCBAdmissions)` (X² 1.4269,
  p 0.2323; uncorrected 1.5246, p 0.2169; common OR 0.9046968, 95 % CI 0.7719074–1.0603298) and with Newcombe's (1998)
  example 56/70 − 48/80 (0.0524 to 0.3339).

## Sanger reads of one gene (scientific core)

`scientific-core/arva_core/sanger.py`; the facts and decisions behind it are in
[sanger-design-notes.md](sanger-design-notes.md). The API and its jobs are in `app/services/sanger.py` and
`app/tasks/sanger.py` (below); nothing is sent anywhere.

- **Reading**: `.ab1` (ABIF) files with Biopython 1.88 (`Bio.SeqIO`, format `abi`): base calls `PBAS2`, Phred
  qualities `PCON2`, peak scans `PLOC2`, the four processed traces `DATA9`–`DATA12` with their bases from `FWO_1`, and
  the instrument, base caller and run date. A file whose qualities are all 0 (an ABI 310 file) has "no usable
  qualities". FASTA and plain `.seq` text are read too, without qualities or trace.
- **Trimming**: the modified Mott algorithm as the maximum-scoring segment: each base scores `limit − 10^(−Q/10)`,
  and the kept region ends at the highest running sum (reset when it is not positive) and starts after the last zero
  before it (CLC Genomics Workbench manual, Quality trimming). The limit is a parameter, 0.05 by default (Biopython's
  value); the kept range is reported in 1-based positions of the original read with its mean quality and share of
  bases at Q20 or more. Biopython's own `abi-trim` is not used: its limit is fixed and it starts at the first positive
  value. A read without qualities is not trimmed unless a range is given by hand.
- **Chromatogram for display**: the traces between two scans, downsampled by keeping the highest value of each block
  of scans so no peak is lost, with a marker per base. A base is flagged for review when it is an IUPAC call or when
  the second channel at its peak is at least 0.33 of the highest (ARVA's flag, adjustable; 0.33 is tracy 0.9.1's
  default peak ratio).
- **Consensus of a forward and a reverse read**: the reverse read is reverse-complemented and aligned to the forward
  read with Biopython's `PairwiseAligner` (global, free end gaps, match 2, mismatch −3, gap open −5, extend −2, N as
  a wildcard). Every column keeps both reads' base, quality, channel heights at the peak and the peak's scan. Inside
  the overlap a difference is a conflict: the higher-quality base wins only when it is at least Q20 and 10 above the
  other (for a base against a gap, the gap read's quality is the lower of its neighbours'); a no-call (N) takes the
  other read's base; anything else is left as an IUPAC code (or N against a gap), and every conflict is listed.
  Outside the overlap the single read's base is used and marked. The other orientation is also scored: when it
  scores higher, the reads are flagged as possibly not a forward/reverse pair. Fewer than 25 overlapping columns or
  below 90 % identity in the overlap gives no consensus. These rules are ARVA's and are reported with the result.
- **Hits**: BLAST+ HSPs (`arva_tools.blast`, optionally with the subject title) are chained per subject with
  `arva_core.region.chain_matches` (pieces up to 50 kb apart join into one "split" match, as hlb interrupted by a
  prophage in MW2), giving identity (identical bases / aligned columns), query and subject coverage, bit score and the
  number of separate matches. Identity and coverage are kept unrounded, so a threshold is never passed by rounding
  (593 of 599 bases is 98.998 %, below 99 %). A genome hit is named by the annotated features it overlaps, with the
  share of each feature covered. Names come from NCBI 16S titles, ABRicate database headers (VFDB's "hly/hla" is
  both hly and hla) or mlst allele ids.
- **16S reading**: CLSI MM18's criteria as quoted by Frickmann et al. 2015, Locher et al. 2022 and Campodónico et al.
  2025 (the guideline itself was not read): species at ≥ 99 % identity with ≥ 0.8 % to the next species, genus at
  ≥ 97 %, query coverage ≥ 98 % and more than 440 aligned bases; ARVA also names a genus only when no other genus is
  within 0.8 %. Every species at or above 99 % and every one within 0.8 % of the best are listed. Caveats: the
  criteria were set for the first 500 bp of the gene (shown when the read aligns elsewhere), the database holds type
  strains, and in *Staphylococcus* 16S often cannot separate species (Kosecka-Strojek et al. 2019; Ghebremedhin et
  al. 2008), with rpoB, sodA, tuf or gap suggested.
- **What the user suspected**: a gene or a species (one word is a genus). "Match" when it is among the best hits,
  alone, and meets the thresholds (genes: 80 % identity and 80 % coverage, ABRicate 1.4.0's defaults, coverage being
  the larger of query and subject coverage; species: the CLSI values); "ambiguous" when other names tie with it
  (genes: same identity and coverage; species: within 0.8 %); "no match" when it is absent, below the thresholds or
  beaten by another name. Better and tied hits with other names are always returned.
- **Verification**: `scientific-core/tests/test_sanger.py` on Biopython's public chromatograms (3100, 310) and rule
  cases; `workflows/tool-adapters/tests/test_sanger_tools.py` on real BLAST+ 2.12.0 outputs: the 3100 16S read
  against NCBI's 16S database (2026-10-29 build: *S. epidermidis* at 99.85 %, four other hits at 99.71 %, read as
  genus *Staphylococcus*), MW2's seh against ABRicate's VFDB and VFDB's hlb split in MW2.

## Sanger identification (API and searches)

- **Where the reads live**: under the sample (strain) they come from; the uploaded files stay unchanged in `raw/`.
  When that sample has a genome in ARVA, its newest genome is the default "genomes" source.
- **Pairing** (ARVA's heuristic, shown and changeable): the direction from the end of the read's name (`-F`, `_R`,
  `Fwd`, `Rev`, `Forward`, `Reverse`, or a primer with its letter such as `784F`), then a primer name before it
  (`_784`), and what is left is the pair key. Two prefixes Macrogen adds are not part of the key: a leading block of 8
  hexadecimal characters and a hyphen on its file names (synthetic example `0a1b2c3d-S9_784-F.ab1`), and the order
  number and well in the FASTA header of its `.txt` (`H000000-000_A01_S9_784-F.ab1`, whose `.ab1` ending is dropped
  too). One forward and one reverse read with the same key of the same sample are proposed as a pair; when a key has
  several reads of one direction and only one has qualities (the chromatogram next to its `.txt` copy), that one is
  proposed, and the text copy is marked as such.
- **Upload checks**: each file is read, checked and stored one at a time; a damaged `.ab1` (any error of Biopython's
  parser, including the AssertionError it raises when a tag's size does not match its element count) or a second
  copy of the same file in one upload is skipped with its reason and the others go on. Before Biopython decodes an
  `.ab1`, ARVA checks its directory (ABIF layout as in Biopython 1.88's `_HEADFMT`/`_DIRFMT`): at most 4,096 tags,
  every tag's data inside the file, and the tags' data adding up to no more than the file size (real chromatograms
  use 81 to 99 % of it), so that a crafted file whose tags share one block cannot make the decoded data many times
  larger than the file. Chromatograms are limited to 5 MiB, text files to 2 MiB, and a file larger than the upload
  limit is refused, never cut.
- **What is searched**: the consensus, or one trimmed read; a reverse read alone is reverse-complemented first, so
  that the searched and exported sequence is on the forward strand as in a consensus. A read with nothing kept after
  trimming is named in the error, with the other read to identify alone.
- **One job per source**, each recording its tool, version, exact commands and (with `record_use`) its database's
  kind, version, version source, checksum and path; the worker checks the sequence's SHA-256, the database record
  and, for genomes, each genome's contigs SHA-256 again before running:
  - NCBI 16S (kind `ncbi_16s`): `blastn -task megablast -evalue 1e-10 -max_target_seqs 500` with the subject title,
    names from the titles;
  - VFDB (ABRicate 1.4.0's bundled copy): `blastn -task blastn -evalue 1e-5`, gene, product and factor from its
    headers;
  - PubMLST alleles (mlst's bundled BLAST database `blast/mlst.fa`): megablast, scheme, locus and allele from the ids;
  - a reference genome collection: megablast against each genome (`-subject`, decompressed when gzipped), species,
    strain and type material from the collection;
  - genomes in ARVA: megablast against the contigs, each hit named by the annotated features of the genome's latest
    annotation it overlaps, with the share of the feature covered; the species is ARVA's own species identification
    of that genome when it gave one;
  - AMRFinderPlus 4.2.7 nucleotide (translated) search with its curated identity thresholds and
    `--coverage_min 0.1` (10 % of the reference protein; ARVA's choice, see below), and spaTyper with the user's
    Ridom files.
  The BLAST settings are ARVA's choices (megablast for near-identical references as in the manual check of the
  design notes, blastn for VFDB) and can be changed per source; they are shown before the run and recorded.
- **AMRFinderPlus coverage**: `--coverage_min` is the share of the reference protein the hit covers (`amrfinder
  --help`: "Minimum coverage of the reference protein (0..1)", default 0.5). A Sanger amplicon is usually 300 to
  1,000 bases, less than half of most resistance genes: with AMRFinderPlus 4.2.7 and database 2026-08-07.1, bases
  701–1,300 of mecA (2,007 bp) give no row at 0.5 and mecA at 29.79 % coverage, 100 % identity, method
  `PARTIAL_CONTIG_ENDX`, at 0.1. When AMRFinderPlus reports nothing, the interface states the coverage asked for and
  the most a read of that length can cover, and that a gene not found is not shown to be absent.
- **Results**: the BLAST rows of every source are ranked together (bit score, identity, query coverage) and rows
  tied with the best are marked, never hidden; the list of identifications says how many rows and names tie with
  the best, since which of several tied species is listed first only follows the database ids, and gives the 16S
  reading's level. The 16S reading uses the NCBI 16S rows only, and when NCBI's 16S database was not searched the
  results say so. For a genome hit the gene's coverage is the share of the annotated feature the hit covers (unknown
  without an annotation); the contig's coverage is kept apart. AMRFinderPlus and spaTyper results are listed on
  their own. Changing the suspicion needs no new search.
- **The suspicion** is compared with every ranked hit: "best hit overall" is the best of all rows, and better rows
  that carry no name of that kind (an unannotated genome) are listed as neither supporting nor contradicting it.
  Gene names are compared case-insensitively with VFDB's aliases, and every name of the 16S rRNA gene ("16S",
  "16S rRNA", "16S ribosomal RNA", "rrs", MLST schemes' 16S loci) is one gene, which NCBI's 16S hits are. A species
  is read as a microbiologist writes it: an abbreviated genus ("S. aureus", "Staph. aureus") matches every genus it
  starts with, and a subspecies or strain is compared at the species level; the matched names are shown. Before any
  search has finished there is no outcome, and while searches run the outcome is marked provisional. For a species,
  hits on the sample's own genome are left out (that genome is named by ARVA's own species identification, so it
  would only repeat it), and when the best hit is not the 16S rRNA gene the comparison says that the CLSI
  thresholds are 16S criteria.
- **NCBI's 16S database**: NCBI publishes only the current build. ARVA reads its metadata file (date, size,
  sequence count) and MD5 file, downloads the archive after the user confirms the date and size, checks the MD5,
  records the archive's SHA-256 and extracts only the database files (NCBI's taxonomy files only when asked; the
  organism comes from the titles). A folder the user already has is registered instead; `blastdbcmd -info` reads it.
- **Report**: HTML (English or Spanish), JSON and CSV with the reads, trimming, consensus and conflicts, every search
  with its database and version, the ranked hits, the 16S reading with its criteria and sources, the suspicion, the
  searched sequence and the limitations. Numbers are cut, not rounded, as in the interface (98.998 % is printed
  98.99, never 99.00 next to a 99 % threshold it does not reach); the CSV and JSON hold every ranked row, not only
  the 50 the interface lists, and a text cell a spreadsheet would read as a formula is quoted.
- **Verification**: `apps/api/tests/test_sanger_api.py`: imports and refusals, pairing, the consensus of 3100.ab1
  with a reverse read built from its own calls, real BLAST+ searches (NCBI 16S 2026-10-29 build: genus
  *Staphylococcus*; the annotation fixture genome named by its Prokka feature; VFDB's seh; mlst's arcC_1;
  a one-genome reference collection), AMRFinderPlus on a mecA fragment with the constructed release, the 16S
  download from a local stand-in of NCBI's folder, and the migration up and down. A user's own real pair was also
  checked locally through the API (nothing of it is committed; design notes, section 6).

## Sanger screens (web)

The sample's **Sanger** tab (and the **Sanger (genes)** area, which lists the samples) shows what the API
computes; the interface decides nothing.

- **Reads**: dropped `.ab1`, FASTA or `.seq` files are uploaded to the sample; each read shows the direction, primer
  and pair key proposed from its name (editable), the bases called, the region kept by the default trimming (modified
  Mott, limit 0.05) with its mean quality and share of bases at Q20 or more, and whether it has qualities and a
  chromatogram. A file the API skips is listed with its reason.
- **Chromatogram**: the four processed traces (DATA9–DATA12, as the instrument recorded them; A green, C blue, G black,
  T red, each also with its own line pattern, A solid, C dashed, G dotted and T dash-dot, so that A and T differ
  without telling red from green), the base calls and a Phred quality bar per base (dashed line at Q20), the trimmed ends shaded, the bases to
  review (IUPAC calls and mixed peaks at the chosen ratio) and the consensus conflicts highlighted. The API sends each
  window downsampled by block maximum (no peak is lost); an overview strip shows the quality along the whole trace.
  Zoom and scroll with buttons, the overview, a "go to base" field or the keyboard (arrows, Shift+arrow or Page
  Up/Down, + and -, Home and End); a base outside the read is said to be outside it. Trimming (limit or manual range)
  and the mixed-peak ratio are previewed live, and the dialog says that this preview is not what the identification
  uses (its own trimming is set where it is built).
- **Consensus**: the proposed pair (or any forward and reverse read, or one read), each with its trimming, and the
  alignment and conflict settings (empty fields keep the defaults); the preview shows the overlap, the conflicts with
  both reads' bases, qualities and positions (each linked to that read's chromatogram) and the sequence in blocks of
  ten with resolved and unresolved conflicts marked by more than colour (bases of one read only underlined, dotted for
  the forward and dashed for the reverse, conflicts boxed). The proposed reads are chosen again when a direction or a
  pair key is corrected in the reads table. The consensus warnings (a single read, reads that look swapped,
  unresolved conflicts, reads without qualities) and the bases to review stay shown on the saved identification.
- **What you suspect**: optional, a gene or a species (a single word is a genus); it can be changed later without a
  new search.
- **Search**: the plan of every local source (tool and version, database and version and checksum, genomes, BLAST
  task and e-value, and what blocks a source), started after an explicit confirmation, only the sources that can run.
- **Results**: the comparison with the suspicion (match, ambiguous or no match, with the best row of that name, the
  best row overall and every better or tied row with another name; no outcome before any search, a provisional one
  while searches run); a note, with a link to the databases, when NCBI's 16S database was not searched; the 16S reading with the CLSI MM18 criteria as
  quoted, every species at or above 99 % and within 0.8 points, and the caveats with their sources; the ranked hits
  of all sources with identity, query and subject coverage, aligned length, match kind, e-value, bit score and the
  database with its version; AMRFinderPlus and spaTyper results. Percentages are cut, not rounded, to two decimals,
  so a value below a threshold is never shown as the threshold. Report in HTML (interface language), JSON or CSV,
  and the searched sequence as FASTA.
- **NCBI BLAST online**: never done by ARVA. A collapsed, optional section explains that pasting the sequence into
  NCBI's web page sends it outside the computer; only after the user ticks that acknowledgement can the sequence be
  copied and NCBI's BLAST home page opened. When the browser does not allow copying (plain http on a network
  address, or no permission) the sequence is shown to copy by hand. No ARVA result needs it.
- **NCBI 16S database**: in Tools & Databases, the 16S kind offers "Download the current build": the dialog shows
  NCBI's date, size, sequence count and MD5 (from NCBI's metadata and MD5 files only), the files kept, the folder and
  the space, and downloads after the user confirms the build, the size and NCBI's terms.
- **Verification**: `apps/web/src/test/sanger.test.tsx` (helpers, chromatogram keyboard and zoom, conflicts, the 16S
  reading, the suspicion, the ranking, the search confirmation, the opt-in online BLAST, uploads in Spanish and the 16S
  download) on data built from Biopython's public `3100.ab1` and the real BLAST+ output of its trimmed read against
  NCBI's 16S database (`apps/web/src/test/fixtures/sanger/build_fixture.py`). The screens were also driven in a
  headless browser on a user's own real pair (local check, nothing committed): no request to any host other than
  ARVA's, in English and Spanish.

## What ARVA does not do yet

- No pass/fail thresholds: suitability depends on technology, chemistry and purpose.
- No duplicate-read detection or k-mer analysis by ARVA itself (fastp reports a duplication estimate).
- No functional annotation of its own (names and products are the annotators'), and no taxonomic call beyond ARVA's
  reading of ANI hits against the collection you chose (above).
- No basecalling: POD5 raw signal must be basecalled outside ARVA (Dorado or MinKNOW).
- No resistance or virulence phenotype: AMR and virulence results are genes and mutations found, not a prediction
  of resistance, susceptibility or virulence; plasmid and mobile-element calls are the tools' (MOB-suite,
  PlasmidFinder, IntegronFinder, ISEScan; geNomad not validated here), never inferred from contig size.
- No structural variants, large indels or copy-number calls from reads; no diploid or mixed-population calling.

## Validation

`scientific-core/tests/test_seqstats.py` checks every metric against values computed by hand
(lengths, Nx/Lx, GC, Phred error averaging, Q20/Q30, per-position means, histograms conserving
counts, reproducible sampling) and checks that malformed inputs fail with the correct line numbers.
`scientific-core/tests/test_assembly_stats.py` and `test_gfa.py` check the assembly statistics, the
warnings and the graph reader (segments, links, paths) against hand-computed values and malformed inputs;
`apps/api/tests/test_assemblies_api.py` checks the graph's contig flags, the project list and the
report's Assembly section, CSV rows and escaping;
`test_synthetic_genome.py` checks the synthetic genome's layout, read geometry (positions, strands,
inserts, reads across the origin) and that its error rates match its qualities.
`workflows/tool-adapters/tests/test_flye.py` checks Flye's command for every option, the checks against
its `--help`, the parsers on real Flye 2.9.3 outputs and failure logs, the samtools helper and the
read-type suggestion; `apps/api/tests/test_flye_api.py` runs the job lifecycle with a stand-in Flye
(inputs refused, progress committed while it runs, failures, the live log) and the real Flye end to end.
`workflows/tool-adapters/tests/test_quast.py` checks QUAST's command, its option and label checks, the
report parsers on real QUAST 5.2.0 outputs and failure logs, and the minimap2 lookup; the real-tool tests
run QUAST on assemblies with known differences from the synthetic genome (and on IUPAC codes) and compare
it with ARVA; `apps/api/tests/test_quast_api.py` runs the job with a stand-in QUAST (requests refused,
recorded command, cross-check, served pages, failures) and the real QUAST end to end.
`workflows/tool-adapters/tests/test_polishing.py` checks every flag ARVA passes to Racon, Pilon, minimap2, BWA,
samtools and dnadiff against their recorded help texts, the argument vectors, and the parsers on real outputs
(`fixtures/polishing`); the real-tool tests polish a draft with known errors and compare the results with the
true reference; `apps/api/tests/test_polishing_api.py` checks the request rules, the lineage migration, and
runs Racon, Pilon, the hybrid strategy (with QUAST when installed) and Racon on a real Flye draft end to end.
`apps/api/tests/test_job_control_api.py` cancels a queued job (removed from the queue, never run by a worker that
had already taken it), a running one (a stand-in tool and the child it started are killed, partial outputs
removed, the log kept) and one no worker runs any more, keeps and resumes a stand-in Flye's work folder (the
interrupted stage's folder removed, `--resume` passed, refusals for another Flye version, an error of Flye's own,
or nothing completed beyond configure), and runs the real Flye: cancelled during polishing, resumed, it gives
the 300 kb chromosome and the 15 kb plasmid at their lengths. `apps/api/tests/test_batch_qc_api.py` checks the
plan's counts and reasons per sample, creation of exactly the planned jobs, refusal of a changed plan, recompute
and a missing tool. `workflows/tool-adapters/tests/test_framework.py` checks that a monitor can stop a tool with
gzip-streamed output and that its child processes are killed with it.
`workflows/tool-adapters/tests/` checks command construction for every option, output parsing,
safe execution (no shell, no secrets in the tool environment, timeouts) and runs each real tool on
the synthetic data; `apps/api/tests/test_tools_api.py` runs complete jobs, lineage and reports.

## References

- Saitou N, Nei M. The neighbor-joining method: a new method for reconstructing phylogenetic trees. Mol Biol Evol 1987;4:406-425.
- Robinson DF, Foulds LR. Comparison of phylogenetic trees. Math Biosci 1981;53:131-147.
- Page AJ, Taylor B, Delaney AJ, et al. SNP-sites: rapid efficient extraction of SNPs from multi-FASTA alignments. Microb Genom 2016;2:e000056.
- Kalyaanamoorthy S, Minh BQ, Wong TKF, et al. ModelFinder: fast model selection for accurate phylogenetic estimates. Nat Methods 2017;14:587-589.
- Guindon S, Dufayard JF, Lefort V, et al. New algorithms and methods to estimate maximum-likelihood phylogenies: assessing the performance of PhyML 3.0. Syst Biol 2010;59:307-321.
- Danecek P, Bonfield JK, Liddle J, et al. Twelve years of SAMtools and BCFtools. GigaScience 2021;10(2):giab008.
- Danecek P, McCarthy SA. BCFtools/csq: haplotype-aware variant consequences. Bioinformatics 2017;33(13):2037-2039.
- Seemann T. Snippy: rapid haploid variant calling and core genome alignment, v4.6.0. https://github.com/tseemann/snippy (source of ARVA's default filter thresholds).
- Xie Z, Tang H. ISEScan: automated identification of insertion sequence elements in prokaryotic genomes. Bioinformatics 2017;33(21):3340-3347.

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

- Schwengers O, Jelonek L, Dieckmann MA, Beyvers S, Blom J, Goesmann A. Bakta: rapid and standardized annotation of bacterial genomes via alignment-free sequence identification. *Microb Genom* 2021;7(11). doi:10.1099/mgen.0.000685
- Seemann T. Prokka: rapid prokaryotic genome annotation. *Bioinformatics* 2014;30(14):2068–2069. doi:10.1093/bioinformatics/btu153
- Maiden MCJ, Bygraves JA, Feil E, et al. Multilocus sequence typing: a portable approach to the identification of clones within populations of pathogenic microorganisms. *Proc Natl Acad Sci U S A* 1998;95(6):3140–3145. doi:10.1073/pnas.95.6.3140
- Seemann T. mlst. https://github.com/tseemann/mlst (software, unpublished; version 2.35.0 used)
- Jolley KA, Bray JE, Maiden MCJ. Open-access bacterial population genomics: BIGSdb software, the PubMLST.org website and their applications. *Wellcome Open Res* 2018;3:124. doi:10.12688/wellcomeopenres.14826.1
- Hyatt D et al. Prodigal: prokaryotic gene recognition and translation initiation site identification. *BMC Bioinformatics* 2010;11:119. doi:10.1186/1471-2105-11-119
- Larralde M. Pyrodigal: Python bindings and interface to Prodigal, an efficient method for gene prediction in prokaryotes. *J Open Source Softw* 2022;7(72):4296. doi:10.21105/joss.04296
- Chan PP, Lin BY, Mak AJ, Lowe TM. tRNAscan-SE 2.0: improved detection and functional classification of transfer RNA genes. *Nucleic Acids Res* 2021;49(16):9077–9096. doi:10.1093/nar/gkab688
- Laslett D, Canback B. ARAGORN, a program to detect tRNA genes and tmRNA genes in nucleotide sequences. *Nucleic Acids Res* 2004;32(1):11–16. doi:10.1093/nar/gkh152
- Nawrocki EP, Eddy SR. Infernal 1.1: 100-fold faster RNA homology searches. *Bioinformatics* 2013;29(22):2933–2935. doi:10.1093/bioinformatics/btt509
- Kalvari I et al. Rfam 14: expanded coverage of metagenomic, viral and microRNA families. *Nucleic Acids Res* 2021;49(D1):D192–D200. doi:10.1093/nar/gkaa1047
- Edgar RC. PILER-CR: fast and accurate identification of CRISPR repeats. *BMC Bioinformatics* 2007;8:18. doi:10.1186/1471-2105-8-18
- Galperin MY et al. COG database update: focus on microbial diversity, model organisms, and widespread pathogens. *Nucleic Acids Res* 2021;49(D1):D274–D281. doi:10.1093/nar/gkaa1018
- Lobry JR. Asymmetric substitution patterns in the two DNA strands of bacteria. *Mol Biol Evol* 1996;13(5):660–665. doi:10.1093/oxfordjournals.molbev.a025626
- Grigoriev A. Analyzing genomes with cumulative skew diagrams. *Nucleic Acids Res* 1998;26(10):2286–2290. doi:10.1093/nar/26.10.2286
- Robinson JT et al. Integrative genomics viewer. *Nat Biotechnol* 2011;29(1):24–26. doi:10.1038/nbt.1754
- Buels R et al. JBrowse: a dynamic web platform for genome visualization and analysis. *Genome Biol* 2016;17:66. doi:10.1186/s13059-016-0924-1
- Watson M, Warr A. Errors in long-read assemblies can critically affect protein prediction. *Nat Biotechnol* 2019;37(2):124–126. doi:10.1038/s41587-018-0004-z
- Ewels P, Magnusson M, Lundin S, Käller M. MultiQC: summarize analysis results for multiple tools and samples in a single report. *Bioinformatics* 2016;32(19):3047–3048. doi:10.1093/bioinformatics/btw354
- Ewing B, Green P. Base-calling of automated sequencer traces using phred. II. Error probabilities. *Genome Res* 1998;8:186–194. doi:10.1101/gr.8.3.186
- Cock PJA et al. The Sanger FASTQ file format for sequences with quality scores, and the Solexa/Illumina FASTQ variants. *Nucleic Acids Res* 2010;38:1767–1771. doi:10.1093/nar/gkp1137
- De Coster W, Rademakers R. NanoPack2: population-scale evaluation of long-read sequencing data. *Bioinformatics* 2023;39(5):btad311. doi:10.1093/bioinformatics/btad311
- De Coster W et al. NanoPack: visualizing and processing long-read sequencing data. *Bioinformatics* 2018;34:2666–2669. doi:10.1093/bioinformatics/bty149
- Kolmogorov M, Yuan J, Lin Y, Pevzner PA. Assembly of long, error-prone reads using repeat graphs. *Nat Biotechnol* 2019;37(5):540–546. doi:10.1038/s41587-019-0072-8
- Kolmogorov M et al. metaFlye: scalable long-read metagenome assembly using repeat graphs. *Nat Methods* 2020;17(11):1103–1110. doi:10.1038/s41592-020-00971-x
- Flye 2.9.3 manual (USAGE.md). https://github.com/mikolmogorov/Flye/blob/2.9.3/docs/USAGE.md
- Flye 2.9.3 source: `flye/main.py` (stages, params.json, --resume) and `flye/polishing/bubbles.py`. https://github.com/mikolmogorov/Flye/tree/2.9.3/flye
- RQ documentation, Jobs (stopping a currently executing job). https://python-rq.org/docs/jobs/
- Gurevich A et al. QUAST: quality assessment tool for genome assemblies. *Bioinformatics* 2013;29:1072–1075. doi:10.1093/bioinformatics/btt086
- Mikheenko A, Prjibelski A, Saveliev V, Antipov D, Gurevich A. Versatile genome assembly evaluation with QUAST-LG. *Bioinformatics* 2018;34(13):i142–i150. doi:10.1093/bioinformatics/bty266
- Mikheenko A, Valin G, Prjibelski A, Saveliev V, Gurevich A. Icarus: visualizer for de novo assembly evaluation. *Bioinformatics* 2016;32(21):3321–3323. doi:10.1093/bioinformatics/btw379
- QUAST 5.2.0 manual. https://github.com/ablab/quast/blob/quast_5.2.0/manual.html
- GFA Format Specification, version 1. https://github.com/GFA-spec/GFA-spec/blob/master/GFA1.md
- Wick RR, Schultz MB, Zobel J, Holt KE. Bandage: interactive visualization of de novo genome assemblies. *Bioinformatics* 2015;31(20):3350–3352. doi:10.1093/bioinformatics/btv383
- Flye release notes (NEWS.md; 2.9: contig paths in GFA, --nano-hq). https://github.com/mikolmogorov/Flye/blob/flye/docs/NEWS.md
- Li H. A new metric on assembly contiguity (auN), 2020. https://lh3.github.io/2020/04/08/a-new-metric-on-assembly-contiguity
- Lander ES, Waterman MS. Genomic mapping by fingerprinting random clones: a mathematical analysis. *Genomics* 1988;2:231–239. doi:10.1016/0888-7543(88)90007-9
- Chen S, Zhou Y, Chen Y, Gu J. fastp: an ultra-fast all-in-one FASTQ preprocessor. *Bioinformatics* 2018;34:i884–i890. doi:10.1093/bioinformatics/bty560
- Shen W, Le S, Li Y, Hu F. SeqKit: a cross-platform and ultrafast toolkit for FASTA/Q file manipulation. *PLoS ONE* 2016;11:e0163962. doi:10.1371/journal.pone.0163962
- Wick RR. Filtlong. https://github.com/rrwick/Filtlong
- Andrews S. FastQC: a quality control tool for high throughput sequence data. https://www.bioinformatics.babraham.ac.uk/projects/fastqc/
- Cornish-Bowden A. Nomenclature for incompletely specified bases in nucleic acid sequences. *Nucleic Acids Res* 1985;13:3021–3030. doi:10.1093/nar/13.9.3021
- Vaser R, Sović I, Nagarajan N, Šikić M. Fast and accurate de novo genome assembly from long uncorrected reads. *Genome Res* 2017;27(5):737–746. doi:10.1101/gr.214270.116
- Walker BJ et al. Pilon: an integrated tool for comprehensive microbial variant detection and genome assembly improvement. *PLoS ONE* 2014;9(11):e112963. doi:10.1371/journal.pone.0112963
- Li H. Minimap2: pairwise alignment for nucleotide sequences. *Bioinformatics* 2018;34(18):3094–3100. doi:10.1093/bioinformatics/bty191
- Li H. Aligning sequence reads, clone sequences and assembly contigs with BWA-MEM. arXiv:1303.3997, 2013.
- Danecek P et al. Twelve years of SAMtools and BCFtools. *GigaScience* 2021;10(2):giab008. doi:10.1093/gigascience/giab008
- Kurtz S et al. Versatile and open software for comparing large genomes. *Genome Biol* 2004;5(2):R12. doi:10.1186/gb-2004-5-2-r12
- Wick RR, Holt KE. Polypolish: Short-read polishing of long-read bacterial genome assemblies. *PLoS Comput Biol* 2022;18(1):e1009802. doi:10.1371/journal.pcbi.1009802
- Wick RR, Judd LM, Holt KE. Assembling the perfect bacterial genome using Oxford Nanopore and Illumina sequencing. *PLoS Comput Biol* 2023;19(3):e1010905. doi:10.1371/journal.pcbi.1010905
- Jain C, Rodriguez-R LM, Phillippy AM, Konstantinidis KT, Aluru S. High throughput ANI analysis of 90K prokaryotic genomes reveals clear species boundaries. *Nat Commun* 2018;9:5114. doi:10.1038/s41467-018-07641-9
- Shaw J, Yu YW. Fast and robust metagenomic sequence comparison through sparse chaining with skani. *Nat Methods* 2023;20:1661–1665. doi:10.1038/s41592-023-02018-3
- Ondov BD et al. Mash: fast genome and metagenome distance estimation using MinHash. *Genome Biol* 2016;17:132. doi:10.1186/s13059-016-0997-x
- Shaw J, Yu YW. Rapid species-level metagenome profiling and containment estimation with sylph. *Nat Biotechnol* 2025;43:1348–1359. doi:10.1038/s41587-024-02412-y
- Chaumeil P-A, Mussig AJ, Hugenholtz P, Parks DH. GTDB-Tk v2: memory friendly classification with the genome taxonomy database. *Bioinformatics* 2022;38(23):5315–5316. doi:10.1093/bioinformatics/btac672
- Varghese NJ et al. Microbial species delineation using whole genome sequences. *Nucleic Acids Res* 2015;43:6761–6771. doi:10.1093/nar/gkv657
- NCBI Datasets v2 API (OpenAPI document, https://www.ncbi.nlm.nih.gov/datasets/docs/v2/openapi3/openapi3.docs.yaml, fetched 2026-10-29).

S. aureus typing: International Working Group on the Classification of Staphylococcal Cassette Chromosome Elements
(IWG-SCC) (2009) Antimicrob Agents Chemother 53(12):4961–4967, doi:10.1128/AAC.00579-09; sccmec,
https://github.com/rpetit3/sccmec; Harmsen D. et al. (2003) J Clin Microbiol 41(12):5442–5448,
doi:10.1128/JCM.41.12.5442-5448.2003; Ridom SpaServer policy, https://spa.ridom.de/policy.shtml; spaTyper,
doi:10.5281/zenodo.4063625; Raghuram V. et al. (2022) Microbiology Spectrum 10(1), doi:10.1128/spectrum.01334-21
(AgrVATE); Diep B.A. et al. (2006) Lancet 367:731–739 (PMID 16517273); Kuroda M. et al. (2001) Lancet 357:1225–1240;
Ito T. et al. (1999) Antimicrob Agents Chemother 43(6):1449–1458.
