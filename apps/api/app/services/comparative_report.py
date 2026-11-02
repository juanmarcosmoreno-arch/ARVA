"""The comparative report of a comparison set (HTML / JSON), built only from stored results, and the comparative
section of a sample's report (the sets that include one of its assemblies)."""
from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__ as ARVA_VERSION
from app.models import (
    AnalysisJob,
    Assembly,
    ComparisonMember,
    ComparisonResult,
    ComparisonSet,
    Project,
    Sample,
)
from app.services import comparative as svc
from app.services.pangenome import data as pangenome_data
from app.services.phylogeny_report import tree_section

DIFFERENCES_SHOWN = 200
METHOD_NAMES = {"skani": "skani triangle", "fastani": "FastANI all-vs-all", "minimap2": "minimap2",
                "nucmer": "MUMmer NUCmer + show-coords", "blast": "BLAST+ (blastp / blastn)", "blastn": "BLAST+ blastn",
                "tblastn": "BLAST+ tblastn", "panaroo": "Panaroo", "ppanggolin": "PPanGGOLiN",
                "iqtree": "IQ-TREE", "fasttree": "FastTree", "nj": "neighbour joining (ARVA, distance tree)"}
ANALYSIS_TITLES = {"ani": "ANI matrix", "alignment": "Whole-genome alignment", "region": "Genome Region Explorer",
                   "gene": "Custom gene investigation", "pangenome": "Pangenome", "phylogeny": "Phylogeny"}
# Colour-blind-safe categorical palette (Okabe-Ito order, then Tol's muted) for homology groups in the figure.
GROUP_COLORS = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#332288", "#88CCEE",
                "#44AA99", "#117733", "#999933", "#DDCC77", "#AA4499", "#882255")
CATEGORY_LABELS = {"insertion": "inserted sequence (absent from the other genome)", "inversion": "inversion",
                   "relocation": "relocation", "translocation": "translocation (to another sequence)"}
METHODS_TEXT = [
    "ANI: skani triangle (sparse rows, -E) compares every pair once and reports the pairs above its screening and "
    "aligned-fraction cut-offs (-s, --min-af); FastANI all-vs-all (--ql/--rl) reports each ordered pair, so A "
    "against B and B against A can differ. Pairs a tool did not report are left empty, never estimated.",
    "Heatmap order: average-linkage (UPGMA) clustering of 100 - ANI computed by ARVA (arva_core.comparative); for "
    "the order only, an unreported pair counts as distance 100 and two directions are averaged. It is similarity "
    "clustering, not a phylogeny.",
    "Alignment: the first genome of the chosen order is the reference; each other genome is aligned to it, and each "
    "genome to the next one, with minimap2 (-x asm5/asm10/asm20 by expected divergence, -c for base-level "
    "alignments; identity = matching bases / alignment block length) or NUCmer (show-coords -rclTH, no filter).",
    "Conservation along the reference (ARVA): per window, the share of reference bases covered by a primary "
    "alignment block, and the mean, over those bases, of the highest identity of a block covering each base.",
    "Structural differences: dnadiff (NUCmer --maxmatch, delta-filter, show-diff) of each genome against the "
    "reference; its report's counts and the show-diff rows (GAP, DUP, BRK, JMP, INV, SEQ) with coordinates, "
    "classified as dnadiff's own report does.",
    "Region Explorer: the homologue of the chosen gene in each genome is the best blastp hit among that genome's "
    "annotated proteins (identity and coverage of both proteins above the thresholds shown) or, for coordinates or "
    "unannotated genomes, the best blastn match of the gene's nucleotides; a window of the chosen size on each side "
    "is drawn with the gene pointing right. Gene colours are single-linkage groups of all-against-all blastp hits "
    "above the stated identity and coverage; bands between tracks are blastn HSPs between the window sequences.",
    "Custom gene investigation: blastn (nucleotide query) or tblastn (protein query, genetic code 11) against each "
    "genome's contigs; HSPs chained into matches by ARVA's rules (complete, partial, split) with the thresholds "
    "shown; mobile elements within the stated distance from the genome's latest mobile-element runs; optional "
    "MAFFT alignment of the matched sequences and an IQ-TREE or FastTree gene tree.",
    "Pangenome: Panaroo (or PPanGGOLiN) clusters the genes of each genome's own annotation (GFF3 with the sequence) "
    "into gene families, with every option recorded. ARVA classifies each family by the share of genomes holding it "
    "with the stated thresholds (core, soft core, shell, cloud), draws accumulation curves over random genome orders "
    "(number of orders and seed stated; pan = families in at least one of the first k genomes, core = in all of "
    "them) and orders genomes for the heatmap by average-linkage clustering of the Jaccard distance between their "
    "family sets (arva_core.pangenome).",
    "Phylogeny: IQ-TREE (ModelFinder by BIC or a stated model; UFBoot and/or SH-aLRT supports) or FastTree (GTR, "
    "Gamma, SH-like supports) on Panaroo's core-genome alignment, its SNPs (SNP-sites; constant sites added back with "
    "-fconst or corrected with +ASC) or one gene's alignment; or neighbour joining computed by ARVA on p, "
    "Jukes-Cantor or 1 - ANI/100 distances (a distance tree). Trees are inferred unrooted; the drawing's root "
    "(midpoint or outgroup) is a display choice (arva_core.phylo).",
]
LIMITATIONS = [
    "ANI and alignment identity measure similarity. They do not establish ancestry, direction of change or "
    "horizontal transfer; shared or missing regions may also reflect assembly gaps, collapsed repeats or "
    "misassemblies.",
    "The heatmap ordering is not a phylogeny. A tree for evolutionary inference needs a phylogenetic method on an "
    "alignment (core genome or SNPs) with a substitution model.",
    "Structural differences are the aligner's classification of alignment breaks. Repeats (IS elements, rRNA "
    "operons) produce breaks that are not rearrangements, and fragmented assemblies produce breaks at contig "
    "ends.",
    "Results describe the assemblies as given; they are not more accurate than those assemblies.",
    "A gene found in several genomes, a shared neighbourhood or a nearby mobile element does not by itself show "
    "horizontal transfer; common descent and assembly artefacts produce the same patterns. A gene tree describes "
    "the gene's history, which may differ from the genomes' history; its root is not inferred.",
    "Pangenome families are only as good as the annotations: genomes annotated differently, fragmented assemblies "
    "and contamination add accessory families. Categories depend on the genomes chosen; with few genomes they are "
    "coarse. The genome clustering of gene content is not a phylogeny, and associations with metadata are "
    "exploratory (related genomes are not independent).",
    "A phylogeny summarises the aligned sequences' history under the method's assumptions; recombination and "
    "horizontal transfer can make one tree a poor summary. Supports are not probabilities of correctness, the root "
    "is a drawing choice, and a tree from ANI is a similarity dendrogram, not a phylogeny.",
]


