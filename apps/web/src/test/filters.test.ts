import { describe, expect, it } from "vitest";
import {
  FASTP_DEFAULTS,
  FILTLONG_EMPTY,
  describeFastp,
  describeFiltlong,
  filtlongHasThreshold,
  identityToPhred,
  lineageOrder,
  phredToIdentity,
} from "@/lib/filters";
import type { RawFile } from "@/lib/types";

describe("Filtlong identity ↔ Phred", () => {
  it("matches the documented equivalences", () => {
    expect(identityToPhred(90)).toBeCloseTo(10, 6);
    expect(identityToPhred(95)).toBeCloseTo(13.0103, 3);
    expect(identityToPhred(99)).toBeCloseTo(20, 6);
    expect(phredToIdentity(10)).toBeCloseTo(90, 6);
    expect(identityToPhred(100)).toBe(Infinity);
  });

  it("requires at least one threshold", () => {
    expect(filtlongHasThreshold(FILTLONG_EMPTY)).toBe(false);
    expect(filtlongHasThreshold({ ...FILTLONG_EMPTY, keep_percent: 90 })).toBe(true);
  });

  it("describes thresholds with Phred equivalents", () => {
    const d = describeFiltlong({ ...FILTLONG_EMPTY, min_length: 1000, min_mean_q: 90 });
    expect(d).toEqual(["Remove reads shorter than 1,000 bp", "Remove reads with mean identity < 90% (≈ Q10.0)"]);
  });
});

describe("fastp description", () => {
  it("lists the default filters explicitly", () => {
    const d = describeFastp(FASTP_DEFAULTS, true).join("\n");
    expect(d).toContain("below Q15");
    expect(d).toContain("> 40%");
    expect(d).toContain("> 5 N bases");
    expect(d).toContain("shorter than 15 bp");
    expect(d).toContain("partner is removed too");
  });

  it("reports when nothing is filtered", () => {
    const off = { ...FASTP_DEFAULTS, adapter_trimming: false, quality_filtering: false, length_filtering: false, poly_g: "disable" as const };
    expect(describeFastp(off, false)).toEqual(["No filtering: reads are copied unchanged"]);
  });
});

describe("lineage ordering", () => {
  const f = (id: string, parent: string | null): RawFile =>
    ({ id, parent_file_id: parent, origin: parent ? "derived" : "imported" }) as RawFile;

  it("places derived files under their parents", () => {
    const order = lineageOrder([f("a", null), f("b", null), f("a1", "a"), f("a1x", "a1")]);
    expect(order.map((o) => [o.file.id, o.depth])).toEqual([["a", 0], ["a1", 1], ["a1x", 2], ["b", 0]]);
  });

  it("shows orphaned derived files at the top level", () => {
    expect(lineageOrder([f("x", "deleted")]).map((o) => o.depth)).toEqual([0]);
  });
});
