"""The native executor: ARVA.app on the user's Mac runs a tool that ARVA's containers cannot run there (Flye, whose
fixed 8 GiB k-mer table does not fit Docker Desktop's VM on an 8 GB Mac, and Bakta, whose DIAMOND block with the full
database does not either; docs/plan-flye-nativo.md, option (b), "Contrato implementado" and "Bakta").

ARVA.app opens no port: it calls the API at 127.0.0.1 with a token, registers itself with what it can run, takes a
waiting job with an exclusive lease, reports heartbeats (each answer says whether to stop) and finally what ran.
The worker stays the owner of the job: it prepares the inputs, publishes a work record, waits while watching the
lease and the cancellation, and then post-processes the outputs exactly as for a Docker run.

State in Redis (shared by the API and the worker; nothing here needs a migration):
* arva:native:executor        the executor's last registration (expires EXECUTOR_TTL_SECONDS after it), with seen_at;
* arva:native:queue           sorted set of jobs waiting for the executor (score: when published);
* arva:native:work:<job>      the work record the worker published (what the claim returns);
* arva:native:lease:<job>     the lease (expires LEASE_SECONDS after the last heartbeat; created with SET NX, so only
                              one claim can hold it);
* arva:native:result:<job>    the executor's final report (set once);
* arva:native:stop:<job>      set by the worker (time limit): the next heartbeat answers cancel.

The executor never receives an argument vector to run: the work record carries structured parameters, paths relative
to the data folder and the argv the API built, and ARVA.app's own copy of the adapter (arva_tools/native.py) builds
the argv itself and runs only an identical one. The finish report's argv is refused unless it equals the API's.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from arva_tools import bakta as bakta_tool
from arva_tools import flye as flye_tool
from arva_tools.bakta import SKIP_FLAGS, BaktaAdapter
from arva_tools.base import DetectedTool, ToolStatus
from arva_tools.flye import NATIVE_LOCK, OUTPUTS, READ_TYPES, FlyeAdapter
from arva_tools.native_common import NativeRefusal, native_relative
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.config import get_settings

# The tools a native executor may run; each needs its adapter's native entry (arva_tools/<tool>.py) and a lock.
TOOLS = ("flye", "bakta")
NAMES = {"flye": "Flye", "bakta": "Bakta"}
MODULES = {"flye": flye_tool, "bakta": bakta_tool}
ADAPTERS = {"flye": FlyeAdapter, "bakta": BaktaAdapter}
LOCKS = {"flye": NATIVE_LOCK, "bakta": bakta_tool.NATIVE_LOCK}
DOCKER, MAC_NATIVE = "docker", "mac_native"
EXECUTIONS = (DOCKER, MAC_NATIVE)
# An executor is "open" (ready to take a job) when it registered within READY_SECONDS; it is remembered, to say
# "ARVA.app is not open" rather than nothing, for EXECUTOR_TTL_SECONDS.
READY_SECONDS = 60
EXECUTOR_TTL_SECONDS = 7 * 24 * 3600
REGISTER_SECONDS = 20
POLL_SECONDS = 5
HEARTBEAT_SECONDS = 15
LEASE_SECONDS = 120
# A job waiting for ARVA.app fails when no executor registered for this long (it was closed, or never opened).
WAIT_SECONDS = 15 * 60
# After a stop was asked (cancellation, time limit), how long the worker waits for ARVA.app's report.
STOP_GRACE_SECONDS = LEASE_SECONDS
RESULT_TTL_SECONDS = 24 * 3600
KEY = "arva:native:"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,256}")
EXECUTOR_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
VERSION_TEXT = re.compile(r"[A-Za-z0-9._+-]{1,64}")
FLYE_REQUIRED_OPTIONS = frozenset({"--out-dir", "--threads", "--iterations", *(f"--{r}" for r in READ_TYPES)})
# Every option ARVA may pass to Bakta (arva_tools.bakta.flags and the skip options).
BAKTA_REQUIRED_OPTIONS = frozenset({"--db", "--output", "--prefix", "--tmp-dir", "--threads", "--min-contig-length",
                                    "--translation-table", "--locus-tag", "--locus-tag-increment", "--genus",
                                    "--species", "--strain", "--complete", "--keep-contig-headers",
                                    *SKIP_FLAGS.values()})
OUTCOMES = ("exited", "refused", "stopped", "not_started")


class NativeError(Exception):
    """A refused executor request or job option: `code` (api.error.<code> in the interface), HTTP `status`."""

    def __init__(self, code: str, message: str, status: int = 409, **params: Any):
        super().__init__(message)
        self.code, self.status, self.params = code, status, params


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def _now() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds") if ts is not None else None


def _get(key: str) -> dict[str, Any] | None:
    raw = get_redis().get(KEY + key)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# --- Token ---------------------------------------------------------------------------------------------------------

def check_token(authorization: str | None) -> None:
    """The request's "Authorization: Bearer <token>" must equal the token ARVA.app wrote (settings.native_token_file),
    compared in constant time. The file is read at every request: ARVA.app may replace it."""
    path = Path(get_settings().native_token_file)
    try:
        expected = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise NativeError("native_token_missing", f"There is no native executor token ({path}): ARVA.app writes it "
                          "when it starts", 503) from None
    if not TOKEN_PATTERN.fullmatch(expected):
        raise NativeError("native_token_missing", f"The native executor token in {path} is malformed", 503)
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme != "Bearer" or not hmac.compare_digest(supplied.strip().encode(), expected.encode()):
        raise NativeError("native_token_refused", "Missing or wrong native executor token", 401)


# --- Executor registration and readiness ---------------------------------------------------------------------------

def _storage_id(db: Session) -> str | None:
    from app.services import locations

    state = locations.inspect(db)
    return state.disk_id if state.status == "ok" else None


def _host_data_dir() -> str | None:
    from app.services.locations import host_path

    return host_path(os.environ.get("ARVA_HOST_DATA_DIR"))


def _version(tool: str, facts: dict[str, Any]) -> str | None:
    found = ADAPTERS[tool].version_pattern.search(facts.get("version") or "")
    return found.group(1) if found else None


def readiness(tool: str, record: dict[str, Any], facts: dict[str, Any], storage_id: str | None,
              host_data: str | None) -> str | None:
    """Why this executor cannot run ARVA's `tool` now (a code), or None when it can: the Mac, the data folder (the
    same as the containers'), and the tool installed from ARVA's osx-arm64 lock (lock, build, version, --help, and
    flye-samtools for Flye; a database folder of arva.conf for Bakta)."""
    module, lock = MODULES[tool], LOCKS[tool]
    if facts.get("tool") not in (None, tool):
        return "tool_mismatch"
    if record.get("platform") != lock["platform"]:
        return "platform_unsupported"
    try:
        data_dir = module.native_data_dir(record.get("data_dir"))
        module.native_executable(facts.get("executable"))
    except NativeRefusal as exc:
        return exc.code
    if storage_id is None or record.get("storage_id") != storage_id:
        return "storage_mismatch"
    if host_data is not None and os.path.normpath(host_data) != data_dir:
        return "other_data_dir"
    if facts.get("lock_sha256") != lock["lock_sha256"]:
        return "lock_mismatch"
    package = facts.get("package") or {}
    if package.get("build") != lock["build"] or package.get("sha256") != lock["package_sha256"]:
        return "build_mismatch"
    if _version(tool, facts) != lock["version"]:
        return "version_mismatch"
    required = FLYE_REQUIRED_OPTIONS if tool == "flye" else BAKTA_REQUIRED_OPTIONS
    if not required <= set(facts.get("help_options") or ()):
        return "help_incomplete"
    if tool == "flye" and not facts.get("samtools_helper"):
        return "samtools_missing"
    if tool == "bakta" and not record.get("database_dirs"):
        return "no_database_folders"
    return None


def flye_readiness(record: dict[str, Any], facts: dict[str, Any], storage_id: str | None,
                   host_data: str | None) -> str | None:
    return readiness("flye", record, facts, storage_id, host_data)


def register(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Record ARVA.app's registration (also its periodic heartbeat) and say, per tool, whether it may run jobs."""
    if unknown := [t for t in payload["tools"] if t not in TOOLS]:
        raise NativeError("native_tool_unknown", f"ARVA does not run {', '.join(unknown)} natively", 422,
                          tools=", ".join(unknown))
    storage_id, host_data = _storage_id(db), _host_data_dir()
    ready = {}
    for tool, facts in payload["tools"].items():
        reason = readiness(tool, payload, facts, storage_id, host_data)
        ready[tool] = {"ready": reason is None, "reason": reason}
    record = {**payload, "ready": ready, "seen_at": _now()}
    previous = executor()
    if previous is None or previous.get("executor_id") != payload["executor_id"]:
        record["registered_at"] = record["seen_at"]
    else:
        record["registered_at"] = previous.get("registered_at", record["seen_at"])
    get_redis().set(KEY + "executor", json.dumps(record), ex=EXECUTOR_TTL_SECONDS)
    return {"executor_id": payload["executor_id"], "ready": ready, "server_time": _iso(record["seen_at"]),
            "register_seconds": REGISTER_SECONDS, "poll_seconds": POLL_SECONDS,
            "heartbeat_seconds": HEARTBEAT_SECONDS, "lease_seconds": LEASE_SECONDS}


