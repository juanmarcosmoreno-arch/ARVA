"""Integration tests that run the real tools on the synthetic example reads.

Skipped automatically for any tool that is not installed.
"""
import gzip
import re
from pathlib import Path

import pytest

from arva_tools import ToolStatus, run_command
from arva_tools.fastp import FastpAdapter, FastpParams
from arva_tools.fastqc import FastqcAdapter
from arva_tools.filtlong import FiltlongAdapter, FiltlongParams
from arva_tools.registry import detect

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "synthetic"
R1 = EXAMPLES / "SYNTHETIC_illumina_R1_001.fastq.gz"
R2 = EXAMPLES / "SYNTHETIC_illumina_R2_001.fastq.gz"
ONT = EXAMPLES / "SYNTHETIC_nanopore_reads.fastq.gz"


def tool(tool_id):
    d = detect(tool_id, refresh=True)
    if d.status is not ToolStatus.available:
        pytest.skip(f"{tool_id} not available: {d.message}")
    return d.path


def count_fastq(path: Path) -> int:
    with gzip.open(path, "rt") as fh:
        return sum(1 for _ in fh) // 4


def test_seqkit_stats(tmp_path):
    from arva_tools.seqkit import SeqkitAdapter

    exe = tool("seqkit")
    out = tmp_path / "stats.tsv"
    run_command(SeqkitAdapter.stats_argv(exe, [R1, ONT]), cwd=tmp_path, stderr_path=tmp_path / "e.log",
                stdout_path=out)
    rows = {Path(r["file"]).name: r for r in SeqkitAdapter.parse_stats(out.read_text())}
    assert rows[R1.name]["num_seqs"] == 2000 and rows[R1.name]["sum_len"] == 300000
    assert rows[ONT.name]["num_seqs"] == 400


def test_fastp_paired_end_filters_and_trims(tmp_path):
    exe = tool("fastp")
    argv = FastpAdapter.argv(exe, FastpParams(threads=2), R1, tmp_path / "o1.fq.gz", tmp_path / "f.json",
                             tmp_path / "f.html", in2=R2, out2=tmp_path / "o2.fq.gz")
    run_command(argv, cwd=tmp_path, stderr_path=tmp_path / "fastp.log")
    report = FastpAdapter.parse_report(tmp_path / "f.json")
    before, after = report["before_filtering"]["total_reads"], report["after_filtering"]["total_reads"]
    assert before == 4000 and after < before
    assert report["filtering_result"]["low_quality_reads"] > 0
    assert report["adapter_trimmed_reads"] > 0
    assert count_fastq(tmp_path / "o1.fq.gz") * 2 == after
    assert (tmp_path / "f.html").stat().st_size > 1000
    data = FastpAdapter.parse_data(tmp_path / "f.json")
    assert {stage: v["total_cycles"] for stage, v in data["reads"]["read2"].items()} == {"before": 150, "after": 150}
    assert data["adapter_cutting"]["adapter_trimmed_reads"] == report["adapter_trimmed_reads"]
    ins = data["insert_size"]
    assert len(ins["histogram"]) == 512 and ins["evaluated_pairs"] <= 2000
    assert sum(ins["histogram_percent"]) + ins["unknown_percent"] == pytest.approx(100)


def _fastp(tmp_path, name, params, paired=False):
    exe = tool("fastp")
    out = tmp_path / name
    out.mkdir()
    pe = dict(in2=R2, out2=out / "o2.fq.gz") if paired else {}
    run_command(FastpAdapter.argv(exe, params, R1, out / "o1.fq.gz", out / "f.json", out / "f.html", **pe),
                cwd=out, stderr_path=out / "fastp.log")
    return out, FastpAdapter.parse_report(out / "f.json")


def read_lengths(path: Path) -> list[int]:
    with gzip.open(path, "rt") as fh:
        return [len(seq) for seq in fh.read().splitlines()[1::4]]


