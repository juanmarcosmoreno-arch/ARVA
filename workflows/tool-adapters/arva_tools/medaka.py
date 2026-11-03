"""Medaka — consensus polishing of an Oxford Nanopore assembly with a neural network trained for the reads'
basecaller model.

Verified against Medaka 2.1.1 (Bioconda package medaka-2.1.1 build 1, ARVA's lock docker/conda-locks/medaka/): the
output of `medaka_consensus -h`, `medaka tools list_models` and `medaka tools resolve_model -h`
(tests/fixtures/medaka), the package's README (its dist-info METADATA), its sources (medaka/options.py,
medaka/models.py, medaka/stitch.py, bin/medaka_consensus) and real runs on the synthetic genome:

* `medaka_consensus -i <reads> -d <draft.fasta> -o <dir> -m <model> -t <threads> -b <batch size>` aligns the reads to
  the draft (mini_align, "a thin veil over minimap2"), runs `medaka inference` and stitches the consensus with
  `medaka sequence` into <dir>/consensus.fasta. It is a bash script that runs `medaka`, `mini_align`, `python`,
  `samtools` and `minimap2` by name, so ARVA puts the environment's bin/ first on its PATH; it checks their versions
  first (`medaka_version_report`, a table "Program Version Required Pass").
* It writes the draft's .fai and .map-ont.mmi indexes next to the draft file (that is, into the draft's folder), so
  ARVA gives it a copy of the draft in the job's work folder.
* Models: "For best results it is important to specify the correct inference model, according to the basecaller
  used" (README). medaka/options.py maps basecaller model names to Medaka models (`basecaller_models`, e.g.
  dna_r10.4.1_e8.2_400bps_sup@v5.2.0 → r1041_e82_400bps_sup_v5.2.0) and lists the models "included in PyPI
  packages" (`current_models`); the Bioconda package also ships exactly those four files in medaka/data/
  (<model>_model_pt.tar.gz, the suffix of medaka/models.py): r1041_e82_400bps_hac_v5.2.0, r1041_e82_400bps_sup_v5.2.0
  and their two variant-calling models. Any other model is downloaded by medaka on first use (models.resolve_model)
  from https://github.com/nanoporetech/medaka/raw/master/medaka/data/<file>, the repository's master branch, with no
  checksum, into medaka/data or ~/.medaka/data. ARVA offers only the consensus models the package ships, whose
  files conda records with their sha256 (conda-meta/medaka-*.json) inside a package pinned by its own sha256 in the
  lock; it never lets medaka download one. -m receives the model name; resolve_model finds the file in the package
  before trying any download, and ARVA checks the log's "Using model: <file>" afterwards.
* The model for the reads comes from medaka's own mapping applied to the basecall model ARVA read from the FASTQ
  headers (the RG:Z read group or basecall_model_version_id, the same fields medaka's _model_from_fastq reads).
  Without -m medaka_consensus would try the same automatically and fall back to its default model with only a
  warning; ARVA always passes -m with the model it shows the user.
* 'fast' basecaller models are not supported by medaka (models.resolve_model). The bacterial methylation research
  model (--bacteria, r1041_e82_400bps_bacterial_methylation) is not in the package: ARVA does not offer --bacteria.
* -t is used for the alignment, the inference and the stitching. README: "It is not recommended to specify a value
  of --threads greater than 2 for medaka inference since the compute scaling efficiency is poor beyond this" and
  inference "may been seen to use resources equivalent to <threads> + 4". -b (batch size, default 100) "controls
  memory use".
* Medaka "has been trained to correct draft sequences output from the Flye assembler" and "should be used directly
  on the output of Flye" (README), once.
* With gap filling (the default) every draft contig keeps its name: regions without enough aligned reads are copied
  from the draft, listed in <dir>/consensus.fasta.gaps_in_draft_coords.bed (contig, start, end; 0-based, end
  exclusive) and, for a contig with no read at all, logged as "Copying contig '<name>' verbatim from input."
  (medaka/stitch.py). The order of the contigs in consensus.fasta can differ from the draft's (seen once with -t 2
  on the synthetic genome: contig_2 first, cause not investigated); ARVA keeps medaka's order and matches contigs
  by name.
* On the synthetic genome (100 kb chromosome and 8 kb plasmid, Nanopore-like reads at 30x, a draft with 7
  substitutions and 12 indel bases) one run with r1041_e82_400bps_sup_v5.2.0 corrected every edit (MUMmer dnadiff:
  0 SNPs, 0 indels against the reference). The synthetic reads' errors are random, not a basecaller's; this checks
  ARVA's handling, not medaka's accuracy on real data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from arva_tools.base import ToolAdapter, ToolInfo, help_options, read_help
from arva_tools.runner import SIGKILL_STATUSES, isolated_home, tool_environment

# medaka/models.py: model_suffixes = ["_model_pt.tar.gz", ]
MODEL_SUFFIX = "_model_pt.tar.gz"
DEFAULT_BATCH_SIZE = 100
FLAGS = ("-i", "-d", "-o", "-m", "-t", "-b")
OUTPUT_DIR = "medaka"
CONSENSUS = "consensus.fasta"
GAPS_BED = "consensus.fasta.gaps_in_draft_coords.bed"
STAGES = ("versions", "alignment", "inference", "consensus")
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.]{0,120}")
_READ_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fastq|fq)(\.gz)?")
_FASTA_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(fasta|fa)")
_CHOICES = re.compile(r"Choices:\s*(.+?)\n\s*Alternatively", re.S)
_VERSION_ROW = re.compile(r"^(\w+)\s+(\S+)\s+(\S+)\s+(True|False)\s*$", re.M)
_USING_MODEL = re.compile(r"Using model: (\S+?)\.?\s*$", re.M)
_VERBATIM = re.compile(r"Copying contig '(.+?)' verbatim from input\.")
_WRITTEN = re.compile(r"Polished assembly written to (\S+), have a nice day\.")
_PY_ERROR = re.compile(r"^(?:\w+\.)*\w*(?:Error|Exception): .+$", re.M)
_STAGE_LINES = (("Checking program versions", "versions"), ("Aligning basecalls to draft", "alignment"),
                ("Running medaka inference", "inference"), ("Finished processing all regions", "consensus"))

# Read in the environment's own Python (-I: no user site, no PYTHONPATH, not the current folder). medaka/options.py
# imports only the standard library ("this module is imported into setup.py, so do not use any non-stdlib packages").
_CATALOGUE_CODE = """
import json
import medaka
import medaka.options as o
print(json.dumps({
    "version": medaka.__version__,
    "default_consensus": o.default_models["consensus"],
    "current_models": list(o.current_models),
    "allowed_models": list(o.allowed_models),
    "deprecated_models": list(o.deprecated_models),
    "basecaller_models": {k: v[0] for k, v in o.basecaller_models.items()},
    "bacterial_model": o.bact_methyl_model,
    "data_dir": str(o.model_stores[0]),
}))
"""


@dataclass
class MedakaParams:
    model: str
    threads: int = 1
    batch_size: int = DEFAULT_BATCH_SIZE

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> MedakaParams:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def validate(self) -> None:
        errors = []
        whole = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
        if not isinstance(self.model, str) or not _MODEL_NAME.fullmatch(self.model):
            errors.append("model must be a Medaka model name")
        if not whole(self.threads) or not 1 <= self.threads <= 128:
            errors.append("threads must be between 1 and 128")
        if not whole(self.batch_size) or not 1 <= self.batch_size <= 1000:
            errors.append("batch_size must be between 1 and 1,000")
        if errors:
            raise ValueError("; ".join(errors))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def env_for(executable: str) -> dict[str, str]:
    """PATH with the environment's bin/ first: medaka_consensus runs medaka, mini_align, python, samtools, minimap2,
    bgzip and tabix by name."""
    return {"PATH": f"{Path(os.path.realpath(executable)).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def consensus_script(executable: str) -> Path:
    """medaka_consensus, installed next to medaka in the environment's bin/."""
    return Path(os.path.realpath(executable)).parent / "medaka_consensus"


