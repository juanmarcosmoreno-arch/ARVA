import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RegisterGenomesDialog } from "@/components/assembly/RegisterGenomesDialog";
import { api } from "@/lib/api";
import type { ProjectGenomeRow } from "@/lib/types";
import { useSettings } from "@/store/settings";

const ROWS: ProjectGenomeRow[] = [
  { sample_id: "s1", sample_code: "cepa_17", status: "ready", file_id: "f1", file_name: "cepa_17.fasta", fasta_files: 1 },
  { sample_id: "s2", sample_code: "cepa_18", status: "ready", file_id: "f2", file_name: "cepa_18.fasta", fasta_files: 1 },
  { sample_id: "s3", sample_code: "Strain_27", status: "registered", file_id: null, file_name: null, fasta_files: 1 },
  { sample_id: "s4", sample_code: "cepa_99", status: "several_fasta", file_id: null, file_name: null, fasta_files: 2 },
];

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RegisterGenomesDialog open onOpenChange={() => {}} projectId="p1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => useSettings.setState({ language: "es" }));
afterEach(() => vi.restoreAllMocks());

describe("Register the genome FASTA of every sample", () => {
  it("lists what will be registered, then registers the ready samples with one source", async () => {
    vi.spyOn(api, "projectGenomes").mockResolvedValue(ROWS);
    const register = vi.spyOn(api, "registerProjectGenomes").mockResolvedValue({
      started: [{ sample_id: "s1", sample_code: "cepa_17", job_id: "j1" }, { sample_id: "s2", sample_code: "cepa_18", job_id: "j2" }],
      skipped: [],
    });
    renderDialog();
    expect(await screen.findByText("cepa_17.fasta")).toBeInTheDocument();
    expect(screen.getByText("ya registrado")).toBeInTheDocument();
    expect(screen.getByText("2 archivos FASTA: regístralo en la muestra eligiendo uno")).toBeInTheDocument();
    expect(screen.getByText("2 de 4 muestras listas para registrar")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /Registrar 2 genomas/ });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Fuente" }), { target: { value: "Pipeline propio GridION: Flye 2.9.6 + Medaka 2.1.1" } });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(button);
    await waitFor(() =>
      expect(register).toHaveBeenCalledWith("p1", { source: "Pipeline propio GridION: Flye 2.9.6 + Medaka 2.1.1", sample_ids: ["s1", "s2"] }),
    );
    expect(await screen.findByText(/Registrando 2 genomas/)).toBeInTheDocument();
  });

  it("refuses a source with characters the API rejects", async () => {
    vi.spyOn(api, "projectGenomes").mockResolvedValue(ROWS);
    renderDialog();
    await screen.findByText("cepa_17.fasta");
    fireEvent.change(screen.getByRole("textbox", { name: "Fuente" }), { target: { value: "<script>" } });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: /Registrar 2 genomas/ })).toBeDisabled();
  });
});
