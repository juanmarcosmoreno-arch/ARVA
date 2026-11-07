"""Medaka models outside the medaka package as a kind of the Database Manager (services/medaka_models.py): the list
of models ARVA can download, the plan and its confirmation (against a local stand-in for GitHub's LFS server, so
nothing leaves this computer), the worker's checksum and archive checks, registering a file you have, and polishing
with a registered model (offered, never chosen for you, passed as -m <file>, recorded). Also the mate fix of item 69:
a single long-read FASTQ named like ENA's <run>_1.fastq.gz is not taken as read 1 of a pair, and the mate role can be
corrected through the API.

The model archives served and registered here are CONSTRUCTED (workflows/tool-adapters/tests/test_medaka_models.py:
medaka's layout and pickled globals, made with stand-in modules) and stand in for medaka's published file of
r941_min_hac_g507 (its SHA-256 and size are swapped in). The real downloaded model is used only when
ARVA_MEDAKA_TEST_MODEL names it (then a real Medaka polishing run uses it).
"""
import hashlib
import json
import os
import shutil
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from arva_tools import medaka_models as mm
from test_flye_api import ONT, R1, fake_flye, start  # noqa: F401 (fake_flye is a fixture)
from test_flye_api import new_sample as new_flye_sample
from test_flye_api import upload as upload_file
from test_polishing_api import (  # noqa: F401 (genome is a fixture)
    dorado_reads,
    draft_assembly,
    genome,
    job,
    new_sample,
    polish,
    ready,
    upload,
)

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import RawFile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "workflows" / "tool-adapters" / "tests"))
from test_medaka_models import meta_pickle, model_archive, weights_zip

API = "/api/v1"
R941 = "r941_min_hac_g507"
FILE = f"{R941}_model_pt.tar.gz"
REAL_MODEL = os.environ.get("ARVA_MEDAKA_TEST_MODEL")


@pytest.fixture
def dbdir(tmp_path, monkeypatch):
    folder = tmp_path / "databases"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "db_dir", folder)
    return folder.resolve()


@pytest.fixture
def model_file(tmp_path, monkeypatch):
    """A constructed model archive that stands in for medaka v2.1.1's published r941_min_hac_g507 file."""
    f = model_archive(tmp_path / "built" / FILE)
    monkeypatch.setitem(mm.PUBLISHED, R941, (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_size))
    return f


@pytest.fixture
def lfs_server(tmp_path, monkeypatch, model_file):
    """A local stand-in for media.githubusercontent.com/media/nanoporetech/medaka: <tag>/medaka/data/<file>."""
    root = tmp_path / "lfs"
    data = root / mm.MEDAKA_TAG / "medaka" / "data"
    data.mkdir(parents=True)
    shutil.copyfile(model_file, data / FILE)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "medaka_models_url", f"http://127.0.0.1:{server.server_port}")
    yield {"data": data, "file": data / FILE}
    server.shutdown()
    server.server_close()


def _download(client, folder="medaka-models/r941") -> dict:
    plan = client.post(f"{API}/databases/medaka-models/plan", json={"model": R941, "folder": folder}).json()
    r = client.post(f"{API}/databases/medaka-models/download",
                    json={"model": R941, "folder": folder, "confirm_sha256": plan["sha256"],
                          "confirm_bytes": plan["bytes"], "accept_licence": True})
    assert r.status_code == 202, r.text
    return client.get(f"{API}/databases/{r.json()['id']}").json()


def test_the_listing_offers_medakas_published_models_with_what_they_are_for(client, dbdir):
    body = client.get(f"{API}/databases/medaka-models").json()
    by_name = {m["name"]: m for m in body["available"]}
    assert {"r941_min_fast_g507", "r941_min_hac_g507", "r941_min_sup_g507", "r941_prom_hac_g507",
            "r941_e81_hac_g514", "r103_hac_g507", "r104_e81_sup_g5015"} <= set(by_name)
    m = by_name[R941]
    assert (m["chemistry"], m["device"], m["accuracy"], m["basecaller"]) == ("R9.4.1", "MinION/GridION", "hac",
                                                                             "Guppy 5.0.7")
    assert m["url"].endswith(f"/v2.1.1/medaka/data/{FILE}") and m["bytes"] == 1502971 and len(m["sha256"]) == 64
    assert m["database_id"] is None and "r941_min_high_g360" not in by_name
    assert body["licence"] == "Oxford Nanopore Technologies PLC. Public License Version 1.0"
    assert body["tag"] == "v2.1.1" and body["published_for"] == "2.1.1" and body["registered"] == []
    if body["medaka_version"]:
        assert body["shipped"] == ["r1041_e82_400bps_hac_v5.2.0", "r1041_e82_400bps_sup_v5.2.0"]
        assert not set(body["shipped"]) & set(by_name)
    kinds = {k["key"]: k for k in client.get(f"{API}/databases/kinds").json()}
    assert kinds["medaka_model"]["licence"].startswith("Oxford Nanopore Technologies PLC. Public License")
    assert kinds["medaka_model"]["download"] == "current" and "file" in kinds["medaka_model"]["accepts"]


