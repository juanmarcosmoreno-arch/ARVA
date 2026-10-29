"""Database kinds: the registry, recognition and versioning of each kind on CONSTRUCTED miniature folders
(tests/database_fixtures.py), registration that never writes into the folder, declared versions, quick and full
verification (with cancellation), databases on a disk that comes and goes, one default per kind, reference genome
collections (NCBI Datasets package, FastANI list with host paths, FASTA folder, a copy extracted from the package
zip), downloads into a chosen folder from a local HTTP server, and the version chosen for Bakta recorded on its job.

Host paths such as /Volumes/JM/BioInf/... are CONSTRUCTED strings standing for what scripts/start.sh passes on a Mac.
"""
import dataclasses
import hashlib
import io
import json
import os
import re
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import database_fixtures as fx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import ReferenceDatabase
from app.services import database_catalogue as catalogue
from app.services import database_detect as detection
from app.services import database_kinds as kinds
from app.services import databases as svc
from app.services import locations
from app.tasks import databases as tasks

API = "/api/v1"
SLOT = "2846640912"
HOST = "/Volumes/JM/BioInf/staph_references"


@pytest.fixture(autouse=True)
def native(monkeypatch):
    monkeypatch.setattr(locations, "in_container", lambda: False)


@pytest.fixture
def dbdir(tmp_path, monkeypatch):
    folder = tmp_path / "databases"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "db_dir", folder)
    return folder.resolve()


@pytest.fixture
def external(tmp_path, monkeypatch, dbdir):
    """An added database folder as scripts/start.sh mounts it (/databases-external/<n>), with its host path."""
    root = tmp_path / "databases-external" / SLOT
    root.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "external_db_roots", [root])
    monkeypatch.setenv(f"ARVA_HOST_EXTERNAL_DB_{SLOT}", HOST)
    return root.resolve()


def register(client, path, **body):
    return client.post(f"{API}/databases/register", json={"path": str(path), **body})


def detect(client, path):
    return client.get(f"{API}/databases/detect", params={"path": str(path)})


def record(client, record_id):
    return client.get(f"{API}/databases/{record_id}").json()


# --- The registry -----------------------------------------------------------------------------------------------

def test_every_kind_states_its_facts_and_their_sources(client):
    keys = [k.key for k in kinds.KINDS]
    assert len(keys) == len(set(keys)) and len(keys) == 16
    for k in kinds.KINDS:
        assert k.source_url.startswith(("https://", "http://")) and k.licence and k.citation and k.recognise
        assert k.version_from and k.typical_size and k.download in ("catalogue", "register") and k.sources
        assert k.tools and all(t.versions for t in k.tools)
        offered = catalogue.for_kind(k.key)
        assert bool(offered) == (k.download == "catalogue"), k.key
    assert kinds.BY_KEY["spa_types"].user_provided_only and kinds.BY_KEY["spa_types"].download == "register"
    assert [t.tool for t in kinds.BY_KEY["bakta"].tools if t.integrated] == ["Bakta"]
    for e in catalogue.CATALOGUE:
        assert e.kind in kinds.BY_KEY and e.download_url.startswith("https://") and e.checksum_algorithm == "md5"
        assert re.fullmatch(r"[0-9a-f]{32}", e.checksum) and e.archive_bytes > 0 and e.extracted_bytes_estimate > 0
        assert e.checksum_sources and e.licence and e.terms and e.citation and e.compatibility
        assert re.fullmatch(r"[A-Za-z0-9._/-]+", e.install_dir)
    body = client.get(f"{API}/databases/kinds").json()
    assert [k["key"] for k in body] == keys
    listed = {e["key"]: e for e in client.get(f"{API}/databases/catalogue").json()}
    assert listed["gtdbtk-r232"]["compatibility_now"]["status"] == "unknown"
    assert listed["bakta-light"]["install_dir"] == "bakta-light/6.0"
    assert listed["kraken2-standard"]["install_dir"] == "kraken2-standard/standard-2026-06-26"


def test_bakta_compatibility_follows_the_installed_schema():
    assert kinds.compatibility("bakta", {"major": 6}, installed="1.12.2").status == "compatible"
    old = kinds.compatibility("bakta", {"major": 5}, installed="1.12.2")
    assert (old.status, old.code, old.params["schema"]) == ("incompatible", "schema_mismatch", 6)
    assert kinds.compatibility("bakta", {"major": 6}, installed="9.9.9").code == "tool_version_unchecked"
    assert kinds.compatibility("kraken2").code == "tool_not_integrated"


# --- Recognition and versions, kind by kind (CONSTRUCTED folders) -----------------------------------------------

