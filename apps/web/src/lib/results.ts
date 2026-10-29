import type { TranslationKey, TranslationVars } from "@/i18n";
import type { AnalysisJobDetail, FileFormat, QCResult } from "./types";

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

const LABELLED_JOBS = new Set([
  "sequence_stats", "seqkit_stats", "fastqc", "fastp", "filtlong", "server_import", "bakta_annotation", "prokka_annotation",
  "mlst_typing", "species_identification", "mobile_elements", "virulence_screen",
]);

export const FILTER_JOBS = new Set(["fastp", "filtlong"]);
export const IMPORT_JOBS = new Set(["server_import"]);
/** Jobs on raw signal (POD5): part of the raw-data stage, not of read QC. */
export const RAW_SIGNAL_JOBS = new Set(["pod5_summary"]);

export function jobLabel(type: string, t: (key: TranslationKey) => string) {
  if (type === "multiqc") return t("multiqc.jobLabel");
  if (type === "nanoplot") return t("nanoplot.jobLabel");
  if (type === "flye_assembly") return t("flye.jobLabel");
  if (type === "spades_assembly") return t("spades.jobLabel");
  if (type === "unicycler_assembly") return t("unicycler.jobLabel");
  if (type === "quast_evaluation") return t("quast.jobLabel");
  if (type === "racon_polish") return t("polishing.jobLabel.racon");
  if (type === "pilon_polish") return t("polishing.jobLabel.pilon");
  if (RAW_SIGNAL_JOBS.has(type)) return t("pod5.jobLabel");
  return LABELLED_JOBS.has(type) ? t(`job.label.${type}` as TranslationKey) : type;
}

/** What ran a job that has no executable path: the separately installed pod5 library, or ARVA itself. */
export function inProcessTool(job: Pick<AnalysisJobDetail, "job_type" | "tool_version" | "parameters">, t: (key: TranslationKey, vars?: TranslationVars) => string) {
  if (!RAW_SIGNAL_JOBS.has(job.job_type)) return t("history.builtIn");
  const lib = job.parameters?.lib_pod5_version;
  return t("pod5.executable", { version: job.tool_version, lib: typeof lib === "string" ? lib : "?" });
}

/** Files with reads; POD5 raw signal and unrecognised files are never offered for read-level analyses. */
export const hasReads = (format: FileFormat) => format !== "unknown" && format !== "pod5";

export const basename = (p: string) => p.split("/").pop() ?? p;
