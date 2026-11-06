"""VFDB's full dataset (set B) as an optional database of the virulence screen: the download plan and its confirmation
(against a local stand-in for VFDB's download folder, so nothing reaches VFDB), the worker's conversion and indexing
with ABRicate's own makeblastdb, the database built from a file the user has, a registered ABRicate folder, the
choice of VFDB in the virulence dialog and in the workflow's virulence node (the bundled core set A stays the default
unless the user makes another the default), and what the results and reports say about the set searched.

The set B served here is CONSTRUCTED (random sequences under VFDB-style headers: workflows/tool-adapters/tests/
test_abricate_vfdb.py, made_up_setb); the genome searched is random sequence with three of those genes inside. The
real ABRicate 1.4.0 runs (skipped when it is not installed); ABRicate's bundled core set A finds nothing on it.
"""
import csv
import gzip
import hashlib
import io
import json
import os
import random
import sys
import threading
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import assemble, new_sample
from test_mobile_api import start
from test_workflows_api import _definition, _items, _run, _workflow

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AnalysisJob

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "workflows" / "tool-adapters" / "tests"))
from test_abricate_vfdb import _revcom, made_up_setb

API = "/api/v1"
REAL = Path.home() / ".arva-tools" / "conda" / "abricate" / "bin" / "abricate"
# The time VFDB's server gave its files on 2026-11-06 (Last-Modified) and the time gzip stored in set B.
LAST_MODIFIED = datetime(2026, 11, 6, 11, 30, 33, tzinfo=UTC).timestamp()
GZIP_MTIME = int(datetime(2026, 11, 6, 11, 30, 20, tzinfo=UTC).timestamp())


@pytest.fixture
def mobile_real_abricate(monkeypatch):
    if not REAL.is_file():
        pytest.skip("ABRicate is not installed (~/.arva-tools/conda/abricate)")
    monkeypatch.setenv("ARVA_TOOL_ABRICATE", str(REAL))
    registry._CACHE.pop("abricate", None)
    assert detect("abricate", refresh=True).path
    return REAL


def setb_gz(path: Path, raw: bytes | None = None) -> Path:
    raw = raw if raw is not None else made_up_setb()[0]
    with open(path, "wb") as fh, gzip.GzipFile(filename="VFDB_setB_nt.fas", mode="wb", fileobj=fh,
                                              mtime=GZIP_MTIME) as gz:
        gz.write(raw)
    return path


@pytest.fixture
def vfdb_server(tmp_path, monkeypatch):
    """A local stand-in for https://www.mgc.ac.cn/VFs/Down: VFDB_setB_nt.fas.gz dated as VFDB's server dated it."""
    root = tmp_path / "Down"
    root.mkdir()
    f = setb_gz(root / "VFDB_setB_nt.fas.gz")
    os.utime(f, (LAST_MODIFIED, LAST_MODIFIED))
    html = {"on": False}

    class Handler(SimpleHTTPRequestHandler):
        def guess_type(self, path):
            return "text/html; charset=utf-8" if html["on"] else "application/x-gzip"

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "vfdb_url", f"http://127.0.0.1:{server.server_port}")
    yield {"root": root, "file": f, "bytes": f.stat().st_size, "html": html}
    server.shutdown()
    server.server_close()


def _download(client, folder: str) -> dict:
    plan = client.post(f"{API}/databases/vfdb/plan", json={"folder": folder}).json()
    r = client.post(f"{API}/databases/vfdb/download", json={"folder": folder, "confirm_version": plan["version"],
                                                             "confirm_bytes": plan["bytes"], "accept_terms": True})
    assert r.status_code == 202, r.text
    rec = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert rec["status"] == "installed", (rec.get("error_message"), rec.get("log_text"))
    return rec


