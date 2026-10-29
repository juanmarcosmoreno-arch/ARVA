"""The kinds of reference database ARVA recognises, with the facts checked against each tool's official documentation
or source code (checked 2026-10-29; each kind cites where its facts come from and lists what was not confirmed).

A kind says how to recognise a folder (or file) of that kind, how its version is read from its own files, which tools
read it, and whether ARVA can download it: only when the publisher offers a stable, versioned archive with a published
checksum (database_catalogue.py lists those versions); every kind can be registered where it already is. The
detectors that apply these rules are in database_detect.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolUse:
    tool: str
    versions: str
    # ARVA runs this tool now (its version decides compatibility); otherwise compatibility is shown as unknown.
    integrated: bool = False


@dataclass(frozen=True)
class DatabaseKind:
    key: str
    name: str
    description: str
    tools: tuple[ToolUse, ...]
    source_url: str
    licence: str
    citation: str
    recognise: str
    version_from: str
    typical_size: str
    # "catalogue": ARVA can download the versions database_catalogue.py lists; "register": register-only;
    # "bundled": shipped inside a tool's package, recorded by ARVA when the tool is found.
    download: str
    download_note: str
    sources: tuple[str, ...]
    unconfirmed: tuple[str, ...] = ()
    licence_url: str | None = None
    # What may be registered: a folder, a single file, or both.
    accepts: tuple[str, ...] = ("folder",)
    # ARVA never copies, redistributes or downloads it (user-provided only).
    user_provided_only: bool = False
    notes: tuple[str, ...] = field(default=())


_CC_BY = "https://creativecommons.org/licenses/by/4.0/"

KINDS: tuple[DatabaseKind, ...] = (
    DatabaseKind(
        key="bakta",
        name="Bakta database",
        description="The database Bakta annotates with, light or full. Bakta 1.12.2 (the version ARVA ships) needs "
                    "database schema 6.",
        tools=(ToolUse("Bakta", "Bakta 1.12.2 accepts schema 6 only (major 6, any minor); database 6.0 needs Bakta "
                                "1.11 or later", integrated=True),),
        source_url="https://doi.org/10.5281/zenodo.4247253",
        licence="CC BY 4.0 (Zenodo record of database 6.0)",
        licence_url=_CC_BY,
        citation="Schwengers O. et al. (2021) Bakta: rapid and standardized annotation of bacterial genomes via "
                 "alignment-free sequence identification. Microbial Genomics 7(11), doi:10.1099/mgen.0.000685.",
        recognise="version.json with date, major, minor and type, and the files Bakta 1.12.2 checks (bakta/db.py "
                  "FILE_NAMES) plus psc.dmnd (full) or pscc.dmnd (light).",
        version_from="version.json: major.minor; type gives light or full.",
        typical_size="light: 1.3 GB zipped, 3.9 GB unzipped; full: 30 GB zipped, 84 GB unzipped (Bakta README).",
        download="catalogue",
        download_note="Zenodo record 14916843 (database 6.0) with published MD5s.",
        sources=("Bakta 1.12.2 wheel: bakta/__init__.py (__db_schema_version__ = 6), bakta/db.py check()",
                 "Zenodo record 14916843 and its db-versions.json"),
    ),
    DatabaseKind(
        key="amrfinderplus",
        name="AMRFinderPlus database",
        description="NCBI's Reference Gene Catalog and HMMs for antimicrobial resistance, stress response and "
                    "virulence genes and point mutations, read by AMRFinderPlus (and by Bakta's AMR expert system "
                    "from amrfinderplus-db/latest inside a Bakta database).",
        tools=(ToolUse("AMRFinderPlus", "the software version must be at least database_format_version.txt; "
                                        "AMRFinderPlus 4.2.7 needs data 2025-09-22.2 or later", integrated=True),),
        source_url="https://ftp.ncbi.nlm.nih.gov/pathogen/Antimicrobial_resistance/AMRFinderPlus/database/",
        licence="Public domain (United States Government Work; NCBI notice in the AMRFinderPlus sources)",
        citation="Feldgarden M. et al. (2021) AMRFinderPlus and the Reference Gene Catalog facilitate examination of "
                 "the genomic links among antimicrobial resistance, stress response, and virulence. Scientific "
                 "Reports 11:12728, doi:10.1038/s41598-021-91456-0.",
        recognise="version.txt, database_format_version.txt and the data files amrfinder reads (AMRProt.fa, AMR.LIB, "
                  "AMR_CDS.fa, fam.tsv, taxgroup.tsv, AMRProt-mutation.tsv, AMRProt-susceptible.tsv, "
                  "AMRProt-suppress.tsv); AMRProt.fa.phr shows that the BLAST indexes were built. The copy inside a "
                  "Bakta database (amrfinderplus-db/<version>) keeps only the indexes and tables Bakta's protein "
                  "search reads (no AMRProt.fa, AMR_CDS.fa or AMR_DNA files).",
        version_from="version.txt (for example 2026-08-07.1); database_format_version.txt gives the minimum "
                     "AMRFinderPlus version.",
        typical_size="Release 2026-08-07.1: 128 MB of release files from NCBI's FTP, 241 MB once indexed "
                     "(measured by ARVA on 2026-10-29).",
        download="release",
        download_note="NCBI publishes each release as a folder of separate files, one folder per software minor "
                      "version (database/4.2/2026-08-07.1/), without checksums. ARVA lists the dated releases for "
                      "the installed AMRFinderPlus, downloads the files amrfinder_update would fetch over HTTPS from "
                      "NCBI after you confirm, records the size and SHA-256 of each one, and indexes them with "
                      "amrfinder_index. It never runs amrfinder -u or amrfinder_update (they fetch the latest "
                      "release, unpinned).",
        sources=("ncbi/amr amrfinder.cpp (4.2.7): database checks, dataVer_min 2025-09-22.2",
                 "ncbi/amr amrfinder_update.cpp and amrfinder_index.cpp (4.2.7): release folder layout, file list, "
                 "indexing commands",
                 "NCBI FTP .../AMRFinderPlus/database/4.2/ (listing of 2026-10-29: 2025-12-03.1 to 2026-08-07.1)"),
        unconfirmed=("NCBI publishes no checksums for the release files; ARVA can only record the SHA-256 of what it "
                     "downloaded and compare each file's size with the server's Content-Length.",),
    ),
    DatabaseKind(
        key="gtdbtk",
        name="GTDB-Tk reference data",
        description="The Genome Taxonomy Database release package GTDB-Tk classifies genomes against.",
        tools=(ToolUse("GTDB-Tk", "R232 needs GTDB-Tk 2.7.0 or later; R226 and R220: 2.4.x to 2.6.1; R214 and "
                                  "R207_v2: 2.1.0 to 2.3.2 (GTDB-Tk installation guide); GTDB-Tk 2.8.0 accepts R232 "
                                  "only", integrated=True),),
        source_url="https://data.gtdb.ecogenomic.org/releases/",
        licence="CC BY-SA 4.0 (GTDB downloads page)",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        citation="Chaumeil P.-A. et al. (2022) GTDB-Tk v2: memory friendly classification with the genome taxonomy "
                 "database. Bioinformatics 38(23), doi:10.1093/bioinformatics/btac672. Parks D.H. et al. (2025) GTDB "
                 "release 10. Nucleic Acids Research, doi:10.1093/nar/gkaf1040.",
        recognise="metadata/metadata.txt with a VERSION_DATA line and taxonomy/gtdb_taxonomy.tsv; GTDB-Tk 2.8.0 "
                  "also reads msa/, masks/, pplacer/, skani/, radii/, mrca_red/, markers/ and split/.",
        version_from="VERSION_DATA in metadata/metadata.txt (for example r232).",
        typical_size="About 100 GB unpacked for R232 (GTDB-Tk installation guide); the R232 archive is "
                     "60,806,405,195 bytes.",
        download="catalogue",
        download_note="Versioned release folders with an MD5SUM.txt (release 232.0).",
        sources=("GTDB-Tk 2.8.0 wheel: gtdbtk/config/common.py", "GTDB-Tk installation guide (compatibility table)",
                 "data.gtdb.ecogenomic.org release232/232.0 MD5SUM.txt and VERSION.txt"),
        unconfirmed=("The folder layout of releases before R232 was not checked; GTDB-Tk versions before 2.7 read "
                     "other folders.",),
    ),
    DatabaseKind(
        key="skani",
        name="skani sketch database",
        description="Genomes sketched by skani sketch (for example the pre-sketched GTDB species representatives), "
                    "searched with skani search for average nucleotide identity.",
        tools=(ToolUse("skani", "databases written by skani 0.4 (markers.bin2) need skani 0.4.0 or later; skani 0.4 "
                                "still reads older databases (markers.bin)"),),
        source_url="https://github.com/bluenote-1577/skani/wiki/Pre%E2%80%90sketched-databases",
        licence="skani: MIT or Apache-2.0; the pre-sketched GTDB databases state no licence of their own",
        citation="Shaw J., Yu Y.W. (2023) Fast and robust metagenomic sequence comparison through sparse chaining "
                 "with skani. Nature Methods, doi:10.1038/s41592-023-02018-3.",
        recognise="markers.bin2 (skani 0.4) or markers.bin (older), with sketches.db2 and index.db2 (or sketches.db "
                  "and index.db), or one .sketch file per genome.",
        version_from="Not stated in the files: the GTDB release is declared by you (ARVA suggests one from the folder "
                     "name). README.txt, written by skani 0.4, names the skani version that built it.",
        typical_size="GTDB R232 and R226: about 30 GB compressed, 50 GB uncompressed (skani wiki).",
        download="register",
        download_note="The pre-sketched databases are offered over plain HTTP without published checksums.",
        sources=("skani 0.4.0 source: src/sketch_db.rs (file names), src/sketch.rs (README.txt)",
                 "skani wiki: Pre-sketched databases"),
    ),
    DatabaseKind(
        key="sylph",
        name="sylph database",
        description="A sylph database file (.syldb, or .syl2db for two-stage databases) of sketched genomes, for "
                    "profiling reads with sylph profile.",
        tools=(ToolUse("sylph", ".syl2db databases need sylph 1.0.0 or later; the sylph documentation states no "
                                "requirement for .syldb databases", integrated=True),),
        source_url="https://sylph-docs.github.io/pre%E2%80%90built-databases/",
        licence="sylph: MIT or Apache-2.0; the pre-built databases state no licence of their own",
        citation="Shaw J., Yu Y.W. (2024) Rapid species-level metagenome profiling and containment estimation with "
                 "sylph. Nature Biotechnology, doi:10.1038/s41587-024-02412-y.",
        recognise="One file ending in .syldb or .syl2db (the suffixes sylph 1.0.0 reads, src/constants.rs).",
        version_from="Not stated in a way ARVA reads: declared by you (ARVA suggests the release and -c value from the "
                     "file name, e.g. gtdb-r232-c200-dbv1.syldb).",
        typical_size="GTDB R232: 24 GB (-c 200), 4.9 GB (-c 1000) or 19 GB (two-stage) (sylph documentation).",
        download="register",
        download_note="Offered over plain HTTP (and a Google Cloud mirror) without published checksums.",
        accepts=("file",),
        sources=("sylph 1.0.0 source: src/constants.rs", "sylph documentation: Pre-built databases"),
        unconfirmed=("ARVA checks the suffix only, not the file's internal format.",),
    ),
    DatabaseKind(
        key="mash",
        name="Mash sketches",
        description="A Mash sketch file (.msh), such as the RefSeq sketches on the Mash data page, for fast "
                    "distance estimates with mash dist.",
        tools=(ToolUse("Mash", "the Mash data page states no version requirement", integrated=True),),
        source_url="https://mash.readthedocs.io/en/latest/data.html",
        licence="Not stated on the Mash data page (RefSeq is NCBI data)",
        citation="Ondov B.D. et al. (2016) Mash: fast genome and metagenome distance estimation using MinHash. "
                 "Genome Biology 17:132, doi:10.1186/s13059-016-0997-x.",
        recognise="One file ending in .msh.",
        version_from="Not stated in a way ARVA reads: declared by you. For RefSeqSketches.msh (k=16, s=400) and "
                     "RefSeqSketchesDefaults.msh (k=21, s=1000) the Mash data page says RefSeq release 70.",
        typical_size="RefSeq release 70: 48 MB (k=16, s=400) or 255 MB (k=21, s=1000), compressed (Mash data page).",
        download="register",
        download_note="The sketches are offered gzip-compressed without checksums.",
        accepts=("file",),
        sources=("Mash documentation: Data (precomputed sketches)",),
        unconfirmed=("ARVA does not read the sketch's k-mer size or sketch size from the file (mash info does).",
                     "Whether Mash reads a gzip-compressed .msh.gz directly was not checked: register the "
                     "decompressed .msh."),
    ),
    DatabaseKind(
        key="kraken2",
        name="Kraken 2 index",
        description="A Kraken 2 database (index) for taxonomic classification of reads, such as the Standard "
                    "collection built by the Kraken 2 maintainers.",
        tools=(ToolUse("Kraken 2", "the index page states no version requirement"),),
        source_url="https://benlangmead.github.io/aws-indexes/k2",
        licence="Not stated on the index page (\"open access thanks to the AWS Open Data Sponsorship Program\")",
        citation="Wood D.E., Lu J., Langmead B. (2019) Improved metagenomic analysis with Kraken 2. Genome Biology "
                 "20:257, doi:10.1186/s13059-019-1891-0.",
        recognise="hash.k2d, opts.k2d and taxo.k2d (the files the kraken2 script opens); the maintainers' indexes "
                  "also hold inspect.txt, library_report.tsv, ktaxonomy.tsv, names.dmp, nodes.dmp and a .md5 file "
                  "with the MD5 of every file.",
        version_from="The archive name in the index's .md5 file (for example k2_standard_20260626.tar.gz: Standard, "
                     "2026-06-26); otherwise declared by you.",
        typical_size="Standard 2026-06-26: 79.6 GB archive, 103.1 GB index (index page).",
        download="catalogue",
        download_note="Dated archives on Amazon S3 with a published MD5 file.",
        sources=("Kraken 2 source: scripts/kraken2 (hash.k2d, opts.k2d, taxo.k2d)",
                 "benlangmead.github.io/aws-indexes/k2 and standard_20260626/standard.md5"),
    ),
    DatabaseKind(
        key="checkm2",
        name="CheckM2 DIAMOND database",
        description="The UniRef100/KEGG DIAMOND database CheckM2 annotates genomes with to estimate completeness and "
                    "contamination.",
        tools=(ToolUse("CheckM2", "database version 3 needs CheckM2 1.1.0 or later; version 2 needs 0.1.0 or later "
                                  "(CheckM2 1.1.0 version_hashes_1.1.0.json)"),),
        source_url="https://doi.org/10.5281/zenodo.14897628",
        licence="CC BY 4.0 (Zenodo record 14897628)",
        licence_url=_CC_BY,
        citation="Chklovski A. et al. (2023) CheckM2: a rapid, scalable and accurate tool for assessing microbial "
                 "genome quality using machine learning. Nature Methods 20, doi:10.1038/s41592-023-01940-w.",
        recognise="uniref100.KO.1.dmnd, directly or in CheckM2_database/; CheckM2's own download also leaves "
                  "CONTENTS.json next to it.",
        version_from="\"version\" in CONTENTS.json; without it, the full checksum identifies the version from the "
                     "SHA-256 CheckM2 publishes for each DIAMOND file.",
        typical_size="Version 3: 1,735,095,710-byte archive; uniref100.KO.1.dmnd is 3,082,500,605 bytes.",
        download="catalogue",
        download_note="Versioned Zenodo record with an MD5.",
        sources=("CheckM2 1.1.0 source: checkm2/versionControl.py, checkm2/fileManager.py, "
                 "checkm2/version/version_hashes_1.1.0.json",
                 "Zenodo record 14897628; CONTENTS.json read from the archive's first block"),
    ),
    DatabaseKind(
        key="busco",
        name="BUSCO lineage dataset",
        description="A BUSCO lineage dataset (for example bacteria_odb12.2): marker gene HMMs and cut-offs BUSCO "
                    "uses to assess genome completeness.",
        tools=(ToolUse("BUSCO", "odb12.2 datasets need BUSCO 6.1.0 or later (BUSCO user guide); the minimum for "
                                "odb10 and odb12 datasets was not confirmed"),),
        source_url="https://busco-data.ezlab.org/v5/data/",
        licence="CC BY-ND 4.0 (BUSCO user guide: the datasets are licensed under the Creative Commons "
                "Attribution-NoDerivatives 4.0 International License)",
        licence_url="https://creativecommons.org/licenses/by-nd/4.0/",
        citation="Tegenfeldt F. et al. OrthoDB and BUSCO update: annotation of orthologs with wider sampling of "
                 "genomes (odb12 datasets); Manni M. et al. (2021) BUSCO update. Molecular Biology and Evolution "
                 "38(10), doi:10.1093/molbev/msab199.",
        recognise="dataset.cfg, hmms/ with the marker HMMs, and scores_cutoff.",
        version_from="dataset.cfg: name and creation_date (also OrthoDB_version and dataset_version).",
        typical_size="bacteria_odb12.2: 58,578,184-byte archive, 77,382,549 bytes unpacked.",
        download="catalogue",
        download_note="Dated archives listed with their MD5 in file_versions.tsv.",
        sources=("BUSCO user guide (busco.ezlab.org)", "busco-data.ezlab.org/v5/data/file_versions.tsv",
                 "bacteria_odb12.2.2026-05-22.tar.gz downloaded and listed on 2026-10-29"),
        unconfirmed=("Older (odb10) datasets may name the date creation instead of creation_date; ARVA reads "
                     "both.",),
    ),
    DatabaseKind(
        key="plasmidfinder",
        name="PlasmidFinder database",
        description="Replicon sequences PlasmidFinder searches to detect and type plasmids (Enterobacterales and "
                    "Gram-positive replicons). ARVA searches the copy ABRicate bundles (db/plasmidfinder), recorded "
                    "read-only when ABRicate is installed.",
        tools=(ToolUse("ABRicate", "ABRicate 1.4.0 reads its bundled copy (db/plasmidfinder: sequences and its BLAST "
                                   "index)", integrated=True),
               ToolUse("PlasmidFinder", "no version requirement is stated in the database repository")),
        source_url="https://bitbucket.org/genomicepidemiology/plasmidfinder_db",
        licence="Not stated in the database repository",
        citation="Carattoli A. et al. (2014) In silico detection and typing of plasmids using PlasmidFinder and "
                 "plasmid multilocus sequence typing. Antimicrobial Agents and Chemotherapy 58(7), "
                 "doi:10.1128/AAC.02412-14.",
        recognise="config (\"# Database configuration file\", one database per line) and the .fsa file of every "
                  "database it lists; ABRicate's copy: db/plasmidfinder/sequences with its BLAST index "
                  "(sequences.njs description \"plasmidfinder\").",
        version_from="VERSION (2.2.0 in the repository on 2026-10-29); ABRicate's copy states only the day the "
                     "package indexed it (sequences.njs last-updated, 2026-04-03 in ABRicate 1.4.0).",
        typical_size="A few megabytes of FASTA (ABRicate 1.4.0's copy: 488 sequences).",
        download="register",
        download_note="Distributed as a git repository, without versioned archives or checksums; ABRicate's copy "
                      "comes with its package (abricate-get_db fetches the repository's HEAD, so ARVA never runs it).",
        sources=("plasmidfinder_db repository (master, 2026-10-29): config, VERSION, INSTALL.py",
                 "ABRicate 1.4.0 package: bin/abricate-get_db (get_plasmidfinder), db/plasmidfinder/sequences.njs"),
        unconfirmed=("The KMA or BLAST index files PlasmidFinder builds are not checked.",
                     "Which plasmidfinder_db commit ABRicate 1.4.0's copy was taken from: its files do not say."),
    ),
    DatabaseKind(
        key="mobsuite",
        name="MOB-suite databases",
        description="The plasmid and biomarker databases MOB-suite (mob_recon, mob_typer) uses to reconstruct and "
                    "type plasmids.",
        tools=(ToolUse("MOB-suite", "mob_suite 3.1.9's mob_init downloads database v. 3.1.8 (Zenodo 10304948)",
                       integrated=True),),
        source_url="https://doi.org/10.5281/zenodo.10304948",
        licence="CC BY 4.0 (Zenodo record 10304948)",
        licence_url=_CC_BY,
        citation="Robertson J., Nash J.H.E. (2018) MOB-suite: software tools for clustering, reconstruction and typing of "
                 "plasmids from draft assemblies. Microbial Genomics 4(8), doi:10.1099/mgen.0.000206.",
        recognise="clusters.txt, rep.dna.fas, mob.proteins.faa, mpf.proteins.faa, orit.fas, repetitive.dna.fas and "
                  "host_range_literature_plasmidDB.txt; the BLAST indexes of ncbi_plasmid_full_seqs.fas (with "
                  "-parse_seqids) and repetitive.dna.fas, ncbi_plasmid_full_seqs.fas.msh and taxa.sqlite show that "
                  "the folder was prepared (by mob_init, with status.txt, or by ARVA, with ARVA_DATABASE.json). The "
                  "FASTA ncbi_plasmid_full_seqs.fas itself is optional: mob_recon 3.1.9 searches only its BLAST "
                  "index.",
        version_from="ARVA_DATABASE.json, written when ARVA prepared the folder (3.1.8); a folder mob_init prepared "
                     "states only its download date (status.txt): declared by you.",
        typical_size="The v. 3.1.8 archive is 472,851,578 bytes; prepared by ARVA without the reference FASTA, "
                     "1.4 GB (2.9 GB with it).",
        download="catalogue",
        download_note="Zenodo record 10304948 (database 3.1.8) with its published MD5. ARVA prepares the folder as "
                      "mob_init would (makeblastdb, mash sketch, ete3's taxa.sqlite from a dated NCBI taxonomy "
                      "archive you confirm) without running mob_init, which downloads with TLS verification off.",
        sources=("mob_suite 3.1.9: mob_suite/mob_init.py, mob_recon.py, utils.py, blast/, wrappers/, config.json",
                 "Zenodo record 10304948", "ete3 3.1.3: ncbi_taxonomy/ncbiquery.py (update_db)",
                 "NCBI pub/taxonomy/taxdump_archive/ listing (2026-10-29)"),
        unconfirmed=("NCBI publishes no checksum for the dated taxonomy archives; ARVA records the SHA-256 of the "
                     "one it downloaded.",),
    ),
    DatabaseKind(
        key="vfdb",
        name="VFDB",
        description="The Virulence Factor Database's protein and nucleotide sequence sets. ARVA searches the copy of "
                    "the core set A nucleotides ABRicate bundles (db/vfdb), recorded read-only when ABRicate is "
                    "installed.",
        tools=(ToolUse("ABRicate", "ABRicate 1.4.0 reads its bundled copy (db/vfdb: VFDB_setA_nt, sequences and its "
                                   "BLAST index)", integrated=True),
               ToolUse("BLAST, DIAMOND and similar", "VFDB's download page states no requirement")),
        source_url="http://www.mgc.ac.cn/VFs/download.htm",
        licence="Not stated on the download page",
        citation="Liu B. et al. (2022) VFDB 2022: a general classification scheme for bacterial virulence factors. "
                 "Nucleic Acids Research 50(D1), doi:10.1093/nar/gkab1107.",
        recognise="One or more of VFDB_setA_pro.fas, VFDB_setA_nt.fas, VFDB_setB_pro.fas and VFDB_setB_nt.fas "
                  "(also .gz); ABRicate's copy: db/vfdb/sequences with its BLAST index (sequences.njs description "
                  "\"vfdb\").",
        version_from="Not stated in the files: declared by you (VFDB shows only a \"Last update\" date on its download "
                     "page). ABRicate's copy states only the day the package indexed it (sequences.njs last-updated, "
                     "2026-04-03 in ABRicate 1.4.0).",
        typical_size="setB nucleotides: 10.19 MB zipped; setA proteins: 1276 kB zipped (download page); ABRicate "
                     "1.4.0's copy: 4,592 sequences.",
        download="register",
        download_note="Undated files over plain HTTP without checksums; ABRicate's copy comes with its package "
                      "(abricate-get_db fetches VFDB_setA_nt.fas.gz over plain HTTP, so ARVA never runs it).",
        accepts=("folder", "file"),
        sources=("VFDB download page (www.mgc.ac.cn/VFs/download.htm, last update 2026-10-23)",
                 "ABRicate 1.4.0 package: bin/abricate-get_db (get_vfdb), db/vfdb/sequences.njs"),
        unconfirmed=("The download page does not say which set is the core and which the full dataset.",
                     "The citation VFDB requests is not stated on the download page.",
                     "Which VFDB release ABRicate 1.4.0's copy was taken from: its files do not say."),
    ),
    DatabaseKind(
        key="genomad",
        name="geNomad database",
        description="The marker and taxonomy database geNomad uses to identify plasmids and viruses.",
        tools=(ToolUse("geNomad", "database 1.9 with geNomad 1.10 to 1.13 (releases.txt on portal.nersc.gov)",
                       integrated=True),),
        source_url="https://doi.org/10.5281/zenodo.14886553",
        licence="CC BY 4.0 (Zenodo record 14886553)",
        licence_url=_CC_BY,
        citation="Camargo A.P. et al. (2023) Identification of mobile genetic elements with geNomad. Nature "
                 "Biotechnology, doi:10.1038/s41587-023-01953-y.",
        recognise="version.txt, genomad_db, genomad_mini_db, genomad_integrase_db, names.dmp, nodes.dmp and "
                  "genomad_marker_metadata.tsv (genomad/database.py).",
        version_from="version.txt (a number such as 1.9).",
        typical_size="The 1.9 archive is 842,023,773 bytes.",
        download="catalogue",
        download_note="Versioned Zenodo record with an MD5.",
        sources=("geNomad source: genomad/database.py, genomad/modules/download.py",
                 "portal.nersc.gov/genomad/__data__/releases.txt", "Zenodo record 14886553"),
        unconfirmed=("geNomad and this database were not installed on ARVA's test machine (disk): the integration "
                     "is written from geNomad 1.13.0's source and not validated with a real run.",),
    ),
    DatabaseKind(
        key="interproscan",
        name="InterProScan installation and data",
        description="An InterProScan 5 installation with its member-database data, for protein domain and family "
                    "annotation. ARVA does not download it: it includes programs, not only data.",
        tools=(ToolUse("InterProScan", "the data belong to the InterProScan release they ship with"),),
        source_url="https://ftp.ebi.ac.uk/pub/software/unix/iprscan/5/",
        licence="InterProScan: Apache-2.0; member databases have their own licences",
        citation="Jones P. et al. (2014) InterProScan 5: genome-scale protein function classification. "
                 "Bioinformatics 30(9), doi:10.1093/bioinformatics/btu031.",
        recognise="interproscan-5.jar and a data/ folder.",
        version_from="Not read from a file: declared by you (ARVA suggests it from the folder name, e.g. "
                     "interproscan-5.78-109.0).",
        typical_size="The 5.78-109.0 archive is 6.6 GB (EBI FTP).",
        download="register",
        download_note="The release archive contains executable programs; ARVA downloads data only.",
        sources=("EBI FTP iprscan/5/5.78-109.0/ (listing and the archive's first members)",),
        unconfirmed=("interproscan.sh, interproscan.properties and the data/ layout were not read from the archive.",),
    ),
    DatabaseKind(
        key="spa_types",
        name="spa types (Ridom SpaServer)",
        description="The spa repeat sequences and spa types of Staphylococcus aureus from the Ridom SpaServer, "
                    "for spa typing. Download them yourself from the SpaServer: ARVA never downloads, copies or "
                    "redistributes them.",
        tools=(ToolUse("spaTyper", "spaTyper 0.3.3 reads sparepeats.fasta and spatypes.txt"),),
        source_url="https://spa.ridom.de/",
        licence="Not stated by the SpaServer; ARVA treats the files as provided by you, for your use only",
        citation="Harmsen D. et al. (2003) Typing of methicillin-resistant Staphylococcus aureus in a university "
                 "hospital setting by using novel software for spa repeat determination and database management. "
                 "Journal of Clinical Microbiology 41(12), doi:10.1128/JCM.41.12.5442-5448.2003.",
        recognise="sparepeats.fasta (FASTA) and spatypes.txt (one \"type,repeats\" line per spa type).",
        version_from="Not stated in the files: declared by you (the date you downloaded them).",
        typical_size="Small text files.",
        download="register",
        download_note="User-provided only: ARVA never redistributes the Ridom files.",
        user_provided_only=True,
        sources=("spaTyper 0.3.3 wheel: spaTyper/utils.py, spaTyper/spa_typing.py",),
    ),
    DatabaseKind(
        key="mlst_schemes",
        name="PubMLST typing schemes (bundled with mlst)",
        description="The MLST schemes mlst ships in its own package: each scheme's profiles (ST definitions) and "
                    "allele sequences, and the BLAST index mlst searches. ARVA reads them where mlst's environment "
                    "installed them, records their date, scheme list and checksum on every MLST job, and ships no "
                    "updater.",
        tools=(ToolUse("mlst", "mlst 2.35.0 reads db/pubmlst (--datadir) and db/blast/mlst.fa (--blastdb)",
                       integrated=True),),
        source_url="https://pubmlst.org/",
        licence="PubMLST terms (updated 2026-05-13): data submitted up to 31 December 2024 may be used and "
                "redistributed with citation; data submitted from 1 January 2025 only for non-commercial academic "
                "research or public health surveillance, and not redistributed",
        licence_url="https://pubmlst.org/terms-conditions",
        citation="Jolley K.A., Bray J.E., Maiden M.C.J. (2018) Open-access bacterial population genomics: BIGSdb "
                 "software, the PubMLST.org website and their applications. Wellcome Open Research 3:124, "
                 "doi:10.12688/wellcomeopenres.14826.1.",
        recognise="pubmlst/<scheme>/<scheme>.txt profile files with <scheme>_info.json, and blast/mlst.fa.njs with "
                  "the BLAST index files it lists.",
        version_from="The download_date every scheme's <scheme>_info.json gives (all the same); db/VERSION.txt and "
                     "the BLAST index's last-updated are recorded beside it.",
        typical_size="About 190 MB (mlst 2.35.0: 162 schemes).",
        download="bundled",
        download_note="Part of mlst's package: it changes only when mlst's environment is rebuilt from a new lock. "
                      "ARVA ships no updater (PubMLST's API needs an account for current data).",
        sources=("mlst 2.35.0 package (Bioconda mlst-2.35.0-hdfd78af_1): README.md, bin/mlst, perl5/MLST/Scheme.pm, "
                 "db/", "pubmlst.org/terms-conditions (updated 2026-05-13)"),
        unconfirmed=("9 schemes come from the Institut Pasteur's BIGSdb (bigsdb.pasteur.fr); its terms were not "
                     "checked.",
                     "Which records were submitted after 31 December 2024: the files give only each scheme's last "
                     "update."),
    ),
    DatabaseKind(
        key="reference_genomes",
        name="Reference genome collection",
        description="Genomes of known species (for example type and reference strains) to identify a genome's "
                    "species by average nucleotide identity (FastANI or skani), for any genus: an NCBI Datasets "
                    "genome package, a FastANI reference list (--rl) or a folder of FASTA files.",
        tools=(ToolUse("FastANI", "--rl takes a file with one genome path per line", integrated=True),
               ToolUse("skani", "skani dist and skani search read FASTA genomes or sketches", integrated=True)),
        source_url="https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/data-packages/genome/",
        licence="NCBI data; each genome's own terms apply (NCBI Datasets)",
        citation="Jain C. et al. (2018) High throughput ANI analysis of 90K prokaryotic genomes reveals clear "
                 "species boundaries. Nature Communications 9:5114, doi:10.1038/s41467-018-07641-9.",
        recognise="An NCBI Datasets genome package (ncbi_dataset/data/assembly_data_report.jsonl, "
                  "dataset_catalog.json and one folder of *_genomic.fna per accession), a text file with one genome "
                  "path per line, or a folder of FASTA files (.fna, .fa, .fasta, .fas, also .gz).",
        version_from="Its source and date plus a fingerprint of its sorted accession list. NCBI's package files do "
                     "not state the download date: you declare it (ARVA suggests the date in the zip's entries).",
        typical_size="About 3 MB per bacterial genome (uncompressed FASTA).",
        download="register",
        download_note="Built by you from NCBI Datasets; a package zip can be extracted into a copy.",
        accepts=("folder", "file"),
        sources=("NCBI Datasets documentation: genome data package", "A two-genome package downloaded from the NCBI "
                 "Datasets v2 API on 2026-10-29 (README.md, md5sum.txt, assembly_data_report.jsonl fields)",
                 "FastANI source: parseCmdArgs.hpp (--rl)"),
        unconfirmed=("The zip entries' date is when NCBI built the package, in a time zone the zip does not "
                     "record.",),
    ),
)

BY_KEY = {k.key: k for k in KINDS}


def kind(key: str) -> DatabaseKind:
    try:
        return BY_KEY[key]
    except KeyError:
        raise LookupError(f"no database kind {key!r}") from None


# --- Compatibility with the tool versions ARVA runs -------------------------------------------------------------

# bakta/__init__.py __db_schema_version__ of the Bakta versions ARVA has checked.
BAKTA_SCHEMA_BY_VERSION = {"1.12.2": 6}


@dataclass(frozen=True)
class Compatibility:
    # compatible | incompatible | unknown
    status: str
    code: str
    params: dict[str, str | int]


def bakta_version() -> str | None:
    from arva_tools.registry import detect

    d = detect("bakta")
    return d.version if d.path else None


# The kinds species identification reads whose files state no version requirement ARVA could check.
_NO_REQUIREMENT = {"reference_genomes": "FastANI and skani", "mash": "Mash", "sylph": "sylph"}


def compatibility(kind_key: str, version_json: dict | None = None, installed: str | None = None,
                  version: str | None = None) -> Compatibility:
    """Whether the tool version ARVA runs can read a database of this kind: Bakta by its schema, GTDB-Tk by the GTDB
    release (VERSION_DATA), mlst's and ABRicate's bundled databases always, MOB-suite and geNomad by the database
    versions their sources pair with them; the kinds species identification reads without a stated requirement are
    compatible; for the other kinds the tool is not integrated and compatibility is unknown (the kind lists what its
    docs require)."""
    if kind_key == "mlst_schemes":
        return Compatibility("compatible", "bundled_with_tool", {"tool": "mlst"})
    if kind_key in _NO_REQUIREMENT:
        return Compatibility("compatible", "no_requirement", {"tool": _NO_REQUIREMENT[kind_key]})
    if kind_key == "gtdbtk":
        from arva_tools.gtdbtk import COMPATIBLE_DATA

        params: dict[str, str | int] = {"tool": "GTDB-Tk", "version": "2.8.0", "needs": ", ".join(COMPATIBLE_DATA),
                                        "release": version or "?"}
        if not version:
            return Compatibility("unknown", "release_unknown", params)
        return Compatibility("compatible" if version in COMPATIBLE_DATA else "incompatible",
                             "release_ok" if version in COMPATIBLE_DATA else "release_mismatch", params)
    if kind_key == "amrfinderplus":
        return _amrfinderplus(version, (version_json or {}).get("database_format_version"), installed)
    if kind_key in ("vfdb", "plasmidfinder"):
        if (version_json or {}).get("variant") == "abricate":
            return Compatibility("compatible", "bundled_with_tool", {"tool": "ABRicate"})
        return Compatibility("unknown", "tool_not_integrated", {"tool": BY_KEY[kind_key].tools[-1].tool})
    if kind_key in TESTED_DATA:
        return _tested(kind_key, version, installed)
    if kind_key != "bakta":
        return Compatibility("unknown", "tool_not_integrated", {"tool": BY_KEY[kind_key].tools[0].tool})
    installed = installed if installed is not None else bakta_version()
    if not installed:
        return Compatibility("unknown", "tool_not_installed", {"tool": "Bakta"})
    schema = BAKTA_SCHEMA_BY_VERSION.get(installed)
    if schema is None:
        return Compatibility("unknown", "tool_version_unchecked", {"tool": "Bakta", "version": installed})
    major = (version_json or {}).get("major")
    if not isinstance(major, int):
        return Compatibility("unknown", "schema_unknown", {"tool": "Bakta", "version": installed})
    if major == schema:
        return Compatibility("compatible", "schema_ok", {"tool": "Bakta", "version": installed, "schema": schema})
    return Compatibility("incompatible", "schema_mismatch", {"tool": "Bakta", "version": installed, "schema": schema,
                                                             "found": major})


# The database versions checked with the tool versions ARVA runs: MOB-suite 3.1.9's mob_init downloads database
# 3.1.8 (mob_suite/config.json); geNomad's releases.txt pairs database 1.9 with geNomad 1.10 to 1.13.
TESTED_DATA = {"mobsuite": ("MOB-suite", "mobsuite", {"3.1.8": ("3.1.9",)}),
               "genomad": ("geNomad", "genomad", {"1.9": ("1.10", "1.11", "1.12", "1.13")})}


def _tested(kind_key: str, version: str | None, installed: str | None) -> Compatibility:
    from arva_tools.registry import detect

    tool, tool_id, pairs = TESTED_DATA[kind_key]
    if installed is None:
        d = detect(tool_id)
        installed = d.version if d.path else None
    if not installed:
        return Compatibility("unknown", "tool_not_installed", {"tool": tool})
    params: dict[str, str | int] = {"tool": tool, "version": installed, "data": version or "?"}
    accepted = pairs.get(version or "")
    if accepted is None:
        return Compatibility("unknown", "data_unpaired", {**params, "needs": ", ".join(pairs)})
    if any(installed == v or installed.startswith(v + ".") for v in accepted):
        return Compatibility("compatible", "data_paired", params)
    return Compatibility("unknown", "tool_version_unchecked", params)


def amrfinderplus_version() -> str | None:
    from arva_tools.registry import detect

    d = detect("amrfinderplus")
    return d.version if d.path else None


def _amrfinderplus(version: str | None, data_format: str | None, installed: str | None) -> Compatibility:
    """AMRFinderPlus's two rules (amrfinder.cpp): data at least the version the software needs, software at least the
    database's format version."""
    from arva_tools.amrfinderplus import data_compatible

    installed = installed if installed is not None else amrfinderplus_version()
    if not installed:
        return Compatibility("unknown", "tool_not_installed", {"tool": "AMRFinderPlus"})
    check = data_compatible(installed, version, data_format)
    params: dict[str, str | int] = {"tool": "AMRFinderPlus", "version": installed, "data": version or "?",
                                    "needs": check["needs_data"] or "?", "format": data_format or "?"}
    code = {"compatible": "data_ok", "data_too_old": "data_too_old", "software_too_old": "software_too_old",
            "unknown": "tool_version_unchecked" if check["needs_data"] is None else "data_unknown"}[check["status"]]
    status = {"compatible": "compatible", "unknown": "unknown"}.get(check["status"], "incompatible")
    return Compatibility(status, code, params)
