from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import sample_or_404
from app.db.session import get_db
from app.schemas.schemas import (
    AnalysisJobRead,
    ImportEntryRead,
    ImportListingRead,
    ImportRootRead,
    ServerImportRequest,
)
from app.services.capacity import ensure_space
from app.services.import_roots import browse, configured_roots, get_root, resolve_file
from app.services.jobs import create_server_import_job

router = APIRouter(tags=["imports"])


@router.get("/imports/roots", response_model=list[ImportRootRead])
def list_import_roots():
    """Server folders configured in ARVA_IMPORT_ROOTS (empty when the feature is disabled)."""
    return [
        ImportRootRead(index=r.index, name=r.name, path=str(r.path), exists=r.exists)
        for r in configured_roots()
    ]


@router.get("/imports/browse", response_model=ImportListingRead)
def browse_import_root(
    root: int = Query(ge=0, description="Index of the import folder"),
    path: str = Query(default="", max_length=4096, description="Folder relative to the import folder"),
):
    listing = browse(get_root(root), path)
    return ImportListingRead(
        root=listing.root,
        path=listing.path,
        parent=listing.parent,
        entries=[
            ImportEntryRead(
                name=e.name, path=e.path, type=e.type, size_bytes=e.size_bytes, kind=e.kind,
                modified_at=e.modified_at,
            )
            for e in listing.entries
        ],
        truncated=listing.truncated,
        unsupported_names=listing.unsupported_names,
    )


@router.post(
    "/samples/{sample_id}/files/import-server",
    response_model=AnalysisJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_from_server(sample_id: str, payload: ServerImportRequest, db: Session = Depends(get_db)):
    """Copy files from a server folder into the sample in a background job (sources are never modified)."""
    sample = sample_or_404(db, sample_id)
    root = get_root(payload.root)
    selected = [resolve_file(root, p) for p in payload.paths]
    if len({f.relative for f in selected}) != len(selected):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The same file was selected more than once")
    ensure_space(sum(f.size_bytes for f in selected))
    return create_server_import_job(db, sample, root.path, [f.relative for f in selected])
