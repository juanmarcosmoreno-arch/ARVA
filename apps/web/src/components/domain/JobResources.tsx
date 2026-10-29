import { useT } from "@/i18n";
import { resourcesLine } from "@/lib/performance";
import type { AnalysisJob } from "@/lib/types";

/** The threads, memory limit and CPU priority a job was given (its performance profile), when it records them. */
export function JobResources({ job }: { job: AnalysisJob }) {
  const t = useT();
  if (!job.resources) return null;
  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">{t("jobres.title")}</div>
      <p className="text-xs">{resourcesLine(t, job.resources)}</p>
    </div>
  );
}
