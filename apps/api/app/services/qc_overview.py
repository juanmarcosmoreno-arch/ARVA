"""Project QC overview: one row per sample from completed jobs only, in four queries (rules: docs/scientific-methods.md)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, cast, select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, FileFormat, FileOrigin, JobStatus, QCResult, RawFile, Sample
from app.services import crosscheck
from app.services.jobs import FASTP_JOB, FASTQ_STATS_JOB, FASTQC_JOB, FILTLONG_JOB, SEQKIT_JOB
from app.services.metadata_table import spreadsheet_csv

READ_FORMATS = {FileFormat.fastq, FileFormat.fastq_gz, FileFormat.fasta, FileFormat.fasta_gz}
FASTQ_FORMATS = {FileFormat.fastq, FileFormat.fastq_gz}
FILTER_JOBS = (FASTP_JOB, FILTLONG_JOB)
FASTQC_COUNTS = ("pass_count", "warn_count", "fail_count")


@dataclass
class _Stats:
    read_count: int
    total_bases: int
    mean_length: float
    n50: int
    gc_percent: float
    mean_quality: float | None
    min_length: int
    max_length: int
    ambiguous_bases: int
    q20: float | None
    q30: float | None
    genome_size: int | None
    tool_version: str

    def crosscheck_input(self) -> dict[str, Any]:
        quality = None if self.q30 is None else {"q20_bases_percent": self.q20, "q30_bases_percent": self.q30}
        return {"read_count": self.read_count, "total_bases": self.total_bases, "min_length": self.min_length,
                "max_length": self.max_length, "mean_length": self.mean_length, "n50": self.n50,
                "gc_percent": self.gc_percent, "ambiguous_bases": self.ambiguous_bases, "quality": quality}


def _int(path: Any) -> Any:
    return cast(QCResult.metrics[path].as_string(), BigInteger)


def _latest_stats(db: Session, project_id: str) -> dict[str, _Stats]:
    """Newest completed ARVA statistics of every file; only the scalars used here are read from the JSON."""
    m = QCResult.metrics
    rows = db.execute(
        select(
            QCResult.raw_file_id, QCResult.read_count, QCResult.total_bases, QCResult.mean_length, QCResult.n50,
            QCResult.gc_percent, QCResult.mean_quality, _int("min_length"), _int("max_length"),
            _int("ambiguous_bases"), m[("quality", "q20_bases_percent")].as_float(),
            m[("quality", "q30_bases_percent")].as_float(),
            cast(m[("coverage_estimate", "expected_genome_size_bp")].as_string(), BigInteger),
            AnalysisJob.tool_version,
        )
        .join(AnalysisJob, QCResult.analysis_job_id == AnalysisJob.id)
        .where(AnalysisJob.project_id == project_id, AnalysisJob.status == JobStatus.completed,
               AnalysisJob.job_type == FASTQ_STATS_JOB)
        .order_by(AnalysisJob.finished_at.desc().nulls_last(), AnalysisJob.created_at.desc())
    ).all()
    latest: dict[str, _Stats] = {}
    for file_id, *values in rows:
        latest.setdefault(file_id, _Stats(*values))
    return latest


def _pooled(pairs: list[tuple[float, int]]) -> float | None:
    weight = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / weight if weight else None


def _percent(part: int, whole: int) -> float | None:
    return 100.0 * part / whole if whole else None


def build_overview(db: Session, project_id: str) -> list[dict[str, Any]]:
    samples = db.execute(
        select(Sample.id, Sample.sample_code, Sample.sequencing_technology)
        .where(Sample.project_id == project_id).order_by(Sample.sample_code)
    ).all()
    files = db.execute(
        select(RawFile.id, RawFile.sample_id, RawFile.original_filename, RawFile.file_format, RawFile.origin,
               RawFile.produced_by_job_id, RawFile.uploaded_at)
        .join(Sample, RawFile.sample_id == Sample.id)
        .where(Sample.project_id == project_id).order_by(RawFile.uploaded_at, RawFile.original_filename)
    ).all()
    jobs = db.execute(
        select(AnalysisJob.id, AnalysisJob.sample_id, AnalysisJob.job_type, AnalysisJob.tool_name,
               AnalysisJob.tool_version, AnalysisJob.finished_at, AnalysisJob.input_raw_file_ids,
               AnalysisJob.result_summary)
        .where(AnalysisJob.project_id == project_id, AnalysisJob.status == JobStatus.completed,
               AnalysisJob.job_type.in_([FASTQC_JOB, SEQKIT_JOB, *FILTER_JOBS]))
        .order_by(AnalysisJob.finished_at.desc().nulls_last(), AnalysisJob.created_at.desc())
    ).all()
    stats = _latest_stats(db, project_id)

    files_by_sample: dict[str, list] = defaultdict(list)
    outputs_of: dict[str, list] = defaultdict(list)
    for f in files:
        files_by_sample[f.sample_id].append(f)
        if f.produced_by_job_id:
            outputs_of[f.produced_by_job_id].append(f)
    names = {f.id: f.original_filename for f in files}
    # Newest completed job of each type for each input file; jobs arrive newest first.
    latest_for_file: dict[tuple[str, str], Any] = {}
    filters_by_sample: dict[str, list] = defaultdict(list)
    for j in jobs:
        for file_id in j.input_raw_file_ids or []:
            latest_for_file.setdefault((j.job_type, file_id), j)
        if j.job_type in FILTER_JOBS:
            filters_by_sample[j.sample_id].append(j)

    rows = []
    for s in samples:
        sample_files = files_by_sample[s.id]
        imported = [f for f in sample_files if f.origin is FileOrigin.imported]
        reads = [f for f in imported if f.file_format in READ_FORMATS]
        with_stats = [(f, stats[f.id]) for f in reads if f.id in stats]
        complete = bool(reads) and len(with_stats) == len(reads)
        row: dict[str, Any] = {
            "sample_id": s.id,
            "sample_code": s.sample_code,
            "sequencing_technology": s.sequencing_technology,
            "imported_files": len(imported),
            "derived_files": len(sample_files) - len(imported),
            "imported_read_files": len(reads),
            "imported_read_files_with_stats": len(with_stats),
            "stats_tool_versions": sorted({st.tool_version for _, st in with_stats}),
            "total_reads": None, "total_bases": None, "largest_file": None, "n50": None,
            "mean_read_quality": None, "q30_percent": None, "gc_percent": None,
            "expected_genome_size_bp": None, "genome_size_status": None, "estimated_depth": None,
            "filtering": _filtering(filters_by_sample[s.id], outputs_of, stats, names),
            "fastqc": _fastqc([f for f in imported if f.file_format in FASTQ_FORMATS], latest_for_file),
            "seqkit": _seqkit(reads, stats, latest_for_file),
        }
        if complete:
            total_bases = sum(st.total_bases for _, st in with_stats)
            # Most bases; ties go to the file imported first (files are in import order).
            big, big_stats = max(with_stats, key=lambda p: p[1].total_bases)
            sizes = {st.genome_size for _, st in with_stats}
            genome = next(iter(sizes)) if len(sizes) == 1 else None
            row.update({
                "total_reads": sum(st.read_count for _, st in with_stats),
                "total_bases": total_bases,
                "largest_file": {"file_id": big.id, "filename": big.original_filename,
                                 "total_bases": big_stats.total_bases},
                "n50": big_stats.n50,
                "mean_read_quality": big_stats.mean_quality,
                "q30_percent": _pooled([(st.q30, st.total_bases) for _, st in with_stats if st.q30 is not None]),
                "gc_percent": _pooled([(st.gc_percent, st.total_bases - st.ambiguous_bases) for _, st in with_stats]),
                "genome_size_status": "not_given" if sizes == {None} else "given" if genome else "inconsistent",
                "expected_genome_size_bp": genome,
                "estimated_depth": total_bases / genome if genome else None,
            })
        rows.append(row)
    return rows


def _filtering(runs: list, outputs_of: dict[str, list], stats: dict[str, _Stats], names: dict[str, str]):
    if not runs:
        return None
    job = runs[0]
    inputs = job.input_raw_file_ids or []
    outputs = outputs_of.get(job.id, [])
    measured = all(i in stats for i in inputs) and bool(outputs) and all(o.id in stats for o in outputs)
    kept_reads = kept_bases = None
    if measured:
        kept_reads = _percent(sum(stats[o.id].read_count for o in outputs), sum(stats[i].read_count for i in inputs))
        kept_bases = _percent(sum(stats[o.id].total_bases for o in outputs), sum(stats[i].total_bases for i in inputs))
    return {
        "job_id": job.id, "tool_name": job.tool_name, "tool_version": job.tool_version, "finished_at": job.finished_at,
        "runs": len(runs), "input_files": [names.get(i, i) for i in inputs],
        "output_files": [o.original_filename for o in outputs],
        "reads_kept_percent": kept_reads, "bases_kept_percent": kept_bases,
    }


def _fastqc(fastq_files: list, latest_for_file: dict) -> dict[str, int]:
    reports = [latest_for_file[(FASTQC_JOB, f.id)] for f in fastq_files if (FASTQC_JOB, f.id) in latest_for_file]
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for job in reports:
        for module in (job.result_summary or {}).get("modules", []):
            if module.get("status") in counts:
                counts[module["status"]] += 1
    return {"files": len(reports), "files_total": len(fastq_files), "pass_count": counts["PASS"],
            "warn_count": counts["WARN"], "fail_count": counts["FAIL"]}


def _seqkit(read_files: list, stats: dict[str, _Stats], latest_for_file: dict) -> dict[str, Any]:
    checked, differing = 0, []
    for f in read_files:
        job = latest_for_file.get((SEQKIT_JOB, f.id))
        seqkit_row = (job.result_summary or {}).get("seqkit_stats") if job else None
        if not seqkit_row or f.id not in stats:
            continue
        decided = [r for r in crosscheck.compare(stats[f.id].crosscheck_input(), seqkit_row) if r["agrees"] is not None]
        if decided:
            checked += 1
            differing += [r["metric"] for r in decided if not r["agrees"] and r["metric"] not in differing]
    status = ("disagree" if differing else "not_run" if checked == 0
              else "partial" if checked < len(read_files) else "agree")
    return {"status": status, "files_checked": checked, "files_total": len(read_files), "differing_metrics": differing}


CSV_HEADER = [
    "sample_code", "sample_id", "sequencing_technology", "imported_files", "derived_files", "imported_read_files",
    "imported_read_files_with_arva_statistics", "arva_statistics_versions", "total_reads_imported",
    "total_bases_imported", "largest_imported_read_file", "n50_bp_largest_file_arva",
    "mean_read_quality_largest_file_arva", "q30_bases_percent_imported_arva", "gc_percent_imported_arva",
    "expected_genome_size_bp", "genome_size_status", "estimated_depth_x", "filtering_tool", "filtering_tool_version",
    "filtering_runs", "filtering_reads_kept_percent_arva", "filtering_bases_kept_percent_arva",
    "fastqc_heuristics_pass_modules", "fastqc_heuristics_warn_modules", "fastqc_heuristics_fail_modules",
    "fastqc_files_with_report", "imported_fastq_files", "seqkit_crosscheck", "seqkit_files_checked",
    "seqkit_differing_metrics",
]


def _fmt(value: float | None, digits: int) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def render_csv(rows: list[dict[str, Any]]) -> bytes:
    table = []
    for r in rows:
        flt, fq, sk, big = r["filtering"] or {}, r["fastqc"], r["seqkit"], r["largest_file"] or {}
        table.append([
            r["sample_code"], r["sample_id"], r["sequencing_technology"].value, r["imported_files"],
            r["derived_files"], r["imported_read_files"], r["imported_read_files_with_stats"],
            " ".join(r["stats_tool_versions"]), r["total_reads"], r["total_bases"], big.get("filename"), r["n50"],
            _fmt(r["mean_read_quality"], 2), _fmt(r["q30_percent"], 2), _fmt(r["gc_percent"], 3),
            r["expected_genome_size_bp"], r["genome_size_status"], _fmt(r["estimated_depth"], 2),
            flt.get("tool_name"), flt.get("tool_version"), flt.get("runs"), _fmt(flt.get("reads_kept_percent"), 2),
            _fmt(flt.get("bases_kept_percent"), 2), *(fq[k] if fq["files"] else None for k in FASTQC_COUNTS),
            fq["files"], fq["files_total"], sk["status"], sk["files_checked"], "; ".join(sk["differing_metrics"]),
        ])
    return spreadsheet_csv(CSV_HEADER, table)
