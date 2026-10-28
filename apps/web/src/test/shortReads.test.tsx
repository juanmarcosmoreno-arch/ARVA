import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyComparison } from "@/components/assembly/AssemblyComparison";
import { AssemblyDialog } from "@/components/assembly/AssemblyDialog";
import { AssemblyCard } from "@/components/assembly/AssemblyResult";
import { api } from "@/lib/api";
import { stageStates } from "@/lib/flye";
import {
  NO_ROLES,
  SPADES_FORM_DEFAULTS,
  UNICYCLER_FORM_DEFAULTS,
  availableData,
  defaultRoles,
  fmtCoverage,
  parseKmers,
  recommendedAssemblers,
  spadesProblems,
  spadesRequest,
  unicyclerMode,
  unicyclerProblems,
  unicyclerRequest,
} from "@/lib/shortReads";
import type { AnalysisJob, Assembly, AssemblyDetail, RawFile, ShortReadPlan, UnicyclerPlan } from "@/lib/types";
import { useSettings } from "@/store/settings";

// ECharts needs a real layout engine.
vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { "aria-label"?: string }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" aria-label={props["aria-label"]} />;
  }),
}));

const file = (id: string, name: string, extra: Partial<RawFile> = {}) =>
  ({ id, original_filename: name, file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null, produced_by_job_id: null, header_metadata: null, ...extra }) as RawFile;
const nanoporeHeaders = { suggested_technology: { value: "nanopore", confidence: "high" } } as unknown as RawFile["header_metadata"];
const r1 = file("r1", "iso_S1_R1_001.fastq.gz", { read_mate: "R1" });
const r2 = file("r2", "iso_S1_R2_001.fastq.gz", { read_mate: "R2" });
const other2 = file("x2", "other_R2_001.fastq.gz", { read_mate: "R2" });
const ont = file("ont", "ont.fastq.gz", { header_metadata: nanoporeHeaders });

const tool = { status: "available", version: "3.15.5", version_validated: true, message: "", reason: null, options: ["--isolate", "--careful", "-k", "--cov-cutoff", "-s"], max_threads: 4, max_memory_gb: 16, default_memory_gb: 16 } as const;
const evidence = (id: string, role: "r1" | "r2" | "unpaired" | "long", name: string) => ({
  file_id: id, name, origin: "imported" as const, header_platform: null, header_confidence: "none" as const, basecall_models: [], pacbio_read_types: [], stats_job_id: "j",
  total_bases: 6_000_000, max_read_length: 150, read_n50: 150, mean_base_quality: 35, role, read_mate: role === "r1" ? "R1" : role === "r2" ? "R2" : null, read_count: 40_000,
});
const spadesPlan: ShortReadPlan = {
  tool: { ...tool, options: [...tool.options] },
  files: [evidence("r1", "r1", r1.original_filename), evidence("r2", "r2", r2.original_filename)],
  assembly_mode: "short", read_layout: "paired-end", problem: null, sample_technology: "illumina", confirmation_required: false,
};
const unicyclerPlan: UnicyclerPlan = {
  ...spadesPlan,
  tool: {
    ...tool, version: "0.5.0", options: ["--kmers", "--keep"], modes: ["short", "long", "hybrid"],
    helpers: { spades: { path: "/usr/bin/spades.py", version: "3.15.5" }, racon: { path: "/usr/bin/racon", version: null }, makeblastdb: { path: "/usr/bin/makeblastdb", version: null }, tblastn: { path: "/usr/bin/tblastn", version: null } },
  },
};
const started = { id: "job" } as AnalysisJob;

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
  vi.spyOn(api, "tools").mockResolvedValue([]);
});
afterEach(() => vi.restoreAllMocks());

