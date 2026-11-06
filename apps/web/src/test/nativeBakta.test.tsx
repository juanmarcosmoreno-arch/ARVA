import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnnotationDialog } from "@/components/annotation/AnnotationDialog";
import { RunningCard } from "@/components/assembly/RunMonitor";
import { NativeFlye } from "@/components/settings/PerformanceSection";
import { api } from "@/lib/api";
import { jobError } from "@/lib/messages";
import { dictionaries } from "@/i18n";
import type { AnalysisJob, AnalysisJobDetail, AnnotationPlan, Assembly, BaktaMemory, BaktaNativeOffer, NativeExecutorStatus, Tool } from "@/lib/types";
import { useSettings } from "@/store/settings";

// The user's Mac (registro de prueba, items 49, 51 and 53): Docker Desktop's VM has 5.9 GB; the full Bakta database
// 6.0 had DIAMOND killed for lack of memory, the light one ran. Synthetic names only.
const stats = { contig_count: 2, total_length: 18_960, circularity: { contigs_with_circularity: 2, circular_contigs: 2 } } as unknown as Assembly["stats"];
const assembly = {
  id: "asm-1", sample_id: "s", job_id: "job-flye", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.6",
  mode: "long", read_type: "nano-hq", input_file_ids: [], created_at: "2026-11-06T13:00:00Z", stats, warnings: [],
} as unknown as Assembly;
const bakta: Tool = {
  id: "bakta", name: "Bakta", description: "", homepage: "", license: "GPL-3.0", citation: "", citation_url: "", categories: [], input_formats: [], output_formats: [],
  min_version: "1.12.2", tested_versions: ["1.12.2"], install: {}, status: "available", path: "/opt/arva-tools/conda/bakta/bin/bakta", version: "1.12.2",
  version_validated: true, message: "", reason: null,
};
const short: BaktaMemory = {
  databases: [{ file: "psc.dmnd", sequences: 90_000_000, letters: 25_000_000_000, block_letters: 3_000_000_000 }], block_size: 3, block_letters: 3_000_000_000,
  largest: "psc.dmnd", bytes_per_letter: 2.41, headroom_gb: 1, estimate_gb: 6.7, container_gb: 5.9, verdict: "may_not_fit", in_container: true,
  light_alternative: { id: "db-light", name: "Bakta database (light)", version: "6.0", estimate_gb: 2.8, verdict: "fits" },
};
const ready: BaktaNativeOffer = {
  memory_short: true, offered: true, ready: true, app_open: true, reason: null, database: { root: "/Volumes/JM/ARVA/databases", rel: "bakta-full/6.0" },
  bakta: { version: "1.12.2", build: "pyhdfd78af_0", lock_matches: true }, mac_memory_bytes: 8 * 1024 ** 3, chip: "Apple M2",
};
const db = (id: string, type: "full" | "light") => ({
  id, key: `bakta-${type}`, name: `Bakta database (${type})`, version: "6.0", type, status: "installed" as const, usable: true, checksum: null, verified_at: null, path: `/databases/bakta-${type}/6.0`,
});
const plan = (over: Partial<AnnotationPlan> = {}): AnnotationPlan => ({
  annotator: "bakta",
  tool: { status: "available", version: "1.12.2", version_validated: true, message: "", reason: null, path: bakta.path, license: "GPL-3.0", citation: "", citation_url: "https://doi.org/10.1099/mgen.0.000685", max_threads: 4, default_threads: 4 },
  steps: { trna: { run: true, reason: null, dependencies: [] }, cds: { run: true, reason: null, dependencies: [] } },
  assembly: {
    assembly_id: "asm-1", kind: "assembly", assembler: "Flye", assembler_version: "2.9.6", parent_assembly_id: null, job_id: "job-flye", contigs_sha256: "x",
    created_at: "2026-11-06T13:00:00Z", contigs: 2, total_length: 18_960, circular_contigs: 2, contigs_with_circularity: 2, all_circular: false, longest_contig_name: 8,
    prokka_name_problem: null, descriptions: 0, synthetic_evidence: [],
  },
  suggestions: { locus_tag: "S27", complete: false, translation_table: 11 },
  translation_tables: [11, 4, 25],
  problems: [],
  dependencies: [],
  skip_options: [],
  databases: [db("db-full", "full"), db("db-light", "light")],
  database_id: "db-full",
  database: null,
  programs: {},
  memory: short,
  native: ready,
  execution: "docker",
  ...over,
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
  vi.spyOn(api, "tools").mockResolvedValue([bakta]);
});
afterEach(() => vi.restoreAllMocks());

