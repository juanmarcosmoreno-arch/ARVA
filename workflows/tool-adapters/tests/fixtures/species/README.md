# Species identification fixtures — real FastANI, skani, Mash and sylph output

Written on 2026-10-29 by the tools of ARVA's Bioconda locks (`docker/conda-locks/<tool>/linux-64.lock`): FastANI 1.34
(`fastani-1.34-hb66fcc3_7`), skani 0.4.0 (`skani-0.4.0-hec9b1f2_0`), Mash 2.3 (`mash-2.3-hf85e966_11`) and sylph
1.0.0 (`sylph-1.0.0-hb42e459_0`), with the options ARVA passes (run from a folder holding `input/` and
`collection/`; local folders were removed from the paths):

```bash
fastANI -q input/<query>.fna --rl <refs>.txt -o fastani_<case>.tsv -t 2 -k 16 --fragLen 3000 --minFraction 0.2 \
  --maxRatioDiff 10.0 > fastani_<case>.log 2>&1
skani dist -q input/<query>.fna --rl <refs>.txt -o skani_<case>.tsv -t 2 -c 125 -m 1000 -s 80 --min-af 15
mash sketch -o db/staph -k 21 -s 1000 -S 42 -l staph_refs.txt          # test database, 3 genomes
mash info -H db/staph.msh; mash info -t db/staph.msh; mash dist -p 2 db/staph.msh input/<query>.fna
sylph sketch --gl staph_refs.txt -o db/staph -t 2 -c 200 -k 31 --min-spacing 30   # test database, 3 genomes
sylph inspect db/staph.syldb
sylph profile db/staph.syldb -r input/<query>.fna -o sylph_<case>.tsv -t 2 -m 95 -M 10 --min-contain 7 \
  --min-count-correct 3 -c 200 -k 31
```

## Genomes (NCBI RefSeq, downloaded with the NCBI Datasets v2 API and deleted after the runs)

Two genome data packages, `POST https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download` with
`{"accessions": [...], "include_annotation_type": ["GENOME_FASTA"]}`; every file matched the package's `md5sum.txt`.
`packages/` keeps their metadata files (README.md, md5sum.txt, assembly_data_report.jsonl, dataset_catalog.json),
not the sequences.

| Accession | Organism (NCBI) | Type material | Role | FASTA sha256 |
| --- | --- | --- | --- | --- |
| GCF_006094915.1 | *Staphylococcus aureus* ATCC 12600 | yes | reference | `6dc572fa2dffc962a066b08bfafe93e069dee825f597267225b98898077edd08` |
| GCF_000236925.1 | *Staphylococcus argenteus* MSHR1132 | yes | reference | `bb8d81c03574f56993cad518ccd1574307a75d2e1836725b69f02c99ce2da6e6` |
| GCF_006094375.1 | *Staphylococcus epidermidis* ATCC 14990 | yes | reference | `b4feaf440f5dd7038ccec84c54c4b5f1ccc26b58093b3c027de9b476d3536964` |
| GCF_000013425.1 | *Staphylococcus aureus* subsp. *aureus* NCTC 8325 | no | query | `05df047f78234de456a72df5f938b7fdef98fc3af3bf8634a11d70fbd3dcd21d` |
| GCF_000005845.2 | *Escherichia coli* str. K-12 substr. MG1655 | no | reference | `53bb6a51b6e92139ced1e38f74b7938781027c52200922ff03718c2237d23bb4` |
| GCF_000006925.2 | *Shigella flexneri* 2a str. 301 | no | reference | `309de340d103d0f683c4499ec59775f28933fdc1203853809528345f89e83279` |
| GCF_000008865.2 | *Escherichia coli* O157:H7 str. Sakai | no | query | `71c2e5c364293c9ba36fc2c7acbcaa75cd6884295fe06260ba198826a8b1ddd3` |

Package zips: Staphylococcus `refs.zip` 3,168,329 bytes (sha256
`f3b30e771171ae2b1c70767e188bdb4e9b597739af450d61071aa18f95e27242`); Escherichia `ecoli.zip` 4,473,990 bytes
(sha256 `424e66a429bc2c01525d53de0e0b7e69534a1006209d49badb19baa30866e842`). NCBI builds the package on each request,
so a new download has the same sequences but may differ in the zip and the data report.

## Cases

| Case | Query | References | FastANI | skani |
| --- | --- | --- | --- | --- |
| `saureus` | NCTC 8325 | the three *Staphylococcus* type strains | *S. aureus* 99.9171 % (900/940 fragments), *S. argenteus* 88.85 %, *S. epidermidis* 79.1388 % | *S. aureus* 99.87 % (AF 97.81/96.46 %), *S. argenteus* 89.51 % |
| `saureus_no_aureus` | NCTC 8325 | *S. argenteus* and *S. epidermidis* only | 88.85 %, 79.1388 % | 89.51 % |
| `ecoli_sakai` | O157:H7 Sakai | K-12 MG1655 and *S. flexneri* 2a 301 | 97.7623 % and 96.9917 % (both above 95 %) | 98.08 % and 97.58 % |
| `synthetic` | ARVA's SYNTHETIC genome (`examples/synthetic-genome/reference.fasta`) | the three type strains | nothing reported (empty file) | header only |

Mash (`mash_saureus.tsv`): distance 0.00173271 (931/1000 shared hashes) to *S. aureus*, 0.0920479 (78/1000) to
*S. argenteus*, 0.243761 (3/1000) to *S. epidermidis*; the synthetic genome shares no hash (distance 1).

sylph (`sylph_saureus.tsv`): *S. aureus* Naive_ANI 99.60 (containment 10496/11891 k-mers, Eff_lambda LOW) and
*S. argenteus* Naive_ANI 92.80 with Adjusted_ANI 100.00 (containment 1158/11748, Eff_lambda 0.023) — sylph's
coverage adjustment does not fit an assembly, which is why ARVA reads Naive_ANI. The synthetic genome: header only.

GTDB-Tk 2.8.0 was installed from its lock only to record `gtdbtk --version` and `gtdbtk classify_wf -h`, then
removed; its reference data (about 100 GB) were not available, so there is no GTDB-Tk output here.

Help texts: `fastani_help_1.34.txt` (`fastANI --help`), `skani_dist_help_0.4.0.txt`, `mash_dist_help_2.3.txt`,
`mash_info_help_2.3.txt`, `sylph_profile_help_1.0.0.txt`, `gtdbtk_classify_wf_help_2.8.0.txt`,
`gtdbtk_version_2.8.0.txt`.

To rerun the real-tool tests on these genomes, download the two packages again (above), extract them into
`<folder>/staphylococcus/` and `<folder>/escherichia/`, and set `ARVA_TEST_SPECIES_GENOMES=<folder>`.
