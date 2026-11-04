"""Sanger reads of one gene: import, pairing, trimming, chromatogram, consensus, identification searches and the
report (app.services.sanger, app.services.sanger_report)."""
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.access import keep_visible, visible_projects
from app.api.deps import get_or_404, sample_or_404
from app.api.routes.tools import _tool_call
from app.db.session import get_db
from app.models import SangerIdentification, SangerRead
from app.schemas.schemas import (
    AnalysisJobRead,
    Ncbi16sPlanRequest,
    Ncbi16sStartRequest,
    ReferenceDatabaseRead,
    SangerBuildIn,
    SangerIdentificationIn,
    SangerIdentificationUpdateIn,
    SangerReadUpdateIn,
    SangerSearchIn,
)
from app.services import databases as dbs
from app.services import ncbi16s_db
from app.services import sanger as svc
from app.services import sanger_report as report
from app.services.jobs import ToolUnavailableError
from app.storage.local import sanitize_filename

router = APIRouter(tags=["sanger"])
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"}


def _error(exc: svc.InputError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST,
                        content={"detail": str(exc), "code": exc.code, "params": exc.params})


def _read(db: Session, read_id: str) -> SangerRead:
    return get_or_404(db, SangerRead, read_id, "Sanger read")


def _ident(db: Session, identification_id: str) -> SangerIdentification:
    return get_or_404(db, SangerIdentification, identification_id, "Sanger identification")


def _raise(exc: Exception):
    raise exc


def _search_request(payload: SangerSearchIn) -> dict:
    out = payload.model_dump()
    out["blast"] = {k: v.model_dump() for k, v in payload.blast.items()}
    return out


@router.get("/samples/{sample_id}/sanger")
def sample_sanger(sample_id: str, db: Session = Depends(get_db)):
    """The sample's Sanger reads (with the direction and pair ARVA proposed or the user set), the proposed pairs,
    its identifications and its genomes in ARVA (searchable as a source)."""
    return svc.sample_overview(db, sample_or_404(db, sample_id))


@router.post("/samples/{sample_id}/sanger/reads", status_code=status.HTTP_201_CREATED)
def import_reads(sample_id: str, files: list[UploadFile] = File(..., description=".ab1 chromatograms, or FASTA or "
                                                                               ".seq text files"),
                 db: Session = Depends(get_db)):
    """Store each file in raw/ unchanged and record its reads; a file that cannot be read, or was already imported
    into this sample, is listed under `skipped` with its reason. Directions and pairs are proposed from the names."""
    sample = sample_or_404(db, sample_id)
    limit = svc.max_upload_bytes()

    def reader(f: UploadFile):
        # Read when the service reaches this file, so one file is in memory at a time; one byte over the limit is
        # enough for the service to refuse it as too large.
        def read() -> bytes:
            try:
                return f.file.read(limit + 1)
            finally:
                f.file.close()
        return read

    try:
        if len(files) > svc.MAX_FILES:
            raise svc.InputError("sanger_too_many_files", max=svc.MAX_FILES)
        return svc.import_files(db, sample, [(f.filename or "read", reader(f)) for f in files])
    except svc.InputError as exc:
        return _error(exc)


@router.get("/sanger/reads/{read_id}")
def get_read(read_id: str, limit: float = Query(default=0.05, gt=0, lt=1), manual_start: int | None = Query(None, ge=1),
             manual_end: int | None = Query(None, ge=1), mixed_ratio: float = Query(default=0.33, gt=0, le=1),
             db: Session = Depends(get_db)):
    """The read's bases and qualities, the kept region at this trimming (modified Mott limit, or a manual range) and
    the bases to review (IUPAC calls and mixed peaks)."""
    try:
        return svc.read_detail(db, _read(db, read_id), {"limit": limit, "manual_start": manual_start,
                                                         "manual_end": manual_end}, mixed_ratio)
    except svc.InputError as exc:
        return _error(exc)


@router.get("/sanger/reads/{read_id}/trace")
def get_trace(read_id: str, scan_start: int = Query(default=0, ge=0), scan_end: int | None = Query(None, ge=1),
              max_points: int = Query(default=2000, ge=10, le=20000), db: Session = Depends(get_db)):
    """The chromatogram between two scans, downsampled by block maximum so no peak is lost, with a marker for each
    called base."""
    try:
        return svc.trace(_read(db, read_id), scan_start, scan_end, max_points)
    except svc.InputError as exc:
        return _error(exc)


