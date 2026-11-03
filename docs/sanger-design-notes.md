# Sanger single-gene module: verified facts and design decisions (Part 0)

Checked on 2026-11-03 for the module planned in [plan-sanger.md](plan-sanger.md). Every interface fact below comes
from a tool's real `--help`, its source code at the stated version, an official page or a peer-reviewed paper, each
cited where it is used. Nothing here is product code. The user's chromatograms were used for local manual checks
only: no read, base call or consensus of the user is in this repository, only the numbers measured on them.

## 1. Reading `.ab1` files: Biopython

**Version.** Biopython 1.88 is the current release on PyPI (released 2026-08-06; wheels for CPython on
manylinux x86_64 and aarch64 and macOS arm64; sdist `biopython-1.88.tar.gz`, 19,858,058 bytes, SHA-256
`9aaa31c0bda4d059f7b2ee00bfdb5cbb73ade3057aa4b737a7cc0187091d071a`; `https://pypi.org/pypi/biopython/json`). It was
installed into a throwaway venv to read its source (`Bio/SeqIO/AbiIO.py`) and to run it. Licence: "Biopython License
Agreement", with some files dual-licensed under BSD 3-Clause (`LICENSE.rst` of the sdist: "Unless stated otherwise in
individual file headers, all Biopython's files are under the 'Biopython License Agreement'"). `AbiIO.py` itself is
dual-licensed (its header).

**What `SeqIO.read(path, "abi")` gives** (`AbiIO.py`, `AbiIterator.__next__`):

- The record's sequence is tag `PBAS2` (the base calls), and `letter_annotations["phred_quality"]` is `PCON2` (one
  quality per base, 0 to 255 by the tag table). A comment in the source says PBAS2 is "only available in 3530", but
  both files of the user (ABI 3730xl at Macrogen) and Biopython's `3730.ab1` have it.
