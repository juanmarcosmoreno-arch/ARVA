import { useQuery } from "@tanstack/react-query";
import { ClipboardCopy, Download, LifeBuoy } from "lucide-react";
import { useState } from "react";
import { CopyErrorDetails } from "@/components/diagnostics/CopyErrorDetails";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { WINDOWS, copyText, entryMessage, fetchReport, recentErrors, reportUrl } from "@/lib/diagnostics";
import { fmtDate } from "@/lib/format";
import { useSettings } from "@/store/settings";

/** Settings → Diagnostics: the recent errors and the diagnostic report to copy (Markdown, for a chat) or download (a
 * zip with the same as JSON), with what it holds and never holds. Nothing is sent anywhere. */
export function DiagnosticsSection() {
  const t = useT();
  const anonymise = useSettings((s) => s.diagnosticsAnonymise);
  const setAnonymise = useSettings((s) => s.setDiagnosticsAnonymise);
  const [includeLogs, setIncludeLogs] = useState(true);
  const [sinceHours, setSinceHours] = useState<number>(168);
  const [copy, setCopy] = useState<{ state: "idle" | "busy" | "copied" | "failed"; error?: string }>({ state: "idle" });
  const errors = useQuery({ queryKey: ["errors", sinceHours], queryFn: () => recentErrors(20, sinceHours), refetchInterval: 30_000 });
  const options = { anonymise, includeLogs, sinceHours };

  async function copyReport() {
    setCopy({ state: "busy" });
    try {
      await copyText(await fetchReport(options));
      setCopy({ state: "copied" });
    } catch (err) {
      setCopy({ state: "failed", error: err instanceof Error ? err.message : String(err) });
    }
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader title={t("diagnostics.title")} description={t("diagnostics.subtitle")} action={<LifeBuoy className="h-4 w-4 text-arva-teal" aria-hidden />} />
      <CardBody className="space-y-5 text-sm">
        <div className="space-y-1 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
          <p>{t("diagnostics.included")}</p>
          <p>{t("diagnostics.excluded")}</p>
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex items-start gap-2.5">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#00B4A6]" checked={anonymise} onChange={(e) => setAnonymise(e.target.checked)} />
            <span className="space-y-0.5">
              <span className="block">{t("diagnostics.anonymise")}</span>
              <span className="block text-[11px] text-muted-foreground">{t("diagnostics.anonymiseHint")}</span>
            </span>
          </label>
          <label className="flex items-start gap-2.5">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#00B4A6]" checked={includeLogs} onChange={(e) => setIncludeLogs(e.target.checked)} />
            <span>{t("diagnostics.includeLogs")}</span>
          </label>
          <Field label={t("diagnostics.window")}>
            <Select value={sinceHours} onChange={(e) => setSinceHours(Number(e.target.value))}>
              {WINDOWS.map((h) => (
                <option key={h} value={h}>
                  {t(`diagnostics.window.${h}` as TranslationKey)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={copyReport} disabled={copy.state === "busy"}>
            <ClipboardCopy className="h-4 w-4" aria-hidden /> {t("diagnostics.copy")}
          </Button>
          <a
            href={reportUrl({ ...options, format: "zip" })}
            className="inline-flex h-10 items-center gap-2 rounded-lg border bg-surface px-4 text-sm font-medium hover:bg-muted"
          >
            <Download className="h-4 w-4" aria-hidden /> {t("diagnostics.download")}
          </a>
          {copy.state === "copied" && <span className="text-xs text-success">{t("diagnostics.copied")}</span>}
          {copy.state === "failed" && <span role="alert" className="text-xs text-danger">{t("diagnostics.copyFailed", { error: copy.error ?? "" })}</span>}
        </div>
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("diagnostics.recent")}</h4>
          {errors.isLoading ? (
            <Skeleton className="h-24" />
          ) : errors.error ? (
            <ErrorNote error={errors.error} />
          ) : !errors.data?.length ? (
            <p className="text-xs text-muted-foreground">{t("diagnostics.noErrors")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-1.5 pr-3 font-medium">{t("diagnostics.col.id")}</th>
                    <th className="py-1.5 pr-3 font-medium">{t("diagnostics.col.time")}</th>
                    <th className="py-1.5 pr-3 font-medium">{t("diagnostics.col.component")}</th>
                    <th className="py-1.5 pr-3 font-medium">{t("diagnostics.col.message")}</th>
                    <th className="py-1.5 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {errors.data.map((e) => (
                    <tr key={e.id} className="border-b align-top last:border-0">
                      <td className="py-2 pr-3 font-mono">{e.id}</td>
                      <td className="whitespace-nowrap py-2 pr-3">{fmtDate(e.time)}</td>
                      <td className="py-2 pr-3">{componentName(t, e.component)}</td>
                      <td className={e.severity === "error" ? "py-2 pr-3 text-danger" : "py-2 pr-3"}>{entryMessage(t, e)}</td>
                      <td className="py-2">
                        <CopyErrorDetails errorId={e.id} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function componentName(t: (key: TranslationKey) => string, component: string) {
  const key = `diagnostics.component.${component}`;
  return ["api", "worker", "job", "web", "launcher"].includes(component) ? t(key as TranslationKey) : component;
}
