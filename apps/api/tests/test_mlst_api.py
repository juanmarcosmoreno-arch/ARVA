"""MLST: the bundled schemes as a read-only database record, previews, request checks, the recorded job, the result
(calls, clonal complex, warnings), files, the project and cross-project overviews, reports, and the run-time
re-check of the database.

A stand-in mlst (a shell script with mlst 2.35.0's real --help and a small database folder) covers what needs no
BLAST search. The end-to-end tests run the real mlst (ARVA_TOOL_MLST) and are skipped without it, on two inputs that
need no download: the seven saureus alleles of ST8 from the bundled allele files, separated by N (a test input, not a
genome), and ARVA's SYNTHETIC genome (no scheme).
"""
import gzip
import os
import shutil
from pathlib import Path

import pytest
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import assemble, new_sample

from app.db.session import SessionLocal
from app.models import AnalysisJob, DatabaseOrigin, JobStatus, MlstResult
from app.tasks.mlst import run_mlst_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
HELP = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "mlst" / "help_2.35.0.txt"
SYNTHETIC = REPO / "examples" / "synthetic-genome" / "reference.fasta"
REAL_MLST = os.environ.get("ARVA_TOOL_MLST")
ST8 = {"arcC": 3, "aroE": 3, "glpF": 1, "gmk": 1, "pta": 4, "tpi": 4, "yqiL": 3}


@pytest.fixture
def real_mlst(monkeypatch):
    if REAL_MLST:
        monkeypatch.setenv("ARVA_TOOL_MLST", REAL_MLST)
    registry._CACHE.pop("mlst", None)
    d = detect("mlst", refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"mlst is not available: {d.message}")
    return d.path


@pytest.fixture
def fake_mlst(tmp_path, monkeypatch):
    """mlst's real --help and version line, and a one-scheme database (nothing can be typed with it)."""
    env = tmp_path / "env"
    (env / "bin").mkdir(parents=True)
    db = env / "db"
    (db / "pubmlst" / "demo").mkdir(parents=True)
    (db / "blast").mkdir()
    (db / "VERSION.txt").write_text("2025-12-29\n")
    (db / "blast" / "mlst.fa.nsq").write_text("x")
    (db / "blast" / "mlst.fa.njs").write_text('{"files": ["mlst.fa.nsq"], "last-updated": "2026-03-11T12:33:00"}')
    (db / "pubmlst" / "demo" / "demo.txt").write_text("ST\tabc\tdef\tclonal_complex\n1\t1\t2\tCC1\n")
    (db / "pubmlst" / "demo" / "demo_info.json").write_text('{"download_date": "2026-03-11", '
                                                            '"last_updated": "2025-02-01", "source": "pubmlst"}')
    exe = env / "bin" / "mlst"
    exe.write_text(f'#!/bin/sh\ncase "$1" in --version) echo "mlst 2.35.0";; --help) cat "{HELP}";; *) exit 3;; '
                   "esac\n")
    exe.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_MLST", str(exe))
    registry._CACHE.pop("mlst", None)
    return exe


def st8_alleles(path: Path, mlst: str) -> Path:
    db = Path(os.path.realpath(mlst)).parent.parent / "db" / "pubmlst" / "saureus"
    parts = []
    for locus, n in ST8.items():
        records = (db / f"{locus}.tfa").read_text().split(">")
        parts.append(next("".join(r.splitlines()[1:]) for r in records
                          if r.split("\n", 1)[0].strip() in (f"{locus}_{n}", f"{locus}-{n}")))
    path.write_text(">TEST_saureus_ST8_alleles\n" + ("N" * 100).join(parts) + "\n")
    return path


def run(client, assembly: dict, settings: dict | None = None) -> dict:
    r = client.post(f"{API}/assemblies/{assembly['id']}/mlst", json={"settings": settings or {}, "confirmed": True})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job.get("error_message")
    return job


