import type { EChartsOption } from "echarts";
import { useT } from "@/i18n";
import { bpUnit, fmtBases, fmtCompact, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import type { SequenceStats } from "@/lib/types";
import { ChartCard } from "./ChartCard";
import { axisStyle, baseOption, useChartTheme, type ChartTheme } from "./theme";

/** Overlays of two distributions measured by identical methods on shared axes. */

function legend(th: ChartTheme) {
  return { top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: th.text, fontSize: 11 } };
}

function series(th: ChartTheme) {
  return { before: th.primary, after: th.secondary };
}

export function CompareYieldChart({ before, after, prefix }: { before: SequenceStats; after: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const c = series(th);
  const minLen = Math.min(before.min_length, after.min_length);
  const maxLen = Math.max(before.max_length, after.max_length);
  // Every read is at least as long as the shared minimum, so each curve is exactly its
  // total below its own shortest read (this also gives fixed-length data a visible line).
  const pts = (s: SequenceStats) => {
    const p = [...s.cumulative_yield].reverse().map((d) => [d.min_length, d.bases]);
    return s.min_length > minLen ? [[minLen, s.total_bases], ...p] : p;
  };
  const logX = minLen > 0 && maxLen / minLen >= 10;
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      valueFormatter: (v) => fmtBases(Number(v)),
    },
    xAxis: {
      type: logX ? "log" : "value",
      ...axisStyle(th, t("qcChart.minLength", { unit: bpUnit() }) + (logX ? ` · ${t("assembly.chart.logScale")}` : ""), { nameGap: 28 }),
      axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) },
      min: logX ? undefined : "dataMin",
    },
    yAxis: { type: "value", ...axisStyle(th, t("qcChart.basesRetained", { unit: bpUnit() }), { nameGap: 44 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      { name: t("beforeAfter.before"), type: "line", step: "start", showSymbol: false, data: pts(before), lineStyle: { width: 2, color: c.before }, itemStyle: { color: c.before } },
      { name: t("beforeAfter.after"), type: "line", step: "start", showSymbol: false, data: pts(after), lineStyle: { width: 2, color: c.after }, itemStyle: { color: c.after } },
    ],
  };
  return (
    <ChartCard
      title={t("qcChart.yieldTitle")}
      subtitle={t("compareChart.yieldSub")}
      explain="before_after"
      option={option}
      filePrefix={prefix}
      table={{
        columns: [t("qcChart.minLengthCol", { unit: bpUnit() }), t("compareChart.basesBefore"), t("compareChart.basesAfter")],
        rows: before.length_thresholds.map((r) => [
          r.min_length,
          r.bases,
          after.length_thresholds.find((a) => a.min_length === r.min_length)?.bases ?? 0,
        ]),
      }}
    />
  );
}

export function CompareQualityChart({ before, after, prefix }: { before: SequenceStats; after: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const c = series(th);
  const qb = before.quality!.read_quality_histogram;
  const qa = after.quality!.read_quality_histogram;
  const lo = Math.min(qb[0]?.quality ?? 0, qa[0]?.quality ?? 0);
  const hi = Math.max(qb.at(-1)?.quality ?? 0, qa.at(-1)?.quality ?? 0);
  const bins = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
  const val = (h: typeof qb) => {
    const m = new Map(h.map((d) => [d.quality, d.reads]));
    return bins.map((q) => m.get(q) ?? 0);
  };
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(th),
    tooltip: { ...baseOption(th).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } }, valueFormatter: (v) => fmtInt(Number(v)) },
    xAxis: { type: "category", data: bins.map((q) => `Q${q}`), ...axisStyle(th, t("qcChart.meanReadQ"), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", ...axisStyle(th, t("stats.reads"), { nameGap: 44 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      { name: t("beforeAfter.before"), type: "bar", data: val(qb), itemStyle: { color: c.before, borderRadius: [4, 4, 0, 0] }, barGap: "8%", barCategoryGap: "20%" },
      { name: t("beforeAfter.after"), type: "bar", data: val(qa), itemStyle: { color: c.after, borderRadius: [4, 4, 0, 0] } },
    ],
  };
  return (
    <ChartCard
      title={t("qcChart.qualityTitle")}
      subtitle={t("compareChart.qualitySub", { before: fmtNum(before.quality!.mean_read_quality), after: fmtNum(after.quality!.mean_read_quality) })}
      explain="read_quality"
      option={option}
      filePrefix={prefix}
      table={{ columns: [t("qcChart.qualityBin"), t("compareChart.readsBefore"), t("compareChart.readsAfter")], rows: bins.map((q, i) => [`Q${q}`, val(qb)[i], val(qa)[i]]) }}
    />
  );
}

export function CompareGcChart({ before, after, prefix }: { before: SequenceStats; after: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const c = series(th);
  const arr = (s: SequenceStats) => {
    const m = new Map(s.gc_histogram.map((b) => [b.gc_percent, b.reads]));
    return Array.from({ length: 101 }, (_, i) => m.get(i) ?? 0);
  };
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(th),
    tooltip: { ...baseOption(th).tooltip, trigger: "axis", valueFormatter: (v) => fmtInt(Number(v)) },
    xAxis: { type: "category", data: Array.from({ length: 101 }, (_, i) => fmtPct(i, 0)), boundaryGap: false, ...axisStyle(th, t("qcChart.gcPerRead"), { nameGap: 28, splitLine: { show: false } }), axisLabel: { color: th.muted, fontSize: 10, interval: 9 } },
    yAxis: { type: "value", ...axisStyle(th, t("stats.reads"), { nameGap: 44 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      { name: t("beforeAfter.before"), type: "line", data: arr(before), showSymbol: false, lineStyle: { width: 2, color: c.before }, itemStyle: { color: c.before } },
      { name: t("beforeAfter.after"), type: "line", data: arr(after), showSymbol: false, lineStyle: { width: 2, color: c.after }, itemStyle: { color: c.after } },
    ],
  };
  return (
    <ChartCard
      title={t("stats.gc")}
      subtitle={t("qcChart.overall", { value: `${fmtPct(before.gc_percent, 2)} → ${fmtPct(after.gc_percent, 2)}` })}
      explain="gc_content"
      option={option}
      filePrefix={prefix}
    />
  );
}
