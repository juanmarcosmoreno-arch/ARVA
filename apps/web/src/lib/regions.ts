/** Genome Region Explorer and Custom Gene Investigation: result types and the pure geometry of the gene-neighbourhood
 * figure and the gene tree. A figure is a list of primitives (polygons, lines, text) drawn as SVG on screen and
 * written as a vector PDF (lib/pdf.ts), so every export shows exactly the same drawing. Tested in regions.test.tsx. */
import type { ToolInfo, Warning } from "./comparative";
import type { ServerMessage } from "./messages";

export interface RegionFeature {
  id: number;
  locus_tag: string | null;
  gene: string | null;
  product: string | null;
  type: string;
  start: number;
  end: number;
  strand: string;
  length: number | null;
  pseudo: boolean;
  rel_start: number;
  rel_end: number;
  rel_strand: string;
  clipped: boolean;
  group?: number;
  marks?: RegionMark[];
}

export interface RegionMark {
  kind: "amr" | "virulence" | "mobile";
  label: string;
  detail: string | null;
  source: string | null;
  start: number;
  end: number;
  strand: string | null;
}

export interface RegionTrack {
  label: string;
  assembly_id: string;
  sample_id: string;
  annotation_id: string | null;
  annotated: boolean;
  located_by: "anchor" | "blastp" | "blastn" | "not_found";
  hit: { identity: number; query_coverage: number; subject_coverage?: number; evalue: number; bitscore: number } | null;
  copies: number;
  features: RegionFeature[];
  elements: (RegionMark & { rel_start: number; rel_end: number })[];
  contig?: string;
  contig_length?: number;
  start?: number;
  end?: number;
  clipped_left?: boolean;
  clipped_right?: boolean;
  anchor_start?: number;
  anchor_end?: number;
  anchor_strand?: string;
  flipped?: boolean;
  anchor_feature_id?: number | null;
}

export interface RegionData {
  anchor: { kind: "feature" | "coordinates"; contig: string; start: number; end: number; strand: string; gene: string | null;
    locus_tag: string | null; product: string | null; feature_id: number | null; annotation_id: string | null };
  flank: number;
  tracks: RegionTrack[];
  groups: { id: number; name: string | null; size: number; tracks: number; anchor: boolean }[];
  links: { upper: number; lower: number; links: RegionLink[] }[];
  settings: { groups: { min_identity: number; min_coverage: number }; links: { min_identity: number; min_length: number };
    locate: { min_identity: number; min_coverage: number; evalue: number } };
}

export interface RegionLink {
  upper_start: number;
  upper_end: number;
  lower_start: number;
  lower_end: number;
  identity: number;
  length: number;
  inverted: boolean;
}

export interface GeneMatch {
  copy: number;
  kind: "complete" | "partial" | "split";
  contig: string;
  subject: string;
  start: number;
  end: number;
  strand: "+" | "-";
  identity: number;
  query_coverage: number;
  query_start: number;
  query_end: number;
  query_length: number;
  evalue: number;
  bitscore: number;
  at_contig_edge: boolean;
  pieces: { qstart: number; qend: number; s_lo: number; s_hi: number; pident: number }[];
  feature: { feature_id: number; locus_tag: string | null; gene: string | null; product: string | null; annotation_id: string } | null;
  mobile: { element: string; category: string; method: string; tool: string; distance: number; start: number; end: number }[];
  on_plasmid_contig: boolean;
}

export interface TreeNode {
  name: string | null;
  length: number | null;
  support: number | null;
  children: TreeNode[];
}

export interface GeneData {
  query: { id: string; name: string; molecule: "nucleotide" | "protein"; length: number; sha256: string; source: Record<string, unknown> };
  program: string;
  task: string;
  genomes: { label: string; assembly_id: string; sample_id: string; annotation_id: string | null; hsps: number;
    hsps_above_identity: number; matches: GeneMatch[] }[];
  alignment: { status: string; columns?: number; strategy?: string; mafft_version?: string;
    sequences: { id: string; label: string; genome: string; copy: number | null; length: number }[] } | null;
  tree: { method: string; status: string; model?: string | null; support?: string; support_max?: number; tool_version?: string;
    sequences: number; unique_sequences: number; newick?: string; tree?: TreeNode } | null;
  settings: Record<string, unknown> & { min_identity: number; min_coverage: number; complete_coverage: number; evalue: number;
    max_gap: number; mobile_distance: number };
}

