"""VFDB's nucleotide FASTA converted to an ABRicate database (arva_tools.abricate_vfdb) and searched with --datadir and
--db pointing at it.

The made-up records below are CONSTRUCTED (random sequences under VFDB-style headers, not biology); they carry the
cases set B has and set A lacks: a record without "(gb|...)", a gene name with a space ("clp G"), a Latin-1 byte
(0xA0) in a description, an identical sequence under another identifier, a gene with internal stops that reads whole
on the other strand, and a description without the gene in parentheses. With ABRicate installed, ABRicate's own
abricate-get_db converts the same file (offline: the file is put where it would download it), and ARVA's output must
be byte-identical except for the gene name with a space; the database ARVA indexes is then searched with the real
abricate. With VFDB's real set B at ARVA_TEST_VFDB_SETB (default ~/.arva-testdata/vfdb/VFDB_setB_nt.fas.gz, downloaded
from https://www.mgc.ac.cn/VFs/Down/ on 2026-11-06) and S. aureus N315 (GCF_000009645.1) in ARVA_TEST_GENOMES, the
full conversion is checked against VFDB's counts and the egc enterotoxin cluster is found on N315.
"""
import gzip
import hashlib
import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from arva_tools import abricate as abr
from arva_tools import abricate_vfdb as conv
from arva_tools.base import help_options
from arva_tools.registry import detect
from arva_tools.runner import isolated_home, tool_environment

FIX = Path(__file__).parent / "fixtures"
SETB = Path(os.environ.get("ARVA_TEST_VFDB_SETB") or Path.home() / ".arva-testdata/vfdb/VFDB_setB_nt.fas.gz")
GENOMES = Path(os.environ.get("ARVA_TEST_GENOMES") or "/root/.arva-testdata/genomes")
STOPS = {"TAA", "TAG", "TGA"}


