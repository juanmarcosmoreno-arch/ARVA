// Mirrors apps/api/app/schemas/schemas.py and arva_core.seqstats output.
import type { ServerMessage } from "./messages";


export type SequencingTechnology = "illumina" | "nanopore" | "pacbio" | "hybrid" | "unknown";
export type FileFormat = "fastq" | "fastq_gz" | "fasta" | "fasta_gz" | "pod5" | "unknown";
export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  institution: string | null;
  researcher: string | null;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  sample_count: number;
}

export interface ProjectInput {
  name: string;
  description?: string | null;
  institution?: string | null;
  researcher?: string | null;
}

export interface SampleInput {
  sample_code: string;
  organism?: string | null;
  expected_species?: string | null;
  sample_type?: string | null;
  host?: string | null;
  geographic_origin?: string | null;
  collection_date?: string | null;
  sequencing_technology?: SequencingTechnology;
  sequencing_run?: string | null;
  researcher?: string | null;
  institution?: string | null;
  description?: string | null;
  notes?: string | null;
  custom_metadata?: Record<string, unknown> | null;
}

export interface Sample extends Required<Omit<SampleInput, "sequencing_technology">> {
  id: string;
  project_id: string;
  project_name: string | null;
  sequencing_technology: SequencingTechnology;
  /** Free-form metadata, e.g. the custom columns of an imported table. */
  custom_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  file_count: number;
}

export interface RawFile {
  id: string;
  sample_id: string;
  original_filename: string;
  file_format: FileFormat;
  read_mate: string | null;
  size_bytes: number;
  checksum_sha256: string | null;
  is_valid: boolean;
  validation_message: string | null;
  uploaded_at: string;
  origin: "imported" | "derived";
  parent_file_id: string | null;
  produced_by_job_id: string | null;
  description: string | null;
  header_metadata: HeaderMetadata | null;
}

export type HeaderConfidence = "high" | "medium" | "low" | "none";
export type HeaderPlatform = "illumina" | "nanopore" | "pacbio";

export interface DistinctValues {
  values: string[];
  n_distinct: number;
  truncated: boolean;
}

/** arva_core.header_meta.summarise() of a file's first read headers. Suggestions only. */
export interface HeaderMetadata {
  schema: string;
  n_headers_read: number;
  n_usable: number;
  platform_counts: Record<string, number>;
  confidence_by_platform: Record<string, Record<string, number>>;
  format_counts: Record<string, number>;
  mates: Record<string, number>;
  mate_layout: string;
  illumina_read_numbers: Record<string, number>;
  illumina_is_filtered: Record<string, number>;
  distinct: Record<string, DistinctValues>;
  warning_counts: Record<string, number>;
  evidence: Record<string, string[]>;
  sources: Record<string, string[]>;
  suggested_technology: {
    value: HeaderPlatform | null;
    confidence: HeaderConfidence;
    agreement: number;
    conflicting_headers: number;
    reason: string;
    overrides_user_metadata: false;
  };
}

export type MateCheckNote = "same_read_names" | "different_read_names" | "mate_markers_conflict" | "not_analysed" | "nothing_compared";

export interface MateCheck {
  r1_file_id: string;
  r2_file_id: string;
  looks_like_pair: boolean | null;
  matched: number;
  compared: number;
  note: MateCheckNote;
}

export interface HeaderSummary {
  suggested_technology: {
    value: SequencingTechnology | null;
    confidence: HeaderConfidence;
    basis: "single_platform" | "short_and_long_reads" | "conflicting_platforms" | "no_evidence";
    platforms: string[];
    files_considered: number;
    files_with_evidence: number;
  };
  per_file: { file_id: string; name: string; analysed: boolean; platform: HeaderPlatform | null; confidence: HeaderConfidence; format: string | null }[];
  mate_check: MateCheck[];
  user_technology: SequencingTechnology;
  agrees: boolean | null;
}

export type ToolStatus = "available" | "not_installed" | "incompatible" | "failed";

export interface Tool {
  id: string;
  name: string;
  description: string;
  homepage: string;
  license: string;
  citation: string;
  citation_url: string;
  categories: string[];
  input_formats: string[];
  output_formats: string[];
  min_version: string;
  tested_versions: string[];
  install: Record<string, string>;
  status: ToolStatus;
  path: string | null;
  version: string | null;
  version_validated: boolean;
  message: string;
  /** Stable code of a tool-specific message (translated as tool.reason.<code>). */
  reason?: string | null;
}

export interface Library {
  id: string;
  name: string;
  homepage: string;
  license: string;
  citation: string;
  citation_url: string;
  required_version: string;
  install: string;
  status: "available" | "not_installed";
  version: string | null;
  companion_versions: Record<string, string | null>;
  version_validated: boolean;
}

/** One acquisition of a POD5 file (fields that may identify people or devices are not included). */
export interface Pod5RunInfo {
  acquisition_id: string | null;
  acquisition_start_time: string | null;
  protocol_start_time: string | null;
  sample_id: string | null;
  experiment_name: string | null;
  flow_cell_id: string | null;
  flow_cell_product_code: string | null;
  sequencing_kit: string | null;
  protocol_name: string | null;
  protocol_run_id: string | null;
  sample_rate: number | null;
  software: string | null;
  system_type: string | null;
  sequencer_position_type: string | null;
  reads: number;
  samples: number;
  signal_duration_s: number | null;
}

/** result_summary of a pod5_summary job (apps/api/app/tasks/pod5_summary.py). */
export interface Pod5Summary {
  schema: string;
  file: {
    writing_software: string;
    file_identifier: string;
    file_version: string;
    original_file_version: string;
    is_vbz_compressed: boolean;
    batch_count: number;
    num_reads: number;
  };
  reads: {
    count: number;
    total_samples: number;
    min_samples: number | null;
    max_samples: number | null;
    distinct_channels: number | null;
    acquisitions: number;
    total_signal_duration_s: number | null;
  };
  run_info_count: number;
  run_infos: Pod5RunInfo[];
  run_infos_truncated: boolean;
  /** Plain strings in summaries written before warnings had codes. */
  warnings: (ServerMessage | string)[];
  withheld_fields: string[];
}

export interface FastpParams {
  adapter_trimming: boolean;
  detect_adapter_for_pe: boolean;
  /** Upper-case A/C/G/T, 4–200 bases; null keeps fastp's own adapter handling. */
  adapter_sequence: string | null;
  adapter_sequence_r2: string | null;
  quality_filtering: boolean;
  qualified_quality_phred: number;
  unqualified_percent_limit: number;
  n_base_limit: number;
  average_qual: number;
  low_complexity_filter: boolean;
  complexity_threshold: number;
  length_filtering: boolean;
  length_required: number;
  /** Discards reads longer than this after trimming (0 = off). */
  length_limit: number;
  trim_front1: number;
  trim_tail1: number;
  /** Trims read 1 to this length (0 = off); no read is removed. */
  max_len1: number;
  /** Paired end only; null follows read 1 (ARVA passes the value explicitly). */
  trim_front2: number | null;
  trim_tail2: number | null;
  max_len2: number | null;
  cut_front: boolean;
  cut_tail: boolean;
  cut_window_size: number;
  cut_mean_quality: number;
  poly_g: "auto" | "force" | "disable";
  dedup: boolean;
}

export interface FiltlongParams {
  min_length: number | null;
  max_length: number | null;
  min_mean_q: number | null;
  min_window_q: number | null;
  keep_percent: number | null;
  target_bases: number | null;
  length_weight: number;
  mean_q_weight: number;
  window_q_weight: number;
  window_size: number;
}

