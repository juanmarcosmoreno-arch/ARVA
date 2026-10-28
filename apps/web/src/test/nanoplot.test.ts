import { describe, expect, it } from "vitest";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import {
  STAT_ROWS,
  formatNanoplot,
  isLongReadTechnology,
  nanoplotCrossCheck,
  nanoplotOutputs,
  nanoplotSideBySide,
  zeroLengthReads,
} from "@/lib/nanoplot";
import { jobLabel } from "@/lib/results";
import type { NanoplotStats, SequenceStats } from "@/lib/types";

// NanoStats.txt of the synthetic nanopore reads (NanoPlot 1.48.0) and ARVA's statistics of the same file.
const np: Pick<NanoplotStats, "number_of_reads" | "number_of_bases" | "n50" | "reads_above_quality"> = {
  number_of_reads: 400,
  number_of_bases: 1513780,
  n50: 4817,
  reads_above_quality: [
    { threshold: 10, reads: 341, percent: 85.2, megabases: 1.3 },
    { threshold: 15, reads: 0, percent: 0, megabases: 0 },
    { threshold: 25, reads: 0, percent: 0, megabases: 0 },
  ],
};
const quality = {
  reads_above_quality: [
    { threshold: 10, reads: 341, percent: 85.25 },
    { threshold: 15, reads: 0, percent: 0 },
    { threshold: 20, reads: 0, percent: 0 },
  ],
} as SequenceStats["quality"];
const arva = { read_count: 400, zero_length_reads: 0, total_bases: 1513780, min_length: 120, n50: 4817, quality };

describe("nanoplotCrossCheck", () => {
  it("checks only reads and bases, which both tools define identically", () => {
    expect(nanoplotCrossCheck(arva, np)).toEqual([
      { metric: "reads", arva: 400, nanoplot: 400, status: "agrees" },
      { metric: "bases", arva: 1513780, nanoplot: 1513780, status: "agrees" },
    ]);
  });

  it("explains a read count lower by exactly ARVA's zero-length records (nanoget skips them)", () => {
    const rows = nanoplotCrossCheck({ ...arva, read_count: 402, zero_length_reads: 2, min_length: 0 }, np);
    expect(rows.map((r) => r.status)).toEqual(["explained", "agrees"]);
    expect(nanoplotCrossCheck({ ...arva, read_count: 403, zero_length_reads: 2, min_length: 0 }, np)[0].status).toBe("differs");
  });

  it("never hides a difference it cannot explain", () => {
    expect(nanoplotCrossCheck({ ...arva, read_count: 401, zero_length_reads: 0 }, np)[0].status).toBe("differs");
    expect(nanoplotCrossCheck({ ...arva, total_bases: 1513781 }, np)[1].status).toBe("differs");
    // Older ARVA results without the count: an empty shortest read means the number is unknown.
    const older = { read_count: 401, total_bases: 1513780, min_length: 0 };
    expect(zeroLengthReads(older)).toBeNull();
    expect(nanoplotCrossCheck(older, np)[0].status).toBe("differs");
    expect(zeroLengthReads({ min_length: 1 })).toBe(0);
  });
});

describe("nanoplotSideBySide", () => {
  it("pairs N50 and the thresholds both tools report, without judging them", () => {
    const rows = nanoplotSideBySide(arva, np);
    expect(rows).toEqual([
      { id: "n50", arva: 4817, nanoplot: 4817 },
      { id: "q10", threshold: 10, arva: 341, nanoplot: 341 },
      { id: "q15", threshold: 15, arva: 0, nanoplot: 0 },
    ]);
    expect(rows.every((r) => !("agrees" in r) && !("status" in r))).toBe(true);
    expect(nanoplotSideBySide({ n50: 3, quality: null }, { ...np, n50: 3 })).toEqual([{ id: "n50", arva: 3, nanoplot: 3 }]);
  });
});

describe("formatting and outputs", () => {
  it("shows NanoPlot's values without inventing precision", () => {
    expect(formatNanoplot(1513780, "count")).toBe("1,513,780");
    expect(formatNanoplot(3784.4, "bp")).toBe("3,784.4 bp");
    expect(formatNanoplot(4817, "bp")).toBe("4,817 bp");
    expect(formatNanoplot(10.2, "q")).toBe("Q10.2");
  });

  it("finds each output by NanoPlot's file name", () => {
    const out = nanoplotOutputs([
      "results/p/s/j/run_1_NanoPlot-report.html",
      "results/p/s/j/run_1_NanoStats.txt",
      "results/p/s/j/run_1_NanoStats_post_filtering.txt",
      "results/p/s/j/run_1_NanoPlot_20261028_0948.log",
      "results/p/s/j/nanoplot.stderr.log",
    ]);
    expect(out).toEqual({
      report: "run_1_NanoPlot-report.html",
      stats: "run_1_NanoStats.txt",
      postFiltering: "run_1_NanoStats_post_filtering.txt",
      log: "run_1_NanoPlot_20261028_0948.log",
    });
    expect(nanoplotOutputs(null).report).toBeUndefined();
  });

  it("runs without confirmation only for long-read technologies", () => {
    expect(["nanopore", "pacbio"].every((t) => isLongReadTechnology(t as "nanopore"))).toBe(true);
    expect(["illumina", "hybrid", "unknown"].some((t) => isLongReadTechnology(t as "illumina"))).toBe(false);
  });
});

describe("NanoPlot texts", () => {
  it("has every label and definition in English and Spanish, and a Guide entry", () => {
    const keys = Object.keys(dictionaries.en).filter((k) => k.startsWith("nanoplot."));
    expect(keys.length).toBeGreaterThan(40);
    for (const k of keys) expect(dictionaries.es[k as keyof typeof dictionaries.es].trim().length, k).toBeGreaterThan(0);
    for (const row of STAT_ROWS) expect(keys).toEqual(expect.arrayContaining([row.label, row.definition]));
    expect(GUIDE_BY_ID.nanoplot.references.some((r) => r.url === "https://doi.org/10.1093/bioinformatics/btad311")).toBe(true);
    expect(jobLabel("nanoplot", (k) => dictionaries.es[k])).toBe("Informe de NanoPlot");
  });

  it("states the different definitions instead of a match", () => {
    for (const lang of ["en", "es"] as const) {
      const d = dictionaries[lang];
      expect(d["nanoplot.def.n50"]).toMatch(/SeqKit/);
      expect(d["nanoplot.def.meanQual"]).toMatch(/ARVA/);
      expect(d["nanoplot.side.aboveWhy"]).toMatch(/≥ \{threshold\}.*> \{threshold\}/);
      // Shown next to the post-filtering column: the first column covers every read, before NanoPlot's filter.
      expect(d["nanoplot.colPre"]).toMatch(/NanoStats\.txt/);
      expect(d["nanoplot.colPre"]).not.toBe(d["nanoplot.colAll"]);
    }
  });
});
