"""AMR detection with AMRFinderPlus: the plan of a run (tool, database, search mode, organism), a sample's runs, the
project's presence/absence matrix and CSV, and the hits placed on an annotation's sequences for the Genome Explorer
and the circular map.

Every result is a gene or mutation AMRFinderPlus found, with its method, identity and coverage: ARVA never turns it
into "resistant" or "susceptible" (AMRFinderPlus does not predict phenotype). A sample without a completed run was not
searched; a completed run without rows found nothing with those settings and that database. The point-mutation
search runs only with an organism; ARVA proposes one from the sample's species identification when the species maps
to an AMRFinderPlus organism (by the table of AMRFinderPlus's own documentation), and the user can change it.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from arva_tools import ToolStatus
from arva_tools import amrfinderplus as amr_tool
from arva_tools.amrfinderplus import DEFAULTS, AmrfinderplusAdapter
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AmrResult,
    AnalysisJob,
    Annotation,
    Assembly,
    JobStatus,
    Project,
    ReferenceDatabase,
    Sample,
    SpeciesResult,
)
from app.services import amrfinder_db
from app.services import databases as dbs
from app.services.annotation import features_of
from app.services.metadata_table import sanitize_spreadsheet_cell
from app.services.mlst import assembly_facts
from app.services.performance import effective_resources

AMR_JOB = "amr_detection"
CSV_COLUMNS = ("project", "sample_code", "assembly_id", "element_symbol", "element_name", "type", "subtype", "class",
               "subclass", "method", "method_kind", "identity", "coverage", "contig", "start", "stop", "strand",
               "closest_reference", "linked_feature", "organism", "tool", "tool_version", "database_version",
               "job_id")
MATRIX_TYPES = ("AMR", "VIRULENCE", "STRESS")

# The English texts of ARVA's AMR warnings; the interface has them as amr.warning.<code>.
WARNINGS = {
    "genotype_not_phenotype": "Genes and mutations found, not a resistance phenotype: AMRFinderPlus does not predict "
                              "whether the isolate is resistant or susceptible.",
    "hits_partial": "{count, plural, one {# hit covers} other {# hits cover}} only part of the reference (PARTIAL, "
                    "inside a contig): {genes}",
    "hits_contig_end": "{count, plural, one {# hit is} other {# hits are}} partial at a contig end "
                       "(PARTIAL_CONTIG_END): the gene may continue on another contig: {genes}",
    "hits_internal_stop": "{count, plural, one {# hit has} other {# hits have}} a stop codon before the end of the "
                          "reference (INTERNAL_STOP): {genes}",
    "hits_hmm": "{count, plural, one {# hit was} other {# hits were}} found by an HMM only, without a close "
                "reference protein: {genes}",
    "hits_frameshift": "{count, plural, one {# stx operon has} other {# stx operons have}} a frameshift: {genes}",
    "hits_extended": "{count, plural, one {# stx operon extends} other {# stx operons extend}} past the reference "
                     "stop codon: {genes}",
    "hits_ambiguous": "{count, plural, one {# stx operon has} other {# stx operons have}} an ambiguous base: {genes}",
    "hits_other": "{count, plural, one {# hit has} other {# hits have}} a method ARVA does not recognise: {genes}",
    "point_mutations_not_searched": "No organism was chosen, so point mutations were not searched (not 'none found').",
    "point_mutation_genes_not_found": "No gene AMRFinderPlus screens for point mutations in {organism} was found in "
                                      "this assembly.",
    "plus_not_searched": "--plus was off: stress response and virulence genes were not searched.",
    "curated_thresholds_overridden": "The minimum identity was set to {ident_min}, overriding AMRFinderPlus's curated "
                                     "thresholds.",
    "synthetic_input": "SYNTHETIC input ({evidence}): this result describes the tools on test data, not biology.",
}


def warning_text(w: dict[str, Any]) -> str:
    from app.core.messages import render

    return render(WARNINGS[w["code"]], w.get("params") or {}) if w["code"] in WARNINGS else w["code"]


class InputError(ValueError):
    """The assembly, annotation or options cannot be used as requested (HTTP 400)."""


def _tool(db: Session) -> dict[str, Any]:
    d = detect("amrfinderplus", refresh=True)
    res = effective_resources(db)
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "reason_params": d.reason_params, "path": d.path,
            "license": d.info.license, "citation": d.info.citation, "citation_url": d.info.citation_url,
            "max_threads": res.max_threads, "default_threads": res.threads}


def database_summary(record: ReferenceDatabase) -> dict[str, Any]:
    available, reason = dbs.availability(record)
    compat = dbs.record_compatibility(record)
    facts = ((record.details or {}).get("detection") or {}).get("facts") or {}
    return {"id": record.id, "key": record.key, "name": record.name, "version": record.version,
            "version_source": record.version_source.value if record.version_source else None,
            "checksum": record.checksum, "path": record.path, "host_path": dbs._shown(record.path or ""),
            "is_default": record.is_default, "status": record.status.value, "available": available,
            "unavailable_reason": reason, "database_format": facts.get("database_format_version"),
            "variant": ((record.details or {}).get("detection") or {}).get("variant"),
            "inside_bakta": (record.details or {}).get("inside_bakta"),
            "compatibility": {"status": compat.status, "code": compat.code, "params": compat.params}}


def database_options(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == amrfinder_db.KIND,
                                                      ReferenceDatabase.status.in_(dbs.USABLE))
                      .order_by(ReferenceDatabase.is_default.desc(), ReferenceDatabase.created_at.desc()))
    return [database_summary(r) for r in rows]


def chosen_database(db: Session, database_id: str | None) -> ReferenceDatabase | None:
    if database_id:
        record = db.get(ReferenceDatabase, database_id)
        if record is None or record.kind != amrfinder_db.KIND:
            raise InputError("The chosen database is not an AMRFinderPlus database")
        return record
    usable = [r for r in database_options(db) if r["compatibility"]["status"] == "compatible" and r["available"]]
    return db.get(ReferenceDatabase, usable[0]["id"]) if usable else None


def annotations_of(db: Session, a: Assembly) -> list[dict[str, Any]]:
    """The assembly's annotations whose proteins, contigs and GFF AMRFinderPlus can read (Bakta or Prokka, with CDS
    annotated), newest first."""
    out = []
    for an in db.scalars(select(Annotation).where(Annotation.assembly_id == a.id)
                         .order_by(Annotation.created_at.desc())):
        files = an.files or {}
        cds = ((an.steps or {}).get("cds") or {}).get("status")
        fmt = {"bakta": "bakta", "prokka": "prokka"}.get(an.tool.lower())
        usable = fmt is not None and all(k in files for k in ("fna", "faa", "gff3")) and cds == "searched"
        out.append({"id": an.id, "tool": an.tool, "tool_version": an.tool_version, "created_at": an.created_at,
                    "annotation_format": fmt, "cds_status": cds, "usable": usable,
                    "cds": (an.summary or {}).get("cds")})
    return out


def species_context(db: Session, a: Assembly) -> dict[str, Any] | None:
    """The most recent species identification of the assembly that named a species."""
    s = db.scalars(select(SpeciesResult).where(SpeciesResult.assembly_id == a.id, SpeciesResult.species.isnot(None))
                   .order_by(SpeciesResult.created_at.desc())).first()
    if s is None:
        return None
    return {"id": s.id, "species": s.species, "method": s.method, "tool": s.tool, "tool_version": s.tool_version,
            "status": s.status, "created_at": s.created_at.isoformat()}


def organism_choice(organisms: list[str], species: dict[str, Any] | None) -> dict[str, Any]:
    found = amr_tool.organism_for(species["species"] if species else None, organisms)
    return {**found, "species": species}


def plan(db: Session, sample: Sample, a: Assembly, database_id: str | None, annotation_id: str | None) -> dict[str, Any]:
    """What an AMRFinderPlus run of this assembly would do here: the tool, the databases (and the copies inside Bakta
    databases, with why one cannot be used), the organisms the chosen database supports and the one ARVA proposes,
    the annotations a combined search can read, AMRFinderPlus's defaults as its --help states them, and what blocks
    the run. Only version, help and database checks run."""
    tool = _tool(db)
    problems: list[dict[str, Any]] = []
    copies = amrfinder_db.bakta_copies(db)
    record = chosen_database(db, database_id)
    database = database_summary(record) if record else None
    organisms: list[str] = []
    tool_defaults: dict[str, str] = {}
    check = None
    if tool["status"] != ToolStatus.available.value or not tool["path"]:
        problems.append({"code": "tool_unavailable", "params": {"status": tool["status"]},
                         "message": f"AMRFinderPlus is not available ({tool['status']}): {tool['message']}"})
    else:
        try:
            tool_defaults = amr_tool.help_defaults(AmrfinderplusAdapter.help_text(tool["path"]))
        except (OSError, RuntimeError) as exc:
            problems.append({"code": "help_unreadable", "params": {"detail": str(exc)},
                             "message": f"AMRFinderPlus's --help could not be read: {exc}"})
    if record is None:
        problems.append({"code": "no_database", "params": {},
                         "message": "No AMRFinderPlus database this AMRFinderPlus can read is installed: download a "
                                    "release in the Database Manager"})
    elif not dbs.usable_now(record):
        problems.append({"code": "database_unavailable", "params": {"name": record.name},
                         "message": f"{record.name} cannot be used now ({record.status.value})"})
    elif database["compatibility"]["status"] == "incompatible":
        problems.append({"code": "database_incompatible", "params": dict(database["compatibility"]["params"]),
                         "message": f"AMRFinderPlus {tool['version']} cannot read {record.name} {record.version}"})
    elif tool["path"]:
        check = amr_tool.database_check(tool["path"], Path(record.path or ""))
        if not check["ok"]:
            problems.append({"code": "database_refused", "params": {"detail": check["error"] or ""},
                             "message": f"AMRFinderPlus refuses {record.name} {record.version}: {check['error']}"})
        else:
            try:
                organisms = amr_tool.list_organisms(tool["path"], Path(record.path or ""))
            except (OSError, RuntimeError) as exc:
                problems.append({"code": "organisms_unreadable", "params": {"detail": str(exc)},
                                 "message": f"amrfinder --list_organisms failed: {exc}"})
    annotations = annotations_of(db, a)
    if annotation_id is not None and not any(x["id"] == annotation_id and x["usable"] for x in annotations):
        problems.append({"code": "annotation_unusable", "params": {},
                         "message": "The chosen annotation has no CDS, or no proteins and GFF AMRFinderPlus reads"})
    return {"tool": tool, "database": database, "databases": database_options(db), "bakta_copies": copies,
            "database_check": check, "organisms": organisms, "organism": organism_choice(organisms,
                                                                                        species_context(db, a)),
            "annotations": annotations, "defaults": DEFAULTS, "tool_defaults": tool_defaults,
            "defaults_match": tool_defaults == DEFAULTS if tool_defaults else None,
            "assembly": assembly_facts(db, a), "problems": problems}


# --- Results ------------------------------------------------------------------------------------------------

def hit_row(r: AmrResult) -> dict[str, Any]:
    return {k: getattr(r, k) for k in (
        "id", "job_id", "annotation_id", "element_symbol", "element_name", "scope", "type", "subtype", "amr_class",
        "amr_subclass", "method", "method_kind", "identity", "coverage", "target_length", "reference_length",
        "alignment_length", "contig", "assembly_contig", "start", "stop", "strand", "protein_id", "closest_accession",
        "closest_name", "hmm_accession", "hmm_description", "hierarchy_node", "feature")}


def summary_by_class(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AMR elements by class (a gene with several classes, "A/B", counts under each), with their symbols."""
    by: dict[str, set[str]] = {}
    for h in hits:
        if h["type"] != "AMR":
            continue
        for c in (h["amr_class"] or "NA").split("/"):
            by.setdefault(c, set()).add(h["element_symbol"])
    return [{"class": c, "elements": sorted(s), "count": len(s)} for c, s in sorted(by.items(), key=lambda kv:
                                                                                     (-len(kv[1]), kv[0]))]


