"""Worker tasks that polish an assembly (Racon with long reads, Pilon with short reads) and compare the result with
its draft.

Each round's commands, logs and changes are recorded. The comparison separates:

* direct evidence of what changed in the sequence: MUMmer dnadiff between the input and output of every round and
  between the draft and the final result (substitutions, insertions and deletions, unaligned bases at contig ends),
  and Pilon's own list of changes;
* indirect indicators: how well the same reads align to the draft and to the polished assembly (samtools stats:
  mapped reads, edit distance per aligned base, indels), and the assembly statistics before and after.

A change is not necessarily a correction: only a comparison with a trusted reference (e.g. QUAST with one) says
whether the polished sequence is closer to the truth.
"""
from __future__ import annotations

import gzip
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from arva_core.assembly_stats import ContigAnnotation
from arva_core.formats import is_gzip
from arva_core.genome_view import depth_bins, parse_depth_lines, write_depth_profile
from arva_tools import ToolExecutionError, ToolStatus, ToolTimeoutError
from arva_tools.dnadiff import DnadiffAdapter, nucmer_version
from arva_tools.flye import read_link_name
from arva_tools.mapping import SORT_MEMORY_DEFAULT_MB, BwaAdapter, Minimap2Adapter, SamtoolsAdapter
from arva_tools.pilon import PilonAdapter, PilonParams, java_executable, java_version
from arva_tools.racon import RaconAdapter, RaconParams
from arva_tools.registry import detect

from app.models import Assembly, FileFormat, RawFile
from app.services.assemblies import register_assembly
from app.services.short_hybrid import ROLES, library_layout
from app.tasks.common import JobContext, JobFailure, now, run_job
from app.tasks.tools import _log_inputs, _rel, _resolve_tool, _run, _sha256

CHANGE_KINDS = ("snp", "insertion", "deletion", "other")
STATS_KEYS = ("reads", "reads_mapped", "mapped_percent", "reads_properly_paired", "properly_paired_percent",
              "bases_mapped_cigar", "nm_sum", "error_rate", "edit_distance_per_100_bases", "insertion_events",
              "deletion_events", "indel_events_per_100kb", "average_length", "supplementary_alignments")
ASSEMBLY_KEYS = ("contig_count", "total_length", "largest_contig", "n50", "l50", "gc_percent", "n_count")
_PILON_SUFFIX = re.compile(r"(?:_pilon)+$")
DEPTH_RESOLUTION = 25


class _Steps:
    """job.progress for a polishing run: its planned steps, the current one and the log the tool is writing."""

    def __init__(self, ctx: JobContext, tool: str, steps: list[str]):
        self.ctx, self.tool, self.steps = ctx, tool, steps
        self.index, self.log_path = 0, None
        self.started, self.started_at, self.step_started_at = time.monotonic(), now(), None

    def start(self, step: str, log_path: Path | None = None) -> None:
        self.index = self.steps.index(step) + 1
        self.step_started_at, self.log_path = now(), log_path
        self.ctx.log(f"Step {self.index}/{len(self.steps)}: {step}")
        self()

    def drop(self, steps: list[str]) -> None:
        self.steps = [s for s in self.steps if s not in steps]

    def __call__(self, finished: bool = False) -> None:
        self.ctx.job.progress = {
            "tool": self.tool,
            "stage": self.steps[self.index - 1] if self.index else None,
            "stage_index": self.index or None,
            "stages_total": len(self.steps),
            "stages": self.steps,
            "started_at": self.started_at.isoformat(),
            "stage_started_at": self.step_started_at.isoformat() if self.step_started_at else None,
            "updated_at": now().isoformat(),
            "elapsed_seconds": round(time.monotonic() - self.started, 1),
            "finished": finished,
            "log": _rel(self.ctx, self.log_path) if self.log_path else None,
        }
        self.ctx.log.flush()


def _helper(ctx: JobContext, tool_id: str, required: bool = True) -> dict[str, Any] | None:
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available or not d.path:
        if required:
            raise JobFailure(f"{d.info.name} is not available on this worker ({d.status.value}): {d.message}",
                             "tool_unavailable", tool=d.info.name, status=d.status.value, message=d.message)
        ctx.log(f"{d.info.name} is not available ({d.status.value}); its part of the comparison is left out")
        return None
    ctx.log(f"{d.info.name}: {d.path} (version {d.version}{'' if d.version_validated else ', not validated with ARVA'})")
    return {"name": d.info.name, "tool_id": tool_id, "path": d.path, "version": d.version,
            "version_validated": d.version_validated}


