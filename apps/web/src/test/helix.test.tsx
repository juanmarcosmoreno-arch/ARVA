import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DoubleHelix } from "@/components/explorer/DoubleHelix";
import { api } from "@/lib/api";
import {
  BP_PER_TURN,
  baseKind,
  blocksFor,
  changesAt,
  codonsAt,
  complement,
  depthAt,
  distanceNm,
  grooveCentres,
  hydrogenBonds,
  inRange,
  parsePosition,
  PITCH_NM,
  rungShare,
  STRAND_OFFSET_DEG,
  strandAngles,
  TWIST_DEG,
  turnOf,
  wrapPosition,
} from "@/lib/helix";
import type { HelixFeature, HelixWindow } from "@/lib/types";
import { useSettings } from "@/store/settings";

describe("B-DNA geometry of the drawing", () => {
  it("uses 10.5 bp per turn and 0.34 nm per pair", () => {
    expect(TWIST_DEG).toBeCloseTo(34.2857, 3);
    expect(PITCH_NM).toBeCloseTo(3.57, 2);
    // the minor groove's share of 22 + 12 Å
    expect(STRAND_OFFSET_DEG).toBeCloseTo((360 * 12) / 34, 6);
    expect(strandAngles(1)).toEqual([0, STRAND_OFFSET_DEG]);
    expect(strandAngles(1 + BP_PER_TURN)[0]).toBeCloseTo(360, 9);
  });

  it("counts turns and pairs in a turn from base 1, and the distance from the start", () => {
    expect(turnOf(1)).toEqual({ turn: 1, pairInTurn: 1 });
    expect(turnOf(11)).toEqual({ turn: 1, pairInTurn: 11 }); // index 10 < 10.5
    expect(turnOf(12)).toEqual({ turn: 2, pairInTurn: 1 }); // index 11 >= 10.5
    expect(turnOf(22)).toEqual({ turn: 3, pairInTurn: 1 }); // index 21 = 2 x 10.5
    expect(turnOf(32)).toEqual({ turn: 3, pairInTurn: 11 });
    expect(turnOf(33)).toEqual({ turn: 4, pairInTurn: 1 }); // index 32 >= 31.5
    expect(distanceNm(1)).toBe(0);
    expect(distanceNm(101)).toBeCloseTo(34, 9);
  });

  it("places the grooves between the two backbones' front crossings", () => {
    const g = grooveCentres(1);
    // minor groove midway between strand 2 at -offset and strand 1 at 0; major groove in the other gap
    expect(g.minor).toBeCloseTo(1 - (STRAND_OFFSET_DEG / 2 / 360) * BP_PER_TURN, 9);
    expect(g.major - g.minor).toBeCloseTo(BP_PER_TURN / 2, 9);
    expect(Math.abs(grooveCentres(500).minor - 500)).toBeLessThanOrEqual(BP_PER_TURN / 2);
  });

  it("wraps positions on circular sequences only", () => {
    expect(wrapPosition(0, 100, true)).toBe(100);
    expect(wrapPosition(101, 100, true)).toBe(1);
    expect(wrapPosition(-1, 100, true)).toBe(99);
    expect(wrapPosition(0, 100, false)).toBeNull();
    expect(wrapPosition(101, 100, null)).toBeNull();
    expect(blocksFor([499, 500, 501, 1001])).toEqual([1, 501, 1001]);
    expect(inRange(5, 90, 10)).toBe(true); // across the origin
    expect(inRange(50, 90, 10)).toBe(false);
  });
});

