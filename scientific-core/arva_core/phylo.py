"""Tree operations ARVA does itself on the trees the tools infer (nested dicts as in arva_core.newick).

* Rooting. IQ-TREE and FastTree infer unrooted trees and write them from an arbitrary node. ARVA roots them for
  drawing, never changing the inferred tree: midpoint rooting (the root at the middle of the longest leaf-to-leaf
  path; it assumes a roughly constant rate of evolution) or an outgroup (the root on the branch that separates the
  outgroup's leaves from the others, which must be one side of a branch of the unrooted tree). The position of the
  root on that branch is not estimated: ARVA places it at the branch's middle. Support values belong to branches
  (bipartitions) and move with them when the tree is re-rooted.
* Robinson-Foulds distance (Robinson & Foulds 1981) between two trees: the number of bipartitions found in one tree
  and not the other, counted on the unrooted trees over the leaves they share; normalised by the number of
  bipartitions of both trees.
* Neighbour joining (Saitou & Nei 1987, with Studier & Keppler's 1988 formulas) on a distance matrix: a distance
  tree, not a model-based phylogeny. Negative branch-length estimates are set to 0 and counted.
* Alignment statistics and pairwise distances (p-distance or Jukes-Cantor 1969) with pairwise deletion: only the
  columns where both sequences hold A, C, G or T are compared.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

BASES = b"ACGT"


class PhyloError(ValueError):
    pass


# --- Trees as graphs -------------------------------------------------------------------------------------------------

def _graph(tree: dict[str, Any]) -> tuple[list[dict[str, Any]], list[list[int]], dict[frozenset[int], dict[str, Any]]]:
    """Nodes (name), adjacency in drawing order, and per edge its length and supports (the attributes the child
    node carried)."""
    nodes: list[dict[str, Any]] = []
    adj: list[list[int]] = []
    edges: dict[frozenset[int], dict[str, Any]] = {}
    stack: list[tuple[dict[str, Any], int | None]] = [(tree, None)]
    while stack:
        n, parent = stack.pop()
        i = len(nodes)
        nodes.append({"name": n.get("name"), "leaf": not n["children"]})
        adj.append([])
        if parent is not None:
            adj[parent].append(i)
            adj[i].append(parent)
            edges[frozenset((parent, i))] = {"length": n.get("length"), "support": n.get("support"),
                                             "supports": n.get("supports")}
        stack.extend((c, i) for c in reversed(n["children"]))
    return nodes, adj, edges


def _build(nodes: list[dict[str, Any]], adj: list[list[int]], edges: dict[frozenset[int], dict[str, Any]],
           start: int, parent: int, attrs: dict[str, Any]) -> dict[str, Any]:
    """The subtree hanging from `start` away from `parent`, with `attrs` on its stem; nodes left with one child are
    merged into their child (lengths summed, the child's support kept, else the node's)."""
    children = [c for c in adj[start] if c != parent]
    if len(children) == 1 and not nodes[start]["leaf"]:
        e = edges[frozenset((start, children[0]))]
        length = None if attrs["length"] is None and e["length"] is None else \
            (attrs["length"] or 0.0) + (e["length"] or 0.0)
        keep = e if e["support"] is not None else attrs
        return _build(nodes, adj, edges, children[0], start,
                      {"length": length, "support": keep["support"], "supports": keep.get("supports")})
    out: dict[str, Any] = {"name": nodes[start]["name"], "length": attrs["length"], "support": attrs["support"],
                           "children": [_build(nodes, adj, edges, c, start, edges[frozenset((start, c))])
                                        for c in children]}
    if attrs.get("supports"):
        out["supports"] = attrs["supports"]
    if not out["children"]:
        out["support"] = None
    return out


def _root_on_edge(nodes: list[dict[str, Any]], adj: list[list[int]], edges: dict[frozenset[int], dict[str, Any]],
                  a: int, b: int, from_a: float | None) -> dict[str, Any]:
    e = edges[frozenset((a, b))]
    total = e["length"]
    if total is None:
        la = lb = None
    else:
        la = min(max(from_a if from_a is not None else total / 2, 0.0), total)
        lb = total - la
    side_a = _build(nodes, adj, edges, a, b, {**e, "length": la})
    side_b = _build(nodes, adj, edges, b, a, {**e, "length": lb})
    return {"name": None, "length": None, "support": None, "children": [side_a, side_b]}


def leaf_names(tree: dict[str, Any]) -> list[str]:
    out, stack = [], [tree]
    while stack:
        n = stack.pop()
        if not n["children"]:
            out.append(n.get("name") or "")
        stack.extend(reversed(n["children"]))
    return out


def _check_leaves(tree: dict[str, Any]) -> list[str]:
    names = leaf_names(tree)
    if len(set(names)) != len(names) or "" in names:
        raise PhyloError("the tree's leaves must have distinct, non-empty names")
    if len(names) < 3:
        raise PhyloError("a tree needs at least three leaves to be rooted")
    return names


def _distances_from(adj: list[list[int]], edges: dict[frozenset[int], dict[str, Any]], start: int
                    ) -> tuple[list[float], list[int]]:
    dist = [math.inf] * len(adj)
    prev = [-1] * len(adj)
    dist[start] = 0.0
    stack = [start]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if dist[v] == math.inf:
                length = edges[frozenset((u, v))]["length"]
                if length is None:
                    raise PhyloError("midpoint rooting needs branch lengths on every branch")
                dist[v] = dist[u] + max(length, 0.0)
                prev[v] = u
                stack.append(v)
    return dist, prev


def midpoint_root(tree: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The tree rooted at the middle of its longest leaf-to-leaf path (ties: the pair whose names sort first)."""
    _check_leaves(tree)
    nodes, adj, edges = _graph(tree)
    leaves = sorted((i for i, n in enumerate(nodes) if n["leaf"]), key=lambda i: nodes[i]["name"])
    best = (-1.0, -1, -1)
    for i in leaves:
        dist, _ = _distances_from(adj, edges, i)
        for j in leaves:
            if dist[j] > best[0] + 1e-12 and nodes[i]["name"] < nodes[j]["name"]:
                best = (dist[j], i, j)
    span, a, b = best
    if span <= 0:
        raise PhyloError("every leaf is at distance 0: there is no midpoint")
    dist, prev = _distances_from(adj, edges, a)
    half = span / 2
    v = b
    while dist[prev[v]] > half:
        v = prev[v]
    u = prev[v]
    rooted = _root_on_edge(nodes, adj, edges, u, v, half - dist[u])
    return rooted, {"method": "midpoint", "leaves": [nodes[a]["name"], nodes[b]["name"]], "path_length": span}


