---
title: 'ARVA: a local graphical platform for bacterial genome analysis with recorded provenance'
tags:
  - bacterial genomics
  - Oxford Nanopore
  - Staphylococcus aureus
  - antimicrobial resistance
  - provenance
  - reproducibility
authors:
  - name: Juan M. Moreno
    orcid: 0009-0002-8116-2871
    affiliation: 1
affiliations:
  - name: Conaprole, Uruguay
    index: 1
date: 12 November 2026
bibliography: paper.bib
---

# Summary

ARVA is an open-source application for analysing bacterial genomes on a laboratory's
own computer. Starting from the reads produced by a DNA sequencer (here, Oxford
Nanopore), it reconstructs the genome (assembly), locates and names its genes
(annotation), identifies the species and the strain type, and reports genes associated
with antimicrobial resistance, virulence and plasmids. The user works in a graphical
interface, in English or Spanish, instead of the command line. ARVA implements no new
algorithms: it runs established open-source tools, among them Flye [@kolmogorov2019],
Medaka [@medaka], Bakta [@schwengers2021], mlst [@mlst; @jolley2018] and AMRFinderPlus
[@feldgarden2021], and adds typing steps for *Staphylococcus aureus*. With each result
ARVA stores the tool and its version, the exact command, checksums of the input files,
the database and its version, and the run time. Sequence data stay on the computer.
ARVA downloads a reference database only after the user has confirmed its source, size
and licence, and no analysis installs or updates software.

# Statement of need

Oxford Nanopore sequencers have brought whole-genome sequencing within reach of small
clinical, veterinary and dairy laboratories. Analysing the reads, however, still
requires bioinformatics skills that many such laboratories lack [@lacyroberts2026]:
pipelines run from the command line, each tool has its own database, and choices such
as the Medaka model or the VFDB set change the biological result. Web platforms remove
the command line but require uploading genomes that may be confidential, and none of
the local graphical tools we found combines the assembly of Nanopore reads with
*S. aureus* typing.

ARVA is written for laboratories that have the isolates and the sequencer but no
bioinformatics support, need typing and resistance results they can defend, and must
keep their data local. It runs on a Linux server or on a laptop. In our benchmark,
assembly with Flye and polishing with Medaka needed about 10 GB of memory; typing and
gene detection of assembled genomes ran on an 8 GB MacBook Air.

# State of the field

Command-line pipelines such as Bactopia [@petit2020], nf-core/bacass [@ewels2020] and
ASA^3^P [@schwengers2020] assemble and characterise bacterial genomes reproducibly
(Bactopia types *S. aureus* with the same three tools that ARVA wraps) but assume a
terminal. Web platforms such as Galaxy [@galaxy2026], BV-BRC [@olson2023] and
Pathogenwatch [@argimon2021] offer graphical access on public servers (Galaxy can also
be installed locally, by an administrator). Three graphical tools run on the user's own
computer. EPI2ME Desktop with Oxford Nanopore's wf-bacterial-genomes workflow
[@epi2me] assembles Nanopore reads and reports MLST and resistance genes,
but its documentation asks for at least 32 GB of memory, lists no ARM support and
includes no *S. aureus* typing. BacExplorer [@privitera2025] types *S. aureus* but
assembles short reads only. BactFlow [@li2026] assembles Nanopore reads, but its
documentation lists no resistance or species-specific typing.

ARVA was built rather than contributed to one of these projects because none of the local graphical tools combines Nanopore assembly
with *S. aureus* typing, and because its core is a persistent record, not a workflow
run: samples, files, databases and results are kept in a database with their lineage.
Workflow managers and Galaxy already record tool versions and parameters; ARVA adds,
visible in the interface, the exact command and the checksums of each result's inputs,
and it warns when tools disagree: a VFDB hit labelled *lukF-PV*, a Panton–Valentine
leukocidin gene, on the locus that AMRFinderPlus identifies as *lukD* is listed as a
cross-hit, not as PVL.

# Software design

ARVA is a FastAPI service with a PostgreSQL database, a Redis/RQ worker that runs the
tools, and a React interface. The analysis logic lives in two Python packages that
work without the web application: `arva_core` (validation, statistics and workflow
logic) and `arva_tools` (one adapter per external tool). ARVA is distributed as
container images (linux/amd64 with every tool; linux/arm64 without those that have no
arm64 build, among them MOB-suite and AgrVATE). It also runs Filtlong
[@filtlong], QUAST [@gurevich2013], skani [@shaw2023], ABRicate [@abricate] with VFDB
[@zhou2025] and PlasmidFinder [@carattoli2014], MOB-suite [@robertson2018;
@robertson2020] and, for *S. aureus*, spaTyper [@spatyper; @harmsen2003], sccmec
[@sccmec] and AgrVATE [@raghuram2022]. Three design decisions follow from one goal:
results that a laboratory can defend.

- **Pinned tools.** Tools are fixed when the container image is built. The assembly,
  polishing, typing and gene-detection tools come from Bioconda [@gruning2018]
  environments, each with a lock file that carries a checksum per package; QUAST is a
  pinned PyPI release, and utilities such as Racon [@vaser2017] and minimap2 are
  Debian packages. Adapters pass arguments as lists, never as shell strings, and most
  check each option against the installed tool's own help text.
- **Databases as records.** A database manager recognises each database from its
  official layout, reads its version from its own files (or records that the user
  declared it) and stores checksums when a database is downloaded or fully verified.
  A user registers databases already on disk, or downloads a chosen version after
  confirming its size and licence, and chooses per analysis which one to use. Derived
  files are linked to their parents; originals are never modified.
