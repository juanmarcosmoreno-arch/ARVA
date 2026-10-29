"""Basic sequencing-data reports (HTML / JSON / CSV) built only from stored results."""
from __future__ import annotations

import csv
import io
import json
import shlex
from datetime import UTC, datetime
from html import escape
from typing import Any

from arva_tools.fastp import removed_reads
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__ as ARVA_VERSION
from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    JobStatus,
    MlstResult,
    RawFile,
    Sample,
    SpeciesResult,
)
from app.services import annotation as annotation_svc
from app.services import crosscheck, genome_explorer, qc_data
from app.services import mlst as mlst_svc
from app.services import species as species_svc
from app.services.annotation import describe_step
from app.services.circular_svg import circular_map_svg
from app.services.jobs import (
    FASTP_JOB,
    FASTQ_STATS_JOB,
    FASTQC_JOB,
    FILTLONG_JOB,
    FLYE_JOB,
    NANOPLOT_JOB,
    PILON_JOB,
    POD5_JOB,
    QUAST_JOB,
    RACON_JOB,
    SEQKIT_JOB,
    SPADES_JOB,
    UNICYCLER_JOB,
)
from app.services.metadata_table import sanitize_spreadsheet_cell
from app.services.raw_signal import is_raw_signal
from app.services.read_headers import build_header_summary, dominant_format

LIMITATIONS = [
    "Statistics describe the reads as provided; they do not assess biological content, "
    "contamination or species identity.",
    "Quality scores are interpreted as Phred+33 and reflect the sequencer's own error model.",
    "Coverage, when shown, is total bases divided by a user-supplied genome size and is an "
    "approximation.",
    "No universal pass/fail thresholds are applied: suitable values depend on technology, "
    "chemistry and the intended analysis.",
    "Platform hints from read headers are suggestions: read names can be rewritten (e.g. by NCBI SRA), "
    "so headers without platform information say nothing about the platform used.",
]
ASSEMBLY_LIMITATIONS = [
    "Assembly warnings are heuristics with stated thresholds; they flag results worth checking, not errors.",
    "Contig coverage, circularity and repeat flags are the assembler's own values; contig lengths, N50/L50, "
    "N90/L90 and GC are computed by ARVA from the contigs file.",
    "Assembly N50 describes contigs, read N50 describes reads: the two are not comparable.",
    "Contig coverage means something different for each assembler: Flye reports mean read depth, SPAdes k-mer "
    "coverage (lower than read depth), Unicycler depth relative to the main replicons (about 1 for the "
    "chromosome). Values of different kinds are not comparable. SPAdes reports no circularity.",
]
POLISHING_LIMITATIONS = [
    "Polishing changes (dnadiff between draft and polished sequence, Pilon's list of changes) are direct evidence "
    "of what changed, not of improvement: a change is a correction only if the polished base is the true one, which "
    "only a trusted reference can show.",
    "Read alignment statistics before and after polishing (mapped reads, edit distance per aligned base) are "
    "indirect indicators: they mix read errors with assembly errors, and the reads were also used to polish.",
    "A polished contig's coverage is the mean depth of the polishing reads mapped to it (samtools coverage); its "
    "circularity is the draft assembler's report for the draft contig. Racon and Pilon treat every contig as linear.",
]
ANNOTATION_LIMITATIONS = [
    "Annotations are predictions: gene calls by Prodigal/Pyrodigal and functions transferred from database matches. "
    "A 'hypothetical protein' has no function assigned and is reported as such.",
    "A step that could not run on this computer (a program missing, too old or crashing) was skipped with the "
    "annotator's own option and is listed as not searched: its count is not zero, it is unknown.",
    "Coding density here is ARVA's: bases inside CDS (overlaps once) over non-N bases. Bakta's own 'coding ratio' "
    "counts every feature, gaps included, and is shown separately.",
    "Results on SYNTHETIC test data describe how the tools behave on that data, not any organism.",
    "The circular map draws every sequence on a circle whatever its topology (given in the sequence table); "
    "contigs of a draft assembly drawn next to each other are not known to be neighbours in the genome.",
    "Strand counts are of the sequences as written: leading and lagging strand need the replication origin and "
    "terminus, which ARVA does not locate. COG categories are shown only as the annotator reported them.",
]
COVERAGE_LABELS = {"read_depth": "mean read depth", "kmer_coverage": "k-mer coverage",
                   "relative_depth": "relative depth", "mapped_read_depth": "mean depth of mapped polishing reads"}
# QUAST fields copied into the HTML report (the JSON report keeps every field QUAST wrote).
QUAST_REPORT_FIELDS = (
    "# contigs", "Total length", "Largest contig", "GC (%)", "N50", "N90", "L50", "L90", "auN", "# N's per 100 kbp",
    "Genome fraction (%)", "Duplication ratio", "# misassemblies", "# local misassemblies", "# unaligned contigs",
    "# mismatches per 100 kbp", "# indels per 100 kbp", "NGA50",
)


def _read_headers(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    suggestion = meta.get("suggested_technology") or {}
    return {
        "header_format": dominant_format(meta),
        "platform": suggestion.get("value"),
        "confidence": suggestion.get("confidence", "none"),
        **{k: v for k, v in meta.items() if k != "mate_fingerprint"},
    }


def collect_report_data(db: Session, sample: Sample) -> dict[str, Any]:
    """Latest completed sequence-statistics result for each raw file of the sample."""
    files = db.scalars(
        select(RawFile).where(RawFile.sample_id == sample.id).order_by(RawFile.uploaded_at)
    ).all()
    jobs = db.scalars(
        select(AnalysisJob)
        .where(
            AnalysisJob.sample_id == sample.id,
            AnalysisJob.job_type == FASTQ_STATS_JOB,
            AnalysisJob.status == JobStatus.completed,
        )
        .order_by(AnalysisJob.finished_at.desc())
    ).all()
    latest: dict[str, tuple[AnalysisJob, Any]] = {}
    for job in jobs:
        for qc in job.qc_results:
            latest.setdefault(qc.raw_file_id, (job, qc))

    by_id = {f.id: f for f in files}
    entries = []
    for f in files:
        if is_raw_signal(f):
            continue
        job, qc = latest.get(f.id, (None, None))
        entries.append(
            {
                "file": {
                    "id": f.id,
                    "filename": f.original_filename,
                    "format": f.file_format.value,
                    "read_mate": f.read_mate,
                    "size_bytes": f.size_bytes,
                    "sha256": f.checksum_sha256,
                    "is_valid": f.is_valid,
                    "validation_message": f.validation_message,
                    "origin": f.origin.value,
                    "derived_from": by_id[f.parent_file_id].original_filename
                    if f.parent_file_id in by_id else None,
                    "produced_by_job_id": f.produced_by_job_id,
                },
                "analysis": None
                if job is None
                else {
                    "job_id": job.id,
                    "tool": job.tool_name,
                    "tool_version": job.tool_version,
                    "parameters": job.parameters,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "duration_seconds": job.duration_seconds,
                    "result_files": job.output_paths,
                    "log": job.log_text,
                },
                "metrics": None if qc is None else qc.metrics,
                "read_headers": _read_headers(f.header_metadata),
            }
        )

    project = sample.project
    return {
        "processing": _processing_steps(db, sample, latest),
        "report_type": "sequencing_data",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "arva_version": ARVA_VERSION,
        "project": {"id": project.id, "name": project.name, "is_demo": project.is_demo},
        "sample": {
            "id": sample.id,
            "sample_code": sample.sample_code,
            "organism": sample.organism,
            "expected_species": sample.expected_species,
            "sample_type": sample.sample_type,
            "host": sample.host,
            "geographic_origin": sample.geographic_origin,
            "collection_date": sample.collection_date.isoformat() if sample.collection_date else None,
            "sequencing_technology": sample.sequencing_technology.value,
            "sequencing_run": sample.sequencing_run,
            "researcher": sample.researcher,
            "institution": sample.institution,
        },
        "files": entries,
        "raw_signal_files": _raw_signal_files(db, sample, files),
        "read_header_summary": build_header_summary(db, sample),
        "assemblies": _assemblies(db, sample, by_id),
        "annotations": _annotations(db, sample),
        "mlst": _mlst(db, sample),
        "species": _species(db, sample),
        "limitations": LIMITATIONS,
    }


def _lineage(f: RawFile, by_id: dict[str, RawFile]) -> list[str]:
    """The file's name, then the name of each file it was derived from, back to the imported original."""
    names, seen = [f.original_filename], {f.id}
    while f.parent_file_id in by_id and f.parent_file_id not in seen:
        f = by_id[f.parent_file_id]
        seen.add(f.id)
        names.append(f.original_filename)
    return names


def _assemblies(db: Session, sample: Sample, by_id: dict[str, RawFile]) -> list[dict[str, Any]]:
    """Each assembly with its read inputs by lineage, the exact command, statistics, heuristic warnings and the
    metrics of every completed QUAST evaluation that included it."""
    assemblies = db.scalars(
        select(Assembly).where(Assembly.sample_id == sample.id).order_by(Assembly.created_at)
    ).all()
    if not assemblies:
        return []
    evaluations = db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.sample_id == sample.id, AnalysisJob.job_type == QUAST_JOB,
               AnalysisJob.status == JobStatus.completed)
        .order_by(AnalysisJob.finished_at)
    ).all()
    out = []
    for a in assemblies:
        job = db.get(AnalysisJob, a.job_id)
        st = a.stats
        inputs = []
        for file_id in a.input_file_ids:
            f = by_id.get(file_id)
            inputs.append({"file_id": file_id, "filename": f.original_filename if f else None,
                           "origin": f.origin.value if f else None, "sha256": f.checksum_sha256 if f else None,
                           "lineage": _lineage(f, by_id) if f else [],
                           "produced_by_job_id": f.produced_by_job_id if f else None})
        quast = []
        for q in evaluations:
            summary = q.result_summary or {}
            entry = next((e for e in summary.get("assemblies", []) if e["assembly_id"] == a.id), None)
            report = summary.get("report") or {}
            if entry is None or entry["label"] not in report.get("labels", []):
                continue
            i = report["labels"].index(entry["label"])
            check = next((c for c in summary.get("crosscheck", []) if c["assembly_id"] == a.id), None)
            quast.append({
                "job_id": q.id, "quast_version": summary.get("quast_version"), "label": entry["label"],
                "min_contig": summary.get("min_contig"),
                "reference": (summary.get("reference") or {}).get("name"),
                "assemblies_compared": [e["label"] for e in summary.get("assemblies", [])],
                "metrics": {r["field"]: r["values"][i] for r in report.get("rows", [])},
                "crosscheck_all_agree": check["all_agree"] if check else None,
                "finished_at": q.finished_at.isoformat() if q.finished_at else None,
            })
        out.append({
            "id": a.id,
            "kind": a.kind.value,
            "parent_assembly_id": a.parent_assembly_id,
            "polishing": _polishing(job) if a.kind.value == "polished" and job is not None else None,
            "assembler": a.assembler,
            "assembler_version": a.assembler_version,
            "mode": a.mode.value,
            "read_type": a.read_type,
            "coverage_kind": a.coverage_kind,
            "created_at": a.created_at.isoformat(),
            "inputs": inputs,
            "job": None if job is None else {
                "id": job.id, "tool": job.tool_name, "tool_version": job.tool_version, "tool_path": job.tool_path,
                "commands": [shlex.join(c) for c in job.commands or []], "parameters": job.parameters,
                "resources": job.resources,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "duration_seconds": job.duration_seconds,
            },
            "statistics": {k: st.get(k) for k in (
                "tool", "contig_count", "total_length", "largest_contig", "smallest_contig", "n50", "l50", "n90",
                "l90", "gc_percent", "n_count", "n_per_100kb", "other_iupac_count", "thresholds", "coverage",
                "circularity", "expected_genome_size", "length_histogram", "contig_rows")},
            "files": st.get("files"),
            "longest_contigs": a.contigs[:20],
            "warnings": a.warnings,
            "warning_checks": st.get("warning_checks", []),
            "quast": quast,
        })
    return out


def _annotations(db: Session, sample: Sample) -> list[dict[str, Any]]:
    """Each annotation with its annotator, database, settings, every step (searched, skipped and why, failed), ARVA's
    counts and the annotator's own statistics, the exact commands and the files with checksums."""
    out = []
    for a in db.scalars(select(Annotation).where(Annotation.sample_id == sample.id).order_by(Annotation.created_at)):
        job = db.get(AnalysisJob, a.job_id)
        params = {k: v for k, v in (a.parameters or {}).items() if k not in ("assembly",)}
        out.append({
            **_annotation_figures(db, sample, a),
            "id": a.id, "assembly_id": a.assembly_id, "assembly": (a.parameters or {}).get("assembly"),
            "tool": a.tool, "tool_version": a.tool_version, "created_at": a.created_at.isoformat(),
            "database": {"key": a.database_key, "name": a.database_name, "version": a.database_version,
                         "checksum": a.database_checksum},
            "parameters": params,
            "steps": a.steps,
            "steps_described": [describe_step(a.tool, k, v) for k, v in a.steps.items()],
            "summary": a.summary,
            "files": a.files,
            "job": None if job is None else {
                "id": job.id, "tool_path": job.tool_path, "commands": [shlex.join(c) for c in job.commands or []],
                "resources": job.resources,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "duration_seconds": job.duration_seconds,
                "programs": (job.result_summary or {}).get("programs"),
            },
        })
    return out


