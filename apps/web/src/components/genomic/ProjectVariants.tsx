import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ChartCard } from "@/components/charts/ChartCard";
import { baseOption, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt, fmtPct } from "@/lib/format";
import { displayOrder, type SnpMatrix } from "@/lib/variants";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

function DistanceHeatmap({ m }: { m: SnpMatrix }) {
  const t = useT();
  const theme = useChartTheme();
  const order = displayOrder(m.distances);
  const labels = order.map((i) => m.samples[i].label);
  const cells: [number, number, number][] = [];
  order.forEach((i, x) => order.forEach((j, y) => cells.push([x, y, m.distances[i][j]])));
  const max = Math.max(1, ...cells.map((c) => c[2]));
  const option: EChartsOption = {
    ...baseOption(theme),
    grid: { left: 110, right: 24, top: 8, bottom: 90 },
    tooltip: { ...baseOption(theme).tooltip, formatter: (p: unknown) => {
      const [x, y, d] = (p as { data: [number, number, number] }).data;
      return `${labels[x]} · ${labels[y]}<br/>${t("variants.matrix.cell", { d: fmtInt(d), n: fmtInt(m.compared_sites[order[x]][order[y]]) })}`;
    } },
    xAxis: { type: "category", data: labels, axisLabel: { rotate: 40, color: theme.muted, fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "category", data: labels, inverse: true, axisLabel: { color: theme.muted, fontSize: 10 }, axisTick: { show: false } },
    visualMap: { min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, textStyle: { color: theme.muted },
      inRange: { color: [theme.series[0], theme.surface === "#FFFFFF" ? "#F1F5F9" : "#1E2A47"] } },
    series: [{ type: "heatmap", data: cells, label: { show: labels.length <= 12, color: theme.text, fontSize: 10, formatter: (p: unknown) => fmtInt((p as { data: [number, number, number] }).data[2]) }, itemStyle: { borderColor: theme.surface, borderWidth: 1 } }],
  };
  return (
    <ChartCard title={t("variants.matrix.title")} subtitle={t("variants.matrix.sub", { sites: fmtInt(m.sites.length), core: fmtInt(m.core_sites) })} explain="snp_distance"
      option={option} filePrefix="arva_snp_distances" height={Math.min(640, Math.max(300, 140 + labels.length * 28))}
      table={{ columns: ["", ...labels], rows: order.map((i) => [m.samples[i].label, ...order.map((j) => m.distances[i][j])]) }}
      footer={<>
        <p>{t("variants.matrix.note")}</p>
        {!m.same_settings && <p className="text-amber-700 dark:text-warning">{t("variants.matrix.mixedSettings")}</p>}
      </>} />
  );
}

/** Per reference, the most recent variant-calling run of each sample of the project with its counts, and with two
 * samples or more the SNP matrix: pairwise SNP distances (heatmap), the sites and their downloads. */
export function ProjectVariants({ projectId }: { projectId: string }) {
  const t = useT();
  const overview = useQuery({ queryKey: ["projectVariants", projectId], queryFn: () => api.projectVariants(projectId) });
  const refs = overview.data?.references ?? [];
  const [chosen, setChosen] = useState("");
  const group = refs.find((g) => g.reference_sha256 === chosen) ?? refs[0];
  const matrix = useQuery({
    queryKey: ["snpMatrix", projectId, group?.reference_sha256],
    queryFn: () => api.snpMatrix(projectId, group!.reference_sha256),
    enabled: Boolean(group && group.runs.length >= 2),
  });
  if (overview.error) return <ErrorNote error={overview.error} />;
  if (!group) return null;
  return (
    <Card className="mt-6 min-w-0" id="project-variants">
      <CardHeader title={t("variants.projectTitle")} description={t("variants.projectSub")}
        action={
          <div className="flex items-center gap-2">
            <Explain id="snp_distance" compact />
            <a href={api.variantReportUrl(projectId)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-muted">
              <FileText className="h-3.5 w-3.5" aria-hidden /> {t("variants.report")}
            </a>
          </div>
        } />
      <CardBody className="space-y-4 pt-3">
        {refs.length > 1 && (
          <Select value={group.reference_sha256} onChange={(e) => setChosen(e.target.value)} aria-label={t("variants.reference")} className="max-w-xl">
            {refs.map((g) => <option key={g.reference_sha256} value={g.reference_sha256}>{g.reference.label} · {t("variants.samplesN", { n: g.runs.length })}</option>)}
          </Select>
        )}
        <p className="text-xs text-muted-foreground">{t("variants.referenceLine", { label: group.reference.label, kind: t(`variants.refKind.${group.reference.kind}` as TranslationKey), sha: group.reference_sha256.slice(0, 16) })}</p>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                {["sample", "tech", "mapped", "callable", "records", "pass", "snps"].map((c) => <th key={c} className={TH}>{t(`variants.pcol.${c}` as TranslationKey)}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y">
              {group.runs.map((r) => (
                <tr key={r.id}>
                  <td className={TD}><Link to={`/samples/${r.sample_id}?tab=genomic`} className="font-medium text-arva-royal hover:underline dark:text-arva-cyan">{r.sample_code}</Link></td>
                  <td className={TD}>{t(`variants.tech.${r.technology}` as TranslationKey)}</td>
                  <td className={TD}>{r.mapped_percent == null ? "—" : fmtPct(r.mapped_percent)}</td>
                  <td className={TD}>{r.callable_percent == null ? "—" : fmtPct(r.callable_percent)}</td>
                  <td className={TD}>{fmtInt(r.records)}</td>
                  <td className={TD}>{fmtInt(r.pass)}</td>
                  <td className={TD}>{fmtInt(r.by_type?.snp ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {group.runs.length < 2 && <p className="text-xs text-muted-foreground">{t("variants.matrix.needTwo")}</p>}
        <ErrorNote error={matrix.error} />
        {matrix.data && (
          <>
            <DistanceHeatmap m={matrix.data} />
            <div className="flex flex-wrap gap-2 text-xs">
              {(["distances", "csv", "fasta"] as const).map((f) => (
                <a key={f} href={api.snpMatrixUrl(projectId, group.reference_sha256, f)} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 hover:bg-muted">
                  <Download className="h-3.5 w-3.5" aria-hidden /> {t(`variants.matrix.download.${f}` as TranslationKey)}
                </a>
              ))}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
