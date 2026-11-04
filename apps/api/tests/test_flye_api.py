"""Flye assembly jobs: request checks, live monitoring, registration, failures, and a real run.

A stand-in executable (Python) behaves like Flye 2.9.3's command line: it prints the real --help, announces the
stages on stderr, and writes the four outputs from recorded fixtures. The end-to-end test runs the real Flye on
the synthetic genome and is skipped without it.
"""
import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from arva_tools import ToolStatus
from arva_tools.registry import detect

from app.db.session import SessionLocal
from app.models import AnalysisJob
from app.tasks import tools as tool_tasks

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "synthetic"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
POD5 = EXAMPLES / "SYNTHETIC_nanopore_signal.pod5"
FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "flye"

FAKE = r'''
import os, shutil, sys, time
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("2.9.3-b1797")
    sys.exit(0)
if args == ["--help"]:
    sys.stdout.write(Path(os.environ["FAKE_FLYE_HELP"]).read_text())
    sys.exit(0)
mode = os.environ.get("FAKE_FLYE_MODE", "ok")
Path(os.environ["FAKE_FLYE_DUMP"]).write_text("\n".join([
    "ARGS=" + "\t".join(args), "CWD=" + os.getcwd(), "HOME=" + os.environ.get("HOME", ""),
    "HELPER=" + str(shutil.which("flye-samtools") or ""),
    "LINKS=" + "\t".join(os.readlink(a) if os.path.islink(a) else "" for a in args[1:args.index("--out-dir")]),
]))
out = Path(args[args.index("--out-dir") + 1])
out.mkdir()
(out / "00-assembly").mkdir()
pause = float(os.environ.get("FAKE_FLYE_PAUSE", "0"))
stages = ["configure", "assembly", "consensus", "repeat", "contigger"]
if args[args.index("--iterations") + 1] != "0":
    stages.append("polishing")
stages.append("finalize")
def say(line):
    sys.stderr.write(f"[2026-10-28 13:37:13] INFO: {line}\n")
    sys.stderr.flush()
say("Starting Flye 2.9.3-b1797")
for stage in stages:
    say(">>>STAGE: " + stage)
    time.sleep(pause)
    if mode == "short" and stage == "configure":
        sys.stderr.write("[2026-10-28 13:47:09] ERROR: No reads above minimum length threshold (1000)\n"
                         "[2026-10-28 13:47:09] ERROR: Pipeline aborted\n")
        sys.exit(1)
    if mode == "oom" and stage == "assembly":
        sys.stderr.write("[2026-10-28 13:47:09] ERROR: Looks like the system ran out of memory\n")
        sys.exit(1)
    if mode == "crash" and stage == "repeat":
        sys.stderr.write("Traceback (most recent call last):\n  boom\n")
        sys.exit(2)
if mode == "no_outputs":
    sys.exit(0)
info = Path(os.environ["FAKE_FLYE_INFO"]).read_text()
rows = [line.split("\t") for line in info.splitlines()[1:] if line.strip()]
if mode == "mismatch":
    rows[0][1] = str(int(rows[0][1]) + 7)
    info = info.splitlines()[0] + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"
(out / "assembly_info.txt").write_text(info)
with open(out / "assembly.fasta", "w") as fa:
    for i, r in enumerate(rows):
        length = int(r[1]) - (7 if mode == "mismatch" and i == 0 else 0)
        fa.write(f">{r[0]}\n" + ("ACGTTGCA" * (length // 8 + 1))[:length] + "\n")
(out / "assembly_graph.gfa").write_text("H\tVN:Z:1.0\n" + "".join(f"S\tedge_{i + 1}\t*\tLN:i:{r[1]}\tdp:i:{r[2]}\n"
                                                                    for i, r in enumerate(rows)))
shutil.copyfile(os.environ["FAKE_FLYE_LOG"], out / "flye.log")
'''