def _job_facts(job: AnalysisJob | None) -> dict[str, Any] | None:
    return None if job is None else {
        "id": job.id, "tool_path": job.tool_path, "commands": [shlex.join(c) for c in job.commands or []],
        "resources": job.resources, "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_seconds": job.duration_seconds,
    }


def _species(db: Session, sample: Sample) -> list[dict[str, Any]]:
    """Each species identification with the method, the database (kind, version, checksum), the ranked hits, ARVA's
    reading (status, thresholds with their sources, reasons, caveats), the consistency checks, warnings, settings,
    commands and files."""
    out = []
    for r in db.scalars(select(SpeciesResult).where(SpeciesResult.sample_id == sample.id)
                        .order_by(SpeciesResult.created_at)):
        i = r.interpretation or {}
        out.append({
            "id": r.id, "assembly_id": r.assembly_id, "method": r.method, "tool": r.tool,
            "tool_version": r.tool_version, "created_at": r.created_at.isoformat(), "status": r.status,
            "status_text": species_svc.reading_text(species_svc.STATUS_TEXT, {"status": r.status,
                                                                              "params": {"species": r.species}}),
            "species": r.species, "hits": r.hits, "interpretation": i,
            "reasons": [{**x, "text": species_svc.reading_text(species_svc.REASON_TEXT, x)} for x in i.get("reasons") or []],
            "caveats": [{**x, "text": species_svc.reading_text(species_svc.CAVEAT_TEXT, x)} for x in i.get("caveats") or []],
            "consistency": r.consistency,
            "warnings": [{**w, "text": species_svc.warning_text(w)} for w in r.warnings],
            "database": {"kind": r.database_kind, "name": r.database_name, "version": r.database_version,
                         "checksum": r.database_checksum,
                         "references_checksum": (r.details or {}).get("references_checksum"),
                         "references": len((r.details or {}).get("references") or [])},
            "parameters": (r.parameters or {}).get("settings"), "files": r.files,
            "job": _job_facts(db.get(AnalysisJob, r.job_id)),
        })
    return out


def _mlst(db: Session, sample: Sample) -> list[dict[str, Any]]:
    """Each MLST call with the scheme, ST, every locus's call and type, the clonal complex (from the scheme's
    profile file, when it has one), ARVA's warnings, the bundled database, the settings, commands and files."""
    out = []
    for m in db.scalars(select(MlstResult).where(MlstResult.sample_id == sample.id).order_by(MlstResult.created_at)):
        job = db.get(AnalysisJob, m.job_id)
        out.append({
            "id": m.id, "assembly_id": m.assembly_id, "assembly": (m.parameters or {}).get("assembly"),
            "tool": m.tool, "tool_version": m.tool_version, "created_at": m.created_at.isoformat(),
            "database": {"key": m.database_key, "name": m.database_name, "version": m.database_version,
                         "checksum": m.database_checksum, "terms": mlst_svc.TERMS},
            "parameters": {k: v for k, v in (m.parameters or {}).items() if k != "assembly"},
            "scheme": m.scheme, "st": m.st, "status": m.status, "score": m.score, "alleles": m.alleles,
            "clonal_complex": m.clonal_complex,
            "warnings": [{**w, "text": mlst_svc.warning_text(w)} for w in m.warnings],
            "scheme_info": (m.details or {}).get("scheme"), "ties": ((m.details or {}).get("log") or {}).get("ties"),
            "novel_alleles": (m.details or {}).get("novel_alleles"), "files": m.files,
            "job": None if job is None else {
                "id": job.id, "tool_path": job.tool_path, "commands": [shlex.join(c) for c in job.commands or []],
                "resources": job.resources,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "duration_seconds": job.duration_seconds,
            },
        })
    return out


def _annotation_figures(db: Session, sample: Sample, a: Annotation) -> dict[str, Any]:
    """The charts' numbers and the circular map (its summary for JSON, its SVG for HTML) of one annotation; when the
    annotation's files are missing, why there are none."""
    out: dict[str, Any] = {"charts": None, "map": None, "map_svg": None, "figures_unavailable": []}
    try:
        out["charts"] = annotation_svc.charts(a)
    except (FileNotFoundError, ValueError) as exc:
        out["figures_unavailable"].append(f"charts: {exc}")
    try:
        m = genome_explorer.genome_map(db, a, [], genome_explorer.REPORT_MAP_POINTS, None)
    except (LookupError, FileNotFoundError, ValueError) as exc:
        out["figures_unavailable"].append(f"circular map: {exc}")
        return out
    assembly = db.get(Assembly, a.assembly_id)
    circular = {c["name"]: c.get("circular") for c in (assembly.contigs if assembly else [])}
    by_id = {s["id"]: s for s in a.sequences}
    out["map"] = {
        "gc_window": m["gc"]["window"], "genome_gc": m["gc"]["genome_gc"], "features": m["total"],
        "coverage": {k: v for k, v in m["coverage"].items() if k != "source"}
        | {"job_id": (m["coverage"]["source"] or {}).get("job_id")},
        "sequences": [{"contig": s["contig"], "contig_in_assembly": s["contig_in_assembly"], "length": s["length"],
                       "gc": s["gc"]["contig_gc"], **_topology(by_id.get(s["contig"], {}), circular, a, assembly),
                       "mean_depth": s["coverage"].get("contig_mean_depth")} for s in m["sequences"]],
    }
    db_name = " ".join(x for x in (a.database_name, a.database_version) if x) or "the annotator's own"
    caption = (f"{sample.sample_code} · {a.tool} {a.tool_version} · database: {db_name} · features are the "
               f"annotator's predictions · drawn by ARVA {ARVA_VERSION}")
    out["map_svg"] = circular_map_svg(m, sample.sample_code, caption,
                                      bool((a.summary or {}).get("synthetic_evidence")))
    return out


def _topology(record: dict[str, Any], circular: dict[str, bool | None], a: Annotation,
              assembly: Assembly | None) -> dict[str, Any]:
    """The topology the annotator reported for a sequence, else the assembler's circularity flag, with its source."""
    if record.get("topology") in ("circular", "linear"):
        return {"topology": record["topology"], "topology_source": a.tool}
    flag = circular.get(record.get("original_id") or record.get("id"))
    if flag is None:
        return {"topology": None, "topology_source": None}
    return {"topology": "circular" if flag else "linear", "topology_source": assembly.assembler if assembly else None}


def _polishing(job: AnalysisJob) -> dict[str, Any] | None:
    """The polishing job's comparison of draft and polished assembly, labelled by kind of evidence."""
    s = job.result_summary or {}
    if not s:
        return None
    direct = s.get("direct") or {}
    diff = direct.get("dnadiff")
    return {
        "polisher": s.get("polisher"), "polisher_version": s.get("polisher_version"), "strategy": s.get("strategy"),
        "draft_assembly_id": (s.get("draft") or {}).get("assembly_id"), "rounds_run": s.get("rounds_run"),
        "rounds": [{"round": r["round"], "changes": r["changes"], "source": r["changes_source"]} for r in s["rounds"]],
        "direct_evidence": {"source": direct.get("source"),
                            "dnadiff_events": diff["events"] if diff else None,
                            "dnadiff_draft_unaligned_bases": diff["before"].get("unaligned_bases") if diff else None,
                            "pilon_changes": direct.get("pilon_changes")},
        "indirect_indicators": {"aligner": (s.get("indirect") or {}).get("aligner"),
                                "before": (s.get("indirect") or {}).get("before", {}).get("stats"),
                                "after": (s.get("indirect") or {}).get("after", {}).get("stats")},
        "assembly_statistics": s.get("assembly_stats"),
        "observations": s.get("observations", []),
        "helpers": [f"{h['name']} {h['version']}" for h in s.get("helpers", []) if h.get("version")],
    }


def _raw_signal_files(db: Session, sample: Sample, files: list[RawFile]) -> list[dict[str, Any]]:
    """POD5 files with their latest run metadata; fields that may identify people or devices are not included."""
    jobs = db.scalars(
        select(AnalysisJob)
        .where(AnalysisJob.sample_id == sample.id, AnalysisJob.job_type == POD5_JOB,
               AnalysisJob.status == JobStatus.completed)
        .order_by(AnalysisJob.finished_at.desc())
    ).all()
    out = []
    for f in files:
        if not is_raw_signal(f):
            continue
        job = next((j for j in jobs if f.id in (j.input_raw_file_ids or [])), None)
        out.append({
            "file": {"id": f.id, "filename": f.original_filename, "size_bytes": f.size_bytes, "sha256": f.checksum_sha256,
                     "is_valid": f.is_valid, "validation_message": f.validation_message},
            "run_metadata": None if job is None else {
                "job_id": job.id, "tool": job.tool_name, "tool_version": job.tool_version,
                "parameters": job.parameters,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                "summary": job.result_summary,
            },
        })
    return out


def _processing_steps(db: Session, sample: Sample, latest: dict) -> list[dict[str, Any]]:
    tool_jobs = db.scalars(
        select(AnalysisJob)
        .where(
            AnalysisJob.sample_id == sample.id,
            AnalysisJob.status == JobStatus.completed,
            AnalysisJob.job_type.in_([FASTP_JOB, FILTLONG_JOB, SEQKIT_JOB, FASTQC_JOB, NANOPLOT_JOB, FLYE_JOB,
                                      SPADES_JOB, UNICYCLER_JOB, QUAST_JOB, RACON_JOB, PILON_JOB]),
        )
        .order_by(AnalysisJob.finished_at)
    ).all()
    names = {f.id: f.original_filename for f in sample.raw_files}
    steps = []
    for j in tool_jobs:
        summary = j.result_summary or {}
        step: dict[str, Any] = {
            "job_id": j.id,
            "job_type": j.job_type,
            "tool": j.tool_name,
            "tool_version": j.tool_version,
            "inputs": [names.get(i, i) for i in j.input_raw_file_ids or []],
            "commands": [shlex.join(c) for c in j.commands or []],
            "resources": j.resources,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "highlights": [],
        }
        if j.job_type == FASTP_JOB and summary:
            b, a = summary["before_filtering"], summary["after_filtering"]
            step["highlights"] = [
                f"Reads {b['total_reads']:,} → {a['total_reads']:,}; bases {b['total_bases']:,} → {a['total_bases']:,}",
                "Removed (reads; both mates counted for pairs): "
                + removed_reads(summary.get("filtering_result", {}), (j.parameters or {}).get("length_limit") or 0),
            ]
            if summary.get("adapter_trimmed_reads") is None:
                step["highlights"].append("Adapter trimming: fastp reported none (trimming disabled, or no adapter "
                                          "detected in single-end reads)")
            else:
                step["highlights"].append(f"Reads with adapter trimmed: {summary['adapter_trimmed_reads']:,} "
                                          f"({summary.get('adapter_trimmed_bases') or 0:,} bases removed)")
            if summary.get("duplication_rate") is not None:
                step["highlights"].append(f"Duplication rate (fastp estimate): {100 * summary['duplication_rate']:.2f} %")
            step["highlights"] += _insert_size_highlight(j, summary)
        elif j.job_type == FILTLONG_JOB:
            step["highlights"] = _filtlong_highlights(j.parameters or {}, summary)
        elif j.job_type == SEQKIT_JOB and summary:
            file_id = (j.input_raw_file_ids or [None])[0]
            qc = latest.get(file_id, (None, None))[1]
            if qc is not None:
                rows = crosscheck.compare(qc.metrics, summary["seqkit_stats"])
                decided = [r for r in rows if r["agrees"] is not None]
                bad = [r["metric"] for r in decided if not r["agrees"]]
                step["highlights"] = [
                    f"Independent check: {len(decided) - len(bad)}/{len(decided)} metrics agree with ARVA"
                    + (f" (differ: {', '.join(bad)})" if bad else "")
                ]
        elif j.job_type == NANOPLOT_JOB and summary:
            st = summary["stats"]
            step["highlights"] = [
                f"NanoStats.txt: {st['number_of_reads']:,} reads, {st['number_of_bases']:,} bases; N50 {st['n50']:,} bp "
                "(NanoPlot's definition, ascending cumulative sum); mean read quality "
                f"Q{st['mean_qual']} (error-probability average of per-read qualities)",
            ]
            if summary.get("post_filtering"):
                step["highlights"].append(
                    f"NanoPlot removed {summary['artefact_reads_removed']} artefactual read(s) (length < 20, quality > 30) "
                    "after these statistics; see NanoStats_post_filtering.txt")
        elif j.job_type == FLYE_JOB and summary:
            step["highlights"] = _flye_highlights(db, j, summary)
        elif j.job_type in (SPADES_JOB, UNICYCLER_JOB) and summary:
            step["highlights"] = _short_hybrid_highlights(db, j, summary)
        elif j.job_type == QUAST_JOB and summary:
            step["highlights"] = _quast_highlights(summary)
        elif j.job_type in (RACON_JOB, PILON_JOB) and summary:
            step["highlights"] = _polishing_highlights(summary)
        elif j.job_type == FASTQC_JOB and summary:
            flags = {}
            for m in summary.get("modules", []):
                flags.setdefault(m["status"], []).append(m["module"])
            step["highlights"] = [
                f"FastQC flags — {status}: {', '.join(mods)}" for status, mods in sorted(flags.items())
            ] + _fastqc_data_highlights(qc_data.fastqc_summary(j))
        steps.append(step)
    return steps


