import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, Pause, Play, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CopyErrorDetails } from "@/components/diagnostics/CopyErrorDetails";
import { CancelJobButton, CancellingNote, FlyeRecovery } from "@/components/domain/JobControls";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { dictionaries, type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { ANNOTATION_JOBS, BAKTA_JOB } from "@/lib/annotation";
import { elapsedSeconds } from "@/lib/assembly";
import { MLST_JOB } from "@/lib/mlst";
import { SPECIES_JOB } from "@/lib/species";
import { FLYE_JOB, stageStates } from "@/lib/flye";
import { POLISHING_JOBS, RACON_JOB } from "@/lib/polishing";
import { fmtDate, fmtDuration } from "@/lib/format";
import { QUAST_JOB } from "@/lib/quast";
import type { AnalysisJob, AnalysisJobDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { jobError } from "@/lib/messages";

const LOG_LINES = 200;

const TEXT = {
  [FLYE_JOB]: { running: "assembly.running", starting: "assembly.startingTool", liveLog: "assembly.liveLog", failed: "assembly.failed", cancelled: "assembly.cancelled", failedAt: "assembly.failedAt", failedNote: "assembly.failedNote", stages: "assembly.stages" },
  [QUAST_JOB]: { running: "quast.running", starting: "quast.startingTool", liveLog: "quast.liveLog", failed: "quast.failed", cancelled: "quast.cancelled", failedAt: "quast.failedAt", failedNote: "quast.failedNote", stages: "quast.stages" },
  [BAKTA_JOB]: { running: "annotation.running", starting: "annotation.startingTool", liveLog: "annotation.liveLog", failed: "annotation.failed", cancelled: "annotation.cancelled", failedAt: "annotation.failedAt", failedNote: "annotation.failedNote", stages: "annotation.stages" },
  [MLST_JOB]: { running: "mlst.running", starting: "mlst.startingTool", liveLog: "mlst.liveLog", failed: "mlst.failed", cancelled: "mlst.cancelled", failedAt: "mlst.failedAt", failedNote: "mlst.failedNote", stages: "mlst.stages" },
  [SPECIES_JOB]: { running: "species.running", starting: "species.startingTool", liveLog: "species.liveLog", failed: "species.failed", cancelled: "species.cancelled", failedAt: "species.failedAt", failedNote: "species.failedNote", stages: "species.stages" },
  [RACON_JOB]: { running: "polishing.running", starting: "polishing.startingTool", liveLog: "polishing.liveLog", failed: "polishing.failed", cancelled: "polishing.cancelled", failedAt: "polishing.failedAt", failedNote: "polishing.failedNote", stages: "polishing.stages" },
} as const satisfies Record<string, Record<string, TranslationKey>>;

const texts = (job: AnalysisJobDetail) =>
  job.job_type === QUAST_JOB
    ? TEXT[QUAST_JOB]
    : POLISHING_JOBS.has(job.job_type)
      ? TEXT[RACON_JOB]
      : ANNOTATION_JOBS.has(job.job_type)
        ? TEXT[BAKTA_JOB]
        : job.job_type === MLST_JOB
          ? TEXT[MLST_JOB]
          : job.job_type === SPECIES_JOB
            ? TEXT[SPECIES_JOB]
            : TEXT[FLYE_JOB];

/** A polishing step's name in the interface language: "Racon round 2", "Reads aligned to both", ... */
function stageName(t: ReturnType<typeof useT>, stage: string) {
  const round = /^(racon|pilon)_round_(\d+)$/.exec(stage);
  if (round) return t("polishing.stage.round", { tool: round[1] === "racon" ? "Racon" : "Pilon", n: round[2] });
  const key = `polishing.stage.${stage}`;
  if (key in dictionaries.en) return t(key as TranslationKey);
  const annotation = `annotation.stageName.${stage}`;
  return annotation in dictionaries.en ? t(annotation as TranslationKey) : stage;
}

/** The current time, ticking every second while `active`. */
function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

/** The tool's stages as a stepper: done, current (or where it failed) and still to come. */
export function StageList({ job }: { job: AnalysisJobDetail }) {
  const t = useT();
  const stages = stageStates(job);
  if (!stages.length) return null;
  return (
    <ol className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4" aria-label={t(texts(job).stages)}>
      {stages.map((s, i) => {
        const Icon = s.state === "done" ? CheckCircle2 : s.state === "failed" ? XCircle : s.state === "current" ? Loader2 : Circle;
        return (
          <li
            key={`${i}-${s.name}`}
            aria-current={s.state === "current" ? "step" : undefined}
            className={cn(
              "flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs",
              s.state === "current" && "border-arva-royal/50 bg-arva-royal/5 dark:border-arva-cyan/50",
              s.state === "failed" && "border-danger/40 bg-danger/5",
              s.state === "waiting" && "text-muted-foreground",
            )}
          >
            <Icon
              className={cn(
                "mt-0.5 h-3.5 w-3.5 shrink-0",
                s.state === "done" && "text-success",
                s.state === "current" && "animate-spin text-arva-royal dark:text-arva-cyan",
                s.state === "failed" && "text-danger",
              )}
              aria-hidden
            />
            <span>
              <span className="font-medium">
                {i + 1}. {stageName(t, s.name)}
              </span>
              <span className="block text-muted-foreground">{stageDescription(t, s.name)}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function stageDescription(t: ReturnType<typeof useT>, stage: string) {
  const annotation = `annotation.stageHint.${stage}`;
  if (annotation in dictionaries.en) return t(annotation as TranslationKey);
  const key = `assembly.stage.${stage}`;
  if (/^(racon|pilon)_round_\d+$/.test(stage)) return t(stage.startsWith("racon") ? "polishing.stage.raconRoundHint" : "polishing.stage.pilonRoundHint");
  return key in dictionaries.en ? t(key as TranslationKey) : "";
}

/** What a run works on: the read files of an assembly, or the assemblies (and reference) QUAST evaluates. */
function runInputs(t: ReturnType<typeof useT>, job: AnalysisJobDetail, names: Map<string, string>) {
  if (POLISHING_JOBS.has(job.job_type)) {
    const draft = (job.parameters?.draft ?? {}) as { assembler?: string; assembler_version?: string; assembly_id?: string };
    return t("polishing.runInputs", {
      draft: `${draft.assembler ?? "?"} ${draft.assembler_version ?? ""} · ${(draft.assembly_id ?? "").slice(0, 8)}`,
      files: (job.input_raw_file_ids ?? []).map((id) => names.get(id) ?? id).join(", "),
    });
  }
  if (ANNOTATION_JOBS.has(job.job_type)) {
    const a = (job.parameters?.assembly ?? {}) as { assembler?: string; assembler_version?: string; assembly_id?: string };
    return t("annotation.runInputs", { assembly: `${a.assembler ?? "?"} ${a.assembler_version ?? ""} · ${(a.assembly_id ?? "").slice(0, 8)}` });
  }
  if (job.job_type === QUAST_JOB) {
    const planned = (job.parameters?.assemblies ?? []) as { label: string }[];
    const ref = job.input_raw_file_ids?.[0];
    return t("quast.evaluating", { labels: planned.map((a) => a.label).join(", ") }) + (ref ? ` · ${t("quast.withReference", { name: names.get(ref) ?? ref })}` : "");
  }
  const inputs = t("assembly.inputs", { files: (job.input_raw_file_ids ?? []).map((id) => names.get(id) ?? id).join(", ") });
  const resumed = job.parameters?.resume as { of_job_id: string; completed_stages: string[] } | undefined;
  return resumed ? `${inputs} · ${t("resume.resumedFrom", { id: resumed.of_job_id.slice(0, 8), stages: resumed.completed_stages.join(", ") })}` : inputs;
}

/** The last lines of the tool's live log, following new lines unless paused. */
function LogTail({ job }: { job: AnalysisJobDetail }) {
  const t = useT();
  const [paused, setPaused] = useState(false);
  const box = useRef<HTMLPreElement>(null);
  const log = useQuery({
    queryKey: ["jobLog", job.id],
    queryFn: () => api.jobLog(job.id, LOG_LINES),
    refetchInterval: paused ? false : 3000,
  });
  const text = log.data?.text;
  useEffect(() => {
    if (!paused && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [text, paused]);
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{log.data?.source === "tool" ? t(texts(job).liveLog, { n: LOG_LINES }) : t("assembly.jobLog")}</span>
        <Button size="sm" variant="ghost" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
          {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
          {paused ? t("assembly.log.resume") : t("assembly.log.pause")}
        </Button>
      </div>
      <pre ref={box} className="max-h-64 overflow-auto rounded-lg bg-arva-navy p-3 text-[11px] leading-relaxed text-slate-200" aria-live={paused ? "off" : "polite"}>
        {text || "…"}
      </pre>
      {paused && <p className="mt-1 text-[11px] text-muted-foreground">{t("assembly.log.paused")}</p>}
      <ErrorNote error={log.error} />
    </div>
  );
}

/** A queued or running assembly or evaluation: stage stepper, live elapsed time and the tool's log. */
export function RunningCard({ job, names }: { job: AnalysisJobDetail; names: Map<string, string> }) {
  const t = useT();
  const k = texts(job);
  const p = job.progress;
  const running = job.status === "running";
  const elapsed = elapsedSeconds(job, useNow(running));
  return (
    <Card className="border-arva-royal/30">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-arva-royal dark:text-arva-cyan" aria-hidden />
            {t(k.running, { tool: `${job.tool_name} ${job.tool_version}` })}
          </span>
        }
        description={runInputs(t, job, names)}
        action={<CancelJobButton job={job} />}
      />
      <CardBody className="space-y-4 pt-3">
        <div className="text-sm">
          {job.status === "pending"
            ? t("assembly.waiting")
            : p?.stage
              ? t("assembly.stageLine", { index: p.stage_index ?? "?", total: p.stages_total ?? "?", stage: stageName(t, p.stage) })
              : t(k.starting)}
          {elapsed != null && <span className="ml-2 text-xs text-muted-foreground">{t("assembly.elapsed", { time: fmtDuration(elapsed) })}</span>}
        </div>
        <StageList job={job} />
        <CancellingNote job={job} />
        {running && <LogTail job={job} />}
      </CardBody>
    </Card>
  );
}

/** A failed or cancelled run: why it stopped, where, and (Flye) whether it can be resumed. */
export function FailedCard({ job, resumedBy }: { job: AnalysisJobDetail; resumedBy?: AnalysisJob }) {
  const t = useT();
  const k = texts(job);
  const stage = job.progress?.stage;
  const cancelled = job.status === "cancelled";
  return (
    <Card className={cancelled ? "border-warning/40" : "border-danger/30"}>
      <CardHeader title={t(cancelled ? k.cancelled : k.failed, { tool: `${job.tool_name} ${job.tool_version}` })} description={fmtDate(job.finished_at ?? job.created_at)} />
      <CardBody className="space-y-2 pt-3">
        {!cancelled && <ErrorNote error={jobError(t, job)} />}
        {!cancelled && <CopyErrorDetails jobId={job.id} />}
        {stage && <p className="text-xs text-muted-foreground">{t(cancelled ? "assembly.cancelledAt" : k.failedAt, { stage: stageName(t, stage) })}</p>}
        <StageList job={job} />
        <p className="text-xs text-muted-foreground">{t(cancelled ? "assembly.cancelledNote" : k.failedNote)}</p>
        <FlyeRecovery job={job} resumedBy={resumedBy} />
      </CardBody>
    </Card>
  );
}
