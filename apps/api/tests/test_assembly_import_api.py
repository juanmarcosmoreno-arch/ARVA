"""A finished genome FASTA registered as an imported assembly (e.g. an NCBI RefSeq genome), and the Flye guard
against a filtered file selected together with the file it was filtered from."""
import gzip

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
