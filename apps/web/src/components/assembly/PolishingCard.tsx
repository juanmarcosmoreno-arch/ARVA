import type { EChartsOption } from "echarts";
import { AlertTriangle, ArrowRight, Download, Info } from "lucide-react";
import type { ReactNode } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { assemblyLabel } from "@/lib/assembly";
import { escapeHtml, fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { CHANGE_KINDS, type CompareRow, assemblyRows, changeSeries, indirectRows, lineage, polishingSummary, trend } from "@/lib/polishing";
import { basename } from "@/lib/results";
import type { AnalysisJobDetail, Assembly, Changes, PolishingObservation, PolishingSummary } from "@/lib/types";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground";
const TD = "px-2 py-1.5 tabular-nums";
const LINK_BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted";

/** One polishing run: what changed in the sequence (direct evidence), how the reads agree with the draft and the
 * polished assembly (indirect indicators), the assembly statistics before and after, and the lineage. */
export function PolishingCard({ job, assemblies }: { job: AnalysisJobDetail; assemblies: Assembly[] }) {
  const t = useT();
  const s = polishingSummary(job);
  if (!s) return null;
  const byId = new Map(assemblies.map((a) => [a.id, a]));
  const draft = byId.get(s.draft.assembly_id);
  const polished = byId.get(s.polished_assembly_id);
  const draftLabel = draft ? assemblyLabel(draft) : `${s.draft.assembler} ${s.draft.assembler_version} · ${s.draft.assembly_id.slice(0, 8)}`;
  const chain = polished ? lineage(polished, assemblies) : [];
  const files = (job.output_paths ?? []).map(basename).filter((n) => n !== "polished.fasta");
  return (
    <Card>
      <CardHeader
        title={t("polishing.result.title", { polisher: s.polisher, version: s.polisher_version, draft: draftLabel })}
        description={`${fmtDate(job.finished_at ?? job.created_at)} · ${t("polishing.result.rounds", { run: s.rounds_run, requested: s.rounds_requested })}${s.stopped_early ? ` · ${t("polishing.result.stoppedEarly")}` : ""}`}
        action={
          <div className="flex flex-wrap gap-2">
            <a className={LINK_BUTTON} href={api.assemblyContigsUrl(s.polished_assembly_id)}>
              <Download className="h-3.5 w-3.5" /> {t("polishing.download")}
            </a>
            <Explain id="polishing_evidence" compact />
          </div>
        }
      />
      <CardBody className="space-y-5 pt-3">
        {chain.length > 1 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label={t("polishing.lineage")}>
            <span className="font-medium">{t("polishing.lineage")}:</span>
            {chain.map((a, i) => (
              <span key={a.id} className="flex items-center gap-1.5">
                {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden />}
                <Badge tone={a.kind === "polished" ? "teal" : "neutral"}>{assemblyLabel(a)}</Badge>
              </span>
            ))}
          </div>
        )}
        <Followups summary={s} />

        <Panel tone="direct" title={t("polishing.evidence.direct")} hint={t("polishing.evidence.directHint")}>
          <DirectEvidence summary={s} />
        </Panel>
        {changeSeries(s).length > 0 && <ChangesChart summary={s} />}

        <Panel tone="indirect" title={t("polishing.evidence.indirect")} hint={t("polishing.evidence.indirectHint", { aligner: s.indirect.aligner })}>
          <CompareTable rows={indirectRows(s)} showTrend />
        </Panel>

        <Panel tone="stats" title={t("polishing.evidence.stats")} hint={t("polishing.evidence.statsHint")}>
          <CompareTable rows={assemblyRows(s)} />
        </Panel>

        {s.observations.length > 0 && (
          <ul className="space-y-1.5">
            {s.observations.map((o, i) => (
              <li key={`${o.code}-${i}`} className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                <span>{observation(t, o)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="flex gap-1.5 text-[11px] text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("polishing.notCorrection")}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {t("polishing.helpers", { tools: [`${s.polisher} ${s.polisher_version}`, ...s.helpers.map((h) => `${h.name} ${h.version ?? "?"}`)].join(", ") })}
        </p>
        {files.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">{t("polishing.files", { count: files.length })}</summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {files.map((n) => (
                <a key={n} className={LINK_BUTTON} href={api.jobOutputUrl(job.id, n, true)}>
                  <Download className="h-3.5 w-3.5" /> {n}
                </a>
              ))}
            </div>
          </details>
        )}
      </CardBody>
    </Card>
  );
}

function Panel({ tone, title, hint, children }: { tone: "direct" | "indirect" | "stats"; title: string; hint: string; children: ReactNode }) {
  const t = useT();
  return (
    <section className="space-y-2" aria-label={title}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold">{title}</h4>
        {tone !== "stats" && <Badge tone={tone === "direct" ? "teal" : "blue"}>{t(tone === "direct" ? "polishing.badge.direct" : "polishing.badge.indirect")}</Badge>}
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
      {children}
    </section>
  );
}

function observation(t: ReturnType<typeof useT>, o: PolishingObservation): string {
  const p = o.params;
  if (o.code === "ends_trimmed") {
    return t(p.circular ? "polishing.obs.ends_trimmed_circular" : "polishing.obs.ends_trimmed", { contig: String(p.contig), start: fmtInt(Number(p.start)), end: fmtInt(Number(p.end)) });
  }
  if (o.code === "contigs_unaligned") return t("polishing.obs.contigs_unaligned", { count: String(p.count) });
  if (o.code === "edit_distance_increased") return t("polishing.obs.edit_distance_increased", { before: fmtNum(Number(p.before), 4), after: fmtNum(Number(p.after), 4) });
  if (o.code === "no_changes") return t("polishing.obs.no_changes");
  return o.message;
}

function Followups({ summary: s }: { summary: PolishingSummary }) {
  const t = useT();
  const f = s.followups ?? {};
  const lines = [
    f.pilon_job_id && t("polishing.followup.pilon"),
    f.pilon_error && t("polishing.followup.pilonError", { error: f.pilon_error }),
    f.quast_job_id && t("polishing.followup.quast"),
    f.quast_error && t("polishing.followup.quastError", { error: f.quast_error }),
  ].filter(Boolean) as string[];
  if (!lines.length) return null;
  return (
    <ul className="space-y-0.5 text-xs text-muted-foreground">
      {lines.map((l) => (
        <li key={l}>{l}</li>
      ))}
    </ul>
  );
}

function changesText(c: Changes | null | undefined, kind: keyof Changes): string {
  if (!c) return "—";
  const v = c[kind];
  return v.events === v.bases ? fmtInt(v.events) : `${fmtInt(v.events)} (${fmtInt(v.bases)} bp)`;
}

function DirectEvidence({ summary: s }: { summary: PolishingSummary }) {
  const t = useT();
  const d = s.direct.dnadiff;
  const rows: [string, string][] = [];
  if (d) {
    rows.push(
      [t("polishing.direct.substitutions"), fmtInt(d.events.substitutions)],
      [t("polishing.direct.insertions"), `${fmtInt(d.events.insertions)} (${fmtInt(d.events.inserted_bases)} bp)`],
      [t("polishing.direct.deletions"), `${fmtInt(d.events.deletions)} (${fmtInt(d.events.deleted_bases)} bp)`],
      [t("polishing.direct.unalignedDraft"), `${fmtInt(d.before.unaligned_bases)} bp`],
      [t("polishing.direct.unalignedPolished"), `${fmtInt(d.after.unaligned_bases)} bp`],
      [t("polishing.direct.breakpoints"), fmtInt(d.before.breakpoints)],
      [t("polishing.direct.identity"), `${fmtNum(d.before.one_to_one_identity, 2)} %`],
    );
  }
  const pilon = s.direct.pilon_changes;
  return (
    <div className="space-y-2">
      {d ? (
        <>
          <p className="text-xs text-muted-foreground">{t("polishing.direct.dnadiffSource")}</p>
          <table className="w-full max-w-xl text-xs">
            <tbody className="divide-y">
              {rows.map(([k, v]) => (
                <tr key={k}>
                  <th scope="row" className="px-2 py-1.5 text-left font-normal">
                    {k}
                  </th>
                  <td className={TD}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p className="text-xs text-amber-700 dark:text-warning">{t(pilon ? "polishing.direct.onlyPilon" : "polishing.direct.none")}</p>
      )}
      {pilon && (
        <>
          <p className="text-xs text-muted-foreground">{t("polishing.direct.pilonSource")}</p>
          <table className="w-full max-w-xl text-xs">
            <thead className="bg-muted/50">
              <tr>
                {CHANGE_KINDS.map((k) => (
                  <th key={k} className={TH}>
                    {t(`polishing.kind.${k}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                {CHANGE_KINDS.map((k) => (
                  <td key={k} className={TD}>
                    {changesText(pilon, k)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function CompareTable({ rows, showTrend = false }: { rows: CompareRow[]; showTrend?: boolean }) {
  const t = useT();
  const fmt = (v: number | null, digits: number) => (v === null ? "—" : digits ? fmtNum(v, digits) : fmtInt(v));
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50">
          <tr>
            <th className={TH}>{t("polishing.col.metric")}</th>
            <th className={TH}>{t("polishing.col.before")}</th>
            <th className={TH}>{t("polishing.col.after")}</th>
            {showTrend && <th className={TH}>{t("polishing.col.trend")}</th>}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => {
            const tr = trend(r);
            return (
              <tr key={r.key}>
                <th scope="row" className="px-2 py-1.5 text-left font-normal">
                  {t(r.label)}
                </th>
                <td className={TD}>{fmt(r.before, r.digits)}</td>
                <td className={TD}>{fmt(r.after, r.digits)}</td>
                {showTrend && <td className="px-2 py-1.5">{tr ? <Badge tone={tr === "improved" ? "success" : tr === "worse" ? "warning" : "neutral"}>{t(`polishing.trend.${tr}`)}</Badge> : "—"}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Changes by type per round (events), from dnadiff or, without it, Pilon's list of changes. */
function ChangesChart({ summary: s }: { summary: PolishingSummary }) {
  const t = useT();
  const th = useChartTheme();
  const series = changeSeries(s);
  const sources = [...new Set(series.map((r) => r.source))];
  const categories = series.map((r) => t("polishing.chart.round", { n: r.round }));
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { ...baseOption(th).grid, top: 36 },
    legend: { top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: th.text, fontSize: 11 } },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const items = p as { seriesName: string; value: number; axisValue: string }[];
        return `<b>${escapeHtml(items[0]?.axisValue ?? "")}</b>` + items.map((i) => `<div>${escapeHtml(i.seriesName)}: <b>${fmtInt(i.value)}</b></div>`).join("");
      },
    },
    xAxis: { type: "category", data: categories, ...axisStyle(th, t("polishing.chart.rounds"), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", minInterval: 1, ...axisStyle(th, t("polishing.chart.events"), { nameGap: 40 }) },
    series: CHANGE_KINDS.map((k, i) => ({
      name: t(`polishing.kind.${k}`),
      type: "bar" as const,
      data: series.map((r) => r.values[k]),
      itemStyle: { color: th.series[i], borderRadius: [3, 3, 0, 0] as [number, number, number, number] },
    })),
  };
  return (
    <ChartCard
      title={t("polishing.chart.title")}
      subtitle={t("polishing.chart.sub", { source: sources.map((x) => t(x === "dnadiff" ? "polishing.source.dnadiff" : "polishing.source.pilon")).join(", ") })}
      explain="polishing_evidence"
      option={option}
      height={240}
      filePrefix={`arva_${s.polisher}_${s.polished_assembly_id.slice(0, 8)}`}
      table={{
        columns: [t("polishing.chart.rounds"), ...CHANGE_KINDS.map((k) => t(`polishing.kind.${k}`))],
        rows: series.map((r) => [t("polishing.chart.round", { n: r.round }), ...CHANGE_KINDS.map((k) => r.values[k])]),
      }}
    />
  );
}
