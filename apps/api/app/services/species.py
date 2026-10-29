"""Species identification of an assembly: the methods ARVA offers, the databases each reads (Database Manager kinds),
the plan shown before a run, the context for the consistency checks, and the overviews of a project and of every
project.

FastANI and skani compare the assembly with every genome of a reference genome collection (validated with ARVA on
NCBI RefSeq genomes). Mash and sylph search a registered sketch file or sylph database (validated with ARVA on small
test databases built from NCBI genomes, not on the published RefSeq or GTDB databases). GTDB-Tk classifies against
the GTDB reference data; it is not validated with ARVA (its data need about 100 GB and about 140 GB of memory) and is
refused when the performance profile gives a run less than that memory.

ARVA's reading of the hits (arva_core.species) never claims more than the evidence: the species boundary is applied
to ANI values only, and the result is only as good as the collection searched.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from arva_core.species import collection_scope
from arva_tools import ToolStatus
from arva_tools import gtdbtk as gtdbtk_tool
from arva_tools.registry import detect
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    Assembly,
    MlstResult,
    Project,
    ReferenceDatabase,
    Sample,
    SpeciesResult,
)
from app.services import database_kinds as kinds
from app.services import databases as dbs
from app.services.metadata_table import sanitize_spreadsheet_cell
from app.services.mlst import InputError, assembly_facts
from app.services.performance import effective_resources

# method → the tool it runs, the database kind it reads, and how far ARVA validated it.
METHODS: dict[str, dict[str, str]] = {
    "fastani": {"tool": "fastani", "kind": "reference_genomes", "validation": "validated"},
    "skani": {"tool": "skani", "kind": "reference_genomes", "validation": "validated"},
    "mash": {"tool": "mash", "kind": "mash", "validation": "test_database"},
    "sylph": {"tool": "sylph", "kind": "sylph", "validation": "test_database"},
    "gtdbtk": {"tool": "gtdbtk", "kind": "gtdbtk", "validation": "not_validated"},
}
TOP_HITS = 25
CSV_COLUMNS = ("project", "sample_code", "assembly_id", "assembly", "method", "tool", "tool_version", "status",
               "species", "best_reference", "best_organism", "best_ani", "best_af", "runner_up", "runner_up_ani",
               "reasons", "consistency", "database", "database_version", "database_checksum", "result_id",
               "created_at")

# The English texts of ARVA's species warnings; the interface has them as species.warning.<code>.
WARNINGS = {
    "synthetic_input": "SYNTHETIC input ({evidence}): this result describes the tools on test data, not biology.",
    "genomes_missing": "{count} genome(s) of the collection could not be read and were left out: {names}",
    "not_validated": "{tool} {version} has not been validated with ARVA: check its result yourself.",
    "test_database_only": "ARVA checked {tool} on a small test database, not on published databases such as this "
                          "one: check the result yourself.",
}


def warning_text(w: dict[str, Any]) -> str:
    from app.core.messages import render

    return render(WARNINGS[w["code"]], w.get("params") or {}) if w["code"] in WARNINGS else w["code"]


def _tool(db: Session, tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=True)
    res = effective_resources(db)
    return {"id": tool_id, "name": d.info.name, "status": d.status.value, "version": d.version,
            "version_validated": d.version_validated, "message": d.message, "reason": d.reason,
            "reason_params": d.reason_params, "path": d.path, "license": d.info.license, "citation": d.info.citation,
            "citation_url": d.info.citation_url, "max_threads": res.max_threads, "default_threads": res.threads,
            "memory_gb": res.memory_gb}


def present_genomes(record: ReferenceDatabase) -> list[dict[str, Any]]:
    return [g for g in record.inventory or [] if g.get("present")]


def database_summary(record: ReferenceDatabase) -> dict[str, Any]:
    """What the dialog and the result show about a database: name, version and how it is known, checksum, and for a
    reference collection its genomes, species, genera and type material."""
    available, reason = dbs.availability(record)
    out: dict[str, Any] = {
        "id": record.id, "kind": record.kind, "name": record.name, "version": record.version,
        "version_source": record.version_source.value if record.version_source else None,
        "checksum": record.checksum, "path": record.path, "host_path": dbs._shown(record.path or ""),
        "size_bytes": record.size_bytes, "is_default": record.is_default, "status": record.status.value,
        "available": available, "unavailable_reason": reason, "verification_level": record.verification_level,
        "collection": None,
    }
    if record.kind == "reference_genomes":
        c = (record.details or {}).get("collection") or {}
        genomes = record.inventory or []
        scope = collection_scope(g.get("species") for g in genomes)
        out["collection"] = {
            "genomes": c.get("genomes", len(genomes)), "present": c.get("present"), "missing": c.get("missing"),
            "species": scope["species"], "genera": scope["genera"][:50], "genus_count": len(scope["genera"]),
            "by_species": (c.get("by_species") or [])[:20], "type_material": sum(1 for g in genomes if g.get("type_label")),
            "reference_genomes": c.get("reference_genomes"), "unclassified": c.get("unclassified"),
            "with_metadata": c.get("with_metadata") or {}, "fingerprint": c.get("fingerprint"),
            "source": ((record.details or {}).get("ncbi") or {}).get("query"),
        }
    if record.kind == "gtdbtk":
        out["data_version"] = record.version
    return out


def database_options(db: Session, kind: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == kind,
                                                      ReferenceDatabase.status.in_(dbs.USABLE))
                      .order_by(ReferenceDatabase.is_default.desc(), ReferenceDatabase.created_at.desc()))
    return [database_summary(r) for r in rows]


def chosen_database(db: Session, kind: str, database_id: str | None) -> ReferenceDatabase | None:
    if database_id:
        record = db.get(ReferenceDatabase, database_id)
        if record is None or record.kind != kind:
            raise InputError("The chosen database is not one of this method's kind")
        return record
    return dbs.default_for(db, kind)


def context(db: Session, a: Assembly) -> dict[str, Any]:
    """The MLST call and the organism given for an annotation of this assembly (the most recent of each), for the
    consistency checks."""
    m = db.scalars(select(MlstResult).where(MlstResult.assembly_id == a.id)
                   .order_by(MlstResult.created_at.desc())).first()
    annotation = None
    for an in db.scalars(select(Annotation).where(Annotation.assembly_id == a.id)
                         .order_by(Annotation.created_at.desc())):
        p = an.parameters or {}
        if p.get("genus"):
            annotation = {"id": an.id, "tool": an.tool, "genus": p.get("genus"), "species": p.get("species")}
            break
    return {"mlst": {"id": m.id, "scheme": m.scheme, "st": m.st, "tool_version": m.tool_version} if m else None,
            "annotation": annotation}


def plan(db: Session, sample: Sample, a: Assembly, method: str, database_id: str | None) -> dict[str, Any]:
    """What a species identification of this assembly would do here: the method's tool, the databases of its kind
    (and the chosen one), the resources, the context for the consistency checks and anything that blocks the run.
    Only version and help checks run."""
    if method not in METHODS:
        raise InputError(f"Unknown method {method}")
    spec = METHODS[method]
    tool = _tool(db, spec["tool"])
    problems: list[dict[str, Any]] = []
    if tool["status"] != ToolStatus.available.value:
        problems.append({"code": "tool_unavailable", "params": {"tool": tool["name"], "status": tool["status"]},
                         "message": f"{tool['name']} is not available ({tool['status']}): {tool['message']}"})
    options = database_options(db, spec["kind"])
    record = chosen_database(db, spec["kind"], database_id)
    database = database_summary(record) if record is not None else None
    kind = kinds.BY_KEY[spec["kind"]]
    if record is None:
        problems.append({"code": "no_database", "params": {"kind": kind.name},
                         "message": f"No usable {kind.name} is registered: add one in the Database Manager"})
    elif not dbs.usable_now(record):
        problems.append({"code": "database_unavailable", "params": {"name": record.name},
                         "message": f"{record.name} cannot be used now ({record.status.value})"})
    elif spec["kind"] == "reference_genomes" and not present_genomes(record):
        problems.append({"code": "collection_empty", "params": {"name": record.name},
                         "message": f"{record.name} has no genome that can be read"})
    if method == "gtdbtk":
        if tool["memory_gb"] < gtdbtk_tool.REQUIRED_MEMORY_GB:
            problems.append({"code": "gtdbtk_memory", "params": {"required": gtdbtk_tool.REQUIRED_MEMORY_GB,
                                                                 "available": tool["memory_gb"]},
                             "message": f"GTDB-Tk needs about {gtdbtk_tool.REQUIRED_MEMORY_GB} GB of memory for "
                                        f"bacteria (GTDB-Tk 2.8.0 documentation); the performance profile gives a "
                                        f"run {tool['memory_gb']} GB"})
        if record is not None and record.version not in gtdbtk_tool.COMPATIBLE_DATA:
            problems.append({"code": "gtdbtk_data_version", "params": {"version": record.version or "?",
                                                                       "compatible": ", ".join(
                                                                           gtdbtk_tool.COMPATIBLE_DATA)},
                             "message": f"GTDB-Tk 2.8.0 reads GTDB {', '.join(gtdbtk_tool.COMPATIBLE_DATA)} only; "
                                        f"this data is {record.version}"})
    return {"method": method, "methods": METHODS, "tool": tool, "validation": spec["validation"],
            "database_kind": spec["kind"], "databases": options, "database": database,
            "assembly": assembly_facts(db, a), "context": context(db, a), "problems": problems,
            "gtdbtk_memory_gb": gtdbtk_tool.MEMORY_GB if method == "gtdbtk" else None}


# --- Overviews --------------------------------------------------------------------------------------------------------

def _rows(db: Session, project_ids: list[str] | None) -> list[tuple[SpeciesResult, Sample, Project, Assembly]]:
    q = (select(SpeciesResult, Sample, Project, Assembly).join(Sample, Sample.id == SpeciesResult.sample_id)
         .join(Project, Project.id == Sample.project_id).join(Assembly, Assembly.id == SpeciesResult.assembly_id))
    if project_ids is not None:
        q = q.where(Sample.project_id.in_(project_ids))
    return list(db.execute(q.order_by(SpeciesResult.created_at.desc())).all())


def _row(s: SpeciesResult, sample: Sample, project: Project, a: Assembly) -> dict[str, Any]:
    i = s.interpretation or {}
    return {"id": s.id, "sample_id": sample.id, "sample_code": sample.sample_code, "project_id": project.id,
            "project_name": project.name, "is_demo": project.is_demo, "assembly_id": a.id, "assembler": a.assembler,
            "assembler_version": a.assembler_version, "assembly_kind": a.kind.value, "method": s.method,
            "tool": s.tool, "tool_version": s.tool_version, "status": s.status, "species": s.species,
            "best": i.get("best"), "runner_up": i.get("runner_up"), "reasons": i.get("reasons") or [],
            "consistency": s.consistency, "warnings": s.warnings, "database_name": s.database_name,
            "database_version": s.database_version, "created_at": s.created_at}


def project_overview(db: Session, project: Project) -> dict[str, Any]:
    """Every sample of the project with its most recent species result, and the species found."""
    rows = _rows(db, [project.id])
    latest: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for s, sample, proj, a in rows:
        counts[sample.id] = counts.get(sample.id, 0) + 1
        latest.setdefault(sample.id, _row(s, sample, proj, a))
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    found: dict[tuple[str, str | None], int] = {}
    for r in latest.values():
        found[(r["status"], r["species"])] = found.get((r["status"], r["species"]), 0) + 1
    return {
        "project_id": project.id, "project_name": project.name, "is_demo": project.is_demo,
        "samples": [{"sample_id": s.id, "sample_code": s.sample_code, "results": counts.get(s.id, 0),
                     "latest": latest.get(s.id)} for s in samples],
        "species": [{"status": k[0], "species": k[1], "samples": n}
                    for k, n in sorted(found.items(), key=lambda kv: (-kv[1], str(kv[0])))],
    }


def overview(db: Session, limit: int) -> dict[str, Any]:
    projects = list(db.scalars(select(Project).order_by(Project.name)))
    sample_counts = dict(db.execute(select(Sample.project_id, func.count()).group_by(Sample.project_id)).all())
    rows = _rows(db, None)
    done: dict[str, set[str]] = {}
    for _s, sample, proj, _a in rows:
        done.setdefault(proj.id, set()).add(sample.id)
    return {
        "projects": [{"project_id": p.id, "project_name": p.name, "is_demo": p.is_demo,
                      "samples": sample_counts.get(p.id, 0), "identified_samples": len(done.get(p.id, set()))}
                     for p in projects],
        "recent": [_row(*r) for r in rows[:limit]],
        "total_results": len(rows),
    }


def _fmt(v: Any) -> str:
    return "" if v is None else f"{v:g}" if isinstance(v, float) else str(v)


def project_csv(db: Session, project: Project) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for s, sample, proj, a in _rows(db, [project.id]):
        i = s.interpretation or {}
        best, other = i.get("best") or {}, i.get("runner_up") or {}
        writer.writerow({
            "project": sanitize_spreadsheet_cell(proj.name), "sample_code": sanitize_spreadsheet_cell(sample.sample_code),
            "assembly_id": a.id, "assembly": sanitize_spreadsheet_cell(f"{a.assembler} {a.assembler_version} "
                                                                       f"({a.kind.value})"),
            "method": s.method, "tool": s.tool, "tool_version": s.tool_version, "status": s.status,
            "species": sanitize_spreadsheet_cell(s.species or ""),
            "best_reference": sanitize_spreadsheet_cell(best.get("accession") or best.get("reference") or ""),
            "best_organism": sanitize_spreadsheet_cell(best.get("organism") or ""),
            "best_ani": _fmt(best.get("ani")), "best_af": _fmt(best.get("af")),
            "runner_up": sanitize_spreadsheet_cell(other.get("species") or ""), "runner_up_ani": _fmt(other.get("ani")),
            "reasons": "; ".join(r["code"] for r in i.get("reasons") or []),
            "consistency": "; ".join(f"{c['source']}:{c['outcome']}" for c in s.consistency),
            "database": sanitize_spreadsheet_cell(s.database_name or ""),
            "database_version": sanitize_spreadsheet_cell(s.database_version or ""),
            "database_checksum": s.database_checksum or "", "result_id": s.id, "created_at": s.created_at.isoformat(),
        })
    return out.getvalue()


def download_name(sample: Sample, s: SpeciesResult, suffix: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in sample.sample_code)
    return f"ARVA_{safe}_species_{s.method}_{s.id[:8]}.{suffix}"



# The English texts of ARVA's reading, for the reports; the interface has them as species.status.<code>,
# species.reason.<code>, species.caveat.<code> and species.consistency.<outcome>.
STATUS_TEXT = {
    "same_species": "Same species as the closest reference: {species}",
    "ambiguous": "Ambiguous: the evidence does not support a single species",
    "below_boundary": "No reference in this collection within the species boundary",
    "no_hits": "No reference reported",
    "screening_only": "Nearest sketch only (Mash distance; no species call)",
}
REASON_TEXT = {
    "near_boundary": "The best ANI ({ani} %) is within {margin} percentage points of the {boundary} % boundary.",
    "two_species_above_boundary": "{species} ({ani} %) and {other} ({other_ani} %) are both above {boundary} %.",
    "close_species": "{other} ({other_ani} %) is within {margin} percentage points of {species} ({ani} %).",
    "low_af": "The aligned fraction ({af}) is below {min_af}: the ANI covers too little of the genomes.",
    "af_unknown": "The aligned fraction is not known for this hit.",
    "no_species_name": "The closest reference ({reference}) has no species name.",
    "gtdbtk_warning": "GTDB-Tk warning: {text}",
}
CAVEAT_TEXT = {
    "collection_bound": "The result can only be as good as the collection: a species that is not in it cannot be "
                        "found, and a reference's name is the one it was deposited with.",
    "single_genus": "This collection holds only {genus} genomes: a genome of another genus cannot be identified with "
                    "it.",
    "fastani_range": "FastANI reports no ANI for pairs much below 80 % (FastANI README).",
    "sylph_assembly": "sylph is built for reads; on an assembly ARVA reads its unadjusted containment ANI "
                      "(Naive_ANI).",
    "not_type_material": "The closest reference ({reference}) is not type material.",
    "mash_not_ani": "Mash's distance estimates a k-mer mutation rate; it is not ANI and no species boundary is applied "
                    "to it.",
    "gtdb_names": "GTDB-Tk names are GTDB's taxonomy, which can differ from NCBI's.",
    "not_validated": "GTDB-Tk has not been validated with ARVA.",
}
CONSISTENCY_TEXT = {
    "agree": "agrees", "genus_agrees": "agrees at genus level", "differs": "differs — check",
    "not_comparable": "not comparable",
}


def reading_text(table: dict[str, str], item: dict[str, Any]) -> str:
    from app.core.messages import render

    code = item.get("code") or item.get("status") or ""
    return render(table[code], item.get("params") or {}) if code in table else code
