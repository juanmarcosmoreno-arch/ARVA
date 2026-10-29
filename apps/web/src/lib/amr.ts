import type { TranslationKey, TranslationVars } from "@/i18n";
import { messageText } from "@/lib/messages";
import type { AmrHit, AmrMapHit, AmrPlan, AmrRequest, AmrWarning, MapFeature } from "@/lib/types";

export const AMR_JOB = "amr_detection";

type T = (key: TranslationKey, vars?: TranslationVars) => string;

export function warningText(t: T, w: AmrWarning): string {
  return messageText(t, "amr.warning", { code: w.code, params: w.params, text: w.code });
}

/** Badge tone of AMRFinderPlus's method, by ARVA's reading of it: anything short of a complete match is marked. */
export const KIND_TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "blue"> = {
  complete: "success",
  point: "blue",
  partial: "warning",
  contig_end: "warning",
  internal_stop: "danger",
  frameshift: "danger",
  extended: "warning",
  ambiguous: "warning",
  hmm: "neutral",
  other: "neutral",
};

export const KNOWN_KINDS = Object.keys(KIND_TONE);

export function kindText(t: T, kind: string): string {
  return t(`amr.kind.${KNOWN_KINDS.includes(kind) ? kind : "other"}` as TranslationKey);
}

export const isPointMutation = (h: Pick<AmrHit, "subtype">) => h.subtype === "POINT" || h.subtype === "POINT_DISRUPT";

/** The circular map's ring for an element: virulence genes on the virulence ring, the rest (AMR genes, point
 * mutations, stress response) on the AMR ring. */
export const ringOf = (h: Pick<AmrHit, "type">): "amr" | "virulence" => (h.type === "VIRULENCE" ? "virulence" : "amr");

/** AMRFinderPlus elements as features of the map (negative ids, so they never collide with annotation features). */
export function amrFeatures(hits: AmrMapHit[], ring: "amr" | "virulence"): MapFeature[] {
  return hits
    .filter((h) => ringOf(h) === ring && h.start != null)
    .map((h, i) => ({
      id: -(i + 1) - (ring === "virulence" ? 100000 : 0),
      locus_tag: h.feature?.locus_tag ?? null,
      tool_id: null,
      type: ring,
      start: h.start as number,
      end: h.end,
      strand: h.strand ?? ".",
      length: h.end - (h.start as number) + 1,
      edge: false,
      gene: h.element_symbol,
      product: h.element_name,
      hypothetical: null,
      pseudo: false,
      partial: null,
      contig: h.contig,
      amr: h,
    }));
}

export interface AmrForm {
  assemblyId: string;
  databaseId: string;
  mode: "nucleotide" | "combined";
  annotationId: string;
  organism: string;
  organismTouched: boolean;
  plus: boolean;
  curated: boolean;
  identMin: string;
  coverageMin: string;
  translationTable: string;
  threads: string;
  confirmed: boolean;
}

export const initialAmrForm = (assemblyId: string): AmrForm => ({
  assemblyId,
  databaseId: "",
  mode: "nucleotide",
  annotationId: "",
  organism: "",
  organismTouched: false,
  plus: true,
  curated: true,
  identMin: "0.9",
  coverageMin: "0.5",
  translationTable: "11",
  threads: "",
  confirmed: false,
});

const proportion = (v: string) => {
  const n = Number(v);
  return v.trim() !== "" && Number.isFinite(n) && n > 0 && n <= 1;
};

/** What the form still needs before AMRFinderPlus can run (translation keys). */
export function amrProblems(form: AmrForm, plan: AmrPlan | undefined): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (!form.curated && !proportion(form.identMin)) out.push("amr.problem.identMin");
  if (!proportion(form.coverageMin)) out.push("amr.problem.coverageMin");
  const table = Number(form.translationTable);
  if (!(Number.isInteger(table) && table >= 1 && table <= 33)) out.push("amr.problem.translationTable");
  if (form.mode === "combined" && !form.annotationId) out.push("amr.problem.annotation");
  if (form.organism && plan && !plan.organisms.includes(form.organism)) out.push("amr.problem.organism");
  if (form.threads && !(Number.isInteger(Number(form.threads)) && Number(form.threads) >= 1 && Number(form.threads) <= (plan?.tool.max_threads ?? 256)))
    out.push("amr.problem.threads");
  if (!form.confirmed) out.push("amr.problem.confirm");
  return out;
}

export function amrBody(form: AmrForm): AmrRequest {
  return {
    settings: {
      mode: form.mode,
      organism: form.organism || null,
      plus: form.plus,
      ident_min: form.curated ? -1 : Number(form.identMin),
      coverage_min: Number(form.coverageMin),
      translation_table: Number(form.translationTable),
    },
    database_id: form.databaseId || null,
    annotation_id: form.mode === "combined" ? form.annotationId || null : null,
    threads: form.threads ? Number(form.threads) : null,
    confirmed: form.confirmed,
  };
}

/** "AMR genes", "point mutations", "virulence", "stress": the table sections, in order. */
export function sections(hits: AmrHit[]): { key: "amr" | "point" | "virulence" | "stress"; hits: AmrHit[] }[] {
  const out = [
    { key: "amr" as const, hits: hits.filter((h) => h.type === "AMR" && !isPointMutation(h)) },
    { key: "point" as const, hits: hits.filter((h) => isPointMutation(h)) },
    { key: "virulence" as const, hits: hits.filter((h) => h.type === "VIRULENCE") },
    { key: "stress" as const, hits: hits.filter((h) => h.type === "STRESS") },
  ];
  return out.filter((s) => s.hits.length > 0);
}

/** A cell of the project's presence/absence matrix: found (with any incomplete method), not found, not searched. */
export function matrixCell(searched: boolean, kinds: string[] | undefined): "found" | "incomplete" | "absent" | "not_searched" {
  if (!searched) return "not_searched";
  if (!kinds?.length) return "absent";
  return kinds.some((k) => k === "complete" || k === "point") ? "found" : "incomplete";
}
