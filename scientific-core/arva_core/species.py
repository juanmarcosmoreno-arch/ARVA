"""Species identification by average nucleotide identity (ANI): ARVA's reading of the ranked hits of a genome against
a reference collection, and its consistency checks with the MLST scheme and the organism given for an annotation.

The thresholds, and where each comes from:

* ANI_BOUNDARY, 95 %: Jain C. et al. (2018) High throughput ANI analysis of 90K prokaryotic genomes reveals clear
  species boundaries. Nat Commun 9:5114, doi:10.1038/s41467-018-07641-9 — 99.8 % of the 8 billion genome pairs they
  analysed conform to >95 % intra-species and <83 % inter-species ANI. It is an empirical boundary: a few species are
  wider or narrower, and names in public collections are not always consistent with it.
* MIN_AF, 0.5: the minimum alignment fraction GTDB-Tk 2.8.0 requires to assign a genome to a species cluster
  (`gtdbtk classify_wf --min_af`, default 0.5). Applying it to FastANI's and skani's aligned fractions, and to sylph's
  containment, is ARVA's choice: ANI computed over a small shared part of two genomes says little about the rest.
* MARGIN, 0.5 percentage points: ARVA's heuristic for "close" values — a best hit this near the boundary, or a second
  species this near the best one, makes the result ambiguous. It is not a value from the literature.

A result is never more certain than its evidence: "same species" needs one species clearly above the boundary with
enough aligned fraction; anything else is "ambiguous" or "no reference within the species boundary", and the result
can only be as good as the collection searched.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

ANI_BOUNDARY = 95.0
MIN_AF = 0.5
MARGIN = 0.5
THRESHOLDS = {"ani_boundary": ANI_BOUNDARY, "min_af": MIN_AF, "margin": MARGIN}
SOURCES = {
    "ani_boundary": "Jain C. et al. (2018) Nat Commun 9:5114, doi:10.1038/s41467-018-07641-9",
    "min_af": "GTDB-Tk 2.8.0 classify_wf --min_af default (minimum alignment fraction to assign a species cluster); "
              "used by ARVA for every method",
    "margin": "ARVA's heuristic",
}

# Methods whose value is an ANI estimate the species boundary applies to; Mash's distance is not one.
ANI_METHODS = ("fastani", "skani", "sylph")


def species_of(organism: str | None) -> str | None:
    """Genus and species epithet of an organism name ("Staphylococcus aureus subsp. aureus NCTC 8325" →
    "Staphylococcus aureus"); None for "Genus sp." and names that are not binomials."""
    words = (organism or "").split()
    if len(words) < 2 or not words[1][:1].islower() or words[1] in ("sp.", "spp.", "bacterium", "cf.", "aff."):
        return None
    return f"{words[0]} {words[1]}"


def genus_of(species: str | None) -> str | None:
    return species.split()[0] if species else None


def _summary(h: dict[str, Any] | None) -> dict[str, Any] | None:
    if h is None:
        return None
    keys = ("reference", "accession", "organism", "species", "strain", "type_material", "ani", "af", "distance")
    return {k: h.get(k) for k in keys}


def collection_scope(species: Iterable[str | None]) -> dict[str, Any]:
    """The genera and species a collection holds (by its genomes' species names)."""
    names = sorted({s for s in species if s})
    genera = sorted({genus_of(s) for s in names if genus_of(s)})
    return {"species": len(names), "genera": genera}


def _caveats(method: str, best: dict[str, Any] | None, scope: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"code": "collection_bound", "params": {}}]
    if scope and len(scope.get("genera") or []) == 1:
        out.append({"code": "single_genus", "params": {"genus": scope["genera"][0]}})
    if method == "fastani":
        out.append({"code": "fastani_range", "params": {}})
    if method == "sylph":
        out.append({"code": "sylph_assembly", "params": {}})
    if best is not None and best.get("type_material") is False:
        out.append({"code": "not_type_material", "params": {"reference": best.get("accession") or best.get("reference")}})
    return out


