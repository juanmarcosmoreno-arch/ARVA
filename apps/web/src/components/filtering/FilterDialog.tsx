import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Segmented } from "@/components/charts/ChartCard";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { api } from "@/lib/api";
import {
  FASTP_DEFAULTS,
  FILTLONG_EMPTY,
  describeFastp,
  describeFiltlong,
  filtlongHasThreshold,
  identityToPhred,
} from "@/lib/filters";
import type { FastpParams, FiltlongParams, RawFile, SequencingTechnology, Tool } from "@/lib/types";

type FilterTool = "fastp" | "filtlong";

const fastqFiles = (files: RawFile[]) =>
  files.filter((f) => (f.file_format === "fastq" || f.file_format === "fastq_gz") && f.is_valid);

const label = (f: RawFile) => `${f.original_filename}${f.origin === "derived" ? " (derived)" : ""}`;

export function FilterDialog({
  open,
  onOpenChange,
  sampleId,
  files,
  technology,
  onStarted,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  files: RawFile[];
  technology: SequencingTechnology;
  onStarted?: () => void;
}) {
  const longReads = technology === "nanopore" || technology === "pacbio";
  const [tool, setTool] = useState<FilterTool>(longReads ? "filtlong" : "fastp");
  useEffect(() => {
    if (open) setTool(longReads ? "filtlong" : "fastp");
  }, [open, longReads]);
  const candidates = fastqFiles(files);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Filter reads"
      description="Creates a new, derived file with the reads that pass. The original file is never modified."
      className="max-w-2xl"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Segmented
          label="Filtering tool"
          value={tool}
          onChange={setTool}
          options={[
            { value: "fastp", label: "fastp · short reads" },
            { value: "filtlong", label: "Filtlong · long reads" },
          ]}
        />
        <Explain id={tool} />
      </div>
      {candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">No valid FASTQ files in this sample.</p>
      ) : tool === "fastp" ? (
        <FastpForm sampleId={sampleId} files={candidates} warnLong={longReads} onDone={() => { onOpenChange(false); onStarted?.(); }} />
      ) : (
        <FiltlongForm sampleId={sampleId} files={candidates} warnShort={technology === "illumina"} onDone={() => { onOpenChange(false); onStarted?.(); }} />
      )}
    </Dialog>
  );
}

function ToolLine({ tool }: { tool: Tool | undefined }) {
  if (!tool) return null;
  if (tool.status !== "available")
    return (
      <div className="flex gap-2 rounded-lg border border-danger/30 bg-danger/5 p-3 text-xs">
        <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
        <span>
          {tool.name} is not available ({tool.status.replace("_", " ")}). Install it, e.g. <code>{tool.install.conda ?? tool.install.apt}</code>, then
          refresh the Tools page.
        </span>
      </div>
    );
  return (
    <p className="text-xs text-muted-foreground">
      {tool.name} {tool.version} · {tool.license}
      {!tool.version_validated && <span className="text-amber-700 dark:text-warning"> · version not validated with ARVA</span>}
    </p>
  );
}

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" className="h-4 w-4 accent-[#00B4A6]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
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
  return (
    <Field label={label} hint={hint}>
      <Input
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        placeholder={placeholder ?? (nullable ? "not set" : undefined)}
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
    <fieldset className="rounded-xl border p-4">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</legend>
      <div className="space-y-3">{children}</div>
    </fieldset>
  );
}

