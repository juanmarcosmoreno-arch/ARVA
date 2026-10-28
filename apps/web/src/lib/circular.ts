/**
 * Circular genome map geometry, kept free of React so it can be tested.
 *
 * Angles are in radians, 0 at 12 o'clock and growing clockwise, as on a clock face. A position is a continuous
 * 0-based coordinate: base n (1-based, as in GFF3) occupies [n - 1, n). Sequences sit around the circle in the order
 * given, each from its first base clockwise, separated by a small gap; a single sequence takes the whole circle, so a
 * feature across the origin of a circular sequence (start > end) is two arcs that meet at the top. In a circle of
 * several sequences, such a feature's two arcs lie at both ends of its own sequence's segment.
 */
import { featureGroup, type FeatureGroup, nice125 } from "./explorer";
import type { GenomeMap, MapFeature } from "./types";

export const TAU = 2 * Math.PI;

export interface Segment {
  id: string;
  name: string;
  length: number;
  /** Angle of position 0 and of the sequence end. */
  a0: number;
  a1: number;
}

export interface CircleLayout {
  segments: Segment[];
  radPerBase: number;
  gap: number;
}

/** Sequences around one circle with `gap` radians between neighbours (no gap for one sequence); all gaps together
 * take at most `maxGapShare` of the circle, so many short contigs still leave room for sequence. */
export function layoutCircle(seqs: { id: string; name: string; length: number }[], gap = 0.02, maxGapShare = 0.1): CircleLayout {
  const n = seqs.length;
  const total = seqs.reduce((sum, s) => sum + s.length, 0);
  const g = n > 1 ? Math.min(gap, (maxGapShare * TAU) / n) : 0;
  const radPerBase = total > 0 ? (TAU - n * g) / total : 0;
  let a = g / 2;
  const segments = seqs.map((s) => {
    const seg = { id: s.id, name: s.name, length: s.length, a0: a, a1: a + s.length * radPerBase };
    a = seg.a1 + g;
    return seg;
  });
  return { segments, radPerBase, gap: g };
}

export const angleAt = (layout: CircleLayout, seg: Segment, pos: number) => seg.a0 + pos * layout.radPerBase;

export const normalise = (a: number) => ((a % TAU) + TAU) % TAU;

/** The sequence and 0-based position at an angle, or null in a gap between sequences. */
export function locate(layout: CircleLayout, angle: number): { index: number; pos: number } | null {
  const a = normalise(angle);
  const index = layout.segments.findIndex((s) => a >= s.a0 && a < s.a1);
  if (index < 0) return null;
  const seg = layout.segments[index];
  return { index, pos: Math.min(seg.length - 1e-9, (a - seg.a0) / layout.radPerBase) };
}

export function polar(cx: number, cy: number, r: number, a: number): [number, number] {
  return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
}

/** The angle (0 at the top, clockwise) and distance of a point from the centre. */
export function pointerPolar(cx: number, cy: number, x: number, y: number): { angle: number; r: number } {
  return { angle: normalise(Math.atan2(x - cx, cy - y)), r: Math.hypot(x - cx, y - cy) };
}

const n2 = (v: number) => (Math.round(v * 100) / 100).toString();
const pt = (p: [number, number]) => `${n2(p[0])},${n2(p[1])}`;

/**
 * An annular sector between radii r0 < r1 from angle a0 to a1, as one closed path drawn outer edge clockwise and
 * inner edge anticlockwise, so that sectors joined into one path fill under the nonzero rule even where they overlap.
 * A sweep of a full turn is a whole ring (two half arcs per edge, since one SVG arc cannot draw a full circle).
 */
