"""ARVA Discover: the per-sample table that the exploratory analyses of arva_core.discover run on, built only from
stored results and sample metadata, with the provenance of every column.

Columns:
* fields (categorical): species (latest species identification), st (latest MLST: scheme:ST), clonal_complex,
  country (geographic origin), host, source (sample type), year (collection date), organism, and every custom
  metadata key as meta:<key> (phenotypes and other columns the user imported).
* features (0/1 per sample): amr:<symbol> from the latest AMRFinderPlus run, vf:<gene> from the latest VFDB screen,
  rep:<replicon> from the latest PlasmidFinder screen. A sample whose latest run of a source does not exist is "not
  searched" (None) for every feature of that source, never absent.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arva_core import discover as core
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AmrResult,
    AnalysisJob,
    JobStatus,
    MlstResult,
    MobileElementResult,
    Project,
    Sample,
    SpeciesResult,
    VirulenceResult,
)
from app.services import amr
from app.services.jobs import AMR_JOB, MOBILE_JOB, VIRULENCE_JOB

FIELDS = ("species", "st", "clonal_complex", "country", "host", "source", "year", "organism")
SOURCES = ("amr", "vf", "rep")
ANALYSES = ("associations", "cooccurrence", "lineage", "heatmap", "pca")
CAVEATS = list(core.CAVEAT_CODES)


class DiscoverError(Exception):
    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message)
        self.code, self.params = code, params


def _latest_by_sample(db: Session, model, samples: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in db.scalars(select(model).where(model.sample_id.in_(samples)).order_by(model.created_at.desc())):
        out.setdefault(r.sample_id, r)
    return out


def _latest_jobs(db: Session, project_id: str, job_type: str,
                 keep: Callable[[AnalysisJob], bool] = lambda _j: True) -> dict[str, AnalysisJob]:
    out: dict[str, AnalysisJob] = {}
    for j in db.scalars(select(AnalysisJob).where(AnalysisJob.project_id == project_id,
                                                  AnalysisJob.job_type == job_type,
                                                  AnalysisJob.status == JobStatus.completed)
                        .order_by(AnalysisJob.created_at.desc())):
        if j.sample_id and j.sample_id not in out and keep(j):
            out[j.sample_id] = j
    return out


def _assembly_of(job: AnalysisJob) -> str | None:
    return ((job.parameters or {}).get("assembly") or {}).get("assembly_id")


def table(db: Session, project: Project) -> dict[str, Any]:
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    ids = [s.id for s in samples]
    species = _latest_by_sample(db, SpeciesResult, ids)
    mlst = _latest_by_sample(db, MlstResult, ids)
    fields: dict[str, list[str | None]] = {k: [] for k in FIELDS}
    meta_keys = sorted({k for s in samples for k in (s.custom_metadata or {})})
    for k in meta_keys:
        fields[f"meta:{k}"] = []
    for s in samples:
        sp, m = species.get(s.id), mlst.get(s.id)
        cc = (m.clonal_complex or {}).get("value") if m and (m.clonal_complex or {}).get("available") else None
        values = {
            "species": sp.species if sp and sp.species else None,
            "st": f"{m.scheme}:{m.st}" if m and m.scheme and m.st else None,
            "clonal_complex": str(cc) if cc else None,
            "country": s.geographic_origin or None, "host": s.host or None, "source": s.sample_type or None,
            "year": str(s.collection_date.year) if s.collection_date else None, "organism": s.organism or None,
        }
        for k in meta_keys:
            v = (s.custom_metadata or {}).get(k)
            values[f"meta:{k}"] = str(v).strip() if v not in (None, "") else None
        for k in fields:
            fields[k].append(values[k])

    amr_jobs = _latest_jobs(db, project.id, AMR_JOB)
    vf_jobs = _latest_jobs(db, project.id, VIRULENCE_JOB)
    rep_jobs = _latest_jobs(db, project.id, MOBILE_JOB, lambda j: (j.parameters or {}).get("method") == "plasmidfinder")
    found: dict[str, dict[str, set[str]]] = {src: {} for src in SOURCES}
    amr_cols: dict[str, dict[str, Any]] = {}
    for sid, j in amr_jobs.items():
        found["amr"][sid] = set()
        for symbol, subtype, scope in db.execute(select(AmrResult.element_symbol, AmrResult.subtype, AmrResult.scope)
                                                 .where(AmrResult.job_id == j.id, AmrResult.type == "AMR")):
            found["amr"][sid].add(symbol)
            col = amr_cols.setdefault(symbol, {"subtype": subtype, "plus": False, "organisms": []})
            col["plus"] |= scope == "plus"
            if subtype == "POINT":
                col["organisms"].append((j.parameters or {}).get("organism"))
    for sid, j in vf_jobs.items():
        found["vf"][sid] = set(db.scalars(select(VirulenceResult.gene).where(VirulenceResult.job_id == j.id)))
    for sid, j in rep_jobs.items():
        found["rep"][sid] = set(db.scalars(select(MobileElementResult.element).where(
            MobileElementResult.job_id == j.id, MobileElementResult.category == "replicon")))
    features: dict[str, list[int | None]] = {}
    for src in SOURCES:
        names = sorted({g for genes in found[src].values() for g in genes if g})
        for g in names:
            # None: not searched, either no run or (AMRFinderPlus) a run that did not look for it (amr.searched_for).
            features[f"{src}:{g}"] = [
                None if s.id not in found[src] or (src == "amr" and not amr.searched_for(
                    amr_jobs[s.id].parameters, amr_cols[g])) else int(g in found[src][s.id]) for s in samples]

    jobs = {"amr": amr_jobs, "vf": vf_jobs, "rep": rep_jobs}
    provenance = {src: {"searched": len(jobs[src]),
                        "versions": sorted({f"{j.tool_name} {j.tool_version}" + (f" / {j.database_name or ''} "
                                                                                  f"{j.database_version}"
                                                                                  if j.database_version else "")
                                            for j in jobs[src].values()})}
                  for src in SOURCES}
    provenance["species"] = {"samples": len(species), "versions": sorted({f"{r.tool} {r.tool_version}"
                                                                          for r in species.values()})}
    provenance["st"] = {"samples": len(mlst), "versions": sorted({f"{r.tool} {r.tool_version}" for r in mlst.values()})}
    mixed = []
    for s in samples:
        used = {a for a in (_assembly_of(jobs[src][s.id]) for src in SOURCES if s.id in jobs[src]) if a}
        used |= {r.assembly_id for r in (species.get(s.id), mlst.get(s.id)) if r is not None}
        if len(used) > 1:
            mixed.append(s.sample_code)
    return {"project_id": project.id, "samples": [{"id": s.id, "code": s.sample_code} for s in samples],
            "fields": fields, "features": features, "provenance": provenance, "mixed_assemblies": mixed}


def summary(data: dict[str, Any]) -> dict[str, Any]:
    n = len(data["samples"])
    return {
        "project_id": data["project_id"], "samples": n, "label": core.LABEL, "caveats": CAVEATS,
        "fields": [{"name": k, "known": sum(1 for v in vals if v is not None),
                    "values": sorted({v for v in vals if v is not None})[:200]} for k, vals in data["fields"].items()],
        "features": [{"name": k, "source": k.split(":", 1)[0], "with": sum(1 for v in vals if v),
                      "searched": sum(1 for v in vals if v is not None)} for k, vals in data["features"].items()],
        "provenance": data["provenance"], "mixed_assemblies": data["mixed_assemblies"],
    }


def _select(data: dict[str, Any], sources: list[str], one_hot: list[str], min_with: int) -> dict[str, list]:
    feats = {k: v for k, v in data["features"].items() if k.split(":", 1)[0] in sources}
    for name in one_hot:
        feats.update(core.one_hot(name, _field(data, name)))
    return {k: v for k, v in feats.items()
            if sum(1 for x in v if x) >= min_with and sum(1 for x in v if x == 0) >= min_with}


def _field(data: dict[str, Any], name: str | None) -> list[str | None]:
    if name not in data["fields"]:
        raise DiscoverError("discover_unknown_field", f"No field named {name}", field=name)
    return data["fields"][name]


def analyse(db: Session, project: Project, analysis: str, sources: list[str], one_hot: list[str],
            group: str | None, lineage: str | None, min_group: int, min_with: int, alpha: float) -> dict[str, Any]:
    if analysis not in ANALYSES:
        raise DiscoverError("discover_unknown_analysis", f"Unknown analysis {analysis}", analysis=analysis)
    bad = [s for s in sources if s not in SOURCES]
    if bad:
        raise DiscoverError("discover_unknown_source", f"Unknown feature source {bad[0]}", source=bad[0])
    data = table(db, project)
    ids = [s["id"] for s in data["samples"]]
    codes = {s["id"]: s["code"] for s in data["samples"]}
    feats = _select(data, sources, one_hot, min_with)
    strata = _field(data, lineage) if lineage else None
    base = {"analysis": analysis, "samples_total": len(ids), "features_used": len(feats), "sources": sources,
            "one_hot": one_hot, "min_with": min_with, "group": group, "lineage": lineage,
            "caveats": CAVEATS, "provenance": data["provenance"], "mixed_assemblies": data["mixed_assemblies"],
            "sample_codes": codes}
    if analysis == "associations":
        if not group:
            raise DiscoverError("discover_group_required", "Choose the field to compare groups by")
        return {**base, **core.associations(feats, _field(data, group), min_group, strata)}
    if analysis == "cooccurrence":
        if len(feats) > core.MAX_COOCCURRENCE_FEATURES:
            raise DiscoverError("discover_too_many_features", "Too many features for a co-occurrence network",
                                features=len(feats), maximum=core.MAX_COOCCURRENCE_FEATURES)
        return {**base, **core.cooccurrence(feats, alpha, strata)}
    if analysis == "lineage":
        if not lineage:
            raise DiscoverError("discover_lineage_required", "Choose the lineage field")
        return {**base, **core.lineage_distribution(feats, strata)}
    if analysis == "heatmap":
        return {**base, **core.heatmap(feats, ids)}
    return {**base, **core.pca(feats, ids)}
