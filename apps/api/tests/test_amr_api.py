"""AMR detection with AMRFinderPlus: database releases (listing, plan, download from a local stand-in of NCBI's folder,
indexing with the real amrfinder_index), the copy inside a Bakta database, previews and the organism proposed from
the species identification, the recorded job, the results (rows, warnings, linked features), the project matrix and
CSV, the annotation track, reports, and the migration.

A stand-in amrfinder (AMRFinderPlus 4.2.7's real --help and organism list; its report is a constructed table on the
fixture genome) covers what needs no search. The real-tool tests (skipped without AMRFinderPlus) index the
constructed release in tests/fixtures/amrfinder_release (subsets of NCBI's release 2026-08-07.1) and search a test
input made of three of its CDS, and ARVA's SYNTHETIC genome (nothing found).
"""
import hashlib
import os
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from arva_tools import registry
from arva_tools.registry import detect
from test_annotation_api import assemble, new_sample

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    AmrResult,
    AnalysisJob,
    Annotation,
    DatabaseOrigin,
    DatabaseStatus,
    JobStatus,
    ReferenceDatabase,
    SpeciesResult,
)

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
ADAPTER_FIXTURES = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures"
HELP = ADAPTER_FIXTURES / "amrfinderplus" / "help_4.2.7.txt"
ORGANISMS = ADAPTER_FIXTURES / "amrfinderplus" / "list_organisms_2026-08-07.1.txt"
GENOME = ADAPTER_FIXTURES / "annotation_genome" / "genome.fna"
RELEASE = Path(__file__).parent / "fixtures" / "amrfinder_release" / "2026-08-07.1"
SYNTHETIC = REPO / "examples" / "synthetic-genome" / "reference.fasta"
REAL_AMR = os.environ.get("ARVA_TOOL_AMRFINDERPLUS")
CHROM = "SYNTHETIC_annotation_chromosome"
HEADER = ("Protein id\tContig id\tStart\tStop\tStrand\tElement symbol\tElement name\tScope\tType\tSubtype\tClass\t"
          "Subclass\tMethod\tTarget length\tReference sequence length\t% Coverage of reference\t% Identity to reference\t"
          "Alignment length\tClosest reference accession\tClosest reference name\tHMM accession\tHMM description\t"
          "Hierarchy node")


def report(protein: bool) -> str:
    """A constructed AMRFinderPlus report on the fixture genome (values in the formats of real reports)."""
    pid = "SYNT_00002" if protein else "NA"
    rows = [
        [pid, CHROM, "1800", "2339", "+", "blaZ", "penicillin-hydrolyzing class A beta-lactamase BlaZ", "core", "AMR",
         "AMR", "BETA-LACTAM", "BETA-LACTAM", "EXACTP" if protein else "EXACTX", "179", "281", "100.00", "100.00", "179",
         "WP_000733285.1", "penicillin-hydrolyzing class A beta-lactamase BlaZ", "NA", "NA", "blaZ"],
        ["NA", CHROM, "2619", "2936", "-", "sasG", "LPXTG-anchored surface protein SasG", "plus", "VIRULENCE",
         "VIRULENCE", "NA", "NA", "PARTIAL_CONTIG_ENDX", "105", "1115", "9.42", "99.85", "105", "BAF79363.1",
         "LPXTG-anchored surface protein SasG", "NA", "NA", "sasG"],
        ["NA", CHROM, "5001", "6000", "+", "gyrA_S84L", "Staphylococcus aureus quinolone resistant GyrA", "core", "AMR",
         "POINT", "QUINOLONE", "QUINOLONE", "POINTX", "887", "887", "100.00", "99.66", "887", "WP_000819084.1",
         "DNA gyrase subunit A GyrA", "NA", "NA", "gyrA"],
    ]
    return HEADER + "\n" + "".join("\t".join(r) + "\n" for r in rows)


