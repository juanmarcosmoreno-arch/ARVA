"""External storage: the locations, the data folder's storage marker, writes refused (503) and jobs failing while it is
missing or foreign, databases on a disk that is not connected, and the metadata backups.

Host paths such as /Volumes/JM/... are CONSTRUCTED strings standing for what scripts/start.sh would pass on a Mac;
the folders themselves are temporary folders here.
"""
import json
import re
import stat
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase
from app.services import annotation, locations
from app.tasks.databases import run_database_verify
from app.tasks.seqstats import run_sequence_stats_job

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "examples" / "synthetic" / "SYNTHETIC_illumina_R1_001.fastq.gz"
I18N = ROOT / "apps" / "web" / "src" / "i18n" / "index.ts"
SLOT = "2846640912"


@pytest.fixture(autouse=True)
def native(monkeypatch):
    """ARVA running natively (not in a container), whatever machine runs the tests: a folder's host path is then its
    own path unless the launcher gave one."""
    monkeypatch.setattr(locations, "in_container", lambda: False)


def _forget_recorded_id():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_settings WHERE key = 'storage'"))


@pytest.fixture
def data(client, tmp_path, monkeypatch):
    """A data folder of its own, so that marker changes leave the other tests' folder alone (the metadata forgets
    the ID the client's start-up recorded for that folder)."""
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "storage_root", folder)
    monkeypatch.setattr(get_settings(), "db_dir", tmp_path / "databases")
    (tmp_path / "databases").mkdir()
    _forget_recorded_id()
    return folder


def _project(client):
    return client.post(f"{API}/projects", json={"name": "Disk"})


def _marker_id(folder: Path) -> str:
    return json.loads((folder / locations.MARKER).read_text())["id"]


def test_the_first_write_marks_the_data_folder_and_records_its_id(client, data):
    assert client.get(f"{API}/system/storage").json()["marker"]["status"] == "new"
    assert _project(client).status_code == 201
    marker = _marker_id(data)
    assert re.fullmatch(r"[0-9a-f-]{36}", marker)
    body = client.get(f"{API}/system/storage").json()
    assert body["marker"] == {"status": "ok", "disk_id": marker, "recorded_id": marker, "backups": 0, "message": None,
                              "text": None}
    assert client.get("/health").json() == {"status": "ok", "version": client.get("/health").json()["version"],
                                            "storage": "ok"}


def test_a_missing_marker_refuses_every_write_with_a_coded_503(client, data, monkeypatch):
    monkeypatch.setenv("ARVA_HOST_DATA_DIR", "/Volumes/JM/ARVA/data")
    assert _project(client).status_code == 201
    (data / locations.MARKER).unlink()
    r = _project(client)
    assert r.status_code == 503
    assert r.json()["code"] == "storage_missing" and r.json()["params"] == {"path": "/Volumes/JM/ARVA/data"}
    assert "not connected" in r.json()["detail"]
    assert client.get(f"{API}/projects").status_code == 200
    assert client.get("/health").json()["status"] == "degraded"
    # Settings stay usable, and no marker was written in the meantime.
    assert client.put(f"{API}/system/performance", json={"profile": "light"}).status_code == 200
    assert not (data / locations.MARKER).exists()


def test_another_disk_in_its_place_is_refused(client, data):
    assert _project(client).status_code == 201
    expected = _marker_id(data)
    (data / locations.MARKER).write_text(json.dumps({"id": "00000000-0000-4000-8000-000000000000"}))
    r = _project(client)
    assert r.status_code == 503 and r.json()["code"] == "storage_mismatch"
    assert r.json()["params"]["recorded_id"] == expected
    (data / locations.MARKER).write_text("not json")
    assert _project(client).json()["code"] == "storage_invalid"


def test_a_data_folder_that_is_not_there_is_never_created(client, data, tmp_path):
    assert _project(client).status_code == 201
    data.rename(tmp_path / "unplugged")
    r = _project(client)
    assert r.status_code == 503 and r.json()["code"] == "storage_unavailable"
    storage = client.get(f"{API}/system/storage").json()
    assert storage["free_bytes"] == 0 and storage["marker"]["status"] == "unavailable"
    assert next(x for x in storage["locations"] if x["role"] == "data")["warnings"] == ["not_connected"]
    assert not data.exists()


