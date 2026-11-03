"""Workflows and batch runs: versioned definitions, the queue that runs them, and what a run shows and exports.

A run (batch) expands a workflow version over samples into items: one per sample-scope node and sample, one per
set-scope node. Every item that runs a tool is launched through the analysis's own API action (workflow_nodes) and
becomes one ordinary analysis job; nothing about how that job runs changes.

The queue (`dispatch`) is ARVA's own scheduler on top of the task queue:

* Order: runs by priority (higher first), then by creation; inside a run, items in the graph's order and sample
  order. An item is ready when every item it reads from has completed.
* Concurrency: at most `max_concurrent` jobs of a run are in the task queue at once, and across runs the threads
  and memory reserved by queued and running batch jobs stay within what the performance profile lets ARVA use
  (its CPUs and memory, or the administrator's caps). An item reserves the run's threads and memory per job; the
  threads are given to the tool, the memory only to tools that take a limit (SPAdes, Unicycler's SPAdes, Pilon).
  These are ARVA's scheduling estimates, not measurements, and jobs started outside a batch are not counted. Jobs
  run in parallel only when there are as many worker processes.
* Retries: a job that failed while running is tried again, as a new job, up to `max_retries` times. A launch the
  analysis's checks refused is never retried (it would be refused again).
* Failure: items that read from a failed, cancelled or skipped item are skipped with that reason.
* Pause stops new launches; resume puts failed, cancelled and skipped items back in the queue (completed items keep
  their results); cancel cancels queued and running jobs and every waiting item.

`dispatch` runs when a run is created or changed, when any job ends (app.tasks.common.run_job), when a job is
cancelled, and when the worker starts (so runs interrupted by a restart continue).
"""
from __future__ import annotations

import csv
import functools
import hashlib
import io
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from arva_core import workflow as core
from arva_tools import ToolStatus
from arva_tools.registry import detect, get_adapter
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import errorlog
from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    BatchItem,
    BatchRun,
    JobStatus,
    Project,
    Sample,
    Workflow,
    WorkflowVersion,
)
from app.services import workflow_nodes as nodes
from app.services.performance import effective_resources

ACTIVE_RUN = ("running", "paused")
TERMINAL_ITEM = ("completed", "failed", "cancelled", "skipped")
IN_QUEUE = ("queued", "running")
SET_KEY = "_set"
_LOCK_KEY = 0x41525641  # "ARVA"
LOCKS_DIR = Path(__file__).resolve().parents[4] / "docker" / "conda-locks"


class WorkflowError(ValueError):
    def __init__(self, message: str, code: str, **params: Any):
        super().__init__(message)
        self.code = code
        self.params = params


def now() -> datetime:
    return datetime.now(UTC)


# --- definitions ---------------------------------------------------------------------------------------------------

