import { ArrowDown, ArrowUp, Download, FlipHorizontal2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useChartTheme } from "@/components/charts/theme";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/form";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonResultRead } from "@/lib/comparative";
import { fmtNum } from "@/lib/format";
import { type FeatureRef, type RegionData, type RegionFeature, MARK_COLORS, regionFigure } from "@/lib/regions";
import { FigureCard, figureTheme } from "./FigureCard";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";

function anchorName(d: RegionData) {
  return d.anchor.gene ?? d.anchor.locus_tag ?? `${d.anchor.contig}:${d.anchor.start}-${d.anchor.end}`;
}

/** The Region Explorer result: the interactive gene-neighbourhood figure (reorder and flip tracks, labels, hover,
 * click for details), its exports, and the table of how each genome's homologous region was found. */
export function RegionView({ result }: { result: ComparisonResultRead }) {
  const t = useT();
  const theme = useChartTheme();
  const data = result.data as unknown as RegionData;
  const [order, setOrder] = useState<number[]>(() => data.tracks.map((_t, i) => i));
  const [flips, setFlips] = useState<Record<number, boolean>>({});
  const [labels, setLabels] = useState<"gene" | "locus" | "none">("gene");
  const [selected, setSelected] = useState<FeatureRef | null>(null);
  const s = data.settings;
  const caption = t("region.caption", {
    gene: anchorName(data), reference: data.tracks[0].label, flank: fmtNum(data.flank / 1000, 0),
    gid: s.groups.min_identity, gcov: s.groups.min_coverage, lid: s.links.min_identity, llen: s.links.min_length,
    tool: `${result.tool} ${result.tool_version}`,
  });
  const fig = useMemo(() => regionFigure(data, {
    order, flips, labels, theme: figureTheme(theme), caption, legendTitle: t("region.legend"),
    marksLegend: { amr: t("region.mark.amr"), virulence: t("region.mark.virulence"), mobile: t("region.mark.mobile") },
    linksLegend: t("region.linksLegend", { identity: s.links.min_identity }), notFound: t("region.notFound"),
    unnamedGroup: (id) => t("region.unnamedGroup", { id }),
    hitLabel: (identity) => t("region.hitLabel", { identity: fmtNum(identity, 1) }),
    kb: (v) => t("region.kb", { v: fmtNum(v, Math.abs(v) < 1 && v !== 0 ? 1 : 0) }),
  }), [data, order, flips, labels, theme, caption, s, t]);
  const move = (pos: number, by: number) => {
    const next = [...order];
    [next[pos], next[pos + by]] = [next[pos + by], next[pos]];
    setOrder(next);
  };
  const feature = (ref: FeatureRef): RegionFeature | undefined =>
    ref.feature != null ? data.tracks[ref.track].features.find((f) => f.id === ref.feature) : undefined;
  const groupName = (g: number | undefined) => (g == null ? null : data.groups.find((x) => x.id === g)?.name ?? t("region.unnamedGroup", { id: g }));
  const tooltip = (ref: FeatureRef) => {
    const tr = data.tracks[ref.track];
    if (ref.element != null) {
      const e = tr.elements[ref.element];
      return <span>{t(`region.mark.${e.kind}` as TranslationKey)}: {e.label} · {e.source}</span>;
    }
    const f = feature(ref);
    if (!f) return null;
    return (
      <div className="space-y-0.5">
        <p className="font-medium">{f.gene ? <i>{f.gene}</i> : f.locus_tag} <span className="text-muted-foreground">· {tr.label}</span></p>
        <p>{f.product ?? "—"}</p>
        <p className="text-muted-foreground">{f.start.toLocaleString()}–{f.end.toLocaleString()} ({f.strand}) · {t("region.group")}: {groupName(f.group) ?? "—"}</p>
        {(f.marks ?? []).map((m, i) => <p key={i} style={{ color: MARK_COLORS[m.kind] }}>{t(`region.mark.${m.kind}` as TranslationKey)}: {m.label}</p>)}
      </div>
    );
  };
  const chosen = selected ? feature(selected) : undefined;
  const chosenTrack = selected ? data.tracks[selected.track] : undefined;
  return (
    <div className="space-y-4">
      <FigureCard title={t("region.figureTitle", { gene: anchorName(data) })} subtitle={t("region.figureHint")} explain="region_explorer"
        fileStem={`ARVA_region_${anchorName(data).replace(/[^\w.-]+/g, "_")}`} fig={fig} tooltip={tooltip}
        onClick={(ref) => setSelected(ref.feature != null ? ref : null)}
        controls={
          <>
            <label className="flex items-center gap-2">
              {t("region.labels")}
              <Select value={labels} onChange={(e) => setLabels(e.target.value as typeof labels)} className="h-7 w-36 text-xs">
                <option value="gene">{t("region.labels.gene")}</option>
                <option value="locus">{t("region.labels.locus")}</option>
                <option value="none">{t("region.labels.none")}</option>
              </Select>
            </label>
            <a href={api.comparisonCsvUrl(result.id, "neighbourhood")} className={`inline-flex items-center gap-1 ${LINK}`}>
              <Download className="h-3.5 w-3.5" /> {t("region.csv")}
            </a>
          </>
        }
        footer={<p>{t("region.transferNote")}</p>}
      />
      {chosen && chosenTrack && (
        <Card>
          <CardHeader title={chosen.gene ?? chosen.locus_tag ?? `#${chosen.id}`} description={`${chosenTrack.label} · ${chosen.product ?? ""}`}
            action={<Button size="sm" variant="ghost" onClick={() => setSelected(null)} aria-label={t("common.close")}><X className="h-3.5 w-3.5" /></Button>} />
          <CardBody className="grid gap-x-6 gap-y-1 pt-3 text-xs sm:grid-cols-2">
            <p>{t("region.detail.locus")}: <span className="font-mono">{chosen.locus_tag ?? "—"}</span></p>
            <p>{t("region.detail.position")}: {chosenTrack.contig}:{chosen.start.toLocaleString()}–{chosen.end.toLocaleString()} ({chosen.strand})</p>
            <p>{t("region.detail.type")}: {chosen.type}{chosen.pseudo ? ` · ${t("region.detail.pseudo")}` : ""}{chosen.clipped ? ` · ${t("region.detail.clipped")}` : ""}</p>
            <p>{t("region.group")}: {groupName(chosen.group) ?? "—"}</p>
            {(chosen.marks ?? []).map((m, i) => (
              <p key={i}>{t(`region.mark.${m.kind}` as TranslationKey)}: {m.label} {m.detail ? `(${m.detail})` : ""} · {m.source}</p>
            ))}
            {chosenTrack.annotation_id && (
              <p className="sm:col-span-2">
                <Link to={`/explorer/${chosenTrack.annotation_id}?feature=${chosen.id}`} className={LINK}>{t("region.openExplorer")}</Link>
              </p>
            )}
          </CardBody>
        </Card>
      )}
      <Card>
        <CardHeader title={t("region.tracks")} description={t("region.tracksHint")} />
        <CardBody className="overflow-x-auto pt-3">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr>
                {["genome", "foundBy", "identity", "coverage", "copies", "window", "order"].map((k) => (
                  <th key={k} className="px-2 py-1.5 font-medium">{t(`region.col.${k}` as TranslationKey)}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {order.map((i, pos) => {
                const tr = data.tracks[i];
                return (
                  <tr key={i}>
                    <td className="px-2 py-1.5 font-medium">{tr.label}</td>
                    <td className="px-2 py-1.5">
                      <Badge tone={tr.located_by === "not_found" ? "danger" : "neutral"}>{t(`region.foundBy.${tr.located_by}` as TranslationKey)}</Badge>
                      {!tr.annotated && tr.located_by !== "not_found" && <span className="ml-1 text-muted-foreground">{t("region.unannotated")}</span>}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums">{tr.hit ? fmtNum(tr.hit.identity, 1) : tr.located_by === "anchor" ? "—" : ""}</td>
                    <td className="px-2 py-1.5 tabular-nums">{tr.hit ? fmtNum(tr.hit.query_coverage, 1) : ""}</td>
                    <td className="px-2 py-1.5 tabular-nums">{tr.copies > 1 ? tr.copies : ""}</td>
                    <td className="px-2 py-1.5">
                      {tr.contig ? `${tr.contig}:${tr.start!.toLocaleString()}–${tr.end!.toLocaleString()}` : "—"}
                      {(tr.clipped_left || tr.clipped_right) && <Badge tone="warning" className="ml-1">{t("region.clipped")}</Badge>}
                    </td>
                    <td className="flex gap-1 px-2 py-1">
                      <Button size="sm" variant="ghost" disabled={pos === 0} onClick={() => move(pos, -1)} aria-label={t("region.up")}><ArrowUp className="h-3.5 w-3.5" /></Button>
                      <Button size="sm" variant="ghost" disabled={pos === order.length - 1} onClick={() => move(pos, 1)} aria-label={t("region.down")}><ArrowDown className="h-3.5 w-3.5" /></Button>
                      <Button size="sm" variant={flips[i] ? "outline" : "ghost"} disabled={tr.located_by === "not_found"}
                        onClick={() => setFlips({ ...flips, [i]: !flips[i] })} aria-label={t("region.flip")} title={t("region.flip")}>
                        <FlipHorizontal2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">{t("region.reorderNote")}</p>
        </CardBody>
      </Card>
    </div>
  );
}
