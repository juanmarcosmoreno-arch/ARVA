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
- Not integrated: **Polypolish** (see *Not yet integrated* below). **Medaka** 2.1.1 was added later from a pinned
  Bioconda environment, with the models its package ships (docs/scientific-methods.md, *Polishing*).

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
| Medaka | Model-based Nanopore polishing | Integrated later (2.1.1 from Bioconda, models shipped in its package only); not packaged in Ubuntu 24.04 or Debian bookworm |
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

## Phase 4 — Annotation ✅

**4A Database Manager** ✅: catalogue with verified facts (Bakta database 6.0 light and full from Zenodo
record 14916843; AMRFinderPlus and CheckM2 listed as planned, without numbers); download as a cancellable,
resumable worker task after an explicit confirmation of size, licence and space, MD5 against the published
checksum, safe unpacking, Bakta's folder check and a SHA-256 manifest; registration of an existing folder;
verification on demand; deletion refused while a job uses the database; disk usage; `ARVA_DB_DIR` (Docker:
the `arva-databases` volume); jobs record the database key, version and checksum; Databases section on the
Tools & Databases page (EN/ES).

**4B Genome annotation** ✅: Bakta 1.12.2 (PyPI, own environment) and Prokka 1.14.6 (Debian package, offered as the
alternative; its README says it is no longer maintained); ARVA repeats Bakta's start-up dependency checks and passes
Bakta's own `--skip-*` options for steps that cannot run, recording why, plus a PILER-CR crash test; `annotations`
table (tool, version, database name, version and checksum, parameters, per-step status, summary, sequences, files
with SHA-256) and a `features.jsonl` index per annotation; API for preview, run, list, summary, bounded feature
queries, feature detail with sequences, the annotator's files and exports of all or selected features (GFF3,
GenBank, FASTA, TSV); Annotation tab with run dialog, tiles, steps, charts, feature table and downloads; Guide
entries (annotation, Bakta, Prokka, hypothetical proteins, CDS, tRNA/rRNA, COG) EN/ES; Annotation section in the
HTML/JSON/CSV reports; Docker image with Bakta and the bookworm packages. On Ubuntu 24.04 Bakta's CDS, sORF, ori and
CRISPR steps cannot run (AMRFinderPlus not packaged, DIAMOND and BLAST+ too old, PILER-CR crashes), so Prokka is the
validated CDS annotator here; Bakta's CDS annotation is not validated yet.

