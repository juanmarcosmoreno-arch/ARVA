import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { AlertTriangle, Download, Telescope } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChartCard } from "@/components/charts/ChartCard";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt, fmtMax, fmtPct } from "@/lib/format";
import {
  DISCOVER_ANALYSES,
  FEATURE_SOURCES,
  discoverCsvUrl,
  fmtP,
  network,
  orderedMatrix,
  platformApi,
  withCi,
  type AssociationsResult,
  type CooccurrenceResult,
  type DiscoverBase,
  type DiscoverQuery,
  type DiscoverSummary,
  type HeatmapResult,
  type LineageResult,
  type PcaResult,
} from "@/lib/platform";

const LINK = "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium hover:bg-muted";
const TH = "px-2 py-1.5 text-left text-[11px] font-medium text-muted-foreground";
const TD = "px-2 py-1 align-top tabular-nums";

export function DiscoverPage() {
  const { projectId } = useParams();
  const t = useT();
  const navigate = useNavigate();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  return (
    <div className="animate-fade-in space-y-5">
      <PageHeader title={t("discover.title")} subtitle={t("discover.subtitle")} actions={<Explain id="discover_stats" />} />
      <Card>
        <CardBody className="flex flex-wrap items-end gap-4 pt-5">
          <Field label={t("discover.project")} className="w-80">
            <Select value={projectId ?? ""} onChange={(e) => navigate(e.target.value ? `/discover/${e.target.value}` : "/discover")}>
              <option value="">{t("discover.chooseProject")}</option>
              {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </Field>
          {projectId && <Link className={LINK} to={`/projects/${projectId}`}>{t("discover.openProject")}</Link>}
        </CardBody>
      </Card>
      {projectId ? <ProjectDiscover projectId={projectId} /> : (
        <EmptyState icon={<Telescope className="h-7 w-7" />} title={t("discover.noProject")} />
      )}
    </div>
  );
}

function Caveats({ codes, label }: { codes: string[]; label: string }) {
  const t = useT();
  return (
    <div className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
      <div className="mb-1 flex items-center gap-2 font-medium">
        <AlertTriangle className="h-4 w-4 text-warning" />
        {label === "exploratory, not confirmatory" ? t("discover.exploratory") : label}
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
        {codes.map((c) => <li key={c}>{t(`discover.caveat.${c}` as TranslationKey)}</li>)}
      </ul>
    </div>
  );
}

function ProjectDiscover({ projectId }: { projectId: string }) {
  const t = useT();
  const summary = useQuery({ queryKey: ["discoverSummary", projectId], queryFn: () => platformApi.discoverSummary(projectId) });
  const [q, setQ] = useState<DiscoverQuery>({ analysis: "associations", sources: ["amr"], one_hot: [], group: "host",
    lineage: "st", min_group: 2, min_with: 1, alpha: 0.05 });
  const result = useQuery({
    queryKey: ["discover", projectId, q],
    queryFn: () => platformApi.discover<DiscoverBase>(projectId, q),
    enabled: !!summary.data,
  });
  if (summary.isLoading) return <Skeleton className="h-40" />;
  if (summary.error || !summary.data) return <ErrorNote error={summary.error} />;
  const s = summary.data;
  const fields = s.fields.filter((f) => f.known > 0);
  const set = (patch: Partial<DiscoverQuery>) => setQ((old) => ({ ...old, ...patch }));
  const toggle = <K extends "sources" | "one_hot">(key: K, value: string) =>
    set({ [key]: q[key].includes(value as never) ? q[key].filter((v) => v !== value) : [...q[key], value] } as Partial<DiscoverQuery>);

  return (
    <>
      <Caveats codes={s.caveats} label={s.label} />
      <Card>
        <CardHeader title={t("discover.data")} description={t("discover.dataHint", { samples: s.samples })} />
        <CardBody className="grid gap-4 text-xs lg:grid-cols-3">
          <div>
            <div className="mb-1 font-medium">{t("discover.sources")}</div>
            {FEATURE_SOURCES.map((src) => {
              const p = s.provenance[src];
              return (
                <div key={src} className="mb-1">
                  {t(`discover.source.${src}` as TranslationKey)}: {t("discover.searched", { n: p?.searched ?? 0, total: s.samples })}
                  {!!p?.versions.length && <div className="text-muted-foreground">{p.versions.join("; ")}</div>}
                </div>
              );
            })}
          </div>
          <div>
            <div className="mb-1 font-medium">{t("discover.fields")}</div>
            <div className="flex flex-wrap gap-1">
              {fields.map((f) => <Badge key={f.name} tone="blue">{fieldLabel(t, f.name)} · {f.known}/{s.samples}</Badge>)}
              {!fields.length && <span className="text-muted-foreground">{t("discover.noFields")}</span>}
            </div>
          </div>
          <div>
            <div className="mb-1 font-medium">{t("discover.features")}</div>
            <p className="text-muted-foreground">{t("discover.featureCount", { n: s.features.length })}</p>
            {!!s.mixed_assemblies.length && (
              <p className="mt-2 text-warning">{t("discover.mixed", { samples: s.mixed_assemblies.join(", ") })}</p>
            )}
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("discover.analysis")} />
        <CardBody className="grid gap-4 md:grid-cols-4">
          <Field label={t("discover.analysis")}>
            <Select value={q.analysis} onChange={(e) => set({ analysis: e.target.value as DiscoverQuery["analysis"] })}>
              {DISCOVER_ANALYSES.map((a) => <option key={a} value={a}>{t(`discover.a.${a}` as TranslationKey)}</option>)}
            </Select>
          </Field>
          <Field label={t("discover.group")} hint={t("discover.groupHint")}>
            <Select value={q.group ?? ""} onChange={(e) => set({ group: e.target.value || undefined })}>
              <option value="">—</option>
              {fields.map((f) => <option key={f.name} value={f.name}>{fieldLabel(t, f.name)}</option>)}
            </Select>
          </Field>
          <Field label={t("discover.lineage")} hint={t("discover.lineageHint")}>
            <Select value={q.lineage ?? ""} onChange={(e) => set({ lineage: e.target.value || undefined })}>
              <option value="">{t("discover.noLineage")}</option>
              {fields.map((f) => <option key={f.name} value={f.name}>{fieldLabel(t, f.name)}</option>)}
            </Select>
          </Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label={t("discover.minGroup")}>
              <Input type="number" min={1} value={q.min_group} onChange={(e) => set({ min_group: Math.max(1, Number(e.target.value) || 1) })} />
            </Field>
            <Field label={t("discover.minWith")}>
              <Input type="number" min={1} value={q.min_with} onChange={(e) => set({ min_with: Math.max(1, Number(e.target.value) || 1) })} />
            </Field>
            <Field label={t("discover.alpha")}>
              <Input type="number" step="0.01" min={0.001} max={0.5} value={q.alpha}
                onChange={(e) => set({ alpha: Math.min(0.5, Math.max(0.001, Number(e.target.value) || 0.05)) })} />
            </Field>
          </div>
          <div className="md:col-span-4 flex flex-wrap gap-4 text-xs">
            {FEATURE_SOURCES.map((src) => (
              <label key={src} className="flex items-center gap-1.5">
                <input type="checkbox" className="accent-[#00B4A6]" checked={q.sources.includes(src)} onChange={() => toggle("sources", src)} />
                {t(`discover.source.${src}` as TranslationKey)}
              </label>
            ))}
            <span className="text-muted-foreground">{t("discover.oneHot")}</span>
            {fields.map((f) => (
              <label key={f.name} className="flex items-center gap-1.5">
                <input type="checkbox" className="accent-[#00B4A6]" checked={q.one_hot.includes(f.name)} onChange={() => toggle("one_hot", f.name)} />
                {fieldLabel(t, f.name)}
              </label>
            ))}
          </div>
        </CardBody>
      </Card>
      {result.isLoading ? <Skeleton className="h-60" /> : result.error ? <ErrorNote error={result.error} /> : result.data && (
        <Result projectId={projectId} q={q} r={result.data} summary={s} />
      )}
    </>
  );
}

