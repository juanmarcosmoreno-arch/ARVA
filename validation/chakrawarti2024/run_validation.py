#!/usr/bin/env python3
"""Run ARVA's Oxford Nanopore-only pipeline on the Chakrawarti et al. 2024 isolates, through ARVA's own HTTP API.

For each isolate of isolates.tsv (one at a time, because the disk is small):

 1. download its ONT FASTQ from ENA over HTTPS and check the md5 (and size) that ENA publishes;
 2. create (or reuse) the project "Validation Chakrawarti 2024" and a sample, and import the reads with ARVA's
    server-folder import (the download folder must be one of ARVA_IMPORT_ROOTS);
 3. run, waiting for each job through the API:
    - Filtlong --min_length 1000 --min_mean_q 90, the equivalent of the paper's NanoFilt -l 1000 -q 10 (see
      FILTER_NOTE);
    - Flye --nano-raw (Guppy 4.0.11 HAC, R9.4.1: pre-Guppy5 reads, Flye's help) with --genome-size 2.8m, the size
      the paper gave Flye;
    - Medaka with r941_min_hac_g507 (README "Medaka model decision"), a model medaka 2.1.1 can load but does not
      ship, registered in ARVA's Database Manager through ARVA's own API before the first isolate (setup(): the
      confirmed download from the medaka v2.1.1 tag, checked by ARVA against the published SHA-256); there is no
      fallback: if ARVA refuses Medaka or Medaka fails, the isolate is recorded as failed with the reason;
    - mlst, then S. aureus typing (sccmec, spa, agr), AMRFinderPlus (--organism Staphylococcus_aureus) and species
      identification with skani when a reference collection is registered (otherwise skipped and recorded);
 4. write results/<isolate>.json (ARVA version and commit, tool versions, parameters, commands, ST, alleles, spa,
    SCCmec, agr, AMR genes, timings, peak disk and memory);
 5. delete the downloaded FASTQ and the ARVA sample and, with --start-arva, the sample's imported copy under ARVA's
    raw/ folder (ARVA's sample deletion keeps raw/ by design; this harness removes it to free the disk, see cleanup());
 6. skip isolates that already have results/<isolate>.json, so the run can be resumed.

Before the first isolate, setup() makes sure ARVA has the databases the steps need, through ARVA's own API with the
confirmations a user gives: the Medaka model (above); an AMRFinderPlus database (the newest NCBI release ARVA lists as
compatible with its AMRFinderPlus, downloaded and indexed by ARVA after confirming its size and NCBI's terms); and, with
--download-ridom-spa, the Ridom SpaServer files for spa typing (ARVA never downloads them: this runner fetches
sparepeats.fasta and spatypes.txt from spa.ridom.de into the import folder and registers that folder, declaring the
download date as the version). mlst's schemes are bundled with mlst.

Two ways to reach ARVA:
- --start-arva: the API and worker from this source tree (scripts/dev.sh's way), with the download folder as the
  import folder;
- an ARVA already running, e.g. the published images under Docker Compose (.github/workflows/validation.yml): --api-url
  its address, --download-dir a host folder mounted as one of its import folders and --container-download-dir the
  same folder as the containers see it (e.g. /import). ARVA's storage is then inside the containers, so the imported
  copies under raw/ are left to ARVA (the whole stack is thrown away after the run in CI).

Standard library only. Run it with -I (downloaded files are untrusted data), e.g.:

    apps/api/.venv/bin/python -I validation/chakrawarti2024/run_validation.py --start-arva --smallest 2
    python3 -I validation/chakrawarti2024/run_validation.py --api-url http://127.0.0.1:8000 --only AC15-06 \
        --download-dir "$RUNNER_TEMP/arva-import" --container-download-dir /import --download-ridom-spa
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
API_DIR = REPO / "apps" / "api"
SCRATCH = Path("/tmp/claude-0/-home-user-ARVA/a0079f7f-7f60-54c5-bf8b-5f8483664aed/scratchpad")
DEFAULT_DOWNLOADS = SCRATCH / "validation-data" / "fastq"
DEFAULT_LOGS = SCRATCH / "validation-data" / "logs"
PROJECT_NAME = "Validation Chakrawarti 2024"
PREFIX = "/api/v1"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ENA_URL = re.compile(r"^https://ftp\.sra\.ebi\.ac\.uk/vol1/fastq/[A-Za-z0-9/_]+\.fastq\.gz$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FINAL = ("completed", "failed", "cancelled")

# The paper (Methods): "NanoFilt v2.7.1 ... -l 1000 -q 10". NanoFilt 2.7.1 (nanofilt/NanoFilt.py, ave_qual) keeps a read
# when -10*log10(mean per-base error probability) >= 10 and length >= 1000. Filtlong 0.3.1 (src/read.cpp,
# get_mean_quality) scores a read as 100 * mean(1 - 10^(-q/10)) and drops it when that is < --min_mean_q, and drops
# reads shorter than --min_length. Mean error <= 0.1 is mean accuracy >= 90 %, so --min_length 1000 --min_mean_q 90 is
# the same filter.
FILTLONG = {"min_length": 1000, "min_mean_q": 90}
FILTER_NOTE = ("Paper: NanoFilt v2.7.1 -l 1000 -q 10. Filtlong --min_length 1000 --min_mean_q 90 applies the same two "
               "thresholds (NanoFilt's ave_qual is -10*log10 of the mean per-base error probability; Filtlong's mean "
               "quality is 100 * mean per-base accuracy; Q10 = 90 %).")
# The paper: Flye v2.3.1 with genome size 2.8 Mb; reads basecalled with Guppy v4.0.11 HAC on R9.4.1. Flye 2.9.6 --help:
# "--nano-raw: ONT reads with older chemistries, pre R9 Guppy5 (10-20% error)"; "--nano-hq: ONT R10 reads, aka Q20
# (<3% error). For R9 Guppy5+, increase --read-error slightly". Guppy 4.0.11 is pre-Guppy5: --nano-raw.
FLYE = {"read_type": "nano-raw", "genome_size_bp": 2_800_000, "genome_size_basis": "entered"}
MEDAKA_MODEL = "r941_min_hac_g507"
# medaka v2.1.1, medaka/data/r941_min_hac_g507_model_pt.tar.gz (Git LFS pointer of the tag; the same values are in
# workflows/tool-adapters/arva_tools/medaka_models.py PUBLISHED). The runner refuses a model with any other checksum.
MEDAKA_MODEL_SHA256 = "6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb268ef07ac7680ac26"
MEDAKA_MODEL_BYTES = 1_502_971
MEDAKA_NOTE = ("Paper: Rebaler then Medaka v1.0.3 (model not stated). ARVA polished the Flye draft once with Medaka "
               "2.1.1 and r941_min_hac_g507 (R9.4.1 MinION, HAC, trained for Guppy 5.0.7), registered in ARVA from the "
               "medaka v2.1.1 tag (SHA-256 " + MEDAKA_MODEL_SHA256 + "); medaka 1.0.3's models (r941_min_high_g360 "
               "and older) cannot be loaded by medaka 2, and no Rebaler step was run.")
AMR_SETTINGS = {"organism": "Staphylococcus_aureus"}
# The Ridom SpaServer files (database_kinds.py, kind spa_types: "Download repeat sequences (FASTA)" and "Download
# spa-types (CSV)"). Ridom's policy (https://spa.ridom.de/policy.shtml): individuals may download and use them for
# non-commercial purposes; they are not redistributed (never written to results/ or to an artifact).
RIDOM_FILES = {"sparepeats.fasta": "https://spa.ridom.de/dynamic/sparepeats.fasta",
               "spatypes.txt": "https://spa.ridom.de/dynamic/spatypes.txt"}
RIDOM_MAX_BYTES = 64 * 1024 ** 2
USABLE_DB = ("installed", "registered")
TYPING_MODULE = "staphylococcus_aureus"
TYPING_METHODS = ("sccmec", "spa", "agr")
# Bioconda environments the way scripts/test-all.sh finds them (ARVA_TOOL_<ID> overrides).
CONDA_TOOLS = (("FLYE", "flye/bin/flye"), ("FILTLONG", "filtlong/bin/filtlong"), ("MEDAKA", "medaka/bin/medaka"),
               ("MLST", "mlst/bin/mlst"), ("SKANI", "skani/bin/skani"), ("AMRFINDERPLUS", "amrfinderplus/bin/amrfinder"),
               ("SCCMEC", "sccmec/bin/sccmec"), ("SPATYPER", "spatyper/bin/spaTyper"), ("AGRVATE", "agrvate/bin/agrvate"),
               ("ABRICATE", "abricate/bin/abricate"), ("FASTANI", "fastani/bin/fastANI"), ("MASH", "mash/bin/mash"),
               ("SYLPH", "sylph/bin/sylph"), ("BAKTA", "bakta/bin/bakta"), ("MOBSUITE", "mobsuite/bin/mob_recon"))


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# --- HTTP -----------------------------------------------------------------------------------------------------------

class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, payload: Any):
        self.status, self.payload = status, payload
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        super().__init__(f"{method} {path} -> HTTP {status}: {detail}")


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        # Local API: never through the HTTPS proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, path: str, body: Any = None, timeout: float = 600) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"{self.base}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw.decode(errors="replace")[:2000]
        if status >= 400:
            raise ApiError(method, path, status, payload)
        return payload

    def get(self, path: str) -> Any:
        return self.call("GET", PREFIX + path)

    def post(self, path: str, body: Any) -> Any:
        return self.call("POST", PREFIX + path, body)

    def delete(self, path: str) -> Any:
        return self.call("DELETE", PREFIX + path)

    def up(self) -> dict | None:
        try:
            return self.call("GET", "/health", timeout=10)
        except (OSError, ApiError):
            return None


# --- ARVA processes (--start-arva) ----------------------------------------------------------------------------------

class Arva:
    """API and worker started the way scripts/dev.sh starts them (uvicorn without --reload; worker from apps/api)."""

    def __init__(self, downloads: Path, logs: Path, db_dir: Path, port: int):
        self.downloads, self.logs, self.db_dir, self.port = downloads, logs, db_dir, port
        self.procs: list[subprocess.Popen] = []

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["ARVA_IMPORT_ROOTS"] = json.dumps([str(self.downloads)])
        env["ARVA_DB_DIR"] = str(self.db_dir)
        tools = Path.home() / ".arva-tools" / "conda"
        for var, rel in CONDA_TOOLS:
            exe = tools / rel
            if f"ARVA_TOOL_{var}" not in env and exe.is_file() and os.access(exe, os.X_OK):
                env[f"ARVA_TOOL_{var}"] = str(exe)
        return env

    def start(self, api: Api) -> None:
        if api.up():
            raise SystemExit(f"Something already answers on port {self.port}; stop it or run without --start-arva")
        self.logs.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        env = self.env()
        py = API_DIR / ".venv" / "bin" / "python"
        for name, argv in (
            ("api", [str(API_DIR / ".venv" / "bin" / "uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port",
                     str(self.port)]),
            ("worker", [str(py), str(REPO / "apps" / "workers" / "run_worker.py")]),
        ):
            fh = open(self.logs / f"{name}-{stamp}.log", "ab")
            self.procs.append(subprocess.Popen(argv, cwd=API_DIR, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, start_new_session=True))
            log(f"started {name} (pid {self.procs[-1].pid}), log {fh.name}")
        for _ in range(120):
            if api.up():
                return
            if any(p.poll() is not None for p in self.procs):
                break
            time.sleep(1)
        self.stop()
        raise SystemExit("ARVA did not start; see the logs in " + str(self.logs))

    def stop(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for p in self.procs:
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        self.procs.clear()


# --- Resource monitor -----------------------------------------------------------------------------------------------

def _meminfo() -> dict[str, int]:
    out = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) * 1024
    return out


def _largest_process() -> tuple[int, str]:
    best, name = 0, ""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/status") as fh:
                fields = dict(line.split(":", 1) for line in fh if ":" in line)
            rss = int(fields.get("VmRSS", "0 kB").split()[0]) * 1024
            if rss > best:
                best, name = rss, fields.get("Name", "").strip()
        except (OSError, ValueError):
            continue
    return best, name


class Monitor(threading.Thread):
    """Peak disk use of the filesystem holding ARVA's storage, peak system memory in use, largest single process."""

    def __init__(self, path: Path, every: float = 5.0):
        super().__init__(daemon=True)
        self.path, self.every = path, every
        self.stop_event = threading.Event()
        du = shutil.disk_usage(path)
        mem = _meminfo()
        self.start_disk_used = du.used
        self.start_mem_used = mem["MemTotal"] - mem["MemAvailable"]
        self.peak_disk_used = du.used
        self.min_disk_free = du.free
        self.peak_mem_used = self.start_mem_used
        self.peak_rss, self.peak_rss_name = _largest_process()

    def run(self) -> None:
        while not self.stop_event.wait(self.every):
            self.sample()

    def sample(self) -> None:
        du = shutil.disk_usage(self.path)
        mem = _meminfo()
        self.peak_disk_used = max(self.peak_disk_used, du.used)
        self.min_disk_free = min(self.min_disk_free, du.free)
        self.peak_mem_used = max(self.peak_mem_used, mem["MemTotal"] - mem["MemAvailable"])
        rss, name = _largest_process()
        if rss > self.peak_rss:
            self.peak_rss, self.peak_rss_name = rss, name

    def finish(self) -> dict[str, Any]:
        self.stop_event.set()
        self.sample()
        return {"sampling_seconds": self.every, "filesystem": str(self.path),
                "disk_used_at_start_bytes": self.start_disk_used, "peak_disk_used_bytes": self.peak_disk_used,
                "peak_disk_increase_bytes": self.peak_disk_used - self.start_disk_used,
                "min_disk_free_bytes": self.min_disk_free,
                "memory_used_at_start_bytes": self.start_mem_used, "peak_memory_used_bytes": self.peak_mem_used,
                "peak_memory_increase_bytes": self.peak_mem_used - self.start_mem_used,
                "largest_process_rss_bytes": self.peak_rss, "largest_process_name": self.peak_rss_name,
                "note": "system-wide samples (MemTotal - MemAvailable; statvfs used) every few seconds, so short "
                        "peaks can be missed"}


