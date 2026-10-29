"""Polishing: request checks by strategy, role and technology, the preview, the assembly lineage migration, and real
Racon, Pilon and hybrid runs on a draft with known errors (scripts/make_polishing_draft.py), skipped without the
tools."""
import subprocess
import sys
from pathlib import Path

import pytest
from arva_core.assembly_stats import ContigAnnotation
from arva_core.genome_view import read_depth_profile
from arva_tools import ToolStatus
from arva_tools.registry import detect

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, AssemblyMode, JobStatus
from app.services.assemblies import register_assembly
from app.tasks.common import run_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]


def ready(*tool_ids: str) -> bool:
    return all(detect(t, refresh=True).status is ToolStatus.available for t in tool_ids)


@pytest.fixture(scope="module")
def genome(tmp_path_factory):
    """A 100 kb circular chromosome and an 8 kb plasmid with Illumina-like pairs at 40x and Nanopore-like reads at
    30x, and draft.fasta: the reference with 7 substitutions, 4 insertions (5 bp) and 5 deletions (7 bp)."""
    out = tmp_path_factory.mktemp("polish") / "genome"
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_synthetic_genome.py"), str(out), "--chromosome-length",
                    "100000", "--plasmid-length", "8000", "--repeat-length", "2000", "--ont-depth", "30",
                    "--illumina-depth", "40"], check=True, capture_output=True)
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_polishing_draft.py"), str(out / "reference.fasta"),
                    str(out)], check=True, capture_output=True)
    return out


