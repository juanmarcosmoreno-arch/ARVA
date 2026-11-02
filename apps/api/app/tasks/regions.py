"""Worker tasks for the Genome Region Explorer and Custom Gene Investigation (app.services.regions).

The genomes are checked against the contigs SHA-256 recorded when the job was created, then staged for BLAST+ with
their sequences renamed contig_1, contig_2, ... (BLAST rewrites some identifiers, e.g. "gi|..." headers; ARVA maps the
names back). Annotated proteins are staged as f<feature id> after checking the protein file's SHA-256. Everything the
tools write stays under the job's results folder; the staged copies are removed at the end.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from arva_core import newick
from arva_core import region as core
from arva_core.annotation import iter_fasta_text
from arva_core.formats import open_sequence_file
from arva_core.genome_view import reverse_complement
from arva_core.seqstats import iter_fasta
from arva_tools.blast import BlastAdapter, BlastParams, parse_tabular, sibling
from arva_tools.mafft import LINSI_MAX_SEQUENCES, MafftAdapter
from arva_tools.phylo import MIN_SEQUENCES, FasttreeAdapter, IqtreeAdapter, TreeParams
from arva_tools.registry import detect, get_adapter

from app.models import Annotation, Assembly, ComparisonResult, ComparisonSet
from app.services import amr as amr_svc
from app.services import annotation as annotation_svc
from app.services import mobile_elements as mobile_svc
from app.services import regions as svc
from app.services import virulence as virulence_svc
from app.tasks.common import JobContext, JobFailure, run_job
from app.tasks.comparative import _check, _files, _read, _run_tool
from app.tasks.tools import _resolve_tool, _sha256

INPUT_DIR = "input"


def _set(ctx: JobContext) -> ComparisonSet:
    cset = ctx.db.get(ComparisonSet, ctx.job.parameters["set_id"])
    if cset is None:
        raise JobFailure("The comparison set was deleted", "comparison_set_missing")
    return cset


def _stage(ctx: JobContext, results: Path) -> list[dict[str, Any]]:
    staged = []
    (results / INPUT_DIR).mkdir(parents=True)
    for n, g in enumerate(ctx.job.parameters["genomes"], 1):
        a = ctx.db.get(Assembly, g["assembly_id"])
        if a is None:
            raise JobFailure(f"Assembly {g['assembly_id']} ({g['label']}) no longer exists", "assembly_missing",
                             assembly=g["label"])
        src = ctx.path(a.contigs_path)
        if not src.is_file():
            raise JobFailure(f"The contigs file of {g['label']} is missing on disk", "contigs_missing",
                             assembly=g["label"])
        if (digest := _sha256(src)) != g["contigs_sha256"]:
            raise JobFailure(f"The contigs of {g['label']} changed since the job was created (sha256 {digest})",
                             "contigs_changed", assembly=g["label"])
        dest = results / INPUT_DIR / f"g{n}.fna"
        info = annotation_svc.stage_genome(src, dest, True)
        with open_sequence_file(dest) as fh:
            seqs = {h[1:].decode().split()[0]: s for h, s, _q, _l in iter_fasta(fh)}
        to_staged = {c["original_name"]: c["name"] for c in info["contigs"]}
        ctx.log(f"Genome {n} '{g['label']}': contigs sha256 {digest}; {len(seqs)} sequences staged as "
                f"{INPUT_DIR}/{dest.name} (sha256 {info['sha256']}, renamed contig_1..contig_{len(seqs)})")
        staged.append({**g, "index": n - 1, "file": f"{INPUT_DIR}/{dest.name}", "staged_sha256": info["sha256"],
                       "seqs": seqs, "to_staged": to_staged,
                       "to_assembly": {v: k for k, v in to_staged.items()}, "total_length": info["total_length"]})
    ctx.check_cancelled()
    return staged


def _snapshot(staged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = ("assembly_id", "label", "sample_id", "sample_code", "project_id", "kind", "assembler",
            "assembler_version", "contigs_sha256", "staged_sha256", "total_length", "synthetic_evidence",
            "annotation")
    return [{k: g.get(k) for k in keep} | {"contig_count": len(g["seqs"])} for g in staged]


def _annotation(ctx: JobContext, g: dict[str, Any]) -> Annotation | None:
    rec = g.get("annotation")
    if not rec:
        return None
    a = ctx.db.get(Annotation, rec["annotation_id"])
    if a is None:
        raise JobFailure(f"The annotation of {g['label']} was deleted", "region_annotation_missing",
                         assembly=g["label"])
    return a


def _proteins(ctx: JobContext, g: dict[str, Any], a: Annotation) -> dict[int, str]:
    """The annotated proteins of a genome by ARVA feature id, after checking the protein file is the one recorded."""
    entry = (a.files or {}).get("faa")
    path = ctx.path(entry["path"]) if entry else None
    if path is None or not path.is_file():
        raise JobFailure(f"{a.tool}'s protein file of {g['label']} is missing", "region_proteins_missing",
                         assembly=g["label"])
    if entry.get("sha256") and _sha256(path) != entry["sha256"]:
        raise JobFailure(f"{a.tool}'s protein file of {g['label']} changed since it was written",
                         "region_proteins_changed", assembly=g["label"])
    by_id = {h.split()[0]: s.rstrip("*") for h, s in iter_fasta_text(path.read_text())}
    out = {}
    for f in annotation_svc.features_of(a):
        if f["type"] in core.CODING:
            seq = by_id.get(f.get("locus_tag") or "") or by_id.get(f.get("tool_id") or "")
            if seq:
                out[f["id"]] = seq
    return out


def _fasta(path: Path, records: list[tuple[str, str]]) -> Path:
    path.write_text("".join(f">{name}\n{seq}\n" for name, seq in records))
    return path


class _Blast:
    def __init__(self, ctx: JobContext, exe: str, results: Path, threads: int):
        self.ctx, self.results, self.threads = ctx, results, threads
        self.exe = {p: sibling(exe, p) for p in ("makeblastdb", "blastn", "tblastn", "blastp")}
        self.n = 0

    def db(self, fasta: str, dbtype: str, name: str) -> str:
        (self.results / "blastdb").mkdir(exist_ok=True)
        out = f"blastdb/{name}"
        _run_tool(self.ctx, "makeblastdb", BlastAdapter.makeblastdb_argv(self.exe["makeblastdb"], fasta, dbtype, out),
                  self.results, f"blastdb/{name}.log")
        return out

    def search(self, program: str, task: str, evalue: float, query: str, name: str, db: str | None = None,
               subject: str | None = None, max_target_seqs: int = 500) -> tuple[list[dict[str, Any]], Path]:
        (self.results / "blast").mkdir(exist_ok=True)
        params = BlastParams(program=program, task=task, evalue=evalue, max_target_seqs=max_target_seqs,
                             threads=self.threads)
        out = f"blast/{name}.tsv"
        argv = _check(program, lambda: BlastAdapter.search_argv(self.exe[program], params, query, out, db=db,
                                                                 subject=subject))
        _run_tool(self.ctx, program, argv, self.results, f"blast/{name}.log")
        return _read(program, self.results / out, parse_tabular), self.results / out


def _cleanup(results: Path) -> None:
    for d in (INPUT_DIR, "blastdb"):
        shutil.rmtree(results / d, ignore_errors=True)


def _tested(tool_id: str, version: str | None) -> list[dict[str, Any]]:
    adapter = get_adapter(tool_id)
    if version in adapter.info.tested_versions:
        return []
    return [{"code": "tool_not_validated", "params": {"tool": adapter.info.name, "version": version}}]


def _store(ctx: JobContext, cset: ComparisonSet, analysis: str, method: str, staged: list[dict[str, Any]],
           summary: dict[str, Any], warnings: list[dict[str, Any]], files: dict[str, Any]) -> None:
    job = ctx.job
    result = ComparisonResult(set_id=cset.id, job_id=job.id, analysis=analysis, method=method, tool=job.tool_name,
                              tool_version=job.tool_version, parameters=job.parameters.get("settings") or {},
                              genomes=_snapshot(staged), summary=summary, warnings=warnings, files=files)
    ctx.db.add(result)
    ctx.db.flush()
    job.result_summary = {"comparison_result_id": result.id, "set_id": cset.id, "analysis": analysis,
                          "method": method, "warnings": [w["code"] for w in warnings], "files": files}
    job.output_paths = [f["path"] for f in files.values()]


# --- Region Explorer ----------------------------------------------------------------------------------------------

def _marks(ctx: JobContext, a: Annotation, contig: str, lo: int, hi: int) -> tuple[list[dict[str, Any]], dict]:
    """AMR, virulence and mobile-element calls of the genome's latest runs that lie in the window, and the runs."""
    out, runs = [], {}
    amr = amr_svc.annotation_hits(ctx.db, a, None)
    vir = virulence_svc.annotation_hits(ctx.db, a)
    mob = mobile_svc.annotation_elements(ctx.db, a)
    if amr["run"]:
        runs["amr"] = {"job_id": amr["run"]["job_id"], "tool_version": amr["run"]["tool_version"],
                       "database_version": amr["run"]["database_version"]}
    if vir["run"]:
        runs["virulence"] = {"job_id": vir["run"]["job_id"], "tool_version": vir["run"]["tool_version"],
                             "database_version": vir["run"]["database_version"]}
    runs["mobile"] = {m: {"job_id": r["job_id"], "tool_version": r.get("tool_version")}
                      for m, r in mob["runs"].items() if r}
    for h in amr["hits"]:
        out.append({"kind": "amr", "label": h["element_symbol"], "detail": h.get("element_name"),
                    "contig": h["contig"], "start": h["start"], "end": h["end"], "strand": h["strand"],
                    "feature_id": (h.get("feature") or {}).get("feature_id"), "source": "AMRFinderPlus"})
    for h in vir["hits"]:
        out.append({"kind": "virulence", "label": h["gene"], "detail": h.get("source"), "contig": h["contig"],
                    "start": h["start"], "end": h["end"], "strand": h["strand"],
                    "feature_id": (h.get("feature") or {}).get("feature_id"), "source": f"ABRicate {h.get('source')}"})
    for e in mob["elements"]:
        if e.get("category") == "plasmid_contig":
            continue
        out.append({"kind": "mobile", "label": e.get("element") or e.get("category"), "detail": e.get("category"),
                    "contig": e["contig"], "start": e["start"], "end": e["end"], "strand": e.get("strand"),
                    "feature_id": (e.get("feature") or {}).get("feature_id"), "source": e.get("method")})
    return [m for m in out if m["contig"] == contig and m["start"] is not None and m["end"] >= lo
            and m["start"] <= hi], runs


