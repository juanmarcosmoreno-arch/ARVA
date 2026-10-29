"""scripts/start.sh with fake sysctl, system_profiler, sw_vers, uname and docker executables on PATH.

All outputs below are CONSTRUCTED from the formats documented in the sources cited in scripts/start.sh and
app/services/host.py (Apple's sysctl keys, sw_vers(1), system_profiler's JSON keys as parsed by mondoohq/cnquery,
Docker's NCPU and MemTotal); none is copied from a real Mac, and the script has not run on one.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "start.sh"
GIB = 1024**3
SHELLS = [s for s in ("dash", "bash") if shutil.which(s)]

FAKES = {
    "uname": 'case "$1" in -s) printf "%s\\n" "${FAKE_UNAME_S:-Darwin}" ;; -m) printf "%s\\n" "${FAKE_UNAME_M:-arm64}" ;; esac',
    "sysctl": '[ "$1" = -n ] || exit 2\n'
              'if [ -f "$FAKE/sysctl/$2" ]; then cat "$FAKE/sysctl/$2"; else echo "sysctl: unknown oid \'$2\'" >&2; exit 1; fi',
    "system_profiler": '[ "$1 $2" = "-json SPHardwareDataType" ] || exit 2\n'
                       '[ -f "$FAKE/system_profiler.json" ] && cat "$FAKE/system_profiler.json" || exit 1',
    "sw_vers": '[ "$1" = -productVersion ] && [ -f "$FAKE/sw_vers" ] && cat "$FAKE/sw_vers" || exit 1',
    "docker": 'case "$1 $2" in\n'
              '  "info --format") [ -f "$FAKE/docker_info" ] && cat "$FAKE/docker_info" || exit 1 ;;\n'
              '  "compose up") env | grep "^ARVA_HOST_" | sort > "$FAKE/compose_env"; echo "$*" > "$FAKE/compose_args" ;;\n'
              '  "compose exec") echo "PROFILE REPORT: $*" ;;\n'
              '  *) exit 2 ;;\n'
              'esac',
}


def mac(tmp_path: Path, sysctl: dict[str, str], profiler: dict | None, version: str | None = "14.5",
        docker: str | None = f"8 {8 * GIB}", spaced: bool = True) -> Path:
    fake = tmp_path / "fake"
    (fake / "sysctl").mkdir(parents=True)
    for key, value in sysctl.items():
        (fake / "sysctl" / key).write_text(value + "\n")
    if profiler is not None:
        text = json.dumps({"SPHardwareDataType": [profiler]}, indent=2)
        if spaced:  # the key-space-colon layout is tolerated as well
            text = text.replace('": ', '" : ')
        # A log line before the JSON, as macOS 26.3.1 and 26.4 print (Apple developer forums, thread 820473).
        (fake / "system_profiler.json").write_text("2026-03-25 11:28:17.939 system_profiler[1:2] note\n" + text)
    if version is not None:
        (fake / "sw_vers").write_text(version + "\n")
    if docker is not None:
        (fake / "docker_info").write_text(docker + "\n")
    return fake


def run(tmp_path: Path, fake: Path, shell: str, uname: str = "Darwin", lang: str = "en_US.UTF-8", *args: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE": str(fake), "FAKE_UNAME_S": uname, "LANG": lang}
    proc = subprocess.run([shell, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)
    compose = fake / "compose_env"
    exported = dict(line.split("=", 1) for line in compose.read_text().splitlines()) if compose.exists() else None
    return proc, exported


APPLE_SILICON = {"hw.model": "Mac14,2", "machdep.cpu.brand_string": "Apple M2", "hw.nperflevels": "2",
                 "hw.perflevel0.physicalcpu": "4", "hw.perflevel1.physicalcpu": "4", "hw.physicalcpu": "8",
                 "hw.logicalcpu": "8", "hw.memsize": str(16 * GIB), "sysctl.proc_translated": "0"}
AIR = {"_name": "hardware_overview", "machine_name": "MacBook Air", "machine_model": "Mac14,2", "chip_type": "Apple M2",
       "number_processors": "proc 8:4:4", "physical_memory": "16 GB", "serial_number": "SERIAL-NEVER-PASSED"}


@pytest.mark.parametrize("shell", SHELLS)
def test_apple_silicon(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, APPLE_SILICON, AIR), shell)
    assert proc.returncode == 0, proc.stderr
    assert env == {
        "ARVA_HOST_ARCH": "arm64", "ARVA_HOST_CHIP": "Apple M2", "ARVA_HOST_DOCKER_CPUS": "8",
        "ARVA_HOST_DOCKER_MEMORY_BYTES": str(8 * GIB), "ARVA_HOST_EFF_CORES": "4", "ARVA_HOST_LOGICAL_CPUS": "8",
        "ARVA_HOST_MEMORY_BYTES": str(16 * GIB), "ARVA_HOST_MODEL_ID": "Mac14,2", "ARVA_HOST_MODEL_NAME": "MacBook Air",
        "ARVA_HOST_OS_VERSION": "14.5", "ARVA_HOST_PERF_CORES": "4", "ARVA_HOST_PHYSICAL_CORES": "8",
        "ARVA_HOST_PLATFORM": "macos"}
    out = proc.stdout
    assert "MacBook Air (Mac14,2) · Apple M2 · 4 performance + 4 efficiency cores · 16.0 GB · macOS 14.5" in out
    assert "Docker Desktop gives its virtual machine 8 CPUs and 8.0 GB" in out
    assert "PROFILE REPORT: compose exec -T api python -m app.services.performance --lang en" in out
    assert "SERIAL-NEVER-PASSED" not in out + json.dumps(env)
    assert (tmp_path / "fake" / "compose_args").read_text().strip() == "compose up -d"


@pytest.mark.parametrize("shell", SHELLS)
def test_older_macos_on_apple_silicon_reads_cores_from_system_profiler(tmp_path, shell):
    sysctl = {k: v for k, v in APPLE_SILICON.items() if "perflevel" not in k}
    proc, env = run(tmp_path, mac(tmp_path, sysctl, {**AIR, "number_processors": "proc 10:8:2"}, "11.7.10",
                                  spaced=False), shell, "Darwin", "es_ES.UTF-8", "--build")
    assert proc.returncode == 0, proc.stderr
    assert (env["ARVA_HOST_PERF_CORES"], env["ARVA_HOST_EFF_CORES"], env["ARVA_HOST_OS_VERSION"]) == ("8", "2", "11.7.10")
    assert "Esta Mac" in proc.stdout and "8 núcleos de rendimiento + 2 de eficiencia" in proc.stdout
    assert "--lang es" in proc.stdout
    assert (tmp_path / "fake" / "compose_args").read_text().strip() == "compose up -d --build"


@pytest.mark.parametrize("shell", SHELLS)
def test_intel_mac(tmp_path, shell):
    sysctl = {"hw.model": "MacBookPro16,1", "machdep.cpu.brand_string": "Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz",
              "hw.physicalcpu": "6", "hw.logicalcpu": "12", "hw.memsize": str(16 * GIB)}
    proc, env = run(tmp_path, mac(tmp_path, sysctl, {"machine_name": "MacBook Pro", "number_processors": 6,
                                                     "cpu_type": "6-Core Intel Core i7"}), shell)
    assert proc.returncode == 0, proc.stderr
    assert (env["ARVA_HOST_PERF_CORES"], env["ARVA_HOST_EFF_CORES"], env["ARVA_HOST_PHYSICAL_CORES"]) == ("", "", "6")
    assert env["ARVA_HOST_CHIP"] == "Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz"
    assert "MacBook Pro (MacBookPro16,1) · Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz · 6 cores" in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_keys_leave_facts_empty(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, {"hw.nperflevels": "2", "hw.perflevel0.physicalcpu": "x"}, None, None,
                                  docker="? ?"), shell)
    assert proc.returncode == 0, proc.stderr
    assert env["ARVA_HOST_PLATFORM"] == "macos"
    assert all(v == "" for k, v in env.items() if k != "ARVA_HOST_PLATFORM" and k != "ARVA_HOST_ARCH")
    assert "? · ? · ? cores · ? · macOS ?" in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_control_characters_are_dropped(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, {**APPLE_SILICON, "hw.model": "Mac14,2\x1b[2J$(touch x)"},
                                  {**AIR, "machine_name": "MacBook\\u001b Air"}), shell)
    assert proc.returncode == 0, proc.stderr
    assert env["ARVA_HOST_MODEL_ID"] == "Mac14,2[2J$(touch x)" and not (tmp_path / "x").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_docker_not_running(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, APPLE_SILICON, AIR, docker=None), shell)
    assert proc.returncode == 1 and env is None
    assert "Docker is not running" in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_linux_only_starts_compose(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, APPLE_SILICON, AIR), shell, "Linux")
    assert proc.returncode == 0, proc.stderr
    assert env == {} and "This Mac" not in proc.stdout and "PROFILE REPORT" in proc.stdout


def test_shellcheck_clean():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    proc = subprocess.run(["shellcheck", "-s", "sh", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
