"""Variant analysis: a sample's reads aligned to a reference (minimap2 for long reads, BWA-MEM for short reads),
haploid SNP and indel calls with bcftools, ARVA's soft filters, and bcftools csq effects when the reference is an ARVA
assembly with an annotation. Across samples called against the same reference (same SHA-256), the SNP matrix and
pairwise SNP distances (arva_core.variants).

The reference is either an assembly in ARVA (any sample, any project) or a genome of a registered reference
collection. Every option that changes the result is written into the commands and recorded with the run.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from arva_core import variants as av
from arva_core.formats import is_gzip
from arva_tools import ToolStatus
from arva_tools.bcftools import (
    COMMANDS,
    FILTER_DEFAULTS,
    MAX_DEPTH_DEFAULT,
    PROFILES,
    BcftoolsAdapter,
    VariantParams,
    flags_used,
)
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    FileFormat,
    JobStatus,
    Project,
    ReferenceDatabase,
    Sample,
    SequencingTechnology,
    VariantCall,
)
from app.services import databases as dbs
from app.services.annotation import original_names
from app.services.performance import effective_resources
from app.services.short_hybrid import Inputs
from app.storage import get_storage

VARIANT_JOB = "variant_calling"
ALIGNERS = {"illumina": ("bwa", None), "ont": ("minimap2", "map-ont"), "pacbio_hifi": ("minimap2", "map-hifi")}
TECH_FROM_SAMPLE = {SequencingTechnology.illumina: "illumina", SequencingTechnology.nanopore: "ont",
                    SequencingTechnology.pacbio: "pacbio_hifi"}
MAX_LIST = 2000
GENOME_MATCHES = 50


class InputError(ValueError):
    def __init__(self, message: str, code: str = "variants_invalid", **params: Any):
        super().__init__(message)
        self.code, self.params = code, params


def _tool(tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=False)
    return {"id": tool_id, "name": d.info.name, "status": d.status.value, "version": d.version, "path": d.path,
            "version_validated": d.version_validated, "message": d.message}


def tools_status(technology: str) -> dict[str, Any]:
    aligner, _ = ALIGNERS[technology]
    out = {k: _tool(k) for k in (aligner, "samtools", "bcftools")}
    b = out["bcftools"]
    b["missing_flags"] = []
    if b["status"] == ToolStatus.available.value and b["path"]:
        p = VariantParams(technology=technology)
        for command in COMMANDS:
            try:
                text = _help(b["path"], command)
            except (RuntimeError, OSError) as exc:
                b["missing_flags"].append(f"{command}: {exc}")
                continue
            wanted = flags_used(p)[command]
            b["missing_flags"] += [f"{command} {f}" for f in wanted
                                   if f in BcftoolsAdapter.missing_flags(command, text)]
    return out


@lru_cache(maxsize=32)
def _help(path: str, command: str) -> str:
    return BcftoolsAdapter.help_text(path, command)


def suggested_technology(sample: Sample) -> str | None:
    return TECH_FROM_SAMPLE.get(sample.sequencing_technology)


def _latest_annotation(db: Session, assembly_id: str) -> Annotation | None:
    return db.scalars(select(Annotation).where(Annotation.assembly_id == assembly_id)
                      .order_by(Annotation.created_at.desc())).first()


def _assembly_label(db: Session, a: Assembly) -> str:
    s = db.get(Sample, a.sample_id)
    code = s.sample_code if s else a.id[:8]
    return f"{code} · {a.assembler}{' (polished)' if a.kind.value == 'polished' else ''}"


def reference_options(db: Session, sample: Sample) -> dict[str, Any]:
    """The assemblies ARVA holds (this project's first) and the usable reference collections."""
    rows = db.scalars(select(Assembly).order_by(Assembly.created_at.desc()).limit(MAX_LIST)).all()
    samples = {s.id: s for s in db.scalars(select(Sample).where(Sample.id.in_({a.sample_id for a in rows})))}
    assemblies = []
    for a in rows:
        s = samples.get(a.sample_id)
        an = _latest_annotation(db, a.id)
        assemblies.append({
            "assembly_id": a.id, "label": _assembly_label(db, a), "sample_id": a.sample_id,
            "sample_code": s.sample_code if s else None, "same_project": bool(s and s.project_id == sample.project_id),
            "own_sample": a.sample_id == sample.id, "kind": a.kind.value, "assembler": a.assembler,
            "contigs": a.stats.get("contig_count"), "total_length": a.stats.get("total_length"),
            "annotation": {"id": an.id, "tool": an.tool, "tool_version": an.tool_version} if an else None,
        })
    assemblies.sort(key=lambda r: (not r["same_project"], r["own_sample"]))
    collections = []
    for r in db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == "reference_genomes",
                                                        ReferenceDatabase.status.in_(dbs.USABLE))):
        present = [g for g in r.inventory or [] if g.get("present")]
        collections.append({"database_id": r.id, "name": r.name, "version": r.version, "genomes": len(present),
                            "available": dbs.usable_now(r)})
    return {"assemblies": assemblies, "collections": collections}


