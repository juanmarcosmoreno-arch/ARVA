"""Genome Region Explorer and Custom Gene Investigation: saved queries and their validation, gene lookup, plans and
refusals, real BLAST+ / MAFFT / FastTree / IQ-TREE runs on the annotation fixture genome (Prokka's real output, a copy
and a reverse-complemented copy), exports, the comparative report section, and the 'seh across S. aureus genomes'
workflow on NCBI genomes (ARVA_TEST_GENOMES; skipped without them or the tools).
"""
import csv
import hashlib
import io
import os
from pathlib import Path

import pytest
from arva_core.genome_view import reverse_complement
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import GENOME, assemble, prokka_fixture_annotation
from test_comparative_api import project_sample

from app.db.session import SessionLocal
from app.models import AnalysisJob, Annotation, JobStatus, MobileElementResult
from app.tasks.regions import run_gene_investigation_job, run_region_explorer_job

API = "/api/v1"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
SEH = Path(__file__).resolve().parents[3] / "workflows/tool-adapters/tests/fixtures/region/seh_WP_000608674.1.faa"
MW2, MSSA476, N315, USA300 = "GCF_000011265.1", "GCF_000011525.1", "GCF_000009645.1", "GCF_000013465.1"


def need(*tool_ids: str) -> None:
    for t in tool_ids:
        registry._CACHE.pop(t, None)
        if detect(t, refresh=True).status.value != "available":
            pytest.skip(f"{t} is not available")


def annotate(storage_root: Path, sample: dict, assembly: dict) -> str:
    """Prokka's fixture annotation with the real SHA-256 of its protein file (the worker checks it) and its CDS step
    recorded as searched, as a real run records it."""
    ann_id = prokka_fixture_annotation(storage_root, sample, assembly)
    with SessionLocal() as db:
        a = db.get(Annotation, ann_id)
        faa = storage_root / a.files["faa"]["path"]
        a.files = {**a.files, "faa": {**a.files["faa"], "sha256": hashlib.sha256(faa.read_bytes()).hexdigest()}}
        a.steps = {"cds": {"status": "searched"}}
        db.commit()
    return ann_id


@pytest.fixture
def region_set(client, storage_root, tmp_path):
    """Three genomes: the fixture genome annotated twice (two samples) and its reverse complement, unannotated."""
    sa = project_sample(client, "Region project", "REG-A")
    sb = project_sample(client, "Region project B", "REG-B")
    sc = project_sample(client, "Region project C", "REG-REV")
    a1, a2 = assemble(client, sa, GENOME), assemble(client, sb, GENOME)
    rev = tmp_path / "reverse.fna"
    seqs, name = {}, None
    for line in GENOME.read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            seqs[name] = []
        else:
            seqs[name].append(line.strip())
    rev.write_text("".join(f">{n}\n{reverse_complement(''.join(s).encode()).decode()}\n" for n, s in seqs.items()))
    a3 = assemble(client, sc, rev)
    ann1, ann2 = annotate(storage_root, sa, a1), annotate(storage_root, sb, a2)
    cset = client.post(f"{API}/comparisons", json={
        "project_id": sa["project_id"], "name": "Region set", "assembly_ids": [a1["id"], a2["id"], a3["id"]],
        "labels": {a1["id"]: "Fixture A", a2["id"]: "Fixture B", a3["id"]: "Fixture reversed"}}).json()
    return {"set": cset, "assemblies": [a1, a2, a3], "annotations": [ann1, ann2], "samples": [sa, sb, sc]}


def feature(client, ann_id: str, gene: str) -> dict:
    (f,) = [x for x in client.get(f"{API}/annotations/{ann_id}/features", params={"q": gene}).json()["items"]
            if x["gene"] == gene]
    return f


