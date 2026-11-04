import type { Translate } from "@/i18n";
import { fmtBases, fmtDate } from "./format";
import type { AnalysisJobDetail, Assembly, AssemblyContig, AssemblyCurve, AssemblyGraph, AssemblyGraphNode, RawFile } from "./types";

export type SortDir = "asc" | "desc";
export type ContigSortKey = "rank" | "name" | "length" | "coverage" | "gc_percent" | "circular" | "repeat";

/** Contig rows sorted by one column; contigs without a value (null) always come last, ties keep the length rank. */
export function sortContigs(rows: AssemblyContig[], key: ContigSortKey, dir: SortDir): AssemblyContig[] {
  const sign = dir === "asc" ? 1 : -1;
  const value = (c: AssemblyContig): string | number | null => {
    const v = c[key];
    return typeof v === "boolean" ? Number(v) : v;
  };
  return [...rows].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va === null || vb === null) return va === vb ? a.rank - b.rank : va === null ? 1 : -1;
    const cmp = typeof va === "string" ? va.localeCompare(String(vb)) : va - (vb as number);
    return cmp !== 0 ? sign * cmp : a.rank - b.rank;
  });
}

/** Points of the Nx curve: each ranked contig is a step at its length, from the share of the total length before
 * it to the share including it (x in %). N50 is the length where the curve crosses x = 50. */
export function nxSteps(curve: AssemblyCurve, total: number): [number, number][] {
  const out: [number, number][] = [];
  curve.length.forEach((len, i) => {
    const end = curve.cumulative_length[i];
    out.push([(100 * (end - len)) / total, len], [(100 * end) / total, len]);
  });
  return out;
}

export const cumulativePoints = (curve: AssemblyCurve): [number, number][] => curve.rank.map((r, i) => [r, curve.cumulative_length[i]]);

export type NodeKind = "circular" | "repeat" | "other" | "unknown";

/** How a graph segment is coloured: from the assembler's flags of the contigs whose GFA path runs through it. */
export function nodeKind(n: Pick<AssemblyGraphNode, "circular" | "repeat" | "paths">): NodeKind {
  if (n.circular) return "circular";
  if (n.repeat) return "repeat";
  return n.circular === false || n.repeat === false ? "other" : "unknown";
}

export const NODE_KINDS: NodeKind[] = ["circular", "repeat", "other", "unknown"];

/** Node size in px, by the square root of the segment length relative to the longest shown segment. */
export function nodeSize(length: number, longest: number): number {
  return 6 + 34 * Math.sqrt(longest > 0 ? length / longest : 0);
}

/** The segment's coverage from the tag the assembler uses for it (Flye: dp), when known. */
export function segmentCoverage(graph: Pick<AssemblyGraph, "coverage_tag">, node: Pick<AssemblyGraphNode, "tags">): number | null {
  const tag = graph.coverage_tag;
  return tag && typeof node.tags[tag] === "number" ? node.tags[tag] : null;
}

/** Live elapsed time of a run: from the tool's start (or the job's) to now, or the recorded duration once it ended. */
export function elapsedSeconds(job: Pick<AnalysisJobDetail, "status" | "started_at" | "duration_seconds" | "progress">, now: number): number | null {
  if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") return job.duration_seconds ?? job.progress?.elapsed_seconds ?? null;
  const start = job.progress?.started_at ?? job.started_at;
  if (!start) return job.progress?.elapsed_seconds ?? null;
  return Math.max(0, (now - Date.parse(start)) / 1000);
}

/** The file and the files it was derived from, back to the imported original (names, newest first). */
export function lineageNames(file: RawFile, files: RawFile[]): string[] {
  const byId = new Map(files.map((f) => [f.id, f]));
  const names = [file.original_filename];
  const seen = new Set([file.id]);
  for (let p = file.parent_file_id ? byId.get(file.parent_file_id) : undefined; p && !seen.has(p.id); p = p.parent_file_id ? byId.get(p.parent_file_id) : undefined) {
    seen.add(p.id);
    names.push(p.original_filename);
  }
  return names;
}

/** Assemblies overlaid in the comparison: the newest ones, as many as the chart palette has distinct colours. */
export const MAX_COMPARED = 6;
export function compared(assemblies: Assembly[]): Assembly[] {
  return [...assemblies].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, MAX_COMPARED);
}

