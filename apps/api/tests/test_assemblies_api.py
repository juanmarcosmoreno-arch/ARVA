"""Assembly records: registration inside a job, statistics, heuristic warnings, downloads and the graph.

A stand-in assembler body writes Flye-like outputs into the job's results folder, so these tests need no
assembler; runs of real assemblers are tested with their adapters.
"""
import hashlib
import stat
from pathlib import Path

import pytest
from arva_core.assembly_stats import ContigAnnotation

from app.db.session import SessionLocal
from app.models import AnalysisJob, Assembly, AssemblyMode, JobStatus
from app.services import assemblies
from app.services.assemblies import register_assembly
from app.tasks.common import run_job

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"

# 100 kb at 50 % GC, 4 kb at 75 % GC, 2 kb at 0 % GC: 106,000 bp, assembly GC 50 %.
CONTIGS = ">contig_1\n" + "ACGT" * 25_000 + "\n>contig_2\n" + "GGCA" * 1000 + "\n>contig_3\n" + "AT" * 1000 + "\n"
NOTES = {"contig_1": ContigAnnotation(coverage=50, circular=False, repeat=False),
         "contig_2": ContigAnnotation(coverage=250, circular=True, repeat=False),
         "contig_3": ContigAnnotation(coverage=5, circular=False, repeat=False)}
INFO = "#seq_name\tlength\tcov.\tcirc.\trepeat\tmult.\talt_group\tgraph_path\n"
GFA = ("H\tVN:Z:1.0\nS\tedge_1\t" + "ACGT" * 25_000 + "\tdp:i:50\nS\tedge_2\t" + "GGCA" * 1000 + "\tdp:i:250\n"
       "L\tedge_1\t+\tedge_1\t+\t0M\tRC:i:12\nL\tedge_2\t+\tedge_2\t+\t0M\n")


