import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Pause, Play, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { type ChartTheme, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { type ContigOption, featureLabel } from "@/lib/explorer";
import { fmtInt, fmtNum } from "@/lib/format";
import { categoryKey } from "@/lib/mobile";
import {
  BLOCK,
  BP_PER_TURN,
  baseKind,
  blocksFor,
  changesAt,
  codonsAt,
  complement,
  DIAMETER_NM,
  depthAt,
  distanceNm,
  grooveCentres,
  hydrogenBonds,
  inRange,
  isAminoAcid,
  parsePosition,
  RISE_NM,
  rungShare,
  SPEEDS,
  strandAngles,
  turnOf,
  wrapPosition,
} from "@/lib/helix";
import type { HelixWindow } from "@/lib/types";

/** Base pairs drawn above and below the reading head, and shown in the sequence window either side of it. */
const HALF = 16;
const SEQ_HALF = 12;
/** Pixels per nanometre: rise and diameter are drawn to the same scale (0.34 nm per pair, 2 nm across). */
const PX_PER_NM = 46;
const RISE_PX = RISE_NM * PX_PER_NM;
const RADIUS_PX = (DIAMETER_NM / 2) * PX_PER_NM;
const W = 300;
const H = (2 * HALF + 1) * RISE_PX + 24;
const CX = 150;
const CY = H / 2;

/** Base colours: four slots of ARVA's validated chart palette. A and G (both purines, drawn the same length) and C
 * and T (both pyrimidines) are each a pair that passes the colour-vision-deficiency and contrast checks in both
 * themes (light: worst CVD ΔE 13.2 / 19.0; dark: 13.2 / 17.5); a purine and a pyrimidine also differ in rung length,
 * hydrogen-bond lines and letter, so the one weaker pair across groups (pink and teal in dark mode) is never the only
 * cue. N and other IUPAC codes take the muted neutral and no pair. */
export function baseColour(theme: ChartTheme, ch: string): string {
  const k = baseKind(ch);
  if (k.kind !== "base") return theme.muted;
  return theme.series[{ A: 3, G: 4, C: 2, T: 0 }[k.base]];
}

function usePrefersReducedMotion(): boolean {
  const query = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  const [reduced, setReduced] = useState(() => query?.matches ?? false);
  useEffect(() => {
    if (!query) return;
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, [query]);
  return reduced;
}

/** The position shown, eased towards the reading head (or jumping there when motion is reduced). */
function useEased(target: number, reduced: boolean): number {
  const [shown, setShown] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    if (reduced || Math.abs(target - current.current) > 3 * HALF || typeof requestAnimationFrame === "undefined") {
      current.current = target;
      setShown(target);
      return;
    }
    let frame = 0;
    const from = current.current;
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 220);
      current.current = from + (target - from) * (1 - (1 - k) ** 3);
      setShown(current.current);
      if (k < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, reduced]);
  return shown;
}

interface Props {
  annotationId: string;
  contig: ContigOption;
  position: number;
  onPosition: (pos: number) => void;
  onClose: () => void;
}

/**
 * The double-helix view of one position of an annotated sequence: a schematic B-DNA helix of the real bases around
 * the reading head, the pair at the head, a sequence window, the helix facts and what ARVA knows about the position
 * (features and the codon read there, AMR / virulence / mobile-element calls, polishing changes, read depth).
 */