def check_definition(definition: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The definition with every node's parameters made explicit, and its problems: the graph's (arva_core) and
    each node's parameters checked against the analysis's request model."""
    problems = core.validate(definition)
    out = json.loads(json.dumps(definition))
    if any(p["code"] in ("wf_format", "wf_node_kind", "wf_node_id", "wf_node_duplicate") for p in problems):
        return out, problems
    for n in out["nodes"]:
        full, errors = nodes.normalise(n["kind"], n.get("params") or {})
        n["params"] = full
        problems.extend(core.problem("wf_param", n["id"], field=e["loc"], message=e["msg"]) for e in errors)
    # A definition written by hand or by a script may carry no positions; stacked nodes are unreadable in the editor.
    if len(out["nodes"]) > 1 and len({json.dumps(n.get("position"), sort_keys=True) for n in out["nodes"]}) == 1 \
            and not any(p["code"] in ("wf_cycle", "wf_edge_node") for p in problems):
        core.layout(out)
    by_id = {n["id"]: n for n in out["nodes"]}
    for e in out["edges"]:
        src, dst = by_id.get(e["source"]), by_id.get(e["target"])
        if src and dst and src["kind"] == "pangenome" and dst["kind"] == "phylogeny":
            kind = dst["params"].get("source_kind")
            if kind in ("core_alignment", "snp_alignment") and (src["params"].get("method") != "panaroo" or (
                    src["params"].get("panaroo") or {}).get("alignment") == "none"):
                problems.append(core.problem("wf_phylo_alignment", dst["id"], source=src["id"]))
    return out, problems


def availability(definition: dict[str, Any], refresh: bool = False) -> list[dict[str, Any]]:
    """Every tool a definition needs that is not available, by node (detected again with `refresh`, as before a
    run; otherwise from the detection cache)."""
    out = []
    for node_id, tool_ids in core.tools_of(definition).items():
        for tool_id in tool_ids:
            d = detect(tool_id, refresh=refresh)
            if d.status is not ToolStatus.available:
                out.append(core.problem("wf_tool_unavailable", node_id, tool=d.info.name, status=d.status.value,
                                        reason=d.message))
    return out


def _lock_info(tool_id: str, path: str | None) -> dict[str, Any] | None:
    info = get_adapter(tool_id).info
    if not info.conda_platforms:
        return None
    out: dict[str, Any] = {"lock": f"docker/conda-locks/{tool_id}/", "platforms": list(info.conda_platforms)}
    for platform in info.conda_platforms:
        f = LOCKS_DIR / tool_id / f"{platform}.lock"
        if f.is_file():
            out[f"{platform}_sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
    if path:
        meta = Path(path).resolve().parent.parent / "conda-meta"
        if meta.is_dir():
            names = sorted(p.name for p in meta.glob("*.json"))
            out["installed_packages"] = len(names)
            out["installed_sha256"] = hashlib.sha256("\n".join(names).encode()).hexdigest()
    return out


def tool_snapshot(definition: dict[str, Any]) -> dict[str, Any]:
    """The tools a definition uses as installed now: name, version, path, status and, for Bioconda tools, the lock
    files' SHA-256 and a checksum of the installed environment's package list (conda-meta)."""
    out = {}
    for tool_id in sorted({t for ts in core.tools_of(definition).values() for t in ts}):
        d = detect(tool_id)
        out[tool_id] = {"name": d.info.name, "version": d.version, "status": d.status.value, "path": d.path,
                        "conda": _lock_info(tool_id, d.path)}
    return out


def create_workflow(db: Session, name: str, description: str | None, template_key: str | None,
                    definition: dict[str, Any] | None) -> Workflow:
    if definition is None:
        if template_key not in core.TEMPLATES:
            raise WorkflowError(f"Unknown predefined workflow {template_key}", "wf_template_unknown",
                                key=str(template_key))
        definition = core.TEMPLATES[template_key]
    wf = Workflow(name=name.strip(), description=description, template_key=template_key)
    db.add(wf)
    db.flush()
    add_version(db, wf, definition, "created")
    return wf


def add_version(db: Session, wf: Workflow, definition: dict[str, Any], note: str | None) -> WorkflowVersion:
    """Save a definition as the workflow's next version (never rewriting one). Structural problems are refused;
    parameter problems are saved and shown, and block only running it."""
    full, problems = check_definition(definition)
    structural = [p for p in problems if p["code"] not in ("wf_param", "wf_phylo_alignment", "wf_input_missing")]
    if structural:
        p = structural[0]
        raise WorkflowError(f"The workflow cannot be saved: {p['code']}", p["code"], **p["params"])
    last = max((v.version for v in wf.versions), default=0)
    v = WorkflowVersion(workflow_id=wf.id, version=last + 1, definition=full,
                        definition_sha256=core.checksum(full), note=note)
    db.add(v)
    wf.updated_at = now()
    db.commit()
    db.refresh(wf)
    return v


def version_of(wf: Workflow, version: int | None) -> WorkflowVersion:
    if not wf.versions:
        raise WorkflowError("The workflow has no version", "wf_version_missing", version="")
    if version is None:
        return wf.versions[-1]
    v = next((v for v in wf.versions if v.version == version), None)
    if v is None:
        raise WorkflowError(f"Version {version} does not exist", "wf_version_missing", version=version)
    return v


def duplicate(db: Session, wf: Workflow, name: str, version: int | None) -> Workflow:
    src = version_of(wf, version)
    copy = Workflow(name=name.strip(), description=wf.description, template_key=wf.template_key,
                    duplicated_from_id=wf.id)
    db.add(copy)
    db.flush()
    add_version(db, copy, src.definition, f"duplicated from {wf.name} v{src.version}")
    return copy


def workflow_view(db: Session, wf: Workflow) -> dict[str, Any]:
    latest = wf.versions[-1] if wf.versions else None
    runs = db.scalar(select(func.count(BatchRun.id)).join(
        WorkflowVersion, WorkflowVersion.id == BatchRun.workflow_version_id).where(
        WorkflowVersion.workflow_id == wf.id)) or 0
    problems = []
    if latest is not None:
        _, problems = check_definition(latest.definition)
        problems += availability(latest.definition)
    return {"id": wf.id, "name": wf.name, "description": wf.description, "template_key": wf.template_key,
            "duplicated_from_id": wf.duplicated_from_id, "created_at": wf.created_at, "updated_at": wf.updated_at,
            "versions": [{"version": v.version, "definition_sha256": v.definition_sha256, "note": v.note,
                          "created_at": v.created_at} for v in wf.versions],
            "latest": None if latest is None else {"version": latest.version, "definition": latest.definition,
                                                    "definition_sha256": latest.definition_sha256},
            "problems": problems, "runs": runs}


def catalogue() -> dict[str, Any]:
    """The node kinds (ports, scope, tools by method, parameter schema and availability) and the predefined
    workflows with whether the tools here can run them."""
    kinds = []
    for kind, spec in core.NODES.items():
        tools = {key: [_tool_state(t) for t in ids] for key, ids in (spec.tools or {}).items()}
        kinds.append({"kind": kind, "scope": spec.scope, "category": spec.category, "source": spec.source,
                      "internal": spec.internal, "tool_param": spec.tool_param, "tools": tools,
                      "inputs": [{"name": p.name, "accepts": list(p.accepts), "required": p.required,
                                  "collection": p.collection} for p in spec.inputs],
                      "outputs": [{"name": p.name, "type": p.accepts[0]} for p in spec.outputs],
                      "params_schema": nodes.param_schema(kind),
                      "defaults": nodes.normalise(kind, {})[0]})
    templates = []
    for key, d in core.TEMPLATES.items():
        full, problems = check_definition(d)
        templates.append({"key": key, "definition": full, "unavailable": availability(full),
                          "needs_parameters": [p for p in problems if p["code"] == "wf_param"]})
    return {"port_types": list(core.PORT_TYPES), "kinds": kinds, "templates": templates,
            "nextflow": {"generated": False, "reason_code": "wf_nextflow_not_faithful"}}


def _tool_state(tool_id: str) -> dict[str, Any]:
    d = detect(tool_id)
    return {"id": tool_id, "name": d.info.name, "version": d.version, "available": d.status is ToolStatus.available,
            "status": d.status.value, "reason": d.reason, "reason_params": d.reason_params, "message": d.message}


def export_definition(wf: Workflow, v: WorkflowVersion) -> dict[str, Any]:
    """A reproducible definition: the graph with every parameter explicit, its checksum, and the tools as installed
    here (versions, Bioconda lock checksums)."""
    return {"format": core.FORMAT, "format_version": core.FORMAT_VERSION, "arva_export": "workflow",
            "workflow": {"name": wf.name, "description": wf.description, "version": v.version,
                         "template_key": wf.template_key},
            "definition_sha256": v.definition_sha256, "definition": v.definition,
            "tools": tool_snapshot(v.definition), "exported_at": now().isoformat(timespec="seconds"),
            "nextflow": {"generated": False, "reason": NEXTFLOW_REASON}}


NEXTFLOW_REASON = (
    "Not generated. Each node runs through the analysis's own ARVA action: input checks that read ARVA's database "
    "(sequencing technology, read evidence, database records and checksums), choices made at launch (Bakta's "
    "skipped steps, genome-size derivation, the polishing follow-up job) and ARVA's own parsing of outputs into its "
    "records. A Nextflow process could only replay the commands, not those steps, so it would not be the same "
    "analysis. The exact commands each job ran are in the run export (jobs[].commands).")


def import_definition(payload: dict[str, Any]) -> dict[str, Any]:
    """The definition inside an ARVA export (or a bare definition); checked like any other on save."""
    definition = payload.get("definition") if payload.get("arva_export") else payload
    if not isinstance(definition, dict):
        raise WorkflowError("Not an ARVA workflow definition", "wf_format", format="?", version="?")
    return definition


# --- runs ----------------------------------------------------------------------------------------------------------

def _settings(db: Session, given: dict[str, Any]) -> dict[str, Any]:
    res = effective_resources(db)
    threads = res.cap_threads(given.get("threads_per_job"))
    memory = max(1, min(given.get("memory_per_job_gb") or res.memory_gb, res.max_memory_gb))
    return {"priority": given.get("priority", 0), "max_concurrent": given.get("max_concurrent", 1),
            "threads_per_job": threads, "memory_per_job_gb": memory, "max_retries": given.get("max_retries", 0),
            "profile": res.profile, "budget_threads": res.max_threads, "budget_memory_gb": res.max_memory_gb}


def _scope(kind: str) -> str:
    return core.NODES[kind].scope


def plan_run(db: Session, project: Project, v: WorkflowVersion, sample_ids: list[str],
             bindings: dict[str, dict[str, dict[str, Any]]], given: dict[str, Any]) -> dict[str, Any]:
    """What a run would do: per sample, what each source node picks (or why it cannot), the tools, the items and
    jobs, the queue settings and estimated resources, and anything that blocks the whole run."""
    definition = v.definition
    _, problems = check_definition(definition)
    problems = [p for p in problems] + availability(definition, refresh=True)
    samples = []
    seen = set()
    for sid in sample_ids:
        sample = db.get(Sample, sid)
        if sample is None or sample.project_id != project.id or sid in seen:
            raise WorkflowError(f"Sample {sid} is not a sample of this project (or is listed twice)",
                                "wf_sample_foreign", sample_id=sid)
        seen.add(sid)
        samples.append(sample)
    sample_nodes = [n for n in definition["nodes"] if _scope(n["kind"]) == "sample"]
    set_nodes = [n for n in definition["nodes"] if _scope(n["kind"]) == "set"]
    if set_nodes and any(n["kind"] == "comparison_set" for n in set_nodes) and len(samples) < 2:
        problems.append(core.problem("wf_set_samples", None, count=len(samples)))
    rows = []
    for sample in samples:
        picks = {}
        for n in sample_nodes:
            if not core.NODES[n["kind"]].source:
                continue
            try:
                picks[n["id"]] = {"ok": True, "outputs": nodes.resolve_source(
                    db, n["kind"], sample, n["params"], bindings.get(sample.id, {}).get(n["id"]))}
            except nodes.LaunchRefused as exc:
                picks[n["id"]] = {"ok": False, "code": exc.code, "params": exc.params, "message": str(exc)}
        rows.append({"sample_id": sample.id, "sample_code": sample.sample_code, "sources": picks,
                     "ready": all(p["ok"] for p in picks.values())})
    for n in set_nodes:
        if n["kind"] == "comparison_set_input":
            try:
                nodes.resolve_source(db, n["kind"], None, n["params"], None, project.id)
            except nodes.LaunchRefused as exc:
                problems.append(core.problem(exc.code, n["id"]))
    settings = _settings(db, given)
    jobs_per_sample = sum(1 for n in sample_nodes if not core.NODES[n["kind"]].source)
    set_jobs = sum(1 for n in set_nodes if not (core.NODES[n["kind"]].source or core.NODES[n["kind"]].internal))
    ready = sum(1 for r in rows if r["ready"])
    return {"workflow_version_id": v.id, "version": v.version, "definition_sha256": v.definition_sha256,
            "samples": rows, "ready_samples": ready, "jobs": jobs_per_sample * ready + set_jobs,
            "settings": settings, "tools": tool_snapshot(definition), "problems": problems,
            "concurrency": _concurrency(settings)}


def _concurrency(settings: dict[str, Any]) -> int:
    by_threads = settings["budget_threads"] // max(1, settings["threads_per_job"])
    by_memory = settings["budget_memory_gb"] // max(1, settings["memory_per_job_gb"])
    return max(1, min(settings["max_concurrent"], by_threads, by_memory))


def create_run(db: Session, project: Project, wf: Workflow | None, v: WorkflowVersion | None, sample_ids: list[str],
               bindings: dict[str, dict[str, dict[str, Any]]], given: dict[str, Any], name: str | None,
               parent: BatchRun | None = None, reuse: dict[str, str] | None = None,
               changes: list[dict[str, Any]] | None = None, definition: dict[str, Any] | None = None) -> BatchRun:
    plan = plan_run(db, project, v, sample_ids, bindings, given) if definition is None else None
    definition = definition or v.definition
    if plan is not None and plan["problems"]:
        p = plan["problems"][0]
        raise WorkflowError(f"The run is blocked: {p['code']}", "wf_run_blocked",
                            problems="; ".join(sorted({x["code"] for x in plan["problems"]})))
    settings = plan["settings"] if plan else _settings(db, given)
    default_name = f"{wf.name} v{v.version}" if wf and v else "workflow run"
    run = BatchRun(project_id=project.id, workflow_version_id=v.id if v else None,
                   parent_run_id=parent.id if parent else None,
                   name=(name or default_name).strip()[:200], status="running",
                   priority=settings["priority"], settings=settings, definition=definition,
                   definition_sha256=core.checksum(definition), tools=tool_snapshot(definition),
                   sample_ids=list(sample_ids), branch_changes=changes,
                   correlation_id=errorlog.current_correlation() or errorlog.new_correlation_id(), started_at=now())
    db.add(run)
    db.flush()
    _expand(db, run, bindings, parent, reuse or {})
    db.commit()
    db.refresh(run)
    return run


def _expand(db: Session, run: BatchRun, bindings, parent: BatchRun | None, reuse: dict[str, str]) -> None:
    definition = run.definition
    order = core.topological_order(definition)
    by_id = {n["id"]: n for n in definition["nodes"]}
    items: dict[tuple[str, str], BatchItem] = {}
    old = {(i.node_id, i.sample_key): i for i in (parent.items if parent else [])}
    seq = 0
    for node_id in order:
        n = by_id[node_id]
        keys = [SET_KEY] if _scope(n["kind"]) == "set" else list(run.sample_ids)
        for key in keys:
            deps = []
            for e in core.upstream(definition, node_id):
                if _scope(by_id[e["source"]]["kind"]) == "sample" and key == SET_KEY:
                    deps.extend(items[(e["source"], s)].id for s in run.sample_ids)
                else:
                    deps.append(items[(e["source"], key)].id)
            item = BatchItem(run_id=run.id, seq=seq, node_id=node_id, node_kind=n["kind"],
                             sample_id=None if key == SET_KEY else key, sample_key=key, status="waiting", attempt=0,
                             depends_on=list(dict.fromkeys(deps)), job_ids=[])
            item.id = nodes_id()
            seq += 1
            prev = old.get((reuse.get(node_id, ""), key))
            if prev is not None and prev.status == "completed":
                item.status, item.outputs, item.inputs = "completed", prev.outputs, prev.inputs
                item.job_id, item.job_ids, item.reused_from_item_id = prev.job_id, list(prev.job_ids), prev.id
                item.started_at, item.finished_at = prev.started_at, prev.finished_at
            elif core.NODES[n["kind"]].source:
                _resolve_source_item(db, item, n, key, bindings)
            items[(node_id, key)] = item
            db.add(item)


def nodes_id() -> str:
    from app.db.base import new_uuid

    return new_uuid()


def _resolve_source_item(db: Session, item: BatchItem, n: dict[str, Any], key: str, bindings) -> None:
    sample = None if key == SET_KEY else db.get(Sample, key)
    override = bindings.get(key, {}).get(n["id"]) if sample else None
    item.started_at = item.finished_at = now()
    try:
        item.outputs = nodes.resolve_source(db, n["kind"], sample, n["params"], override,
                                            db.get(BatchRun, item.run_id).project_id)
        item.inputs = {"rule": "binding" if override else "arva_rule", "params": n["params"]}
        item.status = "completed"
    except nodes.LaunchRefused as exc:
        item.status = "failed"
        item.error = {"code": exc.code, "params": exc.params, "message": str(exc)}


# --- the queue -----------------------------------------------------------------------------------------------------

_local = threading.local()


@contextmanager
def _global_lock():
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            conn.commit()


def dispatch() -> None:
    """Bring every active run up to date and launch what may start now. Safe to call from anywhere: calls made while
    this thread is already dispatching (a job run synchronously by its launch) make the running call loop again."""
    if getattr(_local, "active", False):
        _local.again = True
        return
    _local.active = True
    try:
        for _ in range(1000):
            _local.again = False
            with _global_lock(), SessionLocal() as db:
                _dispatch_once(db)
            if not _local.again:
                break
    finally:
        _local.active = False


def dispatch_quietly(source: str) -> None:
    try:
        dispatch()
    except Exception as exc:  # the caller's own work (a job, a request) must not fail because of the queue
        errorlog.record("batch", "error", "batch_dispatch_failed", f"The batch queue could not be updated ({source})",
                        exc=exc)


def _active_runs(db: Session) -> list[BatchRun]:
    return list(db.scalars(select(BatchRun).where(BatchRun.status.in_(ACTIVE_RUN))
                           .order_by(BatchRun.priority.desc(), BatchRun.created_at)))


def _dispatch_once(db: Session) -> None:
    runs = _active_runs(db)
    # A cancelled run's running jobs stop a few seconds after the request; their items follow them here.
    stopping = db.scalars(select(BatchRun).where(BatchRun.status == "cancelled", BatchRun.id.in_(
        select(BatchItem.run_id).where(BatchItem.status.in_(IN_QUEUE))))).all()
    for run in [*runs, *stopping]:
        for item in run.items:
            if item.status in IN_QUEUE and item.job_id:
                _sync(db, run, item)
        _propagate(run)
        _finish_if_done(run)
    db.commit()
    res = effective_resources(db)
    used_threads = used_memory = in_queue = 0
    for run in runs:
        for item in run.items:
            if item.status in IN_QUEUE:
                in_queue += 1
                used_threads += (item.reserved or {}).get("threads", 0)
                used_memory += (item.reserved or {}).get("memory_gb", 0)
    for run in runs:
        if run.status != "running":
            continue
        run_queue = sum(1 for i in run.items if i.status in IN_QUEUE)
        status = {i.id: i for i in run.items}
        for item in run.items:
            if item.status != "waiting" or not _ready(item, status):
                continue
            spec = core.NODES[item.node_kind]
            if spec.internal:
                _run_internal(db, run, item, status)
                db.commit()
                continue
            t, m = run.settings["threads_per_job"], run.settings["memory_per_job_gb"]
            fits = in_queue == 0 or (used_threads + t <= res.max_threads and used_memory + m <= res.max_memory_gb)
            if run_queue >= run.settings["max_concurrent"] or not fits:
                break
            if _launch(db, run, item, status):
                run_queue += 1
                in_queue += 1
                used_threads += t
                used_memory += m
            db.commit()
        _propagate(run)
        _finish_if_done(run)
        db.commit()


def _ready(item: BatchItem, status: dict[str, BatchItem]) -> bool:
    deps = [status[d] for d in item.depends_on if d in status]
    if item.node_kind == "comparison_set":
        return all(d.status in TERMINAL_ITEM for d in deps)
    return all(d.status == "completed" for d in deps)


def _propagate(run: BatchRun) -> None:
    status = {i.id: i for i in run.items}
    changed = True
    while changed:
        changed = False
        for item in run.items:
            if item.status != "waiting" or item.node_kind == "comparison_set":
                continue
            bad = next((status[d] for d in item.depends_on if d in status and status[d].status in
                        ("failed", "cancelled", "skipped")), None)
            if bad is not None:
                item.status, item.finished_at = "skipped", now()
                item.error = {"code": "wf_upstream", "params": {"node": bad.node_id, "status": bad.status},
                              "message": f"{bad.node_id} ended with status {bad.status}"}
                changed = True


def _finish_if_done(run: BatchRun) -> None:
    if run.status not in ACTIVE_RUN or any(i.status not in TERMINAL_ITEM for i in run.items):
        return
    run.status = "completed" if all(i.status == "completed" for i in run.items) else "completed_with_errors"
    run.finished_at = now()


def _sync(db: Session, run: BatchRun, item: BatchItem) -> None:
    job = db.get(AnalysisJob, item.job_id)
    if job is None:
        _fail(item, "wf_job_missing", "the job record no longer exists")
        return
    if job.status is JobStatus.pending:
        item.status = "queued"
        _check_lost(db, item, job)
    elif job.status is JobStatus.running:
        item.status = "running"
        _check_lost(db, item, job)
    elif job.status is JobStatus.completed:
        try:
            item.outputs = nodes.KINDS[item.node_kind].outputs(db, job)
        except nodes.WaitForFollowUp as wait:
            item.status = "running"
            # Its task can be lost like the item's own (Redis keeps nothing across restarts).
            _check_lost(db, item, wait.follow)
            return
        except nodes.LaunchRefused as exc:
            _fail(item, exc.code, str(exc), **exc.params)
            return
        item.status, item.error, item.finished_at = "completed", None, job.finished_at or now()
    elif job.status is JobStatus.cancelled:
        item.status, item.finished_at = "cancelled", now()
        item.error = {"code": "wf_job_cancelled", "params": {"job_id": job.id}, "message": "the job was cancelled"}
    else:
        detail = job.error_detail or {}
        if item.attempt <= run.settings.get("max_retries", 0) and run.status != "cancelled":
            item.status = "waiting"
            item.error = {"code": "wf_retrying", "params": {"attempt": item.attempt, "job_id": job.id,
                                                            "reason": detail.get("code") or "job_failed"},
                          "message": job.error_message or ""}
            return
        _fail(item, detail.get("code") or "job_failed", job.error_message or "the job failed", job_id=job.id,
              **(detail.get("params") or {}))


def _check_lost(db: Session, item: BatchItem, job: AnalysisJob) -> None:
    """A job whose task the queue no longer holds (ARVA or Redis restarted while it waited or ran) is ended with the
    existing cancellation path, so the item can be resumed or retried."""
    if not get_settings().task_queue_async:
        return
    from app.services import jobs as jobs_service

    # A pending job whose task already failed (run_job raised before starting it) is lost as well.
    if not jobs_service.is_lost(job, jobs_service._rq_status(job.id)):
        return
    jobs_service.cancel_job(db, job.id)
    db.refresh(job)
    if job.status is JobStatus.cancelled:
        _fail(item, "wf_interrupted", "the job's task was lost (ARVA or its task queue restarted)", job_id=job.id)


def _fail(item: BatchItem, code: str, message: str, **params: Any) -> None:
    item.status, item.finished_at = "failed", now()
    item.error = {"code": code, "params": {k: v for k, v in params.items() if isinstance(v, str | int | float)},
                  "message": message}


def _upstream_inputs(run: BatchRun, item: BatchItem, status: dict[str, BatchItem]) -> dict[str, Any]:
    by_key = {(i.node_id, i.sample_key): i for i in run.items}
    out: dict[str, Any] = {}
    for e in core.upstream(run.definition, item.node_id):
        src = by_key.get((e["source"], item.sample_key)) or by_key.get((e["source"], SET_KEY))
        if src is None:
            continue
        out[e["target_port"]] = (src.outputs or {}).get(e["source_port"])
    return out


def _launch(db: Session, run: BatchRun, item: BatchItem, status: dict[str, BatchItem]) -> bool:
    node = next(n for n in run.definition["nodes"] if n["id"] == item.node_id)
    sample = db.get(Sample, item.sample_id) if item.sample_id else None
    inputs = _upstream_inputs(run, item, status)
    ctx = nodes.LaunchContext(db=db, sample=sample, project_id=run.project_id, params=dict(node["params"]),
                              inputs=inputs, threads=run.settings["threads_per_job"],
                              memory_gb=run.settings["memory_per_job_gb"], run_name=run.name)
    token = errorlog.correlation.set(run.correlation_id)
    item.attempt += 1
    item.inputs = {"upstream": inputs, "attempt": item.attempt, "confirmed_by_run": run.id}
    item.started_at = item.started_at or now()
    try:
        db.commit()
        job = nodes.KINDS[item.node_kind].launch(ctx)
    except nodes.LaunchRefused as exc:
        db.rollback()
        _fail(item, exc.code, str(exc), **exc.params)
        return False
    except Exception as exc:
        db.rollback()
        errorlog.record("batch", "error", "wf_launch_error", f"Launching {item.node_kind} failed", exc=exc)
        _fail(item, "wf_launch_error", f"{type(exc).__name__}: {exc}")
        return False
    finally:
        errorlog.correlation.reset(token)
    item.job_id = job.id
    item.job_ids = [*item.job_ids, job.id]
    item.status = "queued"
    item.error = None
    item.inputs = {**item.inputs, "params_sent": ctx.params}
    item.reserved = {"threads": run.settings["threads_per_job"], "memory_gb": run.settings["memory_per_job_gb"]}
    db.commit()
    db.refresh(item)
    job = db.get(AnalysisJob, item.job_id, populate_existing=True)
    if job is not None and job.status is not JobStatus.pending:
        _sync(db, run, item)
    return True


def _run_internal(db: Session, run: BatchRun, item: BatchItem, status: dict[str, BatchItem]) -> None:
    """The comparison set node: a set of the genomes the run's samples produced, saved in the run's project."""
    from app.services import comparative

    node = next(n for n in run.definition["nodes"] if n["id"] == item.node_id)
    item.started_at = now()
    deps = [status[d] for d in item.depends_on if d in status]
    missing = sorted({d.sample_id for d in deps if d.status != "completed" and d.sample_id})
    if missing and node["params"].get("require_all", True):
        item.status, item.finished_at = "skipped", now()
        item.error = {"code": "wf_set_incomplete", "params": {"missing": len(missing)},
                      "message": f"{len(missing)} sample(s) produced no genome"}
        return
    ids = []
    for d in deps:
        if d.status != "completed":
            continue
        for value in (d.outputs or {}).values():
            if isinstance(value, dict) and value.get("assembly_id"):
                ids.append(value["assembly_id"])
                break
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        _fail(item, "wf_set_samples", "a comparison needs at least 2 genomes", count=len(ids))
        return
    project = db.get(Project, run.project_id)
    name = node["params"].get("name") or f"{run.name} · {item.node_id}"
    try:
        cset = comparative.save_set(db, None, project, name[:200], f"Created by workflow run {run.id}", ids, {})
    except comparative.InputError as exc:
        _fail(item, exc.code, str(exc), **exc.params)
        return
    item.status, item.finished_at = "completed", now()
    item.inputs = {"assembly_ids": ids, "missing_sample_ids": missing}
    item.outputs = {"set": {"set_id": cset.id}}


# --- actions on a run ----------------------------------------------------------------------------------------------

def _serialised(action):
    """Run a run action under the dispatcher's lock, on freshly read rows: otherwise the dispatcher, between reading
    an item as 'waiting' and committing its launch, could queue a job of a run the action just cancelled or paused.
    Inside the dispatcher's own thread the lock is already held."""
    @functools.wraps(action)
    def wrapper(db: Session, run: BatchRun, *args, **kwargs):
        if getattr(_local, "active", False):
            return action(db, run, *args, **kwargs)
        with _global_lock():
            db.expire_all()
            return action(db, run, *args, **kwargs)
    return wrapper


@_serialised
def cancel_run(db: Session, run: BatchRun) -> BatchRun:
    from app.services import jobs as jobs_service

    if run.status not in ACTIVE_RUN:
        raise WorkflowError("This run has already finished", "wf_run_finished", status=run.status)
    run.status = "cancelled"
    db.commit()
    for item in run.items:
        if item.status in IN_QUEUE and item.job_id:
            try:
                jobs_service.cancel_job(db, item.job_id)
            except jobs_service.JobStateError:
                pass
            _sync(db, run, item)
        if item.status == "waiting":
            item.status, item.finished_at = "cancelled", now()
            item.error = {"code": "wf_run_cancelled", "params": {}, "message": "the run was cancelled"}
    run.finished_at = now()
    db.commit()
    return run


@_serialised
def pause_run(db: Session, run: BatchRun) -> BatchRun:
    if run.status != "running":
        raise WorkflowError("Only a running run can be paused", "wf_run_not_running", status=run.status)
    run.status = "paused"
    db.commit()
    return run


@_serialised
def resume_run(db: Session, run: BatchRun) -> BatchRun:
    """Continue a paused run, or rerun what did not complete in a finished, cancelled or interrupted one: failed,
    cancelled and skipped items are queued again (sources are looked up again); completed items keep their
    results. New jobs are created; earlier jobs and results are not touched."""
    items = [i for i in run.items if i.status in ("failed", "cancelled", "skipped")]
    if run.status == "running" and not items:
        raise WorkflowError("This run is already running", "wf_run_running", status=run.status)
    by_id = {n["id"]: n for n in run.definition["nodes"]}
    for item in items:
        item.status, item.error, item.finished_at = "waiting", None, None
        item.job_id = None
        if core.NODES[item.node_kind].source:
            _resolve_source_item(db, item, by_id[item.node_id], item.sample_key, {})
    run.status, run.finished_at = "running", None
    db.commit()
    return run


@_serialised
def update_settings(db: Session, run: BatchRun, priority: int | None, max_concurrent: int | None) -> BatchRun:
    settings = dict(run.settings)
    if priority is not None:
        settings["priority"] = run.priority = priority
    if max_concurrent is not None:
        settings["max_concurrent"] = max_concurrent
    run.settings = settings
    db.commit()
    return run


def _branch_plan(run: BatchRun, node_id: str, params: dict[str, Any]):
    if not any(n["id"] == node_id for n in run.definition["nodes"]):
        raise WorkflowError(f"No node {node_id} in this run", "wf_node_missing", node=node_id)
    full, problems = check_definition(core.with_params(run.definition, node_id, params))
    problems += availability(full, refresh=True)
    old_params = next(n for n in run.definition["nodes"] if n["id"] == node_id)["params"]
    new_params = next((n for n in full["nodes"] if n["id"] == node_id), {}).get("params") or {}
    changes = [{"node": node_id, **d} for d in core.param_diff(old_params, new_params)]
    return full, changes, core.reusable_nodes(run.definition, full), problems


def branch_preview(db: Session, run: BatchRun, node_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """What branch_run would do, without doing it: the parameter changes, the steps that run again (the changed one
    and everything after it) and those reused, the new jobs, the run's queue settings and resources, the tools, and
    anything that blocks it."""
    full, changes, reuse, problems = _branch_plan(run, node_id, params)
    runnable = [n for n in full["nodes"] if not (core.NODES[n["kind"]].source or core.NODES[n["kind"]].internal)]
    rerun = [n for n in runnable if n["id"] not in reuse]
    per_sample = sum(1 for n in rerun if _scope(n["kind"]) == "sample")
    settings = dict(run.settings)
    return {"node_id": node_id, "changes": changes, "problems": problems,
            "rerun": [{"node": n["id"], "kind": n["kind"], "scope": _scope(n["kind"])} for n in rerun],
            "reused": sorted(n["id"] for n in runnable if n["id"] in reuse),
            "samples": len(run.sample_ids), "jobs": per_sample * len(run.sample_ids) + len(rerun) - per_sample,
            "settings": settings, "concurrency": _concurrency(settings), "tools": tool_snapshot(full)}


def branch_run(db: Session, run: BatchRun, node_id: str, params: dict[str, Any], name: str | None) -> BatchRun:
    """A new run (branch) with one node's parameters changed: unchanged nodes upstream of the change reuse this
    run's results; the changed node and everything downstream run again as new jobs. Nothing is overwritten."""
    full, changes, reuse, problems = _branch_plan(run, node_id, params)
    if problems:
        raise WorkflowError(f"The changed workflow cannot run: {problems[0]['code']}", "wf_run_blocked",
                            problems="; ".join(sorted({p["code"] for p in problems})))
    if not changes:
        raise WorkflowError("These are the run's parameters already", "wf_branch_same", node=node_id)
    v = db.get(WorkflowVersion, run.workflow_version_id) if run.workflow_version_id else None
    wf = v.workflow if v else None
    project = db.get(Project, run.project_id)
    return create_run(db, project, wf, v, list(run.sample_ids), {}, run.settings,
                      name or f"{run.name} · {node_id}*", parent=run, reuse=reuse, changes=changes, definition=full)


# --- views and exports ---------------------------------------------------------------------------------------------

def _duration(item: BatchItem, jobs: dict[str, AnalysisJob]) -> float | None:
    job = jobs.get(item.job_id or "")
    return job.duration_seconds if job is not None else None


def _jobs(db: Session, run: BatchRun) -> dict[str, AnalysisJob]:
    ids = {j for i in run.items for j in (i.job_ids or [])}
    if not ids:
        return {}
    return {j.id: j for j in db.scalars(select(AnalysisJob).where(AnalysisJob.id.in_(ids)))}


def _counts(items: list[BatchItem]) -> dict[str, int]:
    out = {s: 0 for s in ("waiting", "queued", "running", "completed", "failed", "cancelled", "skipped")}
    for i in items:
        out[i.status] = out.get(i.status, 0) + 1
    return out


def run_summary(db: Session, run: BatchRun) -> dict[str, Any]:
    jobs = _jobs(db, run)
    runnable = [i for i in run.items if not core.NODES[i.node_kind].source]
    durations = [j.duration_seconds for j in jobs.values() if j.duration_seconds is not None]
    v = db.get(WorkflowVersion, run.workflow_version_id) if run.workflow_version_id else None
    return {"id": run.id, "project_id": run.project_id, "name": run.name, "status": run.status,
            "priority": run.priority, "settings": run.settings, "parent_run_id": run.parent_run_id,
            "workflow_id": v.workflow_id if v else None, "workflow_name": v.workflow.name if v else None,
            "version": v.version if v else None, "definition_sha256": run.definition_sha256,
            "samples": len(run.sample_ids), "counts": _counts(runnable), "total": len(runnable),
            "jobs_created": sum(len(i.job_ids or []) for i in runnable if not i.reused_from_item_id),
            "reused": sum(1 for i in runnable if i.reused_from_item_id),
            "job_seconds": round(sum(durations), 1), "created_at": run.created_at, "started_at": run.started_at,
            "finished_at": run.finished_at, "branch_changes": run.branch_changes,
            "estimated": {"threads_per_job": run.settings["threads_per_job"],
                          "memory_per_job_gb": run.settings["memory_per_job_gb"],
                          "concurrency": _concurrency(run.settings)}}


def _item_view(item: BatchItem, jobs: dict[str, AnalysisJob]) -> dict[str, Any]:
    job = jobs.get(item.job_id or "")
    return {"id": item.id, "node_id": item.node_id, "node_kind": item.node_kind, "sample_id": item.sample_id,
            "status": item.status, "attempt": item.attempt, "job_id": item.job_id, "job_ids": item.job_ids,
            "job_status": job.status.value if job else None, "tool": job.tool_name if job else None,
            "tool_version": job.tool_version if job else None,
            "duration_seconds": job.duration_seconds if job else None,
            "progress": (job.progress or {}).get("stage") if job else None,
            "outputs": item.outputs, "error": item.error, "reserved": item.reserved,
            "reused_from_item_id": item.reused_from_item_id, "depends_on": item.depends_on,
            "started_at": item.started_at, "finished_at": item.finished_at}


def run_detail(db: Session, run: BatchRun) -> dict[str, Any]:
    jobs = _jobs(db, run)
    codes = {s.id: s.sample_code for s in db.scalars(select(Sample).where(Sample.id.in_(run.sample_ids)))}
    per_sample = []
    for sid in run.sample_ids:
        items = [i for i in run.items if i.sample_id == sid and not core.NODES[i.node_kind].source]
        per_sample.append({"sample_id": sid, "sample_code": codes.get(sid), "counts": _counts(items),
                           "total": len(items),
                           "seconds": round(sum(_duration(i, jobs) or 0 for i in items), 1)})
    errors = [{"item_id": i.id, "node_id": i.node_id, "node_kind": i.node_kind, "sample_id": i.sample_id,
               "sample_code": codes.get(i.sample_id or ""), "status": i.status, **(i.error or {}),
               "job_id": i.job_id} for i in run.items if i.status in ("failed", "skipped") and i.error]
    return {**run_summary(db, run), "definition": run.definition, "tools": run.tools, "sample_codes": codes,
            "items": [_item_view(i, jobs) for i in run.items], "per_sample": per_sample, "errors": errors,
            "correlation_id": run.correlation_id}


def list_runs(db: Session, project_id: str | None) -> list[dict[str, Any]]:
    q = select(BatchRun).order_by(BatchRun.created_at.desc())
    if project_id:
        q = q.where(BatchRun.project_id == project_id)
    return [run_summary(db, r) for r in db.scalars(q.limit(200))]


def queue_overview(db: Session) -> dict[str, Any]:
    runs = _active_runs(db)
    res = effective_resources(db)
    reserved_threads = reserved_memory = 0
    counts = _counts([])
    for run in runs:
        for i in run.items:
            if core.NODES[i.node_kind].source:
                continue
            counts[i.status] += 1
            if i.status in IN_QUEUE:
                reserved_threads += (i.reserved or {}).get("threads", 0)
                reserved_memory += (i.reserved or {}).get("memory_gb", 0)
    return {"active_runs": len(runs), "counts": counts, "budget_threads": res.max_threads,
            "budget_memory_gb": res.max_memory_gb, "reserved_threads": reserved_threads,
            "reserved_memory_gb": reserved_memory, "profile": res.profile,
            "workers_note_code": "batch_workers_note"}


def _metrics(db: Session, outputs: dict[str, Any] | None, job: AnalysisJob | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for value in (outputs or {}).values():
        if not isinstance(value, dict):
            continue
        if value.get("annotation_id"):
            ann = db.get(Annotation, value["annotation_id"])
            if ann is not None:
                out.update({f"annotation.{k}": v for k, v in (ann.summary or {}).items()
                            if isinstance(v, int | float | str) and not isinstance(v, bool)})
        elif value.get("assembly_id"):
            a = db.get(Assembly, value["assembly_id"])
            if a is not None:
                out.update({f"assembly.{k}": a.stats.get(k) for k in ("contig_count", "total_length", "n50",
                                                                      "gc_percent")})
    if job is not None and isinstance(job.result_summary, dict):
        out.update({f"result.{k}": v for k, v in job.result_summary.items()
                    if isinstance(v, int | float | str) and not isinstance(v, bool) and not k.endswith("_id")})
    return out


def compare_runs(db: Session, a: BatchRun, b: BatchRun) -> dict[str, Any]:
    """Two runs side by side: the definitions' parameter differences by node, and for each node and sample both
    statuses, tools, durations and the numbers their outputs recorded (assembly statistics, annotation summary,
    the job's own result summary). Differences are reported, not interpreted."""
    nodes_a = {n["id"]: n for n in a.definition["nodes"]}
    nodes_b = {n["id"]: n for n in b.definition["nodes"]}
    params = []
    for nid in sorted(set(nodes_a) | set(nodes_b)):
        na, nb = nodes_a.get(nid), nodes_b.get(nid)
        if na is None or nb is None or na["kind"] != nb["kind"]:
            params.append({"node": nid, "path": "", "before": na and na["kind"], "after": nb and nb["kind"]})
            continue
        params.extend({"node": nid, **d} for d in core.param_diff(na["params"], nb["params"]))
    jobs = {**_jobs(db, a), **_jobs(db, b)}
    ib = {(i.node_id, i.sample_key): i for i in b.items}
    codes = {s.id: s.sample_code for s in db.scalars(
        select(Sample).where(Sample.id.in_(set(a.sample_ids) | set(b.sample_ids))))}
    rows = []
    for ia in a.items:
        if core.NODES[ia.node_kind].source:
            continue
        other = ib.get((ia.node_id, ia.sample_key))
        ja, jb = jobs.get(ia.job_id or ""), jobs.get(other.job_id or "") if other else None
        ma, mb = _metrics(db, ia.outputs, ja), _metrics(db, other.outputs if other else None, jb)
        rows.append({"node_id": ia.node_id, "node_kind": ia.node_kind, "sample_id": ia.sample_id,
                     "sample_code": codes.get(ia.sample_id or ""),
                     "a": {"status": ia.status, "job_id": ia.job_id, "tool_version": ja.tool_version if ja else None,
                           "duration_seconds": ja.duration_seconds if ja else None},
                     "b": None if other is None else {
                         "status": other.status, "job_id": other.job_id,
                         "tool_version": jb.tool_version if jb else None,
                         "duration_seconds": jb.duration_seconds if jb else None,
                         "reused": other.reused_from_item_id is not None},
                     "same_job": other is not None and ia.job_id is not None and ia.job_id == other.job_id,
                     "metrics": [{"key": k, "a": ma.get(k), "b": mb.get(k)} for k in sorted(set(ma) | set(mb))]})
    return {"a": run_summary(db, a), "b": run_summary(db, b), "parameters": params, "rows": rows}


CSV_COLUMNS = ("sample_code", "node_id", "node_kind", "status", "attempts", "job_id", "tool", "tool_version",
               "duration_seconds", "error_code", "error", "outputs", "metrics")


def consolidated_rows(db: Session, run: BatchRun) -> list[dict[str, Any]]:
    jobs = _jobs(db, run)
    codes = {s.id: s.sample_code for s in db.scalars(select(Sample).where(Sample.id.in_(run.sample_ids)))}
    rows = []
    for i in run.items:
        if core.NODES[i.node_kind].source:
            continue
        job = jobs.get(i.job_id or "")
        rows.append({"sample_code": codes.get(i.sample_id or "", "(set)"), "node_id": i.node_id,
                     "node_kind": i.node_kind, "status": i.status, "attempts": len(i.job_ids or []),
                     "job_id": i.job_id or "", "tool": job.tool_name if job else "",
                     "tool_version": job.tool_version if job else "",
                     "duration_seconds": job.duration_seconds if job else "",
                     "error_code": (i.error or {}).get("code", "") if i.status != "completed" else "",
                     "error": (i.error or {}).get("message", "") if i.status != "completed" else "",
                     "outputs": json.dumps(i.outputs or {}, sort_keys=True),
                     "metrics": json.dumps(_metrics(db, i.outputs, job), sort_keys=True)})
    return rows


def consolidated_csv(db: Session, run: BatchRun) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for row in consolidated_rows(db, run):
        w.writerow({k: _csv_safe(v) for k, v in row.items()})
    return buf.getvalue()


def _csv_safe(value: Any) -> Any:
    # A cell starting with = + - @ is a formula in spreadsheet programs.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def export_run(db: Session, run: BatchRun) -> dict[str, Any]:
    """Everything needed to reproduce and audit the run: the definition with every parameter, the tool snapshot
    (versions, lock checksums), and for every job its tool, version, parameters, inputs, outputs and the exact
    commands it executed."""
    jobs = _jobs(db, run)
    return {"format": core.FORMAT, "format_version": core.FORMAT_VERSION, "arva_export": "run",
            "run": run_summary(db, run), "definition_sha256": run.definition_sha256, "definition": run.definition,
            "tools": run.tools,
            "items": [{"node_id": i.node_id, "node_kind": i.node_kind, "sample_id": i.sample_id, "status": i.status,
                       "inputs": i.inputs, "outputs": i.outputs, "error": i.error, "job_ids": i.job_ids,
                       "reused_from_item_id": i.reused_from_item_id} for i in run.items],
            "jobs": [{"id": j.id, "job_type": j.job_type, "tool_name": j.tool_name, "tool_version": j.tool_version,
                      "tool_path": j.tool_path, "database_name": j.database_name,
                      "database_version": j.database_version, "database_checksum": j.database_checksum,
                      "parameters": j.parameters, "input_raw_file_ids": j.input_raw_file_ids,
                      "output_paths": j.output_paths, "commands": j.commands, "status": j.status.value,
                      "duration_seconds": j.duration_seconds, "resources": j.resources}
                     for j in sorted(jobs.values(), key=lambda j: j.created_at)],
            "nextflow": {"generated": False, "reason": NEXTFLOW_REASON},
            "exported_at": now().isoformat(timespec="seconds")}


REPORT_LABELS: dict[str, dict[str, str]] = {
    "en": {"title": "Workflow run", "run": "run", "workflow": "Workflow", "definition": "definition SHA-256",
           "status": "status",
           "summary": "{completed} of {total} steps completed, {failed} failed, {skipped} skipped, {cancelled} "
                      "cancelled; {jobs} job(s) created, {reused} step(s) reused from the parent run; total job time "
                      "{seconds} s.",
           "changed": "Changed parameters (branch)", "samples": "Samples", "sample": "Sample",
           "completed": "Completed", "failed": "Failed", "skipped": "Skipped", "job_time": "Job time (s)",
           "errors": "Errors", "step": "Step", "code": "Code", "reason": "Reason", "none": "None.", "tools": "Tools",
           "tool": "Tool", "version": "Version", "tool_status": "Status when the run was created",
           "methods": "Methods",
           "methods_text": "Each step ran as an ordinary ARVA analysis job, launched through the same checks as the "
                           "analysis's own dialog; the run's export lists every job's tool, version, parameters, "
                           "inputs, outputs and exact commands. The queue's concurrency, threads and memory per job "
                           "are ARVA's scheduling settings, not measurements."},
    "es": {"title": "Ejecución del flujo de trabajo", "run": "ejecución", "workflow": "Flujo de trabajo",
           "definition": "SHA-256 de la definición", "status": "estado",
           "summary": "{completed} de {total} pasos completados, {failed} fallidos, {skipped} omitidos, {cancelled} "
                      "cancelados; {jobs} trabajo(s) creado(s), {reused} paso(s) reutilizado(s) de la ejecución de "
                      "origen; tiempo total de los trabajos {seconds} s.",
           "changed": "Parámetros cambiados (rama)", "samples": "Muestras", "sample": "Muestra",
           "completed": "Completados", "failed": "Fallidos", "skipped": "Omitidos",
           "job_time": "Tiempo de los trabajos (s)", "errors": "Errores", "step": "Paso", "code": "Código",
           "reason": "Motivo", "none": "Ninguno.", "tools": "Herramientas", "tool": "Herramienta",
           "version": "Versión", "tool_status": "Estado cuando se creó la ejecución", "methods": "Métodos",
           "methods_text": "Cada paso se ejecutó como un trabajo de análisis normal de ARVA, lanzado con las mismas "
                           "comprobaciones que el diálogo propio del análisis; la exportación de la ejecución indica "
                           "la herramienta, la versión, los parámetros, las entradas, las salidas y los comandos "
                           "exactos de cada trabajo. La concurrencia de la cola, los hilos y la memoria por trabajo "
                           "son ajustes de planificación de ARVA, no mediciones."},
}
# Run, item and tool statuses as the report shows them; the export keeps the codes.
REPORT_STATUS = {"es": {"running": "en curso", "paused": "en pausa", "completed": "completado", "failed": "fallido",
                        "cancelled": "cancelado", "available": "disponible", "not_installed": "no instalado",
                        "incompatible": "incompatible"}}


def report_html(db: Session, run: BatchRun, lang: str = "en") -> str:
    """The run's summary page, in `lang` (en or es); error reasons are the jobs' recorded messages."""
    lang = "es" if lang == "es" else "en"
    L = REPORT_LABELS[lang]

    def st(code: str) -> str:
        return escape(REPORT_STATUS.get(lang, {}).get(code, code))

    d = run_detail(db, run)
    rows = "".join(
        f"<tr><td>{escape(r['sample_code'] or '')}</td><td>{r['counts']['completed']}/{r['total']}</td>"
        f"<td>{r['counts']['failed']}</td><td>{r['counts']['skipped']}</td><td>{r['seconds']}</td></tr>"
        for r in d["per_sample"])
    errs = "".join(
        f"<tr><td>{escape(e.get('sample_code') or '(set)')}</td><td>{escape(e['node_id'])}</td>"
        f"<td><code>{escape(str(e.get('code', '')))}</code></td><td>{escape(str(e.get('message', '')))}</td></tr>"
        for e in d["errors"])
    tools = "".join(f"<tr><td>{escape(t['name'])}</td><td>{escape(str(t['version']))}</td>"
                    f"<td>{st(t['status'])}</td></tr>" for t in run.tools.values())
    changes = "".join(f"<li><code>{escape(c['node'])}.{escape(c['path'])}</code>: {escape(json.dumps(c['before']))}"
                      f" → {escape(json.dumps(c['after']))}</li>" for c in run.branch_changes or [])
    c = d["counts"]
    summary = escape(L["summary"].format(completed=c["completed"], total=d["total"], failed=c["failed"],
                                         skipped=c["skipped"], cancelled=c["cancelled"], jobs=d["jobs_created"],
                                         reused=d["reused"], seconds=d["job_seconds"]))
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>ARVA · {L['run']} · {escape(run.name)}</title>
<style>body {{ font-family: Inter, -apple-system, Segoe UI, Arial, sans-serif; color:#0B132B; background:#F8FAFC;
margin:0; padding:32px 16px; line-height:1.5; }} main {{ max-width: 1000px; margin: 0 auto; background:#fff;
border:1px solid #E5E7EB; border-radius:12px; padding:32px; }} h2 {{ font-size: 18px; color:#1F3B8A; margin-top: 28px; }}
table {{ border-collapse: collapse; font-size: 13px; }} th, td {{ padding: 5px 8px; border-bottom: 1px solid #EEF2F7;
text-align: left; }} code {{ font-size: 11px; }} .muted {{ color:#64748B; font-size: 12px; }}</style></head><body><main>
<div style="letter-spacing:.3em;font-weight:600;color:#1F3B8A;font-size:13px">ARVA</div>
<h1>{L['title']} · {escape(run.name)}</h1>
<p class="muted">{L['workflow']} {escape(str(d['workflow_name']))} v{d['version']} · {L['definition']}
<code>{escape(run.definition_sha256)}</code> · {L['status']} {st(run.status)}</p>
<p>{summary}</p>
{f"<h2>{L['changed']}</h2><ul>" + changes + "</ul>" if changes else ""}
<h2>{L['samples']}</h2><table><tr><th>{L['sample']}</th><th>{L['completed']}</th><th>{L['failed']}</th>
<th>{L['skipped']}</th><th>{L['job_time']}</th></tr>
{rows}</table>
<h2>{L['errors']}</h2>{f"<table><tr><th>{L['sample']}</th><th>{L['step']}</th><th>{L['code']}</th><th>{L['reason']}</th></tr>"
                        + errs + "</table>" if errs else f"<p>{L['none']}</p>"}
<h2>{L['tools']}</h2><table><tr><th>{L['tool']}</th><th>{L['version']}</th><th>{L['tool_status']}</th></tr>{tools}</table>
<h2>{L['methods']}</h2><p>{L['methods_text']}</p>
</main></body></html>"""


def sample_branches(db: Session, sample: Sample) -> list[dict[str, Any]]:
    """The runs that included this sample, oldest first, each with its parent (the run it branched from), what
    changed, and this sample's steps: the timeline's branches. Every branch keeps its own jobs and results."""
    runs = [r for r in db.scalars(select(BatchRun).where(BatchRun.project_id == sample.project_id)
                                  .order_by(BatchRun.created_at)) if sample.id in (r.sample_ids or [])]
    jobs: dict[str, AnalysisJob] = {}
    for r in runs:
        jobs.update(_jobs(db, r))
    out = []
    for r in runs:
        steps = [_item_view(i, jobs) for i in r.items if i.sample_id in (sample.id, None)
                 and not core.NODES[i.node_kind].source]
        out.append({**run_summary(db, r), "steps": steps})
    return out
