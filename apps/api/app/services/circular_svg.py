"""A static circular genome map as inline SVG for the HTML report, from genome_explorer.genome_map.

The geometry is the web map's (apps/web/src/lib/circular.ts): angles in radians from 12 o'clock clockwise, sequences
in the annotator's order separated by small gaps, a feature across the origin drawn as two arcs at both ends of its
own sequence, neighbouring arcs closer than a pixel merged. Every text in the figure (sequence names, the caption) is
escaped, since names come from the assembler and annotator.
"""
from __future__ import annotations

import math
from html import escape
from typing import Any

TAU = 2 * math.pi
GENE_TYPES = {"cds", "sorf"}
RNA_TYPES = {"trna", "tmrna", "rrna", "ncrna"}
# The web map's light palette (apps/web/src/components/charts/theme.ts): validated categorical slots 1-3 for coding,
# RNA and other features, the diverging pair for GC skew, ink for GC content.
COLOURS = {"coding": "#2B54C4", "rna": "#eb6834", "element": "#008C82", "gap": "#64748B", "skew_pos": "#2B54C4",
           "skew_neg": "#e34948", "gc": "#0B132B", "coverage": "#2B54C4", "text": "#0B132B", "muted": "#64748B",
           "axis": "#CBD5E1", "grid": "#EEF2F7"}


def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _polar(cx: float, cy: float, r: float, a: float) -> tuple[float, float]:
    return cx + r * math.sin(a), cy - r * math.cos(a)


def _pt(p: tuple[float, float]) -> str:
    return f"{_n(p[0])},{_n(p[1])}"


def sector(cx: float, cy: float, r0: float, r1: float, a0: float, a1: float) -> str:
    """An annular sector (outer edge clockwise, inner edge back), or a whole ring for a full turn."""
    sweep = a1 - a0
    if sweep <= 0:
        return ""
    if sweep >= TAU - 1e-9:
        o = (_polar(cx, cy, r1, a0), _polar(cx, cy, r1, a0 + math.pi))
        i = (_polar(cx, cy, r0, a0), _polar(cx, cy, r0, a0 + math.pi))
        return (f"M{_pt(o[0])}A{_n(r1)},{_n(r1)} 0 0 1 {_pt(o[1])}A{_n(r1)},{_n(r1)} 0 0 1 {_pt(o[0])}Z"
                f"M{_pt(i[0])}A{_n(r0)},{_n(r0)} 0 0 0 {_pt(i[1])}A{_n(r0)},{_n(r0)} 0 0 0 {_pt(i[0])}Z")
    large = 1 if sweep > math.pi else 0
    return (f"M{_pt(_polar(cx, cy, r1, a0))}A{_n(r1)},{_n(r1)} 0 {large} 1 {_pt(_polar(cx, cy, r1, a1))}"
            f"L{_pt(_polar(cx, cy, r0, a1))}A{_n(r0)},{_n(r0)} 0 {large} 0 {_pt(_polar(cx, cy, r0, a0))}Z")


def layout(sequences: list[dict[str, Any]], gap: float = 0.02, max_gap_share: float = 0.1) -> tuple[list[dict], float]:
    n = len(sequences)
    total = sum(s["length"] for s in sequences)
    g = min(gap, max_gap_share * TAU / n) if n > 1 else 0.0
    per_base = (TAU - n * g) / total if total else 0.0
    a, segs = g / 2, []
    for s in sequences:
        segs.append({"id": s["contig"], "name": s["contig_in_assembly"], "length": s["length"], "a0": a,
                     "a1": a + s["length"] * per_base})
        a = segs[-1]["a1"] + g
    return segs, per_base


def feature_class(f: dict[str, Any]) -> str:
    if f["type"] in GENE_TYPES:
        return "hypothetical" if f["hypothetical"] else "coding"
    if f["type"] in RNA_TYPES:
        return "rna"
    return "gap" if f["type"] == "gap" else "element"


