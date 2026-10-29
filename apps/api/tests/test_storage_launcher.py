"""scripts/start.sh, restore.sh and backup.sh: saved locations, folder checks and the Compose override, with fake uname,
df, diskutil and docker executables on PATH.

The fake outputs are CONSTRUCTED from the documented formats: `df -Pk` (POSIX; Apple file_cmds df/df.c leaves out
the inode columns with -P) and `diskutil info -plist <mount point>` (keys FilesystemType, FilesystemName,
FilesystemUserVisibleName, MountPoint and VolumeName as parsed by corpnewt/gibMacOS and brokeyourbike/mountefi);
none is copied from a real Mac, and the scripts have not run on one.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
START = ROOT / "scripts" / "start.sh"
RESTORE = ROOT / "scripts" / "restore.sh"
BACKUP = ROOT / "scripts" / "backup.sh"
SHELLS = [s for s in ("dash", "bash") if shutil.which(s)]
TB_KB = 1953514584

DOCKER = f"""#!{sys.executable}
import json, os, sys
fake = os.environ["FAKE"]
args = sys.argv[1:]
with open(os.path.join(fake, "docker.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["info", "--format"]:
    print("8 8589934592")
elif args and args[0] == "compose":
    if "up" in args:
        env = {{k: v for k, v in os.environ.items() if k.startswith("ARVA_HOST_")}}
        open(os.path.join(fake, "compose_env.json"), "w").write(json.dumps(env))
    if args[-2:] == ["backup", "list"]:
        sys.stdout.write(open(os.path.join(fake, "backups")).read() if os.path.exists(os.path.join(fake, "backups")) else "")
    if "restore" in args:
        sys.exit(int(os.environ.get("FAKE_RESTORE_STATUS", "0")))
    if "exec" in args:
        sys.exit(1)
"""

# `df -Pk PATH`: the longest mount point in $FAKE/mounts (MOUNT|TOTAL_KB|AVAIL_KB|FILESYSTEM) that holds PATH.
DF = r"""#!/bin/sh
for p do :; done
best='' bt='' ba='' bf=''
while IFS='|' read -r mount total avail fs; do
  case "$p/" in
    "$mount"/* | "${mount%/}"/*) if [ "${#mount}" -gt "${#best}" ]; then best=$mount bt=$total ba=$avail bf=$fs; fi ;;
  esac
done < "$FAKE/mounts"
[ -n "$best" ] || exit 1
printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
printf '%s %s %s %s %s%% %s\n' "$bf" "$bt" "$((bt - ba))" "$ba" "$(( (bt - ba) * 100 / bt ))" "$best"
"""

DISKUTIL = r"""#!/bin/sh
[ "$1 $2" = "info -plist" ] || exit 2
f="$FAKE/diskutil/$(printf '%s' "$3" | tr '/ ' '__').plist"
if [ -f "$f" ]; then cat "$f"; else echo "Could not find disk: $3" >&2; exit 1; fi
"""

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>FilesystemName</key>
	<string>{name}</string>
	<key>FilesystemType</key>
	<string>{type}</string>
	<key>FilesystemUserVisibleName</key>
	<string>{name}</string>
	<key>MountPoint</key>
	<string>{mount}</string>
	<key>VolumeName</key>
	<string>JM</string>
</dict>
</plist>
"""


class Mac:
    """A constructed computer: a tmp folder standing for an external disk mounted at <tmp>/Volumes/JM."""

    def __init__(self, tmp: Path, os_name: str = "Darwin"):
        self.tmp = tmp
        self.fake = tmp / "fake"
        self.bin = tmp / "bin"
        self.home = tmp / "home"
        for d in (self.fake / "diskutil", self.bin, self.home):
            d.mkdir(parents=True)
        self.disk = tmp / "Volumes" / "JM"
        self.disk.mkdir(parents=True)
        self.os_name = os_name
        self.mounts = [("/", "500000000", "300000000", "/dev/disk3s1s1")]
        self.mount(self.disk, "apfs", "APFS")
        for name, body in {"docker": DOCKER, "df": DF, "diskutil": DISKUTIL,
                           "uname": f'#!/bin/sh\n[ "$1" = -s ] && echo {os_name} || echo arm64\n'}.items():
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def mount(self, path: Path, fs_type: str, fs_name: str, avail_kb: int = 900000000):
        self.mounts.append((str(path), str(TB_KB), str(avail_kb), "/dev/disk4s1"))
        (self.fake / "diskutil" / (str(path).replace("/", "_").replace(" ", "_") + ".plist")).write_text(
            PLIST.format(name=fs_name, type=fs_type, mount=path))
        self._write()

    def unmount(self, path: Path):
        self.mounts = [m for m in self.mounts if m[0] != str(path)]
        self._write()

    def _write(self):
        (self.fake / "mounts").write_text("".join("|".join(m) + "\n" for m in self.mounts))

    def folder(self, *parts: str) -> Path:
        p = self.disk.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def run(self, shell: str, *args: str, script: Path = START, stdin: str = "", lang: str = "en_US.UTF-8"):
        for f in ("docker.log", "compose_env.json"):
            (self.fake / f).unlink(missing_ok=True)
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "FAKE": str(self.fake), "HOME": str(self.home), "LANG": lang}
        return subprocess.run([shell, str(script), *args], env=env, input=stdin, capture_output=True, text=True,
                              timeout=60)

    @property
    def calls(self) -> list[list[str]]:
        log = self.fake / "docker.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    @property
    def compose_env(self) -> dict | None:
        f = self.fake / "compose_env.json"
        return json.loads(f.read_text()) if f.exists() else None

    @property
    def config(self) -> Path:
        return self.home / ".config" / "arva" / "arva.conf"

    @property
    def override(self) -> Path:
        return self.home / ".config" / "arva" / "compose.storage.yml"


def _slot(path: Path) -> str:
    return subprocess.run(["cksum"], input=str(path).encode(), capture_output=True, check=True).stdout.split()[0].decode()


@pytest.mark.parametrize("shell", SHELLS)
def test_locations_are_checked_saved_and_mounted_read_only_where_they_must_be(tmp_path, shell):
    m = Mac(tmp_path)
    data, dbs, runs = m.folder("ARVA", "data"), m.folder("ARVA", "databases"), m.folder("runs")
    bakta = m.folder("BioInf", "bakta db")
    proc = m.run(shell, "--data-dir", str(data), f"--databases-dir={dbs}", "--add-databases", str(bakta),
                 "--import-dir", str(runs), "--build")
    assert proc.returncode == 0, proc.stderr
    assert stat.S_IMODE(m.config.stat().st_mode) == 0o600 and stat.S_IMODE(m.config.parent.stat().st_mode) == 0o700
    lines = m.config.read_text().splitlines()[1:]
    assert lines == [f"ARVA_DATA_DIR={data}", f"ARVA_DATA_DIR_MOUNT={m.disk}", f"ARVA_DATABASES_DIR={dbs}",
                     f"ARVA_DATABASES_DIR_MOUNT={m.disk}", f"ARVA_IMPORT_DIR={runs}", f"ARVA_ADD_DATABASES={bakta}"]
    up = next(c for c in m.calls if "up" in c)
    assert up == ["compose", "-f", str(ROOT / "docker-compose.yml"), "-f", str(m.override), "up", "-d", "--build"]
    slot = _slot(bakta)
    assert {k: v for k, v in m.compose_env.items() if not k.startswith(("ARVA_HOST_PLATFORM", "ARVA_HOST_MODEL",
            "ARVA_HOST_CHIP", "ARVA_HOST_PERF", "ARVA_HOST_EFF", "ARVA_HOST_PHYS", "ARVA_HOST_LOGICAL",
            "ARVA_HOST_MEMORY", "ARVA_HOST_OS", "ARVA_HOST_ARCH", "ARVA_HOST_DOCKER"))} == {
        "ARVA_HOST_DATA_DIR": str(data), "ARVA_HOST_DATA_FS": "apfs", "ARVA_HOST_DATABASES_DIR": str(dbs),
        "ARVA_HOST_DATABASES_FS": "apfs", "ARVA_HOST_IMPORT_DIR": str(runs), "ARVA_HOST_IMPORT_FS": "apfs",
        f"ARVA_HOST_EXTERNAL_DB_{slot}": str(bakta), f"ARVA_HOST_EXTERNAL_DB_{slot}_FS": "apfs"}
    text = m.override.read_text()
    assert str(tmp_path) not in text and "create_host_path: false" in text
    assert f"target: /databases-external/{slot}\n    read_only: true" in text
    assert "target: /import\n    read_only: true" in text and "target: /data\n    bind:" in text
    assert "APFS · 858.3 GB free of 1863.0 GB" in proc.stdout
    # The next start uses what was saved.
    again = m.run(shell)
    assert again.returncode == 0, again.stderr
    assert next(c for c in m.calls if "up" in c)[-2:] == ["up", "-d"]


@pytest.mark.parametrize("shell", SHELLS)
def test_saved_values_are_only_ever_paths_never_run(tmp_path, shell):
    m = Mac(tmp_path, "Linux")
    m.config.parent.mkdir(parents=True)
    m.config.write_text("# hand-edited\n"
                        f"ARVA_DATA_DIR=$(touch {tmp_path}/pwned1)\n"
                        f"ARVA_DATABASES_DIR=`touch {tmp_path}/pwned2`\n"
                        f"ARVA_IMPORT_DIR=/tmp; touch {tmp_path}/pwned3\r\n"
                        f"ARVA_ADD_DATABASES=/x/$(touch {tmp_path}/pwned4)\n"
                        "PATH=/nowhere\nnot a key value line\n")
    m.config.chmod(0o600)
    proc = m.run(shell)
    assert proc.returncode == 1 and m.calls == []
    assert "must be an absolute path" in proc.stderr and "unknown key" in proc.stderr
    assert not any((tmp_path / f"pwned{i}").exists() for i in range(1, 5))
    # A writable-by-others file is refused outright.
    m.config.chmod(0o666)
    assert "chmod 600" in m.run(shell).stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_a_path_with_quotes_and_dollars_reaches_compose_unchanged(tmp_path, shell):
    m = Mac(tmp_path, "Linux")
    data = m.folder("it's $HOME `x` data")
    proc = m.run(shell, "--data-dir", str(data))
    assert proc.returncode == 0, proc.stderr
    assert m.compose_env["ARVA_HOST_DATA_DIR"] == str(data)
    assert "$HOME" not in m.override.read_text()
    assert m.run(shell, "--data-dir", "relative/path").returncode == 1
    assert m.run(shell, "--data-dir", f"{data}\nARVA_DATA_DIR=/").returncode == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_exfat_and_low_space_are_warned_about(tmp_path, shell):
    m = Mac(tmp_path)
    usb = tmp_path / "Volumes" / "USB"
    usb.mkdir(parents=True)
    m.mount(usb, "exfat", "ExFAT", avail_kb=1048576)
    proc = m.run(shell, "--data-dir", str(usb), lang="es_ES.UTF-8")
    assert proc.returncode == 0, proc.stderr
    assert "exFAT o FAT" in proc.stderr and "APFS o Mac OS Plus" in proc.stderr and "menos de 20 GB" in proc.stderr
    assert m.compose_env["ARVA_HOST_DATA_FS"] == "exfat"


@pytest.mark.parametrize("shell", SHELLS)
def test_a_disk_that_is_not_connected_stops_the_start(tmp_path, shell):
    m = Mac(tmp_path)
    data = m.folder("ARVA", "data")
    assert m.run(shell, "--data-dir", str(data)).returncode == 0
    # The disk is ejected and an empty folder with the same path is left on the startup disk.
    m.unmount(m.disk)
    proc = m.run(shell)
    assert proc.returncode == 1 and m.calls == []
    assert f"not on the disk it was on when you chose it ({m.disk}) but on /" in proc.stderr
    assert "ARVA did not start" in proc.stderr
    # No folder at all: refused as well, and nothing is created.
    shutil.rmtree(m.disk)
    proc = m.run(shell)
    assert proc.returncode == 1 and "does not exist" in proc.stderr and not data.exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_an_added_database_folder_that_is_missing_is_left_out(tmp_path, shell):
    m = Mac(tmp_path)
    data, bakta = m.folder("ARVA", "data"), m.folder("BioInf", "bakta")
    assert m.run(shell, "--data-dir", str(data), "--add-databases", str(bakta)).returncode == 0
    bakta.rmdir()
    proc = m.run(shell)
    assert proc.returncode == 0, proc.stderr
    assert "is not available: is its disk connected?" in proc.stderr and "unavailable (disk not connected)" in proc.stderr
    slot = _slot(bakta)
    text = m.override.read_text()
    assert f"/databases-external/{slot}" in text and f"target: /databases-external/{slot}" not in text
    assert m.compose_env[f"ARVA_HOST_EXTERNAL_DB_{slot}"] == str(bakta)
    assert m.run(shell, "--remove-databases", str(bakta)).returncode == 0
    assert "ARVA_ADD_DATABASES" not in m.config.read_text()


@pytest.mark.parametrize("shell", SHELLS)
def test_show_and_reset_touch_no_folder(tmp_path, shell):
    m = Mac(tmp_path, "Linux")
    data = m.folder("ARVA", "data")
    (data / "keep.txt").write_text("x")
    assert m.run(shell, "--data-dir", str(data)).returncode == 0
    shown = m.run(shell, "--show-config")
    assert shown.returncode == 0 and str(data) in shown.stdout and "scripts/start.sh --data-dir" in shown.stdout
    assert not any("up" in c for c in m.calls)
    reset = m.run(shell, "--reset-config")
    assert reset.returncode == 0 and not m.config.exists() and not m.override.exists()
    assert (data / "keep.txt").exists()
    assert next(c for c in (m.run(shell) and m.calls) if "up" in c) == ["compose", "up", "-d"]


def test_the_generated_override_is_valid_compose(tmp_path):
    docker = shutil.which("docker")
    if docker is None or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:
        pytest.skip("docker compose is not installed")
    m = Mac(tmp_path, "Linux")
    data, dbs, bakta = m.folder("ARVA", "data"), m.folder("ARVA", "databases"), m.folder("BioInf", "bakta")
    gone = tmp_path / "Volumes" / "Other" / "gtdb"
    gone.mkdir(parents=True)
    assert m.run("sh", "--data-dir", str(data), "--databases-dir", str(dbs), "--add-databases", str(bakta),
                 "--add-databases", str(gone)).returncode == 0
    gone.rmdir()
    assert m.run("sh").returncode == 0
    env = {**os.environ, **m.compose_env}
    files = ["-f", str(ROOT / "docker-compose.yml"), "-f", str(m.override)]
    check = subprocess.run([docker, "compose", *files, "config", "-q"], env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    model = json.loads(subprocess.run([docker, "compose", *files, "config", "--format", "json"], env=env,
                                      capture_output=True, text=True, check=True).stdout)
    api = {v["target"]: v for v in model["services"]["api"]["volumes"]}
    assert api["/data"]["source"] == str(data) and api["/data"]["bind"]["create_host_path"] is False
    assert api[f"/databases-external/{_slot(bakta)}"]["read_only"] is True
    assert f"/databases-external/{_slot(gone)}" not in api
    roots = json.loads(model["services"]["worker"]["environment"]["ARVA_EXTERNAL_DB_ROOTS"])
    assert roots == [f"/databases-external/{_slot(bakta)}", f"/databases-external/{_slot(gone)}"]
    assert {v["target"] for v in model["services"]["backup"]["volumes"]} == {"/data", "/opt/arva/metadata-backup.sh"}
    # Without the launcher's variables Compose refuses instead of mounting something else.
    bare = subprocess.run([docker, "compose", *files, "config", "-q"], capture_output=True, text=True,
                          env={k: v for k, v in os.environ.items() if not k.startswith("ARVA_HOST_")})
    assert bare.returncode != 0 and "set by scripts/start.sh" in bare.stderr


# --- restore.sh and backup.sh -----------------------------------------------------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_restore_asks_first_then_stops_restores_and_starts_again(tmp_path, shell):
    m = Mac(tmp_path, "Linux")
    data = m.folder("ARVA", "data")
    assert m.run(shell, "--data-dir", str(data)).returncode == 0
    (m.fake / "backups").write_text("arva-metadata-manual-20261028T153000Z.dump\narva-metadata-auto-20261028T020000Z.dump\n")
    declined = m.run(shell, "latest", script=RESTORE, stdin="no\n")
    assert declined.returncode == 1 and "Nothing was changed" in declined.stdout
    assert not any("stop" in c or "restore" in c for c in m.calls)
    done = m.run(shell, "latest", script=RESTORE, stdin="yes\n")
    assert done.returncode == 0, done.stderr
    verbs = [c[c.index("-f") + 4:] for c in m.calls]
    assert verbs == [["up", "-d", "--wait", "postgres"], ["run", "--rm", "--no-deps", "-T", "backup", "list"],
                     ["stop", "api", "worker", "backup"],
                     ["run", "--rm", "--no-deps", "-T", "backup", "restore", "arva-metadata-manual-20261028T153000Z.dump"],
                     ["up", "-d"]]
    assert m.run(shell, "../etc/passwd", script=RESTORE).returncode == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_restore_and_backup_do_nothing_while_the_disk_is_missing(tmp_path, shell):
    m = Mac(tmp_path)
    data = m.folder("ARVA", "data")
    assert m.run(shell, "--data-dir", str(data)).returncode == 0
    m.unmount(m.disk)
    for script, args in ((RESTORE, ("--yes", "latest")), (BACKUP, ())):
        proc = m.run(shell, *args, script=script)
        assert proc.returncode == 1 and m.calls == [] and "connect the disk" in proc.stderr.lower()


def test_backup_runs_a_manual_backup_in_the_backup_service(tmp_path):
    m = Mac(tmp_path, "Linux")
    assert m.run("sh", script=BACKUP).returncode == 0
    assert m.calls == [["compose", "up", "-d", "--wait", "postgres"],
                       ["compose", "run", "--rm", "--no-deps", "-T", "backup", "backup", "manual"]]


def test_shellcheck_clean():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    scripts = [START, RESTORE, BACKUP, ROOT / "scripts" / "metadata-backup.sh", ROOT / "scripts" / "lib" / "arva-locations.sh"]
    proc = subprocess.run(["shellcheck", "-x", "-s", "sh", *map(str, scripts)], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout
