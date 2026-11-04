/** Workflow Builder and batch runs: the API's shapes and the pure helpers the editor and dashboards use. The rules
 * for connecting ports mirror arva_core.workflow.edge_problem; the server checks them again on every save. */
import { dictionaries, type Translate, type TranslationKey } from "@/i18n";

export type PortType = "reads_long" | "reads_short" | "assembly" | "annotation" | "comparison_set" | "alignment" | "tree" | "species_call" | "mlst_call";

export interface PortIn {
  name: string;
  accepts: PortType[];
  required: boolean;
  collection: boolean;
}

export interface PortOut {
  name: string;
  type: PortType;
}

export interface ToolState {
  id: string;
  name: string;
  version: string | null;
  available: boolean;
  status: string;
  reason: string | null;
  reason_params: Record<string, string>;
  message: string;
}

export interface JsonSchema {
  type?: string;
  title?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: (string | number)[];
  const?: string | number;
  anyOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  items?: JsonSchema;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  default?: unknown;
  pattern?: string;
  maxLength?: number;
}

export interface NodeKind {
  kind: string;
  scope: "sample" | "set";
  category: string;
  source: boolean;
  internal: boolean;
  tool_param: string | null;
  tools: Record<string, ToolState[]>;
  inputs: PortIn[];
  outputs: PortOut[];
  params_schema: JsonSchema;
  defaults: Record<string, unknown>;
}

export interface Problem {
  code: string;
  node: string | null;
  params: Record<string, string | number>;
}

export interface WfNode {
  id: string;
  kind: string;
  label?: string | null;
  params: Record<string, unknown>;
  position: { x: number; y: number };
}

export interface WfEdge {
  id?: string | null;
  source: string;
  source_port: string;
  target: string;
  target_port: string;
}

export interface Definition {
  format: "arva-workflow";
  format_version: 1;
  nodes: WfNode[];
  edges: WfEdge[];
}

export interface Template {
  key: string;
  definition: Definition;
  unavailable: Problem[];
  needs_parameters: Problem[];
}

export interface Catalogue {
  port_types: PortType[];
  kinds: NodeKind[];
  templates: Template[];
  nextflow: { generated: boolean; reason_code: string };
}

export interface WorkflowVersionBrief {
  version: number;
  definition_sha256: string;
  note: string | null;
  created_at: string;
}

export interface WorkflowRead {
  id: string;
  name: string;
  description: string | null;
  template_key: string | null;
  duplicated_from_id: string | null;
  created_at: string;
  updated_at: string;
  versions: WorkflowVersionBrief[];
  latest: { version: number; definition: Definition; definition_sha256: string } | null;
  selected?: { version: number; definition: Definition; definition_sha256: string };
  problems: Problem[];
  runs: number;
}

export interface ValidationResult {
  definition: Definition;
  problems: Problem[];
  unavailable: Problem[];
  definition_sha256: string;
}

export interface BatchSettings {
  priority: number;
  max_concurrent: number;
  threads_per_job: number | null;
  memory_per_job_gb: number | null;
  max_retries: number;
}

export interface RunSettings extends BatchSettings {
  threads_per_job: number;
  memory_per_job_gb: number;
  profile: string;
  budget_threads: number;
  budget_memory_gb: number;
  /** The run options chosen when it started, and the parameters they changed (absent: none). */
  run_options?: RunOptions;
  option_changes?: OptionChange[];
}

/** Run options (BatchRunOptionsIn): one parameter set on every node of a kind for one run; null keeps the saved value. */
export interface RunOptions {
  polishing_strategy?: "racon" | "medaka" | "pilon" | "hybrid" | null;
  flye_memory_guard?: "off" | "auto" | null;
}

export interface OptionChange {
  node: string;
  option: keyof RunOptions;
  path: string;
  before: unknown;
  after: unknown;
}

/** The run options a definition offers: its nodes of that kind and the value they hold (null: they differ). */
export type OfferedOptions = Partial<Record<keyof RunOptions, { kind: string; param: string; nodes: number; value: string | null; choices?: string[] }>>;

export interface SourcePick {
  ok: boolean;
  outputs?: Record<string, Record<string, unknown>>;
  code?: string;
  params?: Record<string, string | number>;
  message?: string;
}

export interface RunPlan {
  version: number;
  definition_sha256: string;
  samples: { sample_id: string; sample_code: string; sources: Record<string, SourcePick>; ready: boolean }[];
  ready_samples: number;
  jobs: number;
  settings: RunSettings;
  tools: Record<string, { name: string; version: string | null; status: string }>;
  problems: Problem[];
  concurrency: number;
  options?: OfferedOptions;
  option_changes?: OptionChange[];
}

