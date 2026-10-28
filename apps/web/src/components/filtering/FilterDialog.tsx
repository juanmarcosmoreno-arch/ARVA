import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Segmented } from "@/components/charts/ChartCard";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import {
  ADAPTER_PATTERN,
  FASTP_DEFAULTS,
  FILTLONG_EMPTY,
  TRIM_FRONT_MAX,
  TRIM_TAIL_MAX,
  adapterPeaks,
  describeFastp,
  describeFiltlong,
  expectedKeptBases,
  fastpProblems,
  fastpRequestParams,
  filtlongHasThreshold,
  filtlongTarget,
  identityToPhred,
  missedAdapter,
  pairedAdapter,
  storedGenomeSize,
  targetBasesForCoverage,
  type AdapterPeak,
} from "@/lib/filters";
import { fmtBases, fmtInt, fmtNum } from "@/lib/format";
import { FASTP_JOB, FASTQC_JOB } from "@/lib/qcData";
import { latestJobFor, latestResults } from "@/lib/results";
import type { AnalysisJobDetail, FastpParams, FiltlongParams, RawFile, SequencingTechnology, Tool } from "@/lib/types";

type FilterTool = "fastp" | "filtlong";
type T = ReturnType<typeof useT>;

const fastqFiles = (files: RawFile[]) =>
  files.filter((f) => (f.file_format === "fastq" || f.file_format === "fastq_gz") && f.is_valid);

const label = (f: RawFile, t: T) => (f.origin === "derived" ? t("filter.derivedFile", { name: f.original_filename }) : f.original_filename);

export function FilterDialog({
  open,
  onOpenChange,
  sampleId,
  files,
  jobs,
  technology,
  onStarted,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  files: RawFile[];
  jobs: AnalysisJobDetail[];
  technology: SequencingTechnology;
  onStarted?: () => void;
}) {
  const t = useT();
  const longReads = technology === "nanopore" || technology === "pacbio";
  const [tool, setTool] = useState<FilterTool>(longReads ? "filtlong" : "fastp");
  useEffect(() => {
    if (open) setTool(longReads ? "filtlong" : "fastp");
  }, [open, longReads]);
  const candidates = fastqFiles(files);
  const done = () => {
    onOpenChange(false);
    onStarted?.();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("filter.title")} description={t("filter.description")} className="max-w-2xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Segmented
          label={t("filter.toolLabel")}
          value={tool}
          onChange={setTool}
          options={[
            { value: "fastp", label: t("filter.tool.fastp") },
            { value: "filtlong", label: t("filter.tool.filtlong") },
          ]}
        />
        <Explain id={tool} />
      </div>
      {candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("filter.noFiles")}</p>
      ) : tool === "fastp" ? (
        <FastpForm sampleId={sampleId} files={candidates} jobs={jobs} warnLong={longReads} onDone={done} />
      ) : (
        <FiltlongForm sampleId={sampleId} files={candidates} jobs={jobs} warnShort={technology === "illumina"} onDone={done} />
      )}
    </Dialog>
  );
}

function ToolLine({ tool }: { tool: Tool | undefined }) {
  const t = useT();
  if (!tool) return null;
  if (tool.status !== "available")
    return (
      <div className="flex gap-2 rounded-lg border border-danger/30 bg-danger/5 p-3 text-xs">
        <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
        <span>
          {t("filter.unavailable", { name: tool.name, status: tool.status.replace("_", " ") })} <code>{tool.install.conda ?? tool.install.apt}</code>
        </span>
      </div>
    );
  return (
    <p className="text-xs text-muted-foreground">
      {tool.name} {tool.version} · {tool.license}
      {!tool.version_validated && <span className="text-amber-700 dark:text-warning"> · {t("filter.notValidated")}</span>}
    </p>
  );
}

