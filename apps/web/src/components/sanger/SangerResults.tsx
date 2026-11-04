import { AlertTriangle, Globe } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useT } from "@/i18n";
import { fmtInt, fmtMax, fmtNum, fmtPct } from "@/lib/format";
import { messageText } from "@/lib/messages";
import { accessionOf, codedKey, cutDecimals, hitName, hitWhere, levelTone, outcomeTone, sourceText, sourceVersion, type AmrRow, type BriefRow, type IdentificationResults, type Interpretation16s, type SpeciesRow, type SuspectedComparison } from "@/lib/sanger";
import { cn } from "@/lib/utils";

/** A percentage cut, not rounded, to two decimals (lib/sanger cutDecimals), as the locale writes it. */
export const pct = (v: number | null | undefined) => (v == null ? "—" : fmtPct(cutDecimals(v), 2));

/** What ARVA's numbers say about what the user suspected: match, ambiguous or no match, with the best row of that
 * name, the best row overall and every better or tied row with another name (never hidden). Before any search has
 * finished there is no outcome; while searches run the outcome is marked provisional. */
export function SuspectedCard({ comparison }: { comparison: SuspectedComparison | null }) {
  const t = useT();
  if (!comparison) return null;
  const c = comparison;
  const done = c.outcome !== "not_searched";
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1">
            {t("sanger.suspected.title", { value: c.suspected })} <Explain id="sanger_suspected" compact />
          </span>
        }
        description={t(`sanger.suspected.kind.${c.kind}` as const)}
        action={<Badge tone={c.pending > 0 && done ? "neutral" : outcomeTone(c.outcome)}>{t(`sanger.outcome.${c.outcome}` as const)}</Badge>}
      />
      <CardBody className="space-y-2 text-sm">
        {c.pending > 0 && <p className="text-xs text-amber-700 dark:text-warning">{t("sanger.suspected.pending", { n: c.pending })}</p>}
        {!done ? (
          <p className="text-xs text-muted-foreground">{t("sanger.suspected.notSearched")}</p>
        ) : (
          <>
            {c.outcome !== "not_searched" && <p>{t(`sanger.outcome.text.${c.outcome}` as const, { value: c.suspected })}</p>}
            {c.matched_names && c.matched_names.length > 0 && c.matched_names.join(" ").toLowerCase() !== c.suspected.toLowerCase() && <p className="text-xs text-muted-foreground">{t("sanger.suspected.matched", { names: c.matched_names.join(", ") })}</p>}
            {c.reasons.map((r) => (
              <p key={r.code} className="text-xs text-muted-foreground">
                {t(...codedKey("sanger.suspectReason", { ...r, params: { ...r.params, identity: num(r.params.identity), coverage: num(r.params.coverage) } }))}
              </p>
            ))}
            {c.caveats.map((w) => (
              <p key={w.code} className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-warning">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {t(...codedKey("sanger.suspectCaveat", w))}
              </p>
            ))}
            <dl className="grid gap-2 text-xs sm:grid-cols-2">
              <RowFact label={t("sanger.suspected.bestOfName")} row={c.best_suspected ?? null} />
              <RowFact label={t("sanger.suspected.bestOverall")} row={c.best ?? null} />
            </dl>
            {(c.better_other_count ?? 0) > 0 && <OtherList title={t("sanger.suspected.better", { n: c.better_other_count ?? 0 })} rows={c.better_other ?? []} />}
            {(c.tied_other_count ?? 0) > 0 && <OtherList title={t("sanger.suspected.tied", { n: c.tied_other_count ?? 0 })} rows={c.tied_other ?? []} />}
            {(c.better_unnamed_count ?? 0) > 0 && <OtherList title={t("sanger.suspected.unnamed", { n: c.better_unnamed_count ?? 0 })} rows={c.better_unnamed ?? []} />}
            {c.thresholds && (
              <p className="text-[11px] text-muted-foreground">
                {t("sanger.suspected.thresholds", { identity: fmtMax(c.thresholds.min_identity, 2), coverage: fmtMax(c.thresholds.min_coverage, 2), window: fmtMax(c.thresholds.tie_window, 2) })} {c.source && t("sanger.cite", { source: c.source })}
              </p>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

const num = (v: unknown) => (typeof v === "number" ? fmtNum(cutDecimals(v), 2) : (v as string | null));

function RowFact({ label, row }: { label: string; row: BriefRow | null }) {
  const t = useT();
  return (
    <div className="rounded-lg border p-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{row ? <RowLine row={row} /> : t("sanger.suspected.none")}</dd>
    </div>
  );
}

function RowLine({ row }: { row: BriefRow }) {
  const t = useT();
  return (
    <span>
      <span className="font-medium">{hitName(row) ?? t("sanger.ranked.unnamed")}</span>{" "}
      {t("sanger.ranked.numbers", { identity: pct(row.identity), coverage: pct(row.query_coverage) })}{" "}
      <span className="text-muted-foreground">· {sourceText(row.source, t(`sanger.source.${row.source.source}` as const))}</span>
    </span>
  );
}

function OtherList({ title, rows }: { title: string; rows: BriefRow[] }) {
  return (
    <div className="text-xs">
      <p className="font-medium text-amber-700 dark:text-warning">{title}</p>
      <ul className="ml-4 list-disc">
        {rows.map((r, i) => (
          <li key={`${r.subject}-${i}`}>
            <RowLine row={r} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** ARVA's reading of the 16S hits with the CLSI MM18 criteria as quoted, every species above the species threshold
 * or within the separation listed, and the caveats with their sources. */
export function Interpretation16sCard({ interpretation, notSearched = false }: { interpretation: Interpretation16s | null; notSearched?: boolean }) {
  const t = useT();
  if (!interpretation) {
    // Searches ran but none against NCBI's 16S database: say so, so the 16S reading is not silently missing.
    if (!notSearched) return null;
    return (
      <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700 dark:text-warning" aria-hidden />
        <span>
          {t("sanger.s16.notSearched")}{" "}
          <Link to="/tools" className="text-arva-royal underline dark:text-arva-cyan">
            {t("sanger.s16.notSearchedLink")}
          </Link>
        </span>
      </p>
    );
  }
  const i = interpretation;
  const th = i.thresholds;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1">
            {t("sanger.s16.title")} <Explain id="sanger_16s" compact />
          </span>
        }
        description={t("sanger.s16.subtitle", { species: fmtMax(th.species_identity, 2), genus: fmtMax(th.genus_identity, 2), separation: fmtMax(th.species_separation, 2), coverage: fmtMax(th.min_query_coverage, 2), length: fmtInt(th.min_aligned_length) })}
        action={<Badge tone={levelTone(i.level)}>{t(`sanger.s16.level.${i.level}` as const)}</Badge>}
      />
      <CardBody className="space-y-2 text-sm">
        {i.level === "species" && <p>{t("sanger.s16.species", { species: i.species ?? "" })}</p>}
        {i.level === "genus" && <p>{t("sanger.s16.genus", { genus: i.genus ?? "" })}</p>}
        {i.level === "inconclusive" && <p>{t("sanger.s16.inconclusive")}</p>}
        {i.level === "no_hits" && <p>{t("sanger.s16.noHits")}</p>}
        {i.best && (
          <p className="text-xs">
            {t("sanger.s16.best", { species: i.best.species, identity: pct(i.best.identity), coverage: pct(i.best.query_coverage), accession: accessionOf(i.best.subject) })}
            {i.next_species && ` ${t("sanger.s16.next", { species: i.next_species.species, identity: pct(i.next_species.identity), separation: i.separation != null ? fmtNum(cutDecimals(i.separation, 3), 3) : "—" })}`}
          </p>
        )}
        {i.reasons.map((r) => (
          <p key={r.code} className="text-xs text-muted-foreground">
            {t(...codedKey("sanger.s16.reason", { ...r, params: { ...r.params, identity: num(r.params.identity), coverage: num(r.params.coverage), separation: num(r.params.separation) } }))}
          </p>
        ))}
        {i.above_species_threshold.length > 0 && <SpeciesList title={t("sanger.s16.above", { n: i.above_species_threshold.length, threshold: fmtMax(th.species_identity, 2) })} rows={i.above_species_threshold} />}
        {i.within_separation.length > 1 && <SpeciesList title={t("sanger.s16.within", { n: i.within_separation.length, separation: fmtMax(th.species_separation, 2) })} rows={i.within_separation} />}
        {i.caveats.map((c) => (
          <p key={c.code} className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {t(...codedKey("sanger.s16.caveat", c))}
          </p>
        ))}
        <details className="text-[11px] text-muted-foreground">
          <summary className="cursor-pointer">{t("sanger.s16.sources")}</summary>
          <ul className="ml-4 mt-1 list-disc space-y-0.5">
            {Object.entries(i.sources).map(([k, v]) => (
              <li key={k}>{v}</li>
            ))}
          </ul>
        </details>
      </CardBody>
    </Card>
  );
}

function SpeciesList({ title, rows }: { title: string; rows: SpeciesRow[] }) {
  const t = useT();
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, 10);
  return (
    <div className="text-xs">
      <p className="font-medium">{title}</p>
      <ul className="ml-4 list-disc">
        {shown.map((r) => (
          <li key={r.subject}>
            <span className="italic">{r.species}</span> {r.strain ?? ""} · {pct(r.identity)} · <span className="text-muted-foreground">{accessionOf(r.subject)}</span>
          </li>
        ))}
      </ul>
      {rows.length > shown.length && (
        <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[11px]" onClick={() => setAll(true)}>
          {t("sanger.showAll", { n: rows.length })}
        </Button>
      )}
    </div>
  );
}

/** Every hit of every searched source in one list, best first (bit score, identity, query coverage); rows tied with
 * the best are marked, never hidden. */
export function RankedTable({ results }: { results: IdentificationResults }) {
  const t = useT();
  const rows = results.ranked;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1">
            {t("sanger.ranked.title")} <Explain id="sanger_ranking" compact />
          </span>
        }
        description={t("sanger.ranked.subtitle", { n: fmtInt(results.ranked_count), shown: fmtInt(rows.length), tied: fmtInt(results.tied_with_best) })}
      />
      <CardBody className="pt-3">
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{results.identification.searched.length ? t("sanger.ranked.none") : t("sanger.ranked.notSearched")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-2 py-1.5 font-medium">{t("sanger.ranked.col.rank")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.ranked.col.name")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.ranked.col.identity")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.ranked.col.queryCoverage")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.ranked.col.subjectCoverage")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.ranked.col.aligned")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.ranked.col.match")}</th>
                  <th className="px-2 py-1.5 font-medium">{t("sanger.ranked.col.source")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.ranked.col.evalue")}</th>
                  <th className="px-2 py-1.5 text-right font-medium">{t("sanger.ranked.col.bitscore")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.rank}-${r.subject}`} className={cn("border-b align-top last:border-0", r.tied_with_best && "bg-arva-teal/5")}>
                    <td className="px-2 py-1.5 tabular-nums">
                      {r.rank}
                      {r.tied_with_best && (
                        <Badge tone="teal" className="ml-1">
                          {t("sanger.ranked.tied")}
                        </Badge>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className={cn("font-medium", r.species && !r.gene && "italic")}>{hitName(r) ?? t("sanger.ranked.unnamed")}</div>
                      {r.product && r.gene && <div className="text-[11px] text-muted-foreground">{r.product}</div>}
                      <div className="text-[11px] text-muted-foreground">{hitWhere(r)}</div>
                      {r.features && r.features.length > 1 && <div className="text-[11px] text-muted-foreground">{t("sanger.ranked.features", { names: r.features.map((f) => f.gene ?? f.product ?? f.locus_tag ?? "?").join(", ") })}</div>}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{pct(r.identity)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{pct(r.query_coverage)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums" title={r.subject_coverage == null && r.contig_coverage != null ? t("sanger.ranked.geneCoverageUnknown") : undefined}>
                      {pct(r.subject_coverage)}
                      {r.contig_coverage != null && <div className="text-[10px] text-muted-foreground">{t("sanger.ranked.contigCoverage", { value: pct(r.contig_coverage) })}</div>}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.aligned_length != null ? fmtInt(r.aligned_length) : "—"}</td>
                    <td className="px-2 py-1.5">
                      {r.kind ? t(`sanger.ranked.kind.${r.kind === "complete" || r.kind === "partial" || r.kind === "split" ? r.kind : "other"}` as const) : ""}
                      {r.copies != null && r.copies > 1 && <div className="text-[11px] text-muted-foreground">{t("sanger.ranked.copies", { n: r.copies })}</div>}
                    </td>
                    <td className="px-2 py-1.5">
                      {t(`sanger.source.${r.source.source}` as const)}
                      {sourceVersion(r.source) && <div className="text-[11px] text-muted-foreground">{sourceVersion(r.source)}</div>}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.evalue == null ? "—" : r.evalue === 0 ? "0" : r.evalue.toExponential(1)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{r.bitscore != null ? fmtMax(r.bitscore, 1) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[11px] text-muted-foreground">{t("sanger.ranked.note")}</p>
      </CardBody>
    </Card>
  );
}

/** AMRFinderPlus (translated nucleotide search) and spaTyper results, which are not ranked with the BLAST hits. */
export function OtherResults({ results }: { results: IdentificationResults }) {
  const t = useT();
  const amr = results.by_source.amrfinderplus;
  const spa = results.by_source.spa;
  if (!amr && !spa) return null;
  const amrRows = (amr?.rows ?? []) as AmrRow[];
  const amrCoverage = Number((amr?.details?.settings as { coverage_min?: number } | undefined)?.coverage_min ?? 0.1);
  const amrWarnings = ((amr?.details?.warnings ?? []) as { code: string; params: Record<string, string | number> }[]).filter((w) => w.code !== "genotype_not_phenotype" || amrRows.length > 0);
  const spaDetails = (spa?.details ?? {}) as { status?: string; spa_type?: string | null; repeats?: string | null; warnings?: { code: string; params: Record<string, string | number> }[] };
  return (
    <Card>
      <CardHeader title={t("sanger.other.title")} description={t("sanger.other.subtitle")} />
      <CardBody className="space-y-3 text-xs">
        {amr && (
          <div className="space-y-1">
            <h4 className="font-semibold">{t("sanger.source.amrfinderplus")}</h4>
            {amrRows.length === 0 ? (
              <p className="text-muted-foreground">{t("sanger.other.amrNone", { coverage: fmtMax(100 * amrCoverage, 2), length: fmtInt(results.identification.length), aa: fmtInt(Math.floor(results.identification.length / 3)) })}</p>
            ) : (
              <ul className="ml-4 list-disc">
                {amrRows.map((r, i) => (
                  <li key={`${r.element_symbol}-${i}`}>
                    <span className="font-medium">{r.element_symbol}</span> {r.element_name ?? ""} · {[r.type, r.subtype, r.class].filter(Boolean).join(" / ")} · {r.method} · {t("sanger.ranked.numbers", { identity: pct(r.identity), coverage: pct(r.coverage) })}
                  </li>
                ))}
              </ul>
            )}
            {amrWarnings.map((w) => (
              <p key={w.code} className="text-muted-foreground">
                {messageText(t, "amr.warning", { code: w.code, params: w.params, text: w.code })}
              </p>
            ))}
          </div>
        )}
        {spa && (
          <div className="space-y-1">
            <h4 className="font-semibold">{t("sanger.source.spa")}</h4>
            <p>
              {spaDetails.spa_type ? t("sanger.other.spaType", { type: spaDetails.spa_type, repeats: spaDetails.repeats ?? "—" }) : t("sanger.other.spaNone")}{" "}
              {spaDetails.status && <span className="text-muted-foreground">({messageText(t, "typing.status", { code: spaDetails.status, params: {}, text: spaDetails.status })})</span>}
            </p>
            {(spaDetails.warnings ?? []).map((w) => (
              <p key={w.code} className="text-muted-foreground">
                {messageText(t, "typing.warning", { code: w.code, params: w.params, text: w.code })}
              </p>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

/** NCBI's web BLAST, only if the user asks: the sequence is never sent by ARVA. After an explicit acknowledgement
 * the user can copy the sequence and open NCBI's BLAST page to paste it there. */
export function OnlineBlast({ sequence }: { sequence: string }) {
  const t = useT();
  const [ack, setAck] = useState(false);
  const [copied, setCopied] = useState<boolean | "failed">(false);
  return (
    <details className="rounded-xl border bg-surface p-4 text-xs">
      <summary className="flex cursor-pointer items-center gap-2 font-semibold">
        <Globe className="h-4 w-4 text-muted-foreground" aria-hidden /> {t("sanger.online.title")}
      </summary>
      <div className="mt-2 space-y-2">
        <p className="text-amber-700 dark:text-warning">{t("sanger.online.notice")}</p>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>{t("sanger.online.ack")}</span>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!ack}
            onClick={async () => {
              try {
                // Outside a secure context (plain http on a network address) navigator.clipboard is undefined.
                if (!navigator.clipboard) throw new Error("no clipboard");
                await navigator.clipboard.writeText(sequence);
                setCopied(true);
              } catch {
                setCopied("failed");
              }
            }}
          >
            {copied === true ? t("sanger.online.copied") : t("sanger.online.copy")}
          </Button>
          {ack ? (
            <a className="inline-flex h-8 items-center rounded-lg border px-3 text-xs font-medium hover:bg-muted" href="https://blast.ncbi.nlm.nih.gov/" target="_blank" rel="noopener noreferrer">
              {t("sanger.online.open")}
            </a>
          ) : (
            <span className="inline-flex h-8 items-center rounded-lg border px-3 text-xs font-medium opacity-50" aria-disabled="true">
              {t("sanger.online.open")}
            </span>
          )}
        </div>
        {copied === "failed" && (
          <div className="space-y-1">
            <p className="text-amber-700 dark:text-warning" role="status">
              {t("sanger.online.copyFailed")}
            </p>
            <textarea readOnly aria-label={t("sanger.online.copy")} className="h-24 w-full rounded-lg border bg-muted p-2 font-mono text-[11px]" value={sequence} onFocus={(e) => e.currentTarget.select()} />
          </div>
        )}
        <p className="text-muted-foreground">{t("sanger.online.never")}</p>
      </div>
    </details>
  );
}
