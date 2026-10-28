import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, ExternalLink, Loader2, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ChartCard } from "@/components/charts/ChartCard";
import { MetricTile } from "@/components/domain/bits";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { FEATURE_TYPES, MAX_EXPORT, PAGE_SIZE, safeExternalUrl, searched, stepLabel, stepReason, stepState } from "@/lib/annotation";
import { api } from "@/lib/api";
import { fmtBases, fmtBytes, fmtDate, fmtInt, fmtNum } from "@/lib/format";
import type { Annotation, AnnotationExportFormat, AnnotationFeature, AnalysisJobDetail, FeatureQuery } from "@/lib/types";
import { cn } from "@/lib/utils";
import { StepIcon, SyntheticNote } from "./AnnotationDialog";

type T = ReturnType<typeof useT>;

const typeLabel = (t: T, type: string) => t(`annotation.type.${type}` as "annotation.type.cds");

/** One annotation: what was searched (and what not, with why), ARVA's counts, the features and the files. */
export function AnnotationCard({ annotation, job }: { annotation: Annotation; job?: AnalysisJobDetail }) {
  const t = useT();
  const a = annotation;
  const s = a.summary;
  const tool = a.tool.toLowerCase() === "prokka" ? "prokka" : "bakta";
  const notSearched = t("annotation.notSearchedShort");
  const count = (step: string, type: string) => (searched(a.steps, step) ? fmtInt(s.counts[type] ?? 0) : notSearched);
  const params = a.parameters as { assembly?: { assembler?: string; assembler_version?: string; kind?: string }; locus_tag?: string };
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {a.tool} {a.tool_version}
            {a.database_name && <Badge tone="blue">{`${a.database_name} ${a.database_version ?? ""}`}</Badge>}
            <Explain id={tool} compact />
          </span>
        }
        description={t("annotation.cardLine", {
          assembly: `${params.assembly?.assembler ?? "?"} ${params.assembly?.assembler_version ?? ""}${params.assembly?.kind === "polished" ? ` (${t("annotation.polished")})` : ""} · ${a.assembly_id.slice(0, 8)}`,
          date: fmtDate(a.created_at),
          tag: params.locus_tag ?? "?",
        })}
        action={<Downloads annotation={a} />}
      />
      <CardBody className="space-y-5 pt-3">
        {s.synthetic_evidence?.length > 0 && <SyntheticNote evidence={s.synthetic_evidence} />}
        <p className="text-xs text-muted-foreground">{t("annotation.predictions")}</p>
        <div className="grid gap-3 sm:grid-cols-4 xl:grid-cols-8">
          <MetricTile label={t("annotation.tile.cds")} value={s.cds == null ? notSearched : fmtInt(s.cds)} explain="cds" />
          <MetricTile label={t("annotation.tile.trna")} value={count("trna", "trna")} explain="trna_rrna" />
          <MetricTile label={t("annotation.tile.rrna")} value={count("rrna", "rrna")} explain="trna_rrna" />
          <MetricTile label={t("annotation.tile.ncrna")} value={count("ncrna", "ncrna")} />
          <MetricTile label={t("annotation.tile.crispr")} value={count("crispr", "crispr")} />
          <MetricTile label={t("annotation.tile.pseudo")} value={searched(a.steps, "pseudo") ? fmtInt(s.pseudogenes) : notSearched} />
          <MetricTile
            label={t("annotation.tile.hypothetical")}
            value={s.hypothetical_fraction == null ? (s.cds == null ? notSearched : "—") : `${fmtNum(100 * s.hypothetical_fraction, 1)} %`}
            sub={s.hypothetical != null && s.cds != null ? t("annotation.tile.hypotheticalSub", { n: fmtInt(s.hypothetical), total: fmtInt(s.cds) }) : undefined}
            explain="hypothetical_proteins"
          />
          <MetricTile
            label={t("annotation.tile.codingDensity")}
            value={s.coding_density.value == null ? notSearched : `${fmtNum(100 * s.coding_density.value, 1)} %`}
            sub={t("annotation.tile.codingDensitySub")}
          />
        </div>
        <StepsList annotation={a} />
        <FeatureCharts annotation={a} />
        <FeatureTable annotation={a} />
        {a.files.plot_png && (
          <figure className="space-y-1">
            <img src={api.annotationFileUrl(a.id, "plot_png")} alt={t("annotation.plotAlt")} className="mx-auto max-h-[480px] rounded-lg border bg-white" loading="lazy" />
            <figcaption className="text-center text-xs text-muted-foreground">{t("annotation.plotCaption")}</figcaption>
          </figure>
        )}
        {job && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">{t("annotation.commands")}</summary>
            {(job.commands ?? []).map((c, i) => (
              <pre key={i} className="mt-1 whitespace-pre-wrap break-all rounded bg-muted p-2 text-[11px]">
                {c.join(" ")}
              </pre>
            ))}
          </details>
        )}
      </CardBody>
    </Card>
  );
}

