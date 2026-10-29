from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import AnalysisJob, Annotation, ReferenceDatabase, Sample
from app.schemas.schemas import (
    MOBILE_SETTINGS,
    AnalysisJobRead,
    MobileAnnotationRead,
    MobilePlanRead,
    MobilePreviewRequest,
    MobileProjectRead,
    MobileRequest,
    MobileRunRead,
    MobileSampleRead,
    VirulenceAnnotationRead,
    VirulencePlanRead,
    VirulenceRequest,
    VirulenceRunRead,
    VirulenceSampleRead,
)
from app.services import mobile_elements as svc
from app.services import virulence as vir
from app.services.jobs import create_mobile_job, create_virulence_job
from app.services.mlst import InputError as AssemblyInputError
from app.services.mlst import assembly_for
from app.services.performance import effective_resources
from app.storage import get_storage

router = APIRouter(tags=["mobile elements and virulence"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "mobile_confirm": "Confirm the summary of the run first.",
    "mobile_blocked": "{tool} cannot run here: {problems}",
    "mobile_settings_invalid": "The settings are not valid for {method}: {detail}",
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


def _plan(db: Session, sample, a, method: str, database_id: str | None):
    try:
        return svc.plan(db, sample, a, method, database_id)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/assemblies/{assembly_id}/mobile-elements/preview", response_model=MobilePlanRead)
def preview_mobile(assembly_id: str, payload: MobilePreviewRequest, db: Session = Depends(get_db)):
    """What a run of the method on this assembly would do here: the tool, the database (or the models the tool
    bundles), the settings ARVA passes and the tool's own defaults, the assembler's circularity of the contigs."""
    sample, a = _assembly(db, assembly_id)
    return _plan(db, sample, a, payload.method, payload.database_id)


@router.post("/assemblies/{assembly_id}/mobile-elements", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_mobile(assembly_id: str, payload: MobileRequest, db: Session = Depends(get_db)):
    """Search the assembly with one method in one background job; every setting is passed with its value."""
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "mobile_confirm")
    try:
        settings = MOBILE_SETTINGS[payload.method].model_validate(payload.settings)
    except ValidationError as exc:
        detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return _coded(status.HTTP_422_UNPROCESSABLE_CONTENT, "mobile_settings_invalid", method=payload.method,
                      detail=detail)
    plan = _plan(db, sample, a, payload.method, payload.database_id)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "mobile_blocked", tool=plan["tool"]["name"],
                      problems="; ".join(p["message"] for p in plan["problems"]))
    spec = svc.METHODS[payload.method]
    extra = {"database": "plasmidfinder"} if payload.method == "plasmidfinder" else {}
    params = spec["params"](**settings.model_dump(), **extra, threads=payload.threads or effective_resources(db).threads)
    record = db.get(ReferenceDatabase, plan["database"]["id"]) if plan["database"] else None
    provenance = {"synthetic_evidence": plan["assembly"]["synthetic_evidence"],
                  "circularity": plan["circularity"]}
    return _tool_call(create_mobile_job, db, sample, a, payload.method, params, record, plan["models"], provenance)


@router.get("/samples/{sample_id}/mobile-elements", response_model=MobileSampleRead)
def sample_mobile(sample_id: str, db: Session = Depends(get_db)):
    """The sample's completed runs, newest first, each with its rows, and per assembly the contig table (MOB-suite's
    call, the replicons and element counts next to the assembler's circularity)."""
    sample_or_404(db, sample_id)
    return svc.sample_view(db, sample_id)


@router.get("/mobile-elements/runs/{job_id}", response_model=MobileRunRead)
def get_mobile_run(job_id: str, db: Session = Depends(get_db)):
    job = get_or_404(db, AnalysisJob, job_id, "Mobile-element run")
    if job.job_type != svc.MOBILE_JOB:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mobile-element run not found")
    return svc.run_row(db, job)


def _file(job: AnalysisJob, job_type: str, kind: str):
    rs = job.result_summary or {}
    entry = (rs.get("files") or {}).get(kind) or ((rs.get("inputs") or {}).get(kind) if kind == "input" else None)
    if job.job_type != job_type or entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This run has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    return path


@router.get("/mobile-elements/runs/{job_id}/files/{kind}")
def download_mobile_file(job_id: str, kind: str, db: Session = Depends(get_db)):
    """One of the tool's own files (reports, sequences, logs) or the staged input, unchanged, as plain text."""
    job = get_or_404(db, AnalysisJob, job_id, "Mobile-element run")
    path = _file(job, svc.MOBILE_JOB, kind)
    return FileResponse(path, media_type="text/plain", headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(Sample, job.sample_id), job, path.name))