def _region_body(ctx: JobContext) -> None:
    p = ctx.job.parameters
    cset = _set(ctx)
    s = p["settings"]
    exe = _resolve_tool(ctx, "blast")
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, results)
    blast = _Blast(ctx, exe, results, s["threads"])
    anchor = p["anchor"]
    focus = staged[0]
    annotations = [_annotation(ctx, g) for g in staged]
    proteins: dict[int, dict[int, str]] = {}
    seq = focus["seqs"][focus["to_staged"][anchor["contig"]]]
    anchor_nt = seq[anchor["start"] - 1:anchor["end"]]
    if anchor["strand"] == "-":
        anchor_nt = reverse_complement(anchor_nt)
    _fasta(results / INPUT_DIR / "anchor.fna", [("anchor", anchor_nt.decode())])
    if anchor["protein"]:
        proteins[0] = _proteins(ctx, focus, annotations[0])
        if anchor["feature_id"] not in proteins[0]:
            raise JobFailure("The gene's protein is not in the annotator's protein file", "region_anchor_protein")
        _fasta(results / INPUT_DIR / "anchor.faa", [("anchor", proteins[0][anchor["feature_id"]])])
    loc = s["locate"]
    tracks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = _tested("blast", ctx.job.tool_version)
    for g, a in zip(staged, annotations, strict=True):
        located: dict[str, Any] | None
        copies = 0
        if g["index"] == 0:
            located = {"contig_in_assembly": anchor["contig"], "start": anchor["start"], "end": anchor["end"],
                       "strand": anchor["strand"], "by": "anchor", "hit": None}
        elif g["locate_by"] == "blastp":
            proteins[g["index"]] = prots = _proteins(ctx, g, a)
            faa = _fasta(results / INPUT_DIR / f"p{g['index'] + 1}.faa",
                         [(f"f{fid}", sq) for fid, sq in prots.items()])
            db = blast.db(f"{INPUT_DIR}/{faa.name}", "prot", f"p{g['index'] + 1}")
            rows, _ = blast.search("blastp", "blastp", loc["evalue"], f"{INPUT_DIR}/anchor.faa",
                                   f"locate_g{g['index'] + 1}", db=db)
            hits = core.best_protein_hit(rows, loc["min_identity"], loc["min_coverage"])
            copies = len(hits)
            located = None
            if hits:
                fid = int(hits[0]["subject"][1:])
                f = next(x for x in annotation_svc.features_of(a) if x["id"] == fid)
                names = annotation_svc.original_names(a)
                located = {"contig_in_assembly": names.get(f["contig"], f["contig"]), "start": f["start"],
                           "end": f["end"], "strand": f["strand"], "by": "blastp", "hit": hits[0],
                           "feature_id": fid}
        else:
            db = blast.db(g["file"], "nucl", f"g{g['index'] + 1}")
            rows, _ = blast.search("blastn", s["blastn_task"], loc["evalue"], f"{INPUT_DIR}/anchor.fna",
                                   f"locate_g{g['index'] + 1}", db=db)
            matches = core.chain_matches(rows, min_identity=loc["min_identity"], min_coverage=loc["min_coverage"],
                                         complete_coverage=100, max_gap=0)
            copies = len(matches)
            located = None
            if matches:
                m = matches[0]
                located = {"contig_in_assembly": g["to_assembly"][m["subject"]], "start": m["start"],
                           "end": m["end"], "strand": m["strand"], "by": "blastn",
                           "hit": {k: m[k] for k in ("identity", "query_coverage", "evalue", "bitscore", "kind")}}
        track: dict[str, Any] = {"label": g["label"], "assembly_id": g["assembly_id"], "sample_id": g["sample_id"],
                                 "annotation_id": a.id if a else None, "annotated": a is not None,
                                 "located_by": located["by"] if located else "not_found",
                                 "hit": located["hit"] if located else None, "copies": copies, "features": [],
                                 "elements": []}
        if located is None:
            ctx.log(f"{g['label']}: no homologue passing the thresholds")
            tracks.append(track)
            continue
        contig_asm = located["contig_in_assembly"]
        length = len(g["seqs"][g["to_staged"][contig_asm]])
        win = core.window(located["start"], located["end"], s["flank"], length)
        flip = located["strand"] == "-"
        track.update({"contig": contig_asm, "contig_length": length, **win, "anchor_start": located["start"],
                      "anchor_end": located["end"], "anchor_strand": located["strand"], "flipped": flip,
                      "anchor_feature_id": located.get("feature_id") or (anchor["feature_id"] if g["index"] == 0
                                                                         else None)})
        if a is not None:
            to_ann = {s_["original_id"] if s_.get("original_id") else s_["id"]: s_["id"] for s_ in a.sequences}
            ann_contig = to_ann.get(contig_asm, contig_asm)
            track["features"] = core.track_features(annotation_svc.features_of(a), ann_contig, win["start"],
                                                    win["end"], located["start"], located["end"], flip)
            marks, runs = _marks(ctx, a, ann_contig, win["start"], win["end"])
            track["runs"] = runs
            by_id = {f["id"]: f for f in track["features"]}
            for m in marks:
                rel = core.to_relative(max(m["start"], win["start"]), min(m["end"], win["end"]), located["start"],
                                       located["end"], flip)
                entry = {k: m[k] for k in ("kind", "label", "detail", "source", "start", "end", "strand")}
                if m["feature_id"] in by_id:
                    by_id[m["feature_id"]].setdefault("marks", []).append(entry)
                else:
                    track["elements"].append({**entry, "rel_start": rel[0], "rel_end": rel[1]})
        ctx.log(f"{g['label']}: {track['located_by']} → {contig_asm}:{located['start']}-{located['end']} "
                f"({located['strand']}); window {win['start']:,}-{win['end']:,}; {len(track['features'])} features"
                + (f"; {copies} copies pass the thresholds (the best is drawn)" if copies > 1 else ""))
        tracks.append(track)
        ctx.check_cancelled()
    drawn = [t for t in tracks if t["located_by"] != "not_found"]
    # Homology groups over every window's proteins.
    records = []
    for t, g in zip(tracks, staged, strict=True):
        if t["located_by"] == "not_found" or not t["annotated"]:
            continue
        prots = proteins.get(g["index"]) or _proteins(ctx, g, annotations[g["index"]])
        proteins[g["index"]] = prots
        for f in t["features"]:
            if f["id"] in prots:
                records.append((f"t{g['index']}_{f['id']}", prots[f["id"]]))
    groups_out: list[dict[str, Any]] = []
    if records:
        _fasta(results / INPUT_DIR / "windows.faa", records)
        db = blast.db(f"{INPUT_DIR}/windows.faa", "prot", "windows")
        rows, _ = blast.search("blastp", "blastp", loc["evalue"], f"{INPUT_DIR}/windows.faa", "groups", db=db,
                               max_target_seqs=max(500, len(records)))
        gr = s["groups"]
        group_of = core.homology_groups([r[0] for r in records], rows, gr["min_identity"], gr["min_coverage"])
        members: dict[int, list[dict[str, Any]]] = {}
        for t, g in zip(tracks, staged, strict=True):
            for f in t["features"]:
                key = f"t{g['index']}_{f['id']}"
                if key in group_of:
                    f["group"] = group_of[key]
                    members.setdefault(group_of[key], []).append(f)
        anchor_group = next((f.get("group") for f in tracks[0]["features"] if f["id"] == anchor["feature_id"]), None)
        for gid in sorted(members):
            fs = members[gid]
            groups_out.append({"id": gid, "name": core.group_name(fs), "size": len(fs),
                               "tracks": sum(1 for t in tracks if any(f.get("group") == gid for f in t["features"])),
                               "anchor": gid == anchor_group})
    # Identity links between neighbouring drawn tracks.
    links = []
    for i in range(len(drawn) - 1):
        up, low = drawn[i], drawn[i + 1]
        names = []
        for n, t in ((i, up), (i + 1, low)):
            g = next(x for x in staged if x["assembly_id"] == t["assembly_id"])
            sq = g["seqs"][g["to_staged"][t["contig"]]][t["start"] - 1:t["end"]]
            names.append(_fasta(results / INPUT_DIR / f"w{n + 1}.fna", [(f"w{n + 1}", sq.decode())]))
        rows, _ = blast.search("blastn", s["blastn_task"], loc["evalue"], f"{INPUT_DIR}/{names[0].name}",
                               f"links_{i + 1}_{i + 2}", subject=f"{INPUT_DIR}/{names[1].name}")
        ln = s["links"]
        links.append({"upper": i, "lower": i + 1,
                      "links": core.links(rows, up, low, ln["min_identity"], ln["min_length"])})
    if any(t["located_by"] == "not_found" for t in tracks):
        warnings.append({"code": "region_not_found", "params": {
            "genomes": ", ".join(t["label"] for t in tracks if t["located_by"] == "not_found")}})
    if many := [f"{t['label']} ({t['copies']})" for t in tracks if t["copies"] > 1]:
        warnings.append({"code": "region_several_copies", "params": {"genomes": ", ".join(many)}})
    if clipped := [t["label"] for t in drawn if t["clipped_left"] or t["clipped_right"]]:
        warnings.append({"code": "region_window_clipped", "params": {"genomes": ", ".join(clipped)}})
    if unannotated := [t["label"] for t in drawn if not t["annotated"]]:
        warnings.append({"code": "region_unannotated", "params": {"genomes": ", ".join(unannotated)}})
    data = {"anchor": anchor, "flank": s["flank"], "tracks": tracks, "groups": groups_out, "links": links,
            "settings": s, "notes": {"heuristic": svc.HEURISTIC_NOTE, "transfer": svc.TRANSFER_NOTE}}
    (results / "region.json").write_text(json.dumps(data, separators=(",", ":")))
    outputs = [results / "region.json", *sorted((results / "blast").glob("*"))]
    files = _files(ctx, outputs)
    _cleanup(results)
    summary = {"anchor": {k: anchor[k] for k in ("kind", "contig", "start", "end", "strand", "gene", "locus_tag",
                                                  "product")},
               "reference": staged[0]["label"], "flank": s["flank"],
               "tracks": [{k: t.get(k) for k in ("label", "located_by", "hit", "copies", "contig", "start", "end",
                                                 "flipped", "annotated")} for t in tracks],
               "groups": len(groups_out), "links": sum(len(x["links"]) for x in links)}
    _store(ctx, cset, "region", "blast", staged, summary, warnings, files)


