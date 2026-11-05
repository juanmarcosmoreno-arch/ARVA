"""Register the genome FASTA of every sample of a project at once (the per-sample "Register a genome FASTA" dialog,
for a whole batch). Each sample gets the same registration job as the dialog creates; nothing else is decided here."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, Project, RawFile, Sample
from app.models.analysis_job import JobStatus
from app.models.raw_file import FileOrigin
from app.services.jobs import IMPORT_ASSEMBLY_JOB, create_assembly_import_job
from app.services.quast import REFERENCE_FORMATS

LIVE = (JobStatus.pending, JobStatus.running, JobStatus.completed)


def _candidates(sample: Sample) -> list[RawFile]:
    """The sample's own FASTA files (uploaded or imported, valid): ARVA's derived files are its own outputs."""
    return sorted((f for f in sample.raw_files if f.file_format in REFERENCE_FORMATS and f.is_valid
                   and f.origin is not FileOrigin.derived), key=lambda f: f.original_filename)


def _registered(db: Session, sample: Sample) -> set[str]:
    """Checksums of FASTA files already registered (or being registered) in this sample."""
    rows = db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample.id,
                                                AnalysisJob.job_type == IMPORT_ASSEMBLY_JOB,
                                                AnalysisJob.status.in_(LIVE)))
    return {(j.parameters or {}).get("fasta_sha256") for j in rows} - {None}


def plan(db: Session, project: Project) -> list[dict[str, Any]]:
    """Per sample: the FASTA that would be registered and why a sample would be skipped (no FASTA, several FASTA
    files, or that FASTA already registered)."""
    out = []
    for sample in sorted(project.samples, key=lambda s: s.sample_code):
        fastas = _candidates(sample)
        done = _registered(db, sample)
        pending = [f for f in fastas if f.checksum_sha256 not in done]
        if not fastas:
            status, chosen = "no_fasta", None
        elif not pending:
            status, chosen = "registered", None
        elif len(pending) > 1:
            status, chosen = "several_fasta", None
        else:
            status, chosen = "ready", pending[0]
        out.append({"sample_id": sample.id, "sample_code": sample.sample_code, "status": status,
                    "file_id": chosen.id if chosen else None, "file_name": chosen.original_filename if chosen else None,
                    "fasta_files": len(fastas)})
    return out


def register_all(db: Session, project: Project, source: str, draft: dict | None,
                 sample_ids: list[str] | None) -> dict[str, Any]:
    """Start one registration job per ready sample (all of them, or those in `sample_ids`)."""
    wanted = set(sample_ids) if sample_ids is not None else None
    started, skipped = [], []
    by_id = {s.id: s for s in project.samples}
    for row in plan(db, project):
        if wanted is not None and row["sample_id"] not in wanted:
            continue
        if row["status"] != "ready":
            skipped.append({"sample_id": row["sample_id"], "sample_code": row["sample_code"], "status": row["status"]})
            continue
        fasta = db.get(RawFile, row["file_id"])
        job = create_assembly_import_job(db, by_id[row["sample_id"]], fasta, source, draft)
        started.append({"sample_id": row["sample_id"], "sample_code": row["sample_code"], "job_id": job.id})
    return {"started": started, "skipped": skipped}
