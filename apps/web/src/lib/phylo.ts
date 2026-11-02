/** Phylogeny results and the Tree Explorer's drawing: clade keys, collapsing, ladderizing, rectangular and circular
 * layouts, and the figure primitives (lib/regions.ts) that the SVG, PNG and vector PDF exports share. */
import { type Figure, GROUP_PALETTE, type Prim, textWidth } from "./regions";

export interface TreeNode {
  name: string | null;
  length: number | null;
  support: number | null;
  supports?: number[];
  children: TreeNode[];
}

export interface PhyloLeaf {
  name: string;
  genome: string | null;
  assembly_id: string | null;
  sample_id: string | null;
  gene_id?: string | null;
  missing_fraction?: number;
}

export type Layout = "rectangular" | "circular";
export type RootMethod = "none" | "midpoint" | "outgroup";
export type SourceKind = "core_alignment" | "snp_alignment" | "family_alignment" | "gene_alignment" | "ani_matrix";
export type TreeMethod = "iqtree" | "fasttree" | "nj";

export interface PhyloStyle {
  layout: Layout;
  collapsed: string[];
  branch_colors: Record<string, string>;
  leaf_color_field: string | null;
  bands: string[];
  show_support: boolean;
  support_min: number;
  show_lengths: boolean;
  ladderize: boolean;
  align_labels: boolean;
  font_size: number;
}

export const DEFAULT_STYLE: PhyloStyle = {
  layout: "rectangular", collapsed: [], branch_colors: {}, leaf_color_field: null, bands: [], show_support: true,
  support_min: 0, show_lengths: false, ladderize: true, align_labels: false, font_size: 11,
};

export interface Rooting {
  method: RootMethod;
  outgroup: string[];
}

export interface PhyloData {
  tree: TreeNode;
  rooted: TreeNode;
  rooting: { method: RootMethod; leaves?: string[]; path_length?: number; outgroup?: string[]; error?: string };
  view: { rooting: Rooting; style: Partial<PhyloStyle>; updated_at: string };
  leaves: PhyloLeaf[];
  support: { kind: string; label: string; max: number } | null;
  alignment: { sequences: number; columns: number; constant: number; variable: number; parsimony_informative: number } | null;
  distances: { kind: string; matrix: number[][]; compared_sites: number[][] | null } | null;
  source: { kind: SourceKind; result_id: string; core?: string; family?: string; query?: string };
  snp_columns?: number;
  constant_counts?: Record<string, number>;
  iqtree?: { model: string; log_likelihood?: number };
}

export interface PhyloSourceOption {
  result_id: string;
  analysis: string;
  method: string;
  kind: SourceKind;
  created_at: string;
  genomes: number;
  core?: ("all" | "filtered")[];
  families?: string[];
  families_total?: number;
}

export interface PhyloRequest {
  source: { kind: SourceKind; result_id: string; core: "all" | "filtered"; family: string | null };
  method: TreeMethod;
  iqtree: { model: string; ufboot: number; alrt: number; seed: number };
  constant_sites: "fconst" | "asc" | "none";
  distance: "p" | "jc69";
  rooting: Rooting;
  threads: number | null;
  confirmed: boolean;
}

export interface LeafMetadata {
  genomes: string[];
  fields: { key: string; custom: boolean; values: (string | null)[]; recorded: number; distinct: number }[];
  amr: { genes: string[]; by_genome: Record<string, string[] | null> };
}

export interface RfResult {
  rf: number;
  max: number;
  normalized: number;
  shared: number;
  splits_a: number;
  splits_b: number;
  common_leaves: number;
  only_in_a_leaves: string[];
  only_in_b_leaves: string[];
  only_a: string[][];
  only_b: string[][];
  by: "leaf" | "genome";
}

