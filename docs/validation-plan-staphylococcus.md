# Validation plan: ARVA on *Staphylococcus*

Status: plan (October 2026). Nothing here has been run yet. Every accession, DOI and number below was checked against
primary sources (NCBI Datasets and E-utilities, ENA, Crossref, Europe PMC full texts, culture-collection and journal
pages) on 2026-10-28/29. Items that could not be confirmed are listed at the end and must be checked again before use.

## 1. What has to be shown

ARVA runs published tools; what reviewers will judge is what ARVA itself adds (statistics, defaults, recommendations,
parsing of tool outputs, warnings) and whether the platform as a whole gives correct results. Three levels:

1. **Equivalence.** For each module, ARVA's result equals a direct command-line run of the same tool version with the
   same parameters and inputs (identical files, or identical up to documented thread non-determinism, e.g. Flye).
   ARVA's own numbers (N50, GC, depth, read statistics) equal independent tools (SeqKit, QUAST, samtools).
2. **Accuracy against a truth.** End to end (raw reads → QC → assembly → polishing → annotation), on public strains with
   curated reference genomes, using the community's metrics (section 4).
3. **Typing and AMR concordance** (after Phase 5): MLST/CC, spa, SCCmec and AMR/virulence calls against reference
   typing and phenotypic susceptibility testing.

Plus what a software paper needs: a head-to-head comparison with existing pipelines, a usability study, installation
tests on macOS (Intel and Apple Silicon), Linux and Windows WSL2, offline operation, and archived code and data.

## 2. Public datasets

### Tier A — curated truth genomes already used in benchmarks

| Strain | Lineage | Truth | Raw reads | Source |
|---|---|---|---|---|
| JKD6159 | ST93 CA-MRSA | GCF_000144955.2 (chromosome CP002114.3, 2,818,670 bp; plasmid pSaa6159 CP002115.1, 20,730 bp). Rebuilt with Trycycler + Medaka + Polypolish + POLCA and confirmed independently from R9.4.1+Illumina and PacBio. Use version .2, not the 2010 .1 | Illumina NextSeq 500 SRR21386014; ONT R10.4 SRR21386012 (raw SRR21386013); ONT R9.4.1 SRR21386010 (raw SRR21386011); PacBio SRR21386009 (raw ERR1213694). BioProject PRJNA50759, BioSample SAMN02604217. Mirror: figshare doi:10.26180/21007033.v1 (CC BY 4.0) | Wick et al. 2023, Microbiol Resour Announc 12(2):e01129-22; sample data of Wick, Judd & Holt 2023 PLoS Comput Biol 19(3):e1010905; reused by Hybracter (Microb Genom 2024, doi:10.1099/mgen.0.001244) |
| BPH2947 | ST239, spa t037 | GCF_045345275.1 (CP149492–CP149494, 3,079,933 bp), Trycycler + Polypolish + Pypolca + manual curation. Variant truth set: Zenodo doi:10.5281/zenodo.10867171 | ONT R10.4.1, 5 kHz, Dorado 0.5.0 v4.3.0 models (PRJNA1087001): sup SRR28370694, hac SRR28370638, fast SRR28370690, duplex sup SRR28370684, duplex hac SRR28370677. POD5: doi:10.26188/25495075.v1. Illumina from the same extract is not public (only MiSeq ERR2137244, ERR2929425 from 2018/2019) | Hall et al. 2024, eLife 13:RP98300 |
| MRSA252 | ST36 (CC30), EMRSA-16, SCCmec II | Classic GCF_000011505.1 (Sanger). Corrected de novo reference (Trycycler 0.5.4): figshare doi:10.6084/m9.figshare.25472167.v1 | PRJEB51164: MiSeq ERR9285290; R9.4.1 hac ERR8958852, sup ERR8958851; R10.4 hac ERR8958848, sup ERR8958843, duplex ERR8958837; R10.4.1 (Kit 14, 5 kHz) Dorado sup ERR12813215. The 2023 runs share one DNA extract; R10.4.1 used a new one | Sanderson et al. 2023 Microb Genom doi:10.1099/mgen.0.000910; 2024 doi:10.1099/mgen.0.001246 |

