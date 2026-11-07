# Validation set: Chakrawarti et al. 2024 (S. aureus, Vermont dairy farms)

This folder describes an external validation of ARVA's Oxford Nanopore-only
pipeline. It uses 15 *Staphylococcus aureus* isolates from a published study
whose raw reads are public and whose expected results (Sanger MLST, spa types,
phenotypic AST) are in the article's supplement.

No reads or assemblies are stored here. The folder holds the isolate list,
the expected values copied from the paper and their provenance, the runner
(`run_validation.py`), the comparison script (`compare.py`) and ARVA's
per-isolate results (`results/<isolate>.json`, small JSON summaries with
provenance) and concordance (`results/concordance.md`, `.tsv`).

## Source

Chakrawarti A, Eckstrom K, Laaguiby P, Barlow JW. Hybrid Illumina-Nanopore
assembly improves identification of multilocus sequence types and antimicrobial
resistance genes of *Staphylococcus aureus* isolated from Vermont dairy farms:
comparison to Illumina-only and R9.4.1 nanopore-only assemblies.
*Access Microbiology* 2024;6(3):000766.v3.

- DOI: 10.1099/acmi.0.000766.v3 (earlier versions: .v1, .v2)
- PMCID: PMC11077346; PMID: 38725589
- BioProject: PRJNA983748 (BioSamples SAMN36020147 to SAMN36020208 for the 62 study isolates; the BioProject holds 101 samples and 202 runs in total)

### Licence

- Article: Creative Commons Attribution 4.0 (CC BY 4.0). The Crossref record
  gives the licence URL `https://creativecommons.org/licenses/by/4.0/`. The
  JATS full text (Europe PMC) says "Copyright © 2024 The Authors. This is an
  open-access article distributed under the terms of the Creative Commons
  Attribution License."
- Supplement (`acmi-6-00766-s001.xlsx`): it has no licence statement of its
  own. It is published with the article as part of the same package, so we
  treat it as covered by the article's CC BY 4.0.
- What this folder copies: the few values needed for comparison (ST, spa type
  and AST S/I/R for 15 of the 62 isolates, from Tables S1, S3, S5 and S7),
  with this attribution. The full supplement is **not** copied into the
  repository. CC BY would allow it, but it is not needed. Fetch it from the
  URL below.

## Provenance (retrieved 2026-11-07)

| What | URL | sha256 |
|---|---|---|
| Article metadata (Europe PMC) | `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1099/acmi.0.000766.v3&format=json&resultType=core` | – |
| Full text JATS XML (Methods, Table 1) | `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11077346/fullTextXML` | `e8a86e06d1a3357a43ac6a661cbadff661cc5c1fa7dfc484edf93b5d1a19f161` |
| Licence metadata (Crossref) | `https://api.crossref.org/works/10.1099/acmi.0.000766.v3` | – |
| Supplementary files zip (Europe PMC) | `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11077346/supplementaryFiles` | `5fec17949e5b0a846be52337a5d2f04d1c5572619fdf2db304754dd6f4499a10` |
| `acmi-6-00766-s001.xlsx` (inside that zip; 418,772 bytes, the same size the PMC XML records) | as above | `7b94ea7f2d7cd0868bb639367fdb1a5c31f499dea1a97187723e5011ac5b79a9` |
| ENA run report | `https://www.ebi.ac.uk/ena/portal/api/filereport?accession=PRJNA983748&result=read_run&fields=run_accession,experiment_accession,sample_accession,sample_alias,library_name,instrument_platform,instrument_model,library_layout,read_count,base_count,fastq_ftp,fastq_bytes,fastq_md5&format=tsv` | `075b8ebd687dc5f2870c28d044374c4665f32ef66eb6a4a27a808156b624d2d1` (this report is generated on request and may change) |

The PMC link (`https://pmc.ncbi.nlm.nih.gov/articles/PMC11077346/bin/acmi-6-00766-s001.xlsx`)
returned a reCAPTCHA page from this environment instead of the file. We
therefore used the Europe PMC supplementaryFiles endpoint.

Supplement sheets (checked with openpyxl): Table S1 (accessions and reads),
S2 (BUSCO), S3 (MLST predictions), S4 (MLST errors), S5 (spa types), S6 (spa
errors), S7 (AST phenotypes), S8 (folP variants), Figure S1 (heatmap, an
embedded PNG with no cell data) and Figure S2 (contig counts). Table S1 lists
SRA **experiment** accessions (SRX). Each SRX was mapped to its run (SRR)
through the ENA report. For all 15 isolates, the ENA `sample_accession` equals
the BioSample in Table S1 for both the ONT run and the Illumina run.

## How the data were produced (from the paper's Methods)

