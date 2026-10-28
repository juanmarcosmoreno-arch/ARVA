import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, ExternalLink, Info, Loader2, Play, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import {
  NANOPLOT_JOB,
  STAT_ROWS,
  type CheckStatus,
  formatNanoplot,
  isLongReadTechnology,
  nanoplotCrossCheck,
  nanoplotOutputs,
  nanoplotSideBySide,
  zeroLengthReads,
} from "@/lib/nanoplot";
import { latestJobFor } from "@/lib/results";
import type { AnalysisJobDetail, NanoplotStats, NanoplotSummary, RawFile, SequenceStats, SequencingTechnology, Tool } from "@/lib/types";

const LINK_BUTTON =
  "inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted";
const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground";
const TD = "px-2 py-1.5 align-top";

/** QC tab card: NanoPlot's statistics and report for one long-read FASTQ file, next to ARVA's own numbers. */
export function NanoplotCard({
  sampleId,
  file,
  jobs,
  arva,
  technology,
}: {
  sampleId: string;
  file: RawFile;
  jobs: AnalysisJobDetail[];
  arva: SequenceStats;
  technology: SequencingTechnology;
}) {
  const t = useT();
  const done = latestJobFor(jobs, NANOPLOT_JOB, file.id);
  const newest = latestJobFor(jobs, NANOPLOT_JOB, file.id, false);
  const summary = done?.result_summary as unknown as NanoplotSummary | undefined;
  return (
    <Card className="min-w-0 lg:col-span-2">
      <CardHeader title={t("nanoplot.title")} description={t("nanoplot.subtitle")} action={<Explain id="nanoplot" />} />
      <CardBody className="space-y-5 pt-3">
        {newest?.status === "failed" && <ErrorNote error={t("nanoplot.failed", { error: newest.error_message ?? "?" })} />}
        {done && summary ? (
          <Result job={done} summary={summary} arva={arva} />
        ) : (
          <Start sampleId={sampleId} file={file} running={newest?.status === "pending" || newest?.status === "running"} technology={technology} />
        )}
      </CardBody>
    </Card>
  );
}

function Start({ sampleId, file, running, technology }: { sampleId: string; file: RawFile; running: boolean; technology: SequencingTechnology }) {
  const t = useT();
  const queryClient = useQueryClient();
  const tool = useTool("nanoplot");
  const longRead = isLongReadTechnology(technology);
  const [confirmed, setConfirmed] = useState(false);
  const run = useMutation({
    mutationFn: () => api.runNanoplot(sampleId, [file.id], !longRead && confirmed),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] }),
  });
  const available = tool?.status === "available";
  return (
    <div className="space-y-3">
      <Availability tool={tool} />
      <p className="text-xs">{t("nanoplot.explain", { version: (available ? tool.version : tool?.min_version) ?? "" })}</p>
      {!longRead && (
        <div className="space-y-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
          <p className="flex gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden /> {t("nanoplot.longReadsOnly")}
          </p>
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              {t("nanoplot.confirm")}
              <span className="block text-muted-foreground">{t("nanoplot.confirmHint")}</span>
            </span>
          </label>
        </div>
      )}
      <Button size="sm" variant="outline" onClick={() => run.mutate()} disabled={!available || running || run.isPending || (!longRead && !confirmed)}>
        {running || run.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        {running ? t("nanoplot.running") : t("nanoplot.run")}
      </Button>
      <ErrorNote error={run.error} />
    </div>
  );
}

function Availability({ tool }: { tool: Tool | undefined }) {
  const t = useT();
  if (!tool) return <p className="text-xs text-muted-foreground">{t("nanoplot.checking")}</p>;
  if (tool.status === "available") {
    return tool.version_validated ? null : (
      <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {toolMessage(t, tool)}
      </p>
    );
  }
  return (
    <div role="status" className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
      <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
      <p className="min-w-0 break-words">
        {tool.status === "not_installed" ? t("nanoplot.notInstalled") : t("nanoplot.unavailable", { message: toolMessage(t, tool) || tool.status })}{" "}
        <Link to="/tools" className="text-arva-royal hover:underline dark:text-arva-cyan">
          {t("nav.tools")}
        </Link>
      </p>
    </div>
  );
}

