import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtInt, technologyLabel } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import {
  NO_ROLES,
  SPADES_FORM_DEFAULTS,
  UNICYCLER_FORM_DEFAULTS,
  defaultRoles,
  hasShort,
  longCandidates,
  shortCandidates,
  spadesProblems,
  spadesRequest,
  unicyclerMode,
  unicyclerProblems,
  unicyclerRequest,
  type Roles,
  type SpadesForm,
  type UnicyclerForm,
} from "@/lib/shortReads";
import type { AnalysisJobDetail, AssemblyFileEvidence, AssemblyToolInfo, RawFile, ReadRole, ShortReadPlan, SpadesMode, UnicyclerBridging } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Advanced, CHECK, Evidence, OriginBadge, type ReportPanel, Section } from "./FlyePanel";

const ROLE_LABEL: Record<ReadRole, TranslationKey> = {
  r1: "shortReads.role.r1",
  r2: "shortReads.role.r2",
  unpaired: "shortReads.role.unpaired",
  long: "shortReads.role.long",
};

/** The installed tool and its version, or why it cannot run. */
function ToolStatusLine({ tool, name, minVersion, installHint }: { tool: AssemblyToolInfo; name: string; minVersion: string; installHint: string }) {
  const t = useT();
  const msg = toolMessage(t, { ...tool, min_version: minVersion });
  if (tool.status !== "available") {
    return <ErrorNote error={tool.status === "not_installed" ? t("shortReads.notInstalled", { tool: name, install: installHint }) : t("shortReads.unavailable", { tool: name, message: msg || tool.status })} />;
  }
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>{t("shortReads.toolLine", { tool: name, version: tool.version ?? "?" })}</div>
      {(!tool.version_validated || tool.reason) && msg && (
        <p className={cn("flex gap-1.5", !tool.version_validated && "text-amber-700 dark:text-warning")}>
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {msg}
        </p>
      )}
    </div>
  );
}

/** One select per role, each listing the files that can play it (originals and filtered copies), with ARVA's
 * evidence for the chosen file. */
