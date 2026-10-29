import type { TranslationKey, TranslationVars } from "@/i18n";
import { messageText } from "@/lib/messages";
import type { SpeciesCheck, SpeciesCode, SpeciesHit, SpeciesMethod, SpeciesPlan, SpeciesRequest, SpeciesStatus } from "@/lib/types";

export const SPECIES_JOB = "species_identification";
export const SPECIES_METHODS: SpeciesMethod[] = ["fastani", "skani", "mash", "sylph", "gtdbtk"];
/** Methods whose value is an ANI estimate the species boundary applies to (Mash's distance is not one). */
export const ANI_METHODS = new Set<SpeciesMethod>(["fastani", "skani", "sylph", "gtdbtk"]);
/** The hits drawn in the chart; the table shows them all. */
export const CHART_HITS = 10;

type T = (key: TranslationKey, vars?: TranslationVars) => string;

export const STATUS_TONE: Record<SpeciesStatus, "success" | "warning" | "danger" | "neutral" | "blue"> = {
  same_species: "success",
  ambiguous: "warning",
  below_boundary: "neutral",
  no_hits: "neutral",
  screening_only: "blue",
};

export const CHECK_TONE: Record<SpeciesCheck["outcome"], "success" | "warning" | "neutral"> = {
  agree: "success",
  genus_agrees: "success",
  differs: "warning",
  not_comparable: "neutral",
};

const fixed = (v: unknown, digits: number) => (typeof v === "number" ? v.toFixed(digits) : String(v ?? "?"));

/** A reason or caveat code with its values formatted for the interface (ANI to 2 decimals, AF to 2). */
function formatted(c: SpeciesCode): SpeciesCode["params"] {
  const p = { ...c.params };
  for (const k of ["ani", "other_ani", "boundary"]) if (k in p) p[k] = fixed(p[k], 2);
  for (const k of ["af", "min_af"]) if (k in p) p[k] = fixed(p[k], 2);
  return p;
}

export const reasonText = (t: T, c: SpeciesCode) => messageText(t, "species.reason", { code: c.code, params: formatted(c), text: c.code });
export const caveatText = (t: T, c: SpeciesCode) => messageText(t, "species.caveat", { code: c.code, params: formatted(c), text: c.code });
export const warningText = (t: T, c: SpeciesCode) => messageText(t, "species.warning", { code: c.code, params: c.params, text: c.code });

export function statusText(t: T, status: SpeciesStatus, species: string | null): string {
  return t(`species.status.${status}` as TranslationKey, { species: species ?? "" });
}

export function checkText(t: T, c: SpeciesCheck): string {
  const what = c.source === "mlst"
    ? t("species.check.mlst", { scheme: c.params.scheme || "—", st: c.params.st || "—" })
    : t("species.check.annotation", { given: c.params.given ?? "", tool: c.params.tool ?? "" });
  const outcome = c.outcome === "not_comparable" && c.reason ? t(`species.check.reason.${c.reason}` as TranslationKey) : t(`species.check.${c.outcome}` as TranslationKey);
  return `${what}: ${outcome}`;
}

/** The hit's aligned fraction as a percentage, or null when the method gives none. */
export const afPercent = (h: Pick<SpeciesHit, "af">) => (typeof h.af === "number" ? h.af * 100 : null);

export interface SpeciesForm {
  assemblyId: string;
  method: SpeciesMethod;
  databaseId: string;
  threads: string;
  confirmed: boolean;
}

export const initialSpeciesForm = (assemblyId: string): SpeciesForm => ({ assemblyId, method: "fastani", databaseId: "", threads: "", confirmed: false });

/** What the form still needs before the run can start (translation keys). */
export function speciesProblems(form: SpeciesForm, plan: SpeciesPlan | undefined): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (form.threads && !(Number.isInteger(Number(form.threads)) && Number(form.threads) >= 1 && Number(form.threads) <= (plan?.tool.max_threads ?? 256)))
    out.push("species.problem.threads");
  if (!form.confirmed) out.push("species.problem.confirm");
  return out;
}

export function speciesBody(form: SpeciesForm): SpeciesRequest {
  return { method: form.method, database_id: form.databaseId || null, threads: form.threads ? Number(form.threads) : null, confirmed: form.confirmed };
}
