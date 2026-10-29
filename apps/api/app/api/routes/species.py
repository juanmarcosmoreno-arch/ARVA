from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import Assembly, Sample, SpeciesResult
from app.schemas.schemas import (
    AnalysisJobRead,
    SpeciesOverviewRead,
    SpeciesPlanRead,
    SpeciesPreviewRequest,
    SpeciesProjectOverviewRead,
    SpeciesRequest,
    SpeciesResultRead,
)
from app.services import mlst as mlst_svc
from app.services import species as svc
from app.services.jobs import create_species_job
from app.storage import get_storage

router = APIRouter(tags=["species"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "species_confirm": "Confirm the summary of the run first.",
    "species_blocked": "The species identification cannot run here: {problems}",
}
_MEDIA = {"output": "text/plain", "log": "text/plain", "references": "text/plain", "info": "text/plain",
          "info_header": "text/plain", "inspect": "text/plain", "summary_bacteria": "text/plain",
          "summary_archaea": "text/plain", "input": "text/plain"}
_SUFFIX = {"output": "tsv", "log": "log", "references": "references.txt", "info": "mash_info.tsv",
           "info_header": "mash_info_header.txt", "inspect": "sylph_inspect.yaml",
           "summary_bacteria": "bac120.summary.tsv", "summary_archaea": "ar53.summary.tsv", "input": "input.fna"}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}


def _coded(code: int, key: str, **params) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": render(MESSAGES[key], params), "code": key,
                                                   "params": params})


def _assembly(db: Session, assembly_id: str) -> tuple[Sample, Assembly]:
    try:
        a = mlst_svc.assembly_for(db, assembly_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assembly not found") from None
    except mlst_svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return db.get(Sample, a.sample_id), a


def _plan(db: Session, sample: Sample, a: Assembly, method: str, database_id: str | None) -> dict:
    try:
        return svc.plan(db, sample, a, method, database_id)
    except mlst_svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/assemblies/{assembly_id}/species/preview", response_model=SpeciesPlanRead)
def preview_species(assembly_id: str, payload: SpeciesPreviewRequest, db: Session = Depends(get_db)):
    """What a species identification of this assembly would do here: the method's tool, the databases of its kind
    (reference genome collections for FastANI and skani), the resources, the MLST call and annotation organism used
    for the consistency checks, and anything that blocks the run. Only version and help checks run."""
    sample, a = _assembly(db, assembly_id)
    return _plan(db, sample, a, payload.method, payload.database_id)


@router.post("/assemblies/{assembly_id}/species", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_species(assembly_id: str, payload: SpeciesRequest, db: Session = Depends(get_db)):
    """Identify the assembly's species with one method against one database in a background job. Threads come from
    the performance profile unless given; GTDB-Tk is refused when the profile's memory is below its documented
    requirement."""
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "species_confirm")
    plan = _plan(db, sample, a, payload.method, payload.database_id)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "species_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    record = svc.chosen_database(db, plan["database_kind"], plan["database"]["id"])
    provenance = {"synthetic_evidence": plan["assembly"]["synthetic_evidence"], "context": plan["context"],
                  "database_id": record.id}
    return _tool_call(create_species_job, db, sample, a, payload.method, payload.threads, record, provenance)


@router.get("/samples/{sample_id}/species", response_model=list[SpeciesResultRead])
def list_sample_results(sample_id: str, db: Session = Depends(get_db)):
    sample_or_404(db, sample_id)
    return db.scalars(select(SpeciesResult).where(SpeciesResult.sample_id == sample_id)
                      .order_by(SpeciesResult.created_at.desc())).all()


@router.get("/projects/{project_id}/species", response_model=SpeciesProjectOverviewRead)
def project_overview(project_id: str, db: Session = Depends(get_db)):
    """Every sample of the project with its most recent species result, and the species found."""
    return svc.project_overview(db, project_or_404(db, project_id))


@router.get("/projects/{project_id}/species.csv")
def project_csv(project_id: str, db: Session = Depends(get_db)):
    """Every species result of the project's samples, one row each (CSV)."""
    project = project_or_404(db, project_id)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in project.name)[:80]
    return Response(svc.project_csv(db, project), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ARVA_{safe}_species.csv"', **_SAFE_HEADERS})


@router.get("/species", response_model=SpeciesOverviewRead)
def overview(limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)):
    """Every project with how many samples have a species result, and the most recent results across projects."""
    return svc.overview(db, limit)


@router.get("/species/{result_id}", response_model=SpeciesResultRead)
def get_result(result_id: str, db: Session = Depends(get_db)):
    return get_or_404(db, SpeciesResult, result_id, "Species result")


@router.get("/species/{result_id}/files/{kind}")
def download_file(result_id: str, kind: str, db: Session = Depends(get_db)):
    """One of the tool's own files (results, log, the reference list, Mash or sylph database facts) or the staged
    input, unchanged."""
    s = get_or_404(db, SpeciesResult, result_id, "Species result")
    entry = (s.files or {}).get(kind)
    if kind not in _MEDIA or entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This species result has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    return FileResponse(path, media_type=_MEDIA[kind], headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(Sample, s.sample_id), s, _SUFFIX[kind]))
