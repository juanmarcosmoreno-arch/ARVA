"""Storage capacity checks, server-folder import and duplicate detection across samples."""
import gzip
import hashlib
import io
import os
import shutil
import stat
import tempfile
import threading
from types import SimpleNamespace

import pytest

from app import __version__
from app.api.capacity import UploadCapacityGuard
from app.core.config import Settings, get_settings
from app.services import capacity as capacity_service
from app.services.import_roots import (
    MAX_ENTRIES,
    ImportPathError,
    get_root,
    open_source,
    resolve_file,
)
from app.storage import local as local_storage
from app.tasks import server_import

API = "/api/v1"
GIB = 1024**3
RESERVE = 1000
FASTQ = b"@r1\nACGT\n+\nIIII\n@r2\nGGGCCC\n+\n555555\n"
FASTQ_B = b"@x1\nTTTTAA\n+\nIIIIII\n"
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def fake_disk(monkeypatch, *free_values, total=2000 * GIB):
    """Successive shutil.disk_usage calls return the given free sizes; the last one repeats."""
    values = list(free_values)

    def usage(_path):
        free = values.pop(0) if len(values) > 1 else values[0]
        return SimpleNamespace(total=total, used=total - free, free=free)

    monkeypatch.setattr(shutil, "disk_usage", usage)


@pytest.fixture
def reserve(monkeypatch):
    monkeypatch.setattr(get_settings(), "min_free_bytes", RESERVE)


@pytest.fixture
def spool_factor(monkeypatch):
    """Pins whether uploads are spooled on the data disk (2) or elsewhere (1)."""
    def set_factor(factor):
        monkeypatch.setattr(capacity_service, "upload_overhead_factor", lambda _root: factor)
    set_factor(1)
    return set_factor


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    root = tmp_path / "import"
    root.mkdir()
    monkeypatch.setattr(get_settings(), "import_roots", [root])
    return root


@pytest.fixture
def no_import_roots(monkeypatch):
    monkeypatch.setattr(get_settings(), "import_roots", [])


def make_sample(client, code="S1", project=None):
    if project is None:
        project = client.post(f"{API}/projects", json={"name": f"Import tests {code}"}).json()
    r = client.post(f"{API}/projects/{project['id']}/samples", json={"sample_code": code})
    assert r.status_code == 201, r.text
    return project, r.json()


def upload(client, sample_id, name, content):
    return client.post(
        f"{API}/samples/{sample_id}/files",
        files=[("files", (name, io.BytesIO(content), "application/octet-stream"))],
    )


def start_import(client, sample_id, paths, root=0):
    return client.post(f"{API}/samples/{sample_id}/files/import-server", json={"root": root, "paths": paths})


def run_import(client, sample_id, paths):
    r = start_import(client, sample_id, paths)
    assert r.status_code == 202, r.text
    return client.get(f"{API}/jobs/{r.json()['id']}").json()


def browse(client, path="", root=0):
    return client.get(f"{API}/imports/browse", params={"root": root, "path": path})


# --- Storage capacity -----------------------------------------------------------

def test_default_reserve_is_one_gib():
    assert Settings.model_fields["min_free_bytes"].default == GIB


def test_storage_endpoint(client, monkeypatch, reserve, storage_root, spool_factor):
    fake_disk(monkeypatch, 5000)
    spool_factor(2)
    body = client.get(f"{API}/system/storage").json()
    assert {k: body[k] for k in ("storage_root", "free_bytes", "total_bytes", "min_free_bytes",
                                 "available_for_data_bytes", "upload_overhead_factor")} == {
        "storage_root": str(storage_root.resolve()),
        "free_bytes": 5000,
        "total_bytes": 2000 * GIB,
        "min_free_bytes": RESERVE,
        "available_for_data_bytes": 4000,
        "upload_overhead_factor": 2,
    }
    fake_disk(monkeypatch, 10)
    spool_factor(1)
    body = client.get(f"{API}/system/storage").json()
    assert body["available_for_data_bytes"] == 0 and body["upload_overhead_factor"] == 1


