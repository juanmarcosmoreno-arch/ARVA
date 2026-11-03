"""Medaka: parameters, argument vector, model choice from medaka's own mapping, and parsers of real outputs
(fixtures/medaka/README.md)."""
import json
from pathlib import Path

import pytest

from arva_tools.base import help_options
from arva_tools.medaka import (
    FLAGS,
    MedakaAdapter,
    MedakaParams,
    _conda_records,
    help_choices,
    model_for_basecaller,
    offered_models,
)

F = Path(__file__).resolve().parent / "fixtures" / "medaka"
HELP = (F / "medaka_consensus_help_2.1.1.txt").read_text()
SUP = "r1041_e82_400bps_sup_v5.2.0"
HAC = "r1041_e82_400bps_hac_v5.2.0"
CATALOGUE = {
    "basecaller_models": {"dna_r10.4.1_e8.2_400bps_sup@v5.2.0": SUP, "dna_r10.4.1_e8.2_400bps_hac@v5.2.0": HAC,
                          "dna_r10.4.1_e8.2_400bps_sup@v4.3.0": "r1041_e82_400bps_sup_v4.3.0",
                          "dna_r9.4.1_e8_fast@v3.4": "r941_min_fast_g507"},
    "bundled_models": [{"name": HAC, "checksum": "matches_package"}, {"name": SUP, "checksum": "matches_package"},
                       {"name": "r1041_e82_400bps_tampered", "checksum": "differs_from_package"},
                       {"name": "r1041_e82_400bps_unrecorded", "checksum": "unrecorded"}],
}


def test_flags_and_models_are_in_the_recorded_help():
    assert set(FLAGS) <= help_options(HELP) and "--bacteria" in help_options(HELP)
    choices = help_choices(HELP)
    assert SUP in choices and HAC in choices and len(choices) == 51
    assert not [c for c in choices if "variant" in c or "snp" in c]
    assert "-m  medaka model, (default: r1041_e82_400bps_sup_v5.2.0)." in HELP
    assert "-b  batchsize, controls memory use (default: 100)." in HELP
    listed = (F / "list_models_2.1.1.txt").read_text()
    assert "Default consensus:  r1041_e82_400bps_sup_v5.2.0" in listed
    assert MedakaAdapter.version_pattern.search((F / "version_2.1.1.txt").read_text()).group(1) == "2.1.1"


def test_only_models_the_package_ships_and_conda_vouches_for_are_offered():
    assert offered_models(CATALOGUE) == [HAC, SUP]


@pytest.mark.parametrize("models, status, model", [
    (["dna_r10.4.1_e8.2_400bps_sup@v5.2.0"], "mapped", SUP),
    (["dna_r10.4.1_e8.2_400bps_hac@v5.2.0"] * 2, "mapped", HAC),
    (["dna_r10.4.1_e8.2_400bps_sup@v4.3.0"], "mapped_not_bundled", "r1041_e82_400bps_sup_v4.3.0"),
    (["dna_r9.4.1_e8_fast@v3.4"], "mapped_not_bundled", "r941_min_fast_g507"),
    (["dna_r10.4.1_e8.2_400bps_fast@v5.2.0"], "fast_unsupported", None),
    (["dna_r10.4.1_e8.2_400bps_sup@v9.9.9"], "unknown_basecall_model", None),
    (["dna_r10.4.1_e8.2_400bps_sup@v5.2.0", "dna_r10.4.1_e8.2_400bps_hac@v5.2.0"], "several_basecall_models", None),
    ([], "no_basecall_model", None),
])
def test_model_comes_from_medakas_mapping_and_is_never_guessed(models, status, model):
    out = model_for_basecaller(CATALOGUE, models)
    assert (out["status"], out["model"]) == (status, model)
    assert out["source"] == "medaka.options.basecaller_models"


def test_argv_is_an_argument_vector_with_the_chosen_model(tmp_path):
    exe = tmp_path / "env" / "bin" / "medaka"
    argv = MedakaAdapter.argv(str(exe), MedakaParams(SUP, threads=4, batch_size=50), Path("input/1_reads.fastq.gz"),
                              Path("draft.fasta"), HELP, [HAC, SUP])
    assert argv == [str(exe.parent / "medaka_consensus"), "-i", "input/1_reads.fastq.gz", "-d", "draft.fasta",
                    "-o", "medaka", "-m", SUP, "-t", "4", "-b", "50"]


