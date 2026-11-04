"""Sanger reads of one gene: import (.ab1, FASTA, .seq), forward/reverse pairing, trimming and consensus with their
evidence, the identification searches against local sources and ARVA's reading of their hits.

The science is in arva_core.sanger (docs/sanger-design-notes.md). Here:

* Where the data live (app.models.sanger): reads and identifications belong to a sample, the strain the gene was
  amplified from. The uploaded files are kept in raw/ untouched, like every upload. When the same sample has a genome
  in ARVA, the consensus is searched against it as one more source ("genomes"), next to any other genome the user
  chooses, so the Sanger result and the genome's are shown together.
* Pairing (ARVA's heuristic, always shown and changeable): a read's direction is taken from the end of its name
  ("-F", "_R", "784F", "Forward"...), then a primer name before it ("_784"), and what is left is the pair key. Two
  prefixes Macrogen adds are not part of the key: a leading block of 8 hexadecimal characters and a hyphen on the
  file names ("0a1b2c3d-S1_27F-F.ab1", a synthetic example), and the order number and well of the FASTA header of
  its .txt files ("H000000-000_A01_S1_27F-F.ab1"), whose ".ab1" ending is dropped as well. Reads of one sample with
  the same key, one forward and one reverse, are proposed as a pair; when a key has several reads of one direction
  and only one of them has qualities (the chromatogram), that one is proposed.
* Sources, one analysis job each, so that every database is recorded with record_use and the Database Manager sees
  it in use: NCBI 16S (registered or downloaded), ABRicate's bundled VFDB and mlst's bundled PubMLST alleles (blastn),
  AMRFinderPlus (translated nucleotide search), spaTyper with the user's Ridom files, a reference genome collection
  and genomes in ARVA with their annotation (blastn against the contigs, hits named by the annotated features they
  overlap). Nothing is sent outside this computer.
"""
from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from arva_core import sanger as core
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.messages import render
from app.db.base import new_uuid
from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    JobStatus,
    ReferenceDatabase,
    Sample,
    SangerIdentification,
    SangerRead,
    SangerSearchResult,
    SpeciesResult,
)
from app.storage import get_storage
from app.storage.local import sanitize_filename

SANGER_JOB = "sanger_identification"
ACTIVE = (JobStatus.pending, JobStatus.running)
FORMATS = ("abi", "fasta", "seq")
ABI_SUFFIXES = (".ab1", ".abi")
TEXT_SUFFIXES = (".fasta", ".fa", ".fas", ".fna", ".seq", ".txt")
ABIF_MAGIC = b"ABIF"
# ARVA's bounds: an .ab1 file is a few hundred kB (real 3730xl reads are about 0.3 MB); a text file of reads stays small.
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
# Biopython keeps every tag of an .ab1 decoded in memory (a tuple of Python integers per trace, many times the bytes
# they come from), so chromatograms are bounded tighter: real 3730xl reads are about 0.3 MB, Biopython's 0.2 MB.
MAX_ABI_BYTES = 5 * 1024 * 1024
MAX_FILES = 100
MAX_RECORDS = 200
MAX_READ_LENGTH = 20_000
# The searched sequence: long enough for BLAST statistics to mean something (as Custom Gene Investigation), short
# enough for one gene or amplicon.
QUERY_LENGTH = (30, 50_000)
DIRECTIONS = ("forward", "reverse", "unknown")
SUSPECTED_KINDS = ("gene", "species")

# Direction words at the end of a read name, and a primer name before them (ARVA's pairing heuristic).
_ORDER_PREFIX = re.compile(r"^[0-9a-f]{8}-")
_MACROGEN_TEXT_PREFIX = re.compile(r"^H\d{6}-\d{3}_[A-P]\d{2}_")
_DIRECTION_WORD = re.compile(r"[-_. ](F|R|FW|RV|FWD|REV|FORWARD|REVERSE)$", re.I)
_PRIMER_WITH_LETTER = re.compile(r"[-_. ]([A-Za-z]{0,10}\d+[A-Za-z]{0,3}?)(F|R)$")
_PRIMER = re.compile(r"[-_. ]([A-Za-z]{0,10}\d+[A-Za-z]{0,3})$")
_WORD_DIRECTION = {"f": "forward", "fw": "forward", "fwd": "forward", "forward": "forward",
                   "r": "reverse", "rv": "reverse", "rev": "reverse", "reverse": "reverse"}

MESSAGES = {
    "sanger_too_many_files": "Upload at most {max} files at a time.",
    "sanger_file_too_large": "{file} is larger than {max} bytes, more than a Sanger read file holds.",
    "sanger_file_empty": "{file} is empty.",
    "sanger_unknown_format": "{file} is not a chromatogram (.ab1) or a FASTA or .seq text file.",
    "sanger_unreadable": "{file} cannot be read: {detail}",
    "sanger_duplicate": "{file} was already imported into this sample (same content).",
    "sanger_no_space": "{file} was not stored: there is not enough free space for it.",
    "sanger_too_many_records": "{file} holds more than {max} sequences.",
    "sanger_read_too_long": "{file}: the read {name} has {length} bases, more than {max}.",
    "sanger_read_missing": "The read does not exist or belongs to another sample.",
    "sanger_read_in_use": "The read is used by {count, plural, one {# identification} other {# identifications}}; "
                          "delete {count, plural, one {it} other {them}} first.",
    "sanger_direction_invalid": "The direction must be forward, reverse or unknown.",
    "sanger_reads_needed": "Choose one read, or a forward and a reverse read.",
    "sanger_same_read": "The forward and the reverse read must be two different reads.",
    "sanger_trim_invalid": "Trimming: {detail}",
    "sanger_consensus_invalid": "Consensus settings: {detail}",
    "sanger_no_overlap": "The two reads do not overlap enough ({columns} columns at {identity} % identity; at least "
                         "{min_overlap} columns at {min_identity} % are needed). Check that they are the same "
                         "amplicon, or identify each read on its own.",
    "sanger_query_length": "The sequence to search has {length} bases after trimming; it needs {min} to {max}.",
    "sanger_read_nothing_kept": "Nothing of the read {read} is kept after trimming: no base scores above the limit "
                                "(a failed read, or a limit too strict). Look at its chromatogram, lower the limit or "
                                "set a manual range, or identify {other} on its own.",
    "sanger_single_nothing_kept": "Nothing of the read {read} is kept after trimming: no base scores above the limit "
                                  "(a failed read, or a limit too strict). Look at its chromatogram, lower the limit "
                                  "or set a manual range.",
    "sanger_suspected_invalid": "Say whether you suspect a gene or a species, and which.",
    "sanger_identification_busy": "A search of this identification is still queued or running; wait for it or "
                                  "cancel it first.",
    "sanger_source_unknown": "Unknown source: {source}.",
    "sanger_sources_needed": "Choose at least one source to search.",
    "sanger_database_invalid": "The chosen database is not a usable {kind} database.",
    "sanger_genomes_invalid": "Choose genomes ARVA holds (at most {max}).",
    "sanger_search_blocked": "These sources cannot be searched here: {problems}",
    "sanger_confirm": "Confirm the summary of the search first.",
    "sanger_no_trace": "This read has no chromatogram.",
    "sanger_trace_window": "Trace window: {detail}",
}


