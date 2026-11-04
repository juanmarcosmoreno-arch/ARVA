import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyDialog } from "@/components/assembly/AssemblyDialog";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { api } from "@/lib/api";
import type { AnalysisJobDetail, FlyeMemory, FlyePlan, RawFile, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

// The user's Mac (registro de prueba, items 12, 25, 27, 28 and 29): Flye 2.9.6 in a Docker container with 5.9 GB,
// filtered reads next to the original, and a run that ran out of memory. Synthetic names only.
const original = { id: "f1", original_filename: "reads.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null, uploaded_at: "2026-10-01T10:00:00Z" } as RawFile;
const filtered = { id: "f2", original_filename: "reads.filtlong.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "derived", parent_file_id: "f1", produced_by_job_id: "jf", uploaded_at: "2026-10-02T10:00:00Z" } as RawFile;
const flye: Tool = {
  id: "flye", name: "Flye", description: "", homepage: "", license: "BSD-3-Clause", citation: "", citation_url: "", categories: [], input_formats: [],
  output_formats: [], min_version: "2.9", tested_versions: ["2.9.6"], install: {}, status: "available", path: "/usr/bin/flye", version: "2.9.6",
  version_validated: true, message: "", reason: null,
};
const memory: FlyeMemory = {
  reference: { source: "Flye docs", url: "", genome: "E. coli", data: "PB 50x", genome_size_bp: 4_600_000, coverage_x: 50, ram_gb: 2 }, reference_bases: 230_000_000,
  available_gb: 5.9, container_memory_gb: 5.9, in_container: true, read_bases: 413_000_000, floor_gb: 8.6, scaled_gb: 3.59, estimate_gb: 8.6, verdict: "below_floor",
  expected_genome_size_bp: 2_800_000,
};
const ALL = ["--genome-size", "--min-overlap", "--asm-coverage", "--read-error", "--meta", "--keep-haplotypes", "--no-alt-contigs", "--scaffold"];
const plan = (options = ALL, m: FlyeMemory = memory): FlyePlan => ({
  tool: { status: "available", version: "2.9.6", version_validated: true, message: "", reason: null, options, max_threads: 4, default_threads: 4 },
  files: [],
  read_type_suggestion: { heuristic: true, value: "nano-hq", basis: "error_at_most_3_percent", read_error: null, platform: "nanopore", platform_source: "sample_metadata", mean_error_rate: 0.0072, mean_base_quality: 21.4, q20_read_error_note: true, sup_model_but_low_quality: false },
  genome_size: { expected: { bp: 2_800_000, status: "given", source: "read_statistics" }, total_read_bases: 413_000_000, files_without_stats: [], from_depth: null },
  memory: m,
  sample_technology: "nanopore",
  long_reads_confirmation_required: false,
});
const failed: AnalysisJobDetail = {
  id: "job-oom-1234", project_id: "p", sample_id: "s", job_type: "flye_assembly", tool_name: "Flye", tool_version: "2.9.6", database_name: null,
  database_version: null, input_raw_file_ids: ["f2"], output_paths: [], status: "failed", started_at: null, finished_at: "2026-11-01T12:00:00Z",
  duration_seconds: null, log_text: "", created_at: "2026-11-01T11:00:00Z", commands: [], tool_path: "/usr/bin/flye", result_summary: null, parent_job_id: null, qc_results: [],
  parameters: {
    read_type: "nano-raw", genome_size_bp: 2_800_000, genome_size_basis: "expected_genome_size", assumed_depth_x: null, iterations: 1, min_overlap: null, asm_coverage: 40,
    read_error: null, meta: false, keep_haplotypes: false, no_alt_contigs: false, scaffold: false, threads: 4, long_reads_confirmed: false,
    memory_estimate: { floor_gb: 8.6, verdict: "fits" },
  },
  error_message: "Flye ran out of memory during the assembly stage (the operating system stopped it). ...",
  error_detail: { code: "flye_out_of_memory", params: { stage: "assembly", need_gb: 9 } },
  resources: { profile: "light", choice: "auto", threads: 4, memory_gb: 2, memory_limit_gb: null, memory_option: null, nice: 15, usable_cpus: 4, usable_memory_gb: 5.9, in_container: true, host: "Mac" },
  progress: { tool: "Flye", stage: "assembly", stage_index: 2, stages_total: 7, stages: ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"], started_at: null, stage_started_at: null, updated_at: null, elapsed_seconds: 600, finished: true },
} as AnalysisJobDetail;

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (node: ReactElement) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(wrap(ui));
  return { ...view, rerender: (node: ReactElement) => view.rerender(wrap(node)) };
}

beforeEach(() => {
  useSettings.setState({ language: "es" });
  vi.spyOn(api, "tools").mockResolvedValue([flye]);
});
afterEach(() => vi.restoreAllMocks());

describe("A failed Flye run", () => {
  it("explains a lack of memory in Spanish with the memory the container had and the run's options, and offers to retry", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([]);
    const retry = vi.fn();
    renderWith(<AssemblyTab sampleId="s" jobs={[failed]} files={[original, filtered]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} onRetry={retry} />);
    expect(await screen.findByText(/^Flye se quedó sin memoria en la etapa assembly \(el sistema operativo lo detuvo\)\. Flye necesita al menos unos 9 GB/)).toBeInTheDocument();
    expect(screen.queryByText(/Flye ran out of memory/)).not.toBeInTheDocument();
    expect(screen.getByText(/necesita unos 9 GB de memoria dentro de Docker y el contenedor tiene 5,9 GB/)).toBeInTheDocument();
    expect(screen.getByText("memoria en el contenedor: 5,9 GB · tipo de lectura --nano-raw · --genome-size 2.800.000 · --asm-coverage 40")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reintentar con…/ }));
    expect(retry).toHaveBeenCalledWith(failed);
  });

  it("opens New assembly with the run's files and settings, and the memory explanation, without offering --asm-coverage", async () => {
    vi.spyOn(api, "flyePreview").mockResolvedValue(plan());
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} technology="nanopore" retry={failed} />);
    const note = await screen.findByRole("region", { name: "Reintento" });
    expect(within(note).getByText(/Reintento de la ejecución del .* \(trabajo job-oom-\)/)).toBeInTheDocument();
    expect(await within(note).findByRole("alert")).toHaveTextContent(/Flye no puede ejecutarse en esta computadora con la configuración actual: necesita unos 9 GB de memoria dentro de Docker y el contenedor tiene 5,9 GB/);
    expect(within(note).getByText(/--asm-coverage no baja ese piso/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usar --asm-coverage/ })).not.toBeInTheDocument();
    expect((screen.getByRole("combobox", { name: "Tipo de lectura" }) as HTMLSelectElement).value).toBe("nano-raw");
    expect((screen.getByLabelText(/Cobertura de la primera etapa/) as HTMLInputElement).value).toBe("40");
    expect(screen.getByRole("checkbox", { name: "reads.filtlong.fastq.gz" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "reads.fastq.gz" })).not.toBeChecked();
    const summary = screen.getByRole("region", { name: "Qué hará esta ejecución" });
    expect(within(summary).getByText(/^Cobertura de la primera etapa: --asm-coverage 40/)).toBeInTheDocument();
    expect(within(summary).getByText(/^Tamaño del genoma: --genome-size 2800000/)).toBeInTheDocument();
  });
});

