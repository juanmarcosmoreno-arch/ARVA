"""Genome Explorer API: the annotation list, GC/GC skew tracks and their bounds, read depth from a polishing depth
profile (or why there is none), sequence slices and FASTA downloads, the feature layout, region exports and the
checks of a feature's sequences against the genome.

The annotation is Prokka's real output on the SYNTHETIC fixture genome (test_annotation_api.prokka_fixture_annotation);
Prokka's .fna holds its input contigs, which for this genome is genome.fna itself. Results are not biology.
"""
import hashlib
import shutil

import pytest
from arva_core.genome_view import depth_bins, reverse_complement, write_depth_profile
from arva_core.seqstats import iter_fasta
from test_annotation_api import (  # noqa: F401  (setup is a fixture)
    API,
    GENOME,
    prokka_fixture_annotation,
    prokka_ready,
    setup,
)

from app.db.session import SessionLocal
from app.models import AnalysisJob, Annotation, Assembly, AssemblyKind, JobStatus

CHR, PLASMID = "SYNTHETIC_annotation_chromosome", "SYNTHETIC_annotation_plasmid"


def genome() -> dict[str, str]:
    with open(GENOME, "rb") as fh:
        return {h[1:].decode().split()[0]: s.decode() for h, s, _q, _n in iter_fasta(fh)}


@pytest.fixture
def ann(client, setup, storage_root):  # noqa: F811
    sample, assembly = setup
    ann_id = prokka_fixture_annotation(storage_root, sample, assembly)
    with SessionLocal() as db:
        a = db.get(Annotation, ann_id)
        rel = a.features_path.rsplit("/", 1)[0] + "/prokka/annotation.fna"
        shutil.copyfile(GENOME, storage_root / rel)
        a.files = {**a.files, "fna": {"path": rel, "sha256": "-", "size_bytes": 1}}
        db.commit()
    return sample, assembly, ann_id


def test_annotation_list_names_sample_project_and_assembly(client, ann):
    sample, assembly, ann_id = ann
    (row,) = [r for r in client.get(f"{API}/annotations").json() if r["id"] == ann_id]
    assert (row["sample_code"], row["project_id"], row["assembly_id"], row["tool"]) == (
        sample["sample_code"], sample["project_id"], assembly["id"], "Prokka")
    assert row["sequences"] == 2 and row["total_length"] == 18_960
    assert client.get(f"{API}/annotations", params={"limit": 0}).status_code == 422


def test_gc_track_matches_a_count_of_the_bases(client, ann):
    _, _, ann_id = ann
    seq = genome()[CHR]
    r = client.get(f"{API}/annotations/{ann_id}/tracks",
                   params={"contig": CHR, "start": 101, "end": 200, "window": 50, "step": 50}).json()
    gc = r["gc"]
    assert (r["contig"], r["length"], r["start"], r["end"]) == (CHR, 17_516, 101, 200)
    assert gc["start"] == [101, 151] and gc["end"] == [150, 200] and gc["group"] == 1 and not gc["auto"]
    for i, (s, e) in enumerate(zip(gc["start"], gc["end"], strict=True)):
        w = seq[s - 1:e]
        g, c = w.count("G"), w.count("C")
        assert gc["gc"][i] == round((g + c) / sum(w.count(b) for b in "ACGT"), 6)
        assert gc["skew"][i] == round((g - c) / (g + c), 6)
    assert gc["contig_gc"] == round(sum(seq.count(b) for b in "GC") / sum(seq.count(b) for b in "ACGT"), 6)
    assert r["sequence_source"]["file"] == "fna" and len(r["sequence_source"]["sha256"]) == 64


