"""Sanger reads of one gene through the API: import of .ab1, FASTA and .seq files (validation, duplicates, direction
and pairs from the names, manual override), trimming and chromatogram views, the forward + reverse consensus and
its conflicts, identifications and the suspicion, the search plan and its refusals, real searches with BLAST+
(NCBI 16S, a genome in ARVA named by its annotation) and the report in both languages.

Reads: Biopython 1.88's public test chromatograms (scientific-core/tests/fixtures/sanger/README.md). The reverse
read of the pair is built in the test from 3100.ab1's own base calls (a reverse-complemented slice with two
substitutions), as a FASTA without qualities. NCBI's 16S database is read from ARVA_TEST_16S_DB (default
/root/.arva-testdata/ncbi-16s/2026-10-29) and those tests skip without it; no user read is used anywhere.
"""
import csv
import io
import os
import shutil
from pathlib import Path

import pytest
from arva_core import sanger as core
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import GENOME, assemble
from test_comparative_api import project_sample
from test_regions_api import annotate

from app.db.session import SessionLocal
from app.models import AnalysisJob, JobStatus, SangerRead, SangerSearchResult
from app.services import sanger as svc

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
FX = REPO / "scientific-core" / "tests" / "fixtures" / "sanger"
DB16S = Path(os.environ.get("ARVA_TEST_16S_DB", "/root/.arva-testdata/ncbi-16s/2026-10-29"))


def upload(client, sample: dict, *files: tuple[str, bytes]):
    return client.post(f"{API}/samples/{sample['id']}/sanger/reads",
                       files=[("files", (name, data, "application/octet-stream")) for name, data in files])


def ab1(name: str) -> bytes:
    return (FX / name).read_bytes()


def reverse_fasta(start: int = 200, end: int = 697, substitutions=(300, 450)) -> tuple[str, str]:
    """A reverse read built from 3100.ab1's base calls: bases start-end (1-based), the given positions changed to
    another base, reverse-complemented; returned with the forward bases it covers."""
    calls = core.read_abi(FX / "3100.ab1").bases
    piece = list(calls[start - 1:end])
    for pos in substitutions:
        i = pos - start
        piece[i] = {"A": "C", "C": "G", "G": "T", "T": "A"}.get(piece[i], "A")
    return core.reverse_complement(core.SangerRead("r", "".join(piece), "fasta")).bases, calls


def need(tool_id: str) -> None:
    registry._CACHE.pop(tool_id, None)
    if detect(tool_id, refresh=True).status.value != "available":
        pytest.skip(f"{tool_id} is not available")


@pytest.fixture(autouse=True)
def empty_database_folder(storage_root):
    yield
    shutil.rmtree(storage_root / "databases", ignore_errors=True)


@pytest.fixture
def sample(client):
    return project_sample(client, "Sanger project", "STRAIN-27")


# --- Names and pairs ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("57bbff46-1-27_784-F.ab1", ("forward", "784", "1-27")),
    ("893888f6-1-27_1401-R.ab1", ("reverse", "1401", "1-27")),
    ("27_784F.ab1", ("forward", "784F", "27")),
    ("A_1492R.seq", ("reverse", "1492R", "A")),
    ("iso5_icaA-Fwd.fasta", ("forward", None, "iso5_icaA")),
    ("3100.ab1", ("unknown", None, None)),
])
def test_direction_primer_and_pair_key_from_the_name(name, expected):
    p = svc.parse_read_name(name)
    assert (p["direction"], p["primer"], p["pair_key"]) == expected


