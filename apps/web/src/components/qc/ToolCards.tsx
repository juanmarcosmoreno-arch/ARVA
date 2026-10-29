import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, ExternalLink, Loader2, MinusCircle, Play, XCircle } from "lucide-react";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { dictionaries, useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { basename, latestJobFor } from "@/lib/results";
import type { AnalysisJobDetail, FastqcSummary, RawFile } from "@/lib/types";

const METRIC: Record<string, TranslationKey> = {
  Reads: "stats.reads",
  "Total bases": "stats.totalBases",
  "Minimum length": "crosscheck.minLength",
  "Maximum length": "crosscheck.maxLength",
  "Mean length": "crosscheck.meanLength",
  "Bases ≥ Q20 (%)": "crosscheck.q20",
  "Bases ≥ Q30 (%)": "crosscheck.q30",
};

function RunButton({ sampleId, file, tool, label, jobs }: { sampleId: string; file: RawFile; tool: "seqkit" | "fastqc"; label: string; jobs: AnalysisJobDetail[] }) {
  const t = useT();
  const qc = useQueryClient();
  const info = useTool(tool);
  const running = jobs.some(
    (j) => j.job_type === (tool === "seqkit" ? "seqkit_stats" : "fastqc") && (j.status === "pending" || j.status === "running") && j.input_raw_file_ids?.includes(file.id),
  );
  const run = useMutation({
    mutationFn: () => api.runPerFileTool(sampleId, tool, [file.id]),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs", sampleId] }),
  });
  const unavailable = info && info.status !== "available";
  return (
    <div className="space-y-2">
      <Button size="sm" variant="outline" disabled={running || run.isPending || !info || unavailable} onClick={() => run.mutate()}>
        {running || run.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        {running ? t("timeline.running") : label}
      </Button>
      {unavailable && <p className="text-xs text-muted-foreground">{t("crosscheck.notInstalled", { tool: info.name })}</p>}
      <ErrorNote error={run.error} />
    </div>
  );
}

export function CrossCheckCard({ sampleId, file, jobs }: { sampleId: string; file: RawFile; jobs: AnalysisJobDetail[] }) {
  const t = useT();
  const seqkitJob = latestJobFor(jobs, "seqkit_stats", file.id);
  const check = useQuery({
    queryKey: ["crosscheck", file.id, seqkitJob?.id],
    queryFn: () => api.crosscheck(file.id),
    enabled: !!seqkitJob,
  });
  const data = check.data;
  return (
    <Card>
      <CardHeader
        title={t("qcTools.seqkit")}
        description={t("crosscheck.hint")}
        action={<Explain id="crosscheck" />}
      />
      <CardBody className="pt-3">
        {!seqkitJob ? (
          <RunButton sampleId={sampleId} file={file} tool="seqkit" label={t("crosscheck.run")} jobs={jobs} />
        ) : !data || data.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{check.isLoading ? t("common.loading") : t("crosscheck.waiting")}</p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
              {data.all_agree ? (
                <Badge tone="success">
                  <CheckCircle2 className="h-3 w-3" /> {t("crosscheck.allAgree")}
                </Badge>
              ) : (
                <Badge tone="danger">
                  <XCircle className="h-3 w-3" /> {t("crosscheck.someDiffer")}
                </Badge>
              )}
              <span className="text-xs text-muted-foreground">
                SeqKit {data.tool_version} · {fmtDate(seqkitJob.finished_at)}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-1.5 pr-3 font-medium">{t("crosscheck.metric")}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">ARVA</th>
                    <th className="py-1.5 pr-3 text-right font-medium">SeqKit</th>
                    <th className="py-1.5 font-medium">{t("crosscheck.result")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.metric} className="border-b border-border/50">
                      <td className="py-1.5 pr-3">{METRIC[r.metric] ? t(METRIC[r.metric]) : r.metric}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{r.arva == null ? "—" : Number.isInteger(r.arva) ? fmtInt(r.arva) : fmtNum(r.arva, 3)}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">{r.tool == null ? "—" : Number.isInteger(r.tool) ? fmtInt(r.tool) : fmtNum(r.tool, 2)}</td>
                      <td className="py-1.5">
                        {r.agrees === null ? (
                          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                            <MinusCircle className="h-3.5 w-3.5" /> {t("crosscheck.notCompared")}
                          </span>
                        ) : r.agrees ? (
                          <span className="inline-flex items-center gap-1 text-xs text-success">
                            <CheckCircle2 className="h-3.5 w-3.5" /> {t("crosscheck.agrees")}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-danger">
                            <XCircle className="h-3.5 w-3.5" /> {t("crosscheck.differs")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">{data.note === dictionaries.en["crosscheck.note"] ? t("crosscheck.note") : data.note}</p>
          </>
        )}
      </CardBody>
    </Card>
  );
}

const FLAG_TONE = { PASS: "success", WARN: "warning", FAIL: "danger" } as const;

export function FastqcCard({ sampleId, file, jobs }: { sampleId: string; file: RawFile; jobs: AnalysisJobDetail[] }) {
  const t = useT();
  const job = latestJobFor(jobs, "fastqc", file.id);
  const s = job?.result_summary as unknown as FastqcSummary | undefined;
  const html = job?.output_paths?.find((p) => p.endsWith(".html"));
  const zip = job?.output_paths?.find((p) => p.endsWith(".zip"));
  return (
    <Card>
      <CardHeader
        title={t("qcTools.fastqc")}
        description={t("fastqcCard.hint")}
        action={<Explain id="fastqc_flags" />}
      />
      <CardBody className="pt-3">
        {!job || !s ? (
          <RunButton sampleId={sampleId} file={file} tool="fastqc" label={t("fastqcCard.run")} jobs={jobs} />
        ) : (
          <>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {s.modules.map((m) => (
                <li key={m.module} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-1.5 text-sm">
                  <span className="truncate">{m.module}</span>
                  <Badge tone={FLAG_TONE[m.status as keyof typeof FLAG_TONE] ?? "neutral"}>{m.status}</Badge>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {html && (
                <a href={api.jobOutputUrl(job.id, basename(html))} target="_blank" rel="noreferrer">
                  <Button size="sm" variant="outline">
                    <ExternalLink className="h-3.5 w-3.5" /> {t("fastqcCard.open")}
                  </Button>
                </a>
              )}
              {zip && (
                <a href={api.jobOutputUrl(job.id, basename(zip), true)}>
                  <Button size="sm" variant="ghost">
                    <Download className="h-3.5 w-3.5" /> {t("fastqcCard.data")}
                  </Button>
                </a>
              )}
              <span className="text-xs text-muted-foreground">
                FastQC {s.fastqc_version} · {fmtDate(job.finished_at)}
              </span>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
