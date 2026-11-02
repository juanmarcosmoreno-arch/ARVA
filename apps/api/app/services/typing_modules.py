"""Species-specific typing modules: which ones apply to an assembly, and what each needs.

A module declares the taxa it applies to (species names as species identification reports them, and MLST scheme
names as mlst reports them), its steps (each a tool, and the database kind it reads or None for files bundled with the
tool) and the guide entries that explain its results. ARVA offers a module for an assembly only when the evidence
supports it:

* applicable: the most recent species identification that named a species, or the most recent MLST call with a
  scheme, matches the module, and neither names another taxon;
* conflicting: one matches and the other names another taxon;
* not_applicable: the evidence names another taxon only;
* no_evidence: no species identification named a species and mlst found no scheme.

Only `applicable` runs without more; the others need the user's explicit override, which the job records with the
evidence it overrode.

To add a module (for example Klebsiella pneumoniae with Kleborate, E. coli serotyping with ECTyper, Salmonella with
SISTR): write its adapters (arva_tools), a TypingModule here with its taxa, steps and guide keys, the step runners in
app/tasks/typing.py and its summary in a service of its own (as staph_typing.py does); its rows go to typing_results
under its module key, and the interface lists it with its applicability and requirements from this registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arva_tools import ToolStatus
from arva_tools.registry import detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assembly, MlstResult, ReferenceDatabase, SpeciesResult
from app.services import databases as dbs


@dataclass(frozen=True)
class Step:
    key: str
    name: str
    tool: str
    # The database kind the user registers (Database Manager), or None when the tool's own package carries its data.
    database_kind: str | None
    guide: str
    produces: tuple[str, ...]


@dataclass(frozen=True)
class TypingModule:
    key: str
    name: str
    species: tuple[str, ...]
    mlst_schemes: tuple[str, ...]
    steps: tuple[Step, ...]
    guide: tuple[str, ...]
    notes: tuple[str, ...] = field(default=())

    def step(self, key: str) -> Step:
        for s in self.steps:
            if s.key == key:
                return s
        raise KeyError(key)


STAPHYLOCOCCUS_AUREUS = TypingModule(
    key="staphylococcus_aureus",
    name="Staphylococcus aureus typing",
    species=("Staphylococcus aureus",),
    mlst_schemes=("saureus",),
    steps=(
        Step("sccmec", "SCCmec typing", "sccmec", None, "sccmec",
             ("type", "subtype", "mecA", "ccr_complexes", "mec_classes", "targets", "regions")),
        Step("spa", "spa typing", "spatyper", "spa_types", "spa_typing", ("repeats", "spa_type")),
        Step("agr", "agr typing", "agrvate", None, "agr",
             ("agr_group", "match_score", "canonical_agrD", "frameshifts", "operon_alignment")),
    ),
    guide=("sccmec", "spa_typing", "agr", "staph_typing_summary"),
)

MODULES: dict[str, TypingModule] = {m.key: m for m in (STAPHYLOCOCCUS_AUREUS,)}


def evidence(db: Session, a: Assembly) -> dict[str, Any]:
    """The most recent species identification of the assembly that named a species, and its most recent MLST call
    that found a scheme (None when there is none)."""
    s = db.scalars(select(SpeciesResult).where(SpeciesResult.assembly_id == a.id, SpeciesResult.species.isnot(None))
                   .order_by(SpeciesResult.created_at.desc())).first()
    m = db.scalars(select(MlstResult).where(MlstResult.assembly_id == a.id, MlstResult.scheme.isnot(None))
                   .order_by(MlstResult.created_at.desc())).first()
    return {
        "species": {"value": s.species, "method": s.method, "tool": s.tool, "tool_version": s.tool_version,
                    "status": s.status, "result_id": s.id, "created_at": s.created_at.isoformat()} if s else None,
        "mlst": {"value": m.scheme, "st": m.st, "tool": m.tool, "tool_version": m.tool_version, "status": m.status,
                 "result_id": m.id, "created_at": m.created_at.isoformat()} if m else None,
    }


def applicability(module: TypingModule, found: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for source, accepted in (("species", module.species), ("mlst", module.mlst_schemes)):
        item = found.get(source)
        if item is not None:
            checks.append({"source": source, "value": item["value"], "matches": item["value"] in accepted})
    matches = [c for c in checks if c["matches"]]
    others = [c for c in checks if not c["matches"]]
    if matches and not others:
        status = "applicable"
    elif matches:
        status = "conflicting"
    elif others:
        status = "not_applicable"
    else:
        status = "no_evidence"
    return {"module": module.key, "status": status, "checks": checks, "evidence": found,
            "accepted": {"species": list(module.species), "mlst_schemes": list(module.mlst_schemes)},
            "override_required": status != "applicable"}


def tool_facts(tool_id: str) -> dict[str, Any]:
    d = detect(tool_id, refresh=True)
    return {"id": tool_id, "name": d.info.name, "status": d.status.value, "version": d.version,
            "version_validated": d.version_validated, "reason": d.reason, "reason_params": d.reason_params,
            "message": d.message, "path": d.path, "license": d.info.license, "citation": d.info.citation,
            "citation_url": d.info.citation_url, "install": d.info.install,
            "platforms": list(d.info.conda_platforms)}


def databases_of(db: Session, kind: str) -> list[ReferenceDatabase]:
    rows = db.scalars(select(ReferenceDatabase).where(ReferenceDatabase.kind == kind,
                                                      ReferenceDatabase.status.in_(dbs.USABLE))
                      .order_by(ReferenceDatabase.is_default.desc(), ReferenceDatabase.created_at.desc()))
    return [r for r in rows if dbs.usable_now(r)]


def requirements(db: Session, module: TypingModule) -> list[dict[str, Any]]:
    """Per step: the tool (detected here, with how to install it) and the database it needs (None when the tool's
    package carries its data), and what is missing."""
    from app.services import database_kinds as kinds

    out = []
    for s in module.steps:
        tool = tool_facts(s.tool)
        missing = [] if tool["status"] == ToolStatus.available.value else ["tool"]
        database = None
        if s.database_kind:
            k = kinds.BY_KEY[s.database_kind]
            usable = databases_of(db, s.database_kind)
            database = {"kind": s.database_kind, "name": k.name, "registered": [
                {"id": r.id, "name": r.name, "version": r.version, "is_default": r.is_default} for r in usable],
                "source_url": k.source_url, "licence": k.licence, "licence_url": k.licence_url,
                "download_note": k.download_note, "user_provided_only": k.user_provided_only}
            if not usable:
                missing.append("database")
        out.append({"key": s.key, "name": s.name, "tool": tool, "database": database, "missing": missing,
                    "ready": not missing, "guide": s.guide, "produces": list(s.produces)})
    return out


def describe(module: TypingModule) -> dict[str, Any]:
    return {"key": module.key, "name": module.name, "species": list(module.species),
            "mlst_schemes": list(module.mlst_schemes), "guide": list(module.guide)}