def test_import_validation_duplicates_pairs_and_manual_override(client, sample, storage_root):
    rev, _calls = reverse_fasta()
    fasta = f">S2_1387-F\n{core.read_abi(FX / '3100.ab1').bases[18:697]}\n>S2_27-R\n{rev}\n".encode()
    r = upload(client, sample, ("3100.ab1", ab1("3100.ab1")), ("310.ab1", ab1("310.ab1")),
               ("fake.ab1", ab1("fake.ab1")), ("pair.fasta", fasta), ("empty.seq", b""),
               ("notes.docx", b"PK\x03\x04 not a read"), ("plain.seq", b"ACGTACGTAC\nGTACGT\n"))
    assert r.status_code == 201, r.text
    body = r.json()
    names = sorted(x["name"] for x in body["imported"])
    assert names == ["310", "3100", "S2_1387-F", "S2_27-R", "plain"]
    codes = {x["file"]: x["code"] for x in body["skipped"]}
    assert codes == {"fake.ab1": "sanger_unreadable", "empty.seq": "sanger_file_empty",
                     "notes.docx": "sanger_unknown_format"}
    by = {x["name"]: x for x in body["imported"]}
    assert by["3100"]["file_format"] == "abi" and by["3100"]["has_qualities"] and by["3100"]["has_trace"]
    assert by["3100"]["summary"]["sample"] == "16S_S2_1387R" and by["3100"]["length"] == 795
    assert by["3100"]["summary"]["default_trim"]["start"] == 19 and by["3100"]["summary"]["default_trim"]["end"] == 697
    assert by["310"]["has_trace"] and not by["310"]["has_qualities"]
    assert {"code": "no_qualities", "params": {}} in by["310"]["summary"]["warnings"]
    assert by["S2_1387-F"]["record_index"] == 0 and by["S2_27-R"]["record_index"] == 1
    assert by["S2_1387-F"]["sha256"] == by["S2_27-R"]["sha256"] and by["plain"]["file_format"] == "seq"
    assert body["pairs"] == [{"pair_key": "S2", "status": "proposed", "forward_read_id": by["S2_1387-F"]["id"],
                              "reverse_read_id": by["S2_27-R"]["id"]}]
    # The file is kept unchanged in raw/.
    with SessionLocal() as db:
        stored = storage_root / db.get(SangerRead, by["3100"]["id"]).storage_path
    assert stored.read_bytes() == ab1("3100.ab1") and "/sanger/" in str(stored)
    assert client.get(f"{API}/sanger/reads/{by['3100']['id']}/file").content == ab1("3100.ab1")
    again = upload(client, sample, ("copy.ab1", ab1("3100.ab1"))).json()
    assert again["imported"] == [] and again["skipped"][0]["code"] == "sanger_duplicate"
    # The user's own direction and pair key replace the proposals.
    u = client.patch(f"{API}/sanger/reads/{by['3100']['id']}", json={"direction": "forward", "pair_key": "S2"}).json()
    assert (u["direction"], u["direction_source"], u["pair_key"]) == ("forward", "user", "S2")
    overview = client.get(f"{API}/samples/{sample['id']}/sanger").json()
    assert overview["pairs"][0]["status"] == "ambiguous" and len(overview["reads"]) == 5
    assert client.patch(f"{API}/sanger/reads/{by['3100']['id']}", json={"direction": "sideways"}).status_code == 422
    assert client.delete(f"{API}/sanger/reads/{by['plain']['id']}").status_code == 204
    assert client.get(f"{API}/sanger/reads/{by['plain']['id']}").status_code == 404


def test_read_detail_trimming_and_chromatogram(client, sample):
    rid = upload(client, sample, ("3100.ab1", ab1("3100.ab1"))).json()["imported"][0]["id"]
    d = client.get(f"{API}/sanger/reads/{rid}").json()
    assert (d["trim"]["start"], d["trim"]["end"], d["trim"]["limit"]) == (19, 697, 0.05)
    assert len(d["kept_bases"]) == 679 and len(d["qualities"]) == 795 and "Mott" in d["trim_source"]
    assert all(m["position"] in range(1, 796) for m in d["mixed_peaks"])
    manual = client.get(f"{API}/sanger/reads/{rid}", params={"manual_start": 30, "manual_end": 600}).json()
    assert manual["trim"]["method"] == "manual" and manual["trim"]["length"] == 571
    bad = client.get(f"{API}/sanger/reads/{rid}", params={"manual_start": 700, "manual_end": 900})
    assert bad.status_code == 400 and bad.json()["code"] == "sanger_trim_invalid"
    t = client.get(f"{API}/sanger/reads/{rid}/trace", params={"scan_start": 0, "scan_end": 2000,
                                                                 "max_points": 500}).json()
    assert set(t["channels"]) == set("ACGT") and len(t["channels"]["A"]) <= 500 and t["markers"]
    fasta_id = upload(client, sample, ("x.fasta", b">x\nACGTACGTACGTACGTACGTACGTACGTACGTAC\n")).json()["imported"][0]["id"]
    assert client.get(f"{API}/sanger/reads/{fasta_id}/trace").json()["code"] == "sanger_no_trace"


