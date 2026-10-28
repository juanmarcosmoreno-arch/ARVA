# Roadmap and current status

## Phase 2 — Raw data and QC ✅ (v0.2.0)

Tool adapter framework (`workflows/tool-adapters`) with safe execution and version validation;
SeqKit independent cross-check of ARVA statistics; FastQC reports (served sandboxed) with module
flags; fastp (single- and paired-end) and Filtlong filtering with every parameter visible and
recorded; derived files with lineage; automatic statistics of filter outputs; before/after
comparison (metrics table and overlaid distributions); Tools & Databases page; Guide entries for
filtering, fastp, Filtlong, cross-check, FastQC flags and comparison; reports include processing
steps with exact commands; Docker image ships the tools (Debian packages, amd64/arm64).

Import paths and capacity: server-side folder import (`ARVA_IMPORT_ROOTS`, read-only sources, one
background job per import with per-file results); bulk import on the project page with sample IDs
inferred from Illumina/SRA/ONT file names; free-space checks (`ARVA_MIN_FREE_BYTES`, HTTP 507 before
the body is received, per-file re-checks); notice when identical content exists in another sample.

Metadata from the data and the lab sheet: platform hints and run values read from FASTQ/FASTA read
headers (shown as suggestions with a confidence, never applied silently) and an R1/R2 name check;
POD5 raw-signal files recognised by content and their run metadata read with the optional `pod5`
library; sample metadata imported from CSV or Excel (.xlsx) tables with a row-by-row preview, column
mapping (English/Spanish names), explicit date handling, one-transaction apply and an import history
with the file's SHA-256; metadata export to CSV/Excel that is safe against formula injection, and the
same protection in the report CSV.

Project-level QC: analysis jobs can belong to a project instead of a sample; the project page builds
a MultiQC 1.35 report (PyPI, own virtual environment) over the latest FastQC, fastp, SeqKit and
Filtlong results, shows which results it will use and why others are left out, checks that every input
appears exactly once, and keeps the general statistics with units and the producing tool.

NanoPlot 1.48.0 (PyPI, own virtual environment) for long-read FASTQ files: offline, never downloading
a browser, with NanoPlot's statistics labelled by its own definitions, reads and bases cross-checked
against ARVA (zero-length records explained), and N50, quality thresholds and mean quality shown
side by side or separately because their definitions differ.

Filter options: fastp's minimum and maximum length (discarding longer reads, kept apart from trimming
reads to a length), fixed 5′/3′ trimming per mate, low-complexity filtering and explicit adapter
sequences (with a warning when FastQC saw an adapter that fastp's detection missed), and a failed run,
with nothing registered, when no read passes; Filtlong target bases or a target coverage (depth × a
user-given genome size, recorded with the run), with the expected kept bases shown before running and
Filtlong's target outcome and the achieved depth after.

Overviews: a sequencing overview at the top of each sample's QC tab (every imported and derived file
with its lineage, read statistics, POD5 reads and signal duration, and bases per file) and a QC
overview on the project page (one row per sample, each value chosen by a stated rule and left empty
when it cannot be stated exactly; sortable, filterable by technology, CSV export).

### Still open from the original Phase 2 scope

- **Dorado** basecalling is not integrated: Dorado is not distributed through any package channel
  (Bioconda, conda-forge, PyPI, apt or Homebrew), is built for NVIDIA or Apple GPUs and downloads its
  basecalling models while it runs, whereas ARVA only runs packaged tools that work offline. Basecall
  POD5 outside ARVA (Dorado or MinKNOW) and import the FASTQ.

## Phase 1 — Foundation ✅ (v0.1.0)

Monorepo; FastAPI + PostgreSQL + Alembic; Redis/RQ worker; React interface with ARVA identity
(light/dark, EN/ES); projects and samples with metadata; FASTQ/FASTA(.gz) import with checksums,
duplicate detection and validation; read statistics with six interactive figures; analysis history
and provenance; HTML/CSV/JSON reports; ARVA Guide; Analysis Timeline; Docker Compose deployment;
unit, API and end-to-end tests.

### Known limitations (v0.2.0)

- Read statistics are computed by ARVA's own Python engine (≈ 7 Mbp/s short reads, ≈ 25 Mbp/s long
  reads on one core). Very large runs take minutes; SeqKit provides a much faster independent summary.
- Browser uploads are multipart requests (the server spools them before storing); for very large
  runs use server-folder import. Bulk import names samples from file names only: ONT output split
  into many chunk files per barcode is proposed as one sample per chunk (folder names are not used
  yet), so such barcodes are better imported from their sample page or a server folder.
- No read-ID uniqueness check by ARVA; adapter detection and a duplication estimate come from fastp.
- fastp's HTML report loads plotly.js from public CDNs; ARVA blocks external requests, so its charts
  do not draw inside ARVA (tables do; the file can be downloaded).
