import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Square, Trash2 } from "lucide-react";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { FLYE_JOB } from "@/lib/flye";
import { fmtBytes, fmtDate } from "@/lib/format";
import type { AnalysisJob } from "@/lib/types";

export const isActiveJob = (j: Pick<AnalysisJob, "status">) => j.status === "pending" || j.status === "running";
export const isCancelling = (j: Pick<AnalysisJob, "status" | "cancel_requested_at">) => j.status === "running" && !!j.cancel_requested_at;

function useRefreshJobs() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["jobs", "projectJobs", "dashboard", "assemblies", "batchPlan"]) qc.invalidateQueries({ queryKey: [key] });
  };
}

/** Cancel a queued or running job after confirmation; "Cancelling…" while the worker stops a running tool. */
export function CancelJobButton({ job, size = "sm" }: { job: AnalysisJob; size?: "sm" | "md" }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const refresh = useRefreshJobs();
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(job.id),
    onSuccess: () => {
      setOpen(false);
      refresh();
    },
  });
  if (!isActiveJob(job)) return null;
  if (isCancelling(job)) {
    return (
      <Button size={size} variant="outline" disabled>
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("jobStatus.cancelling")}
      </Button>
    );
  }
  return (
    <>
      <Button size={size} variant="outline" onClick={() => setOpen(true)}>
        <Square className="h-3.5 w-3.5" /> {t("jobs.cancel")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title={t("jobs.cancelTitle")} description={`${job.tool_name} ${job.tool_version}`}>
        <div className="space-y-2 text-sm">
          <p>{job.status === "pending" ? t("jobs.cancelQueued") : t("jobs.cancelRunning", { tool: job.tool_name })}</p>
          {job.job_type === FLYE_JOB && job.status === "running" && <p className="text-muted-foreground">{t("jobs.cancelFlye")}</p>}
        </div>
        <ErrorNote error={cancel.error} />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {t("jobs.cancelKeep")}
          </Button>
          <Button variant="danger" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
            {cancel.isPending && <Loader2 className="h-4 w-4 animate-spin" />} {t("jobs.cancel")}
          </Button>
        </div>
      </Dialog>
    </>
  );
}

/** The note shown while a running job's cancellation is being carried out. */
export function CancellingNote({ job }: { job: AnalysisJob }) {
  const t = useT();
  if (!isCancelling(job)) return null;
  return (
    <p role="status" className="text-xs text-muted-foreground">
      {t("jobs.cancelling", { time: fmtDate(job.cancel_requested_at!) })}
    </p>
  );
}

/** For a failed or cancelled Flye run: resume it from the kept work folder, discard the folder, or why neither is offered. */
export function FlyeRecovery({ job, resumedBy }: { job: AnalysisJob; resumedBy?: AnalysisJob }) {
  const t = useT();
  const [confirm, setConfirm] = useState<"resume" | "discard" | null>(null);
  const refresh = useRefreshJobs();
  const done = () => {
    setConfirm(null);
    refresh();
  };
  const resume = useMutation({ mutationFn: () => api.resumeJob(job.id), onSuccess: done });
  const discard = useMutation({ mutationFn: () => api.discardCheckpoint(job.id), onSuccess: done });
  if (job.job_type !== FLYE_JOB || (job.status !== "failed" && job.status !== "cancelled")) return null;
  if (resumedBy) return <p className="text-xs text-muted-foreground">{t("resume.resumedBy", { id: resumedBy.id.slice(0, 8) })}</p>;
  const kept = job.checkpoint;
  if (!kept) {
    return (
      <div className="flex items-start gap-2 text-xs text-muted-foreground">
        <p>{t("resume.notOffered")}</p>
        <Explain id="job_control" compact />
      </div>
    );
  }
  const size = fmtBytes(kept.size_bytes);
  return (
    <section aria-label={t("resume.title")} className="space-y-2 rounded-lg border bg-muted/30 p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-semibold">{t("resume.title")}</h4>
        <Explain id="job_control" compact />
      </div>
      <p>
        {t(`resume.reason.${kept.reason}` as const)} {t("resume.kept", { size, done: kept.completed_stages.join(", "), stage: kept.resume_stage })}
      </p>
      <p className="text-muted-foreground">{t("resume.same", { version: kept.tool_version })}</p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setConfirm("resume")}>
          <RotateCcw className="h-3.5 w-3.5" /> {t("resume.button")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirm("discard")}>
          <Trash2 className="h-3.5 w-3.5" /> {t("resume.discard")}
        </Button>
      </div>
      <Dialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm === "discard" ? t("resume.discardTitle") : t("resume.confirmTitle", { stage: kept.resume_stage })}
      >
        <p className="text-sm">{confirm === "discard" ? t("resume.discardText", { size }) : t("resume.same", { version: kept.tool_version })}</p>
        <ErrorNote error={confirm === "discard" ? discard.error : resume.error} />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirm(null)}>
            {t("common.cancel")}
          </Button>
          {confirm === "discard" ? (
            <Button variant="danger" disabled={discard.isPending} onClick={() => discard.mutate()}>
              {t("resume.discard")}
            </Button>
          ) : (
            <Button disabled={resume.isPending} onClick={() => resume.mutate()}>
              {t("resume.confirm")}
            </Button>
          )}
        </div>
      </Dialog>
    </section>
  );
}