def test_set_b_download_is_planned_confirmed_converted_indexed_and_checked(client, vfdb_server, mobile_real_abricate):
    dbs = {d["key"]: d for d in client.get(f"{API}/databases").json()}
    bundled = dbs["abricate-vfdb"]
    assert bundled["is_default"] and bundled["vfdb"]["set"] == "A" and bundled["vfdb"]["dataset"] == "core"
    plan = client.post(f"{API}/databases/vfdb/plan", json={"folder": "vfdb-dl"}).json()
    # What the confirmation shows: the file, its size and date as the server states them, the source, VFDB's licence
    # and citation, the folder and the space; and that VFDB publishes no checksum.
    assert (plan["file"], plan["bytes"], plan["version"]) == ("VFDB_setB_nt.fas.gz", vfdb_server["bytes"], "2026-11-06")
    assert plan["last_modified"] == "Fri, 06 Nov 2026 11:30:33 GMT" and plan["url"].endswith("/VFDB_setB_nt.fas.gz")
    assert plan["licence"].startswith("CC BY-NC 4.0") and plan["licence_url"].endswith("/by-nc/4.0/")
    assert "VFDB 2025" in plan["citation"] and plan["terms_url"].endswith("main.htm#termofuse")
    assert plan["no_checksum"] and plan["only_current"] and plan["enough"] and plan["blocked_by"] is None
    assert plan["set"] == "B" and plan["dataset"] == "full" and plan["target_path"].endswith("vfdb-dl/vfdb_setB")
    assert plan["required_bytes"] == plan["bytes"] * 8

    start_url = f"{API}/databases/vfdb/download"
    body = {"folder": "vfdb-dl", "confirm_version": "2026-11-06", "confirm_bytes": plan["bytes"]}
    assert client.post(start_url, json={**body, "accept_terms": False}).json()["code"] == "vfdb_confirm"
    changed = client.post(start_url, json={**body, "confirm_version": "2026-10-23", "accept_terms": True})
    assert changed.status_code == 400 and changed.json()["code"] == "vfdb_changed"
    assert client.post(start_url, json={**body, "confirm_bytes": 5, "accept_terms": True}).json()["code"] == \
        "vfdb_changed"
    r = client.post(start_url, json={**body, "accept_terms": True})
    assert r.status_code == 202, r.text
    rec = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert rec["status"] == "installed", (rec.get("error_message"), rec.get("log_text"))
    raw = made_up_setb()[0]
    gz_sha = hashlib.sha256(vfdb_server["file"].read_bytes()).hexdigest()
    folder = Path(rec["path"])
    assert (rec["kind"], rec["key"], rec["name"], rec["version"]) == ("vfdb", "vfdb-setB", "VFDB full (set B)",
                                                                      "2026-11-06")
    assert rec["archive_checksum"] == f"sha256:{gz_sha}" and rec["checksum"].startswith("sha256:")
    assert rec["compatibility"]["code"] == "abricate_format" and not rec["is_default"]
    v = rec["vfdb"]
    assert (v["set"], v["dataset"], v["version"], v["bundled"]) == ("B", "full", "2026-11-06", False)
    assert v["source"]["sha256"] == gz_sha and v["source"]["last_modified"] == plan["last_modified"]
    assert v["source"]["gzip_mtime"] == "2026-11-06T11:30:20+00:00"
    assert v["fasta"] == {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "records": 7}
    seq = (folder / "sequences").read_bytes()
    assert v["sequences"]["sha256"] == hashlib.sha256(seq).hexdigest() and v["sequences"]["records"] == 6
    meta = json.loads((folder / "ARVA_DATABASE.json").read_text())
    assert (meta["set"], meta["version"], meta["version_from"], meta["abricate"]) == (
        "B", "2026-11-06", "last_modified", {"datadir": "..", "db": "vfdb_setB"})
    assert meta["index"]["argv"][:6] == ["makeblastdb", "-in", "sequences", "-title", "vfdb", "-dbtype"]
    assert meta["index"]["sequences"] == 6 and meta["conversion"]["gene_spaces_replaced"] == 1
    assert (folder / "src" / "VFDB_setB_nt.fas.gz").read_bytes() == vfdb_server["file"].read_bytes()
    assert folder.parent.name == "vfdb-dl" and sorted(p.name for p in folder.parent.iterdir()) == ["vfdb_setB"]
    assert "VFDB publishes no checksum" in rec["log_text"] and "blastdbcmd -info: 6 sequences" in rec["log_text"]
    again = client.post(f"{API}/databases/vfdb/plan", json={}).json()
    assert again["blocked_code"] == "already_known"
    # Deleting the record removes the folder ARVA made, and the dated folder above it.
    assert client.delete(f"{API}/databases/{rec['id']}").status_code == 204
    assert not folder.parent.exists()