function fieldLabel(t: ReturnType<typeof useT>, name: string) {
  return name.startsWith("meta:") ? name.slice(5) : t(`discover.field.${name}` as TranslationKey);
}

// The API's method texts are English; the interface shows its own translation of each (same content).
const METHOD_TEXT: Record<DiscoverQuery["analysis"], TranslationKey> = {
  associations: "discover.method.associations",
  cooccurrence: "discover.method.cooccurrence",
  lineage: "discover.method.lineage",
  heatmap: "discover.method.heatmap",
  pca: "discover.method.pca",
};

function Result({ projectId, q, r, summary }: { projectId: string; q: DiscoverQuery; r: DiscoverBase; summary: DiscoverSummary }) {
  const t = useT();
  const csv = q.analysis === "associations" || q.analysis === "cooccurrence";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <Badge tone="warning">{t("discover.exploratory")}</Badge>
        <span>{t("discover.used", { features: r.features_used, samples: r.samples_total })}</span>
        {csv && <a className={LINK} href={discoverCsvUrl(projectId, q)}><Download className="h-3.5 w-3.5" />{t("discover.csv")}</a>}
      </div>
      {r.method && <p className="max-w-5xl text-[11px] text-muted-foreground">{t(METHOD_TEXT[q.analysis])}</p>}
      {q.analysis === "associations" && <AssociationsView r={r as AssociationsResult} />}
      {q.analysis === "cooccurrence" && <NetworkView r={r as CooccurrenceResult} />}
      {q.analysis === "lineage" && <LineageView r={r as LineageResult} />}
      {q.analysis === "heatmap" && <HeatmapView r={r as HeatmapResult} />}
      {q.analysis === "pca" && <PcaView r={r as PcaResult} />}
      {summary.samples < 10 && <p className="text-xs text-warning">{t("discover.smallSample", { n: summary.samples })}</p>}
    </div>
  );
}

