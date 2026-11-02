"""Phylogeny of a comparison set: a tree from an alignment the set's earlier results hold, or a distance tree.

Sources (all within the set, each file checked against the SHA-256 its result recorded):
* core_alignment: Panaroo's concatenated core-gene alignment (`-a core`): core_gene_alignment.aln, or
  core_gene_alignment_filtered.aln without the genes whose alignment entropy is above Panaroo's threshold.
* snp_alignment: the variable columns of that alignment (SNP-sites), with IQ-TREE told about the constant sites left
  out (-fconst with SNP-sites' counts) or ascertainment bias correction (+ASC on an A/C/G/T-only SNP alignment).
* family_alignment: Panaroo's alignment of one gene family (a gene tree).
* gene_alignment: the MAFFT alignment of a Custom Gene Investigation (a gene tree).
* ani_matrix: an ANI result, for a neighbour-joining tree of 1 - ANI/100: a similarity dendrogram, never presented
  as a phylogeny.

Methods: IQ-TREE (ModelFinder, UFBoot and/or SH-aLRT), FastTree (SH-like local supports), or neighbour joining
computed by ARVA (arva_core.phylo) on p-distances, Jukes-Cantor distances or ANI distances: a distance tree.
The inferred tree is kept unrooted as the tool wrote it; the rooting (midpoint or outgroup) is a drawing choice saved
with the Tree Explorer's display (phylo_tree_views) and can change at any time.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import arva_core
from arva_core import newick
from arva_core import phylo as core
from arva_tools.phylo import (
    MIN_SEQUENCES,
    FasttreeAdapter,
    IqtreeAdapter,
    TreeParams,
    missing_flags,
)
from arva_tools.snpsites import SnpsitesAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AmrResult, ComparisonResult, ComparisonSet, PhyloTreeView
from app.services import comparative as comparative_svc
from app.services.comparative import InputError, _problems, _tool
from app.services.pangenome import _read_alignment, alignment_path, family_detail
from app.services.pangenome import data as pangenome_data
from app.services.pangenome import metadata as genome_metadata
from app.services.performance import effective_resources
from app.storage import get_storage

PHYLOGENY_JOB = "phylogeny"
SOURCES = ("core_alignment", "snp_alignment", "family_alignment", "gene_alignment", "ani_matrix")
METHODS = ("iqtree", "fasttree", "nj")
CORE_FILES = {"all": "panaroo/core_gene_alignment.aln", "filtered": "panaroo/core_gene_alignment_filtered.aln"}
GENE_ALIGNMENT = "alignment/alignment.fasta"
CONSTANT_SITES = ("fconst", "asc", "none")
DISTANCES = ("p", "jc69")
ROOTINGS = ("none", "midpoint", "outgroup")
MODEL_SELECTION = ("MFP", "MF", "TEST", "TESTONLY", "TESTNEW", "TESTNEWONLY", "TESTMERGE", "TESTMERGEONLY")
DATA_FILE = "phylogeny.json"
MIN_NJ = 3
GAPPY = 0.5
MAX_FAMILY_NAMES = 5000

ML_NOTE = ("A maximum-likelihood tree describes the history of the aligned sequences under the stated substitution "
           "model. Branch supports measure how consistently the data support a branch, not the probability that "
           "it is correct; recombination and horizontal transfer can make one tree a poor summary.")
GENE_NOTE = ("A gene tree describes the history of one gene, which may differ from the genomes' history (horizontal "
             "transfer, paralogy, recombination, incomplete lineage sorting).")
SNP_NOTE = ("A SNP alignment holds only variable columns. Without -fconst or +ASC, branch lengths would be in "
            "substitutions per variable site and inflated; ARVA states which correction was used.")
DISTANCE_NOTE = ("Neighbour joining on pairwise distances is a distance tree: it is not inferred with a "
                 "substitution model and has no branch support values.")
ANI_NOTE = ("This tree joins genomes by 1 - ANI/100: a similarity dendrogram of whole-genome identity. ANI is not a "
            "phylogenetic method; do not read this tree as an inferred phylogeny.")
ROOT_NOTE = ("The tools infer unrooted trees. A root is a drawing choice: midpoint rooting assumes roughly equal "
             "rates of evolution; an outgroup root is as good as the outgroup. The root's position on its branch is "
             "not estimated (ARVA draws it at the branch's middle).")
SUPPORT_LABELS = {"ufboot": "UFBoot (%)", "alrt": "SH-aLRT (%)", "alrt_ufboot": "SH-aLRT (%) / UFBoot (%)",
                  "sh_like": "SH-like local support (0-1)"}


def _source_file(r: ComparisonResult, key: str) -> dict[str, Any] | None:
    entry = (r.files or {}).get(key)
    if entry is None:
        return None
    present = get_storage().resolve(entry["path"]).is_file()
    return {"key": key, "path": entry["path"], "sha256": entry["sha256"], "present": present}


def _genome_leaves(r: ComparisonResult) -> list[dict[str, Any]]:
    return [{"name": g["label"], "genome": g["label"], "assembly_id": g.get("assembly_id"),
             "sample_id": g.get("sample_id"), "seq_id": g.get("tool_name") or g["label"]} for g in r.genomes]


def sources(db: Session, cset: ComparisonSet) -> list[dict[str, Any]]:
    """What the set's results offer as inputs to a tree."""
    out = []
    results = db.scalars(select(ComparisonResult).where(ComparisonResult.set_id == cset.id)
                         .order_by(ComparisonResult.created_at.desc())).all()
    for r in results:
        base = {"result_id": r.id, "analysis": r.analysis, "method": r.method, "created_at": r.created_at,
                "genomes": len(r.genomes)}
        if r.analysis == "pangenome" and r.method == "panaroo":
            core_files = {k: f for k, key in CORE_FILES.items() if (f := _source_file(r, key))}
            if core_files:
                out.append({**base, "kind": "core_alignment", "core": sorted(core_files)})
                out.append({**base, "kind": "snp_alignment", "core": sorted(core_files)})
            if "alignments.sha256" in (r.files or {}) and (d := pangenome_data(r)):
                names = sorted(f["name"] for f in d["families"] if alignment_path(r, f["name"]) is not None)
                if names:
                    out.append({**base, "kind": "family_alignment", "families": names[:MAX_FAMILY_NAMES],
                                "families_total": len(names)})
        elif r.analysis == "gene" and GENE_ALIGNMENT in (r.files or {}):
            out.append({**base, "kind": "gene_alignment"})
        elif r.analysis == "ani":
            out.append({**base, "kind": "ani_matrix"})
    return out


