import { useQuery } from "@tanstack/react-query";
import { Map as MapIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { SyntheticNote } from "@/components/annotation/AnnotationDialog";
import { Segmented } from "@/components/charts/ChartCard";
import { CircularExplorer } from "@/components/explorer/CircularMap";
import { FeatureDetail } from "@/components/annotation/FeatureDetail";
import { ExplorerLegend, ExplorerSearch, MarkedBar, RegionBar } from "@/components/explorer/ExplorerControls";
import { type GcSettings, GenomeBrowser } from "@/components/explorer/GenomeBrowser";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { Select } from "@/components/ui/form";
import { EmptyState, ErrorNote, PageHeader } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { clampView, contigOptions, regionOf, type View, viewOf, viewOfFeature } from "@/lib/explorer";
import { fmtBases, fmtDate, fmtInt } from "@/lib/format";
import type { Annotation, AnnotationFeature, AssemblyContig, FeatureLayoutItem, MapFeature } from "@/lib/types";

/** The list of annotations to open (the sidebar's Genome Explorer entry). */
export function ExplorerListPage() {
  const t = useT();
  const list = useQuery({ queryKey: ["allAnnotations"], queryFn: api.allAnnotations });
  const rows = list.data ?? [];
  return (
    <div className="animate-fade-in">
      <PageHeader title={t("nav.explorer")} subtitle={t("explorer.listSubtitle")} actions={<Explain id="genome_explorer" />} />
      <ErrorNote error={list.error} />
      {list.data && !rows.length ? (
        <EmptyState icon={<MapIcon className="h-7 w-7" />} title={t("explorer.listEmpty")}>
          {t("explorer.listEmptyHint")}
        </EmptyState>
      ) : (
        <Card>
          <CardBody className="overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs">
                <tr>
                  {["sample", "project", "annotator", "assembly", "sequences", "features", "date"].map((c) => (
                    <th key={c} className="px-3 py-2 font-medium">
                      {t(`explorer.col.${c}` as "explorer.col.sample")}
                    </th>
                  ))}
                  <th className="px-3 py-2">
                    <span className="sr-only">{t("explorer.open")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-3 py-2">
                      <Link to={`/samples/${r.sample_id}`} className="font-medium hover:underline">
                        {r.sample_code}
                      </Link>
                      {r.synthetic_evidence.length > 0 && <Badge className="ml-1.5" tone="warning">SYNTHETIC</Badge>}
                      {r.is_demo && <Badge className="ml-1.5">DEMO</Badge>}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{r.project_name}</td>
                    <td className="px-3 py-2">
                      {r.tool} {r.tool_version}
                      {r.database_name && <span className="block text-xs text-muted-foreground">{`${r.database_name} ${r.database_version ?? ""}`}</span>}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.assembler} {r.assembler_version}
                      {r.assembly_kind === "polished" ? ` (${t("annotation.polished")})` : ""}
                      <span className="block font-mono text-muted-foreground">{r.assembly_id.slice(0, 8)}</span>
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {fmtInt(r.sequences)} · {fmtBases(r.total_length)}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{r.features == null ? "—" : fmtInt(r.features)}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{fmtDate(r.created_at)}</td>
                    <td className="px-3 py-2 text-right">
                      <Link to={`/explorer/${r.id}`} className="inline-flex items-center gap-1 text-arva-royal hover:underline dark:text-arva-cyan">
                        <MapIcon className="h-3.5 w-3.5" aria-hidden /> {t("explorer.open")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

const WINDOWS = [100, 500, 1_000, 5_000, 10_000, 50_000];
const STEP_DIVISORS = [1, 2, 5, 10];

export function ExplorerPage() {
  const { annotationId = "" } = useParams();
  const t = useT();
  const annotation = useQuery({ queryKey: ["annotation", annotationId], queryFn: () => api.annotation(annotationId) });
  const a = annotation.data;
  const sample = useQuery({ queryKey: ["sample", a?.sample_id], queryFn: () => api.sample(a!.sample_id), enabled: !!a });
  const assembly = useQuery({ queryKey: ["assembly", a?.assembly_id], queryFn: () => api.assembly(a!.assembly_id), enabled: !!a });
  if (annotation.error) return <ErrorNote error={annotation.error} />;
  if (!a) return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  const params = a.parameters as { assembly?: { assembler?: string; assembler_version?: string; kind?: string }; locus_tag?: string };
  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        eyebrow={
          <span>
            <Link to="/explorer" className="hover:underline">
              {t("nav.explorer")}
            </Link>
            {sample.data && (
              <>
                {" / "}
                <Link to={`/samples/${a.sample_id}`} className="hover:underline">
                  {sample.data.sample_code}
                </Link>
              </>
            )}
          </span>
        }
        title={`${sample.data?.sample_code ?? ""} · ${a.tool} ${a.tool_version}`}
        subtitle={t("explorer.subtitle", {
          db: a.database_name ? `${a.database_name} ${a.database_version ?? ""}` : t("explorer.noDatabase"),
          assembly: `${params.assembly?.assembler ?? assembly.data?.assembler ?? "?"} ${params.assembly?.assembler_version ?? ""}${(params.assembly?.kind ?? assembly.data?.kind) === "polished" ? ` (${t("annotation.polished")})` : ""}`,
          date: fmtDate(a.created_at),
        })}
        actions={
          <>
            <Explain id="genome_explorer" />
            <Explain id="gc_skew" />
          </>
        }
      />
      {a.summary.synthetic_evidence?.length > 0 && <SyntheticNote evidence={a.summary.synthetic_evidence} />}
      <p className="text-xs text-muted-foreground">{t("annotation.predictions")}</p>
      <ExplorerViews annotation={a} contigs={assembly.data?.contigs} assembler={assembly.data?.assembler} sampleCode={sample.data?.sample_code} />
    </div>
  );
}

type ViewMode = "linear" | "circular";

/** The linear browser or the circular map of the same annotation; the address bar keeps which one, the feature open
 * in the side panel and its sequence, so switching views keeps the feature. */
function ExplorerViews({ annotation, contigs, assembler, sampleCode }: { annotation: Annotation; contigs: AssemblyContig[] | undefined; assembler: string | undefined; sampleCode: string | undefined }) {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const view: ViewMode = params.get("view") === "circular" ? "circular" : "linear";
  const setView = (v: ViewMode) => {
    const next = new URLSearchParams(v === "circular" ? { view: "circular" } : {});
    for (const k of v === "circular" ? ["feature", "contig"] : ["feature", "contig", "start", "end"]) {
      const value = params.get(k);
      if (value) next.set(k, value);
    }
    setParams(next);
  };
  return (
    <div className="space-y-3">
      <Segmented
        label={t("circular.view.label")}
        value={view}
        onChange={setView}
        options={[
          { value: "linear", label: t("circular.view.linear") },
          { value: "circular", label: t("circular.view.circular") },
        ]}
      />
      {view === "linear" ? (
        <Explorer annotation={annotation} contigs={contigs} assembler={assembler} />
      ) : (
        <CircularView annotation={annotation} contigs={contigs} assembler={assembler} sampleCode={sampleCode} />
      )}
    </div>
  );
}

function CircularView({ annotation, contigs, assembler, sampleCode }: { annotation: Annotation; contigs: AssemblyContig[] | undefined; assembler: string | undefined; sampleCode: string | undefined }) {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const options = useMemo(() => contigOptions(annotation.sequences, annotation.tool, contigs, assembler), [annotation, contigs, assembler]);
  const selected = params.get("feature") ? Number(params.get("feature")) : null;
  const select = (f: { id: number; contig: string } | null) =>
    setParams(f ? { view: "circular", feature: String(f.id), contig: f.contig } : { view: "circular" }, { replace: true });
  const showLinear = (f: MapFeature) => setParams({ contig: f.contig, feature: String(f.id) });
  if (!options.length) return <EmptyState title={t("explorer.noSequences")} />;
  return (
    <div className="space-y-3">
      <ExplorerSearch
        annotationId={annotation.id}
        contigs={options}
        current={params.get("contig") ?? options[0].id}
        onRegion={(contig, start, end) => setParams({ contig, start: String(start), end: String(end) })}
        onFeature={(f: AnnotationFeature) => select(f)}
      />
      <div className={selected != null ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px] lg:grid-cols-[minmax(0,1fr)_340px]" : ""}>
        <div className="min-w-0">
          <CircularExplorer annotation={annotation} contigs={options} sampleCode={sampleCode} selected={selected} onSelect={select} onShowLinear={showLinear} />
        </div>
        {selected != null && (
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <FeatureDetail annotation={annotation} featureId={selected} onClose={() => select(null)} variant="panel" />
          </aside>
        )}
      </div>
    </div>
  );
}

function Explorer({ annotation, contigs, assembler }: { annotation: Annotation; contigs: AssemblyContig[] | undefined; assembler: string | undefined }) {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const options = useMemo(
    () => contigOptions(annotation.sequences, annotation.tool, contigs, assembler),
    [annotation, contigs, assembler],
  );
  const initial = options.find((c) => c.id === params.get("contig") || c.name === params.get("contig")) ?? options[0];
  const [contigId, setContigId] = useState(initial?.id ?? "");
  const contig = options.find((c) => c.id === contigId) ?? options[0];
  const startParam = Number(params.get("start"));
  const endParam = Number(params.get("end"));
  const [view, setViewState] = useState<View>(() =>
    contig && startParam >= 1 && endParam >= startParam ? clampView(viewOf(startParam, endParam), contig.length) : { from: 0, to: contig?.length ?? 1 },
  );
  const [selected, setSelected] = useState<number | null>(() => (params.get("feature") ? Number(params.get("feature")) : null));
  const [marked, setMarked] = useState<Set<number>>(new Set());
  const [region, setRegion] = useState<View | null>(null);
  const [gc, setGc] = useState<GcSettings>({ window: null, step: null });
  const pendingFeature = useRef<number | null>(selected);

  const layout = useQuery({
    queryKey: ["explorerLayout", annotation.id, contig?.id],
    queryFn: () => api.annotationLayout(annotation.id, contig!.id),
    enabled: !!contig,
    staleTime: Infinity,
  });
  const features = layout.data?.contig === contig?.id ? layout.data.items : [];

  useEffect(() => {
    const id = pendingFeature.current;
    if (id == null || !layout.data || layout.data.contig !== contig?.id) return;
    const f = layout.data.items.find((x) => x.id === id);
    if (f && !(params.get("start") && params.get("end"))) setViewState(viewOfFeature(f, contig.length));
    pendingFeature.current = null;
  }, [layout.data, contig, params]);

  // Keep the place in the address bar so it can be bookmarked or shared; replaced, not pushed, while moving.
  useEffect(() => {
    if (!contig) return;
    const timer = setTimeout(() => {
      const r = regionOf(view);
      const next = new URLSearchParams({ contig: contig.id, start: String(r.start), end: String(r.end) });
      if (selected != null) next.set("feature", String(selected));
      if (next.toString() !== params.toString()) setParams(next, { replace: true });
    }, 400);
    return () => clearTimeout(timer);
  }, [contig, view, selected, params, setParams]);

  if (!contig) return <EmptyState title={t("explorer.noSequences")} />;
  const setView = (v: View) => setViewState(clampView(v, contig.length));
  const switchContig = (id: string, v?: View) => {
    const c = options.find((x) => x.id === id);
    if (!c) return;
    setContigId(id);
    setRegion(null);
    setViewState(clampView(v ?? { from: 0, to: c.length }, c.length));
  };
  const goTo = (id: string, start: number, end: number) => {
    const c = options.find((x) => x.id === id)!;
    const v = start === end ? { from: start - 500, to: start + 500 } : viewOf(start, end);
    if (id !== contig.id) switchContig(id, v);
    else setView(v);
    if (start !== end && !(start === 1 && end === c.length)) setRegion(viewOf(start, end));
  };
  const openFeature = (f: AnnotationFeature | FeatureLayoutItem) => {
    const target = "contig" in f ? f.contig : contig.id;
    const c = options.find((x) => x.id === target) ?? contig;
    const v = viewOfFeature(f as FeatureLayoutItem, c.length);
    if (c.id !== contig.id) switchContig(c.id, v);
    else setView(v);
    setSelected(f.id);
  };
  const toggleMark = (id: number) =>
    setMarked((m) => {
      const next = new Set(m);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const windowValue = gc.window ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1 text-xs">
          <span className="block text-muted-foreground">{t("explorer.contig")}</span>
          <Select value={contig.id} onChange={(e) => switchContig(e.target.value)} className="w-72">
            {options.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.name !== c.id ? ` (${c.id})` : ""} · {fmtBases(c.length)}
                {c.circular ? ` · ${t("explorer.circular")}` : ""}
              </option>
            ))}
          </Select>
        </label>
        <TopologyBadge circular={contig.circular} source={contig.circularSource} />
        <ExplorerSearch annotationId={annotation.id} contigs={options} current={contig.id} onRegion={goTo} onFeature={openFeature} />
        <label className="space-y-1 text-xs">
          <span className="block text-muted-foreground">{t("explorer.gcWindow")}</span>
          <Select
            value={windowValue}
            onChange={(e) => {
              const w = Number(e.target.value) || null;
              setGc({ window: w, step: w });
            }}
            className="w-32"
          >
            <option value={0}>{t("explorer.windowAutoOption")}</option>
            {WINDOWS.filter((w) => w <= contig.length).map((w) => (
              <option key={w} value={w}>
                {fmtInt(w)} bp
              </option>
            ))}
          </Select>
        </label>
        {gc.window && (
          <label className="space-y-1 text-xs">
            <span className="block text-muted-foreground">{t("explorer.gcStep")}</span>
            <Select value={gc.step ?? gc.window} onChange={(e) => setGc({ ...gc, step: Number(e.target.value) })} className="w-32">
              {STEP_DIVISORS.map((d) => (
                <option key={d} value={Math.max(1, Math.round(gc.window! / d))}>
                  {fmtInt(Math.max(1, Math.round(gc.window! / d)))} bp
                </option>
              ))}
            </Select>
          </label>
        )}
      </div>
      <ExplorerLegend />
      <div className={selected != null ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px] lg:grid-cols-[minmax(0,1fr)_340px]" : ""}>
        <div className="min-w-0 space-y-3">
          <GenomeBrowser
            annotationId={annotation.id}
            contig={contig}
            layout={layout.data?.contig === contig.id ? layout.data : undefined}
            layoutError={layout.error}
            view={view}
            onView={setView}
            selected={selected}
            onSelect={(f) => setSelected(f?.id ?? null)}
            marked={marked}
            onToggleMark={toggleMark}
            region={region}
            onRegion={setRegion}
            gc={gc}
          />
          {region && <RegionBar annotation={annotation} contig={contig} region={region} features={features} onClear={() => setRegion(null)} onZoom={() => setView(region)} />}
          <MarkedBar annotation={annotation} marked={marked} features={features} onClear={() => setMarked(new Set())} />
        </div>
        {selected != null && (
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <FeatureDetail annotation={annotation} featureId={selected} onClose={() => setSelected(null)} variant="panel">
              <label className="mt-3 flex items-center gap-2 border-t pt-3">
                <input type="checkbox" className="h-3.5 w-3.5 accent-[#00B4A6]" checked={marked.has(selected)} onChange={() => toggleMark(selected)} />
                {t("explorer.markForExport")}
              </label>
            </FeatureDetail>
          </aside>
        )}
      </div>
    </div>
  );
}

function TopologyBadge({ circular, source }: { circular: boolean | null; source: string | null }) {
  const t = useT();
  if (circular == null) return <Badge tone="neutral">{t("explorer.topologyUnknown")}</Badge>;
  return <Badge tone={circular ? "teal" : "neutral"}>{t(circular ? "explorer.circularBy" : "explorer.linearBy", { source: source ?? "?" })}</Badge>;
}
