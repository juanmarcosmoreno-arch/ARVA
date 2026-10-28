"""Genome annotation (spec §11): which annotator can run here and what it will do, the assembly and database it
reads, and the queries, details and exports of a finished annotation's features.

Everything an annotator reports is a prediction. ARVA does not add functions, does not turn "hypothetical protein"
into anything else, and makes links only for identifiers the annotator wrote (arva_core.annotation.links). A step
that cannot run on this computer is skipped with the annotator's own option and recorded with the reason, so a
count of zero is never shown for something that was not searched.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from arva_core.annotation import (
    MAX_QUERY_LIMIT,
    fasta_record,
    fasta_subset,
    genbank_subset,
    gff3_subset,
    links,
    query,
    read_jsonl,
)
from arva_core.formats import open_sequence_file
from arva_core.seqstats import SequenceFormatError, iter_fasta
from arva_tools import ToolStatus
from arva_tools import bakta as bakta_tool
from arva_tools import prokka as prokka_tool
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Annotation, Assembly, DatabaseStatus, RawFile, ReferenceDatabase, Sample
from app.services.metadata_table import sanitize_spreadsheet_cell
from app.storage import get_storage

ANNOTATORS = ("bakta", "prokka")
BAKTA_DATABASE_KEYS = ("bakta-light", "bakta-full")
PROKKA_DATABASE_KEY = "prokka-debian"
MAX_EXPORT_FEATURES = 10_000
MAX_DETAIL_SEQUENCE = 500_000
EXPORT_FORMATS = ("gff3", "genbank", "fasta_nt", "fasta_aa", "tsv")
TSV_COLUMNS = ("id", "locus_tag", "type", "contig", "contig_in_assembly", "start", "end", "strand", "length", "gene",
               "product", "ec", "cog", "cog_categories", "go", "db_xrefs", "pseudo", "partial", "hypothetical",
               "inference")
SYNTHETIC = "SYNTHETIC"
_LOCUS_SOURCE = re.compile(r"[^A-Z0-9]")


class InputError(ValueError):
    """The assembly, options or database cannot be used as requested (HTTP 400)."""


# --- The assembly --------------------------------------------------------------------------------------------

def contig_headers(path: Path) -> list[tuple[str, str]]:
    """(name, description) of every contig of a FASTA file."""
    out = []
    try:
        with open_sequence_file(path) as fh:
            for header, _seq, _q, _line in iter_fasta(fh):
                name, _, desc = header[1:].decode("utf-8", "replace").strip().partition(" ")
                out.append((name, desc.strip()))
    except (OSError, SequenceFormatError) as exc:
        raise InputError(f"The contigs file cannot be read: {exc}") from exc
    return out


def assembly_for(db: Session, assembly_id: str) -> Assembly:
    a = db.get(Assembly, assembly_id)
    if a is None:
        raise LookupError(assembly_id)
    if not get_storage().resolve(a.contigs_path).is_file():
        raise InputError("The contigs file of this assembly is missing on disk")
    return a


def assembly_record(a: Assembly) -> dict[str, Any]:
    """What an annotation job records about its assembly (checked again before the run)."""
    return {"assembly_id": a.id, "kind": a.kind.value, "assembler": a.assembler, "assembler_version":
            a.assembler_version, "parent_assembly_id": a.parent_assembly_id, "job_id": a.job_id,
            "contigs_sha256": a.stats["files"]["contigs"]["sha256"]}


def synthetic_evidence(db: Session, a: Assembly, headers: list[tuple[str, str]]) -> list[str]:
    """Where the word SYNTHETIC (ARVA's generators put it in every header and file name) appears for this assembly:
    a hint that results are not biology, never a proof either way."""
    found = []
    if any(SYNTHETIC in name or SYNTHETIC in desc for name, desc in headers):
        found.append("contig names")
    for file_id in a.input_file_ids or []:
        f = db.get(RawFile, file_id)
        if f is not None and (SYNTHETIC in f.original_filename or SYNTHETIC in str(f.header_metadata or "")):
            found.append(f"read file {f.original_filename}")
    return found


def assembly_facts(db: Session, a: Assembly) -> dict[str, Any]:
    headers = contig_headers(get_storage().resolve(a.contigs_path))
    circ = a.stats.get("circularity") or {}
    n = len(headers)
    longest = max((len(name) for name, _ in headers), default=0)
    return {
        **assembly_record(a), "created_at": a.created_at, "contigs": n, "total_length": a.stats.get("total_length"),
        "circular_contigs": circ.get("circular_contigs"), "contigs_with_circularity": circ.get("contigs_with_circularity"),
        "all_circular": bool(n) and circ.get("contigs_with_circularity") == n and circ.get("circular_contigs") == n,
        "longest_contig_name": longest, "prokka_name_problem": prokka_tool.contig_name_problem([h[0] for h in headers]),
        "descriptions": sum(1 for _, d in headers if d), "synthetic_evidence": synthetic_evidence(db, a, headers),
    }


def suggested_locus_tag(sample: Sample) -> str:
    """Capital letters and digits of the sample code (3-12, starting with a letter), else ARVA."""
    tag = _LOCUS_SOURCE.sub("", sample.sample_code.upper())
    tag = tag.lstrip("0123456789")[:12]
    return tag if bakta_tool.LOCUS_TAG.fullmatch(tag) else "ARVA"


def stage_genome(src: Path, dest: Path, rename: bool) -> dict[str, Any]:
    """Write the contigs as the annotator reads them: uncompressed, names kept (or contig_1, contig_2, … when
    renaming), FASTA descriptions removed so no word in them changes how a replicon is treated; sequences are
    unchanged (re-wrapped at 80 columns)."""
    contigs, non_n, total = [], 0, 0
    digest = hashlib.sha256()
    with open_sequence_file(src) as fh, open(dest, "wb") as out:
        for i, (header, seq, _q, _line) in enumerate(iter_fasta(fh), 1):
            original = header[1:].decode("utf-8", "replace").split(maxsplit=1)[0]
            name = f"contig_{i}" if rename else original
            block = f">{name}\n".encode() + b"\n".join(seq[j:j + 80] for j in range(0, len(seq), 80)) + b"\n"
            out.write(block)
            digest.update(block)
            contigs.append({"name": name, "original_name": original, "length": len(seq)})
            total += len(seq)
            non_n += len(seq) - seq.upper().count(b"N")
    if not contigs:
        raise InputError("The contigs file holds no sequence")
    return {"sha256": digest.hexdigest(), "contigs": contigs, "non_n_bases": non_n, "total_length": total,
            "renamed": rename}


# --- Bakta ---------------------------------------------------------------------------------------------------

def _db_type(r: ReferenceDatabase) -> str | None:
    info = (r.details or {}).get("version_json") or {}
    return info.get("type") or {"bakta-light": "light", "bakta-full": "full"}.get(r.key)


def bakta_databases(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.key.in_(BAKTA_DATABASE_KEYS))
                      .order_by(ReferenceDatabase.verified_at.desc().nulls_last()))
    return [{"id": r.id, "key": r.key, "name": r.name, "version": r.version, "type": _db_type(r), "status": r.status,
             "usable": r.status in (DatabaseStatus.installed, DatabaseStatus.registered) and bool(r.checksum),
             "checksum": r.checksum, "verified_at": r.verified_at, "path": r.path} for r in rows]


def bakta_database(db: Session, database_id: str | None) -> ReferenceDatabase:
    usable = [d for d in bakta_databases(db) if d["usable"]]
    if not usable:
        raise InputError("No Bakta database is installed. Install one in Tools & Databases → Database Manager")
    chosen = next((d for d in usable if d["id"] == database_id), None) if database_id else usable[0]
    if chosen is None:
        raise InputError(f"Database {database_id} is not an installed Bakta database")
    return db.get(ReferenceDatabase, chosen["id"])


def _tool(tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=True)
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason, "path": d.path, "license": d.info.license,
            "citation": d.info.citation, "citation_url": d.info.citation_url,
            "max_threads": get_settings().tool_threads}


def bakta_plan(db: Session, sample: Sample, a: Assembly, database_id: str | None, skip_plot: bool) -> dict[str, Any]:
    """What a Bakta run of this assembly would do here: Bakta and each program it checks, the database, every step
    (run or skipped and why), the assembly's facts and ARVA's suggestions. Nothing is run except version checks."""
    tool = _tool("bakta")
    facts = assembly_facts(db, a)
    databases = bakta_databases(db)
    record = None
    problems = []
    try:
        record = bakta_database(db, database_id)
    except InputError as exc:
        problems.append({"code": "no_database", "message": str(exc)})
    dependencies, steps = [], {}
    if tool["status"] == ToolStatus.available.value and tool["path"]:
        db_path = Path(record.path) if record and record.path else None
        dependencies = bakta_tool.check_dependencies(tool["path"], db_path)
        steps = bakta_tool.plan_steps(dependencies, _db_type(record) if record else None, skip_plot)
    else:
        problems.append({"code": "tool_unavailable", "message": f"Bakta is not available ({tool['status']}): "
                                                                f"{tool['message']}"})
    if steps and not any(v["run"] for k, v in steps.items() if k not in ("gap", "plot")):
        problems.append({"code": "nothing_to_annotate", "message": "Every annotation step would be skipped here"})
    return {"annotator": "bakta", "tool": tool, "dependencies": dependencies, "steps": steps,
            "skip_options": bakta_tool.skip_options(steps) if steps else [], "databases": databases,
            "database_id": record.id if record else None, "assembly": facts,
            "suggestions": {"locus_tag": suggested_locus_tag(sample), "complete": facts["all_circular"],
                            "translation_table": 11},
            "translation_tables": list(bakta_tool.TRANSLATION_TABLES), "problems": problems}


# --- Prokka --------------------------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _manifest_checksum(path: str, signature: tuple) -> str:
    from app.tasks.databases import build_manifest, manifest_checksum

    return manifest_checksum(build_manifest(Path(path), lambda _done, _total: None))


def _signature(folder: Path) -> tuple:
    return tuple(sorted((p.relative_to(folder).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                        for p in folder.rglob("*") if p.is_file()))


def prokka_database(executable: str) -> dict[str, Any]:
    """Prokka's database folder (Debian's package) with what it offers and the checksum of all its files."""
    info = prokka_tool.database_info(prokka_tool.database_source(executable))
    if info["ready"]:
        folder = Path(info["path"])
        info["checksum"] = _manifest_checksum(str(folder), _signature(folder))
        package = info["package"]
        info["key"] = PROKKA_DATABASE_KEY
        info["name"] = f"Prokka databases ({'Debian package ' + package[0] if package else 'folder ' + info['path']})"
        info["version"] = package[1] if package else None
    return info


def prokka_plan(db: Session, sample: Sample, a: Assembly, rfam: bool, use_genus: bool, genus: str | None,
                rename_contigs: bool) -> dict[str, Any]:
    tool = _tool("prokka")
    facts = assembly_facts(db, a)
    problems, steps, database, programs = [], {}, None, {}
    if tool["status"] == ToolStatus.available.value and tool["path"]:
        database = prokka_database(tool["path"])
        programs = prokka_tool.programs_found()
        if missing := prokka_tool.missing_programs(programs):
            problems.append({"code": "programs_missing", "message": f"Prokka needs {', '.join(missing)}, which "
                                                                    "is not installed"})
        if not database["ready"]:
            problems.append({"code": "no_database", "message": f"Prokka's databases were not found in "
                                                               f"{database['path']}"})
        steps = prokka_tool.plan_steps(programs, database, rfam, use_genus, genus)
    else:
        problems.append({"code": "tool_unavailable", "message": f"Prokka is not available ({tool['status']}): "
                                                                f"{tool['message']}"})
    if facts["prokka_name_problem"] and not rename_contigs:
        problems.append({"code": "contig_names", "message": facts["prokka_name_problem"] + "; annotate with renamed "
                                                                                            "contigs"})
    return {"annotator": "prokka", "tool": tool, "programs": programs, "steps": steps, "database": database,
            "assembly": facts, "translation_tables": list(bakta_tool.TRANSLATION_TABLES),
            "suggestions": {"locus_tag": suggested_locus_tag(sample), "rename_contigs": bool(facts["prokka_name_problem"]),
                            "translation_table": 11},
            "problems": problems}


# --- Step outcomes after a run -------------------------------------------------------------------------------

def bakta_outcome(steps: dict[str, dict[str, Any]], console: dict[str, Any], plot_written: bool) -> dict[str, Any]:
    out = {}
    for step, plan in steps.items():
        entry = {**plan, "found": console["found"].get(step)}
        if not plan["run"]:
            entry["status"] = "skipped"
        elif step == "crispr" and console["crispr_crashed"] is not None:
            entry.update(status="failed", reason="crashed", returncode=console["crispr_crashed"], found=None)
        elif step == "plot":
            entry["status"] = "searched" if plot_written else "failed"
        elif step in console["skipped"]:
            entry.update(status="skipped", reason="tool_skipped")
        else:
            entry["status"] = "searched"
        out[step] = entry
    return out


def prokka_outcome(steps: dict[str, dict[str, Any]], log: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for step, plan in steps.items():
        entry = {**plan, "found": log["counts"].get(step)}
        ran = plan["run"]
        if step == "ncrna" and ran and not log["ncrna_searched"]:
            entry.update(reason="tool_skipped")
            ran = False
        if step == "crispr" and ran and not log["crispr_searched"]:
            entry.update(reason="tool_skipped")
            ran = False
        entry["status"] = "searched" if ran else "skipped"
        out[step] = entry
    return out


# --- Finished annotations: features, details, exports ---------------------------------------------------------

def annotation_or_404(db: Session, annotation_id: str) -> Annotation:
    a = db.get(Annotation, annotation_id)
    if a is None:
        raise LookupError(annotation_id)
    return a


@lru_cache(maxsize=16)
def _features(path: str, mtime_ns: int, size: int) -> list[dict[str, Any]]:
    return read_jsonl(Path(path))


def features_of(annotation: Annotation) -> list[dict[str, Any]]:
    path = get_storage().resolve(annotation.features_path)
    try:
        st = path.stat()
    except OSError:
        raise FileNotFoundError("The features file of this annotation is missing on disk") from None
    return _features(str(path), st.st_mtime_ns, st.st_size)


def original_names(annotation: Annotation) -> dict[str, str]:
    return {s["id"]: s.get("original_id") or s["id"] for s in annotation.sequences}


def with_assembly_contig(f: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return {**f, "contig_in_assembly": names.get(f["contig"], f["contig"])}


def query_features(annotation: Annotation, **filters: Any) -> dict[str, Any]:
    result = query(features_of(annotation), annotation.sequences, **filters)
    names = original_names(annotation)
    return {"total": result["total"], "limit": filters.get("limit", 200), "offset": filters.get("offset", 0),
            "items": [with_assembly_contig(f, names) for f in result["items"]], "max_limit": MAX_QUERY_LIMIT}


def _file(annotation: Annotation, kind: str) -> Path | None:
    entry = (annotation.files or {}).get(kind)
    if not entry:
        return None
    path = get_storage().resolve(entry["path"])
    return path if path.is_file() else None


def _sequence(annotation: Annotation, kind: str, f: dict[str, Any]) -> dict[str, Any] | None:
    path = _file(annotation, kind)
    if path is None:
        return None
    for key in (f["locus_tag"], f["tool_id"]):
        if key and (rec := fasta_record(path, key)):
            seq = rec[1]
            return {"source": f"{annotation.tool}'s {kind} file", "header": rec[0], "length": len(seq),
                    "sequence": seq[:MAX_DETAIL_SEQUENCE], "truncated": len(seq) > MAX_DETAIL_SEQUENCE}
    return None


def feature_detail(annotation: Annotation, feature_id: int) -> dict[str, Any]:
    f = next((x for x in features_of(annotation) if x["id"] == feature_id), None)
    if f is None:
        raise LookupError(feature_id)
    return {**with_assembly_contig(f, original_names(annotation)), "links": links(f),
            "nucleotide": _sequence(annotation, "ffn", f),
            "protein": _sequence(annotation, "faa", f) if f["type"] in ("cds", "sorf") else None}


def selected(annotation: Annotation, ids: list[int] | None) -> list[dict[str, Any]]:
    features = features_of(annotation)
    if ids is None:
        return features
    if len(ids) > MAX_EXPORT_FEATURES:
        raise InputError(f"Export at most {MAX_EXPORT_FEATURES:,} selected features at once")
    by_id = {f["id"]: f for f in features}
    if missing := [i for i in ids if i not in by_id]:
        raise InputError(f"No feature {missing[0]} in this annotation")
    wanted = set(ids)
    return [f for f in features if f["id"] in wanted]


def tsv(annotation: Annotation, features: list[dict[str, Any]]) -> str:
    """ARVA's feature table; text cells that a spreadsheet would read as a formula get a leading apostrophe."""
    names = original_names(annotation)

    def cell(value: Any) -> str:
        if isinstance(value, list):
            value = "; ".join(map(str, value))
        elif isinstance(value, bool):
            value = "yes" if value else "no"
        text = "" if value is None else str(value)
        return sanitize_spreadsheet_cell(text.replace("\t", " ").replace("\n", " ").replace("\r", " "))

    rows = ["\t".join(TSV_COLUMNS)]
    for f in features:
        g = with_assembly_contig(f, names)
        rows.append("\t".join(cell(g[c]) for c in TSV_COLUMNS))
    return "\n".join(rows) + "\n"


