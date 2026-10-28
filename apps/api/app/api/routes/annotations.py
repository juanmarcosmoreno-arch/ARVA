from arva_tools.bakta import BaktaParams
from arva_tools.prokka import ProkkaParams
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Annotation, Assembly, Sample
from app.schemas.schemas import (
    AnalysisJobRead,
    AnnotationExportRequest,
    AnnotationFeatureDetail,
    AnnotationFeaturePage,
    AnnotationListRow,
    AnnotationPlanRead,
    AnnotationRead,
    AnnotationRegion,
    BaktaPreviewRequest,
    BaktaRequest,
    ProkkaPreviewRequest,
    ProkkaRequest,
)
from app.services import annotation as svc
from app.services import genome_explorer as explorer
from app.services.jobs import create_bakta_job, create_prokka_job
from app.storage import get_storage

router = APIRouter(tags=["annotation"])

# The annotators' own files that can be downloaded, with their media types. The circular plot (PNG) may be shown
# inline as an image; every other file is an attachment.
_MEDIA = {"gff3": "text/plain", "genbank": "text/plain", "embl": "text/plain", "fna": "text/plain",
          "ffn": "text/plain", "faa": "text/plain", "tsv": "text/plain", "json": "application/json",
          "inference": "text/plain", "hypotheticals": "text/plain", "hypotheticals_faa": "text/plain",
          "summary": "text/plain", "log": "text/plain", "tbl": "text/plain", "sqn": "text/plain",
          "errors": "text/plain", "input": "text/plain", "plot_png": "image/png", "plot_svg": "image/svg+xml"}
_SUFFIX = {"gff3": "gff3", "genbank": "gbk", "embl": "embl", "fna": "fna", "ffn": "ffn", "faa": "faa",
           "tsv": "tsv", "json": "json", "inference": "inference.tsv", "hypotheticals": "hypotheticals.tsv",
           "hypotheticals_faa": "hypotheticals.faa", "summary": "txt", "log": "log", "tbl": "tbl", "sqn": "sqn",
           "errors": "err", "input": "input.fna", "plot_png": "png", "plot_svg": "svg"}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}


