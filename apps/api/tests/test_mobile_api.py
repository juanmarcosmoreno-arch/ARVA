"""Plasmids, mobile elements and VFDB: ABRicate's bundled databases as read-only records, the MOB-suite database
(registered, and prepared from a constructed archive by ARVA's own code with the real makeblastdb, mash and ete3),
previews and request checks, the recorded jobs, the contig table (MOB-suite's call next to the replicons and the
assembler's circularity), the virulence view (VFDB and AMRFinderPlus side by side), the project overview, the
annotation's elements, files, reports and the run-time re-check of the database.

Stand-ins (shell scripts with the tools' real --help and version lines) replay the tools' real outputs on S. aureus
N315 and E. coli plasmid R388 (workflows/tool-adapters/tests/fixtures/<tool>/README.md) for a CONSTRUCTED input: random
sequences of the records' lengths under their accessions, so that those outputs fit it (not biology). The end-to-end
tests run the real ABRicate, IntegronFinder and MOB-suite (skipped when absent) on ARVA's SYNTHETIC genome.
"""
import io
import json
import os
import random
import shutil
import tarfile
import threading
import zipfile
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from arva_tools import mobsuite as mob
from arva_tools import registry
from arva_tools.registry import detect
from test_amr_api import _Listing
from test_annotation_api import assemble, new_sample

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    AnalysisJob,
    Annotation,
    DatabaseOrigin,
    DatabaseStatus,
    JobStatus,
    MobileElementResult,
    ReferenceDatabase,
    VersionSource,
    VirulenceResult,
)

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures"
SYNTHETIC = REPO / "examples" / "synthetic-genome" / "reference.fasta"
REAL_DB = Path(os.environ.get("ARVA_TEST_MOBSUITE_DB") or Path.home() / ".arva-db/mobsuite-3.1.8/3.1.8")
LENGTHS = {"NC_002745.2": 2814816, "NC_003140.1": 24653, "NC_028464.1": 33913}


def constructed_genome(path: Path) -> Path:
    rng = random.Random(5)
    with open(path, "w") as out:
        for name, n in LENGTHS.items():
            seq = "".join(rng.choice("ACGT") for _ in range(n))
            out.write(f">{name}\n" + "\n".join(seq[i:i + 80] for i in range(0, n, 80)) + "\n")
    return path


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _bundled(db: Path, name: str, sequences: int) -> None:
    folder = db / name
    folder.mkdir(parents=True)
    (folder / "sequences").write_text(f">{name}~~~x~~~y~~~\nACGT\n")
    files = [f"sequences.{s}" for s in ("ndb", "nhr", "nin", "nsq")]
    for f in files:
        (folder / f).write_text("x")
    (folder / "sequences.njs").write_text(json.dumps({"description": name, "number-of-sequences": sequences,
                                                      "last-updated": "2026-04-03T03:29:00", "dbtype": "Nucleotide",
                                                      "files": files}))


