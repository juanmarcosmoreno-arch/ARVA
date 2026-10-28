import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { forwardRef, type ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FastpDataSection } from "@/components/qc/FastpData";
import { FastqcDataSection } from "@/components/qc/FastqcData";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { api } from "@/lib/api";
import {
  asPercent,
  binCentre,
  copiesText,
  curvePeak,
  duplicationCopies,
  fastpJobFor,
  fastpMate,
  insertSizeSpan,
  isLongReadData,
  padCurve,
  positionText,
} from "@/lib/qcData";
import type { AnalysisJobDetail, FastpData, FastqcData, RawFile } from "@/lib/types";
import { useSettings } from "@/store/settings";

// ECharts needs a real layout engine; the stub exposes the option each chart would draw.
vi.mock("echarts-for-react/lib/core", () => ({
  default: forwardRef<HTMLDivElement, { option: unknown; "aria-label"?: string }>(function Stub(props, ref) {
    return <div ref={ref} data-testid="chart" aria-label={props["aria-label"]} data-option={JSON.stringify(props.option)} />;
  }),
}));

const LEVELS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ">10", ">50", ">100", ">500", ">1k", ">5k", ">10k+"];

function job(overrides: Partial<AnalysisJobDetail>): AnalysisJobDetail {
  return {
    id: "j1", project_id: "p", sample_id: "s", job_type: "fastqc", tool_name: "FastQC", tool_version: "0.12.1", database_name: null,
    database_version: null, parameters: {}, input_raw_file_ids: ["f1"], output_paths: [], status: "completed", started_at: null,
    finished_at: "2026-01-01T00:00:00Z", duration_seconds: 1, log_text: "", error_message: null, created_at: "2026-01-01T00:00:00Z",
    commands: [], tool_path: null, result_summary: null, parent_job_id: null, qc_results: [], ...overrides,
  };
}

