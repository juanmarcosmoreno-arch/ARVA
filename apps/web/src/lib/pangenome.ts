/** Pangenome of a comparison set (Panaroo, or PPanGGOLiN when installed): request and result types and the pure
 * helpers behind the category, curve, distribution and heatmap views (tested in pangenome.test.tsx). */
import type { ComparisonPlan, ComparisonResultRead } from "./comparative";

export type PangenomeMethod = "panaroo" | "ppanggolin";
export type Category = "core" | "soft_core" | "shell" | "cloud";
export const CATEGORIES: Category[] = ["core", "soft_core", "shell", "cloud"];
export const CLEAN_MODES = ["strict", "moderate", "sensitive"] as const;
export const ALIGNMENTS = ["none", "core", "pan"] as const;

export interface PanarooSettings {
  clean_mode: (typeof CLEAN_MODES)[number];
  identity: number;
  family_threshold: number;
  length_difference: number;
  family_length_difference: number;
  merge_paralogs: boolean;
  remove_invalid_genes: boolean;
  search_radius: number;
  refind_prop_match: number;
  refind_mode: "default" | "strict" | "off";
  length_outlier_support_proportion: number;
  high_var_flag: number;
  alignment: (typeof ALIGNMENTS)[number];
  aligner: "mafft";
  core_threshold: number;
  codon_table: number;
}

/** Panaroo 1.8.1's own defaults (passed explicitly; see arva_tools/pangenome.py). */
export const PANAROO_DEFAULTS: PanarooSettings = {
  clean_mode: "strict", identity: 0.98, family_threshold: 0.7, length_difference: 0.98, family_length_difference: 0,
  merge_paralogs: false, remove_invalid_genes: false, search_radius: 5000, refind_prop_match: 0.2, refind_mode: "default",
  length_outlier_support_proportion: 0.1, high_var_flag: 5, alignment: "none", aligner: "mafft", core_threshold: 0.95,
  codon_table: 11,
};

export interface Thresholds {
  core: number;
  soft_core: number;
  shell: number;
}

/** ARVA's default category thresholds: the ones Panaroo's summary_statistics.txt uses. */
export const DEFAULT_THRESHOLDS: Thresholds = { core: 0.99, soft_core: 0.95, shell: 0.15 };

export interface PangenomeRequest {
  method: PangenomeMethod;
  genomes: string[] | null;
  panaroo: PanarooSettings;
  categories: Thresholds;
  curves: { permutations: number; seed: number };
  threads: number | null;
  confirmed: boolean;
}

export interface PangenomeAnnotation {
  annotation_id: string;
  tool: string;
  tool_version: string;
  database_version: string | null;
  gff3_sha256: string | null;
  gff3_present: boolean;
  cds_searched: boolean;
}

export type PangenomePlan = Omit<ComparisonPlan, "analysis" | "genomes"> & {
  analysis: "pangenome";
  genomes: (ComparisonPlan["genomes"][number] & { annotation: PangenomeAnnotation | null })[];
  annotation_consistency: { consistent: boolean; annotators: { annotator: string; genomes: string[] }[] };
};

export interface Stat {
  mean: number[];
  sd: number[];
  min: number[];
  max: number[];
}

export interface Family {
  name: string;
  gene_names: string[];
  annotation: string;
  count: number;
  category: Category;
  partition: "persistent" | "shell" | "cloud" | null;
  members: number;
  presence: string;
}

export interface PangenomeData {
  genomes: { label: string; tool_name: string; assembly_id: string; sample_id: string | null; annotation_id: string }[];
  families: Family[];
  family_order: number[];
  clustering: { order: number[]; merges: [number, number, number, number][]; method: string; distances: number[][] };
  curves: { method: string; permutations: number; seed: number; k: number[]; pan: Stat; core: Stat };
  distribution: { genomes: number; families: number }[];
}

export interface PangenomeSummary {
  genomes: number;
  families: number;
  category_counts: Record<Category, number>;
  thresholds: Thresholds;
  tool_summary: (Record<Category, number> & { total: number }) | null;
  partitions: { persistent: number; shell: number; cloud: number } | null;
  annotation_consistency: PangenomePlan["annotation_consistency"] | null;
  per_genome: { label: string; families: number; unique: number }[];
  aligned: boolean;
}