def test_consensus_preview_identification_and_suspicion(client, sample):
    rev, _calls = reverse_fasta()
    reads = upload(client, sample, ("3100.ab1", ab1("3100.ab1")),
                   ("S2-R.fasta", f">S2-R\n{rev}\n".encode())).json()["imported"]
    fwd = next(r for r in reads if r["file_format"] == "abi")["id"]
    rvs = next(r for r in reads if r["file_format"] == "fasta")["id"]
    payload = {"forward_read_id": fwd, "reverse_read_id": rvs}
    p = client.post(f"{API}/samples/{sample['id']}/sanger/consensus/preview", json=payload).json()
    assert p["mode"] == "pair" and p["status"] == "ok"
    assert p["overlap"]["columns"] == 498 and p["overlap"]["mismatches"] == 2 and p["overlap"]["gaps"] == 0
    conflicts = {c["forward"]["origin"]: c for c in p["conflicts"]}
    assert set(conflicts) == {300, 450}
    # The reverse read has no qualities: nothing is resolved by quality, the column gets the IUPAC code of both.
    for c in conflicts.values():
        assert c["status"] == "unresolved" and c["rule"] == "no_qualities"
        assert c["base"] == core.IUPAC_PAIR[frozenset((c["forward"]["base"], c["reverse"]["base"]))]
    assert p["length"] == 679 and {"code": "conflicts_without_qualities", "params": {}} in p["warnings"]
    # Saving it: the consensus and every column's evidence are kept; the suspicion can change later.
    ident = client.post(f"{API}/samples/{sample['id']}/sanger/identifications",
                        json={**payload, "label": "strain 27 16S", "suspected": {"kind": "species",
                                                                                  "value": "Staphylococcus"}})
    assert ident.status_code == 201, ident.text
    i = ident.json()["identification"]
    assert i["mode"] == "pair" and i["length"] == 679 and i["unresolved"] == 2 and i["suspected"]["kind"] == "species"
    assert ident.json()["suspected"]["outcome"] == "no_match"  # nothing searched yet
    assert ident.json()["suspected"]["reasons"][0]["code"] == "not_found"
    single = client.post(f"{API}/samples/{sample['id']}/sanger/identifications",
                         json={"reverse_read_id": rvs}).json()["identification"]
    assert single["mode"] == "single" and single["reverse_read_id"] == rvs and single["forward_read_id"] is None
    assert client.delete(f"{API}/sanger/reads/{rvs}").json()["code"] == "sanger_read_in_use"
    upd = client.patch(f"{API}/sanger/identifications/{i['id']}", json={"suspected": {"kind": "gene",
                                                                                         "value": "16S"}}).json()
    assert upd["identification"]["suspected"] == {"kind": "gene", "value": "16S"}
    fasta = client.get(f"{API}/sanger/identifications/{i['id']}/consensus.fasta").text
    assert fasta.startswith(">strain_27_16S pair length=679") and "".join(fasta.splitlines()[1:]) == \
        client.get(f"{API}/sanger/identifications/{i['id']}").json()["identification"]["sequence"]


def test_refusals(client, sample):
    other = project_sample(client, "Other project", "OTHER")
    rid = upload(client, other, ("3100.ab1", ab1("3100.ab1"))).json()["imported"][0]["id"]
    base = f"{API}/samples/{sample['id']}/sanger"
    assert client.post(f"{base}/consensus/preview", json={}).json()["code"] == "sanger_reads_needed"
    assert client.post(f"{base}/consensus/preview", json={"forward_read_id": rid}).json()["code"] == \
        "sanger_read_missing"
    mine = upload(client, sample, ("3100.ab1", ab1("3100.ab1")),
                  ("short.fasta", b">far-R\nTTTTTTTTTTGGGGGGGGGGCCCCCCCCCCAAAAAAAAAATTTTTTTTTT\n")).json()["imported"]
    fwd = next(r for r in mine if r["file_format"] == "abi")["id"]
    rev = next(r for r in mine if r["file_format"] == "fasta")["id"]
    assert client.post(f"{base}/consensus/preview", json={"forward_read_id": fwd, "reverse_read_id": fwd}).json()[
        "code"] == "sanger_same_read"
    r = client.post(f"{base}/identifications", json={"forward_read_id": fwd, "reverse_read_id": rev})
    assert r.status_code == 400 and r.json()["code"] == "sanger_no_overlap"
    bad = client.post(f"{base}/consensus/preview", json={"forward_read_id": fwd, "consensus": {"match": -1}})
    assert bad.json()["code"] == "sanger_consensus_invalid"
    ident = client.post(f"{base}/identifications", json={"forward_read_id": fwd}).json()["identification"]
    search = f"{API}/sanger/identifications/{ident['id']}/search"
    assert client.post(search, json={"sources": ["ncbi_16s"]}).json()["code"] == "sanger_confirm"
    plan = client.post(f"{search}/preview", json={"sources": ["genomes", "spa"]}).json()
    assert {p["source"]: p["problems"][0]["code"] for p in plan["sources"] if p["problems"]}["genomes"] == "no_genomes"
    assert plan["blocked"] and client.post(search, json={"sources": ["genomes"], "confirmed": True}).json()[
        "code"] == "sanger_search_blocked"
    assert client.post(f"{search}/preview", json={"sources": ["nr"]}).status_code == 422


