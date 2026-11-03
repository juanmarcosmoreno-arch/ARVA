import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download, FileText, Loader2, Maximize2, Minus, Plus, Save, Search } from "lucide-react";
import { type PointerEvent, type WheelEvent, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useChartTheme } from "@/components/charts/theme";
import { downloadFigure, type FigureFormat } from "@/components/comparative/FigureCard";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import type { ComparisonResultRead, ComparisonSet } from "@/lib/comparative";
import { fmtCompact } from "@/lib/format";
import {
  DEFAULT_STYLE,
  type FieldValues,
  fieldValues,
  markedClades,
  type PhyloData,
  type PhyloStyle,
  type PNode,
  patristic,
  prepare,
  PRESENT,
  type RfResult,
  type Rooting,
  treeFigure,
} from "@/lib/phylo";
import { GROUP_PALETTE } from "@/lib/regions";

const LINK = "text-arva-royal hover:underline dark:text-arva-cyan";
const CHECK = "h-3.5 w-3.5 accent-arva-teal";

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The Tree Explorer: the inferred tree rooted as chosen (midpoint, outgroup or unrooted), rectangular or circular,
 * with zoom and pan, collapsible and colourable clades, leaf colours and metadata bands (sample metadata, MLST, AMR
 * genes, pangenome families), support values, a scale bar, search, patristic distances, comparison with another tree
 * (Robinson-Foulds) and SVG, PNG, PDF and Newick exports. */