KINDS_ON_DISK = [
    # builder, folder name, kind, version (from the files), version file, suggested version
    (fx.bakta, "db-light", "bakta", "6.0", "version.json", None),
    (fx.amrfinderplus, "2026-08-07.1", "amrfinderplus", "2026-08-07.1", "version.txt", None),
    (fx.gtdbtk, "release232", "gtdbtk", "r232", "metadata/metadata.txt", None),
    (fx.skani, "skani_gtdb_r232-v0.4", "skani", None, None, "GTDB r232"),
    (fx.kraken2, "k2", "kraken2", "standard 2026-06-26", "standard.md5", None),
    (fx.checkm2, "checkm2", "checkm2", "3", "CONTENTS.json", None),
    (fx.busco, "bacteria_odb12.2", "busco", "bacteria_odb12.2 (2026-05-22)", "dataset.cfg", None),
    (fx.plasmidfinder, "plasmidfinder_db", "plasmidfinder", "2.2.0", "VERSION", None),
    (fx.mobsuite, "mob_db", "mobsuite", None, None, None),
    (fx.vfdb, "vfdb", "vfdb", None, None, None),
    (fx.genomad, "genomad_db", "genomad", "1.9", "version.txt", None),
    (fx.interproscan, "interproscan-5.78-109.0", "interproscan", None, None, "5.78-109.0"),
    (fx.spa_types, "ridom", "spa_types", None, None, None),
    (fx.ncbi_package, "pkg", "reference_genomes", None, None, None),
]


@pytest.mark.parametrize(("build", "name", "kind", "version", "version_file", "suggested"), KINDS_ON_DISK,
                         ids=[k[2] for k in KINDS_ON_DISK])
def test_each_kind_is_recognised_with_its_version(tmp_path, build, name, kind, version, version_file, suggested):
    folder = build(tmp_path / name)
    (found,) = detection.detect(folder)
    assert found.kind == kind and found.ok, [p.text for p in found.problems]
    assert (found.version, found.version_file, found.suggested_version) == (version, version_file, suggested)
    assert found.needs_declared_version == (version is None)


@pytest.mark.parametrize(("build", "remove", "kind"), [
    (fx.bakta, "sorf.dmnd", "bakta"), (fx.amrfinderplus, "AMR.LIB", "amrfinderplus"),
    (fx.gtdbtk, "taxonomy/gtdb_taxonomy.tsv", "gtdbtk"), (fx.kraken2, "taxo.k2d", "kraken2"),
    (fx.busco, "scores_cutoff", "busco"), (fx.plasmidfinder, "Inc18.fsa", "plasmidfinder"),
    (fx.mobsuite, "orit.fas", "mobsuite"), (fx.genomad, "nodes.dmp", "genomad"),
])
def test_a_missing_required_file_is_named(tmp_path, build, remove, kind):
    folder = build(tmp_path / "db")
    (folder / remove).unlink()
    (found,) = detection.detect(folder)
    assert found.kind == kind and not found.ok
    assert any(p.code == "missing_files" and remove in p.text for p in found.problems)


def test_single_file_kinds_and_their_suggested_versions(tmp_path):
    sylph = tmp_path / "gtdb-r232-c200-dbv1.syldb"
    sylph.write_bytes(b"CONSTRUCTED")
    (d,) = detection.detect(sylph)
    assert (d.kind, d.path_type, d.suggested_version, d.suggested_from) == ("sylph", "file", "GTDB r232, -c 200",
                                                                            "file_name")
    mash = tmp_path / "RefSeqSketchesDefaults.msh"
    mash.write_bytes(b"CONSTRUCTED")
    assert detection.detect(mash)[0].suggested_version == "RefSeq release 70 (k=21, s=1000)"
    packed = tmp_path / "RefSeqSketches.msh.gz"
    packed.write_bytes(b"CONSTRUCTED")
    assert [p.code for p in detection.detect(packed)[0].problems] == ["compressed"]


def test_unusual_layouts(tmp_path):
    # AMRFinderPlus refuses a folder whose BLAST indexes were not built.
    (d,) = detection.detect(fx.amrfinderplus(tmp_path / "amr", indexed=False))
    assert [p.code for p in d.problems] == ["not_indexed"]
    # CheckM2's DIAMOND file without CONTENTS.json: the full checksum identifies the version.
    (c,) = detection.detect(fx.checkm2(tmp_path / "cm2", contents=False))
    assert c.version is None and c.version_by_checksum and not c.needs_declared_version
    # A Kraken 2 index without its .md5: the folder name suggests the version.
    (k,) = detection.detect(fx.kraken2(tmp_path / "k2_pluspf_20260101", with_md5=False))
    assert (k.version, k.suggested_version) == (None, "pluspf 2026-01-01")
    # A Bakta schema ARVA does not know the files of is recognised and flagged, not refused.
    (b,) = detection.detect(fx.bakta(tmp_path / "old", {"date": "2023-02-20", "major": 5, "minor": 0,
                                                         "type": "light"}))
    assert b.ok and b.version == "5.0" and [p.code for p in b.problems] == ["schema_unchecked"]
    # The folder bakta_db download wrote into holds the database in a subfolder.
    fx.bakta(tmp_path / "bakta" / "db-light")
    (n,) = detection.detect(tmp_path / "bakta")
    assert n.kind == "unknown" and n.facts["nested"] == ["db-light"]
    # Bakta's oric.fna does not make a Bakta folder a genome collection.
    assert [d.kind for d in detection.detect(tmp_path / "bakta" / "db-light")] == ["bakta"]


