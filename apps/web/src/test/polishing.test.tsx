import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { PolishingDialog } from "@/components/assembly/PolishingDialog";
import { api } from "@/lib/api";
import {
  POLISHING_FORM_DEFAULTS,
  assemblyRows,
  changeSeries,
  indirectRows,
  lineage,
  polishedFrom,
  polishingProblems,
  polishingRequest,
  rolesFor,
  strategyForData,
  trend,
} from "@/lib/polishing";
import { NO_ROLES } from "@/lib/shortReads";
import type { AnalysisJobDetail, Assembly, PolishingPlan, PolishingSummary, RawFile, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" data-option={JSON.stringify(props.option)} />;
  }),
}));

const stats = (total: number): Assembly["stats"] => ({
  contig_count: 2, total_length: total, largest_contig: total - 8_000, smallest_contig: 7_977, n50: total - 8_000, l50: 1, n90: total - 8_000, l90: 1, gc_percent: 49.9,
  n_count: 0, n_per_100kb: 0, length_histogram: [], cumulative: null,
  circularity: { contigs_with_circularity: 2, circular_contigs: 2 },
  coverage: { contigs_with_coverage: 2, length_weighted_median: 30 },
  contig_rows: { stored: 2, total: 2, truncated: false },
  expected_genome_size: { bp: null, status: "not_given", source: null },
  warning_checks: [],
  files: { contigs: { path: "c", sha256: "x", size_bytes: 1 }, graph: null, info: null },
} as unknown as Assembly["stats"]);
const draft: Assembly = {
  id: "draft-0001", sample_id: "s", job_id: "job-flye", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3", mode: "long",
  read_type: "nano-hq", input_file_ids: ["ont"], created_at: "2026-10-28T13:00:00Z", stats: stats(107_998), warnings: [],
};
const polished: Assembly = {
  ...draft, id: "racon-0002", job_id: "job-racon", kind: "polished", parent_assembly_id: "draft-0001", assembler: "Racon", assembler_version: "1.5.0",
  read_type: "map-ont", coverage_kind: "mapped_read_depth", created_at: "2026-10-28T14:00:00Z", stats: stats(107_946),
};
const changes = (snp: number, ins: [number, number], del: [number, number]) => ({
  snp: { events: snp, bases: snp }, insertion: { events: ins[0], bases: ins[1] }, deletion: { events: del[0], bases: del[1] }, other: { events: 0, bases: 0 },
});
const alignment = (nm: number) => ({
  reads: 515, reads_mapped: 515, mapped_percent: 100, reads_properly_paired: 0, properly_paired_percent: null, bases_mapped_cigar: 3_469_534, nm_sum: 136_061,
  edit_distance_per_100_bases: nm, insertion_events: 31_850, deletion_events: 44_412, indel_events_per_100kb: 2198.0,
});
/** The result summary of a real two-round Racon run on ARVA's synthetic draft with 16 known errors. */
const summary: PolishingSummary = {
  polisher: "Racon", polisher_version: "1.5.0", strategy: "racon",
  draft: { assembly_id: "draft-0001", assembler: "Flye", assembler_version: "2.9.3", kind: "assembly" },
  polished_assembly_id: "racon-0002", read_type: "map-ont", rounds_requested: 2, rounds_run: 2,
  rounds: [
    { round: 1, changes: changes(7, [3, 5], [4, 5]), changes_source: "dnadiff" },
    { round: 2, changes: changes(0, [2, 2], [0, 0]), changes_source: "dnadiff" },
  ],
  direct: {
    source: "dnadiff",
    dnadiff: {
      before: { sequences: 2, aligned_sequences: 2, unaligned_sequences: 0, bases: 107_998, aligned_bases: 107_944, unaligned_bases: 54, one_to_one_identity: 99.98, breakpoints: 4, substituted_bases: 7, indel_bases: 12 },
      after: { sequences: 2, aligned_sequences: 2, unaligned_sequences: 0, bases: 107_946, aligned_bases: 107_946, unaligned_bases: 0, one_to_one_identity: 99.98, breakpoints: 0, substituted_bases: 7, indel_bases: 12 },
      events: { substitutions: 7, insertions: 5, inserted_bases: 7, deletions: 4, deleted_bases: 5 },
      ends: [{ contig: "contig_1", length: 99_999, unaligned_start: 8, unaligned_end: 23 }],
    },
    pilon_changes: null,
  },
  indirect: { aligner: "minimap2 2.26-r1175 -x map-ont", reads: "long", before: { stats: alignment(3.9216), coverage: [] }, after: { stats: alignment(3.9049), coverage: [] } },
  assembly_stats: {
    before: { contig_count: 2, total_length: 107_998, largest_contig: 99_999, n50: 99_999, l50: 1, gc_percent: 49.9, n_count: 0 },
    after: { contig_count: 2, total_length: 107_946, largest_contig: 99_969, n50: 99_969, l50: 1, gc_percent: 49.9, n_count: 0 },
  },
  observations: [{ code: "ends_trimmed", params: { contig: "contig_1", start: 8, end: 23, circular: true }, message: "…" }],
  helpers: [{ name: "minimap2", version: "2.26-r1175", path: "/usr/bin/minimap2" }, { name: "MUMmer dnadiff", version: "1.3", path: "/usr/bin/dnadiff" }],
  followups: {},
};
const job = (extra: Partial<AnalysisJobDetail>): AnalysisJobDetail => ({
  id: "job-racon", project_id: "p", sample_id: "s", job_type: "racon_polish", tool_name: "Racon", tool_version: "1.5.0", database_name: null, database_version: null,
  parameters: { draft: { assembly_id: "draft-0001", assembler: "Flye", assembler_version: "2.9.3" } }, input_raw_file_ids: ["ont"],
  output_paths: ["results/p/s/job-racon/polished.fasta", "results/p/s/job-racon/comparison/dnadiff_overall.report"], status: "completed",
  started_at: null, finished_at: "2026-10-28T14:00:00Z", duration_seconds: 7, log_text: "", error_message: null, created_at: "2026-10-28T13:59:00Z",
  commands: [], tool_path: null, result_summary: summary as unknown as Record<string, unknown>, parent_job_id: null, qc_results: [], ...extra,
});
const ont = { id: "ont", original_filename: "ont.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null, produced_by_job_id: null, header_metadata: { suggested_technology: { value: "nanopore", confidence: "high" } } } as unknown as RawFile;
const r1 = { ...ont, id: "r1", original_filename: "ill_R1.fastq.gz", read_mate: "R1", header_metadata: null } as RawFile;
const r2 = { ...ont, id: "r2", original_filename: "ill_R2.fastq.gz", read_mate: "R2", header_metadata: null } as RawFile;
const tool = (id: string) => ({ status: "available" as const, version: id === "racon" ? "1.5.0" : "1", version_validated: true, message: "", reason: null, path: `/usr/bin/${id}` });
const plan: PolishingPlan = {
  draft: { assembly_id: "draft-0001", kind: "assembly", assembler: "Flye", assembler_version: "2.9.3", mode: "long", read_type: "nano-hq", parent_assembly_id: null, contig_count: 2, total_length: 107_998, n50: 99_999, circular_contigs: 2, created_at: "2026-10-28T13:00:00Z" },
  tools: { racon: tool("racon"), minimap2: tool("minimap2"), pilon: tool("pilon"), java: tool("java"), bwa: tool("bwa"), samtools: tool("samtools"), dnadiff: tool("dnadiff") },
  strategies_available: ["racon", "pilon", "hybrid"], files: [], strategy: "racon", suggested_strategy: "racon",
  preset_suggestion: { heuristic: true, value: "map-ont", basis: "nanopore reads", flye_read_type: "nano-hq", platform: "nanopore" },
  problem: null, sample_technology: "nanopore", confirmation_required: false, max_threads: 4, max_memory_gb: 32, default_heap_gb: 16,
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
  vi.spyOn(api, "tools").mockResolvedValue([{ id: "quast", status: "not_installed" } as Tool]);
});
afterEach(() => vi.restoreAllMocks());

