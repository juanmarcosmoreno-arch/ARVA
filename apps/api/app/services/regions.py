"""Genome Region Explorer and Custom Gene Investigation on a comparison set.

Region Explorer: a gene (an annotated feature) or coordinates in one genome of the set, a window of `flank` bp on
each side, and other genomes of the set. In each other genome the homologous gene is found with BLAST+: blastp of the
gene's protein against that genome's annotated proteins when the gene is a CDS and the genome is annotated (protein
similarity finds the homologue through synonymous changes and does not depend on how the genome was split into
contigs), otherwise blastn of the gene's nucleotides against the genome's contigs. BLAST+ rather than DIAMOND:
the searches are one protein against a few thousand and a few hundred proteins all against all, where BLAST's full
sensitivity costs seconds; DIAMOND is built for millions of queries. minimap2 targets long near-identical sequences
and gives no reliable alignment for one divergent gene. The windows' proteins are grouped by all-against-all blastp
(arva_core.region.homology_groups) and neighbouring tracks are linked by blastn of their window sequences, the way
Easyfig draws comparisons.

Custom Gene Investigation: a query (a saved GeneQuery: pasted or uploaded FASTA, or a feature of an annotation)
searched in each chosen genome with blastn (nucleotide) or tblastn (protein, bacterial genetic code 11; tblastn
searches the contigs, so it finds copies the annotation missed, partial copies and copies split in pieces). Matches,
copies, split and partial matches follow arva_core.region.chain_matches with the thresholds given; nearby mobile
elements come from the genome's latest mobile-element runs (MOB-suite, IntegronFinder, ISEScan, geNomad,
PlasmidFinder). The matched sequences can be aligned with MAFFT and a gene tree built with IQ-TREE or FastTree.

Similarity, shared neighbourhoods and nearby mobile elements are observations. They do not show that a gene moved
between genomes (horizontal transfer); the interface and the reports say so.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any

from arva_core.formats import open_sequence_file
from arva_core.seqstats import iter_fasta
from arva_tools.blast import PROGRAMS, BlastAdapter, missing_flags, sibling
from arva_tools.mafft import STRATEGIES, MafftAdapter
from arva_tools.phylo import METHODS as TREE_METHODS
from arva_tools.phylo import FasttreeAdapter, IqtreeAdapter, TreeParams
from arva_tools.phylo import missing_flags as tree_missing_flags
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation, Assembly, ComparisonResult, ComparisonSet, GeneQuery
from app.services import annotation as annotation_svc
from app.services.comparative import InputError, _problems, _tool, genome_records, result_data
from app.services.performance import effective_resources
from app.storage import get_storage

REGION_JOB = "region_explorer"
GENE_JOB = "gene_investigation"
JOBS = (REGION_JOB, GENE_JOB)
MAX_REGION_GENOMES = 20
MAX_FLANK = 50_000
MOLECULES = ("nucleotide", "protein")
# ARVA's bounds on a query: long enough for BLAST statistics to mean something, short enough for one gene or operon.
QUERY_LENGTH = {"nucleotide": (30, 50_000), "protein": (10, 10_000)}
MAX_FASTA_BYTES = 200_000
NUCLEOTIDE = frozenset("ACGTUNRYKMSWBDHV")
PROTEIN = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO")
MAX_MOBILE_DISTANCE = 100_000
TRANSFER_NOTE = ("Similar sequence, a shared neighbourhood or a nearby mobile element in several genomes does not by "
                 "itself show horizontal transfer: common descent, convergent assembly artefacts and sampling explain "
                 "the same patterns. Testing transfer needs phylogenetic incongruence, dated comparisons or "
                 "experimental evidence.")
HEURISTIC_NOTE = ("Complete, partial and split matches, contig-edge flags, homology groups and links follow ARVA's "
                  "stated rules and thresholds (arva_core.region); they are not the tools' own calls.")


def _latest_annotation(db: Session, assembly_id: str) -> Annotation | None:
    return db.scalar(select(Annotation).where(Annotation.assembly_id == assembly_id)
                     .order_by(Annotation.created_at.desc()).limit(1))


def _annotation_record(a: Annotation | None) -> dict[str, Any] | None:
    if a is None:
        return None
    faa = (a.files or {}).get("faa")
    return {"annotation_id": a.id, "tool": a.tool, "tool_version": a.tool_version, "faa_sha256":
            faa.get("sha256") if faa else None, "cds_searched": annotation_svc.cds_searched(a)}


# --- Queries ------------------------------------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    name = " ".join(name.split())[:100]
    if not name:
        raise InputError("The query needs a name", "gene_query_name_missing")
    return name


def parse_query_fasta(text: str, molecule: str) -> tuple[str | None, str]:
    """One FASTA record (or a bare sequence) checked against the molecule's alphabet; returns (header, sequence)."""
    if molecule not in MOLECULES:
        raise InputError(f"molecule must be one of {', '.join(MOLECULES)}", "gene_query_molecule_invalid")
    if len(text.encode()) > MAX_FASTA_BYTES:
        raise InputError(f"The FASTA text is larger than {MAX_FASTA_BYTES:,} bytes", "gene_query_too_large",
                         max=MAX_FASTA_BYTES)
    header, seq_lines = None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None or seq_lines:
                raise InputError("Give one sequence per query (the FASTA holds several records)",
                                 "gene_query_several_records")
            header = line[1:].strip()[:200]
        elif line.startswith(";"):
            continue
        else:
            seq_lines.append(re.sub(r"\s+", "", line))
    seq = "".join(seq_lines).upper()
    if molecule == "protein" and seq.endswith("*"):
        seq = seq[:-1]
    if molecule == "nucleotide":
        seq = seq.replace("U", "T")
    lo, hi = QUERY_LENGTH[molecule]
    if not lo <= len(seq) <= hi:
        raise InputError(f"A {molecule} query has {lo:,} to {hi:,} residues; this one has {len(seq):,}",
                         "gene_query_length", molecule=molecule, min=lo, max=hi, length=len(seq))
    alphabet = NUCLEOTIDE if molecule == "nucleotide" else PROTEIN
    if bad := sorted(set(seq) - alphabet):
        raise InputError(f"Characters not allowed in a {molecule} sequence: {''.join(bad[:10])}",
                         "gene_query_characters", molecule=molecule, characters="".join(bad[:10]))
    if molecule == "protein" and sum(seq.count(c) for c in "ACGTN") / len(seq) > 0.9:
        raise InputError("This looks like a nucleotide sequence; choose nucleotide", "gene_query_looks_nucleotide")
    return header, seq


