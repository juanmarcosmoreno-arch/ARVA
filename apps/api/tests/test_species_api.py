"""Species identification: previews (methods, databases, problems, GTDB-Tk's memory refusal), request checks, the
recorded job, results with ARVA's reading and the consistency checks, files, overviews, CSV, the report section,
the run-time re-check of the database, and the NCBI Datasets collection builder against a local stand-in server.

Real-tool runs skip when the tool is not installed. FastANI and skani run on ARVA's SYNTHETIC genome against a
collection holding one random SYNTHETIC sequence (expectation: no reference reported; nothing to download). With
ARVA_TEST_SPECIES_GENOMES (the NCBI packages of workflows/tool-adapters/tests/fixtures/species/README.md) they also
run on S. aureus NCTC 8325 (GCF_000013425.1) against three Staphylococcus type strains.

The NCBI stand-in serves real API answers recorded on 2026-10-29 (tests/fixtures/ncbi: taxonomy of "Staphylococcus
argenteus", "Bacillus" and an unknown name; the two pages of type-material RefSeq genomes of S. argenteus; their
download summary). Its genome package is a test construct — the real accessions and metadata with SYNTHETIC
sequences in place of the genomes — that is only downloaded, checked and installed, never analysed.
"""
import hashlib
import io
import json
import os
import random
import shutil
import stat
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest
from arva_tools import registry
from arva_tools.registry import detect
from arva_tools.runner import run_command
from test_annotation_api import assemble, new_sample

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, DatabaseStatus, JobStatus, MlstResult, ReferenceDatabase
from app.services import locations
from app.services import ncbi_datasets as ncbi
from app.tasks.ncbi_collection import run_ncbi_collection
from app.tasks.species import run_species_job

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
SYNTHETIC = REPO / "examples" / "synthetic-genome" / "reference.fasta"
NCBI_FX = Path(__file__).parent / "fixtures" / "ncbi"
GENOMES = os.environ.get("ARVA_TEST_SPECIES_GENOMES")
REFS = ("GCF_006094915.1", "GCF_000236925.1", "GCF_006094375.1")


@pytest.fixture(autouse=True)
def native(monkeypatch):
    monkeypatch.setattr(locations, "in_container", lambda: False)


@pytest.fixture
def dbdir(tmp_path, monkeypatch):
    folder = tmp_path / "databases"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "db_dir", folder)
    return folder.resolve()


def real(tool_id: str) -> str:
    registry._CACHE.pop(tool_id, None)
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"{tool_id} is not available: {d.message}")
    return d.path


def synthetic_collection(dbdir: Path) -> Path:
    folder = dbdir / "synthetic-collection"
    folder.mkdir()
    rng = random.Random(11)
    (folder / "SYNTHETIC_other.fna").write_text(
        ">SYNTHETIC_other random sequence, not biological data\n" + "".join(rng.choice("ACGT") for _ in range(300_000))
        + "\n")
    return folder


def register(client, path: Path, **body) -> dict:
    r = client.post(f"{API}/databases/register", json={"path": str(path), "collection_date": "2026-10-29", **body})
    assert r.status_code == 201, r.text
    return r.json()


def preview(client, assembly: dict, method: str, database_id: str | None = None) -> dict:
    r = client.post(f"{API}/assemblies/{assembly['id']}/species/preview",
                    json={"method": method, "database_id": database_id})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, assembly: dict, method: str, database_id: str | None = None) -> dict:
    r = client.post(f"{API}/assemblies/{assembly['id']}/species",
                    json={"method": method, "database_id": database_id, "confirmed": True})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job.get("error_message")
    return job


def codes(items) -> list[str]:
    return [x["code"] for x in items]


