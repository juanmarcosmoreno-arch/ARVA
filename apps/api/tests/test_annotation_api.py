"""Genome annotation: request checks, previews, the recorded job, features (query, detail, links), the annotators'
files and exports, the run-time re-check, contig renaming and the migration.

The assembly is workflows/tool-adapters/tests/fixtures/annotation_genome/genome.fna (SYNTHETIC: random ORFs, three
back-translated Swiss-Prot proteins, sequences sampled from RNA models; see its README), registered through a
stand-in assembler job. Query and export tests use an annotation registered from Prokka's real output on that genome
(the fixture files); the end-to-end tests run Bakta (with the light database) and Prokka and are skipped without
them. Results on this genome are not biology.
"""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from arva_core.annotation import write_jsonl
from arva_tools import ToolStatus
from arva_tools.prokka import ProkkaAdapter, database_info, database_source
from arva_tools.registry import detect

from app.db.session import SessionLocal
from app.models import AnalysisJob, Annotation, AssemblyMode, DatabaseOrigin, DatabaseStatus, JobStatus
from app.models import ReferenceDatabase as RefDb
from app.services import annotation as svc
from app.services.assemblies import register_assembly
from app.tasks import annotation as annotation_tasks
from app.tasks.common import run_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures"
GENOME = FIXTURES / "annotation_genome" / "genome.fna"
ONT = REPO / "examples" / "synthetic" / "SYNTHETIC_nanopore_reads.fastq.gz"
BAKTA_DB = Path(os.environ.get("ARVA_TEST_BAKTA_DB", "/root/.arva-db/bakta-light/6.0"))
# The content checksum ARVA computed for the light database 6.0 when it installed it (Part 4A).
BAKTA_DB_CHECKSUM = "sha256:93a75bf1a4b9e65b0e03b9136c4fd434925ae2c075f9fdc9c8a99f930e0c7d9c"


def available(tool_id: str) -> bool:
    return detect(tool_id, refresh=True).status is ToolStatus.available


def prokka_ready() -> bool:
    d = detect("prokka", refresh=True)
    return d.status is ToolStatus.available and database_info(database_source(d.path))["ready"]


def new_sample(client, code="ANN-1"):
    p = client.post(f"{API}/projects", json={"name": "Annotation"}).json()
    return client.post(f"{API}/projects/{p['id']}/samples",
                       json={"sample_code": code, "sequencing_technology": "nanopore"}).json()


def assemble(client, sample, fasta: Path, assembler="Flye", version="2.9.3") -> dict:
    r = client.post(f"{API}/samples/{sample['id']}/files",
                    files=[("files", (ONT.name, ONT.read_bytes(), "application/octet-stream"))])
    reads = r.json()["files"][0]
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

    assert run_job(job_id, body) == "completed"
    (a,) = [a for a in client.get(f"{API}/samples/{sample['id']}/assemblies").json() if a["job_id"] == job_id]
    return a


@pytest.fixture
def setup(client):
    sample = new_sample(client)
    return sample, assemble(client, sample, GENOME)


@pytest.fixture
def bakta_db():
    if not (BAKTA_DB / "version.json").is_file():
        pytest.skip("no Bakta light database installed")
    with SessionLocal() as db:
        record = RefDb(key="bakta-light", name="Bakta database (light)", version="6.0", path=str(BAKTA_DB),
                       status=DatabaseStatus.installed, origin=DatabaseOrigin.download, checksum=BAKTA_DB_CHECKSUM,
                       details={"version_json": json.loads((BAKTA_DB / "version.json").read_text())}, log_text="")
        db.add(record)
        db.commit()
        return record.id


