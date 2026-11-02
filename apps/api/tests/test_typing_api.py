"""Species-specific typing (S. aureus: SCCmec, spa, agr): the module registry and its applicability rules, the
requirements shown when a tool or the Ridom files are missing, previews and refusals, the recorded jobs and results,
the summary card (with MLST and AMRFinderPlus beside the calls), the project table and CSV, files and the report.

Stand-ins (shell scripts with the tools' real help and version lines) replay the tools' real outputs on S. aureus N315
and USA300_FPR3757 (workflows/tool-adapters/tests/fixtures/<tool>/README.md) for a CONSTRUCTED input. The end-to-end
tests run the real sccmec, spaTyper and AgrVATE (skipped when absent) on ARVA's SYNTHETIC genome and on the
CONSTRUCTED Ridom-format files and genome of fixtures/spatyper/constructed (no Ridom data).
"""
import shutil
import uuid
from pathlib import Path

import pytest
from arva_tools import amrfinderplus as amr_tool
from arva_tools import registry
from arva_tools.registry import detect
from test_amr_api import species_result
from test_annotation_api import assemble, new_sample

from app.db.session import SessionLocal
from app.models import AmrResult, AnalysisJob, JobStatus, MlstResult, TypingResult
from app.services import typing_modules as tm

API = "/api/v1"
REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures"
SYNTHETIC = REPO / "examples" / "synthetic-genome" / "reference.fasta"
CONSTRUCTED = FIX / "spatyper" / "constructed"
MODULE = "staphylococcus_aureus"
TOOLS = ("sccmec", "spatyper", "agrvate")


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def fake_env(root: Path, genome: str) -> dict[str, Path]:
    """Stand-ins of the three tools replaying their real output on `genome` (n315 or usa300)."""
    sc, sp, ag = FIX / "sccmec", FIX / "spatyper", FIX / "agrvate"
    s_env = root / "sccmec"
    for name in ("sccmec-targets.yaml", "sccmec-regions.yaml", "sccmec-targets.fasta", "sccmec-regions.fasta"):
        (s_env / "share" / "sccmec").mkdir(parents=True, exist_ok=True)
        (s_env / "share" / "sccmec" / name).write_text("CONSTRUCTED stand-in schema file\n")
    _script(s_env / "bin" / "python", 'echo \'{"aliases": [{"name": "ccr Type 2", "targets": ["ccrA2", "ccrB2"]}, '
            '{"name": "mec Class A", "targets": ["IS431", "mecA", "mecR1", "mecI"]}, '
            '{"name": "mec Class B", "targets": ["IS431", "mecA", "mecR1", "IS1272"]}]}\'\n')
    sccmec = _script(s_env / "bin" / "sccmec", f'''
for a in "$@"; do [ "$a" = "--version" ] && {{ printf 'camlhmp, version 1.1.4\\nschema sccmec_targets, version 1.2.0\\n'; exit 0; }}; done
[ "$1" = "--help" ] && {{ cat "{sc}/help_1.2.0.txt"; exit 0; }}
out=""; while [ $# -gt 0 ]; do [ "$1" = "--outdir" ] && out="$2"; shift; done
mkdir -p "$out"
cp "{sc}/{genome}.tsv" "$out/sccmec.tsv"
for f in targets.details.tsv regions.details.tsv targets.blastn.tsv; do cp "{sc}/{genome}.$f" "$out/sccmec.$f"; done
echo "Final Results..." >&2
''')
    spatyper = _script(root / "spatyper" / "bin" / "spaTyper", f'''
[ "$1" = "--help" ] && {{ cat "{sp}/help_0.3.3.txt"; exit 0; }}
out=""; while [ $# -gt 0 ]; do [ "$1" = "--output" ] && out="$2"; shift; done
cp "{sp}/{genome}.spatyper.tsv" "$out"; echo "Results:"
''')
    a_bin = root / "agrvate" / "bin"
    (a_bin / "agrvate_databases" / "references").mkdir(parents=True)
    for name in ("gp1234_all_motifs.fna", "agr_operon_primers.fa", "references/mummer_ref_operon.fna"):
        (a_bin / "agrvate_databases" / name).write_text("CONSTRUCTED stand-in database file\n")
    agrvate = _script(a_bin / "agrvate", f'''
case "$1" in -v) echo "agrvate v1.0.2"; exit 0;; -h) cat "{ag}/help_1.0.2.txt"; exit 0;; esac
mkdir -p contigs-results/contigs-mummer contigs-results/contigs-snippy
cp "{ag}/{genome}.summary.tab" contigs-results/contigs-summary.tab
cp "{ag}/{genome}.agr_gp.tab" contigs-results/contigs-agr_gp.tab
cp "{ag}/{genome}.agr_operon_frameshifts.tab" contigs-results/contigs-agr_operon_frameshifts.tab
cp "{ag}/{genome}.out.1coords" contigs-results/contigs-mummer/out.1coords
cp "{ag}/{genome}.error-report.tab" contigs.fasta-error-report.tab
cat "{ag}/{genome}.stdout.txt"
''')
    return {"sccmec": sccmec, "spatyper": spatyper, "agrvate": agrvate}


