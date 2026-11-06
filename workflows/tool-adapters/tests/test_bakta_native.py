"""Bakta's native entry (ARVA.app on an Apple silicon Mac) and its memory estimate: the same argument vector as the
Docker run with the Mac's paths, the database folders of arva.conf, the start-up checks repeated with the Mac's
programs, every check before running, the run itself with a fake Bakta environment, the lock it installs from, and
DIAMOND's reference block read from the .dmnd headers. Runs on Linux."""
import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from arva_tools import bakta as bakta_module
from arva_tools.bakta import (
    CONSOLE_LOG,
    DIAMOND_MAGIC,
    NATIVE_LOCK,
    BaktaAdapter,
    BaktaParams,
    check_dependencies,
    diamond_header,
    memory_estimate,
    native_database,
    native_expected_argv,
    native_facts,
    plan_steps,
    prepare_native,
    run_native,
    skip_options,
)
from arva_tools.native_common import NativeRefusal

FIXTURES = Path(__file__).parent / "fixtures" / "bakta"
ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "workflows" / "tool-adapters" / "arva_tools" / "native.py"
HELP = (FIXTURES / "help_1.12.2.txt").read_text()
SCOPE = "results/0b0f7c1e-0000-4000-8000-000000000001/_project/0b0f7c1e-0000-4000-8000-000000000003"

# Stand-ins for the programs of Bioconda's Bakta environment, each printing what Bakta's start-up check reads.
VERSIONS = {"tRNAscan-SE": "tRNAscan-SE 2.0.12 (Nov 2022)", "aragorn": "ARAGORN v1.2.41 Dean Laslett",
            "cmscan": "# INFERNAL 1.1.5 (Sep 2023)", "diamond": "diamond v2.2.8.171 (C) Max Planck Society",
            "blastn": "blastn: 2.17.0+"}
FAKE_PROGRAM = """
import sys
print({text!r})
"""
FAKE_PILERCR = """
import sys
args = sys.argv[1:]
if "-options" in args:
    print("pilercr v1.06"); sys.exit(0)
open(args[args.index("-out") + 1], "w").write("no arrays\\n")
"""
FAKE_AMRFINDER = """
import sys
args = sys.argv[1:]
if "--version" in args:
    print("4.2.7"); sys.exit(0)
if "--database_version" in args:
    db = args[args.index("--database") + 1]
    if "old" in db:
        print("Database version: 2024-12-18.1"); sys.stderr.write("*** ERROR *** Database too old\\n"); sys.exit(1)
    print("Software version: 4.2.7"); print("Database version: 2026-10-29.1"); sys.exit(0)
"""
# The environment's python: answers the version imports of Bakta's check, runs scripts with the real interpreter.
FAKE_PYTHON = f"""
import os, sys
if len(sys.argv) > 2 and sys.argv[1] == "-c":
    print({{"pyrodigal": "3.7.1", "pyhmmer": "0.12.3", "pycirclize": "1.10.0"}}[sys.argv[2].split()[1].rstrip(";")])
    sys.exit(0)
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
"""
FAKE_BAKTA = f"""
import os, sys
args = sys.argv[1:]
if "--help" in args:
    sys.stdout.write({HELP!r}); sys.exit(0)
if "--version" in args:
    print("bakta 1.12.2"); sys.exit(0)
out = args[args.index("--output") + 1]
db = args[args.index("--db") + 1]
print("Parse genome sequences...")
print("predict tRNAs...")
print("\\tfound: 2")
sys.stdout.flush()
os.mkdir(out)
open(os.path.join(out, "argv.txt"), "w").write("\\n".join(sys.argv))
open(os.path.join(out, "db.txt"), "w").write(os.path.realpath(os.path.join(db, "amrfinderplus-db", "latest")))
for suffix in ("json", "tsv", "gff3", "gbff", "embl", "fna", "ffn", "faa", "txt", "log"):
    open(os.path.join(out, "annotation." + suffix), "w").write("x\\n")
print("Annotation successfully finished")
"""


