/**
 * Genome Explorer geometry and parsing, kept free of React so it can be tested.
 *
 * A view is a continuous range [from, to) in 0-based sequence coordinates: base n (1-based, as in GFF3) occupies
 * [n - 1, n). Pixels map linearly onto the view. Features are drawn as "pieces": a feature across the origin of a
 * circular sequence (edge, start > end) is two pieces, start..length and 1..end.
 */
import type { AnnotationSequence, AssemblyContig, FeatureLayoutItem } from "./types";

export interface View {
  from: number;
  to: number;
}

export const MIN_SPAN = 30;
export const MAX_GLYPHS = 600;
/** Pixels per base needed to draw base letters. */
export const BASE_PX = 9;
export const MAX_POINTS = 5000;
export const LANES_PER_STRAND = 3;
/** Feature types that are genes, for intergenic regions (regulatory regions, CRISPR arrays, origins and gaps are
 * not genes, so they lie in intergenic space). */
export const GENE_TYPES = new Set(["cds", "sorf", "trna", "tmrna", "rrna", "ncrna"]);

export type FeatureGroup = "coding" | "rna" | "element" | "gap";

export function featureGroup(type: string): FeatureGroup {
  if (type === "cds" || type === "sorf") return "coding";
  if (type === "trna" || type === "tmrna" || type === "rrna" || type === "ncrna") return "rna";
  if (type === "gap") return "gap";
  return "element";
}

export const span = (v: View) => v.to - v.from;

/** The view moved inside [0, length], at least MIN_SPAN bases wide (or the whole sequence), centred where asked. */
export function clampView(v: View, length: number): View {
  const width = Math.min(length, Math.max(Math.min(MIN_SPAN, length), span(v)));
  const centre = (v.from + v.to) / 2;
  const from = Math.min(Math.max(0, centre - width / 2), length - width);
  return { from, to: from + width };
}

/** Zoom by `factor` (< 1 zooms in) keeping the sequence position `anchor` at the same place on screen. */
export function zoomView(v: View, factor: number, anchor: number, length: number): View {
  const width = Math.min(length, Math.max(Math.min(MIN_SPAN, length), span(v) * factor));
  const ratio = span(v) > 0 ? (anchor - v.from) / span(v) : 0.5;
  let from = anchor - ratio * width;
  from = Math.min(Math.max(0, from), length - width);
  return { from, to: from + width };
}

export function panView(v: View, delta: number, length: number): View {
  const from = Math.min(Math.max(0, v.from + delta), length - span(v));
  return { from, to: from + span(v) };
}

export const toX = (pos: number, v: View, width: number) => ((pos - v.from) / span(v)) * width;
export const toPos = (x: number, v: View, width: number) => v.from + (x / width) * span(v);

/** 1-based inclusive bases a view shows (partly shown bases included). */
export function regionOf(v: View): { start: number; end: number } {
  return { start: Math.floor(v.from) + 1, end: Math.max(Math.floor(v.from) + 1, Math.ceil(v.to)) };
}

export const viewOf = (start: number, end: number): View => ({ from: start - 1, to: end });

/** The smallest 1-2-5 number not below x. */
export function nice125(x: number): number {
  if (x <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(x));
  for (const m of [1, 2, 5, 10]) if (m * magnitude >= x) return m * magnitude;
  return 10 * magnitude;
}

/** Ruler ticks at multiples of a 1-2-5 step, about `minPx` apart; each tick marks the centre of base `pos`. */
export function ticks(v: View, width: number, minPx = 90): { step: number; positions: number[] } {
  const step = nice125((span(v) * minPx) / Math.max(width, 1));
  const positions: number[] = [];
  for (let p = Math.max(step, Math.ceil((v.from + 0.5) / step) * step); p - 0.5 <= v.to; p += step) positions.push(p);
  return { step, positions };
}

export function formatPosition(pos: number, step: number): string {
  if (step >= 1_000_000) return `${trim(pos / 1_000_000)} Mb`;
  if (step >= 1_000) return `${trim(pos / 1_000)} kb`;
  return pos.toLocaleString("en-US");
}