function StepsList({ annotation }: { annotation: Annotation }) {
  const t = useT();
  return (
    <section aria-label={t("annotation.steps")}>
      <h4 className="mb-1.5 text-sm font-semibold">{t("annotation.steps")}</h4>
      <ul className="grid gap-1 sm:grid-cols-2 xl:grid-cols-3">
        {Object.entries(annotation.steps).map(([step, s]) => {
          const state = stepState(s);
          return (
            <li key={step} className={cn("flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs", state === "failed" && "border-danger/40 bg-danger/5")}>
              <StepIcon state={state} />
              <span>
                <span className="font-medium">{stepLabel(t, annotation.tool, step)}</span>
                {state === "searched" && s.found != null && <span className="text-muted-foreground"> · {t("annotation.found", { n: fmtInt(s.found) })}</span>}
                {state === "skipped" && <span className="block text-muted-foreground">{t("annotation.notSearched", { reason: stepReason(t, s) })}</span>}
                {state === "failed" && <span className="block text-danger">{t("annotation.failedStep", { reason: stepReason(t, s) })}</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function FeatureCharts({ annotation }: { annotation: Annotation }) {
  const t = useT();
  const counts = annotation.summary.counts;
  const types = FEATURE_TYPES.filter((k) => counts[k]);
  const cats = Object.entries(annotation.summary.cog_categories ?? {});
  if (!types.length) return null;
  return (
    <div className={cn("grid gap-4", cats.length && "lg:grid-cols-2")}>
      <ChartCard
        title={t("annotation.chart.types")}
        subtitle={t("annotation.chart.typesSub")}
        filePrefix={`arva_${annotation.tool.toLowerCase()}`}
        height={240}
        option={{
          grid: { left: 110, right: 24, top: 8, bottom: 32 },
          xAxis: { type: "value", name: t("annotation.chart.features"), nameLocation: "middle", nameGap: 24 },
          yAxis: { type: "category", data: types.map((k) => typeLabel(t, k)), inverse: true },
          tooltip: { trigger: "axis" },
          series: [{ type: "bar", data: types.map((k) => counts[k]), itemStyle: { color: "#1F3B8A" } }],
        }}
        table={{ columns: [t("annotation.col.type"), t("annotation.chart.features")], rows: types.map((k) => [typeLabel(t, k), counts[k]]) }}
      />
      {cats.length > 0 && (
        <ChartCard
          title={t("annotation.chart.cog")}
          subtitle={t("annotation.chart.cogSub")}
          explain="cog"
          filePrefix={`arva_${annotation.tool.toLowerCase()}`}
          height={240}
          option={{
            grid: { left: 40, right: 24, top: 8, bottom: 32 },
            xAxis: { type: "category", data: cats.map(([c]) => c) },
            yAxis: { type: "value", name: "CDS" },
            tooltip: { trigger: "axis" },
            series: [{ type: "bar", data: cats.map(([, n]) => n), itemStyle: { color: "#00B4A6" } }],
          }}
          table={{ columns: ["COG", "CDS"], rows: cats.map(([c, n]) => [c, n]) }}
        />
      )}
    </div>
  );
}

const SORTABLE: { key: FeatureQuery["sort"]; label: string }[] = [
  { key: "locus_tag", label: "annotation.col.locusTag" },
  { key: "type", label: "annotation.col.type" },
  { key: "position", label: "annotation.col.position" },
  { key: "length", label: "annotation.col.length" },
  { key: "gene", label: "annotation.col.gene" },
  { key: "product", label: "annotation.col.product" },
];

function FeatureTable({ annotation }: { annotation: Annotation }) {
  const t = useT();
  const a = annotation;
  const [query, setQuery] = useState<FeatureQuery>({
    types: [], q: "", hypothetical: "", contig: "", start: "", end: "", sort: "position", descending: false, limit: PAGE_SIZE, offset: 0,
  });
  const [text, setText] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  useEffect(() => {
    const timer = setTimeout(() => setQuery((q) => (q.q === text ? q : { ...q, q: text, offset: 0 })), 300);
    return () => clearTimeout(timer);
  }, [text]);
  const page = useQuery({ queryKey: ["annotationFeatures", a.id, query], queryFn: () => api.annotationFeatures(a.id, query), placeholderData: (prev) => prev });
  const types = FEATURE_TYPES.filter((k) => a.summary.counts[k]);
  const items = page.data?.items ?? [];
  const total = page.data?.total ?? 0;
  const update = (patch: Partial<FeatureQuery>) => setQuery((q) => ({ ...q, ...patch, offset: "offset" in patch ? patch.offset! : 0 }));
  const sortBy = (key: FeatureQuery["sort"]) => update({ sort: key, descending: query.sort === key ? !query.descending : false });
  const toggle = (id: number) => setSelected((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  return (
    <section className="space-y-2" aria-label={t("annotation.features")}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h4 className="text-sm font-semibold">{t("annotation.features")}</h4>
        <SelectionExport annotation={a} selected={[...selected]} onClear={() => setSelected(new Set())} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
          <Input className="pl-8" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("annotation.searchPlaceholder")} aria-label={t("annotation.search")} />
        </div>
        <Select value={query.types[0] ?? ""} onChange={(e) => update({ types: e.target.value ? [e.target.value] : [] })} aria-label={t("annotation.filterType")} className="w-44">
          <option value="">{t("annotation.allTypes")}</option>
          {types.map((k) => (
            <option key={k} value={k}>
              {typeLabel(t, k)} ({fmtInt(a.summary.counts[k])})
            </option>
          ))}
        </Select>
        <Select value={query.hypothetical} onChange={(e) => update({ hypothetical: e.target.value as FeatureQuery["hypothetical"] })} aria-label={t("annotation.filterHypothetical")} className="w-48">
          <option value="">{t("annotation.hypo.all")}</option>
          <option value="true">{t("annotation.hypo.only")}</option>
          <option value="false">{t("annotation.hypo.none")}</option>
        </Select>
        <Select value={query.contig} onChange={(e) => update({ contig: e.target.value })} aria-label={t("annotation.filterContig")} className="w-56">
          <option value="">{t("annotation.allContigs")}</option>
          {a.sequences.map((c) => (
            <option key={c.id} value={c.id}>
              {c.original_id}
              {c.original_id !== c.id ? ` (${c.id})` : ""} · {fmtBases(c.length)}
            </option>
          ))}
        </Select>
        {query.contig && (
          <>
            <Input className="w-28" type="number" min={1} placeholder={t("annotation.from")} value={query.start} onChange={(e) => update({ start: e.target.value })} aria-label={t("annotation.from")} />
            <Input className="w-28" type="number" min={1} placeholder={t("annotation.to")} value={query.end} onChange={(e) => update({ end: e.target.value })} aria-label={t("annotation.to")} />
          </>
        )}
      </div>
      <ErrorNote error={page.error} />
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-left">
            <tr>
              <th className="w-8 px-2 py-1.5">
                <span className="sr-only">{t("annotation.select")}</span>
              </th>
              {SORTABLE.map((c) => (
                <th key={c.key} className="px-2 py-1.5 font-medium" aria-sort={query.sort === c.key ? (query.descending ? "descending" : "ascending") : "none"}>
                  <button type="button" className="inline-flex items-center gap-1 hover:underline" onClick={() => sortBy(c.key)}>
                    {t(c.label as "annotation.col.type")}
                    {query.sort === c.key && (query.descending ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
                  </button>
                </th>
              ))}
              <th className="px-2 py-1.5 font-medium">{t("annotation.col.ids")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr key={f.id} className={cn("cursor-pointer border-t hover:bg-muted/40", open === f.id && "bg-arva-teal/5")} onClick={() => setOpen(open === f.id ? null : f.id)}>
                <td className="px-2 py-1" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" className="h-3.5 w-3.5 accent-[#00B4A6]" checked={selected.has(f.id)} onChange={() => toggle(f.id)} aria-label={t("annotation.selectFeature", { id: f.locus_tag ?? f.id })} />
                </td>
                <td className="px-2 py-1 font-mono">{f.locus_tag ?? "—"}</td>
                <td className="px-2 py-1">{typeLabel(t, f.type)}</td>
                <td className="whitespace-nowrap px-2 py-1 tabular-nums">
                  {f.contig_in_assembly}:{fmtInt(f.start)}–{fmtInt(f.end)} ({f.strand})
                </td>
                <td className="px-2 py-1 tabular-nums">{fmtInt(f.length)}</td>
                <td className="px-2 py-1 italic">{f.gene ?? ""}</td>
                <td className="max-w-[28rem] px-2 py-1">
                  {f.product ?? ""}
                  {f.hypothetical && <Badge className="ml-1" tone="neutral">{t("annotation.hypotheticalBadge")}</Badge>}
                  {f.pseudo && <Badge className="ml-1" tone="warning">{t("annotation.pseudoBadge")}</Badge>}
                  {f.partial && <Badge className="ml-1" tone="neutral">{t("annotation.partialBadge", { end: f.partial })}</Badge>}
                </td>
                <td className="px-2 py-1 text-muted-foreground">{[...f.ec.map((e) => `EC ${e}`), ...f.cog].join(", ")}</td>
              </tr>
            ))}
            {!items.length && !page.isLoading && (
              <tr>
                <td colSpan={8} className="px-2 py-4 text-center text-muted-foreground">
                  {t("annotation.noFeatures")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{t("annotation.pageLine", { from: total ? fmtInt(query.offset + 1) : 0, to: fmtInt(Math.min(query.offset + query.limit, total)), total: fmtInt(total) })}</span>
        <span className="flex gap-1">
          <Button size="sm" variant="outline" disabled={query.offset === 0} onClick={() => update({ offset: Math.max(0, query.offset - query.limit) })} aria-label={t("annotation.prev")}>
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="outline" disabled={query.offset + query.limit >= total} onClick={() => update({ offset: query.offset + query.limit })} aria-label={t("annotation.next")}>
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </span>
      </div>
      {open != null && <FeatureDetail annotationId={a.id} featureId={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

function FeatureDetail({ annotationId, featureId, onClose }: { annotationId: string; featureId: number; onClose: () => void }) {
  const t = useT();
  const d = useQuery({ queryKey: ["annotationFeature", annotationId, featureId], queryFn: () => api.annotationFeature(annotationId, featureId) });
  const f = d.data;
  return (
    <div className="rounded-xl border bg-surface p-4 text-xs" role="region" aria-label={t("annotation.detail")}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <h5 className="text-sm font-semibold">
          {f ? `${f.locus_tag ?? f.tool_id ?? f.id} · ${f.product ?? typeLabel(t, f.type)}` : t("common.loading")}
        </h5>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label={t("annotation.close")}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ErrorNote error={d.error} />
      {f && (
        <div className="space-y-3">
          <dl className="grid grid-cols-[150px_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">{t("annotation.col.type")}</dt>
            <dd>
              {typeLabel(t, f.type)} <span className="text-muted-foreground">({f.tool_type})</span>
            </dd>
            <dt className="text-muted-foreground">{t("annotation.col.position")}</dt>
            <dd>
              {f.contig_in_assembly}
              {f.contig !== f.contig_in_assembly ? ` (${f.contig})` : ""}: {fmtInt(f.start)}–{fmtInt(f.end)}, {f.strand} · {fmtInt(f.length)} bp
              {f.edge ? ` · ${t("annotation.edge")}` : ""}
            </dd>
            <dt className="text-muted-foreground">{t("annotation.col.gene")}</dt>
            <dd className="italic">{f.gene ?? "—"}</dd>
            <dt className="text-muted-foreground">{t("annotation.col.product")}</dt>
            <dd>
              {f.product ?? "—"}
              {f.hypothetical && <span className="text-muted-foreground"> · {t("annotation.hypotheticalNote")}</span>}
            </dd>
            {f.ec.length > 0 && (
              <>
                <dt className="text-muted-foreground">EC</dt>
                <dd>{f.ec.join(", ")}</dd>
              </>
            )}
            {(f.cog.length > 0 || f.cog_categories.length > 0) && (
              <>
                <dt className="text-muted-foreground">COG</dt>
                <dd>{[...f.cog, ...f.cog_categories.map((c) => t("annotation.cogCategory", { c }))].join(", ")}</dd>
              </>
            )}
            {f.go.length > 0 && (
              <>
                <dt className="text-muted-foreground">GO</dt>
                <dd>{f.go.join(", ")}</dd>
              </>
            )}
            <dt className="text-muted-foreground">{t("annotation.evidence")}</dt>
            <dd>
              <ul className="list-disc pl-4">
                {f.inference.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </dd>
            {f.db_xrefs.length > 0 && (
              <>
                <dt className="text-muted-foreground">{t("annotation.xrefs")}</dt>
                <dd className="break-all">{f.db_xrefs.join(", ")}</dd>
              </>
            )}
          </dl>
          {f.links.length > 0 && (
            <div>
              <div className="mb-1 text-muted-foreground">{t("annotation.links")}</div>
              <ul className="flex flex-wrap gap-2">
                {f.links.map((l) => {
                  const url = safeExternalUrl(l.url);
                  return url ? (
                    <li key={url}>
                      <a href={url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 text-arva-royal hover:underline dark:text-arva-cyan">
                        {l.xref} <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    </li>
                  ) : null;
                })}
              </ul>
              <p className="mt-1 text-[11px] text-muted-foreground">{t("annotation.linksNote")}</p>
            </div>
          )}
          {f.nucleotide && <SequenceBlock title={t("annotation.nucleotide")} seq={f.nucleotide} />}
          {f.protein && <SequenceBlock title={t("annotation.protein")} seq={f.protein} />}
          {!f.nucleotide && <p className="text-muted-foreground">{t("annotation.noSequence")}</p>}
        </div>
      )}
    </div>
  );
}

function SequenceBlock({ title, seq }: { title: string; seq: NonNullable<AnnotationFeatureDetailSeq> }) {
  const t = useT();
  return (
    <div>
      <div className="mb-1 text-muted-foreground">
        {title} · {fmtInt(seq.length)} · {t("annotation.from")} {seq.source}
        {seq.truncated && ` · ${t("annotation.truncated")}`}
      </div>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-2 font-mono text-[11px]">{seq.sequence}</pre>
    </div>
  );
}

type AnnotationFeatureDetailSeq = { source: string; header: string; length: number; sequence: string; truncated: boolean };

const TOOL_FILES: { kind: string; label: string; key?: TranslationKey }[] = [
  { kind: "gff3", label: "GFF3" },
  { kind: "genbank", label: "GenBank" },
  { kind: "embl", label: "EMBL" },
  { kind: "ffn", label: "FASTA", key: "annotation.file.genes" },
  { kind: "faa", label: "FASTA", key: "annotation.file.proteins" },
  { kind: "fna", label: "FASTA", key: "annotation.file.sequences" },
  { kind: "tsv", label: "TSV" },
  { kind: "json", label: "JSON" },
  { kind: "plot_svg", label: "SVG", key: "annotation.file.plot" },
  { kind: "summary", label: "TXT", key: "annotation.file.summary" },
  { kind: "log", label: "TXT", key: "annotation.file.log" },
];

function Downloads({ annotation }: { annotation: Annotation }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const files = TOOL_FILES.filter((f) => annotation.files[f.kind]);
  return (
    <div className="relative">
      <Button size="sm" variant="outline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Download className="h-3.5 w-3.5" /> {t("annotation.downloads")}
      </Button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-72 rounded-lg border bg-surface p-2 text-xs shadow-lg">
          <div className="px-1 pb-1 font-medium">{t("annotation.toolFiles", { tool: annotation.tool })}</div>
          {files.map((f) => (
            <a key={f.kind} href={api.annotationFileUrl(annotation.id, f.kind)} className="block rounded px-1 py-1 hover:bg-muted">
              {f.key ? t(f.key, { format: f.label }) : f.label} <span className="text-muted-foreground">· {fmtBytes(annotation.files[f.kind].size_bytes)}</span>
            </a>
          ))}
          <div className="mt-1 border-t px-1 pb-1 pt-2 font-medium">{t("annotation.arvaTable")}</div>
          <a href={api.annotationExportUrl(annotation.id, "tsv")} className="block rounded px-1 py-1 hover:bg-muted">
            {t("annotation.featuresTsv")}
          </a>
        </div>
      )}
    </div>
  );
}

const EXPORTS: { format: AnnotationExportFormat; label: string; key?: TranslationKey }[] = [
  { format: "gff3", label: "GFF3" },
  { format: "genbank", label: "GenBank" },
  { format: "fasta_nt", label: "FASTA", key: "annotation.file.genes" },
  { format: "fasta_aa", label: "FASTA", key: "annotation.file.proteins" },
  { format: "tsv", label: "TSV" },
];

function SelectionExport({ annotation, selected, onClear }: { annotation: Annotation; selected: number[]; onClear: () => void }) {
  const t = useT();
  const [format, setFormat] = useState<AnnotationExportFormat>("gff3");
  const save = useMutation({
    mutationFn: () => api.exportAnnotationFeatures(annotation.id, format, selected),
    onSuccess: ({ blob, name }) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    },
  });
  const formats = useMemo(() => EXPORTS.filter((e) => e.format === "tsv" || annotation.files[{ gff3: "gff3", genbank: "genbank", fasta_nt: "ffn", fasta_aa: "faa", tsv: "tsv" }[e.format]]), [annotation]);
  if (!selected.length) return <p className="text-xs text-muted-foreground">{t("annotation.selectHint")}</p>;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span>{t("annotation.selected", { n: fmtInt(selected.length) })}</span>
      <Select value={format} onChange={(e) => setFormat(e.target.value as AnnotationExportFormat)} className="w-40" aria-label={t("annotation.exportFormat")}>
        {formats.map((e) => (
          <option key={e.format} value={e.format}>
            {e.key ? t(e.key, { format: e.label }) : e.label}
          </option>
        ))}
      </Select>
      <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || selected.length > MAX_EXPORT}>
        {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />} {t("annotation.exportSelected")}
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear}>
        {t("annotation.clearSelection")}
      </Button>
      <ErrorNote error={save.error} />
    </div>
  );
}

export type { AnnotationFeature };
