import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnnotationDialog } from "@/components/annotation/AnnotationDialog";
import { AnnotationCard } from "@/components/annotation/AnnotationResult";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { annotationProblems, assemblyOptions, baktaBody, initialForm, safeExternalUrl, stepReason, stepState } from "@/lib/annotation";
import { api } from "@/lib/api";
import type { AnalysisJob, Annotation, AnnotationFeature, AnnotationFeatureDetail, AnnotationPlan, AnnotationStep, Assembly, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" data-option={JSON.stringify(props.option)} />;
  }),
}));

// Shapes follow ARVA's records of a real Bakta 1.12.2 run (light database 6.0) on the SYNTHETIC test genome
// (workflows/tool-adapters/tests/fixtures/annotation_genome): not biology.
const stats = { contig_count: 2, total_length: 18_960, circularity: { contigs_with_circularity: 2, circular_contigs: 2 } } as unknown as Assembly["stats"];
const draft = {
  id: "draft-0001", sample_id: "s", job_id: "job-flye", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3",
  mode: "long", read_type: "nano-hq", input_file_ids: [], created_at: "2026-10-28T13:00:00Z", stats, warnings: [],
} as unknown as Assembly;
const polished = { ...draft, id: "racon-0002", job_id: "job-racon", kind: "polished", parent_assembly_id: "draft-0001", assembler: "Racon", assembler_version: "1.5.0", created_at: "2026-10-28T14:00:00Z" } as Assembly;

const missingAmr = { name: "AMRFinderPlus", status: "missing", found: null, minimum: "4.2.7", steps: ["cds"] };
const oldDiamond = { name: "DIAMOND", status: "too_old", found: "2.1.9", minimum: "2.2.0", steps: ["cds", "sorf"] };
const step = (run: boolean, extra: Partial<AnnotationStep> = {}): AnnotationStep => ({ run, reason: run ? null : "dependency", dependencies: [], ...extra });
const plannedSteps: Record<string, AnnotationStep> = {
  trna: step(true),
  rrna: step(true),
  crispr: step(false, { dependencies: [{ name: "PILER-CR", status: "crashed", returncode: -11 }] }),
  cds: step(false, { dependencies: [missingAmr, oldDiamond] }),
  pseudo: step(false, { reason: "needs_cds" }),
};

const plan: AnnotationPlan = {
  annotator: "bakta",
  tool: {
    status: "available", version: "1.12.2", version_validated: true, message: "", reason: "bakta_steps_skipped", path: "/root/.arva-tools/bakta/bin/bakta",
    license: "GPL-3.0", citation: "Schwengers O et al. 2021", citation_url: "https://doi.org/10.1099/mgen.0.000685", max_threads: 4, default_threads: 4,
  },
  steps: plannedSteps,
  assembly: {
    assembly_id: "racon-0002", kind: "polished", assembler: "Racon", assembler_version: "1.5.0", parent_assembly_id: "draft-0001", job_id: "job-racon",
    contigs_sha256: "x", created_at: "2026-10-28T14:00:00Z", contigs: 2, total_length: 18_960, circular_contigs: 2, contigs_with_circularity: 2,
    all_circular: true, longest_contig_name: 9, prokka_name_problem: null, descriptions: 2, synthetic_evidence: ["contig description says SYNTHETIC"],
  },
  suggestions: { locus_tag: "ANN1", complete: true, translation_table: 11 },
  translation_tables: [11, 4, 25],
  problems: [],
  dependencies: [missingAmr, oldDiamond],
  skip_options: ["--skip-crispr", "--skip-cds", "--skip-pseudo"],
  databases: [{ id: "db-1", key: "bakta-light", name: "Bakta database (light)", version: "6.0", type: "light", status: "installed", usable: true, checksum: "sha256:93a7", verified_at: null, path: "/db" }],
  database_id: "db-1",
  database: null,
  programs: {},
};

