"""Sanger identification on real BLAST+ outputs (fixtures/sanger/README.md): the public 16S read of Biopython's
3100.ab1 against NCBI's 16S database, MW2's seh against ABRicate's VFDB and VFDB's hlb split in two in MW2, read
with arva_core.sanger. The real runs need NCBI's 16S database at ARVA_TEST_16S_DB and ABRicate's environment, and
skip without them."""
import os
from pathlib import Path

import pytest
from arva_core import sanger

from arva_tools import blast
from arva_tools.blast import BlastAdapter, BlastParams, parse_tabular
from arva_tools.registry import detect
from arva_tools.runner import run_command

FX = Path(__file__).parent / "fixtures" / "sanger"
REGION = Path(__file__).parent / "fixtures" / "region"
DB16S = Path(os.environ.get("ARVA_TEST_16S_DB", "/root/.arva-testdata/ncbi-16s/2026-10-29/16S_ribosomal_RNA"))
VFDB = Path(os.environ.get("ARVA_TEST_VFDB", str(Path.home() / ".arva-tools/conda/abricate/db/vfdb/sequences")))
NCBI_16S = {"kind": "ncbi_16s", "name": "16S_ribosomal_RNA", "version": "2026-10-29"}
VFDB_SOURCE = {"kind": "abricate", "name": "vfdb", "version": "2026-Apr-3"}


def name_16s(h):
    p = sanger.parse_16s_title(h.get("stitle") or "")
    return {"species": p["species"], "genus": p["genus"], "strain": p["strain"],
            "accession": sanger.ncbi_accession(h["sseqid"])}


def name_vfdb(h):
    p = sanger.parse_abricate_id(h["sseqid"], h.get("stitle"))
    return {"gene": p["gene"], "product": p["product"], "accession": p["accession"]}


def rows_16s():
    return sanger.hits_from_hsps(parse_tabular((FX / "3100_trimmed_vs_16S_ribosomal_RNA.tsv").read_text(),
                                               titles=True), NCBI_16S, name_16s)


def test_title_column_in_the_usage_text_and_argv():
    assert " stitle means Subject Title" in (REGION / "blastn_help_2.12.0.txt").read_text()
    assert blast.OUTFMT_TITLES == blast.OUTFMT + " stitle"
    argv = BlastAdapter.search_argv("blastn", BlastParams(task="megablast"), "q.fna", "o.tsv", db="d", titles=True)
    assert argv[argv.index("-outfmt") + 1] == blast.OUTFMT_TITLES
    plain = BlastAdapter.search_argv("blastn", BlastParams(), "q.fna", "o.tsv", db="d")
    assert plain[plain.index("-outfmt") + 1] == blast.OUTFMT


def test_parse_rows_with_titles():
    hsps = parse_tabular((FX / "3100_trimmed_vs_16S_ribosomal_RNA.tsv").read_text(), titles=True)
    assert len(hsps) == 97 and hsps[0]["sseqid"] == "gi|310975040|ref|NR_036904.1|"
    assert hsps[0]["stitle"] == "Staphylococcus epidermidis strain Fussel 16S ribosomal RNA, partial sequence"
    assert hsps[0]["sstrand"] == "-" and (hsps[0]["s_lo"], hsps[0]["s_hi"]) == (662, 1340)
    line = "q\ts\t100\t10\t0\t0\t1\t10\t1\t10\t1e-5\t20\t10\t100\t10\tN/A\n"
    assert parse_tabular(line, titles=True)[0]["stitle"] is None
    tabbed = line.replace("N/A", "a\tb")
    assert parse_tabular(tabbed, titles=True)[0]["stitle"] == "a\tb"
    with pytest.raises(ValueError, match="16 columns instead of 15"):
        parse_tabular(line)
    with pytest.raises(ValueError, match="columns instead of 16"):
        parse_tabular("q\ts\t100\n", titles=True)


def test_3100_read_is_genus_staphylococcus():
    rows = rows_16s()
    assert len(rows) == 97 and all(r["kind"] == "complete" and r["copies"] == 1 for r in rows)
    best = sanger.rank_hits(rows)[0]
    # Identity is identical bases / aligned columns, unrounded (BLAST's pident 99.853 is 678/679).
    assert (best["accession"], best["species"], best["identity"], best["query_coverage"]) == (
        "NR_036904.1", "Staphylococcus epidermidis", 100 * 678 / 679, 100.0)
    r = sanger.interpret_16s(rows)
    assert r["level"] == "genus" and r["genus"] == "Staphylococcus" and r["species"] is None
    assert r["best"]["species"] == "Staphylococcus epidermidis" and r["best"]["strain"] == "Fussel"
    assert r["next_species"]["species"] in ("Staphylococcus saccharolyticus", "Staphylococcus caprae")
    assert r["separation"] == pytest.approx(100 / 679)
    assert [c["code"] for c in r["reasons"]] == ["species_not_separated"]
    assert [c["code"] for c in r["caveats"]] == ["criteria_quoted", "not_first_500", "staphylococcus_16s_limit",
                                                 "closest_type_strain"]
    assert {x["species"] for x in r["within_separation"]} >= {"Staphylococcus epidermidis",
                                                             "Staphylococcus saccharolyticus", "Staphylococcus caprae"}
    # Only rows with the CLSI query coverage count: S. argenteus NR_179740.1 (99.08 % over 95.73 % of the read) does not.
    above = {x["species"] for x in r["above_species_threshold"]}
    assert above == {x["species"] for x in rows if x["identity"] >= 99 and x["query_coverage"] >= 98}
    assert len(above) == 8 and "Staphylococcus argenteus" not in above
    assert all(x["genus"] in ("Staphylococcus", "Mammaliicoccus") for x in rows)


