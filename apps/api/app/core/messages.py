"""The English text of a coded message from the interface's template syntax (apps/web/src/i18n/index.ts):
`{name}` placeholders and `{n, plural, =0 {…} one {# file} other {# files}}` blocks, where `#` is the number.

The API keeps this English text next to each code as the fallback for interfaces that do not know the code; the
templates are the interface's English ones, so both say the same. No database or web imports: the POD5 reader
child process uses it too.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

_PLURAL = re.compile(r"\{(\w+), plural,")
_BRANCH = re.compile(r"\s*(=\d+|one|other)\s*\{")


def _closing(text: str, start: int) -> int:
    """Index just past the brace that closes the one at `start`."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError(f"unbalanced braces in message template: {text!r}")


def _plurals(template: str, params: Mapping[str, object]) -> str:
    out, last = [], 0
    for m in _PLURAL.finditer(template):
        if m.start() < last:
            continue
        end = _closing(template, m.start())
        n = params[m.group(1)]
        body, branches, pos = template[m.end():end - 1], {}, 0
        while b := _BRANCH.match(body, pos):
            close = _closing(body, b.end() - 1)
            branches[b.group(1)] = body[b.end():close - 1]
            pos = close
        chosen = branches.get(f"={n}") or branches["one" if n == 1 else "other"]
        out += [template[last:m.start()], chosen.replace("#", f"{n:,}" if isinstance(n, int) else str(n))]
        last = end
    return "".join(out) + template[last:]


def render(template: str, params: Mapping[str, object]) -> str:
    """The English text: plural blocks chosen by English rules (1 is singular), then placeholders filled."""
    return _plurals(template, params).format(**params) if params else template
