"""Worker task for the species-specific typing steps (app.services.typing_modules): for S. aureus, SCCmec with
sccmec, spa with spaTyper and agr with AgrVATE.

Before the run the worker checks again what the user confirmed: the assembly's contigs (SHA-256), and the data the
step reads (the registered Ridom files: the same record, version, checksum and folder; or the data bundled with the
tool: the same checksum). The contigs are staged as input/contigs.fasta (names kept, descriptions removed, upper case);
outputs and logs stay in the job's results folder. The call becomes one typing_results row.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import agrvate as ag
from arva_tools import sccmec as sc
from arva_tools import spatyper as sp

from app.models import Assembly, ReferenceDatabase, TypingResult
from app.services import annotation as annotation_svc
from app.services import staph_typing as svc
from app.services.databases import USABLE
from app.tasks.annotation import _assembly
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.tools import _rel, _resolve_tool, _run, _sha256

INPUT = "contigs.fasta"


def stage_upper(src: Path, dest: Path) -> dict[str, Any]:
    """The contigs as stage_genome writes them, then upper-cased when any base is lower case (spaTyper compares
    repeats case-sensitively); the returned sha256 is the staged file's."""
    staged = annotation_svc.stage_genome(src, dest, False)
    lines = dest.read_text().splitlines(keepends=True)
    if any(not ln.startswith(">") and ln != ln.upper() for ln in lines):
        dest.write_text("".join(ln if ln.startswith(">") else ln.upper() for ln in lines))
        return {**staged, "sha256": _sha256(dest), "uppercased": True}
    return {**staged, "uppercased": False}


def _argv(method: str, build) -> list[str]:
    try:
        return build()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"{svc.NAMES[method]}'s help could not be read to check its options: {exc}",
                         "help_unreadable", tool=svc.NAMES[method], detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"{svc.NAMES[method]} cannot run with these settings: {exc}", "settings_rejected",
                         tool=svc.NAMES[method], detail=str(exc)) from exc


def _read(method: str, path: Path, parse):
    if not path.is_file():
        raise JobFailure(f"{svc.NAMES[method]} exited without an error but did not write {path.name}",
                         "outputs_missing", tool=svc.NAMES[method], files=path.name)
    try:
        return parse(path.read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"{svc.NAMES[method]}'s output cannot be read: {exc}", "output_unreadable",
                         tool=svc.NAMES[method], detail=str(exc)) from exc


def _run_tool(ctx: JobContext, method: str, argv: list[str], workdir: Path, log: str, stdout: Path,
              env: dict[str, str]) -> ToolExecutionError | None:
    """Run the step; a non-zero exit with a known reason fails the job with it. AgrVATE exits 1 after writing its
    summary in some cases: the error is returned so that the summary can still be read."""
    try:
        _run(ctx, argv, workdir, log, stdout=stdout, extra_env=env)
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError):
            raise
        text = "".join(p.read_text(errors="replace") for p in (workdir / log, stdout) if p.is_file())
        if (reason := svc.ADAPTERS[method].failure_reason(text)) is not None:
            raise JobFailure(reason, "tool_stopped", tool=svc.NAMES[method], detail=reason) from None
        if method == "agr" and ag.outputs(workdir)["summary"].is_file():
            return exc
        raise
    return None


def _bundled(ctx: JobContext, method: str, exe: str) -> dict[str, Any]:
    data = svc.bundled(method, exe)
    if data is None or data["checksum"] != ctx.job.database_checksum:
        raise JobFailure(f"The data bundled with {svc.NAMES[method]} are not the recorded ones (was its environment "
                         "rebuilt?)", "bundled_database_changed", name=str(ctx.job.database_name))
    ctx.log(f"Data: {data['name']} at {data['path']}, checksum {data['checksum']}")
    return data


def _ridom(ctx: JobContext) -> ReferenceDatabase:
    job = ctx.job
    record = ctx.db.get(ReferenceDatabase, job.reference_database_id) if job.reference_database_id else None
    if record is None or record.status not in USABLE:
        raise JobFailure(f"The Ridom files {job.database_name} {job.database_version} are no longer registered",
                         "database_missing", name=str(job.database_name), version=str(job.database_version))
    if record.checksum != job.database_checksum or record.version != job.database_version \
            or record.path != job.database_path:
        raise JobFailure("The Ridom files' checksum, version or folder changed since the run was confirmed; start "
                         "spa typing again", "database_changed", name=str(job.database_name))
    ctx.log(f"Ridom SpaServer files: {record.name} {record.version} at {record.path} (registered by the user; "
            "ARVA neither ships nor copies them)")
    return record


