"""Cancelling queued and running jobs, and resuming a stopped Flye run from its kept work folder.

Jobs are created through the API into a task queue that does not run them (as when no worker is free), then run
by calling the worker task in a thread, as a worker would. The stand-in tools run until they are killed, so a
cancellation that did not stop the tool's process group would hang the test. The last test runs the real Flye
and is skipped without it.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from arva_tools import ToolStatus
from arva_tools.registry import detect
from rq.job import JobStatus as RqStatus

from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus
from app.tasks import tools as tool_tasks

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "synthetic"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
FLYE_FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "flye"

# SeqKit stand-in: writes part of its table, starts a child in its process group, then waits to be killed.
SLOW_SEQKIT = r'''
import os, subprocess, sys, time
from pathlib import Path
if sys.argv[1:] == ["version"]:
    print("seqkit v2.3.0")
    sys.exit(0)
print("file\tformat\ttype\tnum_seqs", flush=True)
Path("partial-output.tmp").write_text("partial")
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
Path(os.environ["FAKE_PIDS"]).write_text(f"{os.getpid()} {child.pid}")
time.sleep(120)
'''

# Flye stand-in with Flye 2.9.3's checkpoint behaviour: params.json names the stage before it starts, each stage
# writes in its own folder, and --resume continues from params.json's stage in an existing --out-dir.
RESUMABLE_FLYE = r'''
import json, os, signal, sys, time
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]:
    print("2.9.3-b1797")
    sys.exit(0)
if args == ["--help"]:
    sys.stdout.write(Path(os.environ["FAKE_FLYE_HELP"]).read_text())
    sys.exit(0)
out = Path(args[args.index("--out-dir") + 1])
resume = "--resume" in args
stages = ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"]
dirs = {"assembly": "00-assembly", "consensus": "10-consensus", "repeat": "20-repeat", "contigger": "30-contigger",
        "polishing": "40-polishing"}
def say(line):
    text = f"[2026-10-28 13:37:13] root: INFO: {line}\n"
    sys.stderr.write(text)
    sys.stderr.flush()
    with open(out / "flye.log", "a") as fh:
        fh.write(text)
with open(os.environ["FAKE_FLYE_DUMP"], "a") as dump:
    dump.write("ARGS=" + "\t".join(args) + "\n")
    if resume:
        start = json.loads((out / "params.json").read_text())["stage_name"]
        present = sorted(p.name for p in out.iterdir() if p.is_dir())
        dump.write("RESUME_FROM=" + start + "\nDIRS=" + ",".join(present) + "\n")
if resume:
    say("Resuming previous run")
    stages = stages[stages.index(start):]
else:
    out.mkdir()
stop, mode = os.environ.get("FAKE_FLYE_STOP_AT"), os.environ.get("FAKE_FLYE_MODE", "hang")
for stage in stages:
    (out / "params.json").write_text(json.dumps({"pipeline_version": 3, "stage_name": stage}))
    say(">>>STAGE: " + stage)
    if stage in dirs:
        (out / dirs[stage]).mkdir(exist_ok=True)
        with open(out / dirs[stage] / "partial.txt", "a") as fh:
            fh.write(stage + "\n")
    if stage == stop and not resume:
        if mode == "error":
            sys.stderr.write("[2026-10-28 13:47:09] ERROR: No contigs were assembled - pipeline stopped\n")
            sys.exit(1)
        if mode == "killed":
            os.kill(os.getpid(), signal.SIGKILL)
        Path(os.environ["FAKE_PIDS"]).write_text(str(os.getpid()))
        time.sleep(120)
info = Path(os.environ["FAKE_FLYE_INFO"]).read_text()
rows = [line.split("\t") for line in info.splitlines()[1:] if line.strip()]
(out / "assembly_info.txt").write_text(info)
with open(out / "assembly.fasta", "w") as fa:
    for r in rows:
        fa.write(f">{r[0]}\n" + ("ACGTTGCA" * (int(r[1]) // 8 + 1))[:int(r[1])] + "\n")
(out / "assembly_graph.gfa").write_text("H\tVN:Z:1.0\n" + "".join(f"S\tedge_{i + 1}\t*\tLN:i:{r[1]}\n"
                                                                    for i, r in enumerate(rows)))
'''


def executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return path


@pytest.fixture(autouse=True)
def quick_monitor(monkeypatch):
    monkeypatch.setattr(tool_tasks, "MONITOR_SECONDS", 0.05)


@pytest.fixture
def slow_seqkit(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVA_TOOL_SEQKIT", str(executable(tmp_path / "bin" / "seqkit", SLOW_SEQKIT)))
    monkeypatch.setenv("FAKE_PIDS", str(tmp_path / "pids"))
    return tmp_path / "pids"


@pytest.fixture
def resumable_flye(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVA_TOOL_FLYE", str(executable(tmp_path / "bin" / "flye", RESUMABLE_FLYE)))
    monkeypatch.setenv("ARVA_TOOL_SAMTOOLS", str(executable(tmp_path / "bin" / "samtools",
                                                            "print('samtools 1.19.2')")))
    monkeypatch.setenv("FAKE_FLYE_HELP", str(FLYE_FIXTURES / "help_2.9.3.txt"))
    monkeypatch.setenv("FAKE_FLYE_INFO", str(FLYE_FIXTURES / "synthetic150_assembly_info.txt"))
    monkeypatch.setenv("FAKE_FLYE_DUMP", str(tmp_path / "dump.txt"))
    monkeypatch.setenv("FAKE_PIDS", str(tmp_path / "pids"))

    def mode(stop_at: str | None, how: str = "hang"):
        if stop_at:
            monkeypatch.setenv("FAKE_FLYE_STOP_AT", stop_at)
        else:
            monkeypatch.delenv("FAKE_FLYE_STOP_AT", raising=False)
        monkeypatch.setenv("FAKE_FLYE_MODE", how)
        return tmp_path / "dump.txt", tmp_path / "pids"

    return mode


def new_sample(client, technology="nanopore"):
    p = client.post(f"{API}/projects", json={"name": "Control"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": "CTL-1", "sequencing_technology": technology}).json()


def upload(client, sample_id, path: Path, name: str | None = None):
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (name or path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def scope(sample, job_id) -> str:
    return f"{sample['project_id']}/{sample['id']}/{job_id}"


def in_thread(task, job_id) -> tuple[threading.Thread, list]:
    result: list = []
    t = threading.Thread(target=lambda: result.append(task(job_id)), daemon=True)
    t.start()
    return t, result


def wait_for(condition, seconds=30.0):
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail("timed out")
        time.sleep(0.05)


def gone(pid: int) -> bool:
    """Stopped: no such process, or a zombie (killed, waiting for init to reap it)."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


