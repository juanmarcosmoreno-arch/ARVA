import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Database, Download, FolderPlus, HardDrive } from "lucide-react";
import { useState, type ReactNode } from "react";
import { DownloadDialog } from "@/components/databases/DownloadDialog";
import { RecordRow } from "@/components/databases/RecordRow";
import { RegisterDialog } from "@/components/databases/RegisterDialog";
import { CompatibilityBadge, ExtLink, Fact, kindText, kindToolText, kindUnconfirmed } from "@/components/databases/shared";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { groupByKind, isBusy, type KindGroup } from "@/lib/databases";
import { fmtBytes } from "@/lib/format";
import { serverText } from "@/lib/messages";
import type { CatalogueEntry, DatabaseUsage } from "@/lib/types";

export function DatabasesSection() {
  const t = useT();
  const kinds = useQuery({ queryKey: ["database-kinds"], queryFn: api.databaseKinds, staleTime: 300_000 });
  const catalogue = useQuery({ queryKey: ["database-catalogue"], queryFn: api.databaseCatalogue, staleTime: 300_000 });
  const records = useQuery({
    queryKey: ["databases"],
    queryFn: api.databases,
    refetchInterval: (q) => (q.state.data?.some(isBusy) ? 1500 : false),
  });
  const busy = records.data?.some(isBusy) ?? false;
  const usage = useQuery({ queryKey: ["database-usage"], queryFn: api.databaseUsage, refetchInterval: busy ? 3000 : 60_000 });
  const [registering, setRegistering] = useState(false);
  const groups = kinds.data && catalogue.data && records.data ? groupByKind(kinds.data, records.data, catalogue.data) : null;
  const inUse = groups?.filter((g) => g.records.length > 0 || g.versions.length > 0) ?? [];
  const others = groups?.filter((g) => g.records.length === 0 && g.versions.length === 0) ?? [];

  return (
    <section aria-labelledby="reference-databases" className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="reference-databases" className="flex items-center gap-2 text-base font-semibold">
            <Database className="h-4 w-4 text-arva-royal dark:text-arva-cyan" aria-hidden /> {t("databases.title")}
            <Explain id="reference_databases" />
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("databases.subtitle")}</p>
        </div>
        <Button size="sm" onClick={() => setRegistering(true)}>
          <FolderPlus className="h-3.5 w-3.5" aria-hidden /> {t("databases.registerAction")}
        </Button>
      </div>
      <ErrorNote error={kinds.error ?? catalogue.error ?? records.error ?? usage.error} />
      {usage.data && <UsageCard usage={usage.data} />}
      {!groups ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="space-y-3">
            {inUse.map((g) => (
              <KindCard key={g.kind.key} group={g} />
            ))}
          </div>
          {others.length > 0 && (
            <div className="space-y-2">
              <h3 className="flex items-center gap-1 text-sm font-semibold">
                {t("databases.otherKinds")} <Explain id="database_versions" />
              </h3>
              <p className="text-xs text-muted-foreground">{t("databases.otherKindsHint")}</p>
              <div className="space-y-2">
                {others.map((g) => (
                  <KindCard key={g.kind.key} group={g} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
      {registering && <RegisterDialog onClose={() => setRegistering(false)} />}
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
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-normal">{usage.host_db_dir ?? usage.db_dir}</code>
          </span>
          <span className="text-xs text-muted-foreground">{t("databases.free", { free: fmtBytes(usage.free_bytes), total: fmtBytes(usage.total_bytes) })}</span>
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

function KindCard({ group }: { group: KindGroup }) {
  const t = useT();
  const { kind, records, versions } = group;
  const [open, setOpen] = useState(records.length > 0);
  const [downloading, setDownloading] = useState<CatalogueEntry | null>(null);
  return (
    <Card>
      <button type="button" className="flex w-full items-start justify-between gap-3 px-5 py-4 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 font-semibold">
            {kindText(t, kind, "name")}
            {records.length > 0 && <Badge tone="blue">{t("databases.countKnown", { n: records.length })}</Badge>}
            {kind.download === "catalogue" ? <Badge>{t("databases.downloadable")}</Badge> : <Badge>{t("databases.registerOnly")}</Badge>}
            {kind.user_provided_only && <Badge tone="warning">{t("databases.userProvided")}</Badge>}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{kindText(t, kind, "description")}</p>
        </div>
        <ChevronDown className={`mt-1 h-4 w-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <CardBody className="space-y-3 pt-0 text-sm">
          {records.length > 0 ? (
            <div className="space-y-2">
              {records.map((r) => (
                <RecordRow key={r.id} record={r} />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t("databases.noneOfKind")}</p>
          )}
          {versions.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("databases.versionsToDownload")}</h4>
              {versions.map((e) => (
                <VersionRow key={e.key} entry={e} installed={records.some((r) => r.key === e.key && r.version === e.version && r.status !== "failed" && r.status !== "cancelled")} onDownload={() => setDownloading(e)} />
              ))}
            </div>
          )}
          <KindFacts group={group} />
        </CardBody>
      )}
      {downloading && <DownloadDialog entry={downloading} onClose={() => setDownloading(null)} />}
    </Card>
  );
}

function VersionRow({ entry, installed, onDownload }: { entry: CatalogueEntry; installed: boolean; onDownload: () => void }) {
  const t = useT();
  const incompatible = entry.compatibility_now.status === "incompatible";
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed p-3 text-xs">
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {entry.name} <span className="font-normal text-muted-foreground">{entry.version}</span>
          <CompatibilityBadge compatibility={entry.compatibility_now} />
        </p>
        <p className="text-muted-foreground">{serverText(t, `databases.catalogue.${entry.key}.description`, entry.description)}</p>
        <p className="text-muted-foreground">
          {t("databases.versionFacts", { size: fmtBytes(entry.archive_bytes), unpacked: fmtBytes(entry.extracted_bytes_estimate), date: entry.release_date ?? "?", licence: entry.licence })}
        </p>
        {entry.notes.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            {entry.notes.map((n, i) => (
              <li key={n}>{serverText(t, `databases.catalogue.${entry.key}.note${i}`, n)}</li>
            ))}
          </ul>
        )}
      </div>
      {installed ? (
        <Badge tone="success">{t("databases.alreadyHere")}</Badge>
      ) : (
        <Button size="sm" variant="outline" onClick={onDownload} disabled={incompatible} title={incompatible ? t("databases.incompatibleVersion") : undefined}>
          <Download className="h-3.5 w-3.5" aria-hidden /> {t("databases.downloadAction")}
        </Button>
      )}
    </div>
  );
}

function KindFacts({ group }: { group: KindGroup }) {
  const t = useT();
  const { kind } = group;
  const row = (label: string, value: ReactNode) => (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{value}</dd>
    </>
  );
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("databases.kindFacts")}</summary>
      <dl className="mt-2 grid grid-cols-[170px_1fr] gap-x-3 gap-y-1.5">
        {row(t("databases.recognisedBy"), kindText(t, kind, "recognise"))}
        {row(t("databases.versionLabel"), kindText(t, kind, "version_from"))}
        {row(
          t("databases.tools"),
          <ul className="space-y-0.5">
            {kind.tools.map((tool, i) => (
              <li key={tool.tool}>
                <span className="font-medium">{tool.tool}</span>: {kindToolText(t, kind, i)}
                {tool.integrated && <Badge className="ml-1" tone="success">{t("databases.integrated")}</Badge>}
              </li>
            ))}
          </ul>,
        )}
        {row(t("databases.typicalSize"), kindText(t, kind, "typical_size"))}
        {row(t("databases.downloadByArva"), kindText(t, kind, "download_note"))}
        {row(t("databases.licence"), kind.licence_url ? <ExtLink href={kind.licence_url}>{kindText(t, kind, "licence")}</ExtLink> : kindText(t, kind, "licence"))}
        {row(t("databases.source"), <ExtLink href={kind.source_url}>{kind.source_url}</ExtLink>)}
        {row(t("databases.citation"), kind.citation)}
        {row(t("databases.factSources"), kind.sources.join("; "))}
        {kind.unconfirmed.length > 0 &&
          row(
            t("databases.unconfirmed"),
            <ul className="list-disc space-y-0.5 pl-4">
              {kind.unconfirmed.map((u, i) => (
                <li key={u}>{kindUnconfirmed(t, kind, i)}</li>
              ))}
            </ul>,
          )}
      </dl>
    </details>
  );
}