class InputError(ValueError):
    """The request cannot be done as asked (HTTP 400); `code` and `params` name it for the interface."""

    def __init__(self, code: str, **params: Any):
        super().__init__(render(MESSAGES[code], params))
        self.code = code
        self.params = params


# --- Names, directions and pairs ----------------------------------------------------------------------------------

def parse_read_name(filename_or_name: str) -> dict[str, Any]:
    """Direction, primer and pair key from a read's name (ARVA's heuristic; the module docstring)."""
    name = filename_or_name
    for suffix in (*ABI_SUFFIXES, *TEXT_SUFFIXES):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    base = _ORDER_PREFIX.sub("", _MACROGEN_TEXT_PREFIX.sub("", name))
    direction, primer, rest = "unknown", None, base
    if m := _DIRECTION_WORD.search(rest):
        direction, rest = _WORD_DIRECTION[m.group(1).lower()], rest[: m.start()]
        if p := _PRIMER.search(rest):
            primer, rest = p.group(1), rest[: p.start()]
    elif m := _PRIMER_WITH_LETTER.search(rest):
        direction = _WORD_DIRECTION[m.group(2).lower()]
        primer, rest = m.group(1) + m.group(2), rest[: m.start()]
    key = rest.strip("-_. ") or None
    return {"direction": direction, "primer": primer, "pair_key": key if direction != "unknown" else None}


def _charted(group: list[SangerRead]) -> list[SangerRead]:
    with_qualities = [r for r in group if r.has_qualities]
    return with_qualities if len(group) > 1 and len(with_qualities) == 1 else group


def proposed_pairs(reads: list[SangerRead]) -> list[dict[str, Any]]:
    """Reads with the same pair key, exactly one forward and one reverse, as proposed pairs; keys with more reads
    are listed as ambiguous (the user chooses)."""
    by_key: dict[str, list[SangerRead]] = {}
    for r in reads:
        if r.pair_key and r.direction in ("forward", "reverse"):
            by_key.setdefault(r.pair_key, []).append(r)
    out = []
    for key, group in sorted(by_key.items()):
        fwd = [r for r in group if r.direction == "forward"]
        rev = [r for r in group if r.direction == "reverse"]
        # A Macrogen .txt uploaded next to its .ab1 gives a second read of that direction without qualities: of
        # several reads of one direction, the only one with qualities is proposed.
        fwd, rev = (_charted(group) for group in (fwd, rev))
        if len(fwd) == 1 and len(rev) == 1:
            out.append({"pair_key": key, "status": "proposed", "forward_read_id": fwd[0].id,
                        "reverse_read_id": rev[0].id})
        elif fwd and rev:
            out.append({"pair_key": key, "status": "ambiguous", "forward_read_ids": [r.id for r in fwd],
                        "reverse_read_ids": [r.id for r in rev]})
    return out


# --- Import ---------------------------------------------------------------------------------------------------

def _format_of(filename: str, data: bytes) -> str | None:
    lower = filename.lower()
    if data[:4] == ABIF_MAGIC:
        return "abi"
    if lower.endswith(ABI_SUFFIXES):
        return "abi"
    if lower.endswith(TEXT_SUFFIXES) or not lower.rpartition(".")[1]:
        return "text"
    return None


def _parse_upload(filename: str, data: bytes) -> list[core.SangerRead]:
    kind = _format_of(filename, data)
    if kind is None:
        raise InputError("sanger_unknown_format", file=filename)
    if kind == "abi":
        if len(data) > MAX_ABI_BYTES:
            raise InputError("sanger_file_too_large", file=filename, max=MAX_ABI_BYTES)
        try:
            return [core.read_abi(data, name=parse_name(filename))]
        except ValueError as exc:
            raise InputError("sanger_unreadable", file=filename, detail=str(exc)) from None
    if len(data) > MAX_TEXT_BYTES:
        raise InputError("sanger_file_too_large", file=filename, max=MAX_TEXT_BYTES)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("sanger_unknown_format", file=filename) from None
    try:
        reads = core.parse_sequence_text(text, parse_name(filename))
    except ValueError as exc:
        raise InputError("sanger_unreadable", file=filename, detail=str(exc)) from None
    if len(reads) > MAX_RECORDS:
        raise InputError("sanger_too_many_records", file=filename, max=MAX_RECORDS)
    return reads


def parse_name(filename: str) -> str:
    name = filename.replace("\\", "/").split("/")[-1]
    for suffix in (*ABI_SUFFIXES, *TEXT_SUFFIXES):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)] or name
    return name


def _summary(read: core.SangerRead) -> dict[str, Any]:
    out = read.summary()
    out.pop("trim", None)
    if read.has_qualities:
        trim = core.mott_trim(read.qualities, core.DEFAULT_TRIM_LIMIT)
        out["default_trim"] = {k: trim[k] for k in ("limit", "start", "end", "length", "mean_quality",
                                                     "q20_percent")}
    else:
        out["default_trim"] = None
    return out


