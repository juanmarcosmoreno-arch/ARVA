import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Footer, PlanSummary } from "@/components/comparative/RunDialogs";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonSet } from "@/lib/comparative";
import { fmtDate } from "@/lib/format";
import type { PhyloRequest, RootMethod, SourceKind, TreeMethod } from "@/lib/phylo";

const CHECK = "mt-0.5 h-3.5 w-3.5 accent-arva-teal";
const IQTREE = { model: "MFP", ufboot: 1000, alrt: 1000, seed: 12345 };
const METHODS: Record<SourceKind, TreeMethod[]> = {
  core_alignment: ["iqtree", "fasttree", "nj"],
  snp_alignment: ["iqtree"],
  family_alignment: ["iqtree", "fasttree", "nj"],
  gene_alignment: ["iqtree", "fasttree", "nj"],
  ani_matrix: ["nj"],
};

/** A tree from one of the set's results (core-genome alignment, its SNPs, a gene family or gene alignment, or an
 * ANI matrix for a distance dendrogram), after the user saw the source, every option and the notes, and confirmed. */
export function PhylogenyDialog({ open, onOpenChange, set, initialFamily }: {
  open: boolean; onOpenChange: (o: boolean) => void; set: ComparisonSet; initialFamily?: { resultId: string; family: string } | null;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const sources = useQuery({ queryKey: ["phyloSources", set.id], queryFn: () => api.phyloSources(set.id), enabled: open });
  const [choice, setChoice] = useState<number>(0);
  const [core, setCore] = useState<"all" | "filtered">("all");
  const [family, setFamily] = useState("");
  const [method, setMethod] = useState<TreeMethod>("iqtree");
  const [iqtree, setIqtree] = useState(IQTREE);
  const [constantSites, setConstantSites] = useState<PhyloRequest["constant_sites"]>("fconst");
  const [distance, setDistance] = useState<PhyloRequest["distance"]>("jc69");
  const [root, setRoot] = useState<RootMethod>("midpoint");
  const [outgroup, setOutgroup] = useState("");
  const [threads, setThreads] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const options = useMemo(() => sources.data ?? [], [sources.data]);
  useEffect(() => {
    if (!open) return;
    setCore("all");
    setIqtree(IQTREE);
    setConstantSites("fconst");
    setDistance("jc69");
    setRoot("midpoint");
    setOutgroup("");
    setThreads(null);
    setConfirmed(false);
    const fam = initialFamily ? options.findIndex((o) => o.kind === "family_alignment" && o.result_id === initialFamily.resultId) : -1;
    const first = fam >= 0 ? fam : Math.max(0, options.findIndex((o) => o.kind === "core_alignment"));
    setChoice(first);
    setFamily(initialFamily?.family ?? "");
    setMethod(METHODS[options[first]?.kind ?? "core_alignment"][0]);
  }, [open, initialFamily, options]);
  const src = options[choice];
  const allowed = src ? METHODS[src.kind] : [];
  const body: PhyloRequest | null = src ? {
    source: { kind: src.kind, result_id: src.result_id, core, family: src.kind === "family_alignment" ? family : null },
    method: allowed.includes(method) ? method : allowed[0],
    iqtree: constantSites === "asc" && src.kind === "snp_alignment" && iqtree.model === "MFP" ? { ...iqtree, model: "GTR+F+G4" } : iqtree,
    constant_sites: constantSites, distance,
    rooting: { method: root, outgroup: root === "outgroup" ? outgroup.split(",").map((x) => x.trim()).filter(Boolean) : [] },
    threads, confirmed,
  } : null;
  const plan = useQuery({
    queryKey: ["phyloPlan", set.id, body && { ...body, confirmed: false }],
    queryFn: () => api.phyloPreview(set.id, body!),
    enabled: open && Boolean(body) && (src?.kind !== "family_alignment" || family.length > 0),
    retry: false,
  });
  const run = useMutation({
    mutationFn: () => api.runPhylogeny(set.id, body!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comparison", set.id] });
      onOpenChange(false);
    },
  });
  const touch = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setConfirmed(false);
  };
  const notes = useMemo(() => {
    if (!body) return [];
    const out: TranslationKey[] = [body.method === "nj" ? "phylo.note.distance" : "phylo.note.ml"];
    if (body.source.kind === "ani_matrix") out.push("phylo.note.ani");
    if (body.source.kind === "family_alignment" || body.source.kind === "gene_alignment") out.push("phylo.note.gene");
    if (body.source.kind === "snp_alignment") out.push("phylo.note.snp");
    out.push("phylo.note.root");
    return out;
  }, [body]);
  const p = plan.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("phylo.title")} description={t("phylo.description")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <ErrorNote error={sources.error} />
        {sources.data && options.length === 0 && <p className="text-xs text-muted-foreground">{t("phylo.noSources")}</p>}
        {src && (
          <>
            <Field label={t("phylo.source")} hint={t(`phylo.sourceHint.${src.kind}` as TranslationKey)}>
              <Select value={choice} onChange={(e) => touch(setChoice)(Number(e.target.value))}>
                {options.map((o, i) => (
                  <option key={`${o.kind}-${o.result_id}`} value={i}>
                    {t(`phylo.sourceKind.${o.kind}` as TranslationKey)} · {o.method} · {fmtDate(o.created_at)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              {(src.kind === "core_alignment" || src.kind === "snp_alignment") && (
                <Field label={t("phylo.core")} hint={t(`phylo.coreHint.${core}` as TranslationKey)}>
                  <Select value={core} onChange={(e) => touch(setCore)(e.target.value as "all" | "filtered")}>
                    {(src.core ?? ["all"]).map((c) => <option key={c} value={c}>{t(`phylo.coreOption.${c}` as TranslationKey)}</option>)}
                  </Select>
                </Field>
              )}
              {src.kind === "family_alignment" && (
                <Field label={t("phylo.family")} hint={t("phylo.familyHint", { n: src.families_total ?? 0 })}>
                  <Input list="phylo-families" value={family} onChange={(e) => touch(setFamily)(e.target.value)} />
                  <datalist id="phylo-families">{(src.families ?? []).map((f) => <option key={f} value={f} />)}</datalist>
                </Field>
              )}
              <Field label={t("phylo.method")} hint={t(`phylo.methodHint.${body!.method}` as TranslationKey)}>
                <Select value={body!.method} onChange={(e) => touch(setMethod)(e.target.value as TreeMethod)}>
                  {allowed.map((m) => <option key={m} value={m}>{t(`phylo.methodName.${m}` as TranslationKey)}</option>)}
                </Select>
              </Field>
              {src.kind === "snp_alignment" && (
                <Field label={t("phylo.constantSites")} hint={t(`phylo.constantHint.${constantSites}` as TranslationKey)}>
                  <Select value={constantSites} onChange={(e) => touch(setConstantSites)(e.target.value as PhyloRequest["constant_sites"])}>
                    {(["fconst", "asc", "none"] as const).map((c) => <option key={c} value={c}>{t(`phylo.constant.${c}` as TranslationKey)}</option>)}
                  </Select>
                </Field>
              )}
              {body!.method === "nj" && src.kind !== "ani_matrix" && (
                <Field label={t("phylo.distance")} hint={t("phylo.distanceHint")}>
                  <Select value={distance} onChange={(e) => touch(setDistance)(e.target.value as PhyloRequest["distance"])}>
                    <option value="jc69">{t("phylo.distanceJc")}</option>
                    <option value="p">{t("phylo.distanceP")}</option>
                  </Select>
                </Field>
              )}
              <Field label={t("phylo.rooting")} hint={t(`phylo.rootingHint.${root}` as TranslationKey)}>
                <Select value={root} onChange={(e) => touch(setRoot)(e.target.value as RootMethod)}>
                  {(["midpoint", "outgroup", "none"] as const).map((r) => <option key={r} value={r}>{t(`phylo.root.${r}` as TranslationKey)}</option>)}
                </Select>
              </Field>
              {root === "outgroup" && (
                <Field label={t("phylo.outgroup")} hint={t("phylo.outgroupHint")}>
                  <Input value={outgroup} onChange={(e) => touch(setOutgroup)(e.target.value)} />
                </Field>
              )}
            </div>
            {body!.method === "iqtree" && (
              <details className="rounded-lg border p-3 text-xs" open={src.kind === "snp_alignment" && constantSites === "asc"}>
                <summary className="cursor-pointer font-medium">{t("phylo.advanced")}</summary>
                <div className="mt-3 grid gap-3 sm:grid-cols-4">
                  <Field label={t("phylo.model")} hint={t("phylo.modelHint")}>
                    <Input value={body!.iqtree.model} onChange={(e) => touch(setIqtree)({ ...iqtree, model: e.target.value })} />
                  </Field>
                  <Field label={t("phylo.ufboot")} hint="-B">
                    <Input type="number" step={1000} value={iqtree.ufboot} onChange={(e) => touch(setIqtree)({ ...iqtree, ufboot: Number(e.target.value) })} />
                  </Field>
                  <Field label={t("phylo.alrt")} hint="--alrt">
                    <Input type="number" step={1000} value={iqtree.alrt} onChange={(e) => touch(setIqtree)({ ...iqtree, alrt: Number(e.target.value) })} />
                  </Field>
                  <Field label={t("phylo.seed")} hint="--seed">
                    <Input type="number" value={iqtree.seed} onChange={(e) => touch(setIqtree)({ ...iqtree, seed: Number(e.target.value) })} />
                  </Field>
                </div>
                <p className="mt-2 text-muted-foreground">{t("phylo.supportHint")}</p>
              </details>
            )}
            {body!.method !== "nj" && (
              <Field label={t("comparative.threads")} hint={p ? t("comparative.threadsHint", { max: p.tool.max_threads }) : undefined}>
                <Input type="number" min={1} max={p?.tool.max_threads ?? 256} value={threads ?? p?.settings.threads ?? ""}
                  onChange={(e) => touch(setThreads)(e.target.value ? Number(e.target.value) : null)} />
              </Field>
            )}
          </>
        )}
        <ErrorNote error={plan.error} />
        <PlanSummary plan={p}>
          {p?.source && (
            <p className="text-muted-foreground">
              {t("phylo.planSource", { leaves: p.source.leaves.length, file: p.source.file?.key ?? "—" })}
            </p>
          )}
        </PlanSummary>
        <ul className="space-y-1 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          {notes.map((k) => (
            <li key={k} className="flex gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
              <span>{t(k)}</span>
            </li>
          ))}
        </ul>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>{t("comparative.confirm")}</span>
        </label>
        <ErrorNote error={run.error} />
        <Footer onCancel={() => onOpenChange(false)} onRun={() => run.mutate()} pending={run.isPending} label={t("phylo.run")}
          disabled={!p || p.problems.length > 0 || !confirmed || plan.isFetching} />
      </div>
    </Dialog>
  );
}
