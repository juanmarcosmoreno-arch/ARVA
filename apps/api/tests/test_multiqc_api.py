"""Project-level jobs and the MultiQC project report.

Selection tests build tool job records directly (the files are validated by ARVA's own statistics); the
end-to-end and Chromium tests run the real tools and need MultiQC 1.35 (ARVA_TOOL_MULTIQC) plus FastQC,
fastp, SeqKit and Filtlong, otherwise they are skipped.
"""
import datetime as dt
import json
import stat
from pathlib import Path

import pytest
from arva_tools import ToolStatus
from arva_tools.registry import detect

from app.api.routes.tools import MULTIQC_REPORT_CSP
from app.db.session import SessionLocal
from app.models import AnalysisJob, FileFormat, FileOrigin, JobStatus, Project, RawFile
from app.services import multiqc
from app.services.multiqc import STORAGE_SHIM
from app.storage import get_storage
from app.tasks.tools import run_multiqc_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def upload(client, sample_id, *paths):
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    r = client.post(f"{API}/samples/{sample_id}/files", files=files)
    assert r.status_code == 201, r.text
    return r.json()["files"]


@pytest.fixture
def project(client):
    return client.post(f"{API}/projects", json={"name": "Survey"}).json()


def new_sample(client, project, code):
    return client.post(f"{API}/projects/{project['id']}/samples", json={"sample_code": code}).json()


OUTPUT = {"fastqc": "{stem}_fastqc.zip", "seqkit_stats": "seqkit_stats.tsv", "fastp": "fastp.json",
          "filtlong": "filtlong.log"}
TOOL = {"fastqc": "FastQC", "seqkit_stats": "SeqKit", "fastp": "fastp", "filtlong": "Filtlong"}


def add_job(sample, job_type, files, minutes=0, params=None, write_output=True, status=JobStatus.completed):
    """A finished tool job with its output file in storage (selection only checks that it exists)."""
    with SessionLocal() as db:
        job = AnalysisJob(
            project_id=sample["project_id"], sample_id=sample["id"], job_type=job_type, tool_name=TOOL[job_type],
            tool_version="1.0", parameters=params or {}, input_raw_file_ids=[f["id"] for f in files],
            status=status, finished_at=T0 + dt.timedelta(minutes=minutes), log_text="",
        )
        db.add(job)
        db.flush()
        rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}/" + OUTPUT[job_type].format(stem="x")
        if write_output:
            get_storage().write_text(rel, "output")
        job.output_paths = [rel]
        db.commit()
        return job.id


def add_derived(sample, parent, producer_job_id, name, content: Path):
    target = get_storage().resolve(f"processed/{name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.read_bytes())
    with SessionLocal() as db:
        f = RawFile(sample_id=sample["id"], original_filename=name, stored_path=f"processed/{name}",
                    file_format=FileFormat.fastq_gz, read_mate=parent["read_mate"], size_bytes=1, is_valid=True,
                    origin=FileOrigin.derived, parent_file_id=parent["id"], produced_by_job_id=producer_job_id)
        db.add(f)
        db.commit()
        return {"id": f.id, "read_mate": f.read_mate}


def validate(client, sample, *files):
    """ARVA's read statistics: the full validation MultiQC inputs require."""
    r = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                    json={"raw_file_ids": [f["id"] for f in files]})
    assert r.status_code == 202, r.text
    assert all(client.get(f"{API}/jobs/{j['id']}").json()["status"] == "completed" for j in r.json())