def run_region_explorer_job(job_id: str) -> str:
    return run_job(job_id, _region_body)


# --- Custom Gene Investigation ------------------------------------------------------------------------------------

def _nearby(ctx: JobContext, g: dict[str, Any], contig: str, start: int, end: int, distance: int) -> tuple[list, bool]:
    """Mobile elements of the genome's latest runs within `distance` bp of [start, end] on the same contig
    (assembly names), and whether MOB-suite called the contig a plasmid."""
    near, plasmid = [], False
    for method, job in mobile_svc.latest_runs(ctx.db, g["assembly_id"], g["sample_id"]).items():
        for r in mobile_svc._rows(ctx.db, job) or []:
            if r.contig != contig:
                continue
            if r.category == "contig":
                plasmid = plasmid or r.element_type == "plasmid"
                continue
            if r.start is None or r.end is None:
                continue
            gap = max(r.start - end, start - r.end, 0)
            if gap <= distance:
                near.append({"element": r.element, "category": r.category, "element_type": r.element_type,
                             "method": method, "tool": r.tool, "start": r.start, "end": r.end, "strand": r.strand,
                             "distance": gap, "job_id": job.id})
    near.sort(key=lambda e: (e["distance"], e["start"]))
    return near, plasmid


def _feature(a: Annotation | None, contig: str, start: int, end: int, strand: str) -> dict[str, Any] | None:
    if a is None:
        return None
    to_ann = {s.get("original_id") or s["id"]: s["id"] for s in a.sequences}
    features = [f for f in annotation_svc.features_of(a) if f["type"] in core.CODING]
    return amr_svc.link_feature(features, to_ann.get(contig, contig), start, end, strand, a.id)