def test_a_queued_job_is_cancelled_at_once_and_never_runs(client, held_queue, slow_seqkit, storage_root):
    sample = new_sample(client)
    files = [upload(client, sample["id"], ONT), upload(client, sample["id"], R1)]
    queued = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit",
                         json={"raw_file_ids": [f["id"] for f in files]}).json()
    assert [j["status"] for j in queued] == ["pending", "pending"] and held_queue.count == 2

    r = client.post(f"{API}/jobs/{queued[0]['id']}/cancel")
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["status"] == "cancelled" and d["cancel_requested_at"] and d["finished_at"] and d["error_message"] is None
    assert "cancelled before a worker started it, so nothing was run" in d["log_text"]
    assert held_queue.count == 1 and held_queue.job_ids == [f"arva-{queued[1]['id']}"]
    assert (storage_root / "logs" / f"{d['id']}.log").read_text() == d["log_text"]

    # A worker that had already taken the task off the queue does nothing.
    assert tool_tasks.run_seqkit_job(d["id"]) == "cancelled"
    assert job(client, d["id"])["log_text"] == d["log_text"] and not slow_seqkit.exists()
    assert not (storage_root / "results" / scope(sample, d["id"])).exists()
    assert job(client, queued[1]["id"])["status"] == "pending"

    r = client.post(f"{API}/jobs/{d['id']}/cancel")
    assert r.status_code == 409 and "already finished (status 'cancelled')" in r.json()["detail"]
    assert client.post(f"{API}/jobs/00000000-0000-0000-0000-000000000000/cancel").status_code == 404


