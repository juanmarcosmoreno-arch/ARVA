"""API request/response schemas."""
import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models import (
    FileFormat,
    FileOrigin,
    JobStatus,
    MetadataFileKind,
    MetadataImportMode,
    SequencingTechnology,
)


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
    header_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Summary of the first read headers (arva_core.header_meta); suggestions only, never user metadata",
    )

    @field_serializer("header_metadata")
    def _without_fingerprint(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        # The read-name fingerprint only serves the R1/R2 check of /samples/{id}/header-summary.
        return None if value is None else {k: v for k, v in value.items() if k != "mate_fingerprint"}


Confidence = Literal["high", "medium", "low", "none"]


class HeaderTechnologySuggestion(BaseModel):
    value: SequencingTechnology | None
    confidence: Confidence
    basis: Literal["single_platform", "short_and_long_reads", "conflicting_platforms", "no_evidence"]
    platforms: list[str]
    files_considered: int
    files_with_evidence: int


class HeaderFileSummary(BaseModel):
    file_id: str
    name: str
    analysed: bool = Field(description="False until the file's read headers have been summarised")
    platform: Literal["illumina", "nanopore", "pacbio"] | None
    confidence: Confidence
    format: str | None = Field(description="Most frequent header format among the headers read")


class MateCheck(BaseModel):
    r1_file_id: str
    r2_file_id: str
    looks_like_pair: bool | None
    matched: int
    compared: int
    note: Literal["same_read_names", "different_read_names", "mate_markers_conflict", "not_analysed", "nothing_compared"]


class HeaderSummaryRead(BaseModel):
    suggested_technology: HeaderTechnologySuggestion
    per_file: list[HeaderFileSummary]
    mate_check: list[MateCheck]
    user_technology: SequencingTechnology
    agrees: bool | None = Field(
        description="Whether the suggestion matches the sample's technology; null when either is unknown, or when the "
        "sample is hybrid and only some files carry platform evidence"
    )


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
    project_id: str
    sample_id: str | None = Field(description="None for project-level jobs such as the MultiQC report")
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
    reason: str | None = None


class LibraryRead(BaseModel):
    id: str
    name: str
    homepage: str
    license: str
    citation: str
    citation_url: str
    required_version: str
    install: str = Field(description="Command to run in ARVA's Python environment; ARVA never installs it")
    status: Literal["available", "not_installed"]
    version: str | None
    companion_versions: dict[str, str | None]
    version_validated: bool


class FilesRequest(BaseModel):
    raw_file_ids: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=1000)


class NanoplotRequest(FilesRequest):
    long_reads_confirmed: bool = Field(
        default=False,
        description="The user confirms that the files hold long reads; required unless the sample's "
        "sequencing technology is nanopore or pacbio.",
    )


FASTP_INT_MAX = 2**31 - 1
AdapterSequence = Annotated[str, Field(pattern=r"^[ACGT]{4,200}$", description="4–200 bases of A, C, G, T")]


