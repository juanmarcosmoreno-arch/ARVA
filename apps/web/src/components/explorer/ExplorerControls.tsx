import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Loader2, Search, X } from "lucide-react";
import { useState } from "react";
import { useChartTheme } from "@/components/charts/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { MAX_EXPORT } from "@/lib/annotation";
import { api } from "@/lib/api";
import { type ContigOption, featureLabel, parseSearch, regionOf, type SearchTarget, type View } from "@/lib/explorer";
import { fmtBp, fmtInt } from "@/lib/format";
import type { Annotation, AnnotationExportFormat, AnnotationFeature, AnnotationRegion, FeatureLayoutItem } from "@/lib/types";
import { groupColour } from "./GenomeBrowser";

const MAX_SEQUENCE = 1_000_000;
const SEARCH_LIMIT = 25;

/** Gene name, locus tag, product text or identifier (server-side search over every sequence), or coordinates. */
export function ExplorerSearch({ annotationId, contigs, current, onRegion, onFeature }: {
  annotationId: string;
  contigs: ContigOption[];
  current: string;
  onRegion: (contig: string, start: number, end: number) => void;
  onFeature: (f: AnnotationFeature) => void;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [target, setTarget] = useState<SearchTarget | null>(null);
  const [active, setActive] = useState(0);
  const q = target?.kind === "text" ? target.q : null;
  const results = useQuery({
    queryKey: ["explorerSearch", annotationId, q],
    queryFn: () => api.annotationFeatures(annotationId, { types: [], q: q!, hypothetical: "", contig: "", start: "", end: "", sort: "position", descending: false, limit: SEARCH_LIMIT, offset: 0 }),
    enabled: q != null,
  });
  const items = q != null ? results.data?.items ?? [] : [];
  const pick = (f: AnnotationFeature) => {
    onFeature(f);
    setTarget(null);
  };
  const submit = () => {
    const parsed = parseSearch(text, contigs, current);
    setActive(0);
    if (parsed?.kind === "region") onRegion(parsed.contig, parsed.start, parsed.end);
    else if (parsed?.kind === "contig") {
      const c = contigs.find((x) => x.id === parsed.contig)!;
      onRegion(c.id, 1, c.length);
    }
    setTarget(parsed?.kind === "region" || parsed?.kind === "contig" ? null : parsed);
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (items.length && target?.kind === "text" && target.q === text.trim()) pick(items[active]);
      else submit();
    } else if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      setActive((a) => Math.min(items.length - 1, a + 1));
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Escape") setTarget(null);
  };
  const listId = "explorer-search-results";
  return (
    <div className="relative w-full max-w-xl">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex gap-1.5"
      >
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-3 h-4 w-4 text-muted-foreground" aria-hidden />
          <Input
            className="pl-8"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t("explorer.searchPlaceholder")}
            aria-label={t("explorer.search")}
            aria-controls={items.length ? listId : undefined}
            aria-activedescendant={items.length ? `${listId}-${active}` : undefined}
            role="combobox"
            aria-expanded={items.length > 0}
            aria-autocomplete="list"
          />
        </div>
        <Button type="submit" variant="outline">
          {t("explorer.go")}
        </Button>
      </form>
      {target?.kind === "error" && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {t(`explorer.searchError.${target.code}`)}
        </p>
      )}
      {target?.kind === "text" && (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-80 overflow-y-auto rounded-lg border bg-surface p-1 text-xs shadow-lg">
          {results.isLoading && <p className="p-2 text-muted-foreground">{t("common.loading")}</p>}
          <ErrorNote error={results.error} />
          {results.data && !items.length && <p className="p-2 text-muted-foreground">{t("explorer.noResults", { q: target.q })}</p>}
          {items.length > 0 && (
            <ul id={listId} role="listbox" aria-label={t("explorer.results")}>
              {items.map((f, i) => (
                <li key={f.id} id={`${listId}-${i}`} role="option" aria-selected={i === active}>
                  <button
                    type="button"
                    className={`block w-full rounded px-2 py-1 text-left hover:bg-muted ${i === active ? "bg-muted" : ""}`}
                    onClick={() => pick(f)}
                    onMouseEnter={() => setActive(i)}
                  >
                    <span className="font-mono">{f.locus_tag ?? f.tool_id ?? `#${f.id}`}</span>
                    {f.gene && <span className="italic"> {f.gene}</span>}
                    <span className="text-muted-foreground"> · {f.product ?? t(`annotation.type.${f.type}` as "annotation.type.cds")}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {f.contig_in_assembly}:{fmtInt(f.start)}–{fmtInt(f.end)} ({f.strand})
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {results.data && results.data.total > items.length && (
            <p className="p-2 text-[11px] text-muted-foreground">{t("explorer.moreResults", { n: fmtInt(results.data.total), shown: items.length })}</p>
          )}
          <div className="border-t px-2 pt-1 text-right">
            <button type="button" className="text-[11px] text-muted-foreground hover:underline" onClick={() => setTarget(null)}>
              {t("annotation.close")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Feature colours with what they mean; colour is never the only cue (shape, outline and the side panel say it too). */
export function ExplorerLegend() {
  const t = useT();
  const theme = useChartTheme();
  const swatch = (fill: string, stroke?: string, dash?: string) => (
    <svg width={22} height={10} aria-hidden className="shrink-0">
      <path d="M1,1H15L21,5L15,9H1Z" fill={fill} stroke={stroke ?? "none"} strokeWidth={1.5} strokeDasharray={dash} />
    </svg>
  );
  const items: [React.ReactNode, string][] = [
    [swatch(groupColour(theme, "coding")), t("explorer.legend.coding")],
    [swatch(theme.surface, groupColour(theme, "coding")), t("explorer.legend.hypothetical")],
    [swatch(groupColour(theme, "coding") + "73", groupColour(theme, "coding"), "3 2"), t("explorer.legend.pseudo")],
    [swatch(groupColour(theme, "rna")), t("explorer.legend.rna")],
    [swatch(groupColour(theme, "element")), t("explorer.legend.element")],
    [swatch(theme.muted), t("explorer.legend.gap")],
    [
      <svg width={22} height={10} aria-hidden key="ig" className="shrink-0">
        <line x1={0} x2={22} y1={5} y2={5} stroke={theme.axis} />
        <rect x={4} y={3} width={14} height={4} fill={theme.muted} opacity={0.55} />
      </svg>,
      t("explorer.legend.intergenic"),
    ],
  ];
  return (
    <div className="space-y-1">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label={t("explorer.legend.title")}>
        {items.map(([icon, label]) => (
          <li key={label} className="flex items-center gap-1.5">
            {icon}
            {label}
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-muted-foreground">{t("explorer.legend.note")}</p>
    </div>
  );
}

function saveBlob({ blob, name }: { blob: Blob; name: string }) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const FEATURE_EXPORTS: { format: AnnotationExportFormat; label: string; file: string }[] = [
  { format: "fasta_nt", label: "explorer.export.genesNt", file: "ffn" },
  { format: "fasta_aa", label: "explorer.export.proteins", file: "faa" },
  { format: "gff3", label: "explorer.export.gff3", file: "gff3" },
  { format: "tsv", label: "explorer.export.tsv", file: "" },
];

function FeatureExportButtons({ annotation, selection, disabled }: { annotation: Annotation; selection: number[] | AnnotationRegion; disabled?: boolean }) {
  const t = useT();
  const save = useMutation({
    mutationFn: (format: AnnotationExportFormat) => api.exportAnnotationFeatures(annotation.id, format, selection),
    onSuccess: saveBlob,
  });
  return (
    <>
      {FEATURE_EXPORTS.filter((e) => !e.file || annotation.files[e.file]).map((e) => (
        <Button key={e.format} size="sm" variant="outline" disabled={disabled || save.isPending} onClick={() => save.mutate(e.format)}>
          {save.isPending && save.variables === e.format ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          {t(e.label as "explorer.export.gff3")}
        </Button>
      ))}
      <ErrorNote error={save.error} />
    </>
  );
}

/** The selected region: its sequence (either strand, from the annotator's sequence file) and the features in it. */
export function RegionBar({ annotation, contig, region, features, onClear, onZoom }: {
  annotation: Annotation;
  contig: ContigOption;
  region: View;
  features: FeatureLayoutItem[];
  onClear: () => void;
  onZoom: () => void;
}) {
  const t = useT();
  const { start, end } = regionOf(region);
  const n = features.filter((f) => (f.edge && f.start > f.end ? f.start <= end || f.end >= start : f.start <= end && f.end >= start)).length;
  const tooLong = end - start + 1 > MAX_SEQUENCE;
  const body = { contig: contig.id, start, end };
  return (
    <section className="space-y-2 rounded-lg border border-arva-royal/30 bg-arva-royal/5 p-3 text-xs dark:border-arva-cyan/30 dark:bg-arva-cyan/5" aria-label={t("explorer.region.title")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t("explorer.region.title")}</span>
        <span className="font-mono">
          {contig.name}:{fmtInt(start)}–{fmtInt(end)}
        </span>
        <span className="text-muted-foreground">
          {fmtBp(end - start + 1)} · {t("explorer.region.features", { n: fmtInt(n) })}
        </span>
        <span className="ml-auto flex gap-1">
          <Button size="sm" variant="outline" onClick={onZoom}>
            {t("explorer.zoomToRegion")}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClear} aria-label={t("explorer.region.clear")}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground">{t("explorer.region.sequence")}</span>
        {(["+", "-"] as const).map((strand) =>
          tooLong ? null : (
            <a key={strand} href={api.annotationSequenceUrl(annotation.id, contig.id, start, end, strand)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border bg-surface px-3 hover:bg-muted">
              <Download className="h-3.5 w-3.5" /> {t(strand === "+" ? "explorer.region.fastaForward" : "explorer.region.fastaReverse")}
            </a>
          ),
        )}
        {tooLong && <span className="text-muted-foreground">{t("explorer.region.tooLong", { max: fmtInt(MAX_SEQUENCE) })}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground">{t("explorer.region.featuresExport")}</span>
        <FeatureExportButtons annotation={annotation} selection={body} disabled={n === 0 || n > MAX_EXPORT} />
      </div>
    </section>
  );
}

/** Genes picked one by one (Ctrl/⌘-click, or the panel's checkbox) for export. */
export function MarkedBar({ annotation, marked, features, onClear }: { annotation: Annotation; marked: Set<number>; features: FeatureLayoutItem[]; onClear: () => void }) {
  const t = useT();
  if (!marked.size) return <p className="text-xs text-muted-foreground">{t("explorer.markHint")}</p>;
  const names = features.filter((f) => marked.has(f.id)).map(featureLabel);
  return (
    <section className="flex flex-wrap items-center gap-1.5 rounded-lg border p-3 text-xs" aria-label={t("explorer.marked.title")}>
      <span className="font-medium">{t("explorer.marked.title")}</span>
      <span className="max-w-md truncate text-muted-foreground" title={names.join(", ")}>
        {t("explorer.marked.count", { n: fmtInt(marked.size) })}
        {names.length ? ` · ${names.slice(0, 6).join(", ")}${names.length > 6 ? "…" : ""}` : ""}
      </span>
      <FeatureExportButtons annotation={annotation} selection={[...marked]} />
      <Button size="sm" variant="ghost" onClick={onClear}>
        {t("annotation.clearSelection")}
      </Button>
    </section>
  );
}
