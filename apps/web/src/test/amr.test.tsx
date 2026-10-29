import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CircularExplorer } from "@/components/explorer/CircularMap";
import { GenomeBrowser } from "@/components/explorer/GenomeBrowser";
import { AmrCard } from "@/components/genomic/AmrResult";
import { ProjectAmr } from "@/components/genomic/ProjectAmr";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { amrBody, amrFeatures, amrProblems, initialAmrForm, matrixCell, sections, warningText } from "@/lib/amr";
import { api } from "@/lib/api";
import type { AmrHit, AmrMapHit, AmrPlan, AmrProjectOverview, AmrRun, Annotation, GenomeMap, GenomeTracks } from "@/lib/types";
import { useSettings } from "@/store/settings";

// The hits are AMRFinderPlus 4.2.7's on the fixtures in workflows/tool-adapters/tests/fixtures/amrfinderplus: S. aureus
// N315 (NCBI NC_002745.2 and NC_003140.1) and the edited input derived from it (a test construct, not biology).
const hit = (over: Partial<AmrHit>): AmrHit => ({
  id: "h", job_id: "job-amr", annotation_id: null, element_symbol: "mecA", element_name: "PBP2a family beta-lactam-resistant peptidoglycan transpeptidase MecA",
  scope: "core", type: "AMR", subtype: "AMR", amr_class: "BETA-LACTAM", amr_subclass: "METHICILLIN", method: "EXACTX", method_kind: "complete",
  identity: 100, coverage: 100, target_length: 668, reference_length: 668, alignment_length: 668, contig: "contig_1", assembly_contig: "NC_002745.2",
  start: 45034, stop: 47037, strand: "-", protein_id: null, closest_accession: "WP_000721310.1", closest_name: "PBP2a family beta-lactam-resistant peptidoglycan transpeptidase MecA",
  hmm_accession: null, hmm_description: null, hierarchy_node: "mecA", feature: null, ...over,
});

const hits: AmrHit[] = [
  hit({ id: "h1", feature: { annotation_id: "ann", feature_id: 39, locus_tag: "NTEST_00039", gene: "mecA", product: "PBP2a", how: "overlap", overlap: 1 } }),
  hit({ id: "h2", element_symbol: "mecA", method: "PARTIAL_CONTIG_ENDX", method_kind: "contig_end", coverage: 59.88, start: 3, stop: 1202, assembly_contig: "NC_002745.2_part2" }),
  hit({ id: "h3", element_symbol: "blaZ", element_name: "penicillin-hydrolyzing class A beta-lactamase BlaZ", amr_subclass: "BETA-LACTAM", method: "INTERNAL_STOP", method_kind: "internal_stop", identity: 99.64, start: 7948, stop: 8790, assembly_contig: "NC_003140.1" }),
  hit({ id: "h4", element_symbol: "gyrA_S84L", element_name: "Staphylococcus aureus quinolone resistant GyrA", subtype: "POINT", amr_class: "QUINOLONE", amr_subclass: "QUINOLONE", method: "POINTX", method_kind: "point", identity: 99.66, start: 7005, stop: 9665, strand: "+" }),
  hit({ id: "h5", element_symbol: "tst", element_name: "toxic shock syndrome toxin TSST-1", scope: "plus", type: "VIRULENCE", subtype: "VIRULENCE", amr_class: null, amr_subclass: null, method: "BLASTX", identity: 99.15, start: 2061076, stop: 2061777, strand: "+" }),
];

