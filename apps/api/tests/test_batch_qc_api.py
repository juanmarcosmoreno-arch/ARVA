"""Batch QC over a project: the plan's per-sample counts and reasons, and creating exactly the planned jobs."""
from pathlib import Path

from app.db.session import SessionLocal
from app.models import AnalysisJob, FileOrigin, JobStatus, RawFile

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
POD5 = EXAMPLES / "SYNTHETIC_nanopore_signal.pod5"
ALL = ["sequence_stats", "seqkit", "fastqc"]


def upload(client, sample_id, path: Path):
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def project(client, tmp_path):
    """Sample A: long reads, a POD5 file and a FASTA; sample B: a read pair and one derived (filtered) file."""
    p = client.post(f"{API}/projects", json={"name": "Batch"}).json()
    a = client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "A", "sequencing_technology": "nanopore"}).json()
    b = client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "B", "sequencing_technology": "illumina"}).json()
    fasta = tmp_path / "contigs.fasta"
    fasta.write_text(">c1\nACGTACGTAC\n")
    files = {"ont": upload(client, a["id"], ONT), "pod5": upload(client, a["id"], POD5),
             "fasta": upload(client, a["id"], fasta), "r1": upload(client, b["id"], R1), "r2": upload(client, b["id"], R2)}
    with SessionLocal() as db:
        parent = db.get(RawFile, files["r1"]["id"])
        derived = RawFile(sample_id=b["id"], original_filename="R1.filtered.fastq.gz", stored_path=parent.stored_path,
                          file_format=parent.file_format, read_mate="R1", size_bytes=parent.size_bytes,
                          checksum_sha256=parent.checksum_sha256, is_valid=True, origin=FileOrigin.derived,
                          parent_file_id=parent.id)
        db.add(derived)
        db.commit()
        files["derived"] = {"id": derived.id}
    return p, a, b, files


def batch(client, project_id, **body):
    return client.post(f"{API}/projects/{project_id}/analyses/batch", json={"analyses": ALL, **body})


def decisions(plan, file_id):
    return next(f["decisions"] for s in plan["samples"] for f in s["files"] if f["file_id"] == file_id)


def test_the_preview_counts_jobs_per_sample_and_says_why_files_are_skipped(client, tmp_path):
    p, a, b, files = project(client, tmp_path)
    r = batch(client, p["id"])
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["dry_run"] is True and plan["created_job_ids"] == []
    by_code = {s["sample_code"]: s for s in plan["samples"]}
    assert by_code["A"]["jobs"] == {"sequence_stats": 2, "seqkit": 2, "fastqc": 1} and by_code["A"]["total"] == 5
    assert by_code["B"]["jobs"] == {"sequence_stats": 2, "seqkit": 2, "fastqc": 2} and by_code["B"]["total"] == 6
    assert plan["totals"] == {"sequence_stats": 4, "seqkit": 4, "fastqc": 3} and plan["total_jobs"] == 11
    assert plan["samples_with_jobs"] == 2
    assert decisions(plan, files["pod5"]["id"]) == dict.fromkeys(ALL, "raw_signal")
    assert decisions(plan, files["fasta"]["id"]) == {"sequence_stats": "run", "seqkit": "run", "fastqc": "not_fastq"}
    assert decisions(plan, files["derived"]["id"]) == dict.fromkeys(ALL, "derived_excluded")
    tools = {t["analysis"]: t for t in plan["tools"]}
    assert tools["sequence_stats"]["available"] and tools["sequence_stats"]["tool"] == "arva-core.seqstats"

    assert batch(client, p["id"]).json()["plan_id"] == plan["plan_id"]
    wider = batch(client, p["id"], include_derived=True).json()
    assert wider["total_jobs"] == 14 and wider["plan_id"] != plan["plan_id"]
    assert decisions(wider, files["derived"]["id"]) == dict.fromkeys(ALL, "run")

    only_b = batch(client, p["id"], sample_ids=[b["id"]], analyses=["fastqc"]).json()
    assert [s["sample_code"] for s in only_b["samples"]] == ["B"] and only_b["total_jobs"] == 2
    other = client.post(f"{API}/projects", json={"name": "Other"}).json()
    r = batch(client, other["id"], sample_ids=[a["id"]])
    assert r.status_code == 400 and "does not belong to this project" in r.json()["detail"]
    assert batch(client, p["id"], analyses=["seqkit", "seqkit"]).status_code == 422
    assert batch(client, p["id"], analyses=["nanoplot"]).status_code == 422