def test_fastp_length_limit_discards_and_max_len_trims(tmp_path):
    # Paired end: pairs where either mate is still longer than 120 bp after adapter trimming are discarded.
    out, report = _fastp(tmp_path, "limit", FastpParams(threads=2, length_limit=120), paired=True)
    kept = report["after_filtering"]["total_reads"]
    assert 0 < kept < report["before_filtering"]["total_reads"]
    assert report["filtering_result"]["too_long_reads"] > 0
    lengths = read_lengths(out / "o1.fq.gz") + read_lengths(out / "o2.fq.gz")
    assert len(lengths) == kept and max(lengths) <= 120
    # Single end: --max_len1 trims every read to 140 bp and discards none for its length.
    out, report = _fastp(tmp_path, "trim", FastpParams(threads=2, max_len1=140, trim_front1=2))
    assert report["filtering_result"]["too_long_reads"] == 0
    assert set(read_lengths(out / "o1.fq.gz")) == {140}
    assert report["after_filtering"]["total_reads"] == 2000 - report["filtering_result"]["low_quality_reads"]


def test_fastp_writes_an_empty_output_when_every_read_is_removed(tmp_path):
    out, report = _fastp(tmp_path, "none", FastpParams(threads=2, length_limit=140))
    assert report["after_filtering"]["total_reads"] == 0 and report["filtering_result"]["too_long_reads"] > 0
    # fastp exits with status 0 and leaves a 0-byte file: no gzip header, no reads.
    assert (out / "o1.fq.gz").stat().st_size == 0 and count_fastq(out / "o1.fq.gz") == 0


def test_fastp_low_complexity_count_only_when_enabled(tmp_path):
    _, off = _fastp(tmp_path, "off", FastpParams(threads=2))
    _, on = _fastp(tmp_path, "on", FastpParams(threads=2, low_complexity_filter=True, complexity_threshold=30))
    assert "low_complexity_reads" not in off["filtering_result"]
    assert on["filtering_result"]["low_complexity_reads"] == 0


def test_fastp_explicit_adapter_for_single_end(tmp_path):
    # fastp's single-end auto-detection finds no adapter in R1, although FastQC sees the Illumina adapter.
    _, auto = _fastp(tmp_path, "auto", FastpParams(threads=2))
    _, given = _fastp(tmp_path, "given", FastpParams(threads=2, adapter_sequence="AGATCGGAAGAGCACACGTCTGAACTCCAGTCA"))
    assert auto["adapter_trimmed_reads"] is None
    assert given["adapter_trimmed_reads"] > 100 and given["read1_adapter_sequence"].startswith("AGATCGGAAGAGC")


def test_filtlong_target_outcomes(tmp_path):
    from arva_tools.filtlong import ENVIRONMENT

    exe = tool("filtlong")
    outcomes = {}
    for name, params in {
        "kept": FiltlongParams(target_bases=500_000),
        "not_enough": FiltlongParams(target_bases=1_513_780),
        "below": FiltlongParams(min_length=5000, target_bases=1_000_000),
    }.items():
        run_command(FiltlongAdapter.argv(exe, params, ONT), cwd=tmp_path, stderr_path=tmp_path / f"{name}.log",
                    stdout_path=tmp_path / f"{name}.fq.gz", extra_env=ENVIRONMENT)
        outcomes[name] = FiltlongAdapter.parse_log((tmp_path / f"{name}.log").read_text())
    assert outcomes["kept"]["kept_bases_reported"] == sum(read_lengths(tmp_path / "kept.fq.gz"))
    assert 500_000 <= outcomes["kept"]["kept_bases_reported"] < 500_000 + max(read_lengths(ONT))
    assert outcomes["not_enough"]["not_enough_reads_for_target"] and count_fastq(tmp_path / "not_enough.fq.gz") == 400
    assert outcomes["below"]["below_target_after_filtering"] and "kept_bases_reported" not in outcomes["below"]
    assert min(read_lengths(tmp_path / "below.fq.gz")) >= 5000


