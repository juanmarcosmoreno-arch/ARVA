"""CONSTRUCTED miniature database folders, shaped like each kind's official layout (the file names its tool or
publisher uses; see app/services/database_kinds.py for the sources) but with tiny placeholder contents. None of them
is a real database: they only exercise ARVA's recognition, versioning, registration and verification."""
from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path

from app.services.database_catalogue import BAKTA_REQUIRED_FILES

NOTE = "CONSTRUCTED test file for ARVA, not a real database file\n"


def _write(root: Path, rel: str, text: str = NOTE) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def bakta(root: Path, version: dict | None = None, omit=()) -> Path:
    info = version or {"date": "2025-02-24", "major": 6, "minor": 0, "type": "light"}
    _write(root, "version.json", json.dumps(info))
    for name in (*BAKTA_REQUIRED_FILES, "pscc.dmnd" if info.get("type") != "full" else "psc.dmnd"):
        if name not in omit:
            _write(root, name)
    return root


def amrfinderplus(root: Path, indexed: bool = True) -> Path:
    _write(root, "version.txt", "2026-08-07.1\n")
    _write(root, "database_format_version.txt", "4.2.0\n")
    for name in ("AMRProt.fa", "AMR.LIB", "AMR_CDS.fa", "fam.tsv", "taxgroup.tsv", "AMRProt-mutation.tsv",
                 "AMRProt-susceptible.tsv", "AMRProt-suppress.tsv"):
        _write(root, name)
    if indexed:
        _write(root, "AMRProt.fa.phr")
    return root


def gtdbtk(root: Path, release: str = "r232") -> Path:
    _write(root, "metadata/metadata.txt", f'RED_DIST_BAC_DICT={{"p__": 0.3}}\nVERSION_DATA={release}\n')
    _write(root, "taxonomy/gtdb_taxonomy.tsv", "G000000001\td__Bacteria;p__Constructed\n")
    for d in ("msa", "masks", "pplacer", "skani", "radii", "mrca_red", "markers", "split"):
        _write(root, f"{d}/placeholder.txt")
    return root


def skani(root: Path) -> Path:
    _write(root, "markers.bin", "SKANI-DB-V2: this database requires skani >= 0.4.0.\n")
    for name in ("markers.bin2", "sketches.db2", "index.db2"):
        _write(root, name)
    _write(root, "README.txt", "skani database\n==============\n\nBuilt by   : skani 0.4.0\nBuilt on   : 2026-10-01\n")
    return root


def kraken2(root: Path, with_md5: bool = True) -> Path:
    for name in ("hash.k2d", "opts.k2d", "taxo.k2d", "inspect.txt", "library_report.tsv"):
        _write(root, name)
    if with_md5:
        lines = [f"{hashlib.md5((root / n).read_bytes()).hexdigest()}  {n}"
                 for n in ("hash.k2d", "opts.k2d", "taxo.k2d", "inspect.txt", "library_report.tsv")]
        lines.append("0123456789abcdef0123456789abcdef  k2_standard_20260626.tar.gz")
        _write(root, "standard.md5", "\n".join(lines) + "\n")
    return root


def checkm2(root: Path, contents: bool = True) -> Path:
    dmnd = _write(root, "CheckM2_database/uniref100.KO.1.dmnd")
    if contents:
        _write(root, "CONTENTS.json", json.dumps({"CheckM2_database/uniref100.KO.1.dmnd":
                                                  hashlib.md5(dmnd.read_bytes()).hexdigest(),
                                                  "zenodo_backpack_version": 1, "version": "3"}))
    return root


def busco(root: Path) -> Path:
    _write(root, "dataset.cfg", "name=bacteria_odb12.2\ndomain=prokaryota\ncreation_date=2026-05-22\n"
                                "number_of_BUSCOs=2\nnumber_of_species=1\nOrthoDB_version=12.2\ndataset_version=01\n")
    _write(root, "hmms/1at2.hmm")
    _write(root, "hmms/2at2.hmm")
    _write(root, "scores_cutoff", "1at2\t100\n2at2\t100\n")
    return root


def plasmidfinder(root: Path) -> Path:
    _write(root, "config", "# Database configuration file - Describes the content of the database\n"
                           "#db_prefix\tname\tdescription\nenterobacteriales\tEnterobacteriales\tEnterobacteriales\n"
                           "Inc18\tGram Positive\tInc18\n")
    _write(root, "enterobacteriales.fsa", ">IncFIB_1\nACGT\n")
    _write(root, "Inc18.fsa", ">rep_1\nACGT\n")
    _write(root, "VERSION", "2.2.0\n")
    return root


