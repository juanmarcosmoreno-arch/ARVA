import gzip
import logging
from pathlib import Path

from sqlalchemy import text

from app.db.session import engine

API = "/api/v1"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
# fastcat test/fixtures/fastq/basic/bc2.fastq.gz (EPI2ME), read id varied per record
MINKNOW = ("@1d0fded8-95e7-4b53-858f-8391da5d65{i:02d} runid=5a21d8a6996146deceeaea3784244c52741cae93 read=13 "
           "ch=190 start_time=2021-04-20T17:00:40Z flow_cell_id=FAP67897 protocol_group_id=2021-04-20_UKBC "
           "sample_id={sample} barcode=barcode02 barcode_alias=barcode02")
# help.basespace.illumina.com fastq-files template, tile varied per record
ILLUMINA = "@SIM:1:FCX:1:{i}:6329:1045 {mate}:N:0:ATCACG"


def fastq(headers: list[str], seq: str = "ACGT") -> bytes:
    return "".join(f"{h}\n{seq}\n+\n{'I' * len(seq)}\n" for h in headers).encode()


def sample(client, technology="unknown", code="S1"):
    p = client.post(f"{API}/projects", json={"name": "Headers"}).json()
    body = {"sample_code": code, "sequencing_technology": technology}
    return client.post(f"{API}/projects/{p['id']}/samples", json=body).json()


def upload(client, sample_id, *files: tuple[str, bytes]):
    r = client.post(
        f"{API}/samples/{sample_id}/files",
        files=[("files", (name, content, "application/octet-stream")) for name, content in files],
    )
    assert r.status_code == 201, r.text
    return r.json()["files"]


def summary(client, sample_id):
    r = client.get(f"{API}/samples/{sample_id}/header-summary")
    assert r.status_code == 200, r.text
    return r.json()


def test_synthetic_files_are_honestly_not_inferable(client):
    s = sample(client)
    names = ["SYNTHETIC_illumina_R1_001.fastq.gz", "SYNTHETIC_illumina_R2_001.fastq.gz", "SYNTHETIC_nanopore_reads.fastq.gz"]
    files = upload(client, s["id"], *[(n, (EXAMPLES / n).read_bytes()) for n in names])
    r1, r2, ont = (f["header_metadata"] for f in files)
    assert r1["n_headers_read"] == 1000 and r1["format_counts"] == {"generic_slash_mate": 1000}
    assert r1["mate_layout"] == "mate_1_only" and r2["mate_layout"] == "mate_2_only"
    assert ont["format_counts"] == {"unrecognised": 400}
    for meta in (r1, r2, ont):
        assert meta["suggested_technology"]["value"] is None
        assert "mate_fingerprint" not in meta

    hs = summary(client, s["id"])
    assert hs["suggested_technology"] == {
        "value": None, "confidence": "none", "basis": "no_evidence", "platforms": [],
        "files_considered": 3, "files_with_evidence": 0,
    }
    assert [(f["name"], f["platform"], f["format"], f["analysed"]) for f in hs["per_file"]] == [
        (names[0], None, "generic_slash_mate", True),
        (names[1], None, "generic_slash_mate", True),
        (names[2], None, "unrecognised", True),
    ]
    assert hs["mate_check"] == [{
        "r1_file_id": files[0]["id"], "r2_file_id": files[1]["id"], "looks_like_pair": True,
        "matched": 200, "compared": 200, "note": "same_read_names",
    }]
    assert hs["user_technology"] == "unknown" and hs["agrees"] is None


def test_nanopore_headers_suggest_but_never_set_the_technology(client):
    s = sample(client)
    upload(client, s["id"], ("bc02.fastq.gz", gzip.compress(fastq([MINKNOW.format(i=i, sample="RNA_BA") for i in range(30)]))))
    hs = summary(client, s["id"])
    st = hs["suggested_technology"]
    assert (st["value"], st["confidence"], st["basis"]) == ("nanopore", "high", "single_platform")
    assert hs["per_file"][0]["format"] == "ont_minknow_kv" and hs["agrees"] is None
    assert client.get(f"{API}/samples/{s['id']}").json()["sequencing_technology"] == "unknown"

    meta = client.get(f"{API}/samples/{s['id']}/files").json()[0]["header_metadata"]
    assert meta["distinct"]["flowcell_id"] == {"values": ["FAP67897"], "n_distinct": 1, "truncated": False}
    assert meta["distinct"]["run_id"]["values"] == ["5a21d8a6996146deceeaea3784244c52741cae93"]
    assert meta["sources"]["ont_minknow_kv"][0].startswith("https://software-docs.nanoporetech.com/")

    client.patch(f"{API}/samples/{s['id']}", json={"sequencing_technology": "illumina"})
    hs = summary(client, s["id"])
    assert hs["user_technology"] == "illumina" and hs["agrees"] is False
    client.patch(f"{API}/samples/{s['id']}", json={"sequencing_technology": "nanopore"})
    assert summary(client, s["id"])["agrees"] is True


def test_illumina_and_nanopore_files_suggest_hybrid(client):
    s = sample(client, technology="hybrid")
    upload(
        client, s["id"],
        ("S1_R1_001.fastq", fastq([ILLUMINA.format(i=i, mate=1) for i in range(20)])),
        ("S1_R2_001.fastq", fastq([ILLUMINA.format(i=i, mate=2) for i in range(20)])),
        ("S1_ont.fastq", fastq([MINKNOW.format(i=i, sample="x") for i in range(20)])),
    )
    hs = summary(client, s["id"])
    st = hs["suggested_technology"]
    assert (st["value"], st["confidence"], st["platforms"]) == ("hybrid", "high", ["illumina", "nanopore"])
    assert hs["agrees"] is True
    assert hs["mate_check"][0]["note"] == "same_read_names" and hs["mate_check"][0]["compared"] == 20


