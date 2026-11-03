import { describe, expect, it } from "vitest";
import { translator } from "@/i18n";
import { assemblyWarningText, graphMeasure } from "@/lib/messages";

describe("assembly warnings name the assembler's own coverage measure", () => {
  const es = translator("es");
  const en = translator("en");
  const spades = { code: "high_coverage_contigs", params: { count: 3, ratio: 2, median_coverage: 45, measure: "kmer", unit: "" }, message: "3 contig(s) with k-mer coverage above 2 × the length-weighted median of 45 (heuristic): ..." };

  it("translates SPAdes k-mer coverage without a read-depth ×", () => {
    const text = assemblyWarningText(es, spades);
    expect(text).toContain("cobertura de k-meros");
    expect(text).toContain("de 45:");
    expect(text).not.toContain("45×");
    expect(assemblyWarningText(en, { ...spades, params: { ...spades.params, measure: "relative", unit: "×" } })).toContain("relative depth (Unicycler");
  });

  it("keeps the server's text for a coverage warning stored without its measure", () => {
    const old = { ...spades, params: { count: 3, ratio: 2, median_coverage: 45 } };
    expect(assemblyWarningText(es, old)).toBe(old.message);
  });

  it("translates the assembly mode and the graph's coverage tag", () => {
    const many = { code: "many_contigs", params: { contigs: 300, total_length: 2800000, per_mb: 107, limit_per_mb: 100, mode: "long" }, message: "" };
    expect(assemblyWarningText(es, many)).toContain("ensamblajes de lecturas largas");
    expect(assemblyWarningText(en, many)).toContain("long-read assemblies");
    expect(graphMeasure(es, { coverage_measure: "depth", coverage_meaning: "mean read depth", coverage_tag: "dp" })).toBe("profundidad de lecturas");
  });
});

describe("chart axes follow the interface language", () => {
  it("formats value-axis numbers with the locale and leaves category labels alone", async () => {
    const { axisNumber } = await import("@/components/charts/theme");
    const { useSettings } = await import("@/store/settings");
    useSettings.setState({ language: "es" });
    expect(axisNumber(25000)).toBe("25.000");
    expect(axisNumber("core")).toBe("core");
    useSettings.setState({ language: "en" });
    expect(axisNumber(2500)).toBe("2,500");
  });
});
