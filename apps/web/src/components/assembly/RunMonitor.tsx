import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, Pause, Play, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { dictionaries, type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { elapsedSeconds } from "@/lib/assembly";
import { FLYE_JOB, stageStates } from "@/lib/flye";
import { fmtDate, fmtDuration } from "@/lib/format";
import { QUAST_JOB } from "@/lib/quast";
import type { AnalysisJobDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

const LOG_LINES = 200;

const TEXT = {
  [FLYE_JOB]: { running: "assembly.running", starting: "assembly.startingTool", liveLog: "assembly.liveLog", failed: "assembly.failed", failedAt: "assembly.failedAt", failedNote: "assembly.failedNote", stages: "assembly.stages" },
  [QUAST_JOB]: { running: "quast.running", starting: "quast.startingTool", liveLog: "quast.liveLog", failed: "quast.failed", failedAt: "quast.failedAt", failedNote: "quast.failedNote", stages: "quast.stages" },
} as const satisfies Record<string, Record<string, TranslationKey>>;

const texts = (job: AnalysisJobDetail) => (job.job_type === QUAST_JOB ? TEXT[QUAST_JOB] : TEXT[FLYE_JOB]);

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
            key={s.name}
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
                {i + 1}. {s.name}
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
  const key = `assembly.stage.${stage}`;
  return key in dictionaries.en ? t(key as TranslationKey) : "";
}

/** What a run works on: the read files of an assembly, or the assemblies (and reference) QUAST evaluates. */
function runInputs(t: ReturnType<typeof useT>, job: AnalysisJobDetail, names: Map<string, string>) {
  if (job.job_type === QUAST_JOB) {
    const planned = (job.parameters?.assemblies ?? []) as { label: string }[];
    const ref = job.input_raw_file_ids?.[0];
    return t("quast.evaluating", { labels: planned.map((a) => a.label).join(", ") }) + (ref ? ` · ${t("quast.withReference", { name: names.get(ref) ?? ref })}` : "");
  }
  return t("assembly.inputs", { files: (job.input_raw_file_ids ?? []).map((id) => names.get(id) ?? id).join(", ") });
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
      />
      <CardBody className="space-y-4 pt-3">
        <div className="text-sm">
          {job.status === "pending"
            ? t("assembly.waiting")
            : p?.stage
              ? t("assembly.stageLine", { index: p.stage_index ?? "?", total: p.stages_total ?? "?", stage: p.stage })
              : t(k.starting)}
          {elapsed != null && <span className="ml-2 text-xs text-muted-foreground">{t("assembly.elapsed", { time: fmtDuration(elapsed) })}</span>}
        </div>
        <StageList job={job} />
        {running && <LogTail job={job} />}
        <p className="text-[11px] text-muted-foreground">{t("assembly.noCancel")}</p>
      </CardBody>
    </Card>
  );
}

export function FailedCard({ job }: { job: AnalysisJobDetail }) {
  const t = useT();
  const k = texts(job);
  const stage = job.progress?.stage;
  return (
    <Card className="border-danger/30">
      <CardHeader title={t(k.failed, { tool: `${job.tool_name} ${job.tool_version}` })} description={fmtDate(job.finished_at ?? job.created_at)} />
      <CardBody className="space-y-2 pt-3">
        <ErrorNote error={job.error_message} />
        {stage && <p className="text-xs text-muted-foreground">{t(k.failedAt, { stage })}</p>}
        <StageList job={job} />
        <p className="text-xs text-muted-foreground">{t(k.failedNote)}</p>
      </CardBody>
    </Card>
  );
}
