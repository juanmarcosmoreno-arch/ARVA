# mlst fixtures — real mlst 2.35.0 output

Written by mlst 2.35.0 (Bioconda `mlst-2.35.0-hdfd78af_1`, BLAST+ 2.16.0, Perl 5.32.1; ARVA's environment from
`docker/conda-locks/mlst/linux-64.lock`) with its bundled PubMLST schemes (162 schemes downloaded 2026-03-11,
`db/VERSION.txt` 2025-12-29), on 2026-10-29, with the command ARVA builds (run in the job's results folder):

```bash
mlst --full --outfile mlst.tsv --json mlst.json --novel novel_alleles.fasta --threads 2 --minid 95 --mincov 50 \
  --minscore 50 --exclude ecoli,abaumannii,vcholerae_2,senterica_achtman_2 \
  --blastdb /env/db/blast/mlst.fa --datadir /env/db/pubmlst input/genome.fna 2> mlst.stderr.log
```

`*_scheme_ecoli.*` used `--minscore 0 --scheme ecoli` instead of `--minscore 50 --exclude …` (mlst sets the
minimum score to 0 whenever a scheme is forced, and ignores --exclude).

| Fixture | Input | Result |
| --- | --- | --- |
| `saureus_NC_007795.1` | *Staphylococcus aureus* subsp. *aureus* NCTC 8325 chromosome, NCBI RefSeq NC_007795.1 (assembly GCF_000013425.1), 2,821,361 bp, FASTA sha256 `04b865e316d64ee393dcffcf1cc31c7eaa14a38f4a74c04e385d2acb8e819731` | saureus ST8, PERFECT |
| `ecoli_NC_000913.3` | *Escherichia coli* K-12 MG1655, NCBI RefSeq NC_000913.3 (GCF_000005845.2), 4,641,652 bp, sha256 `6b195feda4c66140f6762742eb8b30c2652f02b45878b174f5b00ef85ecc95d7` | ecoli_achtman_4 ST10, PERFECT |
| `ecoli_NC_000913.3_scheme_ecoli` | the same, scheme forced to `ecoli` (Institut Pasteur scheme, excluded by default) | ecoli ST262, PERFECT |
| `synthetic` | ARVA's SYNTHETIC genome (`scripts/make_synthetic_genome.py`, `examples/synthetic-genome/reference.fasta`) | no scheme (`-`), NONE |
| `saureus_edited` | NC_007795.1 edited by `derive_inputs.py` (sha256 `5e597fc5649b4ff2a02a37b642c5281799ffaec0ab9e5bfa9b6f61045c678f8a`): one substitution in arcC_3, the contig cut inside gmk_1, tpi_4 removed, yqiL_1 added as a contig | saureus, ST `-`, MIXED, score 66: `arcC(~3)`, `gmk(725?)`, `tpi(-)`, `yqiL(1,3)` |
| `mixed` | NC_007795.1 and NC_000913.3 in one file (sha256 `589bcacceaf21c826a49a116446b815240a5094f54c7e889c75ef7d3bf5855bd`) | saureus ST8 and ecoli_achtman_4 ST10 tie at score 100; mlst prints the tie as a WARNING and reports one of them |

The genomes were downloaded from NCBI E-utilities (`efetch.fcgi?db=nuccore&id=<accession>&rettype=fasta`) and
deleted after the runs; only mlst's outputs are kept. The edited and mixed inputs are test constructs for the parser,
not biology. Files are mlst's own, except that local folders in the logs were replaced with `/env` (the environment)
and `/tmp/XXXXXXXXXX` (mlst's temporary folder). `help_2.35.0.txt` is `mlst --help`.

Notes from these runs (and mlst's source, `bin/mlst`):

* The number of an inexact call is the first similar allele in BLAST's output, not necessarily the closest:
  gmk was cut inside allele 1, yet the partial call is `725?`.
* With equal best scores mlst picks one scheme in Perl's hash order, which can differ between runs; the tie is
  only visible in the `WARNING: <scheme>(<ST>)==<scheme>(<ST>) score=<n> <file>` line on standard error.
