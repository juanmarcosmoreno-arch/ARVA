import hashlib
import json
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import project_or_404
from app.core.config import get_settings
from app.db.session import get_db
from app.models import MetadataImport, MetadataImportMode
from app.schemas.schemas import MetadataApplyRead, MetadataImportRead, MetadataPreviewRead
from app.services import metadata_table as mt
from app.services.metadata_import import (
    NothingToApplyError,
    TableOptions,
    apply_import,
    build_preview,
    export_rows,
)
from app.storage.local import sanitize_filename

router = APIRouter(tags=["metadata"])

MAPPING_MAX_CHARS = 200_000


class TableFormat(str, Enum):
    csv = "csv"
    xlsx = "xlsx"


_MEDIA = {
    TableFormat.csv: "text/csv; charset=utf-8",
    TableFormat.xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def table_options(
    sheet: str | None = Form(default=None, min_length=1, max_length=255, description="Worksheet of an .xlsx file"),
    header_row: int | None = Form(default=None, ge=1, le=1_048_576, description="Row that holds the column names"),
    delimiter: str | None = Form(default=None, min_length=1, max_length=1, description="One of , ; TAB |"),
    date_order: Literal["DMY", "MDY"] | None = Form(default=None, description="How to read ambiguous dates"),
    mapping: str | None = Form(
        default=None, max_length=MAPPING_MAX_CHARS,
        description="JSON object {column name: ARVA field | 'custom' | 'ignore'}",
    ),
) -> TableOptions:
    overrides = None
    if mapping:
        try:
            overrides = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"mapping is not valid JSON: {exc}") from exc
        if not isinstance(overrides, dict) or not all(isinstance(v, str) for v in overrides.values()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "mapping must be a JSON object of column name → target")
    return TableOptions(sheet=sheet, header_row=header_row, delimiter=delimiter, date_order=date_order,
                        mapping=overrides)


def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    limit = get_settings().metadata_max_bytes
    try:
        data = upload.file.read(limit + 1)
    finally:
        upload.file.close()
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is larger than {limit:,} bytes, the limit for metadata tables (ARVA_METADATA_MAX_BYTES).",
        )
    name = (upload.filename or "metadata").replace("\\", "/").split("/")[-1][:512] or "metadata"
    return data, name


def _table_error(exc: mt.MetadataImportError) -> HTTPException:
    code = status.HTTP_413_CONTENT_TOO_LARGE if isinstance(exc, mt.MetadataTooLargeError) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(exc))


@router.post("/projects/{project_id}/metadata/preview", response_model=MetadataPreviewRead)
def preview_metadata(
    project_id: str,
    file: UploadFile = File(..., description="CSV, TSV, TXT or .xlsx table with one row per sample"),
    options: TableOptions = Depends(table_options),
    db: Session = Depends(get_db),
):
    """What importing the table would create or change, row by row. Nothing is written."""
    project_or_404(db, project_id)
    data, name = _read_upload(file)
    try:
        return build_preview(db, project_id, data, name, options)
    except mt.MetadataImportError as exc:
        raise _table_error(exc) from exc


@router.post(
    "/projects/{project_id}/metadata/apply", response_model=MetadataApplyRead, status_code=status.HTTP_201_CREATED
)
def apply_metadata(
    project_id: str,
    file: UploadFile = File(...),
    options: TableOptions = Depends(table_options),
    expected_sha256: str = Form(..., pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the previewed file"),
    mode: MetadataImportMode = Form(default=MetadataImportMode.create_and_update),
    db: Session = Depends(get_db),
):
    """Re-run the preview on the server and write it in one transaction; rows with errors are skipped."""
    project_or_404(db, project_id)
    data, name = _read_upload(file)
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This file is not the one that was previewed (its SHA-256 differs). Preview it again before applying.",
        )
    try:
        record, skipped = apply_import(db, project_id, data, name, options, mode)
    except mt.MetadataImportError as exc:
        raise _table_error(exc) from exc
    except NothingToApplyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"record": record, "skipped": skipped}


@router.get("/projects/{project_id}/metadata/imports", response_model=list[MetadataImportRead])
def list_metadata_imports(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    return db.scalars(
        select(MetadataImport).where(MetadataImport.project_id == project_id).order_by(MetadataImport.created_at.desc())
    ).all()


def _download(content: bytes, fmt: TableFormat, filename: str) -> Response:
    return Response(
        content, media_type=_MEDIA[fmt], headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/projects/{project_id}/metadata/export")
def export_metadata(
    project_id: str,
    fmt: TableFormat = Query(default=TableFormat.csv, alias="format"),
    db: Session = Depends(get_db),
):
    """All samples of the project: standard fields, then custom_metadata keys. Cells are formula-injection safe."""
    project = project_or_404(db, project_id)
    rows = export_rows(db, project_id)
    content = mt.export_csv(rows) if fmt is TableFormat.csv else mt.export_xlsx(rows)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # A project name is not a path: keep what comes before a slash.
    name = sanitize_filename(re.sub(r"[\\/]", " ", project.name))
    return _download(content, fmt, f"ARVA_{name}_metadata_{stamp}.{fmt.value}")


@router.get("/metadata/template")
def metadata_template(fmt: TableFormat = Query(default=TableFormat.csv, alias="format")):
    """Header-only table with ARVA's standard column names."""
    content = mt.export_csv([]) if fmt is TableFormat.csv else mt.export_xlsx([])
    return _download(content, fmt, f"ARVA_sample_metadata_template.{fmt.value}")
