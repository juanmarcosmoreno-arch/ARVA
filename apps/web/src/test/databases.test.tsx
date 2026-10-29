import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DatabasesSection } from "@/components/tools/DatabasesSection";
import { api } from "@/lib/api";
import { groupByKind, recordBadges, validDate, validDeclaredVersion, validFolder } from "@/lib/databases";
import type { CatalogueEntry, DatabaseKind, Detection, DownloadPlan, ReferenceDatabase } from "@/lib/types";
import { useSettings } from "@/store/settings";

// CONSTRUCTED responses shaped like the API's (kinds, catalogue, records, detection); not real databases.
const kind = (key: string, name: string, download: "catalogue" | "register" = "register"): DatabaseKind => ({
  key, name, description: `${name} description.`, tools: [{ tool: "Tool", versions: "any", integrated: key === "bakta" }],
  source_url: "https://example.org", licence: "CC BY 4.0", licence_url: null, citation: "Someone (2026)", recognise: "files",
  version_from: "a file", typical_size: "small", download, download_note: "note", sources: ["source"], unconfirmed: [],
  accepts: ["folder"], user_provided_only: false,
});

const KINDS = [kind("bakta", "Bakta database", "catalogue"), kind("skani", "skani sketch database"), kind("reference_genomes", "Reference genome collection")];

const light: CatalogueEntry = {
  key: "bakta-light", name: "Bakta database (light)", kind: "bakta", tool: "bakta", status: "available", description: "Light database.",
  version: "6.0", release_date: "2025-02-24", db_type: "light", source_url: "https://zenodo.org/records/14916843",
  doi: "10.5281/zenodo.14916843", download_url: "https://zenodo.org/api/records/14916843/files/db-light.tar.xz/content",
  filename: "db-light.tar.xz", archive_bytes: 1_344_199_496, checksum_algorithm: "md5", checksum: "4a6e059ded39e9c5537ef4137d2f5648",
  checksum_sources: ["Zenodo record 14916843 (file checksum)"], extracted_size_note: "3.9 Gb unzipped (Bakta README)",
  extracted_bytes_estimate: 4_187_593_113, top_dir: "db-light", install_dir: "bakta-light/6.0", licence: "CC BY 4.0",
  licence_url: "https://creativecommons.org/licenses/by/4.0/", terms: "Cite it.", citation: "Schwengers O. et al.",
  compatibility: "Bakta 1.11 or later", compatibility_now: { status: "compatible", code: "schema_ok", params: { tool: "Bakta", version: "1.12.2", schema: 6 } },
  external_versions: {}, notes: [],
};

const record = (overrides: Partial<ReferenceDatabase> = {}): ReferenceDatabase => ({
  id: "r1", key: "skani", kind: "skani", name: "skani sketch database", version: "GTDB r232", version_source: "declared",
  path: "/databases-external/1/skani", source_url: null, licence: null, size_bytes: 1000, checksum: null, archive_checksum: null,
  status: "registered", origin: "register", is_default: true, verification_level: "quick", installed_at: null, verified_at: null,
  notes: null, error_message: null, progress: null, cancel_requested_at: null, created_at: "", updated_at: "", version_json: null,
  version_file: null, variant: null, collection: null, files: null, published_md5_checked: null, amrfinderplus_db: null, archive: null,
  catalogue_version: null, compatibility: { status: "unknown", code: "tool_not_integrated", params: { tool: "skani" } }, jobs_using: 0,
  available: true, host_path: "/Volumes/JM/BioInf/skani_gtdb_r232-v0.4", log_text: null, ...overrides,
});

