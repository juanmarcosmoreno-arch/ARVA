"""The Flye job log line for the genome size must not fail when no assumed depth was given (regression: a run with
the sample's expected genome size failed with 'unsupported format string passed to NoneType.__format__')."""
from types import SimpleNamespace

from app.tasks.tools import flye_genome_size_basis_text


def basis(kind, depth=None):
    return flye_genome_size_basis_text(SimpleNamespace(genome_size_basis=kind, assumed_depth_x=depth))


def test_expected_genome_size_without_an_assumed_depth():
    assert basis("expected_genome_size") == "the sample's expected genome size"


def test_entered_and_missing_basis():
    assert basis("entered") == "entered by the user"
    assert basis(None) == "entered by the user"


def test_reads_over_depth_formats_the_depth():
    assert basis("reads_over_depth", 50.0) == "total read bases ÷ an assumed depth of 50×"
    assert basis("reads_over_depth", None) == "total read bases ÷ an assumed depth"
