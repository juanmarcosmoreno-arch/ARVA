import type { TranslationKey, TranslationVars } from "@/i18n";
import { fmtBytes } from "./format";
import type { StorageCapacity } from "./types";

export type CapacityState = "ok" | "insufficient" | "unknown";

export const totalBytes = (files: { size: number }[]) => files.reduce((sum, f) => sum + f.size, 0);

/** Whether a selection fits in the space ARVA may use (free space minus the configured reserve). */
export function capacityCheck(neededBytes: number, capacity: StorageCapacity | null | undefined): CapacityState {
  if (!capacity) return "unknown";
  return neededBytes > capacity.available_for_data_bytes ? "insufficient" : "ok";
}

/** Space browser uploads need (one size per request): each request body is spooled first, on the data disk when the factor is 2. */
export function uploadBytesNeeded(requestSizes: number[], capacity: StorageCapacity | null | undefined): number {
  const factor = capacity?.upload_overhead_factor ?? 1;
  const total = requestSizes.reduce((sum, n) => sum + n, 0);
  const largest = requestSizes.reduce((max, n) => Math.max(max, n), 0);
  return total + (factor - 1) * largest;
}

type Translate = (key: TranslationKey, vars?: TranslationVars) => string;

/** The "Selected … · Usable …" line for a browser upload and, if it cannot fit, the refusal explaining why. */
export function uploadSpace(t: Translate, selectedBytes: number, requestSizes: number[], capacity: StorageCapacity | null | undefined) {
  const needed = uploadBytesNeeded(requestSizes, capacity);
  const buffered = needed > selectedBytes;
  const vars = {
    selected: fmtBytes(selectedBytes),
    needed: fmtBytes(needed),
    free: capacity ? fmtBytes(capacity.available_for_data_bytes) : "—",
  };
  const refusal =
    capacity && capacityCheck(needed, capacity) === "insufficient"
      ? t(buffered ? "storage.insufficientBuffered" : "storage.insufficient", {
          ...vars,
          available: fmtBytes(capacity.available_for_data_bytes),
          reserve: fmtBytes(capacity.min_free_bytes),
        })
      : null;
  return { line: t(buffered ? "storage.selectedBuffered" : "storage.selected", vars), refusal };
}
