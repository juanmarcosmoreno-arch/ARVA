import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { addedFolders, databaseCheck, performanceCheck, projectCheck, storageCheck, type CheckItem, type CheckState } from "@/lib/firstRun";
import { profileLabel } from "@/lib/performance";
import { isUnreachable } from "@/lib/unreachable";
import { useSettings } from "@/store/settings";

const ICON: Record<CheckState, { icon: typeof Circle; className: string; label: TranslationKey }> = {
  done: { icon: CheckCircle2, className: "text-success", label: "firstRun.state.done" },
  todo: { icon: Circle, className: "text-muted-foreground", label: "firstRun.state.todo" },
  attention: { icon: TriangleAlert, className: "text-amber-600 dark:text-warning", label: "firstRun.state.attention" },
  busy: { icon: Loader2, className: "animate-spin text-arva-royal dark:text-arva-cyan", label: "firstRun.state.busy" },
  unknown: { icon: Circle, className: "text-muted-foreground/50", label: "firstRun.state.unknown" },
};

const LINK: Record<CheckItem["key"], string> = {
  storage: "/settings",
  performance: "/settings",
  bakta: "/tools#reference-databases",
  references: "/tools#reference-databases",
  amrfinderplus: "/tools#reference-databases",
  project: "/projects",
};

/** How long a status may stay unanswered before the checklist says so and offers to ask again. */
export const SLOW_MS = 20_000;

/** A question that failed is asked again every 10 s (ARVA's API may still be starting), so the item recovers alone. */
const againAfterError = (q: { state: { status: string } }) => (q.state.status === "error" ? 10_000 : false);

/** True once `waiting` has stayed true for SLOW_MS since it became true or since the last `attempt`. */
function useSlow(waiting: boolean, attempt: number) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    setSlow(false);
    if (!waiting) return;
    const id = window.setTimeout(() => setSlow(true), SLOW_MS);
    return () => window.clearTimeout(id);
  }, [waiting, attempt]);
  return slow;
}

/** The dashboard's first-run checklist: each item's status as the API reports it; dismissed in Settings → General. */
export function FirstRunChecklist({ onCreateProject }: { onCreateProject: () => void }) {
  const t = useT();
  const setShow = useSettings((s) => s.setShowChecklist);
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage, refetchInterval: againAfterError });
  const performance = useQuery({ queryKey: ["performance"], queryFn: api.performance, refetchInterval: againAfterError });
  const records = useQuery({ queryKey: ["databases"], queryFn: api.databases, refetchInterval: againAfterError });
  const locations = useQuery({ queryKey: ["database-locations"], queryFn: api.databaseLocations });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: againAfterError });
  const folders = addedFolders(locations.data);
  const qc = useQueryClient();
  const [attempt, setAttempt] = useState(0);
  const slow = useSlow([storage, performance, records, dashboard].some((q) => q.isPending), attempt);

  // An item whose question failed says so (instead of "Reading…" for ever) and offers to ask again; one still waiting
  // after SLOW_MS says that ARVA has not answered yet.
  const sources: Record<CheckItem["key"], UseQueryResult<unknown>> = {
    storage, performance, bakta: records, references: records, amrfinderplus: records, project: dashboard,
  };
  const keys: Record<CheckItem["key"], string> = {
    storage: "storage", performance: "performance", bakta: "databases", references: "databases", amrfinderplus: "databases", project: "dashboard",
  };
  // A reset, not a refetch: a refetch would join a request that never answered instead of making a new one.
  const askAgain = (key: CheckItem["key"]) => {
    setAttempt((n) => n + 1);
    void qc.resetQueries({ queryKey: [keys[key]], exact: true });
  };
  const items = [
    storageCheck(storage.data),
    performanceCheck(performance.data),
    databaseCheck("bakta", records.data),
    databaseCheck("references", records.data),
    databaseCheck("amrfinderplus", records.data),
    projectCheck(dashboard.data),
  ].map((item): CheckItem => {
    const q = sources[item.key];
    if (item.state !== "unknown") return item;
    if (q.isError) return { ...item, state: "attention", code: "readFailed" };
    return slow && q.isPending ? { ...item, code: "slow" } : item;
  });
  const done = items.filter((i) => i.state === "done").length;

  const detail = (item: CheckItem): string => {
    if (item.code === "readFailed") {
      const error = sources[item.key].error;
      return t("firstRun.readFailed", { error: isUnreachable(error) ? t("error.unreachable") : error instanceof Error ? error.message : String(error) });
    }
    if (item.code === "slow") return t("firstRun.slow");
    const params = { ...item.params };
    if (item.key === "performance" && typeof params.profile === "string") params.profile = profileLabel(t, params.profile);
    return t(`firstRun.${item.key}.${item.code}` as TranslationKey, params);
  };
  const hint = (item: CheckItem): string | null => {
    if (item.state === "done" || item.state === "unknown" || item.state === "busy" || item.code === "readFailed") return null;
    if (item.key === "bakta" || item.key === "references") {
      return folders.length > 0
        ? t(`firstRun.${item.key}.hintFolders` as TranslationKey, { folders: folders.join(", ") })
        : t(`firstRun.${item.key}.hintAdd` as TranslationKey);
    }
    return null;
  };

  return (
    <Card aria-labelledby="first-run-title">
      <CardHeader
        title={<span id="first-run-title">{t("firstRun.title")}</span>}
        description={t("firstRun.subtitle", { done, total: items.length })}
        action={
          <Button variant="ghost" size="sm" onClick={() => setShow(false)} aria-label={t("firstRun.dismissLabel")}>
            <X className="h-3.5 w-3.5" aria-hidden /> {t("firstRun.dismiss")}
          </Button>
        }
      />
      <CardBody className="pt-3">
        <ol className="divide-y">
          {items.map((item) => {
            const state = ICON[item.state];
            const extra = hint(item);
            return (
              <li key={item.key} className="flex items-start gap-3 py-2.5">
                <state.icon className={`mt-0.5 h-4 w-4 shrink-0 ${state.className}`} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-medium">{t(`firstRun.${item.key}.title` as TranslationKey)}</span>
                    <span className="sr-only">{t(state.label)}</span>
                  </div>
                  <p className="mt-0.5 break-words text-xs text-muted-foreground">{detail(item)}</p>
                  {extra && <p className="mt-1 break-words text-xs text-muted-foreground">{extra}</p>}
                </div>
                {item.code === "readFailed" || item.code === "slow" ? (
                  <Button size="sm" variant="outline" onClick={() => askAgain(item.key)} className="shrink-0">
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t("error.retry")}
                  </Button>
                ) : item.state !== "done" &&
                  (item.key === "project" ? (
                    <Button size="sm" variant="outline" onClick={onCreateProject} className="shrink-0">
                      {t("firstRun.project.action")}
                    </Button>
                  ) : (
                    <Link to={LINK[item.key]} className={buttonClass("outline", "sm", "shrink-0")}>
                      {t(`firstRun.${item.key}.action` as TranslationKey)}
                    </Link>
                  ))}
              </li>
            );
          })}
        </ol>
      </CardBody>
    </Card>
  );
}