export function DoubleHelix({ annotationId, contig, position, onPosition, onClose }: Props) {
  const t = useT();
  const theme = useChartTheme();
  const reduced = usePrefersReducedMotion();
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(2);
  const [jump, setJump] = useState("");
  const length = contig.length;
  const circular = contig.circular === true;
  const pos = Math.min(Math.max(1, Math.round(position)), length);
  const move = (to: number) => {
    const p = wrapPosition(to, length, circular);
    if (p != null) onPosition(p);
    else onPosition(to < 1 ? 1 : length);
  };

  // The blocks of bases (and their context) that the drawing and the sequence window need.
  const wanted = useMemo(() => {
    const ps: number[] = [];
    for (let d = -HALF - 1; d <= HALF + 1; d++) {
      const p = wrapPosition(pos + d, length, circular);
      if (p != null) ps.push(p);
    }
    return blocksFor(ps);
  }, [pos, length, circular]);
  const blocks = useQueries({
    queries: wanted.map((start) => ({
      queryKey: ["explorerHelix", annotationId, contig.id, start],
      queryFn: () => api.annotationHelix(annotationId, contig.id, start, Math.min(length, start + BLOCK - 1)),
      staleTime: Infinity,
    })),
  });
  const loaded = blocks.map((b) => b.data).filter((d): d is HelixWindow => !!d && d.contig === contig.id);
  const baseAt = (p: number): string | null => {
    const b = loaded.find((w) => p >= w.start && p <= w.end);
    return b ? b.sequence[p - b.start] ?? null : null;
  };
  const here = loaded.find((w) => pos >= w.start && pos <= w.end);
  const error = blocks.find((b) => b.error)?.error;

  // Scanning: one step at a time at the chosen speed; it stops at the end of a linear sequence.
  const posRef = useRef(pos);
  posRef.current = pos;
  const onPositionRef = useRef(onPosition);
  onPositionRef.current = onPosition;
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const next = wrapPosition(posRef.current + 1, length, circular);
      if (next == null) setPlaying(false);
      else onPositionRef.current(next);
    }, 1000 / speed);
    return () => clearInterval(timer);
  }, [playing, speed, length, circular]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("input, select")) return;
    const keys: Record<string, () => void> = {
      ArrowUp: () => move(pos - 1),
      ArrowLeft: () => move(pos - 1),
      ArrowDown: () => move(pos + 1),
      ArrowRight: () => move(pos + 1),
      PageUp: () => move(pos - 10),
      PageDown: () => move(pos + 10),
      Home: () => onPosition(1),
      End: () => onPosition(length),
      " ": () => setPlaying((x) => !x),
    };
    const action = keys[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  };

  const base = baseAt(pos);
  return (
    <section
      aria-label={t("helix.title")}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="rounded-xl border bg-surface p-3 outline-none focus-visible:ring-2 focus-visible:ring-arva-royal dark:focus-visible:ring-arva-cyan"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{t("helix.title")}</h3>
        <span className="text-xs text-muted-foreground">{t("helix.schematic")}</span>
        <span className="ml-auto flex items-center gap-1">
          <Explain id="double_helix" compact />
          <Explain id="base_pairing" compact />
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("helix.close")}>
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </span>
      </header>
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <HelixDrawing theme={theme} shownTarget={pos} reduced={reduced} baseAt={baseAt} length={length} circular={circular} t={t} />
        <div className="min-w-0 space-y-3 text-sm">
          <Controls
            t={t}
            pos={pos}
            length={length}
            playing={playing}
            onPlay={() => setPlaying((x) => !x)}
            speed={speed}
            onSpeed={setSpeed}
            onPrev={() => move(pos - 1)}
            onNext={() => move(pos + 1)}
            jump={jump}
            onJump={setJump}
            onGo={() => {
              const p = parsePosition(jump, length);
              if (p != null) {
                onPosition(p);
                setJump("");
              }
            }}
            jumpInvalid={jump !== "" && parsePosition(jump, length) == null}
          />
          <PairPanel t={t} theme={theme} pos={pos} base={base} contig={contig.name} length={length} />
          <SequenceWindow t={t} theme={theme} pos={pos} baseAt={baseAt} length={length} circular={circular} onPick={onPosition} />
          <HelixFacts t={t} pos={pos} />
          <ContextPanel t={t} annotationId={annotationId} contig={contig} pos={pos} data={here} />
          <ErrorNote error={error} />
          <p className="text-[11px] text-muted-foreground">{t("helix.keys")}</p>
        </div>
      </div>
    </section>
  );
}