def test_a_model_is_downloaded_only_after_confirmation_and_checked(client, dbdir, lfs_server):
    plan = client.post(f"{API}/databases/medaka-models/plan", json={"model": R941}).json()
    sha, size = mm.PUBLISHED[R941]
    assert (plan["model"], plan["sha256"], plan["bytes"], plan["file"]) == (R941, sha, size, FILE)
    assert plan["url"].startswith("http://127.0.0.1:") and plan["url"].endswith(f"/v2.1.1/medaka/data/{FILE}")
    assert plan["medaka_url"] == f"https://github.com/nanoporetech/medaka/raw/master/medaka/data/{FILE}"
    assert plan["licence"].startswith("Oxford Nanopore") and plan["enough"] and plan["blocked_by"] is None
    assert (plan["chemistry"], plan["basecaller"]) == ("R9.4.1", "Guppy 5.0.7")
    assert plan["target_path"].endswith(f"medaka-models/{R941}")
    url = f"{API}/databases/medaka-models/download"
    body = {"model": R941, "confirm_sha256": sha, "confirm_bytes": size}
    assert client.post(url, json={**body, "accept_licence": False}).json()["code"] == "medaka_model_confirm"
    changed = client.post(url, json={**body, "confirm_sha256": "0" * 64, "accept_licence": True})
    assert changed.status_code == 400 and changed.json()["code"] == "medaka_model_changed"
    unknown = client.post(f"{API}/databases/medaka-models/plan", json={"model": "r941_min_high_g360"})
    assert unknown.status_code == 400 and unknown.json()["code"] == "medaka_model_unknown"
    shipped = client.post(f"{API}/databases/medaka-models/plan", json={"model": "r1041_e82_400bps_sup_v5.2.0"})
    assert shipped.status_code == 400 and shipped.json()["code"] in ("medaka_model_shipped", "medaka_model_unknown")

    rec = _download(client, folder=None)
    assert rec["status"] == "installed", (rec["error_message"], rec["log_text"])
    assert (rec["kind"], rec["key"], rec["version"], rec["version_source"]) == ("medaka_model", f"medaka-{R941}", R941,
                                                                                 "checksum")
    assert rec["archive_checksum"] == f"sha256:{sha}" and rec["source_url"] == plan["url"]
    assert rec["licence"].startswith("Oxford Nanopore") and not rec["is_default"]
    assert rec["medaka_model"]["sha256"] == sha and rec["medaka_model"]["path"].endswith(f"{R941}/{FILE}")
    folder = Path(rec["path"])
    meta = json.loads((folder / "ARVA_DATABASE.json").read_text())
    assert (meta["kind"], meta["model"], meta["sha256"], meta["url"]) == ("medaka_model", R941, sha, plan["url"])
    assert meta["archive"]["meta_globals"] and (folder / FILE).read_bytes() == lfs_server["file"].read_bytes()
    assert "matches medaka v2.1.1's published file" in rec["log_text"]
    # One record per model; it is never the default (a model must match the reads, so it is always chosen).
    again = client.post(f"{API}/databases/medaka-models/plan", json={"model": R941}).json()
    assert again["blocked_code"] == "already_known"
    made = client.post(f"{API}/databases/{rec['id']}/default")
    assert made.status_code == 409 and made.json()["code"] == "no_default_kind"
    listed = client.get(f"{API}/databases/medaka-models").json()
    assert [r["model"] for r in listed["registered"]] == [R941]
    assert next(m for m in listed["available"] if m["name"] == R941)["database_id"] == rec["id"]
    assert client.post(f"{API}/databases/{rec['id']}/verify", json={"level": "quick"}).json()["status"] == "installed"
    assert client.delete(f"{API}/databases/{rec['id']}").status_code == 204
    assert not folder.exists()