def test_confirming_creates_exactly_the_planned_jobs(client, tmp_path, held_queue):
    p, _, _, files = project(client, tmp_path)
    plan = batch(client, p["id"]).json()
    r = batch(client, p["id"], dry_run=False)
    assert r.status_code == 422 and "plan_id is required" in r.text
    r = batch(client, p["id"], dry_run=False, plan_id="0" * 32)
    assert r.status_code == 409 and r.json()["detail"]["plan"]["plan_id"] == plan["plan_id"]

    r = batch(client, p["id"], dry_run=False, plan_id=plan["plan_id"])
    assert r.status_code == 202, r.text
    created = r.json()["created_job_ids"]
    assert len(created) == 11 and held_queue.count == 11
    with SessionLocal() as db:
        jobs = [db.get(AnalysisJob, i) for i in created]
        pairs = sorted((j.job_type, j.sample_id, j.input_raw_file_ids[0]) for j in jobs)
        assert all(j.status is JobStatus.pending and len(j.input_raw_file_ids) == 1 for j in jobs)
        stats = next(j for j in jobs if j.job_type == "sequence_stats")
        assert stats.parameters["length_bins"] == 50 and stats.parameters["expected_genome_size_bp"] is None
    job_types = {"sequence_stats": "sequence_stats", "seqkit": "seqkit_stats", "fastqc": "fastqc"}
    planned = sorted((job_types[analysis], s["sample_id"], f["file_id"]) for s in plan["samples"] for f in s["files"]
                     for analysis, decision in f["decisions"].items() if decision == "run")
    assert pairs == planned

    # Queued work is never planned twice, even with recompute.
    again = batch(client, p["id"], recompute=True).json()
    assert again["total_jobs"] == 0 and decisions(again, files["ont"]["id"]) == dict.fromkeys(ALL, "active")


def test_completed_results_are_skipped_unless_recompute(client, tmp_path, monkeypatch):
    p, a, b, files = project(client, tmp_path)
    r = client.post(f"{API}/samples/{a['id']}/analyses/sequence-stats", json={"raw_file_ids": [files["ont"]["id"]]})
    assert r.json()[0]["status"] == "completed"
    with SessionLocal() as db:
        db.add(AnalysisJob(project_id=p["id"], sample_id=b["id"], job_type="sequence_stats", tool_name="arva-core",
                           tool_version="1", parameters={}, input_raw_file_ids=[files["r1"]["id"]],
                           status=JobStatus.cancelled, log_text=""))
        db.commit()
    plan = batch(client, p["id"], analyses=["sequence_stats"]).json()
    assert decisions(plan, files["ont"]["id"]) == {"sequence_stats": "completed"}
    assert decisions(plan, files["r1"]["id"]) == {"sequence_stats": "run"}
    assert plan["totals"] == {"sequence_stats": 3}
    redo = batch(client, p["id"], analyses=["sequence_stats"], recompute=True).json()
    assert decisions(redo, files["ont"]["id"]) == {"sequence_stats": "run"} and redo["total_jobs"] == 4

    monkeypatch.setenv("ARVA_TOOL_FASTQC", str(tmp_path / "missing"))
    from arva_tools.registry import _CACHE

    _CACHE.pop("fastqc", None)
    plan = batch(client, p["id"], analyses=["fastqc"]).json()
    assert plan["tools"][0]["available"] is False
    r = batch(client, p["id"], analyses=["fastqc"], dry_run=False, plan_id=plan["plan_id"])
    assert r.status_code == 409 and "FastQC is not available" in r.json()["detail"]
