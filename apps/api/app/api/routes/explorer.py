import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_or_404
from app.db.session import get_db
from app.models import Annotation, Sample
from app.schemas.schemas import FeatureLayoutRead, GenomeSequenceRead, GenomeTracksRead
from app.services import annotation as annotation_svc
from app.services import genome_explorer as svc

router = APIRouter(tags=["genome-explorer"])

_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; sandbox"}
_Contig = Query(min_length=1, max_length=200, description="The annotator's or the assembly's name of the sequence")


def _call(fn, *args):
    try:
        return fn(*args)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This annotation has no such sequence") from None
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/annotations/{annotation_id}/tracks", response_model=GenomeTracksRead)
def get_tracks(
    annotation_id: str,
    contig: str = _Contig,
    start: int | None = Query(default=None, ge=1),
    end: int | None = Query(default=None, ge=1),
    bins: int = Query(default=svc.DEFAULT_POINTS, ge=10, le=5000, description="At most this many points per track"),
    window: int | None = Query(default=None, ge=1, le=1_000_000, description="GC window, bp (default: chosen for "
                               "the view)"),
    step: int | None = Query(default=None, ge=1, le=1_000_000, description="Distance between windows (default: the "
                             "window)"),
    db: Session = Depends(get_db),
):
    """GC content and GC skew in windows over start..end (default: the whole sequence) of one annotated sequence,
    and read depth when reads were aligned to exactly this assembly (polishing); otherwise coverage says why not."""
    annotation = get_or_404(db, Annotation, annotation_id, "Annotation")
    return _call(svc.tracks, db, annotation, contig, start, end, bins, window, step)


@router.get("/annotations/{annotation_id}/sequence", response_model=GenomeSequenceRead)
def get_sequence(
    annotation_id: str,
    contig: str = _Contig,
    start: int = Query(ge=1),
    end: int = Query(ge=1),
    strand: Literal["+", "-"] = "+",
    format: Literal["json", "fasta"] = "json",
    db: Session = Depends(get_db),
):
    """Bases start..end (1-based, inclusive; at most 1,000,000) of one annotated sequence from the annotator's own
    sequence file, reverse complemented for strand "-"; as JSON or as a FASTA download."""
    annotation = get_or_404(db, Annotation, annotation_id, "Annotation")
    s = _call(svc.sequence, annotation, contig, start, end, strand)
    if format == "json":
        return s
    sample = db.get(Sample, annotation.sample_id)
    region = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{s['contig_in_assembly']}_{s['start']}-{s['end']}").strip("._")
    name = annotation_svc.download_name(sample, annotation, f"{region}{'_rc' if strand == '-' else ''}.fasta")
    return Response(svc.sequence_fasta(sample, annotation, s), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', **_SAFE_HEADERS})


@router.get("/annotations/{annotation_id}/layout", response_model=FeatureLayoutRead)
def get_layout(annotation_id: str, contig: str = _Contig, db: Session = Depends(get_db)):
    """Every feature of one annotated sequence with the fields needed to draw it (at most 50,000)."""
    annotation = get_or_404(db, Annotation, annotation_id, "Annotation")
    return _call(svc.layout, annotation, contig)