def _flye_highlights(db: Session, job: AnalysisJob, summary: dict[str, Any]) -> list[str]:
    params = job.parameters or {}
    out = []
    assembly = db.scalar(select(Assembly).where(Assembly.job_id == job.id))
    if assembly is not None:
        st = assembly.stats
        out.append(f"Assembly ({assembly.read_type}): {st['contig_count']:,} contigs, {st['total_length']:,} bp, "
                   f"N50 {st['n50']:,} bp, largest {st['largest_contig']:,} bp; "
                   f"{st['circularity']['circular_contigs']} reported circular by Flye")
        if assembly.warnings:
            out.append("Heuristic warnings: " + ", ".join(w["code"] for w in assembly.warnings))
    log = summary.get("log") or {}
    if params.get("min_overlap"):
        out.append(f"Minimum overlap {params['min_overlap']:,} bp (set by the user)")
    elif "min_overlap" in log:
        out.append(f"Minimum overlap {log['min_overlap']:,} bp (chosen by Flye from the reads' N90)")
    if (params.get("threads") or 1) > 1:
        out.append(f"{params['threads']} threads: Flye's output can differ between runs and thread counts")
    return out


def _short_hybrid_highlights(db: Session, job: AnalysisJob, summary: dict[str, Any]) -> list[str]:
    params = job.parameters or {}
    out = []
    assembly = db.scalar(select(Assembly).where(Assembly.job_id == job.id))
    if assembly is not None:
        st = assembly.stats
        circular = ("circularity not reported by SPAdes" if assembly.assembler == "SPAdes" else
                    f"{st['circularity']['circular_contigs']} reported circular by Unicycler")
        out.append(f"Assembly ({assembly.mode.value}, {assembly.read_type}): {st['contig_count']:,} contigs, "
                   f"{st['total_length']:,} bp, N50 {st['n50']:,} bp, largest {st['largest_contig']:,} bp; {circular}")
        if assembly.warnings:
            out.append("Heuristic warnings: " + ", ".join(w["code"] for w in assembly.warnings))
    if job.job_type == SPADES_JOB:
        ks = ", ".join(map(str, summary.get("k_values") or []))
        out.append(f"SPAdes mode {params.get('mode')}; k = {ks} "
                   f"({'set by the user' if summary.get('k_source') == 'user' else 'chosen by SPAdes'}); "
                   f"--cov-cutoff {params.get('cov_cutoff')}; {summary.get('output', 'contigs')}.fasta registered")
        out.append("Contig coverage is SPAdes' k-mer coverage, not read depth")
    else:
        log = summary.get("log") or {}
        kmers = params.get("kmers") or log.get("kmer_range")
        out.append(f"Unicycler {summary.get('assembly_mode')} assembly, --mode {params.get('mode')}"
                   + (f"; SPAdes k-mer sizes {', '.join(map(str, kmers))}" if kmers else "")
                   + (f", best k {log['best_kmer']}" if log.get("best_kmer") else ""))
        helpers = [f"{h['name']} {h['version']}" for h in summary.get("helpers", []) if h.get("version")]
        if helpers:
            out.append("Helpers used: " + ", ".join(helpers))
        out.append("Contig depth is Unicycler's relative depth (about 1 for the chromosome), not read depth")
    return out


def _changes_line(changes: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v['events']:,} ({v['bases']:,} bp)" for k, v in changes.items() if v["events"]) or "none"


def _polishing_highlights(summary: dict[str, Any]) -> list[str]:
    draft = summary.get("draft") or {}
    out = [f"{summary['polisher']} {summary.get('polisher_version')} polished {draft.get('assembler')} "
           f"{draft.get('assembler_version')} assembly {str(draft.get('assembly_id', ''))[:8]} in "
           f"{summary.get('rounds_run')} round(s)"]
    for r in summary.get("rounds", []):
        source = {"dnadiff": "dnadiff", "pilon_changes": "Pilon's .changes"}.get(r.get("changes_source"))
        out.append(f"Round {r['round']} changes (direct evidence, {source}): {_changes_line(r['changes'])}"
                   if r.get("changes") else f"Round {r['round']}: no direct evidence (MUMmer dnadiff not installed)")
    ind = summary.get("indirect") or {}
    b, a = (ind.get("before") or {}).get("stats") or {}, (ind.get("after") or {}).get("stats") or {}
    if b.get("edit_distance_per_100_bases") is not None and a.get("edit_distance_per_100_bases") is not None:
        out.append(f"Indirect indicator ({ind.get('aligner')}): reads' edit distance per 100 aligned bases "
                   f"{b['edit_distance_per_100_bases']:.4f} → {a['edit_distance_per_100_bases']:.4f}")
    out += [f"Note [{o['code']}]: {o['message']}" for o in summary.get("observations", [])]
    return out


