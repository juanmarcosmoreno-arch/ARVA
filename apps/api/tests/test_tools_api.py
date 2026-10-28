"""API tests for external tools (SeqKit, FastQC, fastp, Filtlong).

Tests that need a tool are skipped when it is not installed.
"""
import gzip
import shutil
from pathlib import Path

import pytest

from app.storage import get_storage
from app.storage.local import StoragePathError

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"


def needs(*tools):
    missing = [t for t in tools if shutil.which(t) is None]
    return pytest.mark.skipif(bool(missing), reason=f"not installed: {missing}")


@pytest.fixture
def sample(client):
    p = client.post(f"{API}/projects", json={"name": "Tools"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "T1"}).json()


def upload(client, sample_id, *paths):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    r = client.post(f"{API}/samples/{sample_id}/files", files=files)
    assert r.status_code == 201, r.text
    return r.json()["files"]


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def test_tools_listing(client):
    tools = {t["id"]: t for t in client.get(f"{API}/tools").json()}
    assert set(tools) == {"seqkit", "fastqc", "fastp", "filtlong", "multiqc", "nanoplot"}
    for t in tools.values():
        assert t["status"] in ("available", "not_installed", "incompatible", "failed")
        assert t["license"] and t["citation_url"].startswith("https://")


@needs("seqkit")
def test_seqkit_crosscheck_agrees_with_arva(client, sample):
    (f,) = upload(client, sample["id"], R1)
    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={})
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    detail = job(client, j["id"])
    assert detail["status"] == "completed", detail["log_text"]
    assert detail["commands"][0][1:4] == ["stats", "--all", "--tabular"]
    assert detail["result_summary"]["seqkit_stats"]["num_seqs"] == 2000
    check = client.get(f"{API}/files/{f['id']}/crosscheck").json()
    assert check["all_agree"] is True, check["rows"]
    assert {r["metric"] for r in check["rows"]} >= {"Reads", "Total bases", "N50", "Bases ≥ Q30 (%)"}


@needs("fastqc")
def test_fastqc_report_is_served_sandboxed(client, sample):
    (f,) = upload(client, sample["id"], R1)
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/fastqc", json={"raw_file_ids": [f["id"]]}).json()
    detail = job(client, j["id"])
    assert detail["status"] == "completed", detail["log_text"]
    modules = {m["module"] for m in detail["result_summary"]["modules"]}
    assert "Adapter Content" in modules
    html = next(Path(p).name for p in detail["output_paths"] if p.endswith(".html"))
    assert html == "SYNTHETIC_illumina_R1_001_fastqc.html"
    r = client.get(f"{API}/jobs/{j['id']}/outputs/{html}")
    assert r.status_code == 200 and "sandbox" in r.headers["content-security-policy"]
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert client.get(f"{API}/jobs/{j['id']}/outputs/..%2F..%2Fetc%2Fpasswd").status_code == 404


@needs("fastp")
def test_fastp_paired_end_produces_derived_files_and_stats(client, sample):
    f1, f2 = upload(client, sample["id"], R1, R2)
    r = client.post(f"{API}/samples/{sample['id']}/filtering/fastp",
                    json={"read1_file_id": f1["id"], "read2_file_id": f2["id"], "params": {}})
    assert r.status_code == 202, r.text
    detail = job(client, r.json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    cmd = " ".join(detail["commands"][0])
    for flag in ("--qualified_quality_phred 15", "--unqualified_percent_limit 40", "--length_required 15",
                 "--detect_adapter_for_pe"):
        assert flag in cmd
    s = detail["result_summary"]
    assert s["after_filtering"]["total_reads"] < s["before_filtering"]["total_reads"]
    assert s["adapter_trimmed_reads"] > 0

    files = client.get(f"{API}/samples/{sample['id']}/files").json()
    derived = [x for x in files if x["origin"] == "derived"]
    assert len(derived) == 2
    assert {d["parent_file_id"] for d in derived} == {f1["id"], f2["id"]}
    assert all(d["produced_by_job_id"] == detail["id"] and d["is_valid"] for d in derived)
    assert {d["read_mate"] for d in derived} == {"R1", "R2"}
    assert {d["header_metadata"]["mate_layout"] for d in derived} == {"mate_1_only", "mate_2_only"}
    hs = client.get(f"{API}/samples/{sample['id']}/header-summary").json()
    assert [f["file_id"] for f in hs["per_file"]] == [f1["id"], f2["id"]]

    jobs = client.get(f"{API}/samples/{sample['id']}/jobs").json()
    stats = [j for j in jobs if j["job_type"] == "sequence_stats"]
    assert len(stats) == 4 and all(j["status"] == "completed" for j in stats)
    assert all(j["parent_job_id"] == detail["id"] for j in stats)
    kept = sum(j["qc_results"][0]["read_count"] for j in stats if j["input_raw_file_ids"][0] in {d["id"] for d in derived})
    assert kept == s["after_filtering"]["total_reads"]

    stored = get_storage().resolve(next(p for p in detail["output_paths"] if p.endswith(".fastq.gz")))
    assert not stored.stat().st_mode & 0o222

    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert "Processing and independent checks" in html and "--qualified_quality_phred 15" in html
    assert "Derived file — produced from" in html
    csv_text = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "csv"}).text
    assert csv_text.count(",derived,") == 2


