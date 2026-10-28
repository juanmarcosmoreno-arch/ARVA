"""Sequence file format detection and transparent (de)compression."""
from __future__ import annotations

import enum
import gzip
import io
import os
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

GZIP_MAGIC = b"\x1f\x8b"
SNIFF_BYTES = 4096
# POD5 specification, section "Signature": the first and the last eight bytes of every POD5 file.
POD5_SIGNATURE = b"\x8bPOD\r\n\x1a\n"
POD5_MIN_BYTES = 2 * len(POD5_SIGNATURE)


class SequenceFormat(str, enum.Enum):
    fastq = "fastq"
    fasta = "fasta"
    unknown = "unknown"


@dataclass(frozen=True)
class FormatInfo:
    format: SequenceFormat
    compressed: bool
    decompression_error: str | None = None


@dataclass(frozen=True)
class Pod5Check:
    is_complete: bool
    message: str


def is_gzip(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(2) == GZIP_MAGIC


def check_pod5(path: Path) -> Pod5Check | None:
    """None unless the content starts with the POD5 signature; then whether the end signature is present too."""
    with open(path, "rb") as fh:
        if fh.read(len(POD5_SIGNATURE)) != POD5_SIGNATURE:
            return None
        size = os.fstat(fh.fileno()).st_size
        if size >= POD5_MIN_BYTES:
            fh.seek(size - len(POD5_SIGNATURE))
            if fh.read(len(POD5_SIGNATURE)) == POD5_SIGNATURE:
                return Pod5Check(
                    True,
                    "POD5 raw-signal file: start and end signatures present, so the file is complete. "
                    "It holds nanopore signal, not reads: ARVA can read its run metadata; read "
                    "statistics need the basecalled FASTQ.",
                )
    return Pod5Check(
        False,
        "Incomplete or truncated POD5 — the end signature is missing; copy the file again.",
    )


def open_sequence_file(path: Path) -> BinaryIO:
    """Open a possibly gzip-compressed file for buffered binary reading.

    Compression is detected from the file's magic bytes, not its extension.
    """
    if is_gzip(path):
        return io.BufferedReader(gzip.open(path, "rb"), buffer_size=1 << 20)
    return open(path, "rb", buffering=1 << 20)


def sniff_format(path: Path) -> FormatInfo:
    """Identify FASTQ/FASTA from the first non-blank byte of the (decompressed) content."""
    compressed = is_gzip(path)
    try:
        # A small read decompresses only the first block, so a stream that is
        # truncated later is still identified (and reported as corrupt later).
        with (gzip.open(path, "rb") if compressed else open(path, "rb")) as fh:
            head = fh.read(SNIFF_BYTES)
    except (OSError, EOFError, zlib.error) as exc:
        return FormatInfo(SequenceFormat.unknown, compressed, str(exc) or type(exc).__name__)
    first = head.lstrip()[:1]
    if first == b"@":
        return FormatInfo(SequenceFormat.fastq, compressed)
    if first == b">":
        return FormatInfo(SequenceFormat.fasta, compressed)
    return FormatInfo(SequenceFormat.unknown, compressed)