const annotation: Annotation = {
  id: "ann-1", sample_id: "s", assembly_id: "racon-0002", job_id: "job-bakta", tool: "Bakta", tool_version: "1.12.2", database_key: "bakta-light",
  database_name: "Bakta database (light)", database_version: "6.0", database_checksum: "sha256:93a7", parameters: { locus_tag: "ANN1", assembly: { assembler: "Racon", assembler_version: "1.5.0", kind: "polished" } },
  steps: {
    trna: { ...plannedSteps.trna, status: "searched", found: 2 },
    rrna: { ...plannedSteps.rrna, status: "searched", found: 0 },
    crispr: { ...step(true), status: "failed", reason: "crashed", returncode: 139, found: null },
    cds: { ...plannedSteps.cds, status: "skipped" },
  },
  summary: {
    counts: { trna: 2, gap: 1 }, features: 3, cds: null, hypothetical: null, characterised: null, hypothetical_fraction: null, pseudogenes: 0, partial: 0,
    with_ec: 0, with_cog: 0, with_go: 0, with_gene: 0, cog_categories: {},
    coding_density: { value: null, cds_bases: null, non_n_bases: 18_860, definition: "" }, sequences: 2, total_length: 18_960,
    tool_reported: {}, input: { sha256: "x", non_n_bases: 18_860, total_length: 18_960, renamed: false }, synthetic_evidence: ["contig description says SYNTHETIC"],
  },
  sequences: [{ id: "contig_1", original_id: "chromosome", length: 15_000 }],
  files: { gff3: { path: "a.gff3", sha256: "x", size_bytes: 1000 }, ffn: { path: "a.ffn", sha256: "x", size_bytes: 500 } },
  created_at: "2026-10-28T15:00:00Z",
};

const hostile = '<img src=x onerror="alert(1)">';
const feature: AnnotationFeature = {
  id: 7, tool_id: "ABCDEF_1", locus_tag: "ANN1_00005", type: "trna", tool_type: "tRNA", contig: "contig_1", contig_in_assembly: "chromosome", start: 1200,
  end: 1275, strand: "+", length: 76, edge: false, gene: null, product: hostile, ec: [], cog: [], cog_categories: [], go: [], db_xrefs: ["SO:0000253"],
  pseudo: false, partial: null, hypothetical: null, inference: ["profile:tRNAscan:2.0"], accessions: [],
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
  vi.spyOn(api, "tools").mockResolvedValue([{ id: "bakta", name: "Bakta", status: "available" } as Tool]);
});
afterEach(() => vi.restoreAllMocks());

