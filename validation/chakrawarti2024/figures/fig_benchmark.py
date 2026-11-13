"""Benchmark figure: per-isolate agreement matrix and time per step. Reads data/per_isolate.tsv, writes fig/benchmark.html."""
import csv
import html
import sys

src, out = sys.argv[1], sys.argv[2]
with open(src) as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"
C_FLYE, C_MED, C_OTH = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
def st_state(call, truth):
    if call == truth: return "ok"
    return "wrong" if call.isdigit() else "none"
cols = [("MLST\nARVA", lambda r: st_state(r["arva_st"], r["sanger_st"])),
        ("MLST\nstudy, ONT only", lambda r: st_state(r["paper_ont_st"], r["sanger_st"])),
        ("spa\ntype", lambda r: "ok" if r["spa_arva"] == r["spa_ref"] else "wrong"),
        ("Penicillinase\ngene", lambda r: "ok" if (("blaZ" in r["amr_genes"] or "blaPC1" in r["amr_genes"]) == (r["pen"] == "R")) else "wrong"),
        ("mecA", lambda r: "ok" if ("mecA" not in r["amr_genes"].split(",")) == (r["oxa"] == "S" and r["fox"] == "S") else "wrong")]
X0, Y0, RH, CW, CS = 178, 96, 33, 106, 24
MX = X0 + len(cols) * CW + 40          # bars start
BW = 330; TMAX = 120
W, H = MX + BW + 60, Y0 + len(rows) * RH + 112
o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
     f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
def text(x, y, s, size=12, fill=INK, anchor="start", weight="normal", style=""):
    size = round(size * 1.27, 1)
    o.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" {style}>{html.escape(s)}</text>')
text(X0 - 166, 22, "A", 16, INK, weight="bold"); text(X0 - 118, 22, "Agreement with the study's reference results", 13, INK, weight="bold")
text(MX - 20, 22, "B", 16, INK, weight="bold"); text(MX, 22, "Run time per isolate (minutes)", 13, INK, weight="bold")
text(X0 - 166, Y0 - 12, "Isolate (Sanger ST)", 11, INK2)
for i, (name, _) in enumerate(cols):
    for j, part in enumerate(name.split("\n")):
        text(X0 + i * CW + CW / 2, Y0 - 34 + j * 17, part, 11, INK2 if j else INK, "middle", "bold" if j == 0 else "normal",
             'font-style="italic"' if part in ("spa", "mecA") else "")
# x axis for bars
for t in range(0, TMAX + 1, 30):
    x = MX + BW * t / TMAX
    o.append(f'<line x1="{x}" y1="{Y0 - 6}" x2="{x}" y2="{Y0 + len(rows) * RH}" stroke="{GRID if t else AXIS}" stroke-width="1"/>')
    text(x, Y0 - 12, str(t), 11, MUTED, "middle")
def cell(cx, cy, state):
    x, y = cx - CS / 2, cy - CS / 2
    if state == "ok":
        o.append(f'<rect x="{x}" y="{y}" width="{CS}" height="{CS}" rx="4" fill="{GOOD}"/>')
        o.append(f'<path d="M{cx-5.5} {cy+0.5} L{cx-1.5} {cy+4.5} L{cx+6} {cy-4.5}" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>')
    elif state == "none":
        o.append(f'<rect x="{x}" y="{y}" width="{CS}" height="{CS}" rx="4" fill="{WARN}"/>')
        o.append(f'<line x1="{cx-5}" y1="{cy}" x2="{cx+5}" y2="{cy}" stroke="{INK}" stroke-width="2.2" stroke-linecap="round"/>')
    else:
        o.append(f'<rect x="{x}" y="{y}" width="{CS}" height="{CS}" rx="4" fill="{CRIT}"/>')
        o.append(f'<path d="M{cx-4.5} {cy-4.5} L{cx+4.5} {cy+4.5} M{cx+4.5} {cy-4.5} L{cx-4.5} {cy+4.5}" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>')
for k, r in enumerate(rows):
    cy = Y0 + k * RH + RH / 2
    if k: o.append(f'<line x1="{X0 - 166}" y1="{Y0 + k * RH}" x2="{MX - 24}" y2="{Y0 + k * RH}" stroke="{GRID}" stroke-width="1"/>')
    text(X0 - 166, cy + 4, r["isolate"], 12, INK); text(X0 - 14, cy + 4, "ST" + r["sanger_st"], 11, INK2, "end")
    for i, (_, f) in enumerate(cols): cell(X0 + i * CW + CW / 2, cy, f(r))
    fl, me, tot = float(r["t_flye"]) / 60, float(r["t_medaka"]) / 60, float(r["wall_s"]) / 60
    segs = [(fl, C_FLYE), (me, C_MED), (max(tot - fl - me, 0), C_OTH)]
    x, bh = MX, 16
    for n, (v, c) in enumerate(segs):
        w = BW * v / TMAX
        ww = max(w - (2 if n < 2 else 0), 0.5)
        if n == 2:   # rounded data end only
            o.append(f'<path d="M{x} {cy-bh/2} h{max(ww-4,0)} a4 4 0 0 1 4 4 v{bh-8} a4 4 0 0 1 -4 4 h-{max(ww-4,0)} z" fill="{c}"/>')
        else:
            o.append(f'<rect x="{x}" y="{cy-bh/2}" width="{ww}" height="{bh}" fill="{c}"/>')
        x += w
    text(x + 6, cy + 4, f"{tot:.0f}", 11, INK2)
# legends
ly = Y0 + len(rows) * RH + 30
lx = X0 - 166
for state, label in (("ok", "agrees"), ("none", "no ST assigned"), ("wrong", "wrong ST")):
    cell(lx + CS / 2, ly, state); text(lx + CS + 8, ly + 4, label, 11, INK2); lx += CS + 8 + len(label) * 7.9 + 26
lx = MX
for c, label in ((C_FLYE, "Flye assembly"), (C_MED, "Medaka polishing"), (C_OTH, "other steps")):
    o.append(f'<rect x="{lx}" y="{ly-6}" width="12" height="12" rx="2" fill="{c}"/>'); text(lx + 18, ly + 4, label, 11, INK2); lx += 18 + len(label) * 7.2 + 16
def rich(x, y, parts):
    spans = "".join(f'<tspan font-style="italic">{html.escape(t[1:])}</tspan>' if t.startswith("*") else html.escape(t) for t in parts)
    o.append(f'<text x="{x}" y="{y}" font-size="13.3" fill="{MUTED}">{spans}</text>')
rich(X0 - 166, ly + 36, ["References: MLST, Sanger sequencing; ", "*spa", " type, the study's hybrid assembly; penicillinase gene (", "*blaZ", " or ", "*blaPC1", "),"])
rich(X0 - 166, ly + 54, ["penicillin phenotype; ", "*mecA", ", oxacillin and cefoxitin phenotypes."])
o.append("</svg>")
with open(out, "w") as f:
    f.write('<!doctype html><meta charset="utf-8"><title>Benchmark</title><body style="margin:0;background:#fff">' + "\n".join(o) + "</body>")
print(W, H)