export interface FastpSummary {
  fastp_version: string;
  sequencing: string;
  before_filtering: { total_reads: number; total_bases: number; q20_rate: number; q30_rate: number; gc_content: number };
  after_filtering: { total_reads: number; total_bases: number; q20_rate: number; q30_rate: number; gc_content: number };
  filtering_result: Record<string, number>;
  adapter_trimmed_reads: number | null;
  adapter_trimmed_bases: number | null;
  read1_adapter_sequence: string | null;
  read2_adapter_sequence: string | null;
  duplication_rate: number | null;
  insert_size_peak: number | null;
  /** fastp's insert-size estimate without its histogram; absent for jobs that predate it. */
  insert_size?: Omit<NonNullable<FastpData["insert_size"]>, "histogram" | "histogram_percent"> | null;
}

/** Totals and target outcome parsed from Filtlong's log (keys absent when Filtlong did not print them). */
export interface FiltlongSummary {
  input_reads?: number;
  input_bases?: number;
  target_bases_reported?: number;
  kept_bases_reported?: number;
  not_enough_reads_for_target?: boolean;
  below_target_after_filtering?: boolean;
}

export interface FiltlongRequest {
  file_id: string;
  params: FiltlongParams;
  /** With target_coverage_x: the server sets target_bases = round(target_coverage_x × genome_size_bp). */
  genome_size_bp?: number | null;
  target_coverage_x?: number | null;
}

export interface FastqcSummary {
  fastqc_version: string | null;
  modules: { status: "PASS" | "WARN" | "FAIL" | string; module: string }[];
  basic_statistics: Record<string, string>;
}

/** fastqc_data.txt of one FastQC run, as served by GET /jobs/{id}/fastqc-data. Statuses are FastQC heuristics. */
export interface FastqcPosition {
  label: string;
  /** 1-based, inclusive */
  start: number;
  end: number;
}

export interface FastqcData {
  fastqc_version: string | null;
  total_sequences: number | null;
  max_read_length: number | null;
  modules: { module: string; status: string }[];
  adapter_content: {
    status: string;
    positions: FastqcPosition[];
    /** Cumulative % of reads with the adapter at or before each position; a binned position is a mean. */
    adapters: { name: string; percent: number[] }[];
  } | null;
  duplication: {
    status: string;
    total_deduplicated_percent: number;
    duplicate_percent: number;
    bins: { level: string; percent_of_total: number }[];
  } | null;
  overrepresented_sequences: {
    status: string;
    total: number;
    rows: { sequence: string; count: number; percent: number; possible_source: string }[];
    every_read_listed: boolean;
  } | null;
  unrecognised: string[];
  source: string;
}

export interface FastpCurves {
  total_reads: number | null;
  total_cycles: number | null;
  /** Mean Phred score per cycle: mean, A, T, C, G */
  quality: Record<string, number[]>;
  /** Fraction (0–1) of the bases at each cycle: A, T, C, G, GC, N */
  content: Record<string, number[]>;
}

export type FastpMate = "read1" | "read2";

/** fastp.json of one fastp run, as served by GET /jobs/{id}/fastp-data. */
export interface FastpData {
  fastp_version: string | null;
  sequencing: string | null;
  reads: Partial<Record<FastpMate, { before?: FastpCurves; after?: FastpCurves }>>;
  adapter_cutting: {
    adapter_trimmed_reads: number | null;
    adapter_trimmed_bases: number | null;
    read1_adapter_sequence: string | null;
    read2_adapter_sequence: string | null;
    read1_adapter_counts: { sequence: string; count: number }[];
    read2_adapter_counts: { sequence: string; count: number }[];
  } | null;
  /** Fraction (0–1), fastp's estimate */
  duplication_rate: number | null;
  insert_size: {
    peak: number | null;
    unknown: number;
    overlapping_pairs: number;
    evaluated_pairs: number;
    histogram: number[];
    histogram_percent: number[];
    unknown_percent: number | null;
    insert_size_max: number;
  } | null;
  threads: number | null;
}

/** NanoStats.txt (--tsv_stats) as parsed by arva_tools.nanoplot: NanoPlot's own definitions. */
export interface NanoplotStats {
  number_of_reads: number;
  number_of_bases: number;
  median_read_length: number;
  mean_read_length: number;
  read_length_stdev: number;
  n50: number;
  mean_qual: number;
  median_qual: number;
  /** Reads with mean quality strictly above the threshold; megabases rounded by NanoPlot to 0.1. */
  reads_above_quality: { threshold: number; reads: number; percent: number; megabases: number }[];
  longest_reads: { rank: number; length: number; quality: number }[];
  highest_quality_reads: { rank: number; quality: number; length: number }[];
  unparsed: string[];
}

export interface NanoplotSummary {
  nanoplot_version: string;
  stats: NanoplotStats;
  /** Only when NanoPlot removed reads itself (length < 20 and quality > 30). */
  post_filtering: NanoplotStats | null;
  artefact_reads_removed: number;
}

export type MultiqcModule = "fastqc" | "fastp" | "seqkit" | "filtlong";
export type MultiqcExclusionReason =
  | "no_outputs"
  | "derived_input"
  | "filtlong_without_target"
  | "output_missing"
  | "input_missing"
  | "input_invalid"
  | "input_not_validated";

export interface MultiqcPlannedInput {
  module: MultiqcModule;
  /** Sample name in the report: "<sample ID> <file>". */
  name: string;
  sample_id: string;
  sample_code: string;
  job_id: string;
  tool_name: string;
  tool_version: string;
  finished_at: string | null;
  file_ids: string[];
  file_names: string[];
  output_path: string;
}

export interface MultiqcExclusion {
  sample_id: string;
  sample_code: string;
  reason: MultiqcExclusionReason;
  module: MultiqcModule | null;
  job_id: string | null;
  file_names: string[];
}

/** POST /projects/{id}/analyses/multiqc/preview, and the parameters of a MultiQC job. */
export interface MultiqcPlan {
  selection_rule: string;
  modules: MultiqcModule[];
  sample_ids: string[];
  include_derived: boolean;
  inputs: MultiqcPlannedInput[];
  excluded: MultiqcExclusion[];
}

/** Unit of the raw value MultiQC parsed (not of the value its HTML table displays). */
export type MultiqcUnit = "reads" | "sequences" | "bases" | "bp" | "%" | "fraction" | "Phred";

export interface MultiqcColumn {
  module: MultiqcModule;
  key: string;
  title: string;
  description: string;
  unit: MultiqcUnit;
  /** "tool": copied from the tool's output; "multiqc": computed by MultiQC from it. */
  origin: "tool" | "multiqc";
  hidden: boolean;
}

/** result_summary of a multiqc job (apps/api/app/tasks/tools.py). */
export interface MultiqcSummary {
  multiqc_version: string;
  report_creation_date: string | null;
  modules: MultiqcModule[];
  samples: { name: string; sample_id: string; sample_code: string }[];
  versions: { reported_by_multiqc: Record<string, string>; arva_jobs: Record<string, string[]> };
  general_stats: {
    columns: MultiqcColumn[];
    rows: { name: string; values: Partial<Record<MultiqcModule, Record<string, number>>> }[];
    unmapped: string[];
  };
}

export interface CrossCheck {
  raw_file_id: string;
  tool: string;
  tool_version: string | null;
  arva_job_id: string | null;
  tool_job_id: string | null;
  rows: { metric: string; arva: number | null; tool: number | null; tolerance: number; agrees: boolean | null }[];
  all_agree: boolean | null;
  note: string;
}

