"""Registration of raw sequencing files against samples."""
from __future__ import annotations

import re
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from arva_core.formats import SequenceFormat
from arva_core.seqstats import quick_validate

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import FileFormat, RawFile, Sample
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


def register_raw_file(db: Session, sample: Sample, filename: str, stream: BinaryIO) -> RawFile:
    """Store an uploaded file immutably, checksum it, and record a quick validation."""
    settings = get_settings()
    storage = get_storage()
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
        validation_message=check.message,
    )
    db.add(raw)
    db.commit()
    db.refresh(raw)
    return raw
