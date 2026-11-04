import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { ImportGenomeDialog } from "@/components/assembly/ImportGenomeDialog";
import { DatabaseNote, MlstDialog } from "@/components/genomic/MlstDialog";
import { translator } from "@/i18n";
import { api } from "@/lib/api";
import { assemblerName, assemblerText, assemblyLabel, assemblyOptionLabel, canPolish } from "@/lib/assembly";
import { mlstDatabaseName } from "@/lib/mlst";
import { referenceLabel, type ReferenceAssemblyOption } from "@/lib/variants";
import type { AnalysisJob, Assembly, AssemblyDetail, MlstPlan, RawFile } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown }>(function Stub(_props, ref) {
    return <div ref={ref} data-testid="chart" />;
  }),
}));

// A genome FASTA registered with "Register a genome FASTA": the API names its assembler "Imported genome", records the
// source the user stated as its version and "none" as its read type (apps/api/app/tasks/tools.py).
const stats = {
  contig_count: 2, total_length: 2_870_000, largest_contig: 2_800_000, smallest_contig: 70_000, n50: 2_800_000, l50: 1, n90: 2_800_000, l90: 1,
  gc_percent: 32.8, n_count: 0, n_per_100kb: 0, length_histogram: [], cumulative: null,
  circularity: { contigs_with_circularity: 0, circular_contigs: 0 },
  coverage: { contigs_with_coverage: 0, length_weighted_median: null },
  contig_rows: { stored: 2, total: 2, truncated: false },
  expected_genome_size: { bp: null, status: "not_given", source: null },
  warning_checks: [
    { code: "many_contigs", rule: "", evaluated: false, skipped_reason: "imported genome: the reads it was assembled from are not known" },
    { code: "low_coverage_contigs", rule: "", evaluated: false, skipped_reason: "the assembler reported coverage for fewer than two contigs" },
  ],
  files: { contigs: { path: "c", sha256: "x", size_bytes: 1 }, graph: null, info: null },
} as unknown as Assembly["stats"];
const imported: Assembly = {
  id: "imp00001-0000", sample_id: "s", job_id: "job-imp", kind: "assembly", parent_assembly_id: null, assembler: "Imported genome",
  assembler_version: "Own pipeline v1", mode: "imported", read_type: "none", coverage_kind: null, declared_assembler: null, declared_assembler_version: null,
  input_file_ids: ["fa"], created_at: "2026-11-01T10:00:00Z", stats, warnings: [],
};
const declared: Assembly = { ...imported, id: "drf00001-0000", job_id: "job-drf", declared_assembler: "Flye", declared_assembler_version: "2.9.6" };
const polishedFromDeclared: Assembly = {
  ...imported, id: "pol00001-0000", job_id: "job-pol", kind: "polished", parent_assembly_id: declared.id, assembler: "Medaka", assembler_version: "2.1.1",
  read_type: "map-ont", coverage_kind: "mapped_read_depth", declared_assembler: null, declared_assembler_version: null,
};
const flye: Assembly = { ...imported, id: "fly00001-0000", job_id: "job-fly", assembler: "Flye", assembler_version: "2.9.6", mode: "long", read_type: "nano-hq" };
const fasta = { id: "fa", original_filename: "consensus.fasta", file_format: "fasta", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null,
  produced_by_job_id: null, size_bytes: 2_900_000, checksum_sha256: "ab".repeat(32) } as unknown as RawFile;

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function card(a: Assembly, all: Assembly[] = [a]) {
  vi.spyOn(api, "assemblies").mockResolvedValue(all);
  vi.spyOn(api, "assembly").mockResolvedValue({ ...a, contigs: [] } as AssemblyDetail);
  vi.spyOn(api, "tools").mockResolvedValue([]);
  renderWith(<AssemblyTab sampleId="s" jobs={[]} files={[fasta]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("registered genome names", () => {
  const en = translator("en");
  const es = translator("es");

  it("never shows the API's English assembler name or 'none' read type, in either language", () => {
    expect(assemblerName(es, imported)).toBe("Genoma importado");
    expect(assemblerName(es, declared)).toBe("Flye (fuera de ARVA)");
    expect(assemblerName(es, polishedFromDeclared)).toBe("Medaka");
    expect(assemblerText(es, "Imported genome", "Own pipeline v1")).toBe("Genoma importado · Own pipeline v1");
    expect(assemblerText(es, "Flye", "2.9.6")).toBe("Flye 2.9.6");
    expect(assemblyLabel(en, declared)).toBe("Draft assembled outside ARVA (Flye 2.9.6) · Own pipeline v1 · drf00001");
    expect(assemblyLabel(en, flye)).toBe("Flye 2.9.6 · nano-hq · fly00001");
    const option = assemblyOptionLabel(es, imported);
    expect(option.startsWith("Genoma importado · Own pipeline v1 · contigs: 2 · ")).toBe(true);
    expect(option).not.toMatch(/Imported genome|none/);
    expect(assemblyOptionLabel(en, polishedFromDeclared).startsWith("Medaka 2.1.1 · polished · 2 contigs · ")).toBe(true);
    expect(assemblyOptionLabel(en, flye).startsWith("Flye 2.9.6 · nano-hq · 2 contigs · ")).toBe(true);
  });

  it("polishes ARVA's assemblies and declared drafts, never a genome registered as finished", () => {
    expect([flye, imported, declared, polishedFromDeclared].map(canPolish)).toEqual([true, false, true, true]);
  });

  it("names the variant reference and the bundled MLST schemes in the interface language", () => {
    const row = { assembly_id: "imp00001-0000", label: "S27 · Imported genome", sample_code: "S27", same_project: true, own_sample: false, kind: "assembly",
      assembler: "Imported genome", assembler_version: "Own", mode: "imported", declared_assembler: null, contigs: 2, total_length: 1, annotation: null } as ReferenceAssemblyOption;
    expect(referenceLabel(es, row)).toBe("S27 · Genoma importado");
    expect(referenceLabel(es, { ...row, declared_assembler: "Flye" })).toBe("S27 · Flye (fuera de ARVA)");
    expect(referenceLabel(es, { ...row, kind: "polished", assembler: "Medaka", mode: "imported" })).toBe("S27 · Medaka (pulido)");
    expect(referenceLabel(es, { ...row, mode: undefined })).toBe("S27 · Imported genome");
    expect(mlstDatabaseName(es, "PubMLST schemes bundled with mlst 2.35.0")).toBe("Esquemas de PubMLST incluidos en mlst 2.35.0");
    expect(mlstDatabaseName(en, "PubMLST schemes bundled with mlst 2.35.0")).toBe("PubMLST schemes bundled with mlst 2.35.0");
    expect(mlstDatabaseName(es, "My schemes")).toBe("My schemes");
  });
});

describe("Registered genome card", () => {
  it("labels the genome FASTA, translates every check and says coverage and circularity are not known (Spanish)", async () => {
    useSettings.setState({ language: "es" });
    card(imported);
    expect(await screen.findByText("Genoma importado · Own pipeline v1")).toBeInTheDocument();
    expect(screen.getByText("FASTA del genoma: consensus.fasta", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/Lecturas: consensus\.fasta/)).not.toBeInTheDocument();
    expect(screen.getAllByText("no se conoce en un genoma registrado")).toHaveLength(2);
    expect(screen.getByText(/genoma registrado: ARVA no registra con qué lecturas, ni de qué tipo, se ensambló/)).toBeInTheDocument();
    expect(screen.getByText(/FASTA de genoma que registraste: ARVA no lo ensambló/)).toBeInTheDocument();
    expect(await screen.findByText(/La cobertura y la circularidad no se conocen/)).toBeInTheDocument();
    expect(screen.queryByText(/assembly_info\.txt;/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Imported genome|imported genome:/);
    expect(screen.queryByRole("button", { name: "Pulir" })).not.toBeInTheDocument();
  });

  it("states that a declared draft was assembled outside ARVA and offers to polish it", async () => {
    card(declared);
    expect(await screen.findByText("Draft assembled outside ARVA · Flye 2.9.6 · Own pipeline v1")).toBeInTheDocument();
    expect(screen.getByText(/Draft assembled outside ARVA with Flye 2.9.6 from this sample's reads, as declared by the user/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Polish" })).toBeInTheDocument();
  });

  it("keeps the declared provenance on the polished version and names the lineage in the interface language", async () => {
    useSettings.setState({ language: "es" });
    card(polishedFromDeclared, [declared, polishedFromDeclared]);
    expect(await screen.findByText("Pulido a partir de un borrador ensamblado fuera de ARVA con Flye 2.9.6, según declaró el usuario.")).toBeInTheDocument();
    expect(screen.getByText(/Pulido a partir de Borrador ensamblado fuera de ARVA \(Flye 2\.9\.6\) · Own pipeline v1 · drf00001/)).toBeInTheDocument();
  });
});

describe("Register a genome FASTA", () => {
  it("sends the draft declaration only when it is ticked, with the assembler and version, after confirmation", async () => {
    const register = vi.spyOn(api, "importAssembly").mockResolvedValue({ id: "j" } as AnalysisJob);
    renderWith(<ImportGenomeDialog open onOpenChange={() => undefined} sampleId="s" files={[fasta]} />);
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "Own pipeline v1" } });
    fireEvent.click(screen.getByLabelText(/This is a draft I assembled outside ARVA/));
    const run = screen.getByRole("button", { name: "Register" });
    fireEvent.click(screen.getByLabelText(/I confirm that this file is a draft/));
    expect(run).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Assembler"), { target: { value: "Flye" } });
    fireEvent.change(screen.getByLabelText("Assembler version"), { target: { value: "2.9.6" } });
    expect(run).toBeEnabled();
    fireEvent.click(run);
    await waitFor(() =>
      expect(register).toHaveBeenCalledWith("s", { raw_file_id: "fa", source: "Own pipeline v1", draft: { from_this_sample_reads: true, assembler: "Flye", assembler_version: "2.9.6" } }),
    );
  });

  it("registers a finished genome without a declaration and says it will not be polished", async () => {
    const register = vi.spyOn(api, "importAssembly").mockResolvedValue({ id: "j" } as AnalysisJob);
    renderWith(<ImportGenomeDialog open onOpenChange={() => undefined} sampleId="s" files={[fasta]} />);
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "NCBI RefSeq GCF_000013465.1" } });
    fireEvent.click(screen.getByLabelText(/and will not polish it/));
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(register).toHaveBeenCalledWith("s", { raw_file_id: "fa", source: "NCBI RefSeq GCF_000013465.1" }));
  });
});

