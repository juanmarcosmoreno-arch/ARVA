"""Variant analysis and the consolidated mobilome: request checks, the preview, the migration, a real run of BWA-MEM +
samtools + bcftools (with csq) on SYNTHETIC reads against a SYNTHETIC draft with known errors
(scripts/make_synthetic_genome.py, scripts/make_polishing_draft.py: 7 substitutions, 4 insertions, 5 deletions in the
draft), a long-read run with minimap2, the SNP matrix across two samples, the exports and the explorer track. Real
runs skip without the tools."""
import gzip
import subprocess
import sys
from pathlib import Path

import pytest
from arva_core.annotation import new_feature, write_jsonl
from arva_core.assembly_stats import ContigAnnotation
from arva_tools import ToolStatus
from arva_tools.registry import detect

from app.db.session import SessionLocal
from app.models import (
    AmrResult,
    AnalysisJob,
    Annotation,
    AssemblyMode,
    JobStatus,
    MobileElementResult,
)
from app.services.assemblies import register_assembly
from app.tasks.common import run_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]


def ready(*tool_ids: str) -> bool:
    return all(detect(t, refresh=True).status is ToolStatus.available for t in tool_ids)


@pytest.fixture(scope="module")
def genome(tmp_path_factory):
    out = tmp_path_factory.mktemp("variants") / "genome"
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_synthetic_genome.py"), str(out), "--chromosome-length",
                    "100000", "--plasmid-length", "8000", "--repeat-length", "2000", "--ont-depth", "30",
                    "--illumina-depth", "40"], check=True, capture_output=True)
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_polishing_draft.py"), str(out / "reference.fasta"),
                    str(out)], check=True, capture_output=True)
    return out


def new_sample(client, project_id, code, technology="illumina"):
    return client.post(f"{API}/projects/{project_id}/samples",
                       json={"sample_code": code, "sequencing_technology": technology}).json()


def upload(client, sample_id, path: Path) -> str:
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]["id"]


def register(client, sample, fasta: Path, reads: list[str]) -> dict:
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="assembly_test",
                          tool_name="Flye", tool_version="2.9.3", parameters={}, input_raw_file_ids=reads,
                          status=JobStatus.pending, log_text="")
        db.add(job)
        db.commit()
        job_id = job.id

    def body(ctx):
        out = ctx.path(ctx.results_rel)
        out.mkdir(parents=True)
        (out / "assembly.fasta").write_bytes(fasta.read_bytes())
        register_assembly(ctx, assembler="Flye", mode=AssemblyMode.long, read_type="nano-hq",
                          contigs=out / "assembly.fasta",
                          annotations={n: ContigAnnotation(coverage=30.0, circular=True)
                                       for n in ("contig_1", "contig_2")})

    assert run_job(job_id, body) == "completed"
    (a,) = [a for a in client.get(f"{API}/samples/{sample['id']}/assemblies").json() if a["job_id"] == job_id]
    return a


def annotate(sample, assembly, storage_root, features) -> str:
    """A stand-in annotation of the draft: the given CDS features on its contigs."""
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="bakta_annotation",
                          tool_name="Bakta", tool_version="1.12.2", parameters={}, status=JobStatus.completed,
                          log_text="")
        db.add(job)
        db.commit()
        rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}"
        (storage_root / rel).mkdir(parents=True)
        write_jsonl(storage_root / rel / "features.jsonl", features)
        a = Annotation(sample_id=sample["id"], assembly_id=assembly["id"], job_id=job.id, tool="Bakta",
                       tool_version="1.12.2", parameters={}, steps={"cds": {"status": "searched"}}, summary={},
                       sequences=[{"id": "contig_1", "length": 100000}, {"id": "contig_2", "length": 8000}],
                       files={}, features_path=f"{rel}/features.jsonl")
        db.add(a)
        db.commit()
        return a.id


@pytest.fixture
def setup(client, genome):
    p = client.post(f"{API}/projects", json={"name": "Variants"}).json()
    ref_sample = new_sample(client, p["id"], "REF", "nanopore")
    draft = register(client, ref_sample, genome / "draft.fasta", [upload(client, ref_sample["id"],
                                                                         genome / "ont.fastq.gz")])
    s1 = new_sample(client, p["id"], "S1")
    ids = {"r1": upload(client, s1["id"], genome / "illumina_R1.fastq.gz"),
           "r2": upload(client, s1["id"], genome / "illumina_R2.fastq.gz"),
           "long": upload(client, s1["id"], genome / "ont.fastq.gz")}
    return p, ref_sample, draft, s1, ids


