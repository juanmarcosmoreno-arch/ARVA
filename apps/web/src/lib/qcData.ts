import { fmtInt } from "./format";
import type { AnalysisJobDetail, FastpMate, FastqcPosition, RawFile, SequencingTechnology } from "./types";

export const FASTQC_JOB = "fastqc";
export const FASTP_JOB = "fastp";
/** FastQC's adapter-content flags (limits.txt): WARN above 5 %, FAIL above 10 % of reads at any position. */
export const ADAPTER_WARN_PERCENT = 5;
export const ADAPTER_FAIL_PERCENT = 10;
/** Longer than any short-read platform writes (Illumina reads are at most 300 bp). */
export const LONG_READ_MIN_LENGTH = 1000;

/** A FastQC position or bin as text: "5" or "10–14" (1-based, inclusive). */
export function positionText(p: Pick<FastqcPosition, "start" | "end">) {
  return p.start === p.end ? fmtInt(p.start) : `${fmtInt(p.start)}–${fmtInt(p.end)}`;
}

/** Where a FastQC bin is drawn: a binned value is the mean over its positions, so at the bin's centre. */
export const binCentre = (p: Pick<FastqcPosition, "start" | "end">) => (p.start + p.end) / 2;

/** Copies per sequence in each of FastQC's 16 duplication bins (DuplicationLevel.java, 0.12.1). */
const GROUPED_LEVELS: Record<string, [number, number | null]> = {
  ">10": [10, 50],
  ">50": [51, 100],
  ">100": [101, 500],
  ">500": [501, 1000],
  ">1k": [1001, 5000],
  ">5k": [5001, 10000],
  ">10k+": [10001, null],
};

export function duplicationCopies(level: string): { min: number; max: number | null } | null {
  if (/^[1-9]$/.test(level)) return { min: Number(level), max: Number(level) };
  const range = GROUPED_LEVELS[level];
  return range ? { min: range[0], max: range[1] } : null;
}

export function copiesText(level: string) {
  const c = duplicationCopies(level);
  if (!c) return level;
  if (c.max === null) return `≥ ${fmtInt(c.min)}`;
  return c.min === c.max ? fmtInt(c.min) : `${fmtInt(c.min)}–${fmtInt(c.max)}`;
}

/** Long reads: a long-read sample, or reads longer than any short-read platform writes. */
export function isLongReadData(maxReadLength: number | null | undefined, technology: SequencingTechnology) {
  return technology === "nanopore" || technology === "pacbio" || (maxReadLength ?? 0) > LONG_READ_MIN_LENGTH;
}

/** Highest value of a curve and the first index reaching it; null for an empty or all-zero curve. */
export function curvePeak(values: number[]): { value: number; index: number } | null {
  let index = -1;
  values.forEach((v, i) => {
    if (v > 0 && (index < 0 || v > values[index])) index = i;
  });
  return index < 0 ? null : { value: values[index], index };
}

/** fastp writes one value per cycle 1…total_cycles; shorter curves (trimmed reads) are padded with null. */
export function padCurve(values: number[] | undefined, cycles: number): (number | null)[] {
  return Array.from({ length: cycles }, (_, i) => values?.[i] ?? null);
}

/** fastp's content curves are fractions of the bases at each cycle. */
export const asPercent = (values: (number | null)[]) => values.map((v) => (v === null ? null : 100 * v));

/** First and last insert size with at least one pair, so the chart is not drawn mostly empty. */
export function insertSizeSpan(histogram: number[]): [number, number] | null {
  const first = histogram.findIndex((v) => v > 0);
  if (first < 0) return null;
  let last = histogram.length - 1;
  while (histogram[last] === 0) last--;
  return [first, last];
}

/** The latest completed fastp run that read this file, or the one that wrote it. */
export function fastpJobFor(jobs: AnalysisJobDetail[], file: Pick<RawFile, "id" | "produced_by_job_id">) {
  const done = jobs.filter((j) => j.job_type === FASTP_JOB && j.status === "completed");
  return done.find((j) => (j.input_raw_file_ids ?? []).includes(file.id)) ?? done.find((j) => j.id === file.produced_by_job_id);
}

/** Which of fastp's reads a file is: R2 when it, or the file it was derived from, was the run's second input. */
export function fastpMate(job: Pick<AnalysisJobDetail, "input_raw_file_ids">, file: Pick<RawFile, "id" | "parent_file_id">): FastpMate {
  const inputs = job.input_raw_file_ids ?? [];
  const i = inputs.includes(file.id) ? inputs.indexOf(file.id) : inputs.indexOf(file.parent_file_id ?? "");
  return i === 1 ? "read2" : "read1";
}
