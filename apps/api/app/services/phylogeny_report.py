"""The phylogenetic report of one tree, and the tree section of the comparative report: the figure (rectangular,
rooted as the saved view says, every clade expanded), the source and its checksum, methods, tools, versions,
parameters, supports, warnings, limitations and references."""
from __future__ import annotations

import json
import math
import shlex
from datetime import UTC, datetime
from html import escape
from typing import Any

from sqlalchemy.orm import Session

from app import __version__ as ARVA_VERSION
from app.models import AnalysisJob, ComparisonResult, ComparisonSet
from app.services import phylogeny as svc

SOURCE_TITLES = {"core_alignment": "Core-genome alignment (Panaroo)", "snp_alignment": "Core-genome SNPs (SNP-sites)",
                 "family_alignment": "Gene family alignment (Panaroo)",
                 "gene_alignment": "Gene alignment (Custom gene investigation, MAFFT)",
                 "ani_matrix": "ANI matrix (1 - ANI/100)"}
METHOD_TITLES = {"iqtree": "IQ-TREE maximum likelihood", "fasttree": "FastTree approximate maximum likelihood",
                 "nj": "Neighbour joining (ARVA), distance tree"}
REFERENCES = [
    "Minh BQ, Schmidt HA, Chernomor O, et al. IQ-TREE 2: New models and efficient methods for phylogenetic inference "
    "in the genomic era. Mol Biol Evol 2020;37:1530-1534.",
    "Kalyaanamoorthy S, Minh BQ, Wong TKF, et al. ModelFinder: fast model selection for accurate phylogenetic "
    "estimates. Nat Methods 2017;14:587-589.",
    "Hoang DT, Chernomor O, von Haeseler A, et al. UFBoot2: Improving the ultrafast bootstrap approximation. Mol Biol "
    "Evol 2018;35:518-522.",
    "Guindon S, Dufayard JF, Lefort V, et al. New algorithms and methods to estimate maximum-likelihood phylogenies: "
    "assessing the performance of PhyML 3.0. Syst Biol 2010;59:307-321 (SH-aLRT).",
    "Price MN, Dehal PS, Arkin AP. FastTree 2 - approximately maximum-likelihood trees for large alignments. PLoS One "
    "2010;5:e9490.",
    "Page AJ, Taylor B, Delaney AJ, et al. SNP-sites: rapid efficient extraction of SNPs from multi-FASTA alignments. "
    "Microb Genom 2016;2:e000056.",
    "Tonkin-Hill G, MacAlasdair N, Ruis C, et al. Producing polished prokaryotic pangenomes with the Panaroo "
    "pipeline. Genome Biol 2020;21:180.",
    "Saitou N, Nei M. The neighbor-joining method. Mol Biol Evol 1987;4:406-425.",
    "Robinson DF, Foulds LR. Comparison of phylogenetic trees. Math Biosci 1981;53:131-147.",
]
LIMITATIONS = [
    "A tree summarises the history of the aligned sequences under the method's assumptions. Recombination and "
    "horizontal transfer, common in bacteria, make parts of a genome follow different histories; a core-genome tree "
    "is an average over them.",
    "Branch supports (UFBoot, SH-aLRT, SH-like) measure how consistently the data support a branch; they are not "
    "probabilities that a clade is correct. UFBoot values are usually read as strong from 95 %, SH-aLRT from 80 % "
    "(IQ-TREE's documentation).",
    "The root is a drawing choice (midpoint or outgroup), not inferred. Its position on its branch is not estimated.",
    "A distance tree (neighbour joining) has no substitution model and no supports; a tree from ANI is a similarity "
    "dendrogram, not a phylogeny.",
    "Closely related genomes do not establish the direction or route of transmission, and similarity alone does not "
    "show horizontal transfer.",
]


def _layout(tree: dict[str, Any]) -> tuple[list[dict[str, Any]], float, bool]:
    """Nodes with x (distance from the root, or depth when lengths are missing), y (leaf order, ladderized) and
    their parent's x."""
    lengths = all(n.get("length") is not None for n in _walk(tree) if n is not tree)
    size: dict[int, int] = {}

    def count(n: dict[str, Any]) -> int:
        size[id(n)] = 1 if not n["children"] else sum(count(c) for c in n["children"])
        return size[id(n)]
    count(tree)
    out: list[dict[str, Any]] = []
    y = 0

    def place(n: dict[str, Any], x: float, px: float) -> float:
        nonlocal y
        if not n["children"]:
            node = {"n": n, "x": x, "px": px, "y": float(y)}
            y += 1
        else:
            kids = sorted(n["children"], key=lambda c: size[id(c)])
            ys = [place(c, x + ((c.get("length") or 0.0) if lengths else 1.0), x) for c in kids]
            node = {"n": n, "x": x, "px": px, "y": (ys[0] + ys[-1]) / 2, "kids": ys}
        out.append(node)
        return node["y"]
    place(tree, 0.0, 0.0)
    return out, max(o["x"] for o in out) or 1.0, lengths


def _walk(n: dict[str, Any]):
    yield n
    for c in n["children"]:
        yield from _walk(c)


