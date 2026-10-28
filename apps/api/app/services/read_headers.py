"""Sample-level view of the read-header metadata stored per file. Suggestions only: nothing here
writes sample metadata."""
from __future__ import annotations

from typing import Any

from arva_core.header_meta import PLATFORMS, combine_suggestions, compare_fingerprints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FileFormat, FileOrigin, RawFile, Sample, SequencingTechnology
from app.services.imports import mate_pair_key

_NOT_USABLE = ("empty", "invalid")


def dominant_format(meta: dict[str, Any] | None) -> str | None:
    counts = {k: v for k, v in ((meta or {}).get("format_counts") or {}).items() if k not in _NOT_USABLE}
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0] if counts else None


def _file_suggestion(meta: dict[str, Any] | None) -> dict[str, Any]:
    return (meta or {}).get("suggested_technology") or {}


def _imported_sequence_files(db: Session, sample: Sample) -> list[RawFile]:
    return list(
        db.scalars(
            select(RawFile)
            .where(
                RawFile.sample_id == sample.id,
                RawFile.origin == FileOrigin.imported,
                RawFile.file_format.not_in([FileFormat.unknown, FileFormat.pod5]),
            )
            .order_by(RawFile.uploaded_at)
        ).all()
    )


def mate_pairs(files: list[RawFile]) -> list[tuple[RawFile, RawFile]]:
    """R1/R2 files paired by file name; a lone R1 and a lone R2 are paired with each other."""
    r1 = [f for f in files if f.read_mate == "R1"]
    r2 = [f for f in files if f.read_mate == "R2"]
    by_key: dict[str | None, RawFile] = {}
    for f in r2:
        by_key.setdefault(mate_pair_key(f.original_filename), f)
    pairs = []
    for f in r1:
        partner = by_key.pop(mate_pair_key(f.original_filename), None)
        if partner is not None:
            pairs.append((f, partner))
    if not pairs and len(r1) == 1 and len(r2) == 1:
        pairs = [(r1[0], r2[0])]
    return pairs


def mate_check(r1: RawFile, r2: RawFile) -> dict[str, Any]:
    out: dict[str, Any] = {"r1_file_id": r1.id, "r2_file_id": r2.id, "looks_like_pair": None, "matched": 0, "compared": 0}
    fp1 = (r1.header_metadata or {}).get("mate_fingerprint")
    fp2 = (r2.header_metadata or {}).get("mate_fingerprint")
    if fp1 is None or fp2 is None:
        return {**out, "note": "not_analysed"}
    c = compare_fingerprints(fp1, fp2)
    if c.get("error") or not c["pairs_compared"]:
        return {**out, "note": "nothing_compared"}
    out.update(looks_like_pair=c["looks_like_pair"], matched=c["base_name_matches"], compared=c["pairs_compared"])
    if c["looks_like_pair"]:
        return {**out, "note": "same_read_names"}
    if c["r1_mates"].get("2") or c["r2_mates"].get("1"):
        return {**out, "note": "mate_markers_conflict"}
    return {**out, "note": "different_read_names"}


def build_header_summary(db: Session, sample: Sample) -> dict[str, Any]:
    files = _imported_sequence_files(db, sample)
    analysed = [f for f in files if f.header_metadata is not None]
    suggestion = combine_suggestions([_file_suggestion(f.header_metadata) for f in analysed])
    user = sample.sequencing_technology
    agrees = None
    if suggestion["value"] is not None and user is not SequencingTechnology.unknown:
        partial = suggestion["files_with_evidence"] < suggestion["files_considered"]
        # Files without evidence may hold the other half of a hybrid sample: no contradiction.
        undecided = partial and user is SequencingTechnology.hybrid and suggestion["value"] in PLATFORMS
        agrees = None if undecided else suggestion["value"] == user.value
    per_file = []
    for f in files:
        s = _file_suggestion(f.header_metadata)
        per_file.append(
            {
                "file_id": f.id,
                "name": f.original_filename,
                "analysed": f.header_metadata is not None,
                "platform": s.get("value") if s.get("value") in PLATFORMS else None,
                "confidence": s.get("confidence") or "none",
                "format": dominant_format(f.header_metadata),
            }
        )
    return {
        "suggested_technology": {k: suggestion[k] for k in (
            "value", "confidence", "basis", "platforms", "files_considered", "files_with_evidence")},
        "per_file": per_file,
        "mate_check": [mate_check(a, b) for a, b in mate_pairs(files)],
        "user_technology": user.value,
        "agrees": agrees,
    }
