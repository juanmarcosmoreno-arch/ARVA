import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Copy, CornerDownRight, Download, ExternalLink, FileText, Filter, Loader2, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  CumulativeYieldChart,
  GcChart,
  LengthHistogramChart,
  PerPositionQualityChart,
  QualityVsLengthChart,
  ReadQualityChart,
} from "@/components/charts/QcCharts";
import { AnalysisTimeline, JobStatusBadge, MetricTile, type Stage } from "@/components/domain/bits";
import { FileDropzone } from "@/components/domain/FileDropzone";
import { CustomMetadataList } from "@/components/domain/MetadataImport";
import { RawSignalSection } from "@/components/domain/RawSignal";
import { ReadHeadersCard, TechnologySuggestion, useHeaderSummary } from "@/components/domain/ReadHeaders";
import { BeforeAfter } from "@/components/filtering/BeforeAfter";
import { FilterDialog } from "@/components/filtering/FilterDialog";
import { FastpDataSection } from "@/components/qc/FastpData";
import { FastqcDataSection } from "@/components/qc/FastqcData";
import { NanoplotCard } from "@/components/qc/NanoplotCard";
import { SequencingOverview } from "@/components/qc/SequencingOverview";
import { CrossCheckCard, FastqcCard } from "@/components/qc/ToolCards";
import { useTools } from "@/components/tools/useTools";
import { SampleMetadataEditor } from "@/components/domain/SampleForm";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorNote, PageHeader, Skeleton, Tabs } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtBytes, fmtDate, fmtDuration, fmtInt, fmtNum, formatLabel, technologyLabel } from "@/lib/format";
import { lineageOrder } from "@/lib/filters";
import { NANOPLOT_JOB } from "@/lib/nanoplot";
import { FASTQC_JOB, fastpJobFor } from "@/lib/qcData";
import { FILTER_JOBS, IMPORT_JOBS, RAW_SIGNAL_JOBS, basename, hasReads, inProcessTool, jobLabel, latestJobFor, latestResults } from "@/lib/results";
import type { AnalysisJobDetail, HeaderSummary, RawFile, SequencingTechnology } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tab = "files" | "qc" | "filtering" | "history" | "metadata";

