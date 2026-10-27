// Mirrors apps/api/app/schemas/schemas.py and arva_core.seqstats output.

export type SequencingTechnology = "illumina" | "nanopore" | "pacbio" | "hybrid" | "unknown";
export type FileFormat = "fastq" | "fastq_gz" | "fasta" | "fasta_gz" | "unknown";
export type JobStatus = "pending" | "running" | "completed" | "failed";

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
}

export interface Sample extends Required<Omit<SampleInput, "sequencing_technology">> {
  id: string;
  project_id: string;
  project_name: string | null;
  sequencing_technology: SequencingTechnology;
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
}

export interface FastpParams {
  adapter_trimming: boolean;
  detect_adapter_for_pe: boolean;
  quality_filtering: boolean;
  qualified_quality_phred: number;
  unqualified_percent_limit: number;
  n_base_limit: number;
  average_qual: number;
  length_filtering: boolean;
  length_required: number;
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
}

export interface FastqcSummary {
  fastqc_version: string | null;
  modules: { status: "PASS" | "WARN" | "FAIL" | string; module: string }[];
  basic_statistics: Record<string, string>;
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

export interface UploadResult {
  files: RawFile[];
  rejected: { filename: string; reason: string }[];
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
  sample_id: string;
  job_type: string;
  tool_name: string;
  tool_version: string;
  database_name: string | null;
  database_version: string | null;
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
}

export interface ServerImportSummary {
  imported: { file_id: string; name: string; path: string; size_bytes: number }[];
  rejected: { path: string; reason: string }[];
}
