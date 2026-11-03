import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { EChartsOption } from "echarts";
import { Ban, Download, FileText, GitBranch, GitCompareArrows, Loader2, Pause, Play, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChartCard } from "@/components/charts/ChartCard";
import { MetricTile } from "@/components/domain/bits";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { entryMessage } from "@/lib/diagnostics";
import { fmtDate, fmtDuration, fmtInt } from "@/lib/format";
import { messageText } from "@/lib/messages";
import { profileLabel } from "@/lib/performance";
import {
  ITEM_STATUSES,
  STATUS_COLOR,
  STATUS_GLYPH,
  STATUS_TONE,
  finishedShare,
  flyeGuardText,
  isActive,
  nodeProgress,
  nodeTools,
  type Catalogue,
  type ItemError,
  type RunDetail,
  type RunItem,
} from "@/lib/workflows";
import { resolveDark, useSettings } from "@/store/settings";
import { ParamPanel } from "./ParamPanel";
import { problemText } from "./WorkflowEditor";
import { NODE_TYPES, toFlow } from "./WorkflowCanvas";

export function itemErrorText(t: ReturnType<typeof useT>, e: ItemError): string {
  const job = messageText(t, "job.error", { code: e.code, params: e.params, text: "" });
  return job || messageText(t, "api.error", { code: e.code, params: e.params, text: e.message });
}

export function RunStatusBadge({ status }: { status: RunDetail["status"] }) {
  const t = useT();
  const tone = status === "completed" ? "success" : status === "completed_with_errors" ? "warning" : status === "cancelled" ? "danger" : "blue";
  return <Badge tone={tone}>{t(`wf.runStatus.${status}` as TranslationKey)}</Badge>;
}

/** One run: progress on the workflow graph, per sample and overall, the error summary (with the error log entries
 * of its jobs), the exports, queue controls and a new branch with changed parameters. */
