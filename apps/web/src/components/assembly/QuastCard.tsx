import { CheckCircle2, Download, ExternalLink, Info, XCircle } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { FIELD_HELP, formatQuastValue, quastOutput, quastSummary, reportRows } from "@/lib/quast";
import type { AnalysisJobDetail, QuastCrosscheckRow, QuastSummary } from "@/lib/types";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground";
const TD = "px-2 py-1.5 tabular-nums";
const LINK_BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted";
const DOWNLOADS = ["report.tsv", "transposed_report.tsv", "quast.log", "quast.console.log"];

/** A completed QUAST evaluation: QUAST's values for every assembly (ARVA's table is the primary view), ARVA's
 * cross-check of the metrics both compute, and links to QUAST's own HTML pages. */
export function QuastCard({ job }: { job: AnalysisJobDetail }) {
  const t = useT();
  const [all, setAll] = useState(false);
  const s = quastSummary(job);
  if (!s) return null;
  const rows = reportRows(s, all);
  const total = s.report.rows.length;
  const report = quastOutput(job, s.html.report);
  const icarus = quastOutput(job, s.html.icarus);
  const part = t("quast.partial");
  return (
    <Card>
      <CardHeader
        title={t("quast.result", { version: s.quast_version, count: s.report.labels.length, min: fmtInt(s.min_contig) })}
        description={`${fmtDate(job.finished_at ?? job.created_at)} · ${s.reference ? t("quast.withReference", { name: s.reference.name }) : t("quast.noReferenceUsed")}`}
        action={
          <div className="flex flex-wrap gap-2">
            {report && (
              <a className={LINK_BUTTON} href={api.jobOutputUrl(job.id, report)} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-3.5 w-3.5" /> {t("quast.htmlReport")}
              </a>
            )}
            {icarus && (
              <a className={LINK_BUTTON} href={api.jobOutputUrl(job.id, icarus)} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-3.5 w-3.5" /> {t("quast.icarus")}
              </a>
            )}
            {DOWNLOADS.map((n) => {
              const path = quastOutput(job, n);
              return (
                path && (
                  <a key={n} className={LINK_BUTTON} href={api.jobOutputUrl(job.id, path, true)}>
                    <Download className="h-3.5 w-3.5" /> {n}
                  </a>
                )
              );
            })}
          </div>
        }
      />
      <CardBody className="space-y-5 pt-3">
        <p className="flex gap-1.5 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("quast.htmlNote")}
        </p>

        <div>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-xs">
              <thead className="bg-muted/50">
                <tr>
                  <th className={TH}>{t("quast.metric")}</th>
                  {s.report.labels.map((label) => (
                    <th key={label} className={`${TH} font-mono`}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((r) => {
                  const help = FIELD_HELP[r.field];
                  return (
                    <tr key={r.field}>
                      <th scope="row" className="px-2 py-1.5 text-left align-top font-normal">
                        <span className="font-mono">{r.field}</span>
                        {help && <span className="block max-w-md text-[11px] text-muted-foreground">{t(help, { min: fmtInt(s.min_contig) })}</span>}
                      </th>
                      {r.values.map((v, i) => (
                        <td key={s.report.labels[i]} className={`${TD} align-top`}>
                          {formatQuastValue(v, part)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-muted-foreground">{t("quast.tableNote", { min: fmtInt(s.min_contig) })}</p>
            {total > rows.length || all ? (
              <Button size="sm" variant="ghost" onClick={() => setAll(!all)}>
                {all ? t("quast.showMain") : t("quast.showAll", { count: total })}
              </Button>
            ) : null}
          </div>
        </div>

        <Crosscheck summary={s} />

        {s.reference && (
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>{t("quast.referenceCaution")}</p>
            <p>{t("quast.ambiguityNote")}</p>
            {s.aligner && <p>{t("quast.alignerUsed", { name: s.aligner.name, version: s.aligner.version, path: s.aligner.executable })}</p>}
          </div>
        )}
        {(s.warnings.length > 0 || s.quast_log_empty) && (
          <div className="text-xs">
            <div className="mb-1 font-medium">{t("quast.warningsTitle")}</div>
            <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
              {s.warnings.map((w) => (
                <li key={w} className="font-mono text-[11px]">
                  {w}
                </li>
              ))}
              {s.quast_log_empty && <li>{t("quast.emptyLog", { python: s.python_version ?? "?" })}</li>}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function Crosscheck({ summary: s }: { summary: QuastSummary }) {
  const t = useT();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
        {t("quast.crosscheckTitle", { min: fmtInt(s.min_contig) })}
      </div>
      {s.crosscheck.map((c) => {
        const decided = c.rows.filter((r) => r.agrees !== null);
        const equal = decided.filter((r) => r.agrees).length;
        return (
          <details key={c.assembly_id} className="rounded-lg border px-3 py-2 text-xs" open={!c.all_agree}>
            <summary className="flex cursor-pointer flex-wrap items-center gap-2">
              {c.all_agree ? <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden /> : <XCircle className="h-3.5 w-3.5 text-danger" aria-hidden />}
              <span className="font-mono">{c.label}</span>
              <span className="text-muted-foreground">{t("quast.crosscheckLine", { equal, total: decided.length })}</span>
              {!c.all_agree && <Badge tone="warning">{t("quast.crosscheckDiffers")}</Badge>}
            </summary>
            <table className="mt-2 w-full">
              <thead>
                <tr>
                  <th className={TH}>{t("quast.metric")}</th>
                  <th className={TH}>QUAST</th>
                  <th className={TH}>ARVA</th>
                  <th className={TH}>{t("quast.agrees")}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {c.rows.map((r) => (
                  <CrosscheckRow key={r.metric} row={r} />
                ))}
              </tbody>
            </table>
          </details>
        );
      })}
      <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-muted-foreground">
        <li>{t("quast.def.same", { min: fmtInt(s.min_contig) })}</li>
        <li>{t("quast.def.nx")}</li>
        <li>{t("quast.def.gc")}</li>
        <li>{t("quast.def.ns")}</li>
        <li>{t("quast.def.rounding")}</li>
      </ul>
    </div>
  );
}

function CrosscheckRow({ row: r }: { row: QuastCrosscheckRow }) {
  const t = useT();
  const arva = r.arva === null ? "—" : r.decimals === null ? fmtInt(r.arva) : fmtNum(r.arva, r.decimals + 2);
  return (
    <tr>
      <td className="px-2 py-1 font-mono">{r.metric}</td>
      <td className={TD}>{formatQuastValue(r.quast, t("quast.partial"))}</td>
      <td className={TD}>{arva}</td>
      <td className="px-2 py-1">
        {r.agrees === null ? "—" : r.agrees ? <span className="text-success">{t("quast.equal")}</span> : <span className="font-medium text-danger">{t("quast.differs")}</span>}
      </td>
    </tr>
  );
}
