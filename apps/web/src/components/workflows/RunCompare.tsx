import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDuration } from "@/lib/format";
import { STATUS_TONE } from "@/lib/workflows";
import { RunStatusBadge } from "./RunView";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return typeof v === "number" ? String(Math.round(v * 1000) / 1000) : typeof v === "string" ? v : JSON.stringify(v);
}

/** Two runs side by side: the parameters that differ, and for each step and sample both statuses, tool versions,
 * times and the numbers their outputs recorded. Differences are listed, not interpreted. */
export function RunCompare({ a, b }: { a: string; b: string }) {
  const t = useT();
  const cmp = useQuery({ queryKey: ["batchCompare", a, b], queryFn: () => api.compareBatches(a, b) });
  if (cmp.isLoading) return <Skeleton className="h-64" />;
  if (!cmp.data) return <ErrorNote error={cmp.error} />;
  const c = cmp.data;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2">
        {[c.a, c.b].map((r, i) => (
          <Card key={r.id}>
            <CardBody className="space-y-1 py-3 text-xs">
              <p className="text-[11px] font-semibold uppercase text-muted-foreground">{i === 0 ? "A" : "B"}</p>
              <p className="text-sm font-medium"><Link className={LINK} to={`/workflows/runs/${r.id}`}>{r.name}</Link> <RunStatusBadge status={r.status} /></p>
              <p className="text-muted-foreground">{r.workflow_name} · {t("wf.versionShort", { v: r.version ?? "?" })} · <span className="font-mono">{r.definition_sha256.slice(0, 12)}…</span></p>
              <p>{t("wf.tile.steps", { done: r.counts.completed, total: r.total })} · {fmtDuration(r.job_seconds)}</p>
            </CardBody>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader title={t("wf.paramDiff")} description={t("wf.paramDiffHint")} />
        <CardBody className="pt-3 text-xs">
          {c.parameters.length === 0 ? <p className="text-muted-foreground">{t("wf.sameParams")}</p> : (
            <table><tbody>
              {c.parameters.map((p, i) => (
                <tr key={i} className="border-t"><td className="py-1 pr-3 font-mono">{p.node}.{p.path}</td><td className="pr-3 font-mono">{show(p.before)}</td><td className="font-mono">{show(p.after)}</td></tr>
              ))}
            </tbody></table>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("wf.stepDiff")} description={t("wf.stepDiffHint")} />
        <CardBody className="overflow-x-auto pt-3 text-xs">
          <table className="w-full">
            <thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("wf.step")}</th><th>{t("wf.sample")}</th><th>A</th><th>B</th><th>{t("wf.metrics")}</th></tr></thead>
            <tbody>
              {c.rows.map((r, i) => (
                <tr key={i} className="border-t align-top">
                  <td className="py-1 pr-2 font-mono">{r.node_id}</td>
                  <td className="pr-2">{r.sample_code ?? t("wf.setScope")}</td>
                  <td className="pr-2"><Badge tone={STATUS_TONE[r.a.status]}>{t(`wf.status.${r.a.status}` as TranslationKey)}</Badge> <span className="text-muted-foreground">{r.a.tool_version ?? ""} {fmtDuration(r.a.duration_seconds)}</span></td>
                  <td className="pr-2">{r.b ? <><Badge tone={STATUS_TONE[r.b.status]}>{t(`wf.status.${r.b.status}` as TranslationKey)}</Badge> <span className="text-muted-foreground">{r.b.tool_version ?? ""} {fmtDuration(r.b.duration_seconds)}</span>{r.same_job && <span className="ml-1 text-muted-foreground">{t("wf.sameJob")}</span>}</> : "—"}</td>
                  <td>
                    {r.metrics.filter((m) => show(m.a) !== show(m.b) || r.metrics.length <= 6).map((m) => (
                      <p key={m.key} className={show(m.a) !== show(m.b) ? "font-medium" : "text-muted-foreground"}><span className="font-mono">{m.key}</span>: {show(m.a)} → {show(m.b)}</p>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </div>
  );
}
