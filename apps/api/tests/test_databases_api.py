"""Database Manager: catalogue facts, downloads from a local HTTP server with tiny fake archives (checksum match and
mismatch, resume, cancellation, path traversal, insufficient space), registration checks, verification, deletion
and the database recorded on jobs.

The fake archives imitate the layout of a Bakta database (version.json and empty files with Bakta's file names);
they are not Bakta databases. The last test checks a real Bakta light database and is skipped without one.
"""
import dataclasses
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.models import AnalysisJob, JobStatus, ReferenceDatabase
from app.services import database_catalogue as catalogue
from app.services import databases as svc
from app.tasks import databases as tasks

API = "/api/v1"
VERSION = {"date": "2025-02-24", "major": 6, "minor": 0, "type": "light", "doi": "10.5281/zenodo.14916843"}
REAL_LIGHT_DB = Path(os.environ.get("ARVA_TEST_BAKTA_DB", "/root/.arva-db/bakta-light/6.0"))


def _add(tar: tarfile.TarFile, name: str, data: bytes = b"", **attrs) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    for k, v in attrs.items():
        setattr(info, k, v)
    tar.addfile(info, io.BytesIO(data) if info.isreg() else None)


def bakta_archive(path: Path, top: str = "db-light", version: dict | None = None, extra=None, omit=()) -> bytes:
    with tarfile.open(path, "w:xz") as tar:
        _add(tar, top, type=tarfile.DIRTYPE, mode=0o755)
        _add(tar, f"{top}/version.json", json.dumps(version or VERSION).encode())
        for name in (*catalogue.BAKTA_REQUIRED_FILES, "pscc.dmnd"):
            if name not in omit:
                _add(tar, f"{top}/{name}", f"fake {name} — not a Bakta database file\n".encode() * 20)
        for args, attrs in extra or ():
            _add(tar, *args, **attrs)
    return path.read_bytes()


class Server:
    """Serves bytes at /db-light.tar.xz, with byte ranges unless `ranges` is False; `cut_once` sends only that many
    bytes of the next response and closes the connection; `pause_at` writes that many bytes, calls `on_pause`, waits,
    then sends the rest."""

    def __init__(self, data: bytes):
        self.data = data
        self.ranges = True
        self.cut_once: int | None = None
        self.pause_at: int | None = None
        self.on_pause = None
        self.range_headers: list[str | None] = []
        state = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/db-light.tar.xz":
                    self.send_error(404)
                    return
                rng = self.headers.get("Range")
                state.range_headers.append(rng)
                start = int(rng.removeprefix("bytes=").rstrip("-")) if rng and state.ranges else 0
                if start >= len(state.data):
                    self.send_error(416)
                    return
                self.send_response(206 if start else 200)
                if start:
                    self.send_header("Content-Range", f"bytes {start}-{len(state.data) - 1}/{len(state.data)}")
                body = state.data[start:]
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if state.cut_once is not None:
                    self.wfile.write(body[:state.cut_once])
                    state.cut_once = None
                    self.close_connection = True
                    return
                if state.pause_at is not None:
                    self.wfile.write(body[:state.pause_at])
                    self.wfile.flush()
                    state.on_pause()
                    time.sleep(0.3)
                    body = body[state.pause_at:]
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/db-light.tar.xz"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(autouse=True)
def empty_database_folder(storage_root):
    yield
    shutil.rmtree(storage_root / "databases", ignore_errors=True)


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """Replace the catalogue's Bakta light entry by one pointing at a local server with a fake archive."""
    servers = []

    def make(data: bytes | None = None, checksum: str | None = None) -> Server:
        data = data if data is not None else bakta_archive(tmp_path / f"a{len(servers)}.tar.xz")
        server = Server(data)
        servers.append(server)
        fake = dataclasses.replace(catalogue.BY_KEY["bakta-light"], download_url=server.url, archive_bytes=len(data),
                                   checksum=checksum or hashlib.md5(data).hexdigest(),
                                   extracted_bytes_estimate=1024 * 1024)
        monkeypatch.setitem(catalogue.BY_KEY, "bakta-light", fake)
        return server

    yield make
    for s in servers:
        s.close()


