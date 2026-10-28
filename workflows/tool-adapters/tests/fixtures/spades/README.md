# SPAdes fixtures

Written by SPAdes 3.15.5 (Ubuntu 24.04 package `spades` 3.15.5+dfsg-7, run through its `/usr/bin/spades.py`
launcher with Python 3.13) with an empty HOME. Inputs: `scripts/make_synthetic_genome.py` with
`--chromosome-length 100000 --plasmid-length 8000 --repeat-length 2000 --ont-depth 30 --illumina-depth 40`
(default seed), except the memory-limit run, which used `--chromosome-length 6000000 --plasmid-length 50000
--repeat-length 5000 --ont-depth 1 --illumina-depth 60`. All reads are SYNTHETIC.

| Fixture | Run |
|---|---|
| `help_3.15.5.txt` | `spades.py --help` |
| `isolate_paired.*` | `--isolate -1 R1 -2 R2 -t 4 -m 8 --cov-cutoff off` (k chosen by SPAdes: 21,33,55,77): `spades.log` (gzip), `run_spades.yaml`, `params.txt`, and the header lines of `contigs.fasta` and `scaffolds.fasta` |
| `isolate_single_k.spades.log.gz` | `--isolate -s R1 -t 2 -m 4 -k 21,33,55 --cov-cutoff auto` |
| `careful_paired.run_spades.yaml`, `careful_paired.stage_lines.txt` | `--careful -1 R1 -2 R2 -t 4 -m 4 --cov-cutoff off`: the plan, and the `=====`, `Mode:` and k-mer lines of its log |
| `memory_limit.spades.log` | the last 40 lines of `spades.log` of `--isolate -1 R1 -2 R2 -t 4 -m 1 --cov-cutoff off` on the 6 Mb genome: spades-core exceeds the 1 GB limit in K21 (`mmap(2) failed. Reason: Cannot allocate memory`) and spades.py exits with status 12 |

The local folders were replaced with `/job/input` (reads) and `/job` (everything else); nothing else was changed.
