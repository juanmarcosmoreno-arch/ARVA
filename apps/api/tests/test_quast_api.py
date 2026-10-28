"""QUAST evaluation jobs: request checks, the recorded command and results, ARVA's cross-check, served reports,
failures, and a real run.

The assemblies are those of workflows/tool-adapters/tests/fixtures/quast/make_assemblies.py (SYNTHETIC, with known
differences from the synthetic genome), registered through a stand-in assembler job. A stand-in QUAST (Python)
prints QUAST 5.2.0's real --help and writes the recorded fixture reports under the labels it is given, so ARVA's
cross-check of those numbers holds. The end-to-end test runs the real QUAST and is skipped without it.
"""
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from arva_tools import ToolStatus
from arva_tools.quast import aligner
from arva_tools.registry import detect

from app.api.routes.tools import MULTIQC_REPORT_CSP
from app.db.session import SessionLocal
from app.models import AnalysisJob, AssemblyMode, JobStatus
from app.services.assemblies import register_assembly
from app.services.multiqc import STORAGE_SHIM
from app.tasks import tools as tool_tasks
from app.tasks.common import run_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
ONT = REPO / "examples" / "synthetic" / "SYNTHETIC_nanopore_reads.fastq.gz"
FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "quast"

FAKE = r'''
import os, sys, time
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("WARNING: Python locale settings can't be changed\nQUAST v5.2.0")
    sys.exit(0)
if args == ["--help"]:
    sys.stdout.write(Path(os.environ["FAKE_QUAST_HELP"]).read_text())
    sys.exit(0)
mode = os.environ.get("FAKE_QUAST_MODE", "ok")
fixtures = Path(os.environ["FAKE_QUAST_FIXTURES"])
contigs = []
while args and not args[0].startswith("-"):
    contigs.append(args.pop(0))
opts = {args[i]: args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else True
        for i in range(len(args)) if args[i].startswith("-")}
Path(os.environ["FAKE_QUAST_DUMP"]).write_text("\n".join([
    "ARGS=" + "\t".join(sys.argv[1:]), "CWD=" + os.getcwd(), "HOME=" + os.environ.get("HOME", ""),
    "LINKS=" + "\t".join(os.readlink(c) for c in contigs + ([opts["-r"]] if "-r" in opts else [])),
]))
labels = opts["--labels"].split(",")
reference = "-r" in opts
out = Path(opts["--output-dir"])
out.mkdir()
def say(line):
    print(line, flush=True)
say("WARNING: Python locale settings can't be changed")
say("Version: 5.2.0")
say("  Python version: 3.12.3")
stages = ["Running Basic statistics processor..."]
if reference:
    stages += ["Running Contig analyzer...", "Running NA-NGA calculation...", "Running Genome analyzer..."]
stages.append("Creating large visual summaries...")
for line in stages:
    say(line)
    time.sleep(float(os.environ.get("FAKE_QUAST_PAUSE", "0")))
    if mode == "none_correct":
        say("WARNING: Skipping x because it doesn't contain contigs >= 500 bp.")
        say("ERROR! None of the assembly files contains correct contigs. Please, provide different files or decrease "
            "--min-contig threshold.")
        sys.exit(4)
    if mode == "non_acgtn":
        say(f"    ERROR! Skipping {contigs[-1]} because it contains non-ACGTN characters.")
        sys.exit(4)
    if mode == "traceback":
        sys.stderr.write("Traceback (most recent call last):\n  boom\n")
        sys.exit(1)
if reference:
    say("WARNING: Version of installed minimap2 differs from its version in the QUAST package (2.24). Please make "
        "sure that you use an actual version of software.")
if mode == "no_outputs":
    sys.exit(0)
src = fixtures / ("reference" if reference else "no_reference")
def relabel(text, transposed):
    rows = [line.split("\t") for line in text.splitlines()]
    keep = len(labels) - (1 if mode == "skip" else 0)
    if transposed:
        rows = [rows[0]] + [[labels[i]] + r[1:] for i, r in enumerate(rows[1:keep + 1])]
    else:
        rows = [["Assembly"] + labels[:keep]] + [r[:keep + 1] for r in rows[1:]]
    if mode == "n50_off":
        row, col = (1, rows[0].index("N50")) if transposed else (next(i for i, r in enumerate(rows) if r[0] == "N50"), 1)
        rows[row][col] = str(int(rows[row][col]) + 1)
    if mode == "mismatch" and transposed:
        rows[1][1] = "999"
    return "".join("\t".join(r) + "\n" for r in rows)
(out / "report.tsv").write_text(relabel((src / "report.tsv").read_text(), False))
(out / "transposed_report.tsv").write_text(relabel((src / "transposed_report.tsv").read_text(), True))
(out / "report.txt").write_text("All statistics are based on contigs of size >= 500 bp\n")
(out / "report.html").write_text("<!DOCTYPE html><html><head><title>QUAST</title></head><body><script>"
                                 "var c = document.cookie;</script><a href='icarus.html'>Icarus</a></body></html>")
(out / "icarus.html").write_text("<html><head></head><body><a href='icarus_viewers/contig_size_viewer.html'>x</a></body></html>")
(out / "icarus_viewers").mkdir()
(out / "icarus_viewers" / "contig_size_viewer.html").write_text("<html><head></head><body><a href='../icarus.html'>back</a></body></html>")
if reference:
    (out / "icarus_viewers" / "alignment_viewer.html").write_text("<html><head></head><body>alignments</body></html>")
    (out / "contigs_reports").mkdir()
    (out / "contigs_reports" / "misassemblies_report.tsv").write_text("Assembly\t" + "\t".join(labels) + "\n")
    stderr = (fixtures / "reference" / "contigs_report_edited.stderr").read_text()
    (out / "contigs_reports" / "contigs_report_a.stderr").write_text(stderr)
(out / "quast.log").write_text("" if os.environ.get("FAKE_QUAST_EMPTY_LOG") else "QUAST log\n")
(out / "basic_stats").mkdir()
say("RESULTS:")
'''


