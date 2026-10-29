"""API request/response schemas."""
import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.models import (
    AssemblyMode,
    DatabaseOrigin,
    DatabaseStatus,
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

class CodedMessage(BaseModel):
    """A stable code and its parameters for an English message, so the interface can show it translated."""
    code: str
    params: dict[str, str | int | float] = {}


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
    validation_detail: CodedMessage | None = None
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


class JobProgress(BaseModel):
    tool: str
    stage: str | None = Field(description="The tool's own name for the stage it last announced")
    stage_index: int | None = Field(description="1-based position of that stage among the stages seen so far")
    stages_total: int | None = Field(description="Stages this run is expected to go through")
    stages: list[str] = Field(description="The stages expected for this run, in order")
    started_at: dt.datetime | None
    stage_started_at: dt.datetime | None = Field(description="When ARVA saw the stage start in the tool's log")
    updated_at: dt.datetime | None
    elapsed_seconds: float | None = Field(description="Seconds since the tool started, at updated_at")
    finished: bool = Field(default=False, description="True once the tool has exited")


class JobCheckpoint(BaseModel):
    """A stopped Flye run's work folder, kept so that Flye's own --resume can continue it (not a result)."""
    tool: str
    tool_version: str = Field(description="The version that wrote the folder; resuming needs the same one")
    path: str = Field(description="Storage-relative folder")
    reason: Literal["cancelled", "time_limit", "stopped"] = Field(
        description="Why the run stopped: cancelled by the user, the time limit, or killed from outside (a signal, "
                    "the system running out of memory)")
    resume_stage: str = Field(description="The stage Flye reruns (its folder from the interrupted run was removed)")
    completed_stages: list[str]
    stages: list[str] = Field(description="Every stage of the run")
    size_bytes: int
    kept_at: dt.datetime


class AnalysisJobRead(ORMModel):
    id: str
    project_id: str
    sample_id: str | None = Field(description="None for project-level jobs such as the MultiQC report")
    job_type: str
    tool_name: str
    tool_version: str
    database_name: str | None
    database_version: str | None
    database_key: str | None = None
    database_kind: str | None = None
    database_version_source: str | None = Field(default=None, description="file, declared or checksum")
    database_checksum: str | None = Field(default=None, description="Content checksum of the database the job read "
                                          "(None when only a quick verification had been made)")
    database_path: str | None = None
    reference_database_id: str | None = None
    parameters: dict[str, Any] | None
    input_raw_file_ids: list[str] | None
    output_paths: list[str] | None
    status: JobStatus
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    duration_seconds: float | None
    log_text: str | None
    error_message: str | None
    error_detail: CodedMessage | None = None
    created_at: dt.datetime
    commands: list[list[str]] | None = None
    tool_path: str | None = None
    result_summary: dict[str, Any] | None = None
    parent_job_id: str | None = None
    progress: JobProgress | None = Field(default=None, description="Live monitoring of a long tool run (e.g. Flye)")
    cancel_requested_at: dt.datetime | None = Field(
        default=None, description="When cancelling was asked; a running job stays 'running' until the worker stops it")
    checkpoint: JobCheckpoint | None = None
    resources: dict[str, Any] | None = Field(
        default=None, description="The threads, memory limit and CPU priority ARVA gave the job (performance profile), "
        "with the computer it ran on; None for jobs ARVA runs in its own process")


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
    reason_params: dict[str, str] = {}


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


FlyeReadType = Literal["nano-raw", "nano-corr", "nano-hq", "pacbio-raw", "pacbio-corr", "pacbio-hifi"]
GenomeSizeBasis = Literal["entered", "expected_genome_size", "reads_over_depth"]


class FlyeParamsIn(BaseModel):
    read_type: FlyeReadType = Field(description="Flye's read-type option; it selects Flye's error model")
    genome_size_bp: int | None = Field(default=None, ge=1_000, le=10_000_000_000, description="Passed as --genome-size")
    genome_size_basis: GenomeSizeBasis | None = Field(
        default=None,
        description="Where the genome size comes from: typed by the user, the sample's expected genome size, or "
        "total read bases ÷ assumed_depth_x (both are checked against the stored values)",
    )
    assumed_depth_x: float | None = Field(default=None, gt=0, le=100_000)
    iterations: int = Field(default=1, ge=0, le=10, description="Polishing iterations (0 = no polishing)")
    min_overlap: int | None = Field(default=None, ge=1_000, le=10_000, description="Unset: Flye derives it from read N90")
    asm_coverage: int | None = Field(default=None, ge=1, le=100_000,
                                     description="Use only the longest reads up to this coverage for disjointigs")
    read_error: float | None = Field(default=None, gt=0, lt=1, description="Expected read error rate (fraction)")
    meta: bool = False
    keep_haplotypes: bool = False
    no_alt_contigs: bool = False
    scaffold: bool = False
    threads: int | None = Field(default=None, ge=1, le=128, description="Capped at the server's thread limit")


class FlyeRequest(BaseModel):
    raw_file_ids: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=100)
    params: FlyeParamsIn
    long_reads_confirmed: bool = Field(
        default=False,
        description="The user confirms that the files hold long reads; required unless the sample's sequencing "
        "technology is nanopore, pacbio or hybrid",
    )


class FlyePreviewRequest(BaseModel):
    raw_file_ids: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=100)
    assumed_depth_x: float | None = Field(default=None, gt=0, le=100_000,
                                          description="Estimate the genome size as total read bases ÷ this depth")


FileId = Annotated[str, Field(max_length=64)]
SpadesMode = Literal["isolate", "careful", "standard"]
UnicyclerBridging = Literal["conservative", "normal", "bold"]


class ShortReadInputsIn(BaseModel):
    """Files by role. Paired-end reads need both R1 and R2; SPAdes also takes unpaired reads, alone or with pairs."""
    model_config = ConfigDict(extra="forbid")

    r1_file_id: FileId | None = None
    r2_file_id: FileId | None = None
    unpaired_file_id: FileId | None = None

    def roles(self) -> dict[str, str | None]:
        return {"r1": self.r1_file_id, "r2": self.r2_file_id, "unpaired": self.unpaired_file_id}


class UnicyclerInputsIn(ShortReadInputsIn):
    long_file_id: FileId | None = Field(default=None, description="Long reads (Oxford Nanopore or PacBio), one file")

    def roles(self) -> dict[str, str | None]:
        return {**super().roles(), "long": self.long_file_id}


class SpadesParamsIn(BaseModel):
    mode: SpadesMode = Field(default="isolate", description="isolate: --isolate (no read error correction, "
                             "recommended for isolates); careful: --careful (read and mismatch correction); standard: "
                             "no mode flag")
    k: list[Annotated[int, Field(ge=1, le=127)]] | None = Field(
        default=None, min_length=1, max_length=20, description="Passed as -k (odd, ascending); unset: SPAdes chooses")
    cov_cutoff: Literal["off", "auto"] | Annotated[float, Field(gt=0)] = Field(
        default="off", description="Passed as --cov-cutoff ('off' is SPAdes' default)")
    memory_gb: int | None = Field(default=None, ge=1, description="Passed as -m; unset: min(250, ARVA's memory cap)")
    threads: int | None = Field(default=None, ge=1, le=128, description="Capped at the server's thread limit")
    output: Literal["contigs", "scaffolds"] = Field(default="contigs", description="The file registered as the assembly")


class SpadesRequest(BaseModel):
    inputs: ShortReadInputsIn
    params: SpadesParamsIn = SpadesParamsIn()
    reads_confirmed: bool = Field(default=False, description="Required when the sample's technology is unknown: the "
                                  "user confirms that the files hold the reads their roles say")


class ShortReadPreviewRequest(BaseModel):
    inputs: ShortReadInputsIn


class UnicyclerParamsIn(BaseModel):
    mode: UnicyclerBridging = Field(default="normal", description="Passed as --mode (bridging mode)")
    keep: Literal[0, 1] = Field(default=1, description="Passed as --keep: 0 final files only, 1 also checkpoint graphs")
    kmers: list[Annotated[int, Field(ge=11, le=127)]] | None = Field(
        default=None, min_length=1, max_length=20, description="Passed as --kmers (short reads only); unset: automatic")
    depth_filter: float = Field(default=0.25, ge=0, le=1, description="Passed as --depth_filter (short reads only)")
    min_fasta_length: int = Field(default=100, ge=1, description="Passed as --min_fasta_length")
    linear_seqs: int = Field(default=0, ge=0, description="Passed as --linear_seqs")
    threads: int | None = Field(default=None, ge=1, le=128, description="Capped at the server's thread limit")
    spades_memory_gb: int | None = Field(default=None, ge=1, description="SPAdes' -m inside Unicycler (short reads); "
                                         "unset: min(250, ARVA's memory cap)")


class UnicyclerRequest(BaseModel):
    inputs: UnicyclerInputsIn
    params: UnicyclerParamsIn = UnicyclerParamsIn()
    reads_confirmed: bool = False


class UnicyclerPreviewRequest(BaseModel):
    inputs: UnicyclerInputsIn


MultiqcModule = Literal["fastqc", "fastp", "seqkit", "filtlong"]


BatchAnalysis = Literal["sequence_stats", "seqkit", "fastqc"]
BatchDecision = Literal["run", "derived_excluded", "raw_signal", "not_reads", "not_fastq", "invalid", "active",
                        "completed"]


class BatchQcRequest(BaseModel):
    analyses: list[BatchAnalysis] = Field(min_length=1, max_length=3)
    include_derived: bool = Field(default=False, description="Also analyse derived (filtered) files")
    recompute: bool = Field(default=False, description="Also analyse files that already have a completed result")
    sample_ids: list[Annotated[str, Field(max_length=64)]] | None = Field(
        default=None, min_length=1, max_length=10_000, description="Samples to include; every sample if omitted")
    dry_run: bool = Field(default=True, description="Only return the plan; nothing is created")
    plan_id: str | None = Field(default=None, max_length=64,
                                description="Required to create jobs: the plan_id of the preview that was confirmed")

    @model_validator(mode="after")
    def _check(self) -> "BatchQcRequest":
        if len(set(self.analyses)) != len(self.analyses):
            raise ValueError("each analysis may be listed once")
        if not self.dry_run and not self.plan_id:
            raise ValueError("plan_id is required to create jobs: confirm a preview (dry_run) first")
        return self


class BatchToolRead(BaseModel):
    analysis: BatchAnalysis
    tool: str
    version: str | None
    available: bool
    message: str


class BatchFileRead(BaseModel):
    file_id: str
    name: str
    origin: FileOrigin
    file_format: FileFormat
    decisions: dict[str, BatchDecision] = Field(description="Per analysis: 'run', or why no job is created")


class BatchSampleRead(BaseModel):
    sample_id: str
    sample_code: str
    jobs: dict[str, int] = Field(description="Jobs that would be (or were) created, per analysis")
    total: int
    files: list[BatchFileRead]


