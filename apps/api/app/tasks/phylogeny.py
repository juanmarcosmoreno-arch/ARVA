"""Worker task for a phylogeny of a comparison set (app.services.phylogeny).

The source file is checked against the SHA-256 its result recorded, its sequences are renamed s1..sN (the tools
refuse some characters and duplicate names) and written to the results folder, which is removed once the tree is
read. ARVA keeps the tools' own outputs (IQ-TREE's .treefile, .iqtree report, .log, .contree, .mldist; FastTree's
tree and log; the SNP alignment and the constant-site counts), writes phylogeny.nwk (the unrooted tree with the
leaves' names) and phylogeny.json (the tree, leaves, supports and alignment statistics), each with its SHA-256.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import arva_core
from arva_core import newick
from arva_core import phylo as core
from arva_tools.phylo import FasttreeAdapter, IqtreeAdapter, TreeParams, parse_iqtree_report
from arva_tools.registry import get_adapter
from arva_tools.snpsites import SnpsitesAdapter, parse_constant_counts

from app.models import ComparisonResult, ComparisonSet, PhyloTreeView
from app.services import phylogeny as svc
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.comparative import _check, _files, _read, _run_tool
from app.tasks.tools import _resolve_tool, _sha256

INPUT = "input.fasta"
IQTREE_KEEP = (".treefile", ".iqtree", ".log", ".contree", ".mldist")


def _fasta(path: Path, records: list[tuple[str, str]]) -> None:
    with path.open("w") as fh:
        for name, seq in records:
            fh.write(f">{name}\n")
            for i in range(0, len(seq), 80):
                fh.write(seq[i:i + 80] + "\n")


def _stage(ctx: JobContext, src: dict[str, Any], results: Path) -> list[tuple[str, str]]:
    f = src["file"]
    path = svc.source_path(f)
    if not path.is_file():
        raise JobFailure(f"The source file {f['key']} is missing on disk", "phylo_source_file_missing", file=f["key"])
    digest = _sha256(path)
    if f.get("sha256") and digest != f["sha256"]:
        raise JobFailure(f"The source file {f['key']} changed since its result was made (sha256 {digest})",
                         "phylo_source_changed", file=f["key"])
    ctx.log(f"Source {src['kind']}: {f['key']} of result {src['result_id']} ({src['result_tool']} "
            f"{src['result_tool_version']}), sha256 {digest}")
    records = dict(svc.read_alignment(path))
    staged = []
    for i, leaf in enumerate(src["leaves"], 1):
        seq = records.get(leaf["seq_id"])
        if seq is None:
            raise JobFailure(f"The source alignment holds no sequence {leaf['seq_id']}", "phylo_source_changed",
                             file=f["key"])
        staged.append((f"s{i}", seq.upper()))
    if len({len(s) for _, s in staged}) != 1:
        raise JobFailure("The source's sequences are not aligned (their lengths differ)", "phylo_not_aligned")
    _fasta(results / INPUT, staged)
    return staged


def _ani_distances(ctx: JobContext, r: ComparisonResult) -> list[list[float]]:
    ani = r.summary["matrix"]["ani"]
    n = len(ani)
    d = [[0.0] * n for _ in range(n)]
    missing = []
    for i in range(n):
        for j in range(i + 1, n):
            vals = [v for v in (ani[i][j], ani[j][i]) if v is not None]
            if not vals:
                missing.append(f"{r.genomes[i]['label']} / {r.genomes[j]['label']}")
                continue
            d[i][j] = d[j][i] = 1 - (sum(vals) / len(vals)) / 100
    if missing:
        raise JobFailure(f"The ANI result has no value for {len(missing)} pair(s): {', '.join(missing[:5])}",
                         "phylo_ani_missing_pairs", count=len(missing))
    ctx.log("Distances: 1 - ANI/100, the mean of both directions when the tool reported both")
    return d


def _support(method: str, tree_settings: dict[str, Any]) -> dict[str, Any] | None:
    if method == "fasttree":
        return {"kind": "sh_like", "label": svc.SUPPORT_LABELS["sh_like"], "max": 1}
    if method == "iqtree":
        kind = "alrt_ufboot" if tree_settings["alrt"] and tree_settings["ufboot"] else \
            "alrt" if tree_settings["alrt"] else "ufboot"
        return {"kind": kind, "label": svc.SUPPORT_LABELS[kind], "max": 100}
    return None


def _body(ctx: JobContext) -> None:
    p = ctx.job.parameters
    cset = ctx.db.get(ComparisonSet, p["set_id"])
    if cset is None:
        raise JobFailure("The comparison set was deleted", "comparison_set_missing")
    src, s, method = p["source"], p["settings"], p["method"]
    source_result = ctx.db.get(ComparisonResult, src["result_id"])
    if source_result is None:
        raise JobFailure("The source result was deleted", "phylo_source_missing")
    results = ctx.path(ctx.results_rel)
    results.mkdir(parents=True, exist_ok=True)
    leaves = [dict(x) for x in src["leaves"]]
    names = {f"s{i}": x["name"] for i, x in enumerate(leaves, 1)}
    warnings: list[dict[str, Any]] = []
    kept: list[Path] = []
    stats = None
    extra: dict[str, Any] = {}
    distances = None
    if src["kind"] != "ani_matrix":
        staged = _stage(ctx, src, results)
        stats = core.alignment_stats(staged)
        for leaf, frac in zip(leaves, stats.pop("missing_fraction"), strict=True):
            leaf["missing_fraction"] = frac
        ctx.log(f"Alignment: {stats['sequences']} sequences x {stats['columns']} columns; {stats['variable']} variable "
                f"({stats['parsimony_informative']} parsimony-informative), {stats['constant']} constant")
        if gappy := [x["name"] for x in leaves if x["missing_fraction"] > svc.GAPPY]:
            warnings.append({"code": "phylo_gappy_sequences", "params": {"names": ", ".join(gappy[:20]),
                                                                         "threshold": round(svc.GAPPY * 100)}})
        if stats["variable"] == 0:
            raise JobFailure("The aligned sequences are identical: there is nothing to build a tree from",
                             "phylo_no_variable_sites")
        ctx.check_cancelled()
    tree_input = INPUT
    fconst = None
    if src["kind"] == "snp_alignment":
        exe = _resolve_tool(ctx, "snp-sites")
        acgt = s["constant_sites"] == "asc"
        argv = _check("SNP-sites", lambda: SnpsitesAdapter.snp_argv(exe, INPUT, "snp.fasta", acgt))
        _run_tool(ctx, "SNP-sites", argv, results, "snp-sites.log")
        snp = svc.read_alignment(results / "snp.fasta") if (results / "snp.fasta").is_file() else []
        columns = len(snp[0][1]) if snp else 0
        if columns == 0:
            raise JobFailure("SNP-sites found no variable column to build a tree from", "phylo_no_variable_sites")
        kept += [results / "snp.fasta", results / "snp-sites.log"]
        extra["snp_columns"] = columns
        if s["constant_sites"] == "fconst":
            argv = _check("SNP-sites", lambda: SnpsitesAdapter.constant_argv(exe, INPUT, "constant_sites.txt"))
            _run_tool(ctx, "SNP-sites", argv, results, "snp-sites-constant.log")
            fconst = _read("SNP-sites", results / "constant_sites.txt", parse_constant_counts)
            extra["constant_counts"] = dict(zip("ACGT", fconst, strict=True))
            kept.append(results / "constant_sites.txt")
        elif s["constant_sites"] == "none":
            warnings.append({"code": "phylo_snp_uncorrected", "params": {}})
        ctx.log(f"SNP-sites: {columns} variable columns" + (f"; constant A,C,G,T {fconst}" if fconst else ""))
        tree_input = "snp.fasta"
    if method == "nj":
        if src["kind"] == "ani_matrix":
            d = _ani_distances(ctx, source_result)
            compared = None
        else:
            pd = core.pairwise_distances(staged, s["nj"]["distance"])
            d, compared = pd["distances"], pd["compared_sites"]
        tree, negative = core.neighbour_joining([f"s{i}" for i in range(1, len(leaves) + 1)], d)
        if negative:
            warnings.append({"code": "phylo_negative_lengths", "params": {"count": negative}})
        distances = {"kind": s["nj"]["distance"], "matrix": d, "compared_sites": compared}
        with (results / "distances.tsv").open("w") as fh:
            fh.write("\t".join(["", *(x["name"] for x in leaves)]) + "\n")
            for x, row in zip(leaves, d, strict=True):
                fh.write("\t".join([x["name"], *(f"{v:.8g}" for v in row)]) + "\n")
        kept.append(results / "distances.tsv")
        ctx.log(f"Neighbour joining (arva_core.phylo, ARVA {arva_core.__version__}) on {s['nj']['distance']} "
                f"distances; {negative} negative branch length(s) set to 0")
    else:
        exe = _resolve_tool(ctx, method)
        params = TreeParams(**s["tree"])
        if method == "iqtree":
            argv = _check("IQ-TREE", lambda: IqtreeAdapter.argv(exe, params, "nucleotide", tree_input, "tree",
                                                                 fconst=fconst))
            _run_tool(ctx, "IQ-TREE", argv, results, "iqtree.log")
            tree_file = results / "tree.treefile"
            extra["iqtree"] = _read("IQ-TREE", results / "tree.iqtree", parse_iqtree_report)
            kept += [results / f"tree{x}" for x in IQTREE_KEEP]
            log, own = results / "iqtree.log", results / "tree.log"
            if log.is_file() and own.is_file() and log.read_bytes() == own.read_bytes():
                log.unlink()
            kept.append(log)
            for f in results.glob("tree.*"):
                if f.suffix not in IQTREE_KEEP:
                    f.unlink()
        else:
            argv = _check("FastTree", lambda: FasttreeAdapter.argv(exe, params, "nucleotide", tree_input, "tree.nwk"))
            _run_tool(ctx, "FastTree", argv, results, "fasttree.log")
            tree_file = results / "tree.nwk"
            kept += [tree_file, results / "fasttree.log"]
        tree = _read(ctx.job.tool_name, tree_file, newick.parse)
    try:
        named = newick.rename(tree, names)
    except newick.NewickError as exc:
        raise JobFailure(f"The tree file cannot be read: {exc}", "output_unreadable", tool=ctx.job.tool_name,
                         detail=str(exc)) from exc
    (results / INPUT).unlink(missing_ok=True)
    (results / "phylogeny.nwk").write_text(newick.write(named) + "\n")
    rooting = s["rooting"]
    try:
        svc.rooted(named, rooting)
    except core.PhyloError as exc:
        warnings.append({"code": "phylo_rooting_failed", "params": {"detail": str(exc)}})
        rooting = {"method": "none", "outgroup": []}
    summary_tree = core.summary(named)
    if not all(math.isfinite(v) for v in (summary_tree["total_length"], summary_tree["max_root_to_tip"])):
        raise JobFailure("The tree has invalid branch lengths", "output_unreadable", tool=ctx.job.tool_name,
                         detail="branch lengths")
    tested = () if method == "nj" else get_adapter(method).info.tested_versions
    if method != "nj" and ctx.job.tool_version not in tested:
        warnings.append({"code": "tool_not_validated", "params": {"tool": ctx.job.tool_name,
                                                                  "version": ctx.job.tool_version}})
    if src["kind"] == "ani_matrix":
        warnings.append({"code": "phylo_ani_dendrogram", "params": {}})
    support = _support(method, s.get("tree") or {})
    data = {"tree": named, "leaves": leaves, "support": support, "alignment": stats, "distances": distances,
            "source": {k: v for k, v in src.items() if k != "leaves"}, **extra}
    (results / svc.DATA_FILE).write_text(json.dumps(data, separators=(",", ":")))
    files = _files(ctx, [results / svc.DATA_FILE, results / "phylogeny.nwk", *kept])
    summary = {"source": {k: src.get(k) for k in ("kind", "result_id", "analysis", "result_method", "core", "family",
                                                     "query")},
               "leaves": summary_tree["leaves"], "tree": summary_tree, "alignment": stats, "support": support,
               "distance_tree": method == "nj", "notes": p.get("notes") or [], **extra}
    result = ComparisonResult(set_id=cset.id, job_id=ctx.job.id, analysis="phylogeny", method=method,
                              tool=ctx.job.tool_name, tool_version=ctx.job.tool_version, parameters=s,
                              genomes=p["genomes"], summary=summary, warnings=warnings, files=files)
    ctx.db.add(result)
    ctx.db.flush()
    ctx.db.add(PhyloTreeView(result_id=result.id, rooting=rooting, style={}))
    ctx.job.result_summary = {"comparison_result_id": result.id, "set_id": cset.id, "analysis": "phylogeny",
                              "method": method, "warnings": [w["code"] for w in warnings], "files": files}
    ctx.job.output_paths = [f["path"] for f in files.values()]
    ctx.log(f"{ctx.job.tool_name}: tree of {summary_tree['leaves']} leaves" +
            (f", model {extra['iqtree']['model']}" if "iqtree" in extra else ""))


def run_phylogeny_job(job_id: str) -> str:
    return run_job(job_id, _body)
