"""Figure 1: ARVA architecture and the path of one analysis (3 x 3 grid so that text stays >= 7 pt at 190 mm). Writes architecture.html."""
import html
import sys

out = sys.argv[1]
INK, INK2, MUTED, LINE, ACC, ACCBG = "#0b0b0b", "#3d3c39", "#6f6d68", "#b9b8ad", "#2a78d6", "#eef4fc"
BW, BH, GX, GY, X0, Y0 = 270, 136, 78, 52, 20, 20
W = X0 * 2 + 3 * BW + 2 * GX
def bx(c): return X0 + c * (BW + GX)
def by(r): return Y0 + r * (BH + GY)
H = by(3) + 196
o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
     f'<rect width="{W}" height="{H}" fill="#fff"/>',
     '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#3d3c39"/></marker></defs>']
def box(c, r, title, lines, n=None, accent=False):
    x, y = bx(c), by(r)
    o.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{BH}" rx="8" fill="{ACCBG if accent else "#fff"}" stroke="{ACC if accent else LINE}" stroke-width="{1.6 if accent else 1.2}"/>')
    tx = x + 14
    if n is not None:
        o.append(f'<circle cx="{x + 24}" cy="{y + 25}" r="12" fill="{ACC}"/><text x="{x + 24}" y="{y + 30}" font-size="14" fill="#fff" text-anchor="middle" font-weight="bold">{n}</text>')
        tx = x + 44
    o.append(f'<text x="{tx}" y="{y + 31}" font-size="16.5" font-weight="bold" fill="{INK}">{html.escape(title)}</text>')
    for i, ln in enumerate(lines):
        o.append(f'<text x="{x + 14}" y="{y + 60 + i * 21}" font-size="14.5" fill="{INK2}">{html.escape(ln)}</text>')
def line(pts, label=None, lx=0, ly=0, anchor="middle"):
    o.append(f'<polyline points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="none" stroke="{INK2}" stroke-width="1.6" marker-end="url(#ar)"/>')
    if label:
        o.append(f'<text x="{lx}" y="{ly}" font-size="12.5" fill="{MUTED}" text-anchor="{anchor}">{html.escape(label)}</text>')
box(0, 0, "Graphical interface", ["React; English or Spanish", "dialogs, results, reports,", "workflow editor"], n=1, accent=True)
box(1, 0, "API service", ["FastAPI on 127.0.0.1", "checks inputs, species", "evidence, memory, disk"], n=2, accent=True)
box(2, 0, "Job queue and worker", ["Redis / RQ", "cancellation and", "recovery of lost jobs"], n=3, accent=True)
box(2, 1, "Tool adapter", ["argument list, never a shell", "string; options checked;", "runs and parses the output"], n=4, accent=True)
box(1, 1, "Pinned tools", ["Bioconda lock files with", "SHA-256 per package; QUAST", "(PyPI); Debian utilities"])
box(0, 1, "Database manager", ["recognises each database;", "records version, checksums;", "downloads only when confirmed"])
box(1, 2, "Storage", ["originals read-only (SHA-256);", "outputs are new files linked", "to their inputs (lineage)"])
box(0, 2, "Reports", ["HTML, JSON, CSV; PDF for", "projects; methods text from", "the jobs that ran"])
my = by(0) + BH / 2
line([(bx(0) + BW, my), (bx(1) - 2, my)], "request", (bx(0) + BW + bx(1)) / 2, my - 8)
line([(bx(1) + BW, my), (bx(2) - 2, my)], "job", (bx(1) + BW + bx(2)) / 2, my - 8)
line([(bx(2) + BW / 2, by(0) + BH), (bx(2) + BW / 2, by(1) - 2)], "run", bx(2) + BW / 2 + 8, by(0) + BH + 30, "start")
my1 = by(1) + BH / 2
line([(bx(2), my1), (bx(1) + BW + 2, my1)])
line([(bx(0) + BW, my1), (bx(1) - 2, my1)], "database", (bx(0) + BW + bx(1)) / 2, my1 - 8)
line([(bx(1) + BW / 2, by(1) + BH), (bx(1) + BW / 2, by(2) - 2)], "outputs", bx(1) + BW / 2 + 8, by(1) + BH + 30, "start")
my2 = by(2) + BH / 2
line([(bx(1), my2), (bx(0) + BW + 2, my2)])
# provenance record
px, py, pw = X0, by(3) - 10, W - 2 * X0
o.append(f'<rect x="{px}" y="{py}" width="{pw}" height="186" rx="8" fill="#f7f7f4" stroke="{LINE}" stroke-width="1.2"/>')
o.append(f'<text x="{px + 16}" y="{py + 30}" font-size="16.5" font-weight="bold" fill="{INK}">Stored with every result (PostgreSQL)</text>')
cols = [["tool name, version and path", "exact command (argument lists)", "parameters as chosen", "threads, memory and priority"],
        ["input files (SHA-256 on record)", "contigs SHA-256 of assembly inputs", "parent job and lineage", "start, end and duration"],
        ["database name, kind and version", "how the version was known", "database checksum (full check)", "log, warnings and error code"]]
for c, items in enumerate(cols):
    for i, it in enumerate(items):
        x = px + 16 + c * (pw - 32) / 3; y = py + 62 + i * 30
        o.append(f'<circle cx="{x + 4}" cy="{y - 5}" r="3.5" fill="{ACC}"/><text x="{x + 15}" y="{y}" font-size="14.5" fill="{INK2}">{html.escape(it)}</text>')
sx = bx(2) + BW / 2
o.append(f'<polyline points="{sx},{by(1) + BH} {sx},{py - 2}" fill="none" stroke="{INK2}" stroke-width="1.6" marker-end="url(#ar)"/>')
o.append(f'<text x="{sx + 8}" y="{by(2) + BH / 2}" font-size="13" fill="{MUTED}">recorded by</text><text x="{sx + 8}" y="{by(2) + BH / 2 + 17}" font-size="13" fill="{MUTED}">the worker</text>')
o.append("</svg>")
with open(out, "w") as f:
    f.write('<!doctype html><meta charset="utf-8"><body style="margin:0">' + "\n".join(o) + "</body>")
print(W, H)
