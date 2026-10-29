# AMRFinderPlus fixtures — real AMRFinderPlus 4.2.7 output

Written by AMRFinderPlus 4.2.7 (Bioconda `ncbi-amrfinderplus-4.2.7-hf69ffd2_0`, BLAST+ 2.16.0, HMMER 3.4; ARVA's
environment from `docker/conda-locks/amrfinderplus/linux-64.lock`) with the NCBI database release 2026-08-07.1
(`https://ftp.ncbi.nlm.nih.gov/pathogen/Antimicrobial_resistance/AMRFinderPlus/database/4.2/2026-08-07.1/`, database
format 4.2.0, downloaded and indexed with `amrfinder_index` on 2026-10-29), with the command ARVA builds:

```bash
amrfinder --nucleotide input.fna --database /db/2026-08-07.1 --output amrfinder.tsv \
  --nucleotide_output nucleotide_hits.fna --ident_min -1 --coverage_min 0.5 --translation_table 11 --threads 4 \
  --blast_bin /env/bin --hmmer_bin /env/bin --print_node --organism Staphylococcus_aureus \
  --mutation_all mutation_all.tsv --plus
```

| Fixture | Input | Result |
| --- | --- | --- |
| `n315` | *Staphylococcus aureus* subsp. *aureus* N315: NCBI RefSeq NC_002745.2 (chromosome, 2,814,816 bp, FASTA sha256 `d662a3eaad8dffa393e1686a1cbfe3361b7a959669045824b9ebbc28ba1522f4`) and NC_003140.1 (plasmid pN315, 24,653 bp, `68f63fcc7e1c3823bc44edfb11af8aee5e761e1106aef6aece586091eca7ac4d`), assembly GCF_000009645.1, concatenated (sha256 `27edb70497b44b07724389133c927a7cfcec606cbdcf70a0b53719a9e69da09b`) | 49 elements: 21 AMR (mecA, mecR1, mecI, aadD1, bleO, fosB, tet(38), mepA, 5 erm(A), 5 ant(9)-Ia; blaZ, blaR1, blaI on pN315), 5 stress, 23 virulence; sen INTERNAL_STOP, seu and sasG PARTIALX; no point mutation |
| `n315_edited` | the same, edited by `derive_inputs.py` (sha256 `78f5220da34d9f1c319ec3f7cbf393076d0f26d17448a2f8d534634d2674f75c`): gyrA codon 84 TCA→TTA, the chromosome cut 60 % into mecA, codon 100 of blaZ replaced by a stop codon | gyrA_S84L (POINT, POINTX), mecA PARTIAL_CONTIG_ENDX (59.88 % coverage), blaZ INTERNAL_STOP |
| `n315_bakta_combined` | the combined search (`--protein annotation.faa --gff annotation.gff3 --annotation_format bakta` with `annotation.fna`) on Bakta 1.12.2's annotation of `n315` (light database 6.0, locus tag NTEST) | 50 elements: EXACTP/BLASTP with the Bakta locus tag as Protein id, EXACTX where the annotation lacks the protein, an HMM-only arsB, sen INTERNAL_STOP, seu PARTIALP |
| `synthetic` | ARVA's SYNTHETIC genome (`examples/synthetic-genome/reference.fasta`), no organism | no element (header only) |
| `constructed.tsv` | **constructed**, not tool output: one row each for an HMM-only hit, a POINTN 23S mutation, an StxTyper COMPLETE_NOVEL operon, a POINT_DISRUPT subtype and a PARTIAL_CONTIG_ENDP protein hit, in the formats of the real reports | parser cases |

`help_4.2.7.txt` is `amrfinder --help`; `list_organisms_2026-08-07.1.txt` is `amrfinder --database <release>
--list_organisms`; `database_version_bakta_light_6.0.txt` is `amrfinder --database <bakta-light 6.0>/amrfinderplus-db/latest
--database_version`, which refuses the copy inside Bakta's light database ("Software requires database version at
least 2025-09-22.2"). Local paths in the logs were replaced with `/env`, `/db`, `/input`, `/work`, `/annotation` and
`/bakta-db`.

The published annotation of N315 (NCBI RefSeq NC_002745.2 and NC_003140.1, PGAP 6.9, 2025-03-15) names mecA,
erm(A), aadD1, fosB, tet(38), mepA, blaZ, blaI, blaR1, cadD, tst, sec3, sel and the hlg genes; AMRFinderPlus finds
each of them. The genomes were downloaded from NCBI E-utilities (`efetch.fcgi?db=nuccore&id=<accession>&rettype=fasta`)
and deleted after the runs; only AMRFinderPlus's outputs are kept. The edited input is a test construct for the
parser, not biology.