function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
      <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
      <span>{children}</span>
    </div>
  );
}

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" className="h-4 w-4 shrink-0 accent-[#00B4A6]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

function Num({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  hint,
  disabled,
  nullable = false,
  placeholder,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: ReactNode;
  disabled?: boolean;
  nullable?: boolean;
  placeholder?: string;
}) {
  const t = useT();
  return (
    <Field label={label} hint={hint}>
      <Input
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        placeholder={placeholder ?? (nullable ? t("filter.notSet") : undefined)}
        value={value ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") onChange(nullable ? null : (min ?? 0));
          else onChange(Number(raw));
        }}
      />
    </Field>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 rounded-xl border p-4">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</legend>
      <div className="space-y-3">{children}</div>
    </fieldset>
  );
}

function Summary({ items }: { items: string[] }) {
  const t = useT();
  return (
    <div className="rounded-xl bg-muted/60 p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold">
        <Info className="h-3.5 w-3.5 text-arva-teal" /> {t("filter.summaryTitle")}
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-sm">
        {items.map((i) => (
          <li key={i} className="break-words">
            {i}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Every value sent to ARVA for this run, so nothing passed to the tool is hidden. */
function Parameters({ values }: { values: Record<string, unknown> }) {
  const t = useT();
  return (
    <details className="rounded-xl border p-3 text-xs">
      <summary className="cursor-pointer font-medium text-muted-foreground">{t("filter.parameters")}</summary>
      <dl className="mt-2 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-0.5 font-mono">
        {Object.entries(values).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="truncate text-muted-foreground">{k}</dt>
            <dd className="break-all">{v === null || v === undefined ? t("filter.notSet") : String(v)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function Confirm({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  const t = useT();
  return (
    <Toggle checked={checked} onChange={onChange}>
      <span className="text-xs">{t("filter.reviewed")}</span>
    </Toggle>
  );
}

function useStart(sampleId: string, onDone: () => void) {
  const qc = useQueryClient();
  return {
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs", sampleId] });
      qc.invalidateQueries({ queryKey: ["files", sampleId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onDone();
    },
  };
}

/** Warns when FastQC saw an adapter in this file that the previous fastp run on it did not trim. */
function MissedAdapterNote({ jobs, file }: { jobs: AnalysisJobDetail[]; file: RawFile }) {
  const t = useT();
  const fastqc = latestJobFor(jobs, FASTQC_JOB, file.id);
  const stored = (fastqc?.result_summary as { data_summary?: { adapter_content: { adapters: AdapterPeak[] } | null } } | null)?.data_summary;
  const legacy = useQuery({
    queryKey: ["fastqc-data", fastqc?.id],
    queryFn: () => api.fastqcData(fastqc!.id),
    enabled: !!fastqc && stored === undefined,
    staleTime: Infinity,
  });
  const peaks = stored ? (stored.adapter_content?.adapters ?? null) : legacy.data ? adapterPeaks(legacy.data) : null;
  const missed = missedAdapter(peaks, latestJobFor(jobs, FASTP_JOB, file.id));
  if (!missed) return null;
  return <Warning>{t("filter.fastp.missedAdapter", { adapter: missed.name, percent: fmtNum(missed.max_percent, 1), file: file.original_filename })}</Warning>;
}

function AdapterInput({ label, value, onChange, placeholder }: { label: string; value: string | null; onChange: (v: string | null) => void; placeholder: string }) {
  const t = useT();
  const invalid = !!value && !ADAPTER_PATTERN.test(value);
  return (
    <Field label={label} hint={invalid ? <span className="text-danger">{t("filter.fastp.problem.adapter")}</span> : undefined}>
      <Input
        value={value ?? ""}
        placeholder={placeholder}
        spellCheck={false}
        autoCapitalize="characters"
        className="font-mono"
        aria-invalid={invalid}
        onChange={(e) => onChange(e.target.value.toUpperCase().replace(/\s+/g, "") || null)}
      />
    </Field>
  );
}

function FastpForm({ sampleId, files, jobs, warnLong, onDone }: { sampleId: string; files: RawFile[]; jobs: AnalysisJobDetail[]; warnLong: boolean; onDone: () => void }) {
  const t = useT();
  const tool = useTool("fastp");
  const defaultR1 = files.find((f) => f.read_mate === "R1") ?? files[0];
  const defaultR2 = useMemo(
    () => (defaultR1?.read_mate === "R1" ? files.find((f) => f.read_mate === "R2" && f.origin === defaultR1.origin && f.parent_file_id === null) : undefined),
    [files, defaultR1],
  );
  const [r1, setR1] = useState(defaultR1?.id ?? "");
  const [r2, setR2] = useState(defaultR2?.id ?? "");
  const [p, setP] = useState<FastpParams>(FASTP_DEFAULTS);
  const [ok, setOk] = useState(false);
  const set = <K extends keyof FastpParams>(k: K) => (v: FastpParams[K]) => setP((x) => ({ ...x, [k]: v }));
  const paired = Boolean(r2);
  const params = fastpRequestParams(p, paired);
  const problems = fastpProblems(params);
  const { onSuccess } = useStart(sampleId, onDone);
  const run = useMutation({
    mutationFn: () => api.runFastp(sampleId, { read1_file_id: r1, read2_file_id: r2 || null, params }),
    onSuccess,
  });
  const inputs = [r1, r2].map((id) => files.find((f) => f.id === id)).filter((f): f is RawFile => !!f);
  const adapterPlaceholder = (mate: 1 | 2) => {
    if (!paired) return t("filter.fastp.adapterAuto");
    const a = pairedAdapter({ ...params, ...(mate === 1 ? { adapter_sequence: null } : { adapter_sequence_r2: null }) }, mate);
    return a === "detected" ? t("filter.fastp.adapterAuto") : typeof a === "string" ? t(`filter.do.pairedAdapter.${a}`) : a.sequence;
  };
  const sameAs = (v: number) => t("filter.fastp.sameAsRead1", { value: v });
  const mates = paired ? ([1, 2] as const) : ([1] as const);

  return (
    <div className="space-y-4">
      <ToolLine tool={tool} />
      {warnLong && <Warning>{t("filter.fastp.warnLong")}</Warning>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("filter.fastp.read1")}>
          <Select value={r1} onChange={(e) => setR1(e.target.value)}>
            {files.map((f) => (
              <option key={f.id} value={f.id}>
                {label(f, t)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("filter.fastp.read2")}>
          <Select value={r2} onChange={(e) => setR2(e.target.value)}>
            <option value="">{t("filter.fastp.noRead2")}</option>
            {files
              .filter((f) => f.id !== r1)
              .map((f) => (
                <option key={f.id} value={f.id}>
                  {label(f, t)}
                </option>
              ))}
          </Select>
        </Field>
      </div>

      <Section title={t("filter.fastp.section.adapters")}>
        <Toggle checked={p.adapter_trimming} onChange={set("adapter_trimming")}>{t("filter.fastp.adapterTrimming")}</Toggle>
        {paired && (
          <Toggle checked={p.detect_adapter_for_pe} onChange={set("detect_adapter_for_pe")}>
            {t("filter.fastp.detectPe")}
          </Toggle>
        )}
        {p.adapter_trimming && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <AdapterInput
                label={paired ? t("filter.fastp.adapterMate", { mate: 1 }) : t("filter.fastp.adapterSingle")}
                value={p.adapter_sequence}
                onChange={set("adapter_sequence")}
                placeholder={adapterPlaceholder(1)}
              />
              {paired && (
                <AdapterInput
                  label={t("filter.fastp.adapterMate", { mate: 2 })}
                  value={p.adapter_sequence_r2}
                  onChange={set("adapter_sequence_r2")}
                  placeholder={adapterPlaceholder(2)}
                />
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">{t("filter.fastp.adapterHint")}</p>
            {inputs.map((f) => (
              <MissedAdapterNote key={f.id} jobs={jobs} file={f} />
            ))}
          </>
        )}
      </Section>
      <Section title={t("filter.fastp.section.trim")}>
        <p className="text-[11px] text-muted-foreground">{t("filter.fastp.trimExplain")}</p>
        {mates.map((mate) => (
          <div key={mate} className="space-y-1.5">
            {paired && <div className="text-xs font-medium">{t("filter.fastp.mate", { mate })}</div>}
            <div className="grid gap-3 sm:grid-cols-3">
              {mate === 1 ? (
                <>
                  <Num label={t("filter.fastp.trimFront")} value={p.trim_front1} min={0} max={TRIM_FRONT_MAX} onChange={(v) => set("trim_front1")(v ?? 0)} hint={t("filter.fastp.range", { max: TRIM_FRONT_MAX })} />
                  <Num label={t("filter.fastp.trimTail")} value={p.trim_tail1} min={0} max={TRIM_TAIL_MAX} onChange={(v) => set("trim_tail1")(v ?? 0)} hint={t("filter.fastp.range", { max: TRIM_TAIL_MAX })} />
                  <Num label={t("filter.fastp.maxLen")} value={p.max_len1} min={0} onChange={(v) => set("max_len1")(v ?? 0)} hint={t("filter.defaultOff")} />
                </>
              ) : (
                <>
                  <Num label={t("filter.fastp.trimFront")} value={p.trim_front2} min={0} max={TRIM_FRONT_MAX} nullable placeholder={sameAs(p.trim_front1)} onChange={set("trim_front2")} hint={t("filter.fastp.range", { max: TRIM_FRONT_MAX })} />
                  <Num label={t("filter.fastp.trimTail")} value={p.trim_tail2} min={0} max={TRIM_TAIL_MAX} nullable placeholder={sameAs(p.trim_tail1)} onChange={set("trim_tail2")} hint={t("filter.fastp.range", { max: TRIM_TAIL_MAX })} />
                  <Num label={t("filter.fastp.maxLen")} value={p.max_len2} min={0} nullable placeholder={sameAs(p.max_len1)} onChange={set("max_len2")} hint={t("filter.defaultOff")} />
                </>
              )}
            </div>
          </div>
        ))}
      </Section>
      <Section title={t("filter.fastp.section.quality")}>
        <Toggle checked={p.quality_filtering} onChange={set("quality_filtering")}>{t("filter.fastp.qualityFiltering")}</Toggle>
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label={t("filter.fastp.qualifiedQuality")} value={p.qualified_quality_phred} min={0} max={93} disabled={!p.quality_filtering} onChange={(v) => set("qualified_quality_phred")(v ?? 0)} hint={t("filter.default", { value: 15 })} />
          <Num label={t("filter.fastp.unqualifiedPercent")} value={p.unqualified_percent_limit} min={0} max={100} disabled={!p.quality_filtering} onChange={(v) => set("unqualified_percent_limit")(v ?? 0)} hint={t("filter.default", { value: 40 })} />
          <Num label={t("filter.fastp.nBases")} value={p.n_base_limit} min={0} disabled={!p.quality_filtering} onChange={(v) => set("n_base_limit")(v ?? 0)} hint={t("filter.default", { value: 5 })} />
          <Num label={t("filter.fastp.averageQual")} value={p.average_qual} min={0} max={93} disabled={!p.quality_filtering} onChange={(v) => set("average_qual")(v ?? 0)} hint={t("filter.defaultOff")} />
        </div>
        <Toggle checked={p.low_complexity_filter} onChange={set("low_complexity_filter")}>{t("filter.fastp.complexity")}</Toggle>
        <Num label={t("filter.fastp.complexityThreshold")} value={p.complexity_threshold} min={0} max={100} disabled={!p.low_complexity_filter} onChange={(v) => set("complexity_threshold")(v ?? 30)} hint={t("filter.fastp.complexityHint")} />
      </Section>
      <Section title={t("filter.fastp.section.length")}>
        <Toggle checked={p.length_filtering} onChange={set("length_filtering")}>{t("filter.fastp.lengthFiltering")}</Toggle>
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label={t("filter.fastp.lengthRequired")} value={p.length_required} min={0} disabled={!p.length_filtering} onChange={(v) => set("length_required")(v ?? 0)} hint={t("filter.fastp.lengthRequiredHint")} />
          <Num label={t("filter.fastp.lengthLimit")} value={p.length_limit} min={0} disabled={!p.length_filtering && p.length_limit === 0} onChange={(v) => set("length_limit")(v ?? 0)} hint={t("filter.fastp.lengthLimitHint")} />
        </div>
      </Section>
      <Section title={t("filter.fastp.section.window")}>
        <div className="flex flex-wrap gap-4">
          <Toggle checked={p.cut_front} onChange={set("cut_front")}>{t("filter.fastp.cutFront")}</Toggle>
          <Toggle checked={p.cut_tail} onChange={set("cut_tail")}>{t("filter.fastp.cutTail")}</Toggle>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label={t("filter.fastp.windowSize")} value={p.cut_window_size} min={1} max={1000} disabled={!p.cut_front && !p.cut_tail} onChange={(v) => set("cut_window_size")(v ?? 4)} hint={t("filter.default", { value: 4 })} />
          <Num label={t("filter.fastp.windowQuality")} value={p.cut_mean_quality} min={1} max={30} disabled={!p.cut_front && !p.cut_tail} onChange={(v) => set("cut_mean_quality")(v ?? 20)} hint={t("filter.fastp.windowQualityHint")} />
        </div>
      </Section>
      <Section title={t("filter.fastp.section.other")}>
        <Field label={t("filter.fastp.polyG")}>
          <Select value={p.poly_g} onChange={(e) => set("poly_g")(e.target.value as FastpParams["poly_g"])}>
            <option value="auto">{t("filter.fastp.polyG.auto")}</option>
            <option value="force">{t("filter.fastp.polyG.force")}</option>
            <option value="disable">{t("filter.fastp.polyG.disable")}</option>
          </Select>
        </Field>
        <Toggle checked={p.dedup} onChange={set("dedup")}>{t("filter.fastp.dedup")}</Toggle>
      </Section>

      <Summary items={describeFastp(params, paired, t)} />
      {problems.map((k) => (
        <p key={k} className="flex gap-1.5 text-xs text-danger">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {t(k)}
        </p>
      ))}
      <Parameters values={{ read1: inputs[0]?.original_filename, read2: paired ? inputs[1]?.original_filename : null, ...params }} />
      <Confirm checked={ok} onChange={setOk} />
      <ErrorNote error={run.error} />
      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="ghost" onClick={() => setP(FASTP_DEFAULTS)}>{t("filter.fastp.reset")}</Button>
        <Button disabled={!ok || !r1 || problems.length > 0 || run.isPending || tool?.status !== "available"} onClick={() => run.mutate()}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {t("filter.fastp.run")}
        </Button>
      </div>
    </div>
  );
}

type TargetMode = "none" | "bases" | "coverage";

function FiltlongForm({ sampleId, files, jobs, warnShort, onDone }: { sampleId: string; files: RawFile[]; jobs: AnalysisJobDetail[]; warnShort: boolean; onDone: () => void }) {
  const t = useT();
  const tool = useTool("filtlong");
  const [fileId, setFileId] = useState(files[0]?.id ?? "");
  const [p, setP] = useState<FiltlongParams>({ ...FILTLONG_EMPTY, min_length: 1000, keep_percent: 90 });
  const [mode, setMode] = useState<TargetMode>("none");
  const [targetMbp, setTargetMbp] = useState<number | null>(null);
  const results = useMemo(() => latestResults(jobs), [jobs]);
  const file = files.find((f) => f.id === fileId);
  const stored = file ? storedGenomeSize(results, file) : null;
  const [genome, setGenome] = useState<number | null>(stored);
  const [depthX, setDepthX] = useState<number | null>(null);
  useEffect(() => {
    if (stored != null) setGenome(stored);
  }, [fileId, stored]);
  const [ok, setOk] = useState(false);
  const set = <K extends keyof FiltlongParams>(k: K) => (v: FiltlongParams[K]) => setP((x) => ({ ...x, [k]: v }));

  const coverage = mode === "coverage" && genome && genome > 0 && depthX && depthX > 0 ? { genome_size_bp: genome, target_coverage_x: depthX } : null;
  const target =
    mode === "bases" && targetMbp != null ? Math.round(targetMbp * 1e6) : coverage ? targetBasesForCoverage(coverage.genome_size_bp, coverage.target_coverage_x) : null;
  const params = { ...p, target_bases: target };
  const incomplete = mode === "coverage" && !coverage;
  const stats = results.get(fileId)?.qc.metrics;
  const input = stats ? { bases: stats.total_bases, longest: stats.max_length } : null;
  const expected = params.keep_percent != null || target != null ? expectedKeptBases(filtlongTarget(params, input?.bases ?? null), input) : null;
  const depthOf = (bases: number) => (coverage ? `${fmtNum(bases / coverage.genome_size_bp, 1)}×` : "");
  const { onSuccess } = useStart(sampleId, onDone);
  const run = useMutation({
    mutationFn: () =>
      api.runFiltlong(sampleId, {
        file_id: fileId,
        params,
        genome_size_bp: coverage?.genome_size_bp ?? null,
        target_coverage_x: coverage?.target_coverage_x ?? null,
      }),
    onSuccess,
  });
  const qHint = (v: number | null) =>
    v == null ? t("filter.filtlong.qHint") : v >= 100 ? t("filter.filtlong.qTooHigh") : `≈ Q${identityToPhred(v).toFixed(1)}`;
  const suspicious = [p.min_mean_q, p.min_window_q].some((v) => v != null && v > 0 && v < 50);

  return (
    <div className="space-y-4">
      <ToolLine tool={tool} />
      {warnShort && <Warning>{t("filter.filtlong.warnShort")}</Warning>}
      <Field label={t("filter.filtlong.file")}>
        <Select value={fileId} onChange={(e) => setFileId(e.target.value)}>
          {files.map((f) => (
            <option key={f.id} value={f.id}>
              {label(f, t)}
            </option>
          ))}
        </Select>
      </Field>
      <Section title={t("filter.filtlong.section.hard")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label={t("filter.filtlong.minLength")} value={p.min_length} min={1} nullable onChange={set("min_length")} />
          <Num label={t("filter.filtlong.maxLength")} value={p.max_length} min={1} nullable onChange={set("max_length")} />
          <Num label={t("filter.filtlong.minMeanQ")} value={p.min_mean_q} min={0} max={99.99} step={0.1} nullable onChange={set("min_mean_q")} hint={qHint(p.min_mean_q)} />
          <Num label={t("filter.filtlong.minWindowQ")} value={p.min_window_q} min={0} max={99.99} step={0.1} nullable onChange={set("min_window_q")} hint={qHint(p.min_window_q)} />
        </div>
        {suspicious && (
          <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {t("filter.filtlong.suspicious")}
          </p>
        )}
      </Section>
      <Section title={t("filter.filtlong.section.best")}>
        <Num label={t("filter.filtlong.keepPercent")} value={p.keep_percent} min={0.01} max={100} step={0.1} nullable onChange={set("keep_percent")} />
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-muted-foreground">{t("filter.filtlong.targetMode")}</div>
          <Segmented
            label={t("filter.filtlong.targetMode")}
            value={mode}
            onChange={setMode}
            options={[
              { value: "none", label: t("filter.filtlong.target.none") },
              { value: "bases", label: t("filter.filtlong.target.bases") },
              { value: "coverage", label: t("filter.filtlong.target.coverage") },
            ]}
          />
        </div>
        {mode === "bases" && (
          <Num label={t("filter.filtlong.targetMbp")} value={targetMbp} min={0.000001} step={0.1} nullable onChange={setTargetMbp} hint={t("filter.filtlong.targetMbpHint")} />
        )}
        {mode === "coverage" && (
          <>
            <p className="text-[11px] text-muted-foreground">{t("filter.filtlong.coverageExplain")}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Num
                label={t("filter.filtlong.genomeSize")}
                value={genome}
                min={1}
                nullable
                onChange={setGenome}
                hint={
                  stored != null && genome === stored
                    ? t("filter.filtlong.genomeStored", { size: fmtBases(stored) })
                    : stored == null
                      ? t("filter.filtlong.genomeTyped")
                      : genome
                        ? fmtBases(genome)
                        : undefined
                }
              />
              <Num label={t("filter.filtlong.depth")} value={depthX} min={0.1} step={0.1} nullable onChange={setDepthX} hint={t("filter.filtlong.depthHint")} />
            </div>
            {coverage && target != null ? (
              <p className="text-sm font-medium">
                {t("filter.filtlong.coverageTarget", {
                  bases: fmtInt(target),
                  compact: fmtBases(target),
                  depth: fmtNum(coverage.target_coverage_x, 1),
                  genome: fmtInt(coverage.genome_size_bp),
                })}
              </p>
            ) : (
              <p className="text-xs text-amber-700 dark:text-warning">{t("filter.filtlong.coverageIncomplete")}</p>
            )}
          </>
        )}
        {expected && (
          <div className="space-y-1 rounded-lg bg-muted/60 p-3 text-xs">
            <p>
              {expected.kind === "unknown"
                ? t("filter.filtlong.expectedUnknown")
                : expected.kind === "all"
                  ? t("filter.filtlong.expectedAll", {
                      bases: fmtInt(expected.bases),
                      depth: coverage ? t("filter.filtlong.depthOf", { depth: depthOf(expected.bases) }) : "",
                    })
                  : t("filter.filtlong.expected", {
                      min: fmtInt(expected.min),
                      max: fmtInt(expected.max),
                      longest: fmtInt(input?.longest ?? 0),
                      depth: coverage ? t("filter.filtlong.depthRange", { min: depthOf(expected.min), max: depthOf(expected.max) }) : "",
                    })}
            </p>
            {p.keep_percent != null && target != null && <p>{t("filter.filtlong.bothTargets")}</p>}
            <p className="text-muted-foreground">{t("filter.filtlong.hardFirst")}</p>
          </div>
        )}
      </Section>
      <details className="rounded-xl border p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("filter.filtlong.weights")}</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Num label={t("filter.filtlong.lengthWeight")} value={p.length_weight} min={0} step={0.1} onChange={(v) => set("length_weight")(v ?? 1)} hint={t("filter.default", { value: 1 })} />
          <Num label={t("filter.filtlong.meanQWeight")} value={p.mean_q_weight} min={0} step={0.1} onChange={(v) => set("mean_q_weight")(v ?? 1)} hint={t("filter.default", { value: 1 })} />
          <Num label={t("filter.filtlong.windowQWeight")} value={p.window_q_weight} min={0} step={0.1} onChange={(v) => set("window_q_weight")(v ?? 1)} hint={t("filter.default", { value: 1 })} />
          <Num label={t("filter.filtlong.windowSize")} value={p.window_size} min={1} onChange={(v) => set("window_size")(v ?? 250)} hint={t("filter.default", { value: 250 })} />
        </div>
      </details>

      {filtlongHasThreshold(params) ? (
        <Summary items={describeFiltlong(params, t, coverage)} />
      ) : (
        <p className="text-sm text-amber-700 dark:text-warning">{t("filter.filtlong.needThreshold")}</p>
      )}
      <Parameters
        values={{ file: file?.original_filename, ...params, genome_size_bp: coverage?.genome_size_bp ?? null, target_coverage_x: coverage?.target_coverage_x ?? null }}
      />
      <Confirm checked={ok} onChange={setOk} />
      <ErrorNote error={run.error} />
      <div className="flex justify-end">
        <Button disabled={!ok || !fileId || incomplete || !filtlongHasThreshold(params) || run.isPending || tool?.status !== "available"} onClick={() => run.mutate()}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {t("filter.filtlong.run")}
        </Button>
      </div>
    </div>
  );
}
