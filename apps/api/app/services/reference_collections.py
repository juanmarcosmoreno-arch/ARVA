"""Reference genome collections: genomes of known species for identification by average nucleotide identity (FastANI,
skani), for any genus. Three forms are recognised, and a fourth is offered as a copy:

- an extracted NCBI Datasets genome package: README.md, md5sum.txt (MD5 of every file), and ncbi_dataset/data/ with
  assembly_data_report.jsonl (one JSON object per genome: accession, organism, type material, RefSeq category),
  dataset_catalog.json (the files of each accession) and one <accession>/ folder with its *_genomic.fna;
- a FastANI reference list (--rl): a text file with one genome path per line. Paths written as on the host
  (/Volumes/...) are mapped to where ARVA sees them; a path outside the folders ARVA may read is refused;
- a folder of FASTA files (.fna, .fa, .fasta, .fas, also .gz);
- the package's zip: never registered or changed; ARVA can extract a copy (tasks/databases.py).

Layout and fields confirmed from NCBI's documentation of the genome data package and from a two-genome package
downloaded from the Datasets v2 API on 2026-10-29. NCBI's package files do not state the download date: the date
is declared by the user (ARVA suggests the zip entries' date, NCBI's packaging time without a time zone).

The collection's version is its source and date plus a fingerprint: the SHA-256 of its sorted accession list (file
names where a genome has no accession).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from app.services.database_detect import Detection, FileCheck, Problem, published_md5s, read_text

REPORT = "ncbi_dataset/data/assembly_data_report.jsonl"
CATALOG = "ncbi_dataset/data/dataset_catalog.json"
ACCESSION = re.compile(r"GC[AF]_\d{9}\.\d+")
FASTA = re.compile(r"\.(?:fna|fa|fasta|fas)(?:\.gz)?$", re.I)
MAX_GENOMES = 100_000
MAX_LINE = 4096
MAX_LIST_BYTES = 64 << 20
MAX_REPORT_BYTES = 512 << 20
MAX_ZIP_ENTRIES = 500_000
SPECIES_SHOWN = 500


@dataclass
class Genome:
    key: str
    path: str
    present: bool
    size: int | None = None
    accession: str | None = None
    organism: str | None = None
    species: str | None = None
    strain: str | None = None
    type_label: str | None = None
    type_text: str | None = None
    refseq_category: str | None = None
    # package (assembly_data_report.jsonl), fasta_header, or None
    metadata: str | None = None
    # As written in the list (host path), for messages.
    given: str | None = None


@dataclass(frozen=True)
class ListContext:
    """How a reference list's paths are read: from_host maps a host path to where ARVA sees it; allowed says whether
    a resolved path lies inside the folders ARVA may read."""
    from_host: Callable[[str], str]
    allowed: Callable[[Path], bool]


def species_of(organism: str | None) -> str | None:
    """Genus and species epithet of an organism name ("Staphylococcus aureus subsp. aureus NCTC 8325" → "Staphylococcus
    aureus"); None for "Genus sp." and names that are not binomials."""
    words = (organism or "").split()
    if len(words) < 2 or not words[1][:1].islower() or words[1] in ("sp.", "spp.", "bacterium", "cf.", "aff."):
        return None
    return f"{words[0]} {words[1]}"


def _meta(obj: dict) -> dict:
    org = obj.get("organism") if isinstance(obj.get("organism"), dict) else {}
    infra = org.get("infraspecificNames") if isinstance(org.get("infraspecificNames"), dict) else {}
    tm = obj.get("typeMaterial") if isinstance(obj.get("typeMaterial"), dict) else {}
    info = obj.get("assemblyInfo") if isinstance(obj.get("assemblyInfo"), dict) else {}
    name = str(org.get("organismName") or "")[:300] or None

    def s(v):
        return str(v)[:200] if v is not None else None

    return {"organism": name, "species": species_of(name), "strain": s(infra.get("strain")),
            "type_label": s(tm.get("typeLabel")), "type_text": s(tm.get("typeDisplayText")),
            "refseq_category": s(info.get("refseqCategory")), "tax_id": org.get("taxId")
            if isinstance(org.get("taxId"), int) else None}


def parse_report(lines) -> dict[str, dict]:
    out = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        acc = obj.get("accession") if isinstance(obj, dict) else None
        if isinstance(acc, str) and ACCESSION.fullmatch(acc):
            out[acc] = _meta(obj)
        if len(out) >= MAX_GENOMES:
            break
    return out


def is_package(path: Path) -> bool:
    return (path / REPORT).is_file()


def package_root(path: Path) -> Path | None:
    """The package's root folder, given it, its ncbi_dataset/ or its ncbi_dataset/data/ folder."""
    for cand in (path, path.parent, path.parent.parent):
        if is_package(cand) and (cand == path or path in (cand / "ncbi_dataset", cand / "ncbi_dataset" / "data")):
            return cand
    return None


def _report(root: Path) -> dict[str, dict]:
    p = root / REPORT
    if p.stat().st_size > MAX_REPORT_BYTES:
        return {}
    with open(p, encoding="utf-8", errors="replace") as fh:
        return parse_report(fh)


def _safe_rel(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and not rel.startswith("/") and ".." not in parts and "\x00" not in rel


def _catalog_files(text: str) -> dict[str, str]:
    """accession → its genomic FASTA's path (relative to ncbi_dataset/data/) from dataset_catalog.json."""
    try:
        cat = json.loads(text)
    except ValueError:
        return {}
    out = {}
    for a in cat.get("assemblies", []) if isinstance(cat, dict) else []:
        acc = a.get("accession") if isinstance(a, dict) else None
        if not isinstance(acc, str):
            continue
        for f in a.get("files", []):
            if isinstance(f, dict) and f.get("fileType") == "GENOMIC_NUCLEOTIDE_FASTA" and _safe_rel(str(f.get("filePath"))):
                out[acc] = str(f["filePath"])
    return out


def _stat(p: Path) -> tuple[bool, int | None]:
    try:
        st = p.stat()
    except OSError:
        return False, None
    return stat.S_ISREG(st.st_mode) and os.access(p, os.R_OK), st.st_size


def package_genomes(root: Path) -> list[Genome]:
    data = root / "ncbi_dataset" / "data"
    report = _report(root)
    catalog = _catalog_files(read_text(root / CATALOG, MAX_REPORT_BYTES)) if (root / CATALOG).is_file() else {}
    genomes = []
    for acc in sorted(set(report) | set(catalog)):
        rel = catalog.get(acc)
        if rel is None:
            folder = data / acc
            hits = sorted(folder.glob("*_genomic.fna")) if folder.is_dir() else []
            rel = f"{acc}/{hits[0].name}" if hits else f"{acc}/"
        p = data / rel
        present, size = _stat(p)
        genomes.append(Genome(acc, str(p), present, size, acc, metadata="package" if acc in report else None,
                              **{k: v for k, v in report.get(acc, {}).items() if k != "tax_id"}))
    return genomes


def _first_header(p: Path) -> str | None:
    import gzip

    try:
        opener = gzip.open if p.name.lower().endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
            line = fh.readline(2000)
    except (OSError, EOFError):
        return None
    return line[1:].strip() if line.startswith(">") else None


def _from_header(g: Genome, p: Path) -> None:
    header = _first_header(p)
    if header:
        words = header.split()[1:]
        g.organism = " ".join(words[:6])[:300] or None
        g.species = species_of(g.organism)
        g.metadata = "fasta_header" if g.species else None


def _accession(name: str) -> str | None:
    m = ACCESSION.search(name)
    return m.group(0) if m else None


def fasta_folder_genomes(root: Path) -> list[Genome]:
    """The FASTA files directly in the folder (not in its subfolders, which may be databases of other kinds)."""
    try:
        names = sorted(e.name for e in os.scandir(root) if FASTA.search(e.name) and not e.name.startswith("."))
    except OSError:
        return []
    paths = [root / n for n in names[:MAX_GENOMES]]
    genomes = []
    for p in paths:
        present, size = _stat(p)
        g = Genome(str(p.relative_to(root)), str(p), present, size, _accession(p.name))
        _from_header(g, p)
        genomes.append(g)
    return genomes


def fingerprint(genomes: list[Genome]) -> str:
    keys = sorted(g.accession or PurePosixPath(g.path).name for g in genomes)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def summary(genomes: list[Genome]) -> dict:
    present = [g for g in genomes if g.present]
    by_species = Counter(g.species or "unclassified" for g in genomes)
    labels = Counter(g.type_label for g in genomes if g.type_label)
    texts = {g.type_label: g.type_text for g in genomes if g.type_label}
    return {
        "genomes": len(genomes), "present": len(present), "missing": len(genomes) - len(present),
        "bytes": sum(g.size or 0 for g in present),
        "species": len([s for s in by_species if s != "unclassified"]),
        "unclassified": by_species.get("unclassified", 0),
        "by_species": [{"species": s, "genomes": n} for s, n in
                       sorted(by_species.items(), key=lambda x: (-x[1], x[0]))[:SPECIES_SHOWN]],
        "type_material": [{"label": lb, "text": texts.get(lb), "genomes": n} for lb, n in sorted(labels.items())],
        "reference_genomes": sum(1 for g in genomes if g.refseq_category == "reference genome"),
        "with_metadata": dict(Counter(g.metadata or "none" for g in genomes)),
        "accessions": sum(1 for g in genomes if g.accession),
        "fingerprint": fingerprint(genomes),
    }


def _zip_date(zip_path: Path) -> str | None:
    try:
        with zipfile.ZipFile(zip_path) as z:
            if REPORT not in z.namelist():
                return None
            dt = max(i.date_time for i in z.infolist())
    except (OSError, zipfile.BadZipFile, ValueError):
        return None
    return date(*dt[:3]).isoformat()


def _sibling_zip(root: Path) -> tuple[str, str] | None:
    """A zip next to the extracted package that holds an NCBI package (its name and entries' date)."""
    try:
        zips = sorted(e.name for e in os.scandir(root) if e.name.lower().endswith(".zip") and e.is_file())[:5]
    except OSError:
        return None
    for name in zips:
        if day := _zip_date(root / name):
            return name, day
    return None


def _collection(path: Path, path_type: str, variant: str, genomes: list[Genome]) -> Detection:
    d = Detection("reference_genomes", str(path), path_type, variant=variant)
    d.facts["collection"] = summary(genomes)
    d.facts["genomes"] = [asdict(g) for g in genomes]
    if not genomes:
        d.problems.append(Problem("no_genomes", {}))
    missing = [g for g in genomes if not g.present]
    if missing:
        d.problems.append(Problem("genomes_missing", {"count": len(missing), "names": ", ".join(
            (g.given or g.key) for g in missing[:5])}))
    return d


def detect_folder(path: Path, fasta_folder: bool = True) -> Detection | None:
    root = package_root(path)
    if root is not None:
        d = _collection(path, "folder", "ncbi_package", package_genomes(root))
        d.files += [FileCheck(REPORT, "kind", True, (root / REPORT).stat().st_size)]
        for name, role in ((CATALOG, "optional"), ("md5sum.txt", "optional"), ("README.md", "optional")):
            present, size = _stat(root / name)
            if present:
                d.files.append(FileCheck(name, role, True, size))
        if root != path:
            d.facts["package_root"] = str(root)
        d.facts["published_md5"] = "md5sum.txt" if (root / "md5sum.txt").is_file() else None
        if z := _sibling_zip(root):
            d.facts["zip"] = {"name": z[0], "date": z[1]}
            d.suggested_version, d.suggested_from = z[1], "zip_entries"
        return d
    genomes = fasta_folder_genomes(path) if fasta_folder else []
    if not genomes:
        return None
    return _collection(path, "folder", "fasta_folder", genomes)


def _package_of(p: Path, cache: dict[Path, Path | None]) -> Path | None:
    for parent in list(p.parents)[:5]:
        if parent in cache:
            return cache[parent]
        if is_package(parent):
            cache[parent] = parent
            return parent
    return None


def detect_list(path: Path, ctx: ListContext) -> Detection | None:
    """A FastANI --rl list: one genome path per line (blank lines are skipped)."""
    try:
        if path.stat().st_size > MAX_LIST_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    lines = [ln.strip() for ln in raw.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    if not lines or sum(1 for ln in lines if FASTA.search(ln) or "/" in ln) < 0.8 * len(lines):
        return None
    genomes: list[Genome] = []
    outside, relative, too_long = [], 0, 0
    packages: dict[Path, Path | None] = {}
    reports: dict[Path, dict[str, dict]] = {}
    for line in lines[:MAX_GENOMES]:
        if len(line) > MAX_LINE:
            too_long += 1
            continue
        if os.path.isabs(line):
            mapped = Path(ctx.from_host(line))
        else:
            relative += 1
            mapped = path.parent / line
        real = Path(os.path.realpath(mapped))
        if not ctx.allowed(real):
            outside.append(line)
            continue
        present, size = _stat(real)
        g = Genome(_accession(real.name) or real.name, str(real), present, size, _accession(real.name), given=line)
        if present and (pkg := _package_of(real, packages)) is not None:
            if pkg not in reports:
                reports[pkg] = _report(pkg)
            meta = reports[pkg].get(g.accession or "")
            if meta:
                g.metadata = "package"
                for k, v in meta.items():
                    if k != "tax_id":
                        setattr(g, k, v)
        elif present:
            _from_header(g, real)
        genomes.append(g)
    d = _collection(path, "file", "fastani_list", genomes)
    d.files.append(FileCheck(path.name, "kind", True, len(raw)))
    d.facts["lines"] = len(lines)
    d.facts["packages"] = sorted(str(p) for p in reports)
    if outside:
        d.problems.append(Problem("genomes_outside", {"count": len(outside), "names": ", ".join(outside[:5])}))
    if relative:
        d.problems.append(Problem("genomes_relative", {"count": relative}, blocking=False))
    if too_long:
        d.problems.append(Problem("lines_too_long", {"count": too_long, "limit": MAX_LINE}))
    if len(lines) > MAX_GENOMES:
        d.problems.append(Problem("too_many", {"limit": MAX_GENOMES}, blocking=False))
    for pkg in reports:
        if z := _sibling_zip(pkg):
            d.facts["zip"] = {"name": z[0], "date": z[1]}
            d.suggested_version, d.suggested_from = z[1], "zip_entries"
            break
    return d


# --- The package's zip ------------------------------------------------------------------------------------------

def zip_member_problem(info: zipfile.ZipInfo) -> str | None:
    """Why ARVA would not extract this zip entry, or None."""
    name = info.filename
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return "absolute or invalid name"
    if ".." in PurePosixPath(name).parts:
        return "contains '..'"
    mode = info.external_attr >> 16
    if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        return "link or special file"
    if info.flag_bits & 0x1:
        return "encrypted"
    return None


def detect_zip(path: Path) -> Detection | None:
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return None
    with z:
        infos = z.infolist()
        names = {i.filename for i in infos}
        if REPORT not in names or len(infos) > MAX_ZIP_ENTRIES:
            return None
        report_info = z.getinfo(REPORT)
        if report_info.file_size > MAX_REPORT_BYTES:
            return None
        with z.open(report_info) as fh:
            report = parse_report(line.decode("utf-8", errors="replace") for line in fh)
        catalog = _catalog_files(z.read(CATALOG).decode("utf-8", errors="replace")) if CATALOG in names else {}
        unsafe = next(((i.filename, p) for i in infos if (p := zip_member_problem(i))), None)
        md5_listed = published_md5s_text(z.read("md5sum.txt").decode("utf-8", errors="replace")) \
            if "md5sum.txt" in names else {}
        genomes = []
        for acc in sorted(set(report) | set(catalog)):
            rel = f"ncbi_dataset/data/{catalog[acc]}" if acc in catalog else None
            info = z.getinfo(rel) if rel and rel in names else None
            genomes.append(Genome(acc, rel or acc, info is not None, info.file_size if info else None, acc,
                                  metadata="package", **{k: v for k, v in report.get(acc, {}).items() if k != "tax_id"}))
        d = _collection(path, "zip", "ncbi_package_zip", genomes)
        d.facts["zip"] = {
            "name": path.name, "entries": len(infos), "compressed_bytes": sum(i.compress_size for i in infos),
            "uncompressed_bytes": sum(i.file_size for i in infos),
            "date": date(*max(i.date_time for i in infos)[:3]).isoformat(),
            "md5_listed": len(md5_listed),
        }
        d.suggested_version, d.suggested_from = d.facts["zip"]["date"], "zip_entries"
        d.files.append(FileCheck(path.name, "kind", True, path.stat().st_size))
        d.problems.insert(0, Problem("zip_package", {}))
        if unsafe:
            d.problems.append(Problem("zip_unsafe", {"name": unsafe[0][:200], "reason": unsafe[1]}))
        return d


def published_md5s_text(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{32}", parts[0]):
            out[parts[1].lstrip("*").strip()] = parts[0]
    return out


def package_md5s(root: Path) -> dict[str, str]:
    return published_md5s(root / "md5sum.txt") if (root / "md5sum.txt").is_file() else {}


def version_string(variant: str, day: str | None, fp: str) -> str:
    source = {"ncbi_package": "NCBI Datasets", "ncbi_package_zip": "NCBI Datasets", "fastani_list": "FastANI list",
              "fasta_folder": "FASTA folder"}.get(variant, "Collection")
    return f"{source} {day} #{fp[:12]}" if day else f"{source} #{fp[:12]}"


def valid_date(text: str | None) -> str | None:
    try:
        return date.fromisoformat(text).isoformat() if text and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None
    except ValueError:
        return None