@pytest.fixture
def mobile_fake_tools(tmp_path, monkeypatch):
    env = tmp_path / "env"
    (env / "bin").mkdir(parents=True)
    _bundled(env / "db", "vfdb", 4592)
    _bundled(env / "db", "plasmidfinder", 488)
    models = env / "lib" / "python3.14" / "site-packages" / "integron_finder" / "data" / "Models"
    models.mkdir(parents=True)
    (models / "attc_4.cm").write_text("CONSTRUCTED model file\n")
    a = FIX / "abricate"
    exe = {"abricate": _script(env / "bin" / "abricate", f'''
case "$1" in --version) echo "abricate 1.4.0"; exit 0;; --help) cat "{a}/help_1.4.0.txt"; exit 0;;
  --list) cat "{a}/list_1.4.0.txt"; exit 0;; esac
db=""; while [ $# -gt 0 ]; do [ "$1" = "--db" ] && db="$2"; shift; done
cat "{a}/n315.$db.stderr.log" >&2; cat "{a}/n315.$db.tsv"
'''), "mobsuite": _script(env / "bin" / "mob_recon", f'''
case "$1" in --version) echo "mob_recon 3.1.9"; exit 0;; --help) cat "{FIX}/mobsuite/help_3.1.9.txt"; exit 0;; esac
out=""; while [ $# -gt 0 ]; do [ "$1" = "--outdir" ] && out="$2"; shift; done
mkdir "$out" || exit 1
for f in contig_report.txt mobtyper_results.txt mge.report.txt biomarkers.blast.txt; do
  cp "{FIX}/mobsuite/n315.$f" "$out/$f"; done
echo "MOB-recon completed" >&2
'''), "integronfinder": _script(env / "bin" / "integron_finder", f'''
case "$1" in --version) echo "integron_finder version 2.0.6"; exit 0;;
  --help) cat "{FIX}/integronfinder/help_2.0.6.txt"; exit 0;; esac
out=""; while [ $# -gt 0 ]; do [ "$1" = "--outdir" ] && out="$2"; shift; done
mkdir -p "$out/Results_Integron_Finder_contigs"
cp "{FIX}/integronfinder/r388.integrons" "$out/Results_Integron_Finder_contigs/contigs.integrons"
cp "{FIX}/integronfinder/r388.summary" "$out/Results_Integron_Finder_contigs/contigs.summary"
echo "INFO : done" > "$out/Results_Integron_Finder_contigs/integron_finder.out"
''')}
    for tool, path in exe.items():
        monkeypatch.setenv(f"ARVA_TOOL_{tool.upper()}", str(path))
        registry._CACHE.pop(tool, None)
    yield exe


def mobsuite_folder(root: Path) -> Path:
    """A MOB-suite folder as ARVA prepares it (empty files under MOB-suite 3.1.9's names, ARVA's provenance file)."""
    root.mkdir(parents=True)
    for name in (*mob.DB_FILES, *mob.PLASMID_INDEX, *mob.REPETITIVE_INDEX, mob.MASH_SKETCH, mob.TAXA, mob.TAXA_EXTRA):
        (root / name).write_text("x")
    shutil.copyfile(FIX / "mobsuite" / "ARVA_DATABASE_3.1.8.json", root / "ARVA_DATABASE.json")
    return root


def registered_mobsuite(client, storage_root: Path, name: str) -> dict:
    folder = mobsuite_folder(storage_root / "databases" / name / "3.1.8")
    r = client.post(f"{API}/databases/register", json={"path": str(folder)})
    assert r.status_code == 201, r.text
    return r.json()


def empty_annotation(sample: dict, assembly: dict, storage_root: Path) -> str:
    """A constructed annotation record of the assembly's sequences (no features), so its elements can be placed."""
    from arva_core.annotation import write_jsonl

    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="prokka_annotation",
                          tool_name="Prokka", tool_version="1.14.6", parameters={}, status=JobStatus.completed,
                          log_text="")
        db.add(job)
        db.commit()
        rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}"
        (storage_root / rel).mkdir(parents=True)
        write_jsonl(storage_root / rel / "features.jsonl", [])
        a = Annotation(sample_id=sample["id"], assembly_id=assembly["id"], job_id=job.id, tool="Prokka",
                       tool_version="1.14.6", parameters={}, steps={}, summary={}, files={},
                       sequences=[{"id": f"seq{i}", "original_id": n, "length": n_len}
                                  for i, (n, n_len) in enumerate(LENGTHS.items(), 1)],
                       features_path=f"{rel}/features.jsonl")
        db.add(a)
        db.commit()
        return a.id


def start(client, path: str, body: dict) -> dict:
    r = client.post(f"{API}{path}", json={"confirmed": True, **body})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", (job.get("error_message"), job.get("log_text", "")[-2000:])
    return job


