import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MobilomeSection } from "@/components/genomic/Mobilome";
import { ProjectVariants } from "@/components/genomic/ProjectVariants";
import { VariantCard } from "@/components/genomic/VariantResult";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { api } from "@/lib/api";
import {
  displayOrder,
  distributionRows,
  effectImpact,
  formProblems,
  histogramLabels,
  initialVariantForm,
  linkedPosition,
  mainConsequence,
  variantBody,
  type VariantRecord,
  type VariantRun,
} from "@/lib/variants";
import { useSettings } from "@/store/settings";

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

// Numbers from the API test's real bcftools 1.19 run on SIMULATED reads against a SIMULATED draft
// (apps/api/tests/test_variants_api.py): 16 records, 14 passing, two indels failing LowAltFraction.
const run: VariantRun = {
  id: "vc1", job_id: "job1", sample_id: "s1", created_at: "2026-11-02T14:00:00Z",
  reference: { kind: "assembly", label: "REF · Flye", sha256: "a".repeat(64), total_length: 108_000, annotation: { id: "an1", tool: "Bakta", tool_version: "1.12.2" } },
  reference_sha256: "a".repeat(64), technology: "illumina", aligner: "BWA", aligner_version: "0.7.17-r1188", caller_version: "1.19",
  reads: [{ role: "r1", file_id: "f1", name: "illumina_R1.fastq.gz", sha256: null }, { role: "r2", file_id: "f2", name: "illumina_R2.fastq.gz", sha256: null }],
  parameters: { settings: { min_mapq: 60, min_baseq: 13, max_depth: 1000, call_indels: true, prior: 1.1e-3, min_qual: 100, min_depth: 10, min_alt_fraction: 0.9, threads: 2 }, effects: true, keep_alignment: false, aligner_preset: null },
  summary: {
    records: 16, pass: 14, by_type: { snp: 7, mnp: 0, insertion: 4, deletion: 3, complex: 0 }, by_filter: { LowAltFraction: 2 }, by_effect: { missense: 1, none: 13 },
    start_codon_notes: 0,
    depth_histogram: { edges: [0, 10, 20, 1000], pass: [0, 2, 12], filtered: [0, 0, 2] },
    alt_fraction_histogram: { edges: [0, 0.5, 0.9, 1], pass: [0, 0, 14], filtered: [0, 2, 0] },
    distribution: { bin: 500, contigs: [{ contig: "contig_1", length: 100_000, snp: [1, 0, 2], other: [0, 1, 0] }] },
    alignment: { reads: 30_000, reads_mapped: 29_900, mapped_percent: 99.67, properly_paired_percent: 99.1 },
    coverage: [{ contig: "contig_1", length: 100_000, mean_depth: 40, covered_percent: 100 }],
    callable_bases: 107_000, callable_percent: 99.07, reference_length: 108_000, csq_features: { written: 1 },
  },
  warnings: [], files: { vcf: { sha256: "b", size_bytes: 10 }, vcf_index: { sha256: "c", size_bytes: 1 } }, duration_seconds: 4,
};

const record = (over: Partial<VariantRecord>): VariantRecord => ({
  contig: "contig_1", pos: 5000, end: 5000, ref: "A", alt: "G", type: "snp", qual: 225.4, filters: [], pass: true, depth: 40, ref_reads: 0, alt_reads: 40,
  alt_fraction: 1, genotype: "1", consequences: [], effect: null, ...over,
});

describe("variant helpers", () => {
  it("builds the request from the form and lists what is missing", () => {
    const f = initialVariantForm(undefined, "ont");
    expect(formProblems(f)).toEqual(["variants.problem.reference", "variants.problem.reads"]);
    const ready = { ...f, assemblyId: "a1", long: "f9" };
    expect(formProblems(ready)).toEqual([]);
    expect(variantBody(ready)).toMatchObject({ technology: "ont", reference: { kind: "assembly", assembly_id: "a1" }, inputs: { long: "f9" } });
    const pair = { ...initialVariantForm(undefined, "illumina"), assemblyId: "a1", r1: "x" };
    expect(formProblems(pair)).toContain("variants.problem.pair");
    expect(variantBody({ ...pair, r2: "y", threads: "3" })).toMatchObject({ inputs: { r1: "x", r2: "y" }, threads: 3 });
  });

  it("reads consequences, impacts, bins and labels", () => {
    const v = record({ consequences: [{ see_position: 4998 }, { gene: "geneX", aa_change: "4F>4I", terms: ["missense"] }], effect: "missense" });
    expect(mainConsequence(v)?.gene).toBe("geneX");
    expect(linkedPosition(v)).toBe(4998);
    expect([effectImpact("frameshift"), effectImpact("missense"), effectImpact("synonymous"), effectImpact(null)]).toEqual(["high", "moderate", "low", "none"]);
    expect(distributionRows(run.summary.distribution, "contig_1")).toEqual([[1, 1, 0], [501, 0, 1], [1001, 2, 0]]);
    expect(histogramLabels(run.summary.depth_histogram)).toEqual(["0–10", "10–20", "≥ 20"]);
    expect(displayOrder([[0, 9, 1], [9, 0, 8], [1, 8, 0]])).toEqual([0, 2, 1]);
  });

  it("has guide entries in both languages", () => {
    for (const id of ["variant_calling", "variant_filters", "variant_effects", "snp_distance", "mobilome"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.title).toBeTruthy();
    }
  });
});