const trim = (x: number) => String(Math.round(x * 1000) / 1000);

/**
 * The track request for a view: a tile of a power-of-two length at least twice the view, aligned to half its
 * length, so panning within a tile and small zooms reuse the same request; about two points per pixel of the view.
 */
export function trackRequest(v: View, length: number, width: number): { start: number; end: number; bins: number } {
  const tile = 2 ** Math.ceil(Math.log2(Math.max(2 * span(v), 2)));
  const bins = Math.max(10, Math.min(MAX_POINTS, Math.round(2 * width)));
  if (tile >= length) return { start: 1, end: length, bins };
  const half = tile / 2;
  const start0 = Math.min(Math.floor(v.from / half) * half, length - tile);
  return { start: start0 + 1, end: start0 + tile, bins };
}

/** Whether a tile (1-based inclusive) covers the view. */
export const covers = (tile: { start: number; end: number }, v: View) => tile.start - 1 <= v.from && tile.end >= v.to;

// --- Features -------------------------------------------------------------------------------------------------

export interface Piece {
  feature: FeatureLayoutItem;
  start: number;
  end: number;
  /** This piece holds the feature's 3' end on its strand (where the arrow points). */
  head: boolean;
  lane: number;
}

export type StrandGroup = "+" | "-" | ".";

export const strandGroup = (strand: string): StrandGroup => (strand === "+" || strand === "-" ? strand : ".");

export function piecesOf(features: FeatureLayoutItem[], length: number): Piece[] {
  const out: Piece[] = [];
  for (const f of features) {
    if (f.edge && f.start > f.end) {
      out.push({ feature: f, start: f.start, end: length, head: f.strand === "-", lane: 0 });
      out.push({ feature: f, start: 1, end: f.end, head: f.strand !== "-", lane: 0 });
    } else {
      out.push({ feature: f, start: Math.min(f.start, f.end), end: Math.max(f.start, f.end), head: true, lane: 0 });
    }
  }
  return out;
}

/** Lanes per strand group: each piece goes to the first lane whose last piece ends before it starts; when every
 * lane is taken it goes to the lane that frees up first (and overlaps there). Returns lanes used per group. */
export function assignLanes(pieces: Piece[], maxLanes = LANES_PER_STRAND): Record<StrandGroup, number> {
  const used: Record<StrandGroup, number> = { "+": 0, "-": 0, ".": 0 };
  const ends: Record<StrandGroup, number[]> = { "+": [], "-": [], ".": [] };
  const sorted = [...pieces].sort((a, b) => a.start - b.start || b.end - a.end);
  for (const p of sorted) {
    const g = strandGroup(p.feature.strand);
    const lanes = ends[g];
    let lane = lanes.findIndex((e) => e < p.start);
    if (lane < 0 && lanes.length < maxLanes) lane = lanes.length;
    if (lane < 0) lane = lanes.indexOf(Math.min(...lanes));
    lanes[lane] = Math.max(lanes[lane] ?? 0, p.end);
    p.lane = lane;
    used[g] = Math.max(used[g], lane + 1);
  }
  return used;
}

export const visiblePieces = (pieces: Piece[], v: View) => pieces.filter((p) => p.end > v.from && p.start - 1 < v.to);

export interface Run {
  x0: number;
  x1: number;
  group: FeatureGroup;
}

/**
 * Level of detail for a zoomed-out view: per strand group, columns of `px` pixels take the feature group that
 * covers most of their bases; neighbouring columns of the same group merge into one run.
 */
