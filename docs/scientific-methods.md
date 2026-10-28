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
  reports (e.g. Flye's `assembly_info.txt`); ARVA does not recompute them. The coverage summary is the
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
(`coverage_tag`: Flye `dp`, "mean read depth") and leaves it empty for assemblers it does not know.
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
  needs the user's confirmation that the files hold long reads. The interface warns when a filtered
  file and a file it was filtered from are both selected (the reads would count twice).
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
- **Read type: ARVA's suggestion (heuristic).** Flye's descriptions: `--nano-hq` for "Guppy5+ SUP or
  Q20" reads with < 5 % error, `--nano-raw` for pre-Guppy 5 reads (< 20 %), `--pacbio-hifi` < 1 %,
  corrected reads < 3 %. ARVA suggests a value, labelled as a heuristic and never applied by itself:
  the platform comes from the sample's technology, else from the read headers when every file
  identifies the same long-read platform with high or medium confidence. For Nanopore reads the mean
  error probability over all bases of the selected files, `Σ_files bases × 10^(−Q̄/10) ÷ Σ bases`
  where `Q̄` is each file's error-averaged mean base quality, gives `--nano-hq` at ≤ 5 % and
  `--nano-raw` above; without ARVA statistics, a SUP basecall model in the read headers gives
  `--nano-hq`, otherwise there is no suggestion. At ≤ 1 % the interface quotes Flye's manual ("For Q20
  data, use a combination of `--nano-hq` and `--read-error 0.03`"). For PacBio, ≤ 1 % gives
  `--pacbio-hifi`; without statistics CCS read names give `--pacbio-hifi` and subread names
  `--pacbio-raw`. Qualities are the basecaller's estimates; the suggestion and its basis are stored
  with the job (`arva_read_type_suggestion`), next to the read type the user chose.
- **Genome size.** Optional in Flye 2.9; when given, Flye logs the coverage it implies and warns below
  5× or above 1,000×, passes it to its disjointig assembler, and uses it with `--asm-coverage` to keep
  only the longest reads for that stage. ARVA offers three sources and records which one was used
  (`genome_size_basis`): the sample's expected genome size (from its read statistics, as in "Assembly
  warnings"), an estimate `round(total read bases ÷ assumed depth)` (half up; needs ARVA statistics
  for every selected file, and the server recomputes it), or a value typed by the user. ARVA never
  assumes a size. The same size is used for the assembly's genome-size warning, with its basis shown.
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
  ("Looks like the system ran out of memory", or the process killed by signal 9). Flye's last log
  lines go into the job log; partial outputs are removed.
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

### Synthetic genome for assembly

`scripts/make_synthetic_genome.py` writes a SYNTHETIC genome with known structure (circular 300 kb
chromosome with two identical 5 kb repeat copies, circular 15 kb plasmid at two copies) and simulated
Nanopore-like and Illumina-like reads; `examples/synthetic-genome/README.md` documents the model,
parameters and realised statistics. Qualities are calibrated by construction: every base is in error
with the probability its own Phred value states. With Flye 2.9.3 (`--nano-hq`) the default data
assemble into the two replicons at their exact lengths, both circular, the plasmid at about twice the
chromosome's coverage.

## What ARVA does not do yet

- No pass/fail thresholds: suitability depends on technology, chemistry and purpose.
- No duplicate-read detection or k-mer analysis by ARVA itself (fastp reports a duplication estimate).
- No taxonomic or biological interpretation.
- No basecalling: POD5 raw signal must be basecalled outside ARVA (Dorado or MinKNOW).

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

- Ewels P, Magnusson M, Lundin S, Käller M. MultiQC: summarize analysis results for multiple tools and samples in a single report. *Bioinformatics* 2016;32(19):3047–3048. doi:10.1093/bioinformatics/btw354
- Ewing B, Green P. Base-calling of automated sequencer traces using phred. II. Error probabilities. *Genome Res* 1998;8:186–194. doi:10.1101/gr.8.3.186
- Cock PJA et al. The Sanger FASTQ file format for sequences with quality scores, and the Solexa/Illumina FASTQ variants. *Nucleic Acids Res* 2010;38:1767–1771. doi:10.1093/nar/gkp1137
- De Coster W, Rademakers R. NanoPack2: population-scale evaluation of long-read sequencing data. *Bioinformatics* 2023;39(5):btad311. doi:10.1093/bioinformatics/btad311
- De Coster W et al. NanoPack: visualizing and processing long-read sequencing data. *Bioinformatics* 2018;34:2666–2669. doi:10.1093/bioinformatics/bty149
- Kolmogorov M, Yuan J, Lin Y, Pevzner PA. Assembly of long, error-prone reads using repeat graphs. *Nat Biotechnol* 2019;37(5):540–546. doi:10.1038/s41587-019-0072-8
- Kolmogorov M et al. metaFlye: scalable long-read metagenome assembly using repeat graphs. *Nat Methods* 2020;17(11):1103–1110. doi:10.1038/s41592-020-00971-x
- Flye 2.9.3 manual (USAGE.md). https://github.com/mikolmogorov/Flye/blob/2.9.3/docs/USAGE.md
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
