import re

from arva_core.formats import is_gzip
from arva_core.gfa import GfaFormatError
from arva_tools.flye import FlyeParams
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, sample_or_404
from app.api.routes.tools import _owned, _tool_call
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Assembly, Sample
from app.schemas.schemas import (
    AnalysisJobRead,
    AssemblyDetail,
    AssemblyGraphRead,
    AssemblyRead,
    FlyePlanRead,
    FlyePreviewRequest,
    FlyeRequest,
)
from app.services import flye
from app.services.assemblies import GRAPH_MAX_EDGES, GRAPH_MAX_NODES, assembly_graph
from app.services.jobs import create_flye_job
from app.storage import get_storage
from app.storage.local import sanitize_filename

router = APIRouter(tags=["assemblies"])


def _assembly_or_404(db: Session, assembly_id: str) -> Assembly:
    return get_or_404(db, Assembly, assembly_id, "Assembly")


@router.get("/samples/{sample_id}/assemblies", response_model=list[AssemblyRead])
def list_sample_assemblies(sample_id: str, db: Session = Depends(get_db)):
    """Assemblies of the sample, newest first (per-contig rows: GET /assemblies/{id})."""
    sample_or_404(db, sample_id)
    return db.scalars(
        select(Assembly).where(Assembly.sample_id == sample_id).order_by(Assembly.created_at.desc())
    ).all()


@router.get("/assemblies/{assembly_id}", response_model=AssemblyDetail)
def get_assembly(assembly_id: str, db: Session = Depends(get_db)):
    return _assembly_or_404(db, assembly_id)


@router.get("/assemblies/{assembly_id}/contigs.fasta")
def download_contigs(assembly_id: str, db: Session = Depends(get_db)):
    assembly = _assembly_or_404(db, assembly_id)
    path = get_storage().resolve(assembly.contigs_path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The contigs file is missing on disk")
    sample = db.get(Sample, assembly.sample_id)
    stem = sanitize_filename(re.sub(r"[\\/]", " ", f"{sample.sample_code}_{assembly.assembler}_{assembly.id[:8]}_contigs"))
    return FileResponse(path, media_type="application/octet-stream",
                        filename=stem + (".fasta.gz" if is_gzip(path) else ".fasta"))


@router.get("/assemblies/{assembly_id}/graph", response_model=AssemblyGraphRead)
def get_assembly_graph(
    assembly_id: str,
    max_nodes: int = Query(default=GRAPH_MAX_NODES, ge=1, le=20_000),
    max_edges: int = Query(default=GRAPH_MAX_EDGES, ge=0, le=50_000),
    db: Session = Depends(get_db),
):
    """The assembly graph (GFA 1) as segments and links; the longest segments when there are more than max_nodes."""
    assembly = _assembly_or_404(db, assembly_id)
    try:
        return assembly_graph(assembly, max_nodes, max_edges)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This assembly has no assembly graph" if not assembly.graph_path else "The graph file is missing on disk",
        ) from None
    except GfaFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"The assembly graph cannot be read: {exc}") from exc


@router.post("/samples/{sample_id}/assembly/flye/preview", response_model=FlyePlanRead)
def preview_flye(sample_id: str, payload: FlyePreviewRequest, db: Session = Depends(get_db)):
    """What ARVA knows before a Flye run: the installed Flye and its options, each file's evidence (read headers,
    ARVA statistics), a heuristic read-type suggestion and the genome-size options. Nothing is run."""
    sample = sample_or_404(db, sample_id)
    files = _owned(db, sample, payload.raw_file_ids)
    try:
        return flye.plan(db, sample, files, payload.assumed_depth_x)
    except flye.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/samples/{sample_id}/assembly/flye", response_model=AnalysisJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_flye(sample_id: str, payload: FlyeRequest, db: Session = Depends(get_db)):
    """Assemble the selected long-read FASTQ files (imported or derived) with Flye in one background job."""
    sample = sample_or_404(db, sample_id)
    files = _owned(db, sample, payload.raw_file_ids)
    values = payload.params.model_dump()
    threads = values.pop("threads") or get_settings().tool_threads
    params = FlyeParams(**values, threads=threads)
    try:
        ev = flye.evidence(db, files)
        flye.check_files(sample, files, ev, params.read_type)
        if flye.needs_confirmation(sample) and not payload.long_reads_confirmed:
            raise flye.InputError(
                f"Flye assembles long reads (Oxford Nanopore or PacBio), and this sample's sequencing technology is "
                f"'{sample.sequencing_technology.value}'. Set the technology in the sample's metadata, or confirm "
                "that the selected files contain long reads."
            )
        try:
            params.validate()
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        flye.check_genome_size(db, sample, ev, params)
    except flye.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    suggestion = flye.read_type_suggestion(sample, ev)
    provenance = {
        "long_reads_confirmed": payload.long_reads_confirmed,
        "sequencing_technology": sample.sequencing_technology.value,
        "arva_read_type_suggestion": {k: suggestion[k] for k in ("value", "basis", "platform", "platform_source",
                                                                 "mean_error_rate")},
    }
    return _tool_call(create_flye_job, db, sample, files, params, provenance)
