import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, Layers, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { FLYE_JOB, flyeCandidates } from "@/lib/flye";
import { toolMessage } from "@/lib/messages";
import { QUAST_JOB } from "@/lib/quast";
import type { AnalysisJobDetail, RawFile } from "@/lib/types";
import { AssemblyComparison } from "./AssemblyComparison";
import { AssemblyCard } from "./AssemblyResult";
import { QuastCard } from "./QuastCard";
import { FailedCard, RunningCard } from "./RunMonitor";

export function AssemblyTab({
  sampleId,
  jobs,
  files,
  onNew,
  onEvaluate,
}: {
  sampleId: string;
  jobs: AnalysisJobDetail[];
  files: RawFile[];
  onNew: () => void;
  onEvaluate: () => void;
}) {
  const t = useT();
  const tool = useTool("flye");
  const quast = useTool("quast");
  const runs = jobs.filter((j) => j.job_type === FLYE_JOB || j.job_type === QUAST_JOB);
  const active = runs.filter((j) => j.status === "pending" || j.status === "running");
  const failed = runs.filter((j) => j.status === "failed").slice(0, 3);
  const evaluations = jobs.filter((j) => j.job_type === QUAST_JOB && j.status === "completed");
  const assemblies = useQuery({ queryKey: ["assemblies", sampleId], queryFn: () => api.assemblies(sampleId) });
  const byJob = new Map(jobs.map((j) => [j.id, j]));
  const names = new Map(files.map((f) => [f.id, f.original_filename]));
  const hasReads = files.some((f) => (f.file_format === "fastq" || f.file_format === "fastq_gz") && f.is_valid);
  const canStart = flyeCandidates(files).length > 0;
  const list = assemblies.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">{t("assembly.intro")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Explain id="assembly" />
          <Explain id="quast" compact />
          <Button variant="outline" onClick={onEvaluate} disabled={!list.length || quast?.status !== "available"}>
            <ClipboardCheck className="h-4 w-4" /> {t("quast.start")}
          </Button>
          <Button onClick={onNew} disabled={!hasReads}>
            <Plus className="h-4 w-4" /> {t("assembly.start")}
          </Button>
        </div>
      </div>
      {quast && quast.status !== "available" && list.length ? (
        <p className="text-xs text-muted-foreground">
          {quast.status === "not_installed" ? t("quast.notInstalled") : t("quast.unavailable", { message: toolMessage(t, quast) || quast.status })}{" "}
          <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
            {t("nav.tools")}
          </Link>
        </p>
      ) : null}
      {tool && tool.status !== "available" && (
        <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p>
            {tool.status === "not_installed" ? t("flye.notInstalled") : t("flye.unavailable", { message: toolMessage(t, tool) || tool.status })}{" "}
            <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
              {t("nav.tools")}
            </Link>
          </p>
        </div>
      )}

      {active.map((j) => (
        <RunningCard key={j.id} job={j} names={names} />
      ))}

      {list.map((a) => (
        <AssemblyCard key={a.id} assembly={a} job={byJob.get(a.job_id)} files={files} />
      ))}
      <ErrorNote error={assemblies.error} />

      {list.length >= 2 && <AssemblyComparison assemblies={list} files={files} />}

      {evaluations.length > 0 && <h3 className="text-sm font-semibold">{t("quast.section")}</h3>}
      {evaluations.map((j) => (
        <QuastCard key={j.id} job={j} />
      ))}

      {failed.map((j) => (
        <FailedCard key={j.id} job={j} />
      ))}

      {!active.length && !list.length && !failed.length && (
        <EmptyState icon={<Layers className="h-7 w-7" />} title={t("assembly.empty")}>
          {canStart ? t("assembly.emptyHint") : hasReads ? t("assembly.emptyNoLongReads") : t("flye.noFiles")}
        </EmptyState>
      )}
    </div>
  );
}