def preview(client, project, **body):
    r = client.post(f"{API}/projects/{project['id']}/analyses/multiqc/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_selection_uses_latest_qualifying_results_with_stable_names(client, project):
    a = new_sample(client, project, "ISO-001")
    b = new_sample(client, project, "ISO-002")
    empty = new_sample(client, project, "ISO-003")
    r1, r2 = upload(client, a["id"], R1, R2)
    (ont,) = upload(client, b["id"], ONT)
    validate(client, a, r1, r2)
    validate(client, b, ont)
    add_job(a, "fastqc", [r1], minutes=1)
    newest_r1 = add_job(a, "fastqc", [r1], minutes=5)
    add_job(a, "fastqc", [r2], minutes=2)
    fastp = add_job(a, "fastp", [r1, r2], minutes=3)
    add_job(a, "seqkit_stats", [r1], minutes=4)
    add_job(b, "seqkit_stats", [ont], minutes=1)
    with_target = add_job(b, "filtlong", [ont], minutes=1, params={"keep_percent": 90, "target_bases": None})
    no_target = add_job(b, "filtlong", [ont], minutes=2, params={"min_length": 1000, "target_bases": None})
    derived = add_derived(a, r1, fastp, "SYNTHETIC_illumina_R1_001.fastp.fastq.gz", R1)
    validate(client, a, derived)
    add_job(a, "fastqc", [derived], minutes=5)
    on_derived = add_job(a, "fastqc", [derived], minutes=6)

    plan = preview(client, project)
    assert "most recent completed" in plan["selection_rule"] and "read in full" in plan["selection_rule"]
    assert plan["modules"] == ["fastqc", "fastp", "seqkit", "filtlong"]
    got = [(i["module"], i["name"]) for i in plan["inputs"]]
    assert got == [
        ("fastqc", "ISO-001 R1"), ("fastqc", "ISO-001 R2"), ("fastp", "ISO-001 R1+R2"), ("seqkit", "ISO-001 R1"),
        ("seqkit", "ISO-002 SYNTHETIC_nanopore_reads"), ("filtlong", "ISO-002 SYNTHETIC_nanopore_reads"),
    ]
    by_name = {(i["module"], i["name"]): i for i in plan["inputs"]}
    assert by_name[("fastqc", "ISO-001 R1")]["job_id"] == newest_r1
    assert by_name[("filtlong", "ISO-002 SYNTHETIC_nanopore_reads")]["job_id"] == with_target
    assert by_name[("fastp", "ISO-001 R1+R2")]["file_names"] == [R1.name, R2.name]
    # A file-level reason is given once, for the newest result of that file; older ones are not listed.
    reasons = [(e["sample_code"], e["reason"], e["job_id"]) for e in plan["excluded"]]
    assert sorted(reasons, key=str) == sorted([("ISO-001", "derived_input", on_derived),
                                               ("ISO-002", "filtlong_without_target", no_target),
                                               ("ISO-003", "no_outputs", None)], key=str)

    with_derived = preview(client, project, include_derived=True)
    assert ("fastqc", "ISO-001 R1 after fastp") in [(i["module"], i["name"]) for i in with_derived["inputs"]]

    only_b = preview(client, project, sample_ids=[b["id"], empty["id"]])
    assert {i["sample_code"] for i in only_b["inputs"]} == {"ISO-002"} and only_b["sample_ids"] == [b["id"], empty["id"]]


def test_missing_output_falls_back_and_names_stay_unique(client, project):
    a = new_sample(client, project, "<b>X</b>")
    r1, r2 = upload(client, a["id"], R1, R2)
    with SessionLocal() as db:
        db.get(RawFile, r2["id"]).read_mate = "R1"
        db.commit()
    validate(client, a, r1, r2)
    older = add_job(a, "fastqc", [r1], minutes=1)
    newer = add_job(a, "fastqc", [r1], minutes=2, write_output=False)
    add_job(a, "fastqc", [r2], minutes=1)
    plan = preview(client, project)
    assert plan["inputs"][0]["job_id"] == older
    assert [(e["reason"], e["job_id"]) for e in plan["excluded"]] == [("output_missing", newer)]
    # Two files labelled R1 in one sample fall back to their file names; markup never reaches MultiQC.
    assert [i["name"] for i in plan["inputs"]] == ["_b_X__b_ SYNTHETIC_illumina_R1_001",
                                                    "_b_X__b_ SYNTHETIC_illumina_R2_001"]


def test_start_rejects_bad_requests(client, project, monkeypatch, tmp_path):
    a = new_sample(client, project, "ISO-001")
    other = client.post(f"{API}/projects", json={"name": "Other"}).json()
    url = f"{API}/projects/{project['id']}/analyses/multiqc"
    r = client.post(url, json={})
    assert r.status_code == 400 and "Nothing to aggregate" in r.json()["detail"]
    assert client.post(url, json={"sample_ids": []}).status_code == 422
    foreign = new_sample(client, other, "F-1")
    r = client.post(url, json={"sample_ids": [foreign["id"]]})
    assert r.status_code == 400 and "does not belong" in r.json()["detail"]
    assert client.post(f"{API}/projects/nope/analyses/multiqc", json={}).status_code == 404

    (r1,) = upload(client, a["id"], R1)
    validate(client, a, r1)
    add_job(a, "fastqc", [r1])
    monkeypatch.setenv("ARVA_TOOL_MULTIQC", str(tmp_path / "missing"))
    r = client.post(url, json={})
    assert r.status_code == 409 and "not available" in r.json()["detail"]
    old = tmp_path / "multiqc"
    old.write_text("#!/bin/sh\necho 'multiqc, version 1.18'\n")
    old.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_MULTIQC", str(old))
    r = client.post(url, json={})
    assert r.status_code == 409 and "plain HTTP" in r.json()["detail"]
    assert client.get(f"{API}/projects/{project['id']}/jobs").json() == []


def test_invalid_or_partly_validated_files_are_left_out(client, project):
    a = new_sample(client, project, "ISO-001")
    r1, r2 = upload(client, a["id"], R1, R2)
    add_job(a, "fastqc", [r1], minutes=1)
    newest = add_job(a, "fastqc", [r1], minutes=2)
    fastqc_r2 = add_job(a, "fastqc", [r2])
    fastp = add_job(a, "fastp", [r1, r2])
    # Import checks only the start of a file; until ARVA has read all of it, its results are not used.
    plan = preview(client, project)
    assert plan["inputs"] == []
    assert {(e["reason"], e["job_id"]) for e in plan["excluded"]} == {
        ("input_not_validated", newest), ("input_not_validated", fastqc_r2), ("input_not_validated", fastp),
        ("no_outputs", None)}

    validate(client, a, r1, r2)
    with SessionLocal() as db:
        f = db.get(RawFile, r2["id"])
        f.is_valid, f.validation_message = False, "Full validation failed: invalid nucleotide characters ['<']"
        db.commit()
    plan = preview(client, project)
    assert [(i["module"], i["name"], i["job_id"]) for i in plan["inputs"]] == [("fastqc", "ISO-001 R1", newest)]
    assert {(e["reason"], e["job_id"]) for e in plan["excluded"]} == {("input_invalid", fastqc_r2),
                                                                      ("input_invalid", fastp)}


def test_report_names_never_merge_two_samples(client, project):
    slash = new_sample(client, project, "A/1")
    under = new_sample(client, project, "A_1")
    (s1,) = upload(client, slash["id"], R1)
    (u1,) = upload(client, under["id"], R1)
    validate(client, slash, s1)
    validate(client, under, u1)
    add_job(slash, "seqkit_stats", [s1])
    add_job(under, "fastqc", [u1])
    add_job(under, "seqkit_stats", [u1])
    plan = preview(client, project)
    names = {(i["sample_code"], i["module"]): i["name"] for i in plan["inputs"]}
    # Both IDs clean up to "A_1"; MultiQC joins rows by name, so each sample keeps its own name in every module.
    assert names == {("A/1", "seqkit"): f"A_1 R1 ({slash['id'][:8]})",
                     ("A_1", "fastqc"): f"A_1 R1 ({under['id'][:8]})",
                     ("A_1", "seqkit"): f"A_1 R1 ({under['id'][:8]})"}

    long = "L" * 130
    one, two = new_sample(client, project, long + "1"), new_sample(client, project, long + "2")
    for sample in (one, two):
        (f,) = upload(client, sample["id"], ONT)
        validate(client, sample, f)
        add_job(sample, "seqkit_stats", [f])
    plan = preview(client, project, sample_ids=[one["id"], two["id"]])
    names = sorted(i["name"] for i in plan["inputs"])
    assert len(set(names)) == 2 and all(len(n) <= 120 for n in names)
    assert names == sorted(f"{'L' * 109} ({s['id'][:8]})" for s in (one, two))


FAKE_MULTIQC = """#!/bin/sh
if [ "$1" = "--version" ]; then echo 'multiqc, version 1.35'; exit 0; fi
{ echo "HOME=$HOME"; echo "VC=$MULTIQC_NO_VERSION_CHECK"; echo "CWD=$(pwd)"; ls -A; } > "$FAKE_MQC_DUMP"
cat $(cat "$2") > "$FAKE_MQC_DUMP.inputs"
exit 0
"""


def fake_multiqc(tmp_path, monkeypatch):
    fake = tmp_path / "multiqc"
    fake.write_text(FAKE_MULTIQC)
    fake.chmod(0o755)
    dump = tmp_path / "dump.txt"
    monkeypatch.setenv("ARVA_TOOL_MULTIQC", str(fake))
    monkeypatch.setenv("FAKE_MQC_DUMP", str(dump))
    return dump


def test_grouped_filtlong_logs_are_staged_without_separators(client, project, monkeypatch, tmp_path):
    b = new_sample(client, project, "ISO-002")
    (ont,) = upload(client, b["id"], ONT)
    validate(client, b, ont)
    filtlong = add_job(b, "filtlong", [ont], params={"keep_percent": 90})
    with SessionLocal() as db:
        rel = db.get(AnalysisJob, filtlong).output_paths[0]
    # Filtlong run under en_US before ARVA set LC_ALL=C; MultiQC 1.35 crashes on "1,362,402".
    log = "Scoring long reads\n\r  400 reads ({} bp)\n\nFiltering long reads\n  target: {} bp\n  keeping {} bp\n"
    get_storage().write_text(rel, log.format("1,513,780", "1,362,402", "1,366,991"))
    dump = fake_multiqc(tmp_path, monkeypatch)
    job = client.post(f"{API}/projects/{project['id']}/analyses/multiqc", json={}).json()
    detail = client.get(f"{API}/jobs/{job['id']}").json()
    assert "Filtlong wrote its counts with digit grouping; the staged copy has the separators removed" in detail["log_text"]
    assert dump.with_name("dump.txt.inputs").read_bytes() == log.format("1513780", "1362402", "1366991").encode()
    assert "1,362,402" in get_storage().resolve(rel).read_text()


def test_a_job_whose_names_would_merge_samples_fails(client, project, monkeypatch, tmp_path):
    a, b = new_sample(client, project, "A"), new_sample(client, project, "B")
    (fa,), (fb,) = upload(client, a["id"], R1), upload(client, b["id"], R1)
    validate(client, a, fa)
    validate(client, b, fb)
    add_job(a, "seqkit_stats", [fa])
    add_job(b, "seqkit_stats", [fb])
    with SessionLocal() as db:
        plan_inputs = multiqc.plan(db, db.get(Project, project["id"]), None, False).as_dict()["inputs"]
    for item in plan_inputs:
        item["name"] = "same name"
    dump = fake_multiqc(tmp_path, monkeypatch)
    with SessionLocal() as db:
        job = AnalysisJob(project_id=project["id"], job_type="multiqc", tool_name="MultiQC", tool_version="1.35",
                          parameters={"inputs": plan_inputs}, input_raw_file_ids=[fa["id"], fb["id"]],
                          status=JobStatus.pending, log_text="")
        db.add(job)
        db.commit()
        job_id = job.id
    assert run_multiqc_job(job_id) == "failed"
    detail = client.get(f"{API}/jobs/{job_id}").json()
    assert "would each hold results of different samples or files: same name" in detail["error_message"]
    assert not dump.exists()


def test_report_is_served_sandboxed_with_a_storage_stand_in(client, project):
    with SessionLocal() as db:
        job = AnalysisJob(project_id=project["id"], job_type="multiqc", tool_name="MultiQC", tool_version="1.35",
                          parameters={}, input_raw_file_ids=[], status=JobStatus.completed, log_text="")
        db.add(job)
        db.flush()
        rel = f"results/{project['id']}/_project/{job.id}/arva_multiqc_report.html"
        get_storage().write_text(rel, '<!doctype html>\n<html lang="en">\n  <HEAD data-x="1">\n<script>run()</script>')
        job.output_paths = [rel]
        db.commit()
        job_id = job.id
    r = client.get(f"{API}/jobs/{job_id}/outputs/arva_multiqc_report.html")
    assert r.status_code == 200 and r.headers["content-security-policy"] == MULTIQC_REPORT_CSP
    assert MULTIQC_REPORT_CSP.startswith("sandbox allow-scripts allow-popups;") and "allow-same-origin" not in MULTIQC_REPORT_CSP
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    # The stand-in runs before any script of the report; the stored file itself is not changed.
    assert r.content == ('<!doctype html>\n<html lang="en">\n  <HEAD data-x="1">' + STORAGE_SHIM.decode()
                         + '\n<script>run()</script>').encode()
    download = client.get(f"{API}/jobs/{job_id}/outputs/arva_multiqc_report.html?download=true")
    assert STORAGE_SHIM not in download.content and download.headers["content-type"] == "application/octet-stream"


def test_exit_status_zero_without_a_report_fails_the_job(client, project, monkeypatch, tmp_path, storage_root):
    a = new_sample(client, project, "ISO-001")
    (r1,) = upload(client, a["id"], R1)
    validate(client, a, r1)
    with SessionLocal() as db:
        source = get_storage().resolve(db.get(AnalysisJob, add_job(a, "fastqc", [r1])).output_paths[0])
    source.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    dump = fake_multiqc(tmp_path, monkeypatch)
    r = client.post(f"{API}/projects/{project['id']}/analyses/multiqc", json={})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and "did not write its report" in job["error_message"]
    assert job["project_id"] == project["id"] and job["sample_id"] is None
    seen = dict(line.split("=", 1) for line in dump.read_text().splitlines() if "=" in line)
    assert seen["VC"] == "true" and seen["CWD"].endswith("/work") and "arva-tool-home-" in seen["HOME"]
    assert dump.read_text().splitlines()[3:] == []  # the working directory was empty
    assert not (storage_root / "results" / project["id"] / "_project" / job["id"]).exists()
    # Inputs are staged as copies, so removing the failed job's files never touches other jobs' outputs.
    assert source.stat().st_mode & 0o777 == 0o444
    assert [j["id"] for j in client.get(f"{API}/projects/{project['id']}/jobs").json()] == [job["id"]]


def test_project_jobs_listing_and_job_project_id(client, project):
    a = new_sample(client, project, "ISO-001")
    upload(client, a["id"], R1)
    jobs = client.post(f"{API}/samples/{a['id']}/analyses/sequence-stats", json={}).json()
    assert jobs[0]["project_id"] == project["id"] and jobs[0]["sample_id"] == a["id"]
    assert client.get(f"{API}/projects/{project['id']}/jobs").json() == []
    assert client.get(f"{API}/projects/missing/jobs").status_code == 404


def multiqc_ready():
    tools = ["fastqc", "fastp", "seqkit", "filtlong", "multiqc"]
    return all(detect(t, refresh=True).status is ToolStatus.available for t in tools)


needs_multiqc = pytest.mark.skipif(not multiqc_ready(),
                                   reason="needs MultiQC 1.35 (ARVA_TOOL_MULTIQC), FastQC, fastp, SeqKit, Filtlong")


@needs_multiqc
def test_multiqc_end_to_end(client, project, storage_root):
    a = new_sample(client, project, "ISO-001")
    b = new_sample(client, project, "ISO-002")
    r1, r2 = upload(client, a["id"], R1, R2)
    (ont,) = upload(client, b["id"], ONT)
    validate(client, a, r1, r2)
    validate(client, b, ont)
    for sample, files, tool in ((a, [r1, r2], "fastqc"), (b, [ont], "seqkit")):
        jobs = client.post(f"{API}/samples/{sample['id']}/analyses/{tool}", json={"raw_file_ids": [f["id"] for f in files]})
        assert jobs.status_code == 202, jobs.text
    assert client.post(f"{API}/samples/{a['id']}/filtering/fastp",
                       json={"read1_file_id": r1["id"], "read2_file_id": r2["id"]}).status_code == 202
    assert client.post(f"{API}/samples/{b['id']}/filtering/filtlong",
                       json={"file_id": ont["id"], "params": {"keep_percent": 90}}).status_code == 202

    r = client.post(f"{API}/projects/{project['id']}/analyses/multiqc", json={})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"]
    assert job["sample_id"] is None and job["tool_version"] == "1.35"
    assert all(p.startswith(f"results/{project['id']}/_project/{job['id']}/") for p in job["output_paths"])
    argv = job["commands"][0]
    assert "--no-version-check" in argv and argv[argv.index("--file-list") + 1].endswith("/inputs.txt")
    assert "MULTIQC_NO_VERSION_CHECK=true" in job["log_text"] and "every input found once" in job["log_text"]
    assert len(job["parameters"]["inputs"]) == 5 and set(job["input_raw_file_ids"]) == {r1["id"], r2["id"], ont["id"]}

    s = job["result_summary"]
    assert s["multiqc_version"] == "1.35" and s["modules"] == ["fastqc", "fastp", "seqkit", "filtlong"]
    assert s["versions"]["arva_jobs"]["FastQC"] and s["versions"]["reported_by_multiqc"]["fastp"]
    rows = {row["name"]: row["values"] for row in s["general_stats"]["rows"]}
    assert set(rows) == {"ISO-001 R1", "ISO-001 R2", "ISO-001 R1+R2", "ISO-002 SYNTHETIC_nanopore_reads"}
    fastp_job = next(j for j in client.get(f"{API}/samples/{a['id']}/jobs").json() if j["job_type"] == "fastp")
    assert rows["ISO-001 R1+R2"]["fastp"]["filtering_result_passed_filter_reads"] == \
        fastp_job["result_summary"]["filtering_result"]["passed_filter_reads"]
    assert rows["ISO-001 R1"]["fastqc"]["total_sequences"] == 2000
    assert rows["ISO-002 SYNTHETIC_nanopore_reads"]["seqkit"]["num_seqs"] == 400
    units = {(c["module"], c["key"]): c["unit"] for c in s["general_stats"]["columns"]}
    assert units[("fastp", "after_filtering_gc_content")] == "fraction"

    html = client.get(f"{API}/jobs/{job['id']}/outputs/arva_multiqc_report.html")
    assert html.status_code == 200 and html.headers["content-security-policy"] == MULTIQC_REPORT_CSP
    assert html.headers["x-content-type-options"] == "nosniff" and html.headers["referrer-policy"] == "no-referrer"
    assert STORAGE_SHIM in html.content and "ISO-001 R1+R2" in html.text and str(storage_root) not in html.text
    data = client.get(f"{API}/jobs/{job['id']}/outputs/multiqc_data.json")
    assert data.status_code == 200 and json.loads(data.content)["config_version"] == "1.35"

    listed = client.get(f"{API}/projects/{project['id']}/jobs").json()
    assert [j["id"] for j in listed] == [job["id"]]
    recent = client.get(f"{API}/dashboard").json()["recent_jobs"]
    assert any(j["id"] == job["id"] and j["sample_id"] is None for j in recent)

    assert client.delete(f"{API}/projects/{project['id']}").status_code == 204
    assert client.get(f"{API}/jobs/{job['id']}").status_code == 404


@needs_multiqc
def test_multiqc_report_in_chromium(client, project, report_browser_check):
    """The served report under the sandboxed CSP: plots render, no request leaves the page, and a script in it
    can neither use ARVA's origin nor script a same-origin window (scripts/check_multiqc_report.cjs)."""
    a = new_sample(client, project, "ISO-001")
    (r1,) = upload(client, a["id"], R1)
    validate(client, a, r1)
    assert client.post(f"{API}/samples/{a['id']}/analyses/fastqc", json={"raw_file_ids": [r1["id"]]}).status_code == 202
    job = client.post(f"{API}/projects/{project['id']}/analyses/multiqc", json={}).json()
    assert client.get(f"{API}/jobs/{job['id']}").json()["status"] == "completed"
    result = report_browser_check("check_multiqc_report.cjs",
                                  client.get(f"{API}/jobs/{job['id']}/outputs/arva_multiqc_report.html"))
    assert result["documentOrigin"] == "null" and result["escape"]["scriptable"] is False
    assert result["rendered"]["plots"] > 0 and result["external"] == []


def test_migration_up_and_down_on_a_scratch_database(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.core.config import get_settings
    from app.db.session import engine

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    try:
        command.upgrade(cfg, "ee0125d444ac")
        with db.begin() as c:
            c.execute(text("INSERT INTO projects (id, name, is_demo, created_at, updated_at) VALUES ('p', 'P', false, now(), now())"))
            c.execute(text("INSERT INTO samples (id, project_id, sample_code, sequencing_technology, created_at, updated_at) "
                           "VALUES ('s', 'p', 'S', 'unknown', now(), now())"))
            c.execute(text("INSERT INTO analysis_jobs (id, sample_id, job_type, tool_name, tool_version, status, created_at, "
                           "updated_at) VALUES ('j', 's', 'fastqc', 'FastQC', '0.12.1', 'completed', now(), now())"))
        command.upgrade(cfg, "head")
        with db.begin() as c:
            assert c.scalar(text("SELECT project_id FROM analysis_jobs WHERE id = 'j'")) == "p"
            fk = c.execute(text("SELECT confdeltype FROM pg_constraint WHERE conname = 'fk_analysis_jobs_project_id'")).scalar()
            assert fk == "c"
            nullable = dict(c.execute(text("SELECT column_name, is_nullable FROM information_schema.columns "
                                           "WHERE table_name = 'analysis_jobs' AND column_name IN ('project_id', 'sample_id')")).all())
            assert nullable == {"project_id": "NO", "sample_id": "YES"}
            c.execute(text("INSERT INTO analysis_jobs (id, project_id, job_type, tool_name, tool_version, status, created_at, "
                           "updated_at) VALUES ('m', 'p', 'multiqc', 'MultiQC', '1.35', 'completed', now(), now())"))
        with pytest.raises(RuntimeError, match="project-level analysis job"):
            command.downgrade(cfg, "ee0125d444ac")
        with db.begin() as c:
            c.execute(text("DELETE FROM analysis_jobs WHERE id = 'm'"))
        command.downgrade(cfg, "ee0125d444ac")
        with db.begin() as c:
            cols = {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'analysis_jobs'"))}
            assert "project_id" not in cols
            assert c.scalar(text("SELECT sample_id FROM analysis_jobs WHERE id = 'j'")) == "s"
        command.upgrade(cfg, "head")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch"))

