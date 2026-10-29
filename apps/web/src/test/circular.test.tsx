import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnnotationChartsPanel } from "@/components/annotation/AnnotationCharts";
import { CircularExplorer } from "@/components/explorer/CircularMap";
import { binLabel, cogRows, densityRows, densityStrands, densitySummary, hypotheticalRows, lengthClasses, strandRows } from "@/lib/annotationCharts";
import { api } from "@/lib/api";
import {
  angleAt,
  arcPieces,
  barPaths,
  barScale,
  circleModel,
  labelAnchor,
  layoutCircle,
  locate,
  matchFeatures,
  mergeArcs,
  pieceAt,
  pointerPolar,
  polar,
  ringRadii,
  sectorPath,
  segmentTicks,
  stepFeature,
  TAU,
  windowAt,
  windowBars,
} from "@/lib/circular";
import type { Annotation, AnnotationCharts, DensityContig, GenomeMap, MapFeature } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" data-option={JSON.stringify(props.option)} />;
  }),
}));

// Shapes follow ARVA's map and charts endpoints; positions and counts are made up for the geometry, not biology.
const f = (id: number, contig: string, start: number, end: number, strand = "+", extra: Partial<MapFeature> = {}): MapFeature => ({
  id, contig, locus_tag: `SYNT_${String(id).padStart(5, "0")}`, tool_id: null, type: "cds", start, end, strand, length: Math.abs(end - start) + 1,
  edge: false, gene: null, product: "hypothetical protein", hypothetical: true, pseudo: false, partial: null, ...extra,
});
const close = (a: number, b: number) => expect(a).toBeCloseTo(b, 9);

describe("circle layout and angles", () => {
  it("gives one sequence the whole circle from 12 o'clock, clockwise", () => {
    const l = layoutCircle([{ id: "c", name: "chr", length: 1_000 }]);
    expect(l.gap).toBe(0);
    expect(l.segments[0].a0).toBe(0);
    close(l.segments[0].a1, TAU);
    close(angleAt(l, l.segments[0], 250), TAU / 4); // a quarter of the sequence: 3 o'clock
    const [x, y] = polar(100, 100, 50, TAU / 4);
    close(x, 150);
    close(y, 100);
    close(pointerPolar(100, 100, 150, 100).angle, TAU / 4);
    close(pointerPolar(100, 100, 100, 150).angle, TAU / 2); // straight down: 6 o'clock
    expect(locate(l, TAU / 4)?.index).toBe(0);
    close(locate(l, TAU / 4)!.pos, 250);
  });

  it("places several sequences in order, in proportion, with gaps between them", () => {
    const l = layoutCircle([{ id: "chr", name: "chr", length: 900 }, { id: "p", name: "p", length: 100 }], 0.1);
    const [chr, p] = l.segments;
    close(l.radPerBase, (TAU - 0.2) / 1_000);
    close(chr.a0, 0.05); // half a gap before the first sequence, so the top lies in a gap
    close(chr.a1 - chr.a0, 9 * (p.a1 - p.a0));
    close(p.a0 - chr.a1, 0.1);
    expect(locate(l, chr.a1 + 0.05)).toBeNull(); // in the gap
    expect(locate(l, p.a0 + 50 * l.radPerBase)?.index).toBe(1);
    // 500 contigs: gaps take at most 10 % of the circle
    const many = layoutCircle(Array.from({ length: 500 }, (_, i) => ({ id: `c${i}`, name: `c${i}`, length: 10 })));
    close(many.gap * 500, 0.1 * TAU);
  });

  it("draws sectors with the right arc flags and whole rings as two halves", () => {
    const small = sectorPath(0, 0, 10, 20, 0, 1);
    expect(small).toMatch(/^M0,-20A20,20 0 0 1 /);
    expect(small).toContain("A10,10 0 0 0 0,-10Z"); // inner edge back anticlockwise
    expect(sectorPath(0, 0, 10, 20, 0, 4)).toContain("A20,20 0 1 1"); // more than half a turn: large arc
    const ring = sectorPath(0, 0, 10, 20, 0, TAU);
    expect(ring.match(/M/g)).toHaveLength(2);
    expect(ring).toContain("M0,-20A20,20 0 0 1 0,20A20,20 0 0 1 0,-20Z");
    expect(ring).toContain("M0,-10A10,10 0 0 0 0,10A10,10 0 0 0 0,-10Z");
    expect(sectorPath(0, 0, 10, 20, 1, 1)).toBe("");
  });
});

