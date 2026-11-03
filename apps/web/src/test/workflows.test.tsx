import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ParamPanel } from "@/components/workflows/ParamPanel";
import { RunDialog } from "@/components/workflows/RunDialog";
import { RunView } from "@/components/workflows/RunView";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { api } from "@/lib/api";
import {
  connectionProblem,
  fieldProblem,
  flyeGuardText,
  newNodeId,
  nodeProgress,
  nodeTools,
  paramFields,
  setPath,
  type Catalogue,
  type NodeKind,
  type RunDetail,
  type RunItem,
  type RunPlan,
  type WorkflowRead,
} from "@/lib/workflows";
import { useSettings } from "@/store/settings";

// jsdom has no ResizeObserver; React Flow measures its viewport with one.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const tool = (id: string, available = true) => ({ id, name: id, version: "1", available, status: available ? "available" : "not_installed", reason: null, reason_params: {}, message: "" });

// Shapes as GET /workflows/catalogue sends them (ports and scopes from arva_core.workflow.NODES).
const kind = (k: Partial<NodeKind> & Pick<NodeKind, "kind">): NodeKind => ({
  scope: "sample", category: "assembly", source: false, internal: false, tool_param: null, tools: {}, inputs: [], outputs: [],
  params_schema: { properties: {} }, defaults: {}, ...k,
});
const KINDS = new Map<string, NodeKind>([
  ["reads_short_input", kind({ kind: "reads_short_input", source: true, outputs: [{ name: "reads", type: "reads_short" }] })],
  ["reads_long_input", kind({ kind: "reads_long_input", source: true, outputs: [{ name: "reads", type: "reads_long" }] })],
  ["flye", kind({ kind: "flye", inputs: [{ name: "reads", accepts: ["reads_long"], required: true, collection: false }], outputs: [{ name: "assembly", type: "assembly" }], tools: { "": [tool("flye")] } })],
  ["quast", kind({ kind: "quast", inputs: [{ name: "assembly", accepts: ["assembly"], required: true, collection: false }] })],
  ["comparison_set", kind({ kind: "comparison_set", scope: "set", internal: true, inputs: [{ name: "genomes", accepts: ["assembly", "annotation"], required: true, collection: true }], outputs: [{ name: "set", type: "comparison_set" }] })],
  ["comparative_ani", kind({ kind: "comparative_ani", scope: "set", tool_param: "method", inputs: [{ name: "set", accepts: ["comparison_set"], required: true, collection: false }], tools: { skani: [tool("skani", false)], fastani: [tool("fastani")] } })],
]);
const NODES = [
  { id: "short", kind: "reads_short_input" }, { id: "long", kind: "reads_long_input" }, { id: "flye", kind: "flye" },
  { id: "quast", kind: "quast" }, { id: "set", kind: "comparison_set" }, { id: "ani", kind: "comparative_ani" },
];
const edge = (source: string, source_port: string, target: string, target_port: string) => ({ source, source_port, target, target_port });

describe("connection rules (the same as arva_core.workflow.edge_problem)", () => {
  it("refuses incompatible types, scope changes, taken inputs and cycles", () => {
    expect(connectionProblem(KINDS, NODES, [], edge("short", "reads", "flye", "reads"))).toBe("wf.connect.type");
    expect(connectionProblem(KINDS, NODES, [], edge("long", "reads", "flye", "reads"))).toBeNull();
    const taken = [edge("long", "reads", "flye", "reads")];
    expect(connectionProblem(KINDS, NODES, taken, edge("long", "reads", "flye", "reads"))).toBe("wf.connect.taken");
    expect(connectionProblem(KINDS, NODES, [], edge("flye", "assembly", "set", "genomes"))).toBeNull();
    expect(connectionProblem(KINDS, NODES, [edge("flye", "assembly", "set", "genomes")], edge("flye", "assembly", "set", "genomes"))).toBeNull();
    expect(connectionProblem(KINDS, NODES, [], edge("set", "set", "quast", "assembly"))).toBe("wf.connect.type");
    expect(connectionProblem(KINDS, NODES, [], edge("flye", "assembly", "flye", "reads"))).toBe("wf.connect.self");
    expect(connectionProblem(KINDS, NODES, [], edge("flye", "nope", "quast", "assembly"))).toBe("wf.connect.port");
  });

  it("names new nodes uniquely and follows the method parameter for tools", () => {
    expect(newNodeId("flye", [{ id: "flye_1" }, { id: "flye_2" }])).toBe("flye_3");
    expect(nodeTools(KINDS.get("comparative_ani")!, { method: "skani" })[0].available).toBe(false);
    expect(nodeTools(KINDS.get("comparative_ani")!, { method: "fastani" })[0].id).toBe("fastani");
  });
});

