import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MlstDialog } from "@/components/genomic/MlstDialog";
import { MlstCard } from "@/components/genomic/MlstResult";
import { ProjectMlst } from "@/components/genomic/ProjectMlst";
import { ALL_NAV_ITEMS } from "@/components/layout/nav";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import { clonalComplexText, initialMlstForm, MLST_DEFAULT_EXCLUDE, mlstBody, mlstProblems, warningText } from "@/lib/mlst";
import type { AnalysisJob, Assembly, MlstPlan, MlstResult, MlstRow, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

// The calls are mlst 2.35.0's on the fixtures in workflows/tool-adapters/tests/fixtures/mlst: NC_007795.1 edited for
// the parser cases (a test construct, not biology).
const edited: MlstResult = {
  id: "mlst-1", sample_id: "s", assembly_id: "asm-00001", job_id: "job-mlst", tool: "mlst", tool_version: "2.35.0", database_key: "mlst-bundled",
  database_name: "PubMLST schemes bundled with mlst 2.35.0", database_version: "2026-03-11", database_checksum: "sha256:abc",
  parameters: { minid: 95, mincov: 50, minscore: 50, scheme: null, exclude: MLST_DEFAULT_EXCLUDE },
  scheme: "saureus", st: null, status: "MIXED", score: 66,
  alleles: [
    { locus: "arcC", call: "~3", type: "novel", alleles: [], similar_to: "3" },
    { locus: "aroE", call: "3", type: "exact", alleles: ["3"], similar_to: null },
    { locus: "gmk", call: "725?", type: "partial", alleles: [], similar_to: "725" },
    { locus: "tpi", call: "-", type: "missing", alleles: [], similar_to: null },
    { locus: "yqiL", call: "1,3", type: "multiple", alleles: ["1", "3"], similar_to: null },
  ],
  clonal_complex: { available: false, column: null, value: null, reason: "not_in_scheme" },
  warnings: [
    { code: "novel_alleles", params: { count: 1, loci: "arcC" } },
    { code: "partial_alleles", params: { count: 1, loci: "gmk" } },
    { code: "missing_alleles", params: { count: 1, loci: "tpi" } },
    { code: "multiple_alleles", params: { count: 1, loci: "yqiL" } },
    { code: "st_not_assigned", params: {} },
  ],
  details: { scheme: { name: "saureus", loci: ["arcC"], source: "pubmlst", download_date: "2026-03-11", last_updated: "2026-03-10", clonal_complex: false } },
  files: { tsv: { path: "r/mlst.tsv", sha256: "x", size_bytes: 1 }, novel: { path: "r/novel_alleles.fasta", sha256: "x", size_bytes: 1 } },
  created_at: "2026-10-29T15:00:00Z",
};

const draft = {
  id: "asm-00001", sample_id: "s", job_id: "job-flye", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3",
  mode: "long", read_type: "nano-hq", input_file_ids: [], created_at: "2026-10-28T13:00:00Z",
  stats: { contig_count: 1, total_length: 2_821_361, circularity: { contigs_with_circularity: 1, circular_contigs: 1 } }, warnings: [],
} as unknown as Assembly;

const plan: MlstPlan = {
  tool: { status: "available", version: "2.35.0", version_validated: true, message: "", reason: null, path: "/env/bin/mlst", license: "GPL-2.0",
    citation: "Seemann T. mlst", citation_url: "https://doi.org/10.12688/wellcomeopenres.14826.1", max_threads: 4, default_threads: 4 },
  database: { id: "db-mlst", name: "PubMLST schemes bundled with mlst 2.35.0", version: "2026-03-11", checksum: "sha256:abc", path: "/env/db",
    version_txt: "2025-12-29", download_dates: ["2026-03-11"], blast_last_updated: "2026-03-11T12:33:00", scheme_count: 162,
    sources: { pubmlst: 153, pasteur: 9 }, authenticated: ["False"], updated_after_open_terms: ["saureus"], without_update_date: [],
    terms: { open_until: "2024-12-31", url: "https://pubmlst.org/terms-conditions", updated: "2026-05-13" } },
  schemes: [{ name: "saureus", loci: ["arcC", "aroE", "glpF", "gmk", "pta", "tpi", "yqiL"], source: "pubmlst", download_date: "2026-03-11", last_updated: "2026-03-10", clonal_complex: false }],
  defaults: { minid: "95", mincov: "50", minscore: "50", threads: "1", exclude: MLST_DEFAULT_EXCLUDE.join(",") },
  tool_defaults: { minid: "95", mincov: "50", minscore: "50", threads: "1", exclude: MLST_DEFAULT_EXCLUDE.join(",") },
  defaults_match: true,
  assembly: { assembly_id: "asm-00001", kind: "assembly", assembler: "Flye", assembler_version: "2.9.3", parent_assembly_id: null, contigs: 1, total_length: 2_821_361, synthetic_evidence: [] },
  scheme: null,
  problems: [],
};

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useSettings.setState({ language: "en" });
  vi.spyOn(api, "tools").mockResolvedValue([{ id: "mlst", name: "mlst", status: "available" } as Tool]);
});
afterEach(() => vi.restoreAllMocks());

