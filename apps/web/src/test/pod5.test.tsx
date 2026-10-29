import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RawSignalSection } from "@/components/domain/RawSignal";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import { distinctValues, fileTime, runOverview, signalHours } from "@/lib/pod5";
import { hasReads, inProcessTool, jobLabel } from "@/lib/results";
import { isImportableFile, isSequenceFile } from "@/lib/sampleNames";
import type { AnalysisJobDetail, Library, Pod5RunInfo, Pod5Summary, RawFile } from "@/lib/types";
import { useSettings } from "@/store/settings";

const info = (overrides: Partial<Pod5RunInfo> = {}): Pod5RunInfo => ({
  acquisition_id: "A",
  acquisition_start_time: "2026-01-02T03:04:05.678000+00:00",
  protocol_start_time: null,
  sample_id: "SYNTHETIC",
  experiment_name: "SYNTHETIC",
  flow_cell_id: "FC1",
  flow_cell_product_code: "FLO-X",
  sequencing_kit: "KIT-1",
  protocol_name: "proto",
  protocol_run_id: "run",
  sample_rate: 5000,
  software: "MinKNOW",
  system_type: "SYNTHETIC",
  sequencer_position_type: "SYNTHETIC",
  reads: 5,
  samples: 299000,
  signal_duration_s: 59.8,
  ...overrides,
});

const summary = (overrides: Partial<Pod5Summary> = {}): Pod5Summary => ({
  schema: "arva.pod5_summary/1",
  file: {
    writing_software: "Python API", file_identifier: "x", file_version: "0.3.49", original_file_version: "0.3.49",
    is_vbz_compressed: true, batch_count: 1, num_reads: 5,
  },
  reads: {
    count: 5, total_samples: 299000, min_samples: 4000, max_samples: 250000, distinct_channels: 5, acquisitions: 1,
    total_signal_duration_s: 59.8,
  },
  run_info_count: 1,
  run_infos: [info()],
  run_infos_truncated: false,
  warnings: [],
  withheld_fields: ["system_name", "sequencer_position", "context_tags", "tracking_id"],
  ...overrides,
});

const pod5File = (overrides: Partial<RawFile> = {}) =>
  ({
    id: "f1", original_filename: "run.pod5", file_format: "pod5", read_mate: null, origin: "imported", is_valid: true,
    size_bytes: 322144, validation_message: "POD5 raw-signal file", header_metadata: null, ...overrides,
  }) as RawFile;

const job = (overrides: Partial<AnalysisJobDetail> = {}) =>
  ({
    id: "j1", job_type: "pod5_summary", status: "completed", input_raw_file_ids: ["f1"], tool_name: "pod5",
    tool_version: "0.3.49", parameters: { lib_pod5_version: "0.3.49" }, finished_at: "2026-10-28T00:00:00Z",
    result_summary: summary() as unknown as Record<string, unknown>, error_message: null, qc_results: [], ...overrides,
  }) as AnalysisJobDetail;

const library = (overrides: Partial<Library> = {}): Library => ({
  id: "pod5", name: "pod5", homepage: "https://software-docs.nanoporetech.com/pod5/latest/", license: "MPL-2.0",
  citation: "POD5 spec", citation_url: "https://example.org", required_version: "0.3.49", install: 'pip install "pod5==0.3.49"',
  status: "available", version: "0.3.49", companion_versions: { lib_pod5: "0.3.49" }, version_validated: true, ...overrides,
});

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("POD5 helpers", () => {
  it("lists distinct values of all acquisitions in first-seen order", () => {
    const infos = [info(), info({ acquisition_id: "B", sequencing_kit: "KIT-2", flow_cell_product_code: null }), info({ sequencing_kit: "" })];
    expect(distinctValues(infos, "sequencing_kit")).toEqual(["KIT-1", "KIT-2"]);
    const o = runOverview(summary({ run_infos: infos }));
    expect(o.flowCells).toEqual(["FC1 (FLO-X)", "FC1"]);
    expect(o.sampleRates).toEqual([5000]);
  });

  it("takes the earliest valid acquisition start and keeps the file's own offset", () => {
    const o = runOverview(summary({
      run_infos: [
        info({ acquisition_start_time: "2026-01-02T10:00:00+02:00" }),
        info({ acquisition_start_time: "2026-01-02T09:00:00+00:00" }),
        info({ acquisition_start_time: "not a date" }),
      ],
    }));
    expect(o.runStart).toBe("2026-01-02T10:00:00+02:00");
    expect(fileTime(o.runStart!)).toBe("2026-01-02 10:00:00 +02:00");
    expect(fileTime("2026-01-02T03:04:05.678000Z")).toBe("2026-01-02 03:04:05 +00:00");
    expect(fileTime("2026-01-02T03:04:05")).toBe("2026-01-02 03:04:05");
    expect(fileTime("garbage")).toBe("garbage");
  });

  it("converts signal seconds to hours and keeps 'not reported' as null", () => {
    expect(signalHours(7200)).toBe(2);
    expect(signalHours(null)).toBeNull();
  });

  it("never offers POD5 or unrecognised files for read-level analyses", () => {
    expect(hasReads("fastq_gz") && hasReads("fasta")).toBe(true);
    expect(hasReads("pod5") || hasReads("unknown")).toBe(false);
  });

  it("labels the POD5 job through i18n", () => {
    const t = (k: keyof typeof dictionaries.en) => dictionaries.es[k];
    expect(jobLabel("pod5_summary", t)).toBe("Metadatos de corrida POD5");
    expect(jobLabel("fastqc", t)).toBe("Informe de FastQC");
  });

  it("names the pod5 library, not ARVA, as what ran the run-metadata job", () => {
    const t = (k: keyof typeof dictionaries.en, vars?: Record<string, string | number>) =>
      dictionaries.en[k].replace(/\{(\w+)\}/g, (_, v: string) => String(vars?.[v] ?? ""));
    const pod5Job = { job_type: "pod5_summary", tool_version: "0.3.49", parameters: { lib_pod5_version: "0.3.49" } };
    expect(inProcessTool(pod5Job, t)).toBe("pod5 Python library 0.3.49 (lib_pod5 0.3.49), installed separately; not part of ARVA");
    expect(inProcessTool({ ...pod5Job, parameters: {} }, t)).toContain("(lib_pod5 ?)");
    expect(inProcessTool({ job_type: "sequence_stats", tool_version: "0.2.0", parameters: {} }, t)).toBe("built into ARVA");
  });

  it("accepts POD5 for bulk import without calling it a sequence file", () => {
    expect(["run.pod5", "dir/RUN.POD5"].every(isImportableFile)).toBe(true);
    expect(isImportableFile("a.fastq.gz")).toBe(true);
    expect(["a.pod5.gz", "a.fast5", "notes.txt"].some(isImportableFile)).toBe(false);
    expect(isSequenceFile("run.pod5")).toBe(false);
  });
});