/** What a branch would run again and reuse (POST /batches/{id}/branch/preview). */
export interface BranchPlan {
  node_id: string;
  changes: { node: string; path: string; before: unknown; after: unknown }[];
  problems: Problem[];
  rerun: { node: string; kind: string; scope: string }[];
  reused: string[];
  samples: number;
  jobs: number;
  settings: RunSettings;
  concurrency: number;
  tools: Record<string, { name: string; version: string | null; status: string }>;
}

export type ItemStatus = "waiting" | "queued" | "running" | "completed" | "failed" | "cancelled" | "skipped";
export type RunStatus = "running" | "paused" | "completed" | "completed_with_errors" | "cancelled";
export type Counts = Record<ItemStatus, number>;

export interface FlyeGuardNote {
  guard: "off" | "auto";
  estimate: { verdict: "fits" | "may_not_fit" | "below_floor" | "unknown"; estimate_gb: number | null; available_gb: number | null };
  applied: { asm_coverage: number; genome_size_bp?: number } | null;
  not_applied: "asm_coverage_set" | "meta" | "no_genome_size" | "no_read_statistics" | "reads_below_asm_coverage" | "below_kmer_floor" | "memory_unknown" | null;
}

/** The memory guard's decision for a Flye item, as one translated line (null when there is nothing to say). */
export function flyeGuardText(t: Translate, note: FlyeGuardNote | undefined): string | null {
  if (!note || note.guard !== "auto") return null;
  if (note.applied) return t("wf.flyeGuard.applied", { cov: note.applied.asm_coverage, gb: note.estimate.estimate_gb ?? "?", available: note.estimate.available_gb ?? "?" });
  if (note.not_applied && note.estimate.verdict !== "fits") return t(`wf.flyeGuard.${note.not_applied}`);
  return null;
}

export interface ItemError {
  code: string;
  params: Record<string, string | number>;
  message: string;
}

export interface RunItem {
  id: string;
  node_id: string;
  node_kind: string;
  sample_id: string | null;
  status: ItemStatus;
  attempt: number;
  job_id: string | null;
  job_ids: string[];
  job_status: string | null;
  tool: string | null;
  tool_version: string | null;
  duration_seconds: number | null;
  progress: string | null;
  outputs: Record<string, Record<string, unknown>> | null;
  error: ItemError | null;
  /** What ARVA decided at launch beyond the node's parameters (Flye's memory guard). */
  notes?: { flye_memory?: FlyeGuardNote } | null;
  reserved: { threads: number; memory_gb: number } | null;
  reused_from_item_id: string | null;
  depends_on: string[];
  started_at: string | null;
  finished_at: string | null;
}

export interface ParamChange {
  node: string;
  path: string;
  before: unknown;
  after: unknown;
}

export interface RunSummary {
  id: string;
  project_id: string;
  name: string;
  status: RunStatus;
  priority: number;
  settings: RunSettings;
  parent_run_id: string | null;
  workflow_id: string | null;
  workflow_name: string | null;
  version: number | null;
  definition_sha256: string;
  samples: number;
  counts: Counts;
  total: number;
  jobs_created: number;
  reused: number;
  job_seconds: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  branch_changes: ParamChange[] | null;
  estimated: { threads_per_job: number; memory_per_job_gb: number; concurrency: number };
}

export interface RunDetail extends RunSummary {
  definition: Definition;
  tools: Record<string, { name: string; version: string | null; status: string; path: string | null }>;
  sample_codes: Record<string, string>;
  items: RunItem[];
  per_sample: { sample_id: string; sample_code: string | null; counts: Counts; total: number; seconds: number }[];
  errors: (ItemError & { item_id: string; node_id: string; node_kind: string; sample_id: string | null; sample_code: string | null; status: ItemStatus; job_id: string | null })[];
  correlation_id: string | null;
}

export interface QueueOverview {
  active_runs: number;
  counts: Counts;
  budget_threads: number;
  budget_memory_gb: number;
  reserved_threads: number;
  reserved_memory_gb: number;
  profile: string;
}

export interface RunComparison {
  a: RunSummary;
  b: RunSummary;
  parameters: ParamChange[];
  rows: {
    node_id: string;
    node_kind: string;
    sample_id: string | null;
    sample_code: string | null;
    a: { status: ItemStatus; job_id: string | null; tool_version: string | null; duration_seconds: number | null };
    b: { status: ItemStatus; job_id: string | null; tool_version: string | null; duration_seconds: number | null; reused: boolean } | null;
    same_job: boolean;
    metrics: { key: string; a: unknown; b: unknown }[];
  }[];
}

