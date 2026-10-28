import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BulkImportDialog } from "@/components/domain/BulkImportDialog";
import { api } from "@/lib/api";
import type { RawFile, Sample, StorageCapacity, UploadResult } from "@/lib/types";
import { useSettings } from "@/store/settings";

vi.mock("@/lib/api", () => ({
  api: { storage: vi.fn(), createSample: vi.fn(), uploadFiles: vi.fn() },
}));

const mocked = vi.mocked(api);
const capacity = (available: number, factor: 1 | 2 = 1): StorageCapacity => ({
  storage_root: "/data",
  free_bytes: available,
  total_bytes: 1e12,
  min_free_bytes: 0,
  available_for_data_bytes: available,
  upload_overhead_factor: factor,
});
const existing = { id: "sample-a", sample_code: "a" } as Sample;
const stored = (name: string) =>
  ({ id: `f-${name}`, original_filename: name, file_format: "fastq_gz", size_bytes: 10, is_valid: true, validation_message: "ok" }) as RawFile;
const accepted = async (_id: string, files: File[]): Promise<UploadResult> => ({ files: files.map((f) => stored(f.name)), rejected: [] });
const rejectedAll =
  (code: UploadResult["rejected"][number]["code"], reason: string) =>
  async (_id: string, files: File[]): Promise<UploadResult> => ({ files: [], rejected: files.map((f) => ({ filename: f.name, reason, code })) });

function setup(samples: Sample[] = [existing]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (list: Sample[]) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BulkImportDialog open onOpenChange={() => {}} projectId="p1" samples={list} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const { rerender } = render(ui(samples));
  const [filesInput, folderInput] = Array.from(document.body.querySelectorAll<HTMLInputElement>('input[type="file"]'));
  return { filesInput, folderInput, refreshSamples: (list: Sample[]) => rerender(ui(list)) };
}

const file = (name: string) => new File(["@r\nA\n+\nI\n"], name);
const startButton = () => screen.getByRole("button", { name: "Create samples and upload" });

