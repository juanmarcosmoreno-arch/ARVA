"""ARVA Discover over stored results, the full project report (HTML/JSON/CSV/PDF, EN/ES) and the ARVA Assist
integration point with a fake provider (no provider is bundled or called)."""
import stat
from typing import ClassVar

import pytest
from scipy import stats as scipy_stats

from app.db.session import SessionLocal
from app.models import (
    AmrResult,
    AnalysisJob,
    Assembly,
    AssemblyKind,
    AssemblyMode,
    AssistRequest,
    JobStatus,
)
from app.services import assist
from app.services import project_report as pr
from app.services.jobs import AMR_JOB

# 8 samples: blaZ in the 4 cattle samples and one human sample; mecA everywhere but one; S8 never searched.
HOSTS = ["cattle"] * 4 + ["human"] * 3 + ["human"]
GENES = [{"blaZ", "mecA"}, {"blaZ", "mecA"}, {"blaZ", "mecA"}, {"blaZ"}, {"blaZ", "mecA"}, {"mecA"}, {"mecA"}, None]
ST = ["8", "8", "8", "8", "5", "5", "5", "5"]


def _amr(sample: dict, genes: set[str]) -> None:
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="flye_assembly",
                          tool_name="Flye", tool_version="2.9.3", parameters={}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        db.add(job)
        db.flush()
        a = Assembly(sample_id=sample["id"], job_id=job.id, kind=AssemblyKind.assembly, assembler="Flye",
                     assembler_version="2.9.3", mode=AssemblyMode.long, read_type="nano-hq", input_file_ids=[],
                     contigs_path="x.fasta", stats={"contig_count": 2, "total_length": 2_800_000, "n50": 2_700_000,
                                                    "gc_percent": 32.8}, contigs=[], warnings=[])
        db.add(a)
        db.flush()
        amr = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type=AMR_JOB,
                          tool_name="AMRFinderPlus", tool_version="4.0.23", database_name="AMRFinderPlus",
                          database_version="2026-08-07.1", parameters={"assembly": {"assembly_id": a.id}},
                          input_raw_file_ids=[], status=JobStatus.completed, log_text="")
        db.add(amr)
        db.flush()
        for g in genes:
            db.add(AmrResult(sample_id=sample["id"], assembly_id=a.id, job_id=amr.id, element_symbol=g,
                             type="AMR", subtype="AMR", amr_class="BETA-LACTAM", method="EXACTX",
                             method_kind="complete"))
        db.commit()


@pytest.fixture
def project(client):
    pid = client.post("/api/v1/projects", json={"name": "Discover", "researcher": "Dr Private"}).json()["id"]
    samples = []
    for i, host in enumerate(HOSTS):
        s = client.post(f"/api/v1/projects/{pid}/samples", json={
            "sample_code": f"S{i + 1}", "host": host, "geographic_origin": "Peru",
            "custom_metadata": {"st_label": ST[i], "penicillin": "R" if GENES[i] and "blaZ" in GENES[i] else "S"},
        }).json()
        samples.append(s)
        if GENES[i] is not None:
            _amr(s, GENES[i])
    return pid, samples


def test_discover_summary_marks_unsearched_samples(client, project):
    pid, _ = project
    s = client.get(f"/api/v1/projects/{pid}/discover").json()
    assert s["samples"] == 8 and s["label"] == "exploratory, not confirmatory"
    feats = {f["name"]: f for f in s["features"]}
    assert feats["amr:blaZ"] == {"name": "amr:blaZ", "source": "amr", "with": 5, "searched": 7}
    assert {"not_causal", "phylogenetic_dependence", "multiple_testing"} <= set(s["caveats"])
    assert s["provenance"]["amr"]["searched"] == 7
    assert any(f["name"] == "meta:penicillin" for f in s["fields"])