@pytest.fixture
def fake_flye(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "flye"
    exe.write_text(f"#!{sys.executable}\n{FAKE}")
    exe.chmod(0o755)
    samtools = bindir / "samtools"
    samtools.write_text("#!/bin/sh\necho 'samtools 1.19.2'\necho 'Using htslib 1.19'\n")
    samtools.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_FLYE", str(exe))
    monkeypatch.setenv("ARVA_TOOL_SAMTOOLS", str(samtools))
    monkeypatch.setenv("FAKE_FLYE_HELP", str(FIXTURES / "help_2.9.3.txt"))
    monkeypatch.setenv("FAKE_FLYE_INFO", str(FIXTURES / "synthetic150_assembly_info.txt"))
    monkeypatch.setenv("FAKE_FLYE_LOG", str(FIXTURES / "synthetic150_flye.log"))
    monkeypatch.setenv("FAKE_FLYE_DUMP", str(tmp_path / "dump.txt"))
    monkeypatch.setattr(tool_tasks, "MONITOR_SECONDS", 0.05)

    def mode(name="ok", pause=0.0):
        monkeypatch.setenv("FAKE_FLYE_MODE", name)
        monkeypatch.setenv("FAKE_FLYE_PAUSE", str(pause))
        return tmp_path / "dump.txt"

    return mode


def new_sample(client, technology="nanopore"):
    p = client.post(f"{API}/projects", json={"name": "Assembly"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": "ASM-1", "sequencing_technology": technology}).json()


def upload(client, sample_id, path: Path, name: str | None = None):
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (name or path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def start(client, sample, files, params=None, **extra):
    return client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                       json={"raw_file_ids": [f["id"] for f in files], "params": {"read_type": "nano-hq", **(params or {})},
                             **extra})


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def job_dir(storage_root, sample, job_id) -> Path:
    return storage_root / "results" / sample["project_id"] / sample["id"] / job_id


def test_request_checks(client, fake_flye, tmp_path, monkeypatch):
    fake_flye()
    sample = new_sample(client)
    reads = upload(client, sample["id"], ONT)
    pod5 = upload(client, sample["id"], POD5)
    fasta = upload(client, sample["id"], tmp_path.joinpath("c.fasta").write_text(">c\nACGT\n") and tmp_path / "c.fasta")
    mate = upload(client, sample["id"], R1)
    assert mate["read_mate"] == "R1"
    for files, message in (([pod5], "holds no reads, so Flye cannot use it"), ([fasta], "is not a FASTQ file"),
                           ([mate], "marked as read R1 of a pair")):
        r = start(client, sample, files)
        assert r.status_code == 400 and message in r.json()["detail"], r.text
    other = new_sample(client)
    assert "does not belong" in start(client, other, [reads]).json()["detail"]

    r = start(client, sample, [reads], {"read_type": "pacbio-hifi"})
    assert r.status_code == 400 and "is for pacbio reads, but this sample's sequencing technology is 'nanopore'" in r.text
    r = start(client, sample, [reads], {"asm_coverage": 40})
    assert r.status_code == 422 and "asm_coverage requires genome_size_bp" in r.json()["detail"]
    r = start(client, sample, [reads], {"genome_size_bp": 5_000_000})
    assert r.status_code == 422 and "needs its basis" in r.json()["detail"]
    r = start(client, sample, [reads], {"genome_size_bp": 5_000_000, "genome_size_basis": "expected_genome_size"})
    assert r.status_code == 400 and "expected genome size is not known (not given)" in r.json()["detail"]
    r = start(client, sample, [reads], {"genome_size_bp": 5_000_000, "genome_size_basis": "reads_over_depth",
                                        "assumed_depth_x": 50})
    assert r.status_code == 400 and "needs ARVA read statistics for every selected file" in r.json()["detail"]

    unknown = new_sample(client, technology="unknown")
    f = upload(client, unknown["id"], ONT)
    r = start(client, unknown, [f])
    assert r.status_code == 400 and "confirm that the selected files contain long reads" in r.json()["detail"]
    illumina = new_sample(client, technology="illumina")
    r = start(client, illumina, [upload(client, illumina["id"], ONT)], long_reads_confirmed=True)
    assert r.status_code == 400 and "technology is 'illumina'" in r.json()["detail"]

    # An option this Flye's --help does not list is refused before anything runs.
    old_help = tmp_path / "help.txt"
    old_help.write_text((FIXTURES / "help_2.9.3.txt").read_text().replace("--no-alt-contigs", "--no-alt-xxx"))
    monkeypatch.setenv("FAKE_FLYE_HELP", str(old_help))
    r = start(client, sample, [reads], {"no_alt_contigs": True})
    assert r.status_code == 422 and "does not offer --no-alt-contigs" in r.json()["detail"]

    monkeypatch.setenv("ARVA_TOOL_FLYE", str(tmp_path / "missing"))
    r = start(client, sample, [reads])
    assert r.status_code == 409 and "Flye is not available" in r.json()["detail"]


def test_assembly_job_records_everything_and_cleans_up(client, fake_flye, storage_root):
    dump = fake_flye()
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT, name="run 1 pass.fastq.gz")
    r = start(client, sample, [f], {"iterations": 2, "min_overlap": 3000, "meta": True, "threads": 99})
    assert r.status_code == 202, r.text
    detail = job(client, r.json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    assert (detail["job_type"], detail["tool_name"], detail["tool_version"]) == ("flye_assembly", "Flye", "2.9.3")
    p = detail["parameters"]
    assert (p["read_type"], p["iterations"], p["min_overlap"], p["meta"], p["threads"]) == ("nano-hq", 2, 3000, True, 4)
    assert p["arva_read_type_suggestion"]["platform"] == "nanopore" and p["sequencing_technology"] == "nanopore"

    results = job_dir(storage_root, sample, detail["id"])
    seen = dict(line.split("=", 1) for line in dump.read_text().splitlines())
    argv = seen["ARGS"].split("\t")
    assert argv == ["--nano-hq", str(results / "input" / "01_run_1_pass.fastq.gz"), "--out-dir", str(results / "flye"),
                    "--threads", "4", "--iterations", "2", "--min-overlap", "3000", "--meta"]
    assert detail["commands"] == [[detail["tool_path"], *argv]]
    assert seen["CWD"] == str(results) and seen["HOME"] != os.environ.get("HOME")
    # Flye's Debian package lacks flye-samtools: ARVA links it to samtools for the run.
    assert seen["HELPER"] == str(results / "helper-bin" / "flye-samtools")
    with SessionLocal() as db:
        from app.models import RawFile
        from app.storage import get_storage
        assert seen["LINKS"] == str(get_storage().resolve(db.get(RawFile, f["id"]).stored_path))
    assert "ARVA linked it to" in detail["log_text"] and "(samtools 1.19.2)" in detail["log_text"]
    assert detail["result_summary"]["helpers"] == [{"name": "flye-samtools", "provided_by": "arva_link",
                                                    "executable": os.environ["ARVA_TOOL_SAMTOOLS"],
                                                    "samtools_version": "1.19.2"}]

    # Monitoring: every stage is logged and the final progress is stored.
    for n, stage in enumerate(["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"], 1):
        assert f"Flye stage {n}/7: {stage}" in detail["log_text"]
    prog = detail["progress"]
    assert (prog["tool"], prog["stage"], prog["stage_index"], prog["stages_total"], prog["finished"]) == (
        "Flye", "finalize", 7, 7, True)
    assert prog["elapsed_seconds"] >= 0 and prog["stages"][-1] == "finalize"

    # Only the four Flye outputs and its stderr log are kept; stage folders, links and the helper are removed.
    assert sorted(p.name for p in results.iterdir()) == [
        "assembly.fasta", "assembly_graph.gfa", "assembly_info.txt", "flye.log", "flye.stderr.log"]
    assert sorted(Path(p).name for p in detail["output_paths"]) == sorted(p.name for p in results.iterdir())

    s = detail["result_summary"]
    assert s["log"]["min_overlap"] == 4000 and s["log"]["alignment_error_rate"]["polishing"] == 0.04064
    assert [(c["name"], c["multiplicity"], c["graph_path"]) for c in s["contigs"]] == [("contig_1", 1, "1"),
                                                                                      ("contig_2", 2, "2")]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert a["id"] == s["assembly_id"] and a["input_file_ids"] == [f["id"]]
    assert (a["assembler"], a["assembler_version"], a["mode"], a["read_type"]) == ("Flye", "2.9.3", "long", "nano-hq")
    assert (a["stats"]["contig_count"], a["stats"]["total_length"]) == (2, 165_001)
    assert a["stats"]["circularity"] == {"contigs_with_circularity": 2, "circular_contigs": 2}
    contigs = client.get(f"{API}/assemblies/{a['id']}").json()["contigs"]
    assert [(c["name"], c["coverage"], c["circular"], c["repeat"]) for c in contigs] == [
        ("contig_1", 52.0, True, False), ("contig_2", 95.0, True, False)]
    assert client.get(f"{API}/assemblies/{a['id']}/graph").json()["segment_count"] == 2
    report = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    step = next(st for st in report["processing"] if st["job_type"] == "flye_assembly")
    assert step["highlights"][:2] == ["Assembly (nano-hq): 2 contigs, 165,001 bp, N50 150,001 bp, largest 150,001 bp; "
                                      "2 reported circular by Flye", "Minimum overlap 3,000 bp (set by the user)"]

    log = client.get(f"{API}/jobs/{detail['id']}/log", params={"tail": 3})
    assert log.status_code == 200 and log.headers["x-arva-log-source"] == "tool"
    assert log.headers["x-arva-log-name"] == "flye.stderr.log" and log.text.endswith(">>>STAGE: finalize")
    assert len(log.text.splitlines()) == 3
    assert client.get(f"{API}/jobs/{detail['id']}/log", params={"tail": 0}).status_code == 422
    assert client.get(f"{API}/jobs/{detail['id']}/log", params={"tail": 5001}).status_code == 422


def test_progress_is_saved_while_flye_runs(client, fake_flye, monkeypatch):
    fake_flye(pause=0.25)
    snapshots = []
    original = tool_tasks._StageMonitor.__call__

    def spy(self, finished=False):
        original(self, finished)
        # Read back through another session: the progress has been committed, not just set.
        with SessionLocal() as db:
            snapshots.append(dict(db.get(AnalysisJob, self.ctx.job.id).progress))

    monkeypatch.setattr(tool_tasks._StageMonitor, "__call__", spy)
    sample = new_sample(client)
    r = start(client, sample, [upload(client, sample["id"], ONT)], {"iterations": 0})
    assert job(client, r.json()["id"])["status"] == "completed"
    stages = [s["stage"] for s in snapshots]
    assert stages[0] is None and snapshots[-1]["finished"] is True
    assert {"assembly", "consensus", "repeat"} <= set(stages)
    assert all(s["stages_total"] == 6 and "polishing" not in s["stages"] for s in snapshots)
    indices = [s["stage_index"] for s in snapshots if s["stage_index"]]
    assert indices == sorted(indices) and indices[-1] == 6
    elapsed = [s["elapsed_seconds"] for s in snapshots]
    assert elapsed == sorted(elapsed) and elapsed[-1] > 1


def test_log_of_a_running_job_and_its_bounds(client, storage_root):
    p = client.post(f"{API}/projects", json={"name": "Log"}).json()
    sample = client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "L"}).json()
    with SessionLocal() as db:
        j = AnalysisJob(project_id=p["id"], sample_id=sample["id"], job_type="flye_assembly", tool_name="Flye",
                        tool_version="2.9.3", status="running", log_text="ARVA line 1\nARVA line 2")
        db.add(j)
        db.commit()
        job_id = j.id
    live = job_dir(storage_root, sample, job_id) / "flye.stderr.log"
    live.parent.mkdir(parents=True)
    live.write_text("".join(f"line {i}\n" for i in range(10_000)))

    def set_log(rel):
        with SessionLocal() as db:
            db.get(AnalysisJob, job_id).progress = {"tool": "Flye", "log": rel}
            db.commit()

    set_log(str(live.relative_to(storage_root)))
    r = client.get(f"{API}/jobs/{job_id}/log")
    assert r.headers["x-arva-log-source"] == "tool" and r.text.splitlines() == [f"line {i}" for i in range(9800, 10_000)]
    assert r.headers["cache-control"] == "no-store" and r.headers["content-type"].startswith("text/plain")
    # A log path outside the job's own results folder is never read.
    outside = storage_root / "results" / "elsewhere.log"
    outside.write_text("secret\n")
    for rel in ("results/elsewhere.log", f"results/{p['id']}/{sample['id']}/{job_id}/../../elsewhere.log", "/etc/passwd"):
        set_log(rel)
        r = client.get(f"{API}/jobs/{job_id}/log")
        assert r.headers["x-arva-log-source"] == "job" and r.text == "ARVA line 1\nARVA line 2"
    assert client.get(f"{API}/jobs/nope/log").status_code == 404


@pytest.mark.parametrize("mode, message", [
    ("short", "Flye found no read longer than the minimum overlap (No reads above minimum length threshold (1000))"),
    ("oom", "Flye ran out of memory during the assembly stage"),
    ("crash", "flye exited with status 2"),
    ("no_outputs", "Flye exited without an error but did not write assembly.fasta, assembly_graph.gfa, "
                   "assembly_info.txt, flye.log"),
    ("mismatch", "assembly_info.txt does not describe the contigs in assembly.fasta"),
])
def test_failures_are_explained_and_leave_nothing(client, fake_flye, storage_root, mode, message):
    fake_flye(mode)
    sample = new_sample(client)
    r = start(client, sample, [upload(client, sample["id"], ONT)])
    detail = job(client, r.json()["id"])
    assert detail["status"] == "failed" and message in detail["error_message"], detail["error_message"]
    assert not job_dir(storage_root, sample, detail["id"]).exists()
    assert client.get(f"{API}/samples/{sample['id']}/assemblies").json() == []
    assert detail["progress"]["finished"] is True
    log = client.get(f"{API}/jobs/{detail['id']}/log")
    assert log.headers["x-arva-log-source"] == "job" and "ERROR:" in log.text
    # Flye's known reasons carry a code and parameters, so the interface shows them in its own language.
    codes = {"short": ("flye_no_long_reads", {"stage": "configure"}),
             "oom": ("flye_out_of_memory", {"stage": "assembly", "need_gb": 9})}
    if mode in codes:
        code, params = codes[mode]
        assert detail["error_detail"]["code"] == code
        assert params.items() <= detail["error_detail"]["params"].items(), detail["error_detail"]
    if mode == "short":
        assert detail["progress"]["stage"] == "configure"
        assert "Flye output (last lines):" in detail["log_text"] and "Pipeline aborted" in detail["log_text"]


def test_flye_2_9_6_offers_every_optional_option(client, fake_flye, monkeypatch):
    """The installed Flye 2.9.6's real --help (fixture identical to `flye --help` of the Bioconda 2.9.6 build) lists
    --asm-coverage and --genome-size, so the dialog enables those fields (registro de prueba, item 27)."""
    from app.services.flye import OPTIONAL_OPTIONS

    fake_flye()
    monkeypatch.setenv("FAKE_FLYE_HELP", str(FIXTURES / "help_2.9.6.txt"))
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/flye/preview", json={"raw_file_ids": [f["id"]]}).json()
    assert plan["tool"]["options"] == list(OPTIONAL_OPTIONS)
    assert "--asm-coverage" in plan["tool"]["options"] and "--genome-size" in plan["tool"]["options"]


def test_preview_suggests_and_estimates_without_deciding(client, fake_flye):
    fake_flye()
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    url = f"{API}/samples/{sample['id']}/assembly/flye/preview"
    plan = client.post(url, json={"raw_file_ids": [f["id"]]}).json()
    assert plan["tool"]["status"] == "available" and plan["tool"]["reason"] == "samtools_linked"
    assert "--no-alt-contigs" in plan["tool"]["options"] and plan["tool"]["max_threads"] == 4
    assert plan["read_type_suggestion"] == {
        "heuristic": True, "value": None, "basis": "no_quality_or_model", "platform": "nanopore",
        "platform_source": "sample_metadata", "mean_error_rate": None, "mean_base_quality": None,
        "read_error": None, "q20_read_error_note": False, "sup_model_but_low_quality": False}
    assert plan["genome_size"]["total_read_bases"] is None and plan["genome_size"]["files_without_stats"] == [ONT.name]

    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                json={"raw_file_ids": [f["id"]], "expected_genome_size_bp": 300_000})
    plan = client.post(url, json={"raw_file_ids": [f["id"]], "assumed_depth_x": 4}).json()
    (e,) = plan["files"]
    assert (e["total_bases"], e["max_read_length"]) == (1_513_780, e["max_read_length"]) and e["stats_job_id"]
    s = plan["read_type_suggestion"]
    assert s["value"] == ("nano-hq" if s["mean_error_rate"] <= 0.05 else "nano-raw")
    assert s["mean_base_quality"] == pytest.approx(e["mean_base_quality"])
    g = plan["genome_size"]
    assert g["expected"] == {"bp": 300_000, "status": "given", "source": "read_statistics", "basis": None,
                             "assumed_depth_x": None}
    assert g["from_depth"] == {"depth_x": 4.0, "total_read_bases": 1_513_780, "bp": 378_445}
    assert plan["long_reads_confirmation_required"] is False

    # The estimate is checked when the run is requested, and recorded with its basis.
    r = start(client, sample, [f], {"genome_size_bp": 378_444, "genome_size_basis": "reads_over_depth",
                                    "assumed_depth_x": 4})
    assert r.status_code == 400 and "= 378,445 bp, not 378,444 bp" in r.json()["detail"]
    r = start(client, sample, [f], {"genome_size_bp": 378_445, "genome_size_basis": "reads_over_depth",
                                    "assumed_depth_x": 4})
    detail = job(client, r.json()["id"])
    assert "--genome-size" in detail["commands"][0] and "378445" in detail["commands"][0]
    assert "total read bases ÷ an assumed depth of 4×" in detail["log_text"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert a["stats"]["expected_genome_size"] == {"bp": 378_445, "status": "given", "source": "assembly_parameters",
                                                  "basis": "reads_over_depth", "assumed_depth_x": 4.0}

    pod5 = upload(client, sample["id"], POD5)
    assert client.post(url, json={"raw_file_ids": [pod5["id"]]}).status_code == 400


# --- Real Flye --------------------------------------------------------------------------------

def flye_ready():
    return detect("flye", refresh=True).status is ToolStatus.available


@pytest.mark.skipif(not flye_ready(), reason="needs Flye (with samtools)")
def test_flye_assembles_the_synthetic_genome(client, tmp_path, storage_root):
    """The default synthetic genome (300 kb circular chromosome with a 5 kb repeat in two copies, 15 kb plasmid
    at two copies) with Nanopore-like reads at 30x and a 2% mean error, within --nano-hq's range in Flye 2.9.3
    (< 5%) and 2.9.6 (R10, < 3%). Flye 2.9.3 and 2.9.6, 2 threads: both replicons circular at their lengths (within
    10 bp), the plasmid at multiplicity 2. With the generator's default 4% error, Flye 2.9.6 assembled the plasmid
    as a 30,027 bp dimer (see workflows/tool-adapters/tests/test_real_tools.py)."""
    data = tmp_path / "genome"
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_synthetic_genome.py"), str(data),
                    "--ont-depth", "30", "--illumina-depth", "1", "--ont-error-rate", "0.02"],
                   check=True, capture_output=True)
    sample = new_sample(client)
    f = upload(client, sample["id"], data / "ont.fastq.gz")
    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={"raw_file_ids": [f["id"]]})
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/flye/preview",
                       json={"raw_file_ids": [f["id"]], "assumed_depth_x": 30}).json()
    # Calibrated qualities, about 2 % errors: below Flye's limit for --nano-hq (5 % in 2.9.3, 3 % in 2.9.6).
    assert plan["read_type_suggestion"]["value"] == "nano-hq"
    genome = plan["genome_size"]["from_depth"]["bp"]
    r = start(client, sample, [f], {"genome_size_bp": genome, "genome_size_basis": "reads_over_depth",
                                    "assumed_depth_x": 30, "threads": 2})
    assert r.status_code == 202, r.text
    detail = job(client, r.json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    assert detail["progress"]["stage"] == "finalize" and detail["progress"]["stage_index"] == 7
    assert detail["result_summary"]["log"]["stages_seen"] == list(detail["progress"]["stages"])

    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    rows = {c["name"]: c for c in detail["result_summary"]["contigs"]}
    contigs = sorted(client.get(f"{API}/assemblies/{a['id']}").json()["contigs"], key=lambda c: -c["length"])
    assert len(contigs) == 2 and all(c["circular"] for c in contigs)
    chromosome, plasmid = contigs
    assert abs(chromosome["length"] - 300_000) <= 10 and abs(plasmid["length"] - 15_000) <= 10
    assert rows[plasmid["name"]]["multiplicity"] == 2 and 1.5 <= plasmid["coverage"] / chromosome["coverage"] <= 2.5
    assert a["warnings"] == []

    # Flye writes one GFA path (P line) per contig: each replicon is a segment that belongs to its circular
    # contig and is linked to itself, and its coverage tag is dp.
    g = client.get(f"{API}/assemblies/{a['id']}/graph").json()
    assert g["coverage_tag"] == "dp" and g["path_count"] == 2
    by_contig = {n["paths"][0]: n for n in g["nodes"]}
    assert set(by_contig) == {chromosome["name"], plasmid["name"]}
    assert all(n["circular"] is True and len(n["paths"]) == 1 for n in g["nodes"])
    # Flye flags the plasmid's segment, at multiplicity 2, as a repeat (2.9.3 and 2.9.6 alike on these reads).
    assert by_contig[chromosome["name"]]["repeat"] is False
    assert {e["source"] for e in g["edges"] if e["source"] == e["target"]} == {n["id"] for n in g["nodes"]}

    # Compare with the true genome: shared 31-mers on either strand.
    def seqs(path):
        opener = gzip.open if str(path).endswith(".gz") else open
        out, name = {}, None
        with opener(path, "rt") as fh:
            for line in fh:
                if line.startswith(">"):
                    name = line[1:].split()[0]
                    out[name] = []
                else:
                    out[name].append(line.strip())
        return {k: "".join(v) for k, v in out.items()}

    def kmers(s, k=31):
        return {s[i:i + k] for i in range(len(s) - k + 1)}

    ref = "".join(seqs(data / "reference.fasta").values())
    comp = str.maketrans("ACGT", "TGCA")
    truth = kmers(ref) | kmers(ref.translate(comp)[::-1])
    assembled = seqs(storage_root / a["contigs_path"])
    for c in contigs:
        found = kmers(assembled[c["name"]])
        assert len(found & truth) / len(found) >= 0.99, c["name"]
    shutil.rmtree(data)


def test_memory_estimate_in_the_preview_the_job_and_the_workflow_guard(client, fake_flye, monkeypatch):
    """ARVA's estimate (Flye's documented E. coli figure, scaled) is in the preview and recorded on the job; the
    workflow guard adds --asm-coverage only when the estimate may not fit, and never over the user's own value."""
    import arva_tools.flye as adapter

    from app.services import workflow_nodes as nodes

    fake_flye()
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    url = f"{API}/samples/{sample['id']}/assembly/flye/preview"
    m = client.post(url, json={"raw_file_ids": [f["id"]]}).json()["memory"]
    assert m["verdict"] == "unknown" and m["reference"]["ram_gb"] == 2.0 and m["reference_bases"] == 230_000_000
    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                json={"raw_file_ids": [f["id"]], "expected_genome_size_bp": 300_000})
    m = client.post(url, json={"raw_file_ids": [f["id"]]}).json()["memory"]
    # Flye's fixed k-mer table (about 8.6 GB) is the estimate for these few reads; this test machine has more.
    assert m["verdict"] == "fits" and m["read_bases"] == 1_513_780 and m["scaled_gb"] == 0.01
    assert m["estimate_gb"] == m["floor_gb"] == 8.6 and m["available_gb"] == m["container_memory_gb"]
    assert m["available_gb"] >= 1 and m["expected_genome_size_bp"] == 300_000 and m["suggestion"] is None

    r = start(client, sample, [f])
    params = job(client, r.json()["id"])["parameters"]
    assert params["memory_estimate"]["verdict"] == "fits" and "reference" not in params["memory_estimate"]

    with SessionLocal() as db:
        from app.models import Sample

        s = db.get(Sample, sample["id"])
        base = {"read_type": "nano-hq", "iterations": 1}
        assert nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "auto")["applied"] is None
        # Pretend Flye's documented figure were 10,000 times larger: these reads would then not fit.
        monkeypatch.setitem(adapter.MEMORY_REFERENCE, "ram_gb", 20_000.0)
        off = nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "off")
        assert off["estimate"]["verdict"] == "may_not_fit" and off["applied"] is None and off["not_applied"] is None
        # 40x of the expected 300 kb (12 Mb) is more than the 1.5 Mb of reads: --asm-coverage would not use fewer
        # bases, so the guard adds nothing and says why.
        below = nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "auto")
        assert below["applied"] is None and below["not_applied"] == "reads_below_asm_coverage"
        # With a coverage that does cut the reads (4x of 300 kb = 1.2 Mb), the expected size is added with it.
        monkeypatch.setattr(adapter, "SUGGESTED_ASM_COVERAGE", 4)
        on = nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "auto")
        assert on["applied"] == {"asm_coverage": 4, "genome_size_bp": 300_000,
                                 "genome_size_basis": "expected_genome_size", "assumed_depth_x": None}
        assert on["estimate_after"]["bases_used"] == 1_200_000
        monkeypatch.setattr(adapter, "SUGGESTED_ASM_COVERAGE", 40)
        own = nodes.flye_memory_guard(db, s, [f["id"]], {**base, "asm_coverage": 30, "genome_size_bp": 300_000},
                                      "auto")
        assert own["applied"] is None and own["not_applied"] == "asm_coverage_set"
        meta = nodes.flye_memory_guard(db, s, [f["id"]], {**base, "meta": True}, "auto")
        assert meta["not_applied"] == "meta"
        sized = nodes.flye_memory_guard(db, s, [f["id"]], {**base, "genome_size_bp": 30_000,
                                                           "genome_size_basis": "entered"}, "auto")
        assert sized["applied"] == {"asm_coverage": 40} and sized["estimate_after"]["bases_used"] == 1_200_000

        # In a batch the estimate is compared with the memory the batch reserves per job (other jobs may run beside
        # it), capped by what ARVA can use: about 2 GB fits a whole computer's memory but not 1 GB per job.
        monkeypatch.setitem(adapter.MEMORY_REFERENCE, "ram_gb", 304.0)
        per_job = nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "off", memory_gb=1)
        assert per_job["estimate"]["available_gb"] == 1 and per_job["estimate"]["verdict"] == "below_floor"
        # Below Flye's fixed k-mer floor --asm-coverage cannot help: the guard adds nothing and says why.
        floor = nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "auto", memory_gb=1)
        assert floor["applied"] is None and floor["not_applied"] == "below_kmer_floor"
        from app.services.flye import container_memory_gb
        from app.services.performance import effective_resources

        # A batch share larger than the container is capped by what the container has.
        whole = nodes.flye_memory_guard(db, s, [f["id"]], dict(base), "off", memory_gb=10_000)
        assert whole["estimate"]["available_gb"] == container_memory_gb(effective_resources(db))


