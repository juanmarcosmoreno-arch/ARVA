"""What the RQ worker (apps/workers/run_worker.py) keeps in the error log: a task that raised out of its job
lifecycle (run_job records ordinary failures itself), a work horse that died (killed by the system, most often for
lack of memory), and the worker itself stopping on an error."""
from __future__ import annotations

import os
import signal

from app.core import errorlog
from app.core.redaction import clip

_PREFIX = "arva-"


def _job(rq_job) -> dict:
    """The ARVA job behind an RQ task (its id is "arva-<job id>" or the database task's own id)."""
    rq_id = str(getattr(rq_job, "id", "") or "")
    return {"id": rq_id.removeprefix(_PREFIX), "rq_id": clip(rq_id, 80),
            "task": clip(str(getattr(rq_job, "func_name", "") or "?"), 120)}


def on_exception(rq_job, exc_type, exc_value, tb) -> bool:
    job = _job(rq_job)
    exc = exc_value if isinstance(exc_value, BaseException) else exc_type()
    if exc.__traceback__ is None and tb is not None:
        exc = exc.with_traceback(tb)
    errorlog.record("worker", "error", "worker_task_failed", params={"task": job["task"]}, exc=exc, job=job)
    return True


def on_work_horse_killed(rq_job, retpid: int, ret_val: int, rusage) -> None:
    """RQ's waitpid status of the work horse: the signal that killed it and its peak memory (ru_maxrss, KB on
    Linux)."""
    details: dict = {"pid": retpid}
    if os.WIFSIGNALED(ret_val):
        sig = os.WTERMSIG(ret_val)
        details["signal"] = signal.Signals(sig).name if sig in signal.valid_signals() else sig
        status = f"signal {details['signal']}"
    else:
        status = str(os.WEXITSTATUS(ret_val) if os.WIFEXITED(ret_val) else ret_val)
    if rusage is not None:
        details["max_rss_kb"] = getattr(rusage, "ru_maxrss", None)
    ref = _job(rq_job)
    errorlog.record("worker", "error", "worker_crashed", params={"status": status}, job=ref, details=details)
    from app.db.session import SessionLocal
    from app.services import jobs

    try:
        with SessionLocal() as db:
            jobs.end_killed(db, ref["id"], details.get("signal") if isinstance(details.get("signal"), str) else None)
    except Exception as exc:  # noqa: BLE001 - the worker goes on; the next reconciliation ends the job instead
        errorlog.record("worker", "error", "worker_reconcile_failed", exc=exc, job=ref)


def reconcile_quietly(source: str) -> None:
    """End the jobs no worker runs any more (services.jobs.reconcile_lost)."""
    from app.db.session import SessionLocal
    from app.services import jobs

    try:
        with SessionLocal() as db:
            if ended := jobs.reconcile_lost(db):
                errorlog.info("jobs_reconciled", f"{ended} lost job(s) ended ({source})", component="worker")
    except Exception as exc:  # noqa: BLE001 - must not stop the worker or fail the job that just ran
        errorlog.record("worker", "error", "worker_reconcile_failed", params={"source": source}, exc=exc)


def started(queue: str, worker_class: str) -> None:
    errorlog.info("worker_started", "Worker started", component="worker", queue=queue, worker_class=worker_class,
                  **errorlog.build())
    from app.services.batches import dispatch_quietly

    # Runs interrupted by a restart continue: lost tasks are ended and the queue launches what may start; then the
    # jobs outside batches that a restart lost are ended too.
    dispatch_quietly("worker started")
    reconcile_quietly("worker started")


def stopped(exc: BaseException) -> None:
    errorlog.record("worker", "error", "worker_stopped", exc=exc)
