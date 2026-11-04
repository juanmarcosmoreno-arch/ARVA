"""Tool detection records why a version check failed, and checks once more with a longer timeout first.

Seen on a Mac (registro de prueba, item 31): right after Flye ran out of memory, the start-up check marked Medaka
"failed" with no reason; minutes before and after it was available. Medaka imports PyTorch, slow under Rosetta with
the memory taken. These tests use fake executables that are slow, or fail, only on their first call.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from arva_tools import ToolStatus
from arva_tools.medaka import MedakaAdapter


def fake(tmp_path: Path, body: str) -> Path:
    """A stand-in `medaka` whose first call behaves as `body` says, counted in calls.txt next to it."""
    path = tmp_path / "medaka"
    counter = tmp_path / "calls.txt"
    path.write_text(f"""#!{sys.executable}
import sys, time
from pathlib import Path
counter = Path({str(counter)!r})
calls = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(calls))
{body}
""")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def adapter(monkeypatch):
    a = MedakaAdapter()
    # Short timeouts for the test: the first check gives up after 0.5 s, the retry waits up to 5 s.
    monkeypatch.setattr(a, "version_timeout", 0.5)
    monkeypatch.setattr(a, "version_retry_timeout", 5.0)
    return a


def calls(tmp_path: Path) -> int:
    return int((tmp_path / "calls.txt").read_text())


def test_a_slow_first_check_is_retried_with_a_longer_timeout(tmp_path, monkeypatch, adapter):
    exe = fake(tmp_path, "time.sleep(1.5 if calls == 1 else 0.6)\nprint('medaka 2.1.1')")
    monkeypatch.setenv("ARVA_TOOL_MEDAKA", str(exe))
    d = adapter.detect()
    assert d.status is ToolStatus.available and d.version == "2.1.1" and calls(tmp_path) == 2


def test_a_check_that_keeps_timing_out_says_so(tmp_path, monkeypatch, adapter):
    monkeypatch.setattr(adapter, "version_retry_timeout", 1.0)
    exe = fake(tmp_path, "time.sleep(3)\nprint('medaka 2.1.1')")
    monkeypatch.setenv("ARVA_TOOL_MEDAKA", str(exe))
    d = adapter.detect()
    assert d.status is ToolStatus.failed and d.reason == "version_timeout"
    assert d.reason_params == {"seconds": "1", "first": "0.5"} and calls(tmp_path) == 2
    assert "did not answer within 1 s (after a first attempt of 0.5 s)" in d.message


def test_a_failed_exit_is_retried_and_its_status_and_output_recorded(tmp_path, monkeypatch, adapter):
    once = fake(tmp_path, "if calls == 1:\n    sys.stderr.write('Killed\\n'); sys.exit(137)\nprint('medaka 2.1.1')")
    monkeypatch.setenv("ARVA_TOOL_MEDAKA", str(once))
    assert adapter.detect().status is ToolStatus.available and calls(tmp_path) == 2

    (tmp_path / "calls.txt").unlink()
    always = fake(tmp_path, "sys.stderr.write('ImportError: libtorch_cpu.so: cannot open shared object file\\n')\n"
                            "sys.exit(1)")
    monkeypatch.setenv("ARVA_TOOL_MEDAKA", str(always))
    d = adapter.detect()
    assert d.status is ToolStatus.failed and d.reason == "version_exit" and calls(tmp_path) == 2
    assert d.reason_params == {"status": "1", "output": "ImportError: libtorch_cpu.so: cannot open shared object file"}
    assert d.message.startswith("medaka --version exited with status 1: ImportError")


def test_no_version_in_the_output_keeps_its_reason_with_the_output(tmp_path, monkeypatch, adapter):
    exe = fake(tmp_path, "print('something else')")
    monkeypatch.setenv("ARVA_TOOL_MEDAKA", str(exe))
    d = adapter.detect()
    assert d.status is ToolStatus.failed and d.reason == "no_version" and d.reason_params == {"output": "something else"}


def test_an_executable_that_cannot_start_has_a_reason(tmp_path, monkeypatch, adapter):
    broken = tmp_path / "medaka"
    broken.write_text("#!/nonexistent/interpreter\n")
    broken.chmod(broken.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ARVA_TOOL_MEDAKA", str(broken))
    d = adapter.detect()
    assert d.status is ToolStatus.failed and d.reason == "not_runnable" and d.reason_params["detail"]
