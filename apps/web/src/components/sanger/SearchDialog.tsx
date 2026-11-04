import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Play, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtInt, fmtMax } from "@/lib/format";
import { messageText, toolMessage } from "@/lib/messages";
import { BLAST_SOURCES, BLAST_TASKS, SOURCE_KEYS, type IdentificationBrief, type SearchIn, type SourceKey, type SourcePlan } from "@/lib/sanger";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** What a search would do for each local source (tool and version, database and version or the genomes with their
 * checksums, settings, what blocks it), and the start after an explicit confirmation. One job per source; nothing is
 * sent outside this computer. */
export function SearchDialog({ identification, onClose, onStarted }: { identification: IdentificationBrief; onClose: () => void; onStarted: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [sources, setSources] = useState<SourceKey[]>([...SOURCE_KEYS]);
  const [databases, setDatabases] = useState<Partial<Record<SourceKey, string>>>({});
  const [assemblies, setAssemblies] = useState<string[] | null>(null);
  const [tasks, setTasks] = useState<Partial<Record<SourceKey, string>>>({});
  const [confirmed, setConfirmed] = useState(false);
  const request: SearchIn = {
    sources,
    database_ids: databases,
    assembly_ids: assemblies,
    blast: Object.fromEntries(Object.entries(tasks).map(([k, v]) => [k, { task: v }])),
  };
  const plan = useQuery({
    queryKey: ["sangerSearchPlan", identification.id, request],
    queryFn: () => api.sangerSearchPlan(identification.id, request),
    enabled: sources.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const genomes = useQuery({ queryKey: ["sangerGenomes", identification.id], queryFn: () => api.sangerGenomes(identification.id), enabled: sources.includes("genomes") });
  const start = useMutation({
    mutationFn: () => api.startSangerSearch(identification.id, { ...request, only_runnable: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sanger"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onStarted();
    },
  });
  const p = plan.data;
  const toggle = (s: SourceKey) => {
    setConfirmed(false);
    setSources((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : SOURCE_KEYS.filter((x) => x === s || cur.includes(x))));
  };
  const chosenGenomes = assemblies ?? p?.sources.find((s) => s.source === "genomes")?.genomes.map((g) => g.assembly_id) ?? [];
  const toggleGenome = (id: string) => {
    setConfirmed(false);
    setAssemblies(chosenGenomes.includes(id) ? chosenGenomes.filter((x) => x !== id) : [...chosenGenomes, id]);
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("sanger.search.title", { label: identification.label })} description={t("sanger.search.description", { n: fmtInt(identification.length) })} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <p className="flex items-start gap-2 rounded-lg border border-arva-teal/30 bg-arva-teal/5 p-2 text-xs">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-arva-teal" aria-hidden /> {t("sanger.search.localOnly")}
        </p>
        <fieldset className="space-y-1">
          <legend className="mb-1 flex items-center gap-1 text-xs font-semibold">
            {t("sanger.search.sources")} <Explain id="sanger_sources" compact />
          </legend>
          <div className="grid gap-1 sm:grid-cols-2">
            {SOURCE_KEYS.map((s) => (
              <label key={s} className="flex items-start gap-2 text-xs">
                <input type="checkbox" className={CHECK} checked={sources.includes(s)} onChange={() => toggle(s)} />
                <span>
                  <span className="font-medium">{t(`sanger.source.${s}` as const)}</span>
                  <span className="block text-[11px] text-muted-foreground">{t(`sanger.sourceHint.${s}` as const)}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <ErrorNote error={plan.error} />
        {!p && sources.length > 0 && <Skeleton className="h-40" />}
        {p && (
          <ul className="space-y-2">
            {p.sources.map((s) => (
              <SourceRow
                key={s.source}
                plan={s}
                database={databases[s.source] ?? s.database?.id ?? ""}
                onDatabase={(id) => {
                  setConfirmed(false);
                  setDatabases((d) => ({ ...d, [s.source]: id }));
                }}
                task={tasks[s.source] ?? String(s.settings.task ?? "")}
                onTask={(task) => {
                  setConfirmed(false);
                  setTasks((x) => ({ ...x, [s.source]: task }));
                }}
              >
                {s.source === "genomes" && (
                  <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">
                    {(genomes.data ?? []).map((g) => (
                      <label key={g.assembly_id} className="flex items-start gap-2 text-[11px]">
                        <input type="checkbox" className={CHECK} checked={chosenGenomes.includes(g.assembly_id)} onChange={() => toggleGenome(g.assembly_id)} />
                        <span>
                          {g.sample_code} · {g.assembler} {g.assembler_version}
                          {g.total_length != null && ` · ${fmtBases(g.total_length)}`}
                          {g.sample_id === identification.sample_id && <Badge tone="teal" className="ml-1">{t("sanger.search.ownSample")}</Badge>}
                        </span>
                      </label>
                    ))}
                    {genomes.data?.length === 0 && <p className="text-[11px] text-muted-foreground">{t("sanger.search.noGenomes")}</p>}
                  </div>
                )}
              </SourceRow>
            ))}
          </ul>
        )}
        {p && p.blocked.length > 0 && <p className="text-xs text-amber-700 dark:text-warning">{t("sanger.search.blockedNote", { n: p.blocked.length, runnable: p.runnable.length })}</p>}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!p || p.runnable.length === 0} />
          <span>{t("sanger.search.confirm", { n: p?.runnable.length ?? 0 })}</span>
        </label>
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => start.mutate()} disabled={!p || p.runnable.length === 0 || !confirmed || start.isPending || plan.isFetching}>
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {t("sanger.search.start", { n: p?.runnable.length ?? 0 })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function SourceRow({ plan, database, onDatabase, task, onTask, children }: { plan: SourcePlan; database: string; onDatabase: (id: string) => void; task: string; onTask: (t: string) => void; children?: React.ReactNode }) {
  const t = useT();
  const blocked = plan.problems.length > 0;
  const tool = plan.tool;
  return (
    <li className={blocked ? "rounded-lg border border-warning/40 bg-warning/5 p-2" : "rounded-lg border p-2"}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold">{t(`sanger.source.${plan.source}` as const)}</span>
        <Badge tone={blocked ? "warning" : "success"}>{blocked ? t("sanger.search.blocked") : t("sanger.search.ready")}</Badge>
        <span className="text-muted-foreground">
          {tool.name} {tool.version ?? ""}
          {tool.status !== "available" && ` · ${toolMessage(t, { ...tool, min_version: "" })}`}
        </span>
      </div>
      {plan.database_options.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
          <span className="text-muted-foreground">{t("sanger.search.database")}</span>
          {plan.database_options.length > 1 ? (
            <Select className="h-7 w-auto text-[11px]" value={database} onChange={(e) => onDatabase(e.target.value)} aria-label={t("sanger.search.databaseOf", { source: t(`sanger.source.${plan.source}` as const) })}>
              {plan.database_options.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} {d.version ?? ""}
                </option>
              ))}
            </Select>
          ) : (
            <span>
              {plan.database?.name} {plan.database?.version ?? ""}
            </span>
          )}
          {plan.database?.checksum && <code className="text-muted-foreground">{plan.database.checksum.slice(0, 19)}…</code>}
          {plan.collection && <span className="text-muted-foreground">{t("sanger.search.collection", { genomes: fmtInt(plan.collection.genomes), species: fmtInt(plan.collection.species) })}</span>}
        </div>
      )}
      {BLAST_SOURCES.has(plan.source) && plan.settings.task != null && (
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
          <span className="text-muted-foreground">{t("sanger.search.task")}</span>
          <Select className="h-7 w-auto text-[11px]" value={task} onChange={(e) => onTask(e.target.value)} aria-label={t("sanger.search.taskOf", { source: t(`sanger.source.${plan.source}` as const) })}>
            {BLAST_TASKS.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </Select>
          <span className="text-muted-foreground">{t("sanger.search.evalue", { evalue: String(plan.settings.evalue), max: fmtInt(Number(plan.settings.max_target_seqs)) })}</span>
        </div>
      )}
      {plan.source === "amrfinderplus" && <p className="mt-1 text-[11px] text-muted-foreground">{t("sanger.search.amrSettings", { coverage: fmtMax(100 * Number(plan.settings.coverage_min ?? 0.1), 2) })}</p>}
      {children}
      {plan.problems.map((pr, i) => (
        <p key={i} className="mt-1 flex items-start gap-1.5 text-[11px] text-amber-700 dark:text-warning">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden /> {messageText(t, "sanger.problem", { code: pr.code, params: pr.params, text: pr.message })}
        </p>
      ))}
    </li>
  );
}