def test_queries_validation_and_library(client, region_set):
    text = SEH.read_text()
    r = client.post(f"{API}/gene-queries", json={"molecule": "protein", "fasta": text, "source": "upload"})
    assert r.status_code == 201
    q = r.json()
    assert q["name"] == "WP_000608674.1" and q["length"] == 241 and q["source"]["kind"] == "upload"
    again = client.post(f"{API}/gene-queries", json={"name": "seh", "molecule": "protein", "fasta": text}).json()
    assert again["id"] == q["id"]
    for body, code in (({"molecule": "protein", "fasta": text + text}, "gene_query_several_records"),
                       ({"molecule": "nucleotide", "fasta": ">x\nACGTQQ" + "A" * 40}, "gene_query_characters"),
                       ({"molecule": "protein", "fasta": ">x\nMKV"}, "gene_query_length"),
                       ({"molecule": "protein", "fasta": ">x\n" + "ACGT" * 20}, "gene_query_looks_nucleotide")):
        r = client.post(f"{API}/gene-queries", json=body)
        assert r.status_code == 400 and r.json()["code"] == code, body
    alka = feature(client, region_set["annotations"][0], "alkA")
    r = client.post(f"{API}/gene-queries/from-feature", json={
        "annotation_id": region_set["annotations"][0], "feature_id": alka["id"], "molecule": "nucleotide"})
    assert r.status_code == 201
    nt = r.json()
    assert nt["name"] == "alkA" and nt["length"] == 849 and nt["source"]["locus_tag"] == "SYNT_00009"
    assert {x["id"] for x in client.get(f"{API}/gene-queries").json()} >= {q["id"], nt["id"]}
    assert client.delete(f"{API}/gene-queries/{q['id']}").status_code == 204
    assert client.get(f"{API}/gene-queries/{q['id']}").status_code == 404


def test_gene_lookup_and_region_refusals(client, region_set):
    cset = region_set["set"]
    rows = client.get(f"{API}/comparisons/{cset['id']}/gene-lookup", params={"q": "alka"}).json()
    assert [r["label"] for r in rows if r["exact"]] == ["Fixture A", "Fixture B"]
    assert client.get(f"{API}/comparisons/{cset['id']}/gene-lookup", params={"q": "a"}).json()["code"] == \
        "gene_lookup_short"
    alka = feature(client, region_set["annotations"][0], "alkA")
    a1, a2, a3 = region_set["assemblies"]
    url = f"{API}/comparisons/{cset['id']}/region"
    body = {"anchor": {"annotation_id": region_set["annotations"][0], "feature_id": alka["id"]},
            "genomes": [a1["id"], a2["id"], a3["id"]], "threads": 2}
    plan = client.post(f"{url}/preview", json=body).json()
    assert plan["anchor"]["gene"] == "alkA" and plan["problems"] == []
    assert [g.get("locate_by") for g in plan["genomes"]] == [None, "blastp", "blastn"]
    assert plan["unannotated"] == ["Fixture reversed"] and any("horizontal transfer" in n for n in plan["notes"])
    assert client.post(url, json=body).json()["code"] == "comparison_confirm"
    for change, code in (({"flank": 100}, "region_setting_range"),
                         ({"anchor": {"assembly_id": a1["id"], "contig": "nope", "start": 1, "end": 10}},
                          "region_anchor_contig"),
                         ({"anchor": {"assembly_id": a1["id"], "contig": "SYNTHETIC_annotation_chromosome",
                                      "start": 50, "end": 10}}, "region_anchor_range"),
                         ({"genomes": [a1["id"]]}, "comparison_size")):
        r = client.post(f"{url}/preview", json={**body, **change})
        assert r.status_code == 400 and r.json()["code"] == code, change