export type SeqkitCheckStatus = "agree" | "disagree" | "partial" | "not_run";

/** One sample of GET /projects/{id}/qc-overview (apps/api/app/services/qc_overview.py); null = not stated. */
export interface QcOverviewRow {
  sample_id: string;
  sample_code: string;
  sequencing_technology: SequencingTechnology;
  imported_files: number;
  derived_files: number;
  /** Imported FASTQ/FASTA files (POD5 and unrecognised files excluded). */
  imported_read_files: number;
  imported_read_files_with_stats: number;
  stats_tool_versions: string[];
  /** Sums over the imported read files, only when every one has ARVA statistics. */
  total_reads: number | null;
  total_bases: number | null;
  largest_file: { file_id: string; filename: string; total_bases: number } | null;
  n50: number | null;
  mean_read_quality: number | null;
  q30_percent: number | null;
  gc_percent: number | null;
  expected_genome_size_bp: number | null;
  genome_size_status: "given" | "not_given" | "inconsistent" | null;
  estimated_depth: number | null;
  filtering: {
    job_id: string;
    tool_name: string;
    tool_version: string;
    finished_at: string | null;
    runs: number;
    input_files: string[];
    output_files: string[];
    reads_kept_percent: number | null;
    bases_kept_percent: number | null;
  } | null;
  fastqc: { files: number; files_total: number; pass_count: number; warn_count: number; fail_count: number };
  seqkit: { status: SeqkitCheckStatus; files_checked: number; files_total: number; differing_metrics: string[] };
}

export interface QcOverview {
  project_id: string;
  rows: QcOverviewRow[];
}

export type UploadRejectionCode ="duplicate" | "too_large" | "insufficient_storage";

export interface UploadResult {
  files: RawFile[];
  rejected: { filename: string; reason: string; code: UploadRejectionCode }[];
}

export interface Histogram {
  scale: "linear" | "log10";
  bin_width?: number;
  bin_edges: number[];
  reads: number[];
  bases: number[];
}

export interface QualitySection {
  encoding: string;
  min_base_quality: number;
  max_base_quality: number;
  mean_read_quality: number;
  median_read_quality: number;
  mean_base_quality: number;
  q20_bases_percent: number;
  q30_bases_percent: number;
  read_quality_histogram: { quality: number; reads: number }[];
  base_quality_histogram: { quality: number; bases: number }[];
  reads_above_quality: { threshold: number; reads: number; percent: number }[];
  per_position: {
    position_limit: number;
    truncated: boolean;
    positions: number[];
    mean_quality: number[];
    reads_covering: number[];
  };
  notes: string[];
}

export interface SequenceStats {
  schema_version: number;
  tool: { name: string; version: string };
  parameters: Record<string, unknown>;
  file: { format: "fastq" | "fasta"; compressed: boolean };
  read_count: number;
  /** Records of length 0 (counted in read_count); absent in statistics computed before ARVA reported it. */
  zero_length_reads?: number;
  total_bases: number;
  min_length: number;
  max_length: number;
  mean_length: number;
  median_length: number;
  n50: number;
  l50: number;
  n90: number;
  l90: number;
  gc_percent: number;
  ambiguous_bases: number;
  ambiguous_percent: number;
  length_histogram: Histogram;
  length_histogram_log: Histogram | null;
  gc_histogram: { gc_percent: number; reads: number }[];
  cumulative_yield: { min_length: number; reads: number; bases: number }[];
  length_thresholds: { min_length: number; reads: number; bases: number; bases_percent: number }[];
  quality: QualitySection | null;
  sample_points: {
    fields: string[];
    seed: number;
    size: number;
    points: [number, number | null, number | null][];
  };
  coverage_estimate: {
    expected_genome_size_bp: number;
    estimated_depth: number;
    note: string;
  } | null;
  warnings: string[];
}

export interface QCResult {
  id: string;
  analysis_job_id: string;
  raw_file_id: string;
  read_count: number;
  total_bases: number;
  mean_length: number;
  n50: number;
  gc_percent: number;
  mean_quality: number | null;
  metrics: SequenceStats;
  created_at: string;
}

export interface AnalysisJob {
  id: string;
  project_id: string;
  /** Null for project-level jobs such as the MultiQC report. */
  sample_id: string | null;
  job_type: string;
  tool_name: string;
  tool_version: string;
  database_name: string | null;
  database_version: string | null;
  /** The reference database the job read (Database Manager): catalogue key and content checksum. */
  database_key?: string | null;
  database_checksum?: string | null;
  reference_database_id?: string | null;
  parameters: Record<string, unknown> | null;
  input_raw_file_ids: string[] | null;
  output_paths: string[] | null;
  status: JobStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  log_text: string | null;
  error_message: string | null;
  created_at: string;
  commands: string[][] | null;
  tool_path: string | null;
  result_summary: Record<string, unknown> | null;
  parent_job_id: string | null;
  /** Live monitoring of a long tool run (e.g. Flye stages), updated while it runs. */
  progress?: JobProgress | null;
  /** When cancelling was asked; a running job stays "running" until the worker has stopped its tool. */
  cancel_requested_at?: string | null;
  /** A stopped Flye run's work folder, kept so that Flye's own --resume can continue it. */
  checkpoint?: JobCheckpoint | null;
}

export interface JobCheckpoint {
  tool: string;
  /** The Flye version that wrote the folder; resuming needs the same one. */
  tool_version: string;
  path: string;
  /** Cancelled by the user, stopped by the time limit, or killed from outside (signal, out of memory). */
  reason: "cancelled" | "time_limit" | "stopped";
  /** The stage Flye reruns (its folder from the interrupted run was removed). */
  resume_stage: string;
  completed_stages: string[];
  stages: string[];
  size_bytes: number;
  kept_at: string;
}

export type BatchAnalysis = "sequence_stats" | "seqkit" | "fastqc";
export type BatchDecision = "run" | "derived_excluded" | "raw_signal" | "not_reads" | "not_fastq" | "invalid" | "active" | "completed";

export interface BatchQcRequest {
  analyses: BatchAnalysis[];
  include_derived: boolean;
  recompute: boolean;
  sample_ids?: string[];
  dry_run: boolean;
  plan_id?: string;
}

export interface BatchQcPlan {
  plan_id: string;
  analyses: BatchAnalysis[];
  include_derived: boolean;
  recompute: boolean;
  sample_ids: string[] | null;
  tools: { analysis: BatchAnalysis; tool: string; version: string | null; available: boolean; message: string }[];
  samples: {
    sample_id: string;
    sample_code: string;
    /** Jobs per analysis that would be (or were) created. */
    jobs: Partial<Record<BatchAnalysis, number>>;
    total: number;
    files: { file_id: string; name: string; origin: RawFile["origin"]; file_format: FileFormat; decisions: Partial<Record<BatchAnalysis, BatchDecision>> }[];
  }[];
  totals: Partial<Record<BatchAnalysis, number>>;
  total_jobs: number;
  samples_with_jobs: number;
  dry_run: boolean;
  created_job_ids: string[];
}

export interface JobProgress {
  tool: string;
  /** The tool's own name for the stage it last announced. */
  stage: string | null;
  /** 1-based position of that stage among the stages seen so far. */
  stage_index: number | null;
  stages_total: number | null;
  /** The stages expected for this run, in order. */
  stages: string[];
  started_at: string | null;
  stage_started_at: string | null;
  updated_at: string | null;
  elapsed_seconds: number | null;
  finished: boolean;
}

