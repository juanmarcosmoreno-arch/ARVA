"""SPAdes and Unicycler adapters: parameters, argument vectors and the parsers, on recorded real outputs."""
import gzip
from pathlib import Path

import pytest

from arva_tools.base import help_options
from arva_tools.spades import OUTPUTS as SPADES_OUTPUTS
from arva_tools.spades import SpadesAdapter, SpadesParams, parse_node_name
from arva_tools.unicycler import STAGES, UnicyclerAdapter, UnicyclerParams, modes_available

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SP = FIXTURES / "spades"
UNI = FIXTURES / "unicycler"
SPADES_HELP = help_options((SP / "help_3.15.5.txt").read_text())
UNICYCLER_HELP = help_options((UNI / "help_all_0.5.0.txt").read_text())
HELPERS = {"spades": "/usr/bin/spades.py", "racon": "/usr/bin/racon", "makeblastdb": "/usr/bin/makeblastdb",
           "tblastn": "/usr/bin/tblastn"}
R1, R2, SE, ONT = (Path(f"/job/input/{n}") for n in ("01_a_R1.fastq.gz", "02_a_R2.fastq.gz", "03_s.fastq",
                                                       "04_ont.fastq.gz"))


def test_help_lists_short_and_long_options():
    assert {"-1", "-2", "-s", "-o", "-t", "-m", "-k", "--isolate", "--careful", "--cov-cutoff", "--threads"} <= SPADES_HELP
    assert {"-1", "-2", "-s", "-l", "-o", "-t", "--mode", "--keep", "--kmers", "--spades_options",
            "--racon_path", "--makeblastdb_path", "--tblastn_path", "--min_fasta_length"} <= UNICYCLER_HELP
    assert "--no-such" not in SPADES_HELP and "--pilon_path" not in UNICYCLER_HELP


@pytest.mark.parametrize("values, message", [
    ({"mode": "meta"}, "mode must be one of isolate, careful, standard"),
    ({"output": "graph"}, "output must be one of contigs, scaffolds"),
    ({"k": [21, 32]}, "every k must be odd"),
    ({"k": [129]}, "between 1 and 127"),
    ({"k": [55, 33]}, "ascending and distinct"),
    ({"k": [33, 33]}, "ascending and distinct"),
    ({"k": []}, "non-empty list"),
    ({"cov_cutoff": "on"}, "'off', 'auto' or a positive number"),
    ({"cov_cutoff": 0}, "'off', 'auto' or a positive number"),
    ({"cov_cutoff": float("nan")}, "'off', 'auto' or a positive number"),
    ({"memory_gb": 0}, "memory_gb"),
    ({"threads": 0}, "threads"),
])
def test_spades_params_are_validated(values, message):
    with pytest.raises(ValueError, match=message):
        SpadesParams(**values).validate()


def test_spades_argv_paired_isolate_lets_spades_choose_k():
    argv = SpadesAdapter.argv("spades.py", SpadesParams(memory_gb=8, threads=4), Path("/job/spades"), SPADES_HELP,
                              r1=R1, r2=R2)
    assert argv == ["spades.py", "--isolate", "-1", str(R1), "-2", str(R2), "-o", "/job/spades", "-t", "4",
                    "-m", "8", "--cov-cutoff", "off"]


def test_spades_argv_single_end_careful_with_k_and_cutoff():
    params = SpadesParams(mode="careful", k=[21, 33, 55], cov_cutoff=5.0, memory_gb=4, threads=2, output="scaffolds")
    argv = SpadesAdapter.argv("spades.py", params, Path("/job/spades"), SPADES_HELP, r1=R1, r2=R2, unpaired=SE)
    assert argv == ["spades.py", "--careful", "-1", str(R1), "-2", str(R2), "-s", str(SE), "-o", "/job/spades",
                    "-t", "2", "-m", "4", "--cov-cutoff", "5", "-k", "21,33,55"]
    standard = SpadesAdapter.argv("spades.py", SpadesParams(mode="standard", cov_cutoff="auto"), Path("/job/o"),
                                  SPADES_HELP, unpaired=SE)
    assert standard == ["spades.py", "-s", str(SE), "-o", "/job/o", "-t", "1", "-m", "16", "--cov-cutoff", "auto"]
    assert SpadesAdapter.argv("spades.py", SpadesParams(cov_cutoff=2.5), Path("/o"), SPADES_HELP,
                              unpaired=SE)[-1] == "2.5"


