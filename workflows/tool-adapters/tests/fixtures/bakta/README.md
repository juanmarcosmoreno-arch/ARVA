# Bakta fixtures — output on a SYNTHETIC genome, not biology

Written by Bakta 1.12.2 (PyPI wheel, Python 3.12.3, Ubuntu 24.04) with the Bakta light database 6.0, on
`../annotation_genome/genome.fna`, with the command ARVA builds:

```bash
PYTHONUNBUFFERED=1 bakta /work/input.fna --db /databases/bakta-light/6.0 --output /work/bakta --prefix annotation \
  --tmp-dir /work/bakta-tmp --threads 2 --min-contig-length 1 --translation-table 11 --locus-tag SYNT \
  --locus-tag-increment 1 --skip-cds --skip-sorf --skip-ori --skip-crispr > console.log
```

Steps skipped because this computer cannot run them (Bakta's own start-up checks, bakta/utils.py):

- CDS (`--skip-cds`): AMRFinderPlus (>= 4.2.7) is not installed, and DIAMOND 2.1.9 (Ubuntu) is older than 2.2.0;
- sORF (`--skip-sorf`): DIAMOND;
- oriC/oriT (`--skip-ori`): BLAST+ 2.12.0 (Ubuntu) is older than 2.17.0;
- CRISPR (`--skip-crispr`): Ubuntu's pilercr 1.06+dfsg-5 passes Bakta's version check but crashes (SIGSEGV) on every
  non-empty input; Bakta would then only warn and report no arrays.

Dependencies used: tRNAscan-SE 2.0.12, Aragorn 1.2.41, Infernal 1.1.5 (Ubuntu packages), pyCirclize 1.10.1.

Files are copied unchanged from the output folder (`annotation.png`/`.svg`/`.embl`/`.fna`/`.log` were not kept),
except that the local folders in `console.log` were replaced with `/work`. `console.log` is Bakta's standard
output (its stage lines).

`console_pilercr_crash.log` is the standard output of an earlier run (`--verbose`, without `--skip-crispr`, on a
45.7 kb genome from the same script without inserted sequences) in which PILER-CR crashed; Bakta printed the warning
and reported no CRISPR arrays. Its local folders were replaced with `/work`, `/databases/…` and `/tmp/tmpXXXXXXXX`.
