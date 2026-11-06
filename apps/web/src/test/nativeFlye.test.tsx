import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssemblyDialog } from "@/components/assembly/AssemblyDialog";
import { RunningCard } from "@/components/assembly/RunMonitor";
import { NativeFlye } from "@/components/settings/PerformanceSection";
import { api } from "@/lib/api";
import type { AnalysisJob, AnalysisJobDetail, FlyeMemory, FlyeNativeOffer, FlyePlan, NativeExecutorStatus, RawFile, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

// The user's Mac (registro de prueba, items 29 and 32): Docker Desktop's VM has 5.9 GB, below Flye 2.9.6's fixed
// 8 GiB k-mer table, and ARVA.app can run the same Flye natively. Synthetic names only.
const reads = { id: "f1", original_filename: "reads.fastq.gz", file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null, uploaded_at: "2026-10-01T10:00:00Z" } as RawFile;
const flye: Tool = {
  id: "flye", name: "Flye", description: "", homepage: "", license: "BSD-3-Clause", citation: "", citation_url: "", categories: [], input_formats: [],
  output_formats: [], min_version: "2.9", tested_versions: ["2.9.6"], install: {}, status: "available", path: "/opt/arva-tools/conda/flye/bin/flye", version: "2.9.6",
  version_validated: true, message: "", reason: null,
};
const memory: FlyeMemory = {
  reference: { source: "Flye docs", url: "", genome: "E. coli", data: "PB 50x", genome_size_bp: 4_600_000, coverage_x: 50, ram_gb: 2 }, reference_bases: 230_000_000,
  available_gb: 5.9, container_memory_gb: 5.9, in_container: true, read_bases: 413_000_000, floor_gb: 8.6, scaled_gb: 3.59, estimate_gb: 8.6, verdict: "below_floor",
  expected_genome_size_bp: 2_800_000,
};
const ready: FlyeNativeOffer = {
  memory_short: true, offered: true, ready: true, app_open: true, reason: null, flye: { version: "2.9.6", build: "py313h05f0e27_1", lock_matches: true },
  mac_memory_bytes: 8 * 1024 ** 3, chip: "Apple M1",
};
const plan = (native: FlyeNativeOffer | undefined): FlyePlan => ({
  tool: { status: "available", version: "2.9.6", version_validated: true, message: "", reason: null, options: ["--genome-size", "--asm-coverage"], max_threads: 4, default_threads: 4 },
  files: [],
  read_type_suggestion: { heuristic: true, value: "nano-hq", basis: "error_at_most_3_percent", read_error: null, platform: "nanopore", platform_source: "sample_metadata", mean_error_rate: 0.0072, mean_base_quality: 21.4, q20_read_error_note: true, sup_model_but_low_quality: false },
  genome_size: { expected: { bp: 2_800_000, status: "given", source: "read_statistics" }, total_read_bases: 413_000_000, files_without_stats: [], from_depth: null },
  memory,
  sample_technology: "nanopore",
  long_reads_confirmation_required: false,
  native,
});

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openDialog(native: FlyeNativeOffer | undefined) {
  vi.spyOn(api, "flyePreview").mockResolvedValue(plan(native));
  renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[reads]} technology="nanopore" />);
  // The only long-read file is preselected.
  expect(await screen.findByRole("checkbox", { name: "reads.fastq.gz" })).toBeChecked();
  fireEvent.change(screen.getByRole("combobox", { name: "Read type" }), { target: { value: "nano-hq" } });
}

beforeEach(() => {
  useSettings.setState({ language: "en" });
  vi.spyOn(api, "tools").mockResolvedValue([flye]);
});
afterEach(() => vi.restoreAllMocks());

describe("Running Flye on this Mac (native)", () => {
  it("is offered when Docker is short of memory and ARVA.app is ready, and the request asks for it", async () => {
    const run = vi.spyOn(api, "runFlye").mockResolvedValue({ id: "j" } as AnalysisJob);
    await openDialog(ready);
    const option = await screen.findByRole("region", { name: "Run on this Mac (native)" });
    expect(within(option).getByText(/Flye 2.9.6 reserves 8 GiB to count k-mers, more than Docker has on this Mac/)).toBeInTheDocument();
    expect(within(option).getByText(/Flye 2.9.6 for this Mac \(build py313h05f0e27_1\)/)).toBeInTheDocument();
    fireEvent.click(within(option).getByRole("checkbox"));
    const summary = screen.getByRole("region", { name: "What this run will do" });
    expect(within(summary).getByText(/^Flye runs on this Mac with ARVA.app/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("checkbox", { name: /I have reviewed what this run will do/ }));
    fireEvent.click(screen.getByRole("button", { name: /Start assembly/ }));
    await waitFor(() => expect(run).toHaveBeenCalled());
    expect(run.mock.calls[0][1]).toMatchObject({ raw_file_ids: ["f1"], execution: "mac_native", params: { read_type: "nano-hq" } });
  });

  it("is not shown when ARVA.app never registered (Linux, or no native Flye)", async () => {
    await openDialog({ ...ready, offered: false, ready: false, app_open: false, reason: "not_known", flye: null });
    await screen.findByRole("region", { name: "What this run will do" });
    expect(screen.queryByRole("region", { name: "Run on this Mac (native)" })).not.toBeInTheDocument();
  });

  it("says that ARVA.app is not open, in Spanish too, and blocks the native run until it is", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "flyePreview").mockResolvedValue(plan({ ...ready, ready: false, app_open: false, reason: "app_not_open" }));
    renderWith(<AssemblyDialog open onOpenChange={() => undefined} sampleId="s" files={[reads]} technology="nanopore" />);
    expect(await screen.findByRole("checkbox", { name: "reads.fastq.gz" })).toBeChecked();
    const option = await screen.findByRole("region", { name: "Ejecutar en esta Mac (nativo)" });
    expect(within(option).getByText("ARVA.app no está abierta: ábrela para que Flye pueda correr en esta Mac")).toBeInTheDocument();
    fireEvent.click(within(option).getByRole("checkbox"));
    expect(screen.getByText("Flye no puede correr en esta Mac ahora (ver «Ejecutar en esta Mac»).")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Iniciar el ensamblaje/ })).toBeDisabled();
  });
});