def _resolve_source(db: Session, cset: ComparisonSet, source: dict[str, Any]) -> dict[str, Any]:
    kind = source.get("kind")
    if kind not in SOURCES:
        raise InputError(f"Unknown tree source {kind}", "phylo_source_unknown", kind=str(kind))
    r = db.get(ComparisonResult, source.get("result_id") or "")
    if r is None or r.set_id != cset.id:
        raise InputError("The source result is not a result of this set", "phylo_source_missing")
    out: dict[str, Any] = {"kind": kind, "result_id": r.id, "analysis": r.analysis, "result_method": r.method,
                           "result_tool": r.tool, "result_tool_version": r.tool_version}
    if kind in ("core_alignment", "snp_alignment"):
        core_choice = source.get("core") or "all"
        if r.analysis != "pangenome" or r.method != "panaroo" or core_choice not in CORE_FILES:
            raise InputError("A core-genome alignment comes from a Panaroo result", "phylo_source_kind", kind=kind)
        f = _source_file(r, CORE_FILES[core_choice])
        if f is None:
            raise InputError("This Panaroo result has no core-genome alignment (run it with 'Align core genes')",
                             "phylo_core_alignment_missing")
        out.update(core=core_choice, file=f, leaves=_genome_leaves(r))
    elif kind == "family_alignment":
        family = str(source.get("family") or "")
        d = pangenome_data(r) if r.analysis == "pangenome" else None
        index = next((i for i, f in enumerate((d or {}).get("families") or []) if f["name"] == family), None)
        aln = alignment_path(r, family) if index is not None else None
        if aln is None:
            raise InputError(f"No alignment of the family {family} in this result", "phylo_family_alignment_missing",
                             family=family)
        try:
            detail = {row["name"]: row for row in family_detail(r, index)["alignment"]["rows"]}
        except (FileNotFoundError, LookupError, KeyError, TypeError):
            detail = {}
        by_tool = {g.get("tool_name"): g for g in r.genomes}
        leaves = []
        for header, _ in _read_alignment(aln):
            tool_name, _, clustering_id = header.removeprefix("_R_").partition(";")
            g = by_tool.get(tool_name) or {}
            gene = (detail.get(header) or {}).get("gene_id") or clustering_id
            leaves.append({"name": f"{g['label']}|{gene}" if g else header, "genome": g.get("label"),
                           "assembly_id": g.get("assembly_id"), "sample_id": g.get("sample_id"), "seq_id": header,
                           "gene_id": gene})
        manifest = get_storage().resolve(r.files["alignments.sha256"]["path"]).read_text()
        rel = f"panaroo/aligned_gene_sequences/{family}.aln.fas"
        sha = next((ln.split()[0] for ln in manifest.splitlines() if ln.endswith(f"  {rel}")), None)
        results_dir = r.files["alignments.sha256"]["path"].rsplit("/", 1)[0]
        out.update(family=family, file={"key": rel, "path": f"{results_dir}/{rel}", "sha256": sha, "present": True},
                   leaves=leaves)
    elif kind == "gene_alignment":
        f = _source_file(r, GENE_ALIGNMENT) if r.analysis == "gene" else None
        data = comparative_svc.result_data(r) if f else None
        if f is None or data is None or not data.get("alignment"):
            raise InputError("This result holds no gene alignment", "phylo_source_kind", kind=kind)
        by_label = {g["label"]: g for g in r.genomes}
        leaves = [{"name": s["label"], "genome": s.get("genome"),
                   "assembly_id": (by_label.get(s.get("genome")) or {}).get("assembly_id"),
                   "sample_id": (by_label.get(s.get("genome")) or {}).get("sample_id"), "seq_id": s["label"],
                   "copy": s.get("copy")} for s in data["alignment"]["sequences"]]
        out.update(file=f, leaves=leaves, query=(r.parameters or {}).get("query", {}).get("name"))
    else:
        if r.analysis != "ani":
            raise InputError("An ANI distance tree comes from an ANI result", "phylo_source_kind", kind=kind)
        out.update(leaves=_genome_leaves(r), file=None)
    if out.get("file") is not None and not out["file"]["present"]:
        raise InputError("The source file is missing on disk", "phylo_source_file_missing", file=out["file"]["key"])
    names = [x["name"] for x in out["leaves"]]
    if len(set(names)) != len(names):
        raise InputError("The source's sequences do not have distinct names", "phylo_leaf_names")
    return out


