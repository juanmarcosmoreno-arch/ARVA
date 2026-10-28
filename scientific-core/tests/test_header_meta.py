"""Example lines are quoted from the documentation and test data cited in each test; "constructed" lines
follow a documented template."""
import gzip
import random
import time
from pathlib import Path

import pytest

from arva_core import header_meta as hm
from arva_core.header_meta import (
    combine_suggestions,
    compare_fingerprints,
    compare_mates,
    parse_header,
    sources_for,
    summarise,
)

RESULT_KEYS = {
    "schema", "platform_hint", "confidence", "header_format", "format_confidence", "record_type",
    "read_id", "base_name", "mate", "mate_source", "fields", "extra", "evidence", "warnings",
}
PLATFORMS = {"illumina", "nanopore", "pacbio", "unknown"}
CONFS = {"high", "medium", "low", "none"}
SYNTH = Path(__file__).resolve().parents[2] / "examples" / "synthetic"


def check_shape(r: dict) -> None:
    assert RESULT_KEYS <= set(r)
    assert r["platform_hint"] in PLATFORMS
    assert r["confidence"] in CONFS
    assert r["format_confidence"] in CONFS
    assert r["mate"] in (None, 1, 2)
    assert isinstance(r["fields"], dict) and isinstance(r["extra"], dict)
    assert isinstance(r["warnings"], list) and isinstance(r["evidence"], list)
    for v in list(r["fields"].values()) + list(r["extra"].values()):
        if isinstance(v, str):
            assert len(v) <= hm.MAX_VALUE_CHARS
    if r["platform_hint"] == "unknown":
        assert r["confidence"] == "none"


def test_illumina_basespace_example():
    # [ILLUMINA-1] help.basespace.illumina.com fastq-files
    r = parse_header("@SIM:1:FCX:1:15:6329:1045 1:N:0:2")
    check_shape(r)
    assert (r["platform_hint"], r["confidence"], r["header_format"]) == ("illumina", "high", "illumina_casava18")
    f = r["fields"]
    assert f["instrument"] == "SIM" and f["run_number"] == 1 and f["flowcell_id"] == "FCX"
    assert (f["lane"], f["tile"], f["x_pos"], f["y_pos"]) == (1, 15, 6329, 1045)
    assert (f["read_number"], f["is_filtered"], f["control_number"], f["sample_number"]) == (1, "N", 0, 2)
    assert "index_sequence" not in f
    assert r["mate"] == 1 and r["mate_source"] == "illumina_comment_read_field"
    assert r["extra"] == {} and r["warnings"] == []


def test_illumina_bcl2fastq_umi_example():
    # [ILLUMINA-2] bcl2fastq2 v2.20 guide; same line in [ILLUMINA-3] DRAGEN v4.2
    r = parse_header("@SIM:1:FCX:1:2106:15337:1063:GATCTGTACGTC 1:N:0:ATCACG")
    assert r["platform_hint"] == "illumina" and r["confidence"] == "high"
    assert r["fields"]["umi"] == "GATCTGTACGTC"
    assert r["fields"]["index_sequence"] == "ATCACG"
    assert r["fields"]["tile"] == 2106


def test_illumina_wikipedia_casava18_filtered_control_bits():
    # [COMMUNITY-1] Wikipedia CASAVA 1.8 example
    r = parse_header("@EAS139:136:FC706VJ:2:2104:15343:197393 1:Y:18:ATCACG")
    assert r["platform_hint"] == "illumina" and r["confidence"] == "high"
    assert r["fields"]["is_filtered"] == "Y"
    assert r["fields"]["control_number"] == 18
    assert r["fields"]["run_number"] == 136 and r["fields"]["flowcell_id"] == "FC706VJ"


def test_illumina_wikipedia_sample_number_variant_and_legacy_tag_sequence():
    # [COMMUNITY-2] "@EAS139:136:FC706VJ:2:2104:15343:197393 1:N:18:1" (sample number instead of index)
    r = parse_header("@EAS139:136:FC706VJ:2:2104:15343:197393 1:N:18:1")
    assert r["platform_hint"] == "illumina" and r["fields"]["sample_number"] == 1
    # [COMMUNITY-2] pipeline >= 1.4 uses '#NNNNNN' (tag sequence) instead of '#0' - constructed
    r = parse_header("@HWUSI-EAS100R:6:73:941:1973#ATCACG/2")
    assert r["header_format"] == "illumina_legacy" and r["fields"]["legacy_index"] == "ATCACG" and r["mate"] == 2


def test_illumina_read2_constructed():
    # constructed from the [ILLUMINA-1] template with <read>=2
    r = parse_header("@SIM:1:FCX:1:15:6329:1045 2:N:0:2")
    assert r["mate"] == 2 and r["fields"]["read_number"] == 2


def test_illumina_dual_index_and_dragen_r_umi_constructed():
    # '+' between index 1/2 is documented by Element [ELEMENT-1] and bcl2fastq Stats.json; 'r' UMI prefix
    # and '+' between UMIs by DRAGEN [ILLUMINA-3]
    r = parse_header("@A00123:8:HABCDEFXX:1:1101:1000:2000:rACGTACGT+rTTGGCCAA 1:N:0:ATCACG+GTCTAG")
    assert r["platform_hint"] == "illumina" and r["confidence"] == "high"
    assert r["fields"]["umi"] == "rACGTACGT+rTTGGCCAA"
    assert r["fields"]["index_parts"] == ["ATCACG", "GTCTAG"]