@pytest.mark.parametrize("params, reads, draft, offered, message", [
    (MedakaParams("r1041_e82_400bps_sup_v4.3.0"), "r.fastq.gz", "d.fasta", [SUP], "not one of the models"),
    (MedakaParams("r1041_e82_400bps_x"), "r.fastq.gz", "d.fasta", ["r1041_e82_400bps_x"], "does not list the model"),
    (MedakaParams("bad name; rm"), "r.fastq.gz", "d.fasta", [SUP], "model must be"),
    (MedakaParams(SUP, threads=0), "r.fastq.gz", "d.fasta", [SUP], "threads"),
    (MedakaParams(SUP, batch_size=0), "r.fastq.gz", "d.fasta", [SUP], "batch_size"),
    (MedakaParams(SUP), "r 1.fastq.gz", "d.fasta", [SUP], "read file name"),
    (MedakaParams(SUP), "r.fastq.gz", "d.gfa", [SUP], ".fasta"),
])
def test_argv_refuses_what_medaka_or_arva_would_not_run(params, reads, draft, offered, message):
    with pytest.raises(ValueError, match=message):
        MedakaAdapter.argv("/env/bin/medaka", params, Path(reads), Path(draft), HELP, offered)


def test_argv_refuses_a_help_without_an_option():
    with pytest.raises(ValueError, match="-b"):
        MedakaAdapter.argv("/env/bin/medaka", MedakaParams(SUP), Path("r.fastq.gz"), Path("d.fasta"),
                           HELP.replace("    -b  batchsize", "    batchsize"), [SUP])


def test_parse_log_of_a_real_run():
    log = (F / "run_synthetic.stdout.log").read_text() + (F / "run_synthetic.stderr.log").read_text()
    out = MedakaAdapter.parse_log(log)
    assert out["finished"] and out["verbatim_contigs"] == []
    assert out["model_files"] == [
        "/opt/arva-tools/conda/medaka/lib/python3.12/site-packages/medaka/data/r1041_e82_400bps_sup_v5.2.0_model_pt.tar.gz"]
    assert {p["program"]: (p["version"], p["pass"]) for p in out["programs"]} == {
        "bcftools": ("1.25", True), "bgzip": ("1.24", True), "minimap2": ("2.31", True), "samtools": ("1.24", True),
        "tabix": ("1.24", True)}
    stages = [s for line in log.splitlines() if (s := MedakaAdapter.stage(line))]
    assert stages == ["versions", "alignment", "inference", "consensus"]
    assert MedakaAdapter.failure_reason(log, 0, 100) is None


def test_contigs_without_reads_are_copied_from_the_draft_and_listed():
    log = (F / "run_unrelated.stdout.log").read_text() + (F / "run_unrelated.stderr.log").read_text()
    assert MedakaAdapter.parse_log(log)["verbatim_contigs"] == ["x"]
    assert MedakaAdapter.parse_gaps((F / "gaps_unrelated.bed").read_text()) == {"x": {"regions": [[0, 20000]],
                                                                                       "bases": 20000}}
    assert MedakaAdapter.parse_gaps("") == {}
    with pytest.raises(ValueError, match="line 1"):
        MedakaAdapter.parse_gaps("x\t5\t2\n")


@pytest.mark.parametrize("log, code, expect", [
    ("Running medaka inference\nKilled\nFailed to run medaka inference.\n", 1, "ran out of memory"),
    ("", 137, "ran out of memory"),
    ("Traceback...\nRuntimeError: bad thing\nFailed to run medaka inference.\n", 1, "inference failed: RuntimeError"),
    ("Failed to run alignment of reads to draft.\n", 1, "could not align"),
    ("Failed to stitch consensus chunks.\n", 1, "stitch"),
    ("Model r1 is not compatible with reads.fastq\n", 1, "not compatible"),
    ("Program    Version    Required   Pass\nminimap2   2.1   2.11   False\n", 1, "minimap2"),
    ("The model file for x is not already installed and could not be downloaded.", 1, "download"),
    ("Invalid option: -z.\n", 1, "refused its options"),
    ("something else\n", 1, None),
])
def test_failure_reasons(log, code, expect):
    reason = MedakaAdapter.failure_reason(log, code, 100)
    assert reason is None if expect is None else expect in reason


def test_conda_records_give_each_package_files_checksum(tmp_path):
    (tmp_path / "conda-meta").mkdir()
    (tmp_path / "conda-meta" / "medaka-2.1.1-py312_1.json").write_text(json.dumps({
        "name": "medaka", "paths_data": {"paths": [{"_path": "lib/m/data/a_model_pt.tar.gz", "sha256": "ab" * 32}]}}))
    (tmp_path / "conda-meta" / "medaka-cpu-0.json").write_text(json.dumps({"name": "medaka-cpu"}))
    assert _conda_records(tmp_path) == {"lib/m/data/a_model_pt.tar.gz": "ab" * 32}


def test_params_round_trip():
    p = MedakaParams.from_dict({"model": SUP, "threads": 2, "batch_size": 100, "other": 1})
    p.validate()
    assert p.as_dict() == {"model": SUP, "threads": 2, "batch_size": 100}
