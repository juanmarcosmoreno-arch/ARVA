"""Bounded reading of GFA 1 assembly graphs (segments and links) for display.

Only what a graph view needs is kept: each segment's name, length and numeric tags, and each link's
ends, orientations, overlap and numeric tags. Sequences are measured and discarded. Numeric tags are
returned as the assembler wrote them, because assemblers define them differently (Flye's ``dp`` is a
mean read depth, Unicycler's ``dp`` a depth relative to the chromosome, SPAdes' ``KC`` a k-mer count);
interpreting them is left to the caller, which knows the assembler.

When the graph has more segments than ``max_nodes``, the longest are kept (ties: file order) and only
links between kept segments are returned, at most ``max_edges`` of them in file order; ``truncated``
then says that the view is partial.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arva_core.formats import open_sequence_file

GFA_ORIENTATIONS = ("+", "-")
_TAG = re.compile(r"^([A-Za-z][A-Za-z0-9]):([AifZJHB]):(.*)$")
# GFA 2 record types; their presence means the file is not GFA 1.
_GFA2_RECORDS = {"E", "G", "O", "U", "F"}


class GfaFormatError(ValueError):
    def __init__(self, message: str, line_number: int | None = None):
        self.line_number = line_number
        super().__init__(f"line {line_number}: {message}" if line_number else message)


def _numeric_tags(fields: list[str], line_no: int) -> dict[str, int | float]:
    tags: dict[str, int | float] = {}
    for field in fields:
        m = _TAG.match(field)
        if m is None:
            raise GfaFormatError(f"malformed optional field {field[:40]!r}", line_no)
        name, kind, value = m.groups()
        try:
            if kind == "i":
                tags[name] = int(value)
            elif kind == "f":
                tags[name] = float(value)
        except ValueError:
            raise GfaFormatError(f"tag {name}:{kind} has a non-numeric value {value[:40]!r}", line_no) from None
    return tags


def read_gfa(path: Path, max_nodes: int = 2000, max_edges: int = 5000) -> dict[str, Any]:
    if max_nodes < 1 or max_edges < 0:
        raise ValueError("max_nodes must be >= 1 and max_edges >= 0")
    version: str | None = None
    segments: list[tuple[str, int, dict[str, int | float]]] = []
    names: set[str] = set()
    links: list[tuple[str, str, str, str, str, dict[str, int | float]]] = []
    paths = 0
    with open_sequence_file(Path(path)) as fh:
        for line_no, raw in enumerate(fh, start=1):
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError:
                raise GfaFormatError("not UTF-8 text", line_no) from None
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            kind = fields[0]
            if kind == "H":
                for tag in fields[1:]:
                    if tag.startswith("VN:Z:"):
                        version = tag[5:]
                if version is not None and version.startswith("2"):
                    raise GfaFormatError(f"GFA {version} is not supported (GFA 1 only)", line_no)
            elif kind == "S":
                if len(fields) < 3:
                    raise GfaFormatError("segment line needs a name and a sequence (or '*')", line_no)
                name, seq = fields[1], fields[2]
                tags = _numeric_tags(fields[3:], line_no)
                if name in names:
                    raise GfaFormatError(f"segment '{name}' is defined twice", line_no)
                if seq == "*":
                    if "LN" not in tags:
                        raise GfaFormatError(f"segment '{name}' has neither a sequence nor an LN tag", line_no)
                    length = int(tags["LN"])
                else:
                    length = len(seq)
                    if "LN" in tags and tags["LN"] != length:
                        raise GfaFormatError(f"segment '{name}': LN:i:{tags['LN']} but the sequence has {length} bases", line_no)
                names.add(name)
                segments.append((name, length, tags))
            elif kind == "L":
                if len(fields) < 6:
                    raise GfaFormatError("link line needs from, orientation, to, orientation and overlap", line_no)
                if fields[2] not in GFA_ORIENTATIONS or fields[4] not in GFA_ORIENTATIONS:
                    raise GfaFormatError("link orientations must be '+' or '-'", line_no)
                links.append((fields[1], fields[2], fields[3], fields[4], fields[5], _numeric_tags(fields[6:], line_no)))
            elif kind == "P":
                paths += 1
            elif kind in _GFA2_RECORDS:
                raise GfaFormatError(f"'{kind}' records belong to GFA 2, which is not supported", line_no)

    order = sorted(range(len(segments)), key=lambda i: -segments[i][1])[:max_nodes]
    kept = {segments[i][0] for i in order}
    defined = [link for link in links if link[0] in names and link[2] in names]
    between = [link for link in defined if link[0] in kept and link[2] in kept]
    shown = between[:max_edges]
    tag_names = sorted({t for _, _, tags in segments for t in tags})
    return {
        "format": "GFA1",
        "version": version,
        "segment_count": len(segments),
        "link_count": len(links),
        "path_count": paths,
        "dangling_links": len(links) - len(defined),
        "total_segment_length": sum(length for _, length, _ in segments),
        "numeric_tags": tag_names,
        "max_nodes": max_nodes,
        "max_edges": max_edges,
        "truncated": len(order) < len(segments) or len(shown) < len(defined),
        "nodes": [{"id": segments[i][0], "length": segments[i][1], "tags": segments[i][2]} for i in order],
        "edges": [
            {"source": a, "source_orientation": ao, "target": b, "target_orientation": bo, "overlap": ov, "tags": tags}
            for a, ao, b, bo, ov, tags in shown
        ],
    }
