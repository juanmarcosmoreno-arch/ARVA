import { dictionaries, type Translate, type TranslationKey } from "@/i18n";
import { apiError } from "./api";

const BASE = "/api/v1";

/** One entry of ARVA's error log as GET /system/errors lists it. */
export interface ErrorEntry {
  id: string;
  time: string;
  component: "api" | "worker" | "job" | "web" | "launcher" | string;
  severity: "error" | "warning" | "info" | string;
  code: string;
  message: string;
  params: Record<string, string | number>;
  route: string | null;
  job_id: string | null;
  job_type: string | null;
  correlation_id: string | null;
}

export interface ReportOptions {
  anonymise: boolean;
  includeLogs?: boolean;
  sinceHours?: number;
  jobId?: string;
  errorId?: string;
  format?: "markdown" | "json" | "zip";
}

export const WINDOWS = [24, 168, 720] as const;

export function reportUrl(o: ReportOptions): string {
  const params = new URLSearchParams({ format: o.format ?? "markdown", anonymise: String(o.anonymise) });
  if (o.includeLogs === false) params.set("include_logs", "false");
  if (o.sinceHours) params.set("since_hours", String(o.sinceHours));
  if (o.jobId) params.set("job_id", o.jobId);
  if (o.errorId) params.set("error_id", o.errorId);
  return `${BASE}/system/diagnostics?${params}`;
}

export async function recentErrors(limit = 20, sinceHours = 168): Promise<ErrorEntry[]> {
  const res = await fetch(`${BASE}/system/errors?limit=${limit}&since_hours=${sinceHours}`);
  if (!res.ok) throw await apiError(res);
  return res.json() as Promise<ErrorEntry[]>;
}

/** The diagnostic report as Markdown, built by the API when asked. */
export async function fetchReport(o: ReportOptions): Promise<string> {
  const res = await fetch(reportUrl({ ...o, format: "markdown" }));
  if (!res.ok) throw await apiError(res);
  return res.text();
}

/** The clipboard, or (an insecure page, an older browser) a hidden text area and the copy command. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      /* permission refused: try the fallback */
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand?.("copy") ?? false;
  area.remove();
  if (!ok) throw new Error("copy refused");
}

/** An entry's message in the interface language when its code is known (one of the error log's own codes, a job's
 * failure reason or an API refusal), else its English text. */
export function entryMessage(t: Translate, e: Pick<ErrorEntry, "component" | "code" | "message" | "params">): string {
  const keys = [`diagnostics.code.${e.code}`, e.component === "job" ? `job.error.${e.code}` : `api.error.${e.code}`];
  const key = keys.find((k) => k in dictionaries.en);
  return key ? t(key as TranslationKey, e.params) : e.message;
}

/** What the interface itself knows of an error it could not record (the API did not answer), for the clipboard. */
export function localErrorDetails(error: unknown): string {
  const e = error instanceof Error ? error : new Error(String(error));
  return [
    "# ARVA interface error (not recorded: the API did not answer)",
    "",
    `- Time: ${new Date().toISOString()}`,
    `- ARVA interface ${__ARVA_VERSION__} (commit ${__ARVA_COMMIT__})`,
    `- Page: ${window.location.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, "{id}")}`,
    `- Error: ${e.name}: ${e.message}`.slice(0, 1000),
    "",
    "Run scripts/diagnostics.sh on the computer that runs ARVA for the rest.",
  ].join("\n");
}
