import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, TriangleAlert, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { addedFolders, databaseCheck, performanceCheck, projectCheck, storageCheck, type CheckItem, type CheckState } from "@/lib/firstRun";
import { profileLabel } from "@/lib/performance";
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

/** The dashboard's first-run checklist: each item's status as the API reports it; dismissed in Settings → General. */
export function FirstRunChecklist({ onCreateProject }: { onCreateProject: () => void }) {
  const t = useT();
  const setShow = useSettings((s) => s.setShowChecklist);
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage });
  const performance = useQuery({ queryKey: ["performance"], queryFn: api.performance });
  const records = useQuery({ queryKey: ["databases"], queryFn: api.databases });
  const locations = useQuery({ queryKey: ["database-locations"], queryFn: api.databaseLocations });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const folders = addedFolders(locations.data);

  const items = [
    storageCheck(storage.data),
    performanceCheck(performance.data),
    databaseCheck("bakta", records.data),
    databaseCheck("references", records.data),
    databaseCheck("amrfinderplus", records.data),
    projectCheck(dashboard.data),
  ];
  const done = items.filter((i) => i.state === "done").length;

  const detail = (item: CheckItem): string => {
    const params = { ...item.params };
    if (item.key === "performance" && typeof params.profile === "string") params.profile = profileLabel(t, params.profile);
    return t(`firstRun.${item.key}.${item.code}` as TranslationKey, params);
  };
  const hint = (item: CheckItem): string | null => {
    if (item.state === "done" || item.state === "unknown" || item.state === "busy") return null;
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
                {item.state !== "done" &&
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
