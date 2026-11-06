"""The checked-in Bioconda locks (docker/conda-locks): every line an allowed URL with its SHA-256, a lock (or a note
saying why not) per platform, the adapters' platforms matching the locks, and an installed environment identical to
its lock. With ARVA_TEST_NETWORK=1, micromamba is shown to refuse a package whose checksum differs from the lock."""
import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from arva_tools.registry import ADAPTERS, detect

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("conda_locks", ROOT / "scripts" / "conda_locks.py")
conda_locks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conda_locks)
TOOLS = sorted(p.name for p in conda_locks.LOCKS.iterdir() if (p / "spec.txt").is_file())


def test_there_are_locks():
    assert "mlst" in TOOLS


@pytest.mark.parametrize("tool", TOOLS)
def test_each_platform_has_a_valid_lock_or_a_note(tool):
    for plat in conda_locks.tool_platforms(tool):
        lock = conda_locks.LOCKS / tool / f"{plat}.lock"
        note = conda_locks.LOCKS / tool / f"{plat}.unavailable"
        assert lock.is_file() != note.is_file(), f"{tool} {plat}: exactly one of .lock and .unavailable"
        if lock.is_file():
            packages = conda_locks.check_lock(lock, plat)
            assert all(len(p["sha256"]) == 64 for p in packages)
            names = [p["url"].rsplit("/", 1)[1] for p in packages]
            package = conda_locks.read_spec(tool)[0].split("=")[0]
            assert any(n.startswith(f"{package}-") for n in names)
            spec = " ".join(conda_locks.read_spec(tool))
            assert f"# spec: {spec}" in lock.read_text()


@pytest.mark.parametrize("tool", TOOLS)
def test_adapter_platforms_match_the_locks(tool):
    platforms = tuple(p for p in conda_locks.tool_platforms(tool) if (conda_locks.LOCKS / tool / f"{p}.lock").is_file())
    assert ADAPTERS[tool].info.conda_platforms == platforms


def test_only_flye_and_bakta_have_an_optional_native_platform():
    """osx-arm64 is optional (ARVA.app's native Flye and Bakta): only tools whose native-platforms file names it need
    a lock or a note for it, and only Flye and Bakta have one."""
    assert {t: conda_locks.native_platforms(t) for t in TOOLS if conda_locks.native_platforms(t)} == \
        {"flye": ("osx-arm64",), "bakta": ("osx-arm64",)}
    assert conda_locks.tool_platforms("mlst") == conda_locks.PLATFORMS
    for tool in ("flye", "bakta"):
        packages = conda_locks.check_lock(conda_locks.LOCKS / tool / "osx-arm64.lock", "osx-arm64")
        assert {p["url"].split("/")[4] for p in packages} == {"osx-arm64", "noarch"}
        assert "# solved with CONDA_OVERRIDE_OSX=11.0" in (conda_locks.LOCKS / tool / "osx-arm64.lock").read_text()
    # Solving for macOS from Linux needs the __osx virtual package; Linux platforms get no override.
    assert conda_locks.solver_env("osx-arm64") == {"CONDA_OVERRIDE_OSX": "11.0"}
    assert conda_locks.solver_env("linux-64") == {}


def test_an_optional_platform_is_refused_for_a_tool_that_does_not_list_it(monkeypatch):
    monkeypatch.setattr(conda_locks, "micromamba", lambda _explicit: "/nonexistent/micromamba")
    with pytest.raises(SystemExit, match="not one of its platforms"):
        conda_locks.cmd_update(type("Args", (), {"micromamba": None, "tool": "mlst", "platform": ["osx-arm64"]})())


def test_the_installer_pins_micromamba_for_apple_silicon_and_checks_it_with_shasum():
    text = conda_locks.INSTALLER.read_text()
    assert 'SUBDIR="osx-arm64"; SHA256="500f5074feb8d02c4296ef9921c3650ed2874171805a9fbb8fbb53896433646b"' in text
    assert "shasum -a 256 -c" in text and "sha256sum -c" in text