# --- Steps ----------------------------------------------------------------------------------------------------------

def download(url: str, dest: Path, md5: str, size: int, attempts: int = 3) -> dict[str, Any]:
    if not ENA_URL.fullmatch(url):
        raise RuntimeError(f"Unexpected FASTQ URL {url!r}")
    t0 = time.monotonic()
    part = dest.with_name(dest.name + ".part")
    errors = []
    for attempt in range(1, attempts + 1):
        h_md5, h_sha = hashlib.md5(), hashlib.sha256()
        n = 0
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, open(part, "wb") as fh:
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
                    h_md5.update(chunk)
                    h_sha.update(chunk)
                    n += len(chunk)
        except (OSError, urllib.error.URLError) as exc:
            errors.append(f"attempt {attempt}: {exc}")
            part.unlink(missing_ok=True)
            time.sleep(10 * attempt)
            continue
        if n == size and h_md5.hexdigest() == md5:
            os.replace(part, dest)
            return {"url": url, "bytes": n, "md5": h_md5.hexdigest(), "md5_expected": md5, "md5_ok": True,
                    "sha256": h_sha.hexdigest(), "seconds": round(time.monotonic() - t0, 1), "attempts": attempt,
                    "errors": errors}
        errors.append(f"attempt {attempt}: {n} bytes, md5 {h_md5.hexdigest()} (expected {size} bytes, md5 {md5})")
        part.unlink(missing_ok=True)
    raise RuntimeError(f"Download failed: {'; '.join(errors)}")


