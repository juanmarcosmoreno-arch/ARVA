import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NcbiCollectionDialog } from "@/components/databases/NcbiCollectionDialog";
import { SpeciesDialog } from "@/components/genomic/SpeciesDialog";
import { SpeciesCard } from "@/components/genomic/SpeciesResult";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import { checkText, initialSpeciesForm, reasonText, speciesBody, speciesProblems, statusText } from "@/lib/species";
import type { AnalysisJob, Assembly, NcbiPlan, ReferenceDatabase, SpeciesPlan, SpeciesResult, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" data-option={JSON.stringify(props.option)} />;
  }),
}));

// FastANI 1.34's real result for S. aureus NCTC 8325 (GCF_000013425.1) against three Staphylococcus type strains
// (workflows/tool-adapters/tests/fixtures/species), and mlst 2.35.0's real call for that genome (saureus ST8).
const saureus: SpeciesResult = {
  id: "sp-1", sample_id: "s", assembly_id: "asm-00001", job_id: "job-sp", method: "fastani", tool: "FastANI", tool_version: "1.34",
  database_kind: "reference_genomes", database_name: "Reference genome collection (FastANI list)", database_version: "NCBI Datasets 2026-10-29 #62a03f24483a",
  database_checksum: null, parameters: { settings: { threads: 4, kmer: 16, frag_len: 3000, min_fraction: 0.2, max_ratio_diff: 10 } },
  status: "same_species", species: "Staphylococcus aureus",
  hits: [
    { rank: 1, reference: "GCF_006094915.1", accession: "GCF_006094915.1", organism: "Staphylococcus aureus", species: "Staphylococcus aureus", strain: "ATCC 12600", type_material: true, ani: 99.9171, af: 900 / 940, fragments_mapped: 900, fragments_total: 940 },
    { rank: 2, reference: "GCF_000236925.1", accession: "GCF_000236925.1", organism: "Staphylococcus argenteus", species: "Staphylococcus argenteus", strain: "MSHR1132", type_material: true, ani: 88.85, af: 815 / 940, fragments_mapped: 815, fragments_total: 940 },
    { rank: 3, reference: "GCF_006094375.1", accession: "GCF_006094375.1", organism: "Staphylococcus epidermidis", species: "Staphylococcus epidermidis", strain: "ATCC 14990", type_material: true, ani: 79.1388, af: 317 / 940, fragments_mapped: 317, fragments_total: 940 },
  ],
  interpretation: {
    method: "fastani", status: "same_species", species: "Staphylococcus aureus",
    best: { reference: "GCF_006094915.1", accession: "GCF_006094915.1", organism: "Staphylococcus aureus", species: "Staphylococcus aureus", strain: "ATCC 12600", type_material: true, ani: 99.9171, af: 900 / 940, distance: null },
    runner_up: { reference: "GCF_000236925.1", accession: "GCF_000236925.1", organism: "Staphylococcus argenteus", species: "Staphylococcus argenteus", strain: "MSHR1132", type_material: true, ani: 88.85, af: 815 / 940, distance: null },
    reasons: [], caveats: [{ code: "collection_bound", params: {} }, { code: "single_genus", params: { genus: "Staphylococcus" } }, { code: "fastani_range", params: {} }],
    thresholds: { ani_boundary: 95, min_af: 0.5, margin: 0.5 }, sources: {},
  },
  consistency: [{ source: "mlst", outcome: "agree", reason: null, params: { scheme: "saureus", st: "8", species: "Staphylococcus aureus" } }],
  warnings: [],
  details: { references_checksum: "a".repeat(64), references: [], hits_total: 3 },
  files: { output: { path: "r/fastani.tsv", sha256: "x", size_bytes: 1 }, log: { path: "r/fastani.log", sha256: "x", size_bytes: 1 } },
  created_at: "2026-10-29T17:00:00Z",
};

