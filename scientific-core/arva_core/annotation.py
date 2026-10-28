"""Genome annotation features in one shape for every annotator, their summary, identifier links and subsets of the
annotators' own files.

An annotator's features are predictions: a gene finder's call, a similarity or model hit. Nothing here adds
information the annotator did not report; "hypothetical protein" stays hypothetical, and a link is made only for an
identifier the annotator wrote, with the resolver of the database that issues it.

A feature (a JSON-serialisable dict):

    id            ARVA's number for the feature within the annotation (1-based, in the annotator's order)
    tool_id       the annotator's own identifier (GFF3 ID); locus_tag its locus tag, if any
    type          one of FEATURE_TYPES; tool_type the annotator's own type name
    contig        the sequence name in the annotator's output; start <= end are 1-based and inclusive, except for a
                  feature across the origin of a circular sequence (edge: True), where start > end
    strand        "+", "-" or "."; length in bp
    gene, product as reported (None when absent)
    ec, cog, cog_categories, go   identifiers sorted out of the reported cross-references
    db_xrefs      every cross-reference as reported ("DB:ID")
    pseudo        the annotator called it a pseudogene; partial: which end is truncated, if it said so
    hypothetical  for CDS and sORFs: the annotator gave no function; None for other types
    inference     the evidence the annotator reported, in its terms
    accessions    identifiers named in that evidence ("UniProtKB:P04395"), which may get links
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

FEATURE_TYPES = ("cds", "sorf", "trna", "tmrna", "rrna", "ncrna", "ncrna_region", "crispr", "gap", "oric", "oriv",
                 "orit", "other")
CODING_TYPES = frozenset({"cds", "sorf"})
HYPOTHETICAL_PRODUCT = "hypothetical protein"
SORT_KEYS = ("position", "locus_tag", "type", "gene", "product", "length")
MAX_QUERY_LIMIT = 1000

# Resolver URL patterns, each checked on 2026-10-28 with an identifier from ARVA's fixtures. Only identifiers that
# match the database's own format get a link.
_LINKS: tuple[tuple[frozenset[str], re.Pattern[str], str], ...] = (
    (frozenset({"EC"}), re.compile(r"\d+\.\d+\.\d+\.n?\d+"), "https://enzyme.expasy.org/EC/{id}"),
    (frozenset({"GO"}), re.compile(r"GO:\d{7}"), "https://www.ebi.ac.uk/QuickGO/term/{id}"),
    (frozenset({"SO"}), re.compile(r"SO:\d{7}"), "https://identifiers.org/{id}"),
    (frozenset({"COG"}), re.compile(r"COG\d{4}"), "https://www.ncbi.nlm.nih.gov/research/cog/cog/{id}/"),
    (frozenset({"COG"}), re.compile(r"[A-Z]"), "https://www.ncbi.nlm.nih.gov/research/cog/cogcategory/{id}/"),
    (frozenset({"KEGG"}), re.compile(r"K\d{5}"), "https://www.kegg.jp/entry/{id}"),
    (frozenset({"RFAM"}), re.compile(r"RF\d{5}"), "https://rfam.org/family/{id}"),
    (frozenset({"PFAM"}), re.compile(r"PF\d{5}"), "https://www.ebi.ac.uk/interpro/entry/pfam/{id}/"),
    (frozenset({"UNIREF"}), re.compile(r"UniRef(?:50|90|100)_[A-Z0-9]{6,16}"), "https://www.uniprot.org/uniref/{id}"),
    (frozenset({"UNIPARC"}), re.compile(r"UPI[0-9A-F]{10}"), "https://www.uniprot.org/uniparc/{id}/entry"),
    (frozenset({"UNIPROTKB", "UNIPROTKB/SWISS-PROT", "UNIPROTKB/TREMBL", "SWISS-PROT", "SP"}),
     re.compile(r"[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}"),
     "https://www.uniprot.org/uniprotkb/{id}/entry"),
    (frozenset({"REFSEQ", "NCBIPROTEIN"}), re.compile(r"(?:WP|NP|YP|XP|AP)_\d{6,12}(?:\.\d+)?"),
     "https://www.ncbi.nlm.nih.gov/protein/{id}"),
)
# Identifiers written with their database prefix as part of the identifier (Bakta writes "GO:0005840").
_CURIE_DBS = frozenset({"GO", "SO"})
_COG_ID = re.compile(r"COG\d{4}")
_COG_CATEGORIES = re.compile(r"[A-Z]{1,4}")
_EC = re.compile(r"\d+\.(?:\d+|-)\.(?:\d+|-)\.(?:n?\d+|-)")


def new_feature(**values: Any) -> dict[str, Any]:
    f: dict[str, Any] = {
        "id": 0, "tool_id": None, "locus_tag": None, "type": "other", "tool_type": None, "contig": "",
        "start": 0, "end": 0, "strand": ".", "length": 0, "edge": False, "gene": None, "product": None,
        "ec": [], "cog": [], "cog_categories": [], "go": [], "db_xrefs": [], "pseudo": False, "partial": None,
        "hypothetical": None, "inference": [], "accessions": [],
    }
    unknown = set(values) - set(f)
    if unknown:
        raise KeyError(f"unknown feature fields: {', '.join(sorted(unknown))}")
    f.update(values)
    return f


def split_xref(xref: str) -> tuple[str, str] | None:
    db, sep, ident = xref.partition(":")
    if not sep or not db or not ident:
        return None
    db, ident = db.strip(), ident.strip()
    return db, f"{db}:{ident}" if db.upper() in _CURIE_DBS and not ident.startswith(f"{db}:") else ident


def xref_url(xref: str) -> str | None:
    """The resolver URL for a reported "DB:ID" cross-reference, or None when ARVA has no verified pattern for it or
    the identifier does not have the database's format."""
    parts = split_xref(xref)
    if parts is None:
        return None
    db, ident = parts[0].upper(), parts[1]
    for dbs, pattern, template in _LINKS:
        if db in dbs and pattern.fullmatch(ident):
            return template.format(id=ident)
    return None