def _scale(span: float) -> float:
    target = span / 5
    p = 10 ** math.floor(math.log10(target)) if target > 0 else 1
    return next(m * p for m in (5, 2, 1) if m * p <= target) if target > 0 else 1


def tree_svg(tree: dict[str, Any], support: dict[str, Any] | None) -> str:
    nodes, span, lengths = _layout(tree)
    leaves = [o for o in nodes if not o["n"]["children"]]
    row, left, width = 18, 20, 520
    label_w = max(len(o["n"].get("name") or "") for o in leaves) * 6.5 + 20
    h = len(leaves) * row + 50
    sx = width / span

    def X(v: float) -> float:
        return left + v * sx

    def Y(v: float) -> float:
        return 20 + v * row
    parts = []
    for o in nodes:
        n = o["n"]
        parts.append(f"<line x1='{X(o['px']):.1f}' y1='{Y(o['y']):.1f}' x2='{X(o['x']):.1f}' y2='{Y(o['y']):.1f}' "
                     "stroke='#334155' stroke-width='1.2'/>")
        if n["children"]:
            parts.append(f"<line x1='{X(o['x']):.1f}' y1='{Y(o['kids'][0]):.1f}' x2='{X(o['x']):.1f}' "
                         f"y2='{Y(o['kids'][-1]):.1f}' stroke='#334155' stroke-width='1.2'/>")
            label = "/".join(f"{v:g}" for v in n["supports"]) if n.get("supports") else \
                (f"{n['support']:g}" if n.get("support") is not None else "")
            if label and support:
                parts.append(f"<text x='{X(o['x']) - 3:.1f}' y='{Y(o['y']) - 3:.1f}' font-size='9' "
                             f"text-anchor='end' fill='#64748B'>{escape(label)}</text>")
        else:
            parts.append(f"<text x='{X(o['x']) + 4:.1f}' y='{Y(o['y']) + 4:.1f}' font-size='11' "
                         f"fill='#0B132B'>{escape(n.get('name') or '')}</text>")
    if lengths:
        bar = _scale(span)
        y0 = h - 18
        parts.append(f"<line x1='{left}' y1='{y0}' x2='{left + bar * sx:.1f}' y2='{y0}' stroke='#0B132B' "
                     "stroke-width='1.5'/>"
                     f"<text x='{left}' y='{y0 + 13}' font-size='10' fill='#475569'>{bar:g} "
                     "substitutions per site</text>")
    total_w = left + width + label_w
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{total_w:.0f}' height='{h}' viewBox='0 0 {total_w:.0f} "
            f"{h}' font-family='Inter, Arial, sans-serif' role='img'>{''.join(parts)}</svg>")


def _distance_units(r: ComparisonResult) -> str:
    if r.method != "nj":
        return "substitutions per site"
    kind = (r.parameters.get("nj") or {}).get("distance")
    return {"ani": "1 - ANI/100", "p": "p-distance (share of differing compared sites)",
            "jc69": "Jukes-Cantor distance"}.get(kind, "distance")


def tree_section(db: Session, r: ComparisonResult) -> str:
    d = svc.drawing(db, r)
    s = r.summary
    src = s["source"]
    what = SOURCE_TITLES[src["kind"]] + (f" · family {src['family']}" if src.get("family") else "") + \
        (f" · {src['core']} core genes" if src.get("core") else "")
    out = [f"<p><strong>{escape(METHOD_TITLES[r.method])}</strong> on {escape(what)} · {s['leaves']} leaves.</p>"]
    if r.method == "nj" or src["kind"] == "ani_matrix":
        out.append("<div class='warn'>" + escape(svc.ANI_NOTE if src["kind"] == "ani_matrix" else svc.DISTANCE_NOTE)
                   + "</div>")
    facts = []
    if al := s.get("alignment"):
        facts.append(f"Alignment: {al['sequences']} sequences × {al['columns']:,} columns; {al['variable']:,} variable "
                     f"({al['parsimony_informative']:,} parsimony-informative), {al['constant']:,} constant.")
    if "snp_columns" in s:
        cs = r.parameters.get("constant_sites")
        how = {"fconst": f"constant sites added back with -fconst {s.get('constant_counts')}",
               "asc": "ascertainment bias correction (+ASC) on A/C/G/T-only columns",
               "none": "no correction for the constant sites left out (branch lengths per variable site)"}[cs]
        facts.append(f"SNP alignment: {s['snp_columns']:,} columns (SNP-sites); {how}.")
    if iq := s.get("iqtree"):
        facts.append(f"Model: {iq['model']}" + (" (ModelFinder, BIC)" if (r.parameters.get("tree") or {})
                                                 .get("model") == "MFP" else " (stated)")
                     + f"; log-likelihood {iq.get('log_likelihood')}.")
    if sup := s.get("support"):
        facts.append(f"Branch supports: {sup['label']}.")
    facts.append(f"Branch lengths: {_distance_units(r)}.")
    if d is not None:
        info = d["rooting"]
        root = {"none": "unrooted (drawn from the node the tool wrote first)",
                "midpoint": f"midpoint rooted (longest path {', '.join(info.get('leaves') or [])})",
                "outgroup": f"rooted on the outgroup {', '.join(info.get('outgroup') or [])}"}[info["method"]]
        facts.append(f"Drawing: {root}.")
    out.append("<ul class='muted'>" + "".join(f"<li>{escape(f)}</li>" for f in facts) + "</ul>")
    if d is not None:
        out.append(f"<figure class='map'>{tree_svg(d['rooted'], d.get('support'))}</figure>")
    else:
        out.append("<p class='muted'>The tree files of this result are missing on disk.</p>")
    return "".join(out)


