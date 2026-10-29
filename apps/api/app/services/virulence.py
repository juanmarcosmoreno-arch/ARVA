"""Virulence-factor genes: ABRicate's screen of an assembly against its bundled VFDB (core set A), and the view that
puts those hits next to the virulence genes AMRFinderPlus reported with --plus, each row with its source.

The two sources are never merged into one call: they search different references with different methods
(AMRFinderPlus: NCBI's curated proteins, translated search; ABRicate: VFDB's nucleotide sequences, blastn), so a
gene can be found by one and not the other. Where a VFDB hit and an AMRFinderPlus hit overlap on a contig, each row
names the other. A hit is sequence similarity to a known virulence-factor gene, never evidence that the isolate is
virulent. VFDB's licence and the citation it asks for are shown as the vfdb kind states them (not stated on VFDB's
download page; database_kinds.py).
"""
from __future__ import annotations

from typing import Any

from arva_tools import ToolStatus
from arva_tools import abricate as abr
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AmrResult,
    AnalysisJob,
    Annotation,
    Assembly,
    JobStatus,
    ReferenceDatabase,
    Sample,
    VirulenceResult,
)
from app.services import abricate_db
from app.services import databases as dbs
from app.services.amr import AMR_JOB, link_feature
from app.services.amr import latest_run as latest_amr_run
from app.services.annotation import features_of
from app.services.mlst import assembly_facts
from app.services.mobile_elements import database_summary
from app.services.performance import effective_resources

VIRULENCE_JOB = "virulence_screen"
SOURCES = ("vfdb", "amrfinderplus")

# The English texts of ARVA's virulence warnings; the interface has them as virulence.warning.<code>.
WARNINGS = {
    "vfdb_meaning": "A VFDB hit is nucleotide similarity to a known virulence-factor gene, not evidence that the "
                    "isolate is virulent.",
    "hits_partial": "{count, plural, one {# hit covers} other {# hits cover}} only part of the VFDB reference: "
                    "{genes}",
    "hits_contig_end": "{count, plural, one {# partial hit ends} other {# partial hits end}} at a contig end, so the "
                       "gene may continue on another contig: {genes}",
    "hits_complete_gaps": "{count, plural, one {# hit covers} other {# hits cover}} the whole reference with gaps "
                          "(insertions or deletions): {genes}",
    "hits_split": "{count, plural, one {# gene was} other {# genes were}} found in several partial pieces (split "
                  "across contigs or interrupted): {genes}",
    "low_thresholds": "Minimum identity {minid} % and coverage {mincov} % are below ABRicate's defaults (80 %).",
    "split_may_be_missed": "A gene split across contigs is reported only where each piece reaches the minimum "
                           "coverage ({mincov} %); below it, the gene is not reported at all.",
    "vfdb_terms_unstated": "VFDB's download page states no licence for its files; cite VFDB (Liu B. et al. 2022, "
                           "Nucleic Acids Research 50:D912) when you publish.",
    "synthetic_input": "SYNTHETIC input ({evidence}): this result describes the tools on test data, not biology.",
}


def warning_text(w: dict[str, Any]) -> str:
    from app.core.messages import render

    return render(WARNINGS[w["code"]], w.get("params") or {}) if w["code"] in WARNINGS else w["code"]


class InputError(ValueError):
    """The assembly or options cannot be used as requested (HTTP 400)."""


def _tool(db: Session) -> dict[str, Any]:
    d = detect("abricate", refresh=True)
    res = effective_resources(db)
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "reason_params": d.reason_params, "path": d.path,
            "license": d.info.license, "citation": d.info.citation, "citation_url": d.info.citation_url,
            "max_threads": res.max_threads, "default_threads": res.threads}


def database(db: Session) -> ReferenceDatabase | None:
    abricate_db.refresh_bundled(db)
    return db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.key == abricate_db.KEYS["vfdb"],
                                                     ReferenceDatabase.status.in_(dbs.USABLE)))