def test_tracks_choose_a_window_for_the_view_and_group_windows(client, ann):
    _, _, ann_id = ann
    whole = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": CHR, "bins": 100}).json()
    # 17,516 bp in at most 100 points: 175.16 bp per point -> the next 1-2-5 size is 200 bp, step 200
    assert whole["gc"]["auto"] and (whole["gc"]["window"], whole["gc"]["step"]) == (200, 200)
    assert whole["gc"]["windows"] == len(whole["gc"]["gc"]) == 88 and whole["gc"]["group"] == 1
    sliding = client.get(f"{API}/annotations/{ann_id}/tracks",
                         params={"contig": CHR, "bins": 100, "window": 500, "step": 10}).json()["gc"]
    assert sliding["windows"] == 1752 and sliding["group"] == 18 and len(sliding["gc"]) == 98
    assert all(lo <= m <= hi for lo, m, hi in zip(sliding["gc_min"], sliding["gc"], sliding["gc_max"], strict=True))
    by_assembly_name = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": PLASMID}).json()
    assert by_assembly_name["contig"] == PLASMID and by_assembly_name["end"] == 1_444


@pytest.mark.parametrize("params, code", [
    ({"contig": "nope"}, 404),
    ({}, 422),
    ({"contig": CHR, "start": 0}, 422),
    ({"contig": CHR, "start": 10, "end": 5}, 422),
    ({"contig": CHR, "end": 17_517}, 422),
    ({"contig": CHR, "bins": 5}, 422),
    ({"contig": CHR, "bins": 5001}, 422),
    ({"contig": CHR, "window": 10, "step": 20}, 422),
    ({"contig": CHR, "window": 0}, 422),
])
def test_track_bounds(client, ann, params, code):
    assert client.get(f"{API}/annotations/{ann[2]}/tracks", params=params).status_code == code


def test_coverage_says_why_it_is_not_available(client, ann):
    r = client.get(f"{API}/annotations/{ann[2]}/tracks", params={"contig": CHR}).json()
    assert r["coverage"]["available"] is False and r["coverage"]["reason"] == "no_alignment"


def polished_child(sample: dict, draft_id: str, storage_root, profile: bool) -> str:
    """A completed polishing job of the draft, its polished assembly, and (if asked) the draft alignment's profile."""
    seqs = genome()
    with SessionLocal() as db:
        job = AnalysisJob(project_id=sample["project_id"], sample_id=sample["id"], job_type="racon_polish",
                          tool_name="Racon", tool_version="1.5.0", parameters={}, input_raw_file_ids=[],
                          status=JobStatus.completed, log_text="")
        db.add(job)
        db.flush()
        indirect = {"aligner": "minimap2 2.26 -x map-ont", "reads": "long", "before": {}, "after": {}}
        if profile:
            rel = f"results/{sample['project_id']}/{sample['id']}/{job.id}/comparison/draft.depth_profile.json"
            path = storage_root / rel
            path.parent.mkdir(parents=True)
            lengths = {name: len(s) for name, s in seqs.items()}
            rows = [(CHR, p, 10 if p <= 100 else 20) for p in range(1, lengths[CHR] + 1)]
            write_depth_profile(path, depth_bins(rows, lengths, 25), lengths, 25,
                                {"alignment": "draft", "command": ["samtools", "depth", "-aa"], "deletions_counted": False,
                                 "overlapping_mates_counted_twice": True})
            indirect["before"] = {"depth_profile": {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                    "resolution": 25}}
        job.result_summary = {"indirect": indirect, "helpers": [{"tool_id": "samtools", "version": "1.19.2"}]}
        draft = db.get(Assembly, draft_id)
        child = Assembly(sample_id=sample["id"], job_id=job.id, kind=AssemblyKind.polished, parent_assembly_id=draft_id,
                         assembler="Racon", assembler_version="1.5.0", mode=draft.mode, read_type="map-ont",
                         input_file_ids=[], contigs_path=draft.contigs_path, stats=draft.stats, contigs=draft.contigs,
                         warnings=[])
        db.add(child)
        db.commit()
        return job.id


