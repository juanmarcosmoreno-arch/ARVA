/** Helpers for the sample-metadata import dialog. Pure functions, no I/O. */
import type {
  MetadataAction,
  MetadataColumn,
  MetadataField,
  MetadataImportMode,
  MetadataPreview,
  MetadataRowPreview,
  MetadataTarget,
} from "./types";

export const METADATA_FIELDS: MetadataField[] = [
  "sample_code",
  "organism",
  "expected_species",
  "sample_type",
  "host",
  "geographic_origin",
  "collection_date",
  "sequencing_technology",
  "sequencing_run",
  "researcher",
  "institution",
  "description",
  "notes",
];

export const DELIMITERS = [
  { value: ",", name: "comma" },
  { value: ";", name: "semicolon" },
  { value: "\t", name: "tab" },
  { value: "|", name: "pipe" },
] as const;

export type DelimiterName = (typeof DELIMITERS)[number]["name"];

export const delimiterName = (value: string | null): DelimiterName | null =>
  DELIMITERS.find((d) => d.value === value)?.name ?? null;

const isField = (target: MetadataTarget): target is MetadataField => target !== "custom" && target !== "ignore";

/** What the dropdowns show: the user's choices over the mapping the server applied. */
export function currentMapping(columns: MetadataColumn[], choices: Record<string, MetadataTarget>): Record<string, MetadataTarget> {
  return Object.fromEntries(columns.map((c) => [c.header, choices[c.header] ?? c.field]));
}

/** ARVA fields chosen for more than one column; the server refuses such a mapping. */
export function duplicateTargets(mapping: Record<string, MetadataTarget>): MetadataField[] {
  const seen = new Set<MetadataField>();
  const dup = new Set<MetadataField>();
  for (const target of Object.values(mapping)) {
    if (!isField(target)) continue;
    if (seen.has(target)) dup.add(target);
    seen.add(target);
  }
  return METADATA_FIELDS.filter((f) => dup.has(f));
}

export type RowFilter = "all" | MetadataAction;

export function filterRows(rows: MetadataRowPreview[], filter: RowFilter): MetadataRowPreview[] {
  return filter === "all" ? rows : rows.filter((r) => r.action === filter);
}

/** What Apply writes in the chosen mode: updates are skipped when only new samples may be created. */
export function applyPlan(counts: MetadataPreview["counts"], mode: MetadataImportMode) {
  const update = mode === "create_only" ? 0 : counts.update;
  return { create: counts.create, update, skipped: counts.error + (counts.update - update) };
}

/** The date-order choice matters only when ambiguous dates exist or an order is already in force. */
export const showDateOrder = (preview: MetadataPreview) => preview.ambiguous_dates > 0 || preview.date_order !== null;

export const shortSha = (sha: string) => sha.slice(0, 12);

export interface MappingSummary {
  fields: [string, MetadataField][];
  custom: string[];
  ignored: string[];
}

export function summariseMapping(mapping: Record<string, MetadataTarget>): MappingSummary {
  const out: MappingSummary = { fields: [], custom: [], ignored: [] };
  for (const [header, target] of Object.entries(mapping)) {
    if (target === "custom") out.custom.push(header);
    else if (target === "ignore") out.ignored.push(header);
    else out.fields.push([header, target]);
  }
  return out;
}

/** Custom metadata as display text: strings as written, other JSON values serialised. */
export function customEntries(custom: Record<string, unknown> | null | undefined): [string, string][] {
  return Object.entries(custom ?? {}).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]);
}

export interface CustomEdit {
  key: string;
  text: string;
  removed: boolean;
}

export const customDraft = (custom: Record<string, unknown> | null | undefined): CustomEdit[] =>
  customEntries(custom).map(([key, text]) => ({ key, text, removed: false }));

/** The custom_metadata to save: removed or cleared fields are dropped, edited values are stored as text and
 * untouched values keep their original type. null when no field is left. */
export function applyCustomEdits(original: Record<string, unknown> | null | undefined, draft: CustomEdit[]): Record<string, unknown> | null {
  const before = new Map(customEntries(original));
  const out: Record<string, unknown> = {};
  for (const e of draft) {
    const text = e.text.trim();
    if (e.removed || !text) continue;
    out[e.key] = text === before.get(e.key) ? original?.[e.key] : text;
  }
  return Object.keys(out).length ? out : null;
}

export function customEditsChange(original: Record<string, unknown> | null | undefined, draft: CustomEdit[]): boolean {
  const next = applyCustomEdits(original, draft);
  const keys = Object.keys(original ?? {});
  if (!next) return keys.length > 0;
  return keys.length !== Object.keys(next).length || keys.some((k) => !(k in next) || next[k] !== original?.[k]);
}
