"""The mobilome of a sample, consolidated: per assembly, the plasmids MOB-suite reconstructed (with their contigs and
replicon types), the IS elements (ISEScan, and MOB-suite's repetitive elements), the integrons (IntegronFinder) and
the plasmid, virus and provirus calls of geNomad, each with the AMR, stress and virulence genes found on the same
sequence (AMRFinderPlus and VFDB through ABRicate, their most recent runs on that assembly).

A gene is placed relative to an element only by coordinates on the assembly: "inside" (the gene overlaps the
element), "near" (on the same contig within `window` bases of it) or "on_plasmid" (on a contig MOB-suite assigned to
that plasmid). Physical proximity or co-location is not evidence that a gene is mobilised or was transferred
horizontally; nothing here says so.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AmrResult,
    AnalysisJob,
    Assembly,
    JobStatus,
    MobileElementResult,
    Project,
    Sample,
    VirulenceResult,
)
from app.services.mobile_elements import MOBILE_JOB, latest_runs

# The flanking distance of spec §16's regions (10 kb before and after); the user can change it.
WINDOW_DEFAULT = 10_000
WINDOW_MAX = 200_000
ELEMENT_CATEGORIES = {"insertion_sequence": "insertion_sequence", "mge": "repetitive_element", "integron": "integron",
                      "genomad_virus": "virus", "genomad_plasmid": "genomad_plasmid"}


def _latest_job(db: Session, model, assembly_id: str) -> str | None:
    return db.scalar(select(model.job_id).join(AnalysisJob, AnalysisJob.id == model.job_id)
                     .where(model.assembly_id == assembly_id, AnalysisJob.status == JobStatus.completed)
                     .order_by(AnalysisJob.created_at.desc()).limit(1))


def _genes(db: Session, a: Assembly) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    genes: list[dict[str, Any]] = []
    amr_job = _latest_job(db, AmrResult, a.id)
    vf_job = _latest_job(db, VirulenceResult, a.id)
    if amr_job:
        for r in db.scalars(select(AmrResult).where(AmrResult.job_id == amr_job)):
            contig = r.assembly_contig or r.contig
            if contig and r.start is not None and r.stop is not None:
                genes.append({"source": "amrfinderplus", "gene": r.element_symbol, "name": r.element_name,
                              "type": r.type, "subtype": r.subtype, "class": r.amr_class, "contig": contig,
                              "start": min(r.start, r.stop), "end": max(r.start, r.stop), "strand": r.strand,
                              "identity": r.identity, "coverage": r.coverage, "method": r.method})
    if vf_job:
        for r in db.scalars(select(VirulenceResult).where(VirulenceResult.job_id == vf_job)):
            if r.contig and r.start is not None and r.end is not None:
                genes.append({"source": "vfdb", "gene": r.gene, "name": r.product, "type": "VIRULENCE",
                              "subtype": None, "class": r.vf_category, "contig": r.contig,
                              "start": min(r.start, r.end), "end": max(r.start, r.end), "strand": r.strand,
                              "identity": r.identity, "coverage": r.coverage, "method": r.hit_kind})
    return genes, {"amrfinderplus": amr_job, "vfdb": vf_job}


def _rows(db: Session, job: AnalysisJob | None, *categories: str) -> list[MobileElementResult]:
    if job is None:
        return []
    return list(db.scalars(select(MobileElementResult).where(MobileElementResult.job_id == job.id,
                                                             MobileElementResult.category.in_(categories))
                           .order_by(MobileElementResult.contig, MobileElementResult.start)))


def _place(gene: dict[str, Any], contig: str, start: int | None, end: int | None, window: int) -> dict | None:
    if gene["contig"] != contig:
        return None
    if start is None or end is None:
        return {"relation": "same_contig", "distance": None}
    lo, hi = min(start, end), max(start, end)
    if gene["start"] <= hi and gene["end"] >= lo:
        return {"relation": "inside", "distance": 0}
    d = lo - gene["end"] if gene["end"] < lo else gene["start"] - hi
    return {"relation": "near", "distance": d} if d <= window else None


def assembly_mobilome(db: Session, a: Assembly, window: int = WINDOW_DEFAULT) -> dict[str, Any]:
    latest = latest_runs(db, a.id, a.sample_id)
    genes, gene_jobs = _genes(db, a)
    contig_rows = _rows(db, latest.get("mobsuite"), "contig")
    cluster_of = {r.contig: (r.details or {}).get("primary_cluster_id") for r in contig_rows
                  if r.element_type == "plasmid"}
    plasmids = []
    for r in _rows(db, latest.get("mobsuite"), "plasmid"):
        d = r.details or {}
        members = d.get("contigs") or [c for c, k in cluster_of.items() if k == r.element]
        carried = [{**g, "relation": "on_plasmid", "distance": None} for g in genes if g["contig"] in members]
        plasmids.append({"id": r.element, "tool": "mobsuite", "contigs": members, "size": d.get("size"),
                         "rep_types": d.get("rep_type(s)"), "relaxase_types": d.get("relaxase_type(s)"),
                         "mpf_type": d.get("mpf_type"), "orit_types": d.get("orit_type(s)"),
                         "predicted_mobility": r.element_type, "genes": carried})
    replicons = [{"name": r.element, "type": r.element_type, "contig": r.contig, "start": r.start, "end": r.end,
                  "tool": "plasmidfinder", "plasmid": cluster_of.get(r.contig or "")}
                 for r in _rows(db, latest.get("plasmidfinder"), "replicon")]
    sources = (("isescan", ("insertion_sequence",)), ("mobsuite", ("mge",)), ("integronfinder", ("integron",)),
               ("genomad", ("genomad_virus", "genomad_plasmid")))
    elements = []
    for method, cats in sources:
        for r in _rows(db, latest.get(method), *cats):
            whole = r.category == "genomad_plasmid" or (r.category == "genomad_virus" and r.element_type == "virus")
            start, end = (None, None) if whole else (r.start, r.end)
            placed = []
            for g in genes:
                where = _place(g, r.contig or "", start, end, window)
                if where is not None:
                    placed.append({**g, **where})
            elements.append({"tool": method, "category": ELEMENT_CATEGORIES[r.category], "element": r.element,
                             "element_type": r.element_type, "contig": r.contig, "start": start, "end": end,
                             "strand": r.strand, "completeness": r.completeness, "score": r.score,
                             "plasmid": cluster_of.get(r.contig or ""), "genes": placed})
    on_plasmids = {(g["source"], g["gene"], g["contig"], g["start"]) for p in plasmids for g in p["genes"]}
    by_elements = {(g["source"], g["gene"], g["contig"], g["start"]) for e in elements for g in e["genes"]}
    amr_keys = {(g["source"], g["gene"], g["contig"], g["start"]) for g in genes if g["type"] == "AMR"}
    return {
        "assembly_id": a.id, "assembler": a.assembler, "kind": a.kind.value, "window": window,
        "runs": {m: (latest[m].id if m in latest else None) for m in ("mobsuite", "plasmidfinder", "isescan",
                                                                         "integronfinder", "genomad")},
        "gene_runs": gene_jobs, "plasmids": plasmids, "replicons": replicons, "elements": elements,
        "counts": {"plasmids": len(plasmids), "plasmid_contigs": len(cluster_of), "replicons": len(replicons),
                   "insertion_sequences": sum(1 for e in elements if e["category"] == "insertion_sequence"),
                   "repetitive_elements": sum(1 for e in elements if e["category"] == "repetitive_element"),
                   "integrons": sum(1 for e in elements if e["category"] == "integron"),
                   "viruses": sum(1 for e in elements if e["category"] == "virus"),
                   "genes": len(genes), "genes_on_plasmids": len(on_plasmids),
                   "genes_with_elements": len(by_elements),
                   "amr_on_plasmids": len({k for k in on_plasmids if k in amr_keys})},
    }


def _assemblies_with_runs(db: Session, sample_id: str) -> list[Assembly]:
    ids = []
    for job in db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample_id,
                                                    AnalysisJob.job_type == MOBILE_JOB,
                                                    AnalysisJob.status == JobStatus.completed)
                          .order_by(AnalysisJob.created_at.desc())):
        aid = ((job.parameters or {}).get("assembly") or {}).get("assembly_id")
        if aid and aid not in ids:
            ids.append(aid)
    return [a for a in (db.get(Assembly, i) for i in ids) if a is not None]


def sample_mobilome(db: Session, sample_id: str, window: int = WINDOW_DEFAULT) -> dict[str, Any]:
    return {"sample_id": sample_id, "window": window,
            "assemblies": [assembly_mobilome(db, a, window) for a in _assemblies_with_runs(db, sample_id)]}


def project_mobilome(db: Session, project: Project, window: int = WINDOW_DEFAULT) -> dict[str, Any]:
    """Per sample, the consolidated counts of its most recently searched assembly, and the replicon types and genes
    carried on plasmids (by name)."""
    rows = []
    for s in db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)):
        assemblies = _assemblies_with_runs(db, s.id)
        if not assemblies:
            rows.append({"sample_id": s.id, "sample_code": s.sample_code, "assembly_id": None, "counts": None,
                         "replicon_types": [], "plasmid_genes": [], "element_genes": []})
            continue
        m = assembly_mobilome(db, assemblies[0], window)
        rows.append({"sample_id": s.id, "sample_code": s.sample_code, "assembly_id": m["assembly_id"],
                     "counts": m["counts"],
                     "replicon_types": sorted({r["type"] for r in m["replicons"] if r["type"]}
                                              | {t for p in m["plasmids"] for t in (p["rep_types"] or [])}),
                     "plasmid_genes": sorted({g["gene"] for p in m["plasmids"] for g in p["genes"]}),
                     "element_genes": sorted({g["gene"] for e in m["elements"] for g in e["genes"]
                                              if g["relation"] == "inside"})})
    return {"project_id": project.id, "window": window, "samples": rows}