const running = (state: "waiting_for_app" | "running_on_mac", appOpen = true): AnalysisJobDetail =>
  ({
    id: "job-native-1", project_id: "p", sample_id: "s", job_type: "flye_assembly", tool_name: "Flye", tool_version: "2.9.6", database_name: null,
    database_version: null, input_raw_file_ids: ["f1"], output_paths: [], status: "running", started_at: "2026-11-06T10:00:00Z", finished_at: null,
    duration_seconds: null, log_text: "", created_at: "2026-11-06T10:00:00Z", commands: [], tool_path: "/Users/me/.arva-tools/conda/flye/bin/flye",
    result_summary: null, parent_job_id: null, qc_results: [], parameters: { read_type: "nano-hq", execution: "mac_native" }, error_message: null,
    progress: {
      tool: "Flye", stage: null, stage_index: null, stages_total: 7, stages: ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"],
      started_at: "2026-11-06T10:00:00Z", stage_started_at: null, updated_at: "2026-11-06T10:00:05Z", elapsed_seconds: 5, finished: false,
      native: { state, app_open: appOpen, app_version: "1.4.0", macos: "15.1", chip: "Apple M1", claimed_at: null, heartbeat_at: null },
    },
  }) as AnalysisJobDetail;

describe("A native run's progress", () => {
  beforeEach(() => {
    vi.spyOn(api, "jobLog").mockResolvedValue({ text: "", source: "job" } as never);
  });

  it("shows the run waiting for ARVA.app, and that ARVA.app is not open", async () => {
    useSettings.setState({ language: "es" });
    renderWith(<RunningCard job={running("waiting_for_app", false)} names={new Map()} />);
    const state = screen.getByRole("status");
    expect(within(state).getByText("Esperando a ARVA.app")).toBeInTheDocument();
    expect(within(state).getByText("ARVA.app no está abierta: ábrela para que Flye pueda correr en esta Mac")).toBeInTheDocument();
  });

  it("shows the run on this Mac", () => {
    renderWith(<RunningCard job={running("running_on_mac")} names={new Map()} />);
    const state = screen.getByRole("status");
    expect(within(state).getByText("Running on this Mac")).toBeInTheDocument();
    expect(within(state).getByText(/ARVA.app 1.4.0 runs Flye on macOS 15.1 \(Apple M1\)/)).toBeInTheDocument();
  });
});

const status = (over: Partial<NativeExecutorStatus> = {}): NativeExecutorStatus => ({
  known: true, open: true, seen_at: "2026-11-06T10:00:00Z", app_version: "1.4.0", platform: "osx-arm64", macos: "15.1", chip: "Apple M1",
  memory_bytes: 8 * 1024 ** 3,
  expected: { flye: { platform: "osx-arm64", version: "2.9.6", build: "py313h05f0e27_1", lock_sha256: "54c2a42c2ee358b76f4776ab22bf3b7de38946f899ea2b039a8f3233fe8aa780" } },
  tools: { flye: { installed: true, version: "2.9.6", version_text: "2.9.6-b1802", build: "py313h05f0e27_1", lock_sha256: "54c2a42c2ee358b76f4776ab22bf3b7de38946f899ea2b039a8f3233fe8aa780", lock_matches: true, ready: true, reason: null } },
  ...over,
});

describe("Settings → Performance: Flye for this Mac", () => {
  it("shows the installed Flye, its build and ARVA's lock", async () => {
    vi.spyOn(api, "nativeExecutor").mockResolvedValue(status());
    renderWith(<NativeFlye />);
    expect(await screen.findByText("Installed: Flye 2.9.6, build py313h05f0e27_1 (osx-arm64)")).toBeInTheDocument();
    expect(screen.getByText("Installed from ARVA's lock (sha256 54c2a42c2ee3).")).toBeInTheDocument();
    expect(screen.getByText("Ready: ARVA can run Flye on this Mac.")).toBeInTheDocument();
  });

  it("says in Spanish when ARVA.app is closed or its Flye is not from ARVA's lock", async () => {
    useSettings.setState({ language: "es" });
    const flyeTool = status().tools.flye!;
    vi.spyOn(api, "nativeExecutor").mockResolvedValue(status({ open: false, tools: { flye: { ...flyeTool, lock_matches: false, lock_sha256: "0".repeat(64), ready: false, reason: "lock_mismatch" } } }));
    renderWith(<NativeFlye />);
    expect(await screen.findByText("Flye para esta Mac")).toBeInTheDocument();
    expect(screen.getByText(/^ARVA.app no está abierta \(último contacto/)).toBeInTheDocument();
    expect(screen.getByText("No se instaló desde el lock de ARVA (sha256 esperado 54c2a42c2ee3): ARVA no lo usa.")).toBeInTheDocument();
    expect(screen.getByText("No está listo: Flye no se instaló desde el lock osx-arm64 de ARVA.")).toBeInTheDocument();
  });

  it("explains the option when no ARVA.app has registered", async () => {
    vi.spyOn(api, "nativeExecutor").mockResolvedValue({ ...status(), known: false, open: false, tools: {} });
    renderWith(<NativeFlye />);
    expect(await screen.findByText(/ARVA.app has not registered a native Flye on this computer/)).toBeInTheDocument();
  });
});
