"""MOB-suite databases: what a download of the pinned Zenodo archive also needs (a dated NCBI taxonomy archive for
taxa.sqlite, and whether to keep the reference plasmids' FASTA), checked against NCBI's listing.

mob_init would fetch the latest NCBI taxonomy through ete3 (over plain HTTP) every time it runs; ARVA lists NCBI's
dated monthly archives (pub/taxonomy/taxdump_archive/taxdmp_YYYY-MM-DD.zip, checked 2026-10-29), proposes the newest,
reads its size from the server (NCBI publishes no checksum for these archives) and records the SHA-256 of what it
downloaded. The task that prepares the folder is app.tasks.mobsuite_db.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from arva_tools import mobsuite as mob

from app.core.config import get_settings
from app.services import amrfinder_db
from app.services import databases as dbs

KIND = "mobsuite"
TAXONOMY_NAME = re.compile(r"taxdmp_(\d{4}-\d{2}-\d{2})\.zip")
# The reference plasmids' FASTA in database 3.1.8 (listing of the archive, 2026-10-29).
PLASMID_FASTA_BYTES = 1_641_486_485
# What building taxa.sqlite needs besides the folder itself: the gzipped tar ARVA repacks and the tables ete3 3.1.3
# writes before loading them (taxa.tab alone was 534,192,901 bytes for taxdmp_2026-10-01.zip, measured 2026-10-29).
TAXONOMY_WORK_BYTES = 700_000_000


def base_url() -> str:
    url = get_settings().ncbi_taxonomy_url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise dbs.refusal("mobsuite_taxonomy_unreachable", detail=f"{url} is not an https address")
    return url


def taxonomy_archives() -> list[dict[str, Any]]:
    """NCBI's dated taxonomy archives (the old-format taxdmp_*.zip ete3 reads), newest first."""
    url = f"{base_url()}/"
    try:
        listing = amrfinder_db.parse_listing(amrfinder_db._read(url))
    except amrfinder_db.AmrDatabaseError as exc:
        raise dbs.refusal("mobsuite_taxonomy_unreachable", detail=str(exc)) from exc
    rows = [r for r in listing if not r["folder"] and TAXONOMY_NAME.fullmatch(r["name"])]
    rows.sort(key=lambda r: r["name"], reverse=True)
    return [{"name": r["name"], "date": TAXONOMY_NAME.fullmatch(r["name"]).group(1), "url": f"{url}{r['name']}",
             "approx_bytes": r["approx_bytes"], "modified": r["modified"]} for r in rows]


def archive_size(url: str) -> int:
    """The archive's size from the server's Content-Length (a HEAD request)."""
    import urllib.request

    from app.tasks.databases import USER_AGENT, _SameOriginRedirect

    opener = urllib.request.build_opener(_SameOriginRedirect)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with opener.open(req, timeout=60) as resp:
            length = resp.headers.get("Content-Length")
    except OSError as exc:
        raise dbs.refusal("mobsuite_taxonomy_unreachable", detail=str(getattr(exc, "reason", exc))) from exc
    if not (length or "").isdigit():
        raise dbs.refusal("mobsuite_taxonomy_unreachable", detail=f"{url} did not state its size")
    return int(length)


def choose_taxonomy(name: str | None, archives: list[dict[str, Any]]) -> dict[str, Any]:
    """The chosen dated archive (the newest when none is given), with its exact size."""
    if not archives:
        raise dbs.refusal("mobsuite_taxonomy_unreachable", detail="no taxdmp_*.zip in taxdump_archive/")
    chosen = next((a for a in archives if a["name"] == name), None) if name else archives[0]
    if chosen is None:
        raise dbs.refusal("mobsuite_taxonomy_unknown", name=str(name)[:60])
    return {**chosen, "bytes": archive_size(chosen["url"])}


def plan_extras(keep_fasta: bool, taxonomy: str | None) -> dict[str, Any]:
    archives = taxonomy_archives()
    chosen = choose_taxonomy(taxonomy, archives)
    return {"taxonomy": chosen, "taxonomy_archives": [{k: a[k] for k in ("name", "date")} for a in archives[:12]],
            "keep_plasmid_fasta": keep_fasta, "plasmid_fasta_bytes": PLASMID_FASTA_BYTES,
            "extra_bytes": chosen["bytes"] + TAXONOMY_WORK_BYTES + (PLASMID_FASTA_BYTES if keep_fasta else 0),
            "steps": ["makeblastdb -in - -parse_seqids -dbtype nucl (reference plasmids, from the archive)",
                      f"mash sketch -i -k {mob.MASH_K} -s {mob.MASH_S} (reference plasmids, from the archive)",
                      "makeblastdb -in repetitive.dna.fas -dbtype nucl",
                      "ete3 NCBITaxa(dbfile=taxa.sqlite, taxdump_file=<the NCBI archive>)"]}
