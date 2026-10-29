import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { compatibilityText } from "@/components/databases/shared";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { amrBody, type AmrForm, amrProblems, initialAmrForm } from "@/lib/amr";
import { assemblyOptions } from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import type { AmrPlan, Assembly } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Shows what AMRFinderPlus will do here — the database (and why a copy inside a Bakta database cannot be used), the
 * search mode, the organism proposed from the species identification, AMRFinderPlus's defaults — and searches the
 * chosen assembly after an explicit confirmation. */
export function AmrDialog({ open, onOpenChange, sampleId, assemblies }: { open: boolean; onOpenChange: (o: boolean) => void; sampleId: string; assemblies: Assembly[] }) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const [form, setForm] = useState<AmrForm>(() => initialAmrForm(options[options.length - 1]?.assembly.id ?? ""));
  useEffect(() => {
    if (open) setForm(initialAmrForm(options[options.length - 1]?.assembly.id ?? ""));
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const set = <K extends keyof AmrForm>(key: K, value: AmrForm[K]) =>
    setForm((f) => ({ ...f, [key]: value, ...(key === "organism" ? { organismTouched: true } : {}), confirmed: key === "confirmed" ? (value as boolean) : false }));

  const plan = useQuery({
    queryKey: ["amrPlan", form.assemblyId, form.databaseId],
    queryFn: () => api.amrPreview(form.assemblyId, form.databaseId || null, null),
    enabled: open && Boolean(form.assemblyId),
    retry: false,
  });
  const p = plan.data;
  useEffect(() => {
    if (p && !form.organismTouched) setForm((f) => ({ ...f, organism: p.organism.organism ?? "" }));
  }, [p, form.organismTouched]);
  const problems = amrProblems(form, p);
  const run = useMutation({
    mutationFn: () => api.runAmr(form.assemblyId, amrBody(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["amr", sampleId] });
      onOpenChange(false);
    },
  });
  const usableAnnotations = (p?.annotations ?? []).filter((a) => a.usable);
  const proposed = p?.organism.organism ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("amr.title")} description={t("amr.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <Section title={t("mlst.assembly")} hint={t("amr.assemblyHint")}>
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

        <Section title={t("amr.database")} hint={t("amr.databaseHint")} action={<Explain id="amr" compact />}>
          {p && p.databases.length > 0 ? (
            <Select value={form.databaseId || p.database?.id || ""} onChange={(e) => set("databaseId", e.target.value)} aria-label={t("amr.database")}>
              {p.databases.map((d) => (
                <option key={d.id} value={d.id} disabled={d.compatibility.status === "incompatible" || !d.available}>
                  {d.name} {d.version ?? ""}
                  {d.is_default ? ` · ${t("databases.badge.default")}` : ""}
                  {d.compatibility.status === "incompatible" ? ` · ${t("amr.incompatible")}` : ""}
                </option>
              ))}
            </Select>
          ) : (
            p && (
              <p className="text-xs text-amber-700 dark:text-warning">
                {t("amr.noDatabase")}{" "}
                <Link to="/tools#reference-databases" className="text-arva-royal hover:underline dark:text-arva-cyan">
                  {t("amr.openDatabases")}
                </Link>
              </p>
            )
          )}
          {p?.database && (
            <p className="text-xs text-muted-foreground">
              {t("amr.dbLine", { version: p.database.version ?? "?", format: p.database.database_format ?? "?", path: p.database.host_path })}
            </p>
          )}
          {p?.bakta_copies.map((c) => (
            <p key={c.path} className={c.record_id ? "text-xs text-muted-foreground" : "flex gap-1.5 text-xs text-amber-700 dark:text-warning"}>
              {!c.record_id && <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />}
              <span>
                {t("amr.baktaCopy", { name: c.bakta_name, version: c.version })} {compatibilityText(t, c.compatibility)}
                {!c.complete && ` ${t("amr.baktaCopyIncomplete")}`}
              </span>
            </p>
          ))}
          <p className="text-xs text-muted-foreground">{t("amr.noUpdater")}</p>
        </Section>

        <Section title={t("amr.mode")} hint={t("amr.modeHint")}>
          <div className="space-y-1.5 text-xs">
            <label className="flex items-start gap-2">
              <input type="radio" className={CHECK} checked={form.mode === "nucleotide"} onChange={() => set("mode", "nucleotide")} />
              <span>{t("amr.mode.nucleotide")}</span>
            </label>
            <label className="flex items-start gap-2">
              <input type="radio" className={CHECK} checked={form.mode === "combined"} disabled={!usableAnnotations.length} onChange={() => set("mode", "combined")} />
              <span>{usableAnnotations.length ? t("amr.mode.combined") : t("amr.mode.combinedNone")}</span>
            </label>
          </div>
          {form.mode === "combined" && (
            <Select value={form.annotationId} onChange={(e) => set("annotationId", e.target.value)} aria-label={t("amr.annotation")}>
              <option value="">{t("amr.chooseAnnotation")}</option>
              {usableAnnotations.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.tool} {a.tool_version} · {t("amr.annotationCds", { n: fmtInt(a.cds ?? 0) })} · {fmtDate(a.created_at)} · {a.id.slice(0, 8)}
                </option>
              ))}
            </Select>
          )}
        </Section>

        <Section title={t("amr.organism")} hint={t("amr.organismHint")} action={<Explain id="point_mutation" compact />}>
          <Select value={form.organism} onChange={(e) => set("organism", e.target.value)} aria-label={t("amr.organism")}>
            <option value="">{t("amr.organismNone")}</option>
            {(p?.organisms ?? []).map((o) => (
              <option key={o} value={o}>
                {o.replace(/_/g, " ")}
              </option>
            ))}
          </Select>
          {p && <OrganismNote plan={p} chosen={form.organism} />}
          {!form.organism && <p className="text-xs text-amber-700 dark:text-warning">{t("amr.noOrganismNote")}</p>}
          {form.organism && proposed && form.organism !== proposed && <p className="text-xs text-muted-foreground">{t("amr.organismChanged", { proposed: proposed.replace(/_/g, " ") })}</p>}
        </Section>

        <Section title={t("mlst.options")} hint={t("amr.optionsHint")}>
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className={CHECK} checked={form.plus} onChange={(e) => set("plus", e.target.checked)} />
            <span>{t("amr.plus")}</span>
          </label>
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className={CHECK} checked={form.curated} onChange={(e) => set("curated", e.target.checked)} />
            <span>{t("amr.curated", { default: p?.tool_defaults.ident_min ?? "-1" })}</span>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            {!form.curated && (
              <Field label={t("amr.identMin")} hint={t("amr.identMinHint")}>
                <Input type="number" min={0.01} max={1} step="any" value={form.identMin} onChange={(e) => set("identMin", e.target.value)} />
              </Field>
            )}
            <Field label={t("amr.coverageMin")} hint={t("amr.coverageMinHint", { default: p?.tool_defaults.coverage_min ?? "0.5" })}>
              <Input type="number" min={0.01} max={1} step="any" value={form.coverageMin} onChange={(e) => set("coverageMin", e.target.value)} />
            </Field>
            <Field label={t("amr.translationTable")} hint={t("amr.translationTableHint", { default: p?.tool_defaults.translation_table ?? "11" })}>
              <Input type="number" min={1} max={33} value={form.translationTable} onChange={(e) => set("translationTable", e.target.value)} />
            </Field>
            <Field label={t("annotation.threads")} hint={t("annotation.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
              <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
            </Field>
          </div>
          {p && p.defaults_match === false && (
            <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
              <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("mlst.defaultsDiffer")}
            </p>
          )}
        </Section>

        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>
            {t("amr.disclaimer")} <Explain id="genotype_phenotype" compact />
          </span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={form.confirmed} onChange={(e) => set("confirmed", e.target.checked)} />
          <span>{t("amr.confirm")}</span>
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
          <Button onClick={() => run.mutate()} disabled={!p || p.tool.status !== "available" || problems.length > 0 || p.problems.length > 0 || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("mlst.starting") : t("amr.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

type T = ReturnType<typeof useT>;

const PLAN_PROBLEMS = ["tool_unavailable", "help_unreadable", "no_database", "database_unavailable", "database_incompatible", "database_refused", "organisms_unreadable", "annotation_unusable"];

function planProblem(t: T, x: AmrPlan["problems"][number]) {
  return PLAN_PROBLEMS.includes(x.code) ? t(`amr.planProblem.${x.code}` as TranslationKey, x.params) : x.message;
}

function OrganismNote({ plan, chosen }: { plan: AmrPlan; chosen: string }) {
  const t = useT();
  const o = plan.organism;
  const species = o.species?.species ?? "";
  if (o.organism)
    return (
      <p className="text-xs text-muted-foreground">
        {t(`amr.organismRule.${o.rule}` as TranslationKey, { species, organism: o.organism.replace(/_/g, " "), method: o.species?.tool ?? "?" })}
        {o.complex_note ? ` ${t("amr.complexNote", { complex: o.complex_note })}` : ""}
      </p>
    );
  if (o.rule === "no_species") return <p className="text-xs text-muted-foreground">{t("amr.organismRule.no_species")}</p>;
  return (
    <p className="text-xs text-muted-foreground">
      {t("amr.organismRule.not_curated", { species })}
      {o.complex_note && !chosen ? ` ${t("amr.complexOption", { complex: o.complex_note, option: (o.complex_option ?? "").replace(/_/g, " ") })}` : ""}
    </p>
  );
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

function ToolLine({ plan }: { plan: AmrPlan }) {
  const t = useT();
  const tool = plan.tool;
  if (tool.status !== "available") return <ErrorNote error={t("amr.unavailable", { message: toolMessage(t, { ...tool, min_version: "" }) || tool.status })} />;
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>
        {t("amr.toolLine", { version: tool.version ?? "?", licence: tool.license })}{" "}
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
