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
  version, mode (`long`, `short`, `hybrid`, or `imported` for a finished genome FASTA the user registers, e.g. an
  NCBI RefSeq genome: assembler `Imported genome`, version = the source the user states, read type `none`), the assembler's read-type setting, `input_file_ids` (the exact
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
- **ReferenceDatabase** (`reference_databases`): one reference database of a **kind** (`kind`: the registry in
  `app/services/database_kinds.py` — Bakta, AMRFinderPlus, GTDB-Tk, skani, sylph, Mash, Kraken 2, CheckM2, BUSCO,
  PlasmidFinder, MOB-suite, VFDB, geNomad, InterProScan, spa types, reference genome collections), downloaded by the
  Database Manager into a database folder (`origin` download), extracted by it from an archive the user has
  (`origin` extract, e.g. an NCBI Datasets package zip) or registered where it is (`origin` register, only read,
  never modified or deleted): catalogue key, name, version, **how the version was known** (`version_source`: `file`,
  read from the database's own files; `declared` by the user; `checksum`, identified from a checksum the tool
  publishes), path (a folder, or the file of a single-file kind), source, licence, size, **verification level**
  (`quick`: the kind's files, sizes and version file; `full`: plus the SHA-256 of every file), content checksum
  (SHA-256 of the file manifest, after a full verification), the archive's published checksum, `is_default` (one per
  kind, a partial unique index), status (`installed`, `registered`, `downloading`, `extracting`, `verifying`,
  `failed`, `cancelled`), dates, progress, log and cancellation request. The manifest and a reference collection's
  genome inventory are deferred columns (loaded only by the worker). Detection (`database_detect.py`,
  `reference_collections.py`) only reads. Downloads, extractions and full verifications run as worker tasks
  (`app/tasks/databases.py`) with their own lifecycle, since they belong to no project.
  `analysis_jobs.reference_database_id` (SET NULL) plus `database_kind`, `database_key`, `database_name`,
  `database_version`, `database_version_source`, `database_checksum` (None after a quick verification only) and
  `database_path` record the database a job read, and survive its deletion.
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
  `/helix?contig=&start=&end=` (at most 2,000 bases) serves the double-helix view: the bases, the features
  overlapping them with the codons they read there (`arva_core.genome_view.feature_codons`: frame from the 5′ end,
  or from the 3′ end of a 5′-truncated CDS, across the origin, on either strand, the annotation's translation
  table), the bases polishing changed (the polishing job's `comparison/dnadiff_overall.snps`, or of its only round,
  else Pilon's `round1.changes`, read with `DnadiffAdapter.snp_rows` / `PilonAdapter.change_rows`; positions in the
  polished sequence when this assembly is a polishing result, in the draft when it was polished later) and the depth
  profile's bins; the web fetches it in 500-base blocks (`apps/web/src/lib/helix.ts` for the geometry and lookups,
  `components/explorer/DoubleHelix.tsx` for the SVG, reading head and context; AMR, virulence and mobile-element
  calls come from the queries the browser's tracks already use).
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
- **MLST result** (`mlst_results`): one MLST call of one assembly by one `mlst_typing` job: scheme and ST (None
  where mlst wrote `-`), mlst's status and score, every locus with mlst's call and its type (exact, novel, partial,
  missing, multiple, null), the clonal complex read from the scheme's profile file (or why there is none), ARVA's
  coded warnings, and the facts of mlst's log (tied schemes, other schemes with exact matches, the BLAST command),
  the novel alleles and the scheme's own dates; mlst's files with SHA-256. The PubMLST schemes mlst bundles are a
  `reference_databases` record with origin `bundled` (kind `mlst_schemes`): created when mlst is found (the
  database list and the MLST preview), with the SHA-256 of every file, read in place, never deleted or updated
  by ARVA (`DELETE` answers `bundled_read_only`; registering such a folder answers `bundled_only`). The job records
  it like any database (`record_use`) and the worker refuses to run when the folder or its checksum changed.
  `GET /samples/{id}/mlst`, `/mlst/{id}`, `/mlst/{id}/files/{kind}`, `/projects/{id}/mlst` (and `mlst.csv`), and
  `/mlst` (every project) serve them.