- ONT: GridION, R9.4.1 flow cell FLO-MIN106. Kits SQK-LSK109 with barcoding
  kits EXP-NBD104, EXP-NBD114 and EXP-NBD196 (several batches, at least 20
  samples per flow cell, 72 h runs). **High accuracy (HAC) basecalling with
  Guppy v4.0.11.** The FASTQ headers in ENA/SRA have been rewritten
  (`@SRRxxxx.N <read uuid>/1`), so they carry no basecall-model tag.
- Illumina: MiniSeq paired-end reads (ENA `instrument_model`), SeqOnce
  RhinoSeq and Nextera XT library preparation.
- Paper's ONT-only pipeline (ONT-Asm): NanoFilt v2.7.1 `-l 1000 -q 10`, then
  Flye v2.3.1 with genome size 2.8 Mb, then Rebaler v0.2.0, then Medaka
  v1.0.3. The paper does not name the Medaka model.
- Hybrid (Hyb-Asm): the ONT-Asm polished with Pilon v1.23 (Bowtie2 v2.4.2,
  Samtools v1.9). Illumina-only (Illu-Asm): Unicycler v0.5.0 with defaults.
- Typing: mlst v2.19.0. spaTyper v1.0 (the CGE web server). Resistance genes:
  ABRicate v1.01 with CARD, ResFinder, NCBI AMRFinderPlus, MEGARES 2.0 and
  ARG-ANNOT.
- Gold standard for ST: Sanger sequencing of the 7 MLST amplicons; new
  alleles and STs were assigned by the PubMLST curator. ST7083 is the novel ST
  (Table S3 note).

## Medaka model decision

The reads are R9.4.1 (FLO-MIN106, GridION) basecalled with Guppy 4.0.11 HAC.
Medaka has no model trained for exactly Guppy 4.0.11 on MinION/GridION.
`r941_prom_high_g4011` exists, but it is for PromethION.

- Under medaka 1.x's rule ("the highest model version not newer than the
  basecaller"), the model would be `r941_min_high_g360`. That was very likely
  the default of the Medaka 1.0.3 the authors used, although the paper does not
  say so.
- The installed medaka is 2.1.1. Its `medaka/options.py` lists
  `r941_min_high_g360` under `deprecated_models`: "Previous models that have
  not been converted to v2.0 format ... use v1.x". It cannot be loaded.
- In medaka 2.1.1 the R9.4.1 MinION/GridION consensus models are
  `r941_min_fast_g507`, `r941_min_hac_g507` and `r941_min_sup_g507`. Its own
  basecaller mapping sends `dna_r9.4.1_e8_hac@v3.3` to `r941_min_hac_g507`.

**Decision: use `r941_min_hac_g507`**. It matches the chemistry (R9.4.1),
the device class (`min`, which covers GridION) and the accuracy tier (HAC), but
it was trained on Guppy 5.0.7 HAC output, not 4.0.11. Record this as a known
deviation from the paper's pipeline. Two things to note:

1. The installed medaka package ships only R10.4.1 model files
   (`medaka/data/`), and ARVA does not let Medaka download models itself.
   The model is registered in ARVA's Database Manager (kind `medaka_model`)
   through ARVA's own API: `run_validation.py` asks for the download plan
   (`POST /api/v1/databases/medaka-models/plan`) and confirms the download
   (`POST /api/v1/databases/medaka-models/download` with the plan's SHA-256,
   size and Medaka's licence), as a user would in the Databases section. ARVA
   fetches `r941_min_hac_g507_model_pt.tar.gz` from the medaka **v2.1.1** tag
   (`https://media.githubusercontent.com/media/nanoporetech/medaka/v2.1.1/medaka/data/r941_min_hac_g507_model_pt.tar.gz`),
   1,502,971 bytes, SHA-256
   `6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb268ef07ac7680ac26` (the
   tag's Git LFS pointer), checks the archive and lets medaka load it once.
   The runner refuses a registered model with any other checksum. The model
   must be passed explicitly, because these reads carry no basecall-model tag
   for ARVA's automatic mapping (ARVA's plan reports `no_basecall_model`).
2. If a medaka 1.x environment were available, `r941_min_high_g360` would
   reproduce the paper more closely. We did not set one up: disk is limited
   and 1.x needs TensorFlow.

## Methods of the ARVA run (`run_validation.py`)

Everything goes through ARVA's HTTP API, one isolate at a time (the disk is
small): download the ONT FASTQ from ENA (md5 and size checked), import it
into a sample of the project "Validation Chakrawarti 2024", run the steps
below, write `results/<isolate>.json`, delete the FASTQ and the sample.
Isolates that already have a result are skipped, so the run resumes.

