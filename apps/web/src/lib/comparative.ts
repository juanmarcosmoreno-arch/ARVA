/** Comparative genomics: comparison sets, their ANI and alignment results, and the pure geometry behind the
 * heatmap, dot plot, synteny and conservation views (tested in comparative.test.tsx). */
import type { ServerMessage } from "./messages";

export interface ComparisonCandidate {
  assembly_id: string;
  sample_id: string;
  sample_code: string | null;
  project_id: string | null;
  project_name: string | null;
  kind: "assembly" | "polished";
  assembler: string;
  assembler_version: string;
  total_length: number | null;
  contigs: number | null;
  created_at: string;
  annotation_id: string | null;
}

export interface ComparisonMember extends ComparisonCandidate {
  label: string;
  position: number;
  contigs_present: boolean;
}

export interface ComparisonResultBrief {
  id: string;
  job_id: string;
  analysis: "ani" | "alignment" | "region" | "gene" | "pangenome" | "phylogeny";
  method: "skani" | "fastani" | "minimap2" | "nucmer" | "blast" | "blastn" | "tblastn" | "panaroo" | "ppanggolin" | "iqtree" | "fasttree" | "nj";
  tool: string;
  tool_version: string;
  genomes: string[];
  warnings: Warning[];
  created_at: string;
}

export interface Warning {
  code: string;
  params: Record<string, string | number>;
}

export interface ComparisonSet {
  id: string;
  project_id: string;
  project_name: string | null;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  members: ComparisonMember[];
  results: ComparisonResultBrief[];
  jobs: { id: string; job_type: string; status: string; tool_name: string; created_at: string; error_message: string | null;
    error_detail: { code: string; params: Record<string, string | number> } | null }[];
}

export interface ComparisonSetBrief {
  id: string;
  name: string;
  description: string | null;
  project_id: string;
  project_name: string | null;
  genomes: number;
  labels: string[];
  has_results: boolean;
  updated_at: string;
}

export interface ComparisonSetIn {
  project_id: string;
  name: string;
  description: string | null;
  assembly_ids: string[];
  labels: Record<string, string>;
}

export interface ToolInfo {
  id: string;
  name: string;
  status: string;
  version: string | null;
  version_validated: boolean;
  message: string;
  reason: string | null;
  reason_params: Record<string, string | number>;
  path: string | null;
  citation: string;
  citation_url: string;
  max_threads: number;
  default_threads: number;
}

export interface PlanGenome {
  assembly_id: string;
  label: string;
  contigs_sha256: string;
  total_length: number | null;
  synthetic_evidence: string[];
}

export interface ComparisonPlan {
  analysis: "ani" | "alignment" | "phylogeny";
  method: string;
  set_id: string;
  tool: ToolInfo;
  dnadiff_tool: ToolInfo | null;
  settings: Record<string, unknown> & { threads: number };
  dnadiff: boolean | null;
  genomes: PlanGenome[];
  reference: string | null;
  pairs: { reference: string; query: string; role: "reference" | "neighbour" }[];
  comparisons: number | null;
  problems: (ServerMessage & { message: string })[];
  notes: string[];
  source?: { leaves: { name: string }[]; file: { key: string; sha256: string | null } | null } | null;
}

export type AniMethod = "skani" | "fastani";
export type Aligner = "minimap2" | "nucmer";
export type Preset = "asm5" | "asm10" | "asm20";
export const PRESETS: Preset[] = ["asm5", "asm10", "asm20"];
export const ANCHORS = ["mumreference", "mum", "maxmatch"] as const;

export interface NucmerSettings {
  anchors: (typeof ANCHORS)[number];
  breaklen: number;
  mincluster: number;
  maxgap: number;
  minmatch: number;
}

export const NUCMER_DEFAULTS: NucmerSettings = { anchors: "mumreference", breaklen: 200, mincluster: 65, maxgap: 90, minmatch: 20 };

export interface AniRequest {
  method: AniMethod;
  threads: number | null;
  confirmed: boolean;
}

export interface AlignmentRequest {
  aligner: Aligner;
  preset: Preset;
  nucmer: NucmerSettings;
  order: string[];
  dnadiff: boolean;
  threads: number | null;
  confirmed: boolean;
}

export interface AniMatrix {
  ids: string[];
  ani: (number | null)[][];
  af: (number | null)[][];
  directional: boolean;
}

export interface PairSummary {
  reference: string;
  query: string;
  role: "reference" | "neighbour";
  blocks: number;
  forward: number;
  reverse: number;
  ref_aligned: number;
  query_aligned: number;
  ref_fraction: number | null;
  query_fraction: number | null;
  identity: number | null;
  secondary_blocks: number;
}

export interface Difference {
  sequence: string;
  type: "GAP" | "DUP" | "BRK" | "JMP" | "INV" | "SEQ";
  start: number;
  end: number;
  length: number;
  inserted: number;
  category: "insertion" | "inversion" | "relocation" | "translocation" | null;
}

export interface DnadiffEntry {
  reference: string;
  query: string;
  report: { reference: Record<string, number>; query: Record<string, number> };
  reference_differences: Difference[];
  query_differences: Difference[];
}

/** [ref contig, ref start, ref end, query contig, query start, query end, strand, identity %, length, primary] */
export type Block = [string, number, number, string, number, number, "+" | "-", number, number, boolean];

export interface AlignmentData {
  genomes: { label: string; assembly_id: string; sample_id: string; contigs: { name: string; length: number }[]; total_length: number }[];
  reference: number;
  method: Aligner;
  pairs: { reference: number; query: number; role: "reference" | "neighbour"; blocks: Block[] }[];
  conservation: {
    reference: string;
    window: number;
    genomes: { label: string; windows: { contig: string; start: number; end: number; covered: number; identity: number | null }[] }[];
  };
}

