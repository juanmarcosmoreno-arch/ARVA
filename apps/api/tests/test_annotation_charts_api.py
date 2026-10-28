"""The annotation charts' numbers, from Prokka's real output on the SYNTHETIC fixture genome
(test_annotation_api.prokka_fixture_annotation). The genome is synthetic: the numbers describe the tool on test
data, not biology."""
import pytest
from test_annotation_api import API, prokka_fixture_annotation, setup  # noqa: F401  (setup is a fixture)

from app.db.session import SessionLocal
from app.models import Annotation

CHR, PLASMID = "SYNTHETIC_annotation_chromosome", "SYNTHETIC_annotation_plasmid"


@pytest.fixture
def ann_id(client, setup, storage_root):  # noqa: F811
    sample, assembly = setup
    ann_id = prokka_fixture_annotation(storage_root, sample, assembly)
    with SessionLocal() as db:
        db.get(Annotation, ann_id).steps = {"cds": {"run": True, "status": "searched", "found": 18}}
        db.commit()
    return ann_id


def test_chart_numbers_count_the_annotators_features(client, ann_id):
    r = client.get(f"{API}/annotations/{ann_id}/charts").json()
    # 18 CDS (3 with a product, 15 "hypothetical protein"), 1 tRNA, 1 rRNA; 16 CDS on the chromosome, 2 on the plasmid
    assert r["genes"] == 20 and r["types"]["total"] == {"cds": 18, "trna": 1, "rrna": 1}
    assert r["hypothetical"]["total"] == {"characterised": 3, "hypothetical": 15}
    assert [(x["characterised"], x["hypothetical"]) for x in r["hypothetical"]["by_contig"]] == [(3, 13), (0, 2)]
    assert r["strand"]["total"] == {"+": 13, "-": 7, ".": 0} and r["strand"]["replication_strand"] == "not_determined"
    # Prokka reports COG identifiers (3 CDS) but no categories; ARVA does not assign any
    assert r["cog"]["reported"] is False and r["cog"]["cds_with_cog_id"] == 3 and r["cog"]["categories"] == []
    lengths = r["lengths"]
    assert lengths["classes"]["cds_characterised"] == {"n": 3, "min": 564, "median": 819, "mean": 744.0, "max": 849}
    assert lengths["classes"]["rna"]["n"] == 2 and lengths["width"] == 50
    assert sum(b["cds_hypothetical"] for b in lengths["bins"]) == 15
    density = r["density"]
    # the longest sequence (17,516 bp) / 100 windows = 175 bp, so the 1 kb minimum applies
    assert density["window"] == 1_000 and [c["genes"] for c in density["contigs"]] == [18, 2]
    assert density["contigs"][0]["end"][-1] == 17_516 and len(density["contigs"][0]["total"]) == 18


def test_chart_options_and_a_run_without_cds(client, ann_id):
    url = f"{API}/annotations/{ann_id}/charts"
    r = client.get(url, params={"length_bin": 500, "window": 5_000}).json()
    assert r["lengths"]["width"] == 500 and r["density"]["window"] == 5_000
    # middle bases: 750, 2069, 2464 (tRNA), 2777, 3885 | 5178 (rRNA), 7201, 8792, 9688 | 10213 ... 14529 | 15634, 16880
    assert [c["total"] for c in r["density"]["contigs"]] == [[5, 4, 7, 2], [2]]
    assert client.get(url, params={"window": 50}).status_code == 422
    assert client.get(url, params={"length_bin": 0}).status_code == 422
    with SessionLocal() as db:
        db.get(Annotation, ann_id).steps = {"cds": {"run": False, "reason": "dependency", "status": "skipped"}}
        db.commit()
    skipped = client.get(url).json()
    assert skipped["cds_searched"] is False and skipped["hypothetical"]["total"] is None and skipped["cog"]["cds"] is None
    assert client.get(f"{API}/annotations/nope/charts").status_code == 404


HOSTILE = '<img src=x onerror="alert(1)">'


def test_report_draws_the_map_and_the_chart_numbers_with_escaped_names(client, setup, ann_id, storage_root):  # noqa: F811
    sample, _ = setup
    import shutil

    from test_annotation_api import GENOME

    with SessionLocal() as db:
        a = db.get(Annotation, ann_id)
        rel = a.features_path.rsplit("/", 1)[0] + "/prokka/annotation.fna"
        shutil.copyfile(GENOME, storage_root / rel)
        a.files = {**a.files, "fna": {"path": rel, "sha256": "-", "size_bytes": 1}}
        # the assembler's name of the plasmid as a hostile string: names reach the figure and the tables
        a.sequences = [a.sequences[0], {**a.sequences[1], "original_id": HOSTILE}]
        db.commit()
    html = client.get(f"{API}/samples/{sample['id']}/report").text
    assert "<h4>Genome map</h4>" in html and 'aria-label="Circular map of ANN-1"' in html
    assert HOSTILE not in html and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "<h4>Annotation charts: the numbers</h4>" in html and "Gene orientation" in html
    assert "none reported by the annotator (3 CDS carry a COG identifier without a category)" in html
    assert "No coverage ring: no_alignment" in html and "come with Phase 5" in html
    report = client.get(f"{API}/samples/{sample['id']}/report", params={"format": "json"}).json()
    (entry,) = report["annotations"]
    assert "map_svg" not in entry and entry["figures_unavailable"] == []
    assert entry["charts"]["hypothetical"]["total"] == {"characterised": 3, "hypothetical": 15}
    m = entry["map"]
    # the report's map has about 720 windows: 18,960 / 720 = 26.3 bp -> 50 bp
    assert m["gc_window"] == 50 and m["features"] == 20 and m["coverage"]["available"] is False
    assert [s["contig_in_assembly"] for s in m["sequences"]] == [CHR, HOSTILE]
    # Prokka reports no topology and this test assembly records no circularity flag
    assert {(s["topology"], s["topology_source"]) for s in m["sequences"]} == {(None, None)}
    assert "<td>not reported</td>" in html


def test_report_says_why_the_map_is_missing(client, setup, ann_id):  # noqa: F811
    sample, _ = setup
    html = client.get(f"{API}/samples/{sample['id']}/report").text
    assert "Not drawn:" in html and "circular map:" in html and ".fna" in html
    assert "<h4>Annotation charts: the numbers</h4>" in html
