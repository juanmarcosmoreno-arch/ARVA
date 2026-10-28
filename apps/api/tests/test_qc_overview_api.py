"""Project QC overview (GET /projects/{id}/qc-overview and .csv), from jobs run through the synchronous queue."""
import csv
import io
import re
import shutil
from pathlib import Path

import pytest
from sqlalchemy import event

from app.db.session import engine

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
POD5 = EXAMPLES / "SYNTHETIC_nanopore_signal.pod5"
FASTQ_A = b"@a1\nACGTNN\n+\nIIII55\n@a2\nGGGCCCAT\n+\n5555IIII\n"
FASTQ_B = b"@b1\nAAAATTTTGG\n+\nIIIIIIIIII\n"


def needs(*tools):
    missing = [t for t in tools if shutil.which(t) is None]
    return pytest.mark.skipif(bool(missing), reason=f"not installed: {missing}")


def make_project(client, name="Overview"):
    return client.post(f"{API}/projects", json={"name": name}).json()


def make_sample(client, project, code, technology="unknown"):
    r = client.post(f"{API}/projects/{project['id']}/samples",
                    json={"sample_code": code, "sequencing_technology": technology})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, sample, *items):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) if isinstance(p, Path)
             else ("files", (p[0], p[1], "application/octet-stream")) for p in items]
    r = client.post(f"{API}/samples/{sample['id']}/files", files=files)
    assert r.status_code == 201, r.text
    return r.json()["files"]


def stats(client, sample, files, genome=None):
    r = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                    json={"raw_file_ids": [f["id"] for f in files], "expected_genome_size_bp": genome})
    assert r.status_code == 202, r.text
    assert all(j["status"] == "completed" for j in r.json())


def run(client, sample, tool, files):
    r = client.post(f"{API}/samples/{sample['id']}/analyses/{tool}", json={"raw_file_ids": [f["id"] for f in files]})
    assert r.status_code == 202, r.text
    return r.json()


def latest_metrics(client, sample):
    """ARVA statistics per file as the sample page sees them (newest completed first)."""
    out = {}
    for job in client.get(f"{API}/samples/{sample['id']}/jobs").json():
        if job["status"] == "completed":
            for qc in job["qc_results"]:
                out.setdefault(qc["raw_file_id"], qc["metrics"])
    return out


def overview(client, project):
    r = client.get(f"{API}/projects/{project['id']}/qc-overview")
    assert r.status_code == 200, r.text
    return {row["sample_code"]: row for row in r.json()["rows"]}


@needs("fastp", "filtlong", "seqkit", "fastqc")
def test_overview_values_for_imported_and_derived_files(client):
    project = make_project(client)
    ill = make_sample(client, project, "ILL-1", "illumina")
    f1, f2 = upload(client, ill, R1, R2)
    stats(client, ill, [f1, f2], genome=5_000)
    fastp = client.post(f"{API}/samples/{ill['id']}/filtering/fastp",
                        json={"read1_file_id": f1["id"], "read2_file_id": f2["id"], "params": {}}).json()
    run(client, ill, "seqkit", [f1, f2])
    (fastqc,) = run(client, ill, "fastqc", [f1])

    ont = make_sample(client, project, "ONT-1", "nanopore")
    (fo,) = upload(client, ont, ONT)
    (pod5,) = upload(client, ont, POD5)
    stats(client, ont, [fo])
    r = client.post(f"{API}/samples/{ont['id']}/filtering/filtlong",
                    json={"file_id": fo["id"], "params": {"min_length": 1000}})
    assert r.status_code == 202, r.text
    filtlong = r.json()
    empty = make_sample(client, project, "EMPTY")

    rows = overview(client, project)
    assert list(rows) == ["EMPTY", "ILL-1", "ONT-1"]

    m = latest_metrics(client, ill)
    a, b = m[f1["id"]], m[f2["id"]]
    row = rows["ILL-1"]
    assert row["sequencing_technology"] == "illumina"
    assert (row["imported_files"], row["derived_files"], row["imported_read_files"]) == (2, 2, 2)
    assert row["imported_read_files_with_stats"] == 2 and row["stats_tool_versions"]
    assert row["total_reads"] == a["read_count"] + b["read_count"] == 4000
    assert row["total_bases"] == a["total_bases"] + b["total_bases"]
    largest = a if a["total_bases"] >= b["total_bases"] else b
    assert row["largest_file"]["total_bases"] == largest["total_bases"]
    assert row["n50"] == largest["n50"]
    assert row["mean_read_quality"] == pytest.approx(largest["quality"]["mean_read_quality"])
    pooled_q30 = (a["quality"]["q30_bases_percent"] * a["total_bases"] + b["quality"]["q30_bases_percent"]
                  * b["total_bases"]) / (a["total_bases"] + b["total_bases"])
    assert row["q30_percent"] == pytest.approx(pooled_q30)
    acgt = [x["total_bases"] - x["ambiguous_bases"] for x in (a, b)]
    assert row["gc_percent"] == pytest.approx((a["gc_percent"] * acgt[0] + b["gc_percent"] * acgt[1]) / sum(acgt))
    assert row["genome_size_status"] == "given" and row["expected_genome_size_bp"] == 5_000
    assert row["estimated_depth"] == pytest.approx(row["total_bases"] / 5_000)

    flt = row["filtering"]
    assert (flt["job_id"], flt["tool_name"], flt["runs"]) == (fastp["id"], "fastp", 1)
    summary = client.get(f"{API}/jobs/{fastp['id']}").json()["result_summary"]
    before, after = summary["before_filtering"], summary["after_filtering"]
    # ARVA's statistics of inputs and outputs reproduce fastp's own read counts.
    assert flt["reads_kept_percent"] == pytest.approx(100 * after["total_reads"] / before["total_reads"])
    assert flt["input_files"] == [R1.name, R2.name] and len(flt["output_files"]) == 2

    modules = client.get(f"{API}/jobs/{fastqc['id']}").json()["result_summary"]["modules"]
    fq = row["fastqc"]
    assert (fq["files"], fq["files_total"]) == (1, 2)
    assert fq["pass_count"] + fq["warn_count"] + fq["fail_count"] == len(modules)
    assert fq["fail_count"] == sum(mod["status"] == "FAIL" for mod in modules)
    assert row["seqkit"] == {"status": "agree", "files_checked": 2, "files_total": 2, "differing_metrics": []}

    o = latest_metrics(client, ont)[fo["id"]]
    row = rows["ONT-1"]
    assert (row["imported_files"], row["derived_files"], row["imported_read_files"]) == (2, 1, 1)
    assert pod5["file_format"] == "pod5"
    assert (row["total_reads"], row["total_bases"], row["n50"]) == (o["read_count"], o["total_bases"], o["n50"])
    assert row["largest_file"]["filename"] == ONT.name
    assert row["genome_size_status"] == "not_given"
    assert row["expected_genome_size_bp"] is None and row["estimated_depth"] is None
    assert row["filtering"]["tool_name"] == "Filtlong" and row["filtering"]["job_id"] == filtlong["id"]
    kept = next(v for k, v in latest_metrics(client, ont).items() if k != fo["id"])
    assert row["filtering"]["bases_kept_percent"] == pytest.approx(100 * kept["total_bases"] / o["total_bases"])
    assert row["fastqc"] == {"files": 0, "files_total": 1, "pass_count": 0, "warn_count": 0, "fail_count": 0}
    assert row["seqkit"]["status"] == "not_run"

    row = rows["EMPTY"]
    assert row["sample_id"] == empty["id"] and row["imported_files"] == 0 and row["imported_read_files"] == 0
    assert row["total_reads"] is None and row["filtering"] is None and row["genome_size_status"] is None
    assert row["seqkit"] == {"status": "not_run", "files_checked": 0, "files_total": 0, "differing_metrics": []}


