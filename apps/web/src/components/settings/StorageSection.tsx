import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, DatabaseBackup, HardDrive } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes, fmtDate } from "@/lib/format";
import { RESTORE_COMMANDS, RESTORE_LATEST, launcherCommand, markerMessage, markerWritable, removeCommand, shareToRemove } from "@/lib/storage";
import type { MetadataBackups, StorageCapacity, StorageLocation } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Settings → Storage: every folder ARVA uses, its disk's state, the metadata backups and the launcher commands that
 * change a location (a folder is mounted when ARVA's containers start, so a change restarts them). */
export function StorageSection() {
  const t = useT();
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage, refetchInterval: 30_000 });
  return (
    <Card className="lg:col-span-2">
      <CardHeader title={t("storage.section.title")} description={t("storage.section.subtitle")} action={<HardDrive className="h-4 w-4 text-arva-teal" aria-hidden />} />
      <CardBody>
        {storage.isLoading ? <Skeleton className="h-40" /> : storage.error ? <ErrorNote error={storage.error} /> : storage.data && <Storage s={storage.data} />}
      </CardBody>
    </Card>
  );
}

function Storage({ s }: { s: StorageCapacity }) {
  const t = useT();
  const locations = s.locations ?? [];
  return (
    <div className="space-y-6 text-sm">
      {s.marker && !markerWritable(s.marker) && <MarkerAlert s={s} />}
      {locations
        .filter((l) => l.warnings.includes("space_misreported"))
        .map((l) => (
          <MisreportAlert key={`misreport:${l.container_path}`} loc={l} />
        ))}
      <table className="w-full table-fixed border-collapse text-left text-xs">
        <colgroup>
          <col className="w-[18%]" />
          <col className="w-[27%]" />
          <col className="w-[19%]" />
          <col className="w-[10%]" />
          <col className="w-[13%]" />
          <col className="w-[13%]" />
        </colgroup>
        <thead className="text-muted-foreground">
          <tr className="border-b">
            <th className="py-1.5 pr-3 font-medium">{t("storage.col.location")}</th>
            <th className="py-1.5 pr-3 font-medium">{t("storage.col.onComputer")}</th>
            <th className="py-1.5 pr-3 font-medium">{t("storage.col.inArva")}</th>
            <th className="py-1.5 pr-3 font-medium">{t("storage.col.access")}</th>
            <th className="py-1.5 pr-3 font-medium">{t("storage.col.space")}</th>
            <th className="py-1.5 font-medium">{t("storage.col.state")}</th>
          </tr>
        </thead>
        <tbody>
          {locations.map((loc) => (
            <LocationRow key={`${loc.role}:${loc.container_path}`} loc={loc} inContainer={!!s.in_container} />
          ))}
        </tbody>
      </table>
      {/* grid-cols-1 (minmax(0, 1fr)): a long path in the commands scrolls inside its <pre> instead of widening the page. */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Commands locations={locations} />
        {s.backups && <Backups b={s.backups} writable={markerWritable(s.marker)} />}
      </div>
      <p className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">{t("storage.dockerImage")}</p>
    </div>
  );
}

function MarkerAlert({ s }: { s: StorageCapacity }) {
  const t = useT();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const adopt = useMutation({
    mutationFn: api.adoptStorage,
    onSuccess: (data) => {
      qc.setQueryData(["storage"], data);
      setConfirming(false);
    },
  });
  const marker = s.marker!;
  return (
    <div role="alert" className="space-y-2 rounded-lg border border-danger/30 bg-danger/5 p-3 text-danger">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">{t(`storage.marker.${marker.status}` as TranslationKey)}</p>
          <p className="text-xs">{markerMessage(t, marker)}</p>
        </div>
      </div>
      {marker.status === "restore_needed" && (
        <div className="flex flex-wrap items-center gap-2 pl-6">
          <code className="rounded bg-surface px-2 py-1 text-[11px] text-foreground">{RESTORE_LATEST}</code>
          <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
            {t("storage.adopt")}
          </Button>
        </div>
      )}
      <Dialog open={confirming} onOpenChange={setConfirming} title={t("storage.adopt")} description={t("storage.adoptConfirm")}>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirming(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => adopt.mutate()} disabled={adopt.isPending}>
            {t("storage.adopt")}
          </Button>
        </div>
        <ErrorNote error={adopt.error} />
      </Dialog>
    </div>
  );
}

/** A folder whose free space Docker reports from another disk: why, which figure ARVA uses, and how to fix it. */
function MisreportAlert({ loc }: { loc: StorageLocation }) {
  const t = useT();
  const m = loc.misreport;
  const folder = loc.host_path ?? loc.container_path;
  const seen = m?.container_total_bytes != null ? t("storage.freeOfTotal", { free: fmtBytes(m.container_free_bytes ?? 0), total: fmtBytes(m.container_total_bytes) }) : "?";
  const why =
    m?.reason === "size_differs"
      ? t("storage.misreport.size_differs", { folder, seen: m.container_total_bytes != null ? fmtBytes(m.container_total_bytes) : "?", host: loc.host_total_bytes != null ? fmtBytes(loc.host_total_bytes) : "?" })
      : t("storage.misreport.parent_share", { folder, share: m?.share ?? "/Volumes", seen });
  return (
    <div role="alert" className="space-y-1 rounded-lg border border-warning/40 bg-warning/10 p-3 text-amber-900 dark:text-warning">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">{t("storage.misreport.title")}</p>
          <p className="text-xs">{why}</p>
          <p className="text-xs">
            {loc.space_source === "host_at_start"
              ? m?.written_since_bytes != null
                ? t("storage.misreport.used.host_at_start", {
                    when: loc.host_measured_at ? fmtDate(loc.host_measured_at) : "?",
                    host: fmtBytes(loc.host_free_bytes ?? 0),
                    written: fmtBytes(m.written_since_bytes),
                    free: fmtBytes(loc.free_bytes ?? 0),
                    total: fmtBytes(loc.total_bytes ?? 0),
                  })
                : t("storage.misreport.used.host_at_start_unmeasured", {
                    when: loc.host_measured_at ? fmtDate(loc.host_measured_at) : "?",
                    free: fmtBytes(loc.free_bytes ?? 0),
                    total: fmtBytes(loc.total_bytes ?? 0),
                  })
              : t("storage.misreport.used.container_misreported")}
          </p>
          <p className="text-xs">{t("storage.misreport.steps", { disk: m?.disk ?? folder, share: shareToRemove(m) })}</p>
        </div>
      </div>
    </div>
  );
}

function LocationRow({ loc, inContainer }: { loc: StorageLocation; inContainer: boolean }) {
  const t = useT();
  const usedPct = loc.free_bytes != null && loc.total_bytes ? Math.min(100, Math.round(100 * (1 - loc.free_bytes / loc.total_bytes))) : null;
  const unknownHost = loc.role === "import" ? t("storage.importDefault") : loc.role === "external_databases" ? t("storage.unknownHost") : t("storage.dockerVolume");
  return (
    <tr className="border-b align-top last:border-0">
      <td className="py-2 pr-3">
        <div className="font-medium text-foreground">{t(`storage.role.${loc.role}` as TranslationKey)}</div>
        <div className="text-[11px] text-muted-foreground">{t(`storage.stores.${loc.role}` as TranslationKey)}</div>
      </td>
      <td className="py-2 pr-3">
        {loc.host_path ? <code className="break-all">{loc.host_path}</code> : <span className="text-muted-foreground">{inContainer ? unknownHost : t("storage.unknownHost")}</span>}
        {loc.filesystem && <div className="text-[11px] text-muted-foreground">{t("storage.filesystem", { fs: loc.filesystem })}</div>}
      </td>
      <td className="py-2 pr-3">
        <code className="break-all text-muted-foreground">{loc.container_path}</code>
      </td>
      <td className="py-2 pr-3">
        <Badge tone={loc.read_only ? "neutral" : "teal"}>{t(loc.read_only ? "storage.access.ro" : "storage.access.rw")}</Badge>
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {loc.free_bytes != null && loc.total_bytes != null ? (
          <>
            <div>{t("storage.freeOfTotal", { free: fmtBytes(loc.free_bytes), total: fmtBytes(loc.total_bytes) })}</div>
            {loc.space_source === "host_at_start" && loc.host_measured_at && (
              <div className="text-[11px] text-muted-foreground">{t("storage.measuredAtStart", { when: fmtDate(loc.host_measured_at) })}</div>
            )}
            <div
              role="meter"
              aria-label={t("storage.col.space")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={usedPct ?? 0}
              className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"
            >
              <div className={cn("h-full", loc.warnings.includes("low_space") ? "bg-warning" : "bg-arva-teal")} style={{ width: `${usedPct ?? 0}%` }} />
            </div>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="space-y-1 py-2">
        {loc.warnings.length === 0 && <Badge tone="success">{t(loc.marker === "new" ? "storage.marker.new" : "storage.connected")}</Badge>}
        {loc.warnings.map((w) => (
          <Badge key={w} tone={w === "not_connected" ? "danger" : "warning"} className="whitespace-normal text-left">
            {t(`storage.warning.${w}` as TranslationKey)}
          </Badge>
        ))}
        {loc.databases != null && loc.databases > 0 && <div className="text-[11px] text-muted-foreground">{t("storage.databasesHere", { n: loc.databases })}</div>}
      </td>
    </tr>
  );
}

function Commands({ locations }: { locations: StorageLocation[] }) {
  const t = useT();
  const host = (role: StorageLocation["role"]) => locations.find((l) => l.role === role)?.host_path;
  const added = locations.filter((l) => l.role === "external_databases" && l.host_path);
  const lines = [
    launcherCommand("data", host("data"), t("storage.example.data")),
    launcherCommand("databases", host("databases"), t("storage.example.databases")),
    launcherCommand("external_databases", null, t("storage.example.external_databases")),
    launcherCommand("import", host("import"), t("storage.example.import")),
    ...added.map((l) => removeCommand(l.host_path!)),
  ];
  return (
    <section aria-labelledby="storage-change" className="space-y-2">
      <h3 id="storage-change" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("storage.change")}</h3>
      <p className="text-xs text-muted-foreground">{t("storage.changeHint")}</p>
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-[11px] leading-relaxed">{lines.join("\n")}</pre>
      <p className="text-xs text-muted-foreground">{t("storage.changeNote")}</p>
    </section>
  );
}

function Backups({ b, writable }: { b: MetadataBackups; writable: boolean }) {
  const t = useT();
  const qc = useQueryClient();
  const now = useMutation({ mutationFn: api.requestBackup, onSuccess: () => qc.invalidateQueries({ queryKey: ["storage"] }) });
  const latest = b.files[0];
  const waitingLong = b.pending_since != null && Date.now() - new Date(b.pending_since).getTime() > 120_000;
  return (
    <section aria-labelledby="storage-backups" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 id="storage-backups" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("storage.backups.title")}</h3>
        <Button size="sm" variant="outline" onClick={() => now.mutate()} disabled={!writable || now.isPending || b.pending_since != null}>
          <DatabaseBackup className="h-3.5 w-3.5" aria-hidden /> {t("storage.backups.now")}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t("storage.backups.hint", { hours: b.interval_hours, keep: b.keep })}</p>
      <p className="text-xs">
        {latest
          ? t("storage.backups.latest", { when: fmtDate(latest.created_at), size: fmtBytes(latest.size_bytes), kind: t(`storage.backups.kind.${latest.kind}` as TranslationKey) })
          : t("storage.backups.none")}
      </p>
      {b.count > 0 && <p className="text-xs text-muted-foreground">{t("storage.backups.count", { n: b.count, folder: b.host_folder ?? b.folder })}</p>}
      {b.pending_since && (
        <p className={cn("text-xs", waitingLong ? "text-amber-700 dark:text-warning" : "text-muted-foreground")}>
          {t(waitingLong ? "storage.backups.pendingLong" : "storage.backups.pending", { when: fmtDate(b.pending_since) })}
        </p>
      )}
      {b.last_result?.result === "failed" && (
        <p className="text-xs text-danger">{t("storage.backups.lastFailed", { when: fmtDate(b.last_result.at), detail: b.last_result.code && b.last_result.code !== "ok" ? t(`storage.backups.code.${b.last_result.code}`) : b.last_result.detail ?? "" })}</p>
      )}
      <ErrorNote error={now.error} />
      <p className="text-xs text-muted-foreground">{t("storage.backups.restore")}</p>
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-[11px] leading-relaxed">{RESTORE_COMMANDS}</pre>
    </section>
  );
}
