"""Worker task for species identification (FastANI, skani, Mash, sylph or GTDB-Tk).

Before the run the worker checks again what the user confirmed: the assembly's contigs (SHA-256) and the database
(the same record and path, still usable). For a reference collection it lists the genomes it can read, records the
SHA-256 of each (the inputs of FastANI or skani) and leaves out — with a warning — any that cannot be read. Every
output, log and temporary file stays in the job's results folder.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from arva_core.species import collection_scope, consistency, interpret, interpret_gtdbtk, species_of
from arva_tools import ToolExecutionError, ToolTimeoutError
from arva_tools import fastani as fastani_tool
from arva_tools import gtdbtk as gtdbtk_tool
from arva_tools import mash as mash_tool
from arva_tools import skani as skani_tool
from arva_tools import sylph as sylph_tool
from arva_tools.fastani import FastaniAdapter, FastaniParams
from arva_tools.gtdbtk import GtdbtkAdapter, GtdbtkParams
from arva_tools.mash import MashAdapter, MashParams
from arva_tools.registry import detect
from arva_tools.skani import SkaniAdapter, SkaniParams
from arva_tools.sylph import SylphAdapter, SylphParams

from app.models import Assembly, ReferenceDatabase, SpeciesResult
from app.services import annotation as annotation_svc
from app.services import databases as dbs
from app.services import species as svc
from app.services.locations import to_host
from app.services.performance import effective_resources
from app.tasks.annotation import INPUT_NAME, _assembly
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.tools import _rel, _resolve_tool, _run, _sha256

TMP_DIR = "tmp"
REFERENCES = "references.txt"
ADAPTERS = {"fastani": FastaniAdapter, "skani": SkaniAdapter, "mash": MashAdapter, "sylph": SylphAdapter,
            "gtdbtk": GtdbtkAdapter}
FLAGS = {"fastani": fastani_tool.FLAGS, "skani": skani_tool.FLAGS, "mash": mash_tool.FLAGS, "sylph": sylph_tool.FLAGS,
         "gtdbtk": gtdbtk_tool.FLAGS}
PARAMS = {"fastani": FastaniParams, "skani": SkaniParams, "mash": MashParams, "sylph": SylphParams,
          "gtdbtk": GtdbtkParams}


def _database(ctx: JobContext) -> ReferenceDatabase:
    job = ctx.job
    record = ctx.db.get(ReferenceDatabase, job.reference_database_id) if job.reference_database_id else None
    if record is None or record.path != job.database_path or record.version != job.database_version:
        raise JobFailure(f"The database recorded for this run ({job.database_name} {job.database_version}) is no "
                         "longer the same; start the identification again", "species_database_changed",
                         name=str(job.database_name))
    if record.status not in dbs.USABLE:
        raise JobFailure(f"{record.name} cannot be used now ({record.status.value})", "species_database_changed",
                         name=record.name)
    try:
        dbs.require_available(record)
    except dbs.DatabaseUnavailableError as exc:
        raise JobFailure(str(exc), exc.code, **exc.params) from exc
    ctx.log(f"Database: {record.name}, version {record.version} ({record.version_source.value if record.version_source else '?'}), "
            f"at {to_host(record.path) or record.path}, content checksum {record.checksum or 'not computed (no full verification)'}")
    return record


def _params(method: str, p: dict[str, Any]):
    cls = PARAMS[method]
    return cls(**{k: p["settings"][k] for k in cls.__dataclass_fields__ if k in p["settings"]})


def _check(adapter, exe: str, build):
    try:
        return build(adapter.help_options(exe))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"{adapter.info.name}'s help could not be read to check its options: {exc}",
                         "help_unreadable", tool=adapter.info.name, detail=str(exc)) from exc
    except ValueError as exc:
        raise JobFailure(f"{adapter.info.name} cannot run with these settings: {exc}", "settings_rejected",
                         tool=adapter.info.name, detail=str(exc)) from exc


def _parse(name: str, parse, path: Path):
    try:
        return parse(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        raise JobFailure(f"{name}'s output cannot be read: {exc}", "output_unreadable", tool=name,
                         detail=str(exc)) from exc


def _run_tool(ctx: JobContext, argv: list[str], results: Path, log: str, stdout: Path | None = None,
              env: dict[str, str] | None = None) -> None:
    try:
        _run(ctx, argv, results, log, stdout=stdout, extra_env=env)
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError):
            raise
        tail = (results / log).read_text(errors="replace").strip().splitlines()[-3:] if (results / log).is_file() else []
        raise JobFailure(f"{Path(argv[0]).name} stopped: {' / '.join(tail) or exc}", "species_tool_failed",
                         tool=Path(argv[0]).name, detail=" / ".join(tail)[:500]) from None


def _genome_hit(g: dict[str, Any]) -> dict[str, Any]:
    return {"reference": g.get("accession") or Path(g["path"]).name, "accession": g.get("accession"),
            "organism": g.get("organism"), "species": g.get("species"), "strain": g.get("strain"),
            "type_material": bool(g.get("type_label")) if g.get("metadata") == "package" else None,
            "type_label": g.get("type_label"), "refseq_category": g.get("refseq_category")}


def _collection_run(ctx: JobContext, method: str, exe: str, params, record: ReferenceDatabase, query: Path,
                    results: Path) -> dict[str, Any]:
    genomes = list(record.inventory or [])
    usable, missing = [], []
    for g in genomes:
        p = Path(g.get("path") or "")
        (usable if g.get("present") and p.is_file() else missing).append(g)
    if not usable:
        raise JobFailure(f"No genome of {record.name} can be read", "collection_empty", name=record.name)
    references = []
    for g in usable:
        references.append({"accession": g.get("accession"), "path": to_host(g["path"]) or g["path"],
                           "size_bytes": Path(g["path"]).stat().st_size, "sha256": _sha256(Path(g["path"]))})
    checksum = hashlib.sha256("".join(f"{r['accession'] or r['path']}\t{r['sha256']}\n"
                                      for r in sorted(references, key=lambda r: r["accession"] or r["path"])).encode())
    ctx.log(f"{len(usable)} reference genomes (SHA-256 of each recorded; list checksum {checksum.hexdigest()})"
            + (f"; {len(missing)} could not be read and are left out" if missing else ""), flush=True)
    ref_list = results / REFERENCES
    ref_list.write_text("".join(f"{g['path']}\n" for g in usable))
    adapter = ADAPTERS[method]
    argv = _check(adapter, exe, lambda opts: adapter.argv(exe, params, query, ref_list, results, opts))
    mod = fastani_tool if method == "fastani" else skani_tool
    _run_tool(ctx, argv, results, mod.LOG)
    rows = _parse(adapter.info.name, mod.parse_output, results / mod.OUTPUT)
    by_path = {g["path"]: g for g in usable}
    hits = []
    for r in rows:
        g = by_path.get(r["reference"])
        meta = _genome_hit(g) if g else {"reference": Path(r["reference"]).name, "accession": None, "organism": None,
                                         "species": None, "strain": None, "type_material": None}
        hits.append({**meta, **{k: r.get(k) for k in ("ani", "af", "af_query", "af_reference", "fragments_mapped",
                                                       "fragments_total")}})
    learned = method == "skani" and skani_tool.LEARNED in (results / mod.LOG).read_text(errors="replace")
    return {"hits": hits, "scope": collection_scope(g.get("species") for g in genomes),
            "files": {"output": results / mod.OUTPUT, "log": results / mod.LOG, "references": ref_list},
            "details": {"references": references, "references_checksum": checksum.hexdigest(),
                        "references_missing": [to_host(g.get("path") or "") or g.get("path") for g in missing][:50],
                        "missing_count": len(missing), "learned_ani": learned if method == "skani" else None},
            "missing": missing}


def _mash_run(ctx: JobContext, exe: str, params: MashParams, record: ReferenceDatabase, query: Path,
              results: Path) -> dict[str, Any]:
    sketch = Path(record.path or "")
    header_file, info_file = results / "mash_info_header.txt", results / mash_tool.INFO_OUTPUT
    _run_tool(ctx, MashAdapter.info_argv(exe, sketch, False), results, mash_tool.LOG, stdout=header_file)
    _run_tool(ctx, MashAdapter.info_argv(exe, sketch, True), results, mash_tool.LOG, stdout=info_file)
    header = _parse("Mash", mash_tool.parse_info_header, header_file)
    info = _parse("Mash", mash_tool.parse_info_table, info_file)
    ctx.log(f"Sketch: k-mer size {header['kmer']}, sketch size {header['sketch_size']}, seed {header.get('seed')}, "
            f"{header.get('sketches')} sketches (inherited by mash dist)")
    argv = _check(MashAdapter, exe, lambda opts: MashAdapter.argv(exe, params, query, sketch, opts))
    _run_tool(ctx, argv, results, mash_tool.LOG, stdout=results / mash_tool.OUTPUT)
    rows = sorted(_parse("Mash", mash_tool.parse_dist, results / mash_tool.OUTPUT), key=lambda r: r["distance"])
    hits = []
    for r in rows[:svc.TOP_HITS]:
        organism = (info.get(r["reference"]) or {}).get("organism")
        hits.append({"reference": r["reference"], "accession": r["accession"], "organism": organism,
                     "species": species_of(organism), "strain": None, "type_material": None,
                     "distance": r["distance"], "p_value": r["p_value"], "shared": r["shared"], "hashes": r["hashes"]})
    return {"hits": hits, "scope": collection_scope(species_of(v["organism"]) for v in info.values()),
            "files": {"output": results / mash_tool.OUTPUT, "log": results / mash_tool.LOG, "info": info_file,
                      "info_header": header_file},
            "details": {"sketch": header, "references_compared": len(rows)}, "missing": []}


def _sylph_run(ctx: JobContext, exe: str, params: SylphParams, record: ReferenceDatabase, query: Path,
               results: Path) -> dict[str, Any]:
    database = Path(record.path or "")
    inspect_file = results / sylph_tool.INSPECT_OUTPUT
    _run_tool(ctx, SylphAdapter.inspect_argv(exe, database), results, sylph_tool.LOG, stdout=inspect_file)
    info = _parse("sylph", sylph_tool.parse_inspect, inspect_file)
    params.c, params.k = info["c"], info["k"]
    ctx.log(f"sylph database: c {info['c']}, k {info['k']}, {len(info['genomes'])} genomes; the assembly is sketched "
            "with the same c and k")
    argv = _check(SylphAdapter, exe, lambda opts: SylphAdapter.argv(exe, params, query, database, results, opts))
    _run_tool(ctx, argv, results, sylph_tool.LOG)
    rows = _parse("sylph", sylph_tool.parse_profile, results / sylph_tool.OUTPUT)
    hits = []
    for r in sorted(rows, key=lambda r: -r["ani"])[:svc.TOP_HITS]:
        organism = mash_tool.organism_from_comment(r["reference_name"])
        hits.append({"reference": Path(r["reference"]).name, "accession": r["accession"], "organism": organism,
                     "species": species_of(organism), "strain": None, "type_material": None,
                     **{k: r[k] for k in ("ani", "af", "naive_ani", "adjusted_ani", "eff_lambda", "eff_cov",
                                          "containment_shared", "containment_sampled", "taxonomic_abundance")}})
    scope = collection_scope(species_of(mash_tool.organism_from_comment(g.get("first_contig_name") or ""))
                             for g in info["genomes"])
    return {"hits": hits, "scope": scope,
            "files": {"output": results / sylph_tool.OUTPUT, "log": results / sylph_tool.LOG, "inspect": inspect_file},
            "details": {"sylph_database": {"c": info["c"], "k": info["k"], "genomes": len(info["genomes"])}},
            "missing": []}


def _gtdbtk_run(ctx: JobContext, exe: str, params: GtdbtkParams, record: ReferenceDatabase, results: Path) -> dict:
    required = gtdbtk_tool.REQUIRED_MEMORY_GB
    if (memory := effective_resources(ctx.db).memory_gb) < required:
        raise JobFailure(f"GTDB-Tk needs about {required} GB of memory for bacteria (GTDB-Tk 2.8.0 documentation); "
                         f"the performance profile gives a run {memory} GB", "gtdbtk_memory", required=required,
                         available=memory)
    out, tmp = results / "gtdbtk", results / TMP_DIR
    out.mkdir()
    tmp.mkdir(exist_ok=True)
    argv = _check(GtdbtkAdapter, exe, lambda opts: GtdbtkAdapter.argv(exe, params, results / "input", out, tmp, opts))
    try:
        _run_tool(ctx, argv, results, gtdbtk_tool.LOG, env=gtdbtk_tool.env_for(exe, Path(record.path or "")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rows, files = [], {"log": results / gtdbtk_tool.LOG}
    for domain, rel in gtdbtk_tool.SUMMARIES.items():
        if (path := out / rel).is_file():
            rows += _parse("GTDB-Tk", lambda t, d=domain: gtdbtk_tool.parse_summary(t, d), path)
            files[f"summary_{domain}"] = path
    row = next((r for r in rows if r["user_genome"] == Path(INPUT_NAME).stem), None)
    hits = []
    if row and row.get("closest_reference"):
        hits.append({"reference": row["closest_reference"], "accession": row["closest_reference"],
                     "organism": row.get("closest_taxonomy"), "species": row.get("species"), "strain": None,
                     "type_material": None, "ani": row.get("closest_ani"), "af": row.get("closest_af")})
    for rel in (row or {}).get("related") or []:
        hits.append({"reference": rel["accession"], "accession": rel["accession"], "organism": rel["species"],
                     "species": rel["species"], "strain": None, "type_material": None, "ani": rel["ani"],
                     "af": rel["af"]})
    return {"hits": hits, "row": row, "files": files, "details": {"gtdbtk": row}, "missing": []}


def _body(ctx: JobContext) -> None:
    p = ctx.job.parameters or {}
    method = p["method"]
    exe = _resolve_tool(ctx, svc.METHODS[method]["tool"])
    record = _database(ctx)
    params = _params(method, p)
    a: Assembly = _assembly(ctx)
    results = ctx.path(ctx.results_rel)
    (results / "input").mkdir(parents=True)
    query = results / "input" / INPUT_NAME
    staged = annotation_svc.stage_genome(ctx.path(a.contigs_path), query, False)
    ctx.log(f"Input: {len(staged['contigs'])} contigs, {staged['total_length']:,} bp, written as input/{INPUT_NAME} "
            f"(sha256 {staged['sha256']})")
    if method in ("fastani", "skani"):
        run = _collection_run(ctx, method, exe, params, record, query, results)
    elif method == "mash":
        run = _mash_run(ctx, exe, params, record, query, results)
    elif method == "sylph":
        run = _sylph_run(ctx, exe, params, record, query, results)
    else:
        run = _gtdbtk_run(ctx, exe, params, record, results)
    hits = sorted(run["hits"], key=lambda h: (h.get("distance") if method == "mash" else -(h.get("ani") or 0)))
    for n, h in enumerate(hits, 1):
        h["rank"] = n
    interpretation = interpret_gtdbtk(run["row"]) if method == "gtdbtk" else interpret(hits, method, run["scope"])
    if method != "gtdbtk":
        interpretation["scope"] = run["scope"]
    found = svc.context(ctx.db, a)
    checks = consistency(interpretation, found["mlst"], found["annotation"])
    warnings: list[dict[str, Any]] = []
    if evidence := p.get("synthetic_evidence"):
        warnings.append({"code": "synthetic_input", "params": {"evidence": ", ".join(evidence)}})
    if run["missing"]:
        names = ", ".join((g.get("accession") or Path(g.get("path") or "?").name) for g in run["missing"][:5])
        warnings.append({"code": "genomes_missing", "params": {"count": len(run["missing"]), "names": names}})
    validation = svc.METHODS[method]["validation"]
    if validation == "not_validated" or not detect(svc.METHODS[method]["tool"]).version_validated:
        warnings.append({"code": "not_validated", "params": {"tool": ADAPTERS[method].info.name,
                                                             "version": ctx.job.tool_version}})
    elif validation == "test_database":
        warnings.append({"code": "test_database_only", "params": {"tool": ADAPTERS[method].info.name}})
    files = {k: {"path": _rel(ctx, f), "sha256": _sha256(f), "size_bytes": f.stat().st_size}
             for k, f in run["files"].items() if f.is_file()}
    files["input"] = {"path": _rel(ctx, query), "sha256": staged["sha256"], "size_bytes": query.stat().st_size}
    job = ctx.job
    result = SpeciesResult(
        sample_id=job.sample_id, assembly_id=a.id, job_id=job.id, method=method, tool=ADAPTERS[method].info.name,
        tool_version=job.tool_version, database_kind=job.database_kind, database_name=job.database_name,
        database_version=job.database_version, database_checksum=job.database_checksum,
        parameters={**p, "settings": params.as_dict()}, status=interpretation["status"],
        species=interpretation.get("species"), hits=hits[:svc.TOP_HITS], interpretation=interpretation,
        consistency=checks, warnings=warnings,
        details={**run["details"], "hits_total": len(hits), "context": found,
                 "input": {k: staged[k] for k in ("sha256", "total_length", "non_n_bases")},
                 "contigs": len(staged["contigs"]), "database_path": to_host(record.path) or record.path},
        files=files,
    )
    ctx.db.add(result)
    ctx.db.flush()
    best = interpretation.get("best") or {}
    ctx.log(f"{ADAPTERS[method].info.name}: {len(hits)} hit(s); ARVA's reading: {interpretation['status']}"
            + (f" — {interpretation['species']}" if interpretation.get("species") else "")
            + (f"; best {best.get('species') or best.get('reference')} ANI {best.get('ani')}" if best.get("ani")
               else "")
            + (f"; reasons: {', '.join(r['code'] for r in interpretation['reasons'])}" if interpretation["reasons"]
               else "")
            + (f"; consistency: {', '.join(c['source'] + ' ' + c['outcome'] for c in checks)}" if checks else ""))
    job.result_summary = {"species_result_id": result.id, "method": method, "status": interpretation["status"],
                          "species": interpretation.get("species"), "hits": len(hits),
                          "warnings": [w["code"] for w in warnings]}
    job.output_paths = [f["path"] for f in files.values()]


def run_species_job(job_id: str) -> str:
    return run_job(job_id, _body)
