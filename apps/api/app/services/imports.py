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
from app.db.base import new_uuid, utcnow
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


# Reads longer than this are long reads (short_hybrid.SHORT_READ_MAX_LENGTH: short reads are at most 1,000 bp).
LONG_READ_MIN_LENGTH = 1_000
_LONG_PLATFORMS = ("nanopore", "pacbio")
_CONFIDENT = ("high", "medium")


def detect_read_mate(filename: str) -> str | None:
    m = _MATE.search(filename)
    return f"R{m.group(1)}" if m else None


def mate_from_content(name_mate: str | None, max_length: int, headers: dict[str, Any] | None) -> tuple[str | None,
                                                                                                      dict | None]:
    """The mate a file is registered as: the one its name gives (R1/R2), unless its content shows long reads (a read
    longer than LONG_READ_MIN_LENGTH among the first records checked, or headers that identify Oxford Nanopore or
    PacBio): paired-end mates are short reads, and ENA names a run's single FASTQ <run>_1.fastq.gz. Returns the mate
    and, when the name's mate was not used, why."""
    if name_mate is None:
        return None, None
    suggestion = (headers or {}).get("suggested_technology") or {}
    platform = suggestion.get("value") if suggestion.get("confidence") in _CONFIDENT else None
    if max_length > LONG_READ_MIN_LENGTH or platform in _LONG_PLATFORMS:
        reason = "long_reads" if max_length > LONG_READ_MIN_LENGTH else "long_read_headers"
        return None, {"from_name": name_mate, "set_by": "content", "reason": reason, "max_length": max_length,
                      "platform": platform}
    return name_mate, None


def mate_pair_key(filename: str) -> str | None:
    """The same for the R1 and R2 file of one pair (the mate digit replaced)."""
    m = _MATE.search(filename)
    return (filename[: m.start(1)] + "#" + filename[m.end(1) :]).lower() if m else None


def lone_mates(files: list[RawFile]) -> set[str]:
    """The ids of files marked R1 or R2 whose other mate is not among `files` (the same file name with the other
    mate digit, or the other output of the job that wrote it). A lone mate is not half of a pair: a single long-read
    FASTQ that ENA names <run>_1.fastq.gz, imported before ARVA read its content, is one."""
    out = set()
    for f in files:
        if f.read_mate not in ("R1", "R2"):
            continue
        other = "R2" if f.read_mate == "R1" else "R1"
        key = mate_pair_key(f.original_filename)
        if not any(g.id != f.id and g.read_mate == other
                   and ((key is not None and mate_pair_key(g.original_filename) == key)
                        or (f.produced_by_job_id is not None and g.produced_by_job_id == f.produced_by_job_id))
                   for g in files):
            out.add(f.id)
    return out


def sample_lone_mates(db: Session, sample_ids: set[str]) -> tuple[set[str], dict[str, int]]:
    """The lone mates of the samples' files, and how many FASTQ files each sample has."""
    rows = list(db.scalars(select(RawFile).where(RawFile.sample_id.in_(sample_ids)))) if sample_ids else []
    fastq: dict[str, int] = {}
    for f in rows:
        if f.file_format in (FileFormat.fastq, FileFormat.fastq_gz):
            fastq[f.sample_id] = fastq.get(f.sample_id, 0) + 1
    return lone_mates(rows), fastq


def not_a_mate(lone: bool, sample_fastq_files: int, max_length: int | None, platform: str | None,
               confidence: str | None) -> bool:
    """Whether a file marked R1 or R2 by its name is not half of a pair: it is a lone mate (no file of the sample is
    its other half) and either the sample has no other FASTQ file or the file holds long reads (ARVA's statistics or
    confident read headers)."""
    if not lone:
        return False
    long_reads = (max_length is not None and max_length > LONG_READ_MIN_LENGTH) or \
        (platform in _LONG_PLATFORMS and confidence in _CONFIDENT)
    return sample_fastq_files <= 1 or long_reads


def set_read_mate(db: Session, f: RawFile, mate: str | None) -> RawFile:
    """Correct a file's mate role (R1, R2 or none: not part of a pair), keeping what it was and when it changed."""
    detail = dict(f.validation_detail or {})
    note = dict(detail.get("mate") or {})
    note.update({"from_name": note.get("from_name", detect_read_mate(f.original_filename)), "set_by": "user",
                 "previous": f.read_mate, "reason": "user", "at": utcnow().isoformat()})
    detail["mate"] = note
    f.read_mate = mate
    f.validation_detail = detail
    db.commit()
    db.refresh(f)
    return f


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
    headers = header_metadata(check.headers)
    detail: dict[str, Any] = {"code": check.code, "params": check.params}
    mate, note = mate_from_content(detect_read_mate(filename), check.max_length, headers)
    if note is not None:
        detail["mate"] = note
    return (
        _to_file_format(check.format, check.compressed), mate, check.is_valid, check.message, detail, headers,
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