def query_view(q: GeneQuery, with_sequence: bool = False) -> dict[str, Any]:
    out = {"id": q.id, "name": q.name, "description": q.description, "molecule": q.molecule, "length": q.length,
           "sha256": q.sha256, "source": q.source, "created_at": q.created_at}
    if with_sequence:
        out["sequence"] = q.sequence
    return out


def save_query(db: Session, name: str, description: str | None, molecule: str, sequence: str,
               source: dict[str, Any]) -> GeneQuery:
    sha = hashlib.sha256(sequence.encode()).hexdigest()
    existing = db.scalar(select(GeneQuery).where(GeneQuery.molecule == molecule, GeneQuery.sha256 == sha))
    if existing is not None:
        return existing
    q = GeneQuery(name=_clean_name(name), description=description, molecule=molecule, sequence=sequence,
                  length=len(sequence), sha256=sha, source=source)
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def query_from_fasta(db: Session, name: str | None, description: str | None, molecule: str, fasta: str,
                     source_kind: str) -> GeneQuery:
    header, seq = parse_query_fasta(fasta, molecule)
    chosen = name or (header.split()[0] if header else "")
    return save_query(db, chosen, description, molecule, seq, {"kind": source_kind, "header": header})


def query_from_feature(db: Session, annotation_id: str, feature_id: int, molecule: str,
                       name: str | None) -> GeneQuery:
    a = db.get(Annotation, annotation_id)
    if a is None:
        raise InputError("The annotation does not exist", "gene_query_annotation_missing")
    try:
        f = annotation_svc.feature_detail(a, feature_id)
    except LookupError:
        raise InputError(f"No feature {feature_id} in this annotation", "gene_query_feature_missing") from None
    seq = f.get("protein" if molecule == "protein" else "nucleotide")
    if not seq or seq.get("truncated"):
        raise InputError(f"{a.tool}'s files hold no complete {molecule} sequence of this feature",
                         "gene_query_feature_sequence", molecule=molecule)
    _, clean = parse_query_fasta(seq["sequence"], molecule)
    assembly = db.get(Assembly, a.assembly_id)
    label = name or f.get("gene") or f.get("locus_tag") or f"feature {feature_id}"
    return save_query(db, label, f.get("product"), molecule, clean, {
        "kind": "annotation", "annotation_id": a.id, "feature_id": feature_id, "locus_tag": f.get("locus_tag"),
        "gene": f.get("gene"), "product": f.get("product"), "annotator": f"{a.tool} {a.tool_version}",
        "sample_id": assembly.sample_id if assembly else None, "contig": f.get("contig_in_assembly"),
        "start": f["start"], "end": f["end"], "strand": f["strand"]})


