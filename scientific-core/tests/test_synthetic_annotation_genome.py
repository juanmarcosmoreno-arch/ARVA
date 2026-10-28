"""scripts/make_synthetic_annotation_genome.py: planted ORFs, inserts, back-translations and reproducibility."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_synthetic_annotation_genome.py"
_spec = importlib.util.spec_from_file_location("make_synthetic_annotation_genome", SCRIPT)
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)

STOPS = {"TAA", "TAG", "TGA"}
CODE = {c: aa for aa, codons in gen.CODONS_OF.items() for c in codons}
SMALL = gen.Params(chromosome_genes=12, plasmid_genes=2)


def planted(path: Path) -> list[dict]:
    lines = [ln for ln in path.read_text().splitlines() if not ln.startswith("#")]
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"), strict=True)) for ln in lines[1:]]


def cds_of(genome: dict[str, str], f: dict) -> str:
    seq = genome[f["sequence"]][int(f["start"]) - 1:int(f["end"])]
    return seq if f["strand"] == "+" else gen.revcomp(seq)


def test_standard_code_table():
    assert len(CODE) == 64 and {c for c, aa in CODE.items() if aa == "*"} == STOPS
    assert CODE["ATG"] == "M" and CODE["TGG"] == "W" and len(gen.CODONS_OF["L"]) == 6


def test_planted_orfs_start_stop_and_have_no_internal_stop(tmp_path):
    gen.write(tmp_path, SMALL)
    genome = dict(gen.read_fasta(tmp_path / "genome.fasta"))
    assert all("SYNTHETIC" in h for h in (tmp_path / "genome.fasta").read_text().splitlines() if h.startswith(">"))
    orfs = [f for f in planted(tmp_path / "planted_features.tsv") if f["type"] == "orf"]
    assert len(orfs) == 14 and {f["strand"] for f in orfs} == {"+", "-"}
    for f in orfs:
        cds = cds_of(genome, f)
        codons = [cds[i:i + 3] for i in range(0, len(cds), 3)]
        assert codons[0] == "ATG" and codons[-1] in STOPS and not STOPS & set(codons[1:-1])
        upstream = genome[f["sequence"]][int(f["start"]) - 16:int(f["start"]) - 1] if f["strand"] == "+" else \
            gen.revcomp(genome[f["sequence"]][int(f["end"]):int(f["end"]) + 15])
        assert gen.RBS in upstream
    gap = next(f for f in planted(tmp_path / "planted_features.tsv") if f["type"] == "gap")
    assert genome[gap["sequence"]][int(gap["start"]) - 1:int(gap["end"])] == "N" * 100


def test_inserts_and_back_translations(tmp_path):
    protein = "MKVLAAGIRW"
    gen.write(tmp_path, SMALL, inserts=[("rna1", "ACGTTTGCA")], proteins=[("P1", protein)])
    genome = dict(gen.read_fasta(tmp_path / "genome.fasta"))
    rows = {f["id"]: f for f in planted(tmp_path / "planted_features.tsv")}
    assert cds_of(genome, rows["rna1"]) == "ACGTTTGCA"
    cds = cds_of(genome, rows["P1"])
    assert "".join(CODE[cds[i:i + 3]] for i in range(0, len(cds) - 3, 3)) == protein and cds[-3:] in STOPS


def test_reproducible_and_refuses_to_overwrite(tmp_path):
    a = gen.write(tmp_path / "a", SMALL)
    assert gen.write(tmp_path / "b", SMALL) == a
    with pytest.raises(FileExistsError):
        gen.write(tmp_path / "a", SMALL)
    assert gen.main([str(tmp_path / "c"), "--chromosome-genes", "3", "--plasmid-genes", "0"]) == 0