export interface AnalysisJobDetail extends AnalysisJob {
  qc_results: QCResult[];
}

export interface DashboardSummary {
  project_count: number;
  sample_count: number;
  raw_file_count: number;
  total_raw_bytes: number;
  jobs_running: number;
  jobs_completed: number;
  jobs_failed: number;
  storage_used_bytes: number;
  recent_jobs: AnalysisJob[];
  recent_projects: Project[];
}

export interface StorageCapacity {
  storage_root: string;
  free_bytes: number;
  total_bytes: number;
  min_free_bytes: number;
  available_for_data_bytes: number;
  /** 2 when browser uploads are buffered on the same disk and so need twice their size while received. */
  upload_overhead_factor: 1 | 2;
}

export interface ImportRoot {
  index: number;
  name: string;
  path: string;
  exists: boolean;
}

export type ImportEntryKind = "fastq" | "fasta" | "pod5" | "other";

export interface ImportEntry {
  name: string;
  path: string;
  type: "dir" | "file";
  size_bytes: number | null;
  kind: ImportEntryKind;
  modified_at: string;
}

export interface ImportListing {
  root: number;
  path: string;
  parent: string | null;
  entries: ImportEntry[];
  truncated: boolean;
  /** Entries hidden because their names are not valid UTF-8. */
  unsupported_names: number;
}

export interface ServerImportSummary {
  imported: { file_id: string; name: string; path: string; size_bytes: number }[];
  rejected: { path: string; reason: string }[];
}

// --- Sample metadata tables (CSV / .xlsx) -------------------------------------------------------

export type MetadataField =
  | "sample_code"
  | "organism"
  | "expected_species"
  | "sample_type"
  | "host"
  | "geographic_origin"
  | "collection_date"
  | "sequencing_technology"
  | "sequencing_run"
  | "researcher"
  | "institution"
  | "description"
  | "notes";
/** Where a column goes: an ARVA field, the sample's custom metadata, or nowhere. */
export type MetadataTarget = MetadataField | "custom" | "ignore";
export type MetadataAction = "create" | "update" | "unchanged" | "error";
export type DateOrder = "DMY" | "MDY";
export type MetadataImportMode = "create_and_update" | "create_only";

export interface MetadataFileInfo {
  name: string;
  sha256: string;
  kind: "csv" | "xlsx";
  encoding: string | null;
  delimiter: string | null;
  sheet: string | null;
  sheets: string[];
  header_row: number;
}

export interface MetadataColumn {
  header: string;
  field: MetadataTarget;
  suggested_field: MetadataTarget;
}

export interface MetadataChange {
  field: MetadataField | "custom_metadata";
  /** custom_metadata key when field is "custom_metadata". */
  key: string | null;
  old: string | null;
  new: string | null;
}

export interface MetadataRowPreview {
  /** Row number as a spreadsheet shows it. */
  row: number;
  sample_code: string | null;
  action: MetadataAction;
  sample_id: string | null;
  matched_sample_code: string | null;
  matched_by: "exact" | "case_insensitive" | null;
  changes: MetadataChange[];
  errors: ServerMessage[];
  warnings: ServerMessage[];
}

export interface MetadataPreview {
  file: MetadataFileInfo;
  columns: MetadataColumn[];
  fields: MetadataTarget[];
  rows: MetadataRowPreview[];
  warnings: ServerMessage[];
  /** Problems that block every row, e.g. no column mapped to sample_code. */
  errors: ServerMessage[];
  counts: { rows: number; create: number; update: number; unchanged: number; error: number };
  date_order: DateOrder | null;
  date_order_source: "user" | "header" | null;
  ambiguous_dates: number;
}

export interface MetadataImportRecord {
  id: string;
  project_id: string;
  filename: string;
  sha256: string;
  kind: "csv" | "xlsx";
  sheet: string | null;
  encoding: string | null;
  delimiter: string | null;
  header_row: number;
  mapping: Record<string, MetadataTarget>;
  date_order: DateOrder | null;
  mode: MetadataImportMode;
  created_count: number;
  updated_count: number;
  unchanged_count: number;
  skipped_count: number;
  created_at: string;
}

export interface MetadataApplyResult {
  record: MetadataImportRecord;
  skipped: { row: number; sample_code: string | null; reasons: ServerMessage[] }[];
}

/** Choices sent with a metadata table; omitted values let the server detect them. */
export interface MetadataTableOptions {
  sheet?: string | null;
  headerRow?: number | null;
  delimiter?: string | null;
  dateOrder?: DateOrder | null;
  mapping?: Record<string, MetadataTarget> | null;
}

// --- Assembly ---------------------------------------------------------------------------------

export type FlyeReadType = "nano-raw" | "nano-corr" | "nano-hq" | "pacbio-raw" | "pacbio-corr" | "pacbio-hifi";
export type GenomeSizeBasis = "entered" | "expected_genome_size" | "reads_over_depth";

export interface FlyeParams {
  read_type: FlyeReadType;
  genome_size_bp: number | null;
  genome_size_basis: GenomeSizeBasis | null;
  assumed_depth_x: number | null;
  iterations: number;
  min_overlap: number | null;
  asm_coverage: number | null;
  read_error: number | null;
  meta: boolean;
  keep_haplotypes: boolean;
  no_alt_contigs: boolean;
  scaffold: boolean;
  threads: number | null;
}

export interface FlyeRequest {
  raw_file_ids: string[];
  params: FlyeParams;
  long_reads_confirmed: boolean;
}

export interface FlyeFileEvidence {
  file_id: string;
  name: string;
  origin: RawFile["origin"];
  header_platform: HeaderPlatform | null;
  header_confidence: HeaderConfidence;
  basecall_models: string[];
  pacbio_read_types: string[];
  stats_job_id: string | null;
  total_bases: number | null;
  max_read_length: number | null;
  read_n50: number | null;
  mean_base_quality: number | null;
}

export interface FlyeReadTypeSuggestion {
  heuristic: true;
  value: FlyeReadType | null;
  basis: string;
  platform: "nanopore" | "pacbio" | null;
  platform_source: "sample_metadata" | "read_headers" | null;
  mean_error_rate: number | null;
  mean_base_quality: number | null;
  q20_read_error_note: boolean;
  sup_model_but_low_quality: boolean;
}

export interface AssemblyGenomeSize {
  bp: number | null;
  status: "given" | "not_given" | "inconsistent";
  source: "assembly_parameters" | "read_statistics" | null;
  basis?: GenomeSizeBasis | null;
  assumed_depth_x?: number | null;
}

export interface FlyePlan {
  tool: {
    status: ToolStatus;
    version: string | null;
    version_validated: boolean;
    message: string;
    reason: string | null;
    /** Optional Flye options this installed version lists in its --help. */
    options: string[];
    max_threads: number;
  };
  files: FlyeFileEvidence[];
  read_type_suggestion: FlyeReadTypeSuggestion;
  genome_size: {
    expected: AssemblyGenomeSize;
    total_read_bases: number | null;
    files_without_stats: string[];
    from_depth: { depth_x: number; total_read_bases: number; bp: number } | null;
  };
  sample_technology: SequencingTechnology;
  long_reads_confirmation_required: boolean;
}

export interface AssemblyWarning {
  code: string;
  heuristic: true;
  message: string;
  params: Record<string, string | number>;
  contigs: string[];
  contigs_total: number;
}

export interface AssemblyContig {
  rank: number;
  name: string;
  length: number;
  gc_percent: number | null;
  n_count: number;
  other_iupac_count: number;
  coverage: number | null;
  circular: boolean | null;
  repeat: boolean | null;
}

