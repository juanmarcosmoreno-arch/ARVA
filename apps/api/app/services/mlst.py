"""MLST with mlst: the assembly and scheme of a run, the PubMLST schemes mlst bundles as a read-only database record,
a sample's results, and the overviews of a project and of every project.

The ST is mlst's call for the allele combination in the scheme it chose (or was given). ARVA makes no call of its
own: the clonal complex is read from the scheme's profile file when the scheme has one, and novel, partial, missing
or several alleles, tied schemes and no scheme found are shown as warnings next to mlst's call, never turned into an
ST.
"""
from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path
from typing import Any

from arva_tools import ToolStatus
from arva_tools import mlst as mlst_tool
from arva_tools.mlst import DEFAULTS, PUBMLST_OPEN_UNTIL, MlstAdapter
from arva_tools.registry import detect
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Assembly,
    DatabaseOrigin,
    DatabaseStatus,
    MlstResult,
    Project,
    ReferenceDatabase,
    Sample,
    VersionSource,
)
from app.services import database_detect as detection
from app.services import database_kinds as kinds
from app.services.annotation import _signature, assembly_record, contig_headers, synthetic_evidence
from app.services.metadata_table import sanitize_spreadsheet_cell
from app.services.performance import effective_resources
from app.storage import get_storage

BUNDLED_KEY = "mlst-bundled"
KIND = "mlst_schemes"
TERMS = {"open_until": PUBMLST_OPEN_UNTIL, "url": "https://pubmlst.org/terms-conditions", "updated": "2026-05-13"}
CSV_COLUMNS = ("project", "sample_code", "assembly_id", "assembly", "scheme", "st", "status", "score", "alleles",
               "clonal_complex", "warnings", "tool", "tool_version", "database", "database_checksum", "result_id",
               "created_at")


# The English texts of ARVA's MLST warnings; the interface has them as mlst.warning.<code>.
WARNINGS = {
    "no_scheme": "No scheme reached mlst's minimum score: the MLST type is not determined.",
    "novel_alleles": "{count, plural, one {# locus has} other {# loci have}} a novel full-length allele (~n: at least "
                     "the minimum identity to allele n, the first similar allele BLAST reported, not necessarily the "
                     "closest): {loci}",
    "partial_alleles": "{count, plural, one {# locus is} other {# loci are}} only partly matched (n?: at least the "
                       "minimum coverage of allele n): {loci}. The allele is not determined; the gene may be cut at a "
                       "contig end or hold an insertion or deletion.",
    "missing_alleles": "{count, plural, one {# locus was} other {# loci were}} not found: {loci}",
    "multiple_alleles": "{count, plural, one {# locus has} other {# loci have}} several exact alleles (n,m): {loci}. "
                        "The genome may hold several copies, or the sample a mixture of strains.",
    "null_alleles": "{count, plural, one {# locus is} other {# loci are}} 0, a locus the ST's profile leaves without "
                    "an allele: {loci}",
    "unrecognised_alleles": "{count, plural, one {# locus has} other {# loci have}} a call ARVA does not recognise: "
                            "{loci}",
    "st_not_assigned": "The allele combination is not a known ST of the scheme: ST not assigned.",
    "tied_schemes": "Several schemes reached the same best score ({score}): {schemes}. mlst reports one of them in "
                    "an arbitrary order; check the species, and whether the sample is mixed.",
    "scheme_forced": "The scheme {scheme} was chosen, not detected; mlst then uses minimum score 0.",
    "scheme_after_open_terms": "The scheme {scheme} was last updated on {last_updated}, after 31 December 2024: under "
                               "PubMLST's terms, data submitted from 1 January 2025 may be used only for non-commercial "
                               "academic research or public health surveillance, and not redistributed.",
    "synthetic_input": "SYNTHETIC input ({evidence}): this result describes the tools on test data, not biology.",
}


def warning_text(w: dict[str, Any]) -> str:
    from app.core.messages import render

    return render(WARNINGS[w["code"]], w.get("params") or {}) if w["code"] in WARNINGS else w["code"]


