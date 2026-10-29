import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CircularExplorer } from "@/components/explorer/CircularMap";
import { MobileContigCard, MobileRunCard } from "@/components/genomic/MobileResult";
import { VirulenceCard } from "@/components/genomic/Virulence";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { api } from "@/lib/api";
import { flagOf, initialMobileForm, isWholeElement, mobileBody, mobileFeatures, mobileProblems, settingKind, warningText } from "@/lib/mobile";
import type { Annotation, GenomeMap, MobileContigTable, MobileMapElement, MobilePlan, MobileRow, MobileRun, VirulenceRow, VirulenceRun, VirulenceSample } from "@/lib/types";
import { useSettings } from "@/store/settings";

// Values from the real runs in workflows/tool-adapters/tests/fixtures: MOB-suite 3.1.9 and IntegronFinder 2.0.6 on
// plasmid R388 (NCBI NC_028464.1), ABRicate 1.4.0 (VFDB, PlasmidFinder) on S. aureus N315 (NC_002745.2, NC_003140.1).
function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const row = (over: Partial<MobileRow>): MobileRow => ({
  id: "r", job_id: "job-mob", tool: "MOB-suite", category: "biomarker", element: null, element_type: null, contig: null, start: null, end: null, strand: null,
  identity: null, coverage: null, score: null, completeness: null, details: null, feature: null, ...over,
});

const mobRun = (over: Partial<MobileRun> = {}): MobileRun => ({
  job_id: "job-mob", sample_id: "s", assembly_id: "asm-r388", method: "mobsuite", status: "completed", created_at: "2026-10-29T20:00:00Z", finished_at: null,
  tool: "MOB-suite", tool_version: "3.1.9", database_kind: "mobsuite", database_name: "MOB-suite database", database_version: "3.1.8", database_checksum: "sha256:4d54d0ee", database_path: "/db",
  parameters: { min_rep_evalue: 1e-5, threads: 4 }, warnings: [{ code: "chromosome_means_unassigned", params: {} }], counts: {}, files: { contig_report: { path: "x", sha256: "y", size_bytes: 1 } }, searched_contigs: ["NC_028464.1"],
  rows: [
    row({ id: "c1", category: "contig", element: "NC_028464.1", element_type: "plasmid", contig: "NC_028464.1" }),
    row({ id: "p1", category: "plasmid", element: "AD768", element_type: "conjugative" }),
    row({ id: "b1", category: "biomarker", element: "IncW", element_type: "rep_type", contig: "NC_028464.1" }),
  ],
  ...over,
});

const table: MobileContigTable = {
  assembly_id: "asm-r388", assembler: "Flye", assembler_version: "2.9.3",
  runs: { mobsuite: "job-mob", plasmidfinder: null, integronfinder: "job-if", isescan: null, genomad: null },
  contigs: [{
    contig: "NC_028464.1", length: 33_913, circular: true, circular_source: "Flye",
    mobsuite: { molecule_type: "plasmid", primary_cluster_id: "AD768", secondary_cluster_id: "AN421", rep_types: ["IncW"], relaxase_types: ["MOBF"], mpf_types: ["MPF_T"], orit_types: ["MOBF"], predicted_mobility: "conjugative" },
    replicons: null, integrons: 1, insertion_sequences: null, genomad: null,
  }],
};