@pytest.mark.parametrize("inputs, message", [
    ({"r1": R1}, "need both the R1"),
    ({}, "needs paired-end reads, unpaired reads or both"),
    ({"unpaired": Path("/job/in put/s.fastq")}, "white space"),
    ({"unpaired": Path("/job/input/s[1].fastq")}, "white space or the characters"),
    ({"unpaired": Path("/job/input/s.bam")}, "unrecognised read file name"),
])
def test_spades_argv_refuses_bad_inputs(inputs, message):
    with pytest.raises(ValueError, match=message):
        SpadesAdapter.argv("spades.py", SpadesParams(), Path("/job/spades"), SPADES_HELP, **inputs)


def test_spades_argv_refuses_options_missing_from_help():
    with pytest.raises(ValueError, match="does not offer --isolate"):
        SpadesAdapter.argv("spades.py", SpadesParams(), Path("/o"), SPADES_HELP - {"--isolate"}, unpaired=SE)


def test_spades_stages_follow_its_plan():
    log = gzip.open(SP / "isolate_paired.spades.log.gz", "rt").read()
    plan = SpadesAdapter.planned_stages((SP / "isolate_paired.run_spades.yaml").read_text())
    assert plan == ("Before start", "Assembling", "K21", "K33", "K55", "K77", "Copy files", "Breaking scaffolds",
                    "Terminate")
    seen = [s for line in log.splitlines() if (s := SpadesAdapter.stage(line))]
    assert tuple(seen) == plan
    careful = SpadesAdapter.planned_stages((SP / "careful_paired.run_spades.yaml").read_text())
    lines = (SP / "careful_paired.stage_lines.txt").read_text().splitlines()
    stages = tuple(s for line in lines if (s := SpadesAdapter.stage(line)))
    assert stages == careful
    assert careful.count("Read error correction") == 2 and "Mismatch correction scaffolds" in careful
    assert SpadesAdapter.planned_stages("not yaml") is None


def test_spades_log_records_the_k_values_it_used():
    auto = SpadesAdapter.parse_log(gzip.open(SP / "isolate_paired.spades.log.gz", "rt").read())
    assert auto["k_values"] == [21, 33, 55, 77] and auto["finished"]
    assert auto["k_messages"] == ["Default k-mer sizes were set to [21, 33, 55, 77] because estimated read length "
                                  "(150) is equal to or greater than 150"]
    assert auto["mode_line"] == "ONLY assembling (without read error correction)"
    given = SpadesAdapter.parse_log(gzip.open(SP / "isolate_single_k.spades.log.gz", "rt").read())
    assert given["k_values"] == [21, 33, 55] and given["k_messages"] == []


def test_spades_contig_names_carry_kmer_coverage():
    names = [line[1:] for line in (SP / "isolate_paired.contigs_headers.txt").read_text().splitlines()]
    parsed = [parse_node_name(n) for n in names]
    assert parsed[0] == {"node": 1, "length": 98152, "kmer_coverage": 13.419342}
    assert parsed[1] == {"node": 2, "length": 8077, "kmer_coverage": 26.792}
    assert parse_node_name("contig_1") is None and parse_node_name("NODE_1_length_x_cov_1") is None
    assert parse_node_name("NODE_3_length_10_cov_1e-05") == {"node": 3, "length": 10, "kmer_coverage": 1e-05}
    assert "contigs.fasta" in SPADES_OUTPUTS and "assembly_graph_with_scaffolds.gfa" in SPADES_OUTPUTS


def test_spades_failure_reasons():
    memory = SpadesAdapter.failure_reason((SP / "memory_limit.spades.log").read_text(), 12, 1)
    assert memory.startswith("SPAdes ran out of memory (memory limit -m 1 GB): mmap(2) failed. Reason: Cannot allocate")
    staged = "===== K33 started. \n" + (SP / "memory_limit.spades.log").read_text()
    assert "during the K33 stage" in SpadesAdapter.failure_reason(staged, 12, 1)
    assert "stopped by the operating system during the K55 stage" in SpadesAdapter.failure_reason(
        "===== K55 started. \n", -9, 8)
    assert SpadesAdapter.failure_reason("== Error ==  file with reads has unsupported format (only .fq): x.bam\n",
                                        1).startswith("SPAdes did not accept a read file")
    crash = ('===== K21 started. \n== Error ==  system call for: "[\'/usr/libexec/spades/spades-core\', \'c\']" '
             "finished abnormally, OS return value: -11\n")
    assert SpadesAdapter.failure_reason(crash, 255) == ("SPAdes failed during the K21 stage: spades-core stopped "
                                                         "with status -11")
    assert SpadesAdapter.failure_reason("all fine\n", 1) is None


