"""Pangenome of a comparison set: plans and refusals (missing or inconsistent annotations, sizes, thresholds), and a
real Panaroo run on three NCBI S. aureus genomes annotated with Bakta (ARVA_TEST_GENOMES; skipped without them or
Panaroo): the result view, a family's members, sequences and neighbours, exports, metadata groups and associations,
and the report section.
"""
import csv
import hashlib
import io
import os
import shutil
from pathlib import Path

import pytest
from arva_core.annotation import write_jsonl
from arva_tools import registry
from arva_tools.prokka import ProkkaAdapter
from arva_tools.registry import detect
from test_annotation_api import GENOME, assemble, prokka_fixture_annotation
from test_comparative_api import project_sample

from app.db.session import SessionLocal
from app.models import AnalysisJob, Annotation, JobStatus, Sample
from app.tasks.pangenome import run_pangenome_job

API = "/api/v1"
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes"))
BAKTA = GENOMES / "bakta-1.12.2-light6"
N315, MU50, MW2 = "GCF_000009645.1", "GCF_000009665.1", "GCF_000011265.1"


def bakta_annotation(storage_root: Path, sample: dict, assembly: dict, gff: Path) -> str:
    """An annotation registered from a cached real Bakta 1.12.2 GFF3 (fixtures/pangenome/README.md), CDS searched."""
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="bakta_annotation",
                          tool_name="Bakta", tool_version="1.12.2", parameters={}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        db.add(job)
        db.commit()
        rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}"
        (storage_root / rel / "bakta").mkdir(parents=True)
        shutil.copyfile(gff, storage_root / rel / "bakta" / "annotation.gff3")
        sequences, features = ProkkaAdapter.parse_gff(gff.read_text())
        write_jsonl(storage_root / rel / "features.jsonl", features)
        a = Annotation(sample_id=sample["id"], assembly_id=assembly["id"], job_id=job.id, tool="Bakta",
                       tool_version="1.12.2", database_version="6.0", parameters={}, steps={"cds": {"status":
                                                                                                "searched"}},
                       summary={}, sequences=sequences,
                       files={"gff3": {"path": f"{rel}/bakta/annotation.gff3",
                                       "sha256": hashlib.sha256(gff.read_bytes()).hexdigest(), "size_bytes": 1}},
                       features_path=f"{rel}/features.jsonl")
        db.add(a)
        db.commit()
        return a.id


def body(**extra) -> dict:
    return {"threads": 2, "curves": {"permutations": 20, "seed": 7}, **extra}


def test_plan_refusals_and_annotation_checks(client, storage_root):
    samples = [project_sample(client, "Pan plan", f"PAN-{i}") for i in range(3)]
    asms = [assemble(client, s, GENOME) for s in samples]
    cset = client.post(f"{API}/comparisons", json={"project_id": samples[0]["project_id"], "name": "Pan set",
                                                   "assembly_ids": [a["id"] for a in asms]}).json()
    url = f"{API}/comparisons/{cset['id']}/pangenome"
    prokka_fixture_annotation(storage_root, samples[0], asms[0])
    plan = client.post(f"{url}/preview", json=body()).json()
    codes = {p["code"]: p["params"] for p in plan["problems"]}
    assert "pangenome_annotation_missing" in codes and "pangenome_cds_missing" in codes
    assert plan["settings"]["categories"] == {"core": 0.99, "soft_core": 0.95, "shell": 0.15}
    assert plan["settings"]["tool"]["mode_dependent"]["remove_by_consensus"] is True
    assert plan["genomes"][0]["annotation"]["tool"] == "Prokka" and plan["genomes"][1]["annotation"] is None
    for change, code in (({"genomes": [asms[0]["id"], asms[1]["id"]]}, "pangenome_size"),
                         ({"categories": {"core": 0.9, "soft_core": 0.95, "shell": 0.15}},
                          "pangenome_thresholds_invalid"),
                         ({"curves": {"permutations": 5, "seed": 1}}, "pangenome_setting_range"),
                         ({"panaroo": {"identity": 0.1}}, "comparison_settings_invalid")):
        r = client.post(f"{url}/preview", json=body(**change))
        assert r.status_code == 400 and r.json()["code"] == code, change
    assert client.post(url, json=body()).json()["code"] == "comparison_confirm"
    r = client.post(url, json=body(confirmed=True))
    assert r.status_code == 409 and r.json()["code"] == "comparison_blocked"