def test_region_explorer_runs_and_draws(client, region_set, held_queue):
    need("blast")
    cset = region_set["set"]
    a1, a2, a3 = region_set["assemblies"]
    alka = feature(client, region_set["annotations"][0], "alkA")
    job = client.post(f"{API}/comparisons/{cset['id']}/region", json={
        "anchor": {"annotation_id": region_set["annotations"][0], "feature_id": alka["id"]}, "flank": 5000,
        "genomes": [a1["id"], a2["id"], a3["id"]], "threads": 2, "confirmed": True}).json()
    assert job["job_type"] == "region_explorer"
    assert run_region_explorer_job(job["id"]) == "completed"
    view = client.get(f"{API}/comparisons/{cset['id']}").json()
    (brief,) = [r for r in view["results"] if r["analysis"] == "region"]
    r = client.get(f"{API}/comparisons/results/{brief['id']}").json()
    data = r["data"]
    t1, t2, t3 = data["tracks"]
    assert [t["located_by"] for t in data["tracks"]] == ["anchor", "blastp", "blastn"]
    assert t2["hit"]["identity"] == 100.0 and (t2["start"], t2["end"]) == (t1["start"], t1["end"])
    assert not t1["flipped"] and t3["flipped"] and t3["features"] == [] and not t3["annotated"]
    anchor = next(f for f in t1["features"] if f["id"] == alka["id"])
    assert (anchor["rel_start"], anchor["rel_end"], anchor["rel_strand"]) == (0, 848, "+")
    same = next(f for f in t2["features"] if f["id"] == alka["id"])
    assert same["group"] == anchor["group"] and next(g for g in data["groups"] if g["anchor"])["name"] == "alkA"
    (l12, l23) = data["links"]
    for block in (l12, l23):
        assert sum(k["length"] for k in block["links"]) > 0.9 * (t1["end"] - t1["start"])
        assert all(k["identity"] == 100.0 and not k["inverted"] and k["upper_start"] == k["lower_start"]
                   for k in block["links"])
    assert {w["code"] for w in r["warnings"]} >= {"region_unannotated"}
    rows = list(csv.DictReader(io.StringIO(client.get(
        f"{API}/comparisons/results/{brief['id']}/neighbourhood.csv").text)))
    assert any(x["gene"] == "alkA" and x["track"] == "2" for x in rows)
    html = client.get(f"{API}/comparisons/{cset['id']}/report.html").text
    assert "Genome Region Explorer" in html and "<polygon" in html and "horizontal transfer" in html


def test_gene_investigation_with_alignment_tree_and_mobile_elements(client, region_set, held_queue):
    need("blast", "mafft", "fasttree")
    cset = region_set["set"]
    a1, a2, a3 = region_set["assemblies"]
    sa = region_set["samples"][0]
    alka = feature(client, region_set["annotations"][0], "alkA")
    with SessionLocal() as db:
        mob = AnalysisJob(project_id=sa["project_id"], sample_id=sa["id"], job_type="mobile_elements",
                          tool_name="ISEScan", tool_version="1.7.3", status=JobStatus.completed, log_text="",
                          input_raw_file_ids=[], parameters={"method": "isescan", "assembly": {"assembly_id": a1["id"]}})
        db.add(mob)
        db.flush()
        db.add(MobileElementResult(sample_id=sa["id"], assembly_id=a1["id"], job_id=mob.id, tool="ISEScan",
                                   category="insertion_sequence", element="IS256", element_type="IS256 family",
                                   contig="SYNTHETIC_annotation_chromosome", start=11000, end=12300, strand="+"))
        db.commit()
    q = client.post(f"{API}/gene-queries/from-feature", json={
        "annotation_id": region_set["annotations"][0], "feature_id": alka["id"], "molecule": "nucleotide"}).json()
    url = f"{API}/comparisons/{cset['id']}/gene"
    body = {"query_id": q["id"], "genomes": [a1["id"], a2["id"], a3["id"]], "threads": 2, "mobile_distance": 2000,
            "alignment": {"enabled": True, "strategy": "linsi", "kinds": ["complete"], "include_query": True},
            "tree": {"enabled": True, "method": "fasttree"}}
    plan = client.post(f"{url}/preview", json=body).json()
    assert plan["method"] == "blastn" and plan["settings"]["task"] == "blastn" and plan["problems"] == []
    assert plan["settings"]["tree"] == {"method": "fasttree", "seed": 12345, "threads": 2}
    bad = client.post(f"{url}/preview", json={**body, "tree": {"enabled": True}, "alignment": {"enabled": False}})
    assert bad.json()["code"] == "gene_tree_needs_alignment"
    job = client.post(url, json={**body, "confirmed": True}).json()
    assert run_gene_investigation_job(job["id"]) == "completed"
    (brief,) = [r for r in client.get(f"{API}/comparisons/{cset['id']}").json()["results"] if r["analysis"] == "gene"]
    r = client.get(f"{API}/comparisons/results/{brief['id']}").json()
    data = r["data"]
    assert [len(g["matches"]) for g in data["genomes"]] == [1, 1, 1]
    m1, _m2, m3 = (g["matches"][0] for g in data["genomes"])
    assert (m1["kind"], m1["start"], m1["end"], m1["strand"], m1["identity"]) == ("complete", 9264, 10112, "+", 100)
    assert m3["strand"] == "-" and m1["feature"]["locus_tag"] == "SYNT_00009"
    assert m1["mobile"][0]["element"] == "IS256" and m1["mobile"][0]["distance"] == 888
    assert data["alignment"]["status"] == "aligned" and len(data["alignment"]["sequences"]) == 4
    assert data["tree"]["status"] == "built" and sorted(_leaves(data["tree"]["tree"])) == sorted(
        ["query", "Fixture A copy 1", "Fixture B copy 1", "Fixture reversed copy 1"])
    assert "gene_tree_identical" in {w["code"] for w in r["warnings"]}
    aligned = client.get(f"{API}/comparisons/results/{brief['id']}/files/alignment/alignment.fasta").text
    assert aligned.count(">") == 4 and ">Fixture reversed copy 1" in aligned
    assert "Fixture A copy 1" in client.get(f"{API}/comparisons/results/{brief['id']}/files/tree/gene_tree.nwk").text
    rows = list(csv.DictReader(io.StringIO(client.get(f"{API}/comparisons/results/{brief['id']}/hits.csv").text)))
    assert rows[0]["nearby_mobile_elements"].startswith("IS256") and rows[2]["strand"] == "-"
    html = client.get(f"{API}/comparisons/{cset['id']}/report.html").text
    assert "Custom gene investigation" in html and "IS256" in html


