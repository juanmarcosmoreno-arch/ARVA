import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { QuastDialog } from "@/components/assembly/QuastDialog";
import { api } from "@/lib/api";
import {
  formatQuastValue,
  jobRelativePath,
  quastOutput,
  quastProblems,
  quastRequest,
  referenceCandidates,
  reportRows,
} from "@/lib/quast";
import type { AnalysisJobDetail, Assembly, QuastPlan, QuastSummary, RawFile, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

const scope = "results/p/s/job-q";
const summary: QuastSummary = {
  quast_version: "5.2.0",
  python_version: "3.12.3",
  min_contig: 500,
  reference: { file_id: "ref", name: "reference.fasta", sha256: "abc", size_bytes: 319_212 },
  assemblies: [{ assembly_id: "a1", label: "Flye 2.9.3 aaaaaaaa", assembler: "Flye", assembler_version: "2.9.3", assembly_job_id: "j1", contigs_sha256: "x" }],
  report: {
    labels: ["Flye 2.9.3 aaaaaaaa"],
    rows: [
      { field: "# contigs (>= 0 bp)", values: [8] },
      { field: "# contigs", values: [6] },
      { field: "N50", values: [140_000] },
      { field: "auNA", values: [135_185.9] },
      { field: "Genome fraction (%)", values: [99.683] },
      { field: "# unaligned contigs", values: [{ full: 1, partial: 0 }] },
      { field: "NA50", values: [null] },
    ],
  },
  crosscheck: [
    {
      assembly_id: "a1",
      label: "Flye 2.9.3 aaaaaaaa",
      arva: { n50: 140_000 },
      all_agree: false,
      rows: [
        { metric: "N50", arva_key: "n50", quast: 140_001, arva: 140_000, decimals: null, agrees: false },
        { metric: "GC (%)", arva_key: "gc_percent", quast: 49.45, arva: 49.4512, decimals: 2, agrees: true },
      ],
    },
  ],
  aligner: { name: "minimap2", executable: "/usr/bin/minimap2", version: "2.26-r1175" },
  warnings: ["Python locale settings can't be changed"],
  quast_log_empty: false,
  html: { report: "report.html", icarus: "icarus.html", viewers: ["icarus_viewers/contig_size_viewer.html"] },
};
const job = (status: AnalysisJobDetail["status"], extra: Partial<AnalysisJobDetail> = {}): AnalysisJobDetail => ({
  id: "job-q", project_id: "p", sample_id: "s", job_type: "quast_evaluation", tool_name: "QUAST", tool_version: "5.2.0", database_name: null,
  database_version: null, parameters: { assemblies: [{ label: "Flye 2.9.3 aaaaaaaa" }] }, input_raw_file_ids: ["ref"],
  output_paths: [`${scope}/quast/report.html`, `${scope}/quast/icarus.html`, `${scope}/quast/report.tsv`, `${scope}/quast/icarus_viewers/contig_size_viewer.html`],
  status, started_at: null, finished_at: "2026-10-28T14:00:00Z", duration_seconds: 3, log_text: "", error_message: null, created_at: "2026-10-28T13:59:00Z",
  commands: [], tool_path: "/opt/arva-tools/quast/bin/quast.py", result_summary: null, parent_job_id: null, qc_results: [], ...extra,
});
const quastTool: Tool = {
  id: "quast", name: "QUAST", description: "", homepage: "", license: "GPL-2.0", citation: "", citation_url: "", categories: [], input_formats: [],
  output_formats: [], min_version: "5.2.0", tested_versions: ["5.2.0"], install: {}, status: "available", path: "/q/quast.py", version: "5.2.0",
  version_validated: true, message: "", reason: null,
};
const fasta = { id: "ref", original_filename: "reference.fasta", file_format: "fasta", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null } as RawFile;
const reads = { ...fasta, id: "f1", original_filename: "ont.fastq.gz", file_format: "fastq_gz" } as RawFile;
const assembly = {
  id: "aaaaaaaa-1111", sample_id: "s", job_id: "j1", assembler: "Flye", assembler_version: "2.9.3", mode: "long", read_type: "nano-hq", input_file_ids: ["f1"],
  created_at: "2026-10-28T13:05:00Z", stats: { contig_count: 8, total_length: 338_399 }, warnings: [],
} as unknown as Assembly;

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
  vi.spyOn(api, "tools").mockResolvedValue([quastTool]);
  vi.spyOn(api, "assemblies").mockResolvedValue([]);
});
afterEach(() => vi.restoreAllMocks());