export interface AssemblyCurve {
  rank: number[];
  /** Contig lengths, longest first. */
  length: number[];
  cumulative_length: number[];
  /** Over 1,000 contigs: the 500 longest, then evenly spaced ranks to the last. */
  downsampled: boolean;
}

export interface AssemblyCheck {
  code: string;
  rule: string;
  evaluated: boolean;
  skipped_reason: string | null;
}

export interface AssemblyStats {
  contig_count: number;
  total_length: number;
  largest_contig: number;
  smallest_contig: number;
  n50: number;
  l50: number;
  n90: number;
  l90: number;
  gc_percent: number | null;
  n_count: number;
  n_per_100kb?: number;
  /** Bins are [min_length, max_length). */
  length_histogram?: { min_length: number; max_length: number; contigs: number; total_length: number }[];
  cumulative?: AssemblyCurve;
  thresholds?: { min_length: number; contigs: number; total_length: number; total_length_percent: number }[];
  circularity: { contigs_with_circularity: number; circular_contigs: number };
  coverage: { contigs_with_coverage: number; length_weighted_median: number | null };
  contig_rows: { stored: number; total: number; truncated: boolean };
  expected_genome_size: AssemblyGenomeSize;
  /** Every heuristic check, including those that could not be evaluated. */
  warning_checks?: AssemblyCheck[];
  files: Record<"contigs" | "graph" | "info", { path: string; sha256: string; size_bytes: number } | null>;
}

/** What an assembler's per-contig coverage measures; values of different kinds are not comparable. */
export type CoverageKind = "read_depth" | "kmer_coverage" | "relative_depth" | "mapped_read_depth";
/** "polished": made from parent_assembly_id by the polisher named in `assembler`. */
export type AssemblyKind = "assembly" | "polished";

export interface Assembly {
  id: string;
  sample_id: string;
  job_id: string;
  kind: AssemblyKind;
  parent_assembly_id: string | null;
  assembler: string;
  assembler_version: string;
  mode: "long" | "short" | "hybrid";
  read_type: string;
  coverage_kind?: CoverageKind | null;
  input_file_ids: string[];
  stats: AssemblyStats;
  warnings: AssemblyWarning[];
  created_at: string;
}

export interface AssemblyDetail extends Assembly {
  contigs: AssemblyContig[];
}

export interface AssemblyGraphNode {
  id: string;
  length: number;
  /** Numeric GFA tags as the assembler wrote them (e.g. Flye's dp). */
  tags: Record<string, number>;
  /** GFA paths (P lines; Flye: contigs) through this segment, at most 20. */
  paths: string[];
  /** True when a contig in `paths` is reported circular by the assembler; null when none of them has the flag. */
  circular: boolean | null;
  repeat: boolean | null;
}

export interface AssemblyGraphEdge {
  source: string;
  source_orientation: "+" | "-";
  target: string;
  target_orientation: "+" | "-";
  overlap: string;
  tags: Record<string, number>;
}

export interface AssemblyGraph {
  assembly_id: string;
  assembler: string;
  /** The segment tag holding this assembler's coverage (Flye: dp) and what it measures. */
  coverage_tag: string | null;
  coverage_meaning: string | null;
  format: "GFA1";
  version: string | null;
  segment_count: number;
  link_count: number;
  path_count: number;
  /** Links naming a segment the file does not define (not shown). */
  dangling_links: number;
  total_segment_length: number;
  numeric_tags: string[];
  max_nodes: number;
  max_edges: number;
  truncated: boolean;
  /** Longest segments first. */
  nodes: AssemblyGraphNode[];
  edges: AssemblyGraphEdge[];
}

/** One assembly of a project, for the project page. */
export interface ProjectAssembly {
  id: string;
  sample_id: string;
  sample_code: string;
  job_id: string;
  kind: AssemblyKind;
  parent_assembly_id: string | null;
  assembler: string;
  assembler_version: string;
  mode: Assembly["mode"];
  read_type: string;
  contig_count: number;
  total_length: number;
  largest_contig: number;
  n50: number;
  l50: number;
  gc_percent: number | null;
  circular_contigs: number;
  contigs_with_circularity: number;
  median_coverage: number | null;
  coverage_kind?: CoverageKind | null;
  warning_codes: string[];
  created_at: string;
}

/** Flye's own per-contig columns from assembly_info.txt, kept in the job's result summary. */
export interface FlyeContigRow {
  name: string;
  length: number;
  coverage: number;
  circular: boolean;
  repeat: boolean;
  multiplicity: number;
  alt_group: string | null;
  graph_path: string;
}

/** How QUAST would find minimap2 for a reference; "missing": it would compile its own copy, which ARVA refuses. */
export interface QuastAligner {
  provided_by: "quast_bundled" | "path" | "missing";
  executable?: string | null;
  version?: string | null;
  /** A minimap2 on PATH that is too old for QUAST. */
  found?: string | null;
}

export interface QuastPlannedAssembly {
  assembly_id: string;
  /** The name QUAST uses for the assembly in its reports. */
  label: string;
  assembler: string;
  assembler_version: string;
  read_type: string;
  created_at: string;
  contigs: number;
  total_length: number;
  /** Contigs of at least min_contig bp, which QUAST's metrics describe. */
  contigs_kept: number;
  length_kept: number;
  contigs_left_out: number;
  length_left_out: number;
}

export interface QuastPlan {
  tool: {
    status: ToolStatus;
    version: string | null;
    version_validated: boolean;
    message: string;
    reason: string | null;
    aligner: QuastAligner | null;
    max_threads: number;
    default_min_contig: number;
  };
  min_contig: number;
  assemblies: QuastPlannedAssembly[];
  reference: { file_id: string; name: string; size_bytes: number; origin: RawFile["origin"] } | null;
}

export interface QuastRequest {
  assembly_ids: string[];
  reference_file_id: string | null;
  min_contig: number;
  threads?: number | null;
}

/** A value in QUAST's report: a number, "-" (null), "X + Y part", or text ARVA does not interpret. */
export type QuastValue = number | null | string | { full: number; partial: number };

export interface QuastCrosscheckRow {
  metric: string;
  arva_key: string;
  quast: QuastValue;
  arva: number | null;
  /** Decimals QUAST prints (null: an exact count or length). */
  decimals: number | null;
  agrees: boolean | null;
}

/** result_summary of a completed quast_evaluation job. */
export interface QuastSummary {
  quast_version: string;
  python_version: string | null;
  min_contig: number;
  reference: { file_id: string; name: string; sha256: string | null; size_bytes: number } | null;
  assemblies: { assembly_id: string; label: string; assembler: string; assembler_version: string; assembly_job_id: string; contigs_sha256: string }[];
  report: { labels: string[]; rows: { field: string; values: QuastValue[] }[] };
  crosscheck: { assembly_id: string; label: string; arva: Record<string, number | null>; rows: QuastCrosscheckRow[]; all_agree: boolean }[];
  aligner: { name: string; executable: string; version: string } | null;
  warnings: string[];
  quast_log_empty: boolean;
  html: { report: string; icarus: string; viewers: string[] };
}

// --- SPAdes and Unicycler ------------------------------------------------------------------------------------

export type ReadRole = "r1" | "r2" | "unpaired" | "long";
export type SpadesMode = "isolate" | "careful" | "standard";
export type UnicyclerBridging = "conservative" | "normal" | "bold";
export type AssemblyModeName = Assembly["mode"];

