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
- Strings: add to `src/i18n/index.ts` in both languages and read them with `t()`; counts with the plural syntax
  (`{n, plural, one {# file} other {# files}}`), numbers, sizes, base pairs and dates with `lib/format.ts`
  (`fmtInt`, `fmtNum`, `fmtPct`, `fmtBytes`, `fmtBp`, `fmtDate`), never `toFixed` or a literal `bp`. A message the API
  sends gets a stable code and parameters next to its English text (`JobFailure(message, "code", **params)`); the
  interface translates `prefix.<code>` and falls back to the text. `src/test/i18n.test.ts` fails on interface text
  written outside `t()`; a technical token that must stay as written goes to its reviewed allowlist with the reason
  (see "Interface language" in `architecture.md`).
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
# Tool adapters
cd workflows/tool-adapters && ../../apps/api/.venv/bin/pytest -q
# Example data
python3 scripts/make_synthetic_reads.py examples/synthetic
python3 scripts/make_synthetic_genome.py examples/synthetic-genome   # genome + reads for assembly (gitignored)
```

## Integrating an external tool

Follow the existing adapters in `workflows/tool-adapters/arva_tools/` (fastp is the most complete):

1. **Verify first.** Install the tool, read its `--help` and official documentation, run it on
   `examples/synthetic`, and inspect the real outputs. Record which version you verified in the module
   docstring. Check licence, redistribution terms and Bioconda/apt availability for linux-64,
   linux-aarch64, osx-64 and osx-arm64.
2. **Adapter.** Subclass `ToolAdapter` with a `ToolInfo` (licence, citation, homepage, formats,
   `min_version`, `tested_versions`, install hints you have verified: `conda`, `apt`, or `pip` for a
   Python tool installed with exact pins into its own virtual environment outside the repository and
   found through `ARVA_TOOL_<ID>`) and a `version_pattern`.
   Model parameters as a dataclass with `validate()`; build commands as argument lists in which every
   option that can remove or change data is passed explicitly, even at its default.
   `run_command` already gives each run an empty temporary `HOME`/XDG folder; pass tool-specific
   variables with `extra_env`, and an empty working directory when the tool reads configuration from it;
   pass `home=` (an empty job folder) when you need to inspect what the tool wrote there (NanoPlot).
   Check outputs, not only the exit status (MultiQC, for example, exits 0 when it found nothing).
   For long runs pass `monitor=` to follow the tool's log and save `job.progress` (Flye's
   `_StageMonitor` in `app/tasks/tools.py`; give it `plan=` when the tool writes its own stage list, as
   SPAdes does in `run_spades.yaml`); check every option against the installed tool's own
   `--help` when options differ between versions (`FlyeAdapter.help_options`; `arva_tools.base.help_options`
   reads short and long options from a help text, as for SPAdes and Unicycler). Check also that an option
   passed at its documented default really behaves as the default (QUAST's `--ambiguity-score` does not).
   A tool that builds shell commands from its arguments (MUMmer's `dnadiff`) gets only relative file names
   ARVA chose, run in the job's work folder. Java tools run as `java -Xmx<heap> -jar <jar>` (Pilon), never
   through a launcher that fixes the heap; `run_command` removes the Java option variables.
3. **Parsers.** Parse outputs by field name, not position; tolerate extra fields from newer versions.
4. **Tests.** Command construction and validation (`tests/test_adapters.py`), parsing from small
   fixtures, and a real-tool test skipped when the tool is absent (`tests/test_real_tools.py`).
   Add a version to `tested_versions` only after the real-tool tests pass with it.
5. **Job.** Add a task in `apps/api/app/tasks/tools.py` using `run_job`: resolve the tool, record
   `commands`, write outputs under `ctx.results_rel` / `ctx.processed_rel`, register derived files with
   `_register_derived`, store a compact `result_summary`, and queue follow-up work via
   `ctx.after_commit`. Run every external command through `_run` (it checks for a cancellation before the
   command and every few seconds while it runs); long loops in ARVA's own code call `ctx.check_cancelled()` at
   safe points. Something that must survive a failure or cancellation (Flye's resumable work folder) is moved out
   of the results by a `ctx.before_cleanup` hook, never kept in `results/`.
6. **API + UI + Guide.** Endpoint returning `202` with the job; UI showing every parameter and a
   plain-language summary; Guide entries in English and Spanish with references. Tool HTML pages are
   served by `GET /jobs/{id}/outputs/{name}`; pages that link to each other (QUAST's Icarus viewers) are
   opened by their path below the job folder so relative links keep working.
7. **Docker.** Add the tool to `docker/api.Dockerfile`, rebuild, and run the real-tool tests inside
   the image before declaring its version validated.
