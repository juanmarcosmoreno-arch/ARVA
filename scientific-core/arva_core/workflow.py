"""Workflow definitions: typed ports, the node catalogue, validation of a graph, its order of execution, what a
change of parameters makes stale, and the predefined workflows.

A workflow is a directed acyclic graph of nodes. Each node is one ARVA analysis (one ordinary job when it runs) or a
source that picks existing data. A node's scope is either `sample` (it runs once per sample of a run) or `set` (it
runs once per run, on the genomes the run's samples produced). The only edge from a sample node into a set node is
into a collection port, which gathers that output from every sample.

Nothing here runs a tool: the backend maps each node kind to the API action of the same analysis, so a node is
checked and launched exactly as the analysis's own dialog would be.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FORMAT = "arva-workflow"
FORMAT_VERSION = 1

PORT_TYPES = ("reads_long", "reads_short", "assembly", "annotation", "comparison_set", "alignment", "tree")
SCOPES = ("sample", "set")
MAX_NODES = 60


@dataclass(frozen=True)
class Port:
    name: str
    accepts: tuple[str, ...]
    required: bool = True
    collection: bool = False


@dataclass(frozen=True)
class NodeSpec:
    kind: str
    scope: str
    category: str
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    # Tool ids by the value of `tool_param` ("" when the node has a single set of tools).
    tools: Mapping[str, tuple[str, ...]] | None = None
    tool_param: str | None = None
    # A source picks existing data; it launches no job.
    source: bool = False
    # Runs inside ARVA without a tool (e.g. creating a comparison set); no job, no queue slot.
    internal: bool = False

    def tool_ids(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        if not self.tools:
            return ()
        key = str(_get(params, self.tool_param)) if self.tool_param else ""
        return self.tools.get(key, ())


def _get(params: Mapping[str, Any], dotted: str | None) -> Any:
    value: Any = params
    for part in (dotted or "").split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _out(name: str, kind: str) -> Port:
    return Port(name, (kind,))


_ASM = Port("assembly", ("assembly",))
_SET = Port("set", ("comparison_set",))

NODES: dict[str, NodeSpec] = {s.kind: s for s in (
    NodeSpec("reads_long_input", "sample", "source", outputs=(_out("reads", "reads_long"),), source=True),
    NodeSpec("reads_short_input", "sample", "source", outputs=(_out("reads", "reads_short"),), source=True),
    NodeSpec("assembly_input", "sample", "source", outputs=(_out("assembly", "assembly"),), source=True),
    NodeSpec("annotation_input", "sample", "source",
             outputs=(_out("annotation", "annotation"), _out("assembly", "assembly")), source=True),
    NodeSpec("comparison_set_input", "set", "source", outputs=(_out("set", "comparison_set"),), source=True),
    NodeSpec("fastp", "sample", "reads", (Port("reads", ("reads_short",)),), (_out("reads", "reads_short"),),
             {"": ("fastp",)}),
    NodeSpec("filtlong", "sample", "reads", (Port("reads", ("reads_long",)),), (_out("reads", "reads_long"),),
             {"": ("filtlong",)}),
    NodeSpec("flye", "sample", "assembly", (Port("reads", ("reads_long",)),), (_out("assembly", "assembly"),),
             {"": ("flye",)}),
    NodeSpec("spades", "sample", "assembly", (Port("reads", ("reads_short",)),), (_out("assembly", "assembly"),),
             {"": ("spades",)}),
    NodeSpec("unicycler", "sample", "assembly",
             (Port("short_reads", ("reads_short",)), Port("long_reads", ("reads_long",), required=False)),
             (_out("assembly", "assembly"),), {"": ("unicycler",)}),
    NodeSpec("polishing", "sample", "assembly",
             (_ASM, Port("long_reads", ("reads_long",), required=False),
              Port("short_reads", ("reads_short",), required=False)),
             (_out("assembly", "assembly"),),
             {"racon": ("racon", "minimap2"), "pilon": ("pilon", "bwa", "samtools"),
              "hybrid": ("racon", "minimap2", "pilon", "bwa", "samtools")}, "strategy"),
    NodeSpec("quast", "sample", "assembly", (_ASM,), (), {"": ("quast",)}),
    NodeSpec("bakta", "sample", "annotation", (_ASM,), (_out("annotation", "annotation"),), {"": ("bakta",)}),
    NodeSpec("prokka", "sample", "annotation", (_ASM,), (_out("annotation", "annotation"),), {"": ("prokka",)}),
    NodeSpec("mlst", "sample", "characterisation", (_ASM,), (), {"": ("mlst",)}),
    NodeSpec("species", "sample", "characterisation", (_ASM,), (),
             {m: (m,) for m in ("fastani", "skani", "mash", "sylph", "gtdbtk")}, "method"),
    NodeSpec("amrfinderplus", "sample", "characterisation",
             (_ASM, Port("annotation", ("annotation",), required=False)), (), {"": ("amrfinderplus",)}),
    NodeSpec("virulence", "sample", "characterisation", (_ASM,), (), {"": ("abricate",)}),
    NodeSpec("mobile_elements", "sample", "characterisation", (_ASM,), (),
             {"mobsuite": ("mobsuite",), "plasmidfinder": ("abricate",), "integronfinder": ("integronfinder",),
              "isescan": ("isescan",), "genomad": ("genomad",)}, "method"),
    NodeSpec("comparison_set", "set", "comparative",
             (Port("genomes", ("assembly", "annotation"), collection=True),), (_out("set", "comparison_set"),),
             internal=True),
    NodeSpec("comparative_ani", "set", "comparative", (_SET,), (),
             {"skani": ("skani",), "fastani": ("fastani",)}, "method"),
    NodeSpec("comparative_alignment", "set", "comparative", (_SET,), (),
             {"minimap2": ("minimap2",), "nucmer": ("nucmer", "dnadiff")}, "aligner"),
    NodeSpec("pangenome", "set", "comparative", (_SET,), (_out("core_alignment", "alignment"),),
             {"panaroo": ("panaroo",), "ppanggolin": ("ppanggolin",)}, "method"),
    NodeSpec("phylogeny", "set", "phylogeny", (Port("alignment", ("alignment",)),), (_out("tree", "tree"),),
             {"iqtree": ("iqtree",), "fasttree": ("fasttree",), "nj": ()}, "method"),
    NodeSpec("gene_investigation", "set", "comparative", (_SET,), (_out("alignment", "alignment"),),
             {"": ("blast", "mafft")}),
)}

# Port types each phylogeny source kind reads; a phylogeny node's `source_kind` must suit its upstream node.
PHYLO_SOURCES = {"pangenome": ("core_alignment", "snp_alignment", "family_alignment"),
                 "gene_investigation": ("gene_alignment",)}


def problem(code: str, node: str | None = None, **params: Any) -> dict[str, Any]:
    return {"code": code, "node": node, "params": {k: v for k, v in params.items() if v is not None}}


def _ports(spec: NodeSpec, direction: str) -> dict[str, Port]:
    return {p.name: p for p in (spec.inputs if direction == "in" else spec.outputs)}


def edge_problem(nodes: Mapping[str, Mapping[str, Any]], edge: Mapping[str, Any]) -> dict[str, Any] | None:
    """Why this one edge cannot exist (None when it can): unknown nodes or ports, incompatible types, or scopes."""
    src, dst = nodes.get(edge.get("source", "")), nodes.get(edge.get("target", ""))
    if src is None or dst is None:
        return problem("wf_edge_node", edge.get("target"))
    s_spec, d_spec = NODES.get(src.get("kind", "")), NODES.get(dst.get("kind", ""))
    if s_spec is None or d_spec is None:
        return problem("wf_edge_node", edge.get("target"))
    out = _ports(s_spec, "out").get(edge.get("source_port", ""))
    inp = _ports(d_spec, "in").get(edge.get("target_port", ""))
    if out is None or inp is None:
        return problem("wf_edge_port", dst["id"], port=edge.get("target_port"))
    if src["id"] == dst["id"]:
        return problem("wf_cycle", dst["id"])
    if out.accepts[0] not in inp.accepts:
        return problem("wf_edge_type", dst["id"], port=inp.name, given=out.accepts[0], expected="|".join(inp.accepts))
    if s_spec.scope == "set" and d_spec.scope == "sample":
        return problem("wf_edge_scope", dst["id"], port=inp.name)
    if s_spec.scope == "sample" and d_spec.scope == "set" and not inp.collection:
        return problem("wf_edge_collect", dst["id"], port=inp.name)
    if inp.collection and s_spec.scope != "sample":
        return problem("wf_edge_collect", dst["id"], port=inp.name)
    return None


def topological_order(definition: Mapping[str, Any]) -> list[str]:
    """Node ids so that every node follows the nodes it reads from (Kahn's algorithm, ties in definition order).
    Raises ValueError on a cycle."""
    ids = [n["id"] for n in definition.get("nodes", [])]
    incoming: dict[str, set[str]] = {i: set() for i in ids}
    for e in definition.get("edges", []):
        if e.get("target") in incoming and e.get("source") in incoming:
            incoming[e["target"]].add(e["source"])
    order: list[str] = []
    done: set[str] = set()
    while len(order) < len(ids):
        ready = [i for i in ids if i not in done and incoming[i] <= done]
        if not ready:
            raise ValueError("cycle")
        order.append(ready[0])
        done.add(ready[0])
    return order


def upstream(definition: Mapping[str, Any], node_id: str) -> list[dict[str, Any]]:
    return [e for e in definition.get("edges", []) if e.get("target") == node_id]


def descendants(definition: Mapping[str, Any], node_ids: Iterable[str]) -> set[str]:
    """The given nodes and every node that reads from them, directly or not."""
    out = set(node_ids)
    changed = True
    while changed:
        changed = False
        for e in definition.get("edges", []):
            if e.get("source") in out and e.get("target") not in out:
                out.add(e["target"])
                changed = True
    return out


def validate(definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The structural problems of a definition (parameters are checked by the backend, against the same models as
    the analyses' dialogs). An empty list means the graph can run."""
    problems: list[dict[str, Any]] = []
    if definition.get("format") != FORMAT or definition.get("format_version") != FORMAT_VERSION:
        return [problem("wf_format", format=str(definition.get("format")),
                        version=str(definition.get("format_version")))]
    nodes = definition.get("nodes")
    edges = definition.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [problem("wf_format", format=FORMAT, version=str(FORMAT_VERSION))]
    if not nodes:
        return [problem("wf_empty")]
    if len(nodes) > MAX_NODES:
        return [problem("wf_too_many", count=len(nodes), max=MAX_NODES)]
    by_id: dict[str, Mapping[str, Any]] = {}
    for n in nodes:
        nid = n.get("id") if isinstance(n, Mapping) else None
        if not isinstance(nid, str) or not nid or len(nid) > 64:
            problems.append(problem("wf_node_id"))
            continue
        if nid in by_id:
            problems.append(problem("wf_node_duplicate", nid))
            continue
        if n.get("kind") not in NODES:
            problems.append(problem("wf_node_kind", nid, kind=str(n.get("kind"))))
            continue
        if not isinstance(n.get("params", {}), Mapping):
            problems.append(problem("wf_node_params", nid))
        by_id[nid] = n
    if problems:
        return problems
    seen_edges: set[tuple] = set()
    fed: dict[tuple[str, str], int] = {}
    for e in edges:
        if not isinstance(e, Mapping):
            problems.append(problem("wf_edge_node"))
            continue
        if (p := edge_problem(by_id, e)) is not None:
            problems.append(p)
            continue
        key = (e["source"], e["source_port"], e["target"], e["target_port"])
        if key in seen_edges:
            problems.append(problem("wf_edge_duplicate", e["target"], port=e["target_port"]))
            continue
        seen_edges.add(key)
        fed[(e["target"], e["target_port"])] = fed.get((e["target"], e["target_port"]), 0) + 1
    try:
        topological_order(definition)
    except ValueError:
        problems.append(problem("wf_cycle"))
    for nid, n in by_id.items():
        spec = NODES[n["kind"]]
        for port in spec.inputs:
            count = fed.get((nid, port.name), 0)
            if port.required and count == 0:
                problems.append(problem("wf_input_missing", nid, port=port.name))
            if count > 1 and not port.collection:
                problems.append(problem("wf_input_many", nid, port=port.name))
        if n["kind"] == "phylogeny":
            problems.extend(_phylo_source_problems(definition, by_id, nid, n))
    return problems


def _phylo_source_problems(definition, by_id, nid, node) -> list[dict[str, Any]]:
    kind = (node.get("params") or {}).get("source_kind")
    for e in upstream(definition, nid):
        allowed = PHYLO_SOURCES.get(by_id[e["source"]]["kind"], ())
        if kind not in allowed:
            return [problem("wf_phylo_source", nid, kind=str(kind), allowed="|".join(allowed))]
    return []


def canonical(definition: Mapping[str, Any]) -> dict[str, Any]:
    """The parts of a definition that decide what runs (no positions or labels), in a stable order."""
    nodes = sorted(({"id": n["id"], "kind": n["kind"], "params": n.get("params") or {}}
                    for n in definition.get("nodes", [])), key=lambda n: n["id"])
    edges = sorted(({k: e[k] for k in ("source", "source_port", "target", "target_port")}
                    for e in definition.get("edges", [])),
                   key=lambda e: (e["target"], e["target_port"], e["source"], e["source_port"]))
    return {"format": FORMAT, "format_version": FORMAT_VERSION, "nodes": nodes, "edges": edges}


def checksum(definition: Mapping[str, Any]) -> str:
    text = json.dumps(canonical(definition), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def node_signature(definition: Mapping[str, Any], node_id: str) -> str:
    """What a node computes: its kind, its parameters and, recursively, the signatures of what it reads."""
    nodes = {n["id"]: n for n in definition.get("nodes", [])}
    memo: dict[str, str] = {}

    def sig(nid: str) -> str:
        if nid not in memo:
            n = nodes[nid]
            ups = sorted((e["target_port"], e["source_port"], sig(e["source"])) for e in upstream(definition, nid))
            text = json.dumps([n["kind"], n.get("params") or {}, ups], sort_keys=True, separators=(",", ":"))
            memo[nid] = hashlib.sha256(text.encode()).hexdigest()
        return memo[nid]

    return sig(node_id)


def reusable_nodes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, str]:
    """Nodes of `current` whose work `previous` already did, as {current node id: previous node id}: same kind,
    same parameters and the same upstream graph (compared by signature). Everything else, including every node
    downstream of a change, runs again in a new branch; the earlier results stay as they are."""
    prev = {node_signature(previous, n["id"]): n["id"] for n in previous.get("nodes", [])}
    out = {}
    for n in current.get("nodes", []):
        match = prev.get(node_signature(current, n["id"]))
        if match is not None:
            out[n["id"]] = match
    return out


def param_diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    """Every parameter path whose value differs between two parameter sets."""
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        out = []
        for key in sorted(set(a) | set(b), key=str):
            out.extend(param_diff(a.get(key), b.get(key), f"{path}.{key}" if path else str(key)))
        return out
    return [] if a == b else [{"path": path, "before": a, "after": b}]


def with_params(definition: Mapping[str, Any], node_id: str, params: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(definition))
    for n in out["nodes"]:
        if n["id"] == node_id:
            n["params"] = copy.deepcopy(dict(params))
    return out


def tools_of(definition: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    return {n["id"]: NODES[n["kind"]].tool_ids(n.get("params") or {}) for n in definition.get("nodes", [])
            if n.get("kind") in NODES}


def _graph(nodes: list[tuple[str, str, dict]], edges: list[tuple[str, str, str, str]]) -> dict[str, Any]:
    return {
        "format": FORMAT, "format_version": FORMAT_VERSION,
        "nodes": [{"id": i, "kind": k, "params": p, "position": {"x": 0, "y": 0}} for i, k, p in nodes],
        "edges": [{"id": f"e{n}", "source": s, "source_port": sp, "target": t, "target_port": tp}
                  for n, (s, sp, t, tp) in enumerate(edges, 1)],
    }


def layout(definition: dict[str, Any]) -> dict[str, Any]:
    """Columns by depth, rows in definition order: a readable starting layout for the editor."""
    depth: dict[str, int] = {}
    for nid in topological_order(definition):
        depth[nid] = max((depth[e["source"]] + 1 for e in upstream(definition, nid)), default=0)
    rows: dict[int, int] = {}
    for n in definition["nodes"]:
        d = depth[n["id"]]
        n["position"] = {"x": 40 + 260 * d, "y": 40 + 150 * rows.get(d, 0)}
        rows[d] = rows.get(d, 0) + 1
    return definition


# Filtlong's README example (--min_length 1000 --keep_percent 90). Flye's read type and Racon's minimap2 preset
# depend on the data (basecaller, platform), so the templates leave them for the user to choose.
_FILTLONG = {"params": {"min_length": 1000, "keep_percent": 90}}


def _long(read_type: str | None) -> list[tuple[str, str, dict]]:
    return [("long", "reads_long_input", {}), ("filtlong", "filtlong", _FILTLONG), ("flye", "flye", {}),
            ("polish", "polishing", {"strategy": "racon", "racon": {"read_type": read_type}})]


_LONG_EDGES = [("long", "reads", "filtlong", "reads"), ("filtlong", "reads", "flye", "reads"),
               ("flye", "assembly", "polish", "assembly"), ("filtlong", "reads", "polish", "long_reads")]
_ASM_IN = [("asm", "assembly_input", {"prefer": "latest_polished"})]
_ANN_IN = [("ann", "annotation_input", {"prefer": "latest_polished"})]

# The workflows of spec section 25 that ARVA's integrated tools can run. Parameters not given here take the defaults
# of the analysis's own request model when the workflow is created, so that every option is stored explicitly.
TEMPLATES: dict[str, dict[str, Any]] = {
    "bacterial_genome_complete": layout(_graph(
        [*_long(None), ("quast", "quast", {}), ("bakta", "bakta", {}), ("species", "species", {"method": "skani"}),
         ("mlst", "mlst", {}), ("amr", "amrfinderplus", {}), ("vir", "virulence", {}),
         ("mob", "mobile_elements", {"method": "mobsuite"})],
        [*_LONG_EDGES, ("polish", "assembly", "quast", "assembly"), ("polish", "assembly", "bakta", "assembly"),
         ("polish", "assembly", "species", "assembly"), ("polish", "assembly", "mlst", "assembly"),
         ("polish", "assembly", "amr", "assembly"), ("bakta", "annotation", "amr", "annotation"),
         ("polish", "assembly", "vir", "assembly"), ("polish", "assembly", "mob", "assembly")])),
    "nanopore_assembly": layout(_graph(
        [*_long("map-ont"), ("quast", "quast", {})], [*_LONG_EDGES, ("polish", "assembly", "quast", "assembly")])),
    "illumina_assembly": layout(_graph(
        [("short", "reads_short_input", {}), ("fastp", "fastp", {}), ("spades", "spades", {}),
         ("quast", "quast", {})],
        [("short", "reads", "fastp", "reads"), ("fastp", "reads", "spades", "reads"),
         ("spades", "assembly", "quast", "assembly")])),
    "hybrid_assembly": layout(_graph(
        [("short", "reads_short_input", {}), ("long", "reads_long_input", {}), ("fastp", "fastp", {}),
         ("unicycler", "unicycler", {}), ("quast", "quast", {})],
        [("short", "reads", "fastp", "reads"), ("fastp", "reads", "unicycler", "short_reads"),
         ("long", "reads", "unicycler", "long_reads"), ("unicycler", "assembly", "quast", "assembly")])),
    "amr_screening": layout(_graph(
        [*_ANN_IN, ("amr", "amrfinderplus", {})],
        [("ann", "assembly", "amr", "assembly"), ("ann", "annotation", "amr", "annotation")])),
    "virulence_screening": layout(_graph([*_ASM_IN, ("vir", "virulence", {})],
                                          [("asm", "assembly", "vir", "assembly")])),
    "comparative_genomics": layout(_graph(
        [*_ASM_IN, ("set", "comparison_set", {}), ("ani", "comparative_ani", {"method": "skani"}),
         ("aln", "comparative_alignment", {"aligner": "minimap2"})],
        [("asm", "assembly", "set", "genomes"), ("set", "set", "ani", "set"), ("set", "set", "aln", "set")])),
    "bacterial_phylogeny": layout(_graph(
        [*_ANN_IN, ("set", "comparison_set", {}),
         ("pan", "pangenome", {"method": "panaroo", "panaroo": {"alignment": "core"}}),
         ("tree", "phylogeny", {"source_kind": "core_alignment", "method": "iqtree"})],
        [("ann", "annotation", "set", "genomes"), ("set", "set", "pan", "set"),
         ("pan", "core_alignment", "tree", "alignment")])),
    "pangenome_analysis": layout(_graph(
        [*_ANN_IN, ("set", "comparison_set", {}), ("pan", "pangenome", {"method": "panaroo"})],
        [("ann", "annotation", "set", "genomes"), ("set", "set", "pan", "set")])),
    "plasmid_analysis": layout(_graph(
        [*_ASM_IN, ("mob", "mobile_elements", {"method": "mobsuite"}),
         ("pf", "mobile_elements", {"method": "plasmidfinder"})],
        [("asm", "assembly", "mob", "assembly"), ("asm", "assembly", "pf", "assembly")])),
    "mobile_element_analysis": layout(_graph(
        [*_ASM_IN, ("mob", "mobile_elements", {"method": "mobsuite"}),
         ("integron", "mobile_elements", {"method": "integronfinder"}),
         ("is", "mobile_elements", {"method": "isescan"})],
        [("asm", "assembly", "mob", "assembly"), ("asm", "assembly", "integron", "assembly"),
         ("asm", "assembly", "is", "assembly")])),
    "custom_gene_investigation": layout(_graph(
        [*_ASM_IN, ("set", "comparison_set", {}), ("gene", "gene_investigation", {})],
        [("asm", "assembly", "set", "genomes"), ("set", "set", "gene", "set")])),
}
