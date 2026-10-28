<p align="center">
  <img src="apps/web/public/arva-logo.png" width="96" alt="ARVA logo">
</p>

<h1 align="center">ARVA</h1>
<p align="center"><b>Integrated Genomic Discovery Platform</b><br><i>From sequence to insight.</i></p>

ARVA is a local-first platform for analysing sequencing data, starting with bacterial
genomics. It is built around six principles: **scientific integrity** (every result comes
from a real computation with recorded provenance), **beginner friendliness**, **expert
control**, **visual first**, **reproducibility** and **modularity**.

> **Status: Phase 2 — Raw data and QC (v0.2.0).** Projects, samples, FASTQ/FASTA import with
> validation, read statistics, SeqKit cross-checks, FastQC reports, fastp/Filtlong filtering with
> file lineage and before/after comparison, analysis history, reports and the ARVA Guide are
> functional. Assembly, annotation and later modules are listed in the interface as *planned*
> and never show simulated results. See [docs/roadmap.md](docs/roadmap.md).

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
| Visualisation | Six interactive figures (ECharts) with tooltips, table views and SVG/PNG export, light/dark |
| Provenance | Every run records tool, version, parameters, input checksums, environment, timings, outputs and log |
| Independent check | SeqKit summarises the same file; ARVA compares every robust metric and shows any disagreement |
| FastQC | Unmodified FastQC report (opened in a network-isolated sandbox) plus its module flags, labelled as FastQC heuristics |
| Filtering | fastp (short reads, single/paired-end: quality, N, complexity, minimum length, discard longer reads, trim to a length, fixed 5′/3′ cuts, explicit adapter sequences) and Filtlong (long reads: hard thresholds, keep percent, target bases or a target coverage computed from a user-given genome size); every threshold visible, passed explicitly and recorded; explicit confirmation required; a run that keeps no reads fails and registers nothing |
| Lineage | Filtered reads become new read-only derived files linked to their original and the producing job; originals never change |
| Before/after | Statistics for filter outputs are computed automatically; metrics table with changes (and depth when a genome size is known) and overlaid distributions; Filtlong's target outcome |
| Long-read report | NanoPlot 1.48.0 on long-read FASTQ, offline; statistics with NanoPlot's definitions, reads and bases cross-checked against ARVA, differently defined metrics shown side by side |
| Overviews | Sequencing overview per sample (every imported and derived file with lineage, read statistics, POD5 reads and signal duration, bases per file) and a QC overview per project (one row per sample: totals, N50 and quality of the largest file, pooled Q30/GC, depth only with a user-given genome size, filtering, FastQC heuristics, SeqKit check; sortable, filterable, CSV export) |
| Project QC report | MultiQC 1.35 report over the latest FastQC, fastp, SeqKit and Filtlong results of a project, run offline, every input checked; general statistics kept with units and the producing tool |
| Tools & Databases | Detected tools with version (validated or not), executable, licence, citation and install commands; ARVA never installs software |
| Execution | Analyses run in a separate worker process via a Redis queue — never in the HTTP process; external tools run without a shell, with timeouts and a credential-free environment |
| Reports | HTML (figures, methods, processing steps with exact commands, limitations), CSV and JSON per sample |
| ARVA Guide | “What does this mean?” on every metric: beginner / intermediate / advanced, English & Spanish, with references |
| Analysis Timeline | Raw data → QC → Filtering → Assembly → Polishing → Annotation → Biology, per sample |

## Quick start

### Docker (recommended)

```bash
docker compose up -d --build
open http://localhost:8080        # API docs: http://localhost:8000/docs
```

Services bind to `127.0.0.1` only. Data persist in Docker volumes (`ARVA_DATA_DIR` to use a host folder).

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
