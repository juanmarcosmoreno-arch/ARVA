import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import project_or_404
from app.db.session import get_db
from app.schemas.schemas import QcOverviewRead
from app.services import qc_overview
from app.storage.local import sanitize_filename

router = APIRouter(tags=["overview"])


@router.get("/projects/{project_id}/qc-overview", response_model=QcOverviewRead)
def project_qc_overview(project_id: str, db: Session = Depends(get_db)):
    """One row per sample, built only from completed jobs; values that cannot be stated exactly are null."""
    project_or_404(db, project_id)
    return {"project_id": project_id, "rows": qc_overview.build_overview(db, project_id)}


@router.get("/projects/{project_id}/qc-overview.csv")
def project_qc_overview_csv(project_id: str, db: Session = Depends(get_db)):
    """The same rows as CSV (UTF-8 with BOM, every text cell neutralised against formula injection)."""
    project = project_or_404(db, project_id)
    content = qc_overview.render_csv(qc_overview.build_overview(db, project_id))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = sanitize_filename(re.sub(r"[\\/]", " ", project.name))
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ARVA_{name}_qc_overview_{stamp}.csv"'})