describe("features on the circle", () => {
  const one = layoutCircle([{ id: "c", name: "chr", length: 1_000 }]);

  it("splits a feature across the origin into two arcs that meet at the top", () => {
    const pieces = arcPieces([f(1, "c", 951, 50, "+", { edge: true, length: 100 })], one);
    expect(pieces).toHaveLength(2);
    close(pieces[0].a0, (950 / 1_000) * TAU);
    close(pieces[0].a1, TAU);
    close(pieces[1].a0, 0);
    close(pieces[1].a1, (50 / 1_000) * TAU);
    expect(pieceAt(pieces, TAU - 0.001, 0)?.feature.id).toBe(1);
    expect(pieceAt(pieces, 0.001, 0)?.feature.id).toBe(1);
  });

  it("keeps the two arcs of an origin-crossing feature at both ends of its own sequence", () => {
    const l = layoutCircle([{ id: "a", name: "a", length: 500 }, { id: "b", name: "b", length: 500 }], 0.1);
    const [first, last] = arcPieces([f(1, "b", 451, 50, "-", { edge: true, length: 100 })], l);
    const b = l.segments[1];
    close(first.a1, b.a1);
    close(last.a0, b.a0);
    expect(arcPieces([f(2, "elsewhere", 1, 10)], l)).toEqual([]);
  });

  it("merges arcs closer than the gap and widens tiny ones, never across sequences", () => {
    const l = layoutCircle([{ id: "a", name: "a", length: 1_000 }, { id: "b", name: "b", length: 1_000 }], 0.01);
    const pieces = arcPieces([f(1, "a", 1, 100), f(2, "a", 102, 200), f(3, "a", 400, 400), f(4, "b", 1, 100)], l);
    const merged = mergeArcs(pieces, l, 2 * l.radPerBase, 10 * l.radPerBase);
    expect(merged).toHaveLength(3); // 1 and 2 merge (1 bp apart); 3 is widened alone; 4 is on b
    close(merged[0][0], l.segments[0].a0);
    close(merged[0][1], angleAt(l, l.segments[0], 200));
    close(merged[1][1] - merged[1][0], 10 * l.radPerBase);
    close(merged[2][0], l.segments[1].a0);
    // a tiny arc at the very start of a sequence is widened inside the sequence, not into the gap
    const [edge] = mergeArcs(arcPieces([f(5, "b", 1, 1)], l), l, 0, 10 * l.radPerBase);
    close(edge[0], l.segments[1].a0);
  });

  it("finds the feature under the pointer: on it, within the tolerance, shortest first", () => {
    const pieces = arcPieces([f(1, "c", 1, 500), f(2, "c", 101, 150), f(3, "c", 700, 710)], one);
    expect(pieceAt(pieces, angleAt(one, one.segments[0], 120), 0)?.feature.id).toBe(2);
    expect(pieceAt(pieces, angleAt(one, one.segments[0], 300), 0)?.feature.id).toBe(1);
    expect(pieceAt(pieces, angleAt(one, one.segments[0], 712), 0)).toBeNull();
    expect(pieceAt(pieces, angleAt(one, one.segments[0], 712), 3 * one.radPerBase)?.feature.id).toBe(3);
  });
});

