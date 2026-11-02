from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import project_or_404
from app.api.routes.comparative import _SAFE_HEADERS, _coded, _input_error, _result, _set
from app.api.routes.tools import _tool_call
from app.db.session import get_db
from app.models import ComparisonResult, ComparisonSet
from app.schemas.schemas import AnalysisJobRead, ComparisonPlanRead, PangenomeIn
from app.services import comparative as comparative_svc
from app.services import pangenome as svc
from app.services.comparative import InputError
from app.services.jobs import create_pangenome_job

router = APIRouter(tags=["comparative genomics"])


def _plan(db: Session, set_id: str, payload: PangenomeIn) -> dict:
    cset = _set(db, set_id)
    return {**svc.plan(db, cset, payload.method, payload.genomes, payload.panaroo.model_dump(),
                       payload.ppanggolin.model_dump(), payload.categories.model_dump(), payload.curves.model_dump(),
                       payload.threads), "set_id": cset.id}


@router.post("/comparisons/{set_id}/pangenome/preview", response_model=ComparisonPlanRead)
def preview_pangenome(set_id: str, payload: PangenomeIn, db: Session = Depends(get_db)):
    """What a pangenome run would do: the method and every option, each genome's annotation (annotator, version,
    database, GFF3 checksum) and whether the annotations agree, the category thresholds and the curve sampling."""
    try:
        return _plan(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)


@router.post("/comparisons/{set_id}/pangenome", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_pangenome(set_id: str, payload: PangenomeIn, db: Session = Depends(get_db)):
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "comparison_confirm")
    try:
        plan = _plan(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "comparison_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    return _tool_call(create_pangenome_job, db, project_or_404(db, _set(db, set_id).project_id), plan)


def _pangenome(db: Session, result_id: str) -> ComparisonResult:
    r = _result(db, result_id)
    if r.analysis != "pangenome":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This result is not a pangenome")
    return r


def _missing(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@router.get("/comparisons/results/{result_id}/families/{index}.fasta")
def pangenome_family_fasta(result_id: str, index: int, molecule: str = Query("nucleotide",
                                                                           pattern="^(nucleotide|protein)$"),
                           db: Session = Depends(get_db)):
    r = _pangenome(db, result_id)
    try:
        text = svc.family_fasta(r, index, molecule)
        name = (svc.data(r) or {})["families"][index]["name"]
    except (LookupError, FileNotFoundError, TypeError) as exc:
        return _missing(exc)
    filename = comparative_svc.download_name(db.get(ComparisonSet, r.set_id), r,
                                             f"{name}.{'fna' if molecule == 'nucleotide' else 'faa'}")
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', **_SAFE_HEADERS})


@router.get("/comparisons/results/{result_id}/families/{index}")
def pangenome_family(result_id: str, index: int, db: Session = Depends(get_db)):
    """One gene family: its members with their genomes, locations, flags and sequences, its neighbouring families
    and the tool's alignment of it when one was made."""
    try:
        return svc.family_detail(_pangenome(db, result_id), index)
    except (LookupError, FileNotFoundError) as exc:
        return _missing(exc)


@router.get("/comparisons/results/{result_id}/pangenome/presence.Rtab")
def pangenome_presence(result_id: str, db: Session = Depends(get_db)):
    """The presence/absence matrix with the genomes' labels as column names."""
    r = _pangenome(db, result_id)
    name = comparative_svc.download_name(db.get(ComparisonSet, r.set_id), r, "presence_absence.Rtab")
    return Response(svc.presence_rtab(r), media_type="text/tab-separated-values; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', **_SAFE_HEADERS})


@router.get("/comparisons/results/{result_id}/pangenome/metadata")
def pangenome_metadata(result_id: str, db: Session = Depends(get_db)):
    """The metadata fields that can group the genomes, with each genome's current value."""
    return svc.metadata(db, _pangenome(db, result_id))


@router.get("/comparisons/results/{result_id}/pangenome/associations")
def pangenome_associations(result_id: str, field: str = Query(min_length=1, max_length=200),
                           min_group: int = Query(2, ge=1, le=100), limit: int = Query(200, ge=1, le=5000),
                           db: Session = Depends(get_db)):
    """Per-group statistics and exploratory associations (Fisher's exact test, Benjamini-Hochberg) between gene
    families and the groups of a metadata field."""
    try:
        return svc.associations(db, _pangenome(db, result_id), field, min_group, limit)
    except InputError as exc:
        return _input_error(exc)
    except FileNotFoundError as exc:
        return _missing(exc)