def _count(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else "—" if value is None else str(value)


def _quast_highlights(summary: dict[str, Any]) -> list[str]:
    ref = summary.get("reference")
    out = [f"{len(summary['assemblies'])} assembly(ies), minimum contig length {summary['min_contig']:,} bp; "
           + (f"reference {ref['name']}" if ref else "no reference (contiguity only)")]
    report = summary["report"]
    for i, label in enumerate(report["labels"]):
        v = {r["field"]: r["values"][i] for r in report["rows"]}
        line = (f"{label}: {_count(v.get('# contigs'))} contigs, {_count(v.get('Total length'))} bp, "
                f"N50 {_count(v.get('N50'))} bp, L50 {_count(v.get('L50'))}")
        if "Genome fraction (%)" in v:
            line += (f"; genome fraction {v['Genome fraction (%)']} %, {v.get('# misassemblies')} misassemblies, "
                     f"{v.get('# mismatches per 100 kbp')} mismatches and {v.get('# indels per 100 kbp')} indels per "
                     "100 kbp")
        out.append(line)
    for check in summary.get("crosscheck", []):
        rows = [r for r in check["rows"] if r["agrees"] is not None]
        bad = [r["metric"] for r in rows if not r["agrees"]]
        out.append(f"Independent check of {check['label']}: {len(rows) - len(bad)}/{len(rows)} metrics equal ARVA's at "
                   f"{summary['min_contig']:,} bp" + (f" (differ: {', '.join(bad)})" if bad else ""))
    return out


def _insert_size_highlight(job: AnalysisJob, summary: dict[str, Any]) -> list[str]:
    ins = summary.get("insert_size")
    if ins is None and summary.get("insert_size_peak") is not None:
        try:
            ins = qc_data.fastp_data(job)["insert_size"]
        except qc_data.QcDataError:
            return []
    if not ins or not ins["evaluated_pairs"]:
        return []
    threads = (job.parameters or {}).get("threads")
    source = f"the {ins['evaluated_pairs']:,} pairs read by fastp's worker thread 0 (--thread {threads})"
    if ins["peak"] is None:
        return [f"Insert size (fastp estimate): none of {source} overlapped"]
    return [f"Insert size peak (fastp estimate, depends on the thread count): {ins['peak']} bp, from {source}; "
            f"{100 * ins['overlapping_pairs'] / ins['evaluated_pairs']:.1f} % of them overlapped"]


def _filtlong_highlights(params: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    provenance = ("genome_size_bp", "target_coverage_x")
    chosen = {k: v for k, v in params.items()
              if v is not None and k not in provenance and not k.endswith(("weight", "window_size"))}
    out = ["Thresholds: " + ", ".join(f"{k}={v}" for k, v in chosen.items())]
    if params.get("genome_size_bp") is not None:
        out.append(f"Target bases {params['target_bases']:,} = round({params['target_coverage_x']:g}× coverage × "
                   f"{params['genome_size_bp']:,} bp genome size), computed by ARVA; Filtlong receives only "
                   "--target_bases")
    if summary.get("kept_bases_reported") is not None:
        out.append(f"Filtlong kept {summary['kept_bases_reported']:,} bases for a target of "
                   f"{summary['target_bases_reported']:,} (it may overshoot by up to one read)")
    elif summary.get("not_enough_reads_for_target"):
        out.append("Filtlong: not enough reads to reach the target, so no reads were removed to meet it")
    elif summary.get("below_target_after_filtering"):
        out.append("Filtlong: the reads left after the hard thresholds already fall below the target, so no "
                   "further reads were removed to meet it")
    return out


def _fastqc_data_highlights(s: dict[str, Any] | None) -> list[str]:
    if not s:
        return []
    out = []
    if ac := s.get("adapter_content"):
        found = [a for a in ac["adapters"] if a["max_percent"] > 0]
        detail = "; ".join(f"{a['name']} up to {a['max_percent']:.2f} % (first at position {a['first_position']})"
                           for a in found) or "no adapter sequence found at any position"
        out.append(f"Adapter content (FastQC, cumulative % of reads; FastQC heuristics: {ac['status']}): {detail}")
    if dup := s.get("duplication"):
        out.append(
            "Sequence duplication (FastQC estimate from the sequences first seen in the first 100,000 reads, "
            f"reads longer than 50 bp truncated to 50 bp; FastQC heuristics: {dup['status']}): "
            f"{dup['total_deduplicated_percent']:.2f} % of reads would remain if deduplicated "
            f"({dup['duplicate_percent']:.2f} % duplicates)"
        )
    return out


# --- CSV ----------------------------------------------------------------------

CSV_COLUMNS = [
    "sample_code", "filename", "origin", "derived_from", "format", "read_mate", "sha256", "reads", "total_bases",
    "min_length", "max_length", "mean_length", "median_length", "n50", "n90", "gc_percent",
    "ambiguous_percent", "mean_read_quality", "median_read_quality", "q20_bases_percent",
    "q30_bases_percent", "estimated_depth", "tool", "tool_version", "job_id", "finished_at",
    # Assembly summary rows (record_type "assembly") fill these and leave the read columns empty.
    "record_type", "assembly_id", "assembly_read_type", "assembly_inputs", "contigs", "assembly_total_length",
    "largest_contig", "contig_n50", "contig_l50", "contig_n90", "contig_l90", "assembly_gc_percent",
    "circular_contigs", "median_contig_coverage", "contig_coverage_kind", "heuristic_warnings", "assembly_kind",
    "parent_assembly_id",
    # Annotation rows (record_type "annotation"): assembly_id is the annotated assembly; counts are of features.
    "annotation_id", "annotation_database", "annotation_database_checksum", "cds", "hypothetical_cds", "trna",
    "tmrna", "rrna", "ncrna", "crispr_arrays", "pseudogenes", "coding_density", "steps_not_searched",
    # MLST rows (record_type "mlst"): assembly_id is the typed assembly; "-" where mlst reported none.
    "mlst_id", "mlst_scheme", "mlst_st", "mlst_status", "mlst_score", "mlst_alleles", "mlst_clonal_complex",
    "mlst_warnings", "mlst_database", "mlst_database_checksum",
    # Species rows (record_type "species"): assembly_id is the identified assembly; ANI in %, AF from 0 to 1.
    "species_id", "species_method", "species_status", "species_name", "species_best_reference", "species_best_ani",
    "species_best_af", "species_runner_up", "species_runner_up_ani", "species_reasons", "species_consistency",
    "species_database", "species_database_checksum",
]


def _searched_count(counts: dict[str, int], searched: set[str], step: str, key: str) -> Any:
    """The count of a feature type, or empty when its step did not run (unknown, not zero)."""
    return counts.get(key, 0) if step in searched else ""


def render_csv(data: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for entry in data["files"]:
        m = entry["metrics"]
        if m is None:
            continue
        q = m.get("quality") or {}
        cov = m.get("coverage_estimate") or {}
        a = entry["analysis"]
        writer.writerow(
            {
                "sample_code": sanitize_spreadsheet_cell(data["sample"]["sample_code"]),
                "filename": sanitize_spreadsheet_cell(entry["file"]["filename"]),
                "origin": entry["file"]["origin"],
                "derived_from": sanitize_spreadsheet_cell(entry["file"]["derived_from"]),
                "format": entry["file"]["format"],
                "read_mate": entry["file"]["read_mate"] or "",
                "sha256": entry["file"]["sha256"],
                "reads": m["read_count"],
                "total_bases": m["total_bases"],
                "min_length": m["min_length"],
                "max_length": m["max_length"],
                "mean_length": f"{m['mean_length']:.2f}",
                "median_length": m["median_length"],
                "n50": m["n50"],
                "n90": m["n90"],
                "gc_percent": f"{m['gc_percent']:.3f}",
                "ambiguous_percent": f"{m['ambiguous_percent']:.4f}",
                "mean_read_quality": f"{q['mean_read_quality']:.2f}" if q else "",
                "median_read_quality": f"{q['median_read_quality']:.1f}" if q else "",
                "q20_bases_percent": f"{q['q20_bases_percent']:.2f}" if q else "",
                "q30_bases_percent": f"{q['q30_bases_percent']:.2f}" if q else "",
                "estimated_depth": f"{cov['estimated_depth']:.2f}" if cov else "",
                "tool": sanitize_spreadsheet_cell(a["tool"]),
                "tool_version": sanitize_spreadsheet_cell(a["tool_version"]),
                "job_id": a["job_id"],
                "finished_at": a["finished_at"],
                "record_type": "reads",
            }
        )
    for asm in data.get("assemblies", []):
        st, contigs = asm["statistics"], (asm["files"] or {}).get("contigs") or {}
        circ = st["circularity"]
        median = st["coverage"]["length_weighted_median"]
        writer.writerow({
            "sample_code": sanitize_spreadsheet_cell(data["sample"]["sample_code"]),
            "filename": sanitize_spreadsheet_cell(contigs.get("path", "").rsplit("/", 1)[-1]),
            "sha256": contigs.get("sha256", ""),
            "tool": sanitize_spreadsheet_cell(asm["assembler"]),
            "tool_version": sanitize_spreadsheet_cell(asm["assembler_version"]),
            "job_id": (asm["job"] or {}).get("id", ""),
            "finished_at": (asm["job"] or {}).get("finished_at") or asm["created_at"],
            "record_type": "assembly",
            "assembly_id": asm["id"],
            "assembly_read_type": sanitize_spreadsheet_cell(asm["read_type"]),
            "assembly_inputs": sanitize_spreadsheet_cell("; ".join(i["filename"] or i["file_id"] for i in asm["inputs"])),
            "contigs": st["contig_count"],
            "assembly_total_length": st["total_length"],
            "largest_contig": st["largest_contig"],
            "contig_n50": st["n50"],
            "contig_l50": st["l50"],
            "contig_n90": st["n90"],
            "contig_l90": st["l90"],
            "assembly_gc_percent": "" if st["gc_percent"] is None else f"{st['gc_percent']:.3f}",
            "circular_contigs": circ["circular_contigs"],
            "median_contig_coverage": "" if median is None else f"{median:g}",
            "contig_coverage_kind": asm.get("coverage_kind") or "",
            "heuristic_warnings": "; ".join(w["code"] for w in asm["warnings"]),
            "assembly_kind": asm["kind"],
            "parent_assembly_id": asm["parent_assembly_id"] or "",
        })
    for ann in data.get("annotations", []):
        sm, counts = ann["summary"], ann["summary"].get("counts", {})
        searched = {k for k, v in ann["steps"].items() if v.get("status") == "searched"}

        density = (sm.get("coding_density") or {}).get("value")
        writer.writerow({
            "sample_code": sanitize_spreadsheet_cell(data["sample"]["sample_code"]),
            "tool": sanitize_spreadsheet_cell(ann["tool"]),
            "tool_version": sanitize_spreadsheet_cell(ann["tool_version"]),
            "job_id": (ann["job"] or {}).get("id", ""),
            "finished_at": (ann["job"] or {}).get("finished_at") or ann["created_at"],
            "record_type": "annotation",
            "assembly_id": ann["assembly_id"],
            "annotation_id": ann["id"],
            "annotation_database": sanitize_spreadsheet_cell(" ".join(x for x in (ann["database"]["name"],
                                                                                 ann["database"]["version"]) if x)),
            "annotation_database_checksum": ann["database"]["checksum"] or "",
            "cds": "" if sm.get("cds") is None else sm["cds"],
            "hypothetical_cds": "" if sm.get("hypothetical") is None else sm["hypothetical"],
            "trna": _searched_count(counts, searched, "trna", "trna"),
            "tmrna": _searched_count(counts, searched, "tmrna" if ann["tool"] == "Bakta" else "trna", "tmrna"),
            "rrna": _searched_count(counts, searched, "rrna", "rrna"),
            "ncrna": _searched_count(counts, searched, "ncrna", "ncrna"),
            "crispr_arrays": _searched_count(counts, searched, "crispr", "crispr"),
            "pseudogenes": sm.get("pseudogenes") if "pseudo" in searched else "",
            "coding_density": "" if density is None else f"{density:.4f}",
            "steps_not_searched": "; ".join(k for k, v in ann["steps"].items() if v.get("status") != "searched"),
        })
    for m in data.get("mlst", []):
        writer.writerow({
            "sample_code": sanitize_spreadsheet_cell(data["sample"]["sample_code"]),
            "tool": m["tool"], "tool_version": sanitize_spreadsheet_cell(m["tool_version"]),
            "job_id": (m["job"] or {}).get("id", ""),
            "finished_at": (m["job"] or {}).get("finished_at") or m["created_at"],
            "record_type": "mlst", "assembly_id": m["assembly_id"], "mlst_id": m["id"],
            "mlst_scheme": m["scheme"] or "-", "mlst_st": m["st"] or "-", "mlst_status": m["status"],
            "mlst_score": m["score"],
            "mlst_alleles": sanitize_spreadsheet_cell(" ".join(f"{a['locus']}({a['call']})" for a in m["alleles"])),
            "mlst_clonal_complex": sanitize_spreadsheet_cell(_mlst_cc(m["clonal_complex"])),
            "mlst_warnings": "; ".join(w["code"] for w in m["warnings"]),
            "mlst_database": sanitize_spreadsheet_cell(" ".join(x for x in (m["database"]["name"],
                                                                           m["database"]["version"]) if x)),
            "mlst_database_checksum": m["database"]["checksum"] or "",
        })
    for sp in data.get("species", []):
        best, other = sp["interpretation"].get("best") or {}, sp["interpretation"].get("runner_up") or {}
        writer.writerow({
            "sample_code": sanitize_spreadsheet_cell(data["sample"]["sample_code"]),
            "tool": sp["tool"], "tool_version": sanitize_spreadsheet_cell(sp["tool_version"]),
            "job_id": (sp["job"] or {}).get("id", ""),
            "finished_at": (sp["job"] or {}).get("finished_at") or sp["created_at"],
            "record_type": "species", "assembly_id": sp["assembly_id"], "species_id": sp["id"],
            "species_method": sp["method"], "species_status": sp["status"],
            "species_name": sanitize_spreadsheet_cell(sp["species"] or ""),
            "species_best_reference": sanitize_spreadsheet_cell(best.get("accession") or best.get("reference") or ""),
            "species_best_ani": "" if best.get("ani") is None else best["ani"],
            "species_best_af": "" if best.get("af") is None else f"{best['af']:.4f}",
            "species_runner_up": sanitize_spreadsheet_cell(other.get("species") or ""),
            "species_runner_up_ani": "" if other.get("ani") is None else other["ani"],
            "species_reasons": "; ".join(x["code"] for x in sp["reasons"]),
            "species_consistency": "; ".join(f"{c['source']}:{c['outcome']}" for c in sp["consistency"]),
            "species_database": sanitize_spreadsheet_cell(" ".join(x for x in (sp["database"]["name"],
                                                                              sp["database"]["version"]) if x)),
            "species_database_checksum": sp["database"]["checksum"] or "",
        })
    return out.getvalue()


def _mlst_cc(cc: dict[str, Any]) -> str:
    if not cc.get("available"):
        return "not available from the scheme" if cc.get("reason") != "no_scheme" else "not determined"
    if cc.get("reason") == "no_st":
        return "not determined (no ST)"
    return cc.get("value") or "none given for this ST"


def render_json(data: dict[str, Any]) -> str:
    """Everything collected, except the map drawing (the HTML report's figure; its numbers are under "map")."""
    annotations = [{k: v for k, v in a.items() if k != "map_svg"} for a in data.get("annotations", [])]
    return json.dumps({**data, "annotations": annotations}, indent=2)


# --- HTML ---------------------------------------------------------------------

def _fmt_int(v: int) -> str:
    return f"{v:,}"


def _fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"


def _bar_chart(labels: list[str], values: list[float], title: str, x_label: str, y_label: str,
               color: str = "#2B54C4") -> str:
    """Minimal, dependency-free SVG bar chart."""
    w, h, ml, mb, mt, mr = 560, 240, 64, 44, 28, 12
    pw, ph = w - ml - mr, h - mt - mb
    vmax = max(values) if values and max(values) > 0 else 1
    n = max(len(values), 1)
    bw = pw / n
    bars = []
    for i, v in enumerate(values):
        bh = ph * v / vmax
        bars.append(
            f'<rect x="{ml + i * bw + 0.5:.1f}" y="{mt + ph - bh:.1f}" width="{max(bw - 1, 0.5):.1f}" '
            f'height="{bh:.1f}" fill="{color}"><title>{escape(labels[i])}: {v:,.0f}</title></rect>'
        )
    ticks = []
    for frac in (0, 0.5, 1):
        y = mt + ph - ph * frac
        ticks.append(
            f'<line x1="{ml}" x2="{ml + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="#E5E7EB"/>'
            f'<text x="{ml - 6}" y="{y + 4:.1f}" text-anchor="end">{vmax * frac:,.0f}</text>'
        )
    xl = []
    if labels:
        for i in sorted({0, len(labels) // 2, len(labels) - 1}):
            xl.append(
                f'<text x="{ml + (i + 0.5) * bw:.1f}" y="{mt + ph + 16}" text-anchor="middle">'
                f"{escape(labels[i])}</text>"
            )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{escape(title)}" '
        f'font-family="Inter, Arial, sans-serif" font-size="10" fill="#334155">'
        f'<text x="{ml}" y="16" font-size="12" font-weight="600" fill="#0B132B">{escape(title)}</text>'
        + "".join(ticks) + "".join(bars) + "".join(xl)
        + f'<text x="{ml + pw / 2}" y="{h - 6}" text-anchor="middle">{escape(x_label)}</text>'
        f'<text transform="translate(12 {mt + ph / 2}) rotate(-90)" text-anchor="middle">'
        f"{escape(y_label)}</text></svg>"
    )


def _metric_rows(m: dict[str, Any]) -> list[tuple[str, str]]:
    rows = [
        ("Records", _fmt_int(m["read_count"])),
        ("Total bases", _fmt_int(m["total_bases"])),
        ("Length min / median / max", f"{m['min_length']:,} / {m['median_length']:,.1f} / {m['max_length']:,}"),
        ("Mean length", f"{m['mean_length']:,.1f}"),
        ("N50 / N90", f"{m['n50']:,} / {m['n90']:,}"),
        ("GC content", f"{m['gc_percent']:.2f} %"),
        ("Ambiguous bases (non-ACGT)", f"{m['ambiguous_bases']:,} ({m['ambiguous_percent']:.3f} %)"),
    ]
    q = m.get("quality")
    if q:
        rows += [
            ("Mean / median read quality", f"Q{q['mean_read_quality']:.2f} / Q{q['median_read_quality']:.1f}"),
            ("Mean base quality (error-averaged)", f"Q{q['mean_base_quality']:.2f}"),
            ("Bases ≥ Q20 / ≥ Q30", f"{q['q20_bases_percent']:.2f} % / {q['q30_bases_percent']:.2f} %"),
        ]
    cov = m.get("coverage_estimate")
    if cov:
        rows.append(
            ("Approximate depth", f"{cov['estimated_depth']:.1f}× (genome size {cov['expected_genome_size_bp']:,} bp)")
        )
    return rows


def _charts(m: dict[str, Any]) -> str:
    charts = []
    hist = m.get("length_histogram_log") or m["length_histogram"]
    edges = hist["bin_edges"]
    charts.append(
        _bar_chart(
            [f"{edges[i]:,.0f}" for i in range(len(hist["reads"]))],
            hist["reads"],
            "Read length distribution" + (" (log-spaced bins)" if hist["scale"] == "log10" else ""),
            "Read length (bp)",
            "Reads",
        )
    )
    q = m.get("quality")
    if q and q["read_quality_histogram"]:
        counts = {b["quality"]: b["reads"] for b in q["read_quality_histogram"]}
        dense = range(min(counts), max(counts) + 1)
        charts.append(
            _bar_chart(
                [f"Q{v}" for v in dense],
                [counts.get(v, 0) for v in dense],
                "Per-read mean quality",
                "Mean read quality (Phred)",
                "Reads",
                color="#008C82",
            )
        )
    gc = {b["gc_percent"]: b["reads"] for b in m["gc_histogram"]}
    charts.append(
        _bar_chart(
            [f"{i}%" for i in range(101)],
            [gc.get(i, 0) for i in range(101)],
            "Per-read GC content",
            "GC (%)",
            "Reads",
            color="#2B54C4",
        )
    )
    return "".join(f'<div class="chart">{c}</div>' for c in charts)


_POD5_METHODS = (
    "<p>POD5 files were recognised by their start and end signatures. Their run metadata were read with the "
    "official <code>pod5</code> library from the run-information table and the read table's sample counts and "
    "channels, without decoding signal. Signal duration is the sum over acquisitions of samples divided by the "
    "sample rate.</p>"
)

_ASSEMBLY_METHODS = (
    "<p>Assemblies were summarised by the ARVA scientific core (<code>arva-core.assembly_stats</code>) from each "
    "contigs FASTA: contigs ranked by length (ties keep file order); Nx is the length of the contig at which the "
    "cumulative length first reaches x % of the total, Lx its rank (QUAST's definitions); GC = (G + C) / (A + C + "
    "G + T) over unambiguous bases. The median coverage is the coverage of the contig holding the middle base when "
    "contigs are ordered by the assembler's coverage, which is Flye's mean read depth, SPAdes' k-mer coverage or "
    "Unicycler's relative depth: the three are not comparable. Heuristic warnings use fixed thresholds stated with each "
    "warning; every check, including those that could not run, is stored with the assembly. QUAST values, when "
    "present, are QUAST's own and describe only contigs of at least its minimum length.</p>"
)

_ANNOTATION_METHODS = (
    "<p>Annotations were made by Bakta or Prokka on the assembly's contigs, written without their FASTA descriptions "
    "(Bakta reads completeness and replicon type from words in them; only its --complete option was used for that). "
    "Before each run ARVA checked every program the annotator needs, as the annotator checks them, and passed the "
    "annotator's own skip options for steps that could not run. The annotators' files are kept unchanged; ARVA's "
    "feature index, counts and coding density (CDS bases over non-N bases) are computed from them, and links are "
    "made only for identifiers the annotator reported.</p>"
    "<p>The genome map and the charts count the annotator's features (arva_core.annotation_stats). The map draws the "
    "sequences in the annotator's order clockwise from the top, with GC content ((G + C) / (A + C + G + T)) and GC "
    "skew ((G − C) / (G + C)) in windows of one length on every sequence, GC as the difference from the mean of the "
    "drawn sequences. Gene lengths are binned up to the 99th percentile (longer genes in a last open bin); gene "
    "density counts each gene once, in the window holding its middle base; COG category names are those of NCBI's "
    "COG 2020 release (fun-20.tab).</p>"
)

_RESOURCES_METHODS = (
    "<p>Thread counts, memory limits and CPU priority came from ARVA's performance profile (light, balanced, maximum "
    "or custom), an ARVA heuristic chosen from the computer's family and cores, and are recorded with each step. "
    "Memory limits apply only to tools that have one (SPAdes -m, Unicycler's SPAdes, Pilon's Java heap, samtools sort "
    "per thread); Flye, Racon, minimap2, BWA, QUAST, Bakta, Prokka, fastp, FastQC, SeqKit, NanoPlot, Filtlong and "
    "MultiQC take none. Tools started through <code>nice</code>, which changes only their scheduling, not their "
    "results; Flye's output and fastp's insert-size estimate can depend on the thread count.</p>"
)


def resources_text(r: dict[str, Any] | None) -> str:
    """One line describing the resources a job was given (analysis_jobs.resources)."""
    if not r:
        return ""
    parts = [f"{r.get('profile')} performance profile ({'automatic' if r.get('choice') == 'auto' else 'chosen'})"]
    if r.get("threads"):
        parts.append(f"{r['threads']} thread(s)")
    if r.get("memory_limit_gb"):
        parts.append(f"memory limit {r['memory_limit_gb']} GB ({r.get('memory_option')})")
    applied = "nice_executable" not in r or r["nice_executable"]
    parts.append(f"CPU priority nice {r.get('nice')}" + ("" if applied else " (not applied: nice was not found)"))
    parts.append(f"ARVA could use {r.get('usable_cpus')} CPUs and {r.get('usable_memory_gb')} GB"
                 + (" (container)" if r.get("in_container") else ""))
    parts.append(f"computer: {r.get('host')}")
    return "; ".join(parts)


_HEADER_FIELDS = (
    ("instrument", "Instrument"), ("run_number", "Run number"), ("run_name", "Run name"),
    ("flowcell_id", "Flow cell"), ("lane", "Lanes"), ("run_id", "Run ID"), ("sample_id", "Sample ID in headers"),
    ("protocol_group_id", "Protocol group"), ("basecall_model", "Basecall model"), ("basecall_gpu", "Basecall GPU"),
    ("barcode", "Barcode"), ("barcode_alias", "Barcode alias"), ("barcode_arrangement", "Barcode arrangement"),
    ("index_sequence", "Index sequence"), ("sample_number", "Sample number"), ("umi_present", "UMI present"),
    ("movie_name", "PacBio movie"), ("movie_instrument_id", "PacBio instrument (from movie name)"),
    ("read_type", "Read type"), ("strand", "Strand"), ("accession", "SRA accession"),
    ("experiment_start_time", "Experiment start"),
)
_HEADER_VALUES_SHOWN = 5
_MATE_NOTES = {
    "same_read_names": "read names match ({matched} of {compared} compared)",
    "different_read_names": "the files do not look like the same reads ({matched} of {compared} read names match)",
    "mate_markers_conflict": "mate markers in the headers contradict the R1/R2 file names",
    "not_analysed": "not checked (read headers not summarised yet)",
    "nothing_compared": "no read names could be compared",
}


def _header_rows(rh: dict[str, Any]) -> list[tuple[str, str]]:
    hint = f"{rh['platform']} ({rh['confidence']} confidence)" if rh["platform"] else "not inferable from the headers"
    rows = [
        ("Header format", rh["header_format"] or "none recognised"),
        ("Platform hint", hint),
        ("Headers examined", f"{rh.get('n_headers_read', 0):,} (first records of the file)"),
    ]
    distinct = rh.get("distinct") or {}
    for key, label in _HEADER_FIELDS:
        d = distinct.get(key)
        if not d:
            continue
        values = ", ".join(str(v) for v in d["values"][:_HEADER_VALUES_SHOWN])
        if d["n_distinct"] > _HEADER_VALUES_SHOWN:
            values += f" … ({d['n_distinct']:,} distinct)"
        rows.append((label, values))
    sources = sorted({src for listed in (rh.get("sources") or {}).values() for src in listed})
    if sources:
        rows.append(("Format documentation", "; ".join(sources)))
    return rows


def _header_summary_html(data: dict[str, Any]) -> str:
    hs = data["read_header_summary"]
    st = hs["suggested_technology"]
    if not hs["per_file"]:
        return ""
    if not st["files_considered"]:
        text = "The read headers of the imported file(s) have not been read, so no platform is suggested."
    elif st["value"]:
        text = (f"Suggested from read headers: {st['value']} ({st['confidence']} confidence), from "
                f"{st['files_with_evidence']} of {st['files_considered']} imported file(s). ")
        if hs["agrees"] is True:
            text += "This matches the technology recorded for the sample."
        elif hs["agrees"] is False:
            text += f"The sample's recorded technology is {hs['user_technology']}; ARVA does not change it."
        elif hs["user_technology"] != "unknown":
            text += (f"The other files carry no platform information, so this neither confirms nor contradicts the "
                     f"recorded technology ({hs['user_technology']}).")
        else:
            text += "The sample's technology is not recorded; ARVA does not set it automatically."
    else:
        text = (f"Read headers of {st['files_considered']} imported file(s) do not indicate a sequencing platform "
                "(read names can be rewritten, so this is not evidence about the platform).")
    names = {f["file_id"]: f["name"] for f in hs["per_file"]}
    mates = "".join(
        f"<li>{escape(names.get(m['r1_file_id'], ''))} / {escape(names.get(m['r2_file_id'], ''))}: "
        f"{escape(_MATE_NOTES[m['note']].format(**m))}</li>"
        for m in hs["mate_check"]
    )
    return f"<p>{escape(text)}</p>" + (f"<p class='muted'>R1/R2 check from read names:</p><ul>{mates}</ul>" if mates else "")


def _distinct(run_infos: list[dict[str, Any]], key: str) -> str:
    values = []
    for r in run_infos:
        v = r.get(key)
        if v not in (None, "") and str(v) not in values:
            values.append(str(v))
    return ", ".join(values) or "—"


def _pod5_rows(summary: dict[str, Any]) -> list[tuple[str, str]]:
    reads, infos = summary["reads"], summary["run_infos"]
    seconds = reads["total_signal_duration_s"]
    starts = sorted(str(r["acquisition_start_time"]) for r in infos if r.get("acquisition_start_time"))
    return [
        ("Reads (signal segments)", _fmt_int(reads["count"])),
        ("Signal duration", "not reported" if seconds is None else
         f"{seconds / 3600:,.2f} h (summed over all channels; not the run's wall-clock time)"),
        ("Samples per read (min / max)", "—" if reads["min_samples"] is None else
         f"{reads['min_samples']:,} / {reads['max_samples']:,}"),
        ("Channels with reads", "not counted" if reads["distinct_channels"] is None else _fmt_int(reads["distinct_channels"])),
        ("Sample rate (Hz)", _distinct(infos, "sample_rate")),
        ("Flow cell", _distinct(infos, "flow_cell_id") + " · " + _distinct(infos, "flow_cell_product_code")),
        ("Sequencing kit", _distinct(infos, "sequencing_kit")),
        ("Protocol", _distinct(infos, "protocol_name")),
        ("Experiment", _distinct(infos, "experiment_name")),
        ("Sample ID in the file", _distinct(infos, "sample_id")),
        ("First acquisition start", starts[0] if starts else "—"),
        ("Acquisition software", _distinct(infos, "software")),
        ("Written by", str(summary["file"]["writing_software"])),
        ("POD5 file version", str(summary["file"]["file_version"])),
    ]


def _raw_signal_html(data: dict[str, Any]) -> str:
    sections = []
    for entry in data.get("raw_signal_files", []):
        f, meta = entry["file"], entry["run_metadata"]
        head = (f"<h3>{escape(f['filename'])}</h3><p class='muted'>POD5 raw signal · {_fmt_bytes(f['size_bytes'])}"
                f" · SHA-256 <code>{escape(f['sha256'] or '')}</code></p>")
        if not f["is_valid"]:
            sections.append(head + f"<p class='warn'>{escape(f['validation_message'] or '')}</p>")
            continue
        if meta is None or not meta["summary"]:
            sections.append(head + "<p class='muted'>Run metadata have not been read for this file.</p>")
            continue
        summary = meta["summary"]
        rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in _pod5_rows(summary))
        warnings = "".join(f"<li>{escape(w['text'] if isinstance(w, dict) else str(w))}</li>"
                           for w in summary.get("warnings", []))
        sections.append(
            head + f"<table>{rows}</table>"
            + (f"<div class='warn'><strong>Warnings</strong><ul>{warnings}</ul></div>" if warnings else "")
            + f"<p class='muted'>Read with {escape(meta['tool'])} {escape(meta['tool_version'])} "
            f"(lib_pod5 {escape(str((meta['parameters'] or {}).get('lib_pod5_version')))}) · job "
            f"<code>{escape(meta['job_id'])}</code>. System name, sequencer position, context tags and tracking ID "
            "are not shown because they can identify people, computers or devices.</p>"
        )
    if not sections:
        return ""
    return ("<h2>Raw signal files (POD5)</h2><p>POD5 files hold raw nanopore signal, not reads. ARVA reads their run "
            "metadata only; it does not basecall. Read statistics require the basecalled FASTQ (for example from "
            "Dorado or MinKNOW).</p>" + "".join(sections))


def _fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, dict) and "full" in v:
        return f"{v['full']:,} + {v['partial']:,} part"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _quast_html(evaluations: list[dict[str, Any]]) -> str:
    if not evaluations:
        return ""
    head = "".join(
        f"<th>QUAST {escape(str(q['quast_version']))} · ≥ {q['min_contig']:,} bp · "
        f"{escape(q['reference'] or 'no reference')}<br><span class='muted'>job <code>{escape(q['job_id'])}</code>"
        f"</span></th>" for q in evaluations
    )
    rows = "".join(
        f"<tr><th>{escape(field)}</th>"
        + "".join(f"<td>{escape(_fmt_value(q['metrics'].get(field)))}</td>" for q in evaluations) + "</tr>"
        for field in QUAST_REPORT_FIELDS if any(field in q["metrics"] for q in evaluations)
    )
    return (f"<h4>QUAST evaluation</h4><table class='grid'><tr><th>Metric (QUAST's name)</th>{head}</tr>{rows}</table>"
            "<p class='muted'>Values as QUAST reported them, for contigs of at least the minimum length shown. "
            "The JSON report keeps every field.</p>")


def _assembly_html(data: dict[str, Any]) -> str:
    sections = []
    for a in data.get("assemblies", []):
        st, job = a["statistics"], a["job"] or {}
        inputs = "".join(
            f"<li>{escape(' ← '.join(i['lineage']) or i['file_id'])}"
            f"{' (filtered copy)' if i['origin'] == 'derived' else ''} · SHA-256 <code>{escape(i['sha256'] or '')}</code>"
            "</li>" for i in a["inputs"]
        )
        g = st["expected_genome_size"]
        cov = st["coverage"]["length_weighted_median"]
        kind = a.get("coverage_kind")
        label = COVERAGE_LABELS.get(kind, "coverage")
        rows = [
            ("Contigs", _fmt_int(st["contig_count"])),
            ("Total length", f"{st['total_length']:,} bp"),
            ("Largest / smallest contig", f"{st['largest_contig']:,} / {st['smallest_contig']:,} bp"),
            ("Contig N50 / L50", f"{st['n50']:,} bp / {st['l50']:,}"),
            ("Contig N90 / L90", f"{st['n90']:,} bp / {st['l90']:,}"),
            ("GC content", "—" if st["gc_percent"] is None else f"{st['gc_percent']:.2f} % (unambiguous bases)"),
            ("N per 100 kb", f"{st['n_per_100kb']:.2f}"),
            ("Circular contigs", f"{st['circularity']['circular_contigs']} of "
                                 f"{st['circularity']['contigs_with_circularity']} (as reported by {a['assembler']})"
             if st["circularity"]["contigs_with_circularity"] else f"not reported by {a['assembler']}"),
            (f"Median contig {label}", "—" if cov is None else
             f"{_coverage(cov, kind)} (length-weighted; {a['assembler']}'s per-contig {label})"),
            ("Expected genome size", f"{g['bp']:,} bp ({(g.get('basis') or g.get('source') or '').replace('_', ' ')})"
             if g["bp"] else "not known (genome-size check not run)"),
        ]
        table = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
        warnings = "".join(
            f"<li><b>[heuristic] {escape(w['code'])}</b>: {escape(w['message'])}"
            + (f" <span class='muted'>({escape(', '.join(w['contigs']))}{' …' if w['contigs_total'] > len(w['contigs']) else ''})</span>"
               if w["contigs"] else "") + "</li>"
            for w in a["warnings"]
        )
        skipped = "".join(f"<li>{escape(c['code'])}: not evaluated — {escape(c['skipped_reason'] or '')}</li>"
                          for c in a["warning_checks"] if not c["evaluated"])
        contigs = "".join(_contig_row(c, kind) for c in a["longest_contigs"])
        files = "".join(f"<tr><th>{escape(k)}</th><td><code>{escape(v['path'])}</code><br>SHA-256 "
                        f"<code>{escape(v['sha256'])}</code></td></tr>" for k, v in (a["files"] or {}).items() if v)
        hist = st["length_histogram"]
        chart = _bar_chart([f"{b['min_length']:,}" for b in hist], [b["contigs"] for b in hist],
                           "Contig length distribution", "Contig length (bp, bin start)", "Contigs")
        lineage = (f" · polished from assembly <code>{escape(a['parent_assembly_id'] or 'deleted')}</code>"
                   if a["kind"] == "polished" else "")
        sections.append(
            f"<h3>{escape(a['assembler'])} {escape(a['assembler_version'])} · {escape(a['read_type'])}</h3>"
            f"<p class='muted'>Assembly <code>{escape(a['id'])}</code> · {escape(a['mode'])}-read assembly{lineage} · "
            f"created {escape(a['created_at'])}</p>"
            f"<h4>Input reads (file ← the file it was derived from)</h4><ul>{inputs}</ul>"
            f"<h4>Statistics</h4><table>{table}</table>"
            + (f"<div class='warn'><strong>Heuristic warnings</strong><ul>{warnings}</ul></div>" if warnings
               else "<p class='muted'>No heuristic warning.</p>")
            + (f"<p class='muted'>Checks not evaluated:</p><ul class='muted'>{skipped}</ul>" if skipped else "")
            + f"<div class='charts'><div class='chart'>{chart}</div></div>"
            + f"<h4>Longest contigs</h4><table class='grid'><tr><th>#</th><th>Contig</th><th>Length (bp)</th>"
            f"<th>{escape(label.capitalize())}</th><th>GC (%)</th><th>Circular</th><th>Repeat</th></tr>{contigs}</table>"
            + (f"<p class='muted'>{len(a['longest_contigs'])} of {st['contig_count']:,} contigs shown; the JSON report "
               "and the contigs FASTA have them all.</p>" if st["contig_count"] > len(a["longest_contigs"]) else "")
            + _polishing_html(a["polishing"])
            + _quast_html(a["quast"])
            + "<h4>Provenance</h4><table>"
            + f"<tr><th>Tool</th><td>{escape(job.get('tool') or a['assembler'])} "
            f"{escape(job.get('tool_version') or a['assembler_version'])}"
            + (f" (<code>{escape(job['tool_path'])}</code>)" if job.get("tool_path") else "") + "</td></tr>"
            + f"<tr><th>Parameters</th><td><code>{escape(json.dumps(job.get('parameters'), sort_keys=True))}</code></td></tr>"
            + f"<tr><th>Analysis job</th><td><code>{escape(job.get('id') or '')}</code></td></tr>"
            + (f"<tr><th>Resources</th><td>{escape(resources_text(job['resources']))}</td></tr>"
               if job.get("resources") else "")
            + files + "</table>"
            + "".join(f"<pre>{escape(c)}</pre>" for c in job.get("commands") or [])
        )
    if not sections:
        return ""
    return ("<h2>Assembly</h2><p>Contig statistics are computed by ARVA from each contigs file; coverage, "
            "circularity and repeat flags are the assembler's. Warnings are heuristics with stated thresholds.</p>"
            + "".join(sections))


_ANNOTATION_COUNTS = (("cds", "CDS"), ("sorf", "Small ORFs"), ("trna", "tRNA"), ("tmrna", "tmRNA"), ("rrna", "rRNA"),
                      ("ncrna", "ncRNA"), ("ncrna_region", "ncRNA regions"), ("crispr", "CRISPR arrays"),
                      ("gap", "Gaps"), ("oric", "oriC"), ("oriv", "oriV"), ("orit", "oriT"), ("other", "Other"))


def _annotation_html(data: dict[str, Any]) -> str:
    sections = []
    for a in data.get("annotations", []):
        sm, job = a["summary"], a["job"] or {}
        counts = sm.get("counts", {})
        rows = [(label, f"{counts.get(key, 0):,}") for key, label in _ANNOTATION_COUNTS if counts.get(key)]
        if sm.get("cds") is not None:
            frac = sm.get("hypothetical_fraction")
            rows.append(("Hypothetical CDS", f"{sm['hypothetical']:,}" + (f" ({100 * frac:.1f} %)" if frac is not None
                                                                          else "")))
            density = (sm.get("coding_density") or {}).get("value")
            rows.append(("Coding density (ARVA)", "n/a" if density is None else f"{100 * density:.2f} %"))
        rows.append(("Pseudogenes", f"{sm.get('pseudogenes', 0):,}" if (a["steps"].get("pseudo") or {}).get("status")
                     == "searched" else "not searched"))
        table = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows)
        steps = "".join(f"<li>{escape(t)}</li>" for t in a["steps_described"])
        db = a["database"]
        files = "".join(f"<tr><th>{escape(k)}</th><td><code>{escape(v['path'])}</code><br>SHA-256 "
                        f"<code>{escape(v['sha256'])}</code></td></tr>" for k, v in (a["files"] or {}).items())
        synthetic = (f"<p class='warn'>SYNTHETIC input ({escape(', '.join(sm['synthetic_evidence']))}): these "
                     "results describe the tools on test data, not biology.</p>" if sm.get("synthetic_evidence") else "")
        sections.append(
            f"<h3>{escape(a['tool'])} {escape(a['tool_version'])}</h3>"
            f"<p class='muted'>Annotation <code>{escape(a['id'])}</code> of assembly <code>{escape(a['assembly_id'])}"
            f"</code> · created {escape(a['created_at'])}</p>{synthetic}"
            f"<table>{table}</table><h4>Steps</h4><ul>{steps}</ul>"
            + _annotation_figures_html(a)
            + "<table>"
            + f"<tr><th>Database</th><td>{escape(db['name'] or 'none')} {escape(db['version'] or '')}"
            + (f"<br>Content checksum <code>{escape(db['checksum'])}</code>" if db["checksum"] else "") + "</td></tr>"
            + f"<tr><th>Settings</th><td><code>{escape(json.dumps(a['parameters'], sort_keys=True))}</code></td></tr>"
            + f"<tr><th>Analysis job</th><td><code>{escape(job.get('id') or '')}</code></td></tr>"
            + (f"<tr><th>Resources</th><td>{escape(resources_text(job['resources']))}</td></tr>"
               if job.get("resources") else "")
            + files + "</table>"
            + "".join(f"<pre>{escape(c)}</pre>" for c in job.get("commands") or [])
        )
    if not sections:
        return ""
    return ("<h2>Annotation</h2><p>Features are the annotators' predictions; counts are ARVA's counts of the features "
            "each annotator reported. Steps that were not searched are listed with the reason.</p>"
            + "".join(sections))


_CALL_TYPES = {"exact": "exact allele", "novel": "novel, similar to the allele shown", "partial": "partial match",
               "missing": "not found", "multiple": "several exact alleles", "null": "no allele in the ST's profile",
               "unrecognised": "not recognised by ARVA"}


def _mlst_html(data: dict[str, Any]) -> str:
    sections = []
    for m in data.get("mlst", []):
        job, db = m["job"] or {}, m["database"]
        rows = [("Scheme", m["scheme"] or "none (not determined)"), ("ST", m["st"] or "not assigned"),
                ("mlst status", m["status"]), ("mlst score", f"{m['score']} / 100"),
                ("Clonal complex (scheme's profile file)", _mlst_cc(m["clonal_complex"]))]
        info = m.get("scheme_info") or {}
        if info:
            rows.append(("Scheme dates", f"last updated {info.get('last_updated') or 'unknown'}, downloaded "
                                         f"{info.get('download_date') or 'unknown'} from {info.get('source') or '?'}"))
        table = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)
        alleles = "".join(f"<tr><td>{escape(a['locus'])}</td><td><code>{escape(a['call'])}</code></td>"
                          f"<td>{escape(_CALL_TYPES.get(a['type'], a['type']))}</td></tr>" for a in m["alleles"])
        warnings = "".join(f"<li>{escape(w['text'])}</li>" for w in m["warnings"])
        files = "".join(f"<tr><th>{escape(k)}</th><td><code>{escape(v['path'])}</code><br>SHA-256 "
                        f"<code>{escape(v['sha256'])}</code></td></tr>" for k, v in (m["files"] or {}).items())
        sections.append(
            f"<h3>{escape(m['tool'])} {escape(m['tool_version'])}</h3>"
            f"<p class='muted'>MLST result <code>{escape(m['id'])}</code> of assembly <code>{escape(m['assembly_id'])}"
            f"</code> · created {escape(m['created_at'])}</p>"
            f"<table>{table}</table>"
            + (f"<table class='grid'><tr><th>Locus</th><th>Call</th><th>Meaning</th></tr>{alleles}</table>"
               if alleles else "")
            + (f"<div class='warn'><strong>Warnings</strong><ul>{warnings}</ul></div>" if warnings else "")
            + "<table>"
            + f"<tr><th>Database</th><td>{escape(db['name'] or '')}, schemes downloaded {escape(db['version'] or '?')}"
            + (f"<br>Content checksum <code>{escape(db['checksum'])}</code>" if db["checksum"] else "") + "</td></tr>"
            + f"<tr><th>Settings</th><td><code>{escape(json.dumps(m['parameters'], sort_keys=True))}</code></td></tr>"
            + f"<tr><th>Analysis job</th><td><code>{escape(job.get('id') or '')}</code></td></tr>"
            + (f"<tr><th>Resources</th><td>{escape(resources_text(job['resources']))}</td></tr>"
               if job.get("resources") else "")
            + files + "</table>"
            + "".join(f"<pre>{escape(c)}</pre>" for c in job.get("commands") or [])
        )
    if not sections:
        return ""
    return ("<h2>MLST</h2><p>Sequence types are mlst's calls with the PubMLST schemes it bundles; ARVA adds no call of "
            "its own. Inexact, missing or several alleles, tied schemes and no scheme found are listed as warnings.</p>"
            + "".join(sections))