class FastpParamsIn(BaseModel):
    adapter_trimming: bool = True
    detect_adapter_for_pe: bool = True
    adapter_sequence: AdapterSequence | None = Field(
        default=None, description="Read-1 adapter instead of fastp's detection (paired end: used where mates do not overlap)"
    )
    adapter_sequence_r2: AdapterSequence | None = Field(default=None, description="Read-2 adapter (paired end only)")
    quality_filtering: bool = True
    qualified_quality_phred: int = Field(default=15, ge=0, le=93)
    unqualified_percent_limit: int = Field(default=40, ge=0, le=100)
    n_base_limit: int = Field(default=5, ge=0)
    average_qual: int = Field(default=0, ge=0, le=93)
    low_complexity_filter: bool = False
    complexity_threshold: int = Field(default=30, ge=0, le=100)
    length_filtering: bool = True
    length_required: int = Field(default=15, ge=0)
    length_limit: int = Field(
        default=0, ge=0, le=FASTP_INT_MAX,
        description="Discard reads longer than this after trimming (0 = off); a pair goes when either mate does",
    )
    trim_front1: int = Field(default=0, ge=0, le=30)
    trim_tail1: int = Field(default=0, ge=0, le=100)
    max_len1: int = Field(default=0, ge=0, le=FASTP_INT_MAX, description="Trim read 1 to this length (0 = off)")
    trim_front2: int | None = Field(default=None, ge=0, le=30, description="Paired end only; unset follows read 1")
    trim_tail2: int | None = Field(default=None, ge=0, le=100, description="Paired end only; unset follows read 1")
    max_len2: int | None = Field(
        default=None, ge=0, le=FASTP_INT_MAX, description="Paired end only; unset follows read 1"
    )
    cut_front: bool = False
    cut_tail: bool = False
    cut_window_size: int = Field(default=4, ge=1, le=1000)
    cut_mean_quality: int = Field(default=20, ge=1, le=30)
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
    genome_size_bp: int | None = Field(
        default=None, ge=1, le=10_000_000_000,
        description="With target_coverage_x: ARVA sets target_bases = round(target_coverage_x × genome_size_bp)",
    )
    target_coverage_x: float | None = Field(default=None, gt=0, le=100_000)


MultiqcModule = Literal["fastqc", "fastp", "seqkit", "filtlong"]


class MultiqcRequest(BaseModel):
    sample_ids: list[Annotated[str, Field(max_length=64)]] | None = Field(
        default=None, min_length=1, max_length=10_000, description="Samples to include; every sample of the project if omitted"
    )
    include_derived: bool = Field(
        default=False, description="Also use results computed on derived (filtered) files"
    )


class MultiqcPlannedInput(BaseModel):
    module: MultiqcModule
    name: str = Field(description="Sample name in the report: '<sample ID> <file>'")
    sample_id: str
    sample_code: str
    job_id: str
    tool_name: str
    tool_version: str
    finished_at: dt.datetime | None
    file_ids: list[str]
    file_names: list[str]
    output_path: str


class MultiqcExclusion(BaseModel):
    sample_id: str
    sample_code: str
    reason: Literal["no_outputs", "derived_input", "filtlong_without_target", "output_missing", "input_missing",
                    "input_invalid", "input_not_validated"]
    module: MultiqcModule | None
    job_id: str | None
    file_names: list[str]


class MultiqcPlanRead(BaseModel):
    selection_rule: str
    modules: list[MultiqcModule]
    sample_ids: list[str]
    include_derived: bool
    inputs: list[MultiqcPlannedInput]
    excluded: list[MultiqcExclusion]


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


# --- Chart data from FastQC (fastqc_data.txt) and fastp (fastp.json) ----------------

class FastqcPosition(BaseModel):
    label: str = Field(description="FastQC's label: 'a' or 'a-b'")
    start: int = Field(description="1-based, inclusive")
    end: int = Field(description="1-based, inclusive")


class FastqcAdapterSeries(BaseModel):
    name: str
    percent: list[float] = Field(
        description="Cumulative % of reads in which the adapter was seen at or before each position; "
        "a binned position holds the mean over its positions"
    )


class FastqcAdapterContent(BaseModel):
    status: str = Field(description="FastQC heuristics: WARN above 5 %, FAIL above 10 % at any position")
    positions: list[FastqcPosition]
    adapters: list[FastqcAdapterSeries]


class FastqcDuplicationBin(BaseModel):
    level: str = Field(description="Copies per sequence: 1–9, >10 (10–50), >50 (51–100), … >10k+ (over 10,000)")
    percent_of_total: float


class FastqcDuplication(BaseModel):
    status: str
    total_deduplicated_percent: float = Field(
        description="% of reads that would remain if deduplicated (FastQC's 'Total Deduplicated Percentage')"
    )
    duplicate_percent: float = Field(description="100 − total_deduplicated_percent")
    bins: list[FastqcDuplicationBin]


class FastqcOverrepresentedRow(BaseModel):
    sequence: str
    count: int
    percent: float
    possible_source: str


