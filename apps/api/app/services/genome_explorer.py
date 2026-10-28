"""ARVA Genome Explorer (spec §20): an annotation's sequences, their GC content and GC skew in windows, read depth
where reads were aligned to the same contigs, sequence slices and a compact layout of the features of one contig.

The sequence of every track is the annotator's own copy of the contigs (its .fna file): the features' coordinates
refer to it. Read depth comes only from an alignment of reads to exactly the annotated assembly, which ARVA makes
when it polishes: the polishing reads aligned to the draft and to the polished result (arva_core.genome_view depth
profiles). Read depth or k-mer coverage reported by an assembler is per contig and is not drawn as a track.
"""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from arva_core.annotation import region_features, tool_contig
from arva_core.formats import open_sequence_file
from arva_core.genome_view import (
    MAX_POINTS,
    auto_window,
    depth_points,
    gc_counts,
    gc_fraction,
    gc_windows,
    protein_check,
    read_depth_profile,
    slice_sequence,
)
from arva_core.seqstats import SequenceFormatError, iter_fasta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, Annotation, Assembly, AssemblyKind, JobStatus, Project, Sample
from app.services import annotation as annotation_svc
from app.storage import get_storage

MAX_SEQUENCE = 1_000_000
MAX_LAYOUT_FEATURES = 50_000
DEFAULT_POINTS = 1_000
MAP_POINTS = 1_440
REPORT_MAP_POINTS = 720
LAYOUT_FIELDS = ("id", "locus_tag", "tool_id", "type", "start", "end", "strand", "length", "edge", "gene", "product",
                 "hypothetical", "pseudo", "partial")
MAP_FIELDS = ("contig", *LAYOUT_FIELDS)


# --- Sequences -----------------------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _read_fasta(path: str, mtime_ns: int, size: int) -> tuple[dict[str, bytes], str]:
    seqs: dict[str, bytes] = {}
    digest = hashlib.sha256()
    with open(path, "rb") as raw:
        for block in iter(lambda: raw.read(1 << 20), b""):
            digest.update(block)
    with open_sequence_file(Path(path)) as fh:
        for header, seq, _q, _line in iter_fasta(fh):
            name = header[1:].decode("utf-8", "replace").split(maxsplit=1)[0] if header[1:].strip() else ""
            seqs.setdefault(name, seq)
    return seqs, digest.hexdigest()


def sequence_source(annotation: Annotation) -> tuple[dict[str, bytes], dict[str, Any]]:
    """The annotator's FASTA of the annotated sequences, with where it came from."""
    entry = (annotation.files or {}).get("fna")
    path = get_storage().resolve(entry["path"]) if entry else None
    if path is None or not path.is_file():
        raise FileNotFoundError(f"{annotation.tool}'s sequence file (.fna) is missing, so the sequence cannot be shown")
    st = path.stat()
    try:
        seqs, sha256 = _read_fasta(str(path), st.st_mtime_ns, st.st_size)
    except (OSError, SequenceFormatError) as exc:
        raise FileNotFoundError(f"{annotation.tool}'s sequence file cannot be read: {exc}") from exc
    return seqs, {"file": "fna", "tool": annotation.tool, "sha256": sha256, "recorded_sha256": entry.get("sha256")}


def contig(annotation: Annotation, name: str) -> dict[str, Any]:
    """The annotated sequence named `name` (the annotator's name or the assembly's)."""
    tool_name = tool_contig(annotation.sequences, name)
    if tool_name is None:
        raise LookupError(name)
    return next(s for s in annotation.sequences if s["id"] == tool_name)


