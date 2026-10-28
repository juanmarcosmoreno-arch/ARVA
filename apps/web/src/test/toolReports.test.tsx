import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectQcReport } from "@/components/domain/ProjectQcReport";
import { api } from "@/lib/api";
import type { AnalysisJob, MultiqcSummary, Tool } from "@/lib/types";
import { ToolsPage } from "@/pages/ToolsPage";
import { useSettings } from "@/store/settings";

const tool = (overrides: Partial<Tool>): Tool => ({
  id: "multiqc", name: "MultiQC", description: "", homepage: "https://multiqc.info", license: "GPL-3.0", citation: "", citation_url: "",
  categories: [], input_formats: [], output_formats: [], min_version: "1.35", tested_versions: ["1.35"], install: {},
  status: "available", path: "/x/multiqc", version: "1.35", version_validated: true, message: "", reason: null, ...overrides,
});

const summary: MultiqcSummary = {
  multiqc_version: "1.35",
  report_creation_date: null,
  modules: ["fastp"],
  samples: [{ name: "ISO-001 R1+R2", sample_id: "s1", sample_code: "ISO-001" }],
  versions: { reported_by_multiqc: {}, arva_jobs: { fastp: ["0.23.4"] } },
  general_stats: {
    columns: [{ module: "fastp", key: "after_filtering_q30_rate", title: "% > Q30", description: "", unit: "fraction", origin: "tool", hidden: false }],
    rows: [{ name: "ISO-001 R1+R2", values: { fastp: { after_filtering_q30_rate: 0.698063 } } }],
    unmapped: [],
  },
};

const report = (id: string, status: AnalysisJob["status"], finished: string, extra: Partial<AnalysisJob> = {}): AnalysisJob => ({
  id, project_id: "p", sample_id: null, job_type: "multiqc", tool_name: "MultiQC", tool_version: "1.35", database_name: null,
  database_version: null, parameters: { inputs: [] }, input_raw_file_ids: [], output_paths: [], status, started_at: null,
  finished_at: finished, duration_seconds: null, log_text: "", error_message: null, created_at: finished, commands: [], tool_path: null,
  result_summary: null, parent_job_id: null, ...extra,
});

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

describe("Tools page", () => {
  it("shows the reason an old MultiQC is rejected in the interface language", async () => {
    useSettings.setState({ language: "es" });
    const english = "Version 1.18 is older than the minimum supported 1.35. Older releases such as the Ubuntu/Debian 1.18 package…";
    vi.spyOn(api, "tools").mockResolvedValue([
      tool({ status: "incompatible", version: "1.18", version_validated: false, message: english, reason: "multiqc_too_old" }),
      tool({ id: "nanoplot", name: "NanoPlot", status: "failed", version: "1.48.0", min_version: "1.48.0", message: "x", reason: "nanomath_replaced" }),
    ]);
    vi.spyOn(api, "libraries").mockResolvedValue([]);
    renderWith(<ToolsPage />);
    expect(await screen.findByText(/El MultiQC encontrado \(1\.18\) no puede usarse: ARVA necesita 1\.35/)).toBeInTheDocument();
    expect(screen.getByText(/NanoPlot 1\.48\.0 importa un módulo nanomath/)).toBeInTheDocument();
    expect(screen.queryByText(english)).not.toBeInTheDocument();
  });
});

describe("Project QC report card", () => {
  it("keeps the general statistics of the last completed report when the newest run failed", async () => {
    vi.spyOn(api, "tools").mockResolvedValue([tool({})]);
    vi.spyOn(api, "multiqcPreview").mockResolvedValue({
      selection_rule: "", modules: [], sample_ids: [], include_derived: false, inputs: [], excluded: [],
    });
    vi.spyOn(api, "projectJobs").mockResolvedValue([
      report("new", "failed", "2026-02-01T00:00:00Z", { error_message: "MultiQC exited with status 1" }),
      report("old", "completed", "2026-01-01T00:00:00Z", { result_summary: summary as unknown as Record<string, unknown> }),
    ]);
    renderWith(<ProjectQcReport projectId="p" samples={[]} />);
    const section = (await screen.findByRole("heading", { name: "Most recent completed report" })).closest("section")!;
    expect(screen.getByText(/MultiQC exited with status 1/)).toBeInTheDocument();
    // ARVA's own title above the raw fraction, never MultiQC's "% > Q30".
    const table = within(section).getByRole("table");
    expect(within(table).getByText("Q30 bases after filtering")).toBeInTheDocument();
    expect(within(table).getByText("0.6981")).toBeInTheDocument();
    expect(within(section).queryByText("% > Q30")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Previous reports" })).not.toBeInTheDocument();
  });
});
