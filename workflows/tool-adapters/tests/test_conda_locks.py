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
    for plat in conda_locks.PLATFORMS:
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
    platforms = tuple(p for p in conda_locks.PLATFORMS if (conda_locks.LOCKS / tool / f"{p}.lock").is_file())
    assert ADAPTERS[tool].info.conda_platforms == platforms


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
