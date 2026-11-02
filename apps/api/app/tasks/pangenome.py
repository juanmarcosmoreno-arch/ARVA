"""Worker task for the pangenome of a comparison set (Panaroo, or PPanGGOLiN when installed).

Before the run the worker checks each genome's annotation again (its GFF3 SHA-256 recorded when the job was
created) and that the GFF3 holds the genome sequence (##FASTA). The files are staged as input/g<N>.gff3 (links), so
the tools name the genomes g1..gN; ARVA maps the names back to the set's labels. Panaroo builds shell command
strings from its output folder, so it runs in the results folder with relative paths only. Panaroo's intermediate
files (combined CDS FASTA, cd-hit output, the pre-filter graph) are removed; its tables, graph, reference FASTA and
alignments stay, with their SHA-256. ARVA writes pangenome.json (families, presence, categories, curves, ordering) and
members.jsonl (per family: member genes, the offset of each in gene_data.csv, the ARVA annotation feature of each,
neighbouring families).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from arva_core import pangenome as core
from arva_tools import pangenome as tool
from arva_tools.pangenome import PanarooAdapter, PanarooParams, PpanggolinAdapter, PpanggolinParams
from arva_tools.registry import get_adapter

from app.models import Annotation, ComparisonResult, ComparisonSet
from app.services import annotation as annotation_svc
from app.services import pangenome as svc
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.comparative import _check, _files, _read, _run_tool
from app.tasks.tools import _resolve_tool, _sha256

INPUT_DIR = "input"
NEIGHBOURS = 8


def _set(ctx: JobContext) -> ComparisonSet:
    cset = ctx.db.get(ComparisonSet, ctx.job.parameters["set_id"])
    if cset is None:
        raise JobFailure("The comparison set was deleted", "comparison_set_missing")
    return cset


def _has_fasta(path: Path) -> bool:
    with path.open("rb") as fh:
        return any(line.startswith(b"##FASTA") for line in fh)


def _stage(ctx: JobContext, results: Path) -> list[dict[str, Any]]:
    staged = []
    (results / INPUT_DIR).mkdir(parents=True)
    for n, g in enumerate(ctx.job.parameters["genomes"], 1):
        rec = g.get("annotation") or {}
        a = ctx.db.get(Annotation, rec.get("annotation_id"))
        if a is None:
            raise JobFailure(f"The annotation of {g['label']} no longer exists", "pangenome_annotation_missing",
                             genomes=g["label"])
        src = ctx.path((a.files or {}).get("gff3", {}).get("path", ""))
        if not src.is_file():
            raise JobFailure(f"The GFF3 file of {g['label']} is missing on disk", "pangenome_gff_missing",
                             genomes=g["label"])
        digest = _sha256(src)
        if rec.get("gff3_sha256") not in (None, "-", digest):
            raise JobFailure(f"The annotation of {g['label']} changed since the job was created (sha256 {digest})",
                             "pangenome_annotation_changed", genome=g["label"])
        if not _has_fasta(src):
            raise JobFailure(f"The GFF3 file of {g['label']} holds no ##FASTA section with the genome sequence",
                             "pangenome_gff_without_fasta", genome=g["label"])
        dest = results / INPUT_DIR / f"g{n}.gff3"
        os.symlink(src, dest)
        ctx.log(f"Genome g{n} '{g['label']}': {a.tool} {a.tool_version} annotation {a.id}, GFF3 sha256 {digest}")
        staged.append({**g, "index": n - 1, "tool_name": f"g{n}", "gff3_sha256": digest, "annotation_obj": a})
    ctx.check_cancelled()
    return staged


def _features(a: Annotation) -> dict[str, dict[str, Any]]:
    """The annotation's features by the IDs the tools read from the GFF3 (Bakta and Prokka: the locus tag)."""
    names = annotation_svc.original_names(a)
    out = {}
    for f in annotation_svc.features_of(a):
        brief = {"annotation_id": a.id, "feature_id": f["id"], "locus_tag": f.get("locus_tag"),
                 "gene": f.get("gene"), "product": f.get("product"),
                 "contig": names.get(f["contig"], f["contig"]), "start": f["start"], "end": f["end"],
                 "strand": f["strand"]}
        for key in (f.get("tool_id"), f.get("locus_tag")):
            if key:
                out.setdefault(key, brief)
    return out