def _python(executable: str) -> Path:
    return Path(os.path.realpath(executable)).parent / "python"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _conda_records(prefix: Path) -> dict[str, str]:
    """sha256 of each file of the medaka package as conda recorded it when installing (paths relative to the
    environment); empty when the environment has no conda-meta record (not a conda environment)."""
    out: dict[str, str] = {}
    for record in sorted((prefix / "conda-meta").glob("medaka-*.json")):
        try:
            meta = json.loads(record.read_text())
        except (OSError, ValueError):
            continue
        if meta.get("name") != "medaka":
            continue
        for p in (meta.get("paths_data") or {}).get("paths") or []:
            if p.get("_path") and p.get("sha256"):
                out[p["_path"]] = p["sha256"]
    return out


def read_catalogue(executable: str) -> dict[str, Any]:
    """Medaka's own model lists and basecaller mapping (medaka/options.py), and the consensus models its package
    ships, each with its file's sha256 and whether it matches conda's record of the package."""
    py = _python(executable)
    if not (py.is_file() and os.access(py, os.X_OK)):
        raise RuntimeError(f"{py} not found: ARVA reads Medaka's model list with its environment's Python")
    with isolated_home() as home:
        proc = subprocess.run([str(py), "-I", "-c", _CATALOGUE_CODE], capture_output=True, text=True, errors="replace",
                              timeout=60, env={**tool_environment(home), **env_for(executable)}, cwd=home,
                              stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"Medaka's model list could not be read: {proc.stderr.strip()[-300:]}")
    try:
        cat = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("Medaka's model list could not be read: not JSON") from exc
    data = Path(cat["data_dir"])
    prefix = Path(os.path.realpath(executable)).parent.parent
    records = _conda_records(prefix)
    bundled = []
    for name in cat["current_models"]:
        if "variant" in name or "snp" in name:  # medaka_consensus lists consensus models only (same filter)
            continue
        f = data / f"{name}{MODEL_SUFFIX}"
        if not f.is_file():
            continue
        digest = _sha256(f)
        try:
            recorded = records.get(str(f.resolve().relative_to(prefix.resolve())))
        except ValueError:
            recorded = None
        bundled.append({"name": name, "file": f.name, "sha256": digest, "size": f.stat().st_size,
                        "checksum": "unrecorded" if recorded is None else "matches_package" if recorded == digest
                        else "differs_from_package"})
    cat["bundled_models"] = bundled
    return cat


