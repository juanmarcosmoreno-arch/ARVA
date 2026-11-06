"""Bakta through the native executor (ARVA.app runs Bakta on the Mac when DIAMOND's block with this database does
not fit Docker's memory; app.services.native, docs/plan-flye-nativo.md, "Bakta"): the memory estimate and the light
database suggested in the dialog, the native offer and why it is not ready, registration with the Mac's database
folders, the job and its work record (database folders as root + path, the confirmed skip options, the argv the API
built), the run end to end with the adapter's own native entry, and the refusals.

Bakta here is a stand-in environment (bakta and every program its start-up check runs, printing the versions Bakta
reads); a run copies Bakta's real outputs on the fixture genome (workflows/tool-adapters/tests/fixtures/bakta). The
same environment plays Docker's Bakta and the Mac's. The database is a stand-in too: the files Bakta's folder check
needs, and DIAMOND headers giving the light database 6.0's pscc.dmnd and a full-size psc.dmnd."""
import json
import os
import secrets
import stat
import struct
import sys
from pathlib import Path

import pytest
from arva_tools import registry
from arva_tools.bakta import DIAMOND_MAGIC, NATIVE_LOCK, native_facts, run_native
from test_annotation_api import FIXTURES, GENOME, assemble, new_sample
from test_job_control_api import in_thread, wait_for

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import DatabaseOrigin, DatabaseStatus
from app.models import ReferenceDatabase as RefDb
from app.services import host, native, performance
from app.services.database_catalogue import BAKTA_REQUIRED_FILES
from app.tasks import annotation as annotation_tasks
from app.tasks import tools as tool_tasks

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
BAKTA_FIXTURES = FIXTURES / "bakta"
EXECUTOR_ID = "7c2e4d3f-1b5e-4f9a-9d2b-3f4e5d6c7b8a"
VERSIONS = {"tRNAscan-SE": "tRNAscan-SE 2.0.12 (Nov 2022)", "aragorn": "ARAGORN v1.2.41 Dean Laslett",
            "cmscan": "# INFERNAL 1.1.5 (Sep 2023)", "diamond": "diamond v2.2.8.171 (C) Max Planck Society",
            "blastn": "blastn: 2.17.0+"}
FAKE_PYTHON = f"""
import os, sys
if len(sys.argv) > 2 and sys.argv[1] == "-c":
    print({{"pyrodigal": "3.7.1", "pyhmmer": "0.12.3", "pycirclize": "1.10.0"}}[sys.argv[2].split()[1].rstrip(";")])
    sys.exit(0)
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
"""
FAKE_BAKTA = f"""
import os, shutil, sys
args = sys.argv[1:]
if "--help" in args:
    sys.stdout.write(open({str(BAKTA_FIXTURES / "help_1.12.2.txt")!r}).read()); sys.exit(0)
if "--version" in args:
    print("bakta 1.12.2"); sys.exit(0)
out = args[args.index("--output") + 1]
sys.stdout.write(open({str(BAKTA_FIXTURES / "console.log")!r}).read()); sys.stdout.flush()
if os.environ.get("FAKE_BAKTA_OOM"):
    print("ERROR: diamond error! error code: -9"); sys.exit(1)
os.mkdir(out)
for name in os.listdir({str(BAKTA_FIXTURES)!r}):
    if name.startswith("annotation."):
        shutil.copyfile(os.path.join({str(BAKTA_FIXTURES)!r}, name), os.path.join(out, name))
shutil.copyfile(args[0], os.path.join(out, "annotation.fna"))  # not among the fixtures: the genome as given
"""
FAKE_PILERCR = """
import sys
args = sys.argv[1:]
if "-options" in args:
    print("pilercr v1.06"); sys.exit(0)
open(args[args.index("-out") + 1], "w").write("no arrays\\n")
"""
FAKE_AMRFINDER = """
import sys
args = sys.argv[1:]
if "--version" in args:
    print("4.2.7"); sys.exit(0)
print("Software version: 4.2.7"); print("Database version: 2026-10-29.1")
"""