@pytest.fixture
def sample(client):
    p = client.post(f"{API}/projects", json={"name": "Assembly"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples", json={"sample_code": "ISO 7/A"}).json()


def upload(client, sample_id, path):
    r = client.post(f"{API}/samples/{sample_id}/files", files=[("files", (path.name, path.read_bytes(), "x"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]


def new_job(sample, files, parameters=None) -> str:
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="assembly_test",
                          tool_name="TestAssembler", tool_version="0.1", parameters=parameters or {},
                          input_raw_file_ids=[f["id"] for f in files], status=JobStatus.pending, log_text="")
        db.add(job)
        db.commit()
        return job.id


def stand_in(contigs=CONTIGS, graph=GFA, notes=NOTES, contigs_at=None):
    def body(ctx):
        out = ctx.path(ctx.results_rel)
        out.mkdir(parents=True)
        (out / "assembly.fasta").write_text(contigs)
        (out / "assembly_info.txt").write_text(INFO)
        if graph is not None:
            (out / "assembly_graph.gfa").write_text(graph)
        register_assembly(
            ctx, assembler="TestAssembler", mode=AssemblyMode.long, read_type="nano-hq",
            contigs=contigs_at(ctx) if contigs_at else out / "assembly.fasta",
            graph=out / "assembly_graph.gfa" if graph is not None else None, info=out / "assembly_info.txt",
            annotations=notes,
        )
        ctx.job.output_paths = [str(p.relative_to(ctx.storage.root)) for p in sorted(out.iterdir())]
    return body


def assemble(client, sample, files, **kwargs) -> dict:
    job_id = new_job(sample, files, kwargs.pop("parameters", None))
    assert run_job(job_id, stand_in(**kwargs)) == "completed", client.get(f"{API}/jobs/{job_id}").json()["log_text"]
    (a,) = [a for a in client.get(f"{API}/samples/{sample['id']}/assemblies").json() if a["job_id"] == job_id]
    return a


def test_assembly_is_recorded_with_statistics_lineage_and_warnings(client, sample, storage_root):
    reads = upload(client, sample["id"], ONT)
    a = assemble(client, sample, [reads])
    assert (a["assembler"], a["assembler_version"], a["mode"], a["read_type"]) == ("TestAssembler", "0.1", "long", "nano-hq")
    assert a["input_file_ids"] == [reads["id"]]
    s = a["stats"]
    assert (s["contig_count"], s["total_length"], s["largest_contig"], s["n50"], s["l50"]) == (3, 106_000, 100_000, 100_000, 1)
    assert s["gc_percent"] == pytest.approx(50.0) and s["n_count"] == 0
    assert s["coverage"] == {"contigs_with_coverage": 3, "length_weighted_median": 50.0}
    assert s["contig_rows"] == {"stored": 3, "total": 3, "truncated": False}
    assert s["expected_genome_size"] == {"bp": None, "status": "not_given", "source": None, "basis": None,
                                       "assumed_depth_x": None}
    assert s["tool"]["name"] == "arva-core.assembly_stats"
    # Outputs stay in the job's results folder, checksummed and read-only; no read file is registered.
    for key, name in (("contigs", "assembly.fasta"), ("graph", "assembly_graph.gfa"), ("info", "assembly_info.txt")):
        f = s["files"][key]
        assert f["path"].startswith(f"results/{sample['project_id']}/{sample['id']}/{a['job_id']}/") and f["path"].endswith(name)
        path = storage_root / f["path"]
        assert f["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and f["size_bytes"] == path.stat().st_size
        assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    assert a["contigs_path"] == s["files"]["contigs"]["path"] and a["graph_path"] == s["files"]["graph"]["path"]
    assert [f["id"] for f in client.get(f"{API}/samples/{sample['id']}/files").json()] == [reads["id"]]

    codes = {w["code"]: w for w in a["warnings"]}
    assert set(codes) == {"low_coverage_contigs", "high_coverage_contigs", "chromosome_not_circular", "gc_outlier_contigs"}
    assert all(w["heuristic"] is True for w in a["warnings"])
    assert codes["low_coverage_contigs"]["contigs"] == ["contig_3"]
    assert codes["high_coverage_contigs"]["contigs"] == ["contig_2"]
    assert codes["chromosome_not_circular"]["contigs"] == ["contig_1"]
    checks = {c["code"]: c for c in s["warning_checks"]}
    assert len(checks) == 6 and checks["genome_size_mismatch"]["evaluated"] is False

    detail = client.get(f"{API}/assemblies/{a['id']}").json()
    assert [(c["rank"], c["name"], c["length"], c["coverage"], c["circular"]) for c in detail["contigs"]] == [
        (1, "contig_1", 100_000, 50.0, False), (2, "contig_2", 4000, 250.0, True), (3, "contig_3", 2000, 5.0, False)]
    assert detail["contigs"][1]["gc_percent"] == pytest.approx(75.0)
    log = client.get(f"{API}/jobs/{a['job_id']}").json()["log_text"]
    assert "Assembly: 3 contigs, 106,000 bp, N50 100,000 bp" in log
    assert "Heuristic warning [low_coverage_contigs]" in log


def test_contigs_download_and_graph(client, sample):
    a = assemble(client, sample, [upload(client, sample["id"], ONT)])
    r = client.get(f"{API}/assemblies/{a['id']}/contigs.fasta")
    assert r.status_code == 200 and r.text == CONTIGS
    assert f'filename="ISO_7_A_TestAssembler_{a["id"][:8]}_contigs.fasta"' in r.headers["content-disposition"]

    g = client.get(f"{API}/assemblies/{a['id']}/graph").json()
    assert (g["assembly_id"], g["format"], g["segment_count"], g["link_count"], g["truncated"]) == (a["id"], "GFA1", 2, 2, False)
    assert g["nodes"][0] == {"id": "edge_1", "length": 100_000, "tags": {"dp": 50}}
    assert g["edges"][0] == {"source": "edge_1", "source_orientation": "+", "target": "edge_1",
                             "target_orientation": "+", "overlap": "0M", "tags": {"RC": 12}}
    capped = client.get(f"{API}/assemblies/{a['id']}/graph", params={"max_nodes": 1, "max_edges": 0}).json()
    assert ([n["id"] for n in capped["nodes"]], capped["edges"], capped["truncated"]) == (["edge_1"], [], True)
    assert client.get(f"{API}/assemblies/{a['id']}/graph", params={"max_nodes": 0}).status_code == 422
    assert client.get(f"{API}/assemblies/{a['id']}/graph", params={"max_nodes": 20_001}).status_code == 422


def test_expected_genome_size_comes_from_parameters_or_consistent_statistics(client, sample):
    reads = upload(client, sample["id"], ONT)
    r = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                    json={"raw_file_ids": [reads["id"]], "expected_genome_size_bp": 200_000})
    assert r.status_code == 202, r.text
    a = assemble(client, sample, [reads])
    assert a["stats"]["expected_genome_size"] == {"bp": 200_000, "status": "given", "source": "read_statistics",
                                                  "basis": None, "assumed_depth_x": None}
    (w,) = [w for w in a["warnings"] if w["code"] == "genome_size_mismatch"]
    assert w["params"]["difference_percent"] == -47.0 and w["params"]["tolerance_percent"] == 20

    # Given for the assembly itself: it takes precedence, and 106,000 bp is within 20 % of 110,000 bp.
    b = assemble(client, sample, [reads], parameters={"genome_size_bp": 110_000})
    assert b["stats"]["expected_genome_size"] == {"bp": 110_000, "status": "given", "source": "assembly_parameters",
                                                  "basis": None, "assumed_depth_x": None}
    assert "genome_size_mismatch" not in {w["code"] for w in b["warnings"]}

    other = upload(client, sample["id"], R1)
    client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats",
                json={"raw_file_ids": [other["id"]], "expected_genome_size_bp": 150_000})
    c = assemble(client, sample, [reads])
    assert c["stats"]["expected_genome_size"] == {"bp": None, "status": "inconsistent", "source": None, "basis": None,
                                                  "assumed_depth_x": None}
    check = next(x for x in c["stats"]["warning_checks"] if x["code"] == "genome_size_mismatch")
    assert check["evaluated"] is False


def test_contig_rows_are_bounded_but_statistics_use_every_contig(client, sample, monkeypatch):
    monkeypatch.setattr(assemblies, "MAX_CONTIG_ROWS", 2)
    a = client.get(f"{API}/assemblies/{assemble(client, sample, [upload(client, sample['id'], ONT)])['id']}").json()
    assert [c["name"] for c in a["contigs"]] == ["contig_1", "contig_2"]
    assert a["stats"]["contig_rows"] == {"stored": 2, "total": 3, "truncated": True}
    assert a["stats"]["contig_count"] == 3 and "low_coverage_contigs" in {w["code"] for w in a["warnings"]}


@pytest.mark.parametrize("kwargs,message", [
    (dict(contigs=">a\nACGT\n>a\nACGT\n"), "TestAssembler wrote contigs that cannot be read: line 3: contig name 'a'"),
    (dict(notes={"elsewhere": ContigAnnotation(coverage=1)}), "not in the FASTA file: elsewhere"),
    (dict(contigs_at=lambda ctx: ctx.path(ctx.input_files()[0].stored_path)), "is not a file in this job's results folder"),
])
def test_failures_register_nothing(client, sample, storage_root, kwargs, message):
    job_id = new_job(sample, [upload(client, sample["id"], ONT)])
    assert run_job(job_id, stand_in(**kwargs)) == "failed"
    job = client.get(f"{API}/jobs/{job_id}").json()
    assert message in job["error_message"]
    assert client.get(f"{API}/samples/{sample['id']}/assemblies").json() == []
    assert not (storage_root / f"results/{sample['project_id']}/{sample['id']}/{job_id}").exists()


def test_missing_graph_files_and_unknown_assemblies(client, sample, storage_root):
    reads = upload(client, sample["id"], ONT)
    a = assemble(client, sample, [reads], graph=None)
    assert a["graph_path"] is None and a["stats"]["files"]["graph"] is None
    r = client.get(f"{API}/assemblies/{a['id']}/graph")
    assert r.status_code == 404 and r.json()["detail"] == "This assembly has no assembly graph"

    b = assemble(client, sample, [reads], graph="H\tVN:Z:1.0\nS\tx\n")
    r = client.get(f"{API}/assemblies/{b['id']}/graph")
    assert r.status_code == 422 and "line 2: segment line needs a name" in r.json()["detail"]

    (storage_root / b["contigs_path"]).unlink()
    (storage_root / b["graph_path"]).unlink()
    assert client.get(f"{API}/assemblies/{b['id']}/contigs.fasta").status_code == 404
    assert client.get(f"{API}/assemblies/{b['id']}/graph").json()["detail"] == "The graph file is missing on disk"
    for path in ("", "/contigs.fasta", "/graph"):
        assert client.get(f"{API}/assemblies/nope{path}").status_code == 404
    assert client.get(f"{API}/samples/nope/assemblies").status_code == 404


def test_deleting_the_sample_or_job_removes_the_record(client, sample):
    a = assemble(client, sample, [upload(client, sample["id"], ONT)])
    with SessionLocal() as db:
        db.delete(db.get(AnalysisJob, a["job_id"]))
        db.commit()
        assert db.get(Assembly, a["id"]) is None
    b = assemble(client, sample, [upload(client, sample["id"], R1)])
    assert client.delete(f"{API}/samples/{sample['id']}").status_code == 204
    assert client.get(f"{API}/assemblies/{b['id']}").status_code == 404
