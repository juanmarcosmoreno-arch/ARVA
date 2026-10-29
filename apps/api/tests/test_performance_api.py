"""GET/PUT /system/performance, the resources a job records, the CPU priority tools run at, and the failure reason
of a tool killed by SIGKILL. Host facts are CONSTRUCTED (see test_performance.py)."""
import os
import stat
import sys
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import host, performance

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
GIB = 1024**3

M1_PRO = host.Detection(
    host.HostFacts(**{k: host.Fact(v, "launcher") for k, v in {
        "platform": "macos", "model_name": "MacBook Pro", "model_id": "MacBookPro18,3", "chip": "Apple M1 Pro",
        "performance_cores": 8, "efficiency_cores": 2, "physical_cores": 10, "logical_cpus": 10,
        "memory_bytes": 32 * GIB, "os_version": "14.5", "arch": "arm64", "docker_cpus": 4,
        "docker_memory_bytes": 8 * GIB}.items()}),
    host.ContainerFacts(usable_cpus=4, cpus_source="affinity", memory_bytes=int(7.7 * GIB), memory_source="meminfo",
                        in_container=True, container_marker="docker"))


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(performance, "detection", lambda: M1_PRO)
    monkeypatch.setattr(get_settings(), "tool_threads", None)


@pytest.fixture
def sample(client):
    p = client.post(f"{API}/projects", json={"name": "Perf"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "P1"}).json()


def upload(client, sample_id, path):
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def fake_seqkit(tmp_path, monkeypatch, body: str) -> None:
    exe = tmp_path / "seqkit"
    exe.write_text(f"#!{sys.executable}\nimport os, signal, sys\nif sys.argv[1] == 'version':\n"
                   "    print('seqkit v2.3.0'); sys.exit(0)\n" + body + "\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ARVA_TOOL_SEQKIT", str(exe))


def test_get_performance_describes_detection_profile_and_docker(client, mac):
    d = client.get(f"{API}/system/performance").json()
    assert d["host"]["model_name"] == {"value": "MacBook Pro", "source": "launcher"}
    assert "serial_number" not in d["host"]
    assert (d["mac_class"], d["container"]["usable_cpus"], d["container"]["in_container"]) == ("macbook_pro", 4, True)
    assert d["automatic"] == {"profile": "balanced", "reason": "macbook_pro", "core_basis": "performance_cores",
                              "cores": 8}
    assert d["choice"] == {"profile": "auto", "threads": None, "memory_gb": None, "updated_at": None}
    e = d["effective"]
    # Balanced asks for 6 of the 8 performance cores; Docker Desktop gives the container 4.
    assert (e["profile"], e["threads"], e["max_threads"], e["requested_threads"]) == ("balanced", 4, 4, 6)
    assert (e["memory_gb"], e["max_memory_gb"], e["nice"], e["exceeds"]) == (5, 7, 10, ["threads"])
    assert [(p["profile"], p["threads"], p["memory_gb"]) for p in d["profiles"]] == [
        ("light", 4, 3), ("balanced", 4, 5), ("maximum", 4, 6)]
    assert d["docker"]["status"] == "adjust"
    assert d["docker"]["cpus"] == {"current": 4, "recommended": 7, "status": "increase"}
    assert (d["docker"]["memory"]["recommended_gb"], d["docker"]["memory"]["status"]) == (19, "increase")


def test_put_performance_validates_and_saves(client, mac):
    for bad in ({"profile": "turbo"}, {"profile": "custom", "threads": 2}, {"profile": "custom", "threads": 0,
                "memory_gb": 2}, {"profile": "light", "extra": 1}, {"profile": "custom", "threads": 2, "memory_gb": 9999}):
        assert client.put(f"{API}/system/performance", json=bad).status_code == 422, bad
    d = client.put(f"{API}/system/performance", json={"profile": "custom", "threads": 12, "memory_gb": 20}).json()
    assert d["choice"]["profile"] == "custom" and d["choice"]["updated_at"]
    assert (d["effective"]["threads"], d["effective"]["memory_gb"], d["effective"]["exceeds"]) == (
        4, 7, ["threads", "memory_gb"])
    d = client.put(f"{API}/system/performance", json={"profile": "light", "threads": 3, "memory_gb": 3}).json()
    assert d["choice"] == {**d["choice"], "profile": "light", "threads": None, "memory_gb": None}
    assert client.get(f"{API}/system/performance").json()["effective"]["profile"] == "light"


def test_admin_caps_apply_to_every_profile(client, mac, monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_threads", 2)
    monkeypatch.setattr(get_settings(), "tool_memory_gb", 3)
    e = client.put(f"{API}/system/performance", json={"profile": "maximum"}).json()["effective"]
    assert (e["threads"], e["max_threads"], e["memory_gb"], e["max_memory_gb"]) == (2, 2, 3, 3)
    assert (e["admin_threads"], e["admin_memory_gb"]) == (2, 3)


def test_previews_take_their_default_threads_from_the_profile(client, mac, sample):
    client.put(f"{API}/system/performance", json={"profile": "light"})
    f = upload(client, sample["id"], R1)
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/spades/preview",
                       json={"inputs": {"unpaired_file_id": f["id"]}}).json()
    # Light on 8 performance cores: 4 threads, 50 % of 7.7 GB.
    assert (plan["tool"]["default_threads"], plan["tool"]["max_threads"]) == (4, 4)
    assert (plan["tool"]["default_memory_gb"], plan["tool"]["max_memory_gb"]) == (3, 7)