def run_row(db: Session, job: AnalysisJob) -> dict[str, Any]:
    hits = [hit_row(r) for r in db.scalars(select(AmrResult).where(AmrResult.job_id == job.id)
                                           .order_by(AmrResult.assembly_contig, AmrResult.start))]
    p = job.parameters or {}
    rs = job.result_summary or {}
    return {"job_id": job.id, "sample_id": job.sample_id, "assembly_id": (p.get("assembly") or {}).get("assembly_id"),
            "annotation_id": p.get("annotation_id"), "status": job.status.value, "created_at": job.created_at,
            "finished_at": job.finished_at, "tool": job.tool_name, "tool_version": job.tool_version,
            "database_name": job.database_name, "database_version": job.database_version,
            "database_checksum": job.database_checksum, "database_path": job.database_path,
            "parameters": {k: p.get(k) for k in amr_tool.AmrParams.__dataclass_fields__},
            "organism_choice": p.get("organism_choice"), "mode": p.get("mode"), "warnings": rs.get("warnings") or [],
            "counts": rs.get("counts") or {}, "point_mutation_screen": rs.get("point_mutation_screen"),
            "files": rs.get("files") or {}, "log": rs.get("log") or {}, "hits": hits,
            "by_class": summary_by_class(hits)}


def sample_runs(db: Session, sample_id: str) -> list[dict[str, Any]]:
    jobs = db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample_id, AnalysisJob.job_type == AMR_JOB,
                                                AnalysisJob.status == JobStatus.completed)
                      .order_by(AnalysisJob.created_at.desc()))
    return [run_row(db, j) for j in jobs]


