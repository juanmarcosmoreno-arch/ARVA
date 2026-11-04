"""What each workflow node kind does inside ARVA: its parameter model, how a source picks existing data, how a node
is launched, and what it produced.

A node is launched by calling the API action of the same analysis (the function behind its POST route) with a
request built from the node's parameters and the outputs of the nodes it reads. Every check those actions make
(input files, sequencing technology, databases, tool options, Bakta's skipped steps) therefore applies unchanged,
and every job is an ordinary analysis job. The confirmations the dialogs ask for are given by the person who
confirms the run; the provenance of each item records that.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from arva_core import workflow as core
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    AssemblyKind,
    ComparisonResult,
    ComparisonSet,
    FileFormat,
    FileOrigin,
    JobStatus,
    MlstResult,
    RawFile,
    Sample,
    SequencingTechnology,
    SpeciesResult,
)
from app.schemas import schemas as s

PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
FASTQ = (FileFormat.fastq, FileFormat.fastq_gz)


class LaunchRefused(Exception):
    """The analysis's own checks refused the request (or a source found no data): never retried automatically."""

    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message)
        self.code = code
        self.params = params


class NodeSkipped(Exception):
    """The step does not apply to this sample (e.g. S. aureus typing of another species): the item is skipped with
    this reason, which the run records; it is not a failure."""

    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message)
        self.code = code
        self.params = params


class WaitForFollowUp(Exception):
    """The job finished but its result comes from a job it queued (Racon then Pilon), which is still active.

    required=False: the step's result stands without it (the filtered reads' statistics, waited for only so that Flye's
    memory estimate can read their bases); if its task is lost, the step completes instead of failing."""

    def __init__(self, follow: AnalysisJob, required: bool = True):
        super().__init__(follow.id)
        self.follow = follow
        self.required = required


@dataclass
class LaunchContext:
    db: Session
    sample: Sample | None
    project_id: str
    params: dict[str, Any]
    inputs: dict[str, Any]
    threads: int
    memory_gb: int
    run_name: str
    # What ARVA decided for this launch beyond the node's parameters (Flye's memory guard), recorded on the item.
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Kind:
    model: type[BaseModel]
    # Top-level request fields ARVA fills from inputs and the run's confirmation (not node parameters).
    bound: tuple[str, ...] = ()
    placeholders: dict[str, Any] = field(default_factory=dict)
    launch: Callable[[LaunchContext], Any] | None = None
    outputs: Callable[[Session, AnalysisJob], dict[str, Any]] | None = None
    # Where the thread count goes in the request ("threads" or "params.threads"); None: the node takes none.
    threads_at: str | None = "threads"


def _response_error(resp: Response) -> LaunchRefused:
    try:
        body = json.loads(bytes(resp.body))
    except (TypeError, ValueError):
        body = {}
    return LaunchRefused(body.get("code") or "wf_launch_refused", str(body.get("detail") or resp.status_code),
                         **(body.get("params") or {}))


def call(fn: Callable[..., Any], *args: Any) -> AnalysisJob:
    """Run an API action and return its job, or raise LaunchRefused with the action's own reason."""
    try:
        out = fn(*args)
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            raise LaunchRefused(detail.get("code") or "wf_launch_refused", str(detail.get("detail") or detail),
                                **(detail.get("params") or {})) from exc
        raise LaunchRefused("wf_launch_refused", str(detail)) from exc
    except ValidationError as exc:
        raise LaunchRefused("wf_params_invalid", _errors_text(exc)) from exc
    if isinstance(out, Response):
        raise _response_error(out)
    if isinstance(out, list):
        out = out[0]
    return out


def _errors_text(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())


def _request(ctx: LaunchContext, kind: str, filled: dict[str, Any]) -> BaseModel:
    spec = KINDS[kind]
    body = {**ctx.params, **filled}
    if spec.threads_at == "threads" and body.get("threads") is None:
        body["threads"] = ctx.threads
    elif spec.threads_at == "params.threads":
        body["params"] = {**body.get("params", {})}
        if body["params"].get("threads") is None:
            body["params"]["threads"] = ctx.threads
    try:
        return spec.model.model_validate(body)
    except ValidationError as exc:
        raise LaunchRefused("wf_params_invalid", _errors_text(exc)) from exc


# --- outputs -------------------------------------------------------------------------------------------------------

