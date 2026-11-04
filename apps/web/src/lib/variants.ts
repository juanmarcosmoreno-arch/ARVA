import type { Translate, TranslationKey } from "@/i18n";
import { assemblerName } from "./assembly";
import type { Assembly } from "./types";

export const VARIANT_JOB = "variant_calling";
export const TECHNOLOGIES = ["illumina", "ont", "pacbio_hifi"] as const;
export type Technology = (typeof TECHNOLOGIES)[number];
export const VARIANT_TYPES = ["snp", "mnp", "insertion", "deletion", "complex"] as const;
export type VariantType = (typeof VARIANT_TYPES)[number];
export const SOFT_FILTERS = ["LowQual", "LowDepth", "LowAltFraction"] as const;
/** bcftools csq's consequence types from the most to the least severe (csq.c), as BCSQ writes them. */
export const EFFECTS = [
  "splice_acceptor", "splice_donor", "stop_gained", "frameshift", "stop_lost", "start_lost", "inframe_altering", "inframe_insertion",
  "inframe_deletion", "missense", "splice_region", "synonymous", "stop_retained", "start_retained", "non_coding", "5_prime_utr",
  "3_prime_utr", "intron", "intergenic",
] as const;
const HIGH = new Set(["stop_gained", "frameshift", "stop_lost", "start_lost", "splice_acceptor", "splice_donor"]);
const MODERATE = new Set(["missense", "inframe_insertion", "inframe_deletion", "inframe_altering"]);

export interface VariantReferenceIn {
  kind: "assembly" | "collection";
  assembly_id?: string | null;
  database_id?: string | null;
  genome_key?: string | null;
}

export interface VariantSettings {
  min_mapq: number;
  min_baseq: number | null;
  max_depth: number;
  call_indels: boolean | null;
  prior: number;
  min_qual: number;
  min_depth: number;
  min_alt_fraction: number;
}

export interface VariantRequest {
  technology: Technology;
  reference: VariantReferenceIn;
  inputs: Partial<Record<"r1" | "r2" | "unpaired" | "long", string | null>>;
  settings: VariantSettings;
  effects: boolean;
  keep_alignment: boolean;
  threads: number | null;
  confirmed: boolean;
}

export interface ReferenceAssemblyOption {
  assembly_id: string;
  label: string;
  sample_code: string | null;
  same_project: boolean;
  own_sample: boolean;
  kind: string;
  assembler: string;
  assembler_version?: string;
  mode?: string;
  declared_assembler?: string | null;
  declared_assembler_version?: string | null;
  contigs: number | null;
  total_length: number | null;
  annotation: { id: string; tool: string; tool_version: string } | null;
}

export interface VariantOptions {
  assemblies: ReferenceAssemblyOption[];
  collections: { database_id: string; name: string; version: string | null; genomes: number; available: boolean }[];
  suggested_technology: Technology | null;
  defaults: {
    profiles: Record<Technology, { baq: string; min_baseq: number; max_baseq: number; call_indels: boolean }>;
    filters: { min_mapq: number; min_qual: number; min_depth: number; min_alt_fraction: number };
    max_depth: number;
    sources: Record<string, string>;
  };
}

export interface CollectionGenome {
  key: string;
  accession: string | null;
  organism: string | null;
  strain: string | null;
  size: number | null;
}

export interface Note {
  code: string;
  params: Record<string, string | number>;
  message: string;
}

export interface ReferenceSnapshot {
  kind: "assembly" | "collection";
  label: string;
  sha256: string;
  total_length: number;
  contigs?: { name: string; length: number }[];
  annotation: { id: string; tool: string; tool_version: string } | null;
  assembly_id?: string;
  sample_code?: string | null;
  database_name?: string;
  accession?: string | null;
}

export interface VariantPlan {
  technology: Technology;
  suggested_technology: Technology | null;
  roles: string[];
  reference: ReferenceSnapshot;
  aligner: { tool: string; preset: string | null };
  tools: Record<string, { id: string; name: string; status: string; version: string | null; version_validated: boolean; message: string; missing_flags?: string[] }>;
  settings: VariantSettings & { mpileup: Record<string, unknown>; threads: number };
  effects: boolean;
  problems: Note[];
  notes: Note[];
  read_group_sample: string;
  resources: { threads: number; max_threads: number };
}

export interface Histogram {
  edges: number[];
  pass: number[];
  filtered: number[];
}

export interface VariantSummary {
  records: number;
  pass: number;
  by_type: Record<VariantType, number>;
  by_filter: Record<string, number>;
  by_effect: Record<string, number>;
  start_codon_notes: number;
  after_stop?: number;
  depth_histogram: Histogram;
  alt_fraction_histogram: Histogram;
  distribution: { bin: number; contigs: { contig: string; length: number; snp: number[]; other: number[] }[] };
  alignment: { reads: number; reads_mapped: number; mapped_percent: number | null; properly_paired_percent: number | null };
  coverage: { contig: string; length: number; mean_depth: number; covered_percent: number }[];
  callable_bases: number;
  callable_percent: number;
  reference_length: number;
  csq_features: Record<string, number> | null;
}

