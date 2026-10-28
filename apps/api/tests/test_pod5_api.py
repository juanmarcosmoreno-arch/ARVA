"""POD5 raw-signal files: import, exclusion from read-level analyses and the pod5 run-metadata job.

Job tests need the optional pod5 library and are skipped without it.
"""
import gzip
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import RawFile
from app.services import jobs as jobs_service
from app.services.jobs import files_without_stats

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
POD5 = EXAMPLES / "SYNTHETIC_nanopore_signal.pod5"
FASTQ = b"@r1\nACGT\n+\nIIII\n@r2\nGGGCCC\n+\n555555\n"
SIGNATURE = b"\x8bPOD\r\n\x1a\n"
TRUNCATED_MESSAGE = "Incomplete or truncated POD5 — the end signature is missing; copy the file again."
needs_pod5 = pytest.mark.skipif(
    importlib.util.find_spec("pod5") is None,
    reason='the optional pod5 library is not installed (pip install "pod5==0.3.49")',
)


@pytest.fixture
def sample(client):
    p = client.post(f"{API}/projects", json={"name": "POD5"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "P1"}).json()


def upload(client, sample_id, name, data):
    r = client.post(f"{API}/samples/{sample_id}/files", files=[("files", (name, data, "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()


def upload_one(client, sample_id, name, data):
    (f,) = upload(client, sample_id, name, data)["files"]
    return f


def run_pod5(client, sample_id, file_id):
    r = client.post(f"{API}/samples/{sample_id}/analyses/pod5", json={"raw_file_ids": [file_id]})
    assert r.status_code == 202, r.text
    (j,) = r.json()
    return client.get(f"{API}/jobs/{j['id']}").json()


def write_pod5(path: Path, runs: list[tuple[str, int, list[int]]], experiment: str = "SYNTHETIC") -> Path:
    """A POD5 with one acquisition per (acquisition_id, sample_rate, samples per read) entry."""
    import numpy as np
    import pod5

    rng = np.random.default_rng(7)
    start = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    reads = []
    for acq, rate, lengths in runs:
        info = pod5.RunInfo(
            acquisition_id=acq, acquisition_start_time=start, adc_max=4095, adc_min=-4096,
            context_tags={"tag": "SYNTHETIC"}, experiment_name=experiment, flow_cell_id="SYNTHETIC-FC",
            flow_cell_product_code="SYNTHETIC-FLO", protocol_name="SYNTHETIC-protocol", protocol_run_id=f"{acq}-run",
            protocol_start_time=start, sample_id="SYNTHETIC", sample_rate=rate, sequencing_kit="SYNTHETIC-KIT",
            sequencer_position="SYNTHETIC-position", sequencer_position_type="SYNTHETIC", software="tests",
            system_name="SYNTHETIC-system", system_type="SYNTHETIC", tracking_id={"run_id": f"{acq}-run"},
        )
        for i, n in enumerate(lengths):
            reads.append(pod5.Read(
                read_id=uuid.UUID(bytes=rng.bytes(16), version=4),
                pore=pod5.Pore(channel=len(reads) + 1, well=1, pore_type="SYNTHETIC"),
                calibration=pod5.Calibration(offset=0.0, scale=1.0), read_number=i, start_sample=0,
                median_before=200.0, end_reason=pod5.EndReason(pod5.EndReasonEnum.SIGNAL_POSITIVE, False),
                run_info=info, signal=rng.normal(500, 40, n).astype(np.int16),
            ))
    with pod5.Writer(path) as writer:
        if reads:
            writer.add_reads(reads)
    return path


# --- Import -------------------------------------------------------------------------------------

def test_synthetic_pod5_is_registered_as_raw_signal(client, sample, storage_root):
    f = upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    assert f["file_format"] == "pod5"
    assert f["is_valid"] is True and "complete" in f["validation_message"]
    assert f["read_mate"] is None and f["header_metadata"] is None
    stored = next(storage_root.glob(f"raw/*/{sample['id']}/{f['id']}__*"))
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == f["checksum_sha256"]


def test_content_decides_format_and_pod5_never_gets_a_mate(client, sample):
    signal = upload_one(client, sample["id"], "run_R1_001.fastq.gz", POD5.read_bytes())
    assert signal["file_format"] == "pod5" and signal["read_mate"] is None
    reads = upload_one(client, sample["id"], "renamed.pod5", gzip.compress(FASTQ))
    assert reads["file_format"] == "fastq_gz" and reads["is_valid"] is True
    empty = upload_one(client, sample["id"], "empty.pod5", b"")
    assert empty["file_format"] == "unknown"


def test_truncated_pod5_is_registered_as_invalid(client, sample):
    f = upload_one(client, sample["id"], "cut.pod5", POD5.read_bytes()[:200_000])
    assert f["file_format"] == "pod5"
    assert f["is_valid"] is False and f["validation_message"] == TRUNCATED_MESSAGE


def test_duplicate_pod5_is_rejected(client, sample):
    upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    result = upload(client, sample["id"], "copy.pod5", POD5.read_bytes())
    assert result["files"] == [] and result["rejected"][0]["code"] == "duplicate"


def test_server_folder_import_accepts_pod5(client, sample, tmp_path, monkeypatch):
    root = tmp_path / "import"
    root.mkdir()
    (root / POD5.name).write_bytes(POD5.read_bytes())
    monkeypatch.setattr(get_settings(), "import_roots", [root])
    entry = next(e for e in client.get(f"{API}/imports/browse", params={"root": 0}).json()["entries"])
    assert entry["kind"] == "pod5"
    r = client.post(f"{API}/samples/{sample['id']}/files/import-server", json={"root": 0, "paths": [POD5.name]})
    assert r.status_code == 202, r.text
    assert client.get(f"{API}/jobs/{r.json()['id']}").json()["status"] == "completed"
    (f,) = client.get(f"{API}/samples/{sample['id']}/files").json()
    assert f["file_format"] == "pod5" and f["is_valid"] and f["read_mate"] is None


# --- Read-level analyses never use POD5 -----------------------------------------------------------

def _requests(file_id):
    return [
        ("analyses/sequence-stats", {"raw_file_ids": [file_id]}, "read statistics"),
        ("analyses/seqkit", {"raw_file_ids": [file_id]}, "SeqKit"),
        ("analyses/fastqc", {"raw_file_ids": [file_id]}, "FastQC"),
        ("filtering/fastp", {"read1_file_id": file_id}, "fastp"),
        ("filtering/filtlong", {"file_id": file_id, "params": {"min_length": 100}}, "Filtlong"),
    ]


def test_read_level_analyses_refuse_pod5_with_400(client, sample):
    f = upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    for path, body, analysis in _requests(f["id"]):
        r = client.post(f"{API}/samples/{sample['id']}/{path}", json=body)
        assert r.status_code == 400, (path, r.text)
        detail = r.json()["detail"]
        assert "POD5 raw-signal file" in detail and analysis in detail and "Basecall it outside ARVA" in detail
    r = client.get(f"{API}/files/{f['id']}/crosscheck")
    assert r.status_code == 400 and "POD5 raw-signal file" in r.json()["detail"]
    assert client.get(f"{API}/samples/{sample['id']}/jobs").json() == []


def test_statistics_of_all_files_skip_pod5(client, sample):
    pod5_file = upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    r = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={})
    assert r.status_code == 400 and r.json()["detail"] == "No FASTQ/FASTA files to analyse"
    reads = upload_one(client, sample["id"], "reads.fastq", FASTQ)
    (job,) = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={}).json()
    assert job["input_raw_file_ids"] == [reads["id"]]
    assert client.get(f"{API}/files/{pod5_file['id']}").json()["is_valid"] is True


def test_files_without_stats_never_lists_pod5(client, sample):
    pod5_file = upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    reads = upload_one(client, sample["id"], "reads.fastq", FASTQ)
    with SessionLocal() as db:
        files = [db.get(RawFile, pod5_file["id"]), db.get(RawFile, reads["id"])]
        assert [f.id for f in files_without_stats(db, sample["id"], files)] == [reads["id"]]


def test_header_summary_ignores_pod5(client, sample):
    upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    reads = upload_one(client, sample["id"], "reads.fastq", FASTQ)
    summary = client.get(f"{API}/samples/{sample['id']}/header-summary").json()
    assert [f["file_id"] for f in summary["per_file"]] == [reads["id"]]
    assert summary["suggested_technology"]["files_considered"] == 1


# --- pod5 run-metadata job --------------------------------------------------------------------------

def test_pod5_analysis_is_409_with_the_install_command_without_the_library(client, sample, monkeypatch):
    f = upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    monkeypatch.setattr(jobs_service, "pod5_versions", lambda: {"pod5": None, "lib_pod5": None})
    r = client.post(f"{API}/samples/{sample['id']}/analyses/pod5", json={"raw_file_ids": [f["id"]]})
    assert r.status_code == 409
    assert 'pip install "pod5==0.3.49"' in r.json()["detail"]
    assert client.get(f"{API}/samples/{sample['id']}/jobs").json() == []


def test_pod5_analysis_validates_its_inputs(client, sample):
    reads = upload_one(client, sample["id"], "reads.fastq", FASTQ)
    cut = upload_one(client, sample["id"], "cut.pod5", POD5.read_bytes()[:50_000])
    other = client.post(f"{API}/projects/{sample['project_id']}/samples", json={"sample_code": "P2"}).json()
    foreign = upload_one(client, other["id"], POD5.name, POD5.read_bytes())
    url = f"{API}/samples/{sample['id']}/analyses/pod5"
    for ids, expected in [
        ([reads["id"]], "is not a POD5 file"),
        ([cut["id"]], "failed validation"),
        ([foreign["id"]], "does not belong to this sample"),
        ([cut["id"], cut["id"]], "more than once"),
    ]:
        r = client.post(url, json={"raw_file_ids": ids})
        assert r.status_code == 400 and expected in r.json()["detail"], r.text
    assert client.post(url, json={"raw_file_ids": []}).status_code == 422
    assert client.post(url, json={"raw_file_ids": ["x"] * 1001}).status_code == 422


@needs_pod5
def test_pod5_job_reads_run_metadata_end_to_end(client, sample, storage_root):
    from importlib.metadata import version

    f = upload_one(client, sample["id"], POD5.name, POD5.read_bytes())
    job = run_pod5(client, sample["id"], f["id"])
    assert job["status"] == "completed", job["log_text"]
    assert job["job_type"] == "pod5_summary" and job["tool_name"] == "pod5"
    assert job["tool_version"] == version("pod5")
    assert job["parameters"]["lib_pod5_version"] == version("lib_pod5")
    assert "signal was not decoded" in job["log_text"]

    s = job["result_summary"]
    assert s["reads"] == {
        "count": 5, "total_samples": 299_000, "min_samples": 4_000, "max_samples": 250_000,
        "distinct_channels": 5, "acquisitions": 1, "total_signal_duration_s": 59.8,
    }
    assert s["file"]["num_reads"] == 5 and s["file"]["batch_count"] == 1 and s["file"]["is_vbz_compressed"] is True
    (info,) = s["run_infos"]
    assert info["sample_id"] == "SYNTHETIC" and info["experiment_name"] == "SYNTHETIC"
    assert info["sample_rate"] == 5000 and info["reads"] == 5
    assert info["acquisition_start_time"] == "2026-01-02T03:04:05+00:00"
    assert s["warnings"] == []
    assert "SYNTHETIC-system" not in json.dumps(s) and "tracking_id" not in s["run_infos"][0]
    assert s["withheld_fields"] == ["system_name", "sequencer_position", "context_tags", "tracking_id"]

    (out,) = job["output_paths"]
    doc = json.loads((storage_root / out).read_text())
    hidden = doc["potentially_identifying"]
    assert hidden["run_infos"][0]["system_name"] == "SYNTHETIC-system"
    assert hidden["run_infos"][0]["tracking_id"] == {"run_id": "SYNTHETIC-protocol-run-0000"}
    assert doc["software"]["pod5"] == version("pod5") and doc["input"]["sha256"] == f["checksum_sha256"]
    r = client.get(f"{API}/jobs/{job['id']}/outputs/pod5_summary.json")
    assert r.status_code == 200 and json.loads(r.text)["schema"] == "arva.pod5_summary/1"
    after = client.get(f"{API}/files/{f['id']}").json()
    assert after["is_valid"] is True and after["checksum_sha256"] == f["checksum_sha256"]


@needs_pod5
def test_signal_duration_sums_each_acquisition_at_its_own_sample_rate(client, sample, tmp_path):
    path = write_pod5(tmp_path / "merged.pod5", [("SYNTHETIC-A", 5000, [10_000, 5_000]), ("SYNTHETIC-B", 4000, [8_000])])
    f = upload_one(client, sample["id"], path.name, path.read_bytes())
    job = run_pod5(client, sample["id"], f["id"])
    assert job["status"] == "completed", job["log_text"]
    s = job["result_summary"]
    assert s["reads"]["count"] == 3 and s["reads"]["acquisitions"] == 2
    assert s["reads"]["total_signal_duration_s"] == pytest.approx(15_000 / 5000 + 8_000 / 4000)
    by_acq = {r["acquisition_id"]: (r["reads"], r["samples"], r["signal_duration_s"]) for r in s["run_infos"]}
    assert by_acq == {"SYNTHETIC-A": (2, 15_000, 3.0), "SYNTHETIC-B": (1, 8_000, 2.0)}


@needs_pod5
def test_pod5_without_reads_is_summarised(client, sample, tmp_path):
    path = write_pod5(tmp_path / "empty.pod5", [])
    f = upload_one(client, sample["id"], path.name, path.read_bytes())
    assert f["is_valid"] is True
    job = run_pod5(client, sample["id"], f["id"])
    assert job["status"] == "completed", job["log_text"]
    s = job["result_summary"]
    assert s["file"]["batch_count"] == 0 and s["file"]["num_reads"] == 0
    assert s["reads"]["count"] == 0 and s["reads"]["min_samples"] is None
    assert s["warnings"] == ["The file contains no reads."]


@needs_pod5
def test_unreadable_pod5_fails_with_the_library_message_and_keeps_the_file(client, sample, storage_root):
    f = upload_one(client, sample["id"], "garbled.pod5", SIGNATURE + bytes(range(256)) * 4 + SIGNATURE)
    assert f["is_valid"] is True
    job = run_pod5(client, sample["id"], f["id"])
    assert job["status"] == "failed"
    assert job["error_message"].startswith("pod5 ") and "could not read this file: IOError" in job["error_message"]
    assert job["output_paths"] is None
    assert not list(storage_root.glob(f"results/*/{sample['id']}/{job['id']}/*"))
    assert client.get(f"{API}/files/{f['id']}").json()["is_valid"] is True


@needs_pod5
def test_reports_show_run_metadata_escaped_and_without_identifying_fields(client, sample, tmp_path):
    path = write_pod5(tmp_path / "x.pod5", [("SYNTHETIC-A", 5000, [5_000])], experiment="<script>alert(1)</script>")
    f = upload_one(client, sample["id"], path.name, path.read_bytes())
    assert run_pod5(client, sample["id"], f["id"])["status"] == "completed"
    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert "Raw signal files (POD5)" in html and "SYNTHETIC-KIT" in html and "not the run&#x27;s wall-clock time" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    data = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
    assert data["files"] == []
    (entry,) = data["raw_signal_files"]
    assert entry["run_metadata"]["summary"]["reads"]["count"] == 1
    for text in (html, json.dumps(data)):
        assert "SYNTHETIC-system" not in text and "SYNTHETIC-position" not in text
    csv_text = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "csv"}).text
    assert path.name not in csv_text


# --- Library listing and lazy import ------------------------------------------------------------

def test_libraries_listing_reports_pod5(client, monkeypatch):
    (lib,) = client.get(f"{API}/tools/libraries").json()
    assert lib["id"] == "pod5" and lib["license"] == "MPL-2.0" and lib["required_version"] == "0.3.49"
    assert lib["install"] == 'pip install "pod5==0.3.49"' and lib["citation_url"].startswith("https://")
    assert lib["status"] == ("available" if importlib.util.find_spec("pod5") else "not_installed")
    from app.api.routes import tools as tools_routes

    monkeypatch.setattr(tools_routes, "pod5_versions", lambda: {"pod5": None, "lib_pod5": None})
    (lib,) = client.get(f"{API}/tools/libraries").json()
    assert lib["status"] == "not_installed" and lib["version"] is None and lib["version_validated"] is False


def test_api_process_never_imports_pod5():
    code = "import sys, app.main; sys.exit(int(any(m in sys.modules for m in ('pod5', 'lib_pod5', 'pyarrow'))))"
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ}, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