describe("MLST helpers", () => {
  const t = (k: string, v?: Record<string, string | number>) => {
    let s = (dictionaries.en as Record<string, string>)[k];
    for (const [name, value] of Object.entries(v ?? {})) s = s.replace(`{${name}}`, String(value));
    return s;
  };
  it("says why there is no clonal complex instead of leaving it blank", () => {
    expect(clonalComplexText(t as never, edited.clonal_complex)).toBe("Not available from the scheme");
    expect(clonalComplexText(t as never, { available: true, column: "clonal_complex", value: "ST10 Cplx", reason: null })).toBe("ST10 Cplx");
    expect(clonalComplexText(t as never, { available: true, column: "clonal_complex", value: null, reason: "no_st" })).toBe("Not determined (no ST)");
    expect(clonalComplexText(t as never, { available: false, column: null, value: null, reason: "no_scheme" })).toBe("Not determined");
  });

  it("sends mlst's defaults explicitly, and minimum score 0 without exclusions for a chosen scheme", () => {
    const form = { ...initialMlstForm("asm-00001"), confirmed: true };
    expect(mlstBody(form)).toEqual({ settings: { scheme: null, minid: 95, mincov: 50, minscore: 50, exclude: MLST_DEFAULT_EXCLUDE }, threads: null, confirmed: true });
    expect(mlstBody({ ...form, scheme: "saureus", minscore: "70" }).settings).toEqual({ scheme: "saureus", minid: 95, mincov: 50, minscore: 0, exclude: [] });
    expect(mlstBody({ ...form, excludeDefaults: false }).settings.exclude).toEqual([]);
    expect(mlstProblems({ ...form, minid: "0" }, plan)).toEqual(["mlst.problem.minid"]);
    expect(mlstProblems({ ...form, confirmed: false }, plan)).toEqual(["mlst.problem.confirm"]);
  });

  it("has a text in both languages for every warning code and bilingual Guide entries", () => {
    for (const code of ["no_scheme", "novel_alleles", "partial_alleles", "missing_alleles", "multiple_alleles", "null_alleles", "unrecognised_alleles",
      "st_not_assigned", "tied_schemes", "scheme_forced", "scheme_after_open_terms", "synthetic_input"]) {
      expect(dictionaries.en).toHaveProperty(`mlst.warning.${code}`);
      expect(dictionaries.es).toHaveProperty(`mlst.warning.${code}`);
    }
    expect(warningText(((k: string) => k) as never, { code: "something_new", params: {} })).toBe("something_new");
    for (const id of ["mlst", "sequence_type", "novel_allele"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.title).not.toBe(GUIDE_BY_ID[id].en.title);
    }
  });

  it("keeps the sidebar's P5 entry and points it at the genomic-analysis overview", () => {
    const genomic = ALL_NAV_ITEMS.find((i) => i.key === "genomic")!;
    expect(genomic.to).toBe("/genomic");
    expect(genomic.plannedPhase).toBe(5);
  });
});