@pytest.mark.parametrize("values, message", [
    ({"assembly_mode": "meta"}, "assembly_mode must be one of"),
    ({"assembly_mode": "short", "mode": "wild"}, "mode must be one of conservative, normal, bold"),
    ({"assembly_mode": "short", "keep": 3}, "keep must be 0"),
    ({"assembly_mode": "short", "kmers": [9]}, "between 11 and 127"),
    ({"assembly_mode": "short", "kmers": [21, 22]}, "odd"),
    ({"assembly_mode": "short", "kmers": [51, 21]}, "ascending and distinct"),
    ({"assembly_mode": "long", "kmers": [21]}, "only apply to the SPAdes step"),
    ({"assembly_mode": "short", "depth_filter": 1.5}, "depth_filter"),
    ({"assembly_mode": "short", "min_fasta_length": 0}, "min_fasta_length"),
    ({"assembly_mode": "short", "linear_seqs": -1}, "linear_seqs"),
    ({"assembly_mode": "short", "spades_memory_gb": 0}, "spades_memory_gb"),
])
def test_unicycler_params_are_validated(values, message):
    with pytest.raises(ValueError, match=message):
        UnicyclerParams(**values).validate()


def test_unicycler_argv_for_each_mode():
    common = ["--verbosity", "1", "--min_fasta_length", "100", "--linear_seqs", "0"]
    blast = ["--makeblastdb_path", "/usr/bin/makeblastdb", "--tblastn_path", "/usr/bin/tblastn"]
    short = UnicyclerAdapter.argv("unicycler", UnicyclerParams("short", threads=4, spades_memory_gb=12), Path("/job/u"),
                                  UNICYCLER_HELP, HELPERS, r1=R1, r2=R2)
    assert short == ["unicycler", "-1", str(R1), "-2", str(R2), "-o", "/job/u", "-t", "4", "--mode", "normal",
                     "--keep", "1", *common, "--depth_filter", "0.25", "--spades_path", "/usr/bin/spades.py",
                     "--spades_options=-m 12", *blast]
    hybrid = UnicyclerAdapter.argv("unicycler", UnicyclerParams("hybrid", mode="bold", keep=0, kmers=[27, 53, 77]),
                                   Path("/job/u"), UNICYCLER_HELP, HELPERS, unpaired=SE, long=ONT)
    assert hybrid == ["unicycler", "-s", str(SE), "-l", str(ONT), "-o", "/job/u", "-t", "1", "--mode", "bold",
                      "--keep", "0", *common, "--depth_filter", "0.25", "--kmers", "27,53,77",
                      "--spades_path", "/usr/bin/spades.py", "--spades_options=-m 16", "--racon_path", "/usr/bin/racon",
                      *blast]
    long = UnicyclerAdapter.argv("unicycler", UnicyclerParams("long", mode="conservative"), Path("/job/u"),
                                 UNICYCLER_HELP, HELPERS, long=ONT)
    assert long == ["unicycler", "-l", str(ONT), "-o", "/job/u", "-t", "1", "--mode", "conservative", "--keep", "1",
                    *common, "--racon_path", "/usr/bin/racon", *blast]


@pytest.mark.parametrize("mode, inputs, helpers, help_text, message", [
    ("hybrid", {"r1": R1, "r2": R2}, HELPERS, UNICYCLER_HELP, "needs both short and long reads"),
    ("short", {"long": ONT}, HELPERS, UNICYCLER_HELP, "needs short reads and no long reads"),
    ("long", {"unpaired": SE, "long": ONT}, HELPERS, UNICYCLER_HELP, "needs long reads and no short reads"),
    ("short", {"r2": R2}, HELPERS, UNICYCLER_HELP, "need both the R1"),
    ("long", {"long": Path("/job/my reads.fastq")}, HELPERS, UNICYCLER_HELP, "white space"),
    ("hybrid", {"unpaired": SE, "long": ONT}, {**HELPERS, "racon": None}, UNICYCLER_HELP, "needs racon"),
    ("short", {"unpaired": SE}, {**HELPERS, "tblastn": None}, UNICYCLER_HELP, "needs tblastn"),
    ("short", {"unpaired": SE}, HELPERS, UNICYCLER_HELP - {"--spades_options"}, "does not offer --spades_options"),
])
def test_unicycler_argv_refusals(mode, inputs, helpers, help_text, message):
    with pytest.raises(ValueError, match=message):
        UnicyclerAdapter.argv("unicycler", UnicyclerParams(mode), Path("/job/u"), help_text, helpers, **inputs)


def test_unicycler_modes_follow_the_helpers_found():
    assert modes_available(HELPERS) == ["short", "long", "hybrid"]
    assert modes_available({**HELPERS, "racon": None}) == ["short"]
    assert modes_available({**HELPERS, "spades": None}) == ["long"]
    assert modes_available({**HELPERS, "makeblastdb": None}) == []