def test_3100_suspected_species():
    rows = rows_16s()
    epi = sanger.compare_suspected(rows, "Staphylococcus epidermidis", "species")
    assert epi["outcome"] == "ambiguous" and epi["best_suspected"]["identity"] == 100 * 678 / 679
    assert epi["tied_other_count"] >= 2 and epi["better_other_count"] == 0
    genus = sanger.compare_suspected(rows, "Staphylococcus", "species")
    assert genus["outcome"] == "match"
    mamm = sanger.compare_suspected(rows, "Mammaliicoccus", "species")
    assert mamm["outcome"] == "no_match" and mamm["better_other_count"] > 0
    assert mamm["better_other"][0]["species"] == "Staphylococcus epidermidis"
    assert sanger.compare_suspected(rows, "Escherichia coli", "species")["reasons"][0]["code"] == "not_found"


def test_seh_against_vfdb():
    rows = sanger.hits_from_hsps(parse_tabular((FX / "seh_vs_vfdb.tsv").read_text(), titles=True), VFDB_SOURCE,
                                 name_vfdb)
    ranked = sanger.rank_hits(rows)
    assert [(r["gene"], r["identity"], r["query_coverage"]) for r in ranked] == [
        ("seh", 100.0, 100.0), ("selk", 100 * 32 / 35, 100 * 35 / 726)]
    assert ranked[0]["product"] == "staphylococcal enterotoxin H precursor" and ranked[0]["subject_coverage"] == 100.0
    assert sanger.compare_suspected(rows, "seh", "gene")["outcome"] == "match"
    selk = sanger.compare_suspected(rows, "selk", "gene")
    assert selk["outcome"] == "no_match" and selk["better_other"][0]["gene"] == "seh"
    assert sanger.compare_suspected(rows, "sea", "gene")["outcome"] == "no_match"


def test_hlb_split_in_mw2():
    hsps = parse_tabular((FX / "vfdb_hlb_vs_mw2.tsv").read_text())
    (r,) = sanger.hits_from_hsps(hsps, {"kind": "assembly", "name": "MW2"})
    assert r["kind"] == "split" and r["query_coverage"] == 100.0 and len(r["pieces"]) == 2
    assert r["identity"] == 100 * (821 + 183) / (824 + 183)


# --- Real runs --------------------------------------------------------------------------------------------------

def tool(tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"{tool_id} is not available: {d.message}")
    return d.path


def test_real_blastn_3100_against_ncbi_16s(tmp_path):
    exe = tool("blast")
    if not DB16S.with_suffix(".nsq").is_file():
        pytest.skip(f"NCBI 16S database not at {DB16S} (fixtures/sanger/README.md)")
    p = BlastParams(task="megablast", evalue=1e-10, max_target_seqs=500, threads=2)
    run_command(BlastAdapter.search_argv(exe, p, str(FX / "3100_trimmed.fna"), "out.tsv", db=str(DB16S), titles=True),
                cwd=tmp_path, stderr_path=tmp_path / "blastn.log")
    got = [h for h in parse_tabular((tmp_path / "out.tsv").read_text(), titles=True) if h["pident"] >= 97]
    want = parse_tabular((FX / "3100_trimmed_vs_16S_ribosomal_RNA.tsv").read_text(), titles=True)
    assert [(h["sseqid"], h["pident"], h["stitle"]) for h in got] == [(h["sseqid"], h["pident"], h["stitle"])
                                                                       for h in want]


def test_real_blastn_seh_against_abricate_vfdb(tmp_path):
    exe = tool("blast")
    if not VFDB.with_suffix(".nsq").is_file():
        pytest.skip(f"ABRicate's VFDB not at {VFDB}")
    p = BlastParams(task="blastn", evalue=1e-5, threads=2)
    run_command(BlastAdapter.search_argv(exe, p, str(REGION / "seh_MW2_nucleotide.fna"), "out.tsv", db=str(VFDB),
                                         titles=True), cwd=tmp_path, stderr_path=tmp_path / "blastn.log")
    got = parse_tabular((tmp_path / "out.tsv").read_text(), titles=True)
    assert got == parse_tabular((FX / "seh_vs_vfdb.tsv").read_text(), titles=True)


def test_blastdbcmd_info_of_the_16s_database():
    """The real `blastdbcmd -db 16S_ribosomal_RNA -info` output of BLAST+ 2.12.0 on the 2026-10-29 build
    (fixtures/sanger/README.md)."""
    info = blast.parse_db_info((FX / "blastdbcmd_info_16S_2.12.0.txt").read_text())
    assert info == {"title": "16S ribosomal RNA (Bacteria and Archaea type strains)", "sequences": 27646,
                    "letters": 40048476, "date": "Oct 29, 2026 5:36 AM", "blastdb_version": 5}
    assert blast.info_argv("blastdbcmd", "/db/16S_ribosomal_RNA") == ["blastdbcmd", "-db", "/db/16S_ribosomal_RNA",
                                                                      "-info"]
    with pytest.raises(ValueError, match="title, size and version"):
        blast.parse_db_info("BLAST Database error: No alias or index file found\n")
    assert blast.BLASTDBCMD_VERSION.search("blastdbcmd: 2.12.0+\n Package: blast 2.12.0").group(1) == "2.12.0"