def test_overview_states_no_value_it_cannot_derive_exactly(client):
    project = make_project(client)
    s = make_sample(client, project, "S1", "hybrid")
    fa, fb = upload(client, s, ("a.fastq", FASTQ_A), ("b.fastq", FASTQ_B))
    stats(client, s, [fa], genome=2_800_000)
    row = overview(client, project)["S1"]
    assert (row["imported_read_files"], row["imported_read_files_with_stats"]) == (2, 1)
    for key in ("total_reads", "total_bases", "largest_file", "n50", "mean_read_quality", "q30_percent",
                "gc_percent", "estimated_depth", "genome_size_status"):
        assert row[key] is None, key

    stats(client, s, [fb], genome=5_000_000)
    row = overview(client, project)["S1"]
    assert (row["total_reads"], row["total_bases"]) == (3, 24)
    assert row["genome_size_status"] == "inconsistent" and row["estimated_depth"] is None
    assert row["largest_file"]["filename"] == "a.fastq"  # 14 bp against 10 bp
    # GC over unambiguous bases only: a.fastq has 2 N among 14 bases.
    assert row["gc_percent"] == pytest.approx(100 * (2 + 6 + 2) / (12 + 10))

    stats(client, s, [fa, fb], genome=5_000_000)
    row = overview(client, project)["S1"]
    assert row["genome_size_status"] == "given" and row["estimated_depth"] == pytest.approx(24 / 5_000_000)


def test_overview_query_count_does_not_grow_with_samples(client):
    def queries(project):
        seen = []

        def count(*_args):
            seen.append(1)

        event.listen(engine, "before_cursor_execute", count)
        try:
            overview(client, project)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    small, large = make_project(client, "Small"), make_project(client, "Large")
    for project, n in ((small, 1), (large, 4)):
        for i in range(n):
            s = make_sample(client, project, f"S{i}")
            files = upload(client, s, ("a.fastq", FASTQ_A), ("b.fastq", FASTQ_B))
            stats(client, s, files)
    assert queries(small) == queries(large)


def test_overview_csv_is_bom_utf8_and_injection_safe(client):
    project = make_project(client, 'Encuesta Perú / "lab" =1')
    s = make_sample(client, project, '=HYPERLINK("http://x","y")', "nanopore")
    (f,) = upload(client, s, ("@evil.fastq", FASTQ_A))
    stats(client, s, [f], genome=1_000)
    r = client.get(f"{API}/projects/{project['id']}/qc-overview.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert re.fullmatch(r'attachment; filename="ARVA_Encuesta_Peru_lab_1_qc_overview_\d{8}T\d{6}Z\.csv"',
                        r.headers["content-disposition"])
    assert r.content.startswith(b"\xef\xbb\xbf") and b"\r\n" in r.content
    (row,) = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))
    assert row["sample_code"] == "'" + '=HYPERLINK("http://x","y")'
    assert row["largest_imported_read_file"] == "'@evil.fastq"
    assert row["total_reads_imported"] == "2" and row["total_bases_imported"] == "14"
    assert row["estimated_depth_x"] == "0.01" and row["genome_size_status"] == "given"
    assert row["sequencing_technology"] == "nanopore" and row["seqkit_crosscheck"] == "not_run"
    assert row["fastqc_heuristics_fail_modules"] == "" and row["imported_fastq_files"] == "1"
    assert client.get(f"{API}/projects/missing/qc-overview.csv").status_code == 404
    assert client.get(f"{API}/projects/missing/qc-overview").status_code == 404