def _fmt_af(v: Any) -> str:
    return "—" if v is None else f"{v:.3f}"


def _species_html(data: dict[str, Any]) -> str:
    sections = []
    for sp in data.get("species", []):
        job, db, i = sp["job"] or {}, sp["database"], sp["interpretation"]
        mash = sp["method"] == "mash"
        head = ("<tr><th>#</th><th>Reference</th><th>Organism</th><th>Type material</th>"
                + ("<th>Mash distance</th><th>Shared hashes</th>" if mash else "<th>ANI (%)</th><th>Aligned fraction</th>")
                + "</tr>")
        hits = "".join(
            f"<tr><td>{h['rank']}</td><td><code>{escape(str(h.get('accession') or h.get('reference') or ''))}</code></td>"
            f"<td>{escape(h.get('organism') or '—')}{(' · ' + escape(h['strain'])) if h.get('strain') else ''}</td>"
            f"<td>{'yes' if h.get('type_material') else 'no' if h.get('type_material') is False else 'unknown'}</td>"
            + (f"<td>{h.get('distance')}</td><td>{h.get('shared')}/{h.get('hashes')}</td>" if mash else
               f"<td>{'' if h.get('ani') is None else h['ani']}</td><td>{_fmt_af(h.get('af'))}</td>")
            + "</tr>" for h in sp["hits"][:10])
        t = i.get("thresholds") or {}
        rows = [("ARVA's reading", sp["status_text"]),
                ("Thresholds", f"species boundary {t.get('ani_boundary')} % ANI (Jain et al. 2018, Nat Commun 9:5114, "
                               f"doi:10.1038/s41467-018-07641-9); minimum aligned fraction {t.get('min_af')} "
                               f"(GTDB-Tk's default, applied by ARVA); margin {t.get('margin')} percentage points "
                               "(ARVA's heuristic)")]
        for c in sp["consistency"]:
            p = c.get("params") or {}
            what = f"MLST scheme {p.get('scheme') or '-'} (ST {p.get('st') or '-'})" if c["source"] == "mlst" else \
                f"organism given for {p.get('tool') or 'the annotation'}: {p.get('given')}"
            rows.append(("Consistency", f"{what}: {species_svc.CONSISTENCY_TEXT.get(c['outcome'], c['outcome'])}"))
        table = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)
        notes = "".join(f"<li>{escape(x['text'])}</li>" for x in [*sp["reasons"], *sp["warnings"]])
        caveats = "".join(f"<li>{escape(x['text'])}</li>" for x in sp["caveats"])
        files = "".join(f"<tr><th>{escape(k)}</th><td><code>{escape(v['path'])}</code><br>SHA-256 "
                        f"<code>{escape(v['sha256'])}</code></td></tr>" for k, v in (sp["files"] or {}).items())
        sections.append(
            f"<h3>{escape(sp['tool'])} {escape(sp['tool_version'])}</h3>"
            f"<p class='muted'>Species result <code>{escape(sp['id'])}</code> of assembly "
            f"<code>{escape(sp['assembly_id'])}</code> · created {escape(sp['created_at'])}</p>"
            f"<table>{table}</table>"
            + (f"<table class='grid'>{head}{hits}</table>" if hits else "<p>No reference was reported.</p>")
            + (f"<div class='warn'><strong>Why it is not more certain, and warnings</strong><ul>{notes}</ul></div>"
               if notes else "")
            + (f"<p class='muted'>Caveats:</p><ul>{caveats}</ul>" if caveats else "")
            + "<table>"
            + f"<tr><th>Database</th><td>{escape(db['name'] or '')} {escape(db['version'] or '')} ({escape(db['kind'] or '')})"
            + (f"<br>Content checksum <code>{escape(db['checksum'])}</code>" if db["checksum"] else "")
            + (f"<br>{db['references']} reference genomes, SHA-256 of each recorded; list checksum "
               f"<code>{escape(db['references_checksum'])}</code>" if db.get("references_checksum") else "")
            + "</td></tr>"
            + f"<tr><th>Settings</th><td><code>{escape(json.dumps(sp['parameters'], sort_keys=True))}</code></td></tr>"
            + f"<tr><th>Analysis job</th><td><code>{escape(job.get('id') or '')}</code></td></tr>"
            + (f"<tr><th>Resources</th><td>{escape(resources_text(job['resources']))}</td></tr>"
               if job.get("resources") else "")
            + files + "</table>"
            + "".join(f"<pre>{escape(c)}</pre>" for c in job.get("commands") or [])
        )
    if not sections:
        return ""
    return ("<h2>Species identification</h2><p>Ranked hits of each method against the database it searched, with "
            "ARVA's reading of them: a species is named only when one species is clearly above the boundary with "
            "enough aligned fraction; otherwise the result is ambiguous or no reference is within the boundary.</p>"
            + "".join(sections))


