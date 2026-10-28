# Prokka fixtures — output on a SYNTHETIC genome, not biology

Written by Prokka 1.14.6 (Ubuntu package 1.14.6+dfsg-6, its databases indexed by `prokka --dbdir … --setupdb`
from symbolic links to `/usr/share/prokka/db`) on `../annotation_genome/genome.fna`, with the command ARVA builds:

```bash
prokka /work/input.fna --outdir /work/prokka --prefix annotation --dbdir /work/prokka-db --kingdom Bacteria \
  --gcode 11 --locustag SYNT --increment 1 --cpus 2 --evalue 1e-09 --coverage 80 --mincontiglen 1
```

Tools Prokka found: Aragorn 1.2.41, barrnap 0.9, BLAST+ 2.12.0, HMMER 3.4, Infernal 1.1.5, Prodigal 2.6.3,
tbl2asn 25.3, GNU parallel 20231122. Not installed, so not run: MinCED (CRISPR arrays), SignalP, RNAmmer. Debian's
package has no `db/hmm` folder, so there is no HAMAP search. The genome is shorter than 100 kb, so Prokka ran
Prodigal in metagenome mode (`-p meta`), as its log says.

Files are copied unchanged from the output folder (`.err`, `.fna`, `.fsa`, `.sqn`, `.tbl` were not kept), except
that the local folders in `annotation.log` were replaced with `/work`.
