"""Flye's native entry (ARVA.app on an Apple silicon Mac): the same argument vector as the Docker run with the Mac's
paths, every check before running, the run itself with a fake flye, and the lock it installs from. Runs on Linux."""
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from arva_tools import flye as flye_module
from arva_tools.flye import (
    NATIVE_LOCK,
    FlyeAdapter,
    FlyeParams,
    NativeRefusal,
    native_expected_argv,
    native_facts,
    native_relative,
    prepare_native,
    run_native,
)

FIXTURES = Path(__file__).parent / "fixtures" / "flye"
ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "workflows" / "tool-adapters" / "arva_tools" / "native.py"
HELP_296 = (FIXTURES / "help_2.9.6.txt").read_text()
SCOPE = "results/0b0f7c1e-0000-4000-8000-000000000001/_project/0b0f7c1e-0000-4000-8000-000000000002"

# A stand-in for Bioconda's flye 2.9.6: its real --help text; a run writes Flye's four outputs into --out-dir
# (created with mkdir, as Flye does) and logs a stage; a read named *FAIL* fails as Flye does, *SLEEP* waits.
FAKE_FLYE = f"""
import os, sys, time
args = sys.argv[1:]
if "--help" in args:
    sys.stdout.write({HELP_296!r}); sys.exit(0)
if "--version" in args:
    print("2.9.6-b1802"); sys.exit(0)
out = args[args.index("--out-dir") + 1]
reads = [a for a in args[1:args.index("--out-dir")]]
sys.stderr.write(">>>STAGE: configure\\n"); sys.stderr.flush()
if any("FAIL" in r for r in reads):
    sys.stderr.write("ERROR: No disjointigs were assembled\\n"); sys.exit(1)
if any("SLEEP" in r for r in reads):
    open(os.path.join(os.path.dirname(out), "flye.pid"), "w").write(str(os.getpid()))
    time.sleep(60)
for r in reads:
    open(r, "rb").read()
os.mkdir(out)
for name in ("assembly.fasta", "assembly_graph.gfa", "assembly_info.txt", "flye.log"):
    open(os.path.join(out, name), "w").write("x\\n")
open(os.path.join(out, "argv.txt"), "w").write("\\n".join(sys.argv))
"""