export interface GeneQuery {
  id: string;
  name: string;
  description: string | null;
  molecule: "nucleotide" | "protein";
  length: number;
  sha256: string;
  source: Record<string, unknown> & { kind: string };
  created_at: string;
  sequence?: string;
}

export interface GeneLookupRow {
  label: string;
  assembly_id: string;
  annotation_id: string;
  annotator: string;
  feature_id: number;
  type: string;
  gene: string | null;
  locus_tag: string | null;
  product: string | null;
  contig: string;
  start: number;
  end: number;
  strand: string;
  length: number | null;
  exact: boolean;
}

export interface RegionAnchorIn {
  annotation_id?: string | null;
  feature_id?: number | null;
  assembly_id?: string | null;
  contig?: string | null;
  start?: number | null;
  end?: number | null;
  strand?: "+" | "-" | null;
}

export interface RegionRequest {
  anchor: RegionAnchorIn;
  genomes: string[];
  flank: number;
  locate: { min_identity: number; min_coverage: number; evalue: number };
  groups: { min_identity: number; min_coverage: number };
  links: { min_identity: number; min_length: number };
  threads: number | null;
  confirmed: boolean;
}

export interface GeneRequest {
  query_id: string;
  genomes: string[];
  task: string | null;
  thresholds: { min_identity: number; min_coverage: number; complete_coverage: number; evalue: number; max_gap: number };
  mobile_distance: number;
  alignment: { enabled: boolean; strategy: "linsi" | "fftns2"; kinds: ("complete" | "partial" | "split")[]; include_query: boolean };
  tree: { enabled: boolean; method: "iqtree" | "fasttree"; model: string; ufboot: number; seed: number };
  threads: number | null;
  confirmed: boolean;
}

export interface RegionPlan {
  analysis: "region" | "gene";
  method: string;
  tool: ToolInfo;
  tools: Record<string, ToolInfo>;
  settings: Record<string, unknown> & { threads: number };
  anchor: (RegionData["anchor"] & { note?: string; type: string | null }) | null;
  query: GeneQuery | null;
  genomes: { assembly_id: string; label: string; contigs_sha256: string; total_length: number | null; synthetic_evidence: string[];
    locate_by?: "blastp" | "blastn"; annotation: { annotation_id: string; tool: string; tool_version: string } | null }[];
  unannotated: string[];
  problems: (ServerMessage & { message: string })[];
  notes: string[];
}

export const REGION_DEFAULTS = {
  flank: 10_000,
  locate: { min_identity: 70, min_coverage: 70, evalue: 1e-10 },
  groups: { min_identity: 30, min_coverage: 50 },
  links: { min_identity: 70, min_length: 100 },
};
export const GENE_DEFAULTS: Omit<GeneRequest, "query_id" | "genomes" | "threads" | "confirmed"> = {
  task: null,
  thresholds: { min_identity: 80, min_coverage: 50, complete_coverage: 90, evalue: 1e-10, max_gap: 5000 },
  mobile_distance: 10_000,
  alignment: { enabled: true, strategy: "linsi", kinds: ["complete"], include_query: true },
  tree: { enabled: false, method: "iqtree", model: "MFP", ufboot: 1000, seed: 12345 },
};
export const MAX_REGION_GENOMES = 20;
export const TASKS = { blastn: ["blastn", "dc-megablast", "megablast", "blastn-short"], tblastn: ["tblastn", "tblastn-fast"] } as const;

export type { Warning };

// --- Figure primitives -----------------------------------------------------------------------------------------------

export interface FeatureRef {
  track: number;
  feature?: number;
  element?: number;
}

export type Prim =
  | { kind: "poly"; points: [number, number][]; fill: string; stroke?: string; width?: number; opacity?: number; ref?: FeatureRef }
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number; stroke: string; width: number; dash?: boolean }
  | { kind: "text"; x: number; y: number; text: string; size: number; anchor: "start" | "middle" | "end"; fill: string;
      italic?: boolean; bold?: boolean; rotate?: number };

