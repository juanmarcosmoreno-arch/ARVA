"""API request/response schemas."""
import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.models import (
    AssemblyMode,
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
    progress: JobProgress | None = Field(default=None, description="Live monitoring of a long tool run (e.g. Flye)")
    cancel_requested_at: dt.datetime | None = Field(
        default=None, description="When cancelling was asked; a running job stays 'running' until the worker stops it")
    checkpoint: JobCheckpoint | None = None


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
    options: list[str] = Field(description="Optional Flye options this installed version lists in its --help")
    max_threads: int


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
    options: list[str] = Field(description="Options of interest this installed version lists in its help")
    max_threads: int
    max_memory_gb: int = Field(description="Most memory ARVA may give a run (ARVA_TOOL_MEMORY_GB or physical memory)")
    default_memory_gb: int = Field(description="Used when no memory is given: min(250, max_memory_gb), as SPAdes does")


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
    aligner: QuastAligner | None
    max_threads: int
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
    max_memory_gb: int
    default_heap_gb: int
