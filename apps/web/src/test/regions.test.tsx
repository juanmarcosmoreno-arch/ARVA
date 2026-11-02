import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GeneView } from "@/components/comparative/GeneView";
import { RegionView } from "@/components/comparative/RegionView";
import { GUIDE_BY_ID } from "@/guide/metrics";
import type { ComparisonResultRead } from "@/lib/comparative";
import { figurePdf } from "@/lib/pdf";
import {
  type GeneData,
  type RegionData,
  type RegionTrack,
  leaves,
  matchRows,
  regionFigure,
  sharedGroups,
  textWidth,
  trackSpan,
  treeFigure,
  wrap,
} from "@/lib/regions";
import { useSettings } from "@/store/settings";

const THEME = { text: "#000000", muted: "#666666", axis: "#444444", link: "#888888", outline: "#000000", neutral: "#cccccc" };

const cds = (id: number, rel_start: number, rel_end: number, rel_strand: string, group: number, gene: string | null, marks = false) => ({
  id, locus_tag: `L_${id}`, gene, product: gene ? `${gene} protein` : "hypothetical protein", type: "cds", start: 1000 + rel_start,
  end: 1000 + rel_end, strand: rel_strand, length: rel_end - rel_start + 1, pseudo: false, rel_start, rel_end, rel_strand, clipped: false,
  group, marks: marks ? [{ kind: "virulence" as const, label: "seh", detail: "VFDB", source: "ABRicate vfdb", start: 1000, end: 1726, strand: "+" }] : [],
});

function track(label: string, flipped: boolean, extra: Partial<RegionTrack> = {}): RegionTrack {
  return { label, assembly_id: `a-${label}`, sample_id: "s", annotation_id: `ann-${label}`, annotated: true, located_by: "blastp",
    hit: { identity: 100, query_coverage: 100, evalue: 0, bitscore: 480 }, copies: 1, elements: [], contig: "contig_1", contig_length: 50_000,
    start: 1000, end: 13_000, clipped_left: false, clipped_right: false, anchor_start: 6000, anchor_end: 6725, anchor_strand: flipped ? "-" : "+",
    flipped, anchor_feature_id: 1,
    features: [cds(1, 0, 725, "+", 0, "seh", true), cds(2, 900, 1800, "-", 1, null), cds(3, -2000, -100, "+", 2, "sek")], ...extra };
}

const REGION: RegionData = {
  anchor: { kind: "feature", contig: "contig_1", start: 6000, end: 6725, strand: "+", gene: "seh", locus_tag: "L_1", product: "enterotoxin H",
    feature_id: 1, annotation_id: "ann-MW2" },
  flank: 5000,
  tracks: [track("MW2", false, { located_by: "anchor", hit: null }), track("MSSA476", true),
    { ...track("N315", false), located_by: "not_found", hit: null, features: [], contig: undefined, start: undefined, end: undefined }],
  groups: [{ id: 0, name: "seh", size: 2, tracks: 2, anchor: true }, { id: 1, name: null, size: 2, tracks: 2, anchor: false },
    { id: 2, name: "sek", size: 1, tracks: 1, anchor: false }],
  links: [{ upper: 0, lower: 1, links: [{ upper_start: 0, upper_end: 725, lower_start: 0, lower_end: 725, identity: 100, length: 726, inverted: false }] }],
  settings: { groups: { min_identity: 30, min_coverage: 50 }, links: { min_identity: 70, min_length: 100 }, locate: { min_identity: 40, min_coverage: 50, evalue: 1e-10 } },
};

const OPTS = { order: [0, 1, 2], flips: {}, labels: "gene" as const, theme: THEME, legendTitle: "Groups", linksLegend: "links",
  marksLegend: { amr: "AMR", virulence: "Virulence", mobile: "Mobile" }, notFound: "Not found", hitLabel: (v: number) => `${v} %`, unnamedGroup: (id: number) => `group ${id}`, caption: "Caption text", kb: (v: number) => `${v} kb` };

const base = { job_id: "job-1", created_at: "2026-11-02T09:00:00Z", set_id: "set-1", parameters: {}, files: {}, warnings: [], summary: {} };

