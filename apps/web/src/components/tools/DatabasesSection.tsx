import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, Download, ExternalLink, FolderPlus, HardDrive, ShieldCheck, Square, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes, fmtDate, fmtInt, fmtPct } from "@/lib/format";
import type { CatalogueEntry, DatabaseStatus, DatabaseUsage, ReferenceDatabase } from "@/lib/types";
import { databaseError, serverText } from "@/lib/messages";

const BUSY: DatabaseStatus[] = ["downloading", "verifying"];
const STATUS_TONE: Record<DatabaseStatus, "success" | "blue" | "warning" | "danger" | "neutral"> = {
  installed: "success",
  registered: "success",
  downloading: "blue",
  verifying: "blue",
  failed: "danger",
  cancelled: "warning",
};

const isBusy = (r: ReferenceDatabase) => BUSY.includes(r.status);

function useDatabases() {
  return useQuery({
    queryKey: ["databases"],
    queryFn: api.databases,
    refetchInterval: (q) => (q.state.data?.some(isBusy) ? 1500 : false),
  });
}

function ExtLink({ href, children }: { href: string; children: ReactNode }) {
  if (!/^https?:\/\//.test(href)) return <span className="break-all">{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 break-all text-arva-royal hover:underline dark:text-arva-cyan">
      {children} <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
    </a>
  );
}

function StatusBadge({ status }: { status: DatabaseStatus }) {
  const t = useT();
  return (
    <Badge tone={STATUS_TONE[status]}>
      {(status === "installed" || status === "registered") && <CheckCircle2 className="h-3 w-3" aria-hidden />}
      {t(`databases.status.${status}` as TranslationKey)}
    </Badge>
  );
}