def test_fresh_metadata_next_to_backups_asks_for_a_restore_or_an_adoption(client, data):
    assert _project(client).status_code == 201
    (data / "backups").mkdir(exist_ok=True)
    (data / "backups" / "arva-metadata-auto-20261028T020000Z.dump").write_bytes(b"PGDMP")
    _forget_recorded_id()
    r = _project(client)
    assert r.status_code == 503 and r.json()["code"] == "storage_restore_needed"
    assert r.json()["params"]["count"] == 1 and "scripts/restore.sh latest" in r.json()["detail"]
    assert client.post(f"{API}/system/storage/adopt", json={"confirm": False}).status_code == 400
    adopted = client.post(f"{API}/system/storage/adopt", json={"confirm": True})
    assert adopted.status_code == 200 and adopted.json()["marker"]["status"] == "ok"
    assert _project(client).status_code == 201
    assert client.post(f"{API}/system/storage/adopt", json={"confirm": True}).status_code == 409


def test_an_unrecorded_marker_without_backups_is_adopted(client, data):
    assert _project(client).status_code == 201
    marker = _marker_id(data)
    _forget_recorded_id()
    assert _project(client).status_code == 201
    assert client.get(f"{API}/system/storage").json()["marker"]["recorded_id"] == marker


@pytest.fixture
def uploaded(client, data):
    p = client.post(f"{API}/projects", json={"name": "Jobs"}).json()
    s = client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "S1"}).json()
    f = client.post(f"{API}/samples/{s['id']}/files", files=[("files", (R1.name, R1.read_bytes(), "x"))]).json()
    return s, f["files"][0]


def test_a_job_does_not_start_without_the_data_folder_and_writes_nothing(client, data, uploaded, held_queue):
    sample, f = uploaded
    (job,) = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                         json={"raw_file_ids": [f["id"]]}).json()
    (data / locations.MARKER).unlink()
    assert run_sequence_stats_job(job["id"]) == "failed"
    d = client.get(f"{API}/jobs/{job['id']}").json()
    assert d["error_detail"] == {"code": "storage_unavailable", "params": {"path": str(data)}}
    assert "nothing was written" in d["error_message"]
    assert not (data / "logs" / f"{job['id']}.log").exists()
    assert not (data / "results" / sample["project_id"]).exists()


def test_a_disk_lost_while_a_job_runs_is_named_as_the_reason(client, data, uploaded, tmp_path, monkeypatch):
    sample, f = uploaded
    exe = tmp_path / "seqkit"
    exe.write_text(f"#!{sys.executable}\nimport os, sys\nif sys.argv[1] == 'version':\n    print('seqkit v2.3.0')\n"
                   f"    sys.exit(0)\nos.remove({str(data / locations.MARKER)!r})\nsys.exit(3)\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ARVA_TOOL_SEQKIT", str(exe))
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    d = client.get(f"{API}/jobs/{j['id']}").json()
    assert d["status"] == "failed" and d["error_detail"] == {"code": "storage_lost", "params": {"path": str(data)}}
    assert "seqkit exited with status 3" in d["error_message"]
    assert not (data / "logs" / f"{j['id']}.log").exists()


# --- Locations and databases on other disks ----------------------------------------------------------------------

@pytest.fixture
def external(tmp_path, monkeypatch, data):
    """An added database folder as scripts/start.sh mounts it (/databases-external/<n>), with its host path."""
    root = tmp_path / "databases-external" / SLOT
    root.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "external_db_roots", [root])
    monkeypatch.setenv(f"ARVA_HOST_EXTERNAL_DB_{SLOT}", "/Volumes/JM/BioInf/bakta")
    monkeypatch.setenv(f"ARVA_HOST_EXTERNAL_DB_{SLOT}_FS", "exfat")
    return root


