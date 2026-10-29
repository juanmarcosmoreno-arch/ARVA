import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, Loader2, Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBases, fmtDate, fmtInt } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import { QUAST_DEFAULT_MIN_CONTIG, QUAST_LIMITS, type QuastForm, quastProblems, quastRequest, referenceCandidates } from "@/lib/quast";
import type { Assembly, QuastPlan, RawFile } from "@/lib/types";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

const initialForm = (assemblies: Assembly[]): QuastForm => ({
  selected: assemblies.slice(0, QUAST_LIMITS.maxAssemblies).map((a) => a.id),
  referenceId: "",
  minContig: String(QUAST_DEFAULT_MIN_CONTIG),
  threads: "",
});

/** Explains QUAST's options and what it will leave out, then evaluates (and compares) the chosen assemblies. */
export function QuastDialog({
  open,
  onOpenChange,
  sampleId,
  assemblies,
  files,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sampleId: string;
  assemblies: Assembly[];
  files: RawFile[];
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const references = referenceCandidates(files);
  const [form, setForm] = useState<QuastForm>(() => initialForm(assemblies));
  const [minContig, setMinContig] = useState(QUAST_DEFAULT_MIN_CONTIG);
  useEffect(() => {
    if (!open) return;
    setForm(initialForm(assemblies));
    // Only when the dialog opens: the user's choices are never replaced while it is open.
  }, [open]);
  useEffect(() => {
    const m = Number(form.minContig);
    const timer = setTimeout(() => {
      if (Number.isInteger(m) && m >= QUAST_LIMITS.minContig[0] && m <= QUAST_LIMITS.minContig[1]) setMinContig(m);
    }, 350);
    return () => clearTimeout(timer);
  }, [form.minContig]);

  const ids = form.selected;
  const plan = useQuery({
    queryKey: ["quastPlan", sampleId, ids, form.referenceId, minContig],
    queryFn: () => api.quastPreview(sampleId, { assembly_ids: ids, reference_file_id: form.referenceId || null, min_contig: minContig }),
    enabled: open && ids.length > 0 && ids.length <= QUAST_LIMITS.maxAssemblies,
    retry: false,
  });
  const p = plan.data;
  const problems = quastProblems(form, p);
  const run = useMutation({
    mutationFn: () => api.runQuast(sampleId, quastRequest(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", sampleId] });
      onOpenChange(false);
    },
  });
  const set = <K extends keyof QuastForm>(key: K, value: QuastForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const toggle = (id: string) =>
    set("selected", form.selected.includes(id) ? form.selected.filter((x) => x !== id) : [...form.selected, id]);
  const available = p?.tool.status === "available";
  const stale = p !== undefined && p.min_contig !== Number(form.minContig);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("quast.title")} description={t("quast.description")} className="max-w-3xl">
      <div className="space-y-5 text-sm">
        {p && <ToolLine plan={p} />}

        <Section title={t("quast.assembliesLabel")} hint={t("quast.assembliesHint")} action={<Explain id="quast" compact />}>
          <ul className="divide-y rounded-lg border">
            {assemblies.map((a) => {
              const e = p?.assemblies.find((x) => x.assembly_id === a.id);
              return (
                <li key={a.id} className="flex items-start gap-2.5 px-3 py-2">
                  <input type="checkbox" className={CHECK} checked={form.selected.includes(a.id)} onChange={() => toggle(a.id)} aria-label={`${a.assembler} ${a.assembler_version} ${a.id.slice(0, 8)}`} />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">
                      {e?.label ?? `${a.assembler} ${a.assembler_version} ${a.id.slice(0, 8)}`}{" "}
                      <span className="font-normal text-muted-foreground">· --{a.read_type} · {fmtDate(a.created_at)}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {e
                        ? t("quast.kept", {
                            kept: fmtInt(e.contigs_kept),
                            total: fmtInt(e.contigs),
                            min: fmtInt(p?.min_contig ?? minContig),
                            left: fmtInt(e.contigs_left_out),
                            leftBases: fmtBases(e.length_left_out),
                          })
                        : t("quast.assemblyStats", { contigs: fmtInt(a.stats.contig_count), total: fmtBases(a.stats.total_length) })}
                    </div>
                    {e && e.contigs_kept === 0 && (
                      <p className="flex gap-1.5 text-xs text-amber-700 dark:text-warning">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("quast.nothingKept", { min: fmtInt(minContig) })}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
          {plan.isFetching && <p className="text-xs text-muted-foreground">{t("quast.checking")}</p>}
          <ErrorNote error={plan.error} />
        </Section>

        <Section title={t("quast.reference")} hint={t("quast.referenceHint")}>
          <Select value={form.referenceId} onChange={(e) => set("referenceId", e.target.value)} aria-label={t("quast.reference")}>
            <option value="">{t("quast.noReference")}</option>
            {references.map((f) => (
              <option key={f.id} value={f.id}>
                {f.original_filename}
              </option>
            ))}
          </Select>
          {references.length === 0 && <p className="text-xs text-muted-foreground">{t("quast.noFastaFiles")}</p>}
          {form.referenceId ? (
            <div className="space-y-1 text-xs text-muted-foreground">
              <p>{t("quast.referenceMetrics")}</p>
              <p className="text-amber-700 dark:text-warning">{t("quast.referenceCaution")}</p>
              {p?.tool.aligner && <AlignerLine aligner={p.tool.aligner} />}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t("quast.withoutReference")}</p>
          )}
        </Section>

        <Section title={t("quast.options")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("quast.minContig")} hint={t("quast.minContigHint")}>
              <Input type="number" min={0} max={QUAST_LIMITS.minContig[1]} value={form.minContig} onChange={(e) => set("minContig", e.target.value)} />
            </Field>
            <Field label={t("quast.threads")} hint={t("quast.threadsHint", { max: p?.tool.max_threads ?? "?", default: p?.tool.default_threads ?? "?" })}>
              <Input type="number" min={1} max={p?.tool.max_threads} placeholder={String(p?.tool.default_threads ?? "")} value={form.threads} onChange={(e) => set("threads", e.target.value)} />
            </Field>
          </div>
          <p className="text-xs text-muted-foreground">{t("quast.fixedOptions")}</p>
        </Section>

        <p className="flex gap-1.5 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("quast.whatRuns", { version: p?.tool.version ?? "?" })}
        </p>
        {problems.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {problems.map((k) => (
              <li key={k}>{t(k, { max: p?.tool.max_threads ?? "?", limit: QUAST_LIMITS.maxAssemblies, maxMin: fmtInt(QUAST_LIMITS.minContig[1]) })}</li>
            ))}
          </ul>
        )}
        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => run.mutate()} disabled={!available || problems.length > 0 || plan.isError || stale || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {run.isPending ? t("quast.starting") : t("quast.run")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
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

function ToolLine({ plan }: { plan: QuastPlan }) {
  const t = useT();
  const tool = plan.tool;
  const msg = toolMessage(t, { ...tool, min_version: "5.2.0" });
  if (tool.status !== "available") {
    return <ErrorNote error={tool.status === "not_installed" ? t("quast.notInstalled") : t("quast.unavailable", { message: msg || tool.status })} />;
  }
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <div>{t("quast.toolLine", { version: tool.version ?? "?" })}</div>
      {!tool.version_validated && msg && (
        <p className="flex gap-1.5 text-amber-700 dark:text-warning">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden /> {msg}
        </p>
      )}
    </div>
  );
}

function AlignerLine({ aligner }: { aligner: NonNullable<QuastPlan["tool"]["aligner"]> }) {
  const t = useT();
  if (aligner.provided_by === "missing") {
    return (
      <p className="flex gap-1.5 text-amber-700 dark:text-warning">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {aligner.found ? t("quast.alignerOld", { path: aligner.found, version: aligner.version ?? "?" }) : t("quast.alignerMissing")}
      </p>
    );
  }
  return <p>{t("quast.aligner", { version: aligner.version ?? "?", path: aligner.executable ?? "?" })}</p>;
}