def test_a_web_page_instead_of_the_file_is_refused(client, vfdb_server, mobile_real_abricate):
    vfdb_server["html"]["on"] = True
    r = client.post(f"{API}/databases/vfdb/plan", json={})
    assert r.status_code == 502 and r.json()["code"] == "vfdb_not_a_file"
    # Served as gzip but holding VFDB's security filter page: the worker refuses it and installs nothing.
    vfdb_server["html"]["on"] = False
    page = b"<html><head><title>WAF</title></head><body>challenge</body></html>\n"
    vfdb_server["file"].write_bytes(page)
    os.utime(vfdb_server["file"], (LAST_MODIFIED, LAST_MODIFIED))
    plan = client.post(f"{API}/databases/vfdb/plan", json={"folder": "vfdb-waf"}).json()
    r = client.post(f"{API}/databases/vfdb/download", json={"folder": "vfdb-waf", "confirm_version": plan["version"],
                                                             "confirm_bytes": plan["bytes"], "accept_terms": True})
    rec = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert rec["status"] == "failed" and rec["error_detail"]["code"] == "vfdb_bad_file"
    assert not Path(rec["path"]).exists()


def test_set_b_built_from_the_users_file_and_a_registered_abricate_folder(client, mobile_real_abricate,
                                                                          storage_root, tmp_path):
    own = storage_root / "databases" / "my-pipeline"
    own.mkdir(parents=True, exist_ok=True)
    gz = setb_gz(own / "VFDB_setB_nt.fas.gz")
    plan = client.post(f"{API}/databases/vfdb/build-plan", json={"path": str(gz), "folder": "vfdb-own"}).json()
    assert (plan["set"], plan["version"], plan["version_source"], plan["gzip_name"]) == (
        "B", "2026-11-06", "file", "VFDB_setB_nt.fas")
    r = client.post(f"{API}/databases/vfdb/build", json={"path": str(gz), "folder": "vfdb-own",
                                                          "confirm_bytes": plan["bytes"], "accept_terms": True})
    assert r.status_code == 202, r.text
    rec = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert rec["status"] == "installed", (rec.get("error_message"), rec.get("log_text"))
    assert rec["vfdb"]["source"]["path"] == str(gz) and rec["vfdb"]["sequences"]["records"] == 6
    assert gz.is_file() and not (Path(rec["path"]) / "src").joinpath("VFDB_setB_nt.fas.gz").exists()

    # A plain FASTA under another name states neither its set nor its date: both are asked for.
    plain = own / "virulence_full.fasta"
    plain.write_bytes(made_up_setb()[0])
    asked = client.post(f"{API}/databases/vfdb/build-plan", json={"path": str(plain)})
    assert asked.status_code == 400 and asked.json()["code"] == "vfdb_set_needed"
    undated = client.post(f"{API}/databases/vfdb/build-plan", json={"path": str(plain), "vfdb_set": "B"})
    assert undated.json()["code"] == "vfdb_version_needed"
    p2 = client.post(f"{API}/databases/vfdb/build-plan", json={"path": str(plain), "vfdb_set": "B",
                                                                "declared_version": "2026-10-01"}).json()
    assert (p2["version"], p2["version_source"]) == ("2026-10-01", "declared")

    # A folder the user built with abricate-get_db (here ARVA's converter and makeblastdb, the same files): its set is
    # declared at registration, its version too (the index date is suggested).
    built = Path(rec["path"])
    theirs = storage_root / "databases" / "my-abricate-db" / "vfdb"
    theirs.mkdir(parents=True, exist_ok=True)
    for f in built.iterdir():
        if f.is_file() and f.name != "ARVA_DATABASE.json":
            (theirs / f.name).write_bytes(f.read_bytes())
    found = client.get(f"{API}/databases/detect", params={"path": str(theirs)}).json()
    (cand,) = [c for c in found["candidates"] if c["kind"] == "vfdb"]
    assert cand["variant"] == "abricate_folder" and cand["facts"]["abricate"]["header_style"] == "abricate"
    no_set = client.post(f"{API}/databases/register", json={"path": str(theirs), "declared_version": "2026-11-06"})
    assert no_set.status_code == 400 and no_set.json()["code"] == "vfdb_set_needed"
    reg = client.post(f"{API}/databases/register", json={"path": str(theirs), "declared_version": "2026-11-06",
                                                          "vfdb_set": "B"})
    assert reg.status_code == 201, reg.text
    reg = reg.json()
    assert reg["name"] == "VFDB full (set B), your ABRicate folder" and reg["vfdb"]["set"] == "B"
    assert reg["version_source"] == "declared" and not reg["is_default"] and reg["checksum"] is None
    # A search of it records the checksum of what it searched (the folder was registered without the full checksum).
    sample = new_sample(client, "VF-REG")
    a = assemble(client, sample, _genome(tmp_path / "g.fna", made_up_setb()[1]))
    job = start(client, f"/assemblies/{a['id']}/virulence", {"database_id": reg["id"]})
    assert job["commands"][0][1:5] == ["--datadir", str(theirs.parent), "--db", "vfdb"]
    assert job["database_checksum"].startswith("sha256:") and job["parameters"]["vfdb"]["checksum"] == \
        job["database_checksum"]
    assert job["parameters"]["vfdb"]["set"] == "B" and job["result_summary"]["counts"]["hits"] == 3