def _when(v: Any) -> str | None:
    return v.isoformat(timespec="seconds") if v is not None else None


def comparative_report_json(db: Session, cset: ComparisonSet) -> dict[str, Any]:
    view = svc.set_view(db, cset)
    results = db.scalars(select(ComparisonResult).where(ComparisonResult.set_id == cset.id)
                         .order_by(ComparisonResult.created_at)).all()
    out = []
    for r in results:
        job = db.get(AnalysisJob, r.job_id)
        out.append({**svc.result_brief(r), "parameters": r.parameters, "genomes": r.genomes, "summary": r.summary,
                    "files": r.files, "commands": (job.commands if job else None) or [],
                    "job": {"id": r.job_id, "finished_at": _when(job.finished_at) if job else None,
                            "duration_seconds": job.duration_seconds if job else None,
                            "resources": job.resources if job else None}})
    return {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "arva_version": ARVA_VERSION,
            "set": {k: view[k] for k in ("id", "name", "description", "project_id", "project_name")},
            "members": view["members"], "results": out, "methods": METHODS_TEXT, "limitations": LIMITATIONS}


def _num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}" if isinstance(v, float) else f"{v:,}"


def _pct(v: Any) -> str:
    return "—" if v is None else f"{v * 100:.2f} %"


def _ani_color(v: float | None, low: float) -> str:
    if v is None:
        return "#E5E7EB"
    t = max(0.0, min(1.0, (v - low) / (100 - low))) if low < 100 else 1.0
    r, g, b = (round(a + (c - a) * t) for a, c in zip((239, 246, 255), (31, 59, 138), strict=True))
    return f"rgb({r},{g},{b})"


