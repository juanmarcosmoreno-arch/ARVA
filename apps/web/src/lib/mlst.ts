import type { TranslationKey, TranslationVars } from "@/i18n";
import { messageText } from "@/lib/messages";
import type { MlstClonalComplex, MlstPlan, MlstRequest, MlstWarning } from "@/lib/types";

export const MLST_JOB = "mlst_typing";
/** mlst 2.35.0's own --exclude default (its --help); ARVA passes it explicitly unless the user changes it. */
export const MLST_DEFAULT_EXCLUDE = ["ecoli", "abaumannii", "vcholerae_2", "senterica_achtman_2"];

type T = (key: TranslationKey, vars?: TranslationVars) => string;

export function warningText(t: T, w: MlstWarning): string {
  return messageText(t, "mlst.warning", { code: w.code, params: w.params, text: w.code });
}

/** The clonal complex as the scheme's profile file gives it, or why there is none. */
export function clonalComplexText(t: T, cc: MlstClonalComplex): string {
  if (cc.reason === "no_scheme") return t("mlst.cc.noScheme");
  if (!cc.available) return t("mlst.cc.notInScheme");
  if (cc.reason === "no_st") return t("mlst.cc.noSt");
  return cc.value ?? t("mlst.cc.empty");
}

export interface MlstForm {
  assemblyId: string;
  scheme: string;
  minid: string;
  mincov: string;
  minscore: string;
  excludeDefaults: boolean;
  threads: string;
  confirmed: boolean;
}

export const initialMlstForm = (assemblyId: string): MlstForm => ({
  assemblyId,
  scheme: "",
  minid: "95",
  mincov: "50",
  minscore: "50",
  excludeDefaults: true,
  threads: "",
  confirmed: false,
});

const inRange = (v: string, low: number, high: number, open = true) => {
  const n = Number(v);
  return v.trim() !== "" && Number.isFinite(n) && (open ? n > low : n >= low) && n <= high;
};

/** What the form still needs before mlst can run (translation keys). */
export function mlstProblems(form: MlstForm, plan: MlstPlan | undefined): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (!inRange(form.minid, 0, 100)) out.push("mlst.problem.minid");
  if (!inRange(form.mincov, 0, 100)) out.push("mlst.problem.mincov");
  if (!form.scheme && !inRange(form.minscore, 0, 100, false)) out.push("mlst.problem.minscore");
  if (form.threads && !(Number.isInteger(Number(form.threads)) && Number(form.threads) >= 1 && Number(form.threads) <= (plan?.tool.max_threads ?? 256)))
    out.push("mlst.problem.threads");
  if (!form.confirmed) out.push("mlst.problem.confirm");
  return out;
}

export function mlstBody(form: MlstForm): MlstRequest {
  const scheme = form.scheme || null;
  return {
    settings: {
      scheme,
      minid: Number(form.minid),
      mincov: Number(form.mincov),
      minscore: scheme ? 0 : Number(form.minscore),
      exclude: scheme ? [] : form.excludeDefaults ? MLST_DEFAULT_EXCLUDE : [],
    },
    threads: form.threads ? Number(form.threads) : null,
    confirmed: form.confirmed,
  };
}
