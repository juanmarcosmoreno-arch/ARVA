import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, ExternalLink, Info, Loader2, Play, ShieldCheck } from "lucide-react";
import { useId, type ReactNode } from "react";
import { CopyErrorDetails } from "@/components/diagnostics/CopyErrorDetails";
import { MetricTile } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes, fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { fileValidation, jobError, messageText } from "@/lib/messages";
import { fileTime, runOverview, signalHours } from "@/lib/pod5";
import { latestJobFor } from "@/lib/results";
import type { AnalysisJobDetail, Library, Pod5Summary, RawFile } from "@/lib/types";

type T = ReturnType<typeof useT>;

const DORADO_DOCS = "https://software-docs.nanoporetech.com/dorado/latest/";
const POD5_JOB = "pod5_summary";

export function useLibraries() {
  return useQuery({ queryKey: ["libraries"], queryFn: api.libraries, staleTime: 60_000 });
}

/** One card per POD5 file of the sample, with the honest note that ARVA does not basecall. */
export function RawSignalSection({ sampleId, files, jobs }: { sampleId: string; files: RawFile[]; jobs: AnalysisJobDetail[] }) {
  const t = useT();
  const headingId = useId();
  const libraries = useLibraries();
  const signalFiles = files.filter((f) => f.file_format === "pod5");
  if (!signalFiles.length) return null;
  const library = libraries.data?.find((l) => l.id === "pod5");
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id={headingId} className="text-base font-semibold">
            {t("pod5.sectionTitle")}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("pod5.sectionSubtitle")}</p>
        </div>
        <Explain id="pod5" />
      </div>
      <div className="flex gap-2 rounded-xl border bg-muted/40 px-4 py-3 text-sm">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-arva-royal dark:text-arva-cyan" aria-hidden />
        <div className="min-w-0 space-y-1">
          <p className="font-medium">{t("pod5.noBasecalling")}</p>
          <p className="text-xs text-muted-foreground">{t("pod5.noBasecallingWhy")}</p>
          <a href={DORADO_DOCS} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan">
            {t("pod5.doradoDocs")} <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        </div>
      </div>
      {signalFiles.map((f) => (
        <RawSignalCard key={f.id} t={t} sampleId={sampleId} file={f} jobs={jobs} library={library} checking={libraries.isLoading} />
      ))}
    </section>
  );
}

function RawSignalCard({
  t,
  sampleId,
  file,
  jobs,
  library,
  checking,
}: {
  t: T;
  sampleId: string;
  file: RawFile;
  jobs: AnalysisJobDetail[];
  library: Library | undefined;
  checking: boolean;
}) {
  const qc = useQueryClient();
  const hintId = useId();
  const latest = latestJobFor(jobs, POD5_JOB, file.id, false);
  const done = latestJobFor(jobs, POD5_JOB, file.id);
  const running = latest?.status === "pending" || latest?.status === "running";
  const run = useMutation({
    mutationFn: () => api.runPod5Summary(sampleId, [file.id]),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs", sampleId] }),
  });
  const installed = library?.status === "available";
  const summary = done?.result_summary as unknown as Pod5Summary | undefined;

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="min-w-0 break-all">{file.original_filename}</span>
            <Badge tone="blue">{t("pod5.badge")}</Badge>
          </span>
        }
        description={fmtBytes(file.size_bytes)}
      />
      <CardBody className="space-y-4 pt-3">
        {!file.is_valid ? (
          <p className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
            <span className="min-w-0 break-words">{t("pod5.invalid", { message: fileValidation(t, file) })}</span>
          </p>
        ) : (
          <>
            {summary && done && <RunMetadata t={t} summary={summary} job={done} />}
            {latest?.status === "failed" && <ErrorNote error={jobError(t, latest)} />}
            {latest?.status === "failed" && <CopyErrorDetails jobId={latest.id} />}
            <div className="space-y-2">
              <p id={hintId} className="text-xs text-muted-foreground">
                {checking
                  ? t("pod5.checking")
                  : installed
                    ? t("pod5.readExplain", { version: library.version ?? "" })
                    : t("pod5.libraryMissing", { command: library?.install ?? 'pip install "pod5==0.3.49"' })}
              </p>
              <Button
                size="sm"
                variant="outline"
                disabled={!installed || running || run.isPending}
                onClick={() => run.mutate()}
                aria-describedby={hintId}
              >
                {running || run.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Play className="h-3.5 w-3.5" aria-hidden />}
                {running ? t("pod5.reading") : summary ? t("pod5.readAgain") : t("pod5.readAction")}
              </Button>
              <ErrorNote error={run.error} />
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm">{children}</dd>
    </div>
  );
}

