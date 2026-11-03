import json
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import keep_visible, visible_projects
from app.api.deps import get_or_404, project_or_404
from app.core import errorlog
from app.core.messages import render
from app.db.session import get_db
from app.models import BatchRun, Workflow
from app.schemas.schemas import (
    BatchBranchIn,
    BatchRunIn,
    BatchSettingsUpdateIn,
    WorkflowCreateIn,
    WorkflowDefinitionIn,
    WorkflowDuplicateIn,
    WorkflowVersionIn,
)
from app.services import batches as svc

router = APIRouter(tags=["workflows and batches"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "wf_template_unknown": "There is no predefined workflow {key}.",
    "wf_version_missing": "This workflow has no version {version}.",
    "wf_run_blocked": "The run cannot start: {problems}",
    "wf_run_confirm": "Confirm the summary of the run first.",
    "wf_run_finished": "This run has already finished (status {status}).",
    "wf_run_not_running": "Only a running run can be paused (this one is {status}).",
    "wf_run_running": "This run is already running.",
    "wf_node_missing": "This run has no step {node}.",
    "wf_branch_same": "These are the run's parameters already; change at least one to make a branch.",
    "wf_sample_foreign": "Sample {sample_id} is not a sample of this project, or is listed twice.",
    "wf_format": "This is not an ARVA workflow definition (format {format}, version {version}).",
}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"}


def _coded(code: int, key: str, message: str | None = None, **params) -> JSONResponse:
    text = message if message is not None else render(MESSAGES[key], params)
    return JSONResponse(status_code=code, content={"detail": text, "code": key, "params": params})


def _error(exc: svc.WorkflowError, code: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    params = {k: v for k, v in exc.params.items() if isinstance(v, str | int | float)}
    text = render(MESSAGES[exc.code], params) if exc.code in MESSAGES else str(exc)
    return JSONResponse(status_code=code, content={"detail": text, "code": exc.code, "params": params})


def _workflow(db: Session, workflow_id: str) -> Workflow:
    return get_or_404(db, Workflow, workflow_id, "Workflow")


def _run(db: Session, run_id: str) -> BatchRun:
    return get_or_404(db, BatchRun, run_id, "Run")


def _filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:80] or "workflow"


@router.get("/workflows/catalogue")
def workflow_catalogue():
    """The node kinds (typed ports, scope, tools by method with their availability here, the parameter schema of
    the analysis's request model) and the predefined workflows with what they need."""
    return svc.catalogue()


@router.post("/workflows/validate")
def validate_workflow(payload: WorkflowDefinitionIn):
    """A definition's problems (graph and parameters) and the tools it needs that are not available here."""
    full, problems = svc.check_definition(payload.model_dump())
    return {"definition": full, "problems": problems, "unavailable": svc.availability(full),
            "definition_sha256": svc.core.checksum(full)}


@router.get("/workflows")
def list_workflows(db: Session = Depends(get_db)):
    rows = db.scalars(select(Workflow).order_by(Workflow.updated_at.desc())).all()
    return [svc.workflow_view(db, wf) for wf in rows]


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(payload: WorkflowCreateIn, db: Session = Depends(get_db)):
    try:
        wf = svc.create_workflow(db, payload.name, payload.description, payload.template_key,
                                 payload.definition.model_dump() if payload.definition else None)
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc)
    return svc.workflow_view(db, wf)


@router.post("/workflows/import", status_code=status.HTTP_201_CREATED)
def import_workflow(payload: dict[str, Any] = Body(...), name: str = Query(..., min_length=1, max_length=200),
                    db: Session = Depends(get_db)):
    """Create a workflow from an ARVA export (or a bare definition); it is checked as any other definition."""
    try:
        definition = WorkflowDefinitionIn.model_validate(svc.import_definition(payload)).model_dump()
        wf = svc.create_workflow(db, name, None, None, definition)
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc)
    except ValueError as exc:
        return _coded(status.HTTP_400_BAD_REQUEST, "wf_format", f"Not an ARVA workflow definition: {exc}",
                      format="?", version="?")
    return svc.workflow_view(db, wf)


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, version: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    wf = _workflow(db, workflow_id)
    out = svc.workflow_view(db, wf)
    if version is not None:
        try:
            v = svc.version_of(wf, version)
        except svc.WorkflowError as exc:
            return _error(exc, status.HTTP_404_NOT_FOUND)
        out["selected"] = {"version": v.version, "definition": v.definition, "definition_sha256": v.definition_sha256}
    return out


