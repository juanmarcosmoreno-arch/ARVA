# Developer guide

## Principles that shape the code

1. **No invented results.** Every number shown must come from a job that ran real code on real
   input. Planned modules render an explicit *planned* page, never mock data. Demo data, when added,
   must carry `is_demo = true` and be labelled DEMO everywhere.
2. **Provenance is part of the result.** An analysis is not done until its `AnalysisJob` records
   tool, version, parameters, inputs (with checksums), outputs, timings and log.
3. **Originals are immutable.** Never open a `RawFile` for writing; write derived data under
   `results/`.
4. **Heavy work never runs in a request.** Create a job and enqueue it.
5. **Scientific code is framework-free.** Put algorithms in `scientific-core`, test them against
   hand-computed values, and keep the API a thin layer.

## Adding a new analysis (pattern)

Using the existing `sequence_stats` analysis as the template:

1. **Core / adapter**: implement the computation in `arva_core` (pure Python) or, for an external
   tool, a tool adapter that builds the command as an argument list, detects the tool version and
   parses outputs. Never build shell strings.
2. **Job type**: add a constant (cf. `FASTQ_STATS_JOB` in `app/services/jobs.py`) and a
   `create_*_jobs` function that records tool name/version and parameters before enqueueing.
3. **Task**: add `app/tasks/<name>.py` mirroring `run_sequence_stats_job` — status transitions,
   log lines, output files under `results/<project>/<sample>/<job-id>/`, failure handling that
   stores no partial results.
4. **Result model**: add a table (plus Alembic migration:
   `alembic revision --autogenerate -m "..."`) holding headline metrics and the full payload.
5. **API**: a `POST /samples/{id}/analyses/<name>` endpoint returning `202` with the jobs.
6. **UI**: a tab or section that polls jobs, renders results via `ChartCard`, adds `Explain`
   entries to `src/guide/metrics.ts` (EN + ES, with references), and updates the Analysis Timeline.
7. **Tests**: unit tests on small inputs with known answers; an API test running the job through
   the synchronous queue; extend the e2e golden path if it is a primary flow.

## Front-end conventions

- Data fetching with TanStack Query; query keys: `["projects"]`, `["project", id]`,
  `["samples", projectId | "all"]`, `["sample", id]`, `["files", sampleId]`, `["jobs", sampleId]`, `["dashboard"]`.
- Charts: `ChartCard` + `useChartTheme()`. Mark colours in `components/charts/theme.ts` were
  validated (contrast ≥ 3:1, lightness band, colour-vision-deficiency separation) for each theme;
  re-validate if you change them. One y-axis per chart; tooltips on every chart; provide a table view.
- Strings: add to `src/i18n/index.ts` in both languages.
- Brand tokens: `tailwind.config.ts` (`arva-navy`, `arva-royal`, `arva-teal`, `arva-cyan`, …)
  and semantic CSS variables in `src/index.css`.

## Useful commands

```bash
# API
cd apps/api && .venv/bin/uvicorn app.main:app --reload
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/pytest -q
# Web
cd apps/web && npm run dev | npm run typecheck | npm test | npm run build
# Example data
python3 scripts/make_synthetic_reads.py examples/synthetic
```

## Integrating external tools (Phase 2+ checklist)

Before adding any tool: confirm licence and redistribution terms; check macOS ARM64 and Linux
availability (native, Bioconda, or container); pin the exact version; read the official
documentation for every parameter exposed; record database names/versions where applicable; add a
small real-format test dataset with known expected output.
