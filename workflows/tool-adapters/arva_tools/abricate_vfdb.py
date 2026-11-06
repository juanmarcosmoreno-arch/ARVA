"""VFDB's nucleotide FASTA (set A or set B) converted to an ABRicate database, as ABRicate 1.4.0's abricate-get_db
builds its `vfdb` database (bin/abricate-get_db: get_vfdb, load_fasta, is_full_gene, dedupe_seq, save_fasta, read on
the installed ABRicate 1.4.0 and its BioPerl, Bio/SeqIO/fasta.pm and Bio/PrimarySeq.pm):

1. Read the FASTA as BioPerl does: a record is the text up to the next "\\n>"; the ID is the first run of non-space
   characters of the header, the description the rest after the spaces that follow; whitespace is removed from the
   sequence. The sequence is upper-cased; a DNA one (BioPerl's guess: no E F I J L O P Q X Z and more than 70 % of
   A C G T U N W S K M, and no U) has every letter other than A G T C replaced by N, any other one has every
   character other than A-Z replaced by X. A repeated ID gets "_dupe".
2. get_vfdb: on the ID `^(\\w+)\\(\\w+\\|(\\w+)(\\.\\d+)?\\)$`, the accession (without its version) is the second group;
   on the description `^\\((.*?)\\)`, the gene is the text in the first parentheses. Perl keeps the groups of the last
   successful match, so a description without parentheses gives the VFG identifier as the gene when the ID matched,
   and the ID unchanged otherwise; an empty or "0" capture changes nothing (Perl's truth).
3. is_full_gene: a sequence whose length is a multiple of 3, of A C G T only, with a stop codon before its last codon
   is replaced by its reverse complement when that has none.
4. dedupe_seq: of identical sequences only the first is kept; then the records are sorted by gene (Perl's stable
   string sort).
5. save_fasta: `>vfdb~~~<gene>~~~<accession>~~~ <description>`, 60 letters per line (the description is the gene
   when empty).

One deliberate difference: VFDB set B has gene names with spaces ("clp G", "luk S-R"); abricate-get_db writes them
into the header's first word, so BLAST's identifier stops at the space and ABRicate then reports a cut gene ("clp")
and no accession. ARVA writes those spaces as "_" in the identifier only (the description keeps VFDB's text), and
reports how many it changed.

The files are read as bytes (VFDB's headers hold a few Latin-1 bytes, e.g. 0xA0) and written back byte for byte.
"""
from __future__ import annotations

import gzip
import hashlib
import re
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

# What abricate-get_db writes as the first part of every identifier (the --db name) for VFDB.
PREFIX = "vfdb"
WIDTH = 60
SETS = {"A": "VFDB_setA_nt.fas", "B": "VFDB_setB_nt.fas"}
_ID = re.compile(r"^(\w+)\(\w+\|(\w+)(\.\d+)?\)$", re.ASCII)
_GENE = re.compile(r"^\((.*?)\)", re.ASCII)
_TOP = re.compile(r"^\s*(\S+)\s*(.*)", re.ASCII)
_PROTEIN = re.compile(r"[EFIJLOPQXZ]", re.I)
_NUCLEIC = frozenset("ATUGCNWSKMatugcnwskm")
_NOT_DNA = re.compile(r"[^AGTC]")
_NOT_LETTER = re.compile(r"[^A-Z]")
_STOPS = frozenset({"TAA", "TAG", "TGA"})
_COMPLEMENT = str.maketrans("ACGT", "TGCA")
_SPACE = re.compile(r"\s", re.ASCII)
# The most decompressed FASTA read into memory (VFDB set B: about 55 MB in 2026); a larger file, or a gzip file that
# inflates past it, is refused instead of filling the worker's memory.
MAX_FASTA_BYTES = 512 << 20


@dataclass
class Record:
    id: str
    acc: str
    desc: str
    seq: str
    dna: bool


@dataclass
class Conversion:
    """What a conversion read and wrote (the log and the database's provenance file record it)."""
    records_read: int = 0
    records_written: int = 0
    duplicates_dropped: int = 0
    reverse_complemented: int = 0
    without_accession: int = 0
    spaces_replaced: list[str] = field(default_factory=list)
    duplicate_ids: int = 0
    genes: int = 0
    not_dna: int = 0
    sha256_fasta: str = ""
    fasta_bytes: int = 0
    sha256_sequences: str = ""
    sequences_bytes: int = 0

    def as_dict(self) -> dict:
        return {"records_read": self.records_read, "records_written": self.records_written,
                "duplicates_dropped": self.duplicates_dropped, "reverse_complemented": self.reverse_complemented,
                "without_accession": self.without_accession, "genes": self.genes,
                "gene_spaces_replaced": len(self.spaces_replaced), "gene_spaces_examples": self.spaces_replaced[:20],
                "duplicate_ids": self.duplicate_ids, "not_dna": self.not_dna,
                "fasta_sha256": self.sha256_fasta, "fasta_bytes": self.fasta_bytes,
                "sequences_sha256": self.sha256_sequences, "sequences_bytes": self.sequences_bytes}