function file(id: string, overrides: Partial<RawFile> = {}) {
  return { id, original_filename: `${id}.fastq.gz`, produced_by_job_id: null, parent_file_id: null, ...overrides } as RawFile;
}

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function chartOption(title: string) {
  return JSON.parse(screen.getByLabelText(title).getAttribute("data-option")!);
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("FastQC position and duplication labels", () => {
  it("formats single positions and 1-based inclusive bins", () => {
    expect(positionText({ start: 5, end: 5 })).toBe("5");
    expect(positionText({ start: 10, end: 11 })).toBe("10–11");
    expect(positionText({ start: 26500, end: 26582 })).toBe("26,500–26,582");
    expect(binCentre({ start: 9, end: 9 })).toBe(9);
    expect(binCentre({ start: 10, end: 499 })).toBe(254.5);
  });

  it("maps FastQC's 16 duplication bins to copy ranges (DuplicationLevel.java)", () => {
    expect(LEVELS.map(copiesText)).toEqual([
      "1", "2", "3", "4", "5", "6", "7", "8", "9", "10–50", "51–100", "101–500", "501–1,000", "1,001–5,000", "5,001–10,000", "≥ 10,001",
    ]);
    expect(duplicationCopies(">10")).toEqual({ min: 10, max: 50 });
    expect(duplicationCopies(">10k+")).toEqual({ min: 10001, max: null });
    expect(duplicationCopies("0")).toBeNull();
    expect(copiesText(">20k")).toBe(">20k");
  });

  it("treats long-read samples or reads over 1,000 bp as long reads", () => {
    expect(isLongReadData(150, "illumina")).toBe(false);
    expect(isLongReadData(1000, "unknown")).toBe(false);
    expect(isLongReadData(26593, "unknown")).toBe(true);
    expect(isLongReadData(null, "nanopore")).toBe(true);
    expect(isLongReadData(undefined, "pacbio")).toBe(true);
  });

  it("finds the first position where a curve peaks", () => {
    expect(curvePeak([0, 0.2, 7.4, 7.4])).toEqual({ value: 7.4, index: 2 });
    expect(curvePeak([0, 0, 0])).toBeNull();
    expect(curvePeak([])).toBeNull();
  });
});

describe("fastp curve helpers", () => {
  it("pads trimmed curves to the cycle axis and converts fractions to percent", () => {
    expect(padCurve([1, 2], 4)).toEqual([1, 2, null, null]);
    expect(padCurve(undefined, 2)).toEqual([null, null]);
    expect(asPercent([0.3335, null, 0])).toEqual([33.35, null, 0]);
  });

  it("limits the insert-size axis to sizes with pairs", () => {
    const h = Array(512).fill(0);
    h[60] = 3;
    h[118] = 1;
    expect(insertSizeSpan(h)).toEqual([60, 118]);
    expect(insertSizeSpan(Array(512).fill(0))).toBeNull();
  });

  it("finds the fastp run of a file and which read it was", () => {
    const run = job({ id: "fp", job_type: "fastp", input_raw_file_ids: ["r1", "r2"] });
    const older = job({ id: "old", job_type: "fastp", input_raw_file_ids: ["r1", "r2"] });
    const failed = job({ id: "bad", job_type: "fastp", status: "failed", input_raw_file_ids: ["r1"] });
    const jobs = [failed, run, older];
    expect(fastpJobFor(jobs, file("r2"))?.id).toBe("fp");
    expect(fastpJobFor(jobs, file("o2", { produced_by_job_id: "old" }))?.id).toBe("old");
    expect(fastpJobFor(jobs, file("other"))).toBeUndefined();
    expect(fastpMate(run, file("r2"))).toBe("read2");
    expect(fastpMate(run, file("r1"))).toBe("read1");
    expect(fastpMate(run, file("o2", { parent_file_id: "r2" }))).toBe("read2");
  });
});

// Shaped like the nanopore FastQC 0.12.1 result: every read listed, nothing duplicated.
const longReadData: FastqcData = {
  fastqc_version: "0.12.1",
  total_sequences: 400,
  max_read_length: 26593,
  modules: [],
  adapter_content: {
    status: "PASS",
    positions: [{ label: "1", start: 1, end: 1 }, { label: "10-499", start: 10, end: 499 }],
    adapters: [{ name: "Illumina Universal Adapter", percent: [0, 0] }, { name: "PolyA", percent: [0, 0] }],
  },
  duplication: { status: "PASS", total_deduplicated_percent: 100, duplicate_percent: 0, bins: LEVELS.map((level, i) => ({ level, percent_of_total: i ? 0 : 100 })) },
  overrepresented_sequences: {
    status: "WARN",
    total: 400,
    rows: Array.from({ length: 20 }, (_, i) => ({ sequence: `ACGT${i}`.padEnd(50, "A"), count: 1, percent: 0.25, possible_source: "No Hit" })),
    every_read_listed: true,
  },
  unrecognised: [],
  source: "SYNTHETIC_nanopore_reads_fastqc.zip",
};

describe("FastQC data section", () => {
  it("charts adapter content with FastQC's thresholds and flags long-read limitations", async () => {
    vi.spyOn(api, "fastqcData").mockResolvedValue(longReadData);
    renderWith(<FastqcDataSection job={job({})} technology="unknown" prefix="x" />);
    expect(await screen.findByText(/FastQC listed every read of this file/)).toBeInTheDocument();
    expect(screen.getByText(/Long reads: FastQC compares only the first 50 bases/)).toBeInTheDocument();
    expect(screen.getByText(/this chart is greyed out/)).toBeInTheDocument();
    expect(screen.getByText(/predates ARVA's stored chart data/)).toBeInTheDocument();
    expect(screen.getByText("Showing the first 20 of 400 sequences FastQC listed (most frequent first); the FastQC report has the full list.")).toBeInTheDocument();
    expect(screen.getByText("No adapter sequence was found at any position.")).toBeInTheDocument();

    const adapter = chartOption("Adapter content (FastQC)");
    expect(adapter.series).toHaveLength(2);
    expect(adapter.series[0].data).toEqual([[1, 0], [254.5, 0]]);
    expect(adapter.series[0].markLine.data.map((d: { yAxis: number }) => d.yAxis)).toEqual([5, 10]);
    expect(adapter.series[0].lineStyle.color).not.toBe(adapter.series[1].lineStyle.color);

    const dup = chartOption("Sequence duplication levels (FastQC)");
    expect(dup.xAxis.data).toHaveLength(16);
    expect(dup.series[0].itemStyle.opacity).toBe(0.6);
    expect(screen.getAllByText("FastQC heuristics: PASS")).toHaveLength(2);
    expect(screen.getByText("FastQC heuristics: WARN")).toBeInTheDocument();
  });

  it("shows an empty overrepresented table and Spanish text", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "fastqcData").mockResolvedValue({
      ...longReadData,
      max_read_length: 150,
      overrepresented_sequences: { status: "PASS", total: 0, rows: [], every_read_listed: false },
      source: "fastqc_data.json",
    });
    renderWith(<FastqcDataSection job={job({})} technology="illumina" prefix="x" />);
    expect(await screen.findByText("FastQC no encontró ninguna secuencia por encima del 0,1 % de las lecturas.")).toBeInTheDocument();
    expect(screen.queryByText(/atenuado/)).not.toBeInTheDocument();
    expect(chartOption("Niveles de duplicación de secuencias (FastQC)").series[0].itemStyle.opacity).toBe(1);
  });
});

function curves(n: number) {
  return { total_reads: 10, total_cycles: n, quality: { mean: Array(n).fill(30) }, content: { GC: Array(n).fill(0.5), N: Array(n).fill(0) } };
}

const pairedData: FastpData = {
  fastp_version: "0.23.4",
  sequencing: "paired end (150 cycles + 150 cycles)",
  reads: { read1: { before: curves(150), after: curves(140) }, read2: { before: curves(150), after: curves(150) } },
  adapter_cutting: {
    adapter_trimmed_reads: 296, adapter_trimmed_bases: 18204, read1_adapter_sequence: "unspecified", read2_adapter_sequence: "unspecified",
    read1_adapter_counts: [{ sequence: "AGATCGGAAGAGCACACGTCTGAACTCCAGT", count: 4 }, { sequence: "others", count: 137 }],
    read2_adapter_counts: [],
  },
  duplication_rate: 0,
  insert_size: {
    peak: 72, unknown: 923, overlapping_pairs: 77, evaluated_pairs: 1000,
    histogram: Array.from({ length: 512 }, (_, i) => (i === 72 ? 5 : i === 60 ? 3 : 0)),
    histogram_percent: Array.from({ length: 512 }, (_, i) => (i === 72 ? 0.5 : i === 60 ? 0.3 : 0)),
    unknown_percent: 92.3, insert_size_max: 512,
  },
  threads: 3,
};

describe("fastp data section", () => {
  it("draws before/after curves per read, the adapter summary and the insert-size estimate", async () => {
    vi.spyOn(api, "fastpData").mockResolvedValue(pairedData);
    const files = [file("r1"), file("r2")];
    renderWith(<FastpDataSection job={job({ job_type: "fastp", input_raw_file_ids: ["r1", "r2"] })} file={files[1]} files={files} prefix="x" />);
    expect(await screen.findByText(/inputs: r1\.fastq\.gz \+ r2\.fastq\.gz/)).toBeInTheDocument();
    expect(screen.getAllByRole("radio", { name: "R2" })[0]).toHaveAttribute("aria-checked", "true");

    const quality = chartOption("Mean quality per cycle (fastp)");
    expect(quality.xAxis.data).toHaveLength(150);
    expect(quality.series.map((s: { name: string }) => s.name)).toEqual(["Before filtering", "After filtering"]);

    screen.getAllByRole("radio", { name: "R1" })[0].click();
    const r1 = await screen.findAllByText(/· R1$/);
    expect(r1.length).toBeGreaterThan(0);
    const after = chartOption("Mean quality per cycle (fastp)").series[1].data;
    expect(after.slice(139, 141)).toEqual([30, null]);

    expect(screen.getByText("Others (each under 1 % of the trimmed reads)")).toBeInTheDocument();
    expect(screen.getAllByText(/none: fastp trimmed paired-end reads where the two mates overlap/)).toHaveLength(2);
    expect(screen.getByText(/Peak 72 bp · from the 1,000 pairs read by fastp's worker thread 0 \(--thread 3\); 7\.7% of them overlapped/)).toBeInTheDocument();
    expect(screen.getByText(/count as “unknown” \(92\.3% here\)/)).toBeInTheDocument();
    const insert = chartOption("Insert size (fastp estimate)");
    expect(insert.xAxis.data[0]).toBe(60);
    expect(insert.series[0].markLine.data[0].xAxis).toBe(12);
  });

  it("explains missing adapter and insert-size blocks for single-end runs", async () => {
    vi.spyOn(api, "fastpData").mockResolvedValue({ ...pairedData, reads: { read1: pairedData.reads.read1 }, adapter_cutting: null, insert_size: null, duplication_rate: null });
    renderWith(<FastpDataSection job={job({ job_type: "fastp" })} file={file("f1")} files={[file("f1")]} prefix="x" />);
    const card = (await screen.findByText("Adapter trimming (fastp)")).closest("div.rounded-xl") as HTMLElement;
    expect(within(card).getByText(/fastp reported no adapter trimming/)).toBeInTheDocument();
    expect(within(card).getByText("not evaluated")).toBeInTheDocument();
    expect(screen.queryByText("Insert size (fastp estimate)")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "R2" })).not.toBeInTheDocument();
  });
});

describe("Guide entries for the QC charts", () => {
  it.each(["adapter_content", "duplication_levels", "overrepresented_sequences", "per_position_quality_fastp", "insert_size"] as const)(
    "%s exists with references",
    (id) => {
      expect(GUIDE_BY_ID[id].references.length).toBeGreaterThan(0);
      expect(GUIDE_BY_ID[id].es.title.length).toBeGreaterThan(0);
    },
  );

  it("cites FastQC's source code for the 50 bp truncation", () => {
    expect(GUIDE_BY_ID.duplication_levels.en.how).toMatch(/longer than 50 bp .*source code; the documentation says reads over 75 bp/);
  });
});