# --- Registration -----------------------------------------------------------------------------------------------

def test_registration_reads_the_folder_and_never_writes_into_it(client, dbdir):
    folder = fx.kraken2(dbdir / "k2_standard_20260626")
    before = fx.tree_state(folder)
    r = register(client, folder)
    assert r.status_code == 201, r.text
    db = r.json()
    assert (db["kind"], db["version"], db["version_source"], db["version_file"]) == (
        "kraken2", "standard 2026-06-26", "file", "standard.md5")
    assert db["status"] == "registered" and db["verification_level"] == "quick" and db["checksum"] is None
    assert db["is_default"] and db["licence"].startswith("Not stated")
    assert client.post(f"{API}/databases/{db['id']}/verify", json={"level": "quick"}).json()["status"] == "registered"
    full = client.post(f"{API}/databases/{db['id']}/verify", json={"level": "full"}).json()
    assert full["verification_level"] == "full" and full["checksum"].startswith("sha256:")
    assert full["published_md5_checked"] == 5 and full["files"] == 6
    assert "match the publisher's MD5" in record(client, db["id"])["log_text"]
    assert register(client, folder).json()["code"] == "already_registered"
    assert client.delete(f"{API}/databases/{db['id']}").status_code == 204
    assert fx.tree_state(folder) == before


def test_a_version_the_files_do_not_state_is_declared_and_labelled(client, dbdir):
    folder = fx.skani(dbdir / "skani_gtdb_r232-v0.4")
    preview = detect(client, folder).json()["candidates"][0]
    assert preview["needs_declared_version"] and preview["suggested_version"] == "GTDB r232"
    assert preview["facts"]["built_by_skani"] == "0.4.0" and preview["facts"]["format"].startswith("skani 0.4")
    refused = register(client, folder)
    assert refused.status_code == 400 and refused.json()["code"] == "version_needed"
    assert refused.json()["params"]["suggested"] == "GTDB r232"
    assert register(client, folder, declared_version="r232\n<script>").json()["code"] == "version_invalid"
    db = register(client, folder, declared_version="GTDB r232").json()
    assert (db["version"], db["version_source"]) == ("GTDB r232", "declared")
    assert "declared" in record(client, db["id"])["log_text"]


def test_refusals_carry_codes(client, dbdir, tmp_path):
    outside = fx.bakta(tmp_path / "elsewhere")
    assert register(client, outside).json()["code"] == "outside_roots"
    assert register(client, dbdir / "nope").json()["code"] == "not_found"
    (dbdir / "empty").mkdir()
    assert register(client, dbdir / "empty").json()["code"] == "not_recognised"
    broken = fx.bakta(dbdir / "broken", omit=("bakta.db",))
    r = register(client, broken)
    assert r.json()["code"] == "detection_failed" and "bakta.db" in r.json()["detail"]
    assert register(client, fx.busco(dbdir / "bus"), kind="kraken2").json()["code"] == "kind_mismatch"
    assert register(client, dbdir / "bus", kind="nope").status_code == 400
    assert client.get(f"{API}/databases").json() == []


def test_quick_verification_finds_changed_sizes_and_recovers(client, dbdir):
    folder = fx.genomad(dbdir / "genomad_db")
    db = register(client, folder).json()
    (folder / "names.dmp").write_text(fx.NOTE * 3)
    failed = client.post(f"{API}/databases/{db['id']}/verify", json={"level": "quick"}).json()
    assert failed["status"] == "failed" and failed["error_detail"]["code"] == "quick_failed"
    assert "names.dmp" in failed["error_message"]
    (folder / "names.dmp").write_text(fx.NOTE)
    again = client.post(f"{API}/databases/{db['id']}/verify", json={"level": "quick"}).json()
    assert again["status"] == "registered" and again["error_message"] is None
    (folder / "version.txt").write_text("2.0\n")
    assert "version file now says 2.0" in client.post(f"{API}/databases/{db['id']}/verify",
                                                      json={"level": "quick"}).json()["error_message"]


def test_a_publisher_checksum_that_differs_fails_the_full_verification(client, dbdir):
    folder = fx.kraken2(dbdir / "k2")
    db = register(client, folder).json()
    (folder / "opts.k2d").write_text(fx.NOTE.upper())
    failed = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert failed["status"] == "failed" and failed["error_detail"]["code"] == "published_mismatch"


