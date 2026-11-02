"""The test storage folder is removed however the test process ends: at exit, on SIGTERM or SIGHUP (turned into a
clean stop), and after a SIGKILL by the next run's sweep."""
import os
import signal
import subprocess
import time

import conftest
import pytest


def test_storage_is_named_after_this_process():
    assert os.path.basename(conftest._STORAGE).startswith(f"arva-test-storage-{os.getpid()}-")


def test_sweep_removes_folders_of_dead_processes_only(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest.tempfile, "gettempdir", lambda: str(tmp_path))
    dead = subprocess.Popen(["true"])
    dead.wait()
    gone = tmp_path / f"arva-test-storage-{dead.pid}-abc"
    (gone / "results" / "job").mkdir(parents=True)
    (gone / "results" / "job" / "raw.fastq").write_text("@r\nA\n+\nI\n")
    os.chmod(gone / "results" / "job" / "raw.fastq", 0o444)
    os.chmod(gone / "results" / "job", 0o555)
    alive = tmp_path / f"arva-test-storage-{os.getpid()}-def"
    alive.mkdir()
    legacy_old = tmp_path / "arva-test-storage-x1y2z3"
    legacy_old.mkdir()
    os.utime(legacy_old, (time.time() - 2 * 86400,) * 2)
    legacy_new = tmp_path / "arva-test-storage-q9w8e7"
    legacy_new.mkdir()

    conftest._sweep_stale()

    assert not gone.exists() and not legacy_old.exists()
    assert alive.is_dir() and legacy_new.is_dir()


def test_termination_signals_stop_pytest_cleanly():
    for sig in (signal.SIGTERM, signal.SIGHUP):
        assert signal.getsignal(sig) is conftest._interrupted
        with pytest.raises(KeyboardInterrupt):
            conftest._interrupted(sig, None)
