# IntegronFinder fixtures — real IntegronFinder 2.0.6 output

Written by IntegronFinder 2.0.6 (Bioconda `integron_finder-2.0.6-pyhdfd78af_0`, HMMER 3.3.2, Infernal 1.1.4, Prodigal
2.6.3; ARVA's environment from `docker/conda-locks/integronfinder/linux-64.lock`) with its bundled models, with the
command ARVA builds (the topology file says `circ` for every sequence here, as the NCBI records are complete and
circular):

```bash
integron_finder --cpu 4 --distance-thresh 4000 --evalue-attc 1 --calin-threshold 2 --max-attc-size 200 \
  --min-attc-size 40 --topology-file topology.txt --outdir integron_finder --cmsearch /env/bin/cmsearch \
  --hmmsearch /env/bin/hmmsearch --prodigal /env/bin/prodigal --mute --local-max contigs.fna
```

| Fixture | Input (the staged FASTA of the ABRicate fixtures) | Result |
| --- | --- | --- |
| `r388.*` | *E. coli* plasmid R388, NC_028464.1 | one complete integron (intI at 29,666..30,679 on the - strand, two attC sites), the class 1 integron R388 is known for |
| `n315.*` | *S. aureus* N315 | "# No Integron found"; the summary lists both replicons with 0 complete, In0 and CALIN |
| `synthetic.*` | ARVA's SYNTHETIC genome | no integron |

`help_2.0.6.txt` is `integron_finder --help`. Paths were replaced with `/env` and `/work`.