def test_without_tools_everything_is_blocked_and_not_searched(client, tmp_path):
    sample = new_sample(client, "MOB-0")
    a = assemble(client, sample, constructed_genome(tmp_path / "g.fna"))
    plan = client.post(f"{API}/assemblies/{a['id']}/mobile-elements/preview", json={"method": "mobsuite"}).json()
    assert plan["tool"]["status"] == "not_installed" and [p["code"] for p in plan["problems"]] == [
        "tool_unavailable", "no_database"]
    assert set(plan["circularity"]) == set(LENGTHS)
    r = client.post(f"{API}/assemblies/{a['id']}/mobile-elements", json={"method": "plasmidfinder", "confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "mobile_blocked"
    r = client.post(f"{API}/assemblies/{a['id']}/mobile-elements", json={"method": "x", "confirmed": True})
    assert r.status_code == 422
    assert client.post(f"{API}/assemblies/{a['id']}/virulence", json={"confirmed": True}).json()["code"] == \
        "mobile_blocked"
    assert client.get(f"{API}/samples/{sample['id']}/mobile-elements").json() == {"runs": [], "assemblies": []}
    overview = client.get(f"{API}/projects/{sample['project_id']}/mobile-elements").json()
    (row,) = overview["samples"]
    assert all(v is None for v in row["methods"].values()) and row["virulence"] == {"vfdb": None,
                                                                                    "amrfinderplus": None}


def test_stand_in_runs_contig_table_virulence_overview_and_reports(client, mobile_fake_tools, storage_root, tmp_path):
    dbs = {d["key"]: d for d in client.get(f"{API}/databases").json()}
    vf, pf = dbs["abricate-vfdb"], dbs["abricate-plasmidfinder"]
    assert (vf["kind"], vf["origin"], vf["version"], vf["compatibility"]["code"]) == (
        "vfdb", "bundled", "2026-04-03", "bundled_with_tool")
    assert pf["kind"] == "plasmidfinder" and pf["name"] == "PlasmidFinder replicons (bundled with ABRicate 1.4.0)"
    refused = client.post(f"{API}/databases/register", json={"path": vf["path"]})
    assert refused.json()["code"] in ("bundled_only", "outside_roots")
    record = registered_mobsuite(client, storage_root, "mob-stand-in")
    assert (record["kind"], record["version"], record["compatibility"]["code"]) == ("mobsuite", "3.1.8", "data_paired")

    sample = new_sample(client, "MOB-1")
    other = client.post(f"{API}/projects/{sample['project_id']}/samples", json={"sample_code": "MOB-2"}).json()
    a = assemble(client, sample, constructed_genome(tmp_path / "g.fna"))
    for method in ("mobsuite", "plasmidfinder", "integronfinder"):
        plan = client.post(f"{API}/assemblies/{a['id']}/mobile-elements/preview", json={"method": method}).json()
        assert plan["problems"] == [], (method, plan["problems"])
        assert plan["defaults_match"] is True, (method, plan["tool_defaults"])
    plan = client.post(f"{API}/assemblies/{a['id']}/mobile-elements/preview", json={"method": "integronfinder"}).json()
    assert plan["models"]["files"] == ["attc_4.cm"] and plan["database"] is None

    bad = client.post(f"{API}/assemblies/{a['id']}/mobile-elements",
                      json={"method": "mobsuite", "confirmed": True, "settings": {"min_rep_ident": 0}})
    assert bad.status_code == 422 and bad.json()["code"] == "mobile_settings_invalid"
    unknown = client.post(f"{API}/assemblies/{a['id']}/mobile-elements",
                          json={"method": "plasmidfinder", "confirmed": True, "settings": {"db": "card"}})
    assert unknown.status_code == 422
    assert client.post(f"{API}/assemblies/{a['id']}/mobile-elements",
                       json={"method": "mobsuite", "confirmed": False}).json()["code"] == "mobile_confirm"

    mob_job = start(client, f"/assemblies/{a['id']}/mobile-elements", {"method": "mobsuite",
                                                                     "settings": {"min_con_cov": 70}})
    argv = mob_job["commands"][0]
    assert argv[argv.index("--min_con_cov") + 1] == "70" and argv[argv.index("--database_directory") + 1] == \
        record["path"]
    assert mob_job["database_kind"] == "mobsuite" and mob_job["database_version"] == "3.1.8"
    pf_job = start(client, f"/assemblies/{a['id']}/mobile-elements", {"method": "plasmidfinder",
                                                                    "settings": {"minid": 90}})
    assert pf_job["database_key"] == "abricate-plasmidfinder"
    assert pf_job["commands"][0][1:5] == ["--datadir", str(Path(pf["path"]).parent), "--db", "plasmidfinder"]
    if_job = start(client, f"/assemblies/{a['id']}/mobile-elements", {"method": "integronfinder"})
    assert if_job["database_kind"] == "integronfinder_models" and if_job["database_checksum"].startswith("sha256:")
    assert "--local-max" in if_job["commands"][0] and "--topology-file" in if_job["commands"][0]
    vf_job = start(client, f"/assemblies/{a['id']}/virulence", {"settings": {"minid": 80, "mincov": 80}})
    assert vf_job["database_key"] == "abricate-vfdb" and vf_job["parameters"]["database_terms"]["licence"] == \
        "Not stated on the download page"

    view = client.get(f"{API}/samples/{sample['id']}/mobile-elements").json()
    runs = {r["method"]: r for r in view["runs"]}
    assert set(runs) == {"mobsuite", "plasmidfinder", "integronfinder"}
    m = runs["mobsuite"]
    assert m["counts"]["plasmids"] == 1 and m["counts"]["plasmid_contigs"] == 1 and m["counts"]["repetitive_elements"] == 8
    assert [w["code"] for w in m["warnings"]] == ["chromosome_means_unassigned", "host_range_is_prediction",
                                                 "replicon_on_unassigned_contig", "synthetic_input"]
    assert {r["category"] for r in m["rows"]} == {"contig", "plasmid", "biomarker", "mge"}
    assert runs["plasmidfinder"]["counts"]["types"] == ["rep16", "rep19", "rep22", "rep5a"]
    assert runs["plasmidfinder"]["warnings"][0]["code"] == "plasmidfinder_meaning"
    assert runs["integronfinder"]["counts"] == {"integrons": 1, "complete": 1, "In0": 0, "CALIN": 0}
    (table,) = view["assemblies"]
    contigs = {c["contig"]: c for c in table["contigs"]}
    plasmid, chrom, r388 = contigs["NC_003140.1"], contigs["NC_002745.2"], contigs["NC_028464.1"]
    assert plasmid["mobsuite"]["molecule_type"] == "plasmid" and plasmid["mobsuite"]["predicted_mobility"] == \
        "mobilizable"
    assert [r["type"] for r in plasmid["replicons"]] == ["rep19", "rep5a", "rep16"]
    assert chrom["mobsuite"]["molecule_type"] == "chromosome" and chrom["mobsuite"]["rep_types"] == \
        ["rep_cluster_1018"] and [r["type"] for r in chrom["replicons"]] == ["rep22"]
    assert r388["mobsuite"] == {"molecule_type": None} and r388["integrons"] == 1 and r388["replicons"] == []
    assert chrom["insertion_sequences"] is None and chrom["genomad"] is None, "not searched"
    assert chrom["circular"] is None
    f = client.get(f"{API}/mobile-elements/runs/{mob_job['id']}/files/contig_report.txt")
    assert f.status_code == 200 and f.text.startswith("sample_id") and f.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"{API}/mobile-elements/runs/{mob_job['id']}/files/..%2Fetc").status_code == 404

    vir = client.get(f"{API}/samples/{sample['id']}/virulence").json()
    (run,) = vir["runs"]
    assert run["counts"]["hits"] == 86 and run["counts"]["incomplete"] == 13
    assert [w["code"] for w in run["warnings"]][:2] == ["vfdb_meaning", "hits_partial"]
    assert "vfdb_terms_unstated" in [w["code"] for w in run["warnings"]]
    (merged,) = vir["assemblies"]
    assert merged["sources"]["vfdb"]["status"] == "searched" and merged["sources"]["amrfinderplus"]["status"] == \
        "not_searched"
    hlb = next(r for r in merged["rows"] if r["gene"] == "hlb")
    assert (hlb["source"], hlb["kind"], hlb["vf_id"]) == ("vfdb", "partial", hlb["vf_id"])
    assert hlb["vf_id"] and hlb["vf_id"].startswith("VF")

    ann = empty_annotation(sample, a, storage_root)
    placed = client.get(f"{API}/annotations/{ann}/mobile-elements").json()
    cats = {e["category"] for e in placed["elements"]}
    assert {"plasmid_contig", "biomarker", "mge", "replicon", "integron"} <= cats
    contig_calls = {c["contig"]: c["molecule_type"] for c in placed["contigs"]}
    assert contig_calls == {"seq1": "chromosome", "seq2": "plasmid"}
    whole = next(e for e in placed["elements"] if e["category"] == "plasmid_contig")
    assert (whole["contig"], whole["start"], whole["end"]) == ("seq2", 1, 24653)
    vhits = client.get(f"{API}/annotations/{ann}/virulence").json()
    assert len(vhits["hits"]) == 86 and {h["contig"] for h in vhits["hits"]} == {"seq1"}

    overview = client.get(f"{API}/projects/{sample['project_id']}/mobile-elements").json()
    rows = {r["sample_code"]: r for r in overview["samples"]}
    assert rows["MOB-1"]["methods"]["mobsuite"]["counts"]["plasmids"] == 1
    assert rows["MOB-1"]["methods"]["isescan"] is None and rows["MOB-1"]["virulence"]["vfdb"] == 86
    assert rows["MOB-1"]["replicon_types"] == ["rep16", "rep19", "rep22", "rep5a"]
    assert all(v is None for v in rows["MOB-2"]["methods"].values()) and other["id"] == rows["MOB-2"]["sample_id"]
    assert overview["searched"]["mobsuite"] == 1 and overview["searched"]["genomad"] == 0

    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "Plasmids and mobile elements" in html and "chromosome (not assigned to a plasmid)" in html
    assert "Virulence factors" in html and "never merged into one call" in html and "VFDB licence" in html
    data = client.get(f"{API}/samples/{sample['id']}/report?format=json").json()
    assert len(data["mobile"]["runs"]) == 3 and len(data["virulence"]["runs"]) == 1
    report_csv = client.get(f"{API}/samples/{sample['id']}/report?format=csv").text
    assert report_csv.count(",mobile,") > 20 and report_csv.count(",virulence,") == 86


def test_runtime_check_of_the_mobsuite_database(client, mobile_fake_tools, storage_root, held_queue, tmp_path):
    from app.tasks.mobile_elements import run_mobile_job

    record = registered_mobsuite(client, storage_root, "mob-changed")
    sample = new_sample(client, "MOB-3")
    a = assemble(client, sample, constructed_genome(tmp_path / "g.fna"))
    r = client.post(f"{API}/assemblies/{a['id']}/mobile-elements", json={"method": "mobsuite", "confirmed": True})
    assert r.status_code == 202, r.text
    with SessionLocal() as db:
        db.get(ReferenceDatabase, record["id"]).checksum = "sha256:other"
        db.commit()
    assert run_mobile_job(r.json()["id"]) == "failed"
    assert client.get(f"{API}/jobs/{r.json()['id']}").json()["error_detail"]["code"] == "database_changed"
    with SessionLocal() as db:
        assert db.query(MobileElementResult).count() == 0


# --- MOB-suite database preparation (ARVA's own code, the real makeblastdb, mash and ete3) -----------------------

class _Task:
    """What app.tasks.mobsuite_db needs of a Database Manager task."""

    def __init__(self):
        self.lines: list[str] = []

    def log(self, message: str, flush: bool = False) -> None:
        self.lines.append(message)

    def tick(self, force: bool = False, **fields) -> None:
        pass

    def ensure_room(self, needed: int) -> None:
        pass


def _member(tar: tarfile.TarFile, name: str, text: str) -> None:
    data = text.encode()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def constructed_archive(path: Path, extra: str | None = None) -> Path:
    """The layout of Zenodo 10304948's data.tar.gz (data/ with MOB-suite's files and macOS metadata), CONSTRUCTED with
    tiny files."""
    rng = random.Random(7)
    plasmids = "".join(f">P{i} plasmid {i}\n" + "".join(rng.choice("ACGT") for _ in range(3000)) + "\n"
                       for i in range(3))
    with tarfile.open(path, "w:gz") as tar:
        _member(tar, "._data", "macOS")
        tar.addfile(_dir("data/"))
        _member(tar, "data/.DS_Store", "macOS")
        for name in mob.DB_FILES:
            _member(tar, f"data/._{name}", "macOS")
            _member(tar, f"data/{name}", ">r1 constructed\nACGTACGTACGTACGTACGTACGTACGT\n" if name.endswith(
                (".fas", ".faa")) else "constructed\n")
        _member(tar, f"data/{mob.PLASMID_FASTA}", plasmids)
        _member(tar, "data/__init__.py", "")
        if extra:
            _member(tar, extra, "unexpected")
    return path


def _dir(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    return info


@pytest.fixture
def mobile_real_mobsuite(monkeypatch):
    real = os.environ.get("ARVA_TOOL_MOBSUITE_REAL") or str(Path.home() / ".arva-tools/conda/mobsuite/bin/mob_recon")
    if not Path(real).is_file():
        pytest.skip("MOB-suite's environment is not installed")
    monkeypatch.setenv("ARVA_TOOL_MOBSUITE", real)
    registry._CACHE.pop("mobsuite", None)
    return real


@pytest.fixture
def taxonomy_server(tmp_path, monkeypatch):
    root = tmp_path / "taxonomy"
    root.mkdir()
    with zipfile.ZipFile(root / "taxdmp_2026-10-01.zip", "w") as z:
        z.writestr("nodes.dmp", "1\t|\t1\t|\tno rank\t|\n2\t|\t1\t|\tsuperkingdom\t|\n1280\t|\t2\t|\tspecies\t|\n")
        z.writestr("names.dmp", "1\t|\troot\t|\t\t|\tscientific name\t|\n2\t|\tBacteria\t|\t\t|\tscientific name\t|\n"
                                "1280\t|\tStaphylococcus aureus\t|\t\t|\tscientific name\t|\n")
        z.writestr("merged.dmp", "")
    (root / "taxdmp_2026-09-01.zip").write_bytes(b"older")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Listing, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "ncbi_taxonomy_url", f"http://127.0.0.1:{server.server_port}")
    yield root
    server.shutdown()


def test_mobsuite_folder_is_prepared_without_mob_init(tmp_path, mobile_real_mobsuite, taxonomy_server):
    from app.services import mobsuite_db as plan_svc
    from app.services.database_catalogue import entry
    from app.tasks import mobsuite_db
    from app.tasks.databases import TaskFailure

    extras = plan_svc.plan_extras(False, None)
    assert extras["taxonomy"]["name"] == "taxdmp_2026-10-01.zip" and extras["taxonomy"]["bytes"] > 0
    assert [a["name"] for a in extras["taxonomy_archives"]] == ["taxdmp_2026-10-01.zip", "taxdmp_2026-09-01.zip"]
    e = entry("mobsuite-3.1.8")
    task = _Task()
    dest = tmp_path / "staging" / "unpacked"
    prepared = mobsuite_db.prepare(task, e, constructed_archive(tmp_path / "data.tar.gz"), dest, mobile_real_mobsuite,
                                   1, keep_fasta=False)
    assert prepared["plasmid_fasta"]["kept"] is False and not (dest / mob.PLASMID_FASTA).exists()
    assert set(prepared["files"]) == set(mob.DB_FILES)
    assert "._data" in prepared["skipped"] and "data/__init__.py" in prepared["skipped"]
    tax = mobsuite_db.taxonomy(task, e, extras["taxonomy"], tmp_path / "downloads", dest, mobile_real_mobsuite)
    assert tax["archive"] == "taxdmp_2026-10-01.zip" and len(tax["sha256"]) == 64
    assert not (tmp_path / "downloads" / "taxonomy" / "taxdump.tar.gz").exists()
    state = mob.database_state(dest)
    assert state["ready"] and not state["plasmid_fasta"], state["missing"]
    doc = mobsuite_db.write_provenance(dest, e, e.checksum, prepared, tax, "3.1.9")
    assert mobsuite_db.read_provenance(dest)["version"] == "3.1.8" and doc["taxonomy"]["archive"]
    with pytest.raises(TaskFailure, match="nothing was installed"):
        mobsuite_db.prepare(task, e, constructed_archive(tmp_path / "bad.tar.gz", "data/evil.sh"),
                            tmp_path / "other", mobile_real_mobsuite, 1, keep_fasta=True)


def test_the_mobsuite_download_plan_names_the_taxonomy_archive_and_start_repeats_it(client, taxonomy_server):
    plan = client.get(f"{API}/databases/catalogue/mobsuite-3.1.8/plan").json()
    extras = plan["extras"]
    assert extras["taxonomy"]["name"] == "taxdmp_2026-10-01.zip" and not extras["keep_plasmid_fasta"]
    assert plan["required_bytes"] >= plan["download_bytes"] + extras["extra_bytes"]
    kept = client.get(f"{API}/databases/catalogue/mobsuite-3.1.8/plan",
                      params={"keep_plasmid_fasta": "true", "taxonomy_archive": "taxdmp_2026-09-01.zip"}).json()
    assert kept["extras"]["taxonomy"]["name"] == "taxdmp_2026-09-01.zip"
    assert kept["required_bytes"] - plan["required_bytes"] >= extras["plasmid_fasta_bytes"] - 1_000_000
    bad = client.get(f"{API}/databases/catalogue/mobsuite-3.1.8/plan", params={"taxonomy_archive": "../x.zip"})
    assert bad.status_code == 422
    unknown = client.get(f"{API}/databases/catalogue/mobsuite-3.1.8/plan",
                         params={"taxonomy_archive": "taxdmp_2020-01-01.zip"})
    assert unknown.json()["code"] == "mobsuite_taxonomy_unknown"
    body = {"key": "mobsuite-3.1.8", "confirm_bytes": 472_851_578, "accept_licence": True}
    r = client.post(f"{API}/databases/downloads", json=body)
    assert r.status_code == 400 and r.json()["code"] == "mobsuite_taxonomy_confirm"


# --- Real tools on ARVA's SYNTHETIC genome ----------------------------------------------------------------------

@pytest.fixture
def mobile_real_tools(monkeypatch):
    found = {}
    for tool, rel in (("abricate", "abricate/bin/abricate"), ("integronfinder", "integronfinder/bin/integron_finder"),
                      ("mobsuite", "mobsuite/bin/mob_recon")):
        path = Path.home() / ".arva-tools" / "conda" / rel
        if path.is_file():
            monkeypatch.setenv(f"ARVA_TOOL_{tool.upper()}", str(path))
            registry._CACHE.pop(tool, None)
            found[tool] = detect(tool, refresh=True).path
    if not found:
        pytest.skip("none of ABRicate, IntegronFinder and MOB-suite is installed")
    return found


def test_real_tools_find_nothing_on_the_synthetic_genome(client, mobile_real_tools):
    sample = new_sample(client, "MOB-SYN")
    a = assemble(client, sample, SYNTHETIC)
    if "abricate" in mobile_real_tools:
        job = start(client, f"/assemblies/{a['id']}/mobile-elements", {"method": "plasmidfinder"})
        assert job["result_summary"]["counts"]["replicons"] == 0
        vir = start(client, f"/assemblies/{a['id']}/virulence", {})
        assert vir["result_summary"]["counts"]["hits"] == 0
        assert "synthetic_input" in [w["code"] for w in vir["result_summary"]["warnings"]]
    if "integronfinder" in mobile_real_tools:
        job = start(client, f"/assemblies/{a['id']}/mobile-elements", {"method": "integronfinder"})
        assert job["result_summary"]["counts"]["integrons"] == 0
    if "mobsuite" in mobile_real_tools and mob.database_state(REAL_DB)["ready"]:
        with SessionLocal() as db:
            db.add(ReferenceDatabase(key="mobsuite-3.1.8", kind="mobsuite", name="MOB-suite database 3.1.8",
                                     version="3.1.8", version_source=VersionSource.file, path=str(REAL_DB),
                                     origin=DatabaseOrigin.register, status=DatabaseStatus.registered,
                                     log_text="", details={}))
            db.commit()
        job = start(client, f"/assemblies/{a['id']}/mobile-elements", {"method": "mobsuite", "threads": 2})
        assert job["result_summary"]["counts"]["plasmids"] == 0
        assert job["result_summary"]["counts"]["chromosome_contigs"] == 2
    view = client.get(f"{API}/samples/{sample['id']}/mobile-elements").json()
    with SessionLocal() as db:
        assert db.query(VirulenceResult).count() == 0
    assert all(c["replicons"] in (None, []) for c in view["assemblies"][0]["contigs"])