class BatchQcPlanRead(BaseModel):
    plan_id: str
    analyses: list[BatchAnalysis]
    include_derived: bool
    recompute: bool
    sample_ids: list[str] | None
    tools: list[BatchToolRead]
    samples: list[BatchSampleRead]
    totals: dict[str, int]
    total_jobs: int
    samples_with_jobs: int
    dry_run: bool
    created_job_ids: list[str] = []


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
    params: dict[str, str | int] = Field(default={}, description="Values for the translated text of the code")


class UploadResult(BaseModel):
    files: list[RawFileRead]
    rejected: list[UploadRejection]


# --- Storage capacity and server-folder import ----------------------------------

class StorageLocationRead(BaseModel):
    role: Literal["data", "databases", "import", "external_databases"]
    container_path: str = Field(description="Where ARVA sees the folder (inside its containers)")
    host_path: str | None = Field(description="The folder on this computer as scripts/start.sh gave it; None for a "
                                              "Docker volume or when ARVA was started without the launcher")
    read_only: bool
    available: bool = Field(description="The folder can be read now (false: its disk is not connected)")
    free_bytes: int | None
    total_bytes: int | None
    filesystem: str | None = Field(description="The host filesystem as the launcher read it (apfs, hfs, exfat, ...)")
    warnings: list[Literal["not_connected", "fat_filesystem", "low_space"]]
    marker: str | None = Field(default=None, description="The data folder's storage marker status")
    stores: list[str]
    slot: str | None = Field(default=None, description="An added database folder's number (/databases-external/<n>)")
    databases: int | None = Field(default=None, description="Reference databases ARVA knows in this folder")


class StorageMarkerRead(BaseModel):
    status: Literal["ok", "new", "unavailable", "missing", "mismatch", "restore_needed", "invalid"]
    disk_id: str | None
    recorded_id: str | None
    backups: int
    message: CodedMessage | None = None
    text: str | None = Field(default=None, description="The English text of `message`")


class BackupFileRead(BaseModel):
    name: str
    kind: Literal["auto", "manual", "pre-restore"]
    created_at: dt.datetime
    size_bytes: int


class BackupResultRead(BaseModel):
    result: Literal["ok", "failed"]
    kind: Literal["auto", "manual", "pre-restore"] | None
    at: dt.datetime
    detail: str | None


class BackupsRead(BaseModel):
    folder: str
    host_folder: str | None
    count: int
    files: list[BackupFileRead] = Field(description="The newest backups first (at most 30)")
    last_result: BackupResultRead | None
    pending_since: dt.datetime | None = Field(description="A backup asked for and not yet made")
    interval_hours: int
    keep: int = Field(description="Backups kept of each kind")


class StorageCapacityRead(BaseModel):
    storage_root: str
    free_bytes: int
    total_bytes: int
    min_free_bytes: int
    available_for_data_bytes: int
    upload_overhead_factor: Literal[1, 2] = Field(
        description="2 when browser uploads are buffered on the same disk and so need twice their size while received"
    )
    data_host_path: str | None = Field(default=None, description="The data folder on this computer, when known")
    marker: StorageMarkerRead | None = None
    locations: list[StorageLocationRead] = []
    backups: BackupsRead | None = None
    in_container: bool = False


class StorageAdoptRequest(BaseModel):
    confirm: bool = Field(description="Must be true: the folder is then used with the current metadata")


PerformanceProfile = Literal["light", "balanced", "maximum", "custom"]
PerformanceChoice = Literal["auto", "light", "balanced", "maximum", "custom"]


class HostFactRead(BaseModel):
    value: Any = None
    source: Literal["launcher", "macos"] | None = Field(
        description="launcher: scripts/start.sh (ARVA_HOST_*); macos: read natively; None: unknown")


class PerformanceContainerRead(BaseModel):
    usable_cpus: int
    cpus_source: str = Field(description="affinity, cpu_count, cgroup_v2 or cgroup_v1")
    memory_bytes: int | None
    memory_source: str | None = Field(description="cgroup_v2, cgroup_v1, meminfo, macos or sysconf")
    in_container: bool
    container_marker: str | None


class PerformanceAutomaticRead(BaseModel):
    profile: PerformanceProfile
    reason: str = Field(description="The Mac family (macbook_air, macbook, macbook_pro, mac_mini, imac, mac_studio, "
                        "mac_pro), or few_resources / many_resources / default for other computers")
    core_basis: Literal["performance_cores", "physical_cores", "usable_cpus"]
    cores: int


class PerformanceChoiceRead(BaseModel):
    profile: PerformanceChoice
    threads: int | None = None
    memory_gb: int | None = None
    updated_at: dt.datetime | None = None


class PerformanceEffectiveRead(BaseModel):
    profile: PerformanceProfile
    choice: PerformanceChoice
    threads: int = Field(description="Threads a tool run gets by default")
    max_threads: int = Field(description="Most threads a run may ask for")
    memory_gb: int = Field(description="Memory per job: the limit given to tools that take one")
    max_memory_gb: int
    nice: int = Field(description="CPU priority: tools start through nice -n <nice>")
    usable_cpus: int
    usable_memory_gb: float
    requested_threads: int = Field(description="What the profile asks for before the caps")
    requested_memory_gb: int
    exceeds: list[Literal["threads", "memory_gb"]] = Field(description="What the choice asks beyond what ARVA can use")
    admin_threads: int | None = Field(description="ARVA_TOOL_THREADS, when set")
    admin_memory_gb: int | None = Field(description="ARVA_TOOL_MEMORY_GB, when set")
    host: str


class PerformanceProfileRow(BaseModel):
    profile: Literal["light", "balanced", "maximum"]
    threads: int
    memory_gb: int
    nice: int


class DockerCpusRead(BaseModel):
    current: int
    recommended: int
    status: Literal["ok", "increase"]


class DockerMemoryRead(BaseModel):
    current_bytes: int | None
    recommended_gb: int
    most_gb: int = Field(description="The most that still leaves macOS a quarter of the Mac's memory")
    status: Literal["ok", "increase", "decrease", "unknown"]


class DockerAdviceRead(BaseModel):
    status: Literal["ok", "adjust", "partial", "host_unknown", "not_container"]
    cpus: DockerCpusRead | None = None
    memory: DockerMemoryRead | None = None


class PerformanceRead(BaseModel):
    host: dict[str, HostFactRead] = Field(description="platform, model_name, model_id, chip, performance_cores, "
                                          "efficiency_cores, physical_cores, logical_cpus, memory_bytes, os_version, "
                                          "arch, docker_cpus, docker_memory_bytes")
    mac_class: str | None
    container: PerformanceContainerRead
    automatic: PerformanceAutomaticRead
    choice: PerformanceChoiceRead
    effective: PerformanceEffectiveRead
    profiles: list[PerformanceProfileRow]
    docker: DockerAdviceRead


class PerformanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: PerformanceChoice
    threads: int | None = Field(default=None, ge=1, le=256, description="Required for a custom profile")
    memory_gb: int | None = Field(default=None, ge=1, le=4096, description="Required for a custom profile")

    @model_validator(mode="after")
    def custom_needs_values(self):
        if self.profile == "custom" and (self.threads is None or self.memory_gb is None):
            raise ValueError("a custom profile needs threads and memory_gb")
        return self


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


# --- Assemblies -------------------------------------------------------------------------

AssemblyWarningCode = Literal["many_contigs", "genome_size_mismatch", "low_coverage_contigs", "high_coverage_contigs",
                              "chromosome_not_circular", "gc_outlier_contigs"]


class AssemblyContigRead(BaseModel):
    rank: int = Field(description="1 = longest; equal lengths keep the FASTA file's order")
    name: str
    length: int
    gc_percent: float | None = Field(description="(G+C)/(A+C+G+T) × 100; null when the contig has no A, C, G or T")
    n_count: int
    other_iupac_count: int = Field(description="Bases other than A, C, G, T and N")
    coverage: float | None = Field(description="As reported by the assembler (Flye: mean read depth; SPAdes: k-mer "
                                           "coverage; Unicycler: relative depth) or, for a polished assembly, the "
                                           "mean depth of the polishing reads mapped to it; see coverage_kind")
    circular: bool | None = Field(description="As reported by the assembler; null when it reports no circularity "
                                           "(SPAdes). A polished contig keeps its draft contig's value")
    repeat: bool | None = Field(description="As reported by the assembler")


class AssemblyWarningRead(BaseModel):
    code: AssemblyWarningCode
    heuristic: Literal[True] = Field(description="Every assembly warning is a heuristic with a stated threshold")
    message: str = Field(description="The warning in English, with its threshold")
    params: dict[str, Any] = Field(description="Values for a translated message")
    contigs: list[str] = Field(description="Names of the contigs concerned (at most 50)")
    contigs_total: int


class AssemblyCheckRead(BaseModel):
    code: AssemblyWarningCode
    rule: str
    evaluated: bool
    skipped_reason: str | None


class AssemblyLengthBin(BaseModel):
    min_length: int = Field(description="Inclusive")
    max_length: int = Field(description="Exclusive")
    contigs: int
    total_length: int


class AssemblyCurve(BaseModel):
    rank: list[int]
    length: list[int] = Field(description="Contig lengths, longest first")
    cumulative_length: list[int]
    downsampled: bool = Field(description="Over 1,000 contigs: the 500 longest, then evenly spaced ranks to the last")


class AssemblyThreshold(BaseModel):
    min_length: int
    contigs: int
    total_length: int
    total_length_percent: float


class AssemblyCoverageSummary(BaseModel):
    contigs_with_coverage: int
    length_weighted_median: float | None = Field(
        description="Coverage of the contig holding the middle base when contigs are ordered by coverage"
    )


class AssemblyCircularitySummary(BaseModel):
    contigs_with_circularity: int
    circular_contigs: int


class AssemblyContigRows(BaseModel):
    stored: int
    total: int
    truncated: bool = Field(description="True when only the longest contigs' rows are stored")


class AssemblyGenomeSize(BaseModel):
    bp: int | None
    status: Literal["given", "not_given", "inconsistent"]
    source: Literal["assembly_parameters", "read_statistics"] | None
    basis: GenomeSizeBasis | None = Field(
        default=None, description="For a size given with the assembly: typed, the sample's expected size, or reads ÷ depth"
    )
    assumed_depth_x: float | None = None


class AssemblyOutputFile(BaseModel):
    path: str
    sha256: str
    size_bytes: int


class AssemblyFiles(BaseModel):
    contigs: AssemblyOutputFile
    graph: AssemblyOutputFile | None
    info: AssemblyOutputFile | None


class AssemblyStatsRead(BaseModel):
    tool: dict[str, str]
    parameters: dict[str, Any]
    contig_count: int
    total_length: int
    largest_contig: int
    smallest_contig: int
    n50: int
    l50: int
    n90: int
    l90: int
    gc_percent: float | None = Field(description="(G+C)/(A+C+G+T) × 100 over unambiguous bases")
    n_count: int
    n_per_100kb: float
    other_iupac_count: int
    length_histogram: list[AssemblyLengthBin]
    cumulative: AssemblyCurve
    thresholds: list[AssemblyThreshold]
    coverage: AssemblyCoverageSummary
    circularity: AssemblyCircularitySummary
    contig_rows: AssemblyContigRows
    expected_genome_size: AssemblyGenomeSize
    warning_checks: list[AssemblyCheckRead] = Field(description="Every heuristic, including those not evaluated")
    files: AssemblyFiles