def test_preview_lists_the_methods_and_blocks_without_a_database(client, dbdir):
    sample = new_sample(client, "SP-1")
    a = assemble(client, sample, SYNTHETIC)
    p = preview(client, a, "fastani")
    assert set(p["methods"]) == {"fastani", "skani", "mash", "sylph", "gtdbtk"}
    assert p["validation"] == "validated" and p["database_kind"] == "reference_genomes"
    assert "no_database" in codes(p["problems"]) and p["database"] is None
    assert p["assembly"]["synthetic_evidence"] and p["context"] == {"mlst": None, "annotation": None}
    assert preview(client, a, "mash")["validation"] == "test_database"
    r = client.post(f"{API}/assemblies/{a['id']}/species", json={"method": "fastani", "confirmed": False})
    assert (r.status_code, r.json()["code"]) == (400, "species_confirm")
    r = client.post(f"{API}/assemblies/{a['id']}/species", json={"method": "fastani", "confirmed": True})
    assert (r.status_code, r.json()["code"]) == (409, "species_blocked")
    r = client.post(f"{API}/assemblies/{a['id']}/species/preview", json={"method": "blast"})
    assert r.status_code == 422


def test_gtdbtk_is_refused_below_its_documented_memory(client, dbdir):
    sample = new_sample(client, "SP-2")
    a = assemble(client, sample, SYNTHETIC)
    p = preview(client, a, "gtdbtk")
    memory = next(x for x in p["problems"] if x["code"] == "gtdbtk_memory")
    assert memory["params"]["required"] == 140 and memory["params"]["available"] < 140
    assert p["gtdbtk_memory_gb"] == {"bacteria": 140, "archaea": 100} and p["validation"] == "not_validated"
    r = client.post(f"{API}/assemblies/{a['id']}/species", json={"method": "gtdbtk", "confirmed": True})
    assert r.status_code == 409 and "140 GB" in r.json()["detail"]


@pytest.mark.parametrize("method", ["fastani", "skani"])
def test_real_tool_on_the_synthetic_genome_finds_no_reference(client, dbdir, method):
    real(method)
    sample = new_sample(client, f"SP-{method}")
    a = assemble(client, sample, SYNTHETIC)
    db = register(client, synthetic_collection(dbdir))
    p = preview(client, a, method)
    assert p["problems"] == [] and p["database"]["id"] == db["id"]
    assert p["database"]["collection"]["genomes"] == 1
    job = run(client, a, method)
    assert job["database_kind"] == "reference_genomes" and job["database_version"] == db["version"]
    (res,) = client.get(f"{API}/samples/{sample['id']}/species").json()
    assert (res["method"], res["status"], res["species"], res["hits"]) == (method, "no_hits", None, [])
    assert "synthetic_input" in codes(res["warnings"])
    assert codes(res["interpretation"]["caveats"])[0] == "collection_bound"
    assert res["interpretation"]["thresholds"] == {"ani_boundary": 95.0, "min_af": 0.5, "margin": 0.5}
    assert len(res["details"]["references"]) == 1 and len(res["details"]["references"][0]["sha256"]) == 64
    assert res["files"]["output"]["size_bytes"] >= 0 and "references" in res["files"]
    r = client.get(f"{API}/species/{res['id']}/files/references")
    assert r.status_code == 200 and "SYNTHETIC_other.fna" in r.text
    assert client.get(f"{API}/species/{res['id']}/files/nothing").status_code == 404
    o = client.get(f"{API}/projects/{sample['project_id']}/species").json()
    assert o["samples"][0]["latest"]["status"] == "no_hits"
    csv_text = client.get(f"{API}/projects/{sample['project_id']}/species.csv").text
    assert csv_text.splitlines()[0].startswith("project,sample_code,assembly_id") and method in csv_text
    assert client.get(f"{API}/species").json()["total_results"] == 1
    report = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    assert report["species"][0]["status"] == "no_hits" and report["species"][0]["caveats"][0]["text"]
    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "Species identification" in html and "Jain" in html and "No reference was reported" in html
    report_csv = client.get(f"{API}/samples/{sample['id']}/report?format=csv").text
    assert f",species,{a['id']}" in report_csv.replace("\r", "") or "species" in report_csv