def new_sample(client, technology="hybrid"):
    p = client.post(f"{API}/projects", json={"name": "Polishing"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": "POL 1", "sequencing_technology": technology}).json()


def upload(client, sample_id, path: Path, name: str | None = None) -> str:
    r = client.post(f"{API}/samples/{sample_id}/files",
                    files=[("files", (name or path.name, path.read_bytes(), "application/octet-stream"))])
    assert r.status_code == 201, r.text
    return r.json()["files"][0]["id"]


def draft_assembly(client, sample, draft: Path, reads: list[str]) -> dict:
    """The draft registered as a Flye-like assembly (both contigs circular) by a stand-in job."""
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="assembly_test",
                          tool_name="Flye", tool_version="2.9.3", parameters={}, input_raw_file_ids=reads,
                          status=JobStatus.pending, log_text="")
        db.add(job)
        db.commit()
        job_id = job.id

    def body(ctx):
        out = ctx.path(ctx.results_rel)
        out.mkdir(parents=True)
        (out / "assembly.fasta").write_bytes(draft.read_bytes())
        register_assembly(ctx, assembler="Flye", mode=AssemblyMode.long, read_type="nano-hq",
                          contigs=out / "assembly.fasta",
                          annotations={n: ContigAnnotation(coverage=30.0, circular=True) for n in ("contig_1", "contig_2")})

    assert run_job(job_id, body) == "completed"
    (a,) = [a for a in client.get(f"{API}/samples/{sample['id']}/assemblies").json() if a["job_id"] == job_id]
    assert a["kind"] == "assembly" and a["parent_assembly_id"] is None
    return a


def polish(client, assembly_id, strategy, inputs, **body):
    return client.post(f"{API}/assemblies/{assembly_id}/polishing",
                       json={"strategy": strategy, "inputs": inputs, **body})


def job(client, job_id):
    return client.get(f"{API}/jobs/{job_id}").json()


@pytest.fixture
def setup(client, genome):
    sample = new_sample(client)
    ids = {"r1": upload(client, sample["id"], genome / "illumina_R1.fastq.gz"),
           "r2": upload(client, sample["id"], genome / "illumina_R2.fastq.gz"),
           "long": upload(client, sample["id"], genome / "ont.fastq.gz")}
    return sample, ids, draft_assembly(client, sample, genome / "draft.fasta", [ids["long"]])


def test_polishing_request_checks(client, setup, genome):
    sample, ids, draft = setup
    long, pairs = {"long_file_id": ids["long"]}, {"r1_file_id": ids["r1"], "r2_file_id": ids["r2"]}
    assert polish(client, "nope", "racon", long).status_code == 404
    cases = [
        ("racon", pairs, {}, "racon strategy needs long reads and no short reads"),
        ("pilon", long, {}, "pilon strategy needs short reads and no long reads"),
        ("hybrid", long, {}, "hybrid strategy needs both"),
        ("racon", long, {}, "Choose the long reads' type"),
        ("pilon", {"r1_file_id": ids["r1"]}, {}, "Paired-end reads need both the R1 and the R2 file"),
        ("racon", {"long_file_id": ids["r1"]}, {"racon": {"read_type": "map-ont"}}, "paired-end files hold short reads"),
    ]
    for strategy, inputs, extra, message in cases:
        r = polish(client, draft["id"], strategy, inputs, **extra)
        assert r.status_code == 400 and message in r.json()["detail"], (strategy, r.text)

    r = client.post(f"{API}/samples/{sample['id']}/analyses/sequence-stats", json={"raw_file_ids": [ids["long"]]})
    assert r.status_code in (200, 202), r.text
    r = polish(client, draft["id"], "pilon", {"r1_file_id": ids["long"], "r2_file_id": ids["r2"]})
    assert r.status_code == 400 and "so it cannot be the R1" in r.json()["detail"]

    other = new_sample(client)
    foreign = upload(client, other["id"], genome / "ont.fastq.gz")
    r = polish(client, draft["id"], "racon", {"long_file_id": foreign}, racon={"read_type": "map-ont"})
    assert r.status_code == 400 and "does not belong to this sample" in r.json()["detail"]

    client.patch(f"{API}/samples/{sample['id']}", json={"sequencing_technology": "pacbio"})
    r = polish(client, draft["id"], "racon", long, racon={"read_type": "map-ont"})
    assert r.status_code == 400 and "map-ont is for nanopore reads" in r.json()["detail"]
    client.patch(f"{API}/samples/{sample['id']}", json={"sequencing_technology": "unknown"})
    r = polish(client, draft["id"], "racon", long, racon={"read_type": "map-ont"})
    assert r.status_code == 400 and "confirm" in r.json()["detail"]
    r = polish(client, draft["id"], "racon", long, racon={"read_type": "map-ont", "rounds": 9})
    assert r.status_code == 422
    r = polish(client, draft["id"], "pilon", pairs, pilon={"fix": ["amb"]})
    assert r.status_code == 422


def test_polishing_preview_explains_strategy_tools_and_problems(client, setup):
    _, ids, draft = setup
    r = client.post(f"{API}/assemblies/{draft['id']}/polishing/preview",
                    json={"inputs": {"long_file_id": ids["long"], "r1_file_id": ids["r1"], "r2_file_id": ids["r2"]}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["strategy"] == "hybrid" and plan["suggested_strategy"] == "hybrid" and plan["problem"] is None
    assert plan["draft"]["assembly_id"] == draft["id"] and plan["draft"]["circular_contigs"] == 2
    assert set(plan["tools"]) == {"racon", "minimap2", "pilon", "java", "bwa", "samtools", "dnadiff"}
    assert [f["role"] for f in plan["files"]] == ["r1", "r2", "long"]
    assert plan["preset_suggestion"]["heuristic"] is True
    # The test computer has 64 GB; the profile's memory per job (44 GB) exceeds Debian's 16 GB default heap.
    assert (plan["default_heap_gb"], plan["max_memory_gb"], plan["default_threads"], plan["max_threads"]) == (16, 64, 4, 4)
    only_pairs = client.post(f"{API}/assemblies/{draft['id']}/polishing/preview",
                             json={"inputs": {"r1_file_id": ids["r1"]}}).json()
    assert only_pairs["strategy"] == "pilon" and "R2" in only_pairs["problem"]
    none = client.post(f"{API}/assemblies/{draft['id']}/polishing/preview", json={"inputs": {}}).json()
    assert none["strategy"] is None and none["problem"].startswith("Choose the reads to polish with")


def test_lineage_migration_up_and_down_on_a_scratch_database(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.db.session import engine

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch_lineage")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_lineage"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch_lineage"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    insert = ("INSERT INTO assemblies (id, sample_id, job_id, assembler, assembler_version, mode, read_type, "
              "input_file_ids, contigs_path, stats, contigs, warnings, created_at{extra}) VALUES ('{id}', 's', '{job}', "
              "'Flye', '2.9.3', 'long', 'nano-hq', '[]', 'x', '{{}}', '[]', '[]', now(){values})")
    try:
        command.upgrade(cfg, "b5c2e81f4a97")
        with db.begin() as c:
            c.execute(text("INSERT INTO projects (id, name, is_demo, created_at, updated_at) VALUES ('p', 'P', false, now(), now())"))
            c.execute(text("INSERT INTO samples (id, project_id, sample_code, sequencing_technology, created_at, "
                           "updated_at) VALUES ('s', 'p', 'S', 'unknown', now(), now())"))
            for j in ("j1", "j2"):
                c.execute(text(f"INSERT INTO analysis_jobs (id, project_id, sample_id, job_type, tool_name, tool_version, "
                               f"status, created_at, updated_at) VALUES ('{j}', 'p', 's', 'x', 'X', '1', 'completed', "
                               "now(), now())"))
            c.execute(text(insert.format(extra="", id="a1", job="j1", values="")))
        command.upgrade(cfg, "head")
        with db.begin() as c:
            assert c.execute(text("SELECT kind, parent_assembly_id FROM assemblies")).one() == ("assembly", None)
            fk = c.execute(text("SELECT confdeltype FROM pg_constraint WHERE conname = "
                                "'fk_assemblies_parent_assembly_id'")).scalar()
            assert fk == "n"
            c.execute(text(insert.format(extra=", kind, parent_assembly_id", id="a2", job="j2",
                                         values=", 'polished', 'a1'")))
        with pytest.raises(RuntimeError, match="1 polished assembly record"):
            command.downgrade(cfg, "b5c2e81f4a97")
        with db.begin() as c:
            c.execute(text("DELETE FROM assemblies WHERE id = 'a1'"))
            assert c.scalar(text("SELECT parent_assembly_id FROM assemblies WHERE id = 'a2'")) is None
            c.execute(text("DELETE FROM assemblies WHERE id = 'a2'"))
            c.execute(text(insert.format(extra=", kind", id="a3", job="j1", values=", 'assembly'")))
        command.downgrade(cfg, "b5c2e81f4a97")
        with db.begin() as c:
            cols = {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns "
                                                 "WHERE table_name = 'assemblies'"))}
            assert not {"kind", "parent_assembly_id"} & cols
            assert c.scalar(text("SELECT id FROM assemblies")) == "a3"
        command.upgrade(cfg, "head")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_lineage"))


@pytest.mark.skipif(not ready("racon", "minimap2", "samtools", "dnadiff"), reason="needs Racon, minimap2, samtools, MUMmer")
def test_racon_polishes_the_draft_and_reports_direct_and_indirect_evidence(client, setup, storage_root):
    sample, ids, draft = setup
    r = polish(client, draft["id"], "racon", {"long_file_id": ids["long"]},
               racon={"read_type": "map-ont", "rounds": 2}, threads=2)
    assert r.status_code == 202, r.text
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    assert d["job_type"] == "racon_polish" and d["tool_name"] == "Racon"
    p = d["parameters"]
    assert (p["rounds"], p["read_type"], p["match"], p["mismatch"], p["gap"], p["window_length"]) == (2, "map-ont", 3, -5,
                                                                                                    -4, 500)
    assert p["draft"]["assembly_id"] == draft["id"] and p["strategy"] == "racon"
    racon_runs = [c for c in d["commands"] if Path(c[0]).name == "racon"]
    assert len(racon_runs) == 2 and all("-u" in c for c in racon_runs)
    s = d["result_summary"]
    assert s["rounds_run"] == 2 and [r["round"] for r in s["rounds"]] == [1, 2]
    first = s["rounds"][0]
    assert first["changes_source"] == "dnadiff" and first["changes"]["snp"]["events"] == 7
    assert len(first["commands"]) == 3  # minimap2, racon, dnadiff
    assert s["direct"]["source"] == "dnadiff" and s["direct"]["dnadiff"]["events"]["substitutions"] == 7
    assert s["indirect"]["before"]["stats"]["reads_mapped"] > 0 and s["indirect"]["aligner"].startswith("minimap2")
    assert {o["code"] for o in s["observations"]} >= {"ends_trimmed"}
    trimmed = next(o for o in s["observations"] if o["code"] == "ends_trimmed")
    assert trimmed["params"]["circular"] is True
    names = {Path(o).name for o in d["output_paths"]}
    assert {"polished.fasta", "round1.fasta", "dnadiff_round1.report", "dnadiff_overall.snps", "draft.samtools_stats.txt",
            "polished.samtools_coverage.tsv", "round2.racon.log"} <= names
    assert not any("/work/" in o for o in d["output_paths"])
    assert not any(o.endswith(".depth.tsv.gz") for o in d["output_paths"])
    for side in ("before", "after"):
        # The depth profile's mean equals samtools coverage's mean depth (deletions are not counted by either).
        entry = s["indirect"][side]["depth_profile"]
        profile = read_depth_profile(storage_root / entry["path"])
        assert entry["resolution"] == profile["resolution"] == 25
        assert [c["length"] for c in profile["contigs"]] == [r["length"] for r in s["indirect"][side]["coverage"]]
        for c, row in zip(profile["contigs"], s["indirect"][side]["coverage"], strict=True):
            assert c["mean_depth"] == pytest.approx(row["mean_depth"], abs=1e-3)
    assert Path(s["indirect"]["after"]["depth_profile"]["path"]).name == "polished.depth_profile.json"
    assert any(Path(c[0]).name == "samtools" and c[1] == "depth" and "-aa" in c for c in d["commands"])

    polished = client.get(f"{API}/assemblies/{s['polished_assembly_id']}").json()
    assert (polished["kind"], polished["parent_assembly_id"], polished["assembler"]) == ("polished", draft["id"], "Racon")
    assert polished["coverage_kind"] == "mapped_read_depth" and polished["read_type"] == "map-ont"
    assert polished["input_file_ids"] == [ids["long"]] and polished["mode"] == "long"
    assert [c["circular"] for c in polished["contigs"]] == [True, True]
    assert all(c["coverage"] > 10 for c in polished["contigs"])

    report = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
    entry = next(a for a in report["assemblies"] if a["id"] == polished["id"])
    assert entry["kind"] == "polished" and entry["parent_assembly_id"] == draft["id"]
    assert entry["polishing"]["direct_evidence"]["dnadiff_events"]["substitutions"] == 7
    step = next(st for st in report["processing"] if st["job_id"] == d["id"])
    assert step["highlights"][1].startswith("Round 1 changes (direct evidence, dnadiff): snp 7 (7 bp)")
    html = client.get(f"{API}/samples/{sample['id']}/report").text
    assert "Direct evidence" in html and "Indirect indicators" in html and "polished from assembly" in html
    assert "not of improvement" in html


@pytest.mark.skipif(not ready("pilon", "bwa", "samtools", "dnadiff"), reason="needs Pilon, BWA, samtools, MUMmer")
def test_pilon_corrects_the_draft_lists_changes_and_stops_when_nothing_changes(client, setup, monkeypatch, storage_root):
    monkeypatch.setattr(get_settings(), "tool_memory_gb", 4)
    _, ids, draft = setup
    r = polish(client, draft["id"], "pilon", {"r1_file_id": ids["r1"], "r2_file_id": ids["r2"]},
               pilon={"rounds": 3, "heap_gb": 2}, threads=2)
    assert r.status_code == 202, r.text
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    assert d["tool_name"] == "Pilon" and d["tool_version"] == "1.24" and d["tool_path"].endswith(".jar")
    pilon_runs = [c for c in d["commands"] if "-jar" in c]
    assert pilon_runs and all(c[1] == "-Xmx2g" and "--changes" in c for c in pilon_runs)
    assert pilon_runs[0][pilon_runs[0].index("--fix") + 1] == "snps,indels,gaps,local"
    s = d["result_summary"]
    assert s["rounds_run"] == 2 and s["stopped_early"] is True
    first, second = s["rounds"]
    assert {k: (v["events"], v["bases"]) for k, v in first["pilon_changes"].items()} == {
        "snp": (7, 7), "insertion": (5, 7), "deletion": (4, 5), "other": (0, 0)}
    assert first["changes"] == first["pilon_changes"]
    assert sum(v["events"] for v in second["pilon_changes"].values()) == 0
    assert s["direct"]["pilon_changes"]["snp"]["events"] == 7
    before, after = s["indirect"]["before"]["stats"], s["indirect"]["after"]["stats"]
    assert after["edit_distance_per_100_bases"] < before["edit_distance_per_100_bases"]
    assert s["indirect"]["reads"] == "paired-end"
    profile = read_depth_profile(storage_root / s["indirect"]["after"]["depth_profile"]["path"])
    assert [c["name"] for c in profile["contigs"]] == ["contig_1_pilon_pilon", "contig_2_pilon_pilon"]
    assert [st for st in d["progress"]["stages"]] == ["pilon_round_1", "pilon_round_2", "alignment_stats", "comparison"]

    polished = client.get(f"{API}/assemblies/{s['polished_assembly_id']}").json()
    assert polished["assembler"] == "Pilon" and polished["read_type"] == "paired-end"
    assert [c["name"] for c in polished["contigs"]] == ["contig_1_pilon_pilon", "contig_2_pilon_pilon"]
    assert [c["circular"] for c in polished["contigs"]] == [True, True]
    assert polished["stats"]["total_length"] == 108_000


@pytest.mark.skipif(not ready("racon", "minimap2", "pilon", "bwa", "samtools", "dnadiff"),
                    reason="needs Racon, minimap2, Pilon, BWA, samtools, MUMmer")
def test_hybrid_runs_racon_then_pilon_on_its_result(client, setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "tool_memory_gb", 4)
    sample, ids, draft = setup
    quast = ready("quast")
    r = polish(client, draft["id"], "hybrid", {"long_file_id": ids["long"], "r1_file_id": ids["r1"],
                                               "r2_file_id": ids["r2"]},
               racon={"read_type": "map-ont"}, pilon={"heap_gb": 2}, threads=2, quast=quast)
    assert r.status_code == 202, r.text
    racon = job(client, r.json()["id"])
    assert racon["status"] == "completed", racon["log_text"]
    pilon_id = racon["result_summary"]["followups"]["pilon_job_id"]
    pilon = job(client, pilon_id)
    assert pilon["status"] == "completed", pilon["log_text"]
    assert pilon["parent_job_id"] == racon["id"] and pilon["parameters"]["strategy"] == "hybrid"
    first = racon["result_summary"]["polished_assembly_id"]
    assert pilon["parameters"]["draft"]["assembly_id"] == first
    final = client.get(f"{API}/assemblies/{pilon['result_summary']['polished_assembly_id']}").json()
    middle = client.get(f"{API}/assemblies/{first}").json()
    assert (final["parent_assembly_id"], middle["parent_assembly_id"]) == (first, draft["id"])
    if quast:
        q = job(client, pilon["result_summary"]["followups"]["quast_job_id"])
        assert q["status"] == "completed", q["log_text"]
        assert [a["assembly_id"] for a in q["parameters"]["assemblies"]] == [draft["id"], first, final["id"]]
    project = client.get(f"{API}/projects/{sample['project_id']}/assemblies").json()
    assert {(a["kind"], a["assembler"]) for a in project} == {("assembly", "Flye"), ("polished", "Racon"),
                                                              ("polished", "Pilon")}


@pytest.mark.skipif(not ready("flye", "racon", "minimap2", "samtools", "dnadiff"),
                    reason="needs Flye, Racon, minimap2, samtools, MUMmer")
def test_racon_on_a_flye_assembly_reports_its_changes(client, genome):
    """A real Flye draft of the synthetic reads, polished by Racon through the API: the changes are reported as
    direct evidence, whatever they are (Racon also changes a draft that is already correct)."""
    sample = new_sample(client, "nanopore")
    long = upload(client, sample["id"], genome / "ont.fastq.gz")
    r = client.post(f"{API}/samples/{sample['id']}/assembly/flye",
                    json={"raw_file_ids": [long], "params": {"read_type": "nano-hq", "threads": 2}})
    assert r.status_code == 202, r.text
    assert job(client, r.json()["id"])["status"] == "completed"
    (flye,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    r = polish(client, flye["id"], "racon", {"long_file_id": long}, racon={"read_type": "map-ont"}, threads=2)
    d = job(client, r.json()["id"])
    assert d["status"] == "completed", d["log_text"]
    s = d["result_summary"]
    diff = s["direct"]["dnadiff"]
    assert diff is not None and diff["before"]["bases"] == flye["stats"]["total_length"]
    assert set(s["rounds"][0]["changes"]) == {"snp", "insertion", "deletion", "other"}
    assert s["assembly_stats"]["before"]["contig_count"] == s["assembly_stats"]["after"]["contig_count"]
    polished = client.get(f"{API}/assemblies/{s['polished_assembly_id']}").json()
    assert polished["parent_assembly_id"] == flye["id"]


@pytest.mark.skipif(not ready("racon", "minimap2", "samtools"), reason="needs Racon, minimap2, samtools")
def test_a_changed_draft_is_refused_and_leaves_nothing(client, setup, storage_root):
    sample, ids, draft = setup
    path = storage_root / draft["contigs_path"]
    path.chmod(0o644)
    path.write_text(path.read_text().replace("A", "C", 1))
    d = job(client, polish(client, draft["id"], "racon", {"long_file_id": ids["long"]},
                           racon={"read_type": "map-ont"}).json()["id"])
    assert d["status"] == "failed" and "changed since the job was queued" in d["error_message"]
    assert len(client.get(f"{API}/samples/{sample['id']}/assemblies").json()) == 1