export function SampleDetailPage() {
  const { sampleId = "" } = useParams();
  const t = useT();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "files";
  const setTab = (next: Tab) => setParams((p) => ({ ...Object.fromEntries(p), tab: next }), { replace: true });

  const sample = useQuery({ queryKey: ["sample", sampleId], queryFn: () => api.sample(sampleId) });
  const files = useQuery({ queryKey: ["files", sampleId], queryFn: () => api.files(sampleId) });
  const jobs = useQuery({
    queryKey: ["jobs", sampleId],
    queryFn: () => api.sampleJobs(sampleId),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "pending" || j.status === "running") ? 1500 : false),
  });
  const headerSummary = useHeaderSummary(sample.data, files.data);

  const isActive = (j: AnalysisJobDetail) => j.status === "pending" || j.status === "running";
  const allJobs = jobs.data ?? [];
  const qcJobs = allJobs.filter((j) => !FILTER_JOBS.has(j.job_type) && !IMPORT_JOBS.has(j.job_type) && !RAW_SIGNAL_JOBS.has(j.job_type));
  const filterJobs = allJobs.filter((j) => FILTER_JOBS.has(j.job_type));
  const signalJobs = allJobs.filter((j) => RAW_SIGNAL_JOBS.has(j.job_type));
  const importing = allJobs.some((j) => IMPORT_JOBS.has(j.job_type) && isActive(j));
  const readingSignal = signalJobs.some(isActive);
  const completed = qcJobs.filter((j) => j.status === "completed");
  const latestFailed = qcJobs[0]?.status === "failed";
  const [filterOpen, setFilterOpen] = useState(false);
  const queryClient = useQueryClient();
  const finishedCount = allJobs.filter((j) => j.status === "completed" || j.status === "failed").length;
  useEffect(() => {
    // Jobs can create derived files and cross-check data; refresh them whenever a job finishes.
    queryClient.invalidateQueries({ queryKey: ["files", sampleId] });
    queryClient.invalidateQueries({ queryKey: ["crosscheck"] });
  }, [finishedCount, sampleId, queryClient]);

  const stages: Stage[] = [
    {
      key: "raw",
      label: "Raw data",
      state: importing || readingSignal ? "running" : files.data?.length ? "done" : "ready",
      detail: importing ? "Importing…" : readingSignal ? t("pod5.reading") : files.data?.length ? `${files.data.length} file(s)` : "Import reads",
    },
    {
      key: "qc",
      label: "Read QC",
      state: qcJobs.some(isActive) ? "running" : latestFailed ? "failed" : completed.length ? "done" : "ready",
      detail: qcJobs.some(isActive) ? "Computing…" : completed.length ? `${completed.length} run(s)` : "Not run",
    },
    {
      key: "filtering",
      label: "Filtering",
      state: filterJobs.some(isActive) ? "running" : filterJobs[0]?.status === "failed" ? "failed" : filterJobs.some((j) => j.status === "completed") ? "done" : "ready",
      detail: filterJobs.some(isActive) ? "Running…" : filterJobs.length ? `${filterJobs.filter((j) => j.status === "completed").length} run(s)` : "Optional",
    },
    { key: "assembly", label: "Assembly", state: "planned", phase: 3 },
    { key: "polishing", label: "Polishing", state: "planned", phase: 3 },
    { key: "annotation", label: "Annotation", state: "planned", phase: 4 },
    { key: "biology", label: "Biological analysis", state: "planned", phase: 5 },
  ];

  if (sample.isLoading) return <Skeleton className="h-40" />;
  if (sample.error || !sample.data) return <ErrorNote error={sample.error ?? "Sample not found"} />;
  const s = sample.data;

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        eyebrow={
          <span>
            <Link to="/projects" className="hover:underline">{t("nav.projects")}</Link> /{" "}
            <Link to={`/projects/${s.project_id}`} className="hover:underline">{s.project_name}</Link>
          </span>
        }
        title={s.sample_code}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {s.organism && <i>{s.organism}</i>}
            <Badge tone={s.sequencing_technology === "unknown" ? "neutral" : "blue"}>{technologyLabel[s.sequencing_technology]}</Badge>
            <TechnologySuggestion sample={s} summary={headerSummary.data} />
            {s.host && <span>Host: {s.host}</span>}
            {s.geographic_origin && <span>· {s.geographic_origin}</span>}
          </span>
        }
        actions={<ReportMenu sampleId={s.id} disabled={!completed.length && !signalJobs.some((j) => j.status === "completed")} />}
      />

      <Card className="px-4 pb-2 pt-5">
        <AnalysisTimeline
          stages={stages}
          selected={tab === "files" ? "raw" : tab === "qc" ? "qc" : tab === "filtering" ? "filtering" : undefined}
          onSelect={(k) => setTab(k === "raw" ? "files" : k === "filtering" ? "filtering" : "qc")}
        />
      </Card>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        items={[
          { value: "files", label: t("sample.files") },
          { value: "qc", label: t("sample.qc") },
          { value: "filtering", label: `${t("sample.filtering")}${filterJobs.length ? ` (${filterJobs.length})` : ""}` },
          { value: "history", label: `${t("sample.history")}${jobs.data?.length ? ` (${jobs.data.length})` : ""}` },
          { value: "metadata", label: t("sample.metadata") },
        ]}
      />

      {tab === "files" && (
        <FilesTab
          sampleId={s.id}
          files={files.data ?? []}
          loading={files.isLoading}
          headerSummary={headerSummary.data}
          onStarted={() => setTab("qc")}
          onFilter={() => setFilterOpen(true)}
        />
      )}
      {tab === "qc" && (
        <QcTab
          sampleId={s.id}
          jobs={allJobs}
          files={files.data ?? []}
          sampleCode={s.sample_code}
          technology={s.sequencing_technology}
          onGoFiles={() => setTab("files")}
          activeCount={qcJobs.filter(isActive).length}
        />
      )}
      {tab === "filtering" && (
        <FilteringTab jobs={allJobs} files={files.data ?? []} onNew={() => setFilterOpen(true)} technology={s.sequencing_technology} />
      )}
      {tab === "history" && <HistoryTab jobs={jobs.data ?? []} files={files.data ?? []} openJob={params.get("job")} />}
      {tab === "metadata" && (
        <Card>
          <CardBody>
            <SampleMetadataEditor sample={s} />
            <CustomMetadataList sample={s} />
          </CardBody>
        </Card>
      )}
      <FilterDialog
        open={filterOpen}
        onOpenChange={setFilterOpen}
        sampleId={s.id}
        files={files.data ?? []}
        technology={s.sequencing_technology}
        onStarted={() => setTab("filtering")}
      />
    </div>
  );
}