def collection_genomes(db: Session, database_id: str, query: str) -> list[dict[str, Any]]:
    record = db.get(ReferenceDatabase, database_id)
    if record is None or record.kind != "reference_genomes":
        raise InputError("The chosen database is not a reference genome collection", "variants_no_collection")
    q = query.strip().lower()
    out = []
    for g in record.inventory or []:
        if not g.get("present"):
            continue
        text = " ".join(str(g.get(k) or "") for k in ("accession", "organism", "strain", "key")).lower()
        if not q or q in text:
            out.append({"key": g["key"], "accession": g.get("accession"), "organism": g.get("organism"),
                        "strain": g.get("strain"), "size": g.get("size")})
            if len(out) >= GENOME_MATCHES:
                break
    return out


def read_fasta_lengths(path: Path) -> tuple[list[dict[str, Any]], str]:
    """The contigs (name, length) of a FASTA file, plain or gzip, and the SHA-256 of its uncompressed bytes (what the
    aligner reads after ARVA copies it)."""
    h = hashlib.sha256()
    contigs: list[dict[str, Any]] = []
    opener = gzip.open if is_gzip(path) else open
    with opener(path, "rb") as fh:
        for line in fh:
            h.update(line)
            if line.startswith(b">"):
                name = line[1:].split(None, 1)[0].decode(errors="replace") if line[1:].strip() else ""
                contigs.append({"name": name, "length": 0})
            elif contigs:
                contigs[-1]["length"] += len(line.strip())
    return contigs, h.hexdigest()


def resolve_reference(db: Session, ref: dict[str, Any]) -> dict[str, Any]:
    """The snapshot of the reference a run will use. `ref` is {"kind": "assembly", "assembly_id"} or
    {"kind": "collection", "database_id", "genome_key"}."""
    kind = ref.get("kind")
    if kind == "assembly":
        a = db.get(Assembly, ref.get("assembly_id") or "")
        if a is None:
            raise InputError("The reference assembly does not exist", "variants_reference_missing")
        path = get_storage().resolve(a.contigs_path)
        if not path.is_file():
            raise InputError("The reference assembly's contigs file is missing on disk", "variants_reference_missing")
        contigs, sha = read_fasta_lengths(path)
        an = _latest_annotation(db, a.id)
        s = db.get(Sample, a.sample_id)
        return {"kind": "assembly", "label": _assembly_label(db, a), "assembly_id": a.id, "sample_id": a.sample_id,
                "sample_code": s.sample_code if s else None, "assembler": a.assembler, "assembly_kind": a.kind.value,
                "path": a.contigs_path, "sha256": sha, "contigs": contigs,
                "total_length": sum(c["length"] for c in contigs),
                "annotation": ({"id": an.id, "tool": an.tool, "tool_version": an.tool_version,
                                "database_version": an.database_version} if an else None)}
    if kind == "collection":
        record = db.get(ReferenceDatabase, ref.get("database_id") or "")
        if record is None or record.kind != "reference_genomes":
            raise InputError("The chosen database is not a reference genome collection", "variants_no_collection")
        if not dbs.usable_now(record):
            raise InputError(f"{record.name} cannot be used now ({record.status.value})", "variants_collection_unusable",
                             name=record.name)
        g = next((g for g in record.inventory or [] if g.get("key") == ref.get("genome_key") and g.get("present")), None)
        if g is None:
            raise InputError("That genome is not in the collection", "variants_genome_missing")
        path = Path(g["path"])
        if not path.is_file():
            raise InputError("The genome's file is missing", "variants_genome_missing")
        contigs, sha = read_fasta_lengths(path)
        label = " ".join(x for x in (g.get("organism"), g.get("strain"), g.get("accession")) if x) or g["key"]
        return {"kind": "collection", "label": label, "database_id": record.id, "database_name": record.name,
                "database_version": record.version, "genome_key": g["key"], "accession": g.get("accession"),
                "organism": g.get("organism"), "path": str(path), "sha256": sha, "contigs": contigs,
                "total_length": sum(c["length"] for c in contigs), "annotation": None}
    raise InputError("Choose an assembly or a genome of a reference collection as the reference",
                     "variants_reference_kind")


