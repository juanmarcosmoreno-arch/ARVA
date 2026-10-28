"""NanoPlot long-read reports.

Request checks and job isolation use a stand-in executable; the end-to-end tests run the real NanoPlot
1.48.0 (ARVA_TOOL_NANOPLOT) and are skipped without it.
"""
import gzip
import random
from pathlib import Path

import pytest
from arva_tools import ToolStatus
from arva_tools.registry import detect

from app.api.routes.tools import REPORT_CSP
from app.db.session import SessionLocal
from app.models import RawFile
from app.storage import get_storage

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "synthetic"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "nanoplot"


def new_sample(client, technology="nanopore"):
    p = client.post(f"{API}/projects", json={"name": "Long reads"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": "LR-1", "sequencing_technology": technology}).json()


def upload(client, sample_id, name, data: bytes):
    r = client.post(f"{API}/samples/{sample_id}/files", files=[("files", (name, data, "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def start(client, sample, files, **extra):
    return client.post(f"{API}/samples/{sample['id']}/analyses/nanoplot",
                       json={"raw_file_ids": [f["id"] for f in files], **extra})


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


FAKE = """#!/bin/sh
if [ "$1" = "--version" ]; then echo 'NanoPlot 1.48.0'; exit 0; fi
{ echo "ARGS=$*"; echo "HOME=$HOME"; echo "DATA=$XDG_DATA_HOME"; echo "CONFIG=$XDG_CONFIG_HOME"; echo "CWD=$(pwd)";
  echo "LINK=$(readlink "$2")"; echo "LS=$(ls -A)"; } > "$FAKE_NP_DUMP"
cp "$FAKE_NP_STATS" "$4/${6}NanoStats.txt"
echo "Finished!" > "$4/${6}NanoPlot_20260101_0000.log"
case "$FAKE_NP_MODE" in
  stats_only) exit 0 ;;
  fatal) echo "FATAL: No reads left after filtering!. Exiting!" >&2; exit 1 ;;
  chrome) mkdir -p "$XDG_DATA_HOME/choreographer/deps" ;;
esac
echo "<html></html>" > "$4/${6}NanoPlot-report.html"
"""


@pytest.fixture
def fake_nanoplot(tmp_path, monkeypatch):
    exe = tmp_path / "NanoPlot"
    exe.write_text(FAKE)
    exe.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_NANOPLOT", str(exe))
    monkeypatch.setenv("FAKE_NP_DUMP", str(tmp_path / "dump.txt"))
    monkeypatch.setenv("FAKE_NP_STATS", str(FIXTURES / "synthetic_NanoStats.txt"))

    def mode(name):
        monkeypatch.setenv("FAKE_NP_MODE", name)
        return tmp_path / "dump.txt"

    return mode


def test_long_reads_are_required_or_confirmed(client, fake_nanoplot, tmp_path, monkeypatch):
    fake_nanoplot("ok")
    unknown = new_sample(client, technology="unknown")
    f = upload(client, unknown["id"], ONT.name, ONT.read_bytes())
    r = start(client, unknown, [f])
    assert r.status_code == 400 and "long reads" in r.json()["detail"] and "'unknown'" in r.json()["detail"]
    r = start(client, unknown, [f], long_reads_confirmed=True)
    assert r.status_code == 202, r.text
    assert r.json()[0]["parameters"] == {"threads": r.json()[0]["parameters"]["threads"], "long_reads_confirmed": True,
                                         "sequencing_technology": "unknown"}

    pacbio = new_sample(client, technology="pacbio")
    fasta = upload(client, pacbio["id"], "contigs.fasta", b">c1\nACGT\n")
    assert "requires FASTQ" in start(client, pacbio, [fasta]).json()["detail"]
    assert "does not belong" in start(client, pacbio, [f]).json()["detail"]
    monkeypatch.setenv("ARVA_TOOL_NANOPLOT", str(tmp_path / "missing"))
    g = upload(client, pacbio["id"], ONT.name, ONT.read_bytes())
    r = start(client, pacbio, [g])
    assert r.status_code == 409 and "not available" in r.json()["detail"]


def test_job_runs_isolated_and_requires_every_output(client, fake_nanoplot, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], "run 1.FQ.GZ", ONT.read_bytes())
    dump = fake_nanoplot("stats_only")
    (j,) = start(client, sample, [f]).json()
    detail = job(client, j["id"])
    assert detail["status"] == "failed" and "did not write NanoStats.txt, its HTML report" in detail["error_message"]
    seen = dict(line.split("=", 1) for line in dump.read_text().splitlines())
    results = storage_root / "results" / sample["project_id"] / sample["id"] / j["id"]
    assert seen["HOME"] == seen["DATA"] == seen["CONFIG"] == str(results / "home")
    assert seen["CWD"] == str(results / "work") and seen["LS"] == ""
    argv = seen["ARGS"].split()
    assert argv[0] == "--fastq" and argv[1] == str(results / "input" / "run_1.fastq.gz")
    assert argv[argv.index("--prefix") + 1] == "run_1_" and "--no_static" in argv and "--only-report" in argv
    with SessionLocal() as db:
        raw = get_storage().resolve(db.get(RawFile, f["id"]).stored_path)
    assert seen["LINK"] == str(raw)
    # The failed job's folder is gone; removing it never followed the link to the read-only original.
    assert not results.exists() and raw.stat().st_mode & 0o777 == 0o444


def test_browser_traces_in_home_fail_the_job(client, fake_nanoplot, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT.name, ONT.read_bytes())
    fake_nanoplot("chrome")
    (j,) = start(client, sample, [f]).json()
    detail = job(client, j["id"])
    assert detail["status"] == "failed" and "web-browser files" in detail["error_message"]
    assert "home folder (choreographer)" in detail["error_message"]


def test_tool_error_message_names_the_reason(client, fake_nanoplot):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT.name, ONT.read_bytes())
    fake_nanoplot("fatal")
    (j,) = start(client, sample, [f]).json()
    detail = job(client, j["id"])
    assert detail["status"] == "failed"
    assert detail["error_message"] == "NanoPlot exited with status 1: FATAL: No reads left after filtering!. Exiting!"


def nanoplot_ready():
    return detect("nanoplot", refresh=True).status is ToolStatus.available


needs_nanoplot = pytest.mark.skipif(not nanoplot_ready(), reason="needs NanoPlot 1.48.0 (ARVA_TOOL_NANOPLOT)")


@needs_nanoplot
def test_nanoplot_end_to_end(client, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT.name, ONT.read_bytes())
    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={})
    r = start(client, sample, [f])
    assert r.status_code == 202, r.text
    detail = job(client, r.json()[0]["id"])
    assert detail["status"] == "completed", detail["log_text"]
    assert detail["tool_name"] == "NanoPlot" and detail["tool_version"] == "1.48.0"
    argv = detail["commands"][0]
    assert argv[1:3] == ["--fastq", str(storage_root / "results" / sample["project_id"] / sample["id"] / detail["id"]
                                         / "input" / "SYNTHETIC_nanopore_reads.fastq.gz")]
    threads = argv[argv.index("--threads") + 1]
    assert argv[argv.index("--prefix"):] == ["--prefix", "SYNTHETIC_nanopore_reads_", "--threads", threads, "--no_static",
                                             "--only-report", "--include-js", "embedded", "--tsv_stats"]
    names = {Path(p).name for p in detail["output_paths"]}
    log = next(n for n in names if n.startswith("SYNTHETIC_nanopore_reads_NanoPlot_") and n.endswith(".log"))
    assert names == {"SYNTHETIC_nanopore_reads_NanoPlot-report.html", "SYNTHETIC_nanopore_reads_NanoStats.txt", log,
                     "nanoplot.stderr.log"}
    # The input link, empty working folder and empty home folder are removed after the checks.
    job_dir = storage_root / "results" / sample["project_id"] / sample["id"] / detail["id"]
    assert [p.name for p in job_dir.iterdir() if p.is_dir()] == []

    s = detail["result_summary"]
    assert s["post_filtering"] is None and s["artefact_reads_removed"] == 0
    qc = next(j for j in client.get(f"{API}/samples/{sample['id']}/jobs").json() if j["job_type"] == "sequence_stats")
    metrics = qc["qc_results"][0]["metrics"]
    # Definitions identical in both tools: the counts must agree exactly.
    assert (s["stats"]["number_of_reads"], s["stats"]["number_of_bases"]) == (metrics["read_count"], metrics["total_bases"])
    # Different definitions, so different values on the same reads; ARVA never compares them.
    assert s["stats"]["mean_qual"] == 10.2 and metrics["quality"]["mean_read_quality"] == pytest.approx(10.8505, abs=1e-4)

    html = client.get(f"{API}/jobs/{detail['id']}/outputs/SYNTHETIC_nanopore_reads_NanoPlot-report.html")
    assert html.status_code == 200 and html.headers["content-security-policy"] == REPORT_CSP
    assert html.headers["x-content-type-options"] == "nosniff" and html.headers["referrer-policy"] == "no-referrer"
    assert str(storage_root) not in html.text
    stats = client.get(f"{API}/jobs/{detail['id']}/outputs/SYNTHETIC_nanopore_reads_NanoStats.txt")
    assert stats.status_code == 200 and stats.text.startswith("Metrics\tdataset")

    report = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    step = next(st for st in report["processing"] if st["job_type"] == "nanoplot")
    assert "400 reads, 1,513,780 bases" in step["highlights"][0] and "--no_static" in step["commands"][0]


@needs_nanoplot
def test_nanoplot_report_in_chromium(client, report_browser_check):
    """scripts/check_nanoplot_report.cjs: the sandboxed report CSP lets the embedded plotly.js draw every plot,
    no request leaves the page and a script in it cannot reach ARVA's origin, so NanoPlot needs no CSP exception."""
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT.name, ONT.read_bytes())
    (j,) = start(client, sample, [f]).json()
    assert job(client, j["id"])["status"] == "completed"
    result = report_browser_check(
        "check_nanoplot_report.cjs",
        client.get(f"{API}/jobs/{j['id']}/outputs/SYNTHETIC_nanopore_reads_NanoPlot-report.html"))
    assert result["rendered"]["plotsWithSvg"] == 7 and result["documentOrigin"] == "null"
    assert result["escape"]["scriptable"] is False and result["external"] == []


def edge_fastq() -> bytes:
    """30 random reads, one zero-length record and one 10 bp read at Q40 (a NanoPlot 'artefact')."""
    rng = random.Random(7)
    records = []
    for i in range(30):
        n = rng.randint(500, 3000)
        records.append(f"@r{i}\n{''.join(rng.choice('ACGT') for _ in range(n))}\n+\n"
                       f"{''.join(chr(33 + rng.randint(5, 20)) for _ in range(n))}\n")
    records += ["@empty\n\n+\n\n", "@art\nACGTACGTAC\n+\nIIIIIIIIII\n"]
    return gzip.compress("".join(records).encode())


@needs_nanoplot
def test_zero_length_and_artefact_reads(client):
    sample = new_sample(client, technology="hybrid")
    f = upload(client, sample["id"], "edge.fastq.gz", edge_fastq())
    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={})
    (j,) = start(client, sample, [f], long_reads_confirmed=True).json()
    detail = job(client, j["id"])
    assert detail["status"] == "completed", detail["log_text"]
    s = detail["result_summary"]
    qc = next(x for x in client.get(f"{API}/samples/{sample['id']}/jobs").json() if x["job_type"] == "sequence_stats")
    m = qc["qc_results"][0]["metrics"]
    # nanoget drops the zero-length record that ARVA counts; bases are unaffected.
    assert (m["read_count"], m["zero_length_reads"]) == (32, 1)
    assert s["stats"]["number_of_reads"] == m["read_count"] - m["zero_length_reads"]
    assert s["stats"]["number_of_bases"] == m["total_bases"]
    assert s["artefact_reads_removed"] == 1 and s["post_filtering"]["number_of_reads"] == 30
    assert any(p.endswith("edge_NanoStats_post_filtering.txt") for p in detail["output_paths"])
    assert "removed 1 artefactual read(s)" in detail["log_text"]


@needs_nanoplot
def test_no_reads_left_fails_cleanly(client, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], "short.fastq", b"@a\nACGTACGTAC\n+\nIIIIIIIIII\n@b\nACGTA\n+\nIIIII\n")
    (j,) = start(client, sample, [f]).json()
    detail = job(client, j["id"])
    assert detail["status"] == "failed" and "No reads left after filtering" in detail["error_message"]
    assert not (storage_root / "results" / sample["project_id"] / sample["id"] / j["id"]).exists()