export function densityRuns(pieces: Piece[], v: View, width: number, px = 2): Record<StrandGroup, Run[]> {
  const columns = Math.max(1, Math.ceil(width / px));
  const groups: FeatureGroup[] = ["coding", "rna", "element", "gap"];
  const cover: Record<StrandGroup, Float64Array[]> = {
    "+": groups.map(() => new Float64Array(columns)),
    "-": groups.map(() => new Float64Array(columns)),
    ".": groups.map(() => new Float64Array(columns)),
  };
  const bpPerColumn = (span(v) * px) / width;
  for (const p of pieces) {
    const lo = Math.max(p.start - 1, v.from);
    const hi = Math.min(p.end, v.to);
    if (hi <= lo) continue;
    const arr = cover[strandGroup(p.feature.strand)][groups.indexOf(featureGroup(p.feature.type))];
    const c0 = Math.floor((lo - v.from) / bpPerColumn);
    const c1 = Math.min(columns - 1, Math.floor((hi - v.from) / bpPerColumn));
    for (let c = c0; c <= c1; c++) {
      const colLo = v.from + c * bpPerColumn;
      arr[c] += Math.min(hi, colLo + bpPerColumn) - Math.max(lo, colLo);
    }
  }
  const out: Record<StrandGroup, Run[]> = { "+": [], "-": [], ".": [] };
  for (const g of ["+", "-", "."] as StrandGroup[]) {
    let current: Run | null = null;
    for (let c = 0; c < columns; c++) {
      let best = -1;
      let bestCover = 0;
      cover[g].forEach((arr, i) => {
        if (arr[c] > bestCover) {
          bestCover = arr[c];
          best = i;
        }
      });
      const group = best < 0 ? null : groups[best];
      if (current && group === current.group && current.x1 === c * px) current.x1 = Math.min(width, (c + 1) * px);
      else if (group) {
        current = { x0: c * px, x1: Math.min(width, (c + 1) * px), group };
        out[g].push(current);
      } else current = null;
    }
  }
  return out;
}

