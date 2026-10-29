"""Framework tests using small fake executables (no real tools needed)."""
import gzip
import os
import stat
import sys
from pathlib import Path

import pytest

from arva_tools.base import ToolStatus
from arva_tools.fastp import FastpAdapter
from arva_tools.runner import (
    SIGKILL_STATUSES,
    ToolExecutionError,
    ToolTimeoutError,
    nice_prefix,
    run_command,
    tool_environment,
)


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


@pytest.mark.skipif(not nice_prefix(5), reason="the nice executable is not installed")
def test_nice_lowers_the_tools_priority_and_errors_name_the_tool(tmp_path):
    exe = make_exe(tmp_path, "prio", "import os, sys; print(os.nice(0)); sys.exit(int(sys.argv[1]))")
    out = tmp_path / "out.txt"
    result = run_command([str(exe), "0"], cwd=tmp_path, stderr_path=tmp_path / "err.log", stdout_path=out, nice=7)
    assert int(out.read_text()) == os.nice(0) + 7
    assert result.argv == [str(exe), "0"]
    with pytest.raises(ToolExecutionError, match=r"^prio exited with status 4") as exc:
        run_command([str(exe), "4"], cwd=tmp_path, stderr_path=tmp_path / "err.log", nice=7)
    assert exc.value.returncode == 4
    with pytest.raises(ToolExecutionError, match="could not start"):
        run_command([str(tmp_path / "missing")], cwd=tmp_path, stderr_path=tmp_path / "err.log", nice=7)
    assert nice_prefix(0) == [] and nice_prefix(20) == [] and nice_prefix(10)[1:] == ["-n", "10"]


def test_a_tool_killed_by_sigkill_reports_its_status(tmp_path):
    exe = make_exe(tmp_path, "oom", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
    with pytest.raises(ToolExecutionError) as exc:
        run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "err.log", nice=3)
    assert exc.value.returncode in SIGKILL_STATUSES and exc.value.returncode == -9


def test_timeout_kills_process_group(tmp_path):
    exe = make_exe(tmp_path, "sleepy", "import time; time.sleep(30)")
    with pytest.raises(ToolTimeoutError):
        run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "err.log", timeout_seconds=1)


def test_monitor_runs_while_the_tool_runs_and_can_stop_it(tmp_path):
    exe = make_exe(tmp_path, "slow", "import time; time.sleep(0.6)")
    calls = []
    run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "err.log", monitor=lambda: calls.append(1),
                monitor_seconds=0.1)
    assert len(calls) >= 3

    marker = tmp_path / "still-running"
    sleeper = make_exe(tmp_path, "sleeper", f"import time, pathlib; time.sleep(0.8); pathlib.Path({str(marker)!r}).touch()")

    def stop():
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        run_command([str(sleeper)], cwd=tmp_path, stderr_path=tmp_path / "err2.log", monitor=stop, monitor_seconds=0.1)
    import time

    time.sleep(1.2)
    assert not marker.exists()


def test_monitor_with_gzip_stdout_and_stopping_the_whole_group(tmp_path):
    """Filtlong-like: stdout is gzip-streamed and nothing is written for a while (it scores the reads first). The
    monitor still runs, and when it raises, the tool and the child it started are killed."""
    emit = make_exe(tmp_path, "emit", "import sys, time\ntime.sleep(0.4)\nfor i in range(20000): print(f'r{i}')")
    calls = []
    out = tmp_path / "o.txt.gz"
    run_command([str(emit)], cwd=tmp_path, stderr_path=tmp_path / "e.log", stdout_path=out,
                monitor=lambda: calls.append(1), monitor_seconds=0.1)
    assert calls and gzip.decompress(out.read_bytes()).decode().splitlines()[-1] == "r19999"

    pids = tmp_path / "pids"
    quiet = make_exe(tmp_path, "quiet", "import os, subprocess, sys, time, pathlib\n"
                     "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                     f"pathlib.Path({str(pids)!r}).write_text(f'{{os.getpid()}} {{child.pid}}')\ntime.sleep(60)")

    def stop():
        if pids.exists():
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_command([str(quiet)], cwd=tmp_path, stderr_path=tmp_path / "q.log", stdout_path=tmp_path / "q.gz",
                    monitor=stop, monitor_seconds=0.05)
    import time

    for pid in map(int, pids.read_text().split()):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"process {pid} survived")


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