# --- Real searches ------------------------------------------------------------------------------------------------

@pytest.fixture
def ncbi_16s(client, storage_root):
    if not (DB16S / "16S_ribosomal_RNA.nsq").is_file():
        pytest.skip(f"NCBI's 16S database is not at {DB16S} (ARVA_TEST_16S_DB)")
    need("blast")
    target = storage_root.resolve() / "databases" / "ncbi-16s" / DB16S.name
    if not target.exists():
        target.mkdir(parents=True)
        for f in DB16S.iterdir():
            if f.name.startswith("16S_ribosomal_RNA"):
                shutil.copy(f, target / f.name)
    r = client.post(f"{API}/databases/register", json={"path": str(target)})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_16s_kind_is_recognised_registered_and_compatible(ncbi_16s):
    assert ncbi_16s["kind"] == "ncbi_16s" and ncbi_16s["version"] == "2026-10-29"
    assert ncbi_16s["version_source"] == "file" and ncbi_16s["is_default"]
    assert ncbi_16s["compatibility"]["code"] == "blastdb_read"


def test_16s_search_of_a_public_read_names_the_genus_not_the_species(client, sample, ncbi_16s):
    rid = upload(client, sample, ("3100.ab1", ab1("3100.ab1"))).json()["imported"][0]["id"]
    ident = client.post(f"{API}/samples/{sample['id']}/sanger/identifications",
                        json={"forward_read_id": rid, "suspected": {"kind": "species",
                                                                    "value": "Staphylococcus epidermidis"}}).json()
    iid = ident["identification"]["id"]
    plan = client.post(f"{API}/sanger/identifications/{iid}/search/preview", json={"sources": ["ncbi_16s"]}).json()
    (p,) = plan["sources"]
    assert p["problems"] == [] and p["database"]["id"] == ncbi_16s["id"] and p["settings"]["task"] == "megablast"
    jobs = client.post(f"{API}/sanger/identifications/{iid}/search", json={"sources": ["ncbi_16s"],
                                                                         "confirmed": True})
    assert jobs.status_code == 202, jobs.text
    (job,) = jobs.json()
    with SessionLocal() as db:
        j = db.get(AnalysisJob, job["id"])
        assert j.status is JobStatus.completed, j.log_text
        assert (j.database_kind, j.database_version, j.reference_database_id) == ("ncbi_16s", "2026-10-29",
                                                                                   ncbi_16s["id"])
        assert any("-db" in c and "megablast" in c for c in j.commands)
    out = client.get(f"{API}/sanger/identifications/{iid}").json()
    best = out["ranked"][0]
    assert best["species"] == "Staphylococcus epidermidis" and best["accession"] == "NR_036904.1"
    assert round(best["identity"], 3) == 99.853 and best["query_coverage"] == 100
    reading = out["interpretation_16s"]
    assert reading["level"] == "genus" and reading["genus"] == "Staphylococcus"
    assert {r["code"] for r in reading["reasons"]} == {"species_not_separated"}
    assert "staphylococcus_16s_limit" in {c["code"] for c in reading["caveats"]}
    # The suspected species is the best hit, but other species are within 0.8 points: ambiguous, never "match".
    assert out["suspected"]["outcome"] == "ambiguous" and out["suspected"]["tied_other_count"] >= 1
    genus = client.patch(f"{API}/sanger/identifications/{iid}",
                         json={"suspected": {"kind": "species", "value": "Staphylococcus"}}).json()
    assert genus["suspected"]["outcome"] == "match"
    wrong = client.patch(f"{API}/sanger/identifications/{iid}",
                         json={"suspected": {"kind": "species", "value": "Escherichia coli"}}).json()
    assert wrong["suspected"]["outcome"] == "no_match"
    # Reports: HTML in both languages, CSV of the ranked hits, JSON with the database provenance.
    base = f"{API}/sanger/identifications/{iid}/report"
    en = client.get(base, params={"format": "html", "lang": "en"}).text
    es = client.get(base, params={"format": "html", "lang": "es"}).text
    assert 'lang="en"' in en and "Sanger identification" in en and "genus only" in en and "NR_036904.1" in en
    assert 'lang="es"' in es and "Identificación Sanger" in es and "solo género" in es and "Limitaciones" in es
    assert "Staphylococcus" in es and "16S_ribosomal_RNA" not in es.split("<h2>")[0]
    rows = list(csv.DictReader(io.StringIO(client.get(base, params={"format": "csv"}).text)))
    assert rows[0]["database_version"] == "2026-10-29" and rows[0]["source"] == "ncbi_16s"
    data = client.get(base, params={"format": "json"}).json()
    assert data["searches"][0]["database_version"] == "2026-10-29" and data["report"] == "sanger_identification"
    # The database is in use while the search runs, and the identification cannot be deleted then; afterwards it can.
    assert client.delete(f"{API}/sanger/identifications/{iid}").status_code == 204
    with SessionLocal() as db:
        assert db.get(AnalysisJob, job["id"]) is not None
        assert db.query(SangerSearchResult).count() == 0