/** Bases between genes (1-based inclusive ranges): the sequence minus every piece of a GENE_TYPES feature. */
export function intergenic(features: FeatureLayoutItem[], length: number): [number, number][] {
  const spans = piecesOf(features.filter((f) => GENE_TYPES.has(f.type)), length)
    .map((p) => [p.start, p.end] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const out: [number, number][] = [];
  let next = 1;
  for (const [s, e] of spans) {
    if (s > next) out.push([next, s - 1]);
    next = Math.max(next, e + 1);
  }
  if (next <= length) out.push([next, length]);
  return out;
}

/** Intervals (1-based inclusive) in the view as pixel ranges, merged where less than `gapPx` apart, so a zoomed-out
 * view never draws more rectangles than it has pixels. */
export function mergePixels(intervals: [number, number][], v: View, width: number, gapPx = 1): [number, number][] {
  const out: [number, number][] = [];
  for (const [s, e] of intervals) {
    if (e <= v.from || s - 1 >= v.to) continue;
    const x0 = Math.max(0, toX(s - 1, v, width));
    const x1 = Math.min(width, toX(e, v, width));
    const last = out[out.length - 1];
    if (last && x0 - last[1] < gapPx) last[1] = Math.max(last[1], x1);
    else out.push([x0, x1]);
  }
  return out;
}

export const featureLabel = (f: Pick<FeatureLayoutItem, "gene" | "locus_tag" | "tool_id" | "id">) =>
  f.gene ?? f.locus_tag ?? f.tool_id ?? `#${f.id}`;

/** The feature after (step 1) or before (step -1) `current` in position order, or the first one in the view. */
export function neighbour(features: FeatureLayoutItem[], current: number | null, step: 1 | -1, v: View): FeatureLayoutItem | null {
  if (!features.length) return null;
  const sorted = [...features].sort((a, b) => Math.min(a.start, a.end) - Math.min(b.start, b.end) || a.id - b.id);
  const i = sorted.findIndex((f) => f.id === current);
  if (i < 0) {
    const centre = (v.from + v.to) / 2;
    const after = sorted.find((f) => Math.min(f.start, f.end) - 1 >= centre);
    return step === 1 ? after ?? sorted[sorted.length - 1] : [...sorted].reverse().find((f) => Math.min(f.start, f.end) - 1 < centre) ?? sorted[0];
  }
  return sorted[Math.min(sorted.length - 1, Math.max(0, i + step))];
}

/** A view that shows a feature (both pieces when it crosses the origin: the whole sequence) with some margin. */
export function viewOfFeature(f: FeatureLayoutItem, length: number): View {
  if (f.edge && f.start > f.end) return { from: 0, to: length };
  const lo = Math.min(f.start, f.end) - 1;
  const hi = Math.max(f.start, f.end);
  const margin = Math.max(50, (hi - lo) * 1.5);
  return clampView({ from: lo - margin, to: hi + margin }, length);
}

// --- Contigs ---------------------------------------------------------------------------------------------------

export interface ContigOption {
  id: string;
  name: string;
  length: number;
  circular: boolean | null;
  circularSource: string | null;
}

/** The annotated sequences with their topology: Bakta's when it reported one, else the assembler's flag. */
export function contigOptions(sequences: AnnotationSequence[], tool: string, contigs: AssemblyContig[] | undefined, assembler: string | undefined): ContigOption[] {
  const byName = new Map((contigs ?? []).map((c) => [c.name, c]));
  return sequences.map((s) => {
    const name = s.original_id || s.id;
    if (s.topology === "circular" || s.topology === "linear") {
      return { id: s.id, name, length: s.length, circular: s.topology === "circular", circularSource: tool };
    }
    const flag = byName.get(name)?.circular;
    return { id: s.id, name, length: s.length, circular: flag ?? null, circularSource: flag == null ? null : assembler ?? null };
  });
}

// --- Search ----------------------------------------------------------------------------------------------------

export type SearchTarget =
  | { kind: "region"; contig: string; start: number; end: number }
  | { kind: "contig"; contig: string }
  | { kind: "text"; q: string }
  | { kind: "error"; code: "out_of_range" | "order" };

const NUMBER = /^(?:\d{1,3}(?:[,._\s  ]\d{3})+|\d+)$/;

export function parseNumber(text: string): number | null {
  const t = text.trim();
  if (!NUMBER.test(t)) return null;
  const n = Number(t.replace(/[^\d]/g, ""));
  return Number.isSafeInteger(n) ? n : null;
}

function parseRange(text: string): [number, number] | null {
  const parts = text.split(/\s*(?:-|–|\.\.)\s*/);
  if (parts.length === 1) {
    const n = parseNumber(parts[0]);
    return n == null ? null : [n, n];
  }
  if (parts.length !== 2) return null;
  const a = parseNumber(parts[0]);
  const b = parseNumber(parts[1]);
  return a == null || b == null ? null : [a, b];
}

function findContig(name: string, contigs: ContigOption[]): ContigOption | undefined {
  const exact = contigs.find((c) => c.id === name || c.name === name);
  if (exact) return exact;
  const lower = name.toLowerCase();
  const loose = contigs.filter((c) => c.id.toLowerCase() === lower || c.name.toLowerCase() === lower);
  return loose.length === 1 ? loose[0] : undefined;
}

/**
 * What the search box asks for: "contig:start-end" or "contig:position" (either name of the sequence; thousands
 * separators allowed), "start-end" on the current sequence, a sequence name, or else text for the feature search
 * (gene, locus tag, product, identifiers such as "GO:0005840").
 */
export function parseSearch(input: string, contigs: ContigOption[], current: string | null): SearchTarget | null {
  const text = input.trim();
  if (!text) return null;
  const colon = text.lastIndexOf(":");
  let contig: ContigOption | undefined;
  let range: [number, number] | null = null;
  if (colon > 0) {
    contig = findContig(text.slice(0, colon).trim(), contigs);
    range = contig ? parseRange(text.slice(colon + 1)) : null;
  }
  if (!contig && /\d\s*(?:-|–|\.\.)\s*\d/.test(text) && current) {
    const r = parseRange(text);
    if (r) {
      contig = contigs.find((c) => c.id === current);
      range = r;
    }
  }
  if (contig && range) {
    const [start, end] = range;
    if (start < 1 || end > contig.length || start > contig.length) return { kind: "error", code: "out_of_range" };
    if (start > end) return { kind: "error", code: "order" };
    return { kind: "region", contig: contig.id, start, end };
  }
  const named = findContig(text, contigs);
  if (named) return { kind: "contig", contig: named.id };
  return { kind: "text", q: text };
}