export interface Figure {
  width: number;
  height: number;
  prims: Prim[];
}

/** Okabe-Ito (colour-blind safe) followed by Paul Tol's muted scheme; one colour per shared homology group. */
export const GROUP_PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#332288",
  "#88CCEE", "#44AA99", "#117733", "#999933", "#DDCC77", "#AA4499", "#882255"];
export const MARK_COLORS = { amr: "#C2185B", virulence: "#7B1FA2", mobile: "#EF6C00" } as const;

export interface FigureTheme {
  text: string;
  muted: string;
  axis: string;
  link: string;
  outline: string;
  neutral: string;
}

// Helvetica's advance widths (Adobe AFM, 1/1000 em) for ASCII 32-126; Arial has the same metrics.
const HELVETICA = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
  556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
  556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500,
  556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
  260, 334, 584];

export function textWidth(text: string, size: number): number {
  let w = 0;
  for (const ch of text) {
    const c = ch.charCodeAt(0);
    w += c >= 32 && c <= 126 ? HELVETICA[c - 32] : 556;
  }
  return (w * size) / 1000;
}

/** The text, shortened with an ellipsis to fit `width` at `size` (SVG text is never clipped by its box). */
export function fit(text: string, size: number, width: number): string {
  if (textWidth(text, size) <= width) return text;
  let cut = text;
  while (cut.length > 1 && textWidth(`${cut}…`, size) > width) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}…`;
}

export function wrap(text: string, size: number, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (line && textWidth(next, size) > width) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

const drawn = (t: RegionTrack) => t.located_by !== "not_found" && t.start != null;

/** A track's window in its relative coordinates (gene of interest from 0 to its length, pointing right). */
export function trackSpan(t: RegionTrack): [number, number] {
  const a = t.flipped ? t.anchor_end! - t.end! : t.start! - t.anchor_start!;
  const b = t.flipped ? t.anchor_end! - t.start! : t.end! - t.anchor_start!;
  return [a, b];
}

/** Mirror a relative position across the gene of interest of a track (a flip the user asked for). */
export function mirror(t: RegionTrack, x: number): number {
  return t.anchor_end! - t.anchor_start! - x;
}

export interface RegionFigureOptions {
  order: number[];
  flips: Record<number, boolean>;
  labels: "gene" | "locus" | "none";
  theme: FigureTheme;
  legendTitle: string;
  marksLegend: Record<"amr" | "virulence" | "mobile", string>;
  linksLegend: string;
  notFound: string;
  unnamedGroup: (id: number) => string;
  hitLabel: (identity: number) => string;
  caption: string;
  kb: (v: number) => string;
}

const LEFT = 210;
const PLOT = 720;
const ROW = 74;
const ARROW = 16;
// The figure is usually drawn narrower than its 960 units (beside the set list), so its small text is sized for that.
const LEGEND_SIZE = 12;
const TOP = 24;

function arrow(x0: number, x1: number, y: number, strand: string, h = ARROW): [number, number][] {
  const head = Math.min(9, (x1 - x0) * 0.45);
  if (strand === "-") return [[x1, y - h / 2], [x0 + head, y - h / 2], [x0, y], [x0 + head, y + h / 2], [x1, y + h / 2]];
  if (strand === "+") return [[x0, y - h / 2], [x1 - head, y - h / 2], [x1, y], [x1 - head, y + h / 2], [x0, y + h / 2]];
  return [[x0, y - h / 2], [x1, y - h / 2], [x1, y + h / 2], [x0, y + h / 2]];
}

/** Which homology groups get a colour: those shared by at least two tracks (ordered by size); others are grey. */
export function sharedGroups(data: RegionData): number[] {
  return data.groups.filter((g) => g.tracks > 1).sort((a, b) => Number(b.anchor) - Number(a.anchor) || b.size - a.size).map((g) => g.id);
}

/** The gene-neighbourhood figure: one row per located genome in `order`, genes as arrows by strand and size on a
 * common axis aligned on the gene of interest, coloured by shared homology group, the gene of interest outlined,
 * AMR / virulence / mobile calls marked under their gene, blastn identity bands between neighbouring rows (drawn only
 * between rows that were neighbours in the job), a scale, a legend and a caption. */
export function regionFigure(data: RegionData, o: RegionFigureOptions): Figure {
  const rows = o.order.filter((i) => drawn(data.tracks[i]));
  const prims: Prim[] = [];
  const shared = sharedGroups(data);
  const colorOf = (g: number | undefined) => {
    const k = g == null ? -1 : shared.indexOf(g);
    return k >= 0 && k < GROUP_PALETTE.length ? GROUP_PALETTE[k] : o.theme.neutral;
  };
  const spans = rows.map((i) => {
    const [a, b] = trackSpan(data.tracks[i]);
    return o.flips[i] ? [mirror(data.tracks[i], b), mirror(data.tracks[i], a)] : [a, b];
  });
  const lo = Math.min(0, ...spans.map((s) => s[0]));
  const hi = Math.max(1, ...spans.map((s) => s[1]));
  const scale = PLOT / Math.max(1, hi - lo);
  const x = (v: number) => LEFT + (v - lo) * scale;
  const pos = (i: number, v: number) => x(o.flips[i] ? mirror(data.tracks[i], v) : v);
  const yOf = (row: number) => TOP + 20 + row * ROW;
  rows.forEach((i, row) => {
    const next = rows[row + 1];
    const block = next === undefined ? undefined
      : data.links.find((l) => (l.upper === i && l.lower === next) || (l.upper === next && l.lower === i));
    if (!block) return;
    const upperFirst = block.upper === i;
    const yu = upperFirst ? yOf(row) + ARROW / 2 + 2 : yOf(row + 1) - ARROW / 2 - 2;
    const yl = upperFirst ? yOf(row + 1) - ARROW / 2 - 2 : yOf(row) + ARROW / 2 + 2;
    for (const k of block.links.slice(0, 400)) {
      const a0 = pos(block.upper, k.upper_start), a1 = pos(block.upper, k.upper_end);
      const b0 = pos(block.lower, k.lower_start), b1 = pos(block.lower, k.lower_end);
      // Positions map through every flip, so a band joins upper_start to lower_start unless the HSP is inverted.
      const bottom: [number, number][] = k.inverted ? [[b0, yl], [b1, yl]] : [[b1, yl], [b0, yl]];
      prims.push({ kind: "poly", points: [[a0, yu], [a1, yu], ...bottom], fill: o.theme.link,
        opacity: Math.round((0.1 + 0.3 * Math.max(0, (k.identity - 70) / 30)) * 20) / 20 });
    }
  });
  rows.forEach((i, row) => {
    const t = data.tracks[i];
    const y = yOf(row);
    const [s0, s1] = spans[row];
    prims.push({ kind: "text", x: LEFT - 10, y: y + 4, text: fit(t.label, 11 * 1.08, LEFT - 18), size: 11, anchor: "end", fill: o.theme.text, bold: true });
    if (t.contig) prims.push({ kind: "text", x: LEFT - 10, y: y + 17, text: fit(`${t.contig}:${t.start!.toLocaleString("en-US")}-${t.end!.toLocaleString("en-US")}${t.flipped !== Boolean(o.flips[i]) ? " (−)" : ""}`, 9, LEFT - 18), size: 9, anchor: "end", fill: o.theme.muted });
    if (t.hit) prims.push({ kind: "text", x: LEFT - 10, y: y + 28, text: fit(o.hitLabel(t.hit.identity), 9, LEFT - 18), size: 9, anchor: "end", fill: o.theme.muted });
    prims.push({ kind: "line", x1: x(s0), y1: y, x2: x(s1), y2: y, stroke: o.theme.axis, width: 1 });
    t.features.forEach((f) => {
      let a = pos(i, f.rel_start), b = pos(i, f.rel_end);
      if (a > b) [a, b] = [b, a];
      const strand = o.flips[i] ? ({ "+": "-", "-": "+" }[f.rel_strand] ?? f.rel_strand) : f.rel_strand;
      const coding = f.type === "cds" || f.type === "sorf";
      const anchor = f.id === t.anchor_feature_id;
      prims.push({ kind: "poly", points: arrow(a, Math.max(b, a + 1), y, strand, coding ? ARROW : ARROW * 0.6),
        fill: coding ? colorOf(f.group) : o.theme.neutral, stroke: anchor ? o.theme.outline : o.theme.axis,
        width: anchor ? 2 : 0.5, opacity: f.pseudo ? 0.45 : 1, ref: { track: i, feature: f.id } });
      const label = o.labels === "gene" ? f.gene : o.labels === "locus" ? f.locus_tag : null;
      if (label && textWidth(label, 9) < b - a + 6) {
        prims.push({ kind: "text", x: (a + b) / 2, y: y - ARROW / 2 - 4, text: label, size: 9, anchor: "middle", fill: o.theme.text,
          italic: o.labels === "gene" });
      }
      (f.marks ?? []).forEach((m, k) => {
        const cx = (a + b) / 2 + (k - ((f.marks!.length - 1) / 2)) * 8;
        prims.push({ kind: "poly", points: [[cx, y + ARROW / 2 + 3], [cx - 3.5, y + ARROW / 2 + 9], [cx + 3.5, y + ARROW / 2 + 9]],
          fill: MARK_COLORS[m.kind], ref: { track: i, feature: f.id } });
      });
    });
    t.elements.forEach((e, k) => {
      let a = pos(i, e.rel_start), b = pos(i, e.rel_end);
      if (a > b) [a, b] = [b, a];
      const yy = y + ARROW / 2 + 12;
      prims.push({ kind: "poly", points: [[a, yy], [Math.max(b, a + 2), yy], [Math.max(b, a + 2), yy + 4], [a, yy + 4]],
        fill: MARK_COLORS[e.kind], ref: { track: i, element: k } });
    });
  });
  let y = yOf(Math.max(rows.length, 1)) - ROW / 2 + 14;
  const step = [1000, 2000, 5000, 10_000, 20_000, 50_000].find((s) => (hi - lo) / s <= 12) ?? 100_000;
  prims.push({ kind: "line", x1: x(lo), y1: y, x2: x(hi), y2: y, stroke: o.theme.axis, width: 0.8 });
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    prims.push({ kind: "line", x1: x(v), y1: y, x2: x(v), y2: y + 4, stroke: o.theme.axis, width: 0.8 });
    prims.push({ kind: "text", x: x(v), y: y + 14, text: o.kb(v / 1000), size: 10, anchor: "middle", fill: o.theme.muted });
  }
  const missing = data.tracks.filter((t, i) => o.order.includes(i) && !drawn(t)).map((t) => t.label);
  if (missing.length) {
    y += 30;
    prims.push({ kind: "text", x: LEFT, y, text: `${o.notFound}: ${missing.join(", ")}`, size: LEGEND_SIZE, anchor: "start", fill: o.theme.muted });
  }
  y += 30;
  prims.push({ kind: "text", x: 16, y, text: o.legendTitle, size: LEGEND_SIZE + 1, anchor: "start", fill: o.theme.text, bold: true });
  let lx = 16 + textWidth(o.legendTitle, LEGEND_SIZE + 1) + 14;
  const legend: { color: string; text: string; italic: boolean }[] = shared.slice(0, GROUP_PALETTE.length).map((id, k) => {
    const g = data.groups.find((x) => x.id === id)!;
    return { color: GROUP_PALETTE[k], text: g.name ?? o.unnamedGroup(id), italic: Boolean(g.name && !g.name.includes(" ")) };
  });
  legend.push(...(["amr", "virulence", "mobile"] as const).map((k) => ({ color: MARK_COLORS[k], text: o.marksLegend[k], italic: false })));
  for (const item of legend) {
    const w = 14 + textWidth(item.text, LEGEND_SIZE) + 14;
    if (lx + w > LEFT + PLOT + 20) {
      lx = 16;
      y += 18;
    }
    prims.push({ kind: "poly", points: [[lx, y - 9], [lx + 10, y - 9], [lx + 10, y + 1], [lx, y + 1]], fill: item.color });
    prims.push({ kind: "text", x: lx + 14, y, text: item.text, size: LEGEND_SIZE, anchor: "start", fill: o.theme.text, italic: item.italic });
    lx += w;
  }
  y += 18;
  prims.push({ kind: "poly", points: [[16, y - 9], [40, y - 9], [40, y + 1], [16, y + 1]], fill: o.theme.link, opacity: 0.35 });
  prims.push({ kind: "text", x: 46, y, text: o.linksLegend, size: LEGEND_SIZE, anchor: "start", fill: o.theme.text });
  y += 8;
  for (const line of wrap(o.caption, LEGEND_SIZE - 0.5, LEFT + PLOT - 16)) {
    y += 15;
    prims.push({ kind: "text", x: 16, y, text: line, size: LEGEND_SIZE - 0.5, anchor: "start", fill: o.theme.muted });
  }
  return { width: LEFT + PLOT + 30, height: y + 14, prims };
}

// --- Gene tree ---------------------------------------------------------------------------------------------------

export function leaves(n: TreeNode): string[] {
  return n.children.length ? n.children.flatMap(leaves) : [n.name ?? ""];
}

/** A rectangular phylogram of a tree as written (unrooted trees are drawn from the file's base node, which is not a
 * root), branch lengths to scale, support values at internal nodes, a scale bar and a caption. */
export function treeFigure(tree: TreeNode, o: { theme: FigureTheme; caption: string; scaleUnit: string; supportMax: number }): Figure {
  const prims: Prim[] = [];
  const names = leaves(tree);
  const labelW = Math.max(60, ...names.map((n) => textWidth(n, 10))) + 12;
  const plot = 560;
  const depth = (n: TreeNode, d: number): number => Math.max(d, ...n.children.map((c) => depth(c, d + (c.length ?? 0))));
  const maxDepth = depth(tree, 0) || 1;
  const sx = plot / maxDepth;
  let leafY = 0;
  const top = 16;
  const place = (n: TreeNode, d: number): number => {
    const x = 16 + d * sx;
    if (!n.children.length) {
      const y = top + leafY++ * 20;
      prims.push({ kind: "text", x: x + 5, y: y + 3.5, text: n.name ?? "", size: 10, anchor: "start", fill: o.theme.text });
      return y;
    }
    const ys = n.children.map((c) => {
      const cy = place(c, d + (c.length ?? 0));
      prims.push({ kind: "line", x1: x, y1: cy, x2: 16 + (d + (c.length ?? 0)) * sx, y2: cy, stroke: o.theme.text, width: 1 });
      return cy;
    });
    prims.push({ kind: "line", x1: x, y1: Math.min(...ys), x2: x, y2: Math.max(...ys), stroke: o.theme.text, width: 1 });
    const y = (Math.min(...ys) + Math.max(...ys)) / 2;
    if (n.support != null && n !== tree) {
      const s = o.supportMax === 1 ? n.support.toFixed(2) : String(Math.round(n.support));
      prims.push({ kind: "text", x: x - 3, y: y - 3, text: s, size: 8, anchor: "end", fill: o.theme.muted });
    }
    return y;
  };
  place(tree, 0);
  let y = top + names.length * 20 + 8;
  const bar = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1].find((b) => b * sx >= 40) ?? 1;
  prims.push({ kind: "line", x1: 16, y1: y, x2: 16 + bar * sx, y2: y, stroke: o.theme.text, width: 1.2 });
  prims.push({ kind: "text", x: 16 + bar * sx + 6, y: y + 3.5, text: `${bar} ${o.scaleUnit}`, size: 9, anchor: "start", fill: o.theme.muted });
  y += 8;
  const width = 16 + plot + labelW + 24;
  for (const line of wrap(o.caption, 9, width - 32)) {
    y += 13;
    prims.push({ kind: "text", x: 16, y, text: line, size: 9, anchor: "start", fill: o.theme.muted });
  }
  return { width, height: y + 12, prims };
}

/** Matches of every genome as table rows, best first within each genome. */
export function matchRows(data: GeneData) {
  return data.genomes.flatMap((g) => g.matches.map((m) => ({ genome: g.label, assembly_id: g.assembly_id, annotation_id: g.annotation_id, ...m })));
}
