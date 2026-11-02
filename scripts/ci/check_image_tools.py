"""Check every tool adapter's detection inside an ARVA API image (run by .github/workflows/images.yml).

For each Bioconda tool with a lock (docker/conda-locks/<tool>/spec.txt) the detected version must be the version
its spec pins when the image was built with that tool for this platform; a tool whose lock is missing for this
platform must report ARVA's documented reason (no_conda_platform), except Bakta on linux-aarch64, which comes from
PyPI there (docker/api.Dockerfile). No adapter may raise or report "failed". The table is printed either way.

Usage (inside the image): python -I check_image_tools.py --repo /src [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PYPI_ON_ARM = {"bakta": "1.12.2"}


def default_conda_tools(dockerfile: Path) -> set[str]:
    m = re.search(r'^ARG ARVA_CONDA_TOOLS="([^"]*)"', dockerfile.read_text(), re.MULTILINE)
    if not m:
        raise SystemExit(f"{dockerfile}: no ARG ARVA_CONDA_TOOLS default")
    return set(m.group(1).split())


def pinned_version(spec: Path) -> str:
    for line in spec.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split("=")
            if len(parts) < 2:
                raise SystemExit(f"{spec}: first package has no pinned version: {line}")
            return parts[1]
    raise SystemExit(f"{spec}: no package")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    from arva_tools.base import ToolStatus, conda_platform
    from arva_tools.registry import ADAPTERS, detect_all

    plat = conda_platform()
    locks = args.repo / "docker" / "conda-locks"
    built = default_conda_tools(args.repo / "docker" / "api.Dockerfile")
    detected = detect_all(refresh=True)
    rows, problems = [], []
    for d in detected:
        tool = d.info.id
        expect = "any"
        lock_dir = locks / tool
        if d.status is ToolStatus.failed:
            problems.append(f"{tool}: detection failed: {d.message}")
        if lock_dir.is_dir():
            has_lock = (lock_dir / f"{plat}.lock").is_file()
            if has_lock and tool in built:
                expect = pinned_version(lock_dir / "spec.txt")
            elif not has_lock and tool in PYPI_ON_ARM and plat == "linux-aarch64":
                expect = PYPI_ON_ARM[tool]
            elif not has_lock:
                expect = "no_conda_platform"
            else:
                expect = "not_built"
            if expect == "no_conda_platform":
                if d.status is not ToolStatus.not_installed or d.reason != "no_conda_platform":
                    problems.append(f"{tool}: expected reason no_conda_platform, got {d.status.value}/{d.reason}")
            elif expect == "not_built":
                if d.status is not ToolStatus.not_installed:
                    problems.append(f"{tool}: not built by default but detected as {d.status.value}")
            elif d.status is not ToolStatus.available or d.version != expect:
                problems.append(f"{tool}: expected version {expect}, got {d.status.value} {d.version} {d.message}")
        rows.append({"tool": tool, "status": d.status.value, "version": d.version, "reason": d.reason,
                     "expected": expect, "path": d.path, "message": d.message})
    missing = set(ADAPTERS) - {r["tool"] for r in rows}
    if missing:
        problems.append(f"adapters without a detection result: {sorted(missing)}")

    print(f"platform: {plat}; tools built from locks by default: {' '.join(sorted(built))}")
    print(f"{'tool':16} {'status':14} {'version':12} {'expected':18} reason")
    for r in rows:
        print(f"{r['tool']:16} {r['status']:14} {r['version'] or '-':12} {r['expected']:18} {r['reason'] or '-'}")
    if args.json:
        args.json.write_text(json.dumps({"platform": plat, "tools": rows, "problems": problems}, indent=2))
    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