describe("New assembly with Flye", () => {
  it("preselects the filtered reads and keeps the user's choices when the dialog is closed and opened again", async () => {
    vi.spyOn(api, "flyePreview").mockResolvedValue(plan(ALL, { ...memory, available_gb: 15.6, container_memory_gb: 15.6, verdict: "fits" }));
    const view = renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} technology="nanopore" />);
    expect(await screen.findByRole("checkbox", { name: "reads.filtlong.fastq.gz" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "reads.fastq.gz" })).not.toBeChecked();
    fireEvent.change(screen.getByRole("combobox", { name: "Tipo de lectura" }), { target: { value: "nano-raw" } });
    fireEvent.change(screen.getByLabelText(/Cobertura de la primera etapa/), { target: { value: "40" } });
    view.rerender(<AssemblyDialog open={false} onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} technology="nanopore" />);
    view.rerender(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} technology="nanopore" />);
    expect(((await screen.findByRole("combobox", { name: "Tipo de lectura" })) as HTMLSelectElement).value).toBe("nano-raw");
    expect((screen.getByLabelText(/Cobertura de la primera etapa/) as HTMLInputElement).value).toBe("40");
    expect(screen.getByRole("checkbox", { name: "reads.filtlong.fastq.gz" })).toBeChecked();
  });

  it("says why an option field is off when the installed Flye's --help does not list it", async () => {
    vi.spyOn(api, "flyePreview").mockResolvedValue(plan(["--genome-size", "--meta"], { ...memory, available_gb: 15.6, verdict: "fits" }));
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} technology="nanopore" />);
    expect(await screen.findAllByText("El Flye 2.9.6 instalado no la ofrece: su --help no muestra esta opción, así que ARVA no la pasa.")).toHaveLength(3);
    expect(screen.getByLabelText(/Cobertura de la primera etapa/)).toBeDisabled();
  });

  it("shows in English too that Flye cannot run below its fixed k-mer table", async () => {
    useSettings.setState({ language: "en" });
    vi.spyOn(api, "flyePreview").mockResolvedValue(plan());
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} technology="nanopore" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Flye cannot run on this computer as configured: it needs about 9 GB of memory inside Docker, and the container has 5.9 GB.",
    );
  });
});