describe("annotation helpers", () => {
  it("orders assemblies by lineage, each draft followed by what was polished from it", () => {
    expect(assemblyOptions([polished, draft]).map((o) => [o.assembly.id, o.depth])).toEqual([["draft-0001", 0], ["racon-0002", 1]]);
  });

  it("blocks the run until the form is valid and confirmed", () => {
    const form = { ...initialForm("racon-0002"), locusTag: "ann" };
    expect(annotationProblems(form, plan)).toEqual(expect.arrayContaining(["annotation.problem.locusTag", "annotation.problem.confirm"]));
    expect(annotationProblems({ ...form, locusTag: "ANN1", species: "coli", confirmed: true }, plan)).toEqual(["annotation.problem.speciesNeedsGenus"]);
    expect(annotationProblems({ ...form, locusTag: "ANN1", complete: true, confirmed: true }, plan)).toEqual(["annotation.problem.complete"]);
    expect(annotationProblems({ ...form, locusTag: "ANN1", threads: "8", confirmed: true }, plan)).toEqual(["annotation.problem.threads"]);
    expect(annotationProblems({ ...form, annotator: "prokka", locusTag: "ANN1", evalue: "0", confirmed: true }, plan)).toEqual(["annotation.problem.evalue"]);
    expect(annotationProblems({ ...form, locusTag: "ANN1", confirmed: true }, plan)).toEqual([]);
  });

  it("sends the plan's skip options and --complete only when it was confirmed", () => {
    const body = baktaBody({ ...initialForm("racon-0002"), locusTag: "ANN1", completeConfirmed: true, confirmed: true }, plan);
    expect(body).toMatchObject({ database_id: "db-1", skip_options: plan.skip_options, complete_confirmed: false, threads: null });
    expect(body.settings).toMatchObject({ complete: false, genus: null, translation_table: 11, min_contig_length: 1 });
    expect(baktaBody({ ...initialForm("x"), locusTag: "ANN1", complete: true, completeConfirmed: true, confirmed: true }, plan).complete_confirmed).toBe(true);
  });

  it("explains skipped steps with the program, version found and version needed", () => {
    const t = (key: string, vars?: Record<string, string | number>) =>
      (dictionaries.en as Record<string, string>)[key].replace(/\{(\w+)\}/g, (_, k: string) => String(vars?.[k] ?? `{${k}}`));
    expect(stepReason(t, plannedSteps.cds)).toBe("AMRFinderPlus is not installed; DIAMOND 2.1.9 is older than 2.2.0");
    expect(stepReason(t, plannedSteps.pseudo)).toBe("needs the CDS step");
    expect(stepState(plannedSteps.cds)).toBe("skipped");
    expect(stepState(annotation.steps.crispr)).toBe("failed");
  });

  it("renders only https links", () => {
    expect(safeExternalUrl("https://www.ncbi.nlm.nih.gov/research/cog/cog/COG0001/")).toBe("https://www.ncbi.nlm.nih.gov/research/cog/cog/COG0001/");
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("http://example.org/")).toBeNull();
    expect(safeExternalUrl("not a url")).toBeNull();
  });

  it("has bilingual Guide entries for every annotation term the screens explain", () => {
    for (const id of ["annotation", "bakta", "prokka", "hypothetical_proteins", "cds", "trna_rrna", "cog", "genome_explorer", "gc_skew"] as const) {
      expect(GUIDE_BY_ID[id].es.title.length).toBeGreaterThan(0);
    }
  });
});

describe("Annotation results", () => {
  beforeEach(() => {
    vi.spyOn(api, "annotationFeatures").mockResolvedValue({ total: 1, limit: 50, offset: 0, max_limit: 1000, items: [feature] });
  });

  it("shows steps that did not run as not searched, never as zero", async () => {
    renderWith(<AnnotationCard annotation={annotation} />);
    const tile = (label: string) => screen.getAllByText(label)[0].closest("div")!.parentElement!;
    expect(within(tile("CDS")).getByText("not searched")).toBeInTheDocument();
    expect(within(tile("Coding density")).getByText("not searched")).toBeInTheDocument();
    expect(within(tile("tRNA")).getByText("2")).toBeInTheDocument();
    expect(within(tile("rRNA")).getByText("0")).toBeInTheDocument();
    const steps = screen.getByRole("region", { name: "Steps" });
    expect(within(steps).getByText(/Not searched: AMRFinderPlus is not installed; DIAMOND 2.1.9 is older than 2.2.0/)).toBeInTheDocument();
    expect(within(steps).getByText(/Search failed: the program crashed during the run \(exit status 139\)/)).toBeInTheDocument();
    expect(screen.getByText(/SYNTHETIC/)).toBeInTheDocument();
  });

  it("shows product names from databases as text and links only https identifiers", async () => {
    const detail: AnnotationFeatureDetail = {
      ...feature,
      links: [{ xref: "SO:0000253", url: "https://identifiers.org/SO:0000253" }, { xref: "BAD:1", url: "javascript:alert(1)" }],
      nucleotide: { source: "annotation.ffn", header: "ANN1_00005", length: 76, sequence: "GCGGAT", truncated: false },
      protein: null,
      checks: { nucleotide: { status: "match", reason: null }, protein: { table: 11, status: "not_checked", reason: "not_coding", first_difference: null } },
    };
    vi.spyOn(api, "annotationFeature").mockResolvedValue(detail);
    const { container } = renderWith(<AnnotationCard annotation={annotation} />);
    const cell = await screen.findByText(hostile);
    expect(container.querySelector("img[onerror]")).toBeNull();
    fireEvent.click(cell);
    const region = await screen.findByRole("region", { name: "Feature detail" });
    await within(region).findByText("GCGGAT");
    const link = within(region).getByRole("link", { name: /SO:0000253/ });
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
    expect(within(region).queryByRole("link", { name: /BAD:1/ })).toBeNull();
  });
});