def outgroup_root(tree: dict[str, Any], outgroup: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The tree rooted on the branch separating `outgroup` from the other leaves, at the branch's middle."""
    names = _check_leaves(tree)
    group = set(outgroup)
    if not group or not group <= set(names):
        raise PhyloError("the outgroup must name leaves of the tree")
    if len(group) >= len(names) - 1:
        raise PhyloError("the outgroup must leave at least two leaves in the ingroup")
    nodes, adj, edges = _graph(tree)
    below = _leaf_sets(nodes, adj)
    everything = frozenset(names)
    for (child, parent), side in below.items():
        if side == group or everything - side == group:
            rooted = _root_on_edge(nodes, adj, edges, child, parent, None)
            return rooted, {"method": "outgroup", "outgroup": sorted(group)}
    raise PhyloError("the outgroup is not one side of a branch of the tree (it is not monophyletic in the unrooted "
                     "tree)")


def _leaf_sets(nodes: list[dict[str, Any]], adj: list[list[int]]) -> dict[tuple[int, int], frozenset[str]]:
    """For each edge drawn from node 0: (child, parent) -> the leaves on the child's side."""
    order, parent = [], [-1] * len(nodes)
    seen = [False] * len(nodes)
    stack = [0]
    seen[0] = True
    while stack:
        u = stack.pop()
        order.append(u)
        for v in adj[u]:
            if not seen[v]:
                seen[v] = True
                parent[v] = u
                stack.append(v)
    sets: dict[int, frozenset[str]] = {}
    for u in reversed(order):
        if nodes[u]["leaf"] and u != 0:
            sets[u] = frozenset([nodes[u]["name"]])
        else:
            sets[u] = frozenset().union(*(sets[v] for v in adj[u] if v != parent[u])) | (
                frozenset([nodes[u]["name"]]) if nodes[u]["leaf"] else frozenset())
    return {(u, parent[u]): sets[u] for u in order if parent[u] >= 0}


def unroot(tree: dict[str, Any]) -> dict[str, Any]:
    """The same unrooted tree written from an internal node (a root with two children merged away)."""
    nodes, adj, edges = _graph(tree)
    start = next((i for i, n in enumerate(nodes) if not n["leaf"] and len(adj[i]) >= 3), 0)
    return {**_build(nodes, adj, edges, start, -1, {"length": None, "support": None}), "length": None}


def splits(tree: dict[str, Any], among: set[str] | None = None) -> set[frozenset[str]]:
    """The tree's non-trivial bipartitions (both sides >= 2 leaves) over the leaves `among` (default all), each
    written as the side without the alphabetically first leaf."""
    nodes, adj, _ = _graph(tree)
    names = set(leaf_names(tree))
    keep = names if among is None else names & among
    first = min(keep)
    out = set()
    for side in _leaf_sets(nodes, adj).values():
        s = side & keep
        if 2 <= len(s) <= len(keep) - 2:
            out.add(frozenset(keep - s) if first in s else frozenset(s))
    return out


def robinson_foulds(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    la, lb = set(leaf_names(a)), set(leaf_names(b))
    common = la & lb
    if len(common) < 4:
        raise PhyloError("the trees share fewer than four leaves")
    sa, sb = splits(a, common), splits(b, common)
    only_a, only_b = sa - sb, sb - sa
    total = len(sa) + len(sb)
    return {"rf": len(only_a) + len(only_b), "max": total, "normalized": (len(only_a) + len(only_b)) / total
            if total else 0.0, "shared": len(sa & sb), "splits_a": len(sa), "splits_b": len(sb),
            "common_leaves": len(common), "only_in_a_leaves": sorted(la - lb), "only_in_b_leaves": sorted(lb - la),
            "only_a": sorted(sorted(s) for s in only_a), "only_b": sorted(sorted(s) for s in only_b)}


def summary(tree: dict[str, Any]) -> dict[str, Any]:
    leaves = internal = 0
    total = 0.0
    depth = 0.0
    supports: list[float] = []
    stack: list[tuple[dict[str, Any], float]] = [(tree, 0.0)]
    while stack:
        n, d = stack.pop()
        if n is not tree:
            d += n.get("length") or 0.0
            total += n.get("length") or 0.0
        if n["children"]:
            internal += 1
            if n.get("support") is not None:
                supports.append(n["support"])
        else:
            leaves += 1
            depth = max(depth, d)
        stack.extend((c, d) for c in n["children"])
    return {"leaves": leaves, "internal_nodes": internal, "total_length": total, "max_root_to_tip": depth,
            "bifurcating_root": len(tree["children"]) == 2,
            "support_min": min(supports) if supports else None, "support_max": max(supports) if supports else None}


# --- Distances and neighbour joining ---------------------------------------------------------------------------------

def _matrix(records: list[tuple[str, str]]) -> np.ndarray:
    if not records:
        raise PhyloError("the alignment is empty")
    length = len(records[0][1])
    if any(len(s) != length for _, s in records):
        raise PhyloError("the aligned sequences differ in length")
    return np.frombuffer("".join(s for _, s in records).upper().encode("ascii", "replace"),
                         dtype=np.uint8).reshape(len(records), length)


def alignment_stats(records: list[tuple[str, str]], chunk: int = 1_000_000) -> dict[str, Any]:
    """Columns of a nucleotide alignment: constant (one base among A/C/G/T, others gaps or ambiguous), variable,
    parsimony-informative (at least two bases each held by at least two sequences) and without any base; the share of
    gap or ambiguous cells per sequence."""
    m = _matrix(records)
    n, length = m.shape
    constant = variable = informative = empty = 0
    missing = np.zeros(n, dtype=np.int64)
    for start in range(0, length, chunk):
        block = m[:, start:start + chunk]
        counts = np.stack([(block == b).sum(axis=0) for b in BASES])
        present = (counts > 0).sum(axis=0)
        constant += int((present == 1).sum())
        variable += int((present >= 2).sum())
        empty += int((present == 0).sum())
        informative += int(((counts >= 2).sum(axis=0) >= 2).sum())
        missing += (~np.isin(block, np.frombuffer(BASES, dtype=np.uint8))).sum(axis=1)
    return {"sequences": n, "columns": length, "constant": constant, "variable": variable,
            "parsimony_informative": informative, "no_base": empty,
            "missing_fraction": [float(x) / length if length else 0.0 for x in missing]}


def pairwise_distances(records: list[tuple[str, str]], model: str, chunk: int = 500_000) -> dict[str, Any]:
    if model not in ("p", "jc69"):
        raise PhyloError("model must be p or jc69")
    m = _matrix(records)
    n, length = m.shape
    diffs = np.zeros((n, n), dtype=np.int64)
    sites = np.zeros((n, n), dtype=np.int64)
    acgt = np.frombuffer(BASES, dtype=np.uint8)
    for start in range(0, length, chunk):
        block = m[:, start:start + chunk]
        valid = np.isin(block, acgt)
        for i in range(n):
            both = valid & valid[i]
            sites[i] += both.sum(axis=1)
            diffs[i] += ((block != block[i]) & both).sum(axis=1)
    p = np.divide(diffs, sites, out=np.full((n, n), np.nan), where=sites > 0)
    if np.isnan(p[~np.eye(n, dtype=bool)]).any():
        raise PhyloError("some pairs of sequences share no column with a base in both")
    if model == "jc69":
        if (p >= 0.75).any():
            raise PhyloError("a p-distance of 0.75 or more has no Jukes-Cantor correction")
        d = -0.75 * np.log(1 - 4 * p / 3)
    else:
        d = p
    np.fill_diagonal(d, 0.0)
    return {"distances": d.tolist(), "compared_sites": sites.tolist(), "model": model}


def neighbour_joining(names: list[str], distances: list[list[float]]) -> tuple[dict[str, Any], int]:
    """An unrooted NJ tree (written from a node with three children) and the number of negative branch lengths set
    to 0."""
    n = len(names)
    if n < 3:
        raise PhyloError("neighbour joining needs at least three taxa")
    if len(set(names)) != n:
        raise PhyloError("the taxa must have distinct names")
    d = np.array(distances, dtype=float)
    if d.shape != (n, n) or not np.all(np.isfinite(d)) or not np.allclose(d, d.T) or (d < 0).any():
        raise PhyloError("the distances must form a finite, symmetric, non-negative matrix")
    clusters: list[dict[str, Any]] = [{"name": x, "length": None, "support": None, "children": []} for x in names]
    active = list(range(n))
    negative = 0

    def length(x: float) -> float:
        nonlocal negative
        if x < 0:
            negative += 1
            return 0.0
        return float(x)

    while len(active) > 3:
        k = len(active)
        sub = d[np.ix_(active, active)]
        r = sub.sum(axis=1)
        q = (k - 2) * sub - r[:, None] - r[None, :]
        np.fill_diagonal(q, np.inf)
        i, j = np.unravel_index(int(np.argmin(q)), q.shape)
        a, b = active[i], active[j]
        li = 0.5 * d[a, b] + (r[i] - r[j]) / (2 * (k - 2))
        lj = d[a, b] - li
        clusters[a]["length"], clusters[b]["length"] = length(li), length(lj)
        node = {"name": None, "length": None, "support": None, "children": [clusters[a], clusters[b]]}
        new = np.array([0.5 * (d[a, x] + d[b, x] - d[a, b]) for x in range(len(d))])
        d = np.vstack([np.column_stack([d, new]), np.append(new, 0.0)])
        clusters.append(node)
        active = [x for x in active if x not in (a, b)] + [len(clusters) - 1]
    a, b, c = active
    for x, y, z in ((a, b, c), (b, a, c), (c, a, b)):
        clusters[x]["length"] = length(0.5 * (d[x, y] + d[x, z] - d[y, z]))
    return {"name": None, "length": None, "support": None, "children": [clusters[a], clusters[b], clusters[c]]}, \
        negative