def test_a_file_that_is_not_medakas_published_one_is_refused(client, dbdir, lfs_server):
    # The server sends other bytes of the same size: the SHA-256 differs, the file is deleted, nothing installed.
    other = bytearray(lfs_server["file"].read_bytes())
    other[-1] ^= 0xFF
    lfs_server["file"].write_bytes(bytes(other))
    rec = _download(client)
    assert rec["status"] == "failed" and rec["error_detail"]["code"] == "medaka_model_checksum"
    assert not (dbdir / "medaka-models" / "r941").exists()


def test_a_model_file_you_have_is_registered_after_the_checks(client, dbdir, model_file, tmp_path):
    mine = dbdir / "mine" / FILE
    mine.parent.mkdir()
    shutil.copyfile(model_file, mine)
    r = client.post(f"{API}/databases/register", json={"path": str(mine)})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert (rec["kind"], rec["version"], rec["version_source"], rec["origin"]) == ("medaka_model", R941, "checksum",
                                                                                    "register")
    assert rec["medaka_model"]["path"] == str(mine) and rec["medaka_model"]["sha256"] == mm.PUBLISHED[R941][0]
    assert not rec["is_default"]
    dup = dbdir / "copy" / FILE
    dup.parent.mkdir()
    shutil.copyfile(model_file, dup)
    again = client.post(f"{API}/databases/register", json={"path": str(dup)})
    assert again.status_code == 409 and again.json()["code"] == "medaka_model_known"
    # A file that imports something medaka's models never import is refused without being run.
    evil = model_archive(dbdir / "evil" / "r941_min_sup_g507_model_pt.tar.gz",
                         {"model/meta.pkl": meta_pickle(evil=True), "model/weights.pt": weights_zip()})
    refused = client.post(f"{API}/databases/register", json={"path": str(evil)})
    assert refused.status_code == 400 and refused.json()["code"] == "detection_failed"
    assert "never do" in refused.json()["detail"]
    # The deleted record of a registered file leaves the file where it was.
    assert client.delete(f"{API}/databases/{rec['id']}").status_code == 204 and mine.is_file()


@pytest.fixture
def r941_reads(client, genome, tmp_path, dbdir, model_file):  # noqa: F811
    """A Nanopore sample whose reads name an R9.4.1 HAC basecall model (dna_r9.4.1_e8_hac@v3.3, which medaka's own
    mapping gives r941_min_hac_g507), its draft, and the model registered from a file."""
    sample = new_sample(client, "nanopore")
    reads = upload(client, sample["id"], dorado_reads(genome / "ont.fastq.gz", tmp_path / "r941.fastq.gz",
                                                       model="dna_r9.4.1_e8_hac@v3.3"))
    draft = draft_assembly(client, sample, genome / "draft.fasta", [reads])
    f = Path(REAL_MODEL) if REAL_MODEL else model_file
    if REAL_MODEL:
        mm.PUBLISHED[R941] = (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_size)
    # A folder name with a space, as on a Mac's "/Volumes/My Disk": medaka_consensus expands -m unquoted.
    dest = dbdir / "my models" / FILE
    dest.parent.mkdir()
    shutil.copyfile(f, dest)
    rec = client.post(f"{API}/databases/register", json={"path": str(dest)}).json()
    return sample, reads, draft, rec


