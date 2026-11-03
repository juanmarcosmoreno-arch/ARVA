import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FirstRunChecklist } from "@/components/platform/FirstRunChecklist";
import { api } from "@/lib/api";
import { databaseCheck, performanceCheck, projectCheck, storageCheck } from "@/lib/firstRun";
import type { DashboardSummary, DatabaseLocations, PerformanceOverview, ReferenceDatabase, StorageCapacity, StorageLocation } from "@/lib/types";
import { useSettings } from "@/store/settings";

const GB = 1024 ** 3;
const loc = (over: Partial<StorageLocation>): StorageLocation => ({
  role: "data", container_path: "/data", host_path: null, read_only: false, available: true, free_bytes: 800 * GB,
  total_bytes: 2000 * GB, filesystem: null, warnings: [], marker: null, stores: [], slot: null, databases: null, ...over,
});

// CONSTRUCTED API answers for a Mac started with scripts/start.sh on an APFS disk at /Volumes/JM.
const storage: StorageCapacity = {
  storage_root: "/data", free_bytes: 800 * GB, total_bytes: 2000 * GB, min_free_bytes: GB, available_for_data_bytes: 799 * GB,
  upload_overhead_factor: 1, data_host_path: "/Volumes/JM/ARVA/data", in_container: true,
  marker: { status: "ok", disk_id: "a", recorded_id: "a", backups: 0, message: null, text: null },
  locations: [
    loc({ host_path: "/Volumes/JM/ARVA/data", filesystem: "apfs", marker: "ok" }),
    loc({ role: "external_databases", container_path: "/databases-external/1", host_path: "/Volumes/JM/BioInf", read_only: true, filesystem: "apfs", slot: "1" }),
  ],
};
const launcher = (value: string | number) => ({ value, source: "launcher" as const });
const performance = {
  host: { platform: launcher("macos") },
  effective: { profile: "balanced", threads: 4, memory_gb: 5, host: "MacBook Pro (Mac15,6) · Apple M3 Pro" },
  docker: { status: "ok" },
} as unknown as PerformanceOverview;
const locations: DatabaseLocations = {
  writable: [],
  browse: [
    { path: "/databases", host_path: "/Volumes/JM/ARVA/databases", read_only: false, role: "databases", available: true },
    { path: "/databases-external/1", host_path: "/Volumes/JM/BioInf", read_only: true, role: "external_databases", available: true },
  ],
};
const record = (over: Partial<ReferenceDatabase>) => ({ kind: "bakta", name: "Bakta database", version: "6.0", status: "registered", is_default: true, available: true, ...over }) as ReferenceDatabase;
const dashboard = { project_count: 0 } as DashboardSummary;

function renderChecklist(onCreate = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FirstRunChecklist onCreateProject={onCreate} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onCreate;
}

beforeEach(() => useSettings.setState({ language: "en", showChecklist: true }));
afterEach(() => vi.restoreAllMocks());

