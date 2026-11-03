"""Shared lifecycle for every analysis job executed by the worker.

`run_job` marks the job running, records the environment, runs the job body,
and on any failure rolls back database changes, removes partial outputs and
records the reason. A job therefore ends either completed with all outputs
registered, or failed (or cancelled) with none.

Cancellation: the API records `cancel_requested_at`; the worker reads it while a tool runs (every few seconds,
through the monitor callback of run_command, which then kills the tool's process group) and at the points where
ARVA's own code can stop safely. A job cancelled before a worker started it is never run.

Storage: a job starts only while the data folder can be written (app.services.locations: its disk is connected and
it is the folder this metadata knows). Otherwise it fails with a coded reason and touches no file, so that nothing
is written to another disk; when the folder disappears while it runs, the reason says so.
"""
from __future__ import annotations

import json
import platform
import shutil
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from arva_tools import ToolExecutionError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import errorlog
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus, RawFile
from app.storage import LocalStorage, get_storage


class JobFailure(Exception):
    """An expected failure with a clear, user-facing reason (no traceback). `code` and `params` name it for the
    interface (job.error.<code>, recorded in error_detail); the message stays the English text."""

    def __init__(self, message: str, code: str | None = None, **params: str | int):
        super().__init__(message)
        self.code = code
        self.params = params


class JobCancelled(Exception):
    """Someone asked to cancel the job; raised in the worker at the next check."""


def now() -> datetime:
    return datetime.now(UTC)


class JobLog:
    def __init__(self, db: Session, job: AnalysisJob):
        self.db = db
        self.job = job
        self.lines: list[str] = []

    def __call__(self, message: str, flush: bool = False) -> None:
        self.lines.append(f"[{now().isoformat(timespec='seconds')}] {message}")
        if flush:
            self.flush()

    def flush(self) -> None:
        self.job.log_text = "\n".join(self.lines)
        self.db.commit()


@dataclass
class JobContext:
    db: Session
    job: AnalysisJob
    storage: LocalStorage
    log: JobLog
    # Run after the job is committed as completed (e.g. queue follow-up analyses).
    after_commit: list[Callable[[], None]] = field(default_factory=list)
    # Run when the job fails or is cancelled, after the rollback and before partial outputs are removed (e.g. keep
    # Flye's work folder for --resume).
    before_cleanup: list[Callable[[BaseException], None]] = field(default_factory=list)
    # A tool of this job stopped by SIGKILL from outside ARVA (most often for lack of memory).
    killed_tool: str | None = None

    @property
    def _scope(self) -> str:
        j = self.job
        return f"{j.project_id}/{j.sample_id or '_project'}/{j.id}"

    @property
    def results_rel(self) -> str:
        return f"results/{self._scope}"

    @property
    def processed_rel(self) -> str:
        return f"processed/{self._scope}"

    @property
    def checkpoint_rel(self) -> str:
        return f"checkpoints/{self._scope}"

    def cancel_requested(self, lock: bool = False) -> bool:
        """Read from the database, not the session, so a request made while the job runs is seen."""
        query = select(AnalysisJob.cancel_requested_at).where(AnalysisJob.id == self.job.id)
        with self.db.no_autoflush:
            row = self.db.execute(query.with_for_update() if lock else query).first()
        # A job whose record is gone (its project or sample was deleted) has nobody left to report to: stop it.
        return row is None or row[0] is not None

    def check_cancelled(self) -> None:
        if self.cancel_requested():
            raise JobCancelled()

    def path(self, rel: str) -> Path:
        return self.storage.resolve(rel)

    def input_files(self) -> list[RawFile]:
        files = []
        for file_id in self.job.input_raw_file_ids or []:
            f = self.db.get(RawFile, file_id)
            if f is None:
                raise JobFailure(f"input file {file_id} no longer exists", "input_missing", file_id=file_id)
            files.append(f)
        return files


def cancellation_note(job: AnalysisJob) -> str:
    asked = job.cancel_requested_at.isoformat(timespec="seconds") if job.cancel_requested_at else "?"
    return f"Cancelled at the user's request (asked at {asked})"


def _with_memory_advice(job: AnalysisJob, tool: str) -> tuple[str, str]:
    """The failure reason with what to change; a reason that already names memory (an adapter's) gets only the
    advice."""
    from app.services.performance import memory_advice, out_of_memory_reason

    message = (job.error_message or "").rstrip(". ")
    note = memory_advice(job.resources) if "memory" in message.lower() else out_of_memory_reason(tool, job.resources)
    return (f"{message}. {note}" if message else note), note