def test_checkm2_version_is_identified_by_its_published_sha256(client, dbdir, monkeypatch):
    folder = fx.checkm2(dbdir / "checkm2", contents=False)
    sha = hashlib.sha256((folder / "CheckM2_database/uniref100.KO.1.dmnd").read_bytes()).hexdigest()
    monkeypatch.setitem(detection.CHECKM2_DMND_SHA256, sha, "3")
    db = register(client, folder).json()
    assert db["version"] is None and db["version_source"] is None
    done = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert (done["version"], done["version_source"]) == ("3", "checksum")


def test_the_full_checksum_job_can_be_cancelled_while_it_runs(client, dbdir, held_queue, monkeypatch):
    folder = fx.gtdbtk(dbdir / "release232")
    (folder / "split" / "big.bin").write_bytes(b"x" * 200_000)
    db = register(client, folder).json()
    queued = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert queued["status"] == "verifying" and queued["progress"]["phase"] == "queued"
    monkeypatch.setattr(tasks, "CHUNK", 1024)
    monkeypatch.setattr(tasks, "TICK_SECONDS", 0.0)
    real_tick = tasks.Task.tick
    calls = []

    def tick(self, force=False, **fields):
        calls.append(fields.get("bytes_done"))
        if len(calls) == 20:
            with engine.begin() as conn:
                conn.execute(text("UPDATE reference_databases SET cancel_requested_at = now()"))
        return real_tick(self, force, **fields)

    monkeypatch.setattr(tasks.Task, "tick", tick)
    assert tasks.run_database_verify(db["id"]) == "registered"
    after = record(client, db["id"])
    assert after["status"] == "registered" and after["checksum"] is None and after["verification_level"] == "quick"
    assert "Cancelled at the user's request" in after["log_text"] and 20 <= len(calls) < 200
    # Cancelling a queued verification stops it before any worker runs it.
    client.post(f"{API}/databases/{db['id']}/verify")
    assert client.post(f"{API}/databases/{db['id']}/cancel").json()["status"] == "registered"


def test_a_database_on_a_disk_that_comes_and_goes(client, external, tmp_path):
    folder = fx.busco(external / "busco_downloads" / "lineages" / "bacteria_odb12.2")
    db = register(client, f"{HOST}/busco_downloads/lineages/bacteria_odb12.2").json()
    assert db["path"] == str(folder) and db["host_path"] == f"{HOST}/busco_downloads/lineages/bacteria_odb12.2"
    external.rename(tmp_path / "unplugged")
    gone = client.get(f"{API}/databases").json()[0]
    assert gone["available"] is False and gone["unavailable_reason"] == "disk_not_connected"
    assert gone["status"] == "registered"
    r = client.post(f"{API}/databases/{db['id']}/verify", json={"level": "quick"})
    assert r.status_code == 409 and r.json()["code"] == "database_unavailable"
    with SessionLocal() as session:
        assert svc.default_for(session, "busco") is None
    (tmp_path / "unplugged").rename(external)
    back = client.get(f"{API}/databases").json()[0]
    assert back["available"] is True and back["unavailable_reason"] is None and back["status"] == "registered"
    assert client.post(f"{API}/databases/{db['id']}/verify", json={"level": "quick"}).json()["status"] == "registered"
    with SessionLocal() as session:
        assert svc.default_for(session, "busco").id == db["id"]


def test_one_default_per_kind(client, dbdir):
    first = register(client, fx.bakta(dbdir / "a")).json()
    second = register(client, fx.bakta(dbdir / "b", {"date": "2025-06-01", "major": 6, "minor": 1,
                                                     "type": "light"})).json()
    assert first["is_default"] and not second["is_default"]
    made = client.post(f"{API}/databases/{second['id']}/default").json()
    assert made["is_default"] and not record(client, first["id"])["is_default"]
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE reference_databases SET is_default = true"))
    assert client.delete(f"{API}/databases/{second['id']}").status_code == 204
    assert record(client, first["id"])["is_default"]
    old = register(client, fx.bakta(dbdir / "old", {"date": "2023-02-20", "major": 5, "minor": 0,
                                                    "type": "light"})).json()
    assert old["version"] == "5.0" and not old["is_default"]


def test_an_incompatible_bakta_database_cannot_be_the_default(client, dbdir, monkeypatch):
    monkeypatch.setattr(kinds, "bakta_version", lambda: "1.12.2")
    old = register(client, fx.bakta(dbdir / "old", {"date": "2023-02-20", "major": 5, "minor": 0,
                                                    "type": "light"})).json()
    assert old["compatibility"]["status"] == "incompatible" and not old["is_default"]
    r = client.post(f"{API}/databases/{old['id']}/default")
    assert r.status_code == 409 and r.json()["code"] == "incompatible"


# --- Reference genome collections -------------------------------------------------------------------------------

