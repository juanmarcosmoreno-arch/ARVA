import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { Footer, PlanSummary } from "@/components/comparative/RunDialogs";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonPlan, ComparisonSet } from "@/lib/comparative";
import {
  ALIGNMENTS,
  CLEAN_MODES,
  DEFAULT_THRESHOLDS,
  PANAROO_DEFAULTS,
  type PanarooSettings,
  type PangenomeMethod,
  type PangenomeRequest,
  type Thresholds,
} from "@/lib/pangenome";

const CHECK = "mt-0.5 h-3.5 w-3.5 accent-arva-teal";
const CURVES = { permutations: 100, seed: 12345 };

function NumberField({ label, hint, value, step, onChange }: { label: string; hint?: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <Field label={label} hint={hint}>
      <Input type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  );
}

/** The pangenome of the set's genomes from their own annotations with Panaroo (or PPanGGOLiN when installed), after
 * the user saw each genome's annotation, every option and the category thresholds, and confirmed. */
export function PangenomeDialog({ open, onOpenChange, set }: { open: boolean; onOpenChange: (o: boolean) => void; set: ComparisonSet }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [method, setMethod] = useState<PangenomeMethod>("panaroo");
  const [panaroo, setPanaroo] = useState<PanarooSettings>(PANAROO_DEFAULTS);
  const [categories, setCategories] = useState<Thresholds>(DEFAULT_THRESHOLDS);
  const [curves, setCurves] = useState(CURVES);
  const [threads, setThreads] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (open) {
      setMethod("panaroo");
      setPanaroo(PANAROO_DEFAULTS);
      setCategories(DEFAULT_THRESHOLDS);
      setCurves(CURVES);
      setThreads(null);
      setConfirmed(false);
    }
  }, [open]);
  const body: PangenomeRequest = { method, genomes: null, panaroo, categories, curves, threads, confirmed };
  const plan = useQuery({
    queryKey: ["pangenomePlan", set.id, method, panaroo, categories, curves, threads],
    queryFn: () => api.pangenomePreview(set.id, body),
    enabled: open,
    retry: false,
  });
  const run = useMutation({
    mutationFn: () => api.runPangenome(set.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comparison", set.id] });
      onOpenChange(false);
    },
  });
  const p = plan.data;
  const change = <K extends keyof PanarooSettings>(key: K, value: PanarooSettings[K]) => {
    setPanaroo((s) => ({ ...s, [key]: value }));
    setConfirmed(false);
  };
  const setThreshold = (key: keyof Thresholds, v: number) => {
    setCategories((c) => ({ ...c, [key]: v / 100 }));
    setConfirmed(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("pangenome.title")} description={t("pangenome.description")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <div className="space-y-1.5 text-xs">
          {(["panaroo", "ppanggolin"] as PangenomeMethod[]).map((m) => (
            <label key={m} className="flex items-start gap-2">
              <input type="radio" className={CHECK} checked={method === m} onChange={() => { setMethod(m); setConfirmed(false); }} />
              <span>
                <span className="font-medium">{t(`pangenome.method.${m}` as TranslationKey)}</span>
                <span className="block text-muted-foreground">{t(`pangenome.methodHint.${m}` as TranslationKey)}</span>
              </span>
            </label>
          ))}
        </div>
        {method === "panaroo" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("pangenome.cleanMode")} hint={t(`pangenome.cleanModeHint.${panaroo.clean_mode}` as TranslationKey)}>
              <Select value={panaroo.clean_mode} onChange={(e) => change("clean_mode", e.target.value as PanarooSettings["clean_mode"])}>
                {CLEAN_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label={t("pangenome.alignment")} hint={t("pangenome.alignmentHint")}>
              <Select value={panaroo.alignment} onChange={(e) => change("alignment", e.target.value as PanarooSettings["alignment"])}>
                {ALIGNMENTS.map((a) => <option key={a} value={a}>{t(`pangenome.alignmentOption.${a}` as TranslationKey)}</option>)}
              </Select>
            </Field>
          </div>
        )}
        <details className="rounded-lg border p-3 text-xs">
          <summary className="cursor-pointer font-medium">{t("pangenome.advanced")}</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {method === "panaroo" && (
              <>
                <NumberField label={t("pangenome.identity")} hint="-c" value={panaroo.identity} step={0.01} onChange={(v) => change("identity", v)} />
                <NumberField label={t("pangenome.familyThreshold")} hint="-f" value={panaroo.family_threshold} step={0.05} onChange={(v) => change("family_threshold", v)} />
                <NumberField label={t("pangenome.lengthDifference")} hint="--len_dif_percent" value={panaroo.length_difference} step={0.01} onChange={(v) => change("length_difference", v)} />
                <NumberField label={t("pangenome.coreThreshold")} hint="--core_threshold" value={panaroo.core_threshold} step={0.01} onChange={(v) => change("core_threshold", v)} />
                <Field label={t("pangenome.refindMode")} hint="--refind-mode">
                  <Select value={panaroo.refind_mode} onChange={(e) => change("refind_mode", e.target.value as PanarooSettings["refind_mode"])}>
                    {(["default", "strict", "off"] as const).map((m) => <option key={m} value={m}>{m}</option>)}
                  </Select>
                </Field>
                <div className="space-y-1.5 pt-5">
                  <label className="flex items-start gap-2">
                    <input type="checkbox" className={CHECK} checked={panaroo.merge_paralogs} onChange={(e) => change("merge_paralogs", e.target.checked)} />
                    <span>{t("pangenome.mergeParalogs")}</span>
                  </label>
                  <label className="flex items-start gap-2">
                    <input type="checkbox" className={CHECK} checked={panaroo.remove_invalid_genes} onChange={(e) => change("remove_invalid_genes", e.target.checked)} />
                    <span>{t("pangenome.removeInvalid")}</span>
                  </label>
                </div>
              </>
            )}
            <NumberField label={t("pangenome.permutations")} value={curves.permutations} step={10} onChange={(v) => { setCurves((c) => ({ ...c, permutations: v })); setConfirmed(false); }} />
            <NumberField label={t("pangenome.seed")} value={curves.seed} step={1} onChange={(v) => { setCurves((c) => ({ ...c, seed: v })); setConfirmed(false); }} />
            <Field label={t("comparative.threads")} hint={p ? t("comparative.threadsHint", { max: p.tool.max_threads }) : undefined}>
              <Input type="number" min={1} max={p?.tool.max_threads ?? 256} value={threads ?? p?.settings.threads ?? ""}
                onChange={(e) => { setThreads(e.target.value ? Number(e.target.value) : null); setConfirmed(false); }} />
            </Field>
          </div>
        </details>
        <fieldset className="rounded-lg border p-3 text-xs">
          <legend className="px-1 font-medium">{t("pangenome.thresholds")}</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            {(["core", "soft_core", "shell"] as (keyof Thresholds)[]).map((k) => (
              <NumberField key={k} label={t(`pangenome.category.${k}` as TranslationKey)} hint="%" value={Math.round(categories[k] * 1000) / 10} step={1}
                onChange={(v) => setThreshold(k, v)} />
            ))}
          </div>
          <p className="mt-2 text-muted-foreground">{t("pangenome.thresholdsHint")}</p>
        </fieldset>
        <ErrorNote error={plan.error} />
        <PlanSummary plan={p as unknown as ComparisonPlan | undefined}>
          {p && (
            <ul className="space-y-0.5">
              {p.genomes.map((g) => (
                <li key={g.assembly_id}>
                  <span className="font-medium">{g.label}</span>:{" "}
                  {g.annotation ? t("pangenome.annotationLine", { tool: g.annotation.tool, version: g.annotation.tool_version, db: g.annotation.database_version ?? "—" })
                    : <span className="text-danger">{t("pangenome.notAnnotated")}</span>}
                </li>
              ))}
            </ul>
          )}
          {p && !p.annotation_consistency.consistent && (
            <p className="text-amber-700 dark:text-warning">{t("pangenome.mixedAnnotation")}</p>
          )}
        </PlanSummary>
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("pangenome.note")}</span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("comparative.confirm")}</span>
        </label>
        <ErrorNote error={run.error} />
        <Footer onCancel={() => onOpenChange(false)} onRun={() => run.mutate()} pending={run.isPending} label={t("pangenome.run")}
          disabled={!p || p.problems.length > 0 || !confirmed || plan.isFetching} />
      </div>
    </Dialog>
  );
}
