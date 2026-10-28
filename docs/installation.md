# Installation

## Option A — Docker Compose

Requirements: Docker Desktop (macOS, Apple Silicon or Intel) or Docker Engine + Compose v2 (Linux).
All base images are multi-architecture.

```bash
git clone <repository> arva && cd arva
cp .env.example .env              # optional: set ARVA_DB_PASSWORD, ARVA_DATA_DIR
docker compose up -d --build
```

- Web interface: <http://localhost:8080>
- API + OpenAPI docs: <http://localhost:8000/docs>

Services: `postgres`, `redis`, `api` (runs migrations on start), `worker`, `web` (nginx). Ports are
bound to `127.0.0.1`. To keep data in a host folder set `ARVA_DATA_DIR=/absolute/path` in `.env`.

```bash
docker compose logs -f worker     # follow analysis execution
docker compose down               # stop (volumes are kept)
```

The `import/` folder of the repository is mounted read-only at `/import` in the `api` and `worker`
containers for [server-side import](#importing-large-files-from-a-server-folder); set
`ARVA_IMPORT_DIR=/absolute/path` in `.env` to mount another host folder instead.

## Option B — Local development

Requirements: Python ≥ 3.11, Node ≥ 20, PostgreSQL ≥ 14, Redis ≥ 6.

macOS (Homebrew):

```bash
brew install python@3.12 node postgresql@16 redis
brew services start postgresql@16 && brew services start redis
createdb arva
```

Ubuntu/Debian:

```bash
sudo apt install python3-venv nodejs npm postgresql redis-server
sudo -u postgres createdb arva
```

Then:

```bash
scripts/setup-dev.sh     # creates apps/api/.venv, installs deps, writes apps/api/.env, migrates
# edit apps/api/.env if your PostgreSQL user/password differ, then re-run:
(cd apps/api && .venv/bin/alembic upgrade head)
scripts/dev.sh           # http://localhost:5173
```

`scripts/dev.sh` starts three processes: the API (`uvicorn`, port 8000), the analysis worker and the
Vite dev server (port 5173, proxying `/api` to the API).

## External QC tools

ARVA detects tools but never installs them. Without them, ARVA's own read statistics still work;
SeqKit, FastQC, fastp and Filtlong features show as unavailable on the **Tools & Databases** page.

- **Docker**: the API/worker image already contains them (Debian packages: SeqKit 2.3.0 binary,
  FastQC 0.11.9, fastp 0.23.2, Filtlong 0.2.1 — all validated with ARVA).
- **Ubuntu 24.04 / Debian**: `sudo apt install seqkit fastqc fastp filtlong`
  (Ubuntu 24.04: SeqKit 2.3.0, FastQC 0.12.1, fastp 0.23.4, Filtlong 0.2.1 — validated).
- **macOS (Apple Silicon or Intel) / any Linux with conda**:
  ```bash
  mamba env create -f workflows/tool-adapters/environment.yml
  export ARVA_TOOLS_PATH="$(conda info --base)/envs/arva-tools/bin"
  ```
  This environment pins validated versions where Bioconda builds them for every platform; SeqKit is
  2.8.2 because 2.3.x has no Apple Silicon build, and ARVA will mark it "version not validated". The
  conda route has not yet been exercised on a Mac by the ARVA test suite.

Resolution order for each tool: `ARVA_TOOL_<ID>` (absolute path, e.g. `ARVA_TOOL_FASTP`), then the
folders in `ARVA_TOOLS_PATH`, then `PATH`. Re-detect from the Tools page after installing.

## Importing large files from a server folder

Browser uploads work for any size, but multi-gigabyte runs are faster and more robust when ARVA
copies them on the server itself. Configure one or more folders ARVA may read from:

```bash
# apps/api/.env (local) — JSON list of absolute paths
ARVA_IMPORT_ROOTS=["/srv/sequencing/runs"]
```

With Docker Compose this is already set to `["/import"]`, backed by the repository's `import/` folder
(or `ARVA_IMPORT_DIR`). The API **and** the worker must see the folder at the same path. Then use
**Import Data → Import from a server folder**: browse, tick files, choose the sample and start. One
import job copies the files in the background with exactly the same registration as an upload
(streamed SHA-256, read-only copy, quick validation, duplicate and R1/R2 detection); each file's
description records where it came from, and the job log and result list every imported or rejected
file. Source files are opened read-only and are never modified, moved or deleted.

Safety rules: paths are always relative to a configured folder; `..`, absolute paths and hidden
names are refused; symbolic links are followed only when their target stays inside the folder;
listings show at most 2,000 entries per folder. Names that are not valid UTF-8 (for example
Latin-1 names copied from Windows shares) are not listed (the listing says how many) and must be
renamed before import. Files larger than `ARVA_MAX_UPLOAD_SIZE_BYTES` are refused when the import is
requested, before anything is copied. The copy opens the validated file without following any symbolic
link, so a folder or file replaced after the check cannot redirect it outside the import folder. A file
that changes while it is copied (size or modification time differ, e.g. a run still being written) is
rejected and nothing is stored: import it once the sequencer has finished.

To create many samples at once from browser files, use **Bulk import** on a project page: drop the
files or a run folder, review the proposed sample IDs (derived from Illumina/SRA/ONT file names, with
warnings for unpaired R1/R2), adjust them, then confirm.

## Free space

Before an upload or import, ARVA checks the free space on the disk that holds `ARVA_STORAGE_ROOT`
and refuses anything that would leave less than `ARVA_MIN_FREE_BYTES` (default 1 GiB) free:

- the web interface shows *Selected … · Usable for new data …* (the same figure as the storage card)
  and does not start a selection that cannot fit;
- the API answers `507 Insufficient Storage` to an upload whose `Content-Length` exceeds the usable
  space, before receiving the body, and re-checks each file before storing it. Uploads without a
  `Content-Length` (chunked transfer encoding) are refused with `411 Length Required`, since their size
  cannot be checked first; browsers always send it;
- server imports check the total at request time and each file again before copying it;
- while a file is being written ARVA re-checks the free space every 256 MB and stops (deleting the
  partial copy) if the rest no longer fits, so parallel uploads and imports cannot use up the reserve.

**Browser uploads need twice their size while they are received.** The API first buffers each
request body in a temporary file (Python's temporary directory, `TMPDIR`) and then copies it into the
data directory. When that temporary directory is on the same disk as `ARVA_STORAGE_ROOT` — the default
with Docker Compose and for most local installs — the upload is briefly stored twice, so the API and the
web interface require twice the request size (bulk import: the whole selection plus its largest group).
`upload_overhead_factor` in the storage figures is `2` in that case and `1` when the temporary directory
is on another disk. Server folder import copies directly and needs only the files' size.

`GET /api/v1/system/storage` reports the figures (also shown on the Import page).

## Configuration

Environment variables (prefix `ARVA_`), also read from `apps/api/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ARVA_DATABASE_URL` | `postgresql+psycopg://postgres:…@localhost:5432/arva` | SQLAlchemy URL |
| `ARVA_REDIS_URL` | `redis://localhost:6379/0` | Job queue |
| `ARVA_STORAGE_ROOT` | `./data` | Raw files, results, reports, logs |
| `ARVA_MAX_UPLOAD_SIZE_BYTES` | 20 GB | Per-file upload/import limit |
| `ARVA_MIN_FREE_BYTES` | 1073741824 (1 GiB) | Free space that uploads and imports must leave on the storage disk |
| `ARVA_IMPORT_ROOTS` | `[]` (disabled) | Server folders that may be browsed and imported from (JSON list); Docker: `["/import"]` |
| `ARVA_IMPORT_DIR` | `./import` | Docker Compose only: host folder mounted read-only at `/import` |
| `ARVA_CORS_ORIGINS` | `["http://localhost:5173","http://localhost:4173"]` | Allowed web origins (JSON list) |
| `ARVA_TOOLS_PATH` | — | Extra folders (`:`-separated) searched for external tools |
| `ARVA_TOOL_<ID>` | — | Explicit executable for one tool (`SEQKIT`, `FASTQC`, `FASTP`, `FILTLONG`) |
| `ARVA_TOOL_THREADS` | 4 | Maximum threads given to a tool run |
| `ARVA_TOOL_TIMEOUT_SECONDS` | 43200 | A tool run is stopped after this time |

## Running tests

```bash
createdb arva_test                       # once
scripts/test-all.sh
ARVA_TEST_DATABASE_URL=postgresql+psycopg://user:pw@host/db scripts/test-all.sh
```

The API test suite **drops and recreates** the schema of the test database — never point
`ARVA_TEST_DATABASE_URL` at a database holding real data.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Jobs stay *Queued* | The worker is not running or cannot reach Redis — start `apps/workers/run_worker.py` |
| `connection refused` on start | PostgreSQL not running or wrong `ARVA_DATABASE_URL` |
| macOS worker crashes with `objc[...] +[__NSCFConstantString initialize]` | Use the bundled worker script (it selects `SimpleWorker` on macOS) |
| Upload rejected as duplicate | The identical file (same SHA-256) is already registered for that sample |
| File accepted with "Note: identical content is already registered in sample …" | The same content exists in another sample of the project; check the sample assignment |
| Upload or import refused with "Not enough free space" (HTTP 507) | Free disk space where `ARVA_STORAGE_ROOT` lives, or lower `ARVA_MIN_FREE_BYTES` |
| Import page says server folder import is not enabled | Set `ARVA_IMPORT_ROOTS` for both API and worker and restart them |
| Import folder shows "permission denied" / files rejected | The ARVA (container) user cannot read them: `chmod -R a+rX` the folder |
| File marked *Unrecognised* | Content does not start with `@` (FASTQ) or `>` (FASTA) after decompression |
| A tool shows *Not installed* | Install it (see above) or point `ARVA_TOOL_<ID>`/`ARVA_TOOLS_PATH` at it, then **Re-detect** |
| fastp report shows tables but no charts inside ARVA | Expected: its charts load plotly.js from the internet, which ARVA blocks; ARVA's own comparison charts cover the same data, and the original report can be downloaded |
