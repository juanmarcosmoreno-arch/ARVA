"""What ARVA derives from a gene presence/absence matrix (Panaroo's or PPanGGOLiN's gene_presence_absence.Rtab):
frequency categories, accumulation curves, the family-frequency distribution, an ordering of genomes for heatmaps,
per-group statistics and exploratory associations between families and a metadata field.

What each value is, and what it is not:

* Categories are fractions of genomes holding a family, with the thresholds stated and passed in: core
  (>= `core`), soft core (>= `soft_core`), shell (>= `shell`), cloud (below). ARVA's defaults, 99 / 95 / 15 %, are the
  ones Panaroo's summary_statistics.txt uses (generate_output.generate_summary_stats, after Roary). With few genomes
  the categories are coarse: with 5 genomes every family is core (5/5) or shell / cloud.
* Accumulation curves: for `permutations` random orders of the genomes (numpy default_rng(seed), each order drawn
  independently), the number of families present in at least one of the first k genomes (pan) and in all of them
  (core, strictly all k), with the mean, standard deviation, minimum and maximum over the orders at each k.
* Genome clustering is average-linkage (UPGMA) clustering of the Jaccard distance between the genomes' family sets,
  used to place genomes with similar gene content together in a heatmap. Shared gene content reflects descent,
  gene gain and loss, and annotation; the order is not a phylogeny.
* Associations are exploratory: for each group of a metadata field against the other genomes with a value,
  Fisher's exact test (two-sided: the sum of the probabilities of all tables with the same margins that are no more
  probable than the observed one, with a relative tolerance of 1e-7 as R's fisher.test) on the 2x2 table of presence,
  Benjamini-Hochberg adjusted p-values (q) over every test of that field, Wilson 95 % intervals for the share of
  genomes holding the family in each side, and the odds ratio with a Woolf (logit) 95 % interval, with 0.5 added
  to every cell when a cell is 0 (Haldane-Anscombe). The test assumes independent genomes; related genomes share
  families by descent, so lineage structure alone produces associations, and no correction for it is made. An
  association is a hypothesis to test, not a cause.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from arva_core.comparative import average_linkage
from arva_core.stats import benjamini_hochberg, fisher_exact, odds_ratio, wilson

CATEGORIES = ("core", "soft_core", "shell", "cloud")
DEFAULT_THRESHOLDS = {"core": 0.99, "soft_core": 0.95, "shell": 0.15}
CLUSTER_METHOD = "average linkage (UPGMA) on the Jaccard distance between the genomes' gene-family sets"
CURVE_METHOD = ("random orders of the genomes (numpy default_rng with the seed given); pan = families in at least "
                "one of the first k genomes, core = families in all of the first k genomes")


def parse_rtab(text: str) -> dict[str, Any]:
    """A gene_presence_absence.Rtab: a header 'Gene<TAB>genome...' and one row per family of 0/1 (counts accepted;
    present when > 0)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("the presence/absence table is empty")
    header = lines[0].split("\t")
    if header[0] != "Gene" or len(header) < 2:
        raise ValueError("the presence/absence table does not start with 'Gene' and genome columns")
    genomes = header[1:]
    if len(set(genomes)) != len(genomes):
        raise ValueError("the presence/absence table names a genome twice")
    families, rows = [], []
    for n, line in enumerate(lines[1:], 2):
        cells = line.split("\t")
        if len(cells) != len(header):
            raise ValueError(f"line {n} has {len(cells)} columns, the header {len(header)}")
        try:
            rows.append([1 if int(c) > 0 else 0 for c in cells[1:]])
        except ValueError:
            raise ValueError(f"line {n} holds a value that is not a whole number") from None
        families.append(cells[0])
    if len(set(families)) != len(families):
        raise ValueError("the presence/absence table names a family twice")
    return {"genomes": genomes, "families": families, "presence": rows}


def validate_thresholds(t: dict[str, float]) -> None:
    if set(t) != set(DEFAULT_THRESHOLDS):
        raise ValueError(f"thresholds are {', '.join(DEFAULT_THRESHOLDS)}")
    if not 0 < t["shell"] < t["soft_core"] <= t["core"] <= 1:
        raise ValueError("thresholds must satisfy 0 < shell < soft_core <= core <= 1")


