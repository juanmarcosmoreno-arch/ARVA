import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GenomeBrowser } from "@/components/explorer/GenomeBrowser";
import { ALL_NAV_ITEMS } from "@/components/layout/nav";
import { api } from "@/lib/api";
import {
  assignLanes,
  clampView,
  contigOptions,
  densityRuns,
  intergenic,
  MAX_GLYPHS,
  mergePixels,
  neighbour,
  nice125,
  panView,
  parseNumber,
  parseSearch,
  piecesOf,
  regionOf,
  ticks,
  toPos,
  toX,
  trackRequest,
  viewOf,
  viewOfFeature,
  zoomView,
} from "@/lib/explorer";
import type { FeatureLayoutItem, GenomeTracks } from "@/lib/types";
import { useSettings } from "@/store/settings";

// Feature shapes follow ARVA's layout endpoint; positions are made up for the geometry and are not biology.
const f = (id: number, start: number, end: number, strand = "+", extra: Partial<FeatureLayoutItem> = {}): FeatureLayoutItem => ({
  id, locus_tag: `SYNT_${String(id).padStart(5, "0")}`, tool_id: null, type: "cds", start, end, strand, length: Math.abs(end - start) + 1,
  edge: false, gene: null, product: "hypothetical protein", hypothetical: true, pseudo: false, partial: null, ...extra,
});

describe("viewport and coordinates", () => {
  it("maps bases to pixels and back (base n occupies [n-1, n))", () => {
    const v = { from: 100, to: 200 };
    expect(toX(100, v, 1000)).toBe(0);
    expect(toX(150, v, 1000)).toBe(500);
    expect(toPos(250, v, 1000)).toBe(125);
    expect(regionOf({ from: 99.5, to: 200.2 })).toEqual({ start: 100, end: 201 });
    expect(viewOf(101, 200)).toEqual({ from: 100, to: 200 });
  });

  it("clamps the view inside the sequence and to a minimum span", () => {
    expect(clampView({ from: -50, to: 50 }, 1000)).toEqual({ from: 0, to: 100 });
    expect(clampView({ from: 950, to: 1100 }, 1000)).toEqual({ from: 850, to: 1000 });
    expect(clampView({ from: 500, to: 505 }, 1000)).toEqual({ from: 487.5, to: 517.5 }); // 30 bp around 502.5
    expect(clampView({ from: 0, to: 5000 }, 1000)).toEqual({ from: 0, to: 1000 });
    expect(clampView({ from: 0, to: 5 }, 10)).toEqual({ from: 0, to: 10 }); // a sequence shorter than the minimum
  });

  it("zooms around an anchor and pans without leaving the sequence", () => {
    // Zoom in 2x at position 300 of the view 200-400: 300 stays at the same place (the middle)
    expect(zoomView({ from: 200, to: 400 }, 0.5, 300, 10_000)).toEqual({ from: 250, to: 350 });
    // Anchored at the left quarter: 250 stays a quarter of the way across
    expect(zoomView({ from: 200, to: 400 }, 0.5, 250, 10_000)).toEqual({ from: 225, to: 325 });
    expect(zoomView({ from: 0, to: 1000 }, 4, 500, 2000)).toEqual({ from: 0, to: 2000 });
    expect(panView({ from: 100, to: 200 }, 50, 1000)).toEqual({ from: 150, to: 250 });
    expect(panView({ from: 100, to: 200 }, -500, 1000)).toEqual({ from: 0, to: 100 });
    expect(panView({ from: 800, to: 900 }, 500, 1000)).toEqual({ from: 900, to: 1000 });
  });

  it("puts ruler ticks on 1-2-5 steps", () => {
    expect([nice125(0.4), nice125(3), nice125(7), nice125(1_500)]).toEqual([1, 5, 10, 2_000]);
    // 10 kb over 1,000 px with ticks at least 90 px apart: 900 bp -> 1,000 bp steps
    const r = ticks({ from: 0, to: 10_000 }, 1000);
    expect(r.step).toBe(1000);
    expect(r.positions).toEqual([1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000]);
  });

  it("requests tracks in tiles that panning reuses", () => {
    // A 1,000 bp view: tile 2,048 bp aligned to 1,024 bp, two points per pixel
    const a = trackRequest({ from: 5_000, to: 6_000 }, 100_000, 800);
    expect(a).toEqual({ start: 4097, end: 6144, bins: 1600 });
    expect(trackRequest({ from: 5_100, to: 6_100 }, 100_000, 800)).toEqual(a);
    expect(trackRequest({ from: 0, to: 60_000 }, 100_000, 800)).toEqual({ start: 1, end: 100_000, bins: 1600 });
    // Near the end the tile is shifted back so it stays inside the sequence
    expect(trackRequest({ from: 99_000, to: 100_000 }, 100_000, 800)).toEqual({ start: 97953, end: 100_000, bins: 1600 });
    expect(trackRequest({ from: 0, to: 100 }, 100_000, 5000).bins).toBe(5000);
  });
});

