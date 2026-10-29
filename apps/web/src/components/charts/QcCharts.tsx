import type { EChartsOption } from "echarts";
import { useMemo, useState } from "react";
import { useT } from "@/i18n";
import { bpUnit, escapeHtml, fmtBases, fmtBp, fmtCompact, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import type { QualitySection, SequenceStats } from "@/lib/types";
import { ChartCard, Segmented } from "./ChartCard";
import { axisStyle, baseOption, useChartTheme } from "./theme";

const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

function tooltipRow(label: string, value: string) {
  return `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${escapeHtml(label)}</span><b>${value}</b></div>`;
}

export function LengthHistogramChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
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
        return { label: fmtCompact(loR), range: `${fmtInt(loR)}–${fmtInt(Math.max(loR, hiR))} ${bpUnit()}`, reads: hist.reads[i], bases: hist.bases[i] };
      }),
    [hist],
  );

  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const b = bins[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${b.range}</b>${tooltipRow(t("stats.reads"), fmtInt(b.reads))}${tooltipRow(t("qcChart.bases"), fmtBases(b.bases))}`;
      },
    },
    xAxis: { type: "category", data: bins.map((b) => b.label), ...axisStyle(th, t("qcChart.readLength", { unit: bpUnit() }) + (hist.scale === "log10" ? ` · ${t("qcChart.logBinsNote")}` : ""), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: {
      type: "value",
      ...axisStyle(th, weight === "reads" ? t("stats.reads") : t("qcChart.bases"), { nameGap: 44 }),
      axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) },
    },
    series: [
      {
        type: "bar",
        data: bins.map((b) => (weight === "reads" ? b.reads : b.bases)),
        itemStyle: { color: th.primary, borderRadius: BAR_RADIUS },
        barCategoryGap: "12%",
        emphasis: { itemStyle: { opacity: 0.85 } },
      },
    ],
  };

  return (
    <ChartCard
      title={t("qcChart.lengthTitle")}
      subtitle={`${t("stats.readCount", { count: stats.read_count })} · ${fmtInt(stats.min_length)}–${fmtBp(stats.max_length)}`}
      explain="length_distribution"
      option={option}
      filePrefix={prefix}
      controls={
        <>
          <Segmented
            label={t("qcChart.weighting")}
            value={weight}
            onChange={setWeight}
            options={[
              { value: "reads", label: t("stats.reads") },
              { value: "bases", label: t("qcChart.bases") },
            ]}
          />
          {hasLog && (
            <Segmented
              label={t("qcChart.binScale")}
              value={scale}
              onChange={setScale}
              options={[
                { value: "log10", label: t("qcChart.logBins") },
                { value: "linear", label: t("qcChart.linearBins") },
              ]}
            />
          )}
        </>
      }
      table={{ columns: [t("qcChart.lengthRange"), t("stats.reads"), t("qcChart.bases")], rows: bins.map((b) => [b.range, b.reads, b.bases]) }}
    />
  );
}

export function ReadQualityChart({ quality, prefix }: { quality: QualitySection; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  // Dense integer bins so empty quality ranges keep their true width on the axis.
  const counts = new Map(quality.read_quality_histogram.map((d) => [d.quality, d.reads]));
  const qs = quality.read_quality_histogram.map((d) => d.quality);
  const lo = qs.length ? Math.min(...qs) : 0;
  const hi = qs.length ? Math.max(...qs) : 0;
  const data = Array.from({ length: hi - lo + 1 }, (_, i) => ({ quality: lo + i, reads: counts.get(lo + i) ?? 0 }));
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const d = data[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>Q${d.quality}–${d.quality + 1}</b>${tooltipRow(t("stats.reads"), fmtInt(d.reads))}`;
      },
    },
    xAxis: { type: "category", data: data.map((d) => `Q${d.quality}`), ...axisStyle(th, t("qcChart.meanReadQ"), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", ...axisStyle(th, t("stats.reads"), { nameGap: 44 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [{ type: "bar", data: data.map((d) => d.reads), itemStyle: { color: th.secondary, borderRadius: BAR_RADIUS }, barCategoryGap: "12%" }],
  };
  return (
    <ChartCard
      title={t("qcChart.qualityTitle")}
      subtitle={t("qcChart.qualitySub", { mean: fmtNum(quality.mean_read_quality), median: fmtNum(quality.median_read_quality) })}
      explain="read_quality"
      option={option}
      filePrefix={prefix}
      table={{ columns: [t("qcChart.qualityBin"), t("stats.reads")], rows: quality.read_quality_histogram.map((d) => [`Q${d.quality}–${d.quality + 1}`, d.reads]) }}
    />
  );
}