// Fragment of the JSON schema pydantic writes for FastpRequest / PolishingRequest (refs, anyOf null, Literal enums).
const SCHEMA = {
  properties: {
    params: { $ref: "#/$defs/P" },
    strategy: { enum: ["racon", "pilon", "hybrid"], type: "string" },
    threads: { anyOf: [{ type: "integer", maximum: 128, minimum: 1 }, { type: "null" }], default: null },
    fix: { type: "array", items: { enum: ["snps"], type: "string" } },
  },
  $defs: { P: { properties: { qualified_quality_phred: { type: "integer", minimum: 0, maximum: 93 }, error_threshold: { type: "number", exclusiveMinimum: 0, maximum: 1 }, dedup: { type: "boolean" } } } },
};

describe("parameter fields from the analysis's request model", () => {
  it("flattens nested models and reads ranges, nullability and enums", () => {
    const fields = paramFields(SCHEMA);
    expect(fields.map((f) => [f.path, f.kind])).toEqual([
      ["params.qualified_quality_phred", "integer"], ["params.error_threshold", "number"], ["params.dedup", "boolean"],
      ["strategy", "enum"], ["threads", "integer"], ["fix", "json"],
    ]);
    const q = fields[0];
    expect(fieldProblem(q, 94)).toBe("wf.param.range");
    expect(fieldProblem(q, 2.5)).toBe("wf.param.integer");
    expect(fieldProblem(q, 20)).toBeNull();
    expect(fieldProblem(fields[1], 0)).toBe("wf.param.range");
    expect(fieldProblem(fields[4], null)).toBeNull();
    expect(fieldProblem(fields[3], null)).toBe("wf.param.required");
    expect(setPath({ params: { a: 1 } }, "params.b", 2)).toEqual({ params: { a: 1, b: 2 } });
  });

  beforeEach(() => useSettings.setState({ language: "es" }));

  it("renders the fields in Spanish and shows the server's refusal", () => {
    const onChange = vi.fn();
    renderWith(<ParamPanel kind={kind({ kind: "fastp", params_schema: SCHEMA })} params={{ params: { qualified_quality_phred: 15 }, strategy: "racon" }}
      problems={[{ code: "wf_param", node: "n", params: { field: "threads", message: "Input should be ≤ 128" } }]} onChange={onChange} />);
    expect(screen.getByText("Permitido: de 0 a 93")).toBeInTheDocument();
    expect(screen.getByText(/Rechazado por las comprobaciones del análisis/)).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("15"), { target: { value: "120" } });
    expect(onChange).toHaveBeenCalledWith({ params: { qualified_quality_phred: 120 }, strategy: "racon" });
  });
});

const item = (node: string, sample: string | null, status: RunItem["status"], extra: Partial<RunItem> = {}): RunItem => ({
  id: `${node}-${sample}`, node_id: node, node_kind: node === "trim" ? "fastp" : "reads_short_input", sample_id: sample, status, attempt: 1,
  job_id: null, job_ids: [], job_status: null, tool: null, tool_version: null, duration_seconds: null, progress: null, outputs: null,
  error: null, reserved: null, reused_from_item_id: null, depends_on: [], started_at: null, finished_at: null, ...extra,
});

it("counts each node's items by status", () => {
  const p = nodeProgress([item("trim", "a", "completed"), item("trim", "b", "failed"), item("trim", "c", "running")]);
  expect(p.get("trim")).toMatchObject({ completed: 1, failed: 1, running: 1, total: 3 });
});

