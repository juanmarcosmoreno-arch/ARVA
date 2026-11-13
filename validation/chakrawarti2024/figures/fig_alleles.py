"""Figure: one-base homopolymer differences between Sanger and assembly alleles. Reads seqs.json (PubMLST), writes alleles.html."""
import html
import json
import sys

d = sys.argv[1]
with open(f"{d}/seqs.json") as f:
    seq = json.load(f)
def deletion(ref, alt, run_end):          # alt lacks one base of the run that ends at run_end (1-based, inclusive)
    assert ref[:run_end - 1] + ref[run_end:] == alt, "not a single deletion at the run end"
    return ref, alt[:run_end - 1] + "-" + alt[run_end - 1:]
def insertion(ref, alt, run_end):         # alt has one extra base after ref position run_end
    assert alt[:run_end] + alt[run_end + 1:] == ref, "not a single insertion at the run end"
    return ref[:run_end] + "-" + ref[run_end:], alt
panels = []
r, a = deletion(seq["arcC_3"], seq["arcC_90"], 429); panels.append(("arcC", "AC06-110, Medaka", "arcC 3 (Sanger ST398)", "arcC 90 (assembly)", r, a, 410, 448, 423, 429))
r, a = deletion(seq["arcC_1"], seq["arcC_484"], 429); panels.append(("arcC", "AC05-54, Racon only (pilot)", "arcC 1 (Sanger ST5957)", "arcC 484 (assembly)", r, a, 410, 448, 423, 429))
r, a = insertion(seq["aroE_35"], seq["aroE_1216"], 93); panels.append(("aroE", "AC06-110, Medaka", "aroE 35 (Sanger ST398)", "aroE 1216 (assembly)", r, a, 74, 112, 87, 94))
INK, INK2, MUTED, RUN, DIFF = "#0b0b0b", "#52514e", "#898781", "#e8f1fc", "#d03b3b"
CW, X0, W = 13.2, 200, 200 + 38 * 13.2 + 30
PH = 92; H = 30 + len(panels) * PH + 20
o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H}" viewBox="0 0 {W:.0f} {H}">', '<rect width="100%" height="100%" fill="#fff"/>']
def t(x, y, s, size=12, fill=INK, anchor="start", weight="normal", mono=False, italic=False):
    fam = "Courier New, Courier, monospace" if mono else "Helvetica, Arial, sans-serif"
    o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{" font-style=\"italic\"" if italic else ""}>{html.escape(s)}</text>')
for k, (locus, label, rname, aname, r, a, lo, hi, run_lo, run_hi) in enumerate(panels):
    y = 30 + k * PH
    t(16, y, "ABC"[k], 15, INK, weight="bold"); t(36, y, f"{label}", 12.5, INK, weight="bold")
    # run highlight (alignment coordinates are 1-based in reference numbering; gaps shift nothing before the run)
    x_run = X0 + (run_lo - 1 - lo) * CW
    o.append(f'<rect x="{x_run - 1:.1f}" y="{y + 9}" width="{(run_hi - run_lo + 1) * CW + 2:.1f}" height="44" rx="3" fill="{RUN}"/>')
    for row, (name, s) in enumerate(((rname, r), (aname, a))):
        yy = y + 26 + row * 22
        locus_name, rest = name.split(" ", 1)
        o.append(f'<text x="36" y="{yy:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="11.5" fill="{INK2}"><tspan font-style="italic">{html.escape(locus_name)}</tspan> {html.escape(rest)}</text>')
        for i in range(lo, hi):
            c = s[i]; other = (a if row == 0 else r)[i]
            col = DIFF if c != other else INK
            t(X0 + (i - lo) * CW + CW / 2, yy, c, 13, col, "middle", "bold" if c != other else "normal", mono=True)
    t(X0, y + 70, f"position {lo + 1}", 10, MUTED); t(X0 + (hi - lo) * CW, y + 70, f"{hi}", 10, MUTED, "end")
o.append("</svg>")
with open(f"{d}/alleles.html", "w") as f:
    f.write('<!doctype html><meta charset="utf-8"><body style="margin:0">' + "\n".join(o) + "</body>")
print("ok", W, H)