def _exe(path: Path, body: str, interpreter: str = sys.executable) -> Path:
    path.write_text(f"#!{interpreter}\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _dmnd(path: Path, sequences: int, letters: int) -> None:
    path.write_bytes(struct.pack("<QIIQQQ", DIAMOND_MAGIC, 164, 3, sequences, letters, 0) + b"\0" * 16)


def _bakta_db(folder: Path, amr_version: str = "2026-10-29.1") -> Path:
    folder.mkdir(parents=True)
    (folder / "version.json").write_text(json.dumps({"major": 6, "minor": 0, "type": "light"}))
    _dmnd(folder / "pscc.dmnd", 3_557_503, 1_245_018_838)
    amr = folder / "amrfinderplus-db" / amr_version
    amr.mkdir(parents=True)
    (amr / "version.txt").write_text(amr_version + "\n")
    (folder / "amrfinderplus-db" / "latest").symlink_to(amr_version)
    return folder


@pytest.fixture
def mac(tmp_path):
    """A Mac as ARVA.app sees it: a Bakta environment (bakta and every program its start-up check runs, conda-meta),
    a data folder with its storage marker and the job's folder (staged genome, tmp-dir), and a database folder of
    arva.conf with a Bakta light database and an AMRFinderPlus database."""
    env = tmp_path / "arva-tools" / "conda" / "bakta"
    (env / "bin").mkdir(parents=True)
    python = _exe(env / "bin" / "python3.13", FAKE_PYTHON)
    bakta = _exe(env / "bin" / "bakta", FAKE_BAKTA, str(python))
    for name, text in VERSIONS.items():
        _exe(env / "bin" / name, FAKE_PROGRAM.format(text=text))
    _exe(env / "bin" / "pilercr", FAKE_PILERCR)
    _exe(env / "bin" / "amrfinder", FAKE_AMRFINDER)
    (env / "conda-meta").mkdir()
    (env / "conda-meta" / "bakta-1.12.2-pyhdfd78af_0.json").write_text(json.dumps(
        {"name": "bakta", "version": "1.12.2", "build": "pyhdfd78af_0", "sha256": NATIVE_LOCK["package_sha256"],
         "url": "https://conda.anaconda.org/bioconda/noarch/" + NATIVE_LOCK["package"]}))
    data = tmp_path / "Volumes" / "JM" / "ARVA" / "data"
    storage_id = str(uuid.uuid4())
    data.mkdir(parents=True)
    (data / ".arva-storage").write_text(json.dumps({"id": storage_id}))
    results = data / SCOPE
    (results / "input").mkdir(parents=True)
    (results / "input" / "genome.fna").write_text(">contig_1\nACGT\n")
    (results / "bakta-tmp").mkdir()
    databases = tmp_path / "Volumes" / "JM" / "ARVA" / "databases"
    _bakta_db(databases / "bakta-light" / "6.0")
    amr = databases / "amrfinderplus" / "2026-10-29.1"
    amr.mkdir(parents=True)
    (amr / "version.txt").write_text("2026-10-29.1\n")
    return {"data": str(data), "exe": str(bakta), "storage_id": storage_id, "results": results,
            "databases": str(databases), "env": env}


def _skips(mac, amr: bool = False) -> list[str]:
    db = Path(mac["databases"]) / "bakta-light" / "6.0"
    replacement = Path(mac["databases"]) / "amrfinderplus" / "2026-10-29.1" if amr else None
    return skip_options(plan_steps(check_dependencies(mac["exe"], db, replacement), "light", False))


def work_for(mac, amr: bool = False, **changes):
    params = BaktaParams(locus_tag="SAMPLE27", threads=2, genus="Staphylococcus", species="aureus")
    database = {"root": mac["databases"], "rel": "bakta-light/6.0"}
    amr_data = {"root": mac["databases"], "rel": "amrfinderplus/2026-10-29.1"} if amr else None
    skips = _skips(mac, amr)
    work = {"tool": "bakta", "storage_id": mac["storage_id"], "data_dir": mac["data"], "executable": mac["exe"],
            "params": params.as_dict(), "genome": f"{SCOPE}/input/genome.fna", "out_dir": f"{SCOPE}/bakta",
            "tmp_dir": f"{SCOPE}/bakta-tmp", "results_dir": SCOPE, "console_log": CONSOLE_LOG,
            "database": database, "amr_data": amr_data, "database_type": "light", "skip_options": skips,
            "argv": native_expected_argv(params, mac["data"], mac["exe"], f"{SCOPE}/input/genome.fna", database,
                                         amr_data, f"{SCOPE}/bakta", f"{SCOPE}/bakta-tmp", skips,
                                         BaktaAdapter.help_options(mac["exe"]))}
    return {**work, **changes}


def test_the_fake_environment_passes_baktas_start_up_checks(mac):
    """Every program of the fake environment passes, so the CDS step is planned: the same case as the Mac's."""
    deps = check_dependencies(mac["exe"], Path(mac["databases"]) / "bakta-light" / "6.0")
    assert {d["name"]: d["status"] for d in deps} == {d.name: "ok" for d in bakta_module.DEPENDENCIES}
    assert _skips(mac) == []


def test_native_argv_is_the_docker_argv_with_the_macs_paths(mac):
    work = work_for(mac)
    argv, results, env, deps = prepare_native(work, mac["data"], mac["exe"], [mac["databases"]])
    params = BaktaParams(**work["params"])
    docker = BaktaAdapter.argv("/opt/arva-tools/conda/bakta/bin/bakta", params, Path(f"/data/{SCOPE}/input/genome.fna"),
                               Path("/databases/bakta-light/6.0"), Path(f"/data/{SCOPE}/bakta"),
                               Path(f"/data/{SCOPE}/bakta-tmp"), [], BaktaAdapter.help_options(mac["exe"]))
    assert argv == work["argv"]
    assert argv[1:] == [a.replace("/data/", mac["data"] + "/").replace("/databases/", mac["databases"] + "/")
                        for a in docker[1:]]
    assert str(results) == f"{mac['data']}/{SCOPE}"
    assert env["PATH"].split(os.pathsep)[0] == str(Path(mac["exe"]).parent) and env["PYTHONUNBUFFERED"] == "1"
    assert all(d["status"] == "ok" for d in deps)


def test_a_native_run_writes_baktas_outputs_and_reports_what_ran(mac):
    work = work_for(mac)
    report = run_native(work, mac["data"], mac["exe"], [mac["databases"]])
    assert (report["outcome"], report["exit_code"], report["code"]) == ("exited", 0, None)
    assert report["argv"] == work["argv"] and report["executable"] == mac["exe"]
    assert set(report["outputs"]) <= bakta_module.native_outputs(work["out_dir"])
    assert f"{SCOPE}/bakta/annotation.json" in report["outputs"]
    console = (mac["results"] / CONSOLE_LOG).read_text()
    assert console.startswith("Parse genome sequences...") and "successfully finished" in console
    assert (mac["results"] / "bakta" / "argv.txt").read_text().splitlines() == work["argv"]
    assert {d["name"] for d in report["dependencies"]} == {d.name for d in bakta_module.DEPENDENCIES}


def test_the_amrfinderplus_view_is_made_on_the_mac_with_the_macs_paths(mac):
    """AMRFinderPlus data that replaces the database's own copy: --db is the composed view inside tmp-dir, made only
    after every check, linking to the Mac's folders (the container's links would point nowhere here)."""
    work = work_for(mac, amr=True)
    composed = mac["results"] / "bakta-tmp" / "database"
    assert f"{mac['data']}/{SCOPE}/bakta-tmp/database" in work["argv"]
    assert run_native(work_for(mac, amr=True, argv=["x"]), mac["data"], mac["exe"], [mac["databases"]])["code"] == \
        "argv_mismatch"
    assert not composed.exists()
    report = run_native(work, mac["data"], mac["exe"], [mac["databases"]])
    assert report["outcome"] == "exited", report
    assert (mac["results"] / "bakta" / "db.txt").read_text() == \
        os.path.realpath(Path(mac["databases"]) / "amrfinderplus" / "2026-10-29.1")
    assert os.readlink(composed / "pscc.dmnd") == str(Path(mac["databases"]) / "bakta-light" / "6.0" / "pscc.dmnd")


def _refusal(work, mac, data=None, exe=None, dirs=None):
    report = run_native(work, data or mac["data"], exe or mac["exe"], [mac["databases"]] if dirs is None else dirs)
    assert report["outcome"] == "refused" and report["exit_code"] is None and report["argv"] is None
    assert not (mac["results"] / "bakta").exists() and not (mac["results"] / CONSOLE_LOG).exists()
    return report["code"]


def test_every_check_runs_before_bakta(mac, tmp_path):
    assert _refusal(work_for(mac, genome="../../etc/passwd"), mac) == "unsafe_path"
    assert _refusal(work_for(mac, out_dir="/tmp/bakta"), mac) == "unsafe_path"
    assert _refusal(work_for(mac, out_dir="results/other/bakta"), mac) == "unsafe_path"
    assert _refusal(work_for(mac, storage_id=str(uuid.uuid4())), mac) == "storage_mismatch"
    assert _refusal(work_for(mac, data_dir="/Volumes/Other/data"), mac) == "other_data_dir"
    assert _refusal(work_for(mac, executable="/usr/local/bin/bakta"), mac) == "other_executable"
    assert _refusal(work_for(mac, tool="flye"), mac) == "not_bakta_work"
    assert _refusal(work_for(mac, console_log="../x.log"), mac) == "unsafe_path"
    # Database folders: only those of this Mac's arva.conf, and nothing leading outside them.
    assert _refusal(work_for(mac), mac, dirs=["/Volumes/JM/other"]) == "database_folder_unknown"
    assert _refusal(work_for(mac, database={"root": mac["databases"], "rel": "../data"}), mac) == "unsafe_path"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (Path(mac["databases"]) / "escape").symlink_to(outside)
    assert _refusal(work_for(mac, database={"root": mac["databases"], "rel": "escape"}), mac) == "outside_database_dir"
    assert _refusal(work_for(mac, database={"root": mac["databases"], "rel": "missing"}), mac) == "input_missing"
    assert _refusal(work_for(mac, database={"root": mac["databases"]}), mac) == "work_incomplete"
    # The steps confirmed in ARVA must be the ones this Mac's programs allow.
    assert _refusal(work_for(mac, skip_options=["--skip-cds"]), mac) == "programs_changed"
    # The API's argument vector is never run as given.
    for changed in (lambda a: [*a, "--meta"], lambda a: ["/bin/sh", *a[1:]], lambda a: [*a[:-1], "9"]):
        work = work_for(mac)
        assert _refusal({**work, "argv": changed(work["argv"])}, mac) == "argv_mismatch"
    assert _refusal(work_for(mac, params={**work_for(mac)["params"], "threads": 999}), mac) == "settings_rejected"
    assert _refusal(work_for(mac, params={"locus_tag": "X"}), mac) == "settings_rejected"
    work = work_for(mac)
    del work["argv"]
    assert _refusal(work, mac) == "work_incomplete"


def test_a_data_folder_with_spaces_is_refused(mac):
    with pytest.raises(NativeRefusal) as exc:
        prepare_native(work_for(mac), "/Volumes/My Disk/ARVA/data", mac["exe"], [mac["databases"]])
    assert exc.value.code == "path_has_spaces"
    with pytest.raises(NativeRefusal) as exc:
        native_database({"root": "/Volumes/My Disk/db", "rel": "bakta"}, None)
    assert exc.value.code == "path_has_spaces"


def test_facts_report_the_installed_build_lock_and_programs(mac):
    facts = native_facts(mac["exe"], str(ROOT / NATIVE_LOCK["lock"]))
    assert facts["version"] == "bakta 1.12.2" and facts["tool"] == "bakta"
    assert facts["package"]["build"] == NATIVE_LOCK["build"] and facts["package"]["sha256"] == NATIVE_LOCK["package_sha256"]
    assert facts["lock_sha256"] == NATIVE_LOCK["lock_sha256"]
    assert {"--db", "--tmp-dir", "--skip-cds", "--locus-tag-increment"} <= set(facts["help_options"])
    assert {d["name"]: d["status"] for d in facts["dependencies"]}["DIAMOND"] == "ok"


def test_the_native_lock_constants_match_the_checked_in_lock():
    lock = ROOT / NATIVE_LOCK["lock"]
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == NATIVE_LOCK["lock_sha256"]
    line = (f"https://conda.anaconda.org/bioconda/{NATIVE_LOCK['subdir']}/{NATIVE_LOCK['package']}"
            f"#sha256:{NATIVE_LOCK['package_sha256']}")
    lines = lock.read_text().splitlines()
    assert line in lines
    assert NATIVE_LOCK["package"] == f"bakta-{NATIVE_LOCK['version']}-{NATIVE_LOCK['build']}.conda"
    # Every program Bakta's start-up check runs comes from the lock, built for Apple silicon or noarch.
    for package in ("diamond-2.2.8", "blast-2.17.0", "ncbi-amrfinderplus-4.2.7", "trnascan-se-2.0.13",
                    "infernal-1.1.5", "aragorn-1.2.41", "piler-cr-1.06", "pyrodigal-3.7.1", "pyhmmer-0.12.3"):
        assert any(f"/bioconda/osx-arm64/{package}-" in x for x in lines), package
    # The same Bakta file as the Linux lock (noarch).
    assert line in (ROOT / "docker/conda-locks/bakta/linux-64.lock").read_text().splitlines()


def test_the_entry_runs_bakta_with_the_database_folders_of_arva_conf(mac, tmp_path):
    work_file = tmp_path / "work.json"
    work_file.write_text(json.dumps(work_for(mac)))
    base = [sys.executable, "-I", str(NATIVE), "bakta", "run", "--work", str(work_file), "--data-dir", mac["data"],
            "--executable", mac["exe"]]
    refused = subprocess.run(base, capture_output=True, text=True)
    assert refused.returncode == 3 and json.loads(refused.stdout)["code"] == "database_folder_unknown"
    ran = subprocess.run([*base, "--database-dir", mac["databases"]], capture_output=True, text=True)
    report = json.loads(ran.stdout)
    assert ran.returncode == 0 and report["outcome"] == "exited" and report["exit_code"] == 0, ran.stderr


def test_the_entry_imports_with_the_standard_library_only(tmp_path):
    """Run as ARVA.app runs it (python -I <bundle>/arva_tools/native.py): Bakta's adapter loads without arva_core."""
    code = (f"import runpy, sys; sys.argv = [{str(NATIVE)!r}, 'bakta', '--help']\n"
            f"try:\n    runpy.run_path({str(NATIVE)!r}, run_name='__main__')\nexcept SystemExit:\n    pass\n"
            "print(sorted(m for m in sys.modules if m.startswith(('arva_core', 'arva_tools'))))")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True, cwd=tmp_path)
    loaded = out.stdout.strip().splitlines()[-1]
    assert "arva_tools.bakta" in loaded and "arva_core" not in loaded and "registry" not in loaded


