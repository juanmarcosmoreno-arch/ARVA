import { useMutation, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { validFolder } from "@/lib/databases";
import { fmtBytes, fmtInt } from "@/lib/format";
import { serverText } from "@/lib/messages";
import type { CatalogueEntry } from "@/lib/types";
import { useRefreshDatabases } from "./RecordRow";
import { compatibilityText, ExtLink } from "./shared";

export function DownloadDialog({ entry, onClose }: { entry: CatalogueEntry; onClose: () => void }) {
  const t = useT();
  const refresh = useRefreshDatabases();
  const [accepted, setAccepted] = useState(false);
  const [destination, setDestination] = useState<string | null>(null);
  const [folder, setFolder] = useState<string>("");
  const folderOk = folder === "" || validFolder(folder);
  const plan = useQuery({
    queryKey: ["database-plan", entry.key, destination, folder],
    queryFn: () => api.databasePlan(entry.key, destination, folder || null),
    enabled: folderOk,
    staleTime: 0,
  });
  const start = useMutation({
    mutationFn: () => api.downloadDatabase(entry.key, entry.archive_bytes, accepted, destination, folder || null),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  const p = plan.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("databases.confirmTitle", { name: entry.name, version: entry.version })} description={t("databases.confirmText")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs">
            <span className="font-medium">{t("databases.destination")}</span>
            <Select value={destination ?? p?.db_dir ?? ""} onChange={(e) => setDestination(e.target.value)} aria-label={t("databases.destination")}>
              {(p?.destinations ?? []).map((d) => (
                <option key={d.path} value={d.path} disabled={!d.available}>
                  {d.host_path ?? d.path} · {d.free_bytes != null ? t("databases.freeShort", { free: fmtBytes(d.free_bytes) }) : t("databases.unavailable.disk_not_connected")}
                </option>
              ))}
            </Select>
            <span className="block text-muted-foreground">{t("databases.destinationHint")}</span>
          </label>
          <label className="space-y-1 text-xs">
            <span className="font-medium">{t("databases.folderName")}</span>
            <Input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder={entry.install_dir} className="font-mono text-xs" aria-invalid={!folderOk} />
            <span className={folderOk ? "block text-muted-foreground" : "block text-danger"}>{folderOk ? t("databases.folderNameHint") : t("api.error.bad_folder")}</span>
          </label>
        </div>
        <ErrorNote error={plan.error ?? start.error} />
        {!p ? (
          folderOk && <Skeleton className="h-48" />
        ) : (
          <>
            <dl className="grid grid-cols-[200px_1fr] gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-muted-foreground">{t("databases.source")}</dt>
              <dd className="min-w-0">
                <ExtLink href={entry.download_url}>{entry.download_url}</ExtLink>
                <div className="text-muted-foreground">
                  <ExtLink href={entry.source_url}>{entry.source_url}</ExtLink>
                </div>
              </dd>
              <dt className="text-muted-foreground">{t("databases.licence")}</dt>
              <dd>
                {entry.licence_url ? <ExtLink href={entry.licence_url}>{entry.licence}</ExtLink> : entry.licence}
                <p className="mt-0.5 text-muted-foreground">{serverText(t, `databases.catalogue.${entry.key}.terms`, entry.terms)}</p>
              </dd>
              <dt className="text-muted-foreground">{t("databases.compatibility")}</dt>
              <dd>
                {serverText(t, `databases.catalogue.${entry.key}.compatibility`, entry.compatibility)}
                <span className="block text-muted-foreground">{compatibilityText(t, p.compatibility)}</span>
              </dd>
              <dt className="text-muted-foreground">{t("databases.download")}</dt>
              <dd>
                {fmtBytes(entry.archive_bytes)} ({fmtInt(entry.archive_bytes)} {t("databases.bytes")})
              </dd>
              {p.partial_bytes > 0 && (
                <>
                  <dt className="text-muted-foreground">{t("databases.alreadyDownloaded")}</dt>
                  <dd>{fmtBytes(p.partial_bytes)}</dd>
                </>
              )}
              <dt className="text-muted-foreground">{t("databases.stillToDownload")}</dt>
              <dd>{fmtBytes(p.download_bytes)}</dd>
              <dt className="text-muted-foreground">{t("databases.roomToUnpack")}</dt>
              <dd>
                {fmtBytes(entry.extracted_bytes_estimate)}{" "}
                <span className="text-muted-foreground">({serverText(t, `databases.catalogue.${entry.key}.extracted`, entry.extracted_size_note)})</span>
              </dd>
              <dt className="font-medium">{t("databases.required")}</dt>
              <dd className="font-medium">{fmtBytes(p.required_bytes)}</dd>
              <dt className="text-muted-foreground">{t("databases.usableSpace")}</dt>
              <dd>
                {fmtBytes(p.available_bytes)}{" "}
                <span className="text-muted-foreground">{t("databases.usableSpaceHint", { free: fmtBytes(p.free_bytes), reserve: fmtBytes(p.reserve_bytes) })}</span>
              </dd>
              <dt className="text-muted-foreground">{t("databases.installInto")}</dt>
              <dd>
                <code className="break-all">{p.host_target_path}</code>
              </dd>
              <dt className="text-muted-foreground">{t("databases.checksum")}</dt>
              <dd>
                <code className="break-all">
                  {entry.checksum_algorithm.toUpperCase()} {entry.checksum}
                </code>
                <div className="text-muted-foreground">{t("databases.checksumSources", { sources: entry.checksum_sources.join("; ") })}</div>
              </dd>
            </dl>
            <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
              <li>{t("databases.step.download")}</li>
              <li>{t("databases.step.checksum")}</li>
              <li>{t("databases.step.extract")}</li>
              <li>{t("databases.step.checkKind")}</li>
              <li>{t("databases.step.cleanup")}</li>
            </ul>
            {p.blocked_by && <ErrorNote error={p.blocked_code ? t(`databases.blocked.${p.blocked_code}` as "databases.blocked.already_known") : p.blocked_by} />}
            {!p.enough && !p.blocked_by && <ErrorNote error={t("databases.notEnough", { required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })} />}
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className="mt-0.5" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
              <span>{t("databases.accept", { licence: entry.licence })}</span>
            </label>
          </>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => start.mutate()} disabled={!p || !accepted || !p.enough || !!p.blocked_by || start.isPending || !folderOk}>
            <Download className="h-4 w-4" aria-hidden /> {t("databases.confirmDownload", { size: fmtBytes(p?.download_bytes ?? entry.archive_bytes) })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
