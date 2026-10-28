import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Layers, Loader2 } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { ApiError, api } from "@/lib/api";
import { BATCH_ANALYSES, skipSummary } from "@/lib/batch";
import type { BatchAnalysis, BatchQcPlan } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHECKBOX = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Project page card: preview how many jobs each sample would get, then create exactly those after confirmation. */
export function ProjectBatchQc({ projectId }: { projectId: string }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [analyses, setAnalyses] = useState<BatchAnalysis[]>(["sequence_stats"]);
  const [includeDerived, setIncludeDerived] = useState(false);
  const [recompute, setRecompute] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [created, setCreated] = useState<number | null>(null);
  const selection = { analyses, include_derived: includeDerived, recompute };

  const plan = useQuery({
    queryKey: ["batchPlan", projectId, analyses.join(","), includeDerived, recompute],
    queryFn: () => api.batchQc(projectId, { ...selection, dry_run: true }),
    enabled: analyses.length > 0,
  });
  const run = useMutation({
    mutationFn: (planId: string) => api.batchQc(projectId, { ...selection, dry_run: false, plan_id: planId }),
    onSuccess: (res) => {
      setConfirming(false);
      setCreated(res.created_job_ids.length);
      for (const key of ["batchPlan", "jobs", "dashboard", "qcOverview"]) queryClient.invalidateQueries({ queryKey: [key] });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) plan.refetch();
    },
  });

  const toggle = (a: BatchAnalysis) => {
    setCreated(null);
    setAnalyses((prev) => (prev.includes(a) ? prev.filter((x) => x !== a) : BATCH_ANALYSES.filter((x) => x === a || prev.includes(x))));
  };
  const data = analyses.length ? plan.data : undefined;
  const missing = (data?.tools ?? []).filter((tool) => !tool.available && (data?.totals[tool.analysis] ?? 0) > 0);
  const canCreate = !!data && data.total_jobs > 0 && !missing.length && !plan.isFetching && !run.isPending;
  const changed = run.error instanceof ApiError && run.error.status === 409;

  return (
    <Card className="mt-6" id="project-batch-qc">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-arva-royal dark:text-arva-cyan" aria-hidden /> {t("batch.title")}
          </span>
        }
        description={t("batch.subtitle")}
        action={<Explain id="batch_qc" compact />}
      />
      <CardBody className="space-y-5">
        <div className="grid gap-4 lg:grid-cols-2">
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-semibold">{t("batch.analyses")}</legend>
            {BATCH_ANALYSES.map((a) => (
              <label key={a} className="flex items-start gap-2 text-sm">
                <input type="checkbox" className={CHECKBOX} checked={analyses.includes(a)} onChange={() => toggle(a)} />
                {t(`batch.analysis.${a}` as const)}
              </label>
            ))}
            {!analyses.length && <p className="text-xs text-warning">{t("batch.noneSelected")}</p>}
          </fieldset>
          <div className="space-y-3">
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className={CHECKBOX} checked={includeDerived} onChange={(e) => (setCreated(null), setIncludeDerived(e.target.checked))} />
              <span>
                {t("batch.includeDerived")}
                <span className="block text-xs text-muted-foreground">{t("batch.includeDerivedHint")}</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className={CHECKBOX} checked={recompute} onChange={(e) => (setCreated(null), setRecompute(e.target.checked))} />
              <span>
                {t("batch.recompute")}
                <span className="block text-xs text-muted-foreground">{t("batch.recomputeHint")}</span>
              </span>
            </label>
          </div>
        </div>

        <ErrorNote error={plan.error} />
        {plan.isLoading && analyses.length > 0 && <p className="text-xs text-muted-foreground">{t("batch.loading")}</p>}
        {data && <PlanTable plan={data} expanded={expanded} onExpand={setExpanded} />}
        {data && (
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {data.tools.map((tool) => (
              <li key={tool.analysis}>
                {t("batch.tool", { analysis: t(`batch.analysis.${tool.analysis}` as const), tool: tool.tool, version: tool.version ?? "?" })}
              </li>
            ))}
          </ul>
        )}
        {missing.map((tool) => (
          <p key={tool.analysis} role="status" className="flex items-start gap-2 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
            <span>
              {t("batch.toolMissing", { tool: tool.tool, message: tool.message || "?" })}{" "}
              <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
                {t("nav.tools")}
              </Link>
            </span>
          </p>
        ))}
        {data && data.total_jobs === 0 && <p className="text-xs font-medium">{t("batch.nothing")}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setConfirming(true)} disabled={!canCreate}>
            {t("batch.create", { n: data?.total_jobs ?? 0 })}
          </Button>
          {created !== null && <p role="status" className="text-xs text-success">{t("batch.created", { n: created })}</p>}
          {changed && <p role="status" className="text-xs text-warning">{t("batch.changed")}</p>}
        </div>

        {data && (
          <Dialog
            open={confirming}
            onOpenChange={setConfirming}
            title={t("batch.confirmTitle", { n: data.total_jobs, samples: data.samples_with_jobs })}
            className="max-w-2xl"
          >
            <p className="text-sm text-muted-foreground">{t("batch.confirmText")}</p>
            <div className="mt-3 max-h-80 overflow-y-auto">
              <PlanTable plan={{ ...data, samples: data.samples.filter((s) => s.total > 0) }} />
            </div>
            <ErrorNote error={run.error} />
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </Button>
              <Button disabled={!canCreate} onClick={() => run.mutate(data.plan_id)}>
                {run.isPending && <Loader2 className="h-4 w-4 animate-spin" />} {t("batch.confirm")}
              </Button>
            </div>
          </Dialog>
        )}
      </CardBody>
    </Card>
  );
}

