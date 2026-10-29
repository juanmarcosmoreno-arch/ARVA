"""The error log (app.core.errorlog) and the diagnostic report (GET /system/diagnostics): one entry per source,
rotation and cap, the fallback when the data folder cannot be used, redaction of what must never leave the computer,
stable anonymisation, and the web interface's bounded error endpoint."""
import io
import json
import re
import signal
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from arva_tools import ToolExecutionError, ToolStatus
from fastapi.testclient import TestClient
from test_api import FASTQ, make_project, make_sample, upload

from app.api.routes import diagnostics as diagnostics_routes
from app.core import errorlog
from app.core.config import get_settings
from app.core.redaction import redact
from app.db.session import SessionLocal
from app.main import app
from app.models import AnalysisJob
from app.services import diagnostics, locations, performance, startup
from app.tasks import worker_events
from app.tasks.common import JobFailure, run_job

API = "/api/v1"
ENTRY_ID = re.compile(errorlog.ID_PATTERN)
# Things that must never appear in an entry or a report, injected wherever a test can.
SECRETS = ("hunter2", "jmoreno", "jm@example.org", "C02XG2JHJG5J", "ACGTACGTTTGACCAGTAGGACCATTAGGCAT",
           "ghp_abcdefghijklmnop123456", "arva_dev_password")