@pytest.fixture
def typing_tools(tmp_path, monkeypatch):
    def use(genome: str) -> dict[str, Path]:
        exe = fake_env(tmp_path / genome, genome)
        for tool, path in exe.items():
            monkeypatch.setenv(f"ARVA_TOOL_{tool.upper()}", str(path))
            registry._CACHE.pop(tool, None)
        return exe
    yield use
    for tool in TOOLS:
        registry._CACHE.pop(tool, None)


@pytest.fixture
def no_typing_tools(monkeypatch):
    for tool in TOOLS:
        monkeypatch.setenv(f"ARVA_TOOL_{tool.upper()}", f"/nonexistent/{tool}")
        registry._CACHE.pop(tool, None)
    yield
    for tool in TOOLS:
        registry._CACHE.pop(tool, None)


def register_ridom(client, storage_root: Path) -> dict:
    folder = storage_root / "databases" / f"ridom-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    for f in ("sparepeats.fasta", "spatypes.txt"):
        shutil.copy(CONSTRUCTED / f, folder / f)
    r = client.post(f"{API}/databases/register", json={"path": str(folder), "declared_version": "constructed"})
    assert r.status_code == 201, r.text
    return r.json()


def _job(sample: dict, job_type: str, tool: str, version: str, parameters: dict) -> str:
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type=job_type, tool_name=tool,
                          tool_version=version, parameters=parameters, status=JobStatus.completed, log_text="")
        db.add(job)
        db.commit()
        return job.id


def mlst_result(sample: dict, a: dict, st: str, status: str = "PERFECT") -> None:
    job_id = _job(sample, "mlst_typing", "mlst", "2.35.0", {})
    with SessionLocal() as db:
        db.add(MlstResult(sample_id=sample["id"], assembly_id=a["id"], job_id=job_id, tool="mlst",
                          tool_version="2.35.0", parameters={}, scheme="saureus", st=st, status=status, score=100,
                          alleles=[], clonal_complex={"available": True, "value": None}, warnings=[], details={},
                          files={}))
        db.commit()


def amr_result(sample: dict, a: dict, genome: str, plus: bool = True) -> None:
    """AMRFinderPlus 4.2.7's real report on the genome (fixtures/amrfinderplus/<genome>.tsv) as an amr_detection run."""
    job_id = _job(sample, "amr_detection", "AMRFinderPlus", "4.2.7",
                  {"assembly": {"assembly_id": a["id"]}, "plus": plus})
    rows = amr_tool.parse_report((FIX / "amrfinderplus" / f"{genome}.tsv").read_text())
    with SessionLocal() as db:
        for r in rows:
            if not plus and r["type"] != "AMR":
                continue
            db.add(AmrResult(sample_id=sample["id"], assembly_id=a["id"], job_id=job_id,
                             element_symbol=r["element_symbol"], element_name=r["element_name"], type=r["type"],
                             subtype=r["subtype"], method=r["method"], method_kind=r["method_info"]["kind"],
                             identity=r["identity"], coverage=r["coverage"], contig=r["contig"], start=r["start"],
                             stop=r["stop"], strand=r["strand"]))
        db.commit()


