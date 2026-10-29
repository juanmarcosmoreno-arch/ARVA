/** Errors of the interface kept in ARVA's own error log (POST /system/client-errors, on this computer): the error
 * boundary, window errors, unhandled rejections and failed API calls the API could not record itself. Nothing goes
 * anywhere else. Each distinct error is reported once per page load, at most 20 in all; the API bounds and redacts
 * what it keeps. No imports from api.ts, which reports through here. */

const ENDPOINT = "/api/v1/system/client-errors";
const MAX_REPORTS = 20;
const METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);
const IGNORED = /ResizeObserver loop/;

export type ClientErrorKind = "boundary" | "window_error" | "unhandled_rejection" | "api";

export interface ClientErrorReport {
  kind: ClientErrorKind;
  message: string;
  name?: string;
  stack?: string;
  component_stack?: string;
  api?: { method: string; path: string; status: number; code?: string; error_id?: string; correlation_id?: string };
}

let sent = 0;
const seen = new Map<string, Promise<string | null>>();

const clip = (text: string | null | undefined, n: number) => (text == null ? undefined : text.slice(0, n));

/** Reports an error; resolves to its error log id, or null when it could not be recorded (the API is down). */
export function reportClientError(r: ClientErrorReport): Promise<string | null> {
  const key = `${r.kind}:${r.message}:${r.api?.path ?? ""}`;
  const known = seen.get(key);
  if (known) return known;
  if (sent >= MAX_REPORTS) return Promise.resolve(null);
  sent += 1;
  const body = {
    ...r,
    message: clip(r.message, 1000) ?? "",
    name: clip(r.name, 100),
    stack: clip(r.stack, 8000),
    component_stack: clip(r.component_stack, 4000),
    page: clip(window.location.pathname, 300),
    client_commit: __ARVA_COMMIT__,
    user_agent: clip(navigator.userAgent, 300),
  };
  const result = fetch(ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then(async (res) => (res.ok ? ((await res.json()) as { id: string }).id : null))
    .catch(() => null);
  seen.set(key, result);
  return result;
}

export function reportApiFailure(method: string, path: string, status: number, message: string, code?: string, correlationId?: string) {
  if (path.endsWith("/system/client-errors")) return;
  void reportClientError({
    kind: "api",
    message,
    api: {
      method: METHODS.has(method.toUpperCase()) ? method.toUpperCase() : "GET",
      path: path.split("?")[0].slice(0, 300),
      status,
      code: code && /^[a-z0-9_.-]{1,80}$/.test(code) ? code : undefined,
      correlation_id: correlationId && /^[0-9a-f]{16}$/.test(correlationId) ? correlationId : undefined,
    },
  });
}

export function reportException(kind: ClientErrorKind, error: unknown, componentStack?: string | null): Promise<string | null> {
  const e = error instanceof Error ? error : new Error(typeof error === "string" ? error : "A value that is not an Error was thrown");
  return reportClientError({ kind, message: e.message || e.name, name: e.name, stack: e.stack, component_stack: componentStack ?? undefined });
}

export function installErrorReporting() {
  window.addEventListener("error", (ev) => {
    if (!IGNORED.test(ev.message ?? "")) void reportException("window_error", ev.error ?? ev.message);
  });
  window.addEventListener("unhandledrejection", (ev) => void reportException("unhandled_rejection", ev.reason));
}

/** Only for tests: forget what was reported. */
export function resetErrorReporting() {
  sent = 0;
  seen.clear();
}