def plan(db: Session, sample: Sample, a: Assembly) -> dict[str, Any]:
    """What a VFDB screen of this assembly would do here: ABRicate, its bundled VFDB (sequences, index date, checksum,
    licence and citation status), its defaults as --help states them and ARVA's, and what blocks the run."""
    tool = _tool(db)
    problems: list[dict[str, Any]] = []
    tool_defaults: dict[str, str] = {}
    if tool["status"] != ToolStatus.available.value or not tool["path"]:
        problems.append({"code": "tool_unavailable", "params": {"tool": "ABRicate", "status": tool["status"]},
                         "message": f"ABRicate is not available ({tool['status']}): {tool['message']}"})
    else:
        try:
            tool_defaults = abr.help_defaults(abr.AbricateAdapter.help_text(tool["path"]))
        except (OSError, RuntimeError) as exc:
            problems.append({"code": "help_unreadable", "params": {"tool": "ABRicate", "detail": str(exc)},
                             "message": f"ABRicate's --help could not be read: {exc}"})
    record = database(db) if tool["path"] else None
    if tool["path"] and record is None:
        problems.append({"code": "no_database", "params": {"kind": "vfdb"},
                         "message": "ABRicate's bundled VFDB was not found next to ABRicate"})
    return {"tool": tool, "database": database_summary(record) if record else None,
            "defaults": {k: str(v) for k, v in abr.AbricateParams().as_dict().items() if k != "threads"},
            "tool_defaults": tool_defaults, "defaults_match": tool_defaults == abr.DEFAULTS if tool_defaults else None,
            "assembly": assembly_facts(db, a), "problems": problems}


HIT_FIELDS = ("id", "job_id", "source", "gene", "contig", "start", "end", "strand", "identity", "coverage", "ref_start",
              "ref_end", "ref_length", "gap_openings", "gap_positions", "coverage_map", "accession", "product",
              "vf_name", "vf_id", "vf_category", "vfc_id", "organism", "hit_kind", "pieces", "feature")


def hit_row(r: VirulenceResult) -> dict[str, Any]:
    return {k: getattr(r, k) for k in HIT_FIELDS}


def run_row(db: Session, job: AnalysisJob) -> dict[str, Any]:
    hits = [hit_row(r) for r in db.scalars(select(VirulenceResult).where(VirulenceResult.job_id == job.id)
                                           .order_by(VirulenceResult.contig, VirulenceResult.start))]
    p = job.parameters or {}
    rs = job.result_summary or {}
    return {"job_id": job.id, "sample_id": job.sample_id, "assembly_id": (p.get("assembly") or {}).get("assembly_id"),
            "status": job.status.value, "created_at": job.created_at, "finished_at": job.finished_at,
            "tool": job.tool_name, "tool_version": job.tool_version, "database_name": job.database_name,
            "database_version": job.database_version, "database_checksum": job.database_checksum,
            "database_path": job.database_path, "parameters": p.get("settings") or {},
            "database_terms": p.get("database_terms") or {}, "warnings": rs.get("warnings") or [],
            "counts": rs.get("counts") or {}, "files": rs.get("files") or {}, "hits": hits}


def _completed(db: Session, sample_id: str):
    return db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample_id,
                                                AnalysisJob.job_type == VIRULENCE_JOB,
                                                AnalysisJob.status == JobStatus.completed)
                      .order_by(AnalysisJob.created_at.desc()))


def sample_runs(db: Session, sample_id: str) -> list[dict[str, Any]]:
    return [run_row(db, j) for j in _completed(db, sample_id)]


def latest_run(db: Session, assembly_id: str, sample_id: str) -> AnalysisJob | None:
    return next((j for j in _completed(db, sample_id)
                 if ((j.parameters or {}).get("assembly") or {}).get("assembly_id") == assembly_id), None)


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["contig"] == b["contig"] and a["start"] is not None and b["start"] is not None
            and min(a["end"], b["end"]) >= max(a["start"], b["start"]))


