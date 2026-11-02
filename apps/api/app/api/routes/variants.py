from typing import Literal

from arva_tools.bcftools import VariantParams
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import Annotation, Sample, VariantCall
from app.schemas.schemas import AnalysisJobRead, VariantsIn
from app.services import mobilome, variants_report
from app.services import variants as svc
from app.services.jobs import create_variant_job
from app.services.short_hybrid import InputError as ReadsInputError
from app.services.short_hybrid import resolve_inputs

router = APIRouter(tags=["variants and mobilome"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "variants_confirm": "Confirm the summary of the run first.",
    "variants_blocked": "Variant calling cannot run here: {problems}",
    "variants_invalid": "{detail}",
    "variants_reference_missing": "The reference is missing: {detail}",
    "variants_reference_kind": "Choose an assembly or a genome of a reference collection as the reference.",
    "variants_no_collection": "The chosen database is not a reference genome collection.",
    "variants_collection_unusable": "{name} cannot be used now.",
    "variants_genome_missing": "That genome is not in the collection, or its file is missing.",
    "variants_reads_short": "Short reads take either the two files of a pair (R1 and R2) or one file of unpaired "
                            "reads.",
    "variants_reads_long": "Long reads take one file of long reads.",
    "variants_not_fastq": "{file} is not a FASTQ file.",
    "variants_file_invalid": "{file} failed validation.",
    "variants_technology": "Unknown sequencing technology.",
    "variants_matrix_too_few": "The SNP matrix needs at least two samples called against this reference.",
}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}


def _coded(code: int, key: str, **params) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": render(MESSAGES[key], params), "code": key,
                                                   "params": params})


def _refused(exc: svc.InputError) -> JSONResponse:
    key = exc.code if exc.code in MESSAGES else "variants_invalid"
    params = {**exc.params, "detail": str(exc)}
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST,
                        content={"detail": str(exc), "code": key, "params": params})


def _params(payload: VariantsIn, threads: int) -> VariantParams:
    s = payload.settings
    return VariantParams(technology=payload.technology, min_mapq=s.min_mapq, min_baseq=s.min_baseq,
                         max_depth=s.max_depth, call_indels=s.call_indels, prior=s.prior, min_qual=s.min_qual,
                         min_depth=s.min_depth, min_alt_fraction=s.min_alt_fraction, threads=threads)


def _prepare(db: Session, sample: Sample, payload: VariantsIn):
    try:
        inputs = resolve_inputs(db, sample, dict(payload.inputs))
    except ReadsInputError as exc:
        raise svc.InputError(str(exc)) from exc
    from app.services.performance import effective_resources

    params = _params(payload, effective_resources(db).cap_threads(payload.threads or 4))
    try:
        params.validate()
    except ValueError as exc:
        raise svc.InputError(str(exc)) from exc
    plan = svc.plan(db, sample, payload.technology, payload.reference.model_dump(), inputs, params, payload.effects)
    return inputs, params, plan


@router.get("/samples/{sample_id}/variants/options")
def variant_options(sample_id: str, db: Session = Depends(get_db)):
    """The references the dialog offers (ARVA's assemblies, this project's first, and the reference collections),
    the technology the sample's metadata suggests and ARVA's defaults with their sources."""
    sample = sample_or_404(db, sample_id)
    return {**svc.reference_options(db, sample), "suggested_technology": svc.suggested_technology(sample),
            "defaults": svc.defaults()}


@router.get("/variants/collections/{database_id}/genomes")
def collection_genomes(database_id: str, q: str = Query(default="", max_length=200), db: Session = Depends(get_db)):
    try:
        return svc.collection_genomes(db, database_id, q)
    except svc.InputError as exc:
        return _refused(exc)


@router.post("/samples/{sample_id}/variants/preview")
def preview_variants(sample_id: str, payload: VariantsIn, db: Session = Depends(get_db)):
    sample = sample_or_404(db, sample_id)
    try:
        return _prepare(db, sample, payload)[2]
    except svc.InputError as exc:
        return _refused(exc)


@router.post("/samples/{sample_id}/variants", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_variants(sample_id: str, payload: VariantsIn, db: Session = Depends(get_db)):
    sample = sample_or_404(db, sample_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "variants_confirm")
    try:
        inputs, params, plan = _prepare(db, sample, payload)
    except svc.InputError as exc:
        return _refused(exc)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "variants_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    return _tool_call(create_variant_job, db, sample, plan, inputs, params, payload.keep_alignment)


@router.get("/samples/{sample_id}/variants")
def sample_variants(sample_id: str, db: Session = Depends(get_db)):
    """The sample's variant-calling runs, newest first, with their summaries (records are fetched per run)."""
    sample_or_404(db, sample_id)
    return svc.sample_runs(db, sample_id)


def _run(db: Session, run_id: str) -> VariantCall:
    return get_or_404(db, VariantCall, run_id, "Variant-calling run")


@router.get("/variants/runs/{run_id}")
def get_variant_run(run_id: str, db: Session = Depends(get_db)):
    vc = _run(db, run_id)
    from app.models import AnalysisJob

    return svc.brief(vc, db.get(AnalysisJob, vc.job_id))


@router.get("/variants/runs/{run_id}/records")
def variant_records(run_id: str, status_filter: Literal["all", "pass", "filtered"] = Query("all", alias="status"),
                    types: list[str] | None = Query(None, alias="type"), contig: str | None = Query(None, max_length=255),
                    effect: str | None = Query(None, max_length=50), q: str | None = Query(None, max_length=100),
                    offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=5000),
                    db: Session = Depends(get_db)):
    return svc.query_variants(_run(db, run_id), status=status_filter, types=types, contig=contig, effect=effect,
                              text=q, offset=offset, limit=limit)