describe("Annotation dialog", () => {
  it("lists what will not be searched and sends Bakta the plan's skip options after confirmation", async () => {
    const preview = vi.spyOn(api, "baktaPreview").mockResolvedValue(plan);
    const run = vi.spyOn(api, "runBakta").mockResolvedValue({ id: "job-bakta" } as AnalysisJob);
    renderWith(<AnnotationDialog open onOpenChange={() => {}} sampleId="s" assemblies={[draft, polished]} />);
    await waitFor(() => expect(preview).toHaveBeenCalledWith("racon-0002", { database_id: null, skip_plot: false }));
    expect(await screen.findByText(/AMRFinderPlus is not installed; DIAMOND 2.1.9 is older than 2.2.0/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByDisplayValue("ANN1")).toBeInTheDocument());
    const start = screen.getByRole("button", { name: "Annotate" });
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I have read what this run will and will not search/ }));
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    const [assemblyId, body] = run.mock.calls[0];
    expect(assemblyId).toBe("racon-0002");
    expect(body).toMatchObject({ database_id: "db-1", skip_options: ["--skip-crispr", "--skip-cds", "--skip-pseudo"], complete_confirmed: false, confirmed: true });
    expect(body.settings).toMatchObject({ locus_tag: "ANN1", complete: false, translation_table: 11 });
  });

  it("lets the user choose another Bakta database version and sends that one", async () => {
    const two: AnnotationPlan = {
      ...plan,
      databases: [
        { ...plan.databases[0], is_default: true, version_source: "file", verification_level: "full", host_path: "/Volumes/JM/BioInf/bakta/db-light" },
        { id: "db-2", key: "bakta-full", name: "Bakta database (full)", version: "6.0", type: "full", status: "registered", usable: true, is_default: false,
          version_source: "file", verification_level: "quick", checksum: null, verified_at: null, path: "/databases-external/1/db", host_path: "/Volumes/JM/BioInf/bakta/db" },
      ],
    };
    const preview = vi.spyOn(api, "baktaPreview").mockImplementation(async (_id, body) => ({ ...two, database_id: body.database_id ?? "db-1" }));
    const run = vi.spyOn(api, "runBakta").mockResolvedValue({ id: "job-bakta" } as AnalysisJob);
    renderWith(<AnnotationDialog open onOpenChange={() => {}} sampleId="s" assemblies={[draft, polished]} />);
    const select = await screen.findByRole("combobox", { name: "Database" });
    expect(within(select).getByRole("option", { name: /Bakta database \(light\) 6\.0 \(light\) · default/ })).toBeInTheDocument();
    expect(await screen.findByText(/Version 6\.0 \(version read from the database's files\) · full checksum recorded/)).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "db-2" } });
    await waitFor(() => expect(preview).toHaveBeenLastCalledWith("racon-0002", { database_id: "db-2", skip_plot: false }));
    expect(await screen.findByText(/quick check only/)).toBeInTheDocument();
    expect(screen.getByText("/Volumes/JM/BioInf/bakta/db")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByDisplayValue("ANN1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("checkbox", { name: /I have read what this run will and will not search/ }));
    fireEvent.click(screen.getByRole("button", { name: "Annotate" }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][1]).toMatchObject({ database_id: "db-2" });
  });
});
