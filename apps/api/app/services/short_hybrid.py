"""SPAdes and Unicycler requests: which file plays which role, what ARVA knows about each, and whether the reads
suit the assembler and the sample's sequencing technology.

Every check uses recorded evidence only (the sample's metadata, read-header summaries, ARVA read statistics) and
states its rule; a check never changes the files or the parameters the user chose.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from arva_tools import ToolStatus
from arva_tools.registry import detect
from arva_tools.spades import SpadesAdapter
from arva_tools.unicycler import UnicyclerAdapter, helper_paths, modes_available
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import FileFormat, RawFile, Sample, SequencingTechnology
from app.services.flye import CONFIDENT, LONG_READ_PLATFORMS, InputError, evidence
from app.services.raw_signal import is_raw_signal, not_reads_message

ROLES = ("r1", "r2", "unpaired", "long")
SHORT_ROLES = ("r1", "r2", "unpaired")
# Short-read platforms write reads of at most a few hundred bases; a longer read means the file holds long reads.
SHORT_READ_MAX_LENGTH = 1_000
SPADES_MAX_DEFAULT_GB = 250  # SPAdes' own default is min(250, available memory)
SPADES_OPTIONS = ("--isolate", "--careful", "-k", "--cov-cutoff", "-s")
UNICYCLER_OPTIONS = ("--kmers", "--depth_filter", "--linear_seqs", "--min_fasta_length", "--keep")
ROLE_NAMES = {"r1": "R1 (forward reads of the pairs)", "r2": "R2 (reverse reads of the pairs)",
              "unpaired": "unpaired short reads", "long": "long reads"}


@dataclass
class Inputs:
    """The files of one request by role (None when the role is not used)."""
    r1: RawFile | None = None
    r2: RawFile | None = None
    unpaired: RawFile | None = None
    long: RawFile | None = None

    def by_role(self) -> dict[str, RawFile]:
        return {r: f for r in ROLES if (f := getattr(self, r)) is not None}

    def files(self) -> list[RawFile]:
        return list(self.by_role().values())

    def ids(self) -> dict[str, str | None]:
        return {r: f.id if (f := getattr(self, r)) else None for r in ROLES}

    @property
    def short(self) -> bool:
        return self.r1 is not None or self.unpaired is not None

    def assembly_mode(self) -> str | None:
        if self.short and self.long:
            return "hybrid"
        return "short" if self.short else "long" if self.long else None


def library_layout(roles: dict[str, str | None]) -> str:
    """The reads' layout by role, stored as the assembly's read type, e.g. "paired-end + long"."""
    parts = (["paired-end"] if roles.get("r1") else []) + (["single-end"] if roles.get("unpaired") else []) + \
        (["long"] if roles.get("long") else [])
    return " + ".join(parts)


def resolve_inputs(db: Session, sample: Sample, ids: dict[str, str | None]) -> Inputs:
    chosen = {r: i for r, i in ids.items() if i}
    if len(set(chosen.values())) != len(chosen):
        raise InputError("The same file was given for more than one role")
    out = Inputs()
    for role, file_id in chosen.items():
        f = db.get(RawFile, file_id)
        if f is None or f.sample_id != sample.id:
            raise InputError(f"File {file_id} does not belong to this sample")
        setattr(out, role, f)
    return out


def file_evidence(db: Session, inputs: Inputs) -> list[dict[str, Any]]:
    by_role = inputs.by_role()
    ev = evidence(db, list(by_role.values()))
    for role, e in zip(by_role, ev, strict=True):
        e["role"] = role
    return ev


def _check_readable(f: RawFile, tool: str) -> None:
    if is_raw_signal(f):
        raise InputError(not_reads_message(f, tool))
    if f.file_format not in (FileFormat.fastq, FileFormat.fastq_gz):
        raise InputError(f"{f.original_filename} is not a FASTQ file; ARVA runs {tool} on FASTQ reads")
    if not f.is_valid:
        raise InputError(f"{f.original_filename} failed validation and cannot be assembled: {f.validation_message}")


def check_inputs(sample: Sample, inputs: Inputs, ev: list[dict[str, Any]], tool: str, confirmed: bool) -> None:
    """Raise InputError when the files cannot play their roles for `tool`, or contradict the sample's technology
    (an unknown technology needs the user's confirmation that the files hold what their roles say)."""
    if (inputs.r1 is None) != (inputs.r2 is None):
        raise InputError("Paired-end reads need both the R1 and the R2 file")
    if not inputs.short and not inputs.long:
        raise InputError(f"Choose the reads for {tool}")
    if tool == "SPAdes" and inputs.long:
        raise InputError("SPAdes assembles short reads; use Unicycler for long reads with short reads, or Flye")
    for f in inputs.files():
        _check_readable(f, tool)
    by_role = {e["role"]: e for e in ev}
    for role, mate in (("r1", "R2"), ("r2", "R1")):
        e = by_role.get(role)
        if e and e["read_mate"] == mate:
            raise InputError(f"{e['name']} is marked as read {mate} of a pair, so it cannot be the {ROLE_NAMES[role]}")
    for role in SHORT_ROLES:
        e = by_role.get(role)
        if e is None:
            continue
        if e["header_platform"] in LONG_READ_PLATFORMS and e["header_confidence"] in CONFIDENT:
            raise InputError(f"{e['name']}: its read headers identify {e['header_platform']} reads "
                             f"({e['header_confidence']} confidence), not short reads")
        if e["max_read_length"] is not None and e["max_read_length"] > SHORT_READ_MAX_LENGTH:
            raise InputError(f"{e['name']} holds reads up to {e['max_read_length']:,} bp (ARVA read statistics); "
                             f"short reads are at most {SHORT_READ_MAX_LENGTH:,} bp, so it cannot be the "
                             f"{ROLE_NAMES[role]}")
    pair = [by_role.get("r1"), by_role.get("r2")]
    if all(pair) and all(e["read_count"] is not None for e in pair) and pair[0]["read_count"] != pair[1]["read_count"]:
        raise InputError(f"{pair[0]['name']} has {pair[0]['read_count']:,} reads and {pair[1]['name']} "
                         f"{pair[1]['read_count']:,} (ARVA read statistics); the two files of a pair must hold the "
                         "same reads in the same order")
    if (e := by_role.get("long")) is not None:
        if e["read_mate"]:
            raise InputError(f"{e['name']} is marked as read {e['read_mate']} of a pair: paired-end files hold short "
                             "reads, not long reads")
        if e["header_platform"] == "illumina" and e["header_confidence"] in CONFIDENT:
            raise InputError(f"{e['name']}: its read headers identify Illumina reads ({e['header_confidence']} "
                             "confidence), not long reads")
        if e["max_read_length"] is not None and e["max_read_length"] <= SHORT_READ_MAX_LENGTH:
            raise InputError(f"{e['name']} has no read longer than {SHORT_READ_MAX_LENGTH:,} bp (ARVA read "
                             "statistics), so it cannot be the long reads")
    technology = sample.sequencing_technology
    if inputs.short and technology in (SequencingTechnology.nanopore, SequencingTechnology.pacbio):
        raise InputError(f"This sample's sequencing technology is '{technology.value}', but {tool} is given short "
                         "reads. Set the technology in the sample's metadata ('illumina', or 'hybrid' for short and "
                         "long reads of the same isolate)")
    if inputs.long and technology is SequencingTechnology.illumina:
        raise InputError(f"This sample's sequencing technology is 'illumina', but {tool} is given long reads. Set the "
                         "technology in the sample's metadata ('hybrid' for short and long reads of the same isolate)")
    if needs_confirmation(sample) and not confirmed:
        raise InputError(f"This sample's sequencing technology is '{technology.value}'. Set it in the sample's "
                         "metadata, or confirm that the selected files hold the reads their roles say")


def needs_confirmation(sample: Sample) -> bool:
    return sample.sequencing_technology is SequencingTechnology.unknown


def memory_options() -> dict[str, int]:
    cap = get_settings().max_tool_memory_gb
    return {"max_memory_gb": cap, "default_memory_gb": min(SPADES_MAX_DEFAULT_GB, cap)}


def _options(read_options, executable: str | None, wanted: tuple[str, ...]) -> list[str]:
    if not executable:
        return []
    try:
        supported = read_options(executable)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return []
    return [o for o in wanted if o in supported]


def spades_status() -> dict[str, Any]:
    d = detect("spades")
    available = d.status is ToolStatus.available
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason,
            "options": _options(SpadesAdapter.help_options, d.path if available else None, SPADES_OPTIONS),
            "max_threads": get_settings().tool_threads, **memory_options()}


