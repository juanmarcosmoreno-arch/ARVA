import re

from arva_core.formats import is_gzip
from arva_core.gfa import GfaFormatError
from arva_tools import ToolStatus
from arva_tools.flye import FlyeParams
from arva_tools.pilon import PilonParams
from arva_tools.quast import QuastParams
from arva_tools.racon import RaconParams
from arva_tools.registry import detect
from arva_tools.spades import SpadesParams
from arva_tools.unicycler import UnicyclerParams
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, project_or_404, sample_or_404
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
    PolishingPlanRead,
    PolishingPreviewRequest,
    PolishingRequest,
    ProjectAssemblyRead,
    QuastPlanRead,
    QuastPreviewRequest,
    QuastRequest,
    ShortReadPlanRead,
    ShortReadPreviewRequest,
    SpadesRequest,
    UnicyclerPlanRead,
    UnicyclerPreviewRequest,
    UnicyclerRequest,
)
from app.services import flye, polishing, quast, short_hybrid
from app.services.assemblies import GRAPH_MAX_EDGES, GRAPH_MAX_NODES, assembly_graph
from app.services.jobs import (
    create_flye_job,
    create_polishing_job,
    create_quast_job,
    create_spades_job,
    create_unicycler_job,
)
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


@router.get("/projects/{project_id}/assemblies", response_model=list[ProjectAssemblyRead])
def list_project_assemblies(project_id: str, db: Session = Depends(get_db)):
    """Every assembly of the project's samples with its summary statistics, by sample code and newest first."""
    project_or_404(db, project_id)
    rows = db.execute(
        select(Assembly, Sample.sample_code).join(Sample, Sample.id == Assembly.sample_id)
        .where(Sample.project_id == project_id).order_by(Sample.sample_code, Assembly.created_at.desc())
    ).all()
    return [
        {
            "id": a.id, "sample_id": a.sample_id, "sample_code": code, "job_id": a.job_id, "kind": a.kind,
            "parent_assembly_id": a.parent_assembly_id, "assembler": a.assembler,
            "assembler_version": a.assembler_version, "mode": a.mode, "read_type": a.read_type,
            **{k: a.stats[k] for k in ("contig_count", "total_length", "largest_contig", "n50", "l50", "gc_percent")},
            "circular_contigs": a.stats["circularity"]["circular_contigs"],
            "contigs_with_circularity": a.stats["circularity"]["contigs_with_circularity"],
            "median_coverage": a.stats["coverage"]["length_weighted_median"],
            "coverage_kind": a.coverage_kind,
            "warning_codes": [w["code"] for w in a.warnings],
            "created_at": a.created_at,
        }
        for a, code in rows
    ]


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


def _short_hybrid_inputs(db: Session, sample: Sample, roles: dict[str, str | None], tool: str, confirmed: bool,
                         check: bool = True) -> short_hybrid.Inputs:
    try:
        inputs = short_hybrid.resolve_inputs(db, sample, roles)
        if check:
            short_hybrid.check_inputs(sample, inputs, short_hybrid.file_evidence(db, inputs), tool, confirmed)
    except flye.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return inputs


def _provenance(sample: Sample, inputs: short_hybrid.Inputs, confirmed: bool, memory_given: bool) -> dict:
    return {"reads_confirmed": confirmed, "sequencing_technology": sample.sequencing_technology.value,
            "read_layout": short_hybrid.library_layout(inputs.ids()),
            "memory_source": "user" if memory_given else "default: min(250 GB, ARVA's memory cap)"}


@router.post("/samples/{sample_id}/assembly/spades/preview", response_model=ShortReadPlanRead)
def preview_spades(sample_id: str, payload: ShortReadPreviewRequest, db: Session = Depends(get_db)):
    """What ARVA knows before a SPAdes run: the installed SPAdes and its options, the thread and memory limits, each
    file's evidence by role, and why the files cannot be assembled as chosen (if so). Nothing is run."""
    sample = sample_or_404(db, sample_id)
    inputs = _short_hybrid_inputs(db, sample, payload.inputs.roles(), "SPAdes", True, check=False)
    return short_hybrid.plan(db, sample, inputs, "SPAdes")


