import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { AssemblyDialog } from "@/components/assembly/AssemblyDialog";
import { api } from "@/lib/api";
import type { AnalysisJobDetail, Assembly, AssemblyDetail, FlyePlan, RawFile, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

const reads = { id: "f1", original_filename: "ont.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null } as RawFile;
const flye: Tool = {
  id: "flye", name: "Flye", description: "", homepage: "", license: "BSD-3-Clause", citation: "", citation_url: "", categories: [], input_formats: [],
  output_formats: [], min_version: "2.9", tested_versions: ["2.9.3"], install: {}, status: "available", path: "/usr/bin/flye", version: "2.9.3",
  version_validated: true, message: "", reason: "samtools_linked",
};
const job = (status: AnalysisJobDetail["status"], extra: Partial<AnalysisJobDetail> = {}): AnalysisJobDetail => ({
  id: `job-${status}`, project_id: "p", sample_id: "s", job_type: "flye_assembly", tool_name: "Flye", tool_version: "2.9.3", database_name: null,
  database_version: null, parameters: {}, input_raw_file_ids: ["f1"], output_paths: ["results/p/s/j/assembly_graph.gfa", "results/p/s/j/assembly.fasta"],
  status, started_at: null, finished_at: null, duration_seconds: null, log_text: "", error_message: null, created_at: "2026-10-28T13:00:00Z",
  commands: [], tool_path: "/usr/bin/flye", result_summary: null, parent_job_id: null, qc_results: [], ...extra,
});
const progress = {
  tool: "Flye", stage: "repeat", stage_index: 4, stages_total: 7, stages: ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"],
  started_at: null, stage_started_at: null, updated_at: null, elapsed_seconds: 75, finished: false,
};
const assembly: Assembly = {
  id: "a1", sample_id: "s", job_id: "job-completed", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3", mode: "long", read_type: "nano-hq",
  input_file_ids: ["f1"], created_at: "2026-10-28T13:05:00Z",
  stats: {
    contig_count: 2, total_length: 315_000, largest_contig: 300_000, smallest_contig: 15_000, n50: 300_000, l50: 1, n90: 300_000, l90: 1, gc_percent: 49.6,
    n_count: 0, circularity: { contigs_with_circularity: 2, circular_contigs: 2 }, coverage: { contigs_with_coverage: 2, length_weighted_median: 31 },
    contig_rows: { stored: 2, total: 2, truncated: false }, expected_genome_size: { bp: 328_984, status: "given", source: "assembly_parameters", basis: "reads_over_depth", assumed_depth_x: 30 },
    files: { contigs: null, graph: null, info: null },
  },
  warnings: [{ code: "high_coverage_contigs", heuristic: true, message: "x", params: { count: 1, ratio: 4, median_coverage: 31 }, contigs: ["contig_2"], contigs_total: 1 }],
};
const detail: AssemblyDetail = {
  ...assembly,
  contigs: [
    { rank: 1, name: "contig_1", length: 300_000, gc_percent: 49.8, n_count: 0, other_iupac_count: 0, coverage: 31, circular: true, repeat: false },
    { rank: 2, name: "contig_2", length: 15_000, gc_percent: 45.4, n_count: 0, other_iupac_count: 0, coverage: 53, circular: true, repeat: false },
  ],
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
  useSettings.setState({ language: "es" });
  vi.spyOn(api, "tools").mockResolvedValue([flye]);
});
afterEach(() => vi.restoreAllMocks());

describe("Assembly tab", () => {
  it("shows a running Flye job's stage, elapsed time and live log, and a finished assembly with Flye's columns", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([assembly]);
    vi.spyOn(api, "assembly").mockResolvedValue(detail);
    vi.spyOn(api, "jobLog").mockResolvedValue({ text: "INFO: >>>STAGE: repeat", source: "tool" });
    const done = job("completed", {
      result_summary: { contigs: [{ name: "contig_2", length: 15_000, coverage: 53, circular: true, repeat: false, multiplicity: 2, alt_group: null, graph_path: "2" }] },
    });
    renderWith(<AssemblyTab sampleId="s" jobs={[job("running", { progress }), done]} files={[reads]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("Etapa 4 de 7: repeat")).toBeInTheDocument();
    expect(screen.getByText("1 min 15 s transcurridos")).toBeInTheDocument();
    expect(await screen.findByText("INFO: >>>STAGE: repeat")).toBeInTheDocument();
    expect(await screen.findByText("Flye 2.9.3 · --nano-hq")).toBeInTheDocument();
    expect(screen.getByText(/estimado como bases de las lecturas ÷ una profundidad supuesta/)).toBeInTheDocument();
    expect(screen.getByText(/1 contig\(s\) con cobertura mayor que 4 × la mediana/)).toBeInTheDocument();
    // In the warning's contig list and in the contig table.
    expect(await screen.findAllByText("contig_2")).toHaveLength(2);
    expect(screen.getByText("2", { selector: "td.font-mono" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /assembly_graph\.gfa/ })).toHaveAttribute("href", "/api/v1/jobs/job-completed/outputs/assembly_graph.gfa?download=true");
  });

  it("names the stage at which a run failed", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([]);
    renderWith(<AssemblyTab sampleId="s" jobs={[job("failed", { progress: { ...progress, stage: "configure", finished: true }, error_message: "Flye found no read longer than the minimum overlap" })]} files={[reads]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("Flye se detuvo durante la etapa configure.")).toBeInTheDocument();
    expect(screen.getByText("Flye found no read longer than the minimum overlap")).toBeInTheDocument();
  });
});

describe("Flye dialog", () => {
  it("shows ARVA's heuristic suggestion without choosing for the user", async () => {
    const plan: FlyePlan = {
      tool: { status: "available", version: "2.9.3", version_validated: true, message: "", reason: null, options: ["--genome-size", "--meta"], max_threads: 4, default_threads: 4 },
      files: [{ file_id: "f1", name: "ont.fastq.gz", origin: "imported", header_platform: null, header_confidence: "none", basecall_models: [], pacbio_read_types: [], stats_job_id: "j", total_bases: 9_869_520, max_read_length: 45_000, read_n50: 8_700, mean_base_quality: 13.89 }],
      read_type_suggestion: { heuristic: true, value: "nano-hq", basis: "error_at_most_5_percent", platform: "nanopore", platform_source: "sample_metadata", mean_error_rate: 0.0408, mean_base_quality: 13.89, q20_read_error_note: false, sup_model_but_low_quality: false },
      genome_size: { expected: { bp: null, status: "not_given", source: null }, total_read_bases: 9_869_520, files_without_stats: [], from_depth: null },
      sample_technology: "nanopore",
      long_reads_confirmation_required: false,
    };
    const preview = vi.spyOn(api, "flyePreview").mockResolvedValue(plan);
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[reads]} />);
    expect(await screen.findByText("ARVA sugiere --nano-hq")).toBeInTheDocument();
    expect(screen.getByText(/error medio del 4\.08% \(Q13\.9\), dentro del < 5% de Flye/)).toBeInTheDocument();
    expect(preview).toHaveBeenCalledWith("s", { raw_file_ids: ["f1"], assumed_depth_x: null });
    expect((screen.getByRole("combobox", { name: "Tipo de lectura" }) as HTMLSelectElement).value).toBe("");
    expect(screen.getByRole("button", { name: /Iniciar el ensamblaje/ })).toBeDisabled();
    // --keep-haplotypes, --no-alt-contigs and --scaffold are not in this plan's options.
    expect(screen.getAllByText("Esta versión de Flye no la ofrece (no aparece en su --help).")).toHaveLength(3);
  });
});