def prokka_fixture_annotation(storage_root: Path, sample: dict, assembly: dict) -> str:
    """An annotation registered from Prokka's real output files on the fixture genome."""
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="prokka_annotation",
                          tool_name="Prokka", tool_version="1.14.6", parameters={}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        db.add(job)
        db.commit()
        rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}"
        out = storage_root / rel / "prokka"
        out.mkdir(parents=True)
        files = {}
        for kind, suffix in (("gff3", "gff"), ("genbank", "gbk"), ("ffn", "ffn"), ("faa", "faa"), ("tsv", "tsv")):
            shutil.copyfile(FIXTURES / "prokka" / f"annotation.{suffix}", out / f"annotation.{suffix}")
            files[kind] = {"path": f"{rel}/prokka/annotation.{suffix}", "sha256": "-", "size_bytes": 1}
        sequences, features = ProkkaAdapter.parse_gff((out / "annotation.gff").read_text())
        write_jsonl(storage_root / rel / "features.jsonl", features)
        a = Annotation(sample_id=sample["id"], assembly_id=assembly["id"], job_id=job.id, tool="Prokka",
                       tool_version="1.14.6", parameters={}, steps={}, summary={}, sequences=sequences, files=files,
                       features_path=f"{rel}/features.jsonl")
        db.add(a)
        db.commit()
        return a.id


def bakta_request(plan: dict, **settings) -> dict:
    return {"settings": {"locus_tag": "SYNT", **settings}, "skip_options": plan["skip_options"], "confirmed": True,
            "threads": 2}


# --- Queries, details, files and exports (Prokka's real output, no tools needed) ----------------------------------

def test_feature_queries_details_and_links(client, setup, storage_root):
    sample, assembly = setup
    ann = prokka_fixture_annotation(storage_root, sample, assembly)
    page = client.get(f"{API}/annotations/{ann}/features").json()
    assert page["total"] == 20 and page["max_limit"] == 1000
    assert page["items"][0]["contig_in_assembly"] == "SYNTHETIC_annotation_chromosome"
    cds = client.get(f"{API}/annotations/{ann}/features", params={"type": "cds", "hypothetical": "false"}).json()
    assert [f["gene"] for f in cds["items"]] == ["alkA", "tag", "quiB"]
    assert client.get(f"{API}/annotations/{ann}/features", params={"q": "COG0710"}).json()["items"][0]["gene"] == "quiB"
    region = client.get(f"{API}/annotations/{ann}/features", params={
        "contig": "SYNTHETIC_annotation_chromosome", "start": 9264, "end": 9300}).json()
    assert [f["locus_tag"] for f in region["items"]] == ["SYNT_00009"]
    by_length = client.get(f"{API}/annotations/{ann}/features",
                           params={"sort": "length", "descending": "true", "limit": 1}).json()
    assert by_length["total"] == 20 and len(by_length["items"]) == 1 and by_length["items"][0]["type"] == "rrna"
    detail = client.get(f"{API}/annotations/{ann}/features/{cds['items'][0]['id']}").json()
    assert detail["protein"]["sequence"].startswith("M") and detail["protein"]["length"] == 282
    assert len(detail["nucleotide"]["sequence"]) == 849
    assert {link["url"] for link in detail["links"]} == {
        "https://www.ncbi.nlm.nih.gov/research/cog/cog/COG0122/", "https://enzyme.expasy.org/EC/3.2.2.21",
        "https://www.uniprot.org/uniprotkb/P04395/entry"}
    trna = client.get(f"{API}/annotations/{ann}/features", params={"type": "trna"}).json()["items"][0]
    assert client.get(f"{API}/annotations/{ann}/features/{trna['id']}").json()["protein"] is None
    assert client.get(f"{API}/annotations/{ann}/features/999").status_code == 404


@pytest.mark.parametrize("params", [{"limit": 1001}, {"sort": "colour"}, {"start": 5}, {"contig": "c", "start": 9,
                                                                                         "end": 3}, {"offset": -1}])
def test_feature_query_bounds(client, setup, storage_root, params):
    sample, assembly = setup
    ann = prokka_fixture_annotation(storage_root, sample, assembly)
    assert client.get(f"{API}/annotations/{ann}/features", params=params).status_code == 422