def test_memory_estimate_compares_with_the_container_memory_not_a_profile_share(client, fake_flye):
    """The user's Mac: 5.9 GB in the Docker container. Flye takes no memory limit, so the verdict compares the
    estimate (never below Flye's fixed k-mer floor) with what the container has, and says Flye cannot run there."""
    from dataclasses import replace

    from app.services import flye
    from app.services.performance import effective_resources

    fake_flye()
    sample = new_sample(client)
    f = upload(client, sample["id"], ONT)
    with SessionLocal() as db:
        from app.models import RawFile, Sample

        s = db.get(Sample, sample["id"])
        ev = flye.evidence(db, [db.get(RawFile, f["id"])])
        res = effective_resources(db)
        mac = replace(res, usable_memory_gb=5.9, max_memory_gb=5, memory_gb=2, memory_known=True)
        m = flye.memory(db, s, ev, None, mac)
        assert m["available_gb"] == m["container_memory_gb"] == 5.9 and m["verdict"] == "below_floor"
        assert m["suggestion"] is None and m["floor"]["kmer_size"] == 17
        roomy = flye.memory(db, s, ev, None, replace(res, usable_memory_gb=15.6, max_memory_gb=4))
        assert roomy["available_gb"] == 15.6 and roomy["verdict"] == "unknown"  # no read statistics yet
        unread = flye.memory(db, s, ev, None, replace(res, memory_known=False))
        assert unread["available_gb"] is None and unread["verdict"] == "unknown"
