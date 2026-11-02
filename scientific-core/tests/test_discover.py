import math

import numpy as np
import pytest

from arva_core import discover as dv
from arva_core import stats as st

scipy_stats = pytest.importorskip("scipy.stats")
hierarchy = pytest.importorskip("scipy.cluster.hierarchy")

TABLES = [(3, 1, 1, 3), (1, 9, 11, 3), (0, 5, 5, 0), (7, 2, 3, 12), (10, 0, 4, 6), (2, 8, 2, 8), (12, 5, 1, 9)]


@pytest.mark.parametrize("t", TABLES)
def test_fisher_matches_scipy(t):
    a, b, c, d = t
    assert st.fisher_exact(a, b, c, d) == pytest.approx(scipy_stats.fisher_exact([[a, b], [c, d]]).pvalue, rel=1e-9)


def test_benjamini_hochberg_matches_scipy():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    assert st.benjamini_hochberg(p) == pytest.approx(list(scipy_stats.false_discovery_control(p, method="bh")))


@pytest.mark.parametrize("k,n", [(0, 5), (3, 10), (10, 10), (17, 40)])
def test_wilson_matches_scipy(k, n):
    ci = scipy_stats.binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson")
    assert st.wilson(k, n) == pytest.approx((ci.low, ci.high), abs=1e-12)


@pytest.mark.parametrize("t", [(7, 2, 3, 12), (12, 5, 1, 9), (2, 8, 2, 8)])
def test_sample_odds_ratio_and_woolf_interval_match_scipy(t):
    a, b, c, d = t
    ref = scipy_stats.contingency.odds_ratio([[a, b], [c, d]], kind="sample")
    ci = ref.confidence_interval(0.95)
    o = st.odds_ratio(a, b, c, d)
    assert o["odds_ratio"] == pytest.approx(ref.statistic)
    assert (o["ci_low"], o["ci_high"]) == pytest.approx((ci.low, ci.high), rel=1e-6)


def test_newcombe_hybrid_score_interval_matches_the_published_example():
    # Newcombe (1998) Stat Med 17:873, table II, example (a): 56/70 - 48/80, method 10: 0.0524 to 0.3339.
    r = st.proportion_difference(56, 70, 48, 80)
    assert r["difference"] == pytest.approx(0.2)
    assert (round(r["ci_low"], 4), round(r["ci_high"], 4)) == (0.0524, 0.3339)


def test_cmh_matches_r_mantelhaen_on_ucb_admissions():
    # R: mantelhaen.test(UCBAdmissions): X-squared = 1.4269, p = 0.2323 (correct = FALSE: 1.5246, p = 0.2169),
    # common odds ratio 0.9046968, 95 % CI 0.7719074 to 1.0603298.
    # Each department as [[admitted male, admitted female], [rejected male, rejected female]] (R's x[, , k]).
    ucb = [(512, 89, 313, 19), (353, 17, 207, 8), (120, 202, 205, 391), (138, 131, 279, 244), (53, 94, 138, 299),
           (22, 24, 351, 317)]
    r = st.mantel_haenszel(ucb)
    assert r["statistic"] == pytest.approx(1.4269, abs=1e-4)
    assert r["p"] == pytest.approx(0.2323, abs=1e-4)
    raw = st.mantel_haenszel(ucb, correct=False)
    assert (raw["statistic"], raw["p"]) == pytest.approx((1.5246, 0.2169), abs=1e-4)
    assert r["odds_ratio"] == pytest.approx(0.9046968, abs=1e-7)
    assert (r["ci_low"], r["ci_high"]) == pytest.approx((0.7719074, 1.0603298), abs=1e-7)
    assert r["informative_strata"] == 6


def test_cmh_leaves_out_uninformative_strata():
    r = st.mantel_haenszel([(1, 0, 0, 0), (2, 3, 0, 0), (0, 0, 1, 2)])
    assert r["strata"] == 2 and r["informative_strata"] == 0 and r["p"] is None


def test_chi2_sf_matches_scipy():
    for x in (0.0, 0.5, 3.841458820694124, 12.0):
        assert st.chi2_sf_1df(x) == pytest.approx(scipy_stats.chi2.sf(x, 1), rel=1e-9)


