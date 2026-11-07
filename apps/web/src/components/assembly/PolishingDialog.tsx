import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Lightbulb, Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { useTool } from "@/components/tools/useTools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { assemblyLabel, canPolish } from "@/lib/assembly";
import { fmtBases, fmtInt, technologyLabel } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import {
  MAX_ROUNDS,
  MEDAKA_BATCH_DEFAULT,
  PILON_FIXES,
  POLISHING_FORM_DEFAULTS,
  PRESETS,
  STRATEGIES,
  STRATEGY_ROLES,
  changedPilon,
  changedRacon,
  medakaMismatch,
  medakaModel,
  polishingProblems,
  polishingRequest,
  rolesFor,
  strategyForData,
  usesPilon,
  usesRacon,
  type PolishingForm,
} from "@/lib/polishing";
import { referenceCandidates } from "@/lib/quast";
import { NO_ROLES, availableData, defaultRoles, inputsOf, type Roles } from "@/lib/shortReads";
import type { AnalysisJobDetail, Assembly, PolishingPlan, PolishingStrategy, PolishingToolId, RawFile, ReadRole, SequencingTechnology } from "@/lib/types";
import { Advanced, CHECK, Section } from "./FlyePanel";
import { Choice, RolePicker } from "./ShortReadPanels";

const STRATEGY_TOOLS: Record<PolishingStrategy, PolishingToolId[]> = {
  racon: ["racon", "minimap2", "samtools"],
  medaka: ["medaka", "minimap2", "samtools"],
  pilon: ["pilon", "java", "bwa", "samtools"],
  hybrid: ["racon", "minimap2", "pilon", "java", "bwa", "samtools"],
};

/** Polishes one of the sample's assemblies: the strategy follows the reads (long → Racon or, for Oxford Nanopore
 * reads, Medaka; short → Pilon; both → Racon then Pilon), every setting is explained and sent explicitly, and the run
 * is summarised before it starts. */