def list_queries(db: Session) -> list[dict[str, Any]]:
    return [query_view(q) for q in db.scalars(select(GeneQuery).order_by(GeneQuery.created_at.desc())).all()]


def gene_lookup(db: Session, cset: ComparisonSet, text: str, limit: int = 100) -> list[dict[str, Any]]:
    """Features of the set's genomes (each genome's latest annotation) whose gene name or locus tag is `text`
    (case-insensitive), or whose product contains it."""
    needle = text.strip().lower()
    if len(needle) < 2:
        raise InputError("Type at least two characters", "gene_lookup_short")
    out = []
    for m in cset.members:
        a = _latest_annotation(db, m.assembly_id)
        if a is None:
            continue
        names = annotation_svc.original_names(a)
        for f in annotation_svc.features_of(a):
            gene, tag, product = (f.get("gene") or "").lower(), (f.get("locus_tag") or "").lower(), \
                (f.get("product") or "").lower()
            exact = needle in (gene, tag)
            if exact or needle in product:
                out.append({"label": m.label, "assembly_id": m.assembly_id, "annotation_id": a.id,
                            "annotator": f"{a.tool} {a.tool_version}", "feature_id": f["id"], "type": f["type"],
                            "gene": f.get("gene"), "locus_tag": f.get("locus_tag"), "product": f.get("product"),
                            "contig": names.get(f["contig"], f["contig"]), "start": f["start"], "end": f["end"],
                            "strand": f["strand"], "length": f.get("length"), "exact": exact})
    out.sort(key=lambda x: (not x["exact"], x["label"], x["contig"], x["start"]))
    return out[:limit]


# --- Plans --------------------------------------------------------------------------------------------------------

def _blast_problems(tool: dict[str, Any], programs: tuple[str, ...]) -> list[dict[str, Any]]:
    problems = _problems(tool)
    if tool["status"] != "available":
        return problems
    for program in ("makeblastdb", *programs):
        exe = sibling(tool["path"], program)
        if exe is None:
            problems.append({"code": "tool_missing", "params": {"tool": program},
                             "message": f"{program} (BLAST+) is not installed next to blastn"})
            continue
        try:
            missing = missing_flags(program, BlastAdapter.help_text(exe))
        except (OSError, RuntimeError) as exc:
            missing = [str(exc)]
        if missing:
            problems.append({"code": "tool_options_missing", "params": {"tool": program, "options": ", ".join(missing)},
                             "message": f"{program} does not offer {', '.join(missing)}"})
    return problems