def import_files(db: Session, sample: Sample,
                 uploads: list[tuple[str, bytes | Callable[[], bytes]]]) -> dict[str, Any]:
    """Check, store and record every uploaded file; a file that cannot be read, is too large or was already imported
    (into this sample, or earlier in the same upload) is reported with its reason and the others go on. Each upload
    is a file name with its bytes, or with a function that reads them, so that the route holds one file in memory
    at a time. Returns the new reads, the skipped files and the proposed pairs."""
    if len(uploads) > MAX_FILES:
        raise InputError("sanger_too_many_files", max=MAX_FILES)
    from app.services.capacity import InsufficientStorageError, ensure_space

    storage = get_storage()
    limit = max_upload_bytes()
    imported: list[SangerRead] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for filename, content in uploads:
        shown = filename.replace("\\", "/").split("/")[-1][:512] or "read"
        data = content() if callable(content) else content
        try:
            if not data:
                raise InputError("sanger_file_empty", file=shown)
            if len(data) > limit:
                raise InputError("sanger_file_too_large", file=shown, max=limit)
            reads = _parse_upload(shown, data)
            for r in reads:
                if len(r) > MAX_READ_LENGTH:
                    raise InputError("sanger_read_too_long", file=shown, name=r.name, length=len(r),
                                     max=MAX_READ_LENGTH)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen or db.scalar(select(SangerRead.id).where(SangerRead.sample_id == sample.id,
                                                                       SangerRead.sha256 == digest)):
                raise InputError("sanger_duplicate", file=shown)
        except InputError as exc:
            skipped.append({"file": shown, "code": exc.code, "params": exc.params, "detail": str(exc)})
            continue
        try:
            ensure_space(len(data))
        except InsufficientStorageError:
            skipped.append({"file": shown, "code": "sanger_no_space", "params": {"file": shown},
                            "detail": render(MESSAGES["sanger_no_space"], {"file": shown})})
            continue
        seen.add(digest)
        rel = f"raw/{sample.project_id}/{sample.id}/sanger/{new_uuid()}__{sanitize_filename(shown)}"
        stored = storage.save_stream(io.BytesIO(data), rel, limit)
        fmt = reads[0].source_format
        for i, r in enumerate(reads):
            # A FASTA header may carry the chromatogram's file name (Macrogen's .txt: "...-F.ab1").
            name = parse_name(shown) if fmt == "abi" else parse_name(r.name)
            parsed = parse_read_name(name)
            row = SangerRead(
                sample_id=sample.id, name=name[:255], original_filename=shown, file_format=fmt, record_index=i,
                storage_path=stored.relative_path, sha256=stored.sha256, size_bytes=stored.size_bytes,
                direction=parsed["direction"], direction_source="name" if parsed["direction"] != "unknown" else "none",
                pair_key=parsed["pair_key"], primer=parsed["primer"], length=len(r), has_qualities=r.has_qualities,
                has_trace=r.has_trace, summary=_summary(r))
            db.add(row)
            imported.append(row)
    db.commit()
    for r in imported:
        db.refresh(r)
    reads = list(db.scalars(select(SangerRead).where(SangerRead.sample_id == sample.id)))
    return {"imported": [read_view(db, r) for r in imported], "skipped": skipped, "pairs": proposed_pairs(reads)}