describe("bases and pairs", () => {
  it("knows purines, pyrimidines, rings and hydrogen bonds", () => {
    expect(baseKind("a")).toEqual({ kind: "base", base: "A", purine: true, rings: 2 });
    expect(baseKind("T")).toEqual({ kind: "base", base: "T", purine: false, rings: 1 });
    expect(hydrogenBonds("G")).toBe(3);
    expect(hydrogenBonds("t")).toBe(2);
    expect(hydrogenBonds("N")).toBeNull();
    expect(rungShare("A", "T")).toBe(0.6);
    expect(rungShare("C", "G")).toBe(0.4);
    expect(rungShare("N", "N")).toBe(0.5);
  });

  it("shows N and IUPAC codes as such, complemented by the code of the complementary set", () => {
    expect(baseKind("N")).toEqual({ kind: "gap" });
    expect(baseKind("R")).toEqual({ kind: "ambiguous", code: "R", means: ["A", "G"] });
    expect(baseKind("-")).toEqual({ kind: "other", code: "-" });
    expect(["A", "C", "G", "T", "N", "R", "Y", "K", "M", "S", "W", "B", "V", "D", "H"].map(complement).join("")).toBe("TGCANYRMKSWVBHD");
  });

  it("parses typed positions within the sequence", () => {
    expect(parsePosition("12,345", 20_000)).toBe(12_345);
    expect(parsePosition("12.345", 20_000)).toBe(12_345);
    expect(parsePosition("0", 20_000)).toBeNull();
    expect(parsePosition("20001", 20_000)).toBeNull();
    expect(parsePosition("abc", 20_000)).toBeNull();
  });
});

// Feature, codon and change shapes follow ARVA's helix endpoint; positions are made up and are not biology.
const feature = (extra: Partial<HelixFeature>): HelixFeature => ({
  id: 1, locus_tag: "SYNT_00001", tool_id: null, type: "cds", start: 3, end: 11, strand: "+", length: 9, edge: false, gene: "abcA",
  product: "made-up protein", hypothetical: false, pseudo: false, partial: null,
  reading: { frame: "start", reason: null, length_multiple_of_3: true, codons: [
    { number: 1, positions: [3, 4, 5], codon: "ATG", amino_acid: "M" },
    { number: 2, positions: [6, 7, 8], codon: "AAN", amino_acid: "X" },
  ] },
  ...extra,
});

describe("context lookups", () => {
  it("finds the codon and its place, also for a minus-strand feature across the origin", () => {
    const [here] = codonsAt([feature({})], 4);
    expect(here.codon?.codon).toBe("ATG");
    expect(here.place).toBe(2);
    const minus = feature({ strand: "-", start: 28, end: 2, edge: true, reading: { frame: "start", reason: null, length_multiple_of_3: true, codons: [{ number: 1, positions: [2, 1, 30], codon: "ATG", amino_acid: "M" }] } });
    const [m] = codonsAt([minus], 30);
    expect(m.place).toBe(3);
    expect(codonsAt([minus], 15)).toEqual([]);
    expect(codonsAt([feature({ reading: { frame: null, reason: "pseudogene", codons: [], length_multiple_of_3: true } })], 4)[0].codon).toBeNull();
  });

  it("finds the depth bin and the changes at a position", () => {
    const coverage = { available: true, start: [1, 26], end: [25, 50], mean: [10, 20], min: [10, 20], max: [10, 20] };
    expect(depthAt(coverage, 30)).toEqual({ mean: 20, start: 26, end: 50 });
    expect(depthAt({ ...coverage, available: false }, 30)).toBeNull();
    const change = { start: 4, end: 6, kind: "replacement" as const, draft_bases: "AAA", polished_bases: "AG", reverse: false };
    expect(changesAt([change], 5)).toHaveLength(1);
    expect(changesAt([change], 7)).toHaveLength(0);
  });
});