describe("plasmid and mobile-element results", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });

  it("puts each tool's call side by side and keeps 'not searched' apart from 'none found'", () => {
    renderWith(<MobileContigCard table={table} />);
    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells[1].textContent).toContain("plasmid");
    expect(cells[1].textContent).toContain("cluster AD768 / AN421");
    expect(cells[2].textContent).toBe("IncW");
    expect(cells[3].textContent).toContain("MOBF");
    expect(cells[3].textContent).toContain("MPF MPF_T");
    expect(cells[4].textContent).toBe("conjugative");
    expect(cells[5].textContent).toBe("Not searched");
    expect(cells[6].textContent).toBe("1 / Not searched / Not searched");
    expect(cells[7].textContent).toBe("yes (Flye)");
    expect(screen.getByText(/never a contig's size/)).toBeInTheDocument();
    const none = { ...table, contigs: [{ ...table.contigs[0], replicons: [], circular: null }] };
    renderWith(<MobileContigCard table={none} />);
    expect(screen.getAllByText("None found")).toHaveLength(1);
    expect(screen.getAllByText("not reported").length).toBeGreaterThan(0);
  });

  it("shows a run's calls by category, its warnings in the interface language, its database and settings", () => {
    useSettings.setState({ language: "es" });
    renderWith(<MobileRunCard run={mobRun()} />);
    expect(screen.getByText(/no prueba que el contig sea cromosómico/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Plásmidos reconstruidos (MOB-suite)" })).toBeInTheDocument();
    expect(screen.getByText("AD768")).toBeInTheDocument();
    expect(screen.getByText(/min_rep_evalue=0.00001/)).toBeInTheDocument();
    expect(screen.queryByText(/threads=/)).toBeNull();
    expect(screen.getByText("sha256:4d54d0ee")).toBeInTheDocument();
  });

  it("says a run that found nothing found nothing (the synthetic genome)", () => {
    renderWith(<MobileRunCard run={mobRun({ rows: [row({ category: "contig", element: "SYNTHETIC_chromosome", element_type: "chromosome" })], warnings: [{ code: "synthetic_input", params: { evidence: "SYNTHETIC in the contig names" } }] })} />);
    expect(screen.getAllByText("None found")).toHaveLength(1);
    expect(screen.getByText(/describes the tools on test data, not biology/)).toBeInTheDocument();
  });

  it("builds the request from ARVA's defaults and what the user changed, with each tool's own flag names", () => {
    const plan = { defaults: { min_rep_evalue: "1e-05", min_length: "1000", keep_palindromes: "False", local_max: "True" }, tool: { max_threads: 8 } } as unknown as MobilePlan;
    const form = { ...initialMobileForm("asm", "integronfinder"), settings: { min_length: "1500", local_max: "False" }, confirmed: true };
    expect(mobileBody(form, plan)).toEqual({ method: "integronfinder", settings: { min_rep_evalue: 1e-5, min_length: 1500, local_max: false }, database_id: null, threads: null, confirmed: true });
    expect(mobileProblems({ ...form, settings: { min_length: "1.5" } }, plan)).toEqual(["mobile.problem.setting"]);
    expect(mobileProblems({ ...form, confirmed: false, threads: "9" }, plan)).toEqual(["amr.problem.threads", "amr.problem.confirm"]);
    expect([settingKind("True"), settingKind("80"), settingKind("1e-05")]).toEqual(["bool", "int", "float"]);
    expect(flagOf("integronfinder", "calin_threshold")).toBe("--calin-threshold");
    expect(flagOf("mobsuite", "min_rep_evalue")).toBe("--min_rep_evalue");
    expect(flagOf("isescan", "remove_short_is")).toBe("--removeShortIS");
  });

  it("draws whole elements filled and partial ones hollow", () => {
    expect(isWholeElement({ category: "plasmid_contig", completeness: null })).toBe(true);
    expect(isWholeElement({ category: "integron", completeness: "complete" })).toBe(true);
    expect(isWholeElement({ category: "integron", completeness: "CALIN" })).toBe(false);
    expect(isWholeElement({ category: "replicon", completeness: "partial" })).toBe(false);
    const t = (k: string) => k;
    expect(warningText(t as never, { code: "nope", params: {} })).toBe("nope");
  });

  it("has guide entries in both languages", () => {
    for (const id of ["plasmid", "replicon", "mobile_element", "virulence_factor", "vfdb"] as const) {
      expect(GUIDE_BY_ID[id]).toBeDefined();
    }
  });
});

const vfdbRow = (over: Partial<VirulenceRow>): VirulenceRow => ({
  source: "vfdb", gene: "adsA", contig: "NC_002745.2", start: 31_006, end: 33_324, strand: "+", identity: 96.46, coverage: 100, kind: "complete", method: "1-2319/2319",
  description: null, vf_name: "AdsA", vf_id: "VF0422", vf_category: "Immune modulation", reference: "WP_000645781", pieces: null, id: "v1", also_found_by: [], ...over,
});

describe("virulence factors from both sources", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });
  const run = { job_id: "job-vf", tool_version: "1.4.0", database_version: "2026-04-03", parameters: { minid: 80, mincov: 80 }, database_terms: { licence: "not stated" }, warnings: [{ code: "vfdb_meaning", params: {} }, { code: "hits_partial", params: { count: 1, genes: "hlb" } }], files: {} } as unknown as VirulenceRun;

  it("keeps each row's source and method, and says which source was not searched", () => {
    const view: VirulenceSample["assemblies"][number] = {
      assembly_id: "asm-n315",
      sources: { vfdb: { status: "searched", job_id: "job-vf", tool_version: "1.4.0", database_version: "2026-04-03", hits: 2 }, amrfinderplus: { status: "not_searched", job_id: null, tool_version: null, database_version: null, hits: 0 } },
      rows: [vfdbRow({}), vfdbRow({ id: "v2", gene: "hlb", start: 2_049_578, end: 2_050_401, identity: 99.27, coverage: 82.98, kind: "partial", method: "170-993/993", vf_name: "Beta-hemolysin" })],
    };
    renderWith(<VirulenceCard view={view} runs={[run]} />);
    expect(screen.getByText("VFDB (ABRicate): 2 genes (1.4.0, database 2026-04-03)")).toBeInTheDocument();
    expect(screen.getByText("AMRFinderPlus: not searched on this assembly")).toBeInTheDocument();
    expect(screen.getByText(/1 hit covers only part of the VFDB reference: hlb/)).toBeInTheDocument();
    expect(screen.queryByText(/A VFDB hit is nucleotide similarity/)).toBeNull();
    const rows = screen.getAllByRole("row");
    expect(within(rows[2]).getByText("partial")).toBeInTheDocument();
    expect(within(rows[2]).getByText("170-993/993")).toBeInTheDocument();
  });

  it("shows AMRFinderPlus rows with AMRFinderPlus's own method kinds", () => {
    const view: VirulenceSample["assemblies"][number] = {
      assembly_id: "asm-n315",
      sources: { vfdb: { status: "not_searched", job_id: null, tool_version: null, database_version: null, hits: 0 }, amrfinderplus: { status: "searched", job_id: "job-amr", tool_version: "4.2.7", database_version: "2026-08-07.1", hits: 1 } },
      rows: [vfdbRow({ source: "amrfinderplus", gene: "tst", kind: "complete", method: "BLASTX", vf_name: null, description: "toxic shock syndrome toxin TSST-1", also_found_by: ["vfdb"] })],
    };
    renderWith(<VirulenceCard view={view} runs={[]} />);
    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells[0].textContent).toBe("AMRFinderPlus");
    expect(cells[3].textContent).toContain("BLASTX");
    expect(cells[7].textContent).toBe("vfdb");
  });
});