def test_tools_run_with_an_empty_temporary_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MULTIQC_TITLE", "injected")
    exe = make_exe(tmp_path, "envdump", "import os, json\n"
                   "print(json.dumps({k: os.environ.get(k) for k in "
                   "('HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'MULTIQC_TITLE', 'EXTRA')}))\n"
                   "print(json.dumps(os.listdir(os.environ['HOME'])))\n"
                   "open(os.path.join(os.environ['HOME'], 'cache'), 'w').write('x')")
    out = tmp_path / "out.txt"
    run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "e.log", stdout_path=out, extra_env={"EXTRA": "1"})
    import json

    env_line, listing = out.read_text().splitlines()
    env = json.loads(env_line)
    home = env["HOME"]
    assert home != str(tmp_path) and Path(home).name.startswith("arva-tool-home-")
    assert {env[k] for k in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")} == {home}
    assert env["MULTIQC_TITLE"] is None and env["EXTRA"] == "1"
    assert json.loads(listing) == [] and not Path(home).exists()


def test_old_multiqc_is_incompatible_with_reasons(tmp_path, monkeypatch):
    from arva_tools.multiqc import MultiqcAdapter

    old = make_exe(tmp_path, "mqc_old", "print('multiqc, version 1.18')")
    monkeypatch.setenv("ARVA_TOOL_MULTIQC", str(old))
    d = MultiqcAdapter().detect()
    assert (d.status, d.version, d.reason) == (ToolStatus.incompatible, "1.18", "multiqc_too_old")
    assert "--no-version-check" in d.message and "plain HTTP" in d.message and "SeqKit" in d.message

    good = make_exe(tmp_path, "mqc_ok", "print('multiqc, version 1.35')")
    monkeypatch.setenv("ARVA_TOOL_MULTIQC", str(good))
    d = MultiqcAdapter().detect()
    assert (d.status, d.version, d.version_validated) == (ToolStatus.available, "1.35", True)


def test_a_supplied_home_is_used_and_kept(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    exe = make_exe(tmp_path, "writer", "import os\nopen(os.path.join(os.environ['XDG_DATA_HOME'], 'trace'), 'w').write('x')\n"
                   "print(os.environ['HOME'])")
    out = tmp_path / "out.txt"
    run_command([str(exe)], cwd=tmp_path, stderr_path=tmp_path / "e.log", stdout_path=out, home=home)
    assert out.read_text().strip() == str(home) and (home / "trace").is_file()


def fake_nanomath(path: Path, bundled: bool) -> Path:
    (path / "nanomath").mkdir(parents=True)
    (path / "nanomath" / "__init__.py").write_text("def ave_qual_floats(q): return 0\n" if bundled else "def ave_qual(q): return 0\n")
    return path


def test_nanoplot_detection(tmp_path, monkeypatch):
    from arva_tools.nanoplot import NanoplotAdapter

    monkeypatch.setenv("PYTHONPATH", str(fake_nanomath(tmp_path / "bundled", bundled=True)))
    monkeypatch.setenv("ARVA_TOOL_NANOPLOT", str(make_exe(tmp_path, "np_ok", "print('NanoPlot 1.48.0')")))
    d = NanoplotAdapter().detect()
    assert (d.status, d.version, d.version_validated, d.message, d.reason) == (ToolStatus.available, "1.48.0", True, "", None)
    monkeypatch.setenv("ARVA_TOOL_NANOPLOT", str(make_exe(tmp_path, "np_old", "print('NanoPlot 1.42.0')")))
    assert NanoplotAdapter().detect().status is ToolStatus.incompatible


def test_nanoplot_with_a_replaced_nanomath_is_rejected(tmp_path, monkeypatch):
    from arva_tools.nanoplot import NanoplotAdapter

    # A stock nanomath (e.g. pulled in by another package) hides the copy NanoPlot ships; --version is unchanged.
    monkeypatch.setenv("PYTHONPATH", str(fake_nanomath(tmp_path / "stock", bundled=False)))
    monkeypatch.setenv("ARVA_TOOL_NANOPLOT", str(make_exe(tmp_path, "np_ok", "print('NanoPlot 1.48.0')")))
    d = NanoplotAdapter().detect()
    assert (d.status, d.version, d.reason) == (ToolStatus.failed, "1.48.0", "nanomath_replaced")
    assert "without ave_qual_floats" in d.message and str(tmp_path / "stock" / "nanomath") in d.message
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "empty"))
    d = NanoplotAdapter().detect()
    assert (d.status, d.reason) == (ToolStatus.failed, "nanomath_missing") and "could not import nanomath" in d.message

    wrapper = tmp_path / "np_wrapper"
    wrapper.write_text("#!/bin/sh\necho 'NanoPlot 1.48.0'\n")
    wrapper.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_NANOPLOT", str(wrapper))
    d = NanoplotAdapter().detect()
    assert (d.status, d.version_validated, d.reason) == (ToolStatus.available, False, "nanomath_unchecked")
    assert "not a Python script" in d.message


def test_python_of_entry_points(tmp_path):
    from arva_tools.nanoplot import python_of

    scripts = {
        "venv": "#!/opt/np/bin/python3\nimport sys\n",
        "env": "#!/usr/bin/env python3\n",
        "flag": "#!/usr/bin/python3 -E\n",
        "pip_long_path": "#!/bin/sh\n'''exec' \"/a b/bin/python3\" \"$0\" \"$@\"\n' '''\n",
        "shell": "#!/bin/sh\nexec /opt/np/bin/NanoPlot \"$@\"\n",
        "binary": "\x7fELF",
    }
    for name, text in scripts.items():
        (tmp_path / name).write_text(text)
    assert {name: python_of(str(tmp_path / name)) for name in scripts} == {
        "venv": ["/opt/np/bin/python3"], "env": ["/usr/bin/env", "python3"], "flag": ["/usr/bin/python3", "-E"],
        "pip_long_path": ["/a b/bin/python3"], "shell": None, "binary": None,
    }
