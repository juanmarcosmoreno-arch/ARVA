"""Racon, Pilon, the read mappers and MUMmer dnadiff: parameters, argument vectors and parsers of real outputs
(fixtures/polishing/README.md)."""
import os
from pathlib import Path

import pytest

from arva_tools.base import help_options
from arva_tools.dnadiff import DnadiffAdapter
from arva_tools.mapping import BwaAdapter, Minimap2Adapter, SamtoolsAdapter
from arva_tools.pilon import FIXED_OPTIONS, PilonAdapter, PilonParams, locate_jar, upstream_version
from arva_tools.pilon import FLAGS as PILON_FLAGS
from arva_tools.racon import FLAGS as RACON_FLAGS
from arva_tools.racon import RaconAdapter, RaconParams

F = Path(__file__).resolve().parent / "fixtures" / "polishing"


def opts(name: str) -> frozenset[str]:
    return help_options((F / name).read_text())


def test_every_flag_arva_passes_is_in_the_recorded_help():
    assert set(RACON_FLAGS) <= opts("racon_help_1.5.0.txt")
    assert "--no-trimming" in opts("racon_help_1.5.0.txt")
    assert set(PILON_FLAGS) <= opts("pilon_help_1.24.txt") and "--threads" not in opts("pilon_help_1.24.txt")
    assert {"-a", "-x", "-t", "-o"} <= opts("minimap2_help_2.26.txt")
    assert "-p" in opts("bwa_index_usage_0.7.17.txt") and {"-t", "-K"} <= opts("bwa_mem_usage_0.7.17.txt")
    assert {"-T", "-o"} <= opts("samtools_sort_usage_1.19.2.txt")
    assert {"-a", "-Q", "-q", "-l", "-G"} <= opts("samtools_depth_usage_1.19.2.txt")
    assert "-a -a, -aa   Output absolutely all positions" in (F / "samtools_depth_usage_1.19.2.txt").read_text()
    assert "[UNMAP,SECONDARY,QCFAIL,DUP]" in (F / "samtools_depth_usage_1.19.2.txt").read_text()
    assert "-@, --threads INT" in (F / "samtools_sort_usage_1.19.2.txt").read_text()
    assert "-p|prefix" in (F / "dnadiff_help_1.3.txt").read_text()
    for preset in ("map-ont", "map-pb", "map-hifi"):
        assert preset in (F / "minimap2_help_2.26.txt").read_text()


@pytest.mark.parametrize("values, message", [
    ({"read_type": "map-x"}, "read_type must be one of map-ont, map-pb, map-hifi"),
    ({"rounds": 0}, "rounds must be between 1 and 5"),
    ({"rounds": 6}, "rounds must be between 1 and 5"),
    ({"match": 0}, "match must be a positive"),
    ({"mismatch": 5}, "mismatch must be a negative"),
    ({"gap": 0}, "gap must be a negative"),
    ({"window_length": 50}, "window_length"),
    ({"quality_threshold": float("nan")}, "quality_threshold"),
    ({"error_threshold": 0}, "error_threshold"),
    ({"threads": 0}, "threads"),
    ({"rounds": True}, "rounds"),
])
def test_racon_parameters_are_validated(values, message):
    with pytest.raises(ValueError, match=message):
        RaconParams.from_dict({"read_type": "map-ont", **values}).validate()


def test_racon_argv_passes_every_setting_and_keeps_unpolished_contigs():
    supported = opts("racon_help_1.5.0.txt")
    p = RaconParams("map-ont", threads=4, quality_threshold=7.5)
    argv = RaconAdapter.argv("racon", p, Path("/j/in/01_reads.fastq.gz"), Path("/j/round1.paf"), Path("/j/round0.fasta"),
                             supported)
    assert argv == ["racon", "-m", "3", "-x", "-5", "-g", "-4", "-w", "500", "-q", "7.5", "-e", "0.3", "-t", "4", "-u",
                    "/j/in/01_reads.fastq.gz", "/j/round1.paf", "/j/round0.fasta"]
    with pytest.raises(ValueError, match="unsafe or unrecognised read file name"):
        RaconAdapter.argv("racon", p, Path("/j/in/reads; rm.fq"), Path("/j/r.paf"), Path("/j/r.fasta"), supported)
    with pytest.raises(ValueError, match="does not offer -u"):
        RaconAdapter.argv("racon", p, Path("/j/a.fastq"), Path("/j/r.paf"), Path("/j/r.fasta"), supported - {"-u"})