def _bioperl_dna(seq: str) -> bool:
    """Bio::PrimarySeq::_guess_alphabet_from_string: True for 'dna' (load_fasta's nucl), False for rna or protein. An
    empty sequence is 'dna' (Bio::SeqIO::fasta's default)."""
    s = re.sub(r"[-.?]", "", seq)
    if not s:
        return True
    if _PROTEIN.search(s):
        return False
    if sum(c in _NUCLEIC for c in s) / len(s) > 0.7:
        return "U" not in s.upper()
    return False


def read_fasta(fh: BinaryIO) -> Iterator[tuple[str, str, str]]:
    """(ID, description, sequence) of each record as Bio::SeqIO::fasta's next_seq reads it, as Latin-1 text."""
    data = fh.read(MAX_FASTA_BYTES + 1)
    if len(data) > MAX_FASTA_BYTES:
        raise ValueError(f"the FASTA is larger than {MAX_FASTA_BYTES:,} bytes, far more than any VFDB file")
    text = data.decode("latin-1")
    if not text.strip():
        return
    if not text.startswith(">"):
        raise ValueError("the file is not FASTA (its first line is not a '>' header)")
    for n, entry in enumerate(text.split("\n>")):
        entry = entry[1:] if n == 0 else entry
        entry = entry[:-1] if entry.endswith("\n") else entry
        entry = entry[:-1] if entry.endswith("\r") else entry
        top, _, sequence = entry.partition("\n")
        top = top[:-1] if top.endswith("\r") else top  # BioPerl splits the header off at \r?\n
        m = _TOP.match(top)
        rid, desc = (m.group(1), m.group(2)) if m else (None, "")
        if rid == "":
            rid = desc
        sequence = sequence.replace(">", "")
        sequence = re.sub(r"[ \t\n\r]", "", sequence)
        if not rid:
            raise ValueError(f"record {n + 1} has an empty ID")
        yield rid, desc, sequence


def _perl_true(s: str | None) -> bool:
    return s is not None and s not in ("", "0")


def load(fh: BinaryIO, conv: Conversion) -> list[Record]:
    """load_fasta and get_vfdb of abricate-get_db."""
    seen: set[str] = set()
    out: list[Record] = []
    for rid, desc, seq in read_fasta(fh):
        if rid in seen:
            conv.duplicate_ids += 1
            rid = rid + "_dupe"
        seen.add(rid)
        dna = _bioperl_dna(seq)
        s = seq.upper()
        s = _NOT_DNA.sub("N", s) if dna else _NOT_LETTER.sub("X", s)
        if not dna:
            conv.not_dna += 1
        r = Record(id=rid, acc="", desc=desc, seq=s, dna=dna)
        g1 = g2 = None
        if m := _ID.match(r.id):
            g1, g2 = m.group(1), m.group(2)
        if _perl_true(g2):
            r.acc = g2
        if m := _GENE.match(r.desc):
            g1 = m.group(1)
        if _perl_true(g1):
            r.id = g1
        out.append(r)
    conv.records_read = len(out)
    return out


def _revcom(seq: str) -> str:
    return seq.translate(_COMPLEMENT)[::-1]


def _internal_stop(seq: str) -> bool:
    """Whether the translation (codon table 1, frame 0) has a stop codon followed by another residue."""
    return any(seq[i:i + 3] in _STOPS for i in range(0, len(seq) - 3, 3))


def is_full_gene(r: Record) -> bool:
    """is_full_gene: True when the record was replaced by its reverse complement."""
    if len(r.seq) % 3 != 0 or not re.fullmatch(r"[AGCT]+", r.seq):
        return False
    if _internal_stop(r.seq):
        rc = _revcom(r.seq)
        if not _internal_stop(rc):
            r.seq = rc
            return True
    return False