def _genome(path: Path, seqs: dict[str, str]) -> Path:
    rng = random.Random(9)
    filler = lambda n: "".join(rng.choice("ACGT") for _ in range(n))  # noqa: E731
    one = filler(5000) + seqs["selq"] + filler(3000) + _revcom(seqs["clp G"]) + filler(4000)
    two = filler(2000) + seqs["geneA"] + filler(2500)
    path.write_text(f">contig_1\n{one}\n>contig_2\n{two}\n")
    return path


def test_virulence_dialog_and_workflow_node_choose_the_vfdb_and_reports_name_the_set(
        client, vfdb_server, mobile_real_abricate, tmp_path):
    setb = _download(client, "vfdb-run")
    bundled = next(d for d in client.get(f"{API}/databases").json() if d["key"] == "abricate-vfdb")
    sample = new_sample(client, "VF-1")
    a = assemble(client, sample, _genome(tmp_path / "g.fna", made_up_setb()[1]))

    plan = client.post(f"{API}/assemblies/{a['id']}/virulence/preview", json={}).json()
    assert plan["problems"] == [] and plan["database"]["id"] == bundled["id"] and plan["database"]["vfdb_set"] == "A"
    assert {d["vfdb_set"] for d in plan["databases"]} == {"A", "B"} and plan["databases"][0]["id"] == bundled["id"]
    chosen = client.post(f"{API}/assemblies/{a['id']}/virulence/preview", json={"database_id": setb["id"]}).json()
    assert chosen["database"]["id"] == setb["id"] and chosen["database"]["dataset"] == "full"
    wrong = client.post(f"{API}/assemblies/{a['id']}/virulence/preview", json={"database_id": a["id"]})
    assert wrong.status_code == 400

    core = start(client, f"/assemblies/{a['id']}/virulence", {})
    assert core["commands"][0][1:5] == ["--datadir", str(Path(bundled["path"]).parent), "--db", "vfdb"]
    assert core["result_summary"]["counts"]["hits"] == 0 and core["parameters"]["vfdb"]["set"] == "A"
    full = start(client, f"/assemblies/{a['id']}/virulence", {"database_id": setb["id"]})
    assert full["commands"][0][1:5] == ["--datadir", str(Path(setb["path"]).parent), "--db", "vfdb_setB"]
    assert (full["database_key"], full["database_version"], full["database_checksum"]) == (
        "vfdb-setB", "2026-11-06", setb["checksum"])
    p = full["parameters"]["vfdb"]
    assert (p["set"], p["dataset"], p["version"], p["source"]["sha256"]) == (
        "B", "full", "2026-11-06", setb["vfdb"]["source"]["sha256"])
    assert full["result_summary"]["counts"]["hits"] == 3
    codes = [w["code"] for w in full["result_summary"]["warnings"]]
    assert "vfdb_full" in codes and "vfdb_terms" in codes and "vfdb_core" not in codes

    vir = client.get(f"{API}/samples/{sample['id']}/virulence").json()
    run = next(r for r in vir["runs"] if r["job_id"] == full["id"])
    assert run["vfdb"]["set"] == "B" and {h["gene"] for h in run["hits"]} == {"selq", "clp_G", "geneA"}
    (view,) = vir["assemblies"]
    assert (view["sources"]["vfdb"]["vfdb_set"], view["sources"]["vfdb"]["database_version"]) == ("B", "2026-11-06")
    clp = next(r for r in view["rows"] if r["gene"] == "clp_G")
    assert clp["vf_name"] == "Made-up antigen" and clp["strand"] == "-"

    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "VFDB full (set B) 2026-11-06" in html and "also predicted virulence factors" in html
    rows = list(csv.DictReader(io.StringIO(client.get(f"{API}/samples/{sample['id']}/report?format=csv").text)))
    vrows = [r for r in rows if r["record_type"] == "virulence"]
    assert {(r["virulence_vfdb_set"], r["virulence_vfdb_version"]) for r in vrows if r["virulence_gene"] != "none found"
            } == {("B", "2026-11-06")}
    project = sample["project_id"]
    prow = next(r for r in csv.DictReader(io.StringIO(client.get(f"{API}/projects/{project}/report?format=csv").text))
                if r["sample"] == "VF-1")
    assert prow["virulence_vfdb"] == "VFDB full (set B) 2026-11-06" and "selq" in prow["virulence_genes"].split(";")
    data = client.get(f"{API}/projects/{project}/report?format=json").json()
    mine = next(r for r in data["samples"] if r["code"] == "VF-1")
    assert (mine["virulence"]["vfdb_set"], mine["virulence"]["vfdb_dataset"]) == ("B", "full")
    assert "VFDB completo (set B) 2026-11-06" in client.get(f"{API}/projects/{project}/report?format=html&lang=es").text
    from app.services.batches import _found_metrics

    with SessionLocal() as db:
        m = _found_metrics(db, db.get(AnalysisJob, full["id"]))
        assert (m["vfdb.set"], m["vfdb.version"], m["vfdb.hits"]) == ("B", "2026-11-06", 3)
        assert _found_metrics(db, db.get(AnalysisJob, core["id"]))["vfdb.set"] == "A"

    # The workflow's virulence node: no database_id is the default VFDB (still the bundled core set A); a chosen one
    # is searched; once the user makes set B the default, an unset node searches it.
    wf = _workflow(client, _definition([("asm", "assembly_input", {}), ("vir", "virulence", {}),
                                        ("vir_b", "virulence", {"database_id": setb["id"]})],
                                       [("asm", "assembly", "vir", "assembly"), ("asm", "assembly", "vir_b",
                                                                                 "assembly")]), "VFDB choice")
    assert [x["code"] for x in wf["problems"]] == []
    batch = _run(client, {"id": project}, wf, [sample])

    def node_job(run: dict, node: str) -> dict:
        (item,) = _items(run, node)
        assert item["status"] == "completed", item
        return client.get(f"{API}/jobs/{item['job_id']}").json()

    assert node_job(batch, "vir")["parameters"]["vfdb"]["set"] == "A"
    assert node_job(batch, "vir_b")["parameters"]["vfdb"]["set"] == "B"
    assert client.post(f"{API}/databases/{setb['id']}/default").status_code == 200
    plan = client.post(f"{API}/assemblies/{a['id']}/virulence/preview", json={}).json()
    assert plan["database"]["id"] == setb["id"]
    batch2 = _run(client, {"id": project}, _workflow(client, _definition(
        [("asm", "assembly_input", {}), ("vir", "virulence", {})], [("asm", "assembly", "vir", "assembly")]),
        "default"), [sample])
    assert node_job(batch2, "vir")["parameters"]["vfdb"]["set"] == "B"
    # Recording ABRicate's bundled copy again does not take the default back from the user's choice.
    assert next(d for d in client.get(f"{API}/databases").json() if d["id"] == setb["id"])["is_default"]


