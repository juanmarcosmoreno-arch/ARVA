"""Newick trees as nested dicts: read what IQ-TREE and FastTree write, rename the leaves and write them back.

A node is {"name": str | None, "length": float | None, "support": float | None, "children": [...]}. An internal
node's label is read as its support value when it is a number (IQ-TREE's UFBoot 0-100, FastTree's SH-like 0-1;
`support_scale` says which), otherwise as its name. IQ-TREE writes several supports joined by "/" (with --alrt and
-B: "SH-aLRT/UFBoot", e.g. "97.5/100"); they are kept in "supports" and "support" holds the first. Quoted labels
('a b') are read and written as Newick specifies (a quote inside is doubled).
"""
from __future__ import annotations

import re
from typing import Any

MAX_DEPTH = 10_000
_UNQUOTED = re.compile(r"[A-Za-z0-9_.|/-]+")


class NewickError(ValueError):
    pass


def parse(text: str) -> dict[str, Any]:
    s = text.strip()
    if not s.endswith(";"):
        raise NewickError("a Newick tree ends with ';'")
    pos = 0

    def label() -> str:
        nonlocal pos
        if s[pos] == "'":
            out, pos = [], pos + 1
            while pos < len(s):
                if s[pos] == "'":
                    if s[pos + 1:pos + 2] == "'":
                        out.append("'")
                        pos += 2
                        continue
                    pos += 1
                    return "".join(out)
                out.append(s[pos])
                pos += 1
            raise NewickError("unterminated quoted label")
        start = pos
        while s[pos] not in ",():;[":
            pos += 1
        return s[start:pos].strip()

    def node(depth: int) -> dict[str, Any]:
        nonlocal pos
        if depth > MAX_DEPTH:
            raise NewickError("tree too deep")
        n: dict[str, Any] = {"name": None, "length": None, "support": None, "children": []}
        if s[pos] == "(":
            pos += 1
            n["children"].append(node(depth + 1))
            while s[pos] == ",":
                pos += 1
                n["children"].append(node(depth + 1))
            if s[pos] != ")":
                raise NewickError(f"expected ')' at position {pos}")
            pos += 1
        text_label = label()
        if text_label:
            if n["children"]:
                try:
                    values = [float(x) for x in text_label.split("/")]
                except ValueError:
                    n["name"] = text_label
                else:
                    n["support"] = values[0]
                    if len(values) > 1:
                        n["supports"] = values
            else:
                n["name"] = text_label
        if s[pos] == ":":
            pos += 1
            start = pos
            while s[pos] not in ",();[":
                pos += 1
            try:
                n["length"] = float(s[start:pos])
            except ValueError:
                raise NewickError(f"branch length {s[start:pos]!r} is not a number") from None
        if s[pos] == "[":
            end = s.find("]", pos)
            if end < 0:
                raise NewickError("unterminated comment")
            pos = end + 1
        return n

    try:
        root = node(0)
    except IndexError:
        raise NewickError("the tree ends too early") from None
    if pos != len(s) - 1:
        raise NewickError(f"unexpected {s[pos]!r} at position {pos}")
    return root


def leaves(node: dict[str, Any]) -> list[str]:
    if not node["children"]:
        return [node["name"] or ""]
    return [x for c in node["children"] for x in leaves(c)]


def rename(node: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    if not node["children"]:
        if node["name"] not in names:
            raise NewickError(f"leaf {node['name']!r} is not one of the aligned sequences")
        return {**node, "name": names[node["name"]]}
    return {**node, "children": [rename(c, names) for c in node["children"]]}


def _quote(name: str) -> str:
    return name if _UNQUOTED.fullmatch(name) else "'" + name.replace("'", "''") + "'"


def write(node: dict[str, Any]) -> str:
    def w(n: dict[str, Any]) -> str:
        out = ""
        if n["children"]:
            out = "(" + ",".join(w(c) for c in n["children"]) + ")"
            if n.get("supports"):
                out += "/".join(f"{v:g}" for v in n["supports"])
            elif n["support"] is not None:
                out += f"{n['support']:g}"
        elif n["name"] is not None:
            out = _quote(n["name"])
        if n["length"] is not None:
            out += f":{n['length']:.10g}"
        return out
    return w(node) + ";"