const plan = (overrides: Partial<DownloadPlan> = {}): DownloadPlan => ({
  entry: light, db_dir: "/databases", target_path: "/databases/bakta-light/6.0", host_target_path: "/Volumes/JM/ARVA/databases/bakta-light/6.0",
  folder: "bakta-light/6.0", partial_bytes: 0, download_bytes: 1_344_199_496, required_bytes: 5_531_792_609, free_bytes: 12e9,
  reserve_bytes: 1_073_741_824, available_bytes: 10.9e9, enough: true, resume_record_id: null, blocked_by: null, blocked_code: null,
  compatibility: light.compatibility_now,
  destinations: [{ path: "/databases", host_path: "/Volumes/JM/ARVA/databases", available: true, free_bytes: 12e9, total_bytes: 100e9, reserve_bytes: 1_073_741_824 }],
  ...overrides,
});

const skaniDetection: Detection = {
  kind: "skani", kind_name: "skani sketch database", path: "/databases-external/1/skani_gtdb_r232-v0.4", host_path: "/Volumes/JM/BioInf/skani_gtdb_r232-v0.4",
  path_type: "folder", variant: null, version: null, version_file: null, version_detail: null, suggested_version: "GTDB r232",
  suggested_from: "folder_name", version_by_checksum: false, needs_declared_version: true, catalogue_key: null, ok: true,
  files: [{ path: "markers.bin2", role: "kind", present: true, size: 10 }], problems: [], facts: {},
  compatibility: { status: "unknown", code: "tool_not_integrated", params: { tool: "skani" } }, already_registered: null,
};

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DatabasesSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useSettings.setState({ language: "en" });
  vi.spyOn(api, "databaseKinds").mockResolvedValue(KINDS);
  vi.spyOn(api, "databaseCatalogue").mockResolvedValue([light]);
  vi.spyOn(api, "databases").mockResolvedValue([record()]);
  vi.spyOn(api, "databaseUsage").mockResolvedValue({
    db_dir: "/databases", host_db_dir: "/Volumes/JM/ARVA/databases", free_bytes: 12e9, total_bytes: 100e9, reserve_bytes: 1_073_741_824,
    installed_bytes: 0, registered_bytes: 0, partial_bytes: 0, staging_bytes: 0,
  });
  vi.spyOn(api, "databaseLocations").mockResolvedValue({
    writable: plan().destinations,
    browse: [{ path: "/databases-external/1", host_path: "/Volumes/JM/BioInf", read_only: true, role: "external_databases", available: true }],
  });
});
afterEach(() => vi.restoreAllMocks());

describe("database helpers", () => {
  it("badges say ready, declared, default and quick-only, and unavailable replaces ready", () => {
    expect(recordBadges(record()).map((b) => b.key)).toEqual(["ready", "declared", "default", "quickOnly"]);
    expect(recordBadges(record({ available: false, is_default: false, version_source: "file", verification_level: "full" })).map((b) => b.key)).toEqual(["unavailable"]);
    const old = record({ compatibility: { status: "incompatible", code: "schema_mismatch", params: {} }, is_default: false });
    expect(recordBadges(old).map((b) => b.key)).toContain("incompatible");
  });

  it("groups kinds with databases or versions first", () => {
    const groups = groupByKind(KINDS, [record()], [light]);
    expect(groups.map((g) => g.kind.key)).toEqual(["bakta", "skani", "reference_genomes"]);
    expect(groups[1].records).toHaveLength(1);
  });

  it("validates what the API validates", () => {
    expect(validDeclaredVersion("GTDB r232, -c 200")).toBe(true);
    expect(validDeclaredVersion("x<script>")).toBe(false);
    expect(validDate("2026-05-27")).toBe(true);
    expect(validDate("2026-02-30")).toBe(false);
    expect(validFolder("busco/lineages/bacteria_odb12.2")).toBe(true);
    expect(validFolder("../x")).toBe(false);
  });
});

