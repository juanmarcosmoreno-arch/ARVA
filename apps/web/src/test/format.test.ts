import { describe, expect, it } from "vitest";
import { fmtBases, fmtBytes, fmtDuration, fmtInt } from "@/lib/format";

describe("formatters", () => {
  it("formats base counts", () => {
    expect(fmtBases(950)).toBe("950 bp");
    expect(fmtBases(34_336_568)).toBe("34.34 Mbp");
    expect(fmtBases(1_200_000_000)).toBe("1.20 Gbp");
  });

  it("formats bytes", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(37_559_453)).toBe("35.8 MB");
  });

  it("formats integers and durations", () => {
    expect(fmtInt(1234567)).toBe("1,234,567");
    expect(fmtDuration(1.468)).toBe("1.5 s");
    expect(fmtDuration(125)).toBe("2 min 5 s");
    expect(fmtDuration(null)).toBe("—");
  });
});