export interface SampleBranch extends RunSummary {
  steps: RunItem[];
}

export interface BatchRunRequest {
  project_id: string;
  workflow_id: string;
  version?: number | null;
  sample_ids: string[];
  name?: string | null;
  settings: BatchSettings;
  options?: RunOptions;
  confirmed: boolean;
}

export const ITEM_STATUSES: ItemStatus[] = ["waiting", "queued", "running", "completed", "failed", "cancelled", "skipped"];

export const PORT_COLORS: Record<PortType, string> = {
  reads_long: "#0E7490",
  reads_short: "#0891B2",
  assembly: "#3B82F6",
  annotation: "#7C3AED",
  comparison_set: "#B45309",
  alignment: "#BE185D",
  tree: "#15803D",
  species_call: "#64748B",
  mlst_call: "#78716C",
};

/** Why an edge from (source, port) to (target, port) cannot exist, as an i18n key; null when it can. */
export function connectionProblem(
  kinds: Map<string, NodeKind>,
  nodes: Pick<WfNode, "id" | "kind">[],
  edges: WfEdge[],
  edge: WfEdge,
): "wf.connect.type" | "wf.connect.scope" | "wf.connect.collect" | "wf.connect.taken" | "wf.connect.self" | "wf.connect.cycle" | "wf.connect.port" | null {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const src = byId.get(edge.source);
  const dst = byId.get(edge.target);
  const sk = src && kinds.get(src.kind);
  const dk = dst && kinds.get(dst.kind);
  if (!src || !dst || !sk || !dk) return "wf.connect.port";
  if (src.id === dst.id) return "wf.connect.self";
  const out = sk.outputs.find((p) => p.name === edge.source_port);
  const inp = dk.inputs.find((p) => p.name === edge.target_port);
  if (!out || !inp) return "wf.connect.port";
  if (!inp.accepts.includes(out.type)) return "wf.connect.type";
  if (sk.scope === "set" && dk.scope === "sample") return "wf.connect.scope";
  if ((sk.scope === "sample" && dk.scope === "set" && !inp.collection) || (inp.collection && sk.scope !== "sample")) return "wf.connect.collect";
  if (!inp.collection && edges.some((e) => e.target === edge.target && e.target_port === edge.target_port)) return "wf.connect.taken";
  if (reaches(edges, edge.target, edge.source)) return "wf.connect.cycle";
  return null;
}

function reaches(edges: WfEdge[], from: string, to: string): boolean {
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const n = stack.pop()!;
    if (n === to) return true;
    if (seen.has(n)) continue;
    seen.add(n);
    for (const e of edges) if (e.source === n) stack.push(e.target);
  }
  return false;
}

export function newNodeId(kind: string, nodes: Pick<WfNode, "id">[]): string {
  const taken = new Set(nodes.map((n) => n.id));
  for (let i = 1; ; i++) {
    const id = `${kind}_${i}`;
    if (!taken.has(id)) return id;
  }
}

export function edgeId(e: WfEdge): string {
  return `${e.source}:${e.source_port}->${e.target}:${e.target_port}`;
}

/** The tools a node runs with its current parameters (by the kind's method parameter), as the catalogue lists them. */
export function nodeTools(kind: NodeKind, params: Record<string, unknown>): ToolState[] {
  const key = kind.tool_param ? String(getPath(params, kind.tool_param) ?? "") : "";
  return kind.tools[key] ?? [];
}

export function getPath(obj: unknown, path: string): unknown {
  let v: unknown = obj;
  for (const part of path.split(".")) {
    if (!v || typeof v !== "object") return undefined;
    v = (v as Record<string, unknown>)[part];
  }
  return v;
}

export function setPath(obj: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const [head, ...rest] = path.split(".");
  if (!rest.length) return { ...obj, [head]: value };
  const child = obj[head];
  return { ...obj, [head]: setPath(child && typeof child === "object" ? (child as Record<string, unknown>) : {}, rest.join("."), value) };
}

export type FieldKind = "boolean" | "integer" | "number" | "enum" | "string" | "json";

export interface ParamField {
  path: string;
  kind: FieldKind;
  nullable: boolean;
  options?: (string | number)[];
  min?: number;
  max?: number;
  exclusiveMin?: boolean;
  exclusiveMax?: boolean;
  pattern?: string;
}

function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (schema.$ref) {
    const name = schema.$ref.split("/").pop()!;
    return resolve(root.$defs?.[name] ?? {}, root);
  }
  if (schema.allOf?.length === 1) return resolve(schema.allOf[0], root);
  return schema;
}

