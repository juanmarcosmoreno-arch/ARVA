"""Safe execution of external tools.

* Commands are argument vectors executed without a shell.
* The child environment excludes ARVA configuration and anything that looks
  like a credential, so tools cannot read database passwords or API keys.
* stdout/stderr go to files, never into memory; stdout can be gzip-streamed.
* Each tool runs in its own process group so a timeout kills all children.
"""
from __future__ import annotations

import gzip
import os
import re
import signal
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SECRET = re.compile(r"PASSWORD|SECRET|TOKEN|CREDENTIAL|API_?KEY|PRIVATE", re.IGNORECASE)
CHUNK = 1 << 20


class ToolExecutionError(RuntimeError):
    def __init__(self, message: str, returncode: int | None = None, stderr_tail: str = ""):
        self.returncode = returncode
        self.stderr_tail = stderr_tail
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


def tool_environment() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("ARVA_") and not _SECRET.search(k) and not k.startswith("DATABASE")
    }


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
) -> RunResult:
    """Run `argv` and wait. stdout goes to `stdout_path` (gzip if it ends in .gz)
    or is appended to the stderr log. Raises ToolExecutionError on failure."""
    if not argv or not all(isinstance(a, str | os.PathLike) for a in argv):
        raise ValueError("argv must be a non-empty sequence of strings or paths")
    argv = [os.fspath(a) for a in argv]
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
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if gz_out else (out_handle or err),
                stderr=err,
                env=tool_environment(),
                start_new_session=True,
                shell=False,
            )
        except OSError as exc:
            if out_handle:
                out_handle.close()
            raise ToolExecutionError(f"could not start {argv[0]}: {exc}") from exc

        try:
            if gz_out:
                deadline = start + timeout_seconds
                with gzip.open(stdout_path, "wb", compresslevel=6) as gz:
                    assert proc.stdout is not None
                    while chunk := proc.stdout.read(CHUNK):
                        gz.write(chunk)
                        if time.monotonic() > deadline:
                            raise subprocess.TimeoutExpired(argv, timeout_seconds)
                proc.wait(timeout=max(1.0, deadline - time.monotonic()))
            else:
                proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise ToolTimeoutError(
                f"{argv[0]} exceeded the time limit of {timeout_seconds:.0f} s", None, _tail(stderr_path)
            ) from None
        except BaseException:
            _kill_group(proc)
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
        )
    return RunResult(argv, proc.returncode, duration, stderr_path, stdout_path)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()