def interpret(hits: list[dict[str, Any]], method: str, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """ARVA's reading of ranked hits (each with `species`, `ani` in %, `af` as a fraction or None, and the reference's
    `accession`, `organism`, `type_material`). Mash hits (`distance`) are only ranked: Mash's distance estimates a
    k-mer mutation rate, and ARVA applies no ANI boundary to it.

    status: same_species, ambiguous, below_boundary, no_hits, or screening_only (Mash); `reasons` say why a result
    is ambiguous, `caveats` what always limits it."""
    base = {"method": method, "thresholds": THRESHOLDS, "sources": SOURCES, "species": None, "best": None,
            "runner_up": None, "reasons": []}
    if method not in ANI_METHODS:
        shared = sorted((h for h in hits if h.get("shared") and h.get("distance") is not None),
                        key=lambda h: h["distance"])
        best = shared[0] if shared else None
        return {**base, "status": "screening_only" if best else "no_hits", "best": _summary(best),
                "caveats": [{"code": "mash_not_ani", "params": {}}, *_caveats(method, best, scope)]}
    ranked = sorted((h for h in hits if h.get("ani") is not None), key=lambda h: -h["ani"])
    if not ranked:
        return {**base, "status": "no_hits", "caveats": _caveats(method, None, scope)}
    best = ranked[0]
    other = next((h for h in ranked[1:] if h.get("species") and h["species"] != best.get("species")), None)
    out = {**base, "best": _summary(best), "runner_up": _summary(other), "caveats": _caveats(method, best, scope)}
    ani = best["ani"]
    if ani < ANI_BOUNDARY - MARGIN:
        return {**out, "status": "below_boundary"}
    reasons: list[dict[str, Any]] = []
    if ani < ANI_BOUNDARY + MARGIN:
        reasons.append({"code": "near_boundary", "params": {"ani": ani, "boundary": ANI_BOUNDARY, "margin": MARGIN}})
    if not best.get("species"):
        reasons.append({"code": "no_species_name", "params": {"reference": best.get("accession") or best.get("reference"),
                                                              "organism": best.get("organism") or ""}})
    if other is not None and other.get("species"):
        if other["ani"] >= ANI_BOUNDARY:
            reasons.append({"code": "two_species_above_boundary",
                            "params": {"species": best.get("species") or "", "other": other["species"], "ani": ani,
                                       "other_ani": other["ani"], "boundary": ANI_BOUNDARY}})
        elif ani - other["ani"] <= MARGIN:
            reasons.append({"code": "close_species", "params": {"species": best.get("species") or "",
                                                                "other": other["species"], "ani": ani,
                                                                "other_ani": other["ani"], "margin": MARGIN}})
    af = best.get("af")
    if af is None:
        reasons.append({"code": "af_unknown", "params": {}})
    elif af < MIN_AF:
        reasons.append({"code": "low_af", "params": {"af": af, "min_af": MIN_AF}})
    if reasons:
        return {**out, "status": "ambiguous", "reasons": reasons}
    return {**out, "status": "same_species", "species": best["species"]}


# --- Consistency with MLST and the annotation's organism -------------------------------------------------------------

def scheme_stem(scheme: str) -> str:
    """The part of a PubMLST scheme name before its variant ("ecoli_achtman_4" → "ecoli", "listeria_2" →
    "listeria")."""
    return scheme.split("_", 1)[0].lower()


def scheme_matches(scheme: str, species: str) -> str:
    """How a scheme's name relates to a species name, by PubMLST's naming habit (genus initial + epithet, as in
    "saureus"; or the genus, as in "salmonella"): `species`, `genus` or `differs`. This compares names only: some
    schemes cover several species (e.g. S. argenteus is typed with the saureus scheme) or a complex ("bcc")."""
    stem = re.sub(r"[^a-z]", "", scheme_stem(scheme))
    genus, epithet = (w.lower() for w in species.split()[:2])
    genus = re.sub(r"_[a-z]+$", "", genus)
    if stem == genus[:1] + epithet or (stem.endswith(epithet) and len(stem) > len(epithet)
                                         and genus.startswith(stem[: len(stem) - len(epithet)])):
        return "species"
    if stem == genus:
        return "genus"
    return "differs"


def consistency(ani: dict[str, Any], mlst: dict[str, Any] | None, annotation: dict[str, Any] | None) -> list[dict]:
    """ARVA's checks of the ANI species against the MLST scheme mlst chose and the organism given for an annotation.
    Each check: source, outcome (agree, genus_agrees, differs, not_comparable) and its values."""
    species = ani.get("species") if ani.get("status") == "same_species" else None
    checks: list[dict[str, Any]] = []
    if mlst is not None:
        scheme = mlst.get("scheme")
        params = {"scheme": scheme or "", "st": mlst.get("st") or "", "species": species or ""}
        if not scheme:
            checks.append({"source": "mlst", "outcome": "not_comparable", "reason": "no_scheme", "params": params})
        elif species is None:
            checks.append({"source": "mlst", "outcome": "not_comparable", "reason": "no_ani_species", "params": params})
        else:
            match = scheme_matches(scheme, species)
            outcome = {"species": "agree", "genus": "genus_agrees", "differs": "differs"}[match]
            checks.append({"source": "mlst", "outcome": outcome, "reason": None, "params": params})
    if annotation is not None and annotation.get("genus"):
        given = " ".join(x for x in (annotation.get("genus"), annotation.get("species")) if x)
        params = {"given": given, "tool": annotation.get("tool") or "", "species": species or ""}
        if species is None:
            checks.append({"source": "annotation", "outcome": "not_comparable", "reason": "no_ani_species",
                           "params": params})
        else:
            g, s = species.lower().split()[:2]
            same_genus = annotation["genus"].lower() == g
            if same_genus and annotation.get("species"):
                outcome = "agree" if annotation["species"].lower() == s else "differs"
            else:
                outcome = "genus_agrees" if same_genus else "differs"
            checks.append({"source": "annotation", "outcome": outcome, "reason": None, "params": params})
    return checks


def interpret_gtdbtk(row: dict[str, Any] | None) -> dict[str, Any]:
    """GTDB-Tk's own call for one genome (it applies the GTDB species radius, usually 95 % ANI, and its --min_af): a
    species when the s__ rank is filled, otherwise the lowest rank it assigned. The names are GTDB's, which can
    differ from NCBI's (for example GTDB places Shigella in Escherichia)."""
    base = {"method": "gtdbtk", "thresholds": THRESHOLDS, "sources": SOURCES, "runner_up": None, "reasons": [],
            "caveats": [{"code": "gtdb_names", "params": {}}, {"code": "not_validated", "params": {}}]}
    if row is None or row.get("classification", "").startswith("Unclassified"):
        return {**base, "status": "no_hits", "species": None, "best": None}
    best = {"reference": row.get("closest_reference"), "accession": row.get("closest_reference"),
            "organism": row.get("closest_taxonomy"), "species": row.get("species"), "strain": None,
            "type_material": None, "ani": row.get("closest_ani"), "af": row.get("closest_af"), "distance": None}
    reasons = [{"code": "gtdbtk_warning", "params": {"text": row["warnings"]}}] if row.get("warnings") else []
    if row.get("species"):
        return {**base, "status": "ambiguous" if reasons else "same_species",
                "species": None if reasons else row["species"], "best": best, "reasons": reasons}
    ranks = [r for r in row.get("classification", "").split(";") if len(r) > 3]
    return {**base, "status": "below_boundary", "species": None, "best": best, "reasons": reasons,
            "lowest_rank": ranks[-1] if ranks else None}
