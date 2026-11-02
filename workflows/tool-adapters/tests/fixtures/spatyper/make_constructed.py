"""Writes the CONSTRUCTED Ridom-format files and genomes in constructed/: three made-up 24-bp repeats (r91, r92, r93),
one made-up spa type (t9001 = 91-92-93) and three one-contig genomes. None of it is Ridom SpaServer data: it only
exercises spaTyper's file formats and ARVA's reading of its calls. Run: python3 make_constructed.py"""
import random
from pathlib import Path

OUT = Path(__file__).parent / "constructed"
rng = random.Random(9001)


def seq(n: int) -> str:
    return "".join(rng.choice("ACGT") for _ in range(n))


repeats = {"r91": seq(24), "r92": seq(24), "r93": seq(24)}
flank, junk = seq(300), seq(30)
OUT.mkdir(exist_ok=True)
(OUT / "sparepeats.fasta").write_text("".join(f">{k}\n{v}\n" for k, v in repeats.items()))
(OUT / "spatypes.txt").write_text("t9001,91-92-93\n")
r = repeats
genomes = {
    "typed": r["r91"] + r["r92"] + r["r93"],
    "new_succession": r["r93"] + r["r91"],
    "gap": r["r91"] + junk + r["r92"],
}
for name, core in genomes.items():
    (OUT / f"{name}.fasta").write_text(f">CONSTRUCTED_{name}\n{flank}{core}{flank}\n")
(OUT / "two_contigs.fasta").write_text(f">CONSTRUCTED_a\n{flank}{genomes['typed']}{flank}\n"
                                       f">CONSTRUCTED_b\n{flank}{genomes['new_succession']}{flank}\n")
(OUT / "lower_case.fasta").write_text(f">CONSTRUCTED_lower\n{(flank + genomes['typed'] + flank).lower()}\n")
