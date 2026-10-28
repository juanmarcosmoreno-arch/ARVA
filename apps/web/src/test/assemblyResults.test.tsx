import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { AssemblyDialog } from "@/components/assembly/AssemblyDialog";
import { ProjectAssemblies } from "@/components/domain/ProjectAssemblies";
import { api } from "@/lib/api";
import { compared, cumulativePoints, elapsedSeconds, lineageNames, nodeKind, nodeSize, nxSteps, segmentCoverage, selfLinks, sortContigs } from "@/lib/assembly";
import { FLYE_FORM_DEFAULTS, advancedFlags } from "@/lib/flye";
import type { AnalysisJobDetail, Assembly, AssemblyContig, AssemblyDetail, AssemblyGraph, FlyePlan, ProjectAssembly, RawFile, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

// ECharts needs a real layout engine; the stub exposes the option each chart would draw.
vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown; "aria-label"?: string }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" aria-label={props["aria-label"]} data-option={JSON.stringify(props.option)} />;
  }),
}));

const contig = (rank: number, name: string, length: number, extra: Partial<AssemblyContig> = {}): AssemblyContig => ({
  rank, name, length, gc_percent: 50, n_count: 0, other_iupac_count: 0, coverage: 30, circular: false, repeat: false, ...extra,
});
const CONTIGS = [
  contig(1, "contig_1", 300_000, { coverage: 31, circular: true, gc_percent: 49.8 }),
  contig(2, "contig_2", 15_000, { coverage: 53, circular: true, gc_percent: 45.4 }),
  contig(3, "contig_3", 5_000, { coverage: null, circular: null, repeat: true, gc_percent: null }),
];
const stats = (n50: number): Assembly["stats"] => ({
  contig_count: 3, total_length: 320_000, largest_contig: 300_000, smallest_contig: 5_000, n50, l50: 1, n90: 300_000, l90: 1, gc_percent: 49.6,
  n_count: 0, n_per_100kb: 0,
  length_histogram: [
    { min_length: 5_000, max_length: 10_000, contigs: 1, total_length: 5_000 },
    { min_length: 10_000, max_length: 20_000, contigs: 1, total_length: 15_000 },
    { min_length: 200_000, max_length: 500_000, contigs: 1, total_length: 300_000 },
  ],
  cumulative: { rank: [1, 2, 3], length: [300_000, 15_000, 5_000], cumulative_length: [300_000, 315_000, 320_000], downsampled: false },
  circularity: { contigs_with_circularity: 2, circular_contigs: 2 },
  coverage: { contigs_with_coverage: 2, length_weighted_median: 31 },
  contig_rows: { stored: 3, total: 3, truncated: false },
  expected_genome_size: { bp: null, status: "not_given", source: null },
  warning_checks: [
    { code: "genome_size_mismatch", rule: "", evaluated: false, skipped_reason: "no expected genome size is known for this sample" },
    { code: "gc_outlier_contigs", rule: "", evaluated: false, skipped_reason: "fewer than two contigs are long enough" },
  ],
  files: { contigs: { path: "c", sha256: "x", size_bytes: 1 }, graph: { path: "g", sha256: "y", size_bytes: 1 }, info: null },
});
const assembly = (id: string, created: string, n50 = 300_000): Assembly => ({
  id, sample_id: "s", job_id: `job-${id}`, kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3", mode: "long", read_type: "nano-hq",
  input_file_ids: ["f2"], created_at: created, stats: stats(n50), warnings: [],
});
const original = { id: "f1", original_filename: "ont.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null, produced_by_job_id: null } as RawFile;
const filtered = { id: "f2", original_filename: "ont.filtlong.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "derived", parent_file_id: "f1", produced_by_job_id: "jf" } as RawFile;
const flyeTool = { id: "flye", status: "available", version: "2.9.3" } as Tool;
const job = (extra: Partial<AnalysisJobDetail>): AnalysisJobDetail => ({
  id: "j", project_id: "p", sample_id: "s", job_type: "flye_assembly", tool_name: "Flye", tool_version: "2.9.3", database_name: null, database_version: null,
  parameters: {}, input_raw_file_ids: ["f2"], output_paths: [], status: "completed", started_at: null, finished_at: null, duration_seconds: null, log_text: "",
  error_message: null, created_at: "2026-10-28T13:00:00Z", commands: [], tool_path: null, result_summary: null, parent_job_id: null, qc_results: [], ...extra,
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
  vi.spyOn(api, "tools").mockResolvedValue([flyeTool]);
});
afterEach(() => vi.restoreAllMocks());

describe("assembly helpers", () => {
  it("sorts contigs by any column, keeping missing values last and ties in length order", () => {
    expect(sortContigs(CONTIGS, "coverage", "desc").map((c) => c.name)).toEqual(["contig_2", "contig_1", "contig_3"]);
    expect(sortContigs(CONTIGS, "coverage", "asc").map((c) => c.name)).toEqual(["contig_1", "contig_2", "contig_3"]);
    expect(sortContigs(CONTIGS, "name", "desc").map((c) => c.name)).toEqual(["contig_3", "contig_2", "contig_1"]);
    expect(sortContigs(CONTIGS, "circular", "desc").map((c) => c.name)).toEqual(["contig_1", "contig_2", "contig_3"]);
  });

  it("draws the Nx curve as one step per contig and the cumulative curve by rank", () => {
    const curve = stats(1).cumulative!;
    const steps = nxSteps(curve, 320_000);
    expect(steps[0]).toEqual([0, 300_000]);
    expect(steps[1]).toEqual([93.75, 300_000]);
    expect(steps.at(-1)).toEqual([100, 5_000]);
    expect(cumulativePoints(curve)).toEqual([[1, 300_000], [2, 315_000], [3, 320_000]]);
  });

  it("colours graph segments from their contigs' flags and sizes them by length", () => {
    expect(nodeKind({ circular: true, repeat: true, paths: ["a"] })).toBe("circular");
    expect(nodeKind({ circular: false, repeat: true, paths: ["a"] })).toBe("repeat");
    expect(nodeKind({ circular: false, repeat: null, paths: ["a"] })).toBe("other");
    expect(nodeKind({ circular: null, repeat: null, paths: [] })).toBe("unknown");
    expect(nodeSize(100, 100)).toBe(40);
    expect(nodeSize(25, 100)).toBe(23);
    expect(segmentCoverage({ coverage_tag: "dp" }, { tags: { dp: 52 } })).toBe(52);
    expect(segmentCoverage({ coverage_tag: null }, { tags: { dp: 52 } })).toBeNull();
    const edge = { source_orientation: "+" as const, target_orientation: "+" as const, overlap: "0M", tags: {} };
    expect(selfLinks({ edges: [{ ...edge, source: "a", target: "a" }, { ...edge, source: "a", target: "b" }] })).toEqual(new Map([["a", ["+→+"]]]));
  });

  it("measures elapsed time live while running and uses the recorded duration afterwards", () => {
    const now = Date.parse("2026-10-28T13:02:05Z");
    expect(elapsedSeconds({ status: "running", started_at: "2026-10-28T13:00:00Z", duration_seconds: null, progress: null }, now)).toBe(125);
    expect(elapsedSeconds({ status: "completed", started_at: "2026-10-28T13:00:00Z", duration_seconds: 99, progress: null }, now)).toBe(99);
    expect(elapsedSeconds({ status: "pending", started_at: null, duration_seconds: null, progress: null }, now)).toBeNull();
  });

  it("names a file's lineage back to the original and lists the advanced Flye options set", () => {
    expect(lineageNames(filtered, [original, filtered])).toEqual(["ont.filtlong.fastq.gz", "ont.fastq.gz"]);
    expect(advancedFlags(FLYE_FORM_DEFAULTS)).toEqual([]);
    expect(advancedFlags({ ...FLYE_FORM_DEFAULTS, minOverlap: " 3000 ", meta: true })).toEqual(["--min-overlap 3000", "--meta"]);
    const many = Array.from({ length: 8 }, (_, i) => assembly(`a${i}`, `2026-10-2${i}T00:00:00Z`));
    expect(compared(many).map((a) => a.id)).toEqual(["a7", "a6", "a5", "a4", "a3", "a2"]);
  });
});

describe("Assembly results", () => {
  it("shows every summary tile, sorts the contig table and draws the five charts", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([assembly("a1", "2026-10-28T13:05:00Z")]);
    vi.spyOn(api, "assembly").mockResolvedValue({ ...assembly("a1", "2026-10-28T13:05:00Z"), contigs: CONTIGS } as AssemblyDetail);
    renderWith(<AssemblyTab sampleId="s" jobs={[job({ id: "job-a1" })]} files={[original, filtered]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("Reads: ont.filtlong.fastq.gz ← ont.fastq.gz", { exact: false })).toBeInTheDocument();
    for (const label of ["Contigs", "Total length", "Largest contig", "Contig N50", "L50", "Contig N90", "L90", "GC content", "Circular contigs", "Median coverage"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Not checked — contigs with unusual GC: fewer than two contigs of at least 1,000 bp.")).toBeInTheDocument();

    const table = await screen.findByRole("table");
    const names = () => within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[1].textContent);
    expect(names()).toEqual(["contig_1", "contig_2", "contig_3"]);
    // Flye's coverage is a read depth, and the column says so.
    fireEvent.click(within(table).getByRole("button", { name: "Read depth" }));
    expect(names()).toEqual(["contig_2", "contig_1", "contig_3"]);
    expect(within(table).getByRole("columnheader", { name: /Read depth/ })).toHaveAttribute("aria-sort", "descending");
    expect(within(table).getAllByText("circular")).toHaveLength(2);
    expect(within(table).getByText("repeat")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Charts" }));
    const charts = await screen.findAllByTestId("chart");
    expect(charts.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Contig length distribution",
      "Nx curve (sorted contig lengths)",
      "Cumulative assembly length",
      "Coverage versus length",
      "GC versus coverage",
    ]);
    const nx = JSON.parse(charts[1].getAttribute("data-option")!);
    expect(nx.series[0].markLine.data.map((d: { name: string }) => d.name)).toEqual(["N50 300,000 bp", "N90 300,000 bp"]);
    const scatter = JSON.parse(charts[3].getAttribute("data-option")!);
    // contig_3 has no coverage, so only the circular group is drawn; the tooltip names each contig.
    expect(scatter.series.map((s: { name: string }) => s.name)).toEqual(["Circular"]);
    expect(scatter.series[0].data.map((d: { name: string }) => d.name)).toEqual(["contig_1", "contig_2"]);
  });

  it("explores the assembly graph with its truncation notice and self-links", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([assembly("a1", "2026-10-28T13:05:00Z")]);
    vi.spyOn(api, "assembly").mockResolvedValue({ ...assembly("a1", "2026-10-28T13:05:00Z"), contigs: CONTIGS } as AssemblyDetail);
    const graph: AssemblyGraph = {
      assembly_id: "a1", assembler: "Flye", coverage_tag: "dp", coverage_meaning: "mean read depth", format: "GFA1", version: "1.0", segment_count: 900,
      link_count: 1200, path_count: 3, dangling_links: 0, total_segment_length: 320_000, numeric_tags: ["dp"], max_nodes: 500, max_edges: 2000, truncated: true,
      nodes: [
        { id: "edge_1", length: 300_000, tags: { dp: 31 }, paths: ["contig_1"], circular: true, repeat: false },
        { id: "edge_9", length: 5_000, tags: { dp: 90 }, paths: [], circular: null, repeat: null },
      ],
      edges: [
        { source: "edge_1", source_orientation: "+", target: "edge_1", target_orientation: "+", overlap: "0M", tags: { RC: 12 } },
        { source: "edge_1", source_orientation: "+", target: "edge_9", target_orientation: "-", overlap: "0M", tags: {} },
      ],
    };
    const fetchGraph = vi.spyOn(api, "assemblyGraph").mockResolvedValue(graph);
    renderWith(<AssemblyTab sampleId="s" jobs={[]} files={[original, filtered]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    fireEvent.click(await screen.findByRole("radio", { name: "Assembly graph" }));
    const chart = await screen.findByTestId("chart");
    expect(fetchGraph).toHaveBeenCalledWith("a1", 500, 2000);
    const option = JSON.parse(chart.getAttribute("data-option")!);
    const series = option.series[0];
    expect(series.type).toBe("graph");
    expect(series.roam).toBe(true);
    expect(series.data.map((d: { id: string; category: number }) => [d.id, d.category])).toEqual([["edge_1", 0], ["edge_9", 3]]);
    // The self-link is listed, not drawn.
    expect(series.edges.map((e: { source: string; target: string }) => `${e.source}-${e.target}`)).toEqual(["edge_1-edge_9"]);
    expect(screen.getByText(/showing the 2 longest of 900 segments and 2 links among them \(the graph has 1,200\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 segment\(s\) are linked to themselves/)).toBeInTheDocument();
    expect(screen.getByText("Coverage is Flye's GFA tag dp (mean read depth).")).toBeInTheDocument();
  });

  it("compares two or more assemblies in a table and overlaid cumulative curves", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([assembly("bbbbbbbb2", "2026-10-28T14:00:00Z", 150_000), assembly("aaaaaaaa1", "2026-10-28T13:00:00Z")]);
    vi.spyOn(api, "assembly").mockImplementation(async (id) => ({ ...assembly(id, "2026-10-28T13:00:00Z"), contigs: CONTIGS }) as AssemblyDetail);
    renderWith(<AssemblyTab sampleId="s" jobs={[]} files={[original, filtered]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("Comparison of 2 assemblies")).toBeInTheDocument();
    const row = screen.getByRole("rowheader", { name: "Contig N50" }).closest("tr")!;
    expect(within(row).getAllByRole("cell").map((c) => c.textContent)).toEqual(["150,000 bp", "300,000 bp"]);
    const overlay = screen.getByLabelText("Cumulative length of each assembly");
    const option = JSON.parse(overlay.getAttribute("data-option")!);
    expect(option.series.map((s: { name: string }) => s.name)).toEqual(["Flye 2.9.3 · nano-hq · bbbbbbbb", "Flye 2.9.3 · nano-hq · aaaaaaaa"]);
    expect(option.series[0].lineStyle.color).not.toBe(option.series[1].lineStyle.color);
  });

  it("follows a running job's log and can pause it", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([]);
    const log = vi.spyOn(api, "jobLog").mockResolvedValue({ text: "INFO: >>>STAGE: assembly", source: "tool" });
    const running = job({ id: "jr", status: "running", started_at: new Date(Date.now() - 65_000).toISOString() });
    renderWith(<AssemblyTab sampleId="s" jobs={[running]} files={[original, filtered]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText("INFO: >>>STAGE: assembly")).toBeInTheDocument();
    expect(log).toHaveBeenCalledWith("jr", 200);
    expect(screen.getByText(/1 min \d+ s elapsed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByRole("button", { name: "Resume" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Paused: the log is neither refreshed nor scrolled/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel job" })).toBeInTheDocument();
  });
});

describe("New assembly dialog", () => {
  const plan: FlyePlan = {
    tool: { status: "available", version: "2.9.3", version_validated: true, message: "", reason: null, options: ["--genome-size", "--meta", "--asm-coverage", "--read-error"], max_threads: 4 },
    files: [
      { file_id: "f1", name: "ont.fastq.gz", origin: "imported", header_platform: null, header_confidence: "none", basecall_models: [], pacbio_read_types: [], stats_job_id: "j", total_bases: 9_000_000, max_read_length: 45_000, read_n50: 8_700, mean_base_quality: 13.9 },
      { file_id: "f2", name: "ont.filtlong.fastq.gz", origin: "derived", header_platform: null, header_confidence: "none", basecall_models: [], pacbio_read_types: [], stats_job_id: "j", total_bases: 6_000_000, max_read_length: 45_000, read_n50: 9_900, mean_base_quality: 15.0 },
    ],
    read_type_suggestion: { heuristic: true, value: "nano-hq", basis: "error_at_most_5_percent", platform: "nanopore", platform_source: "sample_metadata", mean_error_rate: 0.04, mean_base_quality: 14, q20_read_error_note: false, sup_model_but_low_quality: false },
    genome_size: { expected: { bp: null, status: "not_given", source: null }, total_read_bases: 9_000_000, files_without_stats: [], from_depth: null },
    sample_technology: "nanopore",
    long_reads_confirmation_required: false,
  };
  const filtlongJob = job({ id: "jf", job_type: "filtlong", tool_name: "Filtlong", tool_version: "0.2.1" });

  it("explains the assembler, shows the reads by lineage, summarises the run and starts it only after confirmation", async () => {
    vi.spyOn(api, "flyePreview").mockResolvedValue(plan);
    const run = vi.spyOn(api, "runFlye").mockResolvedValue(job({}));
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[original, filtered]} jobs={[filtlongJob]} technology="nanopore" />);
    expect(await screen.findByText("New assembly")).toBeInTheDocument();
    // Every assembler is offered; the one that fits these long reads is chosen and marked.
    const assemblers = screen.getByRole("radiogroup", { name: "Assembler" });
    expect(within(assemblers).getByRole("radio", { name: /Flye · long reads/ })).toBeChecked();
    expect(within(assemblers).getByRole("radio", { name: /SPAdes · short reads/ })).not.toBeChecked();
    expect(within(assemblers).getByRole("radio", { name: /Unicycler · short, long or hybrid/ })).not.toBeChecked();
    expect(within(assemblers).getAllByText("fits these reads")).toHaveLength(1);
    expect(screen.getByText(/This sample has long reads \(technology: Oxford Nanopore\): Flye assembles them/)).toBeInTheDocument();

    const files = screen.getByRole("list", { name: "Reads to assemble" });
    expect(within(files).getByText("filtered with Filtlong 0.2.1")).toBeInTheDocument();
    expect(within(files).getByText("from ont.fastq.gz")).toBeInTheDocument();
    // Advanced options are collapsed.
    expect(screen.getByText("Advanced Flye options").closest("details")).not.toHaveAttribute("open");

    fireEvent.change(screen.getByRole("combobox", { name: "Read type" }), { target: { value: "nano-hq" } });
    const summary = await screen.findByRole("region", { name: "What this run will do" });
    expect(within(summary).getByText("Reads: 1 file(s), 9.00 Mbp in total — ont.fastq.gz.")).toBeInTheDocument();
    expect(within(summary).getByText("Read type: --nano-hq (Flye's error model for these reads).")).toBeInTheDocument();
    expect(within(summary).getByText("Threads: 4. With more than one thread, runs on the same reads can differ.")).toBeInTheDocument();
    expect(within(summary).getByText("Advanced options: none (Flye's defaults).")).toBeInTheDocument();

    const start = screen.getByRole("button", { name: /Start assembly/ });
    expect(start).toBeDisabled();
    const confirm = screen.getByRole("checkbox", { name: /I have reviewed what this run will do/ });
    fireEvent.click(confirm);
    expect(start).toBeEnabled();
    // Changing a setting clears the confirmation.
    fireEvent.click(screen.getByRole("checkbox", { name: /metagenome/ }));
    expect(screen.getByRole("checkbox", { name: /I have reviewed/ })).not.toBeChecked();
    expect(within(summary).getByText("Advanced options: --meta.")).toBeInTheDocument();
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I have reviewed/ }));
    fireEvent.click(start);
    await vi.waitFor(() => expect(run).toHaveBeenCalled());
    expect(run.mock.calls[0][1]).toMatchObject({ raw_file_ids: ["f1"], params: { read_type: "nano-hq", meta: true, iterations: 1 }, long_reads_confirmed: false });
  });

  it("says when the files do not show which reads they hold", async () => {
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[]} technology="illumina" />);
    expect(await screen.findByText(/ARVA cannot tell short from long reads among this sample's files \(technology: Illumina\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start assembly/ })).toBeDisabled();
  });
});

describe("Project assemblies", () => {
  it("lists every assembly with a link to its sample", async () => {
    const row: ProjectAssembly = {
      id: "a1", sample_id: "s1", sample_code: "ISO-1", job_id: "j", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3", mode: "long", read_type: "nano-hq",
      contig_count: 2, total_length: 315_000, largest_contig: 300_000, n50: 300_000, l50: 1, gc_percent: 49.6, circular_contigs: 2, contigs_with_circularity: 2,
      median_coverage: 31, warning_codes: ["high_coverage_contigs"], created_at: "2026-10-28T13:05:00Z",
    };
    vi.spyOn(api, "projectAssemblies").mockResolvedValue([row]);
    renderWith(<ProjectAssemblies projectId="p" />);
    expect(await screen.findByText("Assemblies (1)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ISO-1" })).toHaveAttribute("href", "/samples/s1?tab=assembly");
    expect(screen.getByText("315.0 kbp")).toBeInTheDocument();
    expect(screen.getByText("1 heuristic")).toHaveAttribute("title", "high_coverage_contigs");
  });

  it("renders nothing when the project has no assembly", async () => {
    const spy = vi.spyOn(api, "projectAssemblies").mockResolvedValue([]);
    const { container } = renderWith(<ProjectAssemblies projectId="p" />);
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
