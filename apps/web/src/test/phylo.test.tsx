import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TreeView } from "@/components/comparative/TreeView";
import { GUIDE_BY_ID } from "@/guide/metrics";
import type { ComparisonResultRead, ComparisonSet } from "@/lib/comparative";
import { figurePdf } from "@/lib/pdf";
import {
  cladeKey,
  DEFAULT_STYLE,
  fieldValues,
  markedClades,
  patristic,
  type PhyloData,
  prepare,
  scaleBar,
  type TreeNode,
  treeFigure,
  visibleTips,
} from "@/lib/phylo";
import { textWidth } from "@/lib/regions";
import { useSettings } from "@/store/settings";

const leaf = (name: string, length: number): TreeNode => ({ name, length, support: null, children: [] });
const node = (children: TreeNode[], length: number | null, support: number | null, supports?: number[]): TreeNode =>
  ({ name: null, length, support, supports, children });
// The midpoint-rooted IQ-TREE core-genome tree of the five S. aureus genomes (fixtures/phylogeny), labels as in ARVA.
const ROOTED = node([
  node([leaf("N315", 0.0002), leaf("Mu50", 0.00014)], 0.0027, 100, [100, 100]),
  node([leaf("USA300", 0.0045), node([leaf("MW2", 0.0004), leaf("MSSA476", 0.00008)], 0.0046, 100, [100, 100])], 0.0027, 100, [100, 100]),
], null, null);
const THEME = { text: "#000000", muted: "#666666", branch: "#333333", highlight: "#F0E442", absent: "#EEEEEE" };
const META = {
  genomes: ["N315", "Mu50", "USA300", "MW2", "MSSA476"],
  fields: [{ key: "host", custom: false, values: ["human", "human", null, "human", "cow"], recorded: 4, distinct: 2 }],
  amr: { genes: ["mecA"], by_genome: { N315: ["mecA"], Mu50: ["mecA"], USA300: ["mecA"], MW2: ["mecA"], MSSA476: [] } },
};
const LEAVES = META.genomes.map((g) => ({ name: g, genome: g, assembly_id: `a-${g}`, sample_id: `s-${g}` }));

describe("phylogeny helpers", () => {
  it("names clades by their leaves, ladderizes, collapses and measures patristic distances", () => {
    expect(cladeKey(["MW2", "MSSA476"])).toBe(cladeKey(["MSSA476", "MW2"]));
    expect(cladeKey(["MW2", "MSSA476"])).not.toBe(cladeKey(["MW2", "USA300"]));
    const root = prepare(ROOTED, { collapsed: [], ladderize: true });
    expect(root.children.map((c) => c.leaves.length)).toEqual([2, 3]);
    expect(root.children[1].supportText).toBe("100/100");
    const collapsed = prepare(ROOTED, { collapsed: [cladeKey(["MW2", "MSSA476"])], ladderize: true });
    expect(visibleTips(collapsed).map((n) => n.name ?? `${n.leaves.length}`)).toEqual(["N315", "Mu50", "USA300", "2"]);
    expect(patristic(root, "MW2", "MSSA476")).toBeCloseTo(0.00048, 8);
    expect(patristic(root, "N315", "MW2")).toBeCloseTo(0.0002 + 0.0027 + 0.0027 + 0.0046 + 0.0004, 8);
    expect(scaleBar(0.0118)).toBe(0.002);
    expect(markedClades(root, [["MW2", "MSSA476"]]).has(cladeKey(["MW2", "MSSA476"]))).toBe(true);
  });

  it("maps metadata, AMR genes and pangenome families to leaves through their genomes", () => {
    const host = fieldValues("host", LEAVES, META, null, "Host")!;
    expect(host.byLeaf.get("MSSA476")).toBe("cow");
    expect(host.byLeaf.get("USA300")).toBeNull();
    expect([...host.colors.keys()]).toEqual(["human", "cow"]);
    const mecA = fieldValues("amr:mecA", LEAVES, META)!;
    expect(mecA.presence && mecA.byLeaf.get("MSSA476")).toBe("absent");
    const fam = fieldValues("family:sea", LEAVES, META, { name: "sea", genomes: META.genomes, presence: "00011" })!;
    expect(fam.byLeaf.get("MW2")).toBe("present");
  });

  it("draws rectangular and circular figures with supports, bands and a scale bar, and exports them to PDF", () => {
    const bands = [fieldValues("host", LEAVES, META, null, "Host")!];
    const rect = treeFigure(ROOTED, DEFAULT_STYLE, { theme: THEME, bands, unit: "substitutions per site", collapsedLabel: (n) => `${n}` });
    const texts = rect.fig.prims.filter((p) => p.kind === "text").map((p) => (p.kind === "text" ? p.text : ""));
    expect(texts).toEqual(expect.arrayContaining(["N315", "MSSA476", "100/100", "0.001 substitutions per site", "Host"]));
    expect(rect.hits.filter((h) => !h.node.children.length)).toHaveLength(5);
    const circ = treeFigure(ROOTED, { ...DEFAULT_STYLE, layout: "circular", show_support: false }, { theme: THEME, collapsedLabel: (n) => `${n}` });
    const labels = circ.fig.prims.filter((p) => p.kind === "text" && p.rotate !== undefined);
    expect(labels).toHaveLength(5);
    expect(circ.fig.prims.some((p) => p.kind === "text" && p.text === "100/100")).toBe(false);
    const pdf = new TextDecoder().decode(figurePdf(circ.fig, "#FFFFFF", textWidth));
    expect(pdf.startsWith("%PDF-1.4")).toBe(true);
    expect(pdf).toContain(" Tm (MW2) Tj");
  });

  it("has a guide entry in both languages", () => {
    const g = GUIDE_BY_ID.phylo_tree;
    expect(g.en.title).toContain("Tree Explorer");
    expect(g.es?.mistakes.length).toBe(g.en.mistakes.length);
  });
});

