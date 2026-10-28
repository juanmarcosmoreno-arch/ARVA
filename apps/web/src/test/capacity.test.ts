import { describe, expect, it } from "vitest";
import { dictionaries, interpolate, type TranslationKey } from "@/i18n";
import { capacityCheck, totalBytes, uploadBytesNeeded, uploadSpace } from "@/lib/capacity";
import type { StorageCapacity } from "@/lib/types";

const capacity = (available: number, factor: 1 | 2 = 1): StorageCapacity => ({
  storage_root: "/data",
  free_bytes: available + 1000,
  total_bytes: 10_000_000,
  min_free_bytes: 1000,
  available_for_data_bytes: available,
  upload_overhead_factor: factor,
});
const en = (key: TranslationKey, vars?: Record<string, string | number>) => interpolate(dictionaries.en[key], vars);

describe("capacityCheck", () => {
  it("compares the selection with the space usable for data (free minus reserve)", () => {
    expect(capacityCheck(500, capacity(500))).toBe("ok");
    expect(capacityCheck(501, capacity(500))).toBe("insufficient");
    expect(capacityCheck(1, capacity(0))).toBe("insufficient");
    expect(capacityCheck(0, capacity(0))).toBe("ok");
  });

  it("is unknown without capacity figures (the server still enforces the limit)", () => {
    expect(capacityCheck(10, undefined)).toBe("unknown");
    expect(capacityCheck(10, null)).toBe("unknown");
  });

  it("sums file sizes", () => {
    expect(totalBytes([{ size: 3 }, { size: 4 }])).toBe(7);
    expect(totalBytes([])).toBe(0);
  });
});

describe("uploadBytesNeeded", () => {
  it("is the selection itself when uploads are not buffered on the data disk", () => {
    expect(uploadBytesNeeded([300, 200], capacity(0, 1))).toBe(500);
    expect(uploadBytesNeeded([300], undefined)).toBe(300);
  });

  it("adds the largest request once when request bodies are spooled on the data disk", () => {
    // One request: stored twice while received. Several requests: earlier spools are gone again.
    expect(uploadBytesNeeded([300], capacity(0, 2))).toBe(600);
    expect(uploadBytesNeeded([300, 200, 100], capacity(0, 2))).toBe(900);
    expect(uploadBytesNeeded([], capacity(0, 2))).toBe(0);
  });
});

describe("uploadSpace", () => {
  it("labels the figure as usable space, like the storage card", () => {
    expect(uploadSpace(en, 2048, [2048], capacity(4096)).line).toBe("Selected 2.00 KB · Usable for new data 4.00 KB");
    expect(uploadSpace(en, 2048, [2048], null).line).toBe("Selected 2.00 KB · Usable for new data —");
    expect(uploadSpace(en, 2048, [2048], capacity(4096)).refusal).toBeNull();
  });

  it("explains the buffered need and refuses what only fits once", () => {
    const space = uploadSpace(en, 3072, [3072], capacity(4096, 2));
    expect(space.line).toBe("Selected 3.00 KB, needs 6.00 KB while uploading (buffered on the same disk) · Usable for new data 4.00 KB");
    expect(space.refusal).toContain("uploading 3.00 KB through the browser needs 6.00 KB");
    expect(space.refusal).toContain("only 4.00 KB can be used");
    expect(uploadSpace(en, 3072, [3072], capacity(4096, 1)).refusal).toBeNull();
  });

  it("refuses an unbuffered selection larger than the usable space", () => {
    expect(uploadSpace(en, 5000, [5000], capacity(4096)).refusal).toContain("the selection needs 4.88 KB but only 4.00 KB can be used");
  });
});

describe("i18n interpolation", () => {
  it("fills placeholders and leaves unknown ones visible", () => {
    expect(interpolate("Selected {selected} · Free {free}", { selected: "2 GB", free: 3 })).toBe("Selected 2 GB · Free 3");
    expect(interpolate("{a} and {b}", { a: 1 })).toBe("1 and {b}");
    expect(interpolate("no placeholders")).toBe("no placeholders");
  });

  it("uses the same placeholders in English and Spanish", () => {
    const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(dictionaries.en) as TranslationKey[]) {
      expect(placeholders(dictionaries.es[key]), key).toEqual(placeholders(dictionaries.en[key]));
    }
  });
});
