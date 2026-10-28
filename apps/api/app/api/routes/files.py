from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import raw_file_or_404, sample_or_404
from app.db.session import get_db
from app.models import RawFile
from app.schemas.schemas import RawFileRead, UploadRejection, UploadResult
from app.services.capacity import InsufficientStorageError
from app.services.imports import DuplicateFileError, register_raw_file
from app.storage import get_storage
from app.storage.local import FileTooLargeError

router = APIRouter(tags=["files"])

_REJECTION_CODES = {
    DuplicateFileError: "duplicate",
    FileTooLargeError: "too_large",
    InsufficientStorageError: "insufficient_storage",
}


@router.post(
    "/samples/{sample_id}/files", response_model=UploadResult, status_code=status.HTTP_201_CREATED
)
def upload_files(
    sample_id: str,
    files: list[UploadFile] = File(..., description="FASTQ/FASTA files, optionally gzip-compressed"),
    db: Session = Depends(get_db),
):
    sample = sample_or_404(db, sample_id)
    stored: list[RawFile] = []
    rejected: list[UploadRejection] = []
    for upload in files:
        name = upload.filename or "upload"
        try:
            # Re-checked per file: the spooled request body may live on another filesystem.
            stored.append(register_raw_file(db, sample, name, upload.file, expected_size=upload.size))
        except (DuplicateFileError, FileTooLargeError, InsufficientStorageError) as exc:
            rejected.append(UploadRejection(filename=name, reason=str(exc), code=_REJECTION_CODES[type(exc)]))
        finally:
            upload.file.close()
    return UploadResult(
        files=[RawFileRead.model_validate(f) for f in stored], rejected=rejected
    )


@router.get("/samples/{sample_id}/files", response_model=list[RawFileRead])
def list_files(sample_id: str, db: Session = Depends(get_db)):
    sample_or_404(db, sample_id)
    return db.scalars(
        select(RawFile).where(RawFile.sample_id == sample_id).order_by(RawFile.uploaded_at)
    ).all()


@router.get("/files/{file_id}", response_model=RawFileRead)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return raw_file_or_404(db, file_id)


@router.get("/files/{file_id}/download")
def download_file(file_id: str, db: Session = Depends(get_db)):
    raw = raw_file_or_404(db, file_id)
    return FileResponse(
        get_storage().resolve(raw.stored_path),
        filename=raw.original_filename,
        media_type="application/octet-stream",
    )
