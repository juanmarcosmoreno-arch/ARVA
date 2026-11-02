from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import AnalysisJob, ReferenceDatabase, Sample
from app.schemas.schemas import (
    TYPING_SETTINGS,
    AnalysisJobRead,
    TypingPlanRead,
    TypingPreviewRequest,
    TypingProjectRead,
    TypingRequest,
    TypingSampleRead,
)
from app.services import staph_typing as svc
from app.services import typing_modules as tm
from app.services.jobs import create_typing_job
from app.services.mlst import InputError as AssemblyInputError
from app.services.mlst import assembly_for
from app.storage import get_storage

router = APIRouter(tags=["species-specific typing"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "typing_unknown_module": "There is no typing module {module}.",
    "typing_confirm": "Confirm the summary of the run first.",
    "typing_blocked": "{tool} cannot run here: {problems}",
    "typing_settings_invalid": "The settings are not valid for {method}: {detail}",
    "typing_not_applicable": "The species evidence does not support {module} ({status}); confirm the override to run "
                             "it anyway.",
}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}


def _coded(code: int, key: str, **params) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": render(MESSAGES[key], params), "code": key,
                                                   "params": params})


def _assembly(db: Session, assembly_id: str):
    try:
        a = assembly_for(db, assembly_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assembly not found") from None
    except AssemblyInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return db.get(Sample, a.sample_id), a


def _module(module: str):
    if module != svc.MODULE.key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, render(MESSAGES["typing_unknown_module"], {"module": module}))
    return tm.MODULES[module]


def _plan(db: Session, sample, a, method: str, database_id: str | None):
    try:
        return svc.plan(db, sample, a, method, database_id)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/typing/modules")
def list_modules(db: Session = Depends(get_db)):
    """The species-specific typing modules ARVA knows: the taxa each applies to, its steps, and per step the tool
    and database it needs and what is missing here (with how to install it)."""
    return [{**tm.describe(m), "requirements": tm.requirements(db, m)} for m in tm.MODULES.values()]


@router.post("/assemblies/{assembly_id}/typing/{module}/preview", response_model=TypingPlanRead)
def preview_typing(assembly_id: str, module: str, payload: TypingPreviewRequest, db: Session = Depends(get_db)):
    """What one step of the module would do on this assembly here: the tool, the Ridom files (spa) or the data the
    tool bundles, the settings ARVA passes and the tool's defaults, and the species evidence."""
    _module(module)
    sample, a = _assembly(db, assembly_id)
    return _plan(db, sample, a, payload.method, payload.database_id)


@router.post("/assemblies/{assembly_id}/typing/{module}", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_typing(assembly_id: str, module: str, payload: TypingRequest, db: Session = Depends(get_db)):
    """Run one step of the module on the assembly in a background job. A module the species evidence does not
    support runs only with override_applicability, which the result records."""
    mod = _module(module)
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "typing_confirm")
    try:
        settings = TYPING_SETTINGS[payload.method].model_validate(payload.settings)
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return _coded(status.HTTP_422_UNPROCESSABLE_CONTENT, "typing_settings_invalid", method=payload.method,
                      detail=detail)
    plan = _plan(db, sample, a, payload.method, payload.database_id)
    found = plan["applicability"]
    if found["override_required"] and not payload.override_applicability:
        return _coded(status.HTTP_409_CONFLICT, "typing_not_applicable", module=mod.name, status=found["status"])
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "typing_blocked", tool=plan["tool"]["name"],
                      problems="; ".join(p["message"] for p in plan["problems"]))
    params = svc.METHODS[payload.method]["params"](**settings.model_dump())
    record = db.get(ReferenceDatabase, plan["database"]["id"]) if plan["database"] else None
    provenance = {"synthetic_evidence": plan["assembly"]["synthetic_evidence"],
                  "applicability": {k: found[k] for k in ("status", "checks", "evidence")},
                  "override": bool(found["override_required"] and payload.override_applicability)}
    if record is not None:
        provenance["database_terms"] = {k: plan["database"][k] for k in ("licence", "licence_url", "citation")}
    return _tool_call(create_typing_job, db, sample, a, mod.key, payload.method, params, record, plan["bundled"],
                      provenance)


@router.get("/samples/{sample_id}/typing", response_model=TypingSampleRead)
def sample_typing(sample_id: str, db: Session = Depends(get_db)):
    """The typing modules with their requirements here, and per assembly of the sample each module's applicability,
    the S. aureus summary card and the step results, newest first."""
    sample_or_404(db, sample_id)
    return svc.sample_view(db, sample_id)


@router.get("/typing/runs/{job_id}/files/{name:path}")
def download_typing_file(job_id: str, name: str, db: Session = Depends(get_db)):
    """One of the tool's own files (tables, logs) or the staged input, unchanged, as plain text."""
    job = get_or_404(db, AnalysisJob, job_id, "Typing run")
    entry = ((job.result_summary or {}).get("files") or {}).get(name)
    if job.job_type != svc.TYPING_JOB or entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This run has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    return FileResponse(path, media_type="text/plain", headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(Sample, job.sample_id), job, name))


@router.get("/projects/{project_id}/typing/{module}.csv")
def project_typing_csv(project_id: str, module: str, db: Session = Depends(get_db)):
    """The project's S. aureus summaries, one row per typed sample, every part with its status and source (CSV)."""
    _module(module)
    project = project_or_404(db, project_id)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in project.name)[:80]
    return Response(svc.project_csv(db, project), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ARVA_{safe}_{module}.csv"',
                             **_SAFE_HEADERS})


@router.get("/projects/{project_id}/typing/{module}", response_model=TypingProjectRead)
def project_typing(project_id: str, module: str, db: Session = Depends(get_db)):
    """Per sample: the S. aureus summary of its most recently typed assembly (null: no step ran)."""
    _module(module)
    return svc.project_overview(db, project_or_404(db, project_id))
