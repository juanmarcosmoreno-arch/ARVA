import { useState } from "react";
import { GuideArticle } from "@/components/guide/GuideArticle";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { GUIDE, localized } from "@/guide/metrics";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useSettings, type GuideLevel } from "@/store/settings";

export function GuidePage() {
  const t = useT();
  const language = useSettings((s) => s.language);
  const level = useSettings((s) => s.guideLevel);
  const setLevel = useSettings((s) => s.setGuideLevel);
  const [active, setActive] = useState(GUIDE[0].id);
  const entry = GUIDE.find((g) => g.id === active)!;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title={t("guide.title")}
        subtitle={t("guide.subtitle")}
        actions={
          <div className="inline-flex rounded-lg bg-muted p-1 text-xs" role="radiogroup" aria-label={t("settings.guideLevel")}>
            {(["beginner", "intermediate", "advanced"] as GuideLevel[]).map((l) => (
              <button
                key={l}
                role="radio"
                aria-checked={level === l}
                onClick={() => setLevel(l)}
                className={cn("rounded-md px-3 py-1 capitalize", level === l ? "bg-surface font-medium shadow-sm" : "text-muted-foreground")}
              >
                {l}
              </button>
            ))}
          </div>
        }
      />
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        <nav aria-label="Guide topics">
          <ul className="space-y-0.5">
            {GUIDE.map((g) => (
              <li key={g.id}>
                <button
                  onClick={() => setActive(g.id)}
                  className={cn(
                    "w-full rounded-lg px-3 py-2 text-left text-sm",
                    active === g.id ? "bg-arva-teal/10 font-medium text-foreground" : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {localized(g, language).title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <Card className="p-6">
          <h2 className="mb-4 text-lg font-semibold">{localized(entry, language).title}</h2>
          <GuideArticle entry={entry} />
        </Card>
      </div>
    </div>
  );
}
