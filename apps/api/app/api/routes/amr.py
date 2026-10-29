from arva_tools.amrfinderplus import AmrParams
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
from app.api.routes.databases import _read as database_read
from app.api.routes.databases import _refusal
from app.api.routes.tools import _tool_call
from app.core.messages import render
from app.db.session import get_db
from app.models import AnalysisJob, Annotation, ReferenceDatabase, Sample
from app.schemas.schemas import (
    AmrAnnotationHitsRead,
    AmrPlanRead,
    AmrPreviewRequest,
    AmrProjectOverviewRead,
    AmrReleasePlanRead,
    AmrReleasePlanRequest,
    AmrReleasesRead,
    AmrReleaseStartRequest,
    AmrRequest,
    AmrRunRead,
    AnalysisJobRead,
    ReferenceDatabaseRead,
)
from app.services import amr as svc
from app.services import amrfinder_db
from app.services import databases as dbs
from app.services.jobs import create_amr_job
from app.services.mlst import InputError as AssemblyInputError
from app.services.mlst import assembly_for
from app.services.performance import effective_resources
from app.storage import get_storage

router = APIRouter(tags=["amr"])

# The English texts of the coded refusals; the interface has them as api.error.<code>.
MESSAGES = {
    "amr_confirm": "Confirm the summary of the run first.",
    "amr_blocked": "AMRFinderPlus cannot run here: {problems}",
    "amr_organism_unknown": "{organism} is not an organism option of this database ({available}).",
    "amr_annotation_needed": "A combined search needs one of the assembly's annotations with CDS.",
}
_MEDIA = {"report": "text/plain", "mutation_all": "text/plain", "nucleotide_hits": "text/plain",
          "protein_hits": "text/plain", "log": "text/plain", "input": "text/plain"}
_SUFFIX = {"report": "tsv", "mutation_all": "mutation_all.tsv", "nucleotide_hits": "nucleotide_hits.fna",
           "protein_hits": "protein_hits.faa", "log": "stderr.log", "input": "input.fna"}
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


def _plan(db: Session, sample, a, database_id, annotation_id):
    try:
        return svc.plan(db, sample, a, database_id, annotation_id)
    except svc.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/assemblies/{assembly_id}/amr/preview", response_model=AmrPlanRead)
def preview_amr(assembly_id: str, payload: AmrPreviewRequest, db: Session = Depends(get_db)):
    """What an AMRFinderPlus run of this assembly would do here: the tool, the databases (and the copies inside Bakta
    databases), the organisms of the chosen database with the one ARVA proposes from the species identification, the
    annotations a combined search can read, and AMRFinderPlus's defaults as its --help states them."""
    sample, a = _assembly(db, assembly_id)
    return _plan(db, sample, a, payload.database_id, payload.annotation_id)