def test_illumina_miseq_style_flowcell_with_dash_is_accepted_with_note():
    r = parse_header("@M00123:45:000000000-A1B2C:1:1101:15589:1331 1:N:0:1")
    assert r["platform_hint"] == "illumina" and r["fields"]["flowcell_id"] == "000000000-A1B2C"
    assert any("outside Illumina's documented character set" in e for e in r["evidence"])


def test_illumina_name_only_is_medium():
    r = parse_header("@SIM:1:FCX:1:15:6329:1045")
    assert r["platform_hint"] == "illumina" and r["confidence"] == "medium"
    assert r["header_format"] == "illumina_casava18_name_only" and r["mate"] is None


def test_illumina_legacy_pre_casava18():
    # [COMMUNITY-1] Wikipedia pre-1.8 example
    r = parse_header("@HWUSI-EAS100R:6:73:941:1973#0/1")
    assert (r["platform_hint"], r["confidence"], r["header_format"]) == ("illumina", "medium", "illumina_legacy")
    assert r["mate"] == 1 and r["mate_source"] == "slash_suffix"
    assert r["base_name"] == "HWUSI-EAS100R:6:73:941:1973#0"
    assert r["fields"]["lane"] == 6 and r["fields"]["legacy_index"] == "0"
    r2 = parse_header("@HWUSI-EAS100R:6:73:941:1973#0/2")
    assert r2["mate"] == 2 and r2["base_name"] == r["base_name"]


def test_mate_conflict_is_warned():
    r = parse_header("@SIM:1:FCX:1:15:6329:1045/2 1:N:0:2")
    assert "mate_conflict_slash_suffix_vs_comment" in r["warnings"]
    assert r["mate"] == 1  # the documented Illumina comment wins over the generic suffix


def test_comment_only_is_low_illumina():
    r = parse_header("@myread_17 1:N:0:ACGTAC")
    assert (r["platform_hint"], r["confidence"]) == ("illumina", "low")


def test_element_aviti_is_not_reported_as_illumina():
    # constructed from the [ELEMENT-1] template "@<instrument>_<model>:<run name>:<flow cell ID>:..."
    r = parse_header("@MyInstr_AVITI:Run-01:2324567890:1:10102:0123:4567 1:N:0:ATCACG")
    assert r["platform_hint"] == "unknown" and r["header_format"] == "element_bases2fastq"
    assert r["fields"]["vendor_hint"] == "element_biosciences"
    assert r["fields"]["run_name"] == "Run-01"
    # cell-screening layout (11 colon fields) [ELEMENT-1], constructed
    r = parse_header("@MyInstr_AVITI:Run-01:FC-1:01:1010203:0012:0034:0000000001:0:B01:0002538 1:N:0:1")
    assert r["platform_hint"] == "unknown" and r["header_format"] == "element_bases2fastq_other_layout"


def test_sra_default_defline():
    # [SRA-2] sra-tools wiki expected output
    r = parse_header("@SRR390728.1 1 length=72")
    check_shape(r)
    assert r["platform_hint"] == "unknown" and r["header_format"] == "sra_default_defline"
    assert r["format_confidence"] == "high"
    assert r["fields"] == {"accession": "SRR390728", "spot_id": 1, "length": 72, "spot_name": "1"}
    assert r["mate"] is None


def test_sra_quality_line_style_plus_is_not_a_header_but_parses():
    r = parse_header("+SRR390728.1 1 length=72")
    assert "missing_record_prefix" in r["warnings"]


def test_sra_split_and_readids_constructed():
    # fasterq-dump split default '$ac.$si/$ri $sn length=$rl' [SRA-1]
    r1 = parse_header("@SRR390728.1/1 1 length=72")
    r2 = parse_header("@SRR390728.1/2 1 length=72")
    assert (r1["mate"], r2["mate"]) == (1, 2)
    assert r1["base_name"] == r2["base_name"] == "SRR390728.1"
    # fastq-dump --readids 'accession.spot.readid' [SRA-3]
    r = parse_header("@SRR390728.1.2 1 length=72")
    assert r["fields"]["read_in_spot"] == 2 and r["mate"] is None


def test_sra_with_original_illumina_name():
    # [COMMUNITY-1] Wikipedia NCBI SRA example
    r = parse_header("@SRR001666.1 071112_SLXA-EAS1_s_7:5:1:817:345 length=36")
    assert r["header_format"] == "sra_default_defline"
    assert r["platform_hint"] == "illumina" and r["confidence"] == "low"
    assert r["original_name"]["header_format"] == "illumina_legacy"


def test_sra_with_ont_attributes_in_comment():
    # [ONT-11] fastcat fixture bcMangled.fastq.gz
    r = parse_header("@SRR12480552.4 /1 runid=0000000000000000000000000000000000000000 barcode=barcode01")
    assert r["platform_hint"] == "nanopore" and r["confidence"] in ("low", "medium")
    assert r["fields"]["barcode"] == "barcode01"
    assert r["header_format"] == "sra_accession_id"


