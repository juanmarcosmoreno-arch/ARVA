import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Loader2, Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import {
  ANCHORS,
  NUCMER_DEFAULTS,
  PRESETS,
  type Aligner,
  type AniMethod,
  type ComparisonPlan,
  type ComparisonSet,
  type NucmerSettings,
  type Preset,
} from "@/lib/comparative";
import { fmtBases } from "@/lib/format";
import { messageText, toolMessage } from "@/lib/messages";

const CHECK = "mt-0.5 h-3.5 w-3.5 accent-arva-teal";
export const MAX_ALIGNMENT_GENOMES = 12;

export function PlanSummary({ plan, children }: { plan: ComparisonPlan | undefined; children?: ReactNode }) {
  const t = useT();
  if (!plan) return null;
  const tool = plan.tool;
  return (
    <section className="space-y-2 rounded-lg border bg-muted/30 p-3 text-xs">
      <p>
        {tool.status === "available"
          ? t("comparative.toolLine", { tool: tool.name, version: tool.version ?? "?" })
          : t("comparative.toolMissing", { tool: tool.name, reason: toolMessage(t, { ...tool, min_version: "" }) })}{" "}
        <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">
          {t("annotation.cite")}
        </a>
      </p>
      {plan.dnadiff_tool && (
        <p>{t("comparative.toolLine", { tool: plan.dnadiff_tool.name, version: plan.dnadiff_tool.version ?? "?" })}</p>
      )}
      <p className="break-all font-mono text-[11px] text-muted-foreground">{JSON.stringify(plan.settings)}</p>
      <ul className="space-y-0.5">
        {plan.genomes.map((g) => (
          <li key={g.assembly_id} className="flex flex-wrap gap-x-2">
            <span className="font-medium">{g.label}</span>
            <span className="text-muted-foreground">{g.total_length ? fmtBases(g.total_length) : ""}</span>
            <span className="font-mono text-[10px] text-muted-foreground">sha256 {g.contigs_sha256.slice(0, 16)}…</span>
            {g.synthetic_evidence.length > 0 && <span className="text-amber-700 dark:text-warning">{t("comparative.syntheticGenome")}</span>}
          </li>
        ))}
      </ul>
      {children}
      {plan.problems.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-amber-700 dark:text-warning">
          {plan.problems.map((p, i) => (
            <li key={i}>{messageText(t, "comparative.problem", { code: p.code, params: p.params, text: p.message })}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Footer({ onCancel, onRun, pending, disabled, label }: { onCancel: () => void; onRun: () => void; pending: boolean; disabled: boolean; label: string }) {
  const t = useT();
  return (
    <div className="flex justify-end gap-2">
      <Button variant="outline" onClick={onCancel}>
        {t("common.cancel")}
      </Button>
      <Button onClick={onRun} disabled={disabled || pending}>
        {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
        {label}
      </Button>
    </div>
  );
}

/** ANI of every pair of the set's genomes with skani (default) or FastANI, after the user confirmed the plan. */
export function AniDialog({ open, onOpenChange, set }: { open: boolean; onOpenChange: (o: boolean) => void; set: ComparisonSet }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [method, setMethod] = useState<AniMethod>("skani");
  const [threads, setThreads] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (open) {
      setMethod("skani");
      setThreads(null);
      setConfirmed(false);
    }
  }, [open]);
  const body = { method, threads, confirmed };
  const plan = useQuery({ queryKey: ["aniPlan", set.id, method, threads], queryFn: () => api.aniPreview(set.id, body), enabled: open, retry: false });
  const run = useMutation({
    mutationFn: () => api.runAni(set.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comparison", set.id] });
      onOpenChange(false);
    },
  });
  const p = plan.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("comparative.aniTitle")} description={t("comparative.aniDescription")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        <div className="space-y-1.5 text-xs">
          {(["skani", "fastani"] as AniMethod[]).map((m) => (
            <label key={m} className="flex items-start gap-2">
              <input type="radio" className={CHECK} checked={method === m} onChange={() => { setMethod(m); setConfirmed(false); }} />
              <span>
                <span className="font-medium">{t(`comparative.method.${m}` as TranslationKey)}</span>
                <span className="block text-muted-foreground">{t(`comparative.methodHint.${m}` as TranslationKey)}</span>
              </span>
            </label>
          ))}
        </div>
        <Field label={t("comparative.threads")} hint={p ? t("comparative.threadsHint", { max: p.tool.max_threads }) : undefined}>
          <Input type="number" min={1} max={p?.tool.max_threads ?? 256} value={threads ?? p?.settings.threads ?? ""}
            onChange={(e) => { setThreads(e.target.value ? Number(e.target.value) : null); setConfirmed(false); }} />
        </Field>
        <ErrorNote error={plan.error} />
        <PlanSummary plan={p}>
          {p?.comparisons != null && <p>{t("comparative.comparisons", { n: p.comparisons })}</p>}
        </PlanSummary>
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("comparative.aniNote")}</span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("comparative.confirm")}</span>
        </label>
        <ErrorNote error={run.error} />
        <Footer onCancel={() => onOpenChange(false)} onRun={() => run.mutate()} pending={run.isPending} label={t("comparative.runAni")}
          disabled={!p || p.problems.length > 0 || !confirmed || plan.isFetching} />
      </div>
    </Dialog>
  );
}

/** Whole-genome alignment of up to 12 of the set's genomes in a chosen order (the first is the reference) with
 * minimap2 or NUCmer, and dnadiff of each against the reference. */
export function AlignmentDialog({ open, onOpenChange, set }: { open: boolean; onOpenChange: (o: boolean) => void; set: ComparisonSet }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [aligner, setAligner] = useState<Aligner>("minimap2");
  const [preset, setPreset] = useState<Preset>("asm5");
  const [nucmer, setNucmer] = useState<NucmerSettings>(NUCMER_DEFAULTS);
  const [order, setOrder] = useState<string[]>([]);
  const [dnadiff, setDnadiff] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (open) {
      setAligner("minimap2");
      setPreset("asm5");
      setNucmer(NUCMER_DEFAULTS);
      setOrder(set.members.slice(0, MAX_ALIGNMENT_GENOMES).map((m) => m.assembly_id));
      setDnadiff(true);
      setConfirmed(false);
    }
  }, [open]);
  const body = { aligner, preset, nucmer, order, dnadiff, threads: null, confirmed };
  const plan = useQuery({
    queryKey: ["alignmentPlan", set.id, aligner, preset, nucmer, order, dnadiff],
    queryFn: () => api.alignmentPreview(set.id, body),
    enabled: open && order.length >= 2,
    retry: false,
  });
  const run = useMutation({
    mutationFn: () => api.runAlignment(set.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comparison", set.id] });
      onOpenChange(false);
    },
  });
  const change = (fn: () => void) => {
    fn();
    setConfirmed(false);
  };
  const labels = new Map(set.members.map((m) => [m.assembly_id, m.label]));
  const toggle = (id: string) => change(() => setOrder((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id])));
  const move = (i: number, d: -1 | 1) =>
    change(() => setOrder((o) => {
      const n = [...o];
      [n[i], n[i + d]] = [n[i + d], n[i]];
      return n;
    }));
  const p = plan.data;
  const tooMany = order.length > MAX_ALIGNMENT_GENOMES;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("comparative.alignTitle")} description={t("comparative.alignDescription")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <div className="grid gap-4 md:grid-cols-2">
          <section className="space-y-2">
            <h4 className="text-sm font-semibold">{t("comparative.aligner")}</h4>
            {(["minimap2", "nucmer"] as Aligner[]).map((a) => (
              <label key={a} className="flex items-start gap-2 text-xs">
                <input type="radio" className={CHECK} checked={aligner === a} onChange={() => change(() => setAligner(a))} />
                <span>
                  <span className="font-medium">{t(`comparative.method.${a}` as TranslationKey)}</span>
                  <span className="block text-muted-foreground">{t(`comparative.methodHint.${a}` as TranslationKey)}</span>
                </span>
              </label>
            ))}
            {aligner === "minimap2" ? (
              <Field label={t("comparative.preset")} hint={t("comparative.presetHint")}>
                <Select value={preset} onChange={(e) => change(() => setPreset(e.target.value as Preset))}>
                  {PRESETS.map((x) => (
                    <option key={x} value={x}>
                      {t(`comparative.preset.${x}` as TranslationKey)}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <Field label={t("comparative.anchors")} className="col-span-2">
                  <Select value={nucmer.anchors} onChange={(e) => change(() => setNucmer((n) => ({ ...n, anchors: e.target.value as NucmerSettings["anchors"] })))}>
                    {ANCHORS.map((x) => (
                      <option key={x} value={x}>
                        {t(`comparative.anchor.${x}` as TranslationKey)}
                      </option>
                    ))}
                  </Select>
                </Field>
                {(["breaklen", "mincluster", "maxgap", "minmatch"] as const).map((k) => (
                  <Field key={k} label={`${k} (${NUCMER_DEFAULTS[k]})`}>
                    <Input type="number" min={1} max={100000} value={nucmer[k]} onChange={(e) => change(() => setNucmer((n) => ({ ...n, [k]: Number(e.target.value) })))} />
                  </Field>
                ))}
              </div>
            )}
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className={CHECK} checked={dnadiff} onChange={(e) => change(() => setDnadiff(e.target.checked))} />
              <span>
                <span className="font-medium">{t("comparative.dnadiff")}</span>
                <span className="block text-muted-foreground">{t("comparative.dnadiffHint")}</span>
              </span>
            </label>
          </section>
          <section className="space-y-2">
            <h4 className="text-sm font-semibold">{t("comparative.orderTitle")}</h4>
            <p className="text-xs text-muted-foreground">{t("comparative.alignOrderHint", { max: MAX_ALIGNMENT_GENOMES })}</p>
            <ol className="space-y-1">
              {order.map((id, i) => (
                <li key={id} className="flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs">
                  <span className="w-5 text-right tabular-nums text-muted-foreground">{i + 1}</span>
                  <span className="flex-1 truncate">{labels.get(id)}</span>
                  {i === 0 && <span className="text-[10px] font-medium text-arva-teal">{t("comparative.reference")}</span>}
                  <button className="rounded p-1 hover:bg-muted disabled:opacity-30" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("comparative.moveUp")}>
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button className="rounded p-1 hover:bg-muted disabled:opacity-30" disabled={i === order.length - 1} onClick={() => move(i, 1)} aria-label={t("comparative.moveDown")}>
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-1">
              {set.members.filter((m) => !order.includes(m.assembly_id)).map((m) => (
                <Button key={m.assembly_id} size="sm" variant="outline" onClick={() => toggle(m.assembly_id)}>
                  + {m.label}
                </Button>
              ))}
              {order.length > 2 && (
                <Button size="sm" variant="ghost" onClick={() => toggle(order[order.length - 1])}>
                  {t("comparative.dropLast")}
                </Button>
              )}
            </div>
            {tooMany && <p className="text-xs text-amber-700 dark:text-warning">{t("comparative.tooMany", { max: MAX_ALIGNMENT_GENOMES })}</p>}
          </section>
        </div>
        <ErrorNote error={plan.error} />
        <PlanSummary plan={p}>
          {p && (
            <ul className="list-disc pl-5">
              {p.pairs.map((x) => (
                <li key={`${x.reference}|${x.query}`}>
                  {t(`comparative.pairRole.${x.role}` as TranslationKey, { reference: x.reference, query: x.query })}
                </li>
              ))}
            </ul>
          )}
        </PlanSummary>
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("comparative.alignNote")}</span>
        </p>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("comparative.confirm")}</span>
        </label>
        <ErrorNote error={run.error} />
        <Footer onCancel={() => onOpenChange(false)} onRun={() => run.mutate()} pending={run.isPending} label={t("comparative.runAlignment")}
          disabled={!p || p.problems.length > 0 || !confirmed || plan.isFetching || tooMany || order.length < 2} />
      </div>
    </Dialog>
  );
}
