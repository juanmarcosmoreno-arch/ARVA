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
- **Ubuntu 24.04 / Debian**: `sudo apt install seqkit fastqc fastp filtlong flye samtools minimap2`
  (Ubuntu 24.04: SeqKit 2.3.0, FastQC 0.12.1, fastp 0.23.4, Filtlong 0.2.1, Flye 2.9.3 — validated;
  minimap2 2.26 is used by QUAST, below).
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

Every tool run gets an empty working folder and a new, empty temporary folder as `HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `XDG_DATA_HOME` (removed afterwards), so configuration files in
your home folder never change a result and nothing is cached there.

### MultiQC (project QC report)

The project page can gather the FastQC, fastp, SeqKit and Filtlong results of all samples into one
MultiQC report. MultiQC is a Python program: install it from PyPI into its own virtual environment,
outside the ARVA folder (MultiQC reads a `.env` file found in any folder above its installation, and
ARVA's folder can hold one), and point ARVA at it in the shell that starts the API and the worker:

```bash
python3 -m venv ~/.arva-tools/multiqc
~/.arva-tools/multiqc/bin/pip install "multiqc==1.35" "plotly==5.24.1"
export ARVA_TOOL_MULTIQC=~/.arva-tools/multiqc/bin/multiqc
```

Validated: MultiQC 1.35 (GPL-3.0) on Python 3.13, Linux x86-64, with plotly 5.24.1 and kaleido 0.2.1
(pinned by MultiQC; without the plotly pin pip picks plotly 7, with which MultiQC's image export fails
silently). PyPI has wheels of every dependency for Linux x86-64/ARM64 (glibc) and macOS Intel/Apple
Silicon; the environment needs about 1.1 GB. Bioconda also builds MultiQC 1.35, but ARVA has not
tested that route. The Ubuntu/Debian `multiqc` package (1.18) is reported as *Incompatible version*:
it has no `--no-version-check` option, contacts multiqc.info over plain HTTP on every run, writes
reports that miss a JavaScript file and has no SeqKit module. ARVA always runs MultiQC with its
version check, AI features and uploads switched off, so it makes no network connection.
`scripts/test-all.sh` uses `~/.arva-tools/multiqc/bin/multiqc` when it exists. The Docker image installs
it the same way (build argument `ARVA_PYTHON_TOOLS`).

The report embeds sample IDs and file names and is meant for viewing on this computer. ARVA opens it
in a new tab and serves it with a sandboxing Content-Security-Policy that isolates it from ARVA and
blocks every network request (settings changed inside the report are therefore not kept); its data
files (`multiqc_data.json`, `multiqc_sources.txt`) also contain local folder paths. Only results of
files that ARVA has read in full (Compute read statistics) go into the report.

### NanoPlot (long-read report)

The QC tab of a long-read sample can run NanoPlot on a FASTQ file. Like MultiQC it is a Python program:
install it from PyPI into its own virtual environment outside the ARVA folder (its package also installs
modules with generic names such as `scripts` and `extra`, and carries its own modified copy of
`nanomath`; never install `nanomath` into that environment, it would replace the copy and change
NanoPlot's mean read quality):

```bash
python3 -m venv ~/.arva-tools/nanoplot
~/.arva-tools/nanoplot/bin/pip install "NanoPlot==1.48.0" "nanoget==1.19.6"
export ARVA_TOOL_NANOPLOT=~/.arva-tools/nanoplot/bin/NanoPlot
```

Validated: NanoPlot 1.48.0 (MIT; its nanoget dependency is GPL-3.0) with nanoget 1.19.6 and plotly
6.9.0 on Python 3.13, Linux x86-64; the environment needs about 600 MB. Older versions are reported as
*Incompatible version*. NanoPlot normally downloads Chrome for Testing (about 360 MB) to draw PNG
images; ARVA always runs it with `--no_static` and `--only-report`, so it never does, and the job fails
if browser files appear in its (empty, job-specific) home folder. `scripts/test-all.sh` uses
`~/.arva-tools/nanoplot/bin/NanoPlot` when it exists. The Docker image installs it the same way.
When it detects NanoPlot, ARVA imports `nanomath` with NanoPlot's own Python and reports the tool as
*Detection failed* if the bundled copy has been replaced; reinstall the environment as above.

### Flye (long-read assembly)

The Assembly tab of a sample runs Flye on long-read FASTQ files. Install it with samtools:

```bash
sudo apt install flye samtools          # Ubuntu 24.04: Flye 2.9.3, samtools 1.19.2
```

Validated: Flye 2.9.3 (BSD-3-Clause; Ubuntu package 2.9.3+dfsg2-1), which needs Python's `six`
(installed with the package) and the system minimap2 and samtools. Flye calls a helper named
`flye-samtools`, which Debian's and Ubuntu's flye package does not ship: without it every assembly
stops in its repeat stage. ARVA links `flye-samtools` to `samtools` for each run when it is missing and
records this; the Tools page shows it as a note, and reports Flye as *Detection failed* when samtools is
missing too (`ARVA_TOOL_SAMTOOLS` sets an explicit samtools). Older versions than 2.9 are *Incompatible
version* (no `--nano-hq`); other 2.9.x versions run with a "not validated" warning. The Docker image
installs Debian bookworm's `flye` (2.9.1) and `samtools` (1.16.1); 2.9.1 has not been validated yet.
A bacterial genome needs a few GB of memory; Flye's own benchmarks list about 2 GB for *E. coli*
PacBio reads at 50×.
The assembly charts, the comparison and the assembly-graph view are drawn by ARVA in the browser from
the stored statistics and the GFA file; they need no further tool. To explore a large graph in full,
download `assembly_graph.gfa` and open it in a graph viewer such as Bandage (not installed by ARVA).

### QUAST (assembly evaluation)

The Assembly tab evaluates and compares a sample's assemblies with QUAST, optionally against a reference
genome imported into the sample as FASTA. Ubuntu 24.04 has no QUAST package; install it from PyPI
into its own virtual environment, with minimap2 for reference-based evaluation:

```bash
python3 -m venv ~/.arva-tools/quast
~/.arva-tools/quast/bin/pip install "setuptools==80.9.0"
~/.arva-tools/quast/bin/pip install --no-build-isolation "quast==5.2.0" "joblib==1.5.2" "simplejson==3.20.2"
export ARVA_TOOL_QUAST=~/.arva-tools/quast/bin/quast.py
sudo apt install minimap2                # Ubuntu 24.04: 2.26; Debian bookworm: 2.24
```

Validated: QUAST 5.2.0 (GPL-2.0; PyPI source package, sha256 `23649fbd…0ad7`) with joblib 1.5.2 and
simplejson 3.20.2 on Python 3.12 (Ubuntu's `python3.12`, as in the Docker image), Linux x86-64; the
environment needs about 145 MB. QUAST 5.2.0 imports `distutils`, which Python 3.12 no longer has: the
pinned setuptools provides it, and building with `--no-build-isolation` uses that same setuptools. The
install compiles nothing and downloads nothing else; QUAST's optional parts (gene prediction, BUSCO,
read analysis, reference search) are not used by ARVA. With a reference QUAST needs minimap2 2.19 or
later: it uses its own compiled copy when present, else `minimap2` on PATH, and would otherwise compile
its bundled source into its installation folder during the run, which ARVA refuses (the Tools page
notes when minimap2 is missing; evaluation without a reference still works). Runs were checked offline
(no network namespace): nothing is fetched, and nothing is written outside the job's folder. Under
CPython 3.13.15 and later 3.13 releases QUAST 5.2.0 leaves `quast.log` empty (a change in Python's
logging); ARVA keeps QUAST's console output in every case, but Python 3.12 is the validated setup.
QUAST warns that it cannot set the `en_US.UTF-8` locale when that locale is absent; only the dates
written in its HTML report depend on it. `scripts/test-all.sh` uses `~/.arva-tools/quast/bin/quast.py`
when it exists; the Docker image installs QUAST and minimap2.

### Optional: POD5 run metadata (pod5 library)

ARVA recognises POD5 raw-signal files without any library. To read their run metadata (reads, signal
duration, sample rate, flow cell, kit, protocol, software) install Oxford Nanopore's `pod5` library
(MPL-2.0) into ARVA's own Python environment yourself; the Docker image already includes it.

```bash
apps/api/.venv/bin/pip install "pod5==0.3.49"        # or: pip install -e "apps/api[pod5]"
```

Wheels exist for Linux x86-64 and ARM64 (glibc 2.28 or newer), Windows and Apple Silicon (macOS 14
or newer). There is no wheel for Intel Macs; install bioconda's `lib-pod5` / `pod5` 0.3.49 there
instead. The package pulls in pyarrow 22 (about 450 MB with its dependencies). ARVA does not
basecall: basecall with Dorado (or MinKNOW) outside ARVA and import the FASTQ.

### Sample metadata tables (CSV / Excel)

Importing and exporting sample metadata needs no extra step: `openpyxl==3.1.5` (MIT; it pulls in
`et_xmlfile` 2.0.0, MIT AND PSF-2.0) is a regular dependency of the API, installed by
`scripts/setup-dev.sh`, by `pip install ./apps/api` and in the Docker image. It is pure Python (one
wheel for every platform, including Intel and Apple Silicon Macs) and makes no network access. The
version is pinned because ARVA reads one private attribute of its read-only worksheets. CSV files are
read with Python's own `csv` module. Old `.xls`, `.xlsm`, `.xlsb` and `.ods` files are refused with
"save the sheet as .xlsx or CSV UTF-8"; no other spreadsheet library is used. Limits are set with the
`ARVA_METADATA_MAX_*` variables below; uploads above `ARVA_METADATA_MAX_BYTES` are refused with
`413` before the body is received.

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
| `ARVA_METADATA_MAX_BYTES` | 10485760 (10 MiB) | Largest sample-metadata table (CSV or .xlsx) accepted |
| `ARVA_METADATA_MAX_ROWS` | 10000 | Data rows per metadata table |
| `ARVA_METADATA_MAX_COLUMNS` | 256 | Columns per metadata table |
| `ARVA_METADATA_MAX_CELL_CHARS` | 10000 | Characters per cell of a metadata table |
| `ARVA_TOOLS_PATH` | — | Extra folders (`:`-separated) searched for external tools |
| `ARVA_TOOL_<ID>` | — | Explicit executable for one tool (`SEQKIT`, `FASTQC`, `FASTP`, `FILTLONG`, `MULTIQC`, `NANOPLOT`, `FLYE`; `SAMTOOLS` for Flye's helper) |
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
| Metadata table refused: "save the sheet as .xlsx or CSV UTF-8" | The file is `.xls`, `.xlsm`, `.xlsb` or `.ods`: open it and save it as Excel Workbook (.xlsx) or CSV UTF-8 |
| Metadata rows blocked by "ambiguous" dates | Dates such as 03/05/2024: choose the date order in the import dialog, or write dates as YYYY-MM-DD |
| File marked *Unrecognised* | Content does not start with `@` (FASTQ) or `>` (FASTA) after decompression |
| A tool shows *Not installed* | Install it (see above) or point `ARVA_TOOL_<ID>`/`ARVA_TOOLS_PATH` at it, then **Re-detect** |
| MultiQC shows *Incompatible version* 1.18 | That is the Ubuntu/Debian package: install MultiQC 1.35 from PyPI as above and set `ARVA_TOOL_MULTIQC` for the API and the worker |
| Project QC report fails with "did not report every input exactly once" | MultiQC skipped or merged an input; the job log lists which. Re-run the tool for that file, or leave the sample out |
| Project QC overview shows "—" with "statistics for 1 of 2 files" | Read totals are only shown when every imported FASTQ/FASTA file of the sample has read statistics: compute them for the remaining files on the sample's Files tab |
| Project QC overview shows no depth | Enter the expected genome size when computing read statistics, the same size for every imported read file of the sample; ARVA never assumes one |
| Flye assembly fails in the repeat stage with "empty sequence" | Flye ran without its `flye-samtools` helper: install samtools and re-detect; ARVA links the helper for each run |
| Flye: "found no read longer than the minimum overlap" | The reads are shorter than 1,000 bp (or than the minimum overlap you set): Flye needs long reads |
| Flye: "could not assemble the reads" | Too few reads or too little coverage, or a read type that does not match the data (check the error rate on the Read statistics tab) |
| Two Flye runs on the same reads differ | Expected with more than one thread: Flye is not deterministic then; the thread count is recorded with each run |
| NanoPlot asks to confirm long reads | The sample's sequencing technology is not Nanopore or PacBio: set it in the sample's Metadata tab, or tick the confirmation if the file does hold long reads |
| fastp report shows tables but no charts inside ARVA | Expected: its charts load plotly.js from the internet, which ARVA blocks; ARVA's own comparison charts cover the same data, and the original report can be downloaded |
