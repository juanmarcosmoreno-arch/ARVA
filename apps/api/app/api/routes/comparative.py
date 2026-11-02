from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.access import keep_visible, visible_projects
from app.api.deps import get_or_404, project_or_404
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import ComparisonResult, ComparisonSet
from app.schemas.schemas import (
    AnalysisJobRead,
    ComparisonAlignmentIn,
    ComparisonAniIn,
    ComparisonPlanRead,
    ComparisonResultRead,
    ComparisonSetBrief,
    ComparisonSetIn,
    ComparisonSetRead,
)
from app.services import comparative as svc
from app.services import pangenome as pangenome_svc
from app.services import regions as regions_svc
from app.services.comparative_report import comparative_report_html, comparative_report_json
from app.services.jobs import create_comparative_job
from app.storage import get_storage

router = APIRouter(tags=["comparative genomics"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "comparison_confirm": "Confirm the summary of the run first.",
    "comparison_blocked": "The comparison cannot run here: {problems}",
}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}


def _coded(code: int, key: str, message: str | None = None, **params) -> JSONResponse:
    text = message if message is not None else render(MESSAGES[key], params)
    return JSONResponse(status_code=code, content={"detail": text, "code": key, "params": params})


def _set(db: Session, set_id: str) -> ComparisonSet:
    return get_or_404(db, ComparisonSet, set_id, "Comparison set")


def _result(db: Session, result_id: str) -> ComparisonResult:
    return get_or_404(db, ComparisonResult, result_id, "Comparison result")


def _input_error(exc: svc.InputError) -> JSONResponse:
    return _coded(status.HTTP_400_BAD_REQUEST, exc.code, str(exc), **exc.params)


@router.get("/comparisons/candidates")
def comparison_candidates(request: Request, db: Session = Depends(get_db)):
    """Every assembly ARVA holds (any sample, any project, polished or not), to choose a comparison set from."""
    return keep_visible(svc.candidates(db), visible_projects(request))


@router.get("/comparisons", response_model=list[ComparisonSetBrief])
def list_comparisons(request: Request, project_id: str | None = None, db: Session = Depends(get_db)):
    return keep_visible(svc.list_sets(db, project_id), visible_projects(request))


@router.post("/comparisons", response_model=ComparisonSetRead, status_code=status.HTTP_201_CREATED)
def create_comparison(payload: ComparisonSetIn, db: Session = Depends(get_db)):
    """Save a named comparison set of 2 to 200 assemblies."""
    project = project_or_404(db, payload.project_id)
    try:
        cset = svc.save_set(db, None, project, payload.name, payload.description, payload.assembly_ids,
                            payload.labels)
    except svc.InputError as exc:
        return _input_error(exc)
    return svc.set_view(db, cset)


@router.get("/comparisons/{set_id}", response_model=ComparisonSetRead)
def get_comparison(set_id: str, db: Session = Depends(get_db)):
    return svc.set_view(db, _set(db, set_id))


@router.put("/comparisons/{set_id}", response_model=ComparisonSetRead)
def update_comparison(set_id: str, payload: ComparisonSetIn, db: Session = Depends(get_db)):
    """Rename the set or change its genomes and order; earlier results keep the genomes they compared."""
    cset = _set(db, set_id)
    project = project_or_404(db, payload.project_id)
    try:
        cset = svc.save_set(db, cset, project, payload.name, payload.description, payload.assembly_ids,
                            payload.labels)
    except svc.InputError as exc:
        return _input_error(exc)
    return svc.set_view(db, cset)


