import type { TranslationKey } from "@/i18n";
import { inputsOf, type Roles } from "./shortReads";
import type {
  AlignmentStats,
  AnalysisJobDetail,
  Assembly,
  AssemblySummaryStats,
  ChangeKind,
  LongReadPreset,
  PilonFix,
  PolishingPlan,
  PolishingRequest,
  PolishingStrategy,
  PolishingSummary,
  ReadRole,
} from "./types";

export const RACON_JOB = "racon_polish";
export const PILON_JOB = "pilon_polish";
export const POLISHING_JOBS = new Set([RACON_JOB, PILON_JOB]);

export const STRATEGIES: PolishingStrategy[] = ["racon", "pilon", "hybrid"];
export const CHANGE_KINDS: ChangeKind[] = ["snp", "insertion", "deletion", "other"];
export const PRESETS: LongReadPreset[] = ["map-ont", "map-pb", "map-hifi"];
export const PILON_FIXES: PilonFix[] = ["snps", "indels", "gaps", "local"];
/** Rounds allowed by the server for either polisher. */
export const MAX_ROUNDS = 5;

/** The read roles each strategy uses. */
export const STRATEGY_ROLES: Record<PolishingStrategy, ReadRole[]> = {
  racon: ["long"],
  pilon: ["r1", "r2", "unpaired"],
  hybrid: ["long", "r1", "r2", "unpaired"],
};

/** The strategy the reads a sample has call for: long → Racon, short → Pilon, both → Racon then Pilon. */
export function strategyForData(data: { short: boolean; long: boolean }): PolishingStrategy | null {
  if (data.short && data.long) return "hybrid";
  return data.long ? "racon" : data.short ? "pilon" : null;
}

/** Roles kept for a strategy; the others are cleared so the request matches what the user sees. */
export function rolesFor(strategy: PolishingStrategy, roles: Roles): Roles {
  const used = new Set(STRATEGY_ROLES[strategy]);
  return { r1: used.has("r1") ? roles.r1 : "", r2: used.has("r2") ? roles.r2 : "", unpaired: used.has("unpaired") ? roles.unpaired : "", long: used.has("long") ? roles.long : "" };
}

export interface PolishingForm {
  strategy: PolishingStrategy;
  preset: LongReadPreset | "";
  raconRounds: string;
  match: string;
  mismatch: string;
  gap: string;
  window: string;
  quality: string;
  error: string;
  pilonRounds: string;
  stopWhenUnchanged: boolean;
  fix: PilonFix[];
  mindepth: string;
  minmq: string;
  minqual: string;
  heap: string;
  threads: string;
  quast: boolean;
  referenceId: string;
}

/** Racon's and Pilon's own defaults (racon --help; Pilon's bytecode, see the adapters). */
export const POLISHING_FORM_DEFAULTS: PolishingForm = {
  strategy: "racon",
  preset: "",
  raconRounds: "1",
  match: "3",
  mismatch: "-5",
  gap: "-4",
  window: "500",
  quality: "10",
  error: "0.3",
  pilonRounds: "1",
  stopWhenUnchanged: true,
  fix: [...PILON_FIXES],
  mindepth: "0.1",
  minmq: "0",
  minqual: "0",
  heap: "",
  threads: "",
  quast: false,
  referenceId: "",
};

const num = (s: string) => (s.trim() === "" ? null : Number(s));
const intIn = (s: string, min: number, max: number) => {
  const n = num(s);
  return n !== null && Number.isInteger(n) && n >= min && n <= max;
};
const numIn = (s: string, min: number, max: number, openMin = false) => {
  const n = num(s);
  return n !== null && Number.isFinite(n) && (openMin ? n > min : n >= min) && n <= max;
};

/** How many advanced settings differ from the defaults (shown on the collapsed section). */
export function changedRacon(form: PolishingForm): number {
  return (["match", "mismatch", "gap", "window", "quality", "error"] as const).filter((k) => Number(form[k]) !== Number(POLISHING_FORM_DEFAULTS[k])).length;
}

