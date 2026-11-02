from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404
from app.api.routes.comparative import _coded, _input_error, _set
from app.api.routes.tools import _tool_call
from app.db.session import get_db
from app.models import GeneQuery
from app.schemas.schemas import (
    AnalysisJobRead,
    ComparisonPlanRead,
    GeneInvestigationIn,
    GeneQueryFromFeatureIn,
    GeneQueryIn,
    GeneQueryRead,
    RegionExplorerIn,
)
from app.services import regions as svc
from app.services.comparative import InputError
from app.services.jobs import create_region_job

router = APIRouter(tags=["comparative genomics"])


@router.get("/gene-queries", response_model=list[GeneQueryRead])
def list_gene_queries(db: Session = Depends(get_db)):
    """The saved query sequences of Custom Gene Investigation, newest first."""
    return svc.list_queries(db)


@router.post("/gene-queries", response_model=GeneQueryRead, status_code=status.HTTP_201_CREATED)
def create_gene_query(payload: GeneQueryIn, db: Session = Depends(get_db)):
    """Save one pasted or uploaded FASTA sequence (checked against the molecule's alphabet and ARVA's size bounds);
    the same sequence saved twice returns the first record."""
    try:
        q = svc.query_from_fasta(db, payload.name, payload.description, payload.molecule, payload.fasta,
                                 payload.source)
    except InputError as exc:
        return _input_error(exc)
    return svc.query_view(q, with_sequence=True)


@router.post("/gene-queries/from-feature", response_model=GeneQueryRead, status_code=status.HTTP_201_CREATED)
def create_gene_query_from_feature(payload: GeneQueryFromFeatureIn, db: Session = Depends(get_db)):
    """Save an annotated feature's protein or nucleotide sequence (from the annotator's own files) as a query."""
    try:
        q = svc.query_from_feature(db, payload.annotation_id, payload.feature_id, payload.molecule, payload.name)
    except InputError as exc:
        return _input_error(exc)
    return svc.query_view(q, with_sequence=True)


@router.get("/gene-queries/{query_id}", response_model=GeneQueryRead)
def get_gene_query(query_id: str, db: Session = Depends(get_db)):
    return svc.query_view(get_or_404(db, GeneQuery, query_id, "Gene query"), with_sequence=True)


@router.delete("/gene-queries/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gene_query(query_id: str, db: Session = Depends(get_db)):
    """Remove a saved query; investigations that used it keep their own copy of the sequence."""
    db.delete(get_or_404(db, GeneQuery, query_id, "Gene query"))
    db.commit()


@router.get("/comparisons/{set_id}/gene-lookup")
def gene_lookup(set_id: str, q: str = Query(min_length=1, max_length=100), db: Session = Depends(get_db)):
    """Features of the set's genomes (their latest annotations) named `q` (gene or locus tag) or whose product
    contains it."""
    try:
        return svc.gene_lookup(db, _set(db, set_id), q)
    except InputError as exc:
        return _input_error(exc)
    except FileNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


def _region_plan(db: Session, set_id: str, payload: RegionExplorerIn) -> dict:
    cset = _set(db, set_id)
    return {**svc.region_plan(db, cset, payload.anchor.model_dump(), payload.genomes, payload.flank,
                              payload.locate.model_dump(), payload.groups.model_dump(), payload.links.model_dump(),
                              payload.threads), "set_id": cset.id}


def _gene_plan(db: Session, set_id: str, payload: GeneInvestigationIn) -> dict:
    cset = _set(db, set_id)
    return {**svc.gene_plan(db, cset, payload.query_id, payload.genomes, payload.task, payload.thresholds.model_dump(),
                            payload.mobile_distance, payload.alignment.model_dump(), payload.tree.model_dump(),
                            payload.threads), "set_id": cset.id}


def _start(db: Session, set_id: str, payload, build, job_type: str):
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "comparison_confirm")
    try:
        plan = build(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "comparison_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    return _tool_call(create_region_job, db, project_or_404(db, _set(db, set_id).project_id), job_type, plan)


@router.post("/comparisons/{set_id}/region/preview", response_model=ComparisonPlanRead)
def preview_region(set_id: str, payload: RegionExplorerIn, db: Session = Depends(get_db)):
    """What a Region Explorer run would do: the gene, the window, how each genome's homologue is found and every
    threshold."""
    try:
        return _region_plan(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)


@router.post("/comparisons/{set_id}/region", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_region(set_id: str, payload: RegionExplorerIn, db: Session = Depends(get_db)):
    return _start(db, set_id, payload, _region_plan, svc.REGION_JOB)


@router.post("/comparisons/{set_id}/gene/preview", response_model=ComparisonPlanRead)
def preview_gene(set_id: str, payload: GeneInvestigationIn, db: Session = Depends(get_db)):
    """What a gene investigation would do: the query, the search program and task, the thresholds, the alignment
    and tree settings, and the genomes with their checksums."""
    try:
        return _gene_plan(db, set_id, payload)
    except InputError as exc:
        return _input_error(exc)


@router.post("/comparisons/{set_id}/gene", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_gene(set_id: str, payload: GeneInvestigationIn, db: Session = Depends(get_db)):
    return _start(db, set_id, payload, _gene_plan, svc.GENE_JOB)

