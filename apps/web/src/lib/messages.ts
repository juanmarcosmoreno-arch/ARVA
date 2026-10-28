import { dictionaries, type TranslationKey, type TranslationVars } from "@/i18n";
import type { Tool } from "./types";

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
  tool: Pick<Tool, "reason" | "message" | "version" | "min_version">,
): string {
  return messageText(t, "tool.reason", { code: tool.reason ?? null, params: { version: tool.version ?? "?", min: tool.min_version }, text: tool.message });
}
