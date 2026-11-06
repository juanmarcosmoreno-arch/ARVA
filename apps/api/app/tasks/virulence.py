"""Worker task for the VFDB screen with ABRicate.

Before the run the worker checks again what the user confirmed: the assembly's contigs and the VFDB (ABRicate's
bundled core set A: the same folder next to the ABRicate that runs, the same content checksum; a VFDB folder in
ABRicate's format, such as a full set B: the same record, version, folder and content checksum, with `sequences` and
its BLAST index present). ABRicate is run with --datadir <the folder's parent> --db <the folder's name>. The contigs
are staged as
input/contigs.fna; ABRicate's report (its standard output), its log and the input stay in the job's results folder.
Each hit becomes one virulence_results row with ARVA's reading of its coordinates (complete, with gaps, partial, at a
contig end, in pieces) and VFDB's factor, category and organism from the sequence description.
"""
from __future__ import annotations

from pathlib import Path

from arva_tools import abricate as abr
from arva_tools.base import help_options

from app.models import Assembly, ReferenceDatabase, VirulenceResult
from app.services import abricate_db, vfdb_db
from app.services import annotation as annotation_svc
from app.services import database_detect as detection
from app.tasks.annotation import _assembly
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.mobile_elements import INPUT, _argv, _bundled_folder, _read, _record, _run_tool
from app.tasks.tools import _rel, _resolve_tool, _sha256


def _body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "abricate")
    p = ctx.job.parameters or {}
    params = abr.AbricateParams(**{k: v for k, v in (p.get("settings") or {}).items()
                                   if k in abr.AbricateParams.__dataclass_fields__})
    datadir = _vfdb_datadir(ctx, exe, params)
    a: Assembly = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    (results / "input").mkdir(parents=True)
    contigs = results / "input" / INPUT
    staged = annotation_svc.stage_genome(ctx.path(a.contigs_path), contigs, False)
    ctx.log(f"Input: {len(staged['contigs'])} contigs, {staged['total_length']:,} bp, written as input/{INPUT} "
            f"(sha256 {staged['sha256']})")
    report = results / abr.OUTPUTS["report"]
    argv = _argv("plasmidfinder", lambda: abr.AbricateAdapter.argv(exe, params, contigs, datadir,
                                                                    help_options(abr.AbricateAdapter.help_text(exe))))
    _run_tool(ctx, "plasmidfinder", argv, results, abr.OUTPUTS["log"], stdout=report, env=abr.env_for(exe))
    rows = abr.classify(_read("plasmidfinder", report, abr.parse_report), {c["name"]: c["length"]
                                                                          for c in staged["contigs"]})
    job = ctx.job
    for r in rows:
        vf = abr.parse_vfdb_product(r["product"])
        ctx.db.add(VirulenceResult(
            sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, source="vfdb", gene=r["gene"],
            contig=r["contig"], start=r["start"], end=r["end"], strand=r["strand"], identity=r["identity"],
            coverage=r["coverage"], ref_start=r["ref_start"], ref_end=r["ref_end"], ref_length=r["ref_length"],
            gap_openings=r["gap_openings"], gap_positions=r["gap_positions"], coverage_map=r["coverage_map"],
            accession=r["accession"], product=vf["description"], vf_name=vf["vf_name"], vf_id=vf["vf_id"],
            vf_category=vf["vf_category"], vfc_id=vf["vfc_id"], organism=vf["organism"], hit_kind=r["hit_kind"],
            pieces=r["pieces"]))
    warnings = abr.warnings(params, rows, "vfdb")
    warnings.append({"code": "split_may_be_missed", "params": {"mincov": f"{params.mincov:g}"}})
    v = p.get("vfdb") or {}
    if v.get("set") in ("A", "B"):
        warnings.append({"code": "vfdb_core" if v["set"] == "A" else "vfdb_full",
                         "params": {"name": job.database_name or "VFDB", "version": job.database_version or "?"}})
    if record_style(ctx) == "vfdb":
        warnings.append({"code": "vfdb_raw_names", "params": {}})
    warnings.append({"code": "vfdb_terms", "params": {"citation": (p.get("database_terms") or {}).get("citation")
                                                      or "VFDB"}})
    if evidence := p.get("synthetic_evidence"):
        warnings.append({"code": "synthetic_input", "params": {"evidence": ", ".join(evidence)}})
    log = abr.parse_stderr((results / abr.OUTPUTS["log"]).read_text(errors="replace"))
    files = {k: {"path": _rel(ctx, f), "sha256": _sha256(f), "size_bytes": f.stat().st_size}
             for k, f in (("report", report), ("log", results / abr.OUTPUTS["log"]), ("input", contigs)) if f.is_file()}
    counts = {"hits": len(rows), "genes": len({r["gene"] for r in rows}),
              "incomplete": sum(1 for r in rows if r["hit_kind"] in ("partial", "contig_end")),
              "categories": sorted({c for c in (abr.parse_vfdb_product(r["product"])["vf_category"] for r in rows) if c})}
    ctx.log(f"ABRicate ({job.database_name} {job.database_version}, set {v.get('set') or '?'}: {log['sequences']} "
            f"sequences, index {log['date']}): {counts['hits']} hits, "
            f"{counts['genes']} genes, {counts['incomplete']} partial or at a contig end")
    job.result_summary = {"counts": counts, "warnings": warnings, "files": files, "log": log}
    job.output_paths = [f["path"] for f in files.values()]


def record_style(ctx: JobContext) -> str | None:
    record = ctx.db.get(ReferenceDatabase, ctx.job.reference_database_id) if ctx.job.reference_database_id else None
    facts = (((record.details or {}).get("detection") or {}).get("facts") or {}) if record else {}
    return (facts.get("abricate") or {}).get("header_style")


def _vfdb_datadir(ctx: JobContext, exe: str, params: abr.AbricateParams) -> Path:
    """The --datadir of the confirmed VFDB: ABRicate's own db/ for its bundled copy; else the parent of the VFDB
    folder, whose name is --db, after checking the record, its files and its content checksum again."""
    record = _record(ctx)
    if vfdb_db.variant(record) == "abricate":
        return _bundled_folder(ctx, exe, "vfdb")
    folder = Path(record.path or "")
    if folder.name != params.database:
        raise JobFailure(f"{record.name} is in {folder}, not in a folder named {params.database}", "database_changed",
                         name=str(record.name))
    found = detection.quick_check(record.kind, folder, (record.details or {}).get("detection") or {})
    if found is None or not found.ok or found.facts["quick"]["changed"] or found.facts["quick"]["missing"]:
        raise JobFailure(f"{record.name}'s files are not the ones recorded (sequences and its BLAST index); verify it "
                         "in the Database Manager", "database_changed", name=str(record.name))
    checksum = abricate_db.content_checksum(folder)
    if record.checksum and checksum != record.checksum:
        raise JobFailure(f"{record.name}'s content checksum is not the recorded {record.checksum}", "database_changed",
                         name=str(record.name))
    if not record.checksum:
        # A registered folder whose full checksum was not asked for: the run records the checksum of what it searched.
        ctx.job.database_checksum = checksum
        ctx.job.parameters = {**(ctx.job.parameters or {}),
                              "vfdb": {**((ctx.job.parameters or {}).get("vfdb") or {}), "checksum": checksum}}
        ctx.log(f"{record.name} has no recorded content checksum (quick verification only); this run searched content "
                f"checksum {checksum}")
    ctx.log(f"VFDB folder {folder} (ABRicate --datadir {folder.parent} --db {folder.name})")
    return folder.parent


def run_virulence_job(job_id: str) -> str:
    return run_job(job_id, _body)
