"""arva_core.genome_view: GC and GC skew windows, grouping, slices, reverse complement, translation, the protein check
and the read-depth profile. Every expected value is computed by hand in the comments."""
import pytest

from arva_core.genome_view import (
    MAX_WINDOWS,
    auto_window,
    depth_bins,
    depth_points,
    gc_fraction,
    gc_windows,
    parse_depth_lines,
    protein_check,
    read_depth_profile,
    reverse_complement,
    slice_sequence,
    translate,
    window_range,
    write_depth_profile,
)

SEQ = b"GGGCATNNCC"  # positions 1-10


def test_non_overlapping_windows():
    r = gc_windows(SEQ, 0, 10, window=5, step=5)
    # GGGCA: G3 C1 A1 -> GC 4/5 = 0.8, skew (3-1)/4 = 0.5; TNNCC: T1 C2 (N not counted) -> GC 2/3, skew (0-2)/2 = -1
    assert r["start"] == [1, 6] and r["end"] == [5, 10]
    assert r["gc"] == [0.8, 0.666667] and r["skew"] == [0.5, -1.0]
    assert r["windows"] == 2 and r["group"] == 1
    assert r["gc_min"] == r["gc"] == r["gc_max"]


def test_sliding_windows_are_cut_at_the_end_and_have_no_value_without_bases():
    r = gc_windows(SEQ, 0, 10, window=4, step=2)
    # [1-4] GGGC: GC 1, skew 2/4; [3-6] GCAT: GC 2/4, skew 0; [5-8] ATNN: GC 0, no G or C -> no skew;
    # [7-10] NNCC: GC 1, skew -1; [9-10] CC (cut at the end): GC 1, skew -1
    assert r["start"] == [1, 3, 5, 7, 9] and r["end"] == [4, 6, 8, 10, 10]
    assert r["gc"] == [1.0, 0.5, 0.0, 1.0, 1.0]
    assert r["skew"] == [0.5, 0.0, None, -1.0, -1.0]


def test_windows_without_unambiguous_bases_have_no_gc():
    assert gc_windows(b"NNNNGG", 0, 6, window=4, step=4)["gc"] == [None, 1.0]


def test_grouping_gives_mean_min_and_max_of_the_windows():
    r = gc_windows(SEQ, 0, 10, window=4, step=2, max_points=2)
    # 5 windows in groups of ceil(5/2) = 3: GC (1 + 0.5 + 0)/3 = 0.5, min 0, max 1; skew (0.5 + 0)/2 (the window
    # without a value left out) = 0.25, min 0, max 0.5; the second group: GC 1, skew -1
    assert r["group"] == 3 and r["windows"] == 5
    assert r["start"] == [1, 7] and r["end"] == [8, 10]
    assert r["gc"] == [0.5, 1.0] and r["gc_min"] == [0.0, 1.0] and r["gc_max"] == [1.0, 1.0]
    assert r["skew"] == [0.25, -1.0] and r["skew_min"] == [0.0, -1.0] and r["skew_max"] == [0.5, -1.0]


def test_windows_stay_on_the_grid_when_the_view_moves():
    # The view [4, 5) (positions 4-5): windows k with [2k, 2k+4) overlapping it are k = 0, 1, 2
    assert window_range(10, 3, 5, 4, 2) == (0, 2)
    r = gc_windows(SEQ, 3, 5, window=4, step=2)
    assert r["start"] == [1, 3, 5] and r["gc"] == [1.0, 0.5, 0.0]
    assert gc_windows(SEQ, 4, 10, 4, 2)["gc"][:2] == r["gc"][1:]


def test_lower_case_counts_and_bad_ranges_are_refused():
    assert gc_windows(b"ggccaatt", 0, 8, 8, 8)["gc"] == [0.5]
    assert gc_fraction(SEQ) == round(6 / 8, 6)  # G3 C3 of A1 T1 G3 C3
    assert gc_fraction(b"NNN") is None
    for args in ((0, 11, 5, 5), (5, 5, 5, 5), (0, 10, 0, 1), (0, 10, 4, 5)):
        with pytest.raises(ValueError):
            gc_windows(SEQ, *args)
    with pytest.raises(ValueError, match="windows would be computed"):
        gc_windows(b"A" * (MAX_WINDOWS + 1), 0, MAX_WINDOWS + 1, 1, 1)


def test_auto_window_uses_1_2_5_steps():
    assert auto_window(5_000, 1_000) == 20  # 5 bp would do, but the minimum is 20
    assert auto_window(5_000_000, 1_000) == 5_000
    assert auto_window(3_000_000, 1_000) == 5_000
    assert auto_window(1_100_000, 1_000) == 2_000
    assert auto_window(100_000, 1_000) == 100