def _exe(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def mac(tmp_path):
    """A Mac as ARVA.app sees it: a Flye environment (flye, flye-samtools, conda-meta) and a data folder with its
    storage marker, a stored read file and the job's results folder with a relative link to it."""
    env = tmp_path / "arva-tools" / "conda" / "flye"
    (env / "bin").mkdir(parents=True)
    flye = _exe(env / "bin" / "flye", FAKE_FLYE)
    _exe(env / "bin" / "flye-samtools", "")
    (env / "conda-meta").mkdir()
    (env / "conda-meta" / "flye-2.9.6-py313h05f0e27_1.json").write_text(json.dumps(
        {"name": "flye", "version": "2.9.6", "build": "py313h05f0e27_1", "sha256": NATIVE_LOCK["package_sha256"],
         "url": "https://conda.anaconda.org/bioconda/osx-arm64/" + NATIVE_LOCK["package"]}))
    data = tmp_path / "Volumes" / "JM" / "ARVA" / "data"
    storage_id = str(uuid.uuid4())
    (data / "raw").mkdir(parents=True)
    (data / ".arva-storage").write_text(json.dumps({"id": storage_id}))
    (data / "raw" / "reads.fastq.gz").write_bytes(b"\x1f\x8b reads")
    results = data / SCOPE
    (results / "input").mkdir(parents=True)
    link = results / "input" / "01_reads.fastq.gz"
    link.symlink_to(os.path.relpath(data / "raw" / "reads.fastq.gz", link.parent))
    return {"data": str(data), "exe": str(flye), "storage_id": storage_id, "results": results}


def work_for(mac, **changes):
    params = FlyeParams(read_type="nano-hq", threads=2, genome_size_bp=2_800_000, genome_size_basis="entered")
    reads, out_dir = [f"{SCOPE}/input/01_reads.fastq.gz"], f"{SCOPE}/flye"
    supported = FlyeAdapter.help_options(mac["exe"])
    work = {"tool": "flye", "storage_id": mac["storage_id"], "data_dir": mac["data"], "executable": mac["exe"],
            "params": params.as_dict(), "reads": reads, "out_dir": out_dir, "results_dir": SCOPE,
            "stderr_log": "flye.stderr.log", "resume": False,
            "argv": native_expected_argv(params, mac["data"], mac["exe"], reads, out_dir, supported, False)}
    return {**work, **changes}


def test_native_argv_is_the_docker_argv_with_the_macs_paths(mac):
    work = work_for(mac)
    argv, results, env = prepare_native(work, mac["data"], mac["exe"])
    params = FlyeParams.from_dict(work["params"])
    docker = FlyeAdapter.argv("/opt/arva-tools/conda/flye/bin/flye", params,
                              [Path(f"/data/{SCOPE}/input/01_reads.fastq.gz")], Path(f"/data/{SCOPE}/flye"),
                              FlyeAdapter.help_options(mac["exe"]))
    assert argv == work["argv"]
    assert argv[1:] == [a.replace("/data/", mac["data"] + "/") for a in docker[1:]]
    assert argv[0] == mac["exe"] and str(results) == f"{mac['data']}/{SCOPE}"
    assert env["PATH"].split(os.pathsep)[0] == str(Path(mac["exe"]).parent)


def test_a_native_run_writes_flyes_outputs_and_reports_what_ran(mac):
    work = work_for(mac)
    report = run_native(work, mac["data"], mac["exe"])
    assert (report["outcome"], report["exit_code"], report["code"]) == ("exited", 0, None)
    assert report["argv"] == work["argv"] and report["executable"] == mac["exe"]
    assert report["outputs"] == [f"{SCOPE}/flye/{n}" for n in flye_module.OUTPUTS]
    assert (mac["results"] / "flye.stderr.log").read_text().startswith(">>>STAGE: configure")
    ran = (mac["results"] / "flye" / "argv.txt").read_text().splitlines()
    assert ran == work["argv"]
    assert report["started_at"] and report["finished_at"] and report["duration_seconds"] is not None


def test_a_failing_flye_is_reported_with_its_exit_code(mac):
    target = Path(mac["data"]) / "raw" / "reads.fastq.gz"
    fail = mac["results"] / "input" / "01_FAIL.fastq.gz"
    fail.symlink_to(os.path.relpath(target, fail.parent))
    work = work_for(mac)
    work["reads"] = [f"{SCOPE}/input/01_FAIL.fastq.gz"]
    work["argv"] = native_expected_argv(FlyeParams.from_dict(work["params"]), mac["data"], mac["exe"], work["reads"],
                                        work["out_dir"], FlyeAdapter.help_options(mac["exe"]), False)
    report = run_native(work, mac["data"], mac["exe"])
    assert (report["outcome"], report["exit_code"], report["code"], report["outputs"]) == ("exited", 1, "tool_exit", [])
    assert "No disjointigs" in (mac["results"] / "flye.stderr.log").read_text()


@pytest.mark.parametrize("rel", ["../outside.fastq.gz", "/etc/passwd", f"{SCOPE}/../x", f"{SCOPE}//x", "", ".",
                                 f"{SCOPE}/input/01 reads.fastq.gz", "results/./x", "results/x\\y"])
def test_relative_paths_with_dotdot_or_outside_the_folder_are_refused(rel):
    with pytest.raises(NativeRefusal) as exc:
        native_relative(rel)
    assert exc.value.code == "unsafe_path"


def _refusal(work, mac, data=None, exe=None):
    report = run_native(work, data or mac["data"], exe or mac["exe"])
    assert report["outcome"] == "refused" and report["exit_code"] is None and report["argv"] is None
    assert not (mac["results"] / "flye").exists() and not (mac["results"] / "flye.stderr.log").exists()
    return report["code"]


def test_every_check_runs_before_flye(mac, tmp_path):
    assert _refusal(work_for(mac, reads=["../../etc/passwd"]), mac) == "unsafe_path"
    assert _refusal(work_for(mac, out_dir="/tmp/flye"), mac) == "unsafe_path"
    # A link in the data folder that leads outside it.
    outside = tmp_path / "secret.fastq.gz"
    outside.write_bytes(b"x")
    escape = mac["results"] / "input" / "02_escape.fastq.gz"
    escape.symlink_to(outside)
    assert _refusal(work_for(mac, reads=[f"{SCOPE}/input/02_escape.fastq.gz"]), mac) == "outside_data_dir"
    assert _refusal(work_for(mac, storage_id=str(uuid.uuid4())), mac) == "storage_mismatch"
    assert _refusal(work_for(mac, data_dir="/Volumes/Other/data"), mac) == "other_data_dir"
    assert _refusal(work_for(mac, executable="/usr/local/bin/flye"), mac) == "other_executable"
    # The API's argument vector is never run as given: one that differs from the adapter's is refused.
    for changed in (lambda a: [*a, "--meta"], lambda a: ["/bin/sh", *a[1:]], lambda a: [*a[:-1], "8"]):
        work = work_for(mac)
        assert _refusal({**work, "argv": changed(work["argv"])}, mac) == "argv_mismatch"
    assert _refusal(work_for(mac, params={"read_type": "nano-hq", "threads": 999}), mac) == "settings_rejected"
    assert _refusal(work_for(mac, tool="bakta"), mac) == "not_flye_work"
    assert _refusal(work_for(mac, stderr_log="../x.log"), mac) == "unsafe_path"
    work = work_for(mac)
    del work["argv"]
    assert _refusal(work, mac) == "work_incomplete"
    (Path(mac["exe"]).parent / "flye-samtools").unlink()
    assert _refusal(work_for(mac), mac) == "samtools_missing"


def test_an_existing_out_dir_link_that_leads_outside_is_refused(mac, tmp_path):
    # A resumed run's work folder exists already: a link in its place must not lead Flye's writes outside.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (mac["results"] / "flye").symlink_to(elsewhere)
    assert _refusal_keeping_out_dir(work_for(mac, resume=True), mac) == "outside_data_dir"


def _refusal_keeping_out_dir(work, mac):
    report = run_native(work, mac["data"], mac["exe"])
    assert report["outcome"] == "refused" and report["argv"] is None
    return report["code"]


def test_a_stop_while_the_checks_run_reports_not_started(mac, monkeypatch):
    def stopped(*_args, **_kwargs):
        raise flye_module.NativeStopped()

    monkeypatch.setattr(flye_module, "prepare_native", stopped)
    report = run_native(work_for(mac), mac["data"], mac["exe"])
    assert (report["outcome"], report["code"], report["argv"]) == ("not_started", "stopped_by_app", None)


def test_a_data_folder_with_spaces_is_refused(mac):
    with pytest.raises(NativeRefusal) as exc:
        prepare_native(work_for(mac), "/Volumes/My Disk/ARVA/data", mac["exe"])
    assert exc.value.code == "path_has_spaces"


def test_facts_report_the_installed_build_and_lock(mac, tmp_path):
    lock = ROOT / NATIVE_LOCK["lock"]
    facts = native_facts(mac["exe"], str(lock))
    assert facts["version"] == "2.9.6-b1802"
    assert facts["package"]["build"] == NATIVE_LOCK["build"] and facts["package"]["sha256"] == NATIVE_LOCK["package_sha256"]
    assert facts["lock_sha256"] == NATIVE_LOCK["lock_sha256"]
    assert facts["samtools_helper"] is True and "--nano-hq" in facts["help_options"] and "--resume" in facts["help_options"]


def test_the_native_lock_constants_match_the_checked_in_lock():
    lock = ROOT / NATIVE_LOCK["lock"]
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == NATIVE_LOCK["lock_sha256"]
    line = (f"https://conda.anaconda.org/bioconda/osx-arm64/{NATIVE_LOCK['package']}"
            f"#sha256:{NATIVE_LOCK['package_sha256']}")
    assert line in lock.read_text().splitlines()
    assert NATIVE_LOCK["package"] == f"flye-{NATIVE_LOCK['version']}-{NATIVE_LOCK['build']}.conda"


def test_the_entry_imports_with_the_standard_library_only(tmp_path):
    """Run as ARVA.app runs it (python -I <bundle>/arva_tools/native.py): the registry and arva_core stay unloaded."""
    code = (f"import runpy, sys; sys.argv = [{str(NATIVE)!r}, 'flye', '--help']\n"
            f"try:\n    runpy.run_path({str(NATIVE)!r}, run_name='__main__')\nexcept SystemExit:\n    pass\n"
            "print(sorted(m for m in sys.modules if m.startswith(('arva_core', 'arva_tools'))))")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True, cwd=tmp_path)
    loaded = out.stdout.strip().splitlines()[-1]
    assert "arva_tools.flye" in loaded and "arva_core" not in loaded and "registry" not in loaded