@pytest.fixture
def fake_amr(tmp_path, monkeypatch):
    """amrfinder's real --help, version and organism list; a run writes the constructed report."""
    env = tmp_path / "env" / "bin"
    env.mkdir(parents=True)
    (tmp_path / "nuc.tsv").write_text(report(False))
    (tmp_path / "prot.tsv").write_text(report(True))
    (tmp_path / "mutation_all.tsv").write_text(HEADER + "\n")
    script = f'''#!/bin/sh
case "$1" in --version) echo "4.2.7"; exit 0;; --help) cat "{HELP}"; exit 0;; esac
db=""; out=""; mut=""; nuc_out=""; prot=""
while [ $# -gt 0 ]; do
  case "$1" in
    --database) db="$2"; shift;; --output) out="$2"; shift;; --mutation_all) mut="$2"; shift;;
    --nucleotide_output) nuc_out="$2"; shift;; --protein) prot="$2"; shift;;
    --database_version) echo "Software version: 4.2.7" >&2; echo "Database version: $(cat "$db/version.txt")"; exit 0;;
    --list_organisms) cat "{ORGANISMS}"; exit 0;;
  esac
  shift
done
echo "Software version: 4.2.7" >&2; echo "Database version: $(cat "$db/version.txt")" >&2
echo "AMRFinder translated nucleotide and mutation search" >&2
if [ -n "$prot" ]; then cp "{tmp_path}/prot.tsv" "$out"; else cp "{tmp_path}/nuc.tsv" "$out"; fi
[ -n "$mut" ] && cp "{tmp_path}/mutation_all.tsv" "$mut"
[ -n "$nuc_out" ] && echo ">hit" > "$nuc_out"
exit 0
'''
    exe = env / "amrfinder"
    exe.write_text(script)
    exe.chmod(0o755)
    monkeypatch.setenv("ARVA_TOOL_AMRFINDERPLUS", str(exe))
    registry._CACHE.pop("amrfinderplus", None)
    yield exe
    registry._CACHE.pop("amrfinderplus", None)


@pytest.fixture
def real_amr(monkeypatch):
    if REAL_AMR:
        monkeypatch.setenv("ARVA_TOOL_AMRFINDERPLUS", REAL_AMR)
    registry._CACHE.pop("amrfinderplus", None)
    d = detect("amrfinderplus", refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"AMRFinderPlus is not available: {d.message}")
    yield d.path
    registry._CACHE.pop("amrfinderplus", None)


@pytest.fixture(autouse=True)
def hidden_amr(monkeypatch, request):
    if not {"fake_amr", "real_amr"} & set(request.fixturenames):
        monkeypatch.setenv("ARVA_TOOL_AMRFINDERPLUS", "/nonexistent/amrfinder")
    registry._CACHE.pop("amrfinderplus", None)


def registered_release(client, storage_root: Path, name: str, index: bool = False) -> dict:
    """The constructed release copied into the database folder and registered (indexed with the real
    amrfinder_index, or with an empty AMRProt.fa.phr for the stand-in)."""
    folder = storage_root / "databases" / name / "2026-08-07.1"
    shutil.rmtree(folder.parent, ignore_errors=True)
    shutil.copytree(RELEASE, folder)
    if index:
        from arva_tools.amrfinderplus import AmrfinderplusAdapter, env_for
        from arva_tools.runner import run_command

        exe = detect("amrfinderplus").path
        run_command(AmrfinderplusAdapter.index_argv(exe, folder), cwd=folder.parent,
                    stderr_path=folder.parent / "index.log", extra_env=env_for(exe, folder.parent))
    else:
        (folder / "AMRProt.fa.phr").write_text("")
    r = client.post(f"{API}/databases/register", json={"path": str(folder)})
    assert r.status_code == 201, r.text
    return r.json()


def species_result(sample: dict, assembly: dict, species: str) -> None:
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="species_identification",
                          tool_name="skani", tool_version="0.4.0", parameters={}, status=JobStatus.completed,
                          log_text="")
        db.add(job)
        db.flush()
        db.add(SpeciesResult(sample_id=sample["id"], assembly_id=assembly["id"], job_id=job.id, method="skani",
                             tool="skani", tool_version="0.4.0", parameters={}, status="same_species",
                             species=species, hits=[], interpretation={}, consistency=[], warnings=[], details={},
                             files={}))
        db.commit()


