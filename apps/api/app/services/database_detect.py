"""Recognise a database folder or file, read its version from its own files and check it quickly (database_kinds.py
says what each kind needs and where the facts come from).

Detection only reads: it opens the kind's marker and version files (at most 1 MiB of each) and looks up the sizes of
the files the kind requires. Nothing is ever written into a registered folder. Every path a detector returns is
relative to the folder it was given, except for the genomes of a reference collection, which may lie anywhere inside
the folders ARVA may read (reference_collections.py).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.messages import render
from app.services.database_catalogue import (
    BAKTA_REQUIRED_FILES,
    BAKTA_SCHEMA_MAJOR,
    BAKTA_TYPE_FILE,
)

READ_LIMIT = 1 << 20
_MAX_NESTED = 50

# The English texts of the problems detection reports; the interface has them as databases.problem.<code>.
PROBLEMS = {
    "missing_files": "{count, plural, one {# required file is} other {# required files are}} missing: {names}",
    "version_unreadable": "{file} could not be read as {kind} expects: {detail}",
    "schema_unchecked": "This is Bakta database schema {major}; ARVA knows the required files of schema "
                        f"{BAKTA_SCHEMA_MAJOR} only, so they were not checked",
    "not_indexed": "{file} is missing: the tool has not built its indexes here yet ({how})",
    "unfinished": "{file} is missing: {tool}'s set-up did not finish in this folder",
    "nested": "This folder holds no database itself, but {names} {count, plural, one {looks like one} other "
              "{look like databases}}: choose {count, plural, one {it} other {one of them}}",
    "compressed": "{file} is compressed; register the decompressed file",
    "no_genomes": "No genome was found",
    "genomes_missing": "{count, plural, one {# genome file is} other {# genome files are}} missing: {names}",
    "genomes_outside": "{count, plural, one {# path lies} other {# paths lie}} outside the folders ARVA may read: "
                       "{names}. Add the folder with scripts/start.sh --add-databases and start ARVA again",
    "genomes_relative": "{count, plural, one {# path is} other {# paths are}} relative; ARVA read "
                        "{count, plural, one {it} other {them}} from the list's folder, while FastANI reads them "
                        "from the folder it runs in",
    "zip_package": "This is a zip archive: FastANI cannot read genomes inside it. ARVA can extract a copy into a "
                   "database folder; the zip is left as it is",
    "zip_unsafe": "The zip archive has an entry ARVA does not extract: {name} ({reason})",
    "lines_too_long": "{count, plural, one {# line is} other {# lines are}} longer than {limit} characters",
    "too_many": "More than {limit} genomes: only the first {limit} were read",
    "not_text": "{file} is not a text file with one genome path per line",
    "spa_format": "{file} does not look like the SpaServer's file: {detail}",
}


@dataclass
class Problem:
    code: str
    params: dict[str, str | int]
    blocking: bool = True

    @property
    def text(self) -> str:
        return render(PROBLEMS[self.code], self.params)


@dataclass
class FileCheck:
    path: str
    # kind (identifies the kind), version (the version was read from it), required, optional
    role: str
    present: bool
    size: int | None = None


@dataclass
class Detection:
    kind: str
    path: str
    path_type: str  # folder | file | zip
    variant: str | None = None
    version: str | None = None
    version_file: str | None = None
    version_detail: str | None = None
    suggested_version: str | None = None
    # folder_name, file_name, zip_entries, checksum
    suggested_from: str | None = None
    catalogue_key: str | None = None
    # The version can be identified from a published checksum by the full verification (CheckM2).
    version_by_checksum: bool = False
    files: list[FileCheck] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(p.blocking for p in self.problems)

    @property
    def needs_declared_version(self) -> bool:
        return self.version is None and not self.version_by_checksum

    def require(self, root: Path, *names: str, role: str = "required") -> list[str]:
        missing = []
        for name in names:
            check = _check(root, name, role)
            self.files.append(check)
            if not check.present:
                missing.append(name)
        if missing and role == "required":
            self.problems.append(Problem("missing_files", {"count": len(missing), "names": ", ".join(missing[:8])}))
        return missing

    def as_dict(self) -> dict:
        out = asdict(self)
        out["problems"] = [{"code": p.code, "params": p.params, "blocking": p.blocking, "text": p.text}
                           for p in self.problems]
        out["ok"] = self.ok
        out["needs_declared_version"] = self.needs_declared_version
        return out


def _check(root: Path, rel: str, role: str) -> FileCheck:
    p = root / rel
    try:
        st = p.stat()
    except OSError:
        return FileCheck(rel, role, False)
    readable = os.access(p, os.R_OK)
    return FileCheck(rel, role, readable, st.st_size if p.is_file() else None)


def read_text(path: Path, limit: int = READ_LIMIT) -> str:
    with open(path, "rb") as fh:
        return fh.read(limit).decode("utf-8", errors="replace")


def _exists(root: Path, *names: str) -> bool:
    return all((root / n).exists() for n in names)


# --- One detector per kind --------------------------------------------------------------------------------------

def _bakta(root: Path) -> Detection | None:
    if not (root / "version.json").is_file():
        return None
    d = Detection("bakta", str(root), "folder")
    try:
        info = json.loads(read_text(root / "version.json"))
    except ValueError as exc:
        d.problems.append(Problem("version_unreadable", {"file": "version.json", "kind": "Bakta", "detail": str(exc)}))
        return d
    if not isinstance(info, dict) or not {"date", "major", "minor", "type"} <= set(info) or not (
            isinstance(info["major"], int) and isinstance(info["minor"], int) and info["type"] in BAKTA_TYPE_FILE):
        if isinstance(info, dict) and "major" not in info and "type" not in info:
            return None
        d.problems.append(Problem("version_unreadable", {"file": "version.json", "kind": "Bakta",
                                                         "detail": "it needs date, major, minor and type"}))
        return d
    d.files.append(_check(root, "version.json", "version"))
    d.variant = info["type"]
    d.version, d.version_file, d.version_detail = f"{info['major']}.{info['minor']}", "version.json", "major.minor"
    d.catalogue_key = f"bakta-{info['type']}"
    d.facts = {"version_json": info}
    if info["major"] == BAKTA_SCHEMA_MAJOR:
        d.require(root, *BAKTA_REQUIRED_FILES, BAKTA_TYPE_FILE[info["type"]])
    else:
        d.problems.append(Problem("schema_unchecked", {"major": info["major"]}, blocking=False))
    return d


_AMR_VERSION = re.compile(r"\d{4}-\d{2}-\d{2}\.\d+")
_AMR_FILES = ("AMRProt.fa", "AMR.LIB", "AMR_CDS.fa", "fam.tsv", "taxgroup.tsv", "AMRProt-mutation.tsv",
              "AMRProt-susceptible.tsv", "AMRProt-suppress.tsv")


def _amrfinderplus(root: Path) -> Detection | None:
    if not _exists(root, "version.txt", "database_format_version.txt", "AMRProt.fa"):
        return None
    d = Detection("amrfinderplus", str(root), "folder")
    version = read_text(root / "version.txt", 200).strip()
    fmt = read_text(root / "database_format_version.txt", 200).strip()
    d.files += [_check(root, "version.txt", "version"), _check(root, "database_format_version.txt", "version")]
    if not _AMR_VERSION.fullmatch(version):
        d.problems.append(Problem("version_unreadable", {"file": "version.txt", "kind": "AMRFinderPlus",
                                                         "detail": f"{version[:40]!r} is not YYYY-MM-DD.N"}))
        return d
    d.version, d.version_file, d.version_detail = version, "version.txt", "data version"
    d.facts = {"database_format_version": fmt}
    d.require(root, *_AMR_FILES)
    if d.require(root, "AMRProt.fa.phr", role="optional"):
        d.problems.append(Problem("not_indexed", {"file": "AMRProt.fa.phr", "how": "amrfinder_update or "
                                                  "amrfinder_index builds it"}))
    return d


_GTDB_DIRS = ("msa", "masks", "pplacer", "skani", "radii", "mrca_red", "markers", "split")
_GTDB_RELEASE = re.compile(r"r\d+(?:_v\d+)?")


def _gtdbtk(root: Path) -> Detection | None:
    meta = root / "metadata" / "metadata.txt"
    if not meta.is_file():
        return None
    d = Detection("gtdbtk", str(root), "folder")
    lines = read_text(meta).splitlines()
    version = next((ln.split("=", 1)[1].strip() for ln in lines if ln.startswith("VERSION_DATA=")), None)
    d.files.append(_check(root, "metadata/metadata.txt", "version"))
    if not version or not _GTDB_RELEASE.fullmatch(version):
        d.problems.append(Problem("version_unreadable", {"file": "metadata/metadata.txt", "kind": "GTDB-Tk",
                                                         "detail": "no VERSION_DATA=rNNN line"}))
        return d
    d.version, d.version_file, d.version_detail = version, "metadata/metadata.txt", "VERSION_DATA"
    d.require(root, "taxonomy/gtdb_taxonomy.tsv")
    missing = [n for n in _GTDB_DIRS if not (root / n).is_dir()]
    d.files += [FileCheck(f"{n}/", "required", n not in missing) for n in _GTDB_DIRS]
    if missing:
        # GTDB-Tk 2.8.0's folders; releases read by older GTDB-Tk versions may lay them out differently.
        d.problems.append(Problem("missing_files", {"count": len(missing), "names": ", ".join(f"{n}/" for n in missing)},
                                  blocking=version == "r232"))
    return d


_RELEASE_IN_NAME = re.compile(r"(?:^|[^a-z0-9])r(\d{2,3})(?:[^0-9]|$)", re.I)


def _release_from_name(name: str) -> str | None:
    m = _RELEASE_IN_NAME.search(name)
    return f"GTDB r{m.group(1)}" if m else None


def _skani(root: Path) -> Detection | None:
    v2 = (root / "markers.bin2").is_file()
    if not v2 and not (root / "markers.bin").is_file():
        return None
    d = Detection("skani", str(root), "folder")
    d.files.append(_check(root, "markers.bin2" if v2 else "markers.bin", "kind"))
    if v2:
        consolidated = _exists(root, "sketches.db2", "index.db2")
        d.facts["format"] = "skani 0.4 (markers.bin2)"
    else:
        consolidated = _exists(root, "sketches.db", "index.db")
        d.facts["format"] = "before skani 0.4 (markers.bin)"
    names = ("sketches.db2", "index.db2") if v2 else ("sketches.db", "index.db")
    if consolidated:
        d.files += [_check(root, n, "required") for n in names]
    else:
        sketches = sum(1 for e in os.scandir(root) if e.name.endswith(".sketch"))
        d.facts["sketch_files"] = sketches
        if not sketches:
            d.problems.append(Problem("missing_files", {"count": 2, "names": " and ".join(names) + " (or .sketch files)"}))
    if (root / "README.txt").is_file():
        text = read_text(root / "README.txt", 64 * 1024)
        built_by = re.search(r"^Built by\s*:\s*skani\s+(\S+)", text, re.M)
        built_on = re.search(r"^Built on\s*:\s*(.+)$", text, re.M)
        d.facts |= {"built_by_skani": built_by.group(1) if built_by else None,
                    "built_on": built_on.group(1).strip()[:40] if built_on else None}
        d.files.append(_check(root, "README.txt", "optional"))
    d.suggested_version, d.suggested_from = _release_from_name(root.name), "folder_name"
    return d


_K2_MD5_ARCHIVE = re.compile(r"^[0-9a-f]{32}\s+\*?(k2_([a-z0-9]+(?:_[a-z0-9]+)*?)_(\d{8})\.tar\.gz)$", re.M)
_K2_NAME = re.compile(r"k2_([a-z0-9]+(?:_[a-z0-9]+)*?)_(\d{8})")
_MD5_LINE = re.compile(r"^([0-9a-f]{32})\s+\*?(\S.*)$")


def _date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def published_md5s(md5_file: Path) -> dict[str, str]:
    """A published MD5 list (md5sum format: hash, then the file's relative path); up to 64 MiB of it (an NCBI package
    of 100,000 genomes lists about 10 MB)."""
    out = {}
    for line in read_text(md5_file, 64 << 20).splitlines():
        if m := _MD5_LINE.match(line.strip()):
            out[m.group(2).strip()] = m.group(1)
    return out


def _kraken2(root: Path) -> Detection | None:
    if not (root / "hash.k2d").exists():
        return None
    d = Detection("kraken2", str(root), "folder")
    d.require(root, "hash.k2d", "opts.k2d", "taxo.k2d")
    for name in ("inspect.txt", "library_report.tsv", "ktaxonomy.tsv", "seqid2taxid.map", "names.dmp", "nodes.dmp"):
        if (root / name).exists():
            d.files.append(_check(root, name, "optional"))
    md5s = sorted(e.name for e in os.scandir(root) if e.name.endswith(".md5") and e.is_file())
    for name in md5s:
        m = _K2_MD5_ARCHIVE.search(read_text(root / name))
        d.files.append(_check(root, name, "version" if m else "optional"))
        if m and d.version is None:
            d.variant = m.group(2)
            d.version = f"{m.group(2)} {_date(m.group(3))}"
            d.version_file, d.version_detail = name, f"archive name {m.group(1)}"
            d.facts["published_md5"] = name
    if d.version is None and (m := _K2_NAME.search(root.name)):
        d.suggested_version, d.suggested_from = f"{m.group(1)} {_date(m.group(2))}", "folder_name"
    return d


CHECKM2_DMND = "uniref100.KO.1.dmnd"
# checkm2/version/version_hashes_1.1.0.json (CheckM2 1.1.0): SHA-256 of uniref100.KO.1.dmnd per database version.
CHECKM2_DMND_SHA256 = {
    "1b86ef3eac0813c1853f53182c17657045e3763d66f384ec95747261a63ae46f": "3",
    "aff3badcd2bd389539e833b5a0d446c13fb257d71abcb6c73fac38e8ab070acb": "1 or 2",
}


def _checkm2(root: Path) -> Detection | None:
    rel = next((r for r in (CHECKM2_DMND, f"CheckM2_database/{CHECKM2_DMND}") if (root / r).is_file()), None)
    if rel is None:
        return None
    d = Detection("checkm2", str(root), "folder")
    d.files.append(_check(root, rel, "required"))
    d.facts["dmnd"] = rel
    contents = root / "CONTENTS.json"
    if contents.is_file():
        try:
            info = json.loads(read_text(contents))
            version = str(info["version"]) if isinstance(info, dict) and "version" in info else None
        except ValueError:
            version = None
        if version and re.fullmatch(r"[0-9][0-9.]*", version):
            d.version, d.version_file, d.version_detail = version, "CONTENTS.json", "version"
            d.files.append(_check(root, "CONTENTS.json", "version"))
            d.facts["contents_md5"] = {k: v for k, v in info.items() if isinstance(v, str) and k.endswith(".dmnd")}
    if d.version is None:
        d.version_by_checksum = True
    return d


def _busco(root: Path) -> Detection | None:
    cfg = root / "dataset.cfg"
    if not cfg.is_file():
        return None
    values = dict(ln.split("=", 1) for ln in read_text(cfg, 64 * 1024).splitlines() if "=" in ln)
    name, created = values.get("name", "").strip(), (values.get("creation_date") or values.get("creation") or "").strip()
    d = Detection("busco", str(root), "folder")
    d.files.append(_check(root, "dataset.cfg", "version"))
    if not re.fullmatch(r"[a-z0-9_]+_odb\d+(?:\.\d+)?", name) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", created):
        d.problems.append(Problem("version_unreadable", {"file": "dataset.cfg", "kind": "BUSCO",
                                                         "detail": "no name=<lineage>_odbNN or creation date"}))
        return d
    d.variant = name
    d.version, d.version_file, d.version_detail = f"{name} ({created})", "dataset.cfg", "name, creation_date"
    d.facts = {k: values[k].strip()[:80] for k in ("domain", "number_of_BUSCOs", "number_of_species",
                                                   "OrthoDB_version", "dataset_version") if k in values}
    d.require(root, "scores_cutoff")
    hmms = root / "hmms"
    count = sum(1 for e in os.scandir(hmms) if e.name.endswith(".hmm")) if hmms.is_dir() else 0
    d.files.append(FileCheck("hmms/", "required", count > 0))
    d.facts["hmms"] = count
    if not count:
        d.problems.append(Problem("missing_files", {"count": 1, "names": "hmms/*.hmm"}))
    return d


def _plasmidfinder(root: Path) -> Detection | None:
    cfg = root / "config"
    if not cfg.is_file() or "Database configuration file" not in read_text(cfg, 4096):
        return None
    d = Detection("plasmidfinder", str(root), "folder")
    d.files.append(_check(root, "config", "kind"))
    prefixes = [ln.split("\t")[0].strip() for ln in read_text(cfg).splitlines()
                if ln.strip() and not ln.startswith("#") and re.fullmatch(r"[\w.-]+", ln.split("\t")[0].strip())]
    d.facts["databases"] = prefixes
    d.require(root, *(f"{p}.fsa" for p in prefixes))
    if (root / "VERSION").is_file():
        version = read_text(root / "VERSION", 200).strip()
        if re.fullmatch(r"[\w.-]{1,40}", version):
            d.version, d.version_file, d.version_detail = version, "VERSION", "VERSION"
            d.files.append(_check(root, "VERSION", "version"))
    return d


_MOB_FILES = ("ncbi_plasmid_full_seqs.fas", "rep.dna.fas", "mob.proteins.faa", "mpf.proteins.faa", "orit.fas",
              "repetitive.dna.fas", "clusters.txt")


def _mobsuite(root: Path) -> Detection | None:
    if not _exists(root, "ncbi_plasmid_full_seqs.fas", "clusters.txt"):
        return None
    d = Detection("mobsuite", str(root), "folder")
    d.require(root, *_MOB_FILES)
    for name, tool_step in (("status.txt", "mob_init"), ("ncbi_plasmid_full_seqs.fas.msh", "mob_init")):
        if not (root / name).is_file():
            d.problems.append(Problem("unfinished", {"file": name, "tool": tool_step}))
        else:
            d.files.append(_check(root, name, "optional"))
    if (root / "status.txt").is_file():
        m = re.search(r"Download date: (\d{4}-\d{2}-\d{2})", read_text(root / "status.txt", 1000))
        d.facts["download_date"] = m.group(1) if m else None
    return d


VFDB_FILES = ("VFDB_setA_pro.fas", "VFDB_setA_nt.fas", "VFDB_setB_pro.fas", "VFDB_setB_nt.fas")


def _vfdb(root: Path) -> Detection | None:
    found = [n + gz for n in VFDB_FILES for gz in ("", ".gz") if (root / (n + gz)).is_file()]
    if not found:
        return None
    d = Detection("vfdb", str(root), "folder")
    d.files += [_check(root, n, "required") for n in found]
    d.facts["sets"] = found
    return d


_GENOMAD_FILES = ("genomad_db", "genomad_mini_db", "genomad_integrase_db", "names.dmp", "nodes.dmp",
                  "genomad_marker_metadata.tsv")


def _genomad(root: Path) -> Detection | None:
    if not _exists(root, "version.txt", "genomad_marker_metadata.tsv"):
        return None
    d = Detection("genomad", str(root), "folder")
    version = read_text(root / "version.txt", 100).strip()
    d.files.append(_check(root, "version.txt", "version"))
    try:
        float(version)
    except ValueError:
        d.problems.append(Problem("version_unreadable", {"file": "version.txt", "kind": "geNomad",
                                                         "detail": f"{version[:20]!r} is not a number"}))
        return d
    d.version, d.version_file, d.version_detail = version, "version.txt", "version.txt"
    d.require(root, *_GENOMAD_FILES)
    return d


def _interproscan(root: Path) -> Detection | None:
    if not (root / "interproscan-5.jar").is_file():
        return None
    d = Detection("interproscan", str(root), "folder")
    d.files.append(_check(root, "interproscan-5.jar", "kind"))
    if not (root / "data").is_dir():
        d.problems.append(Problem("missing_files", {"count": 1, "names": "data/"}))
    for name in ("interproscan.sh", "interproscan.properties"):
        if (root / name).exists():
            d.files.append(_check(root, name, "optional"))
    if m := re.search(r"interproscan-(5\.\d+-\d+\.\d+)", root.name):
        d.suggested_version, d.suggested_from = m.group(1), "folder_name"
    return d


def _spa_types(root: Path) -> Detection | None:
    if not _exists(root, "sparepeats.fasta", "spatypes.txt"):
        return None
    d = Detection("spa_types", str(root), "folder")
    d.files += [_check(root, "sparepeats.fasta", "required"), _check(root, "spatypes.txt", "required")]
    repeats = read_text(root / "sparepeats.fasta")
    types = read_text(root / "spatypes.txt").splitlines()
    if not repeats.startswith(">"):
        d.problems.append(Problem("spa_format", {"file": "sparepeats.fasta", "detail": "it does not start with '>'"}))
    bad = [ln for ln in types if ln.strip() and ln.count(",") != 1]
    if bad or not types:
        d.problems.append(Problem("spa_format", {"file": "spatypes.txt", "detail": "lines are not type,repeats"}))
    d.facts = {"repeats": repeats.count("\n>") + int(repeats.startswith(">")), "types": sum(1 for ln in types if ln)}
    return d


def _sylph(path: Path) -> Detection | None:
    if path.suffix not in (".syldb", ".syl2db", ".sylqueries"):
        return None
    d = Detection("sylph", str(path), "file")
    d.files.append(FileCheck(path.name, "kind", os.access(path, os.R_OK), path.stat().st_size))
    d.facts["two_stage"] = path.suffix == ".syl2db"
    rel = _release_from_name(path.name)
    c = re.search(r"-c(\d+)", path.name)
    if rel:
        d.suggested_version = rel + (f", -c {c.group(1)}" if c else "")
        d.suggested_from = "file_name"
    return d


# The Mash data page: RefSeq release 70 sketches.
MASH_REFSEQ_70 = {"RefSeqSketches.msh": "RefSeq release 70 (k=16, s=400)",
                  "RefSeqSketchesDefaults.msh": "RefSeq release 70 (k=21, s=1000)"}


def _mash(path: Path) -> Detection | None:
    if not path.name.endswith((".msh", ".msh.gz")):
        return None
    d = Detection("mash", str(path), "file")
    d.files.append(FileCheck(path.name, "kind", os.access(path, os.R_OK), path.stat().st_size))
    if path.name.endswith(".gz"):
        d.problems.append(Problem("compressed", {"file": path.name}))
    name = path.name.removesuffix(".gz")
    if name in MASH_REFSEQ_70:
        d.suggested_version, d.suggested_from = MASH_REFSEQ_70[name], "file_name"
    return d


def _vfdb_file(path: Path) -> Detection | None:
    if path.name not in {n + gz for n in VFDB_FILES for gz in ("", ".gz")}:
        return None
    d = Detection("vfdb", str(path), "file")
    d.files.append(FileCheck(path.name, "required", os.access(path, os.R_OK), path.stat().st_size))
    d.facts["sets"] = [path.name]
    return d


def _mlst_schemes(root: Path) -> Detection | None:
    from arva_tools.mlst import database_info, database_version

    if not (root / "blast" / "mlst.fa.njs").is_file() or not (root / "pubmlst").is_dir():
        return None
    info = database_info(root)
    d = Detection("mlst_schemes", str(root), "folder")
    d.require(root, "blast/mlst.fa.njs", *info["blast_files"])
    d.require(root, *(f"pubmlst/{s['name']}/{s['name']}.txt" for s in info["schemes"]))
    d.version = database_version(info)
    if d.version:
        d.version_file, d.version_detail = "pubmlst/<scheme>/<scheme>_info.json", "download_date"
    d.facts = {"mlst": {k: v for k, v in info.items() if k != "schemes"}}
    return d


FOLDER_DETECTORS = (_bakta, _amrfinderplus, _gtdbtk, _skani, _kraken2, _checkm2, _busco, _plasmidfinder, _mobsuite,
                    _genomad, _interproscan, _spa_types, _vfdb, _mlst_schemes)
FILE_DETECTORS = (_sylph, _mash, _vfdb_file)


def detect(path: Path, ctx=None) -> list[Detection]:
    """Every kind the folder or file matches (usually one). `ctx` (reference_collections.ListContext) maps and
    checks the genome paths of a reference list; without it, a list is not read."""
    from app.services import reference_collections as rc

    if path.is_dir():
        found = [d for d in (det(path) for det in FOLDER_DETECTORS) if d is not None]
        # A folder of another kind may hold FASTA files too (Bakta's oric.fna): it is not a genome collection.
        if collection := rc.detect_folder(path, fasta_folder=not found):
            found.append(collection)
        if not found:
            nested = nested_candidates(path)
            if nested:
                d = Detection("unknown", str(path), "folder")
                d.problems.append(Problem("nested", {"count": len(nested), "names": ", ".join(n + "/" for n in nested)}))
                d.facts["nested"] = nested
                return [d]
        return found
    found = [d for d in (det(path) for det in FILE_DETECTORS) if d is not None]
    if found:
        return found
    if path.suffix.lower() == ".zip":
        z = rc.detect_zip(path)
        return [z] if z else []
    if ctx is not None and (lst := rc.detect_list(path, ctx)):
        return [lst]
    return []


def nested_candidates(path: Path) -> list[str]:
    """Subfolders that are databases themselves (e.g. db-light/ in the folder bakta_db download wrote into)."""
    from app.services import reference_collections as rc

    out = []
    try:
        entries = sorted((e for e in os.scandir(path) if e.is_dir()), key=lambda e: e.name)[:_MAX_NESTED]
    except OSError:
        return []
    for e in entries:
        sub = Path(e.path)
        if any(det(sub) for det in FOLDER_DETECTORS) or rc.is_package(sub):
            out.append(e.name)
    return out


def quick_check(record_kind: str, path: Path, recorded: dict, ctx=None) -> Detection | None:
    """Detection again, for a quick verification: the same kind must be found, with the same version if the version
    came from a file, and every file recorded at registration with the same size."""
    found = next((d for d in detect(path, ctx) if d.kind == record_kind), None)
    if found is None:
        return None
    sizes = {f["path"]: f.get("size") for f in recorded.get("files", []) if f.get("present")}
    changed = [f.path for f in found.files if f.path in sizes and f.present and sizes[f.path] is not None
               and f.size != sizes[f.path]]
    gone = [p for p in sizes if not any(f.path == p and f.present for f in found.files)]
    found.facts["quick"] = {"changed": changed, "missing": gone}
    return found
