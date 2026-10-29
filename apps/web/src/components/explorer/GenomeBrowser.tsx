import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Download, Expand, Loader2, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { type ChartTheme, useChartTheme } from "@/components/charts/theme";
import { Button } from "@/components/ui/button";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import {
  BASE_PX,
  type ContigOption,
  covers,
  densityRuns,
  featureGroup,
  type FeatureGroup,
  featureLabel,
  formatPosition,
  intergenic,
  MAX_GLYPHS,
  mergePixels,
  neighbour,
  panView,
  type Piece,
  piecesOf,
  assignLanes,
  regionOf,
  span,
  strandGroup,
  type StrandGroup,
  ticks,
  toPos,
  toX,
  trackRequest,
  type View,
  viewOfFeature,
  visiblePieces,
  zoomView,
} from "@/lib/explorer";
import { fmtBp, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import { KIND_TONE, kindText, ringOf } from "@/lib/amr";
import { categoryKey, isWholeElement } from "@/lib/mobile";
import type { AmrMapHit, CoverageTrack, FeatureLayout, FeatureLayoutItem, GcTrack } from "@/lib/types";

const GUTTER = 96;
const RULER_H = 30;
const LANE_H = 15;
const GLYPH_H = 10;
const LINE_H = 64;
const SEQ_H = 30;
const MSG_H = 22;
const GAP = 10;

/** Glyph colours by feature group: the first three slots of ARVA's validated chart palette (they pass the
 * all-pairs CVD, normal-vision and 3:1 contrast checks in both modes, so any two neighbouring genes stay apart);
 * assembly gaps take the muted neutral, since a gap is no sequence rather than a kind of element. */
export function groupColour(theme: ChartTheme, group: FeatureGroup): string {
  return group === "gap" ? theme.muted : theme.series[group === "coding" ? 0 : group === "rna" ? 1 : 2];
}

/** The AMR ring and track (AMR genes, point mutations, stress response) and the virulence ring: the palette's slots
 * after the custom ring's. */
export const amrColour = (theme: ChartTheme, ring: "amr" | "virulence") => theme.series[ring === "amr" ? 4 : 5];

/** The diverging pair for GC skew: blue (G > C) and red (C > G), validated against both chart surfaces. */
export const SKEW = { light: { pos: "#2B54C4", neg: "#e34948" }, dark: { pos: "#4A88EC", neg: "#e66767" } };

export interface GcSettings {
  window: number | null;
  step: number | null;
}

interface Props {
  annotationId: string;
  contig: ContigOption;
  layout: FeatureLayout | undefined;
  layoutError: unknown;
  view: View;
  onView: (v: View) => void;
  selected: number | null;
  onSelect: (f: FeatureLayoutItem | null) => void;
  marked: Set<number>;
  onToggleMark: (id: number) => void;
  region: View | null;
  onRegion: (v: View | null) => void;
  gc: GcSettings;
}

type Drag = { kind: "pan" | "select"; x0: number; view: View; feature: number | null; moved: boolean; mark: boolean };

/**
 * The linear genome browser, drawn as SVG: elements keep native hit-testing, focus and accessible titles, text stays
 * crisp, and the view can be saved as an SVG figure. Only what is in the view is drawn, and the number of elements
 * stays bounded: individual glyphs up to MAX_GLYPHS pieces, otherwise per-pixel density runs; intergenic regions
 * merge per pixel; line tracks are one path of at most two points per pixel.
 */
export function GenomeBrowser(p: Props) {
  const t = useT();
  const theme = useChartTheme();
  const dark = theme.surface !== "#FFFFFF";
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(1000);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [hovered, setHovered] = useState<FeatureLayoutItem | null>(null);
  const drag = useRef<Drag | null>(null);
  const length = p.contig.length;
  const plotW = Math.max(200, width - GUTTER);
  const v = p.view;

  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => entry.contentRect.width > 0 && setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const features = useMemo(() => p.layout?.items ?? [], [p.layout]);
  const { pieces, lanes } = useMemo(() => {
    const ps = piecesOf(features, length);
    return { pieces: ps, lanes: assignLanes(ps) };
  }, [features, length]);
  const amrRun = useQuery({ queryKey: ["annotationAmr", p.annotationId], queryFn: () => api.annotationAmr(p.annotationId), staleTime: 60_000 });
  const amrHits = useMemo(() => (amrRun.data?.hits ?? []).filter((h) => h.contig === p.contig.id && h.start != null), [amrRun.data, p.contig.id]);
  const vfdbRun = useQuery({ queryKey: ["annotationVirulence", p.annotationId], queryFn: () => api.annotationVirulence(p.annotationId), staleTime: 60_000 });
  const mobileRun = useQuery({ queryKey: ["annotationMobile", p.annotationId], queryFn: () => api.annotationMobile(p.annotationId), staleTime: 60_000 });
  const vfdbItems = useMemo<TrackItem[]>(
    () =>
      (vfdbRun.data?.hits ?? [])
        .filter((h) => h.contig === p.contig.id)
        .map((h) => ({
          id: h.id,
          start: h.start,
          end: h.end,
          whole: h.hit_kind === "complete" || h.hit_kind === "complete_gaps",
          featureId: h.feature?.feature_id ?? null,
          title: [`${h.gene} · ${t("virulence.sourceName.vfdb")}`, h.vf_name ?? h.product ?? "", h.vf_category ?? "", `${t(`mobile.completeness.${["complete", "complete_gaps", "partial", "contig_end"].includes(h.hit_kind) ? h.hit_kind : "unknown"}` as TranslationKey)} · ${t("amr.col.identity")} ${fmtNum(h.identity ?? 0, 2)} · ${t("amr.col.coverage")} ${fmtNum(h.coverage ?? 0, 2)}`, `${fmtInt(h.start)}–${fmtInt(h.end)} (${h.strand ?? "?"})`, t("virulence.notPhenotype")].filter(Boolean).join("\n"),
        })),
    [vfdbRun.data, p.contig.id, t],
  );
  const mobileItems = useMemo<TrackItem[]>(
    () =>
      (mobileRun.data?.elements ?? [])
        .filter((e) => e.contig === p.contig.id)
        .map((e) => ({
          id: e.id,
          start: e.start,
          end: e.end,
          whole: isWholeElement(e),
          featureId: e.feature?.feature_id ?? null,
          title: [`${e.element ?? "?"} · ${t(categoryKey(e.category))}`, e.element_type ?? "", t(`mobile.method.${e.method}` as TranslationKey), `${fmtInt(e.start)}–${fmtInt(e.end)} (${e.strand ?? "?"})`].filter(Boolean).join("\n"),
        })),
    [mobileRun.data, p.contig.id, t],
  );
  const gaps = useMemo(() => intergenic(features, length), [features, length]);
  const visible = useMemo(() => visiblePieces(pieces, v), [pieces, v]);
  const detailed = visible.length <= MAX_GLYPHS;
  const runs = useMemo(() => (detailed ? null : densityRuns(visible, v, plotW)), [detailed, visible, v, plotW]);
  const gapPixels = useMemo(() => mergePixels(gaps, v, plotW), [gaps, v, plotW]);

  const tile = trackRequest(v, length, plotW);
  const tracks = useQuery({
    queryKey: ["explorerTracks", p.annotationId, p.contig.id, tile.start, tile.end, tile.bins, p.gc.window, p.gc.step],
    queryFn: () => api.annotationTracks(p.annotationId, { contig: p.contig.id, ...tile, window: p.gc.window, step: p.gc.step }),
    placeholderData: keepPreviousData,
  });
  const trackData = tracks.data && tracks.data.contig === p.contig.id ? tracks.data : undefined;
  const showBases = span(v) <= plotW / BASE_PX;
  const seq = useQuery({
    queryKey: ["explorerSequence", p.annotationId, p.contig.id, tile.start, tile.end],
    queryFn: () => api.annotationSequence(p.annotationId, p.contig.id, tile.start, tile.end),
    enabled: showBases,
    placeholderData: keepPreviousData,
  });
  const seqData = seq.data && seq.data.contig === p.contig.id && covers(seq.data, v) ? seq.data : undefined;

  // Vertical layout
  const nPlus = Math.max(1, lanes["+"]);
  const nMinus = Math.max(1, lanes["-"]);
  const nMid = Math.max(1, lanes["."]);
  const yPlus = RULER_H + 4;
  const yMid = yPlus + nPlus * LANE_H;
  const yMinus = yMid + nMid * LANE_H;
  const yAmr = yMinus + nMinus * LANE_H + GAP;
  const amrH = amrRun.data?.run ? LANE_H + 4 : 0;
  const yVfdb = yAmr + amrH + (amrH ? GAP : 0);
  const vfdbH = vfdbRun.data?.run ? LANE_H + 4 : 0;
  const yMobile = yVfdb + vfdbH + (vfdbH ? GAP : 0);
  const mobileH = Object.values(mobileRun.data?.runs ?? {}).some(Boolean) ? LANE_H + 4 : 0;
  const yGc = yMobile + mobileH + (mobileH ? GAP : 0);
  const ySkew = yGc + LINE_H + GAP;
  const yCov = ySkew + LINE_H + GAP;
  const covH = trackData?.coverage.available ? LINE_H : MSG_H;
  const ySeq = yCov + covH + GAP;
  const height = ySeq + (showBases ? SEQ_H : MSG_H) + 4;

  const x = (pos: number) => GUTTER + toX(pos, v, plotW);
  const laneY = (piece: Piece) => {
    const g = strandGroup(piece.feature.strand);
    if (g === "+") return yPlus + (nPlus - 1 - piece.lane) * LANE_H;
    if (g === "-") return yMinus + piece.lane * LANE_H;
    return yMid + piece.lane * LANE_H;
  };

  // Wheel: zoom around the pointer; horizontal wheel or Shift+wheel pans. Registered as non-passive so the page
  // does not scroll while the pointer is over the tracks.
  const viewRef = useRef(v);
  viewRef.current = v;
  const onViewRef = useRef(p.onView);
  onViewRef.current = p.onView;
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left - GUTTER;
      if (px < 0) return;
      e.preventDefault();
      const cur = viewRef.current;
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        const d = (e.shiftKey ? e.deltaY : e.deltaX) * (span(cur) / plotW);
        onViewRef.current(panView(cur, d, length));
      } else {
        onViewRef.current(zoomView(cur, Math.exp(e.deltaY * 0.0015), toPos(px, cur, plotW), length));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [length, plotW]);

  const localX = (e: ReactPointerEvent) => e.clientX - (svg.current?.getBoundingClientRect().left ?? 0) - GUTTER;
  const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button > 0) return;
    const target = (e.target as Element).closest("[data-feature]");
    const y = e.clientY - (svg.current?.getBoundingClientRect().top ?? 0);
    drag.current = {
      kind: y < RULER_H || e.shiftKey ? "select" : "pan",
      x0: localX(e),
      view: v,
      feature: target ? Number(target.getAttribute("data-feature")) : null,
      moved: false,
      mark: e.ctrlKey || e.metaKey,
    };
    svg.current?.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const lx = localX(e);
    setHoverX(lx >= 0 && lx <= plotW ? lx : null);
    const d = drag.current;
    if (!d) return;
    if (Math.abs(lx - d.x0) > 3) d.moved = true;
    if (!d.moved) return;
    if (d.kind === "pan") p.onView(panView(d.view, -(lx - d.x0) * (span(d.view) / plotW), length));
    else {
      const a = toPos(Math.max(0, Math.min(plotW, d.x0)), d.view, plotW);
      const b = toPos(Math.max(0, Math.min(plotW, lx)), d.view, plotW);
      p.onRegion({ from: Math.floor(Math.min(a, b)), to: Math.ceil(Math.max(a, b)) });
    }
  };
  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved) return;
    if (d.feature != null) {
      const f = features.find((x) => x.id === d.feature) ?? null;
      if (f && d.mark) p.onToggleMark(f.id);
      else p.onSelect(f);
    } else if (d.kind === "select") p.onRegion(null);
  };

  const zoom = (factor: number) => p.onView(zoomView(v, factor, (v.from + v.to) / 2, length));
  const pan = (fraction: number) => p.onView(panView(v, fraction * span(v), length));
  const step = (dir: 1 | -1) => {
    const f = neighbour(features, p.selected, dir, v);
    if (f) {
      p.onSelect(f);
      if (!(Math.min(f.start, f.end) - 1 >= v.from && Math.max(f.start, f.end) <= v.to)) p.onView(viewOfFeature(f, length));
    }
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    const keys: Record<string, () => void> = {
      ArrowLeft: () => pan(e.shiftKey ? -0.5 : -0.1),
      ArrowRight: () => pan(e.shiftKey ? 0.5 : 0.1),
      "+": () => zoom(0.5),
      "=": () => zoom(0.5),
      "-": () => zoom(2),
      "0": () => p.onView({ from: 0, to: length }),
      Home: () => p.onView({ from: 0, to: length }),
      "]": () => step(1),
      "[": () => step(-1),
      Escape: () => (p.region ? p.onRegion(null) : p.onSelect(null)),
    };
    const action = keys[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  };

  const saveSvg = () => {
    if (!svg.current) return;
    const clone = svg.current.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const r = regionOf(v);
    const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `arva_explorer_${p.contig.name.replace(/[^A-Za-z0-9._-]+/g, "_")}_${r.start}-${r.end}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const r = regionOf(v);
  const { step: tickStep, positions } = ticks(v, plotW);
  const hoverPos = hoverX != null ? Math.floor(toPos(hoverX, v, plotW)) + 1 : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Button size="sm" variant="outline" onClick={() => pan(-0.5)} aria-label={t("explorer.panLeftFar")} title={t("explorer.panLeftFar")}>
          <ChevronsLeft className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => pan(-0.1)} aria-label={t("explorer.panLeft")} title={t("explorer.panLeft")}>
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => pan(0.1)} aria-label={t("explorer.panRight")} title={t("explorer.panRight")}>
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => pan(0.5)} aria-label={t("explorer.panRightFar")} title={t("explorer.panRightFar")}>
          <ChevronsRight className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => zoom(0.5)} aria-label={t("explorer.zoomIn")} title={t("explorer.zoomIn")}>
          <ZoomIn className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => zoom(2)} aria-label={t("explorer.zoomOut")} title={t("explorer.zoomOut")}>
          <ZoomOut className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={() => p.onView({ from: 0, to: length })} aria-label={t("explorer.whole")} title={t("explorer.whole")}>
          <Maximize2 className="h-3.5 w-3.5" />
        </Button>
        {p.region && (
          <Button size="sm" variant="outline" onClick={() => p.onView(p.region!)}>
            <Expand className="h-3.5 w-3.5" /> {t("explorer.zoomToRegion")}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => step(-1)}>
          {t("explorer.prevFeature")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => step(1)}>
          {t("explorer.nextFeature")}
        </Button>
        <span className="ml-2 font-mono text-xs tabular-nums" aria-live="polite">
          {p.contig.name}:{fmtInt(r.start)}–{fmtInt(r.end)} · {fmtBp(r.end - r.start + 1)}
        </span>
        <span className="ml-auto flex items-center gap-2">
          {(tracks.isFetching || seq.isFetching) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label={t("common.loading")} />}
          <Button size="sm" variant="ghost" onClick={saveSvg}>
            <Download className="h-3.5 w-3.5" /> {t("explorer.saveSvg")}
          </Button>
        </span>
      </div>
      <Overview length={length} view={v} onView={p.onView} theme={theme} label={t("explorer.overview")} />
      <div
        ref={wrap}
        tabIndex={0}
        role="group"
        aria-label={t("explorer.browserLabel", { contig: p.contig.name })}
        aria-describedby="explorer-keys"
        onKeyDown={onKeyDown}
        className="rounded-lg border bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <svg
          ref={svg}
          width={width}
          height={height}
          className="block touch-none select-none"
          style={{ cursor: drag.current?.kind === "pan" ? "grabbing" : "default" }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => setHoverX(null)}
          fontFamily="Inter Variable, system-ui, sans-serif"
          role="img"
          aria-label={t("explorer.svgLabel", { contig: p.contig.name, start: fmtInt(r.start), end: fmtInt(r.end) })}
        >
          <rect x={0} y={0} width={width} height={height} fill={theme.surface} />
          <defs>
            <clipPath id="explorer-plot">
              <rect x={GUTTER} y={0} width={plotW} height={height} />
            </clipPath>
            <pattern id="explorer-gap" width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width={6} height={6} fill={theme.surface} />
              <line x1={0} y1={0} x2={0} y2={6} stroke={theme.muted} strokeWidth={3} />
            </pattern>
          </defs>
          {/* Ruler: drag here (or Shift+drag anywhere) to select a region */}
          <rect x={GUTTER} y={0} width={plotW} height={RULER_H} fill={theme.grid} opacity={0.5} style={{ cursor: "crosshair" }} />
          <g clipPath="url(#explorer-plot)">
            {positions.map((pos) => (
              <g key={pos}>
                <line x1={x(pos - 0.5)} x2={x(pos - 0.5)} y1={RULER_H - 8} y2={RULER_H} stroke={theme.axis} />
                <text x={x(pos - 0.5)} y={RULER_H - 11} fontSize={10} textAnchor="middle" fill={theme.muted}>
                  {formatPosition(pos, tickStep)}
                </text>
              </g>
            ))}
          </g>
          <TrackLabel y={yPlus + (nPlus * LANE_H) / 2} text={t("explorer.track.forward")} theme={theme} />
          <TrackLabel y={yMid + (nMid * LANE_H) / 2} text={t("explorer.track.axis")} theme={theme} />
          <TrackLabel y={yMinus + (nMinus * LANE_H) / 2} text={t("explorer.track.reverse")} theme={theme} />
          {amrRun.data?.run && (
            <AmrTrack
              y={yAmr}
              hits={amrHits}
              x={x}
              theme={theme}
              label={t("explorer.track.amr")}
              onSelect={(h) => {
                const linked = features.find((f) => f.id === h.feature?.feature_id);
                if (linked) p.onSelect(linked);
              }}
              tooltip={(h) => amrTooltip(t, h)}
            />
          )}
          {vfdbH > 0 && <ElementTrack track="vfdb" y={yVfdb} items={vfdbItems} x={x} colour={amrColour(theme, "virulence")} theme={theme} label={t("explorer.track.vfdb")} onSelect={(id) => { const f = features.find((x) => x.id === id); if (f) p.onSelect(f); }} />}
          {mobileH > 0 && <ElementTrack track="mobile" y={yMobile} items={mobileItems} x={x} colour={theme.series[1]} theme={theme} label={t("explorer.track.mobile")} onSelect={(id) => { const f = features.find((x) => x.id === id); if (f) p.onSelect(f); }} />}
          <g clipPath="url(#explorer-plot)">
            <line x1={GUTTER} x2={GUTTER + plotW} y1={yMid + (nMid * LANE_H) / 2} y2={yMid + (nMid * LANE_H) / 2} stroke={theme.axis} />
            {gapPixels.map(([a, b], i) => (
              <rect key={i} x={GUTTER + a} y={yMid + (nMid * LANE_H) / 2 - 2} width={Math.max(1, b - a)} height={4} fill={theme.muted} opacity={0.55}>
                <title>{t("explorer.intergenic")}</title>
              </rect>
            ))}
            {detailed
              ? visible.map((piece, i) => (
                  <Glyph
                    key={`${piece.feature.id}-${i}`}
                    piece={piece}
                    x0={x(piece.start - 1)}
                    x1={x(piece.end)}
                    y={laneY(piece)}
                    theme={theme}
                    selected={piece.feature.id === p.selected}
                    marked={p.marked.has(piece.feature.id)}
                    plotLo={GUTTER}
                    plotHi={GUTTER + plotW}
                    onHover={setHovered}
                    typeName={t(`annotation.type.${piece.feature.type}` as "annotation.type.cds")}
                  />
                ))
              : (Object.entries(runs ?? {}) as [StrandGroup, ReturnType<typeof densityRuns>["+"]][]).flatMap(([g, groupRuns]) =>
                  groupRuns.map((run, i) => (
                    <rect
                      key={`${g}-${i}`}
                      x={GUTTER + run.x0}
                      width={Math.max(1, run.x1 - run.x0)}
                      y={(g === "+" ? yPlus + (nPlus - 1) * LANE_H : g === "-" ? yMinus : yMid) + (LANE_H - GLYPH_H) / 2}
                      height={GLYPH_H}
                      fill={groupColour(theme, run.group)}
                    />
                  )),
                )}
          </g>
          <LineTrack
            y={yGc}
            label={t("explorer.track.gc")}
            theme={theme}
            x={x}
            plotW={plotW}
            data={trackData?.gc}
            kind="gc"
            view={v}
            skewColours={dark ? SKEW.dark : SKEW.light}
          />
          <LineTrack
            y={ySkew}
            label={t("explorer.track.skew")}
            theme={theme}
            x={x}
            plotW={plotW}
            data={trackData?.gc}
            kind="skew"
            view={v}
            skewColours={dark ? SKEW.dark : SKEW.light}
          />
          {trackData?.coverage.available ? (
            <CoverageLine y={yCov} label={t("explorer.track.coverage")} theme={theme} x={x} plotW={plotW} data={trackData.coverage} />
          ) : (
            <>
              <TrackLabel y={yCov + MSG_H / 2} text={t("explorer.track.coverage")} theme={theme} />
              <text x={GUTTER + 6} y={yCov + MSG_H / 2 + 3.5} fontSize={10.5} fill={theme.muted}>
                {trackData ? t(`explorer.coverage.${trackData.coverage.reason ?? "no_alignment"}` as "explorer.coverage.no_alignment") : t("common.loading")}
              </text>
            </>
          )}
          <TrackLabel y={ySeq + (showBases ? SEQ_H : MSG_H) / 2} text={t("explorer.track.sequence")} theme={theme} />
          {showBases && seqData ? (
            <g clipPath="url(#explorer-plot)" fontFamily="ui-monospace, SFMono-Regular, monospace" fontSize={10.5} textAnchor="middle">
              {Array.from({ length: r.end - r.start + 1 }, (_, i) => r.start + i).map((pos) => {
                const base = seqData.sequence[pos - seqData.start] ?? "";
                return (
                  <g key={pos}>
                    <text x={x(pos - 0.5)} y={ySeq + 11} fill={theme.text}>
                      {base}
                    </text>
                    <text x={x(pos - 0.5)} y={ySeq + 25} fill={theme.muted}>
                      {COMPLEMENT[base] ?? base}
                    </text>
                  </g>
                );
              })}
            </g>
          ) : (
            <text x={GUTTER + 6} y={ySeq + MSG_H / 2 + 3.5} fontSize={10.5} fill={theme.muted}>
              {showBases ? t("common.loading") : t("explorer.zoomForBases")}
            </text>
          )}
          {p.region && (
            <rect
              x={Math.max(GUTTER, x(p.region.from))}
              width={Math.max(1, Math.min(GUTTER + plotW, x(p.region.to)) - Math.max(GUTTER, x(p.region.from)))}
              y={0}
              height={height}
              fill={theme.primary}
              opacity={0.12}
              pointerEvents="none"
            />
          )}
          {hoverX != null && <line x1={GUTTER + hoverX} x2={GUTTER + hoverX} y1={RULER_H} y2={height} stroke={theme.text} strokeOpacity={0.35} pointerEvents="none" />}
        </svg>
      </div>
      <Readout t={t} hovered={hovered} hoverPos={hoverPos} gc={trackData?.gc} coverage={trackData?.coverage} contig={p.contig.name} />
      {!detailed && <p className="text-xs text-muted-foreground">{t("explorer.density", { n: fmtInt(visible.length), max: fmtInt(MAX_GLYPHS) })}</p>}
      <ErrorNote error={p.layoutError ?? tracks.error ?? seq.error} />
      <p id="explorer-keys" className="text-[11px] text-muted-foreground">
        {t("explorer.keys")}
      </p>
    </div>
  );
}

const COMPLEMENT: Record<string, string> = { A: "T", C: "G", G: "C", T: "A", N: "N", a: "t", c: "g", g: "c", t: "a", n: "n" };

/** AMRFinderPlus's elements of the most recent run on this assembly: AMR (and stress) in one colour, virulence in
 * another; partial, contig-end and internal-stop hits drawn hollow, so an incomplete gene is never shown as whole. */
function AmrTrack({ y, hits, x, theme, label, onSelect, tooltip }: {
  y: number;
  hits: AmrMapHit[];
  x: (pos: number) => number;
  theme: ChartTheme;
  label: string;
  onSelect: (h: AmrMapHit) => void;
  tooltip: (h: AmrMapHit) => string;
}) {
  return (
    <g data-track="amr">
      <TrackLabel y={y + LANE_H / 2 + 2} text={label} theme={theme} />
      <g clipPath="url(#explorer-plot)">
        {hits.map((h) => {
          const colour = amrColour(theme, ringOf(h));
          const whole = KIND_TONE[h.method_kind] === "success" || h.method_kind === "point";
          const x0 = x((h.start as number) - 1);
          return (
            <rect
              key={h.id}
              data-amr={h.element_symbol}
              x={x0}
              y={y + 2}
              width={Math.max(2, x(h.end) - x0)}
              height={GLYPH_H + 2}
              rx={2}
              fill={whole ? colour : theme.surface}
              stroke={colour}
              strokeWidth={1.5}
              style={{ cursor: h.feature ? "pointer" : "default" }}
              onClick={() => onSelect(h)}
            >
              <title>{tooltip(h)}</title>
            </rect>
          );
        })}
      </g>
    </g>
  );
}

interface TrackItem {
  id: string;
  start: number;
  end: number;
  /** Drawn filled when whole, hollow when partial. */
  whole: boolean;
  featureId: number | null;
  title: string;
}

/** One lane of calls from another tool (VFDB hits, mobile elements): whole ones filled, partial ones hollow; a click
 * opens the annotated CDS the call overlaps most. */
function ElementTrack({ track, y, items, x, colour, theme, label, onSelect }: {
  track: string;
  y: number;
  items: TrackItem[];
  x: (pos: number) => number;
  colour: string;
  theme: ChartTheme;
  label: string;
  onSelect: (featureId: number) => void;
}) {
  return (
    <g data-track={track}>
      <TrackLabel y={y + LANE_H / 2 + 2} text={label} theme={theme} />
      <g clipPath="url(#explorer-plot)">
        {items.map((h) => {
          const x0 = x(h.start - 1);
          return (
            <rect
              key={h.id}
              x={x0}
              y={y + 2}
              width={Math.max(2, x(h.end) - x0)}
              height={GLYPH_H + 2}
              rx={2}
              fill={h.whole ? colour : theme.surface}
              stroke={colour}
              strokeWidth={1.5}
              style={{ cursor: h.featureId != null ? "pointer" : "default" }}
              onClick={() => h.featureId != null && onSelect(h.featureId)}
            >
              <title>{h.title}</title>
            </rect>
          );
        })}
      </g>
    </g>
  );
}

function amrTooltip(t: ReturnType<typeof useT>, h: AmrMapHit): string {
  const values = [h.identity != null ? `${t("amr.col.identity")} ${fmtNum(h.identity, 2)}` : null, h.coverage != null ? `${t("amr.col.coverage")} ${fmtNum(h.coverage, 2)}` : null]
    .filter(Boolean)
    .join(" · ");
  return [`${h.element_symbol} · ${h.type}${h.amr_class ? ` · ${h.amr_class}` : ""}`, h.element_name ?? "", `${kindText(t, h.method_kind)} (${h.method})${values ? ` · ${values}` : ""}`, `${fmtInt(h.start ?? 0)}–${fmtInt(h.end)} (${h.strand ?? "?"})`, t("amr.notPhenotype")]
    .filter(Boolean)
    .join("\n");
}

function TrackLabel({ y, text, theme }: { y: number; text: string; theme: ChartTheme }) {
  return (
    <text x={8} y={y + 3.5} fontSize={10.5} fill={theme.muted}>
      {text}
    </text>
  );
}

/** Memoised so that moving the pointer (crosshair, readout) does not redraw every glyph. */
const Glyph = memo(function Glyph({ piece, x0, x1, y, theme, selected, marked, plotLo, plotHi, onHover, typeName }: {
  piece: Piece;
  x0: number;
  x1: number;
  y: number;
  theme: ChartTheme;
  selected: boolean;
  marked: boolean;
  plotLo: number;
  plotHi: number;
  onHover: (f: FeatureLayoutItem | null) => void;
  typeName: string;
}) {
  const plotRange = [plotLo, plotHi];
  const f = piece.feature;
  const colour = groupColour(theme, featureGroup(f.type));
  const top = y + (LANE_H - GLYPH_H) / 2;
  const lo = Math.max(plotRange[0] - 20, x0);
  const hi = Math.min(plotRange[1] + 20, x1);
  const w = hi - lo;
  const forward = f.strand === "+";
  const stranded = f.strand === "+" || f.strand === "-";
  const headAt = forward ? x1 : x0;
  const head = stranded && piece.head && headAt >= plotRange[0] - 1 && headAt <= plotRange[1] + 1 ? Math.min(6, w / 2) : 0;
  const mid = top + GLYPH_H / 2;
  const d = head <= 0 || w < 3
    ? `M${lo},${top}H${hi}V${top + GLYPH_H}H${lo}Z`
    : forward
      ? `M${lo},${top}H${hi - head}L${hi},${mid}L${hi - head},${top + GLYPH_H}H${lo}Z`
      : `M${hi},${top}H${lo + head}L${lo},${mid}L${lo + head},${top + GLYPH_H}H${hi}Z`;
  const hollow = f.hypothetical === true;
  const label = featureLabel(f);
  const visW = Math.min(hi, plotRange[1]) - Math.max(lo, plotRange[0]);
  const fits = visW >= label.length * 6 + 8;
  const strandText = f.strand === "+" ? "+" : f.strand === "-" ? "−" : "·";
  return (
    <g data-feature={f.id} onPointerEnter={() => onHover(f)} onPointerLeave={() => onHover(null)} style={{ cursor: "pointer" }}>
      <title>{`${label} · ${typeName}${f.product ? ` · ${f.product}` : ""} · ${fmtInt(f.start)}–${fmtInt(f.end)} (${strandText})`}</title>
      <rect x={lo} y={y} width={Math.max(4, w)} height={LANE_H} fill="transparent" />
      <path
        d={d}
        fill={hollow ? theme.surface : f.type === "gap" ? "url(#explorer-gap)" : colour}
        stroke={selected ? theme.text : hollow || f.pseudo ? colour : "none"}
        strokeWidth={selected ? 2 : 1.5}
        strokeDasharray={f.pseudo && !selected ? "3 2" : undefined}
        fillOpacity={f.pseudo && !hollow ? 0.45 : 1}
      />
      {marked && <rect x={lo} y={top - 3} width={Math.max(2, w)} height={2} fill={theme.text} />}
      {fits && (
        <text x={(Math.max(lo, plotRange[0]) + Math.min(hi, plotRange[1])) / 2} y={mid + 3.5} fontSize={9.5} textAnchor="middle" fill={hollow || f.type === "gap" ? theme.text : "#FFFFFF"} pointerEvents="none">
          {label}
        </text>
      )}
    </g>
  );
});

function paths(points: { x: number; y: number | null }[]): string {
  let d = "";
  let open = false;
  for (const pt of points) {
    if (pt.y == null) {
      open = false;
      continue;
    }
    d += `${open ? "L" : "M"}${pt.x.toFixed(1)},${pt.y.toFixed(1)}`;
    open = true;
  }
  return d;
}

function band(xs: number[], lo: (number | null)[], hi: (number | null)[], scale: (v: number) => number): string {
  let d = "";
  let i = 0;
  while (i < xs.length) {
    while (i < xs.length && (lo[i] == null || hi[i] == null)) i++;
    const start = i;
    while (i < xs.length && lo[i] != null && hi[i] != null) i++;
    if (i - start < 2) continue;
    const top = xs.slice(start, i).map((x, k) => `${k ? "L" : "M"}${x.toFixed(1)},${scale(hi[start + k]!).toFixed(1)}`).join("");
    const bottom = xs.slice(start, i).reverse().map((x, k) => `L${x.toFixed(1)},${scale(lo[i - 1 - k]!).toFixed(1)}`).join("");
    d += `${top}${bottom}Z`;
  }
  return d;
}

function LineTrack({ y, label, theme, x, plotW, data, kind, view, skewColours }: {
  y: number;
  label: string;
  theme: ChartTheme;
  x: (pos: number) => number;
  plotW: number;
  data: GcTrack | undefined;
  kind: "gc" | "skew";
  view: View;
  skewColours: { pos: string; neg: string };
}) {
  const t = useT();
  if (!data) return <TrackLabel y={y + LINE_H / 2} text={label} theme={theme} />;
  const centres = data.start.map((s, i) => x((s - 1 + data.end[i]) / 2));
  const value = kind === "gc" ? data.gc : data.skew;
  const lo = kind === "gc" ? data.gc_min : data.skew_min;
  const hi = kind === "gc" ? data.gc_max : data.skew_max;
  const inView = data.start.map((s, i) => data.end[i] > view.from && s - 1 < view.to);
  const vals = [...lo, ...hi].filter((v, i): v is number => v != null && inView[i % lo.length]);
  let min: number;
  let max: number;
  if (kind === "gc") {
    const ref = data.contig_gc ?? 0.5;
    min = Math.max(0, Math.min(ref, ...vals) - 0.02);
    max = Math.min(1, Math.max(ref, ...vals) + 0.02);
  } else {
    const m = Math.max(0.05, ...vals.map(Math.abs));
    min = -m;
    max = m;
  }
  const scale = (v: number) => y + LINE_H - ((v - min) / (max - min || 1)) * LINE_H;
  const pts = centres.map((cx, i) => ({ x: cx, y: value[i] == null ? null : scale(value[i]!) }));
  const fmt = (v: number) => (kind === "gc" ? fmtPct(100 * v, 1) : fmtNum(v, 2));
  const zero = scale(0);
  const id = `explorer-${kind}`;
  return (
    <g>
      <TrackLabel y={y + LINE_H / 2 - 6} text={label} theme={theme} />
      <text x={8} y={y + LINE_H / 2 + 8} fontSize={9} fill={theme.muted}>
        {data.auto ? t("explorer.windowAuto", { w: fmtInt(data.window) }) : t("explorer.window", { w: fmtInt(data.window), s: fmtInt(data.step) })}
      </text>
      <text x={GUTTER - 4} y={y + 8} fontSize={9} textAnchor="end" fill={theme.muted}>
        {fmt(max)}
      </text>
      <text x={GUTTER - 4} y={y + LINE_H} fontSize={9} textAnchor="end" fill={theme.muted}>
        {fmt(min)}
      </text>
      <rect x={GUTTER} y={y} width={plotW} height={LINE_H} fill="none" stroke={theme.grid} />
      <g clipPath="url(#explorer-plot)">
        {kind === "gc" ? (
          <>
            {data.group > 1 && <path d={band(centres, lo, hi, scale)} fill={theme.series[0]} opacity={0.12} />}
            {data.contig_gc != null && (
              <>
                <line x1={GUTTER} x2={GUTTER + plotW} y1={scale(data.contig_gc)} y2={scale(data.contig_gc)} stroke={theme.axis} />
                <text x={GUTTER + plotW - 4} y={scale(data.contig_gc) - 3} fontSize={9} textAnchor="end" fill={theme.muted}>
                  {t("explorer.contigMean", { v: fmt(data.contig_gc) })}
                </text>
              </>
            )}
            <path d={paths(pts)} fill="none" stroke={theme.series[0]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          </>
        ) : (
          <>
            <clipPath id={`${id}-pos`}>
              <rect x={GUTTER} y={y} width={plotW} height={Math.max(0, zero - y)} />
            </clipPath>
            <clipPath id={`${id}-neg`}>
              <rect x={GUTTER} y={zero} width={plotW} height={Math.max(0, y + LINE_H - zero)} />
            </clipPath>
            {[["pos", skewColours.pos], ["neg", skewColours.neg]].map(([side, colour]) => (
              <g key={side} clipPath={`url(#${id}-${side})`}>
                <path d={toZero(pts, zero)} fill={colour} opacity={0.3} />
                <path d={paths(pts)} fill="none" stroke={colour} strokeWidth={1.5} strokeLinejoin="round" />
              </g>
            ))}
            <line x1={GUTTER} x2={GUTTER + plotW} y1={zero} y2={zero} stroke={theme.axis} />
          </>
        )}
      </g>
    </g>
  );
}

