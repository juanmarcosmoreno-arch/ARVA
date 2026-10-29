import type { EChartsOption } from "echarts";
import { useState } from "react";
import { ChartCard, Segmented } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, type ChartTheme, useChartTheme } from "@/components/charts/theme";
import { useT } from "@/i18n";
import { assemblyLabel, cumulativePoints, nxSteps } from "@/lib/assembly";
import { COVERAGE_LABEL, coverageKind, fmtCoverage } from "@/lib/shortReads";
import { escapeHtml, fmtBases, fmtBp, fmtCompact, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import type { Assembly, AssemblyContig } from "@/lib/types";

const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

function row(label: string, value: string) {
  return `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`;
}

const legend = (t: ChartTheme) => ({ top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: t.text, fontSize: 11 } });
const compactAxis = (t: ChartTheme) => ({ color: t.muted, fontSize: 10, formatter: (v: number) => fmtCompact(v) });
const prefixOf = (a: Assembly) => `arva_${a.assembler}_${a.id.slice(0, 8)}`;

export function ContigLengthHistogram({ assembly: a }: { assembly: Assembly }) {
  const t = useT();
  const th = useChartTheme();
  const [weight, setWeight] = useState<"contigs" | "bases">("contigs");
  const bins = a.stats.length_histogram ?? [];
  const range = (b: (typeof bins)[number]) => `${fmtInt(b.min_length)}–${fmtBp(b.max_length - 1)}`;
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const b = bins[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${escapeHtml(range(b))}</b>${row(t("assembly.chart.contigs"), fmtInt(b.contigs))}${row(t("assembly.chart.bases"), fmtBases(b.total_length))}`;
      },
    },
    xAxis: { type: "category", data: bins.map((b) => fmtCompact(b.min_length)), ...axisStyle(th, t("assembly.chart.lengthBins"), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", minInterval: 1, ...axisStyle(th, weight === "contigs" ? t("assembly.chart.contigs") : t("assembly.chart.bases"), { nameGap: 44 }), axisLabel: compactAxis(th) },
    series: [{ type: "bar", data: bins.map((b) => (weight === "contigs" ? b.contigs : b.total_length)), itemStyle: { color: th.primary, borderRadius: BAR_RADIUS }, barCategoryGap: "12%" }],
  };
  return (
    <ChartCard
      title={t("assembly.chart.histogram")}
      subtitle={t("assembly.chart.histogramSub", { contigs: fmtInt(a.stats.contig_count), min: fmtInt(a.stats.smallest_contig), max: fmtInt(a.stats.largest_contig) })}
      explain="assembly"
      option={option}
      filePrefix={prefixOf(a)}
      controls={
        <Segmented
          label={t("assembly.chart.weighting")}
          value={weight}
          onChange={setWeight}
          options={[
            { value: "contigs", label: t("assembly.chart.contigs") },
            { value: "bases", label: t("assembly.chart.bases") },
          ]}
        />
      }
      table={{ columns: [t("assembly.chart.lengthRange"), t("assembly.chart.contigs"), t("assembly.chart.bases")], rows: bins.map((b) => [range(b), b.contigs, b.total_length]) }}
    />
  );
}

/** Contig lengths against the share of the assembly reached (Nx curve), with N50 and N90 marked. */
export function NxChart({ assembly: a }: { assembly: Assembly }) {
  const t = useT();
  const th = useChartTheme();
  const curve = a.stats.cumulative;
  if (!curve) return null;
  const total = a.stats.total_length;
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const [x, len] = (p as { value: [number, number] }[])[0].value;
        return `${row("x", fmtPct(x, 1))}${row(t("assembly.chart.contigLength"), fmtBp(len))}`;
      },
    },
    xAxis: { type: "value", min: 0, max: 100, ...axisStyle(th, t("assembly.chart.nxAxis"), { nameGap: 28 }) },
    yAxis: { type: a.stats.largest_contig / Math.max(a.stats.smallest_contig, 1) >= 100 ? "log" : "value", ...axisStyle(th, t("assembly.chart.contigLength"), { nameGap: 44 }), axisLabel: compactAxis(th) },
    series: [
      {
        type: "line",
        data: nxSteps(curve, total),
        showSymbol: false,
        lineStyle: { width: 2, color: th.primary },
        itemStyle: { color: th.primary },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: th.text, type: "dashed", width: 1 },
          label: { color: th.text, fontSize: 10, formatter: "{b}" },
          data: [
            { name: `N50 ${fmtBp(a.stats.n50)}`, xAxis: 50 },
            { name: `N90 ${fmtBp(a.stats.n90)}`, xAxis: 90 },
          ],
        },
      },
    ],
  };
  return (
    <ChartCard
      title={t("assembly.chart.nx")}
      subtitle={t("assembly.chart.nxSub")}
      explain="assembly_n50"
      option={option}
      filePrefix={prefixOf(a)}
      footer={curve.downsampled ? <p>{t("assembly.chart.downsampled")}</p> : undefined}
      table={{
        columns: [t("assembly.col.rank"), t("assembly.chart.contigLength"), t("assembly.chart.cumulative"), "%"],
        rows: curve.rank.map((r, i) => [r, curve.length[i], curve.cumulative_length[i], fmtNum((100 * curve.cumulative_length[i]) / total, 2)]),
      }}
    />
  );
}

export function CumulativeChart({ assembly: a }: { assembly: Assembly }) {
  const t = useT();
  const th = useChartTheme();
  const curve = a.stats.cumulative;
  if (!curve) return null;
  const genome = a.stats.expected_genome_size.bp;
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const [rank, cum] = (p as { value: [number, number] }[])[0].value;
        return `<b>${escapeHtml(t("assembly.chart.firstContigs", { n: fmtInt(rank) }))}</b>${row(t("assembly.chart.cumulative"), fmtBp(cum))}`;
      },
    },
    xAxis: { type: "value", min: 1, minInterval: 1, ...axisStyle(th, t("assembly.chart.rankAxis"), { nameGap: 28 }) },
    yAxis: { type: "value", min: 0, max: genome ? Math.max(genome, a.stats.total_length) : undefined, ...axisStyle(th, t("assembly.chart.cumulative"), { nameGap: 44 }), axisLabel: compactAxis(th) },
    series: [
      {
        type: "line",
        step: "end",
        data: cumulativePoints(curve),
        showSymbol: curve.rank.length <= 30,
        symbolSize: 6,
        lineStyle: { width: 2, color: th.secondary },
        itemStyle: { color: th.secondary },
        areaStyle: { color: th.secondary, opacity: 0.08 },
        markLine: genome
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: th.text, type: "dashed", width: 1 },
              label: { color: th.text, fontSize: 10, formatter: "{b}", position: "insideEndTop" },
              data: [{ name: t("assembly.chart.expected", { size: fmtBases(genome) }), yAxis: genome }],
            }
          : undefined,
      },
    ],
  };
  return (
    <ChartCard
      title={t("assembly.chart.cumulativeTitle")}
      subtitle={t("assembly.chart.cumulativeSub", { total: fmtBases(a.stats.total_length) })}
      explain="assembly_n50"
      option={option}
      filePrefix={prefixOf(a)}
      footer={curve.downsampled ? <p>{t("assembly.chart.downsampled")}</p> : undefined}
      table={{
        columns: [t("assembly.col.rank"), t("assembly.chart.contigLength"), t("assembly.chart.cumulative")],
        rows: curve.rank.map((r, i) => [r, curve.length[i], curve.cumulative_length[i]]),
      }}
    />
  );
}

type ScatterAxis = "length" | "gc";

/** Contigs as points (coverage against length or GC), split by the assembler's circularity flag; tooltips name the contig. */
export function ContigScatter({ assembly: a, contigs, x }: { assembly: Assembly; contigs: AssemblyContig[]; x: ScatterAxis }) {
  const t = useT();
  const th = useChartTheme();
  const kind = coverageKind(a);
  const rows = contigs.filter((c) => c.coverage !== null && (x === "length" || c.gc_percent !== null));
  const groups = [
    { name: t("assembly.chart.circular"), color: th.series[2], rows: rows.filter((c) => c.circular === true) },
    { name: t("assembly.chart.notCircular"), color: th.series[0], rows: rows.filter((c) => c.circular === false) },
    { name: t("assembly.chart.circularUnknown"), color: th.muted, rows: rows.filter((c) => c.circular === null) },
  ].filter((g) => g.rows.length);
  const lengths = rows.map((c) => c.length);
  const logX = x === "length" && lengths.length > 0 && Math.max(...lengths) / Math.max(Math.min(...lengths), 1) >= 10;
  const point = (c: AssemblyContig) => ({ value: [x === "length" ? c.length : (c.gc_percent as number), c.coverage as number], name: c.name, contig: c });
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 56, right: 16, top: 32, bottom: 44 },
    legend: legend(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const c = (p as { data: { contig: AssemblyContig } }).data.contig;
        return (
          `<b>${escapeHtml(c.name)}</b>` +
          row(t("assembly.col.length"), fmtBp(c.length)) +
          row(kind ? t(COVERAGE_LABEL[kind]) : t("assembly.col.coverage"), fmtCoverage(c.coverage, kind)) +
          (c.gc_percent !== null ? row(t("assembly.col.gc"), fmtPct(c.gc_percent, 2)) : "") +
          (c.repeat ? row(t("assembly.col.repeat"), t("assembly.yes")) : "")
        );
      },
    },
    xAxis:
      x === "length"
        ? { type: logX ? "log" : "value", ...axisStyle(th, t("assembly.chart.lengthAxis") + (logX ? ` · ${t("assembly.chart.logScale")}` : ""), { nameGap: 28 }), axisLabel: compactAxis(th), min: logX ? undefined : "dataMin" }
        : { type: "value", ...axisStyle(th, t("assembly.chart.gcAxis"), { nameGap: 28 }), min: (v: { min: number }) => Math.floor(v.min - 1), max: (v: { max: number }) => Math.ceil(v.max + 1) },
    yAxis: { type: "value", ...axisStyle(th, kind ? t(COVERAGE_LABEL[kind]) : t("assembly.chart.coverageAxis", { assembler: a.assembler }), { nameGap: 44 }), axisLabel: compactAxis(th), min: 0 },
    series: groups.map((g, i) => ({
      name: g.name,
      type: "scatter",
      data: g.rows.map(point),
      symbolSize: 9,
      itemStyle: { color: g.color, opacity: 0.8, borderColor: th.surface, borderWidth: 0.5 },
      emphasis: { focus: "series" },
      markLine:
        i === 0 && x === "gc" && a.stats.gc_percent !== null
          ? { silent: true, symbol: "none", lineStyle: { color: th.text, type: "dashed", width: 1 }, label: { color: th.text, fontSize: 10, formatter: t("assembly.chart.assemblyGc", { gc: fmtNum(a.stats.gc_percent, 1) }) }, data: [{ xAxis: a.stats.gc_percent }] }
          : undefined,
    })),
  };
  const truncated = a.stats.contig_rows.truncated;
  return (
    <ChartCard
      title={x === "length" ? t("assembly.chart.coverageLength") : t("assembly.chart.gcCoverage")}
      subtitle={t("assembly.chart.scatterSub", { shown: fmtInt(rows.length), total: fmtInt(a.stats.contig_count) })}
      explain={x === "length" ? "assembly_coverage" : "gc_content"}
      option={option}
      filePrefix={prefixOf(a)}
      height={300}
      footer={
        <>
          <p>{t("assembly.chart.scatterNote", { assembler: a.assembler })}</p>
          {truncated && <p>{t("assembly.chart.rowsTruncated", { shown: fmtInt(a.stats.contig_rows.stored), total: fmtInt(a.stats.contig_rows.total) })}</p>}
        </>
      }
      table={{
        columns: [t("assembly.col.name"), t("assembly.col.length"), kind ? t(COVERAGE_LABEL[kind]) : t("assembly.col.coverage"), t("assembly.col.gc"), t("assembly.col.circular")],
        rows: rows.map((c) => [c.name, c.length, c.coverage ?? "—", c.gc_percent === null ? "—" : fmtNum(c.gc_percent, 2), c.circular === null ? "—" : c.circular ? t("assembly.yes") : t("assembly.no")]),
      }}
    />
  );
}

/** Cumulative length of several assemblies of the sample on shared axes, one colour each. */
export function CompareCumulativeChart({ assemblies }: { assemblies: Assembly[] }) {
  const t = useT();
  const th = useChartTheme();
  const shown = assemblies.filter((a) => a.stats.cumulative);
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 56, right: 16, top: 16 + 22 * Math.ceil(shown.length / 2), bottom: 44 },
    legend: { ...legend(th), left: 8 },
    tooltip: { ...baseOption(th).tooltip, trigger: "axis", valueFormatter: (v) => fmtBp(Number(v)) },
    xAxis: { type: "value", min: 1, minInterval: 1, ...axisStyle(th, t("assembly.chart.rankAxis"), { nameGap: 28 }) },
    yAxis: { type: "value", min: 0, ...axisStyle(th, t("assembly.chart.cumulative"), { nameGap: 44 }), axisLabel: compactAxis(th) },
    series: shown.map((a, i) => ({
      name: assemblyLabel(a),
      type: "line",
      step: "end",
      data: cumulativePoints(a.stats.cumulative!),
      showSymbol: false,
      lineStyle: { width: 2, color: th.series[i % th.series.length] },
      itemStyle: { color: th.series[i % th.series.length] },
    })),
  };
  const maxRank = Math.max(...shown.map((a) => a.stats.cumulative!.rank.length));
  return (
    <ChartCard
      title={t("assembly.compare.chart")}
      subtitle={t("assembly.compare.chartSub")}
      explain="assembly_n50"
      option={option}
      filePrefix="arva_assemblies"
      height={320}
      table={{
        columns: [t("assembly.col.rank"), ...shown.map(assemblyLabel)],
        rows: Array.from({ length: maxRank }, (_, i) => [i + 1, ...shown.map((a) => a.stats.cumulative!.cumulative_length[i] ?? "—")]),
      }}
    />
  );
}
