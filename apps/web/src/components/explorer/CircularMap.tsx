import { type QueryObserverResult, useQueries, useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import { memo, type MouseEvent as ReactMouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { Segmented } from "@/components/charts/ChartCard";
import { type ChartTheme, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import {
  type ArcClass,
  arcClass,
  type ArcPiece,
  barPaths,
  type CircleModel,
  circleModel,
  type CustomCriterion,
  hasRoomForLabel,
  labelAnchor,
  locate,
  matchFeatures,
  mergeArcs,
  pieceAt,
  pointerPolar,
  polar,
  ringRadii,
  sectorPath,
  segmentTicks,
  stepFeature,
  windowAt,
} from "@/lib/circular";
import { amrFeatures, kindText } from "@/lib/amr";
import { categoryKey, isWholeElement, mobileFeatures, vfdbFeatures } from "@/lib/mobile";
import { type ContigOption, featureLabel, formatPosition } from "@/lib/explorer";
import { fmtBases, fmtBp, fmtInt, fmtNum, fmtPct } from "@/lib/format";
import type { AmrAnnotationHits, Annotation, GenomeMap, MapFeature, MobileAnnotationElements, VirulenceAnnotationHits } from "@/lib/types";
import { cn } from "@/lib/utils";
import { amrColour, groupColour, SKEW } from "./GenomeBrowser";

export type RingId = "backbone" | "forward" | "reverse" | "custom" | "amr" | "virulence" | "vfdb" | "mobile" | "coverage" | "gc" | "skew";

/** Rings from the outside in. AMR and virulence come from the assembly's most recent AMRFinderPlus run, the VFDB ring
 * from its most recent VFDB screen (a ring of its own: the two sources are never merged), the mobile-elements ring
 * from the most recent run of each plasmid and mobile-element method. */
const RINGS: RingId[] = ["backbone", "forward", "reverse", "custom", "amr", "virulence", "vfdb", "mobile", "coverage", "gc", "skew"];
const THICKNESS: Partial<Record<RingId, number>> = { backbone: 8, forward: 24, reverse: 24, custom: 10, amr: 12, virulence: 12, vfdb: 12, mobile: 12, coverage: 26, gc: 30, skew: 30 };
/** The mobile-elements ring and the backbone of the contigs MOB-suite calls plasmids. */
const mobileColour = (theme: ChartTheme) => theme.series[1];
const plasmidContigColour = (theme: ChartTheme) => theme.series[2];
const MAX_CIRCLES = 6;
const OFFERED = 24;
const MARGIN = 58;
const LEGEND_LINE = 17;
type GeneRing = "forward" | "reverse" | "backbone";
const CLASSES: ArcClass[] = ["coding", "hypothetical", "rna", "element", "gap"];

const classColour = (theme: ChartTheme, c: ArcClass) => groupColour(theme, c === "hypothetical" ? "coding" : c);
const classOpacity = (c: ArcClass) => (c === "hypothetical" ? 0.4 : 1);

interface Placed {
  model: CircleModel;
  cx: number;
  cy: number;
  R: number;
  radii: Record<string, { r0: number; r1: number }>;
  /** Value-ring scales shared by every circle, so circles side by side compare. */
  scales: CircleModel["scales"];
}

/** Map responses held as one value that stays the same object while no query changes (TanStack's combine). */
function combineMaps(results: QueryObserverResult<GenomeMap>[]) {
  return {
    data: results.map((r) => r.data).filter((m): m is GenomeMap => !!m),
    loading: results.some((r) => r.isLoading),
    error: results.find((r) => r.error)?.error ?? null,
  };
}

interface Hit {
  circle: number;
  ring: RingId | null;
  seq: number | null;
  position: number | null;
  piece: ArcPiece | null;
  x: number;
  y: number;
}

export function CircularExplorer({ annotation, contigs, sampleCode, selected, onSelect, onShowLinear }: {
  annotation: Annotation;
  contigs: ContigOption[];
  sampleCode: string | undefined;
  selected: number | null;
  onSelect: (f: MapFeature | null) => void;
  onShowLinear: (f: MapFeature) => void;
}) {
  const t = useT();
  const theme = useChartTheme();
  const several = contigs.length > 1;
  const [mode, setMode] = useState<"concatenated" | "each">("concatenated");
  const byLength = useMemo(() => [...contigs].sort((a, b) => b.length - a.length), [contigs]);
  const [chosen, setChosen] = useState<string[]>(() => byLength.slice(0, 4).map((c) => c.id));
  const [enabled, setEnabled] = useState<Record<RingId, boolean>>({
    backbone: true, forward: true, reverse: true, custom: true, amr: false, virulence: false, vfdb: false, mobile: false, coverage: true, gc: true, skew: true,
  });
  const [customKind, setCustomKind] = useState("");
  const [customText, setCustomText] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(customText), 250);
    return () => clearTimeout(timer);
  }, [customText]);

  const requests = mode === "each" && several ? contigs.filter((c) => chosen.includes(c.id)).map((c) => [c.id]) : [[]];
  const maps = useQueries({
    queries: requests.map((ids) => ({
      queryKey: ["annotationMap", annotation.id, ids.join("\u0000"), ids.length ? 720 : 1440],
      queryFn: () => api.annotationMap(annotation.id, { contigs: ids, points: ids.length ? 720 : 1440 }),
      staleTime: Infinity,
    })),
    combine: combineMaps,
  });
  const loaded = maps.data;
  const allFeatures = useMemo(() => loaded.flatMap((m) => m.features), [loaded]);
  const criterion = useMemo<CustomCriterion | null>(
    () => (customKind === "text" ? (query.trim() ? { kind: "text", q: query } : null) : customKind === "pseudo" ? { kind: "pseudo" } : customKind ? { kind: "type", type: customKind } : null),
    [customKind, query],
  );
  const customLabel =
    customKind === "text" ? `“${query.trim()}”` : customKind === "pseudo" ? t("circular.custom.pseudo") : customKind ? t(`annotation.type.${customKind}` as TranslationKey) : "";
  const amrQuery = useQuery({ queryKey: ["annotationAmr", annotation.id], queryFn: () => api.annotationAmr(annotation.id), staleTime: 60_000 });
  const amr = amrQuery.data;
  const vfdbQuery = useQuery({ queryKey: ["annotationVirulence", annotation.id], queryFn: () => api.annotationVirulence(annotation.id), staleTime: 60_000 });
  const mobileQuery = useQuery({ queryKey: ["annotationMobile", annotation.id], queryFn: () => api.annotationMobile(annotation.id), staleTime: 60_000 });
  const vfdb = vfdbQuery.data;
  const mobile = mobileQuery.data;
  const amrRings = useMemo(
    () => ({
      amr: amrFeatures(amr?.hits ?? [], "amr"),
      virulence: amrFeatures(amr?.hits ?? [], "virulence"),
      vfdb: vfdbFeatures(vfdb?.hits ?? []),
      mobile: mobileFeatures(mobile?.elements ?? []),
    }),
    [amr, vfdb, mobile],
  );
  const plasmidContigs = useMemo(() => new Set((mobile?.contigs ?? []).filter((c) => c.molecule_type === "plasmid").map((c) => c.contig)), [mobile]);
  const mobileRun = Object.values(mobile?.runs ?? {}).some(Boolean);
  const amrState = { run: Boolean(amr?.run), plus: Boolean(amr?.run?.plus), vfdb: Boolean(vfdb?.run), mobile: mobileRun };
  const coverageAvailable = loaded.some((m) => m.coverage.available);
  const coverageReason = loaded.find((m) => !m.coverage.available)?.coverage.reason ?? "no_alignment";
  const types = useMemo(() => [...new Set(allFeatures.map((f) => f.type))], [allFeatures]);
  const hasPseudo = allFeatures.some((f) => f.pseudo);
  const synthetic = (annotation.summary.synthetic_evidence ?? []).length > 0;
  const rings = useMemo(
    () =>
      RINGS.filter(
        (r) =>
          enabled[r] &&
          (r !== "coverage" || coverageAvailable) &&
          (r !== "custom" || criterion != null) &&
          (r !== "amr" || amrState.run) &&
          (r !== "virulence" || amrState.plus) &&
          (r !== "vfdb" || amrState.vfdb) &&
          (r !== "mobile" || amrState.mobile),
      ),
    [enabled, coverageAvailable, criterion, amrState.run, amrState.plus, amrState.vfdb, amrState.mobile],
  );
  useEffect(() => {
    if (amrState.run) setEnabled((e) => ({ ...e, amr: true, virulence: amrState.plus }));
  }, [amrState.run, amrState.plus]);
  useEffect(() => {
    if (amrState.vfdb || amrState.mobile) setEnabled((e) => ({ ...e, vfdb: e.vfdb || amrState.vfdb, mobile: e.mobile || amrState.mobile }));
  }, [amrState.vfdb, amrState.mobile]);
  const order = contigs.map((c) => c.id);
  const step = (dir: 1 | -1) => {
    const f = stepFeature(allFeatures, order, selected, dir);
    if (f) onSelect(f);
  };
  const error = maps.error;
  const selectedFeature = allFeatures.find((f) => f.id === selected) ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-4">
        {several && (
          <div className="space-y-1 text-xs">
            <span className="block text-muted-foreground">{t("circular.mode.label")}</span>
            <Segmented
              label={t("circular.mode.label")}
              value={mode}
              onChange={setMode}
              options={[
                { value: "concatenated", label: t("circular.mode.concatenated") },
                { value: "each", label: t("circular.mode.each") },
              ]}
            />
          </div>
        )}
        <label className="space-y-1 text-xs">
          <span className="block text-muted-foreground">{t("circular.custom.label")}</span>
          <Select value={customKind} onChange={(e) => setCustomKind(e.target.value)} className="w-56">
            <option value="">{t("circular.custom.none")}</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {t("circular.custom.type", { type: t(`annotation.type.${type}` as TranslationKey) })}
              </option>
            ))}
            {hasPseudo && <option value="pseudo">{t("circular.custom.pseudo")}</option>}
            <option value="text">{t("circular.custom.text")}</option>
          </Select>
        </label>
        {customKind === "text" && (
          <label className="space-y-1 text-xs">
            <span className="block text-muted-foreground">{t("circular.custom.search")}</span>
            <Input className="w-64" value={customText} onChange={(e) => setCustomText(e.target.value)} placeholder={t("circular.custom.placeholder")} />
          </label>
        )}
        <span className="pb-1.5">
          <Explain id="circular_map" />
        </span>
        {criterion && <span className="pb-2.5 text-xs text-muted-foreground">{t("circular.custom.count", { n: fmtInt(matchFeatures(allFeatures, criterion).length) })}</span>}
      </div>
      {mode === "each" && several && (
        <fieldset className="space-y-1 text-xs">
          <legend className="text-muted-foreground">{t("circular.choose", { max: MAX_CIRCLES })}</legend>
          <div className="flex flex-wrap gap-1.5">
            {byLength.slice(0, OFFERED).map((c) => {
              const on = chosen.includes(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={on}
                  disabled={!on && chosen.length >= MAX_CIRCLES}
                  onClick={() => setChosen((x) => (on ? x.filter((id) => id !== c.id) : [...x, c.id]))}
                  className={cn("rounded-full border px-2.5 py-1 disabled:opacity-40", on ? "border-arva-royal bg-arva-royal/10 font-medium dark:border-arva-cyan dark:bg-arva-cyan/10" : "hover:bg-muted")}
                >
                  {c.name} · {fmtBases(c.length)}
                </button>
              );
            })}
          </div>
          {contigs.length > OFFERED && <p className="text-muted-foreground">{t("circular.chooseMore", { n: OFFERED, total: fmtInt(contigs.length) })}</p>}
          {!chosen.length && <p className="text-muted-foreground">{t("circular.chooseNone")}</p>}
        </fieldset>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div className="min-w-0 space-y-2">
          <ErrorNote error={error} />
          {maps.loading && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("common.loading")}
            </p>
          )}
          {loaded.length > 0 && (
            <CircularMap
              maps={loaded}
              amr={amrRings}
              amrRun={amr?.run ?? null}
              vfdbRun={vfdb?.run ?? null}
              mobileRuns={mobile?.runs ?? {}}
              plasmidContigs={plasmidContigs}
              mode={mode === "each" && several ? "each" : "concatenated"}
              contigs={contigs}
              rings={rings}
              criterion={criterion}
              customLabel={customLabel}
              selected={selected}
              onSelect={onSelect}
              onStep={step}
              theme={theme}
              caption={t("circular.caption", {
                sample: sampleCode ?? "",
                tool: `${annotation.tool} ${annotation.tool_version}`,
                db: annotation.database_name ? `${annotation.database_name} ${annotation.database_version ?? ""}` : t("explorer.noDatabase"),
              })}
              synthetic={synthetic}
              fileStem={`arva_circular_${(sampleCode ?? annotation.id.slice(0, 8)).replace(/[^A-Za-z0-9._-]+/g, "_")}`}
            />
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="outline" onClick={() => step(-1)}>
              {t("explorer.prevFeature")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => step(1)}>
              {t("explorer.nextFeature")}
            </Button>
            {selectedFeature && (
              <Button size="sm" variant="outline" onClick={() => onShowLinear(selectedFeature)}>
                {t("circular.showLinear")}
              </Button>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">{t("circular.note")}</p>
        </div>
        <RingList enabled={enabled} setEnabled={setEnabled} coverageAvailable={coverageAvailable} coverageReason={coverageReason} hasCustom={criterion != null} amr={amr} vfdb={vfdb} mobile={mobile} />
      </div>
    </div>
  );
}

function RingList({ enabled, setEnabled, coverageAvailable, coverageReason, hasCustom, amr, vfdb, mobile }: {
  enabled: Record<RingId, boolean>;
  setEnabled: (fn: (e: Record<RingId, boolean>) => Record<RingId, boolean>) => void;
  coverageAvailable: boolean;
  coverageReason: string;
  hasCustom: boolean;
  amr: AmrAnnotationHits | undefined;
  vfdb: VirulenceAnnotationHits | undefined;
  mobile: MobileAnnotationElements | undefined;
}) {
  const t = useT();
  const mobileMethods = Object.entries(mobile?.runs ?? {}).filter(([, v]) => v).map(([k]) => t(`mobile.method.${k}` as TranslationKey));
  const amrNote = (r: RingId): string | null => {
    if (r === "vfdb") return vfdb?.run ? t("circular.ring.vfdbRun", { n: fmtInt(vfdb.hits.length), version: vfdb.run.tool_version, db: vfdb.run.database_version ?? "?" }) : t("circular.ring.vfdbNotRun");
    if (r === "mobile") return mobileMethods.length ? t("circular.ring.mobileRun", { n: fmtInt(mobile?.elements.length ?? 0), methods: mobileMethods.join(", ") }) : t("circular.ring.mobileNotRun");
    if (r !== "amr" && r !== "virulence") return null;
    if (!amr?.run) return t("circular.ring.amrNotRun");
    if (r === "virulence" && !amr.run.plus) return t("circular.ring.plusOff");
    const n = amr.hits.filter((h) => (r === "virulence") === (h.type === "VIRULENCE")).length;
    return t("circular.ring.amrRun", { n: fmtInt(n), version: amr.run.tool_version, db: amr.run.database_version ?? "?" });
  };
  return (
    <fieldset className="space-y-1.5 self-start rounded-lg border p-3 text-xs">
      <legend className="px-1 font-medium">{t("circular.rings")}</legend>
      {RINGS.map((r) => {
        const unavailable =
          (r === "coverage" && !coverageAvailable) || (r === "amr" && !amr?.run) || (r === "virulence" && !amr?.run?.plus) || (r === "vfdb" && !vfdb?.run) || (r === "mobile" && !mobileMethods.length);
        const note =
          amrNote(r) ??
          (r === "coverage" && !coverageAvailable ? t(`explorer.coverage.${coverageReason}` as TranslationKey) : r === "custom" && !hasCustom ? t("circular.ring.customHint") : null);
        return (
          <label key={r} className={cn("flex items-start gap-2", unavailable && "text-muted-foreground")}>
            <input
              type="checkbox"
              className="mt-0.5 h-3.5 w-3.5 accent-[#00B4A6]"
              checked={!unavailable && enabled[r]}
              disabled={unavailable}
              onChange={() => setEnabled((e) => ({ ...e, [r]: !e[r] }))}
            />
            <span>
              {t(`circular.ring.${r}` as TranslationKey)}
              {note && <span className="block text-[11px] text-muted-foreground">{note}</span>}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

interface MapProps {
  maps: GenomeMap[];
  /** AMRFinderPlus's elements of the assembly's most recent run, as map features (empty without a run). */
  amr?: { amr: MapFeature[]; virulence: MapFeature[]; vfdb?: MapFeature[]; mobile?: MapFeature[] };
  amrRun?: AmrAnnotationHits["run"];
  vfdbRun?: VirulenceAnnotationHits["run"];
  mobileRuns?: MobileAnnotationElements["runs"];
  /** The sequences MOB-suite calls plasmids: their backbone is coloured. */
  plasmidContigs?: Set<string>;
  mode: "concatenated" | "each";
  contigs: ContigOption[];
  /** The rings drawn, from the outside in. */
  rings: RingId[];
  criterion: CustomCriterion | null;
  customLabel: string;
  selected: number | null;
  onSelect: (f: MapFeature | null) => void;
  onStep: (dir: 1 | -1) => void;
  theme: ChartTheme;
  caption: string;
  synthetic: boolean;
  fileStem: string;
}

/**
 * The circular map, drawn as SVG (one circle, or one per chosen sequence side by side). Each ring of genes is a few
 * paths, one per kind of feature, of sectors merged below a pixel apart, so a genome of thousands of genes stays a
 * few hundred sectors; hovering and clicking find the feature from the angle and radius, not from DOM elements. The
 * legend and caption are part of the SVG so that a saved figure says what it shows.
 */
export function CircularMap(p: MapProps) {
  const t = useT();
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(760);
  const [hit, setHit] = useState<Hit | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => entry.contentRect.width > 0 && setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const features = useMemo(() => p.maps.flatMap((m) => m.features), [p.maps]);
  const custom = useMemo(() => matchFeatures(features, p.criterion), [features, p.criterion]);
  const customIds = useMemo(() => new Set(custom.map((f) => f.id)), [custom]);
  const models = useMemo(
    () => p.maps.map((m) => circleModel(m, m.features.filter((f) => customIds.has(f.id)), p.amr)),
    [p.maps, customIds, p.amr],
  );

  const n = models.length;
  const cols = n === 1 ? 1 : width >= 980 ? Math.min(3, n) : Math.min(2, n);
  const cell = Math.min(width / cols, n === 1 ? 780 : 520);
  const rows = Math.ceil(n / cols);
  const placed = useMemo<Placed[]>(() => {
    const drawn = p.rings.filter((r) => THICKNESS[r]);
    const scales = sharedScales(models);
    return models.map((model, i) => {
      const R = Math.max(80, cell / 2 - MARGIN);
      const offset = (width - cols * cell) / 2;
      const radii = ringRadii(drawn.map((id) => ({ id, thickness: (THICKNESS[id]! * R) / 300 })), R, R * 0.36, (4 * R) / 300);
      return { model, cx: offset + (i % cols) * cell + cell / 2, cy: Math.floor(i / cols) * cell + cell / 2, R, radii, scales };
    });
  }, [models, p.rings, width, cols, cell]);
  const legend = legendItems(t, p, models, p.rings, custom.length);
  const legendTop = rows * cell + 8;
  const height = legendTop + legend.length * LEGEND_LINE + 34 + (p.synthetic ? LEGEND_LINE : 0);

  const at = (e: ReactMouseEvent<SVGSVGElement>) => {
    const rect = svg.current?.getBoundingClientRect();
    return rect ? hitTest(placed, e.clientX - rect.left, e.clientY - rect.top) : null;
  };
  const onClick = (e: ReactMouseEvent<SVGSVGElement>) => {
    const h = at(e);
    if (!h?.piece) return;
    const f = h.piece.feature;
    const link = f.amr?.feature ?? f.vfdb?.feature ?? f.mobile?.feature;
    if (!f.amr && !f.vfdb && !f.mobile) p.onSelect(f);
    else if (link) {
      const linked = features.find((x) => x.id === link.feature_id);
      if (linked) p.onSelect(linked);
    }
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "]" || e.key === "[") {
      e.preventDefault();
      p.onStep(e.key === "]" ? 1 : -1);
    } else if (e.key === "Escape") p.onSelect(null);
  };
  const serialise = () => {
    if (!svg.current) return null;
    const clone = svg.current.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.querySelectorAll("[data-overlay]").forEach((el) => el.remove());
    return new XMLSerializer().serializeToString(clone);
  };
  const saveSvg = () => {
    const text = serialise();
    if (text) download(URL.createObjectURL(new Blob([text], { type: "image/svg+xml" })), `${p.fileStem}.svg`, true);
  };
  const savePng = () => {
    const text = serialise();
    if (!text) return;
    const img = new Image();
    const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
    img.onload = () => {
      const scale = 3;
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = p.theme.surface;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      download(canvas.toDataURL("image/png"), `${p.fileStem}.png`, false);
    };
    img.src = url;
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-1">
        <span className="mr-1 text-xs text-muted-foreground">{t("circular.export")}</span>
        <Button size="sm" variant="ghost" onClick={saveSvg}>
          <Download className="h-3.5 w-3.5" /> SVG
        </Button>
        <Button size="sm" variant="ghost" onClick={savePng}>
          <Download className="h-3.5 w-3.5" /> PNG (3×)
        </Button>
      </div>
      <div
        ref={wrap}
        tabIndex={0}
        role="group"
        aria-label={t("circular.groupLabel")}
        aria-describedby="circular-keys"
        onKeyDown={onKeyDown}
        className="relative rounded-lg border bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <svg
          ref={svg}
          width={width}
          height={height}
          className="block select-none"
          style={{ cursor: hit?.piece ? "pointer" : "default" }}
          onMouseMove={(e) => setHit(at(e))}
          onMouseLeave={() => setHit(null)}
          onClick={onClick}
          fontFamily="Inter Variable, Inter, system-ui, sans-serif"
          role="img"
          aria-label={t("circular.svgLabel", { what: placed.map((c) => circleTitle(t, c.model)).join(", ") })}
        >
          <rect x={0} y={0} width={width} height={height} fill={p.theme.surface} />
          {placed.map((c, i) => (
            <CircleArt key={i} c={c} theme={p.theme} rings={p.rings} showNames={p.mode === "concatenated"} contigs={p.contigs} plasmidContigs={p.plasmidContigs} />
          ))}
          {placed.map((c, i) => (
            <Highlight key={`h${i}`} c={c} theme={p.theme} id={p.selected} strong />
          ))}
          {hit?.piece && <Highlight c={placed[hit.circle]} theme={p.theme} id={hit.piece.feature.id} />}
          <Legend items={legend} top={legendTop} theme={p.theme} caption={p.caption} synthetic={p.synthetic ? t("circular.synthetic") : null} />
        </svg>
        {hit && <Tooltip hit={hit} placed={placed} width={width} t={t} />}
      </div>
      <p id="circular-keys" className="text-[11px] text-muted-foreground">
        {t("circular.keys")}
      </p>
    </div>
  );
}

const sharedScales = (models: CircleModel[]): CircleModel["scales"] => ({
  gc: Math.max(...models.map((m) => m.scales.gc)),
  skew: Math.max(...models.map((m) => m.scales.skew)),
  coverage: Math.max(...models.map((m) => m.scales.coverage)),
});

function download(url: string, name: string, revoke: boolean) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  if (revoke) URL.revokeObjectURL(url);
}

const GENE_RINGS: GeneRing[] = ["forward", "reverse", "backbone"];

function hitTest(placed: Placed[], x: number, y: number): Hit | null {
  for (let i = 0; i < placed.length; i++) {
    const c = placed[i];
    const { angle, r } = pointerPolar(c.cx, c.cy, x, y);
    if (r > c.R + 12) continue;
    const at = locate(c.model.layout, angle);
    const ring = (Object.entries(c.radii).find(([, rr]) => r >= rr.r0 - 1.5 && r <= rr.r1 + 1.5)?.[0] ?? null) as RingId | null;
    let piece: ArcPiece | null = null;
    const tolerance = 3 / Math.max(r, 1);
    if (ring && (GENE_RINGS as string[]).includes(ring)) piece = pieceAt(c.model.rings[ring as GeneRing], angle, tolerance);
    else if (ring === "custom") piece = pieceAt(c.model.custom, angle, tolerance);
    else if (ring === "amr" || ring === "virulence" || ring === "vfdb" || ring === "mobile") piece = pieceAt(c.model[ring], angle, tolerance);
    return { circle: i, ring, seq: at?.index ?? null, position: at ? Math.floor(at.pos) + 1 : null, piece, x, y };
  }
  return null;
}

/** The rings of one circle: memoised, so moving the pointer only redraws the highlight and the tooltip. */
const CircleArt = memo(function CircleArt({ c, theme, rings, showNames, contigs, plasmidContigs }: {
  c: Placed;
  theme: ChartTheme;
  rings: RingId[];
  showNames: boolean;
  contigs: ContigOption[];
  plasmidContigs?: Set<string>;
}) {
  const t = useT();
  const { model, cx, cy, R, radii } = c;
  const layout = model.layout;
  const dark = theme.surface !== "#FFFFFF";
  const skew = dark ? SKEW.dark : SKEW.light;
  const geneRing = (ring: GeneRing) => {
    const rr = radii[ring];
    if (!rr) return null;
    const mid = (rr.r0 + rr.r1) / 2;
    return CLASSES.map((cls) => {
      const pieces = model.rings[ring].filter((piece) => arcClass(piece.feature) === cls);
      if (!pieces.length) return null;
      const d = mergeArcs(pieces, layout, 0.6 / mid, 0.9 / mid).map(([a0, a1]) => sectorPath(cx, cy, rr.r0, rr.r1, a0, a1)).join("");
      return <path key={`${ring}-${cls}`} d={d} fill={classColour(theme, cls)} fillOpacity={classOpacity(cls)} />;
    });
  };
  const values = (ring: "gc" | "skew" | "coverage") => {
    const rr = radii[ring];
    if (!rr) return null;
    const bars = model[ring];
    const half = (rr.r1 - rr.r0) / 2;
    if (ring === "coverage") {
      const { pos } = barPaths(cx, cy, bars, rr.r0, rr.r1 - rr.r0, c.scales.coverage);
      return (
        <g>
          <circle cx={cx} cy={cy} r={rr.r0} fill="none" stroke={theme.axis} />
          <path d={pos} fill={theme.series[0]} fillOpacity={0.85} />
        </g>
      );
    }
    const { pos, neg } = barPaths(cx, cy, bars, rr.r0 + half, half, c.scales[ring]);
    const colours = ring === "gc" ? { pos: theme.text, neg: theme.text } : skew;
    return (
      <g>
        <path d={pos} fill={colours.pos} fillOpacity={ring === "gc" ? 0.7 : 0.9} />
        <path d={neg} fill={colours.neg} fillOpacity={ring === "gc" ? 0.7 : 0.9} />
        <circle cx={cx} cy={cy} r={rr.r0 + half} fill="none" stroke={theme.axis} strokeWidth={0.75} />
      </g>
    );
  };
  const bb = radii.backbone;
  const s = model.map.sequences;
  const totalGc = model.map.gc.genome_gc;
  return (
    <g>
      {bb &&
        layout.segments.map((seg, i) => (
          <path key={seg.id} d={sectorPath(cx, cy, bb.r0, bb.r1, seg.a0, seg.a1)} fill={plasmidContigs?.has(seg.id) ? plasmidContigColour(theme) : i % 2 ? theme.grid : theme.axis} data-plasmid={plasmidContigs?.has(seg.id) ? "" : undefined}>
            <title>{`${seg.name} · ${fmtBp(seg.length)}${plasmidContigs?.has(seg.id) ? ` · ${t("circular.tooltip.plasmidContig")}` : ""}`}</title>
          </path>
        ))}
      {bb && geneRing("backbone")}
      {layout.segments.map((seg) => {
        const { step, positions } = segmentTicks(layout, seg, R);
        const [x0, y0] = polar(cx, cy, R - 10, seg.a0);
        const [x1, y1] = polar(cx, cy, R + 8, seg.a0);
        return (
          <g key={`t-${seg.id}`}>
            <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={theme.text} strokeWidth={1.25} />
            {positions.map((pos) => {
              const a = seg.a0 + pos * layout.radPerBase;
              const [ax, ay] = polar(cx, cy, R + 1, a);
              const [bx, by] = polar(cx, cy, R + 5, a);
              const [lx, ly] = polar(cx, cy, R + 15, a);
              return (
                <g key={pos}>
                  <line x1={ax} y1={ay} x2={bx} y2={by} stroke={theme.muted} />
                  <text x={lx} y={ly + 3.5} fontSize={9.5} textAnchor={labelAnchor(a)} fill={theme.muted}>
                    {formatPosition(pos, step)}
                  </text>
                </g>
              );
            })}
            {showNames && layout.segments.length > 1 && hasRoomForLabel(seg, R, 48) && <SegmentName seg={seg} cx={cx} cy={cy} r={R + 34} theme={theme} />}
          </g>
        );
      })}
      {rings.includes("forward") && geneRing("forward")}
      {rings.includes("reverse") && geneRing("reverse")}
      {radii.custom && (
        <g>
          <circle cx={cx} cy={cy} r={(radii.custom.r0 + radii.custom.r1) / 2} fill="none" stroke={theme.grid} />
          <path
            d={mergeArcs(model.custom, layout, 0.6 / radii.custom.r0, 2 / radii.custom.r0).map(([a0, a1]) => sectorPath(cx, cy, radii.custom.r0, radii.custom.r1, a0, a1)).join("")}
            fill={theme.series[3]}
          />
        </g>
      )}
      {(["amr", "virulence", "vfdb", "mobile"] as const).map((ring) => {
        const rr = radii[ring];
        if (!rr) return null;
        const colour = ring === "mobile" ? mobileColour(theme) : amrColour(theme, ring === "vfdb" ? "virulence" : ring);
        const whole = model[ring].filter((piece) => isWhole(piece));
        const part = model[ring].filter((piece) => !isWhole(piece));
        const path = (pieces: ArcPiece[]) =>
          mergeArcs(pieces, layout, 0.6 / rr.r0, 2 / rr.r0)
            .map(([a0, a1]) => sectorPath(cx, cy, rr.r0, rr.r1, a0, a1))
            .join("");
        return (
          <g key={ring} data-ring={ring}>
            <circle cx={cx} cy={cy} r={(rr.r0 + rr.r1) / 2} fill="none" stroke={theme.grid} />
            {whole.length > 0 && <path d={path(whole)} fill={colour} />}
            {part.length > 0 && <path d={path(part)} fill={theme.surface} stroke={colour} strokeWidth={1.2} />}
          </g>
        );
      })}
      {values("coverage")}
      {values("gc")}
      {values("skew")}
      <text x={cx} y={cy - 12} fontSize={Math.max(11, R / 18)} fontWeight={600} textAnchor="middle" fill={theme.text}>
        {truncate(circleTitle(t, model), 28)}
      </text>
      <text x={cx} y={cy + 6} fontSize={11} textAnchor="middle" fill={theme.muted}>
        {fmtBases(model.map.total_length)}
        {totalGc != null ? ` · ${t("circular.centre.gc", { v: fmtPct(100 * totalGc, 1) })}` : ""}
      </text>
      <text x={cx} y={cy + 21} fontSize={11} textAnchor="middle" fill={theme.muted}>
        {t("circular.centre.features", { n: fmtInt(model.map.total) })}
      </text>
      {s.length === 1 && (
        <text x={cx} y={cy + 36} fontSize={10} textAnchor="middle" fill={theme.muted}>
          {topologyText(t, contigs.find((o) => o.id === s[0].contig))}
        </text>
      )}
    </g>
  );
});

function SegmentName({ seg, cx, cy, r, theme }: { seg: { name: string; a0: number; a1: number }; cx: number; cy: number; r: number; theme: ChartTheme }) {
  const mid = (seg.a0 + seg.a1) / 2;
  const [x, y] = polar(cx, cy, r, mid);
  return (
    <text x={x} y={y + 4} fontSize={10.5} fontWeight={600} textAnchor={labelAnchor(mid)} fill={theme.text}>
      {truncate(seg.name, 24)}
    </text>
  );
}

function topologyText(t: ReturnType<typeof useT>, c: ContigOption | undefined): string {
  if (c?.circular == null) return t("explorer.topologyUnknown");
  return t(c.circular ? "explorer.circularBy" : "explorer.linearBy", { source: c.circularSource ?? "?" });
}

const circleTitle = (t: ReturnType<typeof useT>, m: CircleModel) =>
  m.map.sequences.length === 1 ? m.map.sequences[0].contig_in_assembly : t("circular.centre.sequences", { n: fmtInt(m.map.sequences.length) });

const truncate = (s: string, max: number) => (s.length > max ? `${s.slice(0, max - 1)}…` : s);

function Highlight({ c, theme, id, strong }: { c: Placed; theme: ChartTheme; id: number | null; strong?: boolean }) {
  if (id == null) return null;
  const pieces = GENE_RINGS.flatMap((ring) => c.model.rings[ring].filter((p) => p.feature.id === id).map((p) => ({ p, ring })));
  if (!pieces.length) return null;
  return (
    <g data-overlay={strong ? undefined : "hover"} pointerEvents="none">
      {pieces.map(({ p, ring }, i) => {
        const rr = c.radii[ring];
        if (!rr) return null;
        const minW = 3 / rr.r1;
        const mid = (p.a0 + p.a1) / 2;
        const [a0, a1] = p.a1 - p.a0 < minW ? [mid - minW / 2, mid + minW / 2] : [p.a0, p.a1];
        const [mx0, my0] = polar(c.cx, c.cy, c.R + 2, mid);
        const [mx1, my1] = polar(c.cx, c.cy, c.R + 11, mid);
        return (
          <g key={i}>
            <path d={sectorPath(c.cx, c.cy, rr.r0 - 1, rr.r1 + 1, a0, a1)} fill="none" stroke={theme.text} strokeWidth={strong ? 2 : 1.25} />
            {strong && <line x1={mx0} y1={my0} x2={mx1} y2={my1} stroke={theme.text} strokeWidth={2} />}
          </g>
        );
      })}
    </g>
  );
}

/** A complete match (or a point mutation) is drawn filled; partial, contig-end and internal-stop hits hollow (for
 * VFDB, hits short of the whole reference; for mobile elements, partial elements). */
const isWhole = (piece: ArcPiece) => {
  const f = piece.feature;
  if (f.vfdb) return f.vfdb.hit_kind === "complete" || f.vfdb.hit_kind === "complete_gaps";
  if (f.mobile) return isWholeElement(f.mobile);
  return ["complete", "point"].includes(f.amr?.method_kind ?? "");
};

interface LegendItem {
  swatches: { fill: string; opacity?: number; stroke?: string }[];
  text: string;
}

function legendItems(t: ReturnType<typeof useT>, p: MapProps, models: CircleModel[], rings: RingId[], customCount: number): LegendItem[] {
  const th = p.theme;
  const skew = th.surface !== "#FFFFFF" ? SKEW.dark : SKEW.light;
  const scales = sharedScales(models);
  const max = (k: "gc" | "skew" | "coverage") => scales[k];
  const mean = models.length === 1 ? models[0].map.gc.genome_gc : null;
  const window = models[0]?.map.gc.window ?? 0;
  const items: LegendItem[] = [];
  const genes = [
    { fill: classColour(th, "coding") },
    { fill: classColour(th, "hypothetical"), opacity: 0.4 },
    { fill: classColour(th, "rna") },
    { fill: classColour(th, "element") },
  ];
  for (const r of rings) {
    if (r === "backbone") items.push({ swatches: [{ fill: th.axis }, { fill: th.grid }, { fill: classColour(th, "gap") }], text: t("circular.legend.backbone") });
    else if (r === "forward" || r === "reverse") items.push({ swatches: genes, text: t(`circular.legend.${r}`) });
    else if (r === "custom") items.push({ swatches: [{ fill: th.series[3] }], text: t("circular.legend.custom", { label: p.customLabel, n: fmtInt(customCount) }) });
    else if (r === "amr" || r === "virulence") {
      const n = models.reduce((sum, m) => sum + m[r].length, 0);
      items.push({
        swatches: [{ fill: amrColour(th, r) }, { fill: th.surface, stroke: amrColour(th, r) }],
        text: t(`circular.legend.${r}`, { n: fmtInt(n), version: p.amrRun?.tool_version ?? "?", db: p.amrRun?.database_version ?? "?" }),
      });
    } else if (r === "vfdb") {
      const n = models.reduce((sum, m) => sum + m.vfdb.length, 0);
      items.push({
        swatches: [{ fill: amrColour(th, "virulence") }, { fill: th.surface, stroke: amrColour(th, "virulence") }],
        text: t("circular.legend.vfdb", { n: fmtInt(n), version: p.vfdbRun?.tool_version ?? "?", db: p.vfdbRun?.database_version ?? "?" }),
      });
    } else if (r === "mobile") {
      const n = models.reduce((sum, m) => sum + m.mobile.length, 0);
      const methods = Object.entries(p.mobileRuns ?? {}).filter(([, v]) => v).map(([k]) => t(`mobile.method.${k}` as TranslationKey));
      items.push({ swatches: [{ fill: mobileColour(th) }, { fill: th.surface, stroke: mobileColour(th) }], text: t("circular.legend.mobile", { n: fmtInt(n), methods: methods.join(", ") }) });
    } else if (r === "coverage") items.push({ swatches: [{ fill: th.series[0], opacity: 0.85 }], text: t("circular.legend.coverage", { max: fmtNum(max("coverage"), 0) }) });
    else if (r === "gc")
      items.push({
        swatches: [{ fill: th.text, opacity: 0.7 }],
        text: t(mean != null ? "circular.legend.gc" : "circular.legend.gcEach", { mean: mean != null ? fmtPct(100 * mean, 1) : "", max: fmtNum(100 * max("gc"), 1), w: fmtInt(window) }),
      });
    else if (r === "skew") items.push({ swatches: [{ fill: skew.pos }, { fill: skew.neg }], text: t("circular.legend.skew", { max: fmtNum(max("skew"), 2), w: fmtInt(window) }) });
  }
  if (rings.includes("backbone") && (p.plasmidContigs?.size ?? 0) > 0) items.push({ swatches: [{ fill: plasmidContigColour(th) }], text: t("circular.legend.plasmidContigs", { n: fmtInt(p.plasmidContigs?.size ?? 0) }) });
  if (rings.includes("forward") || rings.includes("reverse")) items.push({ swatches: [], text: t("circular.legend.genesKey") });
  if (rings.includes("amr") || rings.includes("virulence") || rings.includes("vfdb")) items.push({ swatches: [], text: t("circular.legend.amrKey") });
  if (rings.includes("mobile")) items.push({ swatches: [], text: t("circular.legend.mobileKey") });
  return items;
}

function Legend({ items, top, theme, caption, synthetic }: { items: LegendItem[]; top: number; theme: ChartTheme; caption: string; synthetic: string | null }) {
  return (
    <g fontSize={11}>
      {items.map((item, i) => (
        <g key={i} transform={`translate(16 ${top + i * LEGEND_LINE})`}>
          {item.swatches.map((s, j) => (
            <rect key={j} x={j * 14} y={0} width={11} height={11} rx={2} fill={s.fill} fillOpacity={s.opacity ?? 1} stroke={s.stroke} strokeWidth={s.stroke ? 1.5 : 0} />
          ))}
          <text x={Math.max(1, item.swatches.length) * 14 + 6} y={9.5} fill={theme.text}>
            {item.text}
          </text>
        </g>
      ))}
      <text x={16} y={top + items.length * LEGEND_LINE + 14} fontSize={10} fill={theme.muted}>
        {caption}
      </text>
      {synthetic && (
        <text x={16} y={top + items.length * LEGEND_LINE + 14 + LEGEND_LINE} fontSize={10.5} fontWeight={600} fill={theme.text}>
          {synthetic}
        </text>
      )}
    </g>
  );
}

function Tooltip({ hit, placed, width, t }: { hit: Hit; placed: Placed[]; width: number; t: ReturnType<typeof useT> }) {
  const c = placed[hit.circle];
  const seq = hit.seq != null ? c.model.map.sequences[hit.seq] : null;
  const lines: string[] = [];
  const f = hit.piece?.feature;
  if (seq && hit.position != null) lines.push(`${seq.contig_in_assembly}:${fmtInt(hit.position)}`);
  if (seq && hit.position != null && (hit.ring === "gc" || hit.ring === "skew")) {
    const i = windowAt(seq.gc.start, seq.gc.end, hit.position);
    if (i >= 0) {
      lines.push(t("explorer.readoutWindow", { s: fmtInt(seq.gc.start[i]), e: fmtInt(seq.gc.end[i]) }));
      const gc = seq.gc.gc[i];
      const sk = seq.gc.skew[i];
      if (hit.ring === "gc" && gc != null) lines.push(`${t("explorer.track.gc")} ${fmtPct(100 * gc, 1)}`);
      if (hit.ring === "skew" && sk != null) lines.push(`${t("explorer.track.skew")} ${fmtNum(sk, 3)}`);
    }
  }
  if (seq && hit.position != null && hit.ring === "coverage" && seq.coverage.available) {
    const i = windowAt(seq.coverage.start, seq.coverage.end, hit.position);
    if (i >= 0 && seq.coverage.mean[i] != null) lines.push(t("circular.tooltip.depth", { v: fmtNum(seq.coverage.mean[i]!, 1) }));
  }
  if (!lines.length && !f) return null;
  const left = Math.min(hit.x + 14, width - 300);
  return (
    <div className="pointer-events-none absolute z-20 max-w-[290px] rounded-lg border bg-surface px-2.5 py-1.5 text-xs shadow-lg" style={{ left: Math.max(4, left), top: hit.y + 14 }} role="tooltip">
      {hit.ring && <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t(`circular.ring.${hit.ring}` as TranslationKey)}</div>}
      {f?.amr && (
        <div>
          <span className="font-medium">{f.amr.element_symbol}</span>
          <span className="text-muted-foreground">
            {" "}
            · {f.amr.type}
            {f.amr.amr_class ? ` · ${f.amr.amr_class}` : ""}
          </span>
          {f.amr.element_name && <div className="break-words">{f.amr.element_name}</div>}
          <div className="text-muted-foreground">
            {kindText(t, f.amr.method_kind)} ({f.amr.method})
            {f.amr.identity != null ? ` · ${t("amr.col.identity")} ${fmtNum(f.amr.identity, 2)}` : ""}
            {f.amr.coverage != null ? ` · ${t("amr.col.coverage")} ${fmtNum(f.amr.coverage, 2)}` : ""}
          </div>
          <div className="text-muted-foreground">
            {fmtInt(f.start)}–{fmtInt(f.end)} ({f.strand}){f.amr.feature?.locus_tag ? ` · ${f.amr.feature.locus_tag}` : ""}
          </div>
          <div className="text-[10px] text-muted-foreground">{t("amr.notPhenotype")}</div>
        </div>
      )}
      {f?.vfdb && (
        <div>
          <span className="font-medium">{f.vfdb.gene}</span>
          <span className="text-muted-foreground"> · {t("virulence.sourceName.vfdb")}</span>
          {(f.vfdb.vf_name || f.vfdb.product) && <div className="break-words">{f.vfdb.vf_name ?? f.vfdb.product}</div>}
          {f.vfdb.vf_category && <div className="text-muted-foreground">{f.vfdb.vf_category}</div>}
          <div className="text-muted-foreground">
            {t(`mobile.completeness.${["complete", "complete_gaps", "partial", "contig_end"].includes(f.vfdb.hit_kind) ? f.vfdb.hit_kind : "unknown"}` as TranslationKey)} · {t("amr.col.identity")} {fmtNum(f.vfdb.identity ?? 0, 2)} · {t("amr.col.coverage")} {fmtNum(f.vfdb.coverage ?? 0, 2)}
          </div>
          <div className="text-muted-foreground">
            {fmtInt(f.start)}–{fmtInt(f.end)} ({f.strand}){f.vfdb.feature?.locus_tag ? ` · ${f.vfdb.feature.locus_tag}` : ""}
          </div>
          <div className="text-[10px] text-muted-foreground">{t("virulence.notPhenotype")}</div>
        </div>
      )}
      {f?.mobile && (
        <div>
          <span className="font-medium">{f.mobile.element ?? "?"}</span>
          <span className="text-muted-foreground">
            {" "}
            · {t(categoryKey(f.mobile.category))} · {t(`mobile.method.${f.mobile.method}` as TranslationKey)}
          </span>
          {f.mobile.element_type && <div className="break-words">{f.mobile.element_type}</div>}
          <div className="text-muted-foreground">
            {f.mobile.completeness ? `${t(`mobile.completeness.${f.mobile.completeness}` as TranslationKey)} · ` : ""}
            {fmtInt(f.start)}–{fmtInt(f.end)} ({f.strand}){f.mobile.feature?.locus_tag ? ` · ${f.mobile.feature.locus_tag}` : ""}
          </div>
        </div>
      )}
      {f && !f.amr && !f.vfdb && !f.mobile && (
        <div>
          <span className="font-medium">{featureLabel(f)}</span>
          <span className="text-muted-foreground"> · {t(`annotation.type.${f.type}` as TranslationKey)}</span>
          {f.product && <div className="break-words">{f.product}</div>}
          <div className="text-muted-foreground">
            {fmtInt(f.start)}–{fmtInt(f.end)} ({f.strand}) · {fmtBp(f.length)}
            {f.hypothetical ? ` · ${t("annotation.hypotheticalBadge")}` : ""}
            {f.pseudo ? ` · ${t("annotation.pseudoBadge")}` : ""}
          </div>
        </div>
      )}
      {lines.map((l) => (
        <div key={l} className={f ? "text-muted-foreground" : undefined}>
          {l}
        </div>
      ))}
    </div>
  );
}

