import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, CornerDownRight, Info, Lightbulb } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { dictionaries, type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import {
  FLYE_FORM_DEFAULTS,
  READ_ERROR_TYPES,
  READ_TYPES,
  advancedFlags,
  chosenGenomeSize,
  defaultFlyeSelection,
  flyeCandidates,
  flyeProblems,
  flyeRequestParams,
  selectedTwice,
  type FlyeForm,
  type GenomeChoice,
} from "@/lib/flye";
import { lineageOrder } from "@/lib/filters";
import { fmtBases, fmtBp, fmtInt, fmtNum, technologyLabel } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import type { AnalysisJobDetail, FlyePlan, FlyeReadType, RawFile } from "@/lib/types";
import { cn } from "@/lib/utils";

export const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** What a panel of the "New assembly" dialog reports: why it cannot start yet (translated), and the request it
 * would send (null while blocked). */
export interface PanelState {
  problems: string[];
  request: unknown;
}

export type ReportPanel = (assembler: "flye" | "spades" | "unicycler", state: PanelState) => void;

/** Flye in the "New assembly" dialog: the long reads by lineage with ARVA's evidence, every Flye option explained,
 * and a summary of what the run will do. */
export function FlyePanel({
  open,
  sampleId,
  files,
  jobs = [],
  report,
}: {
  open: boolean;
  sampleId: string;
  files: RawFile[];
  /** The sample's jobs, to name the tool that filtered a derived file. */
  jobs?: AnalysisJobDetail[];
  report: ReportPanel;
}) {
  const t = useT();
  const candidates = flyeCandidates(files);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [form, setForm] = useState<FlyeForm>(FLYE_FORM_DEFAULTS);
  const [confirmed, setConfirmed] = useState(false);
  const [depth, setDepth] = useState<number | null>(null);
  useEffect(() => {
    if (!open) return;
    setSelected(new Set(defaultFlyeSelection(files)));
    setForm(FLYE_FORM_DEFAULTS);
    setConfirmed(false);
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  useEffect(() => {
    const d = form.genomeChoice === "depth" && Number(form.depthX) > 0 ? Number(form.depthX) : null;
    const timer = setTimeout(() => setDepth(d), 350);
    return () => clearTimeout(timer);
  }, [form.genomeChoice, form.depthX]);

  const ids = [...selected].sort();
  const plan = useQuery({
    queryKey: ["flyePlan", sampleId, ids, depth],
    queryFn: () => api.flyePreview(sampleId, { raw_file_ids: ids, assumed_depth_x: depth }),
    enabled: open && ids.length > 0,
    retry: false,
  });
  const p = plan.data;
  const keys = flyeProblems(form, p, ids.length, confirmed);
  if (ids.length && (plan.isError || (p && p.tool.status !== "available"))) keys.push("assembly.problem.tool");
  else if (ids.length && !p) keys.push("assembly.problem.checking");
  const problems = keys.map((k) => t(k, { max: p?.tool.max_threads ?? "?", tool: "Flye" }));
  const request = problems.length ? null : { raw_file_ids: ids, params: flyeRequestParams(form, p), long_reads_confirmed: confirmed };
  const stateKey = JSON.stringify({ problems, request });
  useEffect(() => report("flye", { problems, request }), [stateKey]);

  const set = <K extends keyof FlyeForm>(key: K, value: FlyeForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const twice = selectedTwice(files, selected);
  const names = new Map(files.map((f) => [f.id, f.original_filename]));
  const producedBy = new Map(jobs.map((j) => [j.id, `${j.tool_name} ${j.tool_version}`]));
  const advanced = advancedFlags(form);

  return (
    <div className="space-y-5 text-sm">
      {p && <ToolLine plan={p} />}

      <Section title={t("flye.filesLabel")} hint={t("flye.filesHint")}>
        {candidates.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("flye.noFiles")}</p>
        ) : (
          <ul className="divide-y rounded-lg border" aria-label={t("flye.filesLabel")}>
            {lineageOrder(candidates).map(({ file: f, depth: level }) => {
              const e = p?.files.find((x) => x.file_id === f.id);
              return (
                <li key={f.id} className="flex items-start gap-2.5 py-2 pr-3" style={{ paddingLeft: 12 + level * 20 }}>
                  {level > 0 && <CornerDownRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                  <input type="checkbox" className={CHECK} checked={selected.has(f.id)} onChange={() => toggle(f.id)} aria-label={f.original_filename} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate font-medium">{f.original_filename}</span>
                      <OriginBadge file={f} producedBy={producedBy} />
                    </div>
                    {f.origin === "derived" && f.parent_file_id && (
                      <div className="text-xs text-muted-foreground">{t("assembly.input.from", { name: names.get(f.parent_file_id) ?? f.parent_file_id })}</div>
                    )}
                    {e && <Evidence e={e} />}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {twice.map((f) => (
          <p key={f.id} className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("flye.duplicateWarning", { name: f.original_filename })}
          </p>
        ))}
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("flye.checking")}</p>}
        <ErrorNote error={plan.error} />
      </Section>

      <Section title={t("flye.readType")} hint={t("flye.readTypeGuide")} action={<Explain id="flye_read_types" compact />}>
        <Select value={form.readType} onChange={(e) => set("readType", e.target.value as FlyeReadType | "")} aria-label={t("flye.readType")}>
          <option value="">{t("flye.chooseReadType")}</option>
          {READ_TYPES.map((r) => (
            <option key={r.value} value={r.value}>
              {t(r.label)}
            </option>
          ))}
        </Select>
        {p && <Suggestion plan={p} current={form.readType} onUse={(v) => set("readType", v)} />}
      </Section>

      <GenomeSize form={form} plan={p} set={set} />

      <Section title={t("assembly.runSettings")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("flye.iterations")} hint={t("flye.iterationsHint")}>
            <Input type="number" min={0} max={10} value={form.iterations} onChange={(e) => set("iterations", e.target.value)} />
          </Field>
          <Field label={t("flye.threads")} hint={t("flye.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
            <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
          </Field>
        </div>
      </Section>

      <Advanced title={t("assembly.advanced.title")} changed={advanced.length}>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("flye.minOverlap")} hint={t("flye.minOverlapHint")}>
            <Input type="number" min={1000} max={10000} placeholder={t("flye.auto")} value={form.minOverlap} onChange={(e) => set("minOverlap", e.target.value)} />
          </Field>
          <Field label={t("flye.asmCoverage")} hint={t("flye.asmCoverageHint")}>
            <Input type="number" min={1} value={form.asmCoverage} onChange={(e) => set("asmCoverage", e.target.value)} disabled={!supported(p, "--asm-coverage")} />
          </Field>
          <Field label={t("flye.readError")} hint={t("flye.readErrorHint")}>
            <Input
              inputMode="decimal"
              placeholder="0.03"
              value={form.readError}
              onChange={(e) => set("readError", e.target.value)}
              disabled={!supported(p, "--read-error") || !form.readType || !READ_ERROR_TYPES.has(form.readType)}
            />
          </Field>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["meta", "--meta", "flye.meta", "flye.metaHint"],
              ["keepHaplotypes", "--keep-haplotypes", "flye.keepHaplotypes", "flye.keepHaplotypesHint"],
              ["noAltContigs", "--no-alt-contigs", "flye.noAltContigs", "flye.noAltContigsHint"],
              ["scaffold", "--scaffold", "flye.scaffold", "flye.scaffoldHint"],
            ] as const
          ).map(([key, flag, label, hint]) => {
            const offered = supported(p, flag);
            return (
              <label key={key} className={cn("flex items-start gap-2 text-xs", !offered && "opacity-60")}>
                <input type="checkbox" className={CHECK} checked={form[key]} disabled={!offered} onChange={(e) => set(key, e.target.checked)} />
                <span>
                  <code>{flag}</code> {t(label)}
                  <span className="block text-muted-foreground">{offered ? t(hint) : t("flye.notInThisVersion")}</span>
                </span>
              </label>
            );
          })}
        </div>
      </Advanced>

      {p?.long_reads_confirmation_required && (
        <label className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>
            {t("flye.confirm")}
            <span className="block text-muted-foreground">{t("flye.confirmHint", { technology: technologyLabel(p.sample_technology) })}</span>
          </span>
        </label>
      )}

      <RunSummary form={form} plan={p} files={files} ids={ids} advanced={advanced} />
    </div>
  );
}

/** "Original" or "filtered with <tool>" for a read file. */
export function OriginBadge({ file: f, producedBy }: { file: RawFile; producedBy: Map<string, string> }) {
  const t = useT();
  return f.origin === "derived" ? (
    <Badge tone="teal">{t("assembly.input.filteredBy", { tool: (f.produced_by_job_id && producedBy.get(f.produced_by_job_id)) || t("flye.derived") })}</Badge>
  ) : (
    <Badge tone="neutral">{t("assembly.input.original")}</Badge>
  );
}

/** Collapsed advanced options with the number changed from the defaults. */
export function Advanced({ title, changed, children }: { title: string; changed: number; children: ReactNode }) {
  const t = useT();
  return (
    <details className="group rounded-lg border px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold">
        <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" aria-hidden />
        {title}
        <span className="font-normal text-muted-foreground">· {changed ? t("assembly.advanced.changed", { count: changed }) : t("assembly.advanced.none")}</span>
      </summary>
      <div className="mt-3 space-y-3">
        <p className="text-xs text-muted-foreground">{t("assembly.advanced.hint")}</p>
        {children}
      </div>
    </details>
  );
}

const supported = (p: FlyePlan | undefined, flag: string) => !!p?.tool.options.includes(flag);

/** "What this run will do", from the current form: nothing here is decided by ARVA. */
function RunSummary({ form, plan, files, ids, advanced }: { form: FlyeForm; plan: FlyePlan | undefined; files: RawFile[]; ids: string[]; advanced: string[] }) {
  const t = useT();
  const chosen = files.filter((f) => ids.includes(f.id));
  const evidence = plan?.files.filter((e) => ids.includes(e.file_id)) ?? [];
  const bases = evidence.length === ids.length && evidence.every((e) => e.total_bases !== null) ? evidence.reduce((n, e) => n + (e.total_bases ?? 0), 0) : null;
  const fileNames = chosen.map((f) => f.original_filename + (f.origin === "derived" ? ` (${t("flye.derived")})` : "")).join(", ");
  const genome = chosenGenomeSize(form, plan);
  const iterations = Number(form.iterations);
  const threads = form.threads.trim() || String(plan?.tool.default_threads ?? "?");
  const basisKey = `assembly.genomeSource.${genome.basis}`;
  const items = [
    t("assembly.summary.assembler", { version: plan?.tool.version ?? "?" }),
    bases !== null ? t("assembly.summary.reads", { count: ids.length, bases: fmtBases(bases), names: fileNames }) : t("assembly.summary.readsNoStats", { count: ids.length, names: fileNames || "—" }),
    form.readType ? t("assembly.summary.readType", { value: form.readType }) : t("assembly.summary.readTypeMissing"),
    genome.bp !== null
      ? t("assembly.summary.genome", { bp: String(genome.bp), basis: basisKey in dictionaries.en ? t(basisKey as TranslationKey) : "" })
      : t("assembly.summary.genomeNone"),
    Number.isInteger(iterations) && iterations > 0 ? t("assembly.summary.polishing", { count: iterations }) : t("assembly.summary.polishingNone"),
    t("assembly.summary.threads", { threads }),
    advanced.length ? t("assembly.summary.advanced", { options: advanced.join(" ") }) : t("assembly.summary.advancedNone"),
    t("assembly.summary.outputs"),
  ];
  return (
    <section className="rounded-lg bg-muted p-3 text-xs" aria-label={t("assembly.summary.title")}>
      <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold">
        <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("assembly.summary.title")}
      </h4>
      <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
        {items.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  );
}

export function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold">{title}</h4>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function ToolLine({ plan }: { plan: FlyePlan }) {
  const t = useT();
  const tool = plan.tool;
  const msg = toolMessage(t, { ...tool, min_version: "2.9" });
  if (tool.status !== "available") {
    return <ErrorNote error={tool.status === "not_installed" ? t("flye.notInstalled") : t("flye.unavailable", { message: msg || tool.status })} />;
  }
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>{t("flye.toolLine", { version: tool.version ?? "?" })}</div>
      {(!tool.version_validated || tool.reason) && msg && (
        <p className={cn("flex gap-1.5", !tool.version_validated && "text-amber-700 dark:text-warning")}>
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {msg}
        </p>
      )}
    </div>
  );
}

export function Evidence({ e }: { e: FlyePlan["files"][number] }) {
  const t = useT();
  const parts: string[] = [];
  if (e.total_bases !== null) {
    parts.push(t("flye.fileStats", { bases: fmtBases(e.total_bases), n50: fmtInt(e.read_n50 ?? 0), max: fmtInt(e.max_read_length ?? 0) }));
    if (e.mean_base_quality !== null) {
      parts.push(t("flye.fileQuality", { error: fmtNum(100 * 10 ** (-e.mean_base_quality / 10), 2), q: fmtNum(e.mean_base_quality, 1) }));
    }
  } else {
    parts.push(t("flye.statsMissing"));
  }
  if (e.header_platform) parts.push(t("flye.headers", { platform: e.header_platform, confidence: e.header_confidence }));
  if (e.basecall_models.length) parts.push(t("flye.models", { models: e.basecall_models.join(", ") }));
  return <div className="mt-0.5 text-xs text-muted-foreground">{parts.join(" · ")}</div>;
}

function Suggestion({ plan, current, onUse }: { plan: FlyePlan; current: FlyeReadType | ""; onUse: (v: FlyeReadType) => void }) {
  const t = useT();
  const s = plan.read_type_suggestion;
  const models = [...new Set(plan.files.flatMap((f) => f.basecall_models))].join(", ");
  const vars = {
    error: s.mean_error_rate !== null ? fmtNum(100 * s.mean_error_rate, 2) : "?",
    q: s.mean_base_quality !== null ? fmtNum(s.mean_base_quality, 1) : "?",
    models,
  };
  const basisKey = `flye.basis.${s.basis}`;
  const sourceKey = `flye.platformSource.${s.platform_source}`;
  return (
    <div className="space-y-1.5 rounded-lg border border-arva-teal/30 bg-arva-teal/5 p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-medium">
          <Lightbulb className="h-3.5 w-3.5 text-arva-teal" aria-hidden />
          {s.value ? t("flye.suggestion.title", { value: `--${s.value}` }) : t("flye.suggestion.none")}
          <Badge tone="warning">{t("flye.heuristic")}</Badge>
        </span>
        {s.value && current !== s.value && (
          <Button size="sm" variant="outline" onClick={() => onUse(s.value!)}>
            {t("flye.suggestion.use")}
          </Button>
        )}
      </div>
      <p>{basisKey in dictionaries.en ? t(basisKey as TranslationKey, vars) : s.basis}</p>
      {sourceKey in dictionaries.en && <p className="text-muted-foreground">{t(sourceKey as TranslationKey)}</p>}
      {s.sup_model_but_low_quality && <p className="text-amber-700 dark:text-warning">{t("flye.suggestion.supLow")}</p>}
      {s.q20_read_error_note && <p>{t("flye.suggestion.q20")}</p>}
      <p className="text-muted-foreground">{t("flye.suggestion.decide")}</p>
    </div>
  );
}

function GenomeSize({ form, plan, set }: { form: FlyeForm; plan: FlyePlan | undefined; set: <K extends keyof FlyeForm>(key: K, value: FlyeForm[K]) => void }) {
  const t = useT();
  const g = plan?.genome_size;
  const expected = g?.expected;
  const chosen = chosenGenomeSize(form, plan);
  const expectedText =
    expected?.status === "given" && expected.bp
      ? t("flye.genome.expected", { size: fmtBp(expected.bp) })
      : expected?.status === "inconsistent"
        ? t("flye.genome.expectedInconsistent")
        : t("flye.genome.expectedMissing");
  const options: { value: GenomeChoice; label: string; disabled?: boolean }[] = [
    { value: "none", label: t("flye.genome.none") },
    { value: "expected", label: expectedText, disabled: !(expected?.status === "given" && expected.bp) },
    { value: "depth", label: t("flye.genome.depth") },
    { value: "entered", label: t("flye.genome.entered") },
  ];
  return (
    <Section title={t("flye.genome.title")} hint={t("flye.genome.explain")}>
      <div role="radiogroup" aria-label={t("flye.genome.title")} className="space-y-1.5">
        {options.map((o) => (
          <label key={o.value} className={cn("flex items-center gap-2 text-xs", o.disabled && "opacity-60")}>
            <input type="radio" name="flye-genome" className="h-4 w-4 accent-[#00B4A6]" checked={form.genomeChoice === o.value} disabled={o.disabled} onChange={() => set("genomeChoice", o.value)} />
            {o.label}
          </label>
        ))}
      </div>
      {form.genomeChoice === "depth" && (
        <div className="space-y-1 pl-6">
          <Field label={t("flye.genome.depthInput")} className="max-w-[12rem]">
            <Input inputMode="decimal" placeholder="50" value={form.depthX} onChange={(e) => set("depthX", e.target.value)} />
          </Field>
          {g && g.files_without_stats.length > 0 ? (
            <p className="text-xs text-amber-700 dark:text-warning">{t("flye.genome.depthNeedsStats", { files: g.files_without_stats.join(", ") })}</p>
          ) : (
            g?.from_depth &&
            chosen.bp !== null && (
              <p className="text-xs text-muted-foreground">
                {t("flye.genome.depthResult", { bases: fmtInt(g.from_depth.total_read_bases), depth: fmtNum(g.from_depth.depth_x, 1), size: fmtBp(g.from_depth.bp) })}
              </p>
            )
          )}
        </div>
      )}
      {form.genomeChoice === "entered" && (
        <Field label={t("flye.genome.enteredInput")} className="max-w-[12rem] pl-6">
          <Input inputMode="decimal" placeholder="2.8" value={form.enteredMbp} onChange={(e) => set("enteredMbp", e.target.value)} />
        </Field>
      )}
      <p className="text-xs text-muted-foreground">
        {chosen.bp !== null ? t("flye.genome.passed", { bp: String(chosen.bp) }) : t("flye.genome.notPassed")}
      </p>
    </Section>
  );
}