def test_filtlong_keeps_subset(tmp_path):
    exe = tool("filtlong")
    out = tmp_path / "filtered.fastq.gz"
    run_command(FiltlongAdapter.argv(exe, FiltlongParams(min_length=1000, min_mean_q=90), ONT),
                cwd=tmp_path, stderr_path=tmp_path / "filtlong.log", stdout_path=out)
    kept = count_fastq(out)
    assert 0 < kept < 400
    with gzip.open(out, "rt") as fh:
        lines = fh.read().splitlines()
    assert all(len(seq) >= 1000 for seq in lines[1::4])
    assert FiltlongAdapter.parse_log((tmp_path / "filtlong.log").read_text())["input_reads"] == 400


def test_filtlong_runs_in_the_c_locale(tmp_path):
    from arva_tools.filtlong import ENVIRONMENT

    exe = tool("filtlong")
    # A locale that is not installed makes Filtlong 0.2.1 abort; LC_ALL=C overrides it (and any digit grouping).
    run_command(FiltlongAdapter.argv(exe, FiltlongParams(keep_percent=90), ONT), cwd=tmp_path,
                stderr_path=tmp_path / "filtlong.log", stdout_path=tmp_path / "kept.fq.gz",
                extra_env={"LANG": "xx_XX.UTF-8", **ENVIRONMENT})
    log = (tmp_path / "filtlong.log").read_text()
    assert "target: " in log and "," not in log and count_fastq(tmp_path / "kept.fq.gz") > 0


def test_fastqc_report(tmp_path):
    exe = tool("fastqc")
    (tmp_path / "tmp").mkdir()
    run_command(FastqcAdapter.argv(exe, R1, tmp_path, tmp_path / "tmp"), cwd=tmp_path,
                stderr_path=tmp_path / "fastqc.log")
    html, zipname = FastqcAdapter.output_names(R1.name)
    assert (tmp_path / html).exists()
    parsed = FastqcAdapter.parse_zip(tmp_path / zipname)
    assert parsed["basic_statistics"]["Total Sequences"] == "2000"
    assert {m["module"] for m in parsed["modules"]} >= {"Basic Statistics", "Adapter Content"}
    data = FastqcAdapter.read_data(tmp_path / zipname)
    assert data["unrecognised"] == [] and data["total_sequences"] == 2000
    ac = data["adapter_content"]
    assert ac["positions"][9] == {"label": "10-11", "start": 10, "end": 11}
    assert all(len(a["percent"]) == len(ac["positions"]) for a in ac["adapters"])
    assert len(data["duplication"]["bins"]) == 16
    assert data["overrepresented_sequences"]["rows"] == []


def test_fastqc_data_on_long_reads(tmp_path):
    exe = tool("fastqc")
    (tmp_path / "tmp").mkdir()
    run_command(FastqcAdapter.argv(exe, ONT, tmp_path, tmp_path / "tmp"), cwd=tmp_path,
                stderr_path=tmp_path / "fastqc.log")
    data = FastqcAdapter.read_data(tmp_path / FastqcAdapter.output_names(ONT.name)[1])
    assert data["max_read_length"] > 10_000 and data["adapter_content"]["positions"][9]["start"] == 10
    over = data["overrepresented_sequences"]
    assert over["every_read_listed"] and over["total"] == 400 and len(over["rows"]) == 20