def category(count: int, n: int, t: dict[str, float]) -> str:
    frac = count / n
    eps = 1e-12
    if frac >= t["core"] - eps:
        return "core"
    if frac >= t["soft_core"] - eps:
        return "soft_core"
    if frac >= t["shell"] - eps:
        return "shell"
    return "cloud"


def _matrix(presence: Sequence[Sequence[int]]) -> np.ndarray:
    m = np.asarray(presence, dtype=bool)
    if m.ndim != 2:
        raise ValueError("the presence matrix must have one row per family and one column per genome")
    return m


def summary(presence: Sequence[Sequence[int]], t: dict[str, float]) -> dict[str, Any]:
    """Each family's genome count and category, the category counts, and per genome the families it holds and those
    found in no other genome."""
    validate_thresholds(t)
    m = _matrix(presence)
    n = m.shape[1]
    counts = m.sum(axis=1).astype(int).tolist()
    cats = [category(c, n, t) for c in counts]
    unique = m[m.sum(axis=1) == 1]
    return {"genomes": n, "families": len(counts), "counts": counts, "categories": cats,
            "category_counts": {c: cats.count(c) for c in CATEGORIES}, "thresholds": dict(t),
            "families_per_genome": m.sum(axis=0).astype(int).tolist(),
            "unique_per_genome": unique.sum(axis=0).astype(int).tolist(),
            "absent_families": sum(1 for c in counts if c == 0)}


def frequency_distribution(counts: Sequence[int], n: int) -> list[dict[str, int]]:
    """Number of families found in exactly k genomes, k = 1..n."""
    hist = [0] * (n + 1)
    for c in counts:
        hist[c] += 1
    return [{"genomes": k, "families": hist[k]} for k in range(1, n + 1)]


def _stats(values: np.ndarray) -> dict[str, list[float]]:
    return {"mean": [round(float(x), 3) for x in values.mean(axis=0)],
            "sd": [round(float(x), 3) for x in values.std(axis=0, ddof=1)] if values.shape[0] > 1
            else [0.0] * values.shape[1],
            "min": [int(x) for x in values.min(axis=0)], "max": [int(x) for x in values.max(axis=0)]}


def accumulation(presence: Sequence[Sequence[int]], permutations: int, seed: int) -> dict[str, Any]:
    if not 1 <= permutations <= 10_000:
        raise ValueError("permutations must be between 1 and 10000")
    m = _matrix(presence)
    m = m[m.any(axis=1)]
    n = m.shape[1]
    rng = np.random.default_rng(seed)
    pan = np.zeros((permutations, n), dtype=np.int64)
    core = np.zeros((permutations, n), dtype=np.int64)
    for r in range(permutations):
        cum = np.cumsum(m[:, rng.permutation(n)], axis=1)
        pan[r] = (cum > 0).sum(axis=0)
        core[r] = (cum == np.arange(1, n + 1)).sum(axis=0)
    return {"method": CURVE_METHOD, "permutations": permutations, "seed": seed, "k": list(range(1, n + 1)),
            "pan": _stats(pan), "core": _stats(core)}