describe("QUAST helpers", () => {
  it("keep output paths below the job folder so QUAST's pages can link to each other", () => {
    expect(jobRelativePath("job-q", `${scope}/quast/icarus_viewers/contig_size_viewer.html`)).toBe("quast/icarus_viewers/contig_size_viewer.html");
    expect(jobRelativePath("other", "results/x/report.tsv")).toBe("report.tsv");
    expect(quastOutput(job("completed"), "icarus.html")).toBe("quast/icarus.html");
    expect(quastOutput(job("completed"), "missing.html")).toBeNull();
    expect(api.jobOutputUrl("job-q", "quast/icarus_viewers/a b.html")).toBe("/api/v1/jobs/job-q/outputs/quast/icarus_viewers/a%20b.html");
  });

  it("format QUAST's values as reported and pick the main rows", () => {
    expect(formatQuastValue({ full: 1, partial: 2 }, "part")).toBe("1 + 2 part");
    expect(formatQuastValue(null, "part")).toBe("—");
    expect(formatQuastValue(286_428.6, "part")).toBe("286,428.6");
    expect(formatQuastValue("n/a", "part")).toBe("n/a");
    expect(reportRows(summary, false).map((r) => r.field)).toEqual(["# contigs (>= 0 bp)", "# contigs", "N50", "Genome fraction (%)", "# unaligned contigs"]);
    expect(reportRows(summary, true)).toHaveLength(7);
  });

  it("check the form before anything is sent", () => {
    const form = { selected: ["a"], referenceId: "", minContig: "500", threads: "" };
    expect(quastProblems(form, undefined)).toEqual([]);
    expect(quastProblems({ ...form, selected: [], minContig: "1.5", threads: "9" }, undefined)).toEqual([
      "quast.problem.assemblies", "quast.problem.minContig", "quast.problem.threads"]);
    const plan = { tool: { max_threads: 4, default_threads: 4, aligner: { provided_by: "missing" } }, assemblies: [{ contigs_kept: 0 }] } as unknown as QuastPlan;
    expect(quastProblems({ ...form, referenceId: "ref" }, plan)).toEqual(["quast.problem.nothingKept", "quast.problem.aligner"]);
    expect(quastRequest({ ...form, referenceId: "ref", threads: "2" })).toEqual({ assembly_ids: ["a"], reference_file_id: "ref", min_contig: 500, threads: 2 });
    expect(referenceCandidates([fasta, reads, { ...fasta, id: "bad", is_valid: false }]).map((f) => f.id)).toEqual(["ref"]);
  });
});

describe("Assembly tab with QUAST", () => {
  it("shows QUAST's values, links to its pages and a cross-check difference without hiding it", async () => {
    renderWith(<AssemblyTab sampleId="s" jobs={[job("completed", { result_summary: summary as unknown as Record<string, unknown> })]} files={[reads, fasta]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("QUAST 5.2.0 · 1 ensamblaje(s) · contigs ≥ 500 pb")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Informe de QUAST/ })).toHaveAttribute("href", "/api/v1/jobs/job-q/outputs/quast/report.html");
    expect(screen.getByRole("link", { name: /Navegador de contigs Icarus/ })).toHaveAttribute("href", "/api/v1/jobs/job-q/outputs/quast/icarus.html");
    expect(screen.getByRole("link", { name: /report\.tsv/ })).toHaveAttribute("href", "/api/v1/jobs/job-q/outputs/quast/report.tsv?download=true");
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getByText("1 + 0 parciales")).toBeInTheDocument();
    expect(within(table).getByText("99.683")).toBeInTheDocument();
    expect(within(table).queryByText("auNA")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Mostrar las 7 métricas de QUAST" }));
    expect(within(table).getByText("auNA")).toBeInTheDocument();
    expect(screen.getByText("1 de 2 métricas coinciden con las de ARVA")).toBeInTheDocument();
    expect(screen.getByText("140,001")).toBeInTheDocument();
    expect(screen.getByText("49.4512")).toBeInTheDocument();
    expect(screen.getByText(/rotado 1000 de 300 000 pb dio un 99,683 %/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Evaluar con QUAST/ })).toBeDisabled();
  });

  it("follows a running evaluation and explains a failed one", async () => {
    const progress = {
      tool: "QUAST", stage: "contig_analyzer", stage_index: 2, stages_total: 5, stages: ["basic_stats", "contig_analyzer", "na_nga", "genome_analyzer", "visual_summaries"],
      started_at: null, stage_started_at: null, updated_at: null, elapsed_seconds: 4, finished: false,
    };
    vi.spyOn(api, "jobLog").mockResolvedValue({ text: "Running Contig analyzer...", source: "tool" });
    const failed = job("failed", { id: "job-f", progress: { ...progress, stage: "basic_stats", finished: true }, error_message: "QUAST left out Flye 2.9.3 aaaaaaaa" });
    renderWith(<AssemblyTab sampleId="s" jobs={[job("running", { progress }), failed]} files={[reads, fasta]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("QUAST 5.2.0 está evaluando")).toBeInTheDocument();
    expect(screen.getAllByText("Ensamblajes: Flye 2.9.3 aaaaaaaa · referencia reference.fasta")).toHaveLength(1);
    expect(screen.getByText("Etapa 2 de 5: contig_analyzer")).toBeInTheDocument();
    expect(screen.getAllByText("contigs alineados contra la referencia (minimap2)").length).toBeGreaterThan(0);
    expect(screen.getByText("QUAST se detuvo durante el paso basic_stats.")).toBeInTheDocument();
    expect(screen.getByText("QUAST 5.2.0: la evaluación falló")).toBeInTheDocument();
  });
});