export function RolePicker({
  roles,
  setRole,
  shown,
  files,
  jobs,
  evidence,
}: {
  roles: Roles;
  setRole: (role: ReadRole, id: string) => void;
  shown: ReadRole[];
  files: RawFile[];
  jobs: AnalysisJobDetail[];
  evidence: AssemblyFileEvidence[];
}) {
  const t = useT();
  const producedBy = new Map(jobs.map((j) => [j.id, `${j.tool_name} ${j.tool_version}`]));
  const byId = new Map(files.map((f) => [f.id, f]));
  return (
    <ul className="divide-y rounded-lg border" aria-label={t("shortReads.rolesLabel")}>
      {shown.map((role) => {
        const options = role === "long" ? longCandidates(files) : shortCandidates(files);
        const f = roles[role] ? byId.get(roles[role]) : undefined;
        const e = evidence.find((x) => x.role === role);
        return (
          <li key={role} className="grid gap-2 px-3 py-2 sm:grid-cols-[11rem_1fr] sm:items-start">
            <label htmlFor={`role-${role}`} className="pt-1.5 text-xs font-medium">
              {t(ROLE_LABEL[role])}
            </label>
            <div className="min-w-0 space-y-1">
              <Select id={`role-${role}`} value={roles[role]} onChange={(ev) => setRole(role, ev.target.value)} aria-label={t(ROLE_LABEL[role])}>
                <option value="">{t("shortReads.role.none")}</option>
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.original_filename}
                    {o.origin === "derived" ? ` (${t("flye.derived")})` : ""}
                  </option>
                ))}
              </Select>
              {f && (
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <OriginBadge file={f} producedBy={producedBy} />
                  {f.parent_file_id && <span className="text-muted-foreground">{t("assembly.input.from", { name: byId.get(f.parent_file_id)?.original_filename ?? f.parent_file_id })}</span>}
                  {e?.read_count != null && <span className="text-muted-foreground">· {t("shortReads.readCount", { count: fmtInt(e.read_count) })}</span>}
                </div>
              )}
              {e && <Evidence e={e} />}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function Choice<T extends string>({
  name,
  value,
  options,
  onChange,
  label,
}: {
  name: string;
  value: T;
  options: { value: T; label: string; hint: string; badge?: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="grid gap-2 sm:grid-cols-3">
      {options.map((o) => (
        <label key={o.value} className={cn("flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-xs", value === o.value && "border-arva-teal bg-arva-teal/5")}>
          <input type="radio" name={name} className="mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]" checked={value === o.value} onChange={() => onChange(o.value)} />
          <span>
            <span className="font-medium">{o.label}</span>
            {o.badge && <span className="ml-1 text-arva-teal">· {o.badge}</span>}
            <span className="block text-muted-foreground">{o.hint}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

function ServerProblem({ plan }: { plan: ShortReadPlan | undefined }) {
  if (!plan?.problem) return null;
  return (
    <p role="alert" className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-2 text-xs text-amber-800 dark:text-warning">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {plan.problem}
    </p>
  );
}

function Confirmation({ plan, confirmed, setConfirmed }: { plan: ShortReadPlan | undefined; confirmed: boolean; setConfirmed: (v: boolean) => void }) {
  const t = useT();
  if (!plan?.confirmation_required) return null;
  return (
    <label className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
      <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
      <span>
        {t("shortReads.confirm")}
        <span className="block text-muted-foreground">{t("shortReads.confirmHint", { technology: technologyLabel(plan.sample_technology) })}</span>
      </span>
    </label>
  );
}

function Summary({ items }: { items: string[] }) {
  const t = useT();
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

function readsLine(t: ReturnType<typeof useT>, plan: ShortReadPlan | undefined, roles: Roles, files: RawFile[]): string[] {
  const names = new Map(files.map((f) => [f.id, f.original_filename]));
  return (["r1", "r2", "unpaired", "long"] as const)
    .filter((r) => roles[r])
    .map((r) => {
      const e = plan?.files.find((x) => x.role === r);
      return t("shortReads.summary.role", {
        role: t(ROLE_LABEL[r]),
        name: names.get(roles[r]) ?? roles[r],
        bases: e?.total_bases != null ? fmtBases(e.total_bases) : t("flye.statsMissing"),
      });
    });
}

/** Shared state of the SPAdes and Unicycler panels: roles, preview, confirmation and the report to the dialog. */
function usePanel<P extends ShortReadPlan>(open: boolean, files: RawFile[], withLong: boolean, preview: (roles: Roles) => Promise<P>, key: string) {
  const [roles, setRoles] = useState<Roles>(NO_ROLES);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (!open) return;
    setRoles(defaultRoles(files, withLong));
    setConfirmed(false);
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  const any = hasShort(roles) || !!roles.long;
  const plan = useQuery({ queryKey: [key, roles], queryFn: () => preview(roles), enabled: open && any, retry: false });
  const setRole = (role: ReadRole, id: string) => setRoles((r) => ({ ...r, [role]: id }));
  return { roles, setRole, confirmed, setConfirmed, plan, any };
}

function toolProblems(any: boolean, plan: { isError: boolean; data?: ShortReadPlan }): TranslationKey[] {
  if (!any) return [];
  if (plan.isError || (plan.data && plan.data.tool.status !== "available")) return ["assembly.problem.tool"];
  return plan.data ? [] : ["assembly.problem.checking"];
}

function useReport(report: ReportPanel, assembler: "spades" | "unicycler", problems: string[], request: unknown) {
  const stateKey = JSON.stringify({ problems, request });
  useEffect(() => report(assembler, { problems, request }), [stateKey]);
}

/** SPAdes in the "New assembly" dialog: short reads by role, the mode for bacterial isolates, and every option. */
export function SpadesPanel({ open, sampleId, files, jobs = [], report }: { open: boolean; sampleId: string; files: RawFile[]; jobs?: AnalysisJobDetail[]; report: ReportPanel }) {
  const t = useT();
  const [form, setForm] = useState<SpadesForm>(SPADES_FORM_DEFAULTS);
  useEffect(() => {
    if (open) setForm(SPADES_FORM_DEFAULTS);
  }, [open]);
  const { roles, setRole, confirmed, setConfirmed, plan, any } = usePanel(open, files, false, (r) => api.spadesPreview(sampleId, spadesRequest(form, r, false).inputs), `spadesPlan-${sampleId}`);
  const p = plan.data;
  const keys = [...spadesProblems(form, roles, p, confirmed), ...toolProblems(any, plan)];
  const problems = keys.map((k) => t(k, { max: p?.tool.max_threads ?? "?", maxMemory: p?.tool.max_memory_gb ?? "?", tool: "SPAdes" }));
  const request = problems.length ? null : spadesRequest(form, roles, confirmed);
  useReport(report, "spades", problems, request);
  const set = <K extends keyof SpadesForm>(key: K, value: SpadesForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const changed = Number(form.k.trim() !== "") + Number(form.covCutoff !== "off");
  const memory = form.memory.trim() || String(p?.tool.default_memory_gb ?? "?");

  const modeOptions: { value: SpadesMode; label: string; hint: string; badge?: string }[] = [
    { value: "isolate", label: "--isolate", hint: t("spades.mode.isolate"), badge: t("spades.recommended") },
    { value: "careful", label: "--careful", hint: t("spades.mode.careful") },
    { value: "standard", label: t("spades.mode.standardLabel"), hint: t("spades.mode.standard") },
  ];
  return (
    <div className="space-y-5 text-sm">
      {p && <ToolStatusLine tool={p.tool} name="SPAdes" minVersion="3.14" installHint="apt install spades" />}
      <Section title={t("shortReads.readsTitle")} hint={t("spades.readsHint")}>
        {shortCandidates(files).length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("shortReads.noShortFiles")}</p>
        ) : (
          <RolePicker roles={roles} setRole={setRole} shown={["r1", "r2", "unpaired"]} files={files} jobs={jobs} evidence={p?.files ?? []} />
        )}
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("flye.checking")}</p>}
        <ServerProblem plan={p} />
        <ErrorNote error={plan.error} />
      </Section>

      <Section title={t("spades.modeTitle")} hint={t("spades.modeHint")} action={<Explain id="spades" compact />}>
        <Choice name="spades-mode" label={t("spades.modeTitle")} value={form.mode} options={modeOptions} onChange={(v) => set("mode", v)} />
      </Section>

      <Section title={t("spades.outputTitle")} hint={t("spades.outputHint")}>
        <Choice
          name="spades-output"
          label={t("spades.outputTitle")}
          value={form.output}
          options={[
            { value: "contigs", label: "contigs.fasta", hint: t("spades.output.contigs"), badge: t("spades.default") },
            { value: "scaffolds", label: "scaffolds.fasta", hint: t("spades.output.scaffolds") },
          ]}
          onChange={(v) => set("output", v)}
        />
      </Section>

      <Section title={t("assembly.runSettings")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("flye.threads")} hint={t("shortReads.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
            <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
          </Field>
          <Field label={t("spades.memory")} hint={t("spades.memoryHint", { max: p?.tool.max_memory_gb ?? "?", default: p?.tool.default_memory_gb ?? "?" })}>
            <Input type="number" min={1} max={p?.tool.max_memory_gb} placeholder={String(p?.tool.default_memory_gb ?? "")} value={form.memory} onChange={(e) => set("memory", e.target.value)} />
          </Field>
        </div>
      </Section>

      <Advanced title={t("spades.advancedTitle")} changed={changed}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("spades.k")} hint={t("spades.kHint")}>
            <Input placeholder={t("spades.kAuto")} value={form.k} onChange={(e) => set("k", e.target.value)} />
          </Field>
          <Field label={t("spades.covCutoff")} hint={t("spades.covCutoffHint")}>
            <div className="flex gap-2">
              <Select value={form.covCutoff} onChange={(e) => set("covCutoff", e.target.value as SpadesForm["covCutoff"])} aria-label={t("spades.covCutoff")}>
                <option value="off">off ({t("spades.default")})</option>
                <option value="auto">auto</option>
                <option value="value">{t("spades.covValue")}</option>
              </Select>
              {form.covCutoff === "value" && <Input inputMode="decimal" className="max-w-[7rem]" placeholder="5" value={form.covValue} onChange={(e) => set("covValue", e.target.value)} aria-label={t("spades.covValue")} />}
            </div>
          </Field>
        </div>
      </Advanced>

      <Confirmation plan={p} confirmed={confirmed} setConfirmed={setConfirmed} />
      <Summary
        items={[
          t("spades.summary.assembler", { version: p?.tool.version ?? "?" }),
          ...readsLine(t, p, roles, files),
          t("spades.summary.mode", { mode: form.mode === "standard" ? t("spades.mode.standardLabel") : `--${form.mode}` }),
          form.k.trim() ? t("spades.summary.kGiven", { k: form.k.trim() }) : t("spades.summary.kAuto"),
          t("spades.summary.cov", { value: form.covCutoff === "value" ? form.covValue || "?" : form.covCutoff }),
          t("spades.summary.resources", { threads: form.threads.trim() || String(p?.tool.default_threads ?? "?"), memory }),
          t("spades.summary.output", { file: `${form.output}.fasta` }),
          t("spades.summary.coverage"),
        ]}
      />
    </div>
  );
}

/** Unicycler in the "New assembly" dialog: short reads, long reads or both by role (the roles decide the mode). */
export function UnicyclerPanel({ open, sampleId, files, jobs = [], report }: { open: boolean; sampleId: string; files: RawFile[]; jobs?: AnalysisJobDetail[]; report: ReportPanel }) {
  const t = useT();
  const [form, setForm] = useState<UnicyclerForm>(UNICYCLER_FORM_DEFAULTS);
  useEffect(() => {
    if (open) setForm(UNICYCLER_FORM_DEFAULTS);
  }, [open]);
  const { roles, setRole, confirmed, setConfirmed, plan, any } = usePanel(open, files, true, (r) => api.unicyclerPreview(sampleId, unicyclerRequest(form, r, false).inputs), `unicyclerPlan-${sampleId}`);
  const p = plan.data;
  const short = hasShort(roles);
  const mode = unicyclerMode(roles);
  const keys = [...unicyclerProblems(form, roles, p, confirmed), ...toolProblems(any, plan)];
  const problems = keys.map((k) => t(k, { max: p?.tool.max_threads ?? "?", maxMemory: p?.tool.max_memory_gb ?? "?", tool: "Unicycler", mode: mode ?? "?" }));
  const request = problems.length ? null : unicyclerRequest(form, roles, confirmed);
  useReport(report, "unicycler", problems, request);
  const set = <K extends keyof UnicyclerForm>(key: K, value: UnicyclerForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const d = UNICYCLER_FORM_DEFAULTS;
  const changed = (["keep", "kmers", "depthFilter", "minFastaLength", "linearSeqs"] as const).filter((k) => form[k].trim() !== d[k]).length;
  const helpers = p?.tool.helpers;

  const bridging: { value: UnicyclerBridging; label: string; hint: string; badge?: string }[] = [
    { value: "conservative", label: "conservative", hint: t("unicycler.mode.conservative") },
    { value: "normal", label: "normal", hint: t("unicycler.mode.normal"), badge: t("spades.default") },
    { value: "bold", label: "bold", hint: t("unicycler.mode.bold") },
  ];
  return (
    <div className="space-y-5 text-sm">
      {p && <ToolStatusLine tool={p.tool} name="Unicycler" minVersion="0.5.0" installHint="apt install unicycler" />}
      {helpers && (
        <p className="text-xs text-muted-foreground">
          {t("unicycler.helpers", {
            spades: helpers.spades.path ? `SPAdes ${helpers.spades.version ?? ""}`.trim() : t("unicycler.helperMissing", { name: "SPAdes" }),
            racon: helpers.racon.path ? "Racon" : t("unicycler.helperMissing", { name: "Racon" }),
            blast: helpers.makeblastdb.path && helpers.tblastn.path ? "BLAST+" : t("unicycler.helperMissing", { name: "BLAST+" }),
          })}
        </p>
      )}
      <Section title={t("shortReads.readsTitle")} hint={t("unicycler.readsHint")} action={<Explain id="hybrid_assembly" compact />}>
        <RolePicker roles={roles} setRole={setRole} shown={["r1", "r2", "unpaired", "long"]} files={files} jobs={jobs} evidence={p?.files ?? []} />
        {mode && <p className="text-xs font-medium">{t(`unicycler.modeLine.${mode}`)}</p>}
        {mode === "long" && <p className="text-xs text-muted-foreground">{t("unicycler.longNote")}</p>}
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("flye.checking")}</p>}
        <ServerProblem plan={p} />
        <ErrorNote error={plan.error} />
      </Section>

      <Section title={t("unicycler.bridgingTitle")} hint={t("unicycler.bridgingHint")} action={<Explain id="unicycler" compact />}>
        <Choice name="unicycler-mode" label={t("unicycler.bridgingTitle")} value={form.mode} options={bridging} onChange={(v) => set("mode", v)} />
      </Section>

      <Section title={t("assembly.runSettings")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("flye.threads")} hint={t("shortReads.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
            <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
          </Field>
          {short && (
            <Field label={t("unicycler.spadesMemory")} hint={t("unicycler.spadesMemoryHint", { max: p?.tool.max_memory_gb ?? "?", default: p?.tool.default_memory_gb ?? "?" })}>
              <Input type="number" min={1} max={p?.tool.max_memory_gb} placeholder={String(p?.tool.default_memory_gb ?? "")} value={form.memory} onChange={(e) => set("memory", e.target.value)} />
            </Field>
          )}
        </div>
      </Section>

      <Advanced title={t("unicycler.advancedTitle")} changed={changed}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("unicycler.keep")} hint={t("unicycler.keepHint")}>
            <Select value={form.keep} onChange={(e) => set("keep", e.target.value as UnicyclerForm["keep"])} aria-label={t("unicycler.keep")}>
              <option value="1">1 · {t("unicycler.keep1")}</option>
              <option value="0">0 · {t("unicycler.keep0")}</option>
            </Select>
          </Field>
          <Field label={t("unicycler.minFastaLength")} hint={t("unicycler.minFastaLengthHint")}>
            <Input type="number" min={1} value={form.minFastaLength} onChange={(e) => set("minFastaLength", e.target.value)} />
          </Field>
          <Field label={t("unicycler.linearSeqs")} hint={t("unicycler.linearSeqsHint")}>
            <Input type="number" min={0} value={form.linearSeqs} onChange={(e) => set("linearSeqs", e.target.value)} />
          </Field>
          {short && (
            <Field label={t("unicycler.kmers")} hint={t("unicycler.kmersHint")}>
              <Input placeholder={t("spades.kAuto")} value={form.kmers} onChange={(e) => set("kmers", e.target.value)} />
            </Field>
          )}
          {short && (
            <Field label={t("unicycler.depthFilter")} hint={t("unicycler.depthFilterHint")}>
              <Input inputMode="decimal" value={form.depthFilter} onChange={(e) => set("depthFilter", e.target.value)} />
            </Field>
          )}
        </div>
      </Advanced>

      <Confirmation plan={p} confirmed={confirmed} setConfirmed={setConfirmed} />
      <Summary
        items={[
          t("unicycler.summary.assembler", { version: p?.tool.version ?? "?", mode: mode ? t(`unicycler.modeName.${mode}`) : "?" }),
          ...readsLine(t, p, roles, files),
          t("unicycler.summary.bridging", { mode: form.mode }),
          ...(short ? [form.kmers.trim() ? t("unicycler.summary.kGiven", { k: form.kmers.trim() }) : t("unicycler.summary.kAuto")] : []),
          t("unicycler.summary.resources", {
            threads: form.threads.trim() || String(p?.tool.default_threads ?? "?"),
            memory: short ? t("unicycler.summary.memory", { memory: form.memory.trim() || String(p?.tool.default_memory_gb ?? "?") }) : "",
          }),
          t("unicycler.summary.outputs", { keep: form.keep }),
          t("unicycler.summary.coverage"),
        ]}
      />
    </div>
  );
}
