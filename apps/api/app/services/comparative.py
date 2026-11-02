"""Comparative genomics: comparison sets (named selections of assemblies from any project), the plans of their ANI
and whole-genome alignment jobs, and the views and exports of their results.

Methods, and what ARVA passes to each (every result-changing option explicitly; confirmed against each tool's usage
text, see the adapters):

* ANI: skani triangle (-E sparse rows, -c 125, -m 1000, -s 80, --min-af 15) or FastANI all-vs-all (--ql/--rl, -k 16,
  --fragLen 3000, --minFraction 0.2, --maxRatioDiff 10.0).
* Alignment: minimap2 -x asm5 / asm10 / asm20 -c (by expected divergence: ~0.1 / 1 / 5 %, minimap2's usage text) or
  NUCmer (--mumreference -b 200 -c 65 -g 90 -l 20) with show-coords -rclTH; dnadiff (NUCmer --maxmatch inside) for
  each genome against the reference, for its report and its structural differences (show-diff).

The reference of an alignment is the first genome of the chosen order; every other genome is aligned to it (dot
plots, conservation, dnadiff) and each genome to the next one (synteny links between neighbours).
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from arva_tools.base import help_options
from arva_tools.fastani import ALL_FLAGS as FASTANI_FLAGS
from arva_tools.fastani import FastaniAdapter, FastaniParams
from arva_tools.fastani import help_options as fastani_help_options
from arva_tools.mapping import ASSEMBLY_PRESETS
from arva_tools.nucmer import NucmerAdapter, NucmerParams, missing_help_flags, show_coords_path
from arva_tools.registry import detect
from arva_tools.skani import TRIANGLE_FLAGS, SkaniAdapter, SkaniParams
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    ComparisonMember,
    ComparisonResult,
    ComparisonSet,
    JobStatus,
    Project,
    Sample,
)
from app.services.annotation import assembly_record, contig_headers, synthetic_evidence
from app.services.performance import effective_resources
from app.storage import get_storage

ANI_JOB = "comparative_ani"
ALIGNMENT_JOB = "comparative_alignment"
JOBS = (ANI_JOB, ALIGNMENT_JOB, "region_explorer", "gene_investigation", "pangenome", "phylogeny")
MIN_GENOMES = 2
MAX_SET_GENOMES = 200
# ARVA's limit for one alignment job: N - 1 alignments to the reference plus N - 2 between neighbours (and N - 1
# dnadiff runs), all drawn in one interactive view.
MAX_ALIGNMENT_GENOMES = 12
ANI_METHODS = {"skani": {"tool": "skani", "params": SkaniParams}, "fastani": {"tool": "fastani",
                                                                            "params": FastaniParams}}
ALIGNERS = {"minimap2": {"tool": "minimap2"}, "nucmer": {"tool": "nucmer"}}
PRESET_DIVERGENCE = {"asm5": "~0.1 %", "asm10": "~1 %", "asm20": "~5 %"}
SIMILARITY_NOTE = ("The heatmap order is average-linkage (UPGMA) clustering of 100 - ANI: similarity clustering to "
                   "place similar genomes together, not a phylogeny.")


class InputError(ValueError):
    """The request cannot be done as asked (HTTP 400); `code` and `params` name it for the interface."""

    def __init__(self, message: str, code: str, **params: Any):
        super().__init__(message)
        self.code = code
        self.params = params


def _assembly_row(db: Session, a: Assembly) -> dict[str, Any]:
    sample = db.get(Sample, a.sample_id)
    project = db.get(Project, sample.project_id) if sample else None
    return {"assembly_id": a.id, "sample_id": a.sample_id, "sample_code": sample.sample_code if sample else None,
            "project_id": project.id if project else None, "project_name": project.name if project else None,
            "kind": a.kind.value, "assembler": a.assembler, "assembler_version": a.assembler_version,
            "parent_assembly_id": a.parent_assembly_id, "total_length": a.stats.get("total_length"),
            "contigs": a.stats.get("contig_count", a.stats.get("contigs")), "created_at": a.created_at,
            "annotation_id": db.scalar(select(Annotation.id).where(Annotation.assembly_id == a.id)
                                       .order_by(Annotation.created_at.desc()).limit(1))}


def default_label(db: Session, a: Assembly) -> str:
    sample = db.get(Sample, a.sample_id)
    code = sample.sample_code if sample else a.id[:8]
    return f"{code} ({a.assembler}{', polished' if a.kind.value == 'polished' else ''})"[:100]


def candidates(db: Session) -> list[dict[str, Any]]:
    """Every assembly ARVA holds, with its sample and project, newest first."""
    rows = db.scalars(select(Assembly).order_by(Assembly.created_at.desc())).all()
    return [_assembly_row(db, a) for a in rows]


def _members(db: Session, assembly_ids: list[str], labels: dict[str, str]) -> list[tuple[Assembly, str]]:
    if len(set(assembly_ids)) != len(assembly_ids):
        raise InputError("An assembly is listed twice", "comparison_duplicate")
    if not MIN_GENOMES <= len(assembly_ids) <= MAX_SET_GENOMES:
        raise InputError(f"A comparison set holds {MIN_GENOMES} to {MAX_SET_GENOMES} assemblies",
                         "comparison_size", min=MIN_GENOMES, max=MAX_SET_GENOMES)
    out = []
    for aid in assembly_ids:
        a = db.get(Assembly, aid)
        if a is None:
            raise InputError(f"Assembly {aid} does not exist", "comparison_assembly_missing", assembly=aid)
        label = (labels.get(aid) or "").strip() or default_label(db, a)
        out.append((a, label[:100]))
    if len({label for _a, label in out}) != len(out):
        raise InputError("Two assemblies have the same label; labels name the genomes in plots and tables",
                         "comparison_label_duplicate")
    return out


def save_set(db: Session, cset: ComparisonSet | None, project: Project, name: str, description: str | None,
             assembly_ids: list[str], labels: dict[str, str]) -> ComparisonSet:
    name = name.strip()
    if not name:
        raise InputError("The set needs a name", "comparison_name_missing")
    members = _members(db, assembly_ids, labels)
    if cset is None:
        cset = ComparisonSet(project_id=project.id, name=name, description=description)
        db.add(cset)
    else:
        cset.project_id, cset.name, cset.description = project.id, name, description
        cset.members.clear()
        db.flush()
    for pos, (a, label) in enumerate(members):
        cset.members.append(ComparisonMember(assembly_id=a.id, position=pos, label=label))
    db.commit()
    db.refresh(cset)
    return cset


def _active_jobs(db: Session, cset: ComparisonSet) -> list[AnalysisJob]:
    jobs = db.scalars(select(AnalysisJob).where(
        AnalysisJob.project_id == cset.project_id, AnalysisJob.sample_id.is_(None),
        AnalysisJob.job_type.in_(JOBS)).order_by(AnalysisJob.created_at.desc())).all()
    return [j for j in jobs if (j.parameters or {}).get("set_id") == cset.id]


def result_brief(r: ComparisonResult) -> dict[str, Any]:
    return {"id": r.id, "job_id": r.job_id, "analysis": r.analysis, "method": r.method, "tool": r.tool,
            "tool_version": r.tool_version, "genomes": [g["label"] for g in r.genomes],
            "warnings": r.warnings, "created_at": r.created_at}


def set_view(db: Session, cset: ComparisonSet) -> dict[str, Any]:
    project = db.get(Project, cset.project_id)
    members = []
    for m in cset.members:
        a = db.get(Assembly, m.assembly_id)
        row = _assembly_row(db, a)
        row["contigs_present"] = get_storage().resolve(a.contigs_path).is_file()
        members.append({**row, "label": m.label, "position": m.position})
    results = db.scalars(select(ComparisonResult).where(ComparisonResult.set_id == cset.id)
                         .order_by(ComparisonResult.created_at.desc())).all()
    jobs = _active_jobs(db, cset)
    return {"id": cset.id, "project_id": cset.project_id, "project_name": project.name if project else None,
            "name": cset.name, "description": cset.description, "created_at": cset.created_at,
            "updated_at": cset.updated_at, "members": members, "results": [result_brief(r) for r in results],
            "jobs": [{"id": j.id, "job_type": j.job_type, "status": j.status.value, "tool_name": j.tool_name,
                      "created_at": j.created_at, "error_message": j.error_message, "error_detail": j.error_detail}
                     for j in jobs if j.status is not JobStatus.completed]}


def list_sets(db: Session, project_id: str | None = None) -> list[dict[str, Any]]:
    q = select(ComparisonSet).order_by(ComparisonSet.updated_at.desc())
    if project_id:
        q = q.where(ComparisonSet.project_id == project_id)
    out = []
    for s in db.scalars(q).all():
        project = db.get(Project, s.project_id)
        n = db.scalar(select(ComparisonResult.id).where(ComparisonResult.set_id == s.id).limit(1))
        out.append({"id": s.id, "name": s.name, "description": s.description, "project_id": s.project_id,
                    "project_name": project.name if project else None, "genomes": len(s.members),
                    "labels": [m.label for m in s.members], "has_results": n is not None,
                    "updated_at": s.updated_at})
    return out


# --- Plans --------------------------------------------------------------------------------------------------------

def _tool(db: Session, tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=True)
    res = effective_resources(db)
    return {"id": tool_id, "name": d.info.name, "status": d.status.value, "version": d.version,
            "version_validated": d.version_validated, "message": d.message, "reason": d.reason,
            "reason_params": d.reason_params, "path": d.path, "license": d.info.license,
            "citation": d.info.citation, "citation_url": d.info.citation_url, "install": d.info.install,
            "max_threads": res.max_threads, "default_threads": res.threads}


def genome_records(db: Session, cset: ComparisonSet, order: list[str] | None = None) -> list[dict[str, Any]]:
    """The set's genomes (in `order` when given: a permutation of a subset of the members) as a job records them."""
    members = {m.assembly_id: m for m in cset.members}
    ids = order if order is not None else [m.assembly_id for m in cset.members]
    if order is not None:
        if len(set(order)) != len(order) or not set(order) <= set(members):
            raise InputError("The order must list members of the set, each once", "comparison_order_invalid")
        if len(order) < MIN_GENOMES:
            raise InputError(f"Choose at least {MIN_GENOMES} genomes", "comparison_size", min=MIN_GENOMES,
                             max=MAX_SET_GENOMES)
    out = []
    for aid in ids:
        a = db.get(Assembly, aid)
        path = get_storage().resolve(a.contigs_path)
        if not path.is_file():
            raise InputError(f"The contigs file of {members[aid].label} is missing on disk",
                             "comparison_contigs_missing", label=members[aid].label)
        sample = db.get(Sample, a.sample_id)
        out.append({**assembly_record(a), "label": members[aid].label, "sample_id": a.sample_id,
                    "sample_code": sample.sample_code if sample else None,
                    "project_id": sample.project_id if sample else None,
                    "total_length": a.stats.get("total_length"),
                    "synthetic_evidence": synthetic_evidence(db, a, contig_headers(path))})
    return out