describe("RawSignalSection", () => {
  beforeEach(() => useSettings.setState({ language: "en" }));
  afterEach(() => vi.restoreAllMocks());

  it("renders nothing without POD5 files", () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library()]);
    const { container } = wrap(<RawSignalSection sampleId="s1" files={[pod5File({ file_format: "fastq_gz" })]} jobs={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("explains that ARVA does not basecall and links the Dorado documentation", async () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library()]);
    wrap(<RawSignalSection sampleId="s1" files={[pod5File()]} jobs={[]} />);
    expect(screen.getByText(dictionaries.en["pod5.noBasecalling"])).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dorado documentation/ })).toHaveAttribute("href", "https://software-docs.nanoporetech.com/dorado/latest/");
    expect(await screen.findByText(/reads the run information and the per-read sample counts with the pod5 library 0\.3\.49/)).toBeInTheDocument();
  });

  it("starts the job only on click, after explaining it", async () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library()]);
    const start = vi.spyOn(api, "runPod5Summary").mockResolvedValue([]);
    wrap(<RawSignalSection sampleId="s1" files={[pod5File()]} jobs={[]} />);
    const button = screen.getByRole("button", { name: "Read run metadata" });
    await screen.findByText(/The signal is not decoded and the file is not changed/);
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(button);
    expect(start).toHaveBeenCalledWith("s1", ["f1"]);
  });

  it("disables the action and shows the install command when the library is missing", async () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library({ status: "not_installed", version: null })]);
    wrap(<RawSignalSection sampleId="s1" files={[pod5File()]} jobs={[]} />);
    expect(await screen.findByText(/pip install "pod5==0\.3\.49"/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read run metadata" })).toBeDisabled();
  });

  it("shows run metadata with signal hours summed over channels and withheld identifying fields", async () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library()]);
    wrap(<RawSignalSection sampleId="s1" files={[pod5File()]} jobs={[job()]} />);
    expect(screen.getByText("0.02 h")).toBeInTheDocument();
    expect(screen.getByText(dictionaries.en["pod5.signalSub"])).toBeInTheDocument();
    expect(screen.getByText("5,000 Hz")).toBeInTheDocument();
    expect(screen.getByText("FC1 (FLO-X)")).toBeInTheDocument();
    expect(screen.getByText("2026-01-02 03:04:05 +00:00")).toBeInTheDocument();
    expect(screen.getByText(dictionaries.en["pod5.withheld"])).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Read again" })).toBeEnabled());
  });

  it("reports an invalid file instead of offering the action", () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library()]);
    wrap(<RawSignalSection sampleId="s1" files={[pod5File({ is_valid: false, validation_message: "Incomplete or truncated POD5" })]} jobs={[]} />);
    expect(screen.getByText(/Incomplete or truncated POD5/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read run metadata" })).toBeNull();
  });

  it("shows the failure reason of the latest job", async () => {
    vi.spyOn(api, "libraries").mockResolvedValue([library()]);
    wrap(<RawSignalSection sampleId="s1" files={[pod5File()]} jobs={[job({ status: "failed", result_summary: null, error_message: "pod5 0.3.49 could not read this file: IOError" })]} />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not read this file");
  });
});
