"""ARVA Discover: exploratory analyses of a table of genomes (one row per sample) with categorical fields (ST, country,
host, source, year, phenotypes, ...) and binary features (genes, replicons, one-hot categories). Every analysis is
exploratory, not confirmatory.

Data conventions: a feature value is 1 (found), 0 (searched, not found) or None (not searched); a field value is a
string or None (unknown). Samples with None are left out of each test that needs the value, and every test reports
the samples it used.

* Associations: for each group of a field against the other samples with a value, and each feature that varies among
  the samples used, the 2x2 table, Fisher's exact test, Benjamini-Hochberg q over every test of the run, the shares
  with Wilson 95 % intervals, the difference with Newcombe's interval and the odds ratio with Woolf's interval
  (arva_core.stats). With a lineage field, the same table per lineage and the Cochran-Mantel-Haenszel test with the
  Mantel-Haenszel common odds ratio: related genomes are not independent, so a group that is mostly one lineage
  shows the lineage's genes; the stratified result keeps only within-lineage contrasts.
* Co-occurrence: every pair of features over the samples where both were searched; Fisher's exact test, BH q over
  all pairs, odds ratio with Woolf's interval, phi and Jaccard; optionally stratified by lineage (CMH). Network edges
  are the pairs with q at or below the stated alpha.
* Distribution by lineage: per lineage, the samples with each feature, with a Wilson interval.
* Heatmap: samples ordered by average linkage (UPGMA) on the Jaccard distance between their feature sets, features
  by the same on their sample sets; samples with an unsearched feature are left out. Similarity clustering, not a
  phylogeny.
* PCA of the centred 0/1 matrix (singular value decomposition): a descriptive projection, run only with at least
  MIN_PCA_SAMPLES complete samples and 2 varying features. On 0/1 data it is Euclidean, not a model of gene content.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from arva_core.comparative import average_linkage
from arva_core.stats import (
    benjamini_hochberg,
    fisher_exact,
    mantel_haenszel,
    odds_ratio,
    phi,
    proportion_difference,
    wilson,
)

LABEL = "exploratory, not confirmatory"
MIN_PCA_SAMPLES = 3
MAX_COOCCURRENCE_FEATURES = 150
CAVEAT_CODES = ("not_causal", "phylogenetic_dependence", "multiple_testing", "not_searched_excluded")


def _r(v: float | None, digits: int = 4) -> float | None:
    return None if v is None else float(f"{v:.{digits}g}")


def _ci(lo: float | None, hi: float | None) -> list[float | None] | None:
    return None if lo is None or hi is None else [_r(lo), _r(hi)]


def one_hot(name: str, values: Sequence[str | None]) -> dict[str, list[int | None]]:
    """One 0/1 feature per value of a field (`name=value`); unknown stays None."""
    return {f"{name}={v}": [None if x is None else int(x == v) for x in values]
            for v in sorted({x for x in values if x is not None})}


def _table(x: np.ndarray, y: np.ndarray) -> tuple[int, int, int, int]:
    return (int((x & y).sum()), int((x & ~y).sum()), int((~x & y).sum()), int((~x & ~y).sum()))


def _stratified(x: np.ndarray, y: np.ndarray, strata: Sequence[str | None] | None, keep: np.ndarray) -> dict | None:
    if strata is None:
        return None
    labels = np.array([s if s is not None else "" for s in strata], dtype=object)
    usable = keep & np.array([s is not None for s in strata])
    tables, per = [], []
    for value in sorted({s for s, u in zip(strata, usable, strict=True) if u}):
        m = usable & (labels == value)
        t = _table(x[m], y[m])
        tables.append(t)
        per.append({"lineage": value, "table": list(t)})
    mh = mantel_haenszel(tables)
    return {"samples": int(usable.sum()), "strata": per, "informative_strata": mh["informative_strata"],
            "cmh_statistic": _r(mh["statistic"]), "p": mh["p"], "odds_ratio": _r(mh["odds_ratio"]),
            "odds_ratio_ci": _ci(mh["ci_low"], mh["ci_high"])}


def _effects(a: int, b: int, c: int, d: int) -> dict[str, Any]:
    n1, n2 = a + b, c + d
    w1, w2 = wilson(a, n1), wilson(c, n2)
    diff = proportion_difference(a, n1, c, n2)
    o = odds_ratio(a, b, c, d)
    return {"table": [a, b, c, d], "share_1": _r(a / n1) if n1 else None, "share_1_ci": _ci(*w1) if w1 else None,
            "share_2": _r(c / n2) if n2 else None, "share_2_ci": _ci(*w2) if w2 else None,
            "difference": _r(diff["difference"]) if diff else None,
            "difference_ci": _ci(diff["ci_low"], diff["ci_high"]) if diff else None,
            "odds_ratio": _r(o["odds_ratio"]), "odds_ratio_ci": _ci(o["ci_low"], o["ci_high"]),
            "haldane_corrected": o["haldane_corrected"], "p": fisher_exact(a, b, c, d)}


def _adjust(rows: list[dict[str, Any]]) -> None:
    for r, q in zip(rows, benjamini_hochberg([r["p"] for r in rows]), strict=True):
        r["q"] = _r(q)
    stratified = [r for r in rows if r.get("stratified") and r["stratified"]["p"] is not None]
    for r, q in zip(stratified, benjamini_hochberg([r["stratified"]["p"] for r in stratified]), strict=True):
        r["stratified"]["q"] = _r(q)
        r["stratified"]["p"] = _r(r["stratified"]["p"])
    for r in rows:
        r["p"] = _r(r["p"])


def associations(features: Mapping[str, Sequence[int | None]], groups: Sequence[str | None],
                 min_group: int = 2, strata: Sequence[str | None] | None = None) -> dict[str, Any]:
    """One test per (group, feature): samples of the group against the other samples with a value, over the samples
    where the feature was searched. Groups with fewer than `min_group` samples, or fewer than `min_group` others, are
    listed as skipped; features that do not vary among the samples used are not tested."""
    if min_group < 1:
        raise ValueError("min_group must be at least 1")
    n = len(groups)
    if strata is not None and len(strata) != n:
        raise ValueError("one lineage value per sample is needed")
    has_group = np.array([g is not None for g in groups])
    rows: list[dict[str, Any]] = []
    tested, skipped = [], []
    values = sorted({g for g in groups if g is not None})
    # With two values, the second group's tables are the first's with the rows swapped: testing both would only
    # duplicate every test (and loosen nothing but the multiple-testing correction).
    mirror = values[1] if len(values) == 2 else None
    for value in values:
        if value == mirror:
            skipped.append({"group": value, "samples": int(np.array([g == value for g in groups]).sum()),
                            "mirror_of": values[0]})
            continue
        inside = np.array([g == value for g in groups])
        n1, n2 = int(inside.sum()), int((has_group & ~inside).sum())
        if n1 < min_group or n2 < min_group:
            skipped.append({"group": value, "samples": n1})
            continue
        tested.append({"group": value, "samples": n1, "others": n2})
        for name, raw in features.items():
            if len(raw) != n:
                raise ValueError(f"feature {name!r} needs one value per sample")
            searched = np.array([v is not None for v in raw])
            keep = has_group & searched
            x = inside[keep]
            y = np.array([bool(v) for v in raw], dtype=bool)[keep]
            if x.all() or not x.any() or y.all() or not y.any():
                continue
            row = {"group": value, "feature": name, "samples": int(keep.sum()), **_effects(*_table(x, y))}
            if strata is not None:
                row["stratified"] = _stratified(inside, np.array([bool(v) for v in raw]), strata, keep)
            rows.append(row)
    _adjust(rows)
    rows.sort(key=lambda r: (r["p"], r["group"], r["feature"]))
    return {"label": LABEL, "samples_with_value": int(has_group.sum()), "samples_without_value": int((~has_group).sum()),
            "tests": len(rows), "tested_groups": tested, "skipped_groups": skipped, "min_group": min_group,
            "stratified_by_lineage": strata is not None, "rows": rows,
            "method": "Fisher's exact test (two-sided), one group against the other samples with a value; "
                      "Benjamini-Hochberg q over all tests of this run; Wilson 95 % intervals for the shares; "
                      "difference of shares with Newcombe's hybrid score 95 % interval; odds ratio with Woolf 95 % "
                      "interval (Haldane-Anscombe +0.5 when a cell is 0); with a lineage field, Cochran-Mantel-"
                      "Haenszel test (continuity-corrected) and Mantel-Haenszel common odds ratio with the "
                      "Robins-Breslow-Greenland 95 % interval, BH q over the stratified tests"}


def cooccurrence(features: Mapping[str, Sequence[int | None]], alpha: float = 0.05,
                 strata: Sequence[str | None] | None = None) -> dict[str, Any]:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    names = list(features)
    if len(names) > MAX_COOCCURRENCE_FEATURES:
        raise ValueError(f"at most {MAX_COOCCURRENCE_FEATURES} features")
    cols = {k: (np.array([v is not None for v in features[k]]), np.array([bool(v) for v in features[k]], dtype=bool))
            for k in names}
    rows: list[dict[str, Any]] = []
    for i, f1 in enumerate(names):
        for f2 in names[i + 1:]:
            keep = cols[f1][0] & cols[f2][0]
            x, y = cols[f1][1][keep], cols[f2][1][keep]
            if x.all() or not x.any() or y.all() or not y.any():
                continue
            a, b, c, d = _table(x, y)
            row = {"feature_1": f1, "feature_2": f2, "samples": int(keep.sum()), **_effects(a, b, c, d),
                   "phi": _r(phi(a, b, c, d)), "jaccard": _r(a / (a + b + c)) if a + b + c else None}
            if strata is not None:
                row["stratified"] = _stratified(cols[f1][1], cols[f2][1], strata, keep)
            rows.append(row)
    _adjust(rows)
    rows.sort(key=lambda r: (r["p"], r["feature_1"], r["feature_2"]))
    edges = [r for r in rows if r["q"] is not None and r["q"] <= alpha]
    nodes = sorted({r["feature_1"] for r in edges} | {r["feature_2"] for r in edges})
    return {"label": LABEL, "features": len(names), "pairs_tested": len(rows), "alpha": alpha, "rows": rows,
            "edges": len(edges), "nodes": nodes, "stratified_by_lineage": strata is not None,
            "method": "Fisher's exact test (two-sided) for each pair of features over the samples where both were "
                      "searched; Benjamini-Hochberg q over all pairs; edges: q <= alpha; odds ratio with Woolf 95 % "
                      "interval, phi coefficient and Jaccard index (samples with both / samples with either)"}


def lineage_distribution(features: Mapping[str, Sequence[int | None]],
                         lineages: Sequence[str | None]) -> dict[str, Any]:
    out = []
    for value in sorted({x for x in lineages if x is not None}):
        idx = [i for i, x in enumerate(lineages) if x == value]
        cells = {}
        for name, raw in features.items():
            searched = [raw[i] for i in idx if raw[i] is not None]
            k, m = sum(1 for v in searched if v), len(searched)
            w = wilson(k, m)
            cells[name] = {"with": k, "searched": m, "share": _r(k / m) if m else None,
                           "ci": _ci(*w) if w else None}
        out.append({"lineage": value, "samples": len(idx), "features": cells})
    return {"label": LABEL, "lineages": out, "unknown_lineage": sum(1 for x in lineages if x is None),
            "method": "samples with each feature among the lineage's samples where it was searched, Wilson 95 % "
                      "interval"}


def _complete(features: Mapping[str, Sequence[int | None]], ids: Sequence[str]) -> tuple[list[str], list[str], np.ndarray]:
    names = list(features)
    keep = [i for i in range(len(ids)) if all(features[f][i] is not None for f in names)]
    m = np.array([[int(bool(features[f][i])) for f in names] for i in keep], dtype=np.int64).reshape(len(keep),
                                                                                                    len(names))
    return [ids[i] for i in keep], names, m


def _jaccard(m: np.ndarray) -> list[list[float]]:
    inter = m @ m.T
    sizes = m.sum(axis=1)
    union = sizes[:, None] + sizes[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(union > 0, 1.0 - inter / np.where(union > 0, union, 1), 0.0)
    return [[round(float(x), 6) for x in row] for row in d]


def heatmap(features: Mapping[str, Sequence[int | None]], ids: Sequence[str]) -> dict[str, Any]:
    kept, names, m = _complete(features, ids)
    rows = average_linkage(_jaccard(m), "average linkage (UPGMA) on the Jaccard distance between samples' feature "
                                        "sets") if len(kept) else {"order": [], "merges": []}
    cols = average_linkage(_jaccard(m.T), "average linkage (UPGMA) on the Jaccard distance between features' "
                                          "sample sets") if names else {"order": [], "merges": []}
    return {"label": LABEL, "samples": kept, "excluded_samples": [i for i in ids if i not in set(kept)],
            "features": names, "matrix": m.tolist(), "sample_order": rows["order"], "feature_order": cols["order"],
            "sample_merges": rows["merges"], "method": rows.get("method"),
            "note": "similarity clustering of presence/absence, not a phylogeny"}


def pca(features: Mapping[str, Sequence[int | None]], ids: Sequence[str], components: int = 2) -> dict[str, Any]:
    kept, names, m = _complete(features, ids)
    varying = [j for j in range(m.shape[1]) if 0 < m[:, j].sum() < m.shape[0]] if m.size else []
    base = {"label": LABEL, "samples": kept, "excluded_samples": [i for i in ids if i not in set(kept)],
            "varying_features": [names[j] for j in varying],
            "method": "principal component analysis of the centred 0/1 matrix (SVD); features that do not vary are "
                      "left out"}
    if len(kept) < MIN_PCA_SAMPLES:
        return {**base, "applicable": False, "reason": "too_few_samples", "minimum": MIN_PCA_SAMPLES}
    if len(varying) < 2:
        return {**base, "applicable": False, "reason": "too_few_varying_features", "minimum": 2}
    x = m[:, varying].astype(float)
    x -= x.mean(axis=0)
    u, s, vt = np.linalg.svd(x, full_matrices=False)
    k = min(components, len(s))
    var = s ** 2
    total = var.sum()
    # The sign of a component is arbitrary; fix it so that its largest loading is positive (reproducible output).
    for j in range(k):
        if vt[j, np.argmax(np.abs(vt[j]))] < 0:
            vt[j] *= -1
            u[:, j] *= -1
    scores = u[:, :k] * s[:k]
    loadings = [sorted(({"feature": names[varying[i]], "loading": _r(float(vt[j, i]))} for i in range(len(varying))),
                       key=lambda r: -abs(r["loading"] or 0))[:10] for j in range(k)]
    return {**base, "applicable": True, "components": k,
            "explained_variance_ratio": [_r(float(v / total)) for v in var[:k]] if total > 0 else [0.0] * k,
            "scores": [[_r(float(v)) for v in row] for row in scores], "top_loadings": loadings}
