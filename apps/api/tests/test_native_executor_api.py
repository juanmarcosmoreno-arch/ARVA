"""The native executor (ARVA.app runs Flye on the Mac; app.services.native, docs/plan-flye-nativo.md, "Contrato
implementado"): the token, registration and readiness, the exclusive claim, the work record and its argv, heartbeats
and cancellation, a lease that expires (the work folder is kept for resuming), the final report and its checks, and
when the Flye dialog offers the native option.

The test plays ARVA.app: it registers with facts read by the real adapter (arva_tools.flye.native_facts) from a
stand-in Flye environment, claims the job the worker publishes, runs it with the adapter's own native entry
(run_native) on the test data folder, and reports. The worker runs in a thread, as in test_job_control_api."""
import json
import os
import secrets
import time
from pathlib import Path

import pytest
from arva_tools.flye import NATIVE_LOCK, OUTPUTS, native_facts, run_native
from test_flye_api import FAKE, FIXTURES, ONT, new_sample, upload
from test_job_control_api import in_thread, wait_for

from app.services import host, native, performance
from app.tasks import tools as tool_tasks

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXECUTOR_ID = "6b1f3c2e-9a4d-4e8f-8c1a-2f3e4d5c6b7a"


@pytest.fixture
def mac(tmp_path, monkeypatch, storage_root):
    """ARVA.app's side: a token, a Flye environment as the osx-arm64 lock creates it (flye, flye-samtools,
    conda-meta), and the facts it registers."""
    token = secrets.token_urlsafe(32)
    (tmp_path / "native-executor.token").write_text(token + "\n")
    env = tmp_path / "arva-tools" / "conda" / "flye"
    (env / "bin").mkdir(parents=True)
    exe = env / "bin" / "flye"
    exe.write_text(f"#!{os.sys.executable}\n" + FAKE.replace('print("2.9.3-b1797")', 'print("2.9.6-b1802")'))
    exe.chmod(0o755)
    (env / "bin" / "flye-samtools").write_text("#!/bin/sh\n")
    (env / "bin" / "flye-samtools").chmod(0o755)
    (env / "conda-meta").mkdir()
    (env / "conda-meta" / "flye-2.9.6-py313h05f0e27_1.json").write_text(json.dumps(
        {"name": "flye", "version": "2.9.6", "build": NATIVE_LOCK["build"], "sha256": NATIVE_LOCK["package_sha256"],
         "url": f"https://conda.anaconda.org/bioconda/osx-arm64/{NATIVE_LOCK['package']}"}))
    monkeypatch.setenv("FAKE_FLYE_HELP", str(FIXTURES / "help_2.9.6.txt"))
    monkeypatch.setenv("FAKE_FLYE_INFO", str(FIXTURES / "synthetic150_assembly_info.txt"))
    monkeypatch.setenv("FAKE_FLYE_LOG", str(FIXTURES / "synthetic150_flye.log"))
    monkeypatch.setenv("FAKE_FLYE_DUMP", str(tmp_path / "dump.txt"))
    monkeypatch.setenv("FAKE_FLYE_MODE", "ok")
    monkeypatch.setattr(tool_tasks, "MONITOR_SECONDS", 0.05)
    monkeypatch.setattr(tool_tasks, "NATIVE_POLL_SECONDS", 0.02)
    facts = native_facts(str(exe), str(REPO / NATIVE_LOCK["lock"]))
    return {"token": token, "exe": str(exe), "facts": facts, "data": str(storage_root), "dump": tmp_path / "dump.txt",
            "headers": {"Authorization": f"Bearer {token}"}}


def storage_id(storage_root: Path) -> str:
    return json.loads((storage_root / ".arva-storage").read_text())["id"]


def registration(mac, storage_root, **changes):
    facts = {k: v for k, v in mac["facts"].items()}
    body = {"executor_id": EXECUTOR_ID, "app_version": "1.4.0", "platform": "osx-arm64", "macos": "15.1",
            "chip": "Apple M1", "memory_bytes": 8 * 1024**3, "data_dir": mac["data"],
            "storage_id": storage_id(storage_root), "tools": {"flye": facts}}
    return {**body, **changes}


