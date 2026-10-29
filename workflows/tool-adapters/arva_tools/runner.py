"""Safe execution of external tools.

* Commands are argument vectors executed without a shell.
* The child environment excludes ARVA configuration and anything that looks
  like a credential, so tools cannot read database passwords or API keys.
* HOME and the XDG base directories point at a fresh, empty directory that is
  removed afterwards (or at an empty directory the caller supplies and can
  inspect), so no user configuration applies and nothing is cached in the
  user's home.
* stdout/stderr go to files, never into memory; stdout can be gzip-streamed.
* Each tool runs in its own process group, so a timeout, or an exception raised by the monitor callback (ARVA's
  cancellation), kills the tool with all its children.
* With `nice`, the tool starts through the `nice` executable (POSIX nice(1): `nice -n N utility`, whose exit status
  is the utility's), resolved by path, so it runs at a lower CPU priority than ARVA's own processes.
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

_SECRET = re.compile(r"PASSWORD|SECRET|TOKEN|CREDENTIAL|API_?KEY|PRIVATE", re.IGNORECASE)
# MultiQC reads any MULTIQC_<KEY> variable as configuration. Java reads options (heap size, system properties) from
# the three Java variables, which would override a tool's recorded settings, e.g. Pilon's -Xmx.
_TOOL_CONFIG_PREFIXES = ("ARVA_", "DATABASE", "MULTIQC_", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS")
HOME_VARIABLES = ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")
CHUNK = 1 << 20
# Exit statuses of a process killed by SIGKILL: Popen's -9, or 137 (128 + 9) from a wrapper script whose child was.
SIGKILL_STATUSES = (-signal.SIGKILL, 128 + signal.SIGKILL)


class ToolExecutionError(RuntimeError):
    """`code` and `params` name the failure for the interface (job.error.<code>); the message stays English."""

    def __init__(self, message: str, returncode: int | None = None, stderr_tail: str = "", code: str | None = None,
                 params: dict[str, str | int] | None = None):
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        self.code = code
        self.params = params or {}
        super().__init__(message)


class ToolTimeoutError(ToolExecutionError):
    pass


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    duration_seconds: float
    stderr_path: Path
    stdout_path: Path | None


def tool_environment(home: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_TOOL_CONFIG_PREFIXES) and not _SECRET.search(k)}
    if home is not None:
        env.update(dict.fromkeys(HOME_VARIABLES, str(home)))
    return env


def nice_prefix(nice: int) -> list[str]:
    """The argument vector that lowers a tool's CPU priority by `nice` (1-19); empty for 0, or without `nice`."""
    if not 0 < nice < 20:
        return []
    exe = shutil.which("nice")
    return [exe, "-n", str(nice)] if exe else []


@contextmanager
def isolated_home() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="arva-tool-home-") as home:
        yield Path(home)


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - limit))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    stderr_path: Path,
    stdout_path: Path | None = None,
    timeout_seconds: float = 24 * 3600,
    extra_env: Mapping[str, str] | None = None,
    home: Path | None = None,
    monitor: Callable[[], None] | None = None,
    monitor_seconds: float = 5.0,
    nice: int = 0,
) -> RunResult:
    """Run `argv` and wait. stdout goes to `stdout_path` (gzip if it ends in .gz)
    or is appended to the stderr log. `home` replaces the temporary HOME. While the tool runs, `monitor` is
    called every `monitor_seconds`; if it raises, the tool's process group is killed and the exception propagates.
    `nice` > 0 starts the tool through `nice -n <nice>` (see nice_prefix). Raises ToolExecutionError on failure."""
    with nullcontext(home) if home is not None else isolated_home() as tool_home:
        return _run(argv, cwd, stderr_path, stdout_path, timeout_seconds,
                    {**tool_environment(tool_home), **(extra_env or {})}, monitor, monitor_seconds, nice)