def _derived_files(db: Session, job: AnalysisJob) -> list[RawFile]:
    return list(db.scalars(select(RawFile).where(RawFile.produced_by_job_id == job.id).order_by(RawFile.read_mate)))


def _out_short_reads(db: Session, job: AnalysisJob) -> dict[str, Any]:
    files = _derived_files(db, job)
    mates = {f.read_mate: f.id for f in files}
    if "R1" in mates:
        return {"reads": {"r1": mates["R1"], "r2": mates.get("R2"), "unpaired": None}}
    if len(files) == 1:
        return {"reads": {"r1": None, "r2": None, "unpaired": files[0].id}}
    raise LaunchRefused("wf_output_missing", "the job registered no filtered reads", job_id=job.id)


def _out_long_reads(db: Session, job: AnalysisJob) -> dict[str, Any]:
    files = _derived_files(db, job)
    if not files:
        raise LaunchRefused("wf_output_missing", "the job registered no filtered reads", job_id=job.id)
    # The filtered reads' ARVA statistics (queued by the filter in its own transaction) are waited for: Flye's
    # memory estimate reads their bases. A statistics job that failed, was cancelled or whose task was lost does not
    # hold the run up (batches._sync completes the step when this optional follow-up is lost).
    from app.services.jobs import FASTQ_STATS_JOB

    ids = {f.id for f in files}
    for stats in db.scalars(select(AnalysisJob).where(AnalysisJob.parent_job_id == job.id,
                                                      AnalysisJob.job_type == FASTQ_STATS_JOB)):
        if set(stats.input_raw_file_ids or []) & ids and stats.status in (JobStatus.pending, JobStatus.running):
            raise WaitForFollowUp(stats, required=False)
    return {"reads": {"file_ids": [f.id for f in files]}}


def _assembly_of(db: Session, job: AnalysisJob) -> Assembly:
    a = db.scalar(select(Assembly).where(Assembly.job_id == job.id).order_by(Assembly.created_at.desc()))
    if a is None:
        raise LaunchRefused("wf_output_missing", "the job registered no assembly", job_id=job.id)
    return a


def _out_assembly(db: Session, job: AnalysisJob) -> dict[str, Any]:
    return {"assembly": {"assembly_id": _assembly_of(db, job).id}}


def _out_polished(db: Session, job: AnalysisJob) -> dict[str, Any]:
    if job.job_type == "racon_polish" and (job.parameters or {}).get("then_pilon"):
        follow = db.scalar(select(AnalysisJob).where(AnalysisJob.parent_job_id == job.id,
                                                     AnalysisJob.job_type == "pilon_polish"))
        # The Pilon job is created in the Racon job's own transaction: none after Racon completed means it could
        # not be queued (polishing._queue_followups records why), and waiting for it would never end.
        if follow is None:
            reason = ((job.result_summary or {}).get("followups") or {}).get("pilon_error") or "no Pilon job exists"
            raise LaunchRefused("wf_followup_not_queued", f"the Pilon step after Racon was not queued: {reason}",
                                job_id=job.id)
        if follow.status in (JobStatus.pending, JobStatus.running):
            raise WaitForFollowUp(follow)
        if follow.status is not JobStatus.completed:
            raise LaunchRefused("wf_followup_failed", f"the Pilon job {follow.id} queued after Racon ended with status "
                                f"{follow.status.value}", job_id=follow.id, status=follow.status.value)
        job = follow
    return _out_assembly(db, job)


def _out_annotation(db: Session, job: AnalysisJob) -> dict[str, Any]:
    a = db.scalar(select(Annotation).where(Annotation.job_id == job.id))
    if a is None:
        raise LaunchRefused("wf_output_missing", "the job registered no annotation", job_id=job.id)
    return {"annotation": {"annotation_id": a.id, "assembly_id": a.assembly_id}}


def _comparison_result(db: Session, job: AnalysisJob) -> ComparisonResult:
    r = db.scalar(select(ComparisonResult).where(ComparisonResult.job_id == job.id))
    if r is None:
        raise LaunchRefused("wf_output_missing", "the job registered no result", job_id=job.id)
    return r


def _out_alignment(port: str) -> Callable[[Session, AnalysisJob], dict[str, Any]]:
    def resolve(db: Session, job: AnalysisJob) -> dict[str, Any]:
        r = _comparison_result(db, job)
        return {port: {"result_id": r.id, "analysis": r.analysis, "set_id": r.set_id}}
    return resolve