function Result({ job, summary, arva }: { job: AnalysisJobDetail; summary: NanoplotSummary; arva: SequenceStats }) {
  const t = useT();
  const out = nanoplotOutputs(job.output_paths);
  const { stats, post_filtering: post } = summary;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {out.report && (
          <a className={LINK_BUTTON} href={api.jobOutputUrl(job.id, out.report)} target="_blank" rel="noopener noreferrer">
            <ExternalLink className="h-3.5 w-3.5" aria-hidden /> {t("nanoplot.open")}
          </a>
        )}
        {[out.stats, out.postFiltering, out.log].map(
          (name) =>
            name && (
              <a key={name} className={LINK_BUTTON} href={api.jobOutputUrl(job.id, name, true)}>
                <Download className="h-3.5 w-3.5" aria-hidden /> <span className="max-w-[16rem] truncate">{name.replace(/^.*_(Nano)/, "$1")}</span>
              </a>
            ),
        )}
        <span className="text-xs text-muted-foreground">{t("nanoplot.meta", { version: summary.nanoplot_version, date: fmtDate(job.finished_at) })}</span>
      </div>

      <StatsTable stats={stats} post={post} />
      {post && <p className="text-xs text-muted-foreground">{t("nanoplot.postNote", { count: summary.artefact_reads_removed })}</p>}
      <AboveQuality stats={stats} />
      <CrossCheck arva={arva} stats={stats} />
      <SideBySide arva={arva} stats={stats} />

      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
        <li>{t("nanoplot.subsampleNote")}</li>
        <li>{t("nanoplot.logNote")}</li>
      </ul>
    </>
  );
}

