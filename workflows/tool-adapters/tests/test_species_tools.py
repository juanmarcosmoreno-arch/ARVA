"""FastANI, skani, Mash, sylph and GTDB-Tk adapters: options checked against each tool's real --help, commands, and
parsers on real outputs (tests/fixtures/species/README.md: NCBI RefSeq genomes, ARVA's SYNTHETIC genome).

Real-tool runs skip when the tool is not installed. The synthetic-genome runs need no download (expectation: no
reference reported); the runs on NCBI genomes need ARVA_TEST_SPECIES_GENOMES, a folder holding the two extracted
NCBI Datasets packages of the README (staphylococcus/ and escherichia/), and skip without it.
"""
import os
import random
import shutil
from pathlib import Path

import pytest

from arva_tools import fastani, gtdbtk, mash, skani, sylph
from arva_tools.base import help_options
from arva_tools.fastani import FastaniAdapter, FastaniParams
from arva_tools.gtdbtk import GtdbtkAdapter, GtdbtkParams
from arva_tools.mash import MashAdapter, MashParams
from arva_tools.registry import detect
from arva_tools.runner import run_command
from arva_tools.skani import SkaniAdapter, SkaniParams
from arva_tools.sylph import SylphAdapter, SylphParams

FX = Path(__file__).parent / "fixtures" / "species"
SYNTHETIC = Path(__file__).resolve().parents[3] / "examples" / "synthetic-genome" / "reference.fasta"
GENOMES = os.environ.get("ARVA_TEST_SPECIES_GENOMES")
STAPH = "collection/staphylococcus/ncbi_dataset/data"


def text(name: str) -> str:
    return (FX / name).read_text()


def tool(tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"{tool_id} is not available: {d.message}")
    return d.path


# --- Options against the real --help --------------------------------------------------------------------------------

def test_fastani_options_and_defaults_from_its_help():
    opts = fastani.help_options(text("fastani_help_1.34.txt"))
    assert set(fastani.FLAGS) <= opts and "--refList" in opts and "--visualize" in opts
    assert fastani.help_defaults(text("fastani_help_1.34.txt")) == fastani.DEFAULTS
    argv = FastaniAdapter.argv("fastANI", FastaniParams(threads=4), Path("q.fna"), Path("refs.txt"), Path("out"),
                               opts)
    assert argv == ["fastANI", "-q", "q.fna", "--rl", "refs.txt", "-o", "out/fastani.tsv", "-t", "4", "-k", "16",
                    "--fragLen", "3000", "--minFraction", "0.2", "--maxRatioDiff", "10.0"]
    with pytest.raises(ValueError, match="kmer"):
        FastaniParams(kmer=17).validate()
    with pytest.raises(ValueError, match="does not offer --maxRatioDiff"):
        FastaniAdapter.argv("fastANI", FastaniParams(), Path("q"), Path("r"), Path("o"), opts - {"--maxRatioDiff"})


def test_skani_options_and_defaults_from_its_help():
    opts = help_options(text("skani_dist_help_0.4.0.txt"))
    assert set(skani.FLAGS) <= opts
    assert skani.help_defaults(text("skani_dist_help_0.4.0.txt")) == skani.DEFAULTS
    argv = SkaniAdapter.argv("skani", SkaniParams(threads=2), Path("q.fna"), Path("refs.txt"), Path("out"), opts)
    assert argv == ["skani", "dist", "-q", "q.fna", "--rl", "refs.txt", "-o", "out/skani.tsv", "-t", "2", "-c", "125",
                    "-m", "1000", "-s", "80", "--min-af", "15"]


