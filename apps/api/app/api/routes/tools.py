from pathlib import Path

from arva_tools.fastp import FastpParams
from arva_tools.filtlong import FiltlongParams
from arva_tools.multiqc import REPORT_FILENAME as MULTIQC_REPORT
from arva_tools.registry import detect_all
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import job_or_404, project_or_404, raw_file_or_404, sample_or_404
from app.db.session import get_db
from app.models import (
    AnalysisJob,
    FileFormat,
    JobStatus,
    Project,
    QCResult,
    RawFile,
    Sample,
    SequencingTechnology,
)
from app.schemas.schemas import (
    AnalysisJobRead,
    CrossCheckRead,
    FastpDataRead,
    FastpRequest,
    FastqcDataRead,
    FilesRequest,
    FiltlongRequest,
    LibraryRead,
    MultiqcPlanRead,
    MultiqcRequest,
    NanoplotRequest,
    ToolRead,
)
from app.services import crosscheck, multiqc, qc_data
from app.services.jobs import (
    FASTQ_STATS_JOB,
    MULTIQC_JOB,
    SEQKIT_JOB,
    ToolUnavailableError,
    create_fastp_job,
    create_filtlong_job,
    create_multiqc_job,
    create_per_file_tool_jobs,
    create_pod5_jobs,
)
from app.services.raw_signal import POD5_LIBRARY, is_raw_signal, not_reads_message, pod5_versions
from app.storage import get_storage

router = APIRouter(tags=["tools"])

FASTQ_FORMATS = {FileFormat.fastq, FileFormat.fastq_gz}
LONG_READ_TECHNOLOGIES = {SequencingTechnology.nanopore, SequencingTechnology.pacbio}
_TOOL_NAMES = {"seqkit": "SeqKit", "fastqc": "FastQC"}

# Tool HTML reports run in an opaque, sandboxed origin and may not load anything
# from the network (fastp's report, for example, references plotly.js on a CDN).
REPORT_CSP = (
    "sandbox allow-scripts allow-popups; default-src 'none'; img-src data: blob:; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:"
)
# MultiQC's report is sandboxed too (it is served with multiqc.STORAGE_SHIM); checked in Chromium by
# scripts/check_multiqc_report.cjs: plots render, no request leaves the page, it cannot script ARVA's origin.
MULTIQC_REPORT_CSP = (
    "sandbox allow-scripts allow-popups; default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; font-src 'none'; frame-src 'none'; "
    "base-uri 'none'; form-action 'none'"
)
_REPORT_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


@router.get("/tools", response_model=list[ToolRead])
def list_tools(refresh: bool = Query(default=False)):
    out = []
    for d in detect_all(refresh=refresh):
        i = d.info
        out.append(
            ToolRead(
                id=i.id, name=i.name, description=i.description, homepage=i.homepage, license=i.license,
                citation=i.citation, citation_url=i.citation_url, categories=list(i.categories),
                input_formats=list(i.input_formats), output_formats=list(i.output_formats),
                min_version=i.min_version, tested_versions=list(i.tested_versions), install=dict(i.install),
                status=d.status.value, path=d.path, version=d.version,
                version_validated=d.version_validated, message=d.message, reason=d.reason,
            )
        )
    return out


@router.get("/tools/libraries", response_model=list[LibraryRead])
def list_libraries():
    """Optional Python libraries, detected from package metadata (never imported by the API)."""
    versions = pod5_versions()
    installed = versions["pod5"]
    return [
        LibraryRead(
            **POD5_LIBRARY,
            status="available" if installed else "not_installed",
            version=installed,
            companion_versions={"lib_pod5": versions["lib_pod5"]},
            version_validated=installed == POD5_LIBRARY["required_version"],
        )
    ]


def _owned(db: Session, sample: Sample, ids: list[str]) -> list[RawFile]:
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The same file was given more than once")
    files = []
    for file_id in ids:
        f = db.get(RawFile, file_id)
        if f is None or f.sample_id != sample.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File {file_id} does not belong to this sample")
        files.append(f)
    return files


def _sample_files(db: Session, sample: Sample, ids: list[str], analysis: str) -> list[RawFile]:
    files = _owned(db, sample, ids)
    for f in files:
        if is_raw_signal(f):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, not_reads_message(f, analysis))
        if f.file_format is FileFormat.unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{f.original_filename} is not a FASTQ/FASTA file")
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The same file was given more than once")
    return files


