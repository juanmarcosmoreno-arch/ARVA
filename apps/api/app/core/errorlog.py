"""ARVA's error log and application log: JSON Lines files in <data folder>/logs, for the diagnostic report.

errors.jsonl holds one entry per problem: unhandled API errors (500s) and coded refusals, job failures and
cancellations, worker crashes, start-up problems and the errors the web interface reports. Each entry has a short id
that the interface shows, so that a report can be asked for by that id. app.jsonl holds start-up, the configuration
summary and job start and end with their durations.

Both files rotate by size (errors.jsonl.1 … .N, the oldest dropped) and so stay under a total cap. They are written
only while the data folder can be used (app.services.locations: its disk is connected and is the one this metadata
knows); otherwise an entry goes to stderr only, the container's log, so that nothing is written to another disk.
Every text passes app.core.redaction before it is kept. Nothing here sends anything anywhere.
"""
from __future__ import annotations

import fcntl
import importlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.exc import StatementError

from app import __version__
from app.core.config import get_settings
from app.core.redaction import clip, redact_value, tail

ERRORS = "errors.jsonl"
APP = "app.jsonl"
# Bytes per file and rotated files kept: errors.jsonl takes at most 10 MiB, app.jsonl 3 MiB.
LIMITS = {ERRORS: (2 * 1024**2, 4), APP: (1024**2, 2)}
MAX_ENTRY_BYTES = 48 * 1024
STDERR_TAIL_LINES = 60
COMPONENTS = ("api", "worker", "job", "web", "launcher")
SEVERITIES = ("error", "warning", "info")
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
ID_PATTERN = r"[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}"
CORRELATION_PATTERN = r"[0-9a-f]{16}"
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
_SEGMENT = re.compile(r"[a-z][a-z0-9_-]{0,40}")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_INPUT_VALUE = re.compile(r"input_value=('[^']*'|\"[^\"]*\"|\S+)")
_STORAGE_CHECK_SECONDS = 10.0

# The English texts of the entry codes ARVA itself names; job failures and refusals carry their own message and
# code (job.error.<code>, api.error.<code> in the interface).
MESSAGES = {
    "internal_error": "Unexpected error while handling {method} {route}",
    "job_failed": "The {job_type} job failed",
    "job_cancelled": "The {job_type} job was cancelled at the user's request",
    "worker_task_failed": "The worker could not run the task {task}",
    "worker_crashed": "The worker process running a job ended unexpectedly (exit status {status})",
    "worker_stopped": "The worker stopped because of an error",
    "startup_migration_failed": "The database could not be brought up to date when ARVA started",
    "startup_migrations_pending": "The database is at revision {current} but this ARVA needs {head}",
    "startup_tools_unusable": "Tools that are installed but cannot be used: {tools}",
    "startup_databases_unavailable": "{count} registered databases are in folders that are not available",
    "startup_checks_failed": "The start-up checks could not be completed",
    "web_error": "The web interface failed: {message}",
    "web_api_failed": "A request of the web interface failed: {method} {route} ({status})",
    "launcher_compose_failed": "docker compose up failed (exit status {status})",
}

correlation: ContextVar[str | None] = ContextVar("arva_correlation", default=None)
_recent: deque[dict] = deque(maxlen=200)
_write_lock = threading.Lock()
_storage: dict[str, Any] = {"root": None, "until": 0.0, "ok": False}


def now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id() -> str:
    pick = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{pick[:4]}-{pick[4:]}"


def new_correlation_id() -> str:
    return secrets.token_hex(8)


def current_correlation() -> str | None:
    return correlation.get()


def _git_commit() -> str | None:
    repo = Path(__file__).resolve().parents[4]
    if not (repo / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], capture_output=True,
                             text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and _COMMIT.fullmatch(value) else None


@lru_cache
def build() -> dict[str, str]:
    """ARVA's version and the git commit it was built from: ARVA_GIT_COMMIT, set when the image is built
    (docker/api.Dockerfile), else the checkout's own when run from one, else "unknown"."""
    commit = os.environ.get("ARVA_GIT_COMMIT", "").strip().lower()
    if not _COMMIT.fullmatch(commit):
        commit = _git_commit() or "unknown"
    return {"version": __version__, "commit": commit[:12]}


def route_template(path: str) -> str:
    """A path with every segment that is not a plain lowercase word (ids, names) replaced: the shape, no values."""
    return clip("/".join(p if not p or _SEGMENT.fullmatch(p) else "{…}" for p in path.split("?")[0].split("/")), 200)


def _format(template: str, params: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), "?")), template)


# --- Exceptions -------------------------------------------------------------------------------------------------