def test_preview_and_start_without_mlst(client):
    sample = new_sample(client, "MLST-0")
    a = assemble(client, sample, REPO / "workflows/tool-adapters/tests/fixtures/annotation_genome/genome.fna")
    plan = client.post(f"{API}/assemblies/{a['id']}/mlst/preview", json={}).json()
    assert plan["tool"]["status"] == "not_installed" and plan["database"] is None
    assert [p["code"] for p in plan["problems"]] == ["tool_unavailable"]
    r = client.post(f"{API}/assemblies/{a['id']}/mlst", json={"confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "mlst_blocked"
    assert client.post(f"{API}/assemblies/{a['id']}/mlst", json={"confirmed": False}).json()["code"] == "mlst_confirm"
    bad = client.post(f"{API}/assemblies/{a['id']}/mlst", json={"confirmed": True, "settings": {"scheme": "a b"}})
    assert bad.status_code == 422
    assert client.get(f"{API}/databases").json() == []


def test_bundled_schemes_are_a_read_only_database(client, fake_mlst):
    (record,) = client.get(f"{API}/databases").json()
    assert (record["kind"], record["origin"], record["status"], record["version"]) == (
        "mlst_schemes", DatabaseOrigin.bundled.value, "registered", "2026-03-11")
    assert record["checksum"].startswith("sha256:") and record["verification_level"] == "full"
    assert record["is_default"] and record["compatibility"]["code"] == "bundled_with_tool"
    m = record["mlst"]
    assert m["scheme_count"] == 1 and m["version_txt"] == "2025-12-29" and m["updated_after_open_terms"] == ["demo"]
    assert m["terms"]["open_until"] == "2024-12-31"
    assert len(client.get(f"{API}/databases").json()) == 1
    r = client.delete(f"{API}/databases/{record['id']}")
    assert r.status_code == 409 and r.json()["code"] == "bundled_read_only"
    verified = client.post(f"{API}/databases/{record['id']}/verify", json={"level": "quick"})
    assert verified.status_code == 202 and verified.json()["status"] == "registered"
    kinds = {k["key"]: k for k in client.get(f"{API}/databases/kinds").json()}
    assert kinds["mlst_schemes"]["download"] == "bundled"
    assert "1 January 2025" in kinds["mlst_schemes"]["licence"]


def test_preview_with_the_stand_in(client, fake_mlst):
    sample = new_sample(client, "MLST-1")
    a = assemble(client, sample, REPO / "workflows/tool-adapters/tests/fixtures/annotation_genome/genome.fna")
    plan = client.post(f"{API}/assemblies/{a['id']}/mlst/preview", json={}).json()
    assert plan["problems"] == [] and plan["tool"]["version"] == "2.35.0"
    assert plan["defaults_match"] is True and plan["tool_defaults"]["minid"] == "95"
    assert plan["schemes"] == [{"name": "demo", "loci": ["abc", "def"], "source": "pubmlst",
                                "download_date": "2026-03-11", "last_updated": "2025-02-01", "clonal_complex": True}]
    assert plan["assembly"]["synthetic_evidence"] == ["contig names", "read file SYNTHETIC_nanopore_reads.fastq.gz"]
    unknown = client.post(f"{API}/assemblies/{a['id']}/mlst/preview", json={"scheme": "saureus"}).json()
    assert [p["code"] for p in unknown["problems"]] == ["unknown_scheme"]


def test_real_mlst_types_st8_end_to_end(client, real_mlst, tmp_path):
    sample = new_sample(client, "MLST-2")
    a = assemble(client, sample, st8_alleles(tmp_path / "st8.fasta", real_mlst))
    plan = client.post(f"{API}/assemblies/{a['id']}/mlst/preview", json={}).json()
    assert plan["problems"] == [] and plan["defaults_match"] is True
    saureus = next(s for s in plan["schemes"] if s["name"] == "saureus")
    assert saureus["clonal_complex"] is False and len(saureus["loci"]) == 7
    job = run(client, a)
    assert job["database_kind"] == "mlst_schemes" and job["database_version"] == plan["database"]["version"]
    assert job["database_checksum"] == plan["database"]["checksum"] and job["database_path"].endswith("/db")
    params = job["parameters"]
    assert (params["minid"], params["mincov"], params["minscore"], params["scheme"]) == (95, 50, 50, None)
    assert params["exclude"] == ["ecoli", "abaumannii", "vcholerae_2", "senterica_achtman_2"]
    argv = job["commands"][0]
    assert argv[argv.index("--exclude") + 1] == "ecoli,abaumannii,vcholerae_2,senterica_achtman_2"
    (m,) = client.get(f"{API}/samples/{sample['id']}/mlst").json()
    assert (m["scheme"], m["st"], m["status"], m["score"]) == ("saureus", "8", "PERFECT", 100)
    assert (m["alleles"][0]["locus"], m["alleles"][0]["call"], m["alleles"][0]["type"]) == ("arcC", "3", "exact")
    assert m["clonal_complex"] == {"available": False, "column": None, "value": None, "reason": "not_in_scheme"}
    # The stand-in assembler job read ARVA's SYNTHETIC reads, so the result is marked as test data.
    codes = [w["code"] for w in m["warnings"]]
    assert codes == ["scheme_after_open_terms", "synthetic_input"]
    assert m["details"]["scheme"]["name"] == "saureus" and m["details"]["log"]["ties"] == []
    assert set(m["files"]) == {"tsv", "json", "novel", "log", "input"}
    tsv = client.get(f"{API}/mlst/{m['id']}/files/tsv")
    assert tsv.status_code == 200 and "saureus\t8\tPERFECT" in tsv.text
    assert client.get(f"{API}/mlst/{m['id']}/files/nope").status_code == 404
    results = Path(job["output_paths"][0]).parts
    assert "tmp" not in results

    overview = client.get(f"{API}/projects/{sample['project_id']}/mlst").json()
    assert overview["samples"][0]["latest"]["st"] == "8"
    assert overview["sequence_types"] == [{"scheme": "saureus", "st": "8", "samples": 1}]
    csv_text = client.get(f"{API}/projects/{sample['project_id']}/mlst.csv").text
    assert "saureus,8,PERFECT,100" in csv_text and "not available from the scheme" in csv_text
    everywhere = client.get(f"{API}/mlst").json()
    assert everywhere["total_results"] == 1 and everywhere["projects"][0]["typed_samples"] == 1

    report = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    assert report["mlst"][0]["st"] == "8" and "PubMLST" in report["mlst"][0]["warnings"][0]["text"]
    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "<h2>MLST</h2>" in html and "SYNTHETIC input" in html and "not available from the scheme" in html and "Jolley" in html
    report_csv = client.get(f"{API}/samples/{sample['id']}/report?format=csv").text
    assert ",mlst," in report_csv and "arcC(3) aroE(3)" in report_csv


def test_real_mlst_forced_scheme_and_synthetic_genome(client, real_mlst, tmp_path):
    sample = new_sample(client, "MLST-3")
    a = assemble(client, sample, st8_alleles(tmp_path / "st8.fasta", real_mlst))
    job = run(client, a, {"scheme": "ecoli_achtman_4", "minscore": 50})
    argv = job["commands"][0]
    assert argv[argv.index("--minscore") + 1] == "0" and "--exclude" not in argv
    assert job["parameters"]["exclude"] == []
    (m,) = client.get(f"{API}/samples/{sample['id']}/mlst").json()
    assert (m["scheme"], m["st"]) == ("ecoli_achtman_4", None)
    assert {x["type"] for x in m["alleles"]} == {"missing"}
    assert m["clonal_complex"]["reason"] == "no_st" and m["clonal_complex"]["column"] == "clonal_complex"
    codes = [w["code"] for w in m["warnings"]]
    assert codes[:3] == ["missing_alleles", "st_not_assigned", "scheme_forced"]
    if not SYNTHETIC.is_file():
        pytest.skip("examples/synthetic-genome is not generated")
    other = new_sample(client, "MLST-4")
    b = assemble(client, other, SYNTHETIC)
    run(client, b)
    (n,) = client.get(f"{API}/samples/{other['id']}/mlst").json()
    assert (n["scheme"], n["st"], n["status"], n["alleles"]) == (None, None, "NONE", [])
    assert [w["code"] for w in n["warnings"]] == ["no_scheme", "synthetic_input"]
    assert n["clonal_complex"]["reason"] == "no_scheme"


def test_job_refuses_changed_bundled_files(client, real_mlst, tmp_path, held_queue):
    sample = new_sample(client, "MLST-5")
    a = assemble(client, sample, st8_alleles(tmp_path / "st8.fasta", real_mlst))
    r = client.post(f"{API}/assemblies/{a['id']}/mlst", json={"confirmed": True})
    assert r.status_code == 202
    with SessionLocal() as db:
        job = db.get(AnalysisJob, r.json()["id"])
        job.database_checksum = "sha256:" + "0" * 64
        db.commit()
    run_mlst_job(r.json()["id"])
    with SessionLocal() as db:
        job = db.get(AnalysisJob, r.json()["id"])
        assert job.status is JobStatus.failed and job.error_detail["code"] == "mlst_database_changed"
        assert db.query(MlstResult).count() == 0


def test_staged_gzip_assembly_is_typed(client, real_mlst, tmp_path):
    plain = st8_alleles(tmp_path / "st8.fasta", real_mlst)
    gz = tmp_path / "st8.fasta.gz"
    with open(plain, "rb") as src, gzip.open(gz, "wb") as dst:
        shutil.copyfileobj(src, dst)
    sample = new_sample(client, "MLST-6")
    a = assemble(client, sample, plain)
    run(client, a)
    (m,) = client.get(f"{API}/samples/{sample['id']}/mlst").json()
    assert m["details"]["contigs"] == 1 and m["files"]["input"]["path"].endswith("input/genome.fna")
