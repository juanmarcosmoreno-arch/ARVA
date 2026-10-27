"""Sequence file format detection and transparent (de)compression."""
from __future__ import annotations

import enum
import gzip
import io
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

GZIP_MAGIC = b"\x1f\x8b"
SNIFF_BYTES = 4096


class SequenceFormat(str, enum.Enum):
    fastq = "fastq"
    fasta = "fasta"
    unknown = "unknown"


@dataclass(frozen=True)
class FormatInfo:
    format: SequenceFormat
    compressed: bool
    decompression_error: str | None = None


def is_gzip(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(2) == GZIP_MAGIC


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