def offered_models(catalogue: dict[str, Any]) -> list[str]:
    """The consensus models ARVA lets Medaka use: shipped in the package, with a file conda's record vouches for."""
    return [m["name"] for m in catalogue.get("bundled_models") or [] if m["checksum"] == "matches_package"]


def model_for_basecaller(catalogue: dict[str, Any], basecall_models: list[str]) -> dict[str, Any]:
    """The Medaka consensus model medaka's own mapping gives for the reads' basecall model (from their headers).

    status: mapped (a model ARVA offers), mapped_not_bundled (medaka would download it), unknown_basecall_model (not
    in medaka's mapping), fast_unsupported, several_basecall_models, no_basecall_model."""
    models = sorted(set(basecall_models))
    out: dict[str, Any] = {"basecall_model": models[0] if len(models) == 1 else None, "basecall_models": models,
                           "model": None, "source": "medaka.options.basecaller_models"}
    if not models:
        return {**out, "status": "no_basecall_model"}
    if len(models) > 1:
        return {**out, "status": "several_basecall_models"}
    mapping = catalogue.get("basecaller_models") or {}
    model = mapping.get(models[0])
    if model is None:
        return {**out, "status": "fast_unsupported" if "_fast" in models[0] else "unknown_basecall_model"}
    return {**out, "model": model, "status": "mapped" if model in offered_models(catalogue) else "mapped_not_bundled"}


def help_choices(text: str) -> list[str]:
    """The model names `medaka_consensus -h` lists after "Choices:"."""
    m = _CHOICES.search(text)
    return m.group(1).split() if m else []


