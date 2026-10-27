import type { FastpParams, FiltlongParams, RawFile } from "./types";

/** fastp 0.23.4 defaults (verified from `fastp --help`); ARVA sends them explicitly. */
export const FASTP_DEFAULTS: FastpParams = {
  adapter_trimming: true,
  detect_adapter_for_pe: true,
  quality_filtering: true,
  qualified_quality_phred: 15,
  unqualified_percent_limit: 40,
  n_base_limit: 5,
  average_qual: 0,
  length_filtering: true,
  length_required: 15,
  cut_front: false,
  cut_tail: false,
  cut_window_size: 4,
  cut_mean_quality: 20,
  poly_g: "auto",
  dedup: false,
};

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

/** Human-readable list of what fastp will remove or change with these settings. */
export function describeFastp(p: FastpParams, paired: boolean): string[] {
  const out: string[] = [];
  if (p.adapter_trimming)
    out.push(
      paired
        ? `Trim adapters (overlap analysis${p.detect_adapter_for_pe ? " + adapter auto-detection" : ""})`
        : "Trim adapters (auto-detected)",
    );
  if (p.quality_filtering) {
    out.push(`Remove reads with > ${p.unqualified_percent_limit}% of bases below Q${p.qualified_quality_phred}`);
    out.push(`Remove reads with > ${p.n_base_limit} N bases`);
    if (p.average_qual > 0) out.push(`Remove reads with average quality < Q${p.average_qual}`);
  }
  if (p.cut_front || p.cut_tail)
    out.push(
      `Trim ${[p.cut_front && "5′", p.cut_tail && "3′"].filter(Boolean).join(" and ")} ends where a ${p.cut_window_size}-base window has mean quality < Q${p.cut_mean_quality}`,
    );
  if (p.length_filtering) out.push(`Remove reads shorter than ${p.length_required} bp after trimming`);
  if (p.poly_g === "force") out.push("Trim poly-G tails (forced)");
  if (p.poly_g === "auto") out.push("Trim poly-G tails only if fastp detects NextSeq/NovaSeq data");
  if (p.dedup) out.push("Remove duplicated reads/pairs");
  if (paired) out.push("When one mate is removed, its partner is removed too");
  if (out.length === 0) out.push("No filtering: reads are copied unchanged");
  return out;
}

export function describeFiltlong(p: FiltlongParams): string[] {
  const out: string[] = [];
  if (p.min_length != null) out.push(`Remove reads shorter than ${p.min_length.toLocaleString("en-US")} bp`);
  if (p.max_length != null) out.push(`Remove reads longer than ${p.max_length.toLocaleString("en-US")} bp`);
  if (p.min_mean_q != null)
    out.push(`Remove reads with mean identity < ${p.min_mean_q}% (≈ Q${identityToPhred(p.min_mean_q).toFixed(1)})`);
  if (p.min_window_q != null)
    out.push(
      `Remove reads with any ${p.window_size}-bp window below ${p.min_window_q}% identity (≈ Q${identityToPhred(p.min_window_q).toFixed(1)})`,
    );
  if (p.keep_percent != null) out.push(`Then keep only the best ${p.keep_percent}% of bases`);
  if (p.target_bases != null) out.push(`Then keep only the best reads up to ${p.target_bases.toLocaleString("en-US")} bases`);
  return out;
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