export function sectorPath(cx: number, cy: number, r0: number, r1: number, a0: number, a1: number): string {
  const sweep = a1 - a0;
  if (sweep <= 0) return "";
  if (sweep >= TAU - 1e-9) {
    const o = [polar(cx, cy, r1, a0), polar(cx, cy, r1, a0 + Math.PI)];
    const outer = `M${pt(o[0])}A${n2(r1)},${n2(r1)} 0 0 1 ${pt(o[1])}A${n2(r1)},${n2(r1)} 0 0 1 ${pt(o[0])}Z`;
    if (r0 <= 0) return outer;
    const i = [polar(cx, cy, r0, a0), polar(cx, cy, r0, a0 + Math.PI)];
    return `${outer}M${pt(i[0])}A${n2(r0)},${n2(r0)} 0 0 0 ${pt(i[1])}A${n2(r0)},${n2(r0)} 0 0 0 ${pt(i[0])}Z`;
  }
  const large = sweep > Math.PI ? 1 : 0;
  return (
    `M${pt(polar(cx, cy, r1, a0))}A${n2(r1)},${n2(r1)} 0 ${large} 1 ${pt(polar(cx, cy, r1, a1))}` +
    `L${pt(polar(cx, cy, r0, a1))}A${n2(r0)},${n2(r0)} 0 ${large} 0 ${pt(polar(cx, cy, r0, a0))}Z`
  );
}

// --- Features ---------------------------------------------------------------------------------------------------

export interface ArcPiece {
  feature: MapFeature;
  seg: number;
  a0: number;
  a1: number;
}

/** Each feature on the circle as one arc, or two for a feature across the origin (start..end of its sequence, then
 * its first base..end). Features of sequences not on the circle are left out. */
export function arcPieces(features: MapFeature[], layout: CircleLayout): ArcPiece[] {
  const index = new Map(layout.segments.map((s, i) => [s.id, i]));
  const out: ArcPiece[] = [];
  for (const f of features) {
    const i = index.get(f.contig);
    if (i === undefined) continue;
    const seg = layout.segments[i];
    const spans: [number, number][] =
      f.edge && f.start > f.end ? [[f.start - 1, seg.length], [0, f.end]] : [[Math.min(f.start, f.end) - 1, Math.max(f.start, f.end)]];
    for (const [lo, hi] of spans) out.push({ feature: f, seg: i, a0: angleAt(layout, seg, lo), a1: angleAt(layout, seg, hi) });
  }
  return out;
}

/**
 * Arcs to draw at a given resolution: each at least `minWidth` radians wide (widened about its middle, kept inside
 * its sequence), and neighbours of the same sequence closer than `minGap` merged, so a whole genome needs a few
 * hundred sectors instead of one per gene.
 */
export function mergeArcs(pieces: Pick<ArcPiece, "seg" | "a0" | "a1">[], layout: CircleLayout, minGap: number, minWidth: number): [number, number][] {
  const widened = pieces.map((p) => {
    const seg = layout.segments[p.seg];
    let a0 = p.a0;
    let a1 = p.a1;
    if (a1 - a0 < minWidth) {
      const mid = (a0 + a1) / 2;
      a0 = Math.max(seg.a0, mid - minWidth / 2);
      a1 = Math.min(seg.a1, a0 + minWidth);
    }
    return { seg: p.seg, a0, a1 };
  });
  widened.sort((x, y) => x.seg - y.seg || x.a0 - y.a0);
  const out: [number, number][] = [];
  let lastSeg = -1;
  for (const p of widened) {
    const last = out[out.length - 1];
    if (last && p.seg === lastSeg && p.a0 - last[1] <= minGap) last[1] = Math.max(last[1], p.a1);
    else out.push([p.a0, p.a1]);
    lastSeg = p.seg;
  }
  return out;
}

export type ArcClass = "coding" | "hypothetical" | FeatureGroup;

/** How a feature is drawn: protein-coding features with a function, hypothetical proteins (lighter), RNA genes,
 * other elements and assembly gaps. */
export function arcClass(f: Pick<MapFeature, "type" | "hypothetical">): ArcClass {
  const g = featureGroup(f.type);
  return g === "coding" && f.hypothetical ? "hypothetical" : g;
}

export const strandRing = (strand: string): "forward" | "reverse" | "backbone" => (strand === "+" ? "forward" : strand === "-" ? "reverse" : "backbone");

