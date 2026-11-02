"""Worker task: variant calling of a sample's reads against a reference.

Steps (every command is logged and recorded with the job): copy the reference (checked against the SHA-256 recorded
when the job was queued) and index it; align the reads (BWA-MEM for short reads, minimap2 for long reads, with a read
group naming the sample); sort and index; samtools stats/coverage and depth profile; the per-base depth with the
caller's quality floors (low-depth intervals, for the SNP matrix); bcftools mpileup → call (haploid) → norm → three
soft filters → csq (when the reference is an annotated ARVA assembly) → index. The alignment itself is deleted unless
the user asked to keep it.
"""
from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any

from arva_core import variants as av
from arva_tools.bcftools import BcftoolsAdapter, VariantParams, filter_expressions
from arva_tools.mapping import BwaAdapter, Minimap2Adapter, SamtoolsAdapter, read_group_line

from app.models import Annotation, Assembly, VariantCall
from app.services import variants as svc
from app.services.annotation import features_of, original_names
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.polishing import _alignment_stats, _copy_fasta, _helper, _link_reads, _sorted_bam
from app.tasks.tools import _rel, _run, _sha256


def _reference(ctx: JobContext, work: Path) -> tuple[Path, dict[str, Any]]:
    ref = (ctx.job.parameters or {}).get("reference") or {}
    if ref.get("kind") == "assembly":
        a = ctx.db.get(Assembly, ref.get("assembly_id") or "")
        if a is None:
            raise JobFailure("The reference assembly no longer exists", "variant_reference_missing")
        src = ctx.path(a.contigs_path)
    else:
        src = Path(ref.get("path") or "")
    if not src.is_file():
        raise JobFailure(f"The reference file is missing: {ref.get('label')}", "variant_reference_missing")
    dst = work / "reference.fasta"
    _copy_fasta(src, dst)
    digest = _sha256(dst)
    if digest != ref.get("sha256"):
        raise JobFailure(f"The reference changed since the job was queued (sha256 {digest}, recorded "
                         f"{ref.get('sha256')})", "variant_reference_changed")
    ctx.log(f"Reference: {ref.get('label')} ({ref.get('kind')}; {len(ref.get('contigs') or [])} sequence(s), "
            f"{ref.get('total_length'):,} bp; sha256 {digest})")
    return dst, ref


def _annotation(ctx: JobContext, ref: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]] | None:
    p = ctx.job.parameters or {}
    info = ref.get("annotation")
    if not p.get("effects") or not info:
        return None
    an = ctx.db.get(Annotation, info["id"])
    if an is None:
        raise JobFailure("The reference's annotation no longer exists", "variant_annotation_missing")
    try:
        return features_of(an), original_names(an)
    except FileNotFoundError as exc:
        raise JobFailure(str(exc), "variant_annotation_missing") from exc


def _align(ctx: JobContext, tools: dict, technology: str, ref: Path, reads: dict[str, Path], threads: int,
           work: Path, logs: Path, rg: str) -> Path:
    sam = work / "alignment.sam.gz"
    if technology == "illumina":
        prefix = work / "reference"
        _run(ctx, BwaAdapter.index_argv(tools["aligner"]["path"], ref, prefix), work, "bwa_index.log", log_dir=logs)
        files = [reads["r1"], reads["r2"]] if "r1" in reads else [reads["unpaired"]]
        _run(ctx, BwaAdapter.mem_argv(tools["aligner"]["path"], prefix, files, threads, rg), work, "bwa_mem.log",
             stdout=sam, log_dir=logs)
        for f in work.glob("reference.*"):
            if f.suffix in (".amb", ".ann", ".bwt", ".pac", ".sa"):
                f.unlink()
    else:
        preset = svc.ALIGNERS[technology][1]
        _run(ctx, Minimap2Adapter.argv(tools["aligner"]["path"], preset, threads, ref, reads["long"], None, sam=True,
                                       read_group=rg), work, "minimap2.log", stdout=sam, log_dir=logs)
    return _sorted_bam(ctx, tools["samtools"]["path"], sam, "alignment", threads, logs, index=True)