def _heatmap_svg(labels: list[str], ani: list[list[float | None]], order: list[int]) -> str:
    n = len(labels)
    cell, pad = 34 if n <= 12 else 16, 150
    size = pad + cell * n + 10
    values = [v for row in ani for v in row if v is not None and v < 100]
    low = min(values) if values else 95.0
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" '
             f'role="img" aria-label="ANI heatmap">']
    for col, j in enumerate(order):
        parts.append(f'<text x="{pad + col * cell + cell / 2}" y="{pad - 6}" font-size="10" '
                     f'transform="rotate(-45 {pad + col * cell + cell / 2} {pad - 6})">{escape(labels[j][:24])}</text>')
    for row, i in enumerate(order):
        y = pad + row * cell
        parts.append(f'<text x="{pad - 6}" y="{y + cell / 2 + 3}" font-size="10" text-anchor="end">'
                     f'{escape(labels[i][:24])}</text>')
        for col, j in enumerate(order):
            v = ani[i][j]
            parts.append(f'<rect x="{pad + col * cell}" y="{y}" width="{cell - 1}" height="{cell - 1}" '
                         f'fill="{_ani_color(v, low)}"><title>{escape(labels[i])} vs {escape(labels[j])}: '
                         f'{"not reported" if v is None else f"{v:.2f} %"}</title></rect>')
            if n <= 12 and v is not None:
                fill = "#fff" if (v - low) / max(100 - low, 1e-9) > 0.55 else "#0B132B"
                parts.append(f'<text x="{pad + col * cell + cell / 2}" y="{y + cell / 2 + 3}" font-size="8" '
                             f'text-anchor="middle" fill="{fill}">{v:.1f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _conservation_svg(cons: dict[str, Any]) -> str:
    rows = cons["genomes"]
    if not rows:
        return ""
    n = max(len(r["windows"]) for r in rows)
    width, label, h = 760, 150, 14
    step = (width - label) / max(n, 1)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {len(rows) * (h + 6) + 4}" '
             f'width="{width}" role="img" aria-label="Conservation along the reference">']
    for k, r in enumerate(rows):
        y = k * (h + 6) + 2
        parts.append(f'<text x="{label - 6}" y="{y + h - 3}" font-size="10" text-anchor="end">'
                     f'{escape(r["label"][:24])}</text>')
        for i, w in enumerate(r["windows"]):
            share = w["covered"]
            fill = "#E5E7EB" if not share else f"rgba(0,180,166,{0.15 + 0.85 * share:.2f})"
            parts.append(f'<rect x="{label + i * step:.2f}" y="{y}" width="{step + 0.3:.2f}" height="{h}" '
                         f'fill="{fill}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _ani_html(r: dict[str, Any]) -> str:
    labels = [g["label"] for g in r["genomes"]]
    m, order = r["summary"]["matrix"], r["summary"]["order"]["order"]
    rows = []
    for i, a in enumerate(labels):
        for j in range(i + 1, len(labels)):
            b = labels[j]
            rows.append(f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{_num(m['ani'][i][j])}</td>"
                        f"<td>{_pct(m['af'][i][j])}</td><td>{_num(m['ani'][j][i]) if m['directional'] else '='}</td>"
                        f"<td>{_pct(m['af'][j][i])}</td></tr>")
    return (f"<figure class='map'>{_heatmap_svg(labels, m['ani'], order)}</figure>"
            f"<p class='muted'>{escape(svc.SIMILARITY_NOTE)} Grey cells: pair not reported by the tool.</p>"
            "<table class='grid'><tr><th>Genome A</th><th>Genome B</th><th>ANI A vs B (%)</th><th>Aligned share of "
            "A</th><th>ANI B vs A (%)</th><th>Aligned share of B</th></tr>" + "".join(rows) + "</table>")


def _alignment_html(r: dict[str, Any], data: dict[str, Any] | None) -> str:
    s = r["summary"]
    pairs = "".join(
        f"<tr><td>{escape(p['reference'])}</td><td>{escape(p['query'])}</td><td>{escape(p['role'])}</td>"
        f"<td>{p['blocks']:,} ({p['forward']:,} + / {p['reverse']:,} −)</td><td>{_pct(p['ref_fraction'])}</td>"
        f"<td>{_pct(p['query_fraction'])}</td><td>{_num(p['identity'], 3)}</td></tr>" for p in s["pairs"])
    out = ("<table class='grid'><tr><th>Reference</th><th>Query</th><th>Pair</th><th>Primary blocks</th>"
           "<th>Reference aligned</th><th>Query aligned</th><th>Identity (%)</th></tr>" + pairs + "</table>")
    if data is not None:
        out += (f"<h4>Conservation along {escape(s['reference'])} (windows of {s['window']:,} bp)</h4>"
                f"<figure class='map'>{_conservation_svg(data['conservation'])}</figure>"
                "<p class='muted'>Shade: share of each window covered by an alignment block (grey: none).</p>")
    for d in s.get("dnadiff") or []:
        rep = d["report"]
        keys = (("inversions", "Inversions"), ("relocations", "Relocations"), ("translocations", "Translocations"),
                ("inserted_regions", "Insertions (regions)"), ("inserted_region_bases", "Inserted bases"),
                ("breakpoints", "Breakpoints"), ("substituted_bases", "SNPs (1-to-1 alignments)"),
                ("indel_bases", "Indel bases (1-to-1 alignments)"))
        counts = "".join(f"<tr><th>{label}</th><td>{_num(rep['reference'].get(k))}</td>"
                         f"<td>{_num(rep['query'].get(k))}</td></tr>" for k, label in keys)
        diffs = [(d["reference"], x) for x in d["reference_differences"] if x["category"]] + \
                [(d["query"], x) for x in d["query_differences"] if x["category"]]
        rows = "".join(f"<tr><td>{escape(on)}</td><td>{escape(x['sequence'])}</td><td>{escape(x['type'])}</td>"
                       f"<td>{escape(CATEGORY_LABELS[x['category']])}</td><td>{x['start']:,}</td><td>{x['end']:,}</td>"
                       f"<td>{x['length']:,}</td></tr>" for on, x in diffs[:DIFFERENCES_SHOWN])
        more = (f"<p class='muted'>{len(diffs) - DIFFERENCES_SHOWN:,} more rows in the differences CSV.</p>"
                if len(diffs) > DIFFERENCES_SHOWN else "")
        out += (f"<h4>dnadiff: {escape(d['reference'])} (reference) vs {escape(d['query'])}</h4>"
                f"<table class='grid'><tr><th></th><th>{escape(d['reference'])}</th><th>{escape(d['query'])}</th></tr>"
                f"{counts}</table><table class='grid'><tr><th>Located on</th><th>Sequence</th><th>show-diff type</th>"
                f"<th>Reading (dnadiff)</th><th>Start</th><th>End</th><th>Length</th></tr>{rows}</table>{more}")
    return out


def _region_svg(data: dict[str, Any]) -> str:
    """A gggenes-style neighbourhood figure: one row per genome, genes as arrows coloured by homology group, the
    gene of interest outlined, grey bands for blastn links between neighbouring rows."""
    drawn = [t for t in data["tracks"] if t["located_by"] != "not_found"]
    if not drawn:
        return ""
    lo = min(t["start"] - t["anchor_start"] if not t["flipped"] else t["anchor_end"] - t["end"] for t in drawn)
    hi = max(t["end"] - t["anchor_start"] if not t["flipped"] else t["anchor_end"] - t["start"] for t in drawn)
    left, width, row, h = 170, 720, 70, 16
    scale = width / max(1, hi - lo)

    def x(v: float) -> float:
        return round(left + (v - lo) * scale, 1)

    parts = []
    for block in data.get("links") or []:
        y1, y2 = 30 + block["upper"] * row + h / 2, 30 + block["lower"] * row - h / 2
        for k in block["links"][:300]:
            parts.append(f"<polygon points='{x(k['upper_start'])},{y1} {x(k['upper_end'])},{y1} "
                         f"{x(k['lower_end'] if not k['inverted'] else k['lower_start'])},{y2} "
                         f"{x(k['lower_start'] if not k['inverted'] else k['lower_end'])},{y2}' fill='#94A3B8' "
                         f"fill-opacity='{0.15 + 0.5 * max(0, (k['identity'] - 70) / 30):.2f}'/>")
    for i, t in enumerate(drawn):
        y = 30 + i * row
        a = t["start"] - t["anchor_start"] if not t["flipped"] else t["anchor_end"] - t["end"]
        b = t["end"] - t["anchor_start"] if not t["flipped"] else t["anchor_end"] - t["start"]
        parts.append(f"<text x='{left - 8}' y='{y + 4}' text-anchor='end' font-size='11'>{escape(t['label'][:28])}"
                     f"</text><line x1='{x(a)}' x2='{x(b)}' y1='{y}' y2='{y}' stroke='#64748B'/>")
        for f in t["features"]:
            s0, s1 = x(f["rel_start"]), x(f["rel_end"])
            head = min(8.0, (s1 - s0) * 0.5)
            color = GROUP_COLORS[f["group"] % len(GROUP_COLORS)] if f.get("group") is not None and f["type"] in (
                "cds", "sorf") else "#CBD5E1"
            if f["rel_strand"] == "-":
                pts = f"{s1},{y - h / 2} {s0 + head},{y - h / 2} {s0},{y} {s0 + head},{y + h / 2} {s1},{y + h / 2}"
            else:
                pts = f"{s0},{y - h / 2} {s1 - head},{y - h / 2} {s1},{y} {s1 - head},{y + h / 2} {s0},{y + h / 2}"
            anchor = f["id"] == t.get("anchor_feature_id")
            parts.append(f"<polygon points='{pts}' fill='{color}' stroke='{'#0B132B' if anchor else '#334155'}' "
                         f"stroke-width='{2 if anchor else 0.6}'><title>{escape(f.get('gene') or f.get('locus_tag') or '')}"
                         f" {escape(f.get('product') or '')}</title></polygon>")
            if f.get("gene") and s1 - s0 > 24:
                parts.append(f"<text x='{(s0 + s1) / 2}' y='{y - h / 2 - 3}' text-anchor='middle' font-size='9' "
                             f"font-style='italic'>{escape(f['gene'][:12])}</text>")
            if f.get("marks"):
                parts.append(f"<circle cx='{(s0 + s1) / 2}' cy='{y + h / 2 + 5}' r='3' fill='#B91C1C'/>")
    height = 30 + len(drawn) * row
    ticks = "".join(f"<line x1='{x(v)}' x2='{x(v)}' y1='{height - 22}' y2='{height - 17}' stroke='#64748B'/>"
                    f"<text x='{x(v)}' y='{height - 6}' text-anchor='middle' font-size='9'>{v / 1000:g} kb</text>"
                    for v in range(int(lo // 5000 * 5000), int(hi) + 1, 5000) if lo <= v <= hi)
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {left + width + 20} {height}' width='100%' "
            f"font-family='Helvetica, Arial, sans-serif'>{''.join(parts)}{ticks}</svg>")


def _window(t: dict[str, Any]) -> str:
    return f"{t['contig']}:{t['start']:,}-{t['end']:,}" if t.get("contig") else ""


def _mobile(m: dict[str, Any]) -> str:
    return "; ".join(f"{e['element']} ({e['distance']:,} bp)" for e in m.get("mobile") or [])


def _region_html(r: dict[str, Any], data: dict[str, Any] | None) -> str:
    s = r["summary"]
    a = s["anchor"]
    what = a.get("gene") or a.get("locus_tag") or f"{a['contig']}:{a['start']:,}-{a['end']:,}"
    rows = "".join(
        f"<tr><td>{escape(t['label'])}</td><td>{escape(t['located_by'])}</td>"
        f"<td>{_num((t.get('hit') or {}).get('identity'))}</td>"
        f"<td>{_num((t.get('hit') or {}).get('query_coverage'))}</td><td>{t['copies'] or ''}</td>"
        f"<td>{escape(_window(t))}</td><td>{'yes' if t.get('flipped') else ''}</td></tr>" for t in s["tracks"])
    out = (f"<p>Gene of interest: <strong>{escape(what)}</strong> {escape(a.get('product') or '')} in "
           f"{escape(s['reference'])}; {s['flank']:,} bp on each side; {s['groups']} homology groups, "
           f"{s['links']} links.</p><table class='grid'><tr><th>Genome</th><th>Found by</th><th>Identity (%)</th>"
           f"<th>Coverage (%)</th><th>Copies</th><th>Window</th><th>Reversed</th></tr>{rows}</table>")
    if data is not None:
        out += (f"<figure class='map'>{_region_svg(data)}</figure><p class='muted'>Arrows: genes by strand and size, "
                "coloured by homology group (shared blastp similarity above the thresholds, not orthology); bold "
                "outline: the gene of interest; red dot: AMR, virulence or mobile-element call; grey bands: blastn "
                "identity between neighbouring windows.</p>")
    return out


def _gene_html(r: dict[str, Any], data: dict[str, Any] | None) -> str:
    s = r["summary"]
    q = s["query"]
    rows = "".join(f"<tr><td>{escape(g['label'])}</td><td>{g['matches']}</td><td>{g['complete']}</td>"
                   f"<td>{g['partial']}</td><td>{g['split']}</td><td>{_num(g['best_identity'])}</td>"
                   f"<td>{_num(g['best_coverage'])}</td><td>{g['near_mobile']}</td></tr>" for g in s["genomes"])
    out = (f"<p>Query <strong>{escape(q['name'])}</strong> ({escape(q['molecule'])}, {q['length']:,} "
           f"{'bp' if q['molecule'] == 'nucleotide' else 'aa'}, SHA-256 <code>{escape(q['sha256'])}</code>), "
           f"searched with {escape(s['program'])} -task {escape(s['task'])}.</p>"
           "<table class='grid'><tr><th>Genome</th><th>Matches</th><th>Complete</th><th>Partial</th><th>Split</th>"
           f"<th>Best identity (%)</th><th>Best coverage (%)</th><th>Near a mobile element</th></tr>{rows}</table>")
    if data is not None:
        hits = "".join(
            f"<tr><td>{escape(g['label'])}</td><td>{m['copy']}</td><td>{escape(m['kind'])}</td>"
            f"<td>{escape(m['contig'])}:{m['start']:,}-{m['end']:,} ({m['strand']})</td><td>{_num(m['identity'])}</td>"
            f"<td>{_num(m['query_coverage'])}</td><td>{escape((m.get('feature') or {}).get('locus_tag') or '')}</td>"
            f"<td>{escape(_mobile(m))}</td></tr>"
            for g in data["genomes"] for m in g["matches"])
        out += ("<table class='grid'><tr><th>Genome</th><th>Copy</th><th>Kind</th><th>Location</th><th>Identity (%)"
                "</th><th>Coverage (%)</th><th>Annotated gene</th><th>Mobile elements nearby</th></tr>" + hits +
                "</table>")
    if (al := s.get("alignment")) and al.get("status") == "aligned":
        out += f"<p class='muted'>MAFFT {escape(al['mafft_version'])} ({escape(al['strategy'])}): {al['columns']:,} columns.</p>"
    if (tr := s.get("tree")) and tr.get("status") == "built":
        out += (f"<p class='muted'>Gene tree: {escape(tr['method'])} {escape(tr['tool_version'])}, model "
                f"{escape(str(tr.get('model')))}, supports {escape(tr['support'])}; unrooted.</p>")
        if data is not None and data.get("tree"):
            out += f"<pre>{escape(data['tree']['newick'])}</pre>"
    return out


def _curve_svg(curves: dict[str, Any]) -> str:
    k = curves["k"]
    top = max(curves["pan"]["max"]) or 1
    w, h, left, bottom = 520, 220, 50, 30

    def x(v: int) -> float:
        return left + (v - 1) / max(1, len(k) - 1) * (w - left - 10)

    def y(v: float) -> float:
        return h - bottom - v / top * (h - bottom - 10)

    parts = []
    for key, color in (("pan", "#0072B2"), ("core", "#D55E00")):
        st = curves[key]
        band = " ".join(f"{x(a):.1f},{y(b):.1f}" for a, b in zip(k, st["max"], strict=True))
        band += " " + " ".join(f"{x(a):.1f},{y(b):.1f}" for a, b in reversed(list(zip(k, st["min"], strict=True))))
        line = " ".join(f"{x(a):.1f},{y(b):.1f}" for a, b in zip(k, st["mean"], strict=True))
        parts.append(f"<polygon points='{band}' fill='{color}' fill-opacity='0.15'/>"
                     f"<polyline points='{line}' fill='none' stroke='{color}' stroke-width='2'/>"
                     f"<text x='{x(k[-1]) - 4:.1f}' y='{y(st['mean'][-1]) - 6:.1f}' text-anchor='end' font-size='11' "
                     f"fill='{color}'>{key} {st['mean'][-1]:,.0f}</text>")
    axes = (f"<line x1='{left}' y1='{h - bottom}' x2='{w - 10}' y2='{h - bottom}' stroke='#94A3B8'/>"
            f"<line x1='{left}' y1='10' x2='{left}' y2='{h - bottom}' stroke='#94A3B8'/>"
            f"<text x='{left}' y='{h - 8}' font-size='11' fill='#475569'>1</text>"
            f"<text x='{w - 10}' y='{h - 8}' font-size='11' text-anchor='end' fill='#475569'>{k[-1]} genomes</text>"
            f"<text x='{left - 4}' y='16' font-size='11' text-anchor='end' fill='#475569'>{top:,}</text>")
    return f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' role='img'>{axes}{''.join(parts)}</svg>"


def _pangenome_html(r: dict[str, Any], data: dict[str, Any] | None) -> str:
    s = r["summary"]
    t, cc = s["thresholds"], s["category_counts"]
    rows = "".join(f"<tr><td>{label}</td><td>{escape(rng)}</td><td>{cc[key]:,}</td></tr>" for key, label, rng in (
        ("core", "Core", f">= {t['core']:.0%} of genomes"),
        ("soft_core", "Soft core", f">= {t['soft_core']:.0%} and < {t['core']:.0%}"),
        ("shell", "Shell", f">= {t['shell']:.0%} and < {t['soft_core']:.0%}"),
        ("cloud", "Cloud", f"< {t['shell']:.0%}")))
    out = (f"<p>{s['families']:,} gene families in {s['genomes']} genomes.</p><table class='grid'><tr><th>Category"
           f"</th><th>Genomes holding the family</th><th>Families</th></tr>{rows}</table>")
    if own := s.get("tool_summary"):
        out += (f"<p class='muted'>Panaroo's own summary_statistics.txt (99 / 95 / 15 %): core {own['core']:,}, soft "
                f"core {own['soft_core']:,}, shell {own['shell']:,}, cloud {own['cloud']:,}, total {own['total']:,}."
                "</p>")
    if parts := s.get("partitions"):
        out += (f"<p class='muted'>PPanGGOLiN's partitions: persistent {parts['persistent']:,}, shell "
                f"{parts['shell']:,}, cloud {parts['cloud']:,}.</p>")
    cons = s.get("annotation_consistency") or {}
    ann = "; ".join(f"{a['annotator']}: {', '.join(a['genomes'])}" for a in cons.get("annotators") or [])
    out += (f"<p class='muted'>Annotations: {escape(ann)}"
            + ("" if cons.get("consistent", True) else " — the genomes were annotated differently; part of the "
               "accessory genome may reflect annotation, not biology.") + "</p>")
    per = "".join(f"<tr><td>{escape(g['label'])}</td><td>{g['families']:,}</td><td>{g['unique']:,}</td></tr>"
                  for g in s.get("per_genome") or [])
    out += ("<table class='grid'><tr><th>Genome</th><th>Families</th><th>Found only in this genome</th></tr>"
            f"{per}</table>")
    if data is not None:
        dist = "".join(f"<td>{d['families']:,}</td>" for d in data["distribution"])
        head = "".join(f"<th>{d['genomes']}</th>" for d in data["distribution"])
        c = data["curves"]
        out += (f"<h4>Families by number of genomes</h4><table class='grid'><tr><th>Genomes</th>{head}</tr>"
                f"<tr><td>Families</td>{dist}</tr></table><h4>Accumulation curves</h4>"
                f"<figure class='map'>{_curve_svg(c)}</figure><p class='muted'>Mean over {c['permutations']} random "
                f"genome orders (seed {c['seed']}); bands: minimum to maximum. Core here means present in all of "
                "the first k genomes.</p>")
    return out


def _provenance(r: dict[str, Any]) -> str:
    cmds = "".join(f"<pre>{escape(shlex.join(c))}</pre>" for c in r["commands"])
    warnings = "".join(f"<li><code>{escape(w['code'])}</code> {escape(json.dumps(w['params']))}</li>"
                       for w in r["warnings"])
    return (f"<p class='muted'>{escape(r['tool'])} {escape(r['tool_version'])} · job <code>{escape(r['job_id'])}"
            f"</code> · finished {escape(r['job']['finished_at'] or '')}</p>"
            f"<p class='muted'>Settings: <code>{escape(json.dumps(r['parameters'], sort_keys=True))}</code></p>"
            + (f"<div class='warn'><strong>Notes</strong><ul>{warnings}</ul></div>" if warnings else "") + cmds)


def comparative_report_html(db: Session, cset: ComparisonSet, lang: str = "en") -> str:
    data = comparative_report_json(db, cset)
    members = "".join(
        f"<tr><td>{escape(m['label'])}</td><td>{escape(m['sample_code'] or '')}</td>"
        f"<td>{escape(m['project_name'] or '')}</td><td>{escape(m['assembler'])} {escape(m['assembler_version'])}"
        f" ({escape(m['kind'])})</td><td>{_num(m['total_length'])}</td></tr>" for m in data["members"])
    sections = []
    for r in data["results"]:
        title = f"{ANALYSIS_TITLES[r['analysis']]} · {METHOD_NAMES[r['method']]}"
        genomes = "".join(f"<li>{escape(g['label'])}: contigs SHA-256 <code>{escape(g['contigs_sha256'])}</code></li>"
                          for g in r["genomes"])
        record = db.get(ComparisonResult, r["id"])
        if r["analysis"] == "ani":
            body = _ani_html(r)
        elif r["analysis"] == "alignment":
            body = _alignment_html(r, svc.alignment_data(record))
        elif r["analysis"] == "region":
            body = _region_html(r, svc.result_data(record))
        elif r["analysis"] == "pangenome":
            body = _pangenome_html(r, pangenome_data(record))
        elif r["analysis"] == "phylogeny":
            body = tree_section(db, record) + (f"<p class='muted'>Full phylogenetic report: "
                                               f"/comparisons/results/{escape(r['id'])}/phylogeny/report.html</p>")
        else:
            body = _gene_html(r, svc.result_data(record))
        sections.append(f"<h3>{escape(title)}</h3>{_provenance(r)}<ul class='muted'>{genomes}</ul>{body}")
    methods = "".join(f"<p>{escape(t)}</p>" for t in data["methods"])
    limitations = "".join(f"<li>{escape(t)}</li>" for t in data["limitations"])
    s = data["set"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARVA comparative report · {escape(s['name'])}</title>
<style>
 body {{ font-family: Inter, -apple-system, Segoe UI, Arial, sans-serif; color:#0B132B; background:#F8FAFC;
        margin:0; padding:32px 16px; line-height:1.5; }}
 main {{ max-width: 1000px; margin: 0 auto; background:#fff; border:1px solid #E5E7EB; border-radius:12px; padding:32px; }}
 header {{ border-bottom: 2px solid #00B4A6; padding-bottom: 12px; margin-bottom: 24px; }}
 .brand {{ letter-spacing: .3em; font-weight: 600; color:#1F3B8A; font-size: 13px; }}
 h1 {{ margin: 4px 0; font-size: 26px; }} h2 {{ font-size: 18px; margin-top: 32px; color:#1F3B8A; }}
 h3 {{ font-size: 16px; margin: 28px 0 4px; }} h4 {{ font-size: 14px; margin: 20px 0 6px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin: 8px 0; }}
 th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #EEF2F7; vertical-align: top; }}
 th {{ color:#475569; font-weight: 500; }}
 code {{ font-size: 11px; word-break: break-all; }}
 pre {{ font-size: 11px; background:#F1F5F9; padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-all; }}
 .muted {{ color:#64748B; font-size: 12px; margin: 0; }}
 figure.map {{ margin: 8px 0; overflow-x: auto; }}
 .warn {{ background:#FFFBEB; border:1px solid #F59E0B55; border-radius:8px; padding:8px 12px; font-size: 13px; }}
 footer {{ margin-top: 32px; font-size: 11px; color:#64748B; }}
 @media print {{ body {{ background:#fff; padding:0; }} main {{ border:none; }} }}
</style></head>
<body><main>
<header><div class="brand">ARVA · GENOMIC DISCOVERY PLATFORM</div>
<h1>Comparative genomics report</h1>
<p class="muted">Comparison set “{escape(s['name'])}” · project “{escape(s['project_name'] or '')}” ·
Generated {escape(data['generated_at'])} · ARVA {escape(data['arva_version'])}</p>
{f"<p>{escape(s['description'])}</p>" if s['description'] else ""}</header>
<h2>Genomes</h2>
<table><tr><th>Label</th><th>Sample</th><th>Project</th><th>Assembly</th><th>Length (bp)</th></tr>{members}</table>
<h2>Results</h2>
{''.join(sections) or '<p>No comparison has been run on this set yet.</p>'}
<h2>Methods</h2>{methods}
<h2>Limitations</h2><ul>{limitations}</ul>
<footer>This report is descriptive. It contains values computed from the assemblies and does not make clinical or
biological claims.</footer>
</main></body></html>"""


def sample_comparisons(db: Session, sample: Sample) -> list[dict[str, Any]]:
    """The comparison sets that include an assembly of the sample, with the latest ANI values of that assembly
    against the set's other genomes and its alignment against the reference (when it was aligned)."""
    assembly_ids = set(db.scalars(select(Assembly.id).where(Assembly.sample_id == sample.id)).all())
    if not assembly_ids:
        return []
    set_ids = set(db.scalars(select(ComparisonMember.set_id).where(
        ComparisonMember.assembly_id.in_(assembly_ids))).all())
    out = []
    for cset in db.scalars(select(ComparisonSet).where(ComparisonSet.id.in_(set_ids))
                           .order_by(ComparisonSet.created_at)).all():
        project = db.get(Project, cset.project_id)
        mine = [m.label for m in cset.members if m.assembly_id in assembly_ids]
        entry: dict[str, Any] = {"set_id": cset.id, "name": cset.name, "project": project.name if project else None,
                                 "genomes": [m.label for m in cset.members], "labels": mine, "ani": [],
                                 "alignment": [], "pangenome": []}
        results = db.scalars(select(ComparisonResult).where(ComparisonResult.set_id == cset.id)
                             .order_by(ComparisonResult.created_at.desc())).all()
        ani = next((r for r in results if r.analysis == "ani"), None)
        if ani is not None:
            labels = [g["label"] for g in ani.genomes]
            m = ani.summary["matrix"]
            for i, a in enumerate(labels):
                if ani.genomes[i]["assembly_id"] in assembly_ids:
                    entry["ani"] += [{"genome": a, "other": b, "ani": m["ani"][i][j], "method": ani.method,
                                      "tool_version": ani.tool_version}
                                     for j, b in enumerate(labels) if j != i]
        aln = next((r for r in results if r.analysis == "alignment"), None)
        if aln is not None:
            ids = {g["label"]: g["assembly_id"] for g in aln.genomes}
            entry["alignment"] = [{**p, "method": aln.method, "tool_version": aln.tool_version}
                                  for p in aln.summary["pairs"] if p["role"] == "reference"
                                  and (ids.get(p["query"]) in assembly_ids or ids.get(p["reference"]) in assembly_ids)]
        pan = next((r for r in results if r.analysis == "pangenome"), None)
        if pan is not None:
            per = {g["label"]: g for g in pan.summary.get("per_genome") or []}
            entry["pangenome"] = [{"genome": g["label"], "families": per.get(g["label"], {}).get("families"),
                                   "unique": per.get(g["label"], {}).get("unique"),
                                   "set_families": pan.summary["families"],
                                   "core": pan.summary["category_counts"]["core"],
                                   "core_threshold": pan.summary["thresholds"]["core"], "method": pan.method,
                                   "tool_version": pan.tool_version}
                                  for g in pan.genomes if g["assembly_id"] in assembly_ids]
        out.append(entry)
    return out


def _sample_pangenome(rows: list[dict[str, Any]]) -> str:
    body = "".join(f"<tr><td>{escape(x['genome'])}</td><td>{_num(x['families'], 0)}</td><td>{_num(x['unique'], 0)}</td>"
                   f"<td>{x['core']:,} (>= {x['core_threshold']:.0%}) of {x['set_families']:,}</td>"
                   f"<td>{escape(x['method'])} {escape(x['tool_version'])}</td></tr>" for x in rows)
    return ("<table class='grid'><tr><th>Genome</th><th>Gene families</th><th>Found only in this genome</th>"
            f"<th>Core families of the set</th><th>Pangenome method</th></tr>{body}</table>")


def sample_section_html(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    parts = ["<h2>Comparative genomics</h2><p class='muted'>Similarity values; not a phylogeny and not evidence of "
             "transfer. The full comparative report of each set is in the Comparative genomics area.</p>"]
    for e in entries:
        ani = "".join(f"<tr><td>{escape(x['genome'])}</td><td>{escape(x['other'])}</td><td>{_num(x['ani'])}</td>"
                      f"<td>{escape(x['method'])} {escape(x['tool_version'])}</td></tr>" for x in e["ani"])
        aln = "".join(f"<tr><td>{escape(p['reference'])}</td><td>{escape(p['query'])}</td>"
                      f"<td>{_pct(p['ref_fraction'])}</td><td>{_pct(p['query_fraction'])}</td>"
                      f"<td>{_num(p['identity'], 3)}</td><td>{escape(p['method'])} {escape(p['tool_version'])}</td></tr>"
                      for p in e["alignment"])
        parts.append(f"<h3>{escape(e['name'])}</h3><p class='muted'>Set of {len(e['genomes'])} genomes "
                     f"(project “{escape(e['project'] or '')}”)</p>"
                     + (f"<table class='grid'><tr><th>Genome</th><th>Other genome</th><th>ANI (%)</th><th>Method</th>"
                        f"</tr>{ani}</table>" if ani else "")
                     + (f"<table class='grid'><tr><th>Reference</th><th>Query</th><th>Reference aligned</th>"
                        f"<th>Query aligned</th><th>Identity (%)</th><th>Aligner</th></tr>{aln}</table>" if aln else "")
                     + (_sample_pangenome(e["pangenome"]) if e.get("pangenome") else ""))
    return "".join(parts)