export function RunView({ runId, catalogue }: { runId: string; catalogue: Catalogue }) {
  const t = useT();
  const language = useSettings((s) => s.language);
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["batch", runId],
    queryFn: () => api.batch(runId),
    refetchInterval: (q) => (q.state.data && isActive(q.state.data.status) ? 3000 : false),
  });
  const action = useMutation({
    mutationFn: (a: "cancel" | "pause" | "resume") => api.batchAction(runId, a),
    onSuccess: (d) => {
      queryClient.setQueryData(["batch", runId], d);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
  });
  const [branching, setBranching] = useState(false);
  const r = run.data;
  if (run.isLoading) return <Skeleton className="h-96" />;
  if (!r) return <ErrorNote error={run.error} />;
  const done = finishedShare(r.counts, r.total);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">{r.name} <RunStatusBadge status={r.status} /></h2>
          <p className="text-xs text-muted-foreground">
            {r.workflow_id ? <Link className="text-arva-royal hover:underline dark:text-arva-cyan" to={`/workflows/${r.workflow_id}`}>{r.workflow_name}</Link> : t("wf.deletedWorkflow")}
            {" "}{t("wf.versionShort", { v: r.version ?? "?" })} · {t("wf.createdAt", { date: fmtDate(r.created_at) })} ·{" "}
            <span className="font-mono">sha256 {r.definition_sha256.slice(0, 12)}…</span>
          </p>
          {r.parent_run_id && (
            <p className="mt-1 text-xs">
              <GitBranch className="mr-1 inline h-3.5 w-3.5" />
              <Link className="text-arva-royal hover:underline dark:text-arva-cyan" to={`/workflows/runs/${r.parent_run_id}`}>{t("wf.branchOf")}</Link>{" · "}
              <Link className="text-arva-royal hover:underline dark:text-arva-cyan" to={`/workflows/compare?a=${r.parent_run_id}&b=${r.id}`}>{t("wf.compareWithParent")}</Link>
            </p>
          )}
          {r.settings.option_changes?.length ? (
            <div className="mt-1 text-xs text-muted-foreground">
              <p>{t("wf.optionChanges")}</p>
              <ul>
                {r.settings.option_changes.map((c, i) => (
                  <li key={i} className="font-mono">{c.node}.{c.path}: {JSON.stringify(c.before)} → {JSON.stringify(c.after)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {r.branch_changes?.length ? (
            <ul className="mt-1 text-xs text-muted-foreground">
              {r.branch_changes.map((c, i) => (
                <li key={i} className="font-mono">{c.node}.{c.path}: {JSON.stringify(c.before)} → {JSON.stringify(c.after)}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {r.status === "running" && <Button variant="outline" onClick={() => action.mutate("pause")}><Pause className="h-4 w-4" /> {t("wf.pause")}</Button>}
          {(r.status === "paused" || r.counts.failed + r.counts.cancelled + r.counts.skipped > 0) && (
            <Button variant="outline" onClick={() => action.mutate("resume")} title={t("wf.resumeHint")}><Play className="h-4 w-4" /> {t("wf.resume")}</Button>
          )}
          {isActive(r.status) && (
            <Button variant="danger" onClick={() => window.confirm(t("wf.cancelConfirm")) && action.mutate("cancel")}><Ban className="h-4 w-4" /> {t("wf.cancelRun")}</Button>
          )}
          <Button variant="outline" onClick={() => setBranching(true)}><GitBranch className="h-4 w-4" /> {t("wf.newBranch")}</Button>
          <a href={api.batchTableUrl(r.id)} download className={buttonClass("outline")}><Table2 className="h-4 w-4" /> {t("wf.exportCsv")}</a>
          <a href={api.batchExportUrl(r.id)} download className={buttonClass("outline")}><Download className="h-4 w-4" /> {t("wf.exportRun")}</a>
          <a href={api.batchReportUrl(r.id, language)} target="_blank" rel="noreferrer noopener" className={buttonClass("outline")}><FileText className="h-4 w-4" /> {t("wf.report")}</a>
        </div>
      </div>
      <ErrorNote error={action.error} />
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <MetricTile label={t("wf.tile.progress")} value={`${Math.round(done * 100)} %`} sub={t("wf.tile.steps", { done: r.counts.completed, total: r.total })} />
        <MetricTile label={t("wf.tile.running")} value={fmtInt(r.counts.running + r.counts.queued)} sub={t("wf.tile.waiting", { n: r.counts.waiting })} />
        <MetricTile label={t("wf.tile.failed")} value={fmtInt(r.counts.failed)} sub={t("wf.tile.skipped", { n: r.counts.skipped })} />
        <MetricTile label={t("wf.tile.jobs")} value={fmtInt(r.jobs_created)} sub={t("wf.tile.reused", { n: r.reused })} />
        <MetricTile label={t("wf.tile.time")} value={fmtDuration(r.job_seconds)} sub={t("wf.tile.timeHint")} />
        <MetricTile label={t("wf.tile.resources")} value={t("wf.tile.resourcesValue", { threads: r.estimated.threads_per_job, memory: r.estimated.memory_per_job_gb })}
          sub={t("wf.tile.concurrency", { n: r.estimated.concurrency })} />
      </div>
      <QueueSettings run={r} />
      <Card>
        <CardHeader title={t("wf.graphProgress")} description={t("wf.graphProgressHint")} />
        <CardBody className="pt-3">
          <ReactFlowProvider><RunGraph run={r} catalogue={catalogue} /></ReactFlowProvider>
        </CardBody>
      </Card>
      <SampleGrid run={r} />
      <SampleTimes run={r} />
      <ErrorSummary run={r} />
      {branching && <BranchDialog open={branching} onOpenChange={setBranching} run={r} catalogue={catalogue} />}
    </div>
  );
}

function QueueSettings({ run }: { run: RunDetail }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [priority, setPriority] = useState(run.priority);
  const [concurrent, setConcurrent] = useState(run.settings.max_concurrent);
  useEffect(() => {
    setPriority(run.priority);
    setConcurrent(run.settings.max_concurrent);
  }, [run.priority, run.settings.max_concurrent]);
  const save = useMutation({
    mutationFn: () => api.batchSettings(run.id, { priority, max_concurrent: concurrent }),
    onSuccess: (d) => queryClient.setQueryData(["batch", run.id], d),
  });
  if (!isActive(run.status)) return null;
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border px-3 py-2 text-xs">
      <Field label={t("wf.priority")} className="w-28"><Input className="h-8" type="number" min={-10} max={10} value={priority} onChange={(e) => setPriority(Number(e.target.value))} /></Field>
      <Field label={t("wf.maxConcurrent")} className="w-36"><Input className="h-8" type="number" min={1} max={64} value={concurrent} onChange={(e) => setConcurrent(Number(e.target.value) || 1)} /></Field>
      <Button size="sm" variant="outline" onClick={() => save.mutate()} disabled={save.isPending || (priority === run.priority && concurrent === run.settings.max_concurrent)}>{t("wf.applySettings")}</Button>
      <p className="text-muted-foreground">{t("wf.retriesLine", { n: run.settings.max_retries })} · {t("batch.workersNote")}</p>
      <ErrorNote error={save.error} />
    </div>
  );
}

function RunGraph({ run, catalogue }: { run: RunDetail; catalogue: Catalogue }) {
  const theme = useSettings((s) => s.theme);
  const kinds = useMemo(() => new Map(catalogue.kinds.map((k) => [k.kind, k])), [catalogue]);
  const flow = useMemo(() => {
    const f = toFlow(run.definition, kinds, [], (n, k) => nodeTools(k, n.params));
    const progress = nodeProgress(run.items);
    for (const n of f.nodes) {
      n.data.progress = progress.get(n.id) ?? null;
      n.data.reused = run.items.filter((i) => i.node_id === n.id && i.reused_from_item_id).length;
      n.draggable = false;
    }
    return f;
  }, [run, kinds]);
  return (
    <div className="h-[460px] rounded-lg border">
      <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={NODE_TYPES} nodesConnectable={false} elementsSelectable={false}
        colorMode={resolveDark(theme) ? "dark" : "light"} fitView proOptions={{ hideAttribution: true }}>
        <Background gap={16} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function StatusCell({ item }: { item: RunItem | undefined }) {
  const t = useT();
  if (!item) return <td className="px-1 py-1 text-center text-muted-foreground">—</td>;
  const title = [t(`wf.status.${item.status}` as TranslationKey), item.tool && `${item.tool} ${item.tool_version ?? ""}`,
    item.duration_seconds != null && fmtDuration(item.duration_seconds), item.error && itemErrorText(t, item.error),
    flyeGuardText(t, item.notes?.flye_memory)].filter(Boolean).join(" · ");
  return (
    <td className="px-1 py-1 text-center">
      <span tabIndex={0} role="img" aria-label={title} title={title}
        className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-sm align-middle text-[9px] font-bold leading-none text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        style={{ background: STATUS_COLOR[item.status], opacity: item.reused_from_item_id ? 0.55 : 1 }}>
        <span aria-hidden>{STATUS_GLYPH[item.status]}</span>
      </span>
      {item.attempt > 1 && <span className="ml-0.5 text-[9px] text-muted-foreground">×{item.attempt}</span>}
    </td>
  );
}

function SampleGrid({ run }: { run: RunDetail }) {
  const t = useT();
  const nodes = run.definition.nodes.filter((n) => run.items.some((i) => i.node_id === n.id && i.sample_id));
  const setNodes = run.definition.nodes.filter((n) => run.items.some((i) => i.node_id === n.id && !i.sample_id));
  const byKey = new Map(run.items.map((i) => [`${i.node_id}|${i.sample_id ?? ""}`, i]));
  return (
    <Card>
      <CardHeader title={t("wf.perSample")} description={t("wf.perSampleHint")} />
      <CardBody className="overflow-x-auto pt-3">
        <table className="text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-2 py-1 text-left">{t("wf.sample")}</th>
              {nodes.map((n) => <th key={n.id} className="px-1 py-1 font-mono text-[10px]">{n.id}</th>)}
              <th className="px-2 py-1 text-right">{t("wf.completed")}</th>
              <th className="px-2 py-1 text-right">{t("wf.jobTime")}</th>
            </tr>
          </thead>
          <tbody>
            {run.per_sample.map((s) => (
              <tr key={s.sample_id} className="border-t">
                <td className="px-2 py-1"><Link className="text-arva-royal hover:underline dark:text-arva-cyan" to={`/samples/${s.sample_id}`}>{s.sample_code}</Link></td>
                {nodes.map((n) => <StatusCell key={n.id} item={byKey.get(`${n.id}|${s.sample_id}`)} />)}
                <td className="px-2 py-1 text-right">{s.counts.completed}/{s.total}</td>
                <td className="px-2 py-1 text-right">{fmtDuration(s.seconds)}</td>
              </tr>
            ))}
            {setNodes.length > 0 && (
              <tr className="border-t">
                <td className="px-2 py-1 text-muted-foreground">{t("wf.setSteps")}</td>
                <td colSpan={nodes.length + 2} className="px-2 py-1">
                  {setNodes.map((n) => {
                    const i = byKey.get(`${n.id}|`);
                    return i ? (
                      <span key={n.id} className="mr-3 inline-flex items-center gap-1">
                        <span className="inline-block h-3 w-3 rounded-sm" style={{ background: STATUS_COLOR[i.status] }} />
                        <span className="font-mono">{n.id}</span> {t(`wf.status.${i.status}` as TranslationKey)}
                      </span>
                    ) : null;
                  })}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <p className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          {ITEM_STATUSES.map((s) => (
            <span key={s} className="inline-flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: STATUS_COLOR[s] }} />{t(`wf.status.${s}` as TranslationKey)}</span>
          ))}
          <span>{t("wf.reusedLegend")}</span>
        </p>
      </CardBody>
    </Card>
  );
}

function SampleTimes({ run }: { run: RunDetail }) {
  const t = useT();
  const nodes = run.definition.nodes.filter((n) => run.items.some((i) => i.node_id === n.id && i.sample_id && i.duration_seconds != null));
  if (!nodes.length) return null;
  const codes = run.per_sample.map((s) => s.sample_code ?? s.sample_id);
  const option: EChartsOption = {
    tooltip: { trigger: "axis" },
    legend: { type: "scroll", top: 0 },
    grid: { left: 60, right: 16, top: 36, bottom: 40 },
    xAxis: { type: "category", data: codes },
    yAxis: { type: "value", name: t("wf.seconds") },
    series: nodes.map((n) => ({
      name: n.id,
      type: "bar",
      stack: "time",
      data: run.per_sample.map((s) => run.items.find((i) => i.node_id === n.id && i.sample_id === s.sample_id)?.duration_seconds ?? 0),
    })),
  };
  return (
    <ChartCard title={t("wf.timesTitle")} subtitle={t("wf.timesHint")} option={option} filePrefix={`arva-run-${run.id.slice(0, 8)}-times`}
      table={{ columns: [t("wf.sample"), ...nodes.map((n) => n.id)], rows: run.per_sample.map((s) => [s.sample_code ?? "", ...nodes.map((n) => run.items.find((i) => i.node_id === n.id && i.sample_id === s.sample_id)?.duration_seconds ?? "")]) }} />
  );
}

function ErrorSummary({ run }: { run: RunDetail }) {
  const t = useT();
  const log = useQuery({ queryKey: ["batchErrors", run.id, run.counts.failed], queryFn: () => api.batchErrors(run.id), enabled: run.errors.length > 0 });
  if (!run.errors.length) return null;
  const byCode = new Map<string, number>();
  for (const e of run.errors) byCode.set(e.code, (byCode.get(e.code) ?? 0) + 1);
  return (
    <Card>
      <CardHeader title={t("wf.errorsTitle", { n: run.errors.length })} description={t("wf.errorsHint")} />
      <CardBody className="space-y-3 pt-3 text-xs">
        <p className="flex flex-wrap gap-2">
          {[...byCode].map(([code, n]) => <Badge key={code} tone="danger" className="font-mono">{code} × {n}</Badge>)}
        </p>
        <table className="w-full">
          <thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("wf.sample")}</th><th>{t("wf.step")}</th><th>{t("wf.statusCol")}</th><th>{t("wf.reason")}</th><th>{t("wf.job")}</th></tr></thead>
          <tbody>
            {run.errors.map((e) => (
              <tr key={e.item_id} className="border-t align-top">
                <td className="py-1 pr-2">{e.sample_code ?? t("wf.setScope")}</td>
                <td className="pr-2 font-mono">{e.node_id}</td>
                <td className="pr-2"><Badge tone={STATUS_TONE[e.status]}>{t(`wf.status.${e.status}` as TranslationKey)}</Badge></td>
                <td className="pr-2">{itemErrorText(t, e)}</td>
                <td className="font-mono">{e.job_id && e.sample_id ? <Link className="text-arva-royal hover:underline dark:text-arva-cyan" to={`/samples/${e.sample_id}`}>{e.job_id.slice(0, 8)}</Link> : e.job_id?.slice(0, 8) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div>
          <p className="mb-1 font-medium">{t("wf.errorLog")}</p>
          {log.isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
          {log.data?.length === 0 && <p className="text-muted-foreground">{t("wf.errorLogEmpty")}</p>}
          <ul className="space-y-0.5">
            {log.data?.map((e) => (
              <li key={e.id}><span className="font-mono">{e.id}</span> · {fmtDate(e.time)} · {entryMessage(t, e)}</li>
            ))}
          </ul>
          <Link to="/settings" className="text-arva-royal hover:underline dark:text-arva-cyan">{t("wf.openDiagnostics")}</Link>
        </div>
      </CardBody>
    </Card>
  );
}

/** A new run with one step's parameters changed: the steps before it reuse this run's results; the step and
 * everything after it run again as new jobs. This run is not changed. Like a new run, it is shown first (what runs
 * again, how many jobs, the resources, the tools and what blocks it) and created only after a confirmation that any
 * later parameter change clears. */
function BranchDialog({ open, onOpenChange, run, catalogue }: { open: boolean; onOpenChange: (o: boolean) => void; run: RunDetail; catalogue: Catalogue }) {
  const t = useT();
  const queryClient = useQueryClient();
  const editable = run.definition.nodes.filter((n) => !catalogue.kinds.find((k) => k.kind === n.kind)?.source);
  const [nodeId, setNodeId] = useState(editable[0]?.id ?? "");
  const node = run.definition.nodes.find((n) => n.id === nodeId);
  const kind = catalogue.kinds.find((k) => k.kind === node?.kind);
  const [params, setParams] = useState<Record<string, unknown>>(node?.params ?? {});
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    setParams(node?.params ?? {});
  }, [nodeId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setConfirmed(false), [nodeId, params]);
  const preview = useQuery({
    queryKey: ["branchPreview", run.id, nodeId, params],
    queryFn: () => api.branchPreview(run.id, { node_id: nodeId, params }),
    enabled: open && Boolean(nodeId),
  });
  const p = preview.data;
  const blocked = !p || preview.isFetching || p.problems.length > 0 || p.changes.length === 0;
  const branch = useMutation({
    mutationFn: () => api.branchBatch(run.id, { node_id: nodeId, params, confirmed }),
    onSuccess: (d) => {
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      onOpenChange(false);
      window.location.assign(`/workflows/runs/${d.id}`);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("wf.newBranch")} description={t("wf.branchHint")} className="max-w-2xl">
      <div className="space-y-3 text-sm">
        <Field label={t("wf.step")}>
          <Select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
            {editable.map((n) => <option key={n.id} value={n.id}>{n.id} · {t(`wf.kind.${n.kind}` as TranslationKey)}</option>)}
          </Select>
        </Field>
        {kind && <div className="max-h-80 overflow-y-auto rounded-lg border p-3"><ParamPanel kind={kind} params={params} problems={p?.problems.filter((x) => x.node === nodeId) ?? []} onChange={setParams} /></div>}
        {preview.isFetching && <Loader2 className="h-4 w-4 animate-spin" aria-label={t("common.loading")} />}
        <ErrorNote error={preview.error} />
        {p && (
          <section className="space-y-2 rounded-lg border bg-muted/30 p-3 text-xs" aria-live="polite">
            {p.changes.length === 0 ? (
              <p className="text-amber-700 dark:text-warning">{t("wf.branchNoChange")}</p>
            ) : (
              <>
                <p>{t("wf.branchPlanLine", { steps: p.rerun.length, samples: p.samples, jobs: p.jobs, concurrency: p.concurrency })}</p>
                <p className="text-muted-foreground">{t("wf.branchRerun", { steps: p.rerun.map((r) => r.node).join(", ") })}</p>
                {p.reused.length > 0 && <p className="text-muted-foreground">{t("wf.branchReused", { steps: p.reused.join(", ") })}</p>}
                <p className="text-muted-foreground">
                  {t("wf.budgetLine", { threads: p.settings.threads_per_job, memory: p.settings.memory_per_job_gb, budgetThreads: p.settings.budget_threads, budgetMemory: p.settings.budget_memory_gb, profile: profileLabel(t, p.settings.profile) })}
                </p>
                <p className="text-muted-foreground">{Object.values(p.tools).map((x) => `${x.name} ${x.version ?? "?"}`).join(" · ")}</p>
              </>
            )}
            {p.problems.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-5 text-danger">
                {p.problems.map((x, i) => <li key={i}>{x.node ? `${x.node}: ` : ""}{problemText(t, x)}</li>)}
              </ul>
            )}
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-0.5 accent-arva-teal" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={blocked} />
              <span>{t("wf.branchConfirm")}</span>
            </label>
          </section>
        )}
        <ErrorNote error={branch.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => branch.mutate()} disabled={!confirmed || blocked || branch.isPending}><GitCompareArrows className="h-4 w-4" /> {t("wf.createBranch")}</Button>
        </div>
      </div>
    </Dialog>
  );
}