function Summary({ items }: { items: string[] }) {
  return (
    <div className="rounded-xl bg-muted/60 p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold">
        <Info className="h-3.5 w-3.5 text-arva-teal" /> What this run will do
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-sm">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  );
}

function Confirm({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <Toggle checked={checked} onChange={onChange}>
      <span className="text-xs">
        I have reviewed these settings. Reads that do not pass will be excluded from the new file; the original file is kept unchanged.
      </span>
    </Toggle>
  );
}

function useStart(sampleId: string, onDone: () => void) {
  const qc = useQueryClient();
  return {
    qc,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs", sampleId] });
      qc.invalidateQueries({ queryKey: ["files", sampleId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onDone();
    },
  };
}

function FastpForm({ sampleId, files, warnLong, onDone }: { sampleId: string; files: RawFile[]; warnLong: boolean; onDone: () => void }) {
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
  const { onSuccess } = useStart(sampleId, onDone);
  const run = useMutation({
    mutationFn: () => api.runFastp(sampleId, { read1_file_id: r1, read2_file_id: r2 || null, params: p }),
    onSuccess,
  });
  const paired = Boolean(r2);

  return (
    <div className="space-y-4">
      <ToolLine tool={tool} />
      {warnLong && (
        <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
          This sample is recorded as long-read data. fastp is designed for short reads; Filtlong is usually the appropriate choice.
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Read 1 (or single-end reads)">
          <Select value={r1} onChange={(e) => setR1(e.target.value)}>
            {files.map((f) => (
              <option key={f.id} value={f.id}>
                {label(f)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Read 2 (paired-end, optional)">
          <Select value={r2} onChange={(e) => setR2(e.target.value)}>
            <option value="">None — single-end</option>
            {files
              .filter((f) => f.id !== r1)
              .map((f) => (
                <option key={f.id} value={f.id}>
                  {label(f)}
                </option>
              ))}
          </Select>
        </Field>
      </div>

      <Section title="Adapter trimming">
        <Toggle checked={p.adapter_trimming} onChange={set("adapter_trimming")}>Trim adapter sequences (fastp default: on)</Toggle>
        {paired && (
          <Toggle checked={p.detect_adapter_for_pe} onChange={set("detect_adapter_for_pe")} >
            Also auto-detect adapters for paired-end data (in addition to overlap analysis)
          </Toggle>
        )}
      </Section>
      <Section title="Quality filtering">
        <Toggle checked={p.quality_filtering} onChange={set("quality_filtering")}>Filter reads by base quality (fastp default: on)</Toggle>
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label="Qualified base quality (Phred)" value={p.qualified_quality_phred} min={0} max={93} disabled={!p.quality_filtering} onChange={(v) => set("qualified_quality_phred")(v ?? 0)} hint="default 15" />
          <Num label="Max. unqualified bases (%)" value={p.unqualified_percent_limit} min={0} max={100} disabled={!p.quality_filtering} onChange={(v) => set("unqualified_percent_limit")(v ?? 0)} hint="default 40" />
          <Num label="Max. N bases per read" value={p.n_base_limit} min={0} disabled={!p.quality_filtering} onChange={(v) => set("n_base_limit")(v ?? 0)} hint="default 5" />
          <Num label="Min. average read quality (0 = off)" value={p.average_qual} min={0} max={93} disabled={!p.quality_filtering} onChange={(v) => set("average_qual")(v ?? 0)} hint="default 0 (off)" />
        </div>
      </Section>
      <Section title="Length filtering">
        <Toggle checked={p.length_filtering} onChange={set("length_filtering")}>Remove short reads (fastp default: on)</Toggle>
        <Num label="Minimum length after trimming (bp)" value={p.length_required} min={0} disabled={!p.length_filtering} onChange={(v) => set("length_required")(v ?? 0)} hint="default 15" />
      </Section>
      <Section title="Sliding-window quality trimming (fastp default: off)">
        <div className="flex flex-wrap gap-4">
          <Toggle checked={p.cut_front} onChange={set("cut_front")}>Trim 5′ end</Toggle>
          <Toggle checked={p.cut_tail} onChange={set("cut_tail")}>Trim 3′ end</Toggle>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label="Window size (bases)" value={p.cut_window_size} min={1} max={1000} disabled={!p.cut_front && !p.cut_tail} onChange={(v) => set("cut_window_size")(v ?? 4)} hint="default 4" />
          <Num label="Window mean quality (Phred)" value={p.cut_mean_quality} min={1} max={36} disabled={!p.cut_front && !p.cut_tail} onChange={(v) => set("cut_mean_quality")(v ?? 20)} hint="default 20" />
        </div>
      </Section>
      <Section title="Other">
        <Field label="Poly-G tail trimming">
          <Select value={p.poly_g} onChange={(e) => set("poly_g")(e.target.value as FastpParams["poly_g"])}>
            <option value="auto">Automatic (fastp enables it for NextSeq/NovaSeq data)</option>
            <option value="force">Always trim poly-G tails</option>
            <option value="disable">Never trim poly-G tails</option>
          </Select>
        </Field>
        <Toggle checked={p.dedup} onChange={set("dedup")}>Remove duplicated reads (fastp default: off)</Toggle>
      </Section>

      <Summary items={describeFastp(p, paired)} />
      <Confirm checked={ok} onChange={setOk} />
      <ErrorNote error={run.error} />
      <div className="flex justify-between gap-2">
        <Button variant="ghost" onClick={() => setP(FASTP_DEFAULTS)}>Reset to fastp defaults</Button>
        <Button disabled={!ok || !r1 || run.isPending || tool?.status !== "available"} onClick={() => run.mutate()}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run fastp
        </Button>
      </div>
    </div>
  );
}

function FiltlongForm({ sampleId, files, warnShort, onDone }: { sampleId: string; files: RawFile[]; warnShort: boolean; onDone: () => void }) {
  const tool = useTool("filtlong");
  const [fileId, setFileId] = useState(files[0]?.id ?? "");
  const [p, setP] = useState<FiltlongParams>({ ...FILTLONG_EMPTY, min_length: 1000, keep_percent: 90 });
  const [targetMbp, setTargetMbp] = useState<number | null>(null);
  const [ok, setOk] = useState(false);
  const set = <K extends keyof FiltlongParams>(k: K) => (v: FiltlongParams[K]) => setP((x) => ({ ...x, [k]: v }));
  const params = { ...p, target_bases: targetMbp != null ? Math.round(targetMbp * 1e6) : null };
  const { onSuccess } = useStart(sampleId, onDone);
  const run = useMutation({ mutationFn: () => api.runFiltlong(sampleId, { file_id: fileId, params }), onSuccess });
  const qHint = (v: number | null) => (v == null ? "percent identity, 0–100 (not Phred)" : v >= 100 ? "must be < 100" : `≈ Q${identityToPhred(v).toFixed(1)}`);
  const suspicious = [p.min_mean_q, p.min_window_q].some((v) => v != null && v > 0 && v < 50);

  return (
    <div className="space-y-4">
      <ToolLine tool={tool} />
      {warnShort && (
        <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
          This sample is recorded as Illumina data. Filtlong is designed for long reads; fastp is usually the appropriate choice.
        </div>
      )}
      <Field label="Long-read file">
        <Select value={fileId} onChange={(e) => setFileId(e.target.value)}>
          {files.map((f) => (
            <option key={f.id} value={f.id}>
              {label(f)}
            </option>
          ))}
        </Select>
      </Field>
      <Section title="Hard thresholds (reads failing any are removed)">
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label="Minimum length (bp)" value={p.min_length} min={1} nullable onChange={set("min_length")} />
          <Num label="Maximum length (bp)" value={p.max_length} min={1} nullable onChange={set("max_length")} />
          <Num label="Minimum mean quality (% identity)" value={p.min_mean_q} min={0} max={99.99} step={0.1} nullable onChange={set("min_mean_q")} hint={qHint(p.min_mean_q)} />
          <Num label="Minimum window quality (% identity)" value={p.min_window_q} min={0} max={99.99} step={0.1} nullable onChange={set("min_window_q")} hint={qHint(p.min_window_q)} />
        </div>
        {suspicious && (
          <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            Filtlong quality thresholds are percent identities, not Phred scores. Q10 ≈ 90, Q13 ≈ 95, Q20 ≈ 99.
          </p>
        )}
      </Section>
      <Section title="Keep the best reads (measured in bases)">
        <div className="grid gap-3 sm:grid-cols-2">
          <Num label="Keep best % of bases" value={p.keep_percent} min={0.01} max={100} step={0.1} nullable onChange={set("keep_percent")} />
          <Num label="Target total (Mbp)" value={targetMbp} min={0.000001} step={0.1} nullable onChange={setTargetMbp} hint="keep the best reads up to this many bases" />
        </div>
      </Section>
      <details className="rounded-xl border p-4">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">Score weights (advanced)</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Num label="Length weight" value={p.length_weight} min={0} step={0.1} onChange={(v) => set("length_weight")(v ?? 1)} hint="default 1" />
          <Num label="Mean quality weight" value={p.mean_q_weight} min={0} step={0.1} onChange={(v) => set("mean_q_weight")(v ?? 1)} hint="default 1" />
          <Num label="Window quality weight" value={p.window_q_weight} min={0} step={0.1} onChange={(v) => set("window_q_weight")(v ?? 1)} hint="default 1" />
          <Num label="Window size (bp)" value={p.window_size} min={1} onChange={(v) => set("window_size")(v ?? 250)} hint="default 250" />
        </div>
      </details>

      {filtlongHasThreshold(params) ? (
        <Summary items={describeFiltlong(params)} />
      ) : (
        <p className="text-sm text-amber-700 dark:text-warning">Set at least one threshold — otherwise Filtlong keeps every read.</p>
      )}
      <Confirm checked={ok} onChange={setOk} />
      <ErrorNote error={run.error} />
      <div className="flex justify-end">
        <Button
          disabled={!ok || !fileId || !filtlongHasThreshold(params) || run.isPending || tool?.status !== "available"}
          onClick={() => run.mutate()}
        >
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run Filtlong
        </Button>
      </div>
    </div>
  );
}
