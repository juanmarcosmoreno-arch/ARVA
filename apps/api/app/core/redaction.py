"""What may leave this computer in an error log entry or a diagnostic report, and what never does.

Every text a log entry or a report holds passes through `redact`: the user's home folder becomes ~, credentials in
URLs and secret-looking assignments become ***, e-mail addresses, Mac serial numbers and hardware UUIDs are replaced,
and anything that looks like sequence data (nucleotide or protein runs, long unbroken tokens such as quality strings
or encoded blobs) is replaced by its length. `redact_value` applies it to nested data and blanks every value whose
key names a secret. Over-redaction is the intended failure mode.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_NAME = re.compile(
    r"password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|credential|private[_-]?key|authorization|cookie|"
    r"database_url|redis_url|dsn", re.IGNORECASE)
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@'\"]*@")
_ASSIGNMENT = re.compile(
    r"(?i)\b([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|credential|private[_-]?key|"
    r"authorization|cookie)[\w.-]*[\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&\"'}\])]+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_KNOWN_TOKEN = re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-|xox[abprs]-|glpat-|AKIA)[A-Za-z0-9_-]{12,}")
_EMAIL = re.compile(r"(?i)(?<![\w.%+-])[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b")
_HOME = re.compile(r"(?<![\w.~-])/(?:Users|home)/[^/\s:'\"`]+")
_SERIAL = re.compile(r"(?i)(serial[\s_-]*(?:number)?(?:\s*\([^)]{0,20}\))?[\"']?\s*[:=]\s*[\"']?)[A-Z0-9]{6,20}")
_HARDWARE_ID = re.compile(r"(?i)((?:hardware|platform|provisioning)[\s_-]*u[ud]id[\"']?\s*[:=]\s*[\"']?)[0-9A-F-]{20,40}")
_NUCLEOTIDES = re.compile(r"(?i)(?<![a-z])[acgtun]{20,}(?![a-z])")
_PROTEIN = re.compile(r"(?<![A-Za-z])[ACDEFGHIKLMNPQRSTVWY]{30,}(?![A-Za-z])")
_LONG_TOKEN = re.compile(r"[^\s/]{80,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
REDACTED = "***"


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    out = _CONTROL.sub(" ", str(text))
    out = _URL_CREDENTIALS.sub(r"\1***@", out)
    out = _BEARER.sub(r"\1 ***", out)
    out = _KNOWN_TOKEN.sub("<token>", out)
    out = _ASSIGNMENT.sub(rf"\1{REDACTED}", out)
    out = _SERIAL.sub(r"\1<serial>", out)
    out = _HARDWARE_ID.sub(r"\1<hardware-id>", out)
    out = _EMAIL.sub("<email>", out)
    out = _HOME.sub("~", out)
    out = _NUCLEOTIDES.sub(lambda m: f"<sequence: {len(m.group())} letters>", out)
    out = _PROTEIN.sub(lambda m: f"<sequence: {len(m.group())} letters>", out)
    return _LONG_TOKEN.sub(lambda m: f"<{len(m.group())} characters>", out)


def clip(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f" … ({len(text) - limit} more characters)"


def tail(text: str | None, lines: int, line_chars: int = 400) -> str | None:
    """The last `lines` lines of a text, each bounded, redacted."""
    if not text:
        return None
    kept = [clip(line, line_chars) or "" for line in text.splitlines()[-lines:]]
    return redact("\n".join(kept))


def redact_value(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return "…"
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {str(k): (REDACTED if SECRET_NAME.search(str(k)) and v not in (None, "") else redact_value(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v, depth + 1) for v in value]
    return value
