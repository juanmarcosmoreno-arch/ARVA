"""Chart data parsed from FastQC and fastp outputs that a completed job stored.

FastQC jobs since ARVA wrote fastqc_data.json carry it as an output; for older jobs the stored zip is
parsed on request. fastp's own fastp.json is parsed on request. Only files listed in the job's
outputs and inside its own results folder are read.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arva_tools.fastp import FastpAdapter
from arva_tools.fastqc import DATA_JSON, FastqcAdapter

from app.models import AnalysisJob, JobStatus
from app.services.jobs import FASTP_JOB, FASTQC_JOB
from app.storage import get_storage
from app.storage.local import StoragePathError


class QcDataError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def _require(job: AnalysisJob, job_type: str, tool: str) -> None:
    if job.job_type != job_type:
        raise QcDataError(404, f"Job {job.id} is a {job.job_type} job, not a {tool} job")
    if job.status is not JobStatus.completed:
        raise QcDataError(409, f"The {tool} job has not completed (status: {job.status.value})")


def _output(job: AnalysisJob, matches) -> Path | None:
    prefix = f"results/{job.project_id}/{job.sample_id or '_project'}/{job.id}/"
    storage = get_storage()
    for rel in job.output_paths or []:
        if not rel.startswith(prefix) or not matches(Path(rel).name):
            continue
        try:
            path = storage.resolve(rel)
        except StoragePathError:
            continue
        if path.is_file():
            return path
    return None


def fastqc_data(job: AnalysisJob) -> dict[str, Any]:
    _require(job, FASTQC_JOB, "FastQC")
    stored = _output(job, lambda name: name == DATA_JSON)
    if stored is not None:
        return {**json.loads(stored.read_text()), "source": DATA_JSON}
    archive = _output(job, lambda name: name.endswith("_fastqc.zip"))
    if archive is None:
        raise QcDataError(404, "This FastQC job has no stored data file (zip) on disk")
    try:
        return {**FastqcAdapter.read_data(archive), "source": archive.name}
    except ValueError as exc:
        raise QcDataError(422, f"FastQC's data could not be read: {exc}") from exc


def fastqc_summary(job: AnalysisJob) -> dict[str, Any] | None:
    """The compact figures stored with the job, or parsed from its outputs for jobs that predate them."""
    stored = (job.result_summary or {}).get("data_summary")
    if stored is not None:
        return stored
    try:
        return FastqcAdapter.summarize(fastqc_data(job))
    except QcDataError:
        return None


def fastp_data(job: AnalysisJob) -> dict[str, Any]:
    _require(job, FASTP_JOB, "fastp")
    report = _output(job, lambda name: name == "fastp.json")
    if report is None:
        raise QcDataError(404, "This fastp job has no fastp.json on disk")
    try:
        data = FastpAdapter.parse_data(report)
    except (ValueError, TypeError, AttributeError) as exc:
        raise QcDataError(422, f"fastp.json could not be read: {exc}") from exc
    return {**data, "threads": (job.parameters or {}).get("threads")}
