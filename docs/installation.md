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

## Configuration

Environment variables (prefix `ARVA_`), also read from `apps/api/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ARVA_DATABASE_URL` | `postgresql+psycopg://postgres:…@localhost:5432/arva` | SQLAlchemy URL |
| `ARVA_REDIS_URL` | `redis://localhost:6379/0` | Job queue |
| `ARVA_STORAGE_ROOT` | `./data` | Raw files, results, reports, logs |
| `ARVA_MAX_UPLOAD_SIZE_BYTES` | 20 GB | Per-file upload limit |
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
| File marked *Unrecognised* | Content does not start with `@` (FASTQ) or `>` (FASTA) after decompression |
| A tool shows *Not installed* | Install it (see above) or point `ARVA_TOOL_<ID>`/`ARVA_TOOLS_PATH` at it, then **Re-detect** |
| fastp report shows tables but no charts inside ARVA | Expected: its charts load plotly.js from the internet, which ARVA blocks; ARVA's own comparison charts cover the same data, and the original report can be downloaded |