def unicycler_status() -> dict[str, Any]:
    d = detect("unicycler")
    available = d.status is ToolStatus.available
    paths = helper_paths()
    spades = detect("spades")
    return {"status": d.status.value, "version": d.version, "version_validated": d.version_validated,
            "message": d.message, "reason": d.reason,
            "options": _options(UnicyclerAdapter.help_options, d.path if available else None, UNICYCLER_OPTIONS),
            "modes": modes_available(paths) if available else [],
            "helpers": {name: {"path": path, "version": spades.version if name == "spades" and path else None}
                        for name, path in paths.items()},
            "max_threads": get_settings().tool_threads, **memory_options()}


def plan(db: Session, sample: Sample, inputs: Inputs, tool: str) -> dict[str, Any]:
    """What ARVA knows before a run (nothing is run); input problems are listed, not raised, so the dialog can
    show them next to the choices."""
    ev = file_evidence(db, inputs)
    try:
        check_inputs(sample, inputs, ev, tool, confirmed=True)
        problem = None
    except InputError as exc:
        problem = str(exc)
    return {
        "tool": spades_status() if tool == "SPAdes" else unicycler_status(),
        "files": ev,
        "assembly_mode": inputs.assembly_mode(),
        "read_layout": library_layout(inputs.ids()),
        "problem": problem,
        "sample_technology": sample.sequencing_technology,
        "confirmation_required": needs_confirmation(sample),
    }