def test_genome_of_the_same_strain_names_the_hit_by_its_annotation(client, sample, storage_root):
    need("blast")
    a = assemble(client, sample, GENOME)
    ann = annotate(storage_root, sample, a)
    feat = next(f for f in client.get(f"{API}/annotations/{ann}/features", params={"limit": 500}).json()["items"]
                if f["type"] == "cds" and f.get("gene") and f["end"] - f["start"] > 600)
    seqs, name = {}, None
    for line in GENOME.read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            seqs[name] = []
        else:
            seqs[name].append(line.strip())
    contig = "".join(seqs[feat["contig_in_assembly"]])
    amplicon = contig[feat["start"] + 49:feat["end"] - 50]
    rid = upload(client, sample, ("amplicon.fasta", f">{feat['gene']}_amplicon\n{amplicon}\n".encode())).json()[
        "imported"][0]["id"]
    ident = client.post(f"{API}/samples/{sample['id']}/sanger/identifications",
                        json={"forward_read_id": rid, "suspected": {"kind": "gene", "value": feat["gene"]}}).json()
    iid = ident["identification"]["id"]
    plan = client.post(f"{API}/sanger/identifications/{iid}/search/preview", json={"sources": ["genomes"]}).json()
    (g,) = plan["sources"][0]["genomes"]
    assert g["assembly_id"] == a["id"] and g["own_sample"] and g["annotation"]["annotation_id"] == ann
    (job,) = client.post(f"{API}/sanger/identifications/{iid}/search",
                         json={"sources": ["genomes"], "confirmed": True}).json()
    with SessionLocal() as db:
        j = db.get(AnalysisJob, job["id"])
        assert j.status is JobStatus.completed, j.log_text
        assert j.database_kind is None and j.parameters["genomes"][0]["contigs_sha256"] == g["contigs_sha256"]
    out = client.get(f"{API}/sanger/identifications/{iid}").json()
    best = out["ranked"][0]
    assert best["identity"] == 100 and best["query_coverage"] == 100 and best["subject"] == feat["contig_in_assembly"]
    assert best["gene"] == feat["gene"] and best["features"][0]["locus_tag"] == feat["locus_tag"]
    assert best["features"][0]["hit_inside"] == 100
    assert out["suspected"]["outcome"] in ("match", "ambiguous")
    assert out["suspected"]["best_suspected"]["gene"] == feat["gene"]