def annotation(storage_root: Path, sample: dict, assembly: dict) -> str:
    """A Prokka annotation of the fixture genome, from Prokka's real output (its proteins and GFF) and the genome."""
    from arva_core.annotation import summarize, write_jsonl
    from arva_tools.prokka import ProkkaAdapter

    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="prokka_annotation",
                          tool_name="Prokka", tool_version="1.14.6", parameters={}, status=JobStatus.completed,
                          log_text="")
        db.add(job)
        db.commit()
        rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}"
        out = storage_root / rel / "prokka"
        out.mkdir(parents=True)
        files = {}
        for kind, src in (("gff3", ADAPTER_FIXTURES / "prokka" / "annotation.gff"),
                          ("faa", ADAPTER_FIXTURES / "prokka" / "annotation.faa"), ("fna", GENOME)):
            dest = out / f"annotation.{src.suffix.lstrip('.')}"
            shutil.copyfile(src, dest)
            files[kind] = {"path": f"{rel}/prokka/{dest.name}", "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                           "size_bytes": dest.stat().st_size}
        sequences, features = ProkkaAdapter.parse_gff((out / "annotation.gff").read_text())
        write_jsonl(storage_root / rel / "features.jsonl", features)
        a = Annotation(sample_id=sample["id"], assembly_id=assembly["id"], job_id=job.id, tool="Prokka",
                       tool_version="1.14.6", parameters={}, steps={"cds": {"status": "searched"}},
                       summary=summarize(features, sequences, sum(x["length"] for x in sequences), True),
                       sequences=sequences, files=files,
                       features_path=f"{rel}/features.jsonl")
        db.add(a)
        db.commit()
        return a.id


def start(client, assembly: dict, **body) -> dict:
    r = client.post(f"{API}/assemblies/{assembly['id']}/amr", json={"confirmed": True, **body})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job.get("error_message")
    return job


def test_preview_and_start_without_tool_or_database(client):
    sample = new_sample(client, "AMR-0")
    a = assemble(client, sample, GENOME)
    plan = client.post(f"{API}/assemblies/{a['id']}/amr/preview", json={}).json()
    assert plan["tool"]["status"] == "not_installed" and plan["database"] is None
    assert [p["code"] for p in plan["problems"]] == ["tool_unavailable", "no_database"]
    assert plan["organism"]["rule"] == "no_species" and plan["annotations"] == []
    r = client.post(f"{API}/assemblies/{a['id']}/amr", json={"confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "amr_blocked"
    assert client.post(f"{API}/assemblies/{a['id']}/amr", json={"confirmed": False}).json()["code"] == "amr_confirm"
    r = client.post(f"{API}/assemblies/{a['id']}/amr", json={"confirmed": True, "settings": {"mode": "combined"}})
    assert r.json()["code"] == "amr_annotation_needed"
    bad = client.post(f"{API}/assemblies/{a['id']}/amr", json={"confirmed": True, "settings": {"organism": "x; rm"}})
    assert bad.status_code == 422
    assert client.get(f"{API}/samples/{sample['id']}/amr").json() == []


def test_stand_in_run_results_matrix_track_and_reports(client, fake_amr, storage_root):
    record = registered_release(client, storage_root, "amr-stand-in")
    assert record["kind"] == "amrfinderplus" and record["variant"] == "release"
    assert record["compatibility"]["code"] == "data_ok" and record["is_default"]
    sample = new_sample(client, "AMR-1")
    other = client.post(f"{API}/projects/{sample['project_id']}/samples", json={"sample_code": "AMR-2"}).json()
    a = assemble(client, sample, GENOME)
    species_result(sample, a, "Staphylococcus aureus")
    ann_id = annotation(storage_root, sample, a)
    plan = client.post(f"{API}/assemblies/{a['id']}/amr/preview", json={}).json()
    assert plan["problems"] == [] and plan["database"]["id"] == record["id"]
    assert plan["organism"]["organism"] == "Staphylococcus_aureus" and plan["organism"]["rule"] == "species"
    assert plan["organism"]["species"]["species"] == "Staphylococcus aureus"
    assert len(plan["organisms"]) == 32 and plan["defaults_match"] is True
    assert [(x["id"], x["annotation_format"], x["usable"]) for x in plan["annotations"]] == [(ann_id, "prokka", True)]
    r = client.post(f"{API}/assemblies/{a['id']}/amr", json={"confirmed": True, "settings": {"organism": "Bacillus"}})
    assert r.status_code == 400 and r.json()["code"] == "amr_organism_unknown"

    job = start(client, a, settings={"organism": "Staphylococcus_aureus"})
    p = job["parameters"]
    assert (p["mode"], p["organism"], p["plus"], p["ident_min"], p["coverage_min"]) == \
        ("nucleotide", "Staphylococcus_aureus", True, -1, 0.5)
    assert p["organism_choice"] == {"proposed": "Staphylococcus_aureus", "rule": "species",
                                    "species": plan["organism"]["species"] | {"created_at": p["organism_choice"][
                                        "species"]["created_at"]}, "chosen": "Staphylococcus_aureus",
                                    "changed_by_user": False}
    assert job["database_kind"] == "amrfinderplus" and job["database_version"] == "2026-08-07.1"
    argv = job["commands"][0]
    assert argv[argv.index("--organism") + 1] == "Staphylococcus_aureus" and "--plus" in argv
    assert argv[argv.index("--database") + 1] == record["path"]
    (run,) = client.get(f"{API}/samples/{sample['id']}/amr").json()
    assert run["counts"] == {"total": 3, "AMR": 2, "VIRULENCE": 1, "STRESS": 0, "point_mutations": 1,
                             "incomplete": 1}
    hits = {h["element_symbol"]: h for h in run["hits"]}
    assert hits["sasG"]["method_kind"] == "contig_end" and hits["gyrA_S84L"]["method_kind"] == "point"
    assert hits["blaZ"]["feature"] == {"annotation_id": ann_id, "feature_id": hits["blaZ"]["feature"]["feature_id"],
                                       "locus_tag": "SYNT_00002", "gene": None, "product": "hypothetical protein",
                                       "how": "overlap", "overlap": 1.0}
    assert [w["code"] for w in run["warnings"]] == ["genotype_not_phenotype", "hits_contig_end",
                                                   "point_mutation_genes_not_found", "synthetic_input"]
    assert run["by_class"] == [{"class": "BETA-LACTAM", "elements": ["blaZ"], "count": 1},
                               {"class": "QUINOLONE", "elements": ["gyrA_S84L"], "count": 1}]
    assert set(run["files"]) == {"report", "mutation_all", "nucleotide_hits", "log"}
    f = client.get(f"{API}/amr/runs/{job['id']}/files/report")
    assert f.status_code == 200 and f.text.startswith("Protein id") and f.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"{API}/amr/runs/{job['id']}/files/elsewhere").status_code == 404

    combined = start(client, a, settings={"mode": "combined"}, annotation_id=ann_id)
    argv = combined["commands"][0]
    assert argv[argv.index("--annotation_format") + 1] == "prokka" and "--organism" not in argv
    newest = client.get(f"{API}/samples/{sample['id']}/amr").json()[0]
    assert newest["job_id"] == combined["id"]
    blaz = next(h for h in newest["hits"] if h["element_symbol"] == "blaZ")
    assert (blaz["protein_id"], blaz["feature"]["how"], blaz["method"]) == ("SYNT_00002", "protein_id", "EXACTP")
    assert "point_mutations_not_searched" in [w["code"] for w in newest["warnings"]]

    track = client.get(f"{API}/annotations/{ann_id}/amr").json()
    assert track["run"]["job_id"] == combined["id"] and {h["contig"] for h in track["hits"]} == {CHROM}
    assert {h["element_symbol"]: h["end"] for h in track["hits"]}["sasG"] == 2936

    overview = client.get(f"{API}/projects/{sample['project_id']}/amr").json()
    assert overview["searched"] == 1 and [e["element_symbol"] for e in overview["elements"]] == \
        ["blaZ", "gyrA_S84L", "sasG"]
    rows = {r["sample_code"]: r for r in overview["samples"]}
    assert rows["AMR-1"]["present"]["blaZ"] == ["complete"] and rows["AMR-2"]["latest"] is None
    matrix = client.get(f"{API}/projects/{sample['project_id']}/amr_matrix.csv").text.splitlines()
    assert matrix[0] == "sample_code,searched,blaZ,gyrA_S84L,sasG"
    assert "AMR-1,yes,1,1,1" in matrix and "AMR-2,no,,," in matrix
    csv_text = client.get(f"{API}/projects/{sample['project_id']}/amr.csv").text
    assert csv_text.count("\n") == 7 and "PARTIAL_CONTIG_ENDX" in csv_text
    assert other["id"] not in csv_text

    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "Antimicrobial resistance and virulence genes" in html and "Genotype is not phenotype" in html
    assert "partial, at a contig end" in html and "AMRFinderPlus does not predict" in html
    data = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    assert [len(r["hits"]) for r in data["amr"]] == [3, 3]
    report_csv = client.get(f"{API}/samples/{sample['id']}/report?format=csv").text
    assert report_csv.count(",amr,") == 6 and "gyrA_S84L" in report_csv


def test_runtime_check_of_the_database(client, fake_amr, storage_root, held_queue):
    from app.tasks.amr import run_amr_job

    record = registered_release(client, storage_root, "amr-changed")
    sample = new_sample(client, "AMR-3")
    a = assemble(client, sample, GENOME)
    r = client.post(f"{API}/assemblies/{a['id']}/amr", json={"confirmed": True})
    assert r.status_code == 202
    with SessionLocal() as db:
        db.get(ReferenceDatabase, record["id"]).checksum = "sha256:other"
        db.commit()
    assert run_amr_job(r.json()["id"]) == "failed"
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["error_detail"]["code"] == "database_changed"


def test_bakta_copy_is_registered_only_when_amrfinderplus_reads_it(client, fake_amr, storage_root):
    bakta = storage_root / "databases" / "bakta-test"
    copy = bakta / "amrfinderplus-db" / "2024-12-18.1"
    copy.mkdir(parents=True)
    for name in ("AMRProt.fa.phr", "AMRProt.fa.pin", "AMRProt.fa.psq", "AMR.LIB.h3f", "AMR.LIB.h3i", "AMR.LIB.h3m",
                 "AMR.LIB.h3p", "fam.tsv", "taxgroup.tsv", "AMRProt-mutation.tsv", "AMRProt-susceptible.tsv",
                 "AMRProt-suppress.tsv"):
        (copy / name).write_text("x")
    (copy / "version.txt").write_text("2024-12-18.1\n")
    (copy / "database_format_version.txt").write_text("4.0.1\n")
    os.symlink("2024-12-18.1", bakta / "amrfinderplus-db" / "latest")
    with SessionLocal() as db:
        db.add(ReferenceDatabase(key="bakta-light", kind="bakta", name="Bakta database (light)", version="6.0",
                                 path=str(bakta), status=DatabaseStatus.registered, origin=DatabaseOrigin.register,
                                 log_text=""))
        db.commit()
    sample = new_sample(client, "AMR-4")
    a = assemble(client, sample, GENOME)
    plan = client.post(f"{API}/assemblies/{a['id']}/amr/preview", json={}).json()
    (c,) = plan["bakta_copies"]
    assert (c["version"], c["variant"], c["record_id"]) == ("2024-12-18.1", "bakta_copy", None)
    assert c["compatibility"] == {"status": "incompatible", "code": "data_too_old", "params": {
        "tool": "AMRFinderPlus", "version": "4.2.7", "data": "2024-12-18.1", "needs": "2025-09-22.2",
        "format": "4.0.1"}}
    (bakta_record,) = [d for d in client.get(f"{API}/databases").json() if d["kind"] == "bakta"]
    assert bakta_record["amrfinderplus_db"] is None or bakta_record["amrfinderplus_db"].get("compatibility")
    (copy / "version.txt").write_text("2026-08-07.1\n")
    (copy / "database_format_version.txt").write_text("4.2.0\n")
    plan = client.post(f"{API}/assemblies/{a['id']}/amr/preview", json={}).json()
    (c,) = plan["bakta_copies"]
    # Read by AMRFinderPlus, but without AMRProt.fa the nucleotide and combined searches cannot run on it.
    assert c["compatibility"]["status"] == "compatible" and not c["complete"] and c["record_id"] is None
    for name in ("AMRProt.fa", "AMR_CDS.fa", "AMR.LIB"):
        (copy / name).write_text(">x\nM\n")
    plan = client.post(f"{API}/assemblies/{a['id']}/amr/preview", json={}).json()
    (c,) = plan["bakta_copies"]
    assert c["complete"] and c["record_id"]
    (rec,) = [d for d in client.get(f"{API}/databases").json() if d["kind"] == "amrfinderplus"]
    assert (rec["origin"], rec["key"], rec["status"], rec["variant"]) == ("register", "amrfinderplus-bakta",
                                                                         "registered", "release")
    assert plan["database"]["id"] == rec["id"]


# --- Releases from a stand-in of NCBI's folder ------------------------------------------------------------------

class _Listing(SimpleHTTPRequestHandler):
    """NCBI's folder listings (Apache's format: <a href="name">name</a>  date  size) over the served tree."""

    def log_message(self, *args):
        pass

    def list_directory(self, path):
        entries = []
        for p in sorted(Path(path).iterdir()):
            size = "-" if p.is_dir() else (f"{p.stat().st_size / 1024:.1f}K" if p.stat().st_size >= 1024 else
                                           str(p.stat().st_size))
            name = p.name + ("/" if p.is_dir() else "")
            entries.append(f'<a href="{name}">{name}</a>{" " * 8}2026-08-10 14:51  {size}')
        body = ("<html><body><h1>Index</h1><pre>" + "\n".join(entries) + "</pre></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        import io

        return io.BytesIO(body)


@pytest.fixture
def ncbi(tmp_path, monkeypatch):
    root = tmp_path / "ncbi"
    shutil.copytree(RELEASE, root / "4.2" / "2026-08-07.1")
    (root / "4.2" / "2025-01-10.1").mkdir()
    incomplete = root / "4.2" / "2026-09-01.1"
    shutil.copytree(RELEASE, incomplete)
    (incomplete / "AMR_CDS.fa").unlink()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Listing, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "amrfinder_db_url", f"http://127.0.0.1:{server.server_port}")
    yield root
    server.shutdown()


def test_release_listing_plan_and_refusals(client, fake_amr, ncbi):
    listed = client.get(f"{API}/databases/amrfinderplus/releases").json()
    assert listed["minor"] == "4.2" and listed["tool_version"] == "4.2.7"
    assert [(r["version"], r["compatibility"]) for r in listed["releases"]] == [
        ("2026-09-01.1", "compatible"), ("2026-08-07.1", "compatible"), ("2025-01-10.1", "data_too_old")]
    plan = client.post(f"{API}/databases/amrfinderplus/plan", json={"version": "2026-08-07.1"}).json()
    names = [f["name"] for f in plan["files"]]
    assert names[:11] == ["AMR.LIB", "AMRProt.fa", "AMRProt-mutation.tsv", "AMRProt-suppress.tsv",
                          "AMRProt-susceptible.fa", "AMRProt-susceptible.tsv", "AMR_CDS.fa",
                          "database_format_version.txt", "fam.tsv", "taxgroup.tsv", "version.txt"]
    assert names[11:] == ["AMR_DNA-Staphylococcus_aureus.fa", "AMR_DNA-Staphylococcus_aureus.tsv", "changes.txt"]
    assert plan["missing"] == [] and plan["checksums_published"] is False and plan["blocked_by"] is None
    assert plan["folder"] == "amrfinderplus/2026-08-07.1" and plan["download_bytes"] > 0
    r = client.post(f"{API}/databases/amrfinderplus/download", json={"version": "2026-08-07.1", "confirm_bytes": 1,
                                                                     "accept_terms": True})
    assert r.status_code == 400 and r.json()["code"] == "amr_db_confirm"
    gap = client.post(f"{API}/databases/amrfinderplus/plan", json={"version": "2026-09-01.1"}).json()
    assert gap["missing"] == ["AMR_CDS.fa"]
    r = client.post(f"{API}/databases/amrfinderplus/download", json={
        "version": "2026-09-01.1", "confirm_bytes": gap["download_bytes"], "accept_terms": True})
    assert r.json()["code"] == "amr_db_incomplete_release"
    empty = client.post(f"{API}/databases/amrfinderplus/plan", json={"version": "2025-01-10.1"})
    assert empty.status_code == 400 and empty.json()["code"] == "amr_db_unknown_release"
    assert client.post(f"{API}/databases/amrfinderplus/plan", json={"version": "latest"}).status_code == 422


def test_release_download_and_index_with_the_real_tool(client, real_amr, ncbi, storage_root):
    plan = client.post(f"{API}/databases/amrfinderplus/plan", json={"version": "2026-08-07.1"}).json()
    r = client.post(f"{API}/databases/amrfinderplus/download", json={
        "version": "2026-08-07.1", "confirm_bytes": plan["download_bytes"], "accept_terms": True})
    assert r.status_code == 202, r.text
    record = client.get(f"{API}/databases/{r.json()['id']}").json()
    assert record["status"] == "installed", record.get("error_message")
    assert (record["origin"], record["variant"], record["compatibility"]["code"]) == ("download", "release", "data_ok")
    folder = Path(record["path"])
    assert folder == storage_root / "databases" / "amrfinderplus" / "2026-08-07.1"
    assert (folder / "AMRProt.fa.phr").is_file() and (folder / "AMR.LIB.h3m").is_file()
    assert oct((folder / "AMRProt.fa").stat().st_mode & 0o777) == "0o444"
    with SessionLocal() as db:
        details = db.get(ReferenceDatabase, record["id"]).details
    fetched = {f["name"]: f["sha256"] for f in details["release"]["fetched"]}
    assert fetched["AMRProt.fa"] == hashlib.sha256((RELEASE / "AMRProt.fa").read_bytes()).hexdigest()
    assert details["database_check"]["ok"] and details["index"]["argv"][0] == "amrfinder_index"
    again = client.post(f"{API}/databases/amrfinderplus/plan", json={"version": "2026-08-07.1"}).json()
    assert again["blocked_code"] == "already_known"


def test_real_amrfinder_on_constructed_database(client, real_amr, storage_root, tmp_path):
    registered_release(client, storage_root, "amr-real", index=True)
    cds = [c.split("\n", 1)[1].replace("\n", "") for c in (RELEASE / "AMR_CDS.fa").read_text().split(">")[1:]]
    three = tmp_path / "three_cds.fna"
    three.write_text(">TEST_AMR_CDS_from_database\n" + ("N" * 200).join(cds) + "\n")
    sample = new_sample(client, "AMR-5")
    a = assemble(client, sample, three)
    job = start(client, a, settings={"organism": "Staphylococcus_aureus"})
    (run,) = client.get(f"{API}/samples/{sample['id']}/amr").json()
    assert {(h["element_symbol"], h["method"], h["identity"]) for h in run["hits"]} == {
        ("mecA", "EXACTX", 100.0), ("blaZ", "EXACTX", 100.0), ("tet(38)", "EXACTX", 100.0)}
    assert run["log"]["database_version"] == "2026-08-07.1" and run["point_mutation_screen"]["rows"] == 0
    assert job["result_summary"]["counts"]["AMR"] == 3
    synthetic = new_sample(client, "AMR-6")
    s = assemble(client, synthetic, SYNTHETIC)
    start(client, s)
    (none,) = client.get(f"{API}/samples/{synthetic['id']}/amr").json()
    assert none["hits"] == [] and [w["code"] for w in none["warnings"]][:2] == ["genotype_not_phenotype",
                                                                                 "point_mutations_not_searched"]
    with SessionLocal() as db:
        assert db.query(AmrResult).filter(AmrResult.sample_id == synthetic["id"]).count() == 0


def test_amr_results_migration_up_and_down(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.db.session import engine

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch_amr")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_amr"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch_amr"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    try:
        command.upgrade(cfg, "head")
        with db.begin() as c:
            fks = dict(c.execute(text("SELECT conname, confdeltype FROM pg_constraint WHERE conrelid = "
                                      "'amr_results'::regclass AND contype = 'f'")).all())
            assert fks == {"fk_amr_results_sample_id": "c", "fk_amr_results_assembly_id": "c",
                           "fk_amr_results_job_id": "c", "fk_amr_results_annotation_id": "n"}
        command.downgrade(cfg, "c7f4a2e9d6b1")
        with db.begin() as c:
            assert c.execute(text("SELECT to_regclass('amr_results')")).scalar() is None
        command.upgrade(cfg, "head")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_amr"))