def test_real_panaroo_pangenome_of_three_s_aureus(client, storage_root, held_queue):
    registry._CACHE.pop("panaroo", None)
    if detect("panaroo", refresh=True).status.value != "available":
        pytest.skip("Panaroo is not available")
    gffs = {acc: BAKTA / acc / f"{acc}.gff3" for acc in (N315, MU50, MW2)}
    if not all(p.is_file() and (GENOMES / f"{acc}.fna").is_file() for acc, p in gffs.items()):
        pytest.skip("the Bakta-annotated NCBI genomes are not cached (fixtures/pangenome/README.md)")
    ids, labels, samples = [], {}, []
    for acc, host in ((N315, "human"), (MU50, "human"), (MW2, "community")):
        s = project_sample(client, "Pangenome project", acc)
        a = assemble(client, s, GENOMES / f"{acc}.fna", assembler="NCBI RefSeq", version=acc)
        bakta_annotation(storage_root, s, a, gffs[acc])
        with SessionLocal() as db:
            db.get(Sample, s["id"]).host = host
            db.commit()
        ids.append(a["id"])
        samples.append(s)
        labels[a["id"]] = acc
    first = client.get(f"{API}/assemblies/{ids[0]}").json()
    cset = client.post(f"{API}/comparisons", json={"project_id": first.get("project_id") or project_sample(
        client, "Pangenome home", "HOME")["project_id"], "name": "S. aureus pangenome", "assembly_ids": ids,
        "labels": labels}).json()
    url = f"{API}/comparisons/{cset['id']}/pangenome"
    plan = client.post(f"{url}/preview", json=body()).json()
    assert plan["problems"] == [] and plan["annotation_consistency"]["consistent"]
    job = client.post(url, json=body(confirmed=True)).json()
    assert job["job_type"] == "pangenome" and job["tool_name"] == "Panaroo"
    status = run_pangenome_job(job["id"])
    with SessionLocal() as db:
        done = db.get(AnalysisJob, job["id"])
        assert status == "completed", done.log_text[-3000:]
        argv = done.commands[0]
    assert argv[argv.index("--clean-mode") + 1] == "strict" and "input/g1.gff3" in argv
    (brief,) = [r for r in client.get(f"{API}/comparisons/{cset['id']}").json()["results"]
                if r["analysis"] == "pangenome"]
    r = client.get(f"{API}/comparisons/results/{brief['id']}").json()
    s, data = r["summary"], r["data"]
    assert s["genomes"] == 3 and s["families"] == len(data["families"])
    own = s["tool_summary"]
    assert {k: s["category_counts"][k] for k in ("core", "soft_core", "shell", "cloud")} == \
        {k: own[k] for k in ("core", "soft_core", "shell", "cloud")}
    assert [g["label"] for g in data["genomes"]] == [N315, MU50, MW2]
    assert data["curves"]["pan"]["mean"][-1] == s["families"] and data["curves"]["permutations"] == 20
    assert sum(d["families"] for d in data["distribution"]) == s["families"]
    assert "Jaccard" in data["clustering"]["method"]
    assert {w["code"] for w in r["warnings"]} >= {"pangenome_few_genomes"}
    assert "gene_presence_absence.Rtab" in " ".join(r["files"]) and "panaroo/gene_data.csv" in r["files"]
    # A core family with a named gene: members, sequences, ARVA features and neighbours.
    i = next(n for n, f in enumerate(data["families"]) if f["gene_names"] == ["dnaA"])
    fam = client.get(f"{API}/comparisons/results/{brief['id']}/families/{i}").json()
    assert fam["count"] == 3 and {m["genome"] for m in fam["members"]} == {N315, MU50, MW2}
    m0 = fam["members"][0]
    assert m0["protein"].startswith("M") and m0["dna_length"] > 1000 and m0["feature"]["gene"] == "dnaA"
    assert m0["feature"]["annotation_id"] and fam["neighbours"]
    fasta = client.get(f"{API}/comparisons/results/{brief['id']}/families/{i}.fasta",
                       params={"molecule": "protein"}).text
    assert fasta.count(">") == 3 and f"family={fam['name']}" in fasta
    assert client.get(f"{API}/comparisons/results/{brief['id']}/families/999999").status_code == 404
    rows = list(csv.reader(io.StringIO(client.get(f"{API}/comparisons/results/{brief['id']}/families.csv").text)))
    assert rows[0][:6] == ["family", "gene_names", "annotation", "genomes", "category", "tool_partition"]
    assert len(rows) == s["families"] + 1
    rtab = client.get(f"{API}/comparisons/results/{brief['id']}/pangenome/presence.Rtab").text
    assert rtab.splitlines()[0] == f"Gene\t{N315}\t{MU50}\t{MW2}"
    meta = client.get(f"{API}/comparisons/results/{brief['id']}/pangenome/metadata").json()
    host = next(f for f in meta["fields"] if f["key"] == "host")
    assert host["values"] == ["human", "human", "community"] and host["distinct"] == 2
    assoc = client.get(f"{API}/comparisons/results/{brief['id']}/pangenome/associations",
                       params={"field": "host", "min_group": 1}).json()
    assert assoc["small_sample"] and assoc["tests"] == 2 * assoc["families_tested"]
    assert all(row["q"] >= row["p"] for row in assoc["rows"])
    assert {g["group"] for g in assoc["groups"]} == {"human", "community"}
    assert client.get(f"{API}/comparisons/results/{brief['id']}/pangenome/associations",
                      params={"field": "nope"}).json()["code"] == "pangenome_field_unknown"
    html = client.get(f"{API}/comparisons/{cset['id']}/report.html").text
    assert "Pangenome · Panaroo" in html and "Accumulation curves" in html and "not a phylogeny" in html
    sample_report = client.get(f"{API}/samples/{samples[2]['id']}/report").text
    assert "Core families of the set" in sample_report and MW2 in sample_report
