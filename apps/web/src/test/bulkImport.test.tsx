import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BulkImportDialog } from "@/components/domain/BulkImportDialog";
import { api } from "@/lib/api";
import type { Sample, StorageCapacity, UploadResult } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("@/lib/api", () => ({
  api: { storage: vi.fn(), createSample: vi.fn(), uploadFiles: vi.fn() },
}));

const mocked = vi.mocked(api);
const capacity = (available: number): StorageCapacity => ({
  storage_root: "/data",
  free_bytes: available,
  total_bytes: 1e12,
  min_free_bytes: 0,
  available_for_data_bytes: available,
});
const existing = { id: "sample-a", sample_code: "a" } as Sample;
const empty: UploadResult = { files: [], rejected: [] };

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (samples: Sample[]) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BulkImportDialog open onOpenChange={() => {}} projectId="p1" samples={samples} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const { rerender } = render(ui([existing]));
  const [filesInput, folderInput] = Array.from(document.body.querySelectorAll<HTMLInputElement>('input[type="file"]'));
  return { filesInput, folderInput, refreshSamples: (samples: Sample[]) => rerender(ui(samples)) };
}

const file = (name: string) => new File(["@r\nA\n+\nI\n"], name);

describe("BulkImportDialog", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
    vi.clearAllMocks();
    mocked.storage.mockResolvedValue(capacity(1e9));
    mocked.createSample.mockImplementation(async (_p, input) => ({ id: `new-${input.sample_code}`, sample_code: input.sample_code }) as Sample);
    mocked.uploadFiles.mockResolvedValue(empty);
  });

  it("proposes groups and creates nothing until confirmed", async () => {
    const user = userEvent.setup();
    const { folderInput, refreshSamples } = setup();
    await user.upload(folderInput, [
      file("A_S1_L001_R1_001.fastq.gz"),
      file("A_S1_L001_R2_001.fastq.gz"),
      file("B_R1.fastq.gz"),
      file("SampleSheet.csv"),
    ]);

    expect(screen.getAllByLabelText("Sample ID").map((i) => (i as HTMLInputElement).value)).toEqual(["A", "B"]);
    expect(screen.getByText("existing")).toBeInTheDocument();
    expect(screen.getByText("new")).toBeInTheDocument();
    expect(screen.getByText("R1 without its R2 file: B_R1.fastq.gz")).toBeInTheDocument();
    expect(screen.getByText("1 file(s) ignored (not FASTQ/FASTA): SampleSheet.csv")).toBeInTheDocument();
    expect(mocked.createSample).not.toHaveBeenCalled();
    expect(mocked.uploadFiles).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Create samples and upload" }));
    await screen.findByText("Finished: 2 of 2 group(s) uploaded.");
    // The project page refetches its samples afterwards; the dialog keeps describing what it did.
    refreshSamples([existing, { id: "new-B", sample_code: "B" } as Sample]);
    expect(screen.getByText(/2 sample\(s\): 1 new, 1 existing/)).toBeInTheDocument();
    expect(mocked.createSample).toHaveBeenCalledTimes(1);
    expect(mocked.createSample).toHaveBeenCalledWith("p1", { sample_code: "B", sequencing_technology: "unknown" });
    const uploads = mocked.uploadFiles.mock.calls.map(([id, files]) => [id, files.map((f) => f.name)]);
    expect(uploads).toEqual([
      ["sample-a", ["A_S1_L001_R1_001.fastq.gz", "A_S1_L001_R2_001.fastq.gz"]],
      ["new-B", ["B_R1.fastq.gz"]],
    ]);
  });

  it("blocks duplicate sample IDs and selections larger than the free space", async () => {
    const user = userEvent.setup();
    mocked.storage.mockResolvedValue(capacity(1));
    const { filesInput } = setup();
    await user.upload(filesInput, [file("X_R1.fq.gz"), file("Y_R1.fq.gz")]);

    const start = screen.getByRole("button", { name: "Create samples and upload" });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Not enough free space"));
    expect(start).toBeDisabled();

    const [, second] = screen.getAllByLabelText("Sample ID");
    await user.clear(second);
    await user.type(second, "x");
    expect(screen.getByText(/These sample IDs are used by more than one group: X/)).toBeInTheDocument();
    expect(start).toBeDisabled();
    expect(mocked.createSample).not.toHaveBeenCalled();
  });
});