// FastANI 1.34's real result for E. coli O157:H7 Sakai against K-12 MG1655 and Shigella flexneri 2a 301.
const ecoli: SpeciesResult = {
  ...saureus, id: "sp-2", status: "ambiguous", species: null,
  hits: [
    { rank: 1, reference: "GCF_000005845.2", accession: "GCF_000005845.2", organism: "Escherichia coli str. K-12 substr. MG1655", species: "Escherichia coli", type_material: null, ani: 97.7623, af: 1406 / 1863 },
    { rank: 2, reference: "GCF_000006925.2", accession: "GCF_000006925.2", organism: "Shigella flexneri 2a str. 301", species: "Shigella flexneri", type_material: null, ani: 96.9917, af: 1353 / 1863 },
  ],
  interpretation: {
    ...saureus.interpretation, status: "ambiguous", species: null,
    reasons: [{ code: "two_species_above_boundary", params: { species: "Escherichia coli", other: "Shigella flexneri", ani: 97.7623, other_ani: 96.9917, boundary: 95 } }],
    caveats: [{ code: "collection_bound", params: {} }],
  },
  consistency: [{ source: "mlst", outcome: "not_comparable", reason: "no_ani_species", params: { scheme: "ecoli_achtman_4", st: "11", species: "" } }],
};

const draft = {
  id: "asm-00001", sample_id: "s", job_id: "job-flye", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3",
  mode: "long", read_type: "nano-hq", input_file_ids: [], created_at: "2026-10-28T13:00:00Z",
  stats: { contig_count: 1, total_length: 2_821_361, circularity: { contigs_with_circularity: 1, circular_contigs: 1 } }, warnings: [],
} as unknown as Assembly;

const tool = { status: "available", version: "1.34", version_validated: true, message: "", reason: null, path: "/env/bin/fastANI", license: "Apache-2.0",
  citation: "Jain C. et al.", citation_url: "https://doi.org/10.1038/s41467-018-07641-9", max_threads: 4, default_threads: 4, id: "fastani", name: "FastANI", memory_gb: 8 };

const methods = { fastani: { tool: "fastani", kind: "reference_genomes", validation: "validated" }, skani: { tool: "skani", kind: "reference_genomes", validation: "validated" },
  mash: { tool: "mash", kind: "mash", validation: "test_database" }, sylph: { tool: "sylph", kind: "sylph", validation: "test_database" },
  gtdbtk: { tool: "gtdbtk", kind: "gtdbtk", validation: "not_validated" } } as const;

const collection = { id: "db-1", kind: "reference_genomes", name: "Reference genome collection (FastANI list)", version: "NCBI Datasets 2026-10-29 #62a03f24483a",
  version_source: "declared" as const, checksum: null, path: "/db/refs.txt", host_path: "/db/refs.txt", size_bytes: 8_000_000, is_default: true, status: "registered",
  available: true, unavailable_reason: null, verification_level: "quick",
  collection: { genomes: 3, present: 3, missing: 0, species: 3, genera: ["Staphylococcus"], genus_count: 1, by_species: [], type_material: 3, reference_genomes: 2, unclassified: 0, fingerprint: "f", source: null } };

const plan = (method: keyof typeof methods, extra: Partial<SpeciesPlan> = {}): SpeciesPlan => ({
  method, methods, tool, validation: methods[method].validation, database_kind: methods[method].kind, databases: [collection], database: collection,
  assembly: { assembly_id: "asm-00001", kind: "assembly", assembler: "Flye", assembler_version: "2.9.3", parent_assembly_id: null, contigs: 1, total_length: 2_821_361, synthetic_evidence: [] },
  context: { mlst: { id: "m", scheme: "saureus", st: "8", tool_version: "2.35.0" }, annotation: null }, problems: [], gtdbtk_memory_gb: null, ...extra,
});

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
  vi.spyOn(api, "tools").mockResolvedValue([{ id: "fastani", name: "FastANI", status: "available" } as Tool]);
});
afterEach(() => vi.restoreAllMocks());

const t = (key: keyof typeof dictionaries.en, vars?: Record<string, string | number>) =>
  Object.entries(vars ?? {}).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), dictionaries.en[key] as string);

