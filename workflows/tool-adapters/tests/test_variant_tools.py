"""Variant calling: BCFtools (mpileup, call, norm, filter, csq, index) with BWA-MEM / minimap2 and samtools — options
against the real usage texts (fixtures/variants) and real runs on SIMULATED reads: a random constructed genome with
two genes, a copy carrying known SNPs and indels, and error-free reads drawn from that copy (labelled SIMULATED in
every read name). The truth is known, so the test checks that every planted variant is called, normalised and
annotated; it says nothing about real data, which fixtures/variants/README.md covers.
"""
import gzip
import random
from pathlib import Path

import pytest
from arva_core import variants as av

from arva_tools.bcftools import (
    FILTER_DEFAULTS,
    HELP_FLAGS,
    BcftoolsAdapter,
    VariantParams,
    filter_expressions,
    flags_used,
)
from arva_tools.mapping import BwaAdapter, Minimap2Adapter, SamtoolsAdapter, read_group_line
from arva_tools.registry import ADAPTERS, detect
from arva_tools.runner import run_command

FX = Path(__file__).parent / "fixtures" / "variants"


def tool(tool_id: str) -> str:
    d = detect(tool_id, refresh=True)
    if d.path is None or d.status.value != "available":
        pytest.skip(f"{tool_id} is not available: {d.message}")
    return d.path


def test_registered_and_flags_in_usage_texts():
    assert "bcftools" in ADAPTERS
    for command in HELP_FLAGS:
        text = (FX / f"bcftools_{command}_usage_1.19.txt").read_text()
        assert BcftoolsAdapter.missing_flags(command, text) == [], command
    assert BcftoolsAdapter.missing_flags("call", "Usage: bcftools call\n  -m, --multiallelic-caller") == \
        ["--ploidy", "-P", "-v", "-O", "-o"]


def test_profiles_write_out_bcftools_presets():
    ont = VariantParams(technology="ont")
    argv = BcftoolsAdapter.mpileup_argv("bcftools", Path("r.fa"), Path("a.bam"), Path("o.bcf"), ont)
    assert "-B" in argv and "-I" in argv and "-X" not in argv
    assert argv[argv.index("-Q") + 1] == "5" and argv[argv.index("--max-BQ") + 1] == "30"
    hifi = BcftoolsAdapter.mpileup_argv("bcftools", Path("r.fa"), Path("a.bam"), Path("o.bcf"),
                                        VariantParams(technology="pacbio_hifi"))
    assert "-D" in hifi and hifi[hifi.index("-M") + 1] == "99999" and hifi[hifi.index("-o") + 1] == "25"
    ill = BcftoolsAdapter.mpileup_argv("bcftools", Path("r.fa"), Path("a.bam"), Path("o.bcf"), VariantParams())
    assert "-B" not in ill and "-I" not in ill and ill[ill.index("-q") + 1] == "60" and ill[ill.index("-Q") + 1] == "13"
    assert ill[ill.index("-d") + 1] == "1000"
    assert set(flags_used(ont)["mpileup"]) >= {"-B", "-I"} and "-D" not in flags_used(ont)["mpileup"]
    assert BcftoolsAdapter.call_argv("bcftools", Path("p"), Path("c"), ont)[2:5] == ["--ploidy", "1", "-m"]


def test_params_validation_and_defaults():
    p = VariantParams()
    p.validate()
    assert (p.min_qual, p.min_depth, p.min_alt_fraction, p.min_mapq) == (100.0, 10, 0.9, 60)
    assert FILTER_DEFAULTS["min_mapq"] == 60
    for bad in ({"technology": "sanger"}, {"min_alt_fraction": 1.5}, {"max_depth": 5}, {"min_mapq": 61}):
        with pytest.raises(ValueError):
            VariantParams(**bad).validate()
    names = [n for n, _ in filter_expressions(p)]
    assert names == ["LowQual", "LowDepth", "LowAltFraction"]


def test_read_group_line_is_validated():
    assert read_group_line("job1", "S_1") == "@RG\\tID:job1\\tSM:S_1"
    with pytest.raises(ValueError):
        read_group_line("job1", "bad\tname")
    argv = BwaAdapter.mem_argv("bwa", Path("ref"), [Path("1.fq")], 2, read_group="@RG\\tID:a\\tSM:b")
    assert argv[argv.index("-R") + 1] == "@RG\\tID:a\\tSM:b"


