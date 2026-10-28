import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { useSettings, type GuideLevel, type Language, type Theme } from "@/store/settings";

export function SettingsPage() {
  const t = useT();
  const s = useSettings();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await fetch("/health")).json() as Promise<{ status: string; version: string }>,
  });

  return (
    <div className="animate-fade-in">
      <PageHeader title={t("settings.title")} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Interface" description="Stored in this browser only." />
          <CardBody className="space-y-4">
            <Field label={t("settings.theme")}>
              <Select value={s.theme} onChange={(e) => s.setTheme(e.target.value as Theme)}>
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </Select>
            </Field>
            <Field label={t("settings.language")} hint="Interface and ARVA Guide. Scientific documentation is in English.">
              <Select value={s.language} onChange={(e) => s.setLanguage(e.target.value as Language)}>
                <option value="en">English</option>
                <option value="es">Español</option>
              </Select>
            </Field>
            <Field label={t("settings.guideLevel")}>
              <Select value={s.guideLevel} onChange={(e) => s.setGuideLevel(e.target.value as GuideLevel)}>
                <option value="beginner">Beginner — plain language</option>
                <option value="intermediate">Intermediate — adds methods, limitations and references</option>
                <option value="advanced">Advanced — adds formulas and methodological detail</option>
              </Select>
            </Field>
            <label className="flex items-start gap-2.5">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[#00B4A6]"
                checked={s.showIntro}
                onChange={(e) => s.setShowIntro(e.target.checked)}
              />
              <span className="space-y-0.5">
                <span className="block text-sm">{t("settings.showIntro")}</span>
                <span className="block text-[11px] text-muted-foreground">{t("settings.showIntroHint")}</span>
              </span>
            </label>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="System" />
          <CardBody className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">API status</span>
              <span>{health.data?.status === "ok" ? <span className="text-success">Connected</span> : health.isLoading ? "…" : <span className="text-danger">Unreachable</span>}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">ARVA version</span>
              <span>{health.data?.version ?? "—"}</span>
            </div>
            <div className="flex gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
              <ShieldCheck className="h-4 w-4 shrink-0 text-arva-teal" />
              ARVA runs locally. Sequence data are never sent to external services; external links in the Guide open documentation only.
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