def latest_run(db: Session, assembly_id: str) -> AnalysisJob | None:
    for job in db.scalars(select(AnalysisJob).where(AnalysisJob.job_type == AMR_JOB,
                                                    AnalysisJob.status == JobStatus.completed)
                          .order_by(AnalysisJob.created_at.desc())):
        if ((job.parameters or {}).get("assembly") or {}).get("assembly_id") == assembly_id:
            return job
    return None


def project_overview(db: Session, project: Project) -> dict[str, Any]:
    """The most recent completed run of every sample, and the presence/absence matrix of the elements found (genes
    and point mutations, by type) across those samples. A sample without a run is 'not searched', not 'absent'."""
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    rows, elements = [], {}
    for s in samples:
        runs = sample_runs(db, s.id)
        latest = runs[0] if runs else None
        present: dict[str, list[str]] = {}
        if latest:
            for h in latest["hits"]:
                elements.setdefault(h["element_symbol"], {"element_symbol": h["element_symbol"], "type": h["type"],
                                                          "subtype": h["subtype"], "class": h["amr_class"]})
                present.setdefault(h["element_symbol"], []).append(h["method_kind"])
        rows.append({"sample_id": s.id, "sample_code": s.sample_code, "runs": len(runs),
                     "latest": {k: latest[k] for k in ("job_id", "created_at", "tool_version", "database_version",
                                                       "parameters", "counts", "warnings")} if latest else None,
                     "present": present})
    order = {t: i for i, t in enumerate(MATRIX_TYPES)}
    cols = sorted(elements.values(), key=lambda e: (order.get(e["type"], 9), e["subtype"] != "AMR",
                                                    (e["class"] or "~"), e["element_symbol"].lower()))
    return {"project_id": project.id, "project_name": project.name, "is_demo": project.is_demo, "samples": rows,
            "elements": cols, "searched": sum(1 for r in rows if r["latest"]),
            "versions": sorted({f"{r['latest']['tool_version']} / {r['latest']['database_version']}" for r in rows
                                if r["latest"]})}