def test_the_entry_runs_checks_and_stops_on_sigterm(mac, tmp_path):
    work_file = tmp_path / "work.json"
    work_file.write_text(json.dumps(work_for(mac, tool="bakta")))
    proc = subprocess.run([sys.executable, "-I", str(NATIVE), "flye", "run", "--work", str(work_file), "--data-dir",
                           mac["data"], "--executable", mac["exe"]], capture_output=True, text=True)
    assert proc.returncode == 3 and json.loads(proc.stdout)["code"] == "not_flye_work"

    target = Path(mac["data"]) / "raw" / "reads.fastq.gz"
    sleepy = mac["results"] / "input" / "01_SLEEP.fastq.gz"
    sleepy.symlink_to(os.path.relpath(target, sleepy.parent))
    work = work_for(mac)
    work["reads"] = [f"{SCOPE}/input/01_SLEEP.fastq.gz"]
    work["argv"] = native_expected_argv(FlyeParams.from_dict(work["params"]), mac["data"], mac["exe"], work["reads"],
                                        work["out_dir"], FlyeAdapter.help_options(mac["exe"]), False)
    work_file.write_text(json.dumps(work))
    argv_out = subprocess.run([sys.executable, "-I", str(NATIVE), "flye", "argv", "--work", str(work_file),
                               "--data-dir", mac["data"], "--executable", mac["exe"]], capture_output=True, text=True,
                              check=True)
    assert json.loads(argv_out.stdout)["argv"] == work["argv"]
    runner = subprocess.Popen([sys.executable, "-I", str(NATIVE), "flye", "run", "--work", str(work_file),
                               "--data-dir", mac["data"], "--executable", mac["exe"]], stdout=subprocess.PIPE, text=True)
    pid_file = mac["results"] / "flye.pid"
    deadline = time.monotonic() + 20
    while not pid_file.is_file() and time.monotonic() < deadline:
        time.sleep(0.1)
    flye_pid = int(pid_file.read_text())
    runner.send_signal(signal.SIGTERM)
    out, _ = runner.communicate(timeout=20)
    report = json.loads(out)
    assert (report["outcome"], report["code"], report["exit_code"]) == ("stopped", "stopped_by_app", None)
    with pytest.raises(ProcessLookupError):
        for _ in range(50):
            os.kill(flye_pid, 0)
            time.sleep(0.1)