def load(read: SangerRead) -> core.SangerRead:
    """The read as arva_core sees it, parsed again from its stored file."""
    path = get_storage().resolve(read.storage_path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != read.sha256:
        raise InputError("sanger_unreadable", file=read.original_filename, detail="the stored file changed")
    reads = _parse_upload(read.original_filename, data)
    out = reads[read.record_index]
    out.name = read.name
    return out


def read_view(db: Session, r: SangerRead) -> dict[str, Any]:
    used = db.scalar(select(func.count()).select_from(SangerIdentification).where(
        (SangerIdentification.forward_read_id == r.id) | (SangerIdentification.reverse_read_id == r.id))) or 0
    return {"id": r.id, "sample_id": r.sample_id, "name": r.name, "original_filename": r.original_filename,
            "file_format": r.file_format, "record_index": r.record_index, "sha256": r.sha256,
            "size_bytes": r.size_bytes, "direction": r.direction, "direction_source": r.direction_source,
            "pair_key": r.pair_key, "primer": r.primer, "length": r.length, "has_qualities": r.has_qualities,
            "has_trace": r.has_trace, "summary": r.summary, "created_at": r.created_at, "used_by": used}


def sample_overview(db: Session, sample: Sample) -> dict[str, Any]:
    reads = list(db.scalars(select(SangerRead).where(SangerRead.sample_id == sample.id)
                            .order_by(SangerRead.created_at, SangerRead.name)))
    idents = list(db.scalars(select(SangerIdentification).where(SangerIdentification.sample_id == sample.id)
                             .order_by(SangerIdentification.created_at.desc())))
    # A text read (Macrogen's .txt) of the same pair key and direction as a chromatogram is a copy of its base calls
    # without qualities: the interface says to use the .ab1.
    charted = {(r.pair_key, r.direction) for r in reads if r.has_qualities and r.pair_key}
    views = [{**read_view(db, r), "chromatogram_twin": not r.has_qualities and (r.pair_key, r.direction) in charted}
             for r in reads]
    return {"sample_id": sample.id, "reads": views, "pairs": proposed_pairs(reads),
            "identifications": [identification_brief(db, i) for i in idents],
            "genomes": [_assembly_brief(db, a) for a in _sample_assemblies(db, sample.id)]}


def update_read(db: Session, read: SangerRead, direction: str | None, pair_key: str | None,
                name: str | None) -> SangerRead:
    """The user's own direction, pair key or name for a read (the name-derived ones are only proposals)."""
    if direction is not None:
        if direction not in DIRECTIONS:
            raise InputError("sanger_direction_invalid")
        read.direction, read.direction_source = direction, "user"
    if pair_key is not None:
        read.pair_key = " ".join(pair_key.split())[:255] or None
        read.direction_source = "user"
    if name is not None and " ".join(name.split()):
        read.name = " ".join(name.split())[:255]
    db.commit()
    db.refresh(read)
    return read


def delete_read(db: Session, read: SangerRead) -> None:
    used = db.scalar(select(func.count()).select_from(SangerIdentification).where(
        (SangerIdentification.forward_read_id == read.id) | (SangerIdentification.reverse_read_id == read.id))) or 0
    if used:
        raise InputError("sanger_read_in_use", count=used)
    db.delete(read)
    db.commit()


# --- Quality: trimming, chromatogram, mixed peaks ---------------------------------------------------------------

def _trim(read: core.SangerRead, settings: dict[str, Any] | None) -> core.SangerRead:
    s = settings or {}
    manual = None
    if s.get("manual_start") is not None or s.get("manual_end") is not None:
        manual = (int(s.get("manual_start") or 0), int(s.get("manual_end") or 0))
    try:
        return core.trim_read(read, float(s.get("limit", core.DEFAULT_TRIM_LIMIT)), manual)
    except ValueError as exc:
        raise InputError("sanger_trim_invalid", detail=str(exc)) from None


def trim_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    s = settings or {}
    return {"limit": float(s.get("limit", core.DEFAULT_TRIM_LIMIT)), "manual_start": s.get("manual_start"),
            "manual_end": s.get("manual_end")}


def read_detail(db: Session, r: SangerRead, trim: dict[str, Any] | None, mixed_ratio: float) -> dict[str, Any]:
    """A read's bases and qualities, the kept region at the given trimming and the bases to review."""
    read = load(r)
    trimmed = _trim(read, trim)
    try:
        mixed = core.mixed_peaks(read, mixed_ratio)
    except ValueError as exc:
        raise InputError("sanger_trim_invalid", detail=str(exc)) from None
    lo, hi = (trimmed.trim or {}).get("start"), (trimmed.trim or {}).get("end")
    for m in mixed:
        m["kept"] = lo is not None and lo <= m["position"] <= hi
    return {**read_view(db, r), "bases": read.bases, "qualities": read.qualities if read.has_qualities else None,
            "trim": trimmed.trim, "trim_source": core.SOURCES["trim"], "kept_bases": trimmed.bases,
            "mixed_peaks": mixed, "mixed_ratio": mixed_ratio, "mixed_source": core.SOURCES["mixed_peaks"],
            "warnings": trimmed.warnings}


def trace(r: SangerRead, scan_start: int, scan_end: int | None, max_points: int) -> dict[str, Any]:
    read = load(r)
    if not read.has_trace:
        raise InputError("sanger_no_trace")
    try:
        return core.trace_view(read, scan_start, scan_end, max_points)
    except ValueError as exc:
        raise InputError("sanger_trace_window", detail=str(exc)) from None


# --- Consensus and identifications ------------------------------------------------------------------------------

def consensus_params(values: dict[str, Any] | None) -> core.ConsensusParams:
    names = {f.name for f in fields(core.ConsensusParams)}
    p = core.ConsensusParams(**{k: v for k, v in (values or {}).items() if k in names and v is not None})
    try:
        p.validate()
    except ValueError as exc:
        raise InputError("sanger_consensus_invalid", detail=str(exc)) from None
    return p


def _reads_of(db: Session, sample: Sample, forward_id: str | None, reverse_id: str | None) -> tuple[
        SangerRead | None, SangerRead | None]:
    if not forward_id and not reverse_id:
        raise InputError("sanger_reads_needed")
    if forward_id and forward_id == reverse_id:
        raise InputError("sanger_same_read")
    out = []
    for rid in (forward_id, reverse_id):
        if rid is None:
            out.append(None)
            continue
        r = db.get(SangerRead, rid)
        if r is None or r.sample_id != sample.id:
            raise InputError("sanger_read_missing")
        out.append(r)
    return out[0], out[1]


def build(db: Session, sample: Sample, forward_id: str | None, reverse_id: str | None,
          forward_trim: dict[str, Any] | None, reverse_trim: dict[str, Any] | None,
          params: dict[str, Any] | None, mixed_ratio: float = core.DEFAULT_MIXED_RATIO) -> dict[str, Any]:
    """What an identification would search: the trimmed read, or the forward + reverse consensus with every
    column's evidence, every conflict and the bases to review in each read."""
    fwd, rev = _reads_of(db, sample, forward_id, reverse_id)
    p = consensus_params(params)
    settings = {"forward_trim": trim_settings(forward_trim) if fwd else None,
                "reverse_trim": trim_settings(reverse_trim) if rev else None, "consensus": p.as_dict(),
                "mixed_ratio": mixed_ratio}
    if fwd is not None and rev is not None:
        f, r = _trim(load(fwd), forward_trim), _trim(load(rev), reverse_trim)
        for empty, other in ((f, rev), (r, fwd)):
            if not len(empty):
                raise InputError("sanger_read_nothing_kept", read=(fwd if empty is f else rev).name,
                                 other=other.name)
        result = core.consensus(f, r, p)
        result["mixed_peaks"] = {"forward": _mixed(f, mixed_ratio), "reverse": _mixed(r, mixed_ratio)}
        mode, sequence = "pair", result["sequence"]
    else:
        one = fwd or rev
        t = _trim(load(one), forward_trim if fwd else reverse_trim)
        if not len(t):
            raise InputError("sanger_single_nothing_kept", read=one.name)
        # A reverse read alone is searched and exported reverse-complemented, on the forward read's strand, as in a
        # consensus (BLAST searches both strands either way). Mixed peaks keep the read's own positions.
        searched = core.reverse_complement(t) if rev and not fwd else t
        result = {"status": "single", "role": "forward" if fwd else "reverse", "read": t.summary(),
                  "reverse_complemented": searched is not t, "sequence": searched.bases, "length": len(t),
                  "mixed_peaks": {("forward" if fwd else "reverse"): _mixed(t, mixed_ratio)},
                  "warnings": [*t.warnings, {"code": "single_read", "params": {}}], "counts": {}, "conflicts": [],
                  "columns": []}
        mode, sequence = "single", searched.bases
    result["mixed_source"] = core.SOURCES["mixed_peaks"]
    return {"mode": mode, "settings": settings, "result": result, "sequence": sequence,
            "forward_read_id": fwd.id if fwd else None, "reverse_read_id": rev.id if rev else None}


def _mixed(read: core.SangerRead, ratio: float) -> list[dict[str, Any]]:
    try:
        return core.mixed_peaks(read, ratio)
    except ValueError as exc:
        raise InputError("sanger_trim_invalid", detail=str(exc)) from None


def _suspected(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value or not str(value.get("value") or "").strip():
        return None
    if value.get("kind") not in SUSPECTED_KINDS:
        raise InputError("sanger_suspected_invalid")
    return {"kind": value["kind"], "value": " ".join(str(value["value"]).split())[:200]}


def create_identification(db: Session, sample: Sample, label: str | None, forward_id: str | None,
                          reverse_id: str | None, forward_trim: dict[str, Any] | None,
                          reverse_trim: dict[str, Any] | None, params: dict[str, Any] | None, mixed_ratio: float,
                          suspected: dict[str, Any] | None, notes: str | None) -> SangerIdentification:
    b = build(db, sample, forward_id, reverse_id, forward_trim, reverse_trim, params, mixed_ratio)
    res = b["result"]
    if res["status"] == "no_overlap":
        w = next(x for x in res["warnings"] if x["code"] == "no_overlap")["params"]
        raise InputError("sanger_no_overlap", **w)
    seq = b["sequence"]
    if not QUERY_LENGTH[0] <= len(seq) <= QUERY_LENGTH[1]:
        raise InputError("sanger_query_length", length=len(seq), min=QUERY_LENGTH[0], max=QUERY_LENGTH[1])
    reads = [db.get(SangerRead, i) for i in (b["forward_read_id"], b["reverse_read_id"]) if i]
    default_label = " + ".join(r.name for r in reads)
    ident = SangerIdentification(
        sample_id=sample.id, label=(" ".join((label or "").split()) or default_label)[:255],
        forward_read_id=b["forward_read_id"], reverse_read_id=b["reverse_read_id"], mode=b["mode"],
        settings=b["settings"], sequence=seq, length=len(seq), sha256=hashlib.sha256(seq.encode()).hexdigest(),
        consensus=res, suspected=_suspected(suspected), notes=notes)
    db.add(ident)
    db.commit()
    db.refresh(ident)
    return ident


def set_suspected(db: Session, ident: SangerIdentification, suspected: dict[str, Any] | None,
                  notes: str | None, label: str | None) -> SangerIdentification:
    ident.suspected = _suspected(suspected)
    if notes is not None:
        ident.notes = notes or None
    if label is not None and " ".join(label.split()):
        ident.label = " ".join(label.split())[:255]
    db.commit()
    db.refresh(ident)
    return ident


def jobs_of(db: Session, ident: SangerIdentification) -> list[AnalysisJob]:
    rows = db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == ident.sample_id,
                                                AnalysisJob.job_type == SANGER_JOB)
                      .order_by(AnalysisJob.created_at))
    return [j for j in rows if (j.parameters or {}).get("identification_id") == ident.id]


