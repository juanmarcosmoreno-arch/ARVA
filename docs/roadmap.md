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

## Next recommended step — Phase 3 (assembly)

Integrate Flye for long-read assembly through a new adapter (and Nextflow where multi-step), QUAST
evaluation, contig statistics and plots, with the filtered or original reads selected explicitly by
lineage.

## Later phases

| Phase | Scope |
|---|---|
| 3 | Assembly (Flye first; then SPAdes/Unicycler/Raven), QUAST, contig plots, GFA view, polishing (Medaka/Polypolish) |
| 4 | Annotation (Bakta; Prokka), Genome Explorer (linear + circular), exports (GFF3, GenBank, FASTA) |
| 5 | MLST, AMRFinderPlus, virulence (VFDB), BLAST, species identification (Mash/FastANI/Kraken2/GTDB-Tk) |
| 6 | Comparative genomics: ANI, synteny, dot plots, Genome Region Explorer |
| 7 | Pangenome (Panaroo), alignments (MAFFT), phylogeny (IQ-TREE), Tree Explorer |
| 8 | Workflow Builder (Nextflow DSL2), batch processing, mobilome, variants, ARVA Discover, full reports, optional ARVA Assist, multi-user |
