# Filtlong fixtures

Logs (stderr) written by Filtlong 0.2.1 (Ubuntu package 0.2.1-4) with ARVA's command and `LC_ALL=C` on
`examples/synthetic/SYNTHETIC_nanopore_reads.fastq.gz` (400 reads, 1,513,780 bp; sha256 292a2ae3…), copied
unchanged (the `\r` progress updates included). Each shows one of the three outcomes of a target:

| Fixture | Thresholds | Outcome |
|---|---|---|
| `target_500000.log` | `--target_bases 500000` | `keeping 504167 bp` (overshoots by part of one read) |
| `target_not_enough_reads.log` | `--target_bases 1513780` (= every base of the input) | `not enough reads to reach target` |
| `target_below_after_filtering.log` | `--min_length 5000 --target_bases 1000000` | `reads already fall below target after filtering` |
