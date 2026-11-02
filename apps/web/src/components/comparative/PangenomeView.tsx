import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { AlertTriangle, Download, Map as MapIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { baseOption, useChartTheme } from "@/components/charts/theme";
import { MetricTile } from "@/components/domain/bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonResultRead } from "@/lib/comparative";
import { fmtInt, fmtNum, fmtPct } from "@/lib/format";
import {
  band,
  CATEGORIES,
  type Category,
  filterFamilies,
  fmtP,
  heatmap,
  holders,
  pangenomeOf,
  type PangenomeData,
} from "@/lib/pangenome";
import type { RegionAnchorIn } from "@/lib/regions";

const LINK = "inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan";
const HEATMAP_FAMILIES = 300;
const TABLE_ROWS = 100;

/** A pangenome result: categories with their thresholds, the family-frequency distribution, accumulation curves, the
 * accessory presence/absence heatmap, the family table and explorer, metadata groups and exploratory associations. */
export function PangenomeView({ result, onNeighbourhood, onGeneTree }: {
  result: ComparisonResultRead;
  onNeighbourhood: (anchor: RegionAnchorIn, genomes: string[]) => void;
  onGeneTree?: (family: string) => void;
}) {
  const t = useT();
  const { summary, data } = pangenomeOf(result);
  const [family, setFamily] = useState<number | null>(null);
  const th = summary.thresholds;
  const range: Record<Category, string> = {
    core: `≥ ${fmtPct(th.core * 100, 0)}`,
    soft_core: `${fmtPct(th.soft_core * 100, 0)}–${fmtPct(th.core * 100, 0)}`,
    shell: `${fmtPct(th.shell * 100, 0)}–${fmtPct(th.soft_core * 100, 0)}`,
    cloud: `< ${fmtPct(th.shell * 100, 0)}`,
  };
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-5">
        <MetricTile label={t("pangenome.families")} value={fmtInt(summary.families)} sub={t("comparative.genomeCount", { n: summary.genomes })} explain="pangenome" />
        {CATEGORIES.map((c) => (
          <MetricTile key={c} label={t(`pangenome.category.${c}` as TranslationKey)} value={fmtInt(summary.category_counts[c])}
            sub={t("pangenome.ofGenomes", { range: range[c] })} />
        ))}
      </div>
      {summary.tool_summary && <p className="text-xs text-muted-foreground">{t("pangenome.toolSummary", {
        core: summary.tool_summary.core, soft: summary.tool_summary.soft_core, shell: summary.tool_summary.shell,
        cloud: summary.tool_summary.cloud })}</p>}
      {summary.partitions && <p className="text-xs text-muted-foreground">{t("pangenome.partitions", { ...summary.partitions })}</p>}
      {summary.annotation_consistency && !summary.annotation_consistency.consistent && (
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("pangenome.mixedAnnotation")}</span>
        </p>
      )}
      {data && <Charts result={result} data={data} />}
      <PerGenome rows={summary.per_genome} />
      {data && <Families result={result} data={data} selected={family} onSelect={setFamily} />}
      {data && family !== null && (
        <FamilyPanel resultId={result.id} index={family} onSelect={setFamily} onGeneTree={onGeneTree}
          onNeighbourhood={(anchor) => onNeighbourhood(anchor, data.genomes.map((g) => g.assembly_id))} />
      )}
      {data && <AssociationsPanel result={result} onSelect={setFamily} />}
      <Exports result={result} />
    </div>
  );
}

