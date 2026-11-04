"""Builds sanger-3100.json, the data the web tests show, from Biopython 1.88's public chromatogram 3100.ab1
(scientific-core/tests/fixtures/sanger/README.md) with ARVA's own scientific core, in the shapes the API returns.

Run from the repository root:  apps/api/.venv/bin/python -I apps/web/src/test/fixtures/sanger/build_fixture.py

The pair is built as the core tests build it (scientific-core/tests/test_sanger.py): bases 19-697 of 3100.ab1 as
the forward read, and bases 200-697 with two substitutions (300, 450), reverse-complemented, as the reverse read,
both keeping 3100.ab1's own qualities. The 16S results are the real blastn output of the trimmed read against NCBI's
16S database (workflows/tool-adapters/tests/fixtures/sanger/3100_trimmed_vs_16S_ribosomal_RNA.tsv, its README) read
as app.tasks.sanger reads it. No read of any ARVA user is used.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO / "scientific-core"))
sys.path.insert(0, str(REPO / "workflows" / "tool-adapters"))
from arva_core import sanger as core
from arva_tools.blast import parse_tabular

FX = REPO / "scientific-core" / "tests" / "fixtures" / "sanger" / "3100.ab1"
OUT = Path(__file__).with_name("sanger-3100.json")
SWAP = {"A": "C", "C": "G", "G": "T", "T": "A"}

read = core.read_abi(FX, name="16S_S2_1387-F")
trimmed = core.trim_read(read, 0.05)
mixed = core.mixed_peaks(read, 0.33)
lo, hi = trimmed.trim["start"], trimmed.trim["end"]
for m in mixed:
    m["kept"] = lo <= m["position"] <= hi
overview = core.trace_view(read, 0, None, 600)
window = core.trace_view(read, 2000, 3200, 400)

# The reverse read: a slice of the calls with two substitutions, reverse-complemented, as if read from the other end.
piece = replace(read, bases=read.bases[199:697], qualities=read.qualities[199:697], peaks=read.peaks[199:697],
                origin=list(range(199, 697)), name="16S_S2_27-R")
bases = list(piece.bases)
for pos in (300, 450):
    bases[pos - 200] = SWAP.get(bases[pos - 200], "A")
piece = replace(piece, bases="".join(bases))
reverse = core.reverse_complement(piece)
reverse = replace(reverse, origin=list(range(len(reverse))), peaks=None, traces=None, strand="+")
consensus = core.consensus(trimmed, reverse, core.ConsensusParams())

BLAST = REPO / "workflows" / "tool-adapters" / "tests" / "fixtures" / "sanger" / "3100_trimmed_vs_16S_ribosomal_RNA.tsv"
SOURCE = {"source": "ncbi_16s", "kind": "ncbi_16s", "key": "ncbi-16s", "name": "NCBI 16S ribosomal RNA (type strains)",
          "version": "2026-10-29", "version_source": "file", "checksum": None, "database_id": "db-16s"}


def name_16s(h):
    p = core.parse_16s_title(h.get("stitle") or "")
    return {"species": p["species"], "genus": p["genus"], "strain": p["strain"], "subspecies": p["subspecies"],
            "organism": p["organism"], "accession": core.ncbi_accession(h["sseqid"])}


rows = core.hits_from_hsps(parse_tabular(BLAST.read_text(), titles=True), SOURCE, name_16s)


def suspicion(value, kind):
    return {**core.compare_suspected(rows, value, kind), "searched": ["ncbi_16s"], "pending": 0, "caveats": []}

ranked = core.rank_hits(rows)
keep = ("rank", "tied_with_best", "source", "subject", "title", "gene", "species", "genus", "strain", "product",
        "accession", "identity", "identical", "query_coverage", "subject_coverage", "aligned_length", "query_start",
        "query_end", "query_length", "subject_start", "subject_end", "subject_length", "strand", "kind", "evalue",
        "bitscore", "copies")
results = {
    "ranked": [{k: r.get(k) for k in keep if k in r} for r in ranked[:12]], "ranked_count": len(ranked),
    "tied_with_best": sum(1 for r in ranked if r.get("tied_with_best")),
    "interpretation_16s": core.interpret_16s(rows),
    # As app.services.sanger._suspicion returns them: with the sources searched, the searches still running and the
    # caveats (none here: the best hit is a 16S hit and no genome of the sample was searched).
    "suspected_species": suspicion("Staphylococcus epidermidis", "species"),
    "suspected_abbreviated": suspicion("S. epidermidis", "species"),
    "suspected_genus": suspicion("Staphylococcus", "species"),
    "suspected_other": suspicion("Escherichia coli", "species"),
    "suspected_16s_gene": suspicion("16S rRNA", "gene"),
    "thresholds": {"clsi_16s": core.CLSI_16S, "gene": core.GENE_DEFAULTS}, "sources": core.SOURCES,
}

data = {
    "source": "Biopython 1.88 Tests/Abi/3100.ab1 (Biopython License Agreement); built by build_fixture.py",
    "read": {"name": read.name, "bases": read.bases, "qualities": read.qualities, "summary": read.summary(),
             "trim": trimmed.trim, "kept_bases": trimmed.bases, "mixed_peaks": mixed,
             "trim_source": core.SOURCES["trim"], "mixed_source": core.SOURCES["mixed_peaks"]},
    "overview": overview,
    "window": window,
    "consensus": {k: consensus[k] for k in ("status", "sequence", "length", "overlap", "counts", "conflicts",
                                             "warnings", "score")},
    "results": results,
}
OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
print(OUT, OUT.stat().st_size, "bytes;", "conflicts", len(consensus["conflicts"]), consensus["counts"])
