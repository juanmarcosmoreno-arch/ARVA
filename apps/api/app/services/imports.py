"""Registration of raw sequencing files against samples."""
from __future__ import annotations

import re
from typing import BinaryIO

from arva_core.formats import SequenceFormat
from arva_core.seqstats import quick_validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import FileFormat, RawFile, Sample
from app.services.capacity import ensure_space
from app.storage import get_storage
from app.storage.local import sanitize_filename

# Illumina-style mate markers: sample_R1_001.fastq.gz, sample_1.fq, sample.R2.fastq
_MATE = re.compile(r"(?:^|[._-])R?([12])(?:[._-]\d{3})?\.(?:fastq|fq)(?:\.gz)?$", re.IGNORECASE)


class DuplicateFileError(ValueError):
    def __init__(self, existing: RawFile):
        self.existing = existing
        super().__init__(
            f"identical content is already registered for this sample as "
            f"'{existing.original_filename}' (sha256 {existing.checksum_sha256[:12]}…)"
        )


def detect_read_mate(filename: str) -> str | None:
    m = _MATE.search(filename)
    return f"R{m.group(1)}" if m else None


def _to_file_format(fmt: SequenceFormat, compressed: bool) -> FileFormat:
    if fmt is SequenceFormat.fastq:
        return FileFormat.fastq_gz if compressed else FileFormat.fastq
    if fmt is SequenceFormat.fasta:
        return FileFormat.fasta_gz if compressed else FileFormat.fasta
    return FileFormat.unknown


def _same_content_elsewhere(db: Session, sample: Sample, sha256: str) -> tuple[str, str] | None:
    """(sample code, filename) of the first file with this content in another sample of the project."""
    row = db.execute(
        select(Sample.sample_code, RawFile.original_filename)
        .join(RawFile, RawFile.sample_id == Sample.id)
        .where(
            Sample.project_id == sample.project_id,
            Sample.id != sample.id,
            RawFile.checksum_sha256 == sha256,
        )
        .order_by(RawFile.uploaded_at)
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def register_raw_file(
    db: Session,
    sample: Sample,
    filename: str,
    stream: BinaryIO,
    *,
    expected_size: int | None = None,
    description: str | None = None,
) -> RawFile:
    """Store a file immutably, checksum it, and record a quick validation."""
    settings = get_settings()
    storage = get_storage()
    if expected_size is not None:
        ensure_space(expected_size)
    file_id = new_uuid()
    safe_name = sanitize_filename(filename)
    rel = f"raw/{sample.project_id}/{sample.id}/{file_id}__{safe_name}"
    stored = storage.save_stream(stream, rel, settings.max_upload_size_bytes)

    duplicate = db.scalar(
        select(RawFile).where(
            RawFile.sample_id == sample.id, RawFile.checksum_sha256 == stored.sha256
        )
    )
    if duplicate is not None:
        storage.resolve(rel).unlink()
        raise DuplicateFileError(duplicate)

    check = quick_validate(storage.resolve(rel))
    message = check.message
    twin = _same_content_elsewhere(db, sample, stored.sha256)
    if twin is not None:
        message += f" Note: identical content is already registered in sample {twin[0]} as {twin[1]}."
    raw = RawFile(
        id=file_id,
        sample_id=sample.id,
        original_filename=filename[:512],
        stored_path=rel,
        file_format=_to_file_format(check.format, check.compressed),
        read_mate=detect_read_mate(filename),
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.sha256,
        is_valid=check.is_valid,
        validation_message=message,
        description=description,
    )
    db.add(raw)
    db.commit()
    db.refresh(raw)
    return raw