def test_mash_sylph_and_gtdbtk_options_from_their_help():
    assert set(mash.FLAGS) <= help_options(text("mash_dist_help_2.3.txt"))
    assert {"-H", "-t"} <= help_options(text("mash_info_help_2.3.txt"))
    assert MashAdapter.argv("mash", MashParams(threads=3), Path("q.fna"), Path("db.msh"),
                            help_options(text("mash_dist_help_2.3.txt"))) == ["mash", "dist", "-p", "3", "db.msh",
                                                                               "q.fna"]
    opts = help_options(text("sylph_profile_help_1.0.0.txt"))
    assert set(sylph.FLAGS) <= opts
    argv = SylphAdapter.argv("sylph", SylphParams(threads=2), Path("q.fna"), Path("db.syldb"), Path("out"), opts)
    assert argv == ["sylph", "profile", "db.syldb", "-r", "q.fna", "-o", "out/sylph.tsv", "-t", "2", "-m", "95", "-M",
                    "10", "--min-contain", "7", "--min-count-correct", "3", "-c", "200", "-k", "31"]
    with pytest.raises(ValueError, match="95"):
        SylphParams(minimum_ani=90).validate()
    opts = help_options(text("gtdbtk_classify_wf_help_2.8.0.txt"))
    assert set(gtdbtk.FLAGS) <= opts and "--full_tree" in opts
    assert "--skip_ani_screen" not in opts and "--mash_db" not in opts
    argv = GtdbtkAdapter.argv("gtdbtk", GtdbtkParams(threads=8), Path("in"), Path("out"), Path("tmp"), opts)
    assert argv == ["gtdbtk", "classify_wf", "--genome_dir", "in", "--out_dir", "out", "--extension", "fna",
                    "--prefix", "gtdbtk", "--cpus", "8", "--pplacer_cpus", "1", "--min_af", "0.5", "--min_perc_aa",
                    "10", "--tmpdir", "tmp"]
    assert "(default: 0.5)" in text("gtdbtk_classify_wf_help_2.8.0.txt")
    assert GtdbtkAdapter.version_pattern.search(text("gtdbtk_version_2.8.0.txt")).group(1) == "2.8.0"
    assert gtdbtk.REQUIRED_MEMORY_GB == 140


# --- Parsers on real output -----------------------------------------------------------------------------------------

def test_fastani_real_outputs():
    rows = fastani.parse_output(text("fastani_saureus.tsv"))
    assert [(Path(r["reference"]).parent.name, r["ani"], r["fragments_mapped"], r["fragments_total"]) for r in rows] == [
        ("GCF_006094915.1", 99.9171, 900, 940), ("GCF_000236925.1", 88.85, 815, 940),
        ("GCF_006094375.1", 79.1388, 317, 940)]
    assert rows[0]["af"] == pytest.approx(900 / 940)
    eco = fastani.parse_output(text("fastani_ecoli_sakai.tsv"))
    assert [r["ani"] for r in eco] == [97.7623, 96.9917]
    assert fastani.parse_output(text("fastani_synthetic.tsv")) == []
    with pytest.raises(ValueError, match="columns"):
        fastani.parse_output("a\tb\t99\n")
    with pytest.raises(ValueError, match="range"):
        fastani.parse_output("q\tr\t99\t10\t5\n")


def test_skani_real_outputs():
    rows = skani.parse_output(text("skani_saureus.tsv"))
    assert [(Path(r["reference"]).parent.name, r["ani"]) for r in rows] == [("GCF_006094915.1", 99.87),
                                                                            ("GCF_000236925.1", 89.51)]
    assert (rows[0]["af_reference"], rows[0]["af_query"], rows[0]["af"]) == pytest.approx((0.9781, 0.9646, 0.9646))
    assert rows[1]["reference_name"] == "NC_016941.1 Staphylococcus argenteus, complete sequence"
    assert skani.parse_output(text("skani_synthetic.tsv")) == []
    assert skani.LEARNED in text("skani_saureus.log")
    with pytest.raises(ValueError, match="does not start"):
        skani.parse_output("Ref\tQuery\n")