describe("Bakta's memory and running it on this Mac", () => {
  it("warns that the full database may not fit Docker and switches to the light one", async () => {
    const preview = vi.spyOn(api, "baktaPreview").mockImplementation(async (_id, body) =>
      body.database_id === "db-light" ? plan({ database_id: "db-light", memory: { ...short, verdict: "fits", estimate_gb: 2.8, light_alternative: null }, native: { ...ready, offered: false, memory_short: false } }) : plan({ native: { ...ready, offered: false, reason: "not_known" } }),
    );
    renderWith(<AnnotationDialog open onOpenChange={() => {}} sampleId="s" assemblies={[assembly]} />);
    const note = await screen.findByRole("region", { name: "Memory for Bakta's protein search" });
    expect(within(note).getByText(/needs about 6.7 GB, more than the 5.9 GB ARVA has here/)).toBeInTheDocument();
    expect(within(note).getByText(/3 billion letters, no option to lower it\); the largest block here is 3.00 billion letters of psc.dmnd/)).toBeInTheDocument();
    expect(within(note).getByText(/The light database Bakta database \(light\) 6.0 needs about 2.8 GB/)).toBeInTheDocument();
    // Not offered natively without ARVA.app.
    expect(screen.queryByRole("region", { name: "Run on this Mac (native)" })).toBeNull();
    fireEvent.click(within(note).getByRole("button", { name: "Use the light database" }));
    await waitFor(() => expect(preview).toHaveBeenLastCalledWith("asm-1", { database_id: "db-light", skip_plot: false }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Memory for Bakta's protein search" })).toBeNull());
  });

  it("offers ARVA.app's Bakta, previews with the Mac's programs and asks for a native run", async () => {
    const preview = vi.spyOn(api, "baktaPreview").mockImplementation(async (_id, body) => plan({ execution: body.execution ?? "docker" }));
    const run = vi.spyOn(api, "runBakta").mockResolvedValue({ id: "j" } as AnalysisJob);
    renderWith(<AnnotationDialog open onOpenChange={() => {}} sampleId="s" assemblies={[assembly]} />);
    const option = await screen.findByRole("region", { name: "Run on this Mac (native)" });
    expect(within(option).getByText(/DIAMOND needs about 6.7 GB with this database and Docker has 5.9 GB on this Mac/)).toBeInTheDocument();
    expect(within(option).getByText(/Bakta 1.12.2 for this Mac \(build pyhdfd78af_0\)/)).toBeInTheDocument();
    expect(within(option).getByText(/\/Volumes\/JM\/ARVA\/databases\/bakta-full\/6.0/)).toBeInTheDocument();
    fireEvent.click(within(option).getByRole("checkbox"));
    await waitFor(() => expect(preview).toHaveBeenLastCalledWith("asm-1", { database_id: "db-full", skip_plot: false, execution: "mac_native" }));
    expect(await screen.findByText(/Bakta runs on this Mac with ARVA.app/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByDisplayValue("S27")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("checkbox", { name: /I have read what this run will and will not search/ }));
    const start = screen.getByRole("button", { name: "Annotate" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(run).toHaveBeenCalled());
    expect(run.mock.calls[0][1]).toMatchObject({ database_id: "db-full", execution: "mac_native", skip_options: [] });
  });

  it("blocks the native run while ARVA.app cannot read the database, and says why", async () => {
    vi.spyOn(api, "baktaPreview").mockImplementation(async (_id, body) =>
      plan({ execution: body.execution ?? "docker", native: { ...ready, ready: false, reason: "native_database_not_on_mac", database: null } }),
    );
    renderWith(<AnnotationDialog open onOpenChange={() => {}} sampleId="s" assemblies={[assembly]} />);
    const option = await screen.findByRole("region", { name: "Run on this Mac (native)" });
    expect(within(option).getByText(/this database is inside Docker \(a volume\), not in a folder of the Mac/)).toBeInTheDocument();
    fireEvent.click(within(option).getByRole("checkbox"));
    expect(await screen.findByText(/Bakta cannot run on this Mac now/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /I have read what this run will and will not search/ }));
    expect(screen.getByRole("button", { name: "Annotate" })).toBeDisabled();
  });

  it("shows a native Bakta job waiting for ARVA.app with Bakta's name, and its failures in the job's words", () => {
    const job = {
      id: "j", job_type: "bakta_annotation", tool_name: "Bakta", tool_version: "1.12.2", status: "running", started_at: "2026-11-06T10:00:00Z",
      progress: { tool: "Bakta", stage: null, stage_index: null, stages_total: 15, stages: [], log: null, started_at: null, updated_at: null, elapsed_seconds: null, finished: false, native: { state: "waiting_for_app", app_open: false, app_version: "1.4.0", macos: "15.1", chip: "Apple M2" } },
    } as unknown as AnalysisJobDetail;
    renderWith(<RunningCard job={job} names={new Map()} />);
    expect(screen.getByText(/Bakta will start on this Mac as soon as ARVA.app takes the job/)).toBeInTheDocument();
    expect(screen.getByText(/open it so that Bakta can run on this Mac/)).toBeInTheDocument();
    const t = (k: string, v?: Record<string, unknown>) =>
      Object.entries(v ?? {}).reduce((s, [a, b]) => s.replace(`{${a}}`, String(b)), (dictionaries.en as Record<string, string>)[k] ?? k);
    expect(jobError(t as never, { error_message: "", resources: null, error_detail: { code: "bakta_out_of_memory_native", params: {} } } as never)).toMatch(/stopped by macOS for lack of memory although Bakta ran directly on this Mac/);
  });

  it("lists Bakta for this Mac in Settings → Performance", async () => {
    const status: NativeExecutorStatus = {
      known: true, open: true, seen_at: "2026-11-06T10:00:00Z", app_version: "1.4.0", platform: "osx-arm64", macos: "15.1", chip: "Apple M2", memory_bytes: 8 * 1024 ** 3,
      expected: {
        flye: { platform: "osx-arm64", version: "2.9.6", build: "py313h05f0e27_1", lock_sha256: "54c2a42c2ee3" },
        bakta: { platform: "osx-arm64", version: "1.12.2", build: "pyhdfd78af_0", lock_sha256: "8a302d44802f" },
      },
      tools: { bakta: { installed: true, version: "1.12.2", version_text: "bakta 1.12.2", build: "pyhdfd78af_0", lock_sha256: "8a302d44802fc180", lock_matches: true, ready: true, reason: null } },
    };
    vi.spyOn(api, "nativeExecutor").mockResolvedValue(status);
    renderWith(<NativeFlye />);
    expect(await screen.findByText("Bakta for this Mac: Bakta 1.12.2, build pyhdfd78af_0 (osx-arm64)")).toBeInTheDocument();
    expect(screen.getByText("Ready: ARVA can run Bakta on this Mac.")).toBeInTheDocument();
  });
});