def header(r: Record) -> str:
    gene = _SPACE.sub("_", r.id)
    desc = r.desc if _perl_true(r.desc) else r.id
    top = "~~~".join((PREFIX, gene, r.acc, ""))
    desc = desc.replace("\n", "")
    return f">{top} {desc}" if _perl_true(desc) else f">{top}"


def convert(source: BinaryIO, out: BinaryIO, conv: Conversion | None = None) -> Conversion:
    """Convert a VFDB nucleotide FASTA (already decompressed) into ABRicate's `sequences` file."""
    conv = conv or Conversion()
    records = load(source, conv)
    for r in records:
        if is_full_gene(r):
            conv.reverse_complemented += 1
    seen: set[str] = set()
    kept: list[Record] = []
    for r in records:
        if r.seq in seen:
            conv.duplicates_dropped += 1
            continue
        seen.add(r.seq)
        kept.append(r)
    kept.sort(key=lambda r: r.id)
    digest = hashlib.sha256()
    size = 0
    spaced: list[str] = []
    for r in kept:
        if _SPACE.search(r.id):
            spaced.append(r.id)
        if not r.acc:
            conv.without_accession += 1
        lines = [r.seq[i:i + WIDTH] for i in range(0, len(r.seq), WIDTH)]
        block = (header(r) + "\n" + ("\n".join(lines) + "\n" if r.seq else "\n")).encode("latin-1")
        out.write(block)
        digest.update(block)
        size += len(block)
    conv.records_written = len(kept)
    conv.genes = len({r.id for r in kept})
    conv.spaces_replaced = sorted(set(spaced))
    conv.sha256_sequences, conv.sequences_bytes = digest.hexdigest(), size
    return conv


class _Hashing:
    """A binary reader that hashes what is read through it."""

    def __init__(self, fh: BinaryIO):
        self.fh, self.digest, self.size = fh, hashlib.sha256(), 0

    def read(self, n: int = -1) -> bytes:
        b = self.fh.read(n)
        self.digest.update(b)
        self.size += len(b)
        return b


def convert_file(source: Path, sequences: Path) -> Conversion:
    """Convert a VFDB nucleotide FASTA, plain or gzip-compressed, into `sequences`; records the SHA-256 and size of
    the decompressed FASTA too (a .gz file's own checksum changes whenever VFDB rebuilds it, even with the same
    content, because gzip stores the time)."""
    conv = Conversion()
    with open(source, "rb") as raw:
        compressed = raw.read(2) == b"\x1f\x8b"
    opener = gzip.open if compressed else open
    with opener(source, "rb") as fh, open(sequences, "wb") as out:
        hashing = _Hashing(fh)
        convert(hashing, out, conv)
    conv.sha256_fasta, conv.fasta_bytes = hashing.digest.hexdigest(), hashing.size
    return conv


def gzip_header(path: Path) -> dict | None:
    """The name and modification time gzip stored in a .gz file's header (RFC 1952), or None when it is not gzip.
    VFDB's files keep the name of the FASTA and the time VFDB rebuilt it (the same as the server's Last-Modified)."""
    with open(path, "rb") as fh:
        head = fh.read(10)
        if len(head) < 10 or head[:2] != b"\x1f\x8b":
            return None
        flags, mtime = head[3], struct.unpack("<I", head[4:8])[0]
        name = None
        if flags & 0x04:
            (xlen,) = struct.unpack("<H", fh.read(2))
            fh.read(xlen)
        if flags & 0x08:
            raw = b""
            while (c := fh.read(1)) not in (b"", b"\x00"):
                raw += c
                if len(raw) > 255:
                    break
            name = raw.decode("latin-1")
    return {"name": name, "mtime": datetime.fromtimestamp(mtime, UTC).isoformat() if mtime else None}


def makeblastdb_argv(makeblastdb: str, sequences: Path, log: Path) -> list[str]:
    """The index abricate-get_db builds (`makeblastdb -in <dir>/sequences -title vfdb -dbtype nucl -hash_index
    -logfile <log>`), as an argument list."""
    return [makeblastdb, "-in", str(sequences), "-title", PREFIX, "-dbtype", "nucl", "-hash_index", "-logfile",
            str(log)]


def sniff_set(path: Path) -> str | None:
    """Which VFDB set a file is by VFDB's own file name (VFDB_setB_nt.fas[.gz]), or by the name gzip stored in it;
    None when neither says."""
    for s, name in SETS.items():
        if path.name in (name, name + ".gz"):
            return s
    head = gzip_header(path) if path.is_file() else None
    for s, name in SETS.items():
        if head and head.get("name") == name:
            return s
    return None