export function GcChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const byGc = new Map(stats.gc_histogram.map((b) => [b.gc_percent, b.reads]));
  const values = Array.from({ length: 101 }, (_, i) => byGc.get(i) ?? 0);
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>${fmtPct(i, 0)} GC</b>${tooltipRow(t("stats.reads"), fmtInt(values[i]))}`;
      },
    },
    xAxis: { type: "category", data: values.map((_, i) => fmtPct(i, 0)), ...axisStyle(th, t("qcChart.gcPerRead"), { nameGap: 28, splitLine: { show: false } }), axisLabel: { color: th.muted, fontSize: 10, interval: 9 } },
    yAxis: { type: "value", ...axisStyle(th, t("stats.reads"), { nameGap: 44 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      {
        type: "bar",
        data: values,
        itemStyle: { color: th.primary, borderRadius: [2, 2, 0, 0] },
        barCategoryGap: "10%",
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: th.text, type: "dashed", width: 1 },
          label: { color: th.text, fontSize: 10, formatter: t("qcChart.overall", { value: fmtPct(stats.gc_percent) }) },
          data: [{ xAxis: Math.round(stats.gc_percent) }],
        },
      },
    ],
  };
  return (
    <ChartCard
      title={t("stats.gc")}
      subtitle={t("qcChart.gcSub", { value: fmtPct(stats.gc_percent, 2) })}
      explain="gc_content"
      option={option}
      filePrefix={prefix}
      table={{ columns: ["GC %", t("stats.reads")], rows: stats.gc_histogram.map((b) => [b.gc_percent, b.reads]) }}
    />
  );
}

export function PerPositionQualityChart({ quality, prefix }: { quality: QualitySection; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const pp = quality.per_position;
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>${escapeHtml(t("qcChart.position", { position: pp.positions[i] }))}</b>${tooltipRow(t("qcChart.meanQuality"), `Q${fmtNum(pp.mean_quality[i])}`)}${tooltipRow(t("qcChart.readsCovering"), fmtInt(pp.reads_covering[i]))}`;
      },
    },
    xAxis: { type: "category", data: pp.positions, boundaryGap: false, ...axisStyle(th, t("qcChart.positionAxis", { unit: bpUnit() }), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", min: 0, ...axisStyle(th, t("qcChart.meanPhred"), { nameGap: 36 }) },
    series: [
      {
        type: "line",
        data: pp.mean_quality,
        showSymbol: false,
        lineStyle: { width: 2, color: th.secondary },
        itemStyle: { color: th.secondary },
        areaStyle: { color: th.secondary, opacity: 0.08 },
      },
    ],
  };
  return (
    <ChartCard
      title={t("qcChart.positionTitle")}
      subtitle={pp.truncated ? t("qcChart.positionTruncated", { count: fmtInt(pp.position_limit) }) : t("qcChart.positionSub")}
      explain="per_position_quality"
      option={option}
      filePrefix={prefix}
      table={{ columns: [t("qcChart.positionCol"), t("qcChart.meanQ"), t("qcChart.readsCovering")], rows: pp.positions.map((p, i) => [p, pp.mean_quality[i], pp.reads_covering[i]]) }}
    />
  );
}