def test_racon_headers_and_failures():
    headers = [h[1:] for h in (F / "racon_round1.headers.txt").read_text().splitlines()]
    assert RaconAdapter.parse_headers(headers) == {
        "contig_1": {"length": 99974, "reads": 441, "windows_polished": 1.0},
        "contig_2": {"length": 7977, "reads": 74, "windows_polished": 1.0}}
    assert RaconAdapter.parse_headers(["contig_9"]) == {"contig_9": {"length": None, "reads": None,
                                                                     "windows_polished": None}}
    reason = RaconAdapter.failure_reason((F / "racon_empty_overlaps.stderr.log").read_text(), 1)
    assert reason.startswith("Racon found no overlaps")
    assert "out of memory" in RaconAdapter.failure_reason("", -9)
    assert RaconAdapter.failure_reason("something else", 1) is None


@pytest.mark.parametrize("values, message", [
    ({"rounds": 0}, "rounds"),
    ({"fix": []}, "fix must list"),
    ({"fix": ["snps", "amb"]}, "fix must list"),
    ({"fix": ["snps", "snps"]}, "fix must list"),
    ({"mindepth": 0}, "mindepth"),
    ({"minmq": 61}, "minmq"),
    ({"minqual": -1}, "minqual"),
    ({"heap_gb": 0}, "heap_gb"),
    ({"stop_when_unchanged": "yes"}, "stop_when_unchanged"),
])
def test_pilon_parameters_are_validated(values, message):
    with pytest.raises(ValueError, match=message):
        PilonParams.from_dict(values).validate()


def test_pilon_argv_sets_heap_fix_list_and_every_heuristic_explicitly():
    supported = opts("pilon_help_1.24.txt")
    p = PilonParams(fix=["indels", "snps"], mindepth=0.25, heap_gb=6)
    argv = PilonAdapter.argv("/usr/bin/java", "/usr/share/java/pilon.jar", p, Path("/j/round0.fasta"), Path("/j/out"),
                             "round1", supported, frags=Path("/j/pe.bam"), unpaired=Path("/j/se.bam"))
    assert argv[:6] == ["/usr/bin/java", "-Xmx6g", "-jar", "/usr/share/java/pilon.jar", "--genome", "/j/round0.fasta"]
    assert argv[6:20] == ["--frags", "/j/pe.bam", "--unpaired", "/j/se.bam", "--output", "round1", "--outdir", "/j/out",
                          "--changes", "--fix", "snps,indels", "--mindepth", "0.25", "--minmq"]
    for flag, value in FIXED_OPTIONS:
        assert argv[argv.index(flag) + 1] == value
    assert PilonParams().fix_list() == "snps,indels,gaps,local"
    with pytest.raises(ValueError, match="paired-end"):
        PilonAdapter.argv("java", "p.jar", p, Path("/j/a.fasta"), Path("/j"), "r1", supported)
    with pytest.raises(ValueError, match="unsafe"):
        PilonAdapter.argv("java", "p.jar", p, Path("/j/a.fasta"), Path("/j"), "r1;x", supported, frags=Path("/j/a.bam"))


def test_pilon_changes_log_and_failures():
    changes = PilonAdapter.parse_changes((F / "pilon_round1.changes").read_text())
    assert changes["changes"] == 16
    assert changes["totals"]["snp"] == {"events": 7, "bases": 7}
    assert changes["totals"]["insertion"] == {"events": 5, "bases": 7}
    assert changes["totals"]["deletion"] == {"events": 4, "bases": 5}
    assert changes["by_contig"]["contig_2"]["snp"] == 1
    other = PilonAdapter.parse_changes("c:10-12 c_pilon:10-11 ACG TT\nc:20-21 c_pilon:19-20 AC GT\n")
    assert other["totals"]["replacement"] == {"events": 1, "bases": 3}
    assert other["totals"]["substitution"] == {"events": 1, "bases": 2}
    assert PilonAdapter.parse_changes("")["changes"] == 0
    with pytest.raises(ValueError, match="line 1"):
        PilonAdapter.parse_changes("contig_1 5 A T\n")

    log = PilonAdapter.parse_log((F / "pilon_round1.log").read_text())
    assert log["finished"] and log["mean_coverage"] == {"frags": 37, "total": 37}
    assert log["totals"] == {"confirmed_bases": 107971, "bases": 107998, "snps": 7, "insertions": 5, "inserted_bases": 7,
                             "deletions": 4, "deleted_bases": 5}
    oom = (F / "pilon_oom.log").read_text()
    assert PilonAdapter.parse_log(oom)["finished"] is False
    assert PilonAdapter.failure_reason(oom, 1, 2).startswith("Pilon ran out of Java heap memory (-Xmx2g)")