def _problems(tool: dict[str, Any]) -> list[dict[str, Any]]:
    if tool["status"] != "available":
        return [{"code": "tool_missing", "params": {"tool": tool["name"]},
                 "message": f"{tool['name']} is not available here ({tool['status']}): {tool['message']}"}]
    return []


def ani_plan(db: Session, cset: ComparisonSet, method: str, threads: int | None) -> dict[str, Any]:
    if method not in ANI_METHODS:
        raise InputError(f"Unknown ANI method {method}", "comparison_method_unknown", method=method)
    tool = _tool(db, ANI_METHODS[method]["tool"])
    res = effective_resources(db)
    params = ANI_METHODS[method]["params"](threads=res.cap_threads(threads))
    params.validate()
    genomes = genome_records(db, cset)
    problems = _problems(tool)
    if tool["status"] == "available":
        try:
            if method == "skani":
                opts = help_options(SkaniAdapter.triangle_help_text(tool["path"]))
                missing = [f for f in TRIANGLE_FLAGS if f not in opts]
            else:
                opts = fastani_help_options(FastaniAdapter.help_text(tool["path"]))
                missing = [f for f in FASTANI_FLAGS if f not in opts]
        except (OSError, RuntimeError) as exc:
            missing = [str(exc)]
        if missing:
            problems.append({"code": "tool_options_missing", "params": {"tool": tool["name"],
                                                                        "options": ", ".join(missing)},
                             "message": f"{tool['name']} does not offer {', '.join(missing)}"})
    n = len(genomes)
    return {"analysis": "ani", "method": method, "tool": tool, "settings": params.as_dict(), "genomes": genomes,
            "comparisons": n * (n - 1) // 2 if method == "skani" else n * n, "problems": problems,
            "notes": [SIMILARITY_NOTE]}