def start(client, a: dict, method: str, **extra) -> dict:
    r = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}", json={"method": method, "confirmed": True, **extra})
    assert r.status_code == 202, r.text
    job = client.get(f"{API}/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job.get("log_text")
    return job


# --- Framework ----------------------------------------------------------------------------------------------------

def test_applicability_rules():
    mod = tm.STAPHYLOCOCCUS_AUREUS
    sa = {"value": "Staphylococcus aureus"}
    ec = {"value": "Escherichia coli"}
    assert tm.applicability(mod, {"species": sa, "mlst": None})["status"] == "applicable"
    assert tm.applicability(mod, {"species": None, "mlst": {"value": "saureus"}})["status"] == "applicable"
    both = tm.applicability(mod, {"species": sa, "mlst": {"value": "saureus"}})
    assert both["status"] == "applicable" and not both["override_required"]
    assert tm.applicability(mod, {"species": sa, "mlst": {"value": "ecoli_achtman_4"}})["status"] == "conflicting"
    other = tm.applicability(mod, {"species": ec, "mlst": None})
    assert other["status"] == "not_applicable" and other["override_required"]
    assert other["checks"] == [{"source": "species", "value": "Escherichia coli", "matches": False}]
    assert tm.applicability(mod, {"species": None, "mlst": None})["status"] == "no_evidence"
    assert [s.key for s in mod.steps] == ["sccmec", "spa", "agr"] and mod.step("spa").database_kind == "spa_types"


def test_modules_list_what_is_missing_and_where_to_get_the_ridom_files(client, no_typing_tools):
    (mod,) = client.get(f"{API}/typing/modules").json()
    assert mod["key"] == MODULE and mod["species"] == ["Staphylococcus aureus"] and mod["mlst_schemes"] == ["saureus"]
    steps = {s["key"]: s for s in mod["requirements"]}
    assert steps["sccmec"]["missing"] == ["tool"] and "conda_locks.py install sccmec" in \
        steps["sccmec"]["tool"]["install"]["conda_lock"]
    assert steps["agr"]["tool"]["platforms"] == ["linux-64"]
    spa = steps["spa"]
    assert spa["missing"] == ["tool", "database"] and spa["database"]["user_provided_only"]
    assert "https://spa.ridom.de/dynamic/spatypes.txt" in spa["database"]["download_note"]
    assert spa["database"]["licence_url"] == "https://spa.ridom.de/policy.shtml"
    assert "non-commercial" in spa["database"]["licence"]


# --- Stand-ins replaying real output --------------------------------------------------------------------------------

def test_usa300_summary_card_shorthand_and_sources(client, storage_root, typing_tools):
    typing_tools("usa300")
    sample = new_sample(client, "USA300")
    a = assemble(client, sample, SYNTHETIC)
    preview = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}/preview", json={"method": "spa"}).json()
    assert preview["applicability"]["status"] == "no_evidence"
    assert [p["code"] for p in preview["problems"]] == ["no_ridom_files"]
    r = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}", json={"method": "sccmec", "confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "typing_not_applicable"
    assert client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}",
                       json={"method": "sccmec", "confirmed": False}).json()["code"] == "typing_confirm"
    r = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}",
                    json={"method": "sccmec", "confirmed": True, "settings": {"min_targets_pident": 0}})
    assert r.status_code == 422 and r.json()["code"] == "typing_settings_invalid"

    species_result(sample, a, "Staphylococcus aureus")
    mlst_result(sample, a, "8")
    amr_result(sample, a, "usa300")
    r = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}", json={"method": "spa", "confirmed": True})
    assert r.status_code == 409 and r.json()["code"] == "typing_blocked" and "Ridom" in r.json()["detail"]
    ridom = register_ridom(client, storage_root)
    preview = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}/preview", json={"method": "spa"}).json()
    assert preview["applicability"]["status"] == "applicable" and preview["database"]["id"] == ridom["id"]
    sccmec_preview = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}/preview",
                                 json={"method": "sccmec"}).json()
    assert sccmec_preview["defaults_match"] is True and sccmec_preview["bundled"]["kind"] == "sccmec_schemas"

    jobs = {m: start(client, a, m) for m in ("sccmec", "spa", "agr")}
    assert jobs["sccmec"]["database_kind"] == "sccmec_schemas" and jobs["sccmec"]["database_checksum"].startswith(
        "sha256:")
    assert jobs["spa"]["database_kind"] == "spa_types" and jobs["spa"]["database_version"] == "constructed"
    assert jobs["agr"]["database_kind"] == "agrvate_databases"
    commands = jobs["sccmec"]["commands"][0]
    assert "--min-regions-coverage" in commands and commands[commands.index("--min-targets-pident") + 1] == "90"
    assert "--mummer" in jobs["agr"]["commands"][0]

    view = client.get(f"{API}/samples/{sample['id']}/typing").json()
    by = {r["method"]: r for r in view["results"]}
    assert (by["sccmec"]["status"], by["sccmec"]["call"]) == ("typed", "IVa")
    assert by["sccmec"]["details"]["ccr_complexes"] == ["ccr Type 2"]
    assert by["sccmec"]["details"]["mec_classes"] == ["mec Class B"]
    assert (by["spa"]["status"], by["spa"]["call"]) == ("typed", "t008")
    assert by["spa"]["details"]["ridom_files"]["types"] == 1
    assert (by["agr"]["status"], by["agr"]["call"]) == ("typed", "I")
    assert by["agr"]["details"]["operon_alignment"]["covered_fraction"] == 1.0
    assert {w["code"] for w in by["agr"]["warnings"]} >= {"agr_mummer_mode", "synthetic_input"}
    assert by["agr"]["applicability"]["status"] == "applicable"

    (assembly,) = view["assemblies"]
    card = assembly["summary"]
    assert card["shorthand"] == "ST8-MRSA-IVa, t008, agr I, PVL+"
    assert card["uncertain"] == [] and card["not_determined"] == []
    assert card["mec_crosscheck"] == {"sccmec": True, "amrfinderplus": True, "status": "agree"}
    assert [g["symbol"] for g in card["amr"]["pvl"]] == ["lukF-PV", "lukS-PV"]
    assert card["amr"]["tst"] == [] and card["amr"]["exfoliative_toxins"] == []
    assert sorted(g["symbol"] for g in card["amr"]["enterotoxins"]) == ["sek", "sel26", "selX", "seq"]
    assert card["sccmec"]["source"]["tool"] == "sccmec" and card["mlst"]["source"]["version"] == "2.35.0"
    assert card["amr"]["source"]["version"] == "4.2.7"

    files = by["sccmec"]["files"]
    assert {"sccmec/sccmec.tsv", "input"} <= set(files)
    got = client.get(f"{API}/typing/runs/{by['sccmec']['job_id']}/files/sccmec/sccmec.tsv")
    assert got.status_code == 200 and got.headers["content-security-policy"].startswith("default-src 'none'")
    assert client.get(f"{API}/typing/runs/{by['sccmec']['job_id']}/files/../../etc/passwd").status_code == 404

    project = client.get(f"{API}/projects/{sample['project_id']}/typing/{MODULE}").json()
    assert project["typed"] == 1 and project["samples"][0]["summary"]["shorthand"] == card["shorthand"]
    text = client.get(f"{API}/projects/{sample['project_id']}/typing/{MODULE}.csv").text
    assert "ST8-MRSA-IVa, t008, agr I, PVL+" in text and "lukF-PV(complete)" in text
    assert client.get(f"{API}/projects/{sample['project_id']}/typing/klebsiella").status_code == 404

    html = client.get(f"{API}/samples/{sample['id']}/report?format=html").text
    assert "Staphylococcus aureus typing" in html and "ST8-MRSA-IVa, t008, agr I, PVL+" in html
    assert "spaserver.ridom.de" in html
    csv_text = client.get(f"{API}/samples/{sample['id']}/report?format=csv").text
    assert "typing_summary" in csv_text and ",t008," in csv_text