def mobsuite(root: Path) -> Path:
    """A folder mob_init prepared (status.txt): the files mob_recon reads, the BLAST indexes, the Mash sketch and
    taxa.sqlite (empty files with MOB-suite 3.1.9's names)."""
    from arva_tools import mobsuite as mob

    for name in (mob.PLASMID_FASTA, *mob.DB_FILES, *mob.PLASMID_INDEX, *mob.REPETITIVE_INDEX, mob.MASH_SKETCH,
                 mob.TAXA, mob.TAXA_EXTRA):
        _write(root, name)
    _write(root, "status.txt", "Download date: 2026-09-01. Removing lock file.")
    return root


def vfdb(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with gzip.open(root / "VFDB_setB_pro.fas.gz", "wt") as fh:
        fh.write(">VFG000001 CONSTRUCTED\nMKV\n")
    return root


def genomad(root: Path) -> Path:
    _write(root, "version.txt", "1.9\n")
    for name in ("genomad_db", "genomad_mini_db", "genomad_integrase_db", "names.dmp", "nodes.dmp",
                 "genomad_marker_metadata.tsv"):
        _write(root, name)
    return root


def interproscan(root: Path) -> Path:
    _write(root, "interproscan-5.jar")
    _write(root, "data/pfam/placeholder.txt")
    return root


def spa_types(root: Path) -> Path:
    _write(root, "sparepeats.fasta", ">r01\nAAAGAAGACAACAAAAAACCTGGT\n>r02\nGAGGAAGACAACAACAAACCTGGT\n")
    _write(root, "spatypes.txt", "t001,26-30-17\nt002,26-23-17\n")
    return root


# --- NCBI Datasets genome package (the layout of NCBI's documentation and of a real two-genome package) ----------

GENOMES = (
    # accession, organism, strain, type label, RefSeq category
    ("GCF_000000001.1", "Staphylococcus constructus", "CONSTRUCTED-1", "TYPE_MATERIAL", "reference genome"),
    ("GCF_000000002.1", "Staphylococcus constructus subsp. alter", "CONSTRUCTED-2", None, None),
    ("GCF_000000003.2", "Bacillus inventus", "CONSTRUCTED-3", "TYPE_MATERIAL", None),
)


def _report_line(acc, organism, strain, label, category) -> str:
    obj = {"accession": acc, "currentAccession": acc, "sourceDatabase": "SOURCE_DATABASE_REFSEQ",
           "organism": {"taxId": 1, "organismName": organism, "infraspecificNames": {"strain": strain}},
           "assemblyInfo": {"assemblyLevel": "Complete Genome", **({"refseqCategory": category} if category else {})}}
    if label:
        obj["typeMaterial"] = {"typeLabel": label, "typeDisplayText": "assembly from type material"}
    return json.dumps(obj)


def ncbi_package(root: Path, genomes=GENOMES) -> Path:
    data = root / "ncbi_dataset" / "data"
    catalog = {"apiVersion": "V2", "assemblies": [{"files": [{"filePath": "assembly_data_report.jsonl",
                                                               "fileType": "DATA_REPORT"}]}]}
    for acc, organism, *_ in genomes:
        rel = f"{acc}/{acc}_CONSTRUCTED_genomic.fna"
        _write(data, rel, f">NZ_CONSTRUCTED.1 {organism} chromosome, complete genome (CONSTRUCTED)\nACGTACGT\n")
        catalog["assemblies"].append({"accession": acc, "files": [{"filePath": rel,
                                                                    "fileType": "GENOMIC_NUCLEOTIDE_FASTA"}]})
    _write(data, "assembly_data_report.jsonl", "\n".join(_report_line(*g) for g in genomes) + "\n")
    _write(data, "dataset_catalog.json", json.dumps(catalog))
    _write(root, "README.md", "# NCBI Datasets\n\nCONSTRUCTED copy of the README's layout.\n")
    listed = [p for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ("README.md", "md5sum.txt")]
    _write(root, "md5sum.txt", "".join(f"{hashlib.md5(p.read_bytes()).hexdigest()}  "
                                       f"{p.relative_to(root).as_posix()}\n" for p in listed))
    return root


def package_zip(package: Path, zip_path: Path, extra: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(package.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(package).as_posix())
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return zip_path


def tree_state(root: Path) -> dict:
    """Every file and folder under root with its size, modification time and mode, to show nothing changed."""
    out = {}
    for p in sorted([root, *root.rglob("*")]):
        st = p.lstat()
        out[p.relative_to(root).as_posix()] = (st.st_size if p.is_file() else None, st.st_mtime_ns, st.st_mode)
    return out
