import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Ban, GitBranch, Layers, Plus, Upload, Workflow as WorkflowIcon } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChartCard } from "@/components/charts/ChartCard";
import { MetricTile } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorNote, PageHeader, Skeleton, Tabs } from "@/components/ui/misc";
import { RunCompare } from "@/components/workflows/RunCompare";
import { RunStatusBadge, RunView } from "@/components/workflows/RunView";
import { WorkflowEditor, problemText } from "@/components/workflows/WorkflowEditor";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtDuration } from "@/lib/format";
import { ITEM_STATUSES, STATUS_COLOR, finishedShare, isActive, type Catalogue, type RunSummary, type Template } from "@/lib/workflows";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";

function useCatalogue() {
  return useQuery({ queryKey: ["workflowCatalogue"], queryFn: api.workflowCatalogue, staleTime: 60_000 });
}

/** Workflows (spec §25) and batch runs (§27): saved workflows, the predefined ones, the queue and every run. */
export function WorkflowsPage() {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "workflows" | "runs") ?? "workflows";
  const catalogue = useCatalogue();
  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader title={t("nav.workflows")} subtitle={t("wf.subtitle")} actions={<Explain id={tab === "runs" ? "batch_queue" : "workflow_builder"} />} />
      <Tabs value={tab} onChange={(v) => setParams({ tab: v })} items={[{ value: "workflows", label: t("wf.tabWorkflows") }, { value: "runs", label: t("wf.tabRuns") }]} />
      {catalogue.isLoading && <Skeleton className="h-64" />}
      <ErrorNote error={catalogue.error} />
      {catalogue.data && (tab === "runs" ? <BatchDashboard /> : <WorkflowList catalogue={catalogue.data} />)}
    </div>
  );
}

