"""Deleting a project or a sample: refused while one of its jobs is queued or running, and followed by removal of the
derived outputs of the deleted scope (results/, processed/, checkpoints/, reports/). raw/ stays, as documented."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import errorlog
from app.models import AnalysisJob, JobStatus
from app.storage.local import get_storage

ACTIVE = (JobStatus.pending, JobStatus.running)


def active_jobs(db: Session, project_id: str, sample_id: str | None = None) -> int:
    q = select(func.count(AnalysisJob.id)).where(AnalysisJob.project_id == project_id,
                                                 AnalysisJob.status.in_(ACTIVE))
    if sample_id is not None:
        q = q.where(AnalysisJob.sample_id == sample_id)
    return db.scalar(q) or 0


def remove_outputs(project_id: str, sample_id: str | None = None) -> None:
    scope = f"{project_id}/{sample_id}" if sample_id else project_id
    storage = get_storage()
    for top in ("results", "processed", "checkpoints", "reports"):
        try:
            storage.remove_tree(f"{top}/{scope}")
        except OSError as exc:
            errorlog.record("api", "warning", "delete_outputs_failed", params={"folder": top}, exc=exc)