def _storage_usable() -> bool:
    from app.services import locations

    try:
        with SessionLocal() as db:
            return locations.inspect(db).writable
    except (SQLAlchemyError, OSError):
        return False


def _storage_problem() -> Exception | None:
    from app.services import locations

    try:
        locations.ensure_data()
    except locations.StorageUnavailable as exc:
        return exc
    return None


def _detail(exc: BaseException) -> dict | None:
    code = getattr(exc, "code", None)
    return {"code": code, "params": getattr(exc, "params", {})} if code else None


def job_ref(job: AnalysisJob) -> dict:
    """What an error log entry says about a job (ids, never names)."""
    return {"id": job.id, "type": job.job_type, "status": job.status.value, "project_id": job.project_id,
            "sample_id": job.sample_id, "parent_job_id": job.parent_job_id}


def _log_end(job: AnalysisJob, exc: BaseException) -> None:
    """A failed or cancelled job in the error log: its coded reason, the exception (where ARVA's code raised it)
    and the end of the tool's own output."""
    cancelled = isinstance(exc, JobCancelled)
    detail = job.error_detail or {}
    code = detail.get("code") or ("job_cancelled" if cancelled else "job_failed")
    errorlog.record("job", "info" if cancelled else "error", code,
                    cancellation_note(job) if cancelled else job.error_message,
                    params={"job_type": job.job_type, **(detail.get("params") or {})},
                    exc=None if cancelled else exc, job=job_ref(job),
                    tool={"name": job.tool_name, "version": job.tool_version},
                    stderr_tail=getattr(exc, "stderr_tail", None) or None)


def _ensure_space(db: Session, job: AnalysisJob, root: Path) -> None:
    """A tool is not started when the data folder has less free space than ARVA's reserve (ARVA_MIN_FREE_BYTES) plus
    the size of the job's input files: assemblers, read mapping and pangenome runs write outputs of that order or
    larger, and filling the disk would make other writes (database backups, logs) fail as well. This is a lower
    bound, not an estimate of the job's full output."""
    from app.services.capacity import fmt_bytes

    ids = job.input_raw_file_ids or []
    inputs = int(db.scalar(select(func.coalesce(func.sum(RawFile.size_bytes), 0)).where(RawFile.id.in_(ids)))
                 or 0) if ids else 0
    needed = get_settings().min_free_bytes + inputs
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        return
    if free < needed:
        raise JobFailure(f"Only {fmt_bytes(free)} is free in the ARVA data folder; this job needs at least "
                         f"{fmt_bytes(needed)} (the {fmt_bytes(needed - inputs)} reserve plus the size of its input "
                         "files) before it starts, so nothing was run. Free some space and run the job again.",
                         "insufficient_storage", free=fmt_bytes(free), needed=fmt_bytes(needed))


def _quietly(step: Callable[[], object], name: str) -> None:
    try:
        step()
    except Exception as exc:
        errorlog.record("job", "error", "job_cleanup_failed", params={"step": name}, exc=exc)


