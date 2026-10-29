"""Stable codes next to the English messages the interface shows, so it can show them in the user's language."""
import ast
import re
import stat
import sys
from pathlib import Path

import pytest
from arva_core.formats import check_pod5
from arva_core.seqstats import compute_sequence_stats, quick_validate

from app.core.messages import render
from app.tasks.common import JobFailure, _detail

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "examples" / "synthetic" / "SYNTHETIC_illumina_R1_001.fastq.gz"
I18N = ROOT / "apps" / "web" / "src" / "i18n" / "index.ts"


def test_render_follows_the_interface_template_syntax():
    template = "{count, plural, =0 {no file} one {# file} other {# files}} in {where}"
    assert render(template, {"count": 0, "where": "S1"}) == "no file in S1"
    assert render(template, {"count": 1, "where": "S1"}) == "1 file in S1"
    assert render(template, {"count": 12345, "where": "S1"}) == "12,345 files in S1"
    nested = "{n, plural, one {# cell ({cells}) has} other {# cells ({cells}) have}} no value"
    assert render(nested, {"n": 2, "cells": "A1, B2"}) == "2 cells (A1, B2) have no value"
    assert render("No placeholders.", {}) == "No placeholders."


def test_detail_records_only_coded_failures():
    assert _detail(JobFailure("input file f no longer exists", "input_missing", file_id="f")) == {
        "code": "input_missing", "params": {"file_id": "f"}}
    assert _detail(JobFailure("free text")) is None
    assert _detail(ValueError("boom")) is None


def _codes(path: Path, call: str) -> set[str]:
    """Second positional argument of every `call(...)` whose second argument is a string constant."""
    codes = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == call and len(node.args) > 1:
            if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                codes.add(node.args[1].value)
    return codes


@pytest.mark.skipif(not I18N.exists(), reason="the web sources are not next to the API")
def test_every_code_the_api_sends_has_a_text_in_the_interface():
    source = I18N.read_text(encoding="utf-8")
    en = source[: source.index("const es:")]
    keys = set(re.findall(r'^  "([^"]+)":', en, re.M))
    app = ROOT / "apps" / "api" / "app"
    job_codes = set().union(*(_codes(p, "JobFailure") for p in app.rglob("*.py")))
    runner = (ROOT / "workflows" / "tool-adapters" / "arva_tools" / "runner.py").read_text()
    job_codes |= set(re.findall(r'code="(\w+)"', runner)) | {"tool_exit", "tool_timeout", "out_of_memory"}
    assert {"input_missing", "tool_unavailable", "not_fastq", "settings_rejected", "pod5_not_reads"} <= job_codes
    missing = sorted(f"job.error.{c}" for c in job_codes if f"job.error.{c}" not in keys)
    db_codes = _codes(app / "tasks" / "databases.py", "TaskFailure") | _codes(app / "tasks" / "ncbi_collection.py", "TaskFailure")
    missing += sorted(f"database.error.{c}" for c in db_codes if f"database.error.{c}" not in keys)
    files = {"verified", "corrupt", "unrecognised", "format_error", "no_records", "entire", "full_failed", "pod5_complete",
             "pod5_truncated", "twin"}
    missing += sorted(f"file.validation.{c}" for c in files if f"file.validation.{c}" not in keys)
    missing += sorted(f"upload.rejected.{c}" for c in ("duplicate", "too_large", "insufficient_storage")
                      if f"upload.rejected.{c}" not in keys)
    missing += sorted(f"seqstats.warning.{c}" for c in ("zero_length", "phred64_suspected")
                      if f"seqstats.warning.{c}" not in keys)
    assert missing == []


def test_quick_validation_and_statistics_carry_codes(tmp_path):
    ok = quick_validate(R1)
    assert (ok.code, ok.params) == ("verified", {"format": "FASTQ", "count": ok.records_checked})
    junk = tmp_path / "x.fq"
    junk.write_text("not a sequence file\n")
    assert quick_validate(junk).code == "unrecognised"
    empty_record = tmp_path / "zero.fq"
    empty_record.write_text("@r1\n\n+\n\n@r2\nACGT\n+\nIIII\n")
    stats = compute_sequence_stats(empty_record)
    assert stats["messages"] == [{"code": "zero_length", "params": {"count": 1}, "text": stats["warnings"][0]}]
    pod5 = tmp_path / "cut.pod5"
    pod5.write_bytes(b"\x8bPOD\r\n\x1a\n" + b"\0" * 64)
    assert check_pod5(pod5).code == "pod5_truncated"


@pytest.fixture
def sample(client):
    p = client.post(f"{API}/projects", json={"name": "Codes"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "C1"}).json()


def _upload(client, sample_id, name, data):
    r = client.post(f"{API}/samples/{sample_id}/files", files=[("files", (name, data, "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()


def test_uploads_and_full_validation_record_their_codes(client, sample):
    first = _upload(client, sample["id"], R1.name, R1.read_bytes())["files"][0]
    assert first["validation_detail"]["code"] == "verified"
    assert first["validation_detail"]["params"]["format"] == "FASTQ"
    again = _upload(client, sample["id"], "copy.fastq.gz", R1.read_bytes())
    assert again["rejected"][0]["code"] == "duplicate"
    assert again["rejected"][0]["params"] == {"file": R1.name}
    junk = _upload(client, sample["id"], "notes.fq", b"not a sequence file\n")["files"][0]
    assert junk["validation_detail"] == {"code": "unrecognised", "params": {}}

    (job,) = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                         json={"raw_file_ids": [first["id"]]}).json()
    assert client.get(f"{API}/jobs/{job['id']}").json()["status"] == "completed"
    files = {f["id"]: f for f in client.get(f"{API}/samples/{sample['id']}/files").json()}
    detail = files[first["id"]]["validation_detail"]
    assert detail["code"] == "entire" and detail["params"]["count"] > 0


def test_a_tool_exit_status_is_recorded_as_a_code(client, sample, tmp_path, monkeypatch):
    exe = tmp_path / "seqkit"
    exe.write_text(f"#!{sys.executable}\nimport sys\nif sys.argv[1] == 'version':\n    print('seqkit v2.3.0'); sys.exit(0)\n"
                   "sys.exit(3)\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ARVA_TOOL_SEQKIT", str(exe))
    f = _upload(client, sample["id"], R1.name, R1.read_bytes())["files"][0]
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    d = client.get(f"{API}/jobs/{j['id']}").json()
    assert d["status"] == "failed" and d["error_message"] == "seqkit exited with status 3"
    assert d["error_detail"] == {"code": "tool_exit", "params": {"tool": "seqkit", "status": 3}}


@pytest.mark.skipif(not I18N.exists(), reason="the web sources are not next to the API")
def test_the_interface_translates_the_catalogue_texts_it_shows_in_their_current_english():
    """The interface shows its translation of a catalogue text only while its English is the server's text; this
    keeps the two from drifting apart unnoticed."""
    import json

    from app.services.database_catalogue import CATALOGUE

    source = I18N.read_text(encoding="utf-8")
    en = source[: source.index("const es:")]
    for e in CATALOGUE:
        texts = {f"databases.catalogue.{e.key}.description": e.description}
        texts |= {f"databases.catalogue.{e.key}.note{i}": n for i, n in enumerate(e.notes)}
        for key, text in texts.items():
            line = f"  {json.dumps(key)}: {json.dumps(text, ensure_ascii=False)},\n"
            assert line in en, f"{key} is missing or differs from the catalogue in apps/web/src/i18n/index.ts"