const GENE: GeneData = {
  query: { id: "q", name: "seh", molecule: "protein", length: 241, sha256: "a".repeat(64), source: { kind: "upload" } },
  program: "tblastn", task: "tblastn",
  genomes: [
    { label: "MW2", assembly_id: "a1", sample_id: "s1", annotation_id: "ann1", hsps: 10, hsps_above_identity: 1, matches: [{
      copy: 1, kind: "complete", contig: "NC_003923.1", subject: "contig_1", start: 61524, end: 62246, strand: "+", identity: 100,
      query_coverage: 100, query_start: 1, query_end: 241, query_length: 241, evalue: 1e-150, bitscore: 451, at_contig_edge: false,
      pieces: [{ qstart: 1, qend: 241, s_lo: 61524, s_hi: 62246, pident: 100 }],
      feature: { feature_id: 55, locus_tag: "MW2_00055", gene: "seh", product: "enterotoxin H", annotation_id: "ann1" },
      mobile: [{ element: "IS1182", category: "insertion_sequence", method: "isescan", tool: "ISEScan", distance: 812, start: 63000, end: 64500 }],
      on_plasmid_contig: false }] },
    { label: "N315", assembly_id: "a2", sample_id: "s2", annotation_id: null, hsps: 13, hsps_above_identity: 0, matches: [] },
  ],
  alignment: { status: "too_few", sequences: [{ id: "s1", label: "MW2 copy 1", genome: "MW2", copy: 1, length: 723 }] },
  tree: { method: "iqtree", status: "too_few", sequences: 1, unique_sequences: 1 },
  settings: { min_identity: 70, min_coverage: 50, complete_coverage: 90, evalue: 1e-5, max_gap: 5000, mobile_distance: 10000 },
};

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => useSettings.setState({ language: "en" }));

describe("region figure geometry", () => {
  it("aligns every track on the gene of interest and orients it to the right", () => {
    expect(trackSpan(REGION.tracks[0])).toEqual([-5000, 7000]);
    expect(trackSpan(REGION.tracks[1])).toEqual([-6275, 5725]);
    const fig = regionFigure(REGION, OPTS);
    const anchors = fig.prims.filter((p) => p.kind === "poly" && p.ref?.feature === 1 && p.points.length === 5);
    expect(anchors).toHaveLength(2);
    const xs = anchors.map((p) => (p.kind === "poly" ? Math.min(...p.points.map((q) => q[0])) : 0));
    expect(xs[0]).toBeCloseTo(xs[1]);
    expect(anchors.every((p) => p.kind === "poly" && p.width === 2)).toBe(true);
    expect(fig.prims.some((p) => p.kind === "text" && p.text === "Not found: N315")).toBe(true);
    expect(fig.prims.some((p) => p.kind === "text" && p.text === "Caption text")).toBe(true);
  });

  it("colours only groups shared by several genomes and draws the identity bands", () => {
    expect(sharedGroups(REGION)).toEqual([0, 1]);
    const fig = regionFigure(REGION, OPTS);
    const fills = new Set(fig.prims.filter((p) => p.kind === "poly" && p.ref?.feature === 3).map((p) => (p.kind === "poly" ? p.fill : "")));
    expect([...fills]).toEqual([THEME.neutral]);
    const bands = fig.prims.filter((p) => p.kind === "poly" && p.fill === THEME.link && p.points.length === 4 && p.opacity !== 0.35);
    expect(bands).toHaveLength(1);
  });

  it("mirrors a track the user flips, strands included", () => {
    const plain = regionFigure(REGION, OPTS);
    const flipped = regionFigure(REGION, { ...OPTS, flips: { 1: true } });
    const arrowOf = (fig: typeof plain) => fig.prims.find((p) => p.kind === "poly" && p.ref?.track === 1 && p.ref.feature === 2);
    const a = arrowOf(plain), b = arrowOf(flipped);
    if (a?.kind !== "poly" || b?.kind !== "poly") throw new Error("missing arrow");
    expect(a.points[2][0]).toBe(Math.min(...a.points.map((q) => q[0])));
    expect(b.points[2][0]).toBe(Math.max(...b.points.map((q) => q[0])));
  });

  it("measures and wraps text with Helvetica's widths", () => {
    expect(textWidth("seh", 10)).toBeCloseTo(((500 + 556 + 556) * 10) / 1000);
    expect(wrap("one two three four", 10, textWidth("three four", 10) + 1)).toEqual(["one two", "three four"]);
  });
});

