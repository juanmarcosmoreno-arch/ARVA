import { CheckCircle2, Circle, Clock, Loader2, XCircle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { GuideId } from "@/guide/metrics";
import type { JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS: Record<JobStatus, { tone: "neutral" | "blue" | "success" | "danger"; icon: LucideIcon; label: string }> = {
  pending: { tone: "neutral", icon: Clock, label: "Queued" },
  running: { tone: "blue", icon: Loader2, label: "Running" },
  completed: { tone: "success", icon: CheckCircle2, label: "Completed" },
  failed: { tone: "danger", icon: XCircle, label: "Failed" },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const s = STATUS[status];
  return (
    <Badge tone={s.tone}>
      <s.icon className={cn("h-3 w-3", status === "running" && "animate-spin")} />
      {s.label}
    </Badge>
  );
}

export function StatTile({ label, value, sub, icon: Icon }: { label: string; value: ReactNode; sub?: ReactNode; icon?: LucideIcon }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        {Icon && <Icon className="h-4 w-4 text-arva-teal" />}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}

export function MetricTile({ label, value, sub, explain }: { label: string; value: ReactNode; sub?: ReactNode; explain?: GuideId }) {
  return (
    <div className="rounded-xl border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs text-muted-foreground">{label}</span>
        {explain && <Explain id={explain} compact />}
      </div>
      <div className="mt-1.5 text-xl font-semibold tabular-nums tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export type StageState = "done" | "running" | "failed" | "ready" | "planned";

export interface Stage {
  key: string;
  label: string;
  state: StageState;
  detail?: string;
  phase?: number;
}

const STAGE_STYLE: Record<StageState, { ring: string; icon: LucideIcon; text: string }> = {
  done: { ring: "border-success bg-success/10 text-success", icon: CheckCircle2, text: "text-foreground" },
  running: { ring: "border-arva-royal bg-arva-royal/10 text-arva-royal dark:border-arva-cyan dark:text-arva-cyan", icon: Loader2, text: "text-foreground" },
  failed: { ring: "border-danger bg-danger/10 text-danger", icon: XCircle, text: "text-foreground" },
  ready: { ring: "border-arva-teal bg-surface text-arva-teal", icon: Circle, text: "text-foreground" },
  planned: { ring: "border-dashed border-border bg-surface text-muted-foreground", icon: Circle, text: "text-muted-foreground" },
};

/** ARVA Analysis Timeline: Raw Data → QC → … → Biological Analysis (spec §24). */
export function AnalysisTimeline({ stages, onSelect, selected }: { stages: Stage[]; onSelect?: (key: string) => void; selected?: string }) {
  return (
    <ol className="flex overflow-x-auto pb-2" aria-label="Analysis timeline">
      {stages.map((s, i) => {
        const st = STAGE_STYLE[s.state];
        const clickable = onSelect && s.state !== "planned";
        return (
          <li key={s.key} className="flex min-w-[118px] flex-1 flex-col items-center text-center">
            <div className="flex w-full items-center">
              <div className={cn("h-px flex-1", i === 0 ? "bg-transparent" : "bg-border")} />
              <button
                disabled={!clickable}
                onClick={() => clickable && onSelect?.(s.key)}
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 transition",
                  st.ring,
                  clickable && "hover:scale-105",
                  selected === s.key && "ring-2 ring-ring ring-offset-2 ring-offset-background",
                )}
                aria-label={`${s.label}: ${s.state}`}
              >
                <st.icon className={cn("h-4 w-4", s.state === "running" && "animate-spin")} />
              </button>
              <div className={cn("h-px flex-1", i === stages.length - 1 ? "bg-transparent" : "bg-border")} />
            </div>
            <div className={cn("mt-2 text-xs font-medium", st.text)}>{s.label}</div>
            <div className="mt-0.5 px-1 text-[10px] text-muted-foreground">
              {s.state === "planned" ? `Phase ${s.phase}` : s.detail}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
