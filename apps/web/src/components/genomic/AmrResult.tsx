import { AlertTriangle, Download } from "lucide-react";
import { Link } from "react-router-dom";
import { MetricTile } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { type TranslationKey, useT } from "@/i18n";
import { KIND_TONE, kindText, sections, warningText } from "@/lib/amr";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtNum, shellJoin } from "@/lib/format";
import type { AmrHit, AmrRun, AnalysisJobDetail } from "@/lib/types";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

/** One AMRFinderPlus run as the tool reported it: what was searched (database, organism, --plus), the elements by
 * class, every element with its method, identity, coverage and place (partial and contig-end hits marked as such),
 * point mutations apart, and the reminder that a gene found is not a phenotype. */
export function AmrCard({ run, job }: { run: AmrRun; job?: AnalysisJobDetail }) {
  const t = useT();
  const p = run.parameters;
  const c = run.counts;
  const notSearched = t("amr.notSearched");
  const parts = sections(run.hits);
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {t("amr.cardTitle", { tool: `${run.tool} ${run.tool_version}` })}
            <Badge tone={run.hits.length ? "blue" : "neutral"}>{run.hits.length ? t("amr.elementsBadge", { n: run.hits.length }) : t("amr.noneFound")}</Badge>
          </span>
        }
        description={t("amr.cardSubtitle", { date: fmtDate(run.created_at), assembly: (run.assembly_id ?? "").slice(0, 8), db: `${run.database_name ?? ""} ${run.database_version ?? ""}`.trim() })}
        action={<Explain id="amr" compact />}
      />
      <CardBody className="space-y-4 pt-3">
        <p role="note" className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>
            {t("amr.disclaimer")} <Explain id="genotype_phenotype" compact />
          </span>
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label={t("amr.tile.amr")} value={fmtInt((c.AMR ?? 0) - (c.point_mutations ?? 0))} />
          <MetricTile label={t("amr.tile.point")} value={p.organism ? fmtInt(c.point_mutations ?? 0) : notSearched} sub={p.organism ? p.organism.replace(/_/g, " ") : t("amr.noOrganism")} explain="point_mutation" />
          <MetricTile label={t("amr.tile.virulence")} value={p.plus ? fmtInt(c.VIRULENCE ?? 0) : notSearched} />
          <MetricTile label={t("amr.tile.stress")} value={p.plus ? fmtInt(c.STRESS ?? 0) : notSearched} />
        </div>
        {run.by_class.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium">{t("amr.byClass")}</p>
            <div className="flex flex-wrap gap-1.5 text-xs">
              {run.by_class.map((x) => (
                <Badge key={x.class} tone="blue" title={x.elements.join(", ")}>
                  {x.class} · {fmtInt(x.count)}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {run.warnings.filter((w) => w.code !== "genotype_not_phenotype").length > 0 && (
          <ul role="status" className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
            {run.warnings
              .filter((w) => w.code !== "genotype_not_phenotype")
              .map((w, i) => (
                <li key={`${w.code}-${i}`} className="flex gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {warningText(t, w)}
                </li>
              ))}
          </ul>
        )}
        {!run.hits.length && <p className="text-sm text-muted-foreground">{t("amr.noneFoundText")}</p>}
        {parts.map((s) => (
          <section key={s.key} className="space-y-1.5" aria-label={t(`amr.section.${s.key}` as TranslationKey)}>
            <h4 className="flex items-center gap-1.5 text-xs font-semibold">
              {t(`amr.section.${s.key}` as TranslationKey)} <span className="font-normal text-muted-foreground">({fmtInt(s.hits.length)})</span>
              {s.key === "point" && <Explain id="point_mutation" compact />}
            </h4>
            <HitTable hits={s.hits} point={s.key === "point"} />
          </section>
        ))}
        {run.point_mutation_screen && (
          <p className="text-xs text-muted-foreground">
            {t("amr.screen", { genes: fmtInt(run.point_mutation_screen.genes.length), positions: fmtInt(run.point_mutation_screen.wildtype_positions) })}
          </p>
        )}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{t("amr.database")}</dt>
            <dd>
              {run.database_name} {run.database_version}
              {run.database_checksum && <code className="block break-all text-muted-foreground">{run.database_checksum}</code>}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("mlst.settings")}</dt>
            <dd>
              {t("amr.settingsLine", {
                mode: t(`amr.modeShort.${run.mode === "combined" ? "combined" : "nucleotide"}` as TranslationKey),
                ident: p.ident_min === -1 ? t("amr.curatedShort") : String(p.ident_min),
                cov: String(p.coverage_min ?? "?"),
                table: String(p.translation_table ?? "?"),
                plus: p.plus ? t("amr.plusOn") : t("amr.plusOff"),
              })}
              {run.organism_choice?.changed_by_user && run.organism_choice.proposed && (
                <span className="block text-muted-foreground">{t("amr.organismChanged", { proposed: run.organism_choice.proposed.replace(/_/g, " ") })}</span>
              )}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-2 text-xs">
          {(["report", "mutation_all", "nucleotide_hits", "protein_hits", "log"] as const)
            .filter((k) => run.files[k])
            .map((k) => (
              <a key={k} href={api.amrFileUrl(run.job_id, k)} className="inline-flex items-center gap-1 rounded border px-2 py-1 hover:bg-muted">
                <Download className="h-3.5 w-3.5" aria-hidden /> {t(`amr.file.${k}` as TranslationKey)}
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

export function MethodBadge({ hit }: { hit: Pick<AmrHit, "method" | "method_kind"> }) {
  const t = useT();
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge tone={KIND_TONE[hit.method_kind] ?? "neutral"}>{kindText(t, hit.method_kind)}</Badge>
      <code className="text-[10px] text-muted-foreground">{hit.method}</code>
    </span>
  );
}

const pct = (v: number | null) => (v == null ? "—" : fmtNum(v, 2));

function HitTable({ hits, point }: { hits: AmrHit[]; point: boolean }) {
  const t = useT();
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/50">
          <tr>
            <th className={TH}>{t(point ? "amr.col.mutation" : "amr.col.element")}</th>
            <th className={TH}>{t("amr.col.class")}</th>
            <th className={TH}>
              <span className="inline-flex items-center gap-1">
                {t("amr.col.method")} <Explain id="amr_methods" compact />
              </span>
            </th>
            <th className={TH}>{t("amr.col.identity")}</th>
            <th className={TH}>{t("amr.col.coverage")}</th>
            <th className={TH}>{t("amr.col.location")}</th>
            <th className={TH}>{t("amr.col.reference")}</th>
            <th className={TH}>{t("amr.col.feature")}</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {hits.map((h) => (
            <tr key={h.id} id={`amr-${h.id}`}>
              <td className={TD}>
                <span className="font-mono font-medium">{h.element_symbol}</span>
                {h.element_name && <span className="block max-w-xs text-muted-foreground">{h.element_name}</span>}
                {h.scope === "plus" && <Badge className="mt-0.5">{t("amr.plusBadge")}</Badge>}
              </td>
              <td className={TD}>
                {h.amr_class ?? (h.type === "VIRULENCE" ? t("amr.virulenceClass") : "—")}
                {h.amr_subclass && h.amr_subclass !== h.amr_class && <span className="block text-muted-foreground">{h.amr_subclass}</span>}
              </td>
              <td className={TD}>
                <MethodBadge hit={h} />
              </td>
              <td className={`${TD} tabular-nums`}>{pct(h.identity)}</td>
              <td className={`${TD} tabular-nums`}>{pct(h.coverage)}</td>
              <td className={`${TD} whitespace-nowrap font-mono`}>
                {h.assembly_contig ?? h.contig ?? "?"}:{h.start != null ? fmtInt(h.start) : "?"}–{h.stop != null ? fmtInt(h.stop) : "?"} ({h.strand ?? "?"})
              </td>
              <td className={TD}>
                {h.closest_accession ?? h.hmm_accession ?? "—"}
                {h.closest_name && h.closest_name !== h.element_name && <span className="block text-muted-foreground">{h.closest_name}</span>}
              </td>
              <td className={TD}>
                {h.feature ? (
                  <Link
                    to={`/explorer/${h.feature.annotation_id}?feature=${h.feature.feature_id}`}
                    className="text-arva-royal hover:underline dark:text-arva-cyan"
                    title={t(h.feature.how === "protein_id" ? "amr.linkProtein" : "amr.linkOverlap", { overlap: h.feature.overlap != null ? fmtNum(100 * h.feature.overlap, 0) : "?" })}
                  >
                    {h.feature.locus_tag ?? `#${h.feature.feature_id}`}
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