def check_reads(technology: str, inputs: Inputs) -> list[str]:
    """Which roles a technology takes; raises InputError for any other combination or a file that is not FASTQ."""
    if technology == "illumina":
        if inputs.long or (inputs.r1 is None) != (inputs.r2 is None) or (inputs.r1 and inputs.unpaired) or \
                not (inputs.r1 or inputs.unpaired):
            raise InputError("Short reads take either the two files of a pair (R1 and R2) or one file of unpaired "
                             "reads", "variants_reads_short")
    elif inputs.long is None or inputs.short:
        raise InputError("Long reads take one file of long reads", "variants_reads_long")
    for f in inputs.files():
        if f.file_format not in (FileFormat.fastq, FileFormat.fastq_gz):
            raise InputError(f"{f.original_filename} is not a FASTQ file", "variants_not_fastq",
                             file=f.original_filename)
        if not f.is_valid:
            raise InputError(f"{f.original_filename} failed validation", "variants_file_invalid",
                             file=f.original_filename)
    return list(inputs.by_role())


def read_group_sample(sample: Sample) -> str:
    """The sample name written in the BAM read group and the VCF: the sample code with any other character than
    letters, digits, '.', '_' and '-' replaced by '_'."""
    safe = "".join(ch if (ch.isalnum() and ch.isascii()) or ch in "._-" else "_" for ch in sample.sample_code)
    return (safe or "sample")[:64]


def plan(db: Session, sample: Sample, technology: str, ref: dict[str, Any], inputs: Inputs,
         params: VariantParams, use_annotation: bool) -> dict[str, Any]:
    if technology not in ALIGNERS:
        raise InputError("Unknown sequencing technology", "variants_technology")
    roles = check_reads(technology, inputs)
    reference = resolve_reference(db, ref)
    params.validate()
    tools = tools_status(technology)
    problems: list[dict[str, Any]] = []
    for t in tools.values():
        if t["status"] != ToolStatus.available.value:
            problems.append({"code": "tool_unavailable", "params": {"tool": t["name"], "status": t["status"]},
                             "message": f"{t['name']} is not available ({t['status']}): {t['message']}"})
    if tools["bcftools"]["missing_flags"]:
        flags = ", ".join(tools["bcftools"]["missing_flags"])
        problems.append({"code": "flags_missing", "params": {"tool": "bcftools", "flags": flags},
                         "message": f"This bcftools does not list: {flags}"})
    notes: list[dict[str, Any]] = []
    suggested = suggested_technology(sample)
    if suggested and suggested != technology:
        notes.append({"code": "technology_differs", "params": {"sample": sample.sequencing_technology.value,
                                                               "chosen": technology},
                      "message": f"The sample's recorded technology is {sample.sequencing_technology.value}; "
                                 f"the run uses the {technology} settings"})
    if not PROFILES[technology]["call_indels"] or not params.call_indels:
        notes.append({"code": "no_indels", "params": {},
                      "message": "Indels are not called (bcftools' Nanopore profile skips them: -I)"})
    effects = use_annotation and reference["annotation"] is not None
    if reference["kind"] == "assembly" and reference["assembly_id"] in {a.id for a in sample_assemblies(db, sample)}:
        notes.append({"code": "own_assembly", "params": {},
                      "message": "The reference is an assembly of this sample: the calls show where the reads "
                                 "disagree with it (residual errors, mixed populations, repeats), not differences "
                                 "from another strain"})
    if not effects:
        notes.append({"code": "no_effects", "params": {},
                      "message": "Effects are not annotated: the reference has no ARVA annotation" if
                      reference["annotation"] is None else "Effects are not annotated (not chosen)"})
    aligner, preset = ALIGNERS[technology]
    res = effective_resources(db)
    return {"technology": technology, "suggested_technology": suggested, "roles": roles, "reference": reference,
            "aligner": {"tool": aligner, "preset": preset}, "tools": tools, "settings": params.as_dict(),
            "effects": effects, "problems": problems, "notes": notes, "read_group_sample": read_group_sample(sample),
            "resources": {"threads": res.cap_threads(params.threads), "max_threads": res.threads}}