export function pangenomeOf(result: ComparisonResultRead): { summary: PangenomeSummary; data: PangenomeData | null } {
  return { summary: result.summary as unknown as PangenomeSummary, data: (result.data ?? null) as unknown as PangenomeData | null };
}

export interface FamilyMember {
  genome: string;
  genome_index: number;
  gene_id: string;
  flags: string[];
  feature: { annotation_id: string; feature_id: number; locus_tag: string | null; gene: string | null; product: string | null;
    contig: string; start: number; end: number; strand: string } | null;
  refound: { start: number; end: number; strand: string } | null;
  contig: string | null;
  dna_length: number | null;
  protein_length: number | null;
  dna: string | null;
  protein: string | null;
}

export interface FamilyDetail extends Omit<Family, "members"> {
  index: number;
  members: FamilyMember[];
  members_total: number;
  alignment: { file: string; columns: number; rows: { name: string; genome: string | null; gene_id: string | null; sequence: string }[] } | null;
  neighbours: { index: number; name: string; annotation: string; genomes: number }[];
  method: PangenomeMethod;
}

export interface MetadataField {
  key: string;
  custom: boolean;
  values: (string | null)[];
  recorded: number;
  distinct: number;
}

export interface AssociationRow {
  group: string;
  family: string;
  family_index: number;
  in_group: number;
  group_size: number;
  in_others: number;
  others_size: number;
  share_group: number;
  share_group_ci: [number, number] | null;
  share_others: number;
  share_others_ci: [number, number] | null;
  odds_ratio: number;
  odds_ratio_ci: [number, number];
  haldane_corrected: boolean;
  p: number;
  q: number;
}

export interface Associations {
  field: string;
  values: Record<string, string | null>;
  groups: { group: string; genomes: number; pan: number; core: number; exclusive: number; families_mean: number; families_sd: number | null }[];
  genomes_with_value: number;
  genomes_without_value: number;
  families_tested: number;
  tests: number;
  tested_groups: { group: string; genomes: number; others: number }[];
  skipped_groups: { group: string; genomes: number }[];
  min_group: number;
  rows: AssociationRow[];
  rows_total: number;
  method: string;
  note: string;
  small_sample: boolean;
}

/** Families of the heatmap: accessory families (not core) in ARVA's family order, at most `limit`; the genomes in the
 * clustering order. Cells are [genome position, family position, 0 | 1]. */
export function heatmap(data: PangenomeData, limit: number): { genomes: string[]; families: string[]; cells: [number, number, number][]; hidden: number } {
  const order = data.clustering.order;
  const accessory = data.family_order.filter((i) => data.families[i].category !== "core");
  const shown = accessory.slice(0, limit);
  const cells: [number, number, number][] = [];
  shown.forEach((fi, y) => order.forEach((gi, x) => cells.push([x, y, data.families[fi].presence[gi] === "1" ? 1 : 0])));
  return { genomes: order.map((i) => data.genomes[i].label), families: shown.map((i) => data.families[i].name), cells,
    hidden: accessory.length - shown.length };
}

/** Lower edge and band height (max - min) per k, for a stacked area drawn between the minimum and maximum. */
export function band(s: Stat): { low: number[]; height: number[] } {
  return { low: s.min, height: s.max.map((v, i) => v - s.min[i]) };
}

/** Families whose name, gene names or annotation contain `query` (case-insensitive), in one category or all. */
export function filterFamilies(families: Family[], query: string, category: Category | "all"): number[] {
  const q = query.trim().toLowerCase();
  const out: number[] = [];
  families.forEach((f, i) => {
    if (category !== "all" && f.category !== category) return;
    if (q && !`${f.name} ${f.gene_names.join(" ")} ${f.annotation}`.toLowerCase().includes(q)) return;
    out.push(i);
  });
  return out;
}

/** Genomes holding a family, as labels. */
export function holders(data: PangenomeData, family: Family): string[] {
  return data.genomes.filter((_, i) => family.presence[i] === "1").map((g) => g.label);
}

/** A p- or q-value for tables: three significant digits, scientific below 0.001. */
export function fmtP(v: number): string {
  if (v === 0) return "0";
  return v < 0.001 ? v.toExponential(2) : v.toPrecision(3);
}
