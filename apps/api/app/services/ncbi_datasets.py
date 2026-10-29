"""Reference genome collections built from NCBI Datasets for a chosen taxon (any genus or species of Bacteria).

Endpoints and parameters confirmed in the NCBI Datasets v2 OpenAPI document (openapi3.docs.yaml, fetched 2026-10-29)
and with requests to the API on that day:

* GET /taxonomy/taxon/{taxons}: taxonomy_nodes[].taxonomy with tax_id, organism_name, rank and lineage (tax ids);
  an unknown name gives a node with errors[].reason. A name can match several taxa ("Bacillus" is a bacterial genus,
  tax id 1386, and a stick-insect genus, 55087), so ARVA keeps the nodes whose lineage holds 2 (Bacteria) and asks
  the user to choose when more than one remain.
* GET /genome/taxon/{taxons}/dataset_report with filters.assembly_source (all, refseq, genbank),
  filters.is_type_material, filters.reference_only, filters.exclude_atypical, tax_exact_match, page_size (default 20,
  maximum 1000) and page_token; the page holds reports[] (snake_case fields: accession, organism.organism_name,
  organism.infraspecific_names.strain, type_material.type_label / type_display_text, assembly_info.refseq_category
  and assembly_level, assembly_stats.total_sequence_length and number_of_contigs), total_count and next_page_token.
* POST /genome/download_summary with {"accessions": [...], "include_annotation_type": ["GENOME_FASTA"]}: record_count,
  hydrated.estimated_file_size_mb (NCBI's estimate of the zip) and available_files.all_genomic_fasta (file_count,
  size_mb), resource_updated_on.
* POST /genome/download with the same body: the genome data package (zip) with md5sum.txt, README.md and
  ncbi_dataset/data/ (assembly_data_report.jsonl, dataset_catalog.json, one folder per accession). The response has
  no Content-Length (chunked), so ARVA caps what it accepts.
* Rate limit: the API answers with X-RateLimit-Limit: 5 without an API key; ARVA sends at most a few requests per
  plan, one after the other, and sends no API key, e-mail or other personal data — only the taxon, the filters and
  the accession list.

ARVA shows the number of genomes and NCBI's size estimate before anything is downloaded, and downloads only after
the user confirms that exact list (its fingerprint).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.core.messages import render
from app.models import DatabaseOrigin, DatabaseStatus, ReferenceDatabase
from app.services import database_kinds as kinds
from app.services import databases as dbs
from app.services import reference_collections as rc

USER_AGENT = f"ARVA/{__version__} (reference collection builder)"
TIMEOUT_SECONDS = 60
PAGE_SIZE = 1000
MAX_GENOMES = 2000
PREVIEW = 25
BACTERIA = 2
# One request after the other, at most this often (the API allows 5 per second without a key).
MIN_INTERVAL_SECONDS = 0.25
_TAXON = re.compile(r"[A-Za-z][A-Za-z0-9 .'()_-]{1,99}|\d{1,10}")
_SOURCES = ("refseq", "genbank", "all")

MESSAGES = {
    "ncbi_taxon_invalid": "Give a taxon name (letters, digits, spaces and . ' ( ) _ -) or an NCBI Taxonomy id.",
    "ncbi_taxon_unknown": "NCBI Taxonomy does not know {taxon}.",
    "ncbi_taxon_not_bacterial": "{taxon} is not a taxon of Bacteria in NCBI Taxonomy.",
    "ncbi_taxon_choose": "{taxon} matches several bacterial taxa; choose one.",
    "ncbi_no_genomes": "NCBI Datasets has no genome of {taxon} with these filters.",
    "ncbi_too_many": "{count} genomes match; ARVA builds collections of at most {limit}. Narrow the filters (type "
                     "material, reference genomes) or choose a smaller taxon.",
    "ncbi_unreachable": "NCBI Datasets could not be reached: {detail}",
    "ncbi_http_error": "NCBI Datasets answered HTTP {status} for {what}.",
    "ncbi_bad_answer": "NCBI Datasets sent an answer ARVA cannot read ({what}).",
    "ncbi_list_changed": "The genome list NCBI Datasets returns now is not the one you confirmed; review the plan again.",
    "ncbi_confirm": "Confirm the number of genomes and the download size first.",
}


class NcbiError(dbs.DatabaseError):
    """NCBI Datasets refused, failed or was unreachable (400 for the request, 502 for NCBI)."""

    def __init__(self, code: str, upstream: bool = False, **params):
        super().__init__(render(MESSAGES[code], params), code, **params)
        self.upstream = upstream


@dataclass(frozen=True)
class Filters:
    source: str = "refseq"
    type_material: bool = False
    reference_only: bool = False
    exclude_atypical: bool = True
    exact_taxon: bool = False

    def query(self) -> dict[str, str]:
        out = {"filters.assembly_source": self.source, "filters.exclude_atypical": str(self.exclude_atypical).lower()}
        if self.type_material:
            out["filters.is_type_material"] = "true"
        if self.reference_only:
            out["filters.reference_only"] = "true"
        if self.exact_taxon:
            out["tax_exact_match"] = "true"
        return out


_last_request = [0.0]


def _base() -> str:
    url = get_settings().ncbi_datasets_url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise NcbiError("ncbi_unreachable", True, detail=f"{url} is not an https address")
    return url


def _request(method: str, path: str, params: dict[str, str] | None = None,
             body: dict | None = None) -> urllib.request.Request:
    url = _base() + path + (f"?{urlencode(params)}" if params else "")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, method=method, headers=headers)


def open_request(req: urllib.request.Request, what: str):
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        raise NcbiError("ncbi_http_error", True, status=exc.code, what=what) from exc
    except OSError as exc:
        raise NcbiError("ncbi_unreachable", True, detail=str(getattr(exc, "reason", exc))) from exc


def _json(req: urllib.request.Request, what: str, limit: int = 64 << 20) -> dict:
    with open_request(req, what) as resp:
        raw = resp.read(limit + 1)
    if len(raw) > limit:
        raise NcbiError("ncbi_bad_answer", True, what=f"{what}: larger than {limit:,} bytes")
    try:
        value = json.loads(raw)
    except ValueError:
        raise NcbiError("ncbi_bad_answer", True, what=what) from None
    if not isinstance(value, dict):
        raise NcbiError("ncbi_bad_answer", True, what=what)
    return value


def resolve_taxon(text: str) -> list[dict[str, Any]]:
    """The NCBI Taxonomy nodes a name or tax id matches, each with whether it is a taxon of Bacteria."""
    text = " ".join(text.split())
    if not _TAXON.fullmatch(text):
        raise NcbiError("ncbi_taxon_invalid")
    data = _json(_request("GET", f"/taxonomy/taxon/{quote(text, safe='')}"), "taxonomy")
    nodes = []
    for node in data.get("taxonomy_nodes") or []:
        t = node.get("taxonomy") if isinstance(node, dict) else None
        if not isinstance(t, dict) or not isinstance(t.get("tax_id"), int):
            continue
        lineage = [x for x in t.get("lineage") or [] if isinstance(x, int)]
        nodes.append({"tax_id": t["tax_id"], "name": str(t.get("organism_name") or "")[:200],
                      "rank": str(t.get("rank") or "").lower() or None,
                      "bacterial": BACTERIA in lineage or t["tax_id"] == BACTERIA})
    return nodes


def _genome(r: dict) -> dict[str, Any] | None:
    acc = r.get("accession")
    if not isinstance(acc, str) or not rc.ACCESSION.fullmatch(acc):
        return None
    org = r.get("organism") if isinstance(r.get("organism"), dict) else {}
    infra = org.get("infraspecific_names") if isinstance(org.get("infraspecific_names"), dict) else {}
    tm = r.get("type_material") if isinstance(r.get("type_material"), dict) else {}
    info = r.get("assembly_info") if isinstance(r.get("assembly_info"), dict) else {}
    stats = r.get("assembly_stats") if isinstance(r.get("assembly_stats"), dict) else {}

    def number(v) -> int | None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    name = str(org.get("organism_name") or "")[:300] or None
    return {"accession": acc, "organism": name, "species": rc.species_of(name),
            "strain": str(infra["strain"])[:200] if infra.get("strain") else None,
            "type_label": tm.get("type_label"), "type_text": tm.get("type_display_text"),
            "refseq_category": info.get("refseq_category"), "assembly_level": info.get("assembly_level"),
            "length": number(stats.get("total_sequence_length")), "contigs": number(stats.get("number_of_contigs"))}


def genomes_for(tax_id: int, filters: Filters) -> tuple[list[dict[str, Any]], int]:
    """The genomes NCBI Datasets lists for the taxon with these filters (at most MAX_GENOMES) and its total count."""
    out: list[dict[str, Any]] = []
    token, total = None, 0
    while True:
        params = {**filters.query(), "page_size": str(PAGE_SIZE)}
        if token:
            params["page_token"] = token
        page = _json(_request("GET", f"/genome/taxon/{tax_id}/dataset_report", params), "genome report")
        total = page.get("total_count") if isinstance(page.get("total_count"), int) else len(page.get("reports") or [])
        if total > MAX_GENOMES:
            return out, total
        out += [g for r in page.get("reports") or [] if isinstance(r, dict) and (g := _genome(r))]
        token = page.get("next_page_token")
        if not token or len(out) >= total:
            return out, total


def download_summary(accessions: list[str]) -> dict[str, Any]:
    data = _json(_request("POST", "/genome/download_summary",
                          body={"accessions": accessions, "include_annotation_type": ["GENOME_FASTA"]}),
                 "download summary")
    hydrated = data.get("hydrated") if isinstance(data.get("hydrated"), dict) else {}
    files = (data.get("available_files") or {}).get("all_genomic_fasta") or {}
    return {"record_count": data.get("record_count"), "estimated_mb": hydrated.get("estimated_file_size_mb"),
            "fasta_files": files.get("file_count"), "fasta_mb": files.get("size_mb"),
            "resource_updated_on": data.get("resource_updated_on")}


def fingerprint(accessions: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(accessions)).encode()).hexdigest()


def fasta_estimate(genomes: list[dict[str, Any]]) -> int:
    """ARVA's estimate of the uncompressed FASTA size: the bases, one newline per 80 bases (NCBI's line length in the
    packages ARVA checked) and about 120 bytes of header per sequence."""
    total = 0
    for g in genomes:
        n = g.get("length") or 0
        total += n + math.ceil(n / 80) + 120 * (g.get("contigs") or 1)
    return total


def _zip_estimate(summary: dict[str, Any], genomes: list[dict[str, Any]]) -> int:
    mb = summary.get("estimated_mb")
    return int(mb * 1_000_000) if isinstance(mb, int | float) and mb > 0 else fasta_estimate(genomes)


def _folder_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.").lower() or "taxon"


def plan(db: Session, taxon: str, tax_id: int | None, filters: Filters, destination: str | None = None,
         folder: str | None = None) -> dict[str, Any]:
    """What building a collection would download: the taxon, the genomes NCBI Datasets lists (count, species, type
    material), NCBI's size estimate, ARVA's estimate of the unpacked size, and the destination's free space. Nothing
    is downloaded except this metadata."""
    return _plan(taxon, tax_id, filters, destination, folder)[0]


def _plan(taxon: str, tax_id: int | None, filters: Filters, destination: str | None,
          folder: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if filters.source not in _SOURCES:
        raise NcbiError("ncbi_taxon_invalid")
    nodes = resolve_taxon(str(tax_id) if tax_id else taxon)
    if not nodes:
        raise NcbiError("ncbi_taxon_unknown", taxon=taxon)
    bacterial = [n for n in nodes if n["bacterial"]]
    if not bacterial:
        raise NcbiError("ncbi_taxon_not_bacterial", taxon=taxon)
    base = {"query": taxon, "filters": asdict(filters), "candidates": bacterial if len(bacterial) > 1 else []}
    if len(bacterial) > 1:
        return {**base, "taxon": None, "status": "choose_taxon"}, []
    node = bacterial[0]
    genomes, total = genomes_for(node["tax_id"], filters)
    out = {**base, "taxon": node, "total_count": total, "limit": MAX_GENOMES, "status": "ready",
           "query_url": _base() + f"/genome/taxon/{node['tax_id']}/dataset_report?"
           + urlencode({**filters.query(), "page_size": str(PAGE_SIZE)})}
    if total > MAX_GENOMES:
        return {**out, "status": "too_many", "genomes": 0}, []
    if not genomes:
        return {**out, "status": "no_genomes", "genomes": 0}, []
    accessions = [g["accession"] for g in genomes]
    summary = download_summary(accessions)
    by_species = Counter(g["species"] or "unclassified" for g in genomes)
    root = dbs._destination(destination)
    folder_text = dbs._folder(folder, f"reference-genomes/ncbi-{_folder_name(node['name'])}-"
                                      f"{time.strftime('%Y-%m-%d', time.gmtime())}")
    target = root / folder_text
    fasta = fasta_estimate(genomes)
    zip_bytes = _zip_estimate(summary, genomes)
    required = zip_bytes + fasta
    free = dbs.free_bytes(root)
    available = max(0, free - get_settings().min_free_bytes)
    return {
        **out, "genomes": len(genomes), "fingerprint": fingerprint(accessions),
        "species": len([s for s in by_species if s != "unclassified"]), "unclassified": by_species.get("unclassified", 0),
        "by_species": [{"species": s, "genomes": n} for s, n in by_species.most_common(30)],
        "type_material": sum(1 for g in genomes if g["type_label"]),
        "reference_genomes": sum(1 for g in genomes if g["refseq_category"] == "reference genome"),
        "preview": genomes[:PREVIEW], "download": summary, "zip_estimate_bytes": zip_bytes,
        "fasta_estimate_bytes": fasta, "required_bytes": required, "db_dir": str(root), "folder": folder_text,
        "target_path": str(target), "host_target_path": dbs._shown(target), "free_bytes": free,
        "available_bytes": available, "enough": required <= available, "target_exists": target.exists(),
    }, genomes


def start(db: Session, taxon: str, tax_id: int, filters: Filters, confirm_genomes: int, confirm_fingerprint: str,
          destination: str | None = None, folder: str | None = None) -> ReferenceDatabase:
    """Plan again (NCBI's list may have changed), check the confirmation, and queue the download."""
    from app.tasks.ncbi_collection import run_ncbi_collection

    p, genomes = _plan(taxon, tax_id, filters, destination, folder)
    if p["status"] != "ready":
        raise NcbiError({"too_many": "ncbi_too_many", "no_genomes": "ncbi_no_genomes"}.get(
            p["status"], "ncbi_taxon_choose"), taxon=taxon, count=p.get("total_count", 0), limit=MAX_GENOMES)
    if confirm_genomes != p["genomes"] or confirm_fingerprint != p["fingerprint"]:
        raise NcbiError("ncbi_list_changed")
    if p["target_exists"]:
        raise dbs.DatabaseStateError("", "target_exists", path=p["host_target_path"])
    if not p["enough"]:
        raise dbs.DatabaseSpaceError(p["required_bytes"], p["available_bytes"], Path(p["db_dir"]))
    k = kinds.BY_KEY["reference_genomes"]
    node = p["taxon"]
    label = ", ".join(x for x in (p["filters"]["source"], "type material" if filters.type_material else "",
                                  "reference genomes" if filters.reference_only else "") if x)
    accessions = [g["accession"] for g in genomes]
    record = ReferenceDatabase(
        key="reference_genomes", kind="reference_genomes", name=f"{node['name']} genomes from NCBI Datasets ({label})",
        path=p["target_path"], origin=DatabaseOrigin.download, status=DatabaseStatus.downloading, log_text="",
        source_url=k.source_url, licence=k.licence, task_id=dbs._task_id(),
        details={"destination": p["db_dir"], "ncbi": {
            "api": _base(), "taxon": node, "query": taxon, "filters": p["filters"], "query_url": p["query_url"],
            "accessions": accessions, "fingerprint": p["fingerprint"], "summary": p["download"],
            "zip_estimate_bytes": p["zip_estimate_bytes"], "fasta_estimate_bytes": p["fasta_estimate_bytes"]},
            "confirmation": {"genomes": confirm_genomes, "fingerprint": confirm_fingerprint,
                             "at": dbs.now().isoformat()}},
        progress={"phase": "queued", "bytes_done": 0, "bytes_total": p["zip_estimate_bytes"]},
    )
    db.add(record)
    db.commit()
    dbs._enqueue(record, run_ncbi_collection)
    db.refresh(record)
    return record
