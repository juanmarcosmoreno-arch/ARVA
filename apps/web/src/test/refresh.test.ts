import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { isSampleResultKey, refreshSampleResults } from "@/lib/refresh";

const invalidated = (qc: QueryClient, key: unknown[]) => qc.getQueryState(key)?.isInvalidated ?? false;

describe("refreshSampleResults", () => {
  it("marks every result query of the sample stale, including the tabs added after MLST and species", async () => {
    const qc = new QueryClient();
    const keys = [
      ["files", "s1"], ["assemblies", "s1"], ["annotations", "s1"], ["mlst", "s1"], ["species", "s1"],
      ["amr", "s1"], ["virulence", "s1"], ["mobile", "s1"], ["typing", "s1"], ["variants", "s1"],
      ["mobilome", "s1"], ["sanger", "s1"], ["crosscheck"],
    ];
    for (const k of keys) qc.setQueryData(k, { ok: true });
    await refreshSampleResults(qc, "s1");
    for (const k of keys) expect(invalidated(qc, k), JSON.stringify(k)).toBe(true);
  });

  it("leaves the job list and other samples alone", async () => {
    const qc = new QueryClient();
    for (const k of [["jobs", "s1"], ["amr", "s2"], ["dashboard"]]) qc.setQueryData(k, { ok: true });
    await refreshSampleResults(qc, "s1");
    expect(invalidated(qc, ["jobs", "s1"])).toBe(false);
    expect(invalidated(qc, ["amr", "s2"])).toBe(false);
    expect(invalidated(qc, ["dashboard"])).toBe(false);
  });

  it("recognises sample result keys by their second element", () => {
    expect(isSampleResultKey(["virulence", "s1"], "s1")).toBe(true);
    expect(isSampleResultKey(["virulence", "s1", "extra"], "s1")).toBe(true);
    expect(isSampleResultKey(["jobs", "s1"], "s1")).toBe(false);
    expect(isSampleResultKey(["mlstPlan", "a1", "auto"], "s1")).toBe(false);
    expect(isSampleResultKey(["crosscheck"], "s1")).toBe(false);
  });
});
