import json
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import project_or_404, sample_or_404
from app.db.session import get_db
from app.services import locations, project_report
from app.services.reports import collect_report_data, render_csv, render_html, render_json
from app.storage import get_storage
from app.storage.local import sanitize_filename

router = APIRouter(tags=["reports"])


class ReportFormat(str, Enum):
    html = "html"
    json = "json"
    csv = "csv"


_MEDIA = {
    ReportFormat.html: "text/html; charset=utf-8",
    ReportFormat.json: "application/json",
    ReportFormat.csv: "text/csv; charset=utf-8",
}
_RENDER = {ReportFormat.html: render_html, ReportFormat.json: render_json, ReportFormat.csv: render_csv}


def _archive(rel: str, content: str | bytes) -> bool:
    """Keep a copy of a downloaded report under reports/, unless the data folder may not be written now (its disk
    is missing, or another disk with its own data is in its place, as for every change: storage_guard). The report
    is downloaded either way."""
    try:
        locations.ensure_data()
    except locations.StorageUnavailable:
        return False
    if isinstance(content, bytes):
        target = get_storage().resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    else:
        get_storage().write_text(rel, content)
    return True


@router.get("/samples/{sample_id}/report")
def sample_report(
    sample_id: str,
    fmt: ReportFormat = Query(default=ReportFormat.html, alias="format"),
    db: Session = Depends(get_db),
):
    """Generate, archive and download a sequencing-data report for one sample."""
    sample = sample_or_404(db, sample_id)
    content = _RENDER[fmt](collect_report_data(db, sample))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"ARVA_{sanitize_filename(sample.sample_code)}_sequencing_report_{stamp}.{fmt.value}"
    _archive(f"reports/{sample.project_id}/{sample.id}/{filename}", content)
    return Response(
        content,
        media_type=_MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ProjectReportFormat(str, Enum):
    html = "html"
    json = "json"
    csv = "csv"
    pdf = "pdf"


@router.get("/projects/{project_id}/report")
def download_project_report(
    project_id: str,
    fmt: ProjectReportFormat = Query(default=ProjectReportFormat.html, alias="format"),
    lang: Literal["en", "es"] = "en",
    db: Session = Depends(get_db),
):
    """The full project report (QC, assembly, species and typing, AMR, virulence, replicons, comparative genomics,
    pangenome and phylogeny, methods with versions and citations, limitations), archived and downloaded. HTML and
    PDF follow `lang`; JSON keys and CSV headers stay English."""
    project = project_or_404(db, project_id)
    data = project_report.collect(db, project, lang)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"ARVA_{sanitize_filename(project.name)}_project_report_{stamp}.{fmt.value}"
    if fmt is ProjectReportFormat.pdf:
        if not project_report.pdf_available():
            return JSONResponse(status_code=503, content={
                "detail": "PDF rendering needs WeasyPrint and its Pango libraries, which are not installed; download "
                          "the HTML report and print it to PDF from the browser.",
                "code": "report_pdf_unavailable", "params": {}})
        content: bytes | str = project_report.render_pdf(project_report.render_html(data, lang))
        _archive(f"reports/{project.id}/{filename}", content)
        media = "application/pdf"
    else:
        content = {"html": lambda: project_report.render_html(data, lang),
                   "json": lambda: json.dumps(data, indent=2, default=str),
                   "csv": lambda: project_report.render_csv(data)}[fmt.value]()
        _archive(f"reports/{project.id}/{filename}", content)
        media = {"html": "text/html; charset=utf-8", "json": "application/json",
                 "csv": "text/csv; charset=utf-8"}[fmt.value]
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
