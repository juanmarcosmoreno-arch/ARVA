"""scripts/start.sh's first-run questions (scripts/lib/arva-firstrun.sh), answered on standard input, with the fake
uname, df, diskutil and docker of test_storage_launcher.py plus fake open, arch, sysctl and curl.

As there, every fake output is CONSTRUCTED from documented formats; the Docker Desktop settings keys
(UseVirtualizationFrameworkRosetta, filesharingDirectories) are matched without regard to case because their spelling
in the file is not documented. Nothing here ran on a real Mac.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_storage_launcher import ROOT, SHELLS, START, Mac

# Wraps the Python fake docker: `docker info` fails while $FAKE/docker_down exists, a pull fails until `docker login`
# has run (with $FAKE/pull_denied), and `docker image inspect` finds nothing.
DOCKER_WRAPPER = """#!/bin/sh
echo "$*" >> "$FAKE/docker.args"
case "$1" in
  info) [ ! -e "$FAKE/docker_down" ] || exit 1 ;;
  login) touch "$FAKE/logged_in"; exit 0 ;;
  image) exit 1 ;;
esac
case " $* " in
  *" pull "*) if [ -e "$FAKE/pull_denied" ] && [ ! -e "$FAKE/logged_in" ]; then exit 1; fi ;;
esac
exec "$FAKE/docker.py" "$@"
"""

OTHERS = {
    "open": '#!/bin/sh\necho "$*" >> "$FAKE/open.log"\n[ "$1 $2" != "-a Docker" ] || rm -f "$FAKE/docker_down"\n',
    "arch": '#!/bin/sh\n[ -z "${FAKE_NO_ROSETTA:-}" ]\n',
    "sysctl": '#!/bin/sh\n[ "$2" = sysctl.proc_translated ] && echo 0 || exit 1\n',
    "curl": "#!/bin/sh\nexit 0\n",
}


class FirstRun(Mac):
    def __init__(self, tmp: Path, docker: bool = True):
        super().__init__(tmp)
        (self.bin / "docker").rename(self.fake / "docker.py")
        if docker:
            (self.bin / "docker").write_text(DOCKER_WRAPPER)
            (self.bin / "docker").chmod(0o755)
        for name, body in OTHERS.items():
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.startup = tmp / "Volumes" / "Macintosh HD"
        self.startup.mkdir()
        # A PATH without the real docker of this test machine, for "Docker Desktop is not installed".
        self.usr = tmp / "usr-bin"
        self.usr.mkdir()
        for entry in Path("/usr/bin").iterdir():
            if entry.name != "docker" and not (self.bin / entry.name).exists():
                (self.usr / entry.name).symlink_to(entry)

    def settings(self, text: str):
        folder = self.home / "Library" / "Group Containers" / "group.com.docker"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings-store.json").write_text(text)

    def ask(self, shell: str, answers: list[str], *args: str, lang: str = "es_AR.UTF-8", **extra: str):
        for f in ("docker.log", "compose_env.json", "docker.args", "open.log"):
            (self.fake / f).unlink(missing_ok=True)
        env = {"PATH": f"{self.bin}:{self.usr}", "FAKE": str(self.fake), "HOME": str(self.home), "LANG": lang,
               "ARVA_VOLUMES_ROOT": str(self.tmp / "Volumes"), "ARVA_DOCKER_WAIT": "4", **extra}
        return subprocess.run([shell, str(START), *args], env=env, input="".join(a + "\n" for a in answers),
                              capture_output=True, text=True, timeout=60)

    def log(self, name: str) -> list[str]:
        f = self.fake / name
        return f.read_text().splitlines() if f.exists() else []


@pytest.mark.parametrize("shell", SHELLS)
def test_spanish_first_run_proposes_the_external_disk_and_adds_existing_databases(tmp_path, shell):
    m = FirstRun(tmp_path)
    (tmp_path / "Volumes" / "USB").mkdir()
    m.mount(tmp_path / "Volumes" / "USB", "exfat", "ExFAT")
    m.settings('{\n  "UseVirtualizationFrameworkRosetta": true,\n  "FilesharingDirectories": [\n    "/Users"\n  ]\n}')
    bioinf = m.folder("Bio Inf")
    typed = str(bioinf).replace(" ", "\\ ") + " "
    proc = m.ask(shell, ["abc", "1", "", typed, "/no/such/folder", "", "", "", ""], "--setup")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Discos conectados a esta computadora:" in out
    assert "Macintosh HD · APFS" not in out and "(el disco de arranque de la Mac)" in out
    assert " 1) JM · APFS · 858.3 GB libres de 1863.0 GB" in out and " 2) USB · ExFAT" in out
    assert "la base de datos de Bakta necesita un enlace simbólico" in out
    assert "Escribir un número de la lista" in out
    assert f"añadida (solo lectura): {bioinf}" in out
    assert "/no/such/folder no está disponible" in proc.stderr
    assert "Docker Desktop no comparte" in out and "File sharing" in out
    data, dbs = m.disk / "ARVA" / "data", m.disk / "ARVA" / "databases"
    assert data.is_dir() and dbs.is_dir()
    lines = m.config.read_text().splitlines()[1:]
    assert lines == [f"ARVA_DATA_DIR={data}", f"ARVA_DATA_DIR_MOUNT={m.disk}", f"ARVA_DATABASES_DIR={dbs}",
                     f"ARVA_DATABASES_DIR_MOUNT={m.disk}", f"ARVA_ADD_DATABASES={bioinf}"]
    assert any("up" in c for c in m.calls)
    assert m.log("open.log") == ["http://localhost:8080"]
    # Saved: the next start in a terminal asks nothing.
    again = m.ask(shell, [])
    assert again.returncode == 0 and "Bienvenido" not in again.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_docker_desktop_is_opened_and_docker_volumes_can_be_kept(tmp_path, shell):
    m = FirstRun(tmp_path)
    (m.fake / "docker_down").touch()
    proc = m.ask(shell, ["0", "", "", "2", ""], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Docker Desktop is installed but not running: opening it" in proc.stdout
    assert m.log("open.log")[0] == "-a Docker"
    assert m.config.read_text().splitlines()[1:] == ["ARVA_PLATFORM=linux/arm64"]
    assert not m.override.exists()
    assert next(c for c in m.calls if "up" in c)[:2] == ["compose", "up"]


@pytest.mark.parametrize("shell", SHELLS)
def test_docker_volumes_only_still_marks_the_first_run_done(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings('{"UseVirtualizationFrameworkRosetta": true}')
    proc = m.ask(shell, ["0", "", "", "", ""], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert m.config.read_text().splitlines()[1:] == []


@pytest.mark.parametrize("shell", SHELLS)
def test_docker_that_never_starts_stops_before_any_question(tmp_path, shell):
    m = FirstRun(tmp_path)
    (m.fake / "docker_down").touch()
    (m.bin / "open").write_text('#!/bin/sh\necho "$*" >> "$FAKE/open.log"\n')
    proc = m.ask(shell, [], "--setup", ARVA_DOCKER_WAIT="0")
    assert proc.returncode == 1
    assert "Docker Desktop no estuvo listo en 0 s" in proc.stdout and "no se guardó nada" in proc.stderr
    assert not m.config.exists() and not m.calls


@pytest.mark.parametrize("shell", SHELLS)
def test_docker_desktop_not_installed(tmp_path, shell):
    m = FirstRun(tmp_path, docker=False)
    proc = m.ask(shell, [], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 1
    assert "Docker Desktop is not installed" in proc.stdout and "Mac with Apple chip" in proc.stdout
    assert "https://docs.docker.com/desktop/setup/install/mac-install/" in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_declining_saves_nothing(tmp_path, shell):
    m = FirstRun(tmp_path)
    proc = m.ask(shell, ["1", "", "", "", "", "", "n"], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0 and "Nothing was saved" in proc.stdout
    assert not m.config.exists() and not any("up" in c for c in m.calls)
    assert not (m.disk / "ARVA").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_amd64_with_rosetta_off_explains_the_setting_and_saves_the_choice(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings('{"UseVirtualizationFrameworkRosetta": false}')
    proc = m.ask(shell, ["0", "", "", "1", "", ""], "--setup", lang="en_US.UTF-8", FAKE_NO_ROSETTA="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "Rosetta 2 does not seem to be installed" in out and "softwareupdate --install-rosetta" in out
    assert "Docker Desktop's Rosetta setting is off" in out and "Use Rosetta for x86_64/amd64 emulation" in out
    assert "ARVA_PLATFORM=linux/amd64" in m.config.read_text().splitlines()


@pytest.mark.parametrize("shell", SHELLS)
def test_custom_folders_and_an_existing_data_folder(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings('{"UseVirtualizationFrameworkRosetta": true}')
    base = m.folder("Lab")
    (base / "data").mkdir()
    (base / "data" / ".arva-storage").write_text("{}")
    other = tmp_path / "Volumes" / "JM" / "dbs"
    proc = m.ask(shell, [f"'{base}'", "n", "", str(other), "", "", "", ""], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "is already an ARVA data folder: it is used as it is" in proc.stdout
    lines = m.config.read_text().splitlines()
    assert f"ARVA_DATA_DIR={base / 'data'}" in lines and f"ARVA_DATABASES_DIR={other}" in lines and other.is_dir()


@pytest.mark.parametrize("shell", SHELLS)
def test_a_denied_pull_offers_docker_login(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings('{"UseVirtualizationFrameworkRosetta": true}')
    (m.fake / "pull_denied").touch()
    proc = m.ask(shell, ["0", "", "", "", "", "s", "juan-m"], "--setup")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "read:packages" in proc.stdout
    args = m.log("docker.args")
    assert "login ghcr.io -u juan-m" in args
    pulls = [a for a in args if " pull " in f" {a} "]
    assert len(pulls) == 2 and args.index("login ghcr.io -u juan-m") > args.index(pulls[0])


@pytest.mark.parametrize("shell", SHELLS)
def test_a_denied_pull_refuses_a_bad_user_name(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings('{"UseVirtualizationFrameworkRosetta": true}')
    (m.fake / "pull_denied").touch()
    proc = m.ask(shell, ["0", "", "", "", "", "y", "x; rm -rf ~"], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 1 and "That is not a GitHub user name" in proc.stdout
    assert not any(a.startswith("login") for a in m.log("docker.args"))
    assert "docker login ghcr.io -u <your GitHub user name>" in proc.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_without_a_terminal_or_with_no_setup_nothing_is_asked(tmp_path, shell):
    m = FirstRun(tmp_path)
    for args in ((), ("--no-setup",)):
        proc = m.ask(shell, ["1"], *args)
        assert proc.returncode == 0, proc.stderr
        assert "Bienvenido" not in proc.stdout and not m.config.exists()


def test_stop_script_and_mac_launchers(tmp_path):
    for name in ("ARVA.command", "Detener ARVA.command"):
        launcher = ROOT / name
        assert os.access(launcher, os.X_OK), name
    assert "scripts/start.sh --open" in (ROOT / "ARVA.command").read_text()
    assert "scripts/stop.sh" in (ROOT / "Detener ARVA.command").read_text()
    m = FirstRun(tmp_path)
    proc = m.run("sh", script=ROOT / "scripts" / "stop.sh")
    assert proc.returncode == 0, proc.stderr
    assert m.calls == [["info"], ["compose", "-f", str(ROOT / "docker-compose.yml"), "down"]]
    refused = m.run("sh", "-v", script=ROOT / "scripts" / "stop.sh")
    assert refused.returncode == 2 and m.calls == []


def test_shellcheck_clean():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    files = [ROOT / "scripts" / "lib" / "arva-firstrun.sh", ROOT / "scripts" / "stop.sh", ROOT / "ARVA.command",
             ROOT / "Detener ARVA.command"]
    proc = subprocess.run(["shellcheck", "-x", "-s", "sh", *map(str, files)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