def _panaroo(ctx: JobContext, exe: str, staged: list[dict[str, Any]], results: Path) -> dict[str, Any]:
    s = ctx.job.parameters["settings"]["tool"]
    params = PanarooParams(**{k: v for k, v in s.items() if k != "mode_dependent"})
    argv = _check("Panaroo", lambda: PanarooAdapter.argv(exe, params, [f"{INPUT_DIR}/g{g['index'] + 1}.gff3"
                                                                       for g in staged], "panaroo"))
    _run_tool(ctx, "Panaroo", argv, results, "panaroo.log", extra_env=tool.env_for(exe))
    out = results / "panaroo"
    rtab = _read("Panaroo", out / "gene_presence_absence.Rtab", core.parse_rtab)
    table = _read("Panaroo", out / "gene_presence_absence.csv", tool.parse_presence_csv)
    own = _read("Panaroo", out / "summary_statistics.txt", tool.parse_summary)
    gene_data: dict[tuple[str, str], tuple[int, dict[str, str]]] = {}
    if not (out / "gene_data.csv").is_file():
        raise JobFailure("Panaroo exited without an error but did not write gene_data.csv", "outputs_missing",
                         tool="Panaroo", files="gene_data.csv")
    try:
        for offset, row in tool.iter_gene_data(out / "gene_data.csv"):
            gene_data[(row["gff_file"], row["annotation_id"])] = (offset, row)
    except ValueError as exc:
        raise JobFailure(f"Panaroo's output cannot be read: {exc}", "output_unreadable", tool="Panaroo",
                         detail=str(exc)) from exc
    for f in out.iterdir():
        if f.is_file() and f.name not in tool.PANAROO_KEEP:
            f.unlink()
        elif f.is_dir() and f.name != "aligned_gene_sequences":
            shutil.rmtree(f)
    members = {}
    for fam in table["families"]:
        members[fam["family"]] = [{"genome": gname, "id": gid, "flags": m["flags"],
                                   "row": gene_data.get((gname, gid))}
                                  for gname, m in fam["members"].items() for gid in m["ids"]]
    info = {f["family"]: f for f in table["families"]}
    return {"rtab": rtab, "members": members, "info": info, "partitions": {}, "tool_summary": own,
            "files_dir": out, "gene_data": True}


def _ppanggolin(ctx: JobContext, exe: str, staged: list[dict[str, Any]], results: Path) -> dict[str, Any]:
    params = PpanggolinParams(**ctx.job.parameters["settings"]["tool"])
    (results / "anno.tsv").write_text("".join(f"g{g['index'] + 1}\t{INPUT_DIR}/g{g['index'] + 1}.gff3\n"
                                              for g in staged))
    (results / "tmp").mkdir()
    argv = _check("PPanGGOLiN", lambda: PpanggolinAdapter.argv(exe, params, "anno.tsv", "ppanggolin", "tmp"))
    _run_tool(ctx, "PPanGGOLiN", argv, results, "ppanggolin.log", extra_env=tool.env_for(exe))
    shutil.rmtree(results / "tmp", ignore_errors=True)
    out = results / "ppanggolin"
    rtab = _read("PPanGGOLiN", out / "gene_presence_absence.Rtab", core.parse_rtab)
    partitions = _read("PPanGGOLiN", out / "matrix.csv", tool.parse_ppanggolin_matrix)
    fams = _read("PPanGGOLiN", out / "gene_families.tsv", tool.parse_ppanggolin_families)
    members = {name: [{"genome": None, "id": m["id"], "flags": ["fragment"] if m["fragment"] else [], "row": None}
                      for m in ms] for name, ms in fams.items()}
    return {"rtab": rtab, "members": members, "info": {}, "partitions": partitions, "tool_summary": None,
            "files_dir": out, "gene_data": False}


