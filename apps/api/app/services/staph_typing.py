"""Staphylococcus aureus typing: SCCmec (sccmec), spa (spaTyper with the Ridom SpaServer files the user registers)
and agr (AgrVATE in MUMmer mode), and the summary card that sets them beside the MLST call (mlst) and the
methicillin-resistance and toxin genes AMRFinderPlus found (--plus).

Each part keeps its source (tool, version, job). The conventional shorthand (e.g. "ST8-MRSA-IVa, t008, agr I, PVL+")
is built only from determined parts; a part whose evidence is partial or disputed carries "?" and is listed with the
reason. MRSA and MSSA here name the genotype (mecA or mecC found, or searched and not found), not a susceptibility
test. A part with no completed run is "not determined" and left out.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from arva_tools import ToolStatus
from arva_tools import agrvate as ag
from arva_tools import sccmec as sc
from arva_tools import spatyper as sp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AmrResult,
    AnalysisJob,
    Assembly,
    JobStatus,
    MlstResult,
    Project,
    Sample,
    TypingResult,
)
from app.services import typing_modules as tm
from app.services.metadata_table import sanitize_spreadsheet_cell
from app.services.mlst import assembly_facts
from app.services.performance import effective_resources

TYPING_JOB = "species_typing"
MODULE = tm.STAPHYLOCOCCUS_AUREUS
METHODS: dict[str, dict[str, Any]] = {
    "sccmec": {"tool": "sccmec", "params": sc.SccmecParams, "flags": sc.flags},
    "spa": {"tool": "spatyper", "params": sp.SpaParams, "flags": sp.flags},
    "agr": {"tool": "agrvate", "params": ag.AgrParams, "flags": ag.flags},
}
ADAPTERS = {"sccmec": sc.SccmecAdapter, "spa": sp.SpatyperAdapter, "agr": ag.AgrvateAdapter}
NAMES = {"sccmec": "sccmec", "spa": "spaTyper", "agr": "AgrVATE"}
# AMRFinderPlus element names (database 2026-08-07.1, fam.tsv family_name) that the summary groups.
ENTEROTOXIN_NAME = "staphylococcal enterotoxin"
EXFOLIATIVE_NAME = "exfoliative toxin"
PVL_SYMBOLS = ("lukS-PV", "lukF-PV")
CSV_COLUMNS = ("project", "sample_code", "assembly_id", "shorthand", "uncertain_parts", "mlst_st", "mlst_status",
               "clonal_complex", "sccmec_status", "sccmec_type", "sccmec_subtype", "sccmec_mecA", "ccr_complexes",
               "mec_classes", "spa_status", "spa_type", "spa_repeats", "agr_status", "agr_group", "agr_frameshifts",
               "agr_operon_extracted", "amr_mecA", "amr_mecC", "pvl", "tst", "enterotoxin_genes",
               "exfoliative_toxin_genes", "applicability", "sources")

# The English texts of ARVA's warnings; the interface has them as typing.warning.<code>.
WARNINGS = {
    "applicability_overridden": "Run on your explicit request although the species evidence does not support S. "
                                "aureus typing ({status}).",
    "tool_not_validated": "{tool} {version} has not been validated with ARVA on real data; read its results with care.",
    "synthetic_input": "SYNTHETIC input ({evidence}): this result describes the tools on test data, not biology.",
    "uppercased_input": "The contigs had lower-case bases; they were staged in upper case (spaTyper matches repeats "
                        "case-sensitively).",
    "sccmec_mecA_includes_mecC": "sccmec's mecA target includes the mecC sequence of type XI: its mecA + means mecA "
                                 "or mecC.",
    "sccmec_type_only": "sccmec determined the type but no cassette reached the coverage threshold for a subtype.",
    "sccmec_mec_without_type": "mecA (or mecC) was found but no SCCmec type: a novel, composite or incompletely "
                               "assembled cassette.",
    "sccmec_multiple": "Several SCCmec types matched: a composite cassette or a mixed sample; no type is reported.",
    "spa_new_repeat_succession": "New repeat succession: every repeat is known but no spa type in your Ridom files has "
                                 "this succession (newer files, or a new type to submit to the SpaServer).",
    "spa_unknown_repeat": "The repeat succession has a gap (xx): a repeat not in your Ridom files, or the spa region "
                          "broken across contigs; no spa type is reported.",
    "spa_multiple": "spa repeats were found on several contigs: the spa gene may be split across contigs or "
                    "present twice; no spa type is reported.",
    "spa_not_found": "No spa repeat was found: the spa gene may be missing from the assembly (or the isolate is not "
                     "S. aureus).",
    "spa_files_version": "spa types are as current as your Ridom files ({version}); newer types are not known.",
    "agr_mummer_mode": "AgrVATE ran in MUMmer mode (-m): its default usearch mode needs a 32-bit binary ARVA does "
                       "not install. Its help warns that this mode may not perform frameshift detection.",
    "agr_operon_partial": "Only {percent} % of AgrVATE's group-I reference operon aligned to this assembly; "
                          "variants were called on the extracted fragments only.",
    "agr_low_confidence": "AgrVATE's match score is {score} (4 or less is its 'low confidence' typing).",
    "agr_multiple": "k-mers of several agr groups were found (several S. aureus sequences?); no agr group is "
                    "reported.",
    "agr_untypeable": "No agr typing k-mer was found; the agr group is not determined.",
    "agr_non_canonical_agrD": "AgrVATE's nhmmer search found a possibly non-canonical agrD.",
    "agr_frameshifts_not_determined": "Frameshifts were not determined (no agr group, no operon extracted, or snippy "
                                      "failed).",
    "agr_exit_status": "AgrVATE ended with exit status {status} after writing its summary: {check}.",
    "agr_snippy_threads": "snippy, run by AgrVATE without --cpus, uses its default of up to 8 threads.",
}


def warning_text(w: dict[str, Any]) -> str:
    from app.core.messages import render

    return render(WARNINGS[w["code"]], w.get("params") or {}) if w["code"] in WARNINGS else w["code"]


class InputError(ValueError):
    """The assembly, method or options cannot be used as requested (HTTP 400)."""


# --- Bundled data and plan ----------------------------------------------------------------------------------

def bundled(method: str, executable: str | None) -> dict[str, Any] | None:
    """The data a tool's package carries (sccmec's schemas, AgrVATE's k-mers, HMM and reference operons), with
    their SHA-256, recorded on the job in place of a database record."""
    if not executable:
        return None
    if method == "sccmec":
        files = [p for p in sc.schema_files(executable) if p.is_file()]
        if len(files) != len(sc.SCHEMA_FILES):
            return None
        return {"kind": "sccmec_schemas", "name": "sccmec schemas (sccmec_targets, sccmec_regions)",
                "files": [f.name for f in files], "checksum": sc.schema_checksum(files), "path": str(files[0].parent)}
    if method == "agr":
        files = ag.database_files(executable)
        if not files:
            return None
        root = ag.databases_dir(executable)
        return {"kind": "agrvate_databases", "name": "AgrVATE databases (agrvate_databases)",
                "files": [str(f.relative_to(root)) for f in files], "checksum": ag.database_checksum(files, root),
                "path": str(root)}
    return None


def _help_defaults(method: str, exe: str) -> dict[str, str]:
    if method == "sccmec":
        return sc.help_defaults(sc.SccmecAdapter.help_text(exe))
    return {}


def plan(db: Session, sample: Sample, a: Assembly, method: str, database_id: str | None) -> dict[str, Any]:
    """What a run of this step on this assembly would do here: the tool and its version, the Ridom files (spa) or
    the data the tool bundles, the settings ARVA passes and the tool's own defaults, the species evidence, and what
    blocks the run. Only version and help checks run."""
    from app.services.mobile_elements import database_summary

    if method not in METHODS:
        raise InputError(f"Unknown step {method!r}")
    tool = tm.tool_facts(METHODS[method]["tool"])
    problems: list[dict[str, Any]] = []
    tool_defaults: dict[str, str] = {}
    if tool["status"] != ToolStatus.available.value or not tool["path"]:
        problems.append({"code": "tool_unavailable", "params": {"tool": tool["name"], "status": tool["status"]},
                         "message": f"{tool['name']} is not available ({tool['status']}): {tool['message']}"})
    else:
        try:
            tool_defaults = _help_defaults(method, tool["path"])
        except (OSError, RuntimeError) as exc:
            problems.append({"code": "help_unreadable", "params": {"tool": tool["name"], "detail": str(exc)},
                             "message": f"{tool['name']}'s help could not be read: {exc}"})
    database, databases = None, []
    if method == "spa":
        usable = tm.databases_of(db, "spa_types")
        databases = [database_summary(r) for r in usable]
        record = next((r for r in usable if r.id == database_id), None) if database_id else \
            (usable[0] if usable else None)
        if database_id and record is None:
            raise InputError("The chosen database is not a usable spa types database")
        if record is None:
            problems.append({"code": "no_ridom_files", "params": {},
                             "message": "No Ridom SpaServer files are registered: download sparepeats.fasta and "
                                        "spatypes.txt from the SpaServer and register their folder in the Database "
                                        "Manager (kind 'spa types')"})
        else:
            database = database_summary(record)
    data = bundled(method, tool["path"])
    if method in ("sccmec", "agr") and tool["path"] and data is None:
        problems.append({"code": "bundled_data_missing", "params": {"tool": tool["name"]},
                         "message": f"The data {tool['name']}'s package carries were not found next to it"})
    params = METHODS[method]["params"]()
    defaults = {k: str(v) for k, v in params.as_dict().items()}
    found = tm.evidence(db, a)
    res = effective_resources(db)
    return {"module": MODULE.key, "method": method, "tool": {**tool, "max_threads": res.max_threads,
                                                              "default_threads": res.threads},
            "database": database, "databases": databases, "bundled": data, "defaults": defaults,
            "tool_defaults": tool_defaults,
            "defaults_match": (tool_defaults == sc.DEFAULTS) if method == "sccmec" and tool_defaults else None,
            "assembly": assembly_facts(db, a), "applicability": tm.applicability(MODULE, found),
            "problems": problems}


# --- Results ------------------------------------------------------------------------------------------------

ROW_FIELDS = ("id", "job_id", "sample_id", "assembly_id", "module", "method", "tool", "tool_version", "database_kind",
              "database_name", "database_version", "database_checksum", "parameters", "status", "call", "details",
              "applicability", "warnings", "files", "created_at")


def row(r: TypingResult) -> dict[str, Any]:
    return {k: getattr(r, k) for k in ROW_FIELDS}


def results(db: Session, sample_id: str) -> list[TypingResult]:
    return list(db.scalars(select(TypingResult).where(TypingResult.sample_id == sample_id,
                                                      TypingResult.module == MODULE.key)
                           .order_by(TypingResult.created_at.desc())))


def _latest(db: Session, assembly_id: str) -> dict[str, TypingResult]:
    out: dict[str, TypingResult] = {}
    for r in db.scalars(select(TypingResult).where(TypingResult.assembly_id == assembly_id,
                                                   TypingResult.module == MODULE.key)
                        .order_by(TypingResult.created_at.desc())):
        out.setdefault(r.method, r)
    return out


def _source(tool: str, version: str | None, job_id: str | None, **extra: Any) -> dict[str, Any]:
    return {"tool": tool, "version": version, "job_id": job_id, **extra}


def _amr(db: Session, assembly_id: str) -> dict[str, Any] | None:
    from app.services.amr import latest_run

    job = latest_run(db, assembly_id)
    if job is None:
        return None
    hits = list(db.scalars(select(AmrResult).where(AmrResult.job_id == job.id)))
    plus = bool((job.parameters or {}).get("plus"))

    def genes(match) -> list[dict[str, Any]]:
        return [{"symbol": h.element_symbol, "name": h.element_name, "method": h.method, "method_kind": h.method_kind,
                 "identity": h.identity, "coverage": h.coverage, "contig": h.assembly_contig or h.contig}
                for h in hits if match(h)]

    def name_has(text: str):
        return lambda h: text in (h.element_name or "").lower()

    return {"source": _source(job.tool_name, job.tool_version, job.id, database_version=job.database_version,
                              plus=plus),
            "mecA": genes(lambda h: h.element_symbol.startswith("mecA")),
            "mecC": genes(lambda h: h.element_symbol.startswith("mecC")),
            "pvl": genes(lambda h: h.element_symbol in PVL_SYMBOLS) if plus else None,
            "tst": genes(lambda h: h.element_symbol == "tst") if plus else None,
            "enterotoxins": genes(name_has(ENTEROTOXIN_NAME)) if plus else None,
            "exfoliative_toxins": genes(name_has(EXFOLIATIVE_NAME)) if plus else None}


def _complete(genes: list[dict[str, Any]]) -> bool:
    return any(g["method_kind"] == "complete" for g in genes)


def summary(db: Session, a: Assembly) -> dict[str, Any]:
    """The summary card of one assembly: each part with its value, status and source, the mecA/mecC cross-check,
    and the shorthand built from the determined parts only."""
    latest = _latest(db, a.id)
    found = tm.evidence(db, a)
    m = db.scalars(select(MlstResult).where(MlstResult.assembly_id == a.id)
                   .order_by(MlstResult.created_at.desc())).first()
    mlst = None
    if m is not None:
        mlst = {"scheme": m.scheme, "st": m.st, "status": m.status,
                "clonal_complex": (m.clonal_complex or {}).get("value"),
                "source": _source(m.tool, m.tool_version, m.job_id, result_id=m.id)}
    calls = {k: {"status": r.status, "call": r.call, "details": r.details, "warnings": r.warnings,
                 "source": _source(r.tool, r.tool_version, r.job_id, result_id=r.id,
                                   database_version=r.database_version)} for k, r in latest.items()}
    amr = _amr(db, a.id)
    parts, uncertain = [], []

    if mlst and mlst["scheme"] == "saureus" and mlst["st"]:
        exact = mlst["status"] == "PERFECT"
        parts.append(f"ST{mlst['st']}" + ("" if exact else "?"))
        if not exact:
            uncertain.append({"part": "st", "reason": "mlst_status", "params": {"status": mlst["status"]}})

    sccmec = calls.get("sccmec")
    sccmec_mec = (sccmec or {}).get("details", {}).get("mecA") if sccmec else None
    amr_mec = None if amr is None else bool(amr["mecA"] or amr["mecC"])
    amr_mec_complete = None if amr is None else _complete(amr["mecA"] + amr["mecC"])
    cross = {"sccmec": sccmec_mec, "amrfinderplus": amr_mec,
             "status": "unavailable" if sccmec_mec is None or amr_mec is None
             else ("agree" if sccmec_mec == amr_mec else "disagree")}
    # MSSA needs AMRFinderPlus's search of the whole genome for mecA and mecC; sccmec's targets alone only show MRSA.
    mec = amr_mec if amr_mec is not None else (True if sccmec_mec else None)
    if mec is not None:
        label = "MRSA" if mec else "MSSA"
        doubt = cross["status"] == "disagree" or (mec and amr_mec_complete is False)
        sccmec_part = ""
        if mec and sccmec and sccmec["call"]:
            sccmec_part = f"-{sccmec['call']}"
            if sccmec["status"] == "type_only":
                uncertain.append({"part": "sccmec", "reason": "sccmec_type_only", "params": {}})
        if doubt:
            uncertain.append({"part": "mec", "reason": "mec_disagree" if cross["status"] == "disagree"
                              else "mec_partial", "params": {}})
        parts.append(label + sccmec_part + ("?" if doubt else ""))
    shorthand = ["-".join(parts)] if parts else []

    spa = calls.get("spa")
    if spa and spa["call"]:
        shorthand.append(spa["call"])
    agr = calls.get("agr")
    if agr and agr["call"]:
        low = agr["status"] == "low_confidence"
        shorthand.append(f"agr {agr['call']}" + ("?" if low else ""))
        if low:
            uncertain.append({"part": "agr", "reason": "agr_low_confidence",
                              "params": {"score": agr["details"].get("match_score")}})
    if amr is not None and amr["pvl"] is not None:
        symbols = {g["symbol"] for g in amr["pvl"]}
        if symbols >= set(PVL_SYMBOLS) and _complete([g for g in amr["pvl"] if g["symbol"] == "lukS-PV"]) \
                and _complete([g for g in amr["pvl"] if g["symbol"] == "lukF-PV"]):
            shorthand.append("PVL+")
        elif symbols:
            shorthand.append("PVL?")
            uncertain.append({"part": "pvl", "reason": "pvl_partial", "params": {"genes": ", ".join(sorted(symbols))}})
        else:
            shorthand.append("PVL-")

    return {"assembly_id": a.id, "module": MODULE.key, "applicability": tm.applicability(MODULE, found),
            "mlst": mlst, "sccmec": sccmec, "spa": spa, "agr": agr, "amr": amr, "mec_crosscheck": cross,
            "shorthand": ", ".join(shorthand) if shorthand else None, "uncertain": uncertain,
            "not_determined": [k for k in ("mlst", "sccmec", "spa", "agr", "amr")
                               if (mlst if k == "mlst" else amr if k == "amr" else calls.get(k)) is None]}


def _assemblies(db: Session, sample_id: str) -> list[Assembly]:
    return list(db.scalars(select(Assembly).where(Assembly.sample_id == sample_id)
                           .order_by(Assembly.created_at.desc())))


def sample_view(db: Session, sample_id: str) -> dict[str, Any]:
    """The typing modules (requirements here), and per assembly of the sample: the applicability of each module,
    the S. aureus summary card and the step results, newest first."""
    rows = results(db, sample_id)
    out = []
    for a in _assemblies(db, sample_id):
        found = tm.evidence(db, a)
        out.append({"assembly_id": a.id, "assembler": a.assembler, "assembler_version": a.assembler_version,
                    "kind": a.kind.value, "created_at": a.created_at,
                    "applicability": {k: tm.applicability(mod, found) for k, mod in tm.MODULES.items()},
                    "summary": summary(db, a) if any(r.assembly_id == a.id for r in rows) else None})
    return {"modules": [{**tm.describe(mod), "requirements": tm.requirements(db, mod)} for mod in tm.MODULES.values()],
            "assemblies": out, "results": [row(r) for r in rows]}


def project_overview(db: Session, project: Project) -> dict[str, Any]:
    """Per sample: the summary of its most recently typed assembly (None when no step ran)."""
    samples = list(db.scalars(select(Sample).where(Sample.project_id == project.id).order_by(Sample.sample_code)))
    rows = []
    for s in samples:
        typed = db.scalars(select(TypingResult).where(TypingResult.sample_id == s.id,
                                                      TypingResult.module == MODULE.key)
                           .order_by(TypingResult.created_at.desc())).first()
        a = db.get(Assembly, typed.assembly_id) if typed else None
        rows.append({"sample_id": s.id, "sample_code": s.sample_code, "summary": summary(db, a) if a else None})
    return {"project_id": project.id, "project_name": project.name, "is_demo": project.is_demo,
            "module": MODULE.key, "samples": rows, "typed": sum(1 for r in rows if r["summary"])}


def genes_text(items: list[dict[str, Any]] | None) -> str:
    if items is None:
        return "not searched"
    return " ".join(f"{g['symbol']}({g['method_kind']})" for g in items) or "none found"


def csv_row(project: Project, sample_code: str, s: dict[str, Any]) -> dict[str, Any]:
    def call(key: str, field: str = "call") -> Any:
        part = s.get(key)
        return "" if not part else (part.get(field) if part.get(field) is not None else "")

    sccmec = (s.get("sccmec") or {}).get("details") or {}
    spa = (s.get("spa") or {}).get("details") or {}
    agr = (s.get("agr") or {}).get("details") or {}
    amr = s.get("amr")
    mlst = s.get("mlst") or {}
    sources = [f"{k}: {p['source']['tool']} {p['source']['version']} (job {p['source']['job_id']})"
               for k in ("mlst", "sccmec", "spa", "agr", "amr") if (p := s.get(k))]
    alignment = agr.get("operon_alignment") or {}
    return {k: sanitize_spreadsheet_cell(str(v)) if isinstance(v, str) else v for k, v in {
        "project": project.name, "sample_code": sample_code, "assembly_id": s["assembly_id"],
        "shorthand": s["shorthand"] or "not determined",
        "uncertain_parts": "; ".join(f"{u['part']} ({u['reason']})" for u in s["uncertain"]),
        "mlst_st": mlst.get("st") or "", "mlst_status": mlst.get("status") or "",
        "clonal_complex": mlst.get("clonal_complex") or "",
        "sccmec_status": call("sccmec", "status"), "sccmec_type": sccmec.get("type") or "",
        "sccmec_subtype": sccmec.get("subtype") or "",
        "sccmec_mecA": "" if not sccmec else ("+" if sccmec.get("mecA") else "-"),
        "ccr_complexes": "; ".join(sccmec.get("ccr_complexes") or []),
        "mec_classes": "; ".join(sccmec.get("mec_classes") or []),
        "spa_status": call("spa", "status"), "spa_type": call("spa"), "spa_repeats": spa.get("repeats") or "",
        "agr_status": call("agr", "status"), "agr_group": call("agr"),
        "agr_frameshifts": "" if not agr else ("not determined" if agr.get("frameshifts") is None
                                               else agr["frameshifts"]),
        "agr_operon_extracted": "" if alignment.get("covered_fraction") is None
        else f"{alignment['covered_fraction'] * 100:.1f}%",
        "amr_mecA": "not searched" if amr is None else genes_text(amr["mecA"]),
        "amr_mecC": "not searched" if amr is None else genes_text(amr["mecC"]),
        "pvl": "not searched" if amr is None else genes_text(amr["pvl"]),
        "tst": "not searched" if amr is None else genes_text(amr["tst"]),
        "enterotoxin_genes": "not searched" if amr is None else genes_text(amr["enterotoxins"]),
        "exfoliative_toxin_genes": "not searched" if amr is None else genes_text(amr["exfoliative_toxins"]),
        "applicability": s["applicability"]["status"], "sources": "; ".join(sources)}.items()}


def project_csv(db: Session, project: Project) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for r in project_overview(db, project)["samples"]:
        if r["summary"]:
            writer.writerow(csv_row(project, r["sample_code"], r["summary"]))
    return out.getvalue()


def completed_jobs(db: Session, sample_id: str) -> list[AnalysisJob]:
    return list(db.scalars(select(AnalysisJob).where(AnalysisJob.sample_id == sample_id,
                                                     AnalysisJob.job_type == TYPING_JOB,
                                                     AnalysisJob.status == JobStatus.completed)))


def download_name(sample: Sample, job: AnalysisJob, name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in f"{sample.sample_code}_{Path(name).name}")
    method = (job.parameters or {}).get("method") or "typing"
    return f"ARVA_{method}_{job.id[:8]}_{safe}"
