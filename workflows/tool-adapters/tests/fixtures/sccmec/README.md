# sccmec fixtures — real sccmec 1.2.0 output

Written by sccmec 1.2.0 (Bioconda `sccmec-1.2.0-hdfd78af_0`, camlhmp 1.1.4, BLAST+ 2.16.0; ARVA's environment from
`docker/conda-locks/sccmec/linux-64.lock`) with its bundled schemas (sccmec_targets 1.2.0, sccmec_regions 1.2.0) on
2026-11-02, with the command ARVA builds (the four schema files and every threshold passed explicitly):

```bash
sccmec --input contigs.fasta --yaml-targets <env>/share/sccmec/sccmec-targets.yaml \
  --yaml-regions <env>/share/sccmec/sccmec-regions.yaml --targets <env>/share/sccmec/sccmec-targets.fasta \
  --regions <env>/share/sccmec/sccmec-regions.fasta --min-targets-pident 90 --min-targets-coverage 80 \
  --min-regions-pident 85 --min-regions-coverage 83 --prefix sccmec --outdir sccmec
```

| Fixture | Input | sccmec's call | Published |
| --- | --- | --- | --- |
| `n315.*` | *S. aureus* N315: NCBI RefSeq NC_002745.2 + NC_003140.1 (GCF_000009645.1), concatenated with descriptions removed (sha256 `018ad46ca03e58ecf35d20ee3b5e92e74f5ed0aea2b800e39336a417e36509a5`) | type II, subtype IIa, mecA +; targets ccrA2, ccrB2, IS431, mecA, mecI, mecR1; cassette IIa covered 100 % | SCCmec type II: N315 is the strain in which SCCmec was described (Ito T. et al. 1999 Antimicrob Agents Chemother 43:1449; Kuroda M. et al. 2001 Lancet 357:1225); IIa is the subtype of D86934, N315's cassette, the reference sccmec uses for IIa |
| `usa300.*` | *S. aureus* USA300_FPR3757: NC_007793.1 + NC_007790.1, NC_007791.1, NC_007792.1 (GCF_000013465.1), concatenated with descriptions removed (sha256 `96df7dd2cc9375eb0deade3fbc6b7ed88bc3e5e8d0526df0c845343fc5bb08e8`) | type IV, subtype IVa, mecA +; cassette IVa covered 94.12 % | SCCmec IVa (Diep B.A. et al. 2006 Lancet 367:731-739, PMID 16517273) |
| `synthetic.*` | ARVA's SYNTHETIC genome (`examples/synthetic-genome/reference.fasta`, descriptions removed, sha256 `8aabd59fa25d51dec51cc8a0587584cd23530eb0317a61c73346935739a70f45`) | type `-`, subtype `-`, mecA `-`: "A type could not be determined based on the target matches or cassette coverage" | untypeable by construction |

Kept: `<name>.tsv` (the result row), `<name>.targets.details.tsv`, `<name>.regions.details.tsv` and
`<name>.targets.blastn.tsv`; the regions' BLAST table was not kept (561 rows for N315). `help_1.2.0.txt` is
`sccmec --help` at 120 columns, the environment's folder replaced with `<conda>`. The genomes were downloaded from
NCBI E-utilities (`efetch.fcgi?db=nuccore&id=<accession>&rettype=fasta`) and deleted after the runs.

Notes from these runs and sccmec's scripts:

* The details tables' `params` column reads `min-coverage=90;min-pident=80` for the targets: the labels are swapped
  (the run used identity 90 % and coverage 80 %, as the result row's `params` says).
* The schema's "mecA" target includes the mecC sequence of type XI (FR821779.1), so sccmec's mecA column means "mecA
  or mecC"; ARVA cross-checks it with AMRFinderPlus's mecA and mecC calls.
* Subtypes IVe, IVf and IVh are not in the regions schema 1.2.0: such a cassette can be typed IV without a subtype or
  get the closest subtype.
