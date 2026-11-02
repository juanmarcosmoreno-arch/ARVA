import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtInt } from "@/lib/format";
import { type MobilomeAssembly, type PlacedGene, relationKey } from "@/lib/variants";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";
const WINDOW_DEFAULT = 10_000;
const TOOL_NAMES: Record<string, string> = { isescan: "ISEScan", mobsuite: "MOB-suite", integronfinder: "IntegronFinder", genomad: "geNomad" };

function GeneChips({ genes }: { genes: PlacedGene[] }) {
  const t = useT();
  if (!genes.length) return <span className="text-muted-foreground">{t("mobilome.noGenes")}</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {genes.map((g) => (
        <Badge key={`${g.source}:${g.gene}:${g.contig}:${g.start}`} tone={g.type === "AMR" ? "danger" : g.type === "VIRULENCE" ? "warning" : "neutral"}
          title={`${g.name ?? g.gene} · ${t(`mobilome.source.${g.source}` as TranslationKey)} · ${g.contig}:${fmtInt(g.start)}–${fmtInt(g.end)}`}>
          {g.gene} · {t(relationKey(g.relation))}{g.distance ? ` ${fmtBases(g.distance)}` : ""}
        </Badge>
      ))}
    </span>
  );
}

function AssemblyMobilome({ a }: { a: MobilomeAssembly }) {
  const t = useT();
  const c = a.counts;
  const searched = Object.entries(a.runs).filter(([, v]) => v).map(([k]) => t(`mobile.method.${k}` as TranslationKey));
  const genes = Object.entries(a.gene_runs).filter(([, v]) => v).map(([k]) => t(`mobilome.source.${k}` as TranslationKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t("mobilome.assemblyLine", { assembler: a.assembler, id: a.assembly_id.slice(0, 8), methods: searched.join(", ") || "—", genes: genes.join(", ") || t("mobilome.noGeneRuns") })}
      </p>
      <div className="flex flex-wrap gap-2 text-xs">
        {(["plasmids", "insertion_sequences", "repetitive_elements", "integrons", "viruses", "genes_on_plasmids", "genes_with_elements", "amr_on_plasmids"] as const).map((k) => (
          <span key={k} className="rounded-md border px-2 py-1"><span className="font-semibold tabular-nums">{fmtInt(c[k] ?? 0)}</span> {t(`mobilome.count.${k}` as TranslationKey)}</span>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50">
            <tr>
              <th className={TH}>{t("mobilome.col.kind")}</th>
              <th className={TH}>{t("mobilome.col.element")}</th>
              <th className={TH}>{t("mobilome.col.location")}</th>
              <th className={TH}>{t("mobilome.col.type")}</th>
              <th className={TH}>{t("mobilome.col.genes")}</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {a.plasmids.map((p) => (
              <tr key={`p:${p.id}`}>
                <td className={TD}>{t("mobilome.kind.plasmid")}</td>
                <td className={`${TD} font-medium`}>{p.id}</td>
                <td className={TD}>{p.contigs.join(", ")}{p.size ? ` · ${fmtBases(p.size)}` : ""}</td>
                <td className={TD}>{[(p.rep_types ?? []).join(", "), p.predicted_mobility].filter(Boolean).join(" · ")}</td>
                <td className={TD}><GeneChips genes={p.genes} /></td>
              </tr>
            ))}
            {a.elements.map((e, i) => (
              <tr key={`e:${i}`}>
                <td className={TD}>{t(`mobilome.kind.${e.category}` as TranslationKey)} <span className="text-muted-foreground">({TOOL_NAMES[e.tool] ?? e.tool})</span></td>
                <td className={`${TD} font-medium`}>{e.element ?? "—"}</td>
                <td className={TD}>{e.contig}{e.start != null ? `:${fmtInt(e.start)}–${fmtInt(e.end ?? 0)}` : ` (${t("mobilome.wholeContig")})`}{e.plasmid ? ` · ${t("mobilome.onPlasmid", { id: e.plasmid })}` : ""}</td>
                <td className={TD}>{[e.element_type, e.completeness].filter(Boolean).join(" · ")}</td>
                <td className={TD}><GeneChips genes={e.genes} /></td>
              </tr>
            ))}
            {!a.plasmids.length && !a.elements.length && (
              <tr><td className={TD} colSpan={5}>{t("mobilome.nothing")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The sample's mobilome in one place: plasmids (MOB-suite), IS elements, integrons and geNomad's calls of its most
 * recent runs, each with the resistance and virulence genes placed on it by coordinates (inside, near within the
 * chosen distance, or on the plasmid's contigs). Proximity is not evidence of transfer. */
export function MobilomeSection({ sampleId }: { sampleId: string }) {
  const t = useT();
  const [window, setWindow] = useState(WINDOW_DEFAULT);
  const m = useQuery({ queryKey: ["mobilome", sampleId, window], queryFn: () => api.sampleMobilome(sampleId, window) });
  if (m.error) return <ErrorNote error={m.error} />;
  if (!m.data?.assemblies.length) return <p className="text-sm text-muted-foreground">{t("mobilome.empty")}</p>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("mobilome.window")} hint={t("mobilome.windowHint")}>
          <Input type="number" min={0} max={200000} step={1000} value={window} onChange={(e) => setWindow(Math.max(0, Math.min(200_000, Number(e.target.value) || 0)))} className="w-40" />
        </Field>
        <p className="max-w-xl text-xs text-amber-700 dark:text-warning">{t("mobilome.caveat")}</p>
      </div>
      {m.data.assemblies.map((a) => <AssemblyMobilome key={a.assembly_id} a={a} />)}
    </div>
  );
}

/** Per sample of the project: the consolidated mobilome counts of its most recently searched assembly and the genes
 * found on plasmids or inside mobile elements (by name). */
export function ProjectMobilome({ projectId }: { projectId: string }) {
  const t = useT();
  const o = useQuery({ queryKey: ["projectMobilome", projectId], queryFn: () => api.projectMobilome(projectId) });
  if (o.error) return <ErrorNote error={o.error} />;
  const rows = o.data?.samples ?? [];
  if (!rows.some((r) => r.counts)) return null;
  return (
    <Card className="mt-6 min-w-0" id="project-mobilome">
      <CardHeader title={t("mobilome.projectTitle")} description={t("mobilome.projectSub", { window: fmtBases(o.data?.window ?? WINDOW_DEFAULT) })} action={<Explain id="mobilome" compact />} />
      <CardBody className="pt-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className={TH}>{t("projectMlst.sample")}</th>
                <th className={TH}>{t("mobilome.count.plasmids")}</th>
                <th className={TH}>{t("mobilome.col.replicons")}</th>
                <th className={TH}>{t("mobilome.count.insertion_sequences")}</th>
                <th className={TH}>{t("mobilome.count.integrons")}</th>
                <th className={TH}>{t("mobilome.col.plasmidGenes")}</th>
                <th className={TH}>{t("mobilome.col.elementGenes")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.sample_id}>
                  <td className={TD}>
                    <Link to={`/samples/${r.sample_id}?tab=genomic`} className="font-medium text-arva-royal hover:underline dark:text-arva-cyan">{r.sample_code}</Link>
                  </td>
                  {r.counts ? (
                    <>
                      <td className={TD}>{fmtInt(r.counts.plasmids ?? 0)}</td>
                      <td className={TD}>{r.replicon_types.join(", ") || "—"}</td>
                      <td className={TD}>{fmtInt(r.counts.insertion_sequences ?? 0)}</td>
                      <td className={TD}>{fmtInt(r.counts.integrons ?? 0)}</td>
                      <td className={TD}>{r.plasmid_genes.join(", ") || "—"}</td>
                      <td className={TD}>{r.element_genes.join(", ") || "—"}</td>
                    </>
                  ) : (
                    <td className={`${TD} text-muted-foreground`} colSpan={6}>{t("mobile.notSearchedShort")}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("mobilome.caveat")}</p>
      </CardBody>
    </Card>
  );
}
