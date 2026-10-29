import type { TranslationKey, TranslationVars } from "@/i18n";
import { messageText } from "@/lib/messages";
import type { MapFeature, MobileMapElement, MobileMethod, MobilePlan, MobileRequest, MobileWarning, VirulenceMapHit } from "@/lib/types";

export const MOBILE_JOB = "mobile_elements";
export const VIRULENCE_JOB = "virulence_screen";
export const MOBILE_METHODS: MobileMethod[] = ["mobsuite", "plasmidfinder", "integronfinder", "isescan", "genomad"];
/** The tool each method runs (its id in the tool registry). */
export const METHOD_TOOL: Record<MobileMethod, string> = {
  mobsuite: "mobsuite",
  plasmidfinder: "abricate",
  integronfinder: "integronfinder",
  isescan: "isescan",
  genomad: "genomad",
};

type T = (key: TranslationKey, vars?: TranslationVars) => string;

export function warningText(t: T, w: MobileWarning, prefix: "mobile" | "virulence" = "mobile"): string {
  return messageText(t, prefix === "mobile" ? "mobile.warning" : "virulence.warning", { code: w.code, params: w.params, text: w.code });
}

/** The command-line option of a setting, as the tool's --help names it. */
export function flagOf(method: MobileMethod, key: string): string {
  if (method === "mobsuite" || method === "plasmidfinder") return `--${key}`;
  if (method === "isescan") return key === "remove_short_is" ? "--removeShortIS" : `--${key}`;
  return `--${key.replace(/_/g, "-")}`;
}

export type SettingKind = "bool" | "int" | "float";

/** A setting's kind from ARVA's default as the plan states it ("True", "80", "1e-05"). */
export function settingKind(value: string): SettingKind {
  if (value === "True" || value === "False") return "bool";
  return /^-?\d+$/.test(value) ? "int" : "float";
}

export interface MobileForm {
  assemblyId: string;
  method: MobileMethod;
  databaseId: string;
  settings: Record<string, string>;
  threads: string;
  confirmed: boolean;
}

export const initialMobileForm = (assemblyId: string, method: MobileMethod = "mobsuite"): MobileForm => ({
  assemblyId,
  method,
  databaseId: "",
  settings: {},
  threads: "",
  confirmed: false,
});

/** The settings to send: ARVA's defaults from the plan, replaced by what the user changed. */
export function mobileSettings(form: MobileForm, plan: MobilePlan | undefined): Record<string, number | boolean> {
  const out: Record<string, number | boolean> = {};
  for (const [key, def] of Object.entries(plan?.defaults ?? {})) {
    if (key === "database" || key === "union_integrases" || key === "keep_palindromes" || key === "fraggenescan") continue;
    const value = form.settings[key] ?? def;
    const kind = settingKind(def);
    out[key] = kind === "bool" ? value === "True" : Number(value);
  }
  return out;
}

/** What the form still needs (translation keys). */
export function mobileProblems(form: MobileForm, plan: MobilePlan | undefined): TranslationKey[] {
  const out: TranslationKey[] = [];
  for (const [key, def] of Object.entries(plan?.defaults ?? {})) {
    const value = form.settings[key];
    if (value === undefined || settingKind(def) === "bool") continue;
    if (value.trim() === "" || !Number.isFinite(Number(value)) || (settingKind(def) === "int" && !Number.isInteger(Number(value)))) {
      out.push("mobile.problem.setting");
      break;
    }
  }
  if (form.threads && !(Number.isInteger(Number(form.threads)) && Number(form.threads) >= 1 && Number(form.threads) <= (plan?.tool.max_threads ?? 256)))
    out.push("amr.problem.threads");
  if (!form.confirmed) out.push("amr.problem.confirm");
  return out;
}

export function mobileBody(form: MobileForm, plan: MobilePlan | undefined): MobileRequest {
  return {
    method: form.method,
    settings: mobileSettings(form, plan),
    database_id: form.databaseId || null,
    threads: form.threads ? Number(form.threads) : null,
    confirmed: form.confirmed,
  };
}

/** Badge tone of MOB-suite's call: plasmid blue, chromosome (not assigned) neutral. */
export const callTone = (molecule: string | null | undefined): "blue" | "neutral" => (molecule === "plasmid" ? "blue" : "neutral");

/** The mobile-elements ring's elements as map features (ids below the AMR rings', so they never collide). */
export function mobileFeatures(elements: MobileMapElement[]): MapFeature[] {
  return elements.map((e, i) => ({
    id: -(i + 1) - 200000,
    locus_tag: e.feature?.locus_tag ?? null,
    tool_id: null,
    type: "mobile",
    start: e.start,
    end: e.end,
    strand: e.strand ?? ".",
    length: e.end - e.start + 1,
    edge: false,
    gene: e.element,
    product: e.element_type,
    hypothetical: null,
    pseudo: false,
    partial: null,
    contig: e.contig,
    mobile: e,
  }));
}

/** VFDB hits as features of the virulence ring, beside AMRFinderPlus's (each arc keeps its source). */
export function vfdbFeatures(hits: VirulenceMapHit[]): MapFeature[] {
  return hits.map((h, i) => ({
    id: -(i + 1) - 300000,
    locus_tag: h.feature?.locus_tag ?? null,
    tool_id: null,
    type: "virulence",
    start: h.start,
    end: h.end,
    strand: h.strand ?? ".",
    length: h.end - h.start + 1,
    edge: false,
    gene: h.gene,
    product: h.vf_name ?? h.product,
    hypothetical: null,
    pseudo: false,
    partial: null,
    contig: h.contig,
    vfdb: h,
  }));
}

/** A mobile element is drawn filled when complete (a whole plasmid contig, a complete integron or IS element, a
 * replicon covering its reference), hollow when partial or of unknown completeness. */
export function isWholeElement(e: Pick<MobileMapElement, "category" | "completeness">): boolean {
  if (e.category === "plasmid_contig" || e.category === "biomarker" || e.category === "mge") return true;
  return e.completeness === "complete" || e.completeness === "complete_gaps";
}

/** The category's name key for legends, tooltips and tables. */
export const categoryKey = (category: string) => `mobile.category.${category}` as TranslationKey;

export const COMPLETENESS_TONE: Record<string, "success" | "warning" | "neutral" | "blue"> = {
  complete: "success",
  complete_gaps: "blue",
  partial: "warning",
  contig_end: "warning",
  In0: "neutral",
  CALIN: "neutral",
};