function windowOf(sequence: string, extra: Partial<HelixWindow> = {}): HelixWindow {
  return {
    contig: "contig_1", contig_in_assembly: "contig_1", length: sequence.length, topology: null, start: 1, end: sequence.length, sequence,
    translation_table: 11, features: [feature({})],
    polishing: { available: true, reason: null, changes: [{ start: 4, end: 4, kind: "substitution", draft_bases: "C", polished_bases: "T", reverse: false }],
      source: { job_id: "j", polisher: "Racon", polisher_version: "1.5.0", record: "dnadiff", positions_in: "polished" } },
    coverage: { available: true, resolution: 25, start: [1], end: [30], mean: [12.5], min: [12.5], max: [12.5] },
    ...extra,
  };
}

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("Double helix view", () => {
  const contig = { id: "contig_1", name: "SYNTHETIC_chromosome", length: 30, circular: false, circularSource: null };
  const seq = "CCATGAANRGCTAAATTTGGGCCCAAATTG";
  beforeEach(() => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "annotationHelix").mockResolvedValue(windowOf(seq));
    vi.spyOn(api, "annotationAmr").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationVirulence").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationMobile").mockResolvedValue({ runs: {}, contigs: [], elements: [] });
  });

  it("shows the pair, the codon, the polishing change and the depth in Spanish, and moves with the keyboard", async () => {
    const onPosition = vi.fn();
    const { container } = renderWith(<DoubleHelix annotationId="a" contig={contig} position={4} onPosition={onPosition} onClose={() => {}} />);
    expect(await screen.findByText(/Codón ATG \(base 2 de 3\)/)).toBeInTheDocument();
    expect(screen.getByText("Metionina (Met)")).toBeInTheDocument();
    expect(screen.getByText(/Timina · pirimidina · 1 anillo/)).toBeInTheDocument();
    expect(screen.getByText(/Adenina · purina · 2 anillos/)).toBeInTheDocument();
    expect(screen.getByText(/Par T·A · 2 puentes de hidrógeno/)).toBeInTheDocument();
    expect(screen.getByText(/Sustitución · borrador C → pulido T/)).toBeInTheDocument();
    expect(screen.getByText(/Media 12,5× en 1–30/)).toBeInTheDocument();
    expect(screen.getAllByText("Doble hélice").length).toBeGreaterThan(0);
    expect(api.annotationHelix).toHaveBeenCalledWith("a", "contig_1", 1, 30);
    expect(container.querySelector('svg[role="img"]')).not.toBeNull();
    fireEvent.keyDown(screen.getByRole("region"), { key: "ArrowRight" });
    expect(onPosition).toHaveBeenLastCalledWith(5);
    fireEvent.keyDown(screen.getByRole("region"), { key: "ArrowLeft" });
    expect(onPosition).toHaveBeenLastCalledWith(3);
  });

  it("shows N and IUPAC codes as unknown, not paired", async () => {
    const { rerender } = renderWith(<DoubleHelix annotationId="a" contig={contig} position={8} onPosition={() => {}} onClose={() => {}} />);
    expect(await screen.findByText(/Base desconocida \(N\)/)).toBeInTheDocument();
    expect(screen.getByText(/Sin par/)).toBeInTheDocument();
    expect(screen.queryByText(/puentes de hidrógeno/)).toBeNull();
    expect(screen.getByText(/Desconocido \(una base del codón es N/)).toBeInTheDocument();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <DoubleHelix annotationId="a" contig={contig} position={9} onPosition={() => {}} onClose={() => {}} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Código de ambigüedad IUPAC R \(A \/ G\)/)).toBeInTheDocument();
  });

  it("stops scanning at the end of a linear sequence and jumps to a typed position", async () => {
    const onPosition = vi.fn();
    renderWith(<DoubleHelix annotationId="a" contig={contig} position={30} onPosition={onPosition} onClose={() => {}} />);
    await screen.findByText(/Posición 30 de 30/);
    fireEvent.keyDown(screen.getByRole("region"), { key: "ArrowRight" });
    expect(onPosition).toHaveBeenLastCalledWith(30);
    fireEvent.change(screen.getByLabelText("Ir a la posición"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Ir" }));
    expect(onPosition).toHaveBeenLastCalledWith(12);
  });
});

describe("Double helix scan", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
    vi.spyOn(api, "annotationHelix").mockResolvedValue(windowOf("ACGT".repeat(5)));
    vi.spyOn(api, "annotationAmr").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationVirulence").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationMobile").mockResolvedValue({ runs: {}, contigs: [], elements: [] });
  });

  it("steps at the chosen speed and wraps on a circular sequence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onPosition = vi.fn();
    const contig = { id: "contig_1", name: "c", length: 20, circular: true, circularSource: "Flye" };
    renderWith(<DoubleHelix annotationId="a" contig={contig} position={20} onPosition={onPosition} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Scan along the sequence" }));
    vi.advanceTimersByTime(500);
    expect(onPosition).toHaveBeenLastCalledWith(1);
    vi.useRealTimers();
  });
});
