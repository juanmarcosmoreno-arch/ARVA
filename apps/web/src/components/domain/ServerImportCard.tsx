import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ChevronRight, File as FileIcon, Folder, HardDriveDownload, Info, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { JobStatusBadge } from "@/components/domain/bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { capacityCheck } from "@/lib/capacity";
import { fmtBytes, fmtDate } from "@/lib/format";
import type { AnalysisJob, ImportEntry, ImportRoot, ServerImportSummary } from "@/lib/types";
import { jobError, rejectionText } from "@/lib/messages";

const IMPORTABLE_KINDS = new Set(["fastq", "fasta", "pod5"]);
const KIND_LABEL: Record<string, string> = { fastq: "FASTQ", fasta: "FASTA", pod5: "POD5" };

export function ServerImportCard({ sampleId, sampleCode }: { sampleId: string; sampleCode?: string }) {
  const t = useT();
  const roots = useQuery({ queryKey: ["importRoots"], queryFn: api.importRoots, staleTime: 60_000 });
  return (
    <Card>
      <CardHeader
        title={t("serverImport.title")}
        description={t("serverImport.subtitle")}
        action={<HardDriveDownload className="h-4 w-4 text-arva-teal" aria-hidden />}
      />
      <CardBody>
        {roots.isLoading ? (
          <Skeleton className="h-24" />
        ) : roots.error ? (
          <ErrorNote error={roots.error} />
        ) : roots.data?.length ? (
          <ServerBrowser roots={roots.data} sampleId={sampleId} sampleCode={sampleCode} />
        ) : (
          <div className="flex gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span>{t("serverImport.disabled")}</span>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ServerBrowser({ roots, sampleId, sampleCode }: { roots: ImportRoot[]; sampleId: string; sampleCode?: string }) {
  const t = useT();
  const qc = useQueryClient();
  const [rootIndex, setRootIndex] = useState(roots[0].index);
  const [path, setPath] = useState("");
  // Keyed by root-relative path, so files picked in several sub-folders stay selected.
  const [selected, setSelected] = useState<Map<string, ImportEntry>>(new Map());
  const [jobId, setJobId] = useState<string | null>(null);
  const root = roots.find((r) => r.index === rootIndex) ?? roots[0];

  const listing = useQuery({
    queryKey: ["importBrowse", root.index, path],
    queryFn: () => api.browseImport(root.index, path),
    enabled: root.exists,
  });
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage });
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => (!q.state.data || q.state.data.status === "pending" || q.state.data.status === "running" ? 1500 : false),
  });

  const chosen = [...selected.values()];
  const size = chosen.reduce((sum, e) => sum + (e.size_bytes ?? 0), 0);
  const fits = capacityCheck(size, storage.data);
  const notImportable = chosen.filter((e) => !IMPORTABLE_KINDS.has(e.kind)).length;
  const files = listing.data?.entries.filter((e) => e.type === "file") ?? [];
  const recognised = files.filter((e) => IMPORTABLE_KINDS.has(e.kind));
  const running = job.data?.status === "pending" || job.data?.status === "running";

  const start = useMutation({
    mutationFn: () => api.importFromServer(sampleId, { root: root.index, paths: chosen.map((e) => e.path) }),
    onSuccess: (j) => {
      setJobId(j.id);
      setSelected(new Map());
    },
  });

  const finished = job.data && !running ? job.data : null;
  const finishedKey = finished ? `${finished.id}:${finished.status}` : null;
  useEffect(() => {
    if (!finished) return;
    for (const key of [["files", finished.sample_id], ["sample", finished.sample_id], ["jobs", finished.sample_id], ["samples"], ["storage"], ["dashboard"]]) {
      qc.invalidateQueries({ queryKey: key });
    }
  }, [finishedKey, qc]);

  const go = (next: string) => setPath(next);
  const toggle = (e: ImportEntry) => {
    const next = new Map(selected);
    if (next.has(e.path)) next.delete(e.path);
    else next.set(e.path, e);
    setSelected(next);
  };
  const selectAll = () => {
    const next = new Map(selected);
    for (const e of recognised) next.set(e.path, e);
    setSelected(next);
  };
  const segments = path ? path.split("/") : [];

  return (
    <div className="space-y-4">
      {roots.length > 1 && (
        <Field label={t("serverImport.folder")}>
          <Select
            value={root.index}
            onChange={(e) => {
              setRootIndex(Number(e.target.value));
              setPath("");
              setSelected(new Map());
            }}
          >
            {roots.map((r) => (
              <option key={r.index} value={r.index}>
                {r.name} ({r.path})
              </option>
            ))}
          </Select>
        </Field>
      )}

      <nav aria-label={t("serverImport.path")}>
        <ol className="flex flex-wrap items-center gap-1 text-sm">
          <li>
            <button className="rounded px-1 font-medium text-arva-royal hover:underline dark:text-arva-cyan" onClick={() => go("")} title={root.path}>
              {root.name}
            </button>
          </li>
          {segments.map((seg, i) => (
            <li key={i} className="flex min-w-0 items-center gap-1">
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              {i === segments.length - 1 ? (
                <span className="break-all px-1" aria-current="page">
                  {seg}
                </span>
              ) : (
                <button className="break-all rounded px-1 text-arva-royal hover:underline dark:text-arva-cyan" onClick={() => go(segments.slice(0, i + 1).join("/"))}>
                  {seg}
                </button>
              )}
            </li>
          ))}
        </ol>
      </nav>

      {!root.exists ? (
        <ErrorNote error={t("serverImport.missing")} />
      ) : listing.isLoading ? (
        <Skeleton className="h-40" />
      ) : listing.error ? (
        <ErrorNote error={listing.error} />
      ) : (
        <>
          {listing.data?.entries.length === 0 ? (
            <p className="rounded-lg border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">{t("serverImport.empty")}</p>
          ) : (
            <ul className="max-h-80 divide-y overflow-y-auto rounded-lg border">
              {listing.data?.entries.map((e) =>
                e.type === "dir" ? (
                  <li key={e.path}>
                    <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50" onClick={() => go(e.path)}>
                      <Folder className="h-4 w-4 shrink-0 text-arva-teal" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{e.name}</span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    </button>
                  </li>
                ) : (
                  <li key={e.path}>
                    <label className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50">
                      <input type="checkbox" className="h-4 w-4 shrink-0 accent-[#00B4A6]" checked={selected.has(e.path)} onChange={() => toggle(e)} />
                      <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="min-w-0 flex-1 truncate" title={e.name}>
                        {e.name}
                      </span>
                      {KIND_LABEL[e.kind] && <Badge tone={IMPORTABLE_KINDS.has(e.kind) ? "teal" : "neutral"}>{KIND_LABEL[e.kind]}</Badge>}
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{fmtBytes(e.size_bytes ?? 0)}</span>
                      <span className="hidden shrink-0 text-xs text-muted-foreground md:inline">{fmtDate(e.modified_at)}</span>
                    </label>
                  </li>
                ),
              )}
            </ul>
          )}
          {listing.data?.truncated && <p className="text-xs text-amber-700 dark:text-warning">{t("serverImport.truncated", { count: listing.data.entries.length })}</p>}
          {!!listing.data?.unsupported_names && (
            <p className="text-xs text-amber-700 dark:text-warning">{t("serverImport.unsupportedNames", { count: listing.data.unsupported_names })}</p>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={recognised.length === 0} onClick={selectAll}>
          {t("serverImport.selectAll")}
        </Button>
        <Button size="sm" variant="ghost" disabled={selected.size === 0} onClick={() => setSelected(new Map())}>
          {t("serverImport.clear")}
        </Button>
      </div>

      {selected.size > 0 && (
        <div className="space-y-2 rounded-lg bg-muted p-3 text-xs">
          <div className="font-medium">
            {t("serverImport.selected", { count: selected.size, size: fmtBytes(size) })}
            {storage.data && (
              <span className="font-normal text-muted-foreground">
                {" "}
                · {t("storage.usable")}: {fmtBytes(storage.data.available_for_data_bytes)}
              </span>
            )}
          </div>
          {notImportable > 0 && <p className="text-amber-700 dark:text-warning">{t("serverImport.otherSelected", { count: notImportable })}</p>}
          {sampleId ? (
            <p className="text-muted-foreground">{t("serverImport.explain", { count: selected.size, size: fmtBytes(size), sample: sampleCode ?? "" })}</p>
          ) : (
            <p className="text-muted-foreground">{t("serverImport.needSample")}</p>
          )}
        </div>
      )}
      {fits === "insufficient" && storage.data && (
        <ErrorNote
          error={t("storage.insufficient", {
            needed: fmtBytes(size),
            available: fmtBytes(storage.data.available_for_data_bytes),
            reserve: fmtBytes(storage.data.min_free_bytes),
          })}
        />
      )}
      <ErrorNote error={start.error} />
      <div className="flex justify-end">
        <Button disabled={!sampleId || selected.size === 0 || fits === "insufficient" || start.isPending || running} onClick={() => start.mutate()}>
          {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <HardDriveDownload className="h-4 w-4" />}
          {t("serverImport.start", { count: selected.size })}
        </Button>
      </div>

      {job.data && <ImportJobResult job={job.data} running={running} />}
    </div>
  );
}

function ImportJobResult({ job, running }: { job: AnalysisJob; running: boolean }) {
  const t = useT();
  const summary = job.result_summary as ServerImportSummary | null;
  return (
    <div className="space-y-3 border-t pt-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <JobStatusBadge status={job.status} />
        <Link to={`/samples/${job.sample_id}`} className="inline-flex items-center gap-1 text-sm text-arva-royal hover:underline dark:text-arva-cyan">
          {t("serverImport.openSample")} <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      {running && <p className="text-xs text-muted-foreground">{t("serverImport.running")}</p>}
      {job.status === "failed" && !summary?.rejected.length && <ErrorNote error={jobError(t, job)} />}
      {summary && summary.imported.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">{t("serverImport.imported", { count: summary.imported.length })}</div>
          <ul className="space-y-1 text-sm">
            {summary.imported.map((f) => (
              <li key={f.file_id} className="flex items-start gap-2 rounded-lg border bg-surface px-3 py-2">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                <span className="min-w-0 flex-1 break-all">{f.path}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{fmtBytes(f.size_bytes)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {summary && summary.rejected.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">{t("serverImport.rejected", { count: summary.rejected.length })}</div>
          <ul className="space-y-1 text-sm">
            {summary.rejected.map((r, i) => (
              <li key={`${r.path}-${i}`} className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2">
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                <div className="min-w-0">
                  <div className="break-all font-medium">{r.path}</div>
                  <div className="break-words text-xs text-muted-foreground">{rejectionText(t, r)}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