def _download(client, key="bakta-light", **overrides):
    size = catalogue.BY_KEY[key].archive_bytes
    return client.post(f"{API}/databases/downloads",
                       json={"key": key, "confirm_bytes": size, "accept_licence": True, **overrides})


def _record(client, record_id):
    return client.get(f"{API}/databases/{record_id}").json()


# --- Catalogue --------------------------------------------------------------------------------------------------

def test_bakta_catalogue_entries_carry_the_published_facts(client):
    keys = [e.key for e in catalogue.CATALOGUE]
    assert len(keys) == len(set(keys))
    for e in catalogue.for_kind("bakta"):
        assert e.download_url.startswith("https://zenodo.org/api/records/14916843/files/")
        assert e.download_url.endswith(f"/{e.filename}/content")
        assert re.fullmatch(r"[0-9a-f]{32}", e.checksum) and e.checksum_algorithm == "md5"
        assert len(e.checksum_sources) == 3 and e.licence == "CC BY 4.0" and e.licence_url and e.terms
        assert e.version == "6.0" and e.top_dir and e.db_type in catalogue.BAKTA_TYPE_FILE
        assert e.extracted_bytes_estimate > e.archive_bytes > 0 and e.extracted_size_note
        assert e.source_url == "https://zenodo.org/records/14916843" and e.doi == "10.5281/zenodo.14916843"
    light, full = catalogue.BY_KEY["bakta-light"], catalogue.BY_KEY["bakta-full"]
    assert (light.archive_bytes, light.checksum) == (1_344_199_496, "4a6e059ded39e9c5537ef4137d2f5648")
    assert (full.archive_bytes, full.checksum) == (31_921_769_288, "4c1115e40abfa2b464ae5dd988bdd88e")
    assert "tens of gigabytes" in full.description and full.extracted_bytes_estimate > 80 * 1024**3
    listed = client.get(f"{API}/databases/catalogue").json()
    assert [e["key"] for e in listed] == keys and {e["status"] for e in listed} == {"available"}
    assert client.get(f"{API}/databases/catalogue/nope/plan").status_code == 404


# --- Downloads --------------------------------------------------------------------------------------------------

def test_download_verifies_unpacks_installs_and_reverifies(client, serve, storage_root):
    server = serve()
    plan = client.get(f"{API}/databases/catalogue/bakta-light/plan").json()
    assert plan["enough"] and plan["partial_bytes"] == 0 and plan["blocked_by"] is None
    assert plan["required_bytes"] == len(server.data) + 1024 * 1024
    assert plan["target_path"] == str(storage_root.resolve() / "databases" / "bakta-light" / "6.0")

    r = _download(client)
    assert r.status_code == 202, r.text
    db = r.json()
    assert db["status"] == "installed" and db["origin"] == "download" and db["version"] == "6.0"
    assert db["kind"] == "bakta" and db["version_source"] == "file" and db["verification_level"] == "full"
    assert db["archive_checksum"] == f"md5:{hashlib.md5(server.data).hexdigest()}"
    assert db["checksum"].startswith("sha256:") and db["files"] == len(catalogue.BAKTA_REQUIRED_FILES) + 2
    assert db["licence"] == "CC BY 4.0" and db["source_url"] == "https://zenodo.org/records/14916843"
    folder = Path(db["path"])
    assert json.loads((folder / "version.json").read_text())["type"] == "light"
    assert (folder / "bakta.db").stat().st_mode & 0o222 == 0
    assert not list((storage_root / "databases" / svc.DOWNLOADS).rglob("*.part"))
    assert not list((storage_root / "databases" / svc.STAGING).rglob("*"))
    assert "matches the published checksum" in _record(client, db["id"])["log_text"]
    assert client.get(f"{API}/databases/catalogue/bakta-light/plan").json()["blocked_by"]
    assert _download(client).status_code == 409

    verified = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert verified["status"] == "installed" and verified["verified_at"] >= db["verified_at"]

    (folder / "pfam.h3m").chmod(0o644)
    (folder / "pfam.h3m").write_bytes(b"changed")
    failed = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert failed["status"] == "failed" and "1 file(s) changed" in failed["error_message"]
    assert "pfam.h3m" in failed["error_message"]

    usage = client.get(f"{API}/databases/usage").json()
    assert usage["installed_bytes"] == db["size_bytes"] and usage["db_dir"] == str(folder.parents[1])
    assert client.delete(f"{API}/databases/{db['id']}").status_code == 204
    assert not folder.exists() and client.get(f"{API}/databases").json() == []