def body(draft, inputs, technology="illumina", **extra):
    return {"technology": technology, "reference": {"kind": "assembly", "assembly_id": draft["id"]},
            "inputs": inputs, "threads": 2, **extra}


def test_request_checks_and_preview(client, setup):
    _, _, draft, s1, ids = setup
    url = f"{API}/samples/{s1['id']}/variants"
    r = client.post(url, json=body(draft, {"r1": ids["r1"], "r2": ids["r2"]}))
    assert r.status_code == 400 and r.json()["code"] == "variants_confirm"
    r = client.post(f"{url}/preview", json=body(draft, {"r1": ids["r1"]}))
    assert r.status_code == 400 and r.json()["code"] == "variants_reads_short"
    r = client.post(f"{url}/preview", json=body(draft, {"r1": ids["r1"], "r2": ids["r2"]}, technology="ont"))
    assert r.json()["code"] == "variants_reads_long"
    r = client.post(f"{url}/preview", json={**body(draft, {"long": ids["long"]}, technology="ont"),
                                            "reference": {"kind": "assembly", "assembly_id": "nope"}})
    assert r.json()["code"] == "variants_reference_missing"
    r = client.post(f"{url}/preview", json={**body(draft, {"long": ids["long"]}, technology="ont"),
                                            "reference": {"kind": "collection", "database_id": "x", "genome_key": "y"}})
    assert r.json()["code"] == "variants_no_collection"
    r = client.post(f"{url}/preview", json=body(draft, {"r1": ids["r1"], "r2": ids["r2"]},
                                                settings={"min_alt_fraction": 2}))
    assert r.status_code == 422
    plan = client.post(f"{url}/preview", json=body(draft, {"long": ids["long"]}, technology="ont")).json()
    assert plan["aligner"] == {"tool": "minimap2", "preset": "map-ont"}
    assert plan["settings"]["mpileup"]["baq"] == "off" and plan["settings"]["call_indels"] is False
    assert plan["reference"]["sha256"] and [c["name"] for c in plan["reference"]["contigs"]] == ["contig_1", "contig_2"]
    codes = {n["code"] for n in plan["notes"]}
    assert {"technology_differs", "no_indels", "no_effects"} <= codes
    assert plan["read_group_sample"] == "S1"
    opts = client.get(f"{url}/options").json()
    assert opts["suggested_technology"] == "illumina"
    assert opts["assemblies"][0]["assembly_id"] == draft["id"] and opts["assemblies"][0]["same_project"]
    assert opts["defaults"]["filters"] == {"min_mapq": 60, "min_qual": 100.0, "min_depth": 10, "min_alt_fraction": 0.9}


