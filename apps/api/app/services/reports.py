"""Basic sequencing-data reports (HTML / JSON / CSV) built only from stored results."""
from __future__ import annotations

import csv
import io
import json
import shlex
from datetime import UTC, datetime
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__ as ARVA_VERSION
from app.models import AnalysisJob, JobStatus, RawFile, Sample
from app.services import crosscheck
from app.services.jobs import (
    FASTP_JOB,
    FASTQ_STATS_JOB,
    FASTQC_JOB,
    FILTLONG_JOB,
    POD5_JOB,
    SEQKIT_JOB,
)
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
        "limitations": LIMITATIONS,
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
            AnalysisJob.job_type.in_([FASTP_JOB, FILTLONG_JOB, SEQKIT_JOB, FASTQC_JOB]),
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
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "highlights": [],
        }
        if j.job_type == FASTP_JOB and summary:
            b, a = summary["before_filtering"], summary["after_filtering"]
            fr = summary.get("filtering_result", {})
            step["highlights"] = [
                f"Reads {b['total_reads']:,} → {a['total_reads']:,}; bases {b['total_bases']:,} → {a['total_bases']:,}",
                f"Removed: low quality {fr.get('low_quality_reads', 0):,}, too many N {fr.get('too_many_N_reads', 0):,}, "
                f"too short {fr.get('too_short_reads', 0):,}",
                f"Reads with adapter trimmed: {summary.get('adapter_trimmed_reads') or 0:,}",
            ]
        elif j.job_type == FILTLONG_JOB:
            chosen = {k: v for k, v in (j.parameters or {}).items() if v is not None and not k.endswith(("weight", "window_size"))}
            step["highlights"] = ["Thresholds: " + ", ".join(f"{k}={v}" for k, v in chosen.items())]
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
        elif j.job_type == FASTQC_JOB and summary:
            flags = {}
            for m in summary.get("modules", []):
                flags.setdefault(m["status"], []).append(m["module"])
            step["highlights"] = [
                f"FastQC flags — {status}: {', '.join(mods)}" for status, mods in sorted(flags.items())
            ]
        steps.append(step)
    return steps


# --- CSV ----------------------------------------------------------------------

CSV_COLUMNS = [
    "sample_code", "filename", "origin", "derived_from", "format", "read_mate", "sha256", "reads", "total_bases",
    "min_length", "max_length", "mean_length", "median_length", "n50", "n90", "gc_percent",
    "ambiguous_percent", "mean_read_quality", "median_read_quality", "q20_bases_percent",
    "q30_bases_percent", "estimated_depth", "tool", "tool_version", "job_id", "finished_at",
]


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
                "sample_code": data["sample"]["sample_code"],
                "filename": entry["file"]["filename"],
                "origin": entry["file"]["origin"],
                "derived_from": entry["file"]["derived_from"] or "",
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
                "tool": a["tool"],
                "tool_version": a["tool_version"],
                "job_id": a["job_id"],
                "finished_at": a["finished_at"],
            }
        )
    return out.getvalue()


def render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2)


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
    if st["value"]:
        text = (f"Suggested from read headers: {st['value']} ({st['confidence']} confidence), from "
                f"{st['files_with_evidence']} of {st['files_considered']} imported file(s). ")
        if hs["agrees"] is True:
            text += "This matches the technology recorded for the sample."
        elif hs["agrees"] is False:
            text += f"The sample's recorded technology is {hs['user_technology']}; ARVA does not change it."
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
        warnings = "".join(f"<li>{escape(str(w))}</li>" for w in summary.get("warnings", []))
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
    limitations = "".join(f"<li>{escape(x)}</li>" for x in data["limitations"])
    steps = "".join(
        f"<h3>{escape(st['tool'])} {escape(st['tool_version'])}</h3>"
        f"<p class='muted'>Inputs: {escape(', '.join(st['inputs']))} · finished {escape(st['finished_at'] or '')}"
        f" · job <code>{escape(st['job_id'])}</code></p>"
        + "".join(f"<p>{escape(h)}</p>" for h in st["highlights"])
        + "".join(f"<pre>{escape(c)}</pre>" for c in st["commands"])
        for st in data.get("processing", [])
    )
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
 .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
 .chart {{ border:1px solid #EEF2F7; border-radius: 8px; padding: 8px; }}
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
<h2>Limitations</h2><ul>{limitations}</ul>
<footer>This report is descriptive. It contains values computed from the input files and does not
make clinical or biological claims.</footer>
</main></body></html>"""