def test_the_overview_lists_each_location_with_its_host_path_space_and_warnings(client, data, external, monkeypatch):
    monkeypatch.setenv("ARVA_HOST_DATA_DIR", "/Volumes/JM/ARVA/data")
    monkeypatch.setenv("ARVA_HOST_DATA_FS", "apfs")
    monkeypatch.setenv("ARVA_HOST_DATABASES_DIR", "/Volumes/JM/ARVA/databases\x1b[2J")
    monkeypatch.setenv("ARVA_HOST_DATABASES_FS", "APFS; rm -rf /")
    body = client.get(f"{API}/system/storage").json()
    by_role = {loc["role"]: loc for loc in body["locations"]}
    assert body["data_host_path"] == "/Volumes/JM/ARVA/data"
    d = by_role["data"]
    assert (d["host_path"], d["container_path"], d["read_only"], d["filesystem"]) == (
        "/Volumes/JM/ARVA/data", str(data), False, "apfs")
    assert d["available"] and d["free_bytes"] > 0 and d["total_bytes"] >= d["free_bytes"]
    assert "backups" in d["stores"] and d["marker"] == "new"
    # Malformed launcher strings are dropped, never shown or used.
    assert by_role["databases"]["filesystem"] is None
    assert by_role["databases"]["host_path"] == str(data.parent / "databases")
    ext = by_role["external_databases"]
    assert (ext["host_path"], ext["read_only"], ext["slot"]) == ("/Volumes/JM/BioInf/bakta", True, SLOT)
    assert "fat_filesystem" in ext["warnings"]
    assert body["backups"]["interval_hours"] == 24 and body["backups"]["keep"] == 14


def test_a_database_folder_given_as_on_the_mac_is_registered_where_arva_sees_it(client, external):
    folder = external / "db"
    folder.mkdir()
    (folder / "version.json").write_text(json.dumps({"date": "2025-02-24", "major": 6, "minor": 0, "type": "light"}))
    from app.services.database_catalogue import BAKTA_REQUIRED_FILES

    for name in (*BAKTA_REQUIRED_FILES, "pscc.dmnd"):
        (folder / name).write_text("CONSTRUCTED test file, not a Bakta database file\n")
    r = client.post(f"{API}/databases/register", json={"path": "/Volumes/JM/BioInf/bakta/db"})
    assert r.status_code == 201, r.text
    assert r.json()["path"] == str(folder) and r.json()["host_path"] == "/Volumes/JM/BioInf/bakta/db"
    outside = client.post(f"{API}/databases/register", json={"path": "/Volumes/JM/Elsewhere/db"})
    assert outside.status_code == 400 and "/Volumes/JM/BioInf/bakta" in outside.json()["detail"]
    assert outside.json()["code"] == "outside_roots"


def _record(path: Path, origin=DatabaseOrigin.register, status=DatabaseStatus.registered, **kw) -> str:
    with SessionLocal() as db:
        r = ReferenceDatabase(key="bakta-light", name="Bakta database (light)", version="6.0", path=str(path),
                              status=status, origin=origin, checksum="sha256:" + "0" * 64, **kw)
        db.add(r)
        db.commit()
        return r.id


def test_databases_on_a_disk_that_is_not_connected_are_shown_unavailable_and_kept(client, external, tmp_path,
                                                                                  monkeypatch):
    disk = tmp_path / "second-disk"
    (disk / "databases").mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "db_dir", disk / "databases")
    registered = _record(external / "db")
    installed = _record(disk / "databases" / "bakta-light" / "6.0", origin=DatabaseOrigin.download,
                        status=DatabaseStatus.installed)
    external.rename(tmp_path / "unplugged")
    disk.rename(tmp_path / "unplugged-databases")
    rows = {r["id"]: r for r in client.get(f"{API}/databases").json()}
    assert rows[registered]["available"] is False and rows[registered]["unavailable_reason"] == "disk_not_connected"
    assert rows[registered]["host_path"] == "/Volumes/JM/BioInf/bakta/db"
    assert rows[installed]["unavailable_reason"] == "disk_not_connected"
    v = client.post(f"{API}/databases/{registered}/verify")
    assert v.status_code == 409 and v.json()["code"] == "database_unavailable"
    assert v.json()["params"]["reason"] == "disk_not_connected"
    gone = client.delete(f"{API}/databases/{installed}")
    assert gone.status_code == 409 and gone.json()["code"] == "database_unavailable"
    assert {r["id"] for r in client.get(f"{API}/databases").json()} == {registered, installed}
    with SessionLocal() as db, pytest.raises(annotation.DatabaseNotConnected):
        annotation.bakta_database(db, None)
    usage = client.get(f"{API}/databases/usage")
    assert usage.status_code == 503 and usage.json()["code"] == "databases_unavailable"
    assert not get_settings().db_dir.exists()


