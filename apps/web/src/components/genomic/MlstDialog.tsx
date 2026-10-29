import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { assemblyOptions } from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import { initialMlstForm, MLST_DEFAULT_EXCLUDE, mlstBody, type MlstForm, mlstProblems } from "@/lib/mlst";
import type { Assembly, MlstPlan } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Shows what mlst will do on this computer — its bundled schemes (date, terms), the scheme choice and mlst's
 * defaults — then types the chosen assembly after an explicit confirmation. */
export function MlstDialog({
  open,
  onOpenChange,
  sampleId,
  assemblies,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  assemblies: Assembly[];
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const [form, setForm] = useState<MlstForm>(() => initialMlstForm(options[options.length - 1]?.assembly.id ?? ""));
  useEffect(() => {
    if (open) setForm(initialMlstForm(options[options.length - 1]?.assembly.id ?? ""));
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const set = <K extends keyof MlstForm>(key: K, value: MlstForm[K]) =>
    setForm((f) => ({ ...f, [key]: value, confirmed: key === "confirmed" ? (value as boolean) : false }));

  const plan = useQuery({
    queryKey: ["mlstPlan", form.assemblyId, form.scheme],
    queryFn: () => api.mlstPreview(form.assemblyId, form.scheme || null),
    enabled: open && Boolean(form.assemblyId),
    retry: false,
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === form.assemblyId ? prev : undefined),
  });
  const p = plan.data;
  const problems = mlstProblems(form, p);
  const run = useMutation({
    mutationFn: () => api.runMlst(form.assemblyId, mlstBody(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["mlst", sampleId] });
      onOpenChange(false);
    },
  });
  const available = p?.tool.status === "available";

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("mlst.title")} description={t("mlst.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <Section title={t("mlst.assembly")} hint={t("mlst.assemblyHint")}>
          <Select value={form.assemblyId} onChange={(e) => set("assemblyId", e.target.value)} aria-label={t("mlst.assembly")}>
            {options.map(({ assembly: a, depth }) => (
              <option key={a.id} value={a.id}>
                {"  ".repeat(depth)}
                {depth ? "↳ " : ""}
                {a.assembler} {a.assembler_version} · {a.kind === "polished" ? t("annotation.polished") : a.read_type} · {fmtInt(a.stats.contig_count)} contigs ·{" "}
                {fmtBases(a.stats.total_length)} · {fmtDate(a.created_at)} · {a.id.slice(0, 8)}
              </option>
            ))}
          </Select>
          {p && p.assembly.synthetic_evidence.length > 0 && <SyntheticNote evidence={p.assembly.synthetic_evidence} />}
        </Section>

        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("mlst.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && <ToolLine plan={p} />}
        {p?.database && <DatabaseNote plan={p} />}

        <Section title={t("mlst.schemeChoice")} hint={t("mlst.schemeChoiceHint")} action={<Explain id="mlst" compact />}>
          <Select value={form.scheme} onChange={(e) => set("scheme", e.target.value)} aria-label={t("mlst.schemeChoice")}>
            <option value="">{t("mlst.autoDetect")}</option>
            {(p?.schemes ?? []).map((s) => (
              <option key={s.name} value={s.name}>
                {t("mlst.schemeOption", { name: s.name, loci: s.loci.length, date: s.last_updated ?? "?" })}
              </option>
            ))}
          </Select>
          {form.scheme && <p className="text-xs text-muted-foreground">{t("mlst.forcedNote")}</p>}
        </Section>

        <Section title={t("mlst.options")} hint={t("mlst.optionsHint")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("mlst.minid")} hint={t("mlst.minidHint", { default: p?.tool_defaults.minid ?? "95" })}>
              <Input type="number" min={1} max={100} step="any" value={form.minid} onChange={(e) => set("minid", e.target.value)} />
            </Field>
            <Field label={t("mlst.mincov")} hint={t("mlst.mincovHint", { default: p?.tool_defaults.mincov ?? "50" })}>
              <Input type="number" min={1} max={100} step="any" value={form.mincov} onChange={(e) => set("mincov", e.target.value)} />
            </Field>
            <Field label={t("mlst.minscore")} hint={form.scheme ? t("mlst.minscoreForced") : t("mlst.minscoreHint", { default: p?.tool_defaults.minscore ?? "50" })}>
              <Input type="number" min={0} max={100} step="any" value={form.scheme ? "0" : form.minscore} disabled={Boolean(form.scheme)} onChange={(e) => set("minscore", e.target.value)} />
            </Field>
            <Field label={t("annotation.threads")} hint={t("annotation.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
              <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
            </Field>
          </div>
          {!form.scheme && (
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className={CHECK} checked={form.excludeDefaults} onChange={(e) => set("excludeDefaults", e.target.checked)} />
              <span>{t("mlst.excludeDefaults", { schemes: MLST_DEFAULT_EXCLUDE.join(", ") })}</span>
            </label>
          )}
          {p && p.defaults_match === false && (
            <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
              <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("mlst.defaultsDiffer")}
            </p>
          )}
        </Section>

        {p && (
          <p className="flex gap-1.5 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              {t(form.scheme ? "mlst.summaryForced" : "mlst.summaryAuto", {
                scheme: form.scheme,
                minid: form.minid,
                mincov: form.mincov,
                minscore: form.scheme ? "0" : form.minscore,
                exclude: !form.scheme && form.excludeDefaults ? MLST_DEFAULT_EXCLUDE.join(", ") : t("mlst.excludeNone"),
                date: p.database?.version ?? "?",
              })}
            </span>
          </p>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={form.confirmed} onChange={(e) => set("confirmed", e.target.checked)} />
          <span>{t("mlst.confirm")}</span>
        </label>
        {(problems.length > 0 || (p?.problems.length ?? 0) > 0) && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{t(k, { max: p?.tool.max_threads ?? "?" })}</li>
            ))}
            {p?.problems.map((x) => (
              <li key={x.code} className="text-amber-700 dark:text-warning">
                {planProblem(t, x)}
              </li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!available || !p || problems.length > 0 || p.problems.length > 0 || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("mlst.starting") : t("mlst.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

type T = ReturnType<typeof useT>;

function planProblem(t: T, x: MlstPlan["problems"][number]) {
  const known = ["no_database", "help_unreadable", "tool_unavailable", "unknown_scheme"];
  return known.includes(x.code) ? t(`mlst.planProblem.${x.code}` as TranslationKey, x.params) : x.message;
}

function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold">{title}</h4>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function ToolLine({ plan }: { plan: MlstPlan }) {
  const t = useT();
  const tool = plan.tool;
  if (tool.status !== "available") return <ErrorNote error={t("mlst.unavailable", { message: toolMessage(t, { ...tool, min_version: "" }) || tool.status })} />;
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>
        {t("mlst.toolLine", { version: tool.version ?? "?", licence: tool.license })}{" "}
        <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
          {t("annotation.cite")}
        </a>
      </div>
      {!tool.version_validated && tool.message && (
        <p className="flex gap-1.5 text-amber-700 dark:text-warning">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {toolMessage(t, { ...tool, min_version: "" })}
        </p>
      )}
    </div>
  );
}

export function DatabaseNote({ plan }: { plan: Pick<MlstPlan, "database"> }) {
  const t = useT();
  const d = plan.database!;
  return (
    <div className="space-y-1.5 rounded-lg border p-3 text-xs">
      <p className="font-medium">{d.name}</p>
      <p className="text-muted-foreground">
        {t("mlst.dbLine", { schemes: d.scheme_count ?? "?", date: d.version ?? "?", file: d.version_txt ?? "?", index: d.blast_last_updated ?? "?" })}
      </p>
      <p className="flex gap-1.5 text-amber-700 dark:text-warning">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          {t("mlst.terms", { date: d.terms.open_until, count: d.updated_after_open_terms.length, total: d.scheme_count ?? "?" })}{" "}
          <a href={d.terms.url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
            {t("mlst.termsLink")}
          </a>
        </span>
      </p>
      <p className="text-muted-foreground">{t("mlst.noUpdater")}</p>
    </div>
  );
}