def _arva_tool() -> dict[str, Any]:
    return {"id": "arva", "name": "ARVA", "status": "available", "version": arva_core.__version__,
            "version_validated": True, "message": "", "reason": None, "reason_params": {}, "path": None,
            "license": "", "citation": "Saitou N, Nei M. The neighbor-joining method: a new method for reconstructing "
            "phylogenetic trees. Mol Biol Evol 1987;4(4):406-425.", "citation_url":
            "https://doi.org/10.1093/oxfordjournals.molbev.a040454", "install": {}}


def _options_problem(tool: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    return {"code": "tool_options_missing", "params": {"tool": tool["name"], "options": ", ".join(missing)},
            "message": f"{tool['name']} does not offer {', '.join(missing)}"}


def plan(db: Session, cset: ComparisonSet, source: dict[str, Any], method: str, iqtree: dict[str, Any],
         constant_sites: str, distance: str, rooting: dict[str, Any], threads: int | None) -> dict[str, Any]:
    if method not in METHODS:
        raise InputError(f"Unknown tree method {method}", "comparison_method_unknown", method=method)
    src = _resolve_source(db, cset, source)
    kind = src["kind"]
    if kind == "ani_matrix" and method != "nj":
        raise InputError("An ANI matrix gives only a neighbour-joining distance tree", "phylo_method_source",
                         method=method, kind=kind)
    if kind == "snp_alignment" and method != "iqtree":
        raise InputError("A SNP alignment needs IQ-TREE (it corrects for the constant sites left out)",
                         "phylo_method_source", method=method, kind=kind)
    n = len(src["leaves"])
    needed = MIN_NJ if method == "nj" else MIN_SEQUENCES
    if n < needed:
        raise InputError(f"A tree needs at least {needed} sequences", "phylo_too_few", count=n, min=needed)
    if constant_sites not in CONSTANT_SITES or distance not in DISTANCES:
        raise InputError("Unknown constant-site or distance setting", "comparison_settings_invalid",
                         detail=f"{constant_sites} / {distance}")
    root_method = rooting.get("method", "midpoint")
    outgroup = list(rooting.get("outgroup") or [])
    names = {x["name"] for x in src["leaves"]}
    if root_method not in ROOTINGS or (root_method == "outgroup" and (not outgroup or not set(outgroup) <= names)):
        raise InputError("The outgroup must name leaves of the tree", "phylo_outgroup_invalid")
    n_threads = effective_resources(db).cap_threads(threads)
    tools: dict[str, Any] = {}
    problems: list[dict[str, Any]] = []
    settings: dict[str, Any] = {"method": method, "threads": n_threads,
                                "rooting": {"method": root_method, "outgroup": outgroup if root_method == "outgroup"
                                            else []}}
    if method == "nj":
        res = effective_resources(db)
        tool = {**_arva_tool(), "max_threads": res.max_threads, "default_threads": res.threads}
        settings["nj"] = {"distance": "ani" if kind == "ani_matrix" else distance}
    else:
        tool = _tool(db, method)
        problems += _problems(tool)
        try:
            params = TreeParams(method=method, model=str(iqtree.get("model") or "MFP"),
                                ufboot=int(iqtree.get("ufboot", 1000)), alrt=int(iqtree.get("alrt", 1000)),
                                seed=int(iqtree.get("seed") or 12345), threads=n_threads)
            asc = kind == "snp_alignment" and constant_sites == "asc"
            if asc and params.model.split("+")[0] in MODEL_SELECTION:
                raise InputError("IQ-TREE 3.0.1 aborts when ModelFinder runs with +ASC: state a model, such as "
                                 "GTR+F+G4", "phylo_asc_needs_model")
            if asc and "+ASC" not in params.model:
                params.model += "+ASC"
            if not asc and "+ASC" in params.model:
                raise InputError("+ASC applies only to a SNP alignment with the ascertainment correction chosen",
                                 "phylo_asc_misplaced")
            params.validate()
            if method == "iqtree" and not params.ufboot and not params.alrt:
                raise ValueError("choose UFBoot, SH-aLRT or both")
        except InputError:
            raise
        except (TypeError, ValueError) as exc:
            raise InputError(str(exc), "comparison_settings_invalid", detail=str(exc)) from exc
        settings["tree"] = params.as_dict()
        if tool["status"] == "available":
            adapter = IqtreeAdapter if method == "iqtree" else FasttreeAdapter
            try:
                missing = missing_flags(method, adapter.help_text(tool["path"]))
            except (OSError, RuntimeError) as exc:
                missing = [str(exc)]
            if missing:
                problems.append(_options_problem(tool, missing))
    if kind == "snp_alignment":
        settings["constant_sites"] = constant_sites
        tools["snp"] = snp = _tool(db, "snp-sites")
        problems += _problems(snp)
        if snp["status"] == "available":
            try:
                missing = SnpsitesAdapter.missing_flags(SnpsitesAdapter.help_text(snp["path"]))
            except (OSError, RuntimeError) as exc:
                missing = [str(exc)]
            if missing:
                problems.append(_options_problem(snp, missing))
    r = db.get(ComparisonResult, src["result_id"])
    notes = [DISTANCE_NOTE if method == "nj" else ML_NOTE]
    notes += [ANI_NOTE] if kind == "ani_matrix" else []
    notes += [GENE_NOTE] if kind in ("family_alignment", "gene_alignment") else []
    notes += [SNP_NOTE] if kind == "snp_alignment" else []
    notes.append(ROOT_NOTE)
    return {"analysis": "phylogeny", "method": method, "tool": tool, "tools": tools, "settings": settings,
            "source": src, "genomes": list(r.genomes), "problems": problems, "notes": notes}


# --- Results ---------------------------------------------------------------------------------------------------------

def data(r: ComparisonResult) -> dict[str, Any] | None:
    entry = (r.files or {}).get(DATA_FILE) if r.analysis == "phylogeny" else None
    if entry is None:
        return None
    path = get_storage().resolve(entry["path"])
    return json.loads(path.read_text()) if path.is_file() else None


def view_of(db: Session, r: ComparisonResult) -> PhyloTreeView:
    v = db.scalar(select(PhyloTreeView).where(PhyloTreeView.result_id == r.id))
    if v is None:
        v = PhyloTreeView(result_id=r.id, rooting={"method": "none", "outgroup": []}, style={})
        db.add(v)
        db.flush()
    return v


def rooted(tree: dict[str, Any], rooting: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if rooting["method"] == "midpoint":
        return core.midpoint_root(tree)
    if rooting["method"] == "outgroup":
        return core.outgroup_root(tree, rooting["outgroup"])
    return tree, {"method": "none"}


def drawing(db: Session, r: ComparisonResult) -> dict[str, Any] | None:
    """The result's data with the tree rooted as the saved view says (unrooted when the rooting no longer applies)."""
    d = data(r)
    if d is None:
        return None
    v = view_of(db, r)
    try:
        tree, info = rooted(d["tree"], v.rooting)
    except core.PhyloError as exc:
        tree, info = d["tree"], {"method": "none", "error": str(exc)}
    return {**d, "rooted": tree, "rooting": info, "view": {"rooting": v.rooting, "style": v.style,
                                                          "updated_at": v.updated_at}}


def save_view(db: Session, r: ComparisonResult, rooting: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    d = data(r)
    if d is None:
        raise FileNotFoundError("The phylogeny files of this result are missing on disk")
    if rooting.get("method") not in ROOTINGS:
        raise InputError("Unknown rooting", "phylo_outgroup_invalid")
    rooting = {"method": rooting["method"], "outgroup": list(rooting.get("outgroup") or [])
               if rooting["method"] == "outgroup" else []}
    try:
        rooted(d["tree"], rooting)
    except core.PhyloError as exc:
        raise InputError(str(exc), "phylo_rooting_failed", detail=str(exc)) from exc
    v = view_of(db, r)
    v.rooting, v.style = rooting, style
    db.commit()
    return drawing(db, r) or {}


def newick_text(db: Session, r: ComparisonResult, root: bool) -> str:
    d = drawing(db, r)
    if d is None:
        raise FileNotFoundError("The phylogeny files of this result are missing on disk")
    return newick.write(d["rooted"] if root else d["tree"]) + "\n"


def amr_genes(db: Session, assembly_id: str | None) -> list[str] | None:
    """The AMR element symbols of the assembly's latest AMRFinderPlus run (None when it was never screened)."""
    if not assembly_id:
        return None
    job_id = db.scalar(select(AmrResult.job_id).where(AmrResult.assembly_id == assembly_id)
                       .order_by(AmrResult.created_at.desc()).limit(1))
    if job_id is None:
        return None
    return sorted({x for x in db.scalars(select(AmrResult.element_symbol).where(
        AmrResult.job_id == job_id, AmrResult.type == "AMR")).all()})


def leaf_metadata(db: Session, r: ComparisonResult) -> dict[str, Any]:
    """Per genome of the result: the sample metadata fields and MLST (as the pangenome view offers them) and the AMR
    genes found; the Tree Explorer maps them to leaves through each leaf's genome."""
    meta = genome_metadata(db, r)
    amr = {g["label"]: amr_genes(db, g.get("assembly_id")) for g in r.genomes}
    genes = sorted({x for v in amr.values() for x in (v or [])})
    return {**meta, "amr": {"genes": genes, "by_genome": amr}}


def compare(a: ComparisonResult, b: ComparisonResult, by: str) -> dict[str, Any]:
    da, db_ = data(a), data(b)
    if da is None or db_ is None:
        raise FileNotFoundError("The phylogeny files of a result are missing on disk")
    ta, tb = da["tree"], db_["tree"]
    if by == "genome":
        ta, tb = _by_genome(ta, da["leaves"]), _by_genome(tb, db_["leaves"])
    try:
        return {**core.robinson_foulds(ta, tb), "by": by}
    except core.PhyloError as exc:
        raise InputError(str(exc), "phylo_compare_failed", detail=str(exc)) from exc


def _by_genome(tree: dict[str, Any], leaves: list[dict[str, Any]]) -> dict[str, Any]:
    genome = {x["name"]: x.get("genome") for x in leaves}
    counts: dict[str, int] = {}
    for x in leaves:
        if x.get("genome"):
            counts[x["genome"]] = counts.get(x["genome"], 0) + 1
    if any(c > 1 for c in counts.values()) or any(not genome.get(n) for n in core.leaf_names(tree)):
        raise InputError("Leaves can be matched by genome only when each genome has exactly one leaf",
                         "phylo_compare_by_genome")

    def walk(n: dict[str, Any]) -> dict[str, Any]:
        return {**n, "name": genome[n["name"]] if not n["children"] else n["name"],
                "children": [walk(c) for c in n["children"]]}
    return walk(tree)


def download_name(cset: ComparisonSet, r: ComparisonResult, name: str) -> str:
    return comparative_svc.download_name(cset, r, name)


def source_path(entry: dict[str, Any]) -> Path:
    return get_storage().resolve(entry["path"])


def read_alignment(path: Path) -> list[tuple[str, str]]:
    """(header, sequence) pairs; the whole header line is the name (a gene investigation's labels hold spaces)."""
    return _read_alignment(path)