def _load_make_assemblies():
    spec = importlib.util.spec_from_file_location("make_assemblies", FIXTURES / "make_assemblies.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_assemblies


@pytest.fixture(scope="module")
def genome(tmp_path_factory):
    """The synthetic genome's reference and the two SYNTHETIC assemblies of the QUAST fixtures."""
    root = tmp_path_factory.mktemp("quast-genome")
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_synthetic_genome.py"), str(root / "genome"),
                    "--ont-depth", "1", "--illumina-depth", "1"], check=True, capture_output=True)
    edited, perfect = _load_make_assemblies()(root / "genome" / "reference.fasta", root)
    return {"reference": root / "genome" / "reference.fasta", "edited": edited, "perfect": perfect}


@pytest.fixture
def fake_quast(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "quast.py"
    exe.write_text(f"#!{sys.executable}\n{FAKE}")
    exe.chmod(0o755)
    minimap2 = bindir / "minimap2"
    minimap2.write_text("#!/bin/sh\necho 2.26-r1175\n")
    minimap2.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_QUAST", str(exe))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_QUAST_HELP", str(FIXTURES / "help_5.2.0.txt"))
    monkeypatch.setenv("FAKE_QUAST_FIXTURES", str(FIXTURES))
    monkeypatch.setenv("FAKE_QUAST_DUMP", str(tmp_path / "dump.txt"))
    monkeypatch.setattr(tool_tasks, "MONITOR_SECONDS", 0.05)

    def mode(name="ok", pause=0.0):
        monkeypatch.setenv("FAKE_QUAST_MODE", name)
        monkeypatch.setenv("FAKE_QUAST_PAUSE", str(pause))
        return tmp_path / "dump.txt"

    return mode


