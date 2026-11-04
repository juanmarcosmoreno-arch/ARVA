"""scripts/start.sh with fake sysctl, system_profiler, sw_vers, uname and docker executables on PATH.

All outputs below are CONSTRUCTED from the formats documented in the sources cited in scripts/start.sh and
app/services/host.py (Apple's sysctl keys, sw_vers(1), system_profiler's JSON keys as parsed by mondoohq/cnquery,
Docker's NCPU and MemTotal); none is copied from a real Mac, and the script has not run on one.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "start.sh"
VERSION = re.search(r'__version__ = "([^"]+)"', (SCRIPT.parents[1] / "apps/api/app/__init__.py").read_text()).group(1)
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
              '  "compose up") env | grep "^ARVA_HOST_" | sort > "$FAKE/compose_env"; echo "$*" > "$FAKE/compose_args"\n'
              '    env | grep -E "^ARVA_(PLATFORM|API_IMAGE|WEB_IMAGE|IMAGE_TAG)=" | sort > "$FAKE/compose_images" ;;\n'
              '  "compose pull") echo "$*" > "$FAKE/compose_pull"; [ -z "${FAKE_PULL_FAIL:-}" ] ;;\n'
              '  "image inspect") [ -n "${FAKE_IMAGES_HERE:-}" ] ;;\n'
              '  "image ls") [ -z "${FAKE_OLDER_TAG:-}" ] || printf "%s\\n" "$FAKE_OLDER_TAG" ;;\n'
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


def run(tmp_path: Path, fake: Path, shell: str, uname: str = "Darwin", lang: str = "en_US.UTF-8", *args: str,
        extra: dict[str, str] | None = None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in FAKES.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE": str(fake), "FAKE_UNAME_S": uname, "LANG": lang, **(extra or {})}
    proc = subprocess.run([shell, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)
    compose = fake / "compose_env"
    exported = dict(line.split("=", 1) for line in compose.read_text().splitlines()) if compose.exists() else None
    return proc, exported


# The storage facts every start passes on (the import/ folder next to docker-compose.yml, and the folder of the file
# with the measured free space); test_storage_launcher.py checks them.
STORAGE = ("ARVA_HOST_IMPORT_", "ARVA_HOST_FACTS_DIR")


def without_storage(env: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if not k.startswith(STORAGE)}


APPLE_SILICON = {"hw.model": "Mac14,2", "machdep.cpu.brand_string": "Apple M2", "hw.nperflevels": "2",
                 "hw.perflevel0.physicalcpu": "4", "hw.perflevel1.physicalcpu": "4", "hw.physicalcpu": "8",
                 "hw.logicalcpu": "8", "hw.memsize": str(16 * GIB), "sysctl.proc_translated": "0"}
AIR = {"_name": "hardware_overview", "machine_name": "MacBook Air", "machine_model": "Mac14,2", "chip_type": "Apple M2",
       "number_processors": "proc 8:4:4", "physical_memory": "16 GB", "serial_number": "SERIAL-NEVER-PASSED"}


@pytest.mark.parametrize("shell", SHELLS)
def test_apple_silicon(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, APPLE_SILICON, AIR), shell)
    assert proc.returncode == 0, proc.stderr
    assert env["ARVA_HOST_IMPORT_DIR"] == str((SCRIPT.parents[1] / "import").resolve())
    assert without_storage(env) == {
        "ARVA_HOST_ARCH": "arm64", "ARVA_HOST_CHIP": "Apple M2", "ARVA_HOST_DOCKER_CPUS": "8",
        "ARVA_HOST_DOCKER_MEMORY_BYTES": str(8 * GIB), "ARVA_HOST_EFF_CORES": "4", "ARVA_HOST_LOGICAL_CPUS": "8",
        "ARVA_HOST_MEMORY_BYTES": str(16 * GIB), "ARVA_HOST_MODEL_ID": "Mac14,2", "ARVA_HOST_MODEL_NAME": "MacBook Air",
        "ARVA_HOST_OS_VERSION": "14.5", "ARVA_HOST_PERF_CORES": "4", "ARVA_HOST_PHYSICAL_CORES": "8",
        "ARVA_HOST_PLATFORM": "macos", "ARVA_HOST_IMAGE_PLATFORM": "linux/amd64",
        "ARVA_HOST_IMAGE_REASON": "rosetta_unknown", "ARVA_HOST_DOCKER_ROSETTA": "unknown",
        "ARVA_HOST_IMAGE_SOURCE": "published"}
    out = proc.stdout
    assert "MacBook Air (Mac14,2) · Apple M2 · 4 performance + 4 efficiency cores · 16.0 GB · macOS 14.5" in out
    assert "Docker Desktop gives its virtual machine 8 CPUs and 8.0 GB" in out
    assert "PROFILE REPORT: compose exec -T api python -m app.services.performance --lang en" in out
    assert "SERIAL-NEVER-PASSED" not in out + json.dumps(env)
    assert (tmp_path / "fake" / "compose_args").read_text().strip() == "compose up -d"
    assert (tmp_path / "fake" / "compose_pull").read_text().strip() == "compose pull api web"
    assert images(tmp_path) == {"ARVA_API_IMAGE": "ghcr.io/juanmarcosmoreno-arch/arva-api", "ARVA_IMAGE_TAG": VERSION,
                                "ARVA_PLATFORM": "linux/amd64", "ARVA_WEB_IMAGE": "ghcr.io/juanmarcosmoreno-arch/arva-web"}
    assert "Image architecture: linux/amd64" in out
    assert "No Docker Desktop settings file was found to read the Rosetta setting from" in out
    assert "could not be read" not in out


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
    assert not (tmp_path / "fake" / "compose_pull").exists()
    assert images(tmp_path)["ARVA_API_IMAGE"] == "arva-api" and env["ARVA_HOST_IMAGE_SOURCE"] == "local"
    assert "Arquitectura de las imágenes: linux/amd64" in proc.stdout


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
    assert all(v == "" for k, v in without_storage(env).items() if k not in ("ARVA_HOST_PLATFORM", "ARVA_HOST_ARCH")
               and not k.startswith(("ARVA_HOST_IMAGE", "ARVA_HOST_DOCKER_ROSETTA")))
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
    assert without_storage(env) == {"ARVA_HOST_IMAGE_PLATFORM": "linux/arm64", "ARVA_HOST_IMAGE_REASON": "native",
                   "ARVA_HOST_DOCKER_ROSETTA": "", "ARVA_HOST_IMAGE_SOURCE": "published"}
    assert "This Mac" not in proc.stdout and "PROFILE REPORT" in proc.stdout


def images(tmp_path: Path) -> dict[str, str]:
    text = (tmp_path / "fake" / "compose_images").read_text()
    return dict(line.split("=", 1) for line in text.splitlines())


def docker_settings(tmp_path: Path, name: str, text: str) -> dict[str, str]:
    folder = tmp_path / "home" / "Library" / "Group Containers" / "group.com.docker"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text)
    return {"HOME": str(tmp_path / "home")}


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(("name", "text", "platform", "reason", "rosetta"), [
    ("settings-store.json", '{\n  "AutoStart": false,\n  "UseVirtualizationFrameworkRosetta": false\n}', "linux/arm64",
     "rosetta_off", "off"),
    ("settings.json", '{"useVirtualizationFramework": true, "useVirtualizationFrameworkRosetta" : true}', "linux/amd64",
     "rosetta_on", "on"),
    # Only settings changed from Docker Desktop's defaults are stored (seen on a real Mac): no key is its default.
    ("settings-store.json", '{"AutoStart": true, "UseVirtualizationFramework": true}', "linux/amd64",
     "rosetta_default", "default"),
    ("settings-store.json", '{"UseVirtualizationFrameworkRosetta": "maybe"}', "linux/amd64", "rosetta_unknown",
     "unknown"),
])
def test_apple_silicon_image_follows_docker_desktops_rosetta_setting(tmp_path, shell, name, text, platform, reason,
                                                                      rosetta):
    proc, env = run(tmp_path, mac(tmp_path, APPLE_SILICON, AIR), shell,
                    extra=docker_settings(tmp_path, name, text))
    assert proc.returncode == 0, proc.stderr
    assert (env["ARVA_HOST_IMAGE_PLATFORM"], env["ARVA_HOST_IMAGE_REASON"], env["ARVA_HOST_DOCKER_ROSETTA"]) == (
        platform, reason, rosetta)
    assert images(tmp_path)["ARVA_PLATFORM"] == platform
    if reason == "rosetta_off":
        assert "Rosetta off in Docker Desktop: the native arm64 image" in proc.stdout
    if reason == "rosetta_default":
        assert "does not store the Rosetta setting" in proc.stdout and "Nothing failed" in proc.stdout
        assert "could not be read" not in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_intel_mac_uses_the_amd64_image(tmp_path, shell):
    sysctl = {"hw.model": "MacBookPro16,1", "hw.physicalcpu": "6", "hw.logicalcpu": "12", "hw.memsize": str(16 * GIB)}
    proc, env = run(tmp_path, mac(tmp_path, sysctl, None), shell, extra={"FAKE_UNAME_M": "x86_64"})
    assert proc.returncode == 0, proc.stderr
    assert (env["ARVA_HOST_IMAGE_PLATFORM"], env["ARVA_HOST_IMAGE_REASON"]) == ("linux/amd64", "native")


@pytest.mark.parametrize("shell", SHELLS)
def test_platform_choice_is_saved_until_auto(tmp_path, shell):
    home = docker_settings(tmp_path, "settings-store.json", '{"UseVirtualizationFrameworkRosetta": true}')
    fake = mac(tmp_path, APPLE_SILICON, AIR)
    proc, env = run(tmp_path, fake, shell, "Darwin", "en_US.UTF-8", "--platform", "linux/arm64", extra=home)
    assert proc.returncode == 0, proc.stderr
    config = tmp_path / "home" / ".config" / "arva" / "arva.conf"
    assert "ARVA_PLATFORM=linux/arm64" in config.read_text().splitlines()
    proc, env = run(tmp_path, fake, shell, extra=home)
    assert (env["ARVA_HOST_IMAGE_PLATFORM"], env["ARVA_HOST_IMAGE_REASON"]) == ("linux/arm64", "chosen")
    assert "chosen with --platform" in proc.stdout
    proc, env = run(tmp_path, fake, shell, "Darwin", "en_US.UTF-8", "--platform=auto", extra=home)
    assert (env["ARVA_HOST_IMAGE_PLATFORM"], env["ARVA_HOST_IMAGE_REASON"]) == ("linux/amd64", "rosetta_on")
    assert "ARVA_PLATFORM" not in config.read_text()


@pytest.mark.parametrize("shell", SHELLS)
def test_an_unknown_platform_is_refused(tmp_path, shell):
    proc, env = run(tmp_path, mac(tmp_path, APPLE_SILICON, AIR), shell, "Darwin", "en_US.UTF-8", "--platform", "x86")
    assert proc.returncode == 2 and env is None and "--platform must be" in proc.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_a_failed_pull_explains_docker_login_unless_the_images_are_here(tmp_path, shell):
    fake = mac(tmp_path, APPLE_SILICON, AIR)
    proc, env = run(tmp_path, fake, shell, extra={"FAKE_PULL_FAIL": "1"})
    assert proc.returncode == 1 and env is None
    assert "docker login ghcr.io -u <your GitHub user name>" in proc.stderr and "read:packages" in proc.stderr
    proc, env = run(tmp_path, fake, shell, extra={"FAKE_PULL_FAIL": "1", "FAKE_IMAGES_HERE": "1"})
    assert proc.returncode == 0 and "copies already on this computer" in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_the_first_download_of_a_version_says_how_big_it_is_and_that_it_can_take_long(tmp_path, shell):
    fake = mac(tmp_path, APPLE_SILICON, AIR)
    # The images of this version are not here yet (`docker image inspect` fails): the measured size, before the pull.
    proc, _ = run(tmp_path, fake, shell)
    assert proc.returncode == 0, proc.stderr
    out = " ".join(proc.stdout.split())
    assert f"Downloading ARVA {VERSION} (this version is not on this computer yet)" in out
    assert "for the first time" not in out
    assert "about 16 GB (linux/amd64; the download itself is compressed, so smaller)" in out
    assert "can take more than an hour (one test on a Mac took 1.5 h at about 0.8 MB/s)" in out
    assert "An earlier ARVA version" not in out
    # The native arm64 image is smaller; and the same text in Spanish.
    (tmp_path / "home").mkdir()
    proc, _ = run(tmp_path, fake, shell, "Darwin", "es_AR.UTF-8", "--platform", "linux/arm64",
                  extra={"HOME": str(tmp_path / "home")})
    assert proc.returncode == 0, proc.stderr
    out = " ".join(proc.stdout.split())
    assert f"Se descarga ARVA {VERSION} (esta versión todavía no está en esta computadora)" in out
    assert "unos 10 GB (linux/arm64; la descarga en sí está comprimida, así que es menor)" in out
    assert "puede tardar más de una hora" in out
    # An update: an earlier version's API image is here (only `docker image ls`, local), so the download may be smaller.
    for lang, text in (("en_US.UTF-8", "An earlier ARVA version is on this computer: Docker reuses the parts it already "
                                       "has, so the download may be much smaller."),
                       ("es_AR.UTF-8", "Hay una versión anterior de ARVA en esta computadora: Docker reutiliza las "
                                       "partes que ya tiene, así que la descarga puede ser mucho menor.")):
        proc, _ = run(tmp_path, fake, shell, "Darwin", lang, extra={"FAKE_OLDER_TAG": "0.9.0"})
        assert proc.returncode == 0, proc.stderr
        assert text in " ".join(proc.stdout.split())
    # An untagged leftover (<none>) is no earlier version.
    proc, _ = run(tmp_path, fake, shell, extra={"FAKE_OLDER_TAG": "<none>"})
    assert "An earlier ARVA version" not in proc.stdout
    # Not when the images are already here, nor when they are built here or are not ARVA's published ones.
    for extra, args in (({"FAKE_IMAGES_HERE": "1"}, ()), ({}, ("--build",)),
                        ({"ARVA_API_IMAGE": "registry.example/other-api"}, ())):
        proc, _ = run(tmp_path, fake, shell, "Darwin", "en_US.UTF-8", *args, extra=extra)
        assert proc.returncode == 0, proc.stderr
        assert "this version is not on this computer yet" not in proc.stdout


def test_shellcheck_clean():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    proc = subprocess.run(["shellcheck", "-x", "-s", "sh", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