class InputError(ValueError):
    """The assembly or options cannot be used as requested (HTTP 400)."""


@lru_cache(maxsize=4)
def _manifest(path: str, signature: tuple) -> tuple[tuple[dict, ...], str]:
    from app.tasks.databases import build_manifest, manifest_checksum

    manifest = build_manifest(Path(path), lambda _done, _total: None)
    return tuple(manifest), manifest_checksum(manifest)


def content_checksum(folder: Path) -> str:
    """ARVA's checksum of every file of the folder (cached while no file changes size or modification time)."""
    return _manifest(str(folder), _signature(folder))[1]


def bundled_database(db: Session, executable: str, tool_version: str | None) -> ReferenceDatabase | None:
    """The schemes bundled with this mlst as a database record, created (or recorded again when their files changed)
    with the SHA-256 of every file; None when mlst's folder holds no complete database."""
    from app.services.databases import _stored_detection, append_log, ensure_default, now

    folder = mlst_tool.database_dir(executable)
    found = next((d for d in detection.detect(folder) if d.kind == KIND), None) if folder.is_dir() else None
    if found is None or not found.ok or found.version is None:
        return None
    manifest, checksum = _manifest(str(folder), _signature(folder))
    record = db.scalar(select(ReferenceDatabase).where(ReferenceDatabase.path == str(folder)))
    if record is not None and record.checksum == checksum and record.status is DatabaseStatus.registered:
        return record
    stamp = now()
    k = kinds.BY_KEY[KIND]
    if record is None:
        record = ReferenceDatabase(key=BUNDLED_KEY, kind=KIND, path=str(folder), origin=DatabaseOrigin.bundled,
                                   installed_at=stamp, log_text="")
        db.add(record)
        append_log(record, f"Found the PubMLST schemes bundled with mlst {tool_version} in {folder}; ARVA reads them "
                           "there and never changes, updates or deletes them")
    else:
        append_log(record, "The bundled files are not the ones recorded (was mlst's environment rebuilt?); recorded "
                           "them again")
    info = found.facts["mlst"]
    record.name = f"PubMLST schemes bundled with mlst {tool_version}"
    record.version, record.version_source = found.version, VersionSource.file
    record.status, record.verification_level, record.verified_at = DatabaseStatus.registered, "full", stamp
    record.checksum, record.manifest = checksum, list(manifest)
    record.size_bytes = sum(m.get("size", 0) for m in manifest)
    record.source_url, record.licence = k.source_url, k.licence
    record.error_message = record.error_detail = None
    record.details = {"detection": _stored_detection(found), "mlst": info, "tool_version": tool_version,
                      "terms": TERMS}
    append_log(record, f"{info['scheme_count']} schemes downloaded {found.version} (db/VERSION.txt "
                       f"{info['version_txt'] or 'absent'}, BLAST index built {info['blast_last_updated']}); "
                       f"content checksum {checksum}")
    db.flush()
    ensure_default(db, KIND)
    db.commit()
    db.refresh(record)
    return record


def refresh_bundled(db: Session) -> None:
    """Record the bundled schemes when mlst is installed (the Database Manager lists them)."""
    d = detect("mlst")
    if d.status is ToolStatus.available and d.path:
        bundled_database(db, d.path, d.version)


def database_summary(record: ReferenceDatabase) -> dict[str, Any]:
    info = (record.details or {}).get("mlst") or {}
    return {"id": record.id, "name": record.name, "version": record.version, "checksum": record.checksum,
            "path": record.path, "version_txt": info.get("version_txt"), "download_dates": info.get("download_dates"),
            "blast_last_updated": info.get("blast_last_updated"), "scheme_count": info.get("scheme_count"),
            "sources": info.get("sources") or {}, "authenticated": info.get("authenticated") or [],
            "updated_after_open_terms": info.get("updated_after_open_terms") or [],
            "without_update_date": info.get("without_update_date") or [], "terms": TERMS}