export function PolishingDialog({
  open,
  onOpenChange,
  sampleId,
  technology,
  assemblies: all,
  files,
  jobs,
  draftId: initialDraft,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  technology: SequencingTechnology;
  assemblies: Assembly[];
  files: RawFile[];
  jobs: AnalysisJobDetail[];
  draftId?: string | null;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  // A genome registered as finished is never polished; a draft declared as assembled from this sample's reads is.
  const assemblies = all.filter(canPolish);
  const [draftId, setDraftId] = useState("");
  const [form, setForm] = useState<PolishingForm>(POLISHING_FORM_DEFAULTS);
  const [roles, setRoles] = useState<Roles>(NO_ROLES);
  const [confirmed, setConfirmed] = useState(false);
  const data = availableData(files, technology);
  useEffect(() => {
    if (!open) return;
    const strategy = strategyForData(data) ?? "racon";
    setDraftId(initialDraft ?? assemblies[0]?.id ?? "");
    setForm({ ...POLISHING_FORM_DEFAULTS, strategy });
    setRoles(rolesFor(strategy, defaultRoles(files, true)));
    setConfirmed(false);
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);

  const used = rolesFor(form.strategy, roles);
  const plan = useQuery({
    queryKey: ["polishingPlan", draftId, used, form.preset],
    queryFn: () => api.polishingPreview(draftId, { inputs: inputsOf(used), read_type: form.preset || null }),
    enabled: open && !!draftId,
    retry: false,
  });
  const p = plan.data;
  const problems = polishingProblems(form, roles, p, confirmed);
  const run = useMutation({
    mutationFn: () => api.polish(draftId, polishingRequest(form, roles, confirmed)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      onOpenChange(false);
    },
  });
  const set = <K extends keyof PolishingForm>(key: K, value: PolishingForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const setStrategy = (s: PolishingStrategy) => {
    set("strategy", s);
    setRoles((r) => ({ ...defaultRoles(files, true), ...Object.fromEntries(Object.entries(r).filter(([, v]) => v)) }));
  };
  const usesLong = usesRacon(form.strategy);
  const usesShort = usesPilon(form.strategy);
  const suggested = p?.suggested_strategy ?? strategyForData(data);
  const references = referenceCandidates(files);
  const quastTool = useTool("quast");

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("polishing.title")} description={t("polishing.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        <Section title={t("polishing.draft")} hint={t("polishing.draftHint")} action={<Explain id="polishing" compact />}>
          <Select value={draftId} onChange={(e) => setDraftId(e.target.value)} aria-label={t("polishing.draft")}>
            {assemblies.map((a) => (
              <option key={a.id} value={a.id}>
                {assemblyLabel(t, a)}
                {a.kind === "polished" ? ` (${t("polishing.polishedTag")})` : ""} · {fmtInt(a.stats.contig_count)} contigs · {fmtBases(a.stats.total_length)}
              </option>
            ))}
          </Select>
        </Section>

        <Section title={t("polishing.strategy")} hint={t("polishing.strategyHint")}>
          <Choice<PolishingStrategy>
            name="polishing-strategy"
            label={t("polishing.strategy")}
            value={form.strategy}
            onChange={setStrategy}
            options={STRATEGIES.map((s) => ({
              value: s,
              label: t(`polishing.strategy.${s}`),
              hint: t(`polishing.strategyHint.${s}`),
              badge: s === suggested ? t("polishing.suggested") : undefined,
            }))}
          />
          <p className="text-xs text-muted-foreground">{t("polishing.strategyBasis", { technology: technologyLabel(technology) })}</p>
          {p && <Tools plan={p} strategy={form.strategy} />}
        </Section>

        <Section title={t("polishing.reads")} hint={t("polishing.readsHint")}>
          <RolePicker
            roles={used}
            setRole={(role: ReadRole, id: string) => setRoles((r) => ({ ...r, [role]: id }))}
            shown={STRATEGY_ROLES[form.strategy]}
            files={files}
            jobs={jobs}
            evidence={p?.files ?? []}
          />
          {plan.isFetching && <p className="text-xs text-muted-foreground">{t("quast.checking")}</p>}
          <ErrorNote error={plan.error} />
          {(form.strategy === "medaka" ? p?.medaka?.problem : p?.problem) && (
            <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {form.strategy === "medaka" ? p?.medaka?.problem : p?.problem}
            </p>
          )}
        </Section>

        {form.strategy === "medaka" && <MedakaSection form={form} set={set} plan={p} />}

        {usesLong && (
          <Section title={t("polishing.racon.title")} hint={t("polishing.racon.hint")} action={<Explain id="racon" compact />}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("polishing.preset")} hint={t("polishing.presetHint")}>
                <Select value={form.preset} onChange={(e) => set("preset", e.target.value as PolishingForm["preset"])} aria-label={t("polishing.preset")}>
                  <option value="">{t("polishing.presetChoose")}</option>
                  {PRESETS.map((x) => (
                    <option key={x} value={x}>
                      {x} — {t(`polishing.preset.${x}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("polishing.rounds")} hint={t("polishing.racon.roundsHint")}>
                <Input type="number" min={1} max={MAX_ROUNDS} value={form.raconRounds} onChange={(e) => set("raconRounds", e.target.value)} />
              </Field>
            </div>
            {p?.preset_suggestion && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-arva-teal/30 bg-arva-teal/5 p-2.5 text-xs">
                <span className="flex items-center gap-1.5">
                  <Lightbulb className="h-3.5 w-3.5 text-arva-teal" aria-hidden />
                  {p.preset_suggestion.value ? t("polishing.presetSuggested", { preset: p.preset_suggestion.value }) : t("polishing.presetNoSuggestion")}
                  <Badge tone="warning">{t("flye.heuristic")}</Badge>
                </span>
                {p.preset_suggestion.value && form.preset !== p.preset_suggestion.value && (
                  <Button size="sm" variant="outline" onClick={() => set("preset", p.preset_suggestion.value!)}>
                    {t("flye.suggestion.use")}
                  </Button>
                )}
              </div>
            )}
            <Advanced title={t("polishing.racon.advanced")} tool="Racon" changed={changedRacon(form)}>
              <div className="grid gap-3 sm:grid-cols-3">
                {(
                  [
                    ["match", "-m"],
                    ["mismatch", "-x"],
                    ["gap", "-g"],
                    ["window", "-w"],
                    ["quality", "-q"],
                    ["error", "-e"],
                  ] as const
                ).map(([key, flag]) => (
                  <Field key={key} label={`${t(`polishing.racon.${key}`)} (${flag})`} hint={t(`polishing.racon.${key}Hint`)}>
                    <Input type="number" step="any" value={form[key]} onChange={(e) => set(key, e.target.value)} />
                  </Field>
                ))}
              </div>
            </Advanced>
            <p className="text-xs text-muted-foreground">{t("polishing.racon.fixed")}</p>
            <p className="flex gap-1.5 rounded-lg bg-muted p-2.5 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("polishing.medakaAlternative")}
            </p>
          </Section>
        )}

        {usesShort && (
          <Section title={t("polishing.pilon.title")} hint={t("polishing.pilon.hint")} action={<Explain id="pilon" compact />}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("polishing.rounds")} hint={t("polishing.pilon.roundsHint")}>
                <Input type="number" min={1} max={MAX_ROUNDS} value={form.pilonRounds} onChange={(e) => set("pilonRounds", e.target.value)} />
              </Field>
              <Field label={t("polishing.heap")} hint={t("polishing.heapHint", { default: p?.default_heap_gb ?? "?", max: p?.max_memory_gb ?? "?" })}>
                <Input type="number" min={1} max={p?.max_memory_gb} placeholder={String(p?.default_heap_gb ?? "")} value={form.heap} onChange={(e) => set("heap", e.target.value)} />
              </Field>
            </div>
            {p && p.default_heap_gb < (p.pilon_documented_min_gb ?? 8) && (
              <p role="note" className="flex gap-1.5 rounded-lg bg-warning/10 p-2.5 text-xs text-amber-800 dark:text-warning">
                <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("polishing.heapBelowDocumented", { min: p.pilon_documented_min_gb ?? 8, max: p.max_memory_gb })}
              </p>
            )}
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className={CHECK} checked={form.stopWhenUnchanged} onChange={(e) => set("stopWhenUnchanged", e.target.checked)} />
              <span>
                {t("polishing.stopWhenUnchanged")}
                <span className="block text-muted-foreground">{t("polishing.stopHint")}</span>
              </span>
            </label>
            <fieldset className="space-y-1.5">
              <legend className="text-xs font-medium">{t("polishing.fix")}</legend>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {PILON_FIXES.map((f) => (
                  <label key={f} className="flex items-start gap-2 text-xs">
                    <input
                      type="checkbox"
                      className={CHECK}
                      checked={form.fix.includes(f)}
                      onChange={(e) => set("fix", e.target.checked ? [...form.fix, f] : form.fix.filter((x) => x !== f))}
                    />
                    <span>
                      <code>{f}</code> — {t(`polishing.fix.${f}`)}
                    </span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{t("polishing.fixHint")}</p>
            </fieldset>
            <Advanced title={t("polishing.pilon.advanced")} tool="Pilon" changed={changedPilon(form)}>
              <div className="grid gap-3 sm:grid-cols-3">
                {(["mindepth", "minmq", "minqual"] as const).map((key) => (
                  <Field key={key} label={`--${key}`} hint={t(`polishing.pilon.${key}Hint`)}>
                    <Input type="number" step="any" value={form[key]} onChange={(e) => set(key, e.target.value)} />
                  </Field>
                ))}
              </div>
            </Advanced>
            <p className="text-xs text-muted-foreground">{t("polishing.pilon.fixed")}</p>
          </Section>
        )}

        <Section title={t("polishing.compare.title")} hint={t("polishing.compare.hint")} action={<Explain id="polishing_evidence" compact />}>
          {p && p.tools.dnadiff.status !== "available" && (
            <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("polishing.dnadiffMissing")}
            </p>
          )}
          <label className="flex items-start gap-2 text-xs">
            <input type="checkbox" className={CHECK} checked={form.quast} disabled={quastTool?.status !== "available"} onChange={(e) => set("quast", e.target.checked)} />
            <span>
              {t("polishing.quast")}
              <span className="block text-muted-foreground">{quastTool?.status === "available" ? t("polishing.quastHint") : t("polishing.quastUnavailable")}</span>
            </span>
          </label>
          {form.quast && (
            <Select value={form.referenceId} onChange={(e) => set("referenceId", e.target.value)} aria-label={t("quast.reference")}>
              <option value="">{t("quast.noReference")}</option>
              {references.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.original_filename}
                </option>
              ))}
            </Select>
          )}
          <Field label={t("polishing.threads")} hint={t("polishing.threadsHint", { max: p?.max_threads ?? "?", default: p?.default_threads ?? "?" })}>
            <Input type="number" min={1} max={p?.max_threads} placeholder={String(p?.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
          </Field>
        </Section>

        {p?.confirmation_required && (
          <label className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
            <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            <span>
              {t("shortReads.confirm")}
              <span className="block text-muted-foreground">{t("shortReads.confirmHint", { technology: technologyLabel(p.sample_technology) })}</span>
            </span>
          </label>
        )}

        <Summary form={form} plan={p} />
        {problems.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{t(k, { max: p?.max_threads ?? "?", maxMemory: p?.max_memory_gb ?? "?", rounds: MAX_ROUNDS })}</li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!draftId || problems.length > 0 || plan.isError || plan.isFetching || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("polishing.starting") : t("polishing.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The tools the chosen strategy runs, with their versions, or why one cannot run. */
function Tools({ plan, strategy }: { plan: PolishingPlan; strategy: PolishingStrategy }) {
  const t = useT();
  return (
    <ul className="space-y-0.5 text-xs text-muted-foreground" aria-label={t("polishing.tools")}>
      {[...STRATEGY_TOOLS[strategy], "dnadiff" as const].map((id) => {
        const tool = plan.tools[id];
        const ok = tool.status === "available";
        const msg = toolMessage(t, { ...tool, min_version: "" });
        return (
          <li key={id} className={ok ? "" : "text-amber-700 dark:text-warning"}>
            {ok ? t("polishing.toolLine", { tool: id, version: tool.version ?? "?" }) : t("polishing.toolMissing", { tool: id, message: msg || tool.status })}
            {ok && tool.reason && msg ? ` — ${msg}` : ""}
            {id === "dnadiff" ? ` (${t("polishing.optional")})` : ""}
          </li>
        );
      })}
    </ul>
  );
}

function Summary({ form, plan }: { form: PolishingForm; plan: PolishingPlan | undefined }) {
  const t = useT();
  const items = [t(`polishing.summary.${form.strategy}`)];
  if (usesRacon(form.strategy)) items.push(t("polishing.summary.racon_rounds", { rounds: form.raconRounds, preset: form.preset || "?" }));
  if (form.strategy === "medaka") items.push(t("polishing.summary.medaka_model", { model: medakaModel(form, plan) ?? "?", batch: form.medakaBatch }));
  if (usesPilon(form.strategy))
    items.push(
      t("polishing.summary.pilon_rounds", {
        rounds: form.pilonRounds,
        fix: PILON_FIXES.filter((f) => form.fix.includes(f)).join(","),
        heap: form.heap || plan?.default_heap_gb || "?",
      }),
    );
  items.push(t("polishing.summary.comparison"), t("polishing.summary.result"));
  if (form.quast) items.push(t("polishing.summary.quast"));
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

/** Medaka's model and batch size. The model is medaka's own choice for the reads' basecall model (medaka/options.py)
 * when ARVA read one from their headers and the package ships it; otherwise the user picks one of the shipped
 * models or of the models registered in the Database Manager (R9.4.1 and others; passed as -m <file>), and a choice
 * that differs from medaka's mapping must be confirmed. ARVA never guesses one, and never picks a registered one. */
function MedakaSection({ form, set, plan }: { form: PolishingForm; set: <K extends keyof PolishingForm>(key: K, value: PolishingForm[K]) => void; plan: PolishingPlan | undefined }) {
  const t = useT();
  const m = plan?.medaka;
  const s = m?.suggestion ?? null;
  const mapped = s?.status === "mapped" ? s.model : null;
  const registered = m?.registered ?? [];
  const chosen = registered.find((r) => r.model === form.medakaModel);
  return (
    <Section title={t("polishing.medaka.title")} hint={t("polishing.medaka.hint")} action={<Explain id="medaka" compact />}>
      {m && !m.available && (
        <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("polishing.medaka.unavailable", { error: m.error ?? "" })}
        </p>
      )}
      {s && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-arva-teal/30 bg-arva-teal/5 p-2.5 text-xs" role="note">
          <span className="flex items-center gap-1.5">
            <Lightbulb className="h-3.5 w-3.5 text-arva-teal" aria-hidden />
            {t(`polishing.medaka.suggestion.${s.status}`, { basecall: s.basecall_model ?? "", models: s.basecall_models.join(", "), model: s.model ?? "" })}
          </span>
          {mapped && form.medakaModel && form.medakaModel !== mapped && (
            <Button size="sm" variant="outline" onClick={() => set("medakaModel", "")}>
              {t("flye.suggestion.use")}
            </Button>
          )}
          {s.status === "mapped_registered" && s.model && form.medakaModel !== s.model && (
            <Button size="sm" variant="outline" onClick={() => set("medakaModel", s.model ?? "")}>
              {t("polishing.medaka.chooseRegistered", { model: s.model })}
            </Button>
          )}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("polishing.medaka.model")} hint={t("polishing.medaka.modelHint")}>
          <Select value={form.medakaModel} onChange={(e) => set("medakaModel", e.target.value)} aria-label={t("polishing.medaka.model")}>
            <option value="">{mapped ? t("polishing.medaka.modelFromReads", { model: mapped }) : t("polishing.presetChoose")}</option>
            <optgroup label={t("polishing.medaka.shippedGroup")}>
              {(m?.models ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                  {name === m?.default_model ? ` (${t("polishing.medaka.medakaDefault")})` : ""}
                </option>
              ))}
            </optgroup>
            {registered.length > 0 && (
              <optgroup label={t("polishing.medaka.registeredGroup")}>
                {registered.map((r) => (
                  <option key={r.database_id} value={r.model}>
                    {t("polishing.medaka.registeredOption", { model: r.model, chemistry: r.chemistry ?? "?", basecaller: r.basecaller ?? "?" })}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
        </Field>
        <Field label={t("polishing.medaka.batch")} hint={t("polishing.medaka.batchHint", { default: m?.default_batch_size ?? MEDAKA_BATCH_DEFAULT })}>
          <Input type="number" min={1} max={1000} value={form.medakaBatch} onChange={(e) => set("medakaBatch", e.target.value)} />
        </Field>
      </div>
      {medakaMismatch(form, plan) && (
        <label className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
          <input type="checkbox" className={CHECK} checked={form.medakaAcceptMismatch} onChange={(e) => set("medakaAcceptMismatch", e.target.checked)} />
          <span>
            {t("polishing.medaka.mismatch", { model: form.medakaModel, expected: s?.model ?? "", basecall: s?.basecall_model ?? "" })}
            <span className="block text-muted-foreground">{t("polishing.medaka.mismatchHint")}</span>
          </span>
        </label>
      )}
      {m && !m.draft_is_flye && (
        <p role="note" className="flex gap-1.5 rounded-lg bg-warning/10 p-2.5 text-xs text-amber-800 dark:text-warning">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />{" "}
          {plan?.draft.declared_assembler
            ? t("polishing.medaka.declaredDraft", { assembler: plan.draft.declared_assembler, version: plan.draft.declared_assembler_version ?? "?" })
            : t("polishing.medaka.notFlye")}
        </p>
      )}
      {chosen && (
        <p className="text-xs text-muted-foreground" role="note">
          {t("polishing.medaka.registeredChosen", { model: chosen.model, chemistry: chosen.chemistry ?? "?", basecaller: chosen.basecaller ?? "?", sha256: chosen.sha256.slice(0, 12) })}
        </p>
      )}
      <p role="note" className="flex gap-1.5 rounded-lg bg-muted p-2.5 text-xs text-muted-foreground">
        <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("polishing.medaka.guidance")}
      </p>
      <p className="text-xs text-muted-foreground">{t("polishing.medaka.models", { models: (m?.models ?? []).join(", ") || "—", version: m?.version ?? "?" })}</p>
      <p className="text-xs text-muted-foreground">
        {registered.length > 0 ? t("polishing.medaka.registeredModels", { models: registered.map((r) => r.model).join(", ") }) : t("polishing.medaka.noRegistered")}
      </p>
      <p className="text-xs text-muted-foreground">{t("polishing.medaka.fixed")}</p>
    </Section>
  );
}
