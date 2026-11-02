import type { EChartsOption } from "echarts";
import { Download } from "lucide-react";
import { ChartCard } from "@/components/charts/ChartCard";
import { baseOption, useChartTheme } from "@/components/charts/theme";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { aniFloor, heatmapCells, type ComparisonResultRead } from "@/lib/comparative";
import { fmtNum, fmtPct } from "@/lib/format";

/** The ANI matrix as a heatmap in the similarity order (labelled as clustering, not a phylogeny) and as a table. */
export function AniView({ result }: { result: ComparisonResultRead }) {
  const t = useT();
  const theme = useChartTheme();
  const m = result.summary.matrix!;
  const order = result.summary.order!.order;
  const labels = order.map((i) => m.ids[i]);
  const low = aniFloor(m);
  const cells = heatmapCells(m, order);
  const option: EChartsOption = {
    ...baseOption(theme),
    grid: { left: 150, right: 90, top: 16, bottom: 110 },
    tooltip: {
      ...baseOption(theme).tooltip,
      formatter: (p: unknown) => {
        const d = (p as { data: [number, number, number | "-"] }).data;
        const c = cells.find((x) => x.x === d[0] && x.y === d[1]);
        if (!c) return "";
        const v = c.value === null ? t("comparative.notReported") : `${fmtNum(c.value, 2)} %`;
        return `${c.row} → ${c.col}<br/>ANI ${v}`;
      },
    },
    xAxis: { type: "category", data: labels, axisLabel: { rotate: 40, color: theme.muted, fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "category", data: labels, inverse: true, axisLabel: { color: theme.muted, fontSize: 10 }, axisTick: { show: false } },
    visualMap: {
      min: low, max: 100, calculable: true, orient: "vertical", right: 8, top: "middle", precision: 1,
      textStyle: { color: theme.muted, fontSize: 10 },
      inRange: { color: theme.surface === "#FFFFFF" ? ["#EFF6FF", "#1F3B8A"] : ["#1E2A47", "#7FB2FF"] },
    },
    series: [{
      type: "heatmap" as const,
      data: cells.map((c) => [c.x, c.y, c.value ?? "-"]),
      label: { show: labels.length <= 12, fontSize: 9, formatter: (p: unknown) => {
        const v = (p as { data: [number, number, number | "-"] }).data[2];
        return v === "-" ? "" : fmtNum(v, 1);
      } },
      itemStyle: { borderColor: theme.surface, borderWidth: 1 },
      emphasis: { itemStyle: { borderColor: theme.text } },
    }],
  };
  const rows: (string | number)[][] = [];
  m.ids.forEach((a, i) => m.ids.forEach((b, j) => {
    if (i < j || (m.directional && i !== j)) rows.push([a, b, m.ani[i][j] ?? "—", m.af[i][j] === null ? "—" : fmtPct(m.af[i][j]! * 100, 1)]);
  }));
  return (
    <div className="space-y-3">
      <ChartCard
        title={t("comparative.heatmapTitle")}
        subtitle={t("comparative.heatmapSubtitle", { method: result.tool, version: result.tool_version })}
        explain="ani_matrix"
        option={option}
        height={Math.max(320, 60 + labels.length * 34 + 110)}
        filePrefix="arva_ani"
        table={{ columns: [t("comparative.genomeA"), t("comparative.genomeB"), t("comparative.aniPercent"), t("comparative.afA")], rows }}
        footer={
          <>
            <p>{t("comparative.notPhylogeny")}</p>
            {m.directional && <p>{t("comparative.directionalNote")}</p>}
            {(result.summary.pairs_not_reported ?? 0) > 0 && <p>{t("comparative.missingPairs", { n: result.summary.pairs_not_reported ?? 0 })}</p>}
          </>
        }
      />
      <a href={api.comparisonCsvUrl(result.id, "ani")} className="inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan">
        <Download className="h-3.5 w-3.5" /> {t("comparative.csvAni")}
      </a>
    </div>
  );
}