def schemes(record: ReferenceDatabase) -> list[dict[str, Any]]:
    info = mlst_tool.database_info(Path(record.path or ""))
    return [{"name": s["name"], "loci": s["loci"], "source": s["source"], "download_date": s["download_date"],
             "last_updated": s["last_updated"],
             "clonal_complex": any(c in s["extra_columns"] for c in mlst_tool.CC_COLUMNS)} for s in info["schemes"]]


def assembly_for(db: Session, assembly_id: str) -> Assembly:
    a = db.get(Assembly, assembly_id)
    if a is None:
        raise LookupError(assembly_id)
    if not get_storage().resolve(a.contigs_path).is_file():
        raise InputError("The contigs file of this assembly is missing on disk")
    return a


def assembly_facts(db: Session, a: Assembly) -> dict[str, Any]:
    headers = contig_headers(get_storage().resolve(a.contigs_path))
    return {**assembly_record(a), "created_at": a.created_at, "contigs": len(headers),
            "total_length": a.stats.get("total_length"), "synthetic_evidence": synthetic_evidence(db, a, headers)}


def _tool(db: Session) -> dict[str, Any]:
    d = detect("mlst", refresh=True)
    res = effective_resources(db)
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "reason_params": d.reason_params, "path": d.path,
            "license": d.info.license, "citation": d.info.citation, "citation_url": d.info.citation_url,
            "max_threads": res.max_threads, "default_threads": res.threads}


def plan(db: Session, sample: Sample, a: Assembly, scheme: str | None) -> dict[str, Any]:
    """What an mlst run of this assembly would do here: mlst, its bundled schemes (date, terms, scheme list), the
    options with mlst's defaults (as its --help states them) and the assembly. Only version and help checks run."""
    tool = _tool(db)
    problems: list[dict[str, Any]] = []
    database, scheme_list, tool_defaults = None, [], {}
    if tool["status"] == ToolStatus.available.value and tool["path"]:
        record = bundled_database(db, tool["path"], tool["version"])
        if record is None:
            problems.append({"code": "no_database", "params": {"path": str(mlst_tool.database_dir(tool["path"]))},
                             "message": "mlst's bundled database was not found next to mlst"})
        else:
            database, scheme_list = database_summary(record), schemes(record)
        try:
            tool_defaults = mlst_tool.help_defaults(MlstAdapter.help_text(tool["path"]))
        except (OSError, RuntimeError) as exc:
            problems.append({"code": "help_unreadable", "params": {"detail": str(exc)},
                             "message": f"mlst's --help could not be read: {exc}"})
    else:
        problems.append({"code": "tool_unavailable", "params": {"status": tool["status"]},
                         "message": f"mlst is not available ({tool['status']}): {tool['message']}"})
    if scheme is not None and scheme_list and scheme not in {s["name"] for s in scheme_list}:
        problems.append({"code": "unknown_scheme", "params": {"scheme": scheme},
                         "message": f"mlst's bundled database has no scheme {scheme}"})
    return {"tool": tool, "database": database, "schemes": scheme_list, "defaults": DEFAULTS,
            "tool_defaults": tool_defaults, "defaults_match": tool_defaults == DEFAULTS if tool_defaults else None,
            "assembly": assembly_facts(db, a), "scheme": scheme, "problems": problems}


def mlst_database(db: Session, record_id: str | None) -> ReferenceDatabase:
    record = db.get(ReferenceDatabase, record_id) if record_id else None
    if record is None:
        raise InputError("mlst's bundled database is not recorded")
    return record


def _alleles_text(alleles: list[dict[str, Any]]) -> str:
    return " ".join(f"{a['locus']}({a['call']})" for a in alleles)


def _cc_text(cc: dict[str, Any]) -> str:
    if not cc.get("available"):
        return "not available from the scheme"
    return cc.get("value") or "none for this ST"


def _rows(db: Session, project_ids: list[str] | None) -> list[tuple[MlstResult, Sample, Project, Assembly]]:
    q = (select(MlstResult, Sample, Project, Assembly).join(Sample, Sample.id == MlstResult.sample_id)
         .join(Project, Project.id == Sample.project_id).join(Assembly, Assembly.id == MlstResult.assembly_id))
    if project_ids is not None:
        q = q.where(Sample.project_id.in_(project_ids))
    return list(db.execute(q.order_by(MlstResult.created_at.desc())).all())


