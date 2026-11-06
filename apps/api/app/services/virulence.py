"""Virulence-factor genes: ABRicate's screen of an assembly against a VFDB (its bundled core set A, the default, or a
full set B the Database Manager built or registered: app.services.vfdb_db), and the view that puts those hits next to
the virulence genes AMRFinderPlus reported with --plus, each row with its source.

VFDB's core dataset (set A) holds genes of experimentally verified virulence factors only; the full dataset (set B)
also genes of predicted ones, so it finds more genes (e.g. the egc enterotoxin cluster seg/sei/selm/seln/selo of
S. aureus N315, absent from set A) and more that are not true virulence factors. Each run records which set and
version it searched.

The two sources are never merged into one call: they search different references with different methods
(AMRFinderPlus: NCBI's curated proteins, translated search; ABRicate: VFDB's nucleotide sequences, blastn), so a
gene can be found by one and not the other. Where a VFDB hit and an AMRFinderPlus hit overlap on a contig, each row
names the other. A hit is sequence similarity to a known virulence-factor gene, never evidence that the isolate is
virulent. VFDB's licence (CC BY-NC 4.0) and citation are shown as the vfdb kind states them (database_kinds.py).
"""
from __future__ import annotations

import re
from pathlib import Path
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
from app.services import abricate_db, vfdb_db
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
    # Recorded by runs before VFDB's terms of use were read (2026-11-06); they state CC BY-NC 4.0.
    "vfdb_terms_unstated": "VFDB's data are licensed CC BY-NC 4.0 (non-commercial use; VFDB's terms of use); cite "
                           "VFDB when you publish.",
    "vfdb_terms": "VFDB's data are licensed CC BY-NC 4.0 (non-commercial research or academic use; commercial use only "
                  "with VFDB's permission); cite VFDB ({citation}) when you publish.",
    "vfdb_core": "Searched {name} {version}: VFDB's core dataset (set A), genes of experimentally verified virulence "
                 "factors only.",
    "vfdb_full": "Searched {name} {version}: VFDB's full dataset (set B), which adds genes of predicted virulence "
                 "factors, so it finds more genes than the core set A, and more that are not true virulence factors.",
    "vfdb_raw_names": "This VFDB keeps VFDB's own sequence names, so each gene is reported by its VFDB identifier "
                      "(VFG...), not by the gene's name.",
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


def options(db: Session) -> list[ReferenceDatabase]:
    """The VFDB databases ABRicate can search here (its bundled core set A, full set B folders), the default first."""
    abricate_db.refresh_bundled(db)
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == vfdb_db.KIND,
                                                      ReferenceDatabase.status.in_(dbs.USABLE))
                      .order_by(ReferenceDatabase.is_default.desc(), ReferenceDatabase.created_at))
    return [r for r in rows if vfdb_db.abricate_ready(r)]


def database(db: Session, database_id: str | None = None) -> ReferenceDatabase | None:
    """The VFDB a screen searches: the one chosen, else the default VFDB when ABRicate can search it, else ABRicate's
    bundled core set A."""
    found = options(db)
    if database_id:
        record = db.get(ReferenceDatabase, database_id)
        if record is None or record.kind != vfdb_db.KIND or not vfdb_db.abricate_ready(record):
            raise InputError("The chosen database is not a VFDB that ABRicate can search")
        return record
    usable = [r for r in found if dbs.availability(r)[0]]
    return next((r for r in usable if r.is_default), None) or \
        next((r for r in usable if r.key == abricate_db.KEYS["vfdb"]), None) or (usable[0] if usable else None)


def database_option(record: ReferenceDatabase) -> dict[str, Any]:
    out = database_summary(record)
    v = vfdb_db.provenance(record)
    return {**out, "vfdb_set": v["set"], "dataset": v["dataset"], "vfdb": v}