@router.post("/samples/{sample_id}/assembly/spades", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_spades(sample_id: str, payload: SpadesRequest, db: Session = Depends(get_db)):
    """Assemble short reads (a pair of files, unpaired reads, or both) with SPAdes in one background job."""
    sample = sample_or_404(db, sample_id)
    inputs = _short_hybrid_inputs(db, sample, payload.inputs.roles(), "SPAdes", payload.reads_confirmed)
    values = payload.params.model_dump()
    threads = values.pop("threads") or get_settings().tool_threads
    memory = values.pop("memory_gb")
    params = SpadesParams(**values, threads=threads,
                          memory_gb=memory or short_hybrid.memory_options()["default_memory_gb"])
    try:
        params.validate()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    roles = {r: getattr(inputs, r) for r in short_hybrid.SHORT_ROLES}
    return _tool_call(create_spades_job, db, sample, roles, params,
                      _provenance(sample, inputs, payload.reads_confirmed, memory is not None))


@router.post("/samples/{sample_id}/assembly/unicycler/preview", response_model=UnicyclerPlanRead)
def preview_unicycler(sample_id: str, payload: UnicyclerPreviewRequest, db: Session = Depends(get_db)):
    """What ARVA knows before a Unicycler run: the installed Unicycler, its helpers and the modes they allow, the
    limits, each file's evidence by role, the assembly mode the roles imply, and any problem. Nothing is run."""
    sample = sample_or_404(db, sample_id)
    inputs = _short_hybrid_inputs(db, sample, payload.inputs.roles(), "Unicycler", True, check=False)
    return short_hybrid.plan(db, sample, inputs, "Unicycler")


@router.post("/samples/{sample_id}/assembly/unicycler", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_unicycler(sample_id: str, payload: UnicyclerRequest, db: Session = Depends(get_db)):
    """Assemble with Unicycler in one background job: short reads, long reads, or both (hybrid), as the roles given
    imply."""
    sample = sample_or_404(db, sample_id)
    inputs = _short_hybrid_inputs(db, sample, payload.inputs.roles(), "Unicycler", payload.reads_confirmed)
    values = payload.params.model_dump()
    threads = values.pop("threads") or get_settings().tool_threads
    memory = values.pop("spades_memory_gb")
    params = UnicyclerParams(assembly_mode=inputs.assembly_mode(), **values, threads=threads,
                             spades_memory_gb=memory or short_hybrid.memory_options()["default_memory_gb"])
    try:
        params.validate()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    roles = {r: getattr(inputs, r) for r in short_hybrid.ROLES}
    return _tool_call(create_unicycler_job, db, sample, roles, params,
                      _provenance(sample, inputs, payload.reads_confirmed, memory is not None))


@router.post("/samples/{sample_id}/assembly/quast/preview", response_model=QuastPlanRead)
def preview_quast(sample_id: str, payload: QuastPreviewRequest, db: Session = Depends(get_db)):
    """What a QUAST run would use: the installed QUAST and minimap2, each assembly's label and how many of its contigs
    reach the minimum contig length, and the reference. Nothing is run."""
    sample = sample_or_404(db, sample_id)
    try:
        return quast.plan(db, sample, payload.assembly_ids, payload.reference_file_id, payload.min_contig)
    except quast.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/samples/{sample_id}/assembly/quast", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_quast(sample_id: str, payload: QuastRequest, db: Session = Depends(get_db)):
    """Evaluate (and compare) assemblies of the sample with QUAST in one background job, optionally against a
    reference genome chosen from the sample's FASTA files."""
    sample = sample_or_404(db, sample_id)
    params = QuastParams(min_contig=payload.min_contig, threads=payload.threads or get_settings().tool_threads)
    try:
        assemblies = quast.assemblies_for(db, sample, payload.assembly_ids)
        reference = quast.reference_for(db, sample, payload.reference_file_id)
        quast.check_contigs_kept(assemblies, [quast.summary_at(a, params.min_contig) for a in assemblies],
                                 params.min_contig)
    except quast.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _tool_call(create_quast_job, db, sample, assemblies, quast.labels(assemblies), reference, params)


def _polishing_context(db: Session, assembly_id: str, roles: dict[str, str | None]):
    a = _assembly_or_404(db, assembly_id)
    sample = db.get(Sample, a.sample_id)
    try:
        return sample, polishing.draft_for(db, sample, a.id), short_hybrid.resolve_inputs(db, sample, roles)
    except flye.InputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/assemblies/{assembly_id}/polishing/preview", response_model=PolishingPlanRead)
def preview_polishing(assembly_id: str, payload: PolishingPreviewRequest, db: Session = Depends(get_db)):
    """What ARVA knows before polishing this assembly: the tools of each strategy, the strategy the chosen reads imply
    and the one the sample's technology calls for, each file's evidence, a heuristic read-type suggestion for the long
    reads, the limits, and why the reads cannot be used as chosen (if so). Nothing is run."""
    sample, draft, inputs = _polishing_context(db, assembly_id, payload.inputs.roles())
    return polishing.plan(db, sample, draft, inputs, payload.read_type)


@router.post("/assemblies/{assembly_id}/polishing", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_polishing(assembly_id: str, payload: PolishingRequest, db: Session = Depends(get_db)):
    """Polish this assembly in the background: Racon with long reads, Pilon with short reads, or Racon then Pilon
    (hybrid; the Pilon job is queued when Racon's result is registered). Each result is a new assembly linked to its
    draft, with the comparison of draft and polished sequence; with `quast`, QUAST then compares them."""
    sample, draft, inputs = _polishing_context(db, assembly_id, payload.inputs.roles())
    try:
        ev = short_hybrid.file_evidence(db, inputs)
        polishing.check_request(sample, inputs, ev, payload.strategy, payload.racon.read_type, payload.reads_confirmed)
        reference = quast.reference_for(db, sample, payload.quast_reference_file_id) if payload.quast else None
    except (flye.InputError, quast.InputError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if payload.quast and detect("quast", refresh=True).status is not ToolStatus.available:
        raise HTTPException(status.HTTP_409_CONFLICT, "QUAST is not available, so the assemblies cannot be compared "
                                                      "with it; polish without the QUAST comparison or install QUAST")
    threads = payload.threads or get_settings().tool_threads
    racon = pilon = None
    if payload.strategy in ("racon", "hybrid"):
        racon = RaconParams(**payload.racon.model_dump(), threads=threads)
    if payload.strategy in ("pilon", "hybrid"):
        values = payload.pilon.model_dump()
        heap = values.pop("heap_gb")
        pilon = PilonParams(**values, heap_gb=heap or polishing.resources()["default_heap_gb"], threads=threads)
    try:
        for params in (racon, pilon):
            if params is not None:
                params.validate()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    provenance = {
        "reads_confirmed": payload.reads_confirmed,
        "sequencing_technology": sample.sequencing_technology.value,
        "read_layout": short_hybrid.library_layout(inputs.ids()),
        "arva_strategy_suggestion": polishing.suggested_strategy(sample),
        "arva_read_type_suggestion": polishing.preset_suggestion(sample, ev)["value"],
        "heap_source": None if pilon is None else "user" if payload.pilon.heap_gb else
        "default: min(16 GB, ARVA's memory cap)",
        "quast": payload.quast,
        "quast_reference_file_id": reference.id if reference else None,
    }
    roles = {r: getattr(inputs, r) for r in short_hybrid.ROLES}
    return _tool_call(create_polishing_job, db, sample, draft, payload.strategy, roles, racon, pilon, provenance)