def test_coverage_from_the_draft_alignment_of_a_polishing_run(client, ann, storage_root):
    sample, assembly, ann_id = ann
    polished_child(sample, assembly["id"], storage_root, profile=False)
    old = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": CHR}).json()["coverage"]
    assert old["available"] is False and old["reason"] == "profile_missing"
    job_id = polished_child(sample, assembly["id"], storage_root, profile=True)
    r = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": CHR, "start": 51, "end": 150, "bins": 10})
    cov = r.json()["coverage"]
    assert cov["available"] and cov["source"]["job_id"] == job_id and cov["source"]["alignment"] == "draft"
    assert cov["source"]["samtools_version"] == "1.19.2" and cov["resolution"] == 25
    # the 25 bp bins 51-75 and 76-100 at depth 10, 101-125 and 126-150 at 20
    assert cov["start"] == [51, 76, 101, 126] and cov["end"] == [75, 100, 125, 150]
    assert cov["mean"] == [10.0, 10.0, 20.0, 20.0] and cov["group"] == 1
    grouped = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": CHR, "end": 1000, "bins": 10}).json()
    # 40 bins in groups of 4: the first point is positions 1-100 at depth 10, the second 101-200 at 20
    assert grouped["coverage"]["mean"][:2] == [10.0, 20.0] and grouped["coverage"]["group"] == 4
    assert cov["contig_mean_depth"] == round((100 * 10 + (17_516 - 100) * 20) / 17_516, 3)
    plasmid = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": PLASMID}).json()["coverage"]
    assert plasmid["available"] and set(plasmid["mean"]) == {0.0}


def test_sequence_slices_reverse_complement_and_fasta(client, ann):
    _, _, ann_id = ann
    seq = genome()[CHR]
    url = f"{API}/annotations/{ann_id}/sequence"
    fwd = client.get(url, params={"contig": CHR, "start": 233, "end": 1267}).json()
    assert fwd["sequence"] == seq[232:1267] and fwd["length"] == 1035 and fwd["sequence"].startswith("ATG")
    rev = client.get(url, params={"contig": CHR, "start": 233, "end": 1267, "strand": "-"}).json()
    assert rev["sequence"] == reverse_complement(seq[232:1267].encode()).decode()
    fasta = client.get(url, params={"contig": CHR, "start": 1, "end": 130, "strand": "-", "format": "fasta"})
    assert fasta.status_code == 200 and "attachment" in fasta.headers["content-disposition"]
    assert fasta.headers["content-disposition"].endswith('_1-130_rc.fasta"')
    lines = fasta.text.splitlines()
    assert lines[0].startswith(f">{CHR}:1-130(-) ") and "reverse complement" in lines[0]
    assert [len(x) for x in lines[1:]] == [60, 60, 10] and "".join(lines[1:]) == rev_of(seq[:130])
    for params in ({"contig": CHR, "start": 5, "end": 4}, {"contig": CHR, "start": 1, "end": 17_517},
                   {"contig": CHR, "start": 1, "end": 2, "strand": "x"}, {"contig": CHR, "start": 1}):
        assert client.get(url, params=params).status_code == 422
    assert client.get(url, params={"contig": "nope", "start": 1, "end": 2}).status_code == 404


def rev_of(s: str) -> str:
    return reverse_complement(s.encode()).decode()


def test_sequence_length_is_bounded(client, ann, monkeypatch):
    from app.services import genome_explorer

    monkeypatch.setattr(genome_explorer, "MAX_SEQUENCE", 100)
    r = client.get(f"{API}/annotations/{ann[2]}/sequence", params={"contig": CHR, "start": 1, "end": 101})
    assert r.status_code == 422 and "at most 100 bp" in r.json()["detail"]


def test_missing_sequence_file_is_reported(client, setup, storage_root):  # noqa: F811
    sample, assembly = setup
    ann_id = prokka_fixture_annotation(storage_root, sample, assembly)
    r = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": CHR})
    assert r.status_code == 404 and ".fna" in r.json()["detail"]


def test_layout_lists_every_feature_of_one_sequence(client, ann):
    _, _, ann_id = ann
    r = client.get(f"{API}/annotations/{ann_id}/layout", params={"contig": CHR}).json()
    assert r["total"] == len(r["items"]) == 18 and r["length"] == 17_516
    first = r["items"][0]
    assert (first["locus_tag"], first["type"], first["start"], first["end"], first["strand"]) == (
        "SYNT_00001", "cds", 233, 1267, "+")
    assert set(first) == {"id", "locus_tag", "tool_id", "type", "start", "end", "strand", "length", "edge", "gene",
                          "product", "hypothetical", "pseudo", "partial"}
    plasmid = client.get(f"{API}/annotations/{ann_id}/layout", params={"contig": PLASMID}).json()
    assert [f["locus_tag"] for f in plasmid["items"]] == ["SYNT_00019", "SYNT_00020"]
    assert client.get(f"{API}/annotations/{ann_id}/layout", params={"contig": "nope"}).status_code == 404


