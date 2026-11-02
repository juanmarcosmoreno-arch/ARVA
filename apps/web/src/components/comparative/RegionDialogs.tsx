import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Loader2, Play, Search, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorNote, Tabs } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonSet } from "@/lib/comparative";
import { fmtBases, fmtBp } from "@/lib/format";
import { messageText, toolMessage } from "@/lib/messages";
import {
  GENE_DEFAULTS,
  MAX_REGION_GENOMES,
  REGION_DEFAULTS,
  TASKS,
  type GeneLookupRow,
  type GeneRequest,
  type RegionAnchorIn,
  type RegionPlan,
  type RegionRequest,
} from "@/lib/regions";

const CHECK = "mt-0.5 h-3.5 w-3.5 accent-arva-teal";
const MAX_FASTA_BYTES = 200_000;

function Num({ label, value, onChange, step, min, max }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number }) {
  return (
    <Field label={label}>
      <Input type="number" value={value} step={step} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} />
    </Field>
  );
}

function Summary({ plan, children }: { plan: RegionPlan | undefined; children?: ReactNode }) {
  const t = useT();
  if (!plan) return null;
  const tools = [plan.tool, ...Object.entries(plan.tools ?? {}).filter(([k]) => k !== "blast").map(([, v]) => v)];
  return (
    <section className="space-y-2 rounded-lg border bg-muted/30 p-3 text-xs">
      {tools.map((tool) => (
        <p key={tool.id}>
          {tool.status === "available" ? t("comparative.toolLine", { tool: tool.name, version: tool.version ?? "?" })
            : t("comparative.toolMissing", { tool: tool.name, reason: toolMessage(t, { ...tool, min_version: "" }) })}{" "}
          <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="text-arva-royal hover:underline dark:text-arva-cyan">{t("annotation.cite")}</a>
        </p>
      ))}
      <p className="font-mono text-[11px] text-muted-foreground">{JSON.stringify(plan.settings)}</p>
      {children}
      <ul className="space-y-0.5">
        {plan.genomes.map((g, i) => (
          <li key={g.assembly_id} className="flex flex-wrap gap-x-2">
            <span className="font-medium">{i + 1}. {g.label}</span>
            {g.locate_by && <span>{t(`region.locateBy.${g.locate_by}` as TranslationKey)}</span>}
            <span className="text-muted-foreground">{g.total_length ? fmtBases(g.total_length) : ""}</span>
            <span className="font-mono text-[10px] text-muted-foreground">sha256 {g.contigs_sha256.slice(0, 16)}…</span>
            {!g.annotation && <span className="text-amber-700 dark:text-warning">{t("region.unannotated")}</span>}
          </li>
        ))}
      </ul>
      {plan.problems.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-amber-700 dark:text-warning">
          {plan.problems.map((p, i) => <li key={i}>{messageText(t, "comparative.problem", { code: p.code, params: p.params, text: p.message })}</li>)}
        </ul>
      )}
      <p className="flex gap-1.5 text-muted-foreground"><AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />{t("region.transferNote")}</p>
    </section>
  );
}

function Run({ onCancel, onRun, pending, disabled, label, confirmed, setConfirmed }: {
  onCancel: () => void; onRun: () => void; pending: boolean; disabled: boolean; label: string; confirmed: boolean; setConfirmed: (v: boolean) => void;
}) {
  const t = useT();
  return (
    <>
      <label className="flex items-start gap-2 text-xs">
        <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span>{t("comparative.confirm")}</span>
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel}>{t("common.cancel")}</Button>
        <Button onClick={onRun} disabled={disabled || pending || !confirmed}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{label}
        </Button>
      </div>
    </>
  );
}

