"""API request/response schemas."""
import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import FileFormat, FileOrigin, JobStatus, SequencingTechnology


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
    origin: FileOrigin
    parent_file_id: str | None
    produced_by_job_id: str | None
    description: str | None


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
    commands: list[list[str]] | None = None
    tool_path: str | None = None
    result_summary: dict[str, Any] | None = None
    parent_job_id: str | None = None


class AnalysisJobDetail(AnalysisJobRead):
    qc_results: list[QCResultRead] = []


# --- External tools -------------------------------------------------------------

class ToolRead(BaseModel):
    id: str
    name: str
    description: str
    homepage: str
    license: str
    citation: str
    citation_url: str
    categories: list[str]
    input_formats: list[str]
    output_formats: list[str]
    min_version: str
    tested_versions: list[str]
    install: dict[str, str]
    status: str
    path: str | None
    version: str | None
    version_validated: bool
    message: str


class FilesRequest(BaseModel):
    raw_file_ids: list[str] = Field(min_length=1)


class FastpParamsIn(BaseModel):
    adapter_trimming: bool = True
    detect_adapter_for_pe: bool = True
    quality_filtering: bool = True
    qualified_quality_phred: int = Field(default=15, ge=0, le=93)
    unqualified_percent_limit: int = Field(default=40, ge=0, le=100)
    n_base_limit: int = Field(default=5, ge=0)
    average_qual: int = Field(default=0, ge=0, le=93)
    length_filtering: bool = True
    length_required: int = Field(default=15, ge=0)
    cut_front: bool = False
    cut_tail: bool = False
    cut_window_size: int = Field(default=4, ge=1, le=1000)
    cut_mean_quality: int = Field(default=20, ge=1, le=36)
    poly_g: Literal["auto", "force", "disable"] = "auto"
    dedup: bool = False


class FastpRequest(BaseModel):
    read1_file_id: str
    read2_file_id: str | None = None
    params: FastpParamsIn = FastpParamsIn()


class FiltlongParamsIn(BaseModel):
    min_length: int | None = Field(default=None, ge=1)
    max_length: int | None = Field(default=None, ge=1)
    min_mean_q: float | None = Field(default=None, ge=0, lt=100)
    min_window_q: float | None = Field(default=None, ge=0, lt=100)
    keep_percent: float | None = Field(default=None, gt=0, le=100)
    target_bases: int | None = Field(default=None, ge=1)
    length_weight: float = Field(default=1.0, ge=0)
    mean_q_weight: float = Field(default=1.0, ge=0)
    window_q_weight: float = Field(default=1.0, ge=0)
    window_size: int = Field(default=250, ge=1)


class FiltlongRequest(BaseModel):
    file_id: str
    params: FiltlongParamsIn


class CrossCheckRow(BaseModel):
    metric: str
    arva: float | None
    tool: float | None
    tolerance: float
    agrees: bool | None


class CrossCheckRead(BaseModel):
    raw_file_id: str
    tool: str
    tool_version: str | None
    arva_job_id: str | None
    tool_job_id: str | None
    rows: list[CrossCheckRow]
    all_agree: bool | None
    note: str


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
    code: Literal["duplicate", "too_large", "insufficient_storage"]


class UploadResult(BaseModel):
    files: list[RawFileRead]
    rejected: list[UploadRejection]


# --- Storage capacity and server-folder import ----------------------------------

class StorageCapacityRead(BaseModel):
    storage_root: str
    free_bytes: int
    total_bytes: int
    min_free_bytes: int
    available_for_data_bytes: int
    upload_overhead_factor: Literal[1, 2] = Field(
        description="2 when browser uploads are buffered on the same disk and so need twice their size while received"
    )


class ImportRootRead(BaseModel):
    index: int
    name: str
    path: str
    exists: bool


class ImportEntryRead(BaseModel):
    name: str
    path: str
    type: Literal["dir", "file"]
    size_bytes: int | None
    kind: Literal["fastq", "fasta", "pod5", "other"]
    modified_at: dt.datetime


class ImportListingRead(BaseModel):
    root: int
    path: str
    parent: str | None
    entries: list[ImportEntryRead]
    truncated: bool
    unsupported_names: int = Field(description="Entries hidden because their names are not valid UTF-8")


class ServerImportRequest(BaseModel):
    root: int = Field(ge=0, description="Index of the import folder (GET /imports/roots)")
    paths: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        min_length=1, max_length=500, description="File paths relative to the import folder"
    )


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