def test_sanger_migration_up_and_down(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.core.config import get_settings
    from app.db.session import engine

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch_sanger")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_sanger"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch_sanger"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    try:
        command.upgrade(cfg, "head")
        with db.begin() as c:
            fks = dict(c.execute(text("SELECT conname, confdeltype FROM pg_constraint WHERE contype = 'f' AND "
                                      "conrelid::regclass::text LIKE 'sanger_%'")).all())
            assert fks == {"fk_sanger_reads_sample_id": "c", "fk_sanger_identifications_sample_id": "c",
                           "fk_sanger_identifications_forward_read_id": "a",
                           "fk_sanger_identifications_reverse_read_id": "a",
                           "fk_sanger_search_results_identification_id": "c", "fk_sanger_search_results_job_id": "c"}
        command.downgrade(cfg, "c4e8a2f6d0b1")
        with db.begin() as c:
            assert c.execute(text("SELECT to_regclass('sanger_reads')")).scalar() is None
        command.upgrade(cfg, "head")
        with db.begin() as c:
            c.execute(text("INSERT INTO projects (id, name, is_demo, created_at, updated_at) VALUES ('p', 'P', false, now(), now())"))
            c.execute(text("INSERT INTO samples (id, project_id, sample_code, sequencing_technology, created_at, "
                           "updated_at) VALUES ('s', 'p', 'S', 'unknown', now(), now())"))
            c.execute(text("INSERT INTO sanger_reads (id, sample_id, name, original_filename, file_format, "
                           "record_index, storage_path, sha256, size_bytes, direction, direction_source, length, "
                           "has_qualities, has_trace, summary, created_at, updated_at) VALUES ('r', 's', 'r', 'r.ab1', "
                           "'abi', 0, 'raw/x', 'h', 1, 'forward', 'name', 10, true, true, '{}', now(), now())"))
        with pytest.raises(RuntimeError, match="Sanger data exist"):
            command.downgrade(cfg, "c4e8a2f6d0b1")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_sanger"))


# --- The other sources, with the real tools where they are installed ---------------------------------------------

CONDA = Path.home() / ".arva-tools" / "conda"
SEH = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "region" / "seh_MW2_nucleotide.fna"
AMR_CDS = Path(__file__).parent / "fixtures" / "amrfinder_release" / "2026-08-07.1" / "AMR_CDS.fa"


def _identify(client, sample, name: str, seq: str, suspected: dict | None = None) -> str:
    rid = upload(client, sample, (f"{name}.fasta", f">{name}\n{seq}\n".encode())).json()["imported"][0]["id"]
    body = {"forward_read_id": rid, **({"suspected": suspected} if suspected else {})}
    return client.post(f"{API}/samples/{sample['id']}/sanger/identifications", json=body).json()["identification"]["id"]


def _search(client, iid: str, source: str, **extra) -> dict:
    jobs = client.post(f"{API}/sanger/identifications/{iid}/search",
                       json={"sources": [source], "confirmed": True, **extra})
    assert jobs.status_code == 202, jobs.text
    with SessionLocal() as db:
        j = db.get(AnalysisJob, jobs.json()[0]["id"])
        assert j.status is JobStatus.completed, j.log_text
    return client.get(f"{API}/sanger/identifications/{iid}").json()


def _fasta_records(path: Path) -> dict[str, str]:
    out, name = {}, None
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            out[name] = ""
        elif name:
            out[name] += line.strip()
    return out


@pytest.fixture
def mobile_abricate_real(monkeypatch):
    exe = CONDA / "abricate" / "bin" / "abricate"
    if not exe.is_file():
        pytest.skip("ABRicate's environment is not installed")
    monkeypatch.setenv("ARVA_TOOL_ABRICATE", str(exe))
    registry._CACHE.pop("abricate", None)
    need("blast")
    return exe


@pytest.fixture
def real_mlst(monkeypatch):
    exe = CONDA / "mlst" / "bin" / "mlst"
    if not exe.is_file():
        pytest.skip("mlst's environment is not installed")
    monkeypatch.setenv("ARVA_TOOL_MLST", str(exe))
    registry._CACHE.pop("mlst", None)
    need("blast")
    return exe


def test_vfdb_names_an_enterotoxin_gene(client, sample, mobile_abricate_real):
    (seq,) = _fasta_records(SEH).values()
    iid = _identify(client, sample, "seh_amplicon", seq[50:650], {"kind": "gene", "value": "seh"})
    plan = client.post(f"{API}/sanger/identifications/{iid}/search/preview", json={"sources": ["vfdb"]}).json()
    (p,) = plan["sources"]
    assert p["problems"] == [] and p["database"]["bundled"] and p["settings"]["task"] == "blastn"
    out = _search(client, iid, "vfdb")
    best = out["ranked"][0]
    assert best["gene"] == "seh" and best["identity"] == 100 and best["query_coverage"] == 100
    assert round(best["subject_coverage"], 1) == round(100 * 600 / 726, 1)
    assert out["suspected"]["outcome"] == "match"
    assert out["searches"][0]["database_kind"] == "vfdb" and out["searches"][0]["database_checksum"]


def test_mlst_alleles_give_the_exact_allele(client, sample, real_mlst):
    from arva_tools import mlst as mlst_tool

    alleles = _fasta_records(mlst_tool.database_dir(str(real_mlst)) / "pubmlst" / "saureus" / "arcC.tfa")
    iid = _identify(client, sample, "arcC_amplicon", alleles["arcC_1"], {"kind": "gene", "value": "arcC"})
    out = _search(client, iid, "mlst")
    best = out["ranked"][0]
    assert (best["gene"], best["allele"], best["scheme"]) == ("arcC", "1", "saureus")
    assert best["identity"] == 100 and best["query_coverage"] == 100
    assert out["suspected"]["outcome"] in ("match", "ambiguous")


def test_amrfinderplus_translated_search_of_a_mecA_fragment(client, sample, storage_root):
    from test_amr_api import registered_release

    exe = CONDA / "amrfinderplus" / "bin" / "amrfinder"
    if not exe.is_file():
        pytest.skip("AMRFinderPlus's environment is not installed")
    os.environ["ARVA_TOOL_AMRFINDERPLUS"] = str(exe)
    registry._CACHE.pop("amrfinderplus", None)
    try:
        record = registered_release(client, storage_root, "amr-sanger", index=True)
        mec = next(s for n, s in _fasta_records(AMR_CDS).items() if "mecA" in n or n.startswith("mecA"))
        iid = _identify(client, sample, "mecA_amplicon", mec[:1500])
        out = _search(client, iid, "amrfinderplus", database_ids={"amrfinderplus": record["id"]})
        rows = out["by_source"]["amrfinderplus"]["rows"]
        assert [r["element_symbol"] for r in rows] == ["mecA"] and rows[0]["search"] == "translated"
        assert out["searches"][0]["database_version"] == "2026-08-07.1"
    finally:
        os.environ.pop("ARVA_TOOL_AMRFINDERPLUS", None)
        registry._CACHE.pop("amrfinderplus", None)


def test_reference_collection_rows_carry_the_genome_and_species(client, sample, storage_root):
    need("blast")
    genome = Path(os.environ.get("ARVA_TEST_GENOMES", "/root/.arva-testdata/genomes")) / "GCF_000011265.1.fna"
    if not genome.is_file():
        pytest.skip("MW2's genome is not cached")
    folder = storage_root.resolve() / "databases" / "collection-mw2"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(genome, folder / genome.name)
    r = client.post(f"{API}/databases/register", json={"path": str(folder), "collection_date": "2026-11-03"})
    assert r.status_code == 201, r.text
    rid = upload(client, sample, ("3100.ab1", ab1("3100.ab1"))).json()["imported"][0]["id"]
    iid = client.post(f"{API}/samples/{sample['id']}/sanger/identifications",
                      json={"forward_read_id": rid}).json()["identification"]["id"]
    out = _search(client, iid, "reference_genomes")
    rows = out["by_source"]["reference_genomes"]["rows"]
    assert rows and all(x["genome"] == "GCF_000011265.1" for x in rows)
    assert rows[0]["copies"] >= 5 and rows[0]["query_coverage"] > 99 and 98 < rows[0]["identity"] < 100
    assert out["by_source"]["reference_genomes"]["details"]["genomes_searched"] == 1


def test_spa_needs_the_users_ridom_files(client, sample):
    iid = _identify(client, sample, "spa_amplicon", "ACGT" * 40)
    plan = client.post(f"{API}/sanger/identifications/{iid}/search/preview", json={"sources": ["spa"]}).json()
    codes = [p["code"] for p in plan["sources"][0]["problems"]]
    assert "no_database" in codes


# --- Downloading NCBI's current 16S build -------------------------------------------------------------------------

@pytest.fixture
def ncbi_ftp(tmp_path, monkeypatch):
    """A local stand-in for NCBI's BLAST database folder: an archive made from the real 16S database files (with a
    constructed placeholder named like one of NCBI's taxonomy files, which must not be extracted), the real metadata
    file with its compressed size set to this archive's, and an MD5 file of this archive."""
    import gzip
    import hashlib
    import json
    import tarfile
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from app.core.config import get_settings

    if not (DB16S / "16S_ribosomal_RNA.nsq").is_file():
        pytest.skip(f"NCBI's 16S database is not at {DB16S} (ARVA_TEST_16S_DB)")
    need("blast")
    root = tmp_path / "ncbi"
    root.mkdir()
    placeholder = tmp_path / "taxdb.btd"
    placeholder.write_text("CONSTRUCTED placeholder: stands for NCBI's taxonomy file in the archive\n")
    archive = root / "16S_ribosomal_RNA.tar.gz"
    with gzip.open(archive, "wb", compresslevel=1) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for f in sorted(DB16S.glob("16S_ribosomal_RNA.n*")):
            tar.add(f, arcname=f.name)
        tar.add(placeholder, arcname="taxdb.btd")
    data = archive.read_bytes()
    meta = json.loads((DB16S / "16S_ribosomal_RNA-nucl-metadata.json").read_text())
    meta["bytes-total-compressed"] = len(data)
    (root / "16S_ribosomal_RNA-nucl-metadata.json").write_text(json.dumps(meta))
    md5 = hashlib.md5(data).hexdigest()
    (root / "16S_ribosomal_RNA.tar.gz.md5").write_text(f"{md5}  16S_ribosomal_RNA.tar.gz\n")

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "ncbi_blast_db_url", f"http://127.0.0.1:{server.server_port}")
    yield {"root": root, "bytes": len(data), "md5": md5}
    server.shutdown()
    server.server_close()