/** The piece nearest the angle within `tolerance` radians (0 when the angle lies on it); on a tie, the shortest. */
export function pieceAt(pieces: ArcPiece[], angle: number, tolerance: number): ArcPiece | null {
  const a = normalise(angle);
  let best: ArcPiece | null = null;
  let bestD = Infinity;
  for (const p of pieces) {
    let d = 0;
    if (a < p.a0 || a > p.a1) {
      const d0 = Math.abs(a - p.a0);
      const d1 = Math.abs(a - p.a1);
      d = Math.min(d0, TAU - d0, d1, TAU - d1);
    }
    if (d > tolerance) continue;
    if (d < bestD || (d === bestD && best && p.a1 - p.a0 < best.a1 - best.a0)) {
      best = p;
      bestD = d;
    }
  }
  return best;
}

// --- Value rings --------------------------------------------------------------------------------------------------

export interface Bar {
  a0: number;
  a1: number;
  value: number;
}

/** Windows (1-based inclusive starts and ends) of one sequence as bars, leaving out windows without a value. */
export function windowBars(layout: CircleLayout, segIndex: number, starts: number[], ends: number[], values: (number | null)[], baseline = 0): Bar[] {
  const seg = layout.segments[segIndex];
  const out: Bar[] = [];
  starts.forEach((s, i) => {
    const v = values[i];
    if (v == null) return;
    out.push({ a0: angleAt(layout, seg, s - 1), a1: angleAt(layout, seg, ends[i]), value: v - baseline });
  });
  return out;
}

/** The largest absolute value of the bars (at least `floor`), so that a ring's scale fits what it shows. */
export const barScale = (bars: Bar[], floor: number) => bars.reduce((m, b) => Math.max(m, Math.abs(b.value)), floor);

/**
 * Bars as two paths (values above and below zero), each bar a sector from rBase outwards by value / scale * height
 * (inwards for negative values), clipped to one height either way.
 */
export function barPaths(cx: number, cy: number, bars: Bar[], rBase: number, height: number, scale: number): { pos: string; neg: string } {
  let pos = "";
  let neg = "";
  for (const b of bars) {
    const h = Math.max(-1, Math.min(1, b.value / (scale || 1))) * height;
    if (h > 0) pos += sectorPath(cx, cy, rBase, rBase + h, b.a0, b.a1);
    else if (h < 0) neg += sectorPath(cx, cy, rBase + h, rBase, b.a0, b.a1);
  }
  return { pos, neg };
}

/** The window holding a 1-based position (binary search over sorted, non-overlapping windows), or -1. */
export function windowAt(starts: number[], ends: number[], position: number): number {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ends[mid] < position) lo = mid + 1;
    else if (starts[mid] > position) hi = mid - 1;
    else return mid;
  }
  return -1;
}

// --- Rings, ticks, labels -----------------------------------------------------------------------------------------

/** Radii of rings listed from the outside in, each `thickness` px with `gap` px between them, scaled down together
 * when they do not fit between `outer` and `inner`. */
export function ringRadii<K extends string>(rings: { id: K; thickness: number }[], outer: number, inner: number, gap = 4): Record<K, { r0: number; r1: number }> {
  const need = rings.reduce((s, r) => s + r.thickness, 0) + gap * Math.max(0, rings.length - 1);
  const k = need > 0 ? Math.min(1, Math.max(0, outer - inner) / need) : 1;
  const out = {} as Record<K, { r0: number; r1: number }>;
  let r = outer;
  for (const ring of rings) {
    out[ring.id] = { r0: r - ring.thickness * k, r1: r };
    r -= (ring.thickness + gap) * k;
  }
  return out;
}

/** Ticks of a sequence at multiples of a 1-2-5 number of bases, about `minPx` apart at radius `r` (not at 0, which
 * is marked as the sequence start). */
export function segmentTicks(layout: CircleLayout, seg: Segment, r: number, minPx = 80): { step: number; positions: number[] } {
  const pxPerBase = layout.radPerBase * r;
  const step = nice125(minPx / Math.max(pxPerBase, 1e-12));
  const positions: number[] = [];
  for (let p = step; p < seg.length; p += step) positions.push(p);
  return { step, positions };
}

