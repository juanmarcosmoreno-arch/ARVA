from pathlib import Path

import pytest

from arva_core import pangenome as p

FIXTURES = Path(__file__).resolve().parents[2] / "workflows" / "tool-adapters" / "tests" / "fixtures" / "pangenome"
# Families x genomes: f1 in all, f2 in g1-g3, f3 in g4 only, f4 in g1 and g2, f5 in nobody.
PRESENCE = [[1, 1, 1, 1], [1, 1, 1, 0], [0, 0, 0, 1], [1, 1, 0, 0], [0, 0, 0, 0]]


def test_rtab_parses_and_rejects_malformed_tables():
    t = p.parse_rtab("Gene\tg1\tg2\nfamA\t1\t0\nfamB\t2\t1\n")
    assert t == {"genomes": ["g1", "g2"], "families": ["famA", "famB"], "presence": [[1, 0], [1, 1]]}
    for bad in ("", "Name\tg1\nf\t1\n", "Gene\tg1\tg2\nf\t1\n", "Gene\tg1\nf\tx\n", "Gene\tg1\nf\t1\nf\t0\n"):
        with pytest.raises(ValueError):
            p.parse_rtab(bad)


def test_real_panaroo_matrix_reproduces_panaroos_own_summary():
    """Panaroo 1.8.1 on five S. aureus genomes: ARVA's categories with Panaroo's thresholds give its numbers."""
    t = p.parse_rtab((FIXTURES / "gene_presence_absence.Rtab").read_text())
    s = p.summary(t["presence"], p.DEFAULT_THRESHOLDS)
    expected = {}
    for line in (FIXTURES / "summary_statistics.txt").read_text().splitlines():
        name, _range, count = line.split("\t")
        expected[name] = int(count)
    assert s["category_counts"] == {"core": expected["Core genes"], "soft_core": expected["Soft core genes"],
                                    "shell": expected["Shell genes"], "cloud": expected["Cloud genes"]}
    assert s["families"] == expected["Total genes"] == 3090
    assert p.frequency_distribution(s["counts"], 5) == [
        {"genomes": 1, "families": 332}, {"genomes": 2, "families": 239}, {"genomes": 3, "families": 167},
        {"genomes": 4, "families": 42}, {"genomes": 5, "families": 2310}]
    assert sum(s["unique_per_genome"]) == 332


def test_categories_follow_the_thresholds_given():
    t = {"core": 1.0, "soft_core": 0.75, "shell": 0.5}
    s = p.summary(PRESENCE, t)
    assert s["counts"] == [4, 3, 1, 2, 0]
    assert s["categories"] == ["core", "soft_core", "cloud", "shell", "cloud"]
    assert s["absent_families"] == 1
    assert s["families_per_genome"] == [3, 3, 2, 2] and s["unique_per_genome"] == [0, 0, 0, 1]
    with pytest.raises(ValueError):
        p.summary(PRESENCE, {"core": 0.9, "soft_core": 0.95, "shell": 0.15})


def test_accumulation_is_reproducible_and_bounded():
    a = p.accumulation(PRESENCE, 50, 7)
    assert a == p.accumulation(PRESENCE, 50, 7)
    assert a["k"] == [1, 2, 3, 4]
    assert a["pan"]["mean"][-1] == 4 and a["core"]["mean"][-1] == 1
    assert a["pan"]["min"][0] == 2 and a["pan"]["max"][0] == 3
    assert all(x <= y for x, y in zip(a["pan"]["mean"], a["pan"]["mean"][1:], strict=False))
    assert all(x >= y for x, y in zip(a["core"]["mean"], a["core"]["mean"][1:], strict=False))


def test_genome_clustering_uses_jaccard_and_says_it_is_not_a_phylogeny():
    c = p.genome_clustering(PRESENCE)
    assert c["distances"][0][1] == 0.0 and c["distances"][0][3] == pytest.approx(0.75)
    assert abs(c["order"].index(0) - c["order"].index(1)) == 1 and c["merges"][0][:3] == [0, 1, 0.0]
    assert "Jaccard" in c["method"]
    assert p.family_order(PRESENCE, [0, 1, 2, 3]) == [0, 1, 3, 2, 4]


def test_fisher_exact_matches_known_values():
    assert p.fisher_exact(3, 1, 1, 3) == pytest.approx(0.485714, abs=1e-6)
    assert p.fisher_exact(1, 9, 11, 3) == pytest.approx(0.0027594, abs=1e-7)
    assert p.fisher_exact(0, 5, 5, 0) == pytest.approx(2 / 252)
    assert p.benjamini_hochberg([0.01, 0.04, 0.03, 0.5]) == pytest.approx([0.04, 0.05333, 0.05333, 0.5], abs=1e-4)
    lo, hi = p.wilson(0, 5)
    assert lo == 0 and hi == pytest.approx(0.4345, abs=1e-4)
    o = p.odds_ratio(5, 0, 0, 5)
    assert o["haldane_corrected"] and o["odds_ratio"] == pytest.approx(121)


def test_groups_and_associations():
    groups = ["human", "human", "cow", None]
    g = p.group_statistics(PRESENCE, groups)
    assert g == [{"group": "cow", "genomes": 1, "pan": 2, "core": 2, "exclusive": 0, "families_mean": 2.0,
                  "families_sd": None},
                 {"group": "human", "genomes": 2, "pan": 3, "core": 3, "exclusive": 1, "families_mean": 3.0,
                  "families_sd": 0.0}]
    a = p.associations(PRESENCE, ["f1", "f2", "f3", "f4", "f5"], groups, 1)
    assert a["genomes_with_value"] == 3 and a["genomes_without_value"] == 1
    assert a["families_tested"] == 1 and a["tests"] == 2
    assert {r["family"] for r in a["rows"]} == {"f4"}
    skipped = p.associations(PRESENCE, ["f1", "f2", "f3", "f4", "f5"], groups, 2)
    assert skipped["tests"] == 0 and {s["group"] for s in skipped["skipped_groups"]} == {"cow", "human"}
