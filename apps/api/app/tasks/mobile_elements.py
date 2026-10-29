"""Worker task for the plasmid and mobile-element searches (MOB-suite, PlasmidFinder through ABRicate, IntegronFinder,
ISEScan, geNomad).

Before the run the worker checks again what the user confirmed: the assembly's contigs, and the database (the same
record, version, content checksum and folder; for ABRicate's bundled PlasmidFinder the same folder next to the ABRicate
that runs; for IntegronFinder the same bundled models). The contigs are staged as input/contigs.fna (names kept,
descriptions removed). Outputs, logs and temporary files stay in the job's results folder. Each call the tool reports
becomes one mobile_element_results row with the tool's own values; the run's facts go to the job.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import abricate as abr
from arva_tools import genomad as gn
from arva_tools import integronfinder as itf
from arva_tools import isescan as ise
from arva_tools import mobsuite as mob
from arva_tools.base import help_options

from app.models import Assembly, MobileElementResult, ReferenceDatabase
from app.services import abricate_db
from app.services import annotation as annotation_svc
from app.services import mobile_elements as svc
from app.services.databases import USABLE
from app.tasks.annotation import _assembly
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.tools import _rel, _resolve_tool, _run, _sha256

ADAPTERS = {"mobsuite": mob.MobsuiteAdapter, "plasmidfinder": abr.AbricateAdapter,
            "integronfinder": itf.IntegronfinderAdapter, "isescan": ise.IsescanAdapter, "genomad": gn.GenomadAdapter}
FLAGS = {"mobsuite": mob.flags, "plasmidfinder": abr.flags, "integronfinder": itf.flags, "isescan": ise.flags,
         "genomad": gn.flags}
NAMES = {"mobsuite": "MOB-suite", "plasmidfinder": "ABRicate", "integronfinder": "IntegronFinder", "isescan": "ISEScan",
         "genomad": "geNomad"}
INPUT = "contigs.fna"
TMP_DIR = "tmp"


def _record(ctx: JobContext) -> ReferenceDatabase:
    job = ctx.job
    record = ctx.db.get(ReferenceDatabase, job.reference_database_id) if job.reference_database_id else None
    if record is None or record.status not in USABLE:
        raise JobFailure(f"The database {job.database_name} {job.database_version} is no longer installed",
                         "database_missing", name=str(job.database_name), version=str(job.database_version))
    if record.checksum != job.database_checksum or record.version != job.database_version \
            or record.path != job.database_path:
        raise JobFailure("The database's content checksum, version or folder changed since the run was confirmed; "
                         "start the search again", "database_changed", name=str(job.database_name))
    source = record.version_source.value if record.version_source else "unknown"
    ctx.log(f"Database: {record.name} {record.version} (version from {source}) at {record.path}, content checksum "
            f"{record.checksum or 'not computed (quick verification only)'}")
    return record


def _bundled_folder(ctx: JobContext, exe: str, name: str) -> Path:
    record = _record(ctx)
    folder = abr.datadir(exe) / name
    if record.path != str(folder) or abricate_db.content_checksum(folder) != ctx.job.database_checksum:
        raise JobFailure(f"ABRicate's bundled {name} database is not the recorded one (expected {record.path}, "
                         f"ABRicate now reads {folder})", "bundled_database_changed", name=str(record.name))
    return folder.parent


def _run_tool(ctx: JobContext, method: str, argv: list[str], workdir: Path, log: str, stdout: Path | None = None,
              env: dict[str, str] | None = None) -> None:
    try:
        _run(ctx, argv, workdir, log, stdout=stdout, extra_env=env)
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError):
            raise
        text = (workdir / log).read_text(errors="replace") if (workdir / log).is_file() else ""
        reason = ADAPTERS[method].failure_reason(text)
        if reason is None:
            raise
        raise JobFailure(reason, "tool_stopped", tool=NAMES[method], detail=reason) from None


def _argv(method: str, build) -> list[str]:
    try:
        return build()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"{NAMES[method]}'s --help could not be read to check its options: {exc}",
                         "help_unreadable", tool=NAMES[method], detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"{NAMES[method]} cannot run with these settings: {exc}", "settings_rejected",
                         tool=NAMES[method], detail=str(exc)) from exc


def _read(method: str, path: Path, parse):
    if not path.is_file():
        raise JobFailure(f"{NAMES[method]} exited without an error but did not write {path.name}", "outputs_missing",
                         tool=NAMES[method], files=path.name)
    try:
        return parse(path.read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"{NAMES[method]}'s output cannot be read: {exc}", "output_unreadable", tool=NAMES[method],
                         detail=str(exc)) from exc


def _mobsuite(ctx: JobContext, exe: str, params: mob.MobParams, contigs: Path, results: Path, add) -> dict[str, Any]:
    record = _record(ctx)
    db = Path(record.path or "")
    if not (state := mob.database_state(db))["ready"]:
        raise JobFailure(f"{record.name} lacks {', '.join(state['missing'][:6])}", "database_unprepared",
                         name=record.name, files=", ".join(state["missing"][:6]))
    tmp = results / TMP_DIR
    tmp.mkdir()
    argv = _argv("mobsuite", lambda: mob.MobsuiteAdapter.argv(exe, params, contigs, results, db,
                                                               mob.MobsuiteAdapter.help_options(exe)))
    try:
        _run_tool(ctx, "mobsuite", argv, results, mob.LOG, env=mob.env_for(exe, tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = results / mob.OUTDIR
    contig_rows = _read("mobsuite", out / mob.OUTPUTS["contig_report"], mob.parse_contig_report)
    typed = _read("mobsuite", out / mob.OUTPUTS["mobtyper"], mob.parse_mobtyper) \
        if (out / mob.OUTPUTS["mobtyper"]).is_file() else []
    mges = _read("mobsuite", out / mob.OUTPUTS["mge"], mob.parse_mge_report) if (out / mob.OUTPUTS["mge"]).is_file() \
        else []
    marks = _read("mobsuite", out / mob.OUTPUTS["biomarkers"], mob.parse_biomarkers) \
        if (out / mob.OUTPUTS["biomarkers"]).is_file() else []
    for c in contig_rows:
        add(category="contig", element=c["contig_id"], element_type=c["molecule_type"], contig=c["contig_id"],
            start=1, end=c["size"], details=c)
    for p in typed:
        members = [c["contig_id"] for c in contig_rows if c["primary_cluster_id"] == mob.plasmid_id(p)]
        add(category="plasmid", element=mob.plasmid_id(p), element_type=p["predicted_mobility"], contig=None,
            details={**p, "contigs": members})
    for m in marks:
        add(category="biomarker", element=m["name"], element_type=m["biomarker"], contig=m["contig"],
            start=m["start"], end=m["end"], strand=m["strand"], identity=m["identity"], coverage=m["coverage"],
            score=m["evalue"], details=m)
    for g in mges:
        add(category="mge", element=g["mge_type"], element_type=g["mge_subtype"], contig=g["contig_id"],
            start=g["contig_start"], end=g["contig_end"], identity=g["pident"], coverage=g["qcovhsp"],
            details=g)
    return {"counts": {**mob.summarise(contig_rows, typed), "biomarkers": len(marks), "repetitive_elements": len(mges)},
            "warnings": mob.warnings(contig_rows, typed), "files": [out / n for n in mob.OUTPUTS.values()]
            + list(out.glob("plasmid_*.fasta"))}


def _plasmidfinder(ctx: JobContext, exe: str, params: abr.AbricateParams, contigs: Path, results: Path, add,
                   lengths: dict[str, int]) -> dict[str, Any]:
    datadir = _bundled_folder(ctx, exe, "plasmidfinder")
    report = results / abr.OUTPUTS["report"]
    argv = _argv("plasmidfinder", lambda: abr.AbricateAdapter.argv(exe, params, contigs, datadir,
                                                                    help_options(abr.AbricateAdapter.help_text(exe))))
    _run_tool(ctx, "plasmidfinder", argv, results, abr.OUTPUTS["log"], stdout=report, env=abr.env_for(exe))
    rows = abr.classify(_read("plasmidfinder", report, abr.parse_report), lengths)
    for r in rows:
        add(category="replicon", element=r["gene"], element_type=abr.replicon_type(r["gene"]), contig=r["contig"],
            start=r["start"], end=r["end"], strand=r["strand"], identity=r["identity"], coverage=r["coverage"],
            completeness=r["hit_kind"], details={k: r[k] for k in ("accession", "coverage_range", "coverage_map",
                                                                   "gaps", "ref_start", "ref_end", "ref_length",
                                                                   "pieces", "product")})
    log = abr.parse_stderr((results / abr.OUTPUTS["log"]).read_text(errors="replace"))
    warnings = abr.warnings(params, rows)
    return {"counts": {"replicons": len(rows), "contigs_with_replicons": len({r["contig"] for r in rows}),
                       "types": sorted({abr.replicon_type(r["gene"]) for r in rows})},
            "warnings": warnings, "files": [report, results / abr.OUTPUTS["log"]], "log": log}


def _integronfinder(ctx: JobContext, exe: str, params: itf.IntegronParams, contigs: Path, results: Path, add,
                    circular: dict[str, bool | None]) -> dict[str, Any]:
    models = svc.bundled_models("integronfinder", exe)
    if models is None or models["checksum"] != ctx.job.database_checksum:
        raise JobFailure("IntegronFinder's bundled models are not the recorded ones (was its environment rebuilt?)",
                         "bundled_database_changed", name="IntegronFinder bundled models")
    topology = results / itf.TOPOLOGY
    topology.write_text(itf.topology_text(circular))
    ctx.log("Topology: " + ", ".join(f"{k} {'circular' if v else 'linear'}" for k, v in circular.items())
            + " (the assembler's circularity; linear when it did not report one)")
    argv = _argv("integronfinder", lambda: itf.IntegronfinderAdapter.argv(
        exe, params, contigs, results, topology, itf.IntegronfinderAdapter.help_options(exe)))
    _run_tool(ctx, "integronfinder", argv, results, itf.LOG, env=itf.env_for(exe))
    files = itf.outputs(results)
    found = itf.integrons(_read("integronfinder", files["integrons"], itf.parse_integrons))
    for i in found:
        add(category="integron", element=i["integron"], element_type=i["type"], contig=i["replicon"], start=i["start"],
            end=i["end"], strand=i["strand"], completeness=i["type"],
            details={k: i[k] for k in ("attc_sites", "integrase", "topology", "cassette_proteins", "elements")})
    counts = {t: sum(1 for i in found if i["type"] == t) for t in itf.TYPES}
    return {"counts": {"integrons": len(found), **counts}, "warnings": [],
            "files": [files["integrons"], files["summary"], files["log"], topology]}


def _isescan(ctx: JobContext, exe: str, params: ise.IsescanParams, contigs: Path, results: Path, add) -> dict[str, Any]:
    argv = _argv("isescan", lambda: ise.IsescanAdapter.argv(exe, params, contigs, results,
                                                             ise.IsescanAdapter.help_options(exe)))
    _run_tool(ctx, "isescan", argv, results, ise.LOG, env=ise.env_for(exe))
    rows = _read("isescan", ise.tsv_path(results), ise.parse_tsv)
    for r in rows:
        add(category="insertion_sequence", element=r["cluster"], element_type=r["family"], contig=r["seqID"],
            start=r["isBegin"], end=r["isEnd"], strand=r["strand"] if r["strand"] in ("+", "-") else None,
            score=r["E-value"], completeness=r["completeness"], details=r)
    partial = sum(1 for r in rows if r["completeness"] == "partial")
    warnings = [{"code": "isescan_partial", "params": {"count": partial}}] if partial else []
    return {"counts": {"elements": len(rows), "complete": len(rows) - partial, "partial": partial,
                       "families": sorted({r["family"] for r in rows if r["family"]})},
            "warnings": warnings, "files": [ise.tsv_path(results)]}


def _genomad(ctx: JobContext, exe: str, params: gn.GenomadParams, contigs: Path, results: Path, add) -> dict[str, Any]:
    record = _record(ctx)
    argv = _argv("genomad", lambda: gn.GenomadAdapter.argv(exe, params, contigs, results, Path(record.path or ""),
                                                            gn.GenomadAdapter.help_options(exe)))
    _run_tool(ctx, "genomad", argv, results, gn.LOG, env=gn.env_for(exe))
    files = gn.outputs(results, contigs)
    plasmids = _read("genomad", files["plasmid"], gn.parse_plasmids)
    viruses = _read("genomad", files["virus"], gn.parse_viruses)
    for p in plasmids:
        add(category="genomad_plasmid", element=p["seq_name"], element_type="plasmid", contig=p["contig"],
            score=p["plasmid_score"], details=p)
    for v in viruses:
        add(category="genomad_virus", element=v["seq_name"], element_type="provirus" if v["provirus"] else "virus",
            contig=v["contig"], start=v["start"], end=v["end"], score=v["virus_score"], details=v)
    return {"counts": {"plasmids": len(plasmids), "viruses": sum(1 for v in viruses if not v["provirus"]),
                       "proviruses": sum(1 for v in viruses if v["provirus"])},
            "warnings": [{"code": "genomad_scores", "params": {}}], "files": list(files.values())}


def _body(ctx: JobContext) -> None:
    p = ctx.job.parameters or {}
    method = p["method"]
    spec = svc.METHODS[method]
    exe = _resolve_tool(ctx, spec["tool"])
    params = spec["params"](**{k: v for k, v in (p.get("settings") or {}).items()
                               if k in spec["params"].__dataclass_fields__})
    a: Assembly = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    (results / "input").mkdir(parents=True)
    contigs = results / "input" / INPUT
    staged = annotation_svc.stage_genome(ctx.path(a.contigs_path), contigs, False)
    names = [c["name"] for c in staged["contigs"]]
    ctx.log(f"Input: {len(names)} contigs, {staged['total_length']:,} bp, written as input/{INPUT} "
            f"(sha256 {staged['sha256']})")
    job = ctx.job

    def add(**values) -> None:
        ctx.db.add(MobileElementResult(sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, tool=method,
                                       **values))

    if method == "mobsuite":
        out = _mobsuite(ctx, exe, params, contigs, results, add)
    elif method == "plasmidfinder":
        out = _plasmidfinder(ctx, exe, params, contigs, results, add, {c["name"]: c["length"] for c in staged["contigs"]})
    elif method == "integronfinder":
        circ = svc.circularity(a)
        out = _integronfinder(ctx, exe, params, contigs, results, add, {n: (circ.get(n) or {}).get("circular")
                                                                        for n in names})
    elif method == "isescan":
        out = _isescan(ctx, exe, params, contigs, results, add)
    else:
        out = _genomad(ctx, exe, params, contigs, results, add)
    warnings = out["warnings"]
    if not job.tool_version or job.tool_version not in ADAPTERS[method].info.tested_versions:
        warnings.append({"code": "tool_not_validated", "params": {"tool": NAMES[method], "version": job.tool_version}})
    if evidence := p.get("synthetic_evidence"):
        warnings.append({"code": "synthetic_input", "params": {"evidence": ", ".join(evidence)}})
    files = {f.name: {"path": _rel(ctx, f), "sha256": _sha256(f), "size_bytes": f.stat().st_size}
             for f in out["files"] if f.is_file()}
    inputs = {"input": {"path": _rel(ctx, contigs), "sha256": staged["sha256"], "size_bytes": contigs.stat().st_size}}
    ctx.log(f"{NAMES[method]}: " + ", ".join(f"{k} {v}" for k, v in out["counts"].items() if not isinstance(v, list)))
    job.result_summary = {"counts": out["counts"], "warnings": warnings, "files": files, "inputs": inputs,
                          "searched_contigs": names, "log": out.get("log")}
    job.output_paths = [f["path"] for f in files.values()] + [inputs["input"]["path"]]


def run_mobile_job(job_id: str) -> str:
    return run_job(job_id, _body)