def export(annotation: Annotation, fmt: str, ids: list[int] | None) -> tuple[str, str]:
    """(text, file suffix) of an export of all or the selected features. GFF3, GenBank and FASTA are the
    annotator's own files (all features) or their lines/records for the selected ones; TSV is ARVA's table."""
    if fmt not in EXPORT_FORMATS:
        raise InputError(f"format must be one of {', '.join(EXPORT_FORMATS)}")
    features = selected(annotation, ids)
    keys = {k for f in features for k in (f["locus_tag"], f["tool_id"]) if k}
    if fmt == "tsv":
        return tsv(annotation, features), "features.tsv"
    kind, suffix = {"gff3": ("gff3", "gff3"), "genbank": ("genbank", "gbk"), "fasta_nt": ("ffn", "ffn"),
                    "fasta_aa": ("faa", "faa")}[fmt]
    path = _file(annotation, kind)
    if path is None:
        raise FileNotFoundError(f"{annotation.tool}'s {kind} file is missing on disk")
    text = path.read_text(encoding="utf-8", errors="replace")
    if ids is None:
        return text, suffix
    if fmt == "gff3":
        return gff3_subset(text, keys), suffix
    if fmt == "genbank":
        return genbank_subset(text, {f["locus_tag"] for f in features if f["locus_tag"]}), suffix
    return fasta_subset(text, keys), suffix


