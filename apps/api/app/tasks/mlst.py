"""Worker task for MLST with mlst.

Before the run the worker checks again what the user confirmed: the assembly's contigs (SHA-256) and the bundled
database (the same folder next to the mlst that runs, the same content checksum). mlst's outputs, its log and its
temporary files stay in the job's results folder; the temporary folder is removed afterwards.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import mlst as mlst_tool
from arva_tools.base import help_options
from arva_tools.mlst import OUTPUTS, MlstAdapter, MlstParams

from app.models import Assembly, DatabaseStatus, MlstResult, ReferenceDatabase
from app.services import annotation as annotation_svc
from app.services import mlst as svc
from app.tasks.annotation import INPUT_NAME, _assembly
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.tools import _rel, _resolve_tool, _run, _sha256

TMP_DIR = "tmp"


def _database(ctx: JobContext, exe: str) -> Path:
    job = ctx.job
    record = ctx.db.get(ReferenceDatabase, job.reference_database_id) if job.reference_database_id else None
    folder = mlst_tool.database_dir(exe)
    if record is None or record.status is not DatabaseStatus.registered or record.path != str(folder):
        raise JobFailure(f"The schemes bundled with mlst are not the recorded ones (expected {job.database_path}, "
                         f"mlst now reads {folder})", "mlst_database_changed", name=str(job.database_name))
    checksum = svc.content_checksum(folder)
    if checksum != job.database_checksum:
        raise JobFailure(f"The bundled schemes changed since the run was confirmed (checksum {checksum}, recorded "
                         f"{job.database_checksum}); start MLST again", "mlst_database_changed",
                         name=str(job.database_name))
    ctx.log(f"Database: {record.name}, schemes downloaded {record.version} (version from the schemes' info files), "
            f"at {folder}, content checksum {checksum}")
    return folder


def _clonal_complex(db: Path, row: dict[str, Any], scheme_info: dict[str, Any] | None) -> dict[str, Any]:
    if row["scheme"] is None:
        return {"available": False, "column": None, "value": None, "reason": "no_scheme"}
    found = mlst_tool.clonal_complex(db, row["scheme"], row["st"] or "")
    if not found["available"]:
        return {**found, "reason": "not_in_scheme"}
    if row["st"] is None:
        return {**found, "reason": "no_st"}
    return {**found, "reason": None if found["value"] else "empty_for_st"}


def _body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "mlst")
    p = ctx.job.parameters or {}
    params = MlstParams(**{k: p[k] for k in MlstParams.__dataclass_fields__})
    db = _database(ctx, exe)
    a: Assembly = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    (results / "input").mkdir(parents=True)
    staged = annotation_svc.stage_genome(ctx.path(a.contigs_path), results / "input" / INPUT_NAME, False)
    ctx.log(f"Input: {len(staged['contigs'])} contigs, {staged['total_length']:,} bp, written as input/{INPUT_NAME} "
            f"(sha256 {staged['sha256']})")
    tmp = results / TMP_DIR
    tmp.mkdir()
    try:
        help_text = MlstAdapter.help_text(exe)
        argv = MlstAdapter.argv(exe, params, results / "input" / INPUT_NAME, results, db,
                                help_options(help_text))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"mlst's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="mlst", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"mlst cannot run with these settings: {exc}",
                         "settings_rejected", tool="mlst", detail=str(exc)) from exc
    defaults = mlst_tool.help_defaults(help_text)
    if defaults != mlst_tool.DEFAULTS:
        ctx.log(f"Note: this mlst's --help states the defaults {defaults}; ARVA passes every option explicitly")
    log_path = results / OUTPUTS["log"]
    try:
        _run(ctx, argv, results, log_path.name, extra_env=mlst_tool.env_for(exe, tmp))
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError):
            raise
        errors = mlst_tool.parse_stderr(log_path.read_text(errors="replace") if log_path.is_file() else "")["errors"]
        if not errors:
            raise
        raise JobFailure(f"mlst stopped: {errors[-1]}", "mlst_stopped", detail=errors[-1]) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    outputs = {k: results / name for k, name in OUTPUTS.items()}
    if missing := [k for k in mlst_tool.REQUIRED_OUTPUTS if not outputs[k].is_file()]:
        raise JobFailure("mlst exited without an error but did not write " + ", ".join(missing),
                         "outputs_missing", tool="mlst", files=", ".join(missing))
    try:
        rows = mlst_tool.parse_full(outputs["tsv"].read_text(errors="replace"))
        mlst_tool.check_json(rows, outputs["json"].read_text(errors="replace"))
        if len(rows) != 1:
            raise ValueError(f"{len(rows)} result lines for one input")
    except ValueError as exc:
        raise JobFailure(f"mlst's output cannot be read: {exc}", "output_unreadable", tool="mlst",
                         detail=str(exc)) from exc
    row = rows[0]
    log = mlst_tool.parse_stderr(log_path.read_text(errors="replace"))
    novel = mlst_tool.parse_novel(outputs["novel"].read_text(errors="replace")) if outputs["novel"].is_file() else []
    info = mlst_tool.database_info(db)
    scheme_info = next((s for s in info["schemes"] if s["name"] == row["scheme"]), None)
    warnings = mlst_tool.warnings(row, log, params.scheme is not None)
    if scheme_info and (scheme_info["last_updated"] or "") > mlst_tool.PUBMLST_OPEN_UNTIL:
        warnings.append({"code": "scheme_after_open_terms", "params": {"scheme": row["scheme"],
                                                                        "last_updated": scheme_info["last_updated"]}})
    if evidence := p.get("synthetic_evidence"):
        warnings.append({"code": "synthetic_input", "params": {"evidence": ", ".join(evidence)}})
    files = {k: {"path": _rel(ctx, f), "sha256": _sha256(f), "size_bytes": f.stat().st_size}
             for k, f in outputs.items() if f.is_file()}
    files["input"] = {"path": _rel(ctx, results / "input" / INPUT_NAME), "sha256": staged["sha256"],
                      "size_bytes": (results / "input" / INPUT_NAME).stat().st_size}
    job = ctx.job
    result = MlstResult(
        sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, tool="mlst", tool_version=job.tool_version,
        database_key=job.database_key, database_name=job.database_name, database_version=job.database_version,
        database_checksum=job.database_checksum,
        parameters=dict(p),
        scheme=row["scheme"], st=row["st"], status=row["status"], score=row["score"], alleles=row["alleles"],
        clonal_complex=_clonal_complex(db, row, scheme_info), warnings=warnings,
        details={"log": log, "novel_alleles": novel, "scheme": scheme_info, "tool_defaults": defaults,
                 "input": {k: staged[k] for k in ("sha256", "total_length", "non_n_bases")},
                 "contigs": len(staged["contigs"])},
        files=files,
    )
    ctx.db.add(result)
    ctx.db.flush()
    calls = " ".join(f"{x['locus']}({x['call']})" for x in row["alleles"])
    ctx.log(f"mlst: scheme {row['scheme'] or '-'}, ST {row['st'] or '-'}, {row['status']}, score {row['score']}"
            + (f": {calls}" if calls else "") + (f"; warnings: {', '.join(w['code'] for w in warnings)}"
                                                 if warnings else ""))
    job.result_summary = {"mlst_result_id": result.id, "scheme": row["scheme"], "st": row["st"],
                          "status": row["status"], "score": row["score"], "warnings": [w["code"] for w in warnings]}
    job.output_paths = [f["path"] for f in files.values()]


def run_mlst_job(job_id: str) -> str:
    return run_job(job_id, _body)
