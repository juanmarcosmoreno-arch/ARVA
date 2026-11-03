"""Free space that Docker Desktop reports from another disk (app/services/locations.py, "Free space").

What was seen on a real Mac (MacBook Air M2, Docker Desktop, external APFS disk JM): with Docker Desktop's default File
sharing list, /proc/mounts inside the API container had "/run/host_mark/Volumes /data fakeowner rw,..." and `df -h
/data` gave the startup disk (229G size, 8.6G free) while scripts/start.sh measured JM on the Mac (931.5 GB, 57.3 GB
free); with /Volumes/JM shared and /Volumes removed, /data came from /run/host_mark/Volumes/JM with JM's 932G.

The /proc/mounts lines and launcher figures below are CONSTRUCTED from that; the folders are temporary folders here, and
nothing ran on a Mac.
"""
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.services import capacity, databases, locations, polishing, workflow_nodes
from app.tasks import common

API = "/api/v1"
GB = 1024**3
MEASURED = "2026-11-03T09:12:00Z"


@pytest.fixture(autouse=True)
def in_docker(monkeypatch, tmp_path):
    """ARVA in its container, with its own data and database folders and a /proc/mounts of the test's own."""
    monkeypatch.setattr(locations, "in_container", lambda: True)
    data, dbs = tmp_path / "data", tmp_path / "databases"
    data.mkdir()
    dbs.mkdir()
    monkeypatch.setattr(get_settings(), "storage_root", data)
    monkeypatch.setattr(get_settings(), "db_dir", dbs)
    monkeypatch.setattr(get_settings(), "import_roots", [])
    monkeypatch.setattr(get_settings(), "external_db_roots", [])
    mounts = tmp_path / "mounts"
    mounts.write_text("overlay / overlay rw,relatime 0 0\n")
    monkeypatch.setattr(locations, "PROC_MOUNTS", str(mounts))
    for name in [k for k in os.environ if k.startswith("ARVA_HOST_")]:
        monkeypatch.delenv(name)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_settings WHERE key = 'storage'"))
    return data


def _mount(tmp_path: Path, source: str, target: Path) -> None:
    with (tmp_path / "mounts").open("a") as fh:
        fh.write(f"{source.replace(' ', chr(92) + '040')} {str(target).replace(' ', chr(92) + '040')} fakeowner "
                 "rw,nosuid,nodev,relatime,fakeowner 0 0\n")


def _launcher(monkeypatch, name: str, host: str, total: int, free: int) -> None:
    monkeypatch.setenv(f"ARVA_HOST_{name}_DIR", host)
    monkeypatch.setenv(f"ARVA_HOST_{name}_TOTAL_BYTES", str(total))
    monkeypatch.setenv(f"ARVA_HOST_{name}_AVAIL_BYTES", str(free))
    monkeypatch.setenv("ARVA_HOST_SPACE_MEASURED_AT", MEASURED)


def _data(name: str = "data") -> locations.Location:
    return next(loc for loc in locations.locations() if loc.role == name)


def test_a_folder_shared_through_volumes_is_flagged_and_counted_with_the_launchers_figure(in_docker, tmp_path,
                                                                                          monkeypatch):
    real = shutil.disk_usage(in_docker)
    _mount(tmp_path, "/run/host_mark/Volumes", in_docker)
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", 931 * GB, 57 * GB)
    st = locations.status(_data())
    assert "space_misreported" in st.warnings and "low_space" not in st.warnings
    assert (st.free_bytes, st.total_bytes, st.space.source, st.space.reason) == (57 * GB, 931 * GB, "host_at_start",
                                                                                 "parent_share")
    assert (st.space.share, st.space.disk, st.space.container_total_bytes) == ("/Volumes", "/Volumes/JM", real.total)
    # Every free-space check counts the launcher's figure, not the other disk's.
    c = capacity.storage_capacity()
    assert (c.free_bytes, c.misreported) == (57 * GB, True)
    with pytest.raises(capacity.InsufficientStorageError, match="measured on this computer when ARVA started"):
        capacity.ensure_space(60 * GB)
    with pytest.raises(capacity.InsufficientStorageError):
        capacity.ensure_upload_space(40 * GB)
    (in_docker / "raw").mkdir()
    assert locations.free_space(in_docker / "raw").free_bytes == 57 * GB


def test_the_disk_shared_as_itself_is_trusted(in_docker, tmp_path, monkeypatch):
    real = shutil.disk_usage(in_docker)
    _mount(tmp_path, "/run/host_mark/Volumes/JM", in_docker)
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", real.total, real.free // 2)
    st = locations.status(_data())
    assert "space_misreported" not in st.warnings and st.space.source == "container"
    assert st.total_bytes == real.total and st.free_bytes != real.free // 2
    assert capacity.storage_capacity().misreported is False
    # A folder deeper on the disk counts as the disk's own share too.
    (tmp_path / "mounts").write_text("")
    _mount(tmp_path, "/run/host_mark/Volumes/JM/ARVA", in_docker)
    assert "space_misreported" not in locations.status(_data()).warnings


def test_a_size_that_is_not_the_disks_is_flagged_even_without_the_mount(in_docker, monkeypatch):
    real = shutil.disk_usage(in_docker)
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", real.total * 4 + 10 * GB, 30 * GB)
    st = locations.status(_data())
    assert st.space.reason == "size_differs" and st.free_bytes == 30 * GB
    # Within the tolerance (rounding, the filesystem's own reservation) it is the same disk.
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", real.total + 100 * 1024**2, 30 * GB)
    assert "space_misreported" not in locations.status(_data()).warnings