export function QualityVsLengthChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const pts = stats.sample_points.points.filter((p) => p[1] !== null && p[0] > 0);
  const logX = stats.max_length / Math.max(stats.min_length, 1) >= 10;
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const [len, q, gc] = (p as { value: [number, number, number | null] }).value;
        return `${tooltipRow(t("qcChart.length"), fmtBp(len))}${tooltipRow(t("qcChart.meanQuality"), `Q${fmtNum(q)}`)}${gc !== null ? tooltipRow("GC", fmtPct(gc)) : ""}`;
      },
    },
    xAxis: { type: logX ? "log" : "value", ...axisStyle(th, t("qcChart.readLength", { unit: bpUnit() }) + (logX ? ` · ${t("assembly.chart.logScale")}` : ""), { nameGap: 28 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) }, min: logX ? undefined : "dataMin" },
    yAxis: { type: "value", ...axisStyle(th, t("qcChart.meanReadQ"), { nameGap: 36 }), min: (v: { min: number }) => Math.floor(v.min) },
    series: [
      {
        type: "scatter",
        data: pts,
        symbolSize: 6,
        itemStyle: { color: th.primary, opacity: 0.45, borderColor: th.surface, borderWidth: 0.5 },
        emphasis: { itemStyle: { opacity: 1 } },
        large: pts.length > 3000,
      },
    ],
  };
  return (
    <ChartCard
      title={t("qcChart.qvlTitle")}
      subtitle={t("qcChart.qvlSub", { count: fmtInt(pts.length), total: stats.read_count, seed: stats.sample_points.seed })}
      explain="quality_vs_length"
      option={option}
      filePrefix={prefix}
      height={300}
    />
  );
}

export function CumulativeYieldChart({ stats, prefix }: { stats: SequenceStats; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const pts = [...stats.cumulative_yield].reverse();
  const logX = stats.max_length / Math.max(stats.min_length, 1) >= 10 && stats.min_length > 0;
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const d = pts[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${escapeHtml(t("qcChart.readsAtLeast", { length: fmtBp(d.min_length) }))}</b>${tooltipRow(t("beforeAfter.basesKept"), `${fmtBases(d.bases)} (${fmtPct((100 * d.bases) / stats.total_bases)})`)}${tooltipRow(t("beforeAfter.readsKept"), fmtInt(d.reads))}`;
      },
    },
    xAxis: { type: logX ? "log" : "value", ...axisStyle(th, t("qcChart.minLength", { unit: bpUnit() }) + (logX ? ` · ${t("assembly.chart.logScale")}` : ""), { nameGap: 28 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) }, min: logX ? undefined : "dataMin" },
    yAxis: { type: "value", ...axisStyle(th, t("qcChart.basesRetained", { unit: bpUnit() }), { nameGap: 44 }), axisLabel: { color: th.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) } },
    series: [
      {
        type: "line",
        data: pts.map((d) => [d.min_length, d.bases]),
        showSymbol: pts.length <= 2,
        symbolSize: 8,
        step: "start",
        lineStyle: { width: 2, color: th.primary },
        itemStyle: { color: th.primary },
        areaStyle: { color: th.primary, opacity: 0.08 },
      },
    ],
  };
  return (
    <ChartCard
      title={t("qcChart.yieldTitle")}
      subtitle={t("qcChart.yieldSub")}
      explain="cumulative_yield"
      option={option}
      filePrefix={prefix}
      table={{
        columns: [t("qcChart.minLengthCol", { unit: bpUnit() }), t("beforeAfter.readsKept"), t("beforeAfter.basesKept"), t("qcChart.percentBases")],
        rows: stats.length_thresholds.map((r) => [r.min_length, r.reads, r.bases, fmtNum(r.bases_percent)]),
      }}
    />
  );
}