def executor() -> dict[str, Any] | None:
    """The last registration, or None (never registered, forgotten, or Redis unreachable)."""
    try:
        return _get("executor")
    except RedisError:
        return None


def is_open(record: dict[str, Any] | None) -> bool:
    return record is not None and _now() - float(record.get("seen_at", 0)) <= READY_SECONDS


def status() -> dict[str, Any]:
    """What the interface shows (Settings → Performance, the Flye and Bakta dialogs): whether ARVA.app's native
    executor is known and open, and each tool it has (installed, version, build, whether its lock is ARVA's)."""
    record = executor()
    out: dict[str, Any] = {"known": record is not None, "open": is_open(record), "seen_at": None,
                           "app_version": None, "platform": None, "macos": None, "chip": None, "memory_bytes": None,
                           "expected": {t: {k: LOCKS[t][k] for k in ("platform", "version", "build", "lock_sha256")}
                                        for t in TOOLS},
                           "tools": {}}
    if record is None:
        return out
    out.update(seen_at=_iso(record.get("seen_at")), app_version=record.get("app_version"),
               platform=record.get("platform"), macos=record.get("macos"), chip=record.get("chip"),
               memory_bytes=record.get("memory_bytes"))
    for tool, facts in (record.get("tools") or {}).items():
        if tool not in TOOLS:
            continue
        ready = (record.get("ready") or {}).get(tool) or {}
        package = facts.get("package") or {}
        out["tools"][tool] = {
            "installed": True, "version": _version(tool, facts), "version_text": facts.get("version"),
            "build": package.get("build"), "lock_sha256": facts.get("lock_sha256"),
            "lock_matches": facts.get("lock_sha256") == LOCKS[tool]["lock_sha256"],
            "ready": bool(ready.get("ready")) and out["open"], "reason": ready.get("reason") if out["open"] else
            (ready.get("reason") or "app_not_open"),
        }
    return out


