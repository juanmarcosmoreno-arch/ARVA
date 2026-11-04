"""Worker task for the searches of a Sanger identification (app.services.sanger): one job per source.

Before the run the worker checks again what the user confirmed: the searched sequence (SHA-256 of the consensus or
trimmed read), the database (same record, version, content checksum and folder; for the databases ABRicate and mlst
bundle, the same folder next to the tool that runs) and, for genomes in ARVA, each genome's contigs SHA-256. The
query is written to input/query.fna; BLAST+, AMRFinderPlus and spaTyper write into the job's results folder, and
staged genome copies are removed at the end. Nothing is sent outside this computer.

The hits of one source become one sanger_search_results row: one row per subject with its chained HSPs
(arva_core.sanger.hits_from_hsps), named from the database's titles (NCBI 16S: organism and strain; VFDB: gene,
product, factor; mlst: locus and allele), from the reference collection's metadata (species, strain, type material)
or from the annotated features a genome hit overlaps (arva_core.sanger.name_by_features).
"""
from __future__ import annotations

import gzip
import shutil
from pathlib import Path
from typing import Any

from arva_core import sanger as core
from arva_tools.blast import BlastAdapter, BlastParams, parse_tabular

from app.models import (
    Annotation,
    Assembly,
    ReferenceDatabase,
    SangerIdentification,
    SangerSearchResult,
)
from app.services import abricate_db
from app.services import annotation as annotation_svc
from app.services import mlst as mlst_svc
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.comparative import _check, _read, _run_tool
from app.tasks.mobile_elements import _record
from app.tasks.tools import _rel, _resolve_tool, _sha256

INPUT_DIR = "input"
QUERY = "query.fna"
STAGE_DIR = "staged"
# Features of a genome hit kept on its row (the most covered first).
MAX_FEATURES = 5


def _identification(ctx: JobContext) -> SangerIdentification:
    p = ctx.job.parameters or {}
    ident = ctx.db.get(SangerIdentification, p.get("identification_id"))
    if ident is None:
        raise JobFailure("The Sanger identification was deleted", "sanger_identification_missing")
    if ident.sha256 != (p.get("query") or {}).get("sha256"):
        raise JobFailure("The sequence to search changed since the search was confirmed", "sanger_query_changed")
    return ident


def _write_query(path: Path, ident: SangerIdentification) -> None:
    seq = ident.sequence
    path.write_text(">query\n" + "\n".join(seq[i:i + 80] for i in range(0, len(seq), 80)) + "\n")


def _params(ctx: JobContext) -> BlastParams:
    s = (ctx.job.parameters or {}).get("settings") or {}
    return BlastParams(program="blastn", task=s["task"], evalue=float(s["evalue"]),
                       max_target_seqs=int(s["max_target_seqs"]), low_complexity_filter=bool(s["low_complexity_filter"]),
                       threads=int(s.get("threads") or 1))


def _blast(ctx: JobContext, exe: str, params: BlastParams, query: Path, results: Path, name: str, titles: bool,
           db: str | None = None, subject: str | None = None) -> list[dict[str, Any]]:
    (results / "blast").mkdir(exist_ok=True)
    out = f"blast/{name}.tsv"
    argv = _check("blastn", lambda: BlastAdapter.search_argv(exe, params, str(query), out, db=db, subject=subject,
                                                             titles=titles))
    _run_tool(ctx, "blastn", argv, results, f"blast/{name}.log")
    return _read("blastn", results / out, lambda text: parse_tabular(text, titles=titles))


def _source(ctx: JobContext, record: ReferenceDatabase | None, **extra: Any) -> dict[str, Any]:
    j = ctx.job
    base = {"source": (j.parameters or {}).get("source"), "kind": j.database_kind, "key": j.database_key,
            "name": j.database_name, "version": j.database_version, "version_source": j.database_version_source,
            "checksum": j.database_checksum, "database_id": record.id if record else None}
    return {**base, **extra}


# --- Databases searched with blastn -------------------------------------------------------------------------------

def _name_16s(h: dict[str, Any]) -> dict[str, Any]:
    p = core.parse_16s_title(h.get("stitle") or "")
    # Every sequence of the database is a 16S rRNA gene: arva_core.sanger.row_genes reads the source kind as that
    # gene, so the row keeps its organism as its name.
    return {"species": p["species"], "genus": p["genus"], "strain": p["strain"], "subspecies": p["subspecies"],
            "organism": p["organism"], "accession": core.ncbi_accession(h["sseqid"])}


def _name_vfdb(h: dict[str, Any]) -> dict[str, Any]:
    p = core.parse_abricate_id(h["sseqid"], h.get("stitle"))
    return {"gene": p["gene"], "product": p["product"], "accession": p["accession"], "factor": p["factor"],
            "category": p["category"], "organism": p["organism"]}


