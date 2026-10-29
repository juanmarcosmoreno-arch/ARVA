import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StorageCard } from "@/components/domain/StorageCard";
import { StorageSection } from "@/components/settings/StorageSection";
import { api, codedError } from "@/lib/api";
import { launcherCommand, shellQuote } from "@/lib/storage";
import type { StorageCapacity, StorageLocation } from "@/lib/types";
import { useSettings } from "@/store/settings";

const GB = 1024 ** 3;
const loc = (over: Partial<StorageLocation>): StorageLocation => ({
  role: "data", container_path: "/data", host_path: null, read_only: false, available: true, free_bytes: 800 * GB,
  total_bytes: 2000 * GB, filesystem: null, warnings: [], marker: null, stores: [], slot: null, databases: null, ...over,
});

// CONSTRUCTED: what GET /system/storage returns when scripts/start.sh mounted an APFS disk at /Volumes/JM, a Bakta
// folder on an exFAT disk, and a second database folder whose disk is not connected.
const mac: StorageCapacity = {
  storage_root: "/data", free_bytes: 800 * GB, total_bytes: 2000 * GB, min_free_bytes: GB, available_for_data_bytes: 799 * GB,
  upload_overhead_factor: 1, data_host_path: "/Volumes/JM/ARVA/data", in_container: true,
  marker: { status: "ok", disk_id: "a", recorded_id: "a", backups: 3, message: null, text: null },
  locations: [
    loc({ host_path: "/Volumes/JM/ARVA/data", filesystem: "apfs", marker: "ok", stores: ["raw", "backups"] }),
    loc({ role: "databases", container_path: "/databases", host_path: "/Volumes/JM/ARVA/databases", filesystem: "apfs", free_bytes: 12 * GB, warnings: ["low_space"], databases: 1 }),
    loc({ role: "external_databases", container_path: "/databases-external/2846640912", host_path: "/Volumes/USB/Bakta's db", read_only: true, filesystem: "exfat", warnings: ["fat_filesystem"], slot: "2846640912", databases: 2 }),
    loc({ role: "external_databases", container_path: "/databases-external/17", host_path: "/Volumes/Other/gtdb", read_only: true, available: false, free_bytes: null, total_bytes: null, warnings: ["not_connected"], slot: "17" }),
    loc({ role: "import", container_path: "/import", read_only: true }),
  ],
  backups: {
    folder: "/data/backups", host_folder: "/Volumes/JM/ARVA/data/backups", count: 3, interval_hours: 24, keep: 14, pending_since: null,
    files: [{ name: "arva-metadata-manual-20261028T153000Z.dump", kind: "manual", created_at: "2026-10-28T15:30:00Z", size_bytes: 5 * 1024 * 1024 }],
    last_result: { result: "ok", kind: "manual", at: "2026-10-28T15:30:02Z", detail: null },
  },
};

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("launcher commands", () => {
  it("quote a path so that a copied command runs as shown", () => {
    expect(shellQuote("/Volumes/JM/it's $HOME")).toBe("'/Volumes/JM/it'\\''s $HOME'");
    expect(launcherCommand("data", "/Volumes/JM/ARVA/data", "x")).toBe("scripts/start.sh --data-dir '/Volumes/JM/ARVA/data'");
    expect(launcherCommand("external_databases", null, "/Volumes/<Disk>/<db>")).toBe("scripts/start.sh --add-databases /Volumes/<Disk>/<db>");
  });
});