def test_unicycler_headers_and_graph_agree():
    short = UnicyclerAdapter.parse_headers([h[1:] for h in (UNI / "short.assembly_headers.txt").read_text().splitlines()])
    assert short == {"1": {"length": 57998, "depth": 1.0, "circular": False},
                     "2": {"length": 37998, "depth": 1.01, "circular": False},
                     "3": {"length": 8000, "depth": 2.05, "circular": True},
                     "4": {"length": 2002, "depth": 1.81, "circular": False}}
    graph = UnicyclerAdapter.parse_gfa_annotations((UNI / "short.assembly_noseq.gfa").read_text())
    assert {n: (g["length"], g["circular"], round(g["depth"], 2)) for n, g in graph.items()} == {
        n: (h["length"], h["circular"], h["depth"]) for n, h in short.items()}
    hybrid = UnicyclerAdapter.parse_headers([h[1:] for h in (UNI / "hybrid.assembly_headers.txt").read_text().splitlines()])
    assert hybrid == {"1": {"length": 100000, "depth": 1.0, "circular": True},
                      "2": {"length": 8000, "depth": 2.04, "circular": True}}
    with pytest.raises(ValueError, match="not a Unicycler contig header"):
        UnicyclerAdapter.parse_headers((UNI / "long.assembly_headers.txt").read_text().replace(">", "").splitlines())


def test_unicycler_long_read_only_annotations_come_from_the_graph():
    assert (UNI / "long.assembly_headers.txt").read_text().split() == [">1", ">2"]
    graph = UnicyclerAdapter.parse_gfa_annotations((UNI / "long.assembly_noseq.gfa").read_text())
    assert graph == {"1": {"length": 99996, "depth": 1.0, "circular": True},
                     "2": {"length": 8000, "depth": 1.8351368021958117, "circular": True}}
    hairpin = "S\t1\t*\tLN:i:10\tdp:f:1.0\nL\t1\t+\t1\t-\t0M\n"
    assert UnicyclerAdapter.parse_gfa_annotations(hairpin)["1"]["circular"] is False
    with pytest.raises(ValueError, match="no dp tag"):
        UnicyclerAdapter.parse_gfa_annotations("S\t1\t*\tLN:i:10\n")


@pytest.mark.parametrize("mode", ["short", "hybrid", "long"])
def test_unicycler_log(mode):
    summary = UnicyclerAdapter.parse_log((UNI / f"{mode}.unicycler.log").read_text())
    assert summary["version"] == "0.5.0" and tuple(summary["stages_seen"]) == STAGES[mode]
    assert UnicyclerParams(mode).stages() == STAGES[mode]
    used = {d["program"]: d for d in summary["dependencies"]}
    assert used["makeblastdb"]["version"] == "2.12.0+" and used["tblastn"]["status"] == "good"
    assert (used["spades"]["status"] == "not used") == (mode == "long")
    assert (used["racon"]["version"] == "1.5.0") == (mode != "short")
    if mode == "long":
        assert summary["kmer_range"] is None and summary["components"] == []
    else:
        assert summary["kmer_range"] == [27, 53, 71, 87, 99, 111, 119, 127] and summary["best_kmer"] == 27
    if mode == "hybrid":
        assert [(c["length"], c["status"]) for c in summary["components"]] == [(100000, "complete"), (8000, "complete")]
    assert "Choosing k-mer range for assembly" not in UnicyclerParams("short", kmers=[21]).stages()


def test_unicycler_stage_lines_with_colour():
    assert UnicyclerAdapter.stage("\x1b[1m\x1b[4mSPAdes assemblies\x1b[0m (2026-10-28 15:46:18)") == "SPAdes assemblies"
    assert UnicyclerAdapter.stage("Saving /job/u/assembly.gfa") is None


def test_unicycler_failure_reasons():
    reason = UnicyclerAdapter.failure_reason((UNI / "memory_limit.stderr.log").read_text(), 1,
                                             (UNI / "memory_limit.spades_assembly.spades.log").read_text(), 1)
    assert reason.startswith("Unicycler stopped because SPAdes failed: SPAdes ran out of memory (memory limit -m 1 GB)")
    console = (UNI / "memory_limit.unicycler.log").read_text()
    assert UnicyclerAdapter.failure_reason(console, 1) == "Unicycler failed during 'SPAdes assemblies': SPAdes " \
                                                          "encountered an error:"
    assert "out of memory" in UnicyclerAdapter.failure_reason("Loading reads (2026-10-28 15:48:10)\n", -9)
    assert UnicyclerAdapter.failure_reason("Error: the paired read input files have an unequal number of reads\n",
                                           1) == "Unicycler failed: the paired read input files have an unequal " \
                                                 "number of reads"
    assert UnicyclerAdapter.failure_reason("nothing\n", 1) is None