def test_without_a_launcher_figure_the_wrong_figure_is_kept_and_said_to_be_wrong(in_docker, tmp_path, monkeypatch):
    _mount(tmp_path, "/run/host_mark/Volumes", in_docker)
    monkeypatch.setenv("ARVA_HOST_DATA_DIR", "/Volumes/JM/ARVA/data")
    st = locations.status(_data())
    assert st.space.source == "container_misreported" and "space_misreported" in st.warnings
    assert "low_space" not in st.warnings
    assert st.free_bytes == shutil.disk_usage(in_docker).free


def test_linux_and_the_startup_disk_are_left_alone(in_docker, tmp_path, monkeypatch):
    # A plain bind mount on Linux, and ~/ARVA/import shared through /Users (correct for the startup disk).
    _mount(tmp_path, "/dev/nvme0n1p2", in_docker)
    st = locations.status(_data())
    assert st.space.source == "container" and "space_misreported" not in st.warnings
    (tmp_path / "mounts").write_text("")
    _mount(tmp_path, "/run/host_mark/Users", in_docker)
    monkeypatch.setenv("ARVA_HOST_DATA_DIR", "/Users/juan/ARVA/data")
    assert "space_misreported" not in locations.status(_data()).warnings


def test_paths_with_spaces_in_proc_mounts(in_docker, tmp_path, monkeypatch):
    folder = tmp_path / "data with space"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "storage_root", folder)
    _mount(tmp_path, "/run/host_mark/Volumes", folder)
    monkeypatch.setenv("ARVA_HOST_DATA_DIR", "/Volumes/My Disk/ARVA/data")
    st = locations.status(_data())
    assert st.space.reason == "parent_share" and st.space.disk == "/Volumes/My Disk"


def test_malformed_launcher_figures_are_ignored(in_docker, monkeypatch):
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", 10 * GB, 20 * GB)  # more free than total
    assert _data().host_total_bytes is None
    monkeypatch.setenv("ARVA_HOST_DATA_TOTAL_BYTES", "12; rm -rf /")
    assert _data().host_total_bytes is None
    monkeypatch.setenv("ARVA_HOST_SPACE_MEASURED_AT", "yesterday")
    assert locations.measured_at() is None


def test_a_job_and_a_database_download_count_the_launchers_figure(client, in_docker, tmp_path, monkeypatch):
    dbs = get_settings().db_dir
    _mount(tmp_path, "/run/host_mark/Volumes", dbs)
    _launcher(monkeypatch, "DATABASES", "/Volumes/JM/ARVA/databases", 931 * GB, 2 * GB)
    assert databases.free_bytes(dbs) == 2 * GB
    assert databases.writable_locations()[0]["space_misreported"] is True
    _mount(tmp_path, "/run/host_mark/Volumes", in_docker)
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", 931 * GB, GB // 2)

    job = SimpleNamespace(input_raw_file_ids=[])
    with pytest.raises(common.JobFailure, match=r"measured by scripts/start\.sh"):
        common._ensure_space(None, job, in_docker)


def test_the_storage_endpoint_and_the_launcher_summary_report_it(client, in_docker, tmp_path, monkeypatch, capsys):
    _mount(tmp_path, "/run/host_mark/Volumes", in_docker)
    _launcher(monkeypatch, "DATA", "/Volumes/JM/ARVA/data", 931 * GB, 57 * GB)
    body = client.get(f"{API}/system/storage").json()
    d = next(loc for loc in body["locations"] if loc["role"] == "data")
    assert d["warnings"] == ["space_misreported"] and d["space_source"] == "host_at_start"
    assert d["misreport"]["reason"] == "parent_share" and d["misreport"]["disk"] == "/Volumes/JM"
    assert d["free_bytes"] == 57 * GB and d["host_total_bytes"] == 931 * GB
    assert datetime.fromisoformat(d["host_measured_at"].replace("Z", "+00:00")) == datetime(2026, 11, 3, 9, 12,
                                                                                            tzinfo=UTC)
    assert body["free_bytes"] == 57 * GB
    assert locations._report("es") == 0
    out = capsys.readouterr().out
    assert "ATENCIÓN: Docker Desktop la comparte a través de /Volumes" in out
    assert "Cmd+Shift+G → /Volumes/JM → quitar /Volumes" in out


def test_the_default_import_folder_is_not_called_a_docker_volume(client, in_docker, monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "import_roots", [Path("/import")])
    assert locations._report("es") == 0
    assert "Carpeta de importación: la carpeta import/ junto a docker-compose.yml" in capsys.readouterr().out
    monkeypatch.setenv("ARVA_HOST_IMPORT_DIR", "/Users/juan/ARVA/import")
    assert locations._report("en") == 0
    assert "Import folder: /Users/juan/ARVA/import" in capsys.readouterr().out


# --- Pilon's heap on a small Docker Desktop VM ---------------------------------------------------------------------

def test_pilons_default_heap_follows_its_documentation_within_the_usable_memory():
    # Light profile, 3.8 GB VM (seen on the MacBook Air): 1 GB per job, at most 3 GB per tool.
    assert polishing.default_heap_gb(1, 3) == 3
    assert polishing.default_heap_gb(5, 8) == 8
    assert polishing.default_heap_gb(11, 16) == 11
    assert polishing.default_heap_gb(40, 64) == 16
    assert polishing.default_heap_gb(1, 1) == 1
    assert workflow_nodes.memory_gb_for("polishing", {"strategy": "pilon"}, 1, 3) == 3
    assert workflow_nodes.memory_gb_for("polishing", {"strategy": "pilon", "pilon": {"heap_gb": 2}}, 1, 3) == 2
    assert workflow_nodes.memory_gb_for("polishing", {"strategy": "racon"}, 1, 3) == 1
    assert workflow_nodes.memory_gb_for("spades", {}, 1, 3) == 1