function Charts({ result, data }: { result: ComparisonResultRead; data: PangenomeData }) {
  const t = useT();
  const theme = useChartTheme();
  const c = data.curves;
  const pan = band(c.pan);
  const core = band(c.core);
  const [panColor, coreColor] = theme.series;
  const curve: EChartsOption = {
    ...baseOption(theme),
    legend: { top: 0, textStyle: { color: theme.muted }, data: [t("pangenome.pan"), t("pangenome.coreStrict")] },
    grid: { left: 64, right: 24, top: 36, bottom: 44 },
    xAxis: { type: "category", data: c.k.map(String), name: t("pangenome.genomesAxis"), nameLocation: "middle", nameGap: 28, axisLabel: { color: theme.muted } },
    yAxis: { type: "value", name: t("pangenome.familiesAxis"), nameLocation: "middle", nameGap: 48, axisLabel: { color: theme.muted } },
    series: [
      { type: "line", stack: "pan", data: pan.low, lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false } },
      { type: "line", stack: "pan", data: pan.height, lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { color: panColor, opacity: 0.15 }, tooltip: { show: false } },
      { type: "line", stack: "core", data: core.low, lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false } },
      { type: "line", stack: "core", data: core.height, lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { color: coreColor, opacity: 0.15 }, tooltip: { show: false } },
      { type: "line", name: t("pangenome.pan"), data: c.pan.mean, itemStyle: { color: panColor }, lineStyle: { width: 2 } },
      { type: "line", name: t("pangenome.coreStrict"), data: c.core.mean, itemStyle: { color: coreColor }, lineStyle: { width: 2 } },
    ],
  };
  const dist: EChartsOption = {
    ...baseOption(theme),
    grid: { left: 64, right: 24, top: 16, bottom: 44 },
    xAxis: { type: "category", data: data.distribution.map((d) => String(d.genomes)), name: t("pangenome.genomesAxis"), nameLocation: "middle", nameGap: 28, axisLabel: { color: theme.muted } },
    yAxis: { type: "value", name: t("pangenome.familiesAxis"), nameLocation: "middle", nameGap: 48, axisLabel: { color: theme.muted } },
    series: [{ type: "bar", data: data.distribution.map((d) => d.families), itemStyle: { color: theme.series[2], borderRadius: [3, 3, 0, 0] } }],
  };
  const hm = heatmap(data, HEATMAP_FAMILIES);
  const heat: EChartsOption = {
    ...baseOption(theme),
    grid: { left: hm.families.length <= 60 ? 140 : 24, right: 16, top: 8, bottom: 110 },
    tooltip: { ...baseOption(theme).tooltip, formatter: (p: unknown) => {
      const d = (p as { data: [number, number, number] }).data;
      return `${hm.families[d[1]]} · ${hm.genomes[d[0]]}<br/>${d[2] ? t("pangenome.present") : t("pangenome.absent")}`;
    } },
    xAxis: { type: "category", data: hm.genomes, axisLabel: { rotate: 40, color: theme.muted, fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "category", data: hm.families, inverse: true, axisLabel: { show: hm.families.length <= 60, color: theme.muted, fontSize: 9 }, axisTick: { show: false } },
    visualMap: { show: false, min: 0, max: 1, inRange: { color: [theme.surface === "#FFFFFF" ? "#F1F5F9" : "#1E2A47", theme.series[0]] } },
    series: [{ type: "heatmap", data: hm.cells, itemStyle: { borderColor: theme.surface, borderWidth: hm.families.length <= 60 ? 1 : 0 } }],
  };
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard title={t("pangenome.curveTitle")} subtitle={t("pangenome.curveSubtitle", { n: c.permutations, seed: c.seed })} explain="pangenome_curves"
        option={curve} filePrefix="arva_pangenome_curves"
        table={{ columns: [t("pangenome.genomesAxis"), t("pangenome.pan"), "SD", t("pangenome.coreStrict"), "SD"],
          rows: c.k.map((k, i) => [k, c.pan.mean[i], c.pan.sd[i], c.core.mean[i], c.core.sd[i]]) }}
        footer={<p>{t("pangenome.curveNote")}</p>} />
      <ChartCard title={t("pangenome.distributionTitle")} subtitle={t("pangenome.distributionSubtitle")} explain="pangenome"
        option={dist} filePrefix="arva_pangenome_distribution"
        table={{ columns: [t("pangenome.genomesAxis"), t("pangenome.familiesAxis")], rows: data.distribution.map((d) => [d.genomes, d.families]) }} />
      <div className="xl:col-span-2">
        <ChartCard title={t("pangenome.heatmapTitle")} subtitle={t("pangenome.heatmapSubtitle", { method: result.tool, version: result.tool_version })}
          explain="pangenome" option={heat} filePrefix="arva_pangenome_heatmap" height={Math.min(640, Math.max(320, 120 + hm.families.length * 6))}
          footer={<>
            <p>{t("pangenome.clusterNote")}</p>
            {hm.hidden > 0 && <p>{t("pangenome.heatmapHidden", { shown: hm.families.length, hidden: hm.hidden })}</p>}
          </>} />
      </div>
    </div>
  );
}