_SPECIES_METHODS = (
    "<p>Species identification compared the assembly's contigs with a reference database: FastANI 1.34 (Jain C. et "
    "al. Nat Commun 2018;9:5114, doi:10.1038/s41467-018-07641-9; fragment-based ANI from reciprocal mappings of 3 kb "
    "fragments, aligned fraction = mapped / total query fragments) or skani 0.4.0 (Shaw J., Yu Y.W. Nat Methods "
    "2023;20:1661-1665, doi:10.1038/s41592-023-02018-3; ANI and aligned fractions from sparse approximate alignments) "
    "against a reference genome collection; Mash 2.3 (Ondov B.D. et al. Genome Biol 2016;17:132, "
    "doi:10.1186/s13059-016-0997-x) against a sketch file; sylph 1.0.0 (Shaw J., Yu Y.W. Nat Biotechnol "
    "2025;43:1348-1359, doi:10.1038/s41587-024-02412-y) against a sylph database; or GTDB-Tk 2.8.0 (Chaumeil P.-A. et "
    "al. Bioinformatics 2022;38:5315-5316, doi:10.1093/bioinformatics/btac672). Every option was passed explicitly "
    "(Settings). ARVA's reading applies the 95 % ANI species boundary of Jain et al. (2018) with a minimum aligned "
    "fraction of 0.5 (GTDB-Tk's default --min_af) and a margin of 0.5 percentage points (ARVA's heuristic) for values "
    "near the boundary or near another species; Mash distances are ranked only. The consistency checks compare the "
    "species name with the MLST scheme's name (PubMLST's genus-initial + epithet habit; a name comparison only) and "
    "with the organism given for an annotation.</p>"
)
SPECIES_LIMITATIONS = [
    "A species identification can only be as good as the database searched: a species absent from it cannot be "
    "found, a genus-specific collection cannot identify other genera, and each reference carries the name it was "
    "deposited with (type material is marked when the collection says so).",
    "The 95 % ANI boundary is empirical; some species are wider or narrower, and closely related species (for "
    "example Escherichia coli and Shigella) can both lie above it.",
    "Mash's distance is not ANI; sylph is built for reads and its coverage adjustment does not apply to an assembly; "
    "GTDB-Tk was not validated with ARVA.",
]