type Provenance = Pick<Assembly, "assembler" | "assembler_version" | "mode" | "kind"> & Pick<Partial<Assembly>, "declared_assembler" | "declared_assembler_version">;

/** A genome FASTA registered by the user (an imported assembly that is not a polished version of one): ARVA did not
 * assemble it. Its `assembler` is the API's fixed "Imported genome" and its `assembler_version` the source the user
 * stated (apps/api/app/services/jobs.py, create_assembly_import_job). */
export const isRegistered = (a: Pick<Assembly, "mode" | "kind">) => a.mode === "imported" && a.kind !== "polished";

/** Whether ARVA polishes the assembly: its own assemblies, drafts the user declared as assembled outside ARVA from this
 * sample's reads, and polished versions of either (apps/api/app/services/polishing.py, draft_for). */
export const canPolish = (a: Pick<Assembly, "mode" | "kind"> & Pick<Partial<Assembly>, "declared_assembler">) =>
  !isRegistered(a) || Boolean(a.declared_assembler);

/** The assembler's name for display: ARVA's tool, or for a registered genome a translated name (with the assembler the
 * user declared for a draft assembled outside ARVA). */
export function assemblerName(t: Translate, a: Provenance): string {
  if (!isRegistered(a)) return a.assembler;
  return a.declared_assembler ? t("assembly.imported.declaredName", { assembler: a.declared_assembler }) : t("assembly.imported.name");
}

/** The assembler and its version, or what a registered genome is (never the API's English "Imported genome"). */
export function assemblerWithVersion(t: Translate, a: Provenance): string {
  if (!isRegistered(a)) return `${a.assembler} ${a.assembler_version}`;
  return a.declared_assembler
    ? t("assembly.imported.declaredLabel", { assembler: a.declared_assembler, version: a.declared_assembler_version ?? "?" })
    : t("assembly.imported.name");
}

/** The assembler name the API gives every registered genome (apps/api/app/services/jobs.py, IMPORTED_ASSEMBLER). */
export const IMPORTED_ASSEMBLER = "Imported genome";

/** "Assembler version" for rows that carry only those two fields: a registered genome is named in the interface
 * language, followed by its source (the version the API records for it). */
export function assemblerText(t: Translate, assembler: string, version: string): string {
  return assembler === IMPORTED_ASSEMBLER ? `${t("assembly.imported.name")} · ${version}` : `${assembler} ${version}`;
}

/** What tells assemblies of one assembler apart: the read type (ARVA's), "polished", or a registered genome's source. */
function assemblyDetail(t: Translate, a: Provenance & Pick<Assembly, "read_type">, polished: boolean): string {
  if (isRegistered(a)) return a.assembler_version;
  return polished && a.kind === "polished" ? t("annotation.polished") : a.read_type;
}

/** A short, unique label for an assembly: assembler and version, read type (or a registered genome's source) and the
 * start of its id. */
export const assemblyLabel = (t: Translate, a: Provenance & Pick<Assembly, "read_type" | "id">) =>
  `${assemblerWithVersion(t, a)} · ${assemblyDetail(t, a, false)} · ${a.id.slice(0, 8)}`;

/** The option text of an assembly in the analysis dialogs (annotation, species, MLST, AMR, virulence, mobile
 * elements, typing): assembler and version, read type, "polished" or a registered genome's source, contigs, length,
 * date and the start of its id. */
export const assemblyOptionLabel = (t: Translate, a: Provenance & Pick<Assembly, "read_type" | "id" | "stats" | "created_at">) =>
  [
    assemblerWithVersion(t, a),
    assemblyDetail(t, a, true),
    t("assembly.option.contigs", { count: a.stats.contig_count }),
    fmtBases(a.stats.total_length),
    fmtDate(a.created_at),
    a.id.slice(0, 8),
  ].join(" · ");

/** Segments with a link from the segment to itself (a circular piece of the graph), with the orientations. */
export function selfLinks(graph: Pick<AssemblyGraph, "edges">): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (e.source === e.target) out.set(e.source, [...(out.get(e.source) ?? []), `${e.source_orientation}→${e.target_orientation}`]);
  }
  return out;
}
