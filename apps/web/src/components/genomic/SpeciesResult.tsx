import type { EChartsOption } from "echarts";
import { AlertTriangle, CheckCircle2, Download, Info } from "lucide-react";
import { ChartCard } from "@/components/charts/ChartCard";
import { axisStyle, baseOption, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtNum, shellJoin } from "@/lib/format";
import { afPercent, ANI_METHODS, caveatText, CHART_HITS, CHECK_TONE, checkText, reasonText, STATUS_TONE, statusText, warningText } from "@/lib/species";
import type { AnalysisJobDetail, SpeciesHit, SpeciesResult } from "@/lib/types";

const JAIN = "https://doi.org/10.1038/s41467-018-07641-9";
const FILES = ["output", "log", "references", "info", "info_header", "inspect", "summary_bacteria", "summary_archaea"] as const;

const pct = (v: number | null | undefined, digits = 2) => (typeof v === "number" ? fmtNum(v, digits) : "—");

/** One species identification: ARVA's reading (with why it is not more certain), the consistency checks, a chart
 * and table of the best hits, the database it searched, and the tool's own files. */
export function SpeciesCard({ result, job }: { result: SpeciesResult; job?: AnalysisJobDetail }) {
  const t = useT();
  const r = result;
  const ani = ANI_METHODS.has(r.method);
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {t("species.cardTitle", { tool: `${r.tool} ${r.tool_version}` })}
            <Badge tone={STATUS_TONE[r.status]}>{t(`species.statusShort.${r.status}` as TranslationKey)}</Badge>
          </span>
        }
        description={t("species.cardSubtitle", { date: fmtDate(r.created_at), assembly: r.assembly_id.slice(0, 8) })}
        action={<Explain id="ani" compact />}
      />
      <CardBody className="space-y-4 pt-3">
        <Interpretation result={r} />
        {r.warnings.length > 0 && (
          <ul role="status" className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            {r.warnings.map((w, i) => (
              <li key={`${w.code}-${i}`} className="flex gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {warningText(t, w)}
              </li>
            ))}
          </ul>
        )}
        {ani && r.hits.some((h) => typeof h.ani === "number") && <HitsChart result={r} />}
        {r.hits.length > 0 ? <HitsTable result={r} /> : <p className="text-xs text-muted-foreground">{t("species.noHits")}</p>}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t("species.database")}</dt>
            <dd>
              {r.database_name} · {r.database_version ?? "?"}
              {r.database_checksum && <code className="block break-all text-muted-foreground">{r.database_checksum}</code>}
              {r.details.references_checksum && (
                <span className="block text-muted-foreground">
                  {t("species.referencesChecksum", { n: r.details.references?.length ?? 0 })} <code className="break-all">{r.details.references_checksum}</code>
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("species.settings")}</dt>
            <dd>
              <code className="break-all">{JSON.stringify(r.parameters.settings ?? {})}</code>
              {r.details.learned_ani && <span className="block text-muted-foreground">{t("species.learnedAni")}</span>}
              {r.details.sketch && <span className="block text-muted-foreground">{t("species.mashSketch", { k: r.details.sketch.kmer, s: r.details.sketch.sketch_size })}</span>}
              {r.details.sylph_database && <span className="block text-muted-foreground">{t("species.sylphDb", { c: r.details.sylph_database.c, k: r.details.sylph_database.k })}</span>}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-2 text-xs">
          {FILES.filter((k) => r.files[k]).map((k) => (
            <a key={k} href={api.speciesFileUrl(r.id, k)} className="inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted">
              <Download className="h-3.5 w-3.5" aria-hidden /> {t(`species.file.${k}` as TranslationKey)}
            </a>
          ))}
        </div>
        {job?.commands?.length ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">{t("species.commands")}</summary>
            {job.commands.map((c, i) => (
              <pre key={i} className="mt-1 whitespace-pre-wrap break-all rounded bg-muted p-2 font-mono text-[11px]">
                {shellJoin(c)}
              </pre>
            ))}
          </details>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function Interpretation({ result: r }: { result: SpeciesResult }) {
  const t = useT();
  const i = r.interpretation;
  const best = i.best;
  const th = i.thresholds;
  return (
    <div className="space-y-2 rounded-lg border p-3 text-xs" aria-label={t("species.interpretation")}>
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        {r.status === "same_species" ? <CheckCircle2 className="h-4 w-4 text-success" aria-hidden /> : <Info className="h-4 w-4 text-muted-foreground" aria-hidden />}
        {statusText(t, r.status, r.species)}
        <Explain id="species_boundary" compact />
      </p>
      {best && (
        <p>
          {r.method === "mash"
            ? t("species.bestMash", { reference: best.accession ?? best.reference ?? "?", organism: best.organism ?? "—", distance: best.distance ?? "?" })
            : t("species.best", { reference: best.accession ?? best.reference ?? "?", organism: best.organism ?? best.species ?? "—", ani: pct(best.ani), af: pct(afPercent(best), 1) })}
          {best.type_material === true && ` · ${t("species.typeMaterial")}`}
        </p>
      )}
      {i.runner_up && (
        <p className="text-muted-foreground">
          {t("species.runnerUp", { species: i.runner_up.species ?? "—", ani: pct(i.runner_up.ani), af: pct(afPercent(i.runner_up), 1) })}
        </p>
      )}
      {i.reasons.length > 0 && (
        <ul className="space-y-0.5">
          {i.reasons.map((x, n) => (
            <li key={`${x.code}-${n}`} className="flex gap-1.5 text-amber-700 dark:text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {reasonText(t, x)}
            </li>
          ))}
        </ul>
      )}
      {r.consistency.length > 0 && (
        <ul className="space-y-0.5" aria-label={t("species.consistency")}>
          {r.consistency.map((c) => (
            <li key={c.source} className="flex flex-wrap items-center gap-1.5">
              <Badge tone={CHECK_TONE[c.outcome]}>{t(`species.checkShort.${c.outcome}` as TranslationKey)}</Badge> {checkText(t, c)}
            </li>
          ))}
        </ul>
      )}
      {r.method !== "mash" && r.method !== "gtdbtk" && (
        <p className="text-muted-foreground">
          {t("species.thresholds", { boundary: th.ani_boundary, af: th.min_af, margin: th.margin })}{" "}
          <a href={JAIN} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
            {t("species.jainLink")}
          </a>
        </p>
      )}
      {i.caveats.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
          {i.caveats.map((x) => (
            <li key={x.code}>{caveatText(t, x)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function label(h: SpeciesHit) {
  const name = h.species ?? h.organism ?? h.reference ?? "?";
  return `${name.length > 28 ? `${name.slice(0, 27)}…` : name} · ${h.accession ?? h.reference ?? ""}`;
}

/** ANI and aligned fraction of the best hits, with the species boundary as a line. */
export function HitsChart({ result: r }: { result: SpeciesResult }) {
  const t = useT();
  const th = useChartTheme();
  const hits = r.hits.filter((h) => typeof h.ani === "number").slice(0, CHART_HITS);
  const boundary = r.interpretation.thresholds.ani_boundary;
  const labels = hits.map(label);
  const option: EChartsOption = {
    ...baseOption(th),
    grid: { left: 240, right: 40, top: 28, bottom: 40 },
    legend: { top: 0, textStyle: { color: th.muted, fontSize: 11 } },
    tooltip: { ...baseOption(th).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.6 } } },
    xAxis: { type: "value", min: 0, max: 100, ...axisStyle(th, t("species.chart.axis"), { nameGap: 26 }) },
    yAxis: { type: "category", data: labels, inverse: true, axisLabel: { color: th.text, fontSize: 11 }, axisLine: { lineStyle: { color: th.axis } }, axisTick: { show: false } },
    series: [
      {
        name: t("species.chart.ani"),
        type: "bar",
        data: hits.map((h) => h.ani ?? null),
        itemStyle: { color: th.primary },
        barMaxWidth: 14,
        markLine: {
          symbol: "none",
          silent: true,
          lineStyle: { color: th.series[1], type: "dashed", width: 1.5 },
          label: { color: th.text, fontSize: 10, formatter: t("species.chart.boundary", { boundary }) },
          data: [{ xAxis: boundary }],
        },
      },
      { name: t("species.chart.af"), type: "bar", data: hits.map((h) => afPercent(h)), itemStyle: { color: th.secondary }, barMaxWidth: 14 },
    ],
  };
  return (
    <ChartCard
      title={t("species.chart.title")}
      subtitle={t("species.chart.subtitle", { n: hits.length, boundary })}
      explain="species_boundary"
      option={option}
      height={Math.max(180, 60 + hits.length * 34)}
      filePrefix={`species_${r.method}`}
      table={{
        columns: [t("species.col.reference"), t("species.col.organism"), t("species.chart.ani"), t("species.chart.af")],
        rows: hits.map((h) => [h.accession ?? h.reference ?? "", h.organism ?? "", h.ani ?? "", afPercent(h) ?? ""]),
      }}
      footer={<p className="text-xs text-muted-foreground">{t(`species.chart.footer.${r.method}` as TranslationKey)}</p>}
    />
  );
}

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";

export function HitsTable({ result: r }: { result: SpeciesResult }) {
  const t = useT();
  const m = r.method;
  const cols: TranslationKey[] = ["species.col.rank", "species.col.reference", "species.col.organism", "species.col.type"];
  if (m === "mash") cols.push("species.col.distance", "species.col.pValue", "species.col.shared");
  else cols.push("species.col.ani", "species.col.af");
  if (m === "fastani") cols.push("species.col.fragments");
  if (m === "skani") cols.push("species.col.afBoth");
  if (m === "sylph") cols.push("species.col.adjusted", "species.col.containment");
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50">
          <tr>
            {cols.map((c) => (
              <th key={c} className={TH}>
                {t(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {r.hits.map((h) => (
            <tr key={`${h.rank}-${h.reference}`}>
              <td className={`${TD} tabular-nums`}>{h.rank}</td>
              <td className={`${TD} font-mono`}>{h.accession ?? h.reference}</td>
              <td className="px-2 py-1.5">
                {h.organism ?? "—"}
                {h.strain && <span className="text-muted-foreground"> · {h.strain}</span>}
              </td>
              <td className={TD}>{h.type_material === true ? <Badge tone="success">{t("species.yes")}</Badge> : h.type_material === false ? t("species.no") : t("species.unknown")}</td>
              {m === "mash" ? (
                <>
                  <td className={`${TD} tabular-nums`}>{h.distance ?? "—"}</td>
                  <td className={`${TD} tabular-nums`}>{h.p_value ?? "—"}</td>
                  <td className={`${TD} tabular-nums`}>
                    {h.shared}/{h.hashes}
                  </td>
                </>
              ) : (
                <>
                  <td className={`${TD} font-semibold tabular-nums`}>{pct(h.ani)}</td>
                  <td className={`${TD} tabular-nums`}>{pct(afPercent(h), 1)}</td>
                </>
              )}
              {m === "fastani" && (
                <td className={`${TD} tabular-nums`}>
                  {h.fragments_mapped}/{h.fragments_total}
                </td>
              )}
              {m === "skani" && (
                <td className={`${TD} tabular-nums`}>
                  {pct((h.af_query ?? 0) * 100, 1)} / {pct((h.af_reference ?? 0) * 100, 1)}
                </td>
              )}
              {m === "sylph" && (
                <>
                  <td className={`${TD} tabular-nums`}>
                    {pct(h.adjusted_ani)} {h.eff_lambda === "LOW" && <span className="text-muted-foreground">({t("species.lowLambda")})</span>}
                  </td>
                  <td className={`${TD} tabular-nums`}>
                    {h.containment_shared}/{h.containment_sampled}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