def _low_depth(ctx: JobContext, samtools: str, bam: Path, params: VariantParams, logs: Path) -> dict[str, Any]:
    out = bam.parent / "filtered_depth.tsv.gz"
    _run(ctx, SamtoolsAdapter.filtered_depth_argv(samtools, bam, params.min_mapq, params.min_baseq or 0),
         bam.parent, "samtools_depth_filtered.log", stdout=out, log_dir=logs)
    try:
        with gzip.open(out, "rt") as fh:
            low = av.low_depth_intervals(av.parse_depth(fh), params.min_depth)
    except ValueError as exc:
        raise JobFailure(f"samtools depth output cannot be read: {exc}", "output_unreadable", tool="samtools",
                         detail=str(exc)) from exc
    finally:
        out.unlink(missing_ok=True)
    return low


def _call(ctx: JobContext, bcftools: str, ref: Path, bam: Path, params: VariantParams, gff: Path | None,
          work: Path, logs: Path, results: Path) -> Path:
    steps = [("mpileup", BcftoolsAdapter.mpileup_argv(bcftools, ref, bam, work / "pileup.bcf", params)),
             ("call", BcftoolsAdapter.call_argv(bcftools, work / "pileup.bcf", work / "calls.bcf", params)),
             ("norm", BcftoolsAdapter.norm_argv(bcftools, ref, work / "calls.bcf", work / "normalised.bcf"))]
    src = work / "normalised.bcf"
    exprs = filter_expressions(params)
    for i, (name, expr) in enumerate(exprs):
        last = i == len(exprs) - 1
        out = (work / "filtered.vcf.gz" if gff is not None else results / "variants.vcf.gz") if last else \
            work / f"filter{i + 1}.bcf"
        steps.append((f"filter_{name}", BcftoolsAdapter.filter_argv(bcftools, name, expr, src, out, add=i > 0,
                                                                    compressed=last)))
        src = out
    if gff is not None:
        steps.append(("csq", BcftoolsAdapter.csq_argv(bcftools, ref, gff, src, results / "variants.vcf.gz")))
        src = results / "variants.vcf.gz"
    steps.append(("index", BcftoolsAdapter.index_argv(bcftools, src)))
    for name, argv in steps:
        _run(ctx, argv, work, f"bcftools_{name}.log", log_dir=logs)
    return src


