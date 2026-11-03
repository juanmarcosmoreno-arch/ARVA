import type { Translate } from "@/i18n";
import { messageText } from "./messages";
import type { StorageMarker, StorageMisreport, StorageRole } from "./types";

/** A path in single quotes for a POSIX shell (a ' inside becomes '\''), so that a copied command runs as shown. */
export function shellQuote(path: string): string {
  return `'${path.replaceAll("'", `'\\''`)}'`;
}

const FLAG: Record<StorageRole, string> = {
  data: "--data-dir",
  databases: "--databases-dir",
  import: "--import-dir",
  external_databases: "--add-databases",
};

/** The launcher command that sets a location: with its current folder when known, else `example` (a path to edit). */
export function launcherCommand(role: StorageRole, hostPath: string | null | undefined, example: string): string {
  return `scripts/start.sh ${FLAG[role]} ${hostPath ? shellQuote(hostPath) : example}`;
}

export function removeCommand(hostPath: string): string {
  return `scripts/start.sh --remove-databases ${shellQuote(hostPath)}`;
}

/** The restore commands (scripts/restore.sh), shown to copy. */
export const RESTORE_LATEST = "scripts/restore.sh latest";
export const RESTORE_COMMANDS = ["scripts/restore.sh --list", RESTORE_LATEST].join("\n");

/** True when ARVA may write to the data folder now (a first-used folder is marked at the first write). */
export function markerWritable(marker: StorageMarker | null | undefined): boolean {
  return !marker || marker.status === "ok" || marker.status === "new";
}

/** Why the data folder refuses writes, in the interface language when the code is known. */
export function markerMessage(t: Translate, marker: StorageMarker): string | null {
  if (!marker.message) return null;
  return messageText(t, "api.error", { code: marker.message.code, params: marker.message.params, text: marker.text ?? "" });
}

/** The Docker Desktop File sharing entry to remove so that a disk is shared as itself: the share the mount comes from
 * when it lies above the disk (/Volumes, or /), else /Volumes (Docker Desktop's default list). */
export function shareToRemove(m: StorageMisreport | null | undefined): string {
  const share = m?.share;
  const disk = m?.disk;
  if (share && disk && share !== disk && !`${share}/`.startsWith(`${disk}/`)) return share;
  return "/Volumes";
}