@router.get("/sanger/reads/{read_id}/file")
def download_read(read_id: str, db: Session = Depends(get_db)):
    """The file as it was uploaded."""
    r = _read(db, read_id)
    media = "application/octet-stream" if r.file_format == "abi" else "text/plain; charset=utf-8"
    return Response(svc.stored_file(r).read_bytes(), media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{sanitize_filename(r.original_filename)}"', **_SAFE_HEADERS})


@router.patch("/sanger/reads/{read_id}")
def update_read(read_id: str, payload: SangerReadUpdateIn, db: Session = Depends(get_db)):
    """Set a read's direction, pair key or name yourself (the ones from its name are only proposals)."""
    try:
        r = svc.update_read(db, _read(db, read_id), payload.direction, payload.pair_key, payload.name)
    except svc.InputError as exc:
        return _error(exc)
    return svc.read_view(db, r)


@router.delete("/sanger/reads/{read_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_read(read_id: str, db: Session = Depends(get_db)):
    """Remove a read's record (refused while an identification uses it); the uploaded file stays in raw/."""
    try:
        svc.delete_read(db, _read(db, read_id))
    except svc.InputError as exc:
        return _error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/samples/{sample_id}/sanger/consensus/preview")
def preview_consensus(sample_id: str, payload: SangerBuildIn, db: Session = Depends(get_db)):
    """What an identification would search, with nothing saved: the trimmed read, or the forward + reverse
    consensus with every column's evidence and every conflict."""
    try:
        b = svc.build(db, sample_or_404(db, sample_id), payload.forward_read_id, payload.reverse_read_id,
                      payload.forward_trim.model_dump(), payload.reverse_trim.model_dump(),
                      payload.consensus.model_dump(), payload.mixed_ratio)
    except svc.InputError as exc:
        return _error(exc)
    return {"mode": b["mode"], "settings": b["settings"], **b["result"]}


@router.post("/samples/{sample_id}/sanger/identifications", status_code=status.HTTP_201_CREATED)
def create_identification(sample_id: str, payload: SangerIdentificationIn, db: Session = Depends(get_db)):
    """Save the consensus (or trimmed read) as an identification, with what you suspect it is (optional)."""
    try:
        ident = svc.create_identification(
            db, sample_or_404(db, sample_id), payload.label, payload.forward_read_id, payload.reverse_read_id,
            payload.forward_trim.model_dump(), payload.reverse_trim.model_dump(), payload.consensus.model_dump(),
            payload.mixed_ratio, payload.suspected.model_dump() if payload.suspected else None, payload.notes)
    except svc.InputError as exc:
        return _error(exc)
    return svc.results(db, ident)


@router.get("/sanger/identifications/{identification_id}")
def get_identification(identification_id: str, db: Session = Depends(get_db)):
    """The identification: reads, consensus and evidence, each search with its database and version, the ranking
    across sources, the 16S reading and the comparison with what you suspected."""
    return svc.results(db, _ident(db, identification_id))


@router.patch("/sanger/identifications/{identification_id}")
def update_identification(identification_id: str, payload: SangerIdentificationUpdateIn,
                          db: Session = Depends(get_db)):
    """Change the label, the notes or what you suspect; the comparison is recomputed from the hits already found."""
    try:
        ident = svc.set_suspected(db, _ident(db, identification_id),
                                  payload.suspected.model_dump() if payload.suspected else None, payload.notes,
                                  payload.label)
    except svc.InputError as exc:
        return _error(exc)
    return svc.results(db, ident)


@router.delete("/sanger/identifications/{identification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identification(identification_id: str, db: Session = Depends(get_db)):
    """Remove the identification and its search results (refused while a search runs); the jobs stay in the job
    ledger and the reads stay."""
    try:
        svc.delete_identification(db, _ident(db, identification_id))
    except svc.InputError as exc:
        return _error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sanger/identifications/{identification_id}/genomes")
def genome_candidates(identification_id: str, request: Request, db: Session = Depends(get_db)):
    """Genomes in ARVA that can be searched: this sample's first, then every other one you may read."""
    from app.services.comparative import candidates

    ident = _ident(db, identification_id)
    rows = keep_visible(candidates(db), visible_projects(request))
    return sorted(rows, key=lambda r: r.get("sample_id") != ident.sample_id)


@router.post("/sanger/identifications/{identification_id}/search/preview")
def preview_search(identification_id: str, payload: SangerSearchIn, db: Session = Depends(get_db)):
    """What the search would do for each source: tool, database and version (or genomes and their checksums),
    settings, and what blocks it."""
    try:
        return svc.search_plan(db, _ident(db, identification_id), _search_request(payload))
    except svc.InputError as exc:
        return _error(exc)


@router.post("/sanger/identifications/{identification_id}/search", response_model=list[AnalysisJobRead],
             status_code=status.HTTP_202_ACCEPTED)
def start_search(identification_id: str, payload: SangerSearchIn, db: Session = Depends(get_db)):
    """Start one job per source (nothing leaves this computer). Needs `confirmed`."""
    ident = _ident(db, identification_id)
    try:
        return svc.start_search(db, ident, _search_request(payload), payload.confirmed, payload.only_runnable)
    except svc.InputError as exc:
        return _error(exc)
    except (ToolUnavailableError, ValueError) as exc:
        return _tool_call(_raise, exc)


@router.get("/sanger/identifications/{identification_id}/consensus.fasta")
def consensus_fasta(identification_id: str, db: Session = Depends(get_db)):
    ident = _ident(db, identification_id)
    return Response(svc.consensus_fasta(ident), media_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{sanitize_filename(ident.label)}.fasta"', **_SAFE_HEADERS})


@router.get("/sanger/identifications/{identification_id}/report")
def identification_report(identification_id: str, fmt: Literal["html", "json", "csv"] = Query("html", alias="format"),
                          lang: Literal["en", "es"] = "en", db: Session = Depends(get_db)):
    """The identification report: reads, trimming, consensus and conflicts, every search with its database and
    version, the ranked hits, the 16S reading with its sources, the suspicion and the parameters. HTML follows
    `lang`; JSON keys and CSV headers stay English."""
    ident = _ident(db, identification_id)
    data = report.collect(db, ident)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"ARVA_{sanitize_filename(ident.label)}_sanger_{stamp}.{fmt}"
    content = {"html": lambda: report.render_html(data, lang), "json": lambda: report.render_json(data),
               "csv": lambda: report.render_csv(data)}[fmt]()
    media = {"html": "text/html; charset=utf-8", "json": "application/json", "csv": "text/csv; charset=utf-8"}[fmt]
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                        **_SAFE_HEADERS})


# --- NCBI's 16S database (Database Manager) ------------------------------------------------------------------------

def _db_refusal(exc: Exception):
    from app.api.routes.databases import _refusal

    if isinstance(exc, ncbi16s_db.Ncbi16sError) and exc.upstream:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY,
                            content={"detail": str(exc), "code": exc.code, "params": exc.params})
    return _refusal(exc)


@router.post("/databases/ncbi-16s/plan")
def ncbi_16s_plan(payload: Ncbi16sPlanRequest, db: Session = Depends(get_db)):
    """What downloading NCBI's current 16S build would do: its date, size and MD5 as NCBI publishes them, the files
    kept, the folder and the space needed. Only NCBI's metadata and MD5 files are read; nothing is sent."""
    try:
        return ncbi16s_db.plan(db, payload.taxonomy, payload.destination, payload.folder)
    except dbs.DatabaseError as exc:
        return _db_refusal(exc)


@router.post("/databases/ncbi-16s/download", response_model=ReferenceDatabaseRead,
             status_code=status.HTTP_202_ACCEPTED)
def ncbi_16s_download(payload: Ncbi16sStartRequest, db: Session = Depends(get_db)):
    """Download the current build after you confirmed its date, size and NCBI's terms; the worker checks the MD5 and
    extracts only the database files (and NCBI's taxonomy files if asked)."""
    from app.api.routes.databases import _read as database_read

    try:
        record = ncbi16s_db.start(db, payload.confirm_version, payload.confirm_bytes, payload.accept_terms,
                                  payload.taxonomy, payload.destination, payload.folder)
    except (dbs.DatabaseError, dbs.DatabaseStateError, dbs.DatabaseSpaceError) as exc:
        return _db_refusal(exc)
    return database_read(db, record)
