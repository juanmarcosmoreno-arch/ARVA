"""SPAdes and Unicycler assembly jobs: request checks by role and technology, monitoring, registration, failures,
and real runs.

Stand-in executables (Python) behave like SPAdes 3.15.5 and Unicycler 0.5.0 on the command line: they print the
real help texts, announce stages as the real tools do, and write outputs shaped like the recorded fixtures. The
end-to-end tests run the real tools on a small synthetic genome and are skipped without them.
"""
import gzip
import os
import subprocess
import sys
from pathlib import Path

import pytest
from arva_tools import ToolStatus
from arva_tools.registry import detect
from arva_tools.unicycler import helper_paths, modes_available

from app.core.config import get_settings
from app.tasks import tools as tool_tasks

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
POD5 = EXAMPLES / "SYNTHETIC_nanopore_signal.pod5"
FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures"

FAKE_SPADES = r'''
import gzip, os, sys, time
from pathlib import Path

F = Path(os.environ["FAKE_FIXTURES"]) / "spades"
args = sys.argv[1:]
if args in (["--version"], ["-v"]):
    print("SPAdes genome assembler v3.15.5")
    sys.exit(0)
if args == ["--help"]:
    sys.stdout.write(Path(os.environ["FAKE_SPADES_HELP"]).read_text())
    sys.exit(0)
Path(os.environ["FAKE_SPADES_DUMP"]).write_text("\n".join([
    "ARGS=" + "\t".join(args), "CWD=" + os.getcwd(), "HOME=" + os.environ.get("HOME", ""),
    "LINKS=" + "\t".join(os.readlink(a) for a in args if os.path.islink(a)),
]))
mode = os.environ.get("FAKE_SPADES_MODE", "ok")
out = Path(args[args.index("-o") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "K21").mkdir(exist_ok=True)
(out / "run_spades.yaml").write_text((F / "isolate_paired.run_spades.yaml").read_text())
log = gzip.open(F / "isolate_paired.spades.log.gz", "rt").read()
def say(line):
    print(line, flush=True)
if mode == "oom":
    text = "===== Before start started. \n===== Assembling started. \n===== K21 started. \n" + \
        (F / "memory_limit.spades.log").read_text()
    (out / "spades.log").write_text(text)
    say(text)
    sys.exit(12)
for line in log.splitlines():
    if line.startswith("====="):
        say(line)
        time.sleep(float(os.environ.get("FAKE_SPADES_PAUSE", "0")))
if mode == "crash":
    sys.exit(3)
if mode == "no_outputs":
    sys.exit(0)
(out / "spades.log").write_text(log)
(out / "params.txt").write_text((F / "isolate_paired.params.txt").read_text())
headers = [h[1:] for h in (F / "isolate_paired.contigs_headers.txt").read_text().split()]
if mode == "badname":
    headers[0] = "contig_1"
for name in ("contigs.fasta", "scaffolds.fasta"):
    with open(out / name, "w") as fa:
        for i, h in enumerate(headers):
            n = int(h.split("_")[3]) if h.startswith("NODE_") else 500
            n -= 7 if mode == "mismatch" and i == 0 else 0
            fa.write(f">{h}\n" + ("ACGTTGCA" * (n // 8 + 1))[:n] + "\n")
with open(out / "assembly_graph_with_scaffolds.gfa", "w") as g:
    g.write("H\tVN:Z:1.0\n")
    for i, h in enumerate(headers):
        n = int(h.split("_")[3]) if h.startswith("NODE_") else 500
        g.write(f"S\t{i + 1}\t*\tLN:i:{n}\tDP:f:{h.rsplit('_', 1)[-1] if h.startswith('NODE_') else 1}\tKC:i:10\n")
        g.write(f"P\t{h}_1\t{i + 1}+\t*\n")
'''

