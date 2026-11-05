"""Genome FASTA files registered as imported assemblies: a finished genome (e.g. an NCBI RefSeq genome), which is never
polished, and a draft the user declares was assembled outside ARVA from the sample's reads, which can be; and the Flye
guard against a filtered file selected together with the file it was filtered from."""
import gzip
from pathlib import Path

import pytest
from test_flye_api import ONT, fake_flye, new_sample, start, upload  # noqa: F401  (fake_flye is a fixture)

from app.db.session import SessionLocal
from app.models import FileFormat, FileOrigin, RawFile

API = "/api/v1"
GENOME = ">chr\n" + "ACGTTGCA" * 5_000 + "\n>plasmid\n" + "GGCATTAC" * 500 + "\n"


def test_fasta_is_registered_as_an_imported_genome(client, tmp_path):
    sample = new_sample(client, technology="unknown")
    fasta = tmp_path / "GCF_TEST.fna.gz"
    with gzip.open(fasta, "wt") as fh:
        fh.write(GENOME)
    f = upload(client, sample["id"], fasta)
    r = client.post(f"{API}/samples/{sample['id']}/assembly/import",
                    json={"raw_file_id": f["id"], "source": "NCBI RefSeq GCF_TEST.1"})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"]
    assert job["parameters"]["source"] == "NCBI RefSeq GCF_TEST.1"
    assert job["parameters"]["fasta_sha256"] == f["checksum_sha256"]
    assert "ARVA did not assemble it" in job["log_text"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    assert (a["assembler"], a["assembler_version"], a["mode"], a["read_type"]) == (
        "Imported genome", "NCBI RefSeq GCF_TEST.1", "imported", "none")
    assert a["stats"]["contig_count"] == 2 and a["stats"]["total_length"] == 44_000
    (check,) = [c for c in a["stats"]["warning_checks"] if c["code"] == "many_contigs"]
    assert not check["evaluated"] and "imported genome" in check["skipped_reason"]

    refused = client.post(f"{API}/assemblies/{a['id']}/polishing/preview", json={"inputs": {}})
    assert refused.status_code == 400 and "imported genome" in refused.json()["detail"]


def test_import_refuses_reads_and_unsafe_sources(client, tmp_path):
    sample = new_sample(client, technology="unknown")
    reads = upload(client, sample["id"], ONT)
    r = client.post(f"{API}/samples/{sample['id']}/assembly/import", json={"raw_file_id": reads["id"], "source": "x1"})
    assert r.status_code == 400 and "not a FASTA file" in r.json()["detail"]
    fasta = tmp_path / "g.fasta"
    fasta.write_text(GENOME)
    f = upload(client, sample["id"], fasta)
    for bad in ("", "<b>x</b>", "a" * 101, "-flag"):
        assert client.post(f"{API}/samples/{sample['id']}/assembly/import",
                           json={"raw_file_id": f["id"], "source": bad}).status_code == 422, bad
    assert client.get(f"{API}/samples/{sample['id']}/assemblies").json() == []


def test_flye_refuses_a_filtered_file_with_its_original(client, fake_flye):  # noqa: F811
    fake_flye()
    sample = new_sample(client)
    original = upload(client, sample["id"], ONT)
    with SessionLocal() as db:
        derived = RawFile(sample_id=sample["id"], original_filename="reads.filtlong.fastq.gz", stored_path="raw/x",
                          file_format=FileFormat.fastq_gz, size_bytes=1, checksum_sha256="ab" * 32, is_valid=True,
                          origin=FileOrigin.derived, parent_file_id=original["id"])
        db.add(derived)
        db.commit()
        derived_id = derived.id
    r = start(client, sample, [original, {"id": derived_id}])
    assert r.status_code == 400 and "duplicated read IDs" in r.json()["detail"]
    assert "reads.filtlong.fastq.gz was filtered from" in r.json()["detail"]


def register(client, sample, tmp_path, **body):
    fasta = tmp_path / "draft.fasta"
    fasta.write_text(GENOME)
    f = upload(client, sample["id"], fasta)
    r = client.post(f"{API}/samples/{sample['id']}/assembly/import",
                    json={"raw_file_id": f["id"], "source": "Own pipeline v1", **body})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job["log_text"]
    (a,) = client.get(f"{API}/samples/{sample['id']}/assemblies").json()
    return job, a


def test_a_draft_declared_as_assembled_from_the_samples_reads_can_be_polished(client, tmp_path):
    sample = new_sample(client)
    reads = upload(client, sample["id"], ONT)
    job, a = register(client, sample, tmp_path, draft={"from_this_sample_reads": True, "assembler": "Flye",
                                                       "assembler_version": "2.9.6"})
    assert job["parameters"]["declared_draft"] == {"from_this_sample_reads": True, "assembler": "Flye",
                                                   "assembler_version": "2.9.6"}
    assert "as declared by the user" in job["log_text"] and "outside ARVA" in job["log_text"]
    assert (a["mode"], a["assembler"], a["declared_assembler"], a["declared_assembler_version"]) == (
        "imported", "Imported genome", "Flye", "2.9.6")

    r = client.post(f"{API}/assemblies/{a['id']}/polishing/preview", json={"inputs": {"long_file_id": reads["id"]}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["strategy"] == "racon" and plan["strategies_for_reads"] == ["racon", "medaka"]
    assert (plan["draft"]["declared_assembler"], plan["draft"]["declared_assembler_version"]) == ("Flye", "2.9.6")
    # Medaka's models expect an unpolished Flye draft made by ARVA; a declared one is not taken as such.
    assert plan["medaka"]["draft_is_flye"] is False

    report = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
    (entry,) = report["assemblies"]
    assert entry["declared_assembler"] == "Flye"
    assert entry["provenance"].startswith("Draft assembled outside ARVA with Flye 2.9.6 from this sample's reads, as "
                                          "declared by the user")
    html = client.get(f"{API}/samples/{sample['id']}/report").text
    assert "Draft assembled outside ARVA (Flye 2.9.6)" in html and "<h4>Genome FASTA</h4>" in html


def test_a_finished_genome_is_still_refused_for_polishing(client, tmp_path):
    sample = new_sample(client)
    reads = upload(client, sample["id"], ONT)
    _, a = register(client, sample, tmp_path)
    assert a["declared_assembler"] is None
    r = client.post(f"{API}/assemblies/{a['id']}/polishing/preview", json={"inputs": {"long_file_id": reads["id"]}})
    assert r.status_code == 400
    assert "This is an imported genome, not an assembly of this sample's reads" in r.json()["detail"]
    report = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
    assert report["assemblies"][0]["provenance"].startswith("Genome FASTA registered by the user")


def test_a_draft_declaration_must_be_explicit_and_safe(client, tmp_path):
    sample = new_sample(client)
    fasta = tmp_path / "g.fasta"
    fasta.write_text(GENOME)
    f = upload(client, sample["id"], fasta)
    for draft in ({"from_this_sample_reads": False, "assembler": "Flye", "assembler_version": "2.9.6"},
                  {"assembler": "Flye", "assembler_version": "2.9.6"},
                  {"from_this_sample_reads": True, "assembler": "", "assembler_version": "2.9.6"},
                  {"from_this_sample_reads": True, "assembler": "Flye; rm", "assembler_version": "2.9.6"},
                  {"from_this_sample_reads": True, "assembler": "Flye", "assembler_version": "x" * 101}):
        r = client.post(f"{API}/samples/{sample['id']}/assembly/import",
                        json={"raw_file_id": f["id"], "source": "Own", "draft": draft})
        assert r.status_code == 422, draft
    assert client.get(f"{API}/samples/{sample['id']}/assemblies").json() == []


def test_registered_draft_migration_up_and_down_on_a_scratch_database(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.core.config import get_settings
    from app.db.session import engine

    name = "arva_migration_scratch_registered_draft"
    url = make_url(get_settings().database_url)
    scratch = url.set(database=name)
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        conn.execute(text(f"CREATE DATABASE {name}"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    before = "e2c7a9f4b6d1"
    try:
        command.upgrade(cfg, before)
        with db.begin() as c:
            c.execute(text("INSERT INTO projects (id, name, is_demo, created_at, updated_at) VALUES ('p', 'P', false, "
                           "now(), now())"))
            c.execute(text("INSERT INTO samples (id, project_id, sample_code, sequencing_technology, created_at, "
                           "updated_at) VALUES ('s', 'p', 'S', 'unknown', now(), now())"))
            c.execute(text("INSERT INTO analysis_jobs (id, project_id, sample_id, job_type, tool_name, tool_version, "
                           "status, created_at, updated_at) VALUES ('j', 'p', 's', 'x', 'X', '1', 'completed', now(), "
                           "now())"))
            c.execute(text("INSERT INTO assemblies (id, sample_id, job_id, kind, assembler, assembler_version, mode, "
                           "read_type, input_file_ids, contigs_path, stats, contigs, warnings, created_at) VALUES "
                           "('a', 's', 'j', 'assembly', 'Imported genome', 'Own', 'imported', 'none', '[]', 'x', '{}', "
                           "'[]', '[]', now())"))
        command.upgrade(cfg, "head")
        with db.begin() as c:
            assert c.execute(text("SELECT declared_assembler, declared_assembler_version FROM assemblies")).one() == (
                None, None)
            c.execute(text("UPDATE assemblies SET declared_assembler = 'Flye', declared_assembler_version = '2.9.6'"))
        with pytest.raises(RuntimeError, match="1 registered draft assembly record"):
            command.downgrade(cfg, before)
        with db.begin() as c:
            c.execute(text("UPDATE assemblies SET declared_assembler = NULL, declared_assembler_version = NULL"))
        command.downgrade(cfg, before)
        with db.begin() as c:
            cols = {r[0] for r in c.execute(text("SELECT column_name FROM information_schema.columns "
                                                 "WHERE table_name = 'assemblies'"))}
            assert not {"declared_assembler", "declared_assembler_version"} & cols
        command.upgrade(cfg, "head")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))


def test_every_samples_genome_fasta_is_registered_at_once(client, tmp_path):
    p = client.post(f"{API}/projects", json={"name": "Batch genomes"}).json()
    samples = {code: client.post(f"{API}/projects/{p['id']}/samples",
                                 json={"sample_code": code, "sequencing_technology": "nanopore"}).json()
               for code in ("S1", "S2", "S3", "S4")}
    for code in ("S1", "S2"):
        fasta = tmp_path / f"{code}.fasta"
        fasta.write_text(GENOME)
        upload(client, samples[code]["id"], fasta)
    for name in ("a.fasta", "b.fasta"):  # S3 has two FASTA files: ARVA cannot choose for the user
        (tmp_path / name).write_text(GENOME.replace("ACGT", "TTGC") if name == "b.fasta" else GENOME)
        upload(client, samples["S3"]["id"], tmp_path / name)
    upload(client, samples["S4"]["id"], ONT)  # reads only

    plan = {r["sample_code"]: r for r in client.get(f"{API}/projects/{p['id']}/assembly/import-all").json()}
    assert {c: r["status"] for c, r in plan.items()} == {
        "S1": "ready", "S2": "ready", "S3": "several_fasta", "S4": "no_fasta"}
    assert plan["S1"]["file_name"] == "S1.fasta"

    r = client.post(f"{API}/projects/{p['id']}/assembly/import-all",
                    json={"source": "Own pipeline: Flye 2.9.6 + Medaka 2.1.1"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert sorted(s["sample_code"] for s in body["started"]) == ["S1", "S2"]
    assert {s["sample_code"]: s["status"] for s in body["skipped"]} == {"S3": "several_fasta", "S4": "no_fasta"}
    for s in body["started"]:
        job = client.get(f"{API}/jobs/{s['job_id']}").json()
        assert job["status"] == "completed", job["log_text"]
        (a,) = client.get(f"{API}/samples/{s['sample_id']}/assemblies").json()
        assert (a["mode"], a["assembler_version"]) == ("imported", "Own pipeline: Flye 2.9.6 + Medaka 2.1.1")

    # A second press registers nothing twice.
    again = {r["sample_code"]: r["status"] for r in client.get(f"{API}/projects/{p['id']}/assembly/import-all").json()}
    assert again["S1"] == again["S2"] == "registered"
    r = client.post(f"{API}/projects/{p['id']}/assembly/import-all", json={"source": "x1", "sample_ids": [samples["S1"]["id"]]})
    assert r.json() == {"started": [], "skipped": [{"sample_id": samples["S1"]["id"], "sample_code": "S1",
                                                     "status": "registered"}]}
    assert client.post(f"{API}/projects/{p['id']}/assembly/import-all", json={"source": "<bad>"}).status_code == 422