function GeneLookup({ set, onPick, picked }: { set: ComparisonSet; onPick: (r: GeneLookupRow) => void; picked: GeneLookupRow | null }) {
  const t = useT();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const rows = useQuery({ queryKey: ["geneLookup", set.id, query], queryFn: () => api.geneLookup(set.id, query), enabled: query.length >= 2, retry: false });
  return (
    <div className="space-y-2">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(text.trim()); }}>
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("region.lookupPlaceholder")} />
        <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("region.lookup")}</Button>
      </form>
      <ErrorNote error={rows.error} />
      {rows.data && rows.data.length === 0 && <p className="text-xs text-muted-foreground">{t("region.lookupNone")}</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="max-h-48 overflow-y-auto rounded-lg border text-xs">
          {rows.data.map((r) => (
            <label key={`${r.annotation_id}-${r.feature_id}`} className="flex cursor-pointer items-start gap-2 border-b px-2 py-1.5 last:border-b-0 hover:bg-muted/40">
              <input type="radio" className={CHECK} checked={picked?.annotation_id === r.annotation_id && picked.feature_id === r.feature_id} onChange={() => onPick(r)} />
              <span>
                <span className="font-medium">{r.gene ? <i>{r.gene}</i> : r.locus_tag}</span> · {r.label} · {r.product ?? "—"}
                <span className="block text-muted-foreground">{r.locus_tag} · {r.contig}:{r.start.toLocaleString()}–{r.end.toLocaleString()} ({r.strand}) · {r.annotator}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function GenomeOrder({ set, chosen, setChosen, first, max }: { set: ComparisonSet; chosen: string[]; setChosen: (ids: string[]) => void; first?: string | null; max?: number }) {
  const t = useT();
  const ordered = [...(first ? [first] : []), ...chosen.filter((id) => id !== first),
    ...set.members.map((m) => m.assembly_id).filter((id) => !chosen.includes(id) && id !== first)];
  const label = (id: string) => set.members.find((m) => m.assembly_id === id)?.label ?? id;
  const move = (id: string, by: number) => {
    const i = chosen.indexOf(id);
    const next = [...chosen];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setChosen(next);
  };
  return (
    <div className="max-h-56 overflow-y-auto rounded-lg border text-xs">
      {ordered.map((id) => {
        const on = chosen.includes(id);
        const fixed = id === first;
        return (
          <div key={id} className="flex items-center gap-2 border-b px-2 py-1 last:border-b-0">
            <input type="checkbox" className={CHECK} checked={on || fixed} disabled={fixed || (!on && max != null && chosen.length >= max)}
              onChange={(e) => setChosen(e.target.checked ? [...chosen, id] : chosen.filter((x) => x !== id))} aria-label={label(id)} />
            <span className="flex-1">{label(id)}{fixed && <span className="ml-1 text-muted-foreground">{t("region.focusGenome")}</span>}</span>
            {on && !fixed && (
              <>
                <Button size="sm" variant="ghost" onClick={() => move(id, -1)} disabled={chosen.indexOf(id) <= (first ? 1 : 0)} aria-label={t("region.up")}><ArrowUp className="h-3 w-3" /></Button>
                <Button size="sm" variant="ghost" onClick={() => move(id, 1)} disabled={chosen.indexOf(id) === chosen.length - 1} aria-label={t("region.down")}><ArrowDown className="h-3 w-3" /></Button>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

type AnchorMode = "gene" | "hit" | "coordinates";

/** The Region Explorer: a gene (by name, locus tag or product, or an AMR / virulence hit) or coordinates in one genome,
 * a window on each side, and the set's genomes to compare, in track order; the plan is confirmed before it runs. */
export function RegionDialog({ open, onOpenChange, set, initial }: {
  open: boolean; onOpenChange: (o: boolean) => void; set: ComparisonSet; initial?: { anchor: RegionAnchorIn; genomes: string[] } | null;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<AnchorMode>("gene");
  const [picked, setPicked] = useState<GeneLookupRow | null>(null);
  const [hitGenome, setHitGenome] = useState<string>("");
  const [anchor, setAnchor] = useState<RegionAnchorIn | null>(null);
  const [coords, setCoords] = useState({ assembly_id: "", contig: "", start: 1, end: 1000, strand: "+" as "+" | "-" });
  const [flankKb, setFlankKb] = useState(REGION_DEFAULTS.flank / 1000);
  const [genomes, setGenomes] = useState<string[]>([]);
  const [locate, setLocate] = useState(REGION_DEFAULTS.locate);
  const [groups, setGroups] = useState(REGION_DEFAULTS.groups);
  const [links, setLinks] = useState(REGION_DEFAULTS.links);
  const [threads, setThreads] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (!open) return;
    setConfirmed(false);
    if (initial) {
      setMode("coordinates");
      setCoords({ assembly_id: initial.anchor.assembly_id ?? "", contig: initial.anchor.contig ?? "", start: initial.anchor.start ?? 1,
        end: initial.anchor.end ?? 1, strand: initial.anchor.strand ?? "+" });
      setGenomes(initial.genomes.filter((g) => g !== initial.anchor.assembly_id).slice(0, MAX_REGION_GENOMES - 1));
    } else {
      setGenomes(set.members.map((m) => m.assembly_id).slice(0, MAX_REGION_GENOMES));
    }
  }, [open, initial, set.members]);
  const annotated = set.members.filter((m) => m.annotation_id);
  const hitAnnotation = annotated.find((m) => m.assembly_id === hitGenome)?.annotation_id ?? null;
  const amr = useQuery({ queryKey: ["annotationAmr", hitAnnotation], queryFn: () => api.annotationAmr(hitAnnotation!), enabled: open && mode === "hit" && Boolean(hitAnnotation) });
  const vir = useQuery({ queryKey: ["annotationVirulence", hitAnnotation], queryFn: () => api.annotationVirulence(hitAnnotation!), enabled: open && mode === "hit" && Boolean(hitAnnotation) });
  const current: RegionAnchorIn | null = mode === "gene" ? (picked ? { annotation_id: picked.annotation_id, feature_id: picked.feature_id } : null)
    : mode === "hit" ? anchor
    : coords.assembly_id && coords.contig ? coords : null;
  const focus = mode === "gene" ? picked?.assembly_id : mode === "hit" ? hitGenome : coords.assembly_id;
  const body: RegionRequest = { anchor: current ?? {}, genomes: focus ? [focus, ...genomes.filter((g) => g !== focus)] : genomes,
    flank: Math.round(flankKb * 1000), locate, groups, links, threads, confirmed };
  const plan = useQuery({ queryKey: ["regionPlan", set.id, JSON.stringify({ ...body, confirmed: false })], queryFn: () => api.regionPreview(set.id, { ...body, confirmed: false }),
    enabled: open && Boolean(current), retry: false });
  const run = useMutation({
    mutationFn: () => api.runRegion(set.id, body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["comparison", set.id] }); onOpenChange(false); },
  });
  const change = <T,>(setter: (v: T) => void) => (v: T) => { setter(v); setConfirmed(false); };
  const hits = [
    ...(amr.data?.hits ?? []).map((h) => ({ key: `a${h.id}`, kind: "amr" as const, label: h.element_symbol, feature: h.feature?.feature_id ?? null, contig: h.contig, start: h.start ?? 0, end: h.end, strand: h.strand })),
    ...(vir.data?.hits ?? []).map((h) => ({ key: `v${h.id}`, kind: "virulence" as const, label: h.gene, feature: (h as { feature?: { feature_id: number } | null }).feature?.feature_id ?? null, contig: h.contig, start: h.start, end: h.end, strand: h.strand })),
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("region.dialogTitle")} description={t("region.dialogDescription")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <Tabs value={mode} onChange={change(setMode)} items={(["gene", "hit", "coordinates"] as AnchorMode[]).map((m) => ({ value: m, label: t(`region.mode.${m}` as TranslationKey) }))} />
        {mode === "gene" && <GeneLookup set={set} picked={picked} onPick={change(setPicked)} />}
        {mode === "hit" && (
          <div className="space-y-2">
            <Field label={t("region.hitGenome")}>
              <Select value={hitGenome} onChange={(e) => { setHitGenome(e.target.value); setAnchor(null); setConfirmed(false); }}>
                <option value="">—</option>
                {annotated.map((m) => <option key={m.assembly_id} value={m.assembly_id}>{m.label}</option>)}
              </Select>
            </Field>
            {hitAnnotation && hits.length === 0 && !amr.isLoading && !vir.isLoading && <p className="text-xs text-muted-foreground">{t("region.noHits")}</p>}
            <div className="max-h-44 overflow-y-auto text-xs">
              {hits.map((h) => (
                <label key={h.key} className="flex items-center gap-2 py-0.5">
                  <input type="radio" className={CHECK} name="hit" onChange={() => { setConfirmed(false); setAnchor(h.feature != null
                    ? { annotation_id: hitAnnotation, feature_id: h.feature } : { assembly_id: hitGenome, contig: h.contig, start: h.start, end: h.end, strand: h.strand === "-" ? "-" : "+" }); }} />
                  <span className="font-medium">{h.label}</span><span className="text-muted-foreground">{t(`region.mark.${h.kind}` as TranslationKey)} · {h.contig}:{h.start.toLocaleString()}–{h.end.toLocaleString()}</span>
                </label>
              ))}
            </div>
          </div>
        )}
        {mode === "coordinates" && (
          <div className="grid gap-3 sm:grid-cols-5">
            <Field label={t("region.genome")} className="sm:col-span-2">
              <Select value={coords.assembly_id} onChange={(e) => change(setCoords)({ ...coords, assembly_id: e.target.value })}>
                <option value="">—</option>
                {set.members.map((m) => <option key={m.assembly_id} value={m.assembly_id}>{m.label}</option>)}
              </Select>
            </Field>
            <Field label={t("region.contig")} className="sm:col-span-3"><Input value={coords.contig} onChange={(e) => change(setCoords)({ ...coords, contig: e.target.value })} /></Field>
            <Num label={t("region.start")} value={coords.start} min={1} onChange={(v) => change(setCoords)({ ...coords, start: v })} />
            <Num label={t("region.end")} value={coords.end} min={1} onChange={(v) => change(setCoords)({ ...coords, end: v })} />
            <Field label={t("region.strand")}>
              <Select value={coords.strand} onChange={(e) => change(setCoords)({ ...coords, strand: e.target.value as "+" | "-" })}>
                <option value="+">+</option><option value="-">−</option>
              </Select>
            </Field>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
          <Num label={t("region.flank")} value={flankKb} min={1} max={50} step={1} onChange={change(setFlankKb)} />
          <Field label={t("region.genomes", { max: MAX_REGION_GENOMES })}>
            <GenomeOrder set={set} chosen={genomes.filter((g) => g !== focus)} first={focus} max={MAX_REGION_GENOMES - 1}
              setChosen={change((ids: string[]) => setGenomes(ids))} />
          </Field>
        </div>
        <details className="rounded-lg border p-3 text-xs">
          <summary className="cursor-pointer font-medium">{t("region.advanced")}</summary>
          <p className="mt-2 text-muted-foreground">{t("region.advancedHint")}</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-4">
            <Num label={t("region.locateIdentity")} value={locate.min_identity} onChange={(v) => change(setLocate)({ ...locate, min_identity: v })} />
            <Num label={t("region.locateCoverage")} value={locate.min_coverage} onChange={(v) => change(setLocate)({ ...locate, min_coverage: v })} />
            <Field label={t("region.evalue")}><Input value={String(locate.evalue)} onChange={(e) => change(setLocate)({ ...locate, evalue: Number(e.target.value) })} /></Field>
            <Num label={t("comparative.threads")} value={threads ?? plan.data?.settings.threads ?? 1} min={1} onChange={change(setThreads)} />
            <Num label={t("region.groupIdentity")} value={groups.min_identity} onChange={(v) => change(setGroups)({ ...groups, min_identity: v })} />
            <Num label={t("region.groupCoverage")} value={groups.min_coverage} onChange={(v) => change(setGroups)({ ...groups, min_coverage: v })} />
            <Num label={t("region.linkIdentity")} value={links.min_identity} onChange={(v) => change(setLinks)({ ...links, min_identity: v })} />
            <Num label={t("region.linkLength")} value={links.min_length} onChange={(v) => change(setLinks)({ ...links, min_length: v })} />
          </div>
        </details>
        {!current && <p className="text-xs text-muted-foreground">{t("region.chooseAnchor")}</p>}
        <ErrorNote error={plan.error} />
        <Summary plan={plan.data}>
          {plan.data?.anchor && (
            <p>{t("region.anchorLine", { gene: plan.data.anchor.gene ?? plan.data.anchor.locus_tag ?? "—", contig: plan.data.anchor.contig,
              start: plan.data.anchor.start, end: plan.data.anchor.end, strand: plan.data.anchor.strand })}
              {plan.data.anchor.note === "not_latest_annotation" && <span className="ml-1 text-amber-700 dark:text-warning">{t("region.notLatest")}</span>}</p>
          )}
        </Summary>
        <ErrorNote error={run.error} />
        <Run onCancel={() => onOpenChange(false)} onRun={() => run.mutate()} pending={run.isPending} label={t("region.run")}
          disabled={!plan.data || plan.data.problems.length > 0 || plan.isFetching} confirmed={confirmed} setConfirmed={setConfirmed} />
      </div>
    </Dialog>
  );
}

type QuerySource = "saved" | "fasta" | "gene";

/** Custom Gene Investigation: a query (saved, pasted or uploaded FASTA, or an annotated gene), the genomes, explicit
 * thresholds, and optional MAFFT alignment and gene tree; the plan is confirmed before it runs. */
export function GeneDialog({ open, onOpenChange, set }: { open: boolean; onOpenChange: (o: boolean) => void; set: ComparisonSet }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [source, setSource] = useState<QuerySource>("saved");
  const [queryId, setQueryId] = useState<string>("");
  const [fasta, setFasta] = useState({ name: "", molecule: "protein" as "nucleotide" | "protein", text: "", from: "paste" as "paste" | "upload" });
  const [picked, setPicked] = useState<GeneLookupRow | null>(null);
  const [pickedMolecule, setPickedMolecule] = useState<"nucleotide" | "protein">("protein");
  const [genomes, setGenomes] = useState<string[]>([]);
  const [opts, setOpts] = useState(GENE_DEFAULTS);
  const [threads, setThreads] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setGenomes(set.members.map((m) => m.assembly_id));
      setConfirmed(false);
    }
  }, [open, set.members]);
  const queries = useQuery({ queryKey: ["geneQueries"], queryFn: () => api.geneQueries(), enabled: open });
  const saved = queries.data?.find((q) => q.id === queryId);
  const afterSave = (q: { id: string }) => {
    queryClient.invalidateQueries({ queryKey: ["geneQueries"] });
    setQueryId(q.id);
    setSource("saved");
    setConfirmed(false);
  };
  const saveFasta = useMutation({ mutationFn: () => api.createGeneQuery({ name: fasta.name || null, description: null, molecule: fasta.molecule, fasta: fasta.text, source: fasta.from }), onSuccess: afterSave });
  const saveFeature = useMutation({ mutationFn: () => api.geneQueryFromFeature({ annotation_id: picked!.annotation_id, feature_id: picked!.feature_id, molecule: pickedMolecule, name: null }), onSuccess: afterSave });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteGeneQuery(id), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["geneQueries"] }); setQueryId(""); } });
  const body: GeneRequest = { query_id: queryId, genomes, threads, confirmed, ...opts };
  const plan = useQuery({ queryKey: ["genePlan", set.id, JSON.stringify({ ...body, confirmed: false })], queryFn: () => api.genePreview(set.id, { ...body, confirmed: false }),
    enabled: open && Boolean(queryId) && genomes.length > 0, retry: false });
  const run = useMutation({
    mutationFn: () => api.runGene(set.id, body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["comparison", set.id] }); onOpenChange(false); },
  });
  const set_ = (patch: Partial<typeof opts>) => { setOpts({ ...opts, ...patch }); setConfirmed(false); };
  const program = saved?.molecule === "nucleotide" ? "blastn" : "tblastn";
  const readFile = (file: File | undefined) => {
    setFileError(null);
    if (!file) return;
    if (file.size > MAX_FASTA_BYTES) {
      setFileError(t("gene.fileTooLarge", { max: MAX_FASTA_BYTES }));
      return;
    }
    file.text().then((text) => setFasta({ ...fasta, text, from: "upload", name: fasta.name || file.name.replace(/\.[^.]+$/, "") }));
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("gene.dialogTitle")} description={t("gene.dialogDescription")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        <Tabs value={source} onChange={setSource} items={(["saved", "fasta", "gene"] as QuerySource[]).map((s) => ({ value: s, label: t(`gene.source.${s}` as TranslationKey) }))} />
        {source === "saved" && (
          <div className="max-h-44 overflow-y-auto rounded-lg border text-xs">
            {(queries.data ?? []).length === 0 && <p className="p-2 text-muted-foreground">{t("gene.noQueries")}</p>}
            {(queries.data ?? []).map((q) => (
              <div key={q.id} className="flex items-center gap-2 border-b px-2 py-1.5 last:border-b-0">
                <input type="radio" className={CHECK} checked={queryId === q.id} onChange={() => { setQueryId(q.id); setConfirmed(false); }} aria-label={q.name} />
                <span className="flex-1"><span className="font-medium">{q.name}</span> · {t(`gene.molecule.${q.molecule}` as TranslationKey)} · {q.molecule === "protein" ? t("gene.lengthAa", { n: q.length }) : fmtBp(q.length)}
                  <span className="block text-muted-foreground">{t(`gene.querySource.${q.source.kind}` as TranslationKey)}{q.description ? ` · ${q.description}` : ""}</span></span>
                <Button size="sm" variant="ghost" onClick={() => window.confirm(t("gene.deleteQuery")) && remove.mutate(q.id)} aria-label={t("gene.deleteQuery")}><Trash2 className="h-3.5 w-3.5" /></Button>
              </div>
            ))}
          </div>
        )}
        {source === "fasta" && (
          <div className="space-y-2">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("gene.queryName")}><Input value={fasta.name} onChange={(e) => setFasta({ ...fasta, name: e.target.value })} /></Field>
              <Field label={t("gene.molecule")}>
                <Select value={fasta.molecule} onChange={(e) => setFasta({ ...fasta, molecule: e.target.value as "nucleotide" | "protein" })}>
                  <option value="protein">{t("gene.molecule.protein")}</option><option value="nucleotide">{t("gene.molecule.nucleotide")}</option>
                </Select>
              </Field>
            </div>
            <Field label={t("gene.fasta")} hint={t("gene.fastaHint")}>
              <Textarea rows={5} className="font-mono text-xs" value={fasta.text} onChange={(e) => setFasta({ ...fasta, text: e.target.value, from: "paste" })} />
            </Field>
            <input type="file" accept=".fa,.fasta,.faa,.fna,.ffn,.txt" className="text-xs" onChange={(e) => readFile(e.target.files?.[0])} aria-label={t("gene.upload")} />
            {fileError && <p className="text-xs text-danger">{fileError}</p>}
            <ErrorNote error={saveFasta.error} />
            <Button size="sm" variant="outline" disabled={!fasta.text.trim() || saveFasta.isPending} onClick={() => saveFasta.mutate()}>{t("gene.saveQuery")}</Button>
          </div>
        )}
        {source === "gene" && (
          <div className="space-y-2">
            <GeneLookup set={set} picked={picked} onPick={setPicked} />
            <div className="flex items-end gap-2">
              <Field label={t("gene.molecule")}>
                <Select value={pickedMolecule} onChange={(e) => setPickedMolecule(e.target.value as "nucleotide" | "protein")}>
                  <option value="protein">{t("gene.molecule.protein")}</option><option value="nucleotide">{t("gene.molecule.nucleotide")}</option>
                </Select>
              </Field>
              <Button size="sm" variant="outline" disabled={!picked || saveFeature.isPending} onClick={() => saveFeature.mutate()}>{t("gene.saveQuery")}</Button>
            </div>
            <ErrorNote error={saveFeature.error} />
          </div>
        )}
        {saved && <p className="text-xs">{t("gene.chosenQuery", { name: saved.name, program })}</p>}
        <Field label={t("gene.genomes")}><GenomeOrder set={set} chosen={genomes} setChosen={(ids) => { setGenomes(ids); setConfirmed(false); }} /></Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("gene.task")}>
            <Select value={opts.task ?? program} onChange={(e) => set_({ task: e.target.value })}>
              {TASKS[program].map((k) => <option key={k} value={k}>{k}</option>)}
            </Select>
          </Field>
          <Num label={t("gene.minIdentity")} value={opts.thresholds.min_identity} onChange={(v) => set_({ thresholds: { ...opts.thresholds, min_identity: v } })} />
          <Num label={t("gene.minCoverage")} value={opts.thresholds.min_coverage} onChange={(v) => set_({ thresholds: { ...opts.thresholds, min_coverage: v } })} />
          <Num label={t("gene.completeCoverage")} value={opts.thresholds.complete_coverage} onChange={(v) => set_({ thresholds: { ...opts.thresholds, complete_coverage: v } })} />
          <Field label={t("region.evalue")}><Input value={String(opts.thresholds.evalue)} onChange={(e) => set_({ thresholds: { ...opts.thresholds, evalue: Number(e.target.value) } })} /></Field>
          <Num label={t("gene.maxGap")} value={opts.thresholds.max_gap} onChange={(v) => set_({ thresholds: { ...opts.thresholds, max_gap: v } })} />
          <Num label={t("gene.mobileDistance")} value={opts.mobile_distance} onChange={(v) => set_({ mobile_distance: v })} />
          <Num label={t("comparative.threads")} value={threads ?? plan.data?.settings.threads ?? 1} min={1} onChange={(v) => { setThreads(v); setConfirmed(false); }} />
        </div>
        <p className="text-xs text-muted-foreground">{t("gene.thresholdsHint")}</p>
        <fieldset className="space-y-2 rounded-lg border p-3 text-xs">
          <label className="flex items-center gap-2 font-medium">
            <input type="checkbox" className={CHECK} checked={opts.alignment.enabled}
              onChange={(e) => set_({ alignment: { ...opts.alignment, enabled: e.target.checked }, tree: { ...opts.tree, enabled: e.target.checked && opts.tree.enabled } })} />
            {t("gene.alignmentEnable")}
          </label>
          {opts.alignment.enabled && (
            <div className="grid gap-3 pl-5 sm:grid-cols-3">
              <Field label={t("gene.strategy")}>
                <Select value={opts.alignment.strategy} onChange={(e) => set_({ alignment: { ...opts.alignment, strategy: e.target.value as "linsi" | "fftns2" } })}>
                  <option value="linsi">{t("gene.strategy.linsi")}</option><option value="fftns2">{t("gene.strategy.fftns2")}</option>
                </Select>
              </Field>
              <div className="space-y-1 sm:col-span-2">
                <span className="text-muted-foreground">{t("gene.alignKinds")}</span>
                <div className="flex flex-wrap gap-3">
                  {(["complete", "partial", "split"] as const).map((k) => (
                    <label key={k} className="flex items-center gap-1">
                      <input type="checkbox" className={CHECK} checked={opts.alignment.kinds.includes(k)}
                        onChange={(e) => set_({ alignment: { ...opts.alignment, kinds: e.target.checked ? [...opts.alignment.kinds, k] : opts.alignment.kinds.filter((x) => x !== k) } })} />
                      {t(`gene.kind.${k}` as TranslationKey)}
                    </label>
                  ))}
                  {saved?.molecule === "nucleotide" && (
                    <label className="flex items-center gap-1">
                      <input type="checkbox" className={CHECK} checked={opts.alignment.include_query} onChange={(e) => set_({ alignment: { ...opts.alignment, include_query: e.target.checked } })} />
                      {t("gene.includeQuery")}
                    </label>
                  )}
                </div>
              </div>
              <label className="flex items-center gap-2 font-medium sm:col-span-3">
                <input type="checkbox" className={CHECK} checked={opts.tree.enabled} onChange={(e) => set_({ tree: { ...opts.tree, enabled: e.target.checked } })} />
                {t("gene.treeEnable")}
              </label>
              {opts.tree.enabled && (
                <>
                  <Field label={t("gene.treeMethod")}>
                    <Select value={opts.tree.method} onChange={(e) => set_({ tree: { ...opts.tree, method: e.target.value as "iqtree" | "fasttree" } })}>
                      <option value="iqtree">{t("gene.treeMethod.iqtree")}</option><option value="fasttree">{t("gene.treeMethod.fasttree")}</option>
                    </Select>
                  </Field>
                  {opts.tree.method === "iqtree" && (
                    <>
                      <Field label={t("gene.treeModel")}><Input value={opts.tree.model} onChange={(e) => set_({ tree: { ...opts.tree, model: e.target.value } })} /></Field>
                      <Num label={t("gene.ufboot")} value={opts.tree.ufboot} min={1000} onChange={(v) => set_({ tree: { ...opts.tree, ufboot: v } })} />
                    </>
                  )}
                  <Num label={t("gene.seed")} value={opts.tree.seed} min={1} onChange={(v) => set_({ tree: { ...opts.tree, seed: v } })} />
                </>
              )}
            </div>
          )}
        </fieldset>
        <ErrorNote error={plan.error} />
        <Summary plan={plan.data}>
          {plan.data?.query && <p>{t("gene.planQuery", { name: plan.data.query.name, length: plan.data.query.length, sha: plan.data.query.sha256.slice(0, 16) })}</p>}
        </Summary>
        <ErrorNote error={run.error} />
        <Run onCancel={() => onOpenChange(false)} onRun={() => run.mutate()} pending={run.isPending} label={t("gene.run")}
          disabled={!plan.data || plan.data.problems.length > 0 || plan.isFetching} confirmed={confirmed} setConfirmed={setConfirmed} />
      </div>
    </Dialog>
  );
}