def alignment_pairs(n: int) -> list[tuple[int, int, str]]:
    """(reference index, query index, role) over genomes 0..n-1 in the chosen order: every genome against the first
    ("reference"), then each genome against the next one ("neighbour") unless that pair is already listed."""
    pairs = [(0, j, "reference") for j in range(1, n)]
    pairs += [(i, i + 1, "neighbour") for i in range(1, n - 1)]
    return pairs


def alignment_plan(db: Session, cset: ComparisonSet, aligner: str, preset: str, nucmer: dict[str, Any],
                   order: list[str] | None, dnadiff: bool, threads: int | None) -> dict[str, Any]:
    if aligner not in ALIGNERS:
        raise InputError(f"Unknown aligner {aligner}", "comparison_method_unknown", method=aligner)
    genomes = genome_records(db, cset, order)
    if len(genomes) > MAX_ALIGNMENT_GENOMES:
        raise InputError(f"An alignment compares at most {MAX_ALIGNMENT_GENOMES} genomes; choose them and their "
                         "order", "comparison_alignment_size", max=MAX_ALIGNMENT_GENOMES)
    tool = _tool(db, ALIGNERS[aligner]["tool"])
    res = effective_resources(db)
    settings: dict[str, Any] = {"threads": res.cap_threads(threads)}
    if aligner == "minimap2":
        if preset not in ASSEMBLY_PRESETS:
            raise InputError(f"preset must be one of {', '.join(ASSEMBLY_PRESETS)}", "comparison_preset_invalid")
        settings["preset"] = preset
    else:
        params = NucmerParams(**nucmer)
        try:
            params.validate()
        except ValueError as exc:
            raise InputError(str(exc), "comparison_settings_invalid", detail=str(exc)) from exc
        settings["nucmer"] = params.as_dict()
    problems = _problems(tool)
    if aligner == "nucmer" and tool["status"] == "available":
        try:
            text = NucmerAdapter.help_text(tool["path"])
            if missing := missing_help_flags(text):
                problems.append({"code": "tool_options_missing", "params": {"tool": tool["name"],
                                                                            "options": ", ".join(missing)},
                                 "message": f"{tool['name']} does not offer {', '.join(missing)}"})
        except (OSError, RuntimeError) as exc:
            problems.append({"code": "tool_options_missing", "params": {"tool": tool["name"], "options": str(exc)},
                             "message": str(exc)})
        if not show_coords_path(tool["path"]):
            problems.append({"code": "tool_missing", "params": {"tool": "show-coords"},
                             "message": "show-coords (MUMmer) is not installed next to nucmer"})
    dd = _tool(db, "dnadiff") if dnadiff else None
    if dd is not None:
        problems += _problems(dd)
    pairs = alignment_pairs(len(genomes))
    return {"analysis": "alignment", "method": aligner, "tool": tool, "dnadiff_tool": dd, "settings": settings,
            "dnadiff": dnadiff, "genomes": genomes, "reference": genomes[0]["label"],
            "pairs": [{"reference": genomes[i]["label"], "query": genomes[j]["label"], "role": role}
                      for i, j, role in pairs],
            "preset_divergence": PRESET_DIVERGENCE, "problems": problems}


