import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BeforeAfter } from "@/components/filtering/BeforeAfter";
import { FilterDialog } from "@/components/filtering/FilterDialog";
import { dictionaries, interpolate, type TranslationKey, type TranslationVars } from "@/i18n";
import { api } from "@/lib/api";
import {
  FASTP_DEFAULTS,
  FILTLONG_EMPTY,
  describeFastp,
  describeFiltlong,
  expectedKeptBases,
  fastpProblems,
  fastpRequestParams,
  filtlongTarget,
  missedAdapter,
  pairedAdapter,
  storedGenomeSize,
  targetBasesForCoverage,
} from "@/lib/filters";
import { latestResults } from "@/lib/results";
import type { AnalysisJobDetail, QCResult, RawFile, SequenceStats, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

const ES = (key: TranslationKey, vars?: TranslationVars) => interpolate(dictionaries.es[key], vars);

// The overlaid distributions are tested elsewhere; here only the tables and cards matter.
vi.mock("@/components/charts/CompareCharts", () => ({ CompareYieldChart: () => null, CompareQualityChart: () => null, CompareGcChart: () => null }));

function job(overrides: Partial<AnalysisJobDetail>): AnalysisJobDetail {
  return {
    id: "j", project_id: "p", sample_id: "s", job_type: "fastp", tool_name: "fastp", tool_version: "0.23.4", database_name: null,
    database_version: null, parameters: {}, input_raw_file_ids: ["f1"], output_paths: [], status: "completed", started_at: null,
    finished_at: "2026-01-01T00:00:00Z", duration_seconds: 1, log_text: "", error_message: null, created_at: "2026-01-01T00:00:00Z",
    commands: [], tool_path: null, result_summary: null, parent_job_id: null, qc_results: [], ...overrides,
  };
}

const file = (id: string, overrides: Partial<RawFile> = {}) =>
  ({ id, original_filename: `${id}.fastq.gz`, file_format: "fastq_gz", is_valid: true, origin: "imported", parent_file_id: null,
     produced_by_job_id: null, read_mate: null, ...overrides }) as RawFile;

const stats = (total: number, longest: number, genome: number | null = null) =>
  ({ total_bases: total, max_length: longest, read_count: 400, mean_length: 1, median_length: 1, n50: 1, min_length: 1, gc_percent: 50,
     quality: null, coverage_estimate: genome ? { expected_genome_size_bp: genome, estimated_depth: total / genome, note: "" } : null }) as SequenceStats;

const statsJob = (fileId: string, metrics: SequenceStats) =>
  job({ id: `stats-${fileId}`, job_type: "sequence_stats", qc_results: [{ raw_file_id: fileId, metrics } as QCResult] });

describe("fastp options", () => {
  it("describes discarding and trimming by length as different actions", () => {
    const d = describeFastp({ ...FASTP_DEFAULTS, length_limit: 140, max_len1: 145, trim_front1: 5, trim_tail1: 3 }, false);
    expect(d).toContain("Remove reads longer than 140 bp after trimming (discarded, not shortened)");
    expect(d).toContain("Shorten each read to at most 145 bp from the 3′ end (no read is removed)");
    expect(d).toContain("Cut 5 bases from the 5′ start and 3 from the 3′ end of each read");
  });

  it("writes out the read-2 values that follow read 1 for pairs", () => {
    const d = describeFastp({ ...FASTP_DEFAULTS, trim_front1: 4, max_len1: 120, max_len2: 100 }, true);
    expect(d).toContain("Cut 4 bases from the 5′ start and 0 from the 3′ end of read 2");
    expect(d).toContain("Shorten read 1 to at most 120 bp from the 3′ end (no read is removed)");
    expect(d).toContain("Shorten read 2 to at most 100 bp from the 3′ end (no read is removed)");
  });

  it("describes given adapters, complexity, and is translated", () => {
    const p = { ...FASTP_DEFAULTS, adapter_sequence: "AGATCGGAAGAGC", low_complexity_filter: true, complexity_threshold: 40 };
    expect(describeFastp(p, false)).toEqual(expect.arrayContaining([
      "Trim adapter AGATCGGAAGAGC (given; no auto-detection)",
      "Remove reads with complexity < 40% (share of bases that differ from the next base)",
    ]));
    expect(describeFastp(p, true)).toContain("Where the mates do not overlap, trim read 1 with AGATCGGAAGAGC and read 2 with the adapter fastp detects");
    expect(describeFastp({ ...p, detect_adapter_for_pe: false }, true)).toContain(
      "Where the mates do not overlap, trim read 1 with AGATCGGAAGAGC and read 2 with the read-1 adapter",
    );
    expect(describeFastp({ ...p, length_limit: 140 }, false, ES)).toEqual(expect.arrayContaining([
      "Recortar el adaptador AGATCGGAAGAGC (indicado; sin detección automática)",
      "Eliminar lecturas más largas que 140 pb tras el recorte (se descartan, no se acortan)",
    ]));
  });

  it("follows fastp's handling of adapters that are not given (paired end)", () => {
    expect(pairedAdapter(FASTP_DEFAULTS, 1)).toBe("detected");
    const noDetect = { ...FASTP_DEFAULTS, detect_adapter_for_pe: false };
    expect(pairedAdapter(noDetect, 1)).toBe("overlap");
    expect(pairedAdapter({ ...noDetect, adapter_sequence: "ACGTACGT" }, 2)).toBe("read1");
    expect(pairedAdapter({ ...noDetect, adapter_sequence_r2: "TTTTACGT" }, 2)).toEqual({ sequence: "TTTTACGT" });
  });

  it("finds problems the API would reject and sends read-2 options only for pairs", () => {
    expect(fastpProblems({ ...FASTP_DEFAULTS, length_required: 50, length_limit: 40 })).toEqual(["filter.fastp.problem.limitBelowRequired"]);
    expect(fastpProblems({ ...FASTP_DEFAULTS, length_filtering: false, length_limit: 200 })).toEqual(["filter.fastp.problem.limitWithoutFiltering"]);
    expect(fastpProblems({ ...FASTP_DEFAULTS, adapter_sequence: "ACGN" })).toEqual(["filter.fastp.problem.adapter"]);
    expect(fastpProblems({ ...FASTP_DEFAULTS, length_limit: 15 })).toEqual([]);
    const p = { ...FASTP_DEFAULTS, trim_front2: 3, max_len2: 90, adapter_sequence: "", adapter_sequence_r2: "ACGTACGT" };
    expect(fastpRequestParams(p, false)).toMatchObject({ trim_front2: null, max_len2: null, adapter_sequence: null, adapter_sequence_r2: null });
    expect(fastpRequestParams(p, true)).toMatchObject({ trim_front2: 3, max_len2: 90, adapter_sequence_r2: "ACGTACGT" });
    expect(fastpRequestParams({ ...p, adapter_trimming: false }, true)).toMatchObject({ adapter_sequence_r2: null });
  });

  it("warns about an adapter FastQC saw but the previous fastp run did not trim", () => {
    const peaks = [{ name: "Illumina Universal Adapter", max_percent: 7.4 }, { name: "PolyG", max_percent: 20 }];
    const untrimmed = job({ parameters: { adapter_trimming: true }, result_summary: { adapter_trimmed_reads: null } });
    expect(missedAdapter(peaks, untrimmed)).toEqual({ name: "Illumina Universal Adapter", max_percent: 7.4 });
    expect(missedAdapter([{ name: "PolyG", max_percent: 20 }], untrimmed)).toBeNull();
    expect(missedAdapter([{ name: "Nextera Transposase Sequence", max_percent: 5 }], untrimmed)).toBeNull();
    expect(missedAdapter(peaks, job({ result_summary: { adapter_trimmed_reads: 149 } }))).toBeNull();
    expect(missedAdapter(peaks, job({ parameters: { adapter_trimming: false }, result_summary: { adapter_trimmed_reads: null } }))).toBeNull();
    expect(missedAdapter(peaks, undefined)).toBeNull();
  });
});

describe("Filtlong target coverage", () => {
  it("rounds depth × genome size half up, as the server does", () => {
    expect(targetBasesForCoverage(2_800_000, 30)).toBe(84_000_000);
    expect(targetBasesForCoverage(2_814_816, 42.5)).toBe(119_629_680);
    expect(targetBasesForCoverage(101, 0.5)).toBe(51);
  });

  it("expects the target plus at most one read, or everything when the input is smaller", () => {
    const input = { bases: 1_513_780, longest: 26_593 };
    expect(expectedKeptBases(500_000, input)).toEqual({ kind: "target", min: 500_000, max: 526_592 });
    expect(expectedKeptBases(1_500_000, input)).toEqual({ kind: "target", min: 1_500_000, max: 1_513_780 });
    expect(expectedKeptBases(1_513_780, input)).toEqual({ kind: "all", bases: 1_513_780 });
    expect(expectedKeptBases(500_000, null)).toEqual({ kind: "unknown" });
  });

  it("uses the smaller of --target_bases and --keep_percent, as Filtlong does", () => {
    expect(filtlongTarget({ target_bases: 500_000, keep_percent: null }, null)).toBe(500_000);
    expect(filtlongTarget({ target_bases: 500_000, keep_percent: 50 }, 1_513_780)).toBe(500_000);
    expect(filtlongTarget({ target_bases: 1_000_000, keep_percent: 50 }, 1_513_780)).toBe(756_890);
    expect(filtlongTarget({ target_bases: null, keep_percent: 90 }, null)).toBeNull();
  });

  it("describes the coverage target and where the genome size came from", () => {
    const p = { ...FILTLONG_EMPTY, target_bases: 84_000_000 };
    expect(describeFiltlong(p, undefined, { genome_size_bp: 2_800_000, target_coverage_x: 30 })).toEqual([
      "Then keep only the best reads up to 84,000,000 bases (30.0× of a 2,800,000 bp genome; Filtlong receives only the number of bases)",
    ]);
    expect(describeFiltlong(p, ES)).toEqual(["Después, conservar solo las mejores lecturas hasta 84,000,000 bases"]);
    const results = latestResults([statsJob("parent", stats(1, 1, 2_800_000)), statsJob("other", stats(1, 1))]);
    expect(storedGenomeSize(results, file("child", { parent_file_id: "parent" }))).toBe(2_800_000);
    expect(storedGenomeSize(results, file("other"))).toBeNull();
  });
});

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const tool = (id: string, name: string) =>
  ({ id, name, status: "available", version: "1", license: "MIT", version_validated: true, install: {} }) as unknown as Tool;

beforeEach(() => {
  useSettings.setState({ language: "en" });
  vi.spyOn(api, "tools").mockResolvedValue([tool("fastp", "fastp"), tool("filtlong", "Filtlong")]);
});
afterEach(() => vi.restoreAllMocks());

describe("Filter dialog", () => {
  it("computes a coverage target from the stored genome size and shows what it will keep", async () => {
    const run = vi.spyOn(api, "runFiltlong").mockResolvedValue(job({}));
    const ont = file("ont");
    renderWith(
      <FilterDialog open onOpenChange={() => {}} sampleId="s" files={[ont]} jobs={[statsJob("ont", stats(1_513_780, 26_593, 250_000))]} technology="nanopore" />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Target coverage" }));
    expect(screen.getByLabelText(/^Genome size \(bp\)/)).toHaveValue(250_000);
    expect(screen.getByText(/Prefilled from the genome size given for this file's read statistics/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Keep best % of bases/), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/^Target depth \(×\)/), { target: { value: "2" } });
    expect(screen.getByText("Target: 500,000 bases (500.0 kbp) = 2.0× × 250,000 bp")).toBeInTheDocument();
    expect(screen.getByText(/Expected kept: 500,000–526,592 bases \(≈ 2\.0×–2\.1×\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/I have reviewed these settings/));
    const button = screen.getByRole("button", { name: /Run Filtlong/ });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(run).toHaveBeenCalledWith("s", expect.objectContaining({
      genome_size_bp: 250_000, target_coverage_x: 2, params: expect.objectContaining({ target_bases: 500_000, min_length: 1000 }),
    })));
  });

  it("asks for a genome size instead of assuming one, and says when the target removes nothing", () => {
    renderWith(
      <FilterDialog open onOpenChange={() => {}} sampleId="s" files={[file("ont")]} jobs={[statsJob("ont", stats(1_513_780, 26_593))]} technology="nanopore" />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Target coverage" }));
    expect(screen.getByLabelText(/^Genome size \(bp\)/)).toHaveValue(null);
    expect(screen.getByText(/ARVA never assumes one/)).toBeInTheDocument();
    expect(screen.getByText("Enter both the genome size and the target depth.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Keep best % of bases/), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/^Genome size \(bp\)/), { target: { value: "1513780" } });
    fireEvent.change(screen.getByLabelText(/^Target depth \(×\)/), { target: { value: "1" } });
    expect(screen.getByText(/does not exceed the target: Filtlong will remove no reads to meet it/)).toBeInTheDocument();
  });

  it("offers explicit adapters and warns when FastQC saw one that fastp did not trim", async () => {
    const r1 = file("r1");
    const fastqc = job({ id: "qc", job_type: "fastqc", input_raw_file_ids: ["r1"],
      result_summary: { data_summary: { adapter_content: { adapters: [{ name: "Illumina Universal Adapter", max_percent: 7.4 }] } } } });
    const fastp = job({ id: "fp", input_raw_file_ids: ["r1"], parameters: { adapter_trimming: true }, result_summary: { adapter_trimmed_reads: null } });
    const run = vi.spyOn(api, "runFastp").mockResolvedValue(job({}));
    renderWith(<FilterDialog open onOpenChange={() => {}} sampleId="s" files={[r1]} jobs={[fastqc, fastp]} technology="illumina" />);
    expect(screen.getByText(/FastQC found Illumina Universal Adapter in up to 7\.4% of the reads of r1\.fastq\.gz/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Adapter sequence \(optional\)/), { target: { value: "agatcggaagagc" } });
    fireEvent.change(screen.getByLabelText(/^Discard reads longer than \(bp, 0 = off\)/), { target: { value: "140" } });
    expect(screen.getByText("Trim adapter AGATCGGAAGAGC (given; no auto-detection)")).toBeInTheDocument();
    expect(screen.getByText("Remove reads longer than 140 bp after trimming (discarded, not shortened)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Discard reads shorter than \(bp\)/), { target: { value: "150" } });
    expect(screen.getByText(/must be 0 or at least “Discard reads shorter than”/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/I have reviewed these settings/));
    const button = screen.getByRole("button", { name: /Run fastp/ });
    await screen.findByText(/^fastp 1 · MIT/);
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Discard reads shorter than \(bp\)/), { target: { value: "15" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(run).toHaveBeenCalledWith("s", expect.objectContaining({
      params: expect.objectContaining({ adapter_sequence: "AGATCGGAAGAGC", length_limit: 140, trim_front2: null }),
    })));
  });
});

describe("Before/after with a Filtlong target", () => {
  it("shows the target outcome and the depth achieved", () => {
    const filtlong = job({ id: "fl", job_type: "filtlong", tool_name: "Filtlong",
      parameters: { min_length: 1000, target_bases: 3_027_560, genome_size_bp: 1_513_780, target_coverage_x: 2 },
      result_summary: { input_reads: 400, input_bases: 1_513_780, target_bases_reported: 3_027_560, not_enough_reads_for_target: true, below_target_after_filtering: false } });
    renderWith(
      <BeforeAfter parent={file("p")} derived={file("d", { origin: "derived", parent_file_id: "p" })} parentStats={stats(1_513_780, 26_593)}
        derivedStats={stats(1_400_000, 26_593)} filterJob={filtlong} pending={false} />,
    );
    expect(screen.getByText(/Not enough reads to reach the target: no reads were removed to meet the target\./)).toBeInTheDocument();
    expect(screen.getByText(/were still removed/)).toBeInTheDocument();
    expect(screen.getByText("0.9×")).toBeInTheDocument();
    expect(screen.getByText("target 2.0× · 1,513,780 bp genome")).toBeInTheDocument();
    expect(screen.getByText("Approximate depth (×, 1,513,780 bp genome)")).toBeInTheDocument();
  });
});