export function DatabasesSection() {
  const t = useT();
  const catalogue = useQuery({ queryKey: ["database-catalogue"], queryFn: api.databaseCatalogue, staleTime: 300_000 });
  const records = useDatabases();
  const busy = records.data?.some(isBusy) ?? false;
  const usage = useQuery({ queryKey: ["database-usage"], queryFn: api.databaseUsage, refetchInterval: busy ? 3000 : 60_000 });
  const available = catalogue.data?.filter((e) => e.status === "available") ?? [];
  const planned = catalogue.data?.filter((e) => e.status === "planned") ?? [];

  return (
    <section aria-labelledby="reference-databases" className="space-y-3">
      <div>
        <h2 id="reference-databases" className="flex items-center gap-2 text-base font-semibold">
          <Database className="h-4 w-4 text-arva-royal dark:text-arva-cyan" aria-hidden /> {t("databases.title")}
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("databases.subtitle")}</p>
      </div>
      <ErrorNote error={catalogue.error ?? records.error ?? usage.error} />
      {usage.data && <UsageCard usage={usage.data} />}
      {catalogue.isLoading || records.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {available.map((e) => (
              <CatalogueCard key={e.key} entry={e} records={(records.data ?? []).filter((r) => r.key === e.key)} />
            ))}
          </div>
          <RecordsCard records={records.data ?? []} />
          <RegisterCard dbDir={usage.data?.db_dir} />
          {planned.length > 0 && (
            <Card>
              <CardHeader title={t("databases.planned")} description={t("databases.plannedHint")} />
              <CardBody className="pt-3">
                <ul className="space-y-2 text-sm">
                  {planned.map((e) => (
                    <li key={e.key} className="flex items-start gap-2">
                      <Badge>{t("common.planned")}</Badge>
                      <span>
                        <span className="font-medium">{e.name}</span> — <span className="text-muted-foreground">{e.description}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}
        </>
      )}
    </section>
  );
}

function UsageCard({ usage }: { usage: DatabaseUsage }) {
  const t = useT();
  const used = usage.total_bytes - usage.free_bytes;
  const pct = usage.total_bytes ? Math.round((used / usage.total_bytes) * 100) : 0;
  return (
    <Card>
      <CardBody className="space-y-2 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2 font-medium">
            <HardDrive className="h-4 w-4 text-muted-foreground" aria-hidden /> {t("databases.folder")}
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-normal">{usage.db_dir}</code>
          </span>
          <span className="text-xs text-muted-foreground">
            {t("databases.free", { free: fmtBytes(usage.free_bytes), total: fmtBytes(usage.total_bytes) })}
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={t("databases.diskUsed", { pct })}>
          <div className="h-full bg-arva-royal dark:bg-arva-cyan" style={{ width: `${pct}%` }} />
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs lg:grid-cols-4">
          <Fact label={t("databases.usage.installed")}>{fmtBytes(usage.installed_bytes)}</Fact>
          <Fact label={t("databases.usage.registered")}>{fmtBytes(usage.registered_bytes)}</Fact>
          <Fact label={t("databases.usage.partial")}>{fmtBytes(usage.partial_bytes + usage.staging_bytes)}</Fact>
          <Fact label={t("databases.usage.reserve")}>{fmtBytes(usage.reserve_bytes)}</Fact>
        </dl>
        <p className="text-xs text-muted-foreground">{t("databases.folderHint")}</p>
      </CardBody>
    </Card>
  );
}

function Fact({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-w-0 justify-between gap-2 lg:block">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Progress({ record }: { record: ReferenceDatabase }) {
  const t = useT();
  const p = record.progress;
  const done = p?.bytes_done ?? 0;
  const total = p?.bytes_total ?? 0;
  const pct = total ? Math.min(100, Math.floor((done / total) * 100)) : 0;
  const phase = p?.phase ?? "queued";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span>{t(`databases.phase.${phase}` as TranslationKey)}</span>
        <span className="text-muted-foreground">{total ? `${fmtBytes(done)} / ${fmtBytes(total)} (${fmtPct(pct, 0)})` : "—"}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-arva-teal transition-all" style={{ width: `${pct}%` }} />
      </div>
      {record.cancel_requested_at && <p className="text-xs text-muted-foreground">{t("databases.cancelling")}</p>}
    </div>
  );
}

function CatalogueCard({ entry, records }: { entry: CatalogueEntry; records: ReferenceDatabase[] }) {
  const t = useT();
  const [downloading, setDownloading] = useState(false);
  const current = records.find((r) => r.version === entry.version);
  const resumable = current && current.origin === "download" && (current.status === "failed" || current.status === "cancelled");
  const older = records.filter((r) => r.version !== entry.version && (r.status === "installed" || r.status === "registered"));
  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 font-semibold">
            {entry.name}
            <span className="text-sm font-normal text-muted-foreground">v{entry.version}</span>
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{serverText(t, `databases.catalogue.${entry.key}.description`, entry.description)}</p>
        </div>
        {current ? <StatusBadge status={current.status} /> : <Badge>{t("databases.notInstalled")}</Badge>}
      </div>
      <CardBody className="flex-1 space-y-3 pt-3 text-sm">
        {current && isBusy(current) && <Progress record={current} />}
        {older.length > 0 && (
          <p className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
            {t("databases.updateAvailable", { installed: older.map((r) => r.version).join(", "), latest: entry.version ?? "" })}
          </p>
        )}
        <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">{t("databases.released")}</dt>
          <dd>{entry.release_date}</dd>
          <dt className="text-muted-foreground">{t("databases.download")}</dt>
          <dd>
            {fmtBytes(entry.archive_bytes ?? 0)} ({fmtInt(entry.archive_bytes ?? 0)} {t("databases.bytes")}) · {entry.filename}
          </dd>
          <dt className="text-muted-foreground">{t("databases.unpacked")}</dt>
          <dd>{entry.extracted_size_note}</dd>
          <dt className="text-muted-foreground">{t("databases.checksum")}</dt>
          <dd className="min-w-0">
            <code className="break-all">
              {entry.checksum_algorithm?.toUpperCase()} {entry.checksum}
            </code>
            <div className="text-muted-foreground">{t("databases.checksumSources", { sources: entry.checksum_sources.join("; ") })}</div>
          </dd>
          <dt className="text-muted-foreground">{t("databases.licence")}</dt>
          <dd>{entry.licence_url ? <ExtLink href={entry.licence_url}>{entry.licence}</ExtLink> : entry.licence}</dd>
          <dt className="text-muted-foreground">{t("databases.source")}</dt>
          <dd className="min-w-0">
            {entry.source_url && <ExtLink href={entry.source_url}>{entry.source_url}</ExtLink>}
            {entry.doi && <div className="text-muted-foreground">doi:{entry.doi}</div>}
          </dd>
          <dt className="text-muted-foreground">{t("databases.compatibility")}</dt>
          <dd>{entry.compatibility}</dd>
        </dl>
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("databases.more")}</summary>
          <div className="mt-2 space-y-2">
            <p>{entry.terms}</p>
            <p className="text-muted-foreground">{entry.citation}</p>
            <div>
              <div className="font-medium">{t("databases.externalVersions")}</div>
              <p className="text-muted-foreground">
                {Object.entries(entry.external_versions)
                  .map(([name, v]) => `${name} ${v}`)
                  .join(" · ")}
              </p>
            </div>
            <ul className="list-disc space-y-1 pl-4">
              {entry.notes.map((n, i) => (
                <li key={n}>{serverText(t, `databases.catalogue.${entry.key}.note${i}`, n)}</li>
              ))}
            </ul>
          </div>
        </details>
        {(!current || resumable) && (
          <Button size="sm" onClick={() => setDownloading(true)}>
            <Download className="h-3.5 w-3.5" aria-hidden /> {resumable ? t("databases.resume") : t("databases.downloadAction")}
          </Button>
        )}
      </CardBody>
      {downloading && <DownloadDialog entry={entry} onClose={() => setDownloading(false)} />}
    </Card>
  );
}