function StatsTable({ stats, post }: { stats: NanoplotStats; post: NanoplotStats | null }) {
  const t = useT();
  const longest = (s: NanoplotStats) => (s.longest_reads[0] ? `${fmtInt(s.longest_reads[0].length)} bp (Q${fmtNum(s.longest_reads[0].quality, 1)})` : "—");
  return (
    <section aria-labelledby="np-stats" className="space-y-2">
      <h4 id="np-stats" className="text-sm font-semibold">
        {t("nanoplot.statsTitle")}
      </h4>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              <th scope="col" className={TH}>
                {t("nanoplot.colMetric")}
              </th>
              <th scope="col" className={`${TH} text-right`}>
                {t(post ? "nanoplot.colPre" : "nanoplot.colAll")}
              </th>
              {post && (
                <th scope="col" className={`${TH} text-right`}>
                  {t("nanoplot.colPost")}
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {STAT_ROWS.map((row) => (
              <tr key={row.key} className="border-t">
                <th scope="row" className={`${TD} min-w-[8rem] text-left font-normal`}>
                  <span className="font-medium">{t(row.label)}</span>
                  <span className="block text-[11px] text-muted-foreground">{t(row.definition)}</span>
                </th>
                <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>{formatNanoplot(stats[row.key], row.kind)}</td>
                {post && <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>{formatNanoplot(post[row.key], row.kind)}</td>}
              </tr>
            ))}
            <tr className="border-t">
              <th scope="row" className={`${TD} min-w-[8rem] text-left font-normal`}>
                <span className="font-medium">{t("nanoplot.stat.longest")}</span>
                <span className="block text-[11px] text-muted-foreground">{t("nanoplot.def.longest")}</span>
              </th>
              <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>{longest(stats)}</td>
              {post && <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>{longest(post)}</td>}
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AboveQuality({ stats }: { stats: NanoplotStats }) {
  const t = useT();
  if (!stats.reads_above_quality.length) return null;
  return (
    <section aria-labelledby="np-above" className="space-y-2">
      <h4 id="np-above" className="text-sm font-semibold">
        {t("nanoplot.aboveTitle")}
      </h4>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              <th scope="col" className={TH}>
                {t("nanoplot.colThreshold")}
              </th>
              <th scope="col" className={`${TH} text-right`}>
                {t("nanoplot.colReads")}
              </th>
              <th scope="col" className={`${TH} text-right`}>
                {t("nanoplot.colPercent")}
              </th>
              <th scope="col" className={`${TH} text-right`}>
                {t("nanoplot.colMegabases")}
              </th>
            </tr>
          </thead>
          <tbody>
            {stats.reads_above_quality.map((r) => (
              <tr key={r.threshold} className="border-t tabular-nums">
                <th scope="row" className={`${TD} text-left font-medium`}>
                  &gt; Q{r.threshold}
                </th>
                <td className={`${TD} text-right`}>{fmtInt(r.reads)}</td>
                <td className={`${TD} text-right`}>{fmtNum(r.percent, 1)}%</td>
                <td className={`${TD} text-right`}>{fmtNum(r.megabases, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{t("nanoplot.aboveNote")}</p>
    </section>
  );
}

const STATUS_STYLE: Record<CheckStatus, string> = {
  agrees: "text-success",
  explained: "text-arva-royal dark:text-arva-cyan",
  differs: "text-danger",
};
const STATUS_KEY: Record<CheckStatus, TranslationKey> = {
  agrees: "nanoplot.status.agrees",
  explained: "nanoplot.status.explained",
  differs: "nanoplot.status.differs",
};

function CrossCheck({ arva, stats }: { arva: SequenceStats; stats: NanoplotStats }) {
  const t = useT();
  const rows = nanoplotCrossCheck(arva, stats);
  const zero = zeroLengthReads(arva);
  return (
    <section aria-labelledby="np-check" className="space-y-2">
      <h4 id="np-check" className="text-sm font-semibold">
        {t("nanoplot.checkTitle")}
      </h4>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              <th scope="col" className={TH}>
                {t("nanoplot.colMetric")}
              </th>
              <th scope="col" className={`${TH} text-right`}>
                ARVA
              </th>
              <th scope="col" className={`${TH} text-right`}>
                NanoPlot
              </th>
              <th scope="col" className={TH}>
                {t("nanoplot.colResult")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric} className="border-t">
                <th scope="row" className={`${TD} text-left font-medium`}>
                  {t(r.metric === "reads" ? "nanoplot.stat.reads" : "nanoplot.stat.bases")}
                </th>
                <td className={`${TD} text-right tabular-nums`}>{fmtInt(r.arva)}</td>
                <td className={`${TD} text-right tabular-nums`}>{fmtInt(r.nanoplot)}</td>
                <td className={`${TD} ${STATUS_STYLE[r.status]}`}>
                  <span className="inline-flex items-start gap-1">
                    {r.status === "agrees" ? (
                      <CheckCircle2 className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                    ) : r.status === "explained" ? (
                      <Info className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                    ) : (
                      <XCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                    )}
                    {t(STATUS_KEY[r.status], { count: zero ?? 0 })}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("nanoplot.checkNote")} {zero === null && rows[0].status === "differs" ? t("nanoplot.zeroUnknown") : ""}
      </p>
    </section>
  );
}

function SideBySide({ arva, stats }: { arva: SequenceStats; stats: NanoplotStats }) {
  const t = useT();
  const rows = nanoplotSideBySide(arva, stats);
  return (
    <section aria-labelledby="np-side" className="space-y-2">
      <h4 id="np-side" className="text-sm font-semibold">
        {t("nanoplot.sideTitle")}
      </h4>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              <th scope="col" className={TH}>
                {t("nanoplot.colMetric")}
              </th>
              <th scope="col" className={`${TH} text-right`}>
                ARVA
              </th>
              <th scope="col" className={`${TH} text-right`}>
                NanoPlot
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t">
                <th scope="row" className={`${TD} min-w-[8rem] text-left font-normal`}>
                  <span className="font-medium">{r.threshold === undefined ? "N50" : t("nanoplot.side.above", { threshold: r.threshold })}</span>
                  <span className="block text-[11px] text-muted-foreground">
                    {r.threshold === undefined ? t("nanoplot.side.n50Why") : t("nanoplot.side.aboveWhy", { threshold: r.threshold })}
                  </span>
                </th>
                <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>
                  {r.threshold === undefined ? `${fmtInt(r.arva)} bp` : `${fmtInt(r.arva)} (≥ Q${r.threshold})`}
                </td>
                <td className={`${TD} whitespace-nowrap text-right tabular-nums`}>
                  {r.threshold === undefined ? `${fmtInt(r.nanoplot)} bp` : `${fmtInt(r.nanoplot)} (> Q${r.threshold})`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{t("nanoplot.sideNote")}</p>
    </section>
  );
}