def _revcomp(s: str) -> str:
    return s.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def _simulated(tmp: Path) -> tuple[Path, list[dict], list[tuple], str]:
    rng = random.Random(7)
    codons = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT" if a + b + c not in ("TAA", "TAG", "TGA")]
    body = "".join(rng.choice("ACGT") for _ in range(30000))
    gene_a = "ATG" + "".join(rng.choice(codons) for _ in range(98)) + "TAA"
    gene_b = "GTG" + "".join(rng.choice(codons) for _ in range(98)) + "TAG"
    ref = body[:1000] + gene_a + body[1300:5000] + _revcomp(gene_b) + body[5300:]
    (tmp / "ref.fa").write_text(">chr1 SIMULATED constructed genome\n" +
                                "\n".join(ref[i:i + 60] for i in range(0, len(ref), 60)) + "\n")
    alt = list(ref)
    truth = []
    for pos in (1010, 1150, 5300, 8000, 12000, 20000):
        new = next(b for b in "ACGT" if b != ref[pos - 1])
        alt[pos - 1] = new
        truth.append((pos, ref[pos - 1], new))
    alt[15000 - 1] = ref[15000 - 1] + "GA"
    truth.append((15000, ref[14999], ref[14999] + "GA"))
    del alt[25000:25003]
    truth.append((25000, ref[24999:25003], ref[24999]))
    features = [{"id": 1, "type": "cds", "contig": "chr1", "start": 1001, "end": 1300, "strand": "+",
                 "locus_tag": "SIM_1", "gene": "geneA"},
                {"id": 2, "type": "cds", "contig": "chr1", "start": 5001, "end": 5300, "strand": "-",
                 "locus_tag": "SIM_2", "gene": "geneB"}]
    return tmp / "ref.fa", features, truth, "".join(alt)


def _pairs(seq: str, tmp: Path, n: int = 3000, length: int = 150) -> list[Path]:
    rng = random.Random(11)
    r1, r2 = tmp / "SIMULATED_R1.fastq.gz", tmp / "SIMULATED_R2.fastq.gz"
    with gzip.open(r1, "wt") as f1, gzip.open(r2, "wt") as f2:
        for i in range(n):
            size = int(rng.gauss(350, 30))
            s = rng.randint(0, len(seq) - size)
            frag = seq[s:s + size]
            f1.write(f"@SIMULATED_{i}/1\n{frag[:length]}\n+\n{'I' * length}\n")
            f2.write(f"@SIMULATED_{i}/2\n{_revcomp(frag)[:length]}\n+\n{'I' * length}\n")
    return [r1, r2]


def _long(seq: str, tmp: Path, n: int = 200, length: int = 6000) -> Path:
    rng = random.Random(13)
    out = tmp / "SIMULATED_long.fastq.gz"
    with gzip.open(out, "wt") as fh:
        for i in range(n):
            s = rng.randint(1000 - length, len(seq) - 1000)
            read = seq[max(0, s):s + length]
            read = _revcomp(read) if i % 2 else read
            fh.write(f"@SIMULATED_long_{i}\n{read}\n+\n{'5' * len(read)}\n")
    return out


def _call(tmp: Path, bcftools: str, ref: Path, bam: Path, p: VariantParams, gff: Path | None) -> list[dict]:
    log = tmp / "bcftools.log"
    steps = [BcftoolsAdapter.mpileup_argv(bcftools, ref, bam, tmp / "pileup.bcf", p),
             BcftoolsAdapter.call_argv(bcftools, tmp / "pileup.bcf", tmp / "calls.bcf", p),
             BcftoolsAdapter.norm_argv(bcftools, ref, tmp / "calls.bcf", tmp / "norm.bcf")]
    src = tmp / "norm.bcf"
    exprs = filter_expressions(p)
    for i, (name, expr) in enumerate(exprs):
        out = tmp / ("filtered.vcf.gz" if i == len(exprs) - 1 else f"f{i}.bcf")
        steps.append(BcftoolsAdapter.filter_argv(bcftools, name, expr, src, out, add=i > 0,
                                                 compressed=i == len(exprs) - 1))
        src = out
    if gff is not None:
        steps.append(BcftoolsAdapter.csq_argv(bcftools, ref, gff, src, tmp / "csq.vcf.gz"))
        src = tmp / "csq.vcf.gz"
    steps.append(BcftoolsAdapter.index_argv(bcftools, src))
    for argv in steps:
        run_command(argv, cwd=tmp, stderr_path=log)
    assert (src.parent / f"{src.name}.tbi").is_file()
    with gzip.open(src, "rt") as fh:
        samples, rows = av.parse_vcf(fh)
    assert samples == ["SIM"]
    return rows