/** FNV-1a (32-bit) of the clade's sorted leaf names: a short, stable name for a clade whatever the drawing order. */
export function cladeKey(leaves: string[]): string {
  let h = 0x811c9dc5;
  for (const ch of [...leaves].sort().join("\u0001")) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

export interface PNode {
  id: number;
  name: string | null;
  length: number;
  support: number | null;
  supportText: string | null;
  children: PNode[];
  leaves: string[];
  key: string;
  collapsed: boolean;
  parent: PNode | null;
}

/** The tree with ids, leaf sets, clade keys, children ladderized (smaller clades first) and the collapsed clades
 * marked; a collapsed node keeps its leaves but its children are not drawn. */
export function prepare(tree: TreeNode, style: Pick<PhyloStyle, "collapsed" | "ladderize">): PNode {
  let next = 0;
  const collapsed = new Set(style.collapsed);
  const walk = (n: TreeNode, parent: PNode | null): PNode => {
    const p: PNode = { id: next++, name: n.name, length: Math.max(n.length ?? 0, 0), support: n.support,
      supportText: n.supports?.length ? n.supports.map((v) => String(v)).join("/") : n.support !== null ? String(n.support) : null,
      children: [], leaves: [], key: "", collapsed: false, parent };
    p.children = n.children.map((c) => walk(c, p));
    if (style.ladderize) p.children.sort((a, b) => a.leaves.length - b.leaves.length);
    p.leaves = p.children.length ? p.children.flatMap((c) => c.leaves) : [n.name ?? ""];
    p.key = cladeKey(p.leaves);
    p.collapsed = p.children.length > 0 && parent !== null && collapsed.has(p.key);
    return p;
  };
  return walk(tree, null);
}

export function visibleTips(root: PNode): PNode[] {
  const out: PNode[] = [];
  const go = (n: PNode) => {
    if (!n.children.length || n.collapsed) out.push(n);
    else n.children.forEach(go);
  };
  go(root);
  return out;
}

export function nodes(root: PNode): PNode[] {
  const out: PNode[] = [];
  const go = (n: PNode) => {
    out.push(n);
    if (!n.collapsed) n.children.forEach(go);
  };
  go(root);
  return out;
}

/** Distance from the root along branch lengths, or the number of branches when the tree has no lengths. */
export function depths(root: PNode, useLengths: boolean): Map<number, number> {
  const out = new Map<number, number>();
  const go = (n: PNode, d: number) => {
    out.set(n.id, d);
    n.children.forEach((c) => go(c, d + (useLengths ? c.length : 1)));
  };
  go(root, 0);
  return out;
}

export function hasLengths(tree: TreeNode): boolean {
  const go = (n: TreeNode, root: boolean): boolean => (root || n.length !== null) && n.children.every((c) => go(c, false));
  return go(tree, true);
}

/** The sum of branch lengths between two leaves. */
export function patristic(root: PNode, a: string, b: string): number | null {
  const path = (n: PNode, name: string): PNode[] | null => {
    if (!n.children.length) return n.name === name ? [n] : null;
    for (const c of n.children) {
      const p = path(c, name);
      if (p) return [n, ...p];
    }
    return null;
  };
  const pa = path(root, a);
  const pb = path(root, b);
  if (!pa || !pb) return null;
  let i = 0;
  while (i < pa.length && i < pb.length && pa[i] === pb[i]) i++;
  const sum = (p: PNode[]) => p.slice(i).reduce((s, n) => s + n.length, 0);
  return sum(pa) + sum(pb);
}

/** A round scale-bar length: 1, 2 or 5 × 10^k, at most a fifth of the span. */
export function scaleBar(span: number): number {
  if (!(span > 0)) return 0;
  const target = span / 5;
  const p = 10 ** Math.floor(Math.log10(target));
  return [5, 2, 1].map((m) => m * p).find((v) => v <= target) ?? p;
}

/** Categorical colours in order of first appearance; a presence field uses fixed present/absent colours. */
export function categoryColors(values: (string | null)[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const v of values) {
    if (v !== null && !out.has(v)) out.set(v, GROUP_PALETTE[out.size % GROUP_PALETTE.length]);
  }
  return out;
}

export const PRESENT = "#C2185B";

export interface FieldValues {
  key: string;
  label: string;
  presence: boolean;
  byLeaf: Map<string, string | null>;
  colors: Map<string, string>;
}

export interface TreeTheme {
  text: string;
  muted: string;
  branch: string;
  highlight: string;
  absent: string;
}

export interface Hit {
  node: PNode;
  x: number;
  y: number;
}

export interface TreeFigure {
  fig: Figure;
  hits: Hit[];
}

function arc(cx: number, cy: number, r: number, a0: number, a1: number, stroke: string, width: number): Prim[] {
  const steps = Math.max(1, Math.ceil(Math.abs(a1 - a0) / (Math.PI / 90)));
  const out: Prim[] = [];
  for (let i = 0; i < steps; i++) {
    const t0 = a0 + ((a1 - a0) * i) / steps;
    const t1 = a0 + ((a1 - a0) * (i + 1)) / steps;
    out.push({ kind: "line", x1: cx + r * Math.cos(t0), y1: cy + r * Math.sin(t0), x2: cx + r * Math.cos(t1), y2: cy + r * Math.sin(t1), stroke, width });
  }
  return out;
}

/** The tree as figure primitives. Rectangular: root on the left, one row per visible tip. Circular: root at the
 * centre, tips around the circle. Collapsed clades are triangles labelled with their leaf count; metadata bands are
 * one cell per tip after the labels. `marked` clade keys (bipartitions missing from another tree) are dashed. */
export function treeFigure(tree: TreeNode, style: PhyloStyle, opts: {
  theme: TreeTheme;
  leafColor?: FieldValues | null;
  bands?: FieldValues[];
  highlight?: Set<string>;
  marked?: Set<string>;
  supportMax?: number;
  unit?: string;
  collapsedLabel: (count: number) => string;
}): TreeFigure {
  const { theme } = opts;
  const root = prepare(tree, style);
  const lengths = hasLengths(tree);
  const depth = depths(root, lengths);
  const tips = visibleTips(root);
  const fs = style.font_size;
  const row = Math.max(fs + 6, 14);
  const tipLabel = (n: PNode) => (n.collapsed ? opts.collapsedLabel(n.leaves.length) : n.name ?? "");
  const labelW = Math.max(40, ...tips.map((n) => textWidth(tipLabel(n), fs))) + 8;
  const bands = opts.bands ?? [];
  const bandW = 14;
  let maxDepth = 1e-12;
  const scan = (n: PNode) => {
    if (!n.children.length) maxDepth = Math.max(maxDepth, depth.get(n.id)!);
    n.children.forEach(scan);
  };
  scan(root);
  const prims: Prim[] = [];
  const hits: Hit[] = [];
  const colorOf = (n: PNode): string => {
    for (let p: PNode | null = n; p; p = p.parent) if (style.branch_colors[p.key]) return style.branch_colors[p.key];
    return theme.branch;
  };
  const tipFill = (n: PNode) => {
    if (n.collapsed || !opts.leafColor) return theme.text;
    const v = opts.leafColor.byLeaf.get(n.name ?? "");
    return v ? opts.leafColor.colors.get(v) ?? theme.text : theme.muted;
  };
  const supportLabel = (n: PNode) => style.show_support && n.children.length && n.parent && n.support !== null &&
    n.support >= style.support_min * ((opts.supportMax ?? 100) / 100) ? n.supportText : null;
  const order = new Map(tips.map((n, i) => [n.id, i]));
  const ypos = new Map<number, number>();
  const place = (n: PNode): number => {
    const y = n.collapsed || !n.children.length ? order.get(n.id)! : (() => {
      const ys = n.children.map(place);
      return (ys[0] + ys[ys.length - 1]) / 2;
    })();
    ypos.set(n.id, y);
    return y;
  };
  place(root);
  if (style.layout === "rectangular") {
    const supportW = Math.max(0, ...nodes(root).map((n) => {
      const label = supportLabel(n);
      return label ? textWidth(label, fs - 2) : 0;
    }));
    const left = 16 + supportW;
    const top = 16 + (bands.length ? 34 : 0);
    const treeW = Math.max(420, Math.min(900, tips.length * 9 + 300));
    const sx = treeW / maxDepth;
    const X = (d: number) => left + d * sx;
    const Y = (i: number) => top + i * row;
    const tipX = (n: PNode) => (style.align_labels ? X(maxDepth) : X(depth.get(n.id)!));
    for (const n of nodes(root)) {
      const x = X(depth.get(n.id)!);
      const y = Y(ypos.get(n.id)!);
      const color = colorOf(n);
      const dash = opts.marked?.has(n.key);
      if (n.parent) {
        prims.push({ kind: "line", x1: X(depth.get(n.parent.id)!), y1: y, x2: x, y2: y, stroke: color, width: 1.4, dash });
        if (style.show_lengths && lengths) {
          prims.push({ kind: "text", x: (X(depth.get(n.parent.id)!) + x) / 2, y: y - 3, text: n.length.toPrecision(2), size: fs - 3, anchor: "middle", fill: theme.muted });
        }
      }
      if (n.children.length && !n.collapsed) {
        const ys = n.children.map((c) => Y(ypos.get(c.id)!));
        prims.push({ kind: "line", x1: x, y1: ys[0], x2: x, y2: ys[ys.length - 1], stroke: color, width: 1.4 });
        const s = supportLabel(n);
        if (s) prims.push({ kind: "text", x: x - 3, y: y - 3, text: s, size: fs - 2, anchor: "end", fill: theme.muted });
        hits.push({ node: n, x, y });
      }
      if (n.collapsed) {
        const far = X(maxDepth) - 4;
        prims.push({ kind: "poly", points: [[x, y], [Math.max(far, x + 20), y - row * 0.4], [Math.max(far, x + 20), y + row * 0.4]], fill: color, opacity: 0.35, stroke: color, width: 1 });
        hits.push({ node: n, x, y });
      }
      if (!n.children.length || n.collapsed) {
        const tx = n.collapsed ? Math.max(X(maxDepth), x + 20) : tipX(n);
        if (style.align_labels && !n.collapsed && tx > x) prims.push({ kind: "line", x1: x, y1: y, x2: tx, y2: y, stroke: theme.muted, width: 0.5, dash: true });
        const hl = opts.highlight?.has(n.name ?? "");
        if (hl) prims.push({ kind: "poly", points: [[tx + 2, y - row / 2 + 1], [tx + 6 + textWidth(tipLabel(n), fs), y - row / 2 + 1], [tx + 6 + textWidth(tipLabel(n), fs), y + row / 2 - 1], [tx + 2, y + row / 2 - 1]], fill: theme.highlight, opacity: 0.35 });
        prims.push({ kind: "text", x: tx + 4, y: y + fs * 0.35, text: tipLabel(n), size: fs, anchor: "start", fill: tipFill(n), italic: n.collapsed, bold: hl });
        if (!n.collapsed) hits.push({ node: n, x: tx + 4, y });
      }
    }
    const bandX0 = X(maxDepth) + labelW + 12;
    bands.forEach((b, j) => {
      const bx = bandX0 + j * (bandW + 2);
      prims.push({ kind: "text", x: bx + bandW / 2, y: top - 8, text: b.label.length > 6 ? `${b.label.slice(0, 5)}…` : b.label, size: 8, anchor: "start", fill: theme.muted, rotate: -60 });
      for (const n of tips) {
        if (n.collapsed) continue;
        const v = b.byLeaf.get(n.name ?? "") ?? null;
        const y = Y(ypos.get(n.id)!);
        const fill = v === null ? "none" : b.presence ? (v === "present" ? PRESENT : theme.absent) : b.colors.get(v) ?? theme.absent;
        if (fill !== "none") prims.push({ kind: "poly", points: [[bx, y - row / 2 + 1], [bx + bandW, y - row / 2 + 1], [bx + bandW, y + row / 2 - 1], [bx, y + row / 2 - 1]], fill });
      }
    });
    let height = Y(tips.length - 1) + row;
    if (lengths) {
      const bar = scaleBar(maxDepth);
      height += 6;
      prims.push({ kind: "line", x1: left, y1: height, x2: left + bar * sx, y2: height, stroke: theme.text, width: 1.5 });
      prims.push({ kind: "text", x: left, y: height + 13, text: `${bar} ${opts.unit ?? ""}`.trim(), size: 10, anchor: "start", fill: theme.muted });
      height += 20;
    }
    const width = bandX0 + bands.length * (bandW + 2) + 16;
    return { fig: { width, height, prims }, hits };
  }
  const n = tips.length;
  const radius = Math.max(140, (n * row) / (2 * Math.PI));
  const bandSpan = bands.length * (bandW + 2);
  const margin = labelW + bandSpan + 24;
  const cx = radius + margin;
  const cy = radius + margin;
  const sr = radius / maxDepth;
  const angle = (i: number) => -Math.PI / 2 + (2 * Math.PI * i) / n;
  const P = (r: number, a: number): [number, number] => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  for (const nd of nodes(root)) {
    const r = depth.get(nd.id)! * sr;
    const a = angle(ypos.get(nd.id)!);
    const color = colorOf(nd);
    const dash = opts.marked?.has(nd.key);
    if (nd.parent) {
      const [x1, y1] = P(depth.get(nd.parent.id)! * sr, a);
      const [x2, y2] = P(r, a);
      prims.push({ kind: "line", x1, y1, x2, y2, stroke: color, width: 1.4, dash });
    }
    if (nd.children.length && !nd.collapsed) {
      const as = nd.children.map((c) => angle(ypos.get(c.id)!));
      prims.push(...arc(cx, cy, r, as[0], as[as.length - 1], color, 1.4));
      const [hx, hy] = P(r, a);
      const s = supportLabel(nd);
      if (s && nd.parent) prims.push({ kind: "text", x: hx, y: hy - 3, text: s, size: fs - 2, anchor: "end", fill: theme.muted });
      hits.push({ node: nd, x: hx, y: hy });
    }
    if (!nd.children.length || nd.collapsed) {
      const lr = style.align_labels || nd.collapsed ? radius : r;
      const [px, py] = P(lr, a);
      if (nd.collapsed) {
        const da = Math.PI / n * 0.8;
        prims.push({ kind: "poly", points: [P(r, a), P(radius, a - da), P(radius, a + da)], fill: color, opacity: 0.35, stroke: color, width: 1 });
        hits.push({ node: nd, x: px, y: py });
      } else if (style.align_labels && lr > r) {
        const [qx, qy] = P(r, a);
        prims.push({ kind: "line", x1: qx, y1: qy, x2: px, y2: py, stroke: theme.muted, width: 0.5, dash: true });
      }
      const deg = (a * 180) / Math.PI;
      const flip = Math.cos(a) < 0;
      const [lx, ly] = P(lr + 4, a);
      const hl = opts.highlight?.has(nd.name ?? "");
      prims.push({ kind: "text", x: lx, y: ly, text: tipLabel(nd), size: fs, anchor: flip ? "end" : "start", fill: tipFill(nd), italic: nd.collapsed, bold: hl, rotate: flip ? deg + 180 : deg });
      if (!nd.collapsed) hits.push({ node: nd, x: lx, y: ly });
      bands.forEach((b, j) => {
        const v = b.byLeaf.get(nd.name ?? "") ?? null;
        if (v === null || nd.collapsed) return;
        const r0 = radius + labelW + 8 + j * (bandW + 2);
        const da = Math.PI / n;
        const fill = b.presence ? (v === "present" ? PRESENT : theme.absent) : b.colors.get(v) ?? theme.absent;
        const steps = Math.max(2, Math.ceil((2 * da) / (Math.PI / 90)));
        const edge = (r: number) => Array.from({ length: steps + 1 }, (_, k) => P(r, a - da + (2 * da * k) / steps));
        prims.push({ kind: "poly", points: [...edge(r0), ...edge(r0 + bandW).reverse()], fill, stroke: theme.muted, width: 0.3 });
      });
    }
  }
  let height = cy * 2;
  if (lengths) {
    const bar = scaleBar(maxDepth);
    prims.push({ kind: "line", x1: 16, y1: height - 24, x2: 16 + bar * sr, y2: height - 24, stroke: theme.text, width: 1.5 });
    prims.push({ kind: "text", x: 16, y: height - 10, text: `${bar} ${opts.unit ?? ""}`.trim(), size: 10, anchor: "start", fill: theme.muted });
    height += 4;
  }
  return { fig: { width: cx * 2, height, prims }, hits };
}

/** Field values per leaf, through each leaf's genome: sample metadata and MLST, AMR gene presence ("amr:<gene>")
 * and pangenome family presence ("family:<name>" with the family's presence string over the pangenome's genomes). */
export function fieldValues(key: string, leaves: PhyloLeaf[], meta: LeafMetadata | undefined,
  family?: { name: string; genomes: string[]; presence: string } | null, label?: string): FieldValues | null {
  const byLeaf = new Map<string, string | null>();
  if (key.startsWith("amr:")) {
    if (!meta) return null;
    const gene = key.slice(4);
    for (const l of leaves) {
      const genes = l.genome ? meta.amr.by_genome[l.genome] : null;
      byLeaf.set(l.name, genes ? (genes.includes(gene) ? "present" : "absent") : null);
    }
    return { key, label: label ?? gene, presence: true, byLeaf, colors: new Map() };
  }
  if (key.startsWith("family:")) {
    if (!family) return null;
    const idx = new Map(family.genomes.map((g, i) => [g, i]));
    for (const l of leaves) {
      const i = l.genome !== null ? idx.get(l.genome) : undefined;
      byLeaf.set(l.name, i === undefined ? null : family.presence[i] === "1" ? "present" : "absent");
    }
    return { key, label: label ?? family.name, presence: true, byLeaf, colors: new Map() };
  }
  const field = meta?.fields.find((f) => f.key === key);
  if (!field || !meta) return null;
  const idx = new Map(meta.genomes.map((g, i) => [g, i]));
  for (const l of leaves) {
    const i = l.genome !== null ? idx.get(l.genome) : undefined;
    byLeaf.set(l.name, i === undefined ? null : field.values[i]);
  }
  return { key, label: label ?? key, presence: false, byLeaf, colors: categoryColors([...byLeaf.values()]) };
}

/** Clade keys of the bipartitions listed by a Robinson-Foulds comparison, for the side drawn as a clade in this
 * tree (a bipartition is one clade of a rooted drawing, or the complement of one). */
export function markedClades(root: PNode, splits: string[][]): Set<string> {
  const all = new Set(root.leaves);
  const out = new Set<string>();
  for (const s of splits) {
    out.add(cladeKey(s));
    out.add(cladeKey([...all].filter((x) => !s.includes(x))));
  }
  return out;
}
