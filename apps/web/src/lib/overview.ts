/** Sample sequencing overview and project QC overview: pure aggregation, sorting and filtering helpers. */
import { lineageOrder } from "./filters";
import { latestJobFor, latestResults } from "./results";
import type { AnalysisJobDetail, Pod5Summary, QcOverviewRow, RawFile, SequenceStats, SequencingTechnology } from "./types";

export const STATS_JOB = "sequence_stats";
export const POD5_JOB = "pod5_summary";

/** Why a file has values or not: only completed jobs give values. */
export type FileState = "done" | "running" | "failed" | "not_run" | "not_applicable";

export interface FileOverviewRow {
  file: RawFile;
  /** 0 for imported files, 1 for a file derived from one, and so on. */
  depth: number;
  parent: RawFile | null;
  /** Tool and version of the job that wrote a derived file. */
  producer: string | null;
  kind: "reads" | "signal" | "other";
  state: FileState;
  stats: SequenceStats | null;
  /** arva-core version of the statistics shown. */
  statsVersion: string | null;
  signal: { reads: number; durationS: number | null } | null;
  /** Bases of a derived file as a percentage of its parent's, both from ARVA statistics. */
  shareOfParent: number | null;
}

function stateOf(job: AnalysisJobDetail | undefined): FileState {
  if (!job) return "not_run";
  if (job.status === "pending" || job.status === "running") return "running";
  if (job.status === "cancelled") return "not_run";
  return job.status === "failed" ? "failed" : "done";
}

/** One row per file in lineage order (each derived file right after its parent). */
export function sequencingOverview(files: RawFile[], jobs: AnalysisJobDetail[]): FileOverviewRow[] {
  const results = latestResults(jobs);
  const byId = new Map(files.map((f) => [f.id, f]));
  const producers = new Map(jobs.map((j) => [j.id, `${j.tool_name} ${j.tool_version}`]));
  return lineageOrder(files).map(({ file, depth }) => {
    const parent = file.parent_file_id ? byId.get(file.parent_file_id) ?? null : null;
    const row: FileOverviewRow = {
      file,
      depth,
      parent,
      producer: file.produced_by_job_id ? producers.get(file.produced_by_job_id) ?? null : null,
      kind: file.file_format === "pod5" ? "signal" : file.file_format === "unknown" ? "other" : "reads",
      state: "not_applicable",
      stats: null,
      statsVersion: null,
      signal: null,
      shareOfParent: null,
    };
    if (row.kind === "reads") {
      const result = results.get(file.id);
      row.stats = result?.qc.metrics ?? null;
      row.statsVersion = result?.job.tool_version ?? null;
      row.state = row.stats ? "done" : stateOf(latestJobFor(jobs, STATS_JOB, file.id, false));
      const parentStats = parent ? results.get(parent.id)?.qc.metrics : undefined;
      if (row.stats && parentStats?.total_bases) row.shareOfParent = (100 * row.stats.total_bases) / parentStats.total_bases;
    } else if (row.kind === "signal") {
      const done = latestJobFor(jobs, POD5_JOB, file.id);
      const summary = done?.result_summary as unknown as Pod5Summary | undefined;
      if (summary?.reads) row.signal = { reads: summary.reads.count, durationS: summary.reads.total_signal_duration_s };
      row.state = row.signal ? "done" : stateOf(latestJobFor(jobs, POD5_JOB, file.id, false));
    }
    return row;
  });
}

// --- Project QC overview -----------------------------------------------------------------

export type QcSortKey =
  | "sample"
  | "technology"
  | "files"
  | "reads"
  | "bases"
  | "n50"
  | "quality"
  | "q30"
  | "gc"
  | "depth"
  | "kept"
  | "fastqc"
  | "seqkit";
export type SortDirection = "asc" | "desc";

/** Disagreements first when sorting ascending; samples without a check have no value. */
const SEQKIT_RANK = { disagree: 0, partial: 1, agree: 2, not_run: null } as const;

export function qcSortValue(row: QcOverviewRow, key: QcSortKey): string | number | null {
  switch (key) {
    case "sample":
      return row.sample_code;
    case "technology":
      return row.sequencing_technology;
    case "files":
      return row.imported_files + row.derived_files;
    case "reads":
      return row.total_reads;
    case "bases":
      return row.total_bases;
    case "n50":
      return row.n50;
    case "quality":
      return row.mean_read_quality;
    case "q30":
      return row.q30_percent;
    case "gc":
      return row.gc_percent;
    case "depth":
      return row.estimated_depth;
    case "kept":
      return row.filtering?.bases_kept_percent ?? null;
    case "fastqc":
      return row.fastqc.files ? row.fastqc.fail_count : null;
    case "seqkit":
      return SEQKIT_RANK[row.seqkit.status];
  }
}

const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

/** Stable sort; rows without a value always come last, whichever the direction. */
export function sortQcRows(rows: QcOverviewRow[], key: QcSortKey, direction: SortDirection): QcOverviewRow[] {
  const sign = direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: qcSortValue(row, key) }))
    .sort((a, b) => {
      if (a.value === null || b.value === null) {
        if (a.value === b.value) return a.index - b.index;
        return a.value === null ? 1 : -1;
      }
      const cmp = typeof a.value === "number" && typeof b.value === "number" ? a.value - b.value : collator.compare(String(a.value), String(b.value));
      return cmp ? sign * cmp : a.index - b.index;
    })
    .map((x) => x.row);
}

export function filterQcRows(rows: QcOverviewRow[], technology: SequencingTechnology | "all"): QcOverviewRow[] {
  return technology === "all" ? rows : rows.filter((r) => r.sequencing_technology === technology);
}

const TECHNOLOGY_ORDER: SequencingTechnology[] = ["illumina", "nanopore", "pacbio", "hybrid", "unknown"];

export function technologiesIn(rows: QcOverviewRow[]): SequencingTechnology[] {
  const present = new Set(rows.map((r) => r.sequencing_technology));
  return TECHNOLOGY_ORDER.filter((t) => present.has(t));
}

/** Why the read totals of a sample are not stated, or null when they are. */
export function missingStatsReason(row: QcOverviewRow): "no_files" | "no_read_files" | "incomplete" | null {
  if (row.imported_read_files === 0) return row.imported_files === 0 ? "no_files" : "no_read_files";
  return row.imported_read_files_with_stats < row.imported_read_files ? "incomplete" : null;
}