# --- Results ------------------------------------------------------------------------------------------------------

def alignment_data(r: ComparisonResult) -> dict[str, Any] | None:
    entry = (r.files or {}).get("alignment.json")
    if r.analysis != "alignment" or entry is None:
        return None
    path = get_storage().resolve(entry["path"])
    return json.loads(path.read_text()) if path.is_file() else None


def result_data(r: ComparisonResult) -> dict[str, Any] | None:
    """The drawing data a Region Explorer or gene investigation result keeps in its results folder."""
    entry = (r.files or {}).get(f"{r.analysis}.json") if r.analysis in ("region", "gene") else None
    if entry is None:
        return None
    path = get_storage().resolve(entry["path"])
    return json.loads(path.read_text()) if path.is_file() else None


def result_view(r: ComparisonResult, db: Session | None = None) -> dict[str, Any]:
    out = {**result_brief(r), "set_id": r.set_id, "parameters": r.parameters, "genomes": r.genomes,
           "summary": r.summary, "files": r.files}
    if r.analysis == "alignment":
        data = alignment_data(r)
        out["alignment"] = data
        out["alignment_missing"] = data is None
    elif r.analysis in ("region", "gene"):
        data = result_data(r)
        out["data"] = data
        out["data_missing"] = data is None
    elif r.analysis == "phylogeny" and db is not None:
        from app.services.phylogeny import drawing

        data = drawing(db, r)
        out["data"] = data
        out["data_missing"] = data is None
    elif r.analysis == "pangenome":
        from app.services.pangenome import data as pangenome_data

        data = pangenome_data(r)
        if data is not None:
            data.pop("member_offsets", None)
        out["data"] = data
        out["data_missing"] = data is None
    return out


