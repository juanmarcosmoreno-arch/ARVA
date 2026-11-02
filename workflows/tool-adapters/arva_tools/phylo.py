"""Gene trees from a multiple alignment: IQ-TREE (maximum likelihood with ModelFinder and ultrafast bootstrap) or
FastTree (approximate maximum likelihood with SH-like local supports).

Verified against IQ-TREE 3.0.1 (ARVA's Bioconda lock docker/conda-locks/iqtree) and FastTree 2.1.11 (Ubuntu fasttree
2.1.11-2): `iqtree3 -h`, `FastTree -expert` (fixtures/region) and real runs:

* IQ-TREE: `-s <aln> --seqtype DNA|AA -m MFP -B <n> -T <n> --seed <n> --prefix <p>`. -m MFP is ModelFinder Plus
  (model selection, by BIC, then the tree); -B is UFBoot, ">=1000" replicates. Writes <p>.treefile (Newick, UFBoot
  supports 0-100 as node labels), <p>.iqtree (report, "Best-fit model according to BIC: ...") and <p>.log.
  `--alrt <n>` adds the SH-aLRT test with n replicates; with -B as well each node is labelled "SH-aLRT/UFBoot".
  For alignments of variable sites only: `-m <model>+ASC` (ascertainment bias correction; IQ-TREE refuses it when a
  column is constant) or `-fconst a,c,g,t`, the counts of constant A, C, G and T columns left out, added back as
  constant patterns (the counts snp-sites -C prints). Without either, branch lengths are per variable site.
  IQ-TREE 3.0.1 aborts on `-m MFP+ASC` (an assertion in ModelFactory::initFromNestedModel during ModelFinder, with
  1 or 4 threads, on Panaroo's core SNPs; fixtures/phylogeny), while a stated model such as GTR+F+ASC+G4 runs; ARVA
  therefore asks for a stated model with +ASC. The .iqtree report may print counts in scientific notation
  ("Number of constant sites: 2.15527e+06").
  `-rf <tree> <tree2>` (not in the help text, present in 3.0.1) writes the Robinson-Foulds distance to <p>.rfdist;
  ARVA computes RF itself (arva_core.phylo) and the tests compare both.
* FastTree: `-nt -gtr -gamma` for nucleotides, `-lg -gamma` for proteins (the default is Jukes-Cantor / JTT);
  `-boot 1000` SH-like local supports (the default, passed explicitly; values 0-1); -seed; `-out <tree>`.
* Both refuse duplicate sequence names; ARVA names the sequences s1..sN and maps the names back (arva_core.newick).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, read_help

METHODS = ("iqtree", "fasttree")
SEQTYPES = {"nucleotide": "DNA", "protein": "AA"}
MIN_SEQUENCES = 4
IQTREE_FLAGS = ("-s", "--seqtype", "-m", "-B", "-T", "--seed", "--prefix", "--alrt", "-fconst", "+ASC")
CONSTANT_SITES = ("none", "fconst", "asc")
FASTTREE_FLAGS = ("-nt", "-gtr", "-gamma", "-lg", "-boot", "-seed", "-out")
_MODEL = re.compile(r"MFP|[A-Za-z0-9.]+(\+[A-Za-z0-9.]+)*")


@dataclass
class TreeParams:
    method: str = "iqtree"
    model: str = "MFP"
    ufboot: int = 1000
    seed: int = 12345
    threads: int = 1
    alrt: int = 0

    def validate(self) -> None:
        errors = []
        if self.method not in METHODS:
            errors.append(f"method must be one of {', '.join(METHODS)}")
        if self.method == "iqtree":
            if not _MODEL.fullmatch(self.model) or len(self.model) > 60:
                errors.append("model must be MFP or an IQ-TREE model name such as GTR+F+G4")
            if self.ufboot != 0 and not 1000 <= self.ufboot <= 100_000:
                errors.append("ufboot must be 0 (none) or between 1000 and 100000 (IQ-TREE needs >= 1000)")
            if self.alrt != 0 and not 1000 <= self.alrt <= 100_000:
                errors.append("alrt must be 0 (none) or between 1000 and 100000")
        if not 1 <= self.seed <= 2_147_483_647:
            errors.append("seed must be a positive integer")
        if not 1 <= self.threads <= 256:
            errors.append("threads must be between 1 and 256")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.method == "fasttree":
            for k in ("model", "ufboot", "alrt"):
                d.pop(k)
        return d


def missing_flags(method: str, help_text: str, flags: tuple[str, ...] | None = None) -> list[str]:
    return [f for f in (flags or (IQTREE_FLAGS if method == "iqtree" else FASTTREE_FLAGS)) if f not in help_text]


def _count(text: str) -> int:
    return round(float(text))


def parse_iqtree_report(text: str) -> dict[str, Any]:
    """From <prefix>.iqtree: the model (ModelFinder's BIC choice, or the one given), the log-likelihood and the
    alignment's size as IQ-TREE read it."""
    out: dict[str, Any] = {}
    for key, pattern, cast in (
            ("model", r"Best-fit model according to BIC:\s*(\S+)", str),
            ("model", r"Model of substitution:\s*(\S+)", str),
            ("log_likelihood", r"Log-likelihood of the tree:\s*(-?[\d.]+)", float),
            ("sequences", r"Input data:\s*(\d+) sequences", _count),
            ("sites", r"Input data:\s*\d+ sequences with (\d+)", _count),
            ("constant_sites", r"Number of constant sites:\s*([\d.e+]+)", _count),
            ("informative_sites", r"Number of parsimony informative sites:\s*([\d.e+]+)", _count),
            ("distinct_patterns", r"Number of distinct site patterns:\s*([\d.e+]+)", _count)):
        if key not in out and (m := re.search(pattern, text)):
            out[key] = cast(m.group(1))
    if "model" not in out:
        raise ValueError("the IQ-TREE report names no model")
    return out


class IqtreeAdapter(ToolAdapter):
    info = ToolInfo(
        id="iqtree",
        name="IQ-TREE",
        description="Maximum-likelihood phylogenies with ModelFinder model selection and ultrafast bootstrap; ARVA "
        "builds gene trees from the aligned copies of a gene.",
        homepage="https://iqtree.github.io",
        license="GPL-2.0",
        citation="Minh BQ, Schmidt HA, Chernomor O, et al. IQ-TREE 2: New models and efficient methods for "
        "phylogenetic inference in the genomic era. Mol Biol Evol 2020;37(5):1530-1534. (IQ-TREE 3 builds on it; "
        "iqtree.github.io lists how to cite version 3.)",
        citation_url="https://doi.org/10.1093/molbev/msaa015",
        executable="iqtree3",
        categories=("phylogeny",),
        input_formats=("fasta",),
        output_formats=("newick",),
        min_version="3.0",
        tested_versions=("3.0.1",),
        install={"conda": "bioconda::iqtree"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    # `iqtree3 --version` prints "IQ-TREE version 3.0.1 for Linux x86 64-bit ...".
    version_pattern = re.compile(r"IQ-TREE version (\d+\.\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("-h",))

    @staticmethod
    def argv(executable: str, params: TreeParams, molecule: str, alignment: str, prefix: str,
             fconst: tuple[int, int, int, int] | None = None) -> list[str]:
        params.validate()
        out = [executable, "-s", alignment, "--seqtype", SEQTYPES[molecule], "-m", params.model]
        if params.ufboot:
            out += ["-B", str(params.ufboot)]
        if params.alrt:
            out += ["--alrt", str(params.alrt)]
        if fconst is not None:
            if molecule != "nucleotide" or len(fconst) != 4 or any(c < 0 for c in fconst):
                raise ValueError("-fconst takes four non-negative counts (A, C, G, T) for nucleotides")
            if "+ASC" in params.model:
                raise ValueError("-fconst and +ASC are alternatives")
            out += ["-fconst", ",".join(str(c) for c in fconst)]
        return [*out, "-T", str(params.threads), "--seed", str(params.seed), "--prefix", prefix]

    @staticmethod
    def rf_argv(executable: str, tree_a: str, tree_b: str, prefix: str) -> list[str]:
        return [executable, "-rf", tree_a, tree_b, "--prefix", prefix]


class FasttreeAdapter(ToolAdapter):
    info = ToolInfo(
        id="fasttree",
        name="FastTree",
        description="Approximately-maximum-likelihood phylogenies with SH-like local supports; a fast alternative to "
        "IQ-TREE for gene trees.",
        homepage="http://www.microbesonline.org/fasttree/",
        license="GPL-2.0-or-later",
        citation="Price MN, Dehal PS, Arkin AP. FastTree 2 - approximately maximum-likelihood trees for large "
        "alignments. PLoS One 2010;5(3):e9490.",
        citation_url="https://doi.org/10.1371/journal.pone.0009490",
        executable="FastTree",
        categories=("phylogeny",),
        input_formats=("fasta",),
        output_formats=("newick",),
        min_version="2.1",
        tested_versions=("2.1.11",),
        install={"apt": "fasttree", "conda": "bioconda::fasttree"},
    )
    version_args = ("-help",)
    # `FastTree -help` starts with "FastTree 2.1.11 Double precision (No SSE3):".
    version_pattern = re.compile(r"FastTree (\d+\.\d+\.\d+)")

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(executable, ("-expert",))

    @staticmethod
    def argv(executable: str, params: TreeParams, molecule: str, alignment: str, out: str) -> list[str]:
        params.validate()
        model = ["-nt", "-gtr"] if molecule == "nucleotide" else ["-lg"]
        return [executable, *model, "-gamma", "-boot", "1000", "-seed", str(params.seed), "-out", out, alignment]