@pytest.mark.skipif(not ready("medaka", "minimap2", "samtools"), reason="needs Medaka, minimap2, samtools")
def test_polishing_offers_registered_models_but_uses_one_only_when_chosen(client, r941_reads):
    sample, reads, draft, rec = r941_reads
    inputs = {"long_file_id": reads}
    plan = client.post(f"{API}/assemblies/{draft['id']}/polishing/preview", json={"inputs": inputs}).json()
    m = plan["medaka"]
    assert [r["model"] for r in m["registered"]] == [R941] and R941 not in m["models"]
    assert m["registered"][0]["database_id"] == rec["id"] and m["registered"][0]["path"].endswith(FILE)
    assert m["suggestion"]["status"] == "mapped_registered" and m["suggestion"]["model"] == R941
    # Not chosen for the user, even though medaka's mapping names it.
    refused = polish(client, draft["id"], "medaka", inputs)
    assert refused.status_code == 400 and "registered in the Database Manager; choose it" in refused.text
    r = polish(client, draft["id"], "medaka", inputs, medaka={"model": R941}, threads=1)
    assert r.status_code == 202, r.text
    d = job(client, r.json()["id"])
    p = d["parameters"]
    assert p["model"] == R941 and p["model_file"] == rec["medaka_model"]["path"]
    mm_rec = p["medaka_model"]
    assert (mm_rec["model_source"], mm_rec["source"], mm_rec["database_id"]) == ("registered", "user", rec["id"])
    assert mm_rec["sha256"] == rec["medaka_model"]["sha256"]
    assert d["database_kind"] == "medaka_model" and d["database_version"] == R941
    # While the job is queued or runs, the model's record cannot be deleted.
    if d["status"] in ("pending", "queued", "running"):
        assert client.delete(f"{API}/databases/{rec['id']}").status_code == 409
    if REAL_MODEL and ready("dnadiff"):
        assert d["status"] == "completed", d["log_text"]
        (run,) = [c for c in d["commands"] if Path(c[0]).name == "medaka_consensus"]
        # medaka_consensus receives a checked copy in the job's work folder (it expands -m unquoted).
        staged = Path(run[run.index("-m") + 1])
        assert staged.name == FILE and staged.parent.name == "model" and staged.parent.parent.name == "work"
        assert str(staged) != rec["medaka_model"]["path"]
        s = d["result_summary"]
        assert [Path(f).name for f in s["medaka"]["model_files"]] == [FILE]
        assert s["medaka"]["model"]["model_source"] == "registered"
        assert "registered in the Database Manager" in d["log_text"]
        report = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
        step = next(st for st in report["processing"] if st["job_id"] == d["id"])
        assert step["highlights"][1].startswith(f"Medaka model {R941} (registered in the Database Manager")


# --- Item 69 (b): a lone "_1" long-read file is not a pair mate ------------------------------------------------

def test_a_single_long_read_fastq_named_like_ena_is_not_read_1_of_a_pair(client, fake_flye):  # noqa: F811
    fake_flye()
    sample = new_flye_sample(client)
    f = upload_file(client, sample["id"], ONT, name="SRR24838436_1.fastq.gz")
    assert f["read_mate"] is None
    assert f["mate_note"] == {"from_name": "R1", "set_by": "content", "reason": "long_reads",
                              "max_length": f["mate_note"]["max_length"], "platform": None}
    assert f["mate_note"]["max_length"] > 1000
    r = start(client, sample, [f])
    assert r.status_code == 202, r.text
    # Paired Illumina files keep their mates.
    ill = new_flye_sample(client, "illumina")
    r1 = upload_file(client, ill["id"], R1)
    assert r1["read_mate"] == "R1" and r1["mate_note"] is None


def test_a_lone_mate_is_not_refused_and_the_mate_role_can_be_corrected(client, fake_flye):  # noqa: F811
    fake_flye()
    sample = new_flye_sample(client)
    f = upload_file(client, sample["id"], ONT, name="SRR24838436_1.fastq.gz")
    # A file imported before ARVA read the content: marked R1 by its name alone, with no R2 in the sample.
    with SessionLocal() as db:
        raw = db.get(RawFile, f["id"])
        raw.read_mate, raw.validation_detail = "R1", {**raw.validation_detail, "mate": None}
        db.commit()
    assert client.get(f"{API}/files/{f['id']}").json()["read_mate"] == "R1"
    r = start(client, sample, [f])
    assert r.status_code == 202, r.text
    fixed = client.patch(f"{API}/files/{f['id']}", json={"read_mate": None})
    assert fixed.status_code == 200 and fixed.json()["read_mate"] is None
    assert fixed.json()["mate_note"]["set_by"] == "user" and fixed.json()["mate_note"]["previous"] == "R1"
    assert client.patch(f"{API}/files/{f['id']}", json={"read_mate": "R3"}).status_code == 422
    assert client.patch(f"{API}/files/{f['id']}", json={"read_mate": "R1"}).json()["read_mate"] == "R1"
