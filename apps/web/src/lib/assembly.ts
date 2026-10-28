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

/** A short, unique label for an assembly: assembler, version, read type and the start of its id. */
export const assemblyLabel = (a: Pick<Assembly, "assembler" | "assembler_version" | "read_type" | "id">) =>
  `${a.assembler} ${a.assembler_version} · ${a.read_type} · ${a.id.slice(0, 8)}`;

/** Segments with a link from the segment to itself (a circular piece of the graph), with the orientations. */
export function selfLinks(graph: Pick<AssemblyGraph, "edges">): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (e.source === e.target) out.set(e.source, [...(out.get(e.source) ?? []), `${e.source_orientation}→${e.target_orientation}`]);
  }
  return out;
}