describe("Which reads a sample has, and which assembler fits", () => {
  it("reads the evidence of mate markers, read headers and technology", () => {
    expect(availableData([r1, r2], "unknown")).toEqual({ short: true, long: false });
    expect(availableData([ont], "unknown")).toEqual({ short: false, long: true });
    expect(availableData([r1, r2, ont], "hybrid")).toEqual({ short: true, long: true });
    expect(availableData([file("u", "reads.fastq.gz")], "nanopore")).toEqual({ short: false, long: true });
    expect(availableData([file("u", "reads.fastq.gz")], "unknown")).toEqual({ short: false, long: false });
    expect(recommendedAssemblers({ short: true, long: true })).toEqual(["unicycler"]);
    expect(recommendedAssemblers({ short: true, long: false })).toEqual(["spades", "unicycler"]);
    expect(recommendedAssemblers({ short: false, long: true })).toEqual(["flye"]);
  });

  it("preselects the R1/R2 pair by name and an imported long-read file", () => {
    expect(defaultRoles([other2, r1, r2, ont], true)).toEqual({ r1: "r1", r2: "r2", unpaired: "", long: "ont" });
    expect(defaultRoles([r1, ont], false)).toEqual(NO_ROLES);
    const filtered = file("f", "ont.filtlong.fastq.gz", { origin: "derived", parent_file_id: "ont", header_metadata: nanoporeHeaders });
    expect(defaultRoles([filtered, ont], true).long).toBe("ont");
    expect(unicyclerMode({ ...NO_ROLES, r1: "a", r2: "b", long: "c" })).toBe("hybrid");
    expect(unicyclerMode({ ...NO_ROLES, unpaired: "a" })).toBe("short");
    expect(unicyclerMode({ ...NO_ROLES, long: "c" })).toBe("long");
  });

  it("parses k-mer sizes only when odd, in range and ascending", () => {
    expect(parseKmers("", 1, 127)).toBeNull();
    expect(parseKmers("21, 33,55", 1, 127)).toEqual([21, 33, 55]);
    for (const bad of ["21,32", "55,33", "21,21", "129", "abc", "9"]) expect(parseKmers(bad, 11, 127)).toBe("invalid");
  });
});

describe("SPAdes and Unicycler forms", () => {
  const roles = { ...NO_ROLES, r1: "r1", r2: "r2" };

  it("lists what keeps a SPAdes run from starting and builds its request", () => {
    expect(spadesProblems(SPADES_FORM_DEFAULTS, roles, spadesPlan, false)).toEqual([]);
    expect(spadesProblems(SPADES_FORM_DEFAULTS, { ...roles, r2: "" }, spadesPlan, false)).toContain("shortReads.problem.pair");
    expect(spadesProblems({ ...SPADES_FORM_DEFAULTS, k: "22" }, roles, spadesPlan, false)).toContain("spades.problem.k");
    expect(spadesProblems({ ...SPADES_FORM_DEFAULTS, memory: "17" }, roles, spadesPlan, false)).toContain("shortReads.problem.memory");
    expect(spadesProblems({ ...SPADES_FORM_DEFAULTS, covCutoff: "value", covValue: "0" }, roles, spadesPlan, false)).toContain("spades.problem.cov");
    expect(spadesProblems(SPADES_FORM_DEFAULTS, roles, { ...spadesPlan, confirmation_required: true }, false)).toContain("shortReads.problem.confirm");
    expect(spadesProblems(SPADES_FORM_DEFAULTS, roles, { ...spadesPlan, problem: "x" }, false)).toContain("shortReads.problem.server");
    expect(spadesRequest({ ...SPADES_FORM_DEFAULTS, k: "21,33", covCutoff: "value", covValue: "2.5", memory: "8", output: "scaffolds" }, roles, true)).toEqual({
      inputs: { r1_file_id: "r1", r2_file_id: "r2", unpaired_file_id: null },
      params: { mode: "isolate", k: [21, 33], cov_cutoff: 2.5, memory_gb: 8, threads: null, output: "scaffolds" },
      reads_confirmed: true,
    });
  });

  it("checks Unicycler's helpers for the mode the roles imply and sends no SPAdes options without short reads", () => {
    const longOnly = { ...NO_ROLES, long: "ont" };
    expect(unicyclerProblems(UNICYCLER_FORM_DEFAULTS, longOnly, unicyclerPlan, false)).toEqual([]);
    const noRacon = { ...unicyclerPlan, tool: { ...unicyclerPlan.tool, modes: ["short" as const] } };
    expect(unicyclerProblems(UNICYCLER_FORM_DEFAULTS, longOnly, noRacon, false)).toContain("unicycler.problem.helpers");
    expect(unicyclerProblems({ ...UNICYCLER_FORM_DEFAULTS, kmers: "9" }, roles, unicyclerPlan, false)).toContain("unicycler.problem.kmers");
    expect(unicyclerProblems({ ...UNICYCLER_FORM_DEFAULTS, kmers: "9" }, longOnly, unicyclerPlan, false)).toEqual([]);
    expect(unicyclerProblems({ ...UNICYCLER_FORM_DEFAULTS, depthFilter: "2" }, roles, unicyclerPlan, false)).toContain("unicycler.problem.depthFilter");
    expect(unicyclerRequest({ ...UNICYCLER_FORM_DEFAULTS, kmers: "27,53", memory: "6" }, longOnly, false).params).toMatchObject({ kmers: null, spades_memory_gb: null, keep: 1 });
    expect(unicyclerRequest({ ...UNICYCLER_FORM_DEFAULTS, kmers: "27,53", memory: "6", keep: "0" }, roles, false).params).toMatchObject({
      kmers: [27, 53], spades_memory_gb: 6, keep: 0, mode: "normal", depth_filter: 0.25, min_fasta_length: 100, linear_seqs: 0,
    });
  });

  it("writes each kind of coverage in its own terms", () => {
    expect(fmtCoverage(31.4, "read_depth")).toBe("31×");
    expect(fmtCoverage(13.419, "kmer_coverage")).toBe("13.4");
    expect(fmtCoverage(2.04, "relative_depth")).toBe("2.04×");
    expect(fmtCoverage(null, "kmer_coverage")).toBe("—");
  });

  it("follows a stage that SPAdes announces twice by its index", () => {
    const stages = ["Before start", "Read error correction", "Read error correction", "Assembling"];
    const states = stageStates({ status: "running", progress: { stage: "Read error correction", stage_index: 3, stages } as never });
    expect(states.map((s) => s.state)).toEqual(["done", "done", "current", "waiting"]);
  });
});

