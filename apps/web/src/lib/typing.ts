import type { TranslationKey, TranslationVars } from "@/i18n";
import { messageText } from "@/lib/messages";

export const TYPING_JOB = "species_typing";
export const STAPH_MODULE = "staphylococcus_aureus";
export const TYPING_METHODS = ["sccmec", "spa", "agr"] as const;
export type TypingMethod = (typeof TYPING_METHODS)[number];
export type Applicability = "applicable" | "conflicting" | "not_applicable" | "no_evidence";

type T = (key: TranslationKey, vars?: TranslationVars) => string;

export interface TypingWarning {
  code: string;
  params?: Record<string, string | number>;
}

export interface TypingTool {
  id: string;
  name: string;
  status: string;
  version: string | null;
  version_validated: boolean;
  message: string;
  reason: string | null;
  reason_params: Record<string, string>;
  path: string | null;
  license: string;
  citation: string;
  citation_url: string;
  install: Record<string, string>;
  platforms: string[];
  max_threads?: number;
  default_threads?: number;
}

export interface TypingRequirement {
  key: TypingMethod;
  name: string;
  tool: TypingTool;
  database: {
    kind: string;
    name: string;
    registered: { id: string; name: string; version: string | null; is_default: boolean }[];
    source_url: string;
    licence: string;
    licence_url: string | null;
    download_note: string;
    user_provided_only: boolean;
  } | null;
  missing: ("tool" | "database")[];
  ready: boolean;
  guide: string;
}

export interface TypingModuleInfo {
  key: string;
  name: string;
  species: string[];
  mlst_schemes: string[];
  guide: string[];
  requirements: TypingRequirement[];
}

export interface ApplicabilityCheck {
  source: "species" | "mlst";
  value: string;
  matches: boolean;
}

export interface ApplicabilityInfo {
  module: string;
  status: Applicability;
  checks: ApplicabilityCheck[];
  override_required: boolean;
}

export interface TypingSource {
  tool: string;
  version: string | null;
  job_id: string | null;
  database_version?: string | null;
  plus?: boolean;
}

export interface TypingCall {
  status: string;
  call: string | null;
  details: Record<string, unknown>;
  warnings: TypingWarning[];
  source: TypingSource;
}

export interface AmrGene {
  symbol: string;
  name: string | null;
  method: string;
  method_kind: string;
  identity: number | null;
  coverage: number | null;
  contig: string | null;
}

export interface StaphSummary {
  assembly_id: string;
  applicability: ApplicabilityInfo;
  mlst: { scheme: string | null; st: string | null; status: string; clonal_complex: string | null; source: TypingSource } | null;
  sccmec: TypingCall | null;
  spa: TypingCall | null;
  agr: TypingCall | null;
  amr: {
    source: TypingSource;
    mecA: AmrGene[];
    mecC: AmrGene[];
    pvl: AmrGene[] | null;
    tst: AmrGene[] | null;
    enterotoxins: AmrGene[] | null;
    exfoliative_toxins: AmrGene[] | null;
  } | null;
  mec_crosscheck: { sccmec: boolean | null; amrfinderplus: boolean | null; status: "agree" | "disagree" | "unavailable" };
  shorthand: string | null;
  uncertain: { part: string; reason: string; params: Record<string, string | number> }[];
  not_determined: string[];
}

export interface TypingResult {
  id: string;
  job_id: string;
  sample_id: string;
  assembly_id: string;
  module: string;
  method: TypingMethod;
  tool: string;
  tool_version: string;
  database_kind: string | null;
  database_name: string | null;
  database_version: string | null;
  database_checksum: string | null;
  parameters: Record<string, unknown>;
  status: string;
  call: string | null;
  details: Record<string, unknown>;
  applicability: { status?: Applicability };
  warnings: TypingWarning[];
  files: Record<string, { path: string; sha256: string; size_bytes: number }>;
  created_at: string;
}

export interface TypingSample {
  modules: TypingModuleInfo[];
  assemblies: {
    assembly_id: string;
    assembler: string;
    assembler_version: string;
    kind: string;
    created_at: string;
    applicability: Record<string, ApplicabilityInfo>;
    summary: StaphSummary | null;
  }[];
  results: TypingResult[];
}

export interface TypingPlan {
  module: string;
  method: TypingMethod;
  tool: TypingTool & { max_threads: number; default_threads: number };
  database: { id: string; name: string; version: string | null; host_path: string; licence: string; licence_url: string | null; citation: string } | null;
  databases: { id: string; name: string; version: string | null; is_default: boolean; available: boolean }[];
  bundled: { kind: string; name: string; files: string[]; checksum: string; path: string } | null;
  defaults: Record<string, string>;
  tool_defaults: Record<string, string>;
  defaults_match: boolean | null;
  assembly: { synthetic_evidence: string[] };
  applicability: ApplicabilityInfo;
  problems: { code: string; message: string; params: Record<string, string> }[];
}

export interface TypingRequest {
  method: TypingMethod;
  settings: Record<string, number>;
  database_id: string | null;
  override_applicability: boolean;
  confirmed: boolean;
}

export interface TypingProject {
  project_id: string;
  project_name: string;
  module: string;
  samples: { sample_id: string; sample_code: string; summary: StaphSummary | null }[];
  typed: number;
}

export function typingWarningText(t: T, w: TypingWarning): string {
  return messageText(t, "typing.warning", { code: w.code, params: w.params ?? {}, text: w.code });
}

/** Genes as "symbol (kind)" or the state of the search: not searched (no run, or run without --plus) is never
 * shown as none found. */
export function genesText(t: T, genes: AmrGene[] | null | undefined, searched: boolean): string {
  if (!searched || genes == null) return t("typing.notSearched");
  if (!genes.length) return t("typing.noneFound");
  return genes.map((g) => (g.method_kind === "complete" ? g.symbol : `${g.symbol} (${t(`typing.kind.${g.method_kind}` as TranslationKey)})`)).join(", ");
}

export function sourceText(t: T, s: TypingSource | undefined): string {
  if (!s) return "";
  return t("typing.source", { tool: s.tool, version: s.version ?? "?", job: (s.job_id ?? "").slice(0, 8) });
}

/** The settings form of a step: numbers for sccmec's thresholds, nothing for spaTyper and AgrVATE. */
export function typingBody(method: TypingMethod, settings: Record<string, string>, databaseId: string, override: boolean): TypingRequest {
  const numbers = Object.fromEntries(Object.entries(settings).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, Number(v)]));
  return { method, settings: method === "sccmec" ? numbers : {}, database_id: databaseId || null, override_applicability: override, confirmed: true };
}

export function settingsProblems(method: TypingMethod, settings: Record<string, string>): TranslationKey[] {
  if (method !== "sccmec") return [];
  const bad = Object.values(settings).some((v) => v.trim() !== "" && !(Number.isInteger(Number(v)) && Number(v) >= 1 && Number(v) <= 100));
  return bad ? ["typing.problem.threshold"] : [];
}
