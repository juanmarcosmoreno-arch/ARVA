import { HelpCircle } from "lucide-react";
import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { GUIDE_BY_ID, localized, type GuideId } from "@/guide/metrics";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useSettings, type GuideLevel } from "@/store/settings";
import { GuideArticle } from "./GuideArticle";

/** The "What does this mean?" button attached to every metric and chart. */
export function Explain({ id, compact = false, className }: { id: GuideId; compact?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  const t = useT();
  const language = useSettings((s) => s.language);
  const level = useSettings((s) => s.guideLevel);
  const setLevel = useSettings((s) => s.setGuideLevel);
  const entry = GUIDE_BY_ID[id];

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex items-center gap-1 rounded-md text-xs text-muted-foreground transition-colors hover:text-arva-teal",
          className,
        )}
        aria-label={`${t("common.whatDoesThisMean")} — ${localized(entry, language).title}`}
      >
        <HelpCircle className="h-3.5 w-3.5" />
        {!compact && <span>{t("common.whatDoesThisMean")}</span>}
      </button>
      <Dialog open={open} onOpenChange={setOpen} title={localized(entry, language).title} className="max-w-xl">
        <div className="mb-4 flex gap-1 rounded-lg bg-muted p-1 text-xs" role="radiogroup" aria-label={t("settings.guideLevel")}>
          {(["beginner", "intermediate", "advanced"] as GuideLevel[]).map((l) => (
            <button
              key={l}
              role="radio"
              aria-checked={level === l}
              onClick={() => setLevel(l)}
              className={cn(
                "flex-1 rounded-md px-2 py-1",
                level === l ? "bg-surface font-medium shadow-sm" : "text-muted-foreground",
              )}
            >
              {t(`guide.level.${l}`)}
            </button>
          ))}
        </div>
        <GuideArticle entry={entry} />
      </Dialog>
    </>
  );
}
