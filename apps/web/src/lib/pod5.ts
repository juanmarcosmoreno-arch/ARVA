/** Display helpers for POD5 run metadata (pod5_summary jobs). Pure functions, no I/O. */
import type { Pod5RunInfo, Pod5Summary } from "./types";

type TextField = Exclude<keyof Pod5RunInfo, "sample_rate" | "reads" | "samples" | "signal_duration_s">;

/** Distinct non-empty values in first-seen order (several acquisitions after a merge). */
export function distinctValues(infos: Pod5RunInfo[], key: TextField): string[] {
  const out: string[] = [];
  for (const info of infos) {
    const v = info[key];
    if (typeof v === "string" && v.trim() && !out.includes(v)) out.push(v);
  }
  return out;
}

export interface RunOverview {
  sampleRates: number[];
  flowCells: string[];
  kits: string[];
  protocols: string[];
  experiments: string[];
  samples: string[];
  software: string[];
  /** Earliest acquisition start, as written in the file (with its UTC offset). */
  runStart: string | null;
}

export function runOverview(summary: Pod5Summary): RunOverview {
  const infos = summary.run_infos;
  const flowCells: string[] = [];
  for (const i of infos) {
    const label = [i.flow_cell_id, i.flow_cell_product_code ? `(${i.flow_cell_product_code})` : ""].filter(Boolean).join(" ");
    if (label && !flowCells.includes(label)) flowCells.push(label);
  }
  const starts = infos
    .map((i) => i.acquisition_start_time)
    .filter((s): s is string => !!s && !Number.isNaN(Date.parse(s)))
    .sort((a, b) => Date.parse(a) - Date.parse(b));
  return {
    sampleRates: [...new Set(infos.map((i) => i.sample_rate).filter((r): r is number => typeof r === "number" && r > 0))],
    flowCells,
    kits: distinctValues(infos, "sequencing_kit"),
    protocols: distinctValues(infos, "protocol_name"),
    experiments: distinctValues(infos, "experiment_name"),
    samples: distinctValues(infos, "sample_id"),
    software: distinctValues(infos, "software"),
    runStart: starts[0] ?? null,
  };
}

export const signalHours = (seconds: number | null | undefined) => (seconds == null ? null : seconds / 3600);

/** "2026-01-02T03:04:05.678000+00:00" → "2026-01-02 03:04:05 +00:00": the run's own clock, not the viewer's. */
export function fileTime(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.exec(iso);
  if (!m) return iso;
  return `${m[1]} ${m[2]}${m[3] ? ` ${m[3] === "Z" ? "+00:00" : m[3]}` : ""}`;
}
