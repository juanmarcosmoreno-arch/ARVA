import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, Layers, Plus, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { ASSEMBLY_JOBS } from "@/lib/flye";
import { toolMessage } from "@/lib/messages";
import { POLISHING_JOBS } from "@/lib/polishing";
import { QUAST_JOB } from "@/lib/quast";
import type { AnalysisJobDetail, RawFile } from "@/lib/types";
import { AssemblyComparison } from "./AssemblyComparison";
import { AssemblyCard } from "./AssemblyResult";
import { PolishingCard } from "./PolishingCard";
import { QuastCard } from "./QuastCard";
import { FailedCard, RunningCard } from "./RunMonitor";

export function AssemblyTab({
  sampleId,
  jobs,
  files,
  onNew,
  onEvaluate,
  onPolish,
}: {
  sampleId: string;
  jobs: AnalysisJobDetail[];
  files: RawFile[];
  onNew: () => void;
  onEvaluate: () => void;
  onPolish: (draftId?: string) => void;
}) {
  const t = useT();
  const assemblers = [useTool("flye"), useTool("spades"), useTool("unicycler")];
  const quast = useTool("quast");
  const runs = jobs.filter((j) => ASSEMBLY_JOBS.has(j.job_type) && !POLISHING_JOBS.has(j.job_type));
  const active = runs.filter((j) => j.status === "pending" || j.status === "running");
  const stopped = (j: AnalysisJobDetail) => j.status === "failed" || j.status === "cancelled";
  const failed = runs.filter(stopped).slice(0, 3);
  const resumedBy = (j: AnalysisJobDetail) => runs.find((r) => (r.parameters?.resume as { of_job_id?: string } | undefined)?.of_job_id === j.id);
  const evaluations = jobs.filter((j) => j.job_type === QUAST_JOB && j.status === "completed");
  const polishing = jobs.filter((j) => POLISHING_JOBS.has(j.job_type));
  const polishingActive = polishing.filter((j) => j.status === "pending" || j.status === "running");
  const polishingFailed = polishing.filter(stopped).slice(0, 3);
  const polishingDone = polishing.filter((j) => j.status === "completed");
  const assemblies = useQuery({ queryKey: ["assemblies", sampleId], queryFn: () => api.assemblies(sampleId) });
  const byJob = new Map(jobs.map((j) => [j.id, j]));
  const names = new Map(files.map((f) => [f.id, f.original_filename]));
  const hasReads = files.some((f) => (f.file_format === "fastq" || f.file_format === "fastq_gz") && f.is_valid);
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
      {assemblers.some((a) => a && a.status !== "available") && (
        <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
          <p>
            {t("assembly.toolsMissing", {
              tools: assemblers
                .filter((a) => a && a.status !== "available")
                .map((a) => `${a!.name} (${a!.status === "not_installed" ? t("assembly.assembler.notInstalled") : toolMessage(t, a!) || a!.status})`)
                .join("; "),
            })}{" "}
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
        <AssemblyCard key={a.id} assembly={a} job={byJob.get(a.job_id)} files={files} assemblies={list} onPolish={() => onPolish(a.id)} />
      ))}
      <ErrorNote error={assemblies.error} />

      {list.length > 0 && (
        <section className="space-y-4" aria-labelledby="polishing-section">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="max-w-2xl">
              <h3 id="polishing-section" className="flex items-center gap-2 text-sm font-semibold">
                <Sparkles className="h-4 w-4 text-arva-royal dark:text-arva-cyan" aria-hidden /> {t("polishing.section")}
              </h3>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("polishing.intro")}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Explain id="polishing" compact />
              <Button variant="outline" onClick={() => onPolish()} disabled={!hasReads}>
                <Sparkles className="h-4 w-4" /> {t("polishing.start")}
              </Button>
            </div>
          </div>
          {polishingActive.map((j) => (
            <RunningCard key={j.id} job={j} names={names} />
          ))}
          {polishingDone.map((j) => (
            <PolishingCard key={j.id} job={j} assemblies={list} />
          ))}
          {polishingFailed.map((j) => (
            <FailedCard key={j.id} job={j} />
          ))}
          {!polishing.length && <p className="text-xs text-muted-foreground">{t("polishing.empty")}</p>}
        </section>
      )}

      {list.length >= 2 && <AssemblyComparison assemblies={list} files={files} />}

      {evaluations.length > 0 && <h3 className="text-sm font-semibold">{t("quast.section")}</h3>}
      {evaluations.map((j) => (
        <QuastCard key={j.id} job={j} />
      ))}

      {failed.map((j) => (
        <FailedCard key={j.id} job={j} resumedBy={resumedBy(j)} />
      ))}

      {!active.length && !list.length && !failed.length && (
        <EmptyState icon={<Layers className="h-7 w-7" />} title={t("assembly.empty")}>
          {hasReads ? t("assembly.emptyHint") : t("assembly.noReads")}
        </EmptyState>
      )}
    </div>
  );
}