describe("features", () => {
  it("splits a feature across the origin into two pieces with the arrow on the 3' piece", () => {
    const ps = piecesOf([f(1, 9_900, 50, "+", { edge: true })], 10_000);
    expect(ps.map((p) => [p.start, p.end, p.head])).toEqual([[9_900, 10_000, false], [1, 50, true]]);
    const rev = piecesOf([f(2, 9_900, 50, "-", { edge: true })], 10_000);
    expect(rev.map((p) => p.head)).toEqual([true, false]);
  });

  it("packs overlapping features into lanes per strand", () => {
    const ps = piecesOf([f(1, 1, 100), f(2, 50, 150), f(3, 120, 200), f(4, 10, 20, "-"), f(5, 30, 40, ".")], 1000);
    const used = assignLanes(ps);
    expect(used).toEqual({ "+": 2, "-": 1, ".": 1 });
    expect(ps.map((p) => p.lane)).toEqual([0, 1, 0, 0, 0]);
  });

  it("finds intergenic bases between genes only (regulatory regions and CRISPR arrays do not count as genes)", () => {
    const fs = [f(1, 10, 20), f(2, 15, 30, "-"), f(3, 50, 60, "+", { type: "trna" }), f(4, 70, 80, ".", { type: "crispr" }), f(5, 95, 5, "+", { edge: true })];
    expect(intergenic(fs, 100)).toEqual([[6, 9], [31, 49], [61, 94]]);
  });

  it("draws a zoomed-out view as per-pixel runs of the dominant feature group", () => {
    const fs = [f(1, 1, 400), f(2, 401, 600, "+", { type: "rrna" }), f(3, 601, 1000, "+", { type: "crispr" })];
    const runs = densityRuns(piecesOf(fs, 1000), { from: 0, to: 1000 }, 100, 10);
    expect(runs["+"].map((r) => [r.x0, r.x1, r.group])).toEqual([[0, 40, "coding"], [40, 60, "rna"], [60, 100, "element"]]);
    expect(runs["-"]).toEqual([]);
  });

  it("merges intervals closer than a pixel", () => {
    expect(mergePixels([[1, 10], [11, 20], [500, 600]], { from: 0, to: 1000 }, 100)).toEqual([[0, 2], [49.9, 60]]);
  });

  it("steps to the next and previous feature and frames a feature", () => {
    const fs = [f(3, 500, 600), f(1, 10, 20), f(2, 100, 200)];
    const v = { from: 0, to: 1000 };
    expect(neighbour(fs, 1, 1, v)?.id).toBe(2);
    expect(neighbour(fs, 2, -1, v)?.id).toBe(1);
    expect(neighbour(fs, 3, 1, v)?.id).toBe(3);
    expect(neighbour(fs, null, 1, { from: 300, to: 400 })?.id).toBe(3);
    // bases 1001-2000 with a 1.5x margin on each side (1,500 bp), moved inside the sequence
    expect(viewOfFeature(f(9, 1001, 2000), 100_000)).toEqual({ from: 0, to: 4000 });
    expect(viewOfFeature(f(9, 9_900, 50, "+", { edge: true }), 10_000)).toEqual({ from: 0, to: 10_000 });
  });
});

