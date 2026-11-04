import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Dna, Download, Info, Loader2, Play, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { FailedCard, RunningCard } from "@/components/assembly/RunMonitor";
import { Explain } from "@/components/guide/Explain";
import type { GuideId } from "@/guide/metrics";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { assemblyOptions } from "@/lib/annotation";
import { assemblerText, assemblyOptionLabel } from "@/lib/assembly";
import { api } from "@/lib/api";
import { fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import type { AnalysisJobDetail, Assembly } from "@/lib/types";
import {
  type ApplicabilityInfo,
  genesText,
  settingsProblems,
  STAPH_MODULE,
  type StaphSummary,
  sourceText,
  TYPING_JOB,
  TYPING_METHODS,
  type TypingMethod,
  type TypingModuleInfo,
  type TypingResult,
  typingBody,
  typingWarningText,
} from "@/lib/typing";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";
const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

const active = (jobs: AnalysisJobDetail[]) => jobs.filter((j) => j.status === "pending" || j.status === "running");
const stopped = (jobs: AnalysisJobDetail[]) => jobs.filter((j) => j.status === "failed" || j.status === "cancelled").slice(0, 3);

function ApplicabilityNote({ info }: { info: ApplicabilityInfo }) {
  const t = useT();
  const evidence = info.checks.map((c) => t(`typing.evidence.${c.source}` as TranslationKey, { value: c.value })).join("; ");
  const ok = info.status === "applicable";
  return (
    <p className={`flex gap-1.5 text-xs ${ok ? "text-muted-foreground" : "text-amber-700 dark:text-warning"}`}>
      {ok ? <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />}
      <span>
        {t(`typing.applicability.${info.status}` as TranslationKey)}
        {evidence ? ` (${evidence})` : ""}
      </span>
    </p>
  );
}

/** Per step of a module: whether its tool and database are here, and what to install or register otherwise. */
function Requirements({ module }: { module: TypingModuleInfo }) {
  const t = useT();
  return (
    <ul className="space-y-1.5 text-xs">
      {module.requirements.map((r) => (
        <li key={r.key} className="rounded-md border p-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">
              {t(`typing.method.${r.key}` as TranslationKey)} · {r.tool.name} {r.tool.version ?? ""}
            </span>
            <span className={r.ready ? "text-success" : "text-amber-700 dark:text-warning"}>{r.ready ? t("typing.ready") : t("typing.missing")}</span>
          </div>
          {r.missing.includes("tool") && (
            <p className="mt-1 text-muted-foreground">
              {t("typing.toolMissing", { tool: r.tool.name, reason: toolMessage(t, { ...r.tool, min_version: "" }) || r.tool.status })}{" "}
              {r.tool.install.conda_lock && <code className="break-all">{r.tool.install.conda_lock}</code>}{" "}
              {r.tool.platforms.length > 0 && t("typing.platforms", { platforms: r.tool.platforms.join(", ") })}
            </p>
          )}
          {r.database && r.missing.includes("database") && (
            <div className="mt-1 space-y-0.5 text-muted-foreground">
              <p>{t("typing.ridomMissing")}</p>
              <p>
                <a href="https://spa.ridom.de/dynamic/sparepeats.fasta" target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
                  sparepeats.fasta
                </a>{" "}
                ·{" "}
                <a href="https://spa.ridom.de/dynamic/spatypes.txt" target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
                  spatypes.txt
                </a>{" "}
                ·{" "}
                {r.database.licence_url && (
                  <a href={r.database.licence_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
                    {t("typing.ridomTerms")}
                  </a>
                )}
              </p>
              <p>{t("typing.ridomTermsText")}</p>
              <Link to="/tools#reference-databases" className="text-arva-royal hover:underline dark:text-arva-cyan">
                {t("amr.openDatabases")}
              </Link>
            </div>
          )}
          {r.database && !r.missing.includes("database") && (
            <p className="mt-1 text-muted-foreground">{t("typing.ridomRegistered", { names: r.database.registered.map((d) => `${d.name} ${d.version ?? ""}`).join(", ") })}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Part({ label, value, source, uncertain, explain }: { label: string; value: string; source?: string; uncertain?: boolean; explain?: GuideId }) {
  return (
    <tr>
      <th className={`${TH} align-top`}>
        <span className="inline-flex items-center gap-1">{label}{explain && <Explain id={explain} compact />}</span>
      </th>
      <td className={TD}>
        {value}
        {uncertain ? " ?" : ""}
      </td>
      <td className={`${TD} text-muted-foreground`}>{source}</td>
    </tr>
  );
}

/** The summary of one assembly: each part with its own source, never merged, and the shorthand built from the
 * determined parts only (uncertain parts carry "?"). */
export function StaphSummaryCard({ summary }: { summary: StaphSummary }) {
  const t = useT();
  const nd = t("typing.notDetermined");
  const call = (key: "sccmec" | "spa" | "agr") => {
    const c = summary[key];
    if (!c) return nd;
    const value = c.call ?? nd;
    return `${value} (${t(`typing.status.${c.status}` as TranslationKey)})`;
  };
  const amr = summary.amr;
  const plus = Boolean(amr?.source.plus);
  const doubt = (part: string) => summary.uncertain.some((u) => u.part === part);
  const sccmec = summary.sccmec?.details as { mecA?: boolean; ccr_complexes?: string[]; mec_classes?: string[] } | undefined;
  return (
    <Card className="min-w-0">
      <CardHeader
        title={summary.shorthand ?? t("typing.noShorthand")}
        description={t("typing.summarySubtitle", { assembly: summary.assembly_id.slice(0, 8) })}
        action={<Explain id="staph_typing_summary" compact />}
      />
      <CardBody className="space-y-3 pt-2">
        <ApplicabilityNote info={summary.applicability} />
        {summary.uncertain.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-700 dark:text-warning">
            {summary.uncertain.map((u) => (
              <li key={`${u.part}-${u.reason}`}>{t(`typing.uncertain.${u.reason}` as TranslationKey, { status: "?", score: "?", genes: "", ...u.params })}</li>
            ))}
          </ul>
        )}
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <tbody className="divide-y">
              <Part
                label={t("typing.part.mlst")}
                value={summary.mlst ? `${summary.mlst.st ? `ST${summary.mlst.st}` : nd} · ${summary.mlst.scheme ?? "-"} · ${summary.mlst.status}${summary.mlst.clonal_complex ? ` · ${summary.mlst.clonal_complex}` : ""}` : nd}
                source={sourceText(t, summary.mlst?.source)}
                uncertain={doubt("st")}
              />
              <Part label={t("typing.part.sccmec")} value={call("sccmec")} source={sourceText(t, summary.sccmec?.source)} uncertain={doubt("sccmec")} />
              {sccmec && (
                <Part
                  label={t("typing.part.ccrMec")}
                  value={`${(sccmec.ccr_complexes ?? []).join(", ") || "-"} · ${(sccmec.mec_classes ?? []).join(", ") || "-"} · mecA ${sccmec.mecA ? "+" : "-"}`}
                  source={sourceText(t, summary.sccmec?.source)}
                />
              )}
              <Part label={t("typing.part.spa")} value={call("spa")} source={sourceText(t, summary.spa?.source)} explain="spa_typing" />
              <Part label={t("typing.part.agr")} value={call("agr")} source={sourceText(t, summary.agr?.source)} uncertain={doubt("agr")} explain="agr" />
              <Part label={t("typing.part.mec")} value={amr ? genesText(t, [...amr.mecA, ...amr.mecC, ...(amr.mec_other ?? []), ...(amr.mec_homologues ?? [])], true) : t("typing.notSearched")} source={sourceText(t, amr?.source)} uncertain={doubt("mec")} />
              <Part label={t("typing.part.crosscheck")} value={t(`typing.crosscheck.${summary.mec_crosscheck.status}` as TranslationKey)} />
              <Part label={t("typing.part.pvl")} value={genesText(t, amr?.pvl, plus)} source={sourceText(t, amr?.source)} uncertain={doubt("pvl")} />
              <Part label={t("typing.part.tst")} value={genesText(t, amr?.tst, plus)} source={sourceText(t, amr?.source)} />
              <Part label={t("typing.part.enterotoxins")} value={genesText(t, amr?.enterotoxins, plus)} source={sourceText(t, amr?.source)} />
              <Part label={t("typing.part.exfoliative")} value={genesText(t, amr?.exfoliative_toxins, plus)} source={sourceText(t, amr?.source)} />
            </tbody>
          </table>
        </div>
        {amr && !plus && <p className="text-xs text-muted-foreground">{t("typing.amrWithoutPlus")}</p>}
        <p className="text-xs text-muted-foreground">{t("typing.genotypeNote")}</p>
      </CardBody>
    </Card>
  );
}

function ResultCard({ result }: { result: TypingResult }) {
  const t = useT();
  const d = result.details as Record<string, unknown>;
  const align = d.operon_alignment as { covered_fraction: number | null } | null | undefined;
  const lines: string[] = [];
  if (result.method === "sccmec") {
    lines.push(t("typing.detail.sccmec", { type: String(d.type ?? "-"), subtype: String(d.subtype ?? "-"), coverage: d.coverage == null ? "-" : String(d.coverage), targets: ((d.targets as string[]) ?? []).join(", ") || "-" }));
  } else if (result.method === "spa") {
    lines.push(t("typing.detail.spa", { repeats: String(d.repeats ?? "-"), contigs: fmtInt(((d.rows as unknown[]) ?? []).length) }));
  } else {
    lines.push(
      t("typing.detail.agr", {
        score: String(d.match_score ?? "-"),
        agrD: t(`typing.agrD.${String(d.canonical_agrD)}` as TranslationKey),
        frameshifts: d.frameshifts == null ? t("typing.notDetermined") : String(d.frameshifts),
        extracted: align?.covered_fraction == null ? "-" : `${(align.covered_fraction * 100).toFixed(1)} %`,
      }),
    );
    const variants = (d.variants as { gene: string; effect: string; position: number }[]) ?? [];
    for (const v of variants) lines.push(`${v.gene}: ${v.effect} (${v.position})`);
  }
  return (
    <div className="space-y-1.5 rounded-lg border p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">
          {t(`typing.method.${result.method}` as TranslationKey)} · {result.call ?? t("typing.notDetermined")} · {t(`typing.status.${result.status}` as TranslationKey)}
        </span>
        <span className="text-muted-foreground">
          {result.tool} {result.tool_version} · {fmtDate(result.created_at)}
        </span>
      </div>
      {lines.map((l) => (
        <p key={l}>{l}</p>
      ))}
      <p className="text-muted-foreground">
        {result.database_name ? t("typing.dataLine", { name: result.database_name, version: result.database_version ?? "?", checksum: (result.database_checksum ?? "").slice(0, 19) }) : ""}
      </p>
      {result.warnings.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-amber-700 dark:text-warning">
          {result.warnings.map((w) => (
            <li key={w.code}>{typingWarningText(t, w)}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        {Object.keys(result.files).map((name) => (
          <a key={name} href={api.typingFileUrl(result.job_id, name)} className="inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan">
            <Download className="h-3 w-3" aria-hidden /> {name}
          </a>
        ))}
      </div>
    </div>
  );
}

/** The Genomic analysis tab's species-specific typing: the modules with what they need here, per assembly whether
 * the species evidence supports each, the S. aureus summary card and every step's call. */
export function TypingSection({ sampleId, jobs, onStart }: { sampleId: string; jobs: AnalysisJobDetail[]; onStart: () => void }) {
  const t = useT();
  const view = useQuery({ queryKey: ["typing", sampleId], queryFn: () => api.typingSample(sampleId) });
  const runs = jobs.filter((j) => j.job_type === TYPING_JOB);
  const v = view.data;
  const module = v?.modules.find((m) => m.key === STAPH_MODULE);
  return (
    <section className="space-y-4" aria-labelledby="typing-section">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="max-w-2xl space-y-1">
          <h3 id="typing-section" className="text-sm font-semibold">
            {t("typing.sectionTitle")}
          </h3>
          <p className="text-sm text-muted-foreground">{t("typing.intro")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Explain id="sccmec" />
          <Button onClick={onStart} disabled={!v?.assemblies.length}>
            <Plus className="h-4 w-4" /> {t("typing.start")}
          </Button>
        </div>
      </div>
      <ErrorNote error={view.error} />
      {module && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold">{t("typing.moduleLine", { name: t("typing.module.staphylococcus_aureus"), species: module.species.join(", "), schemes: module.mlst_schemes.join(", ") })}</h4>
          <Requirements module={module} />
        </div>
      )}
      {v?.assemblies.map((a) => (
        <div key={a.assembly_id} className="space-y-1">
          <p className="text-xs text-muted-foreground">
            {assemblerText(t, a.assembler, a.assembler_version)} · {fmtDate(a.created_at)} · {a.assembly_id.slice(0, 8)}
          </p>
          {a.applicability[STAPH_MODULE] && <ApplicabilityNote info={a.applicability[STAPH_MODULE]} />}
          {a.summary && <StaphSummaryCard summary={a.summary} />}
        </div>
      ))}
      {active(runs).map((j) => (
        <RunningCard key={j.id} job={j} names={new Map()} />
      ))}
      {(v?.results ?? []).map((r) => (
        <ResultCard key={r.id} result={r} />
      ))}
      {stopped(runs).map((j) => (
        <FailedCard key={j.id} job={j} />
      ))}
      {v && !v.results.length && !active(runs).length && !stopped(runs).length && (
        <EmptyState icon={<Dna className="h-7 w-7" />} title={t("typing.empty")}>
          {v.assemblies.length ? t("typing.emptyHint") : t("mlst.noAssembly")}
        </EmptyState>
      )}
    </section>
  );
}

/** Shows what one S. aureus typing step will do here — the tool, the Ridom files (spa) or the data the tool bundles,
 * the settings with the tool's defaults, and whether the species evidence supports the module — and runs it after an
 * explicit confirmation (and, when the evidence does not support it, an explicit override). */
export function StaphTypingDialog({ open, onOpenChange, sampleId, assemblies }: { open: boolean; onOpenChange: (o: boolean) => void; sampleId: string; assemblies: Assembly[] }) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const last = options[options.length - 1]?.assembly.id ?? "";
  const [assemblyId, setAssemblyId] = useState(last);
  const [method, setMethod] = useState<TypingMethod>("sccmec");
  const [databaseId, setDatabaseId] = useState("");
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [override, setOverride] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (open) {
      setAssemblyId(last);
      setMethod("sccmec");
      setDatabaseId("");
      setSettings({});
      setOverride(false);
      setConfirmed(false);
    }
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const plan = useQuery({
    queryKey: ["typingPlan", assemblyId, method, databaseId],
    queryFn: () => api.typingPreview(assemblyId, STAPH_MODULE, method, databaseId || null),
    enabled: open && Boolean(assemblyId),
    retry: false,
  });
  const p = plan.data;
  const problems = settingsProblems(method, settings);
  const needsOverride = Boolean(p?.applicability.override_required);
  const run = useMutation({
    mutationFn: () => api.runTyping(assemblyId, STAPH_MODULE, typingBody(method, settings, databaseId, override)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["typing", sampleId] });
      onOpenChange(false);
    },
  });
  const change = (fn: () => void) => {
    fn();
    setConfirmed(false);
  };
  const blocked = !p || p.tool.status !== "available" || p.problems.length > 0 || problems.length > 0 || (needsOverride && !override) || !confirmed;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("typing.title")} description={t("typing.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <section className="space-y-2">
          <h4 className="text-sm font-semibold">{t("mlst.assembly")}</h4>
          <Select value={assemblyId} onChange={(e) => change(() => setAssemblyId(e.target.value))} aria-label={t("mlst.assembly")}>
            {options.map(({ assembly: a, depth }) => (
              <option key={a.id} value={a.id}>
                {"  ".repeat(depth)}
                {depth ? "↳ " : ""}
                {assemblyOptionLabel(t, a)}
              </option>
            ))}
          </Select>
          {p && p.assembly.synthetic_evidence.length > 0 && <SyntheticNote evidence={p.assembly.synthetic_evidence} />}
          {p && <ApplicabilityNote info={p.applicability} />}
        </section>
        <section className="space-y-2">
          <h4 className="text-sm font-semibold">{t("typing.stepLabel")}</h4>
          <div className="space-y-1.5 text-xs">
            {TYPING_METHODS.map((m) => (
              <label key={m} className="flex items-start gap-2">
                <input type="radio" className={CHECK} checked={method === m} onChange={() => change(() => { setMethod(m); setDatabaseId(""); setSettings({}); })} />
                <span>
                  <span className="font-medium">{t(`typing.method.${m}` as TranslationKey)}</span>
                  <span className="block text-muted-foreground">{t(`typing.methodHint.${m}` as TranslationKey)}</span>
                </span>
              </label>
            ))}
          </div>
        </section>
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("mlst.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && p.tool.status === "available" && (
          <p className="text-xs text-muted-foreground">
            {t("mobile.toolLine", { tool: p.tool.name, version: p.tool.version ?? "?", licence: p.tool.license })}{" "}
            <a href={p.tool.citation_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
              {t("annotation.cite")}
            </a>
          </p>
        )}
        {p?.bundled && <p className="text-xs text-muted-foreground">{t("typing.bundled", { name: p.bundled.name, checksum: p.bundled.checksum.slice(0, 19) })}</p>}
        {method === "spa" && p && p.databases.length > 0 && (
          <section className="space-y-1">
            <h4 className="text-sm font-semibold">{t("typing.ridomFiles")}</h4>
            <Select value={databaseId || p.database?.id || ""} onChange={(e) => change(() => setDatabaseId(e.target.value))} aria-label={t("typing.ridomFiles")}>
              {p.databases.map((d) => (
                <option key={d.id} value={d.id} disabled={!d.available}>
                  {d.name} {d.version ?? ""}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{t("typing.ridomTermsText")}</p>
          </section>
        )}
        {p && method === "sccmec" && (
          <section className="grid gap-3 sm:grid-cols-2">
            {Object.entries(p.defaults).map(([key, def]) => (
              <Field key={key} label={`--${key.replace(/_/g, "-")}`} hint={p.tool_defaults[key.replace(/_/g, "-")] ? t("mobile.toolDefault", { value: p.tool_defaults[key.replace(/_/g, "-")] }) : undefined}>
                <Input type="number" min={1} max={100} value={settings[key] ?? def} onChange={(e) => change(() => setSettings((s) => ({ ...s, [key]: e.target.value })))} />
              </Field>
            ))}
          </section>
        )}
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t(`typing.note.${method}` as TranslationKey)}</span>
        </p>
        {needsOverride && (
          <label className="flex items-start gap-2 text-xs text-amber-700 dark:text-warning">
            <input type="checkbox" className={CHECK} checked={override} onChange={(e) => setOverride(e.target.checked)} />
            <span>{t("typing.override")}</span>
          </label>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("typing.confirm")}</span>
        </label>
        {(problems.length > 0 || (p?.problems.length ?? 0) > 0) && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-700 dark:text-warning">
            {problems.map((k) => (
              <li key={k}>{t(k)}</li>
            ))}
            {p?.problems.map((x) => (
              <li key={x.code}>{t(`typing.planProblem.${x.code}` as TranslationKey, { tool: "?", status: "?", detail: "", ...x.params })}</li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={blocked || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("mlst.starting") : t("typing.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The project's S. aureus typing: per sample the summary of its most recently typed assembly (empty: no step ran),
 * with a CSV of every part and its source. */
export function ProjectTyping({ projectId }: { projectId: string }) {
  const t = useT();
  const overview = useQuery({ queryKey: ["projectTyping", projectId], queryFn: () => api.typingProject(projectId, STAPH_MODULE) });
  if (overview.error) return <ErrorNote error={overview.error} />;
  const o = overview.data;
  if (!o || o.typed === 0) return null;
  const nd = t("typing.notDetermined");
  return (
    <Card className="mt-6 min-w-0" id="project-typing">
      <CardHeader
        title={t("projectTyping.title", { typed: o.typed, total: o.samples.length })}
        description={t("projectTyping.subtitle")}
        action={
          <div className="flex items-center gap-2">
            <Explain id="staph_typing_summary" compact />
            <a href={api.typingProjectCsvUrl(projectId, STAPH_MODULE)} className="inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan">
              <Download className="h-3.5 w-3.5" aria-hidden /> CSV
            </a>
          </div>
        }
      />
      <CardBody className="pt-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className={TH}>{t("projectMlst.sample")}</th>
                <th className={TH}>{t("typing.shorthand")}</th>
                <th className={TH}>{t("typing.part.sccmec")}</th>
                <th className={TH}><span className="inline-flex items-center gap-1">{t("typing.part.spa")}<Explain id="spa_typing" compact /></span></th>
                <th className={TH}><span className="inline-flex items-center gap-1">{t("typing.part.agr")}<Explain id="agr" compact /></span></th>
                <th className={TH}>{t("typing.part.pvl")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {o.samples.map((s) => (
                <tr key={s.sample_id}>
                  <td className={TD}>
                    <Link to={`/samples/${s.sample_id}?tab=genomic`} className="font-medium text-arva-royal hover:underline dark:text-arva-cyan">
                      {s.sample_code}
                    </Link>
                  </td>
                  <td className={TD}>{s.summary ? (s.summary.shorthand ?? nd) : t("typing.notTyped")}</td>
                  <td className={TD}>{s.summary?.sccmec?.call ?? (s.summary ? nd : "")}</td>
                  <td className={TD}>{s.summary?.spa?.call ?? (s.summary ? nd : "")}</td>
                  <td className={TD}>{s.summary?.agr?.call ?? (s.summary ? nd : "")}</td>
                  <td className={TD}>{s.summary ? genesText(t, s.summary.amr?.pvl, Boolean(s.summary.amr?.source.plus)) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  );
}