def links(feature: dict[str, Any]) -> list[dict[str, str]]:
    """Links for the identifiers a feature's annotator reported, each once, in the order reported."""
    out, seen = [], set()
    for xref in [*feature.get("db_xrefs", []), *feature.get("accessions", [])]:
        url = xref_url(xref)
        if url and url not in seen:
            seen.add(url)
            out.append({"xref": xref, "url": url})
    return out


def sort_xrefs(xrefs: Iterable[str]) -> dict[str, list[str]]:
    """EC numbers, COG identifiers and categories, and GO terms among reported cross-references."""
    ec, cog, cats, go = [], [], [], []
    for x in xrefs:
        parts = split_xref(x)
        if parts is None:
            continue
        db, ident = parts[0].upper(), parts[1]
        if db == "EC" and _EC.fullmatch(ident):
            ec.append(ident)
        elif db == "COG" and _COG_ID.fullmatch(ident):
            cog.append(ident)
        elif db == "COG" and _COG_CATEGORIES.fullmatch(ident):
            cats.extend(ident)
        elif db == "GO" and re.fullmatch(r"GO:\d{7}", ident):
            go.append(ident)
    uniq = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    return {"ec": uniq(ec), "cog": uniq(cog), "cog_categories": uniq(cats), "go": uniq(go)}


def span_length(start: int, end: int, edge: bool, contig_length: int | None) -> int:
    if edge and start > end and contig_length:
        return contig_length - start + 1 + end
    return end - start + 1


def _intervals(f: dict[str, Any], contig_length: int | None) -> list[tuple[int, int]]:
    if f["edge"] and f["start"] > f["end"] and contig_length:
        return [(f["start"], contig_length), (1, f["end"])]
    return [(min(f["start"], f["end"]), max(f["start"], f["end"]))]


def covered_bases(features: Iterable[dict[str, Any]], lengths: dict[str, int]) -> int:
    """Bases covered by at least one of the features (overlaps counted once)."""
    by_contig: dict[str, list[tuple[int, int]]] = {}
    for f in features:
        by_contig.setdefault(f["contig"], []).extend(_intervals(f, lengths.get(f["contig"])))
    total = 0
    for spans in by_contig.values():
        spans.sort()
        cur_start, cur_end = spans[0]
        for s, e in spans[1:]:
            if s > cur_end + 1:
                total += cur_end - cur_start + 1
                cur_start, cur_end = s, e
            else:
                cur_end = max(cur_end, e)
        total += cur_end - cur_start + 1
    return total


