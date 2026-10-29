import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { useState } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, type ChartTheme, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody } from "@/components/ui/card";
import { Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import {
  binLabel,
  cogRows,
  densityRows,
  densityStrands,
  densitySummary,
  hypotheticalRows,
  lengthClasses,
  lengthTable,
  pct,
  strandRows,
} from "@/lib/annotationCharts";
import { api } from "@/lib/api";
import { bpUnit, escapeHtml, fmtBp, fmtCompact, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import type { Annotation, AnnotationCharts as Charts, LengthClass } from "@/lib/types";
import { typeLabel } from "./FeatureDetail";

const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];
const H_RADIUS: [number, number, number, number] = [0, 4, 4, 0];
const LENGTH_BINS = [0, 50, 100, 200, 500];
const WINDOWS = [0, 1_000, 5_000, 10_000, 50_000, 100_000];

const legend = (th: ChartTheme) => ({ top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: th.text, fontSize: 11 } });
const row = (label: string, value: string) =>
  `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`;
const share = (v: number | null) => (v == null ? "—" : fmtPct(v, 1));

/**
 * Spec §11 "Visualizaciones": features by type, gene lengths, gene density along each sequence, strand, COG
 * categories and hypothetical against characterised CDS. All are counts of the annotator's predictions; a chart
 * whose step did not run says so instead of drawing zeros.
 */
export function AnnotationChartsPanel({ annotation }: { annotation: Annotation }) {
  const t = useT();
  const [lengthBin, setLengthBin] = useState(0);
  const [window, setWindow] = useState(0);
  const charts = useQuery({
    queryKey: ["annotationCharts", annotation.id, lengthBin, window],
    queryFn: () => api.annotationCharts(annotation.id, { lengthBin, window }),
    placeholderData: keepPreviousData,
  });
  const c = charts.data;
  if (charts.error) return <ErrorNote error={charts.error} />;
  if (!c) return <p className="text-xs text-muted-foreground">{t("common.loading")}</p>;
  const prefix = `arva_${annotation.tool.toLowerCase()}_${annotation.id.slice(0, 8)}`;
  const synthetic = (annotation.summary.synthetic_evidence ?? []).length > 0;
  return (
    <section className="space-y-3" aria-label={t("annotation.charts.title")}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold">{t("annotation.charts.title")}</h4>
        <Explain id="annotation_charts" compact />
        {synthetic && <span className="text-xs font-medium text-warning">{t("annotation.charts.synthetic")}</span>}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <TypesChart c={c} prefix={prefix} />
        <HypotheticalChart c={c} prefix={prefix} tool={annotation.tool} />
        <LengthChart
          c={c}
          prefix={prefix}
          controls={
            <label className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">{t("annotation.charts.binWidth")}</span>
              <Select value={lengthBin} onChange={(e) => setLengthBin(Number(e.target.value))} className="h-8 w-32">
                {LENGTH_BINS.map((w) => (
                  <option key={w} value={w}>
                    {w ? fmtBp(w) : t("annotation.charts.auto", { v: fmtBp(c.lengths.width ?? 0) })}
                  </option>
                ))}
              </Select>
            </label>
          }
        />
        <StrandChart c={c} prefix={prefix} />
        <DensityChart
          c={c}
          prefix={prefix}
          windowControl={
            <label className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">{t("annotation.charts.window")}</span>
              <Select value={window} onChange={(e) => setWindow(Number(e.target.value))} className="h-8 w-36">
                {WINDOWS.map((w) => (
                  <option key={w} value={w}>
                    {w ? fmtBp(w) : t("annotation.charts.auto", { v: fmtBp(c.density.window) })}
                  </option>
                ))}
              </Select>
            </label>
          }
        />
        <CogChart c={c} prefix={prefix} tool={annotation.tool} />
      </div>
    </section>
  );
}

function NotAvailable({ title, text, explain }: { title: string; text: string; explain?: "cog" | "hypothetical_proteins" }) {
  return (
    <Card>
      <CardBody className="space-y-1.5 py-4">
        <div className="flex items-center gap-1">
          <h3 className="text-sm font-semibold">{title}</h3>
          {explain && <Explain id={explain} compact className="p-1.5" />}
        </div>
        <p className="text-xs text-muted-foreground">{text}</p>
      </CardBody>
    </Card>
  );
}