@router.get("/projects/{project_id}/mobile-elements", response_model=MobileProjectRead)
def project_mobile(project_id: str, db: Session = Depends(get_db)):
    """Every sample's most recent run of each method with its counts (null: not searched), the replicon types, and
    the virulence genes found by VFDB and by AMRFinderPlus."""
    return svc.project_overview(db, project_or_404(db, project_id))


@router.get("/annotations/{annotation_id}/mobile-elements", response_model=MobileAnnotationRead)
def annotation_mobile(annotation_id: str, db: Session = Depends(get_db)):
    """The assembly's most recent run of each method on this annotation's sequences, for the circular map's
    mobile-elements ring and the Genome Explorer."""
    return svc.annotation_elements(db, get_or_404(db, Annotation, annotation_id, "Annotation"))


# --- Virulence (VFDB through ABRicate) -----------------------------------------------------------------------

@router.post("/assemblies/{assembly_id}/virulence/preview", response_model=VirulencePlanRead)
def preview_virulence(assembly_id: str, db: Session = Depends(get_db)):
    """What a VFDB screen of this assembly would do here: ABRicate, its bundled VFDB (index date, sequences,
    checksum, licence and citation status) and the thresholds."""
    sample, a = _assembly(db, assembly_id)
    return vir.plan(db, sample, a)


@router.post("/assemblies/{assembly_id}/virulence", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_virulence(assembly_id: str, payload: VirulenceRequest, db: Session = Depends(get_db)):
    """Screen the assembly against ABRicate's bundled VFDB in one background job (--minid and --mincov passed)."""
    from arva_tools.abricate import AbricateParams

    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "mobile_confirm")
    plan = vir.plan(db, sample, a)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "mobile_blocked", tool="ABRicate",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    params = AbricateParams(database="vfdb", minid=payload.settings.minid, mincov=payload.settings.mincov,
                            threads=payload.threads or effective_resources(db).threads)
    record = db.get(ReferenceDatabase, plan["database"]["id"])
    terms = {k: plan["database"][k] for k in ("licence", "licence_url", "citation", "unconfirmed")}
    provenance = {"synthetic_evidence": plan["assembly"]["synthetic_evidence"], "database_terms": terms}
    return _tool_call(create_virulence_job, db, sample, a, params, record, provenance)


@router.get("/samples/{sample_id}/virulence", response_model=VirulenceSampleRead)
def sample_virulence(sample_id: str, db: Session = Depends(get_db)):
    """The sample's VFDB screens, and per assembly the VFDB hits and AMRFinderPlus's virulence genes side by side,
    each row with its source."""
    sample_or_404(db, sample_id)
    return vir.sample_view(db, sample_id)


@router.get("/virulence/runs/{job_id}", response_model=VirulenceRunRead)
def get_virulence_run(job_id: str, db: Session = Depends(get_db)):
    job = get_or_404(db, AnalysisJob, job_id, "VFDB run")
    if job.job_type != vir.VIRULENCE_JOB:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VFDB run not found")
    return vir.run_row(db, job)


@router.get("/virulence/runs/{job_id}/files/{kind}")
def download_virulence_file(job_id: str, kind: str, db: Session = Depends(get_db)):
    """ABRicate's report, its log or the staged input, unchanged, as plain text."""
    job = get_or_404(db, AnalysisJob, job_id, "VFDB run")
    path = _file(job, vir.VIRULENCE_JOB, kind)
    return FileResponse(path, media_type="text/plain", headers=_SAFE_HEADERS,
                        filename=vir.download_name(db.get(Sample, job.sample_id), job, path.name))


@router.get("/annotations/{annotation_id}/virulence", response_model=VirulenceAnnotationRead)
def annotation_virulence(annotation_id: str, db: Session = Depends(get_db)):
    """The VFDB hits of the assembly's most recent screen on this annotation's sequences (circular map, explorer)."""
    return vir.annotation_hits(db, get_or_404(db, Annotation, annotation_id, "Annotation"))