function PerGenome({ rows }: { rows: { label: string; families: number; unique: number }[] }) {
  const t = useT();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50 text-left text-muted-foreground">
          <tr><th className="px-2 py-1.5 font-medium">{t("comparative.member.label")}</th><th className="px-2 py-1.5 font-medium">{t("pangenome.families")}</th>
            <th className="px-2 py-1.5 font-medium">{t("pangenome.unique")}</th></tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.label}><td className="px-2 py-1.5 font-medium">{r.label}</td><td className="px-2 py-1.5 tabular-nums">{fmtInt(r.families)}</td>
              <td className="px-2 py-1.5 tabular-nums">{fmtInt(r.unique)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Families({ result, data, selected, onSelect }: { result: ComparisonResultRead; data: PangenomeData; selected: number | null; onSelect: (i: number) => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "all">("all");
  const rows = useMemo(() => filterFamilies(data.families, query, category), [data, query, category]);
  return (
    <section className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-end gap-3">
        <h3 className="mr-auto text-sm font-semibold">{t("pangenome.familyTable")}</h3>
        <Field label={t("pangenome.search")} className="w-56"><Input value={query} onChange={(e) => setQuery(e.target.value)} /></Field>
        <Field label={t("pangenome.categoryFilter")} className="w-40">
          <Select value={category} onChange={(e) => setCategory(e.target.value as Category | "all")}>
            <option value="all">{t("pangenome.all")}</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{t(`pangenome.category.${c}` as TranslationKey)}</option>)}
          </Select>
        </Field>
      </div>
      <p className="text-xs text-muted-foreground">{t("pangenome.familyCount", { shown: Math.min(rows.length, TABLE_ROWS), total: rows.length })}</p>
      <div className="max-h-96 overflow-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted text-left text-muted-foreground">
            <tr>{["family", "genes", "annotation", "genomes", "category"].map((k) => <th key={k} className="px-2 py-1.5 font-medium">{t(`pangenome.col.${k}` as TranslationKey)}</th>)}</tr>
          </thead>
          <tbody className="divide-y">
            {rows.slice(0, TABLE_ROWS).map((i) => {
              const f = data.families[i];
              return (
                <tr key={f.name} onClick={() => onSelect(i)} className={`cursor-pointer hover:bg-muted/50 ${selected === i ? "bg-arva-teal/10" : ""}`}>
                  <td className="px-2 py-1 font-mono">{f.name}</td>
                  <td className="px-2 py-1">{f.gene_names.join(", ")}</td>
                  <td className="px-2 py-1">{f.annotation}</td>
                  <td className="px-2 py-1 tabular-nums" title={holders(data, f).join(", ")}>{f.count}/{data.genomes.length}</td>
                  <td className="px-2 py-1"><Badge tone={f.category === "core" ? "teal" : f.category === "cloud" ? "neutral" : "blue"}>
                    {t(`pangenome.category.${f.category}` as TranslationKey)}</Badge>{f.partition && <span className="ml-1 text-muted-foreground">{f.partition}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <a href={api.pangenomeFamiliesCsvUrl(result.id)} className={LINK}><Download className="h-3.5 w-3.5" /> {t("pangenome.csvFamilies")}</a>
    </section>
  );
}

function FamilyPanel({ resultId, index, onSelect, onNeighbourhood, onGeneTree }: {
  resultId: string; index: number; onSelect: (i: number) => void; onNeighbourhood: (anchor: RegionAnchorIn) => void;
  onGeneTree?: (family: string) => void;
}) {
  const t = useT();
  const q = useQuery({ queryKey: ["pangenomeFamily", resultId, index], queryFn: () => api.pangenomeFamily(resultId, index) });
  if (q.isLoading) return <Skeleton className="h-40" />;
  if (!q.data) return <ErrorNote error={q.error} />;
  const f = q.data;
  const anchor = f.members.find((m) => m.feature)?.feature;
  return (
    <section className="space-y-3 rounded-lg border border-arva-teal/40 p-3" aria-label={t("pangenome.familyExplorer")}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="mr-auto text-sm font-semibold">{t("pangenome.familyExplorer")}: <span className="font-mono">{f.name}</span>
          <span className="ml-2 font-normal text-muted-foreground">{f.annotation}</span></h3>
        <a href={api.pangenomeFamilyFastaUrl(resultId, index, "nucleotide")} className={LINK}><Download className="h-3.5 w-3.5" /> {t("pangenome.fastaNt")}</a>
        <a href={api.pangenomeFamilyFastaUrl(resultId, index, "protein")} className={LINK}><Download className="h-3.5 w-3.5" /> {t("pangenome.fastaAa")}</a>
        {anchor && (
          <Button size="sm" variant="outline" onClick={() => onNeighbourhood({ annotation_id: anchor.annotation_id, feature_id: anchor.feature_id })}>
            <MapIcon className="h-3.5 w-3.5" /> {t("pangenome.openRegion")}
          </Button>
        )}
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-left text-muted-foreground">
            <tr>{["genome", "gene", "location", "length", "flags"].map((k) => <th key={k} className="px-2 py-1.5 font-medium">{t(`pangenome.member.${k}` as TranslationKey)}</th>)}</tr>
          </thead>
          <tbody className="divide-y">
            {f.members.map((m, i) => (
              <tr key={i}>
                <td className="px-2 py-1 font-medium">{m.genome}</td>
                <td className="px-2 py-1 font-mono">{m.gene_id}{m.feature?.gene ? ` (${m.feature.gene})` : ""}</td>
                <td className="px-2 py-1">{m.feature ? `${m.feature.contig}:${fmtInt(m.feature.start)}–${fmtInt(m.feature.end)} (${m.feature.strand})`
                  : m.refound ? `${m.contig ?? ""}:${fmtInt(m.refound.start)}–${fmtInt(m.refound.end)} (${m.refound.strand}) · ${t("pangenome.refound")}` : "—"}</td>
                <td className="px-2 py-1 tabular-nums">{m.dna_length ? t("pangenome.lengthBp", { n: fmtInt(m.dna_length) }) : "—"}{m.protein_length ? ` · ${t("pangenome.lengthAa", { n: fmtInt(m.protein_length) })}` : ""}</td>
                <td className="px-2 py-1">{m.flags.map((fl) => <Badge key={fl} tone="warning">{t(`pangenome.flag.${fl}` as TranslationKey)}</Badge>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {f.members_total > f.members.length && <p className="text-xs text-muted-foreground">{t("pangenome.membersTruncated", { n: f.members.length, total: f.members_total })}</p>}
      {f.neighbours.length > 0 && (
        <div className="text-xs">
          <p className="font-medium">{t("pangenome.neighbours")}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {f.neighbours.map((nb) => (
              <button key={nb.index} onClick={() => onSelect(nb.index)} className="rounded border px-2 py-0.5 hover:bg-muted" title={nb.annotation}>
                <span className="font-mono">{nb.name}</span> · {t("comparative.genomeCount", { n: nb.genomes })}
              </button>
            ))}
          </div>
          <p className="mt-1 text-muted-foreground">{t("pangenome.neighboursNote")}</p>
        </div>
      )}
      {f.alignment ? (
        <div className="space-y-1 text-xs">
          <p className="font-medium">{t("pangenome.alignmentTitle", { columns: f.alignment.columns })}</p>
          <pre className="max-h-56 overflow-auto rounded bg-muted p-2 font-mono text-[10px] leading-tight">
            {f.alignment.rows.map((r) => `${(r.genome ?? r.name).padEnd(18).slice(0, 18)} ${r.sequence.slice(0, 120)}`).join("\n")}
          </pre>
          <a href={api.comparisonFileUrl(resultId, f.alignment.file)} className={LINK}><Download className="h-3.5 w-3.5" /> {t("pangenome.alignmentFile")}</a>
          {onGeneTree && f.alignment.rows.length >= 3 && (
            <Button size="sm" variant="outline" className="ml-2" onClick={() => onGeneTree(f.name)}>{t("phylo.geneTree")}</Button>
          )}
        </div>
      ) : <p className="text-xs text-muted-foreground">{t("pangenome.noAlignment")}</p>}
    </section>
  );
}

function AssociationsPanel({ result, onSelect }: { result: ComparisonResultRead; onSelect: (i: number) => void }) {
  const t = useT();
  const meta = useQuery({ queryKey: ["pangenomeMeta", result.id], queryFn: () => api.pangenomeMetadata(result.id) });
  const [field, setField] = useState("");
  const [minGroup, setMinGroup] = useState(2);
  const usable = (meta.data?.fields ?? []).filter((f) => f.distinct >= 2);
  const chosen = field || usable[0]?.key || "";
  const assoc = useQuery({ queryKey: ["pangenomeAssoc", result.id, chosen, minGroup], queryFn: () => api.pangenomeAssociations(result.id, chosen, minGroup),
    enabled: Boolean(chosen) });
  const fieldLabel = (k: string) => (k.startsWith("custom:") ? k.slice(7) : t(`pangenome.field.${k}` as TranslationKey));
  return (
    <section className="space-y-3 rounded-lg border p-3">
      <h3 className="text-sm font-semibold">{t("pangenome.associationsTitle")}</h3>
      <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
        <span>{t("pangenome.associationsNote")}</span>
      </p>
      <ErrorNote error={meta.error} />
      {meta.data && usable.length === 0 && <p className="text-xs text-muted-foreground">{t("pangenome.noMetadata")}</p>}
      {usable.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t("pangenome.field")} className="w-56">
            <Select value={chosen} onChange={(e) => setField(e.target.value)}>
              {usable.map((f) => <option key={f.key} value={f.key}>{fieldLabel(f.key)} ({f.recorded}/{meta.data!.genomes.length})</option>)}
            </Select>
          </Field>
          <Field label={t("pangenome.minGroup")} className="w-40">
            <Input type="number" min={1} max={100} value={minGroup} onChange={(e) => setMinGroup(Math.max(1, Number(e.target.value) || 1))} />
          </Field>
        </div>
      )}
      <ErrorNote error={assoc.error} />
      {assoc.data && (
        <div className="space-y-2 text-xs">
          <p className="text-muted-foreground">{t("pangenome.associationsSummary", { withValue: assoc.data.genomes_with_value, without: assoc.data.genomes_without_value,
            families: assoc.data.families_tested, tests: assoc.data.tests })}</p>
          {assoc.data.small_sample && <p className="text-amber-700 dark:text-warning">{t("pangenome.smallSample")}</p>}
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full">
              <thead className="bg-muted/50 text-left text-muted-foreground">
                <tr>{["group", "genomes", "pan", "core", "exclusive", "mean"].map((k) => <th key={k} className="px-2 py-1.5 font-medium">{t(`pangenome.groupCol.${k}` as TranslationKey)}</th>)}</tr>
              </thead>
              <tbody className="divide-y">
                {assoc.data.groups.map((g) => (
                  <tr key={g.group}><td className="px-2 py-1 font-medium">{g.group}</td><td className="px-2 py-1">{g.genomes}</td><td className="px-2 py-1">{fmtInt(g.pan)}</td>
                    <td className="px-2 py-1">{fmtInt(g.core)}</td><td className="px-2 py-1">{fmtInt(g.exclusive)}</td>
                    <td className="px-2 py-1">{fmtNum(g.families_mean, 1)}{g.families_sd !== null ? ` ± ${fmtNum(g.families_sd, 1)}` : ""}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          {assoc.data.rows.length > 0 && (
            <div className="max-h-80 overflow-auto rounded-lg border">
              <table className="w-full">
                <thead className="sticky top-0 bg-muted text-left text-muted-foreground">
                  <tr>{["group", "family", "inGroup", "inOthers", "or", "p", "q"].map((k) => <th key={k} className="px-2 py-1.5 font-medium">{t(`pangenome.assocCol.${k}` as TranslationKey)}</th>)}</tr>
                </thead>
                <tbody className="divide-y">
                  {assoc.data.rows.slice(0, 50).map((r, i) => (
                    <tr key={i} className="cursor-pointer hover:bg-muted/50" onClick={() => onSelect(r.family_index)}>
                      <td className="px-2 py-1">{r.group}</td><td className="px-2 py-1 font-mono">{r.family}</td>
                      <td className="px-2 py-1">{r.in_group}/{r.group_size}{r.share_group_ci ? ` (${fmtPct(r.share_group_ci[0] * 100, 0)}–${fmtPct(r.share_group_ci[1] * 100, 0)})` : ""}</td>
                      <td className="px-2 py-1">{r.in_others}/{r.others_size}{r.share_others_ci ? ` (${fmtPct(r.share_others_ci[0] * 100, 0)}–${fmtPct(r.share_others_ci[1] * 100, 0)})` : ""}</td>
                      <td className="px-2 py-1">{fmtNum(r.odds_ratio, 2)} ({fmtNum(r.odds_ratio_ci[0], 2)}–{fmtNum(r.odds_ratio_ci[1], 2)}){r.haldane_corrected ? "*" : ""}</td>
                      <td className="px-2 py-1 tabular-nums">{fmtP(r.p)}</td><td className="px-2 py-1 tabular-nums">{fmtP(r.q)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-muted-foreground">{t("pangenome.associationsMethod")}</p>
        </div>
      )}
    </section>
  );
}

function Exports({ result }: { result: ComparisonResultRead }) {
  const t = useT();
  const files = Object.keys(result.files).filter((k) => /(gene_presence_absence\.(Rtab|csv)|summary_statistics\.txt|pan_genome_reference\.fa|matrix\.csv|gene_families\.tsv|core_gene_alignment_filtered\.aln)$/.test(k));
  return (
    <div className="flex flex-wrap gap-3">
      <a href={api.pangenomePresenceUrl(result.id)} className={LINK}><Download className="h-3.5 w-3.5" /> {t("pangenome.rtabLabels")}</a>
      {files.map((name) => (
        <a key={name} href={api.comparisonFileUrl(result.id, name)} className={LINK}><Download className="h-3.5 w-3.5" /> {name}</a>
      ))}
    </div>
  );
}
