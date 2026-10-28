"""Batch QC over a project: one of ARVA's per-file analyses on the files of every sample (spec §27, first step).

The plan says, for each file and analysis, whether a job would be created or why not, so the user sees exactly
how many jobs each sample gets before confirming. Creating requires the id of the plan that was shown: when files
or results changed in between, the request is refused with the new plan instead of creating different jobs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from arva_core.seqstats import TOOL_NAME, TOOL_VERSION
from arva_tools import ToolStatus
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, FileFormat, FileOrigin, JobStatus, Project, RawFile, Sample
from app.services.jobs import FASTQ_STATS_JOB, FASTQC_JOB, SEQKIT_JOB, create_batch_qc_jobs
from app.services.raw_signal import is_raw_signal

ANALYSES = {"sequence_stats": FASTQ_STATS_JOB, "seqkit": SEQKIT_JOB, "fastqc": FASTQC_JOB}
FASTQ = {FileFormat.fastq, FileFormat.fastq_gz}
RUN = "run"
# Why a file gets no job, in the order they are checked.
SKIP_REASONS = ("derived_excluded", "raw_signal", "not_reads", "not_fastq", "invalid", "active", "completed")


class SelectionError(ValueError):
    pass


class PlanChangedError(RuntimeError):
    def __init__(self, plan: dict):
        self.plan = plan
        super().__init__(f"The files or results changed since the preview; {plan['total_jobs']} job(s) would now be "
                         "created. Review the new preview and confirm again")


@dataclass(frozen=True)
class Selection:
    analyses: tuple[str, ...]
    include_derived: bool
    recompute: bool
    sample_ids: tuple[str, ...] | None

    def as_dict(self) -> dict:
        return {"analyses": list(self.analyses), "include_derived": self.include_derived,
                "recompute": self.recompute, "sample_ids": list(self.sample_ids) if self.sample_ids else None}


def _decision(f: RawFile, analysis: str, sel: Selection, done: set, active: set) -> str:
    if f.origin is FileOrigin.derived and not sel.include_derived:
        return "derived_excluded"
    if is_raw_signal(f):
        return "raw_signal"
    if f.file_format is FileFormat.unknown:
        return "not_reads"
    if analysis == "fastqc" and f.file_format not in FASTQ:
        return "not_fastq"
    if not f.is_valid:
        return "invalid"
    if (analysis, f.id) in active:
        return "active"
    if (analysis, f.id) in done and not sel.recompute:
        return "completed"
    return RUN


def _tools(analyses: tuple[str, ...]) -> list[dict]:
    out = []
    for a in analyses:
        if a == "sequence_stats":
            out.append({"analysis": a, "tool": TOOL_NAME, "version": TOOL_VERSION, "available": True, "message": ""})
            continue
        d = detect(a)
        out.append({"analysis": a, "tool": d.info.name, "version": d.version,
                    "available": d.status is ToolStatus.available, "message": d.message})
    return out


def _samples(db: Session, project: Project, sel: Selection) -> list[Sample]:
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    if sel.sample_ids is None:
        return samples
    by_id = {s.id: s for s in samples}
    if missing := [i for i in sel.sample_ids if i not in by_id]:
        raise SelectionError(f"Sample {missing[0]} does not belong to this project")
    wanted = set(sel.sample_ids)
    return [s for s in samples if s.id in wanted]


def plan(db: Session, project: Project, sel: Selection) -> tuple[dict, dict[str, list[tuple[Sample, RawFile]]]]:
    """The preview, and the (sample, file) pairs each analysis would run on."""
    samples = _samples(db, project, sel)
    ids = [s.id for s in samples]
    files = list(db.scalars(select(RawFile).where(RawFile.sample_id.in_(ids)).order_by(RawFile.uploaded_at,
                                                                                         RawFile.id))) if ids else []
    jobs = list(db.scalars(select(AnalysisJob).where(
        AnalysisJob.sample_id.in_(ids), AnalysisJob.job_type.in_([ANALYSES[a] for a in sel.analyses]),
        AnalysisJob.status.in_([JobStatus.pending, JobStatus.running, JobStatus.completed])))) if ids else []
    kind = {v: k for k, v in ANALYSES.items()}
    done = {(kind[j.job_type], fid) for j in jobs if j.status is JobStatus.completed for fid in j.input_raw_file_ids or []}
    active = {(kind[j.job_type], fid) for j in jobs if j.status is not JobStatus.completed
              for fid in j.input_raw_file_ids or []}

    runs: dict[str, list[tuple[Sample, RawFile]]] = {a: [] for a in sel.analyses}
    rows = []
    by_sample: dict[str, list[RawFile]] = {s.id: [] for s in samples}
    for f in files:
        by_sample[f.sample_id].append(f)
    for s in samples:
        counts = dict.fromkeys(sel.analyses, 0)
        file_rows = []
        for f in by_sample[s.id]:
            decisions = {a: _decision(f, a, sel, done, active) for a in sel.analyses}
            for a, d in decisions.items():
                if d == RUN:
                    counts[a] += 1
                    runs[a].append((s, f))
            file_rows.append({"file_id": f.id, "name": f.original_filename, "origin": f.origin.value,
                              "file_format": f.file_format.value, "decisions": decisions})
        rows.append({"sample_id": s.id, "sample_code": s.sample_code, "jobs": counts, "total": sum(counts.values()),
                     "files": file_rows})

    pairs = sorted((a, s.id, f.id) for a, items in runs.items() for s, f in items)
    plan_id = hashlib.sha256(json.dumps({"selection": sel.as_dict(), "runs": pairs}).encode()).hexdigest()[:32]
    totals = {a: len(runs[a]) for a in sel.analyses}
    return {
        "plan_id": plan_id, **sel.as_dict(), "tools": _tools(sel.analyses), "samples": rows, "totals": totals,
        "total_jobs": sum(totals.values()), "samples_with_jobs": sum(1 for r in rows if r["total"]),
    }, runs


def create(db: Session, project: Project, sel: Selection, plan_id: str) -> tuple[dict, list[AnalysisJob]]:
    preview, runs = plan(db, project, sel)
    if preview["plan_id"] != plan_id:
        raise PlanChangedError(preview)
    return preview, create_batch_qc_jobs(db, runs)
