import gzip

import pytest

from arva_core.gfa import GfaFormatError, read_gfa

# Flye writes "S name seq dp:i:N", links with RC:i and one P line per contig.
GFA = (
    "H\tVN:Z:1.0\n"
    "S\tedge_1\tACGTACGTAC\tdp:i:51\n"
    "S\tedge_2\t*\tLN:i:4\tdp:i:90\tKC:i:7\n"
    "S\tedge_3\tACG\tdp:f:1.5\tSN:Z:x\n"
    "L\tedge_1\t+\tedge_2\t-\t0M\tRC:i:3\n"
    "L\tedge_2\t+\tedge_3\t+\t0M\n"
    "L\tedge_3\t-\tedge_9\t+\t0M\n"
    "P\tcontig_1\tedge_1+,edge_2-\t*\n"
)


def write(tmp_path, text, name="g.gfa", compress=False):
    path = tmp_path / name
    path.write_bytes(gzip.compress(text.encode()) if compress else text.encode())
    return path


def test_reads_segments_links_and_numeric_tags(tmp_path):
    g = read_gfa(write(tmp_path, GFA))
    assert (g["format"], g["version"]) == ("GFA1", "1.0")
    assert (g["segment_count"], g["link_count"], g["path_count"], g["dangling_links"]) == (3, 3, 1, 1)
    assert g["total_segment_length"] == 17
    assert g["numeric_tags"] == ["KC", "LN", "dp"]
    assert g["nodes"] == [
        {"id": "edge_1", "length": 10, "tags": {"dp": 51}},
        {"id": "edge_2", "length": 4, "tags": {"LN": 4, "dp": 90, "KC": 7}},
        {"id": "edge_3", "length": 3, "tags": {"dp": 1.5}},
    ]
    assert g["edges"] == [
        {"source": "edge_1", "source_orientation": "+", "target": "edge_2", "target_orientation": "-",
         "overlap": "0M", "tags": {"RC": 3}},
        {"source": "edge_2", "source_orientation": "+", "target": "edge_3", "target_orientation": "+",
         "overlap": "0M", "tags": {}},
    ]
    assert g["truncated"] is False


def test_caps_keep_the_longest_segments_and_flag_truncation(tmp_path):
    path = write(tmp_path, GFA, compress=True)
    g = read_gfa(path, max_nodes=2)
    assert [n["id"] for n in g["nodes"]] == ["edge_1", "edge_2"]
    assert [(e["source"], e["target"]) for e in g["edges"]] == [("edge_1", "edge_2")]
    assert g["truncated"] is True and g["segment_count"] == 3
    g = read_gfa(path, max_edges=1)
    assert len(g["nodes"]) == 3 and len(g["edges"]) == 1 and g["truncated"] is True
    with pytest.raises(ValueError):
        read_gfa(path, max_nodes=0)


def test_ties_keep_file_order(tmp_path):
    g = read_gfa(write(tmp_path, "S\tb\tAC\nS\ta\tGT\nS\tc\tACGT\n"), max_nodes=2)
    assert [n["id"] for n in g["nodes"]] == ["c", "b"]
    assert g["version"] is None


@pytest.mark.parametrize("text,message", [
    ("H\tVN:Z:2.0\n", "GFA 2.0 is not supported"),
    ("S\ta\tACGT\nE\t*\ta+\tb-\t0\t1\t0\t1\t*\n", "line 2: 'E' records belong to GFA 2"),
    ("S\ta\tACGT\nS\ta\tAC\n", "line 2: segment 'a' is defined twice"),
    ("S\ta\t*\n", "neither a sequence nor an LN tag"),
    ("S\ta\tACGT\tLN:i:5\n", "LN:i:5 but the sequence has 4 bases"),
    ("S\ta\n", "needs a name and a sequence"),
    ("S\ta\tACGT\tdp:i:x\n", "non-numeric value"),
    ("S\ta\tACGT\tbroken\n", "malformed optional field"),
    ("S\ta\tAC\nS\tb\tAC\nL\ta\t+\tb\t?\t0M\n", "line 3: link orientations"),
    ("L\ta\t+\tb\n", "link line needs"),
])
def test_rejects_malformed_graphs(tmp_path, text, message):
    with pytest.raises(GfaFormatError, match=message):
        read_gfa(write(tmp_path, text))


def test_rejects_binary_content(tmp_path):
    path = tmp_path / "bin.gfa"
    path.write_bytes(b"S\ta\t\xff\xfe\n")
    with pytest.raises(GfaFormatError, match="not UTF-8"):
        read_gfa(path)