def new_sample(client, code="QUAST-1"):
    p = client.post(f"{API}/projects", json={"name": "Evaluation"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": code, "sequencing_technology": "nanopore"}).json()


def upload(client, sample_id, path: Path, name: str | None = None):
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (name or path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def assemble(client, sample, reads, fasta: Path, assembler="Flye", version="2.9.3") -> dict:
    """Register `fasta` as an assembly of the sample through a stand-in assembler job."""
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="assembly_test",
                          tool_name=assembler, tool_version=version, parameters={}, input_raw_file_ids=[reads["id"]],
                          status=JobStatus.pending, log_text="")
        db.add(job)
        db.commit()
        job_id = job.id

    def body(ctx):
        out = ctx.path(ctx.results_rel)
        out.mkdir(parents=True)
        shutil.copyfile(fasta, out / "assembly.fasta")
        register_assembly(ctx, assembler=assembler, mode=AssemblyMode.long, read_type="nano-hq",
                          contigs=out / "assembly.fasta")
        ctx.job.output_paths = [str((out / "assembly.fasta").relative_to(ctx.storage.root))]

    assert run_job(job_id, body) == "completed"
    (a,) = [a for a in client.get(f"{API}/samples/{sample['id']}/assemblies").json() if a["job_id"] == job_id]
    return a


@pytest.fixture
def setup(client, genome):
    sample = new_sample(client)
    reads = upload(client, sample["id"], ONT)
    edited = assemble(client, sample, reads, genome["edited"])
    perfect = assemble(client, sample, reads, genome["perfect"])
    reference = upload(client, sample["id"], genome["reference"])
    return {"sample": sample, "reads": reads, "edited": edited, "perfect": perfect, "reference": reference}


def start(client, sample, assemblies, **extra):
    return client.post(f"{API}/samples/{sample['id']}/assembly/quast",
                       json={"assembly_ids": [a["id"] for a in assemblies], **extra})


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


def results_dir(storage_root, sample, job_id) -> Path:
    return storage_root / "results" / sample["project_id"] / sample["id"] / job_id


def label(a) -> str:
    return f"Flye 2.9.3 {a['id'][:8]}"


def test_request_checks(client, fake_quast, setup, tmp_path, monkeypatch):
    fake_quast()
    s, edited = setup["sample"], setup["edited"]
    other = new_sample(client, "OTHER")
    r = start(client, other, [edited])
    assert r.status_code == 400 and "does not belong to this sample" in r.json()["detail"]
    r = client.post(f"{API}/samples/{s['id']}/assembly/quast", json={"assembly_ids": [edited["id"], edited["id"]]})
    assert r.status_code == 400 and "more than once" in r.json()["detail"]
    r = client.post(f"{API}/samples/{s['id']}/assembly/quast", json={"assembly_ids": [edited["id"]] * 11})
    assert r.status_code == 422
    r = start(client, s, [edited], reference_file_id=setup["reads"]["id"])
    assert r.status_code == 400 and "is not a FASTA file" in r.json()["detail"]
    foreign = upload(client, other["id"], tmp_path.joinpath("r.fasta").write_text(">r\nACGT\n") and tmp_path / "r.fasta")
    r = start(client, s, [edited], reference_file_id=foreign["id"])
    assert r.status_code == 400 and "does not belong to this sample" in r.json()["detail"]
    # The longest contig of `edited` is 160,000 bp: nothing would be left for QUAST to evaluate.
    r = start(client, s, [edited, setup["perfect"]], min_contig=200_000)
    assert r.status_code == 400 and f"No contig of {label(edited)} is at least 200,000 bp long" in r.json()["detail"]
    assert start(client, s, [edited], min_contig=1_000_001).status_code == 422

    # An option this QUAST's --help does not list is refused before anything runs.
    old_help = tmp_path / "help.txt"
    old_help.write_text((FIXTURES / "help_5.2.0.txt").read_text().replace("--unaligned-part-size", "--unaligned-xx"))
    monkeypatch.setenv("FAKE_QUAST_HELP", str(old_help))
    r = start(client, s, [edited], reference_file_id=setup["reference"]["id"])
    assert r.status_code == 422 and "does not offer --unaligned-part-size" in r.json()["detail"]
    assert start(client, s, [edited]).status_code == 202
    monkeypatch.setenv("FAKE_QUAST_HELP", str(FIXTURES / "help_5.2.0.txt"))

    # Without minimap2 QUAST would compile its own copy during the run: refused, but a run without reference is fine.
    monkeypatch.setenv("PATH", str(Path(os.environ["ARVA_TOOL_QUAST"]).parent.parent / "empty"))
    r = start(client, s, [edited], reference_file_id=setup["reference"]["id"])
    assert r.status_code == 409 and "needs minimap2 2.19 or later" in r.json()["detail"]
    monkeypatch.setenv("ARVA_TOOL_QUAST", str(tmp_path / "missing"))
    r = start(client, s, [edited])
    assert r.status_code == 409 and "QUAST is not available" in r.json()["detail"]


def test_preview_explains_the_minimum_contig_length(client, fake_quast, setup):
    fake_quast()
    s, edited, perfect = setup["sample"], setup["edited"], setup["perfect"]
    url = f"{API}/samples/{s['id']}/assembly/quast/preview"
    plan = client.post(url, json={"assembly_ids": [edited["id"], perfect["id"]],
                                  "reference_file_id": setup["reference"]["id"]}).json()
    assert plan["tool"]["status"] == "available" and plan["tool"]["version"] == "5.2.0"
    assert plan["tool"]["aligner"]["provided_by"] == "path" and plan["tool"]["aligner"]["version"] == "2.26-r1175"
    assert plan["tool"]["default_min_contig"] == 500 and plan["min_contig"] == 500
    e, p = plan["assemblies"]
    assert (e["label"], e["contigs"], e["contigs_kept"], e["contigs_left_out"], e["length_left_out"]) == (
        label(edited), 8, 6, 2, 400 + 499)
    assert (p["contigs_kept"], p["contigs_left_out"]) == (2, 0)
    assert plan["reference"]["name"] == "reference.fasta" and plan["reference"]["origin"] == "imported"
    plan = client.post(url, json={"assembly_ids": [edited["id"]], "min_contig": 0}).json()
    assert plan["assemblies"][0]["contigs_kept"] == 8 and plan["reference"] is None
    assert client.post(url, json={"assembly_ids": ["nope"]}).status_code == 400


def test_evaluation_records_everything_and_serves_the_reports(client, fake_quast, setup, storage_root):
    dump = fake_quast()
    s, edited, perfect, ref = setup["sample"], setup["edited"], setup["perfect"], setup["reference"]
    r = start(client, s, [edited, perfect], reference_file_id=ref["id"], threads=99)
    assert r.status_code == 202, r.text
    detail = job(client, r.json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    assert (detail["job_type"], detail["tool_name"], detail["tool_version"]) == ("quast_evaluation", "QUAST", "5.2.0")
    p = detail["parameters"]
    assert (p["min_contig"], p["threads"], p["reference_file_id"]) == (500, 4, ref["id"])
    assert [a["label"] for a in p["assemblies"]] == [label(edited), label(perfect)]
    assert p["assemblies"][0]["contigs_sha256"] == edited["stats"]["files"]["contigs"]["sha256"]
    assert detail["input_raw_file_ids"] == [ref["id"]]

    results = results_dir(storage_root, s, detail["id"])
    seen = dict(line.split("=", 1) for line in dump.read_text().splitlines())
    inp = results / "input"
    assert seen["ARGS"].split("\t") == [
        str(inp / "assembly_01.fasta"), str(inp / "assembly_02.fasta"), "--output-dir", str(results / "quast"),
        "--threads", "4", "--min-contig", "500", "--labels", f"{label(edited)},{label(perfect)}",
        "--contig-thresholds", "0,1000,5000,10000,25000,50000", "--x-for-Nx", "90", "--no-plots",
        "-r", str(inp / "reference.fasta"), "--min-alignment", "65", "--min-identity", "95.0", "--ambiguity-usage",
        "one", "--extensive-mis-size", "1000", "--local-mis-size", "200", "--scaffold-gap-max-size", "10000",
        "--unaligned-part-size", "500"]
    assert detail["commands"] == [[detail["tool_path"], *seen["ARGS"].split("\t")]]
    assert seen["CWD"] == str(results) and seen["HOME"] != os.environ.get("HOME")
    assert seen["LINKS"].split("\t") == [str(storage_root / a["contigs_path"]) for a in (edited, perfect)] + [
        str(storage_root / "raw" / s["project_id"] / s["id"] / f"{ref['id']}__reference.fasta")]
    assert not inp.exists()

    prog = detail["progress"]
    assert (prog["tool"], prog["stage"], prog["stage_index"], prog["stages_total"], prog["finished"]) == (
        "QUAST", "visual_summaries", 5, 5, True)
    for n, stage in enumerate(["basic_stats", "contig_analyzer", "na_nga", "genome_analyzer", "visual_summaries"], 1):
        assert f"QUAST stage {n}/5: {stage}" in detail["log_text"]
    assert "QUAST warning: Version of installed minimap2 differs" in detail["log_text"]

    summary = detail["result_summary"]
    assert (summary["quast_version"], summary["python_version"], summary["min_contig"]) == ("5.2.0", "3.12.3", 500)
    assert summary["reference"]["name"] == "reference.fasta" and summary["reference"]["sha256"] == ref["checksum_sha256"]
    assert summary["report"]["labels"] == [label(edited), label(perfect)]
    rows = {r["field"]: r["values"] for r in summary["report"]["rows"]}
    assert rows["# misassemblies"] == [1, 0] and rows["Genome fraction (%)"] == [100.0, 99.683]
    assert summary["aligner"] == {"name": "minimap2", "executable": "/usr/bin/minimap2", "version": "2.26-r1175"}
    assert summary["quast_log_empty"] is False
    assert summary["html"] == {"report": "report.html", "icarus": "icarus.html",
                               "viewers": ["icarus_viewers/alignment_viewer.html", "icarus_viewers/contig_size_viewer.html"]}
    # ARVA's own statistics of the same contigs at 500 bp equal QUAST's.
    (ce, cp) = summary["crosscheck"]
    assert ce["all_agree"] and cp["all_agree"] and ce["label"] == label(edited)
    by_metric = {r["metric"]: r for r in ce["rows"]}
    assert (by_metric["N50"]["quast"], by_metric["N50"]["arva"]) == (140_000, 140_000)
    assert by_metric["GC (%)"]["quast"] == 49.45 and abs(by_metric["GC (%)"]["arva"] - 49.45) < 0.005
    assert (by_metric["# contigs (>= 0 bp)"]["arva"], by_metric["# contigs"]["arva"]) == (8, 6)
    assert "Cross-check" in detail["log_text"] and "11/11 QUAST metrics equal ARVA's at 500 bp" in detail["log_text"]

    names = sorted(Path(p).name for p in detail["output_paths"])
    assert names == sorted(["report.html", "icarus.html", "report.tsv", "transposed_report.tsv", "report.txt",
                            "quast.log", "alignment_viewer.html", "contig_size_viewer.html",
                            "misassemblies_report.tsv", "quast.console.log"])
    base = f"{API}/jobs/{detail['id']}/outputs"
    for page in ("report.html", "icarus.html", "icarus_viewers/contig_size_viewer.html"):
        r = client.get(f"{base}/{page}")
        assert r.status_code == 200 and r.headers["content-security-policy"] == MULTIQC_REPORT_CSP, page
        assert r.content.count(STORAGE_SHIM) == 1 and r.headers["x-content-type-options"] == "nosniff"
    # Dot segments are percent-encoded so that the client does not resolve them before the request.
    for bad in ("icarus_viewers/%2E%2E/report.tsv", "quast/%2E%2E/%2E%2E/x.html", "icarus_viewers/missing.html",
                "/etc/passwd", "a//report.tsv"):
        assert client.get(f"{base}/{bad}").status_code == 404, bad
    r = client.get(f"{base}/report.tsv")
    assert r.headers["content-type"].startswith("text/plain") and r.text.startswith("Assembly\t")
    assert client.get(f"{base}/report.html", params={"download": True}).headers["content-disposition"].startswith(
        "attachment")

    report = client.get(f"{API}/samples/{s['id']}/report?format=json").json()
    step = next(st for st in report["processing"] if st["job_type"] == "quast_evaluation")
    assert step["inputs"] == ["reference.fasta"]
    assert step["highlights"][0] == "2 assembly(ies), minimum contig length 500 bp; reference reference.fasta"
    assert step["highlights"][1].startswith(f"{label(edited)}: 6 contigs, 337,500 bp, N50 140,000 bp, L50 2; "
                                            "genome fraction 100.0 %, 1 misassemblies")
    assert step["highlights"][3] == f"Independent check of {label(edited)}: 11/11 metrics equal ARVA's at 500 bp"


def test_without_a_reference_no_aligner_is_used(client, fake_quast, setup, monkeypatch):
    dump = fake_quast()
    monkeypatch.setenv("FAKE_QUAST_EMPTY_LOG", "1")
    s = setup["sample"]
    detail = job(client, start(client, s, [setup["edited"]], min_contig=500).json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    args = dict(line.split("=", 1) for line in dump.read_text().splitlines())["ARGS"].split("\t")
    assert "-r" not in args and "--min-alignment" not in args and detail["input_raw_file_ids"] == []
    summary = detail["result_summary"]
    assert summary["aligner"] is None and summary["reference"] is None
    assert detail["progress"]["stages"] == ["basic_stats", "visual_summaries"]
    assert "Genome fraction (%)" not in {r["field"] for r in summary["report"]["rows"]}
    assert summary["quast_log_empty"] is True and "QUAST left quast.log empty" in detail["log_text"]
    assert summary["html"]["viewers"] == ["icarus_viewers/contig_size_viewer.html"]


def test_a_crosscheck_difference_is_reported_not_hidden(client, fake_quast, setup):
    fake_quast("n50_off")
    detail = job(client, start(client, setup["sample"], [setup["edited"]]).json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    (check,) = detail["result_summary"]["crosscheck"]
    n50 = next(r for r in check["rows"] if r["metric"] == "N50")
    assert (n50["quast"], n50["arva"], n50["agrees"], check["all_agree"]) == (140_001, 140_000, False, False)
    assert "10/11 QUAST metrics equal ARVA's at 500 bp; differ: N50" in detail["log_text"]


@pytest.mark.parametrize("mode, message", [
    ("skip", "QUAST left out"),
    ("none_correct", "QUAST found no contig at least as long as the minimum contig length"),
    ("non_acgtn", "QUAST refused Flye 2.9.3 "),
    ("traceback", "quast.py exited with status 1"),
    ("no_outputs", "QUAST exited without an error but did not write report.tsv, transposed_report.tsv"),
    ("mismatch", "report.tsv and transposed_report.tsv do not hold the same values"),
])
def test_failures_are_explained_and_leave_nothing(client, fake_quast, setup, storage_root, mode, message):
    fake_quast(mode)
    s = setup["sample"]
    detail = job(client, start(client, s, [setup["edited"], setup["perfect"]]).json()["id"])
    assert detail["status"] == "failed" and message in detail["error_message"], detail["error_message"]
    assert not results_dir(storage_root, s, detail["id"]).exists()
    assert detail["progress"]["finished"] is True and detail["result_summary"] is None
    if mode == "non_acgtn":
        assert detail["error_message"].startswith(f"QUAST refused {label(setup['perfect'])}: it accepts only")


def test_contigs_changed_since_registration_are_refused(client, fake_quast, setup, storage_root):
    fake_quast()
    path = storage_root / setup["edited"]["contigs_path"]
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    path.write_text(path.read_text().replace("SYNTHETIC_H_500bp", "SYNTHETIC_H_500bq"))
    detail = job(client, start(client, setup["sample"], [setup["edited"]]).json()["id"])
    assert detail["status"] == "failed" and "changed since it was registered" in detail["error_message"]


# --- Real QUAST ---------------------------------------------------------------------------------

def quast_ready() -> bool:
    d = detect("quast", refresh=True)
    return d.status is ToolStatus.available and aligner(d.path)["provided_by"] != "missing"


@pytest.mark.skipif(not quast_ready(), reason="needs QUAST (ARVA_TOOL_QUAST) and minimap2")
def test_real_quast_evaluates_the_synthetic_assemblies(client, setup, storage_root):
    s, edited, perfect = setup["sample"], setup["edited"], setup["perfect"]
    r = start(client, s, [edited, perfect], reference_file_id=setup["reference"]["id"], threads=2)
    assert r.status_code == 202, r.text
    detail = job(client, r.json()["id"])
    assert detail["status"] == "completed", detail["log_text"]
    summary = detail["result_summary"]
    assert summary["quast_version"] == "5.2.0" and summary["aligner"]["name"] == "minimap2"
    assert all(c["all_agree"] for c in summary["crosscheck"]), summary["crosscheck"]
    rows = {r["field"]: r["values"] for r in summary["report"]["rows"]}
    assert rows["# misassemblies"] == [1, 0] and rows["# unaligned contigs"][0] == {"full": 1, "partial": 0}
    assert rows["# contigs (>= 0 bp)"] == [8, 2] and rows["# contigs"] == [6, 2]
    assert detail["progress"]["stage_index"] == 5 and detail["progress"]["finished"] is True
    base = f"{API}/jobs/{detail['id']}/outputs"
    for page in ["report.html", "icarus.html", *summary["html"]["viewers"]]:
        r = client.get(f"{base}/{page}")
        assert r.status_code == 200 and r.headers["content-security-policy"] == MULTIQC_REPORT_CSP, page
        assert b"<script" in r.content
    assert (results_dir(storage_root, s, detail["id"]) / "quast" / "quast.log").stat().st_size > 0