@pytest.mark.parametrize("method", ["mash", "sylph"])
def test_real_mash_and_sylph_on_a_synthetic_test_database(client, dbdir, method):
    exe = real(method)
    folder = synthetic_collection(dbdir)
    genome = folder / "SYNTHETIC_other.fna"
    if method == "mash":
        run_command([exe, "sketch", "-o", str(folder / "synthetic"), "-k", "21", "-s", "1000", "-S", "42", str(genome)],
                    cwd=folder, stderr_path=dbdir / "sketch.log")
        database = folder / "synthetic.msh"
    else:
        run_command([exe, "sketch", "-g", str(genome), "-o", str(folder / "synthetic"), "-t", "1", "-c", "200", "-k",
                     "31"], cwd=folder, stderr_path=dbdir / "sketch.log")
        database = folder / "synthetic.syldb"
    db = register(client, database, kind=method, declared_version="ARVA test sketch")
    sample = new_sample(client, f"SP-{method}")
    a = assemble(client, sample, SYNTHETIC)
    assert preview(client, a, method)["problems"] == []
    run(client, a, method, db["id"])
    (res,) = client.get(f"{API}/samples/{sample['id']}/species").json()
    assert res["status"] == "no_hits" and res["species"] is None
    assert {"synthetic_input", "test_database_only"} <= set(codes(res["warnings"]))
    if method == "mash":
        assert res["details"]["sketch"]["kmer"] == 21 and res["hits"][0]["shared"] == 0
        assert codes(res["interpretation"]["caveats"])[0] == "mash_not_ani"
    else:
        assert res["details"]["sylph_database"] == {"c": 200, "k": 31, "genomes": 1} and res["hits"] == []
        assert res["parameters"]["settings"]["c"] == 200


def test_job_refuses_a_changed_database(client, dbdir, held_queue):
    real("fastani")
    sample = new_sample(client, "SP-3")
    a = assemble(client, sample, SYNTHETIC)
    db = register(client, synthetic_collection(dbdir))
    r = client.post(f"{API}/assemblies/{a['id']}/species", json={"method": "fastani", "confirmed": True})
    assert r.status_code == 202
    with SessionLocal() as s:
        s.get(ReferenceDatabase, db["id"]).version = "FASTA folder 2026-10-30 #changed"
        s.commit()
    run_species_job(r.json()["id"])
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and job["error_detail"]["code"] == "species_database_changed"


@pytest.fixture
def genomes():
    if not GENOMES or not (Path(GENOMES) / "staphylococcus").is_dir():
        pytest.skip("ARVA_TEST_SPECIES_GENOMES (the NCBI packages of the species fixtures README) is not set")
    return Path(GENOMES)


@pytest.mark.parametrize(("method", "ani"), [("fastani", 99.9171), ("skani", 99.87)])
def test_real_genomes_same_species_with_mlst_consistency(client, dbdir, genomes, method, ani):
    real(method)
    pkg = dbdir / "staphylococcus"
    shutil.copytree(genomes / "staphylococcus", pkg)
    data = pkg / "ncbi_dataset" / "data"
    refs = dbdir / "staph_type_strains.txt"
    refs.write_text("".join(f"{next((data / acc).glob('*_genomic.fna'))}\n" for acc in REFS))
    db = register(client, refs)
    sample = new_sample(client, "NCTC8325")
    a = assemble(client, sample, next((data / "GCF_000013425.1").glob("*_genomic.fna")))
    with SessionLocal() as s:
        # mlst 2.35.0's real call for this genome (workflows/tool-adapters/tests/fixtures/mlst, saureus_NC_007795.1).
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="mlst_typing",
                          tool_name="mlst", tool_version="2.35.0", parameters={}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        s.add(job)
        s.flush()
        s.add(MlstResult(sample_id=sample["id"], assembly_id=a["id"], job_id=job.id, tool="mlst",
                         tool_version="2.35.0", parameters={}, scheme="saureus", st="8", status="PERFECT", score=100,
                         alleles=[], clonal_complex={}, warnings=[], details={}, files={}))
        s.commit()
    assert preview(client, a, method)["context"]["mlst"]["scheme"] == "saureus"
    run(client, a, method)
    (res,) = client.get(f"{API}/samples/{sample['id']}/species").json()
    assert (res["status"], res["species"]) == ("same_species", "Staphylococcus aureus")
    best = res["hits"][0]
    assert (best["accession"], best["ani"], best["type_material"]) == ("GCF_006094915.1", ani, True)
    assert [c["outcome"] for c in res["consistency"]] == ["agree"]
    assert res["interpretation"]["runner_up"]["species"] == "Staphylococcus argenteus"
    assert res["database_version"] == db["version"] and len(res["details"]["references"]) == 3


