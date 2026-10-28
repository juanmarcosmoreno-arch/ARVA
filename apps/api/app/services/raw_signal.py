"""POD5 raw-signal files: the optional pod5 library and the rule that read-level analyses never use them.

The library is only imported by the worker task; here it is detected from package metadata.
"""
from __future__ import annotations

from importlib import metadata

from app.models import FileFormat, RawFile

POD5_VERSION = "0.3.49"
POD5_INSTALL = f'pip install "pod5=={POD5_VERSION}"'
POD5_LIBRARY = {
    "id": "pod5",
    "name": "pod5",
    "homepage": "https://software-docs.nanoporetech.com/pod5/latest/",
    "license": "MPL-2.0",
    "citation": "Oxford Nanopore Technologies. POD5 file format specification (pod5-file-format 0.3.49).",
    "citation_url": "https://raw.githubusercontent.com/nanoporetech/pod5-file-format/0.3.49/docs/SPECIFICATION.md",
    "required_version": POD5_VERSION,
    "install": POD5_INSTALL,
}


def installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def pod5_versions() -> dict[str, str | None]:
    return {"pod5": installed_version("pod5"), "lib_pod5": installed_version("lib_pod5")}


def not_reads_message(f: RawFile, analysis: str) -> str:
    return (
        f"{f.original_filename} is a POD5 raw-signal file and holds no reads, so {analysis} cannot use it. "
        "Basecall it outside ARVA (for example with Dorado), then import the FASTQ."
    )


def is_raw_signal(f: RawFile) -> bool:
    return f.file_format is FileFormat.pod5
