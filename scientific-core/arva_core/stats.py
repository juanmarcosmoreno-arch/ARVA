"""Small-sample statistics for 2x2 tables, written out so that every formula is visible and tested against reference
values (SciPy, R's fisher.test / mantelhaen.test and the published worked examples named in the tests).

* Fisher's exact test, two-sided: the sum of the probabilities of all tables with the same margins that are no more
  probable than the observed one, with a relative tolerance of 1e-7 as R's fisher.test.
* Benjamini-Hochberg adjusted p-values (q), step-up, monotone.
* Wilson score 95 % interval for a proportion.
* Odds ratio (sample, ad/bc) with a Woolf (logit) 95 % interval; 0.5 is added to every cell when a cell is 0
  (Haldane-Anscombe).
* Difference of two proportions with Newcombe's hybrid score interval (Newcombe 1998, method 10), built from the two
  Wilson intervals.
* Cochran-Mantel-Haenszel test over strata of 2x2 tables, as R's mantelhaen.test for 2x2xK with its default
  continuity correction, with the Mantel-Haenszel common odds ratio and the Robins-Breslow-Greenland interval.
  Strata with fewer than 2 observations carry no information and are left out (R refuses them).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

Z95 = 1.959963984540054


def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided p-value of Fisher's exact test on [[a, b], [c, d]] (row 1 = group: present a, absent b)."""
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    lo, hi = max(0, c1 - r2), min(r1, c1)
    denom = _log_choose(n, c1)
    probs = {x: math.exp(_log_choose(r1, x) + _log_choose(r2, c1 - x) - denom) for x in range(lo, hi + 1)}
    observed = probs[a]
    p = sum(v for v in probs.values() if v <= observed * (1 + 1e-7))
    return min(1.0, p)


def benjamini_hochberg(pvalues: Sequence[float]) -> list[float]:
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q


def wilson(k: int, n: int) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def odds_ratio(a: int, b: int, c: int, d: int) -> dict[str, Any]:
    corrected = 0 in (a, b, c, d)
    x = [v + 0.5 if corrected else float(v) for v in (a, b, c, d)]
    log_or = math.log(x[0] * x[3] / (x[1] * x[2]))
    se = math.sqrt(sum(1 / v for v in x))
    return {"odds_ratio": math.exp(log_or), "ci_low": math.exp(log_or - Z95 * se),
            "ci_high": math.exp(log_or + Z95 * se), "haldane_corrected": corrected}


def proportion_difference(k1: int, n1: int, k2: int, n2: int) -> dict[str, float] | None:
    """k1/n1 - k2/n2 with Newcombe's hybrid score 95 % interval."""
    w1, w2 = wilson(k1, n1), wilson(k2, n2)
    if w1 is None or w2 is None:
        return None
    p1, p2 = k1 / n1, k2 / n2
    diff = p1 - p2
    return {"difference": diff, "ci_low": diff - math.sqrt((p1 - w1[0]) ** 2 + (w2[1] - p2) ** 2),
            "ci_high": diff + math.sqrt((w1[1] - p1) ** 2 + (p2 - w2[0]) ** 2)}


def chi2_sf_1df(x: float) -> float:
    """Upper tail of the chi-squared distribution with one degree of freedom."""
    return math.erfc(math.sqrt(max(x, 0.0) / 2))


def phi(a: int, b: int, c: int, d: int) -> float | None:
    denom = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    return None if denom == 0 else (a * d - b * c) / denom


def mantel_haenszel(tables: Sequence[Sequence[int]], correct: bool = True) -> dict[str, Any]:
    """`tables`: one (a, b, c, d) per stratum. Returns the strata used, the informative ones (both margins vary), the
    continuity-corrected CMH statistic and p-value, and the common odds ratio with its 95 % interval (None when it
    cannot be estimated: no informative stratum, or every stratum's ad or bc term is 0)."""
    used = [tuple(int(v) for v in t) for t in tables if sum(t) >= 2]
    informative = [t for t in used if (t[0] + t[1]) * (t[2] + t[3]) * (t[0] + t[2]) * (t[1] + t[3]) > 0]
    out: dict[str, Any] = {"strata": len(used), "informative_strata": len(informative), "statistic": None,
                           "p": None, "odds_ratio": None, "ci_low": None, "ci_high": None}
    if not informative:
        return out
    delta = var = 0.0
    sx = sy = 0.0
    t1 = t2 = t3 = 0.0
    for a, b, c, d in used:
        n = a + b + c + d
        r1, r2, c1, c2 = a + b, c + d, a + c, b + d
        delta += a - r1 * c1 / n
        var += r1 * r2 * c1 * c2 / (n * n * (n - 1))
        sx += a * d / n
        sy += b * c / n
        t1 += (a + d) * a * d / n ** 2
        t2 += ((a + d) * b * c + (b + c) * a * d) / n ** 2
        t3 += (b + c) * b * c / n ** 2
    yates = 0.5 if correct and abs(delta) >= 0.5 else 0.0
    stat = (abs(delta) - yates) ** 2 / var
    out.update(statistic=stat, p=chi2_sf_1df(stat))
    if sx > 0 and sy > 0:
        est = sx / sy
        sd = math.sqrt(t1 / (2 * sx * sx) + t2 / (2 * sx * sy) + t3 / (2 * sy * sy))
        out.update(odds_ratio=est, ci_low=est * math.exp(-Z95 * sd), ci_high=est * math.exp(Z95 * sd))
    return out
