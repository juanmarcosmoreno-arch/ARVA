import type { QueryClient, QueryKey } from "@tanstack/react-query";

/** A query whose key is [name, sampleId, ...] holds results of that sample (assemblies, MLST, AMR, virulence,
 * plasmids, typing, variants, Sanger…). The job list itself is left out: it drives this refresh. */
export function isSampleResultKey(key: QueryKey, sampleId: string): boolean {
  return key.length >= 2 && key[1] === sampleId && key[0] !== "jobs";
}

/** Refetch every result of a sample, and the cross-check data that spans samples, after one of its jobs finished.
 * Each tab reads its results with its own query; listing the keys one by one left the newer tabs (AMR, virulence,
 * plasmids, typing, variants) stale until the page was opened again. */
export function refreshSampleResults(queryClient: QueryClient, sampleId: string): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ predicate: (q) => isSampleResultKey(q.queryKey, sampleId) }),
    queryClient.invalidateQueries({ queryKey: ["crosscheck"] }),
  ]).then(() => undefined);
}