def _draft(ctx: JobContext) -> Assembly:
    """The draft recorded with the job, after checking that its contigs are the file that was registered."""
    record = (ctx.job.parameters or {}).get("draft") or {}
    a = ctx.db.get(Assembly, record.get("assembly_id") or "")
    if a is None or a.sample_id != ctx.job.sample_id:
        raise JobFailure(f"The draft assembly {record.get('assembly_id')} no longer exists",
                         "assembly_missing", assembly=str(record.get("assembly_id")))
    src = ctx.path(a.contigs_path)
    if not src.is_file():
        raise JobFailure("The draft assembly's contigs file is missing on disk",
                         "contigs_missing", assembly=str(record.get("assembly_id")))
    if (digest := _sha256(src)) != record.get("contigs_sha256"):
        raise JobFailure(f"The draft's contigs changed since the job was queued (sha256 {digest}, recorded "
                         f"{record.get('contigs_sha256')})", "contigs_changed", assembly=str(record.get("assembly_id")))
    ctx.log(f"Draft: {a.assembler} {a.assembler_version} assembly {a.id} ({a.kind.value}; job {a.job_id}; "
            f"{a.stats['contig_count']:,} contigs, {a.stats['total_length']:,} bp; contigs sha256 {digest})")
    return a


def _copy_fasta(src: Path, dst: Path) -> None:
    opener = gzip.open if is_gzip(src) else open
    with opener(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def _link_reads(ctx: JobContext, links: Path) -> dict[str, Path]:
    roles = (ctx.job.parameters or {}).get("inputs") or {}
    files: dict[str, RawFile] = {f.id: f for f in ctx.input_files()}
    _log_inputs(ctx, list(files.values()))
    links.mkdir(parents=True)
    out = {}
    for n, role in enumerate(ROLES, 1):
        if not (file_id := roles.get(role)):
            continue
        f = files.get(file_id)
        if f is None:
            raise JobFailure(f"the {role} file {file_id} is not one of this job's inputs")
        if f.file_format not in (FileFormat.fastq, FileFormat.fastq_gz):
            raise JobFailure(f"{f.original_filename} is not a FASTQ file", "not_fastq", file=f.original_filename)
        link = links / read_link_name(n, f.original_filename, f.file_format is FileFormat.fastq_gz)
        link.symlink_to(ctx.path(f.stored_path))
        out[role] = link
        ctx.log(f"Reads as {role}: {f.original_filename}")
    return out


def _fasta_names(path: Path) -> list[str]:
    with open(path, errors="replace") as fh:
        return [line[1:].split()[0] if line[1:].split() else "" for line in fh if line.startswith(">")]


def _dnadiff(ctx: JobContext, dnadiff: dict | None, work: Path, before: str, after: str, name: str,
             keep: Path, logs: Path) -> dict[str, Any] | None:
    """dnadiff of two FASTA files in `work` (plain names; dnadiff passes them to a shell); keeps its report, .snps
    and .1coords in `keep` as dnadiff_<name>.*."""
    if dnadiff is None:
        return None
    prefix = f"dnadiff_{name}"
    _run(ctx, DnadiffAdapter.argv(dnadiff["path"], prefix, before, after), work, f"{prefix}.log", log_dir=logs)
    keep.mkdir(exist_ok=True)
    for suffix in ("report", "snps", "1coords"):
        (work / f"{prefix}.{suffix}").replace(keep / f"{prefix}.{suffix}")
    for leftover in work.glob(f"{prefix}.*"):
        leftover.unlink()
    try:
        report = DnadiffAdapter.parse_report((keep / f"{prefix}.report").read_text(errors="replace"))
        events = DnadiffAdapter.parse_snps((keep / f"{prefix}.snps").read_text(errors="replace"))
        ends = DnadiffAdapter.parse_coords((keep / f"{prefix}.1coords").read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"dnadiff's output cannot be read: {exc}",
                         "output_unreadable", tool="dnadiff", detail=str(exc)) from exc
    by_contig = events.pop("by_contig")
    return {"before": report["reference"], "after": report["query"], "events": events, "events_by_contig": by_contig,
            "ends": ends}


def _dnadiff_changes(diff: dict[str, Any]) -> dict[str, dict[str, int]]:
    e = diff["events"]
    return {"snp": {"events": e["substitutions"], "bases": e["substitutions"]},
            "insertion": {"events": e["insertions"], "bases": e["inserted_bases"]},
            "deletion": {"events": e["deletions"], "bases": e["deleted_bases"]},
            "other": {"events": 0, "bases": 0}}


def _pilon_changes(parsed: dict[str, Any]) -> dict[str, dict[str, int]]:
    t = parsed["totals"]
    other = {"events": t["substitution"]["events"] + t["replacement"]["events"],
             "bases": t["substitution"]["bases"] + t["replacement"]["bases"]}
    return {"snp": t["snp"], "insertion": t["insertion"], "deletion": t["deletion"], "other": other}


def _alignment_stats(ctx: JobContext, samtools: str, bam: Path, name: str, keep: Path, logs: Path) -> dict[str, Any]:
    keep.mkdir(exist_ok=True)
    stats, coverage = keep / f"{name}.samtools_stats.txt", keep / f"{name}.samtools_coverage.tsv"
    _run(ctx, SamtoolsAdapter.stats_argv(samtools, bam), bam.parent, f"{name}.samtools_stats.log", stdout=stats,
         log_dir=logs)
    _run(ctx, SamtoolsAdapter.coverage_argv(samtools, bam), bam.parent, f"{name}.samtools_coverage.log",
         stdout=coverage, log_dir=logs)
    try:
        parsed = SamtoolsAdapter.parse_stats(stats.read_text(errors="replace"))
        rows = SamtoolsAdapter.parse_coverage(coverage.read_text(errors="replace"))
    except ValueError as exc:
        raise JobFailure(f"samtools' alignment statistics cannot be read: {exc}",
                         "output_unreadable", tool="samtools", detail=str(exc)) from exc
    return {"stats": {k: parsed.get(k) for k in STATS_KEYS}, "coverage": rows,
            "depth_profile": _depth_profile(ctx, samtools, bam, name, {r["contig"]: r["length"] for r in rows}, keep,
                                            logs)}


def _depth_profile(ctx: JobContext, samtools: str, bam: Path, name: str, lengths: dict[str, int], keep: Path,
                   logs: Path) -> dict[str, Any]:
    """The alignment's per-base depth summed in bins of DEPTH_RESOLUTION bases (keep/<name>.depth_profile.json), so
    the Genome Explorer can draw coverage after the alignment itself is deleted."""
    argv = SamtoolsAdapter.depth_argv(samtools, bam)
    depth = bam.parent / f"{name}.depth.tsv.gz"
    _run(ctx, argv, bam.parent, f"{name}.samtools_depth.log", stdout=depth, log_dir=logs)
    try:
        with gzip.open(depth, "rt") as fh:
            sums = depth_bins(parse_depth_lines(fh), lengths, DEPTH_RESOLUTION)
    except ValueError as exc:
        raise JobFailure(f"samtools depth output cannot be read: {exc}",
                         "output_unreadable", tool="samtools", detail=str(exc)) from exc
    finally:
        depth.unlink(missing_ok=True)
    out = keep / f"{name}.depth_profile.json"
    write_depth_profile(out, sums, lengths, DEPTH_RESOLUTION,
                        {"alignment": name, "command": [Path(argv[0]).name, *argv[1:-1], bam.name],
                         "deletions_counted": False, "overlapping_mates_counted_twice": True})
    ctx.log(f"Depth profile of the {name} alignment: per-base depth (samtools depth) summed in {DEPTH_RESOLUTION} bp "
            f"bins for {len(sums)} contig(s) → {out.name}")
    return {"path": _rel(ctx, out), "sha256": _sha256(out), "resolution": DEPTH_RESOLUTION}


def _sort_memory_mb(ctx: JobContext, threads: int) -> int | None:
    """samtools sort -m per thread so that all threads stay within the job's memory per job, when samtools' default
    would not; None keeps the default (sorting with less memory only writes more temporary files)."""
    memory_gb = (ctx.job.resources or {}).get("memory_gb")
    if not memory_gb:
        return None
    per_thread = memory_gb * 1024 // max(threads, 1)
    return per_thread if per_thread < SORT_MEMORY_DEFAULT_MB else None


def _sorted_bam(ctx: JobContext, samtools: str, sam: Path, name: str, threads: int, logs: Path,
                index: bool = False) -> Path:
    bam = sam.parent / f"{name}.bam"
    argv = SamtoolsAdapter.sort_argv(samtools, sam, bam, threads, sam.parent / f"{name}.sort",
                                     _sort_memory_mb(ctx, threads))
    _run(ctx, argv, sam.parent, f"{name}.samtools_sort.log", log_dir=logs)
    sam.unlink()
    if index:
        _run(ctx, SamtoolsAdapter.index_argv(samtools, bam), sam.parent, f"{name}.samtools_index.log", log_dir=logs)
    return bam


def _long_alignment(ctx: JobContext, tools: dict, target: Path, reads: Path, preset: str, threads: int, name: str,
                    keep: Path, logs: Path) -> dict[str, Any]:
    sam = target.parent / f"{name}.sam.gz"
    _run(ctx, Minimap2Adapter.argv(tools["minimap2"]["path"], preset, threads, target, reads, None, sam=True),
         target.parent, f"{name}.minimap2.log", stdout=sam, log_dir=logs)
    bam = _sorted_bam(ctx, tools["samtools"]["path"], sam, name, threads, logs)
    out = _alignment_stats(ctx, tools["samtools"]["path"], bam, name, keep, logs)
    bam.unlink()
    return out


def _short_alignment(ctx: JobContext, tools: dict, target: Path, reads: dict[str, Path], threads: int, name: str,
                     logs: Path) -> dict[str, Path]:
    """BWA-MEM alignments of the pairs and of the unpaired reads to `target`, sorted and indexed."""
    prefix = target.with_suffix("")
    _run(ctx, BwaAdapter.index_argv(tools["bwa"]["path"], target, prefix), target.parent, f"{name}.bwa_index.log",
         log_dir=logs)
    bams = {}
    for library, files in (("frags", [reads.get("r1"), reads.get("r2")]), ("unpaired", [reads.get("unpaired")])):
        if not all(files):
            continue
        sam = target.parent / f"{name}.{library}.sam.gz"
        _run(ctx, BwaAdapter.mem_argv(tools["bwa"]["path"], prefix, files, threads), target.parent,
             f"{name}.{library}.bwa_mem.log", stdout=sam, log_dir=logs)
        bams[library] = _sorted_bam(ctx, tools["samtools"]["path"], sam, f"{name}.{library}", threads, logs, index=True)
    for index_file in target.parent.glob(f"{prefix.name}.*"):
        if index_file.suffix in (".amb", ".ann", ".bwt", ".pac", ".sa"):
            index_file.unlink()
    return bams


def _assembly_summary(a: Assembly) -> dict[str, Any]:
    return {k: a.stats[k] for k in ASSEMBLY_KEYS}


def _observations(polisher: str, draft: Assembly, overall: dict | None, before: dict, after: dict,
                  rounds: list[dict]) -> list[dict[str, Any]]:
    """Facts worth a note, each with a code and values for a translated message."""
    out = []
    if overall is not None:
        circular = {c["name"]: c.get("circular") for c in draft.contigs}
        for end in overall["ends"]:
            lost = end["unaligned_start"] + end["unaligned_end"]
            if lost:
                out.append({"code": "ends_trimmed", "params": {
                    "contig": end["contig"], "start": end["unaligned_start"], "end": end["unaligned_end"],
                    "circular": circular.get(end["contig"])},
                    "message": f"{polisher} left {end['unaligned_start']:,} bp at the start and "
                               f"{end['unaligned_end']:,} bp at the end of {end['contig']} unaligned to the polished "
                               "assembly (dnadiff): the polished contig lacks them"})
        if overall["before"].get("unaligned_sequences"):
            out.append({"code": "contigs_unaligned", "params": {"count": overall["before"]["unaligned_sequences"]},
                        "message": f"{overall['before']['unaligned_sequences']} draft contig(s) have no alignment to the "
                                   "polished assembly (dnadiff)"})
    known = [r["changes"] for r in rounds if r["changes"] is not None]
    if known and len(known) == len(rounds) and not any(c[k]["events"] for c in known for k in CHANGE_KINDS):
        out.append({"code": "no_changes", "params": {}, "message": f"{polisher} changed no base of the draft"})
    b, a = before["stats"].get("edit_distance_per_100_bases"), after["stats"].get("edit_distance_per_100_bases")
    if b is not None and a is not None and a > b:
        out.append({"code": "edit_distance_increased", "params": {"before": round(b, 4), "after": round(a, 4)},
                    "message": f"The reads' edit distance per 100 aligned bases rose from {b:.4f} to {a:.4f} after "
                               "polishing (indirect indicator): check the polished assembly before using it"})
    return out


def _queue_followups(ctx: JobContext, polished: Assembly, draft: Assembly) -> dict[str, Any]:
    """The hybrid strategy's Pilon step and the optional QUAST comparison, created in this job's transaction and
    enqueued once it is committed. A step that cannot be created is recorded, never failing this job."""
    from arva_tools.quast import QuastParams

    from app.services.jobs import (
        ToolUnavailableError,
        enqueue_polishing,
        enqueue_quast,
        new_pilon_job,
        new_quast_job,
    )
    from app.services.performance import effective_resources
    from app.services.quast import labels

    params = ctx.job.parameters or {}
    out: dict[str, Any] = {}
    res = effective_resources(ctx.db)
    then = params.get("then_pilon")
    compared = [*(params.get("compare_with") or []), draft.id]
    if then:
        try:
            inputs = {r: ctx.db.get(RawFile, i) if i else None for r, i in then["inputs"].items()}
            job = new_pilon_job(ctx.job.sample, polished, inputs, PilonParams.from_dict(then["params"]),
                                {"strategy": "hybrid", "quast": params.get("quast", False),
                                 "quast_reference_file_id": params.get("quast_reference_file_id"),
                                 "compare_with": compared}, res, parent_job_id=ctx.job.id)
        except (ToolUnavailableError, ValueError) as exc:
            out["pilon_error"] = str(exc)
            ctx.log(f"The hybrid strategy's Pilon step could not be queued: {exc}")
            return out
        ctx.db.add(job)
        ctx.db.flush()
        out["pilon_job_id"] = job.id
        ctx.after_commit.append(lambda: enqueue_polishing([job]))
        ctx.log(f"Queued the hybrid strategy's Pilon step on this result (job {job.id})")
        return out
    if params.get("quast"):
        ids = list(dict.fromkeys([*compared, polished.id]))
        assemblies = [a for i in ids if (a := ctx.db.get(Assembly, i)) is not None]
        reference_id = params.get("quast_reference_file_id")
        reference = ctx.db.get(RawFile, reference_id) if reference_id else None
        try:
            job = new_quast_job(ctx.job.sample, assemblies, labels(assemblies), reference,
                                QuastParams(threads=params.get("threads") or 1), res, parent_job_id=ctx.job.id)
        except (ToolUnavailableError, ValueError) as exc:
            out["quast_error"] = str(exc)
            ctx.log(f"QUAST could not be queued to compare the assemblies: {exc}")
            return out
        ctx.db.add(job)
        ctx.db.flush()
        out["quast_job_id"] = job.id
        ctx.after_commit.append(lambda: enqueue_quast([job]))
        ctx.log(f"Queued QUAST on {', '.join(a.id[:8] for a in assemblies)} (job {job.id})")
    return out


def _finish(ctx: JobContext, polisher: str, draft: Assembly, work: Path, results: Path, final: Path, read_type: str,
            rounds: list[dict], overall: dict | None, before: dict, after: dict, helpers: list[dict],
            extra: dict) -> None:
    """Keep the outputs, register the polished assembly and write the job's summary."""
    polished_path = results / "polished.fasta"
    final.replace(polished_path)
    kept_rounds = results / "rounds"
    for r in rounds[:-1]:
        kept_rounds.mkdir(exist_ok=True)
        (work / f"round{r['round']}.fasta").replace(kept_rounds / f"round{r['round']}.fasta")
    shutil.rmtree(work)

    depth = {row["contig"]: row["mean_depth"] for row in after["coverage"]}
    circular = {c["name"]: c.get("circular") for c in draft.contigs}
    annotations = {}
    for name in _fasta_names(polished_path):
        base = _PILON_SUFFIX.sub("", name)
        annotations[name] = ContigAnnotation(coverage=depth.get(name), circular=circular.get(base))
    polished = register_assembly(ctx, assembler=polisher, mode=draft.mode, read_type=read_type,
                                 contigs=polished_path, annotations=annotations, parent=draft)
    ctx.db.flush()
    ctx.log(f"Per-contig coverage of the polished assembly: mean depth of the polishing reads mapped to it (samtools "
            f"coverage); circularity as {draft.assembler} reported it for the draft contig")
    followups = _queue_followups(ctx, polished, draft)
    direct_source = "dnadiff" if overall is not None else ("pilon_changes" if polisher == "Pilon" else None)
    ctx.job.result_summary = {
        "polisher": polisher,
        "polisher_version": ctx.job.tool_version,
        "strategy": (ctx.job.parameters or {}).get("strategy"),
        "draft": {**(ctx.job.parameters or {}).get("draft", {}), "stats": _assembly_summary(draft),
                  "parent_assembly_id": draft.parent_assembly_id},
        "polished_assembly_id": polished.id,
        "read_type": read_type,
        "rounds_requested": (ctx.job.parameters or {}).get("rounds"),
        "rounds_run": len(rounds),
        "rounds": rounds,
        "direct": {"source": direct_source, "dnadiff": overall,
                   "pilon_changes": _sum_changes(rounds) if polisher == "Pilon" else None},
        "indirect": {"aligner": extra.pop("aligner"), "reads": extra.pop("reads_used"), "before": before,
                     "after": after},
        "assembly_stats": {"before": _assembly_summary(draft), "after": _assembly_summary(polished)},
        "observations": _observations(polisher, draft, overall, before, after, rounds),
        "helpers": helpers,
        "followups": followups,
        **extra,
    }
    for o in ctx.job.result_summary["observations"]:
        ctx.log(f"Note [{o['code']}]: {o['message']}")
    outputs = [polished_path, *sorted(p for p in results.rglob("*") if p.is_file() and p != polished_path)]
    ctx.job.output_paths = [_rel(ctx, p) for p in outputs]


def _sum_changes(rounds: list[dict]) -> dict[str, dict[str, int]]:
    total = {k: {"events": 0, "bases": 0} for k in CHANGE_KINDS}
    for r in rounds:
        for k, v in (r.get("pilon_changes") or {}).items():
            total[k]["events"] += v["events"]
            total[k]["bases"] += v["bases"]
    return total


def _setup(ctx: JobContext) -> tuple[Path, Path, Path, Path]:
    results = ctx.path(ctx.results_rel)
    work, logs, keep = results / "work", results / "logs", results / "comparison"
    for d in (work, logs):
        d.mkdir(parents=True)
    return results, work, logs, keep


def _commands_since(ctx: JobContext, start: int) -> list[list[str]]:
    return list((ctx.job.commands or [])[start:])


# --- Racon ---------------------------------------------------------------------------------------------------

def _racon_body(ctx: JobContext) -> None:
    exe = _resolve_tool(ctx, "racon")
    params = RaconParams.from_dict(ctx.job.parameters or {})
    tools = {t: _helper(ctx, t) for t in ("minimap2", "samtools")}
    dnadiff = _helper(ctx, "dnadiff", required=False)
    draft = _draft(ctx)
    results, work, logs, keep = _setup(ctx)
    reads = _link_reads(ctx, work / "input")
    if "long" not in reads:
        raise JobFailure("Racon needs the long reads, and none were recorded with the job")
    long = reads["long"]
    _copy_fasta(ctx.path(draft.contigs_path), work / "round0.fasta")
    try:
        supported = RaconAdapter.help_options(exe)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"Racon's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="Racon", detail=str(exc)) from exc
    ctx.log(f"Racon: {params.rounds} round(s); minimap2 preset {params.read_type}; -m {params.match} -x "
            f"{params.mismatch} -g {params.gap} -w {params.window_length} -q {params.quality_threshold:g} -e "
            f"{params.error_threshold:g}; -u keeps contigs without overlaps; consensus trimming at window ends "
            "(Racon's default) kept")
    steps = _Steps(ctx, "Racon", [f"racon_round_{i}" for i in range(1, params.rounds + 1)] +
                   ["alignment_stats", "comparison"])
    draft_names = _fasta_names(work / "round0.fasta")
    rounds = []
    current = work / "round0.fasta"
    for i in range(1, params.rounds + 1):
        start = len(ctx.job.commands or [])
        paf, out = work / f"round{i}.paf", work / f"round{i}.fasta"
        steps.start(f"racon_round_{i}", logs / f"round{i}.minimap2.log")
        _run(ctx, Minimap2Adapter.argv(tools["minimap2"]["path"], params.read_type, params.threads, current, long, paf),
             work, f"round{i}.minimap2.log", log_dir=logs, monitor=steps)
        racon_log = logs / f"round{i}.racon.log"
        steps.log_path = racon_log
        try:
            _run(ctx, RaconAdapter.argv(exe, params, long, paf, current, supported), work, racon_log.name, stdout=out,
                 log_dir=logs, monitor=steps)
        except ToolExecutionError as exc:
            if isinstance(exc, ToolTimeoutError):
                raise
            reason = RaconAdapter.failure_reason(racon_log.read_text(errors="replace") if racon_log.is_file() else
                                                 exc.stderr_tail, exc.returncode)
            if reason is None:
                raise
            raise JobFailure(reason) from None
        paf.unlink()
        try:
            rows = RaconAdapter.parse_headers([line[1:].strip() for line in out.read_text(errors="replace").splitlines()
                                               if line.startswith(">")])
        except ValueError as exc:
            raise JobFailure(f"Racon's output cannot be read: {exc}",
                             "output_unreadable", tool="Racon", detail=str(exc)) from exc
        if sorted(rows) != sorted(draft_names):
            raise JobFailure(f"Racon wrote contigs {', '.join(list(rows)[:5])}, not the draft's "
                             f"{', '.join(draft_names[:5])}; nothing was registered")
        diff = _dnadiff(ctx, dnadiff, work, current.name, out.name, f"round{i}", keep, logs)
        rounds.append({"round": i, "changes": _dnadiff_changes(diff) if diff else None,
                       "changes_source": "dnadiff" if diff else None, "dnadiff": diff, "racon_contigs": rows,
                       "commands": _commands_since(ctx, start)})
        if diff:
            e = diff["events"]
            ctx.log(f"Round {i} (dnadiff): {e['substitutions']:,} substitutions, {e['insertions']:,} insertions "
                    f"({e['inserted_bases']:,} bp), {e['deletions']:,} deletions ({e['deleted_bases']:,} bp)")
        current = out

    steps.start("alignment_stats", logs / "draft.minimap2.log")
    before = _long_alignment(ctx, tools, work / "round0.fasta", long, params.read_type, params.threads, "draft", keep,
                             logs)
    steps.log_path = logs / "polished.minimap2.log"
    after = _long_alignment(ctx, tools, current, long, params.read_type, params.threads, "polished", keep, logs)
    steps.start("comparison", logs / "dnadiff_overall.log")
    overall = rounds[0]["dnadiff"] if len(rounds) == 1 else \
        _dnadiff(ctx, dnadiff, work, "round0.fasta", current.name, "overall", keep, logs)
    steps(finished=True)
    helpers = [h for h in (tools["minimap2"], tools["samtools"], dnadiff) if h]
    if dnadiff:
        dnadiff["nucmer_version"] = nucmer_version(dnadiff["path"])
    _finish(ctx, "Racon", draft, work, results, current, params.read_type, rounds, overall, before, after, helpers,
            {"aligner": f"minimap2 {tools['minimap2']['version']} -x {params.read_type}", "reads_used": "long"})


def run_racon_job(job_id: str) -> str:
    return run_job(job_id, _racon_body)


# --- Pilon ---------------------------------------------------------------------------------------------------

def _pilon_body(ctx: JobContext) -> None:
    jar = _resolve_tool(ctx, "pilon")
    if (d := detect("pilon")).reason == "version_from_package":
        ctx.log(f"Note: {d.message}")
    java = java_executable()
    if java is None:
        raise JobFailure("Java was not found; Pilon needs a Java runtime", "java_missing")
    java_record = {"name": "Java", "tool_id": "java", "path": java, "version": java_version(java),
                   "version_validated": False}
    ctx.log(f"Java: {java} (version {java_record['version']}); Pilon runs as java -Xmx<heap> -jar {jar}")
    params = PilonParams.from_dict(ctx.job.parameters or {})
    roles = (ctx.job.parameters or {}).get("inputs") or {}
    tools = {t: _helper(ctx, t) for t in ("bwa", "samtools")}
    dnadiff = _helper(ctx, "dnadiff", required=False)
    draft = _draft(ctx)
    results, work, logs, keep = _setup(ctx)
    reads = _link_reads(ctx, work / "input")
    if not (reads.get("r1") and reads.get("r2")) and not reads.get("unpaired"):
        raise JobFailure("Pilon needs paired-end or unpaired short reads, and none were recorded with the job")
    _copy_fasta(ctx.path(draft.contigs_path), work / "round0.fasta")
    try:
        supported = PilonAdapter.help_options(java, jar)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise JobFailure(f"Pilon's --help could not be read to check its options: {exc}",
                         "help_unreadable", tool="Pilon", detail=str(exc)) from exc
    ctx.log(f"Pilon: up to {params.rounds} round(s); --fix {params.fix_list()}; --mindepth {params.mindepth:g} "
            f"--minmq {params.minmq} --minqual {params.minqual}; Java heap -Xmx{params.heap_gb}g; BWA-MEM and samtools "
            f"with {params.threads} thread(s)" + ("; stops after a round that changes nothing"
                                                  if params.stop_when_unchanged else ""))
    round_steps = [f"pilon_round_{i}" for i in range(1, params.rounds + 1)]
    steps = _Steps(ctx, "Pilon", [*round_steps, "alignment_stats", "comparison"])
    rounds = []
    before = None
    current = work / "round0.fasta"
    for i in range(1, params.rounds + 1):
        start = len(ctx.job.commands or [])
        steps.start(f"pilon_round_{i}", logs / f"round{i}.frags.bwa_mem.log")
        bams = _short_alignment(ctx, tools, current, reads, params.threads, f"round{i}", logs)
        if before is None:
            primary = bams.get("frags") or bams["unpaired"]
            before = _alignment_stats(ctx, tools["samtools"]["path"], primary, "draft", keep, logs)
        pilon_log = logs / f"round{i}.pilon.log"
        steps.log_path = pilon_log
        argv = PilonAdapter.argv(java, jar, params, current, work, f"round{i}", supported, frags=bams.get("frags"),
                                 unpaired=bams.get("unpaired"))
        try:
            _run(ctx, argv, work, pilon_log.name, log_dir=logs, monitor=steps)
        except ToolExecutionError as exc:
            if isinstance(exc, ToolTimeoutError):
                raise
            reason = PilonAdapter.failure_reason(pilon_log.read_text(errors="replace") if pilon_log.is_file() else
                                                 exc.stderr_tail, exc.returncode, params.heap_gb)
            if reason is None:
                raise
            raise JobFailure(reason) from None
        out, changes_file = work / f"round{i}.fasta", work / f"round{i}.changes"
        if not out.is_file() or not changes_file.is_file():
            raise JobFailure(f"Pilon exited without an error but did not write round{i}.fasta and round{i}.changes",
                             "outputs_missing", tool="Pilon", files=f"round{i}.fasta, round{i}.changes")
        for bam in bams.values():
            for f in (bam, bam.with_suffix(".bam.bai")):
                f.unlink(missing_ok=True)
        try:
            changes = PilonAdapter.parse_changes(changes_file.read_text(errors="replace"))
        except ValueError as exc:
            raise JobFailure(f"Pilon's list of changes cannot be read: {exc}",
                             "output_unreadable", tool="Pilon", detail=str(exc)) from exc
        log_summary = PilonAdapter.parse_log(pilon_log.read_text(errors="replace"))
        keep.mkdir(exist_ok=True)
        changes_file.replace(keep / changes_file.name)
        diff = _dnadiff(ctx, dnadiff, work, current.name, out.name, f"round{i}", keep, logs)
        pilon_changes = _pilon_changes(changes)
        rounds.append({"round": i, "changes": _dnadiff_changes(diff) if diff else pilon_changes,
                       "changes_source": "dnadiff" if diff else "pilon_changes", "pilon_changes": pilon_changes,
                       "pilon_log": {"totals": log_summary["totals"], "mean_coverage": log_summary["mean_coverage"]},
                       "dnadiff": diff, "commands": _commands_since(ctx, start)})
        ctx.log(f"Round {i} (Pilon's changes): {changes['changes']:,} change(s): "
                + ", ".join(f"{k} {v['events']:,} ({v['bases']:,} bp)" for k, v in pilon_changes.items()))
        current = out
        if params.stop_when_unchanged and changes["changes"] == 0 and i < params.rounds:
            ctx.log(f"Round {i} changed nothing, so the remaining {params.rounds - i} round(s) would repeat it; stopped "
                    "(stop_when_unchanged)")
            steps.drop(round_steps[i:])
            break

    steps.start("alignment_stats", logs / "polished.frags.bwa_mem.log")
    bams = _short_alignment(ctx, tools, current, reads, params.threads, "polished", logs)
    after = _alignment_stats(ctx, tools["samtools"]["path"], bams.get("frags") or bams["unpaired"], "polished", keep,
                             logs)
    steps.start("comparison", logs / "dnadiff_overall.log")
    overall = rounds[0]["dnadiff"] if len(rounds) == 1 else \
        _dnadiff(ctx, dnadiff, work, "round0.fasta", current.name, "overall", keep, logs)
    steps(finished=True)
    helpers = [java_record, *(h for h in (tools["bwa"], tools["samtools"], dnadiff) if h)]
    if dnadiff:
        dnadiff["nucmer_version"] = nucmer_version(dnadiff["path"])
    used = "frags" if "frags" in bams else "unpaired"
    _finish(ctx, "Pilon", draft, work, results, current, library_layout(roles), rounds, overall, before, after, helpers,
            {"aligner": f"bwa mem {tools['bwa']['version']} -K 100000000",
             "reads_used": "paired-end" if used == "frags" else "unpaired",
             "stopped_early": len(rounds) < params.rounds})


def run_pilon_job(job_id: str) -> str:
    return run_job(job_id, _pilon_body)