describe("value rings, ticks and labels", () => {
  const one = layoutCircle([{ id: "c", name: "chr", length: 1_000 }]);

  it("turns windows into bars around a baseline and scales them to the largest", () => {
    const bars = windowBars(one, 0, [1, 501], [500, 1_000], [0.6, null], 0.5);
    expect(bars).toHaveLength(1);
    close(bars[0].value, 0.1);
    close(bars[0].a1, TAU / 2);
    expect(barScale(bars, 0.01)).toBeCloseTo(0.1);
    expect(barScale([], 0.05)).toBe(0.05);
    const { pos, neg } = barPaths(0, 0, [...bars, { a0: 4, a1: 5, value: -0.2 }], 50, 10, 0.1);
    expect(pos).toMatch(/A60,60/); // +0.1 of 0.1: full height outward
    expect(neg).toMatch(/A50,50 .*A40,40/); // -0.2 is clipped to one height inward
  });

  it("finds a window by position", () => {
    expect(windowAt([1, 101, 201], [100, 200, 250], 150)).toBe(1);
    expect(windowAt([1, 101, 201], [100, 200, 250], 250)).toBe(2);
    expect(windowAt([1, 101, 201], [100, 200, 250], 251)).toBe(-1);
  });

  it("stacks rings from the outside in and shrinks them together when they do not fit", () => {
    const r = ringRadii([{ id: "a", thickness: 10 }, { id: "b", thickness: 20 }], 100, 0, 5);
    expect(r).toEqual({ a: { r0: 90, r1: 100 }, b: { r0: 65, r1: 85 } });
    const tight = ringRadii([{ id: "a", thickness: 30 }, { id: "b", thickness: 30 }], 100, 70, 0);
    expect(tight).toEqual({ a: { r0: 85, r1: 100 }, b: { r0: 70, r1: 85 } });
  });

  it("puts ticks on 1-2-5 steps about the asked spacing apart", () => {
    const l = layoutCircle([{ id: "c", name: "chr", length: 5_000_000 }]);
    // radius 300: 1,885 px for 5 Mb, 2,653 bp per px; 80 px = 212 kb -> 500 kb steps
    const { step, positions } = segmentTicks(l, l.segments[0], 300);
    expect(step).toBe(500_000);
    expect(positions[0]).toBe(500_000);
    expect(positions[positions.length - 1]).toBe(4_500_000);
    expect(labelAnchor(0)).toBe("middle");
    expect(labelAnchor(TAU / 4)).toBe("start");
    expect(labelAnchor((3 * TAU) / 4)).toBe("end");
  });
});

describe("custom ring, navigation and the circle model", () => {
  const features = [f(1, "c", 1, 90, "+", { type: "trna", product: "tRNA-Leu", hypothetical: null }), f(2, "c", 200, 400, "-", { gene: "dnaA", product: "chromosomal replication initiator", hypothetical: false }), f(3, "c", 500, 600, ".", { type: "crispr", product: null, hypothetical: null }), f(4, "p", 10, 90, "+", { pseudo: true })];

  it("picks features by type, pseudogenes or text", () => {
    expect(matchFeatures(features, { kind: "type", type: "trna" }).map((x) => x.id)).toEqual([1]);
    expect(matchFeatures(features, { kind: "pseudo" }).map((x) => x.id)).toEqual([4]);
    expect(matchFeatures(features, { kind: "text", q: "DNAa" }).map((x) => x.id)).toEqual([2]);
    expect(matchFeatures(features, { kind: "text", q: "SYNT_00003" }).map((x) => x.id)).toEqual([3]);
    expect(matchFeatures(features, { kind: "text", q: "  " })).toEqual([]);
    expect(matchFeatures(features, null)).toEqual([]);
  });

  it("steps through features in sequence order and wraps round", () => {
    expect(stepFeature(features, ["p", "c"], null, 1)?.id).toBe(4);
    expect(stepFeature(features, ["p", "c"], 4, 1)?.id).toBe(1);
    expect(stepFeature(features, ["p", "c"], 3, 1)?.id).toBe(4);
    expect(stepFeature(features, ["p", "c"], 4, -1)?.id).toBe(3);
  });

  it("sorts arcs into rings by strand and measures GC from the drawn sequences' mean", () => {
    const m = circleModel(genomeMap(features), [features[0]]);
    expect(m.rings.forward.map((p) => p.feature.id)).toEqual([1, 4]);
    expect(m.rings.reverse.map((p) => p.feature.id)).toEqual([2]);
    expect(m.rings.backbone.map((p) => p.feature.id)).toEqual([3]);
    expect(m.custom).toHaveLength(1);
    expect(m.gc.map((b) => Math.round(b.value * 100) / 100)).toEqual([-0.1, 0.1, 0]);
    expect(m.scales.gc).toBeCloseTo(0.1);
    expect(m.coverage).toEqual([]);
  });
});

