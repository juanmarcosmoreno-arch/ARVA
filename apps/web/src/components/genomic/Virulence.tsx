import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { assemblyOptions } from "@/lib/annotation";
import { KIND_TONE, kindText } from "@/lib/amr";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import { COMPLETENESS_TONE, warningText } from "@/lib/mobile";
import { DatabaseTerms } from "./MobileDialog";
import type { Assembly, VirulenceRun, VirulenceSample } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";
const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

const proportion = (v: string, min: number) => v.trim() !== "" && Number.isFinite(Number(v)) && Number(v) > min && Number(v) <= 100;

/** Shows what a VFDB screen with ABRicate will do here — the bundled VFDB with its index date, checksum, licence and
 * citation status, the thresholds (ABRicate's defaults shown) — and runs it after an explicit confirmation. */
export function VirulenceDialog({ open, onOpenChange, sampleId, assemblies }: { open: boolean; onOpenChange: (o: boolean) => void; sampleId: string; assemblies: Assembly[] }) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const last = options[options.length - 1]?.assembly.id ?? "";
  const [assemblyId, setAssemblyId] = useState(last);
  const [minid, setMinid] = useState("80");
  const [mincov, setMincov] = useState("80");
  const [threads, setThreads] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (open) {
      setAssemblyId(last);
      setConfirmed(false);
    }
  }, [open]);
  const plan = useQuery({ queryKey: ["virulencePlan", assemblyId], queryFn: () => api.virulencePreview(assemblyId), enabled: open && Boolean(assemblyId), retry: false });
  const p = plan.data;
  const problems: TranslationKey[] = [];
  if (!proportion(minid, 0) || !proportion(mincov, -1)) problems.push("mobile.problem.setting");
  if (!confirmed) problems.push("amr.problem.confirm");
  const run = useMutation({
    mutationFn: () => api.runVirulence(assemblyId, { settings: { minid: Number(minid), mincov: Number(mincov) }, threads: threads ? Number(threads) : null, confirmed }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["virulence", sampleId] });
      onOpenChange(false);
    },
  });
  const tool = p?.tool;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("virulence.title")} description={t("virulence.description")} className="max-w-2xl">
      <div className="space-y-5 text-sm">
        <Select value={assemblyId} onChange={(e) => setAssemblyId(e.target.value)} aria-label={t("mlst.assembly")}>
          {options.map(({ assembly: a }) => (
            <option key={a.id} value={a.id}>
              {a.assembler} {a.assembler_version} · {fmtInt(a.stats.contig_count)} contigs · {fmtBases(a.stats.total_length)} · {fmtDate(a.created_at)} · {a.id.slice(0, 8)}
            </option>
          ))}
        </Select>
        {p && p.assembly.synthetic_evidence.length > 0 && <SyntheticNote evidence={p.assembly.synthetic_evidence} />}
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("mlst.checking")}</p>}
        <ErrorNote error={plan.error} />
        {tool && tool.status !== "available" && <ErrorNote error={t("mobile.unavailable", { tool: "ABRicate", message: toolMessage(t, { ...tool, min_version: "" }) || tool.status })} />}
        {tool?.status === "available" && <p className="text-xs text-muted-foreground">{t("mobile.toolLine", { tool: "ABRicate", version: tool.version ?? "?", licence: tool.license })}</p>}
        {p?.database && (
          <section className="space-y-1">
            <h4 className="flex items-center gap-1.5 text-sm font-semibold">
              {t("virulence.database")} <Explain id="vfdb" compact />
            </h4>
            <DatabaseTerms plan={p} />
            <p className="text-xs text-muted-foreground">{t("virulence.noUpdater")}</p>
          </section>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="--minid" hint={t("mobile.toolDefault", { value: p?.tool_defaults.minid ?? "80" })}>
            <Input type="number" min={1} max={100} step="any" value={minid} onChange={(e) => { setMinid(e.target.value); setConfirmed(false); }} />
          </Field>
          <Field label="--mincov" hint={t("mobile.toolDefault", { value: p?.tool_defaults.mincov ?? "80" })}>
            <Input type="number" min={0} max={100} step="any" value={mincov} onChange={(e) => { setMincov(e.target.value); setConfirmed(false); }} />
          </Field>
          <Field label={t("annotation.threads")}>
            <Input type="number" min={1} max={tool?.max_threads} placeholder={String(tool?.default_threads ?? "")} value={threads} onChange={(e) => setThreads(e.target.value)} />
          </Field>
        </div>
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("virulence.disclaimer")}</span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("virulence.confirm")}</span>
        </label>
        {(problems.length > 0 || (p?.problems.length ?? 0) > 0) && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{t(k)}</li>
            ))}
            {p?.problems.map((x) => (
              <li key={x.code} className="text-amber-700 dark:text-warning">
                {t(`mobile.planProblem.${x.code}` as TranslationKey, { tool: "ABRicate", status: "?", name: "?", files: "?", kind: "vfdb", detail: "", ...x.params })}
              </li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!p || tool?.status !== "available" || problems.length > 0 || p.problems.length > 0 || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("mlst.starting") : t("virulence.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

const pct = (v: number | null) => (v == null ? "—" : fmtNum(v, 2));

/** The virulence genes of an assembly from both sources, side by side: VFDB hits (ABRicate) and AMRFinderPlus's
 * virulence genes, each row with its source, its own method and completeness, and the other source's overlapping
 * rows; a source that did not run is "not searched", never "none found". */
export function VirulenceCard({ view, runs }: { view: VirulenceSample["assemblies"][number]; runs: VirulenceRun[] }) {
  const t = useT();
  const run = runs.find((r) => r.job_id === view.sources.vfdb.job_id);
  const sourceLine = (key: "vfdb" | "amrfinderplus") => {
    const s = view.sources[key];
    return t(`virulence.source.${s.status}` as TranslationKey, { source: t(`virulence.sourceName.${key}` as TranslationKey), n: fmtInt(s.hits), version: s.tool_version ?? "?", db: s.database_version ?? "?" });
  };
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {t("virulence.cardTitle")}
            <Badge tone={view.rows.length ? "blue" : "neutral"}>{view.rows.length ? t("virulence.rowsBadge", { n: view.rows.length }) : t("mobile.noneFound")}</Badge>
          </span>
        }
        description={t("virulence.cardSubtitle", { assembly: view.assembly_id.slice(0, 8) })}
        action={<Explain id="virulence_factor" compact />}
      />
      <CardBody className="space-y-3 pt-3">
        <p role="note" className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("virulence.disclaimer")}</span>
        </p>
        <ul className="space-y-0.5 text-xs">
          <li>{sourceLine("vfdb")}</li>
          <li>{sourceLine("amrfinderplus")}</li>
        </ul>
        {run && run.warnings.filter((w) => w.code !== "vfdb_meaning").length > 0 && (
          <ul role="status" className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            {run.warnings
              .filter((w) => w.code !== "vfdb_meaning")
              .map((w, i) => (
                <li key={`${w.code}-${i}`} className="flex gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {warningText(t, w, "virulence")}
                </li>
              ))}
          </ul>
        )}
        {view.rows.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-xs">
              <thead className="bg-muted/50">
                <tr>
                  <th className={TH}>{t("virulence.col.source")}</th>
                  <th className={TH}>{t("virulence.col.gene")}</th>
                  <th className={TH}>{t("virulence.col.factor")}</th>
                  <th className={TH}>{t("virulence.col.hit")}</th>
                  <th className={TH}>{t("amr.col.identity")}</th>
                  <th className={TH}>{t("amr.col.coverage")}</th>
                  <th className={TH}>{t("amr.col.location")}</th>
                  <th className={TH}>{t("virulence.col.alsoFound")}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {view.rows.map((r) => (
                  <tr key={`${r.source}-${r.id}`}>
                    <td className={TD}>
                      <Badge tone={r.source === "vfdb" ? "blue" : "neutral"}>{t(`virulence.sourceName.${r.source}` as TranslationKey)}</Badge>
                    </td>
                    <td className={`${TD} font-mono font-medium`}>{r.gene}</td>
                    <td className={TD}>
                      {r.vf_name ?? r.description ?? "—"}
                      {r.vf_category && <span className="block text-muted-foreground">{r.vf_category}</span>}
                    </td>
                    <td className={TD}>
                      {r.source === "amrfinderplus" ? (
                        <Badge tone={KIND_TONE[r.kind] ?? "neutral"}>{kindText(t, r.kind)}</Badge>
                      ) : (
                        <Badge tone={COMPLETENESS_TONE[r.kind] ?? "neutral"}>{t(`mobile.completeness.${["complete", "complete_gaps", "partial", "contig_end"].includes(r.kind) ? r.kind : "unknown"}` as TranslationKey)}</Badge>
                      )}
                      <code className="ml-1 text-[10px] text-muted-foreground">{r.method}</code>
                      {r.pieces && <span className="block text-muted-foreground">{t("virulence.pieces", { n: r.pieces })}</span>}
                    </td>
                    <td className={`${TD} tabular-nums`}>{pct(r.identity)}</td>
                    <td className={`${TD} tabular-nums`}>{pct(r.coverage)}</td>
                    <td className={`${TD} whitespace-nowrap font-mono`}>
                      {r.contig ?? "?"}:{r.start != null ? fmtInt(r.start) : "?"}–{r.end != null ? fmtInt(r.end) : "?"} ({r.strand ?? "?"})
                    </td>
                    <td className={TD}>{r.also_found_by.length ? r.also_found_by.join(", ") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {run && (
          <>
            <p className="text-xs text-muted-foreground">
              {t("virulence.runLine", { version: run.tool_version, db: run.database_version ?? "?", minid: String(run.parameters.minid ?? "?"), mincov: String(run.parameters.mincov ?? "?") })}
              {run.database_terms.licence && <span className="block">{t("mobile.dbLicence", { licence: run.database_terms.licence })}</span>}
            </p>
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.keys(run.files).map((k) => (
                <a key={k} href={api.virulenceFileUrl(run.job_id, k)} className="inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted">
                  <Download className="h-3.5 w-3.5" aria-hidden /> {k}
                </a>
              ))}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