describe("RunView", () => {
  beforeEach(() => useSettings.setState({ language: "es" }));

  it("shows progress, the error summary in Spanish and the exports", async () => {
    const counts = { waiting: 0, queued: 0, running: 0, completed: 1, failed: 1, cancelled: 0, skipped: 0 };
    const run: RunDetail = {
      id: "r1", project_id: "p", name: "Recorte", status: "completed_with_errors", priority: 0,
      settings: { priority: 0, max_concurrent: 1, threads_per_job: 4, memory_per_job_gb: 8, max_retries: 1, profile: "balanced", budget_threads: 4, budget_memory_gb: 16 },
      parent_run_id: null, workflow_id: "w", workflow_name: "Trim", version: 2, definition_sha256: "f".repeat(64), samples: 2, counts, total: 2,
      jobs_created: 3, reused: 0, job_seconds: 12.5, created_at: "2026-11-02T10:00:00Z", started_at: null, finished_at: null, branch_changes: null,
      estimated: { threads_per_job: 4, memory_per_job_gb: 8, concurrency: 1 },
      definition: { format: "arva-workflow", format_version: 1, nodes: [{ id: "reads", kind: "reads_short_input", params: {}, position: { x: 0, y: 0 } }, { id: "trim", kind: "fastp", params: {}, position: { x: 260, y: 0 } }], edges: [{ source: "reads", source_port: "reads", target: "trim", target_port: "reads" }] },
      tools: {}, sample_codes: { a: "A", b: "B" },
      items: [item("reads", "a", "completed"), item("reads", "b", "completed"), item("trim", "a", "completed", { duration_seconds: 4.5 }),
        item("trim", "b", "failed", { attempt: 2, error: { code: "input_missing", params: { file_id: "x" }, message: "input file x no longer exists" } })],
      per_sample: [{ sample_id: "a", sample_code: "A", counts: { ...counts, failed: 0 }, total: 1, seconds: 4.5 }, { sample_id: "b", sample_code: "B", counts: { ...counts, completed: 0 }, total: 1, seconds: 0 }],
      errors: [{ item_id: "trim-b", node_id: "trim", node_kind: "fastp", sample_id: "b", sample_code: "B", status: "failed", code: "input_missing", params: { file_id: "x" }, message: "input file x no longer exists", job_id: "job12345678" }],
      correlation_id: "c",
    };
    vi.spyOn(api, "batch").mockResolvedValue(run);
    vi.spyOn(api, "batchErrors").mockResolvedValue([]);
    const catalogue: Catalogue = { port_types: [], kinds: [kind({ kind: "reads_short_input", source: true, outputs: [{ name: "reads", type: "reads_short" }] }), kind({ kind: "fastp", inputs: [{ name: "reads", accepts: ["reads_short"], required: true, collection: false }], outputs: [{ name: "reads", type: "reads_short" }] })], templates: [], nextflow: { generated: false, reason_code: "" } };
    renderWith(<RunView runId="r1" catalogue={catalogue} />);
    await waitFor(() => expect(screen.getByText("Recorte")).toBeInTheDocument());
    expect(screen.getByText("terminada con errores")).toBeInTheDocument();
    expect(screen.getByText("el archivo de entrada x ya no existe")).toBeInTheDocument();
    expect(screen.getByText("Errores (1)")).toBeInTheDocument();
    expect(screen.getByText("Tabla consolidada").closest("a")).toHaveAttribute("href", "/api/v1/batches/r1/table.csv");
    expect(screen.getByText("Tabla consolidada").closest("a")?.querySelector("button")).toBeNull();
    expect(screen.getByText("Informe").closest("a")?.getAttribute("href")).toBe("/api/v1/batches/r1/report.html?lang=es");
    // Grid cells carry their status as text and can be focused, not only coloured.
    const cells = screen.getAllByRole("img").filter((c) => c.getAttribute("tabindex") === "0");
    expect(cells.length).toBeGreaterThan(0);
    expect(cells.some((c) => /^(completado|fallido)/.test(c.getAttribute("aria-label") ?? ""))).toBe(true);

    // A branch is previewed before it can be created, and its confirmation is cleared by any parameter change.
    const preview = vi.spyOn(api, "branchPreview").mockResolvedValue({
      node_id: "trim", changes: [{ node: "trim", path: "params.x", before: 1, after: 2 }], problems: [], rerun: [{ node: "trim", kind: "fastp", scope: "sample" }],
      reused: ["reads"], samples: 2, jobs: 2, settings: run.settings, concurrency: 1, tools: { fastp: { name: "fastp", version: "0.23.4", status: "available" } },
    });
    const branch = vi.spyOn(api, "branchBatch");
    fireEvent.click(screen.getAllByRole("button", { name: /Nueva rama/ })[0]);
    await waitFor(() => expect(screen.getByText(/2 trabajos nuevos/)).toBeInTheDocument());
    expect(preview).toHaveBeenCalledWith("r1", { node_id: "trim", params: {} });
    expect(screen.getByText(/perfil Equilibrado/)).toBeInTheDocument();
    const create = screen.getByRole("button", { name: /Crear rama/ });
    expect(create).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Crear la rama/ }));
    expect(create).toBeEnabled();
    expect(branch).not.toHaveBeenCalled();
  });
});