function TypesChart({ c, prefix }: { c: Charts; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const types = c.types.types;
  if (!types.length) return <NotAvailable title={t("annotation.chart.types")} text={t("annotation.noFeatures")} />;
  const labels = types.map((k) => typeLabel(t, k));
  const contigs = c.types.by_contig.length > 1 && c.types.by_contig.length <= 6 ? c.types.by_contig : [];
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 112, right: 32, top: 8, bottom: 36 },
    tooltip: { ...baseOption(th).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } } },
    xAxis: { type: "value", minInterval: 1, ...axisStyle(th, t("annotation.chart.features"), { nameGap: 24 }) },
    yAxis: { type: "category", data: labels, inverse: true, axisLabel: { color: th.text, fontSize: 11 }, axisLine: { lineStyle: { color: th.axis } }, axisTick: { show: false } },
    series: [{ type: "bar", data: types.map((k) => c.types.total[k]), itemStyle: { color: th.primary, borderRadius: H_RADIUS }, barMaxWidth: 18, label: { show: true, position: "right", color: th.text, fontSize: 10 } }],
  };
  return (
    <ChartCard
      title={t("annotation.chart.types")}
      subtitle={t("annotation.chart.typesSub")}
      option={option}
      filePrefix={prefix}
      height={Math.max(160, 40 + types.length * 26)}
      table={{
        columns: [t("annotation.col.type"), t("annotation.chart.features"), ...contigs.map((x) => x.contig_in_assembly)],
        rows: types.map((k, i) => [labels[i], c.types.total[k], ...contigs.map((x) => x.counts[k] ?? 0)]),
      }}
    />
  );
}

function HypotheticalChart({ c, prefix, tool }: { c: Charts; prefix: string; tool: string }) {
  const t = useT();
  const th = useChartTheme();
  const rows = hypotheticalRows(c.hypothetical);
  if (!c.hypothetical.total) return <NotAvailable title={t("annotation.charts.hypothetical")} text={t("annotation.charts.cdsNotSearched", { tool })} explain="hypothetical_proteins" />;
  const names = rows.map((r) => r.name || t("annotation.charts.allSequences"));
  const series = (["characterised", "hypothetical"] as const).map((k, slot) => ({
    name: t(`annotation.charts.${k}`),
    type: "bar" as const,
    stack: "cds",
    data: rows.map((r) => r[k]),
    itemStyle: { color: th.series[slot], borderColor: th.surface, borderWidth: 1 },
    barMaxWidth: 22,
  }));
  const option: EChartsOption = {
    ...baseOption(th),
    legend: legend(th),
    grid: { left: 140, right: 24, top: 28, bottom: 36 },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        const r = rows[i];
        return `<b>${escapeHtml(names[i])}</b>${row(t("annotation.charts.characterised"), fmtInt(r.characterised))}${row(t("annotation.charts.hypothetical"), `${fmtInt(r.hypothetical)} (${share(r.share)})`)}`;
      },
    },
    xAxis: { type: "value", minInterval: 1, ...axisStyle(th, "CDS", { nameGap: 24 }) },
    yAxis: { type: "category", data: names.map((n) => (n.length > 20 ? `${n.slice(0, 19)}…` : n)), inverse: true, axisLabel: { color: th.text, fontSize: 11 }, axisLine: { lineStyle: { color: th.axis } }, axisTick: { show: false } },
    series,
  };
  const total = c.hypothetical.total;
  return (
    <ChartCard
      title={t("annotation.charts.hypothetical")}
      subtitle={t("annotation.charts.hypotheticalSub", { n: fmtInt(total.hypothetical), total: fmtInt(total.characterised + total.hypothetical), share: share(pct(total.hypothetical, total.characterised + total.hypothetical)) })}
      explain="hypothetical_proteins"
      option={option}
      filePrefix={prefix}
      height={Math.max(150, 60 + rows.length * 32)}
      footer={<p>{t("annotation.charts.hypotheticalNote")}</p>}
      table={{
        columns: [t("annotation.charts.sequence"), t("annotation.charts.characterised"), t("annotation.charts.hypothetical"), t("annotation.charts.hypotheticalShare")],
        rows: rows.map((r, i) => [names[i], r.characterised, r.hypothetical, share(r.share)]),
      }}
    />
  );
}

