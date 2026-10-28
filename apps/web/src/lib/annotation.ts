import type { TranslationKey, TranslationVars } from "@/i18n";
import { dictionaries } from "@/i18n";
import type {
  AnnotationDependency,
  AnnotationPlan,
  AnnotationStep,
  Annotator,
  Assembly,
  BaktaRequest,
  ProkkaRequest,
  TranslationTable,
} from "./types";

export const BAKTA_JOB = "bakta_annotation";
export const PROKKA_JOB = "prokka_annotation";
export const ANNOTATION_JOBS = new Set([BAKTA_JOB, PROKKA_JOB]);
export const FEATURE_TYPES = ["cds", "sorf", "trna", "tmrna", "rrna", "ncrna", "ncrna_region", "crispr", "gap", "oric", "oriv", "orit", "other"] as const;
export const PAGE_SIZE = 50;
export const MAX_EXPORT = 10_000;

// The same rules as the API (and both annotators): see apps/api/app/schemas/schemas.py.
export const LOCUS_TAG = /^[A-Z][A-Z0-9]{2,11}$/;
export const GENUS = /^[A-Za-z]{2,50}$/;
export const SPECIES = /^[A-Za-z][A-Za-z.-]{0,49}$/;
export const STRAIN = /^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,39}$/;

type T = (key: TranslationKey, vars?: TranslationVars) => string;

const has = (key: string): key is TranslationKey => key in dictionaries.en;

export function stepLabel(t: T, tool: string, step: string): string {
  const key = tool.toLowerCase() === "prokka" && step === "trna" ? "annotation.step.trnaProkka" : `annotation.step.${step}`;
  return has(key) ? t(key) : step;
}

export function dependencyText(t: T, d: AnnotationDependency): string {
  const key = `annotation.dependency.${d.status}`;
  return has(key) ? t(key, { name: d.name, found: d.found ?? "?", minimum: d.minimum ?? "?", code: d.returncode ?? "?" }) : `${d.name}: ${d.status}`;
}

/** Why a step did not run (or failed), in the interface language. */
export function stepReason(t: T, s: AnnotationStep): string {
  if (s.reason === "dependency" && s.dependencies.length) return s.dependencies.map((d) => dependencyText(t, d)).join("; ");
  if (s.reason === "crashed") return t("annotation.reason.crashed", { code: s.returncode ?? "?" });
  const key = `annotation.reason.${s.reason}`;
  return s.reason && has(key) ? t(key) : s.reason ?? "";
}

/** The state of a step: after the run when the annotation has it, else the plan. */
export function stepState(s: AnnotationStep): "searched" | "skipped" | "failed" | "planned" {
  return s.status ?? (s.run ? "planned" : "skipped");
}

/** Whether a feature type was searched, so a count of zero is a result and not "not searched". */
export function searched(steps: Record<string, AnnotationStep>, step: string): boolean {
  return steps[step]?.status === "searched";
}