def delete_identification(db: Session, ident: SangerIdentification) -> None:
    """The identification and its search results; the search jobs stay in the job ledger."""
    if any(j.status in ACTIVE for j in jobs_of(db, ident)):
        raise InputError("sanger_identification_busy")
    db.delete(ident)
    db.commit()


def consensus_fasta(ident: SangerIdentification) -> str:
    seq = ident.sequence
    header = f">{sanitize_filename(ident.label)} {ident.mode} length={ident.length} sha256={ident.sha256}"
    return header + "\n" + "\n".join(seq[i:i + 70] for i in range(0, len(seq), 70)) + "\n"


# --- Sources ------------------------------------------------------------------------------------------------------

def _sample_assemblies(db: Session, sample_id: str) -> list[Assembly]:
    return list(db.scalars(select(Assembly).where(Assembly.sample_id == sample_id)
                           .order_by(Assembly.created_at.desc())))


def latest_annotation(db: Session, assembly_id: str) -> Annotation | None:
    return db.scalar(select(Annotation).where(Annotation.assembly_id == assembly_id)
                     .order_by(Annotation.created_at.desc()).limit(1))


def assembly_species(db: Session, assembly_id: str) -> dict[str, Any] | None:
    """The species ARVA's own species identification gave this genome (same_species only), with its method."""
    r = db.scalar(select(SpeciesResult).where(SpeciesResult.assembly_id == assembly_id,
                                              SpeciesResult.status == "same_species")
                  .order_by(SpeciesResult.created_at.desc()).limit(1))
    return {"species": r.species, "method": r.method, "database": r.database_name, "job_id": r.job_id} if r else None


def _assembly_brief(db: Session, a: Assembly) -> dict[str, Any]:
    sample = db.get(Sample, a.sample_id)
    ann = latest_annotation(db, a.id)
    return {"assembly_id": a.id, "sample_id": a.sample_id, "sample_code": sample.sample_code if sample else None,
            "project_id": sample.project_id if sample else None, "kind": a.kind.value, "assembler": a.assembler,
            "assembler_version": a.assembler_version, "created_at": a.created_at.isoformat(),
            "total_length": a.stats.get("total_length"),
            "annotation": {"annotation_id": ann.id, "tool": ann.tool, "tool_version": ann.tool_version}
            if ann else None, "species": assembly_species(db, a.id)}


SOURCE_KEYS = ("ncbi_16s", "vfdb", "mlst", "amrfinderplus", "spa", "reference_genomes", "genomes")
# The database kind each source reads (genomes reads ARVA's assemblies) and the tool that searches it.
SOURCE_KIND = {"ncbi_16s": "ncbi_16s", "vfdb": "vfdb", "mlst": "mlst_schemes", "amrfinderplus": "amrfinderplus",
               "spa": "spa_types", "reference_genomes": "reference_genomes", "genomes": None}
