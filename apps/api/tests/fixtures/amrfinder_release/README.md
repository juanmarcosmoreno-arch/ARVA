# A constructed AMRFinderPlus release (test data, not a usable database)

`2026-08-07.1/` holds small subsets of the files of NCBI's AMRFinderPlus database release 2026-08-07.1
(https://ftp.ncbi.nlm.nih.gov/pathogen/Antimicrobial_resistance/AMRFinderPlus/database/4.2/2026-08-07.1/, public
domain, downloaded 2026-10-29), laid out as NCBI publishes a release folder:

* `AMRProt.fa` and `AMR_CDS.fa`: the first protein and CDS of mecA, blaZ and tet(38);
* `AMR.LIB`: one HMM (NF033646.1, the smallest in the release);
* `fam.tsv`: the hierarchy rows of those genes and of that HMM's family, up to `ALL`;
* `taxgroup.tsv`: the Staphylococcus_aureus line only, with its `AMR_DNA-Staphylococcus_aureus.fa/.tsv` (whole);
* `AMRProt-mutation.tsv`, `AMRProt-susceptible.tsv/.fa`, `changes.txt`: their first lines; `AMRProt-suppress.tsv`,
  `version.txt` and `database_format_version.txt`: whole.

The API tests serve it from a local HTTP server as if it were NCBI's folder, let ARVA download and index it with
the real `amrfinder_index`, and search a test input made of the three CDS joined by N with the real `amrfinder`
(it finds mecA, blaZ and tet(38), EXACTX). A gene set this small says nothing about a genome.
