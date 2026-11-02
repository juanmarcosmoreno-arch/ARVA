import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, FileDown, Send, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { GUIDE_BY_ID, localized, type GuideId } from "@/guide/metrics";
import { useT } from "@/i18n";
import { fmtDate } from "@/lib/format";
import { platformApi, projectReportUrl, type AskBody } from "@/lib/platform";
import { useSettings } from "@/store/settings";
import { useAuthStatus } from "./Accounts";

const LINK = "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium hover:bg-muted";

/** Project page: the full project report in each format, in the interface language. */
export function ProjectReportCard({ projectId }: { projectId: string }) {
  const t = useT();
  const language = useSettings((s) => s.language);
  return (
    <Card className="mt-6">
      <CardHeader title={t("preport.title")} description={t("preport.hint")} action={<Explain id="project_report" compact />} />
      <CardBody className="flex flex-wrap gap-2">
        {(["html", "pdf", "json", "csv"] as const).map((f) => (
          <a key={f} className={LINK} href={projectReportUrl(projectId, f, language)}>
            <FileDown className="h-3.5 w-3.5" />{t(`preport.format.${f}`)}
          </a>
        ))}
        <p className="w-full text-[11px] text-muted-foreground">{t("preport.scope")}</p>
      </CardBody>
    </Card>
  );
}