def test_short_reads_bwa_bcftools_csq_recover_planted_variants(tmp_path):
    bwa, samtools, bcftools = tool("bwa"), tool("samtools"), tool("bcftools")
    ref, features, truth, alt = _simulated(tmp_path)
    reads = _pairs(alt, tmp_path)
    run_command(SamtoolsAdapter.faidx_argv(samtools, ref), cwd=tmp_path, stderr_path=tmp_path / "faidx.log")
    run_command(BwaAdapter.index_argv(bwa, ref, tmp_path / "ref"), cwd=tmp_path, stderr_path=tmp_path / "idx.log")
    run_command(BwaAdapter.mem_argv(bwa, tmp_path / "ref", reads, 2, read_group_line("t", "SIM")), cwd=tmp_path,
                stderr_path=tmp_path / "bwa.log", stdout_path=tmp_path / "aln.sam.gz")
    bam = tmp_path / "aln.bam"
    run_command(SamtoolsAdapter.sort_argv(samtools, tmp_path / "aln.sam.gz", bam, 2, tmp_path / "s"), cwd=tmp_path,
                stderr_path=tmp_path / "sort.log")
    run_command(SamtoolsAdapter.index_argv(samtools, bam), cwd=tmp_path, stderr_path=tmp_path / "index.log")
    lengths = {"chr1": sum(len(x) for x in ref.read_text().split("\n")[1:])}
    text, counts = av.csq_gff(features, {}, lengths)
    assert counts["written"] == 2
    (tmp_path / "csq.gff3").write_text(text)
    rows = _call(tmp_path, bcftools, ref, bam, VariantParams(threads=2), tmp_path / "csq.gff3")
    called = {(r["pos"], r["ref"], r["alt"]): r for r in rows}
    # The 3-bp deletion after 25000 is left-aligned by `bcftools norm` to its leftmost equivalent position.
    deletion = next(r for r in rows if r["type"] == "deletion")
    assert len(deletion["ref"]) - len(deletion["alt"]) == 3 and deletion["pos"] <= 25000
    for t in truth[:-1]:
        assert t in called, t
    assert called[truth[0]]["effect"] == "missense" and called[truth[1]]["effect"] == "synonymous"
    # geneB starts with GTG on the minus strand: csq translates it with the standard code (V), not as a start.
    minus = called[truth[2]]
    assert minus["consequences"][0]["aa_change"].startswith("1V>")
    seq = "".join(ref.read_text().split("\n")[1:])
    av.start_codon_notes(rows, features, {}, {"chr1": seq})
    assert minus["start_codon"] == "GTG"
    assert all(r["pass"] for r in rows if (r["pos"], r["ref"], r["alt"]) in truth[:-1])
    run_command(SamtoolsAdapter.filtered_depth_argv(samtools, bam, 60, 13), cwd=tmp_path,
                stderr_path=tmp_path / "depth.log", stdout_path=tmp_path / "depth.tsv")
    with open(tmp_path / "depth.tsv") as fh:
        low = av.low_depth_intervals(av.parse_depth(fh), 10)
    assert low["contigs"]["chr1"]["positions"] == lengths["chr1"]
    assert low["intervals"]["chr1"][0][0] == 1


def test_long_reads_minimap2_ont_profile_calls_snps_only(tmp_path):
    minimap2, samtools, bcftools = tool("minimap2"), tool("samtools"), tool("bcftools")
    ref, _, truth, alt = _simulated(tmp_path)
    reads = _long(alt, tmp_path)
    run_command(SamtoolsAdapter.faidx_argv(samtools, ref), cwd=tmp_path, stderr_path=tmp_path / "faidx.log")
    run_command(Minimap2Adapter.argv(minimap2, "map-ont", 2, ref, reads, None, sam=True,
                                     read_group=read_group_line("t", "SIM")),
                cwd=tmp_path, stderr_path=tmp_path / "mm.log", stdout_path=tmp_path / "aln.sam.gz")
    bam = tmp_path / "aln.bam"
    run_command(SamtoolsAdapter.sort_argv(samtools, tmp_path / "aln.sam.gz", bam, 2, tmp_path / "s"), cwd=tmp_path,
                stderr_path=tmp_path / "sort.log")
    run_command(SamtoolsAdapter.index_argv(samtools, bam), cwd=tmp_path, stderr_path=tmp_path / "index.log")
    rows = _call(tmp_path, bcftools, ref, bam, VariantParams(technology="ont", threads=2), None)
    called = {(r["pos"], r["ref"], r["alt"]) for r in rows if r["pass"]}
    snps = [t for t in truth if len(t[1]) == len(t[2]) == 1]
    assert set(snps) <= called
    assert not any(r["type"] in ("insertion", "deletion") for r in rows)
