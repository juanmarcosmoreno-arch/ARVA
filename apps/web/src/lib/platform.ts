/** Accounts and sharing, ARVA Discover, the full project report and ARVA Assist (API types and calls). */
import { apiRequest, jsonInit } from "@/lib/api";
import { fmtMax } from "@/lib/format";

export type Role = "admin" | "analyst" | "viewer";

export interface UserRow {
  id: string;
  username: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  locked: boolean;
}

export interface AuthStatus {
  enabled: boolean;
  setup_required: boolean;
  setup_token_file?: string | null;
  user: UserRow | null;
}

export interface ShareRow {
  user: UserRow;
  access: "read" | "write";
}

export interface AuditEvent {
  id: string;
  at: string;
  username: string | null;
  action: string;
  outcome: string;
  method: string | null;
  route: string | null;
  project_name: string | null;
  detail: Record<string, unknown>;
}

export type DiscoverAnalysis = "associations" | "cooccurrence" | "lineage" | "heatmap" | "pca";
export type FeatureSource = "amr" | "vf" | "rep";
export const FEATURE_SOURCES: FeatureSource[] = ["amr", "vf", "rep"];
export const DISCOVER_ANALYSES: DiscoverAnalysis[] = ["associations", "cooccurrence", "lineage", "heatmap", "pca"];

export interface DiscoverSummary {
  project_id: string;
  samples: number;
  label: string;
  caveats: string[];
  fields: { name: string; known: number; values: string[] }[];
  features: { name: string; source: FeatureSource; with: number; searched: number }[];
  provenance: Record<string, { searched?: number; samples?: number; versions: string[] }>;
  mixed_assemblies: string[];
}

export type Ci = [number, number] | null;

export interface Stratified {
  samples: number;
  informative_strata: number;
  cmh_statistic: number | null;
  p: number | null;
  q?: number | null;
  odds_ratio: number | null;
  odds_ratio_ci: Ci;
}

interface Effects {
  table: [number, number, number, number];
  samples: number;
  share_1: number | null;
  share_1_ci: Ci;
  share_2: number | null;
  share_2_ci: Ci;
  difference: number | null;
  difference_ci: Ci;
  odds_ratio: number | null;
  odds_ratio_ci: Ci;
  haldane_corrected: boolean;
  p: number;
  q: number;
  stratified?: Stratified | null;
}

export interface AssociationRow extends Effects {
  group: string;
  feature: string;
}

export interface PairRow extends Effects {
  feature_1: string;
  feature_2: string;
  phi: number | null;
  jaccard: number | null;
}

export interface DiscoverBase {
  analysis: DiscoverAnalysis;
  label: string;
  method?: string;
  samples_total: number;
  features_used: number;
  caveats: string[];
  mixed_assemblies: string[];
  sample_codes: Record<string, string>;
}

export interface AssociationsResult extends DiscoverBase {
  samples_with_value: number;
  samples_without_value: number;
  tests: number;
  tested_groups: { group: string; samples: number; others: number }[];
  skipped_groups: { group: string; samples: number; mirror_of?: string }[];
  stratified_by_lineage: boolean;
  rows: AssociationRow[];
}

export interface CooccurrenceResult extends DiscoverBase {
  pairs_tested: number;
  alpha: number;
  edges: number;
  nodes: string[];
  stratified_by_lineage: boolean;
  rows: PairRow[];
}

export interface LineageResult extends DiscoverBase {
  unknown_lineage: number;
  lineages: { lineage: string; samples: number; features: Record<string, { with: number; searched: number; share: number | null; ci: Ci }> }[];
}

export interface HeatmapResult extends DiscoverBase {
  samples: string[];
  excluded_samples: string[];
  features: string[];
  matrix: number[][];
  sample_order: number[];
  feature_order: number[];
  note: string;
}

export interface PcaResult extends DiscoverBase {
  applicable: boolean;
  reason?: "too_few_samples" | "too_few_varying_features";
  minimum?: number;
  samples: string[];
  excluded_samples: string[];
  varying_features?: string[];
  explained_variance_ratio?: number[];
  scores?: number[][];
  top_loadings?: { feature: string; loading: number }[][];
}

export interface DiscoverQuery {
  analysis: DiscoverAnalysis;
  sources: FeatureSource[];
  one_hot: string[];
  group?: string;
  lineage?: string;
  min_group: number;
  min_with: number;
  alpha: number;
}

export function discoverParams(q: DiscoverQuery): string {
  const p = new URLSearchParams({ analysis: q.analysis, min_group: String(q.min_group), min_with: String(q.min_with),
    alpha: String(q.alpha) });
  q.sources.forEach((s) => p.append("sources", s));
  q.one_hot.forEach((s) => p.append("one_hot", s));
  if (q.group) p.set("group", q.group);
  if (q.lineage) p.set("lineage", q.lineage);
  return p.toString();
}

export interface AssistSettings {
  enabled: boolean;
  provider: string | null;
  endpoint: string | null;
  model: string | null;
  key_set: boolean;
  endpoint_is_local: boolean;
  providers: string[];
  instructions: string;
}

export interface AssistRequestRow {
  id: string;
  at: string;
  username: string | null;
  provider: string;
  endpoint_host: string | null;
  model: string | null;
  question: string;
  sent: Record<string, unknown>;
  sent_sha256: string;
  included_sequences: boolean;
  status: string;
  answer: string | null;
  error_code: string | null;
}

