import { dictionaries, interpolate, type TranslationKey, type TranslationVars } from "@/i18n";
import { fmtInt, fmtNum } from "./format";
import { ADAPTER_WARN_PERCENT } from "./qcData";
import type { latestResults } from "./results";
import type { AnalysisJobDetail, FastpParams, FastpSummary, FastqcData, FiltlongParams, RawFile } from "./types";

export type Translate = (key: TranslationKey, vars?: TranslationVars) => string;
const EN: Translate = (key, vars) => interpolate(dictionaries.en[key], vars);

/** fastp 0.23.4 defaults (verified from `fastp --help`); ARVA sends them explicitly. */
export const FASTP_DEFAULTS: FastpParams = {
  adapter_trimming: true,
  detect_adapter_for_pe: true,
  adapter_sequence: null,
  adapter_sequence_r2: null,
  quality_filtering: true,
  qualified_quality_phred: 15,
  unqualified_percent_limit: 40,
  n_base_limit: 5,
  average_qual: 0,
  low_complexity_filter: false,
  complexity_threshold: 30,
  length_filtering: true,
  length_required: 15,
  length_limit: 0,
  trim_front1: 0,
  trim_tail1: 0,
  max_len1: 0,
  trim_front2: null,
  trim_tail2: null,
  max_len2: null,
  cut_front: false,
  cut_tail: false,
  cut_window_size: 4,
  cut_mean_quality: 20,
  poly_g: "auto",
  dedup: false,
};

/** fastp's own limits (options.cpp, 0.23.2 and 0.23.4); it stops with an error outside them. */
export const TRIM_FRONT_MAX = 30;
export const TRIM_TAIL_MAX = 100;
export const ADAPTER_PATTERN = /^[ACGT]{4,200}$/;

export const FILTLONG_EMPTY: FiltlongParams = {
  min_length: null,
  max_length: null,
  min_mean_q: null,
  min_window_q: null,
  keep_percent: null,
  target_bases: null,
  length_weight: 1,
  mean_q_weight: 1,
  window_q_weight: 1,
  window_size: 250,
};

/** Filtlong mean identity (%) -> equivalent error-averaged Phred value. */
export function identityToPhred(identity: number): number {
  if (identity >= 100) return Infinity;
  return -10 * Math.log10(1 - identity / 100);
}

export function phredToIdentity(q: number): number {
  return 100 * (1 - 10 ** (-q / 10));
}

export function filtlongHasThreshold(p: FiltlongParams): boolean {
  return [p.min_length, p.max_length, p.min_mean_q, p.min_window_q, p.keep_percent, p.target_bases].some(
    (v) => v !== null && v !== undefined,
  );
}

/** What fastp does with a paired-end adapter that is not given (main.cpp/options.cpp, 0.23.2–0.23.4). */
export function pairedAdapter(p: FastpParams, mate: 1 | 2): { sequence: string } | "detected" | "read1" | "overlap" {
  const given = mate === 1 ? p.adapter_sequence : p.adapter_sequence_r2;
  if (given) return { sequence: given };
  if (p.detect_adapter_for_pe) return "detected";
  return mate === 2 && p.adapter_sequence ? "read1" : "overlap";
}

/** Read-2 options are sent only for pairs; adapters only with adapter trimming, and an empty field means "not given". */
export function fastpRequestParams(p: FastpParams, paired: boolean): FastpParams {
  const adapter = (s: string | null) => (s && p.adapter_trimming ? s : null);
  return {
    ...p,
    adapter_sequence: adapter(p.adapter_sequence),
    adapter_sequence_r2: paired ? adapter(p.adapter_sequence_r2) : null,
    trim_front2: paired ? p.trim_front2 : null,
    trim_tail2: paired ? p.trim_tail2 : null,
    max_len2: paired ? p.max_len2 : null,
  };
}

/** Problems ARVA's API would reject, as translation keys, so the dialog can say so before running. */
export function fastpProblems(p: FastpParams): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (p.length_limit > 0 && !p.length_filtering) out.push("filter.fastp.problem.limitWithoutFiltering");
  else if (p.length_limit > 0 && p.length_limit < p.length_required) out.push("filter.fastp.problem.limitBelowRequired");
  for (const s of [p.adapter_sequence, p.adapter_sequence_r2]) {
    if (s && !ADAPTER_PATTERN.test(s)) {
      out.push("filter.fastp.problem.adapter");
      break;
    }
  }
  return out;
}