class FastqcOverrepresented(BaseModel):
    status: str
    total: int = Field(description="Sequences FastQC listed")
    rows: list[FastqcOverrepresentedRow] = Field(description="At most the first 20, in FastQC's order")
    every_read_listed: bool = Field(description="FastQC listed every read of the file (fewer than 1,000 reads)")


class FastqcModuleStatus(BaseModel):
    module: str
    status: str


class FastqcDataRead(BaseModel):
    fastqc_version: str | None
    total_sequences: int | None
    max_read_length: int | None
    modules: list[FastqcModuleStatus]
    adapter_content: FastqcAdapterContent | None
    duplication: FastqcDuplication | None
    overrepresented_sequences: FastqcOverrepresented | None
    unrecognised: list[str] = Field(description="Modules whose columns ARVA does not recognise")
    source: str = Field(description="fastqc_data.json written by the job, or the job's zip parsed on request")


class FastpCurves(BaseModel):
    total_reads: int | None
    total_cycles: int | None
    quality: dict[str, list[float]] = Field(description="Mean Phred score per cycle: mean, A, T, C, G")
    content: dict[str, list[float]] = Field(description="Fraction (0–1) of bases per cycle: A, T, C, G, GC, N")


class FastpAdapterCount(BaseModel):
    sequence: str = Field(description="Adapter sequence, or 'others' for those under 1 % of the trimmed reads")
    count: int


class FastpAdapterCutting(BaseModel):
    adapter_trimmed_reads: int | None
    adapter_trimmed_bases: int | None
    read1_adapter_sequence: str | None
    read2_adapter_sequence: str | None
    read1_adapter_counts: list[FastpAdapterCount]
    read2_adapter_counts: list[FastpAdapterCount]


class FastpInsertSize(BaseModel):
    peak: int | None = Field(description="None when no pair overlapped")
    unknown: int = Field(description="Pairs without a detected overlap, or with inserts ≥ insert_size_max")
    overlapping_pairs: int
    evaluated_pairs: int = Field(description="Pairs read by fastp's worker thread 0, the only one that measures inserts")
    histogram: list[int] = Field(description="Pairs per insert size 0 … insert_size_max − 1")
    histogram_percent: list[float] = Field(description="histogram ÷ evaluated_pairs × 100")
    unknown_percent: float | None
    insert_size_max: int


class FastpDataRead(BaseModel):
    fastp_version: str | None
    sequencing: str | None
    reads: dict[str, dict[str, FastpCurves]] = Field(description="read1/read2 → before/after filtering")
    adapter_cutting: FastpAdapterCutting | None
    duplication_rate: float | None = Field(description="fastp's estimate, a fraction (0–1)")
    insert_size: FastpInsertSize | None
    threads: int | None = Field(description="--thread of the run; the insert-size estimate depends on it")


class QcOverviewFile(BaseModel):
    file_id: str
    filename: str
    total_bases: int


class QcOverviewFiltering(BaseModel):
    job_id: str
    tool_name: str
    tool_version: str
    finished_at: dt.datetime | None
    runs: int = Field(description="Completed filtering runs of the sample; the latest one is described")
    input_files: list[str]
    output_files: list[str]
    reads_kept_percent: float | None = Field(
        description="Reads of the outputs ÷ reads of the inputs × 100, both from ARVA statistics; null until both exist"
    )
    bases_kept_percent: float | None


class QcOverviewFastqc(BaseModel):
    files: int = Field(description="Imported FASTQ files with a completed FastQC report (0: FastQC not run)")
    files_total: int
    pass_count: int = Field(description="FastQC heuristics, summed over the latest report of each file")
    warn_count: int
    fail_count: int


class QcOverviewSeqkit(BaseModel):
    status: Literal["agree", "disagree", "partial", "not_run"]
    files_checked: int
    files_total: int
    differing_metrics: list[str]