def summarize(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]], non_n_bases: int,
              cds_searched: bool) -> dict[str, Any]:
    """Counts by type, hypothetical vs characterised CDS, cross-reference coverage and coding density.

    Coding density: bases inside at least one CDS (overlaps once), divided by the bases of the annotated sequences
    that are not N. It is None when the CDS step did not run, since 0 would then be a statement about the genome.
    """
    counts = Counter(f["type"] for f in features)
    cds = [f for f in features if f["type"] == "cds"]
    hypothetical = sum(1 for f in cds if f["hypothetical"])
    lengths = {s["id"]: s["length"] for s in sequences}
    coding = covered_bases(cds, lengths) if cds else 0
    cats = Counter(c for f in cds for c in f["cog_categories"])
    return {
        "counts": {t: counts[t] for t in FEATURE_TYPES if counts[t]},
        "features": len(features),
        "cds": len(cds) if cds_searched else None,
        "hypothetical": hypothetical if cds_searched else None,
        "characterised": len(cds) - hypothetical if cds_searched else None,
        "hypothetical_fraction": round(hypothetical / len(cds), 6) if cds_searched and cds else None,
        "pseudogenes": sum(1 for f in features if f["pseudo"]),
        "partial": sum(1 for f in cds if f["partial"]),
        "with_ec": sum(1 for f in cds if f["ec"]),
        "with_cog": sum(1 for f in cds if f["cog"]),
        "with_go": sum(1 for f in features if f["go"]),
        "with_gene": sum(1 for f in features if f["gene"]),
        "cog_categories": dict(sorted(cats.items())),
        "coding_density": {
            "value": round(coding / non_n_bases, 6) if cds_searched and non_n_bases else None,
            "cds_bases": coding if cds_searched else None,
            "non_n_bases": non_n_bases,
            "definition": "bases inside at least one CDS (overlaps counted once) / bases of the annotated sequences "
                          "that are not N",
        },
        "sequences": len(sequences),
        "total_length": sum(s["length"] for s in sequences),
    }


# --- Query --------------------------------------------------------------------------------------------------

def tool_contig(sequences: Sequence[dict[str, Any]], contig: str) -> str | None:
    """The annotator's name of a sequence given by that name or by its name in the assembly."""
    names = {s["id"]: s["id"] for s in sequences} | {s.get("original_id") or s["id"]: s["id"] for s in sequences}
    return names.get(contig)


def region_features(features: Iterable[dict[str, Any]], sequences: Sequence[dict[str, Any]], contig: str, start: int,
                    end: int) -> list[dict[str, Any]]:
    """Features of a sequence (either name) that overlap start..end (1-based, inclusive), in the annotator's order;
    a feature across the origin overlaps through either of its two parts."""
    name = tool_contig(sequences, contig)
    length = next((s["length"] for s in sequences if s["id"] == name), None)
    return [f for f in features if f["contig"] == name
            and any(s <= end and e >= start for s, e in _intervals(f, length))]


def _position_key(order: dict[str, int]):
    return lambda f: (order.get(f["contig"], len(order)), min(f["start"], f["end"]), f["id"])


def query(features: Sequence[dict[str, Any]], sequences: Sequence[dict[str, Any]], *, types: Sequence[str] = (),
          contig: str | None = None, start: int | None = None, end: int | None = None, q: str | None = None,
          hypothetical: bool | None = None, sort: str = "position", descending: bool = False, limit: int = 200,
          offset: int = 0) -> dict[str, Any]:
    """Features matching every filter: types; a contig (its name in the annotator's output or in the assembly);
    a region overlapping [start, end] on that contig; a case-insensitive text found in the locus tag, the
    annotator's ID, gene, product, an EC/COG/GO identifier or a cross-reference; and (for CDS and sORFs) whether
    the annotator called it hypothetical."""
    if sort not in SORT_KEYS:
        raise ValueError(f"sort must be one of {', '.join(SORT_KEYS)}")
    if not 1 <= limit <= MAX_QUERY_LIMIT or offset < 0:
        raise ValueError(f"limit must be 1-{MAX_QUERY_LIMIT} and offset >= 0")
    if (start is not None or end is not None) and contig is None:
        raise ValueError("a region (start, end) needs a contig")
    in_contig = None
    if contig is not None:
        in_contig = tool_contig(sequences, contig)
        if in_contig is None:
            return {"total": 0, "items": []}
    lengths = {s["id"]: s["length"] for s in sequences}
    needle = q.strip().lower() if q and q.strip() else None
    wanted = set(types)
    out = []
    for f in features:
        if wanted and f["type"] not in wanted:
            continue
        if hypothetical is not None and f["hypothetical"] is not hypothetical:
            continue
        if in_contig is not None and f["contig"] != in_contig:
            continue
        if start is not None or end is not None:
            lo, hi = start or 1, end or lengths.get(f["contig"], 0)
            if not any(s <= hi and e >= lo for s, e in _intervals(f, lengths.get(f["contig"]))):
                continue
        if needle:
            text = [f["locus_tag"], f["tool_id"], f["gene"], f["product"], *f["ec"], *f["cog"], *f["go"],
                    *f["db_xrefs"], *f["accessions"]]
            if not any(needle in str(t).lower() for t in text if t):
                continue
        out.append(f)
    pos = _position_key({s["id"]: i for i, s in enumerate(sequences)})
    if sort == "position":
        out.sort(key=pos, reverse=descending)
    else:
        present = sorted((f for f in out if f[sort] is not None), reverse=descending,
                         key=lambda f: (f[sort].lower() if isinstance(f[sort], str) else f[sort], pos(f)))
        out = present + sorted((f for f in out if f[sort] is None), key=pos)
    return {"total": len(out), "items": out[offset:offset + limit]}


