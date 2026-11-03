import type { EChartsOption } from "echarts";
import { Download, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChartCard } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Select } from "@/components/ui/form";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import {
  dotSegments,
  explorerUrl,
  identityColor,
  identityFloor,
  offsets,
  segmentPoints,
  syntenyLinks,
  type AlignmentData,
  type ComparisonMember,
  type ComparisonResultRead,
  type Difference,
} from "@/lib/comparative";
import { fmtBases, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { SvgFigure } from "./SvgFigure";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";
const MIN_LENGTHS = [0, 1000, 5000, 20000];

type Annotations = Map<string, string | null>;

function pct(v: number | null) {
  return v === null ? "—" : fmtPct(v * 100, 2);
}

/** Everything one alignment result shows: the pairs, a dot plot, synteny across the order, conservation along the
 * reference and dnadiff's structural differences, each with its export. */
export function AlignmentView({ result, members }: { result: ComparisonResultRead; members: ComparisonMember[] }) {
  const t = useT();
  const data = result.alignment;
  const annotations: Annotations = new Map(members.map((m) => [m.assembly_id, m.annotation_id]));
  if (!data) return <p className="text-sm text-amber-700 dark:text-warning">{t("comparative.alignmentMissing")}</p>;
  return (
    <div className="space-y-4">
      <PairTable result={result} />
      <DotPlot data={data} />
      <SyntenyPlot data={data} />
      <ConservationMap data={data} />
      <Differences result={result} data={data} annotations={annotations} />
      <div className="flex flex-wrap gap-3 text-xs">
        {(["blocks", "conservation", "differences"] as const).map((k) => (
          <a key={k} href={api.comparisonCsvUrl(result.id, k)} className={`inline-flex items-center gap-1 ${LINK}`}>
            <Download className="h-3.5 w-3.5" /> {t(`comparative.csv.${k}` as TranslationKey)}
          </a>
        ))}
      </div>
    </div>
  );
}

function PairTable({ result }: { result: ComparisonResultRead }) {
  const t = useT();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr>
            {["reference", "query", "pairRoleTitle", "blocks", "refAligned", "queryAligned", "identity"].map((k) => (
              <th key={k} className="px-2 py-1.5 font-medium">{t(`comparative.col.${k}` as TranslationKey)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {(result.summary.pairs ?? []).map((p) => (
            <tr key={`${p.reference}|${p.query}`}>
              <td className="px-2 py-1.5">{p.reference}</td>
              <td className="px-2 py-1.5">{p.query}</td>
              <td className="px-2 py-1.5">{t(`comparative.role.${p.role}` as TranslationKey)}</td>
              <td className="px-2 py-1.5 tabular-nums">{t("comparative.blocksLine", { n: p.blocks, f: p.forward, r: p.reverse })}</td>
              <td className="px-2 py-1.5 tabular-nums">{pct(p.ref_fraction)}</td>
              <td className="px-2 py-1.5 tabular-nums">{pct(p.query_fraction)}</td>
              <td className="px-2 py-1.5 tabular-nums">{p.identity === null ? "—" : `${fmtNum(p.identity, 2)} %`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-2 py-1.5 text-[11px] text-muted-foreground">{t(`comparative.identityNote.${result.method}` as TranslationKey)}</p>
    </div>
  );
}

function PairSelect({ data, value, onChange }: { data: AlignmentData; value: number; onChange: (i: number) => void }) {
  const t = useT();
  return (
    <Select className="h-8 w-auto text-xs" value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={t("comparative.pair")}>
      {data.pairs.map((p, i) => (
        <option key={i} value={i}>
          {data.genomes[p.reference].label} × {data.genomes[p.query].label}
        </option>
      ))}
    </Select>
  );
}

function DotPlot({ data }: { data: AlignmentData }) {
  const t = useT();
  const theme = useChartTheme();
  const [index, setIndex] = useState(0);
  const [primaryOnly, setPrimaryOnly] = useState(true);
  const pair = data.pairs[index];
  const ref = data.genomes[pair.reference];
  const qry = data.genomes[pair.query];
  const refOff = offsets(ref.contigs);
  const qryOff = offsets(qry.contigs);
  const { forward, reverse } = dotSegments(pair.blocks, refOff, qryOff, primaryOnly);
  const boundary = (contigs: { length: number }[]) => contigs.slice(0, -1).reduce<number[]>((acc, c) => [...acc, (acc.at(-1) ?? 0) + c.length], []);
  const line = (name: string, color: string, points: ReturnType<typeof segmentPoints>) => ({
    name, type: "line" as const, data: points, showSymbol: false, lineStyle: { color, width: 1.5 }, itemStyle: { color }, connectNulls: false,
  });
  const option: EChartsOption = {
    ...baseOption(theme),
    grid: { left: 72, right: 24, top: 32, bottom: 72 },
    legend: { top: 0, textStyle: { color: theme.muted, fontSize: 11 } },
    tooltip: { ...baseOption(theme).tooltip, trigger: "item", formatter: (p: unknown) => {
      const { seriesName, data: d } = p as { seriesName: string; data: [number, number] };
      return `${seriesName}<br/>${ref.label}: ${fmtInt(d[0])}<br/>${qry.label}: ${fmtInt(d[1])}`;
    } },
    xAxis: { type: "value", min: 0, max: ref.total_length, ...axisStyle(theme, t("comparative.positionOf", { genome: ref.label }), { nameGap: 28 }) },
    yAxis: { type: "value", min: 0, max: qry.total_length, ...axisStyle(theme, t("comparative.positionOf", { genome: qry.label }), { nameGap: 56 }) },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      { type: "inside", yAxisIndex: 0, filterMode: "none" },
      { type: "slider", xAxisIndex: 0, height: 14, bottom: 6, filterMode: "none" },
    ],
    series: [
      { ...line(t("comparative.forward"), theme.series[0], segmentPoints(forward)),
        markLine: { silent: true, symbol: "none", lineStyle: { color: theme.axis, type: "dashed", width: 1 }, label: { show: false },
          data: [...boundary(ref.contigs).map((x) => ({ xAxis: x })), ...boundary(qry.contigs).map((y) => ({ yAxis: y }))] } },
      line(t("comparative.reverse"), theme.series[1], segmentPoints(reverse)),
    ],
  };
  return (
    <ChartCard
      title={t("comparative.dotPlotTitle")}
      subtitle={t("comparative.dotPlotSubtitle")}
      explain="genome_alignment"
      option={option}
      height={460}
      filePrefix="arva_dotplot"
      controls={
        <>
          <PairSelect data={data} value={index} onChange={setIndex} />
          <label className="flex items-center gap-1.5 text-xs">
            <input type="checkbox" className="h-3.5 w-3.5 accent-arva-teal" checked={primaryOnly} onChange={(e) => setPrimaryOnly(e.target.checked)} />
            {t("comparative.primaryOnly")}
          </label>
        </>
      }
      footer={<p>{t("comparative.dotPlotNote")}</p>}
    />
  );
}

function SyntenyPlot({ data }: { data: AlignmentData }) {
  const t = useT();
  const theme = useChartTheme();
  const dark = theme.surface !== "#FFFFFF";
  const [minLength, setMinLength] = useState(1000);
  const W = 960, left = 150, right = 16, barH = 10, gap = 90;
  const width = W - left - right;
  const layouts = data.genomes.map((g) => ({ offsets: offsets(g.contigs), total: g.total_length }));
  const neighbours = data.genomes.slice(0, -1).map((_g, k) => data.pairs.find((p) => p.reference === k && p.query === k + 1));
  const identities = neighbours.flatMap((p) => (p ? p.blocks.filter((b) => b[9]).map((b) => b[7]) : []));
  const low = identityFloor(identities);
  const height = 24 + data.genomes.length * (barH + gap) - gap + 40;
  const y = (k: number) => 24 + k * (barH + gap);
  return (
    <SvgFigure
      title={t("comparative.syntenyTitle")}
      subtitle={t("comparative.syntenySubtitle")}
      explain="synteny_plot"
      fileStem="arva_synteny"
      controls={
        <label className="flex items-center gap-1.5">
          {t("comparative.minLink")}
          <Select className="h-8 w-auto text-xs" value={minLength} onChange={(e) => setMinLength(Number(e.target.value))}>
            {MIN_LENGTHS.map((n) => (
              <option key={n} value={n}>{n ? fmtBases(n) : t("comparative.allLinks")}</option>
            ))}
          </Select>
        </label>
      }
      footer={<p>{t("comparative.syntenyNote", { low })}</p>}
    >
      {(ref) => (
        <svg ref={ref} viewBox={`0 0 ${W} ${height}`} className="h-auto w-full" role="img" aria-label={t("comparative.syntenyTitle")}>
          <rect x={0} y={0} width={W} height={height} fill={theme.surface} />
          {neighbours.map((p, k) => p && syntenyLinks(p.blocks, layouts[k], layouts[k + 1], minLength).map((l, i) => {
            const y0 = y(k) + barH, y1 = y(k + 1);
            const [a, b] = [left + l.r0 * width, left + l.r1 * width];
            const [c, d] = l.reverse ? [left + l.q1 * width, left + l.q0 * width] : [left + l.q0 * width, left + l.q1 * width];
            return (
              <path key={`${k}-${i}`} d={`M${a},${y0} L${b},${y0} L${d},${y1} L${c},${y1} Z`} fill={identityColor(l.identity, low, l.reverse, dark)} fillOpacity={0.75}>
                <title>{`${data.genomes[k].label} ${l.block[0]}:${fmtInt(l.block[1])}-${fmtInt(l.block[2])} → ${data.genomes[k + 1].label} ${l.block[3]}:${fmtInt(l.block[4])}-${fmtInt(l.block[5])} (${l.block[6]}) · ${fmtNum(l.identity, 2)} % · ${fmtBases(l.length)}`}</title>
              </path>
            );
          }))}
          {data.genomes.map((g, k) => {
            let x = left;
            return (
              <g key={g.assembly_id}>
                <text x={left - 8} y={y(k) + barH - 1} textAnchor="end" fontSize={11} fill={theme.text}>
                  {g.label}
                </text>
                {g.contigs.map((c, i) => {
                  const w = (c.length / g.total_length) * width;
                  const el = <rect key={c.name} x={x} y={y(k)} width={Math.max(w - 0.6, 0.4)} height={barH} rx={2} fill={i % 2 ? theme.secondary : theme.primary}><title>{`${c.name} · ${fmtBases(c.length)}`}</title></rect>;
                  x += w;
                  return el;
                })}
              </g>
            );
          })}
        </svg>
      )}
    </SvgFigure>
  );
}

function ConservationMap({ data }: { data: AlignmentData }) {
  const t = useT();
  const theme = useChartTheme();
  const dark = theme.surface !== "#FFFFFF";
  const cons = data.conservation;
  const ref = data.genomes[data.reference];
  const refOff = offsets(ref.contigs);
  const W = 960, left = 150, rowH = 16, gap = 6;
  const width = W - left - 16;
  const identities = cons.genomes.flatMap((g) => g.windows.map((w) => w.identity).filter((v): v is number => v !== null));
  const low = identityFloor(identities);
  const height = 30 + cons.genomes.length * (rowH + gap);
  return (
    <SvgFigure
      title={t("comparative.conservationTitle", { reference: cons.reference })}
      subtitle={t("comparative.conservationSubtitle", { window: fmtBases(cons.window) })}
      explain="synteny_plot"
      fileStem="arva_conservation"
      footer={<p>{t("comparative.conservationNote", { low })}</p>}
    >
      {(svgRef) => (
        <svg ref={svgRef} viewBox={`0 0 ${W} ${height}`} className="h-auto w-full" role="img" aria-label={t("comparative.conservationTitle", { reference: cons.reference })}>
          <rect x={0} y={0} width={W} height={height} fill={theme.surface} />
          {ref.contigs.map((c) => (
            <text key={c.name} x={left + ((refOff.get(c.name) ?? 0) / ref.total_length) * width} y={12} fontSize={9} fill={theme.muted}>{c.name}</text>
          ))}
          {cons.genomes.map((g, k) => {
            const top = 20 + k * (rowH + gap);
            return (
              <g key={g.label}>
                <text x={left - 8} y={top + rowH - 4} textAnchor="end" fontSize={11} fill={theme.text}>{g.label}</text>
                <rect x={left} y={top} width={width} height={rowH} fill={dark ? "#1E2A47" : "#E5E7EB"} />
                {g.windows.map((w, i) => w.covered > 0 && w.identity !== null && (
                  <rect key={i} x={left + (((refOff.get(w.contig) ?? 0) + w.start - 1) / ref.total_length) * width} y={top}
                    width={Math.max(((w.end - w.start + 1) / ref.total_length) * width, 0.5)} height={rowH}
                    fill={identityColor(w.identity, low, false, dark)} fillOpacity={0.25 + 0.75 * w.covered}>
                    <title>{`${w.contig}:${fmtInt(w.start)}-${fmtInt(w.end)} · ${fmtPct(w.covered * 100, 0)} · ${fmtNum(w.identity, 2)} %`}</title>
                  </rect>
                ))}
              </g>
            );
          })}
        </svg>
      )}
    </SvgFigure>
  );
}

function Differences({ result, data, annotations }: { result: ComparisonResultRead; data: AlignmentData; annotations: Annotations }) {
  const t = useT();
  const entries = result.summary.dnadiff ?? [];
  const [index, setIndex] = useState(0);
  const [category, setCategory] = useState<string>("all");
  const ids = useMemo(() => new Map(data.genomes.map((g) => [g.label, g.assembly_id])), [data]);
  if (!entries.length) return <p className="text-xs text-muted-foreground">{t("comparative.noDnadiff")}</p>;
  const e = entries[Math.min(index, entries.length - 1)];
  const rows: { on: string; d: Difference }[] = [
    ...e.reference_differences.map((d) => ({ on: e.reference, d })),
    ...e.query_differences.map((d) => ({ on: e.query, d })),
  ].filter((r) => r.d.category && (category === "all" || r.d.category === category));
  const counts = ["inversions", "relocations", "translocations", "inserted_regions", "inserted_region_bases", "breakpoints", "substituted_bases", "indel_bases"];
  return (
    <section className="space-y-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1 text-sm font-semibold">{t("comparative.differencesTitle")}<Explain id="structural_differences" compact /></h3>
          <p className="text-xs text-muted-foreground">{t("comparative.differencesSubtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Select className="h-8 w-auto text-xs" value={index} onChange={(ev) => setIndex(Number(ev.target.value))} aria-label={t("comparative.pair")}>
            {entries.map((x, i) => (
              <option key={i} value={i}>{x.reference} × {x.query}</option>
            ))}
          </Select>
          <Select className="h-8 w-auto text-xs" value={category} onChange={(ev) => setCategory(ev.target.value)} aria-label={t("comparative.category")}>
            {["all", "insertion", "inversion", "relocation", "translocation"].map((c) => (
              <option key={c} value={c}>{t(`comparative.cat.${c}` as TranslationKey)}</option>
            ))}
          </Select>
        </div>
      </div>
      <table className="w-full max-w-xl text-xs">
        <thead className="text-left text-muted-foreground">
          <tr><th className="py-1 font-medium" /><th className="py-1 font-medium">{e.reference}</th><th className="py-1 font-medium">{e.query}</th></tr>
        </thead>
        <tbody className="divide-y">
          {counts.map((k) => (
            <tr key={k}>
              <td className="py-1 text-muted-foreground">{t(`comparative.count.${k}` as TranslationKey)}</td>
              <td className="py-1 tabular-nums">{e.report.reference[k] === undefined ? "—" : fmtInt(e.report.reference[k])}</td>
              <td className="py-1 tabular-nums">{e.report.query[k] === undefined ? "—" : fmtInt(e.report.query[k])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="max-h-80 overflow-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted text-left text-muted-foreground">
            <tr>
              {["locatedOn", "sequence", "type", "reading", "start", "end", "length", ""].map((k) => (
                <th key={k} className="px-2 py-1.5 font-medium">{k ? t(`comparative.col.${k}` as TranslationKey) : ""}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map(({ on, d }, i) => {
              const url = explorerUrl(annotations.get(ids.get(on) ?? ""), d.sequence, Math.min(d.start, d.end), Math.max(d.start, d.end));
              return (
                <tr key={i}>
                  <td className="px-2 py-1">{on}</td>
                  <td className="px-2 py-1 font-mono">{d.sequence}</td>
                  <td className="px-2 py-1 font-mono">{d.type}</td>
                  <td className="px-2 py-1">{t(`comparative.cat.${d.category}` as TranslationKey)}</td>
                  <td className="px-2 py-1 tabular-nums">{fmtInt(d.start)}</td>
                  <td className="px-2 py-1 tabular-nums">{fmtInt(d.end)}</td>
                  <td className="px-2 py-1 tabular-nums">{fmtInt(d.category === "insertion" ? d.inserted : d.length)}</td>
                  <td className="px-2 py-1">
                    {url ? (
                      <Link to={url} className={`inline-flex items-center gap-1 ${LINK}`}>
                        <ExternalLink className="h-3 w-3" /> {t("comparative.openExplorer")}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground" title={t("comparative.noAnnotation")}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-3 text-xs text-muted-foreground">{t("comparative.noDifferences")}</p>}
      </div>
      <p className="text-xs text-muted-foreground">{t("comparative.differencesNote")}</p>
    </section>
  );
}