const run = (over: Partial<AmrRun> = {}): AmrRun => ({
  job_id: "job-amr", sample_id: "s", assembly_id: "asm-00001", annotation_id: null, status: "completed", created_at: "2026-10-29T20:00:00Z", finished_at: "2026-10-29T20:01:00Z",
  tool: "AMRFinderPlus", tool_version: "4.2.7", database_name: "AMRFinderPlus database", database_version: "2026-08-07.1", database_checksum: "sha256:fd4a", database_path: "/db",
  parameters: { mode: "nucleotide", organism: "Staphylococcus_aureus", plus: true, ident_min: -1, coverage_min: 0.5, translation_table: 11 },
  organism_choice: { proposed: "Staphylococcus_aureus", rule: "species", chosen: "Staphylococcus_aureus", changed_by_user: false, species: null },
  mode: "nucleotide",
  warnings: [{ code: "genotype_not_phenotype", params: {} }, { code: "hits_contig_end", params: { count: 1, genes: "mecA" } }, { code: "hits_internal_stop", params: { count: 1, genes: "blaZ" } }],
  counts: { total: 5, AMR: 4, VIRULENCE: 1, STRESS: 0, point_mutations: 1, incomplete: 2 },
  point_mutation_screen: { rows: 120, genes: ["DNA gyrase subunit A GyrA"], wildtype_positions: 110, unknown_changes: 9, mutations: 1 },
  files: { report: { path: "r/amrfinder.tsv", sha256: "x", size_bytes: 1 } }, log: { search: "translated nucleotide and mutation" },
  hits, by_class: [{ class: "BETA-LACTAM", elements: ["blaZ", "mecA"], count: 2 }, { class: "QUINOLONE", elements: ["gyrA_S84L"], count: 1 }],
  ...over,
});

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AMR result", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });

  it("shows genes found with their method, partial and contig-end hits as such, point mutations apart and the disclaimer", () => {
    renderWith(<AmrCard run={run()} />);
    expect(screen.getByRole("note")).toHaveTextContent(/Genotype is not phenotype/);
    expect(screen.queryByText(/^(resistant|susceptible)$/i)).toBeNull();
    const amr = screen.getByRole("region", { name: "AMR genes" });
    expect(within(amr).getAllByRole("row")).toHaveLength(4);
    expect(within(amr).getByText("partial, at contig end")).toBeInTheDocument();
    expect(within(amr).getByText("PARTIAL_CONTIG_ENDX")).toBeInTheDocument();
    expect(within(amr).getByText("internal stop")).toBeInTheDocument();
    expect(within(amr).getByRole("link", { name: "NTEST_00039" })).toHaveAttribute("href", "/explorer/ann?feature=39");
    const point = screen.getByRole("region", { name: "Point mutations" });
    expect(within(point).getByText("gyrA_S84L")).toBeInTheDocument();
    expect(within(point).getByText("point mutation")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Virulence genes" })).toHaveTextContent("tst");
    expect(screen.getByText(/partial at a contig end \(PARTIAL_CONTIG_END\)/)).toBeInTheDocument();
    expect(screen.getByText(/BETA-LACTAM · 2/)).toBeInTheDocument();
    expect(screen.getByText(/110 curated positions checked were wild type/)).toBeInTheDocument();
  });

  it("says not searched, not zero, for point mutations without an organism and for virulence without --plus", () => {
    renderWith(<AmrCard run={run({ parameters: { mode: "nucleotide", organism: null, plus: false, ident_min: -1, coverage_min: 0.5, translation_table: 11 }, hits: [], by_class: [], counts: { total: 0 }, point_mutation_screen: null, warnings: [{ code: "point_mutations_not_searched", params: {} }] })} />);
    expect(screen.getAllByText("not searched")).toHaveLength(3);
    expect(screen.getByText("None found")).toBeInTheDocument();
    expect(screen.getByText(/does not prove that the isolate has no resistance mechanism/)).toBeInTheDocument();
    expect(screen.getByText(/point mutations were not searched \(not 'none found'\)/)).toBeInTheDocument();
  });

  it("orders the table sections and reads every coded warning in both languages", () => {
    expect(sections(hits).map((s) => [s.key, s.hits.length])).toEqual([["amr", 3], ["point", 1], ["virulence", 1]]);
    const t = (k: string, vars?: Record<string, string | number>) => dictionaries.es[k as keyof typeof dictionaries.es]?.replace("{genes}", String(vars?.genes ?? "")) ?? k;
    expect(warningText(t as never, { code: "hits_internal_stop", params: { count: 1, genes: "blaZ" } })).toContain("blaZ");
    for (const code of ["genotype_not_phenotype", "hits_partial", "hits_contig_end", "hits_internal_stop", "hits_hmm", "point_mutations_not_searched", "point_mutation_genes_not_found", "plus_not_searched", "curated_thresholds_overridden", "synthetic_input"])
      for (const lang of ["en", "es"] as const) expect(dictionaries[lang][`amr.warning.${code}` as keyof typeof dictionaries.en]).toBeTruthy();
    for (const id of ["amr", "amr_methods", "point_mutation", "genotype_phenotype"] as const) expect(GUIDE_BY_ID[id].es.title).toBeTruthy();
  });

  it("builds the request with AMRFinderPlus's defaults passed explicitly", () => {
    const form = { ...initialAmrForm("asm"), organism: "Staphylococcus_aureus", confirmed: true };
    expect(amrBody(form)).toEqual({ settings: { mode: "nucleotide", organism: "Staphylococcus_aureus", plus: true, ident_min: -1, coverage_min: 0.5, translation_table: 11 }, database_id: null, annotation_id: null, threads: null, confirmed: true });
    const plan = { organisms: ["Staphylococcus_aureus"], tool: { max_threads: 4 } } as unknown as AmrPlan;
    expect(amrProblems({ ...form, organism: "Bacillus" }, plan)).toEqual(["amr.problem.organism"]);
    expect(amrProblems({ ...form, mode: "combined", curated: false, identMin: "2" }, plan)).toEqual(["amr.problem.identMin", "amr.problem.annotation"]);
  });
});