def register(client, mac, storage_root, **changes):
    client.post(f"{API}/projects", json={"name": "marker"})  # a first write creates the data folder's marker
    r = client.post(f"{API}/native/executor", json=registration(mac, storage_root, **changes), headers=mac["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def native_job(client, mac, storage_root, params=None):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    register(client, mac, storage_root)
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [f["id"]], "params": {"read_type": "nano-hq", "threads": 2, **(params or {})},
                          "execution": "mac_native"})
    assert r.status_code == 202, r.text
    return sample, r.json()


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def claim(client, mac):
    return client.post(f"{API}/native/jobs/claim", json={"executor_id": EXECUTOR_ID, "tools": ["flye"]},
                       headers=mac["headers"])


def claim_when_published(client, mac):
    found = {}

    def ready():
        r = claim(client, mac)
        if r.status_code == 200:
            found.update(r.json())
        return bool(found)

    wait_for(ready)
    return found


def heartbeat(client, mac, taken, **extra):
    return client.post(f"{API}/native/jobs/{taken['job_id']}/heartbeat",
                       json={"executor_id": EXECUTOR_ID, "lease_id": taken["lease_id"], **extra},
                       headers=mac["headers"])


def finish(client, mac, taken, report):
    return client.post(f"{API}/native/jobs/{taken['job_id']}/finish",
                       json={"executor_id": EXECUTOR_ID, "lease_id": taken["lease_id"], "report": report},
                       headers=mac["headers"])


def test_every_executor_endpoint_needs_the_token(client, mac, storage_root, tmp_path):
    client.post(f"{API}/projects", json={"name": "marker"})
    body = registration(mac, storage_root)
    for path, payload in (("/native/executor", body), ("/native/jobs/claim", {"executor_id": EXECUTOR_ID,
                                                                             "tools": ["flye"]}),
                          ("/native/jobs/x/heartbeat", {"executor_id": EXECUTOR_ID, "lease_id": "0" * 36}),
                          ("/native/jobs/x/finish", {})):
        assert client.post(f"{API}{path}", json=payload).status_code == 401
        r = client.post(f"{API}{path}", json=payload, headers={"Authorization": "Bearer " + "x" * 43})
        assert (r.status_code, r.json()["code"]) == (401, "native_token_refused")
        r = client.post(f"{API}{path}", json=payload, headers={"Authorization": mac["token"]})  # no "Bearer"
        assert r.status_code == 401
    (tmp_path / "native-executor.token").unlink()
    r = client.post(f"{API}/native/executor", json=body, headers=mac["headers"])
    assert (r.status_code, r.json()["code"]) == (503, "native_token_missing")
    (tmp_path / "native-executor.token").write_text("short")
    assert client.post(f"{API}/native/executor", json=body, headers=mac["headers"]).status_code == 503