def _csv(rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def ani_csv(r: ComparisonResult) -> str:
    """One row per ordered pair: ANI of A against B and the share of A aligned, as the tool reported them (empty
    when it did not report the pair)."""
    labels = [g["label"] for g in r.genomes]
    m = r.summary["matrix"]
    rows: list[list[Any]] = [["genome_a", "genome_b", "ani_percent", "aligned_fraction_a", "method", "tool_version"]]
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if i != j or m["ani"][i][j] is not None:
                rows.append([a, b, m["ani"][i][j], m["af"][i][j], r.method, r.tool_version])
    return _csv(rows)


def blocks_csv(r: ComparisonResult) -> str:
    data = alignment_data(r) or {"pairs": [], "genomes": []}
    labels = [g["label"] for g in data["genomes"]]
    rows: list[list[Any]] = [["reference_genome", "reference_contig", "reference_start", "reference_end",
                              "query_genome", "query_contig", "query_start", "query_end", "strand",
                              "identity_percent", "alignment_length", "primary"]]
    for p in data["pairs"]:
        for b in p["blocks"]:
            rows.append([labels[p["reference"]], b[0], b[1], b[2], labels[p["query"]], b[3], b[4], b[5], b[6], b[7],
                         b[8], b[9]])
    return _csv(rows)


def differences_csv(r: ComparisonResult) -> str:
    """dnadiff's structural differences of each genome against the reference, on both sides, as show-diff reports
    them (positions on the genome named in `located_on`)."""
    rows: list[list[Any]] = [["reference_genome", "query_genome", "located_on", "sequence", "type", "category",
                              "start", "end", "length", "inserted_bases"]]
    for d in r.summary.get("dnadiff") or []:
        for side, key in (("reference", "reference_differences"), ("query", "query_differences")):
            on = d["reference"] if side == "reference" else d["query"]
            for x in d.get(key) or []:
                rows.append([d["reference"], d["query"], on, x["sequence"], x["type"], x["category"], x["start"],
                             x["end"], x["length"], x["inserted"]])
    return _csv(rows)


def conservation_csv(r: ComparisonResult) -> str:
    data = alignment_data(r) or {"conservation": {"genomes": []}}
    rows: list[list[Any]] = [["reference_genome", "query_genome", "reference_contig", "window_start", "window_end",
                              "covered_fraction", "mean_best_identity_percent"]]
    cons = data["conservation"]
    for g in cons["genomes"]:
        for w in g["windows"]:
            rows.append([cons["reference"], g["label"], w["contig"], w["start"], w["end"], w["covered"],
                         w["identity"]])
    return _csv(rows)


def project_results(db: Session, project_id: str) -> list[tuple[ComparisonSet, list[ComparisonResult]]]:
    sets = db.scalars(select(ComparisonSet).where(ComparisonSet.project_id == project_id)
                      .order_by(ComparisonSet.created_at)).all()
    return [(s, db.scalars(select(ComparisonResult).where(ComparisonResult.set_id == s.id)
                           .order_by(ComparisonResult.created_at.desc())).all()) for s in sets]


def download_name(cset: ComparisonSet, r: ComparisonResult, name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in cset.name)[:60]
    return f"ARVA_{safe}_{r.analysis}_{r.method}_{name.replace('/', '_')}"
