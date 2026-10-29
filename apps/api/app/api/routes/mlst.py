from arva_tools.mlst import DEFAULT_EXCLUDE, MlstParams
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import Assembly, MlstResult, Sample
from app.schemas.schemas import (
    AnalysisJobRead,
    MlstOverviewRead,
    MlstPlanRead,
    MlstPreviewRequest,
    MlstProjectOverviewRead,
    MlstRequest,
    MlstResultRead,
)
from app.services import mlst as svc
from app.services.jobs import create_mlst_job
from app.services.performance import effective_resources
from app.storage import get_storage

router = APIRouter(tags=["mlst"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "mlst_confirm": "Confirm the summary of the run first.",
    "mlst_blocked": "mlst cannot run here: {problems}",
}
_MEDIA = {"tsv": "text/plain", "json": "application/json", "novel": "text/plain", "log": "text/plain",
          "input": "text/plain"}
_SUFFIX = {"tsv": "tsv", "json": "json", "novel": "novel_alleles.fasta", "log": "stderr.log", "input": "input.fna"}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}


def _coded(code: int, key: str, **params) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": render(MESSAGES[key], params), "code": key,
                                                   "params": params})


def _assembly(db: Session, assembly_id: str) -> tuple[Sample, Assembly]:
    try:
        a = svc.assembly_for(db, assembly_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assembly not found") from None
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return db.get(Sample, a.sample_id), a


@router.post("/assemblies/{assembly_id}/mlst/preview", response_model=MlstPlanRead)
def preview_mlst(assembly_id: str, payload: MlstPreviewRequest, db: Session = Depends(get_db)):
    """What an mlst run of this assembly would do here: mlst, the PubMLST schemes it bundles (their date, the terms,
    the scheme list), mlst's defaults as its --help states them, and the assembly. Only version and help checks run."""
    sample, a = _assembly(db, assembly_id)
    try:
        return svc.plan(db, sample, a, payload.scheme)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/assemblies/{assembly_id}/mlst", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_mlst(assembly_id: str, payload: MlstRequest, db: Session = Depends(get_db)):
    """Type the assembly with mlst in one background job. With a chosen scheme ARVA passes --minscore 0 and no
    --exclude, as mlst would apply them anyway; otherwise every option is passed with its value."""
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "mlst_confirm")
    s = payload.settings
    try:
        plan = svc.plan(db, sample, a, s.scheme)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "mlst_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    exclude = [] if s.scheme else list(DEFAULT_EXCLUDE if s.exclude is None else s.exclude)
    params = MlstParams(scheme=s.scheme, minid=s.minid, mincov=s.mincov, minscore=0 if s.scheme else s.minscore,
                        exclude=exclude, threads=payload.threads or effective_resources(db).threads)
    record = svc.mlst_database(db, plan["database"]["id"])
    provenance = {"synthetic_evidence": plan["assembly"]["synthetic_evidence"],
                  "scheme_mode": "chosen" if s.scheme else "detected"}
    return _tool_call(create_mlst_job, db, sample, a, params, record, provenance)


@router.get("/samples/{sample_id}/mlst", response_model=list[MlstResultRead])
def list_sample_results(sample_id: str, db: Session = Depends(get_db)):
    sample_or_404(db, sample_id)
    return db.scalars(select(MlstResult).where(MlstResult.sample_id == sample_id)
                      .order_by(MlstResult.created_at.desc())).all()


@router.get("/projects/{project_id}/mlst", response_model=MlstProjectOverviewRead)
def project_overview(project_id: str, db: Session = Depends(get_db)):
    """Every sample of the project with its most recent MLST result, and the STs found."""
    return svc.project_overview(db, project_or_404(db, project_id))


@router.get("/projects/{project_id}/mlst.csv")
def project_csv(project_id: str, db: Session = Depends(get_db)):
    """Every MLST result of the project's samples, one row each (CSV)."""
    project = project_or_404(db, project_id)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in project.name)[:80]
    return Response(svc.project_csv(db, project), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ARVA_{safe}_mlst.csv"', **_SAFE_HEADERS})


@router.get("/mlst", response_model=MlstOverviewRead)
def overview(limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)):
    """Every project with how many samples have an MLST result, and the most recent results across projects."""
    return svc.overview(db, limit)


@router.get("/mlst/{result_id}", response_model=MlstResultRead)
def get_result(result_id: str, db: Session = Depends(get_db)):
    return get_or_404(db, MlstResult, result_id, "MLST result")


@router.get("/mlst/{result_id}/files/{kind}")
def download_file(result_id: str, kind: str, db: Session = Depends(get_db)):
    """One of mlst's own files (TSV, JSON, novel alleles, log) or the staged input, unchanged."""
    m = get_or_404(db, MlstResult, result_id, "MLST result")
    entry = (m.files or {}).get(kind)
    if kind not in _MEDIA or entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This MLST result has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    return FileResponse(path, media_type=_MEDIA[kind], headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(Sample, m.sample_id), m, _SUFFIX[kind]))
