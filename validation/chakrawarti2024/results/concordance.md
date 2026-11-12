# ARVA vs Chakrawarti et al. 2024: concordance

Isolates with ARVA results: 15 of 15.

| Comparison | ARVA matches | Notes |
|---|---|---|
| ST vs Sanger (gold standard) | 12/15 | no ST from ARVA counts as a mismatch |
| ST vs paper's ONT-only call | 8/14 | 1 more where both gave no ST |
| ST vs Sanger, isolates the paper's ONT-only assembly got wrong | 4/6 | ONT-only 'Undetermined' or wrong in Table S3 |
| spa vs hybrid assembly (Table S5) | 15/15 | |
| blaZ/blaPC1 vs penicillin phenotype | 15/15 | penicillinase (blaZ or blaPC1) expected exactly in penicillin R (Table 1; Table 1 and Table S7 disagree on the R count, see README) |
| mecA vs oxacillin/cefoxitin | 15/15 | all isolates are S: mecA expected absent |

## Per isolate

| Isolate | Sanger ST | Paper ONT ST | ARVA ST | Loci differing from the Sanger profile | spa paper / ARVA | Pen / blaZ | Oxa / mecA | Polisher |
|---|---|---|---|---|---|---|---|---|
| AC06-110 | 398 | 753 | no ST (novel combination of existing alleles) (MISMATCH) | arcC 90 (Sanger ST: 3); aroE 1216 (Sanger ST: 35) | t571 / t571 (match) | S / absent | S/S / absent | medaka |
| OF01-07 | 2187 | Undetermined | 2187 (match) | - | t267 / t267 (match) | S / absent | S/S / absent | medaka |
| AC12-45 | 7 | Undetermined | 7 (match) | - | t091 / t091 (match) | R / present | S/S / absent | medaka |
| OF10-16 | 8 | Undetermined | 8 (match) | - | t008 / t008 (match) | R / present | S/S / absent | medaka |
| AC14-18 | 72 | 72 | 72 (match) | - | t148 / t148 (match) | R / present | S/S / absent | medaka |
| AC05-54 | 5957 | 5957 | 5957 (match) | - | t548 / t548 (match) | R / present | S/S / absent | medaka |
| AC14-41 | 5 | Undetermined | 5 (match) | - | t010 / t010 (match) | R / present | S/S / absent | medaka |
| AC15-06 | 3028 | 3028 | 3028 (match) | - | t9432 / t9432 (match) | S / absent | S/S / absent | medaka |
| OF20-25 | 30 | 30 | 30 (match) | - | t012 / t012 (match) | R / present | S/S / absent | medaka |
| CP18 | 3021 | 3021 | 3021 (match) | - | t359 / t359 (match) | S / absent | S/S / absent | medaka |
| OF39-02 | 352 | 352 | 352 (match) | - | t3380 / t3380 (match) | S / absent | S/S / absent | medaka |
| V14 | 151 | Undetermined | no ST (partial allele matches) (MISMATCH) | pta 421? (Sanger ST: 49); yqiL 370? (Sanger ST: 59) | t2211 / t2211 (match) | S / absent | S/S / absent | medaka |
| OF21-07 | 97 | 97 | 97 (match) | - | t359 / t359 (match) | R / present | S/S / absent | medaka |
| OF21-04 | 87 | 87 | 87 (match) | - | t216 / t216 (match) | S / absent | S/S / absent | medaka |
| CR92 | 7083 | 7083 | no ST (partial allele matches) (MISMATCH) | pta 421? (Sanger ST: 49); yqiL 370? (Sanger ST: 59) | t529 / t529 (match) | S / absent | S/S / absent | medaka |

## Soft checks (genes named in the paper's text)