def _exe(path: Path, body: str, interpreter: str = sys.executable) -> Path:
    path.write_text(f"#!{interpreter}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _dmnd(path: Path, letters: int) -> None:
    path.write_bytes(struct.pack("<QIIQQQ", DIAMOND_MAGIC, 164, 3, 1000, letters, 0))


def _database(folder: Path, kind: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "version.json").write_text(json.dumps({"date": "2025-02-24", "major": 6, "minor": 0, "type": kind}))
    for name in BAKTA_REQUIRED_FILES:
        (folder / name).write_bytes(b"x")
    _dmnd(folder / "pscc.dmnd", 1_245_018_838)
    _dmnd(folder / "sorf.dmnd", 8_650)
    if kind == "full":
        _dmnd(folder / "psc.dmnd", 25_000_000_000)
    amr = folder / "amrfinderplus-db" / "2026-10-29.1"
    amr.mkdir(parents=True)
    (amr / "version.txt").write_text("2026-10-29.1\n")
    (folder / "amrfinderplus-db" / "latest").symlink_to("2026-10-29.1")
    return folder


def _record(folder: Path, kind: str, default: bool = False) -> str:
    with SessionLocal() as db:
        r = RefDb(key=f"bakta-{kind}", name=f"Bakta database ({kind})", version="6.0", path=str(folder),
                  status=DatabaseStatus.installed, origin=DatabaseOrigin.download, checksum=f"sha256:{kind}",
                  is_default=default, details={"version_json": json.loads((folder / "version.json").read_text())},
                  log_text="")
        db.add(r)
        db.commit()
        return r.id


@pytest.fixture
def mac(tmp_path, monkeypatch, storage_root):
    """ARVA.app's side and Docker's: a token, a Bakta environment as the osx-arm64 lock creates it (also used as
    Docker's Bakta), the facts it registers, and a full and a light database in ARVA's database folder."""
    token = secrets.token_urlsafe(32)
    (tmp_path / "native-executor.token").write_text(token + "\n")
    env = tmp_path / "arva-tools" / "conda" / "bakta"
    (env / "bin").mkdir(parents=True)
    python = _exe(env / "bin" / "python3.13", FAKE_PYTHON)
    exe = _exe(env / "bin" / "bakta", FAKE_BAKTA, str(python))
    for name, text in VERSIONS.items():
        _exe(env / "bin" / name, f"print({text!r})")
    _exe(env / "bin" / "pilercr", FAKE_PILERCR)
    _exe(env / "bin" / "amrfinder", FAKE_AMRFINDER)
    (env / "conda-meta").mkdir()
    (env / "conda-meta" / "bakta-1.12.2-pyhdfd78af_0.json").write_text(json.dumps(
        {"name": "bakta", "version": "1.12.2", "build": NATIVE_LOCK["build"], "sha256": NATIVE_LOCK["package_sha256"],
         "url": f"https://conda.anaconda.org/bioconda/noarch/{NATIVE_LOCK['package']}"}))
    monkeypatch.setenv("ARVA_TOOL_BAKTA", str(exe))
    registry._CACHE.pop("bakta", None)
    monkeypatch.setattr(tool_tasks, "MONITOR_SECONDS", 0.05)
    monkeypatch.setattr(tool_tasks, "NATIVE_POLL_SECONDS", 0.02)
    databases = get_settings().databases_dir.resolve()
    full = _database(databases / f"bakta-full-{tmp_path.name}" / "6.0", "full")
    light = _database(databases / f"bakta-light-{tmp_path.name}" / "6.0", "light")
    facts = native_facts(str(exe), str(REPO / NATIVE_LOCK["lock"]))
    yield {"token": token, "exe": str(exe), "facts": facts, "data": str(storage_root), "databases": str(databases),
           "full": _record(full, "full", default=True), "light": _record(light, "light"),
           "full_rel": f"bakta-full-{tmp_path.name}/6.0",
           "headers": {"Authorization": f"Bearer {token}"}}
    registry._CACHE.pop("bakta", None)


@pytest.fixture
def setup(client):
    sample = new_sample(client)
    return sample, assemble(client, sample, GENOME)


@pytest.fixture
def small_docker(monkeypatch):
    """Docker Desktop's VM on the user's 8 GB Mac: 5.9 GB."""
    small = host.Detection(host.HostFacts(), host.ContainerFacts(usable_cpus=4, cpus_source="affinity",
                                                                 memory_bytes=int(5.9 * 1024**3),
                                                                 memory_source="cgroup"))
    monkeypatch.setattr(performance, "detection", lambda: small)


def register(client, mac, storage_root, **changes):
    client.post(f"{API}/projects", json={"name": "marker"})
    body = {"executor_id": EXECUTOR_ID, "app_version": "1.4.0", "platform": "osx-arm64", "macos": "15.1",
            "chip": "Apple M2", "memory_bytes": 8 * 1024**3, "data_dir": mac["data"],
            "storage_id": json.loads((storage_root / ".arva-storage").read_text())["id"],
            "database_dirs": [mac["databases"]], "tools": {"bakta": mac["facts"]}}
    r = client.post(f"{API}/native/executor", json={**body, **changes}, headers=mac["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def preview(client, assembly, **body):
    r = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def request(plan, execution="docker"):
    return {"database_id": plan["database_id"], "settings": {"locus_tag": "ANN1"}, "skip_options": plan["skip_options"],
            "confirmed": True, "execution": execution}


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def claim_when_published(client, mac):
    found = {}

    def ready():
        r = client.post(f"{API}/native/jobs/claim", json={"executor_id": EXECUTOR_ID, "tools": ["bakta"]},
                        headers=mac["headers"])
        if r.status_code == 200:
            found.update(r.json())
        return bool(found)

    wait_for(ready)
    return found


def finish(client, mac, taken, report):
    return client.post(f"{API}/native/jobs/{taken['job_id']}/finish",
                       json={"executor_id": EXECUTOR_ID, "lease_id": taken["lease_id"], "report": report},
                       headers=mac["headers"])


def test_the_dialog_warns_and_offers_the_light_database_when_the_full_one_does_not_fit(client, mac, setup,
                                                                                         small_docker):
    _, assembly = setup
    plan = preview(client, assembly)
    assert plan["database_id"] == mac["full"]
    m = plan["memory"]
    assert (m["verdict"], m["largest"], m["block_letters"], m["estimate_gb"], m["container_gb"]) == (
        "may_not_fit", "psc.dmnd", 3_000_000_000, 6.7, 5.9)
    assert m["light_alternative"]["id"] == mac["light"] and m["light_alternative"]["verdict"] == "fits"
    assert m["light_alternative"]["estimate_gb"] == 2.8
    # Without ARVA.app nothing native is offered, and the reason says so.
    assert (plan["native"]["memory_short"], plan["native"]["offered"], plan["native"]["reason"]) == (
        True, False, "not_known")
    light = preview(client, assembly, database_id=mac["light"])
    assert light["memory"]["verdict"] == "fits" and light["memory"]["light_alternative"] is None
    assert light["native"]["offered"] is False


def test_registration_and_the_native_offer(client, mac, setup, storage_root, small_docker):
    _, assembly = setup
    out = register(client, mac, storage_root)
    assert out["ready"] == {"bakta": {"ready": True, "reason": None}}
    st = client.get(f"{API}/system/native-executor").json()
    assert st["tools"]["bakta"]["version"] == "1.12.2" and st["tools"]["bakta"]["lock_matches"] is True
    assert st["expected"]["bakta"]["build"] == NATIVE_LOCK["build"]
    p = preview(client, assembly)["native"]
    assert (p["offered"], p["ready"], p["reason"]) == (True, True, None)
    assert p["database"] == {"root": mac["databases"], "rel": mac["full_rel"]}
    facts = mac["facts"]
    for changes, reason in (({"database_dirs": []}, "no_database_folders"),
                            ({"tools": {"bakta": {**facts, "lock_sha256": "0" * 64}}}, "lock_mismatch"),
                            ({"tools": {"bakta": {**facts, "version": "bakta 1.11.4"}}}, "version_mismatch"),
                            ({"tools": {"bakta": {**facts, "help_options": ["--db"]}}}, "help_incomplete"),
                            ({"tools": {"bakta": {**facts, "tool": "flye"}}}, "tool_mismatch"),
                            ({"tools": {"bakta": {**facts, "executable": "/opt/x/bin/flye"}}}, "unsafe_path")):
        assert register(client, mac, storage_root, **changes)["ready"]["bakta"] == {"ready": False, "reason": reason}
    # A database folder the Mac did not name cannot be read there.
    register(client, mac, storage_root, database_dirs=["/Volumes/JM/other"])
    p = preview(client, assembly)["native"]
    assert (p["offered"], p["ready"], p["reason"]) == (True, False, "native_database_folder_unknown")
    r = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta",
                    json=request(preview(client, assembly, execution="mac_native"), "mac_native"))
    assert (r.status_code, r.json()["code"]) == (409, "native_database_folder_unknown")


def test_a_native_bakta_run_end_to_end(client, mac, setup, storage_root, held_queue, small_docker):
    sample, assembly = setup
    register(client, mac, storage_root)
    plan = preview(client, assembly, execution="mac_native")
    assert plan["execution"] == "mac_native" and all(d.get("on_mac") for d in plan["dependencies"])
    assert plan["skip_options"] == []
    r = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta", json=request(plan, "mac_native"))
    assert r.status_code == 202, r.text
    queued = r.json()
    p = queued["parameters"]
    assert p["execution"] == "mac_native" and p["native_executor"]["build"] == NATIVE_LOCK["build"]
    assert p["native_database"]["root"] == mac["databases"] and p["memory_estimate"]["verdict"] == "may_not_fit"
    assert queued["tool_path"] == mac["exe"] and queued["tool_version"] == "1.12.2"

    worker, result = in_thread(annotation_tasks.run_bakta_job, queued["id"])
    taken = claim_when_published(client, mac)
    work = taken["work"]
    scope = f"results/{sample['project_id']}/{sample['id']}/{queued['id']}"
    assert (work["tool"], work["results_dir"], work["genome"], work["database_type"]) == (
        "bakta", scope, f"{scope}/input/genome.fna", "full")
    assert work["database"] == p["native_database"] and work["amr_data"] is None
    assert work["argv"][:6] == [mac["exe"], f"{mac['data']}/{scope}/input/genome.fna", "--db",
                                f"{mac['databases']}/{p['native_database']['rel']}", "--output",
                                f"{mac['data']}/{scope}/bakta"]
    report = run_native(work, mac["data"], mac["exe"], [mac["databases"]])
    assert report["outcome"] == "exited" and report["exit_code"] == 0, report
    assert finish(client, mac, taken, report).status_code == 200
    worker.join(60)
    d = job(client, queued["id"])
    assert result == ["completed"], d["log_text"][-3000:]
    assert d["commands"] == [work["argv"]]
    n = d["result_summary"]["native"]
    assert d["result_summary"]["execution"] == "mac_native"
    assert (n["platform"], n["build"], n["lock_sha256"], n["bakta_version"]) == (
        "osx-arm64", NATIVE_LOCK["build"], NATIVE_LOCK["lock_sha256"], "bakta 1.12.2")
    assert n["argv"] == work["argv"] and n["database"] == work["database"]
    assert all(x.get("on_mac") for x in d["result_summary"]["programs"])
    assert "Execution: natively on this Mac by ARVA.app 1.4.0" in d["log_text"]
    annotations = client.get(f"{API}/samples/{sample['id']}/annotations").json()
    assert [a["tool"] for a in annotations] == ["Bakta"]
    assert not (storage_root / scope / "bakta-tmp").exists()


def test_a_native_run_killed_for_memory_says_so(client, mac, setup, storage_root, held_queue, small_docker,
                                                  monkeypatch):
    _, assembly = setup
    register(client, mac, storage_root)
    plan = preview(client, assembly, execution="mac_native")
    queued = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta", json=request(plan, "mac_native")).json()
    worker, result = in_thread(annotation_tasks.run_bakta_job, queued["id"])
    taken = claim_when_published(client, mac)
    monkeypatch.setenv("FAKE_BAKTA_OOM", "1")
    report = run_native(taken["work"], mac["data"], mac["exe"], [mac["databases"]])
    assert (report["outcome"], report["exit_code"]) == ("exited", 1)
    assert finish(client, mac, taken, report).status_code == 200
    worker.join(60)
    assert result == ["failed"]
    assert job(client, queued["id"])["error_detail"]["code"] == "bakta_out_of_memory_native"


def test_the_mac_refuses_when_its_programs_differ_from_the_confirmed_steps(client, mac, setup, storage_root,
                                                                           held_queue, small_docker):
    _, assembly = setup
    register(client, mac, storage_root)
    plan = preview(client, assembly, execution="mac_native")
    queued = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta", json=request(plan, "mac_native")).json()
    worker, result = in_thread(annotation_tasks.run_bakta_job, queued["id"])
    taken = claim_when_published(client, mac)
    os.remove(Path(mac["exe"]).parent / "diamond")  # DIAMOND gone from the Mac's environment since the preview
    report = run_native(taken["work"], mac["data"], mac["exe"], [mac["databases"]])
    assert (report["outcome"], report["code"]) == ("refused", "programs_changed")
    assert finish(client, mac, taken, report).status_code == 200
    worker.join(60)
    assert result == ["failed"]
    d = job(client, queued["id"])
    assert d["error_detail"]["code"] == "bakta_native_refused"
    assert d["error_detail"]["params"]["reason"] == "programs_changed"


def test_reported_outputs_must_be_baktas_in_the_jobs_folder(client, mac, setup, storage_root, held_queue,
                                                            small_docker):
    _, assembly = setup
    register(client, mac, storage_root)
    plan = preview(client, assembly, execution="mac_native")
    queued = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta", json=request(plan, "mac_native")).json()
    worker, result = in_thread(annotation_tasks.run_bakta_job, queued["id"])
    taken = claim_when_published(client, mac)
    report = {"tool": "bakta", "outcome": "exited", "exit_code": 0, "argv": taken["work"]["argv"],
              "executable": mac["exe"], "outputs": [f"{taken['work']['out_dir']}/../../secret.txt"]}
    r = finish(client, mac, taken, report)
    assert (r.status_code, r.json()["code"]) == (422, "native_unsafe_path")
    worker.join(60)
    assert result == ["failed"]


def test_a_database_in_a_docker_volume_cannot_run_natively(client, mac, setup, storage_root, small_docker,
                                                           monkeypatch):
    """Without the launcher's host path of the database folder (a Docker named volume), the Mac cannot read it."""
    from app.services import locations

    _, assembly = setup
    register(client, mac, storage_root)
    monkeypatch.setattr(locations, "in_container", lambda: True)
    p = preview(client, assembly)["native"]
    assert (p["offered"], p["ready"], p["reason"]) == (True, False, "native_database_not_on_mac")
    assert native.status()["tools"]["bakta"]["ready"] is True
