import type { TranslationKey } from "@/i18n";
import { bpUnit, fmtInt, fmtNum } from "./format";
import { basename } from "./results";
import type { NanoplotStats, SequenceStats, SequencingTechnology } from "./types";

export const NANOPLOT_JOB = "nanoplot";

/** Technologies for which NanoPlot runs without the user confirming that the file holds long reads. */
export const isLongReadTechnology = (t: SequencingTechnology) => t === "nanopore" || t === "pacbio";

export function nanoplotOutputs(paths: string[] | null | undefined) {
  const names = (paths ?? []).map(basename);
  return {
    report: names.find((n) => n.endsWith("_NanoPlot-report.html")),
    stats: names.find((n) => n.endsWith("_NanoStats.txt")),
    postFiltering: names.find((n) => n.endsWith("_NanoStats_post_filtering.txt")),
    log: names.find((n) => /_NanoPlot_\d{8}_\d{4}\.log$/.test(n)),
  };
}

type StatKey = "number_of_reads" | "number_of_bases" | "mean_read_length" | "median_read_length" | "read_length_stdev" | "n50" | "mean_qual" | "median_qual";
export type StatKind = "count" | "bp" | "q";

/** NanoPlot's statistics in display order, each with NanoPlot's definition. */
export const STAT_ROWS: { key: StatKey; label: TranslationKey; definition: TranslationKey; kind: StatKind }[] = [
  { key: "number_of_reads", label: "nanoplot.stat.reads", definition: "nanoplot.def.reads", kind: "count" },
  { key: "number_of_bases", label: "nanoplot.stat.bases", definition: "nanoplot.def.bases", kind: "count" },
  { key: "mean_read_length", label: "nanoplot.stat.meanLength", definition: "nanoplot.def.meanLength", kind: "bp" },
  { key: "median_read_length", label: "nanoplot.stat.medianLength", definition: "nanoplot.def.medianLength", kind: "bp" },
  { key: "read_length_stdev", label: "nanoplot.stat.sdLength", definition: "nanoplot.def.sdLength", kind: "bp" },
  { key: "n50", label: "nanoplot.stat.n50", definition: "nanoplot.def.n50", kind: "bp" },
  { key: "mean_qual", label: "nanoplot.stat.meanQual", definition: "nanoplot.def.meanQual", kind: "q" },
  { key: "median_qual", label: "nanoplot.stat.medianQual", definition: "nanoplot.def.medianQual", kind: "q" },
];

/** NanoPlot prints values with one decimal; whole numbers are shown without it. */
export function formatNanoplot(value: number, kind: StatKind): string {
  const n = Number.isInteger(value) ? fmtInt(value) : fmtNum(value, 1);
  if (kind === "bp") return `${n} ${bpUnit()}`;
  if (kind === "q") return `Q${fmtNum(value, 1)}`;
  return n;
}

export type CheckStatus = "agrees" | "explained" | "differs";

export interface CheckRow {
  metric: "reads" | "bases";
  arva: number;
  nanoplot: number;
  status: CheckStatus;
}

/** ARVA's zero-length records; older statistics lack the count but have none if the shortest read is not empty. */
export function zeroLengthReads(arva: Pick<SequenceStats, "zero_length_reads" | "min_length">): number | null {
  return arva.zero_length_reads ?? (arva.min_length > 0 ? 0 : null);
}

/**
 * Only reads and bases have identical definitions in ARVA and NanoPlot. nanoget skips zero-length records that
 * ARVA counts, so a read count lower by exactly that number is explained rather than a disagreement.
 */
export function nanoplotCrossCheck(
  arva: Pick<SequenceStats, "read_count" | "total_bases" | "zero_length_reads" | "min_length">,
  np: Pick<NanoplotStats, "number_of_reads" | "number_of_bases">,
): CheckRow[] {
  const zero = zeroLengthReads(arva);
  const reads: CheckStatus =
    np.number_of_reads === arva.read_count ? "agrees" : zero && np.number_of_reads === arva.read_count - zero ? "explained" : "differs";
  return [
    { metric: "reads", arva: arva.read_count, nanoplot: np.number_of_reads, status: reads },
    { metric: "bases", arva: arva.total_bases, nanoplot: np.number_of_bases, status: np.number_of_bases === arva.total_bases ? "agrees" : "differs" },
  ];
}

export interface SideBySideRow {
  id: string;
  /** Quality threshold for the reads-above rows. */
  threshold?: number;
  arva: number;
  nanoplot: number;
}

/** Metrics with similar names but different definitions: shown next to each other, never judged equal or not. */
export function nanoplotSideBySide(arva: Pick<SequenceStats, "n50" | "quality">, np: Pick<NanoplotStats, "n50" | "reads_above_quality">): SideBySideRow[] {
  const rows: SideBySideRow[] = [{ id: "n50", arva: arva.n50, nanoplot: np.n50 }];
  for (const above of np.reads_above_quality) {
    const mine = arva.quality?.reads_above_quality.find((r) => r.threshold === above.threshold);
    if (mine) rows.push({ id: `q${above.threshold}`, threshold: above.threshold, arva: mine.reads, nanoplot: above.reads });
  }
  return rows;
}
