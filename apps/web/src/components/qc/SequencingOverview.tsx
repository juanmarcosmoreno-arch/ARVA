import type { EChartsOption } from "echarts";
import { CornerDownRight } from "lucide-react";
import { useMemo } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { escapeHtml, fmtBases, fmtCompact, fmtInt, fmtNum, formatLabel, fmtPct } from "@/lib/format";
import { type FileOverviewRow, type FileState, sequencingOverview } from "@/lib/overview";
import { signalHours } from "@/lib/pod5";
import type { AnalysisJobDetail, RawFile } from "@/lib/types";
import { cn } from "@/lib/utils";

const TH = "whitespace-nowrap px-2 py-1.5 font-medium text-muted-foreground";
const NUM = "whitespace-nowrap px-2 py-1.5 text-right tabular-nums";

const READS_HINT: Record<FileState, TranslationKey> = {
  done: "overview.state.not_run",
  running: "overview.state.running",
  failed: "overview.state.failed",
  not_run: "overview.state.not_run",
  not_applicable: "overview.state.other",
};
const SIGNAL_HINT: Record<FileState, TranslationKey> = {
  done: "overview.state.signalNotRun",
  running: "overview.state.signalRunning",
  failed: "overview.state.signalFailed",
  not_run: "overview.state.signalNotRun",
  not_applicable: "overview.state.other",
};

/** Top of the sample QC tab: one row per file (imported and derived) and the bases of each. */
export function SequencingOverview({ files, jobs, prefix }: { files: RawFile[]; jobs: AnalysisJobDetail[]; prefix: string }) {
  const t = useT();
  const rows = useMemo(() => sequencingOverview(files, jobs), [files, jobs]);
  if (!rows.length) return null;
  const hasSignal = rows.some((r) => r.kind === "signal");
  const versions = [...new Set(rows.map((r) => r.statsVersion).filter((v): v is string => !!v))];
  const statColumns = 7;
  return (
    <>
      <Card className="min-w-0">
        <CardHeader title={t("overview.title")} description={t("overview.subtitle")} action={<Explain id="qc_overview" compact />} />
        <CardBody className="space-y-3 pt-3">
          <div className="relative max-h-[420px] overflow-auto rounded-lg border">
            <table className="w-full min-w-[760px] text-xs">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr className="border-b">
                  <th scope="col" className={cn(TH, "text-left")}>{t("overview.colFile")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colReads")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colBases")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colMeanLength")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colN50")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colQuality")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colQ30")}</th>
                  <th scope="col" className={cn(TH, "text-right")}>{t("overview.colGc")}</th>
                  {hasSignal && <th scope="col" className={cn(TH, "text-right")}>{t("overview.colSignal")}</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.file.id} className="border-b border-border/50 last:border-0">
                    <FileCell row={r} />
                    <Values row={r} span={statColumns} />
                    {hasSignal && <td className={NUM}>{r.signal ? signalDuration(r, t) : "—"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            {t("overview.source", { tool: "arva-core.seqstats", versions: versions.join(", ") || "—" })}
          </p>
          {hasSignal && <p className="text-xs text-muted-foreground">{t("overview.sourceSignal")}</p>}
        </CardBody>
      </Card>
      <BasesPerFileChart rows={rows} prefix={prefix} />
    </>
  );
}

function signalDuration(row: FileOverviewRow, t: ReturnType<typeof useT>) {
  const hours = signalHours(row.signal?.durationS);
  return hours == null ? t("pod5.notReported") : t("pod5.hours", { hours: fmtNum(hours, 2) });
}

function lineage(row: FileOverviewRow, t: ReturnType<typeof useT>) {
  if (row.file.origin === "imported") return t("overview.imported");
  const parent = row.parent?.original_filename ?? "?";
  const made = row.producer ? t("overview.derivedFrom", { parent, tool: row.producer }) : t("overview.derivedFromParent", { parent });
  return row.shareOfParent == null ? made : `${made} · ${t("overview.share", { percent: fmtNum(row.shareOfParent), parent })}`;
}