def phylogeny_report_html(db: Session, r: ComparisonResult) -> str:
    cset = db.get(ComparisonSet, r.set_id)
    job = db.get(AnalysisJob, r.job_id)
    src = r.summary["source"]
    genomes = "".join(f"<tr><td>{escape(g['label'])}</td><td>{escape(g.get('sample_code') or '')}</td>"
                      f"<td><code>{escape(g.get('contigs_sha256') or '')}</code></td></tr>" for g in r.genomes)
    data = svc.data(r) or {}
    source_file = (data.get("source") or {}).get("file") or {}
    commands = "".join(f"<pre>{escape(shlex.join(c))}</pre>" for c in (job.commands if job else None) or [])
    warnings = "".join(f"<li><code>{escape(w['code'])}</code> {escape(json.dumps(w['params']))}</li>"
                       for w in r.warnings)
    notes = "".join(f"<p>{escape(n)}</p>" for n in r.summary.get("notes") or [])
    files = "".join(f"<tr><td>{escape(k)}</td><td><code>{escape(v['sha256'])}</code></td></tr>"
                    for k, v in sorted(r.files.items()))
    refs = "".join(f"<li>{escape(x)}</li>" for x in REFERENCES)
    lims = "".join(f"<li>{escape(x)}</li>" for x in LIMITATIONS)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARVA phylogenetic report · {escape(cset.name if cset else '')}</title>
<style>
 body {{ font-family: Inter, -apple-system, Segoe UI, Arial, sans-serif; color:#0B132B; background:#F8FAFC;
        margin:0; padding:32px 16px; line-height:1.5; }}
 main {{ max-width: 1000px; margin: 0 auto; background:#fff; border:1px solid #E5E7EB; border-radius:12px; padding:32px; }}
 header {{ border-bottom: 2px solid #00B4A6; padding-bottom: 12px; margin-bottom: 24px; }}
 .brand {{ letter-spacing: .3em; font-weight: 600; color:#1F3B8A; font-size: 13px; }}
 h1 {{ margin: 4px 0; font-size: 26px; }} h2 {{ font-size: 18px; margin-top: 32px; color:#1F3B8A; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin: 8px 0; }}
 th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #EEF2F7; vertical-align: top; }}
 th {{ color:#475569; font-weight: 500; }}
 code {{ font-size: 11px; word-break: break-all; }}
 pre {{ font-size: 11px; background:#F1F5F9; padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-all; }}
 .muted {{ color:#64748B; font-size: 12px; }}
 figure.map {{ margin: 8px 0; overflow-x: auto; }}
 .warn {{ background:#FFFBEB; border:1px solid #F59E0B55; border-radius:8px; padding:8px 12px; font-size: 13px; }}
 footer {{ margin-top: 32px; font-size: 11px; color:#64748B; }}
 @media print {{ body {{ background:#fff; padding:0; }} main {{ border:none; }} }}
</style></head>
<body><main>
<header><div class="brand">ARVA · GENOMIC DISCOVERY PLATFORM</div>
<h1>Phylogenetic report</h1>
<p class="muted">Comparison set “{escape(cset.name if cset else '')}” · {escape(r.tool)} {escape(r.tool_version)} ·
job <code>{escape(r.job_id)}</code> · generated {escape(generated)} · ARVA {escape(ARVA_VERSION)}</p></header>
<h2>Summary</h2>{tree_section(db, r)}
<h2>Source</h2>
<p>{escape(SOURCE_TITLES[src['kind']])} from result <code>{escape(src['result_id'])}</code>
({escape(str(src.get('result_method') or ''))}){f" · file <code>{escape(source_file.get('key', ''))}</code> SHA-256 <code>{escape(str(source_file.get('sha256')))}</code>" if source_file else ""}.</p>
<table><tr><th>Genome</th><th>Sample</th><th>Contigs SHA-256</th></tr>{genomes}</table>
<h2>Methods</h2>{notes}
<p class="muted">Settings: <code>{escape(json.dumps(r.parameters, sort_keys=True))}</code></p>{commands}
{f"<div class='warn'><strong>Notes</strong><ul>{warnings}</ul></div>" if warnings else ""}
<h2>Files</h2><table><tr><th>File</th><th>SHA-256</th></tr>{files}</table>
<h2>Limitations</h2><ul>{lims}</ul>
<h2>References</h2><ul>{refs}</ul>
<footer>This report is descriptive. It contains values computed from the assemblies and does not make clinical or
biological claims.</footer>
</main></body></html>"""