@router.post("/assemblies/{assembly_id}/amr", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_amr(assembly_id: str, payload: AmrRequest, db: Session = Depends(get_db)):
    """Search the assembly with AMRFinderPlus in one background job; every option is passed with its value."""
    sample, a = _assembly(db, assembly_id)
    if not payload.confirmed:
        return _coded(status.HTTP_400_BAD_REQUEST, "amr_confirm")
    s = payload.settings
    if s.mode == "combined" and not payload.annotation_id:
        return _coded(status.HTTP_400_BAD_REQUEST, "amr_annotation_needed")
    annotation_id = payload.annotation_id if s.mode == "combined" else None
    plan = _plan(db, sample, a, payload.database_id, annotation_id)
    if plan["problems"]:
        return _coded(status.HTTP_409_CONFLICT, "amr_blocked",
                      problems="; ".join(p["message"] for p in plan["problems"]))
    if s.organism and s.organism not in plan["organisms"]:
        return _coded(status.HTTP_400_BAD_REQUEST, "amr_organism_unknown", organism=s.organism,
                      available=", ".join(plan["organisms"]))
    annotation = next((x for x in plan["annotations"] if x["id"] == annotation_id), None)
    params = AmrParams(mode=s.mode, organism=s.organism, plus=s.plus, ident_min=s.ident_min,
                       coverage_min=s.coverage_min, translation_table=s.translation_table,
                       annotation_format=annotation["annotation_format"] if annotation else None,
                       threads=payload.threads or effective_resources(db).threads)
    record = db.get(ReferenceDatabase, plan["database"]["id"])
    choice = plan["organism"]
    provenance = {"synthetic_evidence": plan["assembly"]["synthetic_evidence"], "organism_choice": {
        "proposed": choice.get("organism"), "rule": choice.get("rule"), "species": choice.get("species"),
        "chosen": s.organism, "changed_by_user": s.organism != choice.get("organism")}}
    linked = {k: annotation[k] for k in ("id", "tool", "tool_version", "annotation_format")} if annotation else None
    return _tool_call(create_amr_job, db, sample, a, params, record, linked, provenance)


@router.get("/samples/{sample_id}/amr", response_model=list[AmrRunRead])
def list_sample_runs(sample_id: str, db: Session = Depends(get_db)):
    """The sample's completed AMRFinderPlus runs, newest first, each with its elements."""
    sample_or_404(db, sample_id)
    return svc.sample_runs(db, sample_id)


@router.get("/amr/runs/{job_id}", response_model=AmrRunRead)
def get_run(job_id: str, db: Session = Depends(get_db)):
    job = get_or_404(db, AnalysisJob, job_id, "AMR run")
    if job.job_type != svc.AMR_JOB:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AMR run not found")
    return svc.run_row(db, job)


@router.get("/amr/runs/{job_id}/files/{kind}")
def download_file(job_id: str, kind: str, db: Session = Depends(get_db)):
    """One of AMRFinderPlus's own files (report, mutation_all, hit sequences, log) or the staged input, unchanged."""
    job = get_or_404(db, AnalysisJob, job_id, "AMR run")
    entry = ((job.result_summary or {}).get("files") or {}).get(kind) or (
        ((job.result_summary or {}).get("inputs") or {}).get(kind) if kind == "input" else None)
    if job.job_type != svc.AMR_JOB or kind not in _MEDIA or entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This AMR run has no such file")
    path = get_storage().resolve(entry["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing on disk")
    return FileResponse(path, media_type=_MEDIA[kind], headers=_SAFE_HEADERS,
                        filename=svc.download_name(db.get(Sample, job.sample_id), job, _SUFFIX[kind]))


@router.get("/projects/{project_id}/amr", response_model=AmrProjectOverviewRead)
def project_overview(project_id: str, db: Session = Depends(get_db)):
    """Every sample's most recent AMR run and the presence/absence matrix of the elements found."""
    return svc.project_overview(db, project_or_404(db, project_id))


def _csv(name: str, body: str) -> Response:
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', **_SAFE_HEADERS})


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in text)[:80]


@router.get("/projects/{project_id}/amr.csv")
def project_csv(project_id: str, db: Session = Depends(get_db)):
    """Every element of every AMR run of the project's samples, one row each (CSV)."""
    project = project_or_404(db, project_id)
    return _csv(f"ARVA_{_safe(project.name)}_amr.csv", svc.project_csv(db, project))


@router.get("/projects/{project_id}/amr_matrix.csv")
def project_matrix_csv(project_id: str, db: Session = Depends(get_db)):
    """The presence/absence matrix (1 found, 0 searched and not found, empty: not searched)."""
    project = project_or_404(db, project_id)
    return _csv(f"ARVA_{_safe(project.name)}_amr_matrix.csv", svc.matrix_csv(svc.project_overview(db, project)))


@router.get("/annotations/{annotation_id}/amr", response_model=AmrAnnotationHitsRead)
def annotation_hits(annotation_id: str, job_id: str | None = Query(default=None, max_length=36),
                    db: Session = Depends(get_db)):
    """The hits of the assembly's most recent AMR run (or job_id) on this annotation's sequences, each with the
    annotated feature it is linked to, for the Genome Explorer track and the circular map's rings."""
    annotation = get_or_404(db, Annotation, annotation_id, "Annotation")
    return svc.annotation_hits(db, annotation, job_id)


# --- Database releases --------------------------------------------------------------------------------------

def _db_refusal(exc: Exception):
    if isinstance(exc, amrfinder_db.AmrDatabaseError) and exc.upstream:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY,
                            content={"detail": str(exc), "code": exc.code, "params": exc.params})
    return _refusal(exc)


@router.get("/databases/amrfinderplus/releases", response_model=AmrReleasesRead)
def releases():
    """The dated AMRFinderPlus database releases NCBI lists for the installed AMRFinderPlus (newest first)."""
    try:
        return amrfinder_db.releases()
    except dbs.DatabaseError as exc:
        return _db_refusal(exc)


@router.post("/databases/amrfinderplus/plan", response_model=AmrReleasePlanRead)
def release_plan(payload: AmrReleasePlanRequest, db: Session = Depends(get_db)):
    """What downloading a release would fetch from NCBI (each file with the size the listing gives), where it would
    be installed and the space it needs with the indexes. NCBI publishes no checksums for these files."""
    try:
        return amrfinder_db.plan(db, payload.version, payload.destination, payload.folder)
    except dbs.DatabaseError as exc:
        return _db_refusal(exc)


@router.post("/databases/amrfinderplus/download", response_model=ReferenceDatabaseRead,
             status_code=status.HTTP_202_ACCEPTED)
def release_download(payload: AmrReleaseStartRequest, db: Session = Depends(get_db)):
    """Download a release (after the user confirmed its size and NCBI's terms) and index it with amrfinder_index."""
    try:
        record = amrfinder_db.start(db, payload.version, payload.confirm_bytes, payload.accept_terms,
                                    payload.destination, payload.folder)
    except (dbs.DatabaseError, dbs.DatabaseStateError, dbs.DatabaseSpaceError) as exc:
        return _db_refusal(exc)
    return database_read(db, record)