class QcOverviewRow(BaseModel):
    sample_id: str
    sample_code: str
    sequencing_technology: SequencingTechnology
    imported_files: int
    derived_files: int
    imported_read_files: int = Field(description="Imported FASTQ/FASTA files (POD5 and unrecognised files excluded)")
    imported_read_files_with_stats: int
    stats_tool_versions: list[str] = Field(description="arva-core versions of the statistics used")
    total_reads: int | None = Field(description="Sum over imported read files; null unless every one has statistics")
    total_bases: int | None
    largest_file: QcOverviewFile | None = Field(description="Imported read file with the most bases")
    n50: int | None = Field(description="N50 of the largest imported read file (ARVA)")
    mean_read_quality: float | None = Field(
        description="Arithmetic mean of per-read qualities of the largest imported read file (ARVA)"
    )
    q30_percent: float | None = Field(description="Bases ≥ Q30, pooled over the imported FASTQ files")
    gc_percent: float | None = Field(description="G+C of unambiguous bases, pooled over the imported read files")
    expected_genome_size_bp: int | None
    genome_size_status: Literal["given", "not_given", "inconsistent"] | None = Field(
        description="Whether every imported read file's statistics used the same user-supplied genome size"
    )
    estimated_depth: float | None = Field(description="total_bases ÷ expected_genome_size_bp")
    filtering: QcOverviewFiltering | None
    fastqc: QcOverviewFastqc
    seqkit: QcOverviewSeqkit


class QcOverviewRead(BaseModel):
    project_id: str
    rows: list[QcOverviewRow]


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


# --- Sample metadata tables (CSV / .xlsx) -----------------------------------------

MetadataAction = Literal["create", "update", "unchanged", "error"]


class MetadataFileInfo(BaseModel):
    name: str
    sha256: str
    kind: MetadataFileKind
    encoding: str | None
    delimiter: str | None
    sheet: str | None
    sheets: list[str]
    header_row: int


class MetadataColumn(BaseModel):
    header: str
    field: str = Field(description="ARVA field, 'custom' (kept in custom_metadata) or 'ignore'")
    suggested_field: str = Field(description="What ARVA suggests from the header name alone")


class MetadataChange(BaseModel):
    field: str
    key: str | None = Field(default=None, description="custom_metadata key when field is 'custom_metadata'")
    old: str | None
    new: str | None


class MetadataMessage(BaseModel):
    code: str | None = Field(description="Stable identifier the interface translates (metadata.msg.<code>); null for free text")
    params: dict[str, str | int] = Field(description="Values for the {placeholders} of the translated text")
    text: str = Field(description="The message in English")


class MetadataRowPreview(BaseModel):
    row: int = Field(description="Row number as a spreadsheet shows it")
    sample_code: str | None
    action: MetadataAction
    sample_id: str | None = None
    matched_sample_code: str | None = None
    matched_by: Literal["exact", "case_insensitive"] | None = None
    changes: list[MetadataChange]
    errors: list[MetadataMessage]
    warnings: list[MetadataMessage]


class MetadataCounts(BaseModel):
    rows: int
    create: int
    update: int
    unchanged: int
    error: int


class MetadataPreviewRead(BaseModel):
    file: MetadataFileInfo
    columns: list[MetadataColumn]
    fields: list[str]
    rows: list[MetadataRowPreview]
    warnings: list[MetadataMessage]
    errors: list[MetadataMessage] = Field(description="Problems that block every row, e.g. no sample_code column")
    counts: MetadataCounts
    date_order: Literal["DMY", "MDY"] | None
    date_order_source: Literal["user", "header"] | None
    ambiguous_dates: int


class MetadataImportRead(ORMModel):
    id: str
    project_id: str
    filename: str
    sha256: str
    kind: MetadataFileKind
    sheet: str | None
    encoding: str | None
    delimiter: str | None
    header_row: int
    mapping: dict[str, str]
    date_order: str | None
    mode: MetadataImportMode
    created_count: int
    updated_count: int
    unchanged_count: int
    skipped_count: int
    created_at: dt.datetime


class MetadataSkippedRow(BaseModel):
    row: int
    sample_code: str | None
    reasons: list[MetadataMessage]


class MetadataApplyRead(BaseModel):
    record: MetadataImportRead
    skipped: list[MetadataSkippedRow]


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
