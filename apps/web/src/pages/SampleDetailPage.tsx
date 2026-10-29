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
import { AnnotationDialog } from "@/components/annotation/AnnotationDialog";
import { AnnotationTab } from "@/components/annotation/AnnotationTab";
import { GenomicTab } from "@/components/genomic/GenomicTab";
import { MlstDialog } from "@/components/genomic/MlstDialog";
import { SpeciesDialog } from "@/components/genomic/SpeciesDialog";
import { AssemblyTab } from "@/components/assembly/AssemblyTab";
import { AssemblyDialog } from "@/components/assembly/AssemblyDialog";
import { PolishingDialog } from "@/components/assembly/PolishingDialog";
import { QuastDialog } from "@/components/assembly/QuastDialog";
import { AnalysisTimeline, JobStatusBadge, MetricTile, type Stage } from "@/components/domain/bits";
import { CancelJobButton, isActiveJob, isCancelling } from "@/components/domain/JobControls";
import { FileDropzone } from "@/components/domain/FileDropzone";
import { JobResources } from "@/components/domain/JobResources";
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
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtBp, fmtBytes, fmtDate, fmtDuration, fmtInt, fmtNum, fmtPct, formatLabel, shellJoin, technologyLabel } from "@/lib/format";
import { derivedDescription, fileValidation, jobError, seqstatsWarnings } from "@/lib/messages";
import { lineageOrder } from "@/lib/filters";
import { ANNOTATION_JOBS } from "@/lib/annotation";
import { MLST_JOB } from "@/lib/mlst";
import { SPECIES_JOB } from "@/lib/species";
import { ASSEMBLY_JOBS } from "@/lib/flye";
import { QUAST_JOB, jobRelativePath } from "@/lib/quast";
import { NANOPLOT_JOB } from "@/lib/nanoplot";
import { FASTQC_JOB, fastpJobFor } from "@/lib/qcData";
import { FILTER_JOBS, IMPORT_JOBS, RAW_SIGNAL_JOBS, hasReads, inProcessTool, jobLabel, latestJobFor, latestResults } from "@/lib/results";
import type { AnalysisJobDetail, HeaderSummary, RawFile, SequencingTechnology } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tab = "files" | "qc" | "filtering" | "assembly" | "annotation" | "genomic" | "history" | "metadata";

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
  const qcJobs = allJobs.filter(
    (j) =>
      !FILTER_JOBS.has(j.job_type) && !IMPORT_JOBS.has(j.job_type) && !RAW_SIGNAL_JOBS.has(j.job_type) && !ASSEMBLY_JOBS.has(j.job_type) && !ANNOTATION_JOBS.has(j.job_type) &&
      j.job_type !== MLST_JOB && j.job_type !== SPECIES_JOB,
  );
  const annotationJobs = allJobs.filter((j) => ANNOTATION_JOBS.has(j.job_type));
  const genomicJobs = allJobs.filter((j) => j.job_type === MLST_JOB || j.job_type === SPECIES_JOB);
  const filterJobs = allJobs.filter((j) => FILTER_JOBS.has(j.job_type));
  const assemblyJobs = allJobs.filter((j) => ASSEMBLY_JOBS.has(j.job_type));
  const signalJobs = allJobs.filter((j) => RAW_SIGNAL_JOBS.has(j.job_type));
  const importing = allJobs.some((j) => IMPORT_JOBS.has(j.job_type) && isActive(j));
  const readingSignal = signalJobs.some(isActive);
  const completed = qcJobs.filter((j) => j.status === "completed");
  const latestFailed = qcJobs[0]?.status === "failed";
  const [filterOpen, setFilterOpen] = useState(false);
  const [assemblyOpen, setAssemblyOpen] = useState(false);
  const [quastOpen, setQuastOpen] = useState(false);
  const [polishDraft, setPolishDraft] = useState<string | null | undefined>(undefined);
  const polishOpen = polishDraft !== undefined;
  const [annotateOpen, setAnnotateOpen] = useState(false);
  const [mlstOpen, setMlstOpen] = useState(false);
  const [speciesOpen, setSpeciesOpen] = useState(false);
  const assemblies = useQuery({
    queryKey: ["assemblies", sampleId],
    queryFn: () => api.assemblies(sampleId),
    enabled: quastOpen || polishOpen || annotateOpen || mlstOpen || speciesOpen,
  });
  const queryClient = useQueryClient();
  const finishedCount = allJobs.filter((j) => j.status === "completed" || j.status === "failed" || j.status === "cancelled").length;
  useEffect(() => {
    // Jobs can create derived files and cross-check data; refresh them whenever a job finishes.
    queryClient.invalidateQueries({ queryKey: ["files", sampleId] });
    queryClient.invalidateQueries({ queryKey: ["crosscheck"] });
    queryClient.invalidateQueries({ queryKey: ["assemblies", sampleId] });
    queryClient.invalidateQueries({ queryKey: ["annotations", sampleId] });
    queryClient.invalidateQueries({ queryKey: ["mlst", sampleId] });
    queryClient.invalidateQueries({ queryKey: ["species", sampleId] });
  }, [finishedCount, sampleId, queryClient]);

  const stages: Stage[] = [
    {
      key: "raw",
      label: t("sample.files"),
      state: importing || readingSignal ? "running" : files.data?.length ? "done" : "ready",
      detail: importing ? t("timeline.importing") : readingSignal ? t("pod5.reading") : files.data?.length ? t("timeline.files", { count: files.data.length }) : t("timeline.importReads"),
    },
    {
      key: "qc",
      label: t("timeline.readQc"),
      state: qcJobs.some(isActive) ? "running" : latestFailed ? "failed" : completed.length ? "done" : "ready",
      detail: qcJobs.some(isActive) ? t("timeline.computing") : completed.length ? t("assembly.timelineRuns", { count: completed.length }) : t("assembly.timelineNotRun"),
    },
    {
      key: "filtering",
      label: t("sample.filtering"),
      state: filterJobs.some(isActive) ? "running" : filterJobs[0]?.status === "failed" ? "failed" : filterJobs.some((j) => j.status === "completed") ? "done" : "ready",
      detail: filterJobs.some(isActive)
        ? t("timeline.running")
        : filterJobs.length
          ? t("assembly.timelineRuns", { count: filterJobs.filter((j) => j.status === "completed").length })
          : t("timeline.optional"),
    },
    {
      key: "assembly",
      label: t("sample.assembly"),
      state: assemblyJobs.some(isActive) ? "running" : assemblyJobs[0]?.status === "failed" ? "failed" : assemblyJobs.some((j) => j.status === "completed") ? "done" : "ready",
      detail: assemblyJobs.some(isActive)
        ? t("assembly.timelineRunning")
        : assemblyJobs.some((j) => j.status === "completed")
          ? t("assembly.timelineRuns", { count: assemblyJobs.filter((j) => j.status === "completed" && j.job_type !== QUAST_JOB).length }) +
            (assemblyJobs.some((j) => j.status === "completed" && j.job_type === QUAST_JOB)
              ? ` · ${t("quast.timelineEvaluations", { count: assemblyJobs.filter((j) => j.status === "completed" && j.job_type === QUAST_JOB).length })}`
              : "")
          : t("assembly.timelineNotRun"),
    },
    { key: "polishing", label: t("timeline.polishing"), state: "planned", phase: 3 },
    {
      key: "annotation",
      label: t("sample.annotation"),
      state: annotationJobs.some(isActive) ? "running" : annotationJobs[0]?.status === "failed" ? "failed" : annotationJobs.some((j) => j.status === "completed") ? "done" : "ready",
      detail: annotationJobs.some(isActive)
        ? t("annotation.timelineRunning")
        : annotationJobs.some((j) => j.status === "completed")
          ? t("annotation.timelineRuns", { count: annotationJobs.filter((j) => j.status === "completed").length })
          : t("annotation.timelineNotRun"),
    },
    {
      key: "genomic",
      label: t("sample.genomic"),
      state: genomicJobs.some(isActive) ? "running" : genomicJobs[0]?.status === "failed" ? "failed" : genomicJobs.some((j) => j.status === "completed") ? "done" : "ready",
      detail: genomicJobs.some(isActive)
        ? t("mlst.timelineRunning")
        : genomicJobs.some((j) => j.status === "completed")
          ? t("annotation.timelineRuns", { count: genomicJobs.filter((j) => j.status === "completed").length })
          : t("annotation.timelineNotRun"),
    },
  ];

  if (sample.isLoading) return <Skeleton className="h-40" />;
  if (sample.error || !sample.data) return <ErrorNote error={sample.error ?? t("sample.notFound")} />;
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
            <Badge tone={s.sequencing_technology === "unknown" ? "neutral" : "blue"}>{technologyLabel(s.sequencing_technology)}</Badge>
            <TechnologySuggestion sample={s} summary={headerSummary.data} />
            {s.host && <span>{t("sample.host", { host: s.host })}</span>}
            {s.geographic_origin && <span>· {s.geographic_origin}</span>}
          </span>
        }
        actions={
          <ReportMenu
            sampleId={s.id}
            disabled={
              !completed.length &&
              !signalJobs.some((j) => j.status === "completed") &&
              !assemblyJobs.some((j) => j.status === "completed") &&
              !annotationJobs.some((j) => j.status === "completed")
            }
          />
        }
      />

      <Card className="px-4 pb-2 pt-5">
        <AnalysisTimeline
          stages={stages}
          selected={tab === "files" ? "raw" : tab === "qc" || tab === "filtering" || tab === "assembly" || tab === "annotation" || tab === "genomic" ? tab : undefined}
          onSelect={(k) => setTab(k === "raw" ? "files" : k === "filtering" || k === "assembly" || k === "annotation" || k === "genomic" ? k : "qc")}
        />
      </Card>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        items={[
          { value: "files", label: t("sample.files") },
          { value: "qc", label: t("sample.qc") },
          { value: "filtering", label: `${t("sample.filtering")}${filterJobs.length ? ` (${filterJobs.length})` : ""}` },
          { value: "assembly", label: `${t("sample.assembly")}${assemblyJobs.length ? ` (${assemblyJobs.length})` : ""}` },
          { value: "annotation", label: `${t("sample.annotation")}${annotationJobs.length ? ` (${annotationJobs.length})` : ""}` },
          { value: "genomic", label: `${t("sample.genomic")}${genomicJobs.length ? ` (${genomicJobs.length})` : ""}` },
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
      {tab === "assembly" && (
        <AssemblyTab
          sampleId={s.id}
          jobs={allJobs}
          files={files.data ?? []}
          onNew={() => setAssemblyOpen(true)}
          onEvaluate={() => setQuastOpen(true)}
          onPolish={(draftId) => setPolishDraft(draftId ?? null)}
        />
      )}
      {tab === "annotation" && <AnnotationTab sampleId={s.id} jobs={allJobs} onNew={() => setAnnotateOpen(true)} />}
      {tab === "genomic" && <GenomicTab sampleId={s.id} jobs={allJobs} onMlst={() => setMlstOpen(true)} onSpecies={() => setSpeciesOpen(true)} />}
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
        jobs={allJobs}
        technology={s.sequencing_technology}
        onStarted={() => setTab("filtering")}
      />
      <AssemblyDialog
        open={assemblyOpen}
        onOpenChange={setAssemblyOpen}
        sampleId={s.id}
        files={files.data ?? []}
        jobs={allJobs}
        technology={s.sequencing_technology}
        onStarted={() => setTab("assembly")}
      />
      {polishOpen && assemblies.data && (
        <PolishingDialog
          open={polishOpen}
          onOpenChange={(o) => !o && setPolishDraft(undefined)}
          sampleId={s.id}
          technology={s.sequencing_technology}
          assemblies={assemblies.data}
          files={files.data ?? []}
          jobs={allJobs}
          draftId={polishDraft}
        />
      )}
      {quastOpen && assemblies.data && (
        <QuastDialog open={quastOpen} onOpenChange={setQuastOpen} sampleId={s.id} assemblies={assemblies.data} files={files.data ?? []} />
      )}
      {annotateOpen && assemblies.data && (
        <AnnotationDialog open={annotateOpen} onOpenChange={setAnnotateOpen} sampleId={s.id} assemblies={assemblies.data} />
      )}
      {mlstOpen && assemblies.data && <MlstDialog open={mlstOpen} onOpenChange={setMlstOpen} sampleId={s.id} assemblies={assemblies.data} />}
      {speciesOpen && assemblies.data && <SpeciesDialog open={speciesOpen} onOpenChange={setSpeciesOpen} sampleId={s.id} assemblies={assemblies.data} />}
    </div>
  );
}