function HelixDrawing({ theme, shownTarget, reduced, baseAt, length, circular, t }: {
  theme: ChartTheme;
  shownTarget: number;
  reduced: boolean;
  baseAt: (p: number) => string | null;
  length: number;
  circular: boolean;
  t: ReturnType<typeof useT>;
}) {
  const shown = useEased(shownTarget, reduced);
  const y = (p: number) => CY + (p - shown) * RISE_PX;
  const first = Math.floor(shown) - HALF;
  const last = Math.ceil(shown) + HALF;
  // Backbones sampled every quarter pair, split where they pass behind the axis.
  const segments: { d: string; front: boolean; strand: 0 | 1 }[] = [];
  for (const strand of [0, 1] as const) {
    let d = "";
    let front: boolean | null = null;
    for (let q = first * 4; q <= last * 4; q++) {
      const p = q / 4;
      if (wrapPosition(Math.round(p), length, circular) == null) {
        if (d) segments.push({ d, front: !!front, strand });
        d = "";
        front = null;
        continue;
      }
      const a = (strandAngles(p)[strand] * Math.PI) / 180;
      const x = CX + RADIUS_PX * Math.sin(a);
      const isFront = Math.cos(a) >= 0;
      if (front !== null && isFront !== front) {
        d += ` L${x.toFixed(1)},${y(p).toFixed(1)}`;
        segments.push({ d, front, strand });
        d = "";
      }
      d += `${d ? " L" : "M"}${x.toFixed(1)},${y(p).toFixed(1)}`;
      front = isFront;
    }
    if (d) segments.push({ d, front: !!front, strand });
  }
  const rungs = [];
  for (let p = first; p <= last; p++) {
    const real = wrapPosition(p, length, circular);
    if (real == null) continue;
    const [a1, a2] = strandAngles(p).map((deg) => (deg * Math.PI) / 180);
    const x1 = CX + RADIUS_PX * Math.sin(a1);
    const x2 = CX + RADIUS_PX * Math.sin(a2);
    const depth = (Math.cos(a1) + Math.cos(a2)) / 2;
    rungs.push({ p, real, x1, x2, depth, b: baseAt(real) });
  }
  rungs.sort((r1, r2) => r1.depth - r2.depth);
  const grooves = grooveCentres(shown);
  const turnStarts = rungs.filter((r) => turnOf(r.real).pairInTurn === 1);
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      role="img"
      aria-label={t("helix.drawingLabel", { pos: fmtInt(wrapPosition(Math.round(shownTarget), length, circular) ?? shownTarget) })}
      className="mx-auto max-w-full"
      fontFamily="Inter Variable, Inter, system-ui, sans-serif"
    >
      <rect x={0} y={CY - RISE_PX / 2} width={W} height={RISE_PX} fill={theme.primary} opacity={0.1} />
      {segments.filter((s) => !s.front).map((s, i) => (
        <path key={`b${i}`} d={s.d} fill="none" stroke={theme.muted} strokeWidth={4} strokeLinecap="round" opacity={0.45} />
      ))}
      {rungs.map((r) => (
        <Rung key={r.p} theme={theme} x1={r.x1} x2={r.x2} y={y(r.p)} base={r.b} depth={r.depth} head={r.real === shownTarget} />
      ))}
      {segments.filter((s) => s.front).map((s, i) => (
        <path key={`f${i}`} d={s.d} fill="none" stroke={s.strand === 0 ? theme.text : theme.muted} strokeWidth={5} strokeLinecap="round" />
      ))}
      {/* Groove labels where each groove faces the viewer near the reading head. */}
      {(["major", "minor"] as const).map((g) =>
        Math.abs(grooves[g] - shown) <= HALF - 1 ? (
          <g key={g}>
            <line x1={CX + RADIUS_PX + 6} x2={CX + RADIUS_PX + 16} y1={y(grooves[g])} y2={y(grooves[g])} stroke={theme.axis} />
            <text x={CX + RADIUS_PX + 19} y={y(grooves[g]) + 3.5} fontSize={10} fill={theme.muted}>
              {t(`helix.groove.${g}`)}
            </text>
          </g>
        ) : null,
      )}
      {turnStarts.map((r) => (
        <g key={`t${r.p}`}>
          <line x1={8} x2={CX - RADIUS_PX - 8} y1={y(r.p)} y2={y(r.p)} stroke={theme.axis} strokeDasharray="2 3" />
          <text x={8} y={y(r.p) - 3} fontSize={9.5} fill={theme.muted}>
            {t("helix.turnMark", { n: fmtInt(turnOf(r.real).turn) })}
          </text>
        </g>
      ))}
      {rungs
        .filter((r) => r.real % 5 === 0 || r.real === shownTarget)
        .map((r) => (
          <text key={`n${r.p}`} x={W - 6} y={y(r.p) + 3.5} fontSize={9.5} textAnchor="end" fill={r.real === shownTarget ? theme.text : theme.muted} fontWeight={r.real === shownTarget ? 600 : 400}>
            {fmtInt(r.real)}
          </text>
        ))}
    </svg>
  );
}