def test_registration_says_whether_flye_can_run(client, mac, storage_root):
    out = register(client, mac, storage_root)
    assert out["ready"] == {"flye": {"ready": True, "reason": None}}
    assert out["lease_seconds"] == native.LEASE_SECONDS and out["heartbeat_seconds"] < out["lease_seconds"]
    st = client.get(f"{API}/system/native-executor").json()
    assert st["known"] and st["open"] and st["chip"] == "Apple M1" and st["macos"] == "15.1"
    assert st["tools"]["flye"] == {"installed": True, "version": "2.9.6", "version_text": "2.9.6-b1802",
                                   "build": NATIVE_LOCK["build"], "lock_sha256": NATIVE_LOCK["lock_sha256"],
                                   "lock_matches": True, "ready": True, "reason": None}
    facts = mac["facts"]
    for changes, reason in (
        ({"storage_id": "00000000-0000-4000-8000-000000000000"}, "storage_mismatch"),
        ({"data_dir": "/Volumes/My Disk/ARVA/data"}, "path_has_spaces"),
        ({"data_dir": "/Volumes/JM/../ARVA/data"}, "unsafe_path"),
        ({"tools": {"flye": {**facts, "lock_sha256": "0" * 64}}}, "lock_mismatch"),
        ({"tools": {"flye": {**facts, "package": {**facts["package"], "build": "py312h_0"}}}}, "build_mismatch"),
        ({"tools": {"flye": {**facts, "version": "2.9.5-b1801"}}}, "version_mismatch"),
        ({"tools": {"flye": {**facts, "help_options": ["--nano-hq"]}}}, "help_incomplete"),
        ({"tools": {"flye": {**facts, "samtools_helper": False}}}, "samtools_missing"),
        ({"tools": {"flye": {**facts, "executable": "/Users/me/flye/../bin/flye"}}}, "unsafe_path"),
    ):
        assert register(client, mac, storage_root, **changes)["ready"]["flye"] == {"ready": False, "reason": reason}
    # The launcher's host path of the data folder, when known, must be ARVA.app's.
    os.environ["ARVA_HOST_DATA_DIR"] = "/Volumes/JM/ARVA/data"
    try:
        assert register(client, mac, storage_root)["ready"]["flye"]["reason"] == "other_data_dir"
    finally:
        del os.environ["ARVA_HOST_DATA_DIR"]
    # Unknown fields (an argv included) and tools ARVA does not run natively are refused.
    r = client.post(f"{API}/native/executor", json={**registration(mac, storage_root), "argv": ["/bin/sh"]},
                    headers=mac["headers"])
    assert r.status_code == 422
    r = client.post(f"{API}/native/executor", json=registration(mac, storage_root, tools={"prokka": facts}),
                    headers=mac["headers"])
    assert r.status_code == 422
    # Flye's facts under another tool's name are never taken for that tool.
    assert register(client, mac, storage_root, tools={"bakta": facts})["ready"]["bakta"]["ready"] is False


def test_an_executor_silent_for_a_minute_is_not_open(client, mac, storage_root, monkeypatch):
    register(client, mac, storage_root)
    later = time.time() + native.READY_SECONDS + 1
    monkeypatch.setattr(native, "_now", lambda: later)
    st = client.get(f"{API}/system/native-executor").json()
    assert st["known"] and not st["open"]
    assert (st["tools"]["flye"]["ready"], st["tools"]["flye"]["reason"]) == (False, "app_not_open")
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [f["id"]], "params": {"read_type": "nano-hq"}, "execution": "mac_native"})
    assert (r.status_code, r.json()["code"]) == (409, "native_app_not_open")