_MLST_METHODS = (
    "<p>MLST was called by mlst (T. Seemann, https://github.com/tseemann/mlst) on the assembly's contigs, with the "
    "PubMLST typing schemes bundled in its package; every option was passed explicitly (shown under Settings). mlst "
    "searches the alleles with blastn (ungapped, minimum identity --minid), calls an exact allele n at full length "
    "and 100 % identity, ~n at full length and lower identity, n? when at least --mincov % of the allele is matched, "
    "- when none is found and n,m when several exact alleles are found; it scores each scheme and reports the best "
    "one. The clonal complex is read by ARVA from the scheme's profile file when the scheme has one. This publication "
    "made use of the PubMLST website (https://pubmlst.org/) sited at the University of Oxford (Jolley K.A., Bray J.E., "
    "Maiden M.C.J. Wellcome Open Research 2018, 3:124, doi:10.12688/wellcomeopenres.14826.1).</p>"
)
MLST_LIMITATIONS = [
    "MLST types a few housekeeping loci: an ST groups related strains, it does not identify a species or predict "
    "a phenotype. A scheme detected by mlst depends on its minimum score; tied schemes are reported in an arbitrary "
    "order.",
    "The n of a novel (~n) or partial (n?) call is the first similar allele BLAST reported, not necessarily the "
    "closest; such alleles, and missing ones, leave the ST not assigned.",
    "The bundled schemes are as downloaded with mlst's package (their date is recorded); newer STs and alleles are "
    "not known to them. PubMLST data submitted from 1 January 2025 are restricted to non-commercial academic "
    "research or public health surveillance.",
]


_LENGTH_CLASS_LABELS = (("cds_characterised", "CDS, characterised"), ("cds_hypothetical", "CDS, hypothetical"),
                        ("rna", "RNA genes"), ("sorf", "Small ORFs"))
_STRAND_LABELS = (("+", "Strand +"), ("-", "Strand −"), (".", "No strand"))


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "—"


def _grid(head: list[str], rows: list[list[Any]]) -> str:
    cells = "".join("<tr>" + "".join(f"<td>{escape(_fmt_value(v))}</td>" for v in r) + "</tr>" for r in rows)
    return "<table class='grid'><tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + f"</tr>{cells}</table>"