def test_exports_and_files(client, setup, storage_root):
    sample, assembly = setup
    ann = prokka_fixture_annotation(storage_root, sample, assembly)
    full = client.get(f"{API}/annotations/{ann}/export/gff3")
    assert full.status_code == 200 and "##FASTA" in full.text
    assert full.headers["x-content-type-options"] == "nosniff" and "attachment" in full.headers["content-disposition"]
    ids = [f["id"] for f in client.get(f"{API}/annotations/{ann}/features", params={"q": "glycosylase"}).json()["items"]]
    gff = client.post(f"{API}/annotations/{ann}/export", json={"format": "gff3", "feature_ids": ids})
    assert [ln.split("\t")[8].split(";")[0] for ln in gff.text.splitlines() if not ln.startswith("#")] == [
        "ID=SYNT_00009", "ID=SYNT_00012"]
    assert "selected_gff3" in gff.headers["content-disposition"]
    gbk = client.post(f"{API}/annotations/{ann}/export", json={"format": "genbank", "feature_ids": ids}).text
    assert gbk.count('/locus_tag="SYNT_000') == 2 and "ORIGIN" in gbk
    faa = client.post(f"{API}/annotations/{ann}/export", json={"format": "fasta_aa", "feature_ids": ids}).text
    assert faa.count(">") == 2
    table = client.post(f"{API}/annotations/{ann}/export", json={"format": "tsv", "feature_ids": ids[:1]}).text
    header, row = table.splitlines()
    assert header.split("\t")[:4] == ["id", "locus_tag", "type", "contig"]
    assert row.split("\t")[1:3] == ["SYNT_00009", "cds"] and "UniProtKB:P04395" not in row.split("\t")[15]
    assert client.post(f"{API}/annotations/{ann}/export", json={"format": "tsv", "feature_ids": [12345]}).status_code == 400
    assert client.post(f"{API}/annotations/{ann}/export", json={"format": "xml"}).status_code == 422
    assert client.get(f"{API}/annotations/{ann}/export/xml").status_code == 400
    f = client.get(f"{API}/annotations/{ann}/files/genbank")
    assert f.status_code == 200 and f.text.startswith("LOCUS") and "attachment" in f.headers["content-disposition"]
    assert f.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert client.get(f"{API}/annotations/{ann}/files/plot_png").status_code == 404
    assert client.get(f"{API}/annotations/{ann}/files/..%2F..%2Fetc").status_code == 404


def test_tsv_neutralises_formulas_from_databases():
    features = [{"id": 1, "locus_tag": "X_1", "type": "cds", "contig": "c", "start": 1, "end": 9, "strand": "+",
                 "length": 9, "gene": None, "product": "=HYPERLINK(\"http://evil\")", "ec": [], "cog": [],
                 "cog_categories": [], "go": [], "db_xrefs": ["@SUM(1)"], "pseudo": False, "partial": None,
                 "hypothetical": False, "inference": ["a\tb"]}]
    text = svc.tsv(SimpleNamespace(sequences=[{"id": "c", "original_id": "chr"}]), features)
    row = text.splitlines()[1].split("\t")
    assert row[10] == "'=HYPERLINK(\"http://evil\")" and row[15] == "'@SUM(1)" and row[4] == "chr"
    assert row[19] == "a b" and len(row) == len(svc.TSV_COLUMNS)


# --- Bakta -----------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not available("bakta"), reason="Bakta is not installed")
def test_bakta_preview_without_database(client, setup):
    _, assembly = setup
    plan = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta/preview", json={}).json()
    assert plan["problems"][0]["code"] == "no_database" and plan["databases"] == []
    assert plan["assembly"]["contigs"] == 2 and plan["assembly"]["descriptions"] == 0
    assert "contig names" in plan["assembly"]["synthetic_evidence"]
    assert plan["suggestions"] == {"locus_tag": "ANN1", "complete": False, "translation_table": 11}
    assert [d["name"] for d in plan["dependencies"]][:2] == ["tRNAscan-SE", "Aragorn"]
    r = client.post(f"{API}/assemblies/{assembly['id']}/annotate/bakta", json=bakta_request(plan))
    assert r.status_code == 409 and "No Bakta database" in r.json()["detail"]


