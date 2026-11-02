import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { AlignmentView } from "@/components/comparative/AlignmentView";
import { AniView } from "@/components/comparative/AniView";
import { GUIDE_BY_ID } from "@/guide/metrics";
import {
  aniFloor,
  dotSegments,
  explorerUrl,
  heatmapCells,
  identityFloor,
  offsets,
  segmentPoints,
  syntenyLinks,
  type AniMatrix,
  type Block,
  type ComparisonMember,
  type ComparisonResultRead,
} from "@/lib/comparative";
import { useSettings } from "@/store/settings";

// skani 0.4.0 triangle on the four NCBI genomes (workflows/tool-adapters/tests/fixtures/comparative): S. epidermidis
// has no reported pair.
const MATRIX: AniMatrix = {
  ids: ["N315", "Mu50", "USA300", "S. epidermidis"],
  ani: [[null, 99.9, 98.97, null], [99.9, null, 98.86, null], [98.97, 98.86, null, null], [null, null, null, null]],
  af: [[null, 0.9813, 0.937, null], [0.9596, null, 0.9185, null], [0.9119, 0.9141, null, null], [null, null, null, null]],
  directional: false,
};

const base = { job_id: "job-1", tool_version: "0.4.0", created_at: "2026-11-02T09:00:00Z", set_id: "set-1", parameters: {}, files: {} };
const genome = (label: string, i: number) => ({ assembly_id: `asm-${i}`, label, sample_id: `s-${i}`, sample_code: label, contigs_sha256: "0".repeat(64), total_length: 3000, contig_count: 2 });

const ani: ComparisonResultRead = {
  ...base, id: "r-ani", analysis: "ani", method: "skani", tool: "skani", warnings: [],
  genomes: MATRIX.ids.map(genome),
  summary: { matrix: MATRIX, order: { order: [3, 2, 0, 1], merges: [], method: "UPGMA" }, pairs_not_reported: 3 },
};

const blocks: Block[] = [
  ["r1", 1, 1000, "q1", 1, 1000, "+", 99.5, 1000, true],
  ["r1", 1001, 2000, "q2", 1, 1000, "-", 97, 1000, true],
  ["r2", 1, 500, "q1", 1001, 1500, "+", 90, 500, false],
];
const contigs = (a: string, b: string) => [{ name: a, length: 2000 }, { name: b, length: 1000 }];

const alignment: ComparisonResultRead = {
  ...base, id: "r-aln", analysis: "alignment", method: "minimap2", tool: "minimap2", tool_version: "2.26-r1175",
  warnings: [{ code: "minimap2_secondary", params: {} }],
  genomes: [genome("N315", 0), genome("Mu50", 1)],
  summary: {
    reference: "N315", window: 1000,
    pairs: [{ reference: "N315", query: "Mu50", role: "reference", blocks: 2, forward: 1, reverse: 1, ref_aligned: 2000, query_aligned: 2000,
      ref_fraction: 0.6667, query_fraction: 0.6667, identity: 98.25, secondary_blocks: 1 }],
    dnadiff: [{
      reference: "N315", query: "Mu50",
      report: { reference: { inversions: 4, relocations: 5, translocations: 0 }, query: { inversions: 2, relocations: 8, translocations: 0 } },
      reference_differences: [{ sequence: "r1", type: "INV", start: 1001, end: 2000, length: 1000, inserted: 0, category: "inversion" }],
      query_differences: [{ sequence: "q2", type: "BRK", start: 1, end: 200, length: 200, inserted: 200, category: "insertion" }],
    }],
  },
  alignment: {
    genomes: [
      { label: "N315", assembly_id: "asm-0", sample_id: "s-0", contigs: contigs("r1", "r2"), total_length: 3000 },
      { label: "Mu50", assembly_id: "asm-1", sample_id: "s-1", contigs: contigs("q1", "q2"), total_length: 3000 },
    ],
    reference: 0, method: "minimap2",
    pairs: [{ reference: 0, query: 1, role: "reference", blocks }],
    conservation: { reference: "N315", window: 1000, genomes: [{ label: "Mu50", windows: [
      { contig: "r1", start: 1, end: 1000, covered: 1, identity: 99.5 }, { contig: "r1", start: 1001, end: 2000, covered: 1, identity: 97 },
      { contig: "r2", start: 1, end: 1000, covered: 0, identity: null }] }] },
  },
};