def project_csv(db: Session, project: Project) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for s in db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)):
        for run in sample_runs(db, s.id):
            for h in run["hits"]:
                feature = h["feature"] or {}
                writer.writerow({
                    "project": sanitize_spreadsheet_cell(project.name), "sample_code": sanitize_spreadsheet_cell(
                        s.sample_code), "assembly_id": run["assembly_id"],
                    "element_symbol": sanitize_spreadsheet_cell(h["element_symbol"]),
                    "element_name": sanitize_spreadsheet_cell(h["element_name"] or ""), "type": h["type"],
                    "subtype": h["subtype"] or "", "class": sanitize_spreadsheet_cell(h["amr_class"] or ""),
                    "subclass": sanitize_spreadsheet_cell(h["amr_subclass"] or ""), "method": h["method"],
                    "method_kind": h["method_kind"], "identity": "" if h["identity"] is None else h["identity"],
                    "coverage": "" if h["coverage"] is None else h["coverage"],
                    "contig": sanitize_spreadsheet_cell(h["assembly_contig"] or h["contig"] or ""),
                    "start": h["start"] or "", "stop": h["stop"] or "", "strand": h["strand"] or "",
                    "closest_reference": h["closest_accession"] or "",
                    "linked_feature": sanitize_spreadsheet_cell(str(feature.get("locus_tag") or "")),
                    "organism": run["parameters"].get("organism") or "", "tool": run["tool"],
                    "tool_version": run["tool_version"], "database_version": run["database_version"] or "",
                    "job_id": run["job_id"]})
    return out.getvalue()