def test_an_ncbi_datasets_package_shows_its_taxonomic_coverage(client, external):
    pkg = fx.ncbi_package(external / "staphylococcus_refseq_type_genomes")
    preview = detect(client, f"{HOST}/staphylococcus_refseq_type_genomes").json()["candidates"][0]
    c = preview["facts"]["collection"]
    assert (preview["kind"], preview["variant"], c["genomes"], c["species"]) == ("reference_genomes", "ncbi_package",
                                                                                 3, 2)
    assert c["by_species"][0] == {"species": "Staphylococcus constructus", "genomes": 2}
    assert c["reference_genomes"] == 1 and c["type_material"][0]["genomes"] == 2
    assert register(client, pkg).json()["code"] == "date_needed"
    db = register(client, pkg, collection_date="2026-05-27").json()
    assert re.fullmatch(r"NCBI Datasets 2026-05-27 #[0-9a-f]{12}", db["version"]) and db["version_source"] == "declared"
    assert db["collection"]["fingerprint"].startswith(db["version"][-12:])
    full = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert full["status"] == "registered" and full["published_md5_checked"] == 5
    with SessionLocal() as session:
        inv = session.get(ReferenceDatabase, db["id"]).inventory
    assert {g["accession"] for g in inv} == {g[0] for g in fx.GENOMES} and inv[0]["path"].startswith(str(external))


def test_a_fastani_list_written_with_mac_paths_is_mapped_and_checked(client, external, tmp_path):
    pkg = fx.ncbi_package(external / "staphylococcus_refseq_type_genomes")
    fnas = sorted(pkg.rglob("*_genomic.fna"))
    host = [f"{HOST}/{p.relative_to(external).as_posix()}" for p in fnas]
    lst = external / "staph_refseq_type_references.txt"
    lst.write_text("\n".join([*host, f"{HOST}/missing/GCF_000000009.1_genomic.fna",
                              "/Volumes/Other/GCF_000000010.1_genomic.fna"]) + "\n")
    d = detect(client, f"{HOST}/staph_refseq_type_references.txt").json()["candidates"][0]
    assert (d["kind"], d["variant"], d["ok"]) == ("reference_genomes", "fastani_list", False)
    codes = {p["code"]: p for p in d["problems"]}
    assert "GCF_000000009.1" in codes["genomes_missing"]["text"]
    assert codes["genomes_outside"]["params"]["names"] == "/Volumes/Other/GCF_000000010.1_genomic.fna"
    assert register(client, lst, collection_date="2026-05-27").json()["code"] == "detection_failed"
    lst.write_text("\n".join(host) + "\n")
    db = register(client, f"{HOST}/staph_refseq_type_references.txt", collection_date="2026-05-27").json()
    assert db["version"].startswith("NCBI Datasets 2026-05-27 #") and db["collection"]["species"] == 2
    with SessionLocal() as session:
        inv = session.get(ReferenceDatabase, db["id"]).inventory
    assert all(g["path"].startswith(str(external)) and g["metadata"] == "package" for g in inv)
    full = client.post(f"{API}/databases/{db['id']}/verify").json()
    assert full["status"] == "registered" and full["published_md5_checked"] == 3
    fnas[0].unlink()
    quick = client.post(f"{API}/databases/{db['id']}/verify", json={"level": "quick"}).json()
    assert quick["status"] == "failed" and "GCF_000000001.1" in quick["error_message"]


def test_a_folder_of_fasta_files_is_a_collection(client, dbdir):
    folder = dbdir / "my_refs"
    folder.mkdir()
    (folder / "GCF_000000004.1_genomic.fna").write_text(">NZ_X.1 Escherichia constructa strain K chromosome\nACGT\n")
    (folder / "other.fasta").write_text(">c1 Escherichia constructa plasmid\nACGT\n")
    import gzip
    with gzip.open(folder / "third.fa.gz", "wt") as fh:
        fh.write(">c2 Salmonella inventa chromosome\nACGT\n")
    d = detect(client, folder).json()["candidates"][0]
    assert d["variant"] == "fasta_folder" and d["facts"]["collection"]["species"] == 2
    db = register(client, folder, collection_date="2026-10-01").json()
    assert db["version"].startswith("FASTA folder 2026-10-01 #")


