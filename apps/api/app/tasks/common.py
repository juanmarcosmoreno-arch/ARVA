"""Shared lifecycle for every analysis job executed by the worker.

`run_job` marks the job running, records the environment, runs the job body,
and on any failure rolls back database changes, removes partial outputs and
records the reason. A job therefore ends either completed with all outputs
registered, or failed with none.
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
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus, RawFile
from app.storage import LocalStorage, get_storage


class JobFailure(Exception):
    """An expected failure with a clear, user-facing reason (no traceback)."""


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

    @property
    def _scope(self) -> str:
        s = self.job.sample
        return f"{s.project_id}/{s.id}/{self.job.id}"

    @property
    def results_rel(self) -> str:
        return f"results/{self._scope}"

    @property
    def processed_rel(self) -> str:
        return f"processed/{self._scope}"

    def path(self, rel: str) -> Path:
        return self.storage.resolve(rel)

    def input_files(self) -> list[RawFile]:
        files = []
        for file_id in self.job.input_raw_file_ids or []:
            f = self.db.get(RawFile, file_id)
            if f is None:
                raise JobFailure(f"input file {file_id} no longer exists")
            files.append(f)
        return files


def run_job(
    job_id: str,
    body: Callable[[JobContext], None],
    on_failure: Callable[[JobContext, BaseException], None] | None = None,
) -> str:
    db = SessionLocal()
    try:
        job = db.get(AnalysisJob, job_id)
        if job is None:
            raise LookupError(f"analysis job {job_id} not found")
        storage = get_storage()
        log = JobLog(db, job)
        ctx = JobContext(db, job, storage, log)
        started = time.monotonic()
        job.status = JobStatus.running
        job.started_at = now()
        log(f"Tool: {job.tool_name} {job.tool_version}" + (f" ({job.tool_path})" if job.tool_path else ""))
        log(f"Environment: Python {platform.python_version()}, {platform.system()} {platform.machine()}")
        log(f"Parameters: {json.dumps(job.parameters, sort_keys=True)}", flush=True)

        try:
            body(ctx)
            job.status = JobStatus.completed
        except BaseException as exc:
            db.rollback()
            job = db.get(AnalysisJob, job_id)
            ctx.job = log.job = job
            for rel in (ctx.results_rel, ctx.processed_rel):
                storage.remove_tree(rel)
            if isinstance(exc, JobFailure):
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
            if on_failure is not None:
                on_failure(ctx, exc)
            job.status = JobStatus.failed
            if not isinstance(exc, Exception):
                raise

        job.finished_at = now()
        job.duration_seconds = round(time.monotonic() - started, 3)
        log(f"Finished with status '{job.status.value}' in {job.duration_seconds:.2f}s")
        log.flush()
        storage.write_text(f"logs/{job.id}.log", job.log_text or "")
        if job.status is JobStatus.completed:
            for hook in ctx.after_commit:
                hook()
        return job.status.value
    finally:
        db.close()