def _require_fastq(files: list[RawFile]) -> None:
    for f in files:
        if f.file_format not in FASTQ_FORMATS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{f.original_filename}: this tool requires FASTQ input")
        if not f.is_valid:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{f.original_filename} failed validation and cannot be processed: {f.validation_message}",
            )


def _tool_call(fn, *args):
    try:
        return fn(*args)
    except ToolUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# Declared before /analyses/{tool_id} so that it takes precedence.
@router.post("/samples/{sample_id}/analyses/pod5", response_model=list[AnalysisJobRead],
             status_code=status.HTTP_202_ACCEPTED)
def start_pod5_summary(sample_id: str, payload: FilesRequest, db: Session = Depends(get_db)):
    """Read the run metadata of each selected POD5 file with the pod5 library (one job per file)."""
    sample = sample_or_404(db, sample_id)
    files = _owned(db, sample, payload.raw_file_ids)
    for f in files:
        if not is_raw_signal(f):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{f.original_filename} is not a POD5 file")
        if not f.is_valid:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{f.original_filename} failed validation and cannot be read: {f.validation_message}",
            )
    return _tool_call(create_pod5_jobs, db, sample, files)


@router.post("/samples/{sample_id}/analyses/nanoplot", response_model=list[AnalysisJobRead],
             status_code=status.HTTP_202_ACCEPTED)
def start_nanoplot(sample_id: str, payload: NanoplotRequest, db: Session = Depends(get_db)):
    """NanoPlot on each selected long-read FASTQ file (one job per file)."""
    sample = sample_or_404(db, sample_id)
    files = _sample_files(db, sample, payload.raw_file_ids, "NanoPlot")
    _require_fastq(files)
    technology = sample.sequencing_technology
    if technology not in LONG_READ_TECHNOLOGIES and not payload.long_reads_confirmed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"NanoPlot is meant for long reads (Oxford Nanopore or PacBio), and this sample's sequencing technology "
            f"is '{technology.value}'. Set the technology in the sample's metadata, or confirm that the selected "
            "files contain long reads.",
        )
    parameters = {"long_reads_confirmed": payload.long_reads_confirmed, "sequencing_technology": technology.value}
    return _tool_call(create_per_file_tool_jobs, db, sample, files, "nanoplot", parameters)


@router.post("/samples/{sample_id}/analyses/{tool_id}", response_model=list[AnalysisJobRead],
             status_code=status.HTTP_202_ACCEPTED)