CoverageKind = Literal["read_depth", "kmer_coverage", "relative_depth", "mapped_read_depth"]
COVERAGE_KIND_DESCRIPTION = ("What the per-contig coverage measures: Flye's mean read depth, SPAdes' k-mer coverage, "
                             "Unicycler's depth relative to the main replicons, or (polished assemblies) the mean depth "
                             "of the polishing reads mapped with minimap2 or BWA-MEM (samtools coverage); values of "
                             "different kinds are not comparable")
AssemblyKindName = Literal["assembly", "polished"]


class AssemblyRead(ORMModel):
    id: str
    sample_id: str
    job_id: str
    kind: AssemblyKindName = Field(description="'polished': made from parent_assembly_id by the polisher in `assembler`")
    parent_assembly_id: str | None = Field(description="The draft a polished assembly was made from")
    assembler: str
    assembler_version: str
    mode: AssemblyMode
    read_type: str
    coverage_kind: CoverageKind | None = Field(description=COVERAGE_KIND_DESCRIPTION)
    input_file_ids: list[str] = Field(description="The imported or derived read files the assembler used")
    contigs_path: str
    graph_path: str | None
    info_path: str | None
    stats: AssemblyStatsRead
    warnings: list[AssemblyWarningRead]
    created_at: dt.datetime


class AssemblyDetail(AssemblyRead):
    contigs: list[AssemblyContigRead] = Field(description="Longest first; see stats.contig_rows for truncation")


class AssemblyGraphNode(BaseModel):
    id: str
    length: int
    tags: dict[str, int | float] = Field(description="Numeric GFA tags as the assembler wrote them (e.g. Flye dp)")
    paths: list[str] = Field(description="GFA paths (P lines; Flye: contigs) through this segment, at most 20")
    circular: bool | None = Field(description="True when a contig in `paths` is reported circular by the assembler; "
                                              "null when none of them has a circularity value")
    repeat: bool | None = Field(description="True when a contig in `paths` is flagged as a repeat by the assembler")


class AssemblyGraphEdge(BaseModel):
    source: str
    source_orientation: Literal["+", "-"]
    target: str
    target_orientation: Literal["+", "-"]
    overlap: str
    tags: dict[str, int | float]


class AssemblyGraphRead(BaseModel):
    assembly_id: str
    assembler: str
    coverage_tag: str | None = Field(description="The segment tag holding this assembler's coverage (Flye: dp)")
    coverage_meaning: str | None = Field(description="What that tag measures (Flye: mean read depth)")
    format: Literal["GFA1"]
    version: str | None
    segment_count: int
    link_count: int
    path_count: int
    dangling_links: int = Field(description="Links naming a segment the file does not define (not shown)")
    total_segment_length: int
    numeric_tags: list[str]
    max_nodes: int
    max_edges: int
    truncated: bool = Field(description="True when segments or links were left out to respect max_nodes/max_edges")
    nodes: list[AssemblyGraphNode] = Field(description="Longest segments first")
    edges: list[AssemblyGraphEdge]


class ProjectAssemblyRead(BaseModel):
    """One assembly of a project, for the project's overview (per-contig rows: GET /assemblies/{id})."""
    id: str
    sample_id: str
    sample_code: str
    job_id: str
    kind: AssemblyKindName
    parent_assembly_id: str | None
    assembler: str
    assembler_version: str
    mode: AssemblyMode
    read_type: str
    contig_count: int
    total_length: int
    largest_contig: int
    n50: int
    l50: int
    gc_percent: float | None
    circular_contigs: int
    contigs_with_circularity: int
    median_coverage: float | None = Field(description="Length-weighted median of the assembler's contig coverage")
    coverage_kind: CoverageKind | None = Field(description=COVERAGE_KIND_DESCRIPTION)
    warning_codes: list[AssemblyWarningCode]
    created_at: dt.datetime


class FlyeToolRead(BaseModel):
    status: str
    version: str | None
    version_validated: bool
    message: str
    reason: str | None
    reason_params: dict[str, str] = {}
    options: list[str] = Field(description="Optional Flye options this installed version lists in its --help")
    max_threads: int = Field(description="Most threads a run may ask for: the CPUs ARVA can use (or ARVA_TOOL_THREADS)")
    default_threads: int = Field(description="Threads a run gets when none are given: the performance profile's")


class FlyeFileEvidence(BaseModel):
    file_id: str
    name: str
    origin: FileOrigin
    header_platform: Literal["illumina", "nanopore", "pacbio"] | None
    header_confidence: Literal["high", "medium", "low", "none"]
    basecall_models: list[str]
    pacbio_read_types: list[str]
    stats_job_id: str | None = Field(description="Newest completed ARVA read statistics of the file")
    total_bases: int | None
    max_read_length: int | None
    read_n50: int | None
    mean_base_quality: float | None = Field(description="-10 log10(mean base error probability), from the FASTQ qualities")


class FlyeReadTypeSuggestion(BaseModel):
    heuristic: Literal[True]
    value: FlyeReadType | None
    basis: str
    platform: Literal["nanopore", "pacbio"] | None
    platform_source: Literal["sample_metadata", "read_headers"] | None
    mean_error_rate: float | None = Field(description="Base-weighted mean error probability implied by the qualities")
    mean_base_quality: float | None
    q20_read_error_note: bool = Field(description="Flye's documentation suggests --read-error 0.03 for Q20 data")
    sup_model_but_low_quality: bool


class FlyeDepthEstimate(BaseModel):
    depth_x: float
    total_read_bases: int
    bp: int = Field(description="round(total_read_bases ÷ depth_x)")


class FlyeGenomeSizeOptions(BaseModel):
    expected: AssemblyGenomeSize
    total_read_bases: int | None = Field(description="Sum over the selected files; null when one has no statistics")
    files_without_stats: list[str]
    from_depth: FlyeDepthEstimate | None


class FlyePlanRead(BaseModel):
    tool: FlyeToolRead
    files: list[FlyeFileEvidence]
    read_type_suggestion: FlyeReadTypeSuggestion
    genome_size: FlyeGenomeSizeOptions
    sample_technology: SequencingTechnology
    long_reads_confirmation_required: bool


class AssemblyToolRead(BaseModel):
    status: str
    version: str | None
    version_validated: bool
    message: str
    reason: str | None
    reason_params: dict[str, str] = {}
    options: list[str] = Field(description="Options of interest this installed version lists in its help")
    max_threads: int = Field(description="Most threads a run may ask for: the CPUs ARVA can use (or ARVA_TOOL_THREADS)")
    default_threads: int = Field(description="Threads a run gets when none are given: the performance profile's")
    max_memory_gb: int = Field(description="Most memory ARVA may give a run: the memory it can use (or "
                               "ARVA_TOOL_MEMORY_GB)")
    default_memory_gb: int = Field(description="Used when no memory is given: min(250, the profile's memory per job); "
                                   "SPAdes' own default is 250")


class UnicyclerHelperRead(BaseModel):
    path: str | None
    version: str | None


class UnicyclerToolRead(AssemblyToolRead):
    modes: list[Literal["short", "long", "hybrid"]] = Field(description="Modes whose helpers are installed")
    helpers: dict[str, UnicyclerHelperRead]


class AssemblyFileEvidence(FlyeFileEvidence):
    role: Literal["r1", "r2", "unpaired", "long"]
    read_mate: str | None
    read_count: int | None


class ShortReadPlanRead(BaseModel):
    tool: AssemblyToolRead
    files: list[AssemblyFileEvidence]
    assembly_mode: AssemblyMode | None
    read_layout: str
    problem: str | None = Field(description="Why these files cannot be assembled as chosen; null when they can")
    sample_technology: SequencingTechnology
    confirmation_required: bool


class UnicyclerPlanRead(ShortReadPlanRead):
    tool: UnicyclerToolRead


class QuastPreviewRequest(BaseModel):
    assembly_ids: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=10)
    reference_file_id: str | None = Field(default=None, max_length=64,
                                          description="A FASTA file of the sample to use as the reference genome")
    min_contig: int = Field(default=500, ge=0, le=1_000_000,
                            description="QUAST's --min-contig: shorter contigs are left out of most metrics")


class QuastRequest(QuastPreviewRequest):
    threads: int | None = Field(default=None, ge=1, le=256, description="Capped at the server's thread limit")


class QuastAligner(BaseModel):
    provided_by: Literal["quast_bundled", "path", "missing"] = Field(
        description="How QUAST would find minimap2 for a reference; 'missing': it would compile it, which ARVA refuses")
    executable: str | None = None
    version: str | None = None
    found: str | None = Field(default=None, description="A minimap2 on PATH that is too old for QUAST")


class QuastToolRead(BaseModel):
    status: str
    version: str | None
    version_validated: bool
    message: str
    reason: str | None
    reason_params: dict[str, str] = {}
    aligner: QuastAligner | None
    max_threads: int
    default_threads: int = Field(description="Threads a run gets when none are given: the performance profile's")
    default_min_contig: int


class QuastPlannedAssembly(BaseModel):
    assembly_id: str
    label: str = Field(description="The name QUAST will use for the assembly in its reports")
    assembler: str
    assembler_version: str
    read_type: str
    created_at: dt.datetime
    contigs: int
    total_length: int
    contigs_kept: int = Field(description="Contigs of at least min_contig bp, which QUAST's metrics describe")
    length_kept: int
    contigs_left_out: int
    length_left_out: int


class QuastReferenceRead(BaseModel):
    file_id: str
    name: str
    size_bytes: int
    origin: FileOrigin


class QuastPlanRead(BaseModel):
    tool: QuastToolRead
    min_contig: int
    assemblies: list[QuastPlannedAssembly]
    reference: QuastReferenceRead | None


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


# --- Polishing ---------------------------------------------------------------------------------------------------

PolishingStrategy = Literal["racon", "pilon", "hybrid"]
LongReadPreset = Literal["map-ont", "map-pb", "map-hifi"]
PilonFix = Literal["snps", "indels", "gaps", "local"]


class PolishingInputsIn(UnicyclerInputsIn):
    """Files by role: long reads for Racon, paired-end (R1 and R2) and/or unpaired short reads for Pilon."""


class RaconSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_type: LongReadPreset | None = Field(default=None, description="minimap2 preset: map-ont (Nanopore), map-pb "
                                             "(PacBio CLR), map-hifi (PacBio HiFi); required with long reads")
    rounds: int = Field(default=1, ge=1, le=5, description="Rounds of minimap2 + Racon, each on the previous result")
    match: int = Field(default=3, ge=1, le=100, description="Passed as -m (Racon's default 3)")
    mismatch: int = Field(default=-5, ge=-100, le=-1, description="Passed as -x (Racon's default -5)")
    gap: int = Field(default=-4, ge=-100, le=-1, description="Passed as -g (Racon's default -4)")
    window_length: int = Field(default=500, ge=100, le=10_000, description="Passed as -w (Racon's default 500)")
    quality_threshold: float = Field(default=10.0, ge=0, le=60, description="Passed as -q (Racon's default 10.0)")
    error_threshold: float = Field(default=0.3, gt=0, le=1, description="Passed as -e (Racon's default 0.3)")


class PilonSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rounds: int = Field(default=1, ge=1, le=5, description="Rounds of BWA-MEM + Pilon, each on the previous result")
    fix: list[PilonFix] = Field(default_factory=lambda: ["snps", "indels", "gaps", "local"], min_length=1,
                                max_length=4, description="Passed as --fix (Pilon's default: all four)")
    mindepth: float = Field(default=0.1, gt=0, le=1000, description="Passed as --mindepth (Pilon's default 0.1)")
    minmq: int = Field(default=0, ge=0, le=60, description="Passed as --minmq (Pilon's default 0)")
    minqual: int = Field(default=0, ge=0, le=60, description="Passed as --minqual (Pilon's default 0)")
    heap_gb: int | None = Field(default=None, ge=1, description="Java -Xmx; unset: min(16 GB, ARVA's memory cap)")
    stop_when_unchanged: bool = Field(default=True, description="Stop after a round in which Pilon changes nothing")


class PolishingPreviewRequest(BaseModel):
    inputs: PolishingInputsIn
    read_type: LongReadPreset | None = None


class PolishingRequest(BaseModel):
    strategy: PolishingStrategy
    inputs: PolishingInputsIn
    racon: RaconSettingsIn = Field(default_factory=RaconSettingsIn)
    pilon: PilonSettingsIn = Field(default_factory=PilonSettingsIn)
    threads: int | None = Field(default=None, ge=1, le=128, description="Capped at the server's thread limit")
    quast: bool = Field(default=False, description="Compare the draft and the polished assemblies with QUAST when done")
    quast_reference_file_id: FileId | None = Field(default=None, description="A FASTA reference of the sample for QUAST")
    reads_confirmed: bool = Field(default=False, description="The files hold the reads their roles say (needed when "
                                  "the sample's sequencing technology is unknown)")


class PolishingToolRead(BaseModel):
    status: str
    version: str | None
    version_validated: bool
    message: str
    reason: str | None
    reason_params: dict[str, str] = {}
    path: str | None


class PolishingDraftRead(BaseModel):
    assembly_id: str
    kind: AssemblyKindName
    assembler: str
    assembler_version: str
    mode: AssemblyMode
    read_type: str
    parent_assembly_id: str | None
    contig_count: int
    total_length: int
    n50: int
    circular_contigs: int
    created_at: dt.datetime


class PolishingPresetSuggestion(BaseModel):
    heuristic: Literal[True]
    value: LongReadPreset | None
    basis: str
    flye_read_type: str | None = Field(description="ARVA's Flye read-type suggestion for the same reads")
    platform: Literal["nanopore", "pacbio"] | None = None


class PolishingPlanRead(BaseModel):
    draft: PolishingDraftRead
    tools: dict[str, PolishingToolRead] = Field(description="racon, minimap2, pilon, java, bwa, samtools, dnadiff")
    strategies_available: list[PolishingStrategy] = Field(description="Strategies whose tools are all installed")
    files: list[AssemblyFileEvidence]
    strategy: PolishingStrategy | None = Field(description="The strategy the chosen reads imply")
    suggested_strategy: PolishingStrategy | None = Field(description="The strategy the sample's technology calls for")
    preset_suggestion: PolishingPresetSuggestion
    problem: str | None
    sample_technology: SequencingTechnology
    confirmation_required: bool
    max_threads: int
    default_threads: int = Field(description="Threads a run gets when none are given: the performance profile's")
    max_memory_gb: int
    default_heap_gb: int = Field(description="min(16 GB, the profile's memory per job); Debian's Pilon launcher uses 16")


# --- Reference databases (Database Manager) ---------------------------------------------------------------------

class CompatibilityRead(BaseModel):
    status: Literal["compatible", "incompatible", "unknown"]
    code: str = Field(description="schema_ok, schema_mismatch, schema_unknown, tool_not_installed, "
                                  "tool_not_integrated, tool_version_unchecked")
    params: dict[str, str | int] = {}


class ToolUseRead(BaseModel):
    tool: str
    versions: str
    integrated: bool


class DatabaseKindRead(BaseModel):
    key: str
    name: str
    description: str
    tools: list[ToolUseRead]
    source_url: str
    licence: str
    licence_url: str | None = None
    citation: str
    recognise: str
    version_from: str
    typical_size: str
    download: Literal["catalogue", "register", "bundled", "release"]
    download_note: str
    sources: list[str]
    unconfirmed: list[str] = []
    accepts: list[str]
    user_provided_only: bool = False


class CatalogueEntryRead(BaseModel):
    key: str
    name: str
    kind: str
    tool: str
    status: Literal["available"] = "available"
    description: str
    version: str
    release_date: str | None = None
    db_type: str | None = None
    source_url: str
    doi: str | None = None
    download_url: str
    filename: str
    archive_bytes: int
    checksum_algorithm: str
    checksum: str
    checksum_sources: list[str] = []
    extracted_size_note: str = Field(description="The publisher's statement of the unpacked size, or ARVA's listing")
    extracted_bytes_estimate: int = Field(description="Bytes ARVA reserves for the unpacked database")
    top_dir: str | None = None
    install_dir: str = Field(description="The default folder inside the chosen database folder")
    licence: str
    licence_url: str | None = None
    terms: str
    citation: str
    compatibility: str
    compatibility_now: CompatibilityRead = Field(description="With the tool version ARVA runs now")
    external_versions: dict[str, str] = {}
    notes: list[str] = []


class DatabaseProgress(BaseModel):
    model_config = ConfigDict(extra="allow")
    phase: str | None = None
    bytes_done: int | None = None
    bytes_total: int | None = None
    written_bytes: int | None = None
    resumed_from: int | None = None
    started_at: str | None = None
    updated_at: str | None = None


class DetectionProblemRead(BaseModel):
    code: str
    params: dict[str, str | int] = {}
    blocking: bool
    text: str


class DetectionFileRead(BaseModel):
    path: str
    role: str = Field(description="kind (identifies the kind), version (the version was read from it), required, "
                                  "optional")
    present: bool
    size: int | None = None


class DetectionRead(BaseModel):
    kind: str = Field(description="A database_kinds key, or unknown (with problem nested: subfolders that are)")
    kind_name: str | None = None
    path: str
    host_path: str | None = None
    path_type: Literal["folder", "file", "zip"]
    variant: str | None = None
    version: str | None = Field(default=None, description="Read from the database's own files")
    version_file: str | None = None
    version_detail: str | None = None
    suggested_version: str | None = Field(default=None, description="For you to confirm (it becomes declared)")
    suggested_from: str | None = Field(default=None, description="folder_name, file_name or zip_entries")
    version_by_checksum: bool = False
    needs_declared_version: bool
    catalogue_key: str | None = None
    ok: bool
    files: list[DetectionFileRead]
    problems: list[DetectionProblemRead]
    facts: dict[str, Any]
    compatibility: CompatibilityRead | None = None
    already_registered: str | None = Field(default=None, description="The record that already has this path")


class DetectResultRead(BaseModel):
    path: str
    host_path: str | None
    candidates: list[DetectionRead]


class ReferenceDatabaseRead(ORMModel):
    id: str
    key: str
    kind: str
    name: str
    version: str | None
    version_source: Literal["file", "declared", "checksum"] | None = None
    path: str | None
    source_url: str | None
    licence: str | None
    size_bytes: int | None
    checksum: str | None = Field(description="SHA-256 over ARVA's manifest of every file (full verification only)")
    archive_checksum: str | None = Field(description="The published checksum of the archive, verified before unpacking")
    status: DatabaseStatus
    origin: DatabaseOrigin
    is_default: bool = False
    verification_level: Literal["quick", "full"] | None = None
    installed_at: dt.datetime | None
    verified_at: dt.datetime | None
    notes: str | None
    error_message: str | None
    error_detail: CodedMessage | None = None
    progress: DatabaseProgress | None
    cancel_requested_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    version_json: dict[str, Any] | None = None
    version_file: str | None = Field(default=None, description="The file the version was read from")
    variant: str | None = None
    collection: dict[str, Any] | None = Field(default=None, description="A reference collection's coverage")
    files: int | None = Field(default=None, description="Files in the recorded manifest")
    published_md5_checked: int | None = None
    amrfinderplus_db: dict[str, Any] | None = Field(
        default=None, description="The AMRFinderPlus data in amrfinderplus-db/latest: link target, version, format, "
                                  "and whether the installed AMRFinderPlus reads them")
    archive: dict[str, Any] | None = None
    catalogue_version: str | None = Field(default=None, description="The catalogue's version of this database")
    compatibility: CompatibilityRead | None = None
    jobs_using: int = Field(default=0, description="Queued or running jobs that use it")
    available: bool = Field(default=True, description="Its folder can be read now (false: e.g. disk not connected)")
    unavailable_reason: Literal["disk_not_connected", "folder_missing"] | None = None
    host_path: str | None = Field(default=None, description="The folder on this computer, when ARVA knows it")
    log_text: str | None = None
    mlst: dict[str, Any] | None = Field(default=None, description="mlst's bundled schemes: count, dates, sources, "
                                        "schemes updated after PubMLST's open-data date, the terms")


class DatabaseLocationRead(BaseModel):
    path: str
    host_path: str | None
    available: bool
    free_bytes: int | None
    total_bytes: int | None
    reserve_bytes: int


class BrowseRootRead(BaseModel):
    path: str
    host_path: str | None
    read_only: bool
    role: Literal["databases", "external_databases"]
    available: bool


class DatabaseLocationsRead(BaseModel):
    writable: list[DatabaseLocationRead]
    browse: list[BrowseRootRead]


class BrowseEntryRead(BaseModel):
    name: str
    type: Literal["folder", "file"]
    size_bytes: int | None
    link: bool
    path: str


class BrowseListingRead(BaseModel):
    root: str
    path: str
    parent: str | None
    host_path: str
    container_path: str
    entries: list[BrowseEntryRead]
    truncated: bool


class DownloadPlanRead(BaseModel):
    entry: CatalogueEntryRead
    db_dir: str
    target_path: str
    host_target_path: str
    folder: str
    partial_bytes: int = Field(description="Bytes of an earlier partial download that will be resumed")
    download_bytes: int
    required_bytes: int = Field(description="Bytes still to download plus the unpacked size")
    free_bytes: int
    reserve_bytes: int = Field(description="ARVA_MIN_FREE_BYTES, always left free")
    available_bytes: int
    enough: bool
    resume_record_id: str | None
    blocked_by: str | None = Field(description="Why the download cannot start now, if it cannot")
    blocked_code: str | None = None
    compatibility: CompatibilityRead
    destinations: list[DatabaseLocationRead] = []
    extras: dict[str, Any] | None = Field(default=None, description="MOB-suite: the NCBI taxonomy archive it also "
                                          "needs, the archives NCBI lists, whether the FASTA is kept, the extra bytes "
                                          "and the preparation steps")