def test_slices_and_reverse_complement():
    assert reverse_complement(b"ACGTRYKMBDHVNWSacgtn") == b"nacgtSWNBDHVKMRYACGT"
    s = b"AACCGGTA"
    assert slice_sequence(s, 2, 4) == b"ACC"
    assert slice_sequence(s, 2, 4, "-") == b"GGT"
    assert slice_sequence(s, 7, 2, circular=True) == b"TAAA"  # 7-8 then 1-2
    assert slice_sequence(s, 7, 2, "-", circular=True) == b"TTTA"
    for args in ((0, 2), (2, 9), (7, 2)):
        with pytest.raises(ValueError):
            slice_sequence(s, *args)
    with pytest.raises(ValueError):
        slice_sequence(s, 1, 2, "x")


def test_translation_tables():
    assert translate("ATGGCTTGA", 11) == "MA*"
    assert translate("GTGAAATAA", 11) == "MK*"  # GTG is a start codon of table 11
    assert translate("GTGAAATAA", 11, first_is_start=False) == "VK*"
    assert translate("ATGTGA", 4) == "MW" and translate("ATGTGA", 25) == "MG"
    assert translate("TTAAAA", 4) == "MK" and translate("TTAAAA", 11) == "LK"  # TTA starts only in table 4
    assert translate("ATNAAA", 11) == "XK"
    with pytest.raises(ValueError):
        translate("ATGA", 11)
    with pytest.raises(ValueError):
        translate("ATG", 1)


def test_protein_check():
    assert protein_check("GTGAAATAA", "MK", 11, None, False)["status"] == "match"
    differs = protein_check("GTGAAATAA", "VK", 11, None, False)
    assert differs["status"] == "differs" and differs["first_difference"] == 1
    assert protein_check("GTGAAATAA", "VK", 11, "5'", False)["status"] == "match"  # no start codon at a 5' break
    stop = protein_check("ATGTGAAAATAA", "MWK", 11, None, False)
    assert stop["status"] == "differs" and stop["internal_stops"] == 1 and stop["first_difference"] == 2
    assert protein_check("ATGTGAAAATAA", "MWK", 4, None, False)["status"] == "match"
    assert protein_check("ATGAAATA", "MK", 11, None, False)["reason"] == "length"
    assert protein_check("ATGAAATAA", "MK", 11, None, True)["reason"] == "pseudogene"


def test_depth_profile_bins_points_and_file(tmp_path):
    rows = list(parse_depth_lines(["c\t1\t2\n", "c\t2\t2\n", "c\t3\t6\n", "c\t4\t6\n", "c\t5\t1\n", "\n"]))
    sums = depth_bins(rows, {"c": 5, "empty": 3}, 2)
    # bins of 2 bp: positions 1-2 sum 4, 3-4 sum 12, 5 sum 1; a contig without reads stays at 0
    assert sums == {"c": [4, 12, 1], "empty": [0, 0]}
    p = depth_points(sums["c"], 5, 2, 0, 5)
    assert p["start"] == [1, 3, 5] and p["end"] == [2, 4, 5] and p["mean"] == [2.0, 6.0, 1.0]
    grouped = depth_points(sums["c"], 5, 2, 0, 5, max_points=2)
    # (4 + 12) / 4 bases = 4, bin means 2 and 6; then 1 / 1 base
    assert grouped["mean"] == [4.0, 1.0] and grouped["min"] == [2.0, 1.0] and grouped["max"] == [6.0, 1.0]
    assert depth_points(sums["c"], 5, 2, 2, 3)["start"] == [3]
    with pytest.raises(ValueError):
        depth_bins([("x", 1, 1)], {"c": 5}, 2)
    with pytest.raises(ValueError):
        depth_bins([("c", 6, 1)], {"c": 5}, 2)
    with pytest.raises(ValueError):
        list(parse_depth_lines(["c\t1\n"]))
    path = tmp_path / "profile.json"
    write_depth_profile(path, sums, {"c": 5, "empty": 3}, 2, {"tool": "samtools depth"})
    profile = read_depth_profile(path)
    assert profile["contigs"][0] == {"name": "c", "length": 5, "mean_depth": 3.4, "sums": [4, 12, 1]}
    path.write_text('{"format": "arva-depth-profile", "version": 1, "resolution": 2, "contigs": '
                    '[{"name": "c", "length": 5, "sums": [1]}]}')
    with pytest.raises(ValueError):
        read_depth_profile(path)
