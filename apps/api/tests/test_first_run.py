"""scripts/start.sh's first-run questions (scripts/lib/arva-firstrun.sh), answered on standard input, with the fake
uname, df, diskutil and docker of test_storage_launcher.py plus fake open, arch, sysctl and curl.

As there, every fake output is CONSTRUCTED from documented formats; the Docker Desktop settings keys
(UseVirtualizationFrameworkRosetta, filesharingDirectories) are matched without regard to case because their spelling
in the file is not documented. Nothing here ran on a real Mac.
"""
import json
import os
import select
import shutil
import signal
import subprocess
import time
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
    # disk "abc" then 1, these folders, two database folders, end, no import folder, image 1, File sharing Enter, save.
    proc = m.ask(shell, ["abc", "1", "", typed, "/no/such/folder", "", "", "", "", ""], "--setup")
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


def summary(out: str) -> str:
    """The summary block the first run prints before "Save these choices and start ARVA?", spaces collapsed."""
    start = out.index("── Summary") if "── Summary" in out else out.index("── Resumen")
    end = out.index("Save these choices") if "Save these choices" in out else out.index("¿Guardar estas elecciones")
    assert start < end
    return " ".join(out[start:end].split())


@pytest.mark.parametrize("shell", SHELLS)
def test_the_summary_before_saving_shows_every_answer_and_none_for_skipped_ones(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings('{"UseVirtualizationFrameworkRosetta": true}')
    # Inside Docker Desktop, the existing database folder and the import folder skipped with Enter, image 2, save.
    proc = m.ask(shell, ["0", "", "", "2", ""], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = summary(proc.stdout)
    assert "Projects, results, reports, logs, backups: inside Docker Desktop (Docker volumes)" in text
    assert "Databases that ARVA downloads: inside Docker Desktop (Docker volumes)" in text
    assert "Existing database folders (read-only): none" in text
    assert "Folder to import from (read-only): none (ARVA's own import folder)" in text
    assert "Image architecture: arm64 (native, without the tools that have no arm64 build)" in text


@pytest.mark.parametrize("shell", SHELLS)
def test_the_spanish_summary_lists_the_chosen_folders(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings(sharing(m, "/Users", "/Volumes/JM"))
    bioinf, runs = m.folder("BioInf"), m.folder("runs")
    # Disk 1, these folders, one database folder, end, the import folder, image 1, save.
    proc = m.ask(shell, ["1", "", str(bioinf), "", str(runs), "", ""], "--setup")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = summary(proc.stdout)
    assert f"Proyectos, resultados, informes, registros, copias: {m.disk / 'ARVA' / 'data'}" in text
    assert f"Bases de datos que descarga ARVA: {m.disk / 'ARVA' / 'databases'}" in text
    assert f"Carpetas de bases de datos existentes (solo lectura): - {bioinf}" in text
    assert "ninguna" not in text
    assert f"Carpeta para importar (solo lectura): {runs}" in text
    assert "Arquitectura de las imágenes: amd64 (todas las herramientas, a través de Rosetta)" in text
    assert f"ARVA_IMPORT_DIR={runs}" in m.config.read_text().splitlines()


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("answers", [
    [],                             # at the first question (the disk)
    ["1"],                          # at "Use these folders?"
    ["1", ""],                      # at an existing database folder
    ["1", "", ""],                  # at the import folder
    ["1", "", "", ""],              # at the image question (seen on a real Mac: the first attempt ended there)
    ["1", "", "", "", ""],          # at "Press Enter" after the Rosetta setting
    ["1", "", "", "", "", ""],      # at "Press Enter" after the File sharing steps
    ["1", "", "", "", "", "", ""],  # at "Save these choices and start ARVA?", whose default is yes
])
def test_input_that_ends_early_stops_the_first_run_with_a_message(tmp_path, shell, answers):
    m = FirstRun(tmp_path)
    m.settings(REAL_KEYS)
    proc = m.ask(shell, answers, "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    err = " ".join(proc.stderr.split())
    assert "The answers ended before the last question" in err and "Nothing was saved and ARVA did not start" in err
    assert err.count("The answers ended before the last question") == 1
    assert "ARVA did not start; nothing was saved." in err
    assert not m.config.exists() and not any("up" in c for c in m.calls)
    assert not (m.disk / "ARVA").exists()
    if len(answers) == 7:
        assert "── Summary" in proc.stdout and "Save these choices and start ARVA?" in proc.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_input_that_ends_early_is_explained_in_spanish(tmp_path, shell):
    m = FirstRun(tmp_path)
    proc = m.ask(shell, ["1", "", "", ""], "--setup")
    assert proc.returncode == 1
    err = " ".join(proc.stderr.split())
    assert "Las respuestas terminaron antes de la última pregunta" in err and "No se guardó nada" in err
    assert not m.config.exists()


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_an_interrupted_first_run_says_so(tmp_path, shell, sig):
    m = FirstRun(tmp_path)
    env = {"PATH": f"{m.bin}:{m.usr}", "FAKE": str(m.fake), "HOME": str(m.home), "LANG": "en_US.UTF-8",
           "ARVA_VOLUMES_ROOT": str(tmp_path / "Volumes"), "ARVA_DOCKER_WAIT": "4"}
    proc = subprocess.Popen([shell, str(START), "--setup"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    out = b""
    deadline = time.monotonic() + 30
    while b"Disk for ARVA's data" not in out and time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 1)
        if ready:
            out += os.read(proc.stdout.fileno(), 4096)
    assert b"Disk for ARVA's data" in out
    proc.send_signal(sig)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 130, err
    assert "The questions were interrupted: nothing was saved and ARVA did not start." in err.decode()
    assert not m.config.exists() and not any(c[0] == "compose" for c in m.calls)


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
    # that folder, not these folders, data [default], databases elsewhere, no database folder, no import folder,
    # image 1, File sharing Enter, save.
    proc = m.ask(shell, [f"'{base}'", "n", "", str(other), "", "", "", "", ""], "--setup", lang="en_US.UTF-8")
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


# --- File sharing: an external disk shared only through /Volumes ------------------------------------------------
# Seen on a real Mac (Docker Desktop, settings-store.json): with the default File sharing list the settings file has
# no file-sharing key, and inside the containers /data (/Volumes/JM/ARVA/data) came from /run/host_mark/Volumes with
# the startup disk's size; with /Volumes/JM shared and /Volumes removed, from /run/host_mark/Volumes/JM with JM's.
# The key name for the list (FilesharingDirectories here) has NOT been seen in a real file: it is matched without
# regard to case, as the launcher does. ARVA_VOLUMES_ROOT stands for /Volumes.

# The settings keys seen on that Mac before the File sharing change (values constructed): PascalCase, only
# settings changed from Docker Desktop's defaults, no Rosetta and no file-sharing key.
REAL_KEYS = ('{"AutoStart": false, "Cpus": 4, "DataFolder": "/x", "DisplayedOnboarding": true, '
             '"LicenseTermsVersion": 2, "SettingsVersion": 43, "SwapMiB": 1024, "UseContainerdSnapshotter": true}')


def sharing(m: FirstRun, *folders: str) -> str:
    """A settings file with a File sharing list; "/Volumes" stands for the test's volumes folder and "/Users" also
    covers the test's home (ARVA's settings folder) and this checkout (its import/ folder), as /Users does on a Mac."""
    vroot = str(m.tmp / "Volumes")
    entries = []
    for f in folders:
        entries += [f, str(m.home), str(ROOT)] if f == "/Users" else [f.replace("/Volumes", vroot, 1)]
    listed = ", ".join(json.dumps(f) for f in entries)
    return '{"UseVirtualizationFrameworkRosetta": true, "FilesharingDirectories": [' + listed + "]}"


@pytest.mark.parametrize("shell", SHELLS)
def test_a_normal_start_explains_how_to_share_the_disk_itself(tmp_path, shell):
    m = FirstRun(tmp_path)
    data = m.folder("ARVA", "data")
    vroot = tmp_path / "Volumes"
    # Docker Desktop's defaults (no list in its settings file): /Volumes covers the disk.
    m.settings(REAL_KEYS)
    proc = m.ask(shell, [], "--data-dir", str(data), lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    err = " ".join(proc.stderr.split())
    # The settings file of a real Mac had no such list: Docker Desktop's defaults, or a key name ARVA does not know,
    # so the text says so instead of stating it as fact.
    assert "has no File sharing list that ARVA can read" in err and "default list" in err
    assert f"{m.disk} reaches ARVA only through {vroot}" in err
    assert "reads the free space of the Mac's startup disk" in err
    assert "under a name ARVA does not know" in err and "decides (Settings → Storage)" in err
    assert f"Cmd+Shift+G → type {m.disk} → Open; then select {vroot} in the list and remove it" in err
    assert any("up" in c for c in m.calls)  # only explained: ARVA still starts
    # Only /Volumes in the list.
    m.settings(sharing(m, "/Users", "/Volumes"))
    err = " ".join(m.ask(shell, [], lang="es_AR.UTF-8").stderr.split())
    assert f"Docker Desktop comparte {m.disk} con ARVA solo a través de {vroot}" in err and "Cmd+Shift+G" in err
    # The disk itself: nothing to say.
    m.settings(sharing(m, "/Users", "/Volumes/JM"))
    assert "File sharing" not in m.ask(shell, [], lang="en_US.UTF-8").stderr
    # A folder on the disk (deeper) also counts as the disk's own share.
    m.settings(sharing(m, "/Users", "/Volumes/JM/ARVA"))
    assert "File sharing" not in m.ask(shell, [], lang="en_US.UTF-8").stderr
    # Both: not confirmed which share Docker then uses.
    m.settings(sharing(m, "/Users", "/Volumes", "/Volumes/JM"))
    err = " ".join(m.ask(shell, [], lang="en_US.UTF-8").stderr.split())
    assert f"shares {m.disk} and also {vroot}" in err and "has not been confirmed" in err
    assert f"select {vroot} → remove it" in err
    # Not covered at all: Docker would refuse the mount. /Volumes is not listed, so there is nothing to remove.
    m.settings(sharing(m, "/Users"))
    err = " ".join(m.ask(shell, [], lang="en_US.UTF-8").stderr.split())
    assert f"Docker Desktop does not share {data}" in err and '"mounts denied"' in err
    assert f"type {m.disk} → Open → Apply" in err and "remove it" not in err
    # No settings file: the launcher cannot tell, and says nothing (ARVA checks once it runs).
    (m.home / "Library" / "Group Containers" / "group.com.docker" / "settings-store.json").unlink()
    assert "File sharing" not in m.ask(shell, [], lang="en_US.UTF-8").stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_the_first_run_waits_for_the_disk_to_be_shared_and_checks_again(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings(REAL_KEYS)
    # The second `docker info` (the one after Enter) stands for the user's change in Docker Desktop.
    fixed = m.fake / "fixed.json"
    fixed.write_text(sharing(m, "/Users", "/Volumes/JM"))
    store = m.home / "Library" / "Group Containers" / "group.com.docker" / "settings-store.json"
    wrapper = (m.bin / "docker").read_text().replace(
        '  info) [ ! -e "$FAKE/docker_down" ] || exit 1 ;;',
        '  info) [ ! -e "$FAKE/docker_down" ] || exit 1\n'
        '    echo x >> "$FAKE/info.count"\n'
        f'    if [ "$(wc -l < "$FAKE/info.count")" -eq 2 ]; then cp "$FAKE/fixed.json" \'{store}\'; fi ;;')
    (m.bin / "docker").write_text(wrapper)
    # disk 1, these folders, no database folder, no import folder, image 1, Rosetta Enter, File sharing Enter, save.
    proc = m.ask(shell, ["1", "", "", "", "", "", "", ""], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = " ".join(proc.stdout.split())
    assert "has no File sharing list that ARVA can read" in out and "Press Enter when done." in out
    assert f"Docker Desktop now shares {m.disk}." in out
    assert any("up" in c for c in m.calls)


@pytest.mark.parametrize("shell", SHELLS)
def test_the_first_run_goes_on_when_the_list_still_does_not_show_the_disk(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings(REAL_KEYS)
    proc = m.ask(shell, ["1", "", "", "", "", "", "", ""], "--setup", lang="es_AR.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = " ".join(proc.stdout.split())
    assert f"todavía muestra el problema de arriba para {m.disk}" in out and "ARVA se inicia igual" in out


@pytest.mark.parametrize("shell", SHELLS)
def test_every_folder_on_a_disk_is_checked_and_the_advice_fits_the_list(tmp_path, shell):
    m = FirstRun(tmp_path)
    data, dbs = m.folder("ARVA", "data"), m.folder("ARVA", "databases")
    vroot = tmp_path / "Volumes"
    # Only the data folder is listed: the database folder on the same disk is not covered ("mounts denied").
    m.settings(sharing(m, "/Users", "/Volumes/JM/ARVA/data"))
    err = " ".join(m.ask(shell, [], "--data-dir", str(data), "--databases-dir", str(dbs), lang="en_US.UTF-8")
                   .stderr.split())
    assert f"Docker Desktop does not share {dbs}" in err and f"type {m.disk} → Open → Apply" in err
    # The import/ folder next to docker-compose.yml is mounted too (no import folder chosen), so it must be shared.
    m.settings(json.dumps({"FilesharingDirectories": [str(m.home), str(m.disk)]}))
    err = " ".join(m.ask(shell, [], lang="en_US.UTF-8").stderr.split())
    assert f"Docker Desktop does not share {(ROOT / 'import').resolve()}:" in err
    # The root share counts as the share above the disk: the steps say to remove /, not /Volumes.
    m.settings('{"FilesharingDirectories": ["/"]}')
    err = " ".join(m.ask(shell, [], lang="en_US.UTF-8").stderr.split())
    assert "only through /. " in err and "select / in the list and remove it" in err
    assert f"select {vroot} in the list" not in err
    # Go's JSON encoder writes & as \u0026, and a comma may be part of a path.
    odd = m.folder("ARVA", "R&D, 2")
    escaped = json.dumps(str(odd)).replace("&", "\\u0026")
    assert "\\u0026" in escaped
    m.settings(sharing(m, "/Users", "/Volumes/JM/ARVA/data", "/Volumes/JM/ARVA/databases")
               .replace("]}", f", {escaped}]}}"))
    err = m.ask(shell, [], "--databases-dir", str(odd), lang="en_US.UTF-8").stderr
    assert "File sharing" not in err, err


@pytest.mark.parametrize("shell", SHELLS)
def test_the_first_run_waits_when_volumes_is_listed_beside_the_disk(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings(sharing(m, "/Users", "/Volumes", "/Volumes/JM"))
    proc = m.ask(shell, ["1", "", "", "", "", "", "", ""], "--setup", lang="en_US.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = " ".join(proc.stdout.split())
    assert f"shares {m.disk} and also" in out and "Press Enter when done." in out
    assert "Docker Desktop shares the chosen folders." not in out


@pytest.mark.parametrize("shell", SHELLS)
def test_a_settings_file_without_the_rosetta_key_is_docker_desktops_default_not_a_failure(tmp_path, shell):
    m = FirstRun(tmp_path)
    m.settings(REAL_KEYS)
    proc = m.ask(shell, ["0", "", "", "", "", ""], "--setup", lang="es_AR.UTF-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = " ".join(proc.stdout.split())
    assert "no guarda el ajuste de Rosetta" in out and "No falló nada" in out
    assert "No se pudo leer el ajuste de Rosetta" not in out
    # The amd64 image stays the automatic choice.
    assert "ARVA_PLATFORM" not in m.config.read_text()
    env = json.loads((m.fake / "compose_env.json").read_text())
    assert (env["ARVA_HOST_DOCKER_ROSETTA"], env["ARVA_HOST_IMAGE_REASON"]) == ("default", "rosetta_default")


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
