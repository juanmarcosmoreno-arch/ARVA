import { useQuery } from "@tanstack/react-query";
import { GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { STATUS_COLOR } from "@/lib/workflows";
import { RunStatusBadge } from "./RunView";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";

/** The analysis timeline's branches for one sample: every workflow run that included it, nested under the run it
 * branched from, with what changed and this sample's steps. A branch never overwrites earlier results. */
export function SampleBranches({ sampleId }: { sampleId: string }) {
  const t = useT();
  const runs = useQuery({ queryKey: ["sampleBranches", sampleId], queryFn: () => api.sampleBranches(sampleId) });
  if (!runs.data?.length) return null;
  const children = new Map<string | null, typeof runs.data>();
  const ids = new Set(runs.data.map((r) => r.id));
  for (const r of runs.data) {
    const parent = r.parent_run_id && ids.has(r.parent_run_id) ? r.parent_run_id : null;
    children.set(parent, [...(children.get(parent) ?? []), r]);
  }
  const render = (parent: string | null, depth: number): JSX.Element[] =>
    (children.get(parent) ?? []).flatMap((r) => [
      <li key={r.id} className="space-y-0.5" style={{ marginLeft: depth * 18 }}>
        <p className="flex flex-wrap items-center gap-1.5">
          {depth > 0 && <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />}
          <Link className={LINK} to={`/workflows/runs/${r.id}`}>{r.name}</Link>
          <RunStatusBadge status={r.status} />
          <span className="text-muted-foreground">{fmtDate(r.created_at)}</span>
        </p>
        {r.branch_changes?.map((c, i) => (
          <p key={i} className="font-mono text-[10px] text-muted-foreground">{c.node}.{c.path}: {JSON.stringify(c.before)} → {JSON.stringify(c.after)}</p>
        ))}
        <p className="flex flex-wrap gap-1.5">
          {r.steps.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]" title={t(`wf.status.${s.status}` as TranslationKey)}>
              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: STATUS_COLOR[s.status], opacity: s.reused_from_item_id ? 0.55 : 1 }} />
              <span className="font-mono">{s.node_id}</span>
              {s.reused_from_item_id && <span className="text-muted-foreground">{t("wf.reused")}</span>}
            </span>
          ))}
        </p>
      </li>,
      ...render(r.id, depth + 1),
    ]);
  return (
    <Card>
      <CardHeader title={t("wf.sampleBranches")} description={t("wf.sampleBranchesHint")} />
      <CardBody className="pt-3 text-xs"><ul className="space-y-2">{render(null, 0)}</ul></CardBody>
    </Card>
  );
}
