import type { EChartsOption } from "echarts";
import { fmtBases, fmtCompact, fmtInt, fmtNum } from "@/lib/format";
import type { SequenceStats } from "@/lib/types";
import { ChartCard } from "./ChartCard";
import { axisStyle, baseOption, useChartTheme, type ChartTheme } from "./theme";

/** Overlays of two distributions measured by identical methods on shared axes. */

function legend(t: ChartTheme) {
  return { top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.text, fontSize: 11 } };
}

function series(t: ChartTheme) {
  return { before: t.primary, after: t.secondary };
}

export function CompareYieldChart({ before, after, prefix }: { before: SequenceStats; after: SequenceStats; prefix: string }) {
  const t = useChartTheme();
  const c = series(t);
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
    ...baseOption(t),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "axis",
      valueFormatter: (v) => fmtBases(Number(v)),
    },
    xAxis: {
      type: logX ? "log" : "value",
      ...axisStyle(t, "Minimum read length (bp)" + (logX ? " · log scale" : ""), { nameGap: 28 }),
      axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) },
      min: logX ? undefined : "dataMin",
    },
    yAxis: { type: "value", ...axisStyle(t, "Bases retained (bp)", { nameGap: 44 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      { name: "Before", type: "line", step: "start", showSymbol: false, data: pts(before), lineStyle: { width: 2, color: c.before }, itemStyle: { color: c.before } },
      { name: "After", type: "line", step: "start", showSymbol: false, data: pts(after), lineStyle: { width: 2, color: c.after }, itemStyle: { color: c.after } },
    ],
  };
  return (
    <ChartCard
      title="Yield by minimum read length"
      subtitle="Bases in reads of at least each length, before and after filtering"
      explain="before_after"
      option={option}
      filePrefix={prefix}
      table={{
        columns: ["Min length (bp)", "Bases before", "Bases after"],
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
  const t = useChartTheme();
  const c = series(t);
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
    ...baseOption(t),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(t),
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.6 } }, valueFormatter: (v) => fmtInt(Number(v)) },
    xAxis: { type: "category", data: bins.map((q) => `Q${q}`), ...axisStyle(t, "Mean read quality (Phred)", { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", ...axisStyle(t, "Reads", { nameGap: 44 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      { name: "Before", type: "bar", data: val(qb), itemStyle: { color: c.before, borderRadius: [4, 4, 0, 0] }, barGap: "8%", barCategoryGap: "20%" },
      { name: "After", type: "bar", data: val(qa), itemStyle: { color: c.after, borderRadius: [4, 4, 0, 0] } },
    ],
  };
  return (
    <ChartCard
      title="Per-read mean quality"
      subtitle={`Mean Q${fmtNum(before.quality!.mean_read_quality)} → Q${fmtNum(after.quality!.mean_read_quality)}`}
      explain="read_quality"
      option={option}
      filePrefix={prefix}
      table={{ columns: ["Quality bin", "Reads before", "Reads after"], rows: bins.map((q, i) => [`Q${q}`, val(qb)[i], val(qa)[i]]) }}
    />
  );
}

export function CompareGcChart({ before, after, prefix }: { before: SequenceStats; after: SequenceStats; prefix: string }) {
  const t = useChartTheme();
  const c = series(t);
  const arr = (s: SequenceStats) => {
    const m = new Map(s.gc_histogram.map((b) => [b.gc_percent, b.reads]));
    return Array.from({ length: 101 }, (_, i) => m.get(i) ?? 0);
  };
  const option: EChartsOption = {
    ...baseOption(t),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(t),
    tooltip: { ...baseOption(t).tooltip, trigger: "axis", valueFormatter: (v) => fmtInt(Number(v)) },
    xAxis: { type: "category", data: Array.from({ length: 101 }, (_, i) => `${i}%`), boundaryGap: false, ...axisStyle(t, "Per-read GC content", { nameGap: 28, splitLine: { show: false } }), axisLabel: { color: t.muted, fontSize: 10, interval: 9 } },
    yAxis: { type: "value", ...axisStyle(t, "Reads", { nameGap: 44 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      { name: "Before", type: "line", data: arr(before), showSymbol: false, lineStyle: { width: 2, color: c.before }, itemStyle: { color: c.before } },
      { name: "After", type: "line", data: arr(after), showSymbol: false, lineStyle: { width: 2, color: c.after }, itemStyle: { color: c.after } },
    ],
  };
  return (
    <ChartCard
      title="GC content"
      subtitle={`Overall ${fmtNum(before.gc_percent, 2)}% → ${fmtNum(after.gc_percent, 2)}%`}
      explain="gc_content"
      option={option}
      filePrefix={prefix}
    />
  );
}
