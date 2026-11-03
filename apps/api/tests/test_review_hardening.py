"""Regressions for the adversarial review: request origin checks, access to JSON bodies whatever their Content-Type,
owner-only project changes, deletion while jobs run, and the worker's clean-up when a job's record is gone."""
import json

from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus
from app.tasks.common import run_job
from test_auth_access import auth_on, login, make_user  # noqa: F401

API = "/api/v1"


def _project(client, name="P", headers=None):
    return client.post(f"{API}/projects", json={"name": name}, headers=headers or {}).json()["id"]


def test_cross_site_changes_and_foreign_hosts_are_refused_with_accounts_off(client):
    blob = json.dumps({"name": "from a web page"})
    # A no-cors fetch of a Blob sends no Content-Type, so the browser makes no preflight; Origin gives it away.
    r = client.post(f"{API}/projects", content=blob, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "request_cross_site_refused"
    r = client.post(f"{API}/projects", content=blob, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json()["code"] == "request_cross_site_refused"
    # DNS rebinding: same origin for the browser, but the Host names the hostile domain.
    r = client.get(f"{API}/projects", headers={"Host": "rebound.evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "request_host_refused"
    assert client.get(f"{API}/projects", headers={"Host": "localhost:8080"}).status_code == 200
    assert client.get(f"{API}/projects", headers={"Host": "[::1]:8000"}).status_code == 200
    ok = {"Origin": "http://localhost:8080", "Host": "localhost:8080"}
    assert client.post(f"{API}/projects", json={"name": "same origin"}, headers=ok).status_code == 201
    assert client.post(f"{API}/projects", json={"name": "dev"}, headers={"Origin": "http://localhost:5173"}) \
        .status_code == 201
    assert client.post(f"{API}/projects", json={"name": "curl"}).status_code == 201


def test_body_project_ids_are_checked_whatever_the_content_type(client, auth_on):  # noqa: F811
    make_user("ana", "analyst")
    make_user("bob", "analyst")
    h = login(client, "ana")
    foreign = _project(client, "Ana's", h)
    h = login(client, "bob")
    own = _project(client, "Bob's", h)
    body = json.dumps({"project_id": foreign, "name": "x", "assembly_ids": []}).encode()
    for ctype in (None, "Application/JSON", "application/vnd.arva+json", "application/json; charset=utf-8"):
        headers = dict(h) | ({"Content-Type": ctype} if ctype else {})
        r = client.post(f"{API}/comparisons", content=body, headers=headers)
        assert r.status_code == 403 and r.json()["code"] == "auth_forbidden", (ctype, r.text)
    r = client.post(f"{API}/comparisons", content=body.replace(foreign.encode(), own.encode()), headers=h)
    assert r.json().get("code") != "auth_forbidden"


def test_only_the_owner_or_an_admin_renames_or_deletes_a_shared_project(client, auth_on):  # noqa: F811
    make_user("ana", "analyst")
    bob = make_user("bob", "analyst")
    h = login(client, "ana")
    pid = _project(client, "Ana's", h)
    client.put(f"{API}/projects/{pid}/shares", json={"user_id": bob, "access": "write"}, headers=h)
    h = login(client, "bob")
    assert client.post(f"{API}/projects/{pid}/samples", json={"sample_code": "S1"}, headers=h).status_code == 201
    for r in (client.delete(f"{API}/projects/{pid}", headers=h),
              client.patch(f"{API}/projects/{pid}", json={"name": "mine now"}, headers=h)):
        assert r.status_code == 403 and r.json()["code"] == "auth_project_owner_only"
    h = login(client, "ana")
    assert client.delete(f"{API}/projects/{pid}", headers=h).status_code == 204


def _job(project_id, sample_id, status=JobStatus.pending):
    with SessionLocal() as db:
        job = AnalysisJob(project_id=project_id, sample_id=sample_id, job_type="test", tool_name="t",
                          tool_version="1", parameters={}, status=status)
        db.add(job)
        db.commit()
        return job.id


def test_deleting_refused_while_a_job_runs_and_derived_outputs_removed_after(client, storage_root):
    pid = _project(client)
    sid = client.post(f"{API}/projects/{pid}/samples", json={"sample_code": "S1"}).json()["id"]
    jid = _job(pid, sid, JobStatus.running)
    for url in (f"{API}/samples/{sid}", f"{API}/projects/{pid}"):
        r = client.delete(url)
        assert r.status_code == 409 and r.json() == {
            "detail": r.json()["detail"], "code": "delete_active_jobs", "params": {"count": 1}}
    with SessionLocal() as db:
        db.get(AnalysisJob, jid).status = JobStatus.completed
        db.commit()
    for top in ("results", "processed", "checkpoints", "reports"):
        (storage_root / top / pid / sid / jid).mkdir(parents=True)
        (storage_root / top / pid / sid / jid / "out.txt").write_text("x")
    (storage_root / "raw" / pid / sid).mkdir(parents=True, exist_ok=True)
    assert client.delete(f"{API}/samples/{sid}").status_code == 204
    assert not any((storage_root / top / pid / sid).exists()
                   for top in ("results", "processed", "checkpoints", "reports"))
    assert (storage_root / "raw" / pid / sid).is_dir()


def test_a_job_whose_record_is_deleted_while_it_runs_stops_and_cleans_up(client, storage_root):
    pid = _project(client)
    sid = client.post(f"{API}/projects/{pid}/samples", json={"sample_code": "S1"}).json()["id"]
    jid = _job(pid, sid)
    seen = {}

    def body(ctx):
        (storage_root / ctx.results_rel).mkdir(parents=True)
        (storage_root / ctx.results_rel / "partial.txt").write_text("x")
        with SessionLocal() as other:
            other.delete(other.get(AnalysisJob, jid))
            other.commit()
        seen["cancel"] = ctx.cancel_requested()
        seen["rel"] = ctx.results_rel

    assert run_job(jid, body) == "deleted"
    assert seen["cancel"] is True
    assert not (storage_root / seen["rel"]).exists()


def test_a_failing_cleanup_hook_still_records_the_failure(client):
    pid = _project(client)
    jid = _job(pid, None)

    def body(ctx):
        ctx.before_cleanup.append(lambda exc: (_ for _ in ()).throw(RuntimeError("hook broke")))
        raise ValueError("tool failed")

    assert run_job(jid, body) == "failed"
    with SessionLocal() as db:
        assert "tool failed" in db.get(AnalysisJob, jid).error_message


def _amr_run(sample, hits, **params):
    from test_discover_reports_assist import _amr

    from app.models import AmrResult
    _amr(sample, set())
    with SessionLocal() as db:
        job = db.query(AnalysisJob).filter_by(sample_id=sample["id"], job_type="amr_detection").one()
        job.parameters = {**job.parameters, "organism": None, "plus": False, **params}
        for symbol, type_, subtype, scope in hits:
            db.add(AmrResult(sample_id=sample["id"], assembly_id=job.parameters["assembly"]["assembly_id"],
                             job_id=job.id, element_symbol=symbol, type=type_, subtype=subtype, scope=scope,
                             amr_class="X", method="POINTX" if subtype == "POINT" else "EXACTX",
                             method_kind="point" if subtype == "POINT" else "complete"))
        db.commit()


def test_amr_matrix_and_discover_leave_unsearched_point_mutations_and_plus_elements_empty(client):
    pid = _project(client, "AMR scope")
    a, b = (client.post(f"{API}/projects/{pid}/samples", json={"sample_code": c}).json() for c in ("A", "B"))
    _amr_run(a, [("mecA", "AMR", "AMR", "core"), ("gyrA_S84L", "AMR", "POINT", "core"),
                 ("sea", "VIRULENCE", "VIRULENCE", "plus")], organism="Staphylococcus_aureus", plus=True)
    _amr_run(b, [("mecA", "AMR", "AMR", "core")])
    rows = client.get(f"{API}/projects/{pid}/amr_matrix.csv").text.splitlines()
    header = rows[0].split(",")
    cells = {r.split(",")[0]: dict(zip(header, r.split(","), strict=True)) for r in rows[1:]}
    assert (cells["A"]["mecA"], cells["A"]["gyrA_S84L"], cells["A"]["sea"]) == ("1", "1", "1")
    assert (cells["B"]["mecA"], cells["B"]["gyrA_S84L"], cells["B"]["sea"]) == ("1", "", "")
    overview = client.get(f"{API}/projects/{pid}/amr").json()
    assert next(s for s in overview["samples"] if s["sample_code"] == "B")["not_searched"] == ["gyrA_S84L", "sea"]
    from app.models import Project
    from app.services import discover
    with SessionLocal() as db:
        features = discover.table(db, db.get(Project, pid))["features"]
    assert features["amr:mecA"] == [1, 1] and features["amr:gyrA_S84L"] == [1, None]


def test_jobs_lost_by_a_restart_are_ended_and_a_killed_horse_fails_its_job(client, monkeypatch):
    import datetime as dt

    from app.core.config import get_settings
    from app.services import jobs as jobs_service

    pid = _project(client, "Lost")
    old = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    lost_pending, failed_pending, fresh, running_lost, running_ok = (
        _job(pid, None, st) for st in (JobStatus.pending, JobStatus.pending, JobStatus.pending, JobStatus.running,
                                       JobStatus.running))
    with SessionLocal() as db:
        for jid in (lost_pending, failed_pending, running_lost, running_ok):
            db.get(AnalysisJob, jid).created_at = old
        db.commit()
    states = {lost_pending: "missing", failed_pending: "failed", fresh: "missing", running_lost: "stopped",
              running_ok: "started"}
    monkeypatch.setattr(get_settings(), "task_queue_async", True)
    monkeypatch.setattr(jobs_service, "_rq_status", lambda jid: states[jid])
    with SessionLocal() as db:
        assert jobs_service.reconcile_lost(db) == 3
    with SessionLocal() as db:
        status = {j: db.get(AnalysisJob, j).status for j in states}
    assert status == {lost_pending: JobStatus.cancelled, failed_pending: JobStatus.cancelled,
                      fresh: JobStatus.pending, running_lost: JobStatus.cancelled, running_ok: JobStatus.running}
    with SessionLocal() as db:
        assert jobs_service.end_killed(db, running_ok, "SIGKILL")
    with SessionLocal() as db:
        job = db.get(AnalysisJob, running_ok)
        assert job.status is JobStatus.failed and job.error_detail == {"code": "out_of_memory",
                                                                        "params": {"tool": "t"}}


def test_a_racon_step_whose_pilon_could_not_be_queued_fails_instead_of_waiting(client):
    import pytest

    from app.services import workflow_nodes as nodes

    pid = _project(client, "Hybrid")
    with SessionLocal() as db:
        racon = AnalysisJob(project_id=pid, job_type="racon_polish", tool_name="Racon", tool_version="1.5.0",
                            parameters={"then_pilon": {"inputs": {}, "params": {}}}, status=JobStatus.completed,
                            result_summary={"followups": {"pilon_error": "Pilon is not installed"}})
        db.add(racon)
        db.commit()
        with pytest.raises(nodes.LaunchRefused) as refused:
            nodes._out_polished(db, racon)
        assert refused.value.code == "wf_followup_not_queued" and "Pilon is not installed" in str(refused.value)
        pilon = AnalysisJob(project_id=pid, job_type="pilon_polish", tool_name="Pilon", tool_version="1.24",
                            parameters={}, status=JobStatus.pending, parent_job_id=racon.id)
        db.add(pilon)
        db.commit()
        with pytest.raises(nodes.WaitForFollowUp) as waiting:
            nodes._out_polished(db, racon)
        assert waiting.value.follow.id == pilon.id


def test_a_workflow_set_node_naming_another_projects_set_is_refused(client):
    import pytest

    from app.models import ComparisonSet
    from app.services import workflow_nodes as nodes

    p, q = _project(client, "P"), _project(client, "Q")
    with SessionLocal() as db:
        cset = ComparisonSet(project_id=p, name="P's set")
        db.add(cset)
        db.commit()
        assert nodes.resolve_source(db, "comparison_set_input", None, {"set_id": cset.id}, None, p) == {
            "set": {"set_id": cset.id}}
        with pytest.raises(nodes.LaunchRefused) as refused:
            nodes.resolve_source(db, "comparison_set_input", None, {"set_id": cset.id}, None, q)
        assert refused.value.code == "wf_source_set"


def test_reference_genome_species_come_only_from_real_binomials_in_headers(tmp_path):
    from app.services import reference_collections as rc

    cases = {"unicycler.fasta": (">1 length=2800000 depth=1.00x circular=true\nACGT\n", None),
             "tagged.fasta": (">ctg1 [organism=Staphylococcus aureus] [strain=X]\nACGT\n", "Staphylococcus aureus"),
             "ncbi.fasta": (">NZ_CP000001.1 Staphylococcus aureus strain N315 chromosome\nACGT\n",
                            "Staphylococcus aureus")}
    for name, (text, species) in cases.items():
        (tmp_path / name).write_text(text)
        g = rc.Genome(key=name, path=str(tmp_path / name), present=True)
        rc._from_header(g, tmp_path / name)
        assert g.species == species, name
        assert g.metadata == ("fasta_header" if species else None)