# --- Files ----------------------------------------------------------------------------------------------------

def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def iter_fasta_text(text: str) -> Iterator[tuple[str, str]]:
    """(header line without '>', sequence) of every record."""
    header, parts = None, []
    for line in text.splitlines():
        if line.startswith(">"):
            if header is not None:
                yield header, "".join(parts)
            header, parts = line[1:].rstrip(), []
        elif header is not None:
            parts.append(line.strip())
    if header is not None:
        yield header, "".join(parts)


def fasta_record(path: Path, record_id: str) -> tuple[str, str] | None:
    """The first record of a FASTA file whose name (the header up to the first space) is record_id."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for header, seq in iter_fasta_text(text):
        if header and header.split(maxsplit=1)[0] == record_id:
            return header, seq
    return None


def fasta_subset(text: str, ids: set[str], width: int = 60) -> str:
    """The records of a FASTA text whose name is in ids, in file order, rewrapped to `width` columns."""
    out = []
    for header, seq in iter_fasta_text(text):
        if header and header.split(maxsplit=1)[0] in ids:
            out.append(f">{header}")
            out.extend(seq[i:i + width] for i in range(0, len(seq), width))
    return "\n".join(out) + ("\n" if out else "")


def gff3_attributes(column: str) -> dict[str, list[str]]:
    """GFF3 column 9: each tag's values, split at unescaped commas and percent-decoded."""
    attrs: dict[str, list[str]] = {}
    for part in column.strip().split(";"):
        key, sep, value = part.partition("=")
        if sep and key:
            attrs[key.strip()] = [unquote(v) for v in value.split(",")]
    return attrs


def gff3_subset(text: str, ids: set[str]) -> str:
    """The annotator's GFF3 restricted to features whose ID, Parent or locus_tag is in ids: the directives and
    comments before the first feature, the ##sequence-region lines of the sequences that keep a feature, and those
    feature lines unchanged; no ##FASTA section."""
    head, kept, regions, contigs = [], [], {}, set()
    for line in text.splitlines():
        if line.startswith("##FASTA"):
            break
        if line.startswith("##sequence-region"):
            parts = line.split()
            if len(parts) >= 2:
                regions[parts[1]] = line
            continue
        if line.startswith("#"):
            if not kept:
                head.append(line)
            continue
        cols = line.split("\t")
        if len(cols) != 9:
            continue
        attrs = gff3_attributes(cols[8])
        names = {*attrs.get("ID", []), *attrs.get("Parent", []), *attrs.get("locus_tag", [])}
        if names & ids:
            kept.append(line)
            contigs.add(cols[0])
    version = [h for h in head if h.startswith("##gff-version")] or ["##gff-version 3"]
    rest = [h for h in head if not h.startswith("##gff-version")]
    return "\n".join([*version, *rest, *(regions[c] for c in regions if c in contigs), *kept]) + "\n"


_GB_FEATURE = re.compile(r"^ {5}(\S+)\s")
_GB_LOCUS_TAG = re.compile(r'^ {21}/locus_tag="([^"]*)"')


def genbank_subset(text: str, locus_tags: set[str]) -> str:
    """The annotator's GenBank file restricted to the features whose /locus_tag is in locus_tags (plus each record's
    source feature); records without such a feature are left out. Headers and sequences are unchanged."""
    out: list[str] = []
    for record in re.split(r"(?m)^//[ \t]*$\n?", text):
        if not record.strip():
            continue
        lines = record.splitlines()
        try:
            features_at = next(i for i, ln in enumerate(lines) if ln.startswith("FEATURES"))
        except StopIteration:
            continue
        end_at = next((i for i in range(features_at + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")),
                      len(lines))
        blocks: list[list[str]] = []
        for ln in lines[features_at + 1:end_at]:
            if _GB_FEATURE.match(ln):
                blocks.append([ln])
            elif blocks:
                blocks[-1].append(ln)
        keep = []
        for block in blocks:
            key = _GB_FEATURE.match(block[0]).group(1)
            tags = {m.group(1) for ln in block if (m := _GB_LOCUS_TAG.match(ln))}
            if key == "source" or tags & locus_tags:
                keep.append(block)
        if not any(_GB_FEATURE.match(b[0]).group(1) != "source" for b in keep):
            continue
        out.extend(lines[:features_at + 1])
        out.extend(ln for b in keep for ln in b)
        out.extend(lines[end_at:])
        out.append("//")
    return "\n".join(out) + ("\n" if out else "")
