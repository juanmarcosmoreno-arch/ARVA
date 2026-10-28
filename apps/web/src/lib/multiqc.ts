import type { TranslationKey } from "@/i18n";
import { fmtInt, fmtNum } from "./format";
import type { AnalysisJob, MultiqcColumn, MultiqcExclusionReason, MultiqcModule, MultiqcPlan, MultiqcUnit } from "./types";

export const MULTIQC_JOB = "multiqc";
export const MULTIQC_REPORT = "arva_multiqc_report.html";
export const MULTIQC_DATA = "multiqc_data.json";
export const MODULE_NAME: Record<MultiqcModule, string> = { fastqc: "FastQC", fastp: "fastp", seqkit: "SeqKit", filtlong: "Filtlong" };
const MODULE_ORDER: MultiqcModule[] = ["fastqc", "fastp", "seqkit", "filtlong"];

export const REASON_KEY: Record<MultiqcExclusionReason, TranslationKey> = {
  no_outputs: "multiqc.reason.no_outputs",
  derived_input: "multiqc.reason.derived_input",
  filtlong_without_target: "multiqc.reason.filtlong_without_target",
  output_missing: "multiqc.reason.output_missing",
  input_missing: "multiqc.reason.input_missing",
  input_invalid: "multiqc.reason.input_invalid",
  input_not_validated: "multiqc.reason.input_not_validated",
};

export const UNIT_KEY: Record<MultiqcUnit, TranslationKey> = {
  reads: "multiqc.unit.reads",
  sequences: "multiqc.unit.sequences",
  bases: "multiqc.unit.bases",
  bp: "multiqc.unit.bp",
  "%": "multiqc.unit.percent",
  fraction: "multiqc.unit.fraction",
  Phred: "multiqc.unit.phred",
};

/** ARVA's definition of each general-statistics value MultiQC 1.35 reports (see arva_tools.multiqc.GENERAL_STATS). */
export const DEFINITION_KEY: Record<string, TranslationKey> = {
  "fastqc:total_sequences": "multiqc.def.fastqc.total_sequences",
  "fastqc:percent_gc": "multiqc.def.fastqc.percent_gc",
  "fastqc:avg_sequence_length": "multiqc.def.fastqc.avg_sequence_length",
  "fastqc:median_sequence_length": "multiqc.def.fastqc.median_sequence_length",
  "fastqc:percent_duplicates": "multiqc.def.fastqc.percent_duplicates",
  "fastqc:percent_fails": "multiqc.def.fastqc.percent_fails",
  "fastp:before_filtering_read1_mean_length": "multiqc.def.fastp.read1_mean_length",
  "fastp:before_filtering_read2_mean_length": "multiqc.def.fastp.read2_mean_length",
  "fastp:filtering_result_passed_filter_reads": "multiqc.def.fastp.passed_filter_reads",
  "fastp:pct_surviving_reads": "multiqc.def.fastp.pct_surviving_reads",
  "fastp:pct_surviving_bases": "multiqc.def.fastp.pct_surviving_bases",
  "fastp:pct_adapter": "multiqc.def.fastp.pct_adapter",
  "fastp:pct_duplication": "multiqc.def.fastp.pct_duplication",
  "fastp:after_filtering_q30_rate": "multiqc.def.fastp.q30_rate",
  "fastp:after_filtering_q30_bases": "multiqc.def.fastp.q30_bases",
  "fastp:after_filtering_gc_content": "multiqc.def.fastp.gc_content",
  "seqkit:num_seqs": "multiqc.def.seqkit.num_seqs",
  "seqkit:sum_len": "multiqc.def.seqkit.sum_len",
  "seqkit:avg_len": "multiqc.def.seqkit.avg_len",
  "seqkit:N50": "multiqc.def.seqkit.n50",
  "seqkit:Q30_pct": "multiqc.def.seqkit.q30_pct",
  "seqkit:GC_pct": "multiqc.def.seqkit.gc_pct",
  "seqkit:AvgQual": "multiqc.def.seqkit.avg_qual",
  "filtlong:Target bases": "multiqc.def.filtlong.target_bases",
  "filtlong:Bases kept": "multiqc.def.filtlong.bases_kept",
};

export const columnId = (c: Pick<MultiqcColumn, "module" | "key">) => `${c.module}:${c.key}`;

/** ARVA's titles for values MultiQC stores as fractions (0–1) but titles for its ×100 display ("% > Q30"). */
export const FRACTION_TITLE_KEY: Record<string, TranslationKey> = {
  "fastp:after_filtering_q30_rate": "multiqc.title.fastp.q30_rate",
  "fastp:after_filtering_gc_content": "multiqc.title.fastp.gc_content",
};

/** MultiQC's column title (ARVA's unscaled counts leave an empty "()" where its "M" suffix was); for fractions,
 * ARVA's own title, because MultiQC's percentage title would sit above a value between 0 and 1. */
export function columnTitle(c: Pick<MultiqcColumn, "module" | "key" | "title" | "unit">, t: (key: TranslationKey) => string): string {
  if (c.unit === "fraction") {
    const key = FRACTION_TITLE_KEY[columnId(c)];
    return key ? t(key) : c.title.replace(/%/g, "").replace(/\s+/g, " ").trim() || c.key;
  }
  return c.title.replace(/\s*\(\)$/, "");
}

/** A raw value in its own unit: counts as integers, fractions and percentages as stored (rounded for display). */
export function formatStat(value: number | undefined, unit: MultiqcUnit): string {
  if (value === undefined || !Number.isFinite(value)) return "—";
  if (unit === "reads" || unit === "sequences" || unit === "bases") return fmtInt(value);
  if (unit === "fraction") return fmtNum(value, 4);
  if (unit === "%") return fmtNum(value, 2);
  return Number.isInteger(value) ? fmtInt(value) : fmtNum(value, 1);
}

/** Columns grouped by tool in report order; MultiQC's hidden-by-default columns only on request. */
export function columnGroups(columns: MultiqcColumn[], showAll: boolean) {
  return MODULE_ORDER.map((module) => ({ module, columns: columns.filter((c) => c.module === module && (showAll || !c.hidden)) })).filter(
    (g) => g.columns.length > 0,
  );
}

/** What a run would include, per sample in plan order: how many results of each tool and which were left out. */
export function planBySample(plan: MultiqcPlan) {
  const samples = new Map<string, { sampleId: string; code: string; inputs: MultiqcPlan["inputs"]; excluded: MultiqcPlan["excluded"] }>();
  const entry = (sampleId: string, code: string) => {
    if (!samples.has(sampleId)) samples.set(sampleId, { sampleId, code, inputs: [], excluded: [] });
    return samples.get(sampleId)!;
  };
  for (const i of plan.inputs) entry(i.sample_id, i.sample_code).inputs.push(i);
  for (const e of plan.excluded) entry(e.sample_id, e.sample_code).excluded.push(e);
  return [...samples.values()].sort((a, b) => a.code.localeCompare(b.code));
}

export const isActive = (j: Pick<AnalysisJob, "status">) => j.status === "pending" || j.status === "running";

/** Reports newest first: the newest one (whatever its status), the most recent completed one, whose general
 * statistics stay visible while a newer run is queued, running or failed, and the others. */
export function reportViews<T extends Pick<AnalysisJob, "status">>(reports: T[]) {
  const [latest, ...rest] = reports;
  const completed = reports.find((j) => j.status === "completed");
  return { latest, completed, previous: rest.filter((j) => j !== completed) };
}

export const outputNamed = (job: Pick<AnalysisJob, "output_paths">, name: string) => job.output_paths?.find((p) => p.split("/").pop() === name);