def test_download_needs_the_confirmed_size_and_the_licence(client, serve):
    serve()
    assert _download(client, confirm_bytes=1).status_code == 400
    r = _download(client, accept_licence=False)
    assert r.status_code == 400 and "licence" in r.json()["detail"]
    assert client.get(f"{API}/databases").json() == []


def test_checksum_mismatch_deletes_the_archive_and_installs_nothing(client, serve, storage_root):
    serve(checksum="0" * 32)
    db = _download(client).json()
    assert db["status"] == "failed" and "published MD5 is 00000000" in db["error_message"]
    assert not list((storage_root / "databases").rglob("*.part"))
    assert not Path(db["path"]).exists()


def test_insufficient_space_is_refused_before_anything_is_downloaded(client, serve, monkeypatch):
    server = serve()
    monkeypatch.setattr(svc, "free_bytes", lambda _p: 10)
    plan = client.get(f"{API}/databases/catalogue/bakta-light/plan").json()
    assert not plan["enough"] and plan["available_bytes"] == 0
    r = _download(client)
    assert r.status_code == 507 and r.json()["needed_bytes"] == plan["required_bytes"]
    assert server.range_headers == [] and client.get(f"{API}/databases").json() == []


def test_interrupted_download_resumes_with_a_range_request(client, serve):
    server = serve()
    server.cut_once = len(server.data) // 2
    first = _download(client).json()
    assert first["status"] == "failed" and "start" in first["error_message"]
    plan = client.get(f"{API}/databases/catalogue/bakta-light/plan").json()
    assert plan["partial_bytes"] == len(server.data) // 2 and plan["resume_record_id"] == first["id"]
    second = _download(client).json()
    assert second["id"] == first["id"] and second["status"] == "installed"
    assert server.range_headers == [None, f"bytes={len(server.data) // 2}-"]
    assert "Resuming the download at byte" in _record(client, first["id"])["log_text"]


def test_a_server_that_ignores_ranges_is_downloaded_again_from_the_start(client, serve):
    server = serve()
    server.cut_once = 100
    first = _download(client).json()
    server.ranges = False
    second = _download(client).json()
    assert second["status"] == "installed", second["error_message"]
    assert "ignored the range request" in _record(client, first["id"])["log_text"]


def test_cancelling_a_running_download_keeps_the_partial_file_for_resuming(client, serve, monkeypatch, storage_root):
    server = serve()
    monkeypatch.setattr(tasks, "CHUNK", 64)
    monkeypatch.setattr(tasks, "TICK_SECONDS", 0.0)
    server.pause_at = len(server.data) // 2

    def cancel_now():
        # Only once the worker has written some bytes, so that the test does not depend on how fast the database
        # connection below opens.
        deadline = time.monotonic() + 5
        parts = storage_root / "databases" / ".arva-downloads"
        while time.monotonic() < deadline and not any(p.stat().st_size for p in parts.rglob("*.part")):
            time.sleep(0.01)
        with engine.begin() as conn:
            conn.execute(text("UPDATE reference_databases SET cancel_requested_at = now()"))

    server.on_pause = cancel_now
    db = _download(client).json()
    assert db["status"] == "cancelled" and db["error_message"] is None
    plan = client.get(f"{API}/databases/catalogue/bakta-light/plan").json()
    assert 0 < plan["partial_bytes"] < len(server.data)
    server.pause_at = None
    again = _download(client).json()
    assert again["status"] == "installed" and server.range_headers[-1] == f"bytes={plan['partial_bytes']}-"