- **Species result** (`species_results`): one species identification of one assembly by one `species_identification`
  job with one method (fastani, skani, mash, sylph, gtdbtk) against one database (kind `reference_genomes`, `mash`,
  `sylph` or `gtdbtk`, recorded with `record_use`): the best hits (accession, organism, strain, type material from
  the collection; ANI, aligned fraction, fragments, Mash distance or sylph containment), ARVA's reading
  (`arva_core.species`: status, species only for *same_species*, thresholds with their sources, coded reasons and
  caveats), the consistency checks with the MLST result and the annotation organism of the same assembly, coded
  warnings, the SHA-256 of every reference genome read and the tool's files. `POST /assemblies/{id}/species/preview`
  and `/assemblies/{id}/species`, `GET /samples/{id}/species`, `/species/{id}`, `/species/{id}/files/{kind}`,
  `/projects/{id}/species` (and `species.csv`) and `/species`. Reference collections can be built from NCBI Datasets
  (`POST /databases/ncbi/plan`, then `/databases/ncbi` with the confirmed count and fingerprint): a database task
  (`app/tasks/ncbi_collection.py`) downloads, extracts, checks the MD5s and the accession list and installs the
  collection (origin `download`, version source `download`).
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

Reference databases are outside the storage root's layout. A database folder ARVA may write to (`ARVA_DB_DIR`, the
one chosen with `scripts/start.sh --databases-dir`) holds what ARVA downloads or extracts; databases registered in
place stay in their own folders (usually an added, read-only database folder):

```
<folder chosen in the download dialog, default <key>/<version>>/…   e.g. bakta-light/6.0 (Bakta's --db folder)
reference-genomes/<zip name>/…      a copy extracted from an NCBI Datasets package zip
.arva-downloads/<record-id>/….part  a partial download kept for resuming
.arva-staging/<record-id>/…         unpacking in progress (removed on success, failure or cancellation)
```

`StorageBackend` is a protocol so an S3-compatible backend can replace `LocalStorage` later.
Sequencing data are never stored in PostgreSQL.

### Container images and their architecture

`.github/workflows/images.yml` builds `docker/api.Dockerfile` and `docker/web.Dockerfile` for linux/amd64 (GitHub's
`ubuntu-24.04` runner) and linux/arm64 (the native `ubuntu-24.04-arm` runner; QEMU on an x86-64 runner when the
repository variable `ARVA_ARM64_RUNNER` says so), with the layer cache in GitHub Actions' cache and the commit as
`ARVA_GIT_COMMIT`. Each image is loaded and smoke-tested (`scripts/ci/smoke-images.sh`,
`scripts/ci/check_image_tools.py`) before the same build, from the builder's cache, is pushed to
`ghcr.io/<owner>/arva-api|arva-web:<version>-<short commit>-<arch>`; a last job joins the two architectures into
the multi-architecture tags `<version>` and `<version>-<short commit>`. Every action is pinned to a commit SHA; the
token is the workflow's own `GITHUB_TOKEN` with `packages: write`.

`docker-compose.yml` names the published images (`ARVA_API_IMAGE`, `ARVA_WEB_IMAGE`, `ARVA_IMAGE_TAG`) and gives
the API, worker and web services `platform: ${ARVA_PLATFORM}` (left out when empty). `scripts/start.sh` pulls
them, or builds them under local names with `--build`, and chooses `ARVA_PLATFORM`: saved with `--platform`, else
the computer's own architecture, except on Apple silicon, where it is linux/amd64 (every tool, through Rosetta)
unless Docker Desktop's Rosetta setting is off. It passes the choice, the reason, the Rosetta setting as read and
the image source as `ARVA_HOST_IMAGE_*` / `ARVA_HOST_DOCKER_ROSETTA`; `app/services/image_platform.py` validates
them, adds the architecture the process really runs (`platform.machine()`), whether that is translated (an amd64
image on an arm64 computer, from the launcher's `ARVA_HOST_ARCH`) and the tools without a build for it (adapters'
`no_conda_platform` and the Debian packages built for amd64 only), for `GET /system/performance`, the launcher's
summary and the diagnostic report.

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