def start_per_file_tool(sample_id: str, tool_id: str, payload: FilesRequest, db: Session = Depends(get_db)):
    """Run SeqKit (`seqkit`) or FastQC (`fastqc`) on each selected file."""
    if tool_id not in ("seqkit", "fastqc"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown analysis '{tool_id}'")
    sample = sample_or_404(db, sample_id)
    files = _sample_files(db, sample, payload.raw_file_ids, _TOOL_NAMES[tool_id])
    if tool_id == "fastqc":
        _require_fastq(files)
    return _tool_call(create_per_file_tool_jobs, db, sample, files, tool_id)


@router.post("/samples/{sample_id}/filtering/fastp", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_fastp(sample_id: str, payload: FastpRequest, db: Session = Depends(get_db)):
    sample = sample_or_404(db, sample_id)
    ids = [payload.read1_file_id] + ([payload.read2_file_id] if payload.read2_file_id else [])
    files = _sample_files(db, sample, ids, "fastp")
    _require_fastq(files)
    if len(files) == 2 and (files[0].read_mate == "R2" or files[1].read_mate == "R1"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Read 1 and read 2 appear to be swapped (check R1/R2)")
    params = FastpParams(**payload.params.model_dump())
    return _tool_call(create_fastp_job, db, sample, files[0], files[1] if len(files) == 2 else None, params)


@router.post("/samples/{sample_id}/filtering/filtlong", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_filtlong(sample_id: str, payload: FiltlongRequest, db: Session = Depends(get_db)):
    sample = sample_or_404(db, sample_id)
    (f,) = _sample_files(db, sample, [payload.file_id], "Filtlong")
    _require_fastq([f])
    params = FiltlongParams(**payload.params.model_dump())
    return _tool_call(create_filtlong_job, db, sample, f, params)


def _multiqc_plan(db: Session, project: Project, payload: MultiqcRequest) -> multiqc.Plan:
    try:
        return multiqc.plan(db, project, payload.sample_ids, payload.include_derived)
    except multiqc.SelectionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/projects/{project_id}/analyses/multiqc/preview", response_model=MultiqcPlanRead)
def preview_multiqc(project_id: str, payload: MultiqcRequest, db: Session = Depends(get_db)):
    """Which tool results a MultiQC report would include, and why others would not (nothing is run)."""
    plan = _multiqc_plan(db, project_or_404(db, project_id), payload)
    return {**plan.as_dict(), "include_derived": payload.include_derived}


@router.post("/projects/{project_id}/analyses/multiqc", response_model=AnalysisJobRead,
             status_code=status.HTTP_202_ACCEPTED)
def start_multiqc(project_id: str, payload: MultiqcRequest, db: Session = Depends(get_db)):
    """One MultiQC report over the latest qualifying FastQC, fastp, SeqKit and Filtlong results."""
    project = project_or_404(db, project_id)
    plan = _multiqc_plan(db, project, payload)
    if not plan.inputs:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Nothing to aggregate: none of the selected samples has a qualifying FastQC, fastp, SeqKit or "
            "Filtlong result. " + multiqc.SELECTION_RULE,
        )
    file_ids = list(dict.fromkeys(f for i in plan.inputs for f in i.file_ids))
    parameters = {**plan.as_dict(), "include_derived": payload.include_derived}
    return _tool_call(create_multiqc_job, db, project, parameters, file_ids)


@router.get("/jobs/{job_id}/outputs/{name}")
def job_output(job_id: str, name: str, download: bool = False, db: Session = Depends(get_db)):
    job = job_or_404(db, job_id)
    match = next((p for p in job.output_paths or [] if Path(p).name == name), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such output for this job")
    path = get_storage().resolve(match)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output file is missing on disk")
    if name.endswith(".html") and not download:
        if job.job_type == MULTIQC_JOB and name == MULTIQC_REPORT:
            return Response(multiqc.sandboxed_report(path.read_bytes()), media_type="text/html; charset=utf-8",
                            headers={"Content-Security-Policy": MULTIQC_REPORT_CSP, **_REPORT_HEADERS})
        return FileResponse(path, media_type="text/html; charset=utf-8",
                            headers={"Content-Security-Policy": REPORT_CSP, **_REPORT_HEADERS})
    media = "text/plain; charset=utf-8" if name.endswith((".log", ".tsv", ".json")) else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=name)


def _qc_data(fn, job: AnalysisJob) -> dict:
    try:
        return fn(job)
    except qc_data.QcDataError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/jobs/{job_id}/fastqc-data", response_model=FastqcDataRead)
def fastqc_data(job_id: str, db: Session = Depends(get_db)):
    """Adapter content, duplication levels and overrepresented sequences of a completed FastQC job."""
    return _qc_data(qc_data.fastqc_data, job_or_404(db, job_id))


@router.get("/jobs/{job_id}/fastp-data", response_model=FastpDataRead)
def fastp_data(job_id: str, db: Session = Depends(get_db)):
    """Per-cycle curves, adapter trimming, duplication rate and insert sizes from a completed fastp job."""
    return _qc_data(qc_data.fastp_data, job_or_404(db, job_id))


@router.get("/files/{file_id}/crosscheck", response_model=CrossCheckRead)
def file_crosscheck(file_id: str, db: Session = Depends(get_db)):
    f = raw_file_or_404(db, file_id)
    if is_raw_signal(f):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, not_reads_message(f, "the SeqKit cross-check"))
    jobs = db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.sample_id == f.sample_id, AnalysisJob.status == JobStatus.completed,
               AnalysisJob.job_type.in_([SEQKIT_JOB, FASTQ_STATS_JOB]))
        .order_by(AnalysisJob.finished_at.desc())
    ).all()
    seqkit_job = next((j for j in jobs if j.job_type == SEQKIT_JOB and file_id in (j.input_raw_file_ids or [])), None)
    qc = db.scalars(
        select(QCResult).where(QCResult.raw_file_id == file_id).order_by(QCResult.created_at.desc())
    ).first()
    rows = []
    if seqkit_job and qc and seqkit_job.result_summary:
        rows = crosscheck.compare(qc.metrics, seqkit_job.result_summary["seqkit_stats"])
    decided = [r["agrees"] for r in rows if r["agrees"] is not None]
    return CrossCheckRead(
        raw_file_id=file_id,
        tool="SeqKit",
        tool_version=seqkit_job.tool_version if seqkit_job else None,
        arva_job_id=qc.analysis_job_id if qc else None,
        tool_job_id=seqkit_job.id if seqkit_job else None,
        rows=rows,
        all_agree=all(decided) if decided else None,
        note=crosscheck.NOTE,
    )