/** Settings → ARVA Assist (administrators): off by default; no provider is bundled with ARVA. */
export function AssistSection() {
  const t = useT();
  const qc = useQueryClient();
  const auth = useAuthStatus();
  const admin = !auth.data?.enabled || auth.data.user?.role === "admin";
  const settings = useQuery({ queryKey: ["assistSettings"], queryFn: platformApi.assistSettings, enabled: admin });
  const audit = useQuery({ queryKey: ["assistAudit"], queryFn: platformApi.assistAudit, enabled: admin });
  const [draft, setDraft] = useState<{ provider: string; endpoint: string; model: string; key: string } | null>(null);
  const save = useMutation({
    mutationFn: (body: Parameters<typeof platformApi.saveAssistSettings>[0]) => platformApi.saveAssistSettings(body),
    onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ["assistSettings"] }); qc.invalidateQueries({ queryKey: ["assistStatus"] }); },
  });
  if (!admin || !settings.data) return null;
  const s = settings.data;
  const d = draft ?? { provider: s.provider ?? "", endpoint: s.endpoint ?? "", model: s.model ?? "", key: "" };
  const body = (enabled: boolean) => ({ enabled, provider: d.provider || null, endpoint: d.endpoint || null, model: d.model || null,
    ...(d.key ? { api_key: d.key } : {}) });
  return (
    <Card className="lg:col-span-2">
      <CardHeader title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" />{t("assist.title")}</span>}
        description={t("assist.hint")} action={<Explain id="assist" compact />} />
      <CardBody className="space-y-4 text-xs">
        <div className="flex items-center gap-2">
          <Badge tone={s.enabled ? "success" : "neutral"}>{s.enabled ? t("assist.on") : t("assist.off")}</Badge>
          {s.endpoint && !s.endpoint_is_local && <Badge tone="warning"><ShieldAlert className="h-3 w-3" />{t("assist.remote")}</Badge>}
          {!s.providers.length && <span className="text-muted-foreground">{t("assist.noProviders")}</span>}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("assist.provider")}>
            <Select value={d.provider} onChange={(e) => setDraft({ ...d, provider: e.target.value })}>
              <option value="">—</option>
              {s.providers.map((p) => <option key={p} value={p}>{p}</option>)}
            </Select>
          </Field>
          <Field label={t("assist.endpoint")} hint={t("assist.endpointHint")}>
            <Input value={d.endpoint} onChange={(e) => setDraft({ ...d, endpoint: e.target.value })} />
          </Field>
          <Field label={t("assist.model")}><Input value={d.model} onChange={(e) => setDraft({ ...d, model: e.target.value })} /></Field>
          <Field label={t("assist.key")} hint={s.key_set ? t("assist.keySet") : t("assist.keyHint")}>
            <Input type="password" autoComplete="off" value={d.key} onChange={(e) => setDraft({ ...d, key: e.target.value })} />
          </Field>
        </div>
        <details><summary className="cursor-pointer text-muted-foreground">{t("assist.instructions")}</summary>
          <p className="mt-1 whitespace-pre-wrap rounded bg-muted p-2">{s.instructions}</p></details>
        <ErrorNote error={save.error} />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={save.isPending || !d.provider} onClick={() => save.mutate(body(true))}>{t("assist.enable")}</Button>
          <Button size="sm" variant="outline" disabled={save.isPending} onClick={() => save.mutate(body(false))}>{t("assist.disable")}</Button>
          {s.key_set && <Button size="sm" variant="ghost" onClick={() => save.mutate({ ...body(s.enabled), clear_key: true })}>{t("assist.clearKey")}</Button>}
        </div>
        <div>
          <div className="mb-1 font-medium">{t("assist.log")}</div>
          {audit.data?.length ? (
            <table className="w-full">
              <tbody>
                {audit.data.slice(0, 20).map((r) => (
                  <tr key={r.id} className="border-t align-top">
                    <td className="py-1 pr-2">{fmtDate(r.at)}</td><td className="pr-2">{r.username ?? "–"}</td>
                    <td className="pr-2">{r.provider}{r.endpoint_host ? ` · ${r.endpoint_host}` : ""}</td>
                    <td className="pr-2">{r.question}</td>
                    <td className="pr-2">{r.included_sequences ? <Badge tone="warning">{t("assist.withSequences")}</Badge> : null}</td>
                    <td><details><summary className="cursor-pointer">{t("assist.sent")}</summary>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[10px]">{JSON.stringify(r.sent, null, 2)}</pre></details></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-muted-foreground">{t("assist.logEmpty")}</p>}
        </div>
      </CardBody>
    </Card>
  );
}

const GUIDE_FOR_ASSIST: GuideId[] = ["discover_stats", "project_report"];

/** Project page: ask ARVA Assist about this project, shown only when an administrator enabled it. */
export function AssistPanel({ projectId }: { projectId: string }) {
  const t = useT();
  const language = useSettings((s) => s.language);
  const status = useQuery({ queryKey: ["assistStatus"], queryFn: platformApi.assistStatus });
  const [question, setQuestion] = useState("");
  const [shown, setShown] = useState<Record<string, unknown> | null>(null);
  const guide = GUIDE_FOR_ASSIST.map((id) => {
    const g = localized(GUIDE_BY_ID[id], language);
    return { id, title: g.title, text: [g.what, g.how, g.interpret, g.limitations].join("\n") };
  });
  const body: AskBody = { question, about_project_id: projectId, guide };
  const preview = useMutation({ mutationFn: () => platformApi.assistPreview(body), onSuccess: (r) => setShown(r.payload) });
  const ask = useMutation({ mutationFn: () => platformApi.assistAsk(body) });
  if (!status.data?.enabled) return null;
  return (
    <Card className="mt-6">
      <CardHeader title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" />{t("assist.ask")}</span>}
        description={status.data.endpoint_is_local ? t("assist.askLocal") : t("assist.askRemote")} action={<Explain id="assist" compact />} />
      <CardBody className="space-y-3 text-xs">
        <Textarea rows={3} value={question} placeholder={t("assist.placeholder")} onChange={(e) => setQuestion(e.target.value)} />
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={!question.trim() || preview.isPending} onClick={() => preview.mutate()}>{t("assist.preview")}</Button>
          <Button size="sm" disabled={!question.trim() || ask.isPending} onClick={() => ask.mutate()}><Send className="h-4 w-4" />{t("assist.send")}</Button>
        </div>
        <p className="text-muted-foreground">{t("assist.noSequences")}</p>
        {shown && <pre className="max-h-60 overflow-auto rounded bg-muted p-2 text-[10px]">{JSON.stringify(shown, null, 2)}</pre>}
        <ErrorNote error={ask.error ?? preview.error} />
        {ask.data && <div className="whitespace-pre-wrap rounded border p-3 text-sm">{ask.data.answer}</div>}
      </CardBody>
    </Card>
  );
}
