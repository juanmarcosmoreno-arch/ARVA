import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PangenomeView } from "@/components/comparative/PangenomeView";
import { GUIDE_BY_ID } from "@/guide/metrics";
import type { ComparisonResultRead } from "@/lib/comparative";
import { band, filterFamilies, fmtP, heatmap, holders, type PangenomeData } from "@/lib/pangenome";
import { useSettings } from "@/store/settings";

vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" data-option={JSON.stringify(props.option)} />;
  }),
}));

const fam = (name: string, presence: string, category: "core" | "shell" | "cloud", gene_names: string[] = [], annotation = "hypothetical protein") => ({
  name, gene_names, annotation, count: [...presence].filter((c) => c === "1").length, category, partition: null, members: 1, presence,
});

const DATA: PangenomeData = {
  genomes: ["N315", "Mu50", "MW2"].map((label, i) => ({ label, tool_name: `g${i + 1}`, assembly_id: `a${i}`, sample_id: `s${i}`, annotation_id: `ann${i}` })),
  families: [fam("dnaA", "111", "core", ["dnaA"], "Chromosomal replication initiator protein DnaA"), fam("group_7", "110", "shell"),
    fam("sea", "001", "cloud", ["sea"], "Enterotoxin type A"), fam("group_9", "100", "cloud")],
  family_order: [0, 1, 3, 2],
  clustering: { order: [1, 0, 2], merges: [[0, 1, 0.01, 2], [2, 3, 0.2, 3]], method: "average linkage (UPGMA) on the Jaccard distance", distances: [] },
  curves: { method: "random orders", permutations: 20, seed: 7, k: [1, 2, 3],
    pan: { mean: [2.5, 3.4, 4], sd: [0.5, 0.4, 0], min: [2, 3, 4], max: [3, 4, 4] },
    core: { mean: [2.5, 1.6, 1], sd: [0.5, 0.4, 0], min: [2, 1, 1], max: [3, 2, 1] } },
  distribution: [{ genomes: 1, families: 2 }, { genomes: 2, families: 1 }, { genomes: 3, families: 1 }],
};

const RESULT = {
  id: "r1", job_id: "j1", set_id: "set", analysis: "pangenome", method: "panaroo", tool: "Panaroo", tool_version: "1.8.1",
  genomes: [], warnings: [], created_at: "2026-11-02T10:00:00Z", parameters: {},
  files: { "panaroo/gene_presence_absence.Rtab": { path: "x", sha256: "y", size_bytes: 1 } },
  summary: { genomes: 3, families: 4, category_counts: { core: 1, soft_core: 0, shell: 1, cloud: 2 }, thresholds: { core: 0.99, soft_core: 0.95, shell: 0.15 },
    tool_summary: { core: 1, soft_core: 0, shell: 1, cloud: 2, total: 4 }, partitions: null,
    annotation_consistency: { consistent: false, annotators: [{ annotator: "Bakta 1.12.2", genomes: ["N315"] }, { annotator: "Prokka 1.14.6", genomes: ["Mu50", "MW2"] }] },
    per_genome: [{ label: "N315", families: 3, unique: 1 }, { label: "Mu50", families: 2, unique: 0 }, { label: "MW2", families: 2, unique: 1 }], aligned: false },
  data: DATA,
} as unknown as ComparisonResultRead;

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
  useSettings.setState({ language: "en" });
});

describe("pangenome helpers", () => {
  it("draws only accessory families in family order, genomes in clustering order", () => {
    const h = heatmap(DATA, 2);
    expect(h.genomes).toEqual(["Mu50", "N315", "MW2"]);
    expect(h.families).toEqual(["group_7", "group_9"]);
    expect(h.hidden).toBe(1);
    expect(h.cells.filter((c) => c[1] === 1)).toEqual([[0, 1, 0], [1, 1, 1], [2, 1, 0]]);
  });

  it("builds curve bands, filters families and formats p-values", () => {
    expect(band(DATA.curves.pan)).toEqual({ low: [2, 3, 4], height: [1, 1, 0] });
    expect(filterFamilies(DATA.families, "enterotoxin", "all")).toEqual([2]);
    expect(filterFamilies(DATA.families, "", "cloud")).toEqual([2, 3]);
    expect(holders(DATA, DATA.families[1])).toEqual(["N315", "Mu50"]);
    expect(fmtP(0.0123)).toBe("0.0123");
    expect(fmtP(0.00001234)).toBe("1.23e-5");
  });

  it("has guide entries in both languages", () => {
    for (const id of ["pangenome", "pangenome_curves"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.mistakes.length).toBe(GUIDE_BY_ID[id].en.mistakes.length);
    }
  });
});

describe("PangenomeView", () => {
  it("shows the categories with their thresholds, the annotation warning and the family table in Spanish", () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ genomes: ["N315", "Mu50", "MW2"], fields: [] }),
      { status: 200, headers: { "Content-Type": "application/json" } }));
    renderWith(<PangenomeView result={RESULT} onNeighbourhood={() => undefined} />);
    expect(screen.getAllByText("Familias de genes").length).toBeGreaterThan(0);
    expect(screen.getByText(/se anotaron con anotadores, versiones o bases de datos distintos/)).toBeInTheDocument();
    expect(screen.getByText("Enterotoxin type A")).toBeInTheDocument();
    expect(screen.getByText(/no es una filogenia/)).toBeInTheDocument();
    expect(screen.getByText(/Exploratorio/)).toBeInTheDocument();
    expect(screen.getAllByTestId("chart")).toHaveLength(3);
  });
});
