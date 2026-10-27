import { describe, expect, it } from "vitest";
import { dictionaries, interpolate, type TranslationKey } from "@/i18n";
import { capacityCheck, totalBytes } from "@/lib/capacity";
import type { StorageCapacity } from "@/lib/types";

const capacity = (available: number): StorageCapacity => ({
  storage_root: "/data",
  free_bytes: available + 1000,
  total_bytes: 10_000_000,
  min_free_bytes: 1000,
  available_for_data_bytes: available,
});

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
