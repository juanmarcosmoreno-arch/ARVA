"""API request/response schemas."""
import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import FileFormat, JobStatus, SequencingTechnology


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Projects -----------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    institution: str | None = Field(default=None, max_length=255)
    researcher: str | None = Field(default=None, max_length=255)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    institution: str | None = Field(default=None, max_length=255)
    researcher: str | None = Field(default=None, max_length=255)


class ProjectRead(ORMModel):
    id: str
    name: str
    description: str | None
    institution: str | None
    researcher: str | None
    is_demo: bool
    created_at: dt.datetime
    updated_at: dt.datetime
    sample_count: int = 0


# --- Samples ------------------------------------------------------------------

class SampleBase(BaseModel):
    sample_code: str = Field(min_length=1, max_length=255)
    organism: str | None = Field(default=None, max_length=255)
    expected_species: str | None = Field(default=None, max_length=255)
    sample_type: str | None = Field(default=None, max_length=100)
    host: str | None = Field(default=None, max_length=255)
    geographic_origin: str | None = Field(default=None, max_length=255)
    collection_date: dt.date | None = None
    sequencing_technology: SequencingTechnology = SequencingTechnology.unknown
    sequencing_run: str | None = Field(default=None, max_length=255)
    researcher: str | None = Field(default=None, max_length=255)
    institution: str | None = Field(default=None, max_length=255)
    description: str | None = None
    notes: str | None = None
    custom_metadata: dict[str, Any] | None = None


class SampleCreate(SampleBase):
    pass


class SampleUpdate(BaseModel):
    sample_code: str | None = Field(default=None, min_length=1, max_length=255)
    organism: str | None = None
    expected_species: str | None = None
    sample_type: str | None = None
    host: str | None = None
    geographic_origin: str | None = None
    collection_date: dt.date | None = None
    sequencing_technology: SequencingTechnology | None = None
    sequencing_run: str | None = None
    researcher: str | None = None
    institution: str | None = None
    description: str | None = None
    notes: str | None = None
    custom_metadata: dict[str, Any] | None = None


class SampleRead(ORMModel, SampleBase):
    id: str
    project_id: str
    created_at: dt.datetime
    updated_at: dt.datetime
    file_count: int = 0
    project_name: str | None = None


# --- Raw files ----------------------------------------------------------------

class RawFileRead(ORMModel):
    id: str
    sample_id: str
    original_filename: str
    file_format: FileFormat
    read_mate: str | None
    size_bytes: int
    checksum_sha256: str | None
    is_valid: bool
    validation_message: str | None
    uploaded_at: dt.datetime


# --- Analysis jobs / QC -------------------------------------------------------

class QCResultRead(ORMModel):
    id: str
    analysis_job_id: str
    raw_file_id: str
    read_count: int
    total_bases: int
    mean_length: float
    n50: int
    gc_percent: float
    mean_quality: float | None
    metrics: dict[str, Any]
    created_at: dt.datetime


class AnalysisJobRead(ORMModel):
    id: str
    sample_id: str
    job_type: str
    tool_name: str
    tool_version: str
    database_name: str | None
    database_version: str | None
    parameters: dict[str, Any] | None
    input_raw_file_ids: list[str] | None
    output_paths: list[str] | None
    status: JobStatus
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    duration_seconds: float | None
    log_text: str | None
    error_message: str | None
    created_at: dt.datetime


class AnalysisJobDetail(AnalysisJobRead):
    qc_results: list[QCResultRead] = []


class SequenceStatsRequest(BaseModel):
    raw_file_ids: list[str] | None = Field(
        default=None,
        description="Files to analyse. Defaults to every FASTQ/FASTA file of the sample.",
    )
    length_bins: int = Field(default=50, ge=5, le=500)
    expected_genome_size_bp: int | None = Field(
        default=None,
        gt=0,
        description="If given, an approximate sequencing depth is reported (total bases / genome size).",
    )


class UploadRejection(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    files: list[RawFileRead]
    rejected: list[UploadRejection]


# --- Dashboard ----------------------------------------------------------------

class DashboardSummary(BaseModel):
    project_count: int
    sample_count: int
    raw_file_count: int
    total_raw_bytes: int
    jobs_running: int
    jobs_completed: int
    jobs_failed: int
    storage_used_bytes: int
    recent_jobs: list[AnalysisJobRead]
    recent_projects: list[ProjectRead]