@lru_cache
def _roots() -> tuple[tuple[str, str], ...]:
    """ARVA's own code: the API package, the tool adapters, the scientific core and the worker script."""
    import app

    api = Path(app.__file__).resolve().parent
    roots = [api, api.parents[1] / "workers"]
    for name in ("arva_tools", "arva_core"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        if module.__file__:
            roots.append(Path(module.__file__).resolve().parent)
    return tuple((str(r) + os.sep, r.name) for r in roots)


def _own(filename: str) -> str | None:
    path = os.path.abspath(filename)
    for prefix, name in _roots():
        if path.startswith(prefix):
            return f"{name}/{path[len(prefix):]}"
    return None


def _package(filename: str) -> str:
    m = re.search(r"(?:site|dist)-packages/([^/]+)", filename)
    return (m.group(1) if m else Path(filename).stem).removesuffix(".py")


def frames(tb) -> list[str]:
    """ARVA's frames as file:line in function: source; consecutive library frames as one summary line."""
    out: list[str] = []
    library: list[str] = []

    def flush() -> None:
        if library:
            names = ", ".join(dict.fromkeys(library))
            out.append(f"… {len(library)} library frame{'s' if len(library) > 1 else ''} ({names})")
            library.clear()

    for fs in traceback.extract_tb(tb):
        rel = _own(fs.filename)
        if rel is None:
            library.append(_package(fs.filename))
            continue
        flush()
        out.append(f"{rel}:{fs.lineno} in {fs.name}" + (f": {clip(fs.line.strip(), 160)}" if fs.line else ""))
    flush()
    return out[-40:]


def _type_name(exc: BaseException) -> str:
    t = type(exc)
    return t.__qualname__ if t.__module__ == "builtins" else f"{t.__module__}.{t.__qualname__}"


def _message(exc: BaseException) -> str:
    """The exception's text without what a database or validation error quotes (SQL, parameters, input values)."""
    if isinstance(exc, StatementError) and getattr(exc, "orig", None) is not None:
        first = (str(exc.orig).strip().splitlines() or [""])[0]
        return f"{type(exc.orig).__name__}: {first} (SQL statement and parameters left out)"
    return _INPUT_VALUE.sub("input_value=…", str(exc))


def describe(exc: BaseException) -> dict[str, Any]:
    out: dict[str, Any] = {"type": _type_name(exc), "message": clip(_message(exc), 1000),
                           "traceback": frames(exc.__traceback__)}
    causes, seen = [], {id(exc)}
    cur = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    while cur is not None and len(causes) < 3 and id(cur) not in seen:
        seen.add(id(cur))
        causes.append({"type": _type_name(cur), "message": clip(_message(cur), 500)})
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    if causes:
        out["causes"] = causes
    return out


# --- Writing ----------------------------------------------------------------------------------------------------

def _data_usable() -> bool:
    from app.services import locations

    try:
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            return locations.inspect(db).writable
    except Exception:
        # Without the database (it may be the problem being logged) the marker file alone decides.
        return locations.marker_present()


def reset_storage_check() -> None:
    _storage.update(root=None, until=0.0, ok=False)


def log_folder() -> Path | None:
    """<data folder>/logs while the data folder can be used (checked at most every few seconds), else None."""
    s = get_settings()
    now = time.monotonic()
    if _storage["root"] != s.storage_root or now >= _storage["until"]:
        _storage.update(root=s.storage_root, until=now + _STORAGE_CHECK_SECONDS, ok=_data_usable())
    if not _storage["ok"]:
        return None
    try:
        s.logs_dir.mkdir(exist_ok=True)
    except OSError:
        return None
    return s.logs_dir


def _rotated(path: Path, n: int) -> Path:
    return path.with_name(f"{path.name}.{n}")


def _append(path: Path, line: bytes, max_bytes: int, keep: int) -> None:
    """One line appended under a lock shared by the API and the worker processes; the file is rotated first when
    the line would take it over its size."""
    with _write_lock, open(path.with_name(f".{path.name}.lock"), "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError:
            pass
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size and size + len(line) > max_bytes:
            _rotated(path, keep).unlink(missing_ok=True)
            for n in range(keep - 1, 0, -1):
                if _rotated(path, n).exists():
                    os.replace(_rotated(path, n), _rotated(path, n + 1))
            os.replace(path, _rotated(path, 1))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


def _shrink(entry: dict[str, Any]) -> dict[str, Any]:
    small = {k: v for k, v in entry.items() if k not in ("details", "stderr_tail", "exception")}
    if isinstance(entry.get("exception"), dict):
        exc = entry["exception"]
        small["exception"] = {"type": exc.get("type"), "message": clip(exc.get("message"), 300),
                              "traceback": (exc.get("traceback") or [])[-12:]}
    if entry.get("stderr_tail"):
        small["stderr_tail"] = tail(entry["stderr_tail"], 20, 200)
    small["truncated"] = True
    return small


def _write(name: str, entry: dict[str, Any]) -> None:
    line = json.dumps(entry, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(line.encode()) > MAX_ENTRY_BYTES:
        line = json.dumps(_shrink(entry), ensure_ascii=False, default=str, separators=(",", ":"))[:MAX_ENTRY_BYTES]
    folder = log_folder()
    if folder is not None:
        try:
            _append(folder / name, (line + "\n").encode(), *LIMITS[name])
            return
        except OSError:
            pass
    print(f"ARVA {name.split('.')[0]} log (data folder not available, kept here only): {line}", file=sys.stderr,
          flush=True)


def record(component: str, severity: str, code: str, message: str | None = None, *,
           params: dict[str, Any] | None = None, exc: BaseException | None = None, request: dict | None = None,
           job: dict | None = None, tool: dict | None = None, stderr_tail: str | None = None,
           correlation_id: str | None = None, details: dict | None = None) -> str:
    """Keep one error log entry and return its id (shown to the user). Never raises: a problem of the log itself
    must not hide the one being logged."""
    entry_id = new_id()
    try:
        _record(entry_id, component, severity, code, message, params, exc, request, job, tool, stderr_tail,
                correlation_id, details)
    except Exception as failure:
        print(f"ARVA error log could not keep entry {entry_id} ({code}): {type(failure).__name__}", file=sys.stderr)
    return entry_id


def _record(entry_id, component, severity, code, message, params, exc, request, job, tool, stderr_tail,
            correlation_id, details) -> None:
    params = dict(params or {})
    b = build()
    entry: dict[str, Any] = {
        "id": entry_id, "time": now_text(), "version": b["version"], "commit": b["commit"],
        "component": component if component in COMPONENTS else "api",
        "severity": severity if severity in SEVERITIES else "error", "code": clip(code, 80),
        "message": clip(message if message is not None else _format(MESSAGES.get(code, code), params), 2000),
        "params": params,
    }
    if cid := correlation_id or correlation.get():
        entry["correlation_id"] = cid
    for key, value in (("request", request), ("job", job), ("tool", tool), ("details", details)):
        if value:
            entry[key] = value
    if exc is not None:
        entry["exception"] = describe(exc)
    if stderr_tail:
        entry["stderr_tail"] = tail(stderr_tail, STDERR_TAIL_LINES)
    entry = redact_value(entry)
    _recent.append(entry)
    if entry["severity"] != "info":
        print(f"ARVA {entry['severity']} {entry['id']} [{entry['component']}] {entry['code']}: "
              f"{clip(entry['message'], 300)}", file=sys.stderr, flush=True)
    _write(ERRORS, entry)


def info(event: str, message: str, component: str = "api", **fields: Any) -> None:
    """One application log line (start-up, configuration, job start and end); never raises."""
    entry = {"time": now_text(), "component": component, "event": event, "message": message, **fields}
    if cid := correlation.get():
        entry.setdefault("correlation_id", cid)
    try:
        _write(APP, redact_value(entry))
    except Exception as failure:
        print(f"ARVA application log could not keep {event}: {type(failure).__name__}", file=sys.stderr)


class RateLimit:
    """At most `count` events in any `seconds`."""

    def __init__(self, count: int, seconds: float):
        self.count, self.seconds = count, seconds
        self.times: deque[float] = deque()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.times and now - self.times[0] > self.seconds:
                self.times.popleft()
            if len(self.times) >= self.count:
                return False
            self.times.append(now)
            return True


_refusals = RateLimit(30, 60.0)
_refusal_seen: dict[tuple[str, str], float] = {}
REFUSAL_REPEAT_SECONDS = 300.0


def refusal(code: str, message: str, params: dict, method: str, route: str, status: int,
            correlation_id: str | None) -> str | None:
    """A coded 4xx or 503 refusal at info level: the same code on the same route at most once in five minutes,
    and at most 30 refusals a minute."""
    key, now = (code, route), time.monotonic()
    if now - _refusal_seen.get(key, -REFUSAL_REPEAT_SECONDS) < REFUSAL_REPEAT_SECONDS or not _refusals.allow():
        return None
    if len(_refusal_seen) > 500:
        _refusal_seen.clear()
    _refusal_seen[key] = now
    return record("api", "info", code, message, params=params,
                  request={"method": method, "route": route, "status": status}, correlation_id=correlation_id)


# --- Reading ----------------------------------------------------------------------------------------------------

def _file_entries(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in reversed(text.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("time"), str):
            yield entry


def read(name: str = ERRORS, limit: int = 20, since: str | None = None,
         match: Callable[[dict], bool] | None = None) -> list[dict]:
    """The newest entries first (at most `limit`, none older than `since`, an ISO time): this data folder's log
    files, and this process's own entries that could not be written there."""
    found: dict[str, dict] = {}
    seen_lines = 0
    folder = log_folder()
    if folder is not None:
        for path in [folder / name, *(_rotated(folder / name, n) for n in range(1, LIMITS[name][1] + 1))]:
            done = False
            for entry in _file_entries(path):
                if since and entry["time"] < since:
                    done = True
                    break
                if match is None or match(entry):
                    found[entry.get("id") or f"line-{seen_lines}"] = entry
                    seen_lines += 1
                    if len(found) >= limit:
                        done = True
                        break
            if done:
                break
    if name == ERRORS:
        for entry in _recent:
            if (not since or entry["time"] >= since) and (match is None or match(entry)):
                found.setdefault(entry["id"], entry)
    return sorted(found.values(), key=lambda e: e["time"], reverse=True)[:limit]