/** Human-readable list of what fastp will remove or change with these settings. */
export function describeFastp(p: FastpParams, paired: boolean, t: Translate = EN): string[] {
  const out: string[] = [];
  if (p.adapter_trimming) {
    if (!paired) out.push(p.adapter_sequence ? t("filter.do.adapterGiven", { sequence: p.adapter_sequence }) : t("filter.do.adaptersAuto"));
    else {
      out.push(t(p.detect_adapter_for_pe ? "filter.do.adaptersPairedDetect" : "filter.do.adaptersPaired"));
      if (p.adapter_sequence || p.adapter_sequence_r2) {
        const text = (a: ReturnType<typeof pairedAdapter>) =>
          typeof a === "object" ? a.sequence : t(`filter.do.pairedAdapter.${a}` as TranslationKey);
        out.push(t("filter.do.adaptersPairedGiven", { r1: text(pairedAdapter(p, 1)), r2: text(pairedAdapter(p, 2)) }));
      }
    }
  }
  const mates: [string, number, number, number][] = [[paired ? "1" : "", p.trim_front1, p.trim_tail1, p.max_len1]];
  if (paired) mates.push(["2", p.trim_front2 ?? p.trim_front1, p.trim_tail2 ?? p.trim_tail1, p.max_len2 ?? p.max_len1]);
  for (const [mate, front, tail, maxLen] of mates) {
    const read = mate ? t("filter.do.readN", { mate }) : t("filter.do.reads");
    if (front > 0 || tail > 0) out.push(t("filter.do.fixedTrim", { read, front, tail }));
    if (maxLen > 0) out.push(t("filter.do.maxLen", { read, length: fmtInt(maxLen) }));
  }
  if (p.quality_filtering) {
    out.push(t("filter.do.unqualified", { percent: p.unqualified_percent_limit, q: p.qualified_quality_phred }));
    out.push(t("filter.do.nBases", { n: p.n_base_limit }));
    if (p.average_qual > 0) out.push(t("filter.do.averageQual", { q: p.average_qual }));
  }
  if (p.low_complexity_filter) out.push(t("filter.do.complexity", { percent: p.complexity_threshold }));
  if (p.cut_front || p.cut_tail)
    out.push(
      t("filter.do.window", {
        ends: [p.cut_front && "5′", p.cut_tail && "3′"].filter(Boolean).join(t("filter.do.and")),
        size: p.cut_window_size,
        q: p.cut_mean_quality,
      }),
    );
  if (p.length_filtering) {
    out.push(t("filter.do.minLength", { length: fmtInt(p.length_required) }));
    if (p.length_limit > 0) out.push(t("filter.do.lengthLimit", { length: fmtInt(p.length_limit) }));
  }
  if (p.poly_g === "force") out.push(t("filter.do.polyGForce"));
  if (p.poly_g === "auto") out.push(t("filter.do.polyGAuto"));
  if (p.dedup) out.push(t("filter.do.dedup"));
  if (paired) out.push(t("filter.do.pairs"));
  if (out.length === 0) out.push(t("filter.do.nothing"));
  return out;
}

export interface CoverageTarget {
  genome_size_bp: number;
  target_coverage_x: number;
}

export function describeFiltlong(p: FiltlongParams, t: Translate = EN, coverage: CoverageTarget | null = null): string[] {
  const out: string[] = [];
  if (p.min_length != null) out.push(t("filter.do.filtlong.minLength", { length: fmtInt(p.min_length) }));
  if (p.max_length != null) out.push(t("filter.do.filtlong.maxLength", { length: fmtInt(p.max_length) }));
  if (p.min_mean_q != null) out.push(t("filter.do.filtlong.meanQ", { identity: p.min_mean_q, q: fmtNum(identityToPhred(p.min_mean_q), 1) }));
  if (p.min_window_q != null)
    out.push(t("filter.do.filtlong.windowQ", { size: p.window_size, identity: p.min_window_q, q: fmtNum(identityToPhred(p.min_window_q), 1) }));
  if (p.keep_percent != null) out.push(t("filter.do.filtlong.keepPercent", { percent: p.keep_percent }));
  if (p.target_bases != null)
    out.push(
      coverage
        ? t("filter.do.filtlong.targetCoverage", {
            bases: fmtInt(p.target_bases),
            depth: fmtNum(coverage.target_coverage_x, 1),
            genome: fmtInt(coverage.genome_size_bp),
          })
        : t("filter.do.filtlong.target", { bases: fmtInt(p.target_bases) }),
    );
  return out;
}

