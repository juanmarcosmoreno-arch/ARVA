"""Registration of raw sequencing files against samples."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from arva_core.formats import SequenceFormat, check_pod5
from arva_core.header_meta import summarise
from arva_core.seqstats import quick_validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import new_uuid
from app.models import FileFormat, RawFile, Sample
from app.services.capacity import InsufficientStorageError, ensure_space
from app.storage import get_storage
from app.storage.local import FileTooLargeError, sanitize_filename

logger = logging.getLogger(__name__)

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


def mate_pair_key(filename: str) -> str | None:
    """The same for the R1 and R2 file of one pair (the mate digit replaced)."""
    m = _MATE.search(filename)
    return (filename[: m.start(1)] + "#" + filename[m.end(1) :]).lower() if m else None


def header_metadata(headers: list[bytes]) -> dict[str, Any] | None:
    """Summary of the read headers for RawFile.header_metadata; reading headers never fails an import."""
    if not headers:
        return None
    try:
        return json.loads(json.dumps(summarise(headers), allow_nan=False))
    except Exception:
        logger.warning("Read headers could not be summarised; storing no header metadata", exc_info=True)
        return None


def _to_file_format(fmt: SequenceFormat, compressed: bool) -> FileFormat:
    if fmt is SequenceFormat.fastq:
        return FileFormat.fastq_gz if compressed else FileFormat.fastq
    if fmt is SequenceFormat.fasta:
        return FileFormat.fasta_gz if compressed else FileFormat.fasta
    return FileFormat.unknown


def _validate(
    path: Path, filename: str
) -> tuple[FileFormat, str | None, bool, str, dict[str, Any], dict[str, Any] | None]:
    """(format, read mate, is_valid, message, {code, params} of the message, header metadata) from the content."""
    pod5 = check_pod5(path)
    if pod5 is not None:
        return FileFormat.pod5, None, pod5.is_complete, pod5.message, {"code": pod5.code, "params": {}}, None
    check = quick_validate(path)
    return (
        _to_file_format(check.format, check.compressed), detect_read_mate(filename), check.is_valid,
        check.message, {"code": check.code, "params": check.params}, header_metadata(check.headers),
    )


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


def rejection(exc: Exception) -> tuple[str, dict[str, str | int]] | None:
    """The stable code and values of a file the import refused (the interface translates them), or None."""
    if isinstance(exc, DuplicateFileError):
        return "duplicate", {"file": exc.existing.original_filename}
    if isinstance(exc, FileTooLargeError):
        return "too_large", {"limit_bytes": exc.max_bytes}
    if isinstance(exc, InsufficientStorageError):
        return "insufficient_storage", {"needed_bytes": exc.needed_bytes,
                                        "available_bytes": exc.capacity.available_for_data_bytes}
    return None


def _space_check(expected_size: int | None) -> Callable[[int], None]:
    """While streaming, the rest of the file must still fit: other uploads or imports may be writing too."""
    def check(written: int) -> None:
        ensure_space(max(1, (expected_size or 0) - written))
    return check


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
        if expected_size > settings.max_upload_size_bytes:
            raise FileTooLargeError(settings.max_upload_size_bytes)
        ensure_space(expected_size)
    file_id = new_uuid()
    safe_name = sanitize_filename(filename)
    rel = f"raw/{sample.project_id}/{sample.id}/{file_id}__{safe_name}"
    stored = storage.save_stream(stream, rel, settings.max_upload_size_bytes, _space_check(expected_size))

    duplicate = db.scalar(
        select(RawFile).where(
            RawFile.sample_id == sample.id, RawFile.checksum_sha256 == stored.sha256
        )
    )
    if duplicate is not None:
        storage.resolve(rel).unlink()
        raise DuplicateFileError(duplicate)

    file_format, read_mate, is_valid, message, detail, headers = _validate(storage.resolve(rel), filename)
    twin = _same_content_elsewhere(db, sample, stored.sha256)
    if twin is not None:
        message += f" Note: identical content is already registered in sample {twin[0]} as {twin[1]}."
        detail["params"] = {**detail["params"], "twin_sample": twin[0], "twin_file": twin[1]}
    raw = RawFile(
        id=file_id,
        sample_id=sample.id,
        original_filename=filename[:512],
        stored_path=rel,
        file_format=file_format,
        read_mate=read_mate,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.sha256,
        is_valid=is_valid,
        validation_message=message,
        validation_detail=detail,
        description=description,
        header_metadata=headers,
    )
    db.add(raw)
    db.commit()
    db.refresh(raw)
    return raw