def _run(
    argv: Sequence[str],
    cwd: Path,
    stderr_path: Path,
    stdout_path: Path | None,
    timeout_seconds: float,
    env: dict[str, str],
    monitor: Callable[[], None] | None = None,
    monitor_seconds: float = 5.0,
    nice: int = 0,
) -> RunResult:
    if not argv or not all(isinstance(a, str | os.PathLike) for a in argv):
        raise ValueError("argv must be a non-empty sequence of strings or paths")
    argv = [os.fspath(a) for a in argv]
    prefix = nice_prefix(nice)
    # Through nice, a missing tool would be nice's exit status 127 rather than an error starting it.
    if prefix and shutil.which(argv[0], path=env.get("PATH")) is None:
        raise ToolExecutionError(f"could not start {argv[0]}: not found or not executable",
                                 code="tool_not_executable", params={"tool": Path(argv[0]).name})
    cwd.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    gz_out = stdout_path is not None and stdout_path.suffix == ".gz"
    start = time.monotonic()

    with open(stderr_path, "ab") as err:
        out_handle = None
        if stdout_path is not None and not gz_out:
            out_handle = open(stdout_path, "wb")
        try:
            proc = subprocess.Popen(
                [*prefix, *argv],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if gz_out else (out_handle or err),
                stderr=err,
                env=env,
                start_new_session=True,
                shell=False,
            )
        except OSError as exc:
            if out_handle:
                out_handle.close()
            raise ToolExecutionError(f"could not start {argv[0]}: {exc}", code="tool_not_started",
                                     params={"tool": Path(argv[0]).name, "detail": str(exc)}) from exc

        pump = _GzipPump(proc, stdout_path) if gz_out and stdout_path is not None else None
        try:
            _wait(proc, start + timeout_seconds, monitor, monitor_seconds)
            if pump is not None:
                pump.finish()
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            if pump is not None:
                pump.join()
            raise ToolTimeoutError(
                f"{argv[0]} exceeded the time limit of {timeout_seconds:.0f} s", None, _tail(stderr_path),
                "tool_timeout", {"tool": Path(argv[0]).name, "seconds": round(timeout_seconds)},
            ) from None
        except BaseException:
            _kill_group(proc)
            if pump is not None:
                pump.join()
            raise
        finally:
            if out_handle:
                out_handle.close()

    duration = time.monotonic() - start
    if proc.returncode != 0:
        raise ToolExecutionError(
            f"{Path(argv[0]).name} exited with status {proc.returncode}",
            proc.returncode,
            _tail(stderr_path),
            "tool_exit",
            {"tool": Path(argv[0]).name, "status": proc.returncode},
        )
    return RunResult(argv, proc.returncode, duration, stderr_path, stdout_path)


def _wait(proc: subprocess.Popen, deadline: float, monitor: Callable[[], None] | None, monitor_seconds: float) -> None:
    if monitor is None:
        proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        return
    while True:
        try:
            proc.wait(timeout=max(0.0, min(monitor_seconds, deadline - time.monotonic())))
            return
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise
            monitor()


class _GzipPump(threading.Thread):
    """Compresses the tool's stdout in a thread, so the main thread can wait with the monitor. A write error
    (e.g. a full disk) stops the tool, which would otherwise block on a full pipe."""

    def __init__(self, proc: subprocess.Popen, path: Path):
        super().__init__(daemon=True)
        self.proc, self.path = proc, path
        self.error: BaseException | None = None
        self.start()

    def run(self) -> None:
        try:
            with gzip.open(self.path, "wb", compresslevel=6) as gz:
                assert self.proc.stdout is not None
                while chunk := self.proc.stdout.read(CHUNK):
                    gz.write(chunk)
        except BaseException as exc:
            self.error = exc
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        finally:
            if self.proc.stdout is not None:
                self.proc.stdout.close()

    def finish(self) -> None:
        self.join()
        if self.error is not None:
            raise self.error


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()