def _annotation_figures_html(a: dict[str, Any]) -> str:
    """The circular map and the numbers behind the annotation charts, or why they are missing."""
    out = []
    missing = "".join(f"<li>{escape(x)}</li>" for x in a.get("figures_unavailable") or [])
    if missing:
        out.append(f"<p class='warn'>Not drawn:</p><ul>{missing}</ul>")
    m, c = a.get("map"), a.get("charts")
    if a.get("map_svg") and m:
        cov = m["coverage"]
        out.append("<h4>Genome map</h4><figure class='map'>" + a["map_svg"] + "<figcaption class='muted'>Rings from "
                   "the outside in: sequence, genes on strand +, genes on strand −"
                   + (", read coverage" if cov["available"] else "") + ", GC content, GC skew. GC in windows of "
                   f"{m['gc_window']:,} bp on every sequence. Positions run clockwise from the top. "
                   + ("" if cov["available"] else f"No coverage ring: {escape(cov.get('reason') or 'no alignment')}. ")
                   + "Rings for resistance, virulence and mobile elements come with Phase 5.</figcaption></figure>")
        genes = {d["contig"]: d["genes"] for d in (c or {}).get("density", {}).get("contigs", [])}
        hypo = {h["contig"]: h for h in ((c or {}).get("hypothetical") or {}).get("by_contig", [])}
        rows = []
        for s in m["sequences"]:
            h = hypo.get(s["contig"])
            topo = f"{s['topology']} ({s['topology_source']})" if s["topology"] else "not reported"
            rows.append([s["contig_in_assembly"], s["length"], "—" if s["gc"] is None else f"{100 * s['gc']:.2f} %",
                         topo, genes.get(s["contig"], 0),
                         "—" if h is None else h["characterised"] + h["hypothetical"],
                         "—" if h is None else _pct(h["hypothetical"], h["characterised"] + h["hypothetical"])])
        out.append("<h4>Sequences</h4>" + _grid(["Sequence", "Length (bp)", "GC", "Topology (reported by)", "Genes",
                                                 "CDS", "Hypothetical CDS"], rows))
    if not c:
        return "".join(out)
    out.append("<h4>Annotation charts: the numbers</h4><p class='muted'>Genes are CDS, small ORFs, tRNA, tmRNA, rRNA "
               "and ncRNA genes, counted as the annotator reported them.</p>")
    lengths = c["lengths"]
    if lengths["bins"]:
        st = lengths["classes"]
        out.append(_grid(["Gene length (bp)", "n", "Min", "Median", "Mean", "Max"],
                         [[label, st[k]["n"], st[k]["min"], st[k]["median"], st[k]["mean"], st[k]["max"]]
                          for k, label in _LENGTH_CLASS_LABELS if st[k]["n"]]))
        bins = lengths["bins"]
        labels = [f"≥ {b['min']:,}" if b["max"] is None else f"{b['min']:,}–{b['max'] - 1:,}" for b in bins]
        out.append("<div class='charts'><div class='chart'>" + _bar_chart(
            labels, [sum(b[k] for k, _ in _LENGTH_CLASS_LABELS) for b in bins],
            f"Gene lengths, all genes ({lengths['width']:,} bp bins; last bin open)", "Gene length (bp)", "Genes")
            + "</div>" + _density_chart(c) + "</div>")
    strand = c["strand"]
    if strand["by_type"]:
        rows = [[_TYPE_LABELS.get(t, t), *(v[k] for k, _ in _STRAND_LABELS), _pct(v["+"], v["+"] + v["-"])]
                for t, v in strand["by_type"].items()]
        tot = strand["total"]
        rows.append(["All genes", *(tot[k] for k, _ in _STRAND_LABELS), _pct(tot["+"], tot["+"] + tot["-"])])
        out.append(_grid(["Gene orientation", *(label for _, label in _STRAND_LABELS), "Share on +"], rows)
                   + "<p class='muted'>Strand of the sequences as written; leading and lagging strand are not "
                     "determined (the replication origin is not located).</p>")
    d = c["density"]
    rows = []
    for x in d["contigs"]:
        full = sorted(t for t, s, e in zip(x["total"], x["start"], x["end"], strict=True) if e - s + 1 == d["window"])
        med = (full[len(full) // 2] if len(full) % 2 else (full[len(full) // 2 - 1] + full[len(full) // 2]) / 2
               ) if full else None
        rows.append([x["contig_in_assembly"], x["genes"], len(x["total"]), "—" if not full else min(full),
                     "—" if med is None else med, "—" if not full else max(full)])
    out.append(_grid([f"Gene density ({d['window']:,} bp windows)", "Genes", "Windows", "Min per full window",
                      "Median", "Max"], rows))
    cog = c["cog"]
    if not cog["cds_searched"]:
        out.append("<p>COG categories: CDS were not searched in this run.</p>")
    elif not cog["reported"]:
        out.append(f"<p>COG categories: none reported by the annotator ({cog['cds_with_cog_id']:,} CDS carry a COG "
                   "identifier without a category); ARVA assigns none.</p>")
    else:
        out.append(_grid(["COG category", "Name (NCBI COG 2020)", "CDS", "Of CDS with a category"],
                         [[k["letter"], k["name"] or "not a COG 2020 letter", k["cds"],
                           _pct(k["cds"], cog["cds_with_category"])] for k in cog["categories"]]))
    return "".join(out)


def _density_chart(c: dict[str, Any]) -> str:
    """Genes per window along the longest sequence that has genes."""
    contigs = sorted((x for x in c["density"]["contigs"] if x["genes"]), key=lambda x: -x["length"])
    if not contigs:
        return ""
    x = contigs[0]
    labels = [f"{s:,}–{e:,}" for s, e in zip(x["start"], x["end"], strict=True)]
    return ("<div class='chart'>" + _bar_chart(labels, x["total"], f"Genes per {c['density']['window']:,} bp window, "
            f"{x['contig_in_assembly']}", "Window", "Genes", color="#008C82") + "</div>")


_TYPE_LABELS = {"cds": "CDS", "sorf": "Small ORF", "trna": "tRNA", "tmrna": "tmRNA", "rrna": "rRNA", "ncrna": "ncRNA"}


def _polishing_html(p: dict[str, Any] | None) -> str:
    if not p:
        return ""
    rounds = "".join(
        f"<tr><td>{r['round']}</td><td>{escape(r['source'] or 'not available')}</td>"
        + "".join(f"<td>{_count((r['changes'] or {}).get(k, {}).get('events'))}</td>"
                  for k in ("snp", "insertion", "deletion", "other")) + "</tr>"
        for r in p["rounds"])
    b, a = p["indirect_indicators"]["before"] or {}, p["indirect_indicators"]["after"] or {}
    def num(v: Any, digits: int) -> str:
        return "—" if v is None else f"{v:.{digits}f}"
    indirect = "".join(
        f"<tr><th>{escape(label)}</th><td>{num(b.get(key), d)}</td><td>{num(a.get(key), d)}</td></tr>"
        for label, key, d in (("Reads mapped (%)", "mapped_percent", 2),
                              ("Edit distance per 100 aligned bases (NM)", "edit_distance_per_100_bases", 4),
                              ("Indel events per 100 kb aligned", "indel_events_per_100kb", 1),
                              ("Properly paired (%)", "properly_paired_percent", 2)))
    st = p["assembly_statistics"] or {}
    before, after = st.get("before") or {}, st.get("after") or {}
    stats = "".join(f"<tr><th>{escape(label)}</th><td>{_count(before.get(k))}</td><td>{_count(after.get(k))}</td></tr>"
                    for label, k in (("Contigs", "contig_count"), ("Total length (bp)", "total_length"),
                                     ("N50 (bp)", "n50")))
    notes = "".join(f"<li>{escape(o['message'])}</li>" for o in p["observations"])
    return (f"<h4>Polishing ({escape(p['polisher'] or '')} {escape(p['polisher_version'] or '')})</h4>"
            "<p><strong>Direct evidence</strong>: changes between the draft and the polished sequence, by round.</p>"
            "<table class='grid'><tr><th>Round</th><th>Source</th><th>SNPs</th><th>Insertions</th><th>Deletions</th>"
            f"<th>Other</th></tr>{rounds}</table>"
            f"<p><strong>Indirect indicators</strong>: the polishing reads aligned with "
            f"{escape(p['indirect_indicators']['aligner'] or '')} to the draft and to the polished assembly.</p>"
            f"<table class='grid'><tr><th></th><th>Draft</th><th>Polished</th></tr>{indirect}{stats}</table>"
            + (f"<ul>{notes}</ul>" if notes else ""))


def _yes_no(v: bool | None) -> str:
    return "—" if v is None else "yes" if v else "no"


def _coverage(value: float, kind: str | None) -> str:
    return f"{value:g}" if kind == "kmer_coverage" else f"{value:g}×"


def _contig_row(c: dict[str, Any], kind: str | None) -> str:
    coverage = "—" if c["coverage"] is None else _coverage(c["coverage"], kind)
    gc = "—" if c["gc_percent"] is None else f"{c['gc_percent']:.2f}"
    return (f"<tr><td>{c['rank']}</td><td><code>{escape(c['name'])}</code></td><td>{c['length']:,}</td>"
            f"<td>{coverage}</td><td>{gc}</td><td>{_yes_no(c['circular'])}</td><td>{_yes_no(c['repeat'])}</td></tr>")


def render_html(data: dict[str, Any]) -> str:
    s = data["sample"]
    meta_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(s[key]))}</td></tr>"
        for key, label in [
            ("sample_code", "Sample ID"), ("organism", "Organism"),
            ("expected_species", "Expected species"), ("sample_type", "Sample type"),
            ("host", "Host"), ("geographic_origin", "Geographic origin"),
            ("collection_date", "Collection date"), ("sequencing_technology", "Technology"),
            ("sequencing_run", "Sequencing run"), ("researcher", "Researcher"),
            ("institution", "Institution"),
        ]
        if s.get(key)
    )

    sections = []
    for entry in data["files"]:
        f, a, m = entry["file"], entry["analysis"], entry["metrics"]
        head = (
            f"<h3>{escape(f['filename'])}</h3>"
            f"<p class='muted'>{escape(f['format'].upper().replace('_GZ', ' (gzip)'))}"
            f"{' · ' + escape(f['read_mate']) if f['read_mate'] else ''} · {_fmt_bytes(f['size_bytes'])}"
            f" · SHA-256 <code>{escape(f['sha256'] or '')}</code></p>"
            + (f"<p class='muted'>Derived file — produced from <b>{escape(f['derived_from'] or 'a deleted file')}</b> "
               f"by analysis job <code>{escape(f['produced_by_job_id'] or '')}</code></p>"
               if f["origin"] == "derived" else "")
        )
        rh = entry["read_headers"]
        if rh is not None:
            head += "<h4>Read headers</h4><table>" + "".join(
                f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in _header_rows(rh)
            ) + "</table>"
        if m is None:
            sections.append(
                head + f"<p class='warn'>No completed statistics for this file. "
                f"Validation: {escape(f['validation_message'] or 'n/a')}</p>"
            )
            continue
        rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in _metric_rows(m))
        warnings = "".join(f"<li>{escape(w)}</li>" for w in m["warnings"])
        params = escape(json.dumps(a["parameters"], sort_keys=True))
        sections.append(
            head
            + f"<table>{rows}</table>"
            + (f"<div class='warn'><strong>Warnings</strong><ul>{warnings}</ul></div>" if warnings else "")
            + f"<div class='charts'>{_charts(m)}</div>"
            + "<h4>Provenance</h4><table>"
            + f"<tr><th>Tool</th><td>{escape(a['tool'])} {escape(a['tool_version'])}</td></tr>"
            + f"<tr><th>Parameters</th><td><code>{params}</code></td></tr>"
            + f"<tr><th>Started / finished</th><td>{escape(a['started_at'] or '')} / {escape(a['finished_at'] or '')}</td></tr>"
            + f"<tr><th>Duration</th><td>{a['duration_seconds']:.2f} s</td></tr>"
            + f"<tr><th>Analysis job</th><td><code>{escape(a['job_id'])}</code></td></tr>"
            + f"<tr><th>Result file</th><td><code>{escape(', '.join(a['result_files'] or []))}</code></td></tr>"
            + "</table>"
        )

    demo = (
        "<div class='demo'>DEMO PROJECT — data in this report are for demonstration only.</div>"
        if data["project"]["is_demo"]
        else ""
    )
    limitations = "".join(f"<li>{escape(x)}</li>" for x in data["limitations"]
                          + (ASSEMBLY_LIMITATIONS if data.get("assemblies") else [])
                          + (POLISHING_LIMITATIONS if any(a["kind"] == "polished" for a in data.get("assemblies", []))
                             else [])
                          + (ANNOTATION_LIMITATIONS if data.get("annotations") else [])
                          + (MLST_LIMITATIONS if data.get("mlst") else [])
                          + (SPECIES_LIMITATIONS if data.get("species") else []))
    steps = "".join(
        f"<h3>{escape(st['tool'])} {escape(st['tool_version'])}</h3>"
        f"<p class='muted'>Inputs: {escape(', '.join(st['inputs']))} · finished {escape(st['finished_at'] or '')}"
        f" · job <code>{escape(st['job_id'])}</code></p>"
        + "".join(f"<p>{escape(h)}</p>" for h in st["highlights"])
        + (f"<p class='muted'>Resources: {escape(resources_text(st['resources']))}</p>" if st.get("resources") else "")
        + "".join(f"<pre>{escape(c)}</pre>" for c in st["commands"])
        for st in data.get("processing", [])
    )
    with_resources = any(st.get("resources") for st in data.get("processing", [])) or any(
        (x.get("job") or {}).get("resources")
        for x in [*data.get("assemblies", []), *data.get("annotations", []), *data.get("mlst", []),
                  *data.get("species", [])])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARVA report · {escape(s['sample_code'])}</title>
<style>
 body {{ font-family: Inter, -apple-system, Segoe UI, Arial, sans-serif; color:#0B132B; background:#F8FAFC;
        margin:0; padding:32px 16px; line-height:1.5; }}
 main {{ max-width: 960px; margin: 0 auto; background:#fff; border:1px solid #E5E7EB; border-radius:12px; padding:32px; }}
 header {{ border-bottom: 2px solid #00B4A6; padding-bottom: 12px; margin-bottom: 24px; }}
 .brand {{ letter-spacing: .3em; font-weight: 600; color:#1F3B8A; font-size: 13px; }}
 h1 {{ margin: 4px 0; font-size: 26px; }} h2 {{ font-size: 18px; margin-top: 32px; color:#1F3B8A; }}
 h3 {{ font-size: 16px; margin: 28px 0 4px; }} h4 {{ font-size: 14px; margin: 20px 0 6px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }}
 th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #EEF2F7; vertical-align: top; }}
 th {{ width: 38%; color:#475569; font-weight: 500; }}
 code {{ font-size: 11px; word-break: break-all; }}
 pre {{ font-size: 11px; background:#F1F5F9; padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-all; }}
 .muted {{ color:#64748B; font-size: 12px; margin: 0; }}
 figure.map {{ margin: 8px 0; }} figure.map svg {{ max-width: 760px; display: block; margin: 0 auto; }}
 .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
 .chart {{ border:1px solid #EEF2F7; border-radius: 8px; padding: 8px; }}
 table.grid th {{ width: auto; }}
 .warn {{ background:#FFFBEB; border:1px solid #F59E0B55; border-radius:8px; padding:8px 12px; font-size: 13px; }}
 .demo {{ background:#F59E0B; color:#0B132B; font-weight:700; text-align:center; padding:8px; border-radius:8px; margin-bottom:16px; }}
 footer {{ margin-top: 32px; font-size: 11px; color:#64748B; }}
 @media print {{ body {{ background:#fff; padding:0; }} main {{ border:none; }} }}
</style></head>
<body><main>
{demo}
<header><div class="brand">ARVA · GENOMIC DISCOVERY PLATFORM</div>
<h1>Sequencing data report</h1>
<p class="muted">Project “{escape(data['project']['name'])}” · Sample {escape(s['sample_code'])} ·
Generated {escape(data['generated_at'])} · ARVA {escape(data['arva_version'])}</p></header>
<h2>Sample</h2><table>{meta_rows}</table>
{_header_summary_html(data)}
<h2>Read statistics</h2>
{''.join(sections) or '<p>No read files registered.</p>'}
{_raw_signal_html(data)}
{_assembly_html(data)}
{_annotation_html(data)}
{_mlst_html(data)}
{_species_html(data)}
{('<h2>Processing and independent checks</h2>' + steps) if steps else ''}
<h2>Methods</h2>
<p>Each file was streamed in full by the ARVA scientific core (<code>arva-core.seqstats</code>), which
validates FASTQ/FASTA structure record by record and computes counts, length distribution
(N50/N90 from lengths sorted in descending order), GC content over unambiguous bases and, for FASTQ,
Phred+33 quality statistics. Per-read mean quality averages per-base error probabilities before
converting back to the Phred scale. Scatter-plot data use a seeded reservoir sample of reads. Exact
parameters and checksums are listed with each file above.</p>
<p>Read headers of the first records of each file (up to 1,000) were matched against documented
Illumina, Oxford Nanopore, PacBio and NCBI SRA header grammars (<code>arva_core.header_meta</code>).
The resulting platform hint is a suggestion with a stated confidence; it never replaces the
technology recorded for the sample.</p>
{_POD5_METHODS if data.get("raw_signal_files") else ""}
{_ASSEMBLY_METHODS if data.get("assemblies") else ""}
{_ANNOTATION_METHODS if data.get("annotations") else ""}
{_MLST_METHODS if data.get("mlst") else ""}
{_SPECIES_METHODS if data.get("species") else ""}
{_RESOURCES_METHODS if with_resources else ""}
<h2>Limitations</h2><ul>{limitations}</ul>
<footer>This report is descriptive. It contains values computed from the input files and does not
make clinical or biological claims.</footer>
</main></body></html>"""
