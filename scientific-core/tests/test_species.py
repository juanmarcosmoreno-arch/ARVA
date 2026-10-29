"""ARVA's reading of ANI hits and its consistency checks. The values in the first tests are the real FastANI 1.34 and
skani 0.4.0 results of workflows/tool-adapters/tests/fixtures/species (NCBI RefSeq genomes); the rest are rule
cases built around the thresholds."""
import pytest

from arva_core.species import (
    ANI_BOUNDARY,
    MARGIN,
    MIN_AF,
    collection_scope,
    consistency,
    interpret,
    scheme_matches,
    species_of,
)

STAPH = {"species": 3, "genera": ["Staphylococcus"]}


def hit(species, ani, af=0.95, accession="GCF_000000001.1", type_material=True, **extra):
    return {"species": species, "ani": ani, "af": af, "accession": accession, "organism": species,
            "type_material": type_material, **extra}


def codes(items):
    return [x["code"] for x in items]


def test_real_fastani_saureus_is_same_species_as_the_type_strain():
    hits = [hit("Staphylococcus aureus", 99.9171, 900 / 940, "GCF_006094915.1"),
            hit("Staphylococcus argenteus", 88.85, 815 / 940, "GCF_000236925.1"),
            hit("Staphylococcus epidermidis", 79.1388, 317 / 940, "GCF_006094375.1")]
    r = interpret(hits, "fastani", STAPH)
    assert r["status"] == "same_species" and r["species"] == "Staphylococcus aureus"
    assert r["runner_up"]["species"] == "Staphylococcus argenteus"
    assert codes(r["caveats"]) == ["collection_bound", "single_genus", "fastani_range"]
    assert r["thresholds"] == {"ani_boundary": 95.0, "min_af": 0.5, "margin": 0.5}


def test_real_collection_without_the_species_gives_no_reference_within_the_boundary():
    hits = [hit("Staphylococcus argenteus", 88.85, 815 / 940), hit("Staphylococcus epidermidis", 79.1388, 317 / 940)]
    r = interpret(hits, "fastani", {"species": 2, "genera": ["Staphylococcus"]})
    assert r["status"] == "below_boundary" and r["species"] is None
    assert r["best"]["species"] == "Staphylococcus argenteus"


def test_real_ecoli_against_ecoli_and_shigella_is_ambiguous():
    # FastANI: E. coli O157:H7 Sakai vs K-12 MG1655 97.7623 %, vs Shigella flexneri 2a 301 96.9917 %.
    hits = [hit("Escherichia coli", 97.7623, 1406 / 1863, type_material=False),
            hit("Shigella flexneri", 96.9917, 1353 / 1863, type_material=False)]
    r = interpret(hits, "fastani", {"species": 2, "genera": ["Escherichia", "Shigella"]})
    assert r["status"] == "ambiguous" and r["species"] is None
    assert codes(r["reasons"]) == ["two_species_above_boundary"]
    assert "not_type_material" in codes(r["caveats"]) and "single_genus" not in codes(r["caveats"])


def test_no_hits_and_synthetic_genome():
    r = interpret([], "skani", STAPH)
    assert r["status"] == "no_hits" and r["best"] is None


@pytest.mark.parametrize(("ani", "status", "reason"), [
    (ANI_BOUNDARY + MARGIN, "same_species", None),
    (ANI_BOUNDARY + MARGIN - 0.01, "ambiguous", "near_boundary"),
    (ANI_BOUNDARY - MARGIN, "ambiguous", "near_boundary"),
    (ANI_BOUNDARY - MARGIN - 0.01, "below_boundary", None),
])
def test_boundary_and_margin(ani, status, reason):
    r = interpret([hit("Bacillus subtilis", ani)], "fastani")
    assert r["status"] == status
    assert codes(r["reasons"]) == ([reason] if reason else [])


def test_low_aligned_fraction_makes_a_high_ani_ambiguous():
    r = interpret([hit("Bacillus subtilis", 99.5, MIN_AF - 0.01)], "skani")
    assert r["status"] == "ambiguous" and codes(r["reasons"]) == ["low_af"]
    assert interpret([hit("Bacillus subtilis", 99.5, MIN_AF)], "skani")["status"] == "same_species"