export function changedPilon(form: PolishingForm): number {
  return (["mindepth", "minmq", "minqual"] as const).filter((k) => Number(form[k]) !== Number(POLISHING_FORM_DEFAULTS[k])).length;
}

/** Why the form cannot be sent yet (translation keys); the server checks everything again. */
export function polishingProblems(form: PolishingForm, roles: Roles, plan: PolishingPlan | undefined, confirmed: boolean): TranslationKey[] {
  const out: TranslationKey[] = [];
  const s = form.strategy;
  const usesLong = s !== "pilon";
  const usesShort = s !== "racon";
  if (usesLong && !roles.long) out.push("polishing.problem.long");
  if (usesShort && !roles.r1 && !roles.r2 && !roles.unpaired) out.push("polishing.problem.short");
  if (usesShort && !!roles.r1 !== !!roles.r2) out.push("shortReads.problem.pair");
  if (usesLong && !form.preset) out.push("polishing.problem.preset");
  if (usesLong) {
    const ok =
      intIn(form.raconRounds, 1, MAX_ROUNDS) &&
      intIn(form.match, 1, 100) &&
      intIn(form.mismatch, -100, -1) &&
      intIn(form.gap, -100, -1) &&
      intIn(form.window, 100, 10_000) &&
      numIn(form.quality, 0, 60) &&
      numIn(form.error, 0, 1, true);
    if (!ok) out.push("polishing.problem.racon");
  }
  if (usesShort) {
    const ok = intIn(form.pilonRounds, 1, MAX_ROUNDS) && form.fix.length > 0 && numIn(form.mindepth, 0, 1000, true) && intIn(form.minmq, 0, 60) && intIn(form.minqual, 0, 60);
    if (!ok) out.push("polishing.problem.pilon");
    if (form.heap.trim() && !intIn(form.heap, 1, plan?.max_memory_gb ?? 1)) out.push("polishing.problem.heap");
  }
  if (form.threads.trim() && !intIn(form.threads, 1, plan?.max_threads ?? 1)) out.push("flye.problem.threads");
  if (plan && !plan.strategies_available.includes(s)) out.push("polishing.problem.tools");
  if (plan?.problem) out.push("shortReads.problem.server");
  if (plan?.confirmation_required && !confirmed) out.push("shortReads.problem.confirm");
  return out;
}

export function polishingRequest(form: PolishingForm, roles: Roles, confirmed: boolean): PolishingRequest {
  return {
    strategy: form.strategy,
    inputs: inputsOf(rolesFor(form.strategy, roles)),
    racon: {
      read_type: form.preset || null,
      rounds: Number(form.raconRounds),
      match: Number(form.match),
      mismatch: Number(form.mismatch),
      gap: Number(form.gap),
      window_length: Number(form.window),
      quality_threshold: Number(form.quality),
      error_threshold: Number(form.error),
    },
    pilon: {
      rounds: Number(form.pilonRounds),
      fix: PILON_FIXES.filter((f) => form.fix.includes(f)),
      mindepth: Number(form.mindepth),
      minmq: Number(form.minmq),
      minqual: Number(form.minqual),
      heap_gb: num(form.heap),
      stop_when_unchanged: form.stopWhenUnchanged,
    },
    threads: num(form.threads),
    quast: form.quast,
    quast_reference_file_id: form.quast && form.referenceId ? form.referenceId : null,
    reads_confirmed: confirmed,
  };
}

// --- Results -------------------------------------------------------------------------------------------------

export const polishingSummary = (job: AnalysisJobDetail): PolishingSummary | null =>
  POLISHING_JOBS.has(job.job_type) && job.status === "completed" && job.result_summary ? (job.result_summary as unknown as PolishingSummary) : null;