const DATA: PhyloData = {
  tree: ROOTED, rooted: ROOTED, rooting: { method: "midpoint", leaves: ["N315", "USA300"], path_length: 0.01 },
  view: { rooting: { method: "midpoint", outgroup: [] }, style: {}, updated_at: "2026-11-02T10:00:00Z" },
  leaves: LEAVES, support: { kind: "alrt_ufboot", label: "SH-aLRT (%) / UFBoot (%)", max: 100 },
  alignment: { sequences: 5, columns: 2186160, constant: 2155266, variable: 30888, parsimony_informative: 19889 },
  distances: null, source: { kind: "core_alignment", result_id: "pan", core: "all" }, iqtree: { model: "TIM2+F+I" },
};
const RESULT = {
  id: "tree1", job_id: "j", set_id: "set", analysis: "phylogeny", method: "iqtree", tool: "IQ-TREE", tool_version: "3.0.1",
  genomes: [], warnings: [], created_at: "2026-11-02T10:00:00Z", parameters: {}, files: {}, summary: {}, data: DATA,
} as unknown as ComparisonResultRead;
const SET = { id: "set", name: "S. aureus", results: [{ id: "tree1", analysis: "phylogeny" }, { id: "tree2", analysis: "phylogeny", tool: "FastTree", method: "fasttree" }] } as unknown as ComparisonSet;

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
  useSettings.setState({ language: "en" });
});

describe("TreeView", () => {
  it("shows the tree with its model and support, and selecting a clade offers collapse and root actions (Spanish)", () => {
    useSettings.setState({ language: "es" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(META), { status: 200, headers: { "Content-Type": "application/json" } })));
    const { container } = renderWith(<TreeView result={RESULT} set={SET} />);
    expect(screen.getByText("TIM2+F+I")).toBeTruthy();
    expect(screen.getByText("SH-aLRT (%) / UFBoot (%)")).toBeTruthy();
    expect(screen.getAllByText("MSSA476").length).toBeGreaterThan(0);
    expect(screen.getByText(/Raíz en el punto medio/)).toBeTruthy();
    const hits = container.querySelectorAll("circle[data-hit]");
    expect(hits.length).toBe(5 + 4);
    fireEvent.click(hits[1]);
    expect(screen.getByRole("button", { name: "Colapsar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enraizar con esto como grupo externo" })).toBeTruthy();
    expect(screen.getByText("Comparar con otro árbol")).toBeTruthy();
  });

  it("selects a node from the keyboard", () => {
    useSettings.setState({ language: "en" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(META), { status: 200, headers: { "Content-Type": "application/json" } })));
    const { container } = renderWith(<TreeView result={RESULT} set={SET} />);
    const node = container.querySelectorAll("circle[data-hit]")[1];
    expect(node.getAttribute("tabindex")).toBe("0");
    expect(node.getAttribute("role")).toBe("button");
    fireEvent.keyDown(node, { key: "Enter" });
    expect(node.getAttribute("aria-pressed")).toBe("true");
  });
});
