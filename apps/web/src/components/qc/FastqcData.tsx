import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { AlertTriangle, Check, Copy, Loader2 } from "lucide-react";
import { useState } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { escapeHtml, fmtDate, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { ADAPTER_FAIL_PERCENT, ADAPTER_WARN_PERCENT, binCentre, copiesText, curvePeak, isLongReadData, positionText } from "@/lib/qcData";
import type { AnalysisJobDetail, FastqcData, SequencingTechnology } from "@/lib/types";

const STATUS_TONE = { PASS: "success", WARN: "warning", FAIL: "danger" } as const;

function tooltipRow(label: string, value: string) {
  return `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${escapeHtml(label)}</span><b>${value}</b></div>`;
}

function Heuristic({ status }: { status: string }) {
  const t = useT();
  return <Badge tone={STATUS_TONE[status as keyof typeof STATUS_TONE] ?? "neutral"}>{t("qcdata.heuristics", { status })}</Badge>;
}

/** QC tab: adapter content, duplication levels and overrepresented sequences from a completed FastQC run. */
export function FastqcDataSection({ job, technology, prefix }: { job: AnalysisJobDetail; technology: SequencingTechnology; prefix: string }) {
  const t = useT();
  const query = useQuery({ queryKey: ["fastqc-data", job.id], queryFn: () => api.fastqcData(job.id), staleTime: Infinity });
  const data = query.data;
  const longReads = isLongReadData(data?.max_read_length, technology);
  return (
    <section className="min-w-0 space-y-4">
      <div>
        <h2 className="text-sm font-semibold">{t("qcdata.fastqc.title")}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {t("qcdata.fastqc.subtitle", { version: data?.fastqc_version ?? job.tool_version, date: fmtDate(job.finished_at) })}
          {data && data.source.endsWith(".zip") && <> {t("qcdata.fastqc.fromZip")}</>}
        </p>
      </div>
      {query.isLoading && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> {t("qcdata.loading")}
        </p>
      )}
      {query.error && <ErrorNote error={t("qcdata.error", { error: query.error instanceof Error ? query.error.message : String(query.error) })} />}
      {data && (
        <>
          {data.unrecognised.length > 0 && (
            <p className="text-xs text-muted-foreground">{t("qcdata.fastqc.unrecognised", { modules: data.unrecognised.join(", ") })}</p>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <AdapterContentChart data={data} prefix={prefix} />
            <DuplicationChart data={data} longReads={longReads} prefix={prefix} />
          </div>
          <OverrepresentedCard data={data} longReads={longReads} />
        </>
      )}
    </section>
  );
}

function Absent({ title }: { title: string }) {
  const t = useT();
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody className="pt-2 text-sm text-muted-foreground">{t("qcdata.fastqc.absent")}</CardBody>
    </Card>
  );
}

function AdapterContentChart({ data, prefix }: { data: FastqcData; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const ac = data.adapter_content;
  if (!ac) return <Absent title={t("qcdata.adapter.title")} />;
  // Colours follow the adapter's place in FastQC's list; a longer custom list is shown in the table only.
  const plotted = ac.adapters.slice(0, th.series.length);
  const peaks = ac.adapters
    .map((a) => ({ name: a.name, peak: curvePeak(a.percent) }))
    .filter((a): a is { name: string; peak: NonNullable<ReturnType<typeof curvePeak>> } => a.peak !== null)
    .sort((a, b) => b.peak.value - a.peak.value);
  const top = peaks[0];
  const guide = (value: number, label: string) => ({ yAxis: value, label: { formatter: label } });
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 52, right: 16, top: 40, bottom: 44 },
    legend: { type: "scroll", top: 0, left: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: th.text, fontSize: 11 } },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const items = p as { dataIndex: number; seriesName: string; value: [number, number] }[];
        const pos = ac.positions[items[0].dataIndex];
        return `<b>${escapeHtml(t("qcdata.adapter.position", { position: positionText(pos) }))}</b>${items
          .map((i) => tooltipRow(i.seriesName, fmtPct(i.value[1], 2)))
          .join("")}`;
      },
    },
    xAxis: {
      type: "value",
      min: 1,
      max: ac.positions.at(-1)?.end,
      ...axisStyle(th, t("qcdata.adapter.x"), { nameGap: 28, splitLine: { show: false } }),
    },
    yAxis: {
      type: "value",
      min: 0,
      max: (v: { max: number }) => (v.max < ADAPTER_FAIL_PERCENT + 2 ? ADAPTER_FAIL_PERCENT + 2 : Math.min(100, Math.ceil(v.max / 10) * 10)),
      ...axisStyle(th, t("qcdata.adapter.y"), { nameGap: 36 }),
    },
    series: plotted.map((a, i) => ({
      name: a.name,
      type: "line" as const,
      showSymbol: false,
      data: a.percent.map((v, j) => [binCentre(ac.positions[j]), v]),
      lineStyle: { width: 2, color: th.series[i] },
      itemStyle: { color: th.series[i] },
      ...(i === 0 && {
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: th.text, type: "dashed" as const, width: 1, opacity: 0.6 },
          label: { color: th.text, fontSize: 10, position: "insideStartTop" as const },
          data: [guide(ADAPTER_WARN_PERCENT, t("qcdata.adapter.warn")), guide(ADAPTER_FAIL_PERCENT, t("qcdata.adapter.fail"))],
        },
      }),
    })),
  };
  return (
    <ChartCard
      title={t("qcdata.adapter.title")}
      subtitle={
        <span className="flex flex-wrap items-center gap-1.5">
          <span>{t("qcdata.adapter.subtitle")}</span>
          <Heuristic status={ac.status} />
        </span>
      }
      explain="adapter_content"
      option={option}
      filePrefix={prefix}
      height={300}
      table={{
        columns: [t("qcdata.adapter.colPosition"), ...ac.adapters.map((a) => `${a.name} (%)`)],
        rows: ac.positions.map((p, j) => [positionText(p), ...ac.adapters.map((a) => a.percent[j])]),
      }}
      footer={
        <>
          <p className="font-medium text-foreground">
            {top
              ? t("qcdata.adapter.highest", { adapter: top.name, percent: fmtNum(top.peak.value, 2), position: positionText(ac.positions[top.peak.index]) })
              : t("qcdata.adapter.none")}
          </p>
          <p>{t("qcdata.adapter.binned")}</p>
          {ac.adapters.length > plotted.length && <p>{t("qcdata.adapter.notCharted", { count: ac.adapters.length - plotted.length })}</p>}
        </>
      }
    />
  );
}