/** Only https URLs are rendered as links (the server builds them from identifiers the annotator reported). */
export function safeExternalUrl(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** Assemblies ordered by lineage: each draft followed by the assemblies polished from it (depth for indentation). */
export function assemblyOptions(assemblies: Assembly[]): { assembly: Assembly; depth: number }[] {
  const ids = new Set(assemblies.map((a) => a.id));
  const children = new Map<string, Assembly[]>();
  for (const a of assemblies) {
    const parent = a.parent_assembly_id && ids.has(a.parent_assembly_id) ? a.parent_assembly_id : "";
    children.set(parent, [...(children.get(parent) ?? []), a]);
  }
  const out: { assembly: Assembly; depth: number }[] = [];
  const walk = (parent: string, depth: number) => {
    for (const a of [...(children.get(parent) ?? [])].sort((x, y) => x.created_at.localeCompare(y.created_at))) {
      out.push({ assembly: a, depth });
      walk(a.id, depth + 1);
    }
  };
  walk("", 0);
  return out;
}

export interface AnnotationForm {
  annotator: Annotator;
  assemblyId: string;
  databaseId: string;
  locusTag: string;
  translationTable: TranslationTable;
  genus: string;
  species: string;
  strain: string;
  minContig: string;
  threads: string;
  complete: boolean;
  completeConfirmed: boolean;
  keepHeaders: boolean;
  skipPlot: boolean;
  rfam: boolean;
  useGenus: boolean;
  evalue: string;
  coverage: string;
  rename: boolean;
  confirmed: boolean;
}

export const initialForm = (assemblyId = ""): AnnotationForm => ({
  annotator: "bakta",
  assemblyId,
  databaseId: "",
  locusTag: "",
  translationTable: 11,
  genus: "",
  species: "",
  strain: "",
  minContig: "1",
  threads: "",
  complete: false,
  completeConfirmed: false,
  keepHeaders: false,
  skipPlot: false,
  rfam: false,
  useGenus: false,
  evalue: "1e-09",
  coverage: "80",
  rename: false,
  confirmed: false,
});

const text = (s: string) => (s.trim() === "" ? null : s.trim());
const num = (s: string) => (s.trim() === "" ? null : Number(s));

/** Problems that keep the form from being sent (i18n keys); the server checks everything again. */
export function annotationProblems(form: AnnotationForm, plan: AnnotationPlan | undefined): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (!form.assemblyId) out.push("annotation.problem.assembly");
  if (!LOCUS_TAG.test(form.locusTag)) out.push("annotation.problem.locusTag");
  if (text(form.genus) && !GENUS.test(form.genus.trim())) out.push("annotation.problem.genus");
  if (text(form.species) && !SPECIES.test(form.species.trim())) out.push("annotation.problem.species");
  if (text(form.species) && !text(form.genus)) out.push("annotation.problem.speciesNeedsGenus");
  if (text(form.strain) && !STRAIN.test(form.strain.trim())) out.push("annotation.problem.strain");
  const minContig = num(form.minContig);
  if (minContig === null || !Number.isInteger(minContig) || minContig < 1 || minContig > 1_000_000) out.push("annotation.problem.minContig");
  const threads = num(form.threads);
  if (threads !== null && (!Number.isInteger(threads) || threads < 1 || (plan && threads > plan.tool.max_threads))) out.push("annotation.problem.threads");
  if (form.annotator === "bakta" && form.complete && !form.completeConfirmed) out.push("annotation.problem.complete");
  if (form.annotator === "prokka") {
    const e = num(form.evalue);
    if (e === null || !(e > 0 && e <= 1)) out.push("annotation.problem.evalue");
    const c = num(form.coverage);
    if (c === null || !(c > 0 && c <= 100)) out.push("annotation.problem.coverage");
    if (form.useGenus && !text(form.genus)) out.push("annotation.problem.useGenus");
  }
  if (plan?.problems.length) out.push("annotation.problem.plan");
  if (!form.confirmed) out.push("annotation.problem.confirm");
  return out;
}

function organism(form: AnnotationForm) {
  return {
    locus_tag: form.locusTag,
    translation_table: form.translationTable,
    genus: text(form.genus),
    species: text(form.species),
    strain: text(form.strain),
    min_contig_length: Number(form.minContig),
  };
}

export function baktaBody(form: AnnotationForm, plan: AnnotationPlan): BaktaRequest {
  return {
    database_id: plan.database_id,
    settings: { ...organism(form), complete: form.complete, keep_contig_headers: form.keepHeaders, skip_plot: form.skipPlot },
    threads: num(form.threads),
    skip_options: plan.skip_options,
    complete_confirmed: form.complete && form.completeConfirmed,
    confirmed: form.confirmed,
  };
}

export function prokkaBody(form: AnnotationForm): ProkkaRequest {
  return {
    settings: {
      ...organism(form),
      use_genus: form.useGenus,
      rfam: form.rfam,
      evalue: Number(form.evalue),
      coverage: Number(form.coverage),
      rename_contigs: form.rename,
    },
    threads: num(form.threads),
    confirmed: form.confirmed,
  };
}