def _orf(rng: random.Random, codons: int, extra: str = "") -> str:
    """A random coding-like sequence without stop codons in frame 0, plus `extra` codons inside."""
    out = []
    while len(out) < codons:
        c = "".join(rng.choice("ACGT") for _ in range(3))
        if c not in STOPS:
            out.append(c)
    if extra:
        out.insert(codons // 2, extra)
    return "ATG" + "".join(out)


def _revcom(s: str) -> str:
    return s.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def made_up_setb() -> tuple[bytes, dict[str, str]]:
    """A CONSTRUCTED VFDB_setB_nt.fas and the sequences by name."""
    rng = random.Random(42)
    a, b, c, d = (_orf(rng, 150) for _ in range(4))
    # On this strand "TTA" reads as an internal stop of its reverse complement: the record is stored the other way
    # round, so abricate-get_db's is_full_gene turns it back.
    whole = _orf(rng, 120, extra="TTA")
    stored = _revcom(whole)
    plain = _orf(rng, 100)
    seqs = {"geneA": a, "selq": b, "clp G": c, "fnbA": d, "rcgene": whole, "VFG000007": plain}
    records = [
        b">VFG000001(gb|WP_000000001.1) (geneA) made-up toxin A [Made-up toxin (VF9001) - Exotoxin (VFC0235)] "
        b"[Madeup organism X]", a,
        b">VFG000002 (selq) made-up enterotoxin-like Q [SE (VF0020) - Exotoxin (VFC0235)] [Staphylococcus aureus]", b,
        b">VFG000003(gb|AAA00003) (clp G) made-up surface antigen [Made-up antigen (VF9003) - Adherence (VFC0001)] "
        b"[Escherichia coli]", c,
        b">VFG000004(gb|NP_000004.2) (fnbA) made-up protein\xa0with a Latin-1 space [FnBP (VF9004) - Adherence "
        b"(VFC0001)] [Staphylococcus aureus]", d.lower(),
        b">VFG000005(gb|WP_000000005) (geneA) the same sequence again [Made-up toxin (VF9001) - Exotoxin (VFC0235)] "
        b"[Madeup organism Y]", a,
        b">VFG000006(gb|WP_000000006) (rcgene) stored on the other strand [Made-up (VF9006) - Toxin (VFC0235)] "
        b"[Madeup organism Z]", stored,
        b">VFG000007(gb|ABC00007) a description without the gene in parentheses", plain,
    ]
    text = b""
    for i in range(0, len(records), 2):
        seq = records[i + 1].encode() if isinstance(records[i + 1], str) else records[i + 1]
        text += records[i] + b"\n" + b"\n".join(seq[j:j + 70] for j in range(0, len(seq), 70)) + b"\n"
    return text, seqs


def test_conversion_rewrites_headers_as_abricate_get_db(tmp_path):
    raw, seqs = made_up_setb()
    src = tmp_path / "VFDB_setB_nt.fas.gz"
    with open(src, "wb") as fh, gzip.GzipFile(filename="VFDB_setB_nt.fas", mode="wb", fileobj=fh,
                                              mtime=1793964607) as gz:
        gz.write(raw)
    assert conv.gzip_header(src) == {"name": "VFDB_setB_nt.fas", "mtime": "2026-11-06T11:30:07+00:00"}
    assert conv.sniff_set(src) == "B" and conv.sniff_set(FIX / "abricate" / "help_1.4.0.txt") is None
    out = tmp_path / "sequences"
    c = conv.convert_file(src, out)
    assert (c.records_read, c.records_written, c.duplicates_dropped, c.reverse_complemented) == (7, 6, 1, 1)
    assert c.without_accession == 1 and c.spaces_replaced == ["clp G"] and c.genes == 6
    assert c.sha256_fasta == hashlib.sha256(raw).hexdigest() and c.fasta_bytes == len(raw)
    data = out.read_bytes()
    assert c.sha256_sequences == hashlib.sha256(data).hexdigest() and c.sequences_bytes == len(data)
    headers = [ln for ln in data.split(b"\n") if ln.startswith(b">")]
    # Sorted by gene (Perl's string sort: upper case first); the accession loses its version; the first record of a
    # repeated sequence is kept; the description keeps VFDB's bytes (0xA0 included).
    assert headers == [
        b">vfdb~~~VFG000007~~~ABC00007~~~ a description without the gene in parentheses",
        b">vfdb~~~clp_G~~~AAA00003~~~ (clp G) made-up surface antigen [Made-up antigen (VF9003) - Adherence "
        b"(VFC0001)] [Escherichia coli]",
        b">vfdb~~~fnbA~~~NP_000004~~~ (fnbA) made-up protein\xa0with a Latin-1 space [FnBP (VF9004) - Adherence "
        b"(VFC0001)] [Staphylococcus aureus]",
        b">vfdb~~~geneA~~~WP_000000001~~~ (geneA) made-up toxin A [Made-up toxin (VF9001) - Exotoxin (VFC0235)] "
        b"[Madeup organism X]",
        b">vfdb~~~rcgene~~~WP_000000006~~~ (rcgene) stored on the other strand [Made-up (VF9006) - Toxin (VFC0235)] "
        b"[Madeup organism Z]",
        b">vfdb~~~selq~~~~~~ (selq) made-up enterotoxin-like Q [SE (VF0020) - Exotoxin (VFC0235)] "
        b"[Staphylococcus aureus]",
    ]
    body = data.decode("latin-1").split(">")[1:]
    by_gene = {b.split("~~~")[1]: "".join(b.split("\n")[1:]) for b in body}
    assert by_gene["rcgene"] == seqs["rcgene"] and by_gene["fnbA"] == seqs["fnbA"].upper()
    assert all(len(line) <= 60 for line in data.decode("latin-1").splitlines() if not line.startswith(">"))
    # A plain FASTA gives the same database; a file that is not FASTA (a web page) is refused.
    plain = tmp_path / "VFDB_setB_nt.fas"
    plain.write_bytes(raw)
    assert conv.convert_file(plain, tmp_path / "again").sha256_sequences == c.sha256_sequences
    page = tmp_path / "page.fas.gz"
    page.write_text("<html><body>WAF</body></html>\n")
    with pytest.raises(ValueError, match="not FASTA"):
        conv.convert_file(page, tmp_path / "x")
    assert conv.gzip_header(page) is None


def test_makeblastdb_and_custom_datadir_commands():
    argv = conv.makeblastdb_argv("/env/bin/makeblastdb", Path("/db/vfdb_setB/sequences"), Path("/db/vfdb_setB/src/log"))
    assert argv == ["/env/bin/makeblastdb", "-in", "/db/vfdb_setB/sequences", "-title", "vfdb", "-dbtype", "nucl",
                    "-hash_index", "-logfile", "/db/vfdb_setB/src/log"]
    supported = help_options((FIX / "abricate" / "help_1.4.0.txt").read_text())
    a = abr.AbricateAdapter.argv("/env/bin/abricate", abr.AbricateParams("vfdb_setB", 80, 80, 4), Path("/job/in.fna"),
                                 Path("/db/vfdb-setB/2026-11-06"), supported)
    assert a[1:5] == ["--datadir", "/db/vfdb-setB/2026-11-06", "--db", "vfdb_setB"] and "--setupdb" not in a
    for bad in ("", "../vfdb", "a b", "vfdb/../x", "-x"):
        with pytest.raises(ValueError, match="database must be"):
            abr.AbricateParams(bad).validate()
    assert abr.database_name_ok("vfdb_setB") and abr.database_name_ok("plasmidfinder")
    # The warning about what a hit means follows the kind, whatever the folder is called.
    assert abr.warnings(abr.AbricateParams("vfdb_setB"), [], "vfdb")[0]["code"] == "vfdb_meaning"


def test_crlf_headers_and_oversized_fasta(tmp_path, monkeypatch):
    """A CRLF file's header loses its \\r as BioPerl's split(/\\r?\\n/) drops it; a FASTA (or a gzip file inflating)
    past MAX_FASTA_BYTES is refused before it fills memory."""
    import io

    src = b">VFG000001(gb|WP_000001) (abcA) made-up protein [Made (VF0001) - Adherence (VFC0001)] [Madeup sp.]\r\n" \
          b"ATGAAACCC\r\nGGGTTTTAA\r\n"
    out = io.BytesIO()
    conv.convert(io.BytesIO(src), out)
    assert b"\r" not in out.getvalue() and out.getvalue().startswith(b">vfdb~~~abcA~~~WP_000001~~~ (abcA) made-up")
    monkeypatch.setattr(conv, "MAX_FASTA_BYTES", 100)
    big = tmp_path / "VFDB_setB_nt.fas.gz"
    with gzip.open(big, "wb") as fh:
        fh.write(src + b"A" * 1000 + b"\n")
    with pytest.raises(ValueError, match="larger than"):
        conv.convert_file(big, tmp_path / "sequences")


def _abricate() -> str:
    d = detect("abricate", refresh=True)
    if d.path is None:
        pytest.skip("ABRicate is not installed")
    return d.path


def _run(argv: list[str], exe: str, cwd: Path, out: Path | None = None) -> subprocess.CompletedProcess:
    with isolated_home() as home:
        with open(out or os.devnull, "w") as fh:
            return subprocess.run(argv, check=True, cwd=cwd, stdout=fh, stderr=subprocess.PIPE, text=True,
                                  env={**tool_environment(home), **abr.env_for(exe)})


def _index(exe: str, folder: Path) -> None:
    (folder / "src").mkdir(exist_ok=True)
    makeblastdb = str(Path(os.path.realpath(exe)).parent / "makeblastdb")
    _run(conv.makeblastdb_argv(makeblastdb, folder / "sequences", folder / "src" / "makeblastdb.log"), exe, folder)


def test_same_database_as_abricate_get_db_and_searched_with_datadir(tmp_path):
    exe = _abricate()
    raw, seqs = made_up_setb()
    # ABRicate's own conversion, offline: get_vfdb finds src/vfdb.fa.gz and does not download it.
    theirs = tmp_path / "getdb"
    (theirs / "vfdb" / "src").mkdir(parents=True)
    (theirs / "vfdb" / "src" / "vfdb.fa.gz").write_bytes(gzip.compress(raw))
    get_db = str(Path(os.path.realpath(exe)).parent / "abricate-get_db")
    done = _run([get_db, "--db", "vfdb", "--dbdir", str(theirs)], exe, tmp_path)
    assert "Won't re-download existing" in done.stderr
    ours = tmp_path / "db" / "vfdb_setB"
    ours.mkdir(parents=True)
    conv.convert_file(_gz(tmp_path, raw), ours / "sequences")
    expected = (theirs / "vfdb" / "sequences").read_bytes().replace(b"~~~clp G~~~", b"~~~clp_G~~~")
    assert (ours / "sequences").read_bytes() == expected

    _index(exe, ours)
    info = abr.database_info(ours)
    assert info["ready"] and info["sequences"] == 6 and info["description"] == "vfdb"
    query = tmp_path / "query.fna"
    query.write_text(f">contig_1\n{'N' * 50}{seqs['clp G']}{'N' * 50}{_revcom(seqs['geneA'])}\n"
                     f">contig_2\n{seqs['rcgene']}\n")
    report = tmp_path / "out.tsv"
    _run(abr.AbricateAdapter.argv(exe, abr.AbricateParams("vfdb_setB", 80, 80, 1), query, ours.parent,
                                  abr.AbricateAdapter.help_options(exe)), exe, tmp_path, report)
    rows = {r["gene"]: r for r in abr.parse_report(report.read_text())}
    assert set(rows) == {"clp_G", "geneA", "rcgene"}
    # DATABASE is the identifier's prefix (vfdb), not the folder's name; the spaced gene keeps its accession.
    assert {r["database"] for r in rows.values()} == {"vfdb"}
    assert rows["clp_G"]["accession"] == "AAA00003" and rows["geneA"]["strand"] == "-"
    assert abr.parse_vfdb_product(rows["clp_G"]["product"])["vf_name"] == "Made-up antigen"


def _gz(tmp_path: Path, raw: bytes) -> Path:
    p = tmp_path / "VFDB_setB_nt.fas.gz"
    p.write_bytes(gzip.compress(raw))
    return p


@pytest.fixture(scope="module")
def real_setb(tmp_path_factory):
    if not SETB.is_file():
        pytest.skip(f"VFDB's set B nucleotides are not at {SETB} (ARVA_TEST_VFDB_SETB)")
    exe = _abricate()
    folder = tmp_path_factory.mktemp("setb") / "vfdb_setB"
    folder.mkdir()
    c = conv.convert_file(SETB, folder / "sequences")
    _index(exe, folder)
    return exe, folder, c


def test_real_set_b_converts_as_vfdb_counts(real_setb):
    _exe, folder, c = real_setb
    # VFDB's file of 2026-11-06 (sha256 baf005d1..., 35,192 records): 24 identical sequences dropped as
    # abricate-get_db drops them, 967 records without an accession, 16 gene names with spaces.
    if hashlib.sha256(SETB.read_bytes()).hexdigest() != ("baf005d1ba55becc214dcc3fb65b9be3e29e1c6c19e2adedc5c5623ac3"
                                                         "ca4dcd"):
        pytest.skip("another VFDB build than the one these counts were read from")
    assert (c.records_read, c.records_written, c.without_accession, len(c.spaces_replaced)) == (35192, 35168, 967, 16)
    assert c.sha256_fasta == "060222aa648b73faed1660b7495b6d914bb4f3e10bd5eb72395bee3864b5e944"
    assert abr.database_info(folder)["sequences"] == 35168
    text = (folder / "sequences").read_bytes().decode("latin-1").lower()
    # selX is not in VFDB (neither as a name nor as "enterotoxin-like x").
    assert "~~~selx~~~" not in text and "enterotoxin-like x" not in text


def test_real_set_b_finds_the_egc_cluster_on_n315(real_setb, tmp_path):
    exe, folder, _c = real_setb
    genome = GENOMES / "GCF_000009645.1.fna"
    if not genome.is_file():
        pytest.skip(f"S. aureus N315 (GCF_000009645.1) is not in {GENOMES} (ARVA_TEST_GENOMES)")
    staged = tmp_path / "n315.fna"
    staged.write_text("".join(f"{ln.split()[0]}\n" if ln.startswith(">") else ln
                              for ln in genome.read_text().splitlines(keepends=True)))
    report = tmp_path / "n315.tsv"
    _run(abr.AbricateAdapter.argv(exe, abr.AbricateParams(folder.name, 80, 80, 4), staged, folder.parent,
                                  abr.AbricateAdapter.help_options(exe)), exe, tmp_path, report)
    rows = abr.parse_report(report.read_text())
    genes = {r["gene"] for r in rows}
    # The enterotoxin gene cluster (egc: seg, sei, selm, seln, selo; VFDB's names), which the core set A lacks, on
    # the chromosome between 1,876,310 and 1,881,633; selu2 is reported by its accession ABK27166.
    egc = {"seg", "sei", "selm", "seln", "selo"}
    assert egc <= genes and "ABK27166" in genes
    assert all(r["contig"] == "NC_002745.2" and 1876000 < r["start"] < 1882000 for r in rows if r["gene"] in egc)
    assert "selx" not in {g.lower() for g in genes}
    assert {r["database"] for r in rows} == {"vfdb"} and len(rows) >= 140
    # The Database Manager's own copy is not touched: ABRicate's bundled vfdb still holds set A.
    assert abr.database_info(abr.datadir(exe) / "vfdb")["sequences"] == 4592
    shutil.rmtree(tmp_path, ignore_errors=True)
