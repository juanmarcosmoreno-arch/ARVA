/** Sanger reads of one gene (app.api.routes.sanger): the shapes the API returns and the pure helpers of the screens
 * (chromatogram geometry, the window of scans shown, display rounding that never crosses a threshold, names of a
 * hit). The science is in arva_core.sanger; nothing here decides a result. */
import type { TranslationKey, TranslationVars } from "@/i18n";
import { fmtMax } from "./format";
import type { AnalysisJob } from "./types";

export const SANGER_JOB = "sanger_identification";
export const SANGER_ACCEPT = ".ab1,.abi,.fasta,.fa,.fas,.fna,.seq,.txt";
export const DEFAULT_TRIM_LIMIT = 0.05;
export const DEFAULT_MIXED_RATIO = 0.33;
export const SOURCE_KEYS = ["ncbi_16s", "vfdb", "mlst", "amrfinderplus", "spa", "reference_genomes", "genomes"] as const;
export type SourceKey = (typeof SOURCE_KEYS)[number];
export const BLAST_SOURCES = new Set<SourceKey>(["ncbi_16s", "vfdb", "mlst", "reference_genomes", "genomes"]);
export const BLAST_TASKS = ["megablast", "dc-megablast", "blastn", "blastn-short"] as const;
export type Direction = "forward" | "reverse" | "unknown";
export type Channel = "A" | "C" | "G" | "T";
export const CHANNELS: Channel[] = ["A", "C", "G", "T"];

export interface Coded {
  code: string;
  params: Record<string, string | number | string[] | null>;
}

export interface TrimSummary {
  limit: number | null;
  start: number | null;
  end: number | null;
  length: number;
  mean_quality?: number | null;
  q20_percent?: number | null;
}

export interface Trim extends TrimSummary {
  method: "modified_mott" | "manual" | "none";
  original_length: number;
  score?: number;
  source?: string;
}

export interface SangerReadView {
  id: string;
  sample_id: string;
  name: string;
  original_filename: string;
  file_format: "abi" | "fasta" | "seq";
  record_index: number;
  sha256: string;
  size_bytes: number;
  direction: Direction;
  direction_source: "name" | "user" | "none";
  pair_key: string | null;
  primer: string | null;
  length: number;
  has_qualities: boolean;
  has_trace: boolean;
  summary: {
    sample?: string | null;
    mean_quality: number | null;
    q20_percent: number | null;
    instrument: Record<string, string>;
    warnings: Coded[];
    default_trim: TrimSummary | null;
  };
  created_at: string;
  used_by: number;
  /** A text read (Macrogen's .txt) with the same pair key and direction as a chromatogram of this sample: a copy of
   * its base calls without qualities (sample overview only). */
  chromatogram_twin?: boolean;
}

export interface MixedPeak {
  position: number;
  origin: number;
  base: string;
  quality: number | null;
  second_base: string | null;
  ratio: number | null;
  kept?: boolean;
}

export interface SangerReadDetail extends SangerReadView {
  bases: string;
  qualities: number[] | null;
  trim: Trim | null;
  trim_source: string;
  kept_bases: string;
  mixed_peaks: MixedPeak[];
  mixed_ratio: number;
  mixed_source: string;
  warnings: Coded[];
}

export interface TraceMarker {
  position: number;
  origin: number;
  base: string;
  quality: number | null;
  scan: number;
  point: number;
}

export interface TraceView {
  scan_start: number;
  scan_end: number;
  scans: number;
  step: number;
  channels: Record<Channel, number[]>;
  markers: TraceMarker[];
  strand: "+" | "-";
}

export interface ProposedPair {
  pair_key: string;
  status: "proposed" | "ambiguous";
  forward_read_id?: string;
  reverse_read_id?: string;
  forward_read_ids?: string[];
  reverse_read_ids?: string[];
}

export interface GenomeBrief {
  assembly_id: string;
  sample_id: string;
  sample_code: string | null;
  project_id: string | null;
  kind: string;
  assembler: string;
  assembler_version: string;
  created_at: string;
  total_length: number | null;
  annotation: { annotation_id: string; tool: string; tool_version: string } | null;
  species: { species: string; method: string; database: string | null; job_id: string } | null;
  contigs_sha256?: string;
  own_sample?: boolean;
}

