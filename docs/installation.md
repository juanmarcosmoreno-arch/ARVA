# Installation

## Option A — Docker Compose

Requirements: Docker Desktop (macOS, Apple Silicon or Intel) or Docker Engine + Compose v2 (Linux).
All base images are multi-architecture.

```bash
git clone <repository> arva && cd arva
cp .env.example .env              # optional: set ARVA_DB_PASSWORD
docker compose up -d --build      # on a Mac: scripts/start.sh --build (see below)
```

- Web interface: <http://localhost:8080>
- API + OpenAPI docs: <http://localhost:8000/docs>

Services: `postgres`, `redis`, `api` (runs migrations on start), `worker`, `backup` (metadata backups, see
[External disk](#external-disk-data-and-databases-outside-the-mac)), `web` (nginx). Ports are bound to
`127.0.0.1`. Projects live in the `arva-data` volume (mounted at `/data`) and reference databases installed from the
Tools & Databases page in the `arva-databases` volume (mounted at `/databases`, `ARVA_DB_DIR`). To keep them in
host folders instead, for example on an external disk (Bakta's full database needs tens of gigabytes), start ARVA
with `scripts/start.sh --data-dir … --databases-dir …`: see [External disk](#external-disk-data-and-databases-outside-the-mac).
`docker-compose.yml` no longer reads `ARVA_DATA_DIR`, `ARVA_DATABASES_DIR` or `ARVA_IMPORT_DIR`; the launcher
warns when they are still set.

```bash
docker compose logs -f worker     # follow analysis execution
docker compose down               # stop (volumes are kept)
```

The `import/` folder of the repository is mounted read-only at `/import` in the `api` and `worker`
containers for [server-side import](#importing-large-files-from-a-server-folder); choose another host folder with
`scripts/start.sh --import-dir /absolute/path`.

### On a Mac: the launcher and the performance profile

Start ARVA with `scripts/start.sh` (it runs `docker compose up -d`, passing on extra arguments such as
`--build`). Before starting, it reads which Mac this is and what Docker Desktop gives its Linux virtual machine,
and passes these facts to the `api` and `worker` containers as `ARVA_HOST_*` variables:

| Fact | Read with | Source of the key or field |
|---|---|---|
| Model name (`MacBook Air`, `Mac Studio`, …) | `system_profiler -json SPHardwareDataType` → `machine_name` | system_profiler(8); field names as parsed by mondoohq/cnquery |
| Model identifier, chip | `sysctl -n hw.model`, `machdep.cpu.brand_string` (else `chip_type`) | sysctl(3) |
| Performance and efficiency cores | `sysctl -n hw.nperflevels`, `hw.perflevelN.physicalcpu` (N = 0 is the fastest kind); else `number_processors` (`proc TOTAL:PERFORMANCE:EFFICIENCY`) | Apple, "Determining system capabilities" |
| Physical and logical cores, memory | `sysctl -n hw.physicalcpu`, `hw.logicalcpu`, `hw.memsize` | same |
| macOS version, architecture | `sw_vers -productVersion`; `uname -m` (`sysctl.proc_translated` = 1 under Rosetta means arm64) | sw_vers(1); Apple, "About the Rosetta translation environment" |
| Docker Desktop's CPUs and memory | `docker info --format '{{.NCPU}} {{.MemTotal}}'` | Docker Engine API, `SystemInfo` |

Only the model name, chip and core counts are kept from system_profiler's report; the serial number and other
identifiers are never passed on, and nothing leaves the computer. Intel Macs and older macOS lack the
`hw.perflevel*` keys: ARVA then uses the physical cores (Intel) or system_profiler's processor field (Apple
silicon). Every value is validated and bounded again by the API (`app/services/host.py`); a missing or malformed
one is shown as unknown. Once ARVA runs, the launcher prints the profile in use and, if Docker Desktop's resources
do not suit it, what to set. A plain `docker compose up` keeps working: the computer is then unknown and the
profile follows the CPUs and memory the containers can use.

**Not yet validated on a real Mac.** The launcher and the macOS readers were written from Apple's documentation
and the open-source code cited above, and tested only with constructed outputs of `sysctl`, `system_profiler`,
`sw_vers` and `docker` (`apps/api/tests/test_start_script.py`, `test_performance.py`).

**Profiles** (ARVA's own heuristics, not measurements; Settings → Performance shows the values on this computer):

| Profile | Threads per tool | Memory per job | CPU priority | Chosen automatically for |
|---|---|---|---|---|
| Light (*Ligero*) | half the cores | 50 % of the memory ARVA can use | `nice 15` | MacBook Air, 12-inch MacBook; other computers with ≤ 4 cores or < 8 GB |
| Balanced (*Equilibrado*) | cores − max(1, cores ÷ 4) | 70 % | `nice 10` | MacBook Pro, Mac mini, iMac; other computers in between |
| Maximum (*Máximo*) | every performance core when efficiency cores remain, else cores − 1 | 85 % | `nice 5` | Mac Studio, Mac Pro; other computers with ≥ 12 cores and ≥ 32 GB |
| Custom (*Personalizado*) | chosen | chosen | `nice 10` | — |

"Cores" are the Mac's performance cores (Apple silicon), else its physical cores, else the CPUs the container can
use; the result is always capped by the CPUs and memory ARVA can actually use (CPU affinity, cgroup v2 `cpu.max`
or v1 `cpu.cfs_quota_us`, cgroup memory limit, else `MemTotal`). The memory per job is the default memory limit of
the tools that have one — SPAdes (`-m`), SPAdes inside Unicycler (`--spades_options "-m N"`), Pilon (Java
`-Xmx`) and samtools sort (`-m` per thread, only when 768M per thread, samtools' default, would exceed it); a
dialog may ask for up to all the memory ARVA can use. Flye, Racon, minimap2, BWA, QUAST, Bakta, Prokka, fastp,
FastQC, SeqKit, NanoPlot, Filtlong and MultiQC have no memory option: give them fewer threads instead. Tool
dialogs take their default thread count from the profile (still editable up to the usable CPUs). Flye's output
can depend on its thread count, so each run records it.

Tools start through `nice -n <N>` (the `nice` executable found on `PATH`; the recorded commands are the tools'
own). Inside Docker Desktop this only orders work inside the Linux virtual machine, where it keeps ARVA's own
API and interface responsive; for macOS, the real limits are the thread count and the CPUs and memory Docker
Desktop gives that machine.

**Docker Desktop resources per Mac class** (ARVA's recommendation for the profile in use; Docker Desktop →
Settings → Resources → Advanced → *CPU limit* and *Memory limit*, then apply and run `scripts/start.sh` again):

| Profile on this Mac | CPU limit | Memory limit |
|---|---|---|
| Light (MacBook Air) | the profile's threads + 1, at most the Mac's logical CPUs | 50 % of the Mac's memory |
| Balanced (MacBook Pro, Mac mini, iMac) | same rule | 60 % |
| Maximum (Mac Studio, Mac Pro) | same rule | 75 % |
| Custom | the custom threads + 1, same cap | 60 % |

For example, for a (constructed) MacBook Pro with 8 performance and 2 efficiency cores and 16 GB the
recommendation is 7 CPUs and 9 GB. ARVA asks for more when Docker Desktop gives fewer CPUs or less than 90 % of
the recommended memory (the virtual machine reports a little less than its setting), and for less memory when
Docker Desktop's share would leave macOS less than a quarter. More CPUs than recommended do no harm. Docker's
documentation gives 50 % of the host's memory as the default memory limit.

**Changing or overriding it.** Choose another profile, or Custom threads and memory, in Settings → Performance
(`PUT /api/v1/system/performance`; `GET` returns every detected fact with its source). The choice is stored in the
database (`app_settings`), so the worker uses it too, and applies to jobs created afterwards; each job records the
resources it was given (`analysis_jobs.resources`: profile, threads, memory limit, priority, computer), shown in
its history and in the reports. `ARVA_TOOL_THREADS` and `ARVA_TOOL_MEMORY_GB`, when set, cap every profile and
every request. Without Docker (Option B on a Mac), ARVA reads the Mac's facts itself with the same keys.

When a tool is killed with SIGKILL (exit status −9, or 137 from a wrapper), which usually means the computer or
the container ran out of memory, the job's failure reason says so, with the memory ARVA could use, the threads and
memory limit of the run, and what to change.

## External disk: data and databases outside the Mac

The aim: on the Mac only the program (this repository and Docker Desktop); projects, their files, reference
databases and metadata backups on an external disk, which can also be moved to another Mac. Databases you already
have (a Bakta full database of about 80 GB, an ANI or taxonomy database, …) are used where they are, read-only.

**Not yet validated on a real Mac.** The launcher's macOS checks were written from the sources cited below and
tested with constructed `df`, `diskutil` and `docker` outputs (`apps/api/tests/test_storage_launcher.py`); the
Docker Compose override and the backups were checked with the real `docker compose config` and the real PostgreSQL
16 `pg_dump`/`pg_restore` here (Linux), not with Docker Desktop.

### Recommended layout

```
/Volumes/<Disk>/ARVA/data         projects: raw/, processed/, results/, reports/, logs/, backups/ (metadata)
/Volumes/<Disk>/ARVA/databases    databases ARVA downloads (Database Manager)
/Volumes/<Disk>/…                 databases you already have, added read-only
```

For example, with a disk named `JM` whose reference data are under `/Volumes/JM/BioInf` (use your own disk and
folder names; nothing here is fixed):

```bash
mkdir -p /Volumes/JM/ARVA/data /Volumes/JM/ARVA/databases
scripts/start.sh --data-dir /Volumes/JM/ARVA/data \
                 --databases-dir /Volumes/JM/ARVA/databases \
                 --add-databases /Volumes/JM/BioInf/bakta/db \
                 --import-dir /Volumes/JM/BioInf/runs
```

Then, in Tools & Databases → Reference databases → *Register existing folder…*, browse the added folder (it is
listed as on the Mac, read-only), choose the database's own folder (for Bakta the one holding `version.json`) or
file, and look at the detection preview: the kind, the version and the file it was read from, the files checked and
any problem. You can also type the path as on the Mac (`/Volumes/JM/BioInf/bakta/db`) or as ARVA sees it
(`/databases-external/<n>/…`). To download a version instead, choose it under its kind: it is installed into the
database folder (or a folder inside it that you name), with the catalogue's version, size and checksum. See
[Reference databases](#reference-databases-database-manager).

### The launcher's options

| Option | Mounted at | Access | Holds |
|---|---|---|---|
| `--data-dir PATH` | `/data` | read-write | projects (raw, processed, results, reports, logs) and the metadata backups |
| `--databases-dir PATH` | `/databases` | read-write | databases ARVA downloads |
| `--add-databases PATH` (repeatable) | `/databases-external/<n>` | read-only | existing database folders, used in place and never modified or deleted |
| `--remove-databases PATH` | — | — | stops using an added folder (the folder is not touched) |
| `--import-dir PATH` | `/import` | read-only | sequencing runs to import |
| `--show-config` | — | — | shows and checks the saved locations, then stops |
| `--reset-config` | — | — | forgets the saved locations (no folder is touched); Docker volumes are used again |

The choices are saved in `${XDG_CONFIG_HOME:-~/.config}/arva/arva.conf` (folder mode 700, file mode 600) as
`KEY=VALUE` lines (`ARVA_DATA_DIR`, `ARVA_DATABASES_DIR`, `ARVA_IMPORT_DIR`, `ARVA_ADD_DATABASES` once per folder, and
the disk each writable folder was on). The file is read line by line and never executed (no `source`, no `eval`): a
value is only a path; a link, a file of another user or one others may write is refused. Every later
`scripts/start.sh` uses the saved locations; `scripts/restore.sh` and `scripts/backup.sh` use them too. `<n>` is the
POSIX `cksum` of the folder's path, so it stays the same as long as the path does (registered databases keep
working).

**Changing a location needs a restart**, because a folder is mounted when the containers start: run
`scripts/start.sh` with the new option; Settings → Storage shows the exact commands with the current folders.

### What is checked before Docker starts

For every folder: an absolute path without control characters, an existing folder (links resolved), readable, and
writable for the data and database folders. Then:

- **The disk.** `df -Pk` gives the folder's mount point and its free and total space (POSIX output; on macOS `-P`
  also leaves out the inode columns, Apple file_cmds `df/df.c`). The mount point of each writable folder is saved
  when the folder is chosen; if the folder later lies on another mount point (typically `/`, when the external disk
  is not connected and an empty folder with the same path was left on the startup disk), **ARVA refuses to start**
  and says to connect the disk. A missing folder is refused as well. Nothing is created in either case. An added
  database or import folder that is missing is left out with a warning; its databases show *unavailable (disk not
  connected)* and are not deleted.
- **The filesystem** (on a Mac): `diskutil info -plist <mount point>` (`info` accepts a mount point, diskutil(8));
  ARVA reads `FilesystemType` and `FilesystemName` (else `FilesystemUserVisibleName`), the keys parsed by the
  open-source corpnewt/gibMacOS and brokeyourbike/mountefi. exFAT shows `FilesystemType` `exfat` (diskutil's "Type
  (Bundle): exfat", as seen in user reports); that FAT shows `msdos` is not confirmed, so a name containing "FAT"
  counts too. On Linux, GNU `stat -f -c %T`.
- **Free space**: a warning below 20 GB on the data or database disk (ARVA's own threshold).
- **Docker Desktop file sharing**: Docker Desktop shares `/Users`, `/Volumes`, `/private`, `/tmp` and `/var/folders`
  by default (Docker Desktop settings documentation), so folders on external disks need nothing. A folder elsewhere
  must be added in Docker Desktop → Settings → Resources → File sharing, otherwise Docker reports "Mounts denied";
  the launcher says so. If macOS asks whether Docker may access the disk, allow it (System Settings → Privacy &
  Security → Files & Folders).

The folders reach Docker Compose through a generated override file (`~/.config/arva/compose.storage.yml`,
rewritten at every start) as **long-syntax bind mounts with `create_host_path: false`**. The Compose
specification says of `create_host_path`: "Creates a directory at the source path on the host if it doesn't exist.
Defaults to `true`" — also in the long syntax, and the short syntax always creates it — so it is set to false: if a
disk disappears between the check and the start, Docker refuses to start instead of mounting a new empty folder on
the internal disk. The override contains no path, only `${ARVA_HOST_…}` variables that the launcher sets after its
checks; without them `docker compose` refuses to use it. The host paths and filesystems are also passed to the
containers as `ARVA_HOST_DATA_DIR`, `ARVA_HOST_DATA_FS`, `ARVA_HOST_DATABASES_DIR`, …,
`ARVA_HOST_EXTERNAL_DB_<n>` (validated again by the API and only displayed). A plain `docker compose up` uses the
Docker volumes and ignores the saved folders.

### Filesystem: use APFS (or Mac OS Extended)

Format the external disk as **APFS** (or Mac OS Extended, *Mac OS Plus* in Spanish macOS). exFAT and FAT keep no
symbolic links and no Unix permissions: the Bakta database contains a symbolic link (`amrfinderplus-db/latest` →
`2024-12-18.1` in the light 6.0 archive ARVA installed), and ARVA stores originals read-only. The launcher and
Settings → Storage warn about exFAT and FAT. Reformatting erases the disk: copy the data elsewhere first.

### Where the metadata lives, and the backups

Projects, samples, files, jobs and settings are recorded in PostgreSQL, which **stays in the `postgres-data` Docker
volume** (inside Docker Desktop's disk image). It is not put on the external disk: PostgreSQL refuses to start
unless its data folder belongs to the server's user and has mode 0700 or 0750 (`checkDataDir()`,
`src/backend/utils/init/miscinit.c`: "data directory … has wrong ownership", "Permissions should be u=rwx (0700) or
u=rwx,g=rx (0750)"), which exFAT and FAT cannot store; on a Docker Desktop bind mount ownership and durable writes
go through the file-sharing layer, which ARVA has not validated; and a disk unplugged under a running database can
damage it.

The external disk is made self-contained by **backups of the metadata**: the `backup` service (the same
`postgres:16.4-alpine` image, so `pg_dump` matches the server; `scripts/metadata-backup.sh`) writes `pg_dump`
archives in custom format into `<data folder>/backups/`:

- automatically every `ARVA_BACKUP_INTERVAL_HOURS` (default 24) and at the first start, `arva-metadata-auto-<UTC
  time>.dump`;
- on request: Settings → Storage → *Back up now*, or `scripts/backup.sh` (`arva-metadata-manual-…`);
- before every restore (`arva-metadata-pre-restore-…`).

Each kind keeps its newest `ARVA_BACKUP_KEEP` (default 14). Every archive is checked with `pg_restore --list` before
it is kept; `backups/.last-result` records the outcome, shown in Settings → Storage. Nothing is written while the
data folder's storage marker is missing (its disk is not connected). The service polls every 30 seconds for a
request from ARVA (`backups/.request`); it needs no Docker socket.

**Restore** (to undo a mistake, or on another Mac):

```bash
scripts/restore.sh --list          # the backups, newest first
scripts/restore.sh latest          # or: scripts/restore.sh arva-metadata-manual-20261028T153000Z.dump
```

It asks for confirmation (`--yes` skips it), backs up the current metadata, stops `api`, `worker` and `backup`,
restores the archive into a new database and only when that succeeded replaces the current one (so a failed restore
changes nothing), then starts ARVA again, whose start-up upgrades the restored metadata to this version
(`alembic upgrade head`). Files in the data folder are not touched. A backup made by a newer ARVA cannot be restored
into an older one. Tested here with a scratch database (`apps/api/tests/test_metadata_backup.py`).

### The storage marker: never writing to the wrong disk

At its first use the data folder gets a marker, `<data folder>/.arva-storage`, with an ID that is also recorded in
the metadata. ARVA checks it at start-up, before every change through the API and before every job:

| Situation | Status | What happens |
|---|---|---|
| Marker present, same ID | `ok` | normal |
| Folder missing or unreadable | `unavailable` | changes refused (HTTP 503, coded message), jobs fail, `/health` says `degraded` |
| Marker missing although the metadata knows one (disk not connected, an empty folder in its place) | `missing` | same |
| Another ID (another disk in its place) | `mismatch` | same |
| Marker present, new metadata, backups beside it (another Mac, reset volume) | `restore_needed` | same, until you restore (`scripts/restore.sh latest`) or choose *Use this folder with the current metadata* in Settings → Storage |
| Marker damaged | `invalid` | same |

A refused change answers `503` with `{"detail", "code", "params"}` (`storage_missing`, …), shown translated in the
interface. A job whose data folder is not available fails with `storage_unavailable` before writing anything (not
even its log file; the log stays in the database); one whose disk disappears while it runs fails with
`storage_lost`. Settings → Storage and Performance stay usable meanwhile. Reference databases whose folder is on a
disk that is not connected show *unavailable (disk not connected)*: they are not verified, used or deleted (ARVA
refuses to delete the record of an installed one, whose files would be left behind), and a verification that finds
the disk gone keeps the database's status.

### Moving the disk to another Mac

1. Install ARVA on the new Mac (Docker Desktop and this repository).
2. Connect the disk and start ARVA with the same folders:
   `scripts/start.sh --data-dir /Volumes/JM/ARVA/data --databases-dir /Volumes/JM/ARVA/databases` (plus
   `--add-databases …` for each added folder). Settings → Storage then shows *This data folder needs its metadata
   back*.
3. `scripts/restore.sh latest`.

Added database folders get the same `/databases-external/<n>` only if their paths are the same on the new Mac (same
disk name); otherwise register them again.

**Moving existing data from the Docker volumes to the disk** (once; not run here): stop ARVA (`docker compose
down`), copy the volumes with an image ARVA already uses, then start with the launcher. The storage marker comes
with the data, so the metadata recognises the folder:

```bash
docker volume ls | grep arva                     # arva_arva-data, arva_arva-databases (project "arva")
docker run --rm -v arva_arva-data:/from:ro -v /Volumes/JM/ARVA/data:/to postgres:16.4-alpine cp -a /from/. /to/
docker run --rm -v arva_arva-databases:/from:ro -v /Volumes/JM/ARVA/databases:/to postgres:16.4-alpine cp -a /from/. /to/
scripts/start.sh --data-dir /Volumes/JM/ARVA/data --databases-dir /Volumes/JM/ARVA/databases
```

Installed databases are recorded at `/databases/…`, which stays the same; the volumes can be removed once ARVA
works from the disk (`docker volume rm arva_arva-data arva_arva-databases`).

### Docker Desktop's disk image

Docker Desktop keeps images, containers and volumes (here: the metadata database) in one disk image file. Its
default place is `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw` (Docker Desktop for Mac FAQ).
To keep that off the internal disk too: Docker Desktop → **Settings → Resources → Advanced → Disk image location**
("Specify the location of the Linux volume where containers and images are stored"; Docker asks whether to use or
replace an image already there). Do not move the file in Finder, Docker's FAQ warns. With the disk image on the
external disk, Docker Desktop needs that disk connected to start.

Expected size of ARVA's images, estimated from component sizes (not measured from a build):

| Image | Basis | Estimate |
|---|---|---|
| `arva-api` (API and worker) | `python:3.12.7-slim-bookworm` (45 MB compressed download, Docker Hub); Debian tool packages ≤ 1.1 GiB installed (upper bound: the dependency closure on Ubuntu 24.04, which counts libraries the base already has); MultiQC 1.2 GB, NanoPlot 0.59 GB, QUAST 0.15 GB, Bakta 0.32 GB as venvs (measured here); ARVA with pod5 ≈ 0.6 GB (its venv here) | about 4 GB |
| `postgres:16.4-alpine`, `redis:7.4.1-alpine`, `nginx:1.27.2-alpine` | 99, 19 and 23 MB compressed downloads (Docker Hub) | a few hundred MB unpacked |
| `arva-web` and build cache | nginx plus the built interface; the `node:22.11.0-alpine3.20` build stage (54 MB compressed) and `node_modules` stay in the build cache | a few hundred MB to about 1 GB |

So reserve about 6 GB for the images and build cache, plus the metadata volume (small) and room for rebuilds;
`docker system df` shows the real figures. Building with `--build-arg ARVA_PYTHON_TOOLS=""` leaves out the Python
report tools (about 2.3 GB).

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

- **Docker**: the API/worker image already contains them (Debian bookworm packages: SeqKit 2.3.0 binary,
  FastQC 0.11.9, fastp 0.23.2, Filtlong 0.2.1 — validated with ARVA), and for assembly and polishing Flye 2.9.1,
  SPAdes 3.15.5, Unicycler 0.5.0, Racon 1.5.0, Pilon 1.24, BWA 0.7.17, MUMmer 3.23, BLAST+, samtools 1.16.1 and
  minimap2 2.24 (SPAdes, Unicycler, Racon, Pilon, BWA and MUMmer are the releases validated on Ubuntu 24.04; Flye
  2.9.1, samtools 1.16.1 and minimap2 2.24 are not validated, and each job records the versions it ran).
- **Ubuntu 24.04 / Debian**: `sudo apt install seqkit fastqc fastp filtlong flye samtools minimap2 spades unicycler
  racon ncbi-blast+ pilon bwa mummer default-jre-headless` (Ubuntu 24.04: SeqKit 2.3.0, FastQC 0.12.1, fastp 0.23.4,
  Filtlong 0.2.1, Flye 2.9.3, SPAdes 3.15.5, Unicycler 0.5.0, Racon 1.5.0, Pilon 1.24, BWA 0.7.17, samtools 1.19.2,
  minimap2 2.26, MUMmer 3.23 — validated; minimap2 is also used by QUAST, below).
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
### SPAdes and Unicycler (short-read and hybrid assembly)

```bash
sudo apt install spades unicycler racon ncbi-blast+   # Ubuntu 24.04: SPAdes 3.15.5, Unicycler 0.5.0, Racon 1.5.0, BLAST+ 2.12.0
```

Validated: SPAdes 3.15.5 (GPL-2.0-only; Ubuntu package 3.15.5+dfsg-7) and Unicycler 0.5.0 (GPL-3.0-or-later;
Ubuntu package 0.5.0+dfsg-1) — the same upstream releases as Debian bookworm, which the Docker image installs.
SPAdes older than 3.14 (no `--isolate`) is *Incompatible version*. Unicycler calls SPAdes for short reads, Racon
for long reads and makeblastdb/tblastn (NCBI BLAST+) to rotate circular replicons; ARVA finds each of them like a
tool (`ARVA_TOOL_SPADES`, `ARVA_TOOL_RACON`, `ARVA_TOOL_MAKEBLASTDB`, `ARVA_TOOL_TBLASTN`, `ARVA_TOOLS_PATH`,
`PATH`) and passes their paths to Unicycler. Without BLAST+ the Tools page reports Unicycler as *Detection failed*;
without SPAdes or Racon it notes which modes remain. Debian's unicycler package also pulls in Pilon (with a Java
runtime), Bowtie 2 and BCFtools, which Unicycler 0.5.0 does not call. Both tools run on the distribution's
`/usr/bin/python3`.

SPAdes needs memory in proportion to the genome and to the read errors (the SPAdes manual lists about 8 GB for an
*E. coli* isolate). ARVA passes a memory limit to SPAdes (`-m`, also inside Unicycler); by default
min(250 GB, the performance profile's memory per job), at most the memory ARVA can use (and `ARVA_TOOL_MEMORY_GB`
when set). When SPAdes needs more, it stops and the job says so.

### Polishing (Racon, Pilon)

```bash
sudo apt install racon minimap2 pilon bwa samtools mummer default-jre-headless
# Ubuntu 24.04: Racon 1.5.0, minimap2 2.26, Pilon 1.24, BWA 0.7.17, samtools 1.19.2, MUMmer 3.23 (dnadiff 1.3), OpenJDK 21
```

Validated: Racon 1.5.0 (MIT), Pilon 1.24 (GPL-2.0), minimap2 2.26 (MIT), BWA 0.7.17 (MIT and GPL-2.0-or-later
per Debian's copyright file), samtools 1.19.2 (MIT) and MUMmer 3.23 (dnadiff 1.3, Artistic licence). Debian
bookworm, which the Docker image installs, ships the same Racon, Pilon, BWA and MUMmer releases, with minimap2 2.24
and samtools 1.16.1 (not validated; ARVA records the versions each run used). Long-read polishing needs racon,
minimap2 and samtools; short-read polishing needs Pilon, Java, BWA and samtools; MUMmer is optional but without it
there is no direct evidence of Racon's changes (Pilon's own list of changes is still kept). The polishing dialog
lists what is missing for each strategy.

Pilon is a Java program. Debian's `/usr/bin/pilon` runs it with a fixed 16 GB heap, so ARVA runs the jar it names
(`/usr/share/java/pilon.jar`) with `java -Xmx<heap>` itself, the heap chosen in the dialog (default min(16 GB, the
performance profile's memory per job)). For another installation set `ARVA_TOOL_PILON` to the path of `pilon.jar`. Debian's build
prints no version number (`Pilon version [COMMIT] [DATE]`), so ARVA reads the version from dpkg and says so on the
Tools page. `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS` and `JDK_JAVA_OPTIONS` are removed from every tool's environment,
as they would change the recorded heap. Medaka is not integrated (it needs a model matching the reads' basecaller,
and downloads models).

The assembly charts, the comparison and the assembly-graph view are drawn by ARVA in the browser from
the stored statistics and the GFA file; they need no further tool. To explore a large graph in full,
download `assembly_graph.gfa` and open it in a graph viewer such as Bandage (not installed by ARVA).

### Cancelling jobs and resuming Flye

Queued and running jobs can be cancelled from the Assembly tab and from a sample's Analysis history (or with
`POST /api/v1/jobs/{id}/cancel`). The worker stops a running tool within about 5 seconds; the job stays
*Cancelling…* until then. Partial outputs are removed and the job log is kept. When a Flye run is stopped from
outside after its first stages (cancelled, time limit, killed or out of memory), ARVA keeps Flye's work folder in
`<ARVA_STORAGE_ROOT>/checkpoints/` so the run can be resumed with Flye's `--resume` (same reads, options, threads
and Flye version) or the folder discarded; it is as large as Flye's intermediate files (tens of MB for a
bacterial genome). Nothing more needs installing.

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

### Bakta and Prokka (genome annotation)

The Annotation tab annotates an assembly with Bakta (recommended) or Prokka. Install the programs Bakta's steps
call, and Prokka, from the distribution, and Bakta from PyPI into its own virtual environment:

```bash
# Ubuntu 24.04 (validated): tRNAscan-SE 2.0.12, Aragorn 1.2.41, Infernal 1.1.5, PILER-CR 1.06, DIAMOND 2.1.9,
# HMMER 3.4, Prodigal 2.6.3, barrnap 0.9, Prokka 1.14.6+dfsg-6 (about 225 MB with their dependencies)
sudo apt install trnascan-se aragorn infernal pilercr diamond-aligner hmmer prodigal barrnap prokka
python3 -m venv ~/.arva-tools/bakta
~/.arva-tools/bakta/bin/pip install "bakta==1.12.2" "biopython==1.88" "xopen==2.1.0" "requests==2.34.2" \
  "alive-progress==3.3.0" "PyYAML==6.0.3" "pyrodigal==3.7.1" "pyhmmer==0.12.3" "pyCirclize==1.10.1"
export ARVA_TOOL_BAKTA=~/.arva-tools/bakta/bin/bakta     # about 320 MB; Python 3.12.3 here
```

Then install the Bakta database from **Tools & Databases → Databases** (light 6.0 is 3.7 GiB unpacked). Bakta's
own `bakta_db` is not needed.

What Bakta can do depends on the programs it finds: at start-up it checks one for each step and stops if one is
missing or too old. ARVA runs the same checks before every run and passes Bakta's own `--skip-*` options for the
steps that cannot run, recording why (the Tools page and the run dialog list them). With the Ubuntu 24.04
packages above:

- **CDS and sORF are skipped.** Bakta 1.12.2 needs AMRFinderPlus ≥ 4.2.7 (no Ubuntu or Debian package) and
  DIAMOND ≥ 2.2.0 (Ubuntu has 2.1.9) for CDS, and DIAMOND for sORF. ARVA does not download other binaries; with
  AMRFinderPlus and a recent DIAMOND on PATH (or `ARVA_TOOLS_PATH`) the steps run, but that setup is not
  validated with ARVA yet. Prokka predicts CDS in the meantime.
- **oriC/oriV/oriT are skipped**: BLAST+ 2.12.0 is older than the 2.17.0 Bakta requires.
- **CRISPR is skipped**: Ubuntu's `pilercr 1.06+dfsg-5` passes Bakta's version check but crashes (SIGSEGV) on any
  non-empty input, and Bakta would then only print a warning and report no arrays. ARVA runs PILER-CR on a short
  test sequence before each run and skips the step when it crashes.
- tRNA, tmRNA, rRNA, ncRNA, ncRNA regions, gaps and the circular plot (pyCirclize, drawn offline) run.

Prokka (GPL-3.0-or-later; its README states that its author no longer maintains it and recommends Bakta) uses the
databases of the Debian package in `/usr/share/prokka/db` (104 MB). They are not indexed, and Prokka refuses
them until `prokka --setupdb` has run in a writable folder; ARVA does that inside each job (about 150 MB while the
job runs, removed after it) and never writes to `/usr/share/prokka`. Debian's package has no HMM databases, and
MinCED (CRISPR) and SignalP are not packaged, so those steps do not run. Prokka builds shell commands from its
options internally, so ARVA restricts genus, species, strain and locus tags to letters, digits and a few
punctuation marks; contig names longer than 37 characters can be replaced with `contig_1`, … for Prokka.

**Docker** (Debian bookworm, not validated with ARVA): the image installs the same packages where bookworm has
them (`trnascan-se`, `infernal`, `hmmer`, `barrnap` and `prokka` are amd64-only) and Bakta into
`/opt/arva-tools/bakta`. Bookworm's versions are older: tRNAscan-SE 2.0.10, Aragorn 1.2.38, Infernal 1.1.4 and
DIAMOND 2.1.3 are below Bakta's minimums, so ARVA's checks skip tRNA, tmRNA, rRNA and ncRNA as well, and say so.
Bookworm's `prokka 1.14.6+dfsg-4` lacks the kingdom protein sets (restored in `1.14.6+dfsg-6`), so ARVA reports
Prokka as unable to annotate there. The database volume is `ARVA_DB_DIR` (`/databases`).

`scripts/test-all.sh` uses `~/.arva-tools/bakta/bin/bakta` when it exists; the real Bakta tests use the light
database at `ARVA_TEST_BAKTA_DB` (default `~/.arva-db/bakta-light/6.0`) and are skipped without it.

**Disk space for annotation** (measured on the development system, 2026-10-28):

| Item | Where | Size |
|---|---|---|
| Bakta 1.12.2 environment | `~/.arva-tools/bakta` (`ARVA_TOOL_BAKTA`) | 319 MB |
| Distribution packages above (Bakta's programs and Prokka) | system | about 225 MB |
| Prokka's indexed databases, per running job | the job's folder, removed after the run | about 150 MB |
| Bakta light database 6.0 | `ARVA_DB_DIR/bakta-light/6.0` (here `ARVA_DB_DIR=~/.arva-db`) | 3,994,877,552 bytes in 47 files and a `latest` link (3.8 GB on disk); the 1,344,199,496-byte archive is needed while it downloads and is deleted after the checked unpacking |
| Bakta full database 6.0 (not installed here) | `ARVA_DB_DIR/bakta-full/6.0` | 84 Gb unpacked (Bakta README), plus the 31,921,769,288-byte archive while downloading |

Keep `ARVA_DB_DIR` outside the repository and outside `ARVA_STORAGE_ROOT` if the databases should survive a
reset of the data folder; the API and the worker must see it at the same path. The Genome Explorer's linear and
circular views, the annotation charts and the report's genome map need no further tools or databases: they are
drawn by ARVA from the annotator's files.

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
(or the folder chosen with `scripts/start.sh --import-dir`). The API **and** the worker must see the folder at the same path. Then use
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

`GET /api/v1/system/storage` reports the figures (also shown on the Import page), with every storage location
(role, folder on the computer as the launcher gave it, folder inside ARVA, read-only or not, free and total space,
filesystem warnings, the data folder's marker) and the metadata backups; Settings → Storage shows them.

## Reference databases (Database Manager)

The **Reference databases** section of the Tools & Databases page knows every kind of database the analyses of
Phase 5 and later read, for any bacterium: Bakta (light and full), AMRFinderPlus, GTDB-Tk reference data, skani
and sylph databases, Mash sketches, Kraken 2 indexes, CheckM2's DIAMOND database, BUSCO lineage datasets,
PlasmidFinder, MOB-suite, VFDB, geNomad, InterProScan (register only), spa types from the Ridom SpaServer (provided
by you, never redistributed) and reference genome collections. [databases/README.md](../databases/README.md) lists
each kind: how ARVA recognises it, where its version is read, which tool versions can use it, whether ARVA can
download it, its licence and citation, and the sources of those facts. The section is organised by kind; several
versions of a kind can be kept, one is the default, and each analysis dialog lets you choose (today: Bakta).

**Not yet validated on a real Mac** (the Mac paths below are constructed in the tests).

### Use the databases you already have, where they are

Add the folder that holds them with the launcher (read-only), for example
`scripts/start.sh --add-databases /Volumes/JM/BioInf`, then *Register existing folder…*:

1. Browse the database folder or an added folder (or type the path as on the Mac) and choose the database's own
   folder or file. ARVA recognises the kind from its files (for example Bakta's `version.json` and required files,
   GTDB-Tk's `metadata/metadata.txt`, Kraken 2's `hash.k2d`, `opts.k2d` and `taxo.k2d`) and shows which file the
   version came from. A parent folder (such as the one `bakta_db download` wrote into) is recognised as holding
   databases in its subfolders, which are offered.
2. When the files do not state the version (skani and sylph databases, Mash sketches, VFDB, MOB-suite, spa types,
   InterProScan), declare it; ARVA may suggest one from the folder or file name. It is recorded as *declared by
   the user*. A CheckM2 DIAMOND file without `CONTENTS.json` is identified by its SHA-256 at the full checksum.
3. Registering makes a **quick verification** (the kind's files are there; their sizes and the version file are
   recorded). ARVA never writes, moves or deletes anything in a registered folder; deleting a registered database
   removes only ARVA's record.
4. The **full checksum** (the SHA-256 of every file, compared with the first one recorded, and with the publisher's
   per-file MD5s where it lists them: a Kraken 2 index's `.md5` file, an NCBI package's `md5sum.txt`, CheckM2's
   `CONTENTS.json`) runs in the background with its progress, and can be cancelled: on 80 GB over USB it can take
   hours. Until then a job records no content checksum for that database, and says so.

A database on a disk that is not connected is shown as *unavailable* and kept as it is (it is not checked, used or
deleted); it is available again as soon as the disk is back at the same path.

### Reference genome collections (species identification by ANI)

A collection of genomes of known species, for FastANI or skani, for any genus. ARVA reads:

- an extracted **NCBI Datasets genome package** (`README.md`, `md5sum.txt`, `ncbi_dataset/data/assembly_data_report.jsonl`,
  `ncbi_dataset/data/dataset_catalog.json`, one `<accession>/` folder with its `*_genomic.fna`): accession,
  organism, strain, type material and NCBI's "reference genome" flag of every genome;
- a **FastANI reference list** (`--rl`, one genome path per line). Paths written as on the Mac are mapped to where
  ARVA sees them through the launcher's folders; a path outside them is refused (add its folder with
  `--add-databases`), and missing files are listed. When the genomes lie in an NCBI package, its metadata are used;
- a **folder of FASTA files** (`.fna`, `.fa`, `.fasta`, `.fas`, also `.gz`; the organism from each first header).

ARVA shows the collection's coverage: genomes, species, genomes per species, type material and reference genomes.
NCBI's package does not record the download date: you give it (ARVA suggests the date of the zip's entries when the
zip is next to the package), and the collection's version is its source, that date and a fingerprint of its sorted
accession list, e.g. `NCBI Datasets 2026-05-27 #3f0c…`. A package **zip** is never registered or changed: ARVA can
extract a copy into a database folder (it shows the size and free space first, refuses unsafe entries, and compares
every file with the package's `md5sum.txt`).

Example (a real case, the paths are the user's own): a FastANI list `staph_refseq_type_references.txt` of 183
RefSeq *Staphylococcus* genomes (82 species, type and reference strains) from an NCBI Datasets package downloaded on
2026-05-27 and extracted in `/Volumes/JM/BioInf/staph_references/staphylococcus_refseq_type_genomes/` (its zip is
there too). With `scripts/start.sh --add-databases /Volumes/JM/BioInf/staph_references`, register either the package
folder or the list (date 2026-05-27); the list's paths written as `/Volumes/JM/BioInf/staph_references/...` are mapped.
A later part will use the collection for species identification; this one registers, validates, lists and records it.

### Download a version into a folder you choose

Each kind ARVA can download lists its versions (only those the publisher offers as a stable, versioned archive with
a published checksum): Bakta 6.0 light and full, GTDB-Tk R232, Kraken 2 Standard 2026-06-26, CheckM2 database 3,
BUSCO bacteria_odb12.2 and geNomad 1.9 (sizes, checksums and sources in
[databases/README.md](../databases/README.md)). A version the tool ARVA runs cannot read is not offered (today only
Bakta is run by ARVA, so the others show *compatibility not checked* with the versions their documentation names).

The dialog asks for the destination, one of the database folders ARVA may write to (the one chosen with
`scripts/start.sh --databases-dir`, which can be on the external disk), and a folder inside it (default
`<key>/<version>`, e.g. `bakta-light/6.0`); it shows the source, licence and terms, the archive size, the space
needed (bytes still to download plus the unpacked size, read in the larger unit) and the usable free space
(`ARVA_MIN_FREE_BYTES` stays free). Nothing starts until you accept the licence and confirm; the API also requires
the confirmed archive size (`confirm_bytes`) and refuses with 507 when the space is insufficient. The worker
downloads from the official URL only (redirects to other hosts are refused), can be cancelled, and keeps a partial
file so the next download resumes it where it was, with an HTTP range request. The MD5 is compared with the
published one (a mismatch deletes the archive), the archive is unpacked with path checks (no absolute or `..`
paths, nothing outside the expected top folder, no links leaving it, no special files), the kind's folder check runs
(Bakta's own for Bakta), the version its files state must be the one offered, ARVA records the SHA-256 of every file
(and compares the publisher's per-file MD5s), moves the folder into place and deletes the archive.

Bakta's own installer `bakta_db download` was examined (Bakta 1.12.2, `bakta/db.py`) and is not used: it needs
AMRFinderPlus installed even to download, reads the list of versions from the `main` branch on GitHub, does not
resume, unpacks with `tarfile.extractall` without a filter, and finally runs `amrfinder_update --force_update`,
which updates the AMRFinderPlus data to whatever release NCBI offers that day (unpinned). ARVA does not run that
update: the light 6.0 archive contains `amrfinderplus-db/2024-12-18.1` (database format 4.0.1), the release its
`version.json` lists. Bakta 1.12.2 needs AMRFinderPlus 4.2.7 or later to use it.

### Default, choice and what jobs record

One database per kind is the default (the first usable one registered or installed becomes it; *Make default*
changes it; an incompatible one cannot be). The Bakta dialog lists the Bakta databases this Bakta can read, the
default preselected, with their version, how the version was known, verification level and folder. Every job
records the database's kind, key, name, version, how the version was known (`file`, `declared` or `checksum`),
content checksum (when the full checksum was computed) and path; the record stays after the database is deleted.

API: `GET /api/v1/databases/kinds`, `GET /databases/catalogue`, `GET /databases/catalogue/{key}/plan`
(`?destination=&folder=`), `POST /databases/downloads` (`{key, confirm_bytes, accept_licence, destination?,
folder?}`), `GET /databases/locations`, `GET /databases/browse?root=&path=`, `GET /databases/detect?path=`,
`POST /databases/register` (`{path, kind?, declared_version?, collection_date?, full_checksum?}`),
`GET /databases/extract/plan?path=`, `POST /databases/extract` (`{path, confirm_bytes, collection_date,
destination?, folder?}`), `GET /databases`, `GET /databases/usage`, `GET /databases/{id}` (with its log),
`POST /databases/{id}/verify` (`{level: quick|full}`), `POST /databases/{id}/default`, `POST /databases/{id}/cancel`,
`DELETE /databases/{id}`. Refusals carry a code (`{detail, code, params}`) that the interface shows in your language.

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
| `ARVA_DB_DIR` | `<ARVA_STORAGE_ROOT>/databases` | Reference databases (Database Manager); Docker: `/databases` |
| `ARVA_EXTERNAL_DB_ROOTS` | `[]` | Existing database folders used in place, read-only (JSON list); set by `scripts/start.sh --add-databases` (`/databases-external/<n>`) |
| `ARVA_BACKUP_INTERVAL_HOURS` | 24 | Docker Compose: hours between automatic metadata backups (`backup` service) |
| `ARVA_BACKUP_KEEP` | 14 | Docker Compose: backups kept of each kind |
| `ARVA_CORS_ORIGINS` | `["http://localhost:5173","http://localhost:4173"]` | Allowed web origins (JSON list) |
| `ARVA_METADATA_MAX_BYTES` | 10485760 (10 MiB) | Largest sample-metadata table (CSV or .xlsx) accepted |
| `ARVA_METADATA_MAX_ROWS` | 10000 | Data rows per metadata table |
| `ARVA_METADATA_MAX_COLUMNS` | 256 | Columns per metadata table |
| `ARVA_METADATA_MAX_CELL_CHARS` | 10000 | Characters per cell of a metadata table |
| `ARVA_TOOLS_PATH` | — | Extra folders (`:`-separated) searched for external tools |
| `ARVA_TOOL_<ID>` | — | Explicit executable for one tool (`SEQKIT`, `FASTQC`, `FASTP`, `FILTLONG`, `MULTIQC`, `NANOPLOT`, `FLYE`, `SPADES`, `UNICYCLER`, `QUAST`, `RACON`, `MINIMAP2`, `BWA`, `SAMTOOLS`, `DNADIFF`; `PILON` takes the path of `pilon.jar`; helpers: `MAKEBLASTDB` and `TBLASTN` for Unicycler, `JAVA` for Pilon) |
| `ARVA_TOOL_THREADS` | — (no cap) | Administrator cap: no tool run gets more threads, whatever the [performance profile](#on-a-mac-the-launcher-and-the-performance-profile) or a request says |
| `ARVA_TOOL_MEMORY_GB` | — (no cap) | Administrator cap on the memory (GB) a tool run may be given (SPAdes' `-m`, also inside Unicycler; Pilon's Java heap; samtools sort) |
| `ARVA_HOST_*` | — | Facts about the computer, set by `scripts/start.sh` on a Mac (`PLATFORM`, `MODEL_NAME`, `MODEL_ID`, `CHIP`, `PERF_CORES`, `EFF_CORES`, `PHYSICAL_CORES`, `LOGICAL_CPUS`, `MEMORY_BYTES`, `OS_VERSION`, `ARCH`, `DOCKER_CPUS`, `DOCKER_MEMORY_BYTES`), and the host folders it mounted with their filesystems (`DATA_DIR`, `DATA_FS`, `DATABASES_DIR`, `DATABASES_FS`, `IMPORT_DIR`, `IMPORT_FS`, `EXTERNAL_DB_<n>`, `EXTERNAL_DB_<n>_FS`); validated and bounded, unknown when empty, only displayed |
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
| A job stays *Cancelling…* | The worker stops the tool at its next check (about 5 s); if the worker is not running, start it. A job whose worker died is ended when cancelled, once the task queue reports it is no longer executing |
| A job stays *Running* after the worker was restarted | Its worker died with it: cancel the job. ARVA ends it at once when the task queue reports it is no longer executing; RQ marks such a task failed at a worker's registry clean-up (when a worker starts, then every 10 minutes) once the dead worker's heartbeat has expired (about 90 s) |
| Flye: "Resume is not offered for this run" | Flye stopped with an error of its own (resuming would repeat it) or before any stage after configure completed; the job log says which. Start a new assembly |
| Flye resume refused: "written by Flye … installed now" | The work folder must be resumed with the Flye version that wrote it; reinstall that version or start a new assembly |
| Batch QC: "The files or results changed since the preview" (HTTP 409) | A file or job changed between the preview and the confirmation; the new preview is shown, confirm again |
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
| SPAdes or Unicycler: "ran out of memory" | Raise the memory limit in the dialog (up to the memory ARVA can use, shown in Settings → Performance) if the computer has more, or assemble fewer reads (e.g. Filtlong/fastp first); on a Mac, give Docker Desktop more memory |
| A job failed: "stopped by the operating system with SIGKILL" | The tool most likely ran out of memory: choose a lighter profile or fewer threads in Settings → Performance, or give Docker Desktop more memory (Settings → Resources → Advanced), then start ARVA again with `scripts/start.sh` |
| Settings → Performance says the computer is unknown | ARVA was started with a plain `docker compose up`: on a Mac start it with `scripts/start.sh`; the profile meanwhile follows the containers' CPUs and memory |
| The Mac gets hot or slow while ARVA works | Choose Light in Settings → Performance (new jobs use it), or fewer threads in the tool's dialog |
| SPAdes refused with "paths with white space" | The storage folder (`ARVA_STORAGE_ROOT`) contains a space or `* ? [ ]`, which Debian's SPAdes launcher splits: move it |
| Unicycler: "needs racon" / "needs tblastn" (HTTP 409) | Install `racon` (long reads) or `ncbi-blast+` (always), then **Re-detect** on the Tools page |
| A SPAdes contig shows a lower coverage than Flye's for the same genome | Expected: SPAdes reports k-mer coverage, which is lower than read depth; ARVA labels each kind and never compares them |
| Pilon: "ran out of Java heap memory" | Raise the Java heap in the polishing dialog (up to the memory ARVA can use) if the computer has the memory |
| Pilon shows *Detection failed*: "does not name the jar it runs" | The `pilon` found is not Debian's launcher: set `ARVA_TOOL_PILON` to the path of `pilon.jar` |
| Racon: "found no overlaps" | No read aligned to the draft: check that the reads belong to the isolate and that the long-read type (minimap2 preset) matches them |
| A Racon-polished contig is a few bases shorter than its draft | Expected: Racon trims its consensus where few reads support it, which happens at contig ends; the polishing result lists the bases removed at each end |
| Polishing reports changes on an assembly that was already correct | Changes are what the polisher did, not proven corrections; compare with a trusted reference (QUAST) to judge them |
| NanoPlot asks to confirm long reads | The sample's sequencing technology is not Nanopore or PacBio: set it in the sample's Metadata tab, or tick the confirmation if the file does hold long reads |
| fastp report shows tables but no charts inside ARVA | Expected: its charts load plotly.js from the internet, which ARVA blocks; ARVA's own comparison charts cover the same data, and the original report can be downloaded |
