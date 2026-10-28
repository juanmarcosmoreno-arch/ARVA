"""Chart data endpoints for FastQC and fastp jobs, and their summaries in the sample report.

Job records with outputs copied from the tool-adapter fixtures (real FastQC 0.12.1 / fastp 0.23.4 runs on
examples/synthetic) test the endpoints without the tools; the end-to-end tests need FastQC or fastp.
"""
import datetime as dt
import io
import shutil
import zipfile
from pathlib import Path

import pytest

from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus
from app.storage import get_storage

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures"
TOOL = {"fastqc": "FastQC", "fastp": "fastp"}


def needs(tool):
    return pytest.mark.skipif(shutil.which(tool) is None, reason=f"{tool} is not installed")


@pytest.fixture
def sample(client):
    p = client.post(f"{API}/projects", json={"name": "QC data"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "Q1"}).json()


def upload(client, sample_id, *paths):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    r = client.post(f"{API}/samples/{sample_id}/files", files=files)
    assert r.status_code == 201, r.text
    return r.json()["files"]


def add_job(sample, job_type, outputs: dict[str, bytes], status=JobStatus.completed, extra_paths=(), params=None,
            summary=None):
    """A tool job whose named outputs are written into its own results folder."""
    with SessionLocal() as db:
        job = AnalysisJob(
            project_id=sample["project_id"], sample_id=sample["id"], job_type=job_type, tool_name=TOOL[job_type],
            tool_version="test", parameters=params or {}, input_raw_file_ids=[], status=status, log_text="",
            finished_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), result_summary=summary,
        )
        db.add(job)
        db.flush()
        paths = []
        for name, content in outputs.items():
            rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}/{name}"
            target = get_storage().resolve(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            paths.append(rel)
        job.output_paths = [*paths, *extra_paths]
        db.commit()
        return job.id


def fastqc_zip(stem: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name in ("fastqc_data", "summary"):
            z.writestr(f"{stem}_fastqc/{name}.txt", (FIXTURES / "fastqc" / f"{stem}_{name}.txt").read_text())
    return buffer.getvalue()


def test_older_fastqc_jobs_are_parsed_from_their_zip(client, sample):
    # The result summary FastQC jobs stored before the chart data existed.
    summary = {"fastqc_version": "0.12.1", "modules": [{"status": "PASS", "module": "Adapter Content"}],
               "basic_statistics": {"Total Sequences": "400"}}
    job_id = add_job(sample, "fastqc", {"SYNTHETIC_nanopore_reads_fastqc.zip": fastqc_zip("SYNTHETIC_nanopore_reads")},
                     summary=summary)
    r = client.get(f"{API}/jobs/{job_id}/fastqc-data")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "SYNTHETIC_nanopore_reads_fastqc.zip" and data["max_read_length"] == 26593
    over = data["overrepresented_sequences"]
    assert over["every_read_listed"] and over["total"] == 400 and len(over["rows"]) == 20
    assert data["adapter_content"]["positions"][9] == {"label": "10-499", "start": 10, "end": 499}
    assert [b["level"] for b in data["duplication"]["bins"]][-1] == ">10k+"

    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert "Adapter content (FastQC, cumulative % of reads; FastQC heuristics: PASS): no adapter sequence" in html
    assert "100.00 % of reads would remain if deduplicated (0.00 % duplicates)" in html


def test_fastqc_data_is_only_read_from_the_jobs_own_outputs(client, sample, storage_root):
    outside = "results/elsewhere/x_fastqc.zip"
    (storage_root / outside).parent.mkdir(parents=True, exist_ok=True)
    (storage_root / outside).write_bytes(fastqc_zip("SYNTHETIC_illumina_R1_001"))
    job_id = add_job(sample, "fastqc", {}, extra_paths=[outside, "../../../etc/passwd_fastqc.zip"])
    r = client.get(f"{API}/jobs/{job_id}/fastqc-data")
    assert r.status_code == 404 and "no stored data file" in r.json()["detail"]


def test_fastqc_data_errors(client, sample):
    broken = add_job(sample, "fastqc", {"x_fastqc.zip": b"PK\x03\x04 not a zip"})
    r = client.get(f"{API}/jobs/{broken}/fastqc-data")
    assert r.status_code == 422 and "could not be opened" in r.json()["detail"]
    running = add_job(sample, "fastqc", {}, status=JobStatus.running)
    assert client.get(f"{API}/jobs/{running}/fastqc-data").status_code == 409
    fastp = add_job(sample, "fastp", {"fastp.json": (FIXTURES / "fastp" / "SYNTHETIC_illumina_R1_SE.fastp.json").read_bytes()})
    assert client.get(f"{API}/jobs/{fastp}/fastqc-data").status_code == 404
    assert client.get(f"{API}/jobs/{broken}/fastp-data").status_code == 404
    assert client.get(f"{API}/jobs/00000000-0000-0000-0000-000000000000/fastqc-data").status_code == 404


def test_fastp_data_paired_and_single_end(client, sample):
    pe = add_job(sample, "fastp", {"fastp.json": (FIXTURES / "fastp" / "SYNTHETIC_illumina_PE.fastp.json").read_bytes()},
                 params={"threads": 3})
    data = client.get(f"{API}/jobs/{pe}/fastp-data").json()
    assert data["threads"] == 3 and set(data["reads"]) == {"read1", "read2"}
    assert data["reads"]["read1"]["after"]["total_cycles"] == 150
    assert len(data["reads"]["read2"]["before"]["quality"]["mean"]) == 150
    ins = data["insert_size"]
    assert ins["peak"] == 72 and ins["evaluated_pairs"] == 1000 and ins["unknown_percent"] == pytest.approx(92.3)
    assert data["adapter_cutting"]["read2_adapter_counts"][-1] == {"sequence": "others", "count": 137}
    assert data["duplication_rate"] == 0

    se = add_job(sample, "fastp", {"fastp.json": (FIXTURES / "fastp" / "SYNTHETIC_illumina_R1_SE.fastp.json").read_bytes()})
    data = client.get(f"{API}/jobs/{se}/fastp-data").json()
    assert data["adapter_cutting"] is None and data["insert_size"] is None and data["threads"] is None
    assert list(data["reads"]) == ["read1"]

    broken = add_job(sample, "fastp", {"fastp.json": b"{not json"})
    assert client.get(f"{API}/jobs/{broken}/fastp-data").status_code == 422
    missing = add_job(sample, "fastp", {})
    assert client.get(f"{API}/jobs/{missing}/fastp-data").status_code == 404


@needs("fastqc")
def test_fastqc_job_stores_chart_data(client, sample):
    (f,) = upload(client, sample["id"], R1)
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/fastqc", json={"raw_file_ids": [f["id"]]}).json()
    job = client.get(f"{API}/jobs/{j['id']}").json()
    assert job["status"] == "completed", job["log_text"]
    assert any(p.endswith("/fastqc_data.json") for p in job["output_paths"])
    compact = job["result_summary"]["data_summary"]
    assert compact["adapter_content"]["status"] == "WARN" and compact["duplication"]["duplicate_percent"] == 0
    assert compact["adapter_content"]["adapters"][0]["max_percent"] == 7.4

    data = client.get(f"{API}/jobs/{j['id']}/fastqc-data").json()
    assert data["source"] == "fastqc_data.json"
    assert data["adapter_content"]["positions"][-1]["label"] == "138-139"
    assert data["overrepresented_sequences"]["rows"] == [] and len(data["duplication"]["bins"]) == 16

    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert "Illumina Universal Adapter up to 7.40 % (first at position 122-123)" in html
    assert "first 100,000 reads, reads longer than 50 bp truncated to 50 bp; FastQC heuristics: PASS" in html

    # A job from before fastqc_data.json existed: the zip is parsed on request, for the API and the report.
    with SessionLocal() as db:
        row = db.get(AnalysisJob, j["id"])
        row.output_paths = [p for p in row.output_paths if not p.endswith(".json")]
        row.result_summary = {k: v for k, v in row.result_summary.items() if k != "data_summary"}
        db.commit()
    legacy = client.get(f"{API}/jobs/{j['id']}/fastqc-data").json()
    assert legacy.pop("source") == "SYNTHETIC_illumina_R1_001_fastqc.zip"
    data.pop("source")
    assert legacy == data
    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert "Illumina Universal Adapter up to 7.40 %" in html


@needs("fastp")
def test_fastp_job_chart_data(client, sample):
    f1, f2 = upload(client, sample["id"], R1, R2)
    r = client.post(f"{API}/samples/{sample['id']}/filtering/fastp",
                    json={"read1_file_id": f1["id"], "read2_file_id": f2["id"], "params": {}})
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"]
    data = client.get(f"{API}/jobs/{job['id']}/fastp-data").json()
    assert data["threads"] == job["parameters"]["threads"]
    assert data["adapter_cutting"]["adapter_trimmed_reads"] == job["result_summary"]["adapter_trimmed_reads"]
    assert data["insert_size"]["peak"] == job["result_summary"]["insert_size_peak"]
    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert "Duplication rate (fastp estimate): 0.00 %" in html and "bases removed)" in html