def _features():
    # 10 samples; geneA follows the host "cattle", geneB is everywhere but sample 9, geneC is not searched in 0-1.
    return {
        "geneA": [1, 1, 1, 1, 0, 0, 0, 0, 0, 1],
        "geneB": [1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
        "geneC": [None, None, 1, 0, 1, 0, 1, 0, 1, 0],
    }


def test_associations_counts_tests_and_effects():
    hosts = ["cattle"] * 5 + ["human"] * 4 + [None]
    r = dv.associations(_features(), hosts, min_group=2)
    assert r["samples_with_value"] == 9 and r["samples_without_value"] == 1 and r["label"] == dv.LABEL
    assert r["skipped_groups"] == [{"group": "human", "samples": 4, "mirror_of": "cattle"}]
    assert {x["group"] for x in r["rows"]} == {"cattle"}
    a = next(x for x in r["rows"] if x["group"] == "cattle" and x["feature"] == "geneA")
    assert a["table"] == [4, 1, 0, 4] and a["samples"] == 9
    assert a["p"] == pytest.approx(scipy_stats.fisher_exact([[4, 1], [0, 4]]).pvalue, rel=1e-3)
    assert a["haldane_corrected"] and a["share_1"] == 0.8 and a["share_2"] == 0.0
    c = next(x for x in r["rows"] if x["group"] == "cattle" and x["feature"] == "geneC")
    assert c["samples"] == 7  # not-searched samples are left out, not counted as absent
    assert not any(x["feature"] == "geneB" for x in r["rows"])  # geneB does not vary among samples with a host
    assert all(x["q"] >= x["p"] for x in r["rows"])


def test_associations_skip_small_groups_and_stratify_by_lineage():
    hosts = ["cattle"] * 5 + ["human"] * 4 + ["dog"]
    lineages = ["ST1", "ST1", "ST1", "ST1", "ST2", "ST2", "ST2", "ST2", "ST2", None]
    r = dv.associations(_features(), hosts, min_group=2, strata=lineages)
    assert r["skipped_groups"] == [{"group": "dog", "samples": 1}]
    a = next(x for x in r["rows"] if x["group"] == "cattle" and x["feature"] == "geneA")
    # Every cattle sample with geneA is ST1, every ST1 sample is cattle: host and lineage are fully confounded.
    assert a["stratified"]["informative_strata"] == 0 and a["stratified"]["p"] is None


def test_cooccurrence_pairs_and_edges():
    f = {"x": [1, 1, 1, 1, 0, 0, 0, 0], "y": [1, 1, 1, 1, 0, 0, 0, 0], "z": [1, 0, 1, 0, 1, 0, 1, None]}
    r = dv.cooccurrence(f, alpha=0.05)
    xy = next(x for x in r["rows"] if (x["feature_1"], x["feature_2"]) == ("x", "y"))
    assert xy["table"] == [4, 0, 0, 4] and xy["phi"] == 1.0 and xy["jaccard"] == 1.0
    assert xy["p"] == pytest.approx(2 / 70, rel=1e-3)
    xz = next(x for x in r["rows"] if x["feature_2"] == "z" and x["feature_1"] == "x")
    assert xz["samples"] == 7
    assert r["pairs_tested"] == 3 and r["edges"] == sum(1 for x in r["rows"] if x["q"] <= 0.05)


def test_lineage_distribution_uses_searched_samples_only():
    r = dv.lineage_distribution({"g": [1, None, 0, 1]}, ["A", "A", "A", "B"])
    a = r["lineages"][0]
    assert a["lineage"] == "A" and a["samples"] == 3
    assert a["features"]["g"]["with"] == 1 and a["features"]["g"]["searched"] == 2


def test_heatmap_order_matches_scipy_average_linkage():
    rng = np.random.default_rng(3)
    m = rng.integers(0, 2, size=(7, 12))
    m[:, 0] = 1
    ids = [f"s{i}" for i in range(7)]
    feats = {f"f{j}": m[:, j].tolist() for j in range(12)}
    h = dv.heatmap(feats, ids)
    from scipy.spatial.distance import pdist
    ref = hierarchy.linkage(pdist(m.astype(bool), "jaccard"), method="average")
    ours = sorted(round(x[2], 6) for x in h["sample_merges"])
    assert ours == pytest.approx(sorted(ref[:, 2].round(6).tolist()), abs=1e-6)


def test_pca_explained_variance_matches_covariance_eigenvalues():
    rng = np.random.default_rng(1)
    m = rng.integers(0, 2, size=(9, 6))
    ids = [f"s{i}" for i in range(9)]
    feats = {f"f{j}": m[:, j].tolist() for j in range(6)}
    r = dv.pca(feats, ids, components=2)
    assert r["applicable"]
    x = m[:, [j for j in range(6) if 0 < m[:, j].sum() < 9]].astype(float)
    eig = np.sort(np.linalg.eigvalsh(np.cov(x, rowvar=False)))[::-1]
    assert r["explained_variance_ratio"] == pytest.approx((eig[:2] / eig.sum()).tolist(), rel=1e-3)
    assert math.isclose(sum(s[0] for s in r["scores"]), 0.0, abs_tol=1e-3)


def test_pca_is_refused_when_not_appropriate():
    r = dv.pca({"a": [1, 0], "b": [0, 1]}, ["s1", "s2"])
    assert not r["applicable"] and r["reason"] == "too_few_samples"
    r = dv.pca({"a": [1, 0, 1, None], "b": [1, 1, 1, 1]}, ["s1", "s2", "s3", "s4"])
    assert not r["applicable"] and r["reason"] == "too_few_varying_features" and r["excluded_samples"] == ["s4"]


def test_one_hot_keeps_unknown():
    assert dv.one_hot("st", ["8", None, "5"]) == {"st=5": [0, None, 1], "st=8": [1, None, 0]}
