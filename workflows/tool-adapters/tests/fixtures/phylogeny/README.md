# Phylogeny fixtures — real SNP-sites 2.5.1 and IQ-TREE 3.0.1 output on Panaroo's core-genome alignment

## Input (kept outside the repository)

Panaroo 1.8.1 (ARVA's Bioconda lock) with `-a core --aligner mafft` on the five Bakta-annotated NCBI *S. aureus*
genomes of `../pangenome/README.md` (g1 N315 GCF_000009645.1, g2 Mu50 GCF_000009665.1, g3 USA300_FPR3757
GCF_000013465.1, g4 MW2 GCF_000011265.1, g5 MSSA476 GCF_000011525.1), with the strict-mode options listed there plus
`-a core --aligner mafft`, run on 2026-11-02 (about 5 min on 4 CPUs). Cached in
`/root/.arva-testdata/genomes/panaroo-1.8.1-core/out/` (Panaroo's intermediate files removed), checksums in
`SHA256SUMS` there:

| File | SHA-256 |
| --- | --- |
| core_gene_alignment.aln (2,310 core genes, 2,186,160 columns) | 96ce6f2b2d70458dfbb541fe512548c7f03e8f21174e1eac411168fd20ad2904 |
| core_gene_alignment_filtered.aln (2,070 genes; entropy threshold set automatically to 0.01604) | 561cdb035343d68f9e626f135025957d6bbca068f90678a2d80866098a9f93f2 |

Panaroo writes the genomes in no fixed order (g1, g3, g4, g5, g2 here); ARVA maps them by name. For each genome and
core gene it takes the copy with the fewest gaps and fills a missing gene with gaps (panaroo/generate_output.py,
`concatenate_core_genome_alignments`).

## Files

* `snp_sites_usage_2.5.1.txt`: `snp-sites` with no argument (exit status 0).
* `core_constant_counts.txt`: `snp-sites -C -o core_constant_counts.txt core_gene_alignment.aln` — constant A, C, G
  and T columns (775,527 / 315,491 / 409,032 / 655,216). `snp-sites -m` keeps 30,888 columns; `-m -c` (A/C/G/T
  only) 29,328. 30,888 + 2,155,266 = 2,186,154: six columns hold no base. On a constructed alignment
  (`A A - -` style columns) a column whose bases agree but which has gaps counts as constant, and a variable column
  with N stays in the default output but not in `-c`'s.
* `core_mfp_ufboot_alrt.iqtree` / `.treefile`: `iqtree3 -s core_gene_alignment.aln --seqtype DNA -m MFP -B 1000
  --alrt 1000 -T 4 --seed 12345 --prefix full` (4 s): TIM2+F+I by BIC; node labels "SH-aLRT/UFBoot" (100/100). The
  report prints "Number of constant sites: 2.15527e+06" in scientific notation.
* `snp_fconst.iqtree`: the same on `snp-sites -m` output with `-fconst 775527,315491,409032,655216`: 2,186,154
  sites, the same model and topology (2.5 s).
* `snp_asc_gtr.iqtree`: `-m GTR+F+ASC+G4` on `snp-sites -m -c` output (29,328 sites, 0 constant).
* `mfp_asc_abort_3.0.1.txt`: the assertion IQ-TREE 3.0.1 aborts with (exit status 134) on `-m MFP+ASC` with that
  alignment, with `-T 4` and `-T 1`, with or without -B/--alrt. ARVA therefore asks for a stated model with +ASC.
  `-m GTR+ASC` on `snp-sites -m` output (with gap columns) was accepted ("0 constant sites"); ARVA still uses `-c`
  for +ASC so that no column is constant in any sense.

`iqtree3 -rf <tree1> <tree2> --prefix p` (not listed by `iqtree3 -h`) writes the Robinson-Foulds distance to
`p.rfdist`; the real-tool test compares it with ARVA's own implementation (arva_core.phylo).

FastTree 2.1.11 (`-nt -gtr -gamma -boot 1000`) on the full 2.2 Mb alignment took 6 min 43 s on one CPU, with the same
topology as IQ-TREE (`iqtree3 -rf`: 0); on the SNP
alignment it takes under a second and gives the same topology, as does ARVA's neighbour joining on Jukes-Cantor
distances of the full alignment.