function LengthChart({ c, prefix, controls }: { c: Charts; prefix: string; controls: React.ReactNode }) {
  const t = useT();
  const th = useChartTheme();
  const classes = lengthClasses(c.lengths);
  if (!classes.length) return <NotAvailable title={t("annotation.charts.lengths")} text={t("annotation.charts.noGenes")} />;
  const { labels, series } = lengthTable(c.lengths);
  const name = (k: LengthClass) => t(`annotation.charts.class.${k}` as TranslationKey);
  const option: EChartsOption = {
    ...baseOption(th),
    legend: legend(th),
    grid: { left: 52, right: 16, top: 28, bottom: 48 },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>${escapeHtml(`${binLabel(c.lengths.bins[i])} ${bpUnit()}`)}</b>${classes.map(({ cls }) => row(name(cls), fmtInt(series[cls][i]))).join("")}`;
      },
    },
    xAxis: { type: "category", data: labels, ...axisStyle(th, t("annotation.charts.lengthAxis"), { nameGap: 30, splitLine: { show: false } }), axisLabel: { color: th.muted, fontSize: 10, hideOverlap: true, formatter: (v: string) => v.split("–")[0] } },
    yAxis: { type: "value", minInterval: 1, ...axisStyle(th, t("annotation.charts.genes"), { nameGap: 36 }) },
    series: classes.map(({ cls, slot }, i) => ({
      name: name(cls),
      type: "bar" as const,
      stack: "len",
      data: series[cls],
      barCategoryGap: "10%",
      itemStyle: { color: th.series[slot], borderColor: th.surface, borderWidth: 1, borderRadius: i === classes.length - 1 ? BAR_RADIUS : 0 },
    })),
  };
  const st = c.lengths.classes;
  return (
    <ChartCard
      title={t("annotation.charts.lengths")}
      subtitle={classes.map(({ cls }) => t("annotation.charts.median", { name: name(cls), v: fmtInt(st[cls].median ?? 0), n: fmtInt(st[cls].n) })).join(" · ")}
      option={option}
      filePrefix={prefix}
      controls={controls}
      footer={<p>{t("annotation.charts.lengthsNote", { w: fmtInt(c.lengths.width ?? 0) })}</p>}
      table={{
        columns: [t("annotation.charts.lengthRange"), ...classes.map(({ cls }) => name(cls))],
        rows: c.lengths.bins.map((b, i) => [binLabel(b), ...classes.map(({ cls }) => series[cls][i])]),
      }}
    />
  );
}

function StrandChart({ c, prefix }: { c: Charts; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const rows = strandRows(c.strand);
  if (!rows.length) return <NotAvailable title={t("annotation.charts.strand")} text={t("annotation.charts.noGenes")} />;
  const hasNone = rows.some((r) => r.counts["."] > 0);
  const keys = (["+", "-", "."] as const).filter((k) => k !== "." || hasNone);
  const strandName = (k: "+" | "-" | ".") => t(k === "+" ? "explorer.strand.forward" : k === "-" ? "explorer.strand.reverse" : "explorer.strand.none");
  const labels = rows.map((r) => typeLabel(t, r.type));
  const option: EChartsOption = {
    ...baseOption(th),
    legend: legend(th),
    grid: { left: 112, right: 24, top: 28, bottom: 36 },
    tooltip: { ...baseOption(th).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } } },
    xAxis: { type: "value", minInterval: 1, ...axisStyle(th, t("annotation.charts.genes"), { nameGap: 24 }) },
    yAxis: { type: "category", data: labels, inverse: true, axisLabel: { color: th.text, fontSize: 11 }, axisLine: { lineStyle: { color: th.axis } }, axisTick: { show: false } },
    series: keys.map((k, slot) => ({
      name: strandName(k),
      type: "bar" as const,
      stack: "strand",
      data: rows.map((r) => r.counts[k]),
      itemStyle: { color: th.series[slot], borderColor: th.surface, borderWidth: 1 },
      barMaxWidth: 20,
    })),
  };
  const tot = c.strand.total;
  return (
    <ChartCard
      title={t("annotation.charts.strand")}
      subtitle={t("annotation.charts.strandSub", { f: fmtInt(tot["+"]), r: fmtInt(tot["-"]), share: share(pct(tot["+"], tot["+"] + tot["-"])) })}
      option={option}
      filePrefix={prefix}
      height={Math.max(150, 60 + rows.length * 30)}
      footer={<p>{t("annotation.charts.strandNote")}</p>}
      table={{
        columns: [t("annotation.col.type"), ...keys.map(strandName), t("annotation.charts.forwardShare")],
        rows: [
          ...rows.map((r, i) => [labels[i], ...keys.map((k) => r.counts[k]), share(r.share == null ? null : 100 * r.share)]),
          ...c.strand.by_contig.map((x) => [`${t("annotation.charts.sequence")}: ${x.contig_in_assembly}`, ...keys.map((k) => x[k]), share(pct(x["+"], x["+"] + x["-"]))]),
        ],
      }}
    />
  );
}

function DensityChart({ c, prefix, windowControl }: { c: Charts; prefix: string; windowControl: React.ReactNode }) {
  const t = useT();
  const th = useChartTheme();
  const contigs = c.density.contigs.filter((x) => x.genes > 0);
  const [chosen, setChosen] = useState<string | null>(null);
  const d = contigs.find((x) => x.contig === chosen) ?? contigs[0];
  if (!d) return <NotAvailable title={t("annotation.charts.density")} text={t("annotation.charts.noGenes")} />;
  const w = c.density.window;
  const strands = densityStrands(d);
  const strandName = (k: "+" | "-" | ".") => t(k === "+" ? "explorer.strand.forward" : k === "-" ? "explorer.strand.reverse" : "explorer.strand.none");
  const summary = densitySummary(d, w);
  const option: EChartsOption = {
    ...baseOption(th),
    legend: legend(th),
    grid: { left: 44, right: 16, top: 28, bottom: 44 },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>${escapeHtml(`${fmtInt(d.start[i])}–${fmtInt(d.end[i])}`)}</b>${strands.map((s) => row(strandName(s.key), fmtInt(d[s.field][i]))).join("")}${row(t("annotation.charts.total"), fmtInt(d.total[i]))}`;
      },
    },
    xAxis: { type: "category", data: d.start.map((s) => fmtCompact(s - 1)), ...axisStyle(th, t("annotation.charts.positionAxis", { seq: d.contig_in_assembly }), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", minInterval: 1, ...axisStyle(th, t("annotation.charts.genesPerWindow"), { nameGap: 30 }) },
    series: strands.map((s, i) => ({
      name: strandName(s.key),
      type: "bar" as const,
      stack: "density",
      data: d[s.field],
      barCategoryGap: "8%",
      itemStyle: { color: th.series[s.slot], borderColor: th.surface, borderWidth: d.start.length > 150 ? 0 : 1, borderRadius: i === strands.length - 1 ? BAR_RADIUS : 0 },
    })),
  };
  return (
    <ChartCard
      title={t("annotation.charts.density")}
      subtitle={t("annotation.charts.densitySub", { w: fmtInt(w), seq: d.contig_in_assembly, n: fmtInt(d.genes) })}
      option={option}
      filePrefix={`${prefix}_${d.contig_in_assembly.replace(/[^A-Za-z0-9._-]+/g, "_")}`}
      controls={
        <>
          {contigs.length > 1 && (
            <label className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">{t("annotation.charts.sequence")}</span>
              <Select value={d.contig} onChange={(e) => setChosen(e.target.value)} className="h-8 w-56">
                {contigs.map((x) => (
                  <option key={x.contig} value={x.contig}>
                    {x.contig_in_assembly} · {t("annotation.charts.genesN", { n: fmtInt(x.genes) })}
                  </option>
                ))}
              </Select>
            </label>
          )}
          {windowControl}
        </>
      }
      footer={
        <>
          {summary && <p>{t("annotation.charts.densitySummary", { min: fmtInt(summary.min), median: fmtNum(summary.median, 1), max: fmtInt(summary.max), n: fmtInt(summary.windows) })}</p>}
          <p>{t("annotation.charts.densityNote")}</p>
        </>
      }
      table={{
        columns: [t("annotation.charts.windowRange"), strandName("+"), strandName("-"), strandName("."), t("annotation.charts.total")],
        rows: densityRows(d, w),
      }}
    />
  );
}

