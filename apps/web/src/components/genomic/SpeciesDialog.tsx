import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { assemblyOptions } from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtBases, fmtBytes, fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import { initialSpeciesForm, SPECIES_METHODS, speciesBody, type SpeciesForm, speciesProblems } from "@/lib/species";
import type { Assembly, SpeciesDatabase, SpeciesMethod, SpeciesPlan } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";
const VALIDATION_TONE = { validated: "success", test_database: "warning", not_validated: "danger" } as const;

/** Shows what a species identification will do on this computer — the method (each explained), the database it
 * searches and what that database holds, the MLST call and annotation organism it will be checked against — then
 * starts it after an explicit confirmation. */
export function SpeciesDialog({ open, onOpenChange, sampleId, assemblies }: { open: boolean; onOpenChange: (o: boolean) => void; sampleId: string; assemblies: Assembly[] }) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const [form, setForm] = useState<SpeciesForm>(() => initialSpeciesForm(options[options.length - 1]?.assembly.id ?? ""));
  useEffect(() => {
    if (open) setForm(initialSpeciesForm(options[options.length - 1]?.assembly.id ?? ""));
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const set = <K extends keyof SpeciesForm>(key: K, value: SpeciesForm[K]) =>
    setForm((f) => ({ ...f, [key]: value, ...(key === "method" ? { databaseId: "" } : {}), confirmed: key === "confirmed" ? (value as boolean) : false }));

  const plan = useQuery({
    queryKey: ["speciesPlan", form.assemblyId, form.method, form.databaseId],
    queryFn: () => api.speciesPreview(form.assemblyId, form.method, form.databaseId || null),
    enabled: open && Boolean(form.assemblyId),
    retry: false,
  });
  const p = plan.data;
  const problems = speciesProblems(form, p);
  const run = useMutation({
    mutationFn: () => api.runSpecies(form.assemblyId, speciesBody(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["species", sampleId] });
      onOpenChange(false);
    },
  });
  const blocked = !p || problems.length > 0 || p.problems.length > 0 || plan.isFetching || run.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("species.title")} description={t("species.description")} className="max-w-4xl">
      <div className="space-y-5 text-sm">
        <Section title={t("species.assembly")} hint={t("species.assemblyHint")}>
          <Select value={form.assemblyId} onChange={(e) => set("assemblyId", e.target.value)} aria-label={t("species.assembly")}>
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

        <Section title={t("species.method")} hint={t("species.methodHint")} action={<Explain id="ani" compact />}>
          <div className="grid gap-2 lg:grid-cols-2" role="radiogroup" aria-label={t("species.method")}>
            {SPECIES_METHODS.map((m) => (
              <MethodOption key={m} method={m} plan={p} selected={form.method === m} onSelect={() => set("method", m)} />
            ))}
          </div>
        </Section>

        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("species.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && <ToolLine plan={p} />}

        {p && (
          <Section title={t("species.database")} hint={t(`species.databaseHint.${p.database_kind}` as TranslationKey)} action={<Explain id="reference_collection" compact />}>
            {p.databases.length > 0 ? (
              <Select value={form.databaseId || p.database?.id || ""} onChange={(e) => set("databaseId", e.target.value)} aria-label={t("species.database")}>
                {p.databases.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.version ?? "?"}
                    {d.is_default ? ` · ${t("species.default")}` : ""}
                  </option>
                ))}
              </Select>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t("species.noDatabase")}{" "}
                <Link to="/tools#reference-databases" className="text-arva-royal hover:underline dark:text-arva-cyan">
                  {t("species.toDatabases")}
                </Link>
              </p>
            )}
            {p.database && <DatabaseFacts database={p.database} />}
          </Section>
        )}

        {p && form.method === "gtdbtk" && p.gtdbtk_memory_gb && (
          <p role="status" className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
            {t("species.gtdbtkMemory", { bacteria: p.gtdbtk_memory_gb.bacteria, archaea: p.gtdbtk_memory_gb.archaea, available: p.tool.memory_gb })}
          </p>
        )}

        {p && <ContextNote plan={p} />}

        <Section title={t("species.resources")}>
          <Field label={t("annotation.threads")} hint={t("annotation.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
            <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} className="max-w-[10rem]" />
          </Field>
        </Section>

        {p?.database && (
          <p className="flex gap-1.5 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{t("species.summary", { tool: p.tool.name, version: p.tool.version ?? "?", database: p.database.name, dbVersion: p.database.version ?? "?" })}</span>
          </p>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={form.confirmed} onChange={(e) => set("confirmed", e.target.checked)} />
          <span>{t("species.confirm")}</span>
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
          <Button onClick={() => run.mutate()} disabled={blocked}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("species.starting") : t("species.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

type T = ReturnType<typeof useT>;

const KNOWN_PROBLEMS = ["tool_unavailable", "no_database", "database_unavailable", "collection_empty", "gtdbtk_memory", "gtdbtk_data_version"];

function planProblem(t: T, x: SpeciesPlan["problems"][number]) {
  return KNOWN_PROBLEMS.includes(x.code) ? t(`species.planProblem.${x.code}` as TranslationKey, x.params) : x.message;
}

function MethodOption({ method, plan, selected, onSelect }: { method: SpeciesMethod; plan?: SpeciesPlan; selected: boolean; onSelect: () => void }) {
  const t = useT();
  const validation = plan?.methods[method]?.validation;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn("space-y-1 rounded-lg border p-3 text-left text-xs transition-colors", selected ? "border-arva-royal bg-arva-royal/5 dark:border-arva-cyan dark:bg-arva-cyan/10" : "hover:bg-muted/50")}
    >
      <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
        {t(`species.methodName.${method}` as TranslationKey)}
        {validation && <Badge tone={VALIDATION_TONE[validation]}>{t(`species.validation.${validation}` as TranslationKey)}</Badge>}
      </span>
      <span className="block text-muted-foreground">{t(`species.methodWhat.${method}` as TranslationKey)}</span>
      {selected && <span className="block text-muted-foreground">{t(`species.methodRange.${method}` as TranslationKey)}</span>}
    </button>
  );
}

function ToolLine({ plan }: { plan: SpeciesPlan }) {
  const t = useT();
  const tool = plan.tool;
  if (tool.status !== "available") return <ErrorNote error={t("species.unavailable", { tool: tool.name, message: toolMessage(t, { ...tool, min_version: "" }) || tool.status })} />;
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>
        {t("species.toolLine", { tool: tool.name, version: tool.version ?? "?", licence: tool.license })}{" "}
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

export function DatabaseFacts({ database: d }: { database: SpeciesDatabase }) {
  const t = useT();
  const c = d.collection;
  return (
    <div className="space-y-1.5 rounded-lg border p-3 text-xs">
      <p className="font-medium">{d.name}</p>
      <p className="text-muted-foreground">
        {t("species.dbLine", { version: d.version ?? "?", source: d.version_source ? t(`annotation.dbVersionSource.${d.version_source}` as TranslationKey) : t("annotation.dbVersionSource.unknown"), size: d.size_bytes ? fmtBytes(d.size_bytes) : "?" })}
      </p>
      {c && (
        <>
          <p>{t("species.collectionLine", { genomes: c.genomes, species: c.species, genera: c.genus_count, type: c.type_material })}</p>
          {c.genus_count > 0 && c.genus_count <= 5 && <p className="text-muted-foreground">{t("species.collectionGenera", { genera: c.genera.join(", ") })}</p>}
          {c.genus_count === 1 && (
            <p className="flex gap-1.5 text-amber-700 dark:text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("species.singleGenus", { genus: c.genera[0] })}
            </p>
          )}
          {(c.missing ?? 0) > 0 && <p className="text-amber-700 dark:text-warning">{t("species.collectionMissing", { n: c.missing ?? 0 })}</p>}
        </>
      )}
      <p className="text-muted-foreground">{t("species.collectionBound")}</p>
    </div>
  );
}

function ContextNote({ plan }: { plan: SpeciesPlan }) {
  const t = useT();
  const { mlst, annotation } = plan.context;
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <p className="font-medium text-foreground">{t("species.contextTitle")}</p>
      <p>{mlst ? t("species.contextMlst", { scheme: mlst.scheme ?? "—", st: mlst.st ?? "—" }) : t("species.contextNoMlst")}</p>
      <p>
        {annotation?.genus
          ? t("species.contextAnnotation", { given: [annotation.genus, annotation.species].filter(Boolean).join(" "), tool: annotation.tool })
          : t("species.contextNoAnnotation")}
      </p>
    </div>
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