export interface Suspected {
  kind: "gene" | "species";
  value: string;
}

export interface BriefRow {
  rank?: number;
  tied_with_best?: boolean;
  source: SourceInfo;
  subject: string;
  title?: string | null;
  gene?: string | null;
  species?: string | null;
  genus?: string | null;
  strain?: string | null;
  product?: string | null;
  allele?: string | null;
  scheme?: string | null;
  accession?: string | null;
  genome?: string | null;
  identity: number;
  identical?: number;
  query_coverage: number;
  /** The gene's coverage: the database sequence's, or for a genome hit the annotated feature's (null when the genome
   * is not annotated). */
  subject_coverage?: number | null;
  /** For a genome hit, the share of the whole contig or chromosome covered. */
  contig_coverage?: number | null;
  aligned_length?: number;
  query_start?: number;
  query_end?: number;
  query_length?: number;
  subject_start?: number;
  subject_end?: number;
  subject_length?: number;
  strand?: string;
  kind?: "complete" | "partial" | "split" | string;
  evalue?: number;
  bitscore?: number;
  copies?: number;
  features?: { gene: string | null; product: string | null; locus_tag: string | null; type: string; feature_coverage: number; hit_inside: number; pseudo: boolean }[];
  type_material?: string | null;
  species_source?: string | null;
}

export interface SourceInfo {
  source: SourceKey;
  kind: string | null;
  key?: string | null;
  name: string | null;
  version: string | null;
  version_source?: string | null;
  checksum?: string | null;
  database_id?: string | null;
  assembly_id?: string;
  own_sample?: boolean;
}

export interface IdentificationBrief {
  id: string;
  sample_id: string;
  label: string;
  mode: "pair" | "single";
  forward_read_id: string | null;
  reverse_read_id: string | null;
  length: number;
  sha256: string;
  suspected: Suspected | null;
  created_at: string;
  searched: SourceKey[];
  running: number;
  best: BriefRow | null;
  /** Rows tied with the best one, and how many different names they carry (several species tie for 16S). */
  best_tied: number;
  best_tied_names: number;
  reading_16s: { level: Interpretation16s["level"]; species: string | null; genus: string | null; within_separation: number; above_species_threshold: number } | null;
  conflicts: number;
  unresolved: number;
}

export interface SangerOverview {
  sample_id: string;
  reads: SangerReadView[];
  pairs: ProposedPair[];
  identifications: IdentificationBrief[];
  genomes: GenomeBrief[];
}

export interface Skipped {
  file: string;
  code: string;
  params: Record<string, string | number>;
  detail: string;
}

export interface ImportResult {
  imported: SangerReadView[];
  skipped: Skipped[];
  pairs: ProposedPair[];
}

export interface Evidence {
  base: string;
  position: number;
  origin: number;
  quality: number | null;
  scan: number | null;
  heights: Record<Channel, number> | null;
}

export interface ConsensusColumn {
  column: number;
  position: number | null;
  base: string;
  status: "agree" | "forward_only" | "reverse_only" | "resolved" | "unresolved";
  kind: "mismatch" | "gap" | null;
  rule: "higher_quality" | "no_call_in_other_read" | "qualities_too_close" | "no_qualities" | null;
  forward: Evidence | null;
  reverse: Evidence | null;
}

export interface ConsensusResult {
  status: "ok" | "no_overlap" | "single";
  sequence: string;
  length: number;
  overlap?: { columns: number; identical: number; mismatches: number; gaps: number; identity: number; consensus_start: number | null; consensus_end: number | null };
  counts: Partial<Record<ConsensusColumn["status"], number>>;
  columns: ConsensusColumn[];
  conflicts: ConsensusColumn[];
  warnings: Coded[];
  score?: number;
  params?: Record<string, number | boolean>;
  role?: "forward" | "reverse";
  /** A reverse read searched alone is reverse-complemented. */
  reverse_complemented?: boolean;
  read?: { length: number; trim: Trim | null; mean_quality: number | null; q20_percent: number | null };
  forward?: { length: number; trim: Trim | null };
  reverse?: { length: number; trim: Trim | null };
  mixed_peaks?: Partial<Record<"forward" | "reverse", MixedPeak[]>>;
  source?: string;
  conflict_rule?: string;
}

