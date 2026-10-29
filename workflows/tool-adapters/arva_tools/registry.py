"""Registry of available adapters with cached detection."""
from __future__ import annotations

import time

from arva_tools.abricate import AbricateAdapter
from arva_tools.amrfinderplus import AmrfinderplusAdapter
from arva_tools.bakta import BaktaAdapter
from arva_tools.base import DetectedTool, ToolAdapter
from arva_tools.dnadiff import DnadiffAdapter
from arva_tools.fastani import FastaniAdapter
from arva_tools.fastp import FastpAdapter
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter
from arva_tools.flye import FlyeAdapter
from arva_tools.genomad import GenomadAdapter
from arva_tools.gtdbtk import GtdbtkAdapter
from arva_tools.integronfinder import IntegronfinderAdapter
from arva_tools.isescan import IsescanAdapter
from arva_tools.mapping import BwaAdapter, Minimap2Adapter, SamtoolsAdapter
from arva_tools.mash import MashAdapter
from arva_tools.mlst import MlstAdapter
from arva_tools.mobsuite import MobsuiteAdapter
from arva_tools.multiqc import MultiqcAdapter
from arva_tools.nanoplot import NanoplotAdapter
from arva_tools.pilon import PilonAdapter
from arva_tools.prokka import ProkkaAdapter
from arva_tools.quast import QuastAdapter
from arva_tools.racon import RaconAdapter
from arva_tools.seqkit import SeqkitAdapter
from arva_tools.skani import SkaniAdapter
from arva_tools.spades import SpadesAdapter
from arva_tools.sylph import SylphAdapter
from arva_tools.unicycler import UnicyclerAdapter

ADAPTERS: dict[str, ToolAdapter] = {
    a.info.id: a
    for a in (SeqkitAdapter(), FastqcAdapter(), FastpAdapter(), FiltlongAdapter(), MultiqcAdapter(), NanoplotAdapter(),
              FlyeAdapter(), SpadesAdapter(), UnicyclerAdapter(), QuastAdapter(), RaconAdapter(), PilonAdapter(),
              Minimap2Adapter(), BwaAdapter(), SamtoolsAdapter(), DnadiffAdapter(), BaktaAdapter(), ProkkaAdapter(),
              MlstAdapter(), FastaniAdapter(), SkaniAdapter(), MashAdapter(), SylphAdapter(), GtdbtkAdapter(),
              AmrfinderplusAdapter(), AbricateAdapter(), MobsuiteAdapter(), IntegronfinderAdapter(), IsescanAdapter(),
              GenomadAdapter())
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
