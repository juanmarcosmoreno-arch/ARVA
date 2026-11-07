# ARVA vs Chakrawarti et al. 2024: concordance

Isolates with ARVA results: 2 of 15. Not run yet: AC06-110, OF01-07, AC12-45, OF10-16, AC14-18, AC14-41, OF20-25, CP18, OF39-02, V14, OF21-07, OF21-04, CR92.

| Comparison | ARVA matches | Notes |
|---|---|---|
| ST vs Sanger (gold standard) | 1/2 | no ST from ARVA counts as a mismatch |
| ST vs paper's ONT-only call | 1/2 | 0 more where both gave no ST |
| ST vs Sanger, isolates the paper's ONT-only assembly got wrong | 0/0 | ONT-only 'Undetermined' or wrong in Table S3 |
| spa vs hybrid assembly (Table S5) | 2/2 | |
| blaZ vs penicillin phenotype | 2/2 | blaZ expected exactly in penicillin R (Table 1; Table 1 and Table S7 disagree on the R count, see README) |
| mecA vs oxacillin/cefoxitin | 2/2 | all isolates are S: mecA expected absent |

## Per isolate

| Isolate | Sanger ST | Paper ONT ST | ARVA ST | Loci differing from the Sanger profile | spa paper / ARVA | Pen / blaZ | Oxa / mecA | Polisher |
|---|---|---|---|---|---|---|---|---|
| AC05-54 | 5957 | 5957 | NOVEL (MISMATCH) | arcC 484 (Sanger ST: 1) | t548 / t548 (match) | R / present | S/S / absent | racon |
| AC15-06 | 3028 | 3028 | 3028 (match) | - | t9432 / t9432 (match) | S / absent | S/S / absent | racon |

## Soft checks (genes named in the paper's text)

| Isolate | Tet / tet(K) | Ery / erm | Lin / lnu(G) | SCCmec | agr | AMR genes (AMRFinderPlus, type AMR) |
|---|---|---|---|---|---|---|
| AC05-54 | S / absent | S / absent | S / absent | not_typeable (mecA no) | II | blaI,blaR1,blaZ,fosB,mepA,tet(38) |
| AC15-06 | S / absent | S / absent | S / absent | not_typeable (mecA no) | I | mepA,tet(38) |

Values from the paper: expected.tsv (Tables S3, S5, S7 of the supplement; CC BY 4.0). blaZ_inferred and the mecA expectation are inferences, see README.md.