describe("polishing helpers", () => {
  it("chooses the strategy from the reads and keeps only the roles it uses", () => {
    expect(strategyForData({ short: false, long: true })).toBe("racon");
    expect(strategyForData({ short: true, long: false })).toBe("pilon");
    expect(strategyForData({ short: true, long: true })).toBe("hybrid");
    expect(strategyForData({ short: false, long: false })).toBeNull();
    const all = { r1: "a", r2: "b", unpaired: "c", long: "d" };
    expect(rolesFor("racon", all)).toEqual({ r1: "", r2: "", unpaired: "", long: "d" });
    expect(rolesFor("pilon", all)).toEqual({ r1: "a", r2: "b", unpaired: "c", long: "" });
  });

  it("lists what blocks a request and builds it with every setting explicit", () => {
    expect(polishingProblems(POLISHING_FORM_DEFAULTS, NO_ROLES, plan, false)).toEqual(["polishing.problem.long", "polishing.problem.preset"]);
    const racon = { ...POLISHING_FORM_DEFAULTS, preset: "map-ont" as const };
    expect(polishingProblems(racon, { ...NO_ROLES, long: "ont" }, plan, false)).toEqual([]);
    expect(polishingProblems({ ...racon, gap: "2" }, { ...NO_ROLES, long: "ont" }, plan, false)).toEqual(["polishing.problem.racon"]);
    const pilon = { ...POLISHING_FORM_DEFAULTS, strategy: "pilon" as const, heap: "64" };
    expect(polishingProblems(pilon, { ...NO_ROLES, r1: "r1" }, { ...plan, strategies_available: ["racon"] }, false)).toEqual([
      "shortReads.problem.pair", "polishing.problem.heap", "polishing.problem.tools"]);
    const request = polishingRequest({ ...racon, strategy: "hybrid", fix: ["indels", "snps"], pilonRounds: "2" }, { r1: "r1", r2: "r2", unpaired: "", long: "ont" }, true);
    expect(request.inputs).toEqual({ r1_file_id: "r1", r2_file_id: "r2", unpaired_file_id: null, long_file_id: "ont" });
    expect(request.racon).toEqual({ read_type: "map-ont", rounds: 1, match: 3, mismatch: -5, gap: -4, window_length: 500, quality_threshold: 10, error_threshold: 0.3 });
    expect(request.pilon).toEqual({ rounds: 2, fix: ["snps", "indels"], mindepth: 0.1, minmq: 0, minqual: 0, heap_gb: null, stop_when_unchanged: true });
    expect(request.reads_confirmed).toBe(true);
  });

  it("charts the changes per round, compares the reads' agreement and follows the lineage", () => {
    expect(changeSeries(summary).map((r) => r.values)).toEqual([
      { snp: 7, insertion: 3, deletion: 4, other: 0 },
      { snp: 0, insertion: 2, deletion: 0, other: 0 },
    ]);
    const rows = indirectRows(summary);
    expect(rows.map((r) => [r.key, trend(r)])).toEqual([["mapped", "same"], ["nm", "improved"], ["indels", "same"]]);
    expect(trend({ ...rows[1], before: 3.9, after: 4.1 })).toBe("worse");
    expect(assemblyRows(summary).find((r) => r.key === "total_length")).toMatchObject({ before: 107_998, after: 107_946 });
    const second = { ...polished, id: "pilon-0003", parent_assembly_id: "racon-0002", assembler: "Pilon" };
    expect(lineage(second, [draft, polished, second]).map((a) => a.id)).toEqual(["draft-0001", "racon-0002", "pilon-0003"]);
    expect(polishedFrom(draft, [draft, polished, second]).map((a) => a.id)).toEqual(["racon-0002"]);
  });
});