**4C Genome Explorer (linear)** ✅: `/explorer` lists every annotation and `/explorer/<annotation>` opens it (also from
the Annotation tab and the feature details): a sequence selector with lengths and topology (Bakta's, else the
assembler's flag), ruler, overview bar, zoom (buttons, wheel, keyboard), pan (drag, buttons, keyboard), region
selection on the ruler; genes as arrows on forward and reverse lanes coloured by feature group with a legend
(validated palette; hypothetical proteins outlined, pseudogenes dashed), intergenic regions, GC and GC skew in
windows (window fitted to the view or chosen, with min–max bands when windows are grouped), coverage from the
polishing alignments when they exist for exactly these contigs (polishing now keeps a 25 bp `samtools depth` profile
of the draft and polished alignments) and a stated reason otherwise, and the bases with their complement when zoomed
in. SVG rendering of the view only, with level of detail above 600 features. Search by gene, locus tag, product,
identifier, sequence name or `contig:start-end`. Feature panel with every §11 field (identifier, coordinates,
orientation, predicted function, the annotator's nucleotide and protein sequences with copy, tool, version, database
and checksum, translation table, evidence, links) and ARVA's checks of the annotator's sequences against the genome.
Exports: region FASTA (either strand, up to 1 Mb), the features overlapping a region or marked one by one (GFF3, FASTA
of genes or proteins, TSV), and the view as SVG. API: `GET /annotations`, `/annotations/{id}/tracks`, `/sequence`,
`/layout`, and region exports. Guide entries `genome_explorer` and `gc_skew` (EN/ES). `samtools depth` was run with
samtools 1.19.2 (Ubuntu 24.04); the Docker image's samtools 1.16.1 was not run. Coverage exists only for polishing
runs made from 4C on.

**4D Circular map, annotation charts, reports** ✅: the Genome Explorer's *Circular map* view (own SVG): rings for the
sequence (with features that have no strand), genes on strand + and −, a custom ring (a feature type, pseudogenes or
a text search), read coverage when it exists, GC content (difference from the mean of the drawn sequences) and GC
skew, in windows of one length on every sequence; rings for AMR, virulence and mobile elements listed as available
after Phase 5 and not drawn; ring toggles; all sequences on one circle or one circle per sequence side by side
(chromosome and plasmids, up to six) with shared scales; tooltips from the angle and radius, click to open the same
feature panel as the linear view and “Show in the linear view”; SVG and PNG export with the legend and a caption
(sample, annotator, version, database; SYNTHETIC note) inside the figure; light and dark. Annotation charts in the
Annotation tab (ChartCard: validated palette, table view, SVG/PNG): features by type, hypothetical against
characterised CDS per sequence, gene length distribution by class, gene orientation (strand only: leading and lagging
need the replication origin), gene density per window along each sequence, and COG categories as reported (named
from NCBI COG 2020) or a statement that none were reported. API: `GET /annotations/{id}/map` and
`/annotations/{id}/charts` (numbers from `arva_core.annotation_stats`). The sample HTML report gains the circular map
as inline SVG (escaped names), a sequence table and the charts' numbers; the JSON report carries the same numbers
(`charts`, `map`); the CSV report is unchanged. Guide entries `circular_map` and `annotation_charts` (EN/ES).

### What Phase 4 leaves for later

- ~~Bakta's CDS annotation is not validated here~~: done in 5D1 (Bakta's Bioconda environment; validated on Linux
  against NCBI's annotation of S. aureus N315). The Docker image has not been built or run.
- **Phase 5**: InterProScan for protein domains (MLST, species identification, AMRFinderPlus with the AMR and
  virulence rings, VFDB and the plasmid and mobile-element searches with their rings are done: 5C1, 5C2, 5D1, 5D2).
- The circular map has no zoom (the linear view is for detail) and draws at most 50,000 features per map; contigs of a
  draft assembly on one circle are in the annotator's order, not in genome order.

## External storage (5A) ✅

- `scripts/start.sh --data-dir / --databases-dir / --add-databases (repeatable) / --remove-databases / --import-dir /
  --show-config / --reset-config`, saved in `~/.config/arva/arva.conf` (mode 600, read line by line, never sourced);
  each folder checked (absolute, existing, readable/writable, still on the disk it was chosen on; on a Mac the
  filesystem through `diskutil info -plist`, exFAT/FAT warned about; free space with `df -Pk`); a missing disk stops
  the start; a generated Compose override mounts the folders with `create_host_path: false` (extra database folders
  read-only at `/databases-external/<n>`).
- PostgreSQL stays in its Docker volume; the `backup` service dumps the metadata (pg_dump custom format) into
  `<data folder>/backups` every 24 h, on request and before a restore, keeping 14 of each kind; `scripts/restore.sh`
  restores into a new database before replacing the current one; `scripts/backup.sh`.
- Storage marker `.arva-storage` recorded in the metadata: writes refused with coded 503s and jobs failing with
  `storage_unavailable`/`storage_lost` when the data folder is missing or foreign; adoption or restore when the
  metadata is new; databases on a disconnected disk shown as unavailable and kept.
- `GET /system/storage` (every location), `POST /system/storage/adopt`, `POST /system/backups`; Settings → Storage
  (EN/ES) with the launcher commands; the Import page's storage card shows the folder on the Mac.
- Not yet validated on a real Mac (macOS commands tested with constructed outputs); the Docker image was not built.

## Database kinds (5B) ✅

- A registry of 16 database kinds (`app/services/database_kinds.py`), every fact checked in the tool's documentation
  or source code (cited; unconfirmed facts listed): how to recognise a folder, where its version is read, typical
  size, tools and versions, licence and citation, and whether ARVA can download it. Detectors per kind on the
  official layouts, tested on constructed miniature folders.
- Register existing folders or files where they are (browse the database folder and the added folders, detection
  preview with the file the version came from, a declared version when the files state none, never writing into the
  folder); quick verification at registration and a cancellable full checksum with progress (and the publisher's
  per-file MD5s where it lists them); unavailable while the disk is disconnected and available again when it is back.
- Reference genome collections for ANI species identification, for any genus: NCBI Datasets package, FastANI `--rl`
  list (host paths mapped to the mounts, paths outside refused, missing files reported), FASTA folder, and a copy
  extracted from the package zip; taxonomic coverage shown; version = source + date + accession fingerprint.
- Downloads of a chosen version into a chosen database folder (Bakta 6.0 light/full, GTDB-Tk R232, Kraken 2 Standard
  2026-06-26, CheckM2 3, BUSCO bacteria_odb12.2, geNomad 1.9) with size, free space, licence, resume and MD5.
- Several versions per kind, one default per kind; the Bakta dialog chooses the version; every job records kind,
  version, how it was known, checksum (if computed) and path. Migration `d9f2b4a6c8e1`.
- Not yet validated on a real Mac; only Bakta is run by ARVA, so the other kinds are registered and versioned for the
  analyses that will use them (species identification, AMR, plasmids, …) without a tool-version check yet.

## Pinned Bioconda tools and MLST (5C1) ✅

- micromamba 2.9.0 from conda-forge (`scripts/install-micromamba.sh`, package SHA-256 pinned per platform and
  checked against conda-forge's repodata); one environment per tool from explicit locks with a SHA-256 per package
  (`docker/conda-locks/<tool>/{spec.txt,linux-64.lock,linux-aarch64.lock}`), created, checked, verified and
  re-solved with `scripts/conda_locks.py`; the Docker build installs the image architecture's locks in one layer,
  without micromamba or its cache. Adapters declare the platforms they have locks for; the Tools page says when there is none.
- mlst 2.35.0 (`arva_tools/mlst.py`): every flag checked in `--help` and its defaults recorded from it; --minid,
  --mincov, --minscore, --threads, --exclude or --scheme, --blastdb, --datadir passed explicitly (minimum score 0
  and no exclusions with a chosen scheme, as mlst applies them); --full TSV, JSON (cross-checked) and --novel FASTA
  parsed; exact, novel (~), partial (?), missing (-), several (n,m) and null (0) calls; tied schemes from mlst's
  warning; clonal complex from the scheme's profile file when it has a column for it.
- Job `mlst_typing` on any assembly of the lineage (draft or polished), the bundled schemes as a read-only database
  record (origin `bundled`, kind `mlst_schemes`, full checksum, PubMLST terms), re-checked before the run; results
  table `mlst_results` (migration `a4c7e2f9b3d1`); the sample's *Genomic analysis* tab, the project's MLST table
  (CSV), the cross-project *Genomic analysis* page (the sidebar's P5 entry), report sections (HTML/JSON/CSV), Guide
  entries (MLST, sequence type, novel alleles) in English and Spanish.
- Tested with real mlst output on NCBI RefSeq NC_007795.1 (S. aureus NCTC 8325: ST8) and NC_000913.3 (E. coli K-12
  MG1655: Achtman ST10; Pasteur scheme ST262), two derived test inputs (novel/partial/missing/several alleles; a
  two-species mixture with a tie) and the SYNTHETIC genome (no scheme). The linux-aarch64 lock was solved, not
  installed or run; the Docker image was not built.

## Species identification (5C2) ✅ — Phase 5C done

- Locks and environments for FastANI 1.34, skani 0.4.0, Mash 2.3 and sylph 1.0.0 (linux-64 and linux-aarch64;
  installed and run here on linux-64) and GTDB-Tk 2.8.0 (linux-64 only: no pplacer 1.1.alpha19 for aarch64).
- Adapters with every flag checked against the tool's `--help`, its defaults recorded and passed explicitly; parsers
  for FastANI's TSV, skani's TSV, `mash info`/`mash dist`, `sylph inspect`/`sylph profile` and GTDB-Tk's summary.
- `arva_core.species`: ARVA's reading of the hits (same species / ambiguous / no reference within the boundary /
  no hits / Mash screening only) with the 95 % boundary of Jain et al. 2018, the 0.5 aligned fraction of GTDB-Tk and
  ARVA's 0.5-point margin, every reason and caveat coded; consistency with the MLST scheme's name and the organism
  given for an annotation.
- Job `species_identification` on any assembly against a reference genome collection (FastANI, skani), a Mash
  sketch, a sylph database or GTDB-Tk data, with the SHA-256 of every reference genome; GTDB-Tk refused below its
  documented 140 GB; table `species_results` (migration `b8e1d5c3f7a2`); the *Genomic analysis* tab (method dialog,
  interpretation card, ANI/AF chart with the 95 % line, hits table), a species column in the project's genomic
  table (and CSV), the cross-project page, report sections (HTML/JSON/CSV), Guide entries (ANI, species boundary,
  reference collection, GTDB) in English and Spanish.
- Reference collections built from NCBI Datasets for any bacterial taxon: plan (taxon, count, species, type material,
  sizes) before anything is downloaded, confirmation of the exact list, MD5 check of every file, version = source,
  download date and accession fingerprint (version source `download`); no personal data sent.
- Validated with real FastANI and skani on NCBI RefSeq *Staphylococcus* type strains (*S. aureus* NCTC 8325 → *S.
  aureus*, consistent with MLST ST8; without the *S. aureus* reference → no reference within the boundary) and on
  *E. coli*/*Shigella* (ambiguous, two species above 95 %); the SYNTHETIC genome → no reference.
- **Not validated**: Mash and sylph against the published RefSeq sketches or GTDB databases (only on three-genome test
  databases); GTDB-Tk (no reference data or memory here: its classification never ran); Mash `screen` and skani
  `search` against pre-sketched databases are not offered; the linux-aarch64 environments were solved, not
  installed; the Docker image was not built.

**Next** (after 5D): species-specific typing (5E, below); InterProScan protein domains, BLAST searches of chosen sequences and Kraken2 read classification remain after Phase 5.

## AMR genes and Bakta CDS (5D1) ✅

- **AMRFinderPlus 4.2.7** from a pinned Bioconda environment (locks for linux-64 and linux-aarch64): adapter with
  every option checked against its `--help` and passed explicitly, parsers for its report and `--mutation_all`
  (real output on S. aureus N315 and a derived input; constructed rows for HMM, POINTN, StxTyper and protein
  contig-end cases), the organism proposed from the species identification by the wiki's table.
- **Database kind `amrfinderplus` downloadable**: dated releases listed from NCBI's folder for the installed minor
  version, a plan with the files and sizes, download after confirmation with each file's SHA-256 recorded (NCBI
  publishes no checksums), indexing with `amrfinder_index`, AMRFinderPlus's own `--database_version` check; the copy
  inside a Bakta database detected and registered read-only only when this AMRFinderPlus reads it. Release
  2026-08-07.1 installed here through that mechanism.
- **Job `amr_detection`** (nucleotide or combined with a Bakta/Prokka annotation), table `amr_results` (one row
  per element, migration `e4b7c9a2d6f8`), the Genomic analysis tab (summary by class, method badges, point
  mutations apart, the genotype-is-not-phenotype note), the project's presence/absence matrix and CSV, report
  sections, guide entries (`amr`, `amr_methods`, `point_mutation`, `genotype_phenotype`).
- **Circular map and Genome Explorer**: the AMR and virulence rings are drawn from the assembly's most recent run
  (with legend, tooltips and the link to the annotated gene); the explorer has an AMR/virulence track.
- **Bakta with CDS**: Bakta 1.12.2 from a Bioconda environment with all its programs (AMRFinderPlus 4.2.7, DIAMOND
  2.2.8, BLAST+ 2.17.0, a working PILER-CR 1.06, tRNAscan-SE 2.0.13); the light database's AMRFinderPlus copy is
  too old for AMRFinderPlus 4.2.7, so ARVA gives Bakta a view of its database with an ARVA-installed AMRFinderPlus
  release in its place. Validated on S. aureus N315: 2,592 CDS against 2,657 protein-coding CDS in NCBI's RefSeq
  annotation. linux-aarch64 has no Bakta lock (Bioconda has no BLAST+ 2.17.0 there): arm64 images keep the PyPI
  Bakta without CDS. The PyPI Bakta environment of the development system was removed.

Not validated here: the linux-aarch64 AMRFinderPlus environment (solved, not installed); point mutations on real
mutants (the gyrA S84L case is a constructed edit of N315); StxTyper's operon calls (no E. coli with stx was run);
the Bakta full database.

## Plasmids, mobile elements and virulence factors (5D2) ✅

- **Tools from pinned Bioconda environments** (scripts/conda_locks.py; installs now hard-link files from the package
  cache and skip the packages' post-link scripts, because MOB-suite's runs `mob_init`, a download with TLS
  verification off): ABRicate 1.4.0 (linux-64 and linux-aarch64 locks), MOB-suite 3.1.9 with BLAST+ 2.15.0 and
  IntegronFinder 2.0.6 (linux-64; Bioconda has no BLAST+ < 2.16 or HMMER <= 3.3.2 for linux-aarch64), ISEScan 1.7.3
  (linux-64) and geNomad 1.13.0 (both). Adapters with every option checked against `--help` (or, for ISEScan and
  geNomad, their source) and passed explicitly.
- **Databases**: MOB-suite's database 3.1.8 in the download catalogue (Zenodo 10304948, MD5 checked), prepared by ARVA
  as `mob_init` would without running it (BLAST indexes, Mash sketch, ete3's taxa.sqlite from a dated NCBI taxonomy
  archive the user confirms, its SHA-256 recorded; the 1.6 GB reference FASTA kept only on request) and installed
  here through that mechanism (1.41 GB); ABRicate's bundled VFDB and PlasmidFinder recorded read-only (`abricate`
  variant of their kinds), never updated by `abricate-get_db`; geNomad's database 1.9 paired with geNomad 1.10–1.13
  by its `releases.txt`.
- **Jobs `mobile_elements`** (MOB-suite, PlasmidFinder, IntegronFinder, ISEScan, geNomad) and **`virulence_screen`**
  (VFDB), tables `mobile_element_results` and `virulence_results` (migration `f5a8c3d1b7e9`), API routes, the Genomic
  analysis tab (contig table with MOB-suite's call, replicons, relaxase, mobility, PlasmidFinder hits, integrons, IS
  elements, viruses and the assembler's circularity side by side; run cards by category; the virulence card with VFDB
  and AMRFinderPlus rows by source), the project's columns, report sections with methods and limitations, guide
  entries (`plasmid`, `replicon`, `mobile_element`, `virulence_factor`, `vfdb`).
- **Circular map and Genome Explorer**: the mobile-element ring is drawn (no longer "Phase 5"), with a VFDB ring next
  to AMRFinderPlus's virulence ring and MOB-suite's plasmid contigs coloured on the sequence ring; VFDB and
  mobile-element tracks in the explorer.
- **Validated** with real runs on NCBI's S. aureus N315 and plasmid R388 and on ARVA's SYNTHETIC genome: MOB-suite,
  PlasmidFinder and VFDB through ABRicate, IntegronFinder (results in *Scientific methods*).

Not validated here: ISEScan and geNomad (their environments, and geNomad's database, did not fit the test machine's
disk; parsers tested on constructed files and every run is labelled as not validated); the linux-aarch64
environments of ABRicate and geNomad (solved, not installed); the Docker image (not built).

## Species-specific typing: S. aureus (5E) ✅ — Phase 5 complete

- **Typing-module framework** (`app/services/typing_modules.py`): a module declares the taxa it applies to (species
  names from species identification, MLST scheme names), its steps (tool and database kind, or data bundled with the
  tool) and its guide entries. For each assembly the Genomic analysis tab shows the module's applicability
  (applicable, conflicting, not applicable, no evidence, with the evidence), and per step whether the tool and the
  database are here and how to install or register them. A module the evidence does not support runs only with an
  explicit override, which the result records. Results go to `typing_results` (migration `b8d3f1a6c2e4`), one row per
  step and job (`species_typing`).
- **S. aureus module**: SCCmec with sccmec 1.2.0 (types I–XV, subtypes from whole cassettes; ccr complexes and mec
  classes from the schema's aliases; per-target hits), spa with spaTyper 0.3.3 and the Ridom SpaServer files the user
  downloads and registers (kind *spa types*; never shipped; "new repeat succession" for unknown successions), agr with
  AgrVATE 1.0.2 in MUMmer mode (group I–IV, match score, agrD, variants, the extracted share of the reference operon).
  A summary card sets them beside MLST and AMRFinderPlus's mecA/mecC, PVL, tst, enterotoxin and exfoliative toxin
  genes, each with its source, cross-checks mecA/mecC, and builds the shorthand (e.g. ST8-MRSA-IVa, t008, agr I,
  PVL+) from determined parts only, marking uncertain parts with "?". Project table with CSV, report sections (HTML,
  JSON, CSV), guide entries `sccmec`, `spa_typing`, `agr`, `staph_typing_summary`.
- **Pinned tools**: sccmec and spaTyper have linux-64 and linux-aarch64 locks; AgrVATE linux-64 only (snippy cannot be
  solved for linux-aarch64). spaTyper's bundled copies of the Ridom files are deleted at installation.
- **Validated** on NCBI's S. aureus N315 (sccmec II/IIa, spa t002, agr II; mlst ST5) and USA300_FPR3757 (IV/IVa, t008,
  agr I, PVL+ by AMRFinderPlus; mlst ST8), and ARVA's SYNTHETIC genome (not typeable); spa typing with the Ridom
  files downloaded on 2026-11-02 (not kept) and with CONSTRUCTED Ridom-format files in the tests.
- Test storage: every run of the API suite now removes its storage folder, also when stopped by SIGTERM or SIGHUP;
  a folder left by a SIGKILL is removed by the next run.

Not validated here: the linux-aarch64 environments of sccmec and spaTyper (solved, not installed); AgrVATE's usearch
mode (needs a binary ARVA does not install); frameshift detection on a real agr-defective genome; the Docker image
(not built).

### What remains after Phase 5

- InterProScan (protein domains) and BLAST search; Kraken 2 read classification.
- Validation of ISEScan and geNomad with real runs (their environments and geNomad's database did not fit the test
  machine), and of GTDB-Tk (its data and memory needs).
- Other species modules on the same framework: Klebsiella pneumoniae (Kleborate), E. coli serotyping, Salmonella
  (SISTR), with their own validation genomes.

## Comparative genomics core (6A) ✅

- **Comparison sets** (`comparison_sets`, `comparison_members`, `comparison_results`, migration `c4e7a2d9f1b3`):
  named, reusable selections of 2 to 200 assemblies from any sample of any project (polished or not), in an order and
  with a label per genome, kept in one project (its jobs, results and report section). Results keep a snapshot of the
  genomes they compared (labels, contigs SHA-256), so a set can change without losing them.
- **ANI matrix** (`comparative_ani` job): skani 0.4.0 `triangle -E` (every pair once; default) or FastANI 1.34
  all-vs-all (`--ql`/`--rl`, both directions), every option passed explicitly; unreported pairs stay empty. Heatmap
  ordered by average-linkage (UPGMA) clustering of 100 − ANI, labelled as similarity clustering, not a phylogeny;
  table and CSV.
- **Whole-genome alignment** (`comparative_alignment` job, up to 12 genomes in a chosen order; the first is the
  reference): minimap2 2.26 `-x asm5|asm10|asm20 -c` or NUCmer 3.1 (`--mumreference|--mum|--maxmatch -b -c -g -l`) with
  `show-coords -rclTH`, every genome against the reference and each against the next; dnadiff 1.3 against the
  reference (report counts, show-diff rows from `.rdiff`/`.qdiff` with coordinates, classified exactly as dnadiff
  counts them). Interactive dot plot (contig boundaries, strand colours, zoom), synteny plot across the order (links
  coloured by identity), conservation along the reference (ARVA's window summary of the blocks), structural
  differences table with links into the Genome Explorer of annotated genomes; SVG/PNG exports; CSV of blocks,
  conservation windows and differences; the tools' own files.
- **Report**: a comparative report per set (HTML with the heatmap and conservation strips, JSON) and a "Comparative
  genomics" section in the sample report; guide entries `ani_matrix`, `genome_alignment`, `synteny_plot`,
  `structural_differences` (EN + ES). The sidebar's Comparative genomics area is live.
- **Validated** on four NCBI RefSeq genomes (S. aureus N315, Mu50, USA300_FPR3757; S. epidermidis ATCC 12228;
  `workflows/tool-adapters/tests/fixtures/comparative/README.md`): skani 99.90 / 98.97 / 98.86 % between the S. aureus
  strains and no reported pair with S. epidermidis; dnadiff N315–Mu50 5/8 relocations, 4/2 inversions and 29/40
  inserted regions (59,724 / 123,208 bases), which ARVA's reading of `.rdiff`/`.qdiff` reproduces exactly; and on
  ARVA's SYNTHETIC genome (identical-genome edge case).

Not validated here: FastANI all-vs-all through the job (its adapter and parser are tested on a real all-vs-all
output), linux-aarch64, the Docker image (not built), the Genome Explorer links on annotated real genomes (no Bakta
run on these genomes here). Not in 6A: the Genome Region Explorer (gene neighbourhoods), locus comparison, BLAST.

## Genome Region Explorer and Custom Gene Investigation (6B) ✅

- **Tools**: BLAST+ 2.12.0 (apt `ncbi-blast+`, already present), MAFFT 7.505 and FastTree 2.1.11 (apt), IQ-TREE 3.0.1
  (pinned Bioconda lock `docker/conda-locks/iqtree`, linux-64 and linux-aarch64; the apt package pulls about 100 MB of
  MPI/ROCm libraries). Adapters `arva_tools.blast`, `mafft`, `phylo` (IQ-TREE, FastTree), options checked against the
  usage texts; minimal tree adapters that phase 7 extends.
- **Region Explorer** (`region_explorer` job on a comparison set, up to 20 genomes): a gene (name, locus tag, product,
  or an AMR / virulence hit) or coordinates, a window of 1-50 kbp on each side; the homologue in each genome by blastp
  on its annotated proteins (or blastn of the gene when the gene is not a CDS or the genome is not annotated), best
  hit above explicit thresholds (default 70 % identity over 70 % of both proteins, so paralogues stay out). Homology
  groups by all-against-all blastp (single linkage), blastn identity bands between neighbouring tracks, AMR / virulence
  / mobile-element marks from each genome's latest runs. Interactive figure (hover, click to detail and Genome
  Explorer, reorder, flip, labels) exported as SVG, PNG and vector PDF with legend and caption; feature CSV.
- **Custom Gene Investigation** (`gene_investigation` job): saved queries (`gene_queries`, migration `d7a3e5c1f9b2`:
  pasted or uploaded FASTA, validated and size-bounded, or an annotated feature's protein / nucleotide), blastn or
  tblastn (code 11) on every chosen genome's contigs, ARVA's chaining into complete / partial / split matches with
  explicit identity, coverage, complete-coverage, e-value and gap thresholds, contig-edge flags, the annotated gene each
  match overlaps, mobile elements within a chosen distance (latest 5D runs) and MOB-suite plasmid contigs; optional
  MAFFT alignment (L-INS-i or FFT-NS-2; exported FASTA) and IQ-TREE (ModelFinder, UFBoot) or FastTree gene tree
  (Newick, drawn and exported); "compare neighbourhoods" opens the Region Explorer on a match.
- **Report** sections for both analyses (HTML with the neighbourhood figure, hits tables, the tree in Newick, every
  command), hits and neighbourhood CSV, guide entries `region_explorer`, `gene_investigation`, `gene_tree` (EN + ES).
  Every view, the guide and the report state that similarity alone does not show horizontal transfer.
- **Validated** on NCBI RefSeq S. aureus MW2, MSSA476, N315 and USA300_FPR3757 (`fixtures/region/README.md`): the seh
  protein (WP_000608674.1) is found complete at 100 % identity in MW2 and MSSA476 only; at 30 % identity the
  superantigen paralogues of all four genomes appear (partial and split matches) and IQ-TREE builds their tree; the
  Region Explorer on Prokka annotations of MW2, MSSA476 and N315 draws the seh neighbourhood in MW2 and MSSA476 and
  reports no homologue in N315 and USA300. API tests on the annotation fixture genome cover reverse-complemented
  genomes, unannotated genomes, links, groups, mobile elements nearby and the exports.

Not validated here: Bakta annotations as Region Explorer input (Prokka was used), AMR / virulence marks on real runs
(no AMRFinderPlus or ABRicate run on these genomes in this environment), linux-aarch64, the Docker image (not built),
IQ-TREE runs on large alignments (hundreds of sequences). Prokka's Debian database names the seh locus "sep_1"
(enterotoxin P): gene names are the annotator's, which is why a curated FASTA query is the reliable way to ask for a
gene.

## Pangenome (7A) ✅

- **Tools**: Panaroo 1.8.1 (pinned Bioconda lock `docker/conda-locks/panaroo`, linux-64 and linux-aarch64; in the
  Docker image's conda-tools stage) validated on real genomes; PPanGGOLiN 2.3.2: lock, adapter, parsers and job path,
  not installed (about 1 GB) and not validated. Every Panaroo option ARVA passes was checked against its usage text and
  source, including the mode-dependent values its clean mode sets for the number of genomes (computed and passed
  explicitly) and `--length_outlier_support_proportion`, whose help says 0.01 while the code uses 0.1 (ARVA passes 0.1).
- **Job** `pangenome` on a comparison set (3-200 genomes, each with a Bakta or Prokka annotation with CDS): the plan
  shows each genome's annotator, version and database and warns when they differ; the worker re-checks each GFF3's
  SHA-256 and its ##FASTA section, stages them as `g1..gN` and runs Panaroo (strict / moderate / sensitive; optional
  MAFFT alignment of core or all families). The result is a `comparison_results` row (`analysis` "pangenome"; no new
  table or migration) with `pangenome.json` and `members.jsonl` beside Panaroo's own files.
- **ARVA's summaries** (`arva_core.pangenome`): core / soft core / shell / cloud with the thresholds chosen (default
  99 / 95 / 15 %, Panaroo's summary thresholds; Panaroo's own counts kept beside them), the family-frequency
  distribution, pan and core accumulation curves over random genome orders (number and seed stated), a Jaccard UPGMA
  ordering of genomes for the heatmap (labelled not a phylogeny), per-group statistics and exploratory associations
  with a metadata field (Fisher's exact test, Benjamini-Hochberg, Wilson and Woolf intervals; no lineage correction,
  stated).
- **Interface**: Pangenome dialog and result view in the Comparative genomics area: category tiles, curves,
  distribution, accessory heatmap, family table with search and category filter, family explorer (members with
  locations, flags, lengths, refound genes, neighbouring families, Panaroo's alignment when made, FASTA nt/aa, link to
  the Region Explorer), metadata groups and associations; exports: families CSV, presence/absence Rtab with labels,
  Panaroo's files. Report section (HTML with the curve figure, JSON) and a pangenome table in the sample report; guide
  entries `pangenome`, `pangenome_curves` (EN + ES).
- **Validated** with Panaroo 1.8.1 on five NCBI S. aureus genomes (N315, Mu50, USA300_FPR3757, MW2, MSSA476) annotated
  with Bakta 1.12.2 (light database 6.0): 3,090 families, 2,310 in all five; ARVA's categories reproduce Panaroo's
  summary_statistics.txt exactly; a three-genome run end to end through the API.

Not validated here: PPanGGOLiN (not installed), Prokka annotations as Panaroo input on real genomes (the Bakta GFF3
was used; Prokka's GFF has the same layout), `-a pan` alignments through the job, linux-aarch64, the Docker image (not
built), large sets (hundreds of genomes).

## Phylogeny and Tree Explorer (7B) ✅

- **Tools**: IQ-TREE 3.0.1 (its pinned lock, from 6B) with ModelFinder, UFBoot (`-B`) and SH-aLRT (`--alrt`), `-fconst`
  and `+ASC` checked against its usage text and real runs; FastTree 2.1.11 (apt); SNP-sites 2.5.1 (apt `snp-sites`,
  about 80 KB). IQ-TREE 3.0.1 aborts on `-m MFP+ASC` (a ModelFinder assertion, reproduced with 1 and 4 threads), so
  ARVA asks for a stated model with +ASC.
- **Job** `phylogeny` on a comparison set, from the set's own results: Panaroo's core-genome alignment (all core genes
  or Panaroo's entropy-filtered set), its SNPs (SNP-sites; constant sites added back with `-fconst` and SNP-sites'
  counts, or `+ASC` on A/C/G/T-only columns, or no correction with a warning), one aligned gene family, a gene
  investigation's MAFFT alignment, or an ANI matrix. Methods: IQ-TREE, FastTree, or neighbour joining computed by ARVA
  (p or Jukes-Cantor distances with pairwise deletion, or 1 − ANI/100; always labelled a distance tree, and the ANI
  one a similarity dendrogram). The source file is re-checked against its recorded SHA-256 and sequences renamed
  s1..sN. Results are `comparison_results` rows (`analysis` "phylogeny") with the tools' files, `phylogeny.nwk` and
  `phylogeny.json`; the rooting and display live in the new table `phylo_tree_views` (migration `e8b4f2a6c3d1`).
- **ARVA's tree operations** (`arva_core.phylo`): midpoint and outgroup rooting that keep supports on their
  bipartitions, Robinson-Foulds distance on shared leaves (checked against IQ-TREE's `-rf`), neighbour joining
  (Studier-Keppler), alignment statistics; Newick reading of "SH-aLRT/UFBoot" labels.
- **Tree Explorer** (own SVG, no extra library): rectangular and circular layouts, zoom (wheel, buttons) and pan,
  collapse clades, colour clades, colour leaves by a field, up to 12 metadata bands (sample type, host, origin,
  organism, year, MLST, custom fields, AMR genes of the latest AMRFinderPlus run, pangenome family presence), support
  values with a threshold, branch lengths, aligned labels, ladderize, scale bar, search, patristic distance between
  two leaves, root on a clade or leaf, comparison with another tree (RF, differing bipartitions dashed), exports SVG,
  PNG (3×), vector PDF and Newick (rooted or as inferred); the view is saved per tree. A "Gene tree" button in the
  pangenome family explorer starts a tree of that family.
- **Reports**: a phylogenetic report per tree (figure, source and checksum, method, model, supports, settings,
  commands, files with SHA-256, limitations, references) and a phylogeny section in the comparative report; guide
  entry `phylo_tree` (EN + ES).
- **Validated** on the five NCBI S. aureus genomes of 7A (Panaroo `-a core`: 2,310 core genes, 2,186,160 columns,
  30,888 variable): IQ-TREE on the core alignment and on its SNPs with `-fconst` (TIM2+F+I, 100/100 supports),
  FastTree on the SNPs and ARVA's neighbour joining on Jukes-Cantor distances give the same topology
  (N315, Mu50 | USA300 | MW2, MSSA476); ARVA's RF equals IQ-TREE's `-rf`. Not validated: trees with hundreds of
  genomes (FastTree took 6 min 43 s on the 2.2 Mb × 5 alignment); the SNP-site FASTA of 8A's SNP matrix is not yet
  offered as a tree source.

## Variant analysis and consolidated mobilome (8A) ✅

- **Tools**: bcftools 1.19 (Ubuntu `bcftools`, already installed; added to the Docker image, where bookworm ships
  1.16), with BWA 0.7.17, minimap2 2.26 and samtools 1.19.2 (from 3B2). New adapter `arva_tools/bcftools.py`
  (registered as `bcftools`): mpileup, call, norm, filter, csq and index, every option checked against the usage texts
  saved in `fixtures/variants`. minimap2 and BWA gained read groups (`-R`), samtools `faidx` and a depth with quality
  floors. Not integrated: BWA-MEM2 (not in Ubuntu's archive), FreeBayes (not in Ubuntu's archive) and Snippy as
  callers; Snippy 4.6.0 and FreeBayes 1.3.6 exist on this machine only inside AgrVATE's environment and were used
  once to cross-check ARVA's calls (below).
- **Facts confirmed** (bcftools 1.19 usage, manual and `csq.c`): the `-X` profiles are shorthands (ont = `-B -Q5
  --max-BQ 30 -I`, pacbio-ccs = `-D -Q5 --max-BQ 50 -F0.1 -o25 -e1 --delta-BQ 10 -M99999`); ARVA writes them out.
  Without `--ploidy` bcftools assumes diploid; `--ploidy 1` makes every site haploid. mpileup skips reads of pairs
  that are not properly paired unless `-A`. csq needs an Ensembl-style GFF3 and translates with the standard code
  only: it reports start_lost only for ATG starts, so ARVA marks changes of GTG/TTG start codons.
- **Job** `variant_calling` on a sample: technology (Illumina → BWA-MEM; Nanopore → minimap2 map-ont, no indels;
  PacBio HiFi → minimap2 map-hifi), reference (any ARVA assembly, or a genome of a registered reference collection;
  its SHA-256 is recorded and checked again by the worker), reads by role, filters (Snippy 4.6.0's QUAL 100, depth
  10, alternative-allele fraction 0.9, MAPQ 60, stated as such), effects with bcftools csq when the reference has an
  ARVA annotation, alignment kept on request. New table `variant_calls` (migration `f3c9a1e7b5d2`, on `e8b4f2a6c3d1`;
  upgrade, downgrade and upgrade checked); the records stay in the run's `variants.json.gz` next to the VCF.
- **Views**: per sample on the Genomic analysis tab (counts, callable fraction, mapped reads, genomic distribution,
  depth and alternative-allele fraction at variable sites, effects, filterable records, VCF/index/CSV/GFF3/BAM
  downloads); per project the most recent run per sample and reference, the SNP matrix and pairwise SNP distances
  (heatmap, CSV, SNP-site FASTA, HTML report); a Variants track in the Genome Explorer of the reference; report
  sections in the sample report.
- **Consolidated mobilome**: per sample and project, the plasmids (MOB-suite), IS elements (ISEScan, MOB-suite's
  repetitive elements), integrons and geNomad calls of the most recent runs, with the AMRFinderPlus and VFDB genes
  inside them, near them (distance chosen, 10 kb by default) or on a plasmid's contigs. Labelled as co-location only.
- **ISEScan 1.7.3 validated** (installed from its lock, about 350 MB of new disk after hard-linking): a real run on
  S. aureus N315 (23 IS elements, 9 min with 3 threads) is now the parser's fixture. geNomad stays not validated
  (its database and environment did not fit the disk).
- **Validated** on SIMULATED reads with known truth (planted SNPs and indels recovered; the polishing draft's 7
  substitutions, 4 insertions and 5 deletions found in the API test) and on three real public Illumina read sets
  (ENA DRR250760, DRR257875, DRR272507) against S. aureus USA300_FPR3757: 161 to 50,557 passing variants per
  sample, 68–122 s per run with 4 threads; on DRR250760 ARVA's passing SNPs and Snippy 4.6.0's substitutions share
  45,852 sites (Jaccard 0.89) (`fixtures/variants/README.md`). Not validated: Nanopore and HiFi calling on real
  reads (only simulated), reference-collection genomes as references in a real run, geNomad.

## Batch processing and Workflow Builder (8B) ✅

- **Editor**: `@xyflow/react` 12.12.0 (React Flow; MIT, maintained by xyflow, pinned exactly) for the node editor:
  it gives custom nodes with several typed handles, connection validation before an edge is drawn, drag-and-drop,
  minimap and keyboard deletion without ARVA re-implementing a canvas. Nodes have typed ports (long / short reads,
  assembly, annotation, comparison set, alignment, tree) and a scope (per sample, or per run through the comparison
  set's collection input); incompatible connections are refused with the reason. Graph rules live in
  `scientific-core/arva_core/workflow.py` (also used by the API on every save) and are mirrored for the editor in
  `apps/web/src/lib/workflows.ts`.
- **Nodes = the analyses' own actions**: each node kind maps to the POST route of its analysis
  (`app/services/workflow_nodes.py`): fastp, Filtlong, Flye, SPAdes, Unicycler, polishing (Racon / Pilon / hybrid),
  QUAST, Bakta, Prokka, MLST, species, AMRFinderPlus, virulence (ABRicate VFDB), plasmids and mobile elements, a
  comparison set of the run's genomes, ANI, whole-genome alignment, pangenome, phylogeny and gene investigation. The
  parameter panel is built from the same request models as the dialogs (their JSON schema) and the API checks every
  parameter with them; defaults are stored explicitly. Each node becomes an ordinary analysis job with its usual
  provenance; Bakta's skipped steps come from its preview at launch, and the locus-tag prefix from the sample's code
  unless set.
- **Workflows**: versioned (`workflows`, `workflow_versions`), duplicated, imported, exported as a reproducible JSON
  definition (every parameter, SHA-256 of the graph, tool versions, Bioconda lock and installed-environment
  checksums). The twelve workflows of spec §25 are predefined; those whose tools are missing here are shown as
  unavailable with the tool, and options that depend on the data (Flye's read type, Racon's preset) are left to the
  user. **No Nextflow DSL2 export**: a node is not only a command but ARVA's checks, launch-time choices and record
  keeping, which a Nextflow process could not reproduce faithfully; the run export lists every executed command.
- **Batch queue** (`batch_runs`, `batch_items`; migration `a7d2c5e9b1f4` on `f3c9a1e7b5d2`, upgrade, downgrade and
  upgrade checked): priority, jobs at once per run, threads and memory per job reserved against the performance
  profile's budget, retries of jobs that fail while running (never of refused launches), pause, resume (re-queues
  failed, cancelled, skipped and interrupted steps; completed ones keep their results), cancel; lost tasks after a
  restart are ended and resumable. The queue advances when a job ends, a job is cancelled, a run changes and the
  worker starts.
- **Views**: runs dashboard (active runs, queue, reserved threads/memory, global progress chart), run page (progress on
  the graph, per-sample grid, run times per sample, error summary with the run's error-log entries, consolidated CSV,
  JSON export with every job's commands, HTML report), comparison of two runs (parameter differences, statuses,
  versions, times, recorded output values), and on each sample the timeline's **branches**: changing a step's
  parameters creates a new run that reuses the unchanged upstream results and runs the rest as new jobs, never
  overwriting earlier results.
- **Validated** with the real queue and two workers on SIMULATED genomes (`scripts/make_synthetic_genome.py`, seeds
  1–3, 30x): Flye 2.9.3 → Racon 1.5.0 → QUAST 5.2.0 on three Nanopore samples and fastp → SPAdes 3.15.5 → QUAST on
  three Illumina samples (all completed, at most two jobs at once, the higher-priority run served first), and a branch
  with two Racon rounds that reused the Flye jobs. Failures seen and reported as such: SPAdes stops on the 5x example
  reads (`Invalid kmer coverage histogram`) and Flye assembles nothing from them. Not run through a workflow
  here: the annotation, characterisation, pangenome, phylogeny and gene-investigation nodes (they call the same API
  actions as the dialogs, already tested in their parts; the API tests cover the comparison-set node and the queue
  with substitute launchers), real-data batches of hundreds of samples, and more than two workers.

## Discover, full reports, ARVA Assist and accounts (8C) ✅ — Phase 8 complete

- **ARVA Discover** (`scientific-core/arva_core/stats.py`, `discover.py`; `app/services/discover.py`; page
  `/discover/:projectId`): exploratory analyses over a project's stored results and metadata. Fields: species, ST,
  clonal complex, origin, host, sample type, year, organism and every custom metadata column (phenotypes); features:
  AMRFinderPlus genes, VFDB genes and PlasmidFinder replicons from each sample's latest run (a sample without a run is
  "not searched", left out of the test, never "absent"), and any field as one-hot features. Analyses: gene–metadata
  associations (Fisher's exact test, Benjamini-Hochberg q, Wilson shares, Newcombe difference, Woolf odds ratio with
  Haldane-Anscombe correction; a lineage-stratified Cochran-Mantel-Haenszel test with the Mantel-Haenszel odds ratio
  and Robins-Breslow-Greenland interval, which reports when group and lineage coincide), co-occurrence network
  (pairwise Fisher, q, phi, Jaccard), distribution by lineage, clustered presence heatmap (UPGMA on Jaccard), PCA when
  at least 3 complete samples and 2 varying features exist. Every result carries its sample sizes, the correction, the
  caveats (not causal, phylogenetic dependence, multiple testing, unsearched samples) and the label "exploratory, not
  confirmatory"; CSV export. Statistics tested against SciPy 1.18.1 (installed in the API venv as a test dependency)
  and R's documented `mantelhaen.test(UCBAdmissions)` and Newcombe's published example.
- **Full project report** (`GET /projects/{id}/report?format=html|pdf|json|csv&lang=en|es`,
  `app/services/project_report.py`): metadata, read QC, assembly, species and typing, AMR matrix and prevalence
  chart, virulence, replicons, comparison sets with their ANI / alignment / pangenome / phylogeny results and links to
  the comparative and phylogenetic reports, methods (tools, versions, databases, citations from the adapters'
  `ToolInfo`) and limitations. HTML and PDF follow the interface language (server-side EN/ES catalogue with a parity
  test); PDF rendered by **WeasyPrint 66.0** (PyPI, BSD-3-Clause; Pango from the system) with every external resource
  refused. Archived under `reports/<project>/`.
- **ARVA Assist** (`app/services/assist.py`): an integration point only, disabled by default. A provider is code that
  implements `AssistProvider` and is registered with `assist.register()`; ARVA bundles none and calls none in tests
  (a fake provider). Settings → ARVA Assist (administrators): provider, endpoint (https, or http on this computer
  only), model, key (owner-only file `<storage>/secrets/assist-key`, never returned). The context builder sends fixed
  instructions, the question, ARVA Guide excerpts and the project report's data without personal fields; sequences
  only with per-request consent. `assist_requests` logs exactly what was sent (and its SHA-256), the answer or the
  failure.
- **Accounts** (optional, `ARVA_AUTH_ENABLED=true`): users with roles admin / analyst / viewer, Argon2id hashes
  (**argon2-cffi 25.1.0**), first administrator through a one-time setup token in `<storage>/secrets/`, server-side
  sessions (HttpOnly SameSite=Strict cookie), CSRF token on every change, lockout after repeated failures, project
  owners and sharing (read / write), access control on every route (`app/api/access.py`: path, query and JSON-body ids
  resolved to projects; unknown route parameters refused for non-administrators, enforced by a test over every
  route), unscoped lists filtered to the caller's projects, and an audit log of sign-ins, account and sharing changes,
  refusals, changes and report downloads (route templates only). Migration `b6e2d4f8a1c3` on `a7d2c5e9b1f4`
  (upgrade, downgrade, upgrade checked).
- **Screenshots** were taken on six NCBI RefSeq genomes (five S. aureus, S. epidermidis ATCC 12228) with real
  mlst 2.35.0, AMRFinderPlus 4.2.7 (database 2026-08-07.1), ABRicate 1.4.0 (VFDB, PlasmidFinder) and skani 0.4.0 runs.

### What remains after Phase 8

- Discover: numeric comparisons between groups (rank tests with effect sizes), pangenome families as Discover
  features, phylogeny-aware methods (e.g. phylogenetic logistic regression, treeWAS-style tests); stratification by
  a lineage label is only a coarse correction.
- Reports: the sample report still follows English only; the per-sample sequencing, quality, assembly, annotation
  and characterisation reports are sections of it rather than separate documents; Excel export, publication-mode
  figures (size, resolution, fonts) are not done.
- Assist: no provider is included; streaming answers, tool use and guide retrieval beyond the excerpts the interface
  sends are not designed yet.
- Accounts: no single sign-on, e-mail password reset or two-factor authentication; jobs run by the worker carry no
  user; existing projects have no owner until shared.
- Validation still open from earlier parts: geNomad and GTDB-Tk real runs, PPanGGOLiN real runs, a Mac host, Docker
  image builds with the new libraries.

## Performance profiles (P1) ✅

- Host detection (`app/services/host.py`): usable CPUs (affinity, cgroup v2/v1 quota), memory (cgroup limit or
  `MemTotal`), container detection; the Mac's model, chip, performance/efficiency cores, memory, macOS version and
  Docker Desktop's allocation, read natively on macOS or passed in by `scripts/start.sh` (`ARVA_HOST_*`, validated).
- Light / Balanced / Maximum / Custom profiles (ARVA heuristics), chosen automatically by Mac family or by cores and
  memory, stored server-side, applied to every tool's default and maximum threads and to the tools with a memory
  option; tools run through `nice`; each job records its resources; SIGKILL failures name memory and what to change;
  Settings → Performance with the Docker Desktop recommendation.
- **Not yet validated on a real Mac**: the launcher and the macOS readers were tested with constructed outputs only.
  The profiles' shares are heuristics, not measurements of heat or speed.

## Interface language (P2) ✅

- The Spanish interface is Spanish throughout: forms, upload progress, history labels, units (`pb`), numbers and
  dates in the locale's format, plurals; terminology made consistent ("estadísticas de lecturas", "encabezados").
- Stable codes for the API messages shown most often (job failures, file checks, upload refusals, read-statistics
  warnings, database-manager failures, catalogue texts), translated by the interface with the English text as
  fallback; a test of the sources keeps interface text inside the dictionaries.
- Still English: the API's HTTP error details, uncoded job failures (mostly the tools' own error lines), job logs,
  the tools' own words, and the sample and comparative reports, which the API writes in English only; the full
  project report (8C) follows the interface language. See "Interface language" in `architecture.md`.

## Published container images (C1)

- `.github/workflows/images.yml` builds the API and web images for linux/amd64 and linux/arm64 (native arm64
  runner), smoke-tests them (tool detection against the locks, migrations, `/health`, the worker, the web proxy, mlst
  on NC_007795.1) and publishes them to GHCR (`<version>`, `<version>-<short commit>`, multi-architecture). GitHub
  created the packages public, linked to the public repository; their owner sets the visibility. `scripts/start.sh`
  pulls them by default, `--build` builds locally.
- Building the image for the first time showed that it had never built: Debian's `trnascan-se` is in non-free (left
  out), `spades` and `unicycler` exist for amd64 only, and the arm64 PyPI Bakta needed `isal` pinned (1.9.0 came out
  without arm64 wheels on the day of the build).
- Image architecture: on Apple silicon the amd64 image (every tool, through Rosetta) unless Docker Desktop's Rosetta
  setting is off; `--platform` chooses; Settings → Performance shows the choice, the reason, translation and the
  tools missing on that architecture. Rosetta's speed cost has not been measured on a real Mac.

## Later phases

| Phase | Scope |
|---|---|
| 3 ✅ | Assembly (Flye, SPAdes, Unicycler), QUAST, contig plots, GFA view, polishing (Racon, Pilon; Medaka added later), job cancellation and Flye resume, batch QC; Polypolish, Raven, Canu, MEGAHIT, BUSCO and CheckM2 not yet integrated (above) |
| 4 ✅ | Database Manager, annotation (Bakta; Prokka), Genome Explorer (linear and circular), annotation charts and report section |
| 5A, 5B ✅ | External storage; database kinds (register in place, download a chosen version to a chosen folder, reference genome collections, one default per kind) |
| 5C1 ✅ | Pinned Bioconda environments (micromamba, checksummed locks for linux-64 and linux-aarch64); MLST with mlst and its bundled PubMLST schemes |
| 5C2 ✅ | Species identification: FastANI and skani against reference genome collections (validated), Mash and sylph (test databases only), GTDB-Tk (not validated, memory-gated); collections from NCBI Datasets; consistency with MLST and the annotation's organism |
| 5D ✅ | AMRFinderPlus (AMR and virulence rings), Bakta with CDS; VFDB (ABRicate); plasmids (MOB-suite, PlasmidFinder) and mobile elements (IntegronFinder; ISEScan and geNomad not validated) with their rings |
| 5E ✅ | Species-specific typing framework; S. aureus SCCmec (sccmec), spa (spaTyper with the user's Ridom files), agr (AgrVATE) and the summary card |
| After 5 | InterProScan, BLAST, Kraken 2; ISEScan, geNomad and GTDB-Tk validation; Klebsiella, E. coli and Salmonella typing modules |
| 6A ✅ | Comparative genomics core: comparison sets, ANI matrices (skani, FastANI), whole-genome alignment (minimap2, NUCmer), dot plots, synteny, conservation, dnadiff structural differences, comparative report |
| 6B ✅ | Genome Region Explorer (gene neighbourhoods across genomes, SVG/PNG/PDF figures) and Custom Gene Investigation (BLAST+, MAFFT, IQ-TREE / FastTree gene trees) |
| 7 ✅ | Pangenome (Panaroo; 7A), phylogeny (IQ-TREE, FastTree, SNP-sites, neighbour joining) and Tree Explorer (7B) |
| 8A ✅ | Variant analysis (BWA-MEM / minimap2 + bcftools, csq effects, SNP matrix and distances, Variants track) and the consolidated mobilome; ISEScan validated |
| 8B ✅ | Workflow Builder (typed ports, versions, predefined workflows, JSON export; no Nextflow export, see above), batch queue (priority, concurrency within the profile's budget, retries, pause, resume, cancel), run dashboards and comparison, timeline branches |
| 8C ✅ | ARVA Discover (associations with lineage stratification, co-occurrence, heatmap, PCA), full project report (HTML/PDF/JSON/CSV, EN/ES), ARVA Assist integration point (no provider bundled), optional accounts with roles, sharing, CSRF and audit log |