/** The editable fields of a parameter schema (the analysis's request model, as the API sends it), flattened to
 * dotted paths; nested models become their fields, anything else that is not a scalar is edited as JSON. */
export function paramFields(schema: JsonSchema, root: JsonSchema = schema, prefix = ""): ParamField[] {
  const out: ParamField[] = [];
  for (const [name, raw] of Object.entries(schema.properties ?? {})) {
    const path = prefix ? `${prefix}.${name}` : name;
    let s = resolve(raw, root);
    let nullable = false;
    if (s.anyOf) {
      const parts = s.anyOf.map((p) => resolve(p, root));
      nullable = parts.some((p) => p.type === "null");
      const rest = parts.filter((p) => p.type !== "null");
      s = rest.length === 1 ? rest[0] : { type: "json" };
    }
    if (s.properties) {
      out.push(...paramFields(s, root, path));
      continue;
    }
    const base = { path, nullable };
    if (s.enum || s.const !== undefined) out.push({ ...base, kind: "enum", options: s.enum ?? [s.const!] });
    else if (s.type === "boolean") out.push({ ...base, kind: "boolean" });
    else if (s.type === "integer" || s.type === "number")
      out.push({
        ...base,
        kind: s.type,
        min: s.minimum ?? s.exclusiveMinimum,
        max: s.maximum ?? s.exclusiveMaximum,
        exclusiveMin: s.exclusiveMinimum !== undefined,
        exclusiveMax: s.exclusiveMaximum !== undefined,
      });
    else if (s.type === "string") out.push({ ...base, kind: "string", pattern: s.pattern });
    else out.push({ ...base, kind: "json" });
  }
  return out;
}

/** The problem of one field value before it reaches the server (which checks it again with the same model). */
export function fieldProblem(f: ParamField, value: unknown): "wf.param.required" | "wf.param.range" | "wf.param.integer" | "wf.param.pattern" | null {
  if (value === null || value === undefined || value === "") return f.nullable || f.kind === "json" ? null : "wf.param.required";
  if (f.kind === "integer" || f.kind === "number") {
    const n = Number(value);
    if (!Number.isFinite(n)) return "wf.param.range";
    if (f.kind === "integer" && !Number.isInteger(n)) return "wf.param.integer";
    if (f.min !== undefined && (f.exclusiveMin ? n <= f.min : n < f.min)) return "wf.param.range";
    if (f.max !== undefined && (f.exclusiveMax ? n >= f.max : n > f.max)) return "wf.param.range";
  }
  if (f.kind === "string" && f.pattern && !new RegExp(f.pattern).test(String(value))) return "wf.param.pattern";
  return null;
}

/** Per node of a run: how many of its items are in each status (a set node has one item, a sample node one per
 * sample). */
export function nodeProgress(items: RunItem[]): Map<string, Counts & { total: number }> {
  const out = new Map<string, Counts & { total: number }>();
  for (const i of items) {
    let c = out.get(i.node_id);
    if (!c) out.set(i.node_id, (c = { ...emptyCounts(), total: 0 }));
    c[i.status] += 1;
    c.total += 1;
  }
  return out;
}

export function emptyCounts(): Counts {
  return { waiting: 0, queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0, skipped: 0 };
}

export function finishedShare(c: Counts, total: number): number {
  return total ? (c.completed + c.failed + c.cancelled + c.skipped) / total : 0;
}

export function isActive(status: RunStatus): boolean {
  return status === "running" || status === "paused";
}

export const STATUS_TONE: Record<ItemStatus, "neutral" | "blue" | "success" | "danger" | "warning"> = {
  waiting: "neutral",
  queued: "blue",
  running: "blue",
  completed: "success",
  failed: "danger",
  cancelled: "warning",
  skipped: "warning",
};

export const STATUS_COLOR: Record<ItemStatus, string> = {
  waiting: "#94A3B8",
  queued: "#38BDF8",
  running: "#0284C7",
  completed: "#16A34A",
  failed: "#DC2626",
  cancelled: "#D97706",
  skipped: "#F59E0B",
};

/** A shape per status, so that the run grid does not rely on colour alone. */
export const STATUS_GLYPH: Record<ItemStatus, string> = {
  waiting: "○",
  queued: "◔",
  running: "◑",
  completed: "✓",
  failed: "✕",
  cancelled: "⊘",
  skipped: "»",
};

/** A parameter's translated name (by its last path segment), or null when the dictionary has none. */
export function paramLabel(t: Translate, path: string): string | null {
  const key = `wf.p.${path.split(".").pop()}`;
  return key in dictionaries.en ? t(key as TranslationKey) : null;
}