const members = [{ assembly_id: "asm-0", annotation_id: "ann-0" }, { assembly_id: "asm-1", annotation_id: null }] as ComparisonMember[];

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => useSettings.setState({ language: "en" }));

describe("comparative geometry", () => {
  it("orders heatmap cells by the similarity order and starts the scale at the lowest ANI", () => {
    const cells = heatmapCells(MATRIX, ani.summary.order!.order);
    expect(cells).toHaveLength(16);
    expect(cells[0]).toEqual({ x: 0, y: 0, value: null, row: "S. epidermidis", col: "S. epidermidis" });
    expect(cells.find((c) => c.row === "N315" && c.col === "Mu50")).toMatchObject({ x: 3, y: 2, value: 99.9 });
    expect(aniFloor(MATRIX)).toBe(98.8);
    expect(aniFloor({ ...MATRIX, ani: [[null]] })).toBe(95);
  });

  it("draws forward blocks up and reverse blocks down, in genome coordinates", () => {
    const { forward, reverse } = dotSegments(blocks, offsets(contigs("r1", "r2")), offsets(contigs("q1", "q2")), true);
    expect(forward).toEqual([[[1, 1], [1000, 1000]]]);
    expect(reverse).toEqual([[[1001, 3000], [2000, 2001]]]);
    expect(dotSegments(blocks, offsets(contigs("r1", "r2")), offsets(contigs("q1", "q2")), false).forward).toHaveLength(2);
    expect(segmentPoints(forward)).toEqual([[1, 1], [1000, 1000], "-"]);
  });

  it("links primary blocks above the minimum length, as fractions of each genome", () => {
    const lay = (a: string, b: string) => ({ offsets: offsets(contigs(a, b)), total: 3000 });
    const links = syntenyLinks(blocks, lay("r1", "r2"), lay("q1", "q2"), 0);
    expect(links).toHaveLength(2);
    expect(links[1]).toMatchObject({ r0: 1000 / 3000, r1: 2000 / 3000, q0: 2000 / 3000, q1: 1, reverse: true });
    expect(syntenyLinks(blocks, lay("r1", "r2"), lay("q1", "q2"), 5000)).toHaveLength(0);
  });

  it("starts the identity colour scale at the 5th percentile", () => {
    expect(identityFloor([])).toBe(90);
    expect(identityFloor([40, ...Array.from({ length: 99 }, () => 98.6)])).toBe(98);
    expect(identityFloor([100, 100])).toBe(99);
  });

  it("builds a Genome Explorer address with a margin, only for annotated genomes", () => {
    expect(explorerUrl("ann-1", "NC_002745.2", 5000, 6000)).toBe("/explorer/ann-1?contig=NC_002745.2&start=4500&end=6500");
    expect(explorerUrl(null, "c", 1, 2)).toBeNull();
  });

  it("has guide entries for every comparative explanation", () => {
    for (const id of ["ani_matrix", "genome_alignment", "synteny_plot", "structural_differences"] as const) expect(GUIDE_BY_ID[id]).toBeDefined();
  });
});

describe("comparative views", () => {
  it("labels the ANI heatmap order as similarity clustering, not a phylogeny (Spanish)", () => {
    useSettings.setState({ language: "es" });
    renderWith(<AniView result={ani} />);
    expect(screen.getByText(/no una filogenia/)).toBeInTheDocument();
    expect(screen.getByText(/3 pares no fueron informados/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tabla de ANI/ })).toHaveAttribute("href", "/api/v1/comparisons/results/r-ani/ani.csv");
  });

  it("shows pairs, figures and dnadiff's differences with links into the Genome Explorer", () => {
    renderWith(<AlignmentView result={alignment} members={members} />);
    expect(screen.getByText("Dot plot")).toBeInTheDocument();
    expect(screen.getByText("Synteny across the order")).toBeInTheDocument();
    expect(screen.getByText("Conservation along N315")).toBeInTheDocument();
    const table = screen.getByText("dnadiff's reading").closest("table")!;
    const inversion = within(table).getByText("Inversion").closest("tr")!;
    expect(within(inversion).getByRole("link")).toHaveAttribute("href", "/explorer/ann-0?contig=r1&start=501&end=2500");
    const insertion = within(table).getByText("Sequence absent from the other genome").closest("tr")!;
    expect(within(insertion).queryByRole("link")).toBeNull();
    expect(screen.getByRole("link", { name: /Alignment blocks/ })).toHaveAttribute("href", "/api/v1/comparisons/results/r-aln/blocks.csv");
  });
});
