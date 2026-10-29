import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ChartCard, Segmented } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, useChartTheme, type ChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { escapeHtml, fmtDate, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { asPercent, fastpMate, insertSizeSpan, padCurve } from "@/lib/qcData";
import type { AnalysisJobDetail, FastpCurves, FastpData, FastpMate, RawFile } from "@/lib/types";

const MATE_LABEL: Record<FastpMate, string> = { read1: "R1", read2: "R2" };

function tooltipRow(label: string, value: string) {
  return `<div style="display:flex;justify-content:space-between;gap:16px"><span style="opacity:.7">${escapeHtml(label)}</span><b>${value}</b></div>`;
}

function legend(th: ChartTheme) {
  return { top: 0, right: 8, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: th.text, fontSize: 11 } };
}

/** QC tab: fastp's per-cycle curves, adapter trimming and insert sizes for the run that read (or wrote) this file. */
export function FastpDataSection({ job, file, files, prefix }: { job: AnalysisJobDetail; file: RawFile; files: RawFile[]; prefix: string }) {
  const t = useT();
  const query = useQuery({ queryKey: ["fastp-data", job.id], queryFn: () => api.fastpData(job.id), staleTime: Infinity });
  const [chosen, setMate] = useState<FastpMate>(() => fastpMate(job, file));
  const data = query.data;
  const names = (job.input_raw_file_ids ?? []).map((id) => files.find((f) => f.id === id)?.original_filename ?? id);
  const mates = (["read1", "read2"] as const).filter((m) => data?.reads[m]);
  const mate = mates.includes(chosen) ? chosen : mates[0];
  const mateSwitch =
    mates.length > 1 ? (
      <Segmented label={t("qcdata.fastp.mate")} value={mate} onChange={setMate} options={mates.map((m) => ({ value: m, label: MATE_LABEL[m] }))} />
    ) : null;
  return (
    <section className="min-w-0 space-y-4">
      <div>
        <h2 className="text-sm font-semibold">{t("qcdata.fastp.title")}</h2>
        <p className="mt-0.5 break-words text-xs text-muted-foreground">
          {t("qcdata.fastp.subtitle", { version: data?.fastp_version ?? job.tool_version, date: fmtDate(job.finished_at), inputs: names.join(" + ") })}
        </p>
      </div>
      {query.isLoading && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> {t("qcdata.loading")}
        </p>
      )}
      {query.error && <ErrorNote error={t("qcdata.error", { error: query.error instanceof Error ? query.error.message : String(query.error) })} />}
      {data && (
        <>
          {mate ? (
            <div className="grid gap-6 lg:grid-cols-2">
              <QualityChart stages={data.reads[mate] ?? {}} mate={mate} controls={mateSwitch} prefix={prefix} />
              <ContentChart stages={data.reads[mate] ?? {}} mate={mate} controls={mateSwitch} prefix={prefix} />
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t("qcdata.fastp.noCurves")}</p>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <AdapterCard data={data} />
            {data.insert_size && <InsertSizeChart data={data} prefix={prefix} />}
          </div>
        </>
      )}
    </section>
  );
}

type Stages = { before?: FastpCurves; after?: FastpCurves };

function cycles(stages: Stages) {
  return Math.max(stages.before?.total_cycles ?? 0, stages.after?.total_cycles ?? 0);
}

function beforeAfterOption(
  th: ChartTheme,
  t: ReturnType<typeof useT>,
  n: number,
  before: (number | null)[],
  after: (number | null)[],
  yName: string,
  unit: string,
): EChartsOption {
  const fmt = (v: number | null) => (v === null ? "—" : `${fmtNum(v, 2)}${unit}`);
  return {
    ...baseOption(th),
    grid: { left: 52, right: 16, top: 32, bottom: 44 },
    legend: legend(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0].dataIndex;
        return `<b>${escapeHtml(t("qcdata.fastp.cycle", { cycle: i + 1 }))}</b>${tooltipRow(t("qcdata.fastp.before"), fmt(before[i]))}${tooltipRow(t("qcdata.fastp.after"), fmt(after[i]))}`;
      },
    },
    xAxis: {
      type: "category",
      data: Array.from({ length: n }, (_, i) => i + 1),
      boundaryGap: false,
      ...axisStyle(th, t("qcdata.fastp.x"), { nameGap: 28, splitLine: { show: false } }),
    },
    yAxis: { type: "value", min: 0, ...axisStyle(th, yName, { nameGap: 36 }) },
    series: [
      { name: t("qcdata.fastp.before"), type: "line", showSymbol: false, data: before, lineStyle: { width: 2, color: th.primary }, itemStyle: { color: th.primary } },
      { name: t("qcdata.fastp.after"), type: "line", showSymbol: false, data: after, lineStyle: { width: 2, color: th.secondary }, itemStyle: { color: th.secondary } },
    ],
  };
}

