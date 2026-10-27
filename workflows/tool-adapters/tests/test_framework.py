"""Framework tests using small fake executables (no real tools needed)."""
import gzip
import os
import stat
import sys
from pathlib import Path

import pytest

from arva_tools.base import ToolStatus
from arva_tools.fastp import FastpAdapter
from arva_tools.runner import ToolExecutionError, ToolTimeoutError, run_command, tool_environment


def make_exe(dirpath: Path, name: str, body: str) -> Path:
    path = dirpath / name
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_arguments_are_passed_verbatim_without_a_shell(tmp_path):
    exe = make_exe(tmp_path, "echoargs", "import sys, json; print(json.dumps(sys.argv[1:]))")
    marker = tmp_path / "pwned"
    tricky = ["a b", "$(touch " + str(marker) + ")", "; rm -rf /", "`id`", "*"]
    out = tmp_path / "out.txt"
    run_command([str(exe), *tricky], cwd=tmp_path, stderr_path=tmp_path / "err.log", stdout_path=out)
    import json

    assert json.loads(out.read_text()) == tricky
    assert not marker.exists()


def test_stdout_can_be_gzip_streamed(tmp_path):
    exe = make_exe(tmp_path, "emit", "import sys\nfor i in range(50000): sys.stdout.write(f'line{i}\\n')")
    out = tmp_path / "out.txt.gz"
    run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "err.log", stdout_path=out)
    lines = gzip.decompress(out.read_bytes()).decode().splitlines()
    assert len(lines) == 50000 and lines[-1] == "line49999"


def test_failure_reports_exit_status_and_stderr(tmp_path):
    exe = make_exe(tmp_path, "boom", "import sys; sys.stderr.write('bad input on line 7'); sys.exit(3)")
    with pytest.raises(ToolExecutionError) as exc:
        run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "err.log")
    assert exc.value.returncode == 3
    assert "bad input on line 7" in exc.value.stderr_tail


def test_timeout_kills_process_group(tmp_path):
    exe = make_exe(tmp_path, "sleepy", "import time; time.sleep(30)")
    with pytest.raises(ToolTimeoutError):
        run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "err.log", timeout_seconds=1)


def test_secrets_are_not_passed_to_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVA_DATABASE_URL", "postgresql://u:secret@h/db")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("SOME_API_KEY", "y")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = tool_environment()
    assert "ARVA_DATABASE_URL" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert "SOME_API_KEY" not in env and env["LANG"] == "C.UTF-8"


def test_argv_must_be_strings(tmp_path):
    with pytest.raises(ValueError):
        run_command(["ls", 3], cwd=tmp_path, stderr_path=tmp_path / "e.log")  # type: ignore[list-item]


class _Fake(FastpAdapter):
    pass


def test_detection_states(tmp_path, monkeypatch):
    adapter = _Fake()
    monkeypatch.setenv("ARVA_TOOL_FASTP", str(tmp_path / "missing"))
    assert adapter.detect().status is ToolStatus.not_installed

    good = make_exe(tmp_path, "fastp_ok", "import sys; sys.stderr.write('fastp 0.23.4\\n')")
    monkeypatch.setenv("ARVA_TOOL_FASTP", str(good))
    d = adapter.detect()
    assert (d.status, d.version, d.version_validated) == (ToolStatus.available, "0.23.4", True)

    newer = make_exe(tmp_path, "fastp_new", "print('fastp 1.4.0')")
    monkeypatch.setenv("ARVA_TOOL_FASTP", str(newer))
    d = adapter.detect()
    assert d.status is ToolStatus.available and not d.version_validated
    assert "not been validated" in d.message

    old = make_exe(tmp_path, "fastp_old", "print('fastp 0.19.0')")
    monkeypatch.setenv("ARVA_TOOL_FASTP", str(old))
    assert adapter.detect().status is ToolStatus.incompatible

    garbage = make_exe(tmp_path, "fastp_bad", "print('hello')")
    monkeypatch.setenv("ARVA_TOOL_FASTP", str(garbage))
    assert adapter.detect().status is ToolStatus.failed


def test_tools_path_is_searched(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    make_exe(bindir, "fastp", "print('fastp 0.23.4')")
    monkeypatch.delenv("ARVA_TOOL_FASTP", raising=False)
    monkeypatch.setenv("ARVA_TOOLS_PATH", str(bindir))
    monkeypatch.setenv("PATH", os.defpath)
    assert _Fake().detect().path == str(bindir / "fastp")
