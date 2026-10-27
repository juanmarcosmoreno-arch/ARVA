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
