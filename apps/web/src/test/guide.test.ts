import { describe, expect, it } from "vitest";
import { GUIDE, GUIDE_BY_ID } from "@/guide/metrics";

describe("ARVA Guide content", () => {
  it("has unique ids", () => {
    expect(new Set(GUIDE.map((g) => g.id)).size).toBe(GUIDE.length);
  });

  it.each(GUIDE.map((g) => [g.id, g] as const))("%s is complete in English and Spanish with references", (_id, entry) => {
    for (const lang of ["en", "es"] as const) {
      const c = entry[lang];
      expect(c.title.trim().length).toBeGreaterThan(0);
      for (const field of ["what", "why", "how", "interpret", "next", "limitations"] as const) {
        expect(c[field].trim().length, `${lang}.${field}`).toBeGreaterThan(10);
      }
      expect(c.mistakes.length).toBeGreaterThan(0);
    }
    expect(entry.references.length).toBeGreaterThan(0);
    for (const r of entry.references) expect(r.url).toMatch(/^https:\/\//);
  });

  it("covers every metric referenced by the QC screen", () => {
    for (const id of ["read_count", "length_distribution", "n50", "gc_content", "read_quality", "q20_q30", "phred", "coverage"] as const) {
      expect(GUIDE_BY_ID[id]).toBeDefined();
    }
  });
});