FAKE_UNICYCLER = r'''
import os, sys, time
from pathlib import Path

F = Path(os.environ["FAKE_FIXTURES"]) / "unicycler"
args = sys.argv[1:]
if args == ["--version"]:
    print("Unicycler v0.5.0")
    sys.exit(0)
if args == ["--help_all"]:
    sys.stdout.write(Path(os.environ["FAKE_UNICYCLER_HELP"]).read_text())
    sys.exit(0)
Path(os.environ["FAKE_UNICYCLER_DUMP"]).write_text("\n".join([
    "ARGS=" + "\t".join(args), "HOME=" + os.environ.get("HOME", ""),
    "LINKS=" + "\t".join(os.readlink(a) for a in args if os.path.islink(a)),
]))
mode = os.environ.get("FAKE_UNICYCLER_MODE", "ok")
kind = "hybrid" if "-l" in args and ("-1" in args or "-s" in args) else "long" if "-l" in args else "short"
out = Path(args[args.index("-o") + 1])
out.mkdir(parents=True)
log = (F / f"{kind}.unicycler.log").read_text()
with open(out / "unicycler.log", "w") as fh:
    for line in log.splitlines():
        fh.write(line + "\n")
        fh.flush()
        if line.endswith(")") and " (2026-" in line:
            print("\x1b[1m\x1b[4m" + line.split(" (")[0] + "\x1b[0m (" + line.split(" (")[1], flush=True)
            time.sleep(float(os.environ.get("FAKE_UNICYCLER_PAUSE", "0")))
        if mode == "spades_oom" and line.startswith("SPAdes assemblies"):
            (out / "spades_assembly").mkdir()
            (out / "spades_assembly" / "spades.log").write_text((F / "memory_limit.spades_assembly.spades.log").read_text())
            sys.stderr.write("Error: SPAdes encountered an error:\n\n")
            sys.exit(1)
if mode == "no_outputs":
    sys.exit(0)
if args[args.index("--keep") + 1] == "1":
    (out / "002_depth_filter.gfa").write_text("H\tVN:Z:1.0\n")
headers = [h[1:] for h in (F / f"{kind}.assembly_headers.txt").read_text().splitlines()]
if kind == "long":
    gfa = (F / "long.assembly_noseq.gfa").read_text()
    lengths = {"1": 99996, "2": 8000}
else:
    gfa = "".join(f"S\t{h.split()[0]}\t*\tLN:i:{h.split('length=')[1].split()[0]}\tdp:f:1.0\n" for h in headers)
    lengths = {h.split()[0]: int(h.split("length=")[1].split()[0]) for h in headers}
(out / "assembly.gfa").write_text(gfa)
with open(out / "assembly.fasta", "w") as fa:
    for i, h in enumerate(headers):
        n = lengths[h.split()[0]] - (5 if mode == "mismatch" and i == 0 else 0)
        fa.write(f">{h}\n" + ("ACGGTCAT" * (n // 8 + 1))[:n] + "\n")
'''