export interface AskBody {
  question: string;
  about_project_id?: string;
  about_sample_id?: string;
  guide?: { id: string; title: string; text: string }[];
  sequence_refs?: { annotation_id: string; feature_id: string }[];
  sequence_consent?: boolean;
}

export const platformApi = {
  authStatus: () => apiRequest<AuthStatus>("/auth/status"),
  login: (username: string, password: string) =>
    apiRequest<{ user: UserRow; csrf_token: string }>("/auth/login", jsonInit("POST", { username, password })),
  setup: (body: { username: string; password: string; token: string; display_name?: string }) =>
    apiRequest<{ user: UserRow }>("/auth/setup", jsonInit("POST", body)),
  logout: () => apiRequest<void>("/auth/logout", { method: "POST" }),
  changePassword: (current: string, next: string) =>
    apiRequest<void>("/auth/password", jsonInit("POST", { current, new: next })),
  users: () => apiRequest<UserRow[]>("/users"),
  createUser: (body: { username: string; password: string; role: Role; display_name?: string }) =>
    apiRequest<UserRow>("/users", jsonInit("POST", body)),
  updateUser: (id: string, body: Partial<{ role: Role; is_active: boolean; password: string }>) =>
    apiRequest<UserRow>(`/users/${id}`, jsonInit("PATCH", body)),
  directory: () => apiRequest<Pick<UserRow, "id" | "username" | "display_name" | "role">[]>("/auth/directory"),
  shares: (projectId: string) => apiRequest<{ owner: UserRow | null; shares: ShareRow[] }>(`/projects/${projectId}/shares`),
  share: (projectId: string, userId: string, access: "read" | "write" | null) =>
    apiRequest<{ owner: UserRow | null; shares: ShareRow[] }>(`/projects/${projectId}/shares`,
      jsonInit("PUT", { user_id: userId, access })),
  audit: (limit = 200) => apiRequest<AuditEvent[]>(`/audit?limit=${limit}`),
  discoverSummary: (projectId: string) => apiRequest<DiscoverSummary>(`/projects/${projectId}/discover`),
  discover: <T extends DiscoverBase>(projectId: string, q: DiscoverQuery) =>
    apiRequest<T>(`/projects/${projectId}/discover/analysis?${discoverParams(q)}`),
  assistStatus: () => apiRequest<{ enabled: boolean; provider: string | null; endpoint_is_local: boolean }>("/assist/status"),
  assistSettings: () => apiRequest<AssistSettings>("/assist/settings"),
  saveAssistSettings: (body: { enabled: boolean; provider?: string | null; endpoint?: string | null; model?: string | null;
    api_key?: string; clear_key?: boolean }) => apiRequest<AssistSettings>("/assist/settings", jsonInit("PUT", body)),
  assistPreview: (body: AskBody) => apiRequest<{ payload: Record<string, unknown> }>("/assist/preview", jsonInit("POST", body)),
  assistAsk: (body: AskBody) =>
    apiRequest<{ request_id: string; answer: string; sent_sha256: string; included_sequences: boolean }>("/assist/ask",
      jsonInit("POST", body)),
  assistAudit: () => apiRequest<AssistRequestRow[]>("/assist/audit"),
};

export const discoverCsvUrl = (projectId: string, q: DiscoverQuery) =>
  `/api/v1/projects/${projectId}/discover/analysis.csv?${discoverParams(q)}`;

export const projectReportUrl = (projectId: string, format: "html" | "pdf" | "json" | "csv", lang: string) =>
  `/api/v1/projects/${projectId}/report?format=${format}&lang=${lang}`;

/** "0.42 (0.18–0.71)": a value with its 95 % interval, in the interface locale. */
export function withCi(v: number | null, ci: Ci, digits = 2): string {
  if (v === null) return "–";
  return ci ? `${fmtMax(v, digits)} (${fmtMax(ci[0], digits)}–${fmtMax(ci[1], digits)})` : fmtMax(v, digits);
}

/** p- and q-values: three significant digits, and "< 0.001" below that. */
export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "–";
  return p < 0.001 ? `< ${fmtMax(0.001, 3)}` : fmtMax(Number(p.toPrecision(3)), 4);
}

/** The heatmap's rows and columns in the clustering order. */
export function orderedMatrix(h: HeatmapResult): { samples: string[]; features: string[]; cells: [number, number, number][] } {
  const samples = h.sample_order.map((i) => h.samples[i]);
  const features = h.feature_order.map((j) => h.features[j]);
  const cells: [number, number, number][] = [];
  h.sample_order.forEach((i, y) => h.feature_order.forEach((j, x) => cells.push([x, y, h.matrix[i][j]])));
  return { samples, features, cells };
}

/** Co-occurrence network: nodes are the features in an edge, edges the pairs with q ≤ alpha (positive or negative). */
export function network(r: CooccurrenceResult) {
  const edges = r.rows.filter((x) => x.q <= r.alpha);
  return {
    nodes: r.nodes.map((n) => ({ id: n, name: n, value: edges.filter((e) => e.feature_1 === n || e.feature_2 === n).length })),
    edges: edges.map((e) => ({ source: e.feature_1, target: e.feature_2, positive: (e.odds_ratio ?? 1) >= 1, q: e.q, phi: e.phi })),
  };
}