export interface ShortReadInputs {
  r1_file_id?: string | null;
  r2_file_id?: string | null;
  unpaired_file_id?: string | null;
}

export interface UnicyclerInputs extends ShortReadInputs {
  long_file_id?: string | null;
}

export interface SpadesParams {
  mode: SpadesMode;
  /** Passed as -k; null lets SPAdes choose from the read length. */
  k: number[] | null;
  cov_cutoff: "off" | "auto" | number;
  memory_gb: number | null;
  threads: number | null;
  output: "contigs" | "scaffolds";
}

export interface SpadesRequest {
  inputs: ShortReadInputs;
  params: SpadesParams;
  reads_confirmed: boolean;
}

export interface UnicyclerParams {
  mode: UnicyclerBridging;
  keep: 0 | 1;
  kmers: number[] | null;
  depth_filter: number;
  min_fasta_length: number;
  linear_seqs: number;
  threads: number | null;
  spades_memory_gb: number | null;
}

export interface UnicyclerRequest {
  inputs: UnicyclerInputs;
  params: UnicyclerParams;
  reads_confirmed: boolean;
}

export interface AssemblyToolInfo {
  status: ToolStatus;
  version: string | null;
  version_validated: boolean;
  message: string;
  reason: string | null;
  /** Options of interest this installed version lists in its help. */
  options: string[];
  max_threads: number;
  /** Most memory ARVA may give a run (ARVA_TOOL_MEMORY_GB, or the computer's memory). */
  max_memory_gb: number;
  /** Used when no memory is given: min(250, max_memory_gb), as SPAdes does. */
  default_memory_gb: number;
}

export interface AssemblyFileEvidence extends FlyeFileEvidence {
  role: ReadRole;
  read_mate: string | null;
  read_count: number | null;
}

export interface ShortReadPlan {
  tool: AssemblyToolInfo;
  files: AssemblyFileEvidence[];
  assembly_mode: AssemblyModeName | null;
  read_layout: string;
  /** Why these files cannot be assembled as chosen; null when they can. */
  problem: string | null;
  sample_technology: SequencingTechnology;
  confirmation_required: boolean;
}

export interface UnicyclerPlan extends ShortReadPlan {
  tool: AssemblyToolInfo & {
    modes: AssemblyModeName[];
    helpers: Record<"spades" | "racon" | "makeblastdb" | "tblastn", { path: string | null; version: string | null }>;
  };
}

// --- Polishing ------------------------------------------------------------------------------------------------

export type PolishingStrategy = "racon" | "pilon" | "hybrid";
/** minimap2 presets for the long reads Racon polishes with. */
export type LongReadPreset = "map-ont" | "map-pb" | "map-hifi";
export type PilonFix = "snps" | "indels" | "gaps" | "local";

export interface PolishingTool {
  status: ToolStatus;
  version: string | null;
  version_validated: boolean;
  message: string;
  reason: string | null;
  path: string | null;
}

export type PolishingToolId = "racon" | "minimap2" | "pilon" | "java" | "bwa" | "samtools" | "dnadiff";

export interface PolishingPlan {
  draft: {
    assembly_id: string;
    kind: AssemblyKind;
    assembler: string;
    assembler_version: string;
    mode: AssemblyModeName;
    read_type: string;
    parent_assembly_id: string | null;
    contig_count: number;
    total_length: number;
    n50: number;
    circular_contigs: number;
    created_at: string;
  };
  tools: Record<PolishingToolId, PolishingTool>;
  /** Strategies whose tools are all installed. */
  strategies_available: PolishingStrategy[];
  files: AssemblyFileEvidence[];
  /** The strategy the chosen reads imply. */
  strategy: PolishingStrategy | null;
  /** The strategy the sample's sequencing technology calls for. */
  suggested_strategy: PolishingStrategy | null;
  preset_suggestion: { heuristic: true; value: LongReadPreset | null; basis: string; flye_read_type: string | null; platform?: "nanopore" | "pacbio" | null };
  problem: string | null;
  sample_technology: SequencingTechnology;
  confirmation_required: boolean;
  max_threads: number;
  max_memory_gb: number;
  default_heap_gb: number;
}

export interface RaconSettings {
  read_type: LongReadPreset | null;
  rounds: number;
  match: number;
  mismatch: number;
  gap: number;
  window_length: number;
  quality_threshold: number;
  error_threshold: number;
}

export interface PilonSettings {
  rounds: number;
  fix: PilonFix[];
  mindepth: number;
  minmq: number;
  minqual: number;
  heap_gb: number | null;
  stop_when_unchanged: boolean;
}

export interface PolishingRequest {
  strategy: PolishingStrategy;
  inputs: UnicyclerInputs;
  racon: RaconSettings;
  pilon: PilonSettings;
  threads: number | null;
  quast: boolean;
  quast_reference_file_id: string | null;
  reads_confirmed: boolean;
}

export type ChangeKind = "snp" | "insertion" | "deletion" | "other";
export type Changes = Record<ChangeKind, { events: number; bases: number }>;

/** One side (draft or polished) of a MUMmer dnadiff report. */
export interface DnadiffSide {
  sequences: number;
  aligned_sequences: number;
  unaligned_sequences: number;
  bases: number;
  aligned_bases: number;
  unaligned_bases: number;
  one_to_one_identity: number;
  breakpoints: number;
  substituted_bases: number;
  indel_bases: number;
}

export interface DnadiffComparison {
  before: DnadiffSide;
  after: DnadiffSide;
  events: { substitutions: number; insertions: number; inserted_bases: number; deletions: number; deleted_bases: number };
  ends: { contig: string; length: number; unaligned_start: number; unaligned_end: number }[];
}

export interface AlignmentStats {
  reads: number;
  reads_mapped: number;
  mapped_percent: number | null;
  reads_properly_paired: number | null;
  properly_paired_percent: number | null;
  bases_mapped_cigar: number;
  nm_sum: number;
  edit_distance_per_100_bases: number | null;
  insertion_events: number;
  deletion_events: number;
  indel_events_per_100kb: number | null;
}

export interface CoverageRow {
  contig: string;
  length: number;
  reads: number;
  covered_percent: number;
  mean_depth: number;
}

export interface PolishingRound {
  round: number;
  changes: Changes | null;
  changes_source: "dnadiff" | "pilon_changes" | null;
  pilon_changes?: Changes;
  racon_contigs?: Record<string, { length: number | null; reads: number | null; windows_polished: number | null }>;
}

export interface PolishingObservation {
  code: "ends_trimmed" | "contigs_unaligned" | "no_changes" | "edit_distance_increased";
  params: Record<string, string | number | boolean | null>;
  message: string;
}

export interface AssemblySummaryStats {
  contig_count: number;
  total_length: number;
  largest_contig: number;
  n50: number;
  l50: number;
  gc_percent: number | null;
  n_count: number;
}

/** result_summary of a racon_polish or pilon_polish job. */
export interface PolishingSummary {
  polisher: "Racon" | "Pilon";
  polisher_version: string;
  strategy: PolishingStrategy | null;
  draft: { assembly_id: string; assembler: string; assembler_version: string; kind: AssemblyKind };
  polished_assembly_id: string;
  read_type: string;
  rounds_requested: number;
  rounds_run: number;
  stopped_early?: boolean;
  rounds: PolishingRound[];
  direct: { source: "dnadiff" | "pilon_changes" | null; dnadiff: DnadiffComparison | null; pilon_changes: Changes | null };
  indirect: { aligner: string; reads: string; before: { stats: AlignmentStats; coverage: CoverageRow[] }; after: { stats: AlignmentStats; coverage: CoverageRow[] } };
  assembly_stats: { before: AssemblySummaryStats; after: AssemblySummaryStats };
  observations: PolishingObservation[];
  helpers: { name: string; version: string | null; path: string }[];
  followups: { pilon_job_id?: string; quast_job_id?: string; pilon_error?: string; quast_error?: string };
}