SOURCE_TOOL = {"ncbi_16s": "blast", "vfdb": "blast", "mlst": "blast", "amrfinderplus": "amrfinderplus",
               "spa": "spatyper", "reference_genomes": "blast", "genomes": "blast"}
# BLAST settings per source (ARVA's choices, shown before the run and recorded): megablast for near-identical
# references (16S of type strains, the strain's own genome, MLST alleles) as in the manual check of
# docs/sanger-design-notes.md section 6; blastn (word size 11) for VFDB, whose alleles may be more distant, with
# the e-value used for the VFDB fixture there; 500 subjects at most, BLAST's default.
BLAST_DEFAULTS = {"ncbi_16s": ("megablast", 1e-10), "vfdb": ("blastn", 1e-5), "mlst": ("megablast", 1e-10),
                  "reference_genomes": ("megablast", 1e-10), "genomes": ("megablast", 1e-10)}
# AMRFinderPlus's --coverage_min is the share of the reference protein the hit covers (amrfinder --help: "Minimum
# coverage of the reference protein (0..1)", default 0.5). A Sanger amplicon is usually 300 to 1,000 bases, less
# than half of most resistance genes (mecA is 2,007 bp): checked with AMRFinderPlus 4.2.7 and database 2026-08-07.1,
# bases 701-1,300 of mecA give no row at 0.5 and mecA at 29.79 % coverage, 100 % identity, method
# PARTIAL_CONTIG_ENDX, at 0.1. ARVA's choice is 0.1 (a 300-base read inside a 1,000-codon gene would still be
# missed, and the interface says so); AMRFinderPlus's curated identity thresholds stay (-1).
AMR_COVERAGE_MIN = 0.1
MAX_GENOMES = 50
MAX_COLLECTION_GENOMES = 5000


def _usable_of(db: Session, kind: str) -> list[ReferenceDatabase]:
    from app.services import databases as dbs

    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == kind,
                                                      ReferenceDatabase.status.in_(dbs.USABLE))
                      .order_by(ReferenceDatabase.is_default.desc(), ReferenceDatabase.created_at.desc()))
    return [r for r in rows if dbs.usable_now(r)]


def _bundled(db: Session, source: str) -> list[ReferenceDatabase]:
    from app.services import abricate_db
    from app.services import mlst as mlst_svc

    if source == "vfdb":
        abricate_db.refresh_bundled(db)
        return [r for r in _usable_of(db, "vfdb") if r.key == abricate_db.KEYS["vfdb"]]
    mlst_svc.refresh_bundled(db)
    return [r for r in _usable_of(db, "mlst_schemes") if r.key == mlst_svc.BUNDLED_KEY]


def database_options(db: Session, source: str) -> list[ReferenceDatabase]:
    if source in ("vfdb", "mlst"):
        return _bundled(db, source)
    kind = SOURCE_KIND[source]
    return _usable_of(db, kind) if kind else []


def _tool_facts(db: Session, tool_id: str) -> dict[str, Any]:
    from app.services.comparative import _tool

    return _tool(db, tool_id)


def _tool_problem(tool: dict[str, Any]) -> list[dict[str, Any]]:
    if tool["status"] == "available":
        return []
    return [{"code": "tool_missing", "params": {"tool": tool["name"]},
             "message": f"{tool['name']} is not available here ({tool['status']}): {tool['message']}"}]


def _blast_problems(tool: dict[str, Any], programs: tuple[str, ...]) -> list[dict[str, Any]]:
    from app.services.regions import _blast_problems as region_problems

    return region_problems(tool, programs)


def _genome_choices(db: Session, ident: SangerIdentification, assembly_ids: list[str] | None) -> list[Assembly]:
    if assembly_ids is None:
        return _sample_assemblies(db, ident.sample_id)[:1]
    if len(assembly_ids) > MAX_GENOMES or len(set(assembly_ids)) != len(assembly_ids):
        raise InputError("sanger_genomes_invalid", max=MAX_GENOMES)
    out = []
    for aid in assembly_ids:
        a = db.get(Assembly, aid)
        if a is None:
            raise InputError("sanger_genomes_invalid", max=MAX_GENOMES)
        out.append(a)
    return out