it("has guide entries for the builder and the queue in both languages", () => {
  for (const id of ["workflow_builder", "batch_queue"] as const) {
    expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
    expect(GUIDE_BY_ID[id].es.limitations.length).toBeGreaterThan(40);
  }
});

describe("run options", () => {
  beforeEach(() => useSettings.setState({ language: "es" }));

  it("offers the polishing strategy and Flye's memory guard, sends the choice and shows what it changes", async () => {
    const settings = { priority: 0, max_concurrent: 1, threads_per_job: 4, memory_per_job_gb: 3, max_retries: 0, profile: "balanced", budget_threads: 4, budget_memory_gb: 3 };
    const plan: RunPlan = { version: 1, definition_sha256: "f", samples: [{ sample_id: "s", sample_code: "S27", sources: {}, ready: true }], ready_samples: 1, jobs: 3, settings, tools: {}, problems: [], concurrency: 1,
      options: { polishing_strategy: { kind: "polishing", param: "strategy", nodes: 1, value: "racon", choices: ["racon", "medaka"] }, flye_memory_guard: { kind: "flye", param: "memory_guard", nodes: 1, value: "auto" } }, option_changes: [] };
    vi.spyOn(api, "projects").mockResolvedValue([{ id: "p", name: "Cepas" }] as Awaited<ReturnType<typeof api.projects>>);
    vi.spyOn(api, "samples").mockResolvedValue([{ id: "s", sample_code: "S27" }] as Awaited<ReturnType<typeof api.samples>>);
    const preview = vi.spyOn(api, "batchPreview").mockImplementation(async (body) =>
      body.options?.polishing_strategy ? { ...plan, option_changes: [{ node: "polish", option: "polishing_strategy", path: "strategy", before: "racon", after: "medaka" }] } : plan);
    const workflow = { id: "w", name: "Genoma completo", latest: { version: 1 } } as WorkflowRead;
    renderWith(<RunDialog open onOpenChange={() => {}} workflow={workflow} />);
    const strategy = await screen.findByRole("combobox", { name: "Estrategia de pulido" });
    expect(screen.getByRole("option", { name: "Como está guardado (Lecturas largas: Racon)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Como está guardado (Activada (solo si puede no caber))" })).toBeInTheDocument();
    // Only what the steps' long reads allow: no Pilon or hybrid for a long-read workflow.
    expect(screen.queryByRole("option", { name: "Lecturas cortas: Pilon" })).not.toBeInTheDocument();
    fireEvent.change(strategy, { target: { value: "medaka" } });
    await waitFor(() => expect(screen.getByText(/Esta ejecución cambia: polish.strategy: "racon" → "medaka"/)).toBeInTheDocument());
    expect(preview).toHaveBeenLastCalledWith(expect.objectContaining({ options: { polishing_strategy: "medaka" }, confirmed: false }));
  });

  it("says what Flye's memory guard did for a step", () => {
    const t = (key: string, p?: Record<string, unknown>) => `${key}${p ? JSON.stringify(p) : ""}`;
    const estimate = { verdict: "may_not_fit" as const, estimate_gb: 3.59, available_gb: 3 };
    expect(flyeGuardText(t as never, { guard: "auto", estimate, applied: { asm_coverage: 40, genome_size_bp: 2_800_000 }, not_applied: null })).toBe('wf.flyeGuard.applied{"cov":40,"gb":3.59,"available":3}');
    expect(flyeGuardText(t as never, { guard: "auto", estimate, applied: null, not_applied: "no_genome_size" })).toBe("wf.flyeGuard.no_genome_size");
    expect(flyeGuardText(t as never, { guard: "off", estimate, applied: null, not_applied: null })).toBeNull();
    expect(flyeGuardText(t as never, { guard: "auto", estimate: { ...estimate, verdict: "fits" }, applied: null, not_applied: null })).toBeNull();
  });
});