def _out_tree(db: Session, job: AnalysisJob) -> dict[str, Any]:
    r = _comparison_result(db, job)
    return {"tree": {"result_id": r.id, "set_id": r.set_id}}


def _out_none(db: Session, job: AnalysisJob) -> dict[str, Any]:
    return {}


def _out_species(db: Session, job: AnalysisJob) -> dict[str, Any]:
    r = db.scalar(select(SpeciesResult).where(SpeciesResult.job_id == job.id))
    return {"evidence": {"result_id": r.id if r else None, "species": r.species if r else None}}


def _out_mlst(db: Session, job: AnalysisJob) -> dict[str, Any]:
    r = db.scalar(select(MlstResult).where(MlstResult.job_id == job.id))
    return {"evidence": {"result_id": r.id if r else None, "scheme": r.scheme if r else None}}


# --- launchers -----------------------------------------------------------------------------------------------------

def _routes():
    from app.api.routes import (
        amr,
        annotations,
        assemblies,
        comparative,
        mlst,
        mobile_elements,
        pangenome,
        phylogeny,
        regions,
        species,
        tools,
    )
    from app.api.routes import typing as typing_routes

    return {"amr": amr, "annotations": annotations, "assemblies": assemblies, "comparative": comparative,
            "mlst": mlst, "mobile": mobile_elements, "pangenome": pangenome, "phylogeny": phylogeny,
            "regions": regions, "species": species, "tools": tools, "typing": typing_routes}


def _assembly_id(ctx: LaunchContext) -> str:
    return ctx.inputs["assembly"]["assembly_id"]