### Tier B — lineage coverage: ONT + Illumina with a modern complete genome

| Strain | Lineage | Reads | Genome |
|---|---|---|---|
| USA300 JE2 (BEI NR-46543) | ST8 CA-MRSA, plasmid-cured LAC | ONT R10.4.1 RBK114.96 SRR40445792; NovaSeq SRR40445793 (library built with a Twist custom panel; use only the `_WT` runs of SAMN62758785) | GCF_061235025.1; independent PacBio+MiSeq GCF_002085525.1 |
| USA300 FPR3757 (ATCC BAA-1556) | ST8, SCCmec IV, spa t008 | ONT SQK-LSK109 SRR26302847; MiSeq SRR26302845 (labelled AMPLICON) | Hybrid GCF_032809245.1 with all 3 plasmids (3.1, 4.4, 37.1 kb): plasmid-recovery test. Classic GCF_000013465.1 |
| UAMS LAC | ST8 | ONT SRR13292383; HiSeq 2500 SRR13292384 (same gDNA) | GCF_015475575.1 |
| Mu50 (ATCC 700699) | ST5 VISA, SCCmec II | ONT SRR24062758; MiniSeq SRR24061434 (KU Leuven, PRJNA952137) | GCF_046741735.1; classic GCF_000009665.1 |
| ATCC 29213 | ST5 MSSA, EUCAST/CLSI QC strain | ONT SRR24062755; MiniSeq SRR24061431 | GCF_046741715.1; independent GCF_022870465.1 and GCF_022832775.1 share the 46,979-bp plasmid |
| ATCC 25923 | ST243 MSSA, CLSI disk QC | ONT R9.4.1 SRR23290061; MiSeq SRR23290088 (PRJNA929966) | Trycycler GCF_028596245.1 (Johnson et al. 2023 Microb Genom doi:10.1099/mgen.0.001024); PacBio GCF_000756205.1. The paper lists two plasmids, the deposit one |
| ATCC 43300 | MRSA, SCCmec II, spa t007 | ONT SRR24062762; MiniSeq SRR24061438 | GCF_046741765.1 (only complete genome: no independent truth) |

### Tier C — PacBio + Illumina or ONT only

| Strain | Reads | Genome |
|---|---|---|
| N315 (ST5) | PacBio ERR12638825; Illumina ERR12639079 (PRJEB72281) | Classic GCF_000009645.1 |
| MW2 (ST1, USA400) | ONT only SRR33600002 (~750x) | ONT-only Flye GCF_050908105.1 (2,820,460 bp vs 2,820,462 bp for BA000033.2) |
| *S. epidermidis* ATCC 12228 (ST8) | FDAARGOS_913: PacBio SRR12047977/SRR12047978; HiSeq 4000 SRR12047979 | GCF_016026915.1. Plasmid counts differ between assemblies (1 to 7) |
| *S. epidermidis* RP62A (ST10) | PacBio ERR3623911 (bax.h5 only, needs conversion); MiSeq ERR1191814 | GCF_902509525.1 |

### Gaps the user's own strains must fill

No public ONT + Illumina data from a recognised reference stock exist for **CC22** (EMRSA-15), **CC398**, or
unmodified **coagulase-negative staphylococci**. Several classic references (NCTC 8325, Newman, COL, MSSA476) have no
usable long reads.

### Typing and AMR phenotype sets (Phase 5)

- CDC & FDA AR Isolate Bank panels with CLSI antibiograms in the BioSamples: BORSA (n=34: 23 *mecA*+, 9 neither,
  2 *blaZ*-*mecC*; PRJNA316321, PRJNA391514), DTD (n=30), VISA (n=14), TLZD (n=30).
- Gordon et al. 2014 J Clin Microbiol 52(4):1182-1191, PRJEB5261 / ERP004655.
- ResFinder 4.0 Danish *S. aureus* set PRJEB37586 (100 MiSeq runs; disk diffusion with EUCAST clinical breakpoints).
- SCCmecFinder set PRJEB22380 (93 runs).
- Five-laboratory R10.4.1 ring trial (Dabernig-Heinz et al. 2024 J Clin Microbiol 62(9):e00628-24), PRJNA1091452:
  18 *S. aureus* with Illumina and cgMLST truth.