const list = (values: string[]) => (values.length ? values.join(", ") : "—");

function RunMetadata({ t, summary, job }: { t: T; summary: Pod5Summary; job: AnalysisJobDetail }) {
  const o = runOverview(summary);
  const r = summary.reads;
  const hours = signalHours(r.total_signal_duration_s);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <MetricTile
          label={t("pod5.reads")}
          value={fmtInt(r.count)}
          sub={
            r.distinct_channels == null
              ? t("pod5.readsSubNoChannels", { samples: fmtInt(r.total_samples) })
              : t("pod5.readsSub", { samples: fmtInt(r.total_samples), channels: fmtInt(r.distinct_channels) })
          }
        />
        <MetricTile
          label={t("pod5.signal")}
          value={hours == null ? t("pod5.notReported") : t("pod5.hours", { hours: fmtNum(hours, 2) })}
          sub={t("pod5.signalSub")}
          explain="pod5"
        />
      </div>
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Fact label={t("pod5.sampleRate")}>{o.sampleRates.length ? o.sampleRates.map((v) => `${fmtInt(v)} Hz`).join(", ") : "—"}</Fact>
        <Fact label={t("pod5.flowCell")}>{list(o.flowCells)}</Fact>
        <Fact label={t("pod5.kit")}>{list(o.kits)}</Fact>
        <Fact label={t("pod5.protocol")}>
          <span className="break-all">{list(o.protocols)}</span>
        </Fact>
        <Fact label={t("pod5.experiment")}>{list(o.experiments)}</Fact>
        <Fact label={t("pod5.sampleInFile")}>{list(o.samples)}</Fact>
        <Fact label={t("pod5.runStart")}>{o.runStart ? fileTime(o.runStart) : "—"}</Fact>
        <Fact label={t("pod5.software")}>{list([...o.software, summary.file.writing_software].filter((v, i, a) => v && a.indexOf(v) === i))}</Fact>
      </dl>
      {summary.run_info_count > 1 && (
        <p className="text-xs text-muted-foreground">
          {t("pod5.acquisitions", { count: fmtInt(summary.run_info_count) })}
          {summary.run_infos_truncated && ` ${t("pod5.acquisitionsTruncated", { shown: fmtInt(summary.run_infos.length) })}`}
        </p>
      )}
      {summary.warnings.length > 0 && (
        <div className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-xs">
          <div className="mb-1 flex items-center gap-1.5 font-medium">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-hidden /> {t("pod5.warnings")}
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
            {summary.warnings.map((w, i) => (
              <li key={i} className="break-words">
                {messageText(t, "pod5.msg", w)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="flex gap-2 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="min-w-0">{t("pod5.withheld")}</span>
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          {t("pod5.provenance", {
            version: job.tool_version,
            lib: String(job.parameters?.lib_pod5_version ?? "—"),
            date: fmtDate(job.finished_at),
          })}
        </span>
        <a href={api.jobOutputUrl(job.id, "pod5_summary.json", true)} className="inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan">
          <Download className="h-3 w-3" aria-hidden /> {t("pod5.downloadJson")}
        </a>
      </div>
    </div>
  );
}