def _short_roles(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    return {"r1_file_id": value.get("r1"), "r2_file_id": value.get("r2"), "unpaired_file_id": value.get("unpaired")}


def _single_long(value: dict[str, Any] | None) -> str | None:
    ids = (value or {}).get("file_ids") or []
    if len(ids) > 1:
        raise LaunchRefused("wf_one_file", f"this step takes one long-read file and {len(ids)} were given",
                            count=len(ids))
    return ids[0] if ids else None


def _launch_fastp(ctx: LaunchContext):
    reads = ctx.inputs["reads"]
    r1 = reads.get("r1") or reads.get("unpaired")
    req = _request(ctx, "fastp", {"read1_file_id": r1, "read2_file_id": reads.get("r2") if reads.get("r1") else None})
    return call(_routes()["tools"].start_fastp, ctx.sample.id, req, ctx.db)


def _launch_filtlong(ctx: LaunchContext):
    req = _request(ctx, "filtlong", {"file_id": _single_long(ctx.inputs["reads"])})
    return call(_routes()["tools"].start_filtlong, ctx.sample.id, req, ctx.db)


def _launch_flye(ctx: LaunchContext):
    node = _request(ctx, "flye", {"raw_file_ids": ctx.inputs["reads"]["file_ids"]})
    body = node.model_dump()
    guard = body.pop("memory_guard")
    params = body["params"]
    decision = flye_memory_guard(ctx.db, ctx.sample, body["raw_file_ids"], params, guard, ctx.memory_gb)
    if decision["applied"]:
        params.update(decision["applied"])
        ctx.params = {**ctx.params, "params": {**ctx.params.get("params", {}), **decision["applied"]}}
    ctx.notes["flye_memory"] = decision
    req = s.FlyeRequest.model_validate(body)
    return call(_routes()["assemblies"].start_flye, ctx.sample.id, req, ctx.db)


def flye_memory_guard(db: Session, sample: Sample, file_ids: list[str], params: dict[str, Any],
                      guard: str, memory_gb: int | None = None) -> dict[str, Any]:
    """Flye's memory estimate for the node's reads and parameters and, with the guard on ("auto") and an estimate
    that may not fit, the options it adds: --asm-coverage (SUGGESTED_ASM_COVERAGE, the 40x Flye's manual gives as
    typically enough) and, when the node set none, the sample's expected genome size. A value the node sets itself
    is never changed; when the guard cannot apply (asm_coverage or meta set, no genome size known, no read
    statistics, or reads already below that coverage, so --asm-coverage would not use fewer) the run goes ahead as
    configured and the reason is recorded.

    memory_gb: what the batch reserves for this job (its memory per job, which decides how many jobs run at once);
    the part of the estimate that depends on the reads is compared with that, capped by the memory the container
    has, because other jobs of the batch may run beside this one. Flye's fixed k-mer counter floor
    (arva_tools.flye.KMER_COUNTER_FLOOR) is compared with the container's memory only: Flye allocates it whatever
    the batch reserves. When the container is below the floor --asm-coverage cannot help: nothing is added and the
    reason is recorded."""
    from arva_tools.flye import SUGGESTED_ASM_COVERAGE, FlyeParams

    from app.services import flye
    from app.services.performance import effective_resources

    res = effective_resources(db)
    files = [db.get(RawFile, i) for i in file_ids]
    ev = flye.evidence(db, [f for f in files if f is not None])
    current = FlyeParams(**{k: v for k, v in params.items() if k != "threads"})
    est = flye.memory(db, sample, ev, current, res, memory_gb or None)
    out = {"guard": guard, "estimate": {k: v for k, v in est.items() if k not in ("reference", "reference_bases")},
           "applied": None, "not_applied": None}
    if guard == "auto" and est["verdict"] == "unknown":
        out["not_applied"] = "no_read_statistics" if not est["read_bases"] else "memory_unknown"
    if guard == "auto" and est["verdict"] == "below_floor":
        out["not_applied"] = "below_kmer_floor"
    if guard != "auto" or est["verdict"] != "may_not_fit":
        return out
    size = params.get("genome_size_bp") or est["expected_genome_size_bp"]
    if params.get("asm_coverage") is not None:
        out["not_applied"] = "asm_coverage_set"
    elif params.get("meta"):
        out["not_applied"] = "meta"
    elif not size:
        out["not_applied"] = "no_genome_size"
    elif SUGGESTED_ASM_COVERAGE * size >= est["read_bases"]:
        out["not_applied"] = "reads_below_asm_coverage"
    else:
        applied: dict[str, Any] = {"asm_coverage": SUGGESTED_ASM_COVERAGE}
        if params.get("genome_size_bp") is None:
            applied.update(genome_size_bp=size, genome_size_basis="expected_genome_size", assumed_depth_x=None)
        after = flye.memory(db, sample, ev, FlyeParams(**{**{k: v for k, v in params.items() if k != "threads"},
                                                          **applied, "genome_size_bp": size}), res,
                            memory_gb or None)
        out["applied"] = applied
        out["estimate_after"] = {k: v for k, v in after.items() if k not in ("reference", "reference_bases")}
    return out


def _with_memory(ctx: LaunchContext, key: str) -> None:
    ctx.params = {**ctx.params, "params": {**ctx.params.get("params", {})}}
    if ctx.params["params"].get(key) is None:
        ctx.params["params"][key] = ctx.memory_gb


def _launch_spades(ctx: LaunchContext):
    _with_memory(ctx, "memory_gb")
    req = _request(ctx, "spades", {"inputs": _short_roles(ctx.inputs["reads"])})
    return call(_routes()["assemblies"].start_spades, ctx.sample.id, req, ctx.db)


def _launch_unicycler(ctx: LaunchContext):
    _with_memory(ctx, "spades_memory_gb")
    inputs = {**_short_roles(ctx.inputs["short_reads"]), "long_file_id": _single_long(ctx.inputs.get("long_reads"))}
    req = _request(ctx, "unicycler", {"inputs": inputs})
    return call(_routes()["assemblies"].start_unicycler, ctx.sample.id, req, ctx.db)


def memory_gb_for(kind: str, params: dict[str, Any], memory_gb: int, max_memory_gb: int) -> int:
    """The memory a node's job gets and a batch reserves for it: the run's memory per job, except Pilon's heap
    (polishing with Pilon), which unless the node sets one follows polishing.default_heap_gb: Pilon documents at
    least 8 GB for bacterial genomes, more than a small profile's memory per job."""
    if kind == "polishing" and params.get("strategy") in ("pilon", "hybrid"):
        from app.services.polishing import default_heap_gb

        heap = (params.get("pilon") or {}).get("heap_gb")
        return heap if isinstance(heap, int) and heap > 0 else default_heap_gb(memory_gb, max_memory_gb)
    return memory_gb


def _launch_polishing(ctx: LaunchContext):
    from app.services.performance import effective_resources

    pilon = {**ctx.params.get("pilon", {})}
    if ctx.params.get("strategy") in ("pilon", "hybrid") and pilon.get("heap_gb") is None:
        pilon["heap_gb"] = memory_gb_for("polishing", ctx.params, ctx.memory_gb, effective_resources(ctx.db).max_memory_gb)
    ctx.params = {**ctx.params, "pilon": pilon}
    inputs = {**_short_roles(ctx.inputs.get("short_reads")),
              "long_file_id": _single_long(ctx.inputs.get("long_reads"))}
    req = _request(ctx, "polishing", {"inputs": inputs, "quast": False, "quast_reference_file_id": None})
    return call(_routes()["assemblies"].start_polishing, _assembly_id(ctx), req, ctx.db)


def _launch_quast(ctx: LaunchContext):
    req = _request(ctx, "quast", {"assembly_ids": [_assembly_id(ctx)], "reference_file_id": None})
    return call(_routes()["assemblies"].start_quast, ctx.sample.id, req, ctx.db)


def _launch_bakta(ctx: LaunchContext):
    r = _routes()["annotations"]
    preview = s.BaktaPreviewRequest(database_id=ctx.params.get("database_id"),
                                    skip_plot=bool((ctx.params.get("settings") or {}).get("skip_plot")))
    try:
        plan = r.preview_bakta(_assembly_id(ctx), preview, ctx.db)
    except HTTPException as exc:
        raise LaunchRefused("wf_launch_refused", str(exc.detail)) from exc
    _locus_tag(ctx)
    req = _request(ctx, "bakta", {"skip_options": plan["skip_options"], "confirmed": True})
    return call(r.start_bakta, _assembly_id(ctx), s.BaktaRequest.model_validate(req.model_dump()), ctx.db)


def _locus_tag(ctx: LaunchContext) -> None:
    from app.services.annotation import suggested_locus_tag

    settings = {**ctx.params.get("settings", {})}
    if not settings.get("locus_tag"):
        settings["locus_tag"] = suggested_locus_tag(ctx.sample)
    ctx.params = {**ctx.params, "settings": settings}


def _launch_prokka(ctx: LaunchContext):
    _locus_tag(ctx)
    req = _request(ctx, "prokka", {"confirmed": True})
    return call(_routes()["annotations"].start_prokka, _assembly_id(ctx), s.ProkkaRequest.model_validate(
        req.model_dump()), ctx.db)


def _assembly_action(route: str, func: str, kind: str, extra: Callable[[LaunchContext], dict] | None = None):
    def launch(ctx: LaunchContext):
        req = _request(ctx, kind, {"confirmed": True, **(extra(ctx) if extra else {})})
        return call(getattr(_routes()[route], func), _assembly_id(ctx), req, ctx.db)
    return launch


def _amr_annotation(ctx: LaunchContext) -> dict[str, Any]:
    ann = ctx.inputs.get("annotation")
    if ann and ann["assembly_id"] != _assembly_id(ctx):
        raise LaunchRefused("wf_annotation_mismatch", "the annotation given is not an annotation of the assembly given")
    return {"annotation_id": ann["annotation_id"] if ann else None}


def _set_action(route: str, func: str, kind: str, extra: Callable[[LaunchContext], dict] | None = None):
    def launch(ctx: LaunchContext):
        set_id = ctx.inputs["set"]["set_id"]
        req = _request(ctx, kind, {"confirmed": True, **(extra(ctx, set_id) if extra else {})})
        return call(getattr(_routes()[route], func), set_id, req, ctx.db)
    return launch


def _members(ctx: LaunchContext, set_id: str) -> list[str]:
    cset = ctx.db.get(ComparisonSet, set_id)
    return [m.assembly_id for m in cset.members]


def _launch_staph_typing(ctx: LaunchContext):
    """One S. aureus typing step through the typing route. The module's applicability is read first from the
    assembly's species identification and MLST records (typing_modules.applicability, the route's own rule):

    * not_applicable (the evidence names another species or MLST scheme, nothing names S. aureus): the step is
      skipped with that reason, which is not an error;
    * no_evidence (no species and no MLST scheme was called) or conflicting (one source names S. aureus, another
      does not): ARVA cannot tell, so the step fails with that reason and the run ends with errors, for the user to
      check the evidence (or set override_applicability).

    With override_applicability the step runs anyway, and the result records the override as the route does."""
    from app.services import staph_typing
    from app.services import typing_modules as tm

    a = ctx.db.get(Assembly, _assembly_id(ctx))
    if a is None:
        raise LaunchRefused("wf_output_missing", "the assembly no longer exists", job_id="")
    found = tm.applicability(staph_typing.MODULE, tm.evidence(ctx.db, a))
    if found["override_required"] and not ctx.params.get("override_applicability"):
        species = (found["evidence"].get("species") or {}).get("value") or ""
        scheme = (found["evidence"].get("mlst") or {}).get("value") or ""
        if found["status"] == "not_applicable":
            raise NodeSkipped("wf_typing_not_applicable",
                              f"S. aureus typing does not apply: the species evidence names species "
                              f"{species or 'none'}, MLST scheme {scheme or 'none'}",
                              status=found["status"], species=species, scheme=scheme)
        if found["status"] == "conflicting":
            raise LaunchRefused("wf_typing_conflicting",
                                f"the species evidence conflicts (species {species or 'none'}, MLST scheme "
                                f"{scheme or 'none'}): check it, or run the step with override_applicability",
                                status=found["status"], species=species, scheme=scheme)
        raise LaunchRefused("wf_typing_no_evidence",
                            "no species and no MLST scheme was identified for this assembly, so ARVA cannot tell "
                            "whether S. aureus typing applies: check the species identification and MLST results, "
                            "or run the step with override_applicability",
                            status=found["status"])
    req = _request(ctx, "staph_typing", {})
    body = s.TypingRequest.model_validate({**req.model_dump(), "confirmed": True})
    return call(_routes()["typing"].start_typing, a.id, staph_typing.MODULE.key, body, ctx.db)


def _launch_phylogeny(ctx: LaunchContext):
    up = ctx.inputs["alignment"]
    p = dict(ctx.params)
    source = {"kind": p.pop("source_kind"), "result_id": up["result_id"], "core": p.pop("core"),
              "family": p.pop("family")}
    body = {**p, "source": source, "confirmed": True}
    if body.get("threads") is None:
        body["threads"] = ctx.threads
    try:
        req = s.PhylogenyIn.model_validate(body)
    except ValidationError as exc:
        raise LaunchRefused("wf_params_invalid", _errors_text(exc)) from exc
    return call(_routes()["phylogeny"].start_phylogeny, up["set_id"], req, ctx.db)


KINDS: dict[str, Kind] = {
    "reads_long_input": Kind(s.ReadsSourceIn, threads_at=None),
    "reads_short_input": Kind(s.ReadsSourceIn, threads_at=None),
    "assembly_input": Kind(s.AssemblySourceIn, threads_at=None),
    "annotation_input": Kind(s.AssemblySourceIn, threads_at=None),
    "comparison_set_input": Kind(s.SetSourceIn, threads_at=None),
    "comparison_set": Kind(s.CollectSetIn, threads_at=None),
    "fastp": Kind(s.FastpRequest, ("read1_file_id", "read2_file_id"), {"read1_file_id": PLACEHOLDER},
                  _launch_fastp, _out_short_reads, None),
    "filtlong": Kind(s.FiltlongRequest, ("file_id",), {"file_id": PLACEHOLDER}, _launch_filtlong, _out_long_reads,
                     None),
    "flye": Kind(s.FlyeNodeIn, ("raw_file_ids",), {"raw_file_ids": [PLACEHOLDER]}, _launch_flye, _out_assembly,
                 "params.threads"),
    "spades": Kind(s.SpadesRequest, ("inputs",), {"inputs": {}}, _launch_spades, _out_assembly, "params.threads"),
    "unicycler": Kind(s.UnicyclerRequest, ("inputs",), {"inputs": {}}, _launch_unicycler, _out_assembly,
                      "params.threads"),
    "polishing": Kind(s.PolishingRequest, ("inputs", "quast", "quast_reference_file_id"), {"inputs": {}},
                      _launch_polishing, _out_polished),
    "quast": Kind(s.QuastRequest, ("assembly_ids", "reference_file_id"), {"assembly_ids": [PLACEHOLDER]},
                  _launch_quast, _out_none),
    "bakta": Kind(s.BaktaNodeIn, ("skip_options", "confirmed"), {"skip_options": [], "confirmed": True},
                  _launch_bakta, _out_annotation),
    "prokka": Kind(s.ProkkaNodeIn, ("confirmed",), {"confirmed": True}, _launch_prokka, _out_annotation),
    "mlst": Kind(s.MlstRequest, ("confirmed",), {"confirmed": True}, _assembly_action("mlst", "start_mlst", "mlst"),
                 _out_mlst),
    "species": Kind(s.SpeciesRequest, ("confirmed",), {"confirmed": True},
                    _assembly_action("species", "start_species", "species"), _out_species),
    "staph_typing": Kind(s.StaphTypingNodeIn, (), {}, _launch_staph_typing, _out_none, None),
    "amrfinderplus": Kind(s.AmrRequest, ("annotation_id", "confirmed"), {"confirmed": True},
                          _assembly_action("amr", "start_amr", "amrfinderplus", _amr_annotation), _out_none),
    "virulence": Kind(s.VirulenceRequest, ("confirmed",), {"confirmed": True},
                      _assembly_action("mobile", "start_virulence", "virulence"), _out_none),
    "mobile_elements": Kind(s.MobileRequest, ("confirmed",), {"confirmed": True},
                            _assembly_action("mobile", "start_mobile", "mobile_elements"), _out_none),
    "comparative_ani": Kind(s.ComparisonAniIn, ("confirmed",), {}, _set_action("comparative", "start_ani",
                                                                                "comparative_ani"), _out_none),
    "comparative_alignment": Kind(s.ComparisonAlignmentIn, ("order", "confirmed"), {},
                                  _set_action("comparative", "start_alignment", "comparative_alignment"), _out_none),
    "pangenome": Kind(s.PangenomeIn, ("genomes", "confirmed"), {},
                      _set_action("pangenome", "start_pangenome", "pangenome"), _out_alignment("core_alignment")),
    "phylogeny": Kind(s.PhylogenyNodeIn, (), {}, _launch_phylogeny, _out_tree),
    "gene_investigation": Kind(s.GeneInvestigationIn, ("genomes", "confirmed"), {"genomes": [PLACEHOLDER]},
                               _set_action("regions", "start_gene", "gene_investigation",
                                           lambda ctx, set_id: {"genomes": _members(ctx, set_id)}),
                               _out_alignment("alignment")),
}

assert set(KINDS) == set(core.NODES), set(KINDS) ^ set(core.NODES)


def normalise(kind: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The node's parameters with every default made explicit, and the problems the analysis's request model finds
    in them (fields ARVA fills itself are left out of both)."""
    spec = KINDS[kind]
    body = {k: v for k, v in (params or {}).items() if k not in spec.bound}
    for name, f in spec.model.model_fields.items():
        sub = f.annotation
        if f.is_required() and name not in body and isinstance(sub, type) and issubclass(sub, BaseModel):
            body[name] = {}
    try:
        full = spec.model.model_validate({**body, **spec.placeholders}).model_dump(mode="json")
    except ValidationError as exc:
        errors = [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()
                  if not e["loc"] or e["loc"][0] not in spec.bound]
        if errors:
            return body, errors
        return body, []
    return {k: v for k, v in full.items() if k not in spec.bound}, []


def param_schema(kind: str) -> dict[str, Any]:
    spec = KINDS[kind]
    schema = spec.model.model_json_schema()
    for name in spec.bound:
        schema.get("properties", {}).pop(name, None)
    schema["required"] = [r for r in schema.get("required", []) if r not in spec.bound]
    return schema


# --- sources -------------------------------------------------------------------------------------------------------

def _reads(db: Session, sample: Sample, include_derived: bool) -> list[RawFile]:
    q = select(RawFile).where(RawFile.sample_id == sample.id, RawFile.is_valid.is_(True),
                              RawFile.file_format.in_(FASTQ)).order_by(RawFile.uploaded_at)
    files = db.scalars(q).all()
    return [f for f in files if include_derived or f.origin is not FileOrigin.derived]


def _source_reads_long(db: Session, sample: Sample, params: dict[str, Any]) -> dict[str, Any]:
    if sample.sequencing_technology is SequencingTechnology.illumina:
        raise LaunchRefused("wf_source_technology", "the sample's sequencing technology is Illumina (short reads)")
    files = [f for f in _reads(db, sample, params.get("include_derived", False)) if f.read_mate is None]
    if len(files) != 1:
        raise LaunchRefused("wf_source_long", f"{len(files)} candidate long-read files (valid FASTQ without a mate)",
                            count=len(files))
    return {"reads": {"file_ids": [files[0].id]}}


def _source_reads_short(db: Session, sample: Sample, params: dict[str, Any]) -> dict[str, Any]:
    files = _reads(db, sample, params.get("include_derived", False))
    r1 = [f for f in files if f.read_mate == "R1"]
    r2 = [f for f in files if f.read_mate == "R2"]
    if len(r1) != 1 or len(r2) != 1:
        raise LaunchRefused("wf_source_pair", f"{len(r1)} R1 and {len(r2)} R2 files", r1=len(r1), r2=len(r2))
    return {"reads": {"r1": r1[0].id, "r2": r2[0].id, "unpaired": None}}


def _newest_assembly(db: Session, sample: Sample, prefer: str) -> Assembly:
    rows = db.scalars(select(Assembly).where(Assembly.sample_id == sample.id)
                      .order_by(Assembly.created_at.desc())).all()
    polished = [a for a in rows if a.kind is AssemblyKind.polished]
    chosen = (polished or rows) if prefer == "latest_polished" else rows
    if not chosen:
        raise LaunchRefused("wf_source_assembly", "the sample has no assembly")
    return chosen[0]


def _source_assembly(db: Session, sample: Sample, params: dict[str, Any]) -> dict[str, Any]:
    return {"assembly": {"assembly_id": _newest_assembly(db, sample, params.get("prefer", "latest_polished")).id}}


def _source_annotation(db: Session, sample: Sample, params: dict[str, Any]) -> dict[str, Any]:
    a = _newest_assembly(db, sample, params.get("prefer", "latest_polished"))
    ann = db.scalar(select(Annotation).where(Annotation.assembly_id == a.id).order_by(Annotation.created_at.desc()))
    if ann is None:
        raise LaunchRefused("wf_source_annotation", "the chosen assembly has no annotation", assembly_id=a.id)
    return {"annotation": {"annotation_id": ann.id, "assembly_id": a.id}, "assembly": {"assembly_id": a.id}}


SOURCES = {"reads_long_input": _source_reads_long, "reads_short_input": _source_reads_short,
           "assembly_input": _source_assembly, "annotation_input": _source_annotation}


def resolve_source(db: Session, kind: str, sample: Sample | None, params: dict[str, Any],
                   override: dict[str, Any] | None, project_id: str | None = None) -> dict[str, Any]:
    """The outputs of a source node: the user's binding when given (checked to belong to the sample), else ARVA's
    rule. Raises LaunchRefused when the rule finds nothing or more than one candidate. A comparison set must be of
    the run's project (`project_id`): workflows are shared by every account, and the set's steps call the routes
    directly, past the access checks, so a set of another project is refused as if it did not exist."""
    if kind == "comparison_set_input":
        cset = db.get(ComparisonSet, params.get("set_id") or "")
        if cset is None or cset.project_id != project_id:
            raise LaunchRefused("wf_source_set", "the comparison set no longer exists in this project")
        return {"set": {"set_id": cset.id}}
    if override:
        return _bound(db, kind, sample, override)
    return SOURCES[kind](db, sample, params)


def _bound(db: Session, kind: str, sample: Sample, value: dict[str, Any]) -> dict[str, Any]:
    def owned(model, ident):
        row = db.get(model, ident or "")
        if row is None or row.sample_id != sample.id:
            raise LaunchRefused("wf_binding", f"{ident} is not data of sample {sample.sample_code}", id=str(ident))
        return row

    if kind == "reads_long_input":
        ids = value.get("file_ids") or []
        for i in ids:
            owned(RawFile, i)
        if not ids:
            raise LaunchRefused("wf_binding", "no file given", id="")
        return {"reads": {"file_ids": list(ids)}}
    if kind == "reads_short_input":
        for role in ("r1", "r2", "unpaired"):
            if value.get(role):
                owned(RawFile, value[role])
        return {"reads": {"r1": value.get("r1"), "r2": value.get("r2"), "unpaired": value.get("unpaired")}}
    if kind == "assembly_input":
        return {"assembly": {"assembly_id": owned(Assembly, value.get("assembly_id")).id}}
    ann = owned(Annotation, value.get("annotation_id"))
    return {"annotation": {"annotation_id": ann.id, "assembly_id": ann.assembly_id},
            "assembly": {"assembly_id": ann.assembly_id}}