- Bioplatforms sepsis set PRJEB29881: five complete PacBio+MiSeq genomes, including BPH2900 (ST22).

## 3. The user's own strains

Collect per strain:
- Raw reads: FASTQ (and POD5 if available), kit, flow cell (R9.4.1/R10.4.1), sampling rate, basecaller and model;
  Illumina run details. Ideally ONT and Illumina from the same DNA extract.
- Results of the current pipeline (assemblies, annotation, typing) with tool versions, as the comparison.
- Phenotype: MICs by ISO 20776-1 broth microdilution and/or EUCAST disk diffusion, interpreted with EUCAST v16.1
  breakpoints (valid from 2026-06-24) and ECOFFs; cefoxitin 30 µg screen (S ≥22 / R <22 mm; MIC >4 mg/L = methicillin
  resistant); penicillin 1-unit disk with zone-edge test; confirm discordances with *mecA*/*mecC* PCR or PBP2a and
  retest them. QC strains: ATCC 29213 (cefoxitin MIC target 2 mg/L, range 1-4; 30 µg disk 27 mm, range 24-30) and
  NCTC 12493 (*mecA*+; cefoxitin disk range 14-20 mm).
- Existing typing (spa by Sanger, PCR) if any; anonymised origin and date.
- Before submission: reads in ENA/SRA, antibiograms in the BioSamples; ethics approval if they are clinical isolates.

## 4. Metrics (as used by the source benchmarks)

- **Structure:** replicons recovered and circularised; longest alignment as % of each replicon (>100 % extra
  sequence, <100 % missing); large indels >60 bp; plasmid recovered when within 250 bp in length and 0.1 % GC, with
  dnadiff aligned bases within 250 bp (Hybracter rule).
- **Base level:** SNVs and indels against the truth with dnadiff, reported per 100 kbp, or as a Q-score with the
  worst-100-bp identity; for polishing, errors fixed vs introduced across depths (0.1-50x, as in Pypolca).
- **Relative indicators only** (never proof of correctness): QUAST, BUSCO, IDEEL, ALE, Inspector, CRAQ.
- **Variants:** precision, recall and F1 with vcfdist (BPH2947 truth set).
- **Typing:** cgMLST allele differences vs Illumina; MLST/spa/SCCmec agreement and typeability.
- **AMR:** per drug, numbers of resistant and susceptible isolates, categorical agreement, very major errors
  (denominator: phenotypically resistant) and major errors (denominator: phenotypically susceptible) with 95 % CIs,
  sensitivity and specificity; ECOFF wild-type/non-wild-type calls. FDA 2009 AST guidance thresholds as a reference
  point: CA >89.9 %, major <3 %, very major judged on the 95 % confidence limits.
- **Resources:** runtime, peak memory and disk per step on a laptop (ARVA records threads and memory per job).
- **Reproducibility:** repeated runs; equivalence with direct command-line runs.

Cite the EUCAST subcommittee reports: Ellington et al. 2017 Clin Microbiol Infect 23(1):2-22
(doi:10.1016/j.cmi.2016.11.012) and the 2025 update, Samuelsen et al. 2026 Clin Microbiol Infect 32(7S):S1-S34
(doi:10.1016/j.cmi.2026.05.012).

## 5. Comparison with existing pipelines

Run on the same reads and score against the same truths: Bactopia, nf-core/bacass, Hybracter and Oxford Nanopore's
EPI2ME wf-bacterial-genomes (the closest local GUI; ONT data only, research-only licence, no ARM support listed).
Staph typing alone is not novel (Bactopia's staphtyper, StaphSCAN, SaLTy, SCCmecFinder, AgrVATE).

ARVA's defensible novelty is the combination: an open-source GUI that installs on a laptop and runs fully offline;
short-read, long-read and hybrid assembly, polishing, QC, annotation and a genome browser in one tool; per-step
provenance in the interface and reports (exportable, e.g. as a Workflow Run RO-Crate); plain-language explanations;
validation on *Staphylococcus*. A small usability study with target users (precedent: AMRColab, Microb Genom 2024,
doi:10.1099/mgen.0.001308) strengthens it.

## 6. Publication

- **Primary target: Microbial Genomics** (Research Article or Methods, noting the Methods and Software collection).
  Precedents: Bakta (doi:10.1099/mgen.0.000685), Hybracter, Theiagen's Terra workflows (doi:10.1099/mgen.0.001051),
  AMRColab, SaLTy (doi:10.1099/mgen.0.001250). 2025: JIF 4.5, CiteScore 7.1. Gold open access (DOAJ maximum APC
  GBP 2,203; waivers and Publish & Read agreements). All sequencing data must be public at submission, and code and
  supporting data deposited.
- **Alternatives:** GigaScience Technical Note (requires comparison with community tools, OSI licence, code and test
  data with expected outputs, RRID); Bioinformatics Original Paper (up to 7 pages; 2025 IF 5.5) or Application Note;
  NAR Genomics and Bioinformatics Application Note. The NAR Web Server issue now also accepts stand-alone applications
  with a container version (pre-submission summaries open November 2026); whether ARVA qualifies is for the editors.
- **With a clinical AMR framing (after Phase 5):** Journal of Clinical Microbiology (precedents: Gordon 2014;
  Dabernig-Heinz 2024) or Journal of Antimicrobial Chemotherapy.
- **Not advised:** Genome Biology and PLOS Computational Biology software sections (they require a clear advance over
  existing tools); BMC Bioinformatics only as a fallback.

Requirements common to these journals that ARVA does not meet yet: **an OSI-approved licence (the repository has no
LICENSE file)**, a versioned archive with a DOI (Zenodo or Software Heritage), an RRID and a bio.tools entry, test
data with expected outputs.

## 7. Licensing constraints for Phase 5 databases

- PubMLST: data submitted up to 2024-12-31 may be redistributed with citation (this is what `mlst` bundles);
  later data are for non-commercial academic or public-health use only and may not be aggregated into software.
  Contact PubMLST before shipping an updater for post-2024 data.
- Ridom SpaServer files: non-commercial use, no redistribution in products; the user downloads them, ARVA never
  ships them.
- CARD: commercial use needs written permission. AMRFinderPlus software and database are public domain;
  ResFinder/PointFinder are Apache-2.0.
- Recommended Phase 5 engines: AMRFinderPlus 4.2.7 (`--organism Staphylococcus_aureus --plus`; also unlocks Bakta's
  CDS step, which needs ≥4.2.7), `mlst`, `sccmec` (types I-XV), spaTyper, AgrVATE, ResFinder/PointFinder and Mykrobe as
  second callers, a species check (skani or sylph against GTDB) to flag *S. argenteus*, *S. schweitzeri* and
  *Mammaliicoccus*; StaphSCAN as an independent comparator.

## 8. What ARVA will automate (validation module)

1. A dataset manifest (strain, accessions, expected checksums, truth genome, licence, citation), downloaded from ENA
   only after the user confirms the size; checksums verified.
2. Runs of the ARVA pipeline and, for equivalence, the same tools called directly with the same parameters.
3. Comparisons against the truth (dnadiff, alignment-based structure checks) and between ARVA and direct runs.
4. A validation report (HTML/JSON) with every metric above, tool and database versions, and the resources used, ready
   for supplementary material.

## 9. Still unconfirmed

Which Illumina run polished the BPH2947 truth; the MRSA252 truth file name inside the figshare archives; the
chemistry of several ONT runs (FPR3757, KU Leuven 'rapid barcoding' runs, Zymo SRR7415644); clonal-complex labels and
some SCCmec types (COL, N315, MW2, LAC); causes of chromosome-length differences between old and new genomes of COL,
ATCC 25923 and FPR3757 (possible stock drift); the *S. aureus* section of the 2025 EUCAST update; ISO 20776-2:2021 full
text; CLSI M100 Ed36 values; VFDB, VirulenceFinder and SCCmecFinder database licences; Microbial Genomics word limits.