def _neighbours(members: dict[str, list[dict[str, Any]]], index: dict[str, int]) -> dict[int, list[dict[str, int]]]:
    """Families of the genes next to each member (Panaroo's clustering ids <genome>_<contig>_<gene>), counted in
    genomes."""
    at: dict[tuple[str, int, int], int] = {}
    for name, ms in members.items():
        for m in ms:
            if m["row"] and (pos := tool.gene_position(m["row"][1]["clustering_id"])):
                at[(m["genome"], *pos)] = index[name]
    out: dict[int, list[dict[str, int]]] = {}
    for name, ms in members.items():
        seen: dict[int, set[str]] = {}
        for m in ms:
            if m["row"] and (pos := tool.gene_position(m["row"][1]["clustering_id"])):
                for step in (-1, 1):
                    nb = at.get((m["genome"], pos[0], pos[1] + step))
                    if nb is not None and nb != index[name]:
                        seen.setdefault(nb, set()).add(m["genome"])
        ranked = sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:NEIGHBOURS]
        out[index[name]] = [{"family": k, "genomes": len(v)} for k, v in ranked]
    return out


def _body(ctx: JobContext) -> None:
    p = ctx.job.parameters
    cset = _set(ctx)
    method, settings = p["method"], p["settings"]
    exe = _resolve_tool(ctx, svc.METHODS[method]["tool"])
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, results)
    by_tool_name = {g["tool_name"]: g for g in staged}
    run = (_panaroo if method == "panaroo" else _ppanggolin)(ctx, exe, staged, results)
    rtab = run["rtab"]
    if rtab["genomes"] != [g["tool_name"] for g in staged]:
        raise JobFailure(f"{ctx.job.tool_name} named the genomes {', '.join(rtab['genomes'])}", "output_unreadable",
                         tool=ctx.job.tool_name, detail="unexpected genome names")
    presence = rtab["presence"]
    summary = core.summary(presence, settings["categories"])
    clustering = core.genome_clustering(presence)
    order = core.family_order(presence, clustering["order"])
    curves = core.accumulation(presence, settings["curves"]["permutations"], settings["curves"]["seed"])
    index = {name: i for i, name in enumerate(rtab["families"])}
    feature_maps = {g["tool_name"]: _features(g["annotation_obj"]) for g in staged}
    neighbours = _neighbours(run["members"], index) if run["gene_data"] else {}
    families, offsets = [], []
    with (results / svc.MEMBERS_FILE).open("w") as fh:
        for i, name in enumerate(rtab["families"]):
            info = run["info"].get(name) or {}
            ms = []
            for m in run["members"].get(name, []):
                row = m["row"]
                gname = m["genome"] or next((g for g, fm in feature_maps.items() if m["id"] in fm), None)
                ms.append({"g": by_tool_name[gname]["index"] if gname in by_tool_name else None, "id": m["id"],
                           "flags": m["flags"], "data": row[0] if row else None,
                           "feature": feature_maps.get(gname, {}).get(m["id"]),
                           "refound": tool.refound_location(row[1]["description"]) if row else None})
            offsets.append(fh.tell())
            fh.write(json.dumps({"family": name, "members": ms, "neighbours": neighbours.get(i, [])},
                                separators=(",", ":")) + "\n")
            families.append({"name": name, "gene_names": info.get("gene_names", []),
                             "annotation": info.get("annotation", ""), "count": summary["counts"][i],
                             "category": summary["categories"][i], "partition": run["partitions"].get(name),
                             "members": len(ms), "presence": "".join(str(x) for x in presence[i])})
            if i % 5000 == 0:
                ctx.check_cancelled()
    genomes = [{"label": g["label"], "tool_name": g["tool_name"], "assembly_id": g["assembly_id"],
                "sample_id": g.get("sample_id"), "annotation_id": g["annotation"]["annotation_id"]} for g in staged]
    data = {"genomes": genomes, "families": families, "family_order": order, "clustering": clustering,
            "curves": curves, "distribution": core.frequency_distribution(summary["counts"], len(staged)),
            "member_offsets": offsets}
    (results / svc.DATA_FILE).write_text(json.dumps(data, separators=(",", ":")))
    shutil.rmtree(results / INPUT_DIR, ignore_errors=True)
    warnings = _warnings(ctx, staged, summary)
    kept = [results / svc.DATA_FILE, results / svc.MEMBERS_FILE, results / f"{method}.log"]
    kept += sorted(f for f in run["files_dir"].iterdir() if f.is_file())
    if (aligned := run["files_dir"] / "aligned_gene_sequences").is_dir():
        manifest = results / svc.ALIGNMENTS_MANIFEST
        manifest.write_text("".join(f"{_sha256(f)}  {f.relative_to(results)}\n"
                                    for f in sorted(aligned.iterdir()) if f.is_file()))
        kept.append(manifest)
    files = _files(ctx, kept)
    sizes = {k: v for k, v in summary.items() if k in ("genomes", "families", "category_counts", "thresholds",
                                                       "families_per_genome", "unique_per_genome")}
    n = len(staged)
    stored = {**sizes, "tool_summary": run["tool_summary"],
              "pan_size": curves["pan"]["mean"][-1], "core_strict": curves["core"]["mean"][-1],
              "curves": {"permutations": curves["permutations"], "seed": curves["seed"]},
              "annotation_consistency": p.get("annotation_consistency"),
              "partitions": {k: sum(1 for f in families if f["partition"] == k)
                             for k in ("persistent", "shell", "cloud")} if run["partitions"] else None,
              "aligned": settings["tool"].get("alignment") not in (None, "none"),
              "notes": [svc.CATEGORY_NOTE, svc.CLUSTER_NOTE, svc.ANNOTATION_NOTE],
              "per_genome": [{"label": g["label"], "families": summary["families_per_genome"][i],
                              "unique": summary["unique_per_genome"][i]} for i, g in enumerate(staged)]}
    result = ComparisonResult(set_id=cset.id, job_id=ctx.job.id, analysis="pangenome", method=method,
                              tool=ctx.job.tool_name, tool_version=ctx.job.tool_version, parameters=settings,
                              genomes=[{k: g.get(k) for k in ("assembly_id", "label", "sample_id", "sample_code",
                                                              "project_id", "kind", "assembler", "assembler_version",
                                                              "contigs_sha256", "total_length",
                                                              "synthetic_evidence")}
                                       | {"annotation": {**g["annotation"], "gff3_sha256": g["gff3_sha256"]},
                                          "tool_name": g["tool_name"]} for g in staged],
                              summary=stored, warnings=warnings, files=files)
    ctx.db.add(result)
    ctx.db.flush()
    ctx.job.result_summary = {"comparison_result_id": result.id, "set_id": cset.id, "analysis": "pangenome",
                              "method": method, "warnings": [w["code"] for w in warnings], "files": files}
    ctx.job.output_paths = [f["path"] for f in files.values()]
    cc = summary["category_counts"]
    ctx.log(f"{ctx.job.tool_name}: {summary['families']} families in {n} genomes; core {cc['core']}, soft core "
            f"{cc['soft_core']}, shell {cc['shell']}, cloud {cc['cloud']} (thresholds {settings['categories']})")


