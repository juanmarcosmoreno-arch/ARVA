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
 raw/ results/ reports/ logs/
```

## Layers and contracts

| Layer | Responsibility | Must not |
|---|---|---|
| `scientific-core` (`arva_core`) | Parse, validate and compute. Pure functions over files → JSON-serialisable dicts. | Import web, DB or queue code |
| `apps/api` | HTTP API, persistence, job creation, reports, storage path control | Run heavy computation in a request |
| `apps/workers` | Execute queued jobs; write results and provenance | Accept network requests |
| `apps/web` | Interaction and visualisation | Load whole sequencing files; compute scientific results |

## Data model

- **Project** → many **Samples** (rich metadata, unique Sample ID per project).
- **RawFile**: original upload, stored once and made read-only; `sha256`, detected format, mate (R1/R2), validation status.
- **AnalysisJob**: one execution of one tool on declared inputs. Records `tool_name`, `tool_version`,
  optional `database_name`/`database_version`, `parameters`, `input_raw_file_ids`, `output_paths`,
  status, start/finish timestamps, duration, log and error.
- **QCResult**: structured output of a sequence-statistics job for one raw file. Headline metrics are
  indexed columns; the full payload is JSON (also written to `results/…/sequence_stats.json`).

Traceability chain implemented today: **raw file → job → result file → report**. Re-running an
analysis creates a new job; earlier results are never overwritten.

## Storage

All paths in the database are relative to `ARVA_STORAGE_ROOT` and resolved through
`app/storage/local.py`, which rejects any path escaping the root. Uploaded filenames are reduced to a
safe basename and prefixed with the file's UUID. The layout:

```
raw/<project>/<sample>/<file-id>__<name>        read-only originals
results/<project>/<sample>/<job-id>/…           analysis outputs
reports/<project>/<sample>/…                    every generated report is archived
logs/<job-id>.log
```

`StorageBackend` is a protocol so an S3-compatible backend can replace `LocalStorage` later.
Sequencing data are never stored in PostgreSQL.

## Jobs

`POST /samples/{id}/analyses/sequence-stats` creates one `AnalysisJob` per input file (status
`pending`) and enqueues it in Redis. A worker (`apps/workers/run_worker.py`) runs
`app.tasks.seqstats.run_sequence_stats_job`, which updates status and log as it progresses. On
Linux each job runs in a forked process; on macOS the worker uses RQ's `SimpleWorker`
(fork-after-Objective-C-init is unsafe there). Tests run the queue synchronously with `fakeredis`.

## Planned extension points

- **Tool adapters** (`workflows/tool-adapters/`): a typed adapter per external tool declaring
  version detection, inputs/outputs, parameters and a command built as an argument list (never a
  shell string). Each adapter produces an `AnalysisJob` exactly like `arva-core.seqstats` does.
- **Nextflow DSL2** (`workflows/nextflow/`): multi-step pipelines (assembly, annotation) executed by a
  worker, with Nextflow's trace/report attached to the job.
- **Containers**: adapters will declare container images (Docker/Apptainer) with explicit
  architecture checks, since many bioinformatics tools have no ARM64 build.
- **Auth**: projects already form the unit of access control; roles (Administrator, Researcher,
  Viewer) will attach there.

## Security

- API and web bind to `127.0.0.1` by default; nothing is exposed to the network.
- Upload filenames cannot influence storage paths; resolution is checked against the root.
- Originals are written once (`open(..., "xb")`), then chmod read-only.
- User-supplied text is HTML-escaped in reports; the React UI never injects raw HTML from data.
- No shell commands are executed in Phase 1; future adapters must use argument vectors.