def _hit_sequence(g: dict[str, Any], m: dict[str, Any]) -> str:
    seq = g["seqs"][m["subject"]]
    parts = [seq[p["s_lo"] - 1:p["s_hi"]] for p in sorted(m["pieces"], key=lambda p: p["s_lo"])]
    joined = b"".join(parts)
    return (reverse_complement(joined) if m["strand"] == "-" else joined).decode()


def _tool_path(tool_id: str) -> tuple[str, str]:
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        raise JobFailure(f"{d.info.name} is not available on this worker ({d.status.value}): {d.message}",
                         "tool_unavailable", tool=d.info.name, status=d.status.value, message=d.message)
    return d.path, d.version or "unknown"


def _gene_body(ctx: JobContext) -> None:
    p = ctx.job.parameters
    cset = _set(ctx)
    s = p["settings"]
    q = p["query"]
    exe = _resolve_tool(ctx, "blast")
    results = ctx.path(ctx.results_rel)
    staged = _stage(ctx, results)
    blast = _Blast(ctx, exe, results, s["threads"])
    suffix = "fna" if q["molecule"] == "nucleotide" else "faa"
    if hashlib.sha256(q["sequence"].encode()).hexdigest() != q["sha256"]:
        raise JobFailure("The query sequence does not match its recorded SHA-256", "gene_query_changed")
    query_file = _fasta(results / f"query.{suffix}", [("query", q["sequence"])])
    tools = [{"name": ctx.job.tool_name, "version": ctx.job.tool_version, "path": exe}]
    warnings = _tested("blast", ctx.job.tool_version)
    genomes_out = []
    for g in staged:
        a = _annotation(ctx, g)
        db = blast.db(g["file"], "nucl", f"g{g['index'] + 1}")
        rows, _ = blast.search(s["program"], s["task"], s["evalue"], query_file.name, f"g{g['index'] + 1}", db=db,
                               max_target_seqs=s["max_target_seqs"])
        matches = core.chain_matches(rows, min_identity=s["min_identity"], min_coverage=s["min_coverage"],
                                     complete_coverage=s["complete_coverage"], max_gap=s["max_gap"])
        for m in matches:
            m["contig"] = g["to_assembly"][m["subject"]]
            m["feature"] = _feature(a, m["contig"], m["start"], m["end"], m["strand"])
            m["mobile"], m["on_plasmid_contig"] = _nearby(ctx, g, m["contig"], m["start"], m["end"],
                                                          s["mobile_distance"])
        genomes_out.append({"label": g["label"], "assembly_id": g["assembly_id"], "sample_id": g["sample_id"],
                            "annotation_id": a.id if a else None, "hsps": len(rows),
                            "hsps_above_identity": sum(1 for r in rows if r["pident"] >= s["min_identity"]),
                            "matches": matches, "_g": g})
        kinds = {k: sum(1 for m in matches if m["kind"] == k) for k in ("complete", "partial", "split")}
        ctx.log(f"{g['label']}: {len(rows)} HSP(s); {len(matches)} match(es) passing the thresholds "
                f"({kinds['complete']} complete, {kinds['partial']} partial, {kinds['split']} split)")
        ctx.check_cancelled()
    alignment = tree = None
    outputs = [results / "gene.json", query_file]
    al = s.get("alignment")
    if al:
        records = [("query", q["sequence"], "query", None)] if al["include_query"] else []
        for gout in genomes_out:
            for m in gout["matches"]:
                if m["kind"] in al["kinds"]:
                    records.append((f"{gout['label']} copy {m['copy']}", _hit_sequence(gout["_g"], m), gout["label"],
                                    m["copy"]))
        names = {f"s{i}": r[0] for i, r in enumerate(records, 1)}
        alignment = {"sequences": [{"id": f"s{i}", "label": r[0], "genome": r[2], "copy": r[3], "length": len(r[1])}
                                   for i, r in enumerate(records, 1)], "status": "not_run"}
        if len(records) < 2:
            alignment["status"] = "too_few"
            warnings.append({"code": "gene_alignment_too_few", "params": {"count": len(records)}})
        elif al["strategy"] == "linsi" and len(records) > LINSI_MAX_SEQUENCES:
            alignment["status"] = "too_many_for_linsi"
            warnings.append({"code": "gene_alignment_too_many", "params": {"count": len(records),
                                                                           "max": LINSI_MAX_SEQUENCES}})
        else:
            mafft, version = _tool_path("mafft")
            tools.append({"name": "MAFFT", "version": version, "path": mafft})
            warnings += _tested("mafft", version)
            (results / "alignment").mkdir()
            _fasta(results / "alignment" / "input.fna", [(f"s{i}", r[1]) for i, r in enumerate(records, 1)])
            out = results / "alignment" / "aligned_ids.fna"
            argv = _check("MAFFT", lambda: MafftAdapter.argv(mafft, al["strategy"], "nucleotide", s["threads"],
                                                               "input.fna"))
            _run_tool(ctx, "MAFFT", argv, results / "alignment", "mafft.log", stdout=out)
            aligned = list(iter_fasta_text(_read("MAFFT", out, lambda t: t)))
            if sorted(h.split()[0] for h, _ in aligned) != sorted(names) or len({len(x) for _, x in aligned}) != 1:
                raise JobFailure("MAFFT's output does not hold every sequence at one aligned length",
                                 "output_unreadable", tool="MAFFT", detail="aligned sequences")
            labelled = results / "alignment" / "alignment.fasta"
            _fasta(labelled, [(names[h.split()[0]], x) for h, x in aligned])
            alignment.update({"status": "aligned", "columns": len(aligned[0][1]), "strategy": al["strategy"],
                              "mafft_version": version})
            outputs += [labelled, out, results / "alignment" / "mafft.log"]
            ctx.check_cancelled()
            tr = s.get("tree")
            if tr:
                unique = len({x for _, x in aligned})
                tree = {"method": tr["method"], "status": "not_run", "sequences": len(aligned),
                        "unique_sequences": unique}
                if len(aligned) < MIN_SEQUENCES:
                    tree["status"] = "too_few"
                    warnings.append({"code": "gene_tree_too_few", "params": {"count": len(aligned),
                                                                             "min": MIN_SEQUENCES}})
                else:
                    tool_id = tr["method"]
                    texe, tversion = _tool_path(tool_id)
                    tools.append({"name": get_adapter(tool_id).info.name, "version": tversion, "path": texe})
                    warnings += _tested(tool_id, tversion)
                    params = TreeParams(**{**tr, "threads": s["threads"]})
                    (results / "tree").mkdir()
                    shutil.copyfile(out, results / "tree" / "alignment.fna")
                    if tool_id == "iqtree":
                        argv = _check("IQ-TREE", lambda: IqtreeAdapter.argv(texe, params, "nucleotide",
                                                                             "alignment.fna", "gene"))
                        _run_tool(ctx, "IQ-TREE", argv, results / "tree", "iqtree.log")
                        tree_file = results / "tree" / "gene.treefile"
                        report = results / "tree" / "gene.iqtree"
                        model = None
                        if report.is_file():
                            for line in report.read_text(errors="replace").splitlines():
                                if line.startswith("Best-fit model according to"):
                                    model = line.split(":", 1)[1].strip()
                                elif line.startswith("Model of substitution:") and model is None:
                                    model = line.split(":", 1)[1].strip()
                        tree.update({"model": model, "support": "UFBoot (%)", "support_max": 100})
                        outputs += [report, results / "tree" / "gene.log"]
                    else:
                        argv = _check("FastTree", lambda: FasttreeAdapter.argv(texe, params, "nucleotide",
                                                                                "alignment.fna", "gene.nwk"))
                        _run_tool(ctx, "FastTree", argv, results / "tree", "fasttree.log")
                        tree_file = results / "tree" / "gene.nwk"
                        tree.update({"model": "GTR+CAT, Gamma20 likelihoods", "support": "SH-like local support",
                                     "support_max": 1})
                        outputs.append(results / "tree" / "fasttree.log")
                    try:
                        parsed = newick.rename(_read(tree["method"], tree_file, newick.parse), names)
                    except newick.NewickError as exc:
                        raise JobFailure(f"The tree file cannot be read: {exc}", "output_unreadable",
                                         tool=tree["method"], detail=str(exc)) from exc
                    named = results / "tree" / "gene_tree.nwk"
                    named.write_text(newick.write(parsed) + "\n")
                    (results / "tree" / "alignment.fna").unlink()
                    tree.update({"status": "built", "tool_version": tversion, "newick": newick.write(parsed),
                                 "tree": parsed})
                    if unique < len(aligned):
                        warnings.append({"code": "gene_tree_identical", "params": {"count": len(aligned) - unique}})
                    outputs += [named, tree_file]
    for gout in genomes_out:
        gout.pop("_g")
    data = {"query": {k: q[k] for k in ("id", "name", "molecule", "length", "sha256", "source")},
            "program": s["program"], "task": s["task"], "genomes": genomes_out, "alignment": alignment, "tree": tree,
            "settings": s, "tools": tools,
            "notes": {"heuristic": svc.HEURISTIC_NOTE, "transfer": svc.TRANSFER_NOTE}}
    (results / "gene.json").write_text(json.dumps(data, separators=(",", ":")))
    outputs += sorted((results / "blast").glob("*"))
    if absent := [x["label"] for x in genomes_out if not x["matches"]]:
        warnings.append({"code": "gene_absent", "params": {"genomes": ", ".join(absent)}})
    if edge := [x["label"] for x in genomes_out if any(m["at_contig_edge"] for m in x["matches"])]:
        warnings.append({"code": "gene_contig_edge", "params": {"genomes": ", ".join(edge)}})
    files = _files(ctx, outputs)
    _cleanup(results)
    summary = {"query": data["query"], "program": s["program"], "task": s["task"], "tools": tools,
               "genomes": [{"label": x["label"], "matches": len(x["matches"]),
                            **{k: sum(1 for m in x["matches"] if m["kind"] == k) for k in ("complete", "partial",
                                                                                         "split")},
                            "best_identity": max((m["identity"] for m in x["matches"]), default=None),
                            "best_coverage": max((m["query_coverage"] for m in x["matches"]), default=None),
                            "near_mobile": sum(1 for m in x["matches"] if m["mobile"])} for x in genomes_out],
               "alignment": {k: v for k, v in (alignment or {}).items() if k != "sequences"} or None,
               "tree": {k: v for k, v in (tree or {}).items() if k not in ("tree", "newick")} or None}
    _store(ctx, cset, "gene", s["program"], staged, summary, warnings, files)


def run_gene_investigation_job(job_id: str) -> str:
    return run_job(job_id, _gene_body)