describe("Project AMR matrix", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });

  it("marks found, partly found, searched-and-absent and not searched", async () => {
    const overview: AmrProjectOverview = {
      project_id: "p", project_name: "P", is_demo: false, searched: 2, versions: ["4.2.7 / 2026-08-07.1"],
      elements: [{ element_symbol: "mecA", type: "AMR", subtype: "AMR", class: "BETA-LACTAM" }, { element_symbol: "blaZ", type: "AMR", subtype: "AMR", class: "BETA-LACTAM" }],
      samples: [
        { sample_id: "s1", sample_code: "N315", runs: 1, latest: { job_id: "j1", created_at: "", tool_version: "4.2.7", database_version: "2026-08-07.1", parameters: {}, counts: {}, warnings: [] }, present: { mecA: ["complete"], blaZ: ["internal_stop"] } },
        { sample_id: "s2", sample_code: "EMPTY", runs: 1, latest: { job_id: "j2", created_at: "", tool_version: "4.2.7", database_version: "2026-08-07.1", parameters: {}, counts: {}, warnings: [] }, present: {} },
        { sample_id: "s3", sample_code: "NEW", runs: 0, latest: null, present: {} },
      ],
    };
    vi.spyOn(api, "amrProject").mockResolvedValue(overview);
    renderWith(<ProjectAmr projectId="p" />);
    expect(await screen.findByText(/2 of 3 samples searched/)).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(within(rows[2]).getByTitle("found")).toHaveTextContent("●");
    expect(within(rows[2]).getByTitle(/found only partly/)).toHaveTextContent("◐");
    expect(within(rows[3]).getAllByTitle("searched, not found")).toHaveLength(2);
    expect(within(rows[4]).getAllByTitle("not searched")).toHaveLength(2);
    expect(matrixCell(true, ["partial", "complete"])).toBe("found");
  });
});

const genomeMap = (): GenomeMap => ({
  total_length: 10_000, points: 1440, sequence_source: { file: "fna", tool: "Bakta", sha256: "x" },
  gc: { window: 500, step: 500, auto: true, genome_gc: 0.33 },
  coverage: { available: false, reason: "no_alignment", source: null },
  sequences: [{ contig: "contig_1", contig_in_assembly: "NC_002745.2", length: 10_000, topology: "circular", gc: { contig_gc: 0.33, start: [1], end: [10_000], gc: [0.33], skew: [0] }, coverage: { available: false, reason: "no_alignment", start: [], end: [], mean: [] } }],
  total: 1,
  features: [{ id: 39, contig: "contig_1", locus_tag: "NTEST_00039", tool_id: null, type: "cds", start: 2_500, end: 5_000, strand: "-", length: 2_501, edge: false, gene: "mecA", product: "PBP2a", hypothetical: false, pseudo: false, partial: null }],
});

const mapHits: AmrMapHit[] = [
  { ...hits[0], contig: "contig_1", start: 2_500, stop: 5_000, end: 5_000 },
  { ...hits[2], contig: "contig_1", start: 6_000, stop: 6_800, end: 6_800 },
];