describe("contigs and search", () => {
  const contigs = contigOptions(
    [{ id: "contig_1", original_id: "SYNTHETIC_chromosome", length: 300_000, topology: "circular" }, { id: "contig_2", original_id: "SYNTHETIC_plasmid", length: 15_000 }],
    "Bakta",
    [{ name: "SYNTHETIC_plasmid", circular: true } as never],
    "Flye",
  );

  it("takes Bakta's topology first, then the assembler's flag", () => {
    expect(contigs.map((c) => [c.name, c.circular, c.circularSource])).toEqual([["SYNTHETIC_chromosome", true, "Bakta"], ["SYNTHETIC_plasmid", true, "Flye"]]);
    expect(contigOptions([{ id: "c", original_id: "c", length: 9 }], "Prokka", [], "SPAdes")[0].circular).toBeNull();
  });

  it("parses numbers with thousands separators in either language", () => {
    expect([parseNumber("12,345"), parseNumber("12.345"), parseNumber("1 000 000"), parseNumber("42")]).toEqual([12_345, 12_345, 1_000_000, 42]);
    expect([parseNumber("1,23"), parseNumber("12k"), parseNumber("-5")]).toEqual([null, null, null]);
  });

  it("reads coordinates, sequence names and text", () => {
    expect(parseSearch("SYNTHETIC_chromosome:1,000-2,500", contigs, "contig_2")).toEqual({ kind: "region", contig: "contig_1", start: 1000, end: 2500 });
    expect(parseSearch("contig_2:700", contigs, "contig_1")).toEqual({ kind: "region", contig: "contig_2", start: 700, end: 700 });
    expect(parseSearch("synthetic_plasmid:1..20", contigs, "contig_1")).toEqual({ kind: "region", contig: "contig_2", start: 1, end: 20 });
    expect(parseSearch("5000 - 6000", contigs, "contig_2")).toEqual({ kind: "region", contig: "contig_2", start: 5000, end: 6000 });
    expect(parseSearch("SYNTHETIC_plasmid", contigs, "contig_1")).toEqual({ kind: "contig", contig: "contig_2" });
    expect(parseSearch("contig_2:14000-16000", contigs, "contig_1")).toEqual({ kind: "error", code: "out_of_range" });
    expect(parseSearch("contig_2:900-100", contigs, "contig_1")).toEqual({ kind: "error", code: "order" });
    // Identifiers with a colon are text when the part before it is not a sequence name
    expect(parseSearch("GO:0005840", contigs, "contig_1")).toEqual({ kind: "text", q: "GO:0005840" });
    expect(parseSearch("  dnaA ", contigs, "contig_1")).toEqual({ kind: "text", q: "dnaA" });
    expect(parseSearch("DNA-3-methyladenine glycosylase", contigs, "contig_1")).toEqual({ kind: "text", q: "DNA-3-methyladenine glycosylase" });
    expect(parseSearch("   ", contigs, "contig_1")).toBeNull();
  });
});

