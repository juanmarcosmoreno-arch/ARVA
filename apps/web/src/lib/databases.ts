import type { CatalogueEntry, DatabaseKind, DatabaseStatus, ReferenceDatabase } from "./types";

export const BUSY_STATUSES: DatabaseStatus[] = ["downloading", "extracting", "verifying"];

export const isBusy = (r: Pick<ReferenceDatabase, "status">) => BUSY_STATUSES.includes(r.status);

export type BadgeTone = "success" | "blue" | "warning" | "danger" | "neutral";

/** The badges of a database: its state (ready, verifying, unavailable, ...), then what qualifies it. Keys are the
 * i18n keys' last part (databases.badge.<key>). */
export function recordBadges(r: ReferenceDatabase): { key: string; tone: BadgeTone }[] {
  const out: { key: string; tone: BadgeTone }[] = [];
  if (r.available === false) out.push({ key: "unavailable", tone: "danger" });
  else if (r.status === "installed" || r.status === "registered") out.push({ key: "ready", tone: "success" });
  else out.push({ key: r.status, tone: r.status === "failed" ? "danger" : r.status === "cancelled" ? "warning" : "blue" });
  if (r.compatibility?.status === "incompatible") out.push({ key: "incompatible", tone: "danger" });
  if (r.version_source === "declared") out.push({ key: "declared", tone: "warning" });
  if (r.version_source === "checksum") out.push({ key: "byChecksum", tone: "neutral" });
  if (r.is_default) out.push({ key: "default", tone: "blue" });
  if ((r.status === "installed" || r.status === "registered") && r.verification_level === "quick") out.push({ key: "quickOnly", tone: "neutral" });
  return out;
}

export interface KindGroup {
  kind: DatabaseKind;
  records: ReferenceDatabase[];
  versions: CatalogueEntry[];
}

/** The kinds in the registry's order with their databases (the default first) and downloadable versions; kinds
 * with neither come last. */
export function groupByKind(kinds: DatabaseKind[], records: ReferenceDatabase[], catalogue: CatalogueEntry[]): KindGroup[] {
  const groups = kinds.map((kind) => ({
    kind,
    records: records.filter((r) => r.kind === kind.key).sort((a, b) => Number(b.is_default) - Number(a.is_default)),
    versions: catalogue.filter((e) => e.kind === kind.key),
  }));
  const used = (g: KindGroup) => g.records.length > 0 || g.versions.length > 0;
  return [...groups.filter(used), ...groups.filter((g) => !used(g))];
}

/** A version written by a user: 1 to 100 letters, digits, spaces or . , : ; ( ) # + / - (as the API accepts). */
export function validDeclaredVersion(text: string): boolean {
  return /^[\p{L}\p{N}_.,:;()#+/ -]{1,100}$/u.test(text.trim().replace(/\s+/g, " "));
}

export function validDate(text: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const d = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === text;
}

/** A folder name inside a database folder (as the API accepts): relative, letters, digits, . _ -, no "..". */
export function validFolder(text: string): boolean {
  const parts = text.trim().replace(/^\/+|\/+$/g, "").split("/");
  return parts.length > 0 && parts.length <= 4 && parts.every((p) => /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(p) && p !== "..");
}

/** The host path of a browse entry: the listing's host folder and the entry's name. */
export function joinHost(folder: string, name: string): string {
  return `${folder.replace(/\/+$/, "")}/${name}`;
}