class ExtractPlanRead(BaseModel):
    source: str
    host_source: str
    detection: DetectionRead
    db_dir: str
    target_path: str
    host_target_path: str
    folder: str
    required_bytes: int
    free_bytes: int
    reserve_bytes: int
    available_bytes: int
    enough: bool
    blocked_by: str | None
    destinations: list[DatabaseLocationRead] = []


class DatabaseDownloadRequest(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    confirm_bytes: int = Field(ge=0, description="The archive size shown to the user, repeated as confirmation")
    accept_licence: bool
    destination: str | None = Field(default=None, max_length=4096, description="A writable database folder "
                                    "(default: the database folder)")
    folder: str | None = Field(default=None, max_length=400, description="Relative folder inside it")
    keep_plasmid_fasta: bool = Field(default=False, description="MOB-suite: keep the reference plasmids' FASTA "
                                     "(mob_recon searches only its BLAST index)")
    taxonomy_archive: str | None = Field(default=None, pattern=r"^taxdmp_\d{4}-\d{2}-\d{2}\.zip$",
                                         description="MOB-suite: the dated NCBI taxonomy archive shown in the plan, "
                                         "repeated as confirmation")


class DatabaseRegisterRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="Absolute path of an existing database folder or file")
    kind: str | None = Field(default=None, max_length=50, description="When several kinds match")
    declared_version: str | None = Field(default=None, max_length=200,
                                         description="When the files do not state the version")
    collection_date: str | None = Field(default=None, max_length=20, description="A reference collection's date")
    full_checksum: bool = Field(default=False, description="Also start the full checksum now")


class DatabaseExtractRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096, description="The NCBI Datasets package zip")
    confirm_bytes: int = Field(ge=0, description="The copy's size shown to the user, repeated as confirmation")
    collection_date: str | None = Field(default=None, max_length=20)
    destination: str | None = Field(default=None, max_length=4096)
    folder: str | None = Field(default=None, max_length=400)


class DatabaseVerifyRequest(BaseModel):
    level: Literal["quick", "full"] = "full"


class DatabaseUsageRead(BaseModel):
    db_dir: str
    host_db_dir: str | None = None
    free_bytes: int
    total_bytes: int
    reserve_bytes: int
    installed_bytes: int
    registered_bytes: int = Field(description="Registered folders (they may lie outside ARVA_DB_DIR)")
    partial_bytes: int = Field(description="Partial downloads kept for resuming")
    staging_bytes: int


# --- Annotation --------------------------------------------------------------------------------------------------

TranslationTable = Literal[11, 4, 25]
_LOCUS_TAG = r"^[A-Z][A-Z0-9]{2,11}$"
_GENUS = r"^[A-Za-z]{2,50}$"
_SPECIES = r"^[A-Za-z][A-Za-z.-]{0,49}$"
_STRAIN = r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,39}$"


class AnnotationOrganismIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locus_tag: str = Field(pattern=_LOCUS_TAG, description="Locus-tag prefix: 3-12 capital letters or digits, "
                           "starting with a letter (accepted by both annotators and by INSDC)")
    translation_table: TranslationTable = Field(default=11, description="11: bacteria and archaea; 4: Mycoplasma and "
                                                "Spiroplasma; 25: candidate division SR1 and Gracilibacteria")
    genus: str | None = Field(default=None, pattern=_GENUS)
    species: str | None = Field(default=None, pattern=_SPECIES)
    strain: str | None = Field(default=None, pattern=_STRAIN)
    min_contig_length: int = Field(default=1, ge=1, le=1_000_000, description="Shorter contigs are not annotated")


class BaktaSettingsIn(AnnotationOrganismIn):
    complete: bool = Field(default=False, description="--complete: every sequence is a complete replicon; Bakta then "
                           "treats each as circular. Needs complete_confirmed")
    keep_contig_headers: bool = Field(default=False, description="--keep-contig-headers: keep the assembly's contig "
                                      "names instead of Bakta's contig_1, contig_2, …")
    skip_plot: bool = Field(default=False, description="--skip-plot: no circular genome plot")


class ProkkaSettingsIn(AnnotationOrganismIn):
    use_genus: bool = Field(default=False, description="--usegenus: search the genus' protein set first (Debian's "
                            "package has Enterococcus, Escherichia and Staphylococcus)")
    rfam: bool = Field(default=False, description="--rfam: search Rfam models for ncRNAs with Infernal (slow)")
    evalue: float = Field(default=1e-09, gt=0, le=1, description="--evalue (Prokka's default 1e-09)")
    coverage: float = Field(default=80.0, gt=0, le=100, description="--coverage, % of the query protein (default 80)")
    rename_contigs: bool = Field(default=False, description="Give Prokka contig_1, contig_2, … (needed when a contig "
                                 "name is longer than 37 characters); ARVA keeps the mapping")


class BaktaPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str | None = Field(default=None, description="An installed Bakta database; default: the most "
                                    "recently verified")
    skip_plot: bool = False


class BaktaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str | None = None
    settings: BaktaSettingsIn
    threads: int | None = Field(default=None, ge=1, le=256)
    skip_options: list[str] = Field(description="The --skip-* options the preview showed; the run is refused if the "
                                    "programs available now imply others")
    complete_confirmed: bool = Field(default=False, description="Required with settings.complete")
    confirmed: bool = Field(description="The user confirmed the summary of the run")


class ProkkaPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rfam: bool = False
    use_genus: bool = False
    genus: str | None = Field(default=None, pattern=_GENUS)
    rename_contigs: bool = False


class ProkkaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: ProkkaSettingsIn
    threads: int | None = Field(default=None, ge=1, le=256)
    confirmed: bool


class AnnotationDependencyRead(BaseModel):
    name: str
    status: str = Field(description="ok, missing, failed, unreadable, too_old, crashed (PILER-CR's test run), "
                        "database_missing or database_refused (AMRFinderPlus: no data, or data it does not read)")
    found: str | None = None
    minimum: str | None = None
    returncode: int | None = None
    steps: list[str] = []
    command: list[str] = []
    database: dict[str, Any] | None = Field(default=None, description="AMRFinderPlus: the data checked and the result")


class AnnotationStepRead(BaseModel):
    run: bool = Field(description="Planned to run")
    reason: str | None = Field(default=None, description="Why not, or why it failed: dependency, user, needs_cds, "
                               "light_database, option_off, database_lacks, not_offered, not_supported, "
                               "tool_skipped, crashed")
    dependencies: list[AnnotationDependencyRead] = []
    status: Literal["searched", "skipped", "failed"] | None = Field(default=None, description="After the run")
    found: int | None = Field(default=None, description="The count the annotator printed for this step")
    returncode: int | None = None


class AnnotationProblem(BaseModel):
    code: str
    message: str


class AnnotationToolRead(BaseModel):
    status: str
    version: str | None
    version_validated: bool
    message: str
    reason: str | None
    reason_params: dict[str, str] = {}
    path: str | None
    license: str
    citation: str
    citation_url: str
    max_threads: int
    default_threads: int = Field(description="Threads a run gets when none are given: the performance profile's")


class AnnotationAssemblyFacts(BaseModel):
    assembly_id: str
    kind: str
    assembler: str
    assembler_version: str
    parent_assembly_id: str | None
    job_id: str
    contigs_sha256: str
    created_at: dt.datetime
    contigs: int
    total_length: int | None
    circular_contigs: int | None
    contigs_with_circularity: int | None
    all_circular: bool = Field(description="Every contig was reported circular by the assembler")
    longest_contig_name: int
    prokka_name_problem: str | None
    descriptions: int = Field(description="Contigs whose FASTA header has a description (removed before annotation)")
    synthetic_evidence: list[str] = Field(description="Where the word SYNTHETIC was found (a hint, not a proof)")


class BaktaDatabaseOption(BaseModel):
    id: str
    key: str
    name: str
    version: str | None
    version_source: str | None = None
    type: str | None
    status: DatabaseStatus
    usable: bool
    is_default: bool = False
    verification_level: str | None = None
    compatibility: CompatibilityRead | None = None
    available: bool = True
    unavailable_reason: Literal["disk_not_connected", "folder_missing"] | None = None
    checksum: str | None
    verified_at: dt.datetime | None
    path: str | None
    host_path: str | None = None


class ProkkaDatabaseRead(BaseModel):
    path: str
    ready: bool
    files: list[str]
    package: list[str] | None
    kingdoms: list[str]
    genera: list[str]
    hmm: list[str]
    checksum: str | None = None
    key: str | None = None
    name: str | None = None
    version: str | None = None


class AnnotationPlanRead(BaseModel):
    annotator: Literal["bakta", "prokka"]
    tool: AnnotationToolRead
    steps: dict[str, AnnotationStepRead]
    assembly: AnnotationAssemblyFacts
    suggestions: dict[str, Any]
    translation_tables: list[int]
    problems: list[AnnotationProblem]
    dependencies: list[AnnotationDependencyRead] = Field(default=[], description="Bakta: each program it checks")
    skip_options: list[str] = []
    databases: list[BaktaDatabaseOption] = []
    database_id: str | None = None
    database: ProkkaDatabaseRead | None = None
    programs: dict[str, str | None] = Field(default={}, description="Prokka: each program and where it was found")
    amr_data: dict[str, Any] | None = Field(default=None, description="Bakta: the AMRFinderPlus data its AMR expert "
                                            "system reads (the database's own copy, or an ARVA AMRFinderPlus database "
                                            "in its place when AMRFinderPlus refuses the copy)")


class AnnotationFileRead(BaseModel):
    path: str
    sha256: str
    size_bytes: int


class AnnotationRead(ORMModel):
    id: str
    sample_id: str
    assembly_id: str
    job_id: str
    tool: str
    tool_version: str
    database_key: str | None
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    parameters: dict[str, Any]
    steps: dict[str, AnnotationStepRead]
    summary: dict[str, Any]
    sequences: list[dict[str, Any]]
    files: dict[str, AnnotationFileRead]
    created_at: dt.datetime


class AnnotationFeatureRead(BaseModel):
    id: int
    tool_id: str | None
    locus_tag: str | None
    type: str
    tool_type: str | None
    contig: str
    contig_in_assembly: str
    start: int
    end: int
    strand: str
    length: int
    edge: bool
    gene: str | None
    product: str | None
    ec: list[str]
    cog: list[str]
    cog_categories: list[str]
    go: list[str]
    db_xrefs: list[str]
    pseudo: bool
    partial: str | None
    hypothetical: bool | None
    inference: list[str]
    accessions: list[str]


class AnnotationFeaturePage(BaseModel):
    total: int
    limit: int
    offset: int
    max_limit: int
    items: list[AnnotationFeatureRead]


class AnnotationLink(BaseModel):
    xref: str
    url: str


class AnnotationSequenceRead(BaseModel):
    source: str
    header: str
    length: int
    sequence: str
    truncated: bool


class SequenceCheckRead(BaseModel):
    status: Literal["match", "differs", "not_checked"]
    reason: str | None = Field(default=None, description="Why not checked: no_sequence, no_genome, not_coding, "
                               "no_protein, pseudogene, length")


class ProteinCheckRead(SequenceCheckRead):
    table: int = Field(description="The translation table given to the annotator")
    first_difference: int | None = None
    translated_length: int | None = None
    protein_length: int | None = None
    internal_stops: int | None = None


