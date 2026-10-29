"""Worker task for AMR detection with AMRFinderPlus.

Before the run the worker checks again what the user confirmed: the assembly's contigs (SHA-256), the database (same
record, version, content checksum and folder, and AMRFinderPlus's own --database_version check) and, for a combined
search, the annotation's contigs, proteins and GFF (the SHA-256 recorded when the annotation was made). Outputs, the
log and the temporary folder stay in the job's results folder; the temporary folder is removed afterwards. Each
element AMRFinderPlus reports becomes one amr_results row; the run's own facts go to the job.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import amrfinderplus as amr_tool
from arva_tools.amrfinderplus import OUTPUTS, AmrfinderplusAdapter, AmrParams
from sqlalchemy import select

from app.models import AmrResult, Annotation, ReferenceDatabase
from app.services import amr as svc
from app.services import annotation as annotation_svc
from app.services.databases import USABLE
from app.tasks.annotation import INPUT_NAME, _assembly
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.tools import _rel, _resolve_tool, _run, _sha256

TMP_DIR = "tmp"


def _database(ctx: JobContext, exe: str) -> Path:
    job = ctx.job
    record = ctx.db.get(ReferenceDatabase, job.reference_database_id) if job.reference_database_id else None
    if record is None or record.status not in USABLE:
        raise JobFailure(f"The database {job.database_name} {job.database_version} is no longer installed",
                         "database_missing", name=str(job.database_name), version=str(job.database_version))
    if record.checksum != job.database_checksum or record.version != job.database_version \
            or record.path != job.database_path:
        raise JobFailure("The database's content checksum, version or folder changed since the run was confirmed; "
                         "start AMR detection again", "database_changed", name=str(job.database_name))
    folder = Path(record.path or "")
    check = amr_tool.database_check(exe, folder)
    if not check["ok"] or check["version"] != record.version:
        raise JobFailure(f"AMRFinderPlus refuses the database {record.name} {record.version}: "
                         f"{check['error'] or 'its version.txt changed'}", "amr_database_refused",
                         name=record.name, detail=str(check["error"] or ""))
    source = record.version_source.value if record.version_source else "unknown"
    ctx.log(f"Database: {record.name} {record.version} (version from {source}; AMRFinderPlus {check['software']} "
            f"accepts it) at {folder}, content checksum {record.checksum or 'not computed (quick verification only)'}")
    return folder


def _annotation(ctx: JobContext, annotation_id: str, assembly_id: str) -> tuple[Annotation, dict[str, Path]]:
    an = ctx.db.get(Annotation, annotation_id)
    if an is None or an.assembly_id != assembly_id:
        raise JobFailure("The annotation chosen for the combined search no longer exists", "annotation_missing")
    paths = {}
    for kind in ("fna", "faa", "gff3"):
        entry = (an.files or {}).get(kind) or {}
        path = ctx.path(entry.get("path") or "")
        if not path.is_file() or _sha256(path) != entry.get("sha256"):
            raise JobFailure(f"The annotation's {kind} file is missing or changed since it was written",
                             "annotation_changed", file=kind)
        paths[kind] = path
    ctx.log(f"Combined search with the {an.tool} {an.tool_version} annotation {an.id}: its contigs (.fna), proteins "
            f"(.faa) and GFF3, unchanged since the annotation (SHA-256 checked)")
    return an, paths


def _link(features: list[dict[str, Any]], hit: dict[str, Any], contig: str | None, an: Annotation | None,
          combined: bool) -> dict[str, Any] | None:
    if an is None:
        return None
    if combined and hit["protein_id"]:
        f = next((f for f in features if hit["protein_id"] in (f.get("locus_tag"), f.get("tool_id"))), None)
        if f is not None:
            return {"annotation_id": an.id, "feature_id": f["id"], "locus_tag": f.get("locus_tag"),
                    "gene": f.get("gene"), "product": f.get("product"), "how": "protein_id", "overlap": None}
    if contig is None or hit["start"] is None or hit["stop"] is None:
        return None
    return svc.link_feature(features, contig, hit["start"], hit["stop"], hit["strand"], an.id)


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {"total": len(rows), "AMR": 0, "VIRULENCE": 0, "STRESS": 0, "point_mutations": 0, "incomplete": 0}
    for r in rows:
        out[r["type"]] = out.get(r["type"], 0) + 1
        out["point_mutations"] += r["subtype"] in ("POINT", "POINT_DISRUPT")
        out["incomplete"] += r["method_info"]["kind"] in ("partial", "contig_end", "internal_stop", "frameshift",
                                                          "extended")
    return out


def _body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "amrfinderplus")
    p = ctx.job.parameters or {}
    params = AmrParams(**{k: p[k] for k in AmrParams.__dataclass_fields__})
    db_path = _database(ctx, exe)
    a = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    (results / "input").mkdir(parents=True)
    combined = params.mode == "combined"
    an, inputs = (None, {})
    if combined:
        an, inputs = _annotation(ctx, p["annotation_id"], a.id)
        nucleotide = inputs["fna"]
        to_assembly = {s["id"]: s.get("original_id") or s["id"] for s in an.sequences}
        input_files = {k: {"path": _rel(ctx, v), "sha256": _sha256(v), "size_bytes": v.stat().st_size}
                       for k, v in inputs.items()}
    else:
        staged = annotation_svc.stage_genome(ctx.path(a.contigs_path), results / "input" / INPUT_NAME, False)
        nucleotide = results / "input" / INPUT_NAME
        to_assembly = {c["name"]: c["original_name"] for c in staged["contigs"]}
        input_files = {"input": {"path": _rel(ctx, nucleotide), "sha256": staged["sha256"],
                                 "size_bytes": nucleotide.stat().st_size}}
        ctx.log(f"Input: {len(staged['contigs'])} contigs, {staged['total_length']:,} bp, written as "
                f"input/{INPUT_NAME} (sha256 {staged['sha256']})")
    tmp = results / TMP_DIR
    tmp.mkdir()
    try:
        help_text = AmrfinderplusAdapter.help_text(exe)
        argv = AmrfinderplusAdapter.argv(exe, params, nucleotide, results, db_path, amr_tool.parse_help_options(
            help_text), inputs.get("faa"), inputs.get("gff3"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"AMRFinderPlus's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="AMRFinderPlus", detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"AMRFinderPlus cannot run with these settings: {exc}",
                         "settings_rejected", tool="AMRFinderPlus", detail=str(exc)) from exc
    defaults = amr_tool.help_defaults(help_text)
    if defaults != amr_tool.DEFAULTS:
        ctx.log(f"Note: this AMRFinderPlus's --help states the defaults {defaults}; ARVA passes every option "
                "explicitly")
    log_path = results / OUTPUTS["log"]
    try:
        _run(ctx, argv, results, log_path.name, extra_env=amr_tool.env_for(exe, tmp))
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError):
            raise
        reason = amr_tool.failure(log_path.read_text(errors="replace") if log_path.is_file() else "")
        if reason is None:
            raise
        raise JobFailure(f"AMRFinderPlus stopped: {reason}", "amrfinder_stopped", detail=reason) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    outputs = {k: results / name for k, name in OUTPUTS.items()}
    if not outputs["report"].is_file():
        raise JobFailure("AMRFinderPlus exited without an error but did not write its report", "outputs_missing",
                         tool="AMRFinderPlus", files=OUTPUTS["report"])
    try:
        rows = amr_tool.parse_report(outputs["report"].read_text(errors="replace"))
        screen = amr_tool.point_mutation_screen(amr_tool.parse_report(outputs["mutation_all"].read_text(
            errors="replace"))) if params.organism and outputs["mutation_all"].is_file() else None
    except ValueError as exc:
        raise JobFailure(f"AMRFinderPlus's report cannot be read: {exc}", "output_unreadable", tool="AMRFinderPlus",
                         detail=str(exc)) from exc
    log = amr_tool.parse_stderr(log_path.read_text(errors="replace"))
    if log["database_version"] != ctx.job.database_version:
        raise JobFailure(f"AMRFinderPlus read database {log['database_version']}, not the recorded "
                         f"{ctx.job.database_version}", "database_changed", name=str(ctx.job.database_name))
    link_to = an
    if link_to is None:
        link_to = ctx.db.scalars(select(Annotation).where(Annotation.assembly_id == a.id)
                                 .order_by(Annotation.created_at.desc())).first()
    features = [f for f in annotation_svc.features_of(link_to) if f["type"] in ("cds", "sorf")] if link_to else []
    by_assembly = {s.get("original_id") or s["id"]: s["id"] for s in link_to.sequences} if link_to else {}
    job = ctx.job
    for r in rows:
        assembly_contig = to_assembly.get(r["contig"] or "", r["contig"])
        feature_contig = r["contig"] if combined else by_assembly.get(assembly_contig or "")
        ctx.db.add(AmrResult(
            sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, annotation_id=an.id if an else None,
            element_symbol=r["element_symbol"] or "", element_name=r["element_name"], scope=r["scope"],
            type=r["type"] or "", subtype=r["subtype"], amr_class=r["class"], amr_subclass=r["subclass"],
            method=r["method"] or "", method_kind=r["method_info"]["kind"], identity=r["identity"],
            coverage=r["coverage"], target_length=r["target_length"], reference_length=r["reference_length"],
            alignment_length=r["alignment_length"], contig=r["contig"], assembly_contig=assembly_contig,
            start=r["start"], stop=r["stop"], strand=r["strand"], protein_id=r["protein_id"],
            closest_accession=r["closest_accession"], closest_name=r["closest_name"],
            hmm_accession=r["hmm_accession"], hmm_description=r["hmm_description"],
            hierarchy_node=r.get("hierarchy_node"), feature=_link(features, r, feature_contig, link_to, combined),
        ))
    warnings = amr_tool.warnings(params, rows, screen)
    if evidence := p.get("synthetic_evidence"):
        warnings.append({"code": "synthetic_input", "params": {"evidence": ", ".join(evidence)}})
    files = {k: {"path": _rel(ctx, f), "sha256": _sha256(f), "size_bytes": f.stat().st_size}
             for k, f in outputs.items() if f.is_file()}
    counts = _counts(rows)
    ctx.log(f"AMRFinderPlus ({log['search']} search): {counts['total']} elements: {counts['AMR']} AMR "
            f"({counts['point_mutations']} point mutations), {counts['VIRULENCE']} virulence, {counts['STRESS']} stress"
            + (f"; {counts['incomplete']} partial, at a contig end or with an internal stop" if counts["incomplete"]
               else "") + (f"; organism {params.organism}" if params.organism else "; no organism: point mutations "
                                                                                    "not searched"))
    job.result_summary = {"counts": counts, "warnings": warnings, "point_mutation_screen": screen, "log": log,
                          "files": files, "inputs": input_files, "linked_annotation_id": link_to.id if link_to
                          else None, "tool_defaults": defaults}
    job.output_paths = [f["path"] for f in files.values()] + [v["path"] for v in input_files.values()
                                                             if v["path"].startswith(ctx.results_rel)]


def run_amr_job(job_id: str) -> str:
    return run_job(job_id, _body)