def test_region_exports(client, ann):
    _, _, ann_id = ann
    url = f"{API}/annotations/{ann_id}/export"
    region = {"contig": CHR, "start": 2400, "end": 2700}  # the tRNA SYNT_00003 and CDS SYNT_00004 (2619-2936)
    gff = client.post(url, json={"format": "gff3", "region": region})
    assert gff.status_code == 200 and "region_" in gff.headers["content-disposition"]
    tags = [ln.split("\t")[8] for ln in gff.text.splitlines() if ln and not ln.startswith("#")]
    assert len(tags) == 2 and "SYNT_00003" in tags[0] and "SYNT_00004" in tags[1]
    faa = client.post(url, json={"format": "fasta_aa", "region": region}).text
    assert [ln.split()[0] for ln in faa.splitlines() if ln.startswith(">")] == [">SYNT_00004"]
    ffn = client.post(url, json={"format": "fasta_nt", "region": region}).text
    assert [ln.split()[0] for ln in ffn.splitlines() if ln.startswith(">")] == [">SYNT_00003", ">SYNT_00004"]
    empty = client.post(url, json={"format": "gff3", "region": {"contig": CHR, "start": 1, "end": 100}})
    assert empty.status_code == 400 and "No feature" in empty.json()["detail"]
    assert client.post(url, json={"format": "gff3", "region": {"contig": CHR, "start": 9, "end": 1}}).status_code == 422
    assert client.post(url, json={"format": "gff3", "region": region, "feature_ids": [1]}).status_code == 422
    assert client.post(url, json={"format": "gff3", "region": {"contig": "x", "start": 1, "end": 2}}).status_code == 404
    assert client.post(url, json={"format": "gff3", "region": {"contig": CHR, "start": 1,
                                                                 "end": 99_999}}).status_code == 422


def test_feature_detail_checks_sequences_against_the_genome(client, ann):
    _, _, ann_id = ann
    features = client.get(f"{API}/annotations/{ann_id}/features", params={"limit": 100}).json()["items"]
    for f in features:
        d = client.get(f"{API}/annotations/{ann_id}/features/{f['id']}").json()
        assert d["checks"]["nucleotide"]["status"] == "match", f["locus_tag"]
        if f["type"] == "cds":
            # Prokka's proteins equal the translation of the genome at their coordinates (table 11)
            assert d["checks"]["protein"] == {"table": 11, "status": "match", "reason": None, "first_difference": None,
                                              "translated_length": None, "protein_length": None,
                                              "internal_stops": None}, f["locus_tag"]
        else:
            assert d["checks"]["protein"]["reason"] == "not_coding"


@pytest.mark.skipif(not prokka_ready(), reason="Prokka or its databases are not installed")
def test_a_real_prokka_annotation_opens_in_the_explorer(client, setup):  # noqa: F811
    _, assembly = setup
    r = client.post(f"{API}/assemblies/{assembly['id']}/annotate/prokka",
                    json={"settings": {"locus_tag": "SYNT"}, "confirmed": True, "threads": 2})
    assert client.get(f"{API}/jobs/{r.json()['id']}").json()["status"] == "completed"
    (ann_id,) = [a["id"] for a in client.get(f"{API}/assemblies/{assembly['id']}/annotations").json()]
    seqs = genome()
    for name, seq in seqs.items():
        whole = client.get(f"{API}/annotations/{ann_id}/sequence",
                           params={"contig": name, "start": 1, "end": len(seq)}).json()
        assert whole["sequence"] == seq  # Prokka's .fna holds the input contigs unchanged
    tracks = client.get(f"{API}/annotations/{ann_id}/tracks", params={"contig": CHR}).json()
    assert tracks["coverage"]["reason"] == "no_alignment" and tracks["gc"]["contig_gc"] is not None
    layout = client.get(f"{API}/annotations/{ann_id}/layout", params={"contig": CHR}).json()
    for f in layout["items"]:
        checks = client.get(f"{API}/annotations/{ann_id}/features/{f['id']}").json()["checks"]
        assert checks["nucleotide"]["status"] == "match"
        if f["type"] == "cds":
            assert checks["protein"]["status"] == "match", f["locus_tag"]