# --- NCBI Datasets builder -------------------------------------------------------------------------------------------

class StandIn(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []
    package_override: ClassVar[bytes | None] = None

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body: bytes | None = None) -> dict:
        u = urlsplit(self.path)
        entry = {"method": self.command, "path": u.path, "query": parse_qs(u.query), "headers": dict(self.headers),
                 "body": json.loads(body) if body else None}
        StandIn.requests.append(entry)
        return entry

    def do_GET(self):
        e = self._record()
        path = e["path"].removeprefix("/v2")
        if path == "/taxonomy/taxon/Staphylococcus%20argenteus" or path == "/taxonomy/taxon/985002":
            return self._send(200, (NCBI_FX / "taxonomy_staphylococcus_argenteus.json").read_bytes())
        if path == "/taxonomy/taxon/Bacillus":
            return self._send(200, (NCBI_FX / "taxonomy_bacillus.json").read_bytes())
        if path.startswith("/taxonomy/taxon/"):
            return self._send(200, (NCBI_FX / "taxonomy_unknown.json").read_bytes())
        if path == "/genome/taxon/985002/dataset_report":
            page = "report_page2.json" if e["query"].get("page_token") else "report_page1.json"
            return self._send(200, (NCBI_FX / page).read_bytes())
        if path == "/genome/taxon/1386/dataset_report":
            return self._send(200, json.dumps({"reports": [], "total_count": 5000}).encode())
        return self._send(404, b"{}")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        e = self._record(body)
        path = e["path"].removeprefix("/v2")
        if path == "/genome/download_summary":
            return self._send(200, (NCBI_FX / "download_summary.json").read_bytes())
        if path == "/genome/download":
            return self._send(200, StandIn.package_override or package(e["body"]["accessions"]), "application/zip")
        return self._send(404, b"{}")


def package(accessions: list[str], drop: str | None = None, corrupt: str | None = None) -> bytes:
    """A genome data package laid out as NCBI's (README.md, md5sum.txt, ncbi_dataset/data/...), with the real
    metadata of the recorded report pages and SYNTHETIC sequences in place of the genomes (a test construct)."""
    reports = {r["accession"]: r for f in ("report_page1.json", "report_page2.json")
               for r in json.loads((NCBI_FX / f).read_text())["reports"]}
    files: dict[str, bytes] = {"README.md": b"# NCBI Datasets\n"}
    lines, catalog = [], [{"files": [{"filePath": "assembly_data_report.jsonl", "fileType": "DATA_REPORT"}]}]
    rng = random.Random(5)
    for acc in accessions:
        if acc == drop:
            continue
        r = reports[acc]
        org = r["organism"]
        lines.append(json.dumps({"accession": acc, "organism": {"organismName": org["organism_name"], "taxId": org[
            "tax_id"], "infraspecificNames": org.get("infraspecific_names", {})}, "typeMaterial": {
            "typeLabel": r["type_material"]["type_label"], "typeDisplayText": r["type_material"]["type_display_text"]},
            "assemblyInfo": {"refseqCategory": r["assembly_info"].get("refseq_category")}}))
        rel = f"{acc}/{acc}_SYNTHETIC_genomic.fna"
        files[f"ncbi_dataset/data/{rel}"] = (f">SYNTHETIC_{acc} test construct, not a genome\n"
                                             + "".join(rng.choice("ACGT") for _ in range(2000)) + "\n").encode()
        catalog.append({"accession": acc, "files": [{"filePath": rel, "fileType": "GENOMIC_NUCLEOTIDE_FASTA"}]})
    files["ncbi_dataset/data/assembly_data_report.jsonl"] = ("\n".join(lines) + "\n").encode()
    files["ncbi_dataset/data/dataset_catalog.json"] = json.dumps({"apiVersion": "V2", "assemblies": catalog}).encode()
    md5 = {k: hashlib.md5(v, usedforsecurity=False).hexdigest() for k, v in files.items() if k.startswith("ncbi")}
    if corrupt:
        md5[corrupt] = "0" * 32
    files["md5sum.txt"] = "".join(f"{v}  {k}\n" for k, v in md5.items()).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, (2026, 10, 29, 12, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, data)
    return out.getvalue()