export interface ConsensusPreview extends ConsensusResult {
  mode: "pair" | "single";
  settings: Record<string, unknown>;
}

export interface TrimIn {
  limit: number;
  manual_start?: number | null;
  manual_end?: number | null;
}

export interface ConsensusIn {
  match?: number | null;
  mismatch?: number | null;
  gap_open?: number | null;
  gap_extend?: number | null;
  min_winner_quality?: number | null;
  min_quality_difference?: number | null;
  min_overlap?: number | null;
  min_overlap_identity?: number | null;
}

export interface BuildIn {
  forward_read_id: string | null;
  reverse_read_id: string | null;
  forward_trim: TrimIn;
  reverse_trim: TrimIn;
  consensus: ConsensusIn;
  mixed_ratio: number;
}

export interface IdentificationIn extends BuildIn {
  label?: string | null;
  suspected?: Suspected | null;
  notes?: string | null;
}

export interface SearchIn {
  sources: SourceKey[];
  database_ids: Partial<Record<SourceKey, string>>;
  assembly_ids?: string[] | null;
  blast: Partial<Record<SourceKey, { task?: string | null; evalue?: number | null; max_target_seqs?: number | null }>>;
  amr_organism?: string | null;
  confirmed?: boolean;
  only_runnable?: boolean;
}

export interface Problem {
  code: string;
  params: Record<string, string | number>;
  message: string;
}

export interface DatabaseOption {
  id: string;
  key: string;
  kind: string;
  name: string;
  version: string | null;
  version_source: string | null;
  checksum: string | null;
  host_path: string;
  is_default: boolean;
  bundled: boolean;
  available: boolean;
  licence: string | null;
  citation: string | null;
}

export interface SourcePlan {
  source: SourceKey;
  kind: string | null;
  tool: { id: string; name: string; status: string; version: string | null; message: string; reason: string | null; reason_params?: Record<string, string | number> | null };
  database: DatabaseOption | null;
  database_options: DatabaseOption[];
  genomes: GenomeBrief[];
  settings: Record<string, string | number | boolean | null>;
  problems: Problem[];
  collection?: { genomes: number; species: number };
}

export interface SearchPlan {
  identification_id: string;
  query: { length: number; sha256: string; mode: string };
  sources: SourcePlan[];
  runnable: SourceKey[];
  blocked: SourceKey[];
  notes: string[];
}

export interface SearchJob {
  job_id: string;
  source: SourceKey;
  status: AnalysisJob["status"];
  tool: string | null;
  tool_version: string | null;
  created_at: string;
  finished_at: string | null;
  database_name: string | null;
  database_version: string | null;
  database_version_source: string | null;
  database_checksum: string | null;
  settings: Record<string, unknown> | null;
  genomes: GenomeBrief[] | null;
  error_message: string | null;
  error_detail: { code: string; params: Record<string, string | number> } | null;
  result_id: string | null;
  rows: number | null;
  details: Record<string, unknown> | null;
}

export interface SpeciesRow {
  subject: string;
  species: string;
  strain: string | null;
  identity: number;
  query_coverage: number;
  aligned_length: number;
  bitscore: number;
  evalue: number;
  subject_start: number;
  subject_end: number;
}

export interface Interpretation16s {
  level: "species" | "genus" | "inconclusive" | "no_hits";
  species: string | null;
  genus: string | null;
  best: SpeciesRow | null;
  next_species: SpeciesRow | null;
  separation: number | null;
  within_separation: SpeciesRow[];
  above_species_threshold: SpeciesRow[];
  reasons: Coded[];
  caveats: Coded[];
  thresholds: Record<string, number>;
  sources: Record<string, string>;
}

