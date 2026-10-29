import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Info } from "lucide-react";
import { ChartCard } from "@/components/charts/ChartCard";
import { baseOption, useChartTheme } from "@/components/charts/theme";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { NODE_KINDS, type NodeKind, nodeKind, nodeSize, segmentCoverage, selfLinks } from "@/lib/assembly";
import { coverageKind, fmtCoverage } from "@/lib/shortReads";
import { escapeHtml, fmtBp, fmtInt } from "@/lib/format";
import type { Assembly, AssemblyGraphEdge, AssemblyGraphNode } from "@/lib/types";

/** Segments drawn at most: a force layout of more stays readable on a laptop screen and responsive. */
export const GRAPH_VIEW_NODES = 500;
export const GRAPH_VIEW_EDGES = 2000;

const KIND_LABEL: Record<NodeKind, TranslationKey> = {
  circular: "assembly.graph.kind.circular",
  repeat: "assembly.graph.kind.repeat",
  other: "assembly.graph.kind.other",
  unknown: "assembly.graph.kind.unknown",
};

function row(label: string, value: string) {
  return `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`;
}

/** The assembly graph (GFA) as a force-directed network: node size by segment length, colour by the assembler's flags
 * of the contigs through each segment, links between segment ends; zoom with the wheel, pan by dragging. */
export function AssemblyGraphView({ assembly }: { assembly: Assembly }) {
  const t = useT();
  const th = useChartTheme();
  const graph = useQuery({
    queryKey: ["assemblyGraph", assembly.id, GRAPH_VIEW_NODES, GRAPH_VIEW_EDGES],
    queryFn: () => api.assemblyGraph(assembly.id, GRAPH_VIEW_NODES, GRAPH_VIEW_EDGES),
    staleTime: Infinity,
  });
  if (graph.isLoading) return <Skeleton className="h-80" />;
  if (graph.error || !graph.data) return <ErrorNote error={graph.error ?? t("assembly.graph.none")} />;
  const g = graph.data;
  const colour: Record<NodeKind, string> = { circular: th.series[2], repeat: th.series[1], other: th.primary, unknown: th.muted };
  const loops = selfLinks(g);
  const longest = g.nodes[0]?.length ?? 0;
  const coverage = (n: AssemblyGraphNode) => segmentCoverage(g, n);
  const nodeTip = (n: AssemblyGraphNode) =>
    `<b>${escapeHtml(n.id)}</b>` +
    row(t("assembly.graph.length"), fmtBp(n.length)) +
    (coverage(n) !== null ? row(t("assembly.graph.coverage", { meaning: g.coverage_meaning ?? g.coverage_tag ?? "" }), fmtCoverage(coverage(n), coverageKind(assembly))) : "") +
    row(t("assembly.graph.contigs"), n.paths.length ? n.paths.join(", ") : "—") +
    row(t("assembly.graph.colour"), t(KIND_LABEL[nodeKind(n)])) +
    (loops.has(n.id) ? row(t("assembly.graph.selfLink"), loops.get(n.id)!.join(", ")) : "");
  const edgeTip = (e: AssemblyGraphEdge) =>
    `<b>${escapeHtml(`${e.source}${e.source_orientation} → ${e.target}${e.target_orientation}`)}</b>` +
    row(t("assembly.graph.overlap"), e.overlap) +
    Object.entries(e.tags)
      .map(([k, v]) => row(k === "RC" && g.assembler === "Flye" ? t("assembly.graph.rc") : k, String(v)))
      .join("");
  const drawn = g.edges.filter((e) => e.source !== e.target);
  const option: EChartsOption = {
    ...baseOption(th),
    legend: { top: 0, left: 8, icon: "circle", itemWidth: 10, itemHeight: 10, textStyle: { color: th.text, fontSize: 11 }, data: NODE_KINDS.map((k) => t(KIND_LABEL[k])) },
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const d = p as { dataType: string; data: { node?: AssemblyGraphNode; edge?: AssemblyGraphEdge } };
        return d.dataType === "edge" && d.data.edge ? edgeTip(d.data.edge) : d.data.node ? nodeTip(d.data.node) : "";
      },
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        top: 32,
        categories: NODE_KINDS.map((k) => ({ name: t(KIND_LABEL[k]), itemStyle: { color: colour[k] } })),
        data: g.nodes.map((n) => ({
          id: n.id,
          name: n.id,
          value: n.length,
          category: NODE_KINDS.indexOf(nodeKind(n)),
          symbolSize: nodeSize(n.length, longest),
          node: n,
          itemStyle: { borderColor: th.surface, borderWidth: 1 },
        })),
        edges: drawn.map((e) => ({ source: e.source, target: e.target, edge: e })),
        autoCurveness: true,
        lineStyle: { color: th.axis, width: 1.5, opacity: 0.9 },
        emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        label: { show: g.nodes.length <= 30, position: "right", color: th.text, fontSize: 10 },
        force: { repulsion: g.nodes.length > 200 ? 80 : 240, edgeLength: [30, 90], gravity: 0.08, layoutAnimation: g.nodes.length <= 200 },
      },
    ],
  };
  return (
    <ChartCard
      title={t("assembly.graph.title")}
      subtitle={t("assembly.graph.subtitle", { segments: fmtInt(g.segment_count), links: fmtInt(g.link_count), paths: fmtInt(g.path_count) })}
      explain="assembly_graph"
      option={option}
      height={440}
      filePrefix={`arva_${assembly.assembler}_${assembly.id.slice(0, 8)}`}
      footer={
        <>
          {g.truncated && (
            <p className="flex gap-1.5 text-amber-700 dark:text-warning">
              <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {t("assembly.graph.truncated", { nodes: fmtInt(g.nodes.length), segments: fmtInt(g.segment_count), edges: fmtInt(g.edges.length), links: fmtInt(g.link_count - g.dangling_links) })}
            </p>
          )}
          <p>{t("assembly.graph.colourNote", { assembler: g.assembler })}</p>
          {loops.size > 0 && <p>{t("assembly.graph.selfLinksNote", { count: loops.size })}</p>}
          {g.coverage_tag && <p>{t("assembly.graph.coverageNote", { tag: g.coverage_tag, meaning: g.coverage_meaning ?? "", assembler: g.assembler })}</p>}
          {g.dangling_links > 0 && <p>{t("assembly.graph.dangling", { count: g.dangling_links })}</p>}
          <p>{t("assembly.graph.navigate")}</p>
        </>
      }
      table={{
        columns: [t("assembly.graph.segment"), t("assembly.graph.length"), t("assembly.col.coverage"), t("assembly.graph.contigs"), t("assembly.graph.colour"), t("assembly.graph.selfLink")],
        rows: g.nodes.map((n) => [n.id, n.length, coverage(n) ?? "—", n.paths.join(", ") || "—", t(KIND_LABEL[nodeKind(n)]), loops.get(n.id)?.join(", ") ?? "—"]),
      }}
    />
  );
}
