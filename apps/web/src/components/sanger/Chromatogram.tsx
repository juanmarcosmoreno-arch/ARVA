import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useId, useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { CHANNELS, centreOn, clampWindow, moveWindow, scanOfBase, scanX, tracePaths, trimmedRanges, type Channel, type TraceMarker, type TraceView } from "@/lib/sanger";
import { cn } from "@/lib/utils";

const W = 1000;
const TRACE_H = 150;
const BASE_Y = 168;
const QUAL_TOP = 180;
const QUAL_H = 50;
const Q_MAX = 60;
const DEFAULT_WIDTH = 1200;
// Letters are drawn when the window holds at most this many bases; beyond it only the quality bars are.
const MAX_LETTERS = 220;

/** The usual chromatogram colours (A green, C blue, G black, T red); G is light in dark mode so it stays visible. */
export const CHANNEL_STROKE: Record<Channel, string> = {
  A: "stroke-green-600",
  C: "stroke-blue-600",
  G: "stroke-neutral-800 dark:stroke-neutral-200",
  T: "stroke-red-600",
};
/** A dash pattern per trace as well, so that A (green) and T (red) differ for readers who cannot tell red from green:
 * A solid, C long dashes, G dots, T dash-dot. */
export const CHANNEL_DASH: Record<Channel, string | undefined> = { A: undefined, C: "6 3", G: "1.5 2.5", T: "7 2.5 1.5 2.5" };
export const CHANNEL_FILL: Record<Channel, string> = {
  A: "fill-green-600",
  C: "fill-blue-600",
  G: "fill-neutral-800 dark:fill-neutral-200",
  T: "fill-red-600",
};

const KEYS: Record<string, Parameters<typeof moveWindow>[2]> = {
  ArrowLeft: "left",
  ArrowRight: "right",
  PageUp: "pageLeft",
  PageDown: "pageRight",
  "+": "zoomIn",
  "=": "zoomIn",
  "-": "zoomOut",
  Home: "home",
  End: "end",
};

/** A read's chromatogram: the four traces, the called bases and their Phred qualities, the trimmed ends shaded, and
 * the bases to review (mixed peaks, IUPAC calls) and the consensus conflicts highlighted. Zoom and scroll with the
 * buttons, the overview strip or the keyboard (arrows, Page Up/Down, + and -, Home and End). Positions are those of
 * the file's base calls; the traces are shown as the instrument recorded them. */
