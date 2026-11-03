import { markerWritable } from "./storage";
import type { DashboardSummary, DatabaseLocations, PerformanceOverview, ReferenceDatabase, StorageCapacity } from "./types";

export type CheckState = "done" | "todo" | "attention" | "busy" | "unknown";
export type CheckKey = "storage" | "performance" | "bakta" | "references" | "amrfinderplus" | "project";

/** One item of the first-run checklist, from what the API reports (null while it has not answered). */
export interface CheckItem {
  key: CheckKey;
  state: CheckState;
  /** What the item's text needs: a message code and its values. */
  code: string;
  params: Record<string, string | number>;
}

const BUSY = new Set(["downloading", "extracting", "verifying"]);

export function storageCheck(s: StorageCapacity | undefined): CheckItem {
  const base = { key: "storage" as const, params: {} };
  if (!s) return { ...base, state: "unknown", code: "unknown" };
  const locations = s.locations ?? [];
  const missing = locations.filter((l) => !l.available || l.warnings.includes("not_connected"));
  if (missing.length > 0) {
    return { ...base, state: "attention", code: "missing", params: { folders: missing.map((l) => l.host_path ?? l.container_path).join(", ") } };
  }
  if (!markerWritable(s.marker)) return { ...base, state: "attention", code: "marker" };
  const data = locations.find((l) => l.role === "data");
  if (!data?.host_path) return { ...base, state: "attention", code: "docker_volumes" };
  const warnings = locations.flatMap((l) => l.warnings);
  if (warnings.includes("fat_filesystem")) return { ...base, state: "attention", code: "fat", params: { folder: data.host_path } };
  if (warnings.includes("low_space")) return { ...base, state: "attention", code: "low_space", params: { folder: data.host_path } };
  return { ...base, state: "done", code: "ok", params: { folder: data.host_path, fs: data.filesystem ?? "?" } };
}

export function performanceCheck(p: PerformanceOverview | undefined): CheckItem {
  const base = { key: "performance" as const, params: {} };
  if (!p) return { ...base, state: "unknown", code: "unknown" };
  const params = { profile: p.effective.profile, threads: p.effective.threads, memory: p.effective.memory_gb, host: p.effective.host };
  if (p.host.platform?.source !== "launcher" && p.host.platform?.source !== "macos") {
    return { ...base, state: "attention", code: "host_unknown", params };
  }
  if (p.docker.status === "adjust" || p.docker.status === "partial") return { ...base, state: "attention", code: "docker_adjust", params };
  return { ...base, state: "done", code: "ok", params };
}

/** A database kind: ready when one of its records is installed or registered and its folder can be read. */
export function databaseCheck(key: "bakta" | "references" | "amrfinderplus", records: ReferenceDatabase[] | undefined): CheckItem {
  const kind = key === "references" ? "reference_genomes" : key;
  if (!records) return { key, state: "unknown", code: "unknown", params: {} };
  const mine = records.filter((r) => r.kind === kind);
  const ready = mine.filter((r) => (r.status === "installed" || r.status === "registered") && r.available !== false);
  const shown = ready.find((r) => r.is_default) ?? ready[0];
  if (shown) {
    return { key, state: "done", code: "ready", params: { name: shown.name, version: shown.version ?? "?", count: ready.length } };
  }
  const busy = mine.find((r) => BUSY.has(r.status));
  if (busy) return { key, state: "busy", code: "busy", params: { name: busy.name } };
  if (mine.some((r) => r.available === false)) return { key, state: "attention", code: "unavailable", params: {} };
  if (mine.length > 0) return { key, state: "attention", code: "failed", params: {} };
  return { key, state: "todo", code: "none", params: {} };
}

export function projectCheck(d: DashboardSummary | undefined): CheckItem {
  if (!d) return { key: "project", state: "unknown", code: "unknown", params: {} };
  return d.project_count > 0
    ? { key: "project", state: "done", code: "ok", params: { count: d.project_count } }
    : { key: "project", state: "todo", code: "none", params: {} };
}

/** The read-only folders added with scripts/start.sh --add-databases, as on this computer (where to look when registering). */
export function addedFolders(locations: DatabaseLocations | undefined): string[] {
  return (locations?.browse ?? []).filter((b) => b.role === "external_databases" && b.host_path).map((b) => b.host_path as string);
}