function DownloadDialog({ entry, onClose }: { entry: CatalogueEntry; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [accepted, setAccepted] = useState(false);
  const plan = useQuery({ queryKey: ["database-plan", entry.key], queryFn: () => api.databasePlan(entry.key), staleTime: 0 });
  const start = useMutation({
    mutationFn: () => api.downloadDatabase(entry.key, entry.archive_bytes ?? 0, accepted),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["databases"] });
      qc.invalidateQueries({ queryKey: ["database-usage"] });
      onClose();
    },
  });
  const p = plan.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("databases.confirmTitle", { name: entry.name, version: entry.version ?? "" })} description={t("databases.confirmText")} className="max-w-2xl">
      <ErrorNote error={plan.error ?? start.error} />
      {!p ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="space-y-4 text-sm">
          <dl className="grid grid-cols-[200px_1fr] gap-x-3 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">{t("databases.source")}</dt>
            <dd className="min-w-0">
              <ExtLink href={entry.download_url ?? ""}>{entry.download_url}</ExtLink>
              <div className="text-muted-foreground">
                {t("databases.record")}: <ExtLink href={entry.source_url ?? ""}>{entry.source_url}</ExtLink>
              </div>
            </dd>
            <dt className="text-muted-foreground">{t("databases.licence")}</dt>
            <dd>
              {entry.licence_url ? <ExtLink href={entry.licence_url}>{entry.licence}</ExtLink> : entry.licence}
              <p className="mt-0.5 text-muted-foreground">{entry.terms}</p>
            </dd>
            <dt className="text-muted-foreground">{t("databases.download")}</dt>
            <dd>
              {fmtBytes(entry.archive_bytes ?? 0)} ({fmtInt(entry.archive_bytes ?? 0)} {t("databases.bytes")})
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
              {fmtBytes(entry.extracted_bytes_estimate ?? 0)} <span className="text-muted-foreground">({t("databases.roomToUnpackHint", { note: entry.extracted_size_note ?? "" })})</span>
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
              <code className="break-all">{p.target_path}</code>
            </dd>
            <dt className="text-muted-foreground">{t("databases.checksum")}</dt>
            <dd>
              <code className="break-all">
                {entry.checksum_algorithm?.toUpperCase()} {entry.checksum}
              </code>
            </dd>
          </dl>
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            <li>{t("databases.step.download")}</li>
            <li>{t("databases.step.checksum")}</li>
            <li>{t("databases.step.extract")}</li>
            <li>{t("databases.step.check")}</li>
            <li>{t("databases.step.cleanup")}</li>
          </ul>
          {p.blocked_by && <ErrorNote error={p.blocked_by} />}
          {!p.enough && !p.blocked_by && (
            <ErrorNote error={t("databases.notEnough", { required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })} />
          )}
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className="mt-0.5" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>{t("databases.accept", { licence: entry.licence ?? "" })}</span>
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button onClick={() => start.mutate()} disabled={!accepted || !p.enough || !!p.blocked_by || start.isPending}>
              <Download className="h-4 w-4" aria-hidden /> {t("databases.confirmDownload", { size: fmtBytes(p.download_bytes) })}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function RecordsCard({ records }: { records: ReferenceDatabase[] }) {
  const t = useT();
  return (
    <Card>
      <CardHeader title={t("databases.onComputer")} description={t("databases.onComputerHint")} />
      <CardBody className="pt-3">
        {records.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("databases.none")}</p>
        ) : (
          <div className="space-y-3">
            {records.map((r) => (
              <RecordRow key={r.id} record={r} />
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function RecordRow({ record }: { record: ReferenceDatabase }) {
  const t = useT();
  const qc = useQueryClient();
  const [deleting, setDeleting] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["databases"] });
    qc.invalidateQueries({ queryKey: ["database-usage"] });
  };
  const verify = useMutation({ mutationFn: () => api.verifyDatabase(record.id), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => api.cancelDatabaseTask(record.id), onSuccess: refresh });
  const log = useQuery({ queryKey: ["database", record.id], queryFn: () => api.database(record.id), enabled: false });
  const busy = isBusy(record);
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            {record.name} <span className="font-normal text-muted-foreground">v{record.version ?? "?"}</span>
            <StatusBadge status={record.status} />
            {record.available === false && (
              <Badge tone="danger">{t(`databases.unavailable.${record.unavailable_reason ?? "folder_missing"}` as TranslationKey)}</Badge>
            )}
            <Badge tone="neutral">{record.origin === "download" ? t("databases.origin.download") : t("databases.origin.register")}</Badge>
          </div>
          <code className="mt-1 block break-all text-xs text-muted-foreground">{record.host_path ?? record.path}</code>
          {record.available === false && <p className="mt-1 text-xs text-muted-foreground">{t("databases.unavailableHint")}</p>}
        </div>
        <div className="flex shrink-0 gap-2">
          {busy ? (
            <Button size="sm" variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending || !!record.cancel_requested_at}>
              <Square className="h-3.5 w-3.5" aria-hidden /> {t("databases.cancel")}
            </Button>
          ) : (
            <>
              {record.checksum && (
                <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending || record.available === false}>
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {t("databases.verify")}
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => setDeleting(true)}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden /> {t("databases.delete")}
              </Button>
            </>
          )}
        </div>
      </div>
      {busy && (
        <div className="mt-2">
          <Progress record={record} />
        </div>
      )}
      <ErrorNote error={verify.error ?? cancel.error} />
      {record.error_message && <p className="mt-2 text-xs text-danger">{databaseError(t, record)}</p>}
      {record.notes && <p className="mt-2 text-xs text-muted-foreground">{record.notes}</p>}
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs lg:grid-cols-4">
        <Fact label={t("databases.size")}>{record.size_bytes != null ? `${fmtBytes(record.size_bytes)} · ${t("databases.filesCount", { n: record.files ?? 0 })}` : "—"}</Fact>
        <Fact label={record.origin === "download" ? t("databases.installedAt") : t("databases.registeredAt")}>{fmtDate(record.installed_at)}</Fact>
        <Fact label={t("databases.verifiedAt")}>{fmtDate(record.verified_at)}</Fact>
        <Fact label={t("databases.licence")}>{record.licence ?? "—"}</Fact>
        <Fact label={t("databases.contentChecksum")}>
          <code className="break-all" title={record.checksum ?? undefined}>
            {record.checksum ? `${record.checksum.slice(0, 23)}…` : "—"}
          </code>
        </Fact>
        <Fact label={t("databases.archiveChecksum")}>
          <code className="break-all">{record.archive_checksum ?? t("databases.noArchive")}</code>
        </Fact>
        <Fact label={t("databases.source")}>{record.source_url ? <ExtLink href={record.source_url}>{t("databases.record")}</ExtLink> : "—"}</Fact>
        <Fact label={t("databases.usedBy")}>{t("databases.jobsUsing", { n: record.jobs_using })}</Fact>
      </dl>
      {record.key.startsWith("bakta") && record.checksum && (
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
  const owned = record.origin === "download";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("databases.deleteTitle", { name: record.name, version: record.version ?? "" })}>
      <div className="space-y-3 text-sm">
        <p>{owned ? t("databases.deleteOwned", { path: record.path ?? "", size: fmtBytes(record.size_bytes ?? 0) }) : t("databases.deleteRegistered", { path: record.path ?? "" })}</p>
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

function RegisterCard({ dbDir }: { dbDir: string | undefined }) {
  const t = useT();
  const qc = useQueryClient();
  const [path, setPath] = useState("");
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage });
  const added = (storage.data?.locations ?? []).filter((l) => l.role === "external_databases");
  const register = useMutation({
    mutationFn: () => api.registerDatabase(path.trim()),
    onSuccess: () => {
      setPath("");
      qc.invalidateQueries({ queryKey: ["databases"] });
      qc.invalidateQueries({ queryKey: ["database-usage"] });
    },
  });
  return (
    <Card>
      <CardHeader title={t("databases.registerTitle")} description={t("databases.registerHint", { dir: dbDir ?? "ARVA_DB_DIR" })} />
      <CardBody className="space-y-2 pt-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            register.mutate();
          }}
        >
          <label className="sr-only" htmlFor="register-db-path">
            {t("databases.registerPath")}
          </label>
          <input
            id="register-db-path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={`${dbDir ?? "/databases"}/bakta/db-light`}
            className="h-9 min-w-0 flex-1 rounded-lg border bg-surface px-3 font-mono text-xs"
          />
          <Button type="submit" size="sm" variant="outline" disabled={!path.trim() || register.isPending}>
            <FolderPlus className="h-3.5 w-3.5" aria-hidden /> {t("databases.register")}
          </Button>
        </form>
        <ErrorNote error={register.error} />
        {added.length > 0 && (
          <div className="space-y-1 pt-1 text-xs">
            <p className="text-muted-foreground">{t("databases.addedFolders")}</p>
            <ul className="space-y-1">
              {added.map((l) => (
                <li key={l.container_path} className="flex items-center justify-between gap-2">
                  <code className="min-w-0 break-all">{l.host_path ?? l.container_path}</code>
                  {l.available ? (
                    <Button size="sm" variant="ghost" onClick={() => setPath(l.host_path ?? l.container_path)}>
                      {t("databases.useFolder")}
                    </Button>
                  ) : (
                    <Badge tone="danger">{t("databases.unavailable.disk_not_connected")}</Badge>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
