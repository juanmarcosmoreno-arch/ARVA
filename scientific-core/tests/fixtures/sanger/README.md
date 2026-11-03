# Sanger fixtures — public chromatograms from Biopython's test data

The three `.ab1` files are copied unchanged from the Biopython 1.88 source distribution (`biopython-1.88.tar.gz`,
19,858,058 bytes, SHA-256 `9aaa31c0bda4d059f7b2ee00bfdb5cbb73ade3057aa4b737a7cc0187091d071a`, from
`https://files.pythonhosted.org/packages/source/b/biopython/biopython-1.88.tar.gz`), folder `Tests/Abi/`. Biopython's
files are under the Biopython License Agreement unless a file header says otherwise, which permits copying and
redistribution with its copyright and permission notice: that notice is `BIOPYTHON_LICENSE.rst` here (the sdist's
`LICENSE.rst`, unchanged).

| File | What it is | SHA-256 |
| --- | --- | --- |
| `3100.ab1` | ABI 3100, KB basecaller 1.4.1.8, sample `16S_S2_1387R`: a 16S rRNA read with primer 1387R, 795 bases, 10,303 scans | `78588d824dd967a1e58a9667a8f7ca1687ba38266420bbc5a6562c1893888efd` |
| `310.ab1` | ABI 310, 868 bases, every quality (`PCON2`) 0 | `0a395d39520d24a89af4c77dd55fd7fb632e732a6da807ceb6ead0c2465cb887` |
| `fake.ab1` | 26 bytes of text, not an ABIF file | `86d9ee4daee09fdcd74f8bb53b43cf5a3ed48633816f6d25892c193d99caaea6` |

Values the tests rely on, measured with Biopython 1.88 and `arva_core.sanger`:

* `3100.ab1`: `FWO_1` is `GATC`; at bases 21 to 580 the highest of the four channels at the base's `PLOC2` scan is
  the called base at all 560 positions. Modified Mott trimming at 0.05 keeps bases 19-697 (679 bases, mean Q 53.0,
  97.8 % of bases at Q20 or more); Biopython's `"abi-trim"` keeps 678 bases from base 19 (it drops the base where the
  running sum is highest).
* `310.ab1`: no usable qualities, so it is not quality-trimmed.

There is no public forward/reverse pair in Biopython's set. The consensus tests build one from `3100.ab1`: two
overlapping slices of its trimmed read, the second reverse-complemented as a reverse read would be, with the
substitutions and deletion each test names (tests/test_sanger.py, `pair`).

No read of any ARVA user is here or anywhere in the repository.