def arcs(features: list[dict[str, Any]], segs: list[dict], per_base: float) -> list[tuple[int, float, float, dict]]:
    index = {s["id"]: i for i, s in enumerate(segs)}
    out = []
    for f in features:
        i = index.get(f["contig"])
        if i is None:
            continue
        s = segs[i]
        spans = ([(f["start"] - 1, s["length"]), (0, f["end"])] if f["edge"] and f["start"] > f["end"]
                 else [(min(f["start"], f["end"]) - 1, max(f["start"], f["end"]))])
        out.extend((i, s["a0"] + lo * per_base, s["a0"] + hi * per_base, f) for lo, hi in spans)
    return out


def merge(pieces: list[tuple[int, float, float]], segs: list[dict], min_gap: float,
          min_width: float) -> list[tuple[float, float]]:
    widened = []
    for i, a0, a1 in pieces:
        if a1 - a0 < min_width:
            mid = (a0 + a1) / 2
            a0 = max(segs[i]["a0"], mid - min_width / 2)
            a1 = min(segs[i]["a1"], a0 + min_width)
        widened.append((i, a0, a1))
    widened.sort()
    out: list[list[float]] = []
    last = -1
    for i, a0, a1 in widened:
        if out and i == last and a0 - out[-1][1] <= min_gap:
            out[-1][1] = max(out[-1][1], a1)
        else:
            out.append([a0, a1])
        last = i
    return [(a, b) for a, b in out]


def nice125(x: float) -> int:
    if x <= 1:
        return 1
    m = 10 ** math.floor(math.log10(x))
    return next(int(k * m) for k in (1, 2, 5, 10) if k * m >= x)


def _position(pos: int, step: int) -> str:
    if step >= 1_000_000:
        return f"{pos / 1_000_000:g} Mb"
    if step >= 1_000:
        return f"{pos / 1_000:g} kb"
    return f"{pos:,}"


def _anchor(a: float) -> str:
    x = math.sin(a % TAU)
    return "middle" if abs(x) < 0.15 else "start" if x > 0 else "end"


def _bars(segs: list[dict], per_base: float, seq_index: int, starts: list[int], ends: list[int],
          values: list[float | None], baseline: float) -> list[tuple[float, float, float]]:
    s = segs[seq_index]
    return [(s["a0"] + (st - 1) * per_base, s["a0"] + en * per_base, v - baseline)
            for st, en, v in zip(starts, ends, values, strict=True) if v is not None]


def _bar_path(cx: float, cy: float, bars: list[tuple[float, float, float]], r_base: float, height: float,
              scale: float) -> tuple[str, str]:
    pos, neg = [], []
    for a0, a1, v in bars:
        h = max(-1.0, min(1.0, v / (scale or 1))) * height
        if h > 0:
            pos.append(sector(cx, cy, r_base, r_base + h, a0, a1))
        elif h < 0:
            neg.append(sector(cx, cy, r_base + h, r_base, a0, a1))
    return "".join(pos), "".join(neg)