def test_cancelling_a_running_job_kills_the_tool_group_and_removes_partial_outputs(client, held_queue, slow_seqkit,
                                                                                    storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    (queued,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    held_queue.fetch_job(f"arva-{queued['id']}").set_status(RqStatus.STARTED)
    worker, result = in_thread(tool_tasks.run_seqkit_job, queued["id"])
    wait_for(slow_seqkit.exists)
    results = storage_root / "results" / scope(sample, queued["id"])
    assert (results / "partial-output.tmp").is_file()

    r = client.post(f"{API}/jobs/{queued['id']}/cancel")
    assert r.status_code == 202 and r.json()["status"] == "running" and r.json()["cancel_requested_at"]
    worker.join(30)
    assert result == ["cancelled"]
    assert all(gone(int(pid)) for pid in slow_seqkit.read_text().split())
    d = job(client, queued["id"])
    assert d["status"] == "cancelled" and d["error_message"] is None and d["output_paths"] is None
    assert "Command: " in d["log_text"] and "Cancelled at the user's request (asked at " in d["log_text"]
    assert "Finished with status 'cancelled'" in d["log_text"]
    assert not results.exists() and (storage_root / "logs" / f"{d['id']}.log").read_text() == d["log_text"]


def test_a_running_job_no_worker_executes_is_ended_at_once(client, held_queue, slow_seqkit, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    (queued,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    with SessionLocal() as db:
        j = db.get(AnalysisJob, queued["id"])
        j.status = JobStatus.running
        db.commit()
    held_queue.fetch_job(f"arva-{queued['id']}").set_status(RqStatus.FAILED)
    partial = storage_root / "results" / scope(sample, queued["id"])
    partial.mkdir(parents=True)
    (partial / "half.tsv").write_text("x")

    d = client.post(f"{API}/jobs/{queued['id']}/cancel").json()
    assert d["status"] == "cancelled" and "task queue status: failed" in d["log_text"] and not partial.exists()


def _cancel_flye_at(client, sample, files, pids, stage_dir_count=None):
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [f["id"] for f in files], "params": {"read_type": "nano-hq", "threads": 2}})
    assert r.status_code == 202, r.text
    worker, result = in_thread(tool_tasks.run_flye_job, r.json()["id"])
    wait_for(pids.exists)
    assert client.post(f"{API}/jobs/{r.json()['id']}/cancel").status_code == 202
    worker.join(30)
    assert result == ["cancelled"] and gone(int(pids.read_text()))
    return job(client, r.json()["id"])


def test_a_cancelled_flye_run_keeps_its_work_folder_and_resumes(client, held_queue, resumable_flye, storage_root):
    dump, pids = resumable_flye("repeat")
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    first = _cancel_flye_at(client, sample, [f], pids)
    kept = first["checkpoint"]
    assert kept["reason"] == "cancelled" and kept["tool_version"] == "2.9.3" and kept["resume_stage"] == "repeat"
    assert kept["completed_stages"] == ["configure", "assembly", "consensus"] and kept["size_bytes"] > 0
    folder = storage_root / kept["path"]
    assert kept["path"] == f"checkpoints/{scope(sample, first['id'])}/flye"
    assert sorted(p.name for p in folder.iterdir()) == ["00-assembly", "10-consensus", "flye.log", "params.json"]
    assert not (storage_root / "results" / scope(sample, first["id"])).exists()
    assert "so the run can resume from repeat (removed 20-repeat, written by the interrupted stage)" in first["log_text"]

    r = client.post(f"{API}/jobs/{first['id']}/resume")
    assert r.status_code == 202, r.text
    second = r.json()
    assert second["status"] == "pending" and second["input_raw_file_ids"] == [f["id"]]
    assert second["parameters"]["resume"] == {"of_job_id": first["id"], "checkpoint_path": kept["path"],
                                              "stage": "repeat", "completed_stages": kept["completed_stages"]}
    assert {k: v for k, v in second["parameters"].items() if k != "resume"} == first["parameters"]
    assert client.post(f"{API}/jobs/{first['id']}/resume").status_code == 409
    r = client.delete(f"{API}/jobs/{first['id']}/checkpoint")
    assert r.status_code == 409 and f"Job {second['id']} is already resuming this run" in r.json()["detail"]

    resumable_flye(None)
    assert tool_tasks.run_flye_job(second["id"]) == "completed", job(client, second["id"])["log_text"]
    lines = dump.read_text().splitlines()
    assert lines[-3].startswith("ARGS=--nano-hq\t") and lines[-3].endswith("\t--resume")
    assert lines[-2:] == ["RESUME_FROM=repeat", "DIRS=00-assembly,10-consensus"]
    d = job(client, second["id"])
    assert d["commands"][0][-1] == "--resume" and d["result_summary"]["resumed"] == {
        "from_job_id": first["id"], "stage": "repeat", "completed_stages": ["configure", "assembly", "consensus"]}
    assert d["result_summary"]["log"]["stages_seen"] == d["progress"]["stages"]
    assert d["result_summary"]["log"]["resumed_at"] == ["repeat"]
    assert d["progress"]["stage"] == "finalize" and d["progress"]["stage_index"] == 7
    assert f"Resuming job {first['id']}: its Flye work folder moved here" in d["log_text"]
    assert job(client, first["id"])["checkpoint"] is None and not folder.exists()
    assert not folder.parent.exists()
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert a["job_id"] == second["id"] and a["assembler"] == "Flye"
    r = client.post(f"{API}/jobs/{first['id']}/resume")
    assert r.status_code == 409 and "kept no Flye work folder" in r.json()["detail"]


def test_which_stopped_flye_runs_can_resume(client, held_queue, resumable_flye, storage_root):
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)

    resumable_flye("repeat", "error")
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [f["id"]], "params": {"read_type": "nano-hq"}}).json()
    assert tool_tasks.run_flye_job(r["id"]) == "failed"
    d = job(client, r["id"])
    assert d["checkpoint"] is None and "Flye stopped with an error of its own" in d["log_text"]
    assert not (storage_root / "checkpoints" / scope(sample, r["id"])).exists()

    resumable_flye("consensus", "killed")
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [f["id"]], "params": {"read_type": "nano-hq"}}).json()
    assert tool_tasks.run_flye_job(r["id"]) == "failed"
    d = job(client, r["id"])
    assert "ran out of memory" in d["error_message"]
    assert d["checkpoint"]["reason"] == "stopped" and d["checkpoint"]["resume_stage"] == "consensus"

    # Resuming needs the Flye version that wrote the folder.
    with SessionLocal() as db:
        j = db.get(AnalysisJob, r["id"])
        j.checkpoint = {**j.checkpoint, "tool_version": "2.9.2"}
        db.commit()
    res = client.post(f"{API}/jobs/{r['id']}/resume")
    assert res.status_code == 409 and "written by Flye 2.9.2 and Flye 2.9.3 is installed" in res.json()["detail"]

    folder = storage_root / d["checkpoint"]["path"]
    r2 = client.delete(f"{API}/jobs/{r['id']}/checkpoint")
    assert r2.status_code == 200 and r2.json()["checkpoint"] is None and not folder.exists()
    assert "Discarded the kept Flye work folder" in r2.json()["log_text"]
    assert client.post(f"{API}/jobs/{r['id']}/resume").status_code == 409

    # Nothing beyond configure completed: nothing worth keeping.
    _, pids = resumable_flye("assembly")
    d = _cancel_flye_at(client, sample, [f], pids)
    assert d["checkpoint"] is None and "no stage after configure had completed" in d["log_text"]