@pytest.mark.skipif(not available("bakta"), reason="Bakta is not installed")
def test_bakta_request_checks(client, setup, bakta_db):
    _, assembly = setup
    url = f"{API}/assemblies/{assembly['id']}/annotate/bakta"
    plan = client.post(f"{url}/preview", json={}).json()
    assert plan["database_id"] == bakta_db and not plan["problems"]
    assert set(plan["steps"]) == {"trna", "tmrna", "rrna", "ncrna", "ncrna_region", "crispr", "cds", "pseudo", "sorf",
                                  "gap", "ori", "plot"}
    assert plan["skip_options"] == [f"--skip-{s.replace('_', '-')}" for s, v in plan["steps"].items()
                                    if not v["run"] and v["reason"] in ("dependency", "user")]
    assert client.post(url, json={**bakta_request(plan), "confirmed": False}).status_code == 400
    assert client.post(url, json=bakta_request(plan, complete=True)).status_code == 400
    assert client.post(url, json=bakta_request(plan, locus_tag="bad tag")).status_code == 422
    assert client.post(url, json=bakta_request(plan, genus="Esch/../x")).status_code == 422
    assert client.post(url, json=bakta_request(plan, species="coli")).status_code == 422
    r = client.post(url, json={**bakta_request(plan), "skip_options": ["--skip-trna"]})
    assert r.status_code == 409 and "changed since the preview" in r.json()["detail"]
    assert client.post(f"{API}/assemblies/nope/annotate/bakta/preview", json={}).status_code == 404


@pytest.mark.skipif(not available("bakta"), reason="Bakta is not installed")
def test_bakta_end_to_end(client, setup, bakta_db, storage_root):
    sample, assembly = setup
    url = f"{API}/assemblies/{assembly['id']}/annotate/bakta"
    plan = client.post(f"{url}/preview", json={}).json()
    r = client.post(url, json=bakta_request(plan, genus="Escherichia", strain="SYNTH-1"))
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"][-3000:]
    assert job["database_key"] == "bakta-light" and job["database_checksum"] == BAKTA_DB_CHECKSUM
    argv = job["commands"][0]
    assert argv[argv.index("--locus-tag") + 1] == "SYNT" and argv[argv.index("--genus") + 1] == "Escherichia"
    assert [a for a in argv if a.startswith("--skip-")] == plan["skip_options"]
    (ann,) = client.get(f"{API}/assemblies/{assembly['id']}/annotations").json()
    assert ann["tool"] == "Bakta" and ann["database_version"] == "6.0"
    assert [s["original_id"] for s in ann["sequences"]] == ["SYNTHETIC_annotation_chromosome",
                                                            "SYNTHETIC_annotation_plasmid"]
    staged = storage_root / ann["files"]["input"]["path"]
    assert [ln for ln in staged.read_text().splitlines() if ln.startswith(">")] == [
        ">SYNTHETIC_annotation_chromosome", ">SYNTHETIC_annotation_plasmid"]
    for step, s in ann["steps"].items():
        assert s["status"] == ("skipped" if not plan["steps"][step]["run"] else s["status"])
    if not plan["steps"]["cds"]["run"]:
        assert ann["summary"]["cds"] is None and ann["summary"]["coding_density"]["value"] is None
    assert ann["summary"]["synthetic_evidence"]
    if plan["steps"]["rrna"]["run"]:
        rrs = client.get(f"{API}/annotations/{ann['id']}/features", params={"q": "rrs"}).json()["items"]
        assert [f["product"] for f in rrs] == ["16S ribosomal RNA"]
        detail = client.get(f"{API}/annotations/{ann['id']}/features/{rrs[0]['id']}").json()
        assert len(detail["nucleotide"]["sequence"]) == rrs[0]["length"]
        assert "https://rfam.org/family/RF00177" in [link["url"] for link in detail["links"]]
    gap = client.get(f"{API}/annotations/{ann['id']}/features", params={"type": "gap"}).json()
    assert gap["total"] == 1 and gap["items"][0]["length"] == 100
    assert client.get(f"{API}/annotations/{ann['id']}/files/json").json()["version"]["bakta"] == "1.12.2"
    if ann["steps"]["plot"]["status"] == "searched":
        png = client.get(f"{API}/annotations/{ann['id']}/files/plot_png")
        assert png.headers["content-type"] == "image/png" and png.headers["content-disposition"].startswith("inline")
    report = client.get(f"{API}/samples/{sample['id']}/report.json").json()
    assert report["annotations"][0]["tool"] == "Bakta"