/** Changes by type for each round (events), for the bar chart; rounds without direct evidence are left out. */
export function changeSeries(summary: PolishingSummary): { round: number; source: string; values: Record<ChangeKind, number> }[] {
  return summary.rounds
    .filter((r) => r.changes)
    .map((r) => ({
      round: r.round,
      source: r.changes_source ?? "",
      values: Object.fromEntries(CHANGE_KINDS.map((k) => [k, r.changes![k].events])) as Record<ChangeKind, number>,
    }));
}

export type Direction = "lower" | "higher" | null;

export interface CompareRow {
  key: string;
  label: TranslationKey;
  before: number | null;
  after: number | null;
  digits: number;
  /** Which way the value moves when the reads agree better with the assembly; null when no direction applies. */
  better: Direction;
}

/** The reads' alignment to the draft and to the polished assembly (indirect indicators). */
export function indirectRows(summary: PolishingSummary): CompareRow[] {
  const b: Partial<AlignmentStats> = summary.indirect.before.stats;
  const a: Partial<AlignmentStats> = summary.indirect.after.stats;
  const rows: CompareRow[] = [
    { key: "mapped", label: "polishing.ind.mapped", before: b.mapped_percent ?? null, after: a.mapped_percent ?? null, digits: 2, better: "higher" },
    { key: "nm", label: "polishing.ind.editDistance", before: b.edit_distance_per_100_bases ?? null, after: a.edit_distance_per_100_bases ?? null, digits: 4, better: "lower" },
    { key: "indels", label: "polishing.ind.indels", before: b.indel_events_per_100kb ?? null, after: a.indel_events_per_100kb ?? null, digits: 1, better: "lower" },
  ];
  if (b.properly_paired_percent != null || a.properly_paired_percent != null) {
    rows.push({ key: "paired", label: "polishing.ind.properlyPaired", before: b.properly_paired_percent ?? null, after: a.properly_paired_percent ?? null, digits: 2, better: "higher" });
  }
  return rows;
}

/** ARVA's statistics of the draft and of the polished assembly. */
export function assemblyRows(summary: PolishingSummary): CompareRow[] {
  const b: Partial<AssemblySummaryStats> = summary.assembly_stats.before;
  const a: Partial<AssemblySummaryStats> = summary.assembly_stats.after;
  const row = (key: keyof AssemblySummaryStats, label: TranslationKey, digits = 0): CompareRow => ({ key, label, before: b[key] ?? null, after: a[key] ?? null, digits, better: null });
  return [
    row("contig_count", "assembly.stat.contigs"),
    row("total_length", "assembly.stat.totalLength"),
    row("largest_contig", "assembly.stat.largest"),
    row("n50", "assembly.stat.n50"),
    row("gc_percent", "assembly.stat.gc", 2),
  ];
}

/** "improved", "worse" or "same" for an indirect indicator; null when either value is missing or no direction applies. */
export function trend(row: CompareRow): "improved" | "worse" | "same" | null {
  if (row.before === null || row.after === null || row.better === null) return null;
  const scale = 10 ** row.digits;
  const diff = Math.round(row.after * scale) - Math.round(row.before * scale);
  if (diff === 0) return "same";
  return (diff < 0) === (row.better === "lower") ? "improved" : "worse";
}

/** The draft chain of an assembly, oldest first, ending with the assembly itself. */
export function lineage(assembly: Assembly, all: Assembly[]): Assembly[] {
  const byId = new Map(all.map((a) => [a.id, a]));
  const chain = [assembly];
  const seen = new Set([assembly.id]);
  for (let p = assembly.parent_assembly_id ? byId.get(assembly.parent_assembly_id) : undefined; p && !seen.has(p.id); p = p.parent_assembly_id ? byId.get(p.parent_assembly_id) : undefined) {
    seen.add(p.id);
    chain.unshift(p);
  }
  return chain;
}

/** Polished assemblies made directly from this one. */
export const polishedFrom = (assembly: Assembly, all: Assembly[]) => all.filter((a) => a.parent_assembly_id === assembly.id);
