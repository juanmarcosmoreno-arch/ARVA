"""Database versions ARVA can download, with facts checked against their official sources (database_kinds.py has the
kinds and what ARVA registers without downloading).

Bakta database 6.0 (checked 2026-10-28):
- Zenodo record 14916843 (API https://zenodo.org/api/records/14916843): title "Bakta database 6.0", published
  2025-02-24, licence cc-by-4.0, files db-light.tar.xz (1,344,199,496 bytes, md5 4a6e059ded39e9c5537ef4137d2f5648)
  and db.tar.xz (31,921,769,288 bytes, md5 4c1115e40abfa2b464ae5dd988bdd88e); its file URLs answer byte ranges (206).
- The same MD5s are in Bakta's README ("light: 1.3 Gb zipped, 3.9 Gb unzipped"; "full: 30 Gb zipped, 84 Gb
  unzipped") and in db-versions.json of that record (also "software-min": Bakta 1.11).
- Bakta 1.12.2 (PyPI wheel, bakta/db.py): database schema 6; `check()` needs version.json with date, major, minor
  and type, and the files in REQUIRED_FILES plus psc.dmnd (full) or pscc.dmnd (light); `bakta_db download` extracts
  the archive into db-light/ or db/.

The other entries (checked 2026-10-29) cite their source in checksum_sources; their unpacked sizes were measured by
listing the archive (BUSCO: downloaded; geNomad and CheckM2: streamed through `tar -tv` without keeping it) or are the
publisher's statement (GTDB-Tk, Kraken 2), read in the larger unit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BAKTA_SCHEMA_MAJOR = 6

# bakta/db.py FILE_NAMES (Bakta 1.12.2).
BAKTA_REQUIRED_FILES = (
    "antifam.h3f", "antifam.h3i", "antifam.h3m", "antifam.h3p", "bakta.db", "expert-protein-sequences.dmnd",
    "ncRNA-genes.i1f", "ncRNA-genes.i1i", "ncRNA-genes.i1m", "ncRNA-genes.i1p",
    "ncRNA-regions.i1f", "ncRNA-regions.i1i", "ncRNA-regions.i1m", "ncRNA-regions.i1p",
    "oric.fna", "orit.fna", "pfam.h3f", "pfam.h3i", "pfam.h3m", "pfam.h3p", "rfam-go.tsv",
    "rRNA.i1f", "rRNA.i1i", "rRNA.i1m", "rRNA.i1p", "sorf.dmnd",
)
BAKTA_TYPE_FILE = {"full": "psc.dmnd", "light": "pscc.dmnd"}
BAKTA_VERSION_KEYS = ("date", "major", "minor", "type")

GIB = 1024**3

_BAKTA_RECORD = "https://zenodo.org/records/14916843"
_BAKTA_FILES = "https://zenodo.org/api/records/14916843/files"
_BAKTA_CHECKSUM_SOURCES = (
    "Zenodo record 14916843 (file checksum)",
    "Bakta README, Database section",
    "db-versions.json in Zenodo record 14916843",
)
# Listed in the description of Zenodo record 14916843.
_BAKTA_EXTERNAL = {
    "NCBI AMRFinderPlus": "2024-12-18.1", "COG": "2024", "DoriC": "12", "ISFinder": "2019-09-25",
    "MOB-suite": "3", "Pfam": "37.2", "RefSeq": "r228", "Rfam": "15", "UniProtKB/Swiss-Prot": "2025_01",
    "VFDB": "2025-02-14",
}
_BAKTA_NOTES = (
    "Bakta 1.12.2's AMR expert system reads an AMRFinderPlus database from amrfinderplus-db/latest inside this "
    "folder (bakta/expert/amrfinder.py) and needs AMRFinderPlus 4.2.7 or later (bakta/utils.py). The light 6.0 "
    "archive contains amrfinderplus-db/2024-12-18.1 (database format 4.0.1) with latest linking to it, the release "
    "its version.json lists (seen when ARVA installed it on 2026-10-28; the full archive was not downloaded to "
    "check).",
    "Bakta's own installer (bakta_db download) then also runs amrfinder_update --force_update, which fetches an "
    "AMRFinderPlus database from NCBI, a version neither Bakta nor ARVA pins. ARVA does not, so the AMRFinderPlus "
    "data stay the release this database was built with; updating them would be a separate, recorded step.",
)
_CC_BY = "https://creativecommons.org/licenses/by/4.0/"


@dataclass(frozen=True)
class CatalogueEntry:
    key: str
    name: str
    kind: str
    tool: str
    description: str
    version: str
    release_date: str | None
    source_url: str
    download_url: str
    filename: str
    archive_bytes: int
    checksum: str
    checksum_sources: tuple[str, ...]
    # The publisher's statement of the unpacked size (or ARVA's listing of the archive), and the bytes ARVA reserves.
    extracted_size_note: str
    extracted_bytes_estimate: int
    # The archive's single top folder, or None when its members lie at its root (they are unpacked into the folder).
    top_dir: str | None
    licence: str
    terms: str
    citation: str
    compatibility: str
    checksum_algorithm: str = "md5"
    db_type: str | None = None
    doi: str | None = None
    licence_url: str | None = None
    external_versions: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    status: str = "available"

    @property
    def install_dir(self) -> str:
        """The default folder, inside the chosen database folder, the database is installed into."""
        return f"{self.key}/{re.sub(r'[^A-Za-z0-9._-]+', '-', self.version).strip('-')}"


_BAKTA_COMMON = dict(
    kind="bakta",
    tool="bakta",
    version="6.0",
    release_date="2025-02-24",
    source_url=_BAKTA_RECORD,
    doi="10.5281/zenodo.14916843",
    checksum_sources=_BAKTA_CHECKSUM_SOURCES,
    licence="CC BY 4.0",
    licence_url=_CC_BY,
    terms="Licence of the Zenodo record: Creative Commons Attribution 4.0. Cite the database and Bakta when you "
          "publish results; the database was built from the external databases listed (UniProt, RefSeq, Pfam, Rfam, "
          "COG, AMRFinderPlus, VFDB, ISFinder, DoriC, MOB-suite).",
    citation="Schwengers O. et al. (2021) Bakta: rapid and standardized annotation of bacterial genomes via "
             "alignment-free sequence identification. Microbial Genomics 7(11), doi:10.1099/mgen.0.000685. Database: "
             "Schwengers O. (2025) Bakta database 6.0, Zenodo, doi:10.5281/zenodo.14916843.",
    compatibility="Bakta 1.11 or later (db-versions.json); database schema 6, the schema Bakta 1.12.2 requires.",
    external_versions=_BAKTA_EXTERNAL,
    notes=_BAKTA_NOTES,
)

CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry(
        key="bakta-light",
        name="Bakta database (light)",
        description="The light Bakta database: all non-coding feature information, but only UniRef50 cluster "
                    "information (PSCC) for coding sequences, so annotations of proteins are less specific than "
                    "with the full database. Smaller and faster.",
        db_type="light",
        download_url=f"{_BAKTA_FILES}/db-light.tar.xz/content",
        filename="db-light.tar.xz",
        archive_bytes=1_344_199_496,
        checksum="4a6e059ded39e9c5537ef4137d2f5648",
        extracted_size_note="3.9 Gb unzipped (Bakta README)",
        extracted_bytes_estimate=int(3.9 * GIB),
        top_dir="db-light",
        **_BAKTA_COMMON,
    ),
    CatalogueEntry(
        key="bakta-full",
        name="Bakta database (full)",
        description="The full Bakta database, recommended by Bakta for the most specific annotations and all "
                    "features. It needs tens of gigabytes: about 32 GB to download and 84 Gb unpacked.",
        db_type="full",
        download_url=f"{_BAKTA_FILES}/db.tar.xz/content",
        filename="db.tar.xz",
        archive_bytes=31_921_769_288,
        checksum="4c1115e40abfa2b464ae5dd988bdd88e",
        extracted_size_note="84 Gb unzipped (Bakta README)",
        extracted_bytes_estimate=84 * GIB,
        top_dir="db",
        **_BAKTA_COMMON,
    ),
    CatalogueEntry(
        key="gtdbtk-r232",
        name="GTDB-Tk reference data R232",
        kind="gtdbtk",
        tool="gtdbtk",
        description="GTDB release 232 (R11-RS232: 901,341 genomes in 199,923 species clusters) packaged for GTDB-Tk.",
        version="r232",
        release_date="2026-04-15",
        source_url="https://data.gtdb.ecogenomic.org/releases/release232/232.0/",
        download_url="https://data.gtdb.ecogenomic.org/releases/release232/232.0/auxillary_files/gtdbtk_package/"
                     "full_package/gtdbtk_r232_data.tar.gz",
        filename="gtdbtk_r232_data.tar.gz",
        archive_bytes=60_806_405_195,
        checksum="25a59e0352b1fd150c589f56559767d4",
        checksum_sources=("MD5SUM.txt of GTDB release 232.0",),
        extracted_size_note="~100G of external data for R232 (GTDB-Tk installation guide)",
        extracted_bytes_estimate=100 * GIB,
        top_dir="release232",
        licence="CC BY-SA 4.0",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        terms="GTDB data are licensed under Creative Commons Attribution-ShareAlike 4.0 (GTDB downloads page). Cite "
              "GTDB and GTDB-Tk when you publish results.",
        citation="Chaumeil P.-A. et al. (2022) GTDB-Tk v2. Bioinformatics, doi:10.1093/bioinformatics/btac672. Parks "
                 "D.H. et al. (2025) GTDB release 10. Nucleic Acids Research, doi:10.1093/nar/gkaf1040.",
        compatibility="GTDB-Tk 2.7.0 or later (GTDB-Tk installation guide); GTDB-Tk 2.8.0 accepts R232 only.",
    ),
    CatalogueEntry(
        key="kraken2-standard",
        name="Kraken 2 Standard index (2026-06-26)",
        kind="kraken2",
        tool="kraken2",
        description="RefSeq archaea, bacteria, viral, plasmid, human and UniVec_Core, built with Kraken 2's default "
                    "k-mer settings by the Kraken 2 maintainers.",
        version="standard 2026-06-26",
        release_date="2026-06-26",
        source_url="https://benlangmead.github.io/aws-indexes/k2",
        download_url="https://genome-idx.s3.amazonaws.com/kraken/k2_standard_20260626.tar.gz",
        filename="k2_standard_20260626.tar.gz",
        archive_bytes=85_465_587_439,
        checksum="70477acf5ad91271725d77aadd8ca6b1",
        checksum_sources=("standard_20260626/standard.md5 (linked from the index page)",),
        extracted_size_note="Index size 103.1 GB (index page)",
        extracted_bytes_estimate=int(103.1 * GIB),
        top_dir=None,
        licence="Not stated by the publisher",
        terms="The index page states no licence; the indexes are \"open access thanks to the AWS Open Data "
              "Sponsorship Program\". library_report.tsv lists the source of every sequence. Cite Kraken 2.",
        citation="Wood D.E., Lu J., Langmead B. (2019) Improved metagenomic analysis with Kraken 2. Genome Biology "
                 "20:257, doi:10.1186/s13059-019-1891-0.",
        compatibility="No Kraken 2 version requirement is stated on the index page.",
        notes=("The index includes standard.md5 with the MD5 of every file: the full verification compares them.",),
    ),
    CatalogueEntry(
        key="checkm2-3",
        name="CheckM2 database version 3",
        kind="checkm2",
        tool="checkm2",
        description="UniRef100/KEGG DIAMOND database (uniref100.KO.1.dmnd) for CheckM2's completeness and "
                    "contamination estimates.",
        version="3",
        release_date="2025-02-20",
        source_url="https://zenodo.org/records/14897628",
        doi="10.5281/zenodo.14897628",
        download_url="https://zenodo.org/api/records/14897628/files/checkm2_database.tar.gz/content",
        filename="checkm2_database.tar.gz",
        archive_bytes=1_735_095_710,
        checksum="07c10655620843b517d0df0c160d911f",
        checksum_sources=("Zenodo record 14897628 (file checksum)",),
        extracted_size_note="CONTENTS.json (122 bytes) and CheckM2_database/uniref100.KO.1.dmnd (3,082,500,605 "
                            "bytes), from the archive's listing",
        extracted_bytes_estimate=3_082_500_727,
        top_dir=None,
        licence="CC BY 4.0",
        licence_url=_CC_BY,
        terms="Licence of the Zenodo record: Creative Commons Attribution 4.0. Cite CheckM2.",
        citation="Chklovski A. et al. (2023) CheckM2. Nature Methods 20, doi:10.1038/s41592-023-01940-w.",
        compatibility="CheckM2 1.1.0 or later (version_hashes_1.1.0.json: incompatible below 1.1.0).",
    ),
    CatalogueEntry(
        key="busco-bacteria-odb12.2",
        name="BUSCO bacteria_odb12.2",
        kind="busco",
        tool="busco",
        description="BUSCO's lineage dataset for all Bacteria: 116 marker genes from 3130 species (OrthoDB 12.2).",
        version="bacteria_odb12.2 (2026-05-22)",
        release_date="2026-05-22",
        source_url="https://busco-data.ezlab.org/v5/data/",
        download_url="https://busco-data.s3.amazonaws.com/lineages/bacteria_odb12.2.2026-05-22.tar.gz",
        filename="bacteria_odb12.2.2026-05-22.tar.gz",
        archive_bytes=58_578_184,
        checksum="e21960d275e09687a86aace486f2886a",
        checksum_sources=("busco-data.ezlab.org/v5/data/file_versions.tsv",),
        extracted_size_note="77,382,549 bytes (listing of the archive, 2026-10-29)",
        extracted_bytes_estimate=77_382_549,
        top_dir="bacteria_odb12.2",
        licence="CC BY-ND 4.0",
        licence_url="https://creativecommons.org/licenses/by-nd/4.0/",
        terms="The BUSCO datasets are licensed under Creative Commons Attribution-NoDerivatives 4.0 (BUSCO user "
              "guide); cite the BUSCO paper of the dataset's version. busco-data.ezlab.org redirects downloads to "
              "busco-data.s3.amazonaws.com, the address ARVA downloads from.",
        citation="Tegenfeldt F. et al. OrthoDB and BUSCO update: annotation of orthologs with wider sampling of "
                 "genomes. Manni M. et al. (2021) Molecular Biology and Evolution 38(10), doi:10.1093/molbev/msab199.",
        compatibility="BUSCO 6.1.0 or later (BUSCO user guide: odb12.2 datasets).",
    ),
    CatalogueEntry(
        key="genomad-1.9",
        name="geNomad database 1.9",
        kind="genomad",
        tool="genomad",
        description="geNomad's markers, MMseqs2 databases and taxonomy for identifying plasmids and viruses.",
        version="1.9",
        release_date="2025-02-18",
        source_url="https://zenodo.org/records/14886553",
        doi="10.5281/zenodo.14886553",
        download_url="https://zenodo.org/api/records/14886553/files/genomad_db_v1.9.tar.gz/content",
        filename="genomad_db_v1.9.tar.gz",
        archive_bytes=842_023_773,
        checksum="67244b528bb8bed464d1ca147136d33e",
        checksum_sources=("Zenodo record 14886553 (file checksum)",),
        extracted_size_note="1,471,626,195 bytes (listing of the archive, 2026-10-29)",
        extracted_bytes_estimate=1_471_626_195,
        top_dir="genomad_db",
        licence="CC BY 4.0",
        licence_url=_CC_BY,
        terms="Licence of the Zenodo record: Creative Commons Attribution 4.0. Cite geNomad.",
        citation="Camargo A.P. et al. (2023) Identification of mobile genetic elements with geNomad. Nature "
                 "Biotechnology, doi:10.1038/s41587-023-01953-y.",
        compatibility="geNomad 1.10 to 1.13 (releases.txt on portal.nersc.gov/genomad).",
    ),
    CatalogueEntry(
        key="mobsuite-3.1.8",
        name="MOB-suite database 3.1.8",
        kind="mobsuite",
        tool="mobsuite",
        description="MOB-suite's reference plasmids (with their MOB-cluster assignments), replicon, relaxase, MPF and "
                    "oriT sequences and repetitive elements, read by mob_recon and mob_typer. ARVA prepares the folder as "
                    "mob_init would (BLAST indexes, Mash sketch, NCBI taxonomy) without running mob_init.",
        version="3.1.8",
        release_date="2023-12-08",
        source_url="https://zenodo.org/records/10304948",
        doi="10.5281/zenodo.10304948",
        download_url="https://zenodo.org/api/records/10304948/files/data.tar.gz/content",
        filename="data.tar.gz",
        archive_bytes=472_851_578,
        checksum="670e293e4ff1918db5b654278a60bea8",
        checksum_sources=("Zenodo record 10304948 (file checksum)",),
        extracted_size_note="1,656,164,567 bytes unpacked, of which ncbi_plasmid_full_seqs.fas is 1,641,486,485 "
                            "(listing of the archive, 2026-10-29); prepared by ARVA without that FASTA, the folder holds "
                            "1,413,260,939 bytes (BLAST index, Mash sketch, taxa.sqlite of taxdmp_2026-10-01)",
        extracted_bytes_estimate=1_413_260_939,
        top_dir="data",
        licence="CC BY 4.0",
        licence_url=_CC_BY,
        terms="Licence of the Zenodo record: Creative Commons Attribution 4.0. Cite MOB-suite. The NCBI taxonomy ARVA adds "
              "for host-range predictions is NCBI data (public domain).",
        citation="Robertson J., Nash J.H.E. (2018) MOB-suite: software tools for clustering, reconstruction and typing of "
                 "plasmids from draft assemblies. Microbial Genomics 4(8), doi:10.1099/mgen.0.000206.",
        compatibility="The database mob_init of MOB-suite 3.1.9 downloads (mob_suite/config.json: Zenodo 10304948).",
        notes=("mob_init downloads this archive with TLS verification turned off and then the latest NCBI taxonomy over "
               "plain HTTP (ete3); ARVA downloads the archive over HTTPS, compares its MD5 with Zenodo's, and builds "
               "taxa.sqlite from the dated NCBI taxonomy archive you confirm.",
               "The reference plasmids' FASTA (1.6 GB) is only searched through its BLAST index by mob_recon 3.1.9; ARVA "
               "keeps it only when you ask, and records its SHA-256 either way."),
    ),
)

BY_KEY = {e.key: e for e in CATALOGUE}


def entry(key: str) -> CatalogueEntry:
    try:
        return BY_KEY[key]
    except KeyError:
        raise LookupError(f"no catalogue database {key!r}") from None


def bakta_entry_for(db_type: str) -> CatalogueEntry | None:
    return next((e for e in CATALOGUE if e.kind == "bakta" and e.db_type == db_type), None)


def for_kind(kind: str) -> list[CatalogueEntry]:
    return [e for e in CATALOGUE if e.kind == kind]
