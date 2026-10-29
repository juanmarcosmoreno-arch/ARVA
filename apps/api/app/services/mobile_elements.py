"""Plasmids and other mobile genetic elements: the plan of a run (method, tool, database), a sample's runs, the contig
table of an assembly, the project overview and the elements placed on an annotation's sequences.

One job type, five methods: MOB-suite (mob_recon: each contig's chromosome or plasmid call, the reconstructed
plasmids typed by mob_typer, their replicon and relaxase biomarkers and MOB-suite's repetitive elements), PlasmidFinder
replicons (ABRicate's bundled copy), IntegronFinder, ISEScan and geNomad. Every row is what the tool reported, with
the tool's own words: MOB-suite's 'chromosome' means "not assigned to a plasmid"; a replicon on a contig does not by
itself make it a plasmid; ARVA never calls a contig a plasmid from its size. The assembler's own circularity (Flye,
Unicycler) is shown next to the calls, not mixed with them. A method without a completed run was not searched; a run
without rows found nothing with those settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from arva_tools import ToolStatus
from arva_tools import abricate as abr
from arva_tools import genomad as gn
from arva_tools import integronfinder as itf
from arva_tools import isescan as ise
from arva_tools import mobsuite as mob
from arva_tools.base import help_options
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    JobStatus,
    MobileElementResult,
    Project,
    ReferenceDatabase,
    Sample,
)
from app.services import abricate_db
from app.services import databases as dbs
from app.services.amr import link_feature
from app.services.annotation import features_of
from app.services.mlst import assembly_facts
from app.services.performance import effective_resources

MOBILE_JOB = "mobile_elements"
# Per method: the tool, the database kind it reads (None: models bundled in the tool's package), its parameters and
# the categories of the rows it writes.
METHODS: dict[str, dict[str, Any]] = {
    "mobsuite": {"tool": "mobsuite", "kind": "mobsuite", "params": mob.MobParams,
                 "categories": ("contig", "plasmid", "biomarker", "mge")},
    "plasmidfinder": {"tool": "abricate", "kind": "plasmidfinder", "params": abr.AbricateParams,
                      "categories": ("replicon",)},
    "integronfinder": {"tool": "integronfinder", "kind": None, "params": itf.IntegronParams,
                       "categories": ("integron",)},
    "isescan": {"tool": "isescan", "kind": None, "params": ise.IsescanParams, "categories": ("insertion_sequence",)},
    "genomad": {"tool": "genomad", "kind": "genomad", "params": gn.GenomadParams,
                "categories": ("genomad_plasmid", "genomad_virus")},
}
DEFAULTS = {"mobsuite": mob.DEFAULTS, "plasmidfinder": abr.DEFAULTS, "integronfinder": itf.DEFAULTS,
            "isescan": ise.DEFAULTS, "genomad": gn.DEFAULTS}

# The English texts of ARVA's warnings; the interface has them as mobile.warning.<code>.
WARNINGS = {
    "chromosome_means_unassigned": "MOB-suite's 'chromosome' means the contig was not assigned to a known plasmid "
                                   "cluster; it is not proof that the contig is chromosomal.",
    "host_range_is_prediction": "The host range is MOB-suite's prediction from the reference plasmids of the cluster "
                                "and the literature, not an observation for this isolate.",
    "replicon_on_unassigned_contig": "{count, plural, one {# contig MOB-suite did not assign to a plasmid carries} "
                                     "other {# contigs MOB-suite did not assign to a plasmid carry}} a replicon or "
                                     "relaxase ({contigs}): an integrated plasmid, or a plasmid not in the database.",
    "plasmidfinder_meaning": "A replicon found is a sequence match, not a plasmid call: replicons also lie in "
                             "chromosomes (integrated plasmids) and small plasmids may carry none.",
    "hits_partial": "{count, plural, one {# hit covers} other {# hits cover}} only part of the reference: {genes}",
    "hits_contig_end": "{count, plural, one {# partial hit ends} other {# partial hits end}} at a contig end, so the "
                       "sequence may continue on another contig: {genes}",
    "hits_complete_gaps": "{count, plural, one {# hit covers} other {# hits cover}} the whole reference with gaps "
                          "(insertions or deletions): {genes}",
    "hits_split": "{count, plural, one {# reference was} other {# references were}} found in several partial pieces "
                  "(split across contigs or interrupted): {genes}",
    "low_thresholds": "Minimum identity {minid} % and coverage {mincov} % are below ABRicate's defaults (80 %).",
    "isescan_partial": "{count, plural, one {# IS element is} other {# IS elements are}} partial (ISEScan's type p): "
                       "shorter than 400 bp or a single copy without a perfect terminal inverted repeat.",
    "genomad_scores": "geNomad's plasmid and virus scores are classifier outputs from gene markers, not proof.",
    "tool_not_validated": "{tool} {version} has not been validated with ARVA on real data; read its results with "
                          "care.",
    "synthetic_input": "SYNTHETIC input ({evidence}): this result describes the tools on test data, not biology.",
}


def warning_text(w: dict[str, Any]) -> str:
    from app.core.messages import render

    return render(WARNINGS[w["code"]], w.get("params") or {}) if w["code"] in WARNINGS else w["code"]


class InputError(ValueError):
    """The assembly, method or options cannot be used as requested (HTTP 400)."""


def _tool(db: Session, tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=True)
    res = effective_resources(db)
    return {"id": tool_id, "name": d.info.name, "status": d.status.value, "version": d.version,
            "version_validated": d.version_validated, "message": d.message, "reason": d.reason,
            "reason_params": d.reason_params, "path": d.path, "license": d.info.license,
            "citation": d.info.citation, "citation_url": d.info.citation_url, "max_threads": res.max_threads,
            "default_threads": res.threads}


def database_summary(record: ReferenceDatabase) -> dict[str, Any]:
    from app.services import database_kinds as kinds

    available, reason = dbs.availability(record)
    compat = dbs.record_compatibility(record)
    k = kinds.BY_KEY[record.kind]
    return {"id": record.id, "key": record.key, "kind": record.kind, "name": record.name, "version": record.version,
            "version_source": record.version_source.value if record.version_source else None,
            "checksum": record.checksum, "path": record.path, "host_path": dbs._shown(record.path or ""),
            "is_default": record.is_default, "status": record.status.value, "available": available,
            "unavailable_reason": reason, "bundled": record.origin.value == "bundled", "licence": k.licence,
            "licence_url": k.licence_url, "citation": k.citation, "unconfirmed": list(k.unconfirmed),
            "compatibility": {"status": compat.status, "code": compat.code, "params": compat.params}}


def database_options(db: Session, kind: str) -> list[dict[str, Any]]:
    if kind == "plasmidfinder":
        abricate_db.refresh_bundled(db)
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == kind,
                                                      ReferenceDatabase.status.in_(dbs.USABLE))
                      .order_by(ReferenceDatabase.is_default.desc(), ReferenceDatabase.created_at.desc()))
    out = [database_summary(r) for r in rows]
    if kind == "plasmidfinder":
        out = [r for r in out if r["bundled"]]
    return out


def chosen_database(db: Session, method: str, database_id: str | None) -> ReferenceDatabase | None:
    kind = METHODS[method]["kind"]
    if kind is None:
        return None
    if database_id:
        record = db.get(ReferenceDatabase, database_id)
        if record is None or record.kind != kind:
            raise InputError(f"The chosen database is not a {kind} database")
        return record
    usable = [r for r in database_options(db, kind) if r["compatibility"]["status"] == "compatible" and r["available"]]
    return db.get(ReferenceDatabase, usable[0]["id"]) if usable else None


def bundled_models(tool_id: str, executable: str | None) -> dict[str, Any] | None:
    """The models a tool bundles in its package (IntegronFinder's attC covariance model and integrase HMMs), with
    their SHA-256, recorded on the job in place of a database record."""
    if tool_id != "integronfinder" or not executable:
        return None
    files = itf.models(executable)
    if not files:
        return None
    return {"kind": "integronfinder_models", "name": "IntegronFinder bundled models", "files": [f.name for f in files],
            "checksum": itf.models_checksum(files), "path": str(files[0].parent)}


def circularity(a: Assembly) -> dict[str, dict[str, Any]]:
    """The assembler's own circularity flag of each contig (Flye's assembly_info, Unicycler's headers), or None."""
    return {c["name"]: {"circular": c.get("circular"), "source": a.assembler if c.get("circular") is not None
                        else None} for c in a.contigs or []}


def plan(db: Session, sample: Sample, a: Assembly, method: str, database_id: str | None) -> dict[str, Any]:
    """What a run of this method on this assembly would do here: the tool and its version, the database (or the
    bundled models), the tool's defaults as its --help states them and ARVA's, the assembler's circularity of the
    contigs, and what blocks the run. Only version and help checks run."""
    if method not in METHODS:
        raise InputError(f"Unknown method {method!r}")
    spec = METHODS[method]
    tool = _tool(db, spec["tool"])
    problems: list[dict[str, Any]] = []
    tool_defaults: dict[str, str] = {}
    if tool["status"] != ToolStatus.available.value or not tool["path"]:
        problems.append({"code": "tool_unavailable", "params": {"tool": tool["name"], "status": tool["status"]},
                         "message": f"{tool['name']} is not available ({tool['status']}): {tool['message']}"})
    else:
        try:
            tool_defaults = _help_defaults(method, tool["path"])
        except (OSError, RuntimeError) as exc:
            problems.append({"code": "help_unreadable", "params": {"tool": tool["name"], "detail": str(exc)},
                             "message": f"{tool['name']}'s --help could not be read: {exc}"})
    record = chosen_database(db, method, database_id)
    database = database_summary(record) if record else None
    if spec["kind"] is not None:
        if record is None:
            problems.append({"code": "no_database", "params": {"kind": spec["kind"]},
                             "message": f"No usable {spec['kind']} database is installed"})
        elif not dbs.usable_now(record):
            problems.append({"code": "database_unavailable", "params": {"name": record.name},
                             "message": f"{record.name} cannot be used now ({record.status.value})"})
        elif database["compatibility"]["status"] == "incompatible":
            problems.append({"code": "database_incompatible", "params": {"name": record.name},
                             "message": f"{tool['name']} {tool['version']} cannot read {record.name}"})
        elif method == "mobsuite" and not mob.database_state(Path(record.path or ""))["ready"]:
            missing = mob.database_state(Path(record.path or ""))["missing"]
            problems.append({"code": "database_unprepared", "params": {"files": ", ".join(missing[:6])},
                             "message": f"{record.name} lacks {', '.join(missing[:6])}"})
    models = bundled_models(spec["tool"], tool["path"])
    params = spec["params"]()
    defaults = {f: str(getattr(params, f)) for f in spec["params"].__dataclass_fields__ if f not in ("threads", "database")}
    return {"method": method, "tool": tool, "database": database,
            "databases": database_options(db, spec["kind"]) if spec["kind"] else [], "models": models,
            "defaults": defaults, "tool_defaults": tool_defaults,
            "defaults_match": tool_defaults == DEFAULTS[method] if tool_defaults else None,
            "assembly": assembly_facts(db, a), "circularity": circularity(a), "problems": problems}


def _help_defaults(method: str, exe: str) -> dict[str, str]:
    if method == "mobsuite":
        return mob.help_defaults(mob.MobsuiteAdapter.help_text(exe))
    if method == "plasmidfinder":
        return abr.help_defaults(abr.AbricateAdapter.help_text(exe))
    if method == "integronfinder":
        return itf.help_defaults(itf.IntegronfinderAdapter.help_text(exe))
    if method == "genomad":
        text = gn.GenomadAdapter.help_text(exe)
        return {k: v for k, v in gn.DEFAULTS.items() if f"--{k}" in help_options(text) or f"--{k}" in text}
    return {"nthread": "1"} if "--nthread" in ise.IsescanAdapter.help_text(exe) else {}


# --- Results ------------------------------------------------------------------------------------------------

ROW_FIELDS = ("id", "job_id", "tool", "category", "element", "element_type", "contig", "start", "end", "strand",
              "identity", "coverage", "score", "completeness", "details", "feature")


def row(r: MobileElementResult) -> dict[str, Any]:
    return {k: getattr(r, k) for k in ROW_FIELDS}


def run_row(db: Session, job: AnalysisJob) -> dict[str, Any]:
    rows = [row(r) for r in db.scalars(select(MobileElementResult).where(MobileElementResult.job_id == job.id)
                                       .order_by(MobileElementResult.category, MobileElementResult.contig,
                                                 MobileElementResult.start))]
    p = job.parameters or {}
    rs = job.result_summary or {}
    return {"job_id": job.id, "sample_id": job.sample_id, "assembly_id": (p.get("assembly") or {}).get("assembly_id"),
            "method": p.get("method"), "status": job.status.value, "created_at": job.created_at,
            "finished_at": job.finished_at, "tool": job.tool_name, "tool_version": job.tool_version,
            "database_kind": job.database_kind, "database_name": job.database_name,
            "database_version": job.database_version, "database_checksum": job.database_checksum,
            "database_path": job.database_path, "parameters": p.get("settings") or {},
            "warnings": rs.get("warnings") or [], "counts": rs.get("counts") or {}, "files": rs.get("files") or {},
            "searched_contigs": rs.get("searched_contigs") or [], "rows": rows}


def _completed(db: Session, sample_id: str | None = None):
    q = select(AnalysisJob).where(AnalysisJob.job_type == MOBILE_JOB, AnalysisJob.status == JobStatus.completed)
    if sample_id is not None:
        q = q.where(AnalysisJob.sample_id == sample_id)
    return db.scalars(q.order_by(AnalysisJob.created_at.desc()))


def sample_runs(db: Session, sample_id: str) -> list[dict[str, Any]]:
    return [run_row(db, j) for j in _completed(db, sample_id)]


def latest_runs(db: Session, assembly_id: str, sample_id: str | None = None) -> dict[str, AnalysisJob]:
    """The most recent completed run of each method on the assembly."""
    out: dict[str, AnalysisJob] = {}
    for job in _completed(db, sample_id):
        p = job.parameters or {}
        if (p.get("assembly") or {}).get("assembly_id") == assembly_id and p.get("method") not in out:
            out[p["method"]] = job
    return out


def _rows(db: Session, job: AnalysisJob | None, *categories: str) -> list[MobileElementResult] | None:
    if job is None:
        return None
    q = select(MobileElementResult).where(MobileElementResult.job_id == job.id)
    if categories:
        q = q.where(MobileElementResult.category.in_(categories))
    return list(db.scalars(q.order_by(MobileElementResult.contig, MobileElementResult.start)))


def contig_table(db: Session, a: Assembly) -> dict[str, Any]:
    """Each contig of the assembly with, side by side, MOB-suite's call (molecule type, clusters, replicon, relaxase,
    MPF and oriT types, the predicted mobility of its plasmid), the PlasmidFinder replicons, the counts of integrons,
    IS elements and geNomad calls on it, and the assembler's circularity. A method's column is None when it was not
    run on this assembly (not searched), an empty list or 0 when it found nothing."""
    latest = latest_runs(db, a.id, a.sample_id)
    mob_rows = _rows(db, latest.get("mobsuite"), "contig", "plasmid")
    plasmids = {r.element: r.details or {} for r in mob_rows or [] if r.category == "plasmid"}
    calls = {r.contig: r for r in mob_rows or [] if r.category == "contig"}
    replicons = _rows(db, latest.get("plasmidfinder"), "replicon")
    integrons = _rows(db, latest.get("integronfinder"), "integron")
    insertions = _rows(db, latest.get("isescan"), "insertion_sequence")
    genomad = _rows(db, latest.get("genomad"))
    circ = circularity(a)
    out = []
    for c in sorted(a.contigs or [], key=lambda c: c.get("rank") or 0):
        name = c["name"]
        call = calls.get(name)
        d = (call.details or {}) if call else {}
        cluster = d.get("primary_cluster_id")
        typed = plasmids.get(cluster or "") if cluster else None

        def count(rows: list[MobileElementResult] | None, name: str = name) -> int | None:
            return None if rows is None else sum(1 for r in rows if r.contig == name)

        out.append({
            "contig": name, "length": c.get("length"), "circular": circ.get(name, {}).get("circular"),
            "circular_source": circ.get(name, {}).get("source"),
            "mobsuite": None if mob_rows is None else ({
                "molecule_type": call.element_type, "primary_cluster_id": cluster,
                "secondary_cluster_id": d.get("secondary_cluster_id"), "rep_types": d.get("rep_type(s)") or [],
                "relaxase_types": d.get("relaxase_type(s)") or [], "mpf_types": sorted(set(d.get("mpf_type") or [])),
                "orit_types": d.get("orit_type(s)") or [], "circularity_status": d.get("circularity_status"),
                "predicted_mobility": (typed or {}).get("predicted_mobility"),
                "mash_nearest_neighbor": d.get("mash_nearest_neighbor"),
                "mash_neighbor_distance": d.get("mash_neighbor_distance"),
                "mash_neighbor_identification": d.get("mash_neighbor_identification"),
                "filtering_reason": d.get("filtering_reason")} if call else {"molecule_type": None}),
            "replicons": None if replicons is None else [
                {"name": r.element, "type": r.element_type, "identity": r.identity, "coverage": r.coverage,
                 "start": r.start, "end": r.end, "completeness": r.completeness} for r in replicons
                if r.contig == name],
            "integrons": count(integrons), "insertion_sequences": count(insertions),
            "genomad": None if genomad is None else {
                "plasmid_score": next((r.score for r in genomad if r.contig == name and r.category == "genomad_plasmid"),
                                      None),
                "viruses": sum(1 for r in genomad if r.contig == name and r.category == "genomad_virus")},
        })
    return {"assembly_id": a.id, "assembler": a.assembler, "assembler_version": a.assembler_version,
            "runs": {m: (latest[m].id if m in latest else None) for m in METHODS}, "contigs": out}


def sample_view(db: Session, sample_id: str) -> dict[str, Any]:
    runs = sample_runs(db, sample_id)
    assemblies = []
    for assembly_id in dict.fromkeys(r["assembly_id"] for r in runs if r["assembly_id"]):
        a = db.get(Assembly, assembly_id)
        if a is not None:
            assemblies.append(contig_table(db, a))
    return {"runs": runs, "assemblies": assemblies}


def run_summary(db: Session, job: AnalysisJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    rs = job.result_summary or {}
    return {"job_id": job.id, "created_at": job.created_at, "tool": job.tool_name, "tool_version": job.tool_version,
            "database_version": job.database_version, "counts": rs.get("counts") or {}}


def project_overview(db: Session, project: Project) -> dict[str, Any]:
    """Per sample: the most recent completed run of each method (on any of its assemblies) with its counts, None
    when not searched; and the replicon types PlasmidFinder found."""
    from app.services import virulence

    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    rows = []
    for s in samples:
        latest: dict[str, AnalysisJob] = {}
        for job in _completed(db, s.id):
            latest.setdefault((job.parameters or {}).get("method"), job)
        replicons = sorted({r.element_type for r in _rows(db, latest.get("plasmidfinder"), "replicon") or []
                            if r.element_type})
        rows.append({"sample_id": s.id, "sample_code": s.sample_code,
                     "methods": {m: run_summary(db, latest.get(m)) for m in METHODS}, "replicon_types": replicons,
                     "virulence": virulence.sample_counts(db, s.id)})
    return {"project_id": project.id, "project_name": project.name, "is_demo": project.is_demo, "samples": rows,
            "searched": {m: sum(1 for r in rows if r["methods"][m]) for m in METHODS}}


def annotation_elements(db: Session, annotation: Annotation) -> dict[str, Any]:
    """The assembly's most recent run of each method placed on the annotation's sequences (the annotation may have
    renamed the contigs: its sequence list maps the assembly's names), for the circular map's mobile-elements ring
    and the Genome Explorer: MOB-suite's plasmid contigs and each contig's call, its biomarkers and repetitive
    elements, PlasmidFinder replicons, integrons, IS elements and geNomad's calls; each element with the CDS it
    overlaps most."""
    a = db.get(Assembly, annotation.assembly_id)
    if a is None:
        return {"runs": {}, "contigs": [], "elements": []}
    latest = latest_runs(db, a.id, a.sample_id)
    to_seq = {s.get("original_id") or s["id"]: s["id"] for s in annotation.sequences}
    lengths = {s["id"]: s["length"] for s in annotation.sequences}
    features = [f for f in features_of(annotation) if f["type"] in ("cds", "sorf")]
    contigs, elements = [], []
    for method, job in latest.items():
        for r in _rows(db, job) or []:
            seq = to_seq.get(r.contig or "")
            if seq is None:
                continue
            whole = (1, lengths.get(seq) or r.end or 1)
            if r.category == "contig":
                contigs.append({"contig": seq, "molecule_type": r.element_type,
                                "primary_cluster_id": (r.details or {}).get("primary_cluster_id"), "job_id": job.id})
                if r.element_type == "plasmid":
                    elements.append({**_placed(r, seq, *whole), "category": "plasmid_contig", "method": method})
            elif r.start is None or r.end is None:
                elements.append({**_placed(r, seq, *whole), "method": method})
            else:
                elements.append({**_placed(r, seq, r.start, r.end), "method": method,
                                 "feature": link_feature(features, seq, r.start, r.end, r.strand, annotation.id)})
    return {"runs": {m: run_summary(db, j) for m, j in latest.items()}, "contigs": contigs, "elements": elements}


def _placed(r: MobileElementResult, seq: str, start: int, end: int) -> dict[str, Any]:
    return {**row(r), "contig": seq, "assembly_contig": r.contig, "start": start, "end": end, "feature": None}


def download_name(sample: Sample, job: AnalysisJob, suffix: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in sample.sample_code)
    method = (job.parameters or {}).get("method") or "mobile"
    return f"ARVA_{safe}_{method}_{job.id[:8]}.{suffix}"