def test_upload_overhead_factor_follows_the_spool_disk(monkeypatch, storage_root):
    monkeypatch.setattr(tempfile, "tempdir", str(storage_root))
    assert capacity_service.upload_overhead_factor(storage_root) == 2

    spool = str(storage_root / "elsewhere")
    real_stat = os.stat

    def other_device(path, *args, **kwargs):
        if str(path) == spool:
            return SimpleNamespace(st_dev=real_stat(storage_root).st_dev + 1)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(tempfile, "tempdir", spool)
    monkeypatch.setattr(os, "stat", other_device)
    assert capacity_service.upload_overhead_factor(storage_root) == 1
    # Unknown spool location: assume the worst case.
    monkeypatch.setattr(os, "stat", real_stat)
    assert capacity_service.upload_overhead_factor(storage_root) == 2


def test_upload_larger_than_free_space_is_refused_with_507(client, monkeypatch, reserve, storage_root):
    p, s = make_sample(client)
    fake_disk(monkeypatch, RESERVE + 100)
    r = upload(client, s["id"], "big.fastq", FASTQ * 20)
    assert r.status_code == 507
    body = r.json()
    assert "Not enough free space" in body["detail"] and "only 100 B can be used" in body["detail"]
    assert body["available_bytes"] == 100 and body["needed_bytes"] > len(FASTQ * 20)
    assert client.get(f"{API}/samples/{s['id']}/files").json() == []
    assert not (storage_root / "raw" / p["id"]).exists()


async def test_upload_guard_answers_before_reading_the_body(monkeypatch, reserve, spool_factor):
    fake_disk(monkeypatch, RESERVE + 10)
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        raise AssertionError("the request body must not be read")

    sent = []

    async def send(message):
        sent.append(message)

    guard = UploadCapacityGuard(inner, "/api/v1")
    scope = {"type": "http", "method": "POST", "path": "/api/v1/samples/abc/files",
             "headers": [(b"content-length", b"5000000000")]}
    await guard(scope, receive, send)
    assert sent[0]["status"] == 507 and reached == []

    for path in ("/api/v1/samples/abc/files/import-server", "/api/v1/projects"):
        await guard({**scope, "path": path}, receive, send)
    await guard({**scope, "method": "GET"}, receive, send)
    assert reached == ["/api/v1/samples/abc/files/import-server", "/api/v1/projects", "/api/v1/samples/abc/files"]

    sent.clear()
    for headers in ([], [(b"transfer-encoding", b"chunked")], [(b"content-length", b"lots")]):
        await guard({**scope, "headers": headers}, receive, send)
        assert sent[-2]["status"] == 411
    assert len(reached) == 3