def _leaves(node: dict) -> list[str]:
    return [node["name"]] if not node["children"] else [x for c in node["children"] for x in _leaves(c)]


def test_real_seh_across_s_aureus_genomes(client, held_queue):
    need("blast", "mafft", "iqtree")
    for acc in (MW2, MSSA476, N315, USA300):
        if not (GENOMES / f"{acc}.fna").is_file():
            pytest.skip("NCBI genomes not cached (workflows/tool-adapters/tests/fixtures/region/README.md)")
    ids = {}
    for code, acc in (("MW2", MW2), ("MSSA476", MSSA476), ("N315", N315), ("USA300", USA300)):
        s = project_sample(client, "seh investigation", code)
        ids[code] = assemble(client, s, GENOMES / f"{acc}.fna", assembler="NCBI RefSeq", version=acc)["id"]
    cset = client.post(f"{API}/comparisons", json={"project_id": s["project_id"], "name": "S. aureus seh",
                                                    "assembly_ids": list(ids.values()),
                                                    "labels": {v: k for k, v in ids.items()}}).json()
    q = client.post(f"{API}/gene-queries", json={"name": "seh", "molecule": "protein", "fasta": SEH.read_text()}).json()
    url = f"{API}/comparisons/{cset['id']}/gene"
    strict = {"query_id": q["id"], "genomes": list(ids.values()), "threads": 2,
              "thresholds": {"min_identity": 70, "min_coverage": 50, "complete_coverage": 90, "evalue": 1e-5,
                             "max_gap": 5000},
              "alignment": {"enabled": True, "strategy": "linsi", "kinds": ["complete"]},
              "tree": {"enabled": True, "method": "iqtree", "model": "GTR+F+G4"}, "confirmed": True}
    assert run_gene_investigation_job(client.post(url, json=strict).json()["id"]) == "completed"
    loose = {**strict, "thresholds": {**strict["thresholds"], "min_identity": 30},
             "alignment": {"enabled": True, "strategy": "linsi", "kinds": ["complete", "partial", "split"]}}
    assert run_gene_investigation_job(client.post(url, json=loose).json()["id"]) == "completed"
    results = sorted((r for r in client.get(f"{API}/comparisons/{cset['id']}").json()["results"]),
                     key=lambda r: r["created_at"])
    first, second = (client.get(f"{API}/comparisons/results/{r['id']}").json() for r in results)
    found = {g["label"]: g["matches"] for g in first["data"]["genomes"]}
    assert [len(found[k]) for k in ("MW2", "MSSA476", "N315", "USA300")] == [1, 1, 0, 0]
    assert found["MW2"][0]["identity"] == 100.0 and found["MW2"][0]["kind"] == "complete"
    codes = {w["code"] for w in first["warnings"]}
    assert {"gene_absent", "gene_tree_too_few"} <= codes and first["data"]["tree"]["status"] == "too_few"
    paralogues = sum(len(g["matches"]) for g in second["data"]["genomes"])
    assert paralogues > 10 and second["data"]["tree"]["status"] == "built"
    assert second["data"]["tree"]["model"] and len(_leaves(second["data"]["tree"]["tree"])) == len(
        second["data"]["alignment"]["sequences"])