describe("New assembly dialog with short reads", () => {
  it("chooses SPAdes for Illumina pairs, explains it, and starts it with the roles and options shown", async () => {
    vi.spyOn(api, "spadesPreview").mockResolvedValue(spadesPlan);
    const run = vi.spyOn(api, "runSpades").mockResolvedValue(started);
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[r1, r2]} technology="illumina" />);
    expect(await screen.findByText("SPAdes 3.15.5 on this server.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /SPAdes · short reads/ })).toBeChecked();
    expect(screen.getAllByText("fits these reads")).toHaveLength(2);
    expect((screen.getByRole("combobox", { name: "R1 (forward reads of the pairs)" }) as HTMLSelectElement).value).toBe("r1");
    expect((screen.getByRole("combobox", { name: "R2 (reverse reads of the pairs)" }) as HTMLSelectElement).value).toBe("r2");
    expect(screen.getByRole("radio", { name: /--isolate/ })).toBeChecked();
    expect(screen.getByText("Advanced SPAdes options").closest("details")).not.toHaveAttribute("open");
    const summary = screen.getByRole("region", { name: "What this run will do" });
    expect(within(summary).getByText("Mode: --isolate.")).toBeInTheDocument();
    expect(within(summary).getByText(/k-mer sizes: chosen by SPAdes from the read length/)).toBeInTheDocument();
    expect(within(summary).getByText("Threads: 4; memory limit: 16 GB.")).toBeInTheDocument();
    expect(within(summary).getByText(/k-mer coverage \(not read depth\); SPAdes does not report circularity/)).toBeInTheDocument();

    const start = screen.getByRole("button", { name: /Start assembly/ });
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I have reviewed what this run will do/ }));
    fireEvent.click(start);
    await vi.waitFor(() => expect(run).toHaveBeenCalled());
    expect(run.mock.calls[0]).toEqual(["s", {
      inputs: { r1_file_id: "r1", r2_file_id: "r2", unpaired_file_id: null },
      params: { mode: "isolate", k: null, cov_cutoff: "off", memory_gb: null, threads: null, output: "contigs" },
      reads_confirmed: false,
    }]);
  });

  it("queues several strategies at once, one job each", async () => {
    vi.spyOn(api, "spadesPreview").mockResolvedValue(spadesPlan);
    vi.spyOn(api, "unicyclerPreview").mockResolvedValue(unicyclerPlan);
    const runSpades = vi.spyOn(api, "runSpades").mockResolvedValue(started);
    const runUnicycler = vi.spyOn(api, "runUnicycler").mockResolvedValue(started);
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[r1, r2]} technology="illumina" />);
    await screen.findByText("SPAdes 3.15.5 on this server.");
    fireEvent.click(screen.getByRole("checkbox", { name: /Run several strategies/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Unicycler · short, long or hybrid/ }));
    expect(await screen.findByText("Unicycler 0.5.0 on this server.")).toBeInTheDocument();
    expect(screen.getByText(/Mode: short-read assembly/)).toBeInTheDocument();
    const start = screen.getByRole("button", { name: /Start 2 assemblies/ });
    fireEvent.click(await screen.findByRole("checkbox", { name: /I have reviewed what these 2 runs will do/ }));
    fireEvent.click(start);
    await vi.waitFor(() => expect(runUnicycler).toHaveBeenCalled());
    expect(runSpades).toHaveBeenCalledTimes(1);
    expect(runUnicycler.mock.calls[0][1]).toMatchObject({
      inputs: { r1_file_id: "r1", r2_file_id: "r2", unpaired_file_id: null, long_file_id: null },
      params: { mode: "normal", keep: 1, kmers: null, spades_memory_gb: null },
    });
  });
});

