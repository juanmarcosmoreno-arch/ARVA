import io

import pytest

from arva_core import comparative as c
from arva_core.seqstats import iter_fasta

IDS = ["mu50", "n315", "sepi", "usa300"]
# skani triangle on the four NCBI genomes (workflows/tool-adapters/tests/fixtures/comparative): S. epidermidis has no row.
SKANI = [
    {"reference": "mu50", "query": "n315", "ani": 99.90, "af_reference": 0.9596, "af_query": 0.9813},
    {"reference": "mu50", "query": "usa300", "ani": 98.86, "af_reference": 0.9185, "af_query": 0.9141},
    {"reference": "n315", "query": "usa300", "ani": 98.97, "af_reference": 0.9370, "af_query": 0.9119},
]


def test_contig_lengths_use_the_first_word_of_the_header():
    fasta = b">c1 chromosome\nACGT\nAC\n>c2\nGG\n"
    assert c.contig_lengths(iter_fasta(io.BytesIO(fasta))) == [{"name": "c1", "length": 6}, {"name": "c2", "length": 2}]
    assert c.layout([{"name": "c1", "length": 6}, {"name": "c2", "length": 2}]) == {"offsets": {"c1": 0, "c2": 6},
                                                                                       "total": 8}


def test_undirected_matrix_fills_both_cells_and_keeps_missing_pairs_empty():
    m = c.ani_matrix(IDS, SKANI, directional=False)
    assert m["ani"][0][1] == m["ani"][1][0] == 99.90
    assert m["af"][1][0] == 0.9813 and m["af"][0][1] == 0.9596
    assert all(m["ani"][2][j] is None for j in range(4)) and m["ani"][0][0] is None


def test_directional_matrix_keeps_each_direction():
    pairs = [{"query": "mu50", "reference": "n315", "ani": 99.9032, "af_query": 924 / 967},
             {"query": "n315", "reference": "mu50", "ani": 99.9143, "af_query": 929 / 946}]
    m = c.ani_matrix(IDS, pairs, directional=True)
    assert m["ani"][0][1] == 99.9032 and m["ani"][1][0] == 99.9143 and m["directional"]


def test_similarity_order_is_average_linkage_and_puts_missing_pairs_last():
    m = c.ani_matrix(IDS, SKANI, directional=False)
    o = c.similarity_order(m["ani"])
    assert o["merges"][0] == [0, 1, pytest.approx(0.1), 2]
    # (1.14 + 1.03) / 2: the average of usa300's distances to mu50 and n315.
    assert o["merges"][1] == [3, 4, pytest.approx(1.085), 3]
    assert o["merges"][2] == [2, 5, 100.0, 4]
    assert o["order"] == [2, 3, 0, 1]
    assert c.similarity_order([])["order"] == [] and c.similarity_order([[None]])["order"] == [0]


def test_auto_window():
    assert c.auto_window(500) == 1000
    assert c.auto_window(2_814_816) == 2000
    assert c.auto_window(10_000_000) == 5000


BLOCKS = [
    {"ref": "r", "ref_start": 1, "ref_end": 1000, "query": "q", "query_start": 1, "query_end": 1000, "strand": "+",
     "identity": 99.0, "length": 1000},
    {"ref": "r", "ref_start": 501, "ref_end": 1500, "query": "q", "query_start": 2001, "query_end": 3000,
     "strand": "-", "identity": 90.0, "length": 1000},
]


def test_pair_summary_counts_overlaps_once():
    s = c.pair_summary(BLOCKS, ref_total=2000, query_total=4000)
    assert s["ref_aligned"] == 1500 and s["query_aligned"] == 2000
    assert s["ref_fraction"] == 0.75 and s["query_fraction"] == 0.5
    assert s["identity"] == 94.5 and (s["forward"], s["reverse"]) == (1, 1)
    assert c.pair_summary([], 10, 10)["identity"] is None


def test_conservation_takes_the_best_identity_per_base():
    rows = c.conservation([{"name": "r", "length": 2500}], BLOCKS, window=1000)
    assert [(r["start"], r["end"]) for r in rows] == [(1, 1000), (1001, 2000), (2001, 2500)]
    assert rows[0] == {"contig": "r", "start": 1, "end": 1000, "covered": 1.0, "identity": 99.0}
    assert rows[1]["covered"] == 0.5 and rows[1]["identity"] == 90.0
    assert rows[2]["covered"] == 0.0 and rows[2]["identity"] is None
