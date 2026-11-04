# Web test data for the Sanger screens

`sanger-3100.json` is built by `build_fixture.py` (run from the repository root with
`apps/api/.venv/bin/python -I apps/web/src/test/fixtures/sanger/build_fixture.py`) from public data only:

* `scientific-core/tests/fixtures/sanger/3100.ab1`, copied unchanged from the Biopython 1.88 source distribution
  (`Tests/Abi/`; see that folder's README for the SHA-256). Biopython's files are under the Biopython License
  Agreement, which permits copying and redistribution with its notice: `BIOPYTHON_LICENSE.rst` here.
* `workflows/tool-adapters/tests/fixtures/sanger/3100_trimmed_vs_16S_ribosomal_RNA.tsv`, the real blastn output of
  the trimmed 3100.ab1 read against NCBI's 16S database (build 2026-10-29; that folder's README).

It holds what the API returns for that read, computed with `arva_core.sanger`: the read with its default trimming
and mixed peaks, two chromatogram views (`trace_view`), a forward + reverse consensus with two substitutions (the
reverse read built from 3100.ab1's own calls, as in `scientific-core/tests/test_sanger.py`), and the ranking, 16S
reading and suspicion comparisons of the BLAST rows. No read of any ARVA user is used.