def test_ont_spec_generic_example_is_uuid_only_low():
    # [ONT-1] ONT output specification record-structure example
    r = parse_header("@bd8655fb-383c-45cc-bff3-eb1dc86533e0 key1=value1 key2=value2")
    assert (r["platform_hint"], r["confidence"], r["header_format"]) == ("nanopore", "low", "uuid_read_id")
    assert r["extra"] == {"key1": "value1", "key2": "value2"}


MINKNOW_FULL = ("@1d0fded8-95e7-4b53-858f-8391da5d6537 runid=5a21d8a6996146deceeaea3784244c52741cae93 read=13 "
                "ch=190 start_time=2021-04-20T17:00:40Z flow_cell_id=FAP67897 protocol_group_id=2021-04-20_UKBC "
                "sample_id=RNAsst10002_spike_BA barcode=barcode02 barcode_alias=barcode02")


def test_ont_minknow_full_kv_header():
    # [ONT-11] fastcat test/fixtures/fastq/basic/bc2.fastq.gz
    r = parse_header(MINKNOW_FULL)
    check_shape(r)
    assert (r["platform_hint"], r["confidence"], r["header_format"]) == ("nanopore", "high", "ont_minknow_kv")
    f = r["fields"]
    assert f["run_id"] == "5a21d8a6996146deceeaea3784244c52741cae93"
    assert f["channel"] == 190 and f["channel_read_number"] == 13
    assert f["flowcell_id"] == "FAP67897" and f["protocol_group_id"] == "2021-04-20_UKBC"
    assert f["sample_id"] == "RNAsst10002_spike_BA" and f["barcode"] == "barcode02"
    assert f["start_time"] == "2021-04-20T17:00:40Z"
    assert r["extra"] == {} and r["warnings"] == []


def test_ont_spec_style_kv_with_model_and_parent_constructed():
    # constructed from [ONT-1] attribute list using the spec's own example values
    line = ("@e4994c62-93f9-439a-bc8f-d20c95a137a5 runid=e4994c62-93f9-439a-bc8f-d20c95a137a5 ch=512 "
            "start_time=2025-01-13T10:45:28.681306+00:00 flow_cell_id=PXX12345 protocol_group_id=my-group-1 "
            "sample_id=my-sample-1 barcode=barcode01 barcode_alias=sample01 "
            "parent_read_id=e4994c62-93f9-439a-bc8f-d20c95a137a5 basecall_model_version_id=rna004_130bps_fast@v5.1.0 "
            "basecall_gpu=Nvidia_3090")
    r = parse_header(line)
    assert (r["platform_hint"], r["confidence"]) == ("nanopore", "high")
    assert r["fields"]["basecall_model"] == "rna004_130bps_fast@v5.1.0"
    assert r["fields"]["basecall_gpu"] == "Nvidia_3090"
    assert r["fields"]["parent_read_id"] == "e4994c62-93f9-439a-bc8f-d20c95a137a5"
    assert r["warnings"] == []


def test_ont_dorado_fixture_old_minknow():
    # [ONT-6] dorado tests/data/aligner_test/dataset.fastq
    r = parse_header("@c2707254-5445-4cfb-a414-fce1f12b56c0 runid=5c76f4079ee8f04e80b4b8b2c4b677bce7bebb1e "
                     "read=1728 ch=332 start_time=2017-06-16T15:31:55Z")
    assert (r["platform_hint"], r["confidence"]) == ("nanopore", "high")
    # [ONT-6] dorado tests/data/barcode_demux/dual/single.fastq ('sampleid' alias)
    r = parse_header("@83008e54-836e-4d14-8b62-2a0ebbecb9f9 runid=4c0e23c14bf67ccb61139b1279f83eeeaf30e50a "
                     "sampleid=native11_PCR60_ecoli66 read=105042 ch=16 start_time=2019-07-13T07:52:41Z")
    assert r["platform_hint"] == "nanopore" and r["fields"]["sample_id"] == "native11_PCR60_ecoli66"


def test_ont_fastcat_model_version_id_alias():
    # fastcat test/fixtures/fastq/metadata/mixed_basecaller_model_key.fastq.gz
    r = parse_header("@18ac90e2-814b-457b-8c43-d3b6da1503ca runid=4cbe20b5e27e673b10b44d873c8dd49f7bbe2daf "
                     "sampleid=24_samples read=37875 ch=36 start_time=2024-02-17T02:29:18Z "
                     "model_version_id=dna_r10.4.1_e8.2_400bps_sup@2023-12-15_episeq-cs")
    assert (r["platform_hint"], r["confidence"]) == ("nanopore", "high")
    assert r["fields"]["basecall_model"] == "dna_r10.4.1_e8.2_400bps_sup@2023-12-15_episeq-cs"


def test_ont_spec_violations_reduce_confidence():
    # [ONT-7] fastcat test/fixtures/fastq/reheader/kv.fastq (synthetic values outside the spec regexes)
    r = parse_header("@read1 runid=run-123 basecall_model_version_id=model@v1 barcode=barcode07 "
                     "start_time=2023-01-01T00:00:00Z parent_read_id=pr-001 read=7 ch=42 flow_cell_id=FLO-MIN114 "
                     "basecall_gpu=gpu0 barcode_alias=alias1 unknown=foo")
    assert r["platform_hint"] == "nanopore" and r["confidence"] == "medium"
    assert "value_outside_spec_regex:runid" in r["warnings"]
    assert "value_outside_spec_regex:parent_read_id" in r["warnings"]
    assert r["extra"] == {"unknown": "foo"}


