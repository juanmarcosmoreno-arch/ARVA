import gzip
from pathlib import Path

import pytest

from arva_core.formats import POD5_SIGNATURE, SequenceFormat, check_pod5, sniff_format

# Bytes 8-23 of a real POD5 file are a random section marker, then the embedded Arrow file ("ARROW1").
BODY = bytes(range(16)) + b"ARROW1\x00\x00" + b"\x00" * 64


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("data", [POD5_SIGNATURE * 2, POD5_SIGNATURE + BODY + POD5_SIGNATURE])
def test_complete_pod5_is_recognised_by_both_signatures(tmp_path, data):
    check = check_pod5(write(tmp_path, "run.pod5", data))
    assert check is not None and check.is_complete
    assert "complete" in check.message


@pytest.mark.parametrize(
    "data",
    [
        POD5_SIGNATURE,
        POD5_SIGNATURE + b"\x00" * 7,
        POD5_SIGNATURE + BODY,
        POD5_SIGNATURE + BODY + POD5_SIGNATURE[:-1],
    ],
    ids=["signature_only", "under_16_bytes", "no_end_signature", "end_signature_cut"],
)
def test_truncated_pod5_is_pod5_but_incomplete(tmp_path, data):
    check = check_pod5(write(tmp_path, "run.pod5", data))
    assert check is not None and not check.is_complete
    assert check.message == "Incomplete or truncated POD5 — the end signature is missing; copy the file again."


def test_content_decides_not_the_extension(tmp_path):
    fastq_gz = gzip.compress(b"@r1\nACGT\n+\nIIII\n")
    renamed = write(tmp_path, "reads.pod5", fastq_gz)
    assert check_pod5(renamed) is None
    assert sniff_format(renamed).format is SequenceFormat.fastq
    assert check_pod5(write(tmp_path, "signal.fastq.gz", POD5_SIGNATURE * 2)) is not None


@pytest.mark.parametrize(
    "data",
    [b"", POD5_SIGNATURE[:7], b"\x8bPOD\n\x1a\n" + POD5_SIGNATURE, b"\x00" + POD5_SIGNATURE * 2],
    ids=["empty", "partial_signature", "line_endings_converted", "shifted"],
)
def test_other_content_is_not_pod5(tmp_path, data):
    assert check_pod5(write(tmp_path, "x.pod5", data)) is None


def test_pod5_is_not_a_sequence_format(tmp_path):
    info = sniff_format(write(tmp_path, "run.pod5", POD5_SIGNATURE + BODY + POD5_SIGNATURE))
    assert info.format is SequenceFormat.unknown and not info.compressed