- The conda environment for macOS (`workflows/tool-adapters/environment.yml`) has not been run on a
  Mac by the test suite; SeqKit is 2.8.2 there and is reported as not validated.
- PDF export: print the HTML report from the browser; native PDF is planned.
- No authentication: intended for single-user local use (bound to localhost).
- Sample tags/cohorts, project duplication/import/export and a per-field change history are not
  implemented yet (metadata imports are recorded, but earlier values are not kept).
- Metadata tables: `.xls`, `.xlsm`, `.xlsb` and `.ods` are not read (save as .xlsx or CSV UTF-8);
  formulas are never calculated, so cells without a value stored by the saving program import as
  empty; ambiguous dates block their row until a date order is chosen, and partial dates ("2024") are
  kept as text in the custom metadata; custom columns are stored as text (no units or types); an
  empty cell never clears a stored value, so values are removed by editing the sample (custom fields
  too, in its Metadata tab). The database has no unique constraint on sample IDs, so imports into one
  project are serialised with a row lock instead (taken after the file has been parsed).
- NanoPlot reads FASTQ only (no BAM, sequencing_summary.txt or POD5); its plots come from unseeded
  random subsets on large files. It is not in the Docker image yet.
- MultiQC is not in the Docker image yet (it needs its own ~1.1 GB Python environment). Its report is
  served from ARVA's own origin with network access blocked, so it shares that origin's local storage
  (MultiQC keeps only its display settings there); Filtlong runs without a target cannot be included.
- Read-header platform hints come from the first 1,000 records only, and headers rewritten by tools
  or NCBI SRA carry no platform information (shown as "not inferable", never as a negative result).
- Deleting a project/sample removes database records but intentionally leaves raw files on disk.
- Demonstration mode (spec §34) is not included yet; the data model already has an `is_demo` flag and
  the UI/report label DEMO projects. Synthetic example reads are provided in `examples/synthetic`.
- Reads must be FASTQ/FASTA(.gz). POD5 raw signal is accepted, but only its run metadata are read
  (no basecalling); other formats are listed in the Import screen as planned.

## Phase 3 — Assembly ✅

Phase 3 delivered assembly of bacterial isolates from long reads (Flye), short reads (SPAdes, Unicycler) and both
(Unicycler hybrid); ARVA's own assembly statistics with heuristic warnings; QUAST evaluation and comparison;
assembly views (tiles, contig table, charts, graph explorer, comparison) and reports; polishing by technology
(Racon, Pilon, both) with direct evidence kept apart from indirect indicators; and job control: cancelling,
recovery of a stopped Flye run with Flye's own `--resume`, and batch QC over a project. Every metric that tools
define differently (read depth, k-mer coverage, relative depth, mapped read depth) is labelled by kind and never
compared as equal.

### 3A — Long-read assembly, evaluation and assembly views ✅

- **Synthetic test genome** (`scripts/make_synthetic_genome.py`): a SYNTHETIC 300 kb circular
  chromosome with two identical 5 kb repeats and a 15 kb two-copy plasmid, with simulated Nanopore
  reads (calibrated qualities) and Illumina pairs; byte-identical for the same seed.
- **ARVA's own assembly statistics** (`arva_core.assembly_stats`): contig count, total length, N50/L50,
  N90/L90, GC over unambiguous bases, length histogram, cumulative curve, length-weighted median
  coverage and six heuristic warnings with stated thresholds (every check stored, also when it could
  not run); a bounded GFA 1 reader with segments, links and paths (contig membership from P lines).
- **Flye 2.9.3** for long reads: the New assembly dialog (assisted configuration) names the assembler
  that fits the sample's technology (short-read and hybrid assemblers listed as coming next, not
  offered), lists the reads by lineage (original vs filtered copy, with ARVA's statistics), explains
  each option (read type with a heuristic suggestion, genome size with its basis, threads, polishing;
  advanced options collapsed), summarises what the run will do and starts only after an explicit
  confirmation. Running jobs show a stage stepper, live elapsed time and the live log (auto-scroll,
  pause), and can be cancelled (3B3). On the default synthetic genome Flye recovers both replicons,
  circular and identical to the reference.
- **Results**: ten summary tiles, heuristic warnings (and checks that could not run), a sortable contig
  table with Flye's columns and FASTA download, five charts (contig length histogram, Nx curve,
  cumulative length, coverage vs length, GC vs coverage) with data tables and SVG/PNG export, an
  assembly-graph explorer (force layout, node size by length, colour by the contigs' circular/repeat
  flags, zoom/pan, truncation notice), and a comparison table with overlaid cumulative curves when a
  sample has two or more assemblies.