def test_n315_summary_marks_disputed_and_unsearched_parts(client, storage_root, typing_tools):
    typing_tools("n315")
    sample = new_sample(client, "N315")
    a = assemble(client, sample, SYNTHETIC)
    mlst_result(sample, a, "5", status="NOVEL")
    start(client, a, "sccmec")
    start(client, a, "agr")
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]["summary"]
    assert card["shorthand"] == "ST5?-MRSA-IIa, agr II"
    assert card["uncertain"] == [{"part": "st", "reason": "mlst_status", "params": {"status": "NOVEL"}}]
    assert card["not_determined"] == ["spa", "amr"] and card["mec_crosscheck"]["status"] == "unavailable"
    agr = card["agr"]
    assert agr["details"]["operon_alignment"]["covered_fraction"] == 0.6436
    assert "agr_operon_partial" in {w["code"] for w in agr["warnings"]}

    amr_result(sample, a, "n315", plus=False)
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]["summary"]
    assert card["amr"]["pvl"] is None and card["amr"]["tst"] is None
    assert card["shorthand"] == "ST5?-MRSA-IIa, agr II" and card["mec_crosscheck"]["status"] == "agree"
    amr_result(sample, a, "n315")
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]["summary"]
    assert card["shorthand"] == "ST5?-MRSA-IIa, agr II, PVL-"
    assert [g["symbol"] for g in card["amr"]["tst"]] == ["tst"]
    sen = next(g for g in card["amr"]["enterotoxins"] if g["symbol"] == "sen")
    assert sen["method_kind"] == "internal_stop"
    register_ridom(client, storage_root)
    start(client, a, "spa")
    mlst_result(sample, a, "5")
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]["summary"]
    assert card["shorthand"] == "ST5-MRSA-IIa, t002, agr II, PVL-" and card["uncertain"] == []


