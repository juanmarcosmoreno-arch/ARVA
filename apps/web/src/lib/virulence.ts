import type { TranslationKey, TranslationVars } from "@/i18n";
import { fmtInt, fmtNum } from "@/lib/format";
import { messageText } from "@/lib/messages";
import type { Cell } from "@/lib/tableExport";
import type { VirulenceFlag, VirulenceRun, VirulenceSample } from "@/lib/types";

type T = (key: TranslationKey, vars?: TranslationVars) => string;
type View = VirulenceSample["assemblies"][number];

const PERCENT = new Set(["identity", "coverage"]);
const POSITION = new Set(["ref_start", "ref_end", "ref_length"]);

/** A row flag of the combined table in the interface language (virulence.flag.<code>), percentages with two
 * decimals and positions as integers in the locale. */
export function flagText(t: T, f: VirulenceFlag): string {
  const params: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(f.params ?? {}))
    params[k] = typeof v === "number" && PERCENT.has(k) ? fmtNum(v, 2) : typeof v === "number" && POSITION.has(k) ? fmtInt(v) : v;
  return messageText(t, "virulence.flag", { code: f.code, params, text: f.code });
}

export const COMBINED_COLUMNS = [
  "assembly_id", "source", "tool", "tool_version", "database_version", "vfdb_set", "gene", "product", "virulence_factor", "category", "match_type", "method",
  "identity", "coverage", "ref_start", "ref_end", "ref_length", "contig", "start", "end", "strand", "reference_accession",
  "also_found_by", "flags", "notes",
];

const TOOL_NAME: Record<string, string> = { vfdb: "ABRicate", amrfinderplus: "AMRFinderPlus" };

/** The combined virulence table as it is shown, one row per hit: its origin (tool, version and database version of
 * the run it comes from), the hit, where it lies, the other source's overlapping rows and ARVA's notes (flag codes,
 * and their text in the interface language). Numbers are written as the tools reported them. */
export function combinedTable(t: T, view: View, runs: VirulenceRun[] = []): { columns: string[]; rows: Cell[][] } {
  const vfRun = runs.find((r) => r.job_id === view.sources.vfdb.job_id);
  const rows = view.rows.map((r): Cell[] => {
    const s = view.sources[r.source];
    const flags = r.flags ?? [];
    return [
      view.assembly_id, r.source, s.tool ?? (r.source === "vfdb" ? vfRun?.tool : null) ?? TOOL_NAME[r.source], s.tool_version, s.database_version,
      r.source === "vfdb" ? (s.vfdb_set ?? vfRun?.vfdb?.set ?? null) : null,
      r.gene, r.description, r.vf_name, r.vf_category, r.kind, r.method,
      r.identity, r.coverage, r.ref_start, r.ref_end, r.ref_length, r.contig, r.start, r.end, r.strand, r.reference,
      r.also_found_by.join("; "), flags.map((f) => f.code).join("; "), flags.map((f) => flagText(t, f)).join(" "),
    ];
  });
  return { columns: COMBINED_COLUMNS, rows };
}

/** File name of the combined table: the assembly's short id, never a sample name. */
export const combinedFileName = (view: View, format: "tsv" | "csv") => `ARVA_virulence_${view.assembly_id.slice(0, 8)}.${format}`;
