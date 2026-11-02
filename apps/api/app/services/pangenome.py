"""Pangenome of a comparison set: Panaroo (validated) or PPanGGOLiN (adapter, not validated) on the genomes' own
annotations (each genome's latest Bakta or Prokka annotation, as GFF3 with the sequence), then ARVA's own summaries of
the presence/absence matrix (arva_core.pangenome): categories with the thresholds chosen, accumulation curves, the
family-frequency distribution, a genome ordering for heatmaps, and, on request, per-group statistics and
exploratory associations with a metadata field.

Families are as good as the annotations: genomes annotated with different annotators, versions or databases call
genes differently, and those differences appear as accessory families. The plan warns when the annotations differ.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from arva_core import pangenome as core
from arva_tools.pangenome import (
    PanarooAdapter,
    PanarooParams,
    PpanggolinAdapter,
    PpanggolinParams,
    missing_flags,
    mode_settings,
    read_gene_data_row,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation, Assembly, ComparisonResult, ComparisonSet, MlstResult, Sample
from app.services import annotation as annotation_svc
from app.services.comparative import InputError, _problems, _tool, genome_records
from app.services.performance import effective_resources
from app.storage import get_storage

PANGENOME_JOB = "pangenome"
METHODS = {"panaroo": {"tool": "panaroo"}, "ppanggolin": {"tool": "ppanggolin"}}
MIN_GENOMES = 3
FEW_GENOMES = 10
ANNOTATORS = ("Bakta", "Prokka")
DATA_FILE = "pangenome.json"
MEMBERS_FILE = "members.jsonl"
ALIGNMENTS_MANIFEST = "alignments.sha256"
MAX_FAMILY_SEQUENCES = 500
METADATA_FIELDS = ("sample_type", "host", "geographic_origin", "organism", "collection_year", "mlst")
CATEGORY_NOTE = ("Core, soft core, shell and cloud are fractions of the genomes holding a family, with the thresholds "
                 "shown (ARVA's defaults are Panaroo's summary thresholds, 99 / 95 / 15 %). With few genomes they are "
                 "coarse, and every family's category depends on which genomes were chosen.")
ANNOTATION_NOTE = ("Gene families come from the genomes' annotations: missing, split or extra gene calls appear as "
                   "accessory families. Annotate every genome with the same annotator, version and database.")
CLUSTER_NOTE = ("The heatmap order of genomes is average-linkage clustering of shared gene content (Jaccard): "
                "similarity of gene repertoires, not a phylogeny.")
ASSOCIATION_NOTE = ("Associations are exploratory: genomes are not independent (related genomes share families by "
                    "descent), no correction for population structure is made, and an association is not a cause. "
                    "Confirm with lineage-aware methods and more genomes.")


def _latest_annotation(db: Session, assembly_id: str) -> Annotation | None:
    return db.scalar(select(Annotation).where(Annotation.assembly_id == assembly_id)
                     .order_by(Annotation.created_at.desc()).limit(1))


def annotation_record(a: Annotation | None) -> dict[str, Any] | None:
    if a is None:
        return None
    gff = (a.files or {}).get("gff3") or {}
    path = get_storage().resolve(gff["path"]) if gff.get("path") else None
    return {"annotation_id": a.id, "tool": a.tool, "tool_version": a.tool_version,
            "database_version": a.database_version, "gff3_sha256": gff.get("sha256"),
            "gff3_present": bool(path and path.is_file()), "cds_searched": annotation_svc.cds_searched(a)}


def annotation_consistency(genomes: list[dict[str, Any]]) -> dict[str, Any]:
    """The distinct (annotator, version, database) combinations among annotated genomes."""
    groups: dict[str, list[str]] = {}
    for g in genomes:
        a = g.get("annotation")
        if a:
            key = f"{a['tool']} {a['tool_version']}" + (f" (database {a['database_version']})"
                                                        if a.get("database_version") else "")
            groups.setdefault(key, []).append(g["label"])
    return {"consistent": len(groups) <= 1, "annotators": [{"annotator": k, "genomes": v} for k, v in groups.items()]}


def _check(name: str, lo: float, hi: float, value: float) -> None:
    if not lo <= value <= hi:
        raise InputError(f"{name} must be between {lo:g} and {hi:g}", "pangenome_setting_range", setting=name,
                         min=lo, max=hi)


def plan(db: Session, cset: ComparisonSet, method: str, genome_ids: list[str] | None, panaroo: dict[str, Any],
         ppanggolin: dict[str, Any], categories: dict[str, float], curves: dict[str, int],
         threads: int | None) -> dict[str, Any]:
    if method not in METHODS:
        raise InputError(f"Unknown pangenome method {method}", "comparison_method_unknown", method=method)
    try:
        core.validate_thresholds(categories)
    except ValueError as exc:
        raise InputError(str(exc), "pangenome_thresholds_invalid") from exc
    _check("curves.permutations", 10, 1000, curves["permutations"])
    _check("curves.seed", 1, 2_147_483_647, curves["seed"])
    genomes = genome_records(db, cset, genome_ids)
    if len(genomes) < MIN_GENOMES:
        raise InputError(f"A pangenome needs at least {MIN_GENOMES} genomes", "pangenome_size", min=MIN_GENOMES)
    for g in genomes:
        g["annotation"] = annotation_record(_latest_annotation(db, g["assembly_id"]))
    n_threads = effective_resources(db).cap_threads(threads)
    tool = _tool(db, METHODS[method]["tool"])
    problems = _problems(tool)
    try:
        if method == "panaroo":
            params = PanarooParams(**panaroo, threads=n_threads)
            params.validate()
            tool_settings = {**params.as_dict(), "mode_dependent": mode_settings(params.clean_mode, len(genomes))}
        else:
            params = PpanggolinParams(**ppanggolin, threads=n_threads)
            params.validate()
            tool_settings = params.as_dict()
    except (TypeError, ValueError) as exc:
        raise InputError(str(exc), "comparison_settings_invalid", detail=str(exc)) from exc
    if tool["status"] == "available":
        adapter = PanarooAdapter if method == "panaroo" else PpanggolinAdapter
        try:
            missing = missing_flags(method, adapter.help_text(tool["path"]))
        except (OSError, RuntimeError) as exc:
            missing = [str(exc)]
        if missing:
            problems.append({"code": "tool_options_missing", "params": {"tool": tool["name"],
                                                                        "options": ", ".join(missing)},
                             "message": f"{tool['name']} does not offer {', '.join(missing)}"})
    for code, test in (("pangenome_annotation_missing", lambda a: a is None),
                       ("pangenome_annotator_unsupported", lambda a: a is not None and a["tool"] not in ANNOTATORS),
                       ("pangenome_gff_missing", lambda a: a is not None and not a["gff3_present"]),
                       ("pangenome_cds_missing", lambda a: a is not None and a["gff3_present"]
                        and not a["cds_searched"])):
        if labels := [g["label"] for g in genomes if test(g["annotation"])]:
            problems.append({"code": code, "params": {"genomes": ", ".join(labels)},
                             "message": f"{code.replace('_', ' ')}: {', '.join(labels)}"})
    consistency = annotation_consistency(genomes)
    settings = {"method": method, "tool": tool_settings, "categories": dict(categories), "curves": dict(curves),
                "threads": n_threads}
    notes = [ANNOTATION_NOTE, CATEGORY_NOTE, CLUSTER_NOTE]
    return {"analysis": "pangenome", "method": method, "tool": tool, "settings": settings, "genomes": genomes,
            "annotation_consistency": consistency, "problems": problems, "notes": notes}


# --- Results ------------------------------------------------------------------------------------------------------

def _entry_path(r: ComparisonResult, name: str) -> Path | None:
    entry = (r.files or {}).get(name)
    if entry is None:
        return None
    path = get_storage().resolve(entry["path"])
    return path if path.is_file() else None


def data(r: ComparisonResult) -> dict[str, Any] | None:
    path = _entry_path(r, DATA_FILE) if r.analysis == "pangenome" else None
    return json.loads(path.read_text()) if path else None


def _members(r: ComparisonResult, index: int) -> dict[str, Any]:
    d = data(r)
    path = _entry_path(r, MEMBERS_FILE)
    if d is None or path is None:
        raise FileNotFoundError("The pangenome files of this result are missing on disk")
    offsets = d["member_offsets"]
    if not 0 <= index < len(offsets):
        raise LookupError(f"No family {index}")
    with path.open("rb") as fh:
        fh.seek(offsets[index])
        return json.loads(fh.readline())


def alignment_path(r: ComparisonResult, family: str) -> Path | None:
    """Panaroo's alignment of a family (aligned_gene_sequences/<family>.aln.fas, listed with its SHA-256 in the
    result's alignments.sha256); Panaroo's family names hold only letters, digits, '_' and '~'."""
    base = _entry_path(r, DATA_FILE)
    if base is None or _entry_path(r, ALIGNMENTS_MANIFEST) is None or not re.fullmatch(r"[A-Za-z0-9_~.-]+", family) \
            or family.startswith("."):
        return None
    path = base.parent / "panaroo" / "aligned_gene_sequences" / f"{family}.aln.fas"
    return path if path.is_file() else None


def _read_alignment(path: Path) -> list[tuple[str, str]]:
    records, name, seq = [], None, []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(seq)))
            name, seq = line[1:].strip(), []
        elif line.strip():
            seq.append(line.strip())
    if name is not None:
        records.append((name, "".join(seq)))
    return records


def family_detail(r: ComparisonResult, index: int) -> dict[str, Any]:
    """One family: its members (genome, gene ID, flags, location, ARVA annotation feature, lengths, sequences from
    the tool's gene_data.csv), its neighbouring families and, when the tool aligned it, the alignment."""
    d = data(r) or {}
    fam = d["families"][index]
    entry = _members(r, index)
    labels = [g["label"] for g in d["genomes"]]
    gene_data = _entry_path(r, "panaroo/gene_data.csv")
    members = []
    by_clustering: dict[str, dict[str, Any]] = {}
    for m in entry["members"][:MAX_FAMILY_SEQUENCES]:
        row = read_gene_data_row(gene_data, m["data"]) if gene_data and m.get("data") is not None else None
        dna, protein = (row or {}).get("dna_sequence") or "", (row or {}).get("prot_sequence") or ""
        item = {"genome": labels[m["g"]], "genome_index": m["g"], "gene_id": m["id"], "flags": m.get("flags") or [],
                "feature": m.get("feature"), "refound": m.get("refound"), "contig": (row or {}).get("scaffold_name"),
                "dna_length": len(dna) or None, "protein_length": len(protein.rstrip("*")) or None,
                "dna": dna or None, "protein": protein or None, "fragment": m.get("fragment", False)}
        if row:
            by_clustering[f"{d['genomes'][m['g']]['tool_name']};{row['clustering_id']}"] = item
        members.append(item)
    alignment = None
    if (aln := alignment_path(r, fam["name"])) is not None:
        records = _read_alignment(aln)
        alignment = {"file": f"panaroo/aligned_gene_sequences/{fam['name']}.aln.fas", "columns":
                     len(records[0][1]) if records else 0,
                     "rows": [{"name": n, "genome": (by_clustering.get(n) or {}).get("genome"),
                               "gene_id": (by_clustering.get(n) or {}).get("gene_id"), "sequence": s}
                              for n, s in records]}
    neighbours = [{"index": nb["family"], "name": d["families"][nb["family"]]["name"],
                   "annotation": d["families"][nb["family"]]["annotation"], "genomes": nb["genomes"]}
                  for nb in entry.get("neighbours") or []]
    return {"index": index, **fam, "members": members, "members_total": len(entry["members"]),
            "alignment": alignment, "neighbours": neighbours, "method": r.method}


def family_fasta(r: ComparisonResult, index: int, molecule: str) -> str:
    detail = family_detail(r, index)
    key = "dna" if molecule == "nucleotide" else "protein"
    out = []
    for m in detail["members"]:
        if m[key]:
            seq = m[key].rstrip("*") if key == "protein" else m[key]
            name = re.sub(r"\s+", "_", f"{m['genome']}|{m['gene_id']}")
            out.append(f">{name} family={detail['name']}\n" + "\n".join(seq[i:i + 60]
                                                                          for i in range(0, len(seq), 60)) + "\n")
    if not out:
        raise LookupError(f"The tool's files hold no {molecule} sequence for this family")
    return "".join(out)


def _csv(rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def families_csv(r: ComparisonResult) -> str:
    d = data(r) or {"families": [], "genomes": []}
    labels = [g["label"] for g in d["genomes"]]
    t = r.summary.get("thresholds") or {}
    rows: list[list[Any]] = [["family", "gene_names", "annotation", "genomes", "category", "tool_partition",
                              *labels, "thresholds", "method", "tool_version"]]
    th = f"core>={t.get('core')};soft_core>={t.get('soft_core')};shell>={t.get('shell')}"
    for f in d["families"]:
        rows.append([f["name"], ";".join(f["gene_names"]), f["annotation"], f["count"], f["category"],
                     f.get("partition"), *[int(c) for c in f["presence"]], th, r.method, r.tool_version])
    return _csv(rows)


def presence_rtab(r: ComparisonResult) -> str:
    """The presence/absence matrix with the genomes' labels as column names (Rtab layout)."""
    d = data(r) or {"families": [], "genomes": []}
    head = "\t".join(["Gene", *[re.sub(r"\s+", " ", g["label"]) for g in d["genomes"]]])
    return head + "\n" + "".join("\t".join([f["name"], *f["presence"]]) + "\n" for f in d["families"])


# --- Metadata, groups and associations ------------------------------------------------------------------------------

def _mlst(db: Session, assembly_id: str) -> str | None:
    m = db.scalar(select(MlstResult).where(MlstResult.assembly_id == assembly_id)
                  .order_by(MlstResult.created_at.desc()).limit(1))
    if m is None or not m.st or not m.scheme:
        return None
    return f"{m.scheme} ST{m.st}"


def metadata(db: Session, r: ComparisonResult) -> dict[str, Any]:
    """Per field, each genome's current value (None when not recorded): the sample's metadata, its custom fields and
    the assembly's latest MLST type."""
    values: dict[str, list[str | None]] = {f: [] for f in METADATA_FIELDS}
    custom: dict[str, list[str | None]] = {}
    n = len(r.genomes)
    for i, g in enumerate(r.genomes):
        sample = db.get(Sample, g.get("sample_id")) if g.get("sample_id") else None
        for f in METADATA_FIELDS:
            if f == "mlst":
                v = _mlst(db, g["assembly_id"]) if db.get(Assembly, g["assembly_id"]) else None
            elif f == "collection_year":
                v = str(sample.collection_date.year) if sample and sample.collection_date else None
            else:
                v = getattr(sample, f, None) if sample else None
            values[f].append(str(v).strip() or None if v is not None else None)
        for k, v in ((sample.custom_metadata or {}) if sample else {}).items():
            col = custom.setdefault(str(k), [None] * n)
            col[i] = str(v).strip() or None if v is not None else None
    fields = [{"key": f, "custom": False, "values": v} for f, v in values.items()]
    fields += [{"key": f"custom:{k}", "custom": True, "values": v} for k, v in sorted(custom.items())]
    for f in fields:
        present = [v for v in f["values"] if v is not None]
        f["recorded"] = len(present)
        f["distinct"] = len(set(present))
    return {"genomes": [g["label"] for g in r.genomes], "fields": fields}


def associations(db: Session, r: ComparisonResult, field: str, min_group: int, limit: int) -> dict[str, Any]:
    d = data(r)
    if d is None:
        raise FileNotFoundError("The pangenome files of this result are missing on disk")
    meta = metadata(db, r)
    f = next((x for x in meta["fields"] if x["key"] == field), None)
    if f is None:
        raise InputError(f"No metadata field {field}", "pangenome_field_unknown", field=field)
    if not 1 <= min_group <= 100:
        raise InputError("min_group must be between 1 and 100", "pangenome_setting_range", setting="min_group",
                         min=1, max=100)
    presence = [[int(c) for c in fam["presence"]] for fam in d["families"]]
    names = [fam["name"] for fam in d["families"]]
    groups = core.group_statistics(presence, f["values"])
    assoc = core.associations(presence, names, f["values"], min_group)
    rows = assoc.pop("rows")
    return {"field": field, "values": dict(zip(meta["genomes"], f["values"], strict=True)), "groups": groups,
            **assoc, "rows": rows[:limit], "rows_total": len(rows), "note": ASSOCIATION_NOTE,
            "small_sample": assoc["genomes_with_value"] < FEW_GENOMES}