def circular_map_svg(m: dict[str, Any], title: str, caption: str, synthetic: bool, size: int = 560,
                     width: int = 760) -> str:
    """The map as one <svg>: sequence ring, genes on strand + and strand -, coverage (when available), GC content and GC
    skew, with ticks, sequence names, a legend and the caption."""
    segs, per_base = layout(m["sequences"])
    cx, cy = width / 2, size / 2
    R = size / 2 - 58
    k = R / 300
    rings = [("backbone", 8), ("forward", 24), ("reverse", 24)]
    if m["coverage"]["available"]:
        rings.append(("coverage", 26))
    rings += [("gc", 30), ("skew", 30)]
    radii, r = {}, R
    for name, thick in rings:
        radii[name] = (r - thick * k, r)
        r -= (thick + 4) * k
    parts: list[str] = []
    for i, s in enumerate(segs):
        parts.append(f'<path d="{sector(cx, cy, *radii["backbone"], s["a0"], s["a1"])}" '
                     f'fill="{COLOURS["axis"] if i % 2 == 0 else COLOURS["grid"]}"><title>{escape(s["name"])} · '
                     f'{s["length"]:,} bp</title></path>')
    pieces = arcs(m["features"], segs, per_base)
    for ring, strand in (("backbone", None), ("forward", "+"), ("reverse", "-")):
        r0, r1 = radii[ring]
        mid = (r0 + r1) / 2
        for cls in ("coding", "hypothetical", "rna", "element", "gap"):
            chosen = [(i, a0, a1) for i, a0, a1, f in pieces if feature_class(f) == cls
                      and (f["strand"] == strand if strand else f["strand"] not in ("+", "-"))]
            if not chosen:
                continue
            d = "".join(sector(cx, cy, r0, r1, a0, a1) for a0, a1 in merge(chosen, segs, 0.6 / mid, 0.9 / mid))
            colour = COLOURS["coding" if cls == "hypothetical" else cls]
            opacity = ' fill-opacity="0.4"' if cls == "hypothetical" else ""
            parts.append(f'<path d="{d}" fill="{colour}"{opacity}/>')
    mean = m["gc"]["genome_gc"] or 0.0
    gc = [b for i, s in enumerate(m["sequences"])
          for b in _bars(segs, per_base, i, s["gc"]["start"], s["gc"]["end"], s["gc"]["gc"], mean)]
    skew = [b for i, s in enumerate(m["sequences"])
            for b in _bars(segs, per_base, i, s["gc"]["start"], s["gc"]["end"], s["gc"]["skew"], 0.0)]
    scales = {"gc": max([abs(b[2]) for b in gc] + [0.01]), "skew": max([abs(b[2]) for b in skew] + [0.05])}
    for name, bars, pos_colour, neg_colour, opacity in (("gc", gc, COLOURS["gc"], COLOURS["gc"], 0.7),
                                                         ("skew", skew, COLOURS["skew_pos"], COLOURS["skew_neg"], 0.9)):
        r0, r1 = radii[name]
        half = (r1 - r0) / 2
        pos, neg = _bar_path(cx, cy, bars, r0 + half, half, scales[name])
        parts.append(f'<path d="{pos}" fill="{pos_colour}" fill-opacity="{opacity}"/>'
                     f'<path d="{neg}" fill="{neg_colour}" fill-opacity="{opacity}"/>'
                     f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r0 + half)}" fill="none" stroke="{COLOURS["axis"]}" '
                     'stroke-width="0.75"/>')
    if "coverage" in radii:
        cov = [b for i, s in enumerate(m["sequences"]) if s["coverage"]["available"]
               for b in _bars(segs, per_base, i, s["coverage"]["start"], s["coverage"]["end"], s["coverage"]["mean"],
                              0.0)]
        scales["coverage"] = max([b[2] for b in cov] + [1.0])
        r0, r1 = radii["coverage"]
        pos, _ = _bar_path(cx, cy, cov, r0, r1 - r0, scales["coverage"])
        parts.append(f'<path d="{pos}" fill="{COLOURS["coverage"]}" fill-opacity="0.85"/>')
    for s in segs:
        x0, y0 = _polar(cx, cy, R - 10, s["a0"])
        x1, y1 = _polar(cx, cy, R + 8, s["a0"])
        parts.append(f'<line x1="{_n(x0)}" y1="{_n(y0)}" x2="{_n(x1)}" y2="{_n(y1)}" stroke="{COLOURS["text"]}" '
                     'stroke-width="1.25"/>')
        step = nice125(80 / max(per_base * R, 1e-12))
        for p in range(step, s["length"], step):
            a = s["a0"] + p * per_base
            ax, ay = _polar(cx, cy, R + 1, a)
            bx, by = _polar(cx, cy, R + 5, a)
            lx, ly = _polar(cx, cy, R + 15, a)
            parts.append(f'<line x1="{_n(ax)}" y1="{_n(ay)}" x2="{_n(bx)}" y2="{_n(by)}" stroke="{COLOURS["muted"]}"/>'
                         f'<text x="{_n(lx)}" y="{_n(ly + 3.5)}" font-size="9.5" text-anchor="{_anchor(a)}" '
                         f'fill="{COLOURS["muted"]}">{_position(p, step)}</text>')
        if len(segs) > 1 and (s["a1"] - s["a0"]) * R >= 48:
            mid = (s["a0"] + s["a1"]) / 2
            nx, ny = _polar(cx, cy, R + 34, mid)
            name = s["name"] if len(s["name"]) <= 24 else s["name"][:23] + "…"
            parts.append(f'<text x="{_n(nx)}" y="{_n(ny + 4)}" font-size="10.5" font-weight="600" '
                         f'text-anchor="{_anchor(mid)}" fill="{COLOURS["text"]}">{escape(name)}</text>')
    gc_text = f" · GC {100 * m['gc']['genome_gc']:.1f} %" if m["gc"]["genome_gc"] is not None else ""
    parts.append(f'<text x="{_n(cx)}" y="{_n(cy - 12)}" font-size="15" font-weight="600" text-anchor="middle" '
                 f'fill="{COLOURS["text"]}">{escape(title)}</text>'
                 f'<text x="{_n(cx)}" y="{_n(cy + 6)}" font-size="11" text-anchor="middle" fill="{COLOURS["muted"]}">'
                 f'{m["total_length"]:,} bp{gc_text}</text>'
                 f'<text x="{_n(cx)}" y="{_n(cy + 21)}" font-size="11" text-anchor="middle" fill="{COLOURS["muted"]}">'
                 f'{m["total"]:,} features</text>')
    legend = [
        ([COLOURS["axis"], COLOURS["grid"], COLOURS["gap"]], "Sequence ring; features without a strand (CRISPR arrays, "
                                                             "gaps) on it"),
        ([COLOURS["coding"], (COLOURS["coding"], 0.4), COLOURS["rna"], COLOURS["element"]],
         "Genes on strand + (outer) and − (inner): protein-coding, hypothetical (lighter), RNA gene, other element"),
    ]
    if "coverage" in radii:
        legend.append(([(COLOURS["coverage"], 0.85)], f"Read coverage: mean depth per window, 0 to "
                                                      f"{scales['coverage']:,.0f}x"))
    legend += [
        ([(COLOURS["gc"], 0.7)], f"GC content, {m['gc']['window']:,} bp windows: out above the mean "
                                 f"({100 * mean:.1f} %), in below; full height ±{100 * scales['gc']:.1f} points"),
        ([COLOURS["skew_pos"], COLOURS["skew_neg"]], f"GC skew (G − C) / (G + C): blue out where G > C, red in where "
                                                     f"C > G; full height ±{scales['skew']:.2f}"),
    ]
    top = size + 4
    for row, (swatches, text) in enumerate(legend):
        y = top + row * 17
        for j, sw in enumerate(swatches):
            colour, op = sw if isinstance(sw, tuple) else (sw, 1)
            parts.append(f'<rect x="{16 + j * 14}" y="{y}" width="11" height="11" rx="2" fill="{colour}" '
                         f'fill-opacity="{op}"/>')
        parts.append(f'<text x="{16 + len(swatches) * 14 + 6}" y="{y + 9.5}" font-size="11" fill="{COLOURS["text"]}">'
                     f'{escape(text)}</text>')
    y = top + len(legend) * 17 + 14
    parts.append(f'<text x="16" y="{y}" font-size="10" fill="{COLOURS["muted"]}">{escape(caption)}</text>')
    if synthetic:
        y += 17
        parts.append(f'<text x="16" y="{y}" font-size="10.5" font-weight="600" fill="{COLOURS["text"]}">SYNTHETIC test '
                     'data: these features describe the tools on test data, not biology.</text>')
    height = y + 12
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'aria-label="{escape(f"Circular map of {title}")}" font-family="Inter, Arial, sans-serif">'
            f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>' + "".join(parts) + "</svg>")