| Isolate | Tet / tet(K) | Ery / erm | Lin / lnu(G) | SCCmec | agr | AMR genes (AMRFinderPlus, type AMR) |
|---|---|---|---|---|---|---|
| AC06-110 | S / absent | R / erm(T) | I / absent | not_typeable (mecA no) | I | erm(T),glpT_A100V,glpT_F3I,mepA,murA_D278E,murA_E291D,tet(38) |
| OF01-07 | S / absent | S / absent | I / absent | not_typeable (mecA no) | I | mepA,tet(38) |
| AC12-45 | R / present | S / absent | S / absent | not_typeable (mecA no) | I | blaI,blaR1,blaZ,mepA,tet(38),tet(K) |
| OF10-16 | S / absent | S / absent | S / absent | not_typeable (mecA no) | I | blaI,blaR1,blaZ,fosB,mepA,murA_G257D,tet(38) |
| AC14-18 | S / absent | S / absent | I / absent | not_typeable (mecA no) | I | blaI,blaZ,fosB,mepA,tet(38) |
| AC05-54 | S / absent | S / absent | S / absent | not_typeable (mecA no) | II | blaI,blaR1,blaZ,fosB,mepA,tet(38) |
| AC14-41 | S / absent | S / absent | S / absent | not_typeable (mecA no) | II | blaI,blaR1,blaZ,fosB,mepA,tet(38) |
| AC15-06 | S / absent | S / absent | S / absent | not_typeable (mecA no) | I | mepA,tet(38) |
| OF20-25 | S / absent | S / erm(A) | I / absent | not_typeable (mecA no) | III | ant(9)-Ia,blaI,blaPC1,blaR1,erm(A),fosB,glpT_A100V,glpT_V213I,mepA,murA_D278E,murA_E291D,tet(38) |
| CP18 | S / absent | S / absent | I / absent | not_typeable (mecA no) | I | mepA,tet(38) |
| OF39-02 | S / absent | S / absent | I / absent | not_typeable (mecA no) | I | mepA,tet(38) |
| V14 | S / absent | S / absent | R / present | not_typeable (mecA no) | II | glpT_A100V,glpT_L27F,lnu(G),murA_E291D,murA_T396N,tet(38) |
| OF21-07 | S / absent | S / absent | S / absent | not_typeable (mecA no) | I | blaI,blaR1,blaZ,mepA,tet(38) |
| OF21-04 | S / absent | S / absent | I / absent | not_typeable (mecA no) | I | glpT_A100V,mepA,murA_E291D,murA_T396N,tet(38) |
| CR92 | S / absent | S / absent | I / absent | not_typeable (mecA no) | II | glpT_A100V,glpT_L27F,mepA,tet(38) |

## Racon (pilot) vs Medaka, same isolates (not part of the counts above)

| Isolate | Sanger ST | Polisher | ST (status) | Alleles | spa | AMR genes | Contigs | Total length |
|---|---|---|---|---|---|---|---|---|
| AC05-54 | 5957 | racon | - (NOVEL) | arcC(484) aroE(4) glpF(1) gmk(4) pta(12) tpi(659) yqiL(10) | t548 | blaI,blaR1,blaZ,fosB,mepA,tet(38) | 2 | 2852902 |
| AC05-54 | 5957 | medaka r941_min_hac_g507 | 5957 (PERFECT) | arcC(1) aroE(4) glpF(1) gmk(4) pta(12) tpi(659) yqiL(10) | t548 | blaI,blaR1,blaZ,fosB,mepA,tet(38) | 2 | 2853450 |
| AC15-06 | 3028 | racon | 3028 (PERFECT) | arcC(3) aroE(317) glpF(1) gmk(184) pta(1) tpi(5) yqiL(3) | t9432 | mepA,tet(38) | 1 | 2751481 |
| AC15-06 | 3028 | medaka r941_min_hac_g507 | 3028 (PERFECT) | arcC(3) aroE(317) glpF(1) gmk(184) pta(1) tpi(5) yqiL(3) | t9432 | mepA,tet(38) | 1 | 2751853 |

Values from the paper: expected.tsv (Tables S3, S5, S7 of the supplement; CC BY 4.0). blaZ_inferred and the mecA expectation are inferences, see README.md.
