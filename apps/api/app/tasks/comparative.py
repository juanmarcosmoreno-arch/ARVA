"""Worker tasks for comparative genomics: the ANI matrix of a comparison set (skani triangle or FastANI all-vs-all) and
the whole-genome alignment of its genomes in a chosen order (minimap2 or NUCmer, with dnadiff against the reference).

Before the run the worker checks again each genome's contigs (SHA-256 recorded when the job was created). The
contigs are staged as input/g<N>.fna (names kept, descriptions removed: stage_genome); NUCmer and dnadiff build shell
command strings from their arguments, so they run in a folder holding links named ref.fna and qry.fna. The staged
copies are removed at the end (their SHA-256 is recorded); the tools' outputs and logs stay in the job's results
folder.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from arva_core import comparative as core
from arva_core.formats import open_sequence_file
from arva_core.seqstats import iter_fasta
from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import fastani as fastani_tool
from arva_tools import skani as skani_tool
from arva_tools.base import help_options
from arva_tools.dnadiff import COMPARISON_SUFFIXES, DnadiffAdapter
from arva_tools.fastani import FastaniAdapter, FastaniParams
from arva_tools.mapping import Minimap2Adapter, parse_paf
from arva_tools.nucmer import NucmerAdapter, NucmerParams, parse_coords, show_coords_path
from arva_tools.registry import detect, get_adapter
from arva_tools.skani import SkaniAdapter, SkaniParams

from app.models import Assembly, ComparisonResult, ComparisonSet
from app.services import annotation as annotation_svc
from app.services import comparative as svc
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.tools import _rel, _resolve_tool, _run, _sha256

INPUT_DIR = "input"
GENOME_LIST = "genomes.txt"


def _set(ctx: JobContext) -> ComparisonSet:
    p = ctx.job.parameters or {}
    cset = ctx.db.get(ComparisonSet, p["set_id"])
    if cset is None:
        raise JobFailure("The comparison set was deleted", "comparison_set_missing")
    return cset


def _stage(ctx: JobContext, results: Path) -> list[dict[str, Any]]:
    """Stage every recorded genome after checking its contigs are the ones recorded."""
    staged = []
    (results / INPUT_DIR).mkdir(parents=True)
    for n, g in enumerate(ctx.job.parameters["genomes"], 1):
        a = ctx.db.get(Assembly, g["assembly_id"])
        if a is None:
            raise JobFailure(f"Assembly {g['assembly_id']} ({g['label']}) no longer exists", "assembly_missing",
                             assembly=g["label"])
        src = ctx.path(a.contigs_path)
        if not src.is_file():
            raise JobFailure(f"The contigs file of {g['label']} is missing on disk", "contigs_missing",
                             assembly=g["label"])
        if (digest := _sha256(src)) != g["contigs_sha256"]:
            raise JobFailure(f"The contigs of {g['label']} changed since the job was created (sha256 {digest})",
                             "contigs_changed", assembly=g["label"])
        dest = results / INPUT_DIR / f"g{n}.fna"
        info = annotation_svc.stage_genome(src, dest, False)
        with open_sequence_file(dest) as fh:
            contigs = core.contig_lengths(iter_fasta(fh))
        ctx.log(f"Genome {n} '{g['label']}': assembly {a.id} ({a.assembler} {a.assembler_version}, {a.kind.value}), "
                f"contigs sha256 {digest}; {len(contigs)} contigs, {info['total_length']:,} bp staged as "
                f"{INPUT_DIR}/{dest.name} (sha256 {info['sha256']})")
        staged.append({**g, "index": n - 1, "file": f"{INPUT_DIR}/{dest.name}", "staged_sha256": info["sha256"],
                       "contigs": contigs, "total_length": info["total_length"]})
    ctx.check_cancelled()
    return staged


def _snapshot(staged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = ("assembly_id", "label", "sample_id", "sample_code", "project_id", "kind", "assembler",
            "assembler_version", "contigs_sha256", "staged_sha256", "total_length", "synthetic_evidence")
    return [{**{k: g.get(k) for k in keep}, "contig_count": len(g["contigs"])} for g in staged]


def _check(name: str, build):
    try:
        return build()
    except (OSError, RuntimeError) as exc:
        raise JobFailure(f"{name}'s help could not be read to check its options: {exc}", "help_unreadable",
                         tool=name, detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"{name} cannot run with these settings: {exc}", "settings_rejected", tool=name,
                         detail=str(exc)) from exc


def _read(name: str, path: Path, parse):
    if not path.is_file():
        raise JobFailure(f"{name} exited without an error but did not write {path.name}", "outputs_missing",
                         tool=name, files=path.name)
    try:
        return parse(path.read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"{name}'s output cannot be read: {exc}", "output_unreadable", tool=name,
                         detail=str(exc)) from exc


def _run_tool(ctx: JobContext, name: str, argv: list[str], workdir: Path, log: str,
              stdout: Path | None = None, extra_env: dict[str, str] | None = None) -> None:
    try:
        _run(ctx, argv, workdir, log, stdout=stdout, extra_env=extra_env)
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError) or exc.code:
            raise
        lines = (workdir / log).read_text(errors="replace").strip().splitlines()[-3:] if (workdir / log).is_file() \
            else []
        raise JobFailure(f"{name} stopped: {' / '.join(lines) or exc}", "comparative_tool_failed", tool=name,
                         detail=" / ".join(lines)[:500]) from None


def _files(ctx: JobContext, paths: list[Path]) -> dict[str, dict[str, Any]]:
    out = {}
    for f in paths:
        if f.is_file():
            rel = _rel(ctx, f)
            out[rel.split(f"{ctx.results_rel}/", 1)[1]] = {"path": rel, "sha256": _sha256(f),
                                                          "size_bytes": f.stat().st_size}
    return out


def _cleanup_inputs(results: Path) -> None:
    shutil.rmtree(results / INPUT_DIR, ignore_errors=True)


def _warnings(ctx: JobContext, staged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    job = ctx.job
    warnings: list[dict[str, Any]] = []
    tested = get_adapter(_tool_id(job.job_type, job.parameters)).info.tested_versions
    if job.tool_version not in tested:
        warnings.append({"code": "tool_not_validated", "params": {"tool": job.tool_name,
                                                                  "version": job.tool_version}})
    seen: dict[str, str] = {}
    for g in staged:
        if g["contigs_sha256"] in seen:
            warnings.append({"code": "comparison_identical_genomes",
                             "params": {"a": seen[g["contigs_sha256"]], "b": g["label"]}})
        seen.setdefault(g["contigs_sha256"], g["label"])
    if synthetic := [f"{g['label']}: {', '.join(g['synthetic_evidence'])}" for g in staged
                     if g.get("synthetic_evidence")]:
        warnings.append({"code": "synthetic_input", "params": {"evidence": "; ".join(synthetic)}})
    return warnings


def _tool_id(job_type: str, p: dict[str, Any]) -> str:
    return svc.ANI_METHODS[p["method"]]["tool"] if job_type == svc.ANI_JOB else svc.ALIGNERS[p["method"]]["tool"]


# --- ANI ----------------------------------------------------------------------------------------------------------

def _ani_body(ctx: JobContext) -> None:
    p = ctx.job.parameters
    cset = _set(ctx)
    method = p["method"]
    exe = _resolve_tool(ctx, svc.ANI_METHODS[method]["tool"])
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, results)
    (results / GENOME_LIST).write_text("".join(f"{g['file']}\n" for g in staged))
    by_file = {g["file"]: g["label"] for g in staged}
    labels = [g["label"] for g in staged]
    if method == "skani":
        params = SkaniParams(**p["settings"])
        argv = _check("skani", lambda: SkaniAdapter.triangle_argv(
            exe, params, Path(GENOME_LIST), Path("."), help_options(SkaniAdapter.triangle_help_text(exe))))
        _run_tool(ctx, "skani", argv, results, "skani_triangle.log")
        rows = _read("skani", results / skani_tool.TRIANGLE_OUTPUT, skani_tool.parse_output)
        pairs = [{"query": by_file[r["query"]], "reference": by_file[r["reference"]], "ani": r["ani"],
                  "af_query": r["af_query"], "af_reference": r["af_reference"]} for r in rows]
        directional = False
        log_text = (results / "skani_triangle.log").read_text(errors="replace")
        outputs = [results / skani_tool.TRIANGLE_OUTPUT, results / "skani_triangle.log"]
    else:
        params = FastaniParams(**p["settings"])
        argv = _check("FastANI", lambda: FastaniAdapter.all_vs_all_argv(
            exe, params, Path(GENOME_LIST), Path("."), fastani_tool.help_options(FastaniAdapter.help_text(exe))))
        _run_tool(ctx, "FastANI", argv, results, "fastani_all.log")
        rows = _read("FastANI", results / fastani_tool.ALL_OUTPUT, fastani_tool.parse_output)
        pairs = [{"query": by_file[r["query"]], "reference": by_file[r["reference"]], "ani": r["ani"],
                  "af_query": r["af"], "fragments_mapped": r["fragments_mapped"],
                  "fragments_total": r["fragments_total"]} for r in rows]
        directional = True
        log_text = ""
        outputs = [results / fastani_tool.ALL_OUTPUT, results / "fastani_all.log"]
    matrix = core.ani_matrix(labels, pairs, directional)
    order = core.similarity_order(matrix["ani"])
    n = len(staged)
    reported = sum(1 for x in pairs if x["query"] != x["reference"])
    missing = (n * (n - 1) if directional else n * (n - 1) // 2) - reported
    warnings = _warnings(ctx, staged)
    if missing:
        warnings.append({"code": "ani_pairs_not_reported", "params": {"count": missing, "tool": ctx.job.tool_name}})
    if method == "skani" and skani_tool.LEARNED in log_text:
        warnings.append({"code": "skani_learned_ani", "params": {}})
    if directional:
        warnings.append({"code": "fastani_directional", "params": {}})
    files = _files(ctx, [*outputs, results / GENOME_LIST])
    _cleanup_inputs(results)
    summary = {"matrix": matrix, "order": order, "pairs": pairs, "pairs_not_reported": missing,
               "similarity_note": svc.SIMILARITY_NOTE}
    _store(ctx, cset, "ani", method, staged, summary, warnings, files)
    ctx.log(f"{ctx.job.tool_name}: {reported} pair(s) reported, {missing} not reported; order "
            f"{', '.join(labels[i] for i in order['order'])} (similarity clustering, not a phylogeny)")


def _store(ctx: JobContext, cset: ComparisonSet, analysis: str, method: str, staged: list[dict[str, Any]],
           summary: dict[str, Any], warnings: list[dict[str, Any]], files: dict[str, Any]) -> None:
    job = ctx.job
    result = ComparisonResult(set_id=cset.id, job_id=job.id, analysis=analysis, method=method, tool=job.tool_name,
                              tool_version=job.tool_version, parameters=job.parameters.get("settings") or {},
                              genomes=_snapshot(staged), summary=summary, warnings=warnings, files=files)
    ctx.db.add(result)
    ctx.db.flush()
    job.result_summary = {"comparison_result_id": result.id, "set_id": cset.id, "analysis": analysis,
                          "method": method, "warnings": [w["code"] for w in warnings], "files": files}
    job.output_paths = [f["path"] for f in files.values()]


def run_comparative_ani_job(job_id: str) -> str:
    return run_job(job_id, _ani_body)


# --- Alignment ----------------------------------------------------------------------------------------------------

def _link(src: Path, dest: Path) -> None:
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)


def _align_pair(ctx: JobContext, method: str, exe: str, settings: dict[str, Any], ref: dict[str, Any],
                qry: dict[str, Any], results: Path, name: str) -> tuple[list[dict[str, Any]], list[Path]]:
    pairs = results / "pairs"
    if method == "minimap2":
        out = pairs / f"{name}.paf"
        argv = _check("minimap2", lambda: Minimap2Adapter.assembly_argv(
            exe, settings["preset"], settings["threads"], results / ref["file"], results / qry["file"], out))
        _run_tool(ctx, "minimap2", argv, pairs, f"{name}.minimap2.log")
        return _read("minimap2", out, parse_paf), [out, pairs / f"{name}.minimap2.log"]
    work = pairs / name
    work.mkdir()
    _link(results / ref["file"], work / "ref.fna")
    _link(results / qry["file"], work / "qry.fna")
    params = NucmerParams(**settings["nucmer"])
    argv = _check("NUCmer", lambda: NucmerAdapter.argv(exe, params, "pair", "ref.fna", "qry.fna"))
    _run_tool(ctx, "NUCmer", argv, work, "nucmer.log")
    show_coords = show_coords_path(exe)
    if show_coords is None:
        raise JobFailure("show-coords (MUMmer) is not installed next to nucmer", "tool_unavailable",
                         tool="show-coords", status="not_installed", message="")
    coords = work / "pair.coords"
    _run_tool(ctx, "show-coords", NucmerAdapter.coords_argv(show_coords, "pair.delta"), work, "show-coords.log",
              stdout=coords)
    for link in ("ref.fna", "qry.fna"):
        (work / link).unlink()
    return _read("show-coords", coords, parse_coords), [work / "pair.delta", coords, work / "nucmer.log"]


def _dnadiff(ctx: JobContext, exe: str, ref: dict[str, Any], qry: dict[str, Any], results: Path,
             name: str) -> tuple[dict[str, Any], list[Path]]:
    work = results / "dnadiff" / name
    work.mkdir(parents=True)
    _link(results / ref["file"], work / "ref.fna")
    _link(results / qry["file"], work / "qry.fna")
    _run_tool(ctx, "dnadiff", DnadiffAdapter.argv(exe, "dnadiff", "ref.fna", "qry.fna"), work, "dnadiff.log")
    for link in ("ref.fna", "qry.fna"):
        (work / link).unlink()
    report = _read("dnadiff", work / "dnadiff.report", DnadiffAdapter.parse_report)
    rdiff = _read("dnadiff", work / "dnadiff.rdiff", DnadiffAdapter.parse_diff)
    qdiff = _read("dnadiff", work / "dnadiff.qdiff", DnadiffAdapter.parse_diff)
    keep = [work / f"dnadiff.{s}" for s in (*COMPARISON_SUFFIXES, "snps")] + [work / "dnadiff.log"]
    for f in work.iterdir():
        if f not in keep:
            f.unlink()
    return {"reference": ref["label"], "query": qry["label"], "report": report,
            "reference_differences": rdiff, "query_differences": qdiff}, keep


def _compact(b: dict[str, Any]) -> list[Any]:
    return [b["ref"], b["ref_start"], b["ref_end"], b["query"], b["query_start"], b["query_end"], b["strand"],
            b["identity"], b["length"], b["primary"]]


def _alignment_body(ctx: JobContext) -> None:
    p = ctx.job.parameters
    cset = _set(ctx)
    method, settings = p["method"], p["settings"]
    exe = _resolve_tool(ctx, svc.ALIGNERS[method]["tool"])
    tools = [{"name": ctx.job.tool_name, "version": ctx.job.tool_version, "path": exe}]
    if method == "nucmer":
        tools.append({"name": "show-coords", "version": "MUMmer (same installation as nucmer)",
                      "path": show_coords_path(exe)})
    dd_exe = None
    if p.get("dnadiff"):
        d = detect("dnadiff", refresh=True)
        if d.path is None or d.status.value != "available":
            raise JobFailure(f"dnadiff is not available on this worker ({d.status.value}): {d.message}",
                             "tool_unavailable", tool="dnadiff", status=d.status.value, message=d.message)
        dd_exe = d.path
        tools.append({"name": d.info.name, "version": d.version, "path": d.path})
        ctx.log(f"dnadiff: {d.path} (version {d.version}"
                + (")" if d.version_validated else f"; WARNING: {d.message})"))
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, results)
    (results / "pairs").mkdir()
    pairs, outputs, summaries = [], [], []
    by_index = {g["index"]: g for g in staged}
    for i, j, role in svc.alignment_pairs(len(staged)):
        ref, qry = by_index[i], by_index[j]
        name = f"g{i + 1}_g{j + 1}"
        blocks, files = _align_pair(ctx, method, exe, settings, ref, qry, results, name)
        outputs += files
        used = [b for b in blocks if b["primary"]]
        summary = core.pair_summary(used, ref["total_length"], qry["total_length"])
        summaries.append({"reference": ref["label"], "query": qry["label"], "role": role, **summary,
                          "secondary_blocks": len(blocks) - len(used)})
        pairs.append({"reference": i, "query": j, "role": role, "blocks": [_compact(b) for b in blocks]})
        ctx.log(f"{ref['label']} vs {qry['label']} ({role}): {len(blocks)} blocks, reference "
                f"{summary['ref_fraction']} and query {summary['query_fraction']} aligned, identity "
                f"{summary['identity']} %")
        ctx.check_cancelled()
    reference = staged[0]
    window = core.auto_window(reference["total_length"])
    conservation = {"reference": reference["label"], "window": window, "genomes": [
        {"label": by_index[pr["query"]]["label"],
         "windows": core.conservation(reference["contigs"],
                                      [b for b in _blocks(pr) if b["primary"]], window)}
        for pr in pairs if pr["role"] == "reference"]}
    dnadiff = []
    if dd_exe:
        for j in range(1, len(staged)):
            entry, files = _dnadiff(ctx, dd_exe, reference, by_index[j], results, f"g1_g{j + 1}")
            dnadiff.append(entry)
            outputs += files
            rep = entry["report"]
            ctx.log(f"dnadiff {reference['label']} vs {by_index[j]['label']}: inversions "
                    f"{rep['reference'].get('inversions')}/{rep['query'].get('inversions')}, relocations "
                    f"{rep['reference'].get('relocations')}/{rep['query'].get('relocations')}, translocations "
                    f"{rep['reference'].get('translocations')}/{rep['query'].get('translocations')}")
            ctx.check_cancelled()
    data = {"genomes": [{"label": g["label"], "assembly_id": g["assembly_id"], "sample_id": g["sample_id"],
                         "contigs": g["contigs"], "total_length": g["total_length"]} for g in staged],
            "reference": 0, "method": method, "pairs": pairs, "conservation": conservation}
    (results / "alignment.json").write_text(json.dumps(data, separators=(",", ":")))
    warnings = _warnings(ctx, staged)
    if method == "minimap2" and any(s["secondary_blocks"] for s in summaries):
        warnings.append({"code": "minimap2_secondary", "params": {}})
    if method == "nucmer":
        warnings.append({"code": "nucmer_all_blocks", "params": {}})
    files = _files(ctx, [results / "alignment.json", *outputs])
    _cleanup_inputs(results)
    _store(ctx, cset, "alignment", method, staged,
           {"reference": reference["label"], "order": [g["label"] for g in staged], "pairs": summaries,
            "window": window, "dnadiff": dnadiff, "tools": tools}, warnings, files)


def _blocks(pr: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("ref", "ref_start", "ref_end", "query", "query_start", "query_end", "strand", "identity", "length",
            "primary")
    return [dict(zip(keys, b, strict=True)) for b in pr["blocks"]]


def run_comparative_alignment_job(job_id: str) -> str:
    return run_job(job_id, _alignment_body)
