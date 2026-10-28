import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Download, ExternalLink, FileBarChart, Loader2, Play } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { JobStatusBadge } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { useTools } from "@/components/tools/useTools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, shellJoin } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import {
  DEFINITION_KEY,
  MODULE_NAME,
  MULTIQC_DATA,
  MULTIQC_JOB,
  MULTIQC_REPORT,
  REASON_KEY,
  UNIT_KEY,
  columnGroups,
  columnId,
  columnTitle,
  formatStat,
  isActive,
  outputNamed,
  planBySample,
  reportViews,
} from "@/lib/multiqc";
import type { AnalysisJob, MultiqcColumn, MultiqcPlan, MultiqcSummary, Sample, Tool } from "@/lib/types";
import { cn } from "@/lib/utils";

const LINK_BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted";

/** Project page card: what a MultiQC project report would include, running it, and the reports built so far. */
export function ProjectQcReport({ projectId, samples }: { projectId: string; samples: Sample[] }) {
  const t = useT();
  const queryClient = useQueryClient();
  const tools = useTools();
  const tool = tools.data?.find((x) => x.id === "multiqc");
  const [includeDerived, setIncludeDerived] = useState(false);
  const [deselected, setDeselected] = useState<Set<string>>(new Set());
  const selected = samples.filter((s) => !deselected.has(s.id)).map((s) => s.id);
  const body = { include_derived: includeDerived, ...(deselected.size ? { sample_ids: selected } : {}) };

  const plan = useQuery({
    queryKey: ["multiqcPlan", projectId, includeDerived, selected.join(",")],
    queryFn: () => api.multiqcPreview(projectId, body),
    enabled: selected.length > 0,
  });
  const jobs = useQuery({
    queryKey: ["projectJobs", projectId],
    queryFn: () => api.projectJobs(projectId),
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 1500 : false),
  });
  const reports = (jobs.data ?? []).filter((j) => j.job_type === MULTIQC_JOB);
  const building = reports.some(isActive);
  const run = useMutation({
    mutationFn: () => api.runMultiqc(projectId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projectJobs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  const toggleSample = (id: string) =>
    setDeselected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const inputs = selected.length ? plan.data?.inputs ?? [] : [];
  const sampleCount = new Set(inputs.map((i) => i.sample_id)).size;
  const canRun = tool?.status === "available" && inputs.length > 0 && !building && !run.isPending && !plan.isFetching;
  const { latest, completed, previous } = reportViews(reports);

  return (
    <Card className="mt-6" id="project-qc-report">
      <CardHeader title={t("multiqc.title")} description={t("multiqc.subtitle")} action={<Explain id="multiqc" compact />} />
      <CardBody className="space-y-5">
        <Availability tool={tool} loading={tools.isLoading} />

        <section aria-labelledby="mqc-rule" className="space-y-2">
          <h4 id="mqc-rule" className="text-sm font-semibold">
            {t("multiqc.ruleTitle")}
          </h4>
          <p className="text-xs text-muted-foreground">{t("multiqc.rule")}</p>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]"
              checked={includeDerived}
              onChange={(e) => setIncludeDerived(e.target.checked)}
            />
            <span>
              {t("multiqc.includeDerived")}
              <span className="block text-xs text-muted-foreground">{t("multiqc.includeDerivedHint")}</span>
            </span>
          </label>
        </section>

        <section aria-labelledby="mqc-samples" className="space-y-2">
          <h4 id="mqc-samples" className="text-sm font-semibold">
            {t("multiqc.samples")}
          </h4>
          <ErrorNote error={plan.error} />
          {plan.isLoading && <p className="text-xs text-muted-foreground">{t("multiqc.loadingPlan")}</p>}
          <SamplePlan samples={samples} plan={selected.length ? plan.data : undefined} deselected={deselected} onToggle={toggleSample} />
          {plan.data && selected.length > 0 && (
            <p className="text-xs font-medium">{inputs.length ? t("multiqc.included", { count: inputs.length }) : t("multiqc.nothing")}</p>
          )}
        </section>

        <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
          <p className="text-xs">
            {t("multiqc.runExplain", {
              version: (tool?.status === "available" ? tool.version : tool?.min_version) ?? "",
              inputs: inputs.length,
              samples: sampleCount,
            })}
          </p>
          <p className="text-xs text-muted-foreground">{t("multiqc.privacy")}</p>
          <Button onClick={() => run.mutate()} disabled={!canRun}>
            {building || run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {building ? t("multiqc.running") : t("multiqc.run")}
          </Button>
          <ErrorNote error={run.error} />
        </div>

        <ErrorNote error={jobs.error} />
        {latest && (
          <section aria-labelledby="mqc-latest" className="space-y-3">
            <h4 id="mqc-latest" className="text-sm font-semibold">
              {t("multiqc.latest")}
            </h4>
            <ReportItem job={latest} expanded={latest === completed} />
          </section>
        )}
        {completed && completed !== latest && (
          <section aria-labelledby="mqc-completed" className="space-y-3">
            <h4 id="mqc-completed" className="text-sm font-semibold">
              {t("multiqc.lastCompleted")}
            </h4>
            <p className="text-xs text-muted-foreground">{t("multiqc.lastCompletedNote", { date: fmtDate(completed.finished_at) })}</p>
            <ReportItem job={completed} expanded />
          </section>
        )}
        {previous.length > 0 && (
          <section aria-labelledby="mqc-previous" className="space-y-2">
            <h4 id="mqc-previous" className="text-sm font-semibold">
              {t("multiqc.previous")}
            </h4>
            <ul className="space-y-2">
              {previous.map((j) => (
                <li key={j.id}>
                  <ReportItem job={j} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </CardBody>
    </Card>
  );
}

function Availability({ tool, loading }: { tool: Tool | undefined; loading: boolean }) {
  const t = useT();
  if (loading) return <p className="text-xs text-muted-foreground">{t("multiqc.checking")}</p>;
  if (tool?.status === "available") {
    return (
      <div className="space-y-1 text-xs">
        <p className="text-muted-foreground">{t("multiqc.available", { version: tool.version ?? "" })}</p>
        {!tool.version_validated && (
          <p className="flex gap-1.5 text-amber-700 dark:text-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {toolMessage(t, tool)}
          </p>
        )}
      </div>
    );
  }
  return (
    <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
      <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="break-words">
          {tool?.status === "incompatible"
            ? toolMessage(t, tool)
            : tool?.status === "not_installed"
              ? t("multiqc.notInstalled")
              : t("multiqc.unavailable", { message: (tool && toolMessage(t, tool)) || tool?.status || "?" })}
        </p>
        <p>
          {t("multiqc.installHint")}{" "}
          <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
            {t("multiqc.toolsLink")}
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

function SamplePlan({
  samples,
  plan,
  deselected,
  onToggle,
}: {
  samples: Sample[];
  plan: MultiqcPlan | undefined;
  deselected: Set<string>;
  onToggle: (id: string) => void;
}) {
  const t = useT();
  const bySample = new Map((plan ? planBySample(plan) : []).map((p) => [p.sampleId, p]));
  return (
    <ul className="max-h-80 divide-y overflow-auto rounded-lg border">
      {samples.map((s) => {
        const entry = bySample.get(s.id);
        const off = deselected.has(s.id);
        return (
          <li key={s.id} className="px-3 py-2">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                className="h-4 w-4 shrink-0 accent-[#00B4A6]"
                checked={!off}
                onChange={() => onToggle(s.id)}
                aria-label={t("multiqc.includeSample", { sample: s.sample_code })}
              />
              <span className={cn("min-w-0 break-words", off && "text-muted-foreground line-through")}>{s.sample_code}</span>
            </label>
            {!off && entry && (
              <ul className="mt-1 space-y-1 pl-6 text-xs">
                {entry.inputs.map((i) => (
                  <li key={`${i.module}-${i.job_id}`} className="flex flex-wrap items-baseline gap-x-1.5">
                    <Badge tone="blue">{MODULE_NAME[i.module]}</Badge>
                    <span className="min-w-0 break-all">{i.file_names.join(" + ")}</span>
                    <span className="text-muted-foreground">
                      {t("multiqc.asName", { name: i.name })} · {i.tool_name} {i.tool_version} · {fmtDate(i.finished_at)}
                    </span>
                  </li>
                ))}
                {entry.excluded.map((e, n) => (
                  <li key={`x-${e.job_id ?? n}`} className="text-muted-foreground">
                    <span className="font-medium">{t("multiqc.excluded")}</span>
                    {e.module && ` · ${MODULE_NAME[e.module]}`}
                    {e.file_names.length > 0 && ` · ${e.file_names.join(" + ")}`}: {t(REASON_KEY[e.reason])}
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function ReportItem({ job, expanded = false }: { job: AnalysisJob; expanded?: boolean }) {
  const t = useT();
  const summary = job.result_summary as unknown as MultiqcSummary | null;
  const report = outputNamed(job, MULTIQC_REPORT);
  const data = outputNamed(job, MULTIQC_DATA);
  const inputs = ((job.parameters?.inputs as unknown[] | undefined) ?? []).length;
  const samples = summary ? new Set(summary.samples.map((s) => s.sample_id)).size : 0;
  const versions = summary
    ? Object.entries(summary.versions.arva_jobs)
        .map(([name, v]) => `${name} ${v.join(", ")}`)
        .join(" · ")
    : "";
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <JobStatusBadge status={job.status} />
        <span className="text-xs text-muted-foreground">
          {summary
            ? t("multiqc.meta", { version: summary.multiqc_version, date: fmtDate(job.finished_at), inputs, samples })
            : `${job.tool_name} ${job.tool_version} · ${fmtDate(job.created_at)}`}
        </span>
      </div>
      {job.status === "completed" && (
        <div className="flex flex-wrap gap-2">
          {report && (
            <a className={LINK_BUTTON} href={api.jobOutputUrl(job.id, MULTIQC_REPORT)} target="_blank" rel="noopener noreferrer">
              <FileBarChart className="h-3.5 w-3.5" aria-hidden /> {t("multiqc.open")} <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          )}
          {data && (
            <a className={LINK_BUTTON} href={api.jobOutputUrl(job.id, MULTIQC_DATA, true)}>
              <Download className="h-3.5 w-3.5" aria-hidden /> {t("multiqc.data")}
            </a>
          )}
        </div>
      )}
      {job.status === "failed" && job.error_message && <ErrorNote error={t("multiqc.failed", { error: job.error_message })} />}
      {expanded && summary && (
        <>
          {versions && <p className="text-xs text-muted-foreground">{t("multiqc.versions", { versions })}</p>}
          <GeneralStats summary={summary} />
        </>
      )}
      <JobDetails job={job} />
    </div>
  );
}

function JobDetails({ job }: { job: AnalysisJob }) {
  const t = useT();
  return (
    <details className="group text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
        <ChevronDown className="h-3.5 w-3.5 transition group-open:rotate-180" aria-hidden /> {t("multiqc.details")}
      </summary>
      <div className="mt-2 space-y-2">
        {job.commands?.map((c, i) => (
          <div key={i}>
            <div className="mb-1 text-muted-foreground">{t("multiqc.command")}</div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-2 text-[11px]">{shellJoin(c)}</pre>
          </div>
        ))}
        <div>
          <div className="mb-1 text-muted-foreground">{t("multiqc.log")}</div>
          <pre className="max-h-60 overflow-auto rounded-lg bg-arva-navy p-2 text-[11px] leading-relaxed text-slate-200">{job.log_text || "—"}</pre>
        </div>
      </div>
    </details>
  );
}

function GeneralStats({ summary }: { summary: MultiqcSummary }) {
  const t = useT();
  const [showAll, setShowAll] = useState(false);
  const stats = summary.general_stats;
  const groups = columnGroups(stats.columns, showAll);
  const columns = groups.flatMap((g) => g.columns);
  const definition = (c: MultiqcColumn) => {
    const key = DEFINITION_KEY[columnId(c)];
    return key ? t(key) : c.description;
  };
  const origin = (c: MultiqcColumn) => t(c.origin === "tool" ? "multiqc.origin.tool" : "multiqc.origin.multiqc", { tool: MODULE_NAME[c.module] });
  return (
    <section aria-labelledby="mqc-stats" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h5 id="mqc-stats" className="text-sm font-semibold">
          {t("multiqc.statsTitle")}
        </h5>
        <label className="flex items-center gap-1.5 text-xs">
          <input type="checkbox" className="h-4 w-4 accent-[#00B4A6]" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          {t("multiqc.showAll")}
        </label>
      </div>
      <p className="text-xs text-muted-foreground">{t("multiqc.statsNote")}</p>
      <div className="max-h-[420px] overflow-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr className="border-b">
              <th rowSpan={2} scope="col" className="px-2 py-1.5 text-left font-medium text-muted-foreground">
                {t("multiqc.sampleColumn")}
              </th>
              {groups.map((g) => (
                <th key={g.module} colSpan={g.columns.length} scope="colgroup" className="border-l px-2 py-1.5 text-left font-semibold">
                  {MODULE_NAME[g.module]}
                </th>
              ))}
            </tr>
            <tr className="border-b">
              {columns.map((c, i) => (
                <th
                  key={columnId(c)}
                  scope="col"
                  title={`${definition(c)} (${origin(c)})`}
                  className={cn("px-2 py-1.5 text-right align-bottom font-medium", (i === 0 || columns[i - 1].module !== c.module) && "border-l")}
                >
                  <span className="whitespace-nowrap">{columnTitle(c, t)}</span>
                  <span className="block whitespace-nowrap font-normal text-muted-foreground">
                    {t(UNIT_KEY[c.unit])}
                    {c.origin === "multiqc" && " · MultiQC"}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stats.rows.map((row) => (
              <tr key={row.name} className="border-b border-border/50">
                <th scope="row" className="whitespace-nowrap px-2 py-1.5 text-left font-medium">
                  {row.name}
                </th>
                {columns.map((c, i) => (
                  <td
                    key={columnId(c)}
                    className={cn("px-2 py-1.5 text-right tabular-nums", (i === 0 || columns[i - 1].module !== c.module) && "border-l")}
                  >
                    {formatStat(row.values[c.module]?.[c.key], c.unit)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("multiqc.definitions")}</summary>
        <dl className="mt-2 space-y-1.5">
          {columns.map((c) => (
            <div key={columnId(c)}>
              <dt className="font-medium">
                {MODULE_NAME[c.module]} · {columnTitle(c, t)} ({t(UNIT_KEY[c.unit])})
              </dt>
              <dd className="text-muted-foreground">
                {definition(c)} — {origin(c)}
              </dd>
            </div>
          ))}
        </dl>
      </details>
      {stats.unmapped.length > 0 && <p className="text-xs text-muted-foreground">{t("multiqc.unmapped", { columns: stats.unmapped.join(", ") })}</p>}
    </section>
  );
}