def contig_sequence(annotation: Annotation, record: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    seqs, source = sequence_source(annotation)
    seq = seqs.get(record["id"])
    if seq is None:
        raise FileNotFoundError(f"{annotation.tool}'s sequence file has no sequence {record['id']}")
    if len(seq) != record["length"]:
        raise FileNotFoundError(f"{annotation.tool}'s sequence {record['id']} has {len(seq):,} bp, but the annotation "
                                f"recorded {record['length']:,} bp")
    return seq, source


def _region(record: dict[str, Any], start: int | None, end: int | None) -> tuple[int, int]:
    length = record["length"]
    start, end = start or 1, end or length
    if not 1 <= start <= end <= length:
        raise ValueError(f"the region must lie within 1-{length:,} with start <= end")
    return start, end


# --- Read depth ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _profile(path: str, mtime_ns: int, size: int) -> tuple[dict[str, Any], str]:
    p = Path(path)
    return read_depth_profile(p), hashlib.sha256(p.read_bytes()).hexdigest()


def _profile_candidates(db: Session, a: Assembly) -> list[tuple[AnalysisJob, str]]:
    """Polishing jobs whose alignment targets are exactly this assembly: its own (the polished result) and those
    that polished it (their draft alignment), newest first."""
    out = []
    if a.kind is AssemblyKind.polished:
        job = db.get(AnalysisJob, a.job_id)
        if job is not None:
            out.append((job, "after"))
    children = db.scalars(select(Assembly).where(Assembly.parent_assembly_id == a.id)
                          .order_by(Assembly.created_at.desc())).all()
    for child in children:
        job = db.get(AnalysisJob, child.job_id)
        if job is not None and job.status is JobStatus.completed:
            out.append((job, "before"))
    return out


def depth_profile(db: Session, annotation: Annotation) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(profile, source) of the read-depth profile for the annotated assembly, or (None, {"reason": ...})."""
    a = db.get(Assembly, annotation.assembly_id)
    if a is None:
        return None, {"reason": "assembly_missing"}
    candidates = _profile_candidates(db, a)
    if not candidates:
        return None, {"reason": "no_alignment"}
    for job, side in candidates:
        summary = job.result_summary or {}
        indirect = summary.get("indirect") or {}
        entry = (indirect.get(side) or {}).get("depth_profile")
        if not entry:
            continue
        path = get_storage().resolve(entry["path"])
        if not path.is_file():
            continue
        st = path.stat()
        try:
            profile, sha256 = _profile(str(path), st.st_mtime_ns, st.st_size)
        except ValueError:
            continue
        if sha256 != entry.get("sha256"):
            continue
        samtools = next((h for h in summary.get("helpers") or [] if h.get("tool_id") == "samtools"), {})
        return profile, {
            "job_id": job.id, "polisher": job.tool_name, "polisher_version": job.tool_version,
            "alignment": "polished" if side == "after" else "draft", "aligner": indirect.get("aligner"),
            "reads": indirect.get("reads"), "resolution": profile["resolution"],
            "command": profile["source"].get("command"), "samtools_version": samtools.get("version"),
            "deletions_counted": profile["source"].get("deletions_counted"),
            "overlapping_mates_counted_twice": profile["source"].get("overlapping_mates_counted_twice"),
            "sha256": sha256,
        }
    return None, {"reason": "profile_missing"}


# --- Tracks, sequence, layout --------------------------------------------------------------------------------

def tracks(db: Session, annotation: Annotation, name: str, start: int | None, end: int | None, points: int,
           window: int | None, step: int | None) -> dict[str, Any]:
    """GC and GC skew of the windows over start..end of a sequence, and its read depth when a profile exists."""
    record = contig(annotation, name)
    seq, source = contig_sequence(annotation, record)
    start, end = _region(record, start, end)
    auto = window is None
    if auto:
        window = auto_window(end - start + 1, points)
    step = step or window
    gc = gc_windows(seq, start - 1, end, window, step, points)
    profile, coverage_source = depth_profile(db, annotation)
    coverage: dict[str, Any] = {"available": False, **coverage_source}
    if profile is not None:
        assembly_name = record.get("original_id") or record["id"]
        entry = next((c for c in profile["contigs"] if c["name"] == assembly_name), None)
        if entry is None or entry["length"] != record["length"]:
            coverage = {"available": False, "reason": "contig_mismatch", "job_id": coverage_source["job_id"]}
        else:
            coverage = {"available": True, "source": coverage_source, "contig_mean_depth": entry["mean_depth"],
                        **depth_points(entry["sums"], entry["length"], profile["resolution"], start - 1, end, points)}
    return {"contig": record["id"], "contig_in_assembly": record.get("original_id") or record["id"],
            "length": record["length"], "start": start, "end": end, "points": points,
            "sequence_source": source, "gc": {**gc, "auto": auto, "contig_gc": gc_fraction(seq)},
            "coverage": coverage}


def sequence(annotation: Annotation, name: str, start: int, end: int, strand: str) -> dict[str, Any]:
    record = contig(annotation, name)
    start, end = _region(record, start, end)
    if end - start + 1 > MAX_SEQUENCE:
        raise ValueError(f"at most {MAX_SEQUENCE:,} bp at a time; download the annotator's sequence file for whole "
                         "contigs")
    seq, source = contig_sequence(annotation, record)
    return {"contig": record["id"], "contig_in_assembly": record.get("original_id") or record["id"], "start": start,
            "end": end, "strand": strand, "length": end - start + 1,
            "sequence": slice_sequence(seq, start, end, strand).decode("ascii", "replace"), "source": source}


def sequence_fasta(sample: Sample, annotation: Annotation, s: dict[str, Any], width: int = 60) -> str:
    rc = " reverse complement" if s["strand"] == "-" else ""
    header = (f">{s['contig_in_assembly']}:{s['start']}-{s['end']}({s['strand']}) sample={sample.sample_code} "
              f"annotation={annotation.id} source={annotation.tool} {s['source']['file']}{rc}")
    seq = s["sequence"]
    return "\n".join([header, *(seq[i:i + width] for i in range(0, len(seq), width))]) + "\n"


def layout(annotation: Annotation, name: str) -> dict[str, Any]:
    """Every feature of one sequence with the fields needed to draw it, in the annotator's order."""
    record = contig(annotation, name)
    items = [{k: f[k] for k in LAYOUT_FIELDS} for f in annotation_svc.features_of(annotation)
             if f["contig"] == record["id"]]
    if len(items) > MAX_LAYOUT_FEATURES:
        raise ValueError(f"{len(items):,} features on this sequence; the explorer draws at most "
                         f"{MAX_LAYOUT_FEATURES:,}")
    return {"contig": record["id"], "contig_in_assembly": record.get("original_id") or record["id"],
            "length": record["length"], "total": len(items), "items": items}


def genome_map(db: Session, annotation: Annotation, names: list[str], points: int,
               window: int | None) -> dict[str, Any]:
    """What a circular map of the named sequences (default: all, in the annotator's order) draws: their features, GC
    content and GC skew in windows of one length for every sequence (default: a 1-2-5 length giving about `points`
    windows over all of them), and read depth in about the same windows where reads were aligned to exactly this
    assembly."""
    records = [] if names else list(annotation.sequences)
    for name in names:
        r = contig(annotation, name)
        if r not in records:
            records.append(r)
    if not records:
        raise LookupError("no sequences")
    total = sum(r["length"] for r in records)
    auto = window is None
    window = window or auto_window(total, points)
    windows = sum(-(-r["length"] // window) for r in records)
    if windows > MAX_POINTS:
        raise ValueError(f"{windows:,} windows of {window:,} bp (a map draws at most {MAX_POINTS:,}): use a larger "
                         "window")
    profile, coverage_source = depth_profile(db, annotation)
    by_name = {c["name"]: c for c in profile["contigs"]} if profile is not None else {}
    sequences, counts, source = [], [0, 0], None
    for r in records:
        seq, source = contig_sequence(annotation, r)
        n = -(-r["length"] // window)
        gc = gc_windows(seq, 0, r["length"], window, window, n)
        g_c, acgt = gc_counts(seq)
        counts[0] += g_c
        counts[1] += acgt
        assembly_name = r.get("original_id") or r["id"]
        coverage: dict[str, Any] = {"available": False, "reason": coverage_source.get("reason")}
        if profile is not None:
            entry = by_name.get(assembly_name)
            if entry is None or entry["length"] != r["length"]:
                coverage = {"available": False, "reason": "contig_mismatch"}
            else:
                pts = depth_points(entry["sums"], entry["length"], profile["resolution"], 0, r["length"],
                                   min(MAX_POINTS, max(1, math.ceil(r["length"] / max(window, profile["resolution"])))))
                coverage = {"available": True, "contig_mean_depth": entry["mean_depth"],
                            **{k: pts[k] for k in ("start", "end", "mean")}}
        sequences.append({"contig": r["id"], "contig_in_assembly": assembly_name, "length": r["length"],
                          "topology": r.get("topology"),
                          "gc": {"contig_gc": round(g_c / acgt, 6) if acgt else None, **{k: gc[k] for k in ("start", "end", "gc", "skew")}},
                          "coverage": coverage})
    ids = {r["id"] for r in records}
    items = [{k: f[k] for k in MAP_FIELDS} for f in annotation_svc.features_of(annotation) if f["contig"] in ids]
    if len(items) > MAX_LAYOUT_FEATURES:
        raise ValueError(f"{len(items):,} features on these sequences; a map draws at most {MAX_LAYOUT_FEATURES:,}")
    available = any(s["coverage"]["available"] for s in sequences)
    return {"total_length": total, "points": points, "sequence_source": source,
            "gc": {"window": window, "step": window, "auto": auto,
                   "genome_gc": round(counts[0] / counts[1], 6) if counts[1] else None},
            "coverage": {"available": available, "reason": None if available else coverage_source.get("reason")
                         or "contig_mismatch", "source": coverage_source if available else None},
            "sequences": sequences, "total": len(items), "features": items}


def region_ids(annotation: Annotation, name: str, start: int, end: int) -> list[int]:
    record = contig(annotation, name)
    start, end = _region(record, start, end)
    ids = [f["id"] for f in region_features(annotation_svc.features_of(annotation), annotation.sequences,
                                            record["id"], start, end)]
    if not ids:
        raise annotation_svc.InputError("No feature overlaps this region")
    return ids


# --- Feature checks --------------------------------------------------------------------------------------------

def feature_checks(annotation: Annotation, f: dict[str, Any], nucleotide: dict | None,
                   protein: dict | None) -> dict[str, Any]:
    """Whether the annotator's gene sequence equals the genome at the feature's coordinates and, for CDS, whether its
    protein equals the genome's translation there. A check; the annotator's sequences are what is shown."""
    table = (annotation.parameters or {}).get("translation_table") or 11
    out: dict[str, Any] = {"nucleotide": {"status": "not_checked", "reason": "no_sequence"},
                           "protein": {"table": table, "status": "not_checked", "reason": "not_coding"}}
    try:
        record = contig(annotation, f["contig"])
        seq, _ = contig_sequence(annotation, record)
        genome = slice_sequence(seq, f["start"], f["end"], f["strand"] if f["strand"] == "-" else "+",
                                circular=f["edge"]).decode("ascii", "replace").upper()
    except (LookupError, FileNotFoundError, ValueError):
        out["nucleotide"]["reason"] = "no_genome"
        out["protein"]["reason"] = "no_genome"
        return out
    if nucleotide:
        theirs = nucleotide["sequence"].upper()
        same = genome[:len(theirs)] == theirs if nucleotide["truncated"] else genome == theirs
        out["nucleotide"] = {"status": "match" if same else "differs", "reason": None}
    if f["type"] in ("cds", "sorf"):
        out["protein"] = (protein_check(genome, protein["sequence"], table, f["partial"], f["pseudo"])
                          if protein and not protein["truncated"] else
                          {"table": table, "status": "not_checked", "reason": "no_protein"})
    return out


# --- Listing ---------------------------------------------------------------------------------------------------

def list_annotations(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(select(Annotation, Sample, Project, Assembly)
                      .join(Sample, Sample.id == Annotation.sample_id)
                      .join(Project, Project.id == Sample.project_id)
                      .join(Assembly, Assembly.id == Annotation.assembly_id)
                      .order_by(Annotation.created_at.desc()).limit(limit)).all()
    out = []
    for ann, sample, project, a in rows:
        s = ann.summary or {}
        out.append({"id": ann.id, "tool": ann.tool, "tool_version": ann.tool_version,
                    "database_name": ann.database_name, "database_version": ann.database_version,
                    "created_at": ann.created_at, "sample_id": sample.id, "sample_code": sample.sample_code,
                    "project_id": project.id, "project_name": project.name, "is_demo": bool(project.is_demo),
                    "assembly_id": a.id, "assembler": a.assembler, "assembler_version": a.assembler_version,
                    "assembly_kind": a.kind.value, "sequences": len(ann.sequences or []),
                    "total_length": sum(x["length"] for x in ann.sequences or []), "features": s.get("features"),
                    "cds": s.get("cds"), "synthetic_evidence": s.get("synthetic_evidence") or []})
    return out
