"""The entry point ARVA.app runs on the user's Mac for the tools it may run natively (Flye and Bakta; see
docs/plan-flye-nativo.md, "Contrato implementado"). It runs with the Python of the tool's own Bioconda environment,
isolated (-I), so it puts this package's parent folder on sys.path itself and imports only the tool's adapter, which
needs the standard library only:

    <env>/bin/python -I <bundle>/arva_tools/native.py flye facts --executable <env>/bin/flye --lock <lock file>
    <env>/bin/python -I <bundle>/arva_tools/native.py flye argv --work work.json --data-dir D --executable E
    <env>/bin/python -I <bundle>/arva_tools/native.py flye run  --work work.json --data-dir D --executable E
    <env>/bin/python -I <bundle>/arva_tools/native.py bakta run --work work.json --data-dir D --executable E \
        --database-dir <ARVA_DATABASES_DIR> [--database-dir <each ARVA_ADD_DATABASES folder> ...]

facts prints what ARVA.app registers with the API; argv prints the checked argument vector (for a caller that runs
the tool itself); run checks and runs it and prints the report for the API's finish endpoint. A refusal prints the
same report with outcome "refused" and exits with status 3. SIGTERM stops a run: the tool's process group is
killed and the report says "stopped".
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arva_tools import bakta, flye
from arva_tools.native_common import NativeRefusal, NativeStopped

# The tools ARVA.app may run natively, by the id the API uses in its executor contract.
TOOLS = {"flye": flye, "bakta": bakta}
# Tools whose work names database folders (their roots must be folders of this Mac's arva.conf).
WITH_DATABASES = frozenset({"bakta"})
REFUSED = 3


def _work(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _stop(_signum, _frame) -> None:
    raise NativeStopped()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tool", choices=sorted(TOOLS))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("facts")
    p.add_argument("--executable", required=True)
    p.add_argument("--lock")
    for name in ("argv", "run"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True, help="the work record the API's claim endpoint returned (JSON file)")
        p.add_argument("--data-dir", required=True, help="ARVA's data folder on this Mac (ARVA_DATA_DIR)")
        p.add_argument("--executable", required=True, help="this Mac's tool (the environment ARVA.app installed)")
        p.add_argument("--database-dir", action="append", default=[], dest="database_dirs",
                       help="a database folder of this Mac's arva.conf (Bakta; repeat for each)")
    args = parser.parse_args(argv)
    module = TOOLS[args.tool]
    if args.command == "facts":
        print(json.dumps(module.native_facts(args.executable, args.lock)))
        return 0
    work = _work(args.work)
    extra = (args.database_dirs,) if args.tool in WITH_DATABASES else ()
    if args.command == "argv":
        try:
            built, results, env, *_ = module.prepare_native(work, args.data_dir, args.executable, *extra)
        except NativeRefusal as exc:
            print(json.dumps({"outcome": "refused", "code": exc.code, "detail": str(exc)}))
            return REFUSED
        print(json.dumps({"argv": built, "cwd": str(results), "env": env}))
        return 0
    signal.signal(signal.SIGTERM, _stop)
    report = module.run_native(work, args.data_dir, args.executable, *extra)
    print(json.dumps(report))
    return REFUSED if report["outcome"] == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