def test_mash_real_outputs():
    header = mash.parse_info_header(text("mash_info_header_staph.txt"))
    assert header == {"hash_function": "MurmurHash3_x64_128", "seed": 42, "kmer": 21, "alphabet": "ACGT (canonical)",
                      "sketch_size": 1000, "sketches": 3}
    table = mash.parse_info_table(text("mash_info_staph.tsv"))
    assert table[f"{STAPH}/GCF_006094915.1/GCF_006094915.1_ASM609491v1_genomic.fna"]["organism"] == \
        "Staphylococcus aureus strain ATCC 12600 chromosome"
    rows = mash.parse_dist(text("mash_saureus.tsv"))
    best = min(rows, key=lambda r: r["distance"])
    assert (best["accession"], best["distance"], best["shared"], best["hashes"]) == ("GCF_006094915.1", 0.00173271,
                                                                                    931, 1000)
    assert {r["shared"] for r in mash.parse_dist(text("mash_synthetic.tsv"))} == {0}
    assert mash.organism_from_comment("[2 seqs] NC_016941.1 Staphylococcus argenteus, complete sequence [...]") == \
        "Staphylococcus argenteus"


def test_sylph_real_outputs():
    info = sylph.parse_inspect(text("sylph_inspect_staph.yaml"))
    assert (info["c"], info["k"], info["min_spacing_parameter"], len(info["genomes"])) == (200, 31, 30, 3)
    assert info["genomes"][0]["first_contig_name"] == "NC_016941.1 Staphylococcus argenteus, complete sequence"
    rows = sylph.parse_profile(text("sylph_saureus.tsv"))
    assert [(r["accession"], r["naive_ani"], r["adjusted_ani"], r["eff_lambda"]) for r in rows] == [
        ("GCF_006094915.1", 99.6, 99.6, "LOW"), ("GCF_000236925.1", 92.8, 100.0, "0.023")]
    assert rows[1]["af"] == pytest.approx(1158 / 11748)
    assert sylph.parse_profile(text("sylph_synthetic.tsv")) == []


def test_gtdbtk_summary_parser():
    header = "\t".join(gtdbtk.SUMMARY_COLUMNS)
    row = ["genome", "d__Bacteria;p__Bacillota;c__Bacilli;o__Staphylococcales;f__Staphylococcaceae;g__Staphylococcus;"
           "s__Staphylococcus aureus", "GCF_001027105.1", "95.0", "d__Bacteria;s__Staphylococcus aureus", "99.9",
           "0.97", "GCF_001027105.1", "95.0", "d__Bacteria", "99.9", "0.97", "d__Bacteria;s__", "ani_screen",
           "classification based on ANI only", "GCF_000236925.1, s__Staphylococcus argenteus, 95.0, 88.9, 0.62",
           "N/A", "11", "N/A", "N/A"]
    # A row in the column layout of gtdbtk/files/classify_summary.py (2.8.0), not a GTDB-Tk run.
    parsed = gtdbtk.parse_summary(header + "\n" + "\t".join(row) + "\n", "bacteria")[0]
    assert parsed["species"] == "Staphylococcus aureus" and parsed["closest_ani"] == 99.9
    assert parsed["related"] == [{"accession": "GCF_000236925.1", "species": "Staphylococcus argenteus",
                                  "radius": 95.0, "ani": 88.9, "af": 0.62}]
    assert parsed["msa_percent"] is None and parsed["warnings"] is None
    assert gtdbtk.species_of_classification("d__Bacteria;g__Staphylococcus;s__") is None
    with pytest.raises(ValueError, match="columns"):
        gtdbtk.parse_summary("user_genome\tclassification\n", "bacteria")


# --- Real tools -----------------------------------------------------------------------------------------------------

def _synthetic_other(path: Path) -> Path:
    rng = random.Random(7)
    path.write_text(">SYNTHETIC_other random sequence, not biological data\n" + "".join(
        rng.choice("ACGT") for _ in range(300_000)) + "\n")
    return path


def test_real_versions_and_help(tmp_path):
    for adapter, tool_id in ((FastaniAdapter, "fastani"), (SkaniAdapter, "skani"), (MashAdapter, "mash"),
                             (SylphAdapter, "sylph")):
        d = detect(tool_id, refresh=True)
        if d.path is None:
            continue
        assert d.version_validated, d.message
        flags = {"fastani": fastani.FLAGS, "skani": skani.FLAGS, "mash": mash.FLAGS, "sylph": sylph.FLAGS}[tool_id]
        assert set(flags) <= adapter.help_options(d.path)