@pytest.fixture
def stand_in(monkeypatch):
    StandIn.requests, StandIn.package_override = [], None
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "ncbi_datasets_url", f"http://127.0.0.1:{server.server_port}/v2")
    monkeypatch.setattr(ncbi, "MIN_INTERVAL_SECONDS", 0)
    yield StandIn
    server.shutdown()


def plan(client, taxon: str, **extra) -> dict:
    r = client.post(f"{API}/databases/ncbi/plan", json={"taxon": taxon, "filters": {"type_material": True}, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_ncbi_plan_shows_genomes_and_size_before_any_download(client, dbdir, stand_in):
    p = plan(client, "Staphylococcus argenteus")
    assert (p["status"], p["taxon"]["tax_id"], p["taxon"]["rank"], p["genomes"], p["total_count"]) == (
        "ready", 985002, "species", 4, 4)
    assert p["type_material"] == 4 and p["species"] == 1 and p["by_species"][0]["species"] == "Staphylococcus argenteus"
    assert p["download"]["estimated_mb"] == 3 and p["zip_estimate_bytes"] == 3_000_000 and p["enough"] is True
    assert p["fasta_estimate_bytes"] > 4 * 2_700_000 and p["folder"].startswith("reference-genomes/ncbi-staphylococcus")
    assert p["fingerprint"] == ncbi.fingerprint([g for g in ("GCF_000236925.1", "GCF_900457475.1", "GCF_014877305.1",
                                                              "GCF_002901785.1")])
    reports = [r for r in stand_in.requests if r["path"].endswith("dataset_report")]
    assert len(reports) == 2 and reports[1]["query"]["page_token"]
    assert reports[0]["query"]["filters.is_type_material"] == ["true"]
    assert reports[0]["query"]["filters.assembly_source"] == ["refseq"]
    assert not any(r["method"] == "POST" and r["path"].endswith("/genome/download") for r in stand_in.requests)
    sent = json.dumps(stand_in.requests).lower()
    assert "api_key" not in sent and "api-key" not in sent and "email" not in sent and "@" not in sent


def test_ncbi_plan_taxon_checks(client, dbdir, stand_in):
    p = plan(client, "Bacillus")
    assert p["status"] == "too_many" and p["taxon"]["tax_id"] == 1386 and p["total_count"] == 5000
    r = client.post(f"{API}/databases/ncbi/plan", json={"taxon": "Notagenusxyz"})
    assert (r.status_code, r.json()["code"]) == (400, "ncbi_taxon_unknown")
    r = client.post(f"{API}/databases/ncbi/plan", json={"taxon": "x; rm -rf /"})
    assert (r.status_code, r.json()["code"]) == (400, "ncbi_taxon_invalid")
    get_settings().ncbi_datasets_url = "http://example.org/v2"
    r = client.post(f"{API}/databases/ncbi/plan", json={"taxon": "Bacillus"})
    assert (r.status_code, r.json()["code"]) == (502, "ncbi_unreachable")


def test_ncbi_choose_between_bacterial_taxa(monkeypatch):
    monkeypatch.setattr(ncbi, "resolve_taxon", lambda text: [
        {"tax_id": 1, "name": "A", "rank": "genus", "bacterial": True},
        {"tax_id": 2, "name": "A", "rank": "genus", "bacterial": True}])
    p = ncbi.plan(None, "A", None, ncbi.Filters())
    assert p["status"] == "choose_taxon" and len(p["candidates"]) == 2


def test_ncbi_download_after_confirmation_installs_a_checked_collection(client, dbdir, stand_in, held_queue):
    p = plan(client, "Staphylococcus argenteus")
    body = {"taxon": "Staphylococcus argenteus", "tax_id": 985002, "filters": {"type_material": True}}
    r = client.post(f"{API}/databases/ncbi", json={**body, "confirm_genomes": 3, "confirm_fingerprint": p["fingerprint"]})
    assert (r.status_code, r.json()["code"]) == (400, "ncbi_list_changed")
    r = client.post(f"{API}/databases/ncbi", json={**body, "confirm_genomes": 4, "confirm_fingerprint": p["fingerprint"]})
    assert r.status_code == 202, r.text
    record = r.json()
    assert record["status"] == "downloading" and record["kind"] == "reference_genomes"
    assert run_ncbi_collection(record["id"]) == "installed"
    with SessionLocal() as s:
        db = s.get(ReferenceDatabase, record["id"])
        assert db.version.startswith("NCBI Datasets ") and db.version_source.value == "download"
        assert db.verification_level == "full" and len(db.inventory) == 4
        assert all(g["type_label"] == "TYPE_MATERIAL" and g["species"] == "Staphylococcus argenteus"
                   for g in db.inventory)
        assert db.details["published_md5_checked"] == 6 and db.details["ncbi"]["taxon"]["tax_id"] == 985002
        assert not (dbdir / ".arva-downloads" / record["id"]).exists()
        path = Path(db.path)
    assert (path / "md5sum.txt").is_file() and path.is_relative_to(dbdir)
    download = next(x for x in stand_in.requests if x["path"].endswith("/genome/download"))
    assert download["body"] == {"accessions": ["GCF_000236925.1", "GCF_900457475.1", "GCF_014877305.1",
                                               "GCF_002901785.1"], "include_annotation_type": ["GENOME_FASTA"]}


@pytest.mark.parametrize(("drop", "corrupt", "code"), [
    ("GCF_014877305.1", None, "ncbi_package_incomplete"),
    (None, "ncbi_dataset/data/assembly_data_report.jsonl", "published_mismatch"),
])
def test_ncbi_download_refuses_an_incomplete_or_damaged_package(client, dbdir, stand_in, held_queue, drop, corrupt,
                                                                code):
    p = plan(client, "Staphylococcus argenteus")
    accessions = ["GCF_000236925.1", "GCF_900457475.1", "GCF_014877305.1", "GCF_002901785.1"]
    stand_in.package_override = package(accessions, drop=drop, corrupt=corrupt)
    r = client.post(f"{API}/databases/ncbi", json={"taxon": "Staphylococcus argenteus", "tax_id": 985002,
                                                   "filters": {"type_material": True}, "confirm_genomes": 4,
                                                   "confirm_fingerprint": p["fingerprint"]})
    assert run_ncbi_collection(r.json()["id"]) == "failed"
    with SessionLocal() as s:
        db = s.get(ReferenceDatabase, r.json()["id"])
        assert db.status is DatabaseStatus.failed and db.error_detail["code"] == code
        assert not Path(db.path).exists()


def test_every_species_and_ncbi_code_has_both_languages():
    from test_database_kinds import _dictionaries

    from app.api.routes import species as routes
    from app.services import species as species_svc

    en, es = _dictionaries()
    keys = [f"api.error.{c}" for c in {**ncbi.MESSAGES, **routes.MESSAGES}]
    keys += [f"species.warning.{c}" for c in species_svc.WARNINGS]
    keys += [f"species.reason.{c}" for c in species_svc.REASON_TEXT] + [f"species.caveat.{c}" for c in species_svc.CAVEAT_TEXT]
    keys += [f"species.status.{c}" for c in species_svc.STATUS_TEXT]
    assert [k for k in keys if k not in en or k not in es] == []
    assert {k: v for k, v in ncbi.MESSAGES.items() if en[f"api.error.{k}"] != v} == {}
