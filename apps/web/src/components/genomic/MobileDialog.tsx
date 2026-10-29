import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { compatibilityText } from "@/components/databases/shared";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { assemblyOptions } from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import { flagOf, initialMobileForm, MOBILE_METHODS, mobileBody, type MobileForm, mobileProblems, settingKind } from "@/lib/mobile";
import type { Assembly, MobileMethod, MobilePlan } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Shows what one plasmid or mobile-element search will do here — the tool and whether ARVA validated it, the
 * database (or the models the tool bundles), every setting with the tool's own default — and runs it on the chosen
 * assembly after an explicit confirmation. */
export function MobileDialog({ open, onOpenChange, sampleId, assemblies, method: initialMethod }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  assemblies: Assembly[];
  method?: MobileMethod;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const options = assemblyOptions(assemblies);
  const last = options[options.length - 1]?.assembly.id ?? "";
  const [form, setForm] = useState<MobileForm>(() => initialMobileForm(last, initialMethod));
  useEffect(() => {
    if (open) setForm(initialMobileForm(last, initialMethod));
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const set = <K extends keyof MobileForm>(key: K, value: MobileForm[K]) =>
    setForm((f) => ({ ...f, [key]: value, ...(key === "method" ? { settings: {}, databaseId: "" } : {}), confirmed: key === "confirmed" ? (value as boolean) : false }));
  const setSetting = (key: string, value: string) => setForm((f) => ({ ...f, settings: { ...f.settings, [key]: value }, confirmed: false }));

  const plan = useQuery({
    queryKey: ["mobilePlan", form.assemblyId, form.method, form.databaseId],
    queryFn: () => api.mobilePreview(form.assemblyId, form.method, form.databaseId || null),
    enabled: open && Boolean(form.assemblyId),
    retry: false,
  });
  const p = plan.data;
  const problems = mobileProblems(form, p);
  const run = useMutation({
    mutationFn: () => api.runMobile(form.assemblyId, mobileBody(form, p)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      queryClient.invalidateQueries({ queryKey: ["mobile", sampleId] });
      onOpenChange(false);
    },
  });
  const circular = Object.values(p?.circularity ?? {});
  const known = circular.filter((c) => c.circular != null).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("mobile.title")} description={t("mobile.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <section className="space-y-2">
          <h4 className="text-sm font-semibold">{t("mlst.assembly")}</h4>
          <Select value={form.assemblyId} onChange={(e) => set("assemblyId", e.target.value)} aria-label={t("mlst.assembly")}>
            {options.map(({ assembly: a, depth }) => (
              <option key={a.id} value={a.id}>
                {"  ".repeat(depth)}
                {depth ? "↳ " : ""}
                {a.assembler} {a.assembler_version} · {fmtInt(a.stats.contig_count)} contigs · {fmtBases(a.stats.total_length)} · {fmtDate(a.created_at)} · {a.id.slice(0, 8)}
              </option>
            ))}
          </Select>
          {p && p.assembly.synthetic_evidence.length > 0 && <SyntheticNote evidence={p.assembly.synthetic_evidence} />}
        </section>

        <section className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <h4 className="text-sm font-semibold">{t("mobile.methodLabel")}</h4>
            <Explain id="mobile_element" compact />
          </div>
          <div className="space-y-1.5 text-xs">
            {MOBILE_METHODS.map((m) => (
              <label key={m} className="flex items-start gap-2">
                <input type="radio" className={CHECK} checked={form.method === m} onChange={() => set("method", m)} />
                <span>
                  <span className="font-medium">{t(`mobile.method.${m}` as TranslationKey)}</span>
                  <span className="block text-muted-foreground">{t(`mobile.methodHint.${m}` as TranslationKey)}</span>
                </span>
              </label>
            ))}
          </div>
        </section>

        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("mlst.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && <ToolLine plan={p} />}

        {p && (p.databases.length > 0 || p.database || p.problems.some((x) => x.code === "no_database")) && (
          <section className="space-y-2">
            <h4 className="text-sm font-semibold">{t("amr.database")}</h4>
            {p.databases.length > 0 ? (
              <Select value={form.databaseId || p.database?.id || ""} onChange={(e) => set("databaseId", e.target.value)} aria-label={t("amr.database")}>
                {p.databases.map((d) => (
                  <option key={d.id} value={d.id} disabled={d.compatibility.status === "incompatible" || !d.available}>
                    {d.name} {d.version ?? ""}
                    {d.is_default ? ` · ${t("databases.badge.default")}` : ""}
                  </option>
                ))}
              </Select>
            ) : (
              <p className="text-xs text-amber-700 dark:text-warning">
                {t("mobile.noDatabase")}{" "}
                <Link to="/tools#reference-databases" className="text-arva-royal hover:underline dark:text-arva-cyan">
                  {t("amr.openDatabases")}
                </Link>
              </p>
            )}
            {p.database && <DatabaseTerms plan={p} />}
          </section>
        )}
        {p?.models && <p className="text-xs text-muted-foreground">{t("mobile.models", { files: p.models.files.join(", "), checksum: p.models.checksum.slice(0, 19) })}</p>}

        {p && (
          <section className="space-y-2">
            <h4 className="text-sm font-semibold">{t("mlst.options")}</h4>
            <p className="text-xs text-muted-foreground">{t("mobile.optionsHint")}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(p.defaults).map(([key, def]) =>
                settingKind(def) === "bool" ? (
                  <label key={key} className="flex items-start gap-2 text-xs">
                    <input type="checkbox" className={CHECK} checked={(form.settings[key] ?? def) === "True"} onChange={(e) => setSetting(key, e.target.checked ? "True" : "False")} />
                    <code>{flagOf(form.method, key)}</code>
                  </label>
                ) : (
                  <Field key={key} label={flagOf(form.method, key)} hint={p.tool_defaults[key.replace(/_/g, "-")] ?? p.tool_defaults[key] ? t("mobile.toolDefault", { value: p.tool_defaults[key.replace(/_/g, "-")] ?? p.tool_defaults[key] }) : undefined}>
                    <Input type="number" step="any" value={form.settings[key] ?? def} onChange={(e) => setSetting(key, e.target.value)} />
                  </Field>
                ),
              )}
              <Field label={t("annotation.threads")} hint={t("annotation.threadsHint", { max: p.tool.max_threads, default: p.tool.default_threads })}>
                <Input type="number" min={1} max={p.tool.max_threads} placeholder={String(p.tool.default_threads)} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
              </Field>
            </div>
            {p.defaults_match === false && (
              <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
                <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("mlst.defaultsDiffer")}
              </p>
            )}
            {form.method === "integronfinder" && <p className="text-xs text-muted-foreground">{t("mobile.topology", { known: fmtInt(known), total: fmtInt(circular.length) })}</p>}
          </section>
        )}

        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t(`mobile.note.${form.method}` as TranslationKey)}</span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={form.confirmed} onChange={(e) => set("confirmed", e.target.checked)} />
          <span>{t("mobile.confirm")}</span>
        </label>
        {(problems.length > 0 || (p?.problems.length ?? 0) > 0) && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{t(k, { max: p?.tool.max_threads ?? "?" })}</li>
            ))}
            {p?.problems.map((x) => (
              <li key={x.code} className="text-amber-700 dark:text-warning">
                {t(`mobile.planProblem.${x.code}` as TranslationKey, { tool: "?", status: "?", name: "?", files: "?", kind: "?", detail: "", ...x.params })}
              </li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!p || p.tool.status !== "available" || problems.length > 0 || p.problems.length > 0 || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("mlst.starting") : t("mobile.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function DatabaseTerms({ plan }: { plan: Pick<MobilePlan, "database"> }) {
  const t = useT();
  const d = plan.database;
  if (!d) return null;
  return (
    <div className="space-y-0.5 text-xs text-muted-foreground">
      <p>
        {t("mobile.dbLine", { name: d.name, version: d.version ?? "?", path: d.host_path })} {compatibilityText(t, d.compatibility)}
      </p>
      <p>
        {t("mobile.dbLicence", { licence: d.licence })} {t("mobile.dbCite", { citation: d.citation })}
      </p>
      {d.unconfirmed.length > 0 && <p>{t("mobile.dbUnconfirmed", { n: d.unconfirmed.length })}</p>}
    </div>
  );
}

function ToolLine({ plan }: { plan: MobilePlan }) {
  const t = useT();
  const tool = plan.tool;
  if (tool.status !== "available") return <ErrorNote error={t("mobile.unavailable", { tool: tool.name, message: toolMessage(t, { ...tool, min_version: "" }) || tool.status })} />;
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>
        {t("mobile.toolLine", { tool: tool.name, version: tool.version ?? "?", licence: tool.license })}{" "}
        <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
          {t("annotation.cite")}
        </a>
      </div>
      {!tool.version_validated && (
        <p className="flex gap-1.5 text-amber-700 dark:text-warning">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("mobile.notValidated", { tool: tool.name, version: tool.version ?? "?" })}
        </p>
      )}
    </div>
  );
}