class FeatureChecksRead(BaseModel):
    nucleotide: SequenceCheckRead = Field(description="The annotator's gene sequence equals the genome at the "
                                          "feature's coordinates")
    protein: ProteinCheckRead = Field(description="The annotator's protein equals ARVA's translation of the genome "
                                      "there (a check only: the protein shown is always the annotator's)")


class AnnotationFeatureDetail(AnnotationFeatureRead):
    links: list[AnnotationLink] = Field(description="Resolver links for identifiers the annotator reported")
    nucleotide: AnnotationSequenceRead | None
    protein: AnnotationSequenceRead | None
    checks: FeatureChecksRead


class AnnotationRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contig: str = Field(min_length=1, max_length=200, description="The annotator's or the assembly's name")
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class AnnotationExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["gff3", "genbank", "fasta_nt", "fasta_aa", "tsv"]
    feature_ids: list[int] | None = Field(default=None, max_length=10_000, description="None: every feature")
    region: AnnotationRegion | None = Field(default=None, description="The features overlapping a region (instead "
                                            "of feature_ids)")

    @model_validator(mode="after")
    def _one_selection(self):
        if self.feature_ids is not None and self.region is not None:
            raise ValueError("give feature_ids or a region, not both")
        return self


class AnnotationListRow(BaseModel):
    id: str
    tool: str
    tool_version: str
    database_name: str | None
    database_version: str | None
    created_at: dt.datetime
    sample_id: str
    sample_code: str
    project_id: str
    project_name: str
    is_demo: bool
    assembly_id: str
    assembler: str
    assembler_version: str
    assembly_kind: str
    sequences: int
    total_length: int
    features: int | None
    cds: int | None
    synthetic_evidence: list[str]


# --- Genome Explorer -----------------------------------------------------------------------------------------------

class GcTrackRead(BaseModel):
    window: int = Field(description="Window length, bp")
    step: int = Field(description="Distance between window starts, bp")
    auto: bool = Field(description="Window chosen by ARVA for the view (step = window)")
    windows: int = Field(description="Windows computed")
    group: int = Field(description="Windows per point (1: one window per point)")
    contig_gc: float | None = Field(description="(G+C)/(A+C+G+T) of the whole sequence")
    start: list[int]
    end: list[int]
    gc: list[float | None]
    gc_min: list[float | None]
    gc_max: list[float | None]
    skew: list[float | None] = Field(description="(G-C)/(G+C)")
    skew_min: list[float | None]
    skew_max: list[float | None]


class CoverageTrackRead(BaseModel):
    available: bool
    reason: str | None = Field(default=None, description="Why not: no_alignment, profile_missing, contig_mismatch, "
                               "assembly_missing")
    job_id: str | None = None
    source: dict[str, Any] | None = Field(default=None, description="The polishing job, alignment, aligner, reads "
                                          "and samtools depth command")
    contig_mean_depth: float | None = None
    resolution: int | None = Field(default=None, description="Bin size of the stored depth profile, bp")
    group: int | None = None
    start: list[int] = []
    end: list[int] = []
    mean: list[float | None] = []
    min: list[float | None] = []
    max: list[float | None] = []


class GenomeTracksRead(BaseModel):
    contig: str
    contig_in_assembly: str
    length: int
    start: int
    end: int
    points: int
    sequence_source: dict[str, Any]
    gc: GcTrackRead
    coverage: CoverageTrackRead


class GenomeSequenceRead(BaseModel):
    contig: str
    contig_in_assembly: str
    start: int
    end: int
    strand: Literal["+", "-"]
    length: int
    sequence: str
    source: dict[str, Any]


class FeatureLayoutItem(BaseModel):
    id: int
    locus_tag: str | None
    tool_id: str | None
    type: str
    start: int
    end: int
    strand: str
    length: int
    edge: bool
    gene: str | None
    product: str | None
    hypothetical: bool | None
    pseudo: bool
    partial: str | None


class FeatureLayoutRead(BaseModel):
    contig: str
    contig_in_assembly: str
    length: int
    total: int
    items: list[FeatureLayoutItem]


class MapGcRead(BaseModel):
    contig_gc: float | None = Field(description="(G+C)/(A+C+G+T) of the whole sequence")
    start: list[int]
    end: list[int]
    gc: list[float | None]
    skew: list[float | None] = Field(description="(G-C)/(G+C)")


class MapCoverageRead(BaseModel):
    available: bool
    reason: str | None = None
    contig_mean_depth: float | None = None
    start: list[int] = []
    end: list[int] = []
    mean: list[float | None] = []


class MapSequenceRead(BaseModel):
    contig: str
    contig_in_assembly: str
    length: int
    topology: str | None
    gc: MapGcRead
    coverage: MapCoverageRead


class MapWindowRead(BaseModel):
    window: int = Field(description="Window length, bp, the same on every sequence")
    step: int
    auto: bool = Field(description="Window chosen by ARVA for the number of points asked")
    genome_gc: float | None = Field(description="(G+C)/(A+C+G+T) over the sequences of the map")


class MapCoverageSummary(BaseModel):
    available: bool
    reason: str | None = None
    source: dict[str, Any] | None = None


class MapFeatureItem(FeatureLayoutItem):
    contig: str


class GenomeMapRead(BaseModel):
    total_length: int
    points: int
    sequence_source: dict[str, Any]
    gc: MapWindowRead
    coverage: MapCoverageSummary
    sequences: list[MapSequenceRead]
    total: int
    features: list[MapFeatureItem]


# --- Annotation charts ------------------------------------------------------------------------------------------

class LengthClassStats(BaseModel):
    n: int
    min: int | None
    median: float | None
    mean: float | None
    max: int | None


class LengthBin(BaseModel):
    min: int
    max: int | None = Field(description="Exclusive upper bound; None for the last, open bin")
    cds_characterised: int
    cds_hypothetical: int
    sorf: int
    rna: int


class LengthHistogramRead(BaseModel):
    width: int | None
    bins: list[LengthBin]
    classes: dict[str, LengthClassStats]


class DensityContigRead(BaseModel):
    contig: str
    contig_in_assembly: str
    length: int
    start: list[int]
    end: list[int]
    forward: list[int]
    reverse: list[int]
    unstranded: list[int]
    total: list[int]
    genes: int


class DensityRead(BaseModel):
    window: int
    contigs: list[DensityContigRead]


class StrandRead(BaseModel):
    by_type: dict[str, dict[str, int]]
    by_contig: list[dict[str, Any]]
    total: dict[str, int]
    replication_strand: Literal["not_determined"]


class CogCategoryRead(BaseModel):
    letter: str
    name: str | None
    cds: int


class CogProfileRead(BaseModel):
    cds_searched: bool
    cds: int | None
    reported: bool
    cds_with_category: int
    cds_with_cog_id: int
    categories: list[CogCategoryRead]
    names_source: str


class HypotheticalRead(BaseModel):
    cds_searched: bool
    by_contig: list[dict[str, Any]]
    total: dict[str, int] | None


class TypeCountsRead(BaseModel):
    types: list[str]
    total: dict[str, int]
    by_contig: list[dict[str, Any]]


class AnnotationChartsRead(BaseModel):
    cds_searched: bool
    genes: int
    lengths: LengthHistogramRead
    density: DensityRead
    strand: StrandRead
    cog: CogProfileRead
    hypothetical: HypotheticalRead
    types: TypeCountsRead


# --- MLST -----------------------------------------------------------------------

_SCHEME = r"^[A-Za-z0-9_]{1,64}$"


class MlstPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme: str | None = Field(default=None, pattern=_SCHEME, description="A bundled scheme; default: mlst detects it")


class MlstSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme: str | None = Field(default=None, pattern=_SCHEME, description="--scheme (mlst then uses minimum score 0 "
                               "and no excluded schemes); default: automatic detection")
    minid: float = Field(default=95.0, gt=0, le=100, description="--minid, DNA % identity of a full-length allele "
                         "to call it similar (~); mlst's default 95")
    mincov: float = Field(default=50.0, gt=0, le=100, description="--mincov, % of an allele covered to call a "
                          "partial match (?); mlst's default 50")
    minscore: float = Field(default=50.0, ge=0, le=100, description="--minscore, minimum score of a detected scheme "
                            "(mlst's default 50; 0 with a chosen scheme)")
    exclude: list[Annotated[str, Field(pattern=_SCHEME)]] | None = Field(
        default=None, max_length=200, description="--exclude; default: mlst's own list (ecoli, abaumannii, "
        "vcholerae_2, senterica_achtman_2)")


class MlstRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: MlstSettingsIn = MlstSettingsIn()
    threads: int | None = Field(default=None, ge=1, le=256)
    confirmed: bool


class MlstProblem(BaseModel):
    code: str
    message: str
    params: dict[str, Any] = {}


class MlstSchemeRead(BaseModel):
    name: str
    loci: list[str]
    source: str | None
    download_date: str | None
    last_updated: str | None
    clonal_complex: bool = Field(description="The scheme's profile file has a clonal_complex or CC column")


class MlstAssemblyFacts(BaseModel):
    assembly_id: str
    kind: str
    assembler: str
    assembler_version: str
    parent_assembly_id: str | None
    job_id: str
    contigs_sha256: str
    created_at: dt.datetime
    contigs: int
    total_length: int | None
    synthetic_evidence: list[str]


class MlstPlanRead(BaseModel):
    tool: AnnotationToolRead
    database: dict[str, Any] | None
    schemes: list[MlstSchemeRead]
    defaults: dict[str, str] = Field(description="mlst 2.35.0's defaults, as ARVA passes them")
    tool_defaults: dict[str, str] = Field(description="The defaults the installed mlst's --help states")
    defaults_match: bool | None
    assembly: MlstAssemblyFacts
    scheme: str | None
    problems: list[MlstProblem]


class MlstAlleleRead(BaseModel):
    locus: str
    call: str = Field(description="mlst's notation: n, ~n, n?, -, n,m or 0")
    type: Literal["exact", "novel", "partial", "missing", "multiple", "null", "unrecognised"]
    alleles: list[str]
    similar_to: str | None


class MlstWarningRead(BaseModel):
    code: str
    params: dict[str, Any] = {}


class MlstResultRead(ORMModel):
    id: str
    sample_id: str
    assembly_id: str
    job_id: str
    tool: str
    tool_version: str
    database_key: str | None
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    parameters: dict[str, Any]
    scheme: str | None
    st: str | None
    status: str
    score: int
    alleles: list[MlstAlleleRead]
    clonal_complex: dict[str, Any]
    warnings: list[MlstWarningRead]
    details: dict[str, Any]
    files: dict[str, AnnotationFileRead]
    created_at: dt.datetime


class MlstRow(BaseModel):
    id: str
    sample_id: str
    sample_code: str
    project_id: str
    project_name: str
    is_demo: bool
    assembly_id: str
    assembler: str
    assembler_version: str
    assembly_kind: str
    scheme: str | None
    st: str | None
    status: str
    score: int
    alleles: list[MlstAlleleRead]
    clonal_complex: dict[str, Any]
    warnings: list[MlstWarningRead]
    tool: str
    tool_version: str
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    created_at: dt.datetime