describe("MLST result", () => {
  it("shows every call with its type, the warnings and no ST for an incomplete profile", () => {
    renderWith(<MlstCard result={edited} />);
    expect(screen.getAllByText("ST not assigned").length).toBeGreaterThan(0);
    const table = screen.getByRole("table");
    expect(within(table).getByText("~3")).toBeInTheDocument();
    expect(within(table).getByText("novel allele (~)")).toBeInTheDocument();
    expect(within(table).getByText("partial match (?)")).toBeInTheDocument();
    expect(within(table).getByText("not found (-)")).toBeInTheDocument();
    expect(within(table).getByText("several exact alleles")).toBeInTheDocument();
    expect(within(table).getAllByText(/not necessarily the closest/).length).toBe(2);
    const warnings = screen.getByRole("status");
    expect(within(warnings).getByText(/1 locus is only partly matched/)).toBeInTheDocument();
    expect(within(warnings).getByText(/ST not assigned\./)).toBeInTheDocument();
    expect(screen.getByText("Not available from the scheme")).toBeInTheDocument();
    expect(screen.getByText(/31 December 2024/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Novel alleles \(FASTA\)/ })).toHaveAttribute("href", "/api/v1/mlst/mlst-1/files/novel");
  });

  it("is shown in Spanish", () => {
    useSettings.setState({ language: "es" });
    renderWith(<MlstCard result={edited} />);
    expect(screen.getAllByText("ST no asignado").length).toBeGreaterThan(0);
    expect(screen.getByText("No disponible en el esquema")).toBeInTheDocument();
    expect(screen.getByText("alelo nuevo (~)")).toBeInTheDocument();
  });
});

describe("MLST dialog", () => {
  it("shows the bundled schemes' date and terms and sends the confirmed options", async () => {
    const preview = vi.spyOn(api, "mlstPreview").mockResolvedValue(plan);
    const run = vi.spyOn(api, "runMlst").mockResolvedValue({ id: "job-mlst" } as AnalysisJob);
    renderWith(<MlstDialog open onOpenChange={() => {}} sampleId="s" assemblies={[draft]} />);
    await waitFor(() => expect(preview).toHaveBeenCalledWith("asm-00001", null));
    expect(await screen.findByText(/162 schemes downloaded 2026-03-11/)).toBeInTheDocument();
    expect(screen.getByText(/Schemes last updated after 2024-12-31: 1 of 162/)).toBeInTheDocument();
    const start = screen.getByRole("button", { name: "Run mlst" });
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I have read the summary/ }));
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0]).toEqual(["asm-00001", { settings: { scheme: null, minid: 95, mincov: 50, minscore: 50, exclude: MLST_DEFAULT_EXCLUDE }, threads: null, confirmed: true }]);
  });
});

describe("Project MLST overview", () => {
  it("lists every sample, typed or not, and the STs found", async () => {
    const row: MlstRow = { ...edited, sample_code: "SA-1", project_id: "p", project_name: "P", is_demo: false, assembler: "Flye", assembler_version: "2.9.3",
      assembly_kind: "assembly", scheme: "saureus", st: "8", status: "PERFECT", score: 100, warnings: [] };
    vi.spyOn(api, "mlstProject").mockResolvedValue({
      project_id: "p", project_name: "P", is_demo: false,
      samples: [{ sample_id: "s1", sample_code: "SA-1", results: 1, latest: row }, { sample_id: "s2", sample_code: "SA-2", results: 0, latest: null }],
      sequence_types: [{ scheme: "saureus", st: "8", samples: 1 }],
    });
    // FastANI 1.34's real reading for this genome (workflows/tool-adapters/tests/fixtures/species, case saureus).
    vi.spyOn(api, "speciesProject").mockResolvedValue({
      project_id: "p", project_name: "P", is_demo: false, species: [{ status: "same_species", species: "Staphylococcus aureus", samples: 1 }],
      samples: [
        { sample_id: "s1", sample_code: "SA-1", results: 1, latest: { ...row, method: "fastani", tool: "FastANI", tool_version: "1.34", status: "same_species",
          species: "Staphylococcus aureus", best: null, runner_up: null, reasons: [], consistency: [{ source: "mlst", outcome: "agree", reason: null, params: {} }] } },
        { sample_id: "s2", sample_code: "SA-2", results: 0, latest: null },
      ],
    });
    renderWith(<ProjectMlst projectId="p" />);
    expect(await screen.findByText("Genomic analysis: 1 of 2 samples with a species identification, 1 typed by MLST")).toBeInTheDocument();
    expect(screen.getByText("Staphylococcus aureus")).toBeInTheDocument();
    expect(screen.getByText("not identified")).toBeInTheDocument();
    expect(screen.getByText("No MLST result")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SA-1" })).toHaveAttribute("href", "/samples/s1?tab=genomic");
    expect(screen.getByText(/saureus · ST 8 · 1 sample/)).toBeInTheDocument();
  });
});
