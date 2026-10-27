import type { EChartsOption } from "echarts";
import { useMemo, useState } from "react";
import { fmtBases, fmtCompact, fmtInt, fmtNum } from "@/lib/format";
import type { QualitySection, SequenceStats } from "@/lib/types";
import { ChartCard, Segmented } from "./ChartCard";
import { axisStyle, baseOption, useChartTheme } from "./theme";

const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

function tooltipRow(label: string, value: string) {
  return `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${label}</span><b>${value}</b></div>`;
}

export function LengthHistogramChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useChartTheme();
  const hasLog = !!stats.length_histogram_log;
  const [scale, setScale] = useState<"linear" | "log10">(hasLog ? "log10" : "linear");
  const [weight, setWeight] = useState<"reads" | "bases">("reads");
  const hist = scale === "log10" && stats.length_histogram_log ? stats.length_histogram_log : stats.length_histogram;

  const bins = useMemo(
    () =>
      hist.reads.map((_, i) => {
        const lo = hist.bin_edges[i];
        const hi = hist.bin_edges[i + 1];
        const loR = Math.ceil(lo);
        const hiR = hist.scale === "linear" ? hi - 1 : Math.floor(hi);
        return { label: fmtCompact(loR), range: `${fmtInt(loR)}–${fmtInt(Math.max(loR, hiR))} bp`, reads: hist.reads[i], bases: hist.bases[i] };
      }),
    [hist],
  );

  const option: EChartsOption = {
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const b = bins[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${b.range}</b>${tooltipRow("Reads", fmtInt(b.reads))}${tooltipRow("Bases", fmtBases(b.bases))}`;
      },
    },
    xAxis: { type: "category", data: bins.map((b) => b.label), ...axisStyle(t, "Read length (bp)" + (hist.scale === "log10" ? " · log-spaced bins" : ""), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: {
      type: "value",
      ...axisStyle(t, weight === "reads" ? "Reads" : "Bases", { nameGap: 44 }),
      axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) },
    },
    series: [
      {
        type: "bar",
        data: bins.map((b) => (weight === "reads" ? b.reads : b.bases)),
        itemStyle: { color: t.primary, borderRadius: BAR_RADIUS },
        barCategoryGap: "12%",
        emphasis: { itemStyle: { opacity: 0.85 } },
      },
    ],
  };

  return (
    <ChartCard
      title="Read length distribution"
      subtitle={`${fmtInt(stats.read_count)} reads · ${fmtInt(stats.min_length)}–${fmtInt(stats.max_length)} bp`}
      explain="length_distribution"
      option={option}
      filePrefix={prefix}
      controls={
        <>
          <Segmented label="Weighting" value={weight} onChange={setWeight} options={[{ value: "reads", label: "Reads" }, { value: "bases", label: "Bases" }]} />
          {hasLog && (
            <Segmented label="Bin scale" value={scale} onChange={setScale} options={[{ value: "log10", label: "Log bins" }, { value: "linear", label: "Linear bins" }]} />
          )}
        </>
      }
      table={{ columns: ["Length range", "Reads", "Bases"], rows: bins.map((b) => [b.range, b.reads, b.bases]) }}
    />
  );
}

export function ReadQualityChart({ quality, prefix }: { quality: QualitySection; prefix: string }) {
  const t = useChartTheme();
  // Dense integer bins so empty quality ranges keep their true width on the axis.
  const counts = new Map(quality.read_quality_histogram.map((d) => [d.quality, d.reads]));
  const qs = quality.read_quality_histogram.map((d) => d.quality);
  const lo = qs.length ? Math.min(...qs) : 0;
  const hi = qs.length ? Math.max(...qs) : 0;
  const data = Array.from({ length: hi - lo + 1 }, (_, i) => ({ quality: lo + i, reads: counts.get(lo + i) ?? 0 }));
  const option: EChartsOption = {
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const d = data[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>Q${d.quality}–${d.quality + 1}</b>${tooltipRow("Reads", fmtInt(d.reads))}`;
      },
    },
    xAxis: { type: "category", data: data.map((d) => `Q${d.quality}`), ...axisStyle(t, "Mean read quality (Phred)", { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", ...axisStyle(t, "Reads", { nameGap: 44 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [{ type: "bar", data: data.map((d) => d.reads), itemStyle: { color: t.secondary, borderRadius: BAR_RADIUS }, barCategoryGap: "12%" }],
  };
  return (
    <ChartCard
      title="Per-read mean quality"
      subtitle={`Mean Q${fmtNum(quality.mean_read_quality)} · median Q${fmtNum(quality.median_read_quality)} (error-probability averaged)`}
      explain="read_quality"
      option={option}
      filePrefix={prefix}
      table={{ columns: ["Quality bin", "Reads"], rows: quality.read_quality_histogram.map((d) => [`Q${d.quality}–${d.quality + 1}`, d.reads]) }}
    />
  );
}

export function GcChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useChartTheme();
  const byGc = new Map(stats.gc_histogram.map((b) => [b.gc_percent, b.reads]));
  const values = Array.from({ length: 101 }, (_, i) => byGc.get(i) ?? 0);
  const option: EChartsOption = {
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: t.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>${i}% GC</b>${tooltipRow("Reads", fmtInt(values[i]))}`;
      },
    },
    xAxis: { type: "category", data: values.map((_, i) => `${i}%`), ...axisStyle(t, "Per-read GC content", { nameGap: 28, splitLine: { show: false } }), axisLabel: { color: t.muted, fontSize: 10, interval: 9 } },
    yAxis: { type: "value", ...axisStyle(t, "Reads", { nameGap: 44 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      {
        type: "bar",
        data: values,
        itemStyle: { color: t.primary, borderRadius: [2, 2, 0, 0] },
        barCategoryGap: "10%",
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: t.text, type: "dashed", width: 1 },
          label: { color: t.text, fontSize: 10, formatter: `Overall ${fmtNum(stats.gc_percent)}%` },
          data: [{ xAxis: Math.round(stats.gc_percent) }],
        },
      },
    ],
  };
  return (
    <ChartCard
      title="GC content"
      subtitle={`Overall GC ${fmtNum(stats.gc_percent, 2)}% of unambiguous bases`}
      explain="gc_content"
      option={option}
      filePrefix={prefix}
      table={{ columns: ["GC %", "Reads"], rows: stats.gc_histogram.map((b) => [b.gc_percent, b.reads]) }}
    />
  );
}

export function PerPositionQualityChart({ quality, prefix }: { quality: QualitySection; prefix: string }) {
  const t = useChartTheme();
  const pp = quality.per_position;
  const option: EChartsOption = {
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>Position ${pp.positions[i]}</b>${tooltipRow("Mean quality", `Q${fmtNum(pp.mean_quality[i])}`)}${tooltipRow("Reads covering", fmtInt(pp.reads_covering[i]))}`;
      },
    },
    xAxis: { type: "category", data: pp.positions, boundaryGap: false, ...axisStyle(t, "Position in read (bp)", { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", min: 0, ...axisStyle(t, "Mean Phred quality", { nameGap: 36 }) },
    series: [
      {
        type: "line",
        data: pp.mean_quality,
        showSymbol: false,
        lineStyle: { width: 2, color: t.secondary },
        itemStyle: { color: t.secondary },
        areaStyle: { color: t.secondary, opacity: 0.08 },
      },
    ],
  };
  return (
    <ChartCard
      title="Quality by position"
      subtitle={pp.truncated ? `First ${fmtInt(pp.position_limit)} positions · hover for reads covering each position` : "Hover for the number of reads covering each position"}
      explain="per_position_quality"
      option={option}
      filePrefix={prefix}
      table={{ columns: ["Position", "Mean Q", "Reads covering"], rows: pp.positions.map((p, i) => [p, pp.mean_quality[i], pp.reads_covering[i]]) }}
    />
  );
}

export function QualityVsLengthChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useChartTheme();
  const pts = stats.sample_points.points.filter((p) => p[1] !== null && p[0] > 0);
  const logX = stats.max_length / Math.max(stats.min_length, 1) >= 10;
  const option: EChartsOption = {
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const [len, q, gc] = (p as { value: [number, number, number | null] }).value;
        return `${tooltipRow("Length", `${fmtInt(len)} bp`)}${tooltipRow("Mean quality", `Q${fmtNum(q)}`)}${gc !== null ? tooltipRow("GC", `${fmtNum(gc)}%`) : ""}`;
      },
    },
    xAxis: { type: logX ? "log" : "value", ...axisStyle(t, "Read length (bp)" + (logX ? " · log scale" : ""), { nameGap: 28 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) }, min: logX ? undefined : "dataMin" },
    yAxis: { type: "value", ...axisStyle(t, "Mean read quality (Phred)", { nameGap: 36 }), min: (v: { min: number }) => Math.floor(v.min) },
    series: [
      {
        type: "scatter",
        data: pts,
        symbolSize: 6,
        itemStyle: { color: t.primary, opacity: 0.45, borderColor: t.surface, borderWidth: 0.5 },
        emphasis: { itemStyle: { opacity: 1 } },
        large: pts.length > 3000,
      },
    ],
  };
  return (
    <ChartCard
      title="Quality versus length"
      subtitle={`Random sample of ${fmtInt(pts.length)} of ${fmtInt(stats.read_count)} reads (seed ${stats.sample_points.seed})`}
      explain="quality_vs_length"
      option={option}
      filePrefix={prefix}
      height={300}
    />
  );
}

