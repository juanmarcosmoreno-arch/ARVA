#!/usr/bin/env python3
"""ARVA's pinned Bioconda tool environments: one micromamba environment per tool, created only from the explicit
lock files checked in under docker/conda-locks/<tool>/ (one per platform; ARVA runs these tools on Linux, inside
the Docker image on a Mac).

A lock file lists every package as its exact URL on conda-forge or Bioconda followed by #sha256:<checksum>, the
value the channel's repodata gives for that file. micromamba refuses a download whose checksum differs and solves
nothing when it installs from a lock, so an environment created from it has exactly these packages.

    python3 scripts/conda_locks.py update mlst            # re-solve spec.txt for each platform, rewrite the locks
    python3 scripts/conda_locks.py check                  # every lock: allowed channel, platform, sha256 on each line
    python3 scripts/conda_locks.py install mlst PREFIX    # create PREFIX from this machine's lock, then verify it
    python3 scripts/conda_locks.py verify-env mlst PREFIX # installed packages == the lock (URL and sha256)
    python3 scripts/conda_locks.py verify-micromamba      # pinned micromamba checksums == conda-forge's repodata

micromamba's package and repodata caches live in a temporary folder that is removed afterwards (micromamba's HOME
points there too), so nothing is cached or recorded in the user's home.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKS = ROOT / "docker" / "conda-locks"
PLATFORMS = ("linux-64", "linux-aarch64")
CHANNELS = ("conda-forge", "bioconda")
ALLOWED_URL = re.compile(r"https://conda\.anaconda\.org/(conda-forge|bioconda)/(linux-64|linux-aarch64|noarch)/"
                         r"[A-Za-z0-9_.+-]+\.(conda|tar\.bz2)")
LINE = re.compile(r"(?P<url>\S+)#sha256:(?P<sha256>[0-9a-f]{64})")
INSTALLER = ROOT / "scripts" / "install-micromamba.sh"


def machine_platform() -> str:
    machine = platform.machine().lower()
    if sys.platform != "linux" or machine not in ("x86_64", "amd64", "aarch64", "arm64"):
        raise SystemExit(f"ARVA's Bioconda environments are for Linux on x86_64 or aarch64 (this is {sys.platform} "
                         f"{machine}); on a Mac they are part of the Docker image")
    return "linux-64" if machine in ("x86_64", "amd64") else "linux-aarch64"


def micromamba(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("ARVA_MICROMAMBA"),
                      str(Path.home() / ".arva-tools" / "micromamba" / "bin" / "micromamba"), shutil.which("micromamba")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise SystemExit("micromamba not found: run scripts/install-micromamba.sh (or pass --micromamba)")


def run(mm: str, args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    """micromamba with its root prefix, package cache, repodata cache (~/.cache/conda) and environment list
    (~/.conda/environments.txt) all inside `root`, a temporary folder, and no conda or mamba settings of the user."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CONDA", "MAMBA"))}
    env.update(MAMBA_ROOT_PREFIX=str(root), HOME=str(root), XDG_CACHE_HOME=str(root / "cache"))
    return subprocess.run([mm, *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


def read_spec(tool: str) -> list[str]:
    path = LOCKS / tool / "spec.txt"
    if not path.is_file():
        raise SystemExit(f"{path} does not exist")
    specs = [ln.split("#", 1)[0].strip() for ln in path.read_text().splitlines()]
    return [s for s in specs if s]


def parse_lock(path: Path) -> list[dict[str, str]]:
    """The packages of an explicit lock file, in order, each with its URL and SHA-256. Raises ValueError for a line
    that is not an allowed URL with a checksum."""
    packages, explicit = [], False
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "@EXPLICIT":
            explicit = True
            continue
        m = LINE.fullmatch(line)
        if not explicit or m is None or not ALLOWED_URL.fullmatch(m["url"]):
            raise ValueError(f"{path.name} line {n}: expected https://conda.anaconda.org/<conda-forge|bioconda>/"
                             f"<subdir>/<file>#sha256:<64 hex> after @EXPLICIT, got {line[:120]}")
        packages.append({"url": m["url"], "sha256": m["sha256"]})
    if not packages:
        raise ValueError(f"{path.name} lists no package")
    return packages


def check_lock(path: Path, plat: str) -> list[dict[str, str]]:
    packages = parse_lock(path)
    for p in packages:
        subdir = p["url"].split("/")[4]
        if subdir not in (plat, "noarch"):
            raise ValueError(f"{path.name}: {p['url']} is for {subdir}, not {plat}")
    if len({p["url"] for p in packages}) != len(packages):
        raise ValueError(f"{path.name} lists a package twice")
    return packages


def cmd_update(args: argparse.Namespace) -> None:
    mm = micromamba(args.micromamba)
    specs = read_spec(args.tool)
    version = run(mm, ["--version"], Path(tempfile.gettempdir())).stdout.strip()
    folder = LOCKS / args.tool
    with tempfile.TemporaryDirectory(prefix="arva-conda-lock-") as root:
        for plat in args.platform or PLATFORMS:
            unavailable = folder / f"{plat}.unavailable"
            proc = run(mm, ["create", "--name", "arva-lock", "--dry-run", "--json", "--no-rc", "--platform", plat,
                            "--override-channels", "--strict-channel-priority",
                            *(a for c in CHANNELS for a in ("--channel", c)), *specs], Path(root))
            try:
                actions = json.loads(proc.stdout).get("actions") or {}
            except json.JSONDecodeError:
                actions = {}
            link = actions.get("LINK") or []
            if proc.returncode != 0 or not link:
                reason = (proc.stderr or proc.stdout).strip().splitlines()[-20:]
                unavailable.write_text(f"# {' '.join(specs)} could not be solved for {plat} on "
                                       f"{dt.date.today().isoformat()} (micromamba {version}):\n"
                                       + "\n".join(f"# {ln}" for ln in reason) + "\n")
                (folder / f"{plat}.lock").unlink(missing_ok=True)
                print(f"{args.tool} {plat}: not solvable, see {unavailable.relative_to(ROOT)}")
                continue
            unavailable.unlink(missing_ok=True)
            lines = [f"# ARVA lock for {args.tool} on {plat}: written by scripts/conda_locks.py update with "
                     f"micromamba {version} on {dt.date.today().isoformat()}",
                     f"# spec: {' '.join(specs)}",
                     f"# channels: {' '.join(CHANNELS)} (strict priority)",
                     "@EXPLICIT"]
            lines += [f"{p['url']}#sha256:{p['sha256']}" for p in link]
            lock = folder / f"{plat}.lock"
            lock.write_text("\n".join(lines) + "\n")
            check_lock(lock, plat)
            print(f"{args.tool} {plat}: {len(link)} packages, "
                  f"{sum(p.get('size', 0) for p in link) / 1e6:.1f} MB to download -> {lock.relative_to(ROOT)}")


def cmd_check(args: argparse.Namespace) -> None:
    tools = args.tool or sorted(p.name for p in LOCKS.iterdir() if (p / "spec.txt").is_file())
    for tool in tools:
        for plat in PLATFORMS:
            lock = LOCKS / tool / f"{plat}.lock"
            if lock.is_file():
                print(f"{tool} {plat}: {len(check_lock(lock, plat))} packages, each with its sha256")
            elif (LOCKS / tool / f"{plat}.unavailable").is_file():
                print(f"{tool} {plat}: not available (see {plat}.unavailable)")
            else:
                raise SystemExit(f"{tool} {plat}: neither a lock nor a .unavailable note")


def installed(prefix: Path) -> dict[str, str]:
    """URL -> sha256 of every package installed in a conda environment (its conda-meta records)."""
    out = {}
    for record in (prefix / "conda-meta").glob("*.json"):
        meta = json.loads(record.read_text())
        out[meta["url"]] = meta.get("sha256") or ""
    return out


def verify_env(tool: str, prefix: Path, plat: str) -> None:
    lock = {p["url"]: p["sha256"] for p in check_lock(LOCKS / tool / f"{plat}.lock", plat)}
    found = installed(prefix)
    problems = [f"missing {u}" for u in lock if u not in found]
    problems += [f"not in the lock {u}" for u in found if u not in lock]
    problems += [f"checksum differs {u}" for u in lock if u in found and found[u] != lock[u]]
    if problems:
        raise SystemExit(f"{prefix} does not match {tool}/{plat}.lock:\n  " + "\n  ".join(problems))
    print(f"{prefix}: {len(found)} packages, identical to {tool}/{plat}.lock (URL and sha256)")


def cmd_install(args: argparse.Namespace) -> None:
    mm = micromamba(args.micromamba)
    plat = machine_platform()
    lock = LOCKS / args.tool / f"{plat}.lock"
    if not lock.is_file():
        raise SystemExit(f"There is no {plat} lock for {args.tool}"
                         + (f": {(LOCKS / args.tool / f'{plat}.unavailable').read_text()}"
                            if (LOCKS / args.tool / f"{plat}.unavailable").is_file() else ""))
    check_lock(lock, plat)
    prefix = Path(args.prefix).resolve()
    if prefix.exists():
        raise SystemExit(f"{prefix} already exists; remove it first to recreate the environment from the lock")
    # The environment's files are hard links to the packages micromamba unpacks in the temporary cache (on the same
    # disk), so the install needs the environment's size once, not twice; they stay when the cache is removed.
    # Packages' link scripts do not run: mob_suite's post-link script runs mob_init, which downloads databases into
    # the environment with TLS verification turned off.
    with tempfile.TemporaryDirectory(prefix="arva-conda-pkgs-") as root:
        proc = run(mm, ["create", "--yes", "--no-rc", "--skip-run-link-scripts", "--prefix", str(prefix), "--file",
                        str(lock)], Path(root))
    if proc.returncode != 0:
        shutil.rmtree(prefix, ignore_errors=True)
        raise SystemExit(f"micromamba could not create {prefix}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
    verify_env(args.tool, prefix, plat)
    size = sum(f.stat().st_size for f in prefix.rglob("*") if f.is_file() and not f.is_symlink())
    print(f"{args.tool}: installed at {prefix} ({size / 1e6:.0f} MB)")


def cmd_verify_env(args: argparse.Namespace) -> None:
    verify_env(args.tool, Path(args.prefix).resolve(), args.platform or machine_platform())


def cmd_verify_micromamba(args: argparse.Namespace) -> None:
    text = INSTALLER.read_text()
    version = re.search(r'^VERSION="([^"]+)"', text, re.M)
    build = re.search(r'^BUILD="([^"]+)"', text, re.M)
    pinned = dict(re.findall(r'SUBDIR="(linux-[\w]+)"; SHA256="([0-9a-f]{64})"', text))
    if not (version and build and set(pinned) == set(PLATFORMS)):
        raise SystemExit(f"{INSTALLER.name}: VERSION, BUILD or a platform's SHA256 not found")
    mm = micromamba(args.micromamba)
    with tempfile.TemporaryDirectory(prefix="arva-conda-search-") as root:
        for plat, sha in pinned.items():
            proc = run(mm, ["search", "--json", "--no-rc", "--override-channels", "--channel", "conda-forge",
                            "--platform", plat, f"micromamba=={version[1]}={build[1]}"], Path(root))
            pkgs = (json.loads(proc.stdout or "{}").get("result") or {}).get("pkgs") or []
            listed = {p.get("sha256") for p in pkgs if p.get("subdir") == plat}
            if sha not in listed:
                raise SystemExit(f"{plat}: pinned {sha} is not the repodata's sha256 ({', '.join(map(str, listed))})")
            print(f"micromamba {version[1]} build {build[1]} {plat}: {sha} matches conda-forge's repodata")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--micromamba", help="micromamba executable (default: ARVA_MICROMAMBA, "
                        "~/.arva-tools/micromamba/bin/micromamba, PATH)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("update")
    p.add_argument("tool")
    p.add_argument("--platform", action="append", choices=PLATFORMS)
    p.set_defaults(func=cmd_update)
    p = sub.add_parser("check")
    p.add_argument("tool", nargs="*")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("install")
    p.add_argument("tool")
    p.add_argument("prefix")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("verify-env")
    p.add_argument("tool")
    p.add_argument("prefix")
    p.add_argument("--platform", choices=PLATFORMS)
    p.set_defaults(func=cmd_verify_env)
    p = sub.add_parser("verify-micromamba")
    p.set_defaults(func=cmd_verify_micromamba)
    args = parser.parse_args()
    try:
        args.func(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