DORADO_HTS_FULL = ("@0a579f20-1ab0-4e5b-91e6-30e37cf7eb96\tRG:Z:4524e8b9-b90e-4ffb-a13a-380266513b64_dna_r10.4.1_e8.2_400bps_hac@v5.0.0"
                   "\tDT:Z:2022-10-18T10:18:07.247000+00:00\tch:i:63\tst:Z:2022-10-18T10:38:07.247+00:00\tPU:Z:PAM93185"
                   "\tLB:Z:PCR_zymo\tSM:Z:barcode03\tal:Z:alias_for_bc03\tpi:Z:e4994c62-93f9-439a-bc8f-d20c95a137a5"
                   "\tDS:Z:gpu:Tesla V100-PCIE-16GB\tqs:f:30.0\tmx:i:2\trn:i:432\tts:i:1048\tpt:i:120\tpa:B:i,12,30,45,232,242")


def test_ont_dorado_hts_full_header():
    # [ONT-6] dorado tests/data/aligner_test/example-hts.fastq.gz
    r = parse_header(DORADO_HTS_FULL)
    check_shape(r)
    assert (r["platform_hint"], r["confidence"], r["header_format"]) == ("nanopore", "high", "ont_dorado_hts")
    f = r["fields"]
    assert f["run_id"] == "4524e8b9-b90e-4ffb-a13a-380266513b64"
    assert f["basecall_model"] == "dna_r10.4.1_e8.2_400bps_hac@v5.0.0"
    assert f["flowcell_id"] == "PAM93185" and f["sample_id"] == "PCR_zymo"
    assert f["barcode"] == "barcode03" and f["barcode_alias"] == "alias_for_bc03"
    assert f["basecall_gpu"] == "Tesla V100-PCIE-16GB"  # value with a space survives tab tokenisation
    assert f["channel"] == 63 and f["mux"] == 2 and f["channel_read_number"] == 432
    assert f["experiment_start_time"] == "2022-10-18T10:18:07.247000+00:00"
    assert r["extra"] == {"ts": "1048", "pa": "i,12,30,45,232,242"}


def test_ont_dorado_minimal_tags_hex_runid():
    # [ONT-6] dorado tests/data/bam_reader/fastq_with_tags.fq
    r = parse_header("@8623ac42-0956-4692-9a93-bdd99bf1a94e\tst:Z:2023-06-22T07:17:48.308+00:00"
                     "\tRG:Z:6a94c5e38fbe36232d63fd05555e41368b204cda_dna_r10.4.1_e8.2_400bps_hac@v4.3.0")
    assert (r["platform_hint"], r["confidence"]) == ("nanopore", "high")
    assert r["fields"]["run_id"] == "6a94c5e38fbe36232d63fd05555e41368b204cda"
    assert r["fields"]["basecall_model"] == "dna_r10.4.1_e8.2_400bps_hac@v4.3.0"


def test_ont_rg_with_barcode_kit_suffix():
    # fastcat .../dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mCG_5hmCG_rbk.bam.fastq.gz (prefix of the header)
    r = parse_header("@7da531c9-2ca9-49d9-ae08-46bd08e5e9ed\tBC:Z:SQK-RBK114-96_barcode09\tqs:f:15.8356\tch:i:5"
                     "\tst:Z:2023-08-04T11:48:39.799+00:00\trn:i:-1"
                     "\tRG:Z:7f49cdd331b10b0f59539902b8f2af9e42ba9eea_dna_r10.4.1_e8.2_400bps_hac@v5.0.0_SQK-RBK114-96_barcode09"
                     "\tpi:Z:84dda407-7d66-4cf0-9700-023c12c222c0\tsp:i:0")
    assert r["platform_hint"] == "nanopore"
    assert r["fields"]["barcode_arrangement"] == "SQK-RBK114-96_barcode09"
    assert r["fields"]["channel_read_number"] == -1
    assert r["extra"]["BC"] == "SQK-RBK114-96_barcode09" and r["extra"]["sp"] == "0"


def test_ont_rg_unknown_model_and_comment_tag():
    # [ONT-11] fastcat test/expected/fastcat/demultiplex/barcode0002.fastq.gz; [ONT-12] "unknown" model rule
    r = parse_header("@1d0fded8-95e7-4b53-858f-8391da5d6537\trn:i:13\tch:i:190\tst:Z:2021-04-20T17:00:40Z\tPU:Z:FAP67897"
                     "\tLB:Z:RNAsst10002_spike_BA\tSM:Z:barcode02\tal:Z:barcode02\tCO:Z:protocol_group_id=2021-04-20_UKBC"
                     "\tRG:Z:5a21d8a6996146deceeaea3784244c52741cae93_unknown_barcode02\tqs:f:7.76831")
    assert (r["platform_hint"], r["confidence"]) == ("nanopore", "high")
    assert "read_group_model_unknown" in r["warnings"]
    assert "basecall_model" not in r["fields"]
    assert r["fields"]["barcode_arrangement"] == "barcode02"
    assert r["extra"]["CO"] == "protocol_group_id=2021-04-20_UKBC"