function genomeMap(features: MapFeature[]): GenomeMap {
  return {
    total_length: 1_100, points: 1440, sequence_source: { file: "fna", tool: "Prokka", sha256: "x" },
    gc: { window: 500, step: 500, auto: true, genome_gc: 0.5 },
    coverage: { available: false, reason: "no_alignment", source: null },
    sequences: [
      { contig: "c", contig_in_assembly: "SYNTHETIC_chromosome", length: 1_000, topology: null, gc: { contig_gc: 0.5, start: [1, 501], end: [500, 1_000], gc: [0.4, 0.6], skew: [0.2, -0.2] }, coverage: { available: false, reason: "no_alignment", start: [], end: [], mean: [] } },
      { contig: "p", contig_in_assembly: "SYNTHETIC_plasmid", length: 100, topology: null, gc: { contig_gc: 0.5, start: [1], end: [100], gc: [0.5], skew: [0] }, coverage: { available: false, reason: "no_alignment", start: [], end: [], mean: [] } },
    ],
    total: features.length,
    features,
  };
}

describe("annotation chart helpers", () => {
  const charts: AnnotationCharts = {
    cds_searched: true, genes: 5,
    lengths: { width: 100, bins: [{ min: 0, max: 100, cds_characterised: 0, cds_hypothetical: 1, sorf: 0, rna: 2 }, { min: 100, max: null, cds_characterised: 2, cds_hypothetical: 0, sorf: 0, rna: 0 }], classes: { cds_characterised: { n: 2, min: 150, median: 175, mean: 175, max: 200 }, cds_hypothetical: { n: 1, min: 90, median: 90, mean: 90, max: 90 }, sorf: { n: 0, min: null, median: null, mean: null, max: null }, rna: { n: 2, min: 70, median: 75, mean: 75, max: 80 } } },
    density: { window: 1_000, contigs: [] },
    strand: { by_type: { cds: { "+": 2, "-": 1, ".": 0 }, crispr: { "+": 0, "-": 0, ".": 1 } }, by_contig: [], total: { "+": 2, "-": 1, ".": 1 }, replication_strand: "not_determined" },
    cog: { cds_searched: true, cds: 3, reported: true, cds_with_category: 2, cds_with_cog_id: 2, categories: [{ letter: "J", name: "Translation, ribosomal structure and biogenesis", cds: 2 }, { letter: "K", name: "Transcription", cds: 1 }], names_source: "NCBI COG 2020 (fun-20.tab)" },
    hypothetical: { cds_searched: true, by_contig: [{ contig: "c", contig_in_assembly: "chr", characterised: 2, hypothetical: 0 }, { contig: "p", contig_in_assembly: "plasmid", characterised: 0, hypothetical: 1 }], total: { characterised: 2, hypothetical: 1 } },
    types: { types: ["cds"], total: { cds: 3 }, by_contig: [] },
  };

  it("labels length bins as whole-base ranges and keeps each class in its slot", () => {
    expect(binLabel({ min: 0, max: 100 })).toBe("0–99");
    expect(binLabel({ min: 1_400, max: null })).toBe("≥ 1,400");
    expect(lengthClasses(charts.lengths)).toEqual([{ cls: "cds_characterised", slot: 0 }, { cls: "cds_hypothetical", slot: 1 }, { cls: "rna", slot: 2 }]);
  });

  it("marks the shorter last window and leaves it out of the density summary", () => {
    const d: DensityContig = { contig: "c", contig_in_assembly: "chr", length: 2_500, start: [1, 1_001, 2_001], end: [1_000, 2_000, 2_500], forward: [3, 1, 0], reverse: [1, 1, 1], unstranded: [0, 0, 0], total: [4, 2, 1], genes: 7 };
    expect(densityRows(d, 1_000)[2]).toEqual(["2,001–2,500 (500 bp)", 0, 1, 0, 1]);
    expect(densityRows(d, 1_000)[0][0]).toBe("1–1,000");
    expect(densitySummary(d, 1_000)).toEqual({ min: 2, median: 3, max: 4, windows: 2 });
    expect(densityStrands(d).map((s) => s.key)).toEqual(["+", "-"]);
  });

  it("gives hypothetical shares per sequence with a total row, COG shares and strand shares", () => {
    const rows = hypotheticalRows(charts.hypothetical);
    expect(rows.map((r) => [r.name, r.share])).toEqual([["chr", 0], ["plasmid", 100], ["", (100 * 1) / 3]]);
    expect(hypotheticalRows({ cds_searched: false, by_contig: [], total: null })).toEqual([]);
    expect(cogRows(charts.cog).map((r) => r.share)).toEqual([100, 50]);
    expect(strandRows(charts.strand)).toEqual([{ type: "cds", counts: { "+": 2, "-": 1, ".": 0 }, share: 2 / 3 }, { type: "crispr", counts: { "+": 0, "-": 0, ".": 1 }, share: null }]);
  });
});

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Circular map", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });
  const hostile = '<img src=x onerror="alert(1)">';
  const annotation = {
    id: "ann", sample_id: "s", assembly_id: "a", job_id: "j", tool: "Prokka", tool_version: "1.14.6", database_key: null, database_name: null, database_version: null, database_checksum: null,
    parameters: {}, steps: {}, sequences: [], files: {}, created_at: "2026-10-28T00:00:00Z",
    summary: { synthetic_evidence: ["SYNTHETIC in the contig names"] },
  } as unknown as Annotation;
  const contigs = [{ id: "c", name: "SYNTHETIC_chromosome", length: 1_000, circular: true, circularSource: "Flye" }];

  it("draws the rings, explains the Phase 5 rings and missing coverage, escapes text, and opens a gene on click", async () => {
    const features = [f(1, "c", 1, 250, "+", { product: hostile, hypothetical: false })];
    const map = { ...genomeMap(features), total_length: 1_000, sequences: [genomeMap(features).sequences[0]] };
    vi.spyOn(api, "annotationMap").mockResolvedValue(map);
    const onSelect = vi.fn();
    const { container } = renderWith(<CircularExplorer annotation={annotation} contigs={contigs} sampleCode="SYN-1" selected={null} onSelect={onSelect} onShowLinear={() => {}} />);
    expect(await screen.findByRole("img", { name: /Circular map of SYNTHETIC_chromosome/ })).toBeInTheDocument();
    expect(api.annotationMap).toHaveBeenCalledWith("ann", { contigs: [], points: 1440 });
    expect(screen.getAllByText(/Available after Phase 5/)).toHaveLength(3);
    for (const name of ["Antimicrobial resistance", "Virulence factors", "Mobile genetic elements"]) expect(screen.getByLabelText(new RegExp(name))).toBeDisabled();
    expect(screen.getByLabelText(/Read coverage/)).toBeDisabled();
    expect(screen.getByText(/no reads were aligned to this assembly/)).toBeInTheDocument();
    expect(screen.getByText(/SYNTHETIC test data/)).toBeInTheDocument();
    expect(screen.getByText("Circular (reported by Flye)")).toBeInTheDocument();
    // default width 760: centre (380, 380), outer radius 322; the + ring lies between about 283 and 309 px
    const svg = container.querySelector("svg[role=img]")!;
    const a = TAU / 8; // the middle of bases 1-250 of 1,000
    fireEvent.mouseMove(svg, { clientX: 380 + 296 * Math.sin(a), clientY: 380 - 296 * Math.cos(a) });
    const tip = await screen.findByRole("tooltip");
    expect(tip.textContent).toContain(hostile);
    expect(container.querySelector("img")).toBeNull();
    fireEvent.click(svg, { clientX: 380 + 296 * Math.sin(a), clientY: 380 - 296 * Math.cos(a) });
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    fireEvent.click(screen.getByLabelText(/^GC skew$/));
    expect(screen.queryByText(/GC skew \(G − C\)/)).toBeNull();
  });
});