@pytest.mark.skipif(not ready("bwa", "samtools", "bcftools", "minimap2"), reason="needs BWA, minimap2, samtools, bcftools")
def test_short_and_long_reads_find_the_draft_errors_with_effects_matrix_and_exports(client, setup, genome,
                                                                                     storage_root):
    p, ref_sample, draft, s1, ids = setup
    cds = new_feature(id=1, type="cds", contig="contig_1", start=4501, end=5700, strand="+", locus_tag="DRAFT_1",
                      gene="geneX", product="test protein")
    annotation_id = annotate(ref_sample, draft, storage_root, [cds])
    r = client.post(f"{API}/samples/{s1['id']}/variants",
                    json={**body(draft, {"r1": ids["r1"], "r2": ids["r2"]}), "confirmed": True})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"][-3000:]
    assert job["tool_name"] == "BCFtools"
    commands = [c[1] if Path(c[0]).name == "bcftools" else Path(c[0]).name for c in job["commands"]]
    assert commands[:1] == ["samtools"] and "csq" in commands and commands[-1] == "index"
    mem = next(c for c in job["commands"] if c[1:2] == ["mem"])
    assert mem[mem.index("-R") + 1] == f"@RG\\tID:{job['id'][:8]}\\tSM:S1"
    (run,) = client.get(f"{API}/samples/{s1['id']}/variants").json()
    s = run["summary"]
    # The reads come from the true genome: the draft's substitutions are SNPs, its insertions are deletions in the
    # reads and its deletions insertions (scripts/make_polishing_draft.py).
    # Two indels at short tandem repeats keep part of the reads on the reference allele and fail LowAltFraction.
    assert s["by_type"]["snp"] == 7 and s["records"] == 16 and s["pass"] >= 14, s
    every = client.get(f"{API}/variants/runs/{run['id']}/records").json()["variants"]
    assert sum(v["type"] == "deletion" for v in every) == 4 and sum(v["type"] == "insertion" for v in every) == 5
    assert set(s["by_filter"]) <= {"LowAltFraction"}
    assert s["csq_features"]["written"] == 1 and s["callable_percent"] > 90
    assert s["alignment"]["mapped_percent"] > 95
    recs = client.get(f"{API}/variants/runs/{run['id']}/records", params={"status": "pass", "type": "snp"}).json()
    assert recs["total"] == 7 and all(v["genotype"] == "1" for v in recs["variants"])
    in_gene = [v for v in recs["variants"] if v["contig"] == "contig_1" and 4501 <= v["pos"] <= 5700]
    assert len(in_gene) == 1 and in_gene[0]["effect"] in ("missense", "synonymous", "stop_gained")
    assert in_gene[0]["consequences"][0]["gene"] == "geneX"
    csv_text = client.get(f"{API}/variants/runs/{run['id']}/variants.csv").text
    assert csv_text.splitlines()[0].startswith("contig,pos,ref,alt,type,qual,filter")
    vcf = client.get(f"{API}/variants/runs/{run['id']}/files/vcf")
    assert vcf.status_code == 200 and gzip.decompress(vcf.content).startswith(b"##fileformat=VCF")
    assert client.get(f"{API}/variants/runs/{run['id']}/files/bam").status_code == 404
    track = client.get(f"{API}/annotations/{annotation_id}/variants",
                       params={"contig": "contig_1", "start": 4000, "end": 6000}).json()
    assert track["run_id"] == run["id"] and len(track["variants"]) == 1

    s2 = new_sample(client, p["id"], "S2", "nanopore")
    long_id = upload(client, s2["id"], genome / "ont.fastq.gz")
    r = client.post(f"{API}/samples/{s2['id']}/variants",
                    json={**body(draft, {"long": long_id}, technology="ont"), "confirmed": True, "effects": False,
                          "keep_alignment": True})
    job2 = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job2["status"] == "completed", job2["log_text"][-3000:]
    (run2,) = client.get(f"{API}/samples/{s2['id']}/variants").json()
    # Simulated Nanopore-like reads: the seven SNPs are called; one has 24 of 27 reads (0.89) on the alternative
    # base and fails LowAltFraction. Indels are not called with the Nanopore profile (-I).
    ont = client.get(f"{API}/variants/runs/{run2['id']}/records").json()["variants"]
    assert len(ont) == 7 and all(v["type"] == "snp" for v in ont)
    assert run2["summary"]["by_type"]["snp"] >= 6 and set(run2["summary"]["by_filter"]) <= {"LowAltFraction"}
    assert run2["summary"]["csq_features"] is None and {"bam", "bam_index"} <= set(run2["files"])
    overview = client.get(f"{API}/projects/{p['id']}/variants").json()
    (group,) = overview["references"]
    assert [r["sample_code"] for r in group["runs"]] == ["S1", "S2"]
    m = client.get(f"{API}/projects/{p['id']}/variants/matrix", params={"reference": group["reference_sha256"]}).json()
    assert len(m["sites"]) == 7 and m["distances"][0][1] == 0 and m["compared_sites"][0][1] >= 6
    dist = client.get(f"{API}/projects/{p['id']}/variants/matrix",
                      params={"reference": group["reference_sha256"], "format": "distances"}).text
    assert dist.splitlines()[0] == ",S1,S2"
    fasta = client.get(f"{API}/projects/{p['id']}/variants/matrix",
                       params={"reference": group["reference_sha256"], "format": "fasta"}).text
    assert fasta.startswith(">S1\n") and len(fasta.splitlines()[1]) == 7
    report = client.get(f"{API}/samples/{s1['id']}/report").text
    assert "<h2>Variants</h2>" in report and "bcftools csq" in report and "Snippy 4.6.0" in report
    assert client.get(f"{API}/samples/{s1['id']}/report", params={"format": "json"}).json()["variants"]["runs"]
    page = client.get(f"{API}/projects/{p['id']}/variants/report.html").text
    assert "Pairwise SNP distances" in page and "Not a phylogeny" in page