describe("Databases section", () => {
  it("shows databases by kind with their badges and where the version came from", async () => {
    renderSection();
    expect(await screen.findByText("skani sketch database description.")).toBeInTheDocument();
    expect(screen.getByText("Version declared by the user")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("/Volumes/JM/BioInf/skani_gtdb_r232-v0.4")).toBeInTheDocument();
    expect(screen.getByText("Declared by the user")).toBeInTheDocument();
    expect(screen.getByText("Other kinds ARVA recognises")).toBeInTheDocument();
  });

  it("downloads into the chosen folder only after the licence is accepted", async () => {
    const planCall = vi.spyOn(api, "databasePlan").mockResolvedValue(plan());
    const download = vi.spyOn(api, "downloadDatabase").mockResolvedValue({} as ReferenceDatabase);
    renderSection();
    fireEvent.click(await screen.findByText("Bakta database"));
    fireEvent.click(await screen.findByRole("button", { name: /Download…/ }));
    const dialog = await screen.findByRole("dialog");
    const confirm = await within(dialog).findByRole("button", { name: /Download 1\.25 GB/ });
    expect(within(dialog).getByText("/Volumes/JM/ARVA/databases/bakta-light/6.0")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByPlaceholderText("bakta-light/6.0"), { target: { value: "bakta/light-6.0" } });
    await waitFor(() => expect(planCall).toHaveBeenLastCalledWith("bakta-light", null, "bakta/light-6.0"));
    expect(confirm).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(await within(dialog).findByRole("button", { name: /Download 1\.25 GB/ }));
    await waitFor(() => expect(download).toHaveBeenCalledWith("bakta-light", 1_344_199_496, true, null, "bakta/light-6.0"));
  });

  it("refuses an invalid folder name and says why in Spanish", async () => {
    vi.spyOn(api, "databasePlan").mockResolvedValue(plan({ enough: false, available_bytes: 1e9 }));
    useSettings.setState({ language: "es" });
    renderSection();
    fireEvent.click(await screen.findByText("Base de datos de Bakta"));
    fireEvent.click(await screen.findByRole("button", { name: /Descargar…/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/No hay espacio libre suficiente/)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByPlaceholderText("bakta-light/6.0"), { target: { value: "../fuera" } });
    expect(await within(dialog).findByText(/El nombre de la carpeta debe ser una ruta relativa/)).toBeInTheDocument();
  });

  it("registers a folder with a declared version after the detection preview", async () => {
    vi.spyOn(api, "browseDatabases").mockResolvedValue({
      root: "/databases-external/1", path: "", parent: null, host_path: "/Volumes/JM/BioInf", container_path: "/databases-external/1", truncated: false,
      entries: [{ name: "skani_gtdb_r232-v0.4", type: "folder", size_bytes: null, link: false, path: "/databases-external/1/skani_gtdb_r232-v0.4" }],
    });
    const detect = vi.spyOn(api, "detectDatabase").mockResolvedValue({ path: skaniDetection.path, host_path: skaniDetection.host_path, candidates: [skaniDetection] });
    const register = vi.spyOn(api, "registerDatabase").mockResolvedValue(record());
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: /Register existing folder/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("skani_gtdb_r232-v0.4")).toBeInTheDocument();
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Detect" })[0]);
    await waitFor(() => expect(detect).toHaveBeenCalledWith("/Volumes/JM/BioInf/skani_gtdb_r232-v0.4"));
    expect(await within(dialog).findByText("Not stated in its files: declare it below")).toBeInTheDocument();
    expect(within(dialog).getByText(/Suggested: GTDB r232, from the folder's name/)).toBeInTheDocument();
    const version = within(dialog).getByDisplayValue("GTDB r232");
    fireEvent.change(version, { target: { value: "GTDB r232 (skani 0.4)" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Register" }));
    await waitFor(() =>
      expect(register).toHaveBeenCalledWith({
        path: "/Volumes/JM/BioInf/skani_gtdb_r232-v0.4", kind: "skani", declared_version: "GTDB r232 (skani 0.4)", collection_date: null, full_checksum: false,
      }),
    );
  });
});