- `record.id` is `SMPL1` (the sample name); `record.name` is the file name without `.ab1`.
- Every tag is kept raw in `annotations["abif_raw"]`, keyed by name and number: `DATA9` to `DATA12` (the processed
  trace of the four dye channels, one value per scan), `PLOC2` (the scan position of each called base's peak),
  `FWO_1` (the base of each channel, in order), `PBAS1`/`PLOC1`/`PCON1` (the instrument's edited copies),
  `MODL1`/`HCFG3` (instrument), `PDMF1` (mobility file), `SVER2` (base caller), `RUND1` (run date) and the others the
  ABIF tag table in the file lists.
- Channel to base: channel *i* of `DATA9+i` is base `FWO_1[i]`. On the two user files and `3100.ab1`
  (`FWO_1 = GATC`) the channel with the highest signal at `PLOC2` was the called base at 560 of 560 positions
  checked in each read (bases 21 to 580), which confirms the mapping on real data.
- An FSA file (no `PBAS1`/`PBAS2`) gives an empty sequence and no qualities.
- A file whose qualities are all 0 parses without error: Biopython's `310.ab1` (ABI 310) has `PCON2` of zeros. ARVA
  must treat such a read as "no usable qualities" (no quality trimming, no quality-based conflict resolution) and say
  so, like a FASTA input.

**The user's two reads** (local check, not committed):

| | 784F read | 1401R read |
| --- | --- | --- |
| Instrument, base caller | ABI 3730xl, KB 1.4.2.5, `KB_3730_POP7_BDTv3.mob` | same |
| Bases called (`PBAS2`) | 1,541 | 1,065 |
| Mean Phred, whole read | 23.1 | 32.6 |
| Trace scans (`DATA9`) | 17,925 | 12,979 |

Macrogen's `.txt` for the 784F read is exactly the `PBAS2` sequence (1,541 bases, compared in full).

**Biopython's own trimming (`"abi-trim"`)** (`AbiIO.py`, `_abi_trim`): the modified Mott algorithm, with the
parameters hard-coded (`cutoff = 0.05`, `segment = 20`); `SeqIO.read(path, "abi-trim")` offers no way to change
them. Each base scores `cutoff - 10^(-Q/10)`; the running sum is reset to 0 when it goes negative; the kept part
starts at the first base where the running sum is positive and ends just before the base where it is highest
(`seq_record[trim_start:trim_finish]`, with `trim_finish` the index of the maximum, so that base is dropped). Reads of
20 bases or fewer are returned untrimmed. This start rule is the one in the CLC Genomics Workbench 6.5 manual
(cited in the source): "the region between the first positive value of the running sum and the highest value of the
running sum". The current CLC manual describes the start differently: "the region ending at the highest value of the
running sum and starting at the last zero value before this highest score"
(`https://resources.qiagenbioinformatics.com/manuals/clcgenomicsworkbench/current/index.php?manual=Quality_trimming.html`).
The two differ when the running sum returns to zero after its first positive value: Biopython then keeps a
low-quality stretch at the start. On the user's 784F read, Biopython's abi-trim keeps bases 9 to 581 (573 bases)
while the maximum-scoring segment with the same 0.05 limit is bases 23 to 582 (560 bases).

**Decision.** Biopython 1.88 (PyPI) reads the files. ARVA does not use `"abi-trim"`: it implements the modified Mott
algorithm itself as the maximum-scoring segment (the current CLC description), with the error-probability limit shown
and editable (default 0.05, Biopython's value) and the kept range reported in 1-based coordinates of the original
read. Measured on the user's reads (1-based, inclusive):

| Limit | 784F read kept | 1401R read kept |
| --- | --- | --- |
| 0.01 | 26–581 (556 bases) | 21–585 (565 bases) |
| 0.05 | 23–582 (560 bases; mean Q 56.1, 99.3 % of bases ≥ Q20) | 15–587 (573 bases; mean Q 57.1, 99.1 % ≥ Q20) |
| 0.10 | 9–584 (576 bases) | 14–589 (576 bases) |

This agrees with the plan: the 784F read is useful up to about base 580 of its 1,541.

**Test data for `.ab1` (redistributable).** Biopython's sdist ships `Tests/Abi/` under the Biopython License
Agreement, which permits copying and redistribution with the copyright and permission notice. Useful files
(SHA-256 of the files in `biopython-1.88.tar.gz`):

| File | What it is | SHA-256 |
| --- | --- | --- |
| `3100.ab1` | ABI 3100, sample `16S_S2_1387R`: a 16S read with primer 1387R, 795 bases | `78588d824dd967a1e58a9667a8f7ca1687ba38266420bbc5a6562c1893888efd` |
| `3730.ab1` | ABI 3730, plasmid read, 1,165 bases | `e4663e4db40232576ccdda5b878dddb01ef80a3d1b032941ba053146ce53f77b` |
| `310.ab1` | ABI 310, 868 bases, all qualities 0 | `0a395d39520d24a89af4c77dd55fd7fb632e732a6da807ceb6ead0c2465cb887` |
| `no_smpl1.ab1` | no `SMPL1` tag, 164 bases | `e854b12cb8fa2cd1452f6fbc9b0928fc191bd7e964ba8822f29e3d22bdcaa49f` |
| `fake.ab1`, `empty.ab1` | invalid and empty-read files | (in the sdist) |

`3100.ab1` trimmed at 0.05 (bases 19 to 697, 679 bases) and searched against NCBI's 16S database (section 3) matches
*Staphylococcus epidermidis* NR_036904 at 99.853 % over 679 bases (100 % query coverage), with *S. epidermidis*
NR_113957, *S. saccharolyticus* and *S. caprae* at 99.705 %: a real, public staphylococcal 16S read that shows the
same limit as the user's strain. There is no public F/R pair in Biopython's set: consensus tests need a fixture built
in a documented way (for example the trimmed calls and qualities of `3100.ab1` and their reverse complement with
substituted bases), or the base calls and qualities as data, without a chromatogram.

## 2. Trimming and consensus: Biopython versus tracy

**tracy** (gear-genomics; Rausch T., Fritz M.H.-Y., Untergasser A., Benes V. (2020) Tracy: basecalling, alignment,
assembly and deconvolution of Sanger chromatogram trace files. BMC Genomics 21:230, doi:10.1186/s12864-020-6635-8).
Bioconda `tracy` 0.9.1 (BSD-3-Clause) has builds for linux-64 (`tracy-0.9.1-h3752d28_0.conda`, SHA-256
`d36691e9d0cce2168307608d245b3faa77366d7920bff2420bc035a2e8362dd7`), linux-aarch64 (`tracy-0.9.1-ha658904_0.conda`,
`4e52df1e036c4c9ccff455678f5d3d81438159ebf9b2b3a3b6ea3637ad467b6b`) and both macOS platforms
(`https://api.anaconda.org/package/bioconda/tracy`). Installed in a throwaway micromamba environment (339 MB with its
Boost 1.85 and HTSlib 1.24 dependencies) and its source read at tag v0.9.1 (commit `1d450cee`).

- `tracy` 0.9.1 lists the commands `index`, `basecall`, `align`, `decompose`, `consensus` and `assemble`. **There is
  no `trim` command** (`tracy trim` answers "Unrecognized command trim"); trimming is an option of each command.
- `tracy consensus [OPTIONS] trace1.ab1 trace2.ab1`: `-p/--pratio` (0.33, peak ratio to call a base), `-f/--fracmatch`
  (0.5), `-c/--minoverlap` (25), alignment scores `-g -10 -e -4 -m 3 -n -5`, `-t/--trim` (stringency 1 to 9; 0 = use
  the fixed sizes `-q -u -r -s`, 50 bases each by default), `-i/--intersect`, `-a/--iupac`, `-o/--outprefix`. It writes
  `<prefix>.fa`, `<prefix>.fq`, `<prefix>.txt` (a text alignment), `<prefix>.align.fa` and one `<prefix>_1st.abif` /
  `_2nd.abif` table per trace (`pos, peakA..peakT, basenum, primary, secondary, consensus, qual, trim`).
- `tracy assemble` (trim `-t` 4 by default, `-d/--called` 0.1 fraction of traces, `-r` reference-guided) and
  `tracy align`/`decompose` (`-r` reference FASTA or wild-type trace) are for many traces or variant calling.
- tracy re-calls bases from the trace (`basecall` in `abif.h`, with the peak ratio) and estimates its own qualities
  (`estimateQualities`). It reads the instrument's `PCON2` qualities but its trimming (`trim.h`, `trimTrace`) does not
  use them: it penalises 10-base windows with ambiguous secondary calls and uneven peak spacing, scaled by the
  stringency.
- `tracy decompose -a <species>` annotates variants by querying `rest.ensembl.org` (`indigo.h`): it sends data
  outside the machine and must never be used by ARVA.

On the user's pair, `tracy consensus -t 4` produced a 583-base consensus from an overlap of 514 columns with no
mismatch; it is contained in the consensus described below (which extends 8 bases further at each end).

**Decision.** For a quality-trimmed read pair, a F+R consensus with its conflicts and per-base evidence, the
simplest documented approach is Biopython alone, without tracy:

1. Read each `.ab1` with Biopython; trim each read with the modified Mott algorithm (section 1).
2. Reverse-complement the reverse read (calls, qualities and trace positions reversed).
3. Align with `Bio.Align.PairwiseAligner` in global mode with free end gaps (`end_gap_score = 0`; scores shown in the
   report).
4. For every alignment column record the evidence: each read's base, Phred quality and the four channel heights at
   its peak (`DATA9..12` at `PLOC2`), with the trace position so the viewer can show it.
5. Where both reads agree the base is kept; where they disagree, or one has a gap inside the overlap, the position is
   a conflict, resolved by the higher quality only when the rule's margins are met (the rule and its thresholds are
   parameters shown in the report; otherwise IUPAC code or N), and always listed for review. Outside the overlap the
   single read's base is used and marked "single read".

Reasons: one PyPI dependency instead of a 339 MB Bioconda environment; the instrument's own qualities are kept and
used; every step and parameter is visible; the per-position evidence is ARVA's own data rather than a text alignment
to parse. tracy remains an option for a later cross-check (multi-trace assembly, heterozygous peaks).

Measured on the user's pair (scores match 2, mismatch -3, gap open -5, extend -2): overlap of 534 columns, 534
identical (100 %), no gap and no conflict; consensus of 599 bases (alignment score 1068).

## 3. NCBI 16S database (type strains)

**Files** (NCBI BLAST database FTP, `https://ftp.ncbi.nlm.nih.gov/blast/db/`, listing of 2026-11-03):

- `16S_ribosomal_RNA.tar.gz`, 72,729,050 bytes, dated 2026-10-29 (SHA-256 measured
  `306e385825e7e81bf4a276a3aae7a92cd6df4c5e5dc55d70c16cea4c7bfa3415`);
- `16S_ribosomal_RNA.tar.gz.md5` (`050f4b623a7e1d745143084095dd96b9`, checked OK);
- `16S_ribosomal_RNA-nucl-metadata.json`: `"description": "16S ribosomal RNA (Bacteria and Archaea type strains)"`,
  `"number-of-sequences": 27646`, `"number-of-letters": 40048476`, `"last-updated": "2026-10-29T00:00:00"`,
  `"bytes-total": 18413401`, `"bytes-total-compressed": 72729050`, `"version": "1.1"` (the metadata format).

**Version and date.** NCBI keeps only the current build on the FTP site (one file per database; the BLAST database
README: "The BLAST databases are updated regularly. There is no established incremental update scheme"). The
version of a copy is its date: `last-updated` of the metadata JSON, which `blastdbcmd -db 16S_ribosomal_RNA -info`
also prints ("Date: Oct 29, 2026 5:36 AM", "BLASTDB Version: 5", 27,646 sequences, 40,048,476 bases), plus the
archive's MD5. ARVA can download only the current build; an older build is available only if the user kept it
(register an existing folder). ARVA's BLAST+ 2.12.0 (Ubuntu) reads this version 5 database (`blastdbcmd -info` and
`blastn` run on it).

**Contents of the archive** (unpacked 368 MB): the database itself, `16S_ribosomal_RNA.{ndb,nhr,nin,nnd,nni,nog,nos,
not,nsq,ntf,nto}` (about 18 MB), and NCBI's taxonomy files `taxdb.btd` (177 MB), `taxdb.bti` (18.5 MB) and
`taxonomy4blast.sqlite3` (99 MB). Without the taxonomy files `blastn` still reports `staxid` and the title (`stitle`,
for example "Staphylococcus taiwanensis strain NTUH-S172 16S ribosomal RNA, complete sequence") but `sscinames` is
`N/A`, with a warning. ARVA can therefore extract only the database files (18 MB) and take the organism from the
title, or keep the taxonomy files when the user wants NCBI's scientific names (choice shown with the sizes).

**Source of the records.** The RefSeq Targeted Loci project (`https://www.ncbi.nlm.nih.gov/refseq/targetedloci/`):
curated RefSeq records of ribosomal RNA loci; the bacterial 16S FASTA and GenBank files are also published under
`https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Bacteria/` (`bacteria.16SrRNA.fna.gz`, 7.7 MB, 2026-11-03), without
a checksum file, so the BLAST archive (with its MD5) is the better download.

**Terms.** NCBI's policy page (`https://www.ncbi.nlm.nih.gov/home/about/policies/`): "NCBI itself places no
restrictions on the use or distribution of the data contained therein ... However, some submitters of the original
data (or the country of origin of such data) may claim patent, copyright, or other intellectual property rights in
all or a portion of the data". ARVA does not redistribute the database: the user downloads it.

**As a Database Manager kind** (new kind in `database_kinds.py`, detector in `database_detect.py`):

- recognise: a folder with `16S_ribosomal_RNA.nsq/.nin/.nhr` (and the other v5 files above); optionally
  `16S_ribosomal_RNA-nucl-metadata.json`; read `blastdbcmd -info` for title, date, sequence count and BLASTDB version;
- version: `last-updated` of the metadata JSON (or the `-info` date), plus the archive's MD5 and SHA-256 when ARVA
  downloaded it;
- download: the current build only, to the folder the user chooses, after confirmation showing size and date; check
  the MD5 against the `.md5` file; never run `update_blastdb.pl` unattended;
- register: an existing folder anywhere ARVA may read;
- tools: BLAST+ (`blastn`), integrated; each search records the database with `record_use`.

## 4. Interpretation thresholds

**CLSI MM18.** The guideline (Clinical and Laboratory Standards Institute, *Interpretive Criteria for Identification
of Bacteria and Fungi by Targeted DNA Sequencing*, MM18, 2nd ed., 2018; 1st ed. MM18-A, 2008) is sold by CLSI and its
text could not be read. Its 16S criteria are quoted here from peer-reviewed open-access papers that cite it:

- Frickmann H. et al. (2015) 16S rRNA gene sequence-based identification of bacteria in automatically incubated
  blood culture materials from tropical sub-Saharan Africa. PLoS One 10:e0135923, doi:10.1371/journal.pone.0135923
  (citing MM18-A): "≥99% identity was demanded for identifications at species level, ≥97% identity for
  identifications at genus level ... Also, 0.8% separation between different species was demanded."
- Locher K. et al. (2022) Automated 16S sequencing using an R-based analysis module for bacterial identification.
  Microbiol Spectr 10:e0040822, doi:10.1128/spectrum.00408-22, Table 5 (following MM18 1st and 2nd eds): species
  when identity ≥ 99 % and distance to the next species ≥ 0.8 %; genus when identity ≥ 99 % with distance < 0.8 %, or
  identity 97–99 %; inconclusive below 97 % or with query cover < 98 %; aligned query length > 440 bp.
- Campodónico V.L. et al. (2025) Evaluation of long-read 16S rRNA next-generation sequencing for identification of
  bacterial isolates in a clinical diagnostic laboratory. J Clin Microbiol 63:e0167024, doi:10.1128/jcm.01670-24:
  "the CLSI MM18 2A interpretation guidelines are limited to Sanger-based sequencing of the first 500 bp of the 16S
  rRNA gene"; for aerobic actinomycetes species-level needs ≥ 99.6 % identity with ≥ 0.4 % separation, and for
  *Mycobacterium* 100 % identity (their family-level rule, ≥ 95 %, is the authors' own).

ARVA will show these values as "CLSI MM18 as quoted by [paper]", not as read from the guideline, and will warn that
they were established for the 5' part of the gene: the 784F–1401R fragment (V5–V8) is a different region.

**16S and *Staphylococcus*.**

- Kosecka-Strojek M. et al. (2019) Development and validation of a reference data set for assigning *Staphylococcus*
  species based on next-generation sequencing of the 16S-23S rRNA region. Front Cell Infect Microbiol 9:278,
  doi:10.3389/fcimb.2019.00278: Sanger 16S identified 27 species (54 %) unambiguously; species with identical or
  nearly identical 16S (1–2 nucleotides) include *S. aureus*–*S. argenteus*–*S. schweitzeri*, *S. epidermidis*–*S.
  haemolyticus*, *S. pasteuri*–*S. warneri*, *S. saprophyticus*–*S. xylosus*, *S. cohnii*–*S. kloosii* and others;
  sodA and rpoB were the most discriminative targets.
- Ghebremedhin B. et al. (2008) Genetic classification and distinguishing of *Staphylococcus* species based on
  different partial gap, 16S rRNA, hsp60, rpoB, sodA, and tuf gene sequences. J Clin Microbiol 46:1019–1025,
  doi:10.1128/JCM.02058-07 (abstract, PubMed 18174295): related species "cannot always be distinguished" by 16S;
  the partial gap sequences' similarities "were found to be lower than those of 16S rRNA (approximately 97%), rpoB
  (approximately 86%), hsp60 (approximately 82%), and sodA (approximately 78%)".

ARVA's text for a 16S result in *Staphylococcus* will name these limits and suggest rpoB, sodA, tuf or gap, citing
these papers.

## 5. Finding and naming any gene

The consensus (or a single trimmed read) is searched with `blastn` (ARVA's adapter `arva_tools/blast.py`,
BLAST+ 2.12.0) against every local source; nothing is sent outside.

**(a) Assemblies in ARVA with a Bakta or Prokka annotation.** `blastn` against the contigs, then the hit is named by
the annotated features it overlaps (gene, product, locus tag from the GFF3), with the fraction of the feature covered.
Checked on MW2 (GCF_000011265.1, Bakta 1.12.2 light): VFDB's *icaA*, *hla* (VFDB "hly/hla") and *sea* hit Bakta
CDSs named icaA, hly "Alpha-Hemolysin precursor" and sea at 100 % identity covering 100 % of the feature. VFDB's *hlb*
hit two pieces about 43 kb apart (83.0 % and 18.4 % of the query, 99.6 % and 100 % identity; *sea* lies between
them), on two CDSs that Bakta names "Phospholipase C", not hlb. So ARVA must chain split hits
(`arva_core.region.chain_matches`), report the gene as interrupted, and show each source's name side by side. The
Bakta runs in the test cache were CDS-only (no rRNA features), so a 16S hit is named by rRNA features only when the
annotation includes them; the NCBI annotation of MW2 and MSSA476 does ("16S ribosomal RNA", RFAM RF00177).

**(b) Reference collection genomes.** An NCBI Datasets genome package contains GFF3 or GenBank files only when they
were requested: the Datasets v2 OpenAPI lists `include_annotation_type` values `GENOME_FASTA`, `GENOME_GFF`,
`GENOME_GBFF`, `RNA_FASTA`, `PROT_FASTA`, `GENOME_GTF`, `CDS_FASTA`, `SEQUENCE_REPORT`
(`https://www.ncbi.nlm.nih.gov/datasets/docs/v2/openapi3/openapi3.docs.yaml`, `v2AnnotationForAssemblyType`; the
catalog's `fileType` values include `GFF3` and `GENBANK_FLAT_FILE`). ARVA's builder (`ncbi_datasets.py`) and the
user's type-strain package request `GENOME_FASTA` only, so their genomes give homologous regions (genome, contig,
coordinates, identity, coverage) without a name; names come from (a), (c) and (d). Asking also for `GENOME_GFF` when
a collection is built would let ARVA name these hits too (to be decided in the build part).

**(c) Specialised databases.**

- VFDB core set A, bundled with ABRicate 1.4.0 (`db/vfdb/sequences`, 4,592 sequences, index date 2026-Apr-3 by
  `abricate --list`; headers `vfdb~~~<gene>~~~<accession>~~~ (<gene>) <product> [<VF> - <category>] [<organism>]`).
  It holds *hla* (as "hly/hla"), *hlb*, *icaA–D*, *icaR*, *clfA/B*, *fnbA/B*, *cna*, *sdrC* and *bap*, but of the
  enterotoxins only *sea*, *seb*, *sec*, *seh*, *selk*, *sell*, *selq* and *tsst-1*: genes such as *sed*, *see*,
  *seg*, *sei* or *sej* are absent, so a result from VFDB alone is not complete for enterotoxins and (a) matters.
- AMRFinderPlus 4.2.7 nucleotide mode (`amrfinder --nucleotide <fasta> --database <dir>`, translated search;
  `--ident_min`, `--coverage_min`, `--organism Staphylococcus_aureus` for point mutations), already integrated
  (`arva_tools/amrfinderplus.py`).
- mlst's PubMLST allele files, e.g. `db/pubmlst/saureus/arcC.tfa` (headers `>arcC_1`, 1,065 alleles for arcC):
  `blastn` gives the exact allele or the closest one with its differences.
- spaTyper 0.3.3 scans any FASTA for exact matches to the Ridom repeats (`arva_tools/spatyper.py`; always with
  `-r`/`-o` files the user registered, never its download). Running it on a Sanger spa amplicon is not yet tested:
  the real Ridom files are not in the test cache.
- NCBI 16S (section 3).

**(d) Ranked output.** One row per source and subject, HSPs of the same subject chained:

| Field | Definition |
| --- | --- |
| identity | BLAST `nident` / alignment length over the chained HSPs, % |
| query coverage | union of the HSPs' query intervals / query length, % |
| subject coverage | union of subject intervals / subject length, %; for a genome hit, the covered part of the overlapped feature / feature length |
| e-value, bit score | BLAST's, for the best HSP; bit score summed over chained HSPs |
| name | feature gene/product (a), database gene/allele/type/species (c), or "unnamed region" (b) |
| source | database kind, name, version (with `record_use`), or the assembly and its annotation run |

Rows are sorted by bit score, then identity, then query coverage; rows whose identity and coverage equal the best are
shown as tied, never hidden. Subject coverage is shown but not used for ranking: a 600-base 16S amplicon covers only
about 38 % of a 1,552-base gene (measured below), which is expected. A suspected gene or species is compared with
the tied best set: "matches" when it is in it and the thresholds are met, "does not match" when a better hit has
another name, "ambiguous" when several names tie.

## 6. Manual end-to-end check on the user's strain 27 (local only)

Reads `1-27_784-F` and `1-27_1401-R`, 16S rRNA, primers 784F/1401R, ABI 3730xl at Macrogen.

1. Trimmed with the modified Mott algorithm, limit 0.05: 784F bases 23–582 (560), 1401R bases 15–587 (573).
2. Consensus (section 2): 599 bases; overlap 534 columns, 100 % identical, no conflicts.
3. `blastn -task megablast -evalue 1e-10` against the six local RefSeq genomes (*S. aureus* N315, Mu50, MW2,
   MSSA476, USA300_FPR3757; *S. epidermidis* ATCC 12228) and the three type-strain genomes of the reference package
   (*S. aureus* ATCC 12600, *S. argenteus* MSHR1132, *S. epidermidis* ATCC 14990): 49 hits, all 598 bases aligned
   (99.8 % query coverage), 5 or 6 hits per chromosome, none on plasmids. All 12 hits in MW2 and MSSA476 (the two
   genomes with an NCBI annotation in the cache) fall on features named "16S ribosomal RNA" (1,552 bases; subject
   coverage 38.5 %):
   - 100 % (0 mismatches): two 16S copies of MSSA476 and one of MW2;
   - 99.83 % (1 mismatch): the other hits in MW2 and MSSA476 (one MSSA476 hit at 99.67 %), all hits in N315, USA300
     and *S. aureus* ATCC 12600, four of five in Mu50 (the fifth 99.67 %) and four of five in *S. argenteus*
     MSHR1132 (the fifth 99.00 %);
   - 99.00–98.83 % (6–7 mismatches): *S. epidermidis* ATCC 12228 and ATCC 14990.
4. The same consensus against NCBI's 16S database (2026-10-29 build, local copy, 500 best hits): 100 % to
   *S. taiwanensis* NR_181843 and *S. borealis* NR_181247; 99.83 % to *S. aureus* (NR_118997, NR_113956, NR_115606),
   *S. argenteus* NR_181984, *S. roterodami*, *S. simiae* and *S. haemolyticus*; 25 species of *Staphylococcus* at
   ≥ 99.0 %, and 7 hits of *Mammaliicoccus* at 97–98.7 %.

Reading of these numbers with the criteria of section 4: genus *Staphylococcus* (well above 97 % with full query
coverage); not resolvable to species with this fragment, because several species are at or above 99 % with no 0.8 %
separation, and *S. aureus* and *S. argenteus* are equally close even among whole genomes. The local genomes place the
strain closest to *S. aureus* (MW2 and MSSA476 copies identical), which is consistent with, but does not prove,
*S. aureus*: a higher-resolution gene (rpoB, sodA, tuf or gap) or the genome is needed. This is the result the
module must be able to state, with these numbers.

## Not confirmed

- The CLSI MM18 text itself (quoted from three papers).
- spaTyper on a real Sanger spa amplicon with Ridom's files.
- Biopython on `.ab1` files from instruments other than ABI 310, 3100, 3730 and 3730xl (SeqStudio, 3500).
- Whether NCBI keeps any older 16S builds elsewhere (none on the FTP listing).
