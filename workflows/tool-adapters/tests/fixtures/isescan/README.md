# ISEScan fixtures

* `N315_GCF_000009645.1.tsv`, `N315_GCF_000009645.1.sum` — REAL output of ISEScan 1.7.3 (installed from
  docker/conda-locks/isescan/linux-64.lock) on the NCBI RefSeq genome of Staphylococcus aureus N315
  (GCF_000009645.1, SHA-256 d7b93eeed77ce08d041f597d28fe3d7310fead42f9f790b6325539fb70c458f9, cached in
  /root/.arva-testdata/genomes, not committed): `isescan.py --seqfile input/contigs.fna --output out --nthread 3`
  with the environment's bin/ first in PATH. 23 elements (14 complete, 9 partial); the plasmid
  pN315 (NC_003140.1) was searched too; all 23 are on the chromosome (NC_002745.2). Run time 9 min 0 s on 4 vCPUs.
* `isescan_help_1.7.3.txt` — `isescan.py --help` of that installation.
* `constructed.tsv` — CONSTRUCTED, not tool output: a file written by hand in the same format before ISEScan could be
  installed (one complete element with a TIR and one partial element without); its names (`contig_1`,
  `IS1181_constructed`) and numbers are not biology. Kept for the parser's edge cases.