describe("variant results", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
    vi.restoreAllMocks();
  });

  it("shows the counts, the callable fraction, the files and the records with their filters", async () => {
    vi.spyOn(api, "variantRecords").mockResolvedValue({ total: 2, offset: 0, variants: [
      record({ consequences: [{ gene: "geneX", aa_change: "4F>4I", terms: ["missense"] }], effect: "missense" }),
      record({ pos: 25000, end: 25003, ref: "GTAT", alt: "G", type: "deletion", filters: ["LowAltFraction"], pass: false, alt_fraction: 0.875, ref_reads: 3, alt_reads: 21, depth: 24 }),
    ] });
    renderWith(<VariantCard run={run} />);
    expect(screen.getByText("Against REF · Flye · Illumina (short reads)")).toBeInTheDocument();
    expect(screen.getByText("of 16 records")).toBeInTheDocument();
    expect(screen.getByText("99.1%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /VCF/ })).toHaveAttribute("href", expect.stringContaining("/variants/runs/vc1/files/vcf"));
    await waitFor(() => expect(screen.getByText("4F>4I")).toBeInTheDocument());
    expect(screen.getByText("LowAltFraction")).toBeInTheDocument();
    expect(screen.getAllByText("Missense").length).toBeGreaterThan(0);
  });

  it("shows the SNP distances with a note that they are not a phylogeny", async () => {
    vi.spyOn(api, "projectVariants").mockResolvedValue({ project_id: "p", references: [{ reference_sha256: "a".repeat(64), reference: run.reference, runs: [
      { id: "1", sample_id: "s1", sample_code: "S1", technology: "illumina", pass: 14, records: 16, by_type: run.summary.by_type, callable_percent: 99, mapped_percent: 99.6 },
      { id: "2", sample_id: "s2", sample_code: "S2", technology: "ont", pass: 6, records: 7, by_type: { ...run.summary.by_type, snp: 6 }, callable_percent: 98, mapped_percent: 99 },
    ] }] });
    vi.spyOn(api, "snpMatrix").mockResolvedValue({ samples: [{ id: "1", label: "S1" }, { id: "2", label: "S2" }], sites: Array.from({ length: 7 }, (_, i) => ({ contig: "contig_1", pos: i + 1, ref: "A" })),
      alleles: ["GGGGGGG", "GGGNGGG"], distances: [[0, 0], [0, 0]], compared_sites: [[7, 6], [6, 6]], core_sites: 6, missing: [0, 1], same_settings: true, reference: run.reference });
    renderWith(<ProjectVariants projectId="p" />);
    await waitFor(() => expect(screen.getByText("Pairwise SNP distances")).toBeInTheDocument());
    expect(screen.getByText(/This is not a phylogeny/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /SNP sites \(FASTA\)/ })).toHaveAttribute("href", expect.stringContaining("format=fasta"));
  });

  it("places genes on plasmids and next to elements, and says proximity is not transfer", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "sampleMobilome").mockResolvedValue({ sample_id: "s", window: 10000, assemblies: [{
      assembly_id: "asm1", assembler: "Flye", kind: "assembly", window: 10000,
      runs: { mobsuite: "j1", plasmidfinder: null, isescan: "j2", integronfinder: null, genomad: null }, gene_runs: { amrfinderplus: "j3", vfdb: null },
      plasmids: [{ id: "AA001", contigs: ["contig_2"], size: 8000, rep_types: ["rep_cluster_1"], relaxase_types: null, predicted_mobility: "mobilizable",
        genes: [{ source: "amrfinderplus", gene: "blaZ", name: null, type: "AMR", class: "BETA-LACTAM", contig: "contig_2", start: 1000, end: 1800, relation: "on_plasmid", distance: null }] }],
      replicons: [],
      elements: [{ tool: "isescan", category: "insertion_sequence", element: "IS21_1", element_type: "IS21", contig: "contig_1", start: 20000, end: 21500, strand: "+", completeness: "complete", plasmid: null,
        genes: [{ source: "amrfinderplus", gene: "near", name: null, type: "AMR", class: null, contig: "contig_1", start: 25000, end: 25600, relation: "near", distance: 3500 }] }],
      counts: { plasmids: 1, insertion_sequences: 1, repetitive_elements: 0, integrons: 0, viruses: 0, genes_on_plasmids: 1, genes_with_elements: 1, amr_on_plasmids: 1 },
    }] });
    renderWith(<MobilomeSection sampleId="s" />);
    await waitFor(() => expect(screen.getByText("AA001")).toBeInTheDocument());
    expect(screen.getByText(/blaZ · en plásmido/)).toBeInTheDocument();
    expect(screen.getByText(/near · cerca 3,5 kpb/)).toBeInTheDocument();
    expect(screen.getByText(/no es prueba de movilización/)).toBeInTheDocument();
  });
});
