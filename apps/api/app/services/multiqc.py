"""Which stored tool outputs go into a project's MultiQC report, and under which sample names."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from arva_tools.multiqc import report_text
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, FileOrigin, JobStatus, Project, QCResult, RawFile, Sample
from app.services.jobs import FASTP_JOB, FASTQC_JOB, FILTLONG_JOB, SEQKIT_JOB
from app.storage import get_storage

SELECTION_RULE = (
    "For each selected sample, ARVA uses the most recent completed FastQC and SeqKit result of each file and "
    "the most recent completed fastp and Filtlong result of each input file or read pair, and only results of "
    "files that ARVA has read in full (completed read statistics) and found valid. Results of derived "
    "(filtered) files are used only when derived files are included. A Filtlong run is used only if it had a "
    "target (--target_bases or --keep_percent): only then does Filtlong log the totals that MultiQC reads. "
    "Sample names in the report are '<sample ID> <file>' (R1/R2 or the file name); when two samples or files "
    "would get the same name, the first 8 characters of their ARVA IDs are added."
)
MODULE_ORDER = ("fastqc", "fastp", "seqkit", "filtlong")
# ARVA job type -> MultiQC module and the name of the job output that the module reads.
_SOURCES: dict[str, tuple[str, re.Pattern[str]]] = {
    FASTQC_JOB: ("fastqc", re.compile(r".+_fastqc\.zip")),
    FASTP_JOB: ("fastp", re.compile(r"fastp\.json")),
    SEQKIT_JOB: ("seqkit", re.compile(r"seqkit_stats\.tsv")),
    FILTLONG_JOB: ("filtlong", re.compile(r"filtlong\.log")),
}


class SelectionError(ValueError):
    pass


# The report reads localStorage and document.cookie, which throw in the opaque origin of a CSP sandbox;
# in-memory stand-ins let it render there instead of on ARVA's own origin.
STORAGE_SHIM = (
    b"<script>(function(){try{window.localStorage;return;}catch(e){}"
    b"var m=new Map();var s={getItem:function(k){k=String(k);return m.has(k)?m.get(k):null;},"
    b"setItem:function(k,v){m.set(String(k),String(v));},removeItem:function(k){m.delete(String(k));},"
    b"clear:function(){m.clear();},key:function(i){var k=Array.from(m.keys())[i];return k===undefined?null:k;},"
    b"get length(){return m.size;}};"
    b"Object.defineProperty(window,'localStorage',{value:s,configurable:true});"
    b"Object.defineProperty(document,'cookie',{get:function(){return '';},set:function(){},configurable:true});"
    b"})();</script>"
)
_HEAD = re.compile(rb"<head\b[^>]*>", re.IGNORECASE)


def sandboxed_report(html: bytes) -> bytes:
    """The report with STORAGE_SHIM as the first element of <head>, so it runs before the report's scripts."""
    m = _HEAD.search(html)
    at = m.end() if m else 0
    return html[:at] + STORAGE_SHIM + html[at:]


@dataclass
class PlannedInput:
    module: str
    name: str
    sample_id: str
    sample_code: str
    job_id: str
    tool_name: str
    tool_version: str
    finished_at: str | None
    file_ids: list[str]
    file_names: list[str]
    output_path: str


@dataclass
class Exclusion:
    sample_id: str
    sample_code: str
    reason: str
    module: str | None = None
    job_id: str | None = None
    file_names: list[str] = field(default_factory=list)


@dataclass
class Plan:
    inputs: list[PlannedInput]
    excluded: list[Exclusion]
    sample_ids: list[str]

    @property
    def modules(self) -> list[str]:
        return [m for m in MODULE_ORDER if any(i.module == m for i in self.inputs)]

    def as_dict(self) -> dict:
        return {
            "selection_rule": SELECTION_RULE,
            "modules": self.modules,
            "sample_ids": self.sample_ids,
            "inputs": [asdict(i) for i in self.inputs],
            "excluded": [asdict(e) for e in self.excluded],
        }


def _stem(name: str) -> str:
    name = re.sub(r"\.gz$", "", name, flags=re.I)
    return re.sub(r"\.(fastq|fq|fasta|fa|fna|fas)$", "", name, flags=re.I)


def _labels(files: list[RawFile], producers: dict[str, str]) -> dict[str, str]:
    """'R1'/'R2' or the file name, made unique within the sample."""
    def derived(f: RawFile) -> str:
        if f.origin is not FileOrigin.derived:
            return ""
        return f" after {producers.get(f.produced_by_job_id or '', 'filtering')}"

    labels = {f.id: (f.read_mate if f.read_mate in ("R1", "R2") else _stem(f.original_filename)) + derived(f)
              for f in files}
    counts = Counter(labels.values())
    for f in files:
        if counts[labels[f.id]] > 1:
            labels[f.id] = _stem(f.original_filename) + derived(f)
    counts = Counter(labels.values())
    for f in files:
        if counts[labels[f.id]] > 1:
            labels[f.id] += f" {f.id[:8]}"
    return labels


def _file_reason(files: list[RawFile | None], include_derived: bool, validated: set[str]) -> str | None:
    present = [f for f in files if f is not None]
    if len(present) < len(files):
        return "input_missing"
    if any(not f.is_valid for f in present):
        return "input_invalid"
    if not include_derived and any(f.origin is FileOrigin.derived for f in present):
        return "derived_input"
    if any(f.id not in validated for f in present):
        return "input_not_validated"
    return None


