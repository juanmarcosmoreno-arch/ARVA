import { AlertTriangle, Download } from "lucide-react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt, fmtNum, shellJoin } from "@/lib/format";
import { callTone, categoryKey, COMPLETENESS_TONE, warningText } from "@/lib/mobile";
import type { AnalysisJobDetail, MobileContigTable, MobileRow, MobileRun } from "@/lib/types";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

/** Each contig of an assembly with, side by side, MOB-suite's call (and what it found on the contig), the
 * PlasmidFinder replicons, the counts of integrons, IS elements and geNomad calls, and the assembler's own
 * circularity. "Not searched" (the method did not run) is kept apart from "none found". */
export function MobileContigCard({ table }: { table: MobileContigTable }) {
  const t = useT();
  const notSearched = t("mobile.notSearched");
  return (
    <Card>
      <CardHeader
        title={t("mobile.contigTitle", { assembler: `${table.assembler} ${table.assembler_version}` })}
        description={t("mobile.contigSubtitle", { assembly: table.assembly_id.slice(0, 8) })}
        action={<Explain id="plasmid" compact />}
      />
      <CardBody className="space-y-3 pt-3">
        <p role="note" className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("mobile.callsNote")}</span>
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className={TH}>{t("mobile.col.contig")}</th>
                <th className={TH}>
                  <span className="inline-flex items-center gap-1">
                    {t("mobile.col.call")} <Explain id="plasmid" compact />
                  </span>
                </th>
                <th className={TH}>
                  <span className="inline-flex items-center gap-1">
                    {t("mobile.col.replicons")} <Explain id="replicon" compact />
                  </span>
                </th>
                <th className={TH}>{t("mobile.col.relaxase")}</th>
                <th className={TH}>{t("mobile.col.mobility")}</th>
                <th className={TH}>{t("mobile.col.plasmidfinder")}</th>
                <th className={TH}>{t("mobile.col.elements")}</th>
                <th className={TH}>{t("mobile.col.circular")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {table.contigs.map((c) => {
                const m = c.mobsuite;
                return (
                  <tr key={c.contig}>
                    <td className={TD}>
                      <span className="font-mono">{c.contig}</span>
                      <span className="block text-muted-foreground">{c.length != null ? fmtBases(c.length) : "?"}</span>
                    </td>
                    <td className={TD}>
                      {m === null ? (
                        <span className="text-muted-foreground">{notSearched}</span>
                      ) : m.molecule_type ? (
                        <>
                          <Badge tone={callTone(m.molecule_type)}>{t(`mobile.molecule.${m.molecule_type === "plasmid" ? "plasmid" : "chromosome"}` as TranslationKey)}</Badge>
                          {m.primary_cluster_id && <span className="block text-muted-foreground">{t("mobile.cluster", { primary: m.primary_cluster_id, secondary: m.secondary_cluster_id ?? "-" })}</span>}
                        </>
                      ) : (
                        <span className="text-muted-foreground">{t("mobile.notReported")}</span>
                      )}
                    </td>
                    <td className={TD}>{m === null ? "—" : (m.rep_types ?? []).join(", ") || "—"}</td>
                    <td className={TD}>
                      {m === null ? "—" : (m.relaxase_types ?? []).join(", ") || "—"}
                      {m && (m.mpf_types ?? []).length > 0 && <span className="block text-muted-foreground">MPF {(m.mpf_types ?? []).join(", ")}</span>}
                      {m && (m.orit_types ?? []).length > 0 && <span className="block text-muted-foreground">oriT {(m.orit_types ?? []).join(", ")}</span>}
                    </td>
                    <td className={TD}>{m?.predicted_mobility ? t(`mobile.mobility.${m.predicted_mobility}` as TranslationKey) : "—"}</td>
                    <td className={TD}>
                      {c.replicons === null ? (
                        <span className="text-muted-foreground">{notSearched}</span>
                      ) : c.replicons.length ? (
                        c.replicons.map((r, i) => (
                          <span key={`${r.name}-${i}`} className="block">
                            <span className="font-mono">{r.name}</span>{" "}
                            <span className="text-muted-foreground">
                              {fmtNum(r.identity ?? 0, 2)} % / {fmtNum(r.coverage ?? 0, 2)} %
                            </span>
                          </span>
                        ))
                      ) : (
                        t("mobile.noneFound")
                      )}
                    </td>
                    <td className={TD}>
                      {t("mobile.elementsLine", {
                        integrons: c.integrons == null ? notSearched : fmtInt(c.integrons),
                        is: c.insertion_sequences == null ? notSearched : fmtInt(c.insertion_sequences),
                        viruses: c.genomad == null ? notSearched : fmtInt(c.genomad.viruses),
                      })}
                    </td>
                    <td className={TD}>
                      {c.circular == null ? <span className="text-muted-foreground">{t("mobile.circularUnknown")}</span> : t(c.circular ? "mobile.circularYes" : "mobile.circularNo", { source: c.circular_source ?? table.assembler })}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  );
}

/** One run as the tool reported it: what was searched (tool, database or bundled models, settings), its counts and
 * warnings, every call with its coordinates, identity, coverage and completeness, the files and commands. */
export function MobileRunCard({ run, job }: { run: MobileRun; job?: AnalysisJobDetail }) {
  const t = useT();
  const rows = run.rows.filter((r) => r.category !== "contig");
  const byCategory = new Map<string, MobileRow[]>();
  for (const r of rows) byCategory.set(r.category, [...(byCategory.get(r.category) ?? []), r]);
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {t(`mobile.method.${run.method}` as TranslationKey)} · {run.tool} {run.tool_version}
            <Badge tone={rows.length ? "blue" : "neutral"}>{rows.length ? t("mobile.callsBadge", { n: rows.length }) : t("mobile.noneFound")}</Badge>
          </span>
        }
        description={t("amr.cardSubtitle", { date: fmtDate(run.created_at), assembly: (run.assembly_id ?? "").slice(0, 8), db: `${run.database_name ?? t("mobile.bundledModels")} ${run.database_version ?? ""}`.trim() })}
        action={<Explain id="mobile_element" compact />}
      />
      <CardBody className="space-y-3 pt-3">
        {run.warnings.length > 0 && (
          <ul role="status" className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            {run.warnings.map((w, i) => (
              <li key={`${w.code}-${i}`} className="flex gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {warningText(t, w)}
              </li>
            ))}
          </ul>
        )}
        {!rows.length && <p className="text-sm text-muted-foreground">{t("mobile.noneFoundText")}</p>}
        {[...byCategory.entries()].map(([category, list]) => (
          <section key={category} className="space-y-1.5" aria-label={t(categoryKey(category))}>
            <h4 className="text-xs font-semibold">
              {t(categoryKey(category))} <span className="font-normal text-muted-foreground">({fmtInt(list.length)})</span>
            </h4>
            <RowTable rows={list} />
          </section>
        ))}
        <p className="text-xs text-muted-foreground">
          {t("mobile.settingsLine", { settings: Object.entries(run.parameters).filter(([k]) => k !== "threads").map(([k, v]) => `${k}=${String(v)}`).join(" ") })}
          {run.database_checksum && <code className="block break-all">{run.database_checksum}</code>}
        </p>
        <div className="flex flex-wrap gap-2 text-xs">
          {Object.keys(run.files).map((k) => (
            <a key={k} href={api.mobileFileUrl(run.job_id, k)} className="inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted">
              <Download className="h-3.5 w-3.5" aria-hidden /> {k}
            </a>
          ))}
        </div>
        {job?.commands?.length ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">{t("mlst.commands")}</summary>
            {job.commands.map((cmd, i) => (
              <pre key={i} className="mt-1 whitespace-pre-wrap break-all rounded bg-muted p-2 font-mono text-[11px]">
                {shellJoin(cmd)}
              </pre>
            ))}
          </details>
        ) : null}
      </CardBody>
    </Card>
  );
}

const pct = (v: number | null) => (v == null ? "—" : fmtNum(v, 2));

function RowTable({ rows }: { rows: MobileRow[] }) {
  const t = useT();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50">
          <tr>
            <th className={TH}>{t("mobile.col.element")}</th>
            <th className={TH}>{t("mobile.col.type")}</th>
            <th className={TH}>{t("mobile.col.location")}</th>
            <th className={TH}>{t("amr.col.identity")}</th>
            <th className={TH}>{t("amr.col.coverage")}</th>
            <th className={TH}>{t("mobile.col.completeness")}</th>
            <th className={TH}>{t("amr.col.feature")}</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.id}>
              <td className={`${TD} font-mono`}>{r.element ?? "—"}</td>
              <td className={TD}>{r.element_type ?? "—"}</td>
              <td className={`${TD} whitespace-nowrap font-mono`}>
                {r.contig ?? (Array.isArray(r.details?.contigs) ? (r.details?.contigs as string[]).join(", ") : "—")}
                {r.start != null && r.end != null ? `:${fmtInt(r.start)}–${fmtInt(r.end)}` : ""}
                {r.strand ? ` (${r.strand})` : ""}
              </td>
              <td className={`${TD} tabular-nums`}>{pct(r.identity)}</td>
              <td className={`${TD} tabular-nums`}>{pct(r.coverage)}</td>
              <td className={TD}>{r.completeness ? <Badge tone={COMPLETENESS_TONE[r.completeness] ?? "neutral"}>{t(`mobile.completeness.${r.completeness}` as TranslationKey)}</Badge> : "—"}</td>
              <td className={TD}>
                {r.feature ? (
                  <Link to={`/explorer/${r.feature.annotation_id}?feature=${r.feature.feature_id}`} className="text-arva-royal hover:underline dark:text-arva-cyan">
                    {r.feature.locus_tag ?? `#${r.feature.feature_id}`}
                  </Link>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
