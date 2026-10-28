"""Reference databases ARVA knows how to install, with facts checked against their official sources.

Bakta database 6.0 (checked 2026-10-28):
- Zenodo record 14916843 (API https://zenodo.org/api/records/14916843): title "Bakta database 6.0", published
  2025-02-24, licence cc-by-4.0, files db-light.tar.xz (1,344,199,496 bytes, md5 4a6e059ded39e9c5537ef4137d2f5648)
  and db.tar.xz (31,921,769,288 bytes, md5 4c1115e40abfa2b464ae5dd988bdd88e); its file URLs answer byte ranges (206).
- The same MD5s are in Bakta's README ("light: 1.3 Gb zipped, 3.9 Gb unzipped"; "full: 30 Gb zipped, 84 Gb
  unzipped") and in db-versions.json of that record (also "software-min": Bakta 1.11).
- Bakta 1.12.2 (PyPI wheel, bakta/db.py): database schema 6; `check()` needs version.json with date, major, minor
  and type, and the files in REQUIRED_FILES plus psc.dmnd (full) or pscc.dmnd (light); `bakta_db download` extracts
  the archive into db-light/ or db/.
"""
from __future__ import annotations

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


@dataclass(frozen=True)
class CatalogueEntry:
    key: str
    name: str
    tool: str
    status: str  # "available" (ARVA can install it) or "planned"
    description: str
    version: str | None = None
    release_date: str | None = None
    db_type: str | None = None
    source_url: str | None = None
    doi: str | None = None
    download_url: str | None = None
    filename: str | None = None
    archive_bytes: int | None = None
    checksum_algorithm: str | None = None
    checksum: str | None = None
    checksum_sources: tuple[str, ...] = ()
    # The publisher's statement of the unpacked size, and the bytes ARVA reserves for it.
    extracted_size_note: str | None = None
    extracted_bytes_estimate: int | None = None
    top_dir: str | None = None
    licence: str | None = None
    licence_url: str | None = None
    terms: str | None = None
    citation: str | None = None
    compatibility: str | None = None
    external_versions: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def install_dir(self) -> str:
        """Folder under ARVA_DB_DIR the database is installed into."""
        return f"{self.key}/{self.version}"


_BAKTA_COMMON = dict(
    tool="bakta",
    status="available",
    version="6.0",
    release_date="2025-02-24",
    source_url=_BAKTA_RECORD,
    doi="10.5281/zenodo.14916843",
    checksum_algorithm="md5",
    checksum_sources=_BAKTA_CHECKSUM_SOURCES,
    licence="CC BY 4.0",
    licence_url="https://creativecommons.org/licenses/by/4.0/",
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
        key="amrfinderplus",
        name="AMRFinderPlus database",
        tool="amrfinderplus",
        status="planned",
        description="NCBI's database of antimicrobial resistance genes and point mutations, read by AMRFinderPlus "
                    "(and by Bakta's AMR expert system). Planned with the AMRFinderPlus integration.",
    ),
    CatalogueEntry(
        key="checkm2",
        name="CheckM2 database",
        tool="checkm2",
        status="planned",
        description="The protein database CheckM2 uses to estimate genome completeness and contamination. Planned "
                    "with the genome quality module.",
    ),
)

BY_KEY = {e.key: e for e in CATALOGUE}


def entry(key: str) -> CatalogueEntry:
    try:
        return BY_KEY[key]
    except KeyError:
        raise LookupError(f"no catalogue database {key!r}") from None


def bakta_entry_for(db_type: str) -> CatalogueEntry | None:
    return next((e for e in CATALOGUE if e.tool == "bakta" and e.db_type == db_type), None)