def _job_reason(job: AnalysisJob, module: str) -> str | None:
    params = job.parameters or {}
    if module == "filtlong" and params.get("target_bases") is None and params.get("keep_percent") is None:
        return "filtlong_without_target"
    return None


def _output(job: AnalysisJob) -> str | None:
    pattern = _SOURCES[job.job_type][1]
    storage = get_storage()
    for p in job.output_paths or []:
        if pattern.fullmatch(Path(p).name) and storage.resolve(p).is_file():
            return p
    return None


def plan(db: Session, project: Project, sample_ids: list[str] | None, include_derived: bool) -> Plan:
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    if sample_ids is not None:
        known = {s.id for s in samples}
        unknown = [i for i in dict.fromkeys(sample_ids) if i not in known]
        if unknown:
            raise SelectionError(f"Sample {unknown[0]} does not belong to this project")
        wanted = set(sample_ids)
        samples = [s for s in samples if s.id in wanted]
    ids = [s.id for s in samples]
    jobs = db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.sample_id.in_(ids), AnalysisJob.status == JobStatus.completed,
               AnalysisJob.job_type.in_(list(_SOURCES)))
        .order_by(AnalysisJob.finished_at.desc(), AnalysisJob.created_at.desc())
    ).all()
    files = {f.id: f for f in db.scalars(select(RawFile).where(RawFile.sample_id.in_(ids)))}
    # A completed ARVA statistics job is the only full validation of a file (import checks its start only).
    validated = set(db.scalars(select(QCResult.raw_file_id).where(QCResult.raw_file_id.in_(list(files)))))
    producer_ids = {f.produced_by_job_id for f in files.values() if f.produced_by_job_id}
    producers = {j.id: j.tool_name for j in db.scalars(select(AnalysisJob).where(AnalysisJob.id.in_(producer_ids)))}

    by_sample: dict[str, dict[tuple, list[AnalysisJob]]] = defaultdict(lambda: defaultdict(list))
    for job in jobs:
        by_sample[job.sample_id or ""][(job.job_type, tuple(job.input_raw_file_ids or []))].append(job)

    inputs: list[PlannedInput] = []
    excluded: list[Exclusion] = []
    for sample in samples:
        chosen: list[tuple[str, AnalysisJob, list[RawFile], str]] = []
        for (job_type, file_ids), group in by_sample[sample.id].items():
            module = _SOURCES[job_type][0]
            maybe_files = [files.get(i) for i in file_ids]
            file_names = [f.original_filename for f in maybe_files if f]
            if reason := _file_reason(maybe_files, include_derived, validated):
                excluded.append(Exclusion(sample.id, sample.sample_code, reason, module, group[0].id, file_names))
                continue
            job_files = [f for f in maybe_files if f]
            for job in group:
                reason = _job_reason(job, module)
                output = _output(job) if reason is None else None
                if output is not None:
                    chosen.append((module, job, job_files, output))
                    break
                excluded.append(Exclusion(sample.id, sample.sample_code, reason or "output_missing", module, job.id,
                                          file_names))
        if not chosen:
            excluded.append(Exclusion(sample.id, sample.sample_code, "no_outputs"))
            continue
        used = list({f.id: f for _, _, fs, _ in chosen for f in fs}.values())
        labels = _labels(used, producers)
        for module, job, job_files, output in chosen:
            inputs.append(PlannedInput(
                module=module,
                name=f"{sample.sample_code} {'+'.join(labels[f.id] for f in job_files)}",
                sample_id=sample.id,
                sample_code=sample.sample_code,
                job_id=job.id,
                tool_name=job.tool_name,
                tool_version=job.tool_version,
                finished_at=job.finished_at.isoformat() if job.finished_at else None,
                file_ids=[f.id for f in job_files],
                file_names=[f.original_filename for f in job_files],
                output_path=output,
            ))
    _assign_names(inputs)
    inputs.sort(key=lambda i: (i.sample_code, MODULE_ORDER.index(i.module), i.name))
    return Plan(inputs, excluded, ids)


def _assign_names(inputs: list[PlannedInput]) -> None:
    """One report name per sample and file set, in every module: MultiQC joins table rows by name, so two
    samples or files that clean up to the same text get their ARVA IDs appended (refused if that is not enough)."""
    texts: dict[tuple[str, ...], str] = {}
    for i in inputs:
        texts.setdefault((i.sample_id, *i.file_ids), i.name)
    names = {key: report_text(text) for key, text in texts.items()}
    by_name: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for key, name in names.items():
        by_name[name].append(key)
    for keys in by_name.values():
        if len(keys) < 2:
            continue
        per_sample = Counter(key[0] for key in keys)
        for key in keys:
            tags = [key[0][:8]] if len(per_sample) > 1 else []
            if per_sample[key[0]] > 1:
                tags.append("+".join(f[:8] for f in key[1:]))
            tag = " ".join(tags)
            names[key] = f"{report_text(texts[key], limit=117 - len(tag))} ({tag})"
    clashes = sorted(name for name, n in Counter(names.values()).items() if n > 1)
    if clashes:
        raise SelectionError("Results of different samples or files would share a name in the report: "
                             + ", ".join(clashes) + ". Rename the samples so that their IDs differ.")
    for i in inputs:
        i.name = names[(i.sample_id, *i.file_ids)]
