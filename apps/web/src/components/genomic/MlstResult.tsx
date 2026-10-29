import { AlertTriangle, Download } from "lucide-react";
import { MetricTile } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, shellJoin } from "@/lib/format";
import { clonalComplexText, warningText } from "@/lib/mlst";
import type { AnalysisJobDetail, MlstAllele, MlstResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const TONE: Record<MlstAllele["type"], "success" | "warning" | "danger" | "neutral"> = {
  exact: "success",
  novel: "warning",
  partial: "warning",
  missing: "danger",
  multiple: "warning",
  null: "neutral",
  unrecognised: "danger",
};

/** One MLST call as mlst reported it: scheme, ST, every locus with its call type, the clonal complex (from the
 * scheme's profile file), ARVA's warnings, the bundled database and the files. */
export function MlstCard({ result, job }: { result: MlstResult; job?: AnalysisJobDetail }) {
  const t = useT();
  const m = result;
  const scheme = m.details.scheme;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {t("mlst.cardTitle", { tool: `${m.tool} ${m.tool_version}` })}
            <Badge tone={m.st ? "success" : "warning"}>{m.st ? t("mlst.stBadge", { st: m.st }) : t("mlst.stNotAssigned")}</Badge>
          </span>
        }
        description={t("mlst.cardSubtitle", { date: fmtDate(m.created_at), assembly: m.assembly_id.slice(0, 8) })}
        action={<Explain id="mlst" compact />}
      />
      <CardBody className="space-y-4 pt-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label={t("mlst.scheme")} value={m.scheme ?? t("mlst.noScheme")} sub={scheme ? t("mlst.schemeSource", { source: scheme.source ?? "?", date: scheme.last_updated ?? "?" }) : undefined} />
          <MetricTile label={t("mlst.st")} value={m.st ?? t("mlst.stNotAssigned")} explain="sequence_type" />
          <MetricTile label={t("mlst.status")} value={m.status} sub={t("mlst.score", { score: m.score })} />
          <MetricTile label={t("mlst.clonalComplex")} value={clonalComplexText(t, m.clonal_complex)} sub={m.clonal_complex.column ? t("mlst.ccColumn", { column: m.clonal_complex.column }) : undefined} />
        </div>
        {m.warnings.length > 0 && (
          <ul role="status" className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            {m.warnings.map((w, i) => (
              <li key={`${w.code}-${i}`} className="flex gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {warningText(t, w)}
              </li>
            ))}
          </ul>
        )}
        {m.alleles.length > 0 && <AlleleTable alleles={m.alleles} />}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t("mlst.database")}</dt>
            <dd>
              {m.database_name} · {t("mlst.downloaded", { date: m.database_version ?? "?" })}
              {m.database_checksum && <code className="block break-all text-muted-foreground">{m.database_checksum}</code>}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("mlst.settings")}</dt>
            <dd>
              {t("mlst.settingsLine", {
                minid: String(m.parameters.minid ?? "?"),
                mincov: String(m.parameters.mincov ?? "?"),
                minscore: String(m.parameters.minscore ?? "?"),
              })}
              {m.parameters.scheme ? ` · ${t("mlst.schemeChosen", { scheme: String(m.parameters.scheme) })}` : ` · ${t("mlst.schemeDetected")}`}
            </dd>
          </div>
        </dl>
        <p className="text-xs text-muted-foreground">{t("mlst.termsNote")}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          {(["tsv", "json", "novel", "log"] as const)
            .filter((k) => m.files[k])
            .map((k) => (
              <a key={k} href={api.mlstFileUrl(m.id, k)} className="inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted">
                <Download className="h-3.5 w-3.5" aria-hidden /> {t(`mlst.file.${k}` as TranslationKey)}
              </a>
            ))}
        </div>
        {job?.commands?.length ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">{t("mlst.commands")}</summary>
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

export function AlleleTable({ alleles }: { alleles: MlstAllele[] }) {
  const t = useT();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{t("mlst.locus")}</th>
            <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{t("mlst.call")}</th>
            <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                {t("mlst.callType")} <Explain id="novel_allele" compact />
              </span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {alleles.map((a) => (
            <tr key={a.locus}>
              <td className="px-2 py-1.5 font-mono">{a.locus}</td>
              <td className={cn("px-2 py-1.5 font-mono", a.type !== "exact" && "font-semibold")}>{a.call}</td>
              <td className="px-2 py-1.5">
                <Badge tone={TONE[a.type]}>{t(`mlst.callType.${a.type}` as TranslationKey)}</Badge>
                {a.similar_to && <span className="ml-2 text-muted-foreground">{t("mlst.similarTo", { allele: a.similar_to })}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