def run_job(
    job_id: str,
    body: Callable[[JobContext], None],
    on_failure: Callable[[JobContext, BaseException], None] | None = None,
) -> str:
    db = SessionLocal()
    token = None
    try:
        # Locked so that a cancellation of the queued job and its start cannot interleave.
        job = db.get(AnalysisJob, job_id, with_for_update=True)
        if job is None:
            raise LookupError(f"analysis job {job_id} not found")
        if job.status is not JobStatus.pending:
            db.rollback()
            return job.status.value
        # Jobs this one launches, and the log entries of its run, carry the correlation id of its request.
        job.correlation_id = job.correlation_id or errorlog.new_correlation_id()
        token = errorlog.correlation.set(job.correlation_id)
        storage = get_storage()
        log = JobLog(db, job)
        ctx = JobContext(db, job, storage, log)
        partial = (ctx.results_rel, ctx.processed_rel)
        started = time.monotonic()
        job.status = JobStatus.running
        job.started_at = now()
        log(f"Tool: {job.tool_name} {job.tool_version}" + (f" ({job.tool_path})" if job.tool_path else ""))
        log(f"Environment: Python {platform.python_version()}, {platform.system()} {platform.machine()}")
        log(f"Parameters: {json.dumps(job.parameters, sort_keys=True)}", flush=True)
        errorlog.info("job_started", f"{job.job_type} job started", component="job", job=job_ref(job),
                      tool={"name": job.tool_name, "version": job.tool_version})

        storage_ok = True
        try:
            if (problem := _storage_problem()) is not None:
                storage_ok = False
                path = problem.params["path"]
                raise JobFailure(f"The ARVA data folder {path} was not available when this job started (its external "
                                 "disk is not connected, or another disk is in its place), so nothing was written. "
                                 f"Connect the disk, start ARVA again and run the job again. ({problem})",
                                 "storage_unavailable", path=path)
            _ensure_space(db, job, storage.root)
            body(ctx)
            # Locked until the commit below, so a cancellation is either seen here or finds the job completed.
            if ctx.cancel_requested(lock=True):
                raise JobCancelled()
            job.status = JobStatus.completed
        except BaseException as exc:
            db.rollback()
            job = db.get(AnalysisJob, job_id)
            if job is None:
                errorlog.record("job", "warning", "job_record_gone", params={"job_id": job_id})
                if storage_ok:
                    _quietly(lambda: [storage.remove_tree(rel) for rel in partial], "remove_tree")
                if not isinstance(exc, Exception):
                    raise
                return "deleted"
            ctx.job = log.job = job
            job.error_detail = _detail(exc) if isinstance(exc, JobFailure | ToolExecutionError) else None
            if isinstance(exc, JobCancelled):
                job.error_message = None
                log(f"{cancellation_note(job)}; any running tool was stopped and partial outputs were removed")
            elif isinstance(exc, JobFailure):
                job.error_message = str(exc)
                log(f"ERROR: {exc}")
            elif isinstance(exc, ToolExecutionError):
                job.error_message = str(exc)
                log(f"ERROR: {exc}")
                if exc.stderr_tail:
                    log("Tool output (last lines):\n" + exc.stderr_tail.strip())
            else:
                job.error_message = f"{type(exc).__name__}: {exc}"
                log("ERROR: unexpected failure\n" + traceback.format_exc())
            if ctx.killed_tool and not isinstance(exc, JobCancelled):
                job.error_message, note = _with_memory_advice(job, ctx.killed_tool)
                job.error_detail = {"code": "out_of_memory", "params": {"tool": ctx.killed_tool}}
                log(note)
            if storage_ok and not _storage_usable():
                from app.services.locations import to_host

                storage_ok = False
                path = to_host(str(storage.root)) or str(storage.root)
                job.error_message = (f"The ARVA data folder {path} stopped being available while this job ran (was "
                                     "its disk disconnected?); its partial outputs could not be removed. Connect the "
                                     f"disk, start ARVA again and run the job again. ({job.error_message})")
                job.error_detail = {"code": "storage_lost", "params": {"path": path}}
                log(f"ERROR: {job.error_message}")
            # A failing clean-up step must not keep the job from being recorded as failed or cancelled.
            if storage_ok:
                for hook in ctx.before_cleanup:
                    _quietly(lambda h=hook, e=exc: h(e), "before_cleanup")
                for rel in partial:
                    _quietly(lambda r=rel: storage.remove_tree(r), "remove_tree")
            if on_failure is not None:
                _quietly(lambda e=exc: on_failure(ctx, e), "on_failure")
            job.status = JobStatus.cancelled if isinstance(exc, JobCancelled) else JobStatus.failed
            _log_end(job, exc)
            if not isinstance(exc, Exception):
                raise

        job.finished_at = now()
        job.duration_seconds = round(time.monotonic() - started, 3)
        log(f"Finished with status '{job.status.value}' in {job.duration_seconds:.2f}s")
        log.flush()
        errorlog.info("job_finished", f"{job.job_type} job finished with status {job.status.value}", component="job",
                      job=job_ref(job), duration_seconds=job.duration_seconds)
        if storage_ok:
            try:
                storage.write_text(f"logs/{job.id}.log", job.log_text or "")
            except OSError:
                pass  # the log stays in the database (job.log_text)
        if job.status is JobStatus.completed:
            for hook in ctx.after_commit:
                hook()
        return job.status.value
    finally:
        if token is not None:
            errorlog.correlation.reset(token)
        db.close()
        _batch_queue()


def _batch_queue() -> None:
    from app.services.batches import dispatch_quietly
    from app.tasks.worker_events import reconcile_quietly

    dispatch_quietly("job finished")
    reconcile_quietly("job finished")
