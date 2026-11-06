"""Workflow Builder and batch runs: definitions and versions, the queue (priority, concurrency, retries, pause,
cancel, resume), branches and run comparison, exports. The real-tool runs use fastp on the synthetic reads."""
import csv
import io
from pathlib import Path

import pytest
from arva_tools.registry import detect
from test_annotation_api import GENOME, assemble
from test_typing_api import typing_tools  # noqa: F401  (a fixture)

from app.db.session import SessionLocal
from app.models import AnalysisJob, BatchItem, BatchRun, JobStatus
from app.services import batches
from app.services import jobs as jobs_service
from app.services import workflow_nodes as nodes
from app.tasks.seqstats import run_sequence_stats_job

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "examples" / "synthetic" / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = ROOT / "examples" / "synthetic" / "SYNTHETIC_illumina_R2_001.fastq.gz"


def _definition(nodes_, edges):
    return {"format": "arva-workflow", "format_version": 1,
            "nodes": [{"id": i, "kind": k, "params": p, "position": {"x": 0, "y": 0}} for i, k, p in nodes_],
            "edges": [{"source": s, "source_port": sp, "target": t, "target_port": tp} for s, sp, t, tp in edges]}


FASTP = _definition([("reads", "reads_short_input", {}), ("trim", "fastp", {})], [("reads", "reads", "trim", "reads")])


@pytest.fixture
def project(client):
    return client.post(f"{API}/projects", json={"name": "Batch"}).json()


def _sample(client, project, code, reads=True):
    s = client.post(f"{API}/projects/{project['id']}/samples",
                    json={"sample_code": code, "sequencing_technology": "illumina"}).json()
    if reads:
        files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in (R1, R2)]
        assert client.post(f"{API}/samples/{s['id']}/files", files=files).status_code == 201
    return s


