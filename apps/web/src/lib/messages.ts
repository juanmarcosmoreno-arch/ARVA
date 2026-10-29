import { dictionaries, type TranslationKey, type TranslationVars } from "@/i18n";
import { profileName } from "./performance";
import type { AnalysisJob, RawFile, SequenceStats, Tool } from "./types";

/** A message from the server: a stable code with parameters, and its English text. */
export interface ServerMessage {
  code: string | null;
  params: Record<string, string | number>;
  text: string;
}

/** The message in the interface language when this version knows its code (key `${prefix}.${code}`), else the
 * server's English text. Plain strings (results stored before messages had codes) are shown as they are. */
export function messageText(t: (key: TranslationKey, vars?: TranslationVars) => string, prefix: string, m: ServerMessage | string): string {
  if (typeof m === "string") return m;
  const key = m.code ? `${prefix}.${m.code}` : null;
  return key && key in dictionaries.en ? t(key as TranslationKey, m.params) : m.text;
}

/** A tool's detection message in the interface language when ARVA knows its reason code (`tool.reason.<code>`). */
export function toolMessage(
  t: (key: TranslationKey, vars?: TranslationVars) => string,
  tool: Pick<Tool, "reason" | "message" | "version" | "min_version"> & { reason_params?: Record<string, string | number> | null },
): string {
  const params = { version: tool.version ?? "?", min: tool.min_version, ...(tool.reason_params ?? {}) };
  return messageText(t, "tool.reason", { code: tool.reason ?? null, params, text: tool.message });
}

/** A tool's description in the interface language when ARVA knows the tool (`tool.description.<id>`), else the server's. */
export function toolDescription(t: (key: TranslationKey, vars?: TranslationVars) => string, tool: Pick<Tool, "id" | "description">): string {
  const key = `tool.description.${tool.id}`;
  return key in dictionaries.en ? t(key as TranslationKey) : tool.description;
}

type T = (key: TranslationKey, vars?: TranslationVars) => string;

/** What the operating system's SIGKILL most likely means and what to change, from the resources the job ran with. */
function memoryAdvice(t: T, job: Pick<AnalysisJob, "resources">) {
  const r = job.resources;
  const parts: string[] = [];
  if (r) {
    const limit = r.memory_limit_gb ? t("job.memory.limit", { gb: r.memory_limit_gb }) : "";
    parts.push(
      t(r.in_container ? "job.memory.usableContainer" : "job.memory.usable", { memory: r.usable_memory_gb }) +
        t("job.memory.ranWith", { threads: r.threads ?? "?", limit, profile: profileName(t, r.profile) }),
    );
  }
  parts.push(t(r?.in_container ?? true ? "job.memory.adviceDocker" : "job.memory.advice"));
  return parts.join(" ");
}

/** A failed job's reason in the interface language when the worker recorded a known code, else its English text. */
export function jobError(t: T, job: Pick<AnalysisJob, "error_message" | "error_detail" | "resources">): string {
  const d = job.error_detail;
  if (d?.code === "out_of_memory") return `${t("job.error.out_of_memory", d.params)} ${memoryAdvice(t, job)}`;
  return d ? messageText(t, "job.error", { code: d.code, params: d.params, text: job.error_message ?? "" }) : (job.error_message ?? "");
}

/** The import check of a file (structure of its first records) in the interface language. */
export function fileValidation(t: T, file: Pick<RawFile, "validation_message" | "validation_detail">): string {
  const d = file.validation_detail;
  return d ? messageText(t, "file.validation", { code: d.code, params: d.params, text: file.validation_message ?? "" }) : (file.validation_message ?? "");
}

const KEPT_BY = /^Reads kept by (fastp|Filtlong) (\S+)$/;

/** The description ARVA gives a filtered file ("Reads kept by fastp 0.23.4") in the interface language. */
export function derivedDescription(t: T, description: string): string {
  const m = KEPT_BY.exec(description);
  return m ? t("files.keptBy", { tool: m[1], version: m[2] }) : description;
}

/** The read-statistics warnings; results computed before warnings had codes keep their English text. */
export function seqstatsWarnings(t: T, stats: Pick<SequenceStats, "warnings" | "messages">): string[] {
  return stats.messages?.length ? stats.messages.map((m) => messageText(t, "seqstats.warning", m)) : stats.warnings;
}