# --- Circular map ------------------------------------------------------------------------------------------------

def test_map_draws_every_sequence_in_windows_of_one_length(client, ann):
    _, _, ann_id = ann
    seqs = genome()
    r = client.get(f"{API}/annotations/{ann_id}/map").json()
    # 18,960 bp in about 1,440 windows: 13.2 bp each -> at least 20 bp (the smallest automatic window)
    assert r["total_length"] == 18_960 and r["gc"] == {"window": 20, "step": 20, "auto": True,
                                                      "genome_gc": r["gc"]["genome_gc"]}
    assert [s["contig"] for s in r["sequences"]] == [CHR, PLASMID]
    chromosome, plasmid = r["sequences"]
    assert len(chromosome["gc"]["gc"]) == 876 and len(plasmid["gc"]["gc"]) == 73  # 17,516 / 20 and 1,444 / 20, up
    assert plasmid["gc"]["start"][-1] == 1_441 and plasmid["gc"]["end"][-1] == 1_444  # the last window is cut
    w = seqs[CHR][20:40]
    g, c = w.count("G"), w.count("C")
    assert chromosome["gc"]["gc"][1] == round((g + c) / sum(w.count(b) for b in "ACGT"), 6)
    assert chromosome["gc"]["skew"][1] == round((g - c) / (g + c), 6)
    every = "".join(seqs.values())
    assert r["gc"]["genome_gc"] == round(sum(every.count(b) for b in "GC") / sum(every.count(b) for b in "ACGT"), 6)
    assert r["total"] == len(r["features"]) == 20 and r["features"][-1]["contig"] == PLASMID
    assert r["coverage"] == {"available": False, "reason": "no_alignment", "source": None}
    assert chromosome["coverage"]["available"] is False and chromosome["coverage"]["reason"] == "no_alignment"


def test_map_of_chosen_sequences_and_bounds(client, ann):
    _, _, ann_id = ann
    url = f"{API}/annotations/{ann_id}/map"
    one = client.get(url, params={"contig": [PLASMID, PLASMID], "points": 100}).json()
    # 1,444 bp in about 100 windows: 14.4 bp -> 20 bp; the plasmid named twice is drawn once
    assert [s["contig"] for s in one["sequences"]] == [PLASMID] and one["gc"]["window"] == 20
    assert {f["locus_tag"] for f in one["features"]} == {"SYNT_00019", "SYNT_00020"}
    coarse = client.get(url, params={"points": 100}).json()
    assert coarse["gc"]["window"] == 200 and not client.get(url, params={"window": 500}).json()["gc"]["auto"]
    assert client.get(url, params={"contig": "nope"}).status_code == 404
    assert client.get(url, params={"window": 1}).status_code == 422  # 18,960 windows, more than a map draws
    assert client.get(url, params={"points": 5}).status_code == 422
    assert client.get(url, params={"contig": [CHR, PLASMID, CHR]}).status_code == 422


def test_map_coverage_in_the_map_windows(client, ann, storage_root):
    sample, assembly, ann_id = ann
    polished_child(sample, assembly["id"], storage_root, profile=True)
    r = client.get(f"{API}/annotations/{ann_id}/map", params={"window": 100}).json()
    assert r["coverage"]["available"] and r["coverage"]["source"]["alignment"] == "draft"
    cov = r["sequences"][0]["coverage"]
    # 25 bp bins grouped by 4: 100 bp points; the first at depth 10, the rest at 20
    assert cov["start"][:2] == [1, 101] and cov["end"][:2] == [100, 200] and cov["mean"][:2] == [10.0, 20.0]
    assert len(cov["mean"]) == 176 and set(r["sequences"][1]["coverage"]["mean"]) == {0.0}