def _genomes(db: Session, cset: ComparisonSet, ids: list[str], focus: str | None, limit: int) -> list[dict[str, Any]]:
    if focus is not None:
        ids = [focus, *[i for i in ids if i != focus]]
    if len(ids) > limit:
        raise InputError(f"Choose at most {limit} genomes", "region_genomes_limit", max=limit)
    records = genome_records(db, cset, ids)
    for g in records:
        g["annotation"] = _annotation_record(_latest_annotation(db, g["assembly_id"]))
    return records


def _threads(db: Session, threads: int | None) -> int:
    return effective_resources(db).cap_threads(threads)


def _check_number(name: str, value: float, lo: float, hi: float) -> None:
    if not lo <= value <= hi:
        raise InputError(f"{name} must be between {lo:g} and {hi:g}", "region_setting_range", setting=name,
                         min=lo, max=hi)


def _anchor(db: Session, cset: ComparisonSet, anchor: dict[str, Any]) -> dict[str, Any]:
    members = {m.assembly_id for m in cset.members}
    if anchor.get("annotation_id"):
        a = db.get(Annotation, anchor["annotation_id"])
        if a is None or a.assembly_id not in members:
            raise InputError("The gene's annotation is not of a genome in this set", "region_anchor_not_in_set")
        f = next((x for x in annotation_svc.features_of(a) if x["id"] == anchor.get("feature_id")), None)
        if f is None:
            raise InputError("The gene is not in that annotation", "region_anchor_missing")
        if f.get("edge"):
            raise InputError("The gene crosses the origin of a circular sequence; choose coordinates instead",
                             "region_anchor_edge")
        names = annotation_svc.original_names(a)
        return {"kind": "feature", "assembly_id": a.assembly_id, "annotation_id": a.id, "feature_id": f["id"],
                "contig": names.get(f["contig"], f["contig"]), "annotation_contig": f["contig"],
                "start": f["start"], "end": f["end"], "strand": f["strand"] if f["strand"] in "+-" else "+",
                "type": f["type"], "gene": f.get("gene"), "locus_tag": f.get("locus_tag"),
                "product": f.get("product"), "protein": f["type"] in ("cds", "sorf")}
    aid = anchor.get("assembly_id")
    if aid not in members:
        raise InputError("Choose a genome of this set for the coordinates", "region_anchor_not_in_set")
    a = db.get(Assembly, aid)
    path = get_storage().resolve(a.contigs_path)
    lengths = {}
    with open_sequence_file(path) as fh:
        for header, seq, _q, _l in iter_fasta(fh):
            lengths[header[1:].decode("utf-8", "replace").split(maxsplit=1)[0]] = len(seq)
    contig, start, end = anchor.get("contig"), anchor.get("start"), anchor.get("end")
    if contig not in lengths:
        raise InputError(f"The genome has no sequence {contig}", "region_anchor_contig", contig=str(contig))
    if not (isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= lengths[contig]):
        raise InputError(f"Coordinates must lie within 1-{lengths[contig]:,} with start <= end",
                         "region_anchor_range", length=lengths[contig])
    if end - start + 1 > 20_000:
        raise InputError("A region of interest is at most 20,000 bp; widen the window instead",
                         "region_anchor_too_long", max=20_000)
    return {"kind": "coordinates", "assembly_id": aid, "annotation_id": None, "feature_id": None, "contig": contig,
            "start": start, "end": end, "strand": anchor.get("strand") if anchor.get("strand") in ("+", "-") else "+",
            "type": None, "gene": None, "locus_tag": None, "product": None, "protein": False}


