import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Download } from "lucide-react";
import { useState } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { baseOption, useChartTheme } from "@/components/charts/theme";
import { MetricTile } from "@/components/domain/bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import {
  distributionRows,
  EFFECTS,
  effectImpact,
  histogramLabels,
  linkedPosition,
  mainConsequence,
  VARIANT_TYPES,
  type VariantRecord,
  type VariantRun,
} from "@/lib/variants";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top whitespace-nowrap";
const PAGE = 100;
const IMPACT_TONE = { high: "text-rose-700 dark:text-rose-300", moderate: "text-amber-700 dark:text-warning", low: "text-muted-foreground", none: "text-muted-foreground" };

export const effectText = (t: ReturnType<typeof useT>, e: string | null) =>
  e ? ((EFFECTS as readonly string[]).includes(e) ? t(`variants.effect.${e}` as TranslationKey) : e) : t("variants.effect.none");

/** One variant-calling run: the reference and reads, how much of the reference could be called, the counts, the
 * genomic distribution, depth and alternative-allele fraction at the variable sites, the effects, and the records
 * (filterable, paged) with their downloads. */
export function VariantCard({ run }: { run: VariantRun }) {
  const t = useT();
  const theme = useChartTheme();
  const s = run.summary;
  const contigs = s.distribution.contigs.map((c) => c.contig);
  const [contig, setContig] = useState(contigs[0] ?? "");
  const [status, setStatus] = useState("all");
  const [type, setType] = useState("");
  const [effect, setEffect] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const records = useQuery({
    queryKey: ["variantRecords", run.id, status, type, effect, q, page],
    queryFn: () => api.variantRecords(run.id, { status, type, effect, q, offset: page * PAGE, limit: PAGE }),
    placeholderData: keepPreviousData,
  });
  const rows = distributionRows(s.distribution, contig);
  const distribution: EChartsOption = {
    ...baseOption(theme),
    grid: { left: 56, right: 16, top: 28, bottom: 44 },
    legend: { top: 0, textStyle: { color: theme.muted } },
    xAxis: { type: "category", data: rows.map((r) => fmtInt(r[0])), name: t("variants.positionAxis"), nameLocation: "middle", nameGap: 28, axisLabel: { color: theme.muted } },
    yAxis: { type: "value", name: t("variants.countAxis"), nameLocation: "middle", nameGap: 36, axisLabel: { color: theme.muted } },
    series: [
      { type: "bar", stack: "v", name: t("variants.type.snp"), data: rows.map((r) => r[1]), itemStyle: { color: theme.series[0] } },
      { type: "bar", stack: "v", name: t("variants.otherTypes"), data: rows.map((r) => r[2]), itemStyle: { color: theme.series[3] } },
    ],
  };
  const histogram = (h: typeof s.depth_histogram, digits: number, axis: string): EChartsOption => ({
    ...baseOption(theme),
    grid: { left: 56, right: 16, top: 28, bottom: 44 },
    legend: { top: 0, textStyle: { color: theme.muted } },
    xAxis: { type: "category", data: histogramLabels(h, digits), name: axis, nameLocation: "middle", nameGap: 28, axisLabel: { color: theme.muted, fontSize: 10 } },
    yAxis: { type: "value", name: t("variants.countAxis"), nameLocation: "middle", nameGap: 36, axisLabel: { color: theme.muted } },
    series: [
      { type: "bar", stack: "h", name: t("variants.passing"), data: h.pass, itemStyle: { color: theme.series[0] } },
      { type: "bar", stack: "h", name: t("variants.filtered"), data: h.filtered, itemStyle: { color: theme.series[5] ?? theme.muted } },
    ],
  });
  const effects = Object.entries(s.by_effect).sort((a, b) => b[1] - a[1]);
  const effectOption: EChartsOption = {
    ...baseOption(theme),
    grid: { left: 180, right: 24, top: 8, bottom: 32 },
    xAxis: { type: "value", axisLabel: { color: theme.muted } },
    yAxis: { type: "category", inverse: true, data: effects.map(([e]) => effectText(t, e === "none" ? null : e)), axisLabel: { color: theme.muted } },
    series: [{ type: "bar", data: effects.map(([, n]) => n), itemStyle: { color: theme.series[2], borderRadius: [0, 3, 3, 0] } }],
  };
  const settings = run.parameters.settings;
  const indels = (s.by_type.insertion ?? 0) + (s.by_type.deletion ?? 0);
  return (
    <Card className="min-w-0">
      <CardHeader
        title={t("variants.cardTitle", { reference: run.reference.label, tech: t(`variants.tech.${run.technology}` as TranslationKey) })}
        description={t("variants.cardSub", { aligner: `${run.aligner} ${run.aligner_version}`, caller: run.caller_version, date: fmtDate(run.created_at), sha: run.reference_sha256.slice(0, 12) })}
        action={
          <div className="flex flex-wrap gap-2">
            {(["vcf", "vcf_index", "csq_gff", "bam"] as const).filter((k) => run.files[k]).map((k) => (
              <a key={k} href={api.variantFileUrl(run.id, k)} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-muted">
                <Download className="h-3.5 w-3.5" aria-hidden /> {t(`variants.file.${k}` as TranslationKey)}
              </a>
            ))}
            <a href={api.variantCsvUrl(run.id)} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-muted">
              <Download className="h-3.5 w-3.5" aria-hidden /> {t("variants.file.csv")}
            </a>
          </div>
        }
      />
      <CardBody className="space-y-4 pt-3">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <MetricTile label={t("variants.tile.pass")} value={fmtInt(s.pass)} sub={t("variants.tile.records", { n: fmtInt(s.records) })} explain="variant_filters" />
          <MetricTile label={t("variants.tile.snps")} value={fmtInt(s.by_type.snp ?? 0)} />
          <MetricTile label={t("variants.tile.indels")} value={fmtInt(indels)} sub={settings.call_indels ? undefined : t("variants.indelsOff")} />
          <MetricTile label={t("variants.tile.callable")} value={fmtPct(s.callable_percent)} sub={t("variants.tile.callableSub", { depth: settings.min_depth, bases: fmtBases(s.callable_bases) })} />
          <MetricTile label={t("variants.tile.mapped")} value={s.alignment.mapped_percent == null ? "—" : fmtPct(s.alignment.mapped_percent)} sub={t("variants.tile.reads", { n: fmtInt(s.alignment.reads) })} />
          <MetricTile label={t("variants.tile.depth")} value={s.coverage.length ? `${fmtNum(s.coverage.reduce((a, c) => a + c.mean_depth * c.length, 0) / Math.max(1, s.coverage.reduce((a, c) => a + c.length, 0)), 1)}×` : "—"} />
        </div>
        <p className="text-xs text-muted-foreground">
          {t("variants.reads")}: {run.reads.map((r) => `${t(`variants.role.${r.role}` as TranslationKey)} ${r.name}`).join(" · ")} ·{" "}
          {t("variants.settingsLine", { qual: settings.min_qual, depth: settings.min_depth, af: settings.min_alt_fraction, mapq: settings.min_mapq, baseq: settings.min_baseq ?? "?" })}
        </p>
        {run.warnings.map((w) => (
          <p key={w.code} className="text-xs text-amber-700 dark:text-warning">{t(`variants.warning.${w.code}` as TranslationKey, { count: 0, ...w.params })}</p>
        ))}
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="xl:col-span-2">
            <ChartCard title={t("variants.distributionTitle")} subtitle={t("variants.distributionSub", { bin: fmtBases(s.distribution.bin) })} explain="variant_calling"
              option={distribution} filePrefix="arva_variant_distribution"
              controls={contigs.length > 1 ? (
                <Select value={contig} onChange={(e) => setContig(e.target.value)} aria-label={t("variants.contig")} className="h-8 w-48 text-xs">
                  {contigs.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              ) : undefined}
              table={{ columns: [t("variants.positionAxis"), t("variants.type.snp"), t("variants.otherTypes")], rows }} />
          </div>
          <ChartCard title={t("variants.depthTitle")} subtitle={t("variants.depthSub")} explain="variant_filters" option={histogram(s.depth_histogram, 0, t("variants.depthAxis"))}
            filePrefix="arva_variant_depth" table={{ columns: [t("variants.depthAxis"), t("variants.passing"), t("variants.filtered")], rows: histogramLabels(s.depth_histogram).map((l, i) => [l, s.depth_histogram.pass[i], s.depth_histogram.filtered[i]]) }} />
          <ChartCard title={t("variants.afTitle")} subtitle={t("variants.afSub")} explain="variant_filters" option={histogram(s.alt_fraction_histogram, 2, t("variants.afAxis"))}
            filePrefix="arva_variant_alt_fraction" table={{ columns: [t("variants.afAxis"), t("variants.passing"), t("variants.filtered")], rows: histogramLabels(s.alt_fraction_histogram, 2).map((l, i) => [l, s.alt_fraction_histogram.pass[i], s.alt_fraction_histogram.filtered[i]]) }} />
          {run.parameters.effects && effects.length > 0 && (
            <div className="xl:col-span-2">
              <ChartCard title={t("variants.effectsTitle")} subtitle={t("variants.effectsSub")} explain="variant_effects" option={effectOption} height={Math.max(160, 40 + effects.length * 26)}
                filePrefix="arva_variant_effects" table={{ columns: [t("variants.col.effect"), t("variants.countAxis")], rows: effects.map(([e, n]) => [effectText(t, e === "none" ? null : e), n]) }}
                footer={<>
                  <p>{t("variants.effectsNote")}</p>
                  {(s.after_stop ?? 0) > 0 && <p>{t("variants.afterStopNote", { n: fmtInt(s.after_stop ?? 0) })}</p>}
                </>} />
            </div>
          )}
        </div>
        <section className="space-y-2" aria-label={t("variants.tableTitle")}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <h4 className="mr-2 text-sm font-semibold">{t("variants.tableTitle")}</h4>
            <Select className="h-8 w-36 text-xs" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} aria-label={t("variants.status")}>
              {["all", "pass", "filtered"].map((x) => <option key={x} value={x}>{t(`variants.statusOpt.${x}` as TranslationKey)}</option>)}
            </Select>
            <Select className="h-8 w-36 text-xs" value={type} onChange={(e) => { setType(e.target.value); setPage(0); }} aria-label={t("variants.col.type")}>
              <option value="">{t("variants.anyType")}</option>
              {VARIANT_TYPES.map((x) => <option key={x} value={x}>{t(`variants.type.${x}` as TranslationKey)}</option>)}
            </Select>
            {run.parameters.effects && (
              <Select className="h-8 w-44 text-xs" value={effect} onChange={(e) => { setEffect(e.target.value); setPage(0); }} aria-label={t("variants.col.effect")}>
                <option value="">{t("variants.anyEffect")}</option>
                {effects.map(([e]) => <option key={e} value={e}>{effectText(t, e === "none" ? null : e)}</option>)}
              </Select>
            )}
            <Input className="h-8 w-44 text-xs" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder={t("variants.searchGene")} aria-label={t("variants.searchGene")} />
          </div>
          <ErrorNote error={records.error} />
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-xs">
              <thead className="bg-muted/50">
                <tr>
                  {["contig", "pos", "change", "type", "qual", "depth", "af", "filter", "effect", "gene", "aa"].map((c) => <th key={c} className={TH}>{t(`variants.col.${c}` as TranslationKey)}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y">
                {(records.data?.variants ?? []).map((v) => <VariantRow key={`${v.contig}:${v.pos}:${v.ref}:${v.alt}`} v={v} />)}
              </tbody>
            </table>
          </div>
          {records.data && records.data.total > PAGE && (
            <div className="flex items-center justify-end gap-2 text-xs">
              <span className="text-muted-foreground">{t("variants.page", { from: fmtInt(page * PAGE + 1), to: fmtInt(Math.min(records.data.total, (page + 1) * PAGE)), total: fmtInt(records.data.total) })}</span>
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>{t("variants.prev")}</Button>
              <Button variant="outline" size="sm" disabled={(page + 1) * PAGE >= records.data.total} onClick={() => setPage(page + 1)}>{t("variants.next")}</Button>
            </div>
          )}
          {records.data?.total === 0 && <p className="text-xs text-muted-foreground">{t("variants.noneMatch")}</p>}
        </section>
      </CardBody>
    </Card>
  );
}

function VariantRow({ v }: { v: VariantRecord }) {
  const t = useT();
  const c = mainConsequence(v);
  const linked = linkedPosition(v);
  const change = `${v.ref.length > 12 ? `${v.ref.slice(0, 12)}…` : v.ref} → ${v.alt.length > 12 ? `${v.alt.slice(0, 12)}…` : v.alt}`;
  return (
    <tr className={v.pass ? "" : "opacity-70"}>
      <td className={TD}>{v.contig}</td>
      <td className={`${TD} tabular-nums`}>{fmtInt(v.pos)}</td>
      <td className={`${TD} font-mono`}>{change}</td>
      <td className={TD}>{t(`variants.type.${v.type}` as TranslationKey)}</td>
      <td className={`${TD} tabular-nums`}>{v.qual == null ? "—" : fmtNum(v.qual, 1)}</td>
      <td className={`${TD} tabular-nums`}>{v.depth ?? "—"}{v.alt_reads != null ? ` (${v.ref_reads ?? 0}/${v.alt_reads})` : ""}</td>
      <td className={`${TD} tabular-nums`}>{v.alt_fraction == null ? "—" : fmtNum(v.alt_fraction, 2)}</td>
      <td className="max-w-[11rem] px-2 py-1.5 align-top"><span className="flex flex-wrap gap-1">{v.pass ? <Badge tone="success">{t("variants.passBadge")}</Badge> : v.filters.map((f) => <Badge key={f} tone="warning">{f}</Badge>)}</span></td>
      <td className={`${TD} ${IMPACT_TONE[effectImpact(v.effect)]}`}>
        {effectText(t, v.effect)}
        {v.start_codon && <span className="block text-[10px] text-amber-700 dark:text-warning">{t("variants.startCodon", { codon: v.start_codon })}</span>}
        {v.after_stop && <span className="block text-[10px] text-muted-foreground">{t("variants.afterStop")}</span>}
        {linked != null && <span className="block text-[10px] text-muted-foreground">{t("variants.linked", { pos: fmtInt(linked) })}</span>}
      </td>
      <td className={TD}>{c?.gene ?? ""}</td>
      <td className={`${TD} font-mono`}>{c?.aa_change ?? ""}</td>
    </tr>
  );
}