def _workflow(client, definition=FASTP, name="Trim"):
    r = client.post(f"{API}/workflows", json={"name": name, "definition": definition})
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, project, wf, samples, **settings):
    body = {"project_id": project["id"], "workflow_id": wf["id"], "sample_ids": [s["id"] for s in samples],
            "settings": settings, "confirmed": True}
    r = client.post(f"{API}/batches", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _items(run, node):
    return [i for i in run["items"] if i["node_id"] == node]


def test_catalogue_templates_and_parameter_schemas(client):
    cat = client.get(f"{API}/workflows/catalogue").json()
    kinds = {k["kind"]: k for k in cat["kinds"]}
    assert set(cat["port_types"]) >= {"reads_short", "reads_long", "assembly", "annotation", "comparison_set",
                                      "alignment", "tree"}
    flye = kinds["flye"]
    assert "raw_file_ids" not in flye["params_schema"]["properties"]
    assert flye["inputs"] == [{"name": "reads", "accepts": ["reads_long"], "required": True, "collection": False}]
    assert "confirmed" not in kinds["mlst"]["params_schema"]["properties"]
    assert kinds["polishing"]["tools"]["hybrid"][0]["id"] == "racon"
    assert [t["id"] for t in kinds["polishing"]["tools"]["medaka"]] == ["medaka", "minimap2", "samtools"]
    assert "medaka" in kinds["polishing"]["params_schema"]["properties"]
    templates = {t["key"]: t for t in cat["templates"]}
    assert len(templates) == 13
    assert {p["params"]["field"] for p in templates["nanopore_assembly"]["needs_parameters"]} == {"params.read_type"}
    assert cat["nextflow"] == {"generated": False, "reason_code": "wf_nextflow_not_faithful"}
    for t in templates.values():
        for p in t["unavailable"]:
            assert p["code"] == "wf_tool_unavailable" and p["params"]["tool"]


def test_definition_without_positions_gets_a_column_layout(client):
    asm = _definition([("asm", "assembly_input", {}), ("mlst", "mlst", {}), ("vir", "virulence", {})],
                      [("asm", "assembly", "mlst", "assembly"), ("asm", "assembly", "vir", "assembly")])
    nodes_ = {n["id"]: n["position"] for n in _workflow(client, asm, "Typing")["latest"]["definition"]["nodes"]}
    assert nodes_["asm"]["x"] < nodes_["mlst"]["x"] == nodes_["vir"]["x"]
    assert nodes_["mlst"]["y"] != nodes_["vir"]["y"]
    placed = _workflow(client, FASTP)["latest"]["definition"]["nodes"]
    placed[1]["position"] = {"x": 500, "y": 70}
    kept = _workflow(client, {**FASTP, "nodes": placed}, "Placed")["latest"]["definition"]["nodes"]
    assert kept[1]["position"] == {"x": 500, "y": 70}


def test_versions_duplicates_validation_and_export(client):
    wf = _workflow(client)
    assert [v["version"] for v in wf["versions"]] == [1]
    params = wf["latest"]["definition"]["nodes"][1]["params"]["params"]
    assert params["qualified_quality_phred"] == 15
    changed = wf["latest"]["definition"]
    changed["nodes"][1]["params"]["params"]["qualified_quality_phred"] = 20
    r = client.post(f"{API}/workflows/{wf['id']}/versions", json={"definition": changed, "note": "Q20"})
    v2 = r.json()
    assert [v["version"] for v in v2["versions"]] == [1, 2]
    assert v2["versions"][0]["definition_sha256"] != v2["versions"][1]["definition_sha256"]
    first = client.get(f"{API}/workflows/{wf['id']}", params={"version": 1}).json()["selected"]
    assert first["definition"]["nodes"][1]["params"]["params"]["qualified_quality_phred"] == 15

    bad = _definition([("reads", "reads_short_input", {}), ("asm", "flye", {"params": {"read_type": "nano-hq"}})],
                      [("reads", "reads", "asm", "reads")])
    r = client.post(f"{API}/workflows/{wf['id']}/versions", json={"definition": bad})
    assert r.status_code == 400 and r.json()["code"] == "wf_edge_type"
    check = client.post(f"{API}/workflows/validate", json=bad).json()
    assert check["problems"][0]["params"] == {"port": "reads", "given": "reads_short", "expected": "reads_long"}
    params_bad = _definition([("reads", "reads_short_input", {}),
                              ("trim", "fastp", {"params": {"qualified_quality_phred": 200}})],
                             [("reads", "reads", "trim", "reads")])
    check = client.post(f"{API}/workflows/validate", json=params_bad).json()
    assert [(p["code"], p["params"]["field"]) for p in check["problems"]] == [
        ("wf_param", "params.qualified_quality_phred")]

    copy = client.post(f"{API}/workflows/{wf['id']}/duplicate", json={"name": "Copy", "version": 1}).json()
    assert copy["duplicated_from_id"] == wf["id"]
    assert copy["versions"][0]["definition_sha256"] == v2["versions"][0]["definition_sha256"]

    export = client.get(f"{API}/workflows/{wf['id']}/export").json()
    assert export["workflow"]["version"] == 2 and export["definition_sha256"] == v2["versions"][1]["definition_sha256"]
    assert set(export["tools"]) == {"fastp"} and export["nextflow"]["generated"] is False
    imported = client.post(f"{API}/workflows/import", params={"name": "Imported"}, json=export).json()
    assert imported["latest"]["definition_sha256"] == export["definition_sha256"]

    t = client.post(f"{API}/workflows", json={"name": "AMR", "template_key": "amr_screening"}).json()
    assert {n["kind"] for n in t["latest"]["definition"]["nodes"]} == {"annotation_input", "amrfinderplus"}
    assert client.post(f"{API}/workflows", json={"name": "x", "template_key": "nope"}).json()["code"] == \
        "wf_template_unknown"


def _fake_fastp(monkeypatch, fail_first: int = 0):
    """fastp's node replaced by an ARVA statistics job on R1 (fast, real), failing `fail_first` times by naming a
    file that does not exist."""
    calls = []

    def launch(ctx):
        calls.append(ctx.sample.id)
        bad = len(calls) <= fail_first
        raw = "missing-file" if bad else ctx.inputs["reads"]["r1"]
        (job,) = [jobs_service.new_sequence_stats_job(ctx.sample, raw, {})]
        ctx.db.add(job)
        ctx.db.commit()
        jobs_service.enqueue_sequence_stats([job])
        return job

    kind = nodes.KINDS["fastp"]
    monkeypatch.setitem(nodes.KINDS, "fastp", nodes.Kind(kind.model, kind.bound, kind.placeholders, launch,
                                                         lambda db, job: {"reads": {"r1": job.input_raw_file_ids[0]}}, None))
    return calls


def test_retries_failure_propagation_and_error_summary(client, project, monkeypatch):
    calls = _fake_fastp(monkeypatch, fail_first=2)
    a, b = _sample(client, project, "A"), _sample(client, project, "B", reads=False)
    two = _definition([("reads", "reads_short_input", {}), ("trim", "fastp", {}), ("again", "fastp", {})],
                      [("reads", "reads", "trim", "reads"), ("trim", "reads", "again", "reads")])
    wf = _workflow(client, two)
    preview = client.post(f"{API}/batches/preview", json={"project_id": project["id"], "workflow_id": wf["id"],
                                                          "sample_ids": [a["id"], b["id"]]}).json()
    assert [r["ready"] for r in preview["samples"]] == [True, False]
    assert preview["samples"][1]["sources"]["reads"]["code"] == "wf_source_pair"
    run = _run(client, project, wf, [a, b], max_retries=1)
    assert run["status"] == "completed_with_errors"
    trim_a = next(i for i in _items(run, "trim") if i["sample_id"] == a["id"])
    assert trim_a["status"] == "failed" and len(trim_a["job_ids"]) == 2 and trim_a["error"]["code"] == "input_missing"
    assert {i["status"] for i in _items(run, "again")} == {"skipped"}
    assert {i["status"] for i in _items(run, "reads")} == {"completed", "failed"}
    assert calls == [a["id"], a["id"]]
    assert {(e["node_id"], e["code"]) for e in run["errors"]} == {
        ("reads", "wf_source_pair"), ("trim", "input_missing"), ("trim", "wf_upstream"), ("again", "wf_upstream")}
    assert run["counts"]["failed"] == 1 and run["counts"]["skipped"] == 3

    resumed = client.post(f"{API}/batches/{run['id']}/resume").json()
    trim_a = next(i for i in _items(resumed, "trim") if i["sample_id"] == a["id"])
    assert trim_a["status"] == "completed" and len(trim_a["job_ids"]) == 3
    assert next(i for i in _items(resumed, "again") if i["sample_id"] == a["id"])["status"] == "completed"
    with SessionLocal() as db:
        job = db.get(AnalysisJob, trim_a["job_id"])
        assert job.job_type == "sequence_stats" and job.status is JobStatus.completed
        assert job.correlation_id == resumed["correlation_id"]


def test_priority_concurrency_pause_cancel(client, project, monkeypatch, held_queue):
    _fake_fastp(monkeypatch)
    samples = [_sample(client, project, c) for c in ("S1", "S2", "S3")]
    wf = _workflow(client)
    low = _run(client, project, wf, samples, max_concurrent=2, priority=0)
    threads = low["settings"]["threads_per_job"]
    assert threads == low["settings"]["budget_threads"] == 4
    assert [i["status"] for i in _items(low, "trim")] == ["queued", "waiting", "waiting"]
    high = _run(client, project, wf, samples[:1], priority=5)
    assert [i["status"] for i in _items(high, "trim")] == ["waiting"]
    queue = client.get(f"{API}/batches/queue").json()
    assert (queue["counts"]["queued"], queue["counts"]["waiting"], queue["reserved_threads"]) == (1, 3, threads)

    run_sequence_stats_job(_items(low, "trim")[0]["job_id"])
    high = client.get(f"{API}/batches/{high['id']}").json()
    low = client.get(f"{API}/batches/{low['id']}").json()
    assert [i["status"] for i in _items(high, "trim")] == ["queued"]
    assert [i["status"] for i in _items(low, "trim")] == ["completed", "waiting", "waiting"]

    assert client.post(f"{API}/batches/{low['id']}/pause").json()["status"] == "paused"
    run_sequence_stats_job(_items(high, "trim")[0]["job_id"])
    assert client.get(f"{API}/batches/{high['id']}").json()["status"] == "completed"
    low = client.get(f"{API}/batches/{low['id']}").json()
    assert [i["status"] for i in _items(low, "trim")] == ["completed", "waiting", "waiting"]
    low = client.post(f"{API}/batches/{low['id']}/resume").json()
    assert [i["status"] for i in _items(low, "trim")] == ["completed", "queued", "waiting"]
    again = client.post(f"{API}/batches/{low['id']}/resume")
    assert again.status_code == 409 and again.json()["code"] == "wf_run_running"

    cancelled = client.post(f"{API}/batches/{low['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert [i["status"] for i in _items(cancelled, "trim")] == ["completed", "cancelled", "cancelled"]
    with SessionLocal() as db:
        assert db.get(AnalysisJob, _items(cancelled, "trim")[1]["job_id"]).status is JobStatus.cancelled
    assert client.post(f"{API}/batches/{low['id']}/cancel").json()["code"] == "wf_run_finished"
    runs = client.get(f"{API}/batches", params={"project_id": project["id"]}).json()
    assert {r["status"] for r in runs} == {"completed", "cancelled"}


def test_job_cancelled_from_its_own_page_updates_the_run(client, project, monkeypatch, held_queue):
    _fake_fastp(monkeypatch)
    run = _run(client, project, _workflow(client), [_sample(client, project, "C1")])
    job_id = _items(run, "trim")[0]["job_id"]
    assert client.post(f"{API}/jobs/{job_id}/cancel").status_code == 202
    run = client.get(f"{API}/batches/{run['id']}").json()
    assert run["status"] == "completed_with_errors" and _items(run, "trim")[0]["error"]["code"] == "wf_job_cancelled"


@pytest.mark.skipif(detect("fastp").status.value != "available", reason="fastp is not installed")
def test_real_fastp_run_branch_compare_and_exports(client, project):
    a = _sample(client, project, "R1S")
    wf = _workflow(client)
    run = _run(client, project, wf, [a])
    assert run["status"] == "completed", run["errors"]
    trim = _items(run, "trim")[0]
    with SessionLocal() as db:
        runs_before = db.query(BatchRun).count()
    assert trim["tool"] == "fastp" and set(trim["outputs"]["reads"]) == {"r1", "r2", "unpaired"}
    with SessionLocal() as db:
        job = db.get(AnalysisJob, trim["job_id"])
        assert job.job_type == "fastp" and job.commands and job.parameters["qualified_quality_phred"] == 15
        assert job.resources["threads"] <= trim["reserved"]["threads"] == run["settings"]["threads_per_job"]

    preview = client.post(f"{API}/batches/{run['id']}/branch/preview", json={
        "node_id": "trim", "params": {"params": {"qualified_quality_phred": 25}}}).json()
    assert preview["changes"] == [{"node": "trim", "path": "params.qualified_quality_phred", "before": 15, "after": 25}]
    assert [r["node"] for r in preview["rerun"]] == ["trim"] and preview["jobs"] == 1 and preview["problems"] == []
    assert preview["settings"] == run["settings"] and "fastp" in str(preview["tools"])
    with SessionLocal() as db:
        assert db.query(BatchRun).count() == runs_before
    branch = client.post(f"{API}/batches/{run['id']}/branch", json={
        "node_id": "trim", "params": {"params": {"qualified_quality_phred": 25}}, "confirmed": True}).json()
    assert branch["parent_run_id"] == run["id"] and branch["status"] == "completed"
    assert branch["branch_changes"] == [{"node": "trim", "path": "params.qualified_quality_phred", "before": 15,
                                         "after": 25}]
    assert _items(branch, "reads")[0]["reused_from_item_id"] == _items(run, "reads")[0]["id"]
    assert _items(branch, "trim")[0]["job_id"] != trim["job_id"]
    same = client.post(f"{API}/batches/{run['id']}/branch", json={
        "node_id": "trim", "params": {"params": {"qualified_quality_phred": 15}}, "confirmed": True})
    assert same.json()["code"] == "wf_branch_same"

    cmp = client.get(f"{API}/batches/compare", params={"a": run["id"], "b": branch["id"]}).json()
    assert cmp["parameters"] == [{"node": "trim", "path": "params.qualified_quality_phred", "before": 15, "after": 25}]
    (row,) = cmp["rows"]
    assert row["a"]["status"] == row["b"]["status"] == "completed" and not row["same_job"]

    table = list(csv.DictReader(io.StringIO(client.get(f"{API}/batches/{run['id']}/table.csv").text)))
    assert [(r["sample_code"], r["node_id"], r["status"], r["tool"]) for r in table] == [
        ("R1S", "trim", "completed", "fastp")]
    export = client.get(f"{API}/batches/{run['id']}/export.json").json()
    assert export["jobs"][0]["commands"][0][0].endswith("fastp") and export["tools"]["fastp"]["version"]
    html = client.get(f"{API}/batches/{run['id']}/report.html")
    assert "1 of 1 steps completed" in html.text and html.headers["content-security-policy"].startswith("default-src")
    assert client.get(f"{API}/batches/{branch['id']}/report.html").text.count("qualified_quality_phred") == 1
    es = client.get(f"{API}/batches/{run['id']}/report.html", params={"lang": "es"}).text
    assert '<html lang="es">' in es and "1 de 1 pasos completados" in es and "estado completado" in es
    timeline = client.get(f"{API}/samples/{a['id']}/batches").json()
    assert [(r["id"], r["parent_run_id"]) for r in timeline] == [(run["id"], None), (branch["id"], run["id"])]
    assert [s["node_id"] for s in timeline[1]["steps"]] == ["trim"]


def test_comparison_set_node_collects_the_samples_genomes(client, project, monkeypatch):
    samples = []
    for code in ("G1", "G2"):
        s = client.post(f"{API}/projects/{project['id']}/samples", json={"sample_code": code}).json()
        assemble(client, s, GENOME)
        samples.append(s)
    called = []
    kind = nodes.KINDS["comparative_ani"]

    def launch(ctx):
        called.append(ctx.inputs["set"]["set_id"])
        raise nodes.LaunchRefused("comparison_blocked", "skani is not available here")

    monkeypatch.setitem(nodes.KINDS, "comparative_ani", nodes.Kind(kind.model, kind.bound, kind.placeholders,
                                                                   launch, kind.outputs))
    monkeypatch.setattr(batches, "availability", lambda d, refresh=False: [])
    wf = client.post(f"{API}/workflows", json={"name": "Cmp", "template_key": "comparative_genomics"}).json()
    run = _run(client, project, wf, samples)
    (cset,) = _items(run, "set")
    assert cset["status"] == "completed" and cset["sample_id"] is None
    detail = client.get(f"{API}/comparisons/{cset['outputs']['set']['set_id']}").json()
    assert len(detail["members"]) == 2 and detail["project_id"] == project["id"]
    assert called == [cset["outputs"]["set"]["set_id"]]
    (ani,) = _items(run, "ani")
    assert ani["status"] == "failed" and ani["error"]["code"] == "comparison_blocked"
    with SessionLocal() as db:
        assert db.get(BatchItem, ani["id"]).attempt == 1


def test_run_refusals(client, project):
    wf = _workflow(client)
    other = client.post(f"{API}/projects", json={"name": "Other"}).json()
    foreign = _sample(client, other, "F", reads=False)
    body = {"project_id": project["id"], "workflow_id": wf["id"], "sample_ids": [foreign["id"]]}
    assert client.post(f"{API}/batches", json=body).json()["code"] == "wf_run_confirm"
    r = client.post(f"{API}/batches", json={**body, "confirmed": True})
    assert r.status_code == 400 and r.json()["code"] == "wf_sample_foreign"
    needs = client.post(f"{API}/workflows", json={"name": "N", "template_key": "nanopore_assembly"}).json()
    s = _sample(client, project, "N1", reads=False)
    r = client.post(f"{API}/batches", json={"project_id": project["id"], "workflow_id": needs["id"],
                                            "sample_ids": [s["id"]], "confirmed": True})
    assert r.status_code == 409 and "wf_param" in r.json()["params"]["problems"]


def test_cancelling_a_run_waits_for_a_launch_the_dispatcher_is_committing(client, project, monkeypatch,
                                                                           held_queue):
    import threading

    from sqlalchemy import text

    from app.db.session import engine

    _fake_fastp(monkeypatch)
    samples = [_sample(client, project, c) for c in ("S1", "S2")]
    run = _run(client, project, _workflow(client), samples, max_concurrent=1)
    waiting = next(i for i in _items(run, "trim") if i["status"] == "waiting")
    done = threading.Event()

    def cancel():
        with SessionLocal() as db:
            batches.cancel_run(db, db.get(BatchRun, run["id"]))
        done.set()

    with engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": batches._LOCK_KEY})
        worker = threading.Thread(target=cancel, daemon=True)
        try:
            worker.start()
            blocked = not done.wait(0.5)
            # Meanwhile the dispatcher, holding the lock, launches the waiting item.
            with SessionLocal() as db:
                job = AnalysisJob(project_id=project["id"], sample_id=waiting["sample_id"], job_type="fastp",
                                  tool_name="fastp", tool_version="x", parameters={}, input_raw_file_ids=[],
                                  status=JobStatus.pending, log_text="")
                db.add(job)
                db.flush()
                item = db.get(BatchItem, waiting["id"])
                item.status, item.job_id = "queued", job.id
                db.commit()
                job_id = job.id
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": batches._LOCK_KEY})
            lock.commit()
    assert blocked
    worker.join(30)
    with SessionLocal() as db:
        assert db.get(BatchItem, waiting["id"]).status == "cancelled"
        assert db.get(AnalysisJob, job_id).status is JobStatus.cancelled


def test_staph_typing_node_runs_on_s_aureus_and_is_skipped_with_its_reason_otherwise(client, project, typing_tools):  # noqa: F811
    """The S. aureus typing node reads the assembly's species evidence (typing_modules.applicability): a sample of
    another species skips it with the reason, which leaves the run completed; S. aureus runs the ordinary job."""
    from test_amr_api import species_result
    from test_annotation_api import assemble as assemble_reads
    from test_typing_api import SYNTHETIC, mlst_result

    typing_tools("n315")
    samples = []
    for code, species in (("SA", "Staphylococcus aureus"), ("EC", "Escherichia coli")):
        s = client.post(f"{API}/projects/{project['id']}/samples",
                        json={"sample_code": code, "sequencing_technology": "nanopore"}).json()
        a = assemble_reads(client, s, SYNTHETIC)
        species_result(s, a, species)
        if code == "SA":
            mlst_result(s, a, "5")
        samples.append(s)
    agr = _definition([("asm", "assembly_input", {}), ("agr", "staph_typing", {"method": "agr"})],
                      [("asm", "assembly", "agr", "assembly")])
    wf = _workflow(client, agr, "agr")
    assert [p["code"] for p in wf["problems"]] == []
    run = _run(client, project, wf, samples)
    by_sample = {i["sample_id"]: i for i in _items(run, "agr")}
    done, skipped = by_sample[samples[0]["id"]], by_sample[samples[1]["id"]]
    assert done["status"] == "completed" and done["tool"] == "AgrVATE"
    assert skipped["status"] == "skipped" and skipped["job_id"] is None
    assert skipped["error"]["code"] == "wf_typing_not_applicable"
    assert skipped["error"]["params"] == {"status": "not_applicable", "species": "Escherichia coli", "scheme": ""}
    assert run["status"] == "completed" and run["counts"]["skipped"] == 1


def test_staph_typing_node_fails_with_its_reason_when_the_species_evidence_is_missing_or_conflicts(
        client, project, typing_tools):  # noqa: F811
    """Only evidence that names another organism skips the step as not applicable. No species and no MLST call, or
    species and MLST that disagree, cannot rule S. aureus out: the step fails with that reason (the run ends with
    errors, so it is flagged), and the node's override still runs it."""
    from test_amr_api import species_result
    from test_annotation_api import assemble as assemble_reads
    from test_typing_api import SYNTHETIC, mlst_result

    typing_tools("n315")
    samples = []
    for code in ("NONE", "CONF"):
        s = client.post(f"{API}/projects/{project['id']}/samples",
                        json={"sample_code": code, "sequencing_technology": "nanopore"}).json()
        a = assemble_reads(client, s, SYNTHETIC)
        if code == "CONF":
            species_result(s, a, "Escherichia coli")
            mlst_result(s, a, "5")
        samples.append(s)
    agr = _definition([("asm", "assembly_input", {}), ("agr", "staph_typing", {"method": "agr"})],
                      [("asm", "assembly", "agr", "assembly")])
    run = _run(client, project, _workflow(client, agr, "agr"), samples)
    by_sample = {i["sample_id"]: i for i in _items(run, "agr")}
    none, conf = by_sample[samples[0]["id"]], by_sample[samples[1]["id"]]
    assert (none["status"], none["error"]["code"]) == ("failed", "wf_typing_no_evidence")
    assert (conf["status"], conf["error"]["code"]) == ("failed", "wf_typing_conflicting")
    assert conf["error"]["params"] == {"status": "conflicting", "species": "Escherichia coli", "scheme": "saureus"}
    assert run["status"] == "completed_with_errors"

    forced = _definition([("asm", "assembly_input", {}),
                          ("agr", "staph_typing", {"method": "agr", "override_applicability": True})],
                         [("asm", "assembly", "agr", "assembly")])
    run = _run(client, project, _workflow(client, forced, "agr forced"), samples[:1])
    item = _items(run, "agr")[0]
    assert item["status"] == "completed" and item["tool"] == "AgrVATE"


def test_species_and_mlst_order_the_typing_and_the_template_has_it(client):
    cat = client.get(f"{API}/workflows/catalogue").json()
    kinds = {k["kind"]: k for k in cat["kinds"]}
    assert {"species_call", "mlst_call"} <= set(cat["port_types"])
    assert kinds["species"]["outputs"] == [{"name": "evidence", "type": "species_call"}]
    assert [p["name"] for p in kinds["staph_typing"]["inputs"]] == ["assembly", "species", "mlst"]
    assert set(kinds["staph_typing"]["tools"]) == {"sccmec", "spa", "agr"}
    assert kinds["flye"]["params_schema"]["properties"]["memory_guard"]["default"] == "off"
    full = next(t for t in cat["templates"] if t["key"] == "bacterial_genome_complete")["definition"]
    nodes_ = {n["id"]: n for n in full["nodes"]}
    assert {nodes_[m]["params"]["method"] for m in ("sccmec", "spa", "agr")} == {"sccmec", "spa", "agr"}
    assert nodes_["flye"]["params"]["memory_guard"] == "auto"
    into = {(e["source"], e["target_port"]) for e in full["edges"] if e["target"] == "spa"}
    assert into == {("polish", "assembly"), ("species", "species"), ("mlst", "mlst")}


def test_run_options_change_the_runs_definition_and_are_recorded(client, project, monkeypatch):
    _fake_fastp(monkeypatch)
    s = _sample(client, project, "OPT")
    d = _definition([("asm", "assembly_input", {}), ("pol", "polishing", {"strategy": "racon"})],
                    [("asm", "assembly", "pol", "assembly")])
    wf = _workflow(client, d, "Polish")
    body = {"project_id": project["id"], "workflow_id": wf["id"], "sample_ids": [s["id"]]}
    plan = client.post(f"{API}/batches/preview", json=body).json()
    assert plan["options"] == {"polishing_strategy": {"kind": "polishing", "param": "strategy", "nodes": 1,
                                                      "value": "racon",
                                                      "choices": ["racon", "medaka", "pilon", "hybrid"]}}
    assert plan["option_changes"] == [] and "definition" not in plan
    plan = client.post(f"{API}/batches/preview", json={**body, "options": {"polishing_strategy": "medaka"}}).json()
    assert plan["option_changes"] == [{"node": "pol", "option": "polishing_strategy", "path": "strategy",
                                       "before": "racon", "after": "medaka"}]
    assert "medaka" in plan["tools"]
    assert client.post(f"{API}/batches/preview", json={**body, "options": {"polishing_strategy": "x"}}).status_code == 422
    definition, changes = batches.apply_options(wf["latest"]["definition"], {"flye_memory_guard": "auto"})
    assert changes == [] and definition == wf["latest"]["definition"]


def test_run_options_offer_only_what_the_steps_reads_allow_and_old_versions_show_defaults(client):
    """The polishing strategy offered is limited to what the reads each polishing step receives allow (long reads:
    Racon or Medaka; short: Pilon; both: hybrid), and another choice blocks the run. A version saved before a
    parameter existed shows that parameter's default, not 'mixed values'."""
    long_only = _definition([("long", "reads_long_input", {}), ("asm", "assembly_input", {}),
                             ("pol", "polishing", {"strategy": "racon"})],
                            [("asm", "assembly", "pol", "assembly"), ("long", "reads", "pol", "long_reads")])
    both = _definition([("long", "reads_long_input", {}), ("short", "reads_short_input", {}),
                        ("asm", "assembly_input", {}), ("pol", "polishing", {"strategy": "hybrid"})],
                       [("asm", "assembly", "pol", "assembly"), ("long", "reads", "pol", "long_reads"),
                        ("short", "reads", "pol", "short_reads")])
    assert batches.run_options(long_only)["polishing_strategy"]["choices"] == ["racon", "medaka"]
    assert batches.run_options(both)["polishing_strategy"]["choices"] == ["hybrid"]
    offered = batches.run_options(long_only)
    assert batches.option_problems(offered, {"polishing_strategy": "medaka"}) == []
    [p] = batches.option_problems(offered, {"polishing_strategy": "pilon"})
    assert p["code"] == "wf_option_not_allowed" and p["params"] == {"option": "polishing_strategy", "value": "pilon",
                                                                     "allowed": "racon, medaka"}
    # A Flye node stored without memory_guard (saved before it existed) is shown with its default.
    old = _definition([("long", "reads_long_input", {}), ("flye", "flye", {"params": {"read_type": "nano-hq"}})],
                      [("long", "reads", "flye", "reads")])
    assert batches.run_options(old)["flye_memory_guard"]["value"] is None
    normalised, _ = batches.check_definition(old)
    assert batches.run_options(normalised)["flye_memory_guard"]["value"] == "off"


def test_a_lost_read_statistics_job_does_not_fail_the_finished_filtlong_step(client, project, monkeypatch):
    """The filtered reads' statistics are an optional follow-up (Flye's memory estimate reads them): if their task is
    lost (ARVA or Redis restarted while it was queued), it is cancelled and the Filtlong step still completes. A
    required follow-up (Pilon after Racon) that is lost still fails its step."""
    import dataclasses
    import types

    from app.core.config import get_settings

    s = _sample(client, project, "LOSTSTATS", reads=False)
    with SessionLocal() as db:
        filt = AnalysisJob(project_id=project["id"], sample_id=s["id"], job_type="read_filter", tool_name="Filtlong",
                           tool_version="0.3.1", parameters={}, status=JobStatus.completed, log_text="")
        db.add(filt)
        db.flush()
        follow = [AnalysisJob(project_id=project["id"], sample_id=s["id"], job_type=jobs_service.FASTQ_STATS_JOB,
                              tool_name="ARVA", tool_version="1", parameters={}, status=JobStatus.pending,
                              log_text="", parent_job_id=filt.id) for _ in range(2)]
        db.add_all(follow)
        db.commit()
        filt_id, optional_id, required_id = filt.id, follow[0].id, follow[1].id

    def outputs(required):
        def read(db, job):
            pending = db.get(AnalysisJob, required_id if required else optional_id)
            if pending.status is JobStatus.pending:
                raise nodes.WaitForFollowUp(pending, required=required)
            return {"reads": {"file_ids": ["f"]}}
        return read

    monkeypatch.setattr(get_settings(), "task_queue_async", True)
    monkeypatch.setattr(jobs_service, "_rq_status", lambda jid: "missing")
    run = types.SimpleNamespace(settings={"max_retries": 0}, status="running")
    for required, status in ((False, "completed"), (True, "failed")):
        monkeypatch.setitem(nodes.KINDS, "filtlong", dataclasses.replace(nodes.KINDS["filtlong"],
                                                                        outputs=outputs(required)))
        item = types.SimpleNamespace(job_id=filt_id, node_kind="filtlong", status="running", outputs=None,
                                     error=None, finished_at=None, attempt=1)
        with SessionLocal() as db:
            batches._sync(db, run, item)
            db.commit()
            assert db.get(AnalysisJob, required_id if required else optional_id).status is JobStatus.cancelled
        assert item.status == status
        if required:
            assert item.error["code"] == "wf_interrupted"
        else:
            assert item.outputs == {"reads": {"file_ids": ["f"]}} and item.error is None