def matrix_csv(overview: dict[str, Any]) -> str:
    """The presence/absence matrix: 1 found, 0 searched and not found, empty not searched."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["sample_code", "searched", *[sanitize_spreadsheet_cell(e["element_symbol"])
                                                  for e in overview["elements"]]])
    for r in overview["samples"]:
        cells = [("1" if e["element_symbol"] in r["present"] else "0") if r["latest"] else ""
                 for e in overview["elements"]]
        writer.writerow([sanitize_spreadsheet_cell(r["sample_code"]), "yes" if r["latest"] else "no", *cells])
    return out.getvalue()


def annotation_hits(db: Session, annotation: Annotation, job_id: str | None) -> dict[str, Any]:
    """The hits of the assembly's most recent AMR run (or `job_id`), placed on the annotation's sequences (its contig
    names; the assembly's names map to them through the annotation's sequence list), each with the annotated
    feature it overlaps most on the same strand."""
    job = db.get(AnalysisJob, job_id) if job_id else latest_run(db, annotation.assembly_id)
    if job is None or job.job_type != AMR_JOB or ((job.parameters or {}).get("assembly") or {}).get(
            "assembly_id") != annotation.assembly_id:
        return {"run": None, "hits": []}
    by_assembly = {s.get("original_id") or s["id"]: s["id"] for s in annotation.sequences}
    ids = {s["id"] for s in annotation.sequences}
    features = [f for f in features_of(annotation) if f["type"] in ("cds", "sorf")]
    out = []
    for r in db.scalars(select(AmrResult).where(AmrResult.job_id == job.id)):
        contig = r.contig if r.annotation_id == annotation.id and r.contig in ids else by_assembly.get(
            r.assembly_contig or "")
        if contig is None or r.start is None or r.stop is None:
            continue
        linked = r.feature if (r.feature or {}).get("annotation_id") == annotation.id else link_feature(
            features, contig, r.start, r.stop, r.strand, annotation.id)
        out.append({**hit_row(r), "contig": contig, "end": r.stop, "feature": linked})
    p = job.parameters or {}
    return {"run": {"job_id": job.id, "tool_version": job.tool_version, "database_version": job.database_version,
                    "organism": p.get("organism"), "plus": p.get("plus"), "mode": p.get("mode"),
                    "created_at": job.created_at}, "hits": out}


def link_feature(features: list[dict[str, Any]], contig: str, start: int, stop: int, strand: str | None,
                 annotation_id: str) -> dict[str, Any] | None:
    """The CDS on the same contig and strand that overlaps the hit most, with the overlap as a fraction of the hit."""
    best, best_overlap = None, 0
    for f in features:
        if f["contig"] != contig or (strand in ("+", "-") and f["strand"] != strand):
            continue
        overlap = min(stop, f["end"]) - max(start, f["start"]) + 1
        if overlap > best_overlap:
            best, best_overlap = f, overlap
    if best is None:
        return None
    return {"annotation_id": annotation_id, "feature_id": best["id"], "locus_tag": best.get("locus_tag"),
            "gene": best.get("gene"), "product": best.get("product"), "how": "overlap",
            "overlap": round(best_overlap / (stop - start + 1), 4)}


def download_name(sample: Sample, job: AnalysisJob, suffix: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in sample.sample_code)
    return f"ARVA_{safe}_amrfinderplus_{job.id[:8]}.{suffix}"
