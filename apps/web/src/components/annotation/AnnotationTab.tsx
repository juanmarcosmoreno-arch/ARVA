import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Dna, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { FailedCard, RunningCard } from "@/components/assembly/RunMonitor";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { ANNOTATION_JOBS } from "@/lib/annotation";
import { api } from "@/lib/api";
import { toolMessage } from "@/lib/messages";
import type { AnalysisJobDetail } from "@/lib/types";
import { AnnotationCard } from "./AnnotationResult";

export function AnnotationTab({ sampleId, jobs, onNew }: { sampleId: string; jobs: AnalysisJobDetail[]; onNew: () => void }) {
  const t = useT();
  const bakta = useTool("bakta");
  const prokka = useTool("prokka");
  const runs = jobs.filter((j) => ANNOTATION_JOBS.has(j.job_type));
  const active = runs.filter((j) => j.status === "pending" || j.status === "running");
  const stopped = runs.filter((j) => j.status === "failed" || j.status === "cancelled").slice(0, 3);
  const annotations = useQuery({ queryKey: ["annotations", sampleId], queryFn: () => api.annotations(sampleId) });
  const assemblies = useQuery({ queryKey: ["assemblies", sampleId], queryFn: () => api.assemblies(sampleId) });
  const byJob = new Map(jobs.map((j) => [j.id, j]));
  const list = annotations.data ?? [];
  const hasAssembly = (assemblies.data ?? []).length > 0;
  const missing = [bakta, prokka].filter((x) => x && x.status !== "available");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">{t("annotation.intro")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Explain id="annotation" />
          <Button onClick={onNew} disabled={!hasAssembly}>
            <Plus className="h-4 w-4" /> {t("annotation.start")}
          </Button>
        </div>
      </div>
      {missing.length > 0 && (
        <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p>
            {t("annotation.toolsMissing", { tools: missing.map((x) => `${x!.name} (${x!.status === "not_installed" ? t("annotation.notInstalled") : toolMessage(t, x!) || x!.status})`).join("; ") })}{" "}
            <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
              {t("nav.tools")}
            </Link>
          </p>
        </div>
      )}
      {active.map((j) => (
        <RunningCard key={j.id} job={j} names={new Map()} />
      ))}
      {list.map((a) => (
        <AnnotationCard key={a.id} annotation={a} job={byJob.get(a.job_id)} />
      ))}
      <ErrorNote error={annotations.error} />
      {stopped.map((j) => (
        <FailedCard key={j.id} job={j} />
      ))}
      {!active.length && !list.length && !stopped.length && (
        <EmptyState icon={<Dna className="h-7 w-7" />} title={t("annotation.empty")}>
          {hasAssembly ? t("annotation.emptyHint") : t("annotation.noAssembly")}
        </EmptyState>
      )}
    </div>
  );
}