def _entry(ctx: JobContext, path: Path) -> dict[str, Any]:
    return {"path": _rel(ctx, path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}


def _body(ctx: JobContext) -> None:
    p = ctx.job.parameters or {}
    technology = p["technology"]
    params = VariantParams(**{k: v for k, v in (p.get("settings") or {}).items()
                              if k in VariantParams.__dataclass_fields__})
    params.validate()
    aligner_id = svc.ALIGNERS[technology][0]
    tools = {"aligner": _helper(ctx, aligner_id), "samtools": _helper(ctx, "samtools"),
             "bcftools": _helper(ctx, "bcftools")}
    results = ctx.path(ctx.results_rel)
    work, logs = results / "work", results / "logs"
    for d in (work, logs):
        d.mkdir(parents=True)
    ref_path, ref = _reference(ctx, work)
    _run(ctx, SamtoolsAdapter.faidx_argv(tools["samtools"]["path"], ref_path), work, "samtools_faidx.log",
         log_dir=logs)
    reads = _link_reads(ctx, work / "reads")
    rg = read_group_line(ctx.job.id[:8], p["read_group_sample"])
    ctx.log(f"Technology: {technology}; aligner {tools['aligner']['name']} {tools['aligner']['version']}; caller "
            f"bcftools {tools['bcftools']['version']} (haploid); settings {json.dumps(params.as_dict(), sort_keys=True)}")
    bam = _align(ctx, tools, technology, ref_path, reads, params.threads, work, logs, rg)
    keep = results / "alignment_stats"
    stats = _alignment_stats(ctx, tools["samtools"]["path"], bam, "alignment", keep, logs)
    if not stats["stats"].get("reads_mapped"):
        raise JobFailure("No read aligned to the reference", "no_reads_mapped")
    low = _low_depth(ctx, tools["samtools"]["path"], bam, params, logs)
    annotation = _annotation(ctx, ref)
    gff = None
    csq_counts = None
    lengths = {c["name"]: c["length"] for c in ref.get("contigs") or []}
    if annotation is not None:
        features, names = annotation
        text, csq_counts = av.csq_gff(features, names, lengths)
        gff = results / "csq_annotation.gff3"
        gff.write_text(text)
        ctx.log(f"Coding sequences written for bcftools csq: {csq_counts}")
    vcf = _call(ctx, tools["bcftools"]["path"], ref_path, bam, params, gff, work, logs, results)
    with gzip.open(vcf, "rt") as fh:
        try:
            _, variants = av.parse_vcf(fh)
        except ValueError as exc:
            raise JobFailure(f"The VCF cannot be read: {exc}", "output_unreadable", tool="bcftools",
                             detail=str(exc)) from exc
    warnings: list[dict[str, Any]] = []
    if annotation is not None:
        seqs = _fasta(ref_path)
        marked = av.start_codon_notes(variants, annotation[0], annotation[1], seqs)
        if marked:
            warnings.append({"code": "start_codon_notes", "params": {"count": marked},
                             "text": f"{marked} variant(s) touch a start codon other than ATG: bcftools csq uses the "
                                     "standard genetic code there (no start_lost)"})
    callable_bases = sum(c["callable"] for c in low["contigs"].values())
    total = sum(lengths.values()) or 1
    summary = av.summarize(variants)
    summary.update({
        "distribution": av.distribution(variants, lengths),
        "alignment": stats["stats"], "coverage": stats["coverage"], "depth_profile": stats["depth_profile"],
        "callable_bases": callable_bases, "callable_percent": round(100 * callable_bases / total, 2),
        "low_depth_contigs": low["contigs"], "csq_features": csq_counts, "reference_length": total,
    })
    if not params.call_indels:
        warnings.append({"code": "no_indels", "params": {}, "text": "Indels were not called (-I)"})
    data = results / "variants.json.gz"
    with gzip.open(data, "wt") as fh:
        json.dump({"variants": variants, "low_depth": low}, fh)
    files = {"vcf": _entry(ctx, vcf), "vcf_index": _entry(ctx, vcf.parent / f"{vcf.name}.tbi"),
             "variants": _entry(ctx, data)}
    if gff is not None:
        files["csq_gff"] = _entry(ctx, gff)
    if p.get("keep_alignment"):
        for src, name in ((bam, "alignment.bam"), (bam.parent / f"{bam.name}.bai", "alignment.bam.bai")):
            dst = results / name
            shutil.move(src, dst)
            files["bam" if name.endswith(".bam") else "bam_index"] = _entry(ctx, dst)
    shutil.rmtree(work)
    vc = VariantCall(sample_id=ctx.job.sample_id, job_id=ctx.job.id,
                     reference_assembly_id=ref.get("assembly_id") if ref.get("kind") == "assembly" else None,
                     reference_sha256=ref["sha256"], reference=ref, technology=technology,
                     aligner=tools["aligner"]["name"], aligner_version=tools["aligner"]["version"] or "unknown",
                     caller_version=tools["bcftools"]["version"] or "unknown", reads=p.get("reads") or [],
                     parameters={"settings": params.as_dict(), "aligner_preset": svc.ALIGNERS[technology][1],
                                 "read_group_sample": p["read_group_sample"], "effects": gff is not None,
                                 "keep_alignment": bool(p.get("keep_alignment")),
                                 "tools": {k: {kk: t[kk] for kk in ("name", "version", "version_validated")}
                                           for k, t in tools.items()}},
                     summary=summary, warnings=warnings, files=files)
    ctx.db.add(vc)
    ctx.job.result_summary = {"pass": summary["pass"], "records": summary["records"], "by_type": summary["by_type"],
                              "files": files, "warnings": warnings}
    ctx.job.output_paths = [f["path"] for f in files.values()]
    ctx.log(f"{summary['records']} record(s), {summary['pass']} passing the filters; "
            f"{summary['callable_percent']}% of the reference callable (depth >= {params.min_depth})")


def _fasta(path: Path) -> dict[str, str]:
    seqs: dict[str, list[str]] = {}
    name = None
    with open(path) as fh:
        for line in fh:
            if line.startswith(">"):
                name = line[1:].split(None, 1)[0] if line[1:].strip() else ""
                seqs[name] = []
            elif name is not None:
                seqs[name].append(line.strip())
    return {k: "".join(v) for k, v in seqs.items()}


def run_variant_job(job_id: str) -> str:
    return run_job(job_id, _body)