def _assembly(db: Session, assembly_id: str) -> tuple[Sample, Assembly]:
    try:
        a = svc.assembly_for(db, assembly_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assembly not found") from None
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return db.get(Sample, a.sample_id), a


def _annotation(db: Session, annotation_id: str) -> Annotation:
    return get_or_404(db, Annotation, annotation_id, "Annotation")


def _plan_or_400(fn, *args):
    try:
        return fn(*args)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _blocking(plan: dict) -> None:
    if plan["problems"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "; ".join(p["message"] for p in plan["problems"]))


def _provenance(plan: dict) -> dict:
    return {"synthetic_evidence": plan["assembly"]["synthetic_evidence"],
            "assembly_all_circular": plan["assembly"]["all_circular"],
            "descriptions_removed": plan["assembly"]["descriptions"]}


@router.post("/assemblies/{assembly_id}/annotate/bakta/preview", response_model=AnnotationPlanRead)
def preview_bakta(assembly_id: str, payload: BaktaPreviewRequest, db: Session = Depends(get_db)):
    """What a Bakta run of this assembly would do here: Bakta's version, each program it checks at start-up, every
    step (run, or skipped and why), the installed databases, the assembly's facts and ARVA's suggestions (locus-tag
    prefix; --complete when every contig is circular). Only version checks are run."""
    sample, a = _assembly(db, assembly_id)
    return _plan_or_400(svc.bakta_plan, db, sample, a, payload.database_id, payload.skip_plot)


@router.post("/assemblies/{assembly_id}/annotate/bakta", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_bakta(assembly_id: str, payload: BaktaRequest, db: Session = Depends(get_db)):
    """Annotate the assembly with Bakta in one background job, skipping exactly the steps the preview showed."""
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirm the summary of the run first")
    if payload.settings.complete and not payload.complete_confirmed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "--complete says every sequence is a complete replicon; "
                                                         "confirm that explicitly")
    values = payload.settings.model_dump()
    if values["species"] and not values["genus"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a species needs a genus")
    plan = _plan_or_400(svc.bakta_plan, db, sample, a, payload.database_id, values["skip_plot"])
    _blocking(plan)
    if plan["skip_options"] != payload.skip_options:
        raise HTTPException(status.HTTP_409_CONFLICT, "The steps Bakta can run here changed since the preview (it "
                                                      f"would now skip {', '.join(plan['skip_options']) or 'nothing'}); "
                                                      "review the preview again")
    record = svc.bakta_database(db, plan["database_id"])
    params = BaktaParams(**values, threads=payload.threads or get_settings().tool_threads)
    return _tool_call(create_bakta_job, db, sample, a, params, record, plan,
                      {**_provenance(plan), "complete_confirmed": payload.complete_confirmed})


@router.post("/assemblies/{assembly_id}/annotate/prokka/preview", response_model=AnnotationPlanRead)
def preview_prokka(assembly_id: str, payload: ProkkaPreviewRequest, db: Session = Depends(get_db)):
    """What a Prokka run of this assembly would do here: Prokka, the programs it uses, its databases (Debian's
    package), every step and why some do not run, and whether the contig names need renaming."""
    sample, a = _assembly(db, assembly_id)
    return _plan_or_400(svc.prokka_plan, db, sample, a, payload.rfam, payload.use_genus, payload.genus,
                        payload.rename_contigs)


@router.post("/assemblies/{assembly_id}/annotate/prokka", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_prokka(assembly_id: str, payload: ProkkaRequest, db: Session = Depends(get_db)):
    """Annotate the assembly with Prokka in one background job."""
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirm the summary of the run first")
    values = payload.settings.model_dump()
    if values["species"] and not values["genus"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a species needs a genus")
    if values["use_genus"] and not values["genus"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "use_genus needs a genus")
    plan = _plan_or_400(svc.prokka_plan, db, sample, a, values["rfam"], values["use_genus"], values["genus"],
                        values["rename_contigs"])
    _blocking(plan)
    params = ProkkaParams(**values, threads=payload.threads or get_settings().tool_threads)
    return _tool_call(create_prokka_job, db, sample, a, params, plan, _provenance(plan))


@router.get("/assemblies/{assembly_id}/annotations", response_model=list[AnnotationRead])
def list_assembly_annotations(assembly_id: str, db: Session = Depends(get_db)):
    get_or_404(db, Assembly, assembly_id, "Assembly")
    return db.scalars(select(Annotation).where(Annotation.assembly_id == assembly_id)
                      .order_by(Annotation.created_at.desc())).all()


@router.get("/samples/{sample_id}/annotations", response_model=list[AnnotationRead])
def list_sample_annotations(sample_id: str, db: Session = Depends(get_db)):
    sample_or_404(db, sample_id)
    return db.scalars(select(Annotation).where(Annotation.sample_id == sample_id)
                      .order_by(Annotation.created_at.desc())).all()


@router.get("/annotations", response_model=list[AnnotationListRow])
def list_annotations(limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)):
    """Every annotation, newest first, with its sample, project and assembly (the Genome Explorer's list)."""
    return explorer.list_annotations(db, limit)


@router.get("/annotations/{annotation_id}", response_model=AnnotationRead)
def get_annotation(annotation_id: str, db: Session = Depends(get_db)):
    return _annotation(db, annotation_id)


@router.get("/annotations/{annotation_id}/features", response_model=AnnotationFeaturePage)
def list_features(
    annotation_id: str,
    type: list[str] = Query(default=[], description="Feature types (repeat for several)"),
    contig: str | None = Query(default=None, max_length=200),
    start: int | None = Query(default=None, ge=1),
    end: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=200, description="Locus tag, gene, product or identifier"),
    hypothetical: bool | None = None,
    sort: str = "position",
    descending: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """The annotation's features matching every filter, sorted, one page at a time (at most 1,000)."""
    annotation = _annotation(db, annotation_id)
    if start is not None and end is not None and end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end must not be before start")
    try:
        return svc.query_features(annotation, types=type, contig=contig, start=start, end=end, q=q,
                                  hypothetical=hypothetical, sort=sort, descending=descending, limit=limit,
                                  offset=offset)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/annotations/{annotation_id}/features/{feature_id}", response_model=AnnotationFeatureDetail)
def get_feature(annotation_id: str, feature_id: int, db: Session = Depends(get_db)):
    """One feature with its nucleotide (and, for CDS, protein) sequence from the annotator's FASTA files and links for
    the identifiers it reported."""
    annotation = _annotation(db, annotation_id)
    try:
        detail = svc.feature_detail(annotation, feature_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature not found") from None
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {**detail, "checks": explorer.feature_checks(annotation, detail, detail["nucleotide"], detail["protein"])}


@router.get("/annotations/{annotation_id}/files/{kind}")
def download_file(annotation_id: str, kind: str, db: Session = Depends(get_db)):
    """One of the annotator's own output files, unchanged."""
    annotation = _annotation(db, annotation_id)
    entry = (annotation.files or {}).get(kind)
    if kind not in _MEDIA or entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This annotation has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    sample = db.get(Sample, annotation.sample_id)
    return FileResponse(path, media_type=_MEDIA[kind], headers=_SAFE_HEADERS,
                        filename=svc.download_name(sample, annotation, _SUFFIX[kind]),
                        content_disposition_type="inline" if kind == "plot_png" else "attachment")


def _export(db: Session, annotation_id: str, fmt: str, ids: list[int] | None,
            region: AnnotationRegion | None = None) -> Response:
    annotation = _annotation(db, annotation_id)
    try:
        if region is not None:
            ids = explorer.region_ids(annotation, region.contig, region.start, region.end)
        text, suffix = svc.export(annotation, fmt, ids)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This annotation has no such sequence") from None
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    sample = db.get(Sample, annotation.sample_id)
    prefix = "region_" if region is not None else "selected_" if ids is not None else ""
    name = svc.download_name(sample, annotation, prefix + suffix)
    return Response(text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', **_SAFE_HEADERS})


@router.get("/annotations/{annotation_id}/export/{fmt}")
def export_all(annotation_id: str, fmt: str, db: Session = Depends(get_db)):
    """Every feature: the annotator's GFF3, GenBank or FASTA (genes, proteins), or ARVA's feature table (TSV)."""
    return _export(db, annotation_id, fmt, None)


@router.post("/annotations/{annotation_id}/export")
def export_selected(annotation_id: str, payload: AnnotationExportRequest, db: Session = Depends(get_db)):
    """Selected features, or those overlapping a region (at most 10,000): their lines or records of the annotator's
    files, or ARVA's table."""
    return _export(db, annotation_id, payload.format, payload.feature_ids, payload.region)
