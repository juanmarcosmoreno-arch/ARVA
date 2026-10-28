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

### Polishing (Racon, Pilon) and the before/after comparison

A polished assembly is a new assembly record (`kind` "polished") linked to the draft it was made from
(`parent_assembly_id`); the draft is never changed. The strategy follows the reads, not one recipe for
every technology: long reads → Racon, short reads → Pilon, both → Racon then Pilon on Racon's result (the
Pilon job is queued when Racon's result is registered). Every tool, version, parameter, command, input
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
  draft contigs with no alignment, a round without changes, and an edit distance that rose.
- **Not integrated.** Medaka (model-based Nanopore polishing) needs a model matching the reads' basecaller and
  downloads models; it is planned. A change is not proof of a correction: Racon also changed a Flye draft that
  was already identical to the reference (5 substitutions, 4 indel bases, 36 bases trimmed at the ends); only a
  trusted reference (QUAST with one) can show which version is closer to the truth.

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
  GiB (the larger reading) and records the real size after unpacking. Databases ARVA does not support yet
  (AMRFinderPlus, CheckM2) are listed as planned without any number.
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

Bakta 1.12.2 (PyPI wheel, in its own virtual environment) with a database from the Database Manager, whose status
and content checksum ARVA re-checks, together with Bakta's folder check, when the job starts.

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
  crashes (SIGSEGV) on every non-empty input, so the CRISPR step is skipped on that system.
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

Ubuntu 24.04, Bakta 1.12.2 with the light database 6.0 and Prokka 1.14.6+dfsg-6, on the SYNTHETIC annotation genome
(`scripts/make_synthetic_annotation_genome.py`; 18,960 bp with planted random ORFs, three back-translated Swiss-Prot
proteins, RNA sequences sampled from covariance models with Infernal's `cmemit`, a CRISPR-like array and 100 N):

- Bakta ran tRNA, tmRNA, rRNA, ncRNA, ncRNA-region and gap detection and the plot; it skipped CDS and sORF
  (AMRFinderPlus not installed; Ubuntu's DIAMOND 2.1.9 older than 2.2.0), oriC/oriT (BLAST+ 2.12.0 older than
  2.17.0) and CRISPR (PILER-CR crash). It found the two sampled tRNAs (as `tRNA-Xxx`), the 5S and 16S rRNA, the
  RNase P RNA and the gap. ARVA's dependency versions were checked to equal Bakta's own `read_tool_output` for
  every installed program.
- Prokka found 18 CDS: the three back-translated proteins named after their Swiss-Prot entries (alkA, tag, quiB)
  and 15 hypothetical proteins, a tRNA (`tRNA-SeC(tca)`) and the 16S rRNA.

These results show that the tools ran and that ARVA reads them correctly; they say nothing about any organism.
Bakta's CDS annotation could not be validated here.

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
- **Limits.** Linear view only (circular view planned); one sequence at a time; at most 50,000 features per sequence
  in the layout. On ARVA's synthetic genomes nothing the explorer shows is biology.

## What ARVA does not do yet

- No pass/fail thresholds: suitability depends on technology, chemistry and purpose.
- No duplicate-read detection or k-mer analysis by ARVA itself (fastp reports a duplication estimate).
- No taxonomic or biological interpretation, and no functional annotation of its own: names and products are the annotators'.
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
