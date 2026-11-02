import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Play, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { messageText } from "@/lib/messages";
import type { BatchRunRequest, BatchSettings, WorkflowRead } from "@/lib/workflows";
import { problemText } from "./WorkflowEditor";

const DEFAULTS: BatchSettings = { priority: 0, max_concurrent: 1, threads_per_job: null, memory_per_job_gb: null, max_retries: 0 };

/** Run a saved workflow version over samples of one project: the queue settings, what each sample's sources pick
 * (or why they cannot), the jobs and the estimated resources; nothing starts until the summary is confirmed. */
export function RunDialog({ open, onOpenChange, workflow }: { open: boolean; onOpenChange: (o: boolean) => void; workflow: WorkflowRead }) {
  const t = useT();
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [settings, setSettings] = useState<BatchSettings>(DEFAULTS);
  const [name, setName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: open });
  const samples = useQuery({ queryKey: ["samples", projectId], queryFn: () => api.samples(projectId), enabled: Boolean(projectId) });
  useEffect(() => {
    if (!projectId && projects.data?.length) setProjectId(projects.data[0].id);
  }, [projects.data, projectId]);
  useEffect(() => setChosen((samples.data ?? []).map((s) => s.id)), [samples.data]);
  useEffect(() => setConfirmed(false), [projectId, chosen, settings]);
  const body: BatchRunRequest = { project_id: projectId, workflow_id: workflow.id, version: workflow.latest?.version, sample_ids: chosen, name: name || null, settings, confirmed };
  const plan = useQuery({
    queryKey: ["batchPreview", body.project_id, body.sample_ids, settings, workflow.latest?.version],
    queryFn: () => api.batchPreview({ ...body, confirmed: false }),
    enabled: open && Boolean(projectId) && chosen.length > 0,
    retry: false,
  });
  const start = useMutation({
    mutationFn: () => api.startBatch(body),
    onSuccess: (run) => {
      onOpenChange(false);
      navigate(`/workflows/runs/${run.id}`);
    },
  });
  const num = (v: string) => (v === "" ? null : Number(v));
  const p = plan.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("wf.runTitle", { name: workflow.name })} description={t("wf.runDescription")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("wf.project")}>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              {projects.data?.map((pr) => <option key={pr.id} value={pr.id}>{pr.name}</option>)}
            </Select>
          </Field>
          <Field label={t("wf.runName")}>
            <Input value={name} placeholder={t("wf.runNamePlaceholder", { name: workflow.name, v: workflow.latest?.version ?? 1 })} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <span className="font-medium text-muted-foreground">{t("wf.samplesChosen", { n: chosen.length, total: samples.data?.length ?? 0 })}</span>
            <span className="space-x-2">
              <button type="button" className="text-arva-royal hover:underline dark:text-arva-cyan" onClick={() => setChosen((samples.data ?? []).map((s) => s.id))}>{t("wf.all")}</button>
              <button type="button" className="text-arva-royal hover:underline dark:text-arva-cyan" onClick={() => setChosen([])}>{t("wf.none")}</button>
            </span>
          </div>
          <div className="grid max-h-36 grid-cols-2 gap-1 overflow-y-auto rounded-lg border p-2 text-xs sm:grid-cols-3">
            {samples.data?.map((s) => (
              <label key={s.id} className="flex items-center gap-1.5">
                <input type="checkbox" className="accent-arva-teal" checked={chosen.includes(s.id)}
                  onChange={(e) => setChosen((c) => (e.target.checked ? [...c, s.id] : c.filter((x) => x !== s.id)))} />
                {s.sample_code}
              </label>
            ))}
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-5">
          <Field label={t("wf.priority")} hint={t("wf.priorityHint")}>
            <Input type="number" min={-10} max={10} value={settings.priority} onChange={(e) => setSettings({ ...settings, priority: Number(e.target.value) })} />
          </Field>
          <Field label={t("wf.maxConcurrent")}>
            <Input type="number" min={1} max={64} value={settings.max_concurrent} onChange={(e) => setSettings({ ...settings, max_concurrent: Number(e.target.value) || 1 })} />
          </Field>
          <Field label={t("wf.threadsPerJob")} hint={p ? t("wf.defaultValue", { v: p.settings.threads_per_job }) : undefined}>
            <Input type="number" min={1} value={settings.threads_per_job ?? ""} placeholder={t("wf.profileDefault")} onChange={(e) => setSettings({ ...settings, threads_per_job: num(e.target.value) })} />
          </Field>
          <Field label={t("wf.memoryPerJob")} hint={p ? t("wf.defaultValue", { v: p.settings.memory_per_job_gb }) : undefined}>
            <Input type="number" min={1} value={settings.memory_per_job_gb ?? ""} placeholder={t("wf.profileDefault")} onChange={(e) => setSettings({ ...settings, memory_per_job_gb: num(e.target.value) })} />
          </Field>
          <Field label={t("wf.retries")} hint={t("wf.retriesHint")}>
            <Input type="number" min={0} max={3} value={settings.max_retries} onChange={(e) => setSettings({ ...settings, max_retries: Number(e.target.value) || 0 })} />
          </Field>
        </div>
        {plan.isFetching && <Loader2 className="h-4 w-4 animate-spin" />}
        <ErrorNote error={plan.error} />
        {p && (
          <section className="space-y-2 rounded-lg border bg-muted/30 p-3 text-xs">
            <p>{t("wf.planLine", { ready: p.ready_samples, total: p.samples.length, jobs: p.jobs, concurrency: p.concurrency })}</p>
            <p className="text-muted-foreground">
              {t("wf.budgetLine", { threads: p.settings.threads_per_job, memory: p.settings.memory_per_job_gb, budgetThreads: p.settings.budget_threads, budgetMemory: p.settings.budget_memory_gb, profile: p.settings.profile })}
            </p>
            <p className="text-muted-foreground">{Object.values(p.tools).map((x) => `${x.name} ${x.version ?? "?"}`).join(" · ")}</p>
            <table className="w-full">
              <tbody>
                {p.samples.map((s) => (
                  <tr key={s.sample_id} className="border-t align-top">
                    <td className="py-1 pr-2 font-medium">{s.sample_code}</td>
                    <td className="py-1">
                      {Object.entries(s.sources).map(([node, pick]) => (
                        <p key={node} className="flex items-start gap-1">
                          {pick.ok ? <CheckCircle2 className="mt-0.5 h-3 w-3 text-success" /> : <XCircle className="mt-0.5 h-3 w-3 text-danger" />}
                          <span className="font-mono">{node}</span>
                          <span className="text-muted-foreground">
                            {pick.ok ? t("wf.sourceOk") : messageText(t, "api.error", { code: pick.code ?? "", params: pick.params ?? {}, text: pick.message ?? "" })}
                          </span>
                        </p>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {p.samples.some((s) => !s.ready) && <p className="text-amber-700 dark:text-warning">{t("wf.notReadyNote")}</p>}
            {p.problems.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-5 text-danger">
                {p.problems.map((x, i) => <li key={i}>{x.node ? `${x.node}: ` : ""}{problemText(t, x)}</li>)}
              </ul>
            )}
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-0.5 accent-arva-teal" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={p.problems.length > 0} />
              <span>{t("wf.confirm")}</span>
            </label>
          </section>
        )}
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button onClick={() => start.mutate()} disabled={!confirmed || !p || p.problems.length > 0 || start.isPending}>
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {t("wf.startRun")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