# --- Memory -----------------------------------------------------------------------------------------------------------

def test_the_dmnd_header_gives_letters(tmp_path):
    _dmnd(tmp_path / "x.dmnd", 12, 3456)
    assert diamond_header(tmp_path / "x.dmnd") == {"build": 164, "db_version": 3, "sequences": 12, "letters": 3456}
    (tmp_path / "y.dmnd").write_bytes(b"not a diamond database at all....")
    assert diamond_header(tmp_path / "y.dmnd") is None and diamond_header(tmp_path / "missing.dmnd") is None


def test_the_light_database_fits_and_a_full_block_does_not_in_docker_on_an_8_gb_mac(tmp_path):
    """The user's Mac (Docker with 5.9 GB): the light database 6.0 ran (log item 53), the full one had DIAMOND killed
    (item 49). Bakta's --block-size 3 caps one block at 3 billion letters."""
    light = _bakta_db(tmp_path / "light")
    est = memory_estimate(light, 5.9)
    assert (est["verdict"], est["estimate_gb"], est["largest"]) == ("fits", 2.8, "pscc.dmnd")
    full = _bakta_db(tmp_path / "full")
    _dmnd(full / "psc.dmnd", 90_000_000, 25_000_000_000)
    est = memory_estimate(full, 5.9)
    assert (est["verdict"], est["block_letters"], est["largest"]) == ("may_not_fit", 3_000_000_000, "psc.dmnd")
    assert est["estimate_gb"] == 6.7
    assert memory_estimate(full, 7.5)["verdict"] == "tight"
    assert memory_estimate(full, 16.0)["verdict"] == "fits"
    assert memory_estimate(full, None)["verdict"] == "unknown"
    assert memory_estimate(tmp_path / "nothing", 5.9)["verdict"] == "unknown"


def test_the_measured_factor_is_consistent_with_the_real_light_database():
    """When ARVA's light database 6.0 is on this machine, its header says what DIAMOND 2.2.8 printed."""
    real = Path(os.path.expanduser("~/.arva-db/bakta-light/6.0/pscc.dmnd"))
    if not real.is_file():
        pytest.skip("Bakta light database 6.0 not installed here")
    assert diamond_header(real)["letters"] == bakta_module.DIAMOND_MEASUREMENT["letters"]