export interface ComparisonResult extends ComparisonResultBrief {
  set_id: string;
  parameters: Record<string, unknown>;
  summary: {
    matrix?: AniMatrix;
    order?: { order: number[]; merges: [number, number, number, number][]; method: string };
    pairs_not_reported?: number;
    reference?: string;
    pairs?: PairSummary[];
    window?: number;
    dnadiff?: DnadiffEntry[];
    tools?: { name: string; version: string | null; path: string | null }[];
  };
  files: Record<string, { path: string; sha256: string; size_bytes: number }>;
  alignment?: AlignmentData | null;
  alignment_missing?: boolean | null;
  data?: Record<string, unknown> | null;
  data_missing?: boolean | null;
}

/** The result as the API sends it: `genomes` is the recorded snapshot, not the labels of the brief. */
export type ComparisonResultRead = Omit<ComparisonResult, "genomes"> & {
  genomes: { assembly_id: string; label: string; sample_id: string; sample_code: string | null; contigs_sha256: string;
    total_length: number; contig_count: number }[];
};

/** Cells of an ANI heatmap in the similarity order: x = column position, y = row position (row 0 drawn on top). */
export function heatmapCells(m: AniMatrix, order: number[]): { x: number; y: number; value: number | null; row: string; col: string }[] {
  const cells = [];
  for (const [y, i] of order.entries()) {
    for (const [x, j] of order.entries()) cells.push({ x, y, value: m.ani[i][j], row: m.ids[i], col: m.ids[j] });
  }
  return cells;
}

/** The lowest ANI below 100 (the colour scale's start), or 95 when there is none. */
export function aniFloor(m: AniMatrix): number {
  const values = m.ani.flat().filter((v): v is number => v !== null && v < 100);
  return values.length ? Math.floor(Math.min(...values) * 10) / 10 : 95;
}

/** Cumulative start of each contig when a genome's contigs are drawn end to end. */
export function offsets(contigs: { name: string; length: number }[]): Map<string, number> {
  const out = new Map<string, number>();
  let total = 0;
  for (const c of contigs) {
    out.set(c.name, total);
    total += c.length;
  }
  return out;
}

/** Dot-plot segments in genome coordinates (x = reference, y = query): a forward block runs up, a reverse block down. */
export function dotSegments(blocks: Block[], refOffsets: Map<string, number>, queryOffsets: Map<string, number>, primaryOnly: boolean) {
  const forward: [number, number][][] = [];
  const reverse: [number, number][][] = [];
  for (const b of blocks) {
    if (primaryOnly && !b[9]) continue;
    const rx = refOffsets.get(b[0]);
    const qy = queryOffsets.get(b[3]);
    if (rx === undefined || qy === undefined) continue;
    const seg: [number, number][] = b[6] === "+"
      ? [[rx + b[1], qy + b[4]], [rx + b[2], qy + b[5]]]
      : [[rx + b[1], qy + b[5]], [rx + b[2], qy + b[4]]];
    (b[6] === "+" ? forward : reverse).push(seg);
  }
  return { forward, reverse };
}

/** Flattened points of segments for an ECharts line series ("-" breaks the line between segments). */
export function segmentPoints(segments: [number, number][][]): ([number, number] | "-")[] {
  const out: ([number, number] | "-")[] = [];
  for (const s of segments) out.push(s[0], s[1], "-");
  return out;
}

/** Synteny links between two genome bars: reference x-range and query x-range in fractions of each bar's width. */
export function syntenyLinks(blocks: Block[], ref: { offsets: Map<string, number>; total: number }, query: { offsets: Map<string, number>; total: number },
  minLength: number) {
  const links = [];
  for (const b of blocks) {
    if (!b[9] || b[8] < minLength) continue;
    const ro = ref.offsets.get(b[0]);
    const qo = query.offsets.get(b[3]);
    if (ro === undefined || qo === undefined) continue;
    links.push({
      r0: (ro + b[1] - 1) / ref.total, r1: (ro + b[2]) / ref.total,
      q0: (qo + b[4] - 1) / query.total, q1: (qo + b[5]) / query.total,
      reverse: b[6] === "-", identity: b[7], length: b[8], block: b,
    });
  }
  return links;
}

/** The start of an identity colour scale: the 5th percentile of the values, rounded down (lower values are drawn
 * with the scale's lightest colour), so that a few short low-identity blocks do not wash out the rest; 90 if none. */
export function identityFloor(values: number[]): number {
  if (!values.length) return 90;
  const sorted = [...values].sort((a, b) => a - b);
  return Math.min(99, Math.floor(sorted[Math.floor((sorted.length - 1) * 0.05)]));
}

/** A colour for an identity (%) on a sequential scale from `low` (light) to 100 (dark); reverse links use another hue. */
export function identityColor(identity: number, low: number, reverse: boolean, dark: boolean): string {
  const tt = Math.max(0, Math.min(1, (identity - low) / Math.max(100 - low, 1e-9)));
  const light = dark ? 30 + 35 * tt : 82 - 47 * tt;
  return reverse ? `hsl(24 85% ${light}%)` : `hsl(222 70% ${light}%)`;
}

/** The Genome Explorer address of a region of a genome, when the genome has an annotation. */
export function explorerUrl(annotationId: string | null | undefined, contig: string, start: number, end: number): string | null {
  if (!annotationId) return null;
  const pad = Math.max(500, Math.round((end - start) * 0.1));
  const lo = Math.max(1, Math.min(start, end) - pad);
  const hi = Math.max(start, end) + pad;
  return `/explorer/${annotationId}?${new URLSearchParams({ contig, start: String(lo), end: String(hi) })}`;
}