def _warnings(ctx: JobContext, staged: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    job = ctx.job
    out: list[dict[str, Any]] = []
    tested = get_adapter(svc.METHODS[job.parameters["method"]]["tool"]).info.tested_versions
    if job.tool_version not in tested:
        out.append({"code": "tool_not_validated", "params": {"tool": job.tool_name, "version": job.tool_version}})
    consistency = job.parameters.get("annotation_consistency") or {}
    if consistency and not consistency.get("consistent"):
        out.append({"code": "pangenome_mixed_annotation", "params": {
            "annotators": "; ".join(f"{a['annotator']}: {', '.join(a['genomes'])}"
                                    for a in consistency["annotators"])}})
    if len(staged) < svc.FEW_GENOMES:
        out.append({"code": "pangenome_few_genomes", "params": {"count": len(staged)}})
    seen: dict[str, str] = {}
    for g in staged:
        if g["contigs_sha256"] in seen:
            out.append({"code": "comparison_identical_genomes", "params": {"a": seen[g["contigs_sha256"]],
                                                                            "b": g["label"]}})
        seen.setdefault(g["contigs_sha256"], g["label"])
    if synthetic := [f"{g['label']}: {', '.join(g['synthetic_evidence'])}" for g in staged
                     if g.get("synthetic_evidence")]:
        out.append({"code": "synthetic_input", "params": {"evidence": "; ".join(synthetic)}})
    if summary["absent_families"]:
        out.append({"code": "pangenome_empty_families", "params": {"count": summary["absent_families"]}})
    return out


def run_pangenome_job(job_id: str) -> str:
    return run_job(job_id, _body)