/** A database ARVA knows (Database Manager catalogue), with the facts published by its source. */
export interface CatalogueEntry {
  key: string;
  name: string;
  tool: string;
  status: "available" | "planned";
  description: string;
  version: string | null;
  release_date: string | null;
  db_type: string | null;
  source_url: string | null;
  doi: string | null;
  download_url: string | null;
  filename: string | null;
  archive_bytes: number | null;
  checksum_algorithm: string | null;
  checksum: string | null;
  checksum_sources: string[];
  extracted_size_note: string | null;
  extracted_bytes_estimate: number | null;
  licence: string | null;
  licence_url: string | null;
  terms: string | null;
  citation: string | null;
  compatibility: string | null;
  external_versions: Record<string, string>;
  notes: string[];
}

export type DatabaseStatus = "installed" | "registered" | "downloading" | "verifying" | "failed" | "cancelled";

export interface DatabaseProgress {
  phase: string | null;
  bytes_done: number | null;
  bytes_total: number | null;
  written_bytes?: number | null;
  resumed_from?: number | null;
  started_at?: string | null;
  updated_at?: string | null;
}

export interface ReferenceDatabase {
  id: string;
  key: string;
  name: string;
  version: string | null;
  path: string | null;
  source_url: string | null;
  licence: string | null;
  size_bytes: number | null;
  checksum: string | null;
  archive_checksum: string | null;
  status: DatabaseStatus;
  origin: "download" | "register";
  installed_at: string | null;
  verified_at: string | null;
  notes: string | null;
  error_message: string | null;
  progress: DatabaseProgress | null;
  cancel_requested_at: string | null;
  created_at: string;
  updated_at: string;
  version_json: Record<string, unknown> | null;
  files: number | null;
  /** AMRFinderPlus data in amrfinderplus-db/latest (Bakta's AMR expert system), if present. */
  amrfinderplus_db: { latest: string | null; version: string | null; database_format: string | null } | null;
  archive: Record<string, unknown> | null;
  catalogue_version: string | null;
  jobs_using: number;
  log_text: string | null;
}

export interface DownloadPlan {
  entry: CatalogueEntry;
  db_dir: string;
  target_path: string;
  partial_bytes: number;
  download_bytes: number;
  required_bytes: number;
  free_bytes: number;
  reserve_bytes: number;
  available_bytes: number;
  enough: boolean;
  resume_record_id: string | null;
  blocked_by: string | null;
}

export interface DatabaseUsage {
  db_dir: string;
  free_bytes: number;
  total_bytes: number;
  reserve_bytes: number;
  installed_bytes: number;
  registered_bytes: number;
  partial_bytes: number;
  staging_bytes: number;
}

// --- Annotation (Bakta, Prokka) ---------------------------------------------------------------------------------

export type Annotator = "bakta" | "prokka";
export type TranslationTable = 11 | 4 | 25;

export interface AnnotationDependency {
  name: string;
  /** ok, missing, failed, unreadable, too_old, crashed (PILER-CR's test run), database_missing (AMRFinderPlus). */
  status: string;
  found?: string | null;
  minimum?: string | null;
  returncode?: number | null;
  steps?: string[];
  command?: string[];
}

export interface AnnotationStep {
  run: boolean;
  /** dependency, user, needs_cds, light_database, option_off, database_lacks, not_offered, not_supported, tool_skipped, crashed */
  reason: string | null;
  dependencies: AnnotationDependency[];
  status?: "searched" | "skipped" | "failed" | null;
  found?: number | null;
  returncode?: number | null;
}

export interface AnnotationAssemblyFacts {
  assembly_id: string;
  kind: string;
  assembler: string;
  assembler_version: string;
  parent_assembly_id: string | null;
  job_id: string;
  contigs_sha256: string;
  created_at: string;
  contigs: number;
  total_length: number | null;
  circular_contigs: number | null;
  contigs_with_circularity: number | null;
  all_circular: boolean;
  longest_contig_name: number;
  prokka_name_problem: string | null;
  descriptions: number;
  synthetic_evidence: string[];
}

export interface BaktaDatabaseOption {
  id: string;
  key: string;
  name: string;
  version: string | null;
  type: string | null;
  status: DatabaseStatus;
  usable: boolean;
  checksum: string | null;
  verified_at: string | null;
  path: string | null;
}

export interface ProkkaDatabase {
  path: string;
  ready: boolean;
  files: string[];
  package: string[] | null;
  kingdoms: string[];
  genera: string[];
  hmm: string[];
  checksum?: string | null;
  key?: string | null;
  name?: string | null;
  version?: string | null;
}

export interface AnnotationPlan {
  annotator: Annotator;
  tool: {
    status: string;
    version: string | null;
    version_validated: boolean;
    message: string;
    reason: string | null;
    path: string | null;
    license: string;
    citation: string;
    citation_url: string;
    max_threads: number;
  };
  steps: Record<string, AnnotationStep>;
  assembly: AnnotationAssemblyFacts;
  suggestions: { locus_tag: string; complete?: boolean; rename_contigs?: boolean; translation_table: TranslationTable };
  translation_tables: TranslationTable[];
  problems: { code: string; message: string }[];
  dependencies: AnnotationDependency[];
  skip_options: string[];
  databases: BaktaDatabaseOption[];
  database_id: string | null;
  database: ProkkaDatabase | null;
  programs: Record<string, string | null>;
}

export interface AnnotationOrganism {
  locus_tag: string;
  translation_table: TranslationTable;
  genus: string | null;
  species: string | null;
  strain: string | null;
  min_contig_length: number;
}

export interface BaktaSettings extends AnnotationOrganism {
  complete: boolean;
  keep_contig_headers: boolean;
  skip_plot: boolean;
}

export interface ProkkaSettings extends AnnotationOrganism {
  use_genus: boolean;
  rfam: boolean;
  evalue: number;
  coverage: number;
  rename_contigs: boolean;
}

export interface BaktaRequest {
  database_id: string | null;
  settings: BaktaSettings;
  threads: number | null;
  skip_options: string[];
  complete_confirmed: boolean;
  confirmed: boolean;
}

export interface ProkkaRequest {
  settings: ProkkaSettings;
  threads: number | null;
  confirmed: boolean;
}

export interface AnnotationSummary {
  counts: Record<string, number>;
  features: number;
  cds: number | null;
  hypothetical: number | null;
  characterised: number | null;
  hypothetical_fraction: number | null;
  pseudogenes: number;
  partial: number;
  with_ec: number;
  with_cog: number;
  with_go: number;
  with_gene: number;
  cog_categories: Record<string, number>;
  coding_density: { value: number | null; cds_bases: number | null; non_n_bases: number; definition: string };
  sequences: number;
  total_length: number;
  tool_reported: Record<string, unknown>;
  input: { sha256: string; non_n_bases: number; total_length: number; renamed: boolean };
  synthetic_evidence: string[];
}

export interface AnnotationSequence {
  id: string;
  original_id: string;
  length: number;
  topology?: string | null;
  replicon_type?: string | null;
  complete?: boolean | null;
}