def test_ont_spec_rg_examples_and_multi_gpu():
    # [ONT-12] bam/spec.yaml RG examples; [ONT-13] DS example with two GPU types
    r = parse_header("@e4994c62-93f9-439a-bc8f-d20c95a137a5\tRG:Z:e4994c62-93f9-439a-bc8f-d20c95a137a5_rna004_130bps_fast@v5.1.0_29d8704b"
                     "\tDS:Z:gpu:NVIDIA A100 80GB PCIe|Quadro GV100")
    assert r["platform_hint"] == "nanopore"
    assert r["fields"]["basecall_model"] == "rna004_130bps_fast@v5.1.0"
    assert r["fields"]["barcode_arrangement"] == "29d8704b"
    assert r["fields"]["basecall_gpu"] == "NVIDIA A100 80GB PCIe|Quadro GV100"


def test_ont_samtools_fastq_T_output():
    # fastcat test/fixtures/fastq/basic/samtoolsfastq.fastq.gz
    r = parse_header("@02f8ea0a-48a3-43e3-b3b4-4832304a1d63\tqs:i:18\tdu:f:3.06125\tns:i:12245\tts:i:635\tmx:i:3\tch:i:388"
                     "\tst:Z:2022-09-27T16:54:30.522+00:00\trn:i:6040\tfn:Z:PAM14583_ee1ba89e_88.pod5\tsm:f:94.3098"
                     "\tsd:f:27.8859\tsv:Z:quantile\tdx:i:0"
                     "\tRG:Z:ee1ba89e9e8bdff1ed2f4b2a81d21464ff7c4f1c_dna_r10.4.1_e8.2_400bps_sup@v4.1.0")
    assert (r["platform_hint"], r["confidence"]) == ("nanopore", "high")
    assert r["fields"]["duplex_flag"] == 0
    assert r["extra"]["fn"] == "PAM14583_ee1ba89e_88.pod5"


def test_generic_kv_is_not_interpreted_as_ont():
    r = parse_header("@foo read=5 ch=3")
    assert r["platform_hint"] == "unknown"
    assert r["fields"] == {} and r["extra"] == {"read": "5", "ch": "3"}


def test_dorado_move_table_token_is_skipped():
    mv = "mv:B:c," + ",".join(["1"] * 5000)
    r = parse_header(DORADO_HTS_FULL + "\t" + mv)
    assert r["platform_hint"] == "nanopore"
    assert "oversized_token_skipped:mv" in r["warnings"]


@pytest.mark.parametrize(
    "line,fmt,strand",
    [
        ("@m64011_190714_120746/14/ccs/rev", "pacbio_ccs_bystrand", "rev"),  # [PACBIO-6] ccs.how
        ("@m64011_190714_120746/35/ccs/fwd", "pacbio_ccs_bystrand", "fwd"),  # [PACBIO-6] ccs.how
        ("@m64011_190830_220126/1/ccs", "pacbio_ccs", None),  # constructed {movieName}/{holeNumber}/ccs
        ("@m64011_190830_220126/1/ccs/fwd/0_1500", "pacbio_ccs_bystrand_segmented", "fwd"),  # [PACBIO-1]
        ("@m84001_220722_134701_s1/4325/ccs/120_9000", "pacbio_ccs_segmented", None),  # [PACBIO-1]+[PACBIO-7]
    ],
)
def test_pacbio_ccs(line, fmt, strand):
    r = parse_header(line)
    check_shape(r)
    assert (r["platform_hint"], r["confidence"], r["header_format"]) == ("pacbio", "high", fmt)
    assert r["fields"]["read_type"] == "ccs"
    assert r["fields"].get("strand") == strand
    assert r["mate"] is None


def test_pacbio_revio_movie_context_decoding():
    r = parse_header("@m84001_220722_134701_s1/4325/ccs")
    f = r["fields"]
    assert f["movie_name"] == "m84001_220722_134701_s1"
    assert (f["movie_instrument_id"], f["movie_date_yymmdd"], f["movie_time_hhmmss"], f["movie_stage"]) == (
        "84001", "220722", "134701", "1")
    assert f["hole_number"] == 4325


def test_pacbio_subread_and_rs_movie():
    # [PACBIO-2] {movieName}/{holeNumber}/{qStart}_{qEnd}; [PACBIO-4] RS-era movie name example
    r = parse_header("@m150404_101626_42267_s1_p0/100/0_500")
    assert (r["platform_hint"], r["header_format"]) == ("pacbio", "pacbio_subread")
    assert (r["fields"]["q_start"], r["fields"]["q_end"]) == (0, 500)


def test_pacbio_prefixed_name_is_low():
    # bam2fastq -p/--seqid-prefix [PACBIO-5] may change the movie part
    r = parse_header("@sample1_m64011_190830_220126/1/ccs")
    assert r["platform_hint"] == "pacbio" and r["confidence"] == "low"


def test_pacbio_tags_from_samtools_fastq():
    r = parse_header("@m64011_190830_220126/1/ccs\tnp:i:12\trq:f:0.999\tzm:i:1\tqs:i:0")
    assert r["fields"]["num_passes"] == "12" and r["fields"]["read_quality"] == "0.999"
    assert r["extra"]["qs"] == "0"  # not interpreted as an ONT mean q-score