def merged(db: Session, a: Assembly) -> dict[str, Any]:
    """The assembly's most recent VFDB screen and most recent AMRFinderPlus run side by side: one list of rows, each
    with its source, sorted by position; `also_found_by` names the other source's overlapping rows. A source that was
    not run (or AMRFinderPlus without --plus, which does not search virulence genes) is 'not_searched'."""
    vf_job = latest_run(db, a.id, a.sample_id)
    amr_job = latest_amr_run(db, a.id)
    rows: list[dict[str, Any]] = []
    if vf_job is not None:
        for r in db.scalars(select(VirulenceResult).where(VirulenceResult.job_id == vf_job.id)):
            rows.append({"source": "vfdb", "gene": r.gene, "contig": r.contig, "start": r.start, "end": r.end,
                         "strand": r.strand, "identity": r.identity, "coverage": r.coverage, "kind": r.hit_kind,
                         "method": "blastn", "description": r.product, "vf_name": r.vf_name, "vf_id": r.vf_id,
                         "vf_category": r.vf_category, "reference": r.accession, "pieces": r.pieces, "id": r.id})
    amr_plus = bool((amr_job.parameters or {}).get("plus")) if amr_job else False
    if amr_job is not None and amr_plus:
        for r in db.scalars(select(AmrResult).where(AmrResult.job_id == amr_job.id, AmrResult.type == "VIRULENCE")):
            rows.append({"source": "amrfinderplus", "gene": r.element_symbol, "contig": r.assembly_contig or r.contig,
                         "start": r.start, "end": r.stop, "strand": r.strand, "identity": r.identity,
                         "coverage": r.coverage, "kind": r.method_kind, "method": r.method,
                         "description": r.element_name, "vf_name": None, "vf_id": None, "vf_category": r.subtype,
                         "reference": r.closest_accession, "pieces": None, "id": r.id})
    rows.sort(key=lambda x: (x["contig"] or "", x["start"] or 0, x["source"]))
    for x in rows:
        x["also_found_by"] = sorted({f"{y['source']}:{y['gene']}" for y in rows
                                     if y["source"] != x["source"] and _overlap(x, y)})
    status = {"vfdb": {"status": "searched" if vf_job else "not_searched", "job_id": vf_job.id if vf_job else None,
                       "tool_version": vf_job.tool_version if vf_job else None,
                       "database_version": vf_job.database_version if vf_job else None,
                       "hits": sum(1 for x in rows if x["source"] == "vfdb")},
              "amrfinderplus": {"status": "searched" if amr_plus else ("plus_off" if amr_job else "not_searched"),
                                "job_id": amr_job.id if amr_job else None,
                                "tool_version": amr_job.tool_version if amr_job else None,
                                "database_version": amr_job.database_version if amr_job else None,
                                "hits": sum(1 for x in rows if x["source"] == "amrfinderplus")}}
    return {"assembly_id": a.id, "sources": status, "rows": rows}


def sample_view(db: Session, sample_id: str) -> dict[str, Any]:
    runs = sample_runs(db, sample_id)
    ids = list(dict.fromkeys([r["assembly_id"] for r in runs if r["assembly_id"]]))
    for job in db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample_id, AnalysisJob.job_type == AMR_JOB,
                                                    AnalysisJob.status == JobStatus.completed)):
        aid = ((job.parameters or {}).get("assembly") or {}).get("assembly_id")
        if aid and aid not in ids:
            ids.append(aid)
    views = [merged(db, a) for a in (db.get(Assembly, i) for i in ids) if a is not None]
    return {"runs": runs, "assemblies": views}


def sample_counts(db: Session, sample_id: str) -> dict[str, int | None]:
    """The VFDB hits of the sample's most recent screen and the AMRFinderPlus virulence genes of its most recent run
    with --plus (None: not searched)."""
    vf = next(iter(_completed(db, sample_id)), None)
    amr = next((j for j in db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample_id,
                                                                AnalysisJob.job_type == AMR_JOB,
                                                                AnalysisJob.status == JobStatus.completed)
                                      .order_by(AnalysisJob.created_at.desc()))
                if (j.parameters or {}).get("plus")), None)
    return {"vfdb": None if vf is None else ((vf.result_summary or {}).get("counts") or {}).get("hits", 0),
            "amrfinderplus": None if amr is None else ((amr.result_summary or {}).get("counts") or {}).get("VIRULENCE",
                                                                                                         0)}


def annotation_hits(db: Session, annotation: Annotation) -> dict[str, Any]:
    """The VFDB hits of the assembly's most recent screen placed on the annotation's sequences, each with the CDS it
    overlaps most (the circular map's virulence ring shows them beside AMRFinderPlus's, by source)."""
    a = db.get(Assembly, annotation.assembly_id)
    job = latest_run(db, a.id, a.sample_id) if a else None
    if job is None:
        return {"run": None, "hits": []}
    to_seq = {s.get("original_id") or s["id"]: s["id"] for s in annotation.sequences}
    features = [f for f in features_of(annotation) if f["type"] in ("cds", "sorf")]
    out = []
    for r in db.scalars(select(VirulenceResult).where(VirulenceResult.job_id == job.id)):
        seq = to_seq.get(r.contig or "")
        if seq is None or r.start is None or r.end is None:
            continue
        out.append({**hit_row(r), "contig": seq, "assembly_contig": r.contig,
                    "feature": link_feature(features, seq, r.start, r.end, r.strand, annotation.id)})
    return {"run": {"job_id": job.id, "tool_version": job.tool_version, "database_version": job.database_version,
                    "created_at": job.created_at}, "hits": out}


def download_name(sample: Sample, job: AnalysisJob, suffix: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in sample.sample_code)
    return f"ARVA_{safe}_vfdb_{job.id[:8]}.{suffix}"
