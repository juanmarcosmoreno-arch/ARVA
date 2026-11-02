# Pangenome fixtures — real Panaroo 1.8.1 output on five NCBI *S. aureus* genomes

## Genomes and annotation (kept outside the repository)

The five NCBI RefSeq genomes cached in `/root/.arva-testdata/genomes/<accession>.fna` (see
`../comparative/README.md` and `../region/README.md` for how they were downloaded and their sha256):

| Name in Panaroo | Accession | Organism (NCBI) |
| --- | --- | --- |
| g1 | GCF_000009645.1 | *S. aureus* subsp. *aureus* N315 |
| g2 | GCF_000009665.1 | *S. aureus* subsp. *aureus* Mu50 |
| g3 | GCF_000013465.1 | *S. aureus* subsp. *aureus* USA300_FPR3757 |
| g4 | GCF_000011265.1 | *S. aureus* subsp. *aureus* MW2 |
| g5 | GCF_000011525.1 | *S. aureus* subsp. *aureus* MSSA476 |

Each was annotated on 2026-11-02 with Bakta 1.12.2 (ARVA's Bioconda lock) and the light database 6.0, with the
AMRFinderPlus data 2026-08-07.1 in place of the light database's older copy (the view ARVA's Bakta adapter builds,
`compose_database`), CDS only:

```bash
bakta <acc>.fna --db <view> --output <acc> --prefix <acc> --threads 4 --min-contig-length 1 --translation-table 11 \
  --locus-tag P<9 digits of the accession> --locus-tag-increment 1 --genus Staphylococcus --species aureus --complete \
  --keep-contig-headers --skip-trna --skip-tmrna --skip-rrna --skip-ncrna --skip-ncrna-region --skip-crispr \
  --skip-sorf --skip-plot
```

The GFF3 files (with the sequence after `##FASTA`) are cached in
`/root/.arva-testdata/genomes/bakta-1.12.2-light6/<acc>/<acc>.gff3` with their sha256 in `SHA256SUMS` there
(2,592 / 2,691 / 2,698 / 2,564 / 2,568 CDS). The real-tool tests read them through `ARVA_TEST_GENOMES` and skip
without them.

## Panaroo run

From a folder holding `in/g1.gff3` … `in/g5.gff3` (links to the files above), with every result-changing option
passed (the strict-mode values Panaroo 1.8.1 sets for five genomes, see `arva_tools/pangenome.py`):

```bash
panaroo -i in/g1.gff3 in/g2.gff3 in/g3.gff3 in/g4.gff3 in/g5.gff3 -o out2 --clean-mode strict -c 0.98 -f 0.7 \
  --len_dif_percent 0.98 --family_len_dif_percent 0.0 --search_radius 5000 --refind_prop_match 0.2 \
  --refind-mode default --min_trailing_support 2 --trailing_recursive 99999999 --edge_support_threshold 2 \
  --length_outlier_support_proportion 0.1 --remove_by_consensus True --high_var_flag 5 --min_edge_support_sv 2 \
  --core_threshold 0.95 -t 4 --codon-table 11
```

72 s on 4 CPUs. The same command with `-a core --aligner mafft` took 7 min 37 s (2,310 core families aligned) and
gave the same presence/absence table.

* `summary_statistics.txt`, `gene_presence_absence.Rtab`: unchanged (3,090 families: 2,310 in all five genomes,
  42 / 167 / 239 / 332 in four / three / two / one).
* `gene_presence_absence.csv`: the header and 14 of the 3,090 rows (families in 5, 4, 3, 2 and 1 genomes, a family
  with refound members flagged `_pseudo`, one flagged `_len`, one with two paralogues in a genome, one named
  `lpl5~~~lpl1`); `gene_data.csv`: the header and the rows of those families' 47 genes.
* `group_2415.aln.fas`: one family alignment of the `-a core` run (headers `<genome>;<clustering id>`).
* `panaroo_help.txt`: `panaroo --help` of 1.8.1.

## PPanGGOLiN (constructed, not tool output)

`ppanggolin_constructed/` holds three small files written by hand in the formats of PPanGGOLiN 2.3.2's writers
(`ppanggolin/formats/writeFlatPangenome.py`: `write_gene_presence_absence`, `write_matrix` with gene counts and the
partition as the second column, `write_gene_families_tsv` without a header). PPanGGOLiN is not installed here (its
environment adds graph-tool, GTK and Boost, about 1 GB), so ARVA's PPanGGOLiN adapter is not validated.