def jaccard_distances(presence: Sequence[Sequence[int]]) -> list[list[float]]:
    m = _matrix(presence).T.astype(np.int64)
    inter = m @ m.T
    sizes = m.sum(axis=1)
    union = sizes[:, None] + sizes[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(union > 0, 1.0 - inter / union, 0.0)
    return [[round(float(x), 6) for x in row] for row in d]


def genome_clustering(presence: Sequence[Sequence[int]]) -> dict[str, Any]:
    dist = jaccard_distances(presence)
    return {**average_linkage(dist, CLUSTER_METHOD), "distances": dist}


def family_order(presence: Sequence[Sequence[int]], genome_order: Sequence[int]) -> list[int]:
    """Families by decreasing genome count, then by their presence pattern along `genome_order` (families held by the
    first genomes of the order first), then by index: blocks of shared families line up in a heatmap."""
    m = _matrix(presence)[:, list(genome_order)]
    keys = [(-int(row.sum()), tuple(-int(x) for x in row), i) for i, row in enumerate(m)]
    return [k[2] for k in sorted(keys)]


# --- Groups and associations ----------------------------------------------------------------------------------------

def group_statistics(presence: Sequence[Sequence[int]], groups: Sequence[str | None]) -> list[dict[str, Any]]:
    """Per value of a metadata field: genomes, families in any of them (group pan), in all of them (group core), found
    in the group and in no genome outside it (exclusive; genomes without a value count as outside), and families per
    genome (mean and SD)."""
    m = _matrix(presence)
    if len(groups) != m.shape[1]:
        raise ValueError("one group value per genome is needed")
    out = []
    for value in sorted({g for g in groups if g is not None}):
        inside = np.array([g == value for g in groups])
        sub, rest = m[:, inside], m[:, ~inside]
        per = sub.sum(axis=0)
        any_in = sub.any(axis=1)
        out.append({"group": value, "genomes": int(inside.sum()), "pan": int(any_in.sum()),
                    "core": int(sub.all(axis=1).sum()),
                    "exclusive": int((any_in & ~rest.any(axis=1)).sum()) if rest.shape[1] else int(any_in.sum()),
                    "families_mean": round(float(per.mean()), 2),
                    "families_sd": round(float(per.std(ddof=1)), 2) if len(per) > 1 else None})
    return out


def _round(v: float | None, digits: int = 4) -> float | None:
    return None if v is None else float(f"{v:.{digits}g}")


def associations(presence: Sequence[Sequence[int]], families: Sequence[str], groups: Sequence[str | None],
                 min_group: int) -> dict[str, Any]:
    """One test per (group, family) for every group with at least `min_group` genomes and at least `min_group`
    genomes with another value, over the families whose presence varies among the genomes with a value."""
    if min_group < 1:
        raise ValueError("min_group must be at least 1")
    m = _matrix(presence)
    if len(groups) != m.shape[1] or len(families) != m.shape[0]:
        raise ValueError("one group value per genome and one name per family are needed")
    with_value = np.array([g is not None for g in groups])
    sub = m[:, with_value]
    values = [g for g in groups if g is not None]
    n = len(values)
    counts = sub.sum(axis=1)
    varying = [i for i in range(m.shape[0]) if 0 < counts[i] < n]
    tested_groups, skipped_groups, rows = [], [], []
    for value in sorted(set(values)):
        inside = np.array([g == value for g in values])
        n1, n2 = int(inside.sum()), int((~inside).sum())
        if n1 < min_group or n2 < min_group:
            skipped_groups.append({"group": value, "genomes": n1})
            continue
        tested_groups.append({"group": value, "genomes": n1, "others": n2})
        k1_all = sub[:, inside].sum(axis=1)
        for i in varying:
            k1, k2 = int(k1_all[i]), int(counts[i] - k1_all[i])
            a, b, c, d = k1, n1 - k1, k2, n2 - k2
            orr = odds_ratio(a, b, c, d)
            w1, w2 = wilson(k1, n1), wilson(k2, n2)
            rows.append({"group": value, "family": families[i], "family_index": i, "in_group": k1, "group_size": n1,
                         "in_others": k2, "others_size": n2, "share_group": _round(k1 / n1),
                         "share_group_ci": [_round(w1[0]), _round(w1[1])] if w1 else None,
                         "share_others": _round(k2 / n2),
                         "share_others_ci": [_round(w2[0]), _round(w2[1])] if w2 else None,
                         "odds_ratio": _round(orr["odds_ratio"]), "odds_ratio_ci": [_round(orr["ci_low"]),
                                                                                     _round(orr["ci_high"])],
                         "haldane_corrected": orr["haldane_corrected"], "p": fisher_exact(a, b, c, d)})
    for r, q in zip(rows, benjamini_hochberg([r["p"] for r in rows]), strict=True):
        r["q"] = _round(q)
        r["p"] = _round(r["p"])
    rows.sort(key=lambda r: (r["p"], r["q"], r["group"], r["family_index"]))
    return {"genomes_with_value": n, "genomes_without_value": int((~with_value).sum()),
            "families_tested": len(varying), "tests": len(rows), "tested_groups": tested_groups,
            "skipped_groups": skipped_groups, "min_group": min_group, "rows": rows,
            "method": "Fisher's exact test (two-sided), one group against the other genomes with a value; "
                      "Benjamini-Hochberg q over all tests of the field; Wilson 95 % intervals; odds ratio with "
                      "Woolf 95 % interval (Haldane-Anscombe +0.5 when a cell is 0)"}
