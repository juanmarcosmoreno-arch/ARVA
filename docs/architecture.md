# Architecture

```
 Browser (React SPA)
      │  HTTP/JSON, multipart uploads
      ▼
 nginx (Docker) / Vite proxy (dev)
      │
      ▼
 FastAPI  ──────────►  PostgreSQL     metadata, provenance, headline metrics
   │   │
   │   └──── enqueue ──►  Redis (RQ queue "arva")
   │                         │
   ▼                         ▼
 Local storage  ◄──────  Worker process(es)  ──►  arva_core (scientific-core)
 raw/ processed/                │
 results/ reports/ logs/        └──►  arva_tools adapters ──► SeqKit · FastQC · fastp · Filtlong
```

## Layers and contracts

| Layer | Responsibility | Must not |
|---|---|---|
| `scientific-core` (`arva_core`) | Parse, validate and compute. Pure functions over files → JSON-serialisable dicts. | Import web, DB or queue code |
| `workflows/tool-adapters` (`arva_tools`) | Find external tools, read their versions, build argument vectors, run them safely, parse outputs | Know about the database or HTTP |
| `apps/api` | HTTP API, persistence, job creation, reports, storage path control | Run heavy computation in a request |
| `apps/workers` | Execute queued jobs; write results and provenance | Accept network requests |
| `apps/web` | Interaction and visualisation | Load whole sequencing files; compute scientific results |

## Data model

- **Project** → many **Samples** (rich metadata, unique Sample ID per project).
- **RawFile**: a sequence file stored once and made read-only; `sha256`, detected format, mate (R1/R2),
  validation status. `origin` is `imported` (user upload) or `derived` (written by a job, e.g. filtered
  reads), with `parent_file_id` and `produced_by_job_id` forming the lineage. `header_metadata` holds
  the summary of the first read headers (platform hint with confidence, distinct instrument/run/flow
  cell/barcode values, a bounded read-name fingerprint for R1/R2 checks); it is a suggestion and is
  never copied into the sample automatically. `file_format` `pod5` marks raw nanopore signal
  (recognised by its start and end signatures); such files are excluded from every read-level
  analysis.
- **AnalysisJob**: one execution of one tool on declared inputs. It belongs to a project
  (`project_id`) and, for per-sample analyses, to a sample (`sample_id`); project-level jobs such as
  the MultiQC report have no sample and are listed by `GET /projects/{id}/jobs`. Records `tool_name`, `tool_version`,
  optional `database_name`/`database_version`, `parameters`, `input_raw_file_ids`, `output_paths`,
  status, start/finish timestamps, duration, log and error; for external tools also `tool_path`,
  `commands` (the exact argument vectors executed) and `result_summary` (parsed key results).
  `parent_job_id` marks jobs started automatically by another job.
- **MetadataImport**: provenance of one sample-metadata table applied to a project (file name, SHA-256,
  kind, sheet, encoding, delimiter, header row, column mapping, date order, mode, and the created /
  updated / unchanged / skipped counts). The table file itself is not stored.
- **QCResult**: structured output of a sequence-statistics job for one raw file. Headline metrics are
  indexed columns; the full payload is JSON (also written to `results/…/sequence_stats.json`).

`GET /projects/{id}/qc-overview` (and `.csv`) summarises a project per sample from completed jobs in
four queries, independent of the number of samples (`app/services/qc_overview.py`).

Traceability chain implemented today: **raw file → processing job → derived file → statistics job →
result file → report**. Re-running an analysis creates a new job; earlier results are never overwritten.

## Storage

All paths in the database are relative to `ARVA_STORAGE_ROOT` and resolved through
`app/storage/local.py`, which rejects any path escaping the root. Uploaded filenames are reduced to a
safe basename and prefixed with the file's UUID. The layout:

```
raw/<project>/<sample>/<file-id>__<name>        read-only originals
processed/<project>/<sample>/<job-id>/…         read-only derived reads (e.g. filtered FASTQ)
results/<project>/<sample>/<job-id>/…           analysis outputs and tool reports
results/<project>/_project/<job-id>/…           project-level outputs (MultiQC report, its staged inputs)
reports/<project>/<sample>/…                    every generated report is archived
logs/<job-id>.log
```

`StorageBackend` is a protocol so an S3-compatible backend can replace `LocalStorage` later.
Sequencing data are never stored in PostgreSQL.

## Jobs

Endpoints create `AnalysisJob` rows (status `pending`, with the tool version detected at that moment)
and enqueue them in Redis. A worker (`apps/workers/run_worker.py`) executes them through
`app/tasks/common.run_job`, which every task shares:

1. mark the job running and log tool, version, executable, environment and parameters;
2. run the task body (ARVA statistics or an external tool);
3. on success, commit status, outputs and any new records, then run *after-commit hooks*
   (e.g. enqueue follow-up statistics jobs that were created in the same transaction);
4. on failure, roll back database changes, delete the job's partial `results/` and `processed/`
   directories (never `raw/`), and record the reason and the tool's last log lines.