def ready_executor(tool: str, require_open: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    """The open executor and its facts for `tool`, or NativeError: ARVA.app not open, or not able to run it. Without
    `require_open`, its last registration is enough (the worker then waits for ARVA.app to come back)."""
    record = executor()
    if record is None or (require_open and not is_open(record)):
        raise NativeError("native_app_not_open", f"ARVA.app is not open: open it so that {NAMES.get(tool, tool)} can "
                          "run on this Mac", tool=tool)
    facts = (record.get("tools") or {}).get(tool)
    ready = (record.get("ready") or {}).get(tool) or {}
    if facts is None:
        raise NativeError("native_tool_not_installed", f"ARVA.app has no {tool} installed for this Mac", tool=tool)
    if not ready.get("ready"):
        reason = ready.get("reason") or "unknown"
        raise NativeError("native_not_ready", f"ARVA.app cannot run {tool} on this Mac now ({reason})", tool=tool,
                          reason=reason)
    return record, facts


def detected_tool(facts: dict[str, Any], tool: str = "flye") -> DetectedTool:
    """The Mac's tool as a detected tool (what the job records as its tool, path and version)."""
    adapter = ADAPTERS[tool]
    value = _version(tool, facts)
    return DetectedTool(adapter.info, ToolStatus.available, facts.get("executable"), value,
                        value in adapter.info.tested_versions)


def provenance(record: dict[str, Any], facts: dict[str, Any], tool: str = "flye") -> dict[str, Any]:
    """What a native run records about where it ran (result_summary.native and the job's parameters)."""
    package = facts.get("package") or {}
    return {"tool": tool, "platform": record.get("platform"), "build": package.get("build"),
            "package_sha256": package.get("sha256"), "lock": LOCKS[tool]["lock"],
            "lock_sha256": facts.get("lock_sha256"), f"{tool}_version": facts.get("version"),
            "executable": facts.get("executable"), "app_version": record.get("app_version"),
            "executor_id": record.get("executor_id"), "macos": record.get("macos"), "chip": record.get("chip"),
            "memory_bytes": record.get("memory_bytes"), "data_dir": record.get("data_dir")}


def database_ref(path: str | None, record: dict[str, Any]) -> dict[str, str]:
    """A database folder as the Mac sees it, for a native run: {"root": the host folder of the ARVA location that
    holds it (the launcher's ARVA_DATABASES_DIR or an ARVA_ADD_DATABASES folder), "rel": the path inside it}. Raises
    NativeError when the database is not in a folder of the Mac (a Docker volume) or ARVA.app did not name that
    folder (its arva.conf), or the path has characters ARVA does not pass to native runs."""
    from app.services.locations import locations

    for loc in sorted(locations(), key=lambda x: len(x.container_path), reverse=True):
        root = loc.container_path.rstrip("/")
        if loc.role not in ("databases", "external_databases") or not path or not path.startswith(root + "/"):
            continue
        if not loc.host_path:
            break
        host = os.path.normpath(loc.host_path)
        if host not in {os.path.normpath(d) for d in record.get("database_dirs") or ()}:
            raise NativeError("native_database_folder_unknown", f"ARVA.app does not know the database folder {host} "
                              "(it reads arva.conf); restart ARVA from ARVA.app", folder=host)
        try:
            ref = {"root": bakta_tool.native_folder(host, "Bakta", "a database folder"),
                   "rel": native_relative(path[len(root) + 1:])}
        except NativeRefusal as exc:
            raise NativeError("native_database_unusable", f"This database's path cannot be used on this Mac: {exc}",
                              reason=exc.code) from None
        return ref
    raise NativeError("native_database_not_on_mac", "This database is inside Docker (a volume), not in a folder of the "
                      "Mac, so ARVA.app cannot read it. Set a database folder on the Mac (ARVA_DATABASES_DIR) or add "
                      "the database's folder (ARVA_ADD_DATABASES)")


# --- Work, lease, heartbeat, finish ----------------------------------------------------------------------------------

def publish(job_id: str, work: dict[str, Any]) -> None:
    r = get_redis()
    r.set(KEY + f"work:{job_id}", json.dumps(work))
    r.zadd(KEY + "queue", {job_id: _now()})


def withdraw(job_id: str) -> None:
    """Forget everything about a job's native run (it ended, one way or another)."""
    r = get_redis()
    r.zrem(KEY + "queue", job_id)
    r.delete(*(KEY + f"{k}:{job_id}" for k in ("work", "lease", "result", "stop")))


def lease(job_id: str) -> dict[str, Any] | None:
    return _get(f"lease:{job_id}")


def result(job_id: str) -> dict[str, Any] | None:
    return _get(f"result:{job_id}")


def request_stop(job_id: str) -> None:
    get_redis().set(KEY + f"stop:{job_id}", "1", ex=RESULT_TTL_SECONDS)


def _registered(executor_id: str, tool: str | None = None) -> dict[str, Any]:
    record = executor()
    if record is None or record.get("executor_id") != executor_id:
        raise NativeError("native_executor_unknown", "This executor has not registered (or another one has since)",
                          409)
    if tool is not None and not ((record.get("ready") or {}).get(tool) or {}).get("ready"):
        raise NativeError("native_not_ready", f"This executor cannot run {tool} now", 409, tool=tool)
    return record


def _job_running(db: Session, job_id: str):
    from app.models import AnalysisJob, JobStatus

    db.expire_all()
    job = db.get(AnalysisJob, job_id)
    ok = job is not None and job.status is JobStatus.running and \
        (job.parameters or {}).get("execution") == MAC_NATIVE
    return job, ok


def claim(db: Session, executor_id: str, tools: list[str]) -> dict[str, Any] | None:
    """The oldest waiting job of one of `tools`, leased to this executor; None when there is none. The lease is
    created with SET NX: two claims of one job cannot both succeed."""
    if unknown := [t for t in tools if t not in TOOLS]:
        raise NativeError("native_tool_unknown", f"ARVA does not run {', '.join(unknown)} natively", 422,
                          tools=", ".join(unknown))
    record = _registered(executor_id)
    r = get_redis()
    for job_id in r.zrange(KEY + "queue", 0, -1):
        work = _get(f"work:{job_id}")
        if work is None:
            r.zrem(KEY + "queue", job_id)
            continue
        if work.get("tool") not in tools or not ((record.get("ready") or {}).get(work["tool"]) or {}).get("ready"):
            continue
        job, ok = _job_running(db, job_id)
        if not ok:
            if job is None or job.status.value not in ("pending", "running"):
                r.zrem(KEY + "queue", job_id)  # left by a worker that stopped
            continue
        if job.cancel_requested_at is not None:
            continue
        now = _now()
        lease_id = str(uuid.uuid4())
        held = {"lease_id": lease_id, "executor_id": executor_id, "claimed_at": now, "heartbeat_at": now, "pid": None}
        if not r.set(KEY + f"lease:{job_id}", json.dumps(held), nx=True, ex=LEASE_SECONDS):
            continue
        r.zrem(KEY + "queue", job_id)
        return {"job_id": job_id, "tool": work["tool"], "lease_id": lease_id, "lease_seconds": LEASE_SECONDS,
                "heartbeat_seconds": HEARTBEAT_SECONDS, "work": work}
    return None


def _held(job_id: str, executor_id: str, lease_id: str) -> dict[str, Any]:
    held = lease(job_id)
    if held is None or held.get("lease_id") != lease_id or held.get("executor_id") != executor_id:
        raise NativeError("native_lease_lost", "This lease expired or is not yours: stop the tool", 409)
    return held


def heartbeat(db: Session, job_id: str, executor_id: str, lease_id: str, pid: int | None) -> dict[str, Any]:
    """Renew the lease; the answer says whether to stop (the user cancelled, the time limit passed, or the job is no
    longer running in ARVA)."""
    held = _held(job_id, executor_id, lease_id)
    job, ok = _job_running(db, job_id)
    cancel = not ok or job.cancel_requested_at is not None or bool(get_redis().exists(KEY + f"stop:{job_id}"))
    held.update(heartbeat_at=_now(), pid=pid if pid is not None else held.get("pid"))
    if not get_redis().set(KEY + f"lease:{job_id}", json.dumps(held), xx=True, ex=LEASE_SECONDS):
        raise NativeError("native_lease_lost", "This lease expired: stop the tool", 409)
    return {"cancel": cancel, "lease_seconds": LEASE_SECONDS, "heartbeat_seconds": HEARTBEAT_SECONDS}


def finish(job_id: str, executor_id: str, lease_id: str, report: dict[str, Any]) -> dict[str, Any]:
    """Record ARVA.app's final report for the worker. Refused (422) when the argv that ran is not the one the API built,
    the executable or tool is another, or an output path is not one of the tool's outputs in the job's out-dir; such a
    report is still recorded as rejected, so the job fails with that reason."""
    _held(job_id, executor_id, lease_id)
    work = _get(f"work:{job_id}")
    if work is None:
        raise NativeError("native_lease_lost", "This job's native run is no longer expected", 409)
    problem = None
    ran = report.get("outcome") in ("exited", "stopped")
    if report.get("executable") != work["executable"]:
        problem = ("native_executable_mismatch", "the executable reported is not the one the work names")
    elif ran and report.get("argv") != work["argv"]:
        problem = ("native_argv_mismatch", "the argument vector reported is not the one ARVA built for this job")
    elif report.get("tool") != work["tool"]:
        problem = ("native_tool_mismatch", f"the report is for {report.get('tool')}, the work for {work['tool']}")
    else:
        allowed = {f"{work['out_dir']}/{n}" for n in OUTPUTS} if work["tool"] == "flye" else \
            bakta_tool.native_outputs(work["out_dir"])
        for rel in report.get("outputs") or []:
            try:
                native_relative(rel)
            except NativeRefusal:
                problem = ("native_unsafe_path", f"{rel!r} is not a plain path inside the data folder")
                break
            if rel not in allowed:
                problem = ("native_unsafe_path", f"{rel} is not one of {NAMES[work['tool']]}'s outputs in this "
                                                 "job's folder")
                break
    stored = {**report, "received_at": _now()}
    if problem is not None:
        stored = {"outcome": "rejected", "code": problem[0], "detail": problem[1], "received_at": _now(),
                  "executable": report.get("executable")}
    if not get_redis().set(KEY + f"result:{job_id}", json.dumps(stored), nx=True, ex=RESULT_TTL_SECONDS):
        raise NativeError("native_already_finished", "This job's native run was already reported", 409)
    if problem is not None:
        raise NativeError(problem[0], f"Report refused: {problem[1]}", 422)
    return {"accepted": True}