@pytest.mark.skipif(detect("flye").status is not ToolStatus.available, reason="Flye is not installed")
def test_real_flye_cancelled_during_polishing_resumes_to_the_right_assembly(client, held_queue, tmp_path,
                                                                            storage_root):
    """Flye 2.9.3 appends to the bubbles file of an interrupted polishing stage when resumed; without ARVA removing
    that stage's folder, this genome's 15 kb plasmid came out as 30 kb (arva_tools.flye)."""
    data = tmp_path / "genome"
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_synthetic_genome.py"), str(data), "--ont-depth", "30",
                    "--illumina-depth", "1"], check=True, capture_output=True)
    sample = new_sample(client)
    f = upload(client, sample["id"], data / "ont.fastq.gz")
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [f["id"]], "params": {"read_type": "nano-hq", "threads": 2}}).json()
    worker, result = in_thread(tool_tasks.run_flye_job, r["id"])
    wait_for(lambda: (job(client, r["id"]).get("progress") or {}).get("stage") == "polishing", seconds=600)
    time.sleep(2)
    client.post(f"{API}/jobs/{r['id']}/cancel")
    worker.join(120)
    first = job(client, r["id"])
    assert result == ["cancelled"] and first["checkpoint"]["resume_stage"] == "polishing", first["log_text"]
    assert not (storage_root / first["checkpoint"]["path"] / "40-polishing").exists()

    second = client.post(f"{API}/jobs/{r['id']}/resume").json()
    assert tool_tasks.run_flye_job(second["id"]) == "completed", job(client, second["id"])["log_text"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    lengths = sorted(c["length"] for c in client.get(f"{API}/assemblies/{a['id']}").json()["contigs"])
    assert len(lengths) == 2 and abs(lengths[0] - 15_000) <= 10 and abs(lengths[1] - 300_000) <= 10
    assert job(client, second["id"])["result_summary"]["resumed"]["stage"] == "polishing"
