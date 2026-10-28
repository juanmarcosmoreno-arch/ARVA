"""Registry of available adapters with cached detection."""
from __future__ import annotations

import time

from arva_tools.base import DetectedTool, ToolAdapter
from arva_tools.fastp import FastpAdapter
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter
from arva_tools.flye import FlyeAdapter
from arva_tools.multiqc import MultiqcAdapter
from arva_tools.nanoplot import NanoplotAdapter
from arva_tools.seqkit import SeqkitAdapter

ADAPTERS: dict[str, ToolAdapter] = {
    a.info.id: a
    for a in (SeqkitAdapter(), FastqcAdapter(), FastpAdapter(), FiltlongAdapter(), MultiqcAdapter(), NanoplotAdapter(),
              FlyeAdapter())
}

_CACHE: dict[str, tuple[float, DetectedTool]] = {}
CACHE_SECONDS = 60.0


def get_adapter(tool_id: str) -> ToolAdapter:
    try:
        return ADAPTERS[tool_id]
    except KeyError:
        raise KeyError(f"unknown tool: {tool_id}") from None


def detect(tool_id: str, refresh: bool = False) -> DetectedTool:
    now = time.monotonic()
    cached = _CACHE.get(tool_id)
    if cached and not refresh and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    result = get_adapter(tool_id).detect()
    _CACHE[tool_id] = (now, result)
    return result


def detect_all(refresh: bool = False) -> list[DetectedTool]:
    return [detect(t, refresh) for t in ADAPTERS]