export function CumulativeYieldChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useChartTheme();
  const pts = [...stats.cumulative_yield].reverse();
  const logX = stats.max_length / Math.max(stats.min_length, 1) >= 10 && stats.min_length > 0;
  const option: EChartsOption = {
    ...baseOption(t),
    tooltip: {
      ...baseOption(t).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const d = pts[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>Reads ≥ ${fmtInt(d.min_length)} bp</b>${tooltipRow("Bases kept", `${fmtBases(d.bases)} (${fmtNum((100 * d.bases) / stats.total_bases)}%)`)}${tooltipRow("Reads kept", fmtInt(d.reads))}`;
      },
    },
    xAxis: { type: logX ? "log" : "value", ...axisStyle(t, "Minimum read length (bp)" + (logX ? " · log scale" : ""), { nameGap: 28 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) }, min: logX ? undefined : "dataMin" },
    yAxis: { type: "value", ...axisStyle(t, "Bases retained (bp)", { nameGap: 44 }), axisLabel: { color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      {
        type: "line",
        data: pts.map((d) => [d.min_length, d.bases]),
        showSymbol: pts.length <= 2,
        symbolSize: 8,
        step: "start",
        lineStyle: { width: 2, color: t.primary },
        itemStyle: { color: t.primary },
        areaStyle: { color: t.primary, opacity: 0.08 },
      },
    ],
  };
  return (
    <ChartCard
      title="Yield by minimum read length"
      subtitle="Bases that would remain after a minimum-length filter"
      explain="cumulative_yield"
      option={option}
      filePrefix={prefix}
      table={{
        columns: ["Min length (bp)", "Reads kept", "Bases kept", "% of bases"],
        rows: stats.length_thresholds.map((r) => [r.min_length, r.reads, r.bases, fmtNum(r.bases_percent)]),
      }}
    />
  );
}