def test_discover_association_matches_scipy_and_is_stratified(client, project):
    pid, _ = project
    r = client.get(f"/api/v1/projects/{pid}/discover/analysis", params={
        "analysis": "associations", "group": "host", "lineage": "meta:st_label", "sources": ["amr"]}).json()
    row = next(x for x in r["rows"] if x["group"] == "cattle" and x["feature"] == "amr:blaZ")
    # cattle: 4/4 blaZ; human (searched): 1/3; the unsearched S8 is left out.
    assert row["table"] == [4, 0, 1, 2] and row["samples"] == 7
    assert row["p"] == pytest.approx(scipy_stats.fisher_exact([[4, 0], [1, 2]]).pvalue, rel=1e-3)
    assert row["difference_ci"] is not None and row["odds_ratio_ci"] is not None and "q" in row
    assert row["stratified"]["informative_strata"] == 0  # host and ST are fully confounded here
    assert r["label"] == "exploratory, not confirmatory" and r["stratified_by_lineage"]
    csv_text = client.get(f"/api/v1/projects/{pid}/discover/analysis.csv", params={
        "analysis": "associations", "group": "host"}).text
    assert csv_text.startswith("# ARVA Discover: associations. Exploratory, not confirmatory.")
    bad = client.get(f"/api/v1/projects/{pid}/discover/analysis", params={"analysis": "associations"})
    assert bad.status_code == 400 and bad.json()["code"] == "discover_group_required"


def test_discover_other_analyses(client, project):
    pid, _ = project
    q = f"/api/v1/projects/{pid}/discover/analysis"
    co = client.get(q, params={"analysis": "cooccurrence", "sources": ["amr"]}).json()
    assert co["pairs_tested"] == 1 and co["rows"][0]["samples"] == 7
    lin = client.get(q, params={"analysis": "lineage", "lineage": "meta:st_label"}).json()
    assert {x["lineage"] for x in lin["lineages"]} == {"5", "8"}
    pca = client.get(q, params={"analysis": "pca", "one_hot": ["host"]}).json()
    assert pca["applicable"] and len(pca["samples"]) == 7
    heat = client.get(q, params={"analysis": "heatmap"}).json()
    assert len(heat["sample_order"]) == 7 and heat["note"].endswith("not a phylogeny")


def test_project_report_formats_and_languages(client, project):
    pid, _ = project
    html = client.get(f"/api/v1/projects/{pid}/report", params={"format": "html"}).text
    assert "Project report" in html and "blaZ" in html and "not searched" in html and 'lang="en"' in html
    assert "Dr Private" not in html
    es = client.get(f"/api/v1/projects/{pid}/report", params={"format": "html", "lang": "es"}).text
    assert 'lang="es"' in es and "Informe del proyecto" in es and "no buscado" in es and "Limitaciones" in es
    data = client.get(f"/api/v1/projects/{pid}/report", params={"format": "json"}).json()
    assert data["counts"]["amr_searched"] == 7
    assert any(m["tool"] == "AMRFinderPlus" and m["citation"] for m in data["methods"])
    csv_text = client.get(f"/api/v1/projects/{pid}/report", params={"format": "csv"}).text
    assert csv_text.splitlines()[0].startswith("sample,organism,host")
    assert "not searched" in csv_text
    if not pr.pdf_available():
        pytest.skip("WeasyPrint is not installed")
    pdf = client.get(f"/api/v1/projects/{pid}/report", params={"format": "pdf", "lang": "es"})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-")


def test_report_label_catalogues_have_the_same_keys():
    assert set(pr.LABELS["en"]) == set(pr.LABELS["es"])
    assert all(pr.LABELS["es"][k] for k in pr.LABELS["en"])
    assert len(pr.LIMITATIONS["en"]) == len(pr.LIMITATIONS["es"])


def test_pdf_renderer_fetches_nothing():
    if not pr.pdf_available():
        pytest.skip("WeasyPrint is not installed")
    with pytest.raises(ValueError):
        pr._no_fetch("https://example.org/x.png")
    assert pr.render_pdf('<img src="https://example.org/x.png"><p>ok</p>').startswith(b"%PDF-")


class FakeProvider:
    calls: ClassVar[list] = []

    def ask(self, payload, config):
        FakeProvider.calls.append((payload, config))
        return "Observed: blaZ was found in 5 of 7 searched samples."