def test_matrix_needs_two_samples_against_one_reference(client, setup):
    p, *_ = setup
    r = client.get(f"{API}/projects/{p['id']}/variants/matrix", params={"reference": "a" * 64})
    assert r.status_code == 400 and r.json()["code"] == "variants_matrix_too_few"
    assert client.get(f"{API}/projects/{p['id']}/variants").json()["references"] == []


def test_mobilome_places_genes_on_plasmids_inside_and_near_elements(client, setup):
    _, ref_sample, draft, *_ = setup
    with SessionLocal() as db:
        jobs = {}
        for method in ("mobsuite", "isescan"):
            job = AnalysisJob(project_id=ref_sample["project_id"], sample_id=ref_sample["id"],
                              job_type="mobile_elements", tool_name=method, tool_version="x",
                              parameters={"method": method, "assembly": {"assembly_id": draft["id"]}},
                              status=JobStatus.completed, log_text="")
            db.add(job)
            db.flush()
            jobs[method] = job.id
        amr_job = AnalysisJob(project_id=ref_sample["project_id"], sample_id=ref_sample["id"], job_type="amr_detection",
                              tool_name="AMRFinderPlus", tool_version="4", parameters={}, status=JobStatus.completed,
                              log_text="")
        db.add(amr_job)
        db.flush()

        def mob(**kw):
            db.add(MobileElementResult(sample_id=ref_sample["id"], assembly_id=draft["id"], **kw))

        mob(job_id=jobs["mobsuite"], tool="mobsuite", category="contig", element="contig_2", element_type="plasmid",
            contig="contig_2", start=1, end=8000, details={"primary_cluster_id": "AA001"})
        mob(job_id=jobs["mobsuite"], tool="mobsuite", category="contig", element="contig_1",
            element_type="chromosome", contig="contig_1", start=1, end=100000, details={})
        mob(job_id=jobs["mobsuite"], tool="mobsuite", category="plasmid", element="AA001", element_type="mobilizable",
            details={"contigs": ["contig_2"], "rep_type(s)": ["rep_cluster_1"], "size": 8000})
        mob(job_id=jobs["isescan"], tool="isescan", category="insertion_sequence", element="IS21_1",
            element_type="IS21", contig="contig_1", start=20000, end=21500, strand="+", completeness="complete")

        def amr(gene, contig, start, stop, kind="AMR"):
            db.add(AmrResult(sample_id=ref_sample["id"], assembly_id=draft["id"], job_id=amr_job.id,
                             element_symbol=gene, type=kind, method="EXACTX", method_kind="exact", contig=contig,
                             assembly_contig=contig, start=start, stop=stop, strand="+"))

        amr("blaZ", "contig_2", 1000, 1800)
        amr("inside", "contig_1", 20500, 20900)
        amr("near", "contig_1", 25000, 25600)
        amr("far", "contig_1", 60000, 60600)
        db.commit()
    m = client.get(f"{API}/samples/{ref_sample['id']}/mobilome").json()
    (a,) = m["assemblies"]
    (plasmid,) = a["plasmids"]
    assert plasmid["id"] == "AA001" and [g["gene"] for g in plasmid["genes"]] == ["blaZ"]
    (element,) = a["elements"]
    placed = {g["gene"]: (g["relation"], g["distance"]) for g in element["genes"]}
    assert placed == {"inside": ("inside", 0), "near": ("near", 3500)}
    assert a["counts"]["amr_on_plasmids"] == 1 and a["counts"]["genes_with_elements"] == 2
    narrow = client.get(f"{API}/samples/{ref_sample['id']}/mobilome", params={"window": 1000}).json()
    assert [g["gene"] for g in narrow["assemblies"][0]["elements"][0]["genes"]] == ["inside"]
    project = client.get(f"{API}/projects/{ref_sample['project_id']}/mobilome").json()
    row = next(r for r in project["samples"] if r["sample_code"] == "REF")
    assert row["plasmid_genes"] == ["blaZ"] and row["element_genes"] == ["inside"]
    assert row["replicon_types"] == ["rep_cluster_1"]