**Reports**: the full project report (`GET /projects/{id}/report?lang=en|es`, `app/services/project_report.py`)
follows the interface language in HTML and PDF: the interface passes its language, the server keeps an EN/ES
catalogue of the report's labels, notes and limitations (a test checks both have the same keys), sets the HTML `lang`
attribute and writes numbers in the locale (thin-space thousands and decimal comma in Spanish); JSON keys and CSV
headers stay English (machine-readable), and tool output texts (product names, tool messages) stay as written. The
sample report (`GET /samples/{id}/report`, `app/services/reports.py`, about 1,500 lines of HTML fragments) and the
comparative and phylogenetic reports are still English only; moving them to the same catalogue is the remaining step.
Figures exported from the interface already follow the interface language.

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

Tools from Bioconda run from environments created only from checked-in explicit locks
(`docker/conda-locks/<tool>/<platform>.lock`, every package URL with its SHA-256; `scripts/conda_locks.py`), one
per tool. An adapter can add variables for its tool (`ToolAdapter.environment`): mlst's `bin/mlst` runs
`env perl` and finds `blastn` and `any2fasta` on `PATH`, so its environment's `bin/` comes first, `MLST_DBDIR`
names the bundled database, Perl's `PERL5LIB`/`PERLLIB`/`PERL5OPT` are emptied and its temporary folder is inside
the job. `ToolInfo.conda_platforms` lists the platforms with a lock; without one, the Tools page says so
(`no_conda_platform`).

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

## Species-specific typing modules