@router.delete("/comparisons/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comparison(set_id: str, db: Session = Depends(get_db)):
    """Delete the set and its result records (the assemblies are not touched)."""
    db.delete(_set(db, set_id))
    db.commit()


def _ani_plan(db: Session, cset: ComparisonSet, payload: ComparisonAniIn) -> dict:
    return {**svc.ani_plan(db, cset, payload.method, payload.threads), "set_id": cset.id}


def _alignment_plan(db: Session, cset: ComparisonSet, payload: ComparisonAlignmentIn) -> dict:
    return {**svc.alignment_plan(db, cset, payload.aligner, payload.preset, payload.nucmer.model_dump(),
                                 payload.order, payload.dnadiff, payload.threads), "set_id": cset.id}


@router.post("/comparisons/{set_id}/ani/preview", response_model=ComparisonPlanRead)
def preview_ani(set_id: str, payload: ComparisonAniIn, db: Session = Depends(get_db)):
    """What an ANI run would do: the tool, the settings passed, the genomes and their checksums."""
    try:
        return _ani_plan(db, _set(db, set_id), payload)
    except svc.InputError as exc:
        return _input_error(exc)


@router.post("/comparisons/{set_id}/ani", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_ani(set_id: str, payload: ComparisonAniIn, db: Session = Depends(get_db)):
    cset = _set(db, set_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "comparison_confirm")
    try:
        plan = _ani_plan(db, cset, payload)
    except svc.InputError as exc:
        return _input_error(exc)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "comparison_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    return _tool_call(create_comparative_job, db, project_or_404(db, cset.project_id), svc.ANI_JOB, plan)


@router.post("/comparisons/{set_id}/alignment/preview", response_model=ComparisonPlanRead)
def preview_alignment(set_id: str, payload: ComparisonAlignmentIn, db: Session = Depends(get_db)):
    """What an alignment run would do: the aligner and its settings, the reference (the first genome of the order),
    the pairs it aligns and whether dnadiff runs."""
    try:
        return _alignment_plan(db, _set(db, set_id), payload)
    except svc.InputError as exc:
        return _input_error(exc)


@router.post("/comparisons/{set_id}/alignment", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_alignment(set_id: str, payload: ComparisonAlignmentIn, db: Session = Depends(get_db)):
    cset = _set(db, set_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "comparison_confirm")
    try:
        plan = _alignment_plan(db, cset, payload)
    except svc.InputError as exc:
        return _input_error(exc)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "comparison_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    return _tool_call(create_comparative_job, db, project_or_404(db, cset.project_id), svc.ALIGNMENT_JOB, plan)


@router.get("/comparisons/results/{result_id}", response_model=ComparisonResultRead)
def get_result(result_id: str, db: Session = Depends(get_db)):
    """A result with everything to draw it: the ANI matrix and ordering, or the alignment blocks, per-pair summaries,
    conservation windows and dnadiff's differences."""
    view = svc.result_view(_result(db, result_id), db)
    db.commit()
    return view


_CSV = {"ani": ("ani", svc.ani_csv), "blocks": ("alignment", svc.blocks_csv),
        "differences": ("alignment", svc.differences_csv), "conservation": ("alignment", svc.conservation_csv),
        "hits": ("gene", regions_svc.hits_csv), "neighbourhood": ("region", regions_svc.region_csv),
        "families": ("pangenome", pangenome_svc.families_csv)}


@router.get("/comparisons/results/{result_id}/{table}.csv")
def result_csv(result_id: str, table: str, db: Session = Depends(get_db)):
    r = _result(db, result_id)
    if table not in _CSV or _CSV[table][0] != r.analysis:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This result has no such table")
    name = svc.download_name(db.get(ComparisonSet, r.set_id), r, f"{table}.csv")
    return Response(_CSV[table][1](r), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', **_SAFE_HEADERS})


@router.get("/comparisons/results/{result_id}/files/{name:path}")
def result_file(result_id: str, name: str, db: Session = Depends(get_db)):
    """One of the tools' own files (tables, alignments, reports, logs), unchanged, as plain text."""
    r = _result(db, result_id)
    entry = (r.files or {}).get(name)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This result has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    return FileResponse(path, media_type="text/plain", headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(ComparisonSet, r.set_id), r, name))


@router.get("/comparisons/{set_id}/report.html", response_class=HTMLResponse)
def comparison_report_html(set_id: str, lang: str = "en", db: Session = Depends(get_db)):
    """The comparative report of the set: its genomes and, per result, the method, tool, settings and findings."""
    cset = _set(db, set_id)
    return HTMLResponse(comparative_report_html(db, cset, lang), headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


@router.get("/comparisons/{set_id}/report.json")
def comparison_report_json(set_id: str, db: Session = Depends(get_db)):
    return comparative_report_json(db, _set(db, set_id))