def test_mismatched_mates_give_a_warning_note_only(client):
    s = sample(client)
    upload(
        client, s["id"],
        ("A_R1_001.fastq", fastq([ILLUMINA.format(i=i, mate=1) for i in range(10)])),
        ("A_R2_001.fastq", fastq([ILLUMINA.format(i=i + 100, mate=2) for i in range(10)])),
        ("B_R1.fastq", fastq([f"@read{i}/2" for i in range(10)])),
        ("B_R2.fastq", fastq([f"@read{i}/2" for i in range(10)], seq="GGCC")),
    )
    checks = summary(client, s["id"])["mate_check"]
    assert [(c["note"], c["looks_like_pair"], c["matched"], c["compared"]) for c in checks] == [
        ("different_read_names", False, 0, 10),
        ("mate_markers_conflict", False, 10, 10),
    ]
    assert all(f["is_valid"] for f in client.get(f"{API}/samples/{s['id']}/files").json())


def test_header_parsing_failure_never_fails_the_import(client, monkeypatch, caplog):
    def broken(_headers):
        raise RuntimeError("parser bug")

    monkeypatch.setattr("app.services.imports.summarise", broken)
    # alembic's fileConfig (run by the migration fixture) disables loggers that already existed
    monkeypatch.setattr(logging.getLogger("app.services.imports"), "disabled", False)
    s = sample(client)
    with caplog.at_level(logging.WARNING, logger="app.services.imports"):
        (f,) = upload(client, s["id"], ("reads.fastq", fastq(["@r1", "@r2"])))
    assert f["is_valid"] is True and f["header_metadata"] is None
    assert "Read headers could not be summarised" in caplog.text
    hs = summary(client, s["id"])
    assert hs["per_file"][0]["analysed"] is False and hs["suggested_technology"]["files_considered"] == 0


def test_statistics_job_backfills_missing_header_metadata(client):
    s = sample(client)
    (f,) = upload(client, s["id"], ("SYNTHETIC_illumina_R1_001.fastq.gz", (EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz").read_bytes()))
    with engine.begin() as conn:
        conn.execute(text("UPDATE raw_files SET header_metadata = NULL WHERE id = :id"), {"id": f["id"]})
    assert client.get(f"{API}/files/{f['id']}").json()["header_metadata"] is None
    assert summary(client, s["id"])["per_file"][0]["analysed"] is False

    (job,) = client.post(f"{API}/samples/{s['id']}/analyses/sequence-stats", json={}).json()
    detail = client.get(f"{API}/jobs/{job['id']}").json()
    assert detail["status"] == "completed", detail["log_text"]
    assert "Summarised the first 1,000 read headers" in detail["log_text"]
    meta = client.get(f"{API}/files/{f['id']}").json()["header_metadata"]
    assert meta["n_headers_read"] == 1000 and meta["mate_layout"] == "mate_1_only"


def test_reports_list_header_metadata_escaped(client):
    s = sample(client)
    evil = "<script>alert(1)</script>"
    upload(client, s["id"], ("ont.fastq", fastq([MINKNOW.format(i=i, sample=evil) for i in range(5)])))
    client.post(f"{API}/samples/{s['id']}/analyses/sequence-stats", json={})

    report = client.get(f"{API}/samples/{s['id']}/report", params={"format": "json"}).json()
    rh = report["files"][0]["read_headers"]
    assert (rh["header_format"], rh["platform"], rh["confidence"]) == ("ont_minknow_kv", "nanopore", "high")
    assert rh["distinct"]["sample_id"]["values"] == [evil] and "mate_fingerprint" not in rh
    assert report["read_header_summary"]["suggested_technology"]["value"] == "nanopore"

    html = client.get(f"{API}/samples/{s['id']}/report", params={"format": "html"}).text
    assert evil not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Platform hint" in html and "nanopore (high confidence)" in html
    assert "Suggested from read headers: nanopore" in html


def test_header_summary_of_unknown_sample_is_404(client):
    assert client.get(f"{API}/samples/missing/header-summary").status_code == 404


def test_mate_pairs_follow_file_names_with_a_lone_pair_fallback():
    from app.models import RawFile
    from app.services.read_headers import mate_pairs

    def f(name, mate):
        return RawFile(id=name, original_filename=name, read_mate=mate)

    lanes = [f("x_L001_R1_001.fastq.gz", "R1"), f("x_L002_R1_001.fastq.gz", "R1"),
             f("X_L002_r2_001.FASTQ.GZ", "R2"), f("x_L001_R2_001.fastq.gz", "R2")]
    assert [(a.id, b.id) for a, b in mate_pairs(lanes)] == [
        ("x_L001_R1_001.fastq.gz", "x_L001_R2_001.fastq.gz"),
        ("x_L002_R1_001.fastq.gz", "X_L002_r2_001.FASTQ.GZ"),
    ]
    lone = [f("reads_1.fq", "R1"), f("other_R2.fastq", "R2")]
    assert [(a.id, b.id) for a, b in mate_pairs(lone)] == [("reads_1.fq", "other_R2.fastq")]
    assert mate_pairs([f("a_R1.fastq", "R1"), f("b_R1.fastq", "R1"), f("c_R2.fastq", "R2")]) == []