function DuplicationChart({ data, longReads, prefix }: { data: FastqcData; longReads: boolean; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const dup = data.duplication;
  if (!dup) return <Absent title={t("qcdata.dup.title")} />;
  const color = longReads ? th.muted : th.primary;
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 52, right: 16, top: 16, bottom: 72 },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const b = dup.bins[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${escapeHtml(t("qcdata.dup.colLevel"))} ${escapeHtml(b.level)}</b>${tooltipRow(t("qcdata.dup.copies"), copiesText(b.level))}${tooltipRow(t("qcdata.dup.percent"), fmtPct(b.percent_of_total, 2))}`;
      },
    },
    xAxis: {
      type: "category",
      data: dup.bins.map((b) => copiesText(b.level)),
      ...axisStyle(th, t("qcdata.dup.x"), { nameGap: 56, splitLine: { show: false } }),
      axisLabel: { color: th.muted, fontSize: 10, rotate: 45, interval: 0, hideOverlap: true },
    },
    yAxis: { type: "value", min: 0, max: 100, ...axisStyle(th, t("qcdata.dup.y"), { nameGap: 36 }) },
    series: [
      {
        type: "bar",
        data: dup.bins.map((b) => b.percent_of_total),
        itemStyle: { color, borderRadius: [4, 4, 0, 0], opacity: longReads ? 0.6 : 1 },
        barCategoryGap: "20%",
      },
    ],
  };
  return (
    <ChartCard
      title={t("qcdata.dup.title")}
      subtitle={
        <span className="flex flex-wrap items-center gap-1.5">
          <span>
            {t("qcdata.dup.subtitle", { remaining: fmtNum(dup.total_deduplicated_percent, 2), duplicates: fmtNum(dup.duplicate_percent, 2) })}
          </span>
          <Heuristic status={dup.status} />
        </span>
      }
      explain="duplication_levels"
      option={option}
      filePrefix={prefix}
      height={300}
      table={{
        columns: [t("qcdata.dup.colLevel"), t("qcdata.dup.colCopies"), t("qcdata.dup.colPercent")],
        rows: dup.bins.map((b) => [b.level, copiesText(b.level), b.percent_of_total]),
      }}
      footer={
        <>
          {longReads && (
            <p className="flex gap-1.5 font-medium text-amber-700 dark:text-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {t("qcdata.dup.longReads")}
            </p>
          )}
          <p>{t("qcdata.dup.caveat")}</p>
        </>
      }
    />
  );
}

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex shrink-0 items-center rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
      aria-label={copied ? t("qcdata.over.copied") : t("qcdata.over.copy")}
      title={copied ? t("qcdata.over.copied") : t("qcdata.over.copy")}
      onClick={() => {
        navigator.clipboard?.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
    </button>
  );
}

function OverrepresentedCard({ data, longReads }: { data: FastqcData; longReads: boolean }) {
  const t = useT();
  const over = data.overrepresented_sequences;
  if (!over) return <Absent title={t("qcdata.over.title")} />;
  return (
    <Card className="min-w-0">
      <CardHeader
        title={t("qcdata.over.title")}
        description={
          <span className="flex flex-wrap items-center gap-1.5">
            <span>{t("qcdata.over.subtitle")}</span>
            <Heuristic status={over.status} />
          </span>
        }
        action={<Explain id="overrepresented_sequences" />}
      />
      <CardBody className="space-y-3 pt-3 text-xs">
        {(over.every_read_listed || longReads) && (
          <div className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-2.5">
            {over.every_read_listed && (
              <p className="flex gap-1.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {t("qcdata.over.everyRead")}
              </p>
            )}
            {longReads && (
              <p className="flex gap-1.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {t("qcdata.over.longReads")}
              </p>
            )}
          </div>
        )}
        {over.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("qcdata.over.none")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">{t("qcdata.over.colSequence")}</th>
                  <th className="py-1.5 pr-3 text-right font-medium">{t("qcdata.over.colCount")}</th>
                  <th className="py-1.5 pr-3 text-right font-medium">{t("qcdata.over.colPercent")}</th>
                  <th className="py-1.5 font-medium">{t("qcdata.over.colSource")}</th>
                </tr>
              </thead>
              <tbody>
                {over.rows.map((r, i) => (
                  <tr key={`${i}-${r.sequence}`} className="border-b border-border/50 align-top">
                    <td className="py-1.5 pr-3">
                      <span className="flex items-start gap-1">
                        <code className="break-all font-mono text-[11px]">{r.sequence}</code>
                        <CopyButton text={r.sequence} />
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtInt(r.count)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmtNum(r.percent, 2)}</td>
                    <td className="py-1.5">{r.possible_source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {over.total > over.rows.length && <p className="text-muted-foreground">{t("qcdata.over.shown", { shown: over.rows.length, total: fmtInt(over.total) })}</p>}
        <p className="text-muted-foreground">{t("qcdata.over.caveat")}</p>
      </CardBody>
    </Card>
  );
}