def plan(db: Session, sample: Sample, a: Assembly, database_id: str | None = None) -> dict[str, Any]:
    """What a VFDB screen of this assembly would do here: ABRicate, the VFDB it would search (set A core or B full,
    version, sequences, checksum, licence and citation) among those ABRicate can search, its defaults as --help states
    them and ARVA's, and what blocks the run."""
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
    record = database(db, database_id) if tool["path"] or database_id else None
    if tool["path"] and record is None:
        problems.append({"code": "no_database", "params": {"kind": "vfdb"},
                         "message": "ABRicate's bundled VFDB was not found next to ABRicate"})
    elif record is not None and not dbs.usable_now(record):
        problems.append({"code": "database_unavailable", "params": {"name": record.name},
                         "message": f"{record.name} cannot be used now ({record.status.value})"})
    elif record is not None and vfdb_db.variant(record) != "abricate" and (
            " " in (record.path or "") or not abr.database_name_ok(Path(record.path or "").name)):
        problems.append({"code": "database_path_spaces", "params": {"name": record.name},
                         "message": f"ABRicate cannot read {record.name}: BLAST splits a database path at its "
                                    "spaces, and ABRicate takes the folder's name as --db (letters, digits, . _ -); "
                                    "move or link it to a folder without spaces"})
    return {"tool": tool, "database": database_option(record) if record else None,
            "databases": [database_option(r) for r in options(db)] if tool["path"] else [],
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
            "database_terms": p.get("database_terms") or {}, "vfdb": vfdb_of(job),
            "warnings": rs.get("warnings") or [],
            "counts": rs.get("counts") or {}, "files": rs.get("files") or {}, "hits": hits}


def vfdb_of(job: AnalysisJob) -> dict[str, Any]:
    """The VFDB a screen searched: what it recorded (set, dataset, version, source, checksums), or for a run recorded
    before sets were chosen, ABRicate's bundled core set A (the only VFDB those runs could search)."""
    p = job.parameters or {}
    if p.get("vfdb"):
        return p["vfdb"]
    bundled = job.database_key == abricate_db.KEYS["vfdb"]
    return {"set": "A" if bundled else None, "dataset": "core" if bundled else None, "name": job.database_name,
            "version": job.database_version, "version_source": job.database_version_source, "bundled": bundled,
            "checksum": job.database_checksum}


def set_label(v: dict[str, Any], lang: str = "en") -> str:
    """'VFDB core (set A)' / 'VFDB full (set B)' (Spanish: 'VFDB básico (set A)' / 'VFDB completo (set B)'), with the
    version; the database's name when the set is not known."""
    names = {"en": {"A": "VFDB core (set A)", "B": "VFDB full (set B)"},
             "es": {"A": "VFDB básico (set A)", "B": "VFDB completo (set B)"}}
    label = names.get(lang, names["en"]).get(v.get("set") or "", v.get("name") or "VFDB")
    return f"{label} {v.get('version') or ''}".strip()


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


# A VFDB row is read as "probably the other gene" when an AMRFinderPlus row naming a different gene, with a higher
# identity, covers at least this share of the shorter of the two hits on the same contig. Seen on real data: VFDB
# reported lukF-PV (82.27 %) on the very region where AMRFinderPlus found lukD (94.19 %), and no lukS-PV: it was lukD.
SAME_REGION_SHARE = 0.5
# Below this coverage of its reference a hit is shown as truncated or interrupted (e.g. VFDB hlb 170-993/993).
PARTIAL_COVERAGE = 90.0

# English texts of the row flags (the interface has them as virulence.flag.<code>; the sample report uses these).
FLAGS = {
    "probable_other_gene": "probably {gene} ({source}, {identity} % identity); VFDB's best match may be a homologue",
    "partial_reference": "truncated or interrupted: only positions {ref_start}-{ref_end} of the {ref_length}-position "
                         "reference",
    "partial_coverage": "truncated or interrupted: covers only {coverage} % of the reference",
}


def flag_text(flag: dict[str, Any]) -> str:
    from app.core.messages import render

    if flag["code"] not in FLAGS:
        return flag["code"]
    params = {k: f"{v:.2f}" if isinstance(v, float) else v for k, v in (flag.get("params") or {}).items()}
    return render(FLAGS[flag["code"]], params)


# Staphylococcal enterotoxin-like genes: VFDB names them sel<x> (selm, seln, selo, selp, selu2...) where other
# catalogues may write se<x> (sem, sen, seo, sep...); both spellings name the same gene here.
_SE_LIKE = re.compile(r"^sel([a-z]\d*)$")


def _gene_keys(name: str | None) -> set[str]:
    """A symbol's spellings to compare: the whole symbol and each "/" part, lower case, letters and digits only; an
    enterotoxin-like sel<x> also as se<x>."""
    key = lambda s: "".join(c for c in s.lower() if c.isalnum())  # noqa: E731
    keys = {k for k in [key(name or ""), *(key(p) for p in (name or "").split("/"))] if k}
    return keys | {f"se{m.group(1)}" for k in keys if (m := _SE_LIKE.match(k))}