def _exe(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    spades = _exe(bindir / "spades.py", f"#!{sys.executable}\n{FAKE_SPADES}")
    unicycler = _exe(bindir / "unicycler", f"#!{sys.executable}\n{FAKE_UNICYCLER}")
    helpers = {name: _exe(bindir / name, "#!/bin/sh\nexit 0\n") for name in ("racon", "makeblastdb", "tblastn")}
    monkeypatch.setenv("ARVA_TOOL_SPADES", str(spades))
    monkeypatch.setenv("ARVA_TOOL_UNICYCLER", str(unicycler))
    for name, path in helpers.items():
        monkeypatch.setenv(f"ARVA_TOOL_{name.upper()}", str(path))
    monkeypatch.setenv("FAKE_FIXTURES", str(FIXTURES))
    monkeypatch.setenv("FAKE_SPADES_HELP", str(FIXTURES / "spades" / "help_3.15.5.txt"))
    monkeypatch.setenv("FAKE_UNICYCLER_HELP", str(FIXTURES / "unicycler" / "help_all_0.5.0.txt"))
    monkeypatch.setenv("FAKE_SPADES_DUMP", str(tmp_path / "spades_dump.txt"))
    monkeypatch.setenv("FAKE_UNICYCLER_DUMP", str(tmp_path / "unicycler_dump.txt"))
    monkeypatch.setattr(tool_tasks, "MONITOR_SECONDS", 0.05)
    monkeypatch.setattr(get_settings(), "tool_memory_gb", 32)

    def mode(spades="ok", unicycler="ok"):
        monkeypatch.setenv("FAKE_SPADES_MODE", spades)
        monkeypatch.setenv("FAKE_UNICYCLER_MODE", unicycler)

    mode()
    return {"mode": mode, "dir": tmp_path, "spades": spades, "helpers": helpers}


def dump(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def new_sample(client, technology="illumina"):
    p = client.post(f"{API}/projects", json={"name": "Short"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": "SR-1", "sequencing_technology": technology}).json()


def upload(client, sample_id, path: Path, name: str | None = None):
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (name or path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def stats(client, sample, files):
    r = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={"raw_file_ids": [f["id"] for f in files]})
    assert r.status_code in (200, 202), r.text


def spades(client, sample, roles, params=None, **extra):
    return client.post(f"{API}/samples/{sample['id']}/assembly/spades",
                       json={"inputs": {f"{k}_file_id": v["id"] for k, v in roles.items()}, "params": params or {},
                             **extra})


def unicycler(client, sample, roles, params=None, **extra):
    return client.post(f"{API}/samples/{sample['id']}/assembly/unicycler",
                       json={"inputs": {f"{k}_file_id": v["id"] for k, v in roles.items()}, "params": params or {},
                             **extra})


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def job_dir(storage_root, sample, job_id) -> Path:
    return storage_root / "results" / sample["project_id"] / sample["id"] / job_id


def fastq(path: Path, n: int, length: int = 150) -> Path:
    with gzip.open(path, "wt") as fh:
        for i in range(n):
            fh.write(f"@SYNTHETIC_{i} 1:N:0:1\n{'ACGT' * (length // 4)}\n+\n{'I' * (length // 4 * 4)}\n")
    return path


# --- SPAdes ------------------------------------------------------------------------------------------------

def test_spades_request_checks(client, fakes, tmp_path, monkeypatch):
    sample = new_sample(client)
    r1, r2 = upload(client, sample["id"], R1), upload(client, sample["id"], R2)
    ont, pod5 = upload(client, sample["id"], ONT), upload(client, sample["id"], POD5)
    stats(client, sample, [r1, r2, ont])
    fasta = upload(client, sample["id"], tmp_path.joinpath("c.fasta").write_text(">c\nACGT\n") and tmp_path / "c.fasta")
    for roles, message in (
        ({"r1": r1}, "need both the R1 and the R2 file"),
        ({"r1": r2, "r2": r1}, "marked as read R2 of a pair, so it cannot be the R1"),
        ({"unpaired": ont}, "short reads are at most 1,000 bp, so it cannot be the unpaired short reads"),
        ({"unpaired": pod5}, "holds no reads"),
        ({"unpaired": fasta}, "is not a FASTQ file"),
        ({"r1": r1, "r2": r1}, "The same file was given for more than one role"),
        ({}, "Choose the reads for SPAdes"),
    ):
        r = spades(client, sample, roles)
        assert r.status_code == 400 and message in r.json()["detail"], (roles, r.text)
    r = client.post(f"{API}/samples/{sample['id']}/assembly/spades",
                    json={"inputs": {"r1_file_id": r1["id"], "r2_file_id": r2["id"], "long_file_id": ont["id"]}})
    assert r.status_code == 422  # SPAdes takes no long-read role
    other = new_sample(client)
    assert "does not belong to this sample" in spades(client, other, {"unpaired": r1}).json()["detail"]

    for params, message in (({"k": [21, 32]}, "every k must be odd"), ({"k": [55, 33]}, "ascending and distinct"),
                            ({"memory_gb": 64}, "more than the 32 GB ARVA may give")):
        r = spades(client, sample, {"r1": r1, "r2": r2}, params)
        assert r.status_code == 422 and message in r.json()["detail"], r.text
    assert spades(client, sample, {"r1": r1, "r2": r2}, {"cov_cutoff": 0}).status_code == 422

    nanopore = new_sample(client, "nanopore")
    a, b = upload(client, nanopore["id"], R1), upload(client, nanopore["id"], R2)
    r = spades(client, nanopore, {"r1": a, "r2": b})
    assert r.status_code == 400 and "sequencing technology is 'nanopore'" in r.json()["detail"]
    unknown = new_sample(client, "unknown")
    a, b = upload(client, unknown["id"], R1), upload(client, unknown["id"], R2)
    r = spades(client, unknown, {"r1": a, "r2": b})
    assert r.status_code == 400 and "confirm that the selected files hold" in r.json()["detail"]
    assert spades(client, unknown, {"r1": a, "r2": b}, reads_confirmed=True).status_code == 202

    old_help = tmp_path / "help.txt"
    old_help.write_text((FIXTURES / "spades" / "help_3.15.5.txt").read_text().replace("--isolate", "--isolatx"))
    monkeypatch.setenv("FAKE_SPADES_HELP", str(old_help))
    r = spades(client, sample, {"r1": r1, "r2": r2})
    assert r.status_code == 422 and "does not offer --isolate" in r.json()["detail"]
    monkeypatch.setenv("ARVA_TOOL_SPADES", str(tmp_path / "missing"))
    r = spades(client, sample, {"r1": r1, "r2": r2})
    assert r.status_code == 409 and "SPAdes is not available" in r.json()["detail"]


def test_spades_pairs_must_hold_the_same_reads(client, fakes, tmp_path):
    sample = new_sample(client)
    a = upload(client, sample["id"], fastq(tmp_path / "x_R1.fastq.gz", 3))
    b = upload(client, sample["id"], fastq(tmp_path / "x_R2.fastq.gz", 2))
    stats(client, sample, [a, b])
    r = spades(client, sample, {"r1": a, "r2": b})
    assert r.status_code == 400 and "has 3 reads and x_R2.fastq.gz 2" in r.json()["detail"]


def test_spades_job_records_everything(client, fakes, storage_root):
    sample = new_sample(client)
    r1 = upload(client, sample["id"], R1, name="run 1_R1.fastq.gz")
    r2 = upload(client, sample["id"], R2, name="run 1_R2.fastq.gz")
    r = spades(client, sample, {"r1": r1, "r2": r2}, {"threads": 99, "memory_gb": 8})
    assert r.status_code == 202, r.text
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    assert (d["job_type"], d["tool_name"], d["tool_version"]) == ("spades_assembly", "SPAdes", "3.15.5")
    p = d["parameters"]
    assert (p["mode"], p["k"], p["cov_cutoff"], p["memory_gb"], p["threads"], p["output"]) == (
        "isolate", None, "off", 8, 4, "contigs")
    assert p["inputs"] == {"r1": r1["id"], "r2": r2["id"], "unpaired": None} and p["memory_source"] == "user"
    assert d["input_raw_file_ids"] == [r1["id"], r2["id"]]

    results = job_dir(storage_root, sample, d["id"])
    seen = dump(fakes["dir"] / "spades_dump.txt")
    argv = seen["ARGS"].split("\t")
    assert argv == ["--isolate", "-1", str(results / "input" / "01_run_1_R1.fastq.gz"), "-2",
                    str(results / "input" / "02_run_1_R2.fastq.gz"), "-o", str(results / "spades"), "-t", "4",
                    "-m", "8", "--cov-cutoff", "off"]
    assert d["commands"] == [[d["tool_path"], *argv]] and seen["HOME"] != os.environ.get("HOME")
    assert "SPAdes planned 9 stages" in d["log_text"] and "SPAdes stage 3/9: K21" in d["log_text"]
    prog = d["progress"]
    assert (prog["tool"], prog["stage"], prog["stage_index"], prog["stages_total"], prog["finished"]) == (
        "SPAdes", "Terminate", 9, 9, True)
    assert "SPAdes ran k = 21, 33, 55, 77 (chosen by SPAdes)" in d["log_text"]
    assert sorted(x.name for x in results.iterdir()) == sorted(
        ["contigs.fasta", "scaffolds.fasta", "assembly_graph_with_scaffolds.gfa", "spades.log", "params.txt",
         "spades.console.log"])
    s = d["result_summary"]
    assert (s["k_values"], s["k_source"], s["coverage_kind"], s["output"]) == (
        [21, 33, 55, 77], "spades", "kmer_coverage", "contigs")

    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert (a["assembler"], a["mode"], a["read_type"], a["coverage_kind"]) == ("SPAdes", "short", "paired-end",
                                                                               "kmer_coverage")
    assert a["input_file_ids"] == [r1["id"], r2["id"]] and a["contigs_path"].endswith("/contigs.fasta")
    assert a["stats"]["circularity"] == {"contigs_with_circularity": 0, "circular_contigs": 0}
    contigs = client.get(f"{API}/assemblies/{a['id']}").json()["contigs"]
    assert [(c["name"], c["coverage"], c["circular"], c["repeat"]) for c in contigs[:2]] == [
        ("NODE_1_length_98152_cov_13.419342", 13.419342, None, None), ("NODE_2_length_8077_cov_26.792000", 26.792, None, None)]
    check = next(c for c in a["stats"]["warning_checks"] if c["code"] == "chromosome_not_circular")
    assert check["skipped_reason"] == "the assembler reported no circularity"
    rule = next(c for c in a["stats"]["warning_checks"] if c["code"] == "high_coverage_contigs")["rule"]
    assert rule == "contig k-mer coverage above 4 × the length-weighted median k-mer coverage"
    g = client.get(f"{API}/assemblies/{a['id']}/graph").json()
    assert g["coverage_tag"] == "DP" and g["coverage_meaning"].startswith("k-mer coverage")
    (row,) = client.get(f"{API}/projects/{sample['project_id']}/assemblies").json()
    assert row["coverage_kind"] == "kmer_coverage"
    report = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    step = next(st for st in report["processing"] if st["job_type"] == "spades_assembly")
    assert step["highlights"][0].startswith("Assembly (short, paired-end): 4 contigs") and \
        step["highlights"][0].endswith("circularity not reported by SPAdes")
    assert any("k = 21, 33, 55, 77 (chosen by SPAdes)" in h for h in step["highlights"])
    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "Median contig k-mer coverage" in html and "not reported by SPAdes" in html
    csv_text = client.get(f"{API}/samples/{sample['id']}/report?format=csv").text
    assert "kmer_coverage" in csv_text


def test_spades_scaffolds_and_explicit_k(client, fakes, storage_root):
    sample = new_sample(client)
    se = upload(client, sample["id"], R1)
    r = spades(client, sample, {"unpaired": se}, {"output": "scaffolds", "k": [21, 33], "mode": "careful",
                                                  "cov_cutoff": "auto"})
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    argv = dump(fakes["dir"] / "spades_dump.txt")["ARGS"].split("\t")
    assert argv[:3] == ["--careful", "-s", str(job_dir(storage_root, sample, d["id"]) / "input" / "03_SYNTHETIC_illumina_R1_001.fastq.gz")]
    assert argv[-4:] == ["--cov-cutoff", "auto", "-k", "21,33"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert a["contigs_path"].endswith("/scaffolds.fasta") and a["read_type"] == "single-end"
    assert d["result_summary"]["k_source"] == "user"
    # The stand-in replays a log of four k values: a difference from the k given is recorded, not hidden.
    assert "Note: SPAdes ran k = 21, 33, 55, 77, not the k given (21, 33)" in d["log_text"]


@pytest.mark.parametrize("mode, message", [
    ("oom", "SPAdes ran out of memory during the K21 stage (memory limit -m 4 GB): mmap(2) failed"),
    ("crash", "spades.py exited with status 3"),
    ("no_outputs", "SPAdes exited without an error but did not write contigs.fasta"),
    ("mismatch", "The lengths in SPAdes' sequence names differ"),
    ("badname", "SPAdes wrote a sequence name without its length and k-mer coverage: 'contig_1'"),
])
def test_spades_failures_are_explained_and_leave_nothing(client, fakes, storage_root, mode, message):
    fakes["mode"](spades=mode)
    sample = new_sample(client)
    r = spades(client, sample, {"unpaired": upload(client, sample["id"], R1)}, {"memory_gb": 4})
    d = job(client, r.json()["id"])
    assert d["status"] == "failed" and message in d["error_message"], d["error_message"]
    assert not job_dir(storage_root, sample, d["id"]).exists()
    assert client.get(f"{API}/samples/{sample['id']}/assemblies").json() == []


def test_spades_preview(client, fakes):
    sample = new_sample(client)
    r1, r2 = upload(client, sample["id"], R1), upload(client, sample["id"], R2)
    stats(client, sample, [r1, r2])
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/spades/preview",
                       json={"inputs": {"r1_file_id": r1["id"], "r2_file_id": r2["id"]}}).json()
    assert plan["tool"]["status"] == "available" and plan["tool"]["version"] == "3.15.5"
    assert set(plan["tool"]["options"]) == {"--isolate", "--careful", "-k", "--cov-cutoff", "-s"}
    assert (plan["tool"]["max_memory_gb"], plan["tool"]["default_memory_gb"]) == (32, 32)
    assert [(f["role"], f["read_mate"]) for f in plan["files"]] == [("r1", "R1"), ("r2", "R2")]
    assert plan["files"][0]["read_count"] == plan["files"][1]["read_count"] > 0
    assert (plan["assembly_mode"], plan["read_layout"], plan["problem"]) == ("short", "paired-end", None)
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/spades/preview",
                       json={"inputs": {"r1_file_id": r1["id"]}}).json()
    assert plan["problem"] == "Paired-end reads need both the R1 and the R2 file"


# --- Unicycler -----------------------------------------------------------------------------------------------

def test_unicycler_request_checks(client, fakes, monkeypatch):
    sample = new_sample(client, "hybrid")
    r1, r2, ont = (upload(client, sample["id"], p) for p in (R1, R2, ONT))
    stats(client, sample, [r1, r2, ont])
    r = unicycler(client, sample, {"r1": r1, "r2": r2, "long": r1})
    assert r.status_code == 400 and "more than one role" in r.json()["detail"]
    r = unicycler(client, sample, {"unpaired": r2, "long": r1})
    assert r.status_code == 400 and "is marked as read R1 of a pair: paired-end files hold short reads" in r.text
    r = unicycler(client, sample, {"long": ont}, {"kmers": [21, 33]})
    assert r.status_code == 422 and "kmers only apply to the SPAdes step" in r.json()["detail"]
    r = unicycler(client, sample, {"r1": r1, "r2": r2}, {"spades_memory_gb": 33})
    assert r.status_code == 422 and "more than the 32 GB" in r.json()["detail"]
    illumina = new_sample(client, "illumina")
    a, b, c = (upload(client, illumina["id"], p) for p in (R1, R2, ONT))
    r = unicycler(client, illumina, {"r1": a, "r2": b, "long": c})
    assert r.status_code == 400 and "technology is 'illumina', but Unicycler is given long reads" in r.text
    monkeypatch.setenv("ARVA_TOOL_RACON", str(fakes["dir"] / "missing"))
    r = unicycler(client, sample, {"r1": r1, "r2": r2, "long": ont})
    assert r.status_code == 409 and "Unicycler needs racon" in r.json()["detail"]
    assert unicycler(client, sample, {"r1": r1, "r2": r2}).status_code == 202


def test_unicycler_hybrid_job(client, fakes, storage_root):
    sample = new_sample(client, "hybrid")
    r1, r2, ont = (upload(client, sample["id"], p) for p in (R1, R2, ONT))
    r = unicycler(client, sample, {"r1": r1, "r2": r2, "long": ont}, {"mode": "bold", "spades_memory_gb": 6,
                                                                       "kmers": [27, 53]})
    assert r.status_code == 202, r.text
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    assert (d["job_type"], d["tool_name"], d["tool_version"]) == ("unicycler_assembly", "Unicycler", "0.5.0")
    p = d["parameters"]
    assert (p["assembly_mode"], p["mode"], p["keep"], p["kmers"], p["spades_memory_gb"], p["threads"]) == (
        "hybrid", "bold", 1, [27, 53], 6, 4)
    results = job_dir(storage_root, sample, d["id"])
    argv = dump(fakes["dir"] / "unicycler_dump.txt")["ARGS"].split("\t")
    h = fakes["helpers"]
    assert argv == ["-1", str(results / "input" / "01_SYNTHETIC_illumina_R1_001.fastq.gz"),
                    "-2", str(results / "input" / "02_SYNTHETIC_illumina_R2_001.fastq.gz"),
                    "-l", str(results / "input" / "04_SYNTHETIC_nanopore_reads.fastq.gz"),
                    "-o", str(results / "unicycler"), "-t", "4", "--mode", "bold", "--keep", "1",
                    "--verbosity", "1", "--min_fasta_length", "100", "--linear_seqs", "0", "--depth_filter", "0.25",
                    "--kmers", "27,53", "--spades_path", str(fakes["spades"]), "--spades_options=-m 6",
                    "--racon_path", str(h["racon"]), "--makeblastdb_path", str(h["makeblastdb"]),
                    "--tblastn_path", str(h["tblastn"])]
    assert "Unicycler stage 1/19: Starting Unicycler" in d["log_text"]
    assert "Choosing k-mer range for assembly (a stage ARVA does not expect" in d["log_text"]
    assert d["progress"]["finished"] and d["progress"]["stage"] == "Assembly complete"
    kept = sorted(str(x.relative_to(results)) for x in results.rglob("*") if x.is_file())
    assert kept == ["assembly.fasta", "assembly.gfa", "unicycler.console.log", "unicycler.log",
                    "unicycler/002_depth_filter.gfa"]
    assert sorted(Path(x).name for x in d["output_paths"]) == sorted(Path(k).name for k in kept)
    s = d["result_summary"]
    assert (s["assembly_mode"], s["annotation_source"], s["coverage_kind"]) == ("hybrid", "fasta_headers",
                                                                                "relative_depth")
    assert {x["name"]: x["version"] for x in s["helpers"]} == {"spades": "3.15.5", "racon": "1.5.0",
                                                               "makeblastdb": "2.12.0+", "tblastn": "2.12.0+"}
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert (a["assembler"], a["mode"], a["read_type"], a["coverage_kind"]) == (
        "Unicycler", "hybrid", "paired-end + long", "relative_depth")
    assert a["input_file_ids"] == [r1["id"], r2["id"], ont["id"]]
    contigs = client.get(f"{API}/assemblies/{a['id']}").json()["contigs"]
    assert [(c["name"], c["length"], c["coverage"], c["circular"]) for c in contigs] == [
        ("1", 100000, 1.0, True), ("2", 8000, 2.04, True)]
    assert client.get(f"{API}/assemblies/{a['id']}/graph").json()["coverage_tag"] == "dp"
    log = client.get(f"{API}/jobs/{d['id']}/log", params={"tail": 2})
    assert log.headers["x-arva-log-source"] == "tool" and log.headers["x-arva-log-name"] == "unicycler.log"
    report = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    step = next(st for st in report["processing"] if st["job_type"] == "unicycler_assembly")
    assert step["highlights"][0].endswith("2 reported circular by Unicycler")
    assert "Helpers used: spades 3.15.5, racon 1.5.0, makeblastdb 2.12.0+, tblastn 2.12.0+" in step["highlights"]


def test_unicycler_long_reads_only_reads_the_graph(client, fakes):
    sample = new_sample(client, "nanopore")
    ont = upload(client, sample["id"], ONT)
    r = unicycler(client, sample, {"long": ont}, {"keep": 0})
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    argv = dump(fakes["dir"] / "unicycler_dump.txt")["ARGS"].split("\t")
    assert "--spades_path" not in argv and "--depth_filter" not in argv and "--racon_path" in argv
    assert d["result_summary"]["annotation_source"] == "assembly_graph"
    assert "writes no length, depth or circularity in long-read-only FASTA headers" in d["log_text"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert (a["mode"], a["read_type"]) == ("long", "long")
    contigs = client.get(f"{API}/assemblies/{a['id']}").json()["contigs"]
    assert [(c["name"], c["length"], c["circular"]) for c in contigs] == [("1", 99996, True), ("2", 8000, True)]


@pytest.mark.parametrize("mode, message", [
    ("spades_oom", "Unicycler stopped because SPAdes failed: SPAdes ran out of memory (memory limit -m 32 GB)"),
    ("no_outputs", "Unicycler exited without an error but did not write assembly.fasta, assembly.gfa"),
    ("mismatch", "The lengths Unicycler reports differ from the sequences in assembly.fasta"),
])
def test_unicycler_failures(client, fakes, storage_root, mode, message):
    fakes["mode"](unicycler=mode)
    sample = new_sample(client)
    r1, r2 = upload(client, sample["id"], R1), upload(client, sample["id"], R2)
    d = job(client, unicycler(client, sample, {"r1": r1, "r2": r2}).json()["id"])
    assert d["status"] == "failed" and message in d["error_message"], d["error_message"]
    assert not job_dir(storage_root, sample, d["id"]).exists()


def test_unicycler_preview_lists_modes_and_helpers(client, fakes, monkeypatch):
    sample = new_sample(client, "hybrid")
    r1, r2, ont = (upload(client, sample["id"], p) for p in (R1, R2, ONT))
    body = {"inputs": {"r1_file_id": r1["id"], "r2_file_id": r2["id"], "long_file_id": ont["id"]}}
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/unicycler/preview", json=body).json()
    assert plan["tool"]["modes"] == ["short", "long", "hybrid"] and plan["assembly_mode"] == "hybrid"
    assert plan["tool"]["helpers"]["spades"]["version"] == "3.15.5"
    assert plan["read_layout"] == "paired-end + long" and plan["problem"] is None
    monkeypatch.setenv("ARVA_TOOL_TBLASTN", str(fakes["dir"] / "missing"))
    plan = client.post(f"{API}/samples/{sample['id']}/assembly/unicycler/preview", json=body).json()
    assert plan["tool"]["status"] in ("failed", "available")  # detection is cached for a minute
    r = unicycler(client, sample, {"r1": r1, "r2": r2, "long": ont})
    assert r.status_code == 409 and "tblastn" in r.json()["detail"]


# --- Real tools ------------------------------------------------------------------------------------------------

def ready(tool_id):
    return detect(tool_id, refresh=True).status is ToolStatus.available


@pytest.fixture(scope="module")
def small_genome(tmp_path_factory):
    out = tmp_path_factory.mktemp("small") / "genome"
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_synthetic_genome.py"), str(out),
                    "--chromosome-length", "100000", "--plasmid-length", "8000", "--repeat-length", "2000",
                    "--ont-depth", "30", "--illumina-depth", "40"], check=True, capture_output=True)
    return out


@pytest.mark.skipif(not ready("spades"), reason="needs SPAdes")
def test_real_spades_assembles_the_synthetic_pairs(client, small_genome, monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_memory_gb", 4)
    sample = new_sample(client)
    r1 = upload(client, sample["id"], small_genome / "illumina_R1.fastq.gz")
    r2 = upload(client, sample["id"], small_genome / "illumina_R2.fastq.gz")
    r = spades(client, sample, {"r1": r1, "r2": r2}, {"threads": 2})
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    assert d["parameters"]["memory_gb"] == 4 and d["result_summary"]["k_values"] == [21, 33, 55, 77]
    assert d["progress"]["stages"] == d["result_summary"]["log"]["stages_seen"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    contigs = client.get(f"{API}/assemblies/{a['id']}").json()["contigs"]
    assert contigs[0]["length"] > 90_000 and all(c["circular"] is None for c in contigs)
    plasmid = next(c for c in contigs if 8_000 <= c["length"] <= 8_077)
    assert 1.5 <= plasmid["coverage"] / contigs[0]["coverage"] <= 2.5
    g = client.get(f"{API}/assemblies/{a['id']}/graph").json()
    assert g["coverage_tag"] == "DP" and g["segment_count"] >= len(contigs)


@pytest.mark.skipif(not ready("unicycler") or modes_available(helper_paths()) != ["short", "long", "hybrid"],
                    reason="needs Unicycler with SPAdes, Racon and BLAST+")
def test_real_unicycler_hybrid_completes_the_synthetic_genome(client, small_genome, monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_memory_gb", 4)
    sample = new_sample(client, "hybrid")
    r1 = upload(client, sample["id"], small_genome / "illumina_R1.fastq.gz")
    r2 = upload(client, sample["id"], small_genome / "illumina_R2.fastq.gz")
    ont = upload(client, sample["id"], small_genome / "ont.fastq.gz")
    r = unicycler(client, sample, {"r1": r1, "r2": r2, "long": ont}, {"threads": 2, "kmers": [27, 53, 77]})
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    assert {h["name"]: h["status"] for h in d["result_summary"]["helpers"]} == {
        "spades": "good", "racon": "good", "makeblastdb": "good", "tblastn": "good"}
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    contigs = client.get(f"{API}/assemblies/{a['id']}").json()["contigs"]
    assert [c["circular"] for c in contigs] == [True, True] and a["warnings"] == []
    assert abs(contigs[0]["length"] - 100_000) <= 10 and abs(contigs[1]["length"] - 8_000) <= 10
    assert contigs[0]["coverage"] == 1.0 and 1.5 <= contigs[1]["coverage"] <= 2.5