export interface VariantRun {
  id: string;
  job_id: string;
  sample_id: string;
  created_at: string;
  reference: ReferenceSnapshot;
  reference_sha256: string;
  technology: Technology;
  aligner: string;
  aligner_version: string;
  caller_version: string;
  reads: { role: string; file_id: string; name: string; sha256: string | null }[];
  parameters: { settings: VariantSettings & { threads: number }; effects: boolean; keep_alignment: boolean; aligner_preset: string | null };
  summary: VariantSummary;
  warnings: { code: string; params: Record<string, string | number>; text: string }[];
  files: Record<string, { sha256: string; size_bytes: number }>;
  duration_seconds: number | null;
}

export interface Consequence {
  consequence?: string | null;
  gene?: string | null;
  transcript?: string | null;
  aa_change?: string | null;
  dna_change?: string | null;
  terms?: string[];
  see_position?: number;
}

export interface VariantRecord {
  contig: string;
  pos: number;
  end: number;
  ref: string;
  alt: string;
  type: VariantType;
  qual: number | null;
  filters: string[];
  pass: boolean;
  depth: number | null;
  ref_reads: number | null;
  alt_reads: number | null;
  alt_fraction: number | null;
  genotype: string | null;
  consequences: Consequence[];
  effect: string | null;
  start_codon?: string;
  after_stop?: boolean;
}

export interface VariantRecords {
  total: number;
  offset: number;
  variants: VariantRecord[];
}

export interface ProjectVariants {
  project_id: string;
  references: {
    reference_sha256: string;
    reference: ReferenceSnapshot;
    runs: { id: string; sample_id: string; sample_code: string | null; technology: Technology; pass: number; records: number; by_type: Record<VariantType, number>; callable_percent: number | null; mapped_percent: number | null }[];
  }[];
}

export interface SnpMatrix {
  samples: { id: string; label: string }[];
  sites: { contig: string; pos: number; ref: string }[];
  alleles: string[];
  distances: number[][];
  compared_sites: number[][];
  core_sites: number;
  missing: number[];
  same_settings: boolean;
  reference: ReferenceSnapshot;
}

export interface ExplorerVariants {
  runs: { id: string; sample_code: string | null; technology: Technology; created_at: string; pass: number }[];
  run_id: string | null;
  variants: VariantRecord[];
}

export interface PlacedGene {
  source: "amrfinderplus" | "vfdb";
  gene: string;
  name: string | null;
  type: string;
  class: string | null;
  contig: string;
  start: number;
  end: number;
  relation: "inside" | "near" | "on_plasmid" | "same_contig";
  distance: number | null;
}

export interface MobilomeAssembly {
  assembly_id: string;
  assembler: string;
  kind: string;
  window: number;
  runs: Record<string, string | null>;
  gene_runs: Record<string, string | null>;
  plasmids: { id: string; contigs: string[]; size: number | null; rep_types: string[] | null; relaxase_types: string[] | null; predicted_mobility: string | null; genes: PlacedGene[] }[];
  replicons: { name: string | null; type: string | null; contig: string | null; start: number | null; end: number | null; plasmid: string | null }[];
  elements: { tool: string; category: string; element: string | null; element_type: string | null; contig: string | null; start: number | null; end: number | null; strand: string | null; completeness: string | null; plasmid: string | null; genes: PlacedGene[] }[];
  counts: Record<string, number>;
}

export interface SampleMobilome {
  sample_id: string;
  window: number;
  assemblies: MobilomeAssembly[];
}

export interface ProjectMobilome {
  project_id: string;
  window: number;
  samples: { sample_id: string; sample_code: string; assembly_id: string | null; counts: Record<string, number> | null; replicon_types: string[]; plasmid_genes: string[]; element_genes: string[] }[];
}

export interface VariantForm {
  technology: Technology;
  referenceKind: "assembly" | "collection";
  assemblyId: string;
  databaseId: string;
  genomeKey: string;
  r1: string;
  r2: string;
  unpaired: string;
  long: string;
  settings: VariantSettings;
  effects: boolean;
  keepAlignment: boolean;
  threads: string;
  confirmed: boolean;
}

/** A reference assembly's name: its sample and assembler (a registered genome's in the interface language, not the
 * API's English label), and whether it is polished. */