@pytest.mark.skipif(not available("bakta"), reason="Bakta is not installed")
def test_bakta_refuses_to_run_when_its_programs_changed(client, setup, bakta_db, held_queue, monkeypatch):
    _, assembly = setup
    url = f"{API}/assemblies/{assembly['id']}/annotate/bakta"
    plan = client.post(f"{url}/preview", json={}).json()
    job_id = client.post(url, json=bakta_request(plan)).json()["id"]
    assert client.get(f"{API}/jobs/{job_id}").json()["status"] == "pending"
    real = annotation_tasks.bakta_tool.check_dependencies

    def without_trnascan(exe, db_path):
        return [{**d, "status": "missing"} if d["name"] == "tRNAscan-SE" else d for d in real(exe, db_path)]

    monkeypatch.setattr(annotation_tasks.bakta_tool, "check_dependencies", without_trnascan)
    assert annotation_tasks.run_bakta_job(job_id) == "failed"
    job = client.get(f"{API}/jobs/{job_id}").json()
    assert "changed since the run was confirmed" in job["error_message"]
    assert client.get(f"{API}/assemblies/{assembly['id']}/annotations").json() == []


# --- Prokka ----------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not prokka_ready(), reason="Prokka or its databases are not installed")
def test_prokka_end_to_end(client, setup, storage_root):
    sample, assembly = setup
    url = f"{API}/assemblies/{assembly['id']}/annotate/prokka"
    plan = client.post(f"{url}/preview", json={}).json()
    assert not plan["problems"] and plan["database"]["ready"] and plan["database"]["checksum"].startswith("sha256:")
    assert plan["steps"]["pseudo"]["reason"] == "not_supported" and plan["steps"]["ncrna"]["reason"] == "option_off"
    r = client.post(url, json={"settings": {"locus_tag": "SYNT"}, "confirmed": True, "threads": 2})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"][-3000:]
    assert job["database_key"] == "prokka-debian" and job["database_checksum"] == plan["database"]["checksum"]
    assert job["commands"][0][-1] == "--setupdb" and "--locustag" in job["commands"][1]
    results = storage_root / "results" / sample["project_id"] / sample["id"] / job["id"]
    assert not (results / "prokka-db").exists()
    (ann,) = client.get(f"{API}/samples/{sample['id']}/annotations").json()
    s = ann["summary"]
    assert (s["cds"], s["hypothetical"], s["characterised"], s["with_ec"]) == (18, 15, 3, 3)
    assert 0 < s["coding_density"]["value"] < 1 and s["tool_reported"]["prodigal_mode"] == "meta"
    assert ann["steps"]["crispr"]["status"] == "skipped" and ann["steps"]["cds"]["status"] == "searched"
    named = client.get(f"{API}/annotations/{ann['id']}/features", params={"hypothetical": "false", "type": "cds"}).json()
    assert {f["gene"] for f in named["items"]} == {"alkA", "tag", "quiB"}