def test_fasta_prefix():
    r = parse_header(">m64011_190830_220126/1/ccs")
    assert r["record_type"] == "fasta" and r["platform_hint"] == "pacbio"


def test_synthetic_illumina_header():
    r = parse_header("@synthetic_ill_0/1 SYNTHETIC random sequence")
    check_shape(r)
    assert r["platform_hint"] == "unknown" and r["confidence"] == "none"
    assert r["header_format"] == "generic_slash_mate"
    assert r["mate"] == 1 and r["base_name"] == "synthetic_ill_0"
    assert r["fields"] == {}
    assert r["extra"] == {"token_0": "SYNTHETIC", "token_1": "random", "token_2": "sequence"}


def test_synthetic_ont_header():
    r = parse_header("@synthetic_ont_0 SYNTHETIC random sequence")
    check_shape(r)
    assert r["platform_hint"] == "unknown" and r["header_format"] == "unrecognised"
    assert r["mate"] is None and r["fields"] == {}


def _fastq_headers(path: Path, n: int = 1000):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i // 4 >= n:
                break
            if i % 4 == 0:
                yield line.rstrip("\n")


def test_summarise_synthetic_files():
    s1 = summarise(_fastq_headers(SYNTH / "SYNTHETIC_illumina_R1_001.fastq.gz"))
    s2 = summarise(_fastq_headers(SYNTH / "SYNTHETIC_illumina_R2_001.fastq.gz"))
    so = summarise(_fastq_headers(SYNTH / "SYNTHETIC_nanopore_reads.fastq.gz"))
    assert s1["n_headers_read"] == 1000 and s1["mate_layout"] == "mate_1_only"
    assert s2["mate_layout"] == "mate_2_only"
    assert so["n_headers_read"] == 400 and so["mate_layout"] == "no_mate_markers"
    for s in (s1, s2, so):
        assert s["suggested_technology"]["value"] is None
        assert s["suggested_technology"]["overrides_user_metadata"] is False
        assert s["platform_counts"] == {"unknown": s["n_usable"]}
    cm = compare_mates(_fastq_headers(SYNTH / "SYNTHETIC_illumina_R1_001.fastq.gz"),
                       _fastq_headers(SYNTH / "SYNTHETIC_illumina_R2_001.fastq.gz"))
    assert cm["looks_like_pair"] is True and cm["pairs_compared"] == 1000


def test_summarise_illumina_lanes_and_reads():
    hs = [f"@A00123:8:HABCDEFXX:{lane}:1101:{x}:2000 1:N:0:ATCACG+GTCTAG" for lane in (1, 2) for x in range(5)]
    hs += ["", "   ", None, b"\x00\x01\x02\x03\xff\xfe"]
    s = summarise(hs)
    assert s["n_headers_read"] == 14 and s["n_usable"] == 10
    assert s["distinct"]["lane"]["values"] == ["1", "2"]
    assert s["distinct"]["flowcell_id"]["values"] == ["HABCDEFXX"]
    assert s["distinct"]["instrument"]["values"] == ["A00123"]
    assert s["illumina_read_numbers"] == {"1": 10}
    assert s["mate_layout"] == "mate_1_only"
    st = s["suggested_technology"]
    assert (st["value"], st["confidence"]) == ("illumina", "high")
    assert s["format_counts"]["empty"] == 2 and s["format_counts"]["invalid"] == 2


def test_summarise_ont_runs_and_models():
    hs = [MINKNOW_FULL, DORADO_HTS_FULL] * 3
    s = summarise(hs)
    d = s["distinct"]
    assert set(d["run_id"]["values"]) == {"5a21d8a6996146deceeaea3784244c52741cae93", "4524e8b9-b90e-4ffb-a13a-380266513b64"}
    assert d["basecall_model"]["values"] == ["dna_r10.4.1_e8.2_400bps_hac@v5.0.0"]
    assert set(d["flowcell_id"]["values"]) == {"FAP67897", "PAM93185"}
    assert set(d["sample_id"]["values"]) == {"RNAsst10002_spike_BA", "PCR_zymo"}
    assert s["suggested_technology"]["value"] == "nanopore"
    assert s["suggested_technology"]["confidence"] == "high"


def test_summarise_mixed_platforms_is_low_and_never_overrides():
    s = summarise(["@SIM:1:FCX:1:15:6329:1045 1:N:0:2"] * 5 + [MINKNOW_FULL] * 5)
    st = s["suggested_technology"]
    assert st["confidence"] == "low" and st["conflicting_headers"] == 5
    assert st["overrides_user_metadata"] is False


def test_summarise_interleaved():
    s = summarise(["@x/1", "@x/2", "@y/1", "@y/2"])
    assert s["mate_layout"] == "mixed_1_and_2"