/** One base pair: the first strand's base from its backbone to the split, the complement from the other; a purine's
 * half longer than a pyrimidine's; 2 or 3 short lines for the hydrogen bonds. N and IUPAC codes: a dashed grey half
 * and no partner. */
function Rung({ theme, x1, x2, y, base, depth, head }: { theme: ChartTheme; x1: number; x2: number; y: number; base: string | null; depth: number; head: boolean }) {
  const opacity = 0.55 + 0.45 * ((depth + 1) / 2);
  if (base == null) return <line x1={x1} x2={x2} y1={y} y2={y} stroke={theme.grid} strokeWidth={3} opacity={opacity} />;
  const k = baseKind(base);
  const other = complement(base);
  if (k.kind !== "base") {
    return (
      <g opacity={opacity}>
        <line x1={x1} x2={x2} y1={y} y2={y} stroke={theme.muted} strokeWidth={2.5} strokeDasharray="3 3" />
        {head && <text x={(x1 + x2) / 2} y={y - 4} fontSize={9} textAnchor="middle" fill={theme.text}>{base.toUpperCase()}</text>}
      </g>
    );
  }
  const share = rungShare(base, other);
  const split = x1 + (x2 - x1) * share;
  const gap = Math.min(4, Math.abs(x2 - x1) / 6) * Math.sign(x2 - x1);
  const bonds = hydrogenBonds(base) ?? 0;
  const width = head ? 6 : 4.5;
  return (
    <g opacity={opacity}>
      <line x1={x1} x2={split - gap} y1={y} y2={y} stroke={baseColour(theme, base)} strokeWidth={width} />
      <line x1={split + gap} x2={x2} y1={y} y2={y} stroke={baseColour(theme, other)} strokeWidth={width} />
      {Math.abs(x2 - x1) > 18 &&
        Array.from({ length: bonds }, (_, i) => {
          const dy = (i - (bonds - 1) / 2) * 1.8;
          return <line key={i} x1={split - gap} x2={split + gap} y1={y + dy} y2={y + dy} stroke={theme.text} strokeWidth={0.7} />;
        })}
    </g>
  );
}

function Controls(p: {
  t: ReturnType<typeof useT>;
  pos: number;
  length: number;
  playing: boolean;
  onPlay: () => void;
  speed: number;
  onSpeed: (n: number) => void;
  onPrev: () => void;
  onNext: () => void;
  jump: string;
  onJump: (s: string) => void;
  onGo: () => void;
  jumpInvalid: boolean;
}) {
  const { t } = p;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Button variant="outline" size="icon" onClick={p.onPrev} aria-label={t("helix.prev")}>
        <ChevronLeft className="h-4 w-4" aria-hidden />
      </Button>
      <Button variant="outline" size="icon" onClick={p.onPlay} aria-label={t(p.playing ? "helix.pause" : "helix.play")} aria-pressed={p.playing}>
        {p.playing ? <Pause className="h-4 w-4" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
      </Button>
      <Button variant="outline" size="icon" onClick={p.onNext} aria-label={t("helix.next")}>
        <ChevronRight className="h-4 w-4" aria-hidden />
      </Button>
      <label className="space-y-1 text-xs">
        <span className="block text-muted-foreground">{t("helix.speed")}</span>
        <Select value={p.speed} onChange={(e) => p.onSpeed(Number(e.target.value))} className="w-28">
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {t("helix.speedValue", { n: s })}
            </option>
          ))}
        </Select>
      </label>
      <form
        className="flex items-end gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          p.onGo();
        }}
      >
        <label className="space-y-1 text-xs">
          <span className="block text-muted-foreground">{t("helix.jump")}</span>
          <Input value={p.jump} onChange={(e) => p.onJump(e.target.value)} inputMode="numeric" placeholder={t("helix.jumpPlaceholder", { max: fmtInt(p.length) })} className="w-36" aria-invalid={p.jumpInvalid} />
        </label>
        <Button type="submit" variant="secondary" size="sm" disabled={p.jumpInvalid || !p.jump}>
          {t("helix.go")}
        </Button>
      </form>
    </div>
  );
}