@needs("fastp")
def test_fastp_rejects_bad_inputs(client, sample):
    f1, f2 = upload(client, sample["id"], R1, R2)
    swapped = client.post(f"{API}/samples/{sample['id']}/filtering/fastp",
                          json={"read1_file_id": f2["id"], "read2_file_id": f1["id"]})
    assert swapped.status_code == 400 and "swapped" in swapped.json()["detail"]
    fasta = client.post(f"{API}/samples/{sample['id']}/files",
                        files=[("files", ("a.fasta", b">c\nACGT\n", "text/plain"))]).json()["files"][0]
    r = client.post(f"{API}/samples/{sample['id']}/filtering/fastp", json={"read1_file_id": fasta["id"]})
    assert r.status_code == 400 and "FASTQ" in r.json()["detail"]
    bad = client.post(f"{API}/samples/{sample['id']}/filtering/fastp",
                      json={"read1_file_id": f1["id"], "params": {"unqualified_percent_limit": 300}})
    assert bad.status_code == 422


@needs("filtlong")
def test_filtlong_filters_long_reads(client, sample):
    (f,) = upload(client, sample["id"], ONT)
    r = client.post(f"{API}/samples/{sample['id']}/filtering/filtlong",
                    json={"file_id": f["id"], "params": {"min_length": 1000, "min_mean_q": 90}})
    assert r.status_code == 202, r.text
    detail = job(client, r.json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    assert detail["commands"][0][1:5] == ["--min_length", "1000", "--min_mean_q", "90"]
    (derived,) = [x for x in client.get(f"{API}/samples/{sample['id']}/files").json() if x["origin"] == "derived"]
    path = get_storage().resolve(next(p for p in detail["output_paths"] if p.endswith(".fastq.gz")))
    with gzip.open(path, "rt") as fh:
        seqs = fh.read().splitlines()[1::4]
    assert 0 < len(seqs) < 400 and min(map(len, seqs)) >= 1000
    assert derived["parent_file_id"] == f["id"]


def test_filtlong_requires_threshold(client, sample, monkeypatch):
    (f,) = upload(client, sample["id"], ONT)
    r = client.post(f"{API}/samples/{sample['id']}/filtering/filtlong", json={"file_id": f["id"], "params": {}})
    assert r.status_code in (409, 422)
    if shutil.which("filtlong"):
        assert r.status_code == 422 and "threshold" in r.json()["detail"]


@needs("filtlong")
def test_failed_filter_leaves_no_partial_outputs(client, sample, storage_root):
    (f,) = upload(client, sample["id"], ONT)
    r = client.post(f"{API}/samples/{sample['id']}/filtering/filtlong",
                    json={"file_id": f["id"], "params": {"min_length": 10_000_000}})
    detail = job(client, r.json()["id"])
    assert detail["status"] == "failed" and "kept no reads" in detail["error_message"]
    files = client.get(f"{API}/samples/{sample['id']}/files").json()
    assert all(x["origin"] == "imported" for x in files)
    assert not list((storage_root / "processed").rglob(f"*{detail['id']}*"))


def test_unavailable_tool_returns_conflict(client, sample, monkeypatch, tmp_path):
    (f,) = upload(client, sample["id"], R1)
    monkeypatch.setenv("ARVA_TOOL_FASTP", str(tmp_path / "nope"))
    r = client.post(f"{API}/samples/{sample['id']}/filtering/fastp", json={"read1_file_id": f["id"]})
    assert r.status_code == 409 and "not available" in r.json()["detail"]


def test_storage_never_deletes_raw_data():
    with pytest.raises(StoragePathError):
        get_storage().remove_tree("raw/anything")


def test_removing_job_outputs_leaves_linked_originals_untouched(storage_root):
    raw = storage_root / "raw" / "p" / "s" / "f.fastq"
    raw.parent.mkdir(parents=True)
    raw.write_text("@r\nA\n+\nI\n")
    raw.chmod(0o444)
    link = storage_root / "results" / "p" / "s" / "j" / "input" / "f.fastq"
    link.parent.mkdir(parents=True)
    link.symlink_to(raw)
    get_storage().remove_tree("results/p/s/j")
    assert not link.parent.exists() and raw.read_text() == "@r\nA\n+\nI\n" and raw.stat().st_mode & 0o777 == 0o444