def test_summarise_limits_and_bad_inputs():
    gen = (f"@SIM:1:FCX:1:15:{i}:1045 1:N:0:2" for i in range(10_000_000))  # lazily consumed
    t = time.perf_counter()
    s = summarise(gen, max_headers=50, max_distinct=3)
    assert time.perf_counter() - t < 2
    assert s["n_headers_read"] == 50
    assert s["distinct"]["lane"]["n_distinct"] == 1
    assert summarise(None)["n_headers_read"] == 0
    assert summarise(42)["warning_counts"] == {"headers_not_iterable": 1}
    assert summarise(["@a"], max_headers="x")["warning_counts"]["invalid_limits_defaulted"] == 1

    def boom():
        yield "@SIM:1:FCX:1:15:6329:1045 1:N:0:2"
        raise OSError("disk gone")

    s = summarise(boom())
    assert s["n_usable"] == 1 and s["warning_counts"] == {"iteration_error:OSError": 1}


def test_compare_mates_mismatch():
    cm = compare_mates(["@a/1", "@b/1"], ["@a/2", "@c/2"])
    assert cm["looks_like_pair"] is False and cm["match_fraction"] == 0.5
    cm = compare_mates(["@SIM:1:FCX:1:15:6329:1045 1:N:0:2"], ["@SIM:1:FCX:1:15:6329:1045 2:N:0:2"])
    assert cm["looks_like_pair"] is True


@pytest.mark.parametrize("value", ["", "@", "@ ", ">", " ", "\n", "\r\n", "\t", "@\t\t"])
def test_empty_like(value):
    r = parse_header(value)
    check_shape(r)
    assert r["platform_hint"] == "unknown" and r["header_format"] in ("empty", "invalid")


@pytest.mark.parametrize("value", [None, 0, 3.14, ["@a"], {"a": 1}, object()])
def test_non_string_inputs(value):
    r = parse_header(value)
    check_shape(r)
    assert r["header_format"] == "invalid"


