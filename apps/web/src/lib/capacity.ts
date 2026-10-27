import type { StorageCapacity } from "./types";

export type CapacityState = "ok" | "insufficient" | "unknown";

export const totalBytes = (files: { size: number }[]) => files.reduce((sum, f) => sum + f.size, 0);

/** Whether a selection fits in the space ARVA may use (free space minus the configured reserve). */
export function capacityCheck(neededBytes: number, capacity: StorageCapacity | null | undefined): CapacityState {
  if (!capacity) return "unknown";
  return neededBytes > capacity.available_for_data_bytes ? "insufficient" : "ok";
}