describe("Storage section", () => {
  it("shows every location with its folder on the Mac, space, warnings and the commands that change it", async () => {
    vi.spyOn(api, "storage").mockResolvedValue(mac);
    wrap(<StorageSection />);
    const rows = await screen.findAllByRole("row");
    const row = (text: string) => rows.find((r) => within(r).queryByText(text))!;
    expect(within(row("/Volumes/JM/ARVA/data")).getByText("Read and write")).toBeInTheDocument();
    expect(within(row("/Volumes/JM/ARVA/data")).getByText("Filesystem: apfs")).toBeInTheDocument();
    expect(within(row("/Volumes/JM/ARVA/databases")).getByText("Less than 20 GB free")).toBeInTheDocument();
    expect(within(row("/Volumes/USB/Bakta's db")).getByText(/exFAT or FAT disk/)).toBeInTheDocument();
    expect(within(row("/Volumes/USB/Bakta's db")).getByText("Read-only")).toBeInTheDocument();
    expect(within(row("/Volumes/Other/gtdb")).getByText("Not available: disk not connected")).toBeInTheDocument();
    expect(within(row("/import")).getByText("The import/ folder next to docker-compose.yml")).toBeInTheDocument();
    const commands = screen.getByText(/scripts\/start.sh --data-dir/).textContent!;
    expect(commands).toContain("scripts/start.sh --data-dir '/Volumes/JM/ARVA/data'");
    expect(commands).toContain("scripts/start.sh --add-databases /Volumes/<Disk>/<database folder>");
    expect(commands).toContain("scripts/start.sh --remove-databases '/Volumes/USB/Bakta'\\''s db'");
    expect(screen.getByText(/^Latest: .*5\.00 MB \(on request\)$/)).toBeInTheDocument();
    expect(screen.getByText(/Disk image location/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains a missing disk in Spanish and asks for a restore or an adoption", async () => {
    useSettings.setState({ language: "es" });
    const missing: StorageCapacity = {
      ...mac,
      marker: { status: "restore_needed", disk_id: "a", recorded_id: null, backups: 3, text: "English fallback",
                message: { code: "storage_restore_needed", params: { path: "/Volumes/JM/ARVA/data", count: 3 } } },
    };
    vi.spyOn(api, "storage").mockResolvedValue(missing);
    const adopt = vi.spyOn(api, "adoptStorage").mockResolvedValue(mac);
    wrap(<StorageSection />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Esta carpeta de datos necesita recuperar sus metadatos");
    expect(alert).toHaveTextContent("contiene 3 copias de los metadatos del ARVA que la usó");
    expect(alert).toHaveTextContent("scripts/restore.sh latest");
    expect(screen.getByRole("button", { name: "Hacer una copia ahora" })).toBeDisabled();
    fireEvent.click(within(alert).getByRole("button", { name: "Usar esta carpeta con los metadatos actuales" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Usar esta carpeta con los metadatos actuales" }));
    await waitFor(() => expect(adopt).toHaveBeenCalledOnce());
  });

  it("asks the backup service for a backup", async () => {
    vi.spyOn(api, "storage").mockResolvedValue(mac);
    const backup = vi.spyOn(api, "requestBackup").mockResolvedValue({ ...mac.backups!, pending_since: "2026-10-29T10:00:00Z" });
    wrap(<StorageSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Back up now" }));
    await waitFor(() => expect(backup).toHaveBeenCalledOnce());
  });
});

describe("coded refusals", () => {
  it("are shown in the interface language, with the server's English text for codes it does not know", () => {
    const body = { detail: "The ARVA data folder … (English)", code: "storage_missing", params: { path: "/Volumes/JM/ARVA/data" } };
    useSettings.setState({ language: "es" });
    expect(codedError(body)).toMatch(/^La carpeta de datos de ARVA \/Volumes\/JM\/ARVA\/data no tiene la marca/);
    expect(codedError({ ...body, code: "from_a_newer_server" })).toBe(body.detail);
    expect(codedError({ detail: "plain" })).toBeNull();
  });
});

describe("Storage card on the Import page", () => {
  it("names the data folder on the Mac and warns while the disk is missing", async () => {
    vi.spyOn(api, "storage").mockResolvedValue({
      ...mac, free_bytes: 0, total_bytes: 0, available_for_data_bytes: 0,
      marker: { status: "missing", disk_id: null, recorded_id: "a", backups: 0, text: "x", message: { code: "storage_missing", params: { path: "/Volumes/JM/ARVA/data" } } },
    });
    wrap(<StorageCard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("has no storage marker (.arva-storage)");
    expect(screen.getByText("/Volumes/JM/ARVA/data")).toBeInTheDocument();
  });
});