class MlstProjectSampleRow(BaseModel):
    sample_id: str
    sample_code: str
    results: int
    latest: MlstRow | None


class MlstTypeCount(BaseModel):
    scheme: str | None
    st: str | None
    samples: int


class MlstProjectOverviewRead(BaseModel):
    project_id: str
    project_name: str
    is_demo: bool
    samples: list[MlstProjectSampleRow]
    sequence_types: list[MlstTypeCount]


class MlstProjectCount(BaseModel):
    project_id: str
    project_name: str
    is_demo: bool
    samples: int
    typed_samples: int


class MlstOverviewRead(BaseModel):
    projects: list[MlstProjectCount]
    recent: list[MlstRow]
    total_results: int


# --- Species identification -------------------------------------------------------------------------------------

SpeciesMethod = Literal["fastani", "skani", "mash", "sylph", "gtdbtk"]


class SpeciesPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: SpeciesMethod
    database_id: str | None = Field(default=None, max_length=36, description="A database of the method's kind; "
                                    "default: the default database of that kind")


class SpeciesRequest(SpeciesPreviewRequest):
    threads: int | None = Field(default=None, ge=1, le=256)
    confirmed: bool


class SpeciesProblem(BaseModel):
    code: str
    message: str
    params: dict[str, Any] = {}


class SpeciesToolRead(AnnotationToolRead):
    id: str
    name: str
    memory_gb: int


class SpeciesPlanRead(BaseModel):
    method: SpeciesMethod
    methods: dict[str, dict[str, str]] = Field(description="Every method with its tool, database kind and how far "
                                               "ARVA validated it (validated, test_database, not_validated)")
    tool: SpeciesToolRead
    validation: str
    database_kind: str
    databases: list[dict[str, Any]]
    database: dict[str, Any] | None
    assembly: MlstAssemblyFacts
    context: dict[str, Any] = Field(description="The MLST call and the organism given for an annotation of this "
                                    "assembly, used for the consistency checks")
    problems: list[SpeciesProblem]
    gtdbtk_memory_gb: dict[str, int] | None


class SpeciesHitRead(BaseModel):
    rank: int
    reference: str | None
    accession: str | None
    organism: str | None
    species: str | None
    strain: str | None = None
    type_material: bool | None = None
    type_label: str | None = None
    refseq_category: str | None = None
    ani: float | None = None
    af: float | None = Field(default=None, description="Aligned fraction used by ARVA (FastANI: mapped / total query "
                             "fragments; skani: the smaller of its two; sylph: containment), 0 to 1")
    af_query: float | None = None
    af_reference: float | None = None
    fragments_mapped: int | None = None
    fragments_total: int | None = None
    distance: float | None = None
    p_value: float | None = None
    shared: int | None = None
    hashes: int | None = None
    naive_ani: float | None = None
    adjusted_ani: float | None = None
    eff_lambda: str | None = None
    eff_cov: str | None = None
    containment_shared: int | None = None
    containment_sampled: int | None = None
    taxonomic_abundance: float | None = None


class SpeciesResultRead(ORMModel):
    id: str
    sample_id: str
    assembly_id: str
    job_id: str
    method: SpeciesMethod
    tool: str
    tool_version: str
    database_kind: str | None
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    parameters: dict[str, Any]
    status: str
    species: str | None
    hits: list[SpeciesHitRead]
    interpretation: dict[str, Any]
    consistency: list[dict[str, Any]]
    warnings: list[MlstWarningRead]
    details: dict[str, Any]
    files: dict[str, AnnotationFileRead]
    created_at: dt.datetime


class SpeciesRow(BaseModel):
    id: str
    sample_id: str
    sample_code: str
    project_id: str
    project_name: str
    is_demo: bool
    assembly_id: str
    assembler: str
    assembler_version: str
    assembly_kind: str
    method: SpeciesMethod
    tool: str
    tool_version: str
    status: str
    species: str | None
    best: dict[str, Any] | None
    runner_up: dict[str, Any] | None
    reasons: list[dict[str, Any]]
    consistency: list[dict[str, Any]]
    warnings: list[MlstWarningRead]
    database_name: str | None
    database_version: str | None
    created_at: dt.datetime


class SpeciesProjectSampleRow(BaseModel):
    sample_id: str
    sample_code: str
    results: int
    latest: SpeciesRow | None


class SpeciesCount(BaseModel):
    status: str
    species: str | None
    samples: int


class SpeciesProjectOverviewRead(BaseModel):
    project_id: str
    project_name: str
    is_demo: bool
    samples: list[SpeciesProjectSampleRow]
    species: list[SpeciesCount]


class SpeciesProjectCount(BaseModel):
    project_id: str
    project_name: str
    is_demo: bool
    samples: int
    identified_samples: int


class SpeciesOverviewRead(BaseModel):
    projects: list[SpeciesProjectCount]
    recent: list[SpeciesRow]
    total_results: int


# --- Reference collections from NCBI Datasets --------------------------------------------------------------------

class NcbiFiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["refseq", "genbank", "all"] = Field(default="refseq", description="filters.assembly_source")
    type_material: bool = Field(default=False, description="filters.is_type_material: genomes from type material only")
    reference_only: bool = Field(default=False, description="filters.reference_only: reference genomes only")
    exclude_atypical: bool = Field(default=True, description="filters.exclude_atypical")
    exact_taxon: bool = Field(default=False, description="tax_exact_match: the taxon itself, not its child taxa")


class NcbiPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxon: str = Field(min_length=1, max_length=100, description="A genus or species name, or an NCBI Taxonomy id")
    tax_id: int | None = Field(default=None, ge=1, le=9_999_999_999, description="The taxon chosen when the name "
                               "matched several")
    filters: NcbiFiltersIn = NcbiFiltersIn()
    destination: str | None = Field(default=None, max_length=4096)
    folder: str | None = Field(default=None, max_length=400)


class NcbiStartRequest(NcbiPlanRequest):
    tax_id: int = Field(ge=1, le=9_999_999_999)
    confirm_genomes: int = Field(ge=1, description="The number of genomes the plan showed")
    confirm_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$", description="The plan's accession-list fingerprint")


class NcbiTaxonRead(BaseModel):
    tax_id: int
    name: str
    rank: str | None
    bacterial: bool


class NcbiPlanRead(BaseModel):
    status: Literal["ready", "choose_taxon", "too_many", "no_genomes"]
    query: str
    filters: dict[str, Any]
    candidates: list[NcbiTaxonRead]
    taxon: NcbiTaxonRead | None
    total_count: int | None = None
    limit: int | None = None
    query_url: str | None = None
    genomes: int = 0
    fingerprint: str | None = None
    species: int | None = None
    unclassified: int | None = None
    by_species: list[dict[str, Any]] = []
    type_material: int | None = None
    reference_genomes: int | None = None
    preview: list[dict[str, Any]] = []
    download: dict[str, Any] | None = None
    zip_estimate_bytes: int | None = None
    fasta_estimate_bytes: int | None = None
    required_bytes: int | None = None
    db_dir: str | None = None
    folder: str | None = None
    target_path: str | None = None
    host_target_path: str | None = None
    free_bytes: int | None = None
    available_bytes: int | None = None
    enough: bool | None = None
    target_exists: bool | None = None


# --- Error log and diagnostics ----------------------------------------------------------------------------------

_ENTRY_ID = r"^[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}$"
_CORRELATION = r"^[0-9a-f]{16}$"


class ErrorEntryRead(BaseModel):
    """One error log entry as Settings → Diagnostics lists it (the full entry is in the diagnostic report)."""
    id: str
    time: str
    component: str
    severity: str
    code: str
    message: str
    params: dict[str, Any] = {}
    route: str | None = None
    job_id: str | None = None
    job_type: str | None = None
    correlation_id: str | None = None


class ClientApiFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(max_length=300, description="The request's path; only its shape is kept (ids and names "
                                                  "replaced), never the query")
    status: int = Field(ge=0, le=599, description="0: no response (network error)")
    code: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    error_id: str | None = Field(default=None, pattern=_ENTRY_ID)
    correlation_id: str | None = Field(default=None, pattern=_CORRELATION)