describe("Annotation charts", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });
  const annotation = { id: "ann", tool: "Prokka", summary: { synthetic_evidence: [] } } as unknown as Annotation;
  const base = (over: Partial<AnnotationCharts>): AnnotationCharts => ({
    cds_searched: true, genes: 3,
    lengths: { width: 100, bins: [{ min: 0, max: 100, cds_characterised: 1, cds_hypothetical: 2, sorf: 0, rna: 0 }], classes: { cds_characterised: { n: 1, min: 90, median: 90, mean: 90, max: 90 }, cds_hypothetical: { n: 2, min: 60, median: 70, mean: 70, max: 80 }, sorf: { n: 0, min: null, median: null, mean: null, max: null }, rna: { n: 0, min: null, median: null, mean: null, max: null } } },
    density: { window: 1_000, contigs: [{ contig: "c", contig_in_assembly: "chr", length: 1_500, start: [1, 1_001], end: [1_000, 1_500], forward: [1, 0], reverse: [1, 1], unstranded: [0, 0], total: [2, 1], genes: 3 }] },
    strand: { by_type: { cds: { "+": 1, "-": 2, ".": 0 } }, by_contig: [{ contig: "c", contig_in_assembly: "chr", "+": 1, "-": 2, ".": 0 }], total: { "+": 1, "-": 2, ".": 0 }, replication_strand: "not_determined" },
    cog: { cds_searched: true, cds: 3, reported: false, cds_with_category: 0, cds_with_cog_id: 3, categories: [], names_source: "NCBI COG 2020 (fun-20.tab)" },
    hypothetical: { cds_searched: true, by_contig: [{ contig: "c", contig_in_assembly: "chr", characterised: 1, hypothetical: 2 }], total: { characterised: 1, hypothetical: 2 } },
    types: { types: ["cds"], total: { cds: 3 }, by_contig: [{ contig: "c", contig_in_assembly: "chr", counts: { cds: 3 } }] },
    ...over,
  });

  it("says when COG categories were not reported instead of drawing zeros, and shows the density table", async () => {
    vi.spyOn(api, "annotationCharts").mockResolvedValue(base({}));
    renderWith(<AnnotationChartsPanel annotation={annotation} />);
    expect(await screen.findByText(/Prokka gave a COG identifier to 3 CDS but no category letters/)).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 CDS \(66\.7%\) have no function assigned/)).toBeInTheDocument();
    expect(screen.getByText(/Leading and lagging strand are not shown/)).toBeInTheDocument();
    const density = screen.getByText("Gene density along the sequence").closest(".flex.flex-col")!;
    fireEvent.click(density.querySelector('[aria-label="Show data table"]')!);
    expect(await screen.findByText("1,001–1,500 (500 bp)")).toBeInTheDocument();
  });

  it("says CDS were not searched when the step did not run", async () => {
    vi.spyOn(api, "annotationCharts").mockResolvedValue(base({ cds_searched: false, cog: { ...base({}).cog, cds_searched: false, cds: null }, hypothetical: { cds_searched: false, by_contig: [], total: null } }));
    renderWith(<AnnotationChartsPanel annotation={annotation} />);
    expect(await screen.findAllByText(/Prokka did not search for CDS in this run/)).toHaveLength(2);
  });
});
