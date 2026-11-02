"""MAFFT — multiple sequence alignment.

Verified against MAFFT 7.505 (Ubuntu mafft 7.505-1): `mafft --help` (fixtures/region/mafft_help_7.505.txt), the
`mafft` script's own argument parsing (--nuc, --amino) and real runs:

* `mafft [options] <in.fasta> > <out.fasta>`: the alignment goes to stdout, in input order (--reorder not passed),
  progress to stderr.
* Strategies named by the usage text: L-INS-i, "high accuracy (for <~200 sequences x <~2,000 aa/nt)",
  `--maxiterate 1000 --localpair`; FFT-NS-2, the default "high speed" strategy, `--retree 2 --maxiterate 0`.
  The gap penalties are MAFFT's defaults for the strategy (recorded with the version).
* --nuc / --amino fix the sequence type instead of MAFFT guessing it. --thread N sets the threads.
"""
from __future__ import annotations

import re
import subprocess

from arva_tools.base import ToolAdapter, ToolInfo
from arva_tools.runner import isolated_home, tool_environment

STRATEGIES = {"linsi": ("--localpair", "--maxiterate", "1000"), "fftns2": ("--retree", "2", "--maxiterate", "0")}
MOLECULES = {"nucleotide": "--nuc", "protein": "--amino"}
HELP_FLAGS = ("--maxiterate", "--localpair", "--thread", "--retree")
# The usage text's own limit for L-INS-i ("<~200 sequences").
LINSI_MAX_SEQUENCES = 200


class MafftAdapter(ToolAdapter):
    info = ToolInfo(
        id="mafft",
        name="MAFFT",
        description="Multiple sequence alignment (L-INS-i for accuracy, FFT-NS-2 for speed); ARVA aligns the copies of "
        "a gene found in several genomes before a gene tree.",
        homepage="https://mafft.cbrc.jp/alignment/software/",
        license="BSD-3-Clause",
        citation="Katoh K, Standley DM. MAFFT multiple sequence alignment software version 7: improvements in "
        "performance and usability. Mol Biol Evol 2013;30(4):772-780.",
        citation_url="https://doi.org/10.1093/molbev/mst010",
        executable="mafft",
        categories=("alignment", "phylogeny"),
        input_formats=("fasta",),
        output_formats=("fasta",),
        min_version="7.300",
        tested_versions=("7.505",),
        install={"apt": "mafft", "conda": "bioconda::mafft"},
    )
    # `mafft --version` prints "v7.505 (2022/Apr/10)".
    version_pattern = re.compile(r"v(\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        """`mafft --help` prints its usage to stderr and exits with status 1 (MAFFT 7.505)."""
        with isolated_home() as home:
            proc = subprocess.run([executable, "--help"], capture_output=True, text=True, errors="replace",
                                  timeout=60, env=tool_environment(home), cwd=home, stdin=subprocess.DEVNULL)
        text = proc.stdout + proc.stderr
        if proc.returncode not in (0, 1) or "MAFFT" not in text:
            raise RuntimeError(f"mafft --help exited with status {proc.returncode}")
        return text

    @staticmethod
    def missing_flags(help_text: str) -> list[str]:
        return [f for f in HELP_FLAGS if f not in help_text]

    @staticmethod
    def argv(executable: str, strategy: str, molecule: str, threads: int, fasta: str) -> list[str]:
        if strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
        if molecule not in MOLECULES:
            raise ValueError(f"molecule must be one of {', '.join(MOLECULES)}")
        if not 1 <= threads <= 256:
            raise ValueError("threads must be between 1 and 256")
        return [executable, MOLECULES[molecule], *STRATEGIES[strategy], "--thread", str(threads), fasta]