class ClientErrorReport(BaseModel):
    """An error of the web interface (POST /system/client-errors): bounded, every text redacted before it is kept."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["boundary", "window_error", "unhandled_rejection", "api"]
    message: str = Field(max_length=1000)
    name: str | None = Field(default=None, max_length=100)
    stack: str | None = Field(default=None, max_length=8000)
    component_stack: str | None = Field(default=None, max_length=4000)
    page: str | None = Field(default=None, max_length=300, description="The interface's route; only its shape is "
                                                                     "kept")
    api: ClientApiFailure | None = None
    client_commit: str | None = Field(default=None, pattern=r"^([0-9a-f]{7,40}|unknown)$")
    user_agent: str | None = Field(default=None, max_length=300)


class ClientErrorLogged(BaseModel):
    id: str
    duplicate: bool = False


# --- AMR detection (AMRFinderPlus) -------------------------------------------------------------------------------

_ORGANISM = r"^[A-Z][a-z]+(?:_[a-z]+)?$"


class AmrPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str | None = Field(default=None, max_length=36, description="An AMRFinderPlus database; default: the "
                                    "default one this AMRFinderPlus reads")
    annotation_id: str | None = Field(default=None, max_length=36, description="For a combined search: one of the "
                                      "assembly's annotations (Bakta or Prokka, with CDS)")


class AmrSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["nucleotide", "combined"] = Field(default="nucleotide", description="nucleotide: the contigs "
                                                    "(--nucleotide); combined: the contigs, proteins and GFF of an "
                                                    "annotation (--nucleotide --protein --gff --annotation_format)")
    organism: str | None = Field(default=None, pattern=_ORGANISM, description="--organism, one of the database's "
                                 "options (amrfinder --list_organisms): point mutations and organism-specific "
                                 "filtering; none: point mutations are not searched")
    plus: bool = Field(default=True, description="--plus: also stress response and virulence genes")
    ident_min: float = Field(default=-1, description="--ident_min; -1 (the default) uses the curated thresholds")
    coverage_min: float = Field(default=0.5, gt=0, le=1, description="--coverage_min, AMRFinderPlus's default 0.5")
    translation_table: int = Field(default=11, ge=1, le=33, description="--translation_table, default 11")


class AmrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: AmrSettingsIn = AmrSettingsIn()
    database_id: str | None = Field(default=None, max_length=36)
    annotation_id: str | None = Field(default=None, max_length=36)
    threads: int | None = Field(default=None, ge=1, le=256)
    confirmed: bool


class AmrProblem(BaseModel):
    code: str
    message: str
    params: dict[str, Any] = {}


class AmrPlanRead(BaseModel):
    tool: AnnotationToolRead
    database: dict[str, Any] | None
    databases: list[dict[str, Any]]
    bakta_copies: list[dict[str, Any]] = Field(description="AMRFinderPlus data inside Bakta databases and whether "
                                               "this AMRFinderPlus reads them")
    database_check: dict[str, Any] | None
    organisms: list[str] = Field(description="amrfinder --list_organisms for the chosen database")
    organism: dict[str, Any] = Field(description="The organism ARVA proposes from the species identification, the "
                                     "rule it used (species, wiki_note, genus) and the species result")
    annotations: list[dict[str, Any]]
    defaults: dict[str, str] = Field(description="AMRFinderPlus 4.2.7's defaults, as ARVA passes them")
    tool_defaults: dict[str, str]
    defaults_match: bool | None
    assembly: dict[str, Any]
    problems: list[AmrProblem]


class AmrHitRead(BaseModel):
    id: str
    job_id: str
    annotation_id: str | None
    element_symbol: str
    element_name: str | None
    scope: str | None
    type: str
    subtype: str | None
    amr_class: str | None
    amr_subclass: str | None
    method: str
    method_kind: str
    identity: float | None
    coverage: float | None
    target_length: int | None
    reference_length: int | None
    alignment_length: int | None
    contig: str | None
    assembly_contig: str | None
    start: int | None
    stop: int | None
    strand: str | None
    protein_id: str | None
    closest_accession: str | None
    closest_name: str | None
    hmm_accession: str | None
    hmm_description: str | None
    hierarchy_node: str | None
    feature: dict[str, Any] | None


class AmrRunRead(BaseModel):
    job_id: str
    sample_id: str | None
    assembly_id: str | None
    annotation_id: str | None
    status: str
    created_at: dt.datetime
    finished_at: dt.datetime | None
    tool: str
    tool_version: str
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    database_path: str | None
    parameters: dict[str, Any]
    organism_choice: dict[str, Any] | None
    mode: str | None
    warnings: list[dict[str, Any]]
    counts: dict[str, int]
    point_mutation_screen: dict[str, Any] | None
    files: dict[str, Any]
    log: dict[str, Any]
    hits: list[AmrHitRead]
    by_class: list[dict[str, Any]]


class AmrProjectOverviewRead(BaseModel):
    project_id: str
    project_name: str
    is_demo: bool
    samples: list[dict[str, Any]]
    elements: list[dict[str, Any]]
    searched: int
    versions: list[str]


class AmrMapHitRead(AmrHitRead):
    end: int | None


class AmrAnnotationHitsRead(BaseModel):
    run: dict[str, Any] | None
    hits: list[AmrMapHitRead]


class AmrReleaseRead(BaseModel):
    version: str
    modified: str
    compatibility: str


class AmrReleasesRead(BaseModel):
    tool_version: str
    minor: str
    url: str
    releases: list[AmrReleaseRead]


class AmrReleasePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}\.\d+$")
    destination: str | None = Field(default=None, max_length=4096)
    folder: str | None = Field(default=None, max_length=400)


class AmrReleaseStartRequest(AmrReleasePlanRequest):
    confirm_bytes: int = Field(ge=0, description="The download size the plan showed (from NCBI's listing)")
    accept_terms: bool


class AmrReleasePlanRead(BaseModel):
    version: str
    minor: str
    tool_version: str
    url: str
    files: list[dict[str, Any]]
    missing: list[str]
    download_bytes: int
    required_bytes: int
    db_dir: str
    folder: str
    target_path: str
    host_target_path: str
    free_bytes: int
    available_bytes: int
    enough: bool
    blocked_by: str | None
    blocked_code: str | None
    compatibility: str
    needs_data: str | None
    licence: str
    checksums_published: bool
    index_command: str


# --- Plasmids and mobile elements (MOB-suite, PlasmidFinder, IntegronFinder, ISEScan, geNomad), VFDB --------------

MobileMethod = Literal["mobsuite", "plasmidfinder", "integronfinder", "isescan", "genomad"]


class MobSettingsIn(BaseModel):
    """mob_recon's thresholds (each passed explicitly; MOB-suite 3.1.9's defaults)."""
    model_config = ConfigDict(extra="forbid")

    min_length: int = Field(default=1000, ge=1, le=1_000_000, description="--min_length: shortest BLAST alignment kept")
    min_rep_ident: int = Field(default=80, ge=1, le=100)
    min_mob_ident: int = Field(default=80, ge=1, le=100)
    min_con_ident: int = Field(default=80, ge=1, le=100)
    min_rpp_ident: int = Field(default=80, ge=1, le=100)
    min_rep_cov: int = Field(default=80, ge=1, le=100)
    min_mob_cov: int = Field(default=80, ge=1, le=100)
    min_con_cov: int = Field(default=60, ge=1, le=100)
    min_rpp_cov: int = Field(default=80, ge=1, le=100)
    min_rep_evalue: float = Field(default=1e-05, gt=0, le=10)
    min_mob_evalue: float = Field(default=1e-05, gt=0, le=10)
    min_con_evalue: float = Field(default=1e-05, gt=0, le=10)
    min_rpp_evalue: float = Field(default=1e-05, gt=0, le=10)
    min_overlap: int = Field(default=10, ge=0, le=10_000)
    max_contig_size: int = Field(default=450000, ge=1000, le=10_000_000)
    max_plasmid_size: int = Field(default=450000, ge=1000, le=10_000_000)
    primary_cluster_dist: float = Field(default=0.06, ge=0, le=1)
    secondary_cluster_dist: float = Field(default=0.025, ge=0, le=1)


class AbricateSettingsIn(BaseModel):
    """ABRicate's thresholds (--minid, --mincov; its defaults 80 and 80)."""
    model_config = ConfigDict(extra="forbid")

    minid: float = Field(default=80, gt=0, le=100)
    mincov: float = Field(default=80, ge=0, le=100)


class IntegronSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_max: bool = Field(default=True, description="--local-max: thorough local search for attC sites (slower)")
    promoter_attI: bool = Field(default=False, description="--promoter-attI: also the Pc promoter and attI site")
    distance_thresh: int = Field(default=4000, ge=1, le=100_000)
    evalue_attc: float = Field(default=1.0, gt=0, le=10)
    calin_threshold: int = Field(default=2, ge=1, le=100)
    max_attc_size: int = Field(default=200, ge=2, le=1000)
    min_attc_size: int = Field(default=40, ge=1, le=999)


class IsescanSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remove_short_is: bool = Field(default=False, description="--removeShortIS: report only complete IS elements")


class GenomadSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_score: float = Field(default=0.7, ge=0, le=1)
    min_number_genes: int = Field(default=1, ge=0, le=1000)
    min_plasmid_marker_enrichment: float = Field(default=0.1, ge=-100, le=100)
    min_virus_marker_enrichment: float = Field(default=0.0, ge=-100, le=100)
    min_plasmid_hallmarks: int = Field(default=0, ge=0, le=1000)
    min_plasmid_hallmarks_short_seqs: int = Field(default=1, ge=0, le=1000)
    min_virus_hallmarks: int = Field(default=0, ge=0, le=1000)
    min_virus_hallmarks_short_seqs: int = Field(default=1, ge=0, le=1000)
    max_uscg: int = Field(default=4, ge=0, le=1000)
    sensitivity: float = Field(default=4.2, gt=0, le=7.5)
    splits: int = Field(default=0, ge=0, le=1000)


MOBILE_SETTINGS = {"mobsuite": MobSettingsIn, "plasmidfinder": AbricateSettingsIn, "integronfinder": IntegronSettingsIn,
                   "isescan": IsescanSettingsIn, "genomad": GenomadSettingsIn}


class MobilePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: MobileMethod
    database_id: str | None = Field(default=None, max_length=36)


class MobileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: MobileMethod
    settings: dict[str, bool | int | float] = Field(default={}, description="The method's settings (validated against "
                                                    "its own model: MobSettingsIn, AbricateSettingsIn, ...)")
    database_id: str | None = Field(default=None, max_length=36)
    threads: int | None = Field(default=None, ge=1, le=256)
    confirmed: bool


class MobileToolRead(AnnotationToolRead):
    id: str
    name: str


class MobilePlanRead(BaseModel):
    method: str
    tool: MobileToolRead
    database: dict[str, Any] | None
    databases: list[dict[str, Any]]
    models: dict[str, Any] | None = Field(description="The models the tool bundles, when it reads no database")
    defaults: dict[str, str] = Field(description="ARVA's settings, each passed explicitly")
    tool_defaults: dict[str, str]
    defaults_match: bool | None
    assembly: dict[str, Any]
    circularity: dict[str, dict[str, Any]] = Field(description="The assembler's circularity flag of each contig")
    problems: list[AmrProblem]


class MobileRowRead(BaseModel):
    id: str
    job_id: str
    tool: str
    category: str
    element: str | None
    element_type: str | None
    contig: str | None
    start: int | None
    end: int | None
    strand: str | None
    identity: float | None
    coverage: float | None
    score: float | None
    completeness: str | None
    details: dict[str, Any] | None
    feature: dict[str, Any] | None


class MobileRunRead(BaseModel):
    job_id: str
    sample_id: str | None
    assembly_id: str | None
    method: str | None
    status: str
    created_at: dt.datetime
    finished_at: dt.datetime | None
    tool: str
    tool_version: str
    database_kind: str | None
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    database_path: str | None
    parameters: dict[str, Any]
    warnings: list[dict[str, Any]]
    counts: dict[str, Any]
    files: dict[str, Any]
    searched_contigs: list[str]
    rows: list[MobileRowRead]


class MobileSampleRead(BaseModel):
    runs: list[MobileRunRead]
    assemblies: list[dict[str, Any]] = Field(description="Per assembly: each contig with MOB-suite's call, the "
                                             "replicons, element counts and the assembler's circularity")


class MobileProjectRead(BaseModel):
    project_id: str
    project_name: str
    is_demo: bool
    samples: list[dict[str, Any]]
    searched: dict[str, int]


class MobileAnnotationRead(BaseModel):
    runs: dict[str, Any]
    contigs: list[dict[str, Any]]
    elements: list[dict[str, Any]]


class VirulenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: AbricateSettingsIn = AbricateSettingsIn()
    threads: int | None = Field(default=None, ge=1, le=256)
    confirmed: bool


class VirulencePlanRead(BaseModel):
    tool: AnnotationToolRead
    database: dict[str, Any] | None
    defaults: dict[str, str]
    tool_defaults: dict[str, str]
    defaults_match: bool | None
    assembly: dict[str, Any]
    problems: list[AmrProblem]


class VirulenceRunRead(BaseModel):
    job_id: str
    sample_id: str | None
    assembly_id: str | None
    status: str
    created_at: dt.datetime
    finished_at: dt.datetime | None
    tool: str
    tool_version: str
    database_name: str | None
    database_version: str | None
    database_checksum: str | None
    database_path: str | None
    parameters: dict[str, Any]
    database_terms: dict[str, Any]
    warnings: list[dict[str, Any]]
    counts: dict[str, Any]
    files: dict[str, Any]
    hits: list[dict[str, Any]]


class VirulenceSampleRead(BaseModel):
    runs: list[VirulenceRunRead]
    assemblies: list[dict[str, Any]] = Field(description="Per assembly: VFDB and AMRFinderPlus virulence rows side by "
                                             "side, each with its source")


class VirulenceAnnotationRead(BaseModel):
    run: dict[str, Any] | None
    hits: list[dict[str, Any]]