describe("Polishing results", () => {
  it("separates direct evidence from indirect indicators, charts the rounds and shows the lineage", async () => {
    vi.spyOn(api, "assemblies").mockResolvedValue([polished, draft]);
    vi.spyOn(api, "assembly").mockResolvedValue({ ...polished, contigs: [] });
    renderWith(<AssemblyTab sampleId="s" jobs={[job({})]} files={[ont]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    const card = (await screen.findByText(/Racon 1\.5\.0 · polished Flye 2\.9\.3/)).closest("div.rounded-xl, section, article") ?? document.body;
    const scope = within(card as HTMLElement);
    expect(scope.getByText("direct evidence")).toBeInTheDocument();
    expect(scope.getByText("indirect indicator")).toBeInTheDocument();
    expect(scope.getByText("Substituted bases (SNPs)").nextSibling).toHaveTextContent("7");
    expect(scope.getByText("Draft bases missing from the polished assembly").nextSibling).toHaveTextContent("54 bp");
    expect(scope.getByText(/contig_1: 8 bp at the start and 23 bp at the end.*circular/)).toBeInTheDocument();
    expect(scope.getByText(/A change is not necessarily a correction/)).toBeInTheDocument();
    const nm = scope.getByText(/Edit distance per 100 aligned bases/).closest("tr")!;
    expect(within(nm).getByText("better")).toBeInTheDocument();
    const options = screen.getAllByTestId("chart").map((c) => JSON.parse(c.dataset.option!));
    const option = options.find((o) => o.series?.[0]?.name === "SNP");
    expect(option.series.map((s: { name: string; data: number[] }) => [s.name, s.data])).toEqual([
      ["SNP", [7, 0]], ["Insertion", [3, 2]], ["Deletion", [4, 0]], ["Other", [0, 0]]]);
    expect(screen.getByText(/Polished from Flye 2\.9\.3/)).toBeInTheDocument();
    expect(screen.getByText(/Polished versions: Racon 1\.5\.0/)).toBeInTheDocument();
  });

  it("says when there is no direct evidence and translates the results", async () => {
    useSettings.setState({ language: "es" });
    const noDiff = { ...summary, rounds: summary.rounds.map((r) => ({ ...r, changes: null, changes_source: null })), direct: { source: null, dnadiff: null, pilon_changes: null }, observations: [] };
    vi.spyOn(api, "assemblies").mockResolvedValue([polished, draft]);
    vi.spyOn(api, "assembly").mockResolvedValue({ ...polished, contigs: [] });
    renderWith(<AssemblyTab sampleId="s" jobs={[job({ result_summary: noDiff as unknown as Record<string, unknown> })]} files={[ont]} onNew={() => undefined} onEvaluate={() => undefined} onPolish={() => undefined} />);
    expect(await screen.findByText(/No hay evidencia directa: MUMmer dnadiff no estaba instalado/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pulido" })).toBeInTheDocument();
    expect(screen.queryByText("Cambios por tipo y ronda")).not.toBeInTheDocument();
  });
});

describe("Polishing dialog", () => {
  it("suggests the strategy and read type, and sends the request the summary describes", async () => {
    const preview = vi.spyOn(api, "polishingPreview").mockResolvedValue(plan);
    const polish = vi.spyOn(api, "polish").mockResolvedValue(job({ status: "pending" }));
    renderWith(<PolishingDialog open onOpenChange={() => undefined} sampleId="s" technology="nanopore" assemblies={[draft]} files={[ont, r1, r2]} jobs={[]} draftId="draft-0001" />);
    expect(await screen.findByRole("radio", { name: /Hybrid: Racon, then Pilon/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /Long reads: Racon/ }));
    expect(screen.getByRole("radio", { name: /Long reads: Racon/ })).toBeChecked();
    expect(screen.getByText(/Medaka .* is not integrated yet/)).toBeInTheDocument();
    expect(screen.queryByText(/What Pilon may fix/)).not.toBeInTheDocument();
    await waitFor(() => expect(preview.mock.calls.at(-1)![1].inputs.r1_file_id).toBeNull());
    expect(preview.mock.calls.at(-1)![1].inputs.long_file_id).toBe("ont");
    const run = screen.getByRole("button", { name: "Polish" });
    expect(run).toBeDisabled();
    fireEvent.click(await screen.findByRole("button", { name: "Use suggestion" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Polish" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Polish" }));
    await waitFor(() => expect(polish).toHaveBeenCalled());
    const [draftId, body] = polish.mock.calls[0];
    expect(draftId).toBe("draft-0001");
    expect(body.strategy).toBe("racon");
    expect(body.racon.read_type).toBe("map-ont");
    expect(body.inputs).toEqual({ r1_file_id: null, r2_file_id: null, unpaired_file_id: null, long_file_id: "ont" });

    fireEvent.click(screen.getByRole("radio", { name: /Short reads: Pilon/ }));
    expect(await screen.findByText(/What Pilon may fix/)).toBeInTheDocument();
    expect(screen.getByLabelText(/R1/)).toBeInTheDocument();
  });
});