/** Jobs per sample and analysis, with the reasons files are skipped; optionally each file's decision. */
function PlanTable({ plan, expanded, onExpand }: { plan: BatchQcPlan; expanded?: string | null; onExpand?: (id: string | null) => void }) {
  const t = useT();
  const cols = plan.analyses;
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-muted-foreground">
        <tr className="border-b">
          <th className="py-1.5 pr-3 font-medium">{t("batch.sample")}</th>
          {cols.map((a) => (
            <th key={a} className="py-1.5 pr-3 text-right font-medium">
              {t(`batch.analysis.${a}` as const)}
            </th>
          ))}
          <th className="py-1.5 text-right font-medium">{t("batch.jobs")}</th>
        </tr>
      </thead>
      <tbody>
        {plan.samples.map((s) => {
          const open = expanded === s.sample_id;
          const skipped = skipSummary(s);
          return (
            <Fragment key={s.sample_id}>
              <tr className="border-b align-top">
                <td className="py-1.5 pr-3">
                  <div className="font-medium">{s.sample_code}</div>
                  {skipped.length > 0 && (
                    <div className="text-muted-foreground">
                      {t("batch.skipped", { reasons: skipped.map(([reason, n]) => `${t(`batch.reason.${reason}` as const)}: ${n}`).join("; ") })}
                    </div>
                  )}
                  {onExpand && s.files.length > 0 && (
                    <button className="mt-0.5 inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan" onClick={() => onExpand(open ? null : s.sample_id)} aria-expanded={open}>
                      <ChevronDown className={cn("h-3 w-3 transition", open && "rotate-180")} aria-hidden />
                      {open ? t("batch.hideFiles") : t("batch.showFiles")}
                    </button>
                  )}
                </td>
                {cols.map((a) => (
                  <td key={a} className="py-1.5 pr-3 text-right tabular-nums">
                    {s.jobs[a] ?? 0}
                  </td>
                ))}
                <td className="py-1.5 text-right font-semibold tabular-nums">{s.total}</td>
              </tr>
              {open &&
                s.files.map((f) => (
                  <tr key={f.file_id} className="border-b bg-muted/30 text-muted-foreground">
                    <td className="py-1 pl-4 pr-3 break-all">{f.name}</td>
                    {cols.map((a) => {
                      const d = f.decisions[a] ?? "run";
                      return (
                        <td key={a} className={cn("py-1 pr-3 text-right", d === "run" && "font-medium text-foreground")}>
                          {t(`batch.reason.${d}` as const)}
                        </td>
                      );
                    })}
                    <td />
                  </tr>
                ))}
            </Fragment>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <td className="py-1.5 pr-3 font-semibold">{t("batch.total")}</td>
          {cols.map((a) => (
            <td key={a} className="py-1.5 pr-3 text-right font-semibold tabular-nums">
              {plan.totals[a] ?? 0}
            </td>
          ))}
          <td className="py-1.5 text-right font-semibold tabular-nums">{plan.total_jobs}</td>
        </tr>
      </tfoot>
    </table>
  );
}