def test_real_fastani_and_skani_on_synthetic_genomes(tmp_path):
    exe_f, exe_s = tool("fastani"), tool("skani")
    refs = tmp_path / "refs.txt"
    refs.write_text(f"{_synthetic_other(tmp_path / 'other.fna')}\n")
    out = tmp_path / "out"
    out.mkdir()
    run_command(FastaniAdapter.argv(exe_f, FastaniParams(threads=1), SYNTHETIC, refs, out,
                                    FastaniAdapter.help_options(exe_f)), cwd=out, stderr_path=out / fastani.LOG)
    assert fastani.parse_output((out / fastani.OUTPUT).read_text()) == []
    run_command(SkaniAdapter.argv(exe_s, SkaniParams(threads=1), SYNTHETIC, refs, out,
                                  SkaniAdapter.help_options(exe_s)), cwd=out, stderr_path=out / skani.LOG)
    assert skani.parse_output((out / skani.OUTPUT).read_text()) == []


@pytest.fixture
def genomes():
    if not GENOMES or not (Path(GENOMES) / "staphylococcus").is_dir():
        pytest.skip("ARVA_TEST_SPECIES_GENOMES (the NCBI packages of tests/fixtures/species/README.md) is not set")
    return Path(GENOMES)


def _refs(tmp_path: Path, root: Path, accessions: list[str]) -> Path:
    paths = [next((root / "staphylococcus" / "ncbi_dataset" / "data" / a).glob("*_genomic.fna")) for a in accessions]
    refs = tmp_path / "refs.txt"
    refs.write_text("".join(f"{p}\n" for p in paths))
    return refs


def test_real_tools_reproduce_the_fixtures(tmp_path, genomes):
    exe_f, exe_s = tool("fastani"), tool("skani")
    query = next((genomes / "staphylococcus" / "ncbi_dataset" / "data" / "GCF_000013425.1").glob("*_genomic.fna"))
    refs = _refs(tmp_path, genomes, ["GCF_006094915.1", "GCF_000236925.1", "GCF_006094375.1"])
    run_command(FastaniAdapter.argv(exe_f, FastaniParams(threads=2), query, refs, tmp_path,
                                    FastaniAdapter.help_options(exe_f)), cwd=tmp_path, stderr_path=tmp_path / "f.log")
    got = [(Path(r["reference"]).parent.name, r["ani"], r["fragments_mapped"])
           for r in fastani.parse_output((tmp_path / fastani.OUTPUT).read_text())]
    want = [(Path(r["reference"]).parent.name, r["ani"], r["fragments_mapped"])
            for r in fastani.parse_output(text("fastani_saureus.tsv"))]
    assert got == want
    run_command(SkaniAdapter.argv(exe_s, SkaniParams(threads=2), query, refs, tmp_path,
                                  SkaniAdapter.help_options(exe_s)), cwd=tmp_path, stderr_path=tmp_path / "s.log")
    got = [(Path(r["reference"]).parent.name, r["ani"]) for r in skani.parse_output((tmp_path / skani.OUTPUT).read_text())]
    assert got == [(Path(r["reference"]).parent.name, r["ani"]) for r in skani.parse_output(text("skani_saureus.tsv"))]
    exe_m = shutil.which("mash", path=str(Path(tool("mash")).parent))
    db = tmp_path / "staph"
    run_command([exe_m, "sketch", "-o", str(db), "-k", "21", "-s", "1000", "-S", "42", "-l", str(refs)], cwd=tmp_path,
                stderr_path=tmp_path / "m.log")
    run_command(MashAdapter.argv(exe_m, MashParams(threads=1), query, tmp_path / "staph.msh",
                                 MashAdapter.help_options(exe_m)), cwd=tmp_path, stderr_path=tmp_path / "m.log",
                stdout_path=tmp_path / mash.OUTPUT)
    best = min(mash.parse_dist((tmp_path / mash.OUTPUT).read_text()), key=lambda r: r["distance"])
    assert (best["accession"], best["shared"]) == ("GCF_006094915.1", 931)