@router.post("/workflows/{workflow_id}/versions", status_code=status.HTTP_201_CREATED)
def save_version(workflow_id: str, payload: WorkflowVersionIn, db: Session = Depends(get_db)):
    """Save the edited graph as the next version; earlier versions, and the runs made with them, stay as they are."""
    wf = _workflow(db, workflow_id)
    if payload.name:
        wf.name = payload.name.strip()
    if payload.description is not None:
        wf.description = payload.description
    try:
        svc.add_version(db, wf, payload.definition.model_dump(), payload.note)
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc)
    return svc.workflow_view(db, wf)


@router.post("/workflows/{workflow_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_workflow(workflow_id: str, payload: WorkflowDuplicateIn, db: Session = Depends(get_db)):
    try:
        copy = svc.duplicate(db, _workflow(db, workflow_id), payload.name, payload.version)
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc)
    return svc.workflow_view(db, copy)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """Delete the workflow and its versions. Its runs keep their own copy of the definition they ran."""
    db.delete(_workflow(db, workflow_id))
    db.commit()


@router.get("/workflows/{workflow_id}/export")
def export_workflow(workflow_id: str, version: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    """The reproducible definition (JSON): every parameter explicit, its checksum, the tools' versions and lock
    checksums as installed here. No Nextflow file: see `nextflow.reason` in the export."""
    wf = _workflow(db, workflow_id)
    try:
        v = svc.version_of(wf, version)
    except svc.WorkflowError as exc:
        return _error(exc, status.HTTP_404_NOT_FOUND)
    body = json.dumps(svc.export_definition(wf, v), indent=2, default=str)
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{_filename(wf.name)}_v{v.version}.arva-workflow.json"'})


# --- runs ----------------------------------------------------------------------------------------------------------

def _version(db: Session, payload: BatchRunIn):
    wf = _workflow(db, payload.workflow_id)
    return wf, svc.version_of(wf, payload.version)


@router.post("/batches/preview")
def preview_batch(payload: BatchRunIn, db: Session = Depends(get_db)):
    """What the run would do, per sample and step, with the queue settings and estimated resources. Nothing runs."""
    project = project_or_404(db, payload.project_id)
    try:
        _, v = _version(db, payload)
        return svc.plan_run(db, project, v, payload.sample_ids, payload.bindings, payload.settings.model_dump())
    except svc.WorkflowError as exc:
        return _error(exc)


@router.post("/batches", status_code=status.HTTP_201_CREATED)
def start_batch(payload: BatchRunIn, db: Session = Depends(get_db)):
    """Create the run and queue it. Each step becomes an ordinary analysis job when the queue reaches it."""
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "wf_run_confirm")
    project = project_or_404(db, payload.project_id)
    try:
        wf, v = _version(db, payload)
        run = svc.create_run(db, project, wf, v, payload.sample_ids, payload.bindings, payload.settings.model_dump(),
                             payload.name)
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc, status.HTTP_409_CONFLICT if exc.code == "wf_run_blocked" else status.HTTP_400_BAD_REQUEST)
    svc.dispatch_quietly("run created")
    db.expire_all()
    return svc.run_detail(db, _run(db, run.id))


@router.get("/batches")
def list_batches(request: Request, project_id: str | None = Query(None, max_length=36), db: Session = Depends(get_db)):
    return keep_visible(svc.list_runs(db, project_id), visible_projects(request))


@router.get("/batches/queue")
def batch_queue(db: Session = Depends(get_db)):
    """Every active run's items by status and the threads and memory reserved against the profile's budget."""
    return svc.queue_overview(db)


@router.get("/batches/compare")
def compare_batches(a: str = Query(..., max_length=36), b: str = Query(..., max_length=36),
                    db: Session = Depends(get_db)):
    return svc.compare_runs(db, _run(db, a), _run(db, b))


