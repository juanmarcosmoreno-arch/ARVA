import { AlertTriangle, Download, Map as MapIcon } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useChartTheme } from "@/components/charts/theme";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Explain } from "@/components/guide/Explain";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonResultRead } from "@/lib/comparative";
import { fmtNum } from "@/lib/format";
import { type GeneData, type GeneMatch, matchRows, treeFigure } from "@/lib/regions";
import { FigureCard, figureTheme } from "./FigureCard";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";
const KIND_TONE = { complete: "success", partial: "warning", split: "blue" } as const;

/** A Custom Gene Investigation result: matches per genome (copies, partial and split matches, contig edges, the
 * annotated gene each overlaps, mobile elements nearby), the alignment export and the gene tree. `onNeighbourhood`
 * opens the Region Explorer on a match. */
export function GeneView({ result, onNeighbourhood }: {
  result: ComparisonResultRead;
  onNeighbourhood: (m: GeneMatch & { assembly_id: string; genome: string }, genomes: string[]) => void;
}) {
  const t = useT();
  const theme = useChartTheme();
  const data = result.data as unknown as GeneData;
  const rows = matchRows(data);
  const withMatches = data.genomes.filter((g) => g.matches.length).map((g) => g.assembly_id);
  const s = data.settings;
  const tree = data.tree;
  const fig = useMemo(() => (tree?.status === "built" && tree.tree ? treeFigure(tree.tree, {
    theme: figureTheme(theme), scaleUnit: t("gene.tree.scaleUnit"), supportMax: tree.support_max ?? 100,
    caption: t("gene.tree.caption", { method: tree.method === "iqtree" ? "IQ-TREE" : "FastTree", version: tree.tool_version ?? "",
      model: tree.model ?? "—", support: tree.support ?? "", query: data.query.name, n: tree.sequences }),
  }) : null), [tree, theme, t, data.query.name]);
  const files = Object.keys(result.files);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("gene.summaryTitle", { query: data.query.name })}
          description={t("gene.summaryLine", { molecule: t(`gene.molecule.${data.query.molecule}` as TranslationKey), length: data.query.length,
            program: data.program, task: data.task, identity: s.min_identity, coverage: s.min_coverage, complete: s.complete_coverage,
            evalue: String(s.evalue), gap: s.max_gap })} action={<Explain id="gene_investigation" compact />} />
        <CardBody className="overflow-x-auto pt-3">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr>{["genome", "matches", "complete", "partial", "split", "bestIdentity", "nearMobile"].map((k) => (
                <th key={k} className="px-2 py-1.5 font-medium">{t(`gene.col.${k}` as TranslationKey)}</th>
              ))}</tr>
            </thead>
            <tbody className="divide-y">
              {data.genomes.map((g) => {
                const count = (k: string) => g.matches.filter((m) => m.kind === k).length;
                return (
                  <tr key={g.assembly_id}>
                    <td className="px-2 py-1.5 font-medium">{g.label}</td>
                    <td className="px-2 py-1.5 tabular-nums">{g.matches.length || <span className="text-muted-foreground">{t("gene.absent")}</span>}</td>
                    <td className="px-2 py-1.5 tabular-nums">{count("complete") || ""}</td>
                    <td className="px-2 py-1.5 tabular-nums">{count("partial") || ""}</td>
                    <td className="px-2 py-1.5 tabular-nums">{count("split") || ""}</td>
                    <td className="px-2 py-1.5 tabular-nums">{g.matches.length ? fmtNum(Math.max(...g.matches.map((m) => m.identity)), 1) : ""}</td>
                    <td className="px-2 py-1.5 tabular-nums">{g.matches.filter((m) => m.mobile.length).length || ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 flex gap-1.5 text-xs text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />{t("gene.transferNote")}
          </p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("gene.hitsTitle")} description={t("gene.hitsHint", { distance: s.mobile_distance })}
          action={<a href={api.comparisonCsvUrl(result.id, "hits")} className={`inline-flex items-center gap-1 text-xs ${LINK}`}><Download className="h-3.5 w-3.5" /> CSV</a>} />
        <CardBody className="overflow-x-auto pt-3">
          {rows.length === 0 ? <p className="text-xs text-muted-foreground">{t("gene.noHits")}</p> : (
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr>{["genome", "copy", "kind", "location", "identity", "coverage", "gene", "mobile", ""].map((k) => (
                  <th key={k} className="px-2 py-1.5 font-medium">{k && t(`gene.col.${k}` as TranslationKey)}</th>
                ))}</tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((m) => (
                  <tr key={`${m.assembly_id}-${m.copy}`}>
                    <td className="px-2 py-1.5 font-medium">{m.genome}</td>
                    <td className="px-2 py-1.5 tabular-nums">{m.copy}</td>
                    <td className="px-2 py-1.5">
                      <Badge tone={KIND_TONE[m.kind]}>{t(`gene.kind.${m.kind}` as TranslationKey)}</Badge>
                      {m.pieces.length > 1 && <span className="ml-1 text-muted-foreground">{t("gene.pieces", { n: m.pieces.length })}</span>}
                      {m.at_contig_edge && <Badge tone="warning" className="ml-1">{t("gene.contigEdge")}</Badge>}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{m.contig}:{m.start.toLocaleString()}–{m.end.toLocaleString()} ({m.strand})
                      {m.on_plasmid_contig && <Badge tone="teal" className="ml-1">{t("gene.plasmidContig")}</Badge>}</td>
                    <td className="px-2 py-1.5 tabular-nums">{fmtNum(m.identity, 1)}</td>
                    <td className="px-2 py-1.5 tabular-nums">{fmtNum(m.query_coverage, 1)}</td>
                    <td className="px-2 py-1.5">
                      {m.feature ? (
                        <Link to={`/explorer/${m.feature.annotation_id}?feature=${m.feature.feature_id}`} className={LINK}>
                          {m.feature.gene ? <i>{m.feature.gene}</i> : m.feature.locus_tag}
                        </Link>
                      ) : <span className="text-muted-foreground">{m.annotation_id ? t("gene.noFeature") : t("gene.notAnnotated")}</span>}
                    </td>
                    <td className="px-2 py-1.5">
                      {m.mobile.length ? m.mobile.map((e, i) => (
                        <span key={i} className="mr-1 inline-block">{e.element} <span className="text-muted-foreground">({t(`mobile.category.${e.category}` as TranslationKey)}, {t("gene.distance", { bp: e.distance })})</span></span>
                      )) : ""}
                    </td>
                    <td className="px-2 py-1">
                      <Button size="sm" variant="ghost" onClick={() => onNeighbourhood(m, withMatches)} title={t("gene.neighbourhood")}>
                        <MapIcon className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>
      {data.alignment && (
        <Card>
          <CardHeader title={t("gene.alignmentTitle")} description={t(`gene.alignment.${data.alignment.status}` as TranslationKey, {
            n: data.alignment.sequences.length, columns: data.alignment.columns ?? 0, version: data.alignment.mafft_version ?? "",
            strategy: data.alignment.strategy === "linsi" ? "L-INS-i" : "FFT-NS-2" })} />
          <CardBody className="flex flex-wrap gap-3 pt-3 text-xs">
            {files.filter((f) => f.startsWith("alignment/alignment.fasta") || f.startsWith("tree/gene_tree.nwk") || f.endsWith(".iqtree") || f === "query.fna" || f === "query.faa").map((f) => (
              <a key={f} href={api.comparisonFileUrl(result.id, f)} className={`inline-flex items-center gap-1 ${LINK}`}><Download className="h-3.5 w-3.5" /> {f}</a>
            ))}
          </CardBody>
        </Card>
      )}
      {tree && tree.status !== "built" && (
        <p className="text-xs text-muted-foreground">{t(`gene.tree.${tree.status}` as TranslationKey, { n: tree.sequences })}</p>
      )}
      {fig && tree && (
        <FigureCard title={t("gene.tree.title", { query: data.query.name })} subtitle={t("gene.tree.hint")} explain="gene_tree"
          fileStem={`ARVA_gene_tree_${data.query.name.replace(/[^\w.-]+/g, "_")}`} fig={fig}
          footer={<p>{t("gene.tree.note")}</p>} />
      )}
    </div>
  );
}