describe("species helpers", () => {
  it("formats ARVA's reasons and the consistency checks", () => {
    expect(reasonText(t, ecoli.interpretation.reasons[0])).toBe(
      "Escherichia coli (97.76 %) and Shigella flexneri (96.99 %) are both above 95.00 %: this collection cannot separate them by ANI.",
    );
    expect(statusText(t, "same_species", "Staphylococcus aureus")).toBe("Same species as the closest reference: Staphylococcus aureus");
    expect(checkText(t, saureus.consistency[0])).toBe("MLST scheme saureus (ST 8): agrees with the ANI species");
    expect(checkText(t, ecoli.consistency[0])).toBe("MLST scheme ecoli_achtman_4 (ST 11): not comparable: the ANI result names no species");
  });

  it("checks the form and builds the request", () => {
    const form = { ...initialSpeciesForm("asm-00001"), threads: "9" };
    expect(speciesProblems(form, plan("fastani"))).toEqual(["species.problem.threads", "species.problem.confirm"]);
    expect(speciesBody({ ...form, threads: "2", confirmed: true, databaseId: "db-1" })).toEqual({ method: "fastani", database_id: "db-1", threads: 2, confirmed: true });
  });

  it("has guide entries for the new terms", () => {
    for (const id of ["ani", "species_boundary", "reference_collection", "gtdb"] as const) expect(GUIDE_BY_ID[id].references.length).toBeGreaterThan(0);
  });
});

describe("SpeciesCard", () => {
  it("shows the same-species reading with the type strain, the MLST agreement and the hits", () => {
    renderWith(<SpeciesCard result={saureus} />);
    expect(screen.getByText("Same species as the closest reference: Staphylococcus aureus")).toBeInTheDocument();
    expect(screen.getByText(/Closest reference: GCF_006094915.1 \(Staphylococcus aureus\), ANI 99.92 %, aligned fraction 95.7 %/)).toBeInTheDocument();
    expect(screen.getByText("MLST scheme saureus (ST 8): agrees with the ANI species")).toBeInTheDocument();
    expect(screen.getByText(/This collection holds only Staphylococcus genomes/)).toBeInTheDocument();
    expect(screen.getByText("900/940")).toBeInTheDocument();
    expect(screen.getByText("ANI and aligned fraction of the best hits")).toBeInTheDocument();
    const option = JSON.parse(screen.getByTestId("chart").dataset.option ?? "{}");
    expect(option.series[0].data).toEqual([99.9171, 88.85, 79.1388]);
    expect(option.series[0].markLine.data).toEqual([{ xAxis: 95 }]);
  });

  it("explains an ambiguous result instead of naming a species", () => {
    renderWith(<SpeciesCard result={ecoli} />);
    expect(screen.getByText("Ambiguous: the evidence does not support a single species")).toBeInTheDocument();
    expect(screen.getByText(/are both above 95.00 %/)).toBeInTheDocument();
    expect(screen.queryByText(/Same species as/)).not.toBeInTheDocument();
  });

  it("is in Spanish", () => {
    useSettings.setState({ language: "es" });
    renderWith(<SpeciesCard result={saureus} />);
    expect(screen.getByText("Misma especie que la referencia más cercana: Staphylococcus aureus")).toBeInTheDocument();
    expect(screen.getByText("Esquema de MLST saureus (ST 8): coincide con la especie por ANI")).toBeInTheDocument();
  });
});

describe("SpeciesDialog", () => {
  it("explains the methods, shows the collection and refuses GTDB-Tk without its memory", async () => {
    const preview = vi.spyOn(api, "speciesPreview").mockImplementation(async (_a, method) =>
      method === "gtdbtk"
        ? plan("gtdbtk", { databases: [], database: null, gtdbtk_memory_gb: { bacteria: 140, archaea: 100 },
            problems: [{ code: "gtdbtk_memory", message: "m", params: { required: 140, available: 8 } }, { code: "no_database", message: "m", params: { kind: "GTDB-Tk reference data" } }] })
        : plan(method),
    );
    const run = vi.spyOn(api, "runSpecies").mockResolvedValue({ id: "job" } as AnalysisJob);
    renderWith(<SpeciesDialog open onOpenChange={() => {}} sampleId="s" assemblies={[draft]} />);
    expect(await screen.findByText(/3 genomes of 3 species in 1 genus; 3 from type material/)).toBeInTheDocument();
    expect(screen.getByText("MLST of this assembly: scheme saureus, ST 8.")).toBeInTheDocument();
    expect(screen.getAllByText("validated with ARVA")).toHaveLength(2);
    expect(screen.getByText("not validated")).toBeInTheDocument();
    fireEvent.click(screen.getByText(/I have checked the method/));
    fireEvent.click(screen.getByRole("button", { name: /Identify$/ }));
    await waitFor(() => expect(run).toHaveBeenCalledWith("asm-00001", { method: "fastani", database_id: null, threads: null, confirmed: true }));

    fireEvent.click(screen.getByRole("radio", { name: /GTDB-Tk/ }));
    expect(await screen.findByText(/the performance profile gives a run 8 GB. ARVA does not start it/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Identify$/ })).toBeDisabled();
    expect(preview).toHaveBeenCalledWith("asm-00001", "gtdbtk", null);
  });
});