def test_current_16s_build_is_planned_confirmed_downloaded_and_checked(client, ncbi_ftp):
    plan = client.post(f"{API}/databases/ncbi-16s/plan", json={}).json()
    assert (plan["version"], plan["archive_bytes"], plan["md5"]) == ("2026-10-29", ncbi_ftp["bytes"], ncbi_ftp["md5"])
    assert plan["sequences"] == 27646 and plan["only_current"] and "taxdb.btd" not in plan["kept_files"]
    assert plan["enough"] and plan["blocked_by"] is None
    start = f"{API}/databases/ncbi-16s/download"
    wrong = client.post(start, json={"confirm_version": "2026-10-29", "confirm_bytes": 1, "accept_terms": True})
    assert wrong.status_code == 400 and wrong.json()["code"] == "ncbi16s_confirm"
    old = client.post(start, json={"confirm_version": "2026-01-01", "confirm_bytes": ncbi_ftp["bytes"],
                                   "accept_terms": True})
    assert old.json()["code"] == "ncbi16s_changed"
    r = client.post(start, json={"confirm_version": "2026-10-29", "confirm_bytes": ncbi_ftp["bytes"],
                                 "accept_terms": True})
    assert r.status_code == 202, r.text
    rec = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert rec["status"] == "installed", rec.get("error_message")
    assert (rec["kind"], rec["version"], rec["archive_checksum"]) == ("ncbi_16s", "2026-10-29",
                                                                      f"md5:{ncbi_ftp['md5']}")
    folder = Path(rec["path"])
    assert (folder / "16S_ribosomal_RNA.nsq").is_file() and (folder / "16S_ribosomal_RNA-nucl-metadata.json").is_file()
    assert not (folder / "taxdb.btd").exists() and rec["is_default"]
    again = client.post(f"{API}/databases/ncbi-16s/plan", json={}).json()
    assert again["blocked_code"] == "already_known"


def test_a_16s_archive_with_another_md5_is_not_installed(client, ncbi_ftp):
    (ncbi_ftp["root"] / "16S_ribosomal_RNA.tar.gz.md5").write_text("0" * 32 + "  16S_ribosomal_RNA.tar.gz\n")
    r = client.post(f"{API}/databases/ncbi-16s/download", json={"confirm_version": "2026-10-29",
                                                                 "confirm_bytes": ncbi_ftp["bytes"],
                                                                 "accept_terms": True})
    rec = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert rec["status"] == "failed" and rec["error_detail"]["code"] == "md5_mismatch"
    assert not Path(rec["path"]).exists()


def test_deleting_the_sample_removes_its_sanger_records_and_keeps_raw_files(client, sample, storage_root):
    reads = upload(client, sample, ("3100.ab1", ab1("3100.ab1"))).json()["imported"]
    client.post(f"{API}/samples/{sample['id']}/sanger/identifications", json={"forward_read_id": reads[0]["id"]})
    with SessionLocal() as db:
        stored = storage_root / db.get(SangerRead, reads[0]["id"]).storage_path
    assert client.delete(f"{API}/samples/{sample['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.get(SangerRead, reads[0]["id"]) is None
    assert stored.is_file()