export interface Annotation {
  id: string;
  sample_id: string;
  assembly_id: string;
  job_id: string;
  tool: string;
  tool_version: string;
  database_key: string | null;
  database_name: string | null;
  database_version: string | null;
  database_checksum: string | null;
  parameters: Record<string, unknown>;
  steps: Record<string, AnnotationStep>;
  summary: AnnotationSummary;
  sequences: AnnotationSequence[];
  files: Record<string, { path: string; sha256: string; size_bytes: number }>;
  created_at: string;
}

export interface AnnotationFeature {
  id: number;
  tool_id: string | null;
  locus_tag: string | null;
  type: string;
  tool_type: string | null;
  contig: string;
  contig_in_assembly: string;
  start: number;
  end: number;
  strand: string;
  length: number;
  edge: boolean;
  gene: string | null;
  product: string | null;
  ec: string[];
  cog: string[];
  cog_categories: string[];
  go: string[];
  db_xrefs: string[];
  pseudo: boolean;
  partial: string | null;
  hypothetical: boolean | null;
  inference: string[];
  accessions: string[];
}

export interface AnnotationFeaturePage {
  total: number;
  limit: number;
  offset: number;
  max_limit: number;
  items: AnnotationFeature[];
}

export interface SequenceCheck {
  status: "match" | "differs" | "not_checked";
  reason: string | null;
}

export interface ProteinCheck extends SequenceCheck {
  table: number;
  first_difference: number | null;
  translated_length?: number | null;
  protein_length?: number | null;
  internal_stops?: number | null;
}

export interface AnnotationSequenceRecord {
  source: string;
  header: string;
  length: number;
  sequence: string;
  truncated: boolean;
}

export interface AnnotationFeatureDetail extends AnnotationFeature {
  links: { xref: string; url: string }[];
  nucleotide: AnnotationSequenceRecord | null;
  protein: AnnotationSequenceRecord | null;
  /** ARVA's checks against the genome; the sequences shown are always the annotator's. */
  checks: { nucleotide: SequenceCheck; protein: ProteinCheck };
}

export interface AnnotationRegion {
  contig: string;
  start: number;
  end: number;
}

export interface AnnotationListRow {
  id: string;
  tool: string;
  tool_version: string;
  database_name: string | null;
  database_version: string | null;
  created_at: string;
  sample_id: string;
  sample_code: string;
  project_id: string;
  project_name: string;
  is_demo: boolean;
  assembly_id: string;
  assembler: string;
  assembler_version: string;
  assembly_kind: string;
  sequences: number;
  total_length: number;
  features: number | null;
  cds: number | null;
  synthetic_evidence: string[];
}

export interface FeatureLayoutItem {
  id: number;
  locus_tag: string | null;
  tool_id: string | null;
  type: string;
  start: number;
  end: number;
  strand: string;
  length: number;
  edge: boolean;
  gene: string | null;
  product: string | null;
  hypothetical: boolean | null;
  pseudo: boolean;
  partial: string | null;
}

export interface FeatureLayout {
  contig: string;
  contig_in_assembly: string;
  length: number;
  total: number;
  items: FeatureLayoutItem[];
}

export interface GcTrack {
  window: number;
  step: number;
  auto: boolean;
  windows: number;
  group: number;
  contig_gc: number | null;
  start: number[];
  end: number[];
  gc: (number | null)[];
  gc_min: (number | null)[];
  gc_max: (number | null)[];
  skew: (number | null)[];
  skew_min: (number | null)[];
  skew_max: (number | null)[];
}

export interface CoverageSource {
  job_id: string;
  polisher: string;
  polisher_version: string;
  alignment: "draft" | "polished";
  aligner: string | null;
  reads: string | null;
  resolution: number;
  command: string[] | null;
  samtools_version: string | null;
  deletions_counted: boolean | null;
  overlapping_mates_counted_twice: boolean | null;
}

export interface CoverageTrack {
  available: boolean;
  reason?: string | null;
  job_id?: string | null;
  source?: CoverageSource | null;
  contig_mean_depth?: number | null;
  resolution?: number | null;
  group?: number | null;
  start: number[];
  end: number[];
  mean: (number | null)[];
  min: (number | null)[];
  max: (number | null)[];
}

export interface GenomeTracks {
  contig: string;
  contig_in_assembly: string;
  length: number;
  start: number;
  end: number;
  points: number;
  sequence_source: { file: string; tool: string; sha256: string };
  gc: GcTrack;
  coverage: CoverageTrack;
}

export interface GenomeSequence {
  contig: string;
  contig_in_assembly: string;
  start: number;
  end: number;
  strand: "+" | "-";
  length: number;
  sequence: string;
}

export type AnnotationExportFormat = "gff3" | "genbank" | "fasta_nt" | "fasta_aa" | "tsv";

export interface FeatureQuery {
  types: string[];
  q: string;
  hypothetical: "" | "true" | "false";
  contig: string;
  start: string;
  end: string;
  sort: "position" | "locus_tag" | "type" | "gene" | "product" | "length";
  descending: boolean;
  limit: number;
  offset: number;
}

// --- Circular genome map ------------------------------------------------------------------------------------------

export interface MapFeature extends FeatureLayoutItem {
  contig: string;
}

export interface MapSequence {
  contig: string;
  contig_in_assembly: string;
  length: number;
  topology: string | null;
  gc: { contig_gc: number | null; start: number[]; end: number[]; gc: (number | null)[]; skew: (number | null)[] };
  coverage: { available: boolean; reason?: string | null; contig_mean_depth?: number | null; start: number[]; end: number[]; mean: (number | null)[] };
}

export interface GenomeMap {
  total_length: number;
  points: number;
  sequence_source: { file: string; tool: string; sha256: string };
  gc: { window: number; step: number; auto: boolean; genome_gc: number | null };
  coverage: { available: boolean; reason: string | null; source: CoverageSource | null };
  sequences: MapSequence[];
  total: number;
  features: MapFeature[];
}

// --- Annotation charts ---------------------------------------------------------------------------------------------

export type LengthClass = "cds_characterised" | "cds_hypothetical" | "sorf" | "rna";

export interface LengthStats {
  n: number;
  min: number | null;
  median: number | null;
  mean: number | null;
  max: number | null;
}

export interface LengthBin extends Record<LengthClass, number> {
  min: number;
  max: number | null;
}

export interface DensityContig {
  contig: string;
  contig_in_assembly: string;
  length: number;
  start: number[];
  end: number[];
  forward: number[];
  reverse: number[];
  unstranded: number[];
  total: number[];
  genes: number;
}

export type StrandCounts = Record<"+" | "-" | ".", number>;

export interface AnnotationCharts {
  cds_searched: boolean;
  genes: number;
  lengths: { width: number | null; bins: LengthBin[]; classes: Record<LengthClass, LengthStats> };
  density: { window: number; contigs: DensityContig[] };
  strand: {
    by_type: Record<string, StrandCounts>;
    by_contig: ({ contig: string; contig_in_assembly: string } & StrandCounts)[];
    total: StrandCounts;
    replication_strand: "not_determined";
  };
  cog: {
    cds_searched: boolean;
    cds: number | null;
    reported: boolean;
    cds_with_category: number;
    cds_with_cog_id: number;
    categories: { letter: string; name: string | null; cds: number }[];
    names_source: string;
  };
  hypothetical: {
    cds_searched: boolean;
    by_contig: { contig: string; contig_in_assembly: string; characterised: number; hypothetical: number }[];
    total: { characterised: number; hypothetical: number } | null;
  };
  types: { types: string[]; total: Record<string, number>; by_contig: { contig: string; contig_in_assembly: string; counts: Record<string, number> }[] };
}