def _same_gene(a: str | None, b: str | None) -> bool:
    """Whether two sources' symbols name the same gene, spelling aside ("lukF-PV"/"lukFPV", "hly/hla"/"hla")."""
    return bool(_gene_keys(a) & _gene_keys(b))


def _shared_share(a: dict[str, Any], b: dict[str, Any]) -> float:
    """The overlap of two hits on the same contig as a share of the shorter one (0 when apart or unplaced)."""
    if a["contig"] != b["contig"] or None in (a["start"], a["end"], b["start"], b["end"]):
        return 0.0
    shared = min(a["end"], b["end"]) - max(a["start"], b["start"]) + 1
    shorter = min(a["end"] - a["start"] + 1, b["end"] - b["start"] + 1)
    return shared / shorter if shared > 0 and shorter > 0 else 0.0


def row_flags(rows: list[dict[str, Any]]) -> None:
    """Adds `flags` (codes with values, never a verdict) to each row of the combined view:

    - probable_other_gene (VFDB rows): an AMRFinderPlus row on the same region (overlap >= half of the shorter hit)
      names a different gene with a higher identity, so VFDB's best match may be a homologue of that gene;
    - partial_reference / partial_coverage: the hit covers less than 90 % of its reference (VFDB gives the
      reference positions; AMRFinderPlus only the percentage). It says truncated or interrupted, not why.
    """
    for x in rows:
        flags: list[dict[str, Any]] = []
        if x["source"] == "vfdb" and x["identity"] is not None:
            better = [y for y in rows if y["source"] == "amrfinderplus" and y["identity"] is not None
                      and y["identity"] > x["identity"] and not _same_gene(x["gene"], y["gene"])
                      and _shared_share(x, y) >= SAME_REGION_SHARE]
            if better:
                y = max(better, key=lambda r: r["identity"])
                flags.append({"code": "probable_other_gene",
                              "params": {"gene": y["gene"], "source": "AMRFinderPlus", "identity": y["identity"]}})
        if x["coverage"] is not None and x["coverage"] < PARTIAL_COVERAGE:
            if x.get("ref_start") is not None and x.get("ref_end") is not None and x.get("ref_length"):
                flags.append({"code": "partial_reference",
                              "params": {"ref_start": x["ref_start"], "ref_end": x["ref_end"],
                                         "ref_length": x["ref_length"], "coverage": x["coverage"]}})
            else:
                flags.append({"code": "partial_coverage", "params": {"coverage": x["coverage"]}})
        x["flags"] = flags


def _source_rows(db: Session, vf_job: AnalysisJob | None, amr_job: AnalysisJob | None) -> list[dict[str, Any]]:
    """The rows of the combined view: the VFDB screen's hits and the AMRFinderPlus run's VIRULENCE rows (pass a run
    with --plus, or None)."""
    rows: list[dict[str, Any]] = []
    if vf_job is not None:
        for r in db.scalars(select(VirulenceResult).where(VirulenceResult.job_id == vf_job.id)):
            rows.append({"source": "vfdb", "gene": r.gene, "contig": r.contig, "start": r.start, "end": r.end,
                         "strand": r.strand, "identity": r.identity, "coverage": r.coverage, "kind": r.hit_kind,
                         "method": "blastn", "description": r.product, "vf_name": r.vf_name, "vf_id": r.vf_id,
                         "vf_category": r.vf_category, "reference": r.accession, "pieces": r.pieces, "id": r.id,
                         "ref_start": r.ref_start, "ref_end": r.ref_end, "ref_length": r.ref_length})
    if amr_job is not None:
        for r in db.scalars(select(AmrResult).where(AmrResult.job_id == amr_job.id, AmrResult.type == "VIRULENCE")):
            rows.append({"source": "amrfinderplus", "gene": r.element_symbol, "contig": r.assembly_contig or r.contig,
                         "start": r.start, "end": r.stop, "strand": r.strand, "identity": r.identity,
                         "coverage": r.coverage, "kind": r.method_kind, "method": r.method,
                         "description": r.element_name, "vf_name": None, "vf_id": None, "vf_category": r.subtype,
                         "reference": r.closest_accession, "pieces": None, "id": r.id,
                         # AMRFinderPlus gives no reference positions, and its reference length is in amino acids
                         # for protein and translated searches: only its coverage is used.
                         "ref_start": None, "ref_end": None, "ref_length": None})
    return rows


