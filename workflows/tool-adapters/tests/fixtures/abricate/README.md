# ABRicate fixtures — real ABRicate 1.4.0 output

Written by ABRicate 1.4.0 (Bioconda `abricate-1.4.0-h05cac1d_0`, BLAST+ 2.16.0; ARVA's environment from
`docker/conda-locks/abricate/linux-64.lock`) with the databases bundled in that package (`abricate --list`:
`list_1.4.0.txt`; vfdb 4,592 sequences, plasmidfinder 488, both indexed 2026-04-03, the package's build date), with
the command ARVA builds:

```bash
abricate --datadir /env/db --db <vfdb|plasmidfinder> --minid 80 --mincov 80 --threads 4 --nopath input.fna
```

| Fixture | Input | Result |
| --- | --- | --- |
| `n315.*` | *Staphylococcus aureus* subsp. *aureus* N315: NCBI RefSeq NC_002745.2 (chromosome, FASTA sha256 `d662a3eaad8dffa393e1686a1cbfe3361b7a959669045824b9ebbc28ba1522f4`) and NC_003140.1 (plasmid pN315, `68f63fcc7e1c3823bc44edfb11af8aee5e761e1106aef6aece586091eca7ac4d`), assembly GCF_000009645.1, concatenated with descriptions removed as ARVA stages contigs (sha256 `018ad46ca03e58ecf35d20ee3b5e92e74f5ed0aea2b800e39336a417e36509a5`) | VFDB: 86 hits, all over the whole reference (capA with one gap); PlasmidFinder: rep19, rep5a and rep16 on pN315, and rep22 (repB of pAMalpha1) on the chromosome |
| `r388.*` | *Escherichia coli* plasmid R388: NCBI RefSeq NC_028464.1 (33,913 bp, circular; staged sha256 `00ccbba899df529ef9a46356c7f74b073f0209213553922c1e5a81ff46573717`) | PlasmidFinder: IncW_1; VFDB: nothing |
| `n315_cut.vfdb.*`, `n315_cut_mincov40.vfdb.*` | N315 cut by `derive_inputs.py` (sha256 `b6a539ba8361bfde4e5e1ee27b22f2d6534215b41c7f5ec78c5ad10a0554fe65`): 10 % into adsA and halfway into cap8D | at --mincov 80, adsA at a contig start (90.04 %) and no cap8D at all (each half covers 50 %); at --mincov 40 the two cap8D halves (a split gene) |
| `synthetic.*` | ARVA's SYNTHETIC genome (`examples/synthetic-genome/reference.fasta`, descriptions removed: sha256 `8aabd59fa25d51dec51cc8a0587584cd23530eb0317a61c73346935739a70f45`) | nothing (header only) |

The published records name what is expected: NC_028464.1 is R388 (IncW); the N315 chromosome carries the
integrated plasmid pUB110 inside SCCmec (Kuroda et al. 2001, Lancet 357:1225), whose rep gene is the replicon
PlasmidFinder finds there. `help_1.4.0.txt` is `abricate --help`. The genomes were downloaded from NCBI E-utilities
(`efetch.fcgi?db=nuccore&id=<accession>&rettype=fasta`) and deleted after the runs; local paths in the logs were
replaced with `/env` and `/input`.
