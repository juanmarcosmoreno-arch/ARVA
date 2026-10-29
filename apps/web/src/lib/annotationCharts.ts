/**
 * Chart data for the annotation charts, from the API's counts (arva_core.annotation_stats), kept free of React so it
 * can be tested. Every series keeps one categorical slot for its whole life (colour follows the entity): the order
 * below is the slot order, so the common case (no small ORFs) uses the first three, validated all-pairs.
 */
import { fmtBp, fmtInt } from "./format";
import type { AnnotationCharts, DensityContig, LengthBin, LengthClass, StrandCounts } from "./types";

export const LENGTH_CLASSES: LengthClass[] = ["cds_characterised", "cds_hypothetical", "rna", "sorf"];
export const STRANDS = [
  { key: "+", field: "forward" },
  { key: "-", field: "reverse" },
  { key: ".", field: "unstranded" },
] as const;

/** A length bin as a range of whole bases in the interface's number format: "0–49", or "≥ 1,450" for the last, open bin. */
export function binLabel(b: Pick<LengthBin, "min" | "max">): string {
  return b.max == null ? `≥ ${fmtInt(b.min)}` : `${fmtInt(b.min)}–${fmtInt(b.max - 1)}`;
}

/** Length classes that have genes, in slot order, with each one's slot. */
export function lengthClasses(c: AnnotationCharts["lengths"]): { cls: LengthClass; slot: number }[] {
  return LENGTH_CLASSES.map((cls, slot) => ({ cls, slot })).filter(({ cls }) => c.classes[cls].n > 0);
}

export function lengthTable(c: AnnotationCharts["lengths"]): { labels: string[]; series: Record<LengthClass, number[]> } {
  const series = Object.fromEntries(LENGTH_CLASSES.map((k) => [k, c.bins.map((b) => b[k])])) as Record<LengthClass, number[]>;
  return { labels: c.bins.map(binLabel), series };
}

/** Strands that have genes on a sequence (the unstranded series only when some gene has no strand). */
export function densityStrands(d: DensityContig) {
  return STRANDS.map((s, slot) => ({ ...s, slot })).filter((s) => s.key !== "." || d.unstranded.some((v) => v > 0));
}

/** Genes per window as rows: window start–end, length when it is shorter than the others (the last), counts. */
export function densityRows(d: DensityContig, window: number): (string | number)[][] {
  return d.start.map((s, i) => {
    const len = d.end[i] - s + 1;
    return [`${fmtInt(s)}–${fmtInt(d.end[i])}${len < window ? ` (${fmtBp(len)})` : ""}`, d.forward[i], d.reverse[i], d.unstranded[i], d.total[i]];
  });
}

/** Summary of genes per window on a sequence, leaving out a shorter last window (it would read as low density). */
export function densitySummary(d: DensityContig, window: number): { min: number; median: number; max: number; windows: number } | null {
  const full = d.total.filter((_, i) => d.end[i] - d.start[i] + 1 === window);
  if (!full.length) return null;
  const sorted = [...full].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return { min: sorted[0], median: sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2, max: sorted[sorted.length - 1], windows: full.length };
}

/** The share of stranded genes on strand + (null without stranded genes). */
export const forwardShare = (s: StrandCounts) => (s["+"] + s["-"] ? s["+"] / (s["+"] + s["-"]) : null);

export const pct = (part: number, whole: number) => (whole > 0 ? (100 * part) / whole : null);

/** Hypothetical and characterised CDS per sequence, then the total, with the share of hypothetical ones. */
export function hypotheticalRows(h: AnnotationCharts["hypothetical"]): { name: string; characterised: number; hypothetical: number; share: number | null }[] {
  if (!h.total) return [];
  const row = (name: string, c: number, y: number) => ({ name, characterised: c, hypothetical: y, share: pct(y, c + y) });
  const rows = h.by_contig.filter((r) => r.characterised + r.hypothetical > 0).map((r) => row(r.contig_in_assembly, r.characterised, r.hypothetical));
  return rows.length > 1 ? [...rows, row("", h.total.characterised, h.total.hypothetical)] : rows;
}

/** COG categories with their share of the CDS that have any category. */
export function cogRows(c: AnnotationCharts["cog"]): { letter: string; name: string | null; cds: number; share: number | null }[] {
  return c.categories.map((k) => ({ ...k, share: pct(k.cds, c.cds_with_category) }));
}

/** Gene types with strand counts, in the order the API gives them. */
export function strandRows(s: AnnotationCharts["strand"]): { type: string; counts: StrandCounts; share: number | null }[] {
  return Object.entries(s.by_type).map(([type, counts]) => ({ type, counts, share: forwardShare(counts) }));
}
