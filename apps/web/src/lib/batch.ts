import type { BatchAnalysis, BatchDecision, BatchQcPlan } from "./types";

export const BATCH_ANALYSES: BatchAnalysis[] = ["sequence_stats", "seqkit", "fastqc"];

/** Why files of a sample get no job: each reason with the number of files it applies to (for at least one of the
 * chosen analyses), most frequent first. */
export function skipSummary(sample: BatchQcPlan["samples"][number]): [Exclude<BatchDecision, "run">, number][] {
  const counts = new Map<Exclude<BatchDecision, "run">, number>();
  for (const f of sample.files) {
    const reasons = new Set(Object.values(f.decisions).filter((d): d is Exclude<BatchDecision, "run"> => !!d && d !== "run"));
    for (const d of reasons) counts.set(d, (counts.get(d) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}