def test_a_job_records_its_resources_and_runs_at_lower_priority(client, sample, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_threads", None)
    client.put(f"{API}/system/performance", json={"profile": "light"})
    fake_seqkit(tmp_path, monkeypatch, "open(os.environ['NICE_OUT'], 'w').write(str(os.nice(0)))\n"
                "print('file\\tnum_seqs'); print('reads.fastq.gz\\t2000')")
    monkeypatch.setenv("NICE_OUT", str(tmp_path / "nice.txt"))
    f = upload(client, sample["id"], R1)
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    d = client.get(f"{API}/jobs/{j['id']}").json()
    r = d["resources"]
    # The test computer (8 usable CPUs, 64 GB, no host facts) with light chosen: half the cores, half the memory.
    assert (r["profile"], r["choice"], r["threads"], r["memory_gb"], r["nice"]) == ("light", "light", 4, 32, 15)
    assert (r["usable_cpus"], r["usable_memory_gb"], r["host"], r["in_container"]) == (8, 64.0, "unknown computer",
                                                                                        False)
    assert d["status"] == "completed" and d["parameters"]["threads"] == 4
    assert r["nice_executable"] and int((tmp_path / "nice.txt").read_text()) == os.nice(0) + 15
    assert "CPU priority: tools start through" in d["log_text"]
    assert d["commands"][0][0] == str(tmp_path / "seqkit")
    report = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
    assert report["processing"][0]["resources"]["profile"] == "light"
    html = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "html"}).text
    assert ("Resources: light performance profile (chosen); 4 thread(s); CPU priority nice 15; ARVA could use 8 CPUs "
            "and 64.0 GB; computer: unknown computer") in html
    assert "came from ARVA's performance profile" in html


def test_a_tool_killed_by_sigkill_fails_with_a_memory_reason(client, sample, tmp_path, monkeypatch):
    fake_seqkit(tmp_path, monkeypatch, "os.kill(os.getpid(), signal.SIGKILL)")
    f = upload(client, sample["id"], R1)
    (j,) = client.post(f"{API}/samples/{sample['id']}/analyses/seqkit", json={"raw_file_ids": [f["id"]]}).json()
    d = client.get(f"{API}/jobs/{j['id']}").json()
    assert d["status"] == "failed"
    msg = d["error_message"]
    assert msg.startswith("seqkit exited with status -9. seqkit was stopped by the operating system with SIGKILL")
    assert "ARVA could use 64.0 GB of memory here; this job ran with 4 thread(s) (balanced profile)" in msg
    assert "lighter performance profile or fewer threads" in msg and "Docker" not in msg
    assert "ARVA could use 64.0 GB" in d["log_text"]


def test_an_adapter_memory_reason_gets_only_the_advice():
    from types import SimpleNamespace

    from app.tasks.common import _with_memory_advice

    job = SimpleNamespace(
        error_message="Racon was stopped by the operating system, most likely because the computer ran out of memory",
        resources={"profile": "light", "threads": 2, "usable_memory_gb": 7.7, "in_container": True})
    message, note = _with_memory_advice(job, "racon")
    assert message.count("out of memory") == 1 and message.endswith("(Docker Desktop → Settings → Resources).")
    assert note.startswith("ARVA could use 7.7 GB of memory here (the container's limit)")


def test_samtools_sort_memory_follows_the_jobs_memory():
    from types import SimpleNamespace

    from app.tasks.polishing import _sort_memory_mb

    ctx = SimpleNamespace(job=SimpleNamespace(resources={"memory_gb": 2}))
    assert _sort_memory_mb(ctx, 4) == 512 and _sort_memory_mb(ctx, 2) is None
    ctx.job.resources = {}
    assert _sort_memory_mb(ctx, 4) is None


def test_text_report_module_runs(monkeypatch, capsys, mac):
    assert performance.main(["--lang", "es"]) == 0
    out = capsys.readouterr().out
    assert "Perfil de rendimiento de ARVA" in out and "MacBook Pro (MacBookPro18,3) · Apple M1 Pro" in out


def test_priority_for_jobs_with_and_without_resources():
    from types import SimpleNamespace

    from app.tasks.tools import _priority

    lines = []
    old = SimpleNamespace(job=SimpleNamespace(resources=None), log=lines.append)
    assert _priority(old) == 0 and old.job.resources is None and lines == []
    ctx = SimpleNamespace(job=SimpleNamespace(resources={"nice": 10, "profile": "balanced"}), log=lines.append)
    assert _priority(ctx) == 10 and ctx.job.resources["nice_executable"].endswith("nice")
    assert _priority(ctx) == 10 and len(lines) == 1 and "nice -n 10" in lines[0]
