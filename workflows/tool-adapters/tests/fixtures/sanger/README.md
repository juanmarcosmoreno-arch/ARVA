# Sanger identification fixtures — real BLAST+ outputs on public sequences

Written on 2026-11-03 with BLAST+ 2.12.0 (Ubuntu ncbi-blast+ 2.12.0+ds-4build2). The columns are ARVA's
`arva_tools.blast.OUTFMT_TITLES` (the 15 fields of `OUTFMT` plus `stitle`), except `vfdb_hlb_vs_mw2.tsv`, which is
`OUTFMT` (a genome has no useful titles).

```bash
OF="6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen nident"
blastn -task megablast -query 3100_trimmed.fna -db <16S>/16S_ribosomal_RNA -outfmt "$OF stitle" -evalue 1e-10 \
  -max_target_seqs 500 -dust yes -strand both -num_threads 2 -out all.tsv
awk -F'\t' '$3>=97' all.tsv > 3100_trimmed_vs_16S_ribosomal_RNA.tsv            # 97 of the 500 rows
blastn -task blastn -query ../region/seh_MW2_nucleotide.fna -db <abricate>/db/vfdb/sequences -outfmt "$OF stitle" \
  -evalue 1e-5 -max_target_seqs 500 -dust yes -strand both -num_threads 2 -out seh_vs_vfdb.tsv
blastn -task megablast -query hlb.fa -subject GCF_000011265.1.fna -outfmt "$OF" -evalue 1e-10 \
  -max_target_seqs 500 -dust yes -strand both -out vfdb_hlb_vs_mw2.tsv
```

## Inputs

* `3100_trimmed.fna`: the base calls of Biopython's public `3100.ab1` (scientific-core/tests/fixtures/sanger) kept by
  ARVA's modified Mott trimming at 0.05 (bases 19-697, 679 bases). Derived from Biopython's test data under the
  Biopython License Agreement (`BIOPYTHON_LICENSE.rst` here).
* `<16S>`: NCBI's BLAST database `16S_ribosomal_RNA` ("16S ribosomal RNA (Bacteria and Archaea type strains)"),
  `https://ftp.ncbi.nlm.nih.gov/blast/db/16S_ribosomal_RNA.tar.gz` (72,729,050 bytes, MD5 checked against the `.md5`
  file), build `last-updated` 2026-10-29, 27,646 sequences, BLASTDB version 5. Only the database files were unpacked
  (not NCBI's taxonomy files). It is kept outside the repository, at `ARVA_TEST_16S_DB` (default
  `/root/.arva-testdata/ncbi-16s/2026-10-29/16S_ribosomal_RNA`).
* `<abricate>`: ABRicate 1.4.0's bundled VFDB (ARVA's Bioconda lock `docker/conda-locks/abricate`; `abricate --list`
  dates it 2026-Apr-3), 4,592 sequences.
* `hlb.fa`: VFDB's hlb sequence (`vfdb~~~hlb~~~WP_000239607~~~`, 993 bp) from that file, not copied here; the genome is
  MW2 (NCBI RefSeq GCF_000011265.1, fixtures/region/README.md).

## What the outputs show

* 16S: *Staphylococcus epidermidis* NR_036904.1 at 99.853 % over all 679 bases (one mismatch); *S. epidermidis*
  NR_113957.1, *S. saccharolyticus* (NR_113405.1, NR_029158.1) and *S. caprae* NR_024665.1 at 99.705 %; 16 rows at
  99 % or more; 90 *Staphylococcus* and 7 *Mammaliicoccus* rows at 97 % or more. The read aligns to the minus strand
  of the references, at about positions 660-1,360: not the 5' region the CLSI criteria were set for. The species
  is not separated by 0.8 %, so the reading is genus *Staphylococcus*.
* seh: VFDB's seh (WP_000608674) at 100 % over all 726 bases; selk at 91.4 % over 35 bases (query 643-677).
* hlb in MW2: two HSPs, query 1-183 at 2,046,036-2,046,218 (100 %) and query 170-993 at 2,088,807-2,089,630
  (99.636 %), 42,588 bp apart on the plus strand: the gene interrupted by a prophage. MW2's Bakta 1.12.2 annotation
  (light database 6.0, in the test cache) names the two overlapping CDSs "Phospholipase C" (2,046,033-2,046,233 and
  2,088,806-2,089,630); NCBI's names the second `sph` (a pseudogene, sphingomyelin phosphodiesterase) and the first
  "phospholipase".

## `blastdbcmd_info_16S_2.12.0.txt`

The output of `blastdbcmd -db <16S>/16S_ribosomal_RNA -info` (blastdbcmd 2.12.0+, the same Ubuntu BLAST+ package) on
the 2026-10-29 build described above, unchanged (its last line is the local path of that copy).