function ReportMenu({ sampleId, disabled }: { sampleId: string; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <Button variant="outline" onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={disabled} title={disabled ? "Compute read statistics first" : undefined}>
        <FileText className="h-4 w-4" /> Report <ChevronDown className="h-3.5 w-3.5" />
      </Button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-56 rounded-xl border bg-surface py-1 text-sm shadow-lg">
          {[
            { f: "html", label: "HTML report", sub: "Printable, with figures & methods" },
            { f: "csv", label: "CSV table", sub: "One row per file" },
            { f: "json", label: "JSON", sub: "Full structured results" },
          ].map((o) => (
            <a key={o.f} href={api.reportUrl(sampleId, o.f as "html")} download className="block px-3 py-2 hover:bg-muted" onClick={() => setOpen(false)}>
              <div className="flex items-center gap-2">
                <Download className="h-3.5 w-3.5" />
                {o.label}
              </div>
              <div className="pl-5 text-xs text-muted-foreground">{o.sub}</div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Raw data ---------------------------------------------------------------

function FilesTab({
  sampleId,
  files,
  loading,
  headerSummary,
  onStarted,
  onFilter,
}: {
  sampleId: string;
  files: RawFile[];
  loading: boolean;
  headerSummary: HeaderSummary | undefined;
  onStarted: () => void;
  onFilter: () => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const analysable = files.filter((f) => hasReads(f.file_format));
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const chosen = selected ?? new Set(analysable.filter((f) => f.origin === "imported").map((f) => f.id));
  const tools = useTools();
  const toolStatus = (id: string) => tools.data?.find((t) => t.id === id);
  const runTool = useMutation({
    mutationFn: (tool: "seqkit" | "fastqc") =>
      api.runPerFileTool(
        sampleId,
        tool,
        [...chosen].filter((id) => tool === "seqkit" || files.find((f) => f.id === id)?.file_format.startsWith("fastq")),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs", sampleId] });
      onStarted();
    },
  });
  const hasFastq = files.some((f) => f.file_format.startsWith("fastq") && f.is_valid);
  const [genomeMbp, setGenomeMbp] = useState("");
  const [bins, setBins] = useState("50");

  const run = useMutation({
    mutationFn: () =>
      api.startSequenceStats(sampleId, {
        raw_file_ids: [...chosen],
        length_bins: Number(bins),
        expected_genome_size_bp: genomeMbp ? Math.round(Number(genomeMbp) * 1e6) : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs", sampleId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onStarted();
    },
  });

  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const genomeValid = !genomeMbp || (Number(genomeMbp) > 0 && Number.isFinite(Number(genomeMbp)));

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="min-w-0 space-y-6 xl:col-span-2">
        <Card>
          <CardHeader title="Import files" description="FASTQ/FASTA, plain or gzip-compressed. Drop several files or a whole folder." action={<Explain id="fastq" />} />
          <CardBody>
            <FileDropzone sampleId={sampleId} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={`Registered files (${files.length})`} description="Originals are stored read-only; analyses never modify them." action={<Explain id="integrity" />} />
          <CardBody className="pt-3">
            {loading ? (
              <Skeleton className="h-16" />
            ) : files.length === 0 ? (
              <p className="text-sm text-muted-foreground">No files yet.</p>
            ) : (
              <ul className="divide-y">
                {lineageOrder(files).map(({ file: f, depth }) => (
                  <li key={f.id} className="flex items-start gap-3 py-3" style={{ paddingLeft: depth * 24 }}>
                    {depth > 0 && <CornerDownRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 accent-[#00B4A6]"
                      checked={chosen.has(f.id)}
                      disabled={!hasReads(f.file_format)}
                      onChange={() => toggle(f.id)}
                      aria-label={`Include ${f.original_filename}`}
                      title={f.file_format === "pod5" ? t("pod5.notAnalysable") : undefined}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium">{f.original_filename}</span>
                        {f.file_format === "pod5" ? (
                          <Badge tone="blue">{t("pod5.badge")}</Badge>
                        ) : (
                          <Badge tone={f.file_format === "unknown" ? "danger" : "teal"}>{formatLabel[f.file_format]}</Badge>
                        )}
                        {f.read_mate && <Badge tone="blue">{f.read_mate}</Badge>}
                        {f.origin === "derived" && <Badge tone="neutral">Derived</Badge>}
                        {!f.is_valid && f.file_format !== "unknown" && (
                          <Badge tone="warning">
                            <AlertTriangle className="h-3 w-3" /> Invalid
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {fmtBytes(f.size_bytes)} · {fmtDate(f.uploaded_at)} · SHA-256 <Checksum value={f.checksum_sha256} />
                      </div>
                      {f.description && <div className="mt-0.5 text-xs text-foreground/80">{f.description}</div>}
                      <div className={cn("mt-0.5 text-xs", f.is_valid ? "text-muted-foreground" : "text-amber-700 dark:text-warning")}>{f.validation_message}</div>
                    </div>
                    <a href={api.fileDownloadUrl(f.id)} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted" aria-label={`Download ${f.original_filename}`}>
                      <Download className="h-4 w-4" />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
        <ReadHeadersCard files={files} summary={headerSummary} />
      </div>

      <Card className="h-fit">
        <CardHeader title="Compute read statistics" description="Streams every record of the selected files in a background worker." />
        <CardBody className="space-y-4">
          <Field label="Expected genome size (Mbp, optional)" hint="Only used to report an approximate depth (total bases ÷ genome size).">
            <Input inputMode="decimal" placeholder="e.g. 2.8" value={genomeMbp} onChange={(e) => setGenomeMbp(e.target.value)} aria-invalid={!genomeValid} />
          </Field>
          <Field label="Length histogram bins">
            <Select value={bins} onChange={(e) => setBins(e.target.value)}>
              {[25, 50, 100, 200].map((b) => (
                <option key={b}>{b}</option>
              ))}
            </Select>
          </Field>
          <div className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">
            Tool: <b>arva-core.seqstats</b>. Tool, version, parameters, input checksums, timings and logs are recorded with the result. No reads are filtered or modified.
          </div>
          <ErrorNote error={run.error} />
          <Button className="w-full" disabled={!chosen.size || !genomeValid || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Analyse {chosen.size} file{chosen.size === 1 ? "" : "s"}
          </Button>
        </CardBody>
      </Card>

      <Card className="h-fit xl:col-start-3">
        <CardHeader title="Quality control tools" description="External tools run on the selected files. Their versions and exact commands are recorded." />
        <CardBody className="space-y-3">
          {(
            [
              { id: "seqkit", label: "Independent check (SeqKit)", explain: "crosscheck" },
              { id: "fastqc", label: "FastQC report", explain: "fastqc_flags" },
            ] as const
          ).map((t) => {
            const info = toolStatus(t.id);
            const ok = info?.status === "available";
            return (
              <div key={t.id} className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-sm">
                    {t.label} <Explain id={t.explain} compact />
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {info ? (ok ? `${info.name} ${info.version}` : `${info.name}: not installed`) : "Checking…"}
                  </div>
                </div>
                <Button size="sm" variant="outline" disabled={!ok || !chosen.size || runTool.isPending} onClick={() => runTool.mutate(t.id)}>
                  <Play className="h-3.5 w-3.5" /> Run
                </Button>
              </div>
            );
          })}
          <ErrorNote error={runTool.error} />
          <div className="border-t pt-3">
            <Button variant="outline" className="w-full" disabled={!hasFastq} onClick={onFilter}>
              <Filter className="h-4 w-4" /> Filter reads…
            </Button>
            <p className="mt-1.5 text-xs text-muted-foreground">fastp (short reads) or Filtlong (long reads). Creates a new derived file; originals are kept.</p>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function Checksum({ value }: { value: string | null }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span>—</span>;
  return (
    <button
      className="inline-flex items-center gap-1 font-mono hover:text-foreground"
      title={value}
      onClick={() => {
        navigator.clipboard?.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
    >
      {value.slice(0, 12)}… <Copy className="h-3 w-3" />
      {copied && <span className="text-success">copied</span>}
    </button>
  );
}

// --- Read statistics --------------------------------------------------------

function QcTab({
  sampleId,
  jobs,
  files,
  sampleCode,
  technology,
  onGoFiles,
  activeCount,
}: {
  sampleId: string;
  jobs: AnalysisJobDetail[];
  files: RawFile[];
  sampleCode: string;
  technology: SequencingTechnology;
  onGoFiles: () => void;
  activeCount: number;
}) {
  const results = useMemo(() => latestResults(jobs), [jobs]);
  const withResults = files.filter((f) => results.has(f.id));
  const [fileId, setFileId] = useState<string | null>(null);
  const currentId = fileId && results.has(fileId) ? fileId : withResults[0]?.id;
  const current = currentId ? results.get(currentId) : undefined;
  const failed = jobs.filter((j) => j.status === "failed" && !IMPORT_JOBS.has(j.job_type) && !RAW_SIGNAL_JOBS.has(j.job_type)).slice(0, 3);
  const rawSignal = <RawSignalSection sampleId={sampleId} files={files} jobs={jobs} />;
  const overview = <SequencingOverview files={files} jobs={jobs} prefix={`ARVA_${sampleCode}`.replace(/[^A-Za-z0-9._-]+/g, "_")} />;

  if (!current) {
    return (
      <div className="space-y-4">
        {overview}
        {activeCount > 0 ? (
          <EmptyState icon={<Loader2 className="h-7 w-7 animate-spin text-arva-teal" />} title={`Computing statistics for ${activeCount} file(s)…`}>
            Results appear here automatically.
          </EmptyState>
        ) : (
          <EmptyState title="No read statistics yet">
            <Button onClick={onGoFiles}>Import files and run analysis</Button>
          </EmptyState>
        )}
        {rawSignal}
        <FailedJobs jobs={failed} />
      </div>
    );
  }

  const m = current.qc.metrics;
  const q = m.quality;
  const file = files.find((f) => f.id === currentId)!;
  const prefix = `ARVA_${sampleCode}_${file.original_filename.replace(/\.(fastq|fq|fasta|fa|fna)(\.gz)?$/i, "")}`.replace(/[^A-Za-z0-9._-]+/g, "_");
  const fastqcJob = m.file.format === "fastq" ? latestJobFor(jobs, FASTQC_JOB, file.id) : undefined;
  const fastpJob = fastpJobFor(jobs, file);

  return (
    <div className="space-y-6">
      {overview}
      <div className="flex flex-wrap items-end justify-between gap-3">
        {withResults.length > 1 ? (
          <Field label="File" className="w-full max-w-md">
            <Select value={currentId} onChange={(e) => setFileId(e.target.value)}>
              {withResults.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.original_filename}
                  {f.read_mate ? ` (${f.read_mate})` : ""}
                  {f.origin === "derived" ? " · derived" : ""}
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <div className="text-sm">
            <span className="text-muted-foreground">File </span>
            <b>{file.original_filename}</b>
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          {current.job.tool_name} {current.job.tool_version} · {fmtDate(current.job.finished_at)} · {fmtDuration(current.job.duration_seconds)}
          {activeCount > 0 && (
            <span className="ml-2 inline-flex items-center gap-1 text-arva-royal dark:text-arva-cyan">
              <Loader2 className="h-3 w-3 animate-spin" /> {activeCount} running
            </span>
          )}
        </div>
      </div>

      {m.warnings.length > 0 && (
        <div className="rounded-xl border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
          <div className="mb-1 flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4 text-warning" /> Warnings
          </div>
          <ul className="list-disc pl-6 text-muted-foreground">
            {m.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <MetricTile label={m.file.format === "fasta" ? "Sequences" : "Reads"} value={fmtInt(m.read_count)} explain="read_count" />
        <MetricTile label="Total bases" value={fmtBases(m.total_bases)} sub={`${fmtInt(m.total_bases)} bp`} explain="read_count" />
        <MetricTile label="Mean / median length" value={`${fmtInt(m.mean_length)} bp`} sub={`median ${fmtInt(m.median_length)} · range ${fmtInt(m.min_length)}–${fmtInt(m.max_length)}`} explain="length_distribution" />
        <MetricTile label="N50" value={`${fmtInt(m.n50)} bp`} sub={`L50 ${fmtInt(m.l50)} · N90 ${fmtInt(m.n90)} bp`} explain="n50" />
        <MetricTile label="GC content" value={`${fmtNum(m.gc_percent, 2)}%`} sub={`${fmtNum(m.ambiguous_percent, 3)}% ambiguous bases`} explain="gc_content" />
        {q && (
          <>
            <MetricTile label="Mean read quality" value={`Q${fmtNum(q.mean_read_quality)}`} sub={`median Q${fmtNum(q.median_read_quality)} · range Q${q.min_base_quality}–Q${q.max_base_quality}`} explain="read_quality" />
            <MetricTile label="Bases ≥ Q20" value={`${fmtNum(q.q20_bases_percent)}%`} explain="q20_q30" />
            <MetricTile label="Bases ≥ Q30" value={`${fmtNum(q.q30_bases_percent)}%`} explain="q20_q30" />
            <MetricTile label="Mean base quality" value={`Q${fmtNum(q.mean_base_quality)}`} sub="error-probability averaged" explain="phred" />
          </>
        )}
        <MetricTile
          label="Approximate depth"
          value={m.coverage_estimate ? `${fmtNum(m.coverage_estimate.estimated_depth)}×` : "—"}
          sub={m.coverage_estimate ? `for ${fmtBases(m.coverage_estimate.expected_genome_size_bp)} genome` : "provide a genome size to estimate"}
          explain="coverage"
        />
      </div>

      {q && (
        <Card>
          <CardHeader title="Reads above quality thresholds" description="Share of reads whose mean quality is at least each value — useful before choosing a filter." action={<Explain id="read_quality" />} />
          <CardBody className="grid grid-cols-3 gap-3 pt-3 sm:grid-cols-6">
            {q.reads_above_quality.map((r) => (
              <div key={r.threshold} className="rounded-lg bg-muted/60 p-3 text-center">
                <div className="text-xs text-muted-foreground">≥ Q{r.threshold}</div>
                <div className="text-lg font-semibold tabular-nums">{fmtNum(r.percent)}%</div>
                <div className="text-[11px] text-muted-foreground">{fmtInt(r.reads)} reads</div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <CrossCheckCard sampleId={sampleId} file={file} jobs={jobs} />
        {m.file.format === "fastq" ? <FastqcCard sampleId={sampleId} file={file} jobs={jobs} /> : <div />}
        {m.file.format === "fastq" && (technology !== "illumina" || latestJobFor(jobs, NANOPLOT_JOB, file.id, false)) && (
          <NanoplotCard sampleId={sampleId} file={file} jobs={jobs} arva={m} technology={technology} />
        )}
      </div>

      {fastqcJob && <FastqcDataSection key={fastqcJob.id} job={fastqcJob} technology={technology} prefix={prefix} />}
      {fastpJob && <FastpDataSection key={`${fastpJob.id}-${file.id}`} job={fastpJob} file={file} files={files} prefix={prefix} />}

      <div className="grid gap-6 lg:grid-cols-2">
        <LengthHistogramChart stats={m} prefix={prefix} />
        {q ? <ReadQualityChart quality={q} prefix={prefix} /> : <GcChart stats={m} prefix={prefix} />}
        {q && <QualityVsLengthChart stats={m} prefix={prefix} />}
        <CumulativeYieldChart stats={m} prefix={prefix} />
        {q && <GcChart stats={m} prefix={prefix} />}
        {q && <PerPositionQualityChart quality={q} prefix={prefix} />}
      </div>

      <p className="text-xs text-muted-foreground">
        All values are computed from every record in the file. ARVA does not apply pass/fail thresholds: suitable values depend on the
        technology, chemistry and intended analysis. Compare original and filtered reads in the Filtering tab.
      </p>
      {rawSignal}
      <FailedJobs jobs={failed} />
    </div>
  );
}

function FailedJobs({ jobs }: { jobs: AnalysisJobDetail[] }) {
  if (!jobs.length) return null;
  return (
    <Card className="border-danger/30">
      <CardHeader title="Recent failed analyses" description="Failures are recorded with the exact reason; no partial results are kept." />
      <CardBody className="space-y-2 pt-3">
        {jobs.map((j) => (
          <div key={j.id} className="rounded-lg bg-danger/5 px-3 py-2 text-sm">
            <div className="text-xs text-muted-foreground">{fmtDate(j.created_at)}</div>
            <div className="text-danger">{j.error_message}</div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

// --- History ----------------------------------------------------------------

function HistoryTab({ jobs, files, openJob }: { jobs: AnalysisJobDetail[]; files: RawFile[]; openJob: string | null }) {
  const t = useT();
  const [open, setOpen] = useState<string | null>(openJob);
  const byId = new Map(files.map((f) => [f.id, f]));
  if (!jobs.length) return <EmptyState title="No analyses have been run for this sample yet." />;
  return (
    <Card>
      <ul className="divide-y">
        {jobs.map((j) => {
          const expanded = open === j.id;
          const inputs = (j.input_raw_file_ids ?? []).map((id) => byId.get(id));
          return (
            <li key={j.id}>
              <button className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-muted/40" onClick={() => setOpen(expanded ? null : j.id)} aria-expanded={expanded}>
                <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition", expanded && "rotate-180")} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {jobLabel(j.job_type, t)} ·{" "}
                    {IMPORT_JOBS.has(j.job_type)
                      ? `${((j.parameters?.paths as string[] | undefined) ?? []).length} file(s) from ${String(j.parameters?.root ?? "")}`
                      : inputs.map((f) => f?.original_filename ?? "deleted file").join(", ")}
                    {j.parent_job_id && <span className="ml-2 text-xs font-normal text-muted-foreground">(started automatically)</span>}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {fmtDate(j.created_at)} · {j.tool_name} {j.tool_version} · {fmtDuration(j.duration_seconds)}
                  </div>
                </div>
                <JobStatusBadge status={j.status} />
              </button>
              {expanded && (
                <div className="space-y-4 px-5 pb-5 pl-12 text-sm">
                  <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
                    {[
                      ["Analysis job ID", <code className="text-xs">{j.id}</code>],
                      ["Tool", `${j.tool_name} ${j.tool_version}`],
                      ["Executable", j.tool_path ? <code className="text-xs">{j.tool_path}</code> : inProcessTool(j, t)],
                      ["Database", j.database_name ? `${j.database_name} ${j.database_version ?? ""}` : "None (no reference database used)"],
                      ["Queued", fmtDate(j.created_at)],
                      ["Started / finished", `${fmtDate(j.started_at)} → ${fmtDate(j.finished_at)}`],
                      ["Run time", fmtDuration(j.duration_seconds)],
                    ].map(([k, v], i) => (
                      <div key={i}>
                        <dt className="text-xs text-muted-foreground">{k}</dt>
                        <dd>{v}</dd>
                      </div>
                    ))}
                  </dl>
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">Inputs</div>
                    <ul className="space-y-0.5 text-xs">
                      {inputs.map((f, i) => (
                        <li key={i}>
                          {f ? (
                            <>
                              {f.original_filename} · {fmtBytes(f.size_bytes)} · <code>sha256:{f.checksum_sha256}</code>
                            </>
                          ) : (
                            "File record no longer available"
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">Parameters</div>
                    <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{JSON.stringify(j.parameters, null, 2)}</pre>
                  </div>
                  {j.commands?.length ? (
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Exact command{j.commands.length > 1 ? "s" : ""} executed</div>
                      {j.commands.map((c, i) => (
                        <pre key={i} className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 text-[11px]">
                          {c.map((a) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replace(/'/g, `'"'"'`)}'`)).join(" ")}
                        </pre>
                      ))}
                    </div>
                  ) : null}
                  {j.output_paths?.length ? (
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Outputs (relative to the ARVA data directory)</div>
                      <ul className="space-y-0.5 text-xs">
                        {j.output_paths.map((p) => (
                          <li key={p} className="flex flex-wrap items-center gap-2">
                            <code>{p}</code>
                            {!p.startsWith("processed/") && (
                              <a className="inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan" href={api.jobOutputUrl(j.id, basename(p), !p.endsWith(".html"))} target={p.endsWith(".html") ? "_blank" : undefined} rel="noreferrer">
                                {p.endsWith(".html") ? <ExternalLink className="h-3 w-3" /> : <Download className="h-3 w-3" />}
                                {p.endsWith(".html") ? "open" : "download"}
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {j.result_summary && j.job_type !== "sequence_stats" && (
                    <details>
                      <summary className="cursor-pointer text-xs text-muted-foreground">Structured result summary</summary>
                      <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-muted p-3 text-[11px]">{JSON.stringify(j.result_summary, null, 2)}</pre>
                    </details>
                  )}
                  {j.error_message && <ErrorNote error={j.error_message} />}
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">Log</div>
                    <pre className="max-h-72 overflow-auto rounded-lg bg-arva-navy p-3 text-[11px] leading-relaxed text-slate-200">{j.log_text || "(empty)"}</pre>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

// --- Filtering --------------------------------------------------------------

function FilteringTab({
  jobs,
  files,
  onNew,
  technology,
}: {
  jobs: AnalysisJobDetail[];
  files: RawFile[];
  onNew: () => void;
  technology: SequencingTechnology;
}) {
  const filterJobs = jobs.filter((j) => FILTER_JOBS.has(j.job_type));
  const derived = files.filter((f) => f.origin === "derived" && f.parent_file_id);
  const [selected, setSelected] = useState<string | null>(null);
  const current = derived.find((f) => f.id === selected) ?? derived[0];
  const results = useMemo(() => latestResults(jobs), [jobs]);
  const byId = new Map(files.map((f) => [f.id, f]));
  const pending = jobs.some((j) => j.job_type === "sequence_stats" && (j.status === "pending" || j.status === "running"));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Filtering creates new derived files and never changes the originals. Each run below lists the tool, version and exact settings;
          ARVA statistics are computed automatically for every output so you can compare before and after.
          {technology === "unknown" && " Set the sequencing technology in Metadata to get the right tool suggested."}
        </p>
        <Button onClick={onNew}>
          <Filter className="h-4 w-4" /> New filtering run
        </Button>
      </div>

      {filterJobs.length === 0 ? (
        <EmptyState icon={<Filter className="h-7 w-7" />} title="No filtering runs yet">
          Filtering is optional. Review the read statistics first, then decide whether it is needed. <Explain id="filtering" />
        </EmptyState>
      ) : (
        <Card>
          <CardHeader title="Filtering runs" action={<Explain id="filtering" />} />
          <CardBody className="pt-3">
            <ul className="divide-y">
              {filterJobs.map((j) => {
                const outs = files.filter((f) => f.produced_by_job_id === j.id);
                return (
                  <li key={j.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                    <div className="min-w-0 text-sm">
                      <div className="font-medium">
                        {j.tool_name} {j.tool_version}
                        <span className="ml-2 text-xs font-normal text-muted-foreground">{fmtDate(j.created_at)}</span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {(j.input_raw_file_ids ?? []).map((id) => byId.get(id)?.original_filename ?? "deleted file").join(" + ")}
                        {outs.length > 0 && <> → {outs.map((o) => o.original_filename).join(" + ")}</>}
                      </div>
                      {j.error_message && <div className="text-xs text-danger">{j.error_message}</div>}
                    </div>
                    <JobStatusBadge status={j.status} />
                  </li>
                );
              })}
            </ul>
          </CardBody>
        </Card>
      )}

      {current && (
        <>
          {derived.length > 1 && (
            <Field label="Compare filtered file with its original" className="max-w-xl">
              <Select value={current.id} onChange={(e) => setSelected(e.target.value)}>
                {derived.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.original_filename}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <BeforeAfter
            parent={byId.get(current.parent_file_id!)!}
            derived={current}
            parentStats={results.get(current.parent_file_id!)?.qc.metrics}
            derivedStats={results.get(current.id)?.qc.metrics}
            filterJob={jobs.find((j) => j.id === current.produced_by_job_id)}
            pending={pending}
          />
        </>
      )}
    </div>
  );
}