`app/services/typing_modules.py` holds a small registry: a `TypingModule` names the taxa it applies to (species names
as species identification reports them, MLST scheme names as mlst reports them), its `Step`s (each a tool adapter id
and the database kind it reads, or `None` when the tool's package carries its data) and its guide entries.
`evidence()` reads the assembly's latest species call and MLST scheme; `applicability()` turns them into
applicable / conflicting / not_applicable / no_evidence; `requirements()` lists, per step, the tool's detection with
its install command and the registered databases. Jobs are `species_typing` with `{module, method}` parameters
(`app/tasks/typing.py`), one `typing_results` row per job. Only the S. aureus module exists
(`app/services/staph_typing.py`: plan, summary card, project table, CSV, report section).

A new module (for example Klebsiella pneumoniae with Kleborate, E. coli serotyping, Salmonella with SISTR) adds its
adapters under `arva_tools`, a `TypingModule` in the registry, its step runners in `app/tasks/typing.py`, a service for
its summary like `staph_typing.py`, its routes' module key, interface texts in both languages and its own validation
genomes; the applicability rules, the override, the results table and the requirements panel are shared.

## Comparative genomics

`app/services/comparative.py` holds comparison sets (`comparison_sets` kept in one project, `comparison_members` with
position and label, any assembly of any project), the plans of the two project-level jobs (`comparative_ani`,
`comparative_alignment`, created by `create_comparative_job` from the confirmed plan) and the result views and CSV
exports. The worker (`app/tasks/comparative.py`) checks each genome's contigs SHA-256, stages them as
`input/g<N>.fna`, runs the tools (`arva_tools.skani`, `fastani`, `mapping.Minimap2Adapter.assembly_argv`, `nucmer`,
`dnadiff`), writes `alignment.json` (genomes with contigs, compact blocks per pair, conservation windows) next to the
tools' own files, removes the staged copies and stores one `comparison_results` row with the genome snapshot, the
summary (ANI matrix and order, or per-pair summaries and dnadiff's features) and the file checksums. Pure helpers
(matrix, UPGMA order, layouts, pair summaries, conservation) are in `arva_core.comparative`. The comparative report
(`app/services/comparative_report.py`) and the sample report's section are built from stored results only.

## Planned extension points

- **Nextflow DSL2** (`workflows/nextflow/`): multi-step pipelines (assembly, annotation) executed by a
  worker, with Nextflow's trace/report attached to the job.
- **Containers**: adapters may declare container images (Docker/Apptainer) with explicit
  architecture checks, since many bioinformatics tools have no ARM64 build.
- **Auth**: projects already form the unit of access control; roles (Administrator, Researcher,
  Viewer) will attach there.

## Error log and diagnostic report

`app/core/errorlog.py` keeps one JSON line per problem in `<data folder>/logs/errors.jsonl`: a short id shown to the
user (`K7Q2-M9XD`), UTC time, ARVA version and commit (`ARVA_GIT_COMMIT`, baked into the images), component (`api`,
`worker`, `job`, `web`, `launcher`), severity, code and English message (the interface translates
`diagnostics.code.<code>`, `job.error.<code>` and `api.error.<code>`), the exception with ARVA's own frames
(`app/`, `arva_tools/`, `arva_core/`, `workers/`) and library frames summarised, the request's method and route
template (never path values, query or body), the job and tool, the tool's last 60 stderr lines, and a correlation id.
`app.jsonl` holds start-up, the configuration summary and job start/end with durations. Sources:

- every request gets a correlation id (`RequestContext`, header `X-ARVA-Correlation-Id`); `AnalysisJob.correlation_id`
  defaults to it, `run_job` runs the job under it, so a request, its jobs and their follow-up jobs share one id;
- an unhandled exception gives a 500 `{detail, code: "internal_error", params: {error_id}, error_id}`; coded 4xx/503/507
  refusals are kept at info level, at most once per code and route in five minutes and 30 a minute;
- `run_job` (and the database tasks) record failures with their code and cancellations; `app/tasks/worker_events.py`
  records RQ exceptions, a killed work horse (signal, peak memory) and the worker stopping;
- `app/services/startup.py`: the API container's migration step (`python -m app.services.startup migrate`), and at
  API start-up the storage marker, pending migrations, unusable tools and databases whose folder is missing;
- the web interface posts its errors (router error element and error boundary, `window.onerror`,
  `unhandledrejection`, server errors the API did not record) to `POST /system/client-errors`: at most 16 KB, a
  closed set of bounded fields, 20 a minute, the same error kept once in ten minutes;
- `scripts/start.sh` appends a `launcher` entry when `docker compose up` fails, only into a data folder that already
  has its storage marker and logs folder.

Writes are appended under an `flock` shared by the API and worker processes; a file is rotated when an entry would
take it over its size, and the number of rotated files is fixed, so the total is capped. Logs are written only while
`locations.inspect` says the data folder is writable (checked at most every 10 s; without the database, the marker file
alone decides); otherwise an entry goes to stderr only. The API also keeps its last 200 entries in memory, so a report
lists them while the disk is away.

`app/core/redaction.py` runs over every text kept or reported: home folders become `~`, URL credentials and
secret-looking assignments `***`, tokens, e-mail addresses, serial numbers and hardware UUIDs are replaced, nucleotide
and protein runs and unbroken tokens of 80 or more characters become their length; values under secret-looking keys
are blanked. Database errors keep only the driver's first line (no SQL or parameters), validation errors lose their
`input_value`. `app/services/diagnostics.py` builds `GET /system/diagnostics` on request from these entries, host
detection (`performance.detection`), the performance profile, `locations.overview`, the services, tool detection,
database records, the Alembic state and, for a job, its record and log tail; each section that fails says so instead
of failing the report. Anonymisation maps project names, sample codes and file names (original and stored forms) to
placeholders numbered by creation order, so they are stable across reports, and leaves structural fields (ids, codes,
statuses) alone. `scripts/diagnostics.sh` covers the case where the API is not running, with the same redaction in
`sed -E`/`awk`.

## Security

- API and web bind to `127.0.0.1` by default; nothing is exposed to the network. Optional accounts with roles,
  project sharing, CSRF protection and an access audit log are described under "Accounts and access control".
- Nothing leaves the machine unless the user acts: ARVA Assist is off, ships no provider and logs every request it
  sends; PDF rendering refuses every external resource.
- Error log entries and diagnostic reports pass `app/core/redaction.py` (no sequences, secrets, e-mail addresses,
  serial numbers or home folder names); the report is built only when asked and never sent anywhere. What the browser
  posts to `/system/client-errors` is size-, field- and rate-bounded and redacted before it is kept.
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
  to another host are refused), after an explicit confirmation of the archive size and licence, into a database
  folder ARVA may write to (the destination must be one of them, the folder inside it a relative path of letters,
  digits, `.`, `_` and `-` without `..`). Archives are unpacked member by member without tarfile's extraction
  helpers: absolute names, `..`, members outside the expected top folder (or outside the archive, for archives
  without one), devices and FIFOs are refused, hard links must point to an earlier file, symbolic links must be
  relative and stay inside the folder and are created last (never under another link), so nothing is written through
  a link. A zip is extracted only with plain files and folders, each no larger than the zip declares and in all no
  more than its declared total; the zip itself is only read. Registration, detection and browsing accept only
  absolute paths whose real path lies inside a database folder, an import folder or an added database folder
  (`ARVA_EXTERNAL_DB_ROOTS`, mounted read-only); a path given as on the host is translated to the mount before the
  same real-path check, and so is every genome path of a FastANI reference list (a path outside is refused). The
  browser hides links that leave the folder. Detection reads only the kinds' marker and version files (at most
  1 MiB each) and the sizes of their files; nothing is written into a registered folder (a test compares every
  file's size, modification time and mode before and after). Deletion removes files only of a database ARVA
  installed or extracted, strictly inside the database folder it was put in.
- Storage locations come from the launcher's saved settings, read line by line (never sourced or evaluated) from a
  mode-600 file of the user; every folder is checked before Docker starts, reaches the Compose override only as a
  `${VARIABLE}` reference, and is mounted with `create_host_path: false`, so a missing disk stops the start instead
  of a folder being created on the internal disk. Writes and jobs stop when the data folder's storage marker is
  missing or foreign. The backup service has no Docker socket; ARVA asks it for a backup through a file.
- User-supplied text is HTML-escaped in reports; the React UI never injects raw HTML from data.
- External tools run from argument vectors only (no shell), with a credential-free environment,
  timeouts and process-group termination. User-supplied names appear in commands only inside
  single arguments (sanitised paths within the storage root), so they cannot inject options or commands.

## Accounts and access control

Optional (`ARVA_AUTH_ENABLED`). Tables `users`, `user_sessions`, `project_shares`, `audit_events` and
`projects.owner_id` (migration `b6e2d4f8a1c3`). Every router is included with the dependency `app.api.access.guard`:

1. With accounts off it only marks the request as the local user (nothing else changes).
2. With them on: a session cookie (random token; only its SHA-256 is stored), the CSRF token in `X-CSRF-Token` for
   every change (compared with its stored hash), role rules (viewers change nothing; `ADMIN_ONLY` routes and changes to
   databases, tools and system settings need an administrator), then project access: each path parameter, id-like
   query parameter and id in a JSON body is resolved to its project (`RESOLVERS`: project, sample, assembly,
   annotation, file, job, comparison set and result, MLST and species results, variant runs, batch runs). The route's
   project needs write access for a change and read access otherwise; other projects a body names need read access.
   A path parameter that is neither resolvable nor declared global is refused to non-administrators, and a test
   checks every route's parameters, so a new route cannot bypass the check. Unscoped lists either filter their rows
   with `visible_projects(request)` (`FILTERED`) or show no project data (`GLOBAL_READS`); others are for
   administrators.
3. Refusals, every allowed change and every report or file download are written to `audit_events` with the user, the
   route template, the project and the outcome (never request values). Sign-ins (and failures), sign-outs, account
   and sharing changes are recorded by their routes.

Passwords: Argon2id via argon2-cffi's `PasswordHasher` defaults (RFC 9106 low-memory profile), rehashed on sign-in
when the parameters change; unknown user names are verified against a dummy hash so both cases take as long; a
locked account is refused even with the right password. Changing a role, deactivating an account or changing a
password revokes the account's sessions. The worker runs jobs without a user.

## ARVA Assist (integration point)

`app/services/assist.py`: `AssistProvider` (`ask(payload, config) -> str`) and a registry (`register`,
`unregister`); no provider is included. Settings live in `app_settings["assist"]` (enabled, provider, endpoint,
model); the key in `<storage>/secrets/assist-key`. `build_payload` is the only place where outgoing content is built:
fixed instructions (answer only from the given data, label Observed / Interpretation / Hypothesis, never invent
results), the question, guide excerpts the interface sends (bounded), the project report's data without personal
fields, and sequences only when the request carries `sequence_consent` (otherwise refused with
`assist_sequence_consent`). `POST /assist/preview` returns the payload without sending it; `POST /assist/ask` records
the exact payload, its SHA-256, the provider, endpoint host and model in `assist_requests` before returning the answer;
a provider failure is recorded and answered with `assist_provider_failed`, never a 500.

## Region Explorer and gene investigation

`app/services/regions.py` holds the saved queries (`gene_queries`), the gene lookup across a set's annotations and
the plans of the `region_explorer` and `gene_investigation` jobs (created by `create_region_job` from the confirmed
plan). Their results are `comparison_results` rows with `analysis` "region" or "gene" (the drawing data in
`region.json` / `gene.json` beside the tools' outputs). The worker (`app/tasks/regions.py`) checks each genome's
contigs SHA-256, stages them renamed `contig_N` (BLAST rewrites some identifiers), stages annotated proteins as
`f<feature id>` after checking the protein file's SHA-256, runs `makeblastdb`/`blastn`/`tblastn`/`blastp`, MAFFT and
IQ-TREE or FastTree, and removes the staged copies. Pure rules (match chaining, windows, relative coordinates,
homology groups, links) are in `arva_core.region`, Newick reading and writing in `arva_core.newick`. The figure is a
list of primitives (`apps/web/src/lib/regions.ts`) drawn as SVG and written as a vector PDF (`lib/pdf.ts`).

## Pangenome

`app/services/pangenome.py` builds the plan of the `pangenome` job (each genome's latest annotation and its GFF3
SHA-256, the annotation consistency, Panaroo's or PPanGGOLiN's settings, the category thresholds and curve sampling;
`create_pangenome_job` records them) and serves the result: the family explorer reads one line of `members.jsonl` by
the byte offset kept in `pangenome.json` and each member's row of Panaroo's `gene_data.csv` by its offset, so a
family opens without reading whole files; metadata groups and associations are computed on request from the stored
matrix and the samples' current metadata. The worker (`app/tasks/pangenome.py`) links the GFF3 files as
`input/g<N>.gff3`, runs Panaroo with its environment's `bin/` first in PATH and relative paths only, removes Panaroo's
intermediate files and writes ARVA's summaries (`arva_core.pangenome`). Results are `comparison_results` rows with
`analysis` "pangenome"; alignments are listed with their SHA-256 in `alignments.sha256` rather than one entry each.

## Phylogeny

`app/services/phylogeny.py` lists what the set's results offer as tree sources, builds the plan of the `phylogeny`
job (the source result, file and SHA-256, the leaves with their genomes, the method's settings, the constant-site
handling and the rooting; `create_phylogeny_job` records them) and serves the result: the tree rooted as the saved
view (`phylo_tree_views`) says, Newick downloads, leaf metadata (sample fields, MLST, AMR genes) and Robinson-Foulds
comparisons. The worker (`app/tasks/phylogeny.py`) re-checks the source file, writes it with sequences renamed
s1..sN, runs SNP-sites, IQ-TREE or FastTree (or ARVA's neighbour joining), renames the leaves back and keeps the
tools' files. Tree operations are in `arva_core.phylo`; the Tree Explorer (`apps/web/src/components/comparative/
TreeView.tsx`, layouts in `lib/phylo.ts`) draws with the same primitives as the Region Explorer, so SVG, PNG and PDF
exports show exactly what is drawn; it is ARVA's own SVG rather than a library such as phylotree.js, to keep one
figure model for drawing and vector PDF export, avoid a d3 dependency and control every label's translation.
`app/services/phylogeny_report.py` writes the phylogenetic report.

## Variant analysis and consolidated mobilome

`app/services/variants.py` offers the references (ARVA's assemblies; genomes of registered reference collections),
builds the plan of a `variant_calling` job (the reference's snapshot with the SHA-256 of the FASTA as the aligner reads
it, the reads by role, the technology's aligner and bcftools profile, the filters, whether effects are annotated;
`create_variant_job` records them) and serves the results: runs per sample, records filtered and paged, CSV, the SNP
matrix and distances across a project's samples, and the Genome Explorer's Variants track. The worker
(`app/tasks/variants.py`) re-checks the reference, aligns (BWA-MEM or minimap2, reusing the polishing task's helpers),
runs samtools and the bcftools chain (`arva_tools.bcftools`), writes the csq GFF3 from the annotation, and stores the
parsed records and low-depth intervals in `variants.json.gz` next to the VCF; a `variant_calls` row keeps the summary
and file checksums (like annotations, records are not database rows). `arva_core.variants` parses VCF and BCSQ, writes
the GFF3 for csq, computes the summaries and the SNP matrix. `app/services/mobilome.py` reads the existing
mobile-element, AMR and virulence rows and places genes relative to elements by coordinates (no new table);
`app/services/variants_report.py` writes the report sections and the project's variant report.


## Workflows and batch runs

- `scientific-core/arva_core/workflow.py`: the node catalogue (ports, scope, tools by method), graph validation
  (types, scopes, single/collection inputs, cycles, required inputs), topological order, the definition checksum,
  node signatures for branch reuse, parameter differences and the predefined workflows. Pure, no I/O.
- `apps/api/app/services/workflow_nodes.py`: per node kind, the request model of its analysis (parameters are that
  model minus the fields ARVA fills), how a source picks data (ARVA's rule or the user's binding), how the node is
  launched (the analysis's POST route function, so all its checks apply) and what it produced (assembly, annotation,
  derived reads, comparison result).
- `apps/api/app/services/batches.py`: versions, runs and the queue. `dispatch()` holds a PostgreSQL advisory lock on
  its own connection; a call made while the same thread dispatches (a job run synchronously by its launch, as in the
  tests) makes the running call loop again. It is called at the end of `run_job`, after a job cancellation, on run
  changes and when a worker starts. Items record the job of each attempt; jobs launched by a run carry the run's
  correlation id, so the error log lists them with the run.
- Tables: `workflows`, `workflow_versions` (definitions never rewritten), `batch_runs` (snapshot of the definition
  and of the tools, queue settings, branch parent and changes), `batch_items` (node × sample, dependencies, job ids,
  outputs, reason, reservation, reused item).
- Routes: `/workflows` (catalogue, validate, CRUD, versions, duplicate, import, export), `/batches` (preview, start,
  list, queue, detail, pause, resume, cancel, settings, branch, compare, errors, export.json, table.csv,
  report.html) and `/samples/{id}/batches` (timeline branches).
- Web: `/workflows` (list, predefined workflows, runs dashboard), `/workflows/:id` (editor, `@xyflow/react` 12.12.0),
  `/workflows/runs/:id`, `/workflows/compare`; `SampleBranches` on the sample page.
- Parallelism: the queue hands at most the allowed number of jobs to RQ; they run in parallel only with as many
  worker processes (for example `docker compose up --scale worker=2`).