def test_the_reason_comes_from_the_most_specific_location(data, monkeypatch):
    inner = data / "databases"
    monkeypatch.setattr(get_settings(), "db_dir", inner)
    assert locations.unavailable_reason(str(inner / "bakta-light" / "6.0")) == "disk_not_connected"
    inner.mkdir()
    assert locations.unavailable_reason(str(inner / "bakta-light" / "6.0")) == "folder_missing"


def test_a_verification_that_finds_the_disk_gone_keeps_the_database_as_it_was(client, external, tmp_path):
    record = _record(external / "db", status=DatabaseStatus.verifying,
                     progress={"phase": "queued", "return_status": "registered"}, task_id="t")
    external.rename(tmp_path / "unplugged")
    assert run_database_verify(record) == "registered"
    r = client.get(f"{API}/databases/{record}").json()
    assert r["error_detail"] == {"code": "disk_not_connected", "params": {"folder": "/Volumes/JM/BioInf/bakta/db"}}


# --- Metadata backups -------------------------------------------------------------------------------------------

def test_backups_are_listed_and_one_can_be_asked_for(client, data):
    folder = data / "backups"
    folder.mkdir(exist_ok=True)
    for name in ("arva-metadata-auto-20261027T020000Z.dump", "arva-metadata-manual-20261028T153000Z.dump",
                 "arva-metadata-auto-20261399T020000Z.dump", "notes.txt"):
        (folder / name).write_bytes(b"PGDMP-constructed")
    (folder / ".last-result").write_text("result=ok\nkind=manual\nat=2026-10-28T15:30:02Z\n"
                                         "detail=arva-metadata-manual-20261028T153000Z.dump\n")
    b = client.get(f"{API}/system/storage").json()["backups"]
    assert [f["name"] for f in b["files"]] == ["arva-metadata-manual-20261028T153000Z.dump",
                                              "arva-metadata-auto-20261027T020000Z.dump"]
    assert b["last_result"]["result"] == "ok" and b["last_result"]["kind"] == "manual"
    assert b["pending_since"] is None
    asked = client.post(f"{API}/system/backups")
    assert asked.status_code == 202 and asked.json()["pending_since"] is not None
    assert json.loads((folder / ".request").read_text())["requested_at"]
    (data / locations.MARKER).unlink()
    refused = client.post(f"{API}/system/backups")
    assert refused.status_code == 503 and refused.json()["code"] == "storage_missing"


def test_the_launcher_summary_reads_in_spanish(client, data, capsys):
    assert locations._report("es") == 0
    out = capsys.readouterr().out
    assert out.startswith("Almacenamiento") and "Carpeta de datos" in out and "Copias de los metadatos: 0" in out


# --- Every code the interface shows has a text ------------------------------------------------------------------

@pytest.mark.skipif(not I18N.exists(), reason="the web sources are not next to the API")
def test_every_storage_code_has_a_text_in_both_languages():
    source = I18N.read_text(encoding="utf-8")
    split = source.index("const es:")
    for part in (source[:split], source[split:]):
        keys = set(re.findall(r'^  "([^"]+)":', part, re.M))
        wanted = {f"api.error.{c}" for c in locations.MESSAGES} | {
            "api.error.database_unavailable", "api.error.databases_unavailable", "job.error.storage_unavailable",
            "job.error.storage_lost", "database.error.databases_unavailable", "database.error.disk_not_connected",
            "annotation.planProblem.database_unavailable"}
        assert wanted - keys == set()
    en = source[:split]
    for code, message in locations.MESSAGES.items():
        assert f"  {json.dumps(f'api.error.{code}')}: {json.dumps(message, ensure_ascii=False)},\n" in en, code