def test_chunked_upload_is_refused_before_it_is_spooled(client, monkeypatch, reserve):
    _, s = make_sample(client)
    fake_disk(monkeypatch, 10 * GIB)

    def body():
        for _ in range(4):
            yield b"x" * 1024

    r = client.post(
        f"{API}/samples/{s['id']}/files",
        content=body(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert r.status_code == 411
    assert "Content-Length" in r.json()["detail"]
    assert client.get(f"{API}/samples/{s['id']}/files").json() == []


def test_spooled_upload_counts_twice_on_the_data_disk(client, monkeypatch, reserve, spool_factor):
    _, s = make_sample(client)
    content = FASTQ * 20
    # Room for the file once (plus multipart overhead), not for the spooled copy as well.
    fake_disk(monkeypatch, RESERVE + len(content) + 400)
    spool_factor(2)
    r = upload(client, s["id"], "a.fastq", content)
    assert r.status_code == 507
    assert "twice its size" in r.json()["detail"] and r.json()["needed_bytes"] > 2 * len(content)

    spool_factor(1)
    assert upload(client, s["id"], "a.fastq", content).json()["rejected"] == []


def test_spooled_upload_that_was_admitted_is_stored(client, monkeypatch, reserve, spool_factor):
    _, s = make_sample(client)
    content = FASTQ * 20
    spool_factor(2)
    # The guard sees room for 2x; spooling then uses 1x before the per-file check.
    fake_disk(monkeypatch, RESERVE + 2 * len(content) + 800, RESERVE + len(content) + 400)
    r = upload(client, s["id"], "a.fastq", content)
    assert r.status_code == 201, r.text
    assert r.json()["rejected"] == [] and len(r.json()["files"]) == 1


def test_each_file_is_rechecked_before_storing(client, monkeypatch, reserve):
    _, s = make_sample(client)
    # The request passes the Content-Length check, then the space is gone when the file is stored.
    fake_disk(monkeypatch, 10 * GIB, RESERVE + 10)
    r = upload(client, s["id"], "a.fastq", FASTQ)
    assert r.status_code == 201, r.text
    assert r.json()["files"] == []
    assert "Not enough free space" in r.json()["rejected"][0]["reason"]
    assert r.json()["rejected"][0]["code"] == "insufficient_storage"


def test_free_space_is_rechecked_while_streaming(client, monkeypatch, reserve, storage_root):
    p, s = make_sample(client)
    monkeypatch.setattr(local_storage, "SPACE_CHECK_BYTES", 1)
    # Guard and per-file check pass; then another writer uses the rest while this file streams.
    fake_disk(monkeypatch, 10 * GIB, 10 * GIB, RESERVE)
    r = upload(client, s["id"], "a.fastq", FASTQ)
    assert r.status_code == 201, r.text
    assert r.json()["files"] == []
    assert r.json()["rejected"][0]["code"] == "insufficient_storage"
    assert not [f for f in (storage_root / "raw" / p["id"]).rglob("*") if f.is_file()]


def test_oversize_upload_is_refused_before_copying(client, monkeypatch):
    _, s = make_sample(client)
    monkeypatch.setattr(get_settings(), "max_upload_size_bytes", 100)
    copies = []
    monkeypatch.setattr(local_storage.LocalStorage, "save_stream", lambda *a, **k: copies.append(a))
    r = upload(client, s["id"], "a.fastq", FASTQ * 20)
    assert r.json()["files"] == [] and copies == []
    rejection = r.json()["rejected"][0]
    assert rejection["code"] == "too_large" and "100 byte limit" in rejection["reason"]


# --- Duplicates across samples ----------------------------------------------------

def test_identical_content_in_another_sample_is_accepted_with_a_note(client):
    p, a = make_sample(client, "A-1")
    _, b = make_sample(client, "B-2", project=p)
    first = upload(client, a["id"], "reads_a.fastq", FASTQ).json()["files"][0]
    assert "Note:" not in first["validation_message"]

    second = upload(client, b["id"], "reads_b.fastq", FASTQ).json()
    assert second["rejected"] == []
    assert second["files"][0]["validation_message"].endswith(
        "Note: identical content is already registered in sample A-1 as reads_a.fastq."
    )

    again = upload(client, b["id"], "copy.fastq", FASTQ).json()
    assert again["files"] == []
    assert "already registered for this sample" in again["rejected"][0]["reason"]
    assert again["rejected"][0]["code"] == "duplicate"

    _, other_project_sample = make_sample(client, "C-3")
    third = upload(client, other_project_sample["id"], "reads_c.fastq", FASTQ).json()["files"][0]
    assert "Note:" not in third["validation_message"]


# --- Import folders: listing and browsing -------------------------------------------

def test_import_roots_listing(client, tmp_path, monkeypatch, no_import_roots):
    assert client.get(f"{API}/imports/roots").json() == []
    assert browse(client).status_code == 400

    runs = tmp_path / "runs"
    runs.mkdir()
    missing = tmp_path / "missing"
    monkeypatch.setattr(get_settings(), "import_roots", [runs, missing])
    assert client.get(f"{API}/imports/roots").json() == [
        {"index": 0, "name": "runs", "path": str(runs), "exists": True},
        {"index": 1, "name": "missing", "path": str(missing), "exists": False},
    ]
    assert browse(client, root=1).status_code == 400
    assert browse(client, root=2).status_code == 400
    assert browse(client, root=-1).status_code == 422


@pytest.fixture
def tree(import_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.fastq").write_bytes(FASTQ)
    (import_root / "run1" / "lane1").mkdir(parents=True)
    (import_root / "Zeta").mkdir()
    (import_root / ".hidden").mkdir()
    (import_root / ".secret.fastq").write_bytes(FASTQ)
    (import_root / "S1_R1_001.fastq.gz").write_bytes(gzip.compress(FASTQ))
    (import_root / "contigs.fna").write_bytes(b">c1\nACGT\n")
    (import_root / "reads.pod5").write_bytes(b"POD5")
    (import_root / "notes.txt").write_bytes(b"hello")
    (import_root / "inner_link.fastq").symlink_to(import_root / "S1_R1_001.fastq.gz")
    (import_root / "escape.fastq").symlink_to(outside / "secret.fastq")
    (import_root / "escape_dir").symlink_to(outside)
    return import_root


def test_browse_lists_folders_first_and_hides_dotfiles_and_escaping_links(client, tree):
    r = browse(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["root"] == 0 and body["path"] == "" and body["parent"] is None and body["truncated"] is False
    rows = [(e["name"], e["type"], e["kind"]) for e in body["entries"]]
    assert rows == [
        ("run1", "dir", "other"),
        ("Zeta", "dir", "other"),
        ("contigs.fna", "file", "fasta"),
        ("inner_link.fastq", "file", "fastq"),
        ("notes.txt", "file", "other"),
        ("reads.pod5", "file", "pod5"),
        ("S1_R1_001.fastq.gz", "file", "fastq"),
    ]
    by_name = {e["name"]: e for e in body["entries"]}
    assert by_name["run1"]["size_bytes"] is None
    assert by_name["notes.txt"]["size_bytes"] == 5 and by_name["notes.txt"]["path"] == "notes.txt"
    assert by_name["notes.txt"]["modified_at"]

    sub = browse(client, "run1").json()
    assert sub["path"] == "run1" and sub["parent"] == "" and sub["entries"][0]["path"] == "run1/lane1"
    assert browse(client, "run1/lane1/").json()["parent"] == "run1"


@pytest.mark.parametrize("path", ["..", "../outside", "run1/../..", "run1/..", "/etc", "/", "escape_dir",
                                  ".hidden", "notes.txt", "does-not-exist", "a\\..\\b"])
def test_browse_rejects_paths_outside_or_invalid(client, tree, path):
    r = browse(client, path)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]


def test_browse_truncates_large_folders(client, import_root):
    big = import_root / "big"
    big.mkdir()
    for i in range(MAX_ENTRIES + 5):
        (big / f"f{i:05d}.fastq").touch()
    body = browse(client, "big").json()
    assert body["truncated"] is True
    assert len(body["entries"]) == MAX_ENTRIES
    assert body["entries"][0]["name"] == "f00000.fastq"


# --- Import folders: the import job ----------------------------------------------------

def test_server_import_copies_files_like_an_upload(client, import_root, storage_root):
    run = import_root / "run1"
    run.mkdir()
    r1 = run / "S1_R1_001.fastq.gz"
    r2 = run / "S1_R2_001.fastq.gz"
    r1.write_bytes(gzip.compress(FASTQ))
    r2.write_bytes(gzip.compress(FASTQ_B))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in (r1, r2)}
    paths = ["run1/S1_R1_001.fastq.gz", "run1/S1_R2_001.fastq.gz"]

    _, s = make_sample(client)
    job = run_import(client, s["id"], paths)
    assert job["status"] == "completed", job["log_text"]
    assert (job["job_type"], job["tool_name"], job["tool_version"]) == ("server_import", "arva-import", __version__)
    assert job["parameters"] == {"root": str(import_root), "paths": paths}
    assert job["input_raw_file_ids"] == []

    files = {f["original_filename"]: f for f in client.get(f"{API}/samples/{s['id']}/files").json()}
    assert set(files) == {"S1_R1_001.fastq.gz", "S1_R2_001.fastq.gz"}
    f1, f2 = files["S1_R1_001.fastq.gz"], files["S1_R2_001.fastq.gz"]
    assert (f1["read_mate"], f2["read_mate"]) == ("R1", "R2")
    assert f1["description"] == f"Imported from server: {import_root}/run1/S1_R1_001.fastq.gz"
    assert f1["file_format"] == "fastq_gz" and f1["is_valid"] is True and f1["origin"] == "imported"
    assert f1["checksum_sha256"] == hashlib.sha256(r1.read_bytes()).hexdigest()

    stored = next((storage_root / "raw").rglob(f"{f1['id']}__*"))
    assert stored.read_bytes() == r1.read_bytes()
    assert not stored.stat().st_mode & WRITE_BITS
    for path, (content, mtime, mode) in before.items():
        assert path.read_bytes() == content
        assert (path.stat().st_mtime_ns, path.stat().st_mode) == (mtime, mode)

    summary = job["result_summary"]
    assert summary["rejected"] == []
    assert [(i["file_id"], i["name"], i["size_bytes"]) for i in summary["imported"]] == [
        (f1["id"], f1["original_filename"], f1["size_bytes"]),
        (f2["id"], f2["original_filename"], f2["size_bytes"]),
    ]
    assert f1["id"] in job["log_text"] and "never modified or deleted" in job["log_text"]


def test_symlink_inside_the_root_can_be_imported(client, import_root):
    (import_root / "real.fastq").write_bytes(FASTQ)
    (import_root / "link.fastq").symlink_to(import_root / "real.fastq")
    _, s = make_sample(client)
    job = run_import(client, s["id"], ["link.fastq"])
    assert job["status"] == "completed", job["log_text"]
    assert job["result_summary"]["imported"][0]["name"] == "link.fastq"


def test_server_import_rejects_files_already_in_the_sample(client, import_root):
    (import_root / "a.fastq").write_bytes(FASTQ)
    (import_root / "b.fastq").write_bytes(FASTQ_B)
    _, s = make_sample(client)
    upload(client, s["id"], "already.fastq", FASTQ)

    job = run_import(client, s["id"], ["a.fastq", "b.fastq"])
    assert job["status"] == "completed", job["log_text"]
    summary = job["result_summary"]
    assert [i["name"] for i in summary["imported"]] == ["b.fastq"]
    assert summary["rejected"][0]["path"] == "a.fastq"
    assert "already registered for this sample as 'already.fastq'" in summary["rejected"][0]["reason"]
    assert "stay registered" in job["log_text"]
    assert len(client.get(f"{API}/samples/{s['id']}/files").json()) == 2


def test_server_import_fails_when_every_file_is_rejected(client, import_root):
    (import_root / "a.fastq").write_bytes(FASTQ)
    _, s = make_sample(client)
    upload(client, s["id"], "already.fastq", FASTQ)

    job = run_import(client, s["id"], ["a.fastq"])
    assert job["status"] == "failed"
    assert job["error_message"].startswith("No file was imported.")
    assert "already registered" in job["error_message"]
    assert job["result_summary"]["imported"] == []
    assert job["result_summary"]["rejected"][0]["path"] == "a.fastq"


def test_server_import_checks_free_space(client, import_root, monkeypatch, reserve):
    (import_root / "a.fastq").write_bytes(FASTQ * 10)
    _, s = make_sample(client)

    fake_disk(monkeypatch, RESERVE + 20)
    r = start_import(client, s["id"], ["a.fastq"])
    assert r.status_code == 507
    assert "Not enough free space" in r.json()["detail"]
    assert client.get(f"{API}/samples/{s['id']}/jobs").json() == []

    # Space disappears between the request and the copy: the worker re-checks every file.
    fake_disk(monkeypatch, 10 * GIB, RESERVE + 20)
    job = run_import(client, s["id"], ["a.fastq"])
    assert job["status"] == "failed"
    assert "Not enough free space" in job["result_summary"]["rejected"][0]["reason"]
    assert client.get(f"{API}/samples/{s['id']}/files").json() == []


def test_server_import_validates_every_path(client, import_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.fastq").write_bytes(FASTQ)
    (import_root / "ok.fastq").write_bytes(FASTQ)
    (import_root / "dir").mkdir()
    (import_root / ".hidden.fastq").write_bytes(FASTQ_B)
    (import_root / "escape.fastq").symlink_to(outside / "secret.fastq")
    _, s = make_sample(client)

    bad = [
        ["../outside/secret.fastq"],
        [str(outside / "secret.fastq")],
        ["escape.fastq"],
        ["ok.fastq", "missing.fastq"],
        ["dir"],
        [".hidden.fastq"],
        ["ok.fastq", "./ok.fastq"],
    ]
    for paths in bad:
        r = start_import(client, s["id"], paths)
        assert r.status_code == 400, (paths, r.text)
    assert start_import(client, s["id"], []).status_code == 422
    assert start_import(client, s["id"], ["ok.fastq"] * 501).status_code == 422
    assert start_import(client, s["id"], ["ok.fastq"], root=1).status_code == 400
    assert start_import(client, "no-such-sample", ["ok.fastq"]).status_code == 404
    assert client.get(f"{API}/samples/{s['id']}/jobs").json() == []


def test_server_import_disabled_without_roots(client, no_import_roots):
    _, s = make_sample(client)
    r = start_import(client, s["id"], ["a.fastq"])
    assert r.status_code == 400
    assert "not enabled" in r.json()["detail"]


def test_server_import_refuses_files_over_the_upload_limit(client, import_root, monkeypatch):
    (import_root / "ok.fastq").write_bytes(FASTQ)
    (import_root / "big.fastq").write_bytes(FASTQ * 100)
    monkeypatch.setattr(get_settings(), "max_upload_size_bytes", 1000)
    _, s = make_sample(client)
    r = start_import(client, s["id"], ["ok.fastq", "big.fastq"])
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "big.fastq: 3.5 KB is larger than the per-file limit of 1000 B (ARVA_MAX_UPLOAD_SIZE_BYTES=1000)"
    )
    assert client.get(f"{API}/samples/{s['id']}/jobs").json() == []


def test_server_import_rejects_a_source_that_changes_while_copied(client, import_root, storage_root, monkeypatch):
    growing = import_root / "growing.fastq"
    growing.write_bytes(FASTQ)
    rewritten = import_root / "rewritten.fastq"
    rewritten.write_bytes(FASTQ_B)
    real_open = server_import.open_source

    def open_then_change(root, selected):
        fh = real_open(root, selected)
        if selected.relative == "growing.fastq":
            with open(growing, "ab") as w:
                w.write(FASTQ * 50)
        else:
            # Same size, rewritten in place.
            with open(rewritten, "r+b") as w:
                w.write(b"@y")
            st = rewritten.stat()
            os.utime(rewritten, ns=(st.st_atime_ns, selected.mtime_ns + 10**9))
        return fh

    monkeypatch.setattr(server_import, "open_source", open_then_change)
    p, s = make_sample(client)
    job = run_import(client, s["id"], ["growing.fastq", "rewritten.fastq"])
    assert job["status"] == "failed", job["log_text"]
    reasons = {r["path"]: r["reason"] for r in job["result_summary"]["rejected"]}
    assert set(reasons) == {"growing.fastq", "rewritten.fastq"}
    assert all("changed while it was being copied" in r for r in reasons.values())
    assert client.get(f"{API}/samples/{s['id']}/files").json() == []
    assert not [f for f in (storage_root / "raw" / p["id"]).rglob("*") if f.is_file()]


def test_server_import_keeps_files_imported_before_an_unexpected_error(client, import_root, monkeypatch):
    (import_root / "a.fastq").write_bytes(FASTQ)
    (import_root / "b.fastq").write_bytes(FASTQ_B)
    real = server_import.register_raw_file
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("disk controller exploded")
        return real(*args, **kwargs)

    monkeypatch.setattr(server_import, "register_raw_file", fail_second)
    _, s = make_sample(client)
    job = run_import(client, s["id"], ["a.fastq", "b.fastq"])
    assert job["status"] == "failed"
    assert "disk controller exploded" in job["error_message"]
    assert [i["name"] for i in job["result_summary"]["imported"]] == ["a.fastq"]
    assert "1 file(s) imported before the failure stay registered" in job["log_text"]
    files = client.get(f"{API}/samples/{s['id']}/files").json()
    assert [f["original_filename"] for f in files] == ["a.fastq"]


def test_server_import_notes_identical_content_in_another_sample(client, import_root):
    (import_root / "reads.fastq").write_bytes(FASTQ)
    p, a = make_sample(client, "A-1")
    _, b = make_sample(client, "B-2", project=p)
    upload(client, a["id"], "reads_a.fastq", FASTQ)
    job = run_import(client, b["id"], ["reads.fastq"])
    assert job["status"] == "completed", job["log_text"]
    [f] = client.get(f"{API}/samples/{b['id']}/files").json()
    assert f["validation_message"].endswith("Note: identical content is already registered in sample A-1 as reads_a.fastq.")


@pytest.fixture
def swappable(import_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.fastq").write_bytes(b"SECRET OUTSIDE THE ROOT\n")
    (import_root / "run1").mkdir()
    (import_root / "run1" / "a.fastq").write_bytes(FASTQ)
    return import_root, outside


def _swap(kind, import_root, outside):
    run1 = import_root / "run1"
    target = run1 / "a.fastq"
    if kind == "folder_symlink":
        run1.rename(import_root / "run1_old")
        run1.symlink_to(outside)
    elif kind == "file_symlink":
        target.unlink()
        target.symlink_to(outside / "a.fastq")
    elif kind == "fifo":
        target.unlink()
        os.mkfifo(target)
    else:
        # Kept under another name so the new file cannot reuse its inode number.
        target.rename(run1 / "a.old")
        target.write_bytes(FASTQ)


@pytest.mark.parametrize("kind", ["folder_symlink", "file_symlink", "fifo", "replaced"])
def test_open_source_refuses_anything_swapped_in_after_validation(swappable, kind):
    import_root, outside = swappable
    root = get_root(0)
    selected = resolve_file(root, "run1/a.fastq")
    _swap(kind, import_root, outside)
    outcome = {}

    def attempt():
        try:
            with open_source(root, selected) as fh:
                outcome["read"] = fh.read(-1)
        except ImportPathError as exc:
            outcome["error"] = str(exc)

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), "opening the source blocked"
    assert outcome == {"error": "run1/a.fastq: changed after it was checked; not imported"}


def test_server_import_does_not_follow_a_folder_swapped_for_a_symlink(client, swappable, monkeypatch):
    import_root, outside = swappable
    real_open = server_import.open_source

    def swap_then_open(root, selected):
        _swap("folder_symlink", import_root, outside)
        return real_open(root, selected)

    monkeypatch.setattr(server_import, "open_source", swap_then_open)
    _, s = make_sample(client)
    job = run_import(client, s["id"], ["run1/a.fastq"])
    assert job["status"] == "failed"
    assert "changed after it was checked" in job["result_summary"]["rejected"][0]["reason"]
    assert client.get(f"{API}/samples/{s['id']}/files").json() == []


def test_names_that_are_not_utf8_are_hidden_and_refused(client, import_root):
    weird = import_root / "weird"
    weird.mkdir()
    (weird / "good.fastq").write_bytes(FASTQ)
    (weird / os.fsdecode(b"bad\xff.fastq")).write_bytes(FASTQ)
    r = browse(client, "weird")
    assert r.status_code == 200, r.text
    assert [e["name"] for e in r.json()["entries"]] == ["good.fastq"]
    assert r.json()["unsupported_names"] == 1
    assert browse(client).json()["unsupported_names"] == 0

    _, s = make_sample(client)
    r = client.post(
        f"{API}/samples/{s['id']}/files/import-server",
        content=b'{"root": 0, "paths": ["weird/bad\\udcff.fastq"]}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, r.text
    assert "valid string" in r.json()["detail"][0]["msg"]
    assert client.get(f"{API}/samples/{s['id']}/jobs").json() == []
    # Should such a name get past the request schema, the path check refuses it too.
    with pytest.raises(ImportPathError, match="UTF-8"):
        resolve_file(get_root(0), os.fsdecode(b"weird/bad\xff.fastq"))