def test_native_jobs_are_refused_unless_arva_app_can_run_flye(client, mac, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    body = {"raw_file_ids": [f["id"]], "params": {"read_type": "nano-hq"}, "execution": "mac_native"}
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye", json=body)
    assert (r.status_code, r.json()["code"]) == (409, "native_app_not_open")
    register(client, mac, storage_root, tools={"flye": {**mac["facts"], "lock_sha256": "0" * 64}})
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye", json=body)
    assert (r.status_code, r.json()["code"], r.json()["params"]["reason"]) == (409, "native_not_ready",
                                                                               "lock_mismatch")
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye", json={**body, "execution": "elsewhere"})
    assert r.status_code == 422


def test_a_native_run_end_to_end(client, mac, storage_root, held_queue):
    sample, queued = native_job(client, mac, storage_root)
    assert queued["parameters"]["execution"] == "mac_native"
    assert queued["tool_path"] == mac["exe"] and queued["tool_version"] == "2.9.6"
    assert queued["parameters"]["native_executor"]["build"] == NATIVE_LOCK["build"]
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    wait_for(lambda: ((job(client, queued["id"]).get("progress") or {}).get("native") or {}).get("state")
             == "waiting_for_app")

    taken = claim_when_published(client, mac)
    # The lease is exclusive: a second claim finds nothing.
    assert claim(client, mac).status_code == 204
    work = taken["work"]
    scope = f"results/{sample['project_id']}/{sample['id']}/{queued['id']}"
    assert taken["job_id"] == queued["id"] and work["results_dir"] == scope and work["out_dir"] == f"{scope}/flye"
    assert work["reads"] == [f"{scope}/input/01_SYNTHETIC_nanopore_reads.fastq.gz"]
    assert work["argv"] == [mac["exe"], "--nano-hq", f"{mac['data']}/{work['reads'][0]}", "--out-dir",
                            f"{mac['data']}/{scope}/flye", "--threads", "2", "--iterations", "1"]
    assert work["storage_id"] == storage_id(storage_root) and work["data_dir"] == mac["data"]
    # The read links are relative, so they resolve in the container and on the Mac.
    link = storage_root / work["reads"][0]
    assert not os.readlink(link).startswith("/") and link.resolve().is_file()

    hb = heartbeat(client, mac, taken, pid=4242)
    assert hb.status_code == 200 and hb.json()["cancel"] is False
    wait_for(lambda: job(client, queued["id"])["progress"]["native"]["state"] == "running_on_mac")

    report = run_native(work, mac["data"], mac["exe"])
    assert report["outcome"] == "exited" and report["exit_code"] == 0, report
    assert report["outputs"] == [f"{scope}/flye/{n}" for n in OUTPUTS]
    r = finish(client, mac, taken, report)
    assert r.status_code == 200, r.text
    assert finish(client, mac, taken, report).status_code == 409
    worker.join(30)
    assert result == ["completed"], job(client, queued["id"])["log_text"]

    d = job(client, queued["id"])
    assert d["commands"] == [work["argv"]] and d["tool_path"] == mac["exe"]
    summary = d["result_summary"]
    assert summary["execution"] == "mac_native" and summary["assembly_id"]
    n = summary["native"]
    assert (n["platform"], n["build"], n["lock_sha256"], n["package_sha256"]) == (
        "osx-arm64", NATIVE_LOCK["build"], NATIVE_LOCK["lock_sha256"], NATIVE_LOCK["package_sha256"])
    assert (n["macos"], n["chip"], n["app_version"], n["executable"]) == ("15.1", "Apple M1", "1.4.0", mac["exe"])
    assert n["argv"] == work["argv"] and n["exit_code"] == 0 and n["reported_outputs"] == report["outputs"]
    assert summary["helpers"][0]["native"] is True
    assert d["output_paths"] == [f"{scope}/{name}" for name in (*OUTPUTS, "flye.stderr.log")]
    assert "Execution: natively on this Mac by ARVA.app 1.4.0" in d["log_text"]
    assert "ARVA.app took the job" in d["log_text"]
    # Nothing is left in Redis, and the lease is gone.
    assert heartbeat(client, mac, taken).json()["code"] == "native_lease_lost"
    assert not [k for k in native.get_redis().keys("arva:native:*") if k != "arva:native:executor"]


def test_the_api_never_takes_an_argv_from_the_app(client, mac, storage_root, held_queue):
    _, queued = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    # Requests that carry an argv (or any unknown field) are refused before anything else.
    r = client.post(f"{API}/native/jobs/claim", json={"executor_id": EXECUTOR_ID, "tools": ["flye"],
                                                      "argv": ["/bin/sh", "-c", "id"]}, headers=mac["headers"])
    assert r.status_code == 422
    taken = claim_when_published(client, mac)
    assert heartbeat(client, mac, taken, argv=["/bin/sh"]).status_code == 422
    report = {"tool": "flye", "outcome": "exited", "exit_code": 0, "argv": [*taken["work"]["argv"], "--meta"],
              "executable": mac["exe"], "outputs": []}
    r = finish(client, mac, taken, report)
    assert (r.status_code, r.json()["code"]) == (422, "native_argv_mismatch")
    # The refused report ends the job: it fails, saying why, and nothing is registered.
    worker.join(30)
    assert result == ["failed"]
    d = job(client, queued["id"])
    assert d["error_detail"] == {"code": "native_refused", "params": {"reason": "native_argv_mismatch",
                                                                      "detail": "the argument vector reported is not "
                                                                                "the one ARVA built for this job"}}
    assert d["result_summary"] is None


@pytest.mark.parametrize("outputs", [["../../../etc/passwd"], ["/etc/passwd"], ["results/x/flye/assembly.fasta"]])
def test_reported_paths_outside_the_jobs_folder_are_refused(client, mac, storage_root, held_queue, outputs):
    _, queued = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    taken = claim_when_published(client, mac)
    report = {"tool": "flye", "outcome": "exited", "exit_code": 0, "argv": taken["work"]["argv"],
              "executable": mac["exe"], "outputs": outputs}
    r = finish(client, mac, taken, report)
    assert (r.status_code, r.json()["code"]) == (422, "native_unsafe_path")
    worker.join(30)
    assert result == ["failed"]
    r = finish(client, mac, taken, {**report, "executable": "/bin/sh"})
    assert r.status_code == 409  # the lease and work are gone with the job


def test_a_refusal_by_the_app_fails_the_job_with_its_reason(client, mac, storage_root, held_queue):
    _, queued = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    taken = claim_when_published(client, mac)
    report = run_native({**taken["work"], "storage_id": "00000000-0000-4000-8000-000000000000"}, mac["data"],
                        mac["exe"])
    assert report["outcome"] == "refused" and report["code"] == "storage_mismatch"
    assert finish(client, mac, taken, report).status_code == 200
    worker.join(30)
    assert result == ["failed"]
    d = job(client, queued["id"])
    assert d["error_detail"]["code"] == "native_refused" and d["error_detail"]["params"]["reason"] == "storage_mismatch"


def test_cancelling_before_and_while_the_mac_runs_flye(client, mac, storage_root, held_queue):
    _, waiting = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, waiting["id"])
    wait_for(lambda: (job(client, waiting["id"]).get("progress") or {}).get("native") is not None)
    assert client.post(f"{API}/jobs/{waiting['id']}/cancel").status_code == 202
    worker.join(30)
    assert result == ["cancelled"] and claim(client, mac).status_code == 204

    _, running = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, running["id"])
    taken = claim_when_published(client, mac)
    assert heartbeat(client, mac, taken).json()["cancel"] is False
    assert client.post(f"{API}/jobs/{running['id']}/cancel").status_code == 202
    assert heartbeat(client, mac, taken).json()["cancel"] is True
    stopped = {"tool": "flye", "outcome": "stopped", "exit_code": None, "argv": taken["work"]["argv"],
               "executable": mac["exe"], "outputs": [], "code": "stopped_by_app"}
    assert finish(client, mac, taken, stopped).status_code == 200
    worker.join(30)
    assert result == ["cancelled"]