/** Whether a sequence's arc at radius r is long enough (in px) to carry its name. */
export const hasRoomForLabel = (seg: Segment, r: number, minPx = 40) => (seg.a1 - seg.a0) * r >= minPx;

/** Text anchor for a label at an angle, so labels on the left half end at the circle and those on the right start
 * there. */
export const labelAnchor = (a: number): "start" | "middle" | "end" => {
  const x = Math.sin(normalise(a));
  return Math.abs(x) < 0.15 ? "middle" : x > 0 ? "start" : "end";
};

// --- Custom ring, navigation --------------------------------------------------------------------------------------

export type CustomCriterion = { kind: "type"; type: string } | { kind: "pseudo" } | { kind: "text"; q: string };

/** Features for the custom ring: of one type, pseudogenes, or with the text in the locus tag, the annotator's ID,
 * the gene name or the product (case-insensitive). */
export function matchFeatures(features: MapFeature[], c: CustomCriterion | null): MapFeature[] {
  if (!c) return [];
  if (c.kind === "type") return features.filter((f) => f.type === c.type);
  if (c.kind === "pseudo") return features.filter((f) => f.pseudo);
  const q = c.q.trim().toLowerCase();
  if (!q) return [];
  return features.filter((f) => [f.locus_tag, f.tool_id, f.gene, f.product].some((v) => v != null && v.toLowerCase().includes(q)));
}

/** The feature after (1) or before (-1) `current` in map order (sequence order, then start), wrapping round. */
export function stepFeature(features: MapFeature[], order: string[], current: number | null, dir: 1 | -1): MapFeature | null {
  if (!features.length) return null;
  const rank = new Map(order.map((id, i) => [id, i]));
  const sorted = [...features].sort(
    (a, b) => (rank.get(a.contig) ?? 0) - (rank.get(b.contig) ?? 0) || Math.min(a.start, a.end) - Math.min(b.start, b.end) || a.id - b.id,
  );
  const i = sorted.findIndex((f) => f.id === current);
  if (i < 0) return dir === 1 ? sorted[0] : sorted[sorted.length - 1];
  return sorted[(i + dir + sorted.length) % sorted.length];
}

// --- One circle ---------------------------------------------------------------------------------------------------

export interface CircleModel {
  map: GenomeMap;
  layout: CircleLayout;
  rings: Record<"forward" | "reverse" | "backbone", ArcPiece[]>;
  custom: ArcPiece[];
  gc: Bar[];
  skew: Bar[];
  coverage: Bar[];
  scales: { gc: number; skew: number; coverage: number };
}

/** Everything one circle draws from a map: the sequences' segments, feature arcs by ring, the custom ring's arcs,
 * GC as the difference from the drawn sequences' GC, GC skew and read depth as bars, and each value ring's scale. */
export function circleModel(map: GenomeMap, custom: MapFeature[]): CircleModel {
  const layout = layoutCircle(map.sequences.map((s) => ({ id: s.contig, name: s.contig_in_assembly, length: s.length })));
  const pieces = arcPieces(map.features, layout);
  const rings: CircleModel["rings"] = { forward: [], reverse: [], backbone: [] };
  for (const p of pieces) rings[strandRing(p.feature.strand)].push(p);
  const mean = map.gc.genome_gc ?? 0;
  const gc = map.sequences.flatMap((s, i) => windowBars(layout, i, s.gc.start, s.gc.end, s.gc.gc, mean));
  const skew = map.sequences.flatMap((s, i) => windowBars(layout, i, s.gc.start, s.gc.end, s.gc.skew));
  const coverage = map.sequences.flatMap((s, i) => (s.coverage.available ? windowBars(layout, i, s.coverage.start, s.coverage.end, s.coverage.mean) : []));
  return {
    map,
    layout,
    rings,
    custom: arcPieces(custom, layout),
    gc,
    skew,
    coverage,
    scales: { gc: barScale(gc, 0.01), skew: barScale(skew, 0.05), coverage: barScale(coverage, 1) },
  };
}