def sample_assemblies(db: Session, sample: Sample) -> list[Assembly]:
    return list(db.scalars(select(Assembly).where(Assembly.sample_id == sample.id)))


def defaults() -> dict[str, Any]:
    return {"profiles": PROFILES, "filters": FILTER_DEFAULTS, "max_depth": MAX_DEPTH_DEFAULT,
            "sources": {"filters": "Snippy 4.6.0 (bin/snippy defaults; README: 10 and 0.9 are commonly used)",
                        "profiles": "bcftools 1.19 mpileup -X profiles (illumina = defaults, ont, pacbio-ccs)",
                        "max_depth": "ARVA's choice (bcftools' own default is 250)"}}


# ---- results ----

def _variants_path(vc: VariantCall) -> Path | None:
    entry = (vc.files or {}).get("variants")
    return get_storage().resolve(entry["path"]) if entry else None


@lru_cache(maxsize=16)
def _load(path: str, mtime_ns: int, size: int) -> dict[str, Any]:
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def variant_data(vc: VariantCall) -> dict[str, Any]:
    """The run's records ("variants") and low-depth intervals ("low_depth") from its results file."""
    p = _variants_path(vc)
    if p is None or not p.is_file():
        return {"variants": [], "low_depth": {}}
    st = p.stat()
    return _load(str(p), st.st_mtime_ns, st.st_size)


def brief(vc: VariantCall, job: AnalysisJob | None = None) -> dict[str, Any]:
    s = vc.summary or {}
    return {"id": vc.id, "job_id": vc.job_id, "sample_id": vc.sample_id, "created_at": vc.created_at,
            "reference": {k: v for k, v in vc.reference.items() if k != "contigs"},
            "reference_sha256": vc.reference_sha256, "technology": vc.technology, "aligner": vc.aligner,
            "aligner_version": vc.aligner_version, "caller_version": vc.caller_version, "reads": vc.reads,
            "parameters": vc.parameters, "summary": s, "warnings": vc.warnings,
            "files": {k: {kk: vv for kk, vv in v.items() if kk != "path"} for k, v in (vc.files or {}).items()},
            "duration_seconds": job.duration_seconds if job else None}