def test_a_cancelled_run_whose_app_stopped_without_a_report_is_cancelled(client, mac, storage_root, held_queue,
                                                                          monkeypatch):
    # The user cancels, ARVA.app stops native.py, but no report arrives (it was stopped before printing one): the
    # lease then expires, and the job ends as cancelled, not as a lost run.
    monkeypatch.setattr(native, "LEASE_SECONDS", 3)
    monkeypatch.setattr(tool_tasks, "NATIVE_POLL_SECONDS", 0.05)
    _, queued = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    claim_when_published(client, mac)
    # The worker has seen the claim (the job says "running on this Mac") before the user cancels.
    wait_for(lambda: ((job(client, queued["id"]).get("progress") or {}).get("native") or {}).get("state")
             == "running_on_mac")
    assert client.post(f"{API}/jobs/{queued['id']}/cancel").status_code == 202
    worker.join(30)
    assert result == ["cancelled"]


def test_an_expired_lease_keeps_the_work_folder_for_resuming(client, mac, storage_root, held_queue, monkeypatch):
    monkeypatch.setattr(native, "LEASE_SECONDS", 1)
    _, queued = native_job(client, mac, storage_root)
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    taken = claim_when_published(client, mac)
    # Flye ran on the Mac up to the repeat stage (params.json names the stage it was running), then ARVA.app
    # disappeared: no heartbeat renews the lease.
    out = storage_root / taken["work"]["out_dir"]
    (out / "00-assembly").mkdir(parents=True)
    (out / "10-consensus").mkdir()
    (out / "params.json").write_text(json.dumps({"stage_name": "repeat"}))
    (out / "flye.log").write_text(">>>STAGE: repeat\n")
    worker.join(30)
    assert result == ["failed"]
    d = job(client, queued["id"])
    assert d["error_detail"]["code"] == "native_lease_expired"
    kept = d["checkpoint"]
    assert (kept["reason"], kept["resume_stage"], kept["execution"], kept["build"], kept["tool_version"]) == (
        "native_stopped", "repeat", "mac_native", NATIVE_LOCK["build"], "2.9.6")
    assert (storage_root / kept["path"] / "10-consensus").is_dir()
    assert heartbeat(client, mac, taken).json()["code"] == "native_lease_lost"

    # It resumes natively, with the same build.
    register(client, mac, storage_root)
    r = client.post(f"{API}/jobs/{queued['id']}/resume")
    assert r.status_code == 202, r.text
    assert r.json()["parameters"]["execution"] == "mac_native" and r.json()["parameters"]["resume"]["stage"] == "repeat"