class MedakaAdapter(ToolAdapter):
    info = ToolInfo(
        id="medaka",
        name="Medaka",
        description="Consensus polishing of Oxford Nanopore assemblies (Flye's in particular) with a neural network "
        "trained for the reads' basecaller model; ARVA uses the models its package ships.",
        homepage="https://github.com/nanoporetech/medaka",
        license="MPL-2.0",
        citation="Oxford Nanopore Technologies. Medaka: sequence correction provided by ONT Research. "
        "https://github.com/nanoporetech/medaka",
        citation_url="https://github.com/nanoporetech/medaka",
        executable="medaka",
        categories=("polishing", "long reads"),
        input_formats=("fasta", "fastq", "fastq.gz"),
        output_formats=("fasta", "bed"),
        min_version="2.0.0",
        tested_versions=("2.1.1",),
        install={"conda_lock": "python3 scripts/conda_locks.py install medaka ~/.arva-tools/conda/medaka  # then "
                               "ARVA_TOOL_MEDAKA=~/.arva-tools/conda/medaka/bin/medaka"},
        conda_platforms=("linux-64", "linux-aarch64"),
    )
    # `medaka --version` prints "medaka 2.1.1".
    version_pattern = re.compile(r"^medaka (\d+\.\d+\.\d+)", re.M)

    def environment(self, executable: str) -> dict[str, str]:
        return env_for(executable)

    @staticmethod
    def help_text(executable: str) -> str:
        return read_help(str(consensus_script(executable)), ("-h",), env_for(executable))

    @staticmethod
    def argv(executable: str, params: MedakaParams, reads: Path, draft: Path, help_text: str,
             offered: list[str]) -> list[str]:
        """medaka_consensus for `draft` (a .fasta in the work folder) and `reads`, writing into OUTPUT_DIR there."""
        params.validate()
        if not _READ_NAME.fullmatch(reads.name):
            raise ValueError(f"unsafe or unrecognised read file name for Medaka: {reads.name}")
        if not _FASTA_NAME.fullmatch(draft.name):
            raise ValueError("Medaka needs the draft in a .fasta file")
        supported = help_options(help_text)
        if missing := [f for f in FLAGS if f not in supported]:
            raise ValueError(f"this Medaka version does not offer {', '.join(missing)} (not in medaka_consensus -h)")
        if params.model not in offered:
            raise ValueError(f"the model {params.model} is not one of the models this Medaka package ships "
                             f"({', '.join(offered) or 'none'})")
        if params.model not in help_choices(help_text):
            raise ValueError(f"medaka_consensus -h does not list the model {params.model}")
        return [str(consensus_script(executable)), "-i", str(reads), "-d", str(draft), "-o", OUTPUT_DIR,
                "-m", params.model, "-t", str(params.threads), "-b", str(params.batch_size)]

    @staticmethod
    def stage(line: str) -> str | None:
        for text, stage in _STAGE_LINES:
            if text in line:
                return stage
        return None

    @staticmethod
    def parse_log(text: str) -> dict[str, Any]:
        """What medaka_consensus reports: the program versions it checked, the model file it used, the contigs it
        copied from the draft unpolished, and whether it wrote the consensus."""
        text = text.replace("\r", "\n")
        programs = [{"program": p, "version": v, "required": r, "pass": ok == "True"}
                    for p, v, r, ok in _VERSION_ROW.findall(text)]
        used = _USING_MODEL.findall(text)
        return {"programs": programs, "model_files": sorted(set(used)), "verbatim_contigs": _VERBATIM.findall(text),
                "finished": bool(_WRITTEN.search(text))}

    @staticmethod
    def parse_gaps(text: str) -> dict[str, dict[str, Any]]:
        """consensus.fasta.gaps_in_draft_coords.bed → the draft regions Medaka copied unpolished, by contig."""
        out: dict[str, dict[str, Any]] = {}
        for n, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit() or int(parts[2]) < int(parts[1]):
                raise ValueError(f"line {n} is not <contig> <start> <end>: {line[:80]!r}")
            row = out.setdefault(parts[0], {"regions": [], "bases": 0})
            row["regions"].append([int(parts[1]), int(parts[2])])
            row["bases"] += int(parts[2]) - int(parts[1])
        return out

    @staticmethod
    def failure_reason(log: str, returncode: int | None, batch_size: int) -> str | None:
        log = log.replace("\r", "\n")
        failed = [p for p, v, r, ok in _VERSION_ROW.findall(log) if ok == "False"]
        if failed:
            return f"Medaka's program check failed for {', '.join(failed)} (version below what medaka requires)"
        if m := re.search(r"Model (\S+) is not compatible with (\S+)", log):
            return f"Medaka reports that the model {m.group(1)} is not compatible with the reads"
        if "could not be downloaded" in log or "is not installed and could not be installed" in log:
            return "Medaka tried to download a model that its package does not ship; ARVA uses only shipped models"
        killed = returncode in SIGKILL_STATUSES or re.search(r"^.*\bKilled\b", log, re.M) is not None
        if "Failed to run medaka inference." in log or killed:
            if killed:
                return (f"Medaka was stopped by the operating system during inference, most likely because the "
                        f"computer ran out of memory; a smaller batch size (-b, now {batch_size}) uses less memory")
            errors = _PY_ERROR.findall(log)
            return "Medaka's inference failed" + (f": {errors[-1].strip()}" if errors else "")
        if "Failed to run alignment of reads to draft." in log:
            return "Medaka could not align the reads to the draft (mini_align, minimap2)"
        if "Failed to stitch consensus chunks." in log:
            return "Medaka could not stitch the consensus (medaka sequence)"
        if "Invalid option" in log or "requires an argument" in log:
            return "medaka_consensus refused its options: " + (re.findall(r"^.*(?:Invalid option|requires an "
                                                                         r"argument).*$", log, re.M) or [""])[-1]
        return None