describe("MLST dialog with a registered genome (Spanish)", () => {
  it("translates the assembly option and the bundled-database title", async () => {
    useSettings.setState({ language: "es" });
    const plan = {
      tool: { status: "available", version: "2.35.0", version_validated: true, message: "", reason: null, path: "/env/bin/mlst", license: "GPL-2.0",
        citation: "Seemann T. mlst", citation_url: "https://doi.org/10.12688/wellcomeopenres.14826.1", max_threads: 4, default_threads: 4 },
      database: { id: "db-mlst", name: "PubMLST schemes bundled with mlst 2.35.0", version: "2026-03-11", checksum: "sha256:abc", path: "/env/db",
        version_txt: "2025-12-29", download_dates: ["2026-03-11"], blast_last_updated: "2026-03-11T12:33:00", scheme_count: 162, sources: { pubmlst: 153 },
        authenticated: ["False"], updated_after_open_terms: [], without_update_date: [], terms: { open_until: "2024-12-31", url: "https://pubmlst.org/terms-conditions", updated: "2026-05-13" } },
      schemes: [], defaults: { minid: "95", mincov: "50", minscore: "50", threads: "1", exclude: "" }, tool_defaults: { minid: "95", mincov: "50", minscore: "50", threads: "1", exclude: "" }, defaults_match: true,
      assembly: { assembly_id: imported.id, kind: "assembly", assembler: "Imported genome", assembler_version: "Own pipeline v1", parent_assembly_id: null, contigs: 2,
        total_length: 2_870_000, synthetic_evidence: [] },
      scheme: null, problems: [],
    } as unknown as MlstPlan;
    vi.spyOn(api, "mlstPreview").mockResolvedValue(plan);
    renderWith(<MlstDialog open onOpenChange={() => undefined} sampleId="s" assemblies={[imported]} />);
    expect(await screen.findByText("Esquemas de PubMLST incluidos en mlst 2.35.0")).toBeInTheDocument();
    const option = screen.getByRole("option", { name: /^Genoma importado/ });
    expect(option.textContent).toMatch(/^Genoma importado · Own pipeline v1 · contigs: 2 · /);
    expect(document.body.textContent).not.toMatch(/Imported genome|· none ·|PubMLST schemes bundled/);
  });

  it("shows any other database name as recorded", () => {
    renderWith(<DatabaseNote plan={{ database: { name: "Custom schemes", scheme_count: 1, version: "x", version_txt: null, blast_last_updated: null, terms: { open_until: "2024-12-31", url: "https://pubmlst.org", updated: "" }, updated_after_open_terms: [] } as unknown as MlstPlan["database"] }} />);
    expect(screen.getByText("Custom schemes")).toBeInTheDocument();
  });
});