function tracks(contig: string, length: number): GenomeTracks {
  return {
    contig, contig_in_assembly: contig, length, start: 1, end: length, points: 2, sequence_source: { file: "fna", tool: "Prokka", sha256: "x" },
    gc: { window: length / 2, step: length / 2, auto: true, windows: 2, group: 1, contig_gc: 0.5, start: [1, length / 2 + 1], end: [length / 2, length], gc: [0.4, 0.6], gc_min: [0.4, 0.6], gc_max: [0.4, 0.6], skew: [0.1, -0.1], skew_min: [0.1, -0.1], skew_max: [0.1, -0.1] },
    coverage: { available: false, reason: "no_alignment", start: [], end: [], mean: [], min: [], max: [] },
  };
}

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Genome browser", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });
  const contig = { id: "contig_1", name: "SYNTHETIC_chromosome", length: 20_000, circular: true, circularSource: "Flye" };
  const hostile = '<img src=x onerror="alert(1)">';

  it("draws genes as text-safe glyphs, says why coverage is missing and selects on click", async () => {
    vi.spyOn(api, "annotationTracks").mockResolvedValue(tracks("contig_1", 20_000));
    const onSelect = vi.fn();
    const layout = { contig: "contig_1", contig_in_assembly: "SYNTHETIC_chromosome", length: 20_000, total: 2, items: [f(1, 100, 900, "+", { product: hostile, hypothetical: false }), f(2, 1_000, 1_500, "-")] };
    const { container } = renderWith(
      <GenomeBrowser annotationId="a" contig={contig} layout={layout} layoutError={null} view={{ from: 0, to: 20_000 }} onView={() => {}} selected={null} onSelect={onSelect}
        marked={new Set()} onToggleMark={() => {}} region={null} onRegion={() => {}} gc={{ window: null, step: null }} />,
    );
    expect(await screen.findByText(/no reads were aligned to this assembly/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles.some((t) => t?.includes(hostile))).toBe(true);
    const glyph = container.querySelector('[data-feature="1"]')!;
    fireEvent.pointerDown(glyph, { button: 0, clientX: 10, clientY: 40 });
    fireEvent.pointerUp(glyph, { clientX: 10, clientY: 40 });
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    expect(api.annotationTracks).toHaveBeenCalledWith("a", { contig: "contig_1", start: 1, end: 20_000, bins: 1808, window: null, step: null });
  });

  it("switches to density runs above the glyph limit and back to glyphs when zoomed in", async () => {
    vi.spyOn(api, "annotationTracks").mockResolvedValue(tracks("contig_1", 20_000));
    const items = Array.from({ length: MAX_GLYPHS + 50 }, (_, i) => f(i + 1, i * 30 + 1, i * 30 + 20, i % 2 ? "+" : "-"));
    const layout = { contig: "contig_1", contig_in_assembly: "SYNTHETIC_chromosome", length: 20_000, total: items.length, items };
    const props = { annotationId: "a", contig, layout, layoutError: null, onView: () => {}, selected: null, onSelect: () => {}, marked: new Set<number>(), onToggleMark: () => {}, region: null, onRegion: () => {}, gc: { window: null, step: null } };
    const { container, rerender } = renderWith(<GenomeBrowser {...props} view={{ from: 0, to: 20_000 }} />);
    expect(screen.getByText(/650 features in this view, more than the 600 drawn one by one/)).toBeInTheDocument();
    expect(container.querySelectorAll("[data-feature]")).toHaveLength(0);
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <GenomeBrowser {...props} view={{ from: 0, to: 3_000 }} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(container.querySelectorAll("[data-feature]").length).toBe(100));
  });

  it("moves and zooms from the keyboard", () => {
    vi.spyOn(api, "annotationTracks").mockResolvedValue(tracks("contig_1", 20_000));
    const onView = vi.fn();
    renderWith(
      <GenomeBrowser annotationId="a" contig={contig} layout={undefined} layoutError={null} view={{ from: 1_000, to: 2_000 }} onView={onView} selected={null} onSelect={() => {}}
        marked={new Set()} onToggleMark={() => {}} region={null} onRegion={() => {}} gc={{ window: null, step: null }} />,
    );
    const group = screen.getByRole("group", { name: "Genome browser of SYNTHETIC_chromosome" });
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(onView).toHaveBeenLastCalledWith({ from: 1_100, to: 2_100 });
    fireEvent.keyDown(group, { key: "+" });
    expect(onView).toHaveBeenLastCalledWith({ from: 1_250, to: 1_750 });
    fireEvent.keyDown(group, { key: "0" });
    expect(onView).toHaveBeenLastCalledWith({ from: 0, to: 20_000 });
  });
});

it("lists the Genome Explorer in the sidebar as available, other planned modules unchanged", () => {
  const explorer = ALL_NAV_ITEMS.find((i) => i.key === "explorer")!;
  expect(explorer.to).toBe("/explorer");
  expect(explorer.plannedPhase).toBeUndefined();
  expect(ALL_NAV_ITEMS.find((i) => i.key === "comparative")?.plannedPhase).toBe(6);
});