The `pod5_summary` job (`app/tasks/pod5_summary.py`) is the only one that uses an optional Python
library: `pod5==0.3.49` (extra `pod5` of `apps/api/pyproject.toml`). The task never imports it; it runs
`python -I -m app.tasks.pod5_reader FILE` as a short-lived child process with the tool timeout, which
validates the Arrow tables before converting them. A damaged file that still crashes native code
(lib_pod5, pyarrow) kills only that child, and the job fails with the signal name instead of staying
`running` or taking the worker down. The API detects the library from package metadata
(`GET /api/v1/tools/libraries`) and answers 409 with the install command when it is missing.

On Linux each job runs in a forked process; on macOS the worker uses RQ's `SimpleWorker`
(fork-after-Objective-C-init is unsafe there). Tests run the queue synchronously with `fakeredis`.

## External tools

`arva_tools` provides one adapter per tool (`ToolInfo`: licence, citation, homepage, formats,
minimum and validated versions, install hints). Executables are resolved from `ARVA_TOOL_<ID>`,
then `ARVA_TOOLS_PATH`, then `PATH`; ARVA never installs software. `run_command` executes argument
vectors without a shell, in their own process group (killed on timeout), with stdout/stderr streamed
to files (optionally gzip-compressed) and an environment stripped of ARVA settings, of `MULTIQC_*`
configuration variables and of anything resembling a credential; `HOME` and the XDG base directories
point at a fresh empty folder that is deleted after the run. `GET /api/v1/tools` reports status (`available`, `not_installed`,
`incompatible`, `failed`) and whether the detected version has been validated.

Tool HTML reports are served by `GET /jobs/{id}/outputs/{name}` with
`Content-Security-Policy: sandbox …; default-src 'none'`: they render in an opaque origin and cannot
load anything from the network. (fastp's report references plotly.js on public CDNs; its charts
therefore do not draw inside ARVA, while its tables do, and the original file can be downloaded.)
NanoPlot's report embeds plotly.js (`--include-js embedded`) and renders completely under this
sandbox (`scripts/check_nanoplot_report.cjs`); its jobs also pass `run_command` a job-specific empty
`home` so ARVA can check afterwards that no browser was downloaded there.

The MultiQC project report is sandboxed too, with
`sandbox allow-scripts allow-popups; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline';
img-src data: blob:; connect-src 'none'; font-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'`.
Its scripts read `localStorage` (and `document.cookie`), which throw in an opaque origin and would stop
the plots, so the endpoint inserts a short script at the top of `<head>` that replaces them with
in-memory stand-ins (`app.services.multiqc.STORAGE_SHIM`); the stored file is unchanged and is what
`?download=true` returns. Without the sandbox the report would run in ARVA's own origin: markup that
reaches it unescaped (for example a FastQC overrepresented sequence) could open a same-origin window
and use the API from there, which `connect-src 'none'` does not prevent. `scripts/check_multiqc_report.cjs`
and `scripts/check_nanoplot_report.cjs` (shared code in `scripts/report_browser_check.cjs`, run by the
API tests when node and playwright are available, otherwise reported as skipped) check in headless
Chromium that the plots render, that requests the bundled code can make (crossref DOI look-ups, AI
services, CDN images) are blocked, that the page has an opaque origin, and that a window it opens on
ARVA's origin can neither be scripted nor carries ARVA's origin. Sample names and the title given to
MultiQC are still reduced to letters, digits and a few punctuation marks (MultiQC does not escape
them), and the UI opens the report in a new tab with `rel="noopener noreferrer"`.

## Planned extension points

- **Nextflow DSL2** (`workflows/nextflow/`): multi-step pipelines (assembly, annotation) executed by a
  worker, with Nextflow's trace/report attached to the job.
- **Containers**: adapters may declare container images (Docker/Apptainer) with explicit
  architecture checks, since many bioinformatics tools have no ARM64 build.
- **Auth**: projects already form the unit of access control; roles (Administrator, Researcher,
  Viewer) will attach there.

## Security

- API and web bind to `127.0.0.1` by default; nothing is exposed to the network.
- Upload filenames cannot influence storage paths; resolution is checked against the root.
- Originals are written once (`open(..., "xb")`), then chmod read-only.
- Server-folder import (`app/services/import_roots.py`) only reads inside `ARVA_IMPORT_ROOTS`: paths
  are root-relative, `..`/absolute/hidden names are refused, real paths are checked against the root
  (symlinks leaving it are rejected), and sources are opened component by component from the root with
  `O_NOFOLLOW` (so a folder swapped for a symlink after the check is refused), checked to be the same
  inode, and rejected if their size or mtime change during the copy. Sources are never altered.
- Uploads whose `Content-Length` (times 2 when the request spool shares the data disk) exceeds the
  usable free space are answered with 507 by an ASGI middleware before the body is read, and uploads
  without `Content-Length` with 411; each file is re-checked before it is stored and every 256 MB
  while it is written.
- User-supplied text is HTML-escaped in reports; the React UI never injects raw HTML from data.
- External tools run from argument vectors only (no shell), with a credential-free environment,
  timeouts and process-group termination. User-supplied names appear in commands only inside
  single arguments (sanitised paths within the storage root), so they cannot inject options or commands.