def test_pilon_version_and_jar_discovery(tmp_path, monkeypatch):
    assert upstream_version("1.24-3") == "1.24" and upstream_version("1:3.23+dfsg-8") == "3.23"
    jar = tmp_path / "share" / "pilon.jar"
    jar.parent.mkdir()
    jar.write_bytes(b"PK")
    launcher = tmp_path / "bin" / "pilon"
    launcher.parent.mkdir()
    launcher.write_text(f"#! /bin/sh\nrun_java -Xms128M -Xmx16384m -jar {jar} \"$@\"\n")
    launcher.chmod(0o755)
    monkeypatch.delenv("ARVA_TOOL_PILON", raising=False)
    monkeypatch.setenv("ARVA_TOOLS_PATH", str(launcher.parent))
    assert locate_jar() == (str(jar), str(launcher))
    launcher.write_text("#!/usr/bin/env python3\nimport pilon\n")
    assert locate_jar() == (None, str(launcher))
    monkeypatch.setenv("ARVA_TOOL_PILON", str(jar))
    assert locate_jar() == (str(jar), None)
    monkeypatch.setenv("ARVA_TOOL_PILON", str(tmp_path / "missing.jar"))
    assert locate_jar() == (None, None)


def test_mapper_argv():
    assert Minimap2Adapter.argv("minimap2", "map-hifi", 3, Path("/j/t.fasta"), Path("/j/r.fq.gz"), Path("/j/o.paf")) == [
        "minimap2", "-x", "map-hifi", "-t", "3", "-o", "/j/o.paf", "/j/t.fasta", "/j/r.fq.gz"]
    assert Minimap2Adapter.argv("m", "map-ont", 1, Path("t"), Path("r"), None, sam=True) == [
        "m", "-a", "-x", "map-ont", "-t", "1", "t", "r"]
    with pytest.raises(ValueError, match="preset"):
        Minimap2Adapter.argv("m", "sr", 1, Path("t"), Path("r"), Path("o"))
    assert BwaAdapter.index_argv("bwa", Path("/j/r0.fasta"), Path("/j/r0")) == ["bwa", "index", "-p", "/j/r0", "/j/r0.fasta"]
    assert BwaAdapter.mem_argv("bwa", Path("/j/r0"), [Path("/j/1.fq"), Path("/j/2.fq")], 4) == [
        "bwa", "mem", "-t", "4", "-K", "100000000", "/j/r0", "/j/1.fq", "/j/2.fq"]
    assert SamtoolsAdapter.sort_argv("samtools", Path("a.sam.gz"), Path("a.bam"), 1, Path("tmp/a")) == [
        "samtools", "sort", "-@", "0", "-T", "tmp/a", "-o", "a.bam", "a.sam.gz"]
    assert SamtoolsAdapter.depth_argv("samtools", Path("a.bam")) == [
        "samtools", "depth", "-aa", "-Q", "0", "-q", "0", "-l", "0", "-G", "UNMAP,SECONDARY,QCFAIL,DUP", "a.bam"]