export function Chromatogram({
  readId,
  name,
  length,
  trim,
  review = [],
  conflicts = [],
  focus,
  focusKey,
}: {
  readId: string;
  name: string;
  length: number;
  trim: { start: number | null; end: number | null } | null;
  review?: number[];
  conflicts?: number[];
  focus?: number | null;
  /** Changes on every request to show `focus`, so asking again for the same base brings the window back to it. */
  focusKey?: number;
}) {
  const t = useT();
  const helpId = useId();
  const overview = useQuery({ queryKey: ["sangerTrace", readId, "overview"], queryFn: () => api.sangerTrace(readId, 0, null, 600), staleTime: 300_000 });
  const scans = overview.data?.scans ?? 0;
  const [win, setWin] = useState<{ start: number; width: number } | null>(null);
  const [goTo, setGoTo] = useState("");
  const [goMissing, setGoMissing] = useState<number | null>(null);
  useEffect(() => {
    if (!overview.data || win) return;
    const start = trim?.start ? (scanOfBase(overview.data.markers, trim.start) ?? 0) : 0;
    setWin(clampWindow(start - 100, DEFAULT_WIDTH, overview.data.scans));
  }, [overview.data, win, trim?.start]);
  useEffect(() => {
    if (!overview.data || focus == null) return;
    const scan = scanOfBase(overview.data.markers, focus);
    if (scan != null) setWin((w) => centreOn(scan, w?.width ?? DEFAULT_WIDTH, overview.data.scans));
  }, [focus, focusKey, overview.data]);
  const detail = useQuery({
    queryKey: ["sangerTrace", readId, win?.start, win?.width],
    queryFn: () => api.sangerTrace(readId, win!.start, win!.start + win!.width, 900),
    enabled: win !== null,
    placeholderData: keepPreviousData,
    staleTime: 300_000,
  });
  const reviewSet = useMemo(() => new Set(review), [review]);
  const conflictSet = useMemo(() => new Set(conflicts), [conflicts]);
  const kept = (pos: number) => trim?.start != null && trim.end != null && pos >= trim.start && pos <= trim.end;

  const act = (action: Parameters<typeof moveWindow>[2]) => win && setWin(moveWindow(win, scans, action));
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const action = e.shiftKey && e.key === "ArrowLeft" ? "pageLeft" : e.shiftKey && e.key === "ArrowRight" ? "pageRight" : KEYS[e.key];
    if (!action) return;
    e.preventDefault();
    act(action);
  };
  const jump = () => {
    const pos = Number.parseInt(goTo, 10);
    const scan = overview.data && Number.isFinite(pos) ? scanOfBase(overview.data.markers, pos) : null;
    setGoMissing(scan == null && Number.isFinite(pos) ? pos : null);
    if (scan != null && win) setWin(centreOn(scan, win.width, scans));
  };

  if (overview.error) return <ErrorNote error={overview.error} />;
  if (!overview.data || !win) return <Skeleton className="h-64" />;
  const view = detail.data;
  const shown = view?.markers ?? [];
  const range = shown.length ? t("sanger.chrom.range", { from: fmtInt(shown[0].origin), to: fmtInt(shown[shown.length - 1].origin), n: fmtInt(length) }) : t("sanger.chrom.noBases");

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Button size="sm" variant="outline" onClick={() => act("pageLeft")} aria-label={t("sanger.chrom.pageLeft")}>
          <ChevronsLeft className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("left")} aria-label={t("sanger.chrom.left")}>
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("right")} aria-label={t("sanger.chrom.right")}>
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("pageRight")} aria-label={t("sanger.chrom.pageRight")}>
          <ChevronsRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("zoomIn")} aria-label={t("sanger.chrom.zoomIn")}>
          <ZoomIn className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("zoomOut")} aria-label={t("sanger.chrom.zoomOut")}>
          <ZoomOut className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <form
          className="ml-2 flex items-center gap-1.5 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            jump();
          }}
        >
          <label className="text-muted-foreground" htmlFor={`${helpId}-goto`}>
            {t("sanger.chrom.goTo")}
          </label>
          <Input id={`${helpId}-goto`} className="h-8 w-20" inputMode="numeric" value={goTo} onChange={(e) => setGoTo(e.target.value)} />
          <Button size="sm" variant="secondary" type="submit">
            {t("sanger.chrom.go")}
          </Button>
          {goMissing != null && (
            <span className="text-danger" role="status">
              {t("sanger.chrom.outOfRange", { n: fmtInt(goMissing), max: fmtInt(length) })}
            </span>
          )}
        </form>
        <span className="ml-auto text-xs text-muted-foreground" aria-live="polite">
          {range}
        </span>
      </div>
      <div
        tabIndex={0}
        role="group"
        aria-label={t("sanger.chrom.label", { name })}
        aria-describedby={helpId}
        onKeyDown={onKey}
        className="rounded-lg border bg-surface p-2 focus-visible:ring-2"
      >
        {view ? <TraceSvg view={view} kept={kept} review={reviewSet} conflicts={conflictSet} label={t("sanger.chrom.imageLabel", { name, range })} /> : <Skeleton className="h-56" />}
      </div>
      <Overview overview={overview.data} length={length} trim={trim} win={win} onPick={(scan) => setWin(centreOn(scan, win.width, scans))} />
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        {CHANNELS.map((c) => (
          <span key={c} className="inline-flex items-center gap-1">
            <svg width="22" height="6" aria-hidden>
              <line x1="0" y1="3" x2="22" y2="3" className={CHANNEL_STROKE[c]} strokeWidth="2" strokeDasharray={CHANNEL_DASH[c]} />
            </svg>
            {c}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-3 rounded-sm bg-muted-foreground/20" aria-hidden /> {t("sanger.chrom.legendTrimmed")}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-3 rounded-sm bg-amber-300/70" aria-hidden /> {t("sanger.chrom.legendReview")}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-3 rounded-sm border-2 border-danger" aria-hidden /> {t("sanger.chrom.legendConflict")}
        </span>
        <span>{t("sanger.chrom.legendQuality", { max: Q_MAX })}</span>
      </div>
      <p id={helpId} className="text-[11px] text-muted-foreground">
        {t("sanger.chrom.keys")}
      </p>
    </div>
  );
}

function TraceSvg({ view, kept, review, conflicts, label }: { view: TraceView; kept: (p: number) => boolean; review: Set<number>; conflicts: Set<number>; label: string }) {
  const { paths } = useMemo(() => tracePaths(view, W, TRACE_H), [view]);
  const markers = view.markers;
  const xs = markers.map((m) => scanX(view, m.scan, W));
  const spacing = markers.length > 1 ? (xs[xs.length - 1] - xs[0]) / (markers.length - 1) : 12;
  const half = Math.max(1, spacing / 2);
  const letters = markers.length <= MAX_LETTERS;
  const bar = Math.max(1, Math.min(9, spacing * 0.7));
  return (
    <svg viewBox={`0 0 ${W} ${QUAL_TOP + QUAL_H + 4}`} className="h-auto w-full" role="img" aria-label={label} preserveAspectRatio="none">
      {markers.map((m, i) =>
        kept(m.origin) ? null : <rect key={`t${m.origin}`} x={xs[i] - half} y={0} width={half * 2} height={QUAL_TOP + QUAL_H} className="fill-muted-foreground/15" />,
      )}
      {markers.map((m, i) =>
        review.has(m.origin) ? <rect key={`r${m.origin}`} x={xs[i] - half} y={0} width={half * 2} height={TRACE_H + 26} className="fill-amber-300/50" /> : null,
      )}
      {CHANNELS.map((c) => (
        <polyline key={c} points={paths[c]} fill="none" strokeWidth={1.3} strokeDasharray={CHANNEL_DASH[c]} vectorEffect="non-scaling-stroke" className={CHANNEL_STROKE[c]} />
      ))}
      {markers.map((m, i) => (
        <g key={m.origin}>
          {conflicts.has(m.origin) && <rect x={xs[i] - half} y={BASE_Y - 13} width={half * 2} height={17} fill="none" strokeWidth={2} className="stroke-danger" />}
          {letters && (
            <text x={xs[i]} y={BASE_Y} textAnchor="middle" fontSize={11} fontFamily="ui-monospace, monospace" className={(CHANNEL_FILL as Record<string, string>)[m.base] ?? "fill-amber-600"} opacity={kept(m.origin) ? 1 : 0.45}>
              {m.base}
            </text>
          )}
          <QualityBar marker={m} x={xs[i]} width={bar} />
        </g>
      ))}
      <line x1={0} x2={W} y1={QUAL_TOP + QUAL_H - (20 / Q_MAX) * QUAL_H} y2={QUAL_TOP + QUAL_H - (20 / Q_MAX) * QUAL_H} strokeDasharray="4 3" strokeWidth={1} className="stroke-muted-foreground/60" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function QualityBar({ marker, x, width }: { marker: TraceMarker; x: number; width: number }) {
  if (marker.quality == null) return null;
  const h = (Math.min(Q_MAX, marker.quality) / Q_MAX) * QUAL_H;
  return <rect x={x - width / 2} y={QUAL_TOP + QUAL_H - h} width={width} height={h} className={cn(marker.quality >= 20 ? "fill-arva-teal/70" : "fill-warning/80")} />;
}

/** The whole read at a glance: quality along the trace, the trimmed ends, and the window shown; a click centres it. */
function Overview({ overview, length, trim, win, onPick }: { overview: TraceView; length: number; trim: { start: number | null; end: number | null } | null; win: { start: number; width: number }; onPick: (scan: number) => void }) {
  const t = useT();
  const scans = Math.max(1, overview.scans);
  const x = (scan: number) => (scan / scans) * W;
  const shaded = trimmedRanges(length, trim)
    .map(([a, b]) => [scanOfBase(overview.markers, a), scanOfBase(overview.markers, b)] as const)
    .filter((r): r is readonly [number, number] => r[0] != null && r[1] != null);
  const pick = (e: MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width > 0) onPick(((e.clientX - box.left) / box.width) * scans);
  };
  return (
    <svg viewBox={`0 0 ${W} 36`} className="h-9 w-full cursor-pointer rounded border bg-muted/30" preserveAspectRatio="none" onClick={pick} role="img" aria-label={t("sanger.chrom.overview")}>
      {shaded.map(([a, b]) => (
        <rect key={a} x={x(a)} y={0} width={Math.max(1, x(b) - x(a))} height={36} className="fill-muted-foreground/20" />
      ))}
      {overview.markers.map((m) =>
        m.quality == null ? null : <rect key={m.origin} x={x(m.scan)} y={36 - (Math.min(Q_MAX, m.quality) / Q_MAX) * 32} width={1} height={(Math.min(Q_MAX, m.quality) / Q_MAX) * 32} className={m.quality >= 20 ? "fill-arva-teal/60" : "fill-warning/70"} />,
      )}
      <rect x={x(win.start)} y={1} width={Math.max(2, x(win.width))} height={34} fill="none" strokeWidth={2} className="stroke-arva-royal dark:stroke-arva-cyan" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
