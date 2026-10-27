import csv
import gzip
import io
import json
import stat

import pytest

API = "/api/v1"

FASTQ = (
    "@r1\nACGT\n+\nIIII\n"
    "@r2\nGGGCCC\n+\n555555\n"
    "@r3\nAAAAATTTTT\n+\n++++++++++\n"
)


def make_project(client, name="Staphylococcus survey"):
    r = client.post(f"{API}/projects", json={"name": name, "institution": "Test Lab"})
    assert r.status_code == 201, r.text
    return r.json()


def make_sample(client, project_id, code="SA-001", **extra):
    body = {"sample_code": code, "organism": "Staphylococcus aureus",
            "sequencing_technology": "nanopore", **extra}
    r = client.post(f"{API}/projects/{project_id}/samples", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, sample_id, name, content: bytes):
    return client.post(
        f"{API}/samples/{sample_id}/files",
        files=[("files", (name, io.BytesIO(content), "application/octet-stream"))],
    )


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_project_crud(client):
    p = make_project(client)
    assert p["sample_count"] == 0 and p["is_demo"] is False
    r = client.patch(f"{API}/projects/{p['id']}", json={"description": "Hospital isolates"})
    assert r.json()["description"] == "Hospital isolates"
    assert [x["id"] for x in client.get(f"{API}/projects").json()] == [p["id"]]
    assert client.delete(f"{API}/projects/{p['id']}").status_code == 204
    assert client.get(f"{API}/projects/{p['id']}").status_code == 404


def test_project_validation(client):
    assert client.post(f"{API}/projects", json={"name": ""}).status_code == 422


def test_sample_crud_and_unique_code(client):
    p = make_project(client)
    s = make_sample(client, p["id"], collection_date="2024-03-15", host="Homo sapiens")
    assert s["collection_date"] == "2024-03-15"
    dup = client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "SA-001"})
    assert dup.status_code == 409
    assert client.get(f"{API}/projects/{p['id']}").json()["sample_count"] == 1
    r = client.patch(f"{API}/samples/{s['id']}", json={"notes": "MRSA suspected"})
    assert r.json()["notes"] == "MRSA suspected"


def test_upload_validate_and_analyse_fastq(client, storage_root):
    p = make_project(client)
    s = make_sample(client, p["id"])

    r = upload(client, s["id"], "SA-001_R1_001.fastq.gz", gzip.compress(FASTQ.encode()))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rejected"] == []
    f = body["files"][0]
    assert f["file_format"] == "fastq_gz"
    assert f["read_mate"] == "R1"
    assert f["is_valid"] is True
    assert len(f["checksum_sha256"]) == 64

    stored = next((storage_root / "raw").rglob(f"{f['id']}__*"))
    assert not stored.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)

    r = client.post(
        f"{API}/samples/{s['id']}/analyses/sequence-stats",
        json={"expected_genome_size_bp": 10},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()[0]["id"]

    job = client.get(f"{API}/jobs/{job_id}").json()
    assert job["status"] == "completed", job["log_text"]
    assert job["tool_name"] == "arva-core.seqstats"
    assert job["parameters"]["expected_genome_size_bp"] == 10
    assert job["input_raw_file_ids"] == [f["id"]]
    assert job["duration_seconds"] is not None
    assert f["checksum_sha256"] in job["log_text"]
    qc = job["qc_results"][0]
    assert qc["read_count"] == 3 and qc["total_bases"] == 20 and qc["n50"] == 10
    assert qc["gc_percent"] == pytest.approx(40.0)
    assert qc["metrics"]["coverage_estimate"]["estimated_depth"] == pytest.approx(2.0)

    result_path = storage_root / job["output_paths"][0]
    assert json.loads(result_path.read_text())["read_count"] == 3
    assert (storage_root / "logs" / f"{job_id}.log").exists()

    history = client.get(f"{API}/samples/{s['id']}/jobs").json()
    assert [j["id"] for j in history] == [job_id]

    dash = client.get(f"{API}/dashboard").json()
    assert dash["project_count"] == 1 and dash["raw_file_count"] == 1
    assert dash["jobs_completed"] == 1


def test_duplicate_upload_rejected(client):
    p = make_project(client)
    s = make_sample(client, p["id"])
    assert upload(client, s["id"], "a.fastq", FASTQ.encode()).json()["rejected"] == []
    second = upload(client, s["id"], "copy.fastq", FASTQ.encode()).json()
    assert second["files"] == []
    assert "already registered" in second["rejected"][0]["reason"]


def test_invalid_file_marked_and_excluded(client):
    p = make_project(client)
    s = make_sample(client, p["id"])
    f = upload(client, s["id"], "notes.txt", b"just some text\n").json()["files"][0]
    assert f["file_format"] == "unknown" and f["is_valid"] is False
    r = client.post(f"{API}/samples/{s['id']}/analyses/sequence-stats", json={})
    assert r.status_code == 400


def test_corrupt_record_fails_job_with_line_number(client):
    p = make_project(client)
    s = make_sample(client, p["id"])
    bad = FASTQ + "@r4\nACGT\n+\nII\n"
    f = upload(client, s["id"], "bad.fastq", bad.encode()).json()["files"][0]
    assert f["is_valid"] is False and "line 16" in f["validation_message"]
    job = client.post(f"{API}/samples/{s['id']}/analyses/sequence-stats", json={}).json()[0]
    detail = client.get(f"{API}/jobs/{job['id']}").json()
    assert detail["status"] == "failed"
    assert "line 16" in detail["error_message"]
    assert detail["qc_results"] == []


def test_files_must_belong_to_sample(client):
    p = make_project(client)
    s1 = make_sample(client, p["id"], "S1")
    s2 = make_sample(client, p["id"], "S2")
    f = upload(client, s1["id"], "a.fastq", FASTQ.encode()).json()["files"][0]
    r = client.post(
        f"{API}/samples/{s2['id']}/analyses/sequence-stats", json={"raw_file_ids": [f["id"]]}
    )
    assert r.status_code == 400


def test_filename_cannot_escape_storage(client, storage_root):
    p = make_project(client)
    s = make_sample(client, p["id"])
    f = upload(client, s["id"], "../../../etc/evil.fastq", FASTQ.encode()).json()["files"][0]
    assert f["original_filename"] == "../../../etc/evil.fastq"
    stored = list((storage_root / "raw").rglob(f"{f['id']}__*"))
    assert len(stored) == 1 and stored[0].name.endswith("__evil.fastq")


@pytest.mark.parametrize("fmt, marker", [("html", "<!doctype html>"), ("json", '"report_type"'),
                                         ("csv", "sample_code,filename")])
def test_reports(client, fmt, marker):
    p = make_project(client)
    s = make_sample(client, p["id"])
    upload(client, s["id"], "reads.fastq", FASTQ.encode())
    client.post(f"{API}/samples/{s['id']}/analyses/sequence-stats", json={})
    r = client.get(f"{API}/samples/{s['id']}/report", params={"format": fmt})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert marker in r.text
    if fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert rows[0]["reads"] == "3" and rows[0]["n50"] == "10"
    if fmt == "json":
        assert r.json()["files"][0]["metrics"]["read_count"] == 3


def test_html_report_escapes_user_input(client):
    p = make_project(client, name="<script>alert(1)</script>")
    s = make_sample(client, p["id"], code="<img src=x>")
    r = client.get(f"{API}/samples/{s['id']}/report")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
