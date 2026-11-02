# Region Explorer and gene investigation fixtures — real BLAST+, MAFFT, IQ-TREE and FastTree usage and output

Written on 2026-11-02 with BLAST+ 2.12.0 (Ubuntu ncbi-blast+ 2.12.0+ds-4build2), MAFFT 7.505 (Ubuntu mafft 7.505-1),
FastTree 2.1.11 (Ubuntu fasttree 2.1.11-2) and IQ-TREE 3.0.1 (ARVA's Bioconda lock `docker/conda-locks/iqtree`).
`*_help_*.txt` are the tools' usage texts (`-help`, `--help`, `-h`, `-expert`).

```bash
OF="6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen nident"
makeblastdb -in GCF_000011265.1.fna -dbtype nucl -out db_mw2/genome          # likewise for N315
tblastn -task tblastn -query seh_WP_000608674.1.faa -db db_mw2/genome -out t.tsv -outfmt "$OF" -evalue 1e-05 \
  -max_target_seqs 500 -seg yes -comp_based_stats 2 -db_gencode 11 -num_threads 2
blastn -task blastn -query seh_MW2_nucleotide.fna -db db_mw2/genome -out n.tsv -outfmt "$OF" -evalue 1e-10 \
  -max_target_seqs 500 -dust yes -strand both -num_threads 2
```

`tblastn_seh_mw2_n315.tsv` is MW2's rows followed by N315's; `blastn_seh_mw2_n315.tsv` likewise (N315 has none).

## Sequences

* `seh_WP_000608674.1.faa` — RefSeq protein WP_000608674.1, staphylococcal enterotoxin type H (seh, 241 aa), copied
  from MW2's `protein.faa` in the NCBI package below.
* `seh_MW2_nucleotide.fna` — MW2 (NC_003923.1) positions 61,524-62,249, plus strand: the seh CDS (726 bp) as NCBI's
  annotation (`genomic.gff`, locus tag MW_RS00265) places it.

## Genomes (NCBI RefSeq, NCBI Datasets v2 API; kept outside the repository)

`POST https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download` with GCF_000011265.1 and GCF_000011525.1 and
`"include_annotation_type": ["GENOME_FASTA", "GENOME_GFF", "PROT_FASTA", "CDS_FASTA"]`: package zip 4,885,059 bytes
(sha256 `a9b29487b6b5ae36ab1930518a6381cfd888f9a56db0d7f733651e429a8c0b13`), every file matched its `md5sum.txt`. The
genomes join the shared cache `/root/.arva-testdata/genomes/<accession>.fna` (`SHA256SUMS`); NCBI's GFF3 and protein
FASTA are in `ncbi-annotation/` there (with their own `SHA256SUMS`). N315 and USA300 are the 6A genomes
(fixtures/comparative/README.md).

| Accession | Organism (NCBI) | FASTA sha256 |
| --- | --- | --- |
| GCF_000011265.1 | *S. aureus* subsp. *aureus* MW2 | `e669f54b36d619cc94d86bd04a1ba0443ec0472373a9d96294146e84a1b52288` |
| GCF_000011525.1 | *S. aureus* subsp. *aureus* MSSA476 | `3ad245d91848d526f7e58a38481dae7a34032ff5d14f8b9edee141c072d14074` |

## What the outputs show

* tblastn (e-value <= 1e-5): seh at 100 % identity over all 241 aa in MW2 (61,524-62,246; the stop codon is not
  aligned) and in MSSA476 (60,231-60,953); no such hit in N315 or USA300_FPR3757. Every genome also has HSPs of
  28-47 % identity to other superantigen genes (enterotoxin and enterotoxin-like paralogues): an identity threshold
  decides what counts as "the gene", which is why ARVA asks for it explicitly.
* Just downstream of seh in MW2 two short HSPs (query 93-134 and 134-238, 37-38 %) lie next to each other on the
  genome, overlapping by 17 bp: ARVA's chaining joins them into one "split" match when the identity threshold allows
  it.
* blastn of the seh CDS: one HSP, 726/726 identical, in MW2; none in N315.
* MAFFT L-INS-i, FastTree (-lg -gamma) and IQ-TREE (-m MFP -B 1000) on four MW2 superantigen proteins: four aligned
  sequences of one length; both trees have the four leaves; IQ-TREE's report names the best-fit model by BIC. Both
  tree programs refuse duplicate sequence names, so ARVA renames the sequences s1..sN and maps the names back.