def _multiqc_inputs(tmp_path):
    """Real FastQC, fastp, SeqKit and Filtlong outputs of the synthetic reads, staged like ARVA does."""
    from arva_tools.multiqc import ReportInput, report_text, staged_name
    from arva_tools.seqkit import SeqkitAdapter

    exes = {t: tool(t) for t in ("fastqc", "fastp", "seqkit", "filtlong")}
    raw = tmp_path / "raw"
    (raw / "tmp").mkdir(parents=True)
    run_command(FastqcAdapter.argv(exes["fastqc"], R1, raw, raw / "tmp"), cwd=raw, stderr_path=raw / "fastqc.log")
    run_command(FastpAdapter.argv(exes["fastp"], FastpParams(threads=2), R1, raw / "o1.fq.gz", raw / "fastp.json",
                                  raw / "fastp.html", in2=R2, out2=raw / "o2.fq.gz", title="ARVA fastp report - S1"),
                cwd=raw, stderr_path=raw / "fastp.log")
    run_command(SeqkitAdapter.stats_argv(exes["seqkit"], [ONT]), cwd=raw, stderr_path=raw / "s.log",
                stdout_path=raw / "seqkit_stats.tsv")
    run_command(FiltlongAdapter.argv(exes["filtlong"], FiltlongParams(keep_percent=90), ONT), cwd=raw,
                stderr_path=raw / "filtlong.log", stdout_path=raw / "kept.fq.gz")
    sources = [("fastqc", raw / FastqcAdapter.output_names(R1.name)[1], "S1 <b>R1</b>"),
               ("fastp", raw / "fastp.json", "S1 R1+R2"),
               ("seqkit", raw / "seqkit_stats.tsv", "S2 reads"),
               ("filtlong", raw / "filtlong.log", "S2 reads")]
    staged = tmp_path / "job" / "inputs"
    staged.mkdir(parents=True)
    inputs = []
    for n, (module, src, name) in enumerate(sources, 1):
        dst = staged / staged_name(n, module)
        dst.write_bytes(src.read_bytes())
        inputs.append(ReportInput(module, dst, report_text(name)))
    return raw, inputs


def _run_multiqc(exe, job, inputs, title="Synthetic <script>x</script>"):
    from arva_tools.multiqc import ENVIRONMENT, MultiqcAdapter

    modules = [m for m in ("fastqc", "fastp", "seqkit", "filtlong") if any(i.module == m for i in inputs)]
    (job / "inputs.txt").write_text("".join(f"{i.path}\n" for i in inputs))
    (job / "config.yaml").write_text(MultiqcAdapter.config(modules))
    (job / "names.tsv").write_text(MultiqcAdapter.replace_names(inputs))
    (job / "work").mkdir(exist_ok=True)
    argv = MultiqcAdapter.argv(exe, file_list=job / "inputs.txt", outdir=job, config=job / "config.yaml",
                               names=job / "names.tsv", title=title, comment="ARVA test", modules=modules)
    run_command(argv, cwd=job / "work", stderr_path=job / "multiqc.stderr.log", extra_env=ENVIRONMENT)


def test_multiqc_project_report(tmp_path):
    from arva_tools.multiqc import DATA_DIR, REPORT_FILENAME, SOURCES_FILE, MultiqcAdapter

    exe = tool("multiqc")
    raw, inputs = _multiqc_inputs(tmp_path)
    job = tmp_path / "job"
    _run_multiqc(exe, job, inputs)

    html = (job / REPORT_FILENAME).read_text()
    data_dir = job / DATA_DIR
    sources = MultiqcAdapter.parse_sources((data_dir / SOURCES_FILE).read_text())
    assert MultiqcAdapter.check_sources(inputs, sources) == []
    assert "<script>x</script>" not in html and "<b>R1</b>" not in html
    assert '<a class="module-doi' not in html and str(job) not in html and 'class="mqc_analysis_path' not in html
    debug_log = (data_dir / "multiqc.log").read_text()
    assert "no_version_check from the environment variable" in debug_log and "api.multiqc.info" not in debug_log

    parsed = MultiqcAdapter.parse_data(data_dir)
    assert parsed["multiqc_version"] == "1.35"
    rows = {r["name"]: r["values"] for r in parsed["general_stats"]["rows"]}
    # The raw values are the tools' own numbers, in the units ARVA records.
    fastp_json = FastpAdapter.parse_report(raw / "fastp.json")
    fastp = rows["S1 R1+R2"]["fastp"]
    assert fastp["filtering_result_passed_filter_reads"] == fastp_json["filtering_result"]["passed_filter_reads"]
    assert fastp["after_filtering_q30_rate"] == pytest.approx(fastp_json["after_filtering"]["q30_rate"])
    assert fastp["after_filtering_gc_content"] == pytest.approx(fastp_json["after_filtering"]["gc_content"])
    assert rows["S1 _b_R1__b_"]["fastqc"]["total_sequences"] == 2000
    assert rows["S2 reads"]["seqkit"]["num_seqs"] == 400
    filtlong_log = FiltlongAdapter.parse_log((raw / "filtlong.log").read_text())
    assert rows["S2 reads"]["filtlong"]["Target bases"] == filtlong_log["target_bases_reported"]
    assert rows["S2 reads"]["filtlong"]["Bases kept"] == filtlong_log["kept_bases_reported"]
    assert parsed["software_versions"]["fastp"] and parsed["software_versions"]["FastQC"]