describe("AMR on the circular map and in the explorer", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
    vi.spyOn(api, "annotationVirulence").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationMobile").mockResolvedValue({ runs: {}, contigs: [], elements: [] });
  });
  const annotation = { id: "ann", tool: "Bakta", tool_version: "1.12.2", database_name: "Bakta", database_version: "6.0", summary: { synthetic_evidence: [] } } as unknown as Annotation;
  const contigs = [{ id: "contig_1", name: "NC_002745.2", length: 10_000, circular: true, circularSource: "Bakta" }];

  it("draws the AMR ring from the run, with a legend and tooltips, and keeps virulence off without --plus", async () => {
    vi.spyOn(api, "annotationMap").mockResolvedValue(genomeMap());
    vi.spyOn(api, "annotationAmr").mockResolvedValue({ run: { job_id: "job-amr", tool_version: "4.2.7", database_version: "2026-08-07.1", organism: "Staphylococcus_aureus", plus: false, mode: "nucleotide", created_at: "" }, hits: mapHits });
    const onSelect = vi.fn();
    const { container } = renderWith(<CircularExplorer annotation={annotation} contigs={contigs} sampleCode="N315" selected={null} onSelect={onSelect} onShowLinear={() => {}} />);
    await waitFor(() => expect(container.querySelector('[data-ring="amr"]')).not.toBeNull());
    expect(screen.getByLabelText(/Antimicrobial resistance/)).toBeEnabled();
    expect(screen.getByLabelText(/^Virulence factors(?! \(VFDB)/)).toBeDisabled();
    expect(screen.getByText(/did not search virulence genes/)).toBeInTheDocument();
    expect(screen.getByText(/AMR ring: 2 AMR genes, point mutations and stress genes/)).toBeInTheDocument();
    expect(screen.getByText(/not phenotypes\./)).toBeInTheDocument();
    const ring = container.querySelector('[data-ring="amr"]')!;
    expect(ring.querySelectorAll("path")).toHaveLength(2); // the complete hit filled, the internal stop hollow
    expect(amrFeatures(mapHits, "amr").map((f) => f.id)).toEqual([-1, -2]);
  });

  it("adds an AMR track to the linear browser, hollow for incomplete hits, that opens the linked gene", async () => {
    const tracks: GenomeTracks = {
      contig: "contig_1", contig_in_assembly: "NC_002745.2", length: 10_000, start: 1, end: 10_000, points: 2, sequence_source: { file: "fna", tool: "Bakta", sha256: "x" },
      gc: { window: 5_000, step: 5_000, auto: true, windows: 2, group: 1, contig_gc: 0.33, start: [1, 5_001], end: [5_000, 10_000], gc: [0.3, 0.35], gc_min: [0.3, 0.35], gc_max: [0.3, 0.35], skew: [0.1, -0.1], skew_min: [0.1, -0.1], skew_max: [0.1, -0.1] },
      coverage: { available: false, reason: "no_alignment", start: [], end: [], mean: [], min: [], max: [] },
    };
    vi.spyOn(api, "annotationTracks").mockResolvedValue(tracks);
    vi.spyOn(api, "annotationAmr").mockResolvedValue({ run: { job_id: "job-amr", tool_version: "4.2.7", database_version: "2026-08-07.1", organism: null, plus: true, mode: "nucleotide", created_at: "" }, hits: mapHits });
    const onSelect = vi.fn();
    const layout = { contig: "contig_1", contig_in_assembly: "NC_002745.2", length: 10_000, total: 1, items: genomeMap().features };
    const { container } = renderWith(
      <GenomeBrowser annotationId="ann" contig={contigs[0]} layout={layout} layoutError={null} view={{ from: 0, to: 10_000 }} onView={() => {}} selected={null} onSelect={onSelect}
        marked={new Set()} onToggleMark={() => {}} region={null} onRegion={() => {}} gc={{ window: null, step: null }} />,
    );
    await waitFor(() => expect(container.querySelector('[data-amr="blaZ"]')).not.toBeNull());
    expect(container.querySelector('[data-amr="mecA"]')!.getAttribute("fill")).not.toBe(container.querySelector('[data-amr="blaZ"]')!.getAttribute("fill"));
    expect(container.querySelector('[data-amr="blaZ"] title')!.textContent).toContain("internal stop (INTERNAL_STOP)");
    fireEvent.click(container.querySelector('[data-amr="mecA"]')!);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 39 }));
  });
});