def region_plan(db: Session, cset: ComparisonSet, anchor: dict[str, Any], genome_ids: list[str], flank: int,
                locate: dict[str, float], groups: dict[str, float], links: dict[str, float],
                threads: int | None) -> dict[str, Any]:
    _check_number("flank", flank, 1_000, MAX_FLANK)
    _check_number("locate.min_identity", locate["min_identity"], 20, 100)
    _check_number("locate.min_coverage", locate["min_coverage"], 10, 100)
    _check_number("locate.evalue", locate["evalue"], 1e-300, 1)
    _check_number("groups.min_identity", groups["min_identity"], 20, 100)
    _check_number("groups.min_coverage", groups["min_coverage"], 10, 100)
    _check_number("links.min_identity", links["min_identity"], 50, 100)
    _check_number("links.min_length", links["min_length"], 20, 100_000)
    a = _anchor(db, cset, anchor)
    genomes = _genomes(db, cset, genome_ids, a["assembly_id"], MAX_REGION_GENOMES)
    if len(genomes) < 2:
        raise InputError("Choose at least one other genome", "comparison_size", min=2, max=MAX_REGION_GENOMES)
    focus = genomes[0]
    if a["kind"] == "feature" and focus["annotation"]["annotation_id"] != a["annotation_id"]:
        a["note"] = "not_latest_annotation"
    for g in genomes[1:]:
        ann = g["annotation"]
        g["locate_by"] = "blastp" if a["protein"] and ann and ann["faa_sha256"] and ann["cds_searched"] else "blastn"
    tool = _tool(db, "blast")
    settings = {"flank": flank, "locate": locate, "groups": groups, "links": links, "threads": _threads(db, threads),
                "blastp_task": "blastp", "blastn_task": "blastn"}
    problems = _blast_problems(tool, ("blastn", "blastp"))
    unannotated = [g["label"] for g in genomes if g["annotation"] is None]
    return {"analysis": "region", "method": "blast", "tool": tool, "settings": settings, "anchor": a,
            "genomes": genomes, "unannotated": unannotated, "problems": problems,
            "notes": [HEURISTIC_NOTE, TRANSFER_NOTE]}


def gene_plan(db: Session, cset: ComparisonSet, query_id: str, genome_ids: list[str], task: str | None,
              thresholds: dict[str, float], mobile_distance: int, alignment: dict[str, Any], tree: dict[str, Any],
              threads: int | None) -> dict[str, Any]:
    q = db.get(GeneQuery, query_id)
    if q is None:
        raise InputError("The query does not exist", "gene_query_missing")
    program = "blastn" if q.molecule == "nucleotide" else "tblastn"
    task = task or program
    if task not in PROGRAMS[program]:
        raise InputError(f"{program} task must be one of {', '.join(PROGRAMS[program])}", "gene_task_invalid",
                         program=program)
    _check_number("min_identity", thresholds["min_identity"], 20, 100)
    _check_number("min_coverage", thresholds["min_coverage"], 10, 100)
    _check_number("complete_coverage", thresholds["complete_coverage"], thresholds["min_coverage"], 100)
    _check_number("evalue", thresholds["evalue"], 1e-300, 1)
    _check_number("max_gap", thresholds["max_gap"], 0, 50_000)
    _check_number("mobile_distance", mobile_distance, 0, MAX_MOBILE_DISTANCE)
    genomes = _genomes(db, cset, genome_ids, None, 200)
    n_threads = _threads(db, threads)
    tool = _tool(db, "blast")
    problems = _blast_problems(tool, (program,))
    tools = {"blast": tool}
    settings: dict[str, Any] = {"program": program, "task": task, **thresholds, "mobile_distance": mobile_distance,
                                "low_complexity_filter": True, "max_target_seqs": 500, "threads": n_threads,
                                "alignment": None, "tree": None}
    if alignment.get("enabled"):
        if alignment.get("strategy") not in STRATEGIES:
            raise InputError(f"strategy must be one of {', '.join(STRATEGIES)}", "gene_alignment_strategy")
        kinds = [k for k in alignment.get("kinds") or [] if k in ("complete", "partial", "split")]
        if not kinds:
            raise InputError("Choose which matches to align", "gene_alignment_kinds")
        settings["alignment"] = {"strategy": alignment["strategy"], "kinds": kinds,
                                 "include_query": bool(alignment.get("include_query")) and q.molecule == "nucleotide"}
        tools["mafft"] = mafft = _tool(db, "mafft")
        problems += _problems(mafft)
        if mafft["status"] == "available" and (missing := MafftAdapter.missing_flags(
                MafftAdapter.help_text(mafft["path"]))):
            problems.append({"code": "tool_options_missing", "params": {"tool": "MAFFT", "options": ", ".join(missing)},
                             "message": f"MAFFT does not offer {', '.join(missing)}"})
        if tree.get("enabled"):
            method = tree.get("method")
            if method not in TREE_METHODS:
                raise InputError(f"tree method must be one of {', '.join(TREE_METHODS)}", "gene_tree_method")
            params = TreeParams(method=method, model=tree.get("model") or "MFP", ufboot=int(tree.get("ufboot") or 1000),
                                seed=int(tree.get("seed") or 12345), threads=n_threads)
            try:
                params.validate()
            except ValueError as exc:
                raise InputError(str(exc), "comparison_settings_invalid", detail=str(exc)) from exc
            settings["tree"] = params.as_dict()
            tools["tree"] = tt = _tool(db, method)
            problems += _problems(tt)
            if tt["status"] == "available":
                adapter = IqtreeAdapter if method == "iqtree" else FasttreeAdapter
                if missing := tree_missing_flags(method, adapter.help_text(tt["path"])):
                    problems.append({"code": "tool_options_missing",
                                     "params": {"tool": tt["name"], "options": ", ".join(missing)},
                                     "message": f"{tt['name']} does not offer {', '.join(missing)}"})
    elif tree.get("enabled"):
        raise InputError("A gene tree needs the alignment", "gene_tree_needs_alignment")
    return {"analysis": "gene", "method": program, "tool": tool, "tools": tools, "settings": settings,
            "query": {**query_view(q, with_sequence=True), "created_at": q.created_at.isoformat()},
            "genomes": genomes, "problems": problems,
            "notes": [HEURISTIC_NOTE, TRANSFER_NOTE]}