@router.get("/variants/runs/{run_id}/variants.csv")
def variant_csv(run_id: str, db: Session = Depends(get_db)):
    vc = _run(db, run_id)
    name = svc.download_name(db.get(Sample, vc.sample_id), vc, ".csv")
    return Response(svc.variants_csv(vc), media_type="text/csv",
                    headers={**_SAFE_HEADERS, "Content-Disposition": f'attachment; filename="{name}"'})


FILE_SUFFIX = {"vcf": ".vcf.gz", "vcf_index": ".vcf.gz.tbi", "csq_gff": "_csq.gff3", "bam": ".bam",
               "bam_index": ".bam.bai"}


@router.get("/variants/runs/{run_id}/files/{kind}")
def variant_file(run_id: str, kind: str, db: Session = Depends(get_db)):
    """The run's VCF (bgzip, with its tabix index), the GFF3 given to bcftools csq, or the kept alignment."""
    vc = _run(db, run_id)
    if kind not in FILE_SUFFIX:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This run has no such file")
    path = svc.file_path(vc, kind)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This run has no such file, or it is missing on disk")
    return FileResponse(path, media_type="application/octet-stream", headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(Sample, vc.sample_id), vc, FILE_SUFFIX[kind]))


@router.get("/projects/{project_id}/variants")
def project_variants(project_id: str, db: Session = Depends(get_db)):
    return svc.project_overview(db, project_or_404(db, project_id))


@router.get("/projects/{project_id}/variants/matrix")
def project_matrix(project_id: str, reference: str = Query(..., min_length=64, max_length=64),
                   format: Literal["json", "csv", "distances", "fasta"] = "json", db: Session = Depends(get_db)):
    """SNP matrix and pairwise SNP distances of the samples' most recent runs against one reference (by SHA-256)."""
    project = project_or_404(db, project_id)
    try:
        m = svc.matrix(db, project, reference)
    except svc.InputError as exc:
        return _refused(exc)
    if format == "json":
        return m
    text = svc.matrix_fasta(m) if format == "fasta" else svc.matrix_csv(m, format)
    ext = {"csv": "snp_matrix.csv", "distances": "snp_distances.csv", "fasta": "snp_sites.fasta"}[format]
    return Response(text, media_type="text/plain" if format == "fasta" else "text/csv",
                    headers={**_SAFE_HEADERS, "Content-Disposition": f'attachment; filename="{ext}"'})


@router.get("/projects/{project_id}/variants/report.html", response_class=HTMLResponse)
def project_variant_report(project_id: str, db: Session = Depends(get_db)):
    """Each reference's runs and, with two samples or more, the pairwise SNP distances, as a self-contained page."""
    html = variants_report.project_html(db, project_or_404(db, project_id))
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                                       "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


@router.get("/annotations/{annotation_id}/variants")
def annotation_variants(annotation_id: str, contig: str | None = Query(None, max_length=255),
                        start: int | None = Query(None, ge=1), end: int | None = Query(None, ge=1),
                        run: str | None = Query(None, max_length=36), db: Session = Depends(get_db)):
    """The Genome Explorer's Variants track: runs whose reference is this annotation's assembly and the records of
    one of them in a region (assembly contig names)."""
    annotation = get_or_404(db, Annotation, annotation_id, "Annotation")
    return svc.annotation_track(db, annotation, contig, start, end, run)


@router.get("/samples/{sample_id}/mobilome")
def sample_mobilome(sample_id: str, window: int = Query(mobilome.WINDOW_DEFAULT, ge=0, le=mobilome.WINDOW_MAX),
                    db: Session = Depends(get_db)):
    sample_or_404(db, sample_id)
    return mobilome.sample_mobilome(db, sample_id, window)


@router.get("/projects/{project_id}/mobilome")
def project_mobilome(project_id: str, window: int = Query(mobilome.WINDOW_DEFAULT, ge=0, le=mobilome.WINDOW_MAX),
                     db: Session = Depends(get_db)):
    return mobilome.project_mobilome(db, project_or_404(db, project_id), window)