def fetch_small(url: str, dest: Path, limit: int, attempts: int = 3) -> dict[str, Any]:
    """Download a small public file (no published checksum) and record its size and SHA-256."""
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read(limit + 1)
        except (OSError, urllib.error.URLError) as exc:
            errors.append(f"attempt {attempt}: {exc}")
            time.sleep(10 * attempt)
            continue
        if not data or len(data) > limit:
            errors.append(f"attempt {attempt}: {len(data)} bytes (expected 1 to {limit})")
            continue
        dest.write_bytes(data)
        return {"url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "fetched_at": now()}
    raise SystemExit(f"Download of {url} failed: {'; '.join(errors)}")


def job_record(job: dict, wall: float | None = None) -> dict[str, Any]:
    keys = ("id", "job_type", "tool_name", "tool_version", "tool_path", "status", "parameters", "commands",
            "database_name", "database_version", "database_kind", "database_checksum", "database_path",
            "duration_seconds", "started_at", "finished_at", "error_message", "result_summary", "resources")
    rec = {k: job.get(k) for k in keys}
    rec["wall_seconds"] = None if wall is None else round(wall, 1)
    if job.get("status") != "completed":
        rec["log_tail"] = (job.get("log_text") or "")[-6000:]
    return rec


class Runner:
    def __init__(self, api: Api, args: argparse.Namespace):
        self.api, self.args = api, args
        self.root_index: int | None = None
        self.project_id: str | None = None
        self.medaka_model: dict[str, Any] | None = None
        self.amr_db: dict[str, Any] | None = None
        self.spa_files: dict[str, Any] | None = None

    # generic -------------------------------------------------------------------------------------------------------
    def wait(self, job_id: str, label: str) -> dict:
        t0 = time.monotonic()
        last = None
        while True:
            job = self.api.get(f"/jobs/{job_id}")
            if job["status"] != last:
                log(f"  {label}: {job['status']}")
                last = job["status"]
            if job["status"] in FINAL:
                job["_wall"] = time.monotonic() - t0
                return job
            if time.monotonic() - t0 > self.args.job_timeout:
                raise RuntimeError(f"{label}: still {job['status']} after {self.args.job_timeout} s")
            time.sleep(self.args.poll)

    def run_job(self, label: str, path: str, body: dict, steps: dict) -> dict:
        t0 = time.monotonic()
        started = self.api.post(path, body)
        job = self.wait(started["id"], label)
        steps[label] = job_record(job, time.monotonic() - t0)
        if job["status"] != "completed":
            raise RuntimeError(f"{label} {job['status']}: {job.get('error_message')}")
        return job

    def idle(self, sample_id: str) -> None:
        while any(j["status"] in ("pending", "running") for j in self.api.get(f"/samples/{sample_id}/jobs")):
            time.sleep(self.args.poll)

    # setup ---------------------------------------------------------------------------------------------------------
    def as_seen_by_arva(self, host_path: Path) -> str:
        """A path under the download folder as ARVA sees it (inside its containers with --container-download-dir)."""
        rel = host_path.resolve().relative_to(self.args.downloads.resolve())
        if self.args.container_download_dir:
            return posixpath.join(self.args.container_download_dir, *rel.parts)
        return str(host_path.resolve())

    def setup(self) -> None:
        roots = self.api.get("/imports/roots")
        if self.args.container_download_dir:
            want = posixpath.normpath(self.args.container_download_dir)
            for r in roots:
                if posixpath.normpath(r["path"]) == want and r["exists"]:
                    self.root_index = r["index"]
        else:
            want = os.path.realpath(self.args.downloads)
            for r in roots:
                if os.path.realpath(r["path"]) == want and r["exists"]:
                    self.root_index = r["index"]
        if self.root_index is None:
            raise SystemExit(f"{want} is not one of ARVA's import folders ({[r['path'] for r in roots]}); start ARVA "
                             "with ARVA_IMPORT_ROOTS including it (or use --start-arva), or give the folder as ARVA's "
                             "containers see it with --container-download-dir")
        for p in self.api.get("/projects"):
            if p["name"] == PROJECT_NAME:
                self.project_id = p["id"]
        if self.project_id is None:
            self.project_id = self.api.post("/projects", {
                "name": PROJECT_NAME,
                "description": "External validation of ARVA's ONT-only pipeline against Chakrawarti et al. 2024 "
                               "(Access Microbiology 6(3):000766.v3, BioProject PRJNA983748). Created by "
                               "validation/chakrawarti2024/run_validation.py."})["id"]
            log(f"created project {self.project_id}")
        else:
            log(f"reusing project {self.project_id}")
        self.medaka_model = self.ensure_medaka_model()
        self.amr_db = self.ensure_amrfinder_db()
        self.spa_files = self.ensure_spa_files()

    def wait_database(self, record_id: str, label: str, timeout: float = 3600) -> dict:
        t0, last = time.monotonic(), None
        while True:
            rec = self.api.get(f"/databases/{record_id}")
            if rec["status"] != last:
                log(f"  {label}: {rec['status']}")
                last = rec["status"]
            if rec["status"] not in ("downloading", "extracting", "verifying"):
                return rec
            if time.monotonic() - t0 > timeout:
                raise SystemExit(f"{label}: still {rec['status']} after {timeout:.0f} s")
            time.sleep(5)

    def ensure_medaka_model(self) -> dict[str, Any]:
        """r941_min_hac_g507 registered in ARVA through its API, the way a user would: the listing first; if ARVA has
        no usable record, the download plan and the confirmed download (SHA-256, size and Medaka's licence repeated
        from the plan, after checking them against the values medaka v2.1.1 publishes); or, with
        --medaka-model-file, the registration of a copy already on disk. Stops the run if none of that works."""
        def registered() -> dict | None:
            for r in self.api.get("/databases/medaka-models")["registered"]:
                if r["model"] == MEDAKA_MODEL:
                    return r
            return None

        how = "already registered"
        found = registered()
        if found is None:
            entry = next((m for m in self.api.get("/databases/medaka-models")["available"]
                          if m["name"] == MEDAKA_MODEL), None)
            if entry is None:
                raise SystemExit(f"ARVA does not offer {MEDAKA_MODEL} in GET /databases/medaka-models")
            if entry.get("database_id") and entry.get("status") in ("downloading", "verifying"):
                self.wait_database(entry["database_id"], f"Medaka model {MEDAKA_MODEL}")
                how = "downloaded by ARVA (download already in progress)"
            elif self.args.medaka_model_file:
                path = str(self.args.medaka_model_file.resolve())
                if hashlib.sha256(self.args.medaka_model_file.read_bytes()).hexdigest() != MEDAKA_MODEL_SHA256:
                    raise SystemExit(f"{path} is not medaka v2.1.1's {MEDAKA_MODEL} (SHA-256 differs)")
                rec = self.api.post("/databases/register", {"path": path, "kind": "medaka_model"})
                log(f"registered {path} as {rec['name']} ({rec['status']})")
                how = "existing file registered (POST /databases/register)"
            else:
                plan = self.api.post("/databases/medaka-models/plan", {"model": MEDAKA_MODEL})
                if (plan["sha256"], plan["bytes"]) != (MEDAKA_MODEL_SHA256, MEDAKA_MODEL_BYTES):
                    raise SystemExit(f"ARVA's plan offers {MEDAKA_MODEL} with SHA-256 {plan['sha256']} and "
                                     f"{plan['bytes']} bytes, not medaka v2.1.1's {MEDAKA_MODEL_SHA256} "
                                     f"({MEDAKA_MODEL_BYTES} bytes)")
                if plan.get("blocked_by"):
                    raise SystemExit(f"ARVA cannot download {MEDAKA_MODEL}: {plan['blocked_by']} "
                                     f"({plan.get('blocked_code')})")
                log(f"downloading {MEDAKA_MODEL} through ARVA: {plan['url']} ({plan['bytes']:,} bytes, SHA-256 "
                    f"{plan['sha256']}, licence {plan['licence']}) into {plan['target_path']}")
                rec = self.api.post("/databases/medaka-models/download", {
                    "model": MEDAKA_MODEL, "confirm_sha256": plan["sha256"], "confirm_bytes": plan["bytes"],
                    "accept_licence": True})
                rec = self.wait_database(rec["id"], f"Medaka model {MEDAKA_MODEL}")
                if rec["status"] not in ("installed", "registered"):
                    raise SystemExit(f"ARVA's download of {MEDAKA_MODEL} ended {rec['status']}: "
                                     f"{rec.get('error_message')}")
                how = "downloaded by ARVA (POST /databases/medaka-models/download, confirmed)"
            found = registered()
        if found is None:
            raise SystemExit(f"{MEDAKA_MODEL} is not among ARVA's registered Medaka models")
        if found.get("sha256") != MEDAKA_MODEL_SHA256:
            raise SystemExit(f"ARVA's registered {MEDAKA_MODEL} has SHA-256 {found.get('sha256')}, not "
                             f"{MEDAKA_MODEL_SHA256}")
        log(f"Medaka model {MEDAKA_MODEL}: {how}; {found['path']} (SHA-256 {found['sha256']})")
        return {**found, "how": how, "expected_sha256": MEDAKA_MODEL_SHA256}

    def usable_databases(self, kind: str) -> list[dict]:
        return [d for d in self.api.get("/databases") if d["kind"] == kind and d["status"] in USABLE_DB]

    def ensure_amrfinder_db(self) -> dict[str, Any]:
        """An AMRFinderPlus database in ARVA, the way a user gets one in the Databases section: the usable record ARVA
        already has, or the newest release NCBI lists that ARVA says its AMRFinderPlus reads, after the plan (files,
        size, terms) and the confirmed download (size repeated, NCBI's terms accepted); ARVA then indexes it with
        amrfinder_index. Stops the run if none of that works: every isolate would fail at AMRFinderPlus."""
        have = self.usable_databases("amrfinderplus")
        if have:
            d = next((x for x in have if x.get("is_default")), have[0])
            log(f"AMRFinderPlus database: already registered, {d['name']} {d['version']} ({d['path']})")
            return {"how": "already registered", "name": d["name"], "version": d["version"], "path": d["path"]}
        rel = self.api.get("/databases/amrfinderplus/releases")
        ok = [r for r in rel["releases"] if r["compatibility"] == "compatible"]
        if not ok:
            raise SystemExit(f"NCBI lists no AMRFinderPlus release that ARVA's AMRFinderPlus {rel['tool_version']} "
                             f"reads ({rel['url']}): {[(r['version'], r['compatibility']) for r in rel['releases']]}")
        # The newest compatible release whose folder is complete: NCBI may still be uploading the newest one (ARVA
        # refuses a release that lacks a required file), so the next ones are tried before giving up.
        for r in ok[:3]:
            version = r["version"]
            plan = self.api.post("/databases/amrfinderplus/plan", {"version": version})
            if not plan.get("missing"):
                break
            log(f"AMRFinderPlus database {version}: NCBI's folder lacks {plan['missing']}; trying an older release")
        if plan.get("blocked_by") or plan.get("missing") or not plan.get("enough"):
            raise SystemExit(f"ARVA cannot download AMRFinderPlus database {version}: blocked_by "
                             f"{plan.get('blocked_by')!r} ({plan.get('blocked_code')}), missing {plan.get('missing')}, "
                             f"enough space {plan.get('enough')}")
        log(f"downloading AMRFinderPlus database {version} through ARVA: {plan['url']} ({len(plan['files'])} files, "
            f"{plan['download_bytes']:,} bytes as NCBI's listing gives them; terms: {plan['licence']}) into "
            f"{plan['target_path']}")
        rec = self.api.post("/databases/amrfinderplus/download", {
            "version": version, "confirm_bytes": plan["download_bytes"], "accept_terms": True})
        rec = self.wait_database(rec["id"], f"AMRFinderPlus database {version}")
        if rec["status"] not in USABLE_DB:
            raise SystemExit(f"ARVA's download of AMRFinderPlus database {version} ended {rec['status']}: "
                             f"{rec.get('error_message')}")
        return {"how": "downloaded and indexed by ARVA (POST /databases/amrfinderplus/download, confirmed)",
                "name": rec.get("name"), "version": rec.get("version"), "path": rec.get("path"),
                "tool_version": plan["tool_version"], "url": plan["url"], "download_bytes": plan["download_bytes"]}

    def ensure_spa_files(self) -> dict[str, Any] | None:
        """The Ridom SpaServer files for spa typing. ARVA never downloads them (kind spa_types is user-provided only):
        the usable record ARVA already has or, with --download-ridom-spa, this runner downloads them into the import
        folder and registers that folder through POST /databases/register, declaring the download date as the
        version (the files state none). Without either, spa typing is refused by ARVA and recorded as skipped."""
        have = self.usable_databases("spa_types")
        if have:
            d = next((x for x in have if x.get("is_default")), have[0])
            log(f"Ridom spa files: already registered, {d['name']} {d['version']} ({d['path']})")
            return {"how": "already registered", "name": d["name"], "version": d["version"], "path": d["path"]}
        if not self.args.download_ridom_spa:
            log("Ridom spa files: none registered and --download-ridom-spa not given; spa typing will be skipped")
            return None
        day = dt.datetime.now(dt.UTC).date().isoformat()
        folder = self.args.downloads / f"ridom-spa-{day}"
        folder.mkdir(parents=True, exist_ok=True)
        files = {}
        for name, url in RIDOM_FILES.items():
            files[name] = fetch_small(url, folder / name, RIDOM_MAX_BYTES)
            log(f"Ridom {name}: {files[name]['bytes']:,} bytes, SHA-256 {files[name]['sha256']}")
        path = self.as_seen_by_arva(folder)
        declared = f"downloaded {day} from spa.ridom.de"
        rec = self.api.post("/databases/register", {"path": path, "kind": "spa_types", "declared_version": declared})
        if rec["status"] not in USABLE_DB:
            raise SystemExit(f"ARVA registered the Ridom files at {path} as {rec['status']}: {rec.get('error_message')}")
        log(f"registered the Ridom spa files {path} as {rec['name']} {rec['version']} ({rec['status']})")
        return {"how": "downloaded by this runner from spa.ridom.de and registered (POST /databases/register)",
                "name": rec.get("name"), "version": rec.get("version"), "path": rec.get("path"), "files": files,
                "policy": "https://spa.ridom.de/policy.shtml (non-commercial use; files not redistributed)"}

    def provenance(self) -> dict[str, Any]:
        def git(*argv: str) -> str:
            return subprocess.run(["git", "-C", str(REPO), *argv], capture_output=True, text=True).stdout.strip()
        tools = {t["id"]: {"version": t["version"], "path": t["path"], "status": t["status"]}
                 for t in self.api.get("/tools")
                 if t["id"] in ("filtlong", "flye", "medaka", "racon", "minimap2", "samtools", "mlst", "sccmec",
                                "spatyper", "agrvate", "amrfinderplus", "skani")}
        dbs = [{k: d.get(k) for k in ("kind", "name", "version", "version_source", "path", "is_default", "status")}
               for d in self.api.get("/databases")]
        perf = self.api.get("/system/performance")["effective"]
        return {"arva_version": (self.api.up() or {}).get("version"),
                "arva_started_from": "source tree (--start-arva)" if self.args.start_arva else "running ARVA",
                "arva_image": self.args.arva_image, "arva_image_commit": self.args.arva_image_commit,
                "setup": {"medaka_model": (self.medaka_model or {}).get("how"), "amrfinderplus_database": self.amr_db,
                          "spa_files": self.spa_files},
                "git_commit": git("rev-parse", "HEAD"),
                "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "git_dirty_paths": [line for line in git("status", "--porcelain").splitlines() if line],
                "tools": tools, "databases": dbs, "performance_profile": perf, "threads_requested": self.args.threads}

    # one isolate ---------------------------------------------------------------------------------------------------
    def isolate(self, row: dict[str, str], expected: dict[str, str] | None) -> None:
        name = row["isolate"]
        if not SAFE_NAME.fullmatch(name):
            raise RuntimeError(f"Unexpected isolate name {name!r}")
        out = self.args.results / f"{name}.json"
        size = int(row["ont_fastq_bytes"])
        need = 3 * size + int(self.args.margin_gb * 1024 ** 3)
        free = shutil.disk_usage(self.args.downloads).free
        if free < need:
            raise SystemExit(f"{name}: {free / 1e9:.2f} GB free, {need / 1e9:.2f} GB needed (3 x FASTQ + margin); "
                             "stopping")
        mon = Monitor(self.args.monitor_path)
        mon.start()
        t_start = time.monotonic()
        res: dict[str, Any] = {"isolate": name, "started_at": now(), "input": {k: row[k] for k in (
            "source", "farm", "biosample", "ont_experiment", "ont_run", "ont_fastq_url", "ont_fastq_md5",
            "ont_fastq_bytes", "ont_read_count", "ont_base_count", "ont_instrument")},
            "expected_from_paper": expected, "provenance": self.provenance(), "steps": {}, "skipped": {},
            "deviations": [MEDAKA_NOTE], "notes": [FILTER_NOTE]}
        steps = res["steps"]
        folder = self.args.downloads / name
        # ENA names single-end ONT runs <run>_1.fastq.gz. The file keeps ENA's name, as a user would download it:
        # ARVA no longer takes a lone long-read "_1" file as mate R1 of a pair (app/services/imports.py
        # mate_from_content); the import records read_mate and mate_note, and an isolate whose file is still marked
        # as a mate fails with that reason (see below) rather than being renamed silently.
        if not re.fullmatch(r"[SED]RR\d+", row["ont_run"]):
            raise RuntimeError(f"Unexpected run accession {row['ont_run']!r}")
        ena_name = Path(urllib.parse.urlsplit(row["ont_fastq_url"]).path).name
        if ena_name not in (f"{row['ont_run']}_1.fastq.gz", f"{row['ont_run']}.fastq.gz"):
            raise RuntimeError(f"Unexpected ENA file name {ena_name!r}")
        fastq = folder / ena_name
        sample_id = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            log(f"{name}: downloading {size / 1e6:.0f} MB")
            res["download"] = download(row["ont_fastq_url"], fastq, row["ont_fastq_md5"], size)
            res["download"]["ena_file_name"] = ena_name
            res["download"]["local_file_name"] = fastq.name
            log(f"{name}: md5 ok ({res['download']['seconds']} s)")

            for s in self.api.get(f"/projects/{self.project_id}/samples"):
                if s["sample_code"] == name:  # left over from an interrupted run
                    log(f"{name}: removing a sample left by an earlier run ({s['id']})")
                    self.idle(s["id"])
                    self.remove_sample(s["id"])
            sample = self.api.post(f"/projects/{self.project_id}/samples", {
                "sample_code": name, "organism": "Staphylococcus aureus", "expected_species": "Staphylococcus aureus",
                "sample_type": row["source"], "sequencing_technology": "nanopore", "sequencing_run": row["ont_run"],
                "description": "Chakrawarti et al. 2024 validation isolate (ONT reads from ENA)",
                "custom_metadata": {"biosample": row["biosample"], "ont_run": row["ont_run"],
                                    "ont_experiment": row["ont_experiment"], "farm": row["farm"]}})
            sample_id = res["sample_id"] = sample["id"]

            # import ---------------------------------------------------------------------------------------------
            rel = f"{name}/{fastq.name}"
            self.run_job("import", f"/samples/{sample_id}/files/import-server",
                         {"root": self.root_index, "paths": [rel]}, steps)
            self.idle(sample_id)
            files = self.api.get(f"/samples/{sample_id}/files")
            imported = [f for f in files if f["origin"] == "imported"]
            if len(imported) != 1:
                raise RuntimeError(f"expected one imported file, found {len(imported)}")
            raw = imported[0]
            res["imported_file"] = {k: raw.get(k) for k in ("id", "original_filename", "size_bytes", "checksum_sha256",
                                                            "is_valid", "validation_message", "read_mate",
                                                            "mate_note")}
            res["imported_file"]["sha256_matches_download"] = raw.get("checksum_sha256") == res["download"]["sha256"]
            if not raw["is_valid"]:
                raise RuntimeError(f"ARVA marked the FASTQ invalid: {raw.get('validation_message')}")
            if raw.get("read_mate"):
                raise RuntimeError(f"ARVA registered the single ONT FASTQ {raw['original_filename']} as pair mate "
                                   f"{raw['read_mate']} ({raw.get('mate_note')})")
            if not self.args.keep_download:
                fastq.unlink()
                res["download"]["deleted_after_import"] = True

            # Filtlong (the paper filtered with NanoFilt) -------------------------------------------------------------
            job = self.run_job("filtlong", f"/samples/{sample_id}/filtering/filtlong",
                               {"file_id": raw["id"], "params": FILTLONG}, steps)
            derived = [f for f in self.api.get(f"/samples/{sample_id}/files") if f["produced_by_job_id"] == job["id"]]
            if len(derived) != 1:
                raise RuntimeError(f"expected one Filtlong output, found {len(derived)}")
            reads = derived[0]
            res["filtered_file"] = {k: reads.get(k) for k in ("id", "original_filename", "size_bytes")}

            # Flye -------------------------------------------------------------------------------------------------
            plan = self.api.post(f"/samples/{sample_id}/assembly/flye/preview", {"raw_file_ids": [reads["id"]]})
            res["flye_plan"] = {"read_type_suggestion": plan.get("read_type_suggestion"),
                                "memory": plan.get("memory")}
            job = self.run_job("flye", f"/samples/{sample_id}/assembly/flye",
                               {"raw_file_ids": [reads["id"]], "params": {**FLYE, "threads": self.args.threads}}, steps)
            draft = self.assembly(sample_id, job["id"])
            res["assembly_flye"] = draft

            # polishing --------------------------------------------------------------------------------------------
            inputs = {"long_file_id": reads["id"]}
            pplan = self.api.post(f"/assemblies/{draft['id']}/polishing/preview",
                                  {"inputs": inputs, "read_type": "map-ont"})
            res["polishing_plan"] = {"medaka": pplan.get("medaka"), "strategies_available":
                                     pplan.get("strategies_available"), "problem": pplan.get("problem")}
            offered = [r for r in (pplan.get("medaka") or {}).get("registered") or [] if r["model"] == MEDAKA_MODEL]
            if not offered:
                raise RuntimeError(f"ARVA's polishing plan does not offer the registered {MEDAKA_MODEL} "
                                   f"(problem: {pplan.get('problem') or (pplan.get('medaka') or {}).get('problem')})")
            try:
                polished_job = self.run_job("polishing_medaka", f"/assemblies/{draft['id']}/polishing", {
                    "strategy": "medaka", "inputs": inputs, "medaka": {"model": MEDAKA_MODEL},
                    "threads": self.args.threads}, steps)
            except ApiError as exc:
                res["medaka_refusal"] = {"model_requested": MEDAKA_MODEL, "http_status": exc.status,
                                         "arva_refusal": exc.payload}
                raise
            used = (polished_job.get("parameters") or {}).get("medaka_model") or {}
            res["medaka_model"] = {
                "model": used.get("model"), "source": used.get("model_source"), "sha256": used.get("sha256"),
                "expected_sha256": MEDAKA_MODEL_SHA256, "sha256_ok": used.get("sha256") == MEDAKA_MODEL_SHA256,
                "database_id": used.get("database_id"), "path": used.get("path"), "url": used.get("url"),
                "origin": used.get("origin"), "chemistry": used.get("chemistry"), "basecaller": used.get("basecaller"),
                "choice": used.get("source"), "suggestion": used.get("suggestion"),
                "medaka_version": used.get("medaka_version"),
                "registration": (self.medaka_model or {}).get("how")}
            if used.get("model") != MEDAKA_MODEL or used.get("model_source") != "registered" or \
                    used.get("sha256") != MEDAKA_MODEL_SHA256:
                raise RuntimeError(f"Medaka ran with {used.get('model')} ({used.get('model_source')}, SHA-256 "
                                   f"{used.get('sha256')}), not the registered {MEDAKA_MODEL}")
            polished = self.assembly(sample_id, polished_job["id"])
            res["assembly_polished"] = polished
            target = polished["id"]

            # MLST -------------------------------------------------------------------------------------------------
            job = self.run_job("mlst", f"/assemblies/{target}/mlst", {"confirmed": True, "threads": self.args.threads},
                               steps)
            m = [r for r in self.api.get(f"/samples/{sample_id}/mlst") if r["job_id"] == job["id"]]
            res["mlst"] = None if not m else {k: m[0].get(k) for k in (
                "scheme", "st", "status", "score", "alleles", "clonal_complex", "warnings", "tool_version",
                "database_name", "database_version", "parameters")}

            # species (skani) --------------------------------------------------------------------------------------
            splan = self.api.post(f"/assemblies/{target}/species/preview", {"method": "skani"})
            if splan.get("database") is None or splan.get("problems"):
                res["skipped"]["species_skani"] = {"reason": "no usable skani reference collection registered in "
                                                   "ARVA" if splan.get("database") is None else "ARVA's plan lists "
                                                   "problems", "problems": splan.get("problems"),
                                                   "databases": splan.get("databases")}
            else:
                job = self.run_job("species_skani", f"/assemblies/{target}/species",
                                   {"method": "skani", "confirmed": True, "threads": self.args.threads}, steps)
                sp = [r for r in self.api.get(f"/samples/{sample_id}/species") if r.get("job_id") == job["id"]]
                res["species"] = sp[0] if sp else None

            # S. aureus typing -------------------------------------------------------------------------------------
            res["typing"] = {}
            for method in TYPING_METHODS:
                label = f"typing_{method}"
                try:
                    job = self.run_job(label, f"/assemblies/{target}/typing/{TYPING_MODULE}",
                                       {"method": method, "confirmed": True}, steps)
                except ApiError as exc:
                    res["skipped"][label] = {"http_status": exc.status, "arva_refusal": exc.payload}
                    continue
                rows = [r for r in self.api.get(f"/samples/{sample_id}/typing")["results"] if r["job_id"] == job["id"]]
                res["typing"][method] = [{k: r.get(k) for k in ("method", "status", "call", "details", "warnings",
                                                                "tool_version", "database_name", "database_version",
                                                                "parameters", "applicability")} for r in rows]

            # AMRFinderPlus ----------------------------------------------------------------------------------------
            job = self.run_job("amrfinderplus", f"/assemblies/{target}/amr",
                               {"settings": AMR_SETTINGS, "confirmed": True, "threads": self.args.threads}, steps)
            run = self.api.get(f"/amr/runs/{job['id']}")
            res["amrfinderplus"] = {
                "tool_version": run.get("tool_version"), "database_version": run.get("database_version"),
                "parameters": run.get("parameters"), "organism_choice": run.get("organism_choice"),
                "counts": run.get("counts"), "warnings": run.get("warnings"),
                "point_mutation_screen": run.get("point_mutation_screen"),
                "hits": [{k: h.get(k) for k in ("element_symbol", "element_name", "scope", "type", "subtype",
                                                "amr_class", "amr_subclass", "method", "identity", "coverage",
                                                "contig", "start", "stop", "strand", "closest_accession")}
                         for h in run.get("hits") or []]}
            res["status"] = "completed"
        except Exception as exc:  # recorded, then the next isolate runs
            res["status"] = "failed"
            res["error"] = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, ApiError):
                res["error_payload"] = exc.payload
            log(f"{name}: FAILED: {res['error']}")
        res["finished_at"] = now()
        res["wall_seconds"] = round(time.monotonic() - t_start, 1)
        res["resources"] = mon.finish()
        if sample_id is not None and self.args.storage_root is not None:
            res["arva_storage_bytes_before_cleanup"] = self.storage_bytes(sample_id)
        res["summary"] = summary(res)
        if res["status"] == "completed" or not self.args.keep_on_failure:
            self.cleanup(res, sample_id, folder)
        dest = out if res["status"] == "completed" else self.args.results / f"{name}.failed.json"
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_text(json.dumps(res, indent=2, sort_keys=False, default=str) + "\n")
        os.replace(tmp, dest)
        if res["status"] == "completed":
            (self.args.results / f"{name}.failed.json").unlink(missing_ok=True)
        log(f"{name}: {res['status']} in {res['wall_seconds'] / 60:.1f} min -> {dest}")

    def assembly(self, sample_id: str, job_id: str) -> dict[str, Any]:
        rows = [a for a in self.api.get(f"/samples/{sample_id}/assemblies") if a["job_id"] == job_id]
        if len(rows) != 1:
            raise RuntimeError(f"expected one assembly from job {job_id}, found {len(rows)}")
        a = rows[0]
        return {k: a.get(k) for k in ("id", "assembler", "assembler_version", "kind", "parent_assembly_id", "mode",
                                      "read_type", "stats", "warnings")}

    def storage_bytes(self, sample_id: str) -> dict[str, int]:
        out = {}
        for top in ("raw", "processed", "results", "checkpoints"):
            d = self.args.storage_root / top / self.project_id / sample_id
            out[top] = sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.is_dir() else 0
        return out

    def remove_sample(self, sample_id: str) -> bool:
        """DELETE the sample through the API, then, with --start-arva (ARVA's storage is this computer's folder), its
        imported copy under raw/ (ARVA keeps raw/ on deletion). Returns whether raw/ was removed."""
        if not UUID.fullmatch(sample_id) or not UUID.fullmatch(self.project_id or ""):
            raise RuntimeError("unexpected identifiers")
        self.api.delete(f"/samples/{sample_id}")
        if not self.args.start_arva or self.args.storage_root is None:
            return False
        raw = (self.args.storage_root / "raw" / self.project_id / sample_id).resolve()
        base = (self.args.storage_root / "raw").resolve()
        if raw.is_dir() and base in raw.parents:
            shutil.rmtree(raw)
            return True
        return False

    def cleanup(self, res: dict, sample_id: str | None, folder: Path) -> None:
        done = {}
        if sample_id is not None:
            try:
                self.idle(sample_id)
                done["arva_raw_copy_removed"] = self.remove_sample(sample_id)
                done["arva_sample_deleted"] = True
            except Exception as exc:
                done["arva_sample_delete_error"] = str(exc)
        if folder.is_dir() and folder.parent.resolve() == self.args.downloads.resolve():
            shutil.rmtree(folder)
            done["download_folder_removed"] = True
        res["cleanup"] = done