function BaseLine({ t, theme, ch, strand }: { t: ReturnType<typeof useT>; theme: ChartTheme; ch: string; strand: 1 | 2 }) {
  const k = baseKind(ch);
  let detail: string;
  if (k.kind === "base") {
    detail = `${t(`helix.base.${k.base}`)} · ${t(k.purine ? "helix.purine" : "helix.pyrimidine")} · ${t("helix.rings", { n: k.rings })}`;
  } else if (k.kind === "gap") {
    detail = t("helix.unknownBase");
  } else if (k.kind === "ambiguous") {
    detail = t("helix.ambiguous", { code: k.code, bases: k.means.join(" / ") });
  } else {
    detail = t("helix.otherCharacter", { code: k.code });
  }
  return (
    <div className="flex items-baseline gap-2">
      <span className="w-24 shrink-0 text-xs text-muted-foreground">{t(strand === 1 ? "helix.strand1" : "helix.strand2")}</span>
      <span className="font-mono text-base font-semibold" style={{ color: baseColour(theme, ch) }}>
        {ch.toUpperCase()}
      </span>
      <span className="text-xs">{detail}</span>
    </div>
  );
}

function PairPanel({ t, theme, pos, base, contig, length }: { t: ReturnType<typeof useT>; theme: ChartTheme; pos: number; base: string | null; contig: string; length: number }) {
  const k = base ? baseKind(base) : null;
  return (
    <div className="rounded-lg border p-2" aria-live="polite">
      <div className="mb-1 text-xs text-muted-foreground">{t("helix.position", { pos: fmtInt(pos), length: fmtInt(length), contig })}</div>
      {base == null ? (
        <p className="text-xs text-muted-foreground">{t("common.loading")}</p>
      ) : (
        <>
          <BaseLine t={t} theme={theme} ch={base} strand={1} />
          {k?.kind === "base" ? (
            <>
              <BaseLine t={t} theme={theme} ch={complement(base)} strand={2} />
              <p className="mt-1 text-xs">{t("helix.pair", { a: base.toUpperCase(), b: complement(base), n: hydrogenBonds(base) ?? 0 })}</p>
            </>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">{t("helix.notPaired")}</p>
          )}
          {base !== base.toUpperCase() && <p className="mt-1 text-xs text-muted-foreground">{t("helix.lowercase")}</p>}
        </>
      )}
    </div>
  );
}

