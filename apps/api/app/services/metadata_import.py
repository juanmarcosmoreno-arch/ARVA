"""Sample metadata tables in a project: preview against the stored samples, apply in one transaction, export."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import MetadataFileKind, MetadataImport, MetadataImportMode, Project, Sample
from app.schemas.schemas import SampleCreate, SampleUpdate
from app.services import metadata_table as mt

ACTIONS = ("create", "update", "unchanged", "error")


class NothingToApplyError(ValueError):
    pass


@dataclass(frozen=True)
class TableOptions:
    sheet: str | None = None
    header_row: int | None = None
    delimiter: str | None = None
    date_order: str | None = None
    mapping: dict[str, str] | None = None


def table_limits() -> mt.Limits:
    s = get_settings()
    return mt.Limits(max_rows=s.metadata_max_rows, max_columns=s.metadata_max_columns,
                     max_cell_chars=s.metadata_max_cell_chars)


def sample_values(sample: Sample) -> dict[str, Any]:
    """The sample's metadata as text, the form the table rows are compared with and exported in."""
    values: dict[str, Any] = {f: getattr(sample, f) for f in mt.ARVA_FIELDS}
    values["collection_date"] = sample.collection_date.isoformat() if sample.collection_date else None
    values["sequencing_technology"] = sample.sequencing_technology.value
    return {"id": sample.id, **values, "custom_metadata": sample.custom_metadata}


def _messages(messages: list[str]) -> list[dict[str, Any]]:
    return [mt.message_json(m) for m in messages]


def _project_samples(db: Session, project_id: str) -> list[Sample]:
    return list(db.scalars(select(Sample).where(Sample.project_id == project_id).order_by(Sample.sample_code)))


def read_table(data: bytes, filename: str, options: TableOptions) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse and map the file (no database); raises MetadataImportError for unreadable files."""
    parsed = mt.parse_metadata_table(data, filename, sheet=options.sheet, delimiter=options.delimiter,
                                     header_row=options.header_row, limits=table_limits())
    return parsed, mt.build_samples(parsed, overrides=options.mapping, date_order=options.date_order)


def build_preview(db: Session, project_id: str, data: bytes, filename: str, options: TableOptions,
                  table: tuple[dict[str, Any], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Everything the import would do, row by row. Writes nothing."""
    parsed, built = table or read_table(data, filename, options)
    rows = [
        {**r, "errors": _messages(r["errors"]), "warnings": _messages(r["warnings"])}
        for r in mt.plan_rows(built, [sample_values(s) for s in _project_samples(db, project_id)])
    ]
    return {
        "file": {"name": filename, "sha256": hashlib.sha256(data).hexdigest(), "kind": parsed["kind"],
                 "encoding": parsed["encoding"], "delimiter": parsed["delimiter"], "sheet": parsed["sheet"],
                 "sheets": parsed["sheets"], "header_row": parsed["header_row"]},
        "columns": built["columns"],
        "mapping": built["mapping"],
        "fields": list(mt.TARGETS),
        "rows": rows,
        "warnings": _messages(built["warnings"]),
        "errors": _messages(built["errors"]),
        "counts": {"rows": len(rows), **{a: sum(r["action"] == a for r in rows) for a in ACTIONS}},
        "date_order": built["date_order"],
        "date_order_source": built["date_order_source"],
        "ambiguous_dates": built["ambiguous_dates"],
    }


def apply_import(db: Session, project_id: str, data: bytes, filename: str, options: TableOptions,
                 mode: MetadataImportMode) -> tuple[MetadataImport, list[dict[str, Any]]]:
    """Recompute the preview and write it in one transaction. Empty cells never clear stored values."""
    # Parsed before the lock: a slow file must not block sample creation in the project meanwhile.
    table = read_table(data, filename, options)
    # Serialises imports into one project: sample_code has no unique constraint in the database.
    db.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    preview = build_preview(db, project_id, data, filename, options, table)
    counts = dict.fromkeys(("created", "updated", "unchanged"), 0)
    skipped: list[dict[str, Any]] = []
    for row in preview["rows"]:
        action = row["action"]
        if action == "error":
            skipped.append({"row": row["row"], "sample_code": row["sample_code"], "reasons": row["errors"]})
        elif action == "unchanged":
            counts["unchanged"] += 1
        elif action == "update" and mode is MetadataImportMode.create_only:
            reason = mt.Msg("exists_create_only", sample=repr(row["matched_sample_code"]))
            skipped.append({"row": row["row"], "sample_code": row["sample_code"], "reasons": _messages([reason])})
        elif action == "create":
            payload = SampleCreate.model_validate({**row["data"], "custom_metadata": row["custom"] or None})
            db.add(Sample(project_id=project_id, **payload.model_dump()))
            counts["created"] += 1
        else:
            sample = db.get(Sample, row["sample_id"])
            changes = SampleUpdate.model_validate({k: v for k, v in row["data"].items() if k != "sample_code"})
            for field, value in changes.model_dump(exclude_unset=True).items():
                setattr(sample, field, value)
            if row["custom"]:
                sample.custom_metadata = {**(sample.custom_metadata or {}), **row["custom"]}
            counts["updated"] += 1
    if counts["created"] + counts["updated"] == 0:
        raise NothingToApplyError("Nothing to apply: no row would create or update a sample.")
    file = preview["file"]
    record = MetadataImport(
        project_id=project_id, filename=filename, sha256=file["sha256"], kind=MetadataFileKind(file["kind"]),
        sheet=(file["sheet"] or "")[:255] or None, encoding=file["encoding"], delimiter=file["delimiter"], header_row=file["header_row"],
        mapping=preview["mapping"], date_order=preview["date_order"], mode=mode,
        created_count=counts["created"], updated_count=counts["updated"], unchanged_count=counts["unchanged"],
        skipped_count=len(skipped),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, skipped


def export_rows(db: Session, project_id: str) -> list[dict[str, Any]]:
    return [sample_values(s) for s in _project_samples(db, project_id)]