def _row(m: MlstResult, sample: Sample, project: Project, a: Assembly) -> dict[str, Any]:
    return {"id": m.id, "sample_id": sample.id, "sample_code": sample.sample_code, "project_id": project.id,
            "project_name": project.name, "is_demo": project.is_demo, "assembly_id": a.id, "assembler": a.assembler,
            "assembler_version": a.assembler_version, "assembly_kind": a.kind.value, "scheme": m.scheme, "st": m.st,
            "status": m.status, "score": m.score, "alleles": m.alleles, "clonal_complex": m.clonal_complex,
            "warnings": m.warnings, "tool": m.tool, "tool_version": m.tool_version,
            "database_name": m.database_name, "database_version": m.database_version,
            "database_checksum": m.database_checksum, "created_at": m.created_at}


def project_overview(db: Session, project: Project) -> dict[str, Any]:
    """Every sample of the project with its most recent MLST result (and how many it has), and the STs found."""
    rows = _rows(db, [project.id])
    latest: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for m, sample, proj, a in rows:
        counts[sample.id] = counts.get(sample.id, 0) + 1
        latest.setdefault(sample.id, _row(m, sample, proj, a))
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    types: dict[tuple[str | None, str | None], int] = {}
    for r in latest.values():
        types[(r["scheme"], r["st"])] = types.get((r["scheme"], r["st"]), 0) + 1
    return {
        "project_id": project.id, "project_name": project.name, "is_demo": project.is_demo,
        "samples": [{"sample_id": s.id, "sample_code": s.sample_code, "results": counts.get(s.id, 0),
                     "latest": latest.get(s.id)} for s in samples],
        "sequence_types": [{"scheme": k[0], "st": k[1], "samples": n}
                           for k, n in sorted(types.items(), key=lambda kv: (-kv[1], str(kv[0])))],
    }


def overview(db: Session, limit: int) -> dict[str, Any]:
    """Every project with how many of its samples have an MLST result, and the most recent results."""
    projects = list(db.scalars(select(Project).order_by(Project.name)))
    sample_counts = dict(db.execute(select(Sample.project_id, func.count()).group_by(Sample.project_id)).all())
    rows = _rows(db, None)
    typed: dict[str, set[str]] = {}
    for _m, sample, proj, _a in rows:
        typed.setdefault(proj.id, set()).add(sample.id)
    return {
        "projects": [{"project_id": p.id, "project_name": p.name, "is_demo": p.is_demo,
                      "samples": sample_counts.get(p.id, 0), "typed_samples": len(typed.get(p.id, set()))}
                     for p in projects],
        "recent": [_row(*r) for r in rows[:limit]],
        "total_results": len(rows),
    }


def project_csv(db: Session, project: Project) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for m, sample, proj, a in _rows(db, [project.id]):
        writer.writerow({
            "project": sanitize_spreadsheet_cell(proj.name), "sample_code": sanitize_spreadsheet_cell(sample.sample_code),
            "assembly_id": a.id, "assembly": sanitize_spreadsheet_cell(f"{a.assembler} {a.assembler_version} "
                                                                       f"({a.kind.value})"),
            "scheme": m.scheme or "-", "st": m.st or "-", "status": m.status, "score": m.score,
            "alleles": sanitize_spreadsheet_cell(_alleles_text(m.alleles)),
            "clonal_complex": sanitize_spreadsheet_cell(_cc_text(m.clonal_complex)),
            "warnings": "; ".join(w["code"] for w in m.warnings), "tool": m.tool, "tool_version": m.tool_version,
            "database": sanitize_spreadsheet_cell(f"{m.database_name or ''} {m.database_version or ''}".strip()),
            "database_checksum": m.database_checksum or "", "result_id": m.id, "created_at": m.created_at.isoformat(),
        })
    return out.getvalue()


def download_name(sample: Sample, m: MlstResult, suffix: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in sample.sample_code)
    return f"ARVA_{safe}_mlst_{m.id[:8]}.{suffix}"