def sample_runs(db: Session, sample_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(select(VariantCall).where(VariantCall.sample_id == sample_id)
                      .order_by(VariantCall.created_at.desc())).all()
    return [brief(vc, db.get(AnalysisJob, vc.job_id)) for vc in rows]


def query_variants(vc: VariantCall, *, status: str = "all", types: list[str] | None = None, contig: str | None = None,
                   effect: str | None = None, text: str | None = None, offset: int = 0,
                   limit: int = 200) -> dict[str, Any]:
    rows = variant_data(vc)["variants"]
    if status == "pass":
        rows = [v for v in rows if v["pass"]]
    elif status == "filtered":
        rows = [v for v in rows if not v["pass"]]
    if types:
        rows = [v for v in rows if v["type"] in types]
    if contig:
        rows = [v for v in rows if v["contig"] == contig]
    if effect:
        rows = [v for v in rows if (v["effect"] or "none") == effect]
    if text:
        t = text.lower()
        rows = [v for v in rows if any(t in (c.get(k) or "").lower() for c in v["consequences"]
                                       for k in ("gene", "transcript", "aa_change"))]
    return {"total": len(rows), "offset": offset, "variants": rows[offset:offset + limit]}


CSV_COLUMNS = ("contig", "pos", "ref", "alt", "type", "qual", "filter", "depth", "ref_reads", "alt_reads",
               "alt_fraction", "effect", "gene", "transcript", "aa_change", "dna_change", "start_codon")


def variants_csv(vc: VariantCall) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for v in variant_data(vc)["variants"]:
        c = next((c for c in v["consequences"] if "see_position" not in c), {})
        w.writerow([v["contig"], v["pos"], v["ref"], v["alt"], v["type"], v["qual"],
                    ";".join(v["filters"]) or "PASS", v["depth"], v["ref_reads"], v["alt_reads"], v["alt_fraction"],
                    v["effect"] or "", c.get("gene") or "", c.get("transcript") or "", c.get("aa_change") or "",
                    c.get("dna_change") or "", v.get("start_codon") or ""])
    return out.getvalue()


def file_path(vc: VariantCall, kind: str) -> Path | None:
    entry = (vc.files or {}).get(kind)
    if entry is None:
        return None
    p = get_storage().resolve(entry["path"])
    return p if p.is_file() else None


def download_name(sample: Sample | None, vc: VariantCall, suffix: str) -> str:
    code = read_group_sample(sample) if sample else "sample"
    return f"{code}_variants_{vc.job_id[:8]}{suffix}"


# ---- across samples ----

def _latest_per_sample(db: Session, project: Project) -> list[VariantCall]:
    rows = db.scalars(select(VariantCall).join(Sample, Sample.id == VariantCall.sample_id)
                      .where(Sample.project_id == project.id).order_by(VariantCall.created_at.desc())).all()
    seen: set[tuple[str, str]] = set()
    out = []
    for vc in rows:
        key = (vc.sample_id, vc.reference_sha256)
        if key not in seen:
            seen.add(key)
            out.append(vc)
    return out


def project_overview(db: Session, project: Project) -> dict[str, Any]:
    """Per reference (by SHA-256): the most recent run of each sample with its counts."""
    groups: dict[str, dict[str, Any]] = {}
    for vc in _latest_per_sample(db, project):
        g = groups.setdefault(vc.reference_sha256, {"reference_sha256": vc.reference_sha256,
                                                    "reference": {k: v for k, v in vc.reference.items()
                                                                  if k != "contigs"}, "runs": []})
        s = db.get(Sample, vc.sample_id)
        summ = vc.summary or {}
        g["runs"].append({"id": vc.id, "job_id": vc.job_id, "sample_id": vc.sample_id,
                          "sample_code": s.sample_code if s else None, "technology": vc.technology,
                          "created_at": vc.created_at, "pass": summ.get("pass"), "records": summ.get("records"),
                          "by_type": summ.get("by_type"), "by_effect": summ.get("by_effect"),
                          "callable_percent": summ.get("callable_percent"),
                          "mapped_percent": (summ.get("alignment") or {}).get("mapped_percent")})
    out = sorted(groups.values(), key=lambda g: -len(g["runs"]))
    for g in out:
        g["runs"].sort(key=lambda r: r["sample_code"] or "")
    return {"project_id": project.id, "references": out}


def matrix(db: Session, project: Project, reference_sha256: str) -> dict[str, Any]:
    runs = [vc for vc in _latest_per_sample(db, project) if vc.reference_sha256 == reference_sha256]
    if len(runs) < 2:
        raise InputError("The SNP matrix needs at least two samples called against this reference",
                         "variants_matrix_too_few")
    samples = []
    for vc in sorted(runs, key=lambda r: (db.get(Sample, r.sample_id).sample_code if db.get(Sample, r.sample_id)
                                          else "")):
        s = db.get(Sample, vc.sample_id)
        data = variant_data(vc)
        samples.append({"id": vc.id, "label": s.sample_code if s else vc.sample_id, "variants": data["variants"],
                        "low_depth": (data.get("low_depth") or {}).get("intervals") or {}})
    m = av.snp_matrix(samples)
    m["runs"] = [{"id": vc.id, "job_id": vc.job_id, "sample_id": vc.sample_id, "technology": vc.technology,
                  "min_depth": (vc.parameters.get("settings") or {}).get("min_depth")} for vc in runs]
    m["reference"] = {k: v for k, v in runs[0].reference.items() if k != "contigs"}
    m["reference_sha256"] = reference_sha256
    settings = {json.dumps({k: (vc.parameters.get("settings") or {}).get(k) for k in
                            ("min_qual", "min_depth", "min_alt_fraction", "min_mapq", "min_baseq")}, sort_keys=True)
                for vc in runs}
    m["same_settings"] = len(settings) == 1
    return m


def matrix_csv(m: dict[str, Any], what: str) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    labels = [s["label"] for s in m["samples"]]
    if what == "distances":
        w.writerow(["", *labels])
        for label, row in zip(labels, m["distances"], strict=True):
            w.writerow([label, *row])
    else:
        w.writerow(["contig", "pos", "ref", *labels])
        for k, site in enumerate(m["sites"]):
            w.writerow([site["contig"], site["pos"], site["ref"], *(a[k] for a in m["alleles"])])
    return out.getvalue()


def matrix_fasta(m: dict[str, Any]) -> str:
    """The SNP sites as an alignment (one sequence per sample, N where the sample has no base), e.g. for a tree."""
    return "".join(f">{s['label']}\n{seq}\n" for s, seq in zip(m["samples"], m["alleles"], strict=True))


# ---- Genome Explorer ----

def annotation_track(db: Session, annotation: Annotation, contig: str | None, start: int | None, end: int | None,
                     run_id: str | None, visible: set[str] | None = None) -> dict[str, Any]:
    """The variant-calling runs whose reference is this annotation's assembly, and the records of one of them (the
    most recent unless `run_id`) in a region of a contig, named as the annotation names it (the annotator may have
    renamed the assembly's contigs; the records use the assembly's names). Runs of samples in projects outside
    `visible` (None: every project) are left out, and `run_id` is taken only from the runs listed."""
    query = (select(VariantCall, Sample).join(Sample, Sample.id == VariantCall.sample_id)
             .where(VariantCall.reference_assembly_id == annotation.assembly_id))
    if visible is not None:
        query = query.where(Sample.project_id.in_(visible))
    pairs = db.execute(query.order_by(VariantCall.created_at.desc())).all()
    runs = [vc for vc, _ in pairs]
    listed = []
    for vc, s in pairs:
        listed.append({"id": vc.id, "sample_code": s.sample_code if s else None, "technology": vc.technology,
                       "created_at": vc.created_at, "pass": (vc.summary or {}).get("pass")})
    chosen = next((vc for vc in runs if vc.id == run_id), runs[0] if runs else None)
    rows: list[dict[str, Any]] = []
    if contig:
        contig = original_names(annotation).get(contig, contig)
    if chosen is not None and contig:
        lo, hi = start or 1, end or 10**12
        rows = [v for v in variant_data(chosen)["variants"]
                if v["contig"] == contig and v["pos"] <= hi and v["end"] >= lo][:5000]
    return {"runs": listed, "run_id": chosen.id if chosen else None, "variants": rows}


def job_summary(db: Session, job: AnalysisJob) -> dict[str, Any] | None:
    if job.job_type != VARIANT_JOB or job.status is not JobStatus.completed:
        return None
    vc = db.scalar(select(VariantCall).where(VariantCall.job_id == job.id))
    return brief(vc, job) if vc else None
