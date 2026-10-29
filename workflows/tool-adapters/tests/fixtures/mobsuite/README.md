# MOB-suite fixtures — real mob_recon 3.1.9 output

Written by MOB-suite 3.1.9 (Bioconda `mob_suite-3.1.9-pyhdfd78af_1`, BLAST+ 2.15.0, Mash 2.3, ete3 3.1.3; ARVA's
environment from `docker/conda-locks/mobsuite/linux-64.lock`, installed without the package's post-link script) with
database 3.1.8 as ARVA's Database Manager prepared it on 2026-10-29 (`ARVA_DATABASE_3.1.8.json`: Zenodo 10304948
archive MD5 `670e293e4ff1918db5b654278a60bea8`; BLAST index and Mash sketch built by the commands it lists, the
reference FASTA not kept; taxa.sqlite from NCBI's `taxdmp_2026-10-01.zip`, sha256
`d744af371c0b9fc7269d80b49546b6ac4c9ddc52a2fd97bcbfd02783edb5c9eb`), with the command ARVA builds:

```bash
mob_recon --infile input.fna --outdir mob_recon --num_threads 4 --sample_id sample --database_directory /db \
  --min_length 1000 --min_rep_ident 80 --min_mob_ident 80 --min_con_ident 80 --min_rpp_ident 80 --min_rep_cov 80 \
  --min_mob_cov 80 --min_con_cov 60 --min_rpp_cov 80 --min_rep_evalue 1e-05 --min_mob_evalue 1e-05 \
  --min_con_evalue 1e-05 --min_rpp_evalue 1e-05 --min_overlap 10 --max_contig_size 450000 \
  --max_plasmid_size 450000 --primary_cluster_dist 0.06 --secondary_cluster_dist 0.025
```

| Fixture | Input (the staged FASTA of the ABRicate fixtures) | Result |
| --- | --- | --- |
| `n315.*` | *S. aureus* N315, NC_002745.2 + NC_003140.1 | pN315 a plasmid (cluster AA409/AI458, rep_cluster_1017/1733/2214, relaxase MOBV, oriT MOBP, mobilizable, host range genus Staphylococcus); the chromosome 'chromosome' although it carries a replicon (rep_cluster_1018) and a MOBV relaxase (pUB110 integrated in SCCmec); 8 repetitive elements (IS1181, ...) in `mge.report.txt` |
| `r388.*` | *E. coli* plasmid R388, NC_028464.1 | a plasmid (cluster AD768/AN421, IncW, relaxase MOBF, MPF_T, oriT MOBF, conjugative; nearest neighbour NC_028464 at Mash distance 0) |
| `synthetic.*` | ARVA's SYNTHETIC genome | both sequences 'chromosome' (not assigned to a plasmid), no plasmid report |

`help_3.1.9.txt` is `mob_recon --help`. Paths in the logs were replaced with `/env`, `/db`, `/input` and `/work`.