def vfdb_genes(db: Session, vf_job: AnalysisJob) -> dict[str, Any]:
    """The genes of one VFDB screen as reports and tables list them, read as the combined view reads them: a hit the
    view flags probable_other_gene (on the region where AMRFinderPlus, in the assembly's most recent run with --plus,
    found a different gene with a higher identity) is listed apart as a cross-hit, with that gene, never dropped.

    `genes`: genes with at least one hit that is not a cross-hit; `cross_hits`: one entry per VFDB gene and gene
    AMRFinderPlus names (e.g. VFDB lukF-PV on the region of AMRFinderPlus lukD, which is not PVL), with both
    identities and the hits' places; `hits`: every VFDB hit; `amr_job_id`: the AMRFinderPlus run compared (None:
    no run with --plus, so nothing is set apart)."""
    aid = ((vf_job.parameters or {}).get("assembly") or {}).get("assembly_id")
    amr_job = latest_amr_run(db, aid) if aid else None
    if amr_job is not None and not (amr_job.parameters or {}).get("plus"):
        amr_job = None
    rows = _source_rows(db, vf_job, amr_job)
    row_flags(rows)
    vf = [x for x in rows if x["source"] == "vfdb"]
    crossed: dict[tuple[str, str], dict[str, Any]] = {}
    plain: set[str] = set()
    for x in sorted(vf, key=lambda r: (r["contig"] or "", r["start"] or 0)):
        flag = next((f for f in x["flags"] if f["code"] == "probable_other_gene"), None)
        if flag is None:
            plain.add(x["gene"])
            continue
        other = flag["params"]["gene"]
        c = crossed.setdefault((x["gene"], other), {"gene": x["gene"], "probable_gene": other,
                                                    "source": flag["params"]["source"], "identity": x["identity"],
                                                    "other_identity": flag["params"]["identity"], "places": []})
        c["places"].append(f"{x['contig']}:{x['start']}-{x['end']}")
    return {"genes": sorted(plain), "cross_hits": sorted(crossed.values(), key=lambda c: (c["gene"], c["probable_gene"])),
            "hits": len(vf), "amr_job_id": amr_job.id if amr_job else None}


def cross_hit_text(c: dict[str, Any], lang: str = "en") -> str:
    """A cross-hit in a list of genes: "lukF-PV (probably lukD, AMRFinderPlus)"."""
    word = "probablemente" if lang == "es" else "probably"
    return f"{c['gene']} ({word} {c['probable_gene']}, {c['source']})"


def merged(db: Session, a: Assembly) -> dict[str, Any]:
    """The assembly's most recent VFDB screen and most recent AMRFinderPlus run side by side: one list of rows, each
    with its source, sorted by position; `also_found_by` names the other source's overlapping rows. A source that was
    not run (or AMRFinderPlus without --plus, which does not search virulence genes) is 'not_searched'."""
    vf_job = latest_run(db, a.id, a.sample_id)
    amr_job = latest_amr_run(db, a.id)
    amr_plus = bool((amr_job.parameters or {}).get("plus")) if amr_job else False
    rows = _source_rows(db, vf_job, amr_job if amr_plus else None)
    rows.sort(key=lambda x: (x["contig"] or "", x["start"] or 0, x["source"]))
    for x in rows:
        x["also_found_by"] = sorted({f"{y['source']}:{y['gene']}" for y in rows
                                     if y["source"] != x["source"] and _overlap(x, y)})
    row_flags(rows)
    v = vfdb_of(vf_job) if vf_job else {}
    status = {"vfdb": {"status": "searched" if vf_job else "not_searched", "job_id": vf_job.id if vf_job else None,
                       "tool": vf_job.tool_name if vf_job else None,
                       "tool_version": vf_job.tool_version if vf_job else None,
                       "database_version": vf_job.database_version if vf_job else None,
                       "database_name": vf_job.database_name if vf_job else None,
                       "vfdb_set": v.get("set"), "dataset": v.get("dataset"),
                       "hits": sum(1 for x in rows if x["source"] == "vfdb")},
              "amrfinderplus": {"status": "searched" if amr_plus else ("plus_off" if amr_job else "not_searched"),
                                "job_id": amr_job.id if amr_job else None,
                                "tool": amr_job.tool_name if amr_job else None,
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
    v = vfdb_of(job)
    return {"run": {"job_id": job.id, "tool_version": job.tool_version, "database_version": job.database_version,
                    "database_name": job.database_name, "vfdb_set": v.get("set"), "created_at": job.created_at},
            "hits": out}


def download_name(sample: Sample, job: AnalysisJob, suffix: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in sample.sample_code)
    return f"ARVA_{safe}_vfdb_{job.id[:8]}.{suffix}"
