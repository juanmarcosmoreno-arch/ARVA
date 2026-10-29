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
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from arva_tools import ToolExecutionError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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
            return self.db.scalar(query.with_for_update() if lock else query) is not None

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


def run_job(
    job_id: str,
    body: Callable[[JobContext], None],
    on_failure: Callable[[JobContext, BaseException], None] | None = None,
) -> str:
    db = SessionLocal()
    try:
        # Locked so that a cancellation of the queued job and its start cannot interleave.
        job = db.get(AnalysisJob, job_id, with_for_update=True)
        if job is None:
            raise LookupError(f"analysis job {job_id} not found")
        if job.status is not JobStatus.pending:
            db.rollback()
            return job.status.value
        storage = get_storage()
        log = JobLog(db, job)
        ctx = JobContext(db, job, storage, log)
        started = time.monotonic()
        job.status = JobStatus.running
        job.started_at = now()
        log(f"Tool: {job.tool_name} {job.tool_version}" + (f" ({job.tool_path})" if job.tool_path else ""))
        log(f"Environment: Python {platform.python_version()}, {platform.system()} {platform.machine()}")
        log(f"Parameters: {json.dumps(job.parameters, sort_keys=True)}", flush=True)

        storage_ok = True
        try:
            if (problem := _storage_problem()) is not None:
                storage_ok = False
                path = problem.params["path"]
                raise JobFailure(f"The ARVA data folder {path} was not available when this job started (its external "
                                 "disk is not connected, or another disk is in its place), so nothing was written. "
                                 f"Connect the disk, start ARVA again and run the job again. ({problem})",
                                 "storage_unavailable", path=path)
            body(ctx)
            # Locked until the commit below, so a cancellation is either seen here or finds the job completed.
            if ctx.cancel_requested(lock=True):
                raise JobCancelled()
            job.status = JobStatus.completed
        except BaseException as exc:
            db.rollback()
            job = db.get(AnalysisJob, job_id)
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
            if storage_ok:
                for hook in ctx.before_cleanup:
                    hook(exc)
                for rel in (ctx.results_rel, ctx.processed_rel):
                    storage.remove_tree(rel)
            if on_failure is not None:
                on_failure(ctx, exc)
            job.status = JobStatus.cancelled if isinstance(exc, JobCancelled) else JobStatus.failed
            if not isinstance(exc, Exception):
                raise

        job.finished_at = now()
        job.duration_seconds = round(time.monotonic() - started, 3)
        log(f"Finished with status '{job.status.value}' in {job.duration_seconds:.2f}s")
        log.flush()
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
        db.close()
