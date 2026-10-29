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
 results/ reports/ logs/        └──►  arva_tools adapters ──► SeqKit · FastQC · fastp · Filtlong · Flye · SPAdes · Unicycler · QUAST · Racon · Pilon · dnadiff …
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
  `parent_job_id` marks jobs started automatically by another job. `progress` (JSON, nullable) is
  written while a long tool runs (Flye: stage, stage index, expected stages, elapsed time, live log
  path) and committed every few seconds; `GET /jobs/{id}/log?tail=N` serves the last lines of that
  live log (only inside the job's results folder), else of the ARVA job log. Status is `pending`, `running`,
  `completed`, `failed` or `cancelled`; `cancel_requested_at` records a cancellation request (a running job keeps
  status `running` until the worker has stopped its tool), and `checkpoint` (JSON, nullable) describes a stopped
  Flye run's work folder kept under `checkpoints/` for `--resume` (never a result). `resources` (JSON, nullable)
  records what the job was given when it was created: performance profile and how it was chosen, threads, the
  profile's memory per job and the value passed to the tool's own memory option, CPU priority (`nice`, and the
  `nice` executable the worker used), the CPUs and memory ARVA could use, and a one-line description of the
  computer. Jobs ARVA runs in its own process (read statistics, imports, POD5) record none.
- **AppSetting**: a key → JSON value stored server-side so that the API and the worker read the same setting; the
  key `performance` holds the chosen performance profile (`auto`, `light`, `balanced`, `maximum`, or `custom` with
  `threads` and `memory_gb`).
- **MetadataImport**: provenance of one sample-metadata table applied to a project (file name, SHA-256,
  kind, sheet, encoding, delimiter, header row, column mapping, date order, mode, and the created /
  updated / unchanged / skipped counts). The table file itself is not stored.
- **Assembly**: a genome assembly written by one job (`job_id`, unique) for one sample: assembler and
  version, mode (`long`, `short`, `hybrid`), the assembler's read-type setting, `input_file_ids` (the exact
  imported or derived read files used), the contigs/graph/info paths in the job's `results/` folder
  (checksummed and read-only, never registered as read files), `stats` (arva-core assembly statistics,
  output checksums, expected genome size and its source, the heuristic checks run), `contigs` (rows for
  the 2,000 longest contigs) and `warnings` (labelled heuristics). Read through
  `GET /samples/{id}/assemblies`, `GET /projects/{id}/assemblies` (summary rows for the project page),
  `GET /assemblies/{id}`, `GET /assemblies/{id}/contigs.fasta` and `GET /assemblies/{id}/graph`
  (bounded GFA view; each segment carries the contigs whose GFA path runs through it and their
  circular/repeat flags, and the response names the assembler's coverage tag). The sample report's
  JSON/HTML/CSV include an Assembly section built from these records. Flye assemblies are started with
  `POST /samples/{id}/assembly/flye` (202; 409 when Flye is unavailable; 400 for inputs it cannot
  assemble) after `POST /samples/{id}/assembly/flye/preview`, which returns the installed Flye and the
  options its `--help` lists, each file's evidence, a heuristic read-type suggestion and the
  genome-size options, without running anything. SPAdes and Unicycler assemblies are started with
  `POST /samples/{id}/assembly/spades` and `POST /samples/{id}/assembly/unicycler` (202; 409 when the tool or a
  helper the mode needs is unavailable; 400 for files that cannot play their roles — R1, R2, unpaired, long — or
  that contradict the sample's technology; 422 for invalid options), after the matching `…/preview`, which
  returns the installed tool (and Unicycler's helpers and modes), the thread and memory limits, each file's
  evidence by role and any problem, without running anything. Each assembly names its `coverage_kind`
  (`read_depth` for Flye, `kmer_coverage` for SPAdes, `relative_depth` for Unicycler).
  An assembly is polished with `POST /assemblies/{id}/polishing` (202; `strategy` racon, pilon or hybrid, the
  reads by role, Racon and Pilon settings, optional QUAST; 400 when the reads do not fit the strategy, the read
  type or the sample's technology; 409 when a tool the strategy needs is unavailable) after
  `POST /assemblies/{id}/polishing/preview` (the tools of each strategy, the strategy the reads imply and the one
  the sample's technology calls for, a heuristic minimap2 preset, the limits). The `racon_polish` and
  `pilon_polish` jobs (`app/tasks/polishing.py`) record each round's commands and changes in `result_summary`
  (direct evidence from dnadiff and Pilon's `.changes`, indirect indicators from samtools, assembly statistics
  before and after) and register the result as an Assembly with `kind` "polished" and `parent_assembly_id`
  (FK, SET NULL) its draft; the hybrid strategy's Racon job queues the Pilon job, and the last job the optional
  QUAST job, in the transaction that completes it.
  Assemblies are evaluated with `POST /samples/{id}/assembly/quast` (202; 1–10 assemblies of the sample, an
  optional reference chosen among the sample's FASTA files, `min_contig`; 409 when QUAST, or minimap2 for a
  reference, is unavailable) after `POST /samples/{id}/assembly/quast/preview` (labels, contigs kept and
  left out at the minimum length, installed QUAST and minimap2). The `quast_evaluation` job records the
  assemblies with their contigs checksums in `parameters` and the reference file as its input; its
  `result_summary` holds QUAST's report read by field name and ARVA's cross-check. QUAST's HTML pages are
  served by `GET /jobs/{id}/outputs/{path}`, where a path below the job folder (e.g.
  `quast/icarus_viewers/contig_size_viewer.html`) keeps the pages' relative links working.
- **ReferenceDatabase** (`reference_databases`): a database installed by the Database Manager
  (`origin` download, folder owned by ARVA inside `ARVA_DB_DIR`) or a registered folder (`origin` register,
  only read): catalogue key, name, version, path, source, licence, size, content checksum (SHA-256 of the
  file manifest), the archive's published checksum, status (`installed`, `registered`, `downloading`,
  `verifying`, `failed`, `cancelled`), dates, progress, log and cancellation request. Downloads and
  verifications run as worker tasks (`app/tasks/databases.py`) with their own lifecycle, since they belong
  to no project. `analysis_jobs.reference_database_id` (SET NULL) plus `database_key`, `database_name`,
  `database_version` and `database_checksum` record the database a job read.
- **Annotation** (`annotations`): one finished annotation of one assembly, written by the `bakta_annotation` or
  `prokka_annotation` job that produced it (one per job, all three links CASCADE): tool and version, database key,
  name, version and checksum, the parameters, the per-step plan and outcome (`steps`: run or not, why, searched,
  skipped or failed, count found), ARVA's summary, the annotated sequences (names given to the annotator and in
  the assembly, length, topology), the annotator's files (`files`: kind → path, SHA-256, size) and the path of the
  feature index. The features themselves are not rows: they are a JSON-lines file in the job's results
  (`features.jsonl`, `arva_core.annotation` shape), written once and read into memory per annotation, with a
  small cache keyed by path, modification time and size. `POST /assemblies/{id}/annotate/{bakta|prokka}/preview`
  explains a run (steps, dependencies, skip options, database, problems); the run endpoints require
  `confirmed`, and Bakta's also the skip options of that preview. `GET /annotations/{id}/features` filters
  (type, contig and range, text, hypothetical), sorts and pages (at most 1,000 per page);
  `/features/{fid}` adds checked links and the nucleotide and protein sequence; `/files/{kind}` serves an
  annotator file from a fixed list (attachment, `nosniff`, `default-src 'none'; sandbox`); `/export/{fmt}` and
  `POST /export` (at most 10,000 selected features) cut GFF3, GenBank or FASTA from the annotator's files or
  write ARVA's TSV; it also takes a `region` (contig, start, end) instead of ids: the features overlapping it.
  The Genome Explorer (`app/services/genome_explorer.py`, `app/api/routes/explorer.py`) reads the annotator's `.fna`
  (cached by path, modification time and size): `GET /annotations` lists every annotation with its sample, project
  and assembly; `/annotations/{id}/tracks?contig=&start=&end=&bins=&window=&step=` returns GC and GC skew per window
  (`arva_core.genome_view`; at most 5,000 points and 2,000,000 windows) and coverage from a polishing job's depth
  profile when one exists for exactly these contigs, else the reason; `/sequence?contig=&start=&end=&strand=&format=`
  returns at most 1,000,000 bases as JSON or a FASTA attachment; `/layout?contig=` returns every feature of one
  sequence with the fields needed to draw it (at most 50,000); feature details add `checks` (the annotator's gene
  and protein sequences against the genome). Polishing jobs keep `comparison/{draft,polished}.depth_profile.json`
  (samtools depth summed in 25 bp bins; path and SHA-256 in `result_summary.indirect.{before,after}.depth_profile`).
  `/map?contig=…&points=&window=` serves the circular map: the features of the chosen sequences (default all, in
  the annotator's order; at most 50,000), GC and GC skew in windows of one length on every sequence (at most 5,000
  windows) with the mean GC of the drawn sequences, and coverage per window when a depth profile exists. The web
  draws it (`apps/web/src/lib/circular.ts` for the geometry, `components/explorer/CircularMap.tsx` for the SVG);
  the HTML report draws a static copy server-side (`app/services/circular_svg.py`, every text escaped), since a
  report is a single self-contained file. `GET /annotations/{id}/charts?length_bin=&window=` returns the numbers
  behind the annotation charts (`arva_core.annotation_stats`: gene lengths, gene density per window, strand,
  COG categories as reported, hypothetical and characterised CDS, features by type), computed from the feature
  index on request rather than stored, so existing annotations get them and the definitions live in one place.
  The sample report collects the same numbers (`charts`, `map` in the JSON; the map's SVG only in the HTML).
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
results/<project>/<sample>/<job-id>/input/…     an annotation job's staged contigs (genome.fna)
results/<project>/<sample>/<job-id>/features.jsonl  an annotation's feature index (bakta/ or prokka/ beside it)
reports/<project>/<sample>/…                    every generated report is archived
logs/<job-id>.log
```

Reference databases are outside the storage root's layout, in `ARVA_DB_DIR`:

```
<key>/<version>/…                   an installed database (e.g. bakta-light/6.0, Bakta's --db folder)
.arva-downloads/<record-id>/….part  a partial download kept for resuming
.arva-staging/<record-id>/…         unpacking in progress (removed on success, failure or cancellation)
```

`StorageBackend` is a protocol so an S3-compatible backend can replace `LocalStorage` later.
Sequencing data are never stored in PostgreSQL.

### Storage locations and external disks

`app/services/locations.py` describes every folder ARVA uses: the data folder (`ARVA_STORAGE_ROOT`, with
`backups/`), the database folder (`ARVA_DB_DIR`), the import folders (`ARVA_IMPORT_ROOTS`, read-only) and the
added database folders (`ARVA_EXTERNAL_DB_ROOTS`, read-only, used in place). With Docker, `scripts/start.sh`
chooses and remembers host folders (`~/.config/arva/arva.conf`, read line by line, never sourced), checks them
(`scripts/lib/arva-locations.sh`: existing, writable, still on the disk they were chosen on, filesystem via
`diskutil`, free space via `df -Pk`) and mounts them through a generated Compose override as bind mounts with
`create_host_path: false` at `/data`, `/databases`, `/import` and `/databases-external/<cksum of the path>`; the
host paths reach the API as `ARVA_HOST_*` strings for display only. Neither the settings nor the storage layer
create a missing data or database folder whose parent is missing (a disconnected disk).

```
<data folder>/.arva-storage            {"id": …}: ties the folder to the metadata (app_settings "storage")
<data folder>/backups/arva-metadata-<auto|manual|pre-restore>-<UTC>.dump   pg_dump -Fc archives
<data folder>/backups/.last-result     outcome of the last backup (KEY=VALUE)
<data folder>/backups/.request         a backup asked for in Settings → Storage
```

The marker is checked at start-up, by an ASGI middleware before every API write (`app/api/storage_guard.py`: 503
with `{detail, code, params}`; `/system/…` stays usable) and by `run_job` before a job starts (`storage_unavailable`,
nothing written, not even the log file) and after a failure (`storage_lost`). PostgreSQL itself stays in a Docker
volume; the `backup` service (`scripts/metadata-backup.sh` in the postgres image) dumps it into the data folder,
and `scripts/restore.sh` restores a dump into a new database before replacing the current one. Reference
databases whose folder is unavailable are reported per record (`available`, `unavailable_reason`) and are not
verified, used or deleted.

## Jobs

Endpoints create `AnalysisJob` rows (status `pending`, with the tool version detected at that moment)
and enqueue them in Redis. A worker (`apps/workers/run_worker.py`) executes them through
`app/tasks/common.run_job`, which every task shares:

1. lock the job row and run it only if it is still `pending` (a job cancelled while queued never runs), then mark
   it running and log tool, version, executable, environment and parameters;
2. run the task body (ARVA statistics or an external tool);
3. on success, check once more, with the row locked, that no cancellation was requested, then commit status,
   outputs and any new records, then run *after-commit hooks*
   (e.g. enqueue follow-up statistics jobs that were created in the same transaction);
4. on failure or cancellation, roll back database changes, run the task's *before-clean-up hooks* (Flye moves a
   resumable work folder to `checkpoints/`), delete the job's partial `results/` and `processed/`
   directories (never `raw/`), and record the reason (or the cancellation) and the tool's last log lines.

Cancellation (`POST /jobs/{id}/cancel`) of a queued job marks it `cancelled` and removes it from the queue. For a
running job the API records the request; the worker reads it every few seconds through the monitor callback of
every tool run (and at checkpoints of ARVA's own code), which raises, so that `run_command` kills the tool's
process group and step 4 runs. RQ's stop-job command is not used: it kills only the work horse, leaving the tool
(in its own process group) running and the job record unfinished. Batch QC
(`POST /projects/{id}/analyses/batch`) plans per-file jobs for every sample and creates exactly the previewed set
in one transaction.

The `pod5_summary` job (`app/tasks/pod5_summary.py`) is the only one that uses an optional Python
library: `pod5==0.3.49` (extra `pod5` of `apps/api/pyproject.toml`). The task never imports it; it runs
`python -I -m app.tasks.pod5_reader FILE` as a short-lived child process with the tool timeout, which
validates the Arrow tables before converting them. A damaged file that still crashes native code
(lib_pod5, pyarrow) kills only that child, and the job fails with the signal name instead of staying
`running` or taking the worker down. The API detects the library from package metadata
(`GET /api/v1/tools/libraries`) and answers 409 with the install command when it is missing.

On Linux each job runs in a forked process; on macOS the worker uses RQ's `SimpleWorker`
(fork-after-Objective-C-init is unsafe there). Tests run the queue synchronously with `fakeredis`.

### Performance profiles and resources

Thread counts, memory limits and CPU priority come from one function, `app.services.performance.
effective_resources(db)`, used by every job constructor (`app/services/jobs.py`), by the routes for their
defaults and by the previews (`default_threads`, `max_threads`, `default_memory_gb`, `max_memory_gb`,
`default_heap_gb`). It combines three things:

1. **Detection** (`app/services/host.py`, pure parsers plus readers, cached per process): the CPUs this process can
   use (`os.sched_getaffinity`, then the tightest cgroup v2 `cpu.max` or v1 `cpu.cfs_quota_us`/`cpu.cfs_period_us`
   along the process's cgroup path), the memory (the tightest cgroup `memory.max` / `memory.limit_in_bytes`, else
   `/proc/meminfo` `MemTotal`), whether it runs in a container (`/.dockerenv`, `/run/.containerenv` or the
   `container` variable, as systemd's detect-virt checks), and host facts: on native macOS read with `sysctl -n`,
   `sw_vers -productVersion` and `system_profiler -json SPHardwareDataType` (argument vectors, absolute paths,
   timeouts), otherwise taken from the `ARVA_HOST_*` variables `scripts/start.sh` sets. Those are untrusted
   strings: control characters are removed, text is bounded to 80 characters, numbers must be plain digits in a
   range (cores 1–1024, memory 256 MiB–64 TiB), versions and architectures must match a pattern; anything else
   is unknown. Each fact carries its source (`launcher`, `macos`) for the interface.
2. **The choice** stored in `app_settings` (`GET`/`PUT /api/v1/system/performance`, validated by the schema and
   again when read).
3. **The profile table** (ARVA heuristics, `compute()`): the automatic profile from the Mac family (model name,
   else the pre-2022 model identifier prefix), else from usable cores and memory; threads from performance or
   physical cores; memory per job as a share of usable memory; `nice` per profile; capped by the usable CPUs and
   memory and by `ARVA_TOOL_THREADS` / `ARVA_TOOL_MEMORY_GB`. `threads`/`memory_gb` are defaults, `max_threads`/
   `max_memory_gb` the most a request may ask for. `docker_advice()` compares Docker Desktop's figures (from the
   launcher, else the container's view) with what the profile needs on that Mac.

The worker applies the recorded `nice` through `run_command(..., nice=N)`, which prefixes the argument vector
with the `nice` executable resolved by `shutil.which` (no `preexec_fn`, no shell); the error messages and the
recorded `commands` stay the tool's own. samtools sort gets `-m` per thread from the job's memory per job when its
default would exceed it. A tool that exits with SIGKILL (−9, or 137) not caused by ARVA (cancellation and the
time limit raise their own exceptions) marks the job context; `run_job` then appends to the failure reason the
memory ARVA could use, the run's threads and memory limit, and what to change
(`performance.out_of_memory_reason`). `python -m app.services.performance --lang en|es` prints the same summary
for the launcher. Reports list each step's resources and add a methods paragraph on them.

## Interface language

The web interface is in English and Spanish (`apps/web/src/i18n/index.ts`; Settings → Language). Every string the
user reads goes through `t(key, vars)`; the two dictionaries have the same keys (the Spanish one is typed
`Record<TranslationKey, string>`).

- **Plurals**: ICU-style blocks, `{count, plural, =0 {…} one {# file} other {# files}}`, chosen with
  `Intl.PluralRules` for the language; `#` is the count in the locale's format.
- **Numbers, units and dates**: `lib/format.ts` formats with the language's locale (`en-US`, `es-ES`): 1,234.5 and
  45.2% in English, 1234,5 / 12.345 and 45,2 % in Spanish; base pairs are `bp`/`kbp`/`Mbp` in English and
  `pb`/`kpb`/`Mpb` in Spanish (`fmtBp`, `fmtBases`, `bpUnit`). Values typed into inputs (genome size, `--read-error`)
  keep the decimal point the parsers expect.
- **Messages from the API** carry a stable code and parameters next to their English text; the interface shows
  `prefix.<code>` in its language and the English text for codes it does not know (`lib/messages.ts`):
  tool detection (`DetectedTool.reason`, `reason_params` → `tool.reason.*`); job failures
  (`analysis_jobs.error_detail` → `job.error.*`, written by `run_job` from `JobFailure(message, code, **params)`, from
  `ToolExecutionError`'s code, and `out_of_memory` after a SIGKILL); file checks (`raw_files.validation_detail` →
  `file.validation.*`, from `arva_core`'s `QuickValidation.code`/`Pod5Check.code` and the full validation after
  statistics); upload and server-import refusals (`code`, `params` → `upload.rejected.*`); read-statistics warnings
  (`messages` in the statistics document → `seqstats.warning.*`); database-manager failures
  (`reference_databases.error_detail` → `database.error.*`); metadata-import and POD5 warnings (`metadata.msg.*`,
  `pod5.msg.*`); assembly warnings, polishing observations, annotation steps and plan problems (their own codes).
  Parameters named `*_bytes` are shown as sizes in the locale. Migration `c3e9a5d7f1b4` adds the three
  `*_detail` columns; rows written before it have none and show their English text.
- **English text in the API** for coded metadata and POD5 messages uses the interface's English templates, plurals
  included (`app/core/messages.render`, English rules: 1 is singular), and a test checks that both say the same.
  Catalogue descriptions and notes are shown translated only while the interface's English for them is the server's
  text exactly (`serverText`), so a corrected fact never shows in an older translation; a test checks the pair.
- **Guards** (`apps/web/src/test/i18n.test.ts`): a scan of every `.tsx`/`.ts` source with the TypeScript compiler
  API for JSX text, user-facing attributes (`title`, `aria-label`, `placeholder`, `alt`, `label`, …), label-like and
  chart properties (`label`, `title`, `header`, series `name`, …) and `bp` after a number written outside `t()`,
  with a small reviewed allowlist (tool option values, QUAST's field names); same keys, placeholders and plural
  variables in both languages; every plural complete; no unused key; no Spanish text left identical to the English
  one unless all its words are names or written the same in Spanish.

**Still English in the Spanish interface** (by design or not yet coded): HTTP error details of the API's guards
(`detail` of 4xx answers, FastAPI's 422 validation messages), shown as the server wrote them; job failures without a
code, chiefly the adapters' `failure_reason` texts that quote the tool's own error line, the consistency checks of
MultiQC, NanoPlot, SPAdes, Unicycler and QUAST outputs, server-import summaries and unexpected exceptions; the rarer
database-manager failures (redirects, size or Content-Range mismatches, archive layout); job logs; the tools' own
words (QUAST field names and log warnings, FastQC's pass/warn/fail, option values such as SPAdes'
`--cov-cutoff off|auto` and Unicycler's `--mode`), NCBI's COG category names, annotation products, reference titles
and the tools' own HTML reports.

**Reports** (`GET /samples/{id}/report`, HTML/JSON/CSV) and the circular map inside the HTML report are English
only: they are written by the API (`app/services/reports.py`, about 1,500 lines with some 110 HTML fragments and
30 explanatory notes; `app/services/circular_svg.py`, its legend and caption) and the API has no language
parameter. Following the interface language would take a `lang` query parameter passed by the interface, a
server-side EN/ES catalogue for the HTML text with a parity test against the web dictionary, the HTML `lang`
attribute and locale number formatting in the HTML; JSON keys and CSV headers would stay English (machine-readable)
and the free-text fields of the JSON would carry codes. Figures exported from the interface (charts, the circular
map's SVG with its legend and caption) already follow the interface language.

## External tools

`arva_tools` provides one adapter per tool (`ToolInfo`: licence, citation, homepage, formats,
minimum and validated versions, install hints). Executables are resolved from `ARVA_TOOL_<ID>`,
then `ARVA_TOOLS_PATH`, then `PATH`; ARVA never installs software. `run_command` executes argument
vectors without a shell, in their own process group (killed on timeout), with stdout/stderr streamed
to files (optionally gzip-compressed) and an environment stripped of ARVA settings, of `MULTIQC_*`
configuration variables and of anything resembling a credential; `HOME` and the XDG base directories
point at a fresh empty folder that is deleted after the run. A `monitor` callback can follow a long
run: it is called every few seconds while the tool runs (Flye's stages, ARVA's cancellation check), also with
gzip-streamed stdout (compressed in a thread), and the tool's process group is killed if it raises. `GET /api/v1/tools` reports status (`available`, `not_installed`,
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
- Database downloads come only from the catalogue's URL (no URL is accepted from a request; redirects
  to another host are refused), after an explicit confirmation of the archive size and licence. Archives
  are unpacked member by member without tarfile's extraction helpers: absolute names, `..`, members
  outside the expected top folder, devices and FIFOs are refused, hard links must point to an earlier
  file, symbolic links must be relative and stay inside the folder and are created last (never under
  another link), so nothing is written through a link. Registration accepts only absolute paths whose
  real path lies inside `ARVA_DB_DIR` or an import folder; deletion removes files only of a database ARVA
  installed, strictly inside `ARVA_DB_DIR`. Registration may also read added database folders
  (`ARVA_EXTERNAL_DB_ROOTS`), mounted read-only; a path given as on the host is translated to the mount
  before the same real-path check.
- Storage locations come from the launcher's saved settings, read line by line (never sourced or evaluated) from a
  mode-600 file of the user; every folder is checked before Docker starts, reaches the Compose override only as a
  `${VARIABLE}` reference, and is mounted with `create_host_path: false`, so a missing disk stops the start instead
  of a folder being created on the internal disk. Writes and jobs stop when the data folder's storage marker is
  missing or foreign. The backup service has no Docker socket; ARVA asks it for a backup through a file.
- User-supplied text is HTML-escaped in reports; the React UI never injects raw HTML from data.
- External tools run from argument vectors only (no shell), with a credential-free environment,
  timeouts and process-group termination. User-supplied names appear in commands only inside
  single arguments (sanitised paths within the storage root), so they cannot inject options or commands.