describe("mobile elements and VFDB on the circular map", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
  });
  const map: GenomeMap = {
    total_length: 33_913, points: 1440, sequence_source: { file: "fna", tool: "Bakta", sha256: "x" },
    gc: { window: 500, step: 500, auto: true, genome_gc: 0.575 },
    coverage: { available: false, reason: "no_alignment", source: null },
    sequences: [{ contig: "contig_1", contig_in_assembly: "NC_028464.1", length: 33_913, topology: "circular", gc: { contig_gc: 0.575, start: [1], end: [33_913], gc: [0.575], skew: [0] }, coverage: { available: false, reason: "no_alignment", start: [], end: [], mean: [] } }],
    total: 0, features: [],
  };
  const annotation = { id: "ann", tool: "Bakta", tool_version: "1.12.2", summary: { synthetic_evidence: [] } } as unknown as Annotation;
  const contigs = [{ id: "contig_1", name: "NC_028464.1", length: 33_913, circular: true, circularSource: "Flye" }];
  const integron: MobileMapElement = { ...row({ id: "i1", tool: "IntegronFinder", category: "integron", element: "integron_01", element_type: "complete", completeness: "complete", strand: "-" }), method: "integronfinder", assembly_contig: "NC_028464.1", contig: "contig_1", start: 29_666, end: 32_156 };
  const calin: MobileMapElement = { ...integron, id: "i2", element: "integron_02", completeness: "CALIN", start: 1_000, end: 1_500 };
  const plasmid: MobileMapElement = { ...row({ id: "p", category: "plasmid_contig", element: "AD768", element_type: "plasmid" }), method: "mobsuite", assembly_contig: "NC_028464.1", contig: "contig_1", start: 1, end: 33_913 };

  it("enables the mobile ring, colours MOB-suite's plasmid contigs on the backbone and keeps VFDB off until it ran", async () => {
    vi.spyOn(api, "annotationMap").mockResolvedValue(map);
    vi.spyOn(api, "annotationAmr").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationVirulence").mockResolvedValue({ run: null, hits: [] });
    vi.spyOn(api, "annotationMobile").mockResolvedValue({
      runs: { mobsuite: { job_id: "job-mob", created_at: "", tool: "MOB-suite", tool_version: "3.1.9", database_version: "3.1.8", counts: {} }, integronfinder: { job_id: "job-if", created_at: "", tool: "IntegronFinder", tool_version: "2.0.6", database_version: null, counts: {} } },
      contigs: [{ contig: "contig_1", molecule_type: "plasmid", primary_cluster_id: "AD768", job_id: "job-mob" }],
      elements: [plasmid, integron, calin],
    });
    const { container } = renderWith(<CircularExplorer annotation={annotation} contigs={contigs} sampleCode="R388" selected={null} onSelect={() => {}} onShowLinear={() => {}} />);
    await waitFor(() => expect(container.querySelector('[data-ring="mobile"]')).not.toBeNull());
    expect(screen.getByLabelText(/^Mobile genetic elements/)).toBeEnabled();
    expect(screen.getByLabelText(/^Virulence factors \(VFDB\)/)).toBeDisabled();
    expect(screen.getByText(/3 elements from Plasmid reconstruction \(MOB-suite mob_recon\), Integrons \(IntegronFinder\)/)).toBeInTheDocument();
    expect(screen.getByText("Contigs MOB-suite called plasmid, coloured on the sequence ring: 1")).toBeInTheDocument();
    expect(container.querySelector("[data-plasmid] title")!.textContent).toContain("plasmid (MOB-suite)");
    const ring = container.querySelector('[data-ring="mobile"]')!;
    expect(ring.querySelectorAll("path")).toHaveLength(2); // the plasmid contig and the complete integron filled, the CALIN hollow
    expect(mobileFeatures([integron, calin]).map((f) => f.id)).toEqual([-200001, -200002]);
  });
});