export interface SuspectedComparison {
  suspected: string;
  kind: "gene" | "species" | "genus";
  /** not_searched: no search has finished, so there is nothing to compare yet (no other field but these). */
  outcome: "match" | "ambiguous" | "no_match" | "not_searched";
  thresholds?: { min_identity: number; min_coverage: number; tie_window: number };
  best?: BriefRow | null;
  best_suspected?: BriefRow | null;
  /** The names of the hits that matched what was written ("S. aureus" -> "Staphylococcus aureus"). */
  matched_names?: string[];
  better_other?: BriefRow[];
  better_other_count?: number;
  tied_other?: BriefRow[];
  tied_other_count?: number;
  better_unnamed?: BriefRow[];
  better_unnamed_count?: number;
  reasons: Coded[];
  caveats: Coded[];
  /** Searches still queued or running: the outcome is provisional. */
  pending: number;
  source?: string;
  searched?: SourceKey[];
}

export interface AmrRow {
  element_symbol: string;
  element_name: string | null;
  type: string | null;
  subtype: string | null;
  class: string | null;
  method: string;
  identity: number | null;
  coverage: number | null;
  closest_accession: string | null;
  closest_name: string | null;
}

export interface IdentificationResults {
  identification: IdentificationBrief & { settings: Record<string, unknown>; notes: string | null; sequence: string };
  reads: { forward: SangerReadView | null; reverse: SangerReadView | null };
  consensus: ConsensusResult;
  searches: SearchJob[];
  by_source: Partial<Record<SourceKey, { job_id: string; rows: (BriefRow | AmrRow | Record<string, unknown>)[]; row_count: number; details: Record<string, unknown> | null }>>;
  ranked: BriefRow[];
  ranked_count: number;
  tied_with_best: number;
  interpretation_16s: Interpretation16s | null;
  suspected: SuspectedComparison | null;
  /** Sources with no finished search and none queued or running. */
  not_searched: SourceKey[];
  thresholds: { clsi_16s: Record<string, number>; gene: Record<string, number> };
  sources: Record<string, string>;
  notes: string[];
}

export interface Ncbi16sPlan {
  version: string;
  archive_bytes: number;
  database_bytes: number | null;
  description: string | null;
  sequences: number | null;
  letters: number | null;
  url: string;
  md5: string;
  taxonomy: boolean;
  kept_files: string[];
  required_bytes: number;
  host_target_path: string;
  folder: string;
  available_bytes: number;
  enough: boolean;
  blocked_by: string | null;
  blocked_code: string | null;
  licence: string;
  licence_url: string | null;
  only_current: boolean;
}

// --- Display -------------------------------------------------------------------------------------------------

/** Identities and coverages arrive unrounded and are compared unrounded; for display they are cut (not rounded) to
 * `digits` decimals, so 593 of 599 bases (98.998 %) never reads 99.00 % next to a 99 % threshold. The tolerance only
 * absorbs floating-point error, as arva_core.sanger.EPSILON does. */
export function cutDecimals(value: number, digits = 2): number {
  const f = 10 ** digits;
  return Math.floor(value * f + 1e-9) / f;
}

/** The name a hit is known by, from whichever source named it: gene (database or annotation), species and strain,
 * MLST allele, product; a genome hit with no annotated feature has none. */
export function hitName(row: Pick<BriefRow, "gene" | "species" | "strain" | "allele" | "product">): string | null {
  if (row.gene && row.allele) return `${row.gene}_${row.allele}`;
  if (row.gene) return row.gene;
  if (row.species) return row.strain ? `${row.species} ${row.strain}` : row.species;
  return row.product ?? null;
}

/** Where a hit lies in the source: accession, allele or contig with its coordinates. */
export function hitWhere(row: BriefRow): string {
  const at = row.subject_start != null && row.subject_end != null ? `:${row.subject_start}-${row.subject_end}` : "";
  if (row.genome) return `${row.genome} ${row.subject}${at}`;
  return `${row.accession ?? row.subject}${at}`;
}

/** The accession in a BLAST subject id of an NCBI database ("gi|2363085989|ref|NR_181247.1|" -> "NR_181247.1"), as
 * arva_core.sanger.ncbi_accession reads it; any other id is returned as it is. */