function WorkflowList({ catalogue }: { catalogue: Catalogue }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: api.workflows });
  const [creating, setCreating] = useState<Template | "blank" | null>(null);
  const [importError, setImportError] = useState<unknown>(null);
  const file = useRef<HTMLInputElement>(null);
  const importFile = async (f: File) => {
    try {
      const wf = await api.importWorkflow(f.name.replace(/\.json$/i, "").replace(/\.arva-workflow$/i, ""), JSON.parse(await f.text()));
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      navigate(`/workflows/${wf.id}`);
    } catch (e) {
      setImportError(e);
    }
  };
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_420px]">
      <Card>
        <CardHeader title={t("wf.saved")} description={t("wf.savedHint")}
          action={
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => file.current?.click()}><Upload className="h-4 w-4" /> {t("wf.import")}</Button>
              <Button onClick={() => setCreating("blank")}><Plus className="h-4 w-4" /> {t("wf.new")}</Button>
              <input ref={file} type="file" accept=".json,application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
            </div>
          } />
        <CardBody className="pt-3">
          <ErrorNote error={workflows.error ?? importError} />
          {workflows.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("wf.noneSaved")}</p>}
          <table className="w-full text-sm">
            <tbody>
              {workflows.data?.map((w) => (
                <tr key={w.id} className="border-t">
                  <td className="py-2"><Link className={`font-medium ${LINK}`} to={`/workflows/${w.id}`}>{w.name}</Link>
                    {w.template_key && <span className="ml-2 text-xs text-muted-foreground">{t(`wf.template.${w.template_key}` as TranslationKey)}</span>}</td>
                  <td className="text-xs text-muted-foreground">{t("wf.versionShort", { v: w.latest?.version ?? 0 })}</td>
                  <td className="text-xs text-muted-foreground">{t("wf.runsCount", { n: w.runs })}</td>
                  <td className="text-xs">{w.problems.length ? <Badge tone="warning">{t("wf.problemsCount", { n: w.problems.length })}</Badge> : <Badge tone="success">{t("wf.ready")}</Badge>}</td>
                  <td className="text-right text-xs text-muted-foreground">{fmtDate(w.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("wf.predefined")} description={t("wf.predefinedHint")} />
        <CardBody className="space-y-2 pt-3">
          {catalogue.templates.map((tp) => (
            <div key={tp.key} className="rounded-lg border p-2.5 text-xs">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{t(`wf.template.${tp.key}` as TranslationKey)}</p>
                  <p className="text-muted-foreground">{t(`wf.templateHint.${tp.key}` as TranslationKey)}</p>
                </div>
                <Button size="sm" variant="outline" onClick={() => setCreating(tp)}><Plus className="h-3.5 w-3.5" /> {t("wf.use")}</Button>
              </div>
              {tp.unavailable.length > 0 && (
                <p className="mt-1 flex items-start gap-1 text-danger"><Ban className="mt-0.5 h-3 w-3 shrink-0" />
                  {t("wf.templateUnavailable", { tools: [...new Set(tp.unavailable.map((p) => String(p.params.tool)))].join(", ") })}</p>
              )}
              {tp.needs_parameters.length > 0 && (
                <p className="mt-1 text-amber-700 dark:text-warning">{t("wf.templateNeeds", { fields: tp.needs_parameters.map((p) => `${p.node}.${p.params.field}`).join(", ") })}</p>
              )}
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground">{t("wf.nextflowNote")}</p>
        </CardBody>
      </Card>
      {creating && <CreateDialog template={creating === "blank" ? null : creating} onClose={() => setCreating(null)} />}
    </div>
  );
}

function CreateDialog({ template, onClose }: { template: Template | null; onClose: () => void }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState(template ? t(`wf.template.${template.key}` as TranslationKey) : "");
  const create = useMutation({
    mutationFn: () => api.createWorkflow(template
      ? { name, template_key: template.key }
      : { name, definition: { format: "arva-workflow", format_version: 1, nodes: [{ id: "reads_short_input_1", kind: "reads_short_input", params: {}, position: { x: 40, y: 40 } }], edges: [] } }),
    onSuccess: (wf) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      navigate(`/workflows/${wf.id}`);
    },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("wf.new")} description={template ? t(`wf.templateHint.${template.key}` as TranslationKey) : t("wf.newBlankHint")}>
      <div className="space-y-3">
        <Field label={t("wf.name")}><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <ErrorNote error={create.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}><Plus className="h-4 w-4" /> {t("wf.create")}</Button>
        </div>
      </div>
    </Dialog>
  );
}

function BatchDashboard() {
  const t = useT();
  const navigate = useNavigate();
  const [project, setProject] = useState("");
  const [pick, setPick] = useState<string[]>([]);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const runs = useQuery({ queryKey: ["batches", project], queryFn: () => api.batches(project || undefined), refetchInterval: 5000 });
  const queue = useQuery({ queryKey: ["batchQueue"], queryFn: api.batchQueue, refetchInterval: 5000 });
  const q = queue.data;
  const active = (runs.data ?? []).filter((r) => isActive(r.status));
  const option: EChartsOption | null = active.length
    ? {
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        legend: { top: 0 },
        grid: { left: 16, right: 24, top: 30, bottom: 36, containLabel: true },
        xAxis: { type: "value", name: t("wf.steps"), nameLocation: "middle", nameGap: 26, minInterval: 1 },
        yAxis: { type: "category", data: active.map((r) => r.name), axisLabel: { width: 240, overflow: "truncate" } },
        series: ITEM_STATUSES.map((s) => ({ name: t(`wf.status.${s}` as TranslationKey), type: "bar", stack: "s", itemStyle: { color: STATUS_COLOR[s] }, data: active.map((r) => r.counts[s]) })),
      }
    : null;
  return (
    <div className="space-y-5">
      {q && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <MetricTile label={t("batch.activeRuns")} value={q.active_runs} />
          <MetricTile label={t("batch.inQueue")} value={q.counts.queued + q.counts.running} sub={t("wf.tile.waiting", { n: q.counts.waiting })} />
          <MetricTile label={t("wf.tile.failed")} value={q.counts.failed} />
          <MetricTile label={t("batch.threads")} value={`${q.reserved_threads} / ${q.budget_threads}`} sub={t("batch.profile", { profile: q.profile })} explain="batch_queue" />
          <MetricTile label={t("batch.memory")} value={`${q.reserved_memory_gb} / ${q.budget_memory_gb} GB`} sub={t("batch.estimate")} />
        </div>
      )}
      <p className="text-xs text-muted-foreground">{t("batch.workersNote")}</p>
      {option && <ChartCard title={t("batch.globalProgress")} subtitle={t("batch.globalProgressHint")} option={option} height={Math.max(170, 52 + active.length * 36)} filePrefix="arva-batch-progress"
        table={{ columns: [t("wf.run"), ...ITEM_STATUSES.map((s) => t(`wf.status.${s}` as TranslationKey))], rows: active.map((r) => [r.name, ...ITEM_STATUSES.map((s) => r.counts[s])]) }} />}
      <Card>
        <CardHeader title={t("batch.runs")} description={t("batch.runsHint")}
          action={
            <div className="flex items-end gap-2">
              <Select className="h-9 w-56 text-xs" value={project} onChange={(e) => setProject(e.target.value)} aria-label={t("wf.project")}>
                <option value="">{t("batch.allProjects")}</option>
                {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
              <Button variant="outline" disabled={pick.length !== 2} onClick={() => navigate(`/workflows/compare?a=${pick[0]}&b=${pick[1]}`)}>
                <Layers className="h-4 w-4" /> {t("batch.compareTwo")}
              </Button>
            </div>
          } />
        <CardBody className="overflow-x-auto pt-3">
          <ErrorNote error={runs.error} />
          {runs.data?.length === 0 && <EmptyState icon={<WorkflowIcon className="h-7 w-7" />} title={t("batch.noRuns")}>{t("batch.noRunsHint")}</EmptyState>}
          {!!runs.data?.length && <RunTable runs={runs.data} pick={pick} setPick={setPick} />}
        </CardBody>
      </Card>
    </div>
  );
}

function RunTable({ runs, pick, setPick }: { runs: RunSummary[]; pick: string[]; setPick: (p: string[]) => void }) {
  const t = useT();
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="py-1" />
          <th>{t("wf.run")}</th><th>{t("wf.statusCol")}</th><th>{t("wf.priority")}</th><th>{t("wf.samples")}</th>
          <th>{t("wf.progressCol")}</th><th>{t("wf.tile.failed")}</th><th>{t("wf.jobTime")}</th><th>{t("wf.created")}</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const share = finishedShare(r.counts, r.total);
          return (
            <tr key={r.id} className="border-t">
              <td className="py-1.5 pr-2"><input type="checkbox" className="accent-arva-teal" checked={pick.includes(r.id)} aria-label={t("batch.pickToCompare")}
                onChange={(e) => setPick(e.target.checked ? [...pick, r.id].slice(-2) : pick.filter((x) => x !== r.id))} /></td>
              <td className="pr-2">
                <Link className={LINK} to={`/workflows/runs/${r.id}`}>{r.name}</Link>
                {r.parent_run_id && <GitBranch className="ml-1 inline h-3 w-3 text-muted-foreground" aria-label={t("wf.branchOf")} />}
              </td>
              <td className="pr-2"><RunStatusBadge status={r.status} /></td>
              <td className="pr-2">{r.priority}</td>
              <td className="pr-2">{r.samples}</td>
              <td className="w-48 pr-2">
                <div className="flex h-2 overflow-hidden rounded-full bg-muted">
                  {ITEM_STATUSES.filter((s) => r.counts[s] > 0).map((s) => <div key={s} style={{ width: `${(100 * r.counts[s]) / r.total}%`, background: STATUS_COLOR[s] }} />)}
                </div>
                <span className="text-[10px] text-muted-foreground">{t("wf.tile.steps", { done: r.counts.completed, total: r.total })} · {Math.round(share * 100)} %</span>
              </td>
              <td className={`pr-2 ${r.counts.failed ? "text-danger" : ""}`}>{r.counts.failed}</td>
              <td className="pr-2">{fmtDuration(r.job_seconds)}</td>
              <td className="text-muted-foreground">{fmtDate(r.created_at)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function WorkflowEditorPage() {
  const t = useT();
  const { workflowId } = useParams();
  const [params] = useSearchParams();
  const version = params.get("version") ? Number(params.get("version")) : undefined;
  const catalogue = useCatalogue();
  const wf = useQuery({ queryKey: ["workflow", workflowId, version], queryFn: () => api.workflow(workflowId!, version) });
  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader title={wf.data?.name ?? t("nav.workflows")} subtitle={t("wf.editorSubtitle")}
        actions={<><Explain id="workflow_builder" /><Link className={`text-sm ${LINK}`} to="/workflows">{t("wf.backToList")}</Link></>} />
      {(wf.isLoading || catalogue.isLoading) && <Skeleton className="h-96" />}
      <ErrorNote error={wf.error ?? catalogue.error} />
      {wf.data && catalogue.data && <WorkflowEditor key={`${wf.data.id}-${version ?? "latest"}-${wf.data.latest?.version}`} workflow={wf.data} catalogue={catalogue.data} version={version} />}
      {wf.data && wf.data.problems.length > 0 && !version && (
        <p className="text-xs text-muted-foreground">{t("wf.savedProblems", { list: wf.data.problems.slice(0, 3).map((p) => problemText(t, p)).join("; ") })}</p>
      )}
    </div>
  );
}

export function RunPage() {
  const t = useT();
  const { runId } = useParams();
  const catalogue = useCatalogue();
  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader title={t("wf.runPageTitle")} subtitle={t("wf.runPageSubtitle")}
        actions={<><Explain id="batch_queue" /><Link className={`text-sm ${LINK}`} to="/workflows?tab=runs">{t("wf.backToRuns")}</Link></>} />
      <ErrorNote error={catalogue.error} />
      {catalogue.data && runId && <RunView runId={runId} catalogue={catalogue.data} />}
    </div>
  );
}

export function ComparePage() {
  const t = useT();
  const [params] = useSearchParams();
  const a = params.get("a");
  const b = params.get("b");
  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader title={t("wf.compareTitle")} subtitle={t("wf.compareSubtitle")}
        actions={<Link className={`text-sm ${LINK}`} to="/workflows?tab=runs">{t("wf.backToRuns")}</Link>} />
      {a && b ? <RunCompare a={a} b={b} /> : <EmptyState title={t("wf.compareChoose")} />}
    </div>
  );
}