- **QUAST 5.2.0** evaluates and compares a sample's assemblies, with or without a reference FASTA of
  the sample (offline, minimap2 from the system, never compiled during a run); ARVA reads its report by
  field name, shows its metrics and cross-checks the contiguity metrics against its own statistics at
  the same minimum contig length; QUAST's HTML report and Icarus viewers are served sandboxed.
- **Project and reports**: an Assemblies table on the project page; the sample HTML/JSON report has an
  Assembly section (inputs by lineage, command, version, statistics, warnings, QUAST metrics) and the
  CSV adds one assembly summary row per assembly (formula-injection safe).
- **Guide** entries: genome assembly (long, short, hybrid), assembly N50/L50/N90/L90 versus read N50,
  circularity, contig coverage, the assembly graph (GFA), Flye read types, Flye and QUAST.

### 3B1 — Short-read and hybrid assembly (done)

- **SPAdes 3.15.5** (short reads: an R1/R2 pair, unpaired reads or both; `--isolate`, `--careful` or no mode;
  explicit threads, memory limit and `--cov-cutoff`; `-k` only when given, otherwise the k values SPAdes ran
  are read from its log; contigs or scaffolds registered as chosen). Contig coverage is SPAdes' k-mer
  coverage, labelled as such everywhere; circularity is "not reported".
- **Unicycler 0.5.0** (short reads, long reads only, or hybrid, as the files' roles imply; bridging mode,
  `--keep`, k-mer sizes, depth filter, minimum FASTA length and linear sequences; helpers SPAdes, Racon and
  BLAST+ passed explicitly and recorded with Unicycler's own dependency table). Depth is Unicycler's relative
  depth; in long-read-only mode, which writes bare FASTA names, depth and circularity come from its GFA.
- Both register assemblies like Flye (lineage, statistics, warnings, live stage progress, plain failure
  reasons such as running out of memory); `coverage_kind` keeps read depth, k-mer coverage and relative depth
  apart in the interface, reports and exports.
- **New assembly dialog**: the assembler that fits the sample's reads (long → Flye; short → SPAdes or
  Unicycler; both → Unicycler hybrid), each with a plain-language explanation, defaults visible and advanced
  options collapsed; **run several strategies** queues one job per chosen assembler for side-by-side comparison.
- Guide entries: SPAdes, Unicycler, hybrid assembly, k-mer coverage.

### 3B2 — Polishing (done)

- **Strategy by technology**, never one recipe for all reads: long reads → **Racon 1.5.0** (minimap2 overlaps with
  the preset of the reads, every Racon option explicit, `-u` so no contig is dropped), short reads → **Pilon 1.24**
  (BWA-MEM with a fixed batch size, samtools, Pilon's jar with an explicit Java heap, `--fix` and every pileup
  heuristic explicit), both → Racon, then Pilon on Racon's result (queued automatically). N rounds, each recorded
  with its commands and logs; Pilon can stop after a round without changes.
- **Lineage**: a polished assembly is a new record (`kind` polished, `parent_assembly_id` its draft); the
  Assembly tab and the project table show draft → polished.
- **Before/after comparison** for every run, separating **direct evidence** (MUMmer dnadiff between the input and
  output of every round and between draft and result: substitutions, insertions and deletions as events and
  bases, bases lost at contig ends, breakpoints; Pilon's own list of changes) from **indirect indicators** (the
  polishing reads aligned to both versions: mapped reads, edit distance per 100 aligned bases, indels in the
  alignments, properly paired reads), plus ARVA's assembly statistics before and after, a chart of changes by
  type per round, labelled notes (trimmed ends of circular contigs, rising edit distance) and optional QUAST on
  the draft and every polished version.
- Reports: polished assemblies carry their lineage and the comparison in the HTML/JSON/CSV reports.
- Guide entries: polishing, Racon, Pilon, direct evidence versus indirect indicators.
- Not integrated: **Medaka** and **Polypolish** (see *Not yet integrated* below).

### 3B3 — Job cancellation, recovery and batch QC (done)

- **Cancelling** (`POST /jobs/{id}/cancel`; Cancel buttons with confirmation on running assemblies, polishing and
  QUAST runs and in every sample's Analysis history; status *Cancelled*): a queued job is removed from the task
  queue and never runs; for a running one the worker kills the tool's whole process group within about 5 s
  (a cancellation flag read by the monitor callback, chosen over RQ's stop-job, which would leave the tool
  running), removes the partial outputs exactly as for a failure and keeps the log. A job whose worker died is
  ended when cancelled once the task queue reports it is no longer executing.
- **Flye recovery**: Flye 2.9.3's `--resume` was confirmed in its source and with real runs, including after the
  work folder was moved. Its polishing stage appends to a file of the interrupted run, which turned the synthetic
  genome's 15 kb plasmid into 30 kb without any error, so ARVA deletes the interrupted stage's folder before
  resuming; resumed runs then matched an uninterrupted run byte for byte. ARVA keeps the work folder only when a
  run was stopped from outside (cancelled, time limit, killed, out of memory) after a stage beyond configure, and
  offers **Resume** (same reads, options, threads and Flye version, checked by ARVA because Flye does not) or
  **Discard**; otherwise it says why resuming is not offered.
- **Batch QC** on the project page and `POST /projects/{id}/analyses/batch`: ARVA read statistics, SeqKit and/or
  FastQC on every sample's files (imported only, or also derived; files with a completed result skipped unless
  *Recompute*), with a dry-run preview of exactly how many jobs each sample gets and why files are skipped;
  confirming creates exactly the previewed jobs (a changed plan is refused with the new one). Jobs are ordinary
  per-sample jobs.