| Step | ARVA | Paper (ONT-Asm) |
|---|---|---|
| Read filter | Filtlong `--min_length 1000 --min_mean_q 90` (the same two thresholds as NanoFilt `-l 1000 -q 10`; see `FILTER_NOTE` in the runner) | NanoFilt v2.7.1 `-l 1000 -q 10` |
| Assembly | Flye `--nano-raw` (Guppy 4.0.11 reads are pre-Guppy5), `--genome-size 2.8m` | Flye v2.3.1, genome size 2.8 Mb |
| Polishing | Medaka 2.1.1, model `r941_min_hac_g507` registered from medaka v2.1.1 (SHA-256 `6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb268ef07ac7680ac26`), one round on the Flye draft | Rebaler v0.2.0, then Medaka v1.0.3 (model not stated) |
| Typing | mlst; spaTyper, sccmec, AgrVATE (ARVA's S. aureus typing) | mlst v2.19.0; spaTyper v1.0 (CGE) |
| Resistance genes | AMRFinderPlus `--organism Staphylococcus_aureus` | ABRicate v1.01 (CARD, ResFinder, NCBI, MEGARES 2.0, ARG-ANNOT) |

Deviations, recorded in every result (`deviations`): the Medaka model is
`r941_min_hac_g507` (trained on Guppy 5.0.7 HAC output) because the medaka
1.0.3 models (`r941_min_high_g360` and older) are not loadable in medaka 2;
there is no Rebaler step. There is no fallback polisher: if ARVA refuses
Medaka or Medaka fails, the isolate is written as `results/<isolate>.failed.json`
with the reason. Each result records the model actually used
(`medaka_model`: name, source `registered`, SHA-256, database record, how it
was registered), taken from the polishing job's own provenance.

The ENA FASTQ keeps its name (`<run>_1.fastq.gz`). ARVA no longer takes a
lone long-read file named `_1` as mate R1 of a pair; the import's `read_mate`
and `mate_note` are recorded, and an isolate whose file is still marked as a
mate fails with that reason.

Run (PostgreSQL and Redis running):

```
apps/api/.venv/bin/python -I validation/chakrawarti2024/run_validation.py --start-arva
apps/api/.venv/bin/python -I validation/chakrawarti2024/compare.py
```

### Racon pilot (`results/racon-pilot/`)

The pilot (AC05-54 and AC15-06) ran before ARVA could register an R9.4.1
Medaka model, so ARVA refused `r941_min_hac_g507` (HTTP 400, recorded in
those files) and the pilot polished with Racon (minimap2 `map-ont`, ARVA's
Racon defaults) instead. Those two results are kept in
`results/racon-pilot/` for a Racon-vs-Medaka comparison. `compare.py`
never counts them in the concordance; it lists them beside the Medaka
results of the same isolates in a separate section of
`results/concordance.md`. In the pilot, AC15-06 gave ST3028 (match) and
AC05-54 a novel profile (arcC allele 484 instead of 1, so no ST5957).

## Isolate selection (15)

The 62 isolates carry exactly 15 distinct Sanger STs. The set takes one
isolate per ST (5, 7, 8, 30, 72, 87, 97, 151, 352, 398, 2187, 3021, 3028, 5957
and the novel 7083). When an ST had several isolates, the choice followed these
priorities:

1. Milk isolates (BTM = bulk tank milk, CQM = composite quarter milk) over
   human or hock-skin isolates. 11 of the 15 are milk isolates. ST7, ST72,
   ST398 and ST5957 occur only in human samples in this study.
2. Mix concordant and discordant ONT-only ST calls. 6 of the 15 were wrong in
   the paper's ONT-only assembly:
   - AC06-110: called as ST753 (wrong arcC allele), the only incorrect call in
     the paper.
   - OF01-07, AC12-45, OF10-16, AC14-41, V14: "Undetermined".
3. Mix penicillin phenotypes: 7 R and 8 S. The set also covers erythromycin R
   (AC06-110), tetracycline R (AC12-45), lincomycin and pirlimycin R (V14),
   and a pan-susceptible isolate (AC15-06).
4. Smaller ONT FASTQ files when the other priorities left a choice.

The per-isolate reason is in `isolates.tsv`.

**Total ONT download: 6,120,615,791 bytes (6.12 GB / 5.70 GiB) for the 15
runs.** The largest single file is 752,879,819 bytes (CP18). Download, run and
delete one isolate at a time.

## Files

- `isolates.tsv`: isolate, source, farm, BioSample, ONT SRX/SRR, ONT FASTQ
  URL (ENA HTTPS), md5, bytes, read and base counts, instrument, Illumina
  SRX/SRR with FASTQ URLs, md5s and bytes (for a later hybrid comparison), and
  the reason the isolate was chosen.
- `expected.tsv`: values from the supplement:
  - `sanger_st`: Table S3 "MLST" column, the Sanger gold standard.
  - `ont_asm_st_paper`, `illu_asm_st_paper`, `hyb_asm_st_paper`: Table S3.
  - `spa_hyb_asm` (hybrid assembly, the reference used here), plus
    `spa_ont_asm` and `spa_illu_asm`: Table S5.
  - `cc_table_s7`: the "CC" column of Table S7, as given.
  - `ast_*`: S/I/R for the 20 antibiotics in Table S7.
  - `blaZ_inferred`, `mecA_paper`, `per_isolate_genes_in_paper`: see below.

### Genes per isolate

The paper does **not** tabulate resistance genes per isolate. They appear only
in heatmap figures: Fig. 3 shows 20 isolates, and Fig. S1, an image in the
supplement, shows all 62. Neither was transcribed. `per_isolate_genes_in_paper`
is therefore `heatmap_figure_only`.

- `blaZ_inferred` is an **inference**, not a reported per-isolate call. Table 1
  says blaZ was present in every penicillin-resistant isolate and absent from
  every penicillin-susceptible one. The column is "present" where Table S7
  gives penicillin R and "absent" otherwise.
- `mecA_paper = not_reported`. mecA is not mentioned anywhere in the article.
  All 62 isolates are oxacillin S and cefoxitin S (Table S7), and Table 1 lists
  no gene for those drugs. The isolates are therefore expected to be mecA- and
  SCCmec-negative (MSSA). That expectation is our inference.

Gene and phenotype links stated in the text, usable as soft checks:

- tet(K) occurs in the tetracycline-R isolates, mostly CC7; tet(38) is in all
  genomes.
- erm(T) is in the CC398 human isolates; erm(A) is in CC30 milk isolates.
- lnu(G) is in the lincosamide-R CC151 isolates.
- fosB is in 23 genomes (CC5, CC8 and CC30).
- aac(3) is in all genomes; ant(9)-Ia is in one CC30 genome.

## What is compared

For each isolate, ARVA runs its ONT-only pipeline (Filtlong, Flye
`--nano-raw`, Medaka with the registered `r941_min_hac_g507`) and the following comparisons are made:

1. **MLST** (ARVA `mlst`) against the Sanger ST (gold standard) and against
   the paper's ONT-only call.
2. **spa type** (ARVA spaTyper) against the hybrid-assembly spa type. The paper
   reports that ONT-Asm and Hyb-Asm agree on spa for all 62 isolates.
3. **Resistance genes** (AMRFinderPlus; the runner does not run ABRicate) against the S7 phenotypes:
   - blaZ against penicillin;
   - mecA against oxacillin and cefoxitin (all S);
   - tet(K) against tetracycline;
   - erm against erythromycin;
   - lnu(G) against lincomycin and pirlimycin.
4. Optionally, SCCmec (expected absent) and AgrVATE (no reference values in the
   paper).

## Inconsistencies inside the paper (record them; do not "fix" them)

- **ONT-only MLST:** Table S3 has 18 "Undetermined" and 1 incorrect call (19
  discordant, 43 of 62 correct). The text says "19 undetermined and one
  incorrectly typed" and "42 (68%)" correct.
- **Penicillin:** Table 1 has 28 R with blaZ and 34 S without it. Table S7 has
  26 R and 36 S. The text says "Twenty-six genomes had all three genes [blaZ,
  blaI, blaR] and were phenotypically resistant to penicillin".
- **Erythromycin:** Table 1 has 8 R. Table S7 has 7 R, all CC398 (AC06-*). The
  text says the erm(A) CC30 milk isolates were erythromycin R, but Table S7
  gives the CC30 isolates (OF20-25, AC18-18) erythromycin S.
- **Lincomycin:** Table 1 has 5 R. Table S7 has 6 R (AC06-111 in addition to
  the five CC151 isolates). Pirlimycin R is 5 in both.
- **CC column:** the S7 "CC" column does not always follow the ST, for
  example ST72 is listed as CC8 and ST7083 as CC151. It is kept as given.
- **Table S4** lists "OF10-26", which is most likely OF10-16 (no isolate
  OF10-26 exists).
- **Isolate names vary between sheets.** Examples: OF01-07 / OF1-07 / "OF 1-07";
  AC15-06 / AC15-6; AC07-01 / AC07-1; V27-LhB / V27; V41_2066-3 / V41_2006-3 /
  V41; OF17-34 / OF-17-34. ENA `sample_alias` differs too (Jun = JUNEAU,
  Hkl = HOCKKL). We matched names by BioSample and SRX, not by name.