function StratCell({ s }: { s: AssociationsResult["rows"][number]["stratified"] | undefined }) {
  const t = useT();
  if (!s) return <>–</>;
  if (!s.informative_strata) return <span className="text-warning">{t("discover.confounded")}</span>;
  // One value per line, each kept whole: the cell's four values otherwise wrap mid-value in a narrow column.
  return (
    <span className="flex min-w-[11rem] flex-col">
      <span className="whitespace-nowrap">{t("discover.stratLineages", { n: s.informative_strata })}</span>
      <span className="whitespace-nowrap">p {fmtP(s.p)} · q {fmtP(s.q)}</span>
      <span className="whitespace-nowrap">{t("discover.stratOr", { or: withCi(s.odds_ratio, s.odds_ratio_ci) })}</span>
    </span>
  );
}

function AssociationsView({ r }: { r: AssociationsResult }) {
  const t = useT();
  const [onlySig, setOnlySig] = useState(false);
  const rows = (onlySig ? r.rows.filter((x) => x.q <= 0.05) : r.rows).slice(0, 300);
  return (
    <Card>
      <CardHeader title={t("discover.a.associations")} description={t("discover.assocHint", {
        tests: r.tests, withValue: r.samples_with_value, without: r.samples_without_value })}
        action={<Explain id="discover_stats" />} />
      <CardBody className="space-y-2 text-xs">
        {r.skipped_groups.filter((g) => !g.mirror_of).length > 0 && (
          <p className="text-muted-foreground">{t("discover.skipped", { groups: r.skipped_groups.filter((g) => !g.mirror_of).map((g) => `${g.group} (${g.samples})`).join(", ") })}</p>
        )}
        {r.skipped_groups.filter((g) => g.mirror_of).map((g) => (
          <p key={g.group} className="text-muted-foreground">{t("discover.mirror", { group: g.group, other: g.mirror_of ?? "" })}</p>
        ))}
        <label className="flex items-center gap-1.5">
          <input type="checkbox" className="accent-[#00B4A6]" checked={onlySig} onChange={(e) => setOnlySig(e.target.checked)} />
          {t("discover.onlyQ")}
        </label>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr>
              {(["group", "feature", "n", "shareIn", "shareOut", "diff", "or", "p", "q", "stratified"] as const).map((k) => (
                <th key={k} className={TH}>{t(`discover.col.${k}` as TranslationKey)}</th>))}
            </tr></thead>
            <tbody>
              {rows.map((x) => (
                <tr key={`${x.group}|${x.feature}`} className="border-t">
                  <td className={TD}>{x.group}</td>
                  <td className={TD}>{x.feature}</td>
                  <td className={TD}>{fmtInt(x.samples)}</td>
                  <td className={TD}>{x.table[0]}/{x.table[0] + x.table[1]} · {withCi(x.share_1, x.share_1_ci)}</td>
                  <td className={TD}>{x.table[2]}/{x.table[2] + x.table[3]} · {withCi(x.share_2, x.share_2_ci)}</td>
                  <td className={TD}>{withCi(x.difference, x.difference_ci)}</td>
                  <td className={TD}>{withCi(x.odds_ratio, x.odds_ratio_ci)}{x.haldane_corrected ? " *" : ""}</td>
                  <td className={TD}>{fmtP(x.p)}</td>
                  <td className={TD}>{fmtP(x.q)}</td>
                  <td className={TD}><StratCell s={x.stratified} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-muted-foreground">{t("discover.haldane")}</p>
        {r.rows.length > 300 && <p className="text-muted-foreground">{t("discover.firstRows", { n: 300, total: r.rows.length })}</p>}
      </CardBody>
    </Card>
  );
}

function NetworkView({ r }: { r: CooccurrenceResult }) {
  const t = useT();
  const net = useMemo(() => network(r), [r]);
  const option: EChartsOption = {
    tooltip: {},
    series: [{
      type: "graph", layout: "force", roam: true, draggable: true, force: { repulsion: 120, edgeLength: 80 },
      label: { show: true, fontSize: 10 },
      data: net.nodes.map((n) => ({ ...n, symbolSize: 8 + 3 * n.value })),
      links: net.edges.map((e) => ({ source: e.source, target: e.target,
        lineStyle: { color: e.positive ? "#0072B2" : "#D55E00", type: e.positive ? "solid" : "dashed", width: 1.5 } })),
    }],
  };
  const top = r.rows.slice(0, 50);
  return (
    <>
      {r.edges > 0 ? (
        <ChartCard title={t("discover.network")} subtitle={t("discover.networkHint", { edges: r.edges, pairs: r.pairs_tested, alpha: fmtMax(r.alpha, 3) })}
          explain="discover_stats" option={option} height={420} filePrefix="arva_discover" />
      ) : (
        <p className="text-sm text-muted-foreground">{t("discover.noEdges")} {t("discover.networkHint", { edges: 0, pairs: r.pairs_tested, alpha: fmtMax(r.alpha, 3) })}</p>
      )}
      <Card>
        <CardHeader title={t("discover.topPairs", { n: top.length, total: r.rows.length })} />
        <CardBody className="overflow-x-auto text-xs">
          <table className="w-full">
            <thead><tr>
              {(["f1", "f2", "n", "phi", "or", "p", "q", "stratified"] as const).map((k) => <th key={k} className={TH}>{t(`discover.col.${k}` as TranslationKey)}</th>)}
            </tr></thead>
            <tbody>
              {top.map((x) => (
                <tr key={`${x.feature_1}|${x.feature_2}`} className="border-t">
                  <td className={TD}>{x.feature_1}</td><td className={TD}>{x.feature_2}</td><td className={TD}>{x.samples}</td>
                  <td className={TD}>{x.phi === null ? "–" : fmtMax(x.phi, 2)}</td>
                  <td className={TD}>{withCi(x.odds_ratio, x.odds_ratio_ci)}{x.haldane_corrected ? " *" : ""}</td>
                  <td className={TD}>{fmtP(x.p)}</td><td className={TD}>{fmtP(x.q)}</td>
                  <td className={TD}><StratCell s={x.stratified} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </>
  );
}

function LineageView({ r }: { r: LineageResult }) {
  const t = useT();
  const features = Object.keys(r.lineages[0]?.features ?? {});
  return (
    <Card>
      <CardHeader title={t("discover.a.lineage")} description={t("discover.lineageResultHint", { unknown: r.unknown_lineage })} />
      <CardBody className="overflow-x-auto text-xs">
        <table className="w-full">
          <thead><tr><th className={TH}>{t("discover.lineage")}</th><th className={TH}>{t("discover.col.n")}</th>
            {features.map((f) => <th key={f} className={TH}>{f}</th>)}</tr></thead>
          <tbody>
            {r.lineages.map((l) => (
              <tr key={l.lineage} className="border-t">
                <td className={TD}>{l.lineage}</td><td className={TD}>{l.samples}</td>
                {features.map((f) => {
                  const c = l.features[f];
                  return <td key={f} className={TD} title={c.ci ? `${fmtPct(c.ci[0] * 100, 0)}–${fmtPct(c.ci[1] * 100, 0)}` : ""}>
                    {c.searched ? `${c.with}/${c.searched}` : "–"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

function HeatmapView({ r }: { r: HeatmapResult }) {
  const t = useT();
  const m = useMemo(() => orderedMatrix(r), [r]);
  const labels = m.samples.map((id) => r.sample_codes[id] ?? id);
  const option: EChartsOption = {
    tooltip: { formatter: (p: unknown) => { const d = (p as { data: number[] }).data; return `${labels[d[1]]} · ${m.features[d[0]]}`; } },
    grid: { left: 130, right: 20, top: 10, bottom: 120 },
    xAxis: { type: "category", data: m.features, axisLabel: { rotate: 60, fontSize: 9 } },
    yAxis: { type: "category", data: labels, axisLabel: { fontSize: 10 } },
    visualMap: { show: false, min: 0, max: 1, inRange: { color: ["#EEF2F7", "#0072B2"] } },
    series: [{ type: "heatmap", data: m.cells }],
  };
  return (
    <>
      <ChartCard title={t("discover.a.heatmap")} subtitle={t("discover.heatmapHint")} explain="discover_stats" option={option}
        height={Math.max(260, 22 * labels.length + 140)} filePrefix="arva_discover" />
      {!!r.excluded_samples.length && <p className="text-xs text-muted-foreground">{t("discover.excluded", { n: r.excluded_samples.length })}</p>}
    </>
  );
}

function PcaView({ r }: { r: PcaResult }) {
  const t = useT();
  if (!r.applicable) {
    return <p className="text-sm text-warning">{t(`discover.pca.${r.reason ?? "too_few_samples"}` as TranslationKey, { n: r.minimum ?? 0 })}</p>;
  }
  const ev = r.explained_variance_ratio ?? [];
  const option: EChartsOption = {
    tooltip: { formatter: (p: unknown) => (p as { data: [number, number, string] }).data[2] },
    xAxis: { name: t("discover.pc", { n: 1, pct: fmtPct((ev[0] ?? 0) * 100) }), nameLocation: "middle", nameGap: 26 },
    yAxis: { name: t("discover.pc", { n: 2, pct: fmtPct((ev[1] ?? 0) * 100) }), nameLocation: "middle", nameGap: 36 },
    series: [{ type: "scatter", symbolSize: 10, label: { show: true, position: "right", fontSize: 10, formatter: (p) => (p.data as [number, number, string])[2] },
      data: (r.scores ?? []).map((s, i) => [s[0], s[1] ?? 0, r.sample_codes[r.samples[i]] ?? r.samples[i]]) }],
  };
  return (
    <ChartCard title={t("discover.a.pca")} subtitle={t("discover.pcaHint")} explain="discover_stats" option={option} height={380}
      filePrefix="arva_discover"
      footer={<span>{t("discover.loadings")}: {(r.top_loadings?.[0] ?? []).slice(0, 5).map((l) => `${l.feature} (${fmtMax(l.loading, 2)})`).join(", ")}</span>} />
  );
}