def test_samtools_stats_and_coverage():
    pe = SamtoolsAdapter.parse_stats((F / "illumina_pe.samtools_stats.txt").read_text())
    assert (pe["reads"], pe["reads_mapped"], pe["reads_properly_paired"], pe["nm_sum"]) == (30934, 30934, 30788, 24239)
    assert pe["error_rate"] == pytest.approx(0.005224773)
    assert pe["edit_distance_per_100_bases"] == pytest.approx(100 * 24239 / 4639245)
    assert (pe["insertion_events"], pe["deletion_events"]) == (221, 137)
    assert pe["properly_paired_percent"] == pytest.approx(100 * 30788 / 30934)
    ont = SamtoolsAdapter.parse_stats((F / "ont.samtools_stats.txt").read_text())
    assert ont["mapped_percent"] == 100.0 and ont["properly_paired_percent"] is None
    assert ont["indel_events_per_100kb"] == pytest.approx(1e5 * (31847 + 44411) / 3469534)
    with pytest.raises(ValueError, match="did not report"):
        SamtoolsAdapter.parse_stats("SN\treads mapped:\t1\n")
    rows = SamtoolsAdapter.parse_coverage((F / "ont.samtools_coverage.tsv").read_text())
    assert [(r["contig"], r["length"], r["mean_depth"]) for r in rows] == [("contig_1", 99999, 29.9472),
                                                                          ("contig_2", 7999, 55.3399)]


def test_dnadiff_known_edits_are_counted_as_events():
    """fixtures/polishing/known_edits.*: reference → scripts/make_polishing_draft.py-style draft with 7 substitutions,
    4 insertions (A, G, TT, C: 5 bases) and 5 deletions (1, 1, 3, 1 and 1 bases: 7 bases)."""
    snps = DnadiffAdapter.parse_snps((F / "known_edits.snps").read_text())
    assert {k: v for k, v in snps.items() if k != "by_contig"} == {
        "substitutions": 7, "insertions": 4, "inserted_bases": 5, "deletions": 5, "deleted_bases": 7}
    report = DnadiffAdapter.parse_report((F / "known_edits.report").read_text())
    assert report["reference"]["substituted_bases"] == 7 and report["reference"]["indel_bases"] == 12
    assert report["reference"]["bases"] == 108000 and report["query"]["bases"] == 107998
    assert report["reference"]["one_to_one_identity"] == 99.98


def test_dnadiff_racon_round_shows_end_trimming_and_pilon_round_agrees_with_its_change_log():
    coords = {c["contig"]: c for c in DnadiffAdapter.parse_coords((F / "racon_round1.1coords").read_text())}
    assert (coords["contig_1"]["unaligned_start"], coords["contig_1"]["unaligned_end"]) == (8, 17)
    assert (coords["contig_2"]["unaligned_start"], coords["contig_2"]["unaligned_end"]) == (12, 10)
    report = DnadiffAdapter.parse_report((F / "racon_round1.report").read_text())
    assert report["reference"]["unaligned_bases"] == 47 and report["reference"]["breakpoints"] == 4
    pilon = DnadiffAdapter.parse_snps((F / "pilon_round1.snps").read_text())
    changes = PilonAdapter.parse_changes((F / "pilon_round1.changes").read_text())["totals"]
    assert (pilon["substitutions"], pilon["insertions"], pilon["inserted_bases"], pilon["deletions"],
            pilon["deleted_bases"]) == (changes["snp"]["events"], changes["insertion"]["events"],
                                        changes["insertion"]["bases"], changes["deletion"]["events"],
                                        changes["deletion"]["bases"])
    with pytest.raises(ValueError, match="12 tab-separated"):
        DnadiffAdapter.parse_snps("1\tA\tT\n")
    with pytest.raises(ValueError, match="lacks"):
        DnadiffAdapter.parse_report("[Bases]\nTotalBases 1 1\n")


def test_dnadiff_argv_refuses_names_the_shell_would_interpret():
    assert DnadiffAdapter.argv("dnadiff", "round1", "round0.fasta", "round1.fasta") == [
        "dnadiff", "-p", "round1", "round0.fasta", "round1.fasta"]
    for bad in ("a b.fasta", "x;rm.fasta", "../a.fasta", "/abs.fasta", "$(x).fasta"):
        with pytest.raises(ValueError, match="unsafe name"):
            DnadiffAdapter.argv("dnadiff", "out", bad, "b.fasta")


def test_java_option_variables_do_not_reach_tools(monkeypatch):
    from arva_tools.runner import tool_environment

    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        monkeypatch.setenv(name, "-Xmx1m")
    env = tool_environment()
    assert not {"JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"} & set(env) and "PATH" in env
    assert os.environ["JAVA_TOOL_OPTIONS"] == "-Xmx1m"