describe("gene tree and PDF", () => {
  const tree = { name: null, length: null, support: null, children: [
    { name: "MW2 copy 1", length: 0.01, support: null, children: [] },
    { name: null, length: 0.2, support: 98, children: [{ name: "N315 copy 1", length: 0.1, support: null, children: [] },
      { name: "USA300 copy 1", length: 0.05, support: null, children: [] }] },
    { name: "MSSA476 copy 1", length: 0.0, support: null, children: [] }] };

  it("draws every leaf with its support values and a scale bar", () => {
    expect(leaves(tree)).toEqual(["MW2 copy 1", "N315 copy 1", "USA300 copy 1", "MSSA476 copy 1"]);
    const fig = treeFigure(tree, { theme: THEME, caption: "Unrooted", scaleUnit: "subst/site", supportMax: 100 });
    const texts = fig.prims.filter((p) => p.kind === "text").map((p) => (p.kind === "text" ? p.text : ""));
    expect(texts).toEqual(expect.arrayContaining(["MW2 copy 1", "98", "0.05 subst/site", "Unrooted"]));
  });

  it("writes a one-page vector PDF with a valid cross-reference table", () => {
    const fig = regionFigure(REGION, OPTS);
    const bytes = figurePdf(fig, "#FFFFFF", textWidth);
    const text = new TextDecoder("latin1").decode(bytes);
    expect(text.startsWith("%PDF-1.4")).toBe(true);
    expect(text).toContain("/BaseFont /Helvetica-Oblique");
    expect(text).toContain("(seh) Tj");
    const xref = Number(/startxref\n(\d+)/.exec(text)![1]);
    expect(text.slice(xref, xref + 4)).toBe("xref");
    const offsets = [...text.slice(xref).matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]));
    offsets.forEach((o, i) => expect(text.slice(o).startsWith(`${i + 1} 0 obj`)).toBe(true));
    expect(new TextDecoder("latin1").decode(figurePdf({ width: 10, height: 10, prims: [
      { kind: "text", x: 1, y: 1, text: "β (x) ≥ 70", size: 8, anchor: "start", fill: "#000" }] }, "#fff", textWidth))).toContain("(? \\(x\\) >= 70) Tj");
  });
});

describe("result views", () => {
  it("shows the region figure, the tracks table and the transfer caveat in Spanish", () => {
    useSettings.setState({ language: "es" });
    const result = { ...base, id: "r1", analysis: "region", method: "blast", tool: "BLAST+", tool_version: "2.12.0", genomes: [], data: REGION } as unknown as ComparisonResultRead;
    renderWith(<RegionView result={result} />);
    expect(screen.getByText("Vecindarios génicos alrededor de seh")).toBeInTheDocument();
    expect(screen.getByText("no encontrada")).toBeInTheDocument();
    expect(screen.getAllByText(/no demuestran por sí solos una transferencia horizontal/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Exportar PDF" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Invertir esta pista" })[1]);
    expect(screen.getByRole("img", { name: "Vecindarios génicos alrededor de seh" })).toBeInTheDocument();
  });

  it("lists matches with the annotated gene and nearby mobile elements, and opens the Region Explorer on a match", () => {
    const onNeighbourhood = vi.fn();
    const result = { ...base, id: "r2", analysis: "gene", method: "tblastn", tool: "BLAST+", tool_version: "2.12.0", genomes: [], data: GENE } as unknown as ComparisonResultRead;
    renderWith(<GeneView result={result} onNeighbourhood={onNeighbourhood} />);
    expect(matchRows(GENE)).toHaveLength(1);
    expect(screen.getByText("IS1182")).toBeInTheDocument();
    expect(screen.getByText(/812 bp away/)).toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument();
    expect(screen.getByText(/a gene tree needs at least four/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Compare this region across genomes (Region Explorer)"));
    expect(onNeighbourhood).toHaveBeenCalledWith(expect.objectContaining({ contig: "NC_003923.1", start: 61524, assembly_id: "a1" }), ["a1"]);
  });

  it("has guide entries for the new analyses in both languages", () => {
    for (const id of ["region_explorer", "gene_investigation", "gene_tree"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.mistakes.length).toBe(GUIDE_BY_ID[id].en.mistakes.length);
    }
  });
});
