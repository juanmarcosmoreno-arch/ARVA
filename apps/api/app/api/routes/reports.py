from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import sample_or_404
from app.db.session import get_db
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


@router.get("/samples/{sample_id}/report")
def sample_report(
    sample_id: str,
    fmt: ReportFormat = Query(default=ReportFormat.html, alias="format"),
    db: Session = Depends(get_db),
):
    """Generate, archive and download a sequencing-data report for one sample."""
    sample = sample_or_404(db, sample_id)
    content = _RENDER[fmt](collect_report_data(db, sample))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"ARVA_{sanitize_filename(sample.sample_code)}_sequencing_report_{stamp}.{fmt.value}"
    get_storage().write_text(f"reports/{sample.project_id}/{sample.id}/{filename}", content)
    return Response(
        content,
        media_type=_MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