export function accessionOf(subject: string): string {
  const m = /\|(?:ref|gb|emb|dbj)\|([^|]+)\|?$/.exec(subject);
  return m ? m[1] : subject;
}

/** How a row's source is written: the database (or genome) with its version, and the kind of source only for genomes,
 * whose name is a sample code. */
export function sourceText(s: SourceInfo, label: string): string {
  const named = sourceVersion(s);
  if (!named) return label;
  return s.source === "genomes" || s.source === "reference_genomes" ? `${label}: ${named}` : named;
}

/** The database a row came from, with its version; a genome in ARVA is named by its sample. */
export function sourceVersion(s: SourceInfo | null | undefined): string {
  if (!s) return "";
  return [s.name, s.version].filter(Boolean).join(" ");
}

export const readStatusTone = (r: Pick<SangerReadView, "has_qualities" | "has_trace">) => (r.has_trace ? "teal" : r.has_qualities ? "blue" : "warning");

/** A coded message (`{code, params}`) under a prefix, as `${prefix}.${code}` with its params; lists are joined and
 * decimals written in the interface's locale. */
export function codedKey(prefix: string, c: Coded): [TranslationKey, TranslationVars] {
  const vars: TranslationVars = {};
  for (const [k, v] of Object.entries(c.params ?? {})) {
    if (v == null) continue;
    // Whole numbers stay numbers (plural rules read them); others are written in the locale (0,8 in Spanish).
    vars[k] = Array.isArray(v) ? v.join(", ") : typeof v === "number" ? (Number.isInteger(v) ? v : fmtMax(v, 3)) : String(v);
  }
  return [`${prefix}.${c.code}` as TranslationKey, vars];
}

/** The consensus as blocks of ten bases with the 1-based position of each block's first base, and each base's
 * column status (agree, single read, resolved or unresolved conflict) so conflicts can be highlighted. */
export function consensusBlocks(columns: ConsensusColumn[], size = 10): { start: number; bases: { base: string; status: ConsensusColumn["status"]; column: number }[] }[] {
  const bases = columns.filter((c) => c.base).map((c) => ({ base: c.base, status: c.status, column: c.column }));
  const out = [];
  for (let i = 0; i < bases.length; i += size) out.push({ start: i + 1, bases: bases.slice(i, i + size) });
  return out;
}

// --- Chromatogram -------------------------------------------------------------------------------------------

export const MIN_WINDOW_SCANS = 120;

/** The window of scans shown, clamped to the trace: `width` scans starting at `start`. */
export function clampWindow(start: number, width: number, scans: number): { start: number; width: number } {
  const w = Math.max(Math.min(MIN_WINDOW_SCANS, scans), Math.min(Math.round(width), scans));
  const s = Math.max(0, Math.min(Math.round(start), scans - w));
  return { start: s, width: w };
}

/** The window after a keyboard or button action: scroll by a quarter (or a whole) window, zoom in or out by two
 * around the centre, or go to either end. */
export function moveWindow(win: { start: number; width: number }, scans: number, action: "left" | "right" | "pageLeft" | "pageRight" | "zoomIn" | "zoomOut" | "home" | "end"): { start: number; width: number } {
  const { start, width } = win;
  const centre = start + width / 2;
  switch (action) {
    case "left":
      return clampWindow(start - width / 4, width, scans);
    case "right":
      return clampWindow(start + width / 4, width, scans);
    case "pageLeft":
      return clampWindow(start - width, width, scans);
    case "pageRight":
      return clampWindow(start + width, width, scans);
    case "zoomIn":
      return clampWindow(centre - width / 4, width / 2, scans);
    case "zoomOut":
      return clampWindow(centre - width, width * 2, scans);
    case "home":
      return clampWindow(0, width, scans);
    case "end":
      return clampWindow(scans - width, width, scans);
  }
}

/** The window centred on a scan (a base's peak), keeping the current width. */
export const centreOn = (scan: number, width: number, scans: number) => clampWindow(scan - width / 2, width, scans);

/** SVG polyline points of each channel of a trace view, scaled to `width` x `height` (0 at the bottom). `max` is the
 * highest value of the four channels in the view (the shared scale). */