function FileCell({ row }: { row: FileOverviewRow }) {
  const t = useT();
  const f = row.file;
  return (
    <th scope="row" className="px-2 py-1.5 text-left align-top font-normal">
      <div className="flex items-start gap-1.5" style={{ paddingLeft: Math.min(row.depth, 4) * 16 }}>
        {row.depth > 0 && <CornerDownRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="break-all font-medium">{f.original_filename}</span>
            {f.file_format === "pod5" ? <Badge tone="blue">{t("pod5.badge")}</Badge> : <Badge tone={f.file_format === "unknown" ? "danger" : "teal"}>{formatLabel(f.file_format)}</Badge>}
            {f.read_mate && <Badge tone="blue">{f.read_mate}</Badge>}
          </div>
          <div className="text-[11px] text-muted-foreground">{lineage(row, t)}</div>
        </div>
      </div>
    </th>
  );
}

function Values({ row, span }: { row: FileOverviewRow; span: number }) {
  const t = useT();
  if (row.kind === "signal" && row.signal) {
    return (
      <>
        <td className={cn(NUM, "align-top")}>{fmtInt(row.signal.reads)}</td>
        <td colSpan={span - 1} className="px-2 py-1.5 align-top text-muted-foreground">
          {t("overview.signalNoBases")}
        </td>
      </>
    );
  }
  const s = row.stats;
  if (!s) {
    const hint = (row.kind === "signal" ? SIGNAL_HINT : READS_HINT)[row.kind === "other" ? "not_applicable" : row.state];
    return (
      <td colSpan={span} className="px-2 py-1.5 align-top text-muted-foreground">
        — {t(hint)}
      </td>
    );
  }
  const q = s.quality;
  return (
    <>
      <td className={cn(NUM, "align-top")}>{fmtInt(s.read_count)}</td>
      <td className={cn(NUM, "align-top")} title={`${fmtInt(s.total_bases)} bp`}>
        {fmtBases(s.total_bases)}
      </td>
      <td className={cn(NUM, "align-top")}>{fmtInt(s.mean_length)} bp</td>
      <td className={cn(NUM, "align-top")}>{fmtInt(s.n50)} bp</td>
      <td className={cn(NUM, "align-top")}>{q ? `Q${fmtNum(q.mean_read_quality)}` : "—"}</td>
      <td className={cn(NUM, "align-top")}>{q ? fmtPct(q.q30_bases_percent) : "—"}</td>
      <td className={cn(NUM, "align-top")}>{fmtPct(s.gc_percent, 2)}</td>
    </>
  );
}

function BasesPerFileChart({ rows, prefix }: { rows: FileOverviewRow[]; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const drawn = rows.filter((r) => r.kind === "reads" && r.stats);
  const missing = rows.filter((r) => r.kind === "reads" && !r.stats).length;
  if (!drawn.length) return null;
  const importedName = t("overview.legendImported");
  const derivedName = t("overview.legendDerived");
  // The arrow and indentation repeat the lineage of the table: a derived bar sits right under its parent.
  const labels = drawn.map((r) => `${"  ".repeat(Math.max(0, r.depth - 1))}${r.depth > 0 ? "↳ " : ""}${r.file.original_filename}`);
  const bases = (derived: boolean) => drawn.map((r) => ((r.file.origin === "derived") === derived ? r.stats!.total_bases : null));
  const bar = { type: "bar" as const, stack: "files", barMaxWidth: 24, emphasis: { itemStyle: { opacity: 0.85 } } };
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 8, right: 24, top: 32, bottom: 40, containLabel: true },
    legend: { top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: th.text, fontSize: 11 } },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const r = drawn[(p as { dataIndex: number }).dataIndex];
        const s = r.stats!;
        return [
          `<b>${escapeHtml(r.file.original_filename)}</b>`,
          escapeHtml(lineage(r, t)),
          `${t("overview.colBases")}: <b>${fmtBases(s.total_bases)}</b> (${fmtInt(s.total_bases)} bp)`,
          `${t("overview.colReads")}: <b>${fmtInt(s.read_count)}</b>`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "value",
      ...axisStyle(th, `${t("overview.colBases")} (bp)`, { nameGap: 28 }),
      axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: labels,
      ...axisStyle(th, "", { splitLine: { show: false } }),
      axisLabel: { color: th.muted, fontSize: 10, width: window.innerWidth >= 768 ? 240 : 110, overflow: "truncate" },
    },
    series: [
      { ...bar, name: importedName, data: bases(false), itemStyle: { color: th.primary, borderRadius: [0, 4, 4, 0] } },
      { ...bar, name: derivedName, data: bases(true), itemStyle: { color: th.secondary, borderRadius: [0, 4, 4, 0] } },
    ],
  };
  return (
    <ChartCard
      title={t("overview.chartTitle")}
      subtitle={missing ? `${t("overview.chartSubtitle")}. ${t("overview.chartMissing", { count: missing })}` : t("overview.chartSubtitle")}
      explain="qc_overview"
      option={option}
      filePrefix={prefix}
      height={Math.max(150, 80 + drawn.length * 34)}
      table={{
        columns: [t("overview.colFile"), t("overview.colOrigin"), t("overview.colReads"), `${t("overview.colBases")} (bp)`],
        rows: drawn.map((r) => [r.file.original_filename, lineage(r, t), r.stats!.read_count, r.stats!.total_bases]),
      }}
    />
  );
}