/** Closed areas between each run of points and the zero line. */
function toZero(points: { x: number; y: number | null }[], zero: number): string {
  let d = "";
  let run: { x: number; y: number }[] = [];
  const flush = () => {
    if (run.length > 1) d += `M${run[0].x.toFixed(1)},${zero}` + run.map((p) => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join("") + `L${run[run.length - 1].x.toFixed(1)},${zero}Z`;
    run = [];
  };
  for (const p of points) {
    if (p.y == null) flush();
    else run.push({ x: p.x, y: p.y });
  }
  flush();
  return d;
}

function CoverageLine({ y, label, theme, x, plotW, data }: { y: number; label: string; theme: ChartTheme; x: (pos: number) => number; plotW: number; data: CoverageTrack }) {
  const t = useT();
  const centres = data.start.map((s, i) => x((s - 1 + data.end[i]) / 2));
  const max = Math.max(1, ...data.max.filter((v): v is number => v != null));
  const scale = (v: number) => y + LINE_H - (v / max) * LINE_H;
  const pts = centres.map((cx, i) => ({ x: cx, y: data.mean[i] == null ? null : scale(data.mean[i]!) }));
  return (
    <g>
      <TrackLabel y={y + LINE_H / 2 - 6} text={label} theme={theme} />
      <text x={8} y={y + LINE_H / 2 + 8} fontSize={9} fill={theme.muted}>
        {t("explorer.coverageBins", { r: data.resolution ?? "?" })}
      </text>
      <text x={GUTTER - 4} y={y + 8} fontSize={9} textAnchor="end" fill={theme.muted}>
        {fmtNum(max, 0)}×
      </text>
      <text x={GUTTER - 4} y={y + LINE_H} fontSize={9} textAnchor="end" fill={theme.muted}>
        0×
      </text>
      <rect x={GUTTER} y={y} width={plotW} height={LINE_H} fill="none" stroke={theme.grid} />
      <g clipPath="url(#explorer-plot)">
        {(data.group ?? 1) > 1 && <path d={band(centres, data.min, data.max, scale)} fill={theme.series[0]} opacity={0.12} />}
        <path d={toZero(pts, y + LINE_H)} fill={theme.series[0]} opacity={0.1} />
        <path d={paths(pts)} fill="none" stroke={theme.series[0]} strokeWidth={2} strokeLinejoin="round" />
      </g>
    </g>
  );
}

function Overview({ length, view, onView, theme, label }: { length: number; view: View; onView: (v: View) => void; theme: ChartTheme; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const centreAt = (clientX: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;
    const pos = ((clientX - rect.left) / rect.width) * length;
    onView(panView(view, pos - (view.from + view.to) / 2, length));
  };
  return (
    <div ref={ref} className="relative h-3 cursor-pointer rounded-full" style={{ background: theme.grid }} onClick={(e) => centreAt(e.clientX)} title={label} aria-hidden>
      <div
        className="absolute top-0 h-3 rounded-full"
        style={{ left: `${(view.from / length) * 100}%`, width: `${Math.max(0.5, (span(view) / length) * 100)}%`, background: theme.primary, opacity: 0.6 }}
      />
    </div>
  );
}

function nearest(starts: number[], ends: number[], pos: number): number {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (ends[m] < pos) lo = m + 1;
    else hi = m;
  }
  return lo;
}

function Readout({ t, hovered, hoverPos, gc, coverage, contig }: {
  t: ReturnType<typeof useT>;
  hovered: FeatureLayoutItem | null;
  hoverPos: number | null;
  gc: GcTrack | undefined;
  coverage: CoverageTrack | undefined;
  contig: string;
}) {
  const parts: string[] = [];
  if (hoverPos != null) {
    parts.push(`${contig}:${fmtInt(hoverPos)}`);
    if (gc?.start.length) {
      const i = nearest(gc.start, gc.end, hoverPos);
      if (gc.gc[i] != null) parts.push(`${t("explorer.track.gc")} ${fmtPct(100 * gc.gc[i]!, 1)}`);
      if (gc.skew[i] != null) parts.push(`${t("explorer.track.skew")} ${fmtNum(gc.skew[i]!, 3)}`);
      parts.push(t("explorer.readoutWindow", { s: fmtInt(gc.start[i]), e: fmtInt(gc.end[i]) }));
    }
    if (coverage?.available && coverage.start.length) {
      const i = nearest(coverage.start, coverage.end, hoverPos);
      if (coverage.mean[i] != null) parts.push(`${t("explorer.track.coverage")} ${fmtNum(coverage.mean[i]!, 1)}×`);
    }
  }
  return (
    <div className="min-h-[2.5rem] rounded-lg bg-muted/40 px-3 py-1.5 text-xs" aria-live="off">
      {hovered ? (
        <div className="truncate">
          <span className="font-medium">{featureLabel(hovered)}</span>
          <span className="text-muted-foreground">
            {" "}
            · {t(`annotation.type.${hovered.type}` as "annotation.type.cds")} · {fmtInt(hovered.start)}–{fmtInt(hovered.end)} ({hovered.strand}) · {fmtBp(hovered.length)}
          </span>
          {hovered.product && <span> · {hovered.product}</span>}
        </div>
      ) : (
        <div className="truncate text-muted-foreground">{parts.length ? parts.join(" · ") : t("explorer.hoverHint")}</div>
      )}
    </div>
  );
}