def test_the_package_zip_is_never_registered_but_can_be_extracted_into_a_copy(client, external, dbdir, tmp_path):
    pkg = fx.ncbi_package(tmp_path / "pkg")
    folder = external / "staphylococcus_refseq_type_genomes"
    folder.mkdir()
    zp = fx.package_zip(pkg, folder / "staphylococcus_refseq_type_genomes.zip")
    zip_sha = hashlib.sha256(zp.read_bytes()).hexdigest()
    host_zip = f"{HOST}/staphylococcus_refseq_type_genomes/staphylococcus_refseq_type_genomes.zip"
    d = detect(client, host_zip).json()["candidates"][0]
    assert d["path_type"] == "zip" and d["problems"][0]["code"] == "zip_package"
    assert d["suggested_from"] == "zip_entries" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["suggested_version"])
    assert register(client, host_zip, collection_date="2026-05-27").json()["code"] == "zip_needs_extraction"
    plan = client.get(f"{API}/databases/extract/plan", params={"path": host_zip}).json()
    assert plan["enough"] and plan["blocked_by"] is None and plan["folder"] == \
        "reference-genomes/staphylococcus_refseq_type_genomes"
    assert plan["target_path"].startswith(str(dbdir)) and plan["destinations"][0]["path"] == str(dbdir)
    body = {"path": host_zip, "confirm_bytes": plan["required_bytes"], "collection_date": "2026-05-27"}
    assert client.post(f"{API}/databases/extract", json={**body, "confirm_bytes": 1}).status_code == 400
    copy = client.post(f"{API}/databases/extract", json=body).json()
    assert copy["status"] == "installed" and copy["origin"] == "extract", copy["error_message"]
    assert copy["version"].startswith("NCBI Datasets 2026-05-27 #") and copy["published_md5_checked"] == 5
    assert Path(copy["path"], "ncbi_dataset/data/assembly_data_report.jsonl").is_file()
    assert hashlib.sha256(zp.read_bytes()).hexdigest() == zip_sha and sorted(os.listdir(folder)) == [zp.name]
    assert client.get(f"{API}/databases/extract/plan", params={"path": host_zip}).json()["blocked_by"]
    assert client.delete(f"{API}/databases/{copy['id']}").status_code == 204 and not Path(copy["path"]).exists()
    assert zp.is_file()


def test_an_unsafe_zip_is_not_extracted(client, external, tmp_path):
    pkg = fx.ncbi_package(tmp_path / "pkg")
    zp = fx.package_zip(pkg, external / "evil.zip", extra={"../escape.txt": "x"})
    plan = client.get(f"{API}/databases/extract/plan", params={"path": str(zp)}).json()
    assert "contains '..'" in plan["blocked_by"]
    r = client.post(f"{API}/databases/extract", json={"path": str(zp), "confirm_bytes": plan["required_bytes"],
                                                      "collection_date": "2026-05-27"})
    assert r.status_code == 409 and not (external.parent / "escape.txt").exists()


# --- Browsing ---------------------------------------------------------------------------------------------------

def test_browsing_shows_the_database_folders_only(client, external, dbdir, tmp_path):
    fx.busco(external / "lineages" / "bacteria_odb12.2")
    (tmp_path / "secret").mkdir()
    os.symlink(tmp_path / "secret", external / "escape")
    roots = client.get(f"{API}/databases/locations").json()
    assert [r["role"] for r in roots["browse"]] == ["databases", "external_databases"]
    assert roots["writable"][0]["path"] == str(dbdir) and roots["writable"][0]["free_bytes"] > 0
    listing = client.get(f"{API}/databases/browse", params={"root": str(external), "path": "lineages"}).json()
    assert [e["name"] for e in listing["entries"]] == ["bacteria_odb12.2"] and listing["parent"] == ""
    assert listing["host_path"] == f"{HOST}/lineages"
    top = client.get(f"{API}/databases/browse", params={"root": str(external)}).json()
    assert [e["name"] for e in top["entries"]] == ["lineages"] and top["parent"] is None
    assert client.get(f"{API}/databases/browse", params={"root": str(external), "path": "../.."}).status_code == 400
    assert client.get(f"{API}/databases/browse", params={"root": str(tmp_path)}).json()["code"] == "outside_roots"


# --- Downloads into a chosen folder (local HTTP server, CONSTRUCTED archives) -----------------------------------