describe("SPAdes and Unicycler results", () => {
  const stats = {
    contig_count: 2, total_length: 106_229, largest_contig: 98_152, smallest_contig: 8_077, n50: 98_152, l50: 1, n90: 98_152, l90: 1, gc_percent: 50.1, n_count: 0,
    circularity: { contigs_with_circularity: 0, circular_contigs: 0 }, coverage: { contigs_with_coverage: 2, length_weighted_median: 13.419342 },
    contig_rows: { stored: 2, total: 2, truncated: false }, expected_genome_size: { bp: null, status: "not_given" as const, source: null },
    files: { contigs: null, graph: null, info: null },
  };
  const spades: Assembly = {
    id: "sp", sample_id: "s", job_id: "j1", kind: "assembly", parent_assembly_id: null, assembler: "SPAdes", assembler_version: "3.15.5", mode: "short", read_type: "paired-end", coverage_kind: "kmer_coverage",
    input_file_ids: ["r1", "r2"], created_at: "2026-10-28T15:00:00Z", stats, warnings: [],
  };

  it("labels k-mer coverage as SPAdes' and says that SPAdes reports no circularity", async () => {
    const contigs = [
      { rank: 1, name: "NODE_1_length_98152_cov_13.419342", length: 98_152, gc_percent: 50.2, n_count: 0, other_iupac_count: 0, coverage: 13.419342, circular: null, repeat: null },
      { rank: 2, name: "NODE_2_length_8077_cov_26.792000", length: 8_077, gc_percent: 46.1, n_count: 0, other_iupac_count: 0, coverage: 26.792, circular: null, repeat: null },
    ];
    vi.spyOn(api, "assembly").mockResolvedValue({ ...spades, contigs } as AssemblyDetail);
    renderWith(<AssemblyCard assembly={spades} job={undefined} files={[r1, r2]} />);
    expect(screen.getByText("SPAdes 3.15.5 · short reads · paired-end")).toBeInTheDocument();
    expect(screen.getByText("not reported by SPAdes")).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: /k-mer coverage \(SPAdes\)/ })).toBeInTheDocument();
    expect(within(table).getByText("26.8")).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: "Multiplicity" })).not.toBeInTheDocument();
    expect(screen.getByText(/Coverage is SPAdes' k-mer coverage, read from each contig's name/)).toBeInTheDocument();
  });

  it("warns that coverage is not comparable between assemblers", () => {
    const unicycler: Assembly = { ...spades, id: "un", assembler: "Unicycler", assembler_version: "0.5.0", coverage_kind: "relative_depth", stats: { ...stats, coverage: { contigs_with_coverage: 2, length_weighted_median: 1 } } };
    renderWith(<AssemblyComparison assemblies={[spades, unicycler]} files={[r1, r2]} />);
    expect(screen.getByText("13.4 (k-mer coverage (SPAdes))")).toBeInTheDocument();
    expect(screen.getByText("1.00× (Relative depth (Unicycler))")).toBeInTheDocument();
    expect(screen.getByText(/compare coverage only between assemblies of the same assembler/)).toBeInTheDocument();
  });
});