# --- Results ------------------------------------------------------------------------------------------------------

def _csv(rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()


def hits_csv(r: ComparisonResult) -> str:
    data = result_data(r) or {"genomes": []}
    rows: list[list[Any]] = [["genome", "copy", "kind", "contig", "start", "end", "strand", "identity_percent",
                              "query_coverage_percent", "query_start", "query_end", "query_length", "pieces",
                              "evalue", "bitscore", "at_contig_edge", "overlapping_locus_tag", "overlapping_gene",
                              "overlapping_product", "nearby_mobile_elements", "on_plasmid_contig", "program",
                              "tool_version"]]
    for g in data["genomes"]:
        for m in g["matches"]:
            f = m.get("feature") or {}
            mobile = "; ".join(f"{e['element']} ({e['category']}, {e['method']}, {e['distance']} bp)"
                               for e in m.get("mobile") or [])
            rows.append([g["label"], m["copy"], m["kind"], m["contig"], m["start"], m["end"], m["strand"],
                         m["identity"], m["query_coverage"], m["query_start"], m["query_end"], m["query_length"],
                         len(m["pieces"]), m["evalue"], m["bitscore"], m["at_contig_edge"], f.get("locus_tag"),
                         f.get("gene"), f.get("product"), mobile, m.get("on_plasmid_contig"), r.method,
                         r.tool_version])
    return _csv(rows)


def region_csv(r: ComparisonResult) -> str:
    data = result_data(r) or {"tracks": [], "groups": []}
    names = {g["id"]: g["name"] for g in data["groups"]}
    rows: list[list[Any]] = [["track", "genome", "contig", "located_by", "locus_tag", "gene", "product", "type",
                              "start", "end", "strand", "relative_start", "relative_end", "relative_strand",
                              "homology_group", "group_name", "marks"]]
    for n, t in enumerate(data["tracks"], 1):
        for f in t["features"]:
            marks = "; ".join(f"{m['kind']}: {m['label']}" for m in f.get("marks") or [])
            rows.append([n, t["label"], t["contig"], t["located_by"], f.get("locus_tag"), f.get("gene"),
                         f.get("product"), f["type"], f["start"], f["end"], f["strand"], f["rel_start"], f["rel_end"],
                         f["rel_strand"], f.get("group"), names.get(f.get("group")), marks])
    return _csv(rows)