def test_multiqc_failures_are_detected(tmp_path):
    from arva_tools import ToolExecutionError
    from arva_tools.multiqc import DATA_DIR, SOURCES_FILE, MultiqcAdapter, ReportInput

    exe = tool("multiqc")
    _, inputs = _multiqc_inputs(tmp_path)
    job = tmp_path / "job"
    # Two inputs under one name: MultiQC drops one silently (exit status 0).
    clash = [inputs[1], ReportInput("fastp", inputs[1].path.with_name("arva-0009.fastp.json"), inputs[1].name)]
    clash[1].path.write_bytes(inputs[1].path.read_bytes())
    _run_multiqc(exe, job, clash)
    sources = MultiqcAdapter.parse_sources((job / DATA_DIR / SOURCES_FILE).read_text())
    assert len(MultiqcAdapter.check_sources(clash, sources)) == 1

    # A Filtlong log without a target has no totals: --require-logs turns "nothing found" into an error.
    no_target = tmp_path / "job" / "inputs" / "arva-0010.filtlong.log"
    run_command(FiltlongAdapter.argv(tool("filtlong"), FiltlongParams(min_length=1000), ONT), cwd=tmp_path,
                stderr_path=no_target, stdout_path=tmp_path / "kept2.fq.gz")
    with pytest.raises(ToolExecutionError):
        _run_multiqc(exe, tmp_path / "job", [ReportInput("filtlong", no_target, "S3 reads")])


def test_multiqc_reads_grouped_filtlong_logs_only_after_plain_counts(tmp_path):
    from arva_tools import ToolExecutionError
    from arva_tools.filtlong import plain_counts
    from arva_tools.multiqc import DATA_DIR, MultiqcAdapter

    exe = tool("multiqc")
    _, inputs = _multiqc_inputs(tmp_path)
    (staged,) = [i for i in inputs if i.module == "filtlong"]
    plain = staged.path.read_text()
    # What Filtlong writes under en_US: MultiQC 1.35's filtlong module crashes on "1,362,402".
    grouped = re.sub(r"\d{4,}", lambda m: f"{int(m.group(0)):,}", plain)
    assert grouped != plain and plain_counts(grouped) == plain
    staged.path.write_text(grouped)
    with pytest.raises(ToolExecutionError):
        _run_multiqc(exe, tmp_path / "job", [staged])
    staged.path.write_text(plain_counts(grouped))
    _run_multiqc(exe, tmp_path / "job", [staged])
    rows = {r["name"]: r["values"] for r in MultiqcAdapter.parse_data(tmp_path / "job" / DATA_DIR)["general_stats"]["rows"]}
    expected = FiltlongAdapter.parse_log(grouped)
    assert rows[staged.name]["filtlong"] == {"Target bases": expected["target_bases_reported"],
                                             "Bases kept": expected["kept_bases_reported"]}