function CogChart({ c, prefix, tool }: { c: Charts; prefix: string; tool: string }) {
  const t = useT();
  const th = useChartTheme();
  const title = t("annotation.chart.cog");
  if (!c.cog.cds_searched) return <NotAvailable title={title} text={t("annotation.charts.cdsNotSearched", { tool })} explain="cog" />;
  if (!c.cog.reported)
    return <NotAvailable title={title} text={t(c.cog.cds_with_cog_id ? "annotation.charts.cogIdsOnly" : "annotation.charts.cogNone", { tool, n: fmtInt(c.cog.cds_with_cog_id) })} explain="cog" />;
  const rows = cogRows(c.cog);
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 40, right: 16, top: 12, bottom: 40 },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const r = rows[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${escapeHtml(`${r.letter} · ${r.name ?? t("annotation.charts.cogUnknownLetter")}`)}</b>${row("CDS", fmtInt(r.cds))}${row(t("annotation.charts.ofCategorised"), share(r.share))}`;
      },
    },
    xAxis: { type: "category", data: rows.map((r) => r.letter), ...axisStyle(th, t("annotation.charts.cogAxis"), { nameGap: 26, splitLine: { show: false } }) },
    yAxis: { type: "value", minInterval: 1, ...axisStyle(th, "CDS", { nameGap: 32 }) },
    series: [{ type: "bar", data: rows.map((r) => r.cds), itemStyle: { color: th.primary, borderRadius: BAR_RADIUS }, barMaxWidth: 22 }],
  };
  return (
    <ChartCard
      title={title}
      subtitle={t("annotation.charts.cogSub", { n: fmtInt(c.cog.cds_with_category), total: fmtInt(c.cog.cds ?? 0) })}
      explain="cog"
      option={option}
      filePrefix={prefix}
      footer={<p>{t("annotation.charts.cogNames", { source: c.cog.names_source })}</p>}
      table={{
        columns: ["COG", t("annotation.charts.cogName"), "CDS", t("annotation.charts.ofCategorised")],
        rows: rows.map((r) => [r.letter, r.name ?? t("annotation.charts.cogUnknownLetter"), r.cds, share(r.share)]),
      }}
    />
  );
}