def _sccmec(ctx: JobContext, exe: str, params: sc.SccmecParams, contigs: Path, results: Path) -> dict[str, Any]:
    data = _bundled(ctx, "sccmec", exe)
    argv = _argv("sccmec", lambda: sc.SccmecAdapter.argv(exe, params, contigs, results,
                                                          sc.SccmecAdapter.help_options(exe)))
    _run_tool(ctx, "sccmec", argv, results, sc.LOG, results / "sccmec.stdout.log", sc.env_for(exe))
    files = sc.outputs(results)
    result = _read("sccmec", files["result"], sc.parse_result)
    targets = _read("sccmec", files["targets_details"], sc.parse_target_details)
    regions = _read("sccmec", files["regions_details"], sc.parse_region_details)
    blast = _read("sccmec", files["targets_blast"], sc.parse_blast)
    try:
        schema = sc.read_schema(exe, sc.schema_files(exe)[0])
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"sccmec's targets schema could not be read: {exc}", "output_unreadable", tool="sccmec",
                         detail=str(exc)) from exc
    call = sc.interpret(result)
    groups = sc.complexes(result["targets"], schema)
    warnings = [{"code": "sccmec_mecA_includes_mecC", "params": {}}]
    if call["status"] in ("type_only", "mec_without_type", "multiple"):
        warnings.append({"code": f"sccmec_{call['status']}", "params": {}})
    elif call["status"] == "multiple_subtypes":
        warnings.append({"code": "sccmec_multiple_subtypes", "params": {"subtypes": ", ".join(result["regions"])}})
    details = {**result, "ccr_complexes": groups["ccr"], "mec_classes": groups["mec"],
               "target_hits": sc.target_hits(blast, params.min_targets_pident, params.min_targets_coverage),
               "types_considered": targets,
               "regions_considered": sorted(regions, key=lambda r: -(r["coverage"] or 0))[:10],
               "bundled": {k: data[k] for k in ("name", "checksum", "files")}}
    return {**call, "details": details, "warnings": warnings,
            "files": [*files.values(), results / sc.LOG]}


def _spa(ctx: JobContext, exe: str, params: sp.SpaParams, contigs: Path, results: Path) -> dict[str, Any]:
    record = _ridom(ctx)
    folder = Path(record.path or "")
    try:
        checksums, counts = sp.file_checksums(folder), sp.count_entries(folder)
    except OSError as exc:
        raise JobFailure(f"The Ridom files cannot be read: {exc}", "database_unreadable", name=record.name) from exc
    argv = _argv("spa", lambda: sp.SpatyperAdapter.argv(exe, params, contigs, folder, results,
                                                         sp.SpatyperAdapter.help_options(exe)))
    _run_tool(ctx, "spa", argv, results, "spatyper.stderr.log", results / sp.LOG, sp.env_for(exe))
    rows = _read("spa", results / sp.OUTPUT, sp.parse_output)
    call = sp.interpret(rows)
    warnings = [{"code": "spa_files_version", "params": {"version": record.version or "?"}}]
    if call["status"] != "typed":
        warnings.append({"code": f"spa_{call['status']}", "params": {}})
    details = {"repeats": call["repeats"], "spa_type": call["call"], "rows": rows,
               "ridom_files": {"name": record.name, "version": record.version, "sha256": checksums, **counts}}
    return {**call, "details": details, "warnings": warnings,
            "files": [results / sp.OUTPUT, results / sp.LOG, results / "spatyper.stderr.log"]}