def summary(res: dict) -> dict[str, Any]:
    typing = res.get("typing") or {}

    def call(method: str) -> Any:
        rows = typing.get(method) or []
        return rows[0].get("call") if rows else None

    hits = (res.get("amrfinderplus") or {}).get("hits") or []
    pol = res.get("assembly_polished") or {}
    stats = pol.get("stats") or {}
    return {
        "st": (res.get("mlst") or {}).get("st"),
        "mlst_status": (res.get("mlst") or {}).get("status"),
        "alleles": {a["locus"]: a["call"] for a in (res.get("mlst") or {}).get("alleles") or []},
        "spa": call("spa"), "sccmec": call("sccmec"), "agr": call("agr"),
        "amr_genes": sorted({h["element_symbol"] for h in hits if h.get("type") == "AMR"}),
        "all_elements": sorted({h["element_symbol"] for h in hits}),
        "polisher": "medaka" if "polishing_medaka" in res.get("steps", {}) else
        "racon" if "polishing_racon" in res.get("steps", {}) else None,
        "medaka_model": (res.get("medaka_model") or {}).get("model"),
        "medaka_model_source": (res.get("medaka_model") or {}).get("source"),
        "medaka_model_sha256": (res.get("medaka_model") or {}).get("sha256"),
        "contigs": stats.get("contig_count"), "total_length": stats.get("total_length"), "n50": stats.get("n50"),
        "step_seconds": {k: v.get("wall_seconds") for k, v in res.get("steps", {}).items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", "--api-url", dest="api", default="http://127.0.0.1:8000", help="ARVA's address")
    ap.add_argument("--isolates", type=Path, default=HERE / "isolates.tsv")
    ap.add_argument("--expected", type=Path, default=HERE / "expected.tsv")
    ap.add_argument("--results", type=Path, default=HERE / "results")
    ap.add_argument("--downloads", "--download-dir", dest="downloads", type=Path, default=DEFAULT_DOWNLOADS,
                    help="where the FASTQ files are downloaded: an ARVA import folder (or one mounted as one)")
    ap.add_argument("--container-download-dir", help="the download folder as ARVA sees it when ARVA runs in containers "
                    "and the folder is mounted at another path (e.g. /import); default: the same path")
    ap.add_argument("--storage-root", type=Path, default=None, help="ARVA_STORAGE_ROOT of the running API, when it is "
                    "a folder of this computer (default with --start-arva: apps/api/data; otherwise none: ARVA's "
                    "per-sample storage is not measured and raw/ is left to ARVA)")
    ap.add_argument("--monitor-path", type=Path, default=None, help="a path on the filesystem whose disk use is "
                    "sampled (default: --storage-root, else the download folder), e.g. Docker's data root")
    ap.add_argument("--download-ridom-spa", action="store_true", help="when ARVA has no Ridom spa files, download "
                    "sparepeats.fasta and spatypes.txt from spa.ridom.de into the download folder and register them "
                    "(Ridom's policy: non-commercial use; https://spa.ridom.de/policy.shtml)")
    ap.add_argument("--arva-image", help="the ARVA image the API runs (recorded in each result's provenance)")
    ap.add_argument("--arva-image-commit", help="the commit that image was built from (recorded likewise)")
    ap.add_argument("--only", nargs="*", help="isolate names")
    ap.add_argument("--smallest", type=int, help="only the N isolates with the smallest ONT FASTQ")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--poll", type=float, default=10)
    ap.add_argument("--job-timeout", type=float, default=12 * 3600)
    ap.add_argument("--margin-gb", type=float, default=1.5, help="free space required beyond 3 x the FASTQ size")
    ap.add_argument("--keep-download", action="store_true", help="keep the FASTQ until the isolate is done")
    ap.add_argument("--keep-on-failure", action="store_true", help="keep the sample and FASTQ of a failed isolate")
    ap.add_argument("--start-arva", action="store_true", help="start the API and the worker, stop them at the end")
    ap.add_argument("--db-dir", type=Path, default=Path.home() / ".arva-db", help="ARVA_DB_DIR with --start-arva")
    ap.add_argument("--medaka-model-file", type=Path, help=f"register this copy of {MEDAKA_MODEL}_model_pt.tar.gz "
                    "(in a folder ARVA may register from) instead of letting ARVA download it, when ARVA has none")
    ap.add_argument("--logs", type=Path, default=DEFAULT_LOGS, help="API and worker logs with --start-arva")
    args = ap.parse_args()
    if args.start_arva and args.container_download_dir:
        ap.error("--container-download-dir is for an ARVA running in containers, not with --start-arva")
    if args.start_arva and args.storage_root is None:
        args.storage_root = API_DIR / "data"
    args.results.mkdir(parents=True, exist_ok=True)
    args.downloads.mkdir(parents=True, exist_ok=True)
    args.monitor_path = args.monitor_path or args.storage_root or args.downloads
    try:
        shutil.disk_usage(args.monitor_path)
    except OSError as exc:
        ap.error(f"--monitor-path {args.monitor_path}: {exc}")

    with open(args.isolates, newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    with open(args.expected, newline="") as fh:
        expected = {r["isolate"]: r for r in csv.DictReader(fh, delimiter="\t")}
    if args.only:
        unknown = set(args.only) - {r["isolate"] for r in rows}
        if unknown:
            raise SystemExit(f"unknown isolates: {sorted(unknown)}")
        rows = [r for r in rows if r["isolate"] in args.only]
    if args.smallest:
        rows = sorted(rows, key=lambda r: int(r["ont_fastq_bytes"]))[: args.smallest]
    rows = sorted(rows, key=lambda r: int(r["ont_fastq_bytes"]))  # smallest first

    api = Api(args.api)
    arva = Arva(args.downloads, args.logs, args.db_dir, urllib.parse.urlsplit(args.api).port or 8000)
    if args.start_arva:
        arva.start(api)
    elif not api.up():
        raise SystemExit(f"ARVA does not answer at {args.api} (use --start-arva)")

    def stop(*_: Any) -> None:
        arva.stop()
        raise SystemExit(130)
    signal.signal(signal.SIGTERM, stop)
    try:
        runner = Runner(api, args)
        runner.setup()
        todo = [r for r in rows if not (args.results / f"{r['isolate']}.json").exists()]
        log(f"{len(rows) - len(todo)} isolate(s) already have results; {len(todo)} to run: "
            f"{', '.join(r['isolate'] for r in todo)}")
        for row in todo:
            runner.isolate(row, expected.get(row["isolate"]))
    finally:
        arva.stop()


if __name__ == "__main__":
    sys.exit(main())