@pytest.fixture
def fake_provider():
    FakeProvider.calls = []
    assist.register("fake", FakeProvider)
    yield FakeProvider
    assist.unregister("fake")


def test_assist_is_off_by_default_and_sends_nothing(client, project):
    pid, _ = project
    assert client.get("/api/v1/assist/status").json()["enabled"] is False
    r = client.post("/api/v1/assist/ask", json={"question": "What is N50?", "about_project_id": pid})
    assert r.status_code == 409 and r.json()["code"] == "assist_disabled"
    assert client.get("/api/v1/assist/audit").json() == []


def test_assist_settings_validate_and_keep_the_key_private(client, fake_provider, storage_root):
    r = client.put("/api/v1/assist/settings", json={"enabled": True, "provider": "missing"})
    assert r.json()["code"] == "assist_no_provider"
    r = client.put("/api/v1/assist/settings", json={"enabled": True, "provider": "fake",
                                                    "endpoint": "http://example.org/v1"})
    assert r.json()["code"] == "assist_endpoint_invalid"
    r = client.put("/api/v1/assist/settings", json={"enabled": True, "provider": "fake",
                                                    "endpoint": "http://127.0.0.1:8080/v1", "api_key": "sk-secret"})
    view = r.json()
    assert view["key_set"] and view["endpoint_is_local"] and "sk-secret" not in r.text
    key = storage_root / "secrets" / assist.KEY_FILE
    assert stat.S_IMODE(key.stat().st_mode) == 0o600 and key.read_text() == "sk-secret"
    assert "sk-secret" not in client.get("/api/v1/assist/settings").text
    client.put("/api/v1/assist/settings", json={"enabled": False, "clear_key": True})
    assert not key.exists()


def test_assist_sends_real_data_only_with_consent_and_logs_it(client, project, fake_provider):
    pid, _ = project
    client.put("/api/v1/assist/settings", json={"enabled": True, "provider": "fake",
                                                "endpoint": "https://assist.example.org", "api_key": "k"})
    body = {"question": "Which samples carry blaZ?", "about_project_id": pid,
            "guide": [{"id": "amr", "title": "AMR genes", "text": "AMRFinderPlus reports ..."}]}
    preview = client.post("/api/v1/assist/preview", json=body).json()["payload"]
    assert preview["sequences"] == [] and fake_provider.calls == []
    assert "Dr Private" not in str(preview) and "researcher" not in preview["data"]["project"]
    r = client.post("/api/v1/assist/ask", json=body).json()
    assert r["answer"].startswith("Observed:") and not r["included_sequences"]
    sent, config = fake_provider.calls[0]
    assert config.api_key == "k" and sent["question"] == body["question"]
    s1 = next(s for s in sent["data"]["samples"] if s["code"] == "S1")
    assert s1["amr"]["genes"] == ["blaZ", "mecA"]
    s8 = next(s for s in sent["data"]["samples"] if s["code"] == "S8")
    assert s8["amr"] is None
    log = client.get("/api/v1/assist/audit").json()
    assert len(log) == 1 and log[0]["sent"] == sent and log[0]["endpoint_host"] == "assist.example.org"
    refused = client.post("/api/v1/assist/ask", json={**body, "sequence_refs": [{"annotation_id": "x",
                                                                                   "feature_id": "1"}]})
    assert refused.status_code == 400 and refused.json()["code"] == "assist_sequence_consent"
    with SessionLocal() as db:
        assert db.query(AssistRequest).count() == 1


def test_assist_provider_failure_is_logged_not_raised(client, project, fake_provider, monkeypatch):
    pid, _ = project
    client.put("/api/v1/assist/settings", json={"enabled": True, "provider": "fake"})

    def boom(self, payload, config):
        raise TimeoutError("down")

    monkeypatch.setattr(FakeProvider, "ask", boom)
    r = client.post("/api/v1/assist/ask", json={"question": "Hi", "about_project_id": pid})
    assert r.status_code == 502 and r.json()["code"] == "assist_provider_failed"
    assert client.get("/api/v1/assist/audit").json()[0]["status"] == "failed"