@pytest.mark.skipif(not prokka_ready(), reason="Prokka or its databases are not installed")
def test_prokka_long_contig_names_need_renaming(client, tmp_path):
    long_names = tmp_path / "long.fasta"
    text = GENOME.read_text().replace(">SYNTHETIC_annotation_chromosome", ">SYNTHETIC_annotation_chromosome_with_a_long_name")
    long_names.write_text(text)
    sample = new_sample(client, "ANN-2")
    assembly = assemble(client, sample, long_names)
    url = f"{API}/assemblies/{assembly['id']}/annotate/prokka"
    plan = client.post(f"{url}/preview", json={}).json()
    assert [p["code"] for p in plan["problems"]] == ["contig_names"] and plan["suggestions"]["rename_contigs"]
    assert client.post(url, json={"settings": {"locus_tag": "SYNT"}, "confirmed": True}).status_code == 409
    r = client.post(url, json={"settings": {"locus_tag": "SYNT", "rename_contigs": True}, "confirmed": True})
    assert client.get(f"{API}/jobs/{r.json()['id']}").json()["status"] == "completed"
    (ann,) = client.get(f"{API}/samples/{sample['id']}/annotations").json()
    assert [(s["id"], s["original_id"]) for s in ann["sequences"]] == [
        ("contig_1", "SYNTHETIC_annotation_chromosome_with_a_long_name"), ("contig_2", "SYNTHETIC_annotation_plasmid")]
    first = client.get(f"{API}/annotations/{ann['id']}/features",
                       params={"contig": "SYNTHETIC_annotation_chromosome_with_a_long_name", "limit": 1}).json()
    assert first["items"][0]["contig"] == "contig_1"


# --- Migration -------------------------------------------------------------------------------------------------

def test_annotations_migration_up_and_down(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.core.config import get_settings
    from app.db.session import engine

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch_annotations")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_annotations"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch_annotations"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    try:
        command.upgrade(cfg, "head")
        with db.begin() as c:
            fks = dict(c.execute(text("SELECT conname, confdeltype FROM pg_constraint WHERE conrelid = "
                                      "'annotations'::regclass AND contype = 'f'")).all())
            assert fks == {"fk_annotations_sample_id": "c", "fk_annotations_assembly_id": "c",
                           "fk_annotations_job_id": "c"}
            c.execute(text("INSERT INTO projects (id, name, is_demo, created_at, updated_at) VALUES ('p', 'P', false, "
                           "now(), now())"))
            c.execute(text("INSERT INTO samples (id, project_id, sample_code, sequencing_technology, created_at, "
                           "updated_at) VALUES ('s', 'p', 'S', 'unknown', now(), now())"))
            c.execute(text("INSERT INTO analysis_jobs (id, project_id, sample_id, job_type, tool_name, tool_version, "
                           "status, created_at, updated_at) VALUES ('j', 'p', 's', 'x', 'X', '1', 'completed', now(), "
                           "now())"))
            c.execute(text("INSERT INTO assemblies (id, sample_id, job_id, assembler, assembler_version, mode, "
                           "read_type, input_file_ids, contigs_path, stats, contigs, warnings, created_at, kind) VALUES "
                           "('a', 's', 'j', 'Flye', '2.9.3', 'long', 'nano-hq', '[]', 'x', '{}', '[]', '[]', now(), "
                           "'assembly')"))
            c.execute(text("INSERT INTO annotations (id, sample_id, assembly_id, job_id, tool, tool_version, "
                           "parameters, steps, summary, sequences, files, features_path, created_at) VALUES ('n', 's', "
                           "'a', 'j', 'Bakta', '1.12.2', '{}', '{}', '{}', '[]', '{}', 'x', now())"))
        with pytest.raises(RuntimeError, match="1 annotation record"):
            command.downgrade(cfg, "e7a3c5b9d214")
        with db.begin() as c:
            c.execute(text("DELETE FROM assemblies WHERE id = 'a'"))
            assert c.scalar(text("SELECT count(*) FROM annotations")) == 0
        command.downgrade(cfg, "e7a3c5b9d214")
        with db.begin() as c:
            assert c.scalar(text("SELECT to_regclass('annotations')")) is None
        command.upgrade(cfg, "head")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_annotations"))
