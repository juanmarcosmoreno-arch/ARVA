"""Comparative genomics: comparison sets (assemblies from any project), plans and refusals, ANI matrices (skani
triangle, FastANI all-vs-all), whole-genome alignments (minimap2, NUCmer) with dnadiff, exports, the comparative
report and the sample report's section.

The real runs use four NCBI RefSeq genomes cached in ARVA_TEST_GENOMES (default /root/.arva-testdata/genomes:
S. aureus N315, Mu50, USA300_FPR3757 and S. epidermidis ATCC 12228; workflows/tool-adapters/tests/fixtures/
comparative/README.md) and ARVA's SYNTHETIC genome; they skip when a tool or genome is missing.
"""
import csv
import io
import os
from pathlib import Path

import pytest
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import assemble

from app.db.session import SessionLocal
from app.models import AnalysisJob, Assembly, JobStatus
from app.storage import get_storage
from app.tasks.comparative import run_comparative_alignment_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
SYNTHETIC = REPO / "examples" / "synthetic-genome" / "reference.fasta"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
N315, MU50, USA300, SEPI = "GCF_000009645.1", "GCF_000009665.1", "GCF_000013465.1", "GCF_000007645.1"


def project_sample(client, project: str, code: str) -> dict:
    p = client.post(f"{API}/projects", json={"name": project}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": code, "sequencing_technology": "nanopore"}).json()


def genome(acc: str) -> Path:
    p = GENOMES / f"{acc}.fna"
    if not p.is_file():
        pytest.skip(f"test genome {p} is not cached")
    return p


def need(tool_id: str) -> None:
    registry._CACHE.pop(tool_id, None)
    if detect(tool_id, refresh=True).status.value != "available":
        pytest.skip(f"{tool_id} is not available")


@pytest.fixture
def two_projects(client):
    a = project_sample(client, "Comparative A", "SYN-A")
    b = project_sample(client, "Comparative B", "SYN-B")
    return a, b, assemble(client, a, SYNTHETIC), assemble(client, b, SYNTHETIC)


def test_sets_across_projects_and_their_validation(client, two_projects):
    sa, sb, a1, a2 = two_projects
    ids = {c["assembly_id"] for c in client.get(f"{API}/comparisons/candidates").json()}
    assert {a1["id"], a2["id"]} <= ids
    body = {"project_id": sa["project_id"], "name": "Two synthetic", "assembly_ids": [a1["id"], a2["id"]]}
    r = client.post(f"{API}/comparisons", json=body)
    assert r.status_code == 201, r.text
    s = r.json()
    assert [m["label"] for m in s["members"]] == ["SYN-A (Flye)", "SYN-B (Flye)"]
    assert {m["project_name"] for m in s["members"]} == {"Comparative A", "Comparative B"}
    for bad, code in (({"assembly_ids": [a1["id"], a1["id"]]}, "comparison_duplicate"),
                      ({"assembly_ids": [a1["id"], "nope"]}, "comparison_assembly_missing"),
                      ({"labels": {a1["id"]: "same", a2["id"]: "same"}}, "comparison_label_duplicate"),
                      ({"name": "  "}, "comparison_name_missing")):
        r = client.post(f"{API}/comparisons", json={**body, **bad})
        assert r.status_code == 400 and r.json()["code"] == code, r.text
    assert client.post(f"{API}/comparisons", json={**body, "assembly_ids": [a1["id"]]}).status_code == 422
    r = client.put(f"{API}/comparisons/{s['id']}", json={**body, "name": "Renamed", "assembly_ids": [a2["id"], a1["id"]],
                                                         "labels": {a2["id"]: "B first"}})
    assert r.status_code == 200 and [m["label"] for m in r.json()["members"]] == ["B first", "SYN-A (Flye)"]
    listed = client.get(f"{API}/comparisons", params={"project_id": sa["project_id"]}).json()
    assert [x["name"] for x in listed] == ["Renamed"] and listed[0]["genomes"] == 2
    assert client.get(f"{API}/comparisons", params={"project_id": sb["project_id"]}).json() == []
    assert client.delete(f"{API}/comparisons/{s['id']}").status_code == 204
    assert client.get(f"{API}/comparisons/{s['id']}").status_code == 404
    assert len(client.get(f"{API}/samples/{sa['id']}/assemblies").json()) == 1


def test_plans_and_refusals(client, two_projects, monkeypatch):
    sa, _sb, a1, a2 = two_projects
    s = client.post(f"{API}/comparisons", json={"project_id": sa["project_id"], "name": "S",
                                                 "assembly_ids": [a1["id"], a2["id"]]}).json()
    monkeypatch.setenv("ARVA_TOOL_SKANI", "/nonexistent/skani")
    registry._CACHE.pop("skani", None)
    plan = client.post(f"{API}/comparisons/{s['id']}/ani/preview", json={"method": "skani"}).json()
    assert plan["problems"][0]["code"] == "tool_missing" and plan["comparisons"] == 1
    assert plan["settings"] == {"threads": plan["settings"]["threads"], "c": 125, "m": 1000, "s": 80.0,
                                "min_af": 15.0}
    assert any("not a phylogeny" in n for n in plan["notes"])
    r = client.post(f"{API}/comparisons/{s['id']}/ani", json={"method": "skani"})
    assert r.status_code == 400 and r.json()["code"] == "comparison_confirm"
    r = client.post(f"{API}/comparisons/{s['id']}/ani", json={"method": "skani", "confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "comparison_blocked"
    r = client.post(f"{API}/comparisons/{s['id']}/alignment/preview", json={"order": [a1["id"]]})
    assert r.status_code == 400 and r.json()["code"] == "comparison_size"
    r = client.post(f"{API}/comparisons/{s['id']}/alignment/preview", json={"order": [a1["id"], "x"]})
    assert r.status_code == 400 and r.json()["code"] == "comparison_order_invalid"
    plan = client.post(f"{API}/comparisons/{s['id']}/alignment/preview",
                       json={"order": [a2["id"], a1["id"]], "preset": "asm20", "dnadiff": False}).json()
    assert plan["reference"] == "SYN-B (Flye)" and plan["settings"]["preset"] == "asm20"
    assert plan["pairs"] == [{"reference": "SYN-B (Flye)", "query": "SYN-A (Flye)", "role": "reference"}]
    assert client.post(f"{API}/comparisons/{s['id']}/alignment/preview",
                       json={"aligner": "nucmer", "nucmer": {"anchors": "all"}}).status_code == 422


def test_nucmer_alignment_of_identical_genomes_and_changed_contigs(client, two_projects, held_queue):
    need("nucmer")
    sa, _sb, a1, a2 = two_projects
    s = client.post(f"{API}/comparisons", json={"project_id": sa["project_id"], "name": "Identical",
                                                 "assembly_ids": [a1["id"], a2["id"]]}).json()
    job = client.post(f"{API}/comparisons/{s['id']}/alignment",
                      json={"aligner": "nucmer", "dnadiff": False, "confirmed": True}).json()
    assert run_comparative_alignment_job(job["id"]) == "completed"
    view = client.get(f"{API}/comparisons/{s['id']}").json()
    (brief,) = view["results"]
    r = client.get(f"{API}/comparisons/results/{brief['id']}").json()
    (pair,) = r["summary"]["pairs"]
    assert pair["identity"] == 100.0 and pair["ref_fraction"] == 1.0 and pair["query_fraction"] == 1.0
    codes = {w["code"] for w in r["warnings"]}
    assert {"comparison_identical_genomes", "nucmer_all_blocks", "synthetic_input"} <= codes
    assert all(w["covered"] == 1.0 for g in r["alignment"]["conservation"]["genomes"] for w in g["windows"])
    assert r["genomes"][0]["contigs_sha256"] == r["genomes"][1]["contigs_sha256"]
    with SessionLocal() as db:
        j = db.get(AnalysisJob, job["id"])
        assert j.commands[0][1:4] == ["--mumreference", "-b", "200"]
        assert not any("/input/" in p for p in j.output_paths)
    root = get_storage().resolve(f"results/{sa['project_id']}/_project/{job['id']}")
    assert not (root / "input").exists() and (root / "pairs" / "g1_g2" / "pair.coords").is_file()

    job = client.post(f"{API}/comparisons/{s['id']}/alignment",
                      json={"aligner": "nucmer", "dnadiff": False, "confirmed": True}).json()
    with SessionLocal() as db:
        path = get_storage().resolve(db.get(Assembly, a1["id"]).contigs_path)
    path.write_text(path.read_text().replace("ACGT", "TTTT", 1))
    assert run_comparative_alignment_job(job["id"]) == "failed"
    with SessionLocal() as db:
        j = db.get(AnalysisJob, job["id"])
        assert j.status is JobStatus.failed and j.error_detail["code"] == "contigs_changed"


def test_real_ani_and_alignment_on_ncbi_genomes(client):
    for tool in ("skani", "minimap2", "dnadiff"):
        need(tool)
    paths = {acc: genome(acc) for acc in (N315, MU50, USA300, SEPI)}
    labels = {N315: "N315", MU50: "Mu50", USA300: "USA300", SEPI: "S. epidermidis"}
    sample_a = project_sample(client, "Staph A", "N315")
    sample_b = project_sample(client, "Staph B", "USA300")
    samples = {N315: sample_a, USA300: sample_b}
    for acc, code in ((MU50, "Mu50"), (SEPI, "SE-12228")):
        project = sample_a["project_id"] if acc == MU50 else sample_b["project_id"]
        samples[acc] = client.post(f"{API}/projects/{project}/samples",
                                   json={"sample_code": code, "sequencing_technology": "nanopore"}).json()
    asm = {acc: assemble(client, samples[acc], p) for acc, p in paths.items()}
    s = client.post(f"{API}/comparisons", json={
        "project_id": sample_a["project_id"], "name": "Staphylococcus", "assembly_ids": [asm[a]["id"] for a in paths],
        "labels": {asm[a]["id"]: labels[a] for a in paths}}).json()

    r = client.post(f"{API}/comparisons/{s['id']}/ani", json={"method": "skani", "threads": 2, "confirmed": True})
    assert r.status_code == 202, r.text
    view = client.get(f"{API}/comparisons/{s['id']}").json()
    ani = client.get(f"{API}/comparisons/results/{view['results'][0]['id']}").json()
    m = ani["summary"]["matrix"]
    names = m["ids"]
    at = {(names[i], names[j]): m["ani"][i][j] for i in range(4) for j in range(4)}
    assert at[("N315", "Mu50")] == at[("Mu50", "N315")] == 99.90
    assert at[("N315", "USA300")] == 98.97 and at[("Mu50", "USA300")] == 98.86
    assert all(at[("S. epidermidis", x)] is None for x in names)
    order = [names[i] for i in ani["summary"]["order"]["order"]]
    assert order == ["S. epidermidis", "USA300", "N315", "Mu50"]
    codes = {w["code"]: w["params"] for w in ani["warnings"]}
    assert codes["ani_pairs_not_reported"]["count"] == 3 and "skani_learned_ani" in codes
    rows = list(csv.DictReader(io.StringIO(client.get(f"{API}/comparisons/results/{ani['id']}/ani.csv").text)))
    assert len(rows) == 12 and {r_["ani_percent"] for r_ in rows if r_["genome_a"] == "S. epidermidis"} == {""}
    assert client.get(f"{API}/comparisons/results/{ani['id']}/blocks.csv").status_code == 404

    order_ids = [asm[a]["id"] for a in (N315, MU50, USA300)]
    r = client.post(f"{API}/comparisons/{s['id']}/alignment",
                    json={"aligner": "minimap2", "preset": "asm10", "order": order_ids, "threads": 2,
                          "confirmed": True})
    assert r.status_code == 202, r.text
    view = client.get(f"{API}/comparisons/{s['id']}").json()
    aln = client.get(f"{API}/comparisons/results/{view['results'][0]['id']}").json()
    assert aln["analysis"] == "alignment" and [g["label"] for g in aln["genomes"]] == ["N315", "Mu50", "USA300"]
    pairs = {(p["reference"], p["query"]): p for p in aln["summary"]["pairs"]}
    assert set(pairs) == {("N315", "Mu50"), ("N315", "USA300"), ("Mu50", "USA300")}
    assert pairs[("N315", "Mu50")]["role"] == "reference" and pairs[("Mu50", "USA300")]["role"] == "neighbour"
    # minimap2 identity counts gap bases (matching bases / block length), so long indels inside blocks lower it.
    assert all(p["identity"] > 90 and p["ref_fraction"] > 0.9 for p in pairs.values())
    dd = {d["query"]: d["report"] for d in aln["summary"]["dnadiff"]}
    # The same dnadiff run on the same genomes as fixtures/comparative/dnadiff_n315_mu50.report.
    assert (dd["Mu50"]["reference"]["relocations"], dd["Mu50"]["query"]["relocations"]) == (5, 8)
    assert (dd["Mu50"]["reference"]["inversions"], dd["Mu50"]["query"]["inversions"]) == (4, 2)
    cons = aln["alignment"]["conservation"]
    assert cons["reference"] == "N315" and cons["window"] == 2000
    assert [g["label"] for g in cons["genomes"]] == ["Mu50", "USA300"]
    assert sum(w["covered"] for w in cons["genomes"][0]["windows"]) / len(cons["genomes"][0]["windows"]) > 0.9
    assert {g["label"]: len(g["contigs"]) for g in aln["alignment"]["genomes"]} == {"N315": 2, "Mu50": 2,
                                                                                    "USA300": 4}
    diffs = list(csv.DictReader(io.StringIO(client.get(f"{API}/comparisons/results/{aln['id']}/differences.csv").text)))
    inversions = [d for d in diffs if d["query_genome"] == "Mu50" and d["category"] == "inversion"]
    assert len(inversions) == 6 and {d["type"] for d in inversions} == {"INV"}
    blocks = client.get(f"{API}/comparisons/results/{aln['id']}/blocks.csv").text
    assert blocks.startswith("reference_genome,reference_contig") and "NC_002745.2" in blocks
    assert client.get(f"{API}/comparisons/results/{aln['id']}/conservation.csv").text.count("\n") > 2000
    assert "NUCMER" in client.get(f"{API}/comparisons/results/{aln['id']}/files/dnadiff/g1_g2/dnadiff.report").text
    assert client.get(f"{API}/comparisons/results/{aln['id']}/files/../../etc/passwd").status_code == 404

    html = client.get(f"{API}/comparisons/{s['id']}/report.html").text
    assert "Comparative genomics report" in html and "not a phylogeny" in html and "Staphylococcus" in html
    assert "<script" not in html.lower()
    data = client.get(f"{API}/comparisons/{s['id']}/report.json").json()
    assert [x["analysis"] for x in data["results"]] == ["ani", "alignment"] and data["results"][1]["commands"]
    report = client.get(f"{API}/samples/{sample_b['id']}/report")
    assert report.status_code == 200 and "Comparative genomics" in report.text and "USA300" in report.text
