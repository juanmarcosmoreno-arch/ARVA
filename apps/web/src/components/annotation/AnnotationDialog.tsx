import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Info, Loader2, MinusCircle, Play, XCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import {
  type AnnotationForm,
  annotationProblems,
  assemblyOptions,
  baktaBody,
  initialForm,
  prokkaBody,
  stepLabel,
  stepReason,
  stepState,
} from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import type { AnnotationPlan, Assembly, TranslationTable } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Explains what Bakta or Prokka will do on this computer (every step, run or skipped and why) and its options, then
 * annotates the chosen assembly after an explicit confirmation. */
export function AnnotationDialog({
  open,
  onOpenChange,
  sampleId,
  assemblies,
  initialAssemblyId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  assemblies: Assembly[];
  initialAssemblyId?: string | null;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const [form, setForm] = useState<AnnotationForm>(() => initialForm(initialAssemblyId ?? options[0]?.assembly.id ?? ""));
  const [genus, setGenus] = useState("");
  useEffect(() => {
    if (!open) return;
    setForm(initialForm(initialAssemblyId ?? options[options.length - 1]?.assembly.id ?? ""));
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  useEffect(() => {
    const timer = setTimeout(() => setGenus(form.genus.trim()), 350);
    return () => clearTimeout(timer);
  }, [form.genus]);

  const set = <K extends keyof AnnotationForm>(key: K, value: AnnotationForm[K]) => setForm((f) => ({ ...f, [key]: value, confirmed: key === "confirmed" ? (value as boolean) : false }));
  const bakta = form.annotator === "bakta";
  const plan = useQuery({
    queryKey: ["annotationPlan", form.annotator, form.assemblyId, form.databaseId, form.skipPlot, form.rfam, form.useGenus, genus, form.rename],
    queryFn: () =>
      bakta
        ? api.baktaPreview(form.assemblyId, { database_id: form.databaseId || null, skip_plot: form.skipPlot })
        : api.prokkaPreview(form.assemblyId, { rfam: form.rfam, use_genus: form.useGenus, genus: genus || null, rename_contigs: form.rename }),
    enabled: open && Boolean(form.assemblyId),
    retry: false,
    // Choosing the database (or another option) re-checks the plan; keep showing the last one for the same annotator
    // and assembly meanwhile. Starting is disabled until the new plan has arrived.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === form.annotator && prevQuery?.queryKey[2] === form.assemblyId ? prev : undefined),
  });
  const p = plan.data;
  useEffect(() => {
    if (!p) return;
    setForm((f) => ({
      ...f,
      locusTag: f.locusTag || p.suggestions.locus_tag,
      databaseId: f.databaseId || p.database_id || "",
      rename: f.rename || Boolean(p.assembly.prokka_name_problem && p.annotator === "prokka"),
    }));
  }, [p]);

  const problems = annotationProblems(form, p);
  const run = useMutation({
    mutationFn: () => (bakta ? api.runBakta(form.assemblyId, baktaBody(form, p!)) : api.runProkka(form.assemblyId, prokkaBody(form))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["annotations", sampleId] });
      onOpenChange(false);
    },
  });
  const available = p?.tool.status === "available";
  const assembly = assemblies.find((a) => a.id === form.assemblyId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("annotation.title")} description={t("annotation.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <Section title={t("annotation.assembly")} hint={t("annotation.assemblyHint")}>
          <Select value={form.assemblyId} onChange={(e) => set("assemblyId", e.target.value)} aria-label={t("annotation.assembly")}>
            {options.map(({ assembly: a, depth }) => (
              <option key={a.id} value={a.id}>
                {"  ".repeat(depth)}
                {depth ? "↳ " : ""}
                {a.assembler} {a.assembler_version} · {a.kind === "polished" ? t("annotation.polished") : a.read_type} · {fmtInt(a.stats.contig_count)} contigs ·{" "}
                {fmtBases(a.stats.total_length)} · {fmtDate(a.created_at)} · {a.id.slice(0, 8)}
              </option>
            ))}
          </Select>
          {assembly && p?.assembly.assembly_id === assembly.id && (
            <p className="text-xs text-muted-foreground">
              {t("annotation.assemblyFacts", {
                contigs: fmtInt(p.assembly.contigs),
                circular: p.assembly.circular_contigs == null ? "?" : fmtInt(p.assembly.circular_contigs),
                reported: p.assembly.contigs_with_circularity == null ? "?" : fmtInt(p.assembly.contigs_with_circularity),
              })}
              {p.assembly.descriptions > 0 && ` ${t("annotation.descriptionsRemoved", { n: fmtInt(p.assembly.descriptions) })}`}
            </p>
          )}
          {p && p.assembly.synthetic_evidence.length > 0 && <SyntheticNote evidence={p.assembly.synthetic_evidence} />}
        </Section>

        <Section title={t("annotation.annotator")} action={<Explain id="annotation" compact />}>
          <div className="grid gap-2 sm:grid-cols-2">
            <AnnotatorChoice id="bakta" checked={bakta} onChange={() => set("annotator", "bakta")} />
            <AnnotatorChoice id="prokka" checked={!bakta} onChange={() => set("annotator", "prokka")} />
          </div>
        </Section>

        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("annotation.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && <ToolLine plan={p} />}
        {p && <DatabaseSection plan={p} value={form.databaseId} onChange={(v) => set("databaseId", v)} />}
        {p && Object.keys(p.steps).length > 0 && <StepsSection plan={p} />}

        <Section title={t("annotation.options")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("annotation.locusTag")} hint={t("annotation.locusTagHint")}>
              <Input value={form.locusTag} onChange={(e) => set("locusTag", e.target.value.toUpperCase())} maxLength={12} />
            </Field>
            <Field label={t("annotation.translationTable")} hint={t("annotation.translationTableHint")}>
              <Select value={String(form.translationTable)} onChange={(e) => set("translationTable", Number(e.target.value) as TranslationTable)}>
                {(p?.translation_tables ?? [11, 4, 25]).map((n) => (
                  <option key={n} value={n}>
                    {t(`annotation.table.${n}` as "annotation.table.11")}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("annotation.genus")} hint={t("annotation.organismHint")}>
              <Input value={form.genus} onChange={(e) => set("genus", e.target.value)} maxLength={50} />
            </Field>
            <Field label={t("annotation.species")}>
              <Input value={form.species} onChange={(e) => set("species", e.target.value)} maxLength={50} />
            </Field>
            <Field label={t("annotation.strain")}>
              <Input value={form.strain} onChange={(e) => set("strain", e.target.value)} maxLength={40} />
            </Field>
            <Field label={t("annotation.minContig")} hint={t("annotation.minContigHint")}>
              <Input type="number" min={1} value={form.minContig} onChange={(e) => set("minContig", e.target.value)} />
            </Field>
            <Field label={t("annotation.threads")} hint={t("annotation.threadsHint", { max: p?.tool.max_threads ?? "?" })}>
              <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.max_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
            </Field>
          </div>
          {bakta ? <BaktaOptions form={form} set={set} plan={p} /> : <ProkkaOptions form={form} set={set} plan={p} />}
        </Section>

        {p && (
          <p className="flex gap-1.5 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{summaryText(t, form, p)}</span>
          </p>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={form.confirmed} onChange={(e) => set("confirmed", e.target.checked)} />
          <span>{t("annotation.confirm")}</span>
        </label>
        {problems.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{t(k, { max: p?.tool.max_threads ?? "?" })}</li>
            ))}
            {p?.problems.map((x) => (
              <li key={x.code} className="text-amber-700 dark:text-warning">
                {problemText(t, x)}
              </li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!available || !p || problems.length > 0 || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("annotation.starting") : t("annotation.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

type T = ReturnType<typeof useT>;

function problemText(t: T, x: { code: string; message: string }) {
  const known = ["no_database", "tool_unavailable", "nothing_to_annotate", "contig_names", "programs_missing"];
  return known.includes(x.code) ? `${t(`annotation.planProblem.${x.code}` as "annotation.planProblem.no_database")} (${x.message})` : x.message;
}

function summaryText(t: T, form: AnnotationForm, p: AnnotationPlan) {
  const run = Object.entries(p.steps).filter(([, s]) => s.run).map(([k]) => stepLabel(t, p.annotator, k));
  const skipped = Object.entries(p.steps).filter(([, s]) => !s.run).map(([k]) => stepLabel(t, p.annotator, k));
  return t(form.annotator === "bakta" ? "annotation.summary.bakta" : "annotation.summary.prokka", {
    version: p.tool.version ?? "?",
    database: form.annotator === "bakta" ? p.databases.find((d) => d.id === p.database_id)?.name ?? "—" : p.database?.name ?? "—",
    steps: run.join(", ") || "—",
    skipped: skipped.join(", ") || "—",
    tag: form.locusTag || "?",
    table: form.translationTable,
  });
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

export function SyntheticNote({ evidence }: { evidence: string[] }) {
  const t = useT();
  return (
    <p role="note" className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
      {t("annotation.synthetic", { where: evidence.join(", ") })}
    </p>
  );
}

function AnnotatorChoice({ id, checked, onChange }: { id: "bakta" | "prokka"; checked: boolean; onChange: () => void }) {
  const t = useT();
  const tool = useTool(id);
  return (
    <label className={cn("flex cursor-pointer items-start gap-2 rounded-lg border p-3", checked && "border-arva-teal bg-arva-teal/5")}>
      <input type="radio" name="annotator" className={CHECK} checked={checked} onChange={onChange} />
      <span className="space-y-0.5">
        <span className="flex items-center gap-2 font-medium">
          {id === "bakta" ? "Bakta" : "Prokka"}
          {tool?.version && <span className="text-xs font-normal text-muted-foreground">v{tool.version}</span>}
          <Explain id={id} compact />
        </span>
        <span className="block text-xs text-muted-foreground">{t(`annotation.choice.${id}` as "annotation.choice.bakta")}</span>
        {tool && tool.status !== "available" && <span className="block text-xs text-amber-700 dark:text-warning">{tool.status === "not_installed" ? t("annotation.notInstalled") : toolMessage(t, tool)}</span>}
      </span>
    </label>
  );
}

function ToolLine({ plan }: { plan: AnnotationPlan }) {
  const t = useT();
  const tool = plan.tool;
  if (tool.status !== "available") return <ErrorNote error={t("annotation.unavailable", { message: tool.message || tool.status })} />;
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>
        {t("annotation.toolLine", { tool: plan.annotator === "bakta" ? "Bakta" : "Prokka", version: tool.version ?? "?", licence: tool.license })}{" "}
        <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
          {t("annotation.cite")}
        </a>
      </div>
      {!tool.version_validated && tool.message && (
        <p className="flex gap-1.5 text-amber-700 dark:text-warning">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {tool.message}
        </p>
      )}
    </div>
  );
}

function DatabaseSection({ plan, value, onChange }: { plan: AnnotationPlan; value: string; onChange: (v: string) => void }) {
  const t = useT();
  if (plan.annotator === "prokka") {
    const db = plan.database;
    return (
      <Section title={t("annotation.database")} hint={t("annotation.prokkaDbHint")}>
        {db?.ready ? (
          <p className="text-xs">
            {t("annotation.prokkaDb", { name: db.name ?? "?", version: db.version ?? "?", files: fmtInt(db.files.length), path: db.path })}{" "}
            <code className="break-all text-[11px] text-muted-foreground">{db.checksum}</code>
          </p>
        ) : (
          <ErrorNote error={t("annotation.prokkaDbMissing", { path: db?.path ?? "?" })} />
        )}
      </Section>
    );
  }
  const usable = plan.databases.filter((d) => d.usable);
  return (
    <Section title={t("annotation.database")} hint={t("annotation.baktaDbHint")} action={<Link to="/tools" className="text-xs text-arva-royal hover:underline dark:text-arva-cyan">{t("annotation.databaseManager")}</Link>}>
      {usable.length ? (
        <>
          <Select value={value || plan.database_id || ""} onChange={(e) => onChange(e.target.value)} aria-label={t("annotation.database")}>
            {usable.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} {d.version ?? ""} ({d.type ?? "?"}) · {d.verified_at ? t("annotation.verified", { date: fmtDate(d.verified_at) }) : t("annotation.notVerified")}
              </option>
            ))}
          </Select>
          {plan.databases.find((d) => d.id === plan.database_id)?.type === "light" && <p className="text-xs text-muted-foreground">{t("annotation.lightDb")}</p>}
        </>
      ) : (
        <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            {t("annotation.noDatabase")}{" "}
            <Link to="/tools" className="text-arva-royal underline dark:text-arva-cyan">
              {t("annotation.databaseManager")}
            </Link>
          </span>
        </p>
      )}
    </Section>
  );
}

export function StepIcon({ state }: { state: string }) {
  if (state === "searched" || state === "planned") return <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />;
  if (state === "failed") return <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />;
  return <MinusCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />;
}

function StepsSection({ plan }: { plan: AnnotationPlan }) {
  const t = useT();
  return (
    <Section title={t("annotation.steps")} hint={t("annotation.stepsHint")}>
      <ul className="grid gap-1 sm:grid-cols-2">
        {Object.entries(plan.steps).map(([step, s]) => (
          <li key={step} className="flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs">
            <StepIcon state={stepState(s)} />
            <span>
              <span className="font-medium">{stepLabel(t, plan.annotator, step)}</span>
              {!s.run && <span className="block text-muted-foreground">{t("annotation.notSearched", { reason: stepReason(t, s) })}</span>}
            </span>
          </li>
        ))}
      </ul>
      {plan.dependencies.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">{t("annotation.dependencies")}</summary>
          <table className="mt-1 w-full">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1 pr-2 font-medium">{t("annotation.dep.program")}</th>
                <th className="py-1 pr-2 font-medium">{t("annotation.dep.found")}</th>
                <th className="py-1 pr-2 font-medium">{t("annotation.dep.required")}</th>
                <th className="py-1 font-medium">{t("annotation.dep.status")}</th>
              </tr>
            </thead>
            <tbody>
              {plan.dependencies.map((d) => (
                <tr key={d.name} className="border-t">
                  <td className="py-1 pr-2">{d.name}</td>
                  <td className="py-1 pr-2 tabular-nums">{d.found ?? "—"}</td>
                  <td className="py-1 pr-2 tabular-nums">≥ {d.minimum}</td>
                  <td className="py-1">{d.status === "ok" ? t("annotation.dep.ok") : t(`annotation.dependency.${d.status}` as "annotation.dependency.missing", { name: "", found: d.found ?? "?", minimum: d.minimum ?? "?", code: d.returncode ?? "?" }).trim()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </Section>
  );
}

type Setter = <K extends keyof AnnotationForm>(key: K, value: AnnotationForm[K]) => void;

function BaktaOptions({ form, set, plan }: { form: AnnotationForm; set: Setter; plan: AnnotationPlan | undefined }) {
  const t = useT();
  const suggest = plan?.suggestions.complete;
  return (
    <div className="space-y-2 text-xs">
      <label className="flex items-start gap-2">
        <input type="checkbox" className={CHECK} checked={form.complete} onChange={(e) => set("complete", e.target.checked)} />
        <span>
          <span className="font-medium">{t("annotation.complete")}</span> <span className="text-muted-foreground">--complete</span>
          <span className="block text-muted-foreground">{t("annotation.completeHint")}</span>
          {suggest !== undefined && <span className="block text-muted-foreground">{t(suggest ? "annotation.completeSuggested" : "annotation.completeNotSuggested")}</span>}
        </span>
      </label>
      {form.complete && (
        <label className="ml-6 flex items-start gap-2 text-amber-700 dark:text-warning">
          <input type="checkbox" className={CHECK} checked={form.completeConfirmed} onChange={(e) => set("completeConfirmed", e.target.checked)} />
          <span>{t("annotation.completeConfirm")}</span>
        </label>
      )}
      <label className="flex items-start gap-2">
        <input type="checkbox" className={CHECK} checked={form.keepHeaders} onChange={(e) => set("keepHeaders", e.target.checked)} />
        <span>
          <span className="font-medium">{t("annotation.keepHeaders")}</span> <span className="text-muted-foreground">--keep-contig-headers</span>
          <span className="block text-muted-foreground">{t("annotation.keepHeadersHint")}</span>
        </span>
      </label>
      <label className="flex items-start gap-2">
        <input type="checkbox" className={CHECK} checked={form.skipPlot} onChange={(e) => set("skipPlot", e.target.checked)} />
        <span>
          <span className="font-medium">{t("annotation.skipPlot")}</span> <span className="text-muted-foreground">--skip-plot</span>
          <span className="block text-muted-foreground">{t("annotation.skipPlotHint")}</span>
        </span>
      </label>
      <p className="text-muted-foreground">{t("annotation.baktaFixed")}</p>
    </div>
  );
}

function ProkkaOptions({ form, set, plan }: { form: AnnotationForm; set: Setter; plan: AnnotationPlan | undefined }) {
  const t = useT();
  const genera = plan?.database?.genera ?? [];
  const nameProblem = plan?.assembly.prokka_name_problem;
  return (
    <div className="space-y-2 text-xs">
      <p className="text-muted-foreground">{t("annotation.prokkaMaintenance")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("annotation.evalue")} hint={t("annotation.evalueHint")}>
          <Input value={form.evalue} onChange={(e) => set("evalue", e.target.value)} />
        </Field>
        <Field label={t("annotation.coverage")} hint={t("annotation.coverageHint")}>
          <Input type="number" min={1} max={100} value={form.coverage} onChange={(e) => set("coverage", e.target.value)} />
        </Field>
      </div>
      <label className="flex items-start gap-2">
        <input type="checkbox" className={CHECK} checked={form.rfam} onChange={(e) => set("rfam", e.target.checked)} />
        <span>
          <span className="font-medium">{t("annotation.rfam")}</span> <span className="text-muted-foreground">--rfam</span>
          <span className="block text-muted-foreground">{t("annotation.rfamHint")}</span>
        </span>
      </label>
      <label className="flex items-start gap-2">
        <input type="checkbox" className={CHECK} checked={form.useGenus} onChange={(e) => set("useGenus", e.target.checked)} />
        <span>
          <span className="font-medium">{t("annotation.useGenus")}</span> <span className="text-muted-foreground">--usegenus</span>
          <span className="block text-muted-foreground">{t("annotation.useGenusHint", { genera: genera.join(", ") || "—" })}</span>
        </span>
      </label>
      <label className="flex items-start gap-2">
        <input type="checkbox" className={CHECK} checked={form.rename} onChange={(e) => set("rename", e.target.checked)} />
        <span>
          <span className="font-medium">{t("annotation.rename")}</span>
          <span className="block text-muted-foreground">{nameProblem ? t("annotation.renameNeeded", { problem: nameProblem }) : t("annotation.renameHint")}</span>
        </span>
      </label>
      <p className="text-muted-foreground">{t("annotation.prokkaFixed")}</p>
    </div>
  );
}