@pytest.fixture
def recording_proxy():
    """A local listener every proxy variable points at: any connection attempt is recorded and refused."""
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    seen: list[bytes] = []

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                seen.append(conn.recv(200))

    threading.Thread(target=serve, daemon=True).start()
    url = f"http://127.0.0.1:{server.getsockname()[1]}"
    env = {k: url for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")}
    yield {**env, "NO_PROXY": "", "no_proxy": ""}, seen
    server.close()


def _nanoplot(exe, src: Path, job: Path, env, prefix="SYNTHETIC_nanopore_reads_"):
    from arva_tools.nanoplot import NanoplotAdapter, input_name

    for d in ("input", "work", "home"):
        (job / d).mkdir(parents=True)
    link = job / "input" / input_name(prefix, src.suffix == ".gz")
    link.symlink_to(src)
    run_command(NanoplotAdapter.argv(exe, link, job, prefix, 2), cwd=job / "work", stderr_path=job / "stderr.log",
                extra_env=env, home=job / "home")


def test_nanoplot_report_offline(tmp_path, recording_proxy):
    from arva_tools.nanoplot import NanoplotAdapter, browser_traces, output_names

    exe = tool("nanoplot")
    env, attempts = recording_proxy
    _nanoplot(exe, ONT, tmp_path, env)
    names = output_names("SYNTHETIC_nanopore_reads_")
    assert attempts == [] and browser_traces(tmp_path / "home") == []
    assert list((tmp_path / "home").iterdir()) == [] and list((tmp_path / "work").iterdir()) == []
    (log,) = tmp_path.glob(names.log_glob)
    produced = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert produced == {names.report, names.stats, log.name, "stderr.log"}

    s = NanoplotAdapter.parse_stats((tmp_path / names.stats).read_text())
    # Same file, same counts as ARVA and SeqKit; mean_qual 10.2 also fails if a stock nanomath replaced
    # the copy NanoPlot ships (it then reports 9.8).
    assert (s["number_of_reads"], s["number_of_bases"], s["n50"]) == (400, 1513780, 4817)
    assert (s["mean_qual"], s["median_qual"]) == (10.2, 11.7)
    html = (tmp_path / names.report).read_text()
    assert "<script src" not in html.replace(" ", "") and html.count('class="plotly-graph-div"') == 7
    assert str(tmp_path) not in html and "plotly.js v" in html


def test_nanoplot_detection_rejects_a_replaced_nanomath(tmp_path, monkeypatch):
    from arva_tools.nanoplot import NanoplotAdapter

    tool("nanoplot")
    # A stock nanomath found first (here through PYTHONPATH, as after `pip install nanomath`) lacks
    # ave_qual_floats, and NanoPlot would then report a different mean quality under the same version.
    (tmp_path / "nanomath").mkdir()
    (tmp_path / "nanomath" / "__init__.py").write_text("def ave_qual(quals): return 0\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    d = NanoplotAdapter().detect()
    assert d.status is ToolStatus.failed and d.version == "1.48.0" and "ave_qual_floats" in d.message


def test_nanoplot_fails_when_no_reads_are_left(tmp_path, recording_proxy):
    from arva_tools import ToolExecutionError
    from arva_tools.nanoplot import output_names

    exe = tool("nanoplot")
    src = tmp_path / "artefacts.fastq"
    src.write_text("@a\nAC\n+\nII\n@b\nACG\n+\nIII\n@c\nACGTA\n+\nIIIII\n")
    job = tmp_path / "job"
    with pytest.raises(ToolExecutionError) as err:
        _nanoplot(exe, src, job, recording_proxy[0], prefix="a_")
    # NanoStats.txt is written before NanoPlot gives up, so its presence alone does not mean success.
    assert "No reads left after filtering" in err.value.stderr_tail
    assert (job / output_names("a_").stats).is_file() and not (job / output_names("a_").report).exists()