def _name_mlst(h: dict[str, Any]) -> dict[str, Any]:
    p = core.parse_mlst_allele(h["sseqid"]) or {}
    return {"gene": p.get("locus"), "allele": p.get("allele"), "scheme": p.get("scheme")}


def _ncbi_16s(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    record = _record(ctx)
    db = Path(record.path or "") / "16S_ribosomal_RNA"
    hsps = _blast(ctx, exe, _params(ctx), query, results, "ncbi_16s", True, db=str(db))
    rows = core.hits_from_hsps(hsps, _source(ctx, record), _name_16s)
    return rows, {"hsps": len(hsps), "blastdb": ((record.details or {}).get("detection") or {})
                  .get("facts", {}).get("blastdb")}


def _bundled_folder(ctx: JobContext, record: ReferenceDatabase, folder: Path, checksum) -> None:
    if record.path != str(folder) or checksum(folder) != ctx.job.database_checksum:
        raise JobFailure(f"The bundled database is not the recorded one (expected {record.path}, the tool now reads "
                         f"{folder})", "bundled_database_changed", name=str(record.name))


def _vfdb(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    from arva_tools import abricate as abr
    from arva_tools.registry import detect

    record = _record(ctx)
    abricate = detect("abricate", refresh=True)
    if not abricate.path:
        raise JobFailure("ABRicate, whose bundled VFDB this search reads, is not installed any more",
                         "tool_unavailable", tool="ABRicate", status=abricate.status.value, message=abricate.message)
    folder = abr.datadir(abricate.path) / "vfdb"
    _bundled_folder(ctx, record, folder, abricate_db.content_checksum)
    hsps = _blast(ctx, exe, _params(ctx), query, results, "vfdb", True, db=str(folder / "sequences"))
    return core.hits_from_hsps(hsps, _source(ctx, record), _name_vfdb), {"hsps": len(hsps)}


def _mlst(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    from arva_tools import mlst as mlst_tool
    from arva_tools.registry import detect

    record = _record(ctx)
    tool = detect("mlst", refresh=True)
    if not tool.path:
        raise JobFailure("mlst, whose bundled PubMLST alleles this search reads, is not installed any more",
                         "tool_unavailable", tool="mlst", status=tool.status.value, message=tool.message)
    folder = mlst_tool.database_dir(tool.path)
    _bundled_folder(ctx, record, folder, mlst_svc.content_checksum)
    hsps = _blast(ctx, exe, _params(ctx), query, results, "mlst", True, db=str(folder / "blast" / "mlst.fa"))
    return core.hits_from_hsps(hsps, _source(ctx, record), _name_mlst), {"hsps": len(hsps)}


# --- Genomes searched one by one ----------------------------------------------------------------------------------

def _subject_file(path: Path, stage: Path) -> Path:
    """BLAST's -subject reads plain FASTA only: a gzip-compressed genome is decompressed into the staging folder."""
    if path.suffix != ".gz":
        return path
    out = stage / "genome.fna"
    with gzip.open(path, "rb") as src, open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return out


def _reference_genomes(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    record = _record(ctx)
    genomes = [g for g in (record.inventory or []) if g.get("present")]
    stage = results / STAGE_DIR
    stage.mkdir()
    params = _params(ctx)
    rows: list[dict[str, Any]] = []
    missing = []
    try:
        for n, g in enumerate(genomes, 1):
            ctx.check_cancelled()
            path = Path(g["path"])
            if not path.is_file():
                missing.append(g.get("accession") or g.get("key"))
                continue
            subject = _subject_file(path, stage)
            hsps = _blast(ctx, exe, params, query, results, f"g{n}", False, subject=str(subject))
            species = g.get("species")
            names = {"species": species, "genus": species.split()[0] if species else None,
                     "strain": g.get("strain"), "accession": g.get("accession"), "organism": g.get("organism"),
                     "genome": g.get("accession") or g.get("key"), "type_material": g.get("type_label"),
                     "species_source": "collection"}
            for row in core.hits_from_hsps(hsps, _source(ctx, record), lambda _h, x=names: dict(x)):
                # The subject is a whole contig or chromosome: its coverage is not the gene's, which is unknown here
                # (the collection's genomes are not annotated).
                row["contig_coverage"], row["subject_coverage"] = row["subject_coverage"], None
                rows.append(row)
            if subject != path:
                subject.unlink()
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if missing:
        ctx.log(f"WARNING: {len(missing)} genome file(s) of the collection are missing and were not searched: "
                + ", ".join(str(m) for m in missing[:10]))
    rows.sort(key=lambda r: (-r["bitscore"], -r["identity"]))
    return rows, {"genomes_searched": len(genomes) - len(missing), "genomes_missing": missing[:100]}


def _feature_names(row: dict[str, Any], features: list[dict[str, Any]], contig: str | None) -> dict[str, Any]:
    named = core.name_by_features(row, features, contig=contig)
    top = named[0] if named else None
    return {"features": named[:MAX_FEATURES], "gene": top.get("gene") if top else None,
            "product": top.get("product") if top else None}


def _genomes(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    genomes = (ctx.job.parameters or {}).get("genomes") or []
    stage = results / STAGE_DIR
    stage.mkdir()
    params = _params(ctx)
    rows: list[dict[str, Any]] = []
    searched = []
    try:
        for n, g in enumerate(genomes, 1):
            ctx.check_cancelled()
            a = ctx.db.get(Assembly, g["assembly_id"])
            if a is None:
                raise JobFailure(f"Assembly {g['assembly_id']} no longer exists", "assembly_missing",
                                 assembly=str(g.get("sample_code") or g["assembly_id"]))
            src = ctx.path(a.contigs_path)
            if not src.is_file():
                raise JobFailure(f"The contigs file of {g.get('sample_code')} is missing on disk", "contigs_missing",
                                 assembly=str(g.get("sample_code")))
            if (digest := _sha256(src)) != g["contigs_sha256"]:
                raise JobFailure(f"The contigs of {g.get('sample_code')} changed since the search was confirmed "
                                 f"(sha256 {digest})", "contigs_changed", assembly=str(g.get("sample_code")))
            dest = stage / f"g{n}.fna"
            info = annotation_svc.stage_genome(src, dest, True)
            to_assembly = {c["name"]: c["original_name"] for c in info["contigs"]}
            hsps = _blast(ctx, exe, params, query, results, f"g{n}", False, subject=str(dest))
            ann = None
            if g.get("annotation"):
                ann = ctx.db.get(Annotation, g["annotation"]["annotation_id"])
            features = annotation_svc.features_of(ann) if ann is not None else []
            # Annotation contig (Bakta and Prokka may rename them) for each assembly contig.
            to_annotation = {v: k for k, v in annotation_svc.original_names(ann).items()} if ann is not None else {}
            species = g.get("species") or {}
            source = _source(ctx, None, kind="genome", name=g.get("sample_code"), assembly_id=a.id,
                             contigs_sha256=g["contigs_sha256"],
                             annotation=g.get("annotation"), own_sample=g.get("own_sample"))
            for row in core.hits_from_hsps(hsps, source):
                contig = to_assembly.get(row["subject"], row["subject"])
                row["subject"] = contig
                row.update({"genome": g.get("sample_code"), "assembly_id": a.id,
                            "species": species.get("species"),
                            "genus": species["species"].split()[0] if species.get("species") else None,
                            "species_source": "species_identification" if species.get("species") else None})
                if ann is not None:
                    row.update(_feature_names(row, features, to_annotation.get(contig, contig)))
                # The subject is a contig: the gene's coverage is the share of the annotated feature the hit covers
                # (none without an annotation), and the contig's is kept apart.
                top = (row.get("features") or [None])[0]
                row["contig_coverage"] = row["subject_coverage"]
                row["subject_coverage"] = top["feature_coverage"] if top else None
                rows.append(row)
            searched.append({"assembly_id": a.id, "sample_code": g.get("sample_code"), "hsps": len(hsps),
                             "annotation": g.get("annotation"), "own_sample": g.get("own_sample")})
            dest.unlink()
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    rows.sort(key=lambda r: (-r["bitscore"], -r["identity"]))
    unannotated = [s["sample_code"] for s in searched if not s["annotation"]]
    warnings = [{"code": "genomes_unannotated", "params": {"genomes": ", ".join(str(x) for x in unannotated)}}] \
        if unannotated else []
    return rows, {"genomes": searched, "warnings": warnings}


# --- AMRFinderPlus and spaTyper -----------------------------------------------------------------------------------

def _amrfinderplus(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    from arva_tools import ToolExecutionError, ToolTimeoutError
    from arva_tools import amrfinderplus as amr_tool
    from arva_tools.amrfinderplus import OUTPUTS, AmrfinderplusAdapter, AmrParams

    from app.tasks.amr import TMP_DIR
    from app.tasks.amr import _database as amr_database
    from app.tasks.tools import _run

    folder = amr_database(ctx, exe)
    s = (ctx.job.parameters or {}).get("settings") or {}
    params = AmrParams(**{k: s[k] for k in ("mode", "organism", "plus", "ident_min", "coverage_min",
                                            "translation_table") if k in s}, threads=int(s.get("threads") or 1))
    help_text = _check("AMRFinderPlus", lambda: AmrfinderplusAdapter.help_text(exe))
    argv = _check("AMRFinderPlus", lambda: AmrfinderplusAdapter.argv(
        exe, params, query, results, folder, amr_tool.parse_help_options(help_text)))
    tmp = results / TMP_DIR
    tmp.mkdir()
    log_path = results / OUTPUTS["log"]
    try:
        _run(ctx, argv, results, log_path.name, extra_env=amr_tool.env_for(exe, tmp))
    except ToolExecutionError as exc:
        if isinstance(exc, ToolTimeoutError):
            raise
        reason = amr_tool.failure(log_path.read_text(errors="replace") if log_path.is_file() else "")
        if reason is None:
            raise
        raise JobFailure(f"AMRFinderPlus stopped: {reason}", "amrfinder_stopped", detail=reason) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    found = _read("AMRFinderPlus", results / OUTPUTS["report"], amr_tool.parse_report)
    log = amr_tool.parse_stderr(log_path.read_text(errors="replace"))
    if log["database_version"] != ctx.job.database_version:
        raise JobFailure(f"AMRFinderPlus read database {log['database_version']}, not the recorded "
                         f"{ctx.job.database_version}", "database_changed", name=str(ctx.job.database_name))
    keep = ("element_symbol", "element_name", "scope", "type", "subtype", "class", "subclass", "method", "identity",
            "coverage", "target_length", "reference_length", "alignment_length", "start", "stop", "strand",
            "closest_accession", "closest_name", "hmm_accession", "hmm_description")
    rows = [{**{k: r.get(k) for k in keep}, "method_kind": r["method_info"]["kind"],
             "search": r["method_info"]["search"]} for r in found]
    return rows, {"log": log, "warnings": amr_tool.warnings(params, found, None),
                  "files": {k: _rel(ctx, results / v) for k, v in OUTPUTS.items() if (results / v).is_file()}}


def _spa(ctx: JobContext, exe: str, query: Path, results: Path) -> tuple[list, dict]:
    from arva_tools import spatyper as sp

    from app.tasks.typing import _spa as spa_step

    out = spa_step(ctx, exe, sp.SpaParams(), query, results)
    return out["details"]["rows"], {"status": out["status"], "spa_type": out["call"], "repeats": out["repeats"],
                                    "ridom_files": out["details"]["ridom_files"], "warnings": out["warnings"]}


HANDLERS = {"ncbi_16s": _ncbi_16s, "vfdb": _vfdb, "mlst": _mlst, "reference_genomes": _reference_genomes,
            "genomes": _genomes, "amrfinderplus": _amrfinderplus, "spa": _spa}
TOOLS = {"ncbi_16s": "blast", "vfdb": "blast", "mlst": "blast", "reference_genomes": "blast", "genomes": "blast",
         "amrfinderplus": "amrfinderplus", "spa": "spatyper"}


def _body(ctx: JobContext) -> None:
    from arva_tools.blast import sibling

    job = ctx.job
    p = job.parameters or {}
    source = p.get("source")
    if source not in HANDLERS:
        raise JobFailure(f"Unknown Sanger search source {source!r}", "settings_rejected", tool="ARVA",
                         detail=f"source {source}")
    ident = _identification(ctx)
    exe = _resolve_tool(ctx, TOOLS[source])
    if TOOLS[source] == "blast":
        exe = sibling(exe, "blastn") or exe
    results = ctx.path(ctx.results_rel)
    (results / INPUT_DIR).mkdir(parents=True)
    query = results / INPUT_DIR / QUERY
    _write_query(query, ident)
    ctx.log(f"Query: the {'consensus' if ident.mode == 'pair' else 'trimmed read'} of '{ident.label}', "
            f"{ident.length} bases (sha256 {ident.sha256}), written as {INPUT_DIR}/{QUERY}")
    rows, details = HANDLERS[source](ctx, exe, query, results)
    details = {**details, "query": {"length": ident.length, "sha256": ident.sha256, "file": _rel(ctx, query)},
               "settings": p.get("settings")}
    ctx.db.add(SangerSearchResult(identification_id=ident.id, job_id=job.id, source=source, rows=rows,
                                  details=details))
    ctx.log(f"{source}: {len(rows)} result row(s)")
    files = [f for f in results.rglob("*") if f.is_file()]
    job.result_summary = {"source": source, "rows": len(rows), "warnings": details.get("warnings") or [],
                          "files": {_rel(ctx, f): {"sha256": _sha256(f), "size_bytes": f.stat().st_size}
                                    for f in files}}
    job.output_paths = [_rel(ctx, f) for f in files]


def run_sanger_job(job_id: str) -> str:
    return run_job(job_id, _body)
