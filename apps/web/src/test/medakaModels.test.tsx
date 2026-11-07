import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MedakaModelDialog } from "@/components/databases/MedakaModelDialog";
import { ParamPanel } from "@/components/workflows/ParamPanel";
import { api } from "@/lib/api";
import type { MedakaModelInfo, MedakaModelListing, MedakaModelPlan, ReferenceDatabase } from "@/lib/types";
import type { NodeKind } from "@/lib/workflows";
import { useSettings } from "@/store/settings";

// medaka 2.1.1's published r941_min_hac_g507 (its Git LFS pointer at the tag v2.1.1: 1,502,971 bytes, SHA-256 6e8760…).
const SHA = "6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb268ef07ac7680ac26";
const FILE = "r941_min_hac_g507_model_pt.tar.gz";
const info: MedakaModelInfo = {
  name: "r941_min_hac_g507", file: FILE, pore: "R9.4.1", chemistry: "R9.4.1", device: "MinION/GridION", accuracy: "hac", basecaller: "Guppy 5.0.7",
  sha256: SHA, bytes: 1_502_971, url: `https://media.githubusercontent.com/media/nanoporetech/medaka/v2.1.1/medaka/data/${FILE}`,
  pointer_url: `https://github.com/nanoporetech/medaka/blob/v2.1.1/medaka/data/${FILE}`, medaka_url: `https://github.com/nanoporetech/medaka/raw/master/medaka/data/${FILE}`,
  notes: [], database_id: null, status: null,
};
const plan: MedakaModelPlan = {
  ...info, model: info.name, key: "medaka-r941_min_hac_g507", medaka_version: "2.1.1", tag: "v2.1.1", commit: "7354d9d564693ea08998577a21aa72f02117107e",
  licence: "Oxford Nanopore Technologies PLC. Public License Version 1.0", licence_url: "https://github.com/nanoporetech/medaka/blob/v2.1.1/LICENSE",
  citation: "Oxford Nanopore Technologies. Medaka", source_page: "https://github.com/nanoporetech/medaka/tree/v2.1.1/medaka/data",
  db_dir: "/db", folder: "medaka-models/r941_min_hac_g507", target_path: "/db/medaka-models/r941_min_hac_g507", host_target_path: null,
  destinations: [{ path: "/db", host_path: null, available: true, free_bytes: 10_000_000_000 } as MedakaModelPlan["destinations"][number]],
  required_bytes: 1_502_971, free_bytes: 10_000_000_000, reserve_bytes: 1_000_000, available_bytes: 9_999_000_000, enough: true, blocked_by: null, blocked_code: null,
};

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("Medaka model download", () => {
  it("shows the model, what it was trained for, the address, size, SHA-256 and licence, and downloads only after confirmation", async () => {
    vi.spyOn(api, "medakaModelPlan").mockResolvedValue(plan);
    const download = vi.spyOn(api, "medakaModelDownload").mockResolvedValue({ id: "db-1" } as ReferenceDatabase);
    const onClose = vi.fn();
    renderWith(<MedakaModelDialog model={info} onClose={onClose} />);
    expect(await screen.findByText("R9.4.1 · MinION/GridION · hac · Guppy 5.0.7")).toBeInTheDocument();
    expect(screen.getByText(SHA)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: plan.url })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: plan.licence })).toBeInTheDocument();
    expect(screen.getByText(/medaka itself would download from .*raw\/master.*which ARVA does not use/)).toBeInTheDocument();
    const start = screen.getByRole("button", { name: /Download \(1\.43 MB\)/ });
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(download).toHaveBeenCalled());
    expect(download.mock.calls[0][0]).toEqual({ model: "r941_min_hac_g507", destination: null, folder: null, confirm_sha256: SHA, confirm_bytes: 1_502_971, accept_licence: true });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("in Spanish", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "medakaModelPlan").mockResolvedValue(plan);
    renderWith(<MedakaModelDialog model={info} onClose={() => undefined} />);
    expect(await screen.findByText("Descargar el modelo de Medaka r941_min_hac_g507")).toBeInTheDocument();
    expect(screen.getByText(/Confirmo la descarga de r941_min_hac_g507 \(1,43 MB\) y acepto la licencia de Medaka/)).toBeInTheDocument();
  });
});

describe("workflow polishing node", () => {
  it("offers the shipped and registered models for medaka.model", async () => {
    const listing: MedakaModelListing = {
      medaka_version: "2.1.1", published_for: "2.1.1", tag: "v2.1.1", commit: "7354d9d", shipped: ["r1041_e82_400bps_hac_v5.2.0", "r1041_e82_400bps_sup_v5.2.0"],
      available: [{ ...info, database_id: "db-r941", status: "installed" }],
      registered: [{ database_id: "db-r941", model: "r941_min_hac_g507", name: "Medaka model r941_min_hac_g507", path: `/db/m/${FILE}`, sha256: SHA, url: info.url, origin: "download",
        status: "installed", chemistry: "R9.4.1", device: "MinION/GridION", accuracy: "hac", basecaller: "Guppy 5.0.7", notes: [] }],
      licence: plan.licence, licence_url: plan.licence_url, citation: plan.citation, medaka_url_template: "", download_url_template: "", deprecated_example: "r941_min_high_g360",
    };
    vi.spyOn(api, "medakaModels").mockResolvedValue(listing);
    const onChange = vi.fn();
    const schema = { type: "object", properties: { medaka: { type: "object", properties: { model: { anyOf: [{ type: "string" }, { type: "null" }], default: null } } } } };
    const kind = { kind: "polishing", label: "Polishing", category: "assembly", source: false, internal: false, tool_param: null, tools: {}, inputs: [], outputs: [],
      params_schema: schema, defaults: {}, database_kinds: {} } as unknown as NodeKind;
    renderWith(<ParamPanel kind={kind} params={{ medaka: { model: null } }} problems={[]} onChange={onChange} />);
    const select = await screen.findByRole("combobox");
    await within(select).findByRole("option", { name: "r941_min_hac_g507 (R9.4.1, Guppy 5.0.7)" });
    expect(within(select).getByRole("option", { name: "r1041_e82_400bps_sup_v5.2.0" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "r941_min_hac_g507" } });
    expect(onChange).toHaveBeenLastCalledWith({ medaka: { model: "r941_min_hac_g507" } });
  });
});