const REPORT_FORMATS: { f: "html" | "csv" | "json"; label: TranslationKey; sub: TranslationKey }[] = [
  { f: "html", label: "report.html", sub: "report.htmlHint" },
  { f: "csv", label: "report.csv", sub: "report.csvHint" },
  { f: "json", label: "report.json", sub: "report.jsonHint" },
];

function ReportMenu({ sampleId, disabled }: { sampleId: string; disabled: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="relative" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <Button variant="outline" onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={disabled} title={disabled ? t("report.disabled") : undefined}>
        <FileText className="h-4 w-4" /> {t("sample.report")} <ChevronDown className="h-3.5 w-3.5" />
      </Button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-56 rounded-xl border bg-surface py-1 text-sm shadow-lg">
          {REPORT_FORMATS.map((o) => (
            <a key={o.f} href={api.reportUrl(sampleId, o.f)} download className="block px-3 py-2 hover:bg-muted" onClick={() => setOpen(false)}>
              <div className="flex items-center gap-2">
                <Download className="h-3.5 w-3.5" />
                {t(o.label)}
              </div>
              <div className="pl-5 text-xs text-muted-foreground">{t(o.sub)}</div>
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
          <CardHeader title={t("files.import")} description={t("files.importHint")} action={<Explain id="fastq" />} />
          <CardBody>
            <FileDropzone sampleId={sampleId} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("files.registered", { count: files.length })} description={t("files.registeredHint")} action={<Explain id="integrity" />} />
          <CardBody className="pt-3">
            {loading ? (
              <Skeleton className="h-16" />
            ) : files.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("files.none")}</p>
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
                      aria-label={t("files.include", { name: f.original_filename })}
                      title={f.file_format === "pod5" ? t("pod5.notAnalysable") : undefined}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium">{f.original_filename}</span>
                        {f.file_format === "pod5" ? (
                          <Badge tone="blue">{t("pod5.badge")}</Badge>
                        ) : (
                          <Badge tone={f.file_format === "unknown" ? "danger" : "teal"}>{formatLabel(f.file_format)}</Badge>
                        )}
                        {f.read_mate && <Badge tone="blue">{f.read_mate}</Badge>}
                        {f.origin === "derived" && <Badge tone="neutral">{t("files.derived")}</Badge>}
                        {!f.is_valid && f.file_format !== "unknown" && (
                          <Badge tone="warning">
                            <AlertTriangle className="h-3 w-3" /> {t("files.invalid")}
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {fmtBytes(f.size_bytes)} · {fmtDate(f.uploaded_at)} · SHA-256 <Checksum value={f.checksum_sha256} />
                      </div>
                      {f.description && <div className="mt-0.5 text-xs text-foreground/80">{derivedDescription(t, f.description)}</div>}
                      <div className={cn("mt-0.5 text-xs", f.is_valid ? "text-muted-foreground" : "text-amber-700 dark:text-warning")}>{fileValidation(t, f)}</div>
                    </div>
                    <a href={api.fileDownloadUrl(f.id)} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted" aria-label={t("files.download", { name: f.original_filename })}>
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
        <CardHeader title={t("sample.runStats")} description={t("stats.runHint")} />
        <CardBody className="space-y-4">
          <Field label={t("stats.genomeSize")} hint={t("stats.genomeSizeHint")}>
            <Input inputMode="decimal" placeholder={t("stats.genomeSizePlaceholder")} value={genomeMbp} onChange={(e) => setGenomeMbp(e.target.value)} aria-invalid={!genomeValid} />
          </Field>
          <Field label={t("stats.bins")}>
            <Select value={bins} onChange={(e) => setBins(e.target.value)}>
              {[25, 50, 100, 200].map((b) => (
                <option key={b}>{b}</option>
              ))}
            </Select>
          </Field>
          <div className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">
            {t("stats.tool")} <b>arva-core.seqstats</b>. {t("stats.recorded")}
          </div>
          <ErrorNote error={run.error} />
          <Button className="w-full" disabled={!chosen.size || !genomeValid || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {t("stats.analyse", { count: chosen.size })}
          </Button>
        </CardBody>
      </Card>

      <Card className="h-fit xl:col-start-3">
        <CardHeader title={t("qcTools.title")} description={t("qcTools.hint")} />
        <CardBody className="space-y-3">
          {(
            [
              { id: "seqkit", label: "qcTools.seqkit", explain: "crosscheck" },
              { id: "fastqc", label: "qcTools.fastqc", explain: "fastqc_flags" },
            ] as const
          ).map((tool) => {
            const info = toolStatus(tool.id);
            const ok = info?.status === "available";
            return (
              <div key={tool.id} className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-sm">
                    {t(tool.label)} <Explain id={tool.explain} compact />
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {info ? (ok ? `${info.name} ${info.version}` : t("qcTools.notInstalled", { tool: info.name })) : t("qcTools.checking")}
                  </div>
                </div>
                <Button size="sm" variant="outline" disabled={!ok || !chosen.size || runTool.isPending} onClick={() => runTool.mutate(tool.id)}>
                  <Play className="h-3.5 w-3.5" /> {t("qcTools.run")}
                </Button>
              </div>
            );
          })}
          <ErrorNote error={runTool.error} />
          <div className="border-t pt-3">
            <Button variant="outline" className="w-full" disabled={!hasFastq} onClick={onFilter}>
              <Filter className="h-4 w-4" /> {t("qcTools.filter")}
            </Button>
            <p className="mt-1.5 text-xs text-muted-foreground">{t("qcTools.filterHint")}</p>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function Checksum({ value }: { value: string | null }) {
  const t = useT();
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
      {copied && <span className="text-success">{t("files.copied")}</span>}
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
  const t = useT();
  const results = useMemo(() => latestResults(jobs), [jobs]);
  const withResults = files.filter((f) => results.has(f.id));
  const [fileId, setFileId] = useState<string | null>(null);
  const currentId = fileId && results.has(fileId) ? fileId : withResults[0]?.id;
  const current = currentId ? results.get(currentId) : undefined;
  const failed = jobs
    .filter((j) => j.status === "failed" && !IMPORT_JOBS.has(j.job_type) && !RAW_SIGNAL_JOBS.has(j.job_type) && !ASSEMBLY_JOBS.has(j.job_type))
    .slice(0, 3);
  const rawSignal = <RawSignalSection sampleId={sampleId} files={files} jobs={jobs} />;
  const overview = <SequencingOverview files={files} jobs={jobs} prefix={`ARVA_${sampleCode}`.replace(/[^A-Za-z0-9._-]+/g, "_")} />;

  if (!current) {
    return (
      <div className="space-y-4">
        {overview}
        {activeCount > 0 ? (
          <EmptyState icon={<Loader2 className="h-7 w-7 animate-spin text-arva-teal" />} title={t("stats.computing", { count: activeCount })}>
            {t("stats.appearHere")}
          </EmptyState>
        ) : (
          <EmptyState title={t("stats.none")}>
            <Button onClick={onGoFiles}>{t("stats.goFiles")}</Button>
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
          <Field label={t("stats.file")} className="w-full max-w-md">
            <Select value={currentId} onChange={(e) => setFileId(e.target.value)}>
              {withResults.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.original_filename}
                  {f.read_mate ? ` (${f.read_mate})` : ""}
                  {f.origin === "derived" ? ` · ${t("stats.derivedSuffix")}` : ""}
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <div className="text-sm">
            <span className="text-muted-foreground">{t("stats.file")} </span>
            <b>{file.original_filename}</b>
          </div>
        )}
        <div className="text-xs text-muted-foreground">
          {current.job.tool_name} {current.job.tool_version} · {fmtDate(current.job.finished_at)} · {fmtDuration(current.job.duration_seconds)}
          {activeCount > 0 && (
            <span className="ml-2 inline-flex items-center gap-1 text-arva-royal dark:text-arva-cyan">
              <Loader2 className="h-3 w-3 animate-spin" /> {t("stats.running", { count: activeCount })}
            </span>
          )}
        </div>
      </div>

      {m.warnings.length > 0 && (
        <div className="rounded-xl border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
          <div className="mb-1 flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4 text-warning" /> {t("stats.warnings")}
          </div>
          <ul className="list-disc pl-6 text-muted-foreground">
            {seqstatsWarnings(t, m).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <MetricTile label={m.file.format === "fasta" ? t("stats.sequences") : t("stats.reads")} value={fmtInt(m.read_count)} explain="read_count" />
        <MetricTile label={t("stats.totalBases")} value={fmtBases(m.total_bases)} sub={fmtBp(m.total_bases)} explain="read_count" />
        <MetricTile
          label={t("stats.meanMedianLength")}
          value={fmtBp(m.mean_length)}
          sub={t("stats.lengthSub", { median: fmtInt(m.median_length), min: fmtInt(m.min_length), max: fmtInt(m.max_length) })}
          explain="length_distribution"
        />
        <MetricTile label="N50" value={fmtBp(m.n50)} sub={`L50 ${fmtInt(m.l50)} · N90 ${fmtBp(m.n90)}`} explain="n50" />
        <MetricTile label={t("stats.gc")} value={fmtPct(m.gc_percent, 2)} sub={t("stats.ambiguous", { percent: fmtPct(m.ambiguous_percent, 3) })} explain="gc_content" />
        {q && (
          <>
            <MetricTile
              label={t("stats.meanReadQuality")}
              value={`Q${fmtNum(q.mean_read_quality)}`}
              sub={t("stats.qualitySub", { median: fmtNum(q.median_read_quality), min: q.min_base_quality, max: q.max_base_quality })}
              explain="read_quality"
            />
            <MetricTile label={t("stats.basesQ", { q: 20 })} value={fmtPct(q.q20_bases_percent)} explain="q20_q30" />
            <MetricTile label={t("stats.basesQ", { q: 30 })} value={fmtPct(q.q30_bases_percent)} explain="q20_q30" />
            <MetricTile label={t("stats.meanBaseQuality")} value={`Q${fmtNum(q.mean_base_quality)}`} sub={t("stats.meanBaseQualitySub")} explain="phred" />
          </>
        )}
        <MetricTile
          label={t("stats.depth")}
          value={m.coverage_estimate ? `${fmtNum(m.coverage_estimate.estimated_depth)}×` : "—"}
          sub={m.coverage_estimate ? t("stats.depthFor", { size: fmtBases(m.coverage_estimate.expected_genome_size_bp) }) : t("stats.depthNone")}
          explain="coverage"
        />
      </div>

      {q && (
        <Card>
          <CardHeader title={t("stats.aboveQ")} description={t("stats.aboveQHint")} action={<Explain id="read_quality" />} />
          <CardBody className="grid grid-cols-3 gap-3 pt-3 sm:grid-cols-6">
            {q.reads_above_quality.map((r) => (
              <div key={r.threshold} className="rounded-lg bg-muted/60 p-3 text-center">
                <div className="text-xs text-muted-foreground">≥ Q{r.threshold}</div>
                <div className="text-lg font-semibold tabular-nums">{fmtPct(r.percent)}</div>
                <div className="text-[11px] text-muted-foreground">{t("stats.readCount", { count: r.reads })}</div>
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
        {t("stats.footnote")}
      </p>
      {rawSignal}
      <FailedJobs jobs={failed} />
    </div>
  );
}

function FailedJobs({ jobs }: { jobs: AnalysisJobDetail[] }) {
  const t = useT();
  if (!jobs.length) return null;
  return (
    <Card className="border-danger/30">
      <CardHeader title={t("failed.title")} description={t("failed.hint")} />
      <CardBody className="space-y-2 pt-3">
        {jobs.map((j) => (
          <div key={j.id} className="rounded-lg bg-danger/5 px-3 py-2 text-sm">
            <div className="text-xs text-muted-foreground">{fmtDate(j.created_at)}</div>
            <div className="text-danger">{jobError(t, j)}</div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

// --- History ----------------------------------------------------------------

/** The reference database a job read: name and version, how the version was known, checksum and folder. */
function JobDatabase({ job }: { job: AnalysisJobDetail }) {
  const t = useT();
  const source = job.database_version_source
    ? t(`history.dbVersionSource.${job.database_version_source}` as "history.dbVersionSource.file")
    : null;
  return (
    <span className="block">
      {job.database_name} {job.database_version ?? ""}
      {source && <span className="block text-xs text-muted-foreground">{source}</span>}
      <span className="block text-xs text-muted-foreground">
        {job.database_checksum ? <code className="break-all">{job.database_checksum.slice(0, 23)}…</code> : t("history.dbNoChecksum")}
      </span>
      {job.database_path && <code className="block break-all text-xs text-muted-foreground">{job.database_path}</code>}
    </span>
  );
}

function HistoryTab({ jobs, files, openJob }: { jobs: AnalysisJobDetail[]; files: RawFile[]; openJob: string | null }) {
  const t = useT();
  const [open, setOpen] = useState<string | null>(openJob);
  const byId = new Map(files.map((f) => [f.id, f]));
  if (!jobs.length) return <EmptyState title={t("history.empty")} />;
  return (
    <Card>
      <ul className="divide-y">
        {jobs.map((j) => {
          const expanded = open === j.id;
          const inputs = (j.input_raw_file_ids ?? []).map((id) => byId.get(id));
          return (
            <li key={j.id}>
              <div className="flex items-center gap-2 hover:bg-muted/40">
                <button className="flex min-w-0 flex-1 items-center gap-3 px-5 py-3 text-left" onClick={() => setOpen(expanded ? null : j.id)} aria-expanded={expanded}>
                  <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition", expanded && "rotate-180")} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {jobLabel(j.job_type, t)} ·{" "}
                      {IMPORT_JOBS.has(j.job_type)
                        ? t("history.importFrom", { count: ((j.parameters?.paths as string[] | undefined) ?? []).length, root: String(j.parameters?.root ?? "") })
                        : inputs.map((f) => f?.original_filename ?? t("history.deletedFile")).join(", ")}
                      {j.parent_job_id && <span className="ml-2 text-xs font-normal text-muted-foreground">{t("history.automatic")}</span>}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {fmtDate(j.created_at)} · {j.tool_name} {j.tool_version} · {fmtDuration(j.duration_seconds)}
                    </div>
                  </div>
                  <JobStatusBadge status={j.status} cancelling={isCancelling(j)} />
                </button>
                {isActiveJob(j) && (
                  <div className="shrink-0 pr-5">
                    <CancelJobButton job={j} />
                  </div>
                )}
              </div>
              {expanded && (
                <div className="space-y-4 px-5 pb-5 pl-12 text-sm">
                  <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
                    {[
                      [t("history.jobId"), <code className="text-xs">{j.id}</code>],
                      [t("history.tool"), `${j.tool_name} ${j.tool_version}`],
                      [t("tools.executable"), j.tool_path ? <code className="text-xs">{j.tool_path}</code> : inProcessTool(j, t)],
                      [t("history.database"), j.database_name ? <JobDatabase job={j} /> : t("history.noDatabase")],
                      [t("history.queued"), fmtDate(j.created_at)],
                      [t("history.startedFinished"), `${fmtDate(j.started_at)} → ${fmtDate(j.finished_at)}`],
                      [t("history.runTime"), fmtDuration(j.duration_seconds)],
                      ...(j.cancel_requested_at ? [[t("history.cancelRequested"), fmtDate(j.cancel_requested_at)]] : []),
                    ].map(([k, v], i) => (
                      <div key={i}>
                        <dt className="text-xs text-muted-foreground">{k}</dt>
                        <dd>{v}</dd>
                      </div>
                    ))}
                  </dl>
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">{t("history.inputs")}</div>
                    <ul className="space-y-0.5 text-xs">
                      {inputs.map((f, i) => (
                        <li key={i}>
                          {f ? (
                            <>
                              {f.original_filename} · {fmtBytes(f.size_bytes)} · <code>sha256:{f.checksum_sha256}</code>
                            </>
                          ) : (
                            t("history.fileGone")
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <JobResources job={j} />
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">{t("history.parameters")}</div>
                    <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">{JSON.stringify(j.parameters, null, 2)}</pre>
                  </div>
                  {j.commands?.length ? (
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">{t("history.commands", { count: j.commands.length })}</div>
                      {j.commands.map((c, i) => (
                        <pre key={i} className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 text-[11px]">
                          {shellJoin(c)}
                        </pre>
                      ))}
                    </div>
                  ) : null}
                  {j.output_paths?.length ? (
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">{t("history.outputs")}</div>
                      <ul className="space-y-0.5 text-xs">
                        {j.output_paths.map((p) => (
                          <li key={p} className="flex flex-wrap items-center gap-2">
                            <code>{p}</code>
                            {!p.startsWith("processed/") && (
                              <a className="inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan" href={api.jobOutputUrl(j.id, jobRelativePath(j.id, p), !p.endsWith(".html"))} target={p.endsWith(".html") ? "_blank" : undefined} rel="noreferrer">
                                {p.endsWith(".html") ? <ExternalLink className="h-3 w-3" /> : <Download className="h-3 w-3" />}
                                {p.endsWith(".html") ? t("history.open") : t("history.download")}
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {j.result_summary && j.job_type !== "sequence_stats" && (
                    <details>
                      <summary className="cursor-pointer text-xs text-muted-foreground">{t("history.summary")}</summary>
                      <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-muted p-3 text-[11px]">{JSON.stringify(j.result_summary, null, 2)}</pre>
                    </details>
                  )}
                  {j.error_message && <ErrorNote error={jobError(t, j)} />}
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">{t("history.log")}</div>
                    <pre className="max-h-72 overflow-auto rounded-lg bg-arva-navy p-3 text-[11px] leading-relaxed text-slate-200">{j.log_text || t("history.logEmpty")}</pre>
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
  const t = useT();
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
          {t("filtering.intro")}
          {technology === "unknown" && ` ${t("filtering.setTechnology")}`}
        </p>
        <Button onClick={onNew}>
          <Filter className="h-4 w-4" /> {t("filtering.new")}
        </Button>
      </div>

      {filterJobs.length === 0 ? (
        <EmptyState icon={<Filter className="h-7 w-7" />} title={t("filtering.none")}>
          {t("filtering.noneHint")} <Explain id="filtering" />
        </EmptyState>
      ) : (
        <Card>
          <CardHeader title={t("filtering.runs")} action={<Explain id="filtering" />} />
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
                        {(j.input_raw_file_ids ?? []).map((id) => byId.get(id)?.original_filename ?? t("history.deletedFile")).join(" + ")}
                        {outs.length > 0 && <> → {outs.map((o) => o.original_filename).join(" + ")}</>}
                      </div>
                      {j.error_message && <div className="text-xs text-danger">{jobError(t, j)}</div>}
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
            <Field label={t("filtering.compare")} className="max-w-xl">
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
