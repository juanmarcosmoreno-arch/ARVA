import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FailedCard } from "@/components/assembly/RunMonitor";
import { JobStatusBadge } from "@/components/domain/bits";
import { CancelJobButton } from "@/components/domain/JobControls";
import { ProjectBatchQc } from "@/components/domain/ProjectBatchQc";
import { ApiError, api } from "@/lib/api";
import { skipSummary } from "@/lib/batch";
import type { AnalysisJobDetail, BatchQcPlan, JobCheckpoint } from "@/lib/types";
import { useSettings } from "@/store/settings";

const job = (extra: Partial<AnalysisJobDetail>): AnalysisJobDetail => ({
  id: "job-1", project_id: "p", sample_id: "s", job_type: "flye_assembly", tool_name: "Flye", tool_version: "2.9.3", database_name: null, database_version: null,
  parameters: {}, input_raw_file_ids: ["f1"], output_paths: null, status: "running", started_at: "2026-10-28T13:00:00Z", finished_at: null, duration_seconds: null,
  log_text: "", error_message: null, created_at: "2026-10-28T13:00:00Z", commands: [], tool_path: null, result_summary: null, parent_job_id: null, qc_results: [], ...extra,
});
const kept: JobCheckpoint = {
  tool: "Flye", tool_version: "2.9.3", path: "checkpoints/p/s/job-1/flye", reason: "cancelled", resume_stage: "repeat",
  completed_stages: ["configure", "assembly", "consensus"], stages: [], size_bytes: 52_428_800, kept_at: "2026-10-28T13:30:00Z",
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

describe("Cancelling jobs", () => {
  it("asks for confirmation, says what happens to a running Flye run, then cancels", async () => {
    const cancel = vi.spyOn(api, "cancelJob").mockResolvedValue(job({ cancel_requested_at: "2026-10-28T13:10:00Z" }));
    renderWith(<CancelJobButton job={job({})} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/The worker stops Flye, with every process it started/)).toBeInTheDocument();
    expect(within(dialog).getByText(/ARVA keeps Flye's work folder/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep running" }));
    expect(cancel).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel job" }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("job-1"));
  });

  it("explains a queued job is only removed, and shows a running cancellation in progress", () => {
    const { unmount } = renderWith(<CancelJobButton job={job({ status: "pending", job_type: "seqkit_stats", tool_name: "SeqKit" })} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    expect(screen.getByText(/It has not started yet: it is removed from the queue/)).toBeInTheDocument();
    unmount();
    renderWith(<CancelJobButton job={job({ cancel_requested_at: "2026-10-28T13:10:00Z" })} />);
    expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
  });

  it("labels the cancelled status in both languages and renders nothing for finished jobs", () => {
    const { unmount } = renderWith(<JobStatusBadge status="cancelled" />);
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    unmount();
    useSettings.setState({ language: "es" });
    renderWith(
      <>
        <JobStatusBadge status="cancelled" />
        <JobStatusBadge status="running" cancelling />
        <CancelJobButton job={job({ status: "completed" })} />
      </>,
    );
    expect(screen.getByText("Cancelado")).toBeInTheDocument();
    expect(screen.getByText("Cancelando…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("Resuming a stopped Flye run", () => {
  it("offers resume and discard for a kept work folder, each after confirmation", async () => {
    const resume = vi.spyOn(api, "resumeJob").mockResolvedValue(job({ id: "job-2", status: "pending" }));
    const discard = vi.spyOn(api, "discardCheckpoint").mockResolvedValue(job({ status: "cancelled" }));
    renderWith(<FailedCard job={job({ status: "cancelled", checkpoint: kept, progress: { tool: "Flye", stage: "repeat", stage_index: 4, stages_total: 7, stages: [], started_at: null, stage_started_at: null, updated_at: null, elapsed_seconds: null, finished: true } })} />);
    expect(screen.getByText("Flye 2.9.3: assembly cancelled")).toBeInTheDocument();
    expect(screen.getByText(/Stopped during the repeat stage/)).toBeInTheDocument();
    expect(screen.getByText(/The run was cancelled\. Flye's work folder was kept \(50(\.0)? MB\): configure, assembly, consensus completed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume Flye run" }));
    const dialog = await screen.findByRole("dialog", { name: "Resume from the repeat stage?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start the resumed run" }));
    await waitFor(() => expect(resume).toHaveBeenCalledWith("job-1"));

    fireEvent.click(screen.getByRole("button", { name: "Discard work folder" }));
    const confirm = await screen.findByRole("dialog", { name: "Discard the kept work folder?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Discard work folder" }));
    await waitFor(() => expect(discard).toHaveBeenCalledWith("job-1"));
  });

  it("says why resume is not offered, and links a run already resumed", () => {
    const { unmount } = renderWith(<FailedCard job={job({ status: "failed", error_message: "Flye could not assemble the reads" })} />);
    expect(screen.getByText(/Resume is not offered for this run/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume Flye run" })).not.toBeInTheDocument();
    unmount();
    renderWith(<FailedCard job={job({ status: "cancelled" })} resumedBy={job({ id: "abcdef1234", status: "running" })} />);
    expect(screen.getByText("Resumed in a new run (job abcdef12).")).toBeInTheDocument();
  });
});

const plan = (extra: Partial<BatchQcPlan> = {}): BatchQcPlan => ({
  plan_id: "plan-1", analyses: ["sequence_stats", "fastqc"], include_derived: false, recompute: false, sample_ids: null,
  tools: [
    { analysis: "sequence_stats", tool: "arva-core.seqstats", version: "0.2.0", available: true, message: "" },
    { analysis: "fastqc", tool: "FastQC", version: "0.12.1", available: true, message: "" },
  ],
  samples: [
    {
      sample_id: "a", sample_code: "A", jobs: { sequence_stats: 1, fastqc: 0 }, total: 1,
      files: [
        { file_id: "f1", name: "a.fasta", origin: "imported", file_format: "fasta", decisions: { sequence_stats: "run", fastqc: "not_fastq" } },
        { file_id: "f2", name: "a.pod5", origin: "imported", file_format: "pod5", decisions: { sequence_stats: "raw_signal", fastqc: "raw_signal" } },
      ],
    },
    {
      sample_id: "b", sample_code: "B", jobs: { sequence_stats: 1, fastqc: 2 }, total: 3,
      files: [
        { file_id: "f3", name: "b_R1.fastq.gz", origin: "imported", file_format: "fastq_gz", decisions: { sequence_stats: "completed", fastqc: "run" } },
        { file_id: "f4", name: "b_R2.fastq.gz", origin: "imported", file_format: "fastq_gz", decisions: { sequence_stats: "run", fastqc: "run" } },
      ],
    },
  ],
  totals: { sequence_stats: 2, fastqc: 2 }, total_jobs: 4, samples_with_jobs: 2, dry_run: true, created_job_ids: [], ...extra,
});

describe("Batch QC", () => {
  it("counts skipped files once per reason", () => {
    expect(skipSummary(plan().samples[0])).toEqual([["not_fastq", 1], ["raw_signal", 1]]);
    expect(skipSummary(plan().samples[1])).toEqual([["completed", 1]]);
  });

  it("previews the jobs per sample and creates exactly the confirmed plan", async () => {
    const batch = vi.spyOn(api, "batchQc").mockImplementation(async (_p, body) =>
      body.dry_run ? plan({ analyses: body.analyses }) : plan({ dry_run: false, created_job_ids: ["j1", "j2", "j3", "j4"] }),
    );
    renderWith(<ProjectBatchQc projectId="p" />);
    await waitFor(() => expect(batch).toHaveBeenCalledWith("p", { analyses: ["sequence_stats"], include_derived: false, recompute: false, dry_run: true }));
    fireEvent.click(screen.getByLabelText("FastQC report"));
    await waitFor(() => expect(batch).toHaveBeenLastCalledWith("p", { analyses: ["sequence_stats", "fastqc"], include_derived: false, recompute: false, dry_run: true }));
    const rowA = (await screen.findByText("A")).closest("tr")!;
    expect(within(rowA).getAllByRole("cell").map((c) => c.textContent?.trim()).slice(1)).toEqual(["1", "0", "1"]);
    expect(within(rowA).getByText("Files skipped — FASTA (FastQC needs FASTQ): 1; POD5 raw signal (no reads): 1")).toBeInTheDocument();
    fireEvent.click(within(screen.getByText("B").closest("tr")!).getByRole("button", { name: "Show files" }));
    expect(within(screen.getByText("b_R1.fastq.gz").closest("tr")!).getByText("with a completed result")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create 4 jobs…" }));
    const dialog = await screen.findByRole("dialog", { name: "Create 4 jobs in 2 samples?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create jobs" }));
    await waitFor(() =>
      expect(batch).toHaveBeenCalledWith("p", { analyses: ["sequence_stats", "fastqc"], include_derived: false, recompute: false, dry_run: false, plan_id: "plan-1" }),
    );
    expect(await screen.findByText(/4 jobs created/)).toBeInTheDocument();
  });

  it("refreshes the preview when the plan changed, and blocks a missing tool", async () => {
    let calls = 0;
    vi.spyOn(api, "batchQc").mockImplementation(async (_p, body) => {
      if (!body.dry_run) throw new ApiError(409, "The files or results changed since the preview");
      calls += 1;
      return plan({ plan_id: `plan-${calls}` });
    });
    renderWith(<ProjectBatchQc projectId="p" />);
    fireEvent.click(await screen.findByRole("button", { name: "Create 4 jobs…" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Create jobs" }));
    expect(await screen.findByText(/changed since the preview, which is now updated/)).toBeInTheDocument();
    await waitFor(() => expect(calls).toBe(2));

    vi.spyOn(api, "batchQc").mockResolvedValue(plan({ tools: [{ analysis: "fastqc", tool: "FastQC", version: null, available: false, message: "not installed" }] }));
    renderWith(<ProjectBatchQc projectId="q" />);
    expect(await screen.findByText(/FastQC is not available \(not installed\)/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Create 4 jobs…" }).at(-1)).toBeDisabled();
  });
});
