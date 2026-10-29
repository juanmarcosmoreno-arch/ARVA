import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/misc";
import { DiagnosticsSection } from "@/components/settings/DiagnosticsSection";
import { PerformanceSection } from "@/components/settings/PerformanceSection";
import { StorageSection } from "@/components/settings/StorageSection";
import { useT } from "@/i18n";
import { useSettings, type GuideLevel, type Language, type Theme } from "@/store/settings";

export function SettingsPage() {
  const t = useT();
  const s = useSettings();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await fetch("/health")).json() as Promise<{ status: string; version: string; storage?: string }>,
  });

  return (
    <div className="animate-fade-in">
      <PageHeader title={t("settings.title")} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("settings.interface")} description={t("settings.interfaceHint")} />
          <CardBody className="space-y-4">
            <Field label={t("settings.theme")}>
              <Select value={s.theme} onChange={(e) => s.setTheme(e.target.value as Theme)}>
                <option value="system">{t("settings.theme.system")}</option>
                <option value="light">{t("settings.theme.light")}</option>
                <option value="dark">{t("settings.theme.dark")}</option>
              </Select>
            </Field>
            <Field label={t("settings.language")} hint={t("settings.languageHint")}>
              <Select value={s.language} onChange={(e) => s.setLanguage(e.target.value as Language)}>
                <option value="en">English</option>
                <option value="es">Español</option>
              </Select>
            </Field>
            <Field label={t("settings.guideLevel")}>
              <Select value={s.guideLevel} onChange={(e) => s.setGuideLevel(e.target.value as GuideLevel)}>
                <option value="beginner">{t("settings.level.beginner")}</option>
                <option value="intermediate">{t("settings.level.intermediate")}</option>
                <option value="advanced">{t("settings.level.advanced")}</option>
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
          <CardHeader title={t("settings.system")} />
          <CardBody className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t("settings.apiStatus")}</span>
              <span>
                {health.data?.status === "ok" ? (
                  <span className="text-success">{t("settings.apiConnected")}</span>
                ) : health.data?.status === "degraded" ? (
                  <span className="text-warning">{t("settings.apiDegraded")}</span>
                ) : health.isLoading ? (
                  "…"
                ) : (
                  <span className="text-danger">{t("settings.apiUnreachable")}</span>
                )}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t("settings.version")}</span>
              <span>{health.data?.version ?? "—"}</span>
            </div>
            <div className="flex gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
              <ShieldCheck className="h-4 w-4 shrink-0 text-arva-teal" />
              {t("settings.privacy")}
            </div>
          </CardBody>
        </Card>
        <StorageSection />
        <PerformanceSection />
        <DiagnosticsSection />
      </div>
    </div>
  );
}