describe("QUAST dialog", () => {
  it("explains which contigs QUAST leaves out and blocks a run that would skip an assembly", async () => {
    const plan: QuastPlan = {
      tool: { status: "available", version: "5.2.0", version_validated: true, message: "", reason: null,
        aligner: { provided_by: "path", executable: "/usr/bin/minimap2", version: "2.26-r1175" }, max_threads: 4, default_threads: 4, default_min_contig: 500 },
      min_contig: 500,
      assemblies: [{ assembly_id: assembly.id, label: "Flye 2.9.3 aaaaaaaa", assembler: "Flye", assembler_version: "2.9.3", read_type: "nano-hq",
        created_at: assembly.created_at, contigs: 8, total_length: 338_399, contigs_kept: 6, length_kept: 337_500, contigs_left_out: 2, length_left_out: 899 }],
      reference: null,
    };
    const preview = vi.spyOn(api, "quastPreview").mockResolvedValue(plan);
    renderWith(<QuastDialog open onOpenChange={() => undefined} sampleId="s" assemblies={[assembly]} files={[reads, fasta]} />);
    expect(await screen.findByText(/6 de 8 contigs tienen al menos 500 pb; QUAST deja los otros 2 \(899 bp\) fuera/)).toBeInTheDocument();
    expect(preview).toHaveBeenCalledWith("s", { assembly_ids: [assembly.id], reference_file_id: null, min_contig: 500 });
    expect((screen.getByRole("spinbutton", { name: /Longitud mínima de contig/ }) as HTMLInputElement).value).toBe("500");
    expect(screen.getByRole("option", { name: "reference.fasta" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "ont.fastq.gz" })).toBeNull();
    expect(screen.getByRole("button", { name: /Iniciar la evaluación/ })).toBeEnabled();

    preview.mockResolvedValue({ ...plan, min_contig: 200_000, assemblies: [{ ...plan.assemblies[0], contigs_kept: 0, contigs_left_out: 8 }] });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Longitud mínima de contig/ }), { target: { value: "200000" } });
    expect(await screen.findByText(/Ningún contig llega a 200,000 pb/, {}, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Iniciar la evaluación/ })).toBeDisabled();
  });

  it("takes its default thread count from the performance profile, bounded by the usable CPUs", async () => {
    const plan = {
      tool: { status: "available", version: "5.2.0", version_validated: true, message: "", reason: null,
        aligner: { provided_by: "path", executable: "/usr/bin/minimap2", version: "2.26-r1175" }, max_threads: 8, default_threads: 3, default_min_contig: 500 },
      min_contig: 500,
      assemblies: [{ assembly_id: assembly.id, label: "Flye 2.9.3 aaaaaaaa", assembler: "Flye", assembler_version: "2.9.3", read_type: "nano-hq",
        created_at: assembly.created_at, contigs: 8, total_length: 338_399, contigs_kept: 8, length_kept: 338_399, contigs_left_out: 0, length_left_out: 0 }],
      reference: null,
    } as QuastPlan;
    vi.spyOn(api, "quastPreview").mockResolvedValue(plan);
    renderWith(<QuastDialog open onOpenChange={() => undefined} sampleId="s" assemblies={[assembly]} files={[reads, fasta]} />);
    const threads = await screen.findByRole("spinbutton", { name: /^Hilos/ });
    expect(threads).toHaveAttribute("placeholder", "3");
    expect(threads).toHaveAttribute("max", "8");
    expect(screen.getByText("1–8 en este equipo (vacío: 3, del perfil de rendimiento); QUAST los reparte entre los ensamblajes.")).toBeInTheDocument();
  });
});
