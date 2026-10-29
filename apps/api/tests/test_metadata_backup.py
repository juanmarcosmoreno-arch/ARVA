"""scripts/metadata-backup.sh with the real pg_dump, pg_restore, dropdb, createdb and psql against a scratch PostgreSQL
database (the backup service runs the same script in the postgres image, whose tools match the server's version)."""
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.session import engine
from app.services import locations

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "metadata-backup.sh"
pytestmark = pytest.mark.skipif(not all(shutil.which(t) for t in ("pg_dump", "pg_restore", "dropdb", "createdb", "psql")),
                                reason="the PostgreSQL client programs are not installed")


@pytest.fixture
def scratch(tmp_path):
    name = f"arva_backup_scratch_{uuid.uuid4().hex[:8]}"
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(get_settings().database_url).set(database=name)
    data = tmp_path / "data"
    data.mkdir()
    (data / locations.MARKER).write_text('{"id": "00000000-0000-4000-8000-000000000001"}\n')
    env = {"PATH": os.environ["PATH"], "PGHOST": url.host or "localhost", "PGPORT": str(url.port or 5432),
           "PGUSER": url.username or "", "PGPASSWORD": url.password or "", "PGDATABASE": name,
           "ARVA_BACKUP_DIR": str(data / "backups")}
    db = create_engine(url.render_as_string(hide_password=False))
    yield db, env, data
    db.dispose()
    with admin.connect() as conn:
        for n in (name, f"{name}_restoring"):
            conn.execute(text(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)'))


def _run(env, *args, **kw):
    return subprocess.run(["sh", str(SCRIPT), *args], env={**env, **kw}, capture_output=True, text=True, timeout=120)


def _rows(db) -> list[int]:
    with db.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT x FROM t ORDER BY x"))]


def test_a_backup_restores_the_metadata_it_was_taken_of(scratch):
    db, env, data = scratch
    with db.begin() as conn:
        conn.execute(text("CREATE TABLE t (x int)"))
        conn.execute(text("INSERT INTO t VALUES (1), (2)"))
    made = _run(env, "backup", "manual")
    assert made.returncode == 0, made.stderr
    name = made.stdout.strip()
    assert name.startswith("arva-metadata-manual-") and (data / "backups" / name).stat().st_size > 0
    assert "result=ok" in (data / "backups" / ".last-result").read_text()
    assert [f["name"] for f in locations.backup_files(data)] == [name]
    with db.begin() as conn:
        conn.execute(text("INSERT INTO t VALUES (3)"))
    db.dispose()
    restored = _run(env, "restore", name)
    assert restored.returncode == 0, restored.stderr
    assert _rows(db) == [1, 2]
    # What was there before the restore was backed up first, and can be brought back.
    (before,) = [f["name"] for f in locations.backup_files(data) if f["kind"] == "pre-restore"]
    db.dispose()
    assert _run(env, "restore", before).returncode == 0
    assert _rows(db) == [1, 2, 3]
    assert _run(env, "list").stdout.split()[0].startswith("arva-metadata-pre-restore-")


def test_a_damaged_archive_or_a_path_changes_nothing(scratch):
    db, env, data = scratch
    with db.begin() as conn:
        conn.execute(text("CREATE TABLE t (x int)"))
        conn.execute(text("INSERT INTO t VALUES (7)"))
    (data / "backups").mkdir()
    (data / "backups" / "arva-metadata-manual-20261028T153000Z.dump").write_bytes(b"PGDMP but CONSTRUCTED garbage")
    bad = _run(env, "restore", "arva-metadata-manual-20261028T153000Z.dump")
    assert bad.returncode == 1 and "nothing was changed" in bad.stderr
    assert _run(env, "restore", "../../etc/passwd").returncode == 1
    db.dispose()
    assert _rows(db) == [7] and not list((data / "backups").glob("*pre-restore*"))


def test_nothing_is_written_while_the_disk_is_not_connected(scratch):
    _db, env, data = scratch
    (data / locations.MARKER).unlink()
    made = _run(env, "backup", "auto")
    assert made.returncode == 1 and "not connected" in made.stderr and not (data / "backups").exists()


def test_each_kind_keeps_its_newest_backups(scratch):
    _db, env, data = scratch
    folder = data / "backups"
    folder.mkdir()
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        (folder / f"arva-metadata-auto-{stamp}.dump").write_bytes(b"old")
    (folder / "arva-metadata-manual-20250101T000000Z.dump").write_bytes(b"kept")
    made = _run(env, "backup", "auto", ARVA_BACKUP_KEEP="2")
    assert made.returncode == 0, made.stderr
    autos = sorted(p.name for p in folder.glob("arva-metadata-auto-*"))
    assert autos == ["arva-metadata-auto-20260103T000000Z.dump", made.stdout.strip()]
    assert (folder / "arva-metadata-manual-20250101T000000Z.dump").exists()


def test_the_service_makes_the_backups_asked_for_in_arva(scratch):
    _db, env, data = scratch
    (data / "backups").mkdir()
    (data / "backups" / ".request").write_text('{"requested_at": "2026-10-29T10:00:00+00:00"}\n')
    loop = subprocess.Popen(["sh", str(SCRIPT), "loop"], env={**env, "ARVA_BACKUP_POLL_SECONDS": "1"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (
                list((data / "backups").glob("arva-metadata-manual-*")) and list((data / "backups").glob("arva-metadata-auto-*"))):
            time.sleep(0.2)
    finally:
        loop.send_signal(signal.SIGTERM)
        loop.wait(timeout=10)
    assert list((data / "backups").glob("arva-metadata-manual-*")), loop.stderr.read()
    assert list((data / "backups").glob("arva-metadata-auto-*"))
    assert not (data / "backups" / ".request").exists()