- Guide entries: cancelling, recovering and resuming jobs; batch QC.

### Not yet integrated (Phase 3 scope)

Checked in the package indexes of Ubuntu 24.04 (the development system) and Debian bookworm (the Docker image):

| Tool | Purpose | Why not yet |
|---|---|---|
| Medaka | Model-based Nanopore polishing | Not packaged in Ubuntu 24.04 or Debian bookworm; needs a model matching the reads' basecaller and downloads its models |
| Polypolish | Short-read polishing that handles repeats | Not packaged in Ubuntu 24.04 or Debian bookworm |
| Raven | Fast long-read assembler | Not packaged in Ubuntu 24.04 or Debian bookworm (would have to be built from source) |
| Canu | Long-read assembler | Packaged, but in different versions (Ubuntu 2.2, Debian 2.0), so one validation would not cover both systems; not evaluated in ARVA yet (Flye covers long-read isolates) |
| MEGAHIT | Short-read assembler | Packaged (1.2.9 in both), but described by its package as a metagenome assembler; not evaluated on isolates against SPAdes `--isolate` |
| BUSCO | Gene-content completeness | Packaged (Ubuntu 5.5.0, Debian 5.4.4) but needs lineage datasets downloaded from its server, which ARVA does not do during runs; database handling is planned with the annotation phase |
| CheckM2 | Completeness and contamination | Not packaged in Ubuntu 24.04 or Debian bookworm; needs its DIAMOND reference database (several GB, downloaded) |

### Next

- The Assembly navigation page across projects; batch processing beyond QC (filtering, assembly) on top of the
  batch plan; resume for SPAdes or Unicycler only once their own restart options are validated.

Known limitations: the Docker image installs Debian bookworm's Flye 2.9.1 and minimap2 2.24, which have not
been validated (2.9.3 and 2.26 were tested); SPAdes and Unicycler take one file per role (several runs of the
same library must be merged first), and so do Racon and Pilon; polishing treats circular contigs as linear (their
ends are polished less well, and Racon may trim them); the graph view draws at most 500 segments (the GFA can be downloaded for
Bandage) and does not draw a segment's link to itself; coverage, circularity and repeat flags are the
assembler's own values.

## Phase 4 — Annotation (in progress)

**4A Database Manager** ✅: catalogue with verified facts (Bakta database 6.0 light and full from Zenodo
record 14916843; AMRFinderPlus and CheckM2 listed as planned, without numbers); download as a cancellable,
resumable worker task after an explicit confirmation of size, licence and space, MD5 against the published
checksum, safe unpacking, Bakta's folder check and a SHA-256 manifest; registration of an existing folder;
verification on demand; deletion refused while a job uses the database; disk usage; `ARVA_DB_DIR` (Docker:
the `arva-databases` volume); jobs record the database key, version and checksum; Databases section on the
Tools & Databases page (EN/ES). Next: Bakta, the Genome Explorer, annotation views and exports.

## Later phases

| Phase | Scope |
|---|---|
| 3 ✅ | Assembly (Flye, SPAdes, Unicycler), QUAST, contig plots, GFA view, polishing (Racon, Pilon), job cancellation and Flye resume, batch QC; Medaka, Polypolish, Raven, Canu, MEGAHIT, BUSCO and CheckM2 not yet integrated (above) |
| 4 | Annotation (Bakta; Prokka), Genome Explorer (linear + circular), exports (GFF3, GenBank, FASTA) |
| 5 | MLST, AMRFinderPlus, virulence (VFDB), BLAST, species identification (Mash/FastANI/Kraken2/GTDB-Tk) |
| 6 | Comparative genomics: ANI, synteny, dot plots, Genome Region Explorer |
| 7 | Pangenome (Panaroo), alignments (MAFFT), phylogeny (IQ-TREE), Tree Explorer |
| 8 | Workflow Builder (Nextflow DSL2), batch processing beyond QC (first step: batch QC, Phase 3), mobilome, variants, ARVA Discover, full reports, optional ARVA Assist, multi-user |