def test_set_b_names_keep_the_amrfinderplus_cross_check():
    """Set B names the S. aureus enterotoxin-like genes sel<x> (selp, seln...) and finds lukD/lukE where set A's best
    match was lukF-PV: the same gene under VFDB's name is not a cross-hit, another gene still is."""
    from test_mobile_api import _vrow

    from app.services.virulence import _same_gene, row_flags

    assert _same_gene("selp", "sep") and _same_gene("seln", "sen") and _same_gene("selm", "sem")
    assert not _same_gene("selp", "sea") and not _same_gene("lukD", "lukF-PV")
    sel = _vrow("vfdb", "selp", 100, 900, 100.0)
    sep = _vrow("amrfinderplus", "sep", 100, 900, 99.5)
    luk = _vrow("vfdb", "lukD", 2000, 2980, 100.0)
    lukd = _vrow("amrfinderplus", "lukD", 1994, 2986, 94.19)
    old = _vrow("vfdb", "lukF-PV", 5000, 5968, 82.37)
    other = _vrow("amrfinderplus", "lukD", 4994, 5974, 94.19)
    rows = [sel, sep, luk, lukd, old, other]
    row_flags(rows)
    assert sel["flags"] == [] and luk["flags"] == []
    assert old["flags"][0]["code"] == "probable_other_gene" and old["flags"][0]["params"]["gene"] == "lukD"