def test_binary_junk_never_raises():
    rng = random.Random(1234)
    for _ in range(2000):
        blob = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
        r = parse_header(blob)
        check_shape(r)
    r = parse_header(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03")  # gzip magic passed by mistake
    assert r["header_format"] == "invalid"


def test_bytes_header_is_decoded():
    r = parse_header(MINKNOW_FULL.encode())
    assert r["platform_hint"] == "nanopore"


def test_nul_and_control_characters():
    r = parse_header("@SIM:1:FCX:1:15:6329:1045 1:N:0:2" + "\x00")
    check_shape(r)
    assert "control_or_undecodable_characters" in r["warnings"]


def test_crlf_and_multiline():
    r = parse_header("@SIM:1:FCX:1:15:6329:1045 1:N:0:2\r\n")
    assert r["platform_hint"] == "illumina" and r["warnings"] == []
    r = parse_header("@SIM:1:FCX:1:15:6329:1045 1:N:0:2\nACGT\n+\nIIII\n")
    assert r["platform_hint"] == "illumina" and "multiple_lines_input_only_first_used" in r["warnings"]


def test_non_ascii_digits_are_not_numbers():
    # Arabic-Indic digits must not be accepted as lane/tile numbers (re.ASCII)
    r = parse_header("@SIM:١:FCX:1:15:6329:1045 1:N:0:2")
    assert r["header_format"] != "illumina_casava18"
    check_shape(r)


def test_huge_numbers_stay_strings():
    r = parse_header("@SIM:1:FCX:1:15:6329:" + "9" * 5000 + " 1:N:0:2")
    check_shape(r)
    assert r["platform_hint"] in PLATFORMS  # oversized read id is truncated, never int()-converted
    r = parse_header("@SIM:1:FCX:" + "1" * 30 + ":15:6329:1045 1:N:0:2")
    assert isinstance(r["fields"]["lane"], str)
    assert "non_integer_or_oversized_number:lane" in r["warnings"]


@pytest.mark.parametrize(
    "line",
    [
        "@" + "A" * 2_000_000,
        "@" + "a:" * 500_000,
        "@id " + "k=v " * 300_000,
        "@id " + ("x" * 10_000 + " ") * 50,
        "@" + "1" * 10_000 + " 1:N:0:" + "A" * 100_000,
        "@m" + "0" * 100_000 + "/1/ccs",
        "@" + "a/" * 200_000 + "1",
        "@0a579f20-1ab0-4e5b-91e6-30e37cf7eb96\t" + "\t".join(f"x{i % 9}:Z:" + "v" * 50 for i in range(100_000)),
        "@e4994c62-93f9-439a-bc8f-d20c95a137a5\tRG:Z:e4994c62-93f9-439a-bc8f-d20c95a137a5_" + "@v1" * 1300,
    ],
    ids=["2M_char_id", "500k_colons", "300k_kv_tokens", "50_oversized_tokens", "huge_illumina_like",
         "100k_digit_movie", "200k_slashes", "100k_tab_tags", "rg_backtracking_probe"],
)
def test_very_long_inputs_are_fast_and_bounded(line):
    t = time.perf_counter()
    r = parse_header(line)
    elapsed = time.perf_counter() - t
    check_shape(r)
    assert elapsed < 2.0, elapsed
    assert len(r["extra"]) <= 64
    assert len(r["read_id"] or "") <= hm.MAX_VALUE_CHARS


def test_random_header_like_fuzz_never_raises():
    rng = random.Random(42)
    alphabet = "ACGTN0123456789:@/_-.=+#\t abcxyzZRGsthpié�"
    pieces = ["1:N:0:", "runid=", "RG:Z:", "/ccs", "/1", "@v5.0.0", "SRR1234567.", " length=", "ch:i:", "flow_cell_id="]
    for _ in range(5000):
        s = "@" + "".join(rng.choice(pieces) if rng.random() < 0.2 else rng.choice(alphabet)
                          for _ in range(rng.randrange(0, 120)))
        check_shape(parse_header(s))


def test_summary_keeps_evidence_sources_and_a_bounded_fingerprint():
    s = summarise([MINKNOW_FULL] * 300 + ["@synthetic_ont_0 SYNTHETIC random sequence"])
    assert s["evidence"]["ont_minknow_kv"][0].startswith("MinKNOW-style key=value attributes")
    assert s["evidence"]["unrecognised"] == []
    assert s["sources"]["ont_minknow_kv"] == hm.SOURCES["ont_minknow_kv"]
    assert s["sources"]["unrecognised"] == []
    fp = s["mate_fingerprint"]
    assert len(fp["base_names"]) == len(fp["mates"]) == hm.FINGERPRINT_SIZE
    assert fp["base_names"][0] == "1d0fded8-95e7-4b53-858f-8391da5d6537"
    assert summarise(["@a/1", ""], fingerprint_size=5)["mate_fingerprint"] == {"base_names": ["a", None], "mates": [1, None]}


def test_sources_for_formats():
    assert sources_for("illumina_casava18_name_only") == hm.SOURCES["illumina_casava18"]
    assert sources_for("illumina_legacy") == hm.SOURCES["illumina_legacy"]
    assert sources_for("pacbio_ccs_bystrand") == hm.SOURCES["pacbio"]
    assert sources_for("uuid_read_id") == hm.SOURCES["ont_minknow_kv"]
    assert sources_for("illumina_comment_only+uuid_read_id") == hm.SOURCES["illumina_casava18"] + hm.SOURCES["ont_minknow_kv"]
    assert sources_for("generic_slash_mate") == sources_for("unrecognised") == []


def test_stored_fingerprints_give_the_same_answer_as_compare_mates():
    r1 = _fastq_headers(SYNTH / "SYNTHETIC_illumina_R1_001.fastq.gz")
    r2 = _fastq_headers(SYNTH / "SYNTHETIC_illumina_R2_001.fastq.gz")
    ont = _fastq_headers(SYNTH / "SYNTHETIC_nanopore_reads.fastq.gz")
    fp1, fp2, fpo = (summarise(h)["mate_fingerprint"] for h in (r1, r2, ont))
    good = compare_fingerprints(fp1, fp2)
    assert good["looks_like_pair"] is True and good["pairs_compared"] == good["base_name_matches"] == 200
    assert compare_fingerprints(fp1, fpo)["looks_like_pair"] is False
    swapped = compare_fingerprints(fp2, fp1)
    assert swapped["looks_like_pair"] is False and swapped["match_fraction"] == 1.0
    a, b = ["@a/1", "@b/1", "@x/1"], ["@a/2", "@c/2", "@x/2"]
    via_fp = compare_fingerprints(summarise(a)["mate_fingerprint"], summarise(b)["mate_fingerprint"])
    assert via_fp == compare_mates(a, b)
    for bad in (None, {}, {"base_names": ["a"], "mates": []}, {"base_names": 3, "mates": 3}):
        assert compare_fingerprints(bad, fp1) == {"pairs_compared": 0, "error": "invalid_fingerprint", "looks_like_pair": False}


def _suggestion(value, confidence):
    return {"value": value, "confidence": confidence}


@pytest.mark.parametrize(
    "per_file, value, confidence, basis",
    [
        ([], None, "none", "no_evidence"),
        ([_suggestion(None, "none")] * 3, None, "none", "no_evidence"),
        ([_suggestion("nanopore", "high")], "nanopore", "high", "single_platform"),
        ([_suggestion("illumina", "high"), _suggestion("illumina", "medium")], "illumina", "medium", "single_platform"),
        ([_suggestion("illumina", "high"), _suggestion("nanopore", "high")], "hybrid", "high", "short_and_long_reads"),
        ([_suggestion("illumina", "high"), _suggestion("pacbio", "low")], "hybrid", "low", "short_and_long_reads"),
        ([_suggestion("nanopore", "high"), _suggestion("pacbio", "high")], None, "none", "conflicting_platforms"),
        ([_suggestion("nanopore", "high"), _suggestion(None, "none")], "nanopore", "medium", "single_platform"),
        ([_suggestion("nanopore", "high"), None, "junk"], "nanopore", "medium", "single_platform"),
    ],
)
def test_combine_suggestions(per_file, value, confidence, basis):
    c = combine_suggestions(per_file)
    assert (c["value"], c["confidence"], c["basis"]) == (value, confidence, basis)
    assert c["overrides_user_metadata"] is False
    assert c["files_considered"] == len(per_file)


def test_combine_synthetic_files_is_not_inferable():
    files = ("SYNTHETIC_illumina_R1_001.fastq.gz", "SYNTHETIC_illumina_R2_001.fastq.gz", "SYNTHETIC_nanopore_reads.fastq.gz")
    c = combine_suggestions([summarise(_fastq_headers(SYNTH / f))["suggested_technology"] for f in files])
    assert c["value"] is None and c["basis"] == "no_evidence" and c["files_with_evidence"] == 0
