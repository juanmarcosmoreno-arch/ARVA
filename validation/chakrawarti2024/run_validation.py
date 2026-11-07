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
    - Medaka with r941_min_hac_g507 (README "Medaka model decision"); if ARVA refuses that model, Racon (map-ont)
      through ARVA instead, with ARVA's refusal recorded;
    - mlst, then S. aureus typing (sccmec, spa, agr), AMRFinderPlus (--organism Staphylococcus_aureus) and species
      identification with skani when a reference collection is registered (otherwise skipped and recorded);
 4. write results/<isolate>.json (ARVA version and commit, tool versions, parameters, commands, ST, alleles, spa,
    SCCmec, agr, AMR genes, timings, peak disk and memory);
 5. delete the downloaded FASTQ and the ARVA sample, and the sample's imported copy under ARVA's raw/ folder (ARVA's
    sample deletion keeps raw/ by design; this harness removes it to free the disk, see cleanup());
 6. skip isolates that already have results/<isolate>.json, so the run can be resumed.

Standard library only. Run it with -I (downloaded files are untrusted data), e.g.:

    apps/api/.venv/bin/python -I validation/chakrawarti2024/run_validation.py --start-arva --smallest 2
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
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
RACON = {"read_type": "map-ont"}
AMR_SETTINGS = {"organism": "Staphylococcus_aureus"}
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
    def setup(self) -> None:
        roots = self.api.get("/imports/roots")
        want = os.path.realpath(self.args.downloads)
        for r in roots:
            if os.path.realpath(r["path"]) == want and r["exists"]:
                self.root_index = r["index"]
        if self.root_index is None:
            raise SystemExit(f"{want} is not one of ARVA's import folders ({[r['path'] for r in roots]}); start ARVA "
                             "with ARVA_IMPORT_ROOTS including it (or use --start-arva)")
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
        return {"arva_version": (self.api.up() or {}).get("version"), "git_commit": git("rev-parse", "HEAD"),
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
        mon = Monitor(self.args.storage_root)
        mon.start()
        t_start = time.monotonic()
        res: dict[str, Any] = {"isolate": name, "started_at": now(), "input": {k: row[k] for k in (
            "source", "farm", "biosample", "ont_experiment", "ont_run", "ont_fastq_url", "ont_fastq_md5",
            "ont_fastq_bytes", "ont_read_count", "ont_base_count", "ont_instrument")},
            "expected_from_paper": expected, "provenance": self.provenance(), "steps": {}, "skipped": {},
            "deviations": [], "notes": [FILTER_NOTE]}
        steps = res["steps"]
        folder = self.args.downloads / name
        # ENA names single-end ONT runs <run>_1.fastq.gz; ARVA reads "_1" as mate R1 of a pair (Illumina naming,
        # app/services/imports.py detect_read_mate) and Flye then refuses the file, with no API to correct it. The
        # local copy is therefore saved as <run>.fastq.gz (same bytes, md5 checked).
        if not re.fullmatch(r"[SED]RR\d+", row["ont_run"]):
            raise RuntimeError(f"Unexpected run accession {row['ont_run']!r}")
        fastq = folder / f"{row['ont_run']}.fastq.gz"
        sample_id = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            log(f"{name}: downloading {size / 1e6:.0f} MB")
            res["download"] = download(row["ont_fastq_url"], fastq, row["ont_fastq_md5"], size)
            res["download"]["ena_file_name"] = Path(urllib.parse.urlsplit(row["ont_fastq_url"]).path).name
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
                                                            "is_valid", "validation_message")}
            res["imported_file"]["sha256_matches_download"] = raw.get("checksum_sha256") == res["download"]["sha256"]
            if not raw["is_valid"]:
                raise RuntimeError(f"ARVA marked the FASTQ invalid: {raw.get('validation_message')}")
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
            polished_job = None
            try:
                started = self.api.post(f"/assemblies/{draft['id']}/polishing", {
                    "strategy": "medaka", "inputs": inputs, "medaka": {"model": MEDAKA_MODEL},
                    "threads": self.args.threads})
            except ApiError as exc:
                if exc.status not in (400, 409, 422):
                    raise
                res["skipped"]["medaka"] = {"model_requested": MEDAKA_MODEL, "http_status": exc.status,
                                            "arva_refusal": exc.payload}
                res["deviations"].append(
                    f"Medaka with {MEDAKA_MODEL} was refused by ARVA (HTTP {exc.status}); the assembly was polished "
                    "with Racon (minimap2 map-ont, ARVA's Racon defaults) instead. The paper used Rebaler then Medaka "
                    "v1.0.3 (model not stated).")
                log(f"{name}: Medaka refused by ARVA ({exc.status}); polishing with Racon")
            else:
                t0 = time.monotonic()
                polished_job = self.wait(started["id"], "polishing_medaka")
                steps["polishing_medaka"] = job_record(polished_job, time.monotonic() - t0)
                if polished_job["status"] != "completed":
                    raise RuntimeError(f"Medaka {polished_job['status']}: {polished_job.get('error_message')}")
            if polished_job is None:
                polished_job = self.run_job("polishing_racon", f"/assemblies/{draft['id']}/polishing", {
                    "strategy": "racon", "inputs": inputs, "racon": RACON, "threads": self.args.threads}, steps)
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
        if sample_id is not None:
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

    def remove_sample(self, sample_id: str) -> None:
        """DELETE the sample through the API, then its imported copy under raw/ (ARVA keeps raw/ on deletion)."""
        if not UUID.fullmatch(sample_id) or not UUID.fullmatch(self.project_id or ""):
            raise RuntimeError("unexpected identifiers")
        self.api.delete(f"/samples/{sample_id}")
        raw = (self.args.storage_root / "raw" / self.project_id / sample_id).resolve()
        base = (self.args.storage_root / "raw").resolve()
        if raw.is_dir() and base in raw.parents:
            shutil.rmtree(raw)

    def cleanup(self, res: dict, sample_id: str | None, folder: Path) -> None:
        done = {}
        if sample_id is not None:
            try:
                self.idle(sample_id)
                self.remove_sample(sample_id)
                done["arva_sample_deleted"] = True
                done["arva_raw_copy_removed"] = True
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
        "contigs": stats.get("contig_count"), "total_length": stats.get("total_length"), "n50": stats.get("n50"),
        "step_seconds": {k: v.get("wall_seconds") for k, v in res.get("steps", {}).items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--isolates", type=Path, default=HERE / "isolates.tsv")
    ap.add_argument("--expected", type=Path, default=HERE / "expected.tsv")
    ap.add_argument("--results", type=Path, default=HERE / "results")
    ap.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS, help="an ARVA import folder")
    ap.add_argument("--storage-root", type=Path, default=API_DIR / "data", help="ARVA_STORAGE_ROOT of the running API")
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
    ap.add_argument("--logs", type=Path, default=DEFAULT_LOGS, help="API and worker logs with --start-arva")
    args = ap.parse_args()
    args.results.mkdir(parents=True, exist_ok=True)
    args.downloads.mkdir(parents=True, exist_ok=True)

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