- **Species-aware typing.** A species-specific step runs when the available evidence
  (the species identification, the MLST scheme, or both) points to one of its taxa and
  none of it contradicts; otherwise it needs an explicit override, and a batch skips
  the step and reports the reason.

These choices have costs. Containers make installation uniform but cap memory: Flye
allocates a fixed 8 GiB table when counting k-mers, which does not fit in Docker on an
8 GB computer, so ARVA estimates memory before such steps and says when they will not
fit. Refusing the tools' own updaters costs convenience, but every
database then has a version that the user confirmed. ARVA runs batches with its own
job queue, not a workflow engine such as Nextflow: a step is also ARVA's checks and
provenance records, at the price of those engines' scheduling and portability.

ARVA's own code is MIT-licensed; some tools and databases restrict use (Medaka has
Oxford Nanopore's research-only licence; VFDB and the Ridom SpaServer data are for
non-commercial use). The test suite has about 2,700 cases; part of it runs the real
tools on synthetic reads or public reference genomes.

# Research impact statement

ARVA has not yet been used in a published study. The evidence today is a benchmark on
public data and first use in the author's laboratory.

**Benchmark on public data.** From the dairy *S. aureus* study of @chakrawarti2024,
deposited as BioProject PRJNA983748 (GridION, R9.4.1 flow cells), one isolate was taken
for each of the 15 sequence types (STs) found by Sanger sequencing. The set
deliberately includes six isolates for which the study's own nanopore-only assembly
gave no ST (five) or a wrong ST (one). Each isolate was processed from the public
reads through ARVA's HTTP API, the one its interface uses, in a fresh installation of
the published container images (`0.2.0-d78bb98`): Filtlong, Flye 2.9.6, Medaka 2.1.1
(model `r941_min_hac_g507`), mlst 2.35.0, spaTyper, sccmec, AgrVATE and AMRFinderPlus
(\autoref{tab:validation}). The runner, expected values, per-isolate results with
provenance and a GitHub Actions workflow are in `validation/chakrawarti2024`.

| Result | Reference in the study | Agreement |
|:--|:--|:-:|
| MLST sequence type | Sanger sequencing of the seven loci | 12/15 |
| MLST, the six isolates the study's nanopore-only assembly missed | Sanger sequencing | 4/6 |
| *spa* type | hybrid Illumina–nanopore assembly | 15/15 |
| Penicillinase gene (*blaZ*, also reported as *blaPC1*) | penicillin phenotype | 15/15 |
| *mecA* | oxacillin and cefoxitin phenotype (all susceptible) | absent in 15/15 |

: ARVA, from nanopore reads only, against the reference results of @chakrawarti2024. \label{tab:validation}

None of the three discordant isolates received a wrong ST number: mlst assigned no ST.
Two belong to one lineage (ST151 and the novel ST7083) and share partial matches at
*pta* and *yqiL*; the study's nanopore-only assembly typed one of them correctly. In
the third (ST398) the assembly matched other existing alleles exactly (*arcC* 90
instead of 3, *aroE* 1216 instead of 35), each one base different from the Sanger
allele in a run of seven adenines. In a two-isolate pilot, Racon alone left one
with the same *arcC* deletion, which Medaka corrected: Medaka reduced, but did not
remove, homopolymer errors in these assemblies.

The benchmark has clear limits: 15 isolates of one species from one study, the
superseded R9.4.1 chemistry, and a Medaka model trained for a later basecaller. All
isolates are methicillin-susceptible, so *mecA* detection and SCCmec typing are
covered only by tests on the reference genomes N315 and USA300_FPR3757. Species
identification, annotation, virulence, plasmid and agr results were not compared.

**Use in the author's laboratory.** ARVA was run on 23 staphylococcal isolates from
bovine mastitis (17 *S. aureus* and six of other species), sequenced on a GridION.
Their genomes had been assembled beforehand with the author's command-line workflow,
so the comparison with that workflow covers identification, typing and gene
detection, not assembly. The two agreed on species (23/23), MLST (23/23), spa type
(17/17), agr group (16/17) and resistance genes (22/23). The agr difference is
unresolved; the resistance-gene difference (*blaR1* in one *S. chromogenes*) is
probably explained by ARVA searching nucleotide sequence only. These data are not yet
public.

# AI usage disclosure

ARVA was built with a generative AI coding agent, Claude Code (Anthropic). The agent
made 161 of the repository's first 162 commits under its own Git identity, and the
trailer of each commit names the model and version that produced it. The agent wrote
nearly all of the code, tests, documentation and validation scripts, selected the
benchmark isolates, ran the benchmark, and drafted and revised this paper. The author
framed the problem, wrote the specification, chose the analyses, tools, databases and
safeguards, made the design decisions described above and chose the benchmark study.
The author validated the AI-generated work by running each build on the laboratory's
computer and sequencing data, recording every defect and its correction in
`docs/registro-prueba-mac.md`, comparing ARVA's results with the author's own
command-line analysis, and reviewing this paper. Every reference with a DOI was
checked against its Crossref record. The author takes responsibility for the software
and this paper.

# Acknowledgements

The author thanks the developers and maintainers of the open-source tools and
databases that ARVA integrates, and Chakrawarti and colleagues [-@chakrawarti2024] for
making their reads and supplementary results public. This publication made use of
the spa typing website (https://spaserver.ridom.de/) that is developed by Ridom GmbH
and curated by SeqNet.org, and of the PubMLST website (https://pubmlst.org/) developed
by Keith Jolley [@jolley2018] and sited at the University of Oxford; the development
of that website was funded by the Wellcome Trust.

<!-- AUTHOR, before submitting: add here the funding statement that JOSS requires, for
example "This work received no specific funding." or the funder and its role. -->

# References