describe("first-run checks", () => {
  it("read each status from the API's answer", () => {
    expect(storageCheck(storage)).toMatchObject({ state: "done", params: { folder: "/Volumes/JM/ARVA/data", fs: "apfs" } });
    expect(storageCheck({ ...storage, locations: [loc({})] }).code).toBe("docker_volumes");
    expect(storageCheck({ ...storage, locations: [loc({ host_path: "/Volumes/JM/ARVA/data", available: false })] }).state).toBe("attention");
    expect(storageCheck({ ...storage, marker: { ...storage.marker!, status: "mismatch" } }).code).toBe("marker");
    expect(storageCheck(undefined).state).toBe("unknown");
    // Another disk's free space: the warning names the disk to share and the share to remove.
    const report = { reason: "parent_share" as const, share: "/Volumes", disk: "/Volumes/JM", container_free_bytes: 8 * GB, container_total_bytes: 229 * GB };
    const misreported = loc({ host_path: "/Volumes/JM/ARVA/data", warnings: ["space_misreported"], space_source: "host_at_start", misreport: report });
    expect(storageCheck({ ...storage, locations: [misreported] })).toMatchObject({
      state: "attention", code: "space_misreported", params: { folder: "/Volumes/JM/ARVA/data", disk: "/Volumes/JM", share: "/Volumes" } });
    expect(storageCheck({ ...storage, locations: [{ ...misreported, space_source: "container_misreported", misreport: { ...report, share: "/" } }] }))
      .toMatchObject({ code: "space_misreported_no_figure", params: { share: "/" } });
    // "Less than 20 GB free", which the API judges on the launcher's figure, is not hidden behind it.
    expect(storageCheck({ ...storage, locations: [{ ...misreported, warnings: ["space_misreported", "low_space"] }] }).code).toBe("low_space");
    // A read-only folder's free space is only shown: no warning in the checklist.
    const importLoc = loc({ role: "import", read_only: true, host_path: "/Volumes/JM/import", warnings: ["space_misreported"], misreport: report });
    expect(storageCheck({ ...storage, locations: [loc({ host_path: "/Volumes/JM/ARVA/data", filesystem: "apfs" }), importLoc] }).code).toBe("ok");
    expect(performanceCheck(performance).state).toBe("done");
    expect(performanceCheck({ ...performance, docker: { status: "adjust" } }).code).toBe("docker_adjust");
    expect(performanceCheck({ ...performance, host: { platform: { value: null, source: null } } } as unknown as PerformanceOverview).code).toBe("host_unknown");
    expect(databaseCheck("bakta", [record({})])).toMatchObject({ state: "done", params: { version: "6.0", count: 1 } });
    expect(databaseCheck("bakta", [record({ status: "downloading" })]).state).toBe("busy");
    expect(databaseCheck("bakta", [record({ available: false })]).code).toBe("unavailable");
    expect(databaseCheck("bakta", [record({ status: "failed" })]).code).toBe("failed");
    expect(databaseCheck("references", [record({})]).code).toBe("none");
    expect(databaseCheck("amrfinderplus", undefined).state).toBe("unknown");
    expect(projectCheck(dashboard).state).toBe("todo");
    expect(projectCheck({ project_count: 2 } as DashboardSummary)).toMatchObject({ state: "done", params: { count: 2 } });
  });
});

describe("FirstRunChecklist", () => {
  beforeEach(() => {
    vi.spyOn(api, "storage").mockResolvedValue(storage);
    vi.spyOn(api, "performance").mockResolvedValue(performance);
    vi.spyOn(api, "databases").mockResolvedValue([record({})]);
    vi.spyOn(api, "databaseLocations").mockResolvedValue(locations);
    vi.spyOn(api, "dashboard").mockResolvedValue(dashboard);
  });

  it("shows each item's real status, the folder hint and the actions", async () => {
    const onCreate = renderChecklist();
    expect(await screen.findByText("3 of 6 ready. Each status is read from ARVA now, not ticked by hand.")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => within(li).getByText(/Ready|To do|Needs attention|In progress|Not known yet/).textContent)).toEqual([
      "Ready", "Ready", "Ready", "To do", "To do", "To do",
    ]);
    expect(items[0]).toHaveTextContent("Projects and backups in /Volumes/JM/ARVA/data (apfs)");
    expect(items[1]).toHaveTextContent("Balanced: 4 threads and 5 GB per tool run, for MacBook Pro (Mac15,6) · Apple M3 Pro.");
    expect(items[2]).toHaveTextContent("Bakta database 6.0 is ready (1 registered).");
    expect(items[3]).toHaveTextContent("browse the folders added read-only: /Volumes/JM/BioInf.");
    expect(within(items[3]).getByRole("link", { name: "Database Manager" })).toHaveAttribute("href", "/tools#reference-databases");
    fireEvent.click(within(items[5]).getByRole("button", { name: "New project" }));
    expect(onCreate).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Hide the getting-started checklist/ }));
    expect(useSettings.getState().showChecklist).toBe(false);
  });

  it("speaks Spanish and asks to add the folder when none was added", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "databaseLocations").mockResolvedValue({ writable: [], browse: [] });
    vi.spyOn(api, "storage").mockResolvedValue({ ...storage, locations: [loc({})] });
    renderChecklist();
    expect(await screen.findByText(/^2 de 6 listos\./)).toBeInTheDocument();
    expect(screen.getByText(/se guardan dentro de la imagen de disco de Docker Desktop/)).toBeInTheDocument();
    expect(screen.getAllByText(/scripts\/start.sh --add-databases \/Volumes\/<Disco>\/BioInf/)).toHaveLength(1);
    expect(screen.getByText("Primeros pasos")).toBeInTheDocument();
  });
});