def _tar(path: Path, files: dict[str, bytes], top: str | None) -> bytes:
    with tarfile.open(path, "w:gz") as tar:
        if top:
            info = tarfile.TarInfo(top)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(info)
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}" if top else name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path.read_bytes()


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Serve a CONSTRUCTED archive for a catalogue entry from a local HTTP server."""
    servers = []

    def make(key: str, data: bytes):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        fake = dataclasses.replace(catalogue.BY_KEY[key], download_url=f"http://127.0.0.1:{httpd.server_address[1]}/a",
                                   archive_bytes=len(data), checksum=hashlib.md5(data).hexdigest(),
                                   extracted_bytes_estimate=1 << 20)
        monkeypatch.setitem(catalogue.BY_KEY, key, fake)
        return fake

    yield make
    for s in servers:
        s.shutdown()
        s.server_close()


def test_a_download_goes_into_the_chosen_folder(client, dbdir, served, tmp_path):
    src = fx.busco(tmp_path / "src")
    files = {p.relative_to(src).as_posix(): p.read_bytes() for p in src.rglob("*") if p.is_file()}
    e = served("busco-bacteria-odb12.2", _tar(tmp_path / "b.tar.gz", files, "bacteria_odb12.2"))
    plan = client.get(f"{API}/databases/catalogue/{e.key}/plan",
                      params={"destination": str(dbdir), "folder": "busco/lineages/bacteria_odb12.2"}).json()
    assert plan["target_path"] == str(dbdir / "busco/lineages/bacteria_odb12.2") and plan["enough"]
    assert plan["destinations"][0]["path"] == str(dbdir) and plan["compatibility"]["status"] == "unknown"
    bad = client.get(f"{API}/databases/catalogue/{e.key}/plan", params={"folder": "../x"}).json()
    assert bad["code"] == "bad_folder"
    elsewhere = client.get(f"{API}/databases/catalogue/{e.key}/plan", params={"destination": str(tmp_path)}).json()
    assert elsewhere["code"] == "bad_destination"
    r = client.post(f"{API}/databases/downloads", json={"key": e.key, "confirm_bytes": e.archive_bytes,
                                                        "accept_licence": True, "destination": str(dbdir),
                                                        "folder": "busco/lineages/bacteria_odb12.2"})
    db = r.json()
    assert db["status"] == "installed", db["error_message"]
    assert (db["kind"], db["version"], db["version_source"], db["verification_level"]) == (
        "busco", "bacteria_odb12.2 (2026-05-22)", "file", "full")
    assert Path(db["path"], "dataset.cfg").is_file() and db["path"] == str(dbdir / "busco/lineages/bacteria_odb12.2")
    assert db["is_default"] and not list((dbdir / svc.DOWNLOADS).rglob("*.part"))


def test_an_archive_without_a_top_folder_is_unpacked_and_its_published_md5s_compared(client, dbdir, served,
                                                                                     tmp_path):
    src = fx.kraken2(tmp_path / "src")
    files = {p.name: p.read_bytes() for p in src.iterdir()}
    e = served("kraken2-standard", _tar(tmp_path / "k.tar.gz", files, None))
    db = client.post(f"{API}/databases/downloads", json={"key": e.key, "confirm_bytes": e.archive_bytes,
                                                         "accept_licence": True}).json()
    assert db["status"] == "installed", db["error_message"]
    assert db["path"] == str(dbdir / e.install_dir) and db["published_md5_checked"] == 5
    corrupt = {**files, "taxo.k2d": b"CONSTRUCTED but changed\n"}
    e2 = served("kraken2-standard", _tar(tmp_path / "k2.tar.gz", corrupt, None))
    client.delete(f"{API}/databases/{db['id']}")
    bad = client.post(f"{API}/databases/downloads", json={"key": e2.key, "confirm_bytes": e2.archive_bytes,
                                                          "accept_licence": True}).json()
    assert bad["status"] == "failed" and "publisher's MD5" in bad["error_message"]
    assert not Path(bad["path"]).exists()


def test_a_downloaded_archive_of_another_version_is_not_installed(client, dbdir, served, tmp_path):
    src = fx.genomad(tmp_path / "src")
    (src / "version.txt").write_text("1.8\n")
    files = {p.name: p.read_bytes() for p in src.iterdir()}
    e = served("genomad-1.9", _tar(tmp_path / "g.tar.gz", files, "genomad_db"))
    db = client.post(f"{API}/databases/downloads", json={"key": e.key, "confirm_bytes": e.archive_bytes,
                                                         "accept_licence": True}).json()
    assert db["status"] == "failed" and db["error_detail"]["code"] == "version_mismatch"


# --- Jobs record the version chosen -----------------------------------------------------------------------------

def test_record_use_keeps_kind_version_source_checksum_and_path(client, dbdir):
    from app.models import AnalysisJob, JobStatus

    db = register(client, fx.skani(dbdir / "skani_gtdb_r232-v0.4"), declared_version="GTDB r232").json()
    project = client.post(f"{API}/projects", json={"name": "Kinds"}).json()["id"]
    with SessionLocal() as session:
        job = AnalysisJob(project_id=project, job_type="x", tool_name="t", tool_version="0", status=JobStatus.pending,
                          log_text="")
        svc.record_use(job, session.get(ReferenceDatabase, db["id"]))
        session.add(job)
        session.commit()
        job_id = job.id
    j = client.get(f"{API}/jobs/{job_id}").json()
    assert (j["database_kind"], j["database_version"], j["database_version_source"], j["database_checksum"],
            j["database_path"]) == ("skani", "GTDB r232", "declared", None, db["path"])


def test_the_bakta_version_chosen_in_the_dialog_is_recorded_on_the_job(client, dbdir, held_queue):
    from arva_tools.registry import detect as detect_tool
    from test_annotation_api import GENOME, assemble, bakta_request, new_sample

    if detect_tool("bakta").path is None:
        pytest.skip("Bakta is not installed")
    default = register(client, fx.bakta(dbdir / "bakta-6.0")).json()
    other = register(client, fx.bakta(dbdir / "bakta-6.1", {"date": "2025-06-01", "major": 6, "minor": 1,
                                                            "type": "light"})).json()
    sample = new_sample(client)
    assembly = assemble(client, sample, GENOME)
    url = f"{API}/assemblies/{assembly['id']}/annotate/bakta"
    plan = client.post(f"{url}/preview", json={}).json()
    assert plan["database_id"] == default["id"]
    options = {d["id"]: d for d in plan["databases"]}
    assert options[default["id"]]["is_default"] and options[other["id"]]["version_source"] == "file"
    chosen = client.post(f"{url}/preview", json={"database_id": other["id"]}).json()
    assert chosen["database_id"] == other["id"]
    r = client.post(url, json={**bakta_request(chosen), "database_id": other["id"]})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert (job["database_kind"], job["database_key"], job["database_version"], job["database_version_source"],
            job["database_path"], job["database_checksum"]) == ("bakta", "bakta-light", "6.1", "file", other["path"],
                                                                None)


# --- Migration --------------------------------------------------------------------------------------------------

def test_the_database_kinds_migration_moves_the_manifest_and_back(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch_kinds")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_kinds"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch_kinds"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    manifest = [{"path": "version.json", "size": 2, "sha256": "0" * 64}]
    try:
        command.upgrade(cfg, "c3e9a5d7f1b4")
        with db.begin() as c:
            for rid, status, verified in (("a", "installed", "2026-10-01"), ("b", "registered", "2026-10-02")):
                c.execute(text("INSERT INTO reference_databases (id, key, name, version, path, status, origin, "
                               "checksum, details, verified_at, created_at, updated_at) VALUES (:id, 'bakta-light', "
                               "'Bakta', '6.0', :path, :status, 'download', 'sha256:x', :details, :v, now(), now())"),
                          {"id": rid, "path": f"/db/{rid}", "status": status, "v": verified,
                           "details": json.dumps({"manifest": manifest, "version_json": {"major": 6}})})
        command.upgrade(cfg, "head")
        with db.begin() as c:
            rows = {r.id: r for r in c.execute(text("SELECT id, kind, is_default, verification_level, "
                                                    "version_source, manifest, details FROM reference_databases"))}
            assert rows["a"].kind == "bakta" and rows["a"].manifest == manifest
            assert rows["a"].details == {"version_json": {"major": 6}, "file_count": 1}
            assert rows["b"].is_default and not rows["a"].is_default
            assert rows["a"].verification_level == "full" and rows["a"].version_source == "file"
        command.downgrade(cfg, "c3e9a5d7f1b4")
        with db.begin() as c:
            details = c.execute(text("SELECT details FROM reference_databases WHERE id = 'a'")).scalar()
            assert details == {"version_json": {"major": 6}, "manifest": manifest}
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_kinds"))



# --- Texts in both languages -------------------------------------------------------------------------------------

I18N = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "i18n" / "index.ts"


def _dictionaries() -> tuple[dict, dict]:
    source = I18N.read_text(encoding="utf-8")
    split = source.index("const es:")

    def entries(part: str) -> dict:
        return {k: json.loads(f'"{v}"') for k, v in re.findall(r'^  "([^"]+)": "((?:[^"\\]|\\.)*)",$', part, re.M)}

    return entries(source[:split]), entries(source[split:])


@pytest.mark.skipif(not I18N.exists(), reason="the web sources are not next to the API")
def test_every_database_code_and_server_text_has_both_languages():
    en, es = _dictionaries()
    keys = [f"api.error.{c}" for c in svc.MESSAGES] + [f"databases.problem.{c}" for c in detection.PROBLEMS]
    keys += [f"database.error.{c}" for c in ("not_recognised", "check_failed", "version_mismatch", "published_mismatch",
                                             "quick_failed")]
    assert [k for k in keys if k not in en or k not in es] == []
    # The interface translates a kind's or a catalogue entry's text only when its English is exactly the server's.
    server = {}
    for k in kinds.KINDS:
        for f in ("name", "description", "recognise", "version_from", "typical_size", "download_note", "licence"):
            server[f"databases.kind.{k.key}.{f}"] = getattr(k, f)
        server |= {f"databases.kind.{k.key}.tool{i}": t.versions for i, t in enumerate(k.tools)}
        server |= {f"databases.kind.{k.key}.unconfirmed{i}": u for i, u in enumerate(k.unconfirmed)}
    for e in catalogue.CATALOGUE:
        server |= {f"databases.catalogue.{e.key}.{f}": getattr(e, a) for f, a in (
            ("description", "description"), ("terms", "terms"), ("compatibility", "compatibility"),
            ("extracted", "extracted_size_note"))}
        server |= {f"databases.catalogue.{e.key}.note{i}": n for i, n in enumerate(e.notes)}
    assert {k: v for k, v in server.items() if en.get(k) != v} == {}
    assert [k for k in server if not es.get(k)] == []