def test_a_module_the_evidence_contradicts_runs_only_with_an_override(client, typing_tools):
    typing_tools("n315")
    sample = new_sample(client, "ECOLI")
    a = assemble(client, sample, SYNTHETIC)
    species_result(sample, a, "Escherichia coli")
    r = client.post(f"{API}/assemblies/{a['id']}/typing/{MODULE}", json={"method": "agr", "confirmed": True})
    assert r.status_code == 409 and "not_applicable" in r.json()["detail"]
    start(client, a, "agr", override_applicability=True)
    (res,) = client.get(f"{API}/samples/{sample['id']}/typing").json()["results"]
    assert res["applicability"]["status"] == "not_applicable"
    assert "applicability_overridden" in {w["code"] for w in res["warnings"]}
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]
    assert card["applicability"][MODULE]["status"] == "not_applicable"


def test_mssa_needs_amrfinderplus_and_a_disagreement_is_marked(client, typing_tools):
    typing_tools("n315")
    sample = new_sample(client, "MEC")
    a = assemble(client, sample, SYNTHETIC)
    species_result(sample, a, "Staphylococcus aureus")
    amr_result(sample, a, "synthetic")
    start(client, a, "agr")
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]["summary"]
    assert card["shorthand"] == "MSSA, agr II, PVL-"
    start(client, a, "sccmec")
    card = client.get(f"{API}/samples/{sample['id']}/typing").json()["assemblies"][0]["summary"]
    assert card["mec_crosscheck"] == {"sccmec": True, "amrfinderplus": False, "status": "disagree"}
    assert card["shorthand"] == "MSSA?, agr II, PVL-"
    assert {"part": "mec", "reason": "mec_disagree", "params": {}} in card["uncertain"]


def test_typing_results_migration_up_and_down(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app.core.config import get_settings
    from app.db.session import engine

    url = make_url(get_settings().database_url)
    scratch = url.set(database="arva_migration_scratch_typing")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_typing"))
        conn.execute(text("CREATE DATABASE arva_migration_scratch_typing"))
    monkeypatch.setattr(get_settings(), "database_url", scratch.render_as_string(hide_password=False))
    api_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    db = create_engine(scratch)
    try:
        command.upgrade(cfg, "head")
        with db.begin() as c:
            fks = dict(c.execute(text("SELECT conname, confdeltype FROM pg_constraint WHERE conrelid = "
                                      "'typing_results'::regclass AND contype = 'f'")).all())
            assert fks == {"fk_typing_results_sample_id": "c", "fk_typing_results_assembly_id": "c",
                           "fk_typing_results_job_id": "c"}
        command.downgrade(cfg, "f5a8c3d1b7e9")
        with db.begin() as c:
            assert c.execute(text("SELECT to_regclass('typing_results')")).scalar() is None
        command.upgrade(cfg, "head")
    finally:
        db.dispose()
        with admin.connect() as conn:
            conn.execute(text("DROP DATABASE IF EXISTS arva_migration_scratch_typing"))


# --- Real tools ---------------------------------------------------------------------------------------------------

def _real(*tools: str) -> None:
    for tool in tools:
        registry._CACHE.pop(tool, None)
        if detect(tool, refresh=True).path is None:
            pytest.skip(f"{tool} is not installed")


def test_real_spatyper_types_the_constructed_genome_with_the_constructed_ridom_files(client, storage_root):
    _real("spatyper")
    register_ridom(client, storage_root)
    sample = new_sample(client, "SPA-C")
    a = assemble(client, sample, CONSTRUCTED / "lower_case.fasta")
    mlst_result(sample, a, "8")
    start(client, a, "spa")
    (res,) = client.get(f"{API}/samples/{sample['id']}/typing").json()["results"]
    assert (res["status"], res["call"], res["details"]["repeats"]) == ("typed", "t9001", "91-92-93")
    assert "uppercased_input" in {w["code"] for w in res["warnings"]}


def test_real_sccmec_and_agrvate_on_the_synthetic_genome(client):
    _real("sccmec", "agrvate")
    sample = new_sample(client, "SYN-T")
    a = assemble(client, sample, SYNTHETIC)
    start(client, a, "sccmec", override_applicability=True)
    start(client, a, "agr", override_applicability=True)
    view = client.get(f"{API}/samples/{sample['id']}/typing").json()
    by = {r["method"]: r for r in view["results"]}
    assert (by["sccmec"]["status"], by["sccmec"]["call"]) == ("not_typeable", None)
    assert (by["agr"]["status"], by["agr"]["call"]) == ("untypeable", None)
    assert by["agr"]["details"]["frameshifts"] is None
    assert view["assemblies"][0]["summary"]["shorthand"] is None
    with SessionLocal() as db:
        assert db.query(TypingResult).filter(TypingResult.sample_id == sample["id"]).count() == 2