def test_a_job_waiting_for_an_app_that_never_comes_fails(client, mac, storage_root, held_queue, monkeypatch):
    _, queued = native_job(client, mac, storage_root)
    monkeypatch.setattr(native, "WAIT_SECONDS", 0.3)
    later = time.time() + native.READY_SECONDS + 5
    monkeypatch.setattr(native, "_now", lambda: later)
    worker, result = in_thread(tool_tasks.run_flye_job, queued["id"])
    worker.join(30)
    assert result == ["failed"]
    d = job(client, queued["id"])
    assert d["error_detail"]["code"] == "native_app_not_open" and d["checkpoint"] is None


def test_the_dialog_offers_the_native_run_only_when_docker_is_short_of_memory(client, mac, storage_root,
                                                                               monkeypatch):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)

    def preview():
        r = client.post(f"{API}/samples/{sample['id']}/assembly/flye/preview", json={"raw_file_ids": [f["id"]]})
        assert r.status_code == 200, r.text
        return r.json()

    # 64 GB: Flye fits in Docker, nothing to offer (and no executor is known yet).
    p = preview()
    assert p["memory"]["verdict"] in ("fits", "unknown") and p["native"]["offered"] is False
    assert p["native"]["reason"] == "not_known"
    # 5.9 GB in Docker Desktop's VM: below Flye's fixed k-mer table floor.
    small = host.Detection(host.HostFacts(), host.ContainerFacts(usable_cpus=4, cpus_source="affinity",
                                                                 memory_bytes=int(5.9 * 1024**3),
                                                                 memory_source="cgroup"))
    monkeypatch.setattr(performance, "detection", lambda: small)
    p = preview()
    assert p["memory"]["verdict"] == "below_floor"
    assert p["native"]["memory_short"] is True and p["native"]["offered"] is False
    register(client, mac, storage_root)
    p = preview()["native"]
    assert (p["offered"], p["ready"], p["reason"], p["flye"]["build"]) == (True, True, None, NATIVE_LOCK["build"])
    later = time.time() + native.READY_SECONDS + 1
    monkeypatch.setattr(native, "_now", lambda: later)
    p = preview()["native"]
    assert (p["offered"], p["ready"], p["reason"], p["app_open"]) == (True, False, "app_not_open", False)