def test_cancelling_a_queued_download_stops_it_before_it_runs(client, serve, held_queue):
    serve()
    db = _download(client).json()
    assert db["status"] == "downloading"
    cancelled = client.post(f"{API}/databases/{db['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert tasks.run_database_download(db["id"]) == "cancelled"
    assert client.post(f"{API}/databases/{db['id']}/cancel").status_code == 409


@pytest.mark.parametrize(("extra", "reason"), [
    ([(("db-light/../evil.txt", b"x"), {})], "contains '..'"),
    ([(("/tmp/arva-evil.txt", b"x"), {})], "absolute path"),
    ([(("other/file.txt", b"x"), {})], "outside the expected folder"),
    ([(("db-light/escape",), {"type": tarfile.SYMTYPE, "linkname": "../../../../etc"})], "points outside"),
    ([(("db-light/abs",), {"type": tarfile.SYMTYPE, "linkname": "/etc/passwd"})], "absolute or invalid target"),
    ([(("db-light/fifo",), {"type": tarfile.FIFOTYPE})], "device or FIFO"),
    ([(("db-light/bakta.db/inside", b"x"), {})], "could not be unpacked"),
])
def test_unsafe_archives_are_rejected_and_nothing_is_installed(client, serve, tmp_path, extra, reason):
    serve(bakta_archive(tmp_path / "evil.tar.xz", extra=extra))
    db = _download(client).json()
    assert db["status"] == "failed" and reason in db["error_message"]
    assert not Path(db["path"]).exists() and not Path("/tmp/arva-evil.txt").exists()
    assert not (Path(db["path"]).parents[2] / "evil.txt").exists()


def test_extract_accepts_links_that_stay_inside_and_never_writes_through_them(tmp_path):
    archive = tmp_path / "links.tar"
    with tarfile.open(archive, "w") as tar:
        _add(tar, "db/a.txt", b"a")
        _add(tar, "db/sub", type=tarfile.SYMTYPE, linkname=".")
        _add(tar, "db/hard.txt", type=tarfile.LNKTYPE, linkname="db/a.txt")
    tasks.extract(archive, tmp_path / "out", "db", lambda _r, _w: None)
    assert os.readlink(tmp_path / "out" / "db" / "sub") == "." and (tmp_path / "out/db/hard.txt").read_text() == "a"

    nested = tmp_path / "nested.tar"
    with tarfile.open(nested, "w") as tar:
        _add(tar, "db/d", type=tarfile.DIRTYPE)
        _add(tar, "db/link", type=tarfile.SYMTYPE, linkname="d")
        _add(tar, "db/link/inner", type=tarfile.SYMTYPE, linkname="..")
    with pytest.raises(tasks.UnsafeArchive, match="under another link"):
        tasks.extract(nested, tmp_path / "out2", "db", lambda _r, _w: None)


def test_downloaded_archive_without_the_bakta_files_is_not_installed(client, serve, tmp_path):
    serve(bakta_archive(tmp_path / "partial.tar.xz", omit=("sorf.dmnd",)))
    db = _download(client).json()
    assert db["status"] == "failed" and "sorf.dmnd" in db["error_message"] and not Path(db["path"]).exists()


# --- Registration -----------------------------------------------------------------------------------------------

def _bakta_folder(path: Path, version: dict | None = None, omit=()) -> Path:
    path.mkdir(parents=True)
    (path / "version.json").write_text(json.dumps(version or VERSION))
    for name in (*catalogue.BAKTA_REQUIRED_FILES, "pscc.dmnd"):
        if name not in omit:
            (path / name).write_text(f"fake {name}")
    return path


def test_registration_checks_the_folder_like_bakta_and_never_touches_it(client, storage_root, tmp_path):
    root = storage_root.resolve() / "databases"
    register = lambda p: client.post(f"{API}/databases/register", json={"path": str(p)})  # noqa: E731
    assert register("relative/path").status_code == 400
    outside = _bakta_folder(tmp_path / "outside")
    assert register(outside).json()["code"] == "outside_roots"
    empty = root / "custom" / "empty"
    empty.mkdir(parents=True)
    assert register(empty).json()["code"] == "not_recognised"
    no_type = _bakta_folder(root / "custom" / "no-type", {k: v for k, v in VERSION.items() if k != "type"})
    assert "needs date, major, minor and type" in register(no_type).json()["detail"]
    missing = _bakta_folder(root / "custom" / "missing", omit=("pscc.dmnd",))
    assert "pscc.dmnd" in register(missing).json()["detail"]
    assert client.get(f"{API}/databases").json() == []

    good = _bakta_folder(root / "custom" / "good", {**VERSION, "minor": 1})
    r = register(good)
    assert r.status_code == 201, r.text
    db = r.json()
    assert db["status"] == "registered" and db["origin"] == "register" and db["version"] == "6.1"
    assert db["key"] == "bakta-light" and db["kind"] == "bakta" and db["checksum"] is None
    assert db["verification_level"] == "quick" and db["version_source"] == "file"
    assert "differs from the catalogue" in db["notes"] and db["catalogue_version"] == "6.0"
    assert register(good).status_code == 409
    full = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert full["status"] == "registered" and full["checksum"].startswith("sha256:")
    assert client.delete(f"{API}/databases/{db['id']}").status_code == 204
    assert (good / "version.json").is_file() and (good / "bakta.db").is_file()


# --- Use by jobs ------------------------------------------------------------------------------------------------

def test_jobs_record_the_database_and_block_its_deletion(client, storage_root):
    folder = _bakta_folder(storage_root.resolve() / "databases" / "custom" / "for-job")
    db_id = client.post(f"{API}/databases/register", json={"path": str(folder), "full_checksum": True}).json()["id"]
    project_id = client.post(f"{API}/projects", json={"name": "Database use"}).json()["id"]
    with SessionLocal() as session:
        record = session.get(ReferenceDatabase, db_id)
        job = AnalysisJob(project_id=project_id, job_type="annotation", tool_name="test", tool_version="0",
                          status=JobStatus.pending, log_text="")
        svc.record_use(job, record)
        session.add(job)
        session.commit()
        job_id, checksum = job.id, record.checksum
    r = client.delete(f"{API}/databases/{db_id}")
    assert r.status_code == 409 and "1 queued or running job" in r.json()["detail"]
    assert client.get(f"{API}/databases").json()[0]["jobs_using"] == 1
    with engine.begin() as conn:
        conn.execute(text("UPDATE analysis_jobs SET status = 'completed' WHERE id = :id"), {"id": job_id})
    assert client.delete(f"{API}/databases/{db_id}").status_code == 204
    job = client.get(f"{API}/jobs/{job_id}").json()
    assert (job["database_key"], job["database_version"], job["database_checksum"]) == ("bakta-light", "6.0", checksum)
    assert checksum.startswith("sha256:") and job["database_path"] == str(folder) and job["database_kind"] == "bakta"
    assert job["reference_database_id"] is None


# --- Real database ----------------------------------------------------------------------------------------------

@pytest.mark.skipif(not (REAL_LIGHT_DB / "version.json").is_file(), reason="no Bakta light database installed")
def test_real_bakta_light_database_passes_bakta_folder_check():
    info = svc.check_bakta_dir(REAL_LIGHT_DB)
    assert (info["major"], info["minor"], info["type"]) == (6, 0, "light")
    assert {"name": "AMRFinderPlus", "release": "2024-12-18.1"} in info["dependencies"]
    assert tasks.amrfinder_info(REAL_LIGHT_DB) == {"latest": "2024-12-18.1", "version": "2024-12-18.1",
                                                   "database_format": "4.0.1"}
