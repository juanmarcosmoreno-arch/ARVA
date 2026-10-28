import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DatabasesSection } from "@/components/tools/DatabasesSection";
import { api } from "@/lib/api";
import type { CatalogueEntry, DownloadPlan, ReferenceDatabase } from "@/lib/types";
import { useSettings } from "@/store/settings";

const light: CatalogueEntry = {
  key: "bakta-light", name: "Bakta database (light)", tool: "bakta", status: "available", description: "Light database.",
  version: "6.0", release_date: "2025-02-24", db_type: "light", source_url: "https://zenodo.org/records/14916843",
  doi: "10.5281/zenodo.14916843", download_url: "https://zenodo.org/api/records/14916843/files/db-light.tar.xz/content",
  filename: "db-light.tar.xz", archive_bytes: 1_344_199_496, checksum_algorithm: "md5", checksum: "4a6e059ded39e9c5537ef4137d2f5648",
  checksum_sources: ["Zenodo record 14916843 (file checksum)"], extracted_size_note: "3.9 Gb unzipped (Bakta README)",
  extracted_bytes_estimate: 4_187_593_113, licence: "CC BY 4.0", licence_url: "https://creativecommons.org/licenses/by/4.0/",
  terms: "Cite it.", citation: "Schwengers O. et al.", compatibility: "Bakta 1.11 or later", external_versions: {}, notes: [],
};

const plan = (overrides: Partial<DownloadPlan> = {}): DownloadPlan => ({
  entry: light, db_dir: "/db", target_path: "/db/bakta-light/6.0", partial_bytes: 0, download_bytes: 1_344_199_496,
  required_bytes: 5_531_792_609, free_bytes: 12e9, reserve_bytes: 1_073_741_824, available_bytes: 10.9e9, enough: true,
  resume_record_id: null, blocked_by: null, ...overrides,
});

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
  vi.spyOn(api, "databaseCatalogue").mockResolvedValue([light, { ...light, key: "checkm2", name: "CheckM2 database", status: "planned" }]);
  vi.spyOn(api, "databases").mockResolvedValue([]);
  vi.spyOn(api, "databaseUsage").mockResolvedValue({
    db_dir: "/db", free_bytes: 12e9, total_bytes: 100e9, reserve_bytes: 1_073_741_824, installed_bytes: 0, registered_bytes: 0,
    partial_bytes: 0, staging_bytes: 0,
  });
});
afterEach(() => vi.restoreAllMocks());

describe("Databases section", () => {
  it("downloads only after the licence is accepted, confirming the published archive size", async () => {
    vi.spyOn(api, "databasePlan").mockResolvedValue(plan());
    const download = vi.spyOn(api, "downloadDatabase").mockResolvedValue({} as ReferenceDatabase);
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: /Download…/ }));
    const dialog = await screen.findByRole("dialog");
    const confirm = await within(dialog).findByRole("button", { name: /Download 1\.25 GB/ });
    expect(within(dialog).getByText("5.15 GB")).toBeInTheDocument();
    expect(confirm).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("checkbox"));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(download).toHaveBeenCalledWith("bakta-light", 1_344_199_496, true));
  });

  it("refuses to start when the free space is not enough and lists planned databases without numbers", async () => {
    vi.spyOn(api, "databasePlan").mockResolvedValue(plan({ enough: false, available_bytes: 1e9 }));
    useSettings.setState({ language: "es" });
    renderSection();
    expect(await screen.findByText("CheckM2 database")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Descargar…/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/No hay espacio libre suficiente/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("checkbox"));
    expect(within(dialog).getByRole("button", { name: /Descargar 1\.25 GB/ })).toBeDisabled();
  });
});
