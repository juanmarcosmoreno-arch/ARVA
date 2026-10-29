"""scripts/diagnostics.sh with fake docker and curl executables, and the launcher's own error log entry
(scripts/start.sh). The fake outputs are CONSTRUCTED; neither script has run on a real Mac."""
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_storage_launcher import SHELLS, Mac

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "diagnostics.sh"
START = ROOT / "scripts" / "start.sh"
LEAKS = ("hunter2", "supersecret", "jmoreno", "jm@example.org", "C02XG2JHJG5J", "ACGTACGTTTGACCAGTAGGACCATTAGG")

DOCKER = f"""#!{sys.executable}
import os, sys
args = sys.argv[1:]
if os.environ.get("FAKE_DOCKER_DOWN") and args[:3] != ["compose", "version", "--short"] and \
        args[:3] != ["version", "--format", "{{{{.Client.Version}}}}"]:
    print("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", file=sys.stderr)
    sys.exit(1)
if args[:2] == ["version", "--format"]:
    print("27.3.1")
elif args[:3] == ["compose", "version", "--short"]:
    print("2.29.7")
elif args[:2] == ["info", "--format"]:
    print("8 CPUs, 8589934592 bytes of memory")
elif args[0] == "compose" and "ps" in args:
    print("NAME          SERVICE   STATUS")
    print("arva-api-1    api       Up 2 minutes (unhealthy)")
    print("arva-worker-1 worker    Restarting (1) 5 seconds ago")
elif args[0] == "compose" and "logs" in args:
    service = args[-1]
    for n in range(1, 101):
        print(f"{{service}} line {{n}}")
    print(f"{{service}}: connect postgresql+psycopg://arva:hunter2@postgres:5432/arva failed; ARVA_DB_PASSWORD=supersecret")
    print(f"{{service}}: /Users/jmoreno/ARVA/data owner jm@example.org Serial Number (system): C02XG2JHJG5J")
    print(f"{{service}}: read ACGTACGTTTGACCAGTAGGACCATTAGG")
elif args[0] == "compose" and "up" in args:
    sys.exit(int(os.environ.get("FAKE_UP_STATUS", "0")))
else:
    sys.exit(1)
"""

CURL = """#!/bin/sh
if [ -n "${FAKE_DOCKER_DOWN:-}" ]; then echo "curl: (7) Failed to connect to 127.0.0.1 port 8000" >&2; exit 7; fi
case "$*" in
  *http_code*) printf '200' ;;
  *) printf '{"status":"degraded","version":"0.2.0","storage":"missing"}' ;;
esac
"""


def _machine(tmp_path: Path) -> Mac:
    m = Mac(tmp_path, os_name="Linux")
    for name, body in (("docker", DOCKER), ("curl", CURL)):
        (m.bin / name).write_text(body)
        (m.bin / name).chmod(0o755)
    return m


def _config(m: Mac, data: Path) -> None:
    m.config.parent.mkdir(parents=True, exist_ok=True)
    m.config.write_text(f"# test\nARVA_DATA_DIR={data}\nARVA_DATA_DIR_MOUNT={m.disk}\n")
    m.config.chmod(0o600)


def _run(m: Mac, shell: str, *args: str, env: dict | None = None):
    base = {"PATH": f"{m.bin}:/usr/bin:/bin", "FAKE": str(m.fake), "HOME": str(m.home), "LANG": "en_US.UTF-8",
            "ARVA_DB_PASSWORD": "supersecret", "GITHUB_TOKEN": "hunter2"}
    return subprocess.run([shell, str(SCRIPT), *args], env={**base, **(env or {})}, capture_output=True, text=True,
                          timeout=60)


@pytest.mark.parametrize("shell", SHELLS)
def test_the_report_covers_docker_health_folders_errors_and_logs_without_secrets(tmp_path, shell):
    m = _machine(tmp_path)
    data = m.folder("ARVA", "data")
    (data / ".arva-storage").write_text('{"id": "x"}')
    (data / "logs").mkdir()
    (data / "logs" / "errors.jsonl").write_text("".join(
        json.dumps({"id": f"AAAA-{n:04d}", "message": f"entry {n}"}) + "\n" for n in range(30)))
    _config(m, data)
    out_file = tmp_path / "report.md"
    proc = _run(m, shell, "--lines", "5", "--output", str(out_file))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for heading in ("# ARVA diagnostics", "## Saved locations", "## Docker", "## Health", "## Recent errors",
                    "## Log of api (last 5 lines)", "## Log of backup (last 5 lines)"):
        assert heading in out
    assert f"Data folder: {data} — there, readable and writable" in out
    assert "storage marker (.arva-storage): present; logs folder: present" in out
    assert "docker: client 27.3.1, server 27.3.1" in out and "docker compose: 2.29.7" in out
    assert "arva-worker-1 worker    Restarting" in out and '"storage":"missing"' in out and "HTTP 200" in out
    assert "AAAA-0029" in out and "AAAA-0009" not in out
    assert "api line 99\n" in out and "api line 98\n" not in out
    assert "postgresql+psycopg://***@postgres:5432/arva" in out and "~/ARVA/data" in out and "<email>" in out
    for leak in LEAKS:
        assert leak not in out, leak
    assert out_file.read_text() == out and stat.S_IMODE(out_file.stat().st_mode) == 0o600


@pytest.mark.parametrize("shell", SHELLS)
def test_without_docker_running_or_saved_locations_it_still_reports(tmp_path, shell):
    m = _machine(tmp_path)
    proc = _run(m, shell, env={"FAKE_DOCKER_DOWN": "1"})
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "server not reachable (is Docker Desktop running?)" in out and "Cannot connect to the Docker daemon" in out
    assert "not created: Docker volumes are used" in out and "No error log could be read" in out
    assert "Failed to connect to 127.0.0.1 port 8000" in out
    assert _run(m, shell, "--lines", "0").returncode == 2


def test_a_compose_failure_is_kept_in_the_data_folders_error_log(tmp_path):
    m = _machine(tmp_path)
    data = m.folder("ARVA", "data")
    (data / ".arva-storage").write_text('{"id": "x"}')
    (data / "logs").mkdir()
    env = {"PATH": f"{m.bin}:/usr/bin:/bin", "FAKE": str(m.fake), "HOME": str(m.home), "LANG": "en_US.UTF-8",
           "FAKE_UP_STATUS": "17"}
    proc = subprocess.run(["sh", str(START), "--data-dir", str(data)], env=env, capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 17 and "scripts/diagnostics.sh" in proc.stdout + proc.stderr
    entry = json.loads((data / "logs" / "errors.jsonl").read_text())
    assert entry["component"] == "launcher" and entry["code"] == "launcher_compose_failed"
    assert entry["params"] == {"status": 17} and len(entry["id"]) == 9 and entry["id"][4] == "-"


def test_shellcheck_clean():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    proc = subprocess.run(["shellcheck", "-x", "-s", "sh", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
