from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import project_or_404
from app.api.routes.comparative import _SAFE_HEADERS, _coded, _input_error, _result, _set
from app.api.routes.tools import _tool_call
from app.db.session import get_db
from app.models import ComparisonResult, ComparisonSet
from app.schemas.schemas import AnalysisJobRead, ComparisonPlanRead, PhylogenyIn, PhyloViewIn
from app.services import phylogeny as svc
from app.services.comparative import InputError
from app.services.jobs import create_phylogeny_job
from app.services.phylogeny_report import phylogeny_report_html

router = APIRouter(tags=["comparative genomics"])


def _plan(db: Session, set_id: str, payload: PhylogenyIn) -> dict:
    cset = _set(db, set_id)
    return {**svc.plan(db, cset, payload.source.model_dump(), payload.method, payload.iqtree.model_dump(),
                       payload.constant_sites, payload.distance, payload.rooting.model_dump(), payload.threads),
            "set_id": cset.id}


@router.get("/comparisons/{set_id}/phylogeny/sources")
def phylogeny_sources(set_id: str, db: Session = Depends(get_db)):
    """The set's results a tree can be built from: Panaroo core-genome alignments (and their SNPs), aligned gene
    families, gene investigation alignments and ANI matrices."""
    return svc.sources(db, _set(db, set_id))


@router.post("/comparisons/{set_id}/phylogeny/preview", response_model=ComparisonPlanRead)
def preview_phylogeny(set_id: str, payload: PhylogenyIn, db: Session = Depends(get_db)):
    """What a tree run would do: the source (result, file and SHA-256, leaves), the method with every option, the
    constant-site handling of a SNP alignment, the rooting, and the notes on how to read the tree."""
    try:
        return _plan(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)


@router.post("/comparisons/{set_id}/phylogeny", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_phylogeny(set_id: str, payload: PhylogenyIn, db: Session = Depends(get_db)):
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "comparison_confirm")
    try:
        plan = _plan(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "comparison_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    return _tool_call(create_phylogeny_job, db, project_or_404(db, _set(db, set_id).project_id), plan)


def _tree(db: Session, result_id: str) -> ComparisonResult:
    r = _result(db, result_id)
    if r.analysis != "phylogeny":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This result is not a tree")
    return r


def _missing(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@router.put("/comparisons/results/{result_id}/phylogeny/view")
def save_phylogeny_view(result_id: str, payload: PhyloViewIn, db: Session = Depends(get_db)):
    """Saves the rooting and the Tree Explorer's display; returns the tree rooted accordingly. An outgroup that is
    not one side of a branch of the tree is refused."""
    try:
        return svc.save_view(db, _tree(db, result_id), payload.rooting.model_dump(), payload.style.model_dump())
    except InputError as exc:
        return _input_error(exc)
    except FileNotFoundError as exc:
        return _missing(exc)


@router.get("/comparisons/results/{result_id}/phylogeny/tree.nwk")
def phylogeny_newick(result_id: str, rooted: bool = True, db: Session = Depends(get_db)):
    """The tree in Newick with the leaves' names: rooted as the saved view says, or unrooted as inferred."""
    r = _tree(db, result_id)
    try:
        text = svc.newick_text(db, r, rooted)
    except FileNotFoundError as exc:
        return _missing(exc)
    name = svc.download_name(db.get(ComparisonSet, r.set_id), r, "rooted.nwk" if rooted else "unrooted.nwk")
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', **_SAFE_HEADERS})


@router.get("/comparisons/results/{result_id}/phylogeny/metadata")
def phylogeny_metadata(result_id: str, db: Session = Depends(get_db)):
    """Per genome of the tree: sample metadata, MLST and the AMR genes of the latest AMRFinderPlus run, for leaf
    colours and metadata bands."""
    return svc.leaf_metadata(db, _tree(db, result_id))


@router.get("/comparisons/phylogeny/compare")
def phylogeny_compare(a: str = Query(max_length=36), b: str = Query(max_length=36),
                      by: Literal["leaf", "genome"] = "leaf", db: Session = Depends(get_db)):
    """Robinson-Foulds distance between two trees over the leaves they share (by leaf name, or by genome when each
    genome has one leaf), with the bipartitions found in only one of them."""
    try:
        return svc.compare(_tree(db, a), _tree(db, b), by)
    except InputError as exc:
        return _input_error(exc)
    except FileNotFoundError as exc:
        return _missing(exc)


@router.get("/comparisons/results/{result_id}/phylogeny/report.html", response_class=HTMLResponse)
def phylogeny_report(result_id: str, db: Session = Depends(get_db)):
    """The phylogenetic report of one tree: the figure, source, methods, tools, versions, parameters, supports,
    warnings, limitations and references."""
    r = _tree(db, result_id)
    html = phylogeny_report_html(db, r)
    db.commit()
    return HTMLResponse(html, headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