describe("NcbiCollectionDialog", () => {
  const ready: NcbiPlan = {
    status: "ready", query: "Staphylococcus argenteus", filters: { source: "refseq", type_material: true, reference_only: false, exclude_atypical: true, exact_taxon: false },
    candidates: [], taxon: { tax_id: 985002, name: "Staphylococcus argenteus", rank: "species", bacterial: true }, total_count: 4, limit: 2000,
    query_url: "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/985002/dataset_report", genomes: 4, fingerprint: "f".repeat(64), species: 1,
    by_species: [{ species: "Staphylococcus argenteus", genomes: 4 }], type_material: 4, reference_genomes: 1, preview: [],
    download: { record_count: 4, estimated_mb: 3, fasta_files: 4, fasta_mb: 3.4, resource_updated_on: null }, zip_estimate_bytes: 3_000_000,
    fasta_estimate_bytes: 11_300_000, required_bytes: 14_300_000, db_dir: "/db", folder: "reference-genomes/ncbi-x", host_target_path: "/db/reference-genomes/ncbi-x",
    free_bytes: 10_000_000_000, available_bytes: 9_000_000_000, enough: true, target_exists: false,
  };

  it("shows the number of genomes and the size, and downloads only after confirmation", async () => {
    const planCall = vi.spyOn(api, "ncbiPlan").mockResolvedValue(ready);
    const start = vi.spyOn(api, "ncbiStart").mockResolvedValue({ id: "db" } as ReferenceDatabase);
    renderWith(<NcbiCollectionDialog onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Staphylococcus"), { target: { value: "Staphylococcus argenteus" } });
    fireEvent.click(screen.getByRole("button", { name: /Check/ }));
    expect(await screen.findByText(/4 genomes of 1 species; 4 from type material, 1 reference genomes/)).toBeInTheDocument();
    expect(screen.getByText(/Download about 3 MB \(NCBI's estimate\)/)).toBeInTheDocument();
    expect(planCall).toHaveBeenCalledWith({ taxon: "Staphylococcus argenteus", tax_id: null, filters: ready.filters });
    const download = screen.getByRole("button", { name: /Download$/ });
    expect(download).toBeDisabled();
    fireEvent.click(screen.getByText(/Download these 4 genomes/));
    fireEvent.click(download);
    await waitFor(() => expect(start).toHaveBeenCalledWith({ taxon: "Staphylococcus argenteus", tax_id: 985002, filters: ready.filters, confirm_genomes: 4, confirm_fingerprint: "f".repeat(64) }));
  });

  it("asks to choose between bacterial taxa of the same name", async () => {
    const planCall = vi.spyOn(api, "ncbiPlan").mockResolvedValueOnce({ ...ready, status: "choose_taxon", taxon: null,
      candidates: [{ tax_id: 1, name: "Alpha", rank: "genus", bacterial: true }, { tax_id: 2, name: "Alpha", rank: "genus", bacterial: true }] }).mockResolvedValueOnce(ready);
    renderWith(<NcbiCollectionDialog onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Staphylococcus"), { target: { value: "Alpha" } });
    fireEvent.click(screen.getByRole("button", { name: /Check/ }));
    fireEvent.click(await screen.findByText(/Alpha · genus · NCBI Taxonomy 2/));
    await waitFor(() => expect(planCall).toHaveBeenLastCalledWith({ taxon: "Alpha", tax_id: 2, filters: ready.filters }));
  });
});