POISON = ("failed for postgresql://arva:hunter2@postgres:5432/arva in /Users/jmoreno/runs/x.fastq "
          "(owner jm@example.org, Serial Number (system): C02XG2JHJG5J, read ACGTACGTTTGACCAGTAGGACCATTAGGCAT, "
          "token ghp_abcdefghijklmnop123456)")


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    """A data folder of its own (marked and recorded), so that its logs can be read back."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(get_settings(), "storage_root", data)
    with SessionLocal() as db:
        recorded = locations._recorded(db)
    if recorded:  # a TestClient started first recorded the suite's data folder
        (data / locations.MARKER).write_text(json.dumps({"id": recorded}))
    errorlog.reset_storage_check()
    errorlog._refusal_seen.clear()
    locations.ensure_data()
    yield data / "logs"
    errorlog.reset_storage_check()


def entries(logdir, name=errorlog.ERRORS) -> list[dict]:
    path = logdir / name
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def entry(logdir, entry_id: str) -> dict:
    return next(e for e in entries(logdir) if e["id"] == entry_id)


def assert_clean(text: str):
    for secret in SECRETS:
        assert secret not in text, secret


def test_redaction_removes_what_must_never_leave_the_computer():
    out = redact(POISON + " ARVA_DB_PASSWORD=s3cret api_key: 'k-9' Authorization: Bearer abcdefghijkl1234 "
                 "IOPlatformUUID = \"12345678-1234-1234-1234-123456789ABC\" /home/alice/x "
                 + "MKVLAAGIVALLLAAGCSSHHHHHHENLYFQ" + " " + "Q" * 120)
    assert_clean(out)
    for gone in ("s3cret", "k-9", "abcdefghijkl1234", "123456789ABC", "alice", "Q" * 100, "MKVLAAGIVALLLAAGCSS"):
        assert gone not in out
    assert "postgresql://***@postgres:5432/arva" in out and "~/runs/x.fastq" in out and "<email>" in out
    assert "<serial>" in out and "<sequence: 32 letters>" in out and "~/x" in out


def test_an_unexpected_api_error_is_logged_with_its_id_and_route_and_the_id_is_returned(logdir, monkeypatch):
    def broken(db):
        raise RuntimeError(POISON)

    monkeypatch.setattr(performance, "overview", broken)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get(f"{API}/system/performance?secret_query=hunter2")
        assert r.status_code == 500
        body = r.json()
        assert body["code"] == "internal_error" and ENTRY_ID.fullmatch(body["error_id"])
        assert body["params"] == {"error_id": body["error_id"]} and body["error_id"] in body["detail"]
        cid = r.headers["x-arva-correlation-id"]
        listed = c.get(f"{API}/system/errors").json()
    e = entry(logdir, body["error_id"])
    assert e["component"] == "api" and e["severity"] == "error" and e["correlation_id"] == cid
    assert e["request"] == {"method": "GET", "route": f"{API}/system/performance", "status": 500}
    assert e["version"] and e["commit"] and e["exception"]["type"] == "RuntimeError"
    assert any(f.startswith("app/api/routes/system.py:") for f in e["exception"]["traceback"])
    assert any(f.startswith("… ") and "library frame" in f for f in e["exception"]["traceback"])
    assert_clean(json.dumps(e))
    assert listed[0]["id"] == body["error_id"] and listed[0]["route"] == f"{API}/system/performance"


def _job(sample: dict, project: dict, correlation: str | None = None) -> str:
    token = errorlog.correlation.set(correlation)
    try:
        with SessionLocal() as db:
            job = AnalysisJob(project_id=project["id"], sample_id=sample["id"], job_type="seqkit_stats",
                              tool_name="SeqKit", tool_version="2.3.0", parameters={"threads": 4, "note": POISON})
            db.add(job)
            db.commit()
            return job.id
    finally:
        errorlog.correlation.reset(token)


def test_a_failed_job_is_logged_with_the_end_of_the_tools_output_and_its_request(client, logdir):
    project, cid = make_project(client), "0123456789abcdef"
    sample = make_sample(client, project["id"])
    job_id = _job(sample, project, cid)
    stderr = "\n".join(f"line {n}" for n in range(1, 101)) + "\n" + POISON

    def body(ctx):
        raise ToolExecutionError("seqkit exited with status 1", 1, stderr_tail=stderr)

    assert run_job(job_id, body) == "failed"
    e = next(x for x in entries(logdir) if (x.get("job") or {}).get("id") == job_id)
    assert e["component"] == "job" and e["code"] == "job_failed" and e["correlation_id"] == cid
    assert e["job"]["type"] == "seqkit_stats" and e["tool"] == {"name": "SeqKit", "version": "2.3.0"}
    tail = e["stderr_tail"].splitlines()
    assert len(tail) == errorlog.STDERR_TAIL_LINES and tail[0] == "line 42" and "line 41" not in tail
    assert e["message"] == "seqkit exited with status 1" and e["exception"]["type"].endswith("ToolExecutionError")
    assert_clean(json.dumps(e))
    events = [x["event"] for x in entries(logdir, errorlog.APP) if (x.get("job") or {}).get("id") == job_id]
    assert events == ["job_started", "job_finished"]


def test_a_coded_job_failure_and_a_cancellation_keep_their_codes(client, logdir):
    project = make_project(client)
    sample = make_sample(client, project["id"])
    job_id = _job(sample, project)

    def body(ctx):
        raise JobFailure("input file x no longer exists", "input_missing", file_id="x")

    run_job(job_id, body)
    e = next(x for x in entries(logdir) if (x.get("job") or {}).get("id") == job_id)
    assert e["code"] == "input_missing" and e["params"] == {"job_type": "seqkit_stats", "file_id": "x"}


def test_worker_crashes_and_task_errors_are_logged(logdir):
    rq_job = SimpleNamespace(id="arva-1b2c", func_name="app.tasks.tools.run_seqkit_job")
    worker_events.on_work_horse_killed(rq_job, 4242, signal.SIGKILL, SimpleNamespace(ru_maxrss=2048000))
    try:
        raise LookupError("analysis job 1b2c not found")
    except LookupError as exc:
        assert worker_events.on_exception(rq_job, LookupError, exc, exc.__traceback__) is True
    crash, failed = (next(e for e in entries(logdir) if e["code"] == code)
                     for code in ("worker_crashed", "worker_task_failed"))
    assert crash["component"] == "worker" and crash["params"] == {"status": "signal SIGKILL"}
    assert crash["job"]["id"] == "1b2c" and crash["details"] == {"pid": 4242, "signal": "SIGKILL", "max_rss_kb": 2048000}
    assert failed["exception"]["type"] == "LookupError" and failed["params"]["task"] == "app.tasks.tools.run_seqkit_job"
    assert failed["exception"]["traceback"][0].startswith("tests/") is False


def test_the_web_error_endpoint_keeps_bounded_redacted_reports_and_limits_their_rate(client, logdir, monkeypatch):
    report = {"kind": "boundary", "message": "Cannot read properties of undefined " + POISON, "name": "TypeError",
              "stack": "TypeError: x\n    at Panel (http://localhost:8080/assets/index-abc.js:12:34)\n" * 40,
              "page": "/samples/6f1c2a7e-0000-4000-8000-000000000000", "client_commit": "abc1234"}
    r = client.post(f"{API}/system/client-errors", json=report)
    assert r.status_code == 201 and not r.json()["duplicate"]
    e = entry(logdir, r.json()["id"])
    assert e["component"] == "web" and e["code"] == "web_error" and e["details"]["page"] == "/samples/{…}"
    assert len(e["details"]["stack"]) == 25 and "localhost:8080" not in json.dumps(e)
    assert_clean(json.dumps(e))
    again = client.post(f"{API}/system/client-errors", json=report).json()
    assert again == {"id": r.json()["id"], "duplicate": True}

    api_failure = {"kind": "api", "message": "502 Bad Gateway",
                   "api": {"method": "GET", "path": "/api/v1/samples/KP-HOSP-17/files?x=hunter2", "status": 502}}
    e = entry(logdir, client.post(f"{API}/system/client-errors", json=api_failure).json()["id"])
    assert e["code"] == "web_api_failed" and e["request"] == {"method": "GET", "route": "/api/v1/samples/{…}/files",
                                                              "status": 502}

    big = client.post(f"{API}/system/client-errors", content=b"{" + b" " * 20000 + b"}",
                      headers={"content-type": "application/json"})
    assert big.status_code == 413 and big.json()["code"] == "client_error_too_large"
    for bad in ({**report, "extra": 1}, {**report, "message": "x" * 1001}, {**report, "kind": "other"}):
        r = client.post(f"{API}/system/client-errors", json=bad)
        assert r.status_code == 422 and r.json()["code"] == "client_error_invalid"
        assert "x" * 50 not in r.text
    monkeypatch.setattr(diagnostics_routes, "_client_limit", errorlog.RateLimit(1, 60.0))
    assert client.post(f"{API}/system/client-errors", json={**report, "message": "one"}).status_code == 201
    limited = client.post(f"{API}/system/client-errors", json={**report, "message": "two"})
    assert limited.status_code == 429 and limited.json()["code"] == "client_error_rate_limited"


def test_coded_refusals_are_kept_at_info_level_once_in_a_while(client, logdir):
    (logdir.parent / locations.MARKER).unlink()
    errorlog.reset_storage_check()
    for _ in range(3):
        r = client.post(f"{API}/projects", json={"name": "x"})
        assert r.status_code == 503 and r.json()["code"] == "storage_missing"
    kept = errorlog.read(limit=50, match=lambda e: e["code"] == "storage_missing" and e.get("request"))
    assert len(kept) == 1 and kept[0]["severity"] == "info" and kept[0]["request"]["route"] == f"{API}/projects"


def test_logs_rotate_by_size_and_stay_under_their_cap(logdir, monkeypatch):
    monkeypatch.setitem(errorlog.LIMITS, errorlog.ERRORS, (4000, 2))
    ids = [errorlog.record("api", "error", "internal_error", "word " * 60) for _ in range(60)]
    files = sorted(p.name for p in logdir.glob("errors.jsonl*"))
    assert files == ["errors.jsonl", "errors.jsonl.1", "errors.jsonl.2"]
    assert all((logdir / f).stat().st_size <= 4000 for f in files)
    kept = [e["id"] for f in files for e in entries(logdir, f)]
    assert ids[-1] in kept and ids[0] not in kept
    assert [e["id"] for e in errorlog.read(limit=3)] == ids[:-4:-1]


def test_without_its_disk_nothing_is_written_and_the_entry_goes_to_stderr(logdir, capsys):
    (logdir.parent / locations.MARKER).unlink()
    errorlog.reset_storage_check()
    before = entries(logdir)
    entry_id = errorlog.record("api", "error", "internal_error", POISON)
    assert entries(logdir) == before
    err = capsys.readouterr().err
    assert entry_id in err and "data folder not available" in err
    assert_clean(err)
    assert errorlog.read(limit=5, match=lambda e: e["id"] == entry_id)


def test_start_up_problems_are_logged(logdir, monkeypatch):
    from arva_tools import DetectedTool, registry

    bakta = DetectedTool(registry.get_adapter("bakta").info, ToolStatus.incompatible, "/usr/bin/bakta", "1.0",
                         message="Version 1.0 is older than 1.9", reason="too_old")
    monkeypatch.setattr(registry, "detect_all", lambda refresh=False: [bakta])
    startup.check()
    e = next(x for x in entries(logdir) if x["code"] == "startup_tools_unusable")
    assert e["params"] == {"tools": "bakta"} and e["severity"] == "warning"
    assert not [x for x in entries(logdir) if x["code"] == "startup_migrations_pending"]
    assert any(x["event"] == "startup_checks" for x in entries(logdir, errorlog.APP))

    def fail(cfg, rev):
        raise RuntimeError("could not connect to server at postgres://arva:hunter2@postgres")

    monkeypatch.setattr("alembic.command.upgrade", fail)
    assert startup.migrate() == 1
    e = next(x for x in entries(logdir) if x["code"] == "startup_migration_failed")
    assert e["exception"]["type"] == "RuntimeError" and "hunter2" not in json.dumps(e)


def _failed_job(client, project, sample) -> str:
    job_id = _job(sample, project)

    def body(ctx):
        ctx.log("Reading KP-HOSP-17_R1.fastq for sample KP-HOSP-17 " + POISON)
        raise ToolExecutionError("seqkit could not read KP-HOSP-17_R1.fastq", 2, stderr_tail=POISON)

    run_job(job_id, body)
    return job_id


def test_the_report_for_a_job_has_its_details_and_never_what_must_stay(client, logdir, monkeypatch):
    monkeypatch.setenv("ARVA_SECRET_TOKEN", "hunter2")
    project = make_project(client, "Klebsiella outbreak 2026")
    sample = make_sample(client, project["id"], code="KP-HOSP-17")
    assert upload(client, sample["id"], "KP-HOSP-17_R1.fastq", FASTQ.encode()).status_code == 201
    job_id = _failed_job(client, project, sample)

    md = client.get(f"{API}/system/diagnostics", params={"job_id": job_id}).text
    assert f"## Job {job_id}" in md and "| status | failed |" in md and "seqkit could not read" in md
    assert "Log (last 80 lines):" in md and "## Recent errors" in md and "## Tools" in md and "## Storage" in md
    assert "Error log entries of this job:" in md and "## Migrations" in md
    assert_clean(md)
    report = client.get(f"{API}/system/diagnostics", params={"job_id": job_id, "format": "json"}).json()
    assert report["job"]["related_errors"][0]["job"]["id"] == job_id
    assert report["migrations"]["up_to_date"] is True and report["options"]["job_id"] == job_id
    assert_clean(json.dumps(report))
    archive = client.get(f"{API}/system/diagnostics", params={"job_id": job_id, "format": "zip"})
    assert archive.headers["content-disposition"].startswith('attachment; filename="arva-diagnostics-')
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert names == ["arva-diagnostics.md", "arva-diagnostics.json"]

    without = client.get(f"{API}/system/diagnostics", params={"job_id": job_id, "include_logs": "false"}).text
    assert "Log (last 80 lines):" not in without and "Traceback" not in without and "Tool output" not in without

    missing = client.get(f"{API}/system/diagnostics", params={"job_id": "00000000-0000-4000-8000-000000000000"})
    assert missing.status_code == 404 and missing.json()["code"] == "diagnostics_not_found"
    assert client.get(f"{API}/system/diagnostics", params={"job_id": "../etc"}).status_code == 422
    assert client.get(f"{API}/system/diagnostics", params={"errors": 1000}).status_code == 422


def test_anonymised_reports_use_the_same_placeholders_every_time(client, logdir):
    project = make_project(client, "Klebsiella outbreak 2026")
    sample = make_sample(client, project["id"], code="KP-HOSP-17")
    assert upload(client, sample["id"], "KP-HOSP-17_R1.fastq", FASTQ.encode()).status_code == 201
    job_id = _failed_job(client, project, sample)

    def report() -> str:
        return client.get(f"{API}/system/diagnostics", params={"job_id": job_id, "anonymise": "true"}).text

    first = report()
    for name in ("Klebsiella outbreak 2026", "KP-HOSP-17"):
        assert name not in first
    assert "file-1 for sample sample-1" in first and "seqkit could not read file-1" in first
    with SessionLocal() as db:
        before = diagnostics.Anonymiser(db).mapping
    later = make_project(client, "Another project")
    make_sample(client, later["id"], code="OTHER-1")
    with SessionLocal() as db:
        after = diagnostics.Anonymiser(db).mapping
    assert {k: after[k] for k in before} == before and after["OTHER-1"] == "sample-2"
    assert before["KP-HOSP-17_R1.fastq"] == "file-1" and before["Klebsiella outbreak 2026"] == "project-1"
    assert "project-2" not in first


def test_a_report_for_an_error_id_has_that_error_in_full(client, logdir):
    project = make_project(client)
    sample = make_sample(client, project["id"])
    job_id = _failed_job(client, project, sample)
    error_id = next(e["id"] for e in entries(logdir) if (e.get("job") or {}).get("id") == job_id)
    md = client.get(f"{API}/system/diagnostics", params={"error_id": error_id, "errors": 0}).text
    assert "## The error" in md and f"### {error_id}" in md and f"## Job {job_id}" in md
    assert "## Recent errors (0)" in md
    gone = client.get(f"{API}/system/diagnostics", params={"error_id": "ZZZZ-ZZZZ"})
    assert gone.status_code == 404 and gone.json()["params"] == {"what": "error", "value": "ZZZZ-ZZZZ"}


def test_every_entry_and_refusal_code_has_a_text_in_the_interface():
    i18n = (Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "i18n" / "index.ts").read_text()
    en = i18n[: i18n.index("const es:")]
    keys = set(re.findall(r'^  "([^"]+)":', en, re.M))
    missing = [f"diagnostics.code.{c}" for c in errorlog.MESSAGES if f"diagnostics.code.{c}" not in keys]
    missing += [f"api.error.{c}" for c in ("internal_error", "diagnostics_not_found") if f"api.error.{c}" not in keys]
    assert missing == []