def test_lock_lines_are_refused_unless_pinned(tmp_path):
    good = "https://conda.anaconda.org/bioconda/noarch/any2fasta-0.8.1-hdfd78af_0.conda#sha256:" + "a" * 64
    for bad in ("https://conda.anaconda.org/bioconda/noarch/any2fasta-0.8.1-hdfd78af_0.conda",
                good.replace("sha256:", "md5:"), good.replace("conda.anaconda.org/bioconda", "example.org/x"),
                good.replace("a" * 64, "a" * 63), good.replace("https://", "http://")):
        lock = tmp_path / "linux-64.lock"
        lock.write_text(f"@EXPLICIT\n{bad}\n")
        with pytest.raises(ValueError):
            conda_locks.parse_lock(lock)
    lock.write_text(f"{good}\n")
    with pytest.raises(ValueError, match="@EXPLICIT"):
        conda_locks.parse_lock(lock)
    lock.write_text(f"@EXPLICIT\n{good.replace('noarch', 'linux-aarch64')}\n")
    with pytest.raises(ValueError, match="not linux-64"):
        conda_locks.check_lock(lock, "linux-64")


@pytest.mark.parametrize("tool", TOOLS)
def test_installed_environment_is_identical_to_its_lock(tool, capsys):
    d = detect(tool, refresh=True)
    plat = conda_locks.machine_platform()
    prefix = Path(os.path.realpath(d.path)).parent.parent if d.path else None
    if prefix is None or not (prefix / "conda-meta").is_dir():
        pytest.skip(f"{tool} is not installed from a conda environment here")
    conda_locks.verify_env(tool, prefix, plat)
    assert "identical" in capsys.readouterr().out


@pytest.mark.skipif(os.environ.get("ARVA_TEST_NETWORK") != "1", reason="downloads one small package (ARVA_TEST_NETWORK=1)")
def test_micromamba_refuses_a_package_whose_checksum_differs(tmp_path):
    try:
        mm = conda_locks.micromamba(None)
    except SystemExit:
        pytest.skip("micromamba is not installed")
    lock = next(p for p in conda_locks.check_lock(conda_locks.LOCKS / "mlst" / "linux-64.lock", "linux-64")
                if "/any2fasta-" in p["url"])
    for sha, ok in ((lock["sha256"], True), ("0" * 64, False)):
        explicit = tmp_path / f"{ok}.lock"
        explicit.write_text(f"@EXPLICIT\n{lock['url']}#sha256:{sha}\n")
        with tempfile.TemporaryDirectory() as root:
            proc = conda_locks.run(mm, ["create", "--yes", "--no-rc", "--prefix", str(tmp_path / f"env-{ok}"),
                                        "--file", str(explicit)], Path(root))
        assert (proc.returncode == 0) is ok, proc.stdout + proc.stderr
        if not ok:
            assert "incorrect SHA256" in proc.stdout + proc.stderr


def test_script_check_command():
    out = subprocess.run(["python3", "-I", str(ROOT / "scripts" / "conda_locks.py"), "check"], capture_output=True,
                         text=True, check=True).stdout
    assert "mlst linux-64:" in out and "mlst linux-aarch64:" in out
    assert "flye osx-arm64: 19 packages" in out and "mlst osx-arm64" not in out


def test_ridom_copies_bundled_by_spatyper_are_removed_after_install(tmp_path, capsys):
    for rel in ("bin/sparepeats.fasta", "bin/spatypes.txt", "share/spatyper-0.3.3/sparepeats.fasta",
                "share/spatyper-0.3.3/spatypes.txt", "bin/spaTyper"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    conda_locks.remove_listed("spatyper", tmp_path)
    left = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert left == ["bin/spaTyper"]
    assert capsys.readouterr().out.count("removed") == 4
    d = detect("spatyper", refresh=True)
    if d.path:
        prefix = Path(os.path.realpath(d.path)).parent.parent
        assert not list(prefix.glob("bin/spa*.fasta")) and not list(prefix.glob("share/spatyper-*/spatypes.txt"))