function SequenceWindow({ t, theme, pos, baseAt, length, circular, onPick }: { t: ReturnType<typeof useT>; theme: ChartTheme; pos: number; baseAt: (p: number) => string | null; length: number; circular: boolean; onPick: (p: number) => void }) {
  const cells = Array.from({ length: 2 * SEQ_HALF + 1 }, (_, i) => wrapPosition(pos - SEQ_HALF + i, length, circular));
  const row = (strand: 1 | 2) => (
    <div className="flex items-center gap-[2px] font-mono text-xs">
      <span className="w-8 text-right text-muted-foreground">{strand === 1 ? "5′" : "3′"}</span>
      {cells.map((p, i) => {
        if (p == null) return <span key={i} className="w-4" />;
        const b = baseAt(p);
        const ch = b == null ? "·" : strand === 1 ? b.toUpperCase() : complement(b);
        const isHead = p === pos;
        return (
          <button
            key={i}
            type="button"
            tabIndex={-1}
            onClick={() => onPick(p)}
            title={fmtInt(p)}
            className={`w-4 rounded text-center ${isHead ? "bg-arva-royal/15 font-bold ring-1 ring-arva-royal dark:bg-arva-cyan/20 dark:ring-arva-cyan" : ""}`}
            style={{ color: b == null ? undefined : baseColour(theme, ch) }}
          >
            {ch}
          </button>
        );
      })}
      <span className="w-8 text-muted-foreground">{strand === 1 ? "3′" : "5′"}</span>
    </div>
  );
  return (
    <div className="overflow-x-auto rounded-lg border p-2">
      <div className="mb-1 text-xs text-muted-foreground">{t("helix.window")}</div>
      {row(1)}
      {row(2)}
    </div>
  );
}

function HelixFacts({ t, pos }: { t: ReturnType<typeof useT>; pos: number }) {
  const { turn, pairInTurn } = turnOf(pos);
  const nm = distanceNm(pos);
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg border p-2 text-xs sm:grid-cols-4">
      <dt className="text-muted-foreground">{t("helix.fact.turn")}</dt>
      <dd>{fmtInt(turn)}</dd>
      <dt className="text-muted-foreground">{t("helix.fact.pairInTurn")}</dt>
      <dd>{t("helix.fact.pairOf", { n: pairInTurn, per: fmtNum(BP_PER_TURN, 1) })}</dd>
      <dt className="text-muted-foreground">{t("helix.fact.distance")}</dt>
      <dd>{nm >= 1000 ? t("helix.fact.um", { n: fmtNum(nm / 1000, 2) }) : t("helix.fact.nm", { n: fmtNum(nm, 2) })}</dd>
      <dt className="text-muted-foreground">{t("helix.fact.geometry")}</dt>
      <dd>{t("helix.fact.geometryValue", { per: fmtNum(BP_PER_TURN, 1), rise: fmtNum(RISE_NM, 2) })}</dd>
      <dd className="col-span-full text-muted-foreground">{t("helix.key")}</dd>
    </dl>
  );
}

function ContextPanel({ t, annotationId, contig, pos, data: w }: { t: ReturnType<typeof useT>; annotationId: string; contig: ContigOption; pos: number; data: HelixWindow | undefined }) {
  const amr = useQuery({ queryKey: ["annotationAmr", annotationId], queryFn: () => api.annotationAmr(annotationId), staleTime: 60_000 });
  const vfdb = useQuery({ queryKey: ["annotationVirulence", annotationId], queryFn: () => api.annotationVirulence(annotationId), staleTime: 60_000 });
  const mobile = useQuery({ queryKey: ["annotationMobile", annotationId], queryFn: () => api.annotationMobile(annotationId), staleTime: 60_000 });
  if (!w) return <p className="text-xs text-muted-foreground">{t("common.loading")}</p>;
  const features = codonsAt(w.features, pos);
  const amrHits = (amr.data?.hits ?? []).filter((h) => h.contig === contig.id && h.start != null && inRange(pos, h.start, h.end));
  const vfHits = (vfdb.data?.hits ?? []).filter((h) => h.contig === contig.id && inRange(pos, h.start, h.end));
  const elements = (mobile.data?.elements ?? []).filter((e) => e.contig === contig.id && inRange(pos, e.start, e.end));
  const call = (mobile.data?.contigs ?? []).find((c) => c.contig === contig.id);
  const changes = changesAt(w.polishing.changes, pos);
  const depth = depthAt(w.coverage, pos);
  return (
    <div className="space-y-2 rounded-lg border p-2 text-xs">
      <h4 className="font-semibold">{t("helix.context")}</h4>
      <div>
        <div className="text-muted-foreground">{t("helix.ctx.features")}</div>
        {features.length === 0 ? (
          <p>{t("helix.ctx.noFeature")}</p>
        ) : (
          <ul className="space-y-1">
            {features.map(({ feature: f, codon, place }) => (
              <li key={f.id}>
                <span className="font-medium">{featureLabel(f)}</span>
                {f.locus_tag && f.gene ? <span className="text-muted-foreground"> · {f.locus_tag}</span> : null}
                {` · ${f.type.toUpperCase()} · ${t("helix.ctx.strand", { s: f.strand })}`}
                {f.product && <span className="block text-muted-foreground">{f.product}</span>}
                {codon ? (
                  <span className="block">
                    {t("helix.ctx.codon", { codon: codon.codon, place: place ?? 0 })}
                    {codon.number != null ? ` · ${t("helix.ctx.codonNumber", { n: fmtInt(codon.number) })}` : ` · ${t("helix.ctx.fromEnd")}`}
                    {" · "}
                    <span className="font-medium">{aminoAcidText(t, codon.amino_acid)}</span>
                    {` · ${t("helix.ctx.table", { n: w.translation_table })}`}
                  </span>
                ) : (
                  f.type === "cds" || f.type === "sorf" ? <span className="block text-muted-foreground">{t(`helix.noCodon.${f.reading.reason ?? "edge"}` as TranslationKey)}</span> : null
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="text-muted-foreground">{t("helix.ctx.calls")}</div>
        {!amr.data?.run && !vfdb.data?.run && !Object.values(mobile.data?.runs ?? {}).some(Boolean) ? (
          <p>{t("helix.ctx.noRuns")}</p>
        ) : amrHits.length + vfHits.length + elements.length === 0 ? (
          <p>{t("helix.ctx.noCalls")}</p>
        ) : (
          <ul>
            {amrHits.map((h) => (
              <li key={h.id}>{t("helix.ctx.amr", { name: h.element_symbol, type: h.type })}</li>
            ))}
            {vfHits.map((h) => (
              <li key={h.id}>{t("helix.ctx.vfdb", { name: h.gene })}</li>
            ))}
            {elements.map((e) => (
              <li key={`${e.method}-${e.id}`}>{t("helix.ctx.mobile", { name: e.element ?? e.element_type ?? "?", category: t(categoryKey(e.category)) })}</li>
            ))}
          </ul>
        )}
        {call && <p>{t("helix.ctx.contigCall", { call: call.molecule_type ?? "?" })}</p>}
      </div>
      <div>
        <div className="text-muted-foreground">{t("helix.ctx.polishing")}</div>
        {!w.polishing.available ? (
          <p>{t(`helix.polishing.${w.polishing.reason ?? "not_polished"}` as TranslationKey)}</p>
        ) : changes.length === 0 ? (
          <p>{t("helix.polishing.unchanged", { polisher: w.polishing.source?.polisher ?? "?" })}</p>
        ) : (
          <ul>
            {changes.map((c, i) => (
              <li key={i}>
                {t(`helix.change.${c.kind}`)}
                {c.draft_bases != null && ` · ${t("helix.change.bases", { draft: c.draft_bases || "—", polished: c.polished_bases || "—" })}`}
                {c.reverse && ` · ${t("helix.change.reverse")}`}
                {` · ${t(w.polishing.source?.positions_in === "draft" ? "helix.change.inDraft" : "helix.change.inPolished", { polisher: w.polishing.source?.polisher ?? "?", record: w.polishing.source?.record === "dnadiff" ? "dnadiff" : "Pilon" })}`}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="text-muted-foreground">{t("helix.ctx.depth")}</div>
        {depth ? (
          <p>{t("helix.depth", { mean: depth.mean == null ? "—" : fmtNum(depth.mean, 1), start: fmtInt(depth.start), end: fmtInt(depth.end) })}</p>
        ) : (
          <p>{t(`explorer.coverage.${w.coverage.reason ?? "no_alignment"}` as TranslationKey)}</p>
        )}
      </div>
    </div>
  );
}

function aminoAcidText(t: ReturnType<typeof useT>, aa: string): string {
  if (aa === "X") return t("helix.aa.X");
  return isAminoAcid(aa) ? t(`helix.aa.${aa === "*" ? "stop" : aa}` as TranslationKey) : aa;
}
