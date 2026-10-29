<p align="center">
  <img src="apps/web/public/arva-logo.png" width="96" alt="ARVA logo">
</p>

<h1 align="center">ARVA</h1>
<p align="center"><b>Integrated Genomic Discovery Platform</b><br><i>From sequence to insight.</i></p>

ARVA is a local-first platform for analysing sequencing data, starting with bacterial
genomics. It is built around six principles: **scientific integrity** (every result comes
from a real computation with recorded provenance), **beginner friendliness**, **expert
control**, **visual first**, **reproducibility** and **modularity**.

> **Status: Phase 4 — Annotation, complete (v0.2.0 + Phases 3 and 4).** Projects, samples, FASTQ/FASTA import
> with validation, read statistics, SeqKit cross-checks, FastQC reports, fastp/Filtlong filtering with
> file lineage and before/after comparison, long-read assembly with Flye, short-read and hybrid assembly with
> SPAdes and Unicycler, polishing with Racon and Pilon (with a before/after comparison), assembly views and QUAST
> evaluation, job cancellation and Flye resume, batch QC across a project, the Database Manager, genome annotation
> with Bakta and Prokka, the Genome Explorer (linear browser and circular map), annotation charts, analysis history,
> reports and the ARVA Guide are functional: from raw reads to an assembled, annotated genome. On Ubuntu 24.04
> Bakta cannot predict CDS (its AMRFinderPlus and DIAMOND requirements are not met there), so Prokka is the validated
> CDS annotator. Later modules (AMR, virulence and mobile elements in Phase 5, among others) are listed in the
> interface as *planned* and never show simulated results. See [docs/roadmap.md](docs/roadmap.md).

## What works today

