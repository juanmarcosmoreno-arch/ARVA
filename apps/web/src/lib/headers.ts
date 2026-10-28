/** Display helpers for read-header metadata (arva_core.header_meta). Pure functions, no I/O. */
import { dictionaries, type TranslationKey } from "@/i18n";
import type { DistinctValues, HeaderMetadata, SequencingTechnology } from "./types";

// Same order as the summary keys in arva_core.header_meta.
export const DISTINCT_FIELDS = [
  "instrument",
  "run_number",
  "run_name",
  "flowcell_id",
  "lane",
  "run_id",
  "sample_id",
  "protocol_group_id",
  "basecall_model",
  "basecall_gpu",
  "barcode",
  "barcode_alias",
  "barcode_arrangement",
  "index_sequence",
  "sample_number",
  "umi_present",
  "movie_name",
  "movie_instrument_id",
  "read_type",
  "strand",
  "accession",
  "experiment_start_time",
] as const;

export type DistinctField = (typeof DISTINCT_FIELDS)[number];

const NOT_USABLE = new Set(["empty", "invalid"]);

/** Most frequent usable header format (ties broken by name, as on the server). */
export function dominantFormat(meta: HeaderMetadata | null | undefined): string | null {
  const counts = Object.entries(meta?.format_counts ?? {}).filter(([fmt]) => !NOT_USABLE.has(fmt));
  if (!counts.length) return null;
  counts.sort(([a, na], [b, nb]) => nb - na || (a < b ? 1 : a > b ? -1 : 0));
  return counts[0][0];
}

export function distinctRows(meta: HeaderMetadata | null | undefined): ({ key: DistinctField } & DistinctValues)[] {
  const distinct = meta?.distinct ?? {};
  return DISTINCT_FIELDS.filter((key) => distinct[key]?.values?.length).map((key) => ({ key, ...distinct[key] }));
}

/** A translation key built from a server code, or null for codes this UI version does not know. */
export function codeKey(prefix: string, code: string): TranslationKey | null {
  const key = `${prefix}.${code}`;
  return key in dictionaries.en ? (key as TranslationKey) : null;
}

export type SuggestionState = "none" | "offer" | "agrees" | "mismatch";

/** "offer" only when the user has not recorded a technology: ARVA never replaces a user value. */
export function suggestionState(user: SequencingTechnology, suggested: SequencingTechnology | null): SuggestionState {
  if (!suggested) return "none";
  if (user === "unknown") return "offer";
  return user === suggested ? "agrees" : "mismatch";
}

/** Unique documentation sources; only plain https URLs become links. */
export function documentationLinks(sources: Record<string, string[]> | null | undefined): { text: string; href: string | null }[] {
  const seen = new Set<string>();
  const out: { text: string; href: string | null }[] = [];
  for (const list of Object.values(sources ?? {})) {
    for (const text of list ?? []) {
      if (typeof text !== "string" || seen.has(text)) continue;
      seen.add(text);
      const first = text.split(" ")[0];
      out.push({ text, href: /^https:\/\/[^\s"'<>]+$/.test(first) ? first : null });
    }
  }
  return out;
}