export function TreeView({ result, set }: { result: ComparisonResultRead; set: ComparisonSet }) {
  const t = useT();
  const theme = useChartTheme();
  const initial = result.data as unknown as PhyloData;
  const [data, setData] = useState<PhyloData>(initial);
  const [style, setStyle] = useState<PhyloStyle>({ ...DEFAULT_STYLE, ...initial.view.style });
  const [dirty, setDirty] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<PNode | null>(null);
  const [distanceTo, setDistanceTo] = useState("");
  const [familyBand, setFamilyBand] = useState("");
  const [other, setOther] = useState("");
  const [by, setBy] = useState<"leaf" | "genome">("leaf");
  const [markDiff, setMarkDiff] = useState(true);
  const [box, setBox] = useState<Box | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; box: Box } | null>(null);
  const meta = useQuery({ queryKey: ["phyloMeta", result.id], queryFn: () => api.phyloMetadata(result.id) });
  const pangenomeId = set.results.find((r) => r.analysis === "pangenome")?.id ?? null;
  const needsFamilies = style.bands.some((b) => b.startsWith("family:")) || style.leaf_color_field?.startsWith("family:");
  const pangenome = useQuery({ queryKey: ["comparisonResult", pangenomeId], queryFn: () => api.comparisonResult(pangenomeId!),
    enabled: Boolean(pangenomeId && needsFamilies) });
  const others = set.results.filter((r) => r.analysis === "phylogeny" && r.id !== result.id);
  const compare = useQuery({ queryKey: ["phyloCompare", result.id, other, by], queryFn: () => api.phyloCompare(result.id, other, by),
    enabled: Boolean(other), retry: false });
  const save = useMutation({
    mutationFn: (rooting: Rooting) => api.savePhyloView(result.id, rooting, style),
    onSuccess: (d) => {
      setData(d);
      setDirty(false);
      setSelected(null);
    },
  });
  const change = (patch: Partial<PhyloStyle>) => {
    setStyle((s) => ({ ...s, ...patch }));
    setDirty(true);
  };
  const fieldLabel = (k: string) => (k.startsWith("custom:") ? k.slice(7) : k.startsWith("amr:") ? `AMR ${k.slice(4)}`
    : k.startsWith("family:") ? k.slice(7) : t(`pangenome.field.${k}` as TranslationKey));
  const pan = pangenome.data?.data as { genomes: { label: string }[]; families: { name: string; presence: string }[] } | undefined;
  const values = (key: string | null): FieldValues | null => {
    if (!key) return null;
    const fam = key.startsWith("family:") && pan ? pan.families.find((f) => f.name === key.slice(7)) : null;
    return fieldValues(key, data.leaves, meta.data,
      fam ? { name: fam.name, genomes: pan!.genomes.map((g) => g.label), presence: fam.presence } : null, fieldLabel(key));
  };
  const leafColor = values(style.leaf_color_field);
  const bands = style.bands.map(values).filter((b): b is FieldValues => b !== null);
  const root = useMemo(() => prepare(data.rooted, style), [data.rooted, style]);
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return new Set(q ? root.leaves.filter((l) => l.toLowerCase().includes(q)) : []);
  }, [query, root]);
  const rf = compare.data as RfResult | undefined;
  const marked = rf && markDiff && rf.by === "leaf" ? markedClades(root, rf.only_a) : undefined;
  const dark = theme.surface !== "#FFFFFF";
  const unit = result.method === "nj" ? t(`phylo.unit.${data.distances?.kind ?? "p"}` as TranslationKey) : t("phylo.unit.subst");
  const { fig, hits } = treeFigure(data.rooted, style, {
    theme: { text: theme.text, muted: theme.muted, branch: dark ? "#CBD5E1" : "#334155", highlight: "#F0E442", absent: dark ? "#334155" : "#E2E8F0" },
    leafColor, bands, highlight: matches, marked, supportMax: data.support?.max ?? 100, unit,
    collapsedLabel: (n) => t("phylo.collapsedLeaves", { n }),
  });
  const view = box ?? { x: 0, y: 0, w: fig.width, h: fig.height };
  const zoom = (factor: number, cx = view.x + view.w / 2, cy = view.y + view.h / 2) => {
    const w = Math.min(fig.width * 4, Math.max(40, view.w * factor));
    const h = (w / view.w) * view.h;
    setBox({ x: cx - ((cx - view.x) * w) / view.w, y: cy - ((cy - view.y) * h) / view.h, w, h });
  };
  const onWheel = (e: WheelEvent<SVGSVGElement>) => {
    const r = svgRef.current!.getBoundingClientRect();
    zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, view.x + ((e.clientX - r.left) / r.width) * view.w, view.y + ((e.clientY - r.top) / r.height) * view.h);
  };
  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).getAttribute("data-hit")) return;
    drag.current = { x: e.clientX, y: e.clientY, box: view };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!drag.current) return;
    const r = svgRef.current!.getBoundingClientRect();
    const d = drag.current;
    setBox({ ...d.box, x: d.box.x - ((e.clientX - d.x) / r.width) * d.box.w, y: d.box.y - ((e.clientY - d.y) / r.height) * d.box.h });
  };
  const exportAs = (format: FigureFormat) => svgRef.current && downloadFigure(format, fig, svgRef.current, theme.surface,
    `ARVA_tree_${set.name.replace(/[^A-Za-z0-9._-]/g, "_")}_${result.method}`);
  const fieldOptions = [
    ...(meta.data?.fields.filter((f) => f.recorded > 0).map((f) => f.key) ?? []),
    ...(meta.data?.amr.genes.map((g) => `amr:${g}`) ?? []),
  ];
  const leafInfo = selected && !selected.children.length ? data.leaves.find((l) => l.name === selected.name) : null;
  const rooting = data.view.rooting;
  const kind = data.source.kind;
  const distanceTree = result.method === "nj";
  const dist = leafInfo && distanceTo ? patristic(root, leafInfo.name, distanceTo) : null;
  return (
    <div className="space-y-4">
      <div className="grid gap-2 text-xs sm:grid-cols-3 xl:grid-cols-6">
        {[
          [t("phylo.tile.method"), t(`phylo.methodName.${result.method}` as TranslationKey)],
          [t("phylo.tile.source"), `${t(`phylo.sourceKind.${kind}` as TranslationKey)}${data.source.family ? ` · ${data.source.family}` : ""}`],
          [t("phylo.tile.leaves"), fmtCompact(root.leaves.length)],
          [t("phylo.tile.model"), data.iqtree?.model ?? (distanceTree ? t(`phylo.unit.${data.distances?.kind ?? "p"}` as TranslationKey) : "GTR+CAT, Gamma20")],
          [t("phylo.tile.support"), data.support?.label ?? t("phylo.noSupport")],
          [t("phylo.tile.sites"), data.alignment ? t("phylo.sitesLine", { columns: fmtCompact(data.alignment.columns), variable: fmtCompact(data.alignment.variable) }) : "—"],
        ].map(([k, v]) => (
          <div key={k} className="rounded-lg border px-3 py-2">
            <p className="text-muted-foreground">{k}</p>
            <p className="font-medium">{v}</p>
          </div>
        ))}
      </div>
      {distanceTree && kind !== "ani_matrix" && (
        <p className="flex gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>{t("phylo.note.distance")}</span>
        </p>
      )}
      {data.snp_columns !== undefined && (
        <p className="text-xs text-muted-foreground">
          {t("phylo.snpLine", { n: fmtCompact(data.snp_columns), how: t(`phylo.constant.${String(result.parameters.constant_sites)}` as TranslationKey) })}
        </p>
      )}
      <div className="flex flex-wrap items-end gap-3 text-xs">
        <Field label={t("phylo.layout")}>
          <Select value={style.layout} onChange={(e) => change({ layout: e.target.value as PhyloStyle["layout"] })}>
            <option value="rectangular">{t("phylo.layoutRect")}</option>
            <option value="circular">{t("phylo.layoutCircular")}</option>
          </Select>
        </Field>
        <Field label={t("phylo.rooting")}>
          <Select value={rooting.method} onChange={(e) => {
            const m = e.target.value as Rooting["method"];
            if (m !== "outgroup") save.mutate({ method: m, outgroup: [] });
          }}>
            <option value="midpoint">{t("phylo.root.midpoint")}</option>
            <option value="none">{t("phylo.root.none")}</option>
            {rooting.method === "outgroup" && <option value="outgroup">{t("phylo.rootOutgroupLine", { names: rooting.outgroup.join(", ") })}</option>}
          </Select>
        </Field>
        <Field label={t("phylo.leafColour")}>
          <Select value={style.leaf_color_field ?? ""} onChange={(e) => change({ leaf_color_field: e.target.value || null })}>
            <option value="">{t("phylo.none")}</option>
            {fieldOptions.map((k) => <option key={k} value={k}>{fieldLabel(k)}</option>)}
          </Select>
        </Field>
        <Field label={t("phylo.addBand")}>
          <Select value="" onChange={(e) => e.target.value && style.bands.length < 12 && !style.bands.includes(e.target.value) && change({ bands: [...style.bands, e.target.value] })}>
            <option value="">{t("phylo.chooseField")}</option>
            {fieldOptions.map((k) => <option key={k} value={k}>{fieldLabel(k)}</option>)}
          </Select>
        </Field>
        {pangenomeId && (
          <Field label={t("phylo.familyBand")}>
            <div className="flex gap-1">
              <Input value={familyBand} onChange={(e) => setFamilyBand(e.target.value)} className="w-28" />
              <Button size="sm" variant="outline" disabled={!familyBand.trim() || style.bands.length >= 12}
                onClick={() => { change({ bands: [...style.bands, `family:${familyBand.trim()}`] }); setFamilyBand(""); }}>
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </div>
          </Field>
        )}
        <Field label={t("phylo.search")}>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} className="w-40 pl-7" />
          </div>
        </Field>
        <Field label={t("phylo.fontSize")}>
          <Input type="number" min={6} max={24} value={style.font_size} onChange={(e) => change({ font_size: Math.min(24, Math.max(6, Number(e.target.value) || 11)) })} className="w-16" />
        </Field>
        {data.support && (
          <Field label={t("phylo.supportMin")} hint={t("phylo.supportMinHint")}>
            <Input type="number" min={0} max={100} value={style.support_min} onChange={(e) => change({ support_min: Math.min(100, Math.max(0, Number(e.target.value) || 0)) })} className="w-16" />
          </Field>
        )}
        <div className="flex flex-col gap-1">
          {([["show_support", "phylo.showSupport"], ["show_lengths", "phylo.showLengths"], ["ladderize", "phylo.ladderize"], ["align_labels", "phylo.alignLabels"]] as const).map(([k, label]) => (
            <label key={k} className="flex items-center gap-1.5">
              <input type="checkbox" className={CHECK} checked={style[k]} onChange={(e) => change({ [k]: e.target.checked })} />
              {t(label)}
            </label>
          ))}
        </div>
      </div>
      {style.bands.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {style.bands.map((b) => (
            <button key={b} onClick={() => change({ bands: style.bands.filter((x) => x !== b) })} className="rounded-full border px-2 py-0.5 hover:bg-muted" title={t("phylo.removeBand")}>
              {fieldLabel(b)} ×
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1">
        <Button size="sm" variant="ghost" onClick={() => zoom(1 / 1.4)} aria-label={t("phylo.zoomIn")}><Plus className="h-3.5 w-3.5" /></Button>
        <Button size="sm" variant="ghost" onClick={() => zoom(1.4)} aria-label={t("phylo.zoomOut")}><Minus className="h-3.5 w-3.5" /></Button>
        <Button size="sm" variant="ghost" onClick={() => setBox(null)} aria-label={t("phylo.zoomReset")}><Maximize2 className="h-3.5 w-3.5" /></Button>
        <span className="mx-1 text-xs text-muted-foreground">{t("phylo.zoomHint")}</span>
        <span className="flex-1" />
        <Explain id="phylo_tree" compact className="p-1.5" />
        {(["svg", "png", "pdf"] as const).map((f) => (
          <Button key={f} size="sm" variant="ghost" onClick={() => exportAs(f)} aria-label={t("region.export", { format: f.toUpperCase() })}>
            <Download className="h-3.5 w-3.5" /> {f.toUpperCase()}
          </Button>
        ))}
        <a href={api.phyloNewickUrl(result.id, true)} className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs hover:bg-muted"><Download className="h-3.5 w-3.5" /> {t("phylo.newickRooted")}</a>
        <a href={api.phyloNewickUrl(result.id, false)} className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs hover:bg-muted"><Download className="h-3.5 w-3.5" /> {t("phylo.newickUnrooted")}</a>
        <a href={api.phyloReportUrl(result.id)} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs hover:bg-muted"><FileText className="h-3.5 w-3.5" /> {t("phylo.report")}</a>
        <Button size="sm" variant={dirty ? "primary" : "outline"} onClick={() => save.mutate(rooting)} disabled={save.isPending}>
          {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} {t("phylo.saveView")}
        </Button>
      </div>
      <ErrorNote error={save.error} />
      <div className="space-y-4">
        <div className="overflow-hidden rounded-lg border">
          <svg ref={svgRef} viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} role="img" aria-label={t("phylo.figureLabel")} preserveAspectRatio="xMinYMin meet"
            fontFamily="Helvetica, Arial, sans-serif" className="block w-full cursor-grab touch-none select-none active:cursor-grabbing"
            style={{ height: Math.min(620, Math.max(260, fig.height + 24)) }}
            onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => { drag.current = null; }}>
            {fig.prims.map((p, i) => {
              if (p.kind === "line") return <line key={i} x1={p.x1} y1={p.y1} x2={p.x2} y2={p.y2} stroke={p.stroke} strokeWidth={p.width} strokeLinecap="round" strokeDasharray={p.dash ? "3 2" : undefined} />;
              if (p.kind === "text") {
                return (
                  <text key={i} x={p.x} y={p.y} fontSize={p.size} textAnchor={p.anchor} fill={p.fill} fontStyle={p.italic ? "italic" : undefined}
                    fontWeight={p.bold ? 600 : undefined} transform={p.rotate ? `rotate(${p.rotate} ${p.x} ${p.y})` : undefined}>{p.text}</text>
                );
              }
              return <polygon key={i} points={p.points.map(([x, y]) => `${x},${y}`).join(" ")} fill={p.fill} fillOpacity={p.opacity} stroke={p.stroke} strokeWidth={p.width} />;
            })}
            <g data-export="skip">
              {hits.map((h) => (
                <circle key={h.node.id} data-hit="1" cx={h.x} cy={h.y} r={h.node.children.length ? 5 : 7} fill={selected?.key === h.node.key ? theme.primary : "transparent"}
                  fillOpacity={0.5} className="cursor-pointer focus:outline-none focus-visible:[stroke-width:2px]" stroke={theme.primary} strokeWidth={0}
                  tabIndex={0} role="button" aria-pressed={selected?.key === h.node.key}
                  aria-label={h.node.children.length ? t("phylo.cladeTitle", { n: h.node.leaves.length, support: h.node.supportText ?? "—" }) : h.node.name ?? ""}
                  onClick={() => { setSelected(h.node); setDistanceTo(""); }}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(h.node); setDistanceTo(""); } }}>
                  <title>{h.node.children.length ? t("phylo.cladeTitle", { n: h.node.leaves.length, support: h.node.supportText ?? "—" }) : h.node.name ?? ""}</title>
                </circle>
              ))}
            </g>
          </svg>
        </div>
        <aside className="grid items-start gap-3 text-xs lg:grid-cols-3">
          {selected ? (
            <section className="space-y-2 rounded-lg border p-3">
              {leafInfo ? (
                <>
                  <p className="text-sm font-medium">{leafInfo.name}</p>
                  {leafInfo.genome && <p>{t("phylo.genome")}: {leafInfo.genome}</p>}
                  {leafInfo.sample_id && <Link to={`/samples/${leafInfo.sample_id}`} className={LINK}>{t("phylo.openSample")}</Link>}
                  {leafInfo.missing_fraction !== undefined && <p className="text-muted-foreground">{t("phylo.missing", { pct: (leafInfo.missing_fraction * 100).toFixed(1) })}</p>}
                  {meta.data && leafInfo.genome && (
                    <dl className="grid grid-cols-2 gap-x-2">
                      {meta.data.fields.filter((f) => f.recorded > 0).map((f) => (
                        <div key={f.key} className="contents">
                          <dt className="text-muted-foreground">{fieldLabel(f.key)}</dt>
                          <dd>{f.values[meta.data!.genomes.indexOf(leafInfo.genome!)] ?? "—"}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  <Field label={t("phylo.distanceTo")}>
                    <Select value={distanceTo} onChange={(e) => setDistanceTo(e.target.value)}>
                      <option value="">—</option>
                      {root.leaves.filter((l) => l !== leafInfo.name).map((l) => <option key={l} value={l}>{l}</option>)}
                    </Select>
                  </Field>
                  {dist !== null && <p>{t("phylo.patristic", { d: dist.toPrecision(4), unit })}</p>}
                  <Button size="sm" variant="outline" onClick={() => save.mutate({ method: "outgroup", outgroup: [leafInfo.name] })}>{t("phylo.rootHere")}</Button>
                </>
              ) : (
                <>
                  <p className="text-sm font-medium">{t("phylo.cladeTitle", { n: selected.leaves.length, support: selected.supportText ?? "—" })}</p>
                  <p className="text-muted-foreground">{selected.leaves.slice(0, 8).join(", ")}{selected.leaves.length > 8 ? " …" : ""}</p>
                  {selected.parent && (
                    <div className="flex flex-wrap gap-1">
                      <Button size="sm" variant="outline" onClick={() => change({ collapsed: style.collapsed.includes(selected.key) ? style.collapsed.filter((k) => k !== selected.key) : [...style.collapsed, selected.key] })}>
                        {style.collapsed.includes(selected.key) ? t("phylo.expand") : t("phylo.collapse")}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => save.mutate({ method: "outgroup", outgroup: selected.leaves })}>{t("phylo.rootHere")}</Button>
                    </div>
                  )}
                  <p className="text-muted-foreground">{t("phylo.colourClade")}</p>
                  <div className="flex flex-wrap gap-1">
                    {GROUP_PALETTE.slice(0, 10).map((c) => (
                      <button key={c} className="h-5 w-5 rounded border" style={{ background: c }} aria-label={c}
                        onClick={() => change({ branch_colors: { ...style.branch_colors, [selected.key]: c } })} />
                    ))}
                    <button className="h-5 rounded border px-1" onClick={() => {
                      const rest = { ...style.branch_colors };
                      delete rest[selected.key];
                      change({ branch_colors: rest });
                    }}>{t("phylo.clearColour")}</button>
                  </div>
                </>
              )}
            </section>
          ) : (
            <p className="rounded-lg border p-3 text-muted-foreground">{t("phylo.clickHint")}</p>
          )}
          {(leafColor || bands.length > 0) && (
            <section className="space-y-2 rounded-lg border p-3">
              <p className="font-medium">{t("phylo.legend")}</p>
              {[leafColor, ...bands].map((f, i) => f && (
                <div key={`${i}-${f.key}`}>
                  <p className="text-muted-foreground">{t(f === leafColor && i === 0 ? "phylo.legendLeaves" : "phylo.legendBand", { field: f.label })}</p>
                  <div className="flex flex-wrap gap-x-2">
                    {f.presence ? (
                      <><Swatch c={PRESENT} label={t("phylo.present")} /><Swatch c={dark ? "#334155" : "#E2E8F0"} label={t("phylo.absent")} /></>
                    ) : [...f.colors].map(([v, c]) => <Swatch key={v} c={c} label={v} />)}
                  </div>
                </div>
              ))}
              <p className="text-muted-foreground">{t("phylo.legendNote")}</p>
            </section>
          )}
          <section className="space-y-2 rounded-lg border p-3">
            <p className="font-medium">{t("phylo.compare")}</p>
            {others.length === 0 ? <p className="text-muted-foreground">{t("phylo.compareNone")}</p> : (
              <>
                <Select value={other} onChange={(e) => setOther(e.target.value)}>
                  <option value="">{t("phylo.compareChoose")}</option>
                  {others.map((r) => <option key={r.id} value={r.id}>{r.tool} · {r.method} · {r.id.slice(0, 8)}</option>)}
                </Select>
                <Select value={by} onChange={(e) => setBy(e.target.value as "leaf" | "genome")}>
                  <option value="leaf">{t("phylo.byLeaf")}</option>
                  <option value="genome">{t("phylo.byGenome")}</option>
                </Select>
                <ErrorNote error={compare.error} />
                {rf && (
                  <>
                    <p>{t("phylo.rfLine", { rf: rf.rf, max: rf.max, norm: rf.normalized.toFixed(2), shared: rf.shared, leaves: rf.common_leaves })}</p>
                    {(rf.only_in_a_leaves.length > 0 || rf.only_in_b_leaves.length > 0) && (
                      <p className="text-muted-foreground">{t("phylo.rfLeavesDropped", { n: rf.only_in_a_leaves.length + rf.only_in_b_leaves.length })}</p>
                    )}
                    {rf.by === "leaf" && (
                      <label className="flex items-center gap-1.5">
                        <input type="checkbox" className={CHECK} checked={markDiff} onChange={(e) => setMarkDiff(e.target.checked)} />
                        {t("phylo.markDiff")}
                      </label>
                    )}
                    <p className="text-muted-foreground">{t("phylo.rfNote")}</p>
                  </>
                )}
              </>
            )}
          </section>
        </aside>
      </div>
      {data.rooting.error && <p className="text-xs text-danger">{t("phylo.rootingLost")}</p>}
      <p className="text-xs text-muted-foreground">{t(`phylo.rootNote.${data.rooting.method}` as TranslationKey, { leaves: (data.rooting.leaves ?? []).join(", "), outgroup: (data.rooting.outgroup ?? []).join(", ") })}</p>
    </div>
  );
}

function Swatch({ c, label }: { c: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: c }} />
      {label}
    </span>
  );
}