| Capability | Details |
|---|---|
| Projects & samples | Create, edit, search; rich sample metadata (organism, host, origin, dates, technology, run, notes) |
| Raw data import | Drag-and-drop files or folders; bulk import with sample IDs inferred from file names; import from a server folder without the browser; free-space checks; content-based FASTQ/FASTA + gzip detection; SHA-256 checksums; duplicate detection; R1/R2 recognition; originals stored read-only |
| Sample metadata tables | Import from CSV or Excel (.xlsx) with a row-by-row preview, English/Spanish column names, explicit date handling, one-transaction apply and an import history with the file's SHA-256; export to CSV/Excel protected against formula injection; header-only template |
| Read headers | Platform hints (Illumina, Oxford Nanopore, PacBio) and run values read from the first read headers (NCBI SRA deflines included), with confidence and documentation source, plus an R1/R2 name check — suggestions only, never applied silently |
| POD5 raw signal | Recognised by content (truncated files flagged); run metadata — reads, signal duration, sample rate, flow cell, kit, protocol — read with the optional `pod5` library; no basecalling |
| Validation | Quick structural check at import; full record-by-record validation (with line numbers) during analysis |
| Read statistics | Reads, bases, length distribution, N50/N90, GC, ambiguous bases, Phred quality (error-probability averaging), Q20/Q30, per-position quality, reads above quality thresholds, yield by length, optional depth estimate |
| Visualisation | Interactive figures (ECharts) for reads and assemblies, with tooltips, table views and SVG/PNG export, light/dark |
| Provenance | Every run records tool, version, parameters, input checksums, environment, timings, outputs and log |
| Independent check | SeqKit summarises the same file; ARVA compares every robust metric and shows any disagreement |
| FastQC | Unmodified FastQC report (opened in a network-isolated sandbox) plus its module flags, labelled as FastQC heuristics |
| Filtering | fastp (short reads, single/paired-end: quality, N, complexity, minimum length, discard longer reads, trim to a length, fixed 5′/3′ cuts, explicit adapter sequences) and Filtlong (long reads: hard thresholds, keep percent, target bases or a target coverage computed from a user-given genome size); every threshold visible, passed explicitly and recorded; explicit confirmation required; a run that keeps no reads fails and registers nothing |
| Lineage | Filtered reads become new read-only derived files linked to their original and the producing job; originals never change |
| Before/after | Statistics for filter outputs are computed automatically; metrics table with changes (and depth when a genome size is known) and overlaid distributions; Filtlong's target outcome |
| Long-read report | NanoPlot 1.48.0 on long-read FASTQ, offline; statistics with NanoPlot's definitions, reads and bases cross-checked against ARVA, differently defined metrics shown side by side |
| Assembly | Flye (long reads), SPAdes (short reads) and Unicycler (short, long or hybrid) in an assisted New assembly dialog: the assembler that fits the sample's reads, or several strategies queued at once for comparison; reads chosen by lineage and, for SPAdes and Unicycler, by role (R1, R2, unpaired, long) with checks against the sample's technology (original or filtered copy, with their statistics), every option explained, a labelled heuristic read-type suggestion from base qualities and read headers, genome size never assumed (entered, the sample's expected size, or reads ÷ an assumed depth, recorded with its basis), advanced options collapsed, a "what this run will do" summary and explicit confirmation; options checked against the installed Flye's `--help`; stage stepper, live elapsed time and live log (auto-scroll, pause) while it runs |
| Assembly results | Contigs, total length, largest, N50/L50, N90/L90, GC, circular contigs and median coverage (ARVA's statistics; coverage and circularity are the assembler's, labelled by kind: Flye's read depth, SPAdes' k-mer coverage, Unicycler's relative depth), labelled heuristic warnings, a sortable contig table with FASTA download, five charts (length histogram, Nx curve, cumulative length, coverage vs length, GC vs coverage) with tables and SVG/PNG export, an interactive assembly-graph (GFA) explorer, side-by-side comparison of a sample's assemblies, an Assemblies table per project, and an Assembly section in the sample's HTML/JSON/CSV reports |
| Polishing | Racon (long reads, minimap2), Pilon (short reads, BWA-MEM, explicit Java heap) or both in sequence, chosen by the reads' technology; N rounds with every command recorded; each result a new assembly linked to its draft (lineage shown in the Assembly tab); before/after comparison separating direct evidence (MUMmer dnadiff and Pilon's change list: SNPs, insertions, deletions per round, bases lost at contig ends) from indirect indicators (the reads' alignment to both versions), with a chart of changes per round and optional QUAST |
| Assembly evaluation | QUAST 5.2.0 on one or more assemblies of a sample (comparison), optionally against a reference FASTA of the sample; offline, every result-changing option explicit, QUAST's metrics read by field name, its contiguity values cross-checked against ARVA's at the same minimum contig length with both definitions shown; QUAST's HTML report and Icarus viewers served sandboxed |
| Overviews | Sequencing overview per sample (every imported and derived file with lineage, read statistics, POD5 reads and signal duration, bases per file) and a QC overview per project (one row per sample: totals, N50 and quality of the largest file, pooled Q30/GC, depth only with a user-given genome size, filtering, FastQC heuristics, SeqKit check; sortable, filterable, CSV export) |
| Project QC report | MultiQC 1.35 report over the latest FastQC, fastp, SeqKit and Filtlong results of a project, run offline, every input checked; general statistics kept with units and the producing tool |
| Tools & Databases | Detected tools with version (validated or not), executable, licence, citation and install commands; ARVA never installs software |
| Database Manager | Reference databases (Bakta database 6.0, light and full) with their published size, checksum, licence and source; download only after an explicit confirmation of size, licence and free space, as a cancellable, resumable worker task with MD5 verification, safe unpacking and Bakta's folder check; register an existing folder, verify every file again (SHA-256), delete (refused while a job uses it), disk usage; jobs record the database key, version and checksum |
| Genome annotation | Bakta 1.12.2 (recommended, with a database from the Database Manager) or Prokka 1.14.6 (alternative; its author no longer maintains it) on any assembly of the sample's lineage, draft or polished: a dialog that shows every step that will run and every step that will not, with the reason (Bakta's own start-up checks repeated by ARVA, a PILER-CR crash test, the light database), each option explained (locus tag, translation table, organism, `--complete` only after confirmation, contig names), and explicit confirmation; results as tiles (CDS, tRNA, rRNA, ncRNA, CRISPR, pseudogenes, hypothetical share, coding density — *not searched* when a step did not run), charts (features by type, hypothetical vs characterised CDS, gene length distribution, gene orientation, gene density along each sequence, COG categories as reported — or a statement that none were — each with a table view and SVG/PNG export), a searchable, filterable, sortable feature table with details (evidence, cross-references linked only to checked resolvers, nucleotide and protein sequence), the annotator's files unchanged and GFF3/GenBank/FASTA/TSV exports of all or selected features, and an Annotation section in the reports with the circular map and the charts' numbers |
| Genome Explorer | A linear browser of any annotation: sequence selector with topology, ruler, zoom (buttons, wheel, keyboard), pan, region selection; genes as strand arrows coloured by feature group with a legend, intergenic regions, GC and GC skew in windows (fitted to the view or chosen), read coverage when the polishing reads were aligned to exactly these contigs (otherwise the reason), the bases when zoomed in; search by gene, locus tag, product, identifier or `contig:start-end`; a feature panel with every field of spec §11 (identifier, coordinates, orientation, predicted function, the annotator's nucleotide and protein sequences with copy, tool, version and database, evidence, links) and ARVA's checks of those sequences against the genome; region FASTA (either strand), GFF3/FASTA/TSV of the features in a region or marked one by one, and the view as SVG |
| Circular genome map | The Genome Explorer's second view: rings for the sequence, genes on each strand, a custom ring (a feature type, pseudogenes or a text), read coverage when it exists, GC content and GC skew; AMR, virulence and mobile-element rings listed as *available after Phase 5* (not drawn, no guesses); ring toggles; all sequences on one circle or chromosome and plasmids side by side; tooltips, click to open a gene's details or show it in the linear view; SVG and PNG export with the legend and caption in the figure; light and dark |
| Execution | Analyses run in a separate worker process via a Redis queue — never in the HTTP process; external tools run without a shell, with timeouts and a credential-free environment |
| Performance profiles | ARVA detects the computer (on a Mac, through `scripts/start.sh`: model, chip, performance and efficiency cores, memory, Docker Desktop's allocation) and the CPUs and memory it can actually use, and chooses Light, Balanced or Maximum (ARVA heuristics, changeable in Settings → Performance, or Custom threads and memory) so that the computer does not overheat or freeze; tools run at a lower CPU priority with the profile's threads and memory limits, every job records the resources it was given, a tool stopped for lack of memory says so and what to change, and Settings shows what to set in Docker Desktop. Not yet validated on a real Mac |
| External disk | Projects, downloaded databases and metadata backups on an external disk, existing databases (e.g. a Bakta full database) used in place read-only: the launcher checks every folder (absolute, existing, writable, still on its disk; on a Mac exFAT/FAT is warned about, via `diskutil`) and refuses to start when a disk is missing instead of letting Docker create an empty folder; a storage marker makes writes stop (503) and jobs fail cleanly if the disk goes away; daily and on-demand `pg_dump` backups of the metadata go to the disk, and `scripts/restore.sh` brings them back on another Mac. Settings → Storage shows every location. Not yet validated on a real Mac |
| Cancelling and recovery | Cancel queued or running jobs (with confirmation): the tool and every process it started are stopped within seconds, partial outputs removed and the log kept; a Flye run stopped from outside after its first stages can be resumed with Flye's own `--resume` (same reads, options, threads and version; the interrupted stage rerun from scratch) or its kept work folder discarded |
| Batch QC | Read statistics, SeqKit and/or FastQC on every sample of a project (imported or also derived files; completed results skipped unless recomputing), with a preview of exactly how many jobs each sample gets and why files are skipped; confirming creates exactly those ordinary per-sample jobs |
| Reports | HTML (figures, methods, processing steps with exact commands, limitations), CSV and JSON per sample |
| ARVA Guide | “What does this mean?” on every metric: beginner / intermediate / advanced, English & Spanish, with references |
| Analysis Timeline | Raw data → QC → Filtering → Assembly → Polishing → Annotation → Biology, per sample |

## Quick start

### Docker (recommended)

```bash
docker compose up -d --build      # on a Mac: scripts/start.sh --build (detects the Mac, see docs/installation.md)
open http://localhost:8080        # API docs: http://localhost:8000/docs
```

Services bind to `127.0.0.1` only. Data persist in Docker volumes; to keep projects and databases on an external
disk, start with `scripts/start.sh --data-dir /Volumes/<Disk>/ARVA/data --databases-dir /Volumes/<Disk>/ARVA/databases`
and add databases you already have with `--add-databases <folder>` (used in place, read-only). The launcher checks
each folder (refusing to start when a disk is missing), remembers it, and the metadata is backed up into the data
folder so the disk can move to another Mac ([External disk](docs/installation.md#external-disk-data-and-databases-outside-the-mac)).

### Local development (macOS / Linux)

Requires Python ≥ 3.11, Node ≥ 20, PostgreSQL ≥ 14 and Redis. The QC tools are optional:
`sudo apt install seqkit fastqc fastp filtlong` (Debian/Ubuntu) or
`mamba env create -f workflows/tool-adapters/environment.yml` (macOS/Linux).

```bash
createdb arva                     # or: psql -c 'CREATE DATABASE arva'
scripts/setup-dev.sh              # venv, npm install, .env, migrations
scripts/dev.sh                    # API :8000 · worker · web :5173
```

Try it with the synthetic reads in [`examples/synthetic`](examples/README.md).
Full instructions: [docs/installation.md](docs/installation.md).

## Repository layout

```
apps/
  api/              FastAPI service, SQLAlchemy models, Alembic migrations, report generation
  workers/          RQ worker entry point (executes analysis jobs)
  web/              React + TypeScript + Vite + Tailwind interface
scientific-core/    arva_core: pure-Python validation & statistics (no web/DB dependencies)
workflows/
  tool-adapters/    arva_tools: adapters for SeqKit, FastQC, fastp, Filtlong (+ conda environment)
  nextflow/         multi-step pipelines — Phase 3+
visualizations/     shared visualisation specs — planned
databases/          reference database manifests — planned
docker/             Dockerfiles and nginx configuration
docs/               architecture, installation, methods, developer guide, roadmap
examples/           synthetic example reads
scripts/            setup, dev runner, test runner, data generator
tests/e2e/          browser end-to-end test
```

## Tests

```bash
scripts/test-all.sh               # core + tool adapters + API (PostgreSQL) + web typecheck/unit
ARVA_E2E=1 scripts/test-all.sh    # also the browser golden path (stack must be running)
```

## Documentation

- [Architecture](docs/architecture.md)
- [Installation](docs/installation.md)
- [Scientific methods](docs/scientific-methods.md)
- [Developer guide](docs/developer-guide.md)
- [Roadmap & current limitations](docs/roadmap.md)
- API reference: interactive OpenAPI at `/docs` on the running API

## Privacy

ARVA runs entirely locally. Sequence data are never sent to external services.