def _source_plan(db: Session, ident: SangerIdentification, source: str, request: dict[str, Any],
                 tools: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from app.services.mobile_elements import database_summary

    tool_id = SOURCE_TOOL[source]
    tool = tools.setdefault(tool_id, _tool_facts(db, tool_id))
    problems = list(_tool_problem(tool))
    if tool_id == "blast" and not problems:
        problems += _blast_problems(tool, ("blastn",))
    plan: dict[str, Any] = {"source": source, "kind": SOURCE_KIND[source], "tool": tool, "database": None,
                            "database_options": [], "genomes": [], "settings": {}, "problems": problems}
    chosen = (request.get("database_ids") or {}).get(source)
    if source == "genomes":
        genomes = _genome_choices(db, ident, request.get("assembly_ids"))
        plan["genomes"] = [{**_assembly_brief(db, a), "contigs_sha256": a.stats["files"]["contigs"]["sha256"],
                            "own_sample": a.sample_id == ident.sample_id} for a in genomes]
        if not genomes:
            plan["problems"].append({"code": "no_genomes", "params": {},
                                     "message": "No genome was chosen (this sample has none in ARVA)"})
    else:
        options = database_options(db, source)
        plan["database_options"] = [database_summary(r) for r in options]
        record = None
        if chosen:
            record = next((r for r in options if r.id == chosen), None)
            if record is None:
                raise InputError("sanger_database_invalid", kind=SOURCE_KIND[source])
        elif options:
            record = options[0]
        if record is None:
            plan["problems"].append({"code": "no_database", "params": {"kind": SOURCE_KIND[source]},
                                     "message": f"No usable {SOURCE_KIND[source]} database is registered or "
                                                "installed"})
        else:
            plan["database"] = database_summary(record)
            if source == "reference_genomes":
                genomes = [g for g in (record.inventory or []) if g.get("present")]
                plan["collection"] = {"genomes": len(genomes), "species": len({g.get("species") for g in genomes
                                                                               if g.get("species")})}
                if len(genomes) > MAX_COLLECTION_GENOMES:
                    plan["problems"].append({"code": "collection_too_large",
                                             "params": {"count": len(genomes), "max": MAX_COLLECTION_GENOMES},
                                             "message": f"The collection has {len(genomes)} genomes; ARVA searches "
                                                        f"at most {MAX_COLLECTION_GENOMES} one by one"})
    if source in BLAST_DEFAULTS:
        task, evalue = BLAST_DEFAULTS[source]
        overrides = (request.get("blast") or {}).get(source) or {}
        plan["settings"] = {"program": "blastn", "task": overrides.get("task") or task,
                            "evalue": float(overrides.get("evalue") or evalue),
                            "max_target_seqs": int(overrides.get("max_target_seqs") or 500),
                            "low_complexity_filter": True}
        from arva_tools.blast import BlastParams

        try:
            BlastParams(**plan["settings"]).validate()
        except ValueError as exc:
            raise InputError("sanger_consensus_invalid", detail=str(exc)) from None
    elif source == "amrfinderplus":
        organism = request.get("amr_organism") or None
        plan["settings"] = {"mode": "nucleotide", "organism": organism, "plus": True, "ident_min": -1.0,
                            "coverage_min": AMR_COVERAGE_MIN, "translation_table": 11}
    elif source == "spa":
        plan["settings"] = {"do_enrich": False}
    return plan


def search_plan(db: Session, ident: SangerIdentification, request: dict[str, Any]) -> dict[str, Any]:
    """What a search of this identification would do: for each chosen source the tool, the database (kind, name,
    version, checksum) or the genomes with their checksums and annotation, the settings, and what blocks it."""
    sources = request.get("sources") or list(SOURCE_KEYS)
    if not sources:
        raise InputError("sanger_sources_needed")
    for s in sources:
        if s not in SOURCE_KEYS:
            raise InputError("sanger_source_unknown", source=str(s)[:40])
    tools: dict[str, dict[str, Any]] = {}
    plans = [_source_plan(db, ident, s, request, tools) for s in dict.fromkeys(sources)]
    return {"identification_id": ident.id, "query": {"length": ident.length, "sha256": ident.sha256,
                                                      "mode": ident.mode},
            "sources": plans, "runnable": [p["source"] for p in plans if not p["problems"]],
            "blocked": [p["source"] for p in plans if p["problems"]],
            "notes": ["local_only", "one_job_per_source"]}


def start_search(db: Session, ident: SangerIdentification, request: dict[str, Any], confirmed: bool,
                 only_runnable: bool) -> list[AnalysisJob]:
    from app.services.jobs import create_sanger_job

    if not confirmed:
        raise InputError("sanger_confirm")
    if any(j.status in ACTIVE for j in jobs_of(db, ident)):
        raise InputError("sanger_identification_busy")
    plan = search_plan(db, ident, request)
    blocked = [p for p in plan["sources"] if p["problems"]]
    if blocked and not only_runnable:
        raise InputError("sanger_search_blocked", problems="; ".join(
            f"{p['source']}: {p['problems'][0]['message']}" for p in blocked))
    runnable = [p for p in plan["sources"] if not p["problems"]]
    if not runnable:
        raise InputError("sanger_search_blocked", problems="; ".join(
            f"{p['source']}: {p['problems'][0]['message']}" for p in blocked))
    sample = db.get(Sample, ident.sample_id)
    return [create_sanger_job(db, sample, ident, p) for p in runnable]


# --- Results ------------------------------------------------------------------------------------------------------

def _job_brief(j: AnalysisJob) -> dict[str, Any]:
    p = j.parameters or {}
    return {"job_id": j.id, "source": p.get("source"), "status": j.status.value, "tool": j.tool_name,
            "tool_version": j.tool_version, "created_at": j.created_at, "finished_at": j.finished_at,
            "database_kind": j.database_kind, "database_key": j.database_key, "database_name": j.database_name,
            "database_version": j.database_version, "database_version_source": j.database_version_source,
            "database_checksum": j.database_checksum, "database_path": j.database_path,
            "settings": p.get("settings"), "genomes": p.get("genomes"), "error_message": j.error_message,
            "error_detail": j.error_detail}


def _latest_results(db: Session, ident: SangerIdentification) -> dict[str, tuple[AnalysisJob, SangerSearchResult]]:
    """The latest completed search of each source."""
    out: dict[str, tuple[AnalysisJob, SangerSearchResult]] = {}
    for res in db.scalars(select(SangerSearchResult).where(SangerSearchResult.identification_id == ident.id)
                          .order_by(SangerSearchResult.created_at)):
        job = db.get(AnalysisJob, res.job_id)
        if job is not None and job.status is JobStatus.completed:
            out[res.source] = (job, res)
    return out


RANKED_SOURCES = ("ncbi_16s", "vfdb", "mlst", "reference_genomes", "genomes")
MAX_LISTED = 50


def _ranked_rows(latest: dict[str, tuple[AnalysisJob, SangerSearchResult]]) -> list[dict[str, Any]]:
    return [r for s in RANKED_SOURCES if s in latest for r in latest[s][1].rows]


def _reading_brief(interpretation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not interpretation:
        return None
    return {"level": interpretation["level"], "species": interpretation.get("species"),
            "genus": interpretation.get("genus"),
            "within_separation": len(interpretation.get("within_separation") or []),
            "above_species_threshold": len(interpretation.get("above_species_threshold") or [])}


def identification_brief(db: Session, ident: SangerIdentification) -> dict[str, Any]:
    """An identification in the sample's list: its best hit with how many rows and names tie with it (when several
    species tie, the one listed first only follows the database ids' sort order), and the 16S reading's level."""
    latest = _latest_results(db, ident)
    summary = core.best_summary(core.rank_hits(_ranked_rows(latest)))
    s16 = latest.get("ncbi_16s")
    jobs = jobs_of(db, ident)
    return {"id": ident.id, "sample_id": ident.sample_id, "label": ident.label, "mode": ident.mode,
            "forward_read_id": ident.forward_read_id, "reverse_read_id": ident.reverse_read_id,
            "length": ident.length, "sha256": ident.sha256, "suspected": ident.suspected,
            "created_at": ident.created_at, "searched": sorted(latest),
            "running": sum(1 for j in jobs if j.status in ACTIVE),
            "best": _brief_row(summary["row"]) if summary else None,
            "best_tied": summary["tied"] if summary else 0, "best_tied_names": summary["tied_names"] if summary else 0,
            "reading_16s": _reading_brief(core.interpret_16s(s16[1].rows)) if s16 else None,
            "conflicts": len(ident.consensus.get("conflicts") or []),
            "unresolved": (ident.consensus.get("counts") or {}).get("unresolved", 0)}


def _brief_row(r: dict[str, Any]) -> dict[str, Any]:
    keep = ("rank", "tied_with_best", "source", "subject", "title", "gene", "species", "genus", "strain", "product",
            "allele", "scheme", "accession", "genome", "identity", "identical", "query_coverage", "subject_coverage",
            "contig_coverage", "aligned_length", "query_start", "query_end", "query_length", "subject_start",
            "subject_end", "subject_length", "strand", "kind", "evalue", "bitscore", "copies", "features",
            "type_material", "species_source")
    return {k: r.get(k) for k in keep if k in r}


def _own_genome(row: dict[str, Any]) -> bool:
    src = row.get("source") or {}
    return src.get("source") == "genomes" and bool(src.get("own_sample"))


def _suspicion(ident: SangerIdentification, ranked: list[dict[str, Any]], searched: list[str],
               running: int) -> dict[str, Any] | None:
    """The comparison with what the user suspected, over every ranked hit. Before any search has finished there is
    nothing to compare (outcome not_searched); while some are still running the outcome is provisional (`pending`).
    For a species, hits on this sample's own genome are left out: the genome is named by ARVA's own species
    identification, so it would only repeat that result; and the CLSI thresholds are 16S criteria, so when the
    best hit is not the 16S rRNA gene the comparison says so."""
    if not ident.suspected:
        return None
    kind, value = ident.suspected["kind"], ident.suspected["value"]
    if not searched:
        return {"suspected": value, "kind": kind, "outcome": "not_searched", "pending": running, "searched": [],
                "reasons": [], "caveats": []}
    caveats: list[dict[str, Any]] = []
    pool = ranked
    if kind == "species":
        own = [r for r in ranked if _own_genome(r)]
        if own:
            pool = [r for r in ranked if not _own_genome(r)]
            caveats.append({"code": "own_genome_excluded", "params": {"count": len(own)}})
        if pool and not core.is_16s(pool[0]):
            caveats.append({"code": "criteria_16s_only", "params": {}})
    out = core.compare_suspected(pool, value, kind)
    return {**out, "searched": searched, "pending": running, "caveats": caveats}


def results(db: Session, ident: SangerIdentification, limit: int | None = MAX_LISTED) -> dict[str, Any]:
    """Everything shown for an identification: the reads, the consensus, each search (job, database provenance,
    rows), the ranking across sources, the 16S reading, the AMRFinderPlus and spa results and the comparison with
    the suspicion. `limit` cuts the listed rows of the ranking and of each ranked source for the interface (the
    counts are always whole); the reports pass None and list every row. `not_searched` names the sources with no
    finished search and none queued or running (16S, when its database is missing, for example)."""
    latest = _latest_results(db, ident)
    searches = []
    jobs = jobs_of(db, ident)
    for j in jobs:
        res = db.scalar(select(SangerSearchResult).where(SangerSearchResult.job_id == j.id))
        searches.append({**_job_brief(j), "result_id": res.id if res else None,
                         "rows": len(res.rows) if res else None, "details": res.details if res else None})
    ranked = core.rank_hits(_ranked_rows(latest))
    s16 = latest.get("ncbi_16s")
    interpretation = core.interpret_16s(s16[1].rows) if s16 else None
    running = sum(1 for j in jobs if j.status in ACTIVE)
    active_sources = {(j.parameters or {}).get("source") for j in jobs if j.status in ACTIVE}
    suspected = _suspicion(ident, ranked, sorted(latest), running)
    reads = {}
    for role, rid in (("forward", ident.forward_read_id), ("reverse", ident.reverse_read_id)):
        r = db.get(SangerRead, rid) if rid else None
        reads[role] = read_view(db, r) if r else None
    by_source = {}
    for s, (j, res) in latest.items():
        rows = res.rows[:limit] if s in RANKED_SOURCES and limit is not None else res.rows
        by_source[s] = {"job_id": j.id, "rows": rows, "row_count": len(res.rows), "details": res.details}
    listed = ranked[:limit] if limit is not None else ranked
    return {"identification": {**identification_brief(db, ident), "settings": ident.settings, "notes": ident.notes,
                               "sequence": ident.sequence},
            "reads": reads, "consensus": ident.consensus, "searches": searches, "by_source": by_source,
            "ranked": [_brief_row(r) for r in listed], "ranked_count": len(ranked),
            "tied_with_best": sum(1 for r in ranked if r.get("tied_with_best")),
            "interpretation_16s": interpretation, "suspected": suspected,
            "not_searched": [s for s in SOURCE_KEYS if s not in latest and s not in active_sources],
            "thresholds": {"clsi_16s": core.CLSI_16S, "gene": core.GENE_DEFAULTS},
            "sources": core.SOURCES, "notes": ["local_only", "similarity_not_function"]}


def max_upload_bytes() -> int:
    return min(MAX_FILE_BYTES, get_settings().max_upload_size_bytes)


def stored_file(r: SangerRead) -> Path:
    return get_storage().resolve(r.storage_path)
