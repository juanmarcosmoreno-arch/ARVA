# Variant-calling fixtures and validation

## Usage texts (bcftools 1.19, Ubuntu bcftools 1.19-1build2, htslib 1.19)

`bcftools_<command>_usage_1.19.txt` were written by `bcftools mpileup` (no argument: its `-h` takes a value) and
`bcftools <call|norm|filter|csq|index> -h`; they exit with status 1 or 255. `bcftools_version_1.19.txt` is
`bcftools --version`. The adapter's option checks (`HELP_FLAGS`) are tested against them.

Facts read from the bcftools 1.19 source (`csq.c`, tag 1.19 on GitHub) and the online manual: csq's GFF3 must be
Ensembl-style (gene `ID=gene:…;biotype=…`, transcript `ID=transcript:…;Parent=gene:…;biotype=…`, CDS
`Parent=transcript:…`); csq translates with the standard genetic code (`gencode` table) and only flags start_lost
when the reference's first codon translates to M (ATG).

## SIMULATED data (tests)

`tests/test_variant_tools.py` and `apps/api/tests/test_variants_api.py` build their genomes and reads at run time;
every read name contains SIMULATED or SYNTHETIC. They test that planted variants are recovered, not biology:

* a 30 kb random genome with two genes (one starting ATG on +, one starting GTG on −), six planted SNPs, a 2-bp
  insertion and a 3-bp deletion; error-free 2 × 150 bp pairs (BWA-MEM → bcftools, every planted variant called and
  annotated; the GTG start change reported as `1V>1M` and marked) and long reads (minimap2 map-ont → bcftools ont
  profile: the SNPs, no indels);
* the synthetic polishing draft (`scripts/make_polishing_draft.py`: 7 substitutions, 4 insertions, 5 deletions)
  called with the synthetic genome's Illumina-like reads (16 records: 7 SNPs, 5 insertions, 4 deletions; two indels
  at short repeats fail LowAltFraction) and Nanopore-like reads (the 7 SNPs; one at 24/27 reads fails
  LowAltFraction).

## REAL public read sets (validation run, not a test fixture)

Reads (ENA, MD5 checked, not committed; `/root/.arva-testdata/genomes/reads/README.md`): DRR250760, DRR257875
(Illumina MiSeq) and DRR272507 (HiSeq X Five), S. aureus. Reference: NCBI RefSeq GCF_000013465.1 (USA300_FPR3757;
chromosome and three plasmids, SHA-256 d5fec7a6…dd35) with its cached real Bakta 1.12.2 annotation (2,698 CDS written
for csq, none left out). ARVA's `variant_calling` job with the defaults (Illumina profile, MAPQ ≥ 60, base quality
≥ 13, QUAL ≥ 100, depth ≥ 10, alternative-allele fraction ≥ 0.9), 4 threads:

| run | reads aligned | callable (depth ≥ 10) | records | passing | passing SNPs / ins / del | run time |
|---|---|---|---|---|---|---|
| DRR250760 | 91.8 % | 88.3 % | 53,943 | 50,557 | 50,199 / 161 / 197 | 104 s |
| DRR257875 | 94.2 % | 90.9 % | 23,417 | 21,145 | 20,944 / 93 / 108 | 122 s |
| DRR272507 | 96.3 % | 96.8 % | 203 | 161 | 150 / 2 / 9 | 68 s |

DRR272507 is close to USA300 (161 passing variants); the other two are distant lineages. SNP matrix of the three:
61,532 SNP sites, 58,019 with a base in every sample; distances 48,941 (DRR250760–DRR257875), 49,948
(DRR250760–DRR272507) and 20,869 (DRR257875–DRR272507). csq reported start_lost 12 and 4 times and marked 5 and 5
changes of GTG/TTG start codons in the two distant samples; 328 and 87 passing variants lie after a stop (`*`).

**Cross-check with Snippy 4.6.0** (FreeBayes 1.3.6, inside AgrVATE's Bioconda environment; `snippy --cpus 2 --ref
GCF_000013465.1.fna --R1 … --R2 …`, its defaults) on DRR250760: Snippy's substitutions (`snps.subs.vcf`, SNPs and the
bases changed in its MNP and complex records) 47,183; ARVA's passing SNPs 50,199; shared 45,852 (Jaccard 0.89);
4,347 only in ARVA, 1,331 only in Snippy (336 of these were called by ARVA but failed a filter). The two pipelines
differ in aligner post-processing (Snippy removes reads with long soft clips, samclip), caller and QUAL scale; the
differences were not investigated site by site.
