# Unicycler fixtures

Written by Unicycler 0.5.0 (Ubuntu 24.04 package `unicycler` 0.5.0+dfsg-1) with SPAdes 3.15.5, Racon 1.5.0 and
BLAST+ 2.12.0 from the same distribution, `--mode normal --keep 0`, an empty HOME. Inputs:
`scripts/make_synthetic_genome.py` with `--chromosome-length 100000 --plasmid-length 8000 --repeat-length 2000
--ont-depth 30 --illumina-depth 40` (default seed), except the memory-limit run (6 Mb chromosome, see
`../spades/README.md`). All reads are SYNTHETIC.

| Fixture | Run |
|---|---|
| `help_all_0.5.0.txt` | `unicycler --help_all` (colour escapes removed) |
| `short.*` | `-1 R1 -2 R2 -t 2 --spades_path /usr/bin/spades.py`: `unicycler.log`, the FASTA header lines, and `assembly.gfa` |
| `hybrid.*` | `-1 R1 -2 R2 -l ONT -t 2 --spades_path /usr/bin/spades.py "--spades_options=-m 4"`: `unicycler.log` and the FASTA header lines (two complete circular replicons, 100,000 and 8,000 bp) |
| `long.*` | `-l ONT -t 2`: `unicycler.log`, the FASTA header lines (bare names in this mode) and `assembly.gfa` |
| `memory_limit.*` | `-1 R1 -2 R2 -t 4 --spades_path /usr/bin/spades.py "--spades_options=-m 1"` on the 6 Mb genome: Unicycler's stderr (`Error: SPAdes encountered an error:` with no reason), its `unicycler.log`, and the last 40 lines of the `spades_assembly/spades.log` it left |

In the `*_noseq.gfa` files each segment's sequence was replaced with `*` (its `LN` tag, written by Unicycler, keeps
the length); the logs had their local folders replaced with `/job/input` (reads) and `/job`. Nothing else was
changed.