describe("BulkImportDialog", () => {
  beforeEach(() => {
    useSettings.setState({ language: "en" });
    vi.clearAllMocks();
    mocked.storage.mockResolvedValue(capacity(1e9));
    mocked.createSample.mockImplementation(async (_p, input) => ({ id: `new-${input.sample_code}`, sample_code: input.sample_code }) as Sample);
    mocked.uploadFiles.mockImplementation(accepted);
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
    expect(screen.getByText("1 file(s) ignored (not FASTQ/FASTA/POD5): SampleSheet.csv")).toBeInTheDocument();
    expect(mocked.createSample).not.toHaveBeenCalled();
    expect(mocked.uploadFiles).not.toHaveBeenCalled();

    await user.click(startButton());
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

  it("imports POD5 raw-signal files as their own sample group", async () => {
    const user = userEvent.setup();
    const { folderInput } = setup([]);
    await user.upload(folderInput, [file("run7_barcode02.pod5"), file("run7_barcode02.fastq.gz"), file("reads.fast5")]);
    expect(screen.getAllByLabelText("Sample ID").map((i) => (i as HTMLInputElement).value)).toEqual(["run7_barcode02"]);
    expect(screen.getByText("1 file(s) ignored (not FASTQ/FASTA/POD5): reads.fast5")).toBeInTheDocument();
    await user.click(startButton());
    await screen.findByText(/^Finished:/);
    expect(mocked.uploadFiles.mock.calls.map(([, files]) => files.map((f) => f.name))).toEqual([["run7_barcode02.fastq.gz", "run7_barcode02.pod5"]]);
  });

  it("blocks duplicate sample IDs and selections larger than the free space", async () => {
    const user = userEvent.setup();
    mocked.storage.mockResolvedValue(capacity(1));
    const { filesInput } = setup();
    await user.upload(filesInput, [file("X_R1.fq.gz"), file("Y_R1.fq.gz")]);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Not enough free space"));
    expect(startButton()).toBeDisabled();

    const [, second] = screen.getAllByLabelText("Sample ID");
    await user.clear(second);
    await user.type(second, "x");
    expect(screen.getByText(/These sample IDs are used by more than one group: X/)).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
    expect(mocked.createSample).not.toHaveBeenCalled();
  });

  it("counts the spooled copy when uploads are buffered on the data disk", async () => {
    const user = userEvent.setup();
    const bytes = file("X.fq").size;
    mocked.storage.mockResolvedValue(capacity(bytes + 1, 2));
    const { filesInput } = setup();
    await user.upload(filesInput, [file("X.fq")]);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("through the browser needs"));
    expect(screen.getByText(/needs .* while uploading \(buffered on the same disk\) · Usable for new data/)).toBeInTheDocument();
    expect(startButton()).toBeDisabled();
  });

  it("uploads into the exactly matching sample when codes differ only by case", async () => {
    const user = userEvent.setup();
    const upper = { id: "upper", sample_code: "S1" } as Sample;
    const lower = { id: "lower", sample_code: "s1" } as Sample;
    const { filesInput } = setup([upper, lower]);
    await user.upload(filesInput, [file("S1_R1_001.fastq.gz")]);
    expect(screen.getByText("existing")).toBeInTheDocument();
    await user.click(startButton());
    await screen.findByText(/^Finished:/);
    expect(mocked.uploadFiles.mock.calls[0][0]).toBe("upper");
    expect(mocked.createSample).not.toHaveBeenCalled();
  });

  it("asks for the exact ID when several samples match ignoring case", async () => {
    const user = userEvent.setup();
    const { filesInput } = setup([{ id: "1", sample_code: "Ab" } as Sample, { id: "2", sample_code: "aB" } as Sample]);
    await user.upload(filesInput, [file("AB.fastq.gz")]);
    expect(screen.getByRole("alert")).toHaveTextContent("Several existing samples match AB when case is ignored (Ab, aB)");
    expect(startButton()).toBeDisabled();

    const [input] = screen.getAllByLabelText("Sample ID");
    await user.clear(input);
    await user.type(input, "aB");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("existing")).toBeInTheDocument();
    expect(startButton()).toBeEnabled();
  });

  it("does not count a group whose files were all rejected as uploaded", async () => {
    const user = userEvent.setup();
    mocked.uploadFiles.mockImplementation(async (id, files) =>
      id === "sample-a" ? rejectedAll("duplicate", "identical content is already registered")(id, files) : accepted(id, files),
    );
    const { filesInput } = setup();
    await user.upload(filesInput, [file("a.fastq.gz"), file("b.fastq.gz")]);
    await user.click(startButton());
    await screen.findByText("Finished: 1 of 2 group(s) uploaded. 1 with every file rejected (nothing stored).");
    expect(screen.getByText("Nothing stored: every file was rejected")).toBeInTheDocument();
  });

  it.each([
    ["an insufficient-space rejection", () => mocked.uploadFiles.mockImplementationOnce(rejectedAll("insufficient_storage", "Not enough free space"))],
    ["HTTP 507", () => mocked.uploadFiles.mockRejectedValueOnce(Object.assign(new Error("Not enough free space"), { status: 507 }))],
  ])("stops creating samples after %s", async (_label, firstUpload) => {
    const user = userEvent.setup();
    firstUpload();
    const { filesInput } = setup([]);
    await user.upload(filesInput, [file("A.fastq.gz"), file("B.fastq.gz"), file("C.fastq.gz")]);
    await user.click(startButton());
    await screen.findByText("Finished: 0 of 3 group(s) uploaded.", { exact: false });
    expect(mocked.createSample).toHaveBeenCalledTimes(1);
    expect(mocked.uploadFiles).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Not started")).toHaveLength(2);
    expect(screen.getByText(/2 not started\./)).toBeInTheDocument();
    expect(screen.getByText(/no usable space left, so the remaining groups were not started/)).toBeInTheDocument();
  });

  it("shows the links to the samples only after every group has run", async () => {
    const user = userEvent.setup();
    let release: (r: UploadResult) => void = () => {};
    mocked.uploadFiles
      .mockImplementationOnce(accepted)
      .mockImplementationOnce(() => new Promise<UploadResult>((resolve) => (release = resolve)));
    const { filesInput } = setup([]);
    await user.upload(filesInput, [file("A.fastq.gz"), file("B.fastq.gz")]);
    await user.click(startButton());
    await screen.findByText("Done");
    expect(screen.queryByRole("link", { name: "Open sample" })).not.toBeInTheDocument();

    release({ files: [stored("B.fastq.gz")], rejected: [] });
    await screen.findByText("Finished: 2 of 2 group(s) uploaded.");
    expect(screen.getAllByRole("link", { name: "Open sample" })).toHaveLength(2);
  });

  it("translates the pairing warnings", async () => {
    const user = userEvent.setup();
    useSettings.setState({ language: "es" });
    const { filesInput } = setup();
    const lanes = [1, 2, 3].map((l) => file(`Z_S1_L00${l}_R1_001.fastq.gz`));
    await user.upload(filesInput, [file("A_R1.fq"), ...lanes]);
    expect(screen.getByText("R1 sin su archivo R2: A_R1.fq")).toBeInTheDocument();
    expect(screen.getByText("3 archivos R1 en una misma muestra: comprueba que van juntos (p. ej., varios carriles o corridas)")).toBeInTheDocument();
  });
});
