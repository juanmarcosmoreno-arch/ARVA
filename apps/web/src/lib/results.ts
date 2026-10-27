import type { AnalysisJobDetail, QCResult } from "./types";

/** Latest completed ARVA statistics per file (jobs are ordered newest first by the API). */
export function latestResults(jobs: AnalysisJobDetail[]) {
  const map = new Map<string, { job: AnalysisJobDetail; qc: QCResult }>();
  for (const job of jobs) {
    if (job.status !== "completed") continue;
    for (const qc of job.qc_results) if (!map.has(qc.raw_file_id)) map.set(qc.raw_file_id, { job, qc });
  }
  return map;
}

/** Latest job of a type that used the given file as input. */
export function latestJobFor(jobs: AnalysisJobDetail[], type: string, fileId: string, completedOnly = true) {
  return jobs.find(
    (j) => j.job_type === type && (j.input_raw_file_ids ?? []).includes(fileId) && (!completedOnly || j.status === "completed"),
  );
}

export const JOB_LABEL: Record<string, string> = {
  sequence_stats: "Read statistics",
  seqkit_stats: "Independent check",
  fastqc: "FastQC report",
  fastp: "Filtering (fastp)",
  filtlong: "Filtering (Filtlong)",
  server_import: "Import from server folder",
};

export const FILTER_JOBS = new Set(["fastp", "filtlong"]);
export const IMPORT_JOBS = new Set(["server_import"]);

export const basename = (p: string) => p.split("/").pop() ?? p;