@router.get("/batches/{run_id}")
def get_batch(run_id: str, db: Session = Depends(get_db)):
    return svc.run_detail(db, _run(db, run_id))


def _action(db: Session, run_id: str, fn) -> Any:
    try:
        fn(db, _run(db, run_id))
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc, status.HTTP_409_CONFLICT)
    svc.dispatch_quietly("run changed")
    db.expire_all()
    return svc.run_detail(db, _run(db, run_id))


@router.post("/batches/{run_id}/cancel")
def cancel_batch(run_id: str, db: Session = Depends(get_db)):
    return _action(db, run_id, svc.cancel_run)


@router.post("/batches/{run_id}/pause")
def pause_batch(run_id: str, db: Session = Depends(get_db)):
    return _action(db, run_id, svc.pause_run)


@router.post("/batches/{run_id}/resume")
def resume_batch(run_id: str, db: Session = Depends(get_db)):
    return _action(db, run_id, svc.resume_run)


@router.put("/batches/{run_id}/settings")
def update_batch(run_id: str, payload: BatchSettingsUpdateIn, db: Session = Depends(get_db)):
    return _action(db, run_id, lambda d, r: svc.update_settings(d, r, payload.priority, payload.max_concurrent))


@router.post("/batches/{run_id}/branch/preview")
def preview_branch(run_id: str, payload: BatchBranchIn, db: Session = Depends(get_db)):
    """What the branch would run again and reuse, its jobs, settings and tools, and what blocks it. Nothing runs."""
    try:
        return svc.branch_preview(db, _run(db, run_id), payload.node_id, payload.params)
    except svc.WorkflowError as exc:
        return _error(exc)


@router.post("/batches/{run_id}/branch", status_code=status.HTTP_201_CREATED)
def branch_batch(run_id: str, payload: BatchBranchIn, db: Session = Depends(get_db)):
    """A new run with one step's parameters changed: the steps before it reuse this run's results, the changed step
    and everything after it run again as new jobs. This run and its results are not changed."""
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "wf_run_confirm")
    try:
        new = svc.branch_run(db, _run(db, run_id), payload.node_id, payload.params, payload.name)
    except svc.WorkflowError as exc:
        db.rollback()
        return _error(exc, status.HTTP_409_CONFLICT if exc.code == "wf_run_blocked" else status.HTTP_400_BAD_REQUEST)
    svc.dispatch_quietly("branch created")
    db.expire_all()
    return svc.run_detail(db, _run(db, new.id))


@router.get("/batches/{run_id}/errors")
def batch_error_log(run_id: str, db: Session = Depends(get_db)):
    """The error log entries of this run's requests and jobs (matched by the run's correlation id), newest first."""
    from app.api.routes.diagnostics import _summary

    run = _run(db, run_id)
    if not run.correlation_id:
        return []
    entries = errorlog.read(limit=200, match=lambda e: e.get("correlation_id") == run.correlation_id)
    return [_summary(e) for e in entries]


@router.get("/batches/{run_id}/export.json")
def export_batch(run_id: str, db: Session = Depends(get_db)):
    run = _run(db, run_id)
    body = json.dumps(svc.export_run(db, run), indent=2, default=str)
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{_filename(run.name)}_run.json"'})


@router.get("/batches/{run_id}/table.csv")
def batch_table(run_id: str, db: Session = Depends(get_db)):
    """The consolidated table: one row per step and sample with status, job, tool, version, time, outputs and the
    numbers the outputs recorded."""
    run = _run(db, run_id)
    return Response(svc.consolidated_csv(db, run), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{_filename(run.name)}_table.csv"'})


@router.get("/batches/{run_id}/report.html")
def batch_report(run_id: str, db: Session = Depends(get_db)):
    return HTMLResponse(svc.report_html(db, _run(db, run_id)), headers=_SAFE_HEADERS)


@router.get("/samples/{sample_id}/batches")
def sample_batches(sample_id: str, db: Session = Depends(get_db)):
    """The workflow runs that included the sample and how they branch from each other (the analysis timeline)."""
    from app.api.deps import sample_or_404

    return svc.sample_branches(db, sample_or_404(db, sample_id))