def download_name(sample: Sample, annotation: Annotation, suffix: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{sample.sample_code}_{annotation.tool}_{annotation.id[:8]}").strip("._")
    return f"{stem or 'annotation'}.{suffix}"


# --- Plain-language step descriptions (reports; the interface builds its own from the codes) --------------------

STEP_LABELS = {"trna": "tRNA", "tmrna": "tmRNA", "rrna": "rRNA", "ncrna": "ncRNA", "ncrna_region": "ncRNA regions",
               "crispr": "CRISPR arrays", "cds": "CDS", "pseudo": "pseudogenes", "sorf": "small ORFs (sORFs)",
               "gap": "gaps", "ori": "origins of replication and transfer", "plot": "circular genome plot",
               "similarity": "protein similarity search", "genus": "genus-specific protein search",
               "hmm": "HMM search (HAMAP)", "signal_peptides": "signal peptides"}
_REASONS = {"user": "switched off for this run", "needs_cds": "needs the CDS step",
            "light_database": "Bakta detects pseudogenes only with the full database",
            "option_off": "not requested for this run", "database_lacks": "the database has none",
            "not_offered": "needs SignalP and a Gram-stain option, which ARVA does not offer",
            "not_supported": "Prokka does not predict them", "tool_skipped": "the annotator did not run it"}


def _dependency_text(d: dict[str, Any]) -> str:
    status = d.get("status")
    text = {"missing": "is not installed", "failed": "could not be run", "unreadable": "printed no version",
            "database_missing": "found no database in the Bakta database folder"}.get(status)
    if status == "too_old":
        text = f"{d.get('found')} is older than the {d.get('minimum')} required"
    elif status == "crashed":
        text = f"is installed but crashed on a test sequence (exit status {d.get('returncode')})"
    return f"{d['name']} {text or status}"


def describe_step(tool: str, step: str, s: dict[str, Any]) -> str:
    label = "tRNA and tmRNA" if tool == "Prokka" and step == "trna" else STEP_LABELS.get(step, step)
    status = s.get("status") or ("planned" if s.get("run") else "skipped")
    if status in ("searched", "planned"):
        found = s.get("found")
        return f"{label}: searched" + (f" ({found:,} found)" if isinstance(found, int) else "")
    if status == "failed":
        return (f"{label}: search failed — the program crashed during the run (exit status {s.get('returncode')}); "
                "no result" if s.get("reason") == "crashed" else f"{label}: failed")
    if s.get("reason") == "dependency":
        return f"{label}: not searched — " + "; ".join(_dependency_text(d) for d in s.get("dependencies") or [])
    return f"{label}: not searched — {_REASONS.get(s.get('reason'), s.get('reason') or 'skipped')}"