/** ARVA's coverage target: target bases = round(depth × genome size); the server computes the same (half up). */
export function targetBasesForCoverage(genomeSizeBp: number, coverageX: number): number {
  return Math.round(coverageX * genomeSizeBp);
}

/**
 * The target Filtlong will use: --target_bases, or --keep_percent of the input bases, whichever is
 * smaller when both are set (main.cpp, truncated to an integer); null when it depends on unknown input.
 */
export function filtlongTarget(p: Pick<FiltlongParams, "target_bases" | "keep_percent">, inputBases: number | null): number | null {
  if (p.keep_percent == null) return p.target_bases;
  if (inputBases == null) return null;
  const keep = Math.floor((p.keep_percent / 100) * inputBases);
  return p.target_bases == null ? keep : Math.min(p.target_bases, keep);
}

/**
 * What Filtlong's --target_bases should keep, from ARVA's statistics of the input. Filtlong keeps the
 * best reads while its running total is below the target, so it can overshoot by up to one read
 * (at most target − 1 + longest read); with a target at or above the input it removes nothing for it.
 */
export type ExpectedKept = { kind: "unknown" } | { kind: "all"; bases: number } | { kind: "target"; min: number; max: number };

export function expectedKeptBases(target: number | null, input: { bases: number; longest: number } | null): ExpectedKept {
  if (target == null || !input) return { kind: "unknown" };
  if (target >= input.bases) return { kind: "all", bases: input.bases };
  return { kind: "target", min: target, max: Math.min(input.bases, target - 1 + input.longest) };
}

/** The genome size given for the latest statistics of the file (or of the file it was derived from); never assumed. */
export function storedGenomeSize(stats: ReturnType<typeof latestResults>, file: Pick<RawFile, "id" | "parent_file_id">) {
  for (const id of [file.id, file.parent_file_id]) {
    const size = id ? stats.get(id)?.qc.metrics.coverage_estimate?.expected_genome_size_bp : undefined;
    if (size) return size;
  }
  return null;
}

/** Highest cumulative % of reads per FastQC adapter, as in the stored FastQC summary. */
export type AdapterPeak = { name: string; max_percent: number };

/** The same peaks from fastqc_data, for FastQC jobs that predate the stored summary. */
export function adapterPeaks(data: Pick<FastqcData, "adapter_content">): AdapterPeak[] {
  return (data.adapter_content?.adapters ?? []).map((a) => ({ name: a.name, max_percent: Math.max(0, ...a.percent) }));
}

/** FastQC's PolyA/PolyG rows are homopolymers that fastp handles by poly-X/poly-G trimming, not adapter trimming. */
const NOT_ADAPTERS = new Set(["PolyA", "PolyG"]);

/**
 * FastQC saw an adapter in more than 5 % of the reads (its WARN level) but the latest fastp run on the
 * same file, with adapter trimming on, trimmed none: fastp's automatic detection can miss it.
 */
export function missedAdapter(peaks: AdapterPeak[] | null, previousFastp: AnalysisJobDetail | undefined) {
  if (!peaks || !previousFastp) return null;
  const params = previousFastp.parameters as Partial<FastpParams> | null;
  const summary = previousFastp.result_summary as unknown as FastpSummary | null;
  if (params?.adapter_trimming === false || !summary || (summary.adapter_trimmed_reads ?? 0) > 0) return null;
  const seen = peaks.filter((a) => !NOT_ADAPTERS.has(a.name) && a.max_percent > ADAPTER_WARN_PERCENT);
  return seen.sort((a, b) => b.max_percent - a.max_percent)[0] ?? null;
}

/** Build the lineage tree: imported files followed by their derived descendants. */
export function lineageOrder(files: RawFile[]): { file: RawFile; depth: number }[] {
  const children = new Map<string | null, RawFile[]>();
  for (const f of files) {
    const key = f.parent_file_id && files.some((p) => p.id === f.parent_file_id) ? f.parent_file_id : null;
    children.set(key, [...(children.get(key) ?? []), f]);
  }
  const out: { file: RawFile; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const f of children.get(parent) ?? []) {
      out.push({ file: f, depth });
      walk(f.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export function pct(part: number, whole: number): number {
  return whole ? (100 * part) / whole : 0;
}