export function tracePaths(view: Pick<TraceView, "channels">, width: number, height: number): { paths: Record<Channel, string>; max: number } {
  const max = Math.max(1, ...CHANNELS.map((c) => Math.max(0, ...view.channels[c])));
  const n = Math.max(1, view.channels.A.length - 1);
  const paths = {} as Record<Channel, string>;
  for (const c of CHANNELS) {
    paths[c] = view.channels[c].map((v, i) => `${((i / n) * width).toFixed(1)},${(height - (Math.max(0, v) / max) * height).toFixed(1)}`).join(" ");
  }
  return { paths, max };
}

/** The x position (0..width) of a scan in a view. */
export function scanX(view: Pick<TraceView, "scan_start" | "scan_end">, scan: number, width: number): number {
  const span = Math.max(1, view.scan_end - view.scan_start);
  return ((scan - view.scan_start) / span) * width;
}

/** The bases outside the kept region, as 1-based inclusive ranges of the read as called. */
export function trimmedRanges(length: number, trim: Pick<Trim, "start" | "end"> | null): [number, number][] {
  if (!trim || trim.start == null || trim.end == null) return length ? [[1, length]] : [];
  const out: [number, number][] = [];
  if (trim.start > 1) out.push([1, trim.start - 1]);
  if (trim.end < length) out.push([trim.end + 1, length]);
  return out;
}

/** The scan of a base (1-based position in the read as called) from the markers of a whole-trace view. */
export function scanOfBase(markers: TraceMarker[], position: number): number | null {
  const m = markers.find((x) => x.origin === position) ?? markers.find((x) => x.position === position);
  return m ? m.scan : null;
}

// --- Requests ------------------------------------------------------------------------------------------------

/** A trim request from the form: the Mott limit, or a manual range when both ends are given. */
export function trimRequest(limit: number, manualStart: string, manualEnd: string): TrimIn {
  const lo = Number.parseInt(manualStart, 10);
  const hi = Number.parseInt(manualEnd, 10);
  return Number.isFinite(lo) && Number.isFinite(hi) ? { limit, manual_start: lo, manual_end: hi } : { limit };
}

/** The pair proposed for the reads, or the first forward and reverse reads, or one read. */
export function defaultPair(o: Pick<SangerOverview, "reads" | "pairs">): { forward: string | null; reverse: string | null } {
  const p = o.pairs.find((x) => x.status === "proposed");
  if (p) return { forward: p.forward_read_id ?? null, reverse: p.reverse_read_id ?? null };
  // A chromatogram (with qualities) before a text copy of it.
  const pick = (d: Direction) => o.reads.find((r) => r.direction === d && r.has_qualities) ?? o.reads.find((r) => r.direction === d);
  const f = pick("forward");
  const r = pick("reverse");
  if (f || r) return { forward: f?.id ?? null, reverse: r?.id ?? null };
  return { forward: o.reads[0]?.id ?? null, reverse: null };
}

/** What decides the proposed reads: each read's id, direction and pair key. When the user corrects a direction or a
 * pair key, the proposal is made again. */
export const pairSignature = (reads: Pick<SangerReadView, "id" | "direction" | "pair_key">[]) => reads.map((r) => `${r.id}:${r.direction}:${r.pair_key ?? ""}`).join(",");

/** The suspicion to send: nothing when the text is empty. */
export function suspicionRequest(kind: Suspected["kind"], value: string): Suspected | null {
  const v = value.trim().replace(/\s+/g, " ");
  return v ? { kind, value: v } : null;
}

export const isActiveSearch = (j: Pick<SearchJob, "status">) => j.status === "pending" || j.status === "running";

/** The outcome's badge tone: a match is green, an ambiguous answer amber, no match red. */
export const outcomeTone = (o: SuspectedComparison["outcome"]) => (o === "match" ? "success" : o === "ambiguous" ? "warning" : o === "not_searched" ? "neutral" : "danger");
export const levelTone = (l: Interpretation16s["level"]) => (l === "species" ? "success" : l === "genus" ? "teal" : "warning");