export function referenceLabel(t: Translate, a: ReferenceAssemblyOption): string {
  if (!a.mode) return a.label;
  const kind = a.kind === "polished" ? "polished" : "assembly";
  const name = assemblerName(t, { ...a, kind, mode: a.mode as Assembly["mode"], assembler_version: a.assembler_version ?? "" });
  return `${a.sample_code ?? a.assembly_id.slice(0, 8)} · ${name}${kind === "polished" ? ` (${t("annotation.polished")})` : ""}`;
}

export function initialVariantForm(options: VariantOptions | undefined, technology: Technology | null): VariantForm {
  const f = options?.defaults.filters;
  return {
    technology: technology ?? "illumina",
    referenceKind: "assembly",
    assemblyId: options?.assemblies.find((a) => !a.own_sample)?.assembly_id ?? options?.assemblies[0]?.assembly_id ?? "",
    databaseId: options?.collections[0]?.database_id ?? "",
    genomeKey: "",
    r1: "",
    r2: "",
    unpaired: "",
    long: "",
    settings: {
      min_mapq: f?.min_mapq ?? 60, min_baseq: null, max_depth: options?.defaults.max_depth ?? 1000, call_indels: null, prior: 1.1e-3,
      min_qual: f?.min_qual ?? 100, min_depth: f?.min_depth ?? 10, min_alt_fraction: f?.min_alt_fraction ?? 0.9,
    },
    effects: true,
    keepAlignment: false,
    threads: "",
    confirmed: false,
  };
}

export const isLong = (t: Technology) => t !== "illumina";

export function variantBody(form: VariantForm): VariantRequest {
  const inputs = isLong(form.technology)
    ? { long: form.long || null }
    : form.r1 || form.r2 ? { r1: form.r1 || null, r2: form.r2 || null } : { unpaired: form.unpaired || null };
  const reference: VariantReferenceIn = form.referenceKind === "assembly"
    ? { kind: "assembly", assembly_id: form.assemblyId }
    : { kind: "collection", database_id: form.databaseId, genome_key: form.genomeKey };
  const threads = Number.parseInt(form.threads, 10);
  return { technology: form.technology, reference, inputs, settings: form.settings, effects: form.effects, keep_alignment: form.keepAlignment,
    threads: Number.isFinite(threads) && threads > 0 ? threads : null, confirmed: form.confirmed };
}

/** What the form still lacks before a preview makes sense (message keys). */
export function formProblems(form: VariantForm): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (form.referenceKind === "assembly" ? !form.assemblyId : !form.databaseId || !form.genomeKey) out.push("variants.problem.reference");
  if (isLong(form.technology) ? !form.long : !(form.r1 && form.r2) && !form.unpaired) out.push("variants.problem.reads");
  if (!isLong(form.technology) && Boolean(form.r1) !== Boolean(form.r2)) out.push("variants.problem.pair");
  return out;
}

export function effectImpact(effect: string | null): "high" | "moderate" | "low" | "none" {
  if (!effect) return "none";
  if (HIGH.has(effect)) return "high";
  return MODERATE.has(effect) ? "moderate" : "low";
}

/** The first consequence that is not a pointer to another position (bcftools csq writes "@POS" for the other
 * variants of a codon it reports together). */
export function mainConsequence(v: Pick<VariantRecord, "consequences">): Consequence | null {
  return v.consequences.find((c) => c.see_position == null) ?? null;
}

export function linkedPosition(v: Pick<VariantRecord, "consequences">): number | null {
  return v.consequences.find((c) => c.see_position != null)?.see_position ?? null;
}

/** Rows of the distribution chart: bin start (1-based) on the contig, PASS SNPs and PASS other variants. */
export function distributionRows(d: VariantSummary["distribution"], contig: string): [number, number, number][] {
  const c = d.contigs.find((x) => x.contig === contig);
  if (!c) return [];
  return c.snp.map((n, i) => [i * d.bin + 1, n, c.other[i]]);
}

export function histogramLabels(h: Histogram, digits = 0): string[] {
  const last = h.edges.length - 2;
  return h.edges.slice(0, -1).map((e, i) => (i === last ? `≥ ${e.toFixed(digits)}` : `${e.toFixed(digits)}–${h.edges[i + 1].toFixed(digits)}`));
}

/** Order of the samples for the distance heatmap: single-linkage from the first sample, so close samples sit together;
 * a display order only, not a tree. */
export function displayOrder(distances: number[][]): number[] {
  const n = distances.length;
  if (n === 0) return [];
  const order = [0];
  const left = new Set(Array.from({ length: n }, (_, i) => i).slice(1));
  while (left.size) {
    let best = -1;
    let bestD = Infinity;
    for (const j of left) {
      const d = Math.min(...order.map((i) => distances[i][j]));
      if (d < bestD) [best, bestD] = [j, d];
    }
    order.push(best);
    left.delete(best);
  }
  return order;
}

export const relationKey = (r: PlacedGene["relation"]) => `mobilome.relation.${r}` as TranslationKey;
