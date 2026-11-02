# AgrVATE fixtures — real AgrVATE 1.0.2 output (MUMmer mode)

Written by AgrVATE 1.0.2 (Bioconda `agrvate-1.0.2-hdfd78af_0` with snippy 4.6.0, MUMmer 3.23, BLAST+ 2.16.0, HMMER
3.4; ARVA's environment from `docker/conda-locks/agrvate/linux-64.lock`) on 2026-11-02 with the command ARVA builds,
in a folder holding only the staged `contigs.fasta`:

```bash
agrvate --input contigs.fasta --mummer --databases <env>/bin/agrvate_databases/
```

The default mode needs usearch11.0.667_i86linux32, a 32-bit binary that is not in the package and that ARVA does not
download; `--mummer` runs here.

| Fixture | Input | AgrVATE's call | Published |
| --- | --- | --- | --- |
| `n315.*` | *S. aureus* N315 (as in `../sccmec/README.md`) | gp2 (agr II), 15 k-mers, canonical agrD, single, 0 frameshifts; the group-I reference operon aligned in two fragments (1-1,417 and 2,659-3,482 of 3,482 bp: 64 %) | agr group II (N315 used as the agr-II prototype: Frontiers in Microbiology 2022, doi:10.3389/fmicb.2022.700894) |
| `usa300.*` | *S. aureus* USA300_FPR3757 (as in `../sccmec/README.md`) | gp1 (agr I), 13 k-mers, canonical agrD, single, 0 frameshifts; the reference operon aligned whole (3,482 bp, 99.91 %) | agr I is reported for the USA300 clone (CC8); no publication stating FPR3757's agr group was checked here |
| `synthetic.*` | ARVA's SYNTHETIC genome | u (untypeable), 0 k-mers, agrD not found, no operon | none by construction |

Kept: `<name>.summary.tab`, `<name>.agr_gp.tab` (k-mer hits), `<name>.agr_operon_frameshifts.tab`, `<name>.out.1coords`
(dnadiff's alignment of the reference operon), `<name>.error-report.tab` and AgrVATE's standard output
(`<name>.stdout.txt`, the environment's folder replaced with `<conda>`). `help_1.0.2.txt` is `agrvate -h`.
