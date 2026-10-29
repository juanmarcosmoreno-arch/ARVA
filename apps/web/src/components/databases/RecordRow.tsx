import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, Square, Star, Trash2, Zap } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { DatabaseNote } from "@/components/genomic/MlstDialog";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { isBusy } from "@/lib/databases";
import { fmtBytes, fmtDate, fmtInt } from "@/lib/format";
import { databaseError } from "@/lib/messages";
import type { ReferenceDatabase } from "@/lib/types";
import { compatibilityText, ExtLink, Fact, ProgressBar, RecordBadges } from "./shared";

export function useRefreshDatabases() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["databases"] });
    qc.invalidateQueries({ queryKey: ["database-usage"] });
  };
}

function VersionSourceLine({ record }: { record: ReferenceDatabase }) {
  const t = useT();
  if (record.version_source === "file") return <>{t("databases.versionFrom.file", { file: record.version_file ?? "?" })}</>;
  if (record.version_source === "declared") return <>{t("databases.versionFrom.declared")}</>;
  if (record.version_source === "checksum") return <>{t("databases.versionFrom.checksum")}</>;
  if (record.version_source === "download") return <>{t("databases.versionFrom.download")}</>;
  return <>{t("databases.versionFrom.unknown")}</>;
}

export function RecordRow({ record }: { record: ReferenceDatabase }) {
  const t = useT();
  const refresh = useRefreshDatabases();
  const [deleting, setDeleting] = useState(false);
  const quick = useMutation({ mutationFn: () => api.verifyDatabase(record.id, "quick"), onSuccess: refresh });
  const full = useMutation({ mutationFn: () => api.verifyDatabase(record.id, "full"), onSuccess: refresh });
  const makeDefault = useMutation({ mutationFn: () => api.setDefaultDatabase(record.id), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => api.cancelDatabaseTask(record.id), onSuccess: refresh });
  const log = useQuery({ queryKey: ["database", record.id], queryFn: () => api.database(record.id), enabled: false });
  const busy = isBusy(record);
  const ready = record.status === "installed" || record.status === "registered";
  const offline = record.available === false;
  const c = record.collection;
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            {record.name} <span className="font-normal text-muted-foreground">{record.version ?? t("databases.versionPending")}</span>
            <RecordBadges record={record} />
          </div>
          <code className="mt-1 block break-all text-xs text-muted-foreground">{record.host_path ?? record.path}</code>
          {offline && <p className="mt-1 text-xs text-muted-foreground">{t("databases.unavailableHint")}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {busy ? (
            <Button size="sm" variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending || !!record.cancel_requested_at}>
              <Square className="h-3.5 w-3.5" aria-hidden /> {t("databases.cancel")}
            </Button>
          ) : (
            <>
              {ready && !record.is_default && record.compatibility?.status !== "incompatible" && (
                <Button size="sm" variant="outline" onClick={() => makeDefault.mutate()} disabled={makeDefault.isPending || offline}>
                  <Star className="h-3.5 w-3.5" aria-hidden /> {t("databases.makeDefault")}
                </Button>
              )}
              {record.status !== "cancelled" && (
                <>
                  <Button size="sm" variant="outline" onClick={() => quick.mutate()} disabled={quick.isPending || offline} title={t("databases.quickHint")}>
                    <Zap className="h-3.5 w-3.5" aria-hidden /> {t("databases.quickCheck")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => full.mutate()} disabled={full.isPending || offline} title={t("databases.fullHint")}>
                    <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {t("databases.fullCheck")}
                  </Button>
                </>
              )}
              {record.origin !== "bundled" && (
                <Button size="sm" variant="outline" onClick={() => setDeleting(true)}>
                  <Trash2 className="h-3.5 w-3.5" aria-hidden /> {t("databases.delete")}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
      {busy && (
        <div className="mt-2">
          <ProgressBar record={record} />
        </div>
      )}
      <ErrorNote error={quick.error ?? full.error ?? cancel.error ?? makeDefault.error} />
      {record.error_message && <p className="mt-2 text-xs text-danger">{databaseError(t, record)}</p>}
      {record.compatibility?.status === "incompatible" && <p className="mt-2 text-xs text-danger">{compatibilityText(t, record.compatibility)}</p>}
      {record.notes && <p className="mt-2 text-xs text-muted-foreground">{record.notes}</p>}
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs lg:grid-cols-4">
        <Fact label={t("databases.versionSource")}>
          <VersionSourceLine record={record} />
        </Fact>
        <Fact label={t("databases.verification")}>
          {record.verification_level ? t(`databases.level.${record.verification_level}` as TranslationKey) : "—"}
          {record.verified_at && <span className="block text-muted-foreground">{fmtDate(record.verified_at)}</span>}
        </Fact>
        <Fact label={t("databases.size")}>
          {record.size_bytes != null ? fmtBytes(record.size_bytes) : "—"}
          {record.files != null && <span className="block text-muted-foreground">{t("databases.filesCount", { n: record.files })}</span>}
        </Fact>
        <Fact label={t("databases.contentChecksum")}>
          <code className="break-all" title={record.checksum ?? undefined}>
            {record.checksum ? `${record.checksum.slice(0, 23)}…` : t("databases.notComputed")}
          </code>
          {record.published_md5_checked ? <span className="block text-muted-foreground">{t("databases.publishedChecked", { n: record.published_md5_checked })}</span> : null}
        </Fact>
        <Fact label={record.origin === "register" ? t("databases.registeredAt") : record.origin === "bundled" ? t("databases.foundAt") : t("databases.installedAt")}>
          {fmtDate(record.installed_at)}
        </Fact>
        <Fact label={t("databases.origin")}>{t(`databases.origin.${record.origin}` as TranslationKey)}</Fact>
        <Fact label={t("databases.archiveChecksum")}>
          <code className="break-all">{record.archive_checksum ?? t("databases.noArchive")}</code>
        </Fact>
        <Fact label={t("databases.usedBy")}>{t("databases.jobsUsing", { n: record.jobs_using })}</Fact>
        {record.source_url && (
          <Fact label={t("databases.source")}>
            <ExtLink href={record.source_url}>{t("databases.sourceLink")}</ExtLink>
          </Fact>
        )}
      </dl>
      {c && (
        <div className="mt-2 rounded-lg bg-muted/40 p-2 text-xs">
          <p className="font-medium">
            {t("databases.coverage", { genomes: c.genomes, species: c.species })}
            {c.unclassified > 0 && <span className="font-normal text-muted-foreground"> · {t("databases.unclassified", { n: c.unclassified })}</span>}
          </p>
          <p className="text-muted-foreground">
            {t("databases.typeAndReference", { type: c.type_material.reduce((n, x) => n + (x.label === "TYPE_MATERIAL" ? x.genomes : 0), 0), reference: c.reference_genomes })}
          </p>
          <p className="mt-1 text-muted-foreground">
            {c.by_species
              .slice(0, 6)
              .map((s) => `${s.species === "unclassified" ? t("databases.unclassifiedName") : s.species} (${fmtInt(s.genomes)})`)
              .join(" · ")}
            {c.by_species.length > 6 && " …"}
          </p>
        </div>
      )}
      {record.mlst && <DatabaseNote plan={{ database: record.mlst }} />}
      {record.kind === "bakta" && record.verification_level === "full" && (
        <p className="mt-2 text-xs text-muted-foreground">
          {record.amrfinderplus_db
            ? t("databases.amrfinderDb", { version: record.amrfinderplus_db.version ?? "?", format: record.amrfinderplus_db.database_format ?? "?" })
            : t("databases.noAmrfinderDb")}
        </p>
      )}
      <details className="mt-2 text-xs" onToggle={(e) => (e.currentTarget.open ? log.refetch() : undefined)}>
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("databases.log")}</summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 font-mono text-[11px]">{log.data?.log_text ?? t("common.loading")}</pre>
      </details>
      {deleting && <DeleteDialog record={record} onClose={() => setDeleting(false)} onDone={refresh} />}
    </div>
  );
}

function DeleteDialog({ record, onClose, onDone }: { record: ReferenceDatabase; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const remove = useMutation({
    mutationFn: () => api.deleteDatabase(record.id),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  const owned = record.origin !== "register";
  const shown = record.host_path ?? record.path ?? "";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("databases.deleteTitle", { name: record.name, version: record.version ?? "" })}>
      <div className="space-y-3 text-sm">
        <p>{owned ? t("databases.deleteOwned", { path: shown, size: fmtBytes(record.size_bytes ?? 0) }) : t("databases.deleteRegistered", { path: shown })}</p>
        <p className="text-xs text-muted-foreground">{t("databases.deleteJobs")}</p>
        {record.jobs_using > 0 && <ErrorNote error={t("databases.deleteInUse", { n: record.jobs_using })} />}
        <ErrorNote error={remove.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending || record.jobs_using > 0}>
            <Trash2 className="h-4 w-4" aria-hidden /> {owned ? t("databases.deleteFiles") : t("databases.deleteRecord")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