def _agr(ctx: JobContext, exe: str, params: ag.AgrParams, contigs: Path, results: Path) -> dict[str, Any]:
    data = _bundled(ctx, "agr", exe)
    work = results / "agrvate"
    work.mkdir()
    shutil.copy(contigs, work / ag.INPUT)
    argv = _argv("agr", lambda: ag.AgrvateAdapter.argv(exe, params, ag.AgrvateAdapter.help_options(exe)))
    error = _run_tool(ctx, "agr", argv, work, ag.LOG, work / "agrvate.stdout.log", ag.env_for(exe))
    out = ag.outputs(work)
    summary = _read("agr", out["summary"], ag.parse_summary)
    report = _read("agr", out["error_report"], ag.parse_error_report) if out["error_report"].is_file() else {}
    variants = _read("agr", out["variants"], ag.parse_variants) if out["variants"].is_file() else []
    alignment = _read("agr", out["coords"], ag.parse_coords) if out["coords"].is_file() else None
    call = ag.interpret(summary)
    warnings = [{"code": "agr_mummer_mode", "params": {}}, {"code": "agr_snippy_threads", "params": {}}]
    if call["status"] in ("low_confidence", "multiple", "untypeable"):
        warnings.append({"code": f"agr_{call['status']}", "params": {"score": summary["match_score"]}})
    if summary["canonical_agrD"] == "possible_non_canonical":
        warnings.append({"code": "agr_non_canonical_agrD", "params": {}})
    if alignment and alignment["covered_fraction"] is not None and alignment["covered_fraction"] < 1:
        warnings.append({"code": "agr_operon_partial",
                         "params": {"percent": f"{alignment['covered_fraction'] * 100:.1f}"}})
    if summary["frameshifts"] is None:
        warnings.append({"code": "agr_frameshifts_not_determined", "params": {}})
    if error is not None:
        failed = ", ".join(k for k, v in report.items() if v == "fail") or "?"
        warnings.append({"code": "agr_exit_status", "params": {"status": error.returncode or "?", "check": failed}})
    details = {**summary, "variants": variants, "operon_alignment": alignment, "checks": report, "mode": params.mode,
               "bundled": {k: data[k] for k in ("name", "checksum")}}
    return {**call, "details": details, "warnings": warnings,
            "files": [*out.values(), work / ag.LOG, work / "agrvate.stdout.log"]}


def _body(ctx: JobContext) -> None:
    p = ctx.job.parameters or {}
    method = p["method"]
    spec = svc.METHODS[method]
    exe = _resolve_tool(ctx, spec["tool"])
    params = spec["params"](**{k: v for k, v in (p.get("settings") or {}).items()
                               if k in spec["params"].__dataclass_fields__})
    a: Assembly = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    (results / "input").mkdir(parents=True)
    contigs = results / "input" / INPUT
    staged = stage_upper(ctx.path(a.contigs_path), contigs)
    ctx.log(f"Input: {len(staged['contigs'])} contigs, {staged['total_length']:,} bp, written as input/{INPUT} "
            f"(sha256 {staged['sha256']}{', upper-cased' if staged['uppercased'] else ''})")
    runner = {"sccmec": _sccmec, "spa": _spa, "agr": _agr}[method]
    out = runner(ctx, exe, params, contigs, results)
    job = ctx.job
    warnings = list(out["warnings"])
    if staged["uppercased"]:
        warnings.append({"code": "uppercased_input", "params": {}})
    if not job.tool_version or job.tool_version not in svc.ADAPTERS[method].info.tested_versions:
        warnings.append({"code": "tool_not_validated", "params": {"tool": svc.NAMES[method],
                                                                  "version": job.tool_version}})
    if p.get("override"):
        warnings.append({"code": "applicability_overridden",
                         "params": {"status": (p.get("applicability") or {}).get("status", "?")}})
    if evidence := p.get("synthetic_evidence"):
        warnings.append({"code": "synthetic_input", "params": {"evidence": ", ".join(evidence)}})
    files = {_rel(ctx, f).split(f"{ctx.results_rel}/", 1)[1]: {"path": _rel(ctx, f), "sha256": _sha256(f),
                                                               "size_bytes": f.stat().st_size}
             for f in out["files"] if f.is_file()}
    files["input"] = {"path": _rel(ctx, contigs), "sha256": staged["sha256"], "size_bytes": contigs.stat().st_size}
    result = TypingResult(
        sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, module=p["module"], method=method,
        tool=job.tool_name, tool_version=job.tool_version, database_kind=job.database_kind,
        database_name=job.database_name, database_version=job.database_version,
        database_checksum=job.database_checksum, parameters=p.get("settings") or {}, status=out["status"],
        call=out["call"], details=out["details"], applicability=p.get("applicability") or {}, warnings=warnings,
        files=files)
    ctx.db.add(result)
    ctx.db.flush()
    ctx.log(f"{svc.NAMES[method]}: {out['status']}" + (f", {out['call']}" if out["call"] else "")
            + (f"; warnings: {', '.join(w['code'] for w in warnings)}" if warnings else ""))
    job.result_summary = {"typing_result_id": result.id, "method": method, "status": out["status"],
                          "call": out["call"], "warnings": [w["code"] for w in warnings], "files": files}
    job.output_paths = [f["path"] for f in files.values()]


def run_typing_job(job_id: str) -> str:
    return run_job(job_id, _body)
