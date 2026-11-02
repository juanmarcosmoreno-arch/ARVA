"""Phylogeny of a comparison set: sources, plans and refusals, and real runs (IQ-TREE on Panaroo's core-genome
alignment and its SNPs, FastTree and neighbour joining on a gene family, neighbour joining on an ANI matrix) on the
five NCBI S. aureus genomes of the pangenome fixtures. The Panaroo result is registered from the cached real
`-a core` output (ARVA_TEST_GENOMES/panaroo-1.8.1-core, workflows/tool-adapters/tests/fixtures/phylogeny/README.md);
the tests skip without it or without the tools. Then: rooting, the saved view, Newick downloads, tree comparison,
leaf metadata and the reports.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from arva_core import newick, phylo
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import assemble
from test_comparative_api import project_sample

from app.db.session import SessionLocal
from app.models import AnalysisJob, ComparisonResult, JobStatus
from app.tasks.phylogeny import run_phylogeny_job

API = "/api/v1"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
PANAROO = GENOMES / "panaroo-1.8.1-core" / "out"
FX = Path(__file__).parents[3] / "workflows" / "tool-adapters" / "tests" / "fixtures" / "phylogeny"
ACCS = {"g1": ("GCF_000009645.1", "N315"), "g2": ("GCF_000009665.1", "Mu50"), "g3": ("GCF_000013465.1", "USA300"),
        "g4": ("GCF_000011265.1", "MW2"), "g5": ("GCF_000011525.1", "MSSA476")}
FAMILIES = ("spa", "dnaA")


def _need(*tools: str) -> None:
    for t in tools:
        registry._CACHE.pop(t, None)
        if detect(t, refresh=True).status.value != "available":
            pytest.skip(f"{t} is not available")
    if not (PANAROO / "core_gene_alignment.aln").is_file() or not all(
            (GENOMES / f"{acc}.fna").is_file() for acc, _ in ACCS.values()):
        pytest.skip("Panaroo's cached core alignment or the NCBI genomes are missing (fixtures/phylogeny/README.md)")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _entry(storage_root: Path, rel: str) -> dict:
    p = storage_root / rel
    return {"path": rel, "sha256": _sha(p), "size_bytes": p.stat().st_size}


@pytest.fixture
def tree_set(client, storage_root):
    """A set of the five genomes with a registered Panaroo result (core alignments, two aligned families)."""
    _need("iqtree", "snp-sites")
    ids, labels, genomes = [], {}, []
    for tool_name, (acc, label) in ACCS.items():
        s = project_sample(client, "Phylogeny project", label)
        a = assemble(client, s, GENOMES / f"{acc}.fna", assembler="NCBI RefSeq", version=acc)
        ids.append(a["id"])
        labels[a["id"]] = label
        genomes.append({"label": label, "assembly_id": a["id"], "sample_id": s["id"], "tool_name": tool_name,
                        "contigs_sha256": _sha(GENOMES / f"{acc}.fna")})
    cset = client.post(f"{API}/comparisons", json={"project_id": s["project_id"], "name": "S. aureus tree",
                                                   "assembly_ids": ids, "labels": labels}).json()
    with SessionLocal() as db:
        job = AnalysisJob(project_id=s["project_id"], sample_id=None, job_type="pangenome", tool_name="Panaroo",
                          tool_version="1.8.1", parameters={"set_id": cset["id"]}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        db.add(job)
        db.commit()
        rel = f"results/{s['project_id']}/comparisons/{job.id}"
        out = storage_root / rel
        (out / "panaroo" / "aligned_gene_sequences").mkdir(parents=True)
        for name in ("core_gene_alignment.aln", "core_gene_alignment_filtered.aln"):
            shutil.copyfile(PANAROO / name, out / "panaroo" / name)
        manifest = ""
        for fam in FAMILIES:
            f = out / "panaroo" / "aligned_gene_sequences" / f"{fam}.aln.fas"
            shutil.copyfile(PANAROO / "aligned_gene_sequences" / f.name, f)
            manifest += f"{_sha(f)}  panaroo/aligned_gene_sequences/{f.name}\n"
        (out / "alignments.sha256").write_text(manifest)
        (out / "pangenome.json").write_text(json.dumps({"genomes": genomes, "families": [
            {"name": fam, "presence": "11111"} for fam in FAMILIES]}))
        files = {k: _entry(storage_root, f"{rel}/{k}") for k in (
            "panaroo/core_gene_alignment.aln", "panaroo/core_gene_alignment_filtered.aln", "alignments.sha256",
            "pangenome.json")}
        r = ComparisonResult(set_id=cset["id"], job_id=job.id, analysis="pangenome", method="panaroo",
                             tool="Panaroo", tool_version="1.8.1", parameters={}, genomes=genomes, summary={},
                             warnings=[], files=files)
        db.add(r)
        db.commit()
        pan_id = r.id
    yield {"set": cset, "pangenome": pan_id, "genomes": genomes, "storage_root": storage_root}


def _expected(labels: bool = True) -> dict:
    t = newick.parse((FX / "core_mfp_ufboot_alrt.treefile").read_text())
    return newick.rename(t, {k: v[1] for k, v in ACCS.items()}) if labels else t


def _run(client, set_id: str, body: dict) -> dict:
    url = f"{API}/comparisons/{set_id}/phylogeny"
    plan = client.post(f"{url}/preview", json=body)
    assert plan.status_code == 200, plan.json()
    assert plan.json()["problems"] == []
    job = client.post(url, json={**body, "confirmed": True}).json()
    status = run_phylogeny_job(job["id"])
    with SessionLocal() as db:
        done = db.get(AnalysisJob, job["id"])
        assert status == "completed", done.log_text[-3000:]
        rid = done.result_summary["comparison_result_id"]
        commands = done.commands
    return {**client.get(f"{API}/comparisons/results/{rid}").json(), "commands": commands}


def test_sources_and_plan_refusals(client, tree_set, held_queue):
    sid, pan = tree_set["set"]["id"], tree_set["pangenome"]
    kinds = {x["kind"]: x for x in client.get(f"{API}/comparisons/{sid}/phylogeny/sources").json()}
    assert set(kinds) == {"core_alignment", "snp_alignment", "family_alignment"}
    assert kinds["core_alignment"]["core"] == ["all", "filtered"] and kinds["family_alignment"]["families"] == [
        "dnaA", "spa"]
    url = f"{API}/comparisons/{sid}/phylogeny/preview"
    core = {"kind": "core_alignment", "result_id": pan}
    snp = {"kind": "snp_alignment", "result_id": pan}
    for body, code in (({"source": snp, "method": "fasttree"}, "phylo_method_source"),
                       ({"source": snp, "constant_sites": "asc"}, "phylo_asc_needs_model"),
                       ({"source": core, "iqtree": {"model": "GTR+F+ASC+G4"}}, "phylo_asc_misplaced"),
                       ({"source": core, "rooting": {"method": "outgroup", "outgroup": ["nope"]}},
                        "phylo_outgroup_invalid"),
                       ({"source": {**core, "result_id": "x" * 36}}, "phylo_source_missing"),
                       ({"source": {"kind": "family_alignment", "result_id": pan, "family": "../x"}},
                        "phylo_family_alignment_missing"),
                       ({"source": {"kind": "gene_alignment", "result_id": pan}}, "phylo_source_kind"),
                       ({"source": core, "iqtree": {"ufboot": 0, "alrt": 0}}, "comparison_settings_invalid")):
        r = client.post(url, json=body)
        assert r.status_code == 400 and r.json()["code"] == code, (body, r.json())
    plan = client.post(url, json={"source": snp, "constant_sites": "asc", "iqtree": {"model": "GTR+F+G4"}}).json()
    assert plan["settings"]["tree"]["model"] == "GTR+F+G4+ASC" and plan["tools"]["snp"]["id"] == "snp-sites"
    assert any("SNP alignment" in n for n in plan["notes"])
    assert client.post(f"{API}/comparisons/{sid}/phylogeny", json={"source": core}).json()["code"] == \
        "comparison_confirm"


def test_real_core_and_snp_trees_rooting_view_and_comparison(client, tree_set, held_queue):
    sid, pan = tree_set["set"]["id"], tree_set["pangenome"]
    core = _run(client, sid, {"source": {"kind": "core_alignment", "result_id": pan}, "threads": 2})
    s, d = core["summary"], core["data"]
    assert core["method"] == "iqtree" and s["iqtree"]["model"] == "TIM2+F+I" and s["support"]["kind"] == "alrt_ufboot"
    assert s["alignment"]["columns"] == 2186160 and s["alignment"]["variable"] == 30888
    assert phylo.robinson_foulds(d["tree"], _expected())["rf"] == 0
    assert d["rooting"]["method"] == "midpoint" and len(d["rooted"]["children"]) == 2
    assert {"phylogeny.json", "phylogeny.nwk", "tree.treefile", "tree.iqtree", "tree.mldist"} <= set(core["files"])
    argv = core["commands"][0]
    assert argv[argv.index("-m") + 1] == "MFP" and argv[argv.index("--alrt") + 1] == "1000" and "input.fasta" in argv
    snp = _run(client, sid, {"source": {"kind": "snp_alignment", "result_id": pan}, "threads": 2,
                             "rooting": {"method": "none"}})
    assert snp["summary"]["snp_columns"] == 30888
    assert snp["summary"]["constant_counts"] == {"A": 775527, "C": 315491, "G": 409032, "T": 655216}
    argv = snp["commands"][-1]
    assert argv[argv.index("-fconst") + 1] == "775527,315491,409032,655216" and "snp.fasta" in argv
    assert snp["data"]["rooting"]["method"] == "none"
    cmp = client.get(f"{API}/comparisons/phylogeny/compare", params={"a": core["id"], "b": snp["id"]}).json()
    assert cmp["rf"] == 0 and cmp["common_leaves"] == 5
    view = f"{API}/comparisons/results/{core['id']}/phylogeny/view"
    style = {"layout": "circular", "collapsed": ["abc"], "branch_colors": {"abc": "#00B4A6"}, "bands": ["host"]}
    bad = client.put(view, json={"rooting": {"method": "outgroup", "outgroup": ["N315", "MW2"]}, "style": style})
    assert bad.status_code == 400 and bad.json()["code"] == "phylo_rooting_failed"
    ok = client.put(view, json={"rooting": {"method": "outgroup", "outgroup": ["USA300", "MW2", "MSSA476"]},
                                "style": style}).json()
    sides = [sorted(phylo.leaf_names(c)) for c in ok["rooted"]["children"]]
    assert sorted(sides) == [["MSSA476", "MW2", "USA300"], ["Mu50", "N315"]]
    assert ok["view"]["style"]["layout"] == "circular" and ok["view"]["style"]["branch_colors"] == {"abc": "#00B4A6"}
    assert client.put(view, json={"rooting": {"method": "none"}, "style": {"branch_colors": {"a": "red"}}}
                      ).status_code == 422
    rooted = client.get(f"{API}/comparisons/results/{core['id']}/phylogeny/tree.nwk").text
    unrooted = client.get(f"{API}/comparisons/results/{core['id']}/phylogeny/tree.nwk", params={"rooted": False}).text
    assert len(newick.parse(rooted)["children"]) == 2 and len(newick.parse(unrooted)["children"]) == 3
    assert "100/100" in unrooted
    meta = client.get(f"{API}/comparisons/results/{core['id']}/phylogeny/metadata").json()
    assert meta["genomes"] == ["N315", "Mu50", "USA300", "MW2", "MSSA476"] and "amr" in meta
    assert {f["key"] for f in meta["fields"]} >= {"host", "mlst"}
    report = client.get(f"{API}/comparisons/results/{core['id']}/phylogeny/report.html")
    assert report.status_code == 200 and "Phylogenetic report" in report.text and "<svg" in report.text
    assert "TIM2+F+I" in report.text and "rooted on the outgroup" in report.text
    with SessionLocal() as db:  # the registered Panaroo result holds only the files a tree needs
        db.delete(db.get(ComparisonResult, pan))
        db.commit()
    set_report = client.get(f"{API}/comparisons/{sid}/report.html").text
    assert "Phylogeny · IQ-TREE" in set_report


def test_real_gene_trees_and_ani_distance_tree(client, tree_set, held_queue):
    _need("fasttree")
    sid, pan = tree_set["set"]["id"], tree_set["pangenome"]
    fam = {"kind": "family_alignment", "result_id": pan, "family": "spa"}
    ft = _run(client, sid, {"source": fam, "method": "fasttree"})
    leaves = phylo.leaf_names(ft["data"]["tree"])
    assert len(leaves) == 5 and all("|" in x for x in leaves)
    assert ft["data"]["support"]["kind"] == "sh_like" and any("gene tree" in n for n in ft["summary"]["notes"])
    nj = _run(client, sid, {"source": fam, "method": "nj", "distance": "p"})
    assert nj["tool"] == "ARVA neighbour joining" and nj["summary"]["distance_tree"]
    assert nj["data"]["distances"]["kind"] == "p" and "distances.tsv" in nj["files"]
    cmp = client.get(f"{API}/comparisons/phylogeny/compare", params={"a": ft["id"], "b": nj["id"], "by": "genome"})
    assert cmp.status_code == 200 and cmp.json()["common_leaves"] == 5 and cmp.json()["by"] == "genome"
    with SessionLocal() as db:
        job = AnalysisJob(project_id=tree_set["set"]["project_id"], sample_id=None, job_type="comparative_ani",
                          tool_name="skani", tool_version="0.2.2", parameters={}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        db.add(job)
        db.commit()
        ani = [[100, 99.9, 99.1, 99.0, 99.0], [99.9, 100, 99.1, 99.0, 99.0], [99.1, 99.1, 100, 99.4, 99.4],
               [99.0, 99.0, 99.4, 100, 99.95], [99.0, 99.0, 99.4, 99.95, 100]]
        r = ComparisonResult(set_id=sid, job_id=job.id, analysis="ani", method="skani", tool="skani",
                             tool_version="0.2.2", parameters={}, genomes=tree_set["genomes"],
                             summary={"matrix": {"ani": ani}}, warnings=[], files={})
        db.add(r)
        db.commit()
        ani_id = r.id
    url = f"{API}/comparisons/{sid}/phylogeny/preview"
    r = client.post(url, json={"source": {"kind": "ani_matrix", "result_id": ani_id}})
    assert r.status_code == 400 and r.json()["code"] == "phylo_method_source"
    dendro = _run(client, sid, {"source": {"kind": "ani_matrix", "result_id": ani_id}, "method": "nj"})
    assert {w["code"] for w in dendro["warnings"]} >= {"phylo_ani_dendrogram"}
    assert phylo.splits(dendro["data"]["tree"]) == phylo.splits(newick.parse("((N315,Mu50),USA300,(MW2,MSSA476));"))
    report = client.get(f"{API}/comparisons/results/{dendro['id']}/phylogeny/report.html").text
    assert "similarity dendrogram" in report
