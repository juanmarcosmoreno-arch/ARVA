---
title: 'ARVA: a local, graphical platform for bacterial genome analysis with full provenance'
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
date: 8 November 2026
bibliography: paper.bib
---

# Summary

ARVA is an open-source platform that takes a microbiology laboratory from raw
sequencing reads to an assembled, annotated and typed bacterial genome on its own
computer, through a graphical interface in English or Spanish. It runs established
tools (Filtlong [@filtlong], Flye [@kolmogorov2019], Medaka [@medaka], QUAST
[@gurevich2013], Bakta [@schwengers2021], mlst [@mlst] with PubMLST schemes
[@jolley2018], skani [@shaw2023], AMRFinderPlus [@feldgarden2021], ABRicate
[@abricate] with VFDB [@zhou2025] and PlasmidFinder [@carattoli2014], MOB-suite
[@robertson2018], and, for *Staphylococcus aureus*, spaTyper [@spatyper], sccmec
[@sccmec] and AgrVATE [@raghuram2022]) behind one interface. Every result records
which tool and version produced it, the exact command, the checksums of its inputs
and of the database it used, and how long it took. Reads and genomes never leave the
computer: ARVA downloads reference databases only after the user confirms the source,
size and licence, and it never installs software at run time.

# Statement of need

Whole-genome sequencing with portable Oxford Nanopore devices is now within reach of
small clinical, veterinary and dairy laboratories, but analysing the reads still
assumes a bioinformatician: command-line pipelines, dozens of tools with their own
databases, and decisions (which Medaka model, which VFDB set, whether a hit is the
gene it is named after) that change the biological answer. The alternatives are web
services, which require uploading genomes that may be confidential or subject to
data-sharing agreements.

ARVA is written for the microbiologist who has the isolates and the sequencer but not
the bioinformatics support. Its target users are laboratories that sequence a few to a
few hundred isolates, need typing and resistance results they can defend, and must
keep their data local. It runs on a laptop (it is tested on an 8 GB MacBook Air) as
well as on a Linux server.

# State of the field

Command-line pipelines such as Bactopia [@petit2020], nf-core workflows [@ewels2020]
and TORMES [@quijada2019] provide comprehensive, reproducible bacterial analyses, and
web platforms such as Galaxy [@galaxy2024], BV-BRC [@olson2023] and Pathogenwatch
[@argimon2021] offer graphical access. ARVA does not replace the analytical tools;
it wraps the same community tools. It differs in three respects that motivated
building rather than contributing: (i) a local graphical application that a laboratory
installs and uses without the command line or a server administrator, and without
sending data anywhere; (ii) provenance and safeguards built into every result rather
than left to the user, including interpretation warnings when tools disagree (for
example a VFDB hit labelled *lukF-PV*, the Panton–Valentine leukocidin, that lies on
the region where AMRFinderPlus finds *lukD* with higher identity, which ARVA reports
as a cross-hit instead of as PVL); and (iii) the assumption of modest hardware, with
memory estimates before memory-bound steps and the option to run Flye and Bakta
natively on macOS when they do not fit in Docker's memory.

# Software design

ARVA is a FastAPI service with a PostgreSQL database and a Redis/RQ worker that runs
the tools, and a React interface. It is distributed as container images for
linux/amd64 and linux/arm64 and as a small macOS application that starts the
containers and can run memory-bound tools natively. Several design decisions follow
from the goal of results a laboratory can defend:

- **Pinned, checked tools.** Each tool comes from a Bioconda environment fixed by a
  lock file with a checksum per package. Adapters build argument lists (never shell
  strings) and their options are checked against each tool's own help text, so an
  option the installed version does not offer is refused rather than guessed.
- **Databases as first-class records.** A database manager recognises each database
  from its official layout, reads its version from its own files, and records
  checksums. A user can register databases already on an external disk, download
  versions after confirming size and licence (for example the full VFDB set or a
  Medaka model for older R9.4.1 flow cells, verified against the published SHA-256),
  and choose per analysis which one to use. The choice is stored with the result.
- **Provenance and lineage.** Filtered reads, assemblies and polished assemblies are
  new files linked to their parents; originals never change. Reports (HTML, CSV,
  JSON) include methods text built from what actually ran.
- **Species-aware typing.** Species-specific steps declare the taxa they apply to and
  run only when the species identification and MLST scheme agree; a batch skips them
  for other species and says why (in the author's data, six non-*aureus*
  staphylococci were skipped for spa, SCCmec and agr typing).
- **Batch workflows.** A node editor with typed ports composes ARVA's own analyses
  into versioned workflows, run over a project with progress per sample and a
  consolidated results table.

The code base has more than 2,700 automated tests (API, tool adapters, scientific
core and interface), many of which run the real tools on public genomes.

# Research impact statement

ARVA was validated against a published study with public data, as a reproducible
GitHub Actions workflow that anyone can rerun (`validation/chakrawarti2024`).
From the dairy *S. aureus* dataset of @chakrawarti2024 (BioProject PRJNA983748;
GridION, R9.4.1), one isolate per Sanger sequence type (15 isolates, including six
the paper's own nanopore-only assembly could not type) was analysed from raw reads
through ARVA's interface API, starting from an empty installation of the published
images. Compared with the paper's Sanger MLST, hybrid-assembly spa types and
antimicrobial susceptibility: MLST matched Sanger for 12/15 isolates (two of the other
three received no ST rather than a wrong one; the paper's nanopore-only calls matched
9/15), spa types 15/15, the penicillinase gene matched the penicillin phenotype 15/15,
and *mecA* was absent in all 15 oxacillin-susceptible isolates. The validation also
showed why polishing matters: with Racon only, one isolate acquired a homopolymer
error in *arcC* and a spurious novel ST, which Medaka with the R9.4.1 model removed.

In the author's laboratory, ARVA was used on 23 staphylococcal isolates from bovine
mastitis sequenced on a GridION and compared with an independent command-line analysis
of the same genomes: species 23/23, MLST 23/23, spa 17/17, agr 16/17 and resistance
genes 22/23 agreed, and the remaining differences were traced to database or search
mode choices that ARVA now reports explicitly.

# AI usage disclosure

Most of ARVA's source code, tests and documentation were written with the assistance
of a generative AI model (Claude, Anthropic), working from the author's specification
and under the author's direction. The author defined the scientific requirements, the
analyses, the tools and databases, and the safeguards; tested every release on real
laboratory data; designed the validation; and reviewed the results. Correctness was
checked through automated tests that run the real tools, through comparison with an
independent analysis of the author's own isolates, and through the published-data
validation described above, whose inputs, scripts and results are in the repository.
This paper was drafted with AI assistance and revised by the author; all references
were checked against their DOIs.

# Acknowledgements

ARVA relies on the authors and maintainers of the open-source tools and databases it
integrates, and on the authors of @chakrawarti2024 for making their reads and
supplementary results public.

# References