def test_close_second_species_below_the_boundary_is_named():
    r = interpret([hit("Genus alpha", 95.3), hit("Genus beta", 94.9)], "fastani")
    assert r["status"] == "ambiguous" and codes(r["reasons"]) == ["near_boundary", "close_species"]


def test_same_species_references_do_not_compete_and_unnamed_best_is_ambiguous():
    r = interpret([hit("Genus alpha", 99.0), hit("Genus alpha", 98.9), hit(None, 98.8)], "fastani")
    assert r["status"] == "same_species" and r["runner_up"] is None
    r = interpret([hit(None, 99.0, organism="Genus sp. X1")], "fastani")
    assert r["status"] == "ambiguous" and codes(r["reasons"]) == ["no_species_name"]


def test_unknown_aligned_fraction_is_not_assumed():
    r = interpret([hit("Genus alpha", 99.0, None)], "sylph")
    assert r["status"] == "ambiguous" and codes(r["reasons"]) == ["af_unknown"]
    assert "sylph_assembly" in codes(r["caveats"])


def test_mash_is_only_ranked():
    hits = [{"species": "Staphylococcus argenteus", "distance": 0.0920479, "shared": 78},
            {"species": "Staphylococcus aureus", "distance": 0.00173271, "shared": 931},
            {"species": None, "distance": 1.0, "shared": 0}]
    r = interpret(hits, "mash")
    assert r["status"] == "screening_only" and r["species"] is None
    assert r["best"]["species"] == "Staphylococcus aureus" and codes(r["caveats"])[0] == "mash_not_ani"
    assert interpret([{"species": None, "distance": 1.0, "shared": 0}], "mash")["status"] == "no_hits"


def test_species_and_scope():
    assert species_of("Staphylococcus aureus subsp. aureus NCTC 8325") == "Staphylococcus aureus"
    assert species_of("Staphylococcus sp. HMSC") is None
    assert collection_scope(["Escherichia coli", "Shigella flexneri", None]) == {
        "species": 2, "genera": ["Escherichia", "Shigella"]}


@pytest.mark.parametrize(("scheme", "species", "match"), [
    ("saureus", "Staphylococcus aureus", "species"),
    ("ecoli_achtman_4", "Escherichia coli", "species"),
    ("staphlugdunensis", "Staphylococcus lugdunensis", "species"),
    ("listeria_2", "Listeria monocytogenes", "genus"),
    ("saureus", "Staphylococcus argenteus", "differs"),
    ("bcc", "Burkholderia cenocepacia", "differs"),
    ("ecoli", "Staphylococcus aureus", "differs"),
])
def test_scheme_names(scheme, species, match):
    assert scheme_matches(scheme, species) == match


def test_consistency_checks():
    same = {"status": "same_species", "species": "Staphylococcus aureus"}
    checks = consistency(same, {"scheme": "saureus", "st": "8"}, {"genus": "Staphylococcus", "species": "aureus",
                                                                    "tool": "bakta"})
    assert [(c["source"], c["outcome"]) for c in checks] == [("mlst", "agree"), ("annotation", "agree")]
    checks = consistency(same, {"scheme": "sepidermidis", "st": "2"}, {"genus": "Staphylococcus", "species": None})
    assert [(c["source"], c["outcome"]) for c in checks] == [("mlst", "differs"), ("annotation", "genus_agrees")]
    checks = consistency(same, {"scheme": None, "st": None}, {"genus": "Escherichia", "species": "coli"})
    assert [(c["outcome"], c["reason"]) for c in checks] == [("not_comparable", "no_scheme"), ("differs", None)]
    ambiguous = {"status": "ambiguous", "species": None}
    checks = consistency(ambiguous, {"scheme": "ecoli_achtman_4", "st": "10"}, None)
    assert [(c["outcome"], c["reason"]) for c in checks] == [("not_comparable", "no_ani_species")]
    assert consistency(same, None, {"genus": None}) == []