function QualityChart({ stages, mate, controls, prefix }: { stages: Stages; mate: FastpMate; controls: ReactNode; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const n = cycles(stages);
  const before = padCurve(stages.before?.quality.mean, n);
  const after = padCurve(stages.after?.quality.mean, n);
  return (
    <ChartCard
      title={t("qcdata.fastp.qualityTitle")}
      subtitle={t("qcdata.fastp.qualitySubtitle", { mate: MATE_LABEL[mate] })}
      explain="per_position_quality_fastp"
      option={beforeAfterOption(th, t, n, before, after, t("qcdata.fastp.qualityY"), "")}
      controls={controls}
      filePrefix={`${prefix}_fastp_${MATE_LABEL[mate]}`}
      table={{
        columns: [t("qcdata.fastp.colCycle"), t("qcdata.fastp.before"), t("qcdata.fastp.after")],
        rows: before.map((v, i) => [i + 1, v ?? "—", after[i] ?? "—"]),
      }}
    />
  );
}

function ContentChart({ stages, mate, controls, prefix }: { stages: Stages; mate: FastpMate; controls: ReactNode; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const [base, setBase] = useState<"GC" | "N">("GC");
  const n = cycles(stages);
  const before = asPercent(padCurve(stages.before?.content[base], n));
  const after = asPercent(padCurve(stages.after?.content[base], n));
  return (
    <ChartCard
      title={t("qcdata.fastp.contentTitle")}
      subtitle={t("qcdata.fastp.contentSubtitle", { base, mate: MATE_LABEL[mate] })}
      explain="per_position_quality_fastp"
      option={beforeAfterOption(th, t, n, before, after, t("qcdata.fastp.contentY"), "%")}
      controls={
        <>
          {controls}
          <Segmented label={t("qcdata.fastp.base")} value={base} onChange={setBase} options={[{ value: "GC", label: "GC" }, { value: "N", label: "N" }]} />
        </>
      }
      filePrefix={`${prefix}_fastp_${MATE_LABEL[mate]}_${base}`}
      table={{
        columns: [t("qcdata.fastp.colCycle"), `${t("qcdata.fastp.before")} (%)`, `${t("qcdata.fastp.after")} (%)`],
        rows: before.map((v, i) => [i + 1, v ?? "—", after[i] ?? "—"]),
      }}
    />
  );
}

function AdapterCard({ data }: { data: FastpData }) {
  const t = useT();
  const ac = data.adapter_cutting;
  const rate = data.duplication_rate;
  const tile = (label: string, value: string) => (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
  return (
    <Card className="min-w-0">
      <CardHeader title={t("qcdata.fastp.adapterTitle")} description={t("qcdata.fastp.adapterSubtitle")} action={<Explain id="fastp" />} />
      <CardBody className="space-y-4 pt-3 text-xs">
        <div className="grid gap-3 sm:grid-cols-3">
          {ac && tile(t("qcdata.fastp.trimmedReads"), fmtInt(ac.adapter_trimmed_reads ?? 0))}
          {ac && tile(t("qcdata.fastp.trimmedBases"), fmtInt(ac.adapter_trimmed_bases ?? 0))}
          {tile(t("qcdata.fastp.dupRate"), rate === null ? t("qcdata.fastp.dupNotEvaluated") : fmtPct(100 * rate, 2))}
        </div>
        {!ac ? (
          <p className="text-muted-foreground">{t("qcdata.fastp.adapterNone")}</p>
        ) : (
          (["read1", "read2"] as const).map((m) => {
            const counts = m === "read1" ? ac.read1_adapter_counts : ac.read2_adapter_counts;
            const given = m === "read1" ? ac.read1_adapter_sequence : ac.read2_adapter_sequence;
            if (!counts.length && !given) return null;
            return (
              <div key={m} className="space-y-1.5">
                <p className="break-words text-muted-foreground">
                  {t("qcdata.fastp.adapterSequence", { mate: MATE_LABEL[m] })}:{" "}
                  {given === "unspecified" ? t("qcdata.fastp.unspecified") : <code className="break-all font-mono text-[11px] text-foreground">{given}</code>}
                </p>
                {counts.length > 0 && (
                  <table className="w-full table-fixed">
                    <caption className="pb-1 text-left font-medium">{t("qcdata.fastp.countsTitle", { mate: MATE_LABEL[m] })}</caption>
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-1 pr-3 font-medium">{t("qcdata.fastp.colSequence")}</th>
                        <th className="w-20 py-1 text-right font-medium">{t("qcdata.fastp.colReads")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {counts.map((c) => (
                        <tr key={c.sequence} className="border-b border-border/50">
                          <td className="py-1 pr-3">
                            {c.sequence === "others" ? t("qcdata.fastp.others") : <code className="break-all font-mono text-[11px]">{c.sequence}</code>}
                          </td>
                          <td className="py-1 text-right tabular-nums">{fmtInt(c.count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })
        )}
      </CardBody>
    </Card>
  );
}

function InsertSizeChart({ data, prefix }: { data: FastpData; prefix: string }) {
  const t = useT();
  const th = useChartTheme();
  const ins = data.insert_size!;
  const span = insertSizeSpan(ins.histogram);
  const notes = <p>{t("qcdata.insert.note", { max: fmtInt(ins.insert_size_max), unknown: fmtNum(ins.unknown_percent ?? 0, 1) })}</p>;
  if (!span || ins.peak === null) {
    return (
      <Card>
        <CardHeader title={t("qcdata.insert.title")} action={<Explain id="insert_size" />} />
        <CardBody className="space-y-2 pt-2 text-xs text-muted-foreground">
          <p className="text-sm">{t("qcdata.insert.noOverlap", { evaluated: fmtInt(ins.evaluated_pairs) })}</p>
          {notes}
        </CardBody>
      </Card>
    );
  }
  const sizes = Array.from({ length: span[1] - span[0] + 1 }, (_, i) => span[0] + i);
  const option: EChartsOption = {
    ...baseOption(th),
    tooltip: {
      ...baseOption(th).tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } },
      formatter: (p: unknown) => {
        const size = sizes[(p as { dataIndex: number }[])[0].dataIndex];
        return `<b>${fmtInt(size)} bp</b>${tooltipRow(t("qcdata.insert.pairs"), fmtInt(ins.histogram[size]))}${tooltipRow(t("qcdata.insert.colPercent"), fmtPct(ins.histogram_percent[size], 2))}`;
      },
    },
    xAxis: { type: "category", data: sizes, ...axisStyle(th, t("qcdata.insert.x"), { nameGap: 28, splitLine: { show: false } }) },
    yAxis: { type: "value", min: 0, ...axisStyle(th, t("qcdata.insert.y"), { nameGap: 36 }) },
    series: [
      {
        type: "bar",
        data: sizes.map((s) => ins.histogram_percent[s]),
        itemStyle: { color: th.primary, borderRadius: [2, 2, 0, 0] },
        barCategoryGap: "10%",
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: th.text, type: "dashed", width: 1, opacity: 0.6 },
          label: { color: th.text, fontSize: 10, formatter: t("qcdata.insert.peakLabel", { peak: ins.peak }) },
          data: [{ xAxis: ins.peak - span[0] }],
        },
      },
    ],
  };
  return (
    <ChartCard
      title={t("qcdata.insert.title")}
      subtitle={t("qcdata.insert.subtitle", {
        peak: fmtInt(ins.peak),
        evaluated: fmtInt(ins.evaluated_pairs),
        threads: data.threads ?? "?",
        overlap: fmtNum((100 * ins.overlapping_pairs) / ins.evaluated_pairs, 1),
      })}
      explain="insert_size"
      option={option}
      filePrefix={`${prefix}_fastp`}
      table={{
        columns: [t("qcdata.insert.x"), t("qcdata.insert.pairs"), t("qcdata.insert.colPercent")],
        rows: [
          ...sizes.filter((s) => ins.histogram[s] > 0).map((s) => [s, ins.histogram[s], fmtNum(ins.histogram_percent[s], 2)]),
          ["unknown", ins.unknown, fmtNum(ins.unknown_percent ?? 0, 2)],
        ],
      }}
      footer={notes}
    />
  );
}
