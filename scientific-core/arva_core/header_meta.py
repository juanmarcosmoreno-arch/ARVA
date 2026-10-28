"""Best-effort sequencing metadata from FASTQ/FASTA read headers: standard library only, never raises,
every grammar tied to a documentation source in SOURCES. Results are suggestions that must never overwrite
user metadata, and read names can be rewritten (e.g. by NCBI SRA), so a missing match proves nothing.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

SCHEMA = "arva.header_meta/1"

MAX_LINE_CHARS = 1_000_000
# Dorado --emit-moves writes very long "mv:B:c,..." tokens; they carry no metadata.
MAX_TOKEN_CHARS = 4096
MAX_TOKENS = 512
MAX_VALUE_CHARS = 256
_MAX_INT_DIGITS = 18
FINGERPRINT_SIZE = 200

SOURCES = {
    "illumina_casava18": [
        "https://help.basespace.illumina.com/files-used-by-basespace/fastq-files",
        "bcl2fastq2 v2.20 Software Guide 15051736 v03 (Table 7 Sequence Identifier Fields)",
        "https://support-docs.illumina.com/SW/dragen_v42/Content/SW/DRAGEN/OutputFiles.htm",
        "Illumina Knowledge Article #7412 (FASTQ files explained): header content varies with the conversion software",
    ],
    "illumina_legacy": ["https://en.wikipedia.org/wiki/FASTQ_format (community source)"],
    "element_bases2fastq": ["https://docs.elembio.io/docs/bases2fastq/outputs/"],
    "ont_minknow_kv": [
        "https://software-docs.nanoporetech.com/output-specifications/latest/read_formats/fastq/",
        "https://github.com/nanoporetech/ont-output-specifications/blob/main/fastq/header-spec.yaml",
    ],
    "ont_dorado_hts": [
        "https://github.com/nanoporetech/ont-output-specifications/blob/main/fastq/header-spec-hts.yaml",
        "https://software-docs.nanoporetech.com/dorado/latest/basecaller/sam_spec/",
        "dorado/hts_utils/hts_file.cpp fastq_aux_tags (nanoporetech/dorado v2.1.2)",
    ],
    "pacbio": [
        "https://pacbiofileformats.readthedocs.io/en/13.1/BAM.html#qname-convention",
        "https://pacbiofileformats.readthedocs.io/en/11.0/BAM.html (subread QNAME)",
        "PacBioFileFormats FileStructure.rst (Revio Movie Context ID mNNNNN_YYMMDD_HHMMSS_sN)",
        "https://ccs.how/faq/mode-by-strand.html (example m64011_190714_120746/14/ccs/rev)",
    ],
    "sra": [
        "https://github.com/ncbi/sra-tools/wiki/HowTo:-fasterq-dump (default deflines)",
        "sra-tools tools/external/sra-dump/fastq.c (--readids 'accession.spot.readid')",
        "https://github.com/ncbi/sra-tools/wiki/Read-Names",
    ],
}
# header_format prefix -> SOURCES key (first match wins)
_SOURCE_KEYS = (
    ("illumina_legacy", "illumina_legacy"),
    ("illumina_", "illumina_casava18"),
    ("element_", "element_bases2fastq"),
    ("casava18_like", "element_bases2fastq"),
    ("ont_minknow_kv", "ont_minknow_kv"),
    ("uuid_read_id", "ont_minknow_kv"),
    ("ont_dorado_hts", "ont_dorado_hts"),
    ("pacbio", "pacbio"),
    ("sra_", "sra"),
)

_CONF = {"none": 0, "low": 1, "medium": 2, "high": 3}
_CONF_NAMES = {v: k for k, v in _CONF.items()}
PLATFORMS = ("illumina", "nanopore", "pacbio")

# re.ASCII everywhere: \d must not match non-ASCII digits.
_A = re.ASCII
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_HEX40 = r"[0-9a-f]{40}"  # pre-UUID MinKNOW run ids (Dorado and EPI2ME fastcat test data)
RE_UUID = re.compile(rf"^{_UUID}$", _A)
RE_RUN_ID = re.compile(rf"^(?:{_UUID}|{_HEX40})$", _A)

# Documented charsets are [A-Za-z0-9_] (instrument) and [A-Za-z0-9] (flowcell); '-' is accepted
# because real ids use it (MiSeq "000000000-A1B2C"). DRAGEN may prefix a UMI with 'r'.
_UMI = r"r?[ACGTN]+(?:\+r?[ACGTN]+)*"
RE_ILMN_ID = re.compile(
    r"^(?P<instrument>[A-Za-z0-9_-]+):(?P<run_number>\d+):(?P<flowcell_id>[A-Za-z0-9-]+):"
    r"(?P<lane>\d+):(?P<tile>\d+):(?P<x_pos>\d+):(?P<y_pos>\d+)"
    rf"(?::(?P<umi>{_UMI}))?$",
    _A,
)
# Same layout with a non-numeric second field: Element bases2fastq "<run name>".
RE_CASAVA_LIKE_ID = re.compile(
    r"^(?P<instrument>[A-Za-z0-9_-]+):(?P<run_name>[A-Za-z0-9_-]+):(?P<flowcell_id>[A-Za-z0-9-]+):"
    r"(?P<lane>\d+):(?P<tile>\d+):(?P<x_pos>\d+):(?P<y_pos>\d+)"
    rf"(?::(?P<umi>{_UMI}))?$",
    _A,
)
RE_ILMN_COMMENT = re.compile(
    r"^(?P<read_number>\d+):(?P<is_filtered>[YN]):(?P<control_number>\d+):"
    r"(?P<index>[ACGTN]+(?:\+[ACGTN]+)*|\d+)?$",
    _A,
)
# Pre-CASAVA-1.8: @HWUSI-EAS100R:6:73:941:1973#0/1 (instrument:lane:tile:x:y#index/mate)
RE_ILMN_LEGACY = re.compile(
    r"^(?P<instrument>[A-Za-z0-9_.-]+):(?P<lane>\d+):(?P<tile>\d+):(?P<x_pos>-?\d+):(?P<y_pos>-?\d+)"
    r"(?:#(?P<index>[A-Za-z0-9]+))?(?:/(?P<mate>[12]))?$",
    _A,
)

RE_PB_CCS = re.compile(
    r"^(?P<movie_name>[A-Za-z0-9_.-]+)/(?P<hole_number>\d+)/ccs"
    r"(?:/(?P<strand>fwd|rev))?(?:/(?P<q_start>\d+)_(?P<q_end>\d+))?$",
    _A,
)
RE_PB_SUBREAD = re.compile(
    r"^(?P<movie_name>[A-Za-z0-9_.-]+)/(?P<hole_number>\d+)/(?P<q_start>\d+)_(?P<q_end>\d+)$", _A
)
# Revio Movie Context ID is documented; decoding Sequel-era names (no _sN) is by analogy.
RE_PB_MOVIE_CONTEXT = re.compile(
    r"^m(?P<instrument_id>\d{5}[A-Za-z]?)_(?P<date_yymmdd>\d{6})_(?P<time_hhmmss>\d{6})(?:_s(?P<stage>\d+))?$",
    _A,
)
RE_PB_MOVIE_RS = re.compile(r"^m\d{6}_\d{6}_\d+_[A-Za-z0-9_]+$", _A)

# sra-tools: $ac.$si, $ac.$si/$ri (fasterq-dump split), $ac.$si.$ri (fastq-dump --readids)
RE_SRA_ID = re.compile(
    r"^(?P<accession>[SED]RR\d{6,})\.(?P<spot_id>\d+)(?:(?P<sep>[./])(?P<read_in_spot>\d+))?$", _A
)
RE_SRA_LENGTH = re.compile(r"^length=(?P<length>\d+)$", _A)

RE_KV = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$", _A | re.S)
RE_SAMTAG = re.compile(r"^(?P<tag>[A-Za-z][A-Za-z0-9]):(?P<type>[AifZHB]):(?P<value>.*)$", _A | re.S)
RE_MATE_SUFFIX = re.compile(r"^(?P<base>.+)/(?P<mate>[12])$", _A | re.S)
RE_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$", _A)
RE_ONT_FLOWCELL = re.compile(r"^[A-Z0-9_-]+$", _A)
RE_ONT_BARCODE = re.compile(r"^(?:unclassified|barcode\d+)$", _A)
RE_ONT_MODEL = re.compile(r"^[A-Za-z0-9_@.\-]+$", _A)
# Dorado read group id: <runid>_<basecalling_model>_<barcode_arrangement>
RE_ONT_RG = re.compile(rf"^(?P<run_id>{_UUID}|{_HEX40})_(?P<rest>.+)$", _A)
RE_ONT_MODEL_IN_RG = re.compile(r"^(?P<model>.*?@v\d+(?:\.\d+)*)(?:_(?P<barcode>.+))?$", _A)

# MinKNOW key=value attributes (ONT output specification) plus aliases seen in ONT/EPI2ME data:
# 'read', 'sampleid' (Dorado/fastcat fixtures) and 'model_version_id' (fastcat parser).
ONT_KV_MAP = {
    "runid": "run_id",
    "ch": "channel",
    "start_time": "start_time",
    "flow_cell_id": "flowcell_id",
    "protocol_group_id": "protocol_group_id",
    "sample_id": "sample_id",
    "sampleid": "sample_id",
    "barcode": "barcode",
    "barcode_alias": "barcode_alias",
    "parent_read_id": "parent_read_id",
    "basecall_model_version_id": "basecall_model",
    "model_version_id": "basecall_model",
    "basecall_gpu": "basecall_gpu",
    "read": "channel_read_number",
}
ONT_KV_DISTINCTIVE = {
    "runid",
    "start_time",
    "flow_cell_id",
    "protocol_group_id",
    "parent_read_id",
    "basecall_model_version_id",
    "model_version_id",
    "basecall_gpu",
}
# Dorado/MinKNOW HTS-style FASTQ tags (header-spec-hts.yaml, Dorado SAM spec and source)
ONT_TAG_MAP = {
    "RG": "read_group",
    "st": "start_time",
    "DT": "experiment_start_time",
    "ch": "channel",
    "PU": "flowcell_id",
    "LB": "sample_id",
    "SM": "barcode",
    "al": "barcode_alias",
    "pi": "parent_read_id",
    "DS": "basecall_gpu",
    "qs": "mean_qscore",
    "mx": "mux",
    "rn": "channel_read_number",
    "tm": "trim_flags",
    "pt": "poly_a_length",
    "dx": "duplex_flag",
}
PACBIO_TAG_MAP = {"np": "num_passes", "rq": "read_quality", "ec": "effective_coverage", "zm": "zmw"}

_NUMERIC_FIELDS = {
    "run_number", "lane", "tile", "x_pos", "y_pos", "read_number", "control_number", "sample_number",
    "channel", "channel_read_number", "hole_number", "q_start", "q_end", "spot_id", "read_in_spot",
    "length", "mux", "poly_a_length", "duplex_flag",
}


class _Ctx:
    __slots__ = ("consumed", "extra", "fields", "warnings")

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.fields: dict[str, Any] = {}
        self.extra: dict[str, str] = {}
        self.consumed: set[int] = set()  # comment-token indices interpreted by a detector

    def warn(self, msg: str) -> None:
        if msg not in self.warnings and len(self.warnings) < 50:
            self.warnings.append(msg)

    def clip(self, value: str, what: str) -> str:
        if len(value) > MAX_VALUE_CHARS:
            self.warn(f"value_clipped:{what}")
            return value[:MAX_VALUE_CHARS]
        return value

    def put(self, key: str, value: Any, *, overwrite: bool = False) -> None:
        if value is None or value == "":
            return
        if isinstance(value, str):
            value = _to_int(value, self, key) if key in _NUMERIC_FIELDS else self.clip(value, key)
        if key in self.fields and not overwrite:
            if self.fields[key] != value:
                self.warn(f"conflicting_values:{key}")
            return
        self.fields[key] = value

    def put_extra(self, key: str, value: str) -> None:
        if len(self.extra) >= 64:
            self.warn("too_many_extra_tokens")
            return
        self.extra[self.clip(key, "extra_key")] = self.clip(value, f"extra:{key[:32]}")

    def merge(self, other: _Ctx) -> None:
        for w in other.warnings:
            self.warn(w)
        for k, v in other.fields.items():
            self.put(k, v)
        self.consumed |= other.consumed


def _to_int(s: str, ctx: _Ctx, key: str) -> Any:
    body = s[1:] if s.startswith("-") else s
    if s.isascii() and body.isdigit() and len(body) <= _MAX_INT_DIGITS:
        return int(s)
    ctx.warn(f"non_integer_or_oversized_number:{key}")
    return s[:MAX_VALUE_CHARS]


def _is_bad_char(ch: str) -> bool:
    o = ord(ch)
    return (o < 32 and ch != "\t") or o == 127 or ch == "�"


def _sanitise(line: Any, ctx: _Ctx) -> str | None:
    """A printable str, "" for a blank line, or None if the input cannot be a header."""
    if line is None:
        ctx.warn("input_is_none")
        return None
    if isinstance(line, bytes | bytearray | memoryview):
        line = bytes(line[: MAX_LINE_CHARS * 4]).decode("utf-8", errors="replace")
    elif not isinstance(line, str):
        ctx.warn(f"unsupported_input_type:{type(line).__name__}")
        return None
    if len(line) > MAX_LINE_CHARS:
        ctx.warn("line_truncated")
        line = line[:MAX_LINE_CHARS]
    cut = min((i for i in (line.find("\n"), line.find("\r")) if i != -1), default=-1)
    if cut != -1:
        if line[cut:].strip():
            ctx.warn("multiple_lines_input_only_first_used")
        line = line[:cut]
    if not line.strip():
        return ""
    bad = sum(1 for ch in line if _is_bad_char(ch))
    if bad:
        ctx.warn("control_or_undecodable_characters")
        if bad / max(len(line), 1) > 0.10:
            return None
        line = "".join("�" if _is_bad_char(ch) else ch for ch in line)
    return line


def _tokenise_comment(comment: str, ctx: _Ctx) -> list[str]:
    # Dorado writes tab-separated SAM tags whose values may contain spaces (DS:Z:gpu:Tesla V100);
    # MinKNOW writes space-separated key=value pairs.
    tokens: list[str] = []
    if "\t" in comment:
        for part in comment.split("\t"):
            p = part.strip()
            if RE_SAMTAG.match(p):
                tokens.append(p)
            else:
                tokens.extend(t for t in part.split(" ") if t)
    else:
        tokens = [t for t in comment.split(" ") if t]
    out: list[str] = []
    for tok in tokens:
        if len(out) >= MAX_TOKENS:
            ctx.warn("too_many_tokens_truncated")
            break
        if len(tok) > MAX_TOKEN_CHARS:
            m = RE_SAMTAG.match(tok[:8])
            ctx.warn(f"oversized_token_skipped:{m.group('tag') if m else tok[:16]}")
            continue
        out.append(tok)
    return out


@dataclass(slots=True)
class _Cand:
    platform: str
    conf: str
    fmt: str
    evidence: list[str]


def _cap(conf: str, limit: str) -> str:
    return _CONF_NAMES[min(_CONF[conf], _CONF[limit])]


def _detect_pacbio(read_id: str, ctx: _Ctx) -> _Cand | None:
    m = RE_PB_CCS.match(read_id)
    kind = "ccs"
    if not m:
        m = RE_PB_SUBREAD.match(read_id)
        kind = "subread"
    if not m:
        return None
    g = m.groupdict()
    movie = g["movie_name"]
    ctx.put("movie_name", movie)
    ctx.put("hole_number", g["hole_number"])
    ctx.put("read_type", kind)
    if g.get("strand"):
        ctx.put("strand", g["strand"])
    if g.get("q_start") is not None:
        ctx.put("q_start", g["q_start"])
        ctx.put("q_end", g["q_end"])
    if kind == "ccs":
        fmt = "pacbio_ccs" + ("_bystrand" if g.get("strand") else "") + ("_segmented" if g.get("q_start") else "")
    else:
        fmt = "pacbio_subread"
    ev = [f"read id matches PacBio QNAME convention ({fmt})"]
    mc = RE_PB_MOVIE_CONTEXT.match(movie)
    if mc:
        ctx.put("movie_instrument_id", mc.group("instrument_id"))
        ctx.put("movie_date_yymmdd", mc.group("date_yymmdd"))
        ctx.put("movie_time_hhmmss", mc.group("time_hhmmss"))
        if mc.group("stage"):
            ctx.put("movie_stage", mc.group("stage"))
        ev.append("movie name matches mNNNNN_YYMMDD_HHMMSS[_sN] (documented for Revio; "
                  "decoding of Sequel-era names is by analogy)")
        return _Cand("pacbio", "high", fmt, ev)
    if RE_PB_MOVIE_RS.match(movie):
        ev.append("movie name matches RS-era example form m150404_101626_42267_s1_p0 (not decoded)")
        return _Cand("pacbio", "high", fmt, ev)
    if movie.startswith("m"):
        ev.append("movie name starts with 'm' but has an undocumented layout")
        return _Cand("pacbio", "medium", fmt, ev)
    ev.append("movie name does not start with 'm' (renamed or prefixed, e.g. bam2fastq --seqid-prefix)")
    return _Cand("pacbio", "low", fmt, ev)


def _detect_illumina(base_id: str, read_id: str, tokens: list[str], ctx: _Ctx) -> _Cand | None:
    first = tokens[0] if tokens else ""
    cm = RE_ILMN_COMMENT.match(first) if first else None
    im = RE_ILMN_ID.match(base_id)
    lm = None if im else RE_CASAVA_LIKE_ID.match(base_id)

    def put_comment() -> None:
        if not cm:
            return
        ctx.consumed.add(0)
        ctx.put("read_number", cm.group("read_number"))
        ctx.put("is_filtered", cm.group("is_filtered"))
        ctx.put("control_number", cm.group("control_number"))
        idx = cm.group("index")
        if idx is None:
            ctx.warn("illumina_comment_without_index_field")
        elif idx.isdigit():
            ctx.put("sample_number", idx)
        else:
            ctx.put("index_sequence", idx)
            if "+" in idx:
                ctx.put("index_parts", idx.split("+")[:4])

    def put_id(m: re.Match[str], run_key: str) -> None:
        g = m.groupdict()
        ctx.put("instrument", g["instrument"])
        ctx.put(run_key, g[run_key])
        ctx.put("flowcell_id", g["flowcell_id"])
        for k in ("lane", "tile", "x_pos", "y_pos"):
            ctx.put(k, g[k])
        if g.get("umi"):
            ctx.put("umi", g["umi"])

    def element(m: re.Match[str], ev: list[str]) -> _Cand | None:
        # Element bases2fastq writes "<instrument>_<model>" here, e.g. ..._AVITI
        if m.group("instrument").upper().endswith("_AVITI"):
            ctx.put("vendor_hint", "element_biosciences")
            return _Cand("unknown", "medium", "element_bases2fastq",
                         [*ev, "instrument ends with _AVITI: Element bases2fastq writes <instrument>_<model> "
                               "in this layout (vendor: Element Biosciences, not Illumina)"])
        return None

    if im:
        put_id(im, "run_number")
        put_comment()
        ev = ["read id has the 7 colon-separated CASAVA 1.8+ fields "
              "<instrument>:<run>:<flowcell>:<lane>:<tile>:<x>:<y>[:<UMI>]"]
        if "-" in im.group("instrument") or "-" in im.group("flowcell_id"):
            ev.append("note: '-' in instrument/flowcell is outside Illumina's documented character set (accepted)")
        el = element(im, ev)
        if el:
            return el
        if cm:
            ev.append("comment matches <read>:<is filtered Y/N>:<control number>:<index or sample number>")
            ev.append("caveat: Element bases2fastq documents a compatible layout; "
                      "vendor inference is strong but not exclusive")
            return _Cand("illumina", "high", "illumina_casava18", ev)
        if first:
            ctx.warn("casava18_name_with_unrecognised_comment")
        return _Cand("illumina", "medium", "illumina_casava18_name_only", ev)
    if lm:
        put_id(lm, "run_name")
        put_comment()
        ev = ["read id has the CASAVA 1.8 layout but field 2 is not numeric (Illumina documents a numeric run "
              "number; Element bases2fastq documents a <run name> here)"]
        return element(lm, ev) or _Cand("unknown", "low", "casava18_like_nonnumeric_run", ev)
    leg = RE_ILMN_LEGACY.match(read_id)
    if leg:
        g = leg.groupdict()
        ctx.put("instrument", g["instrument"])
        for k in ("lane", "tile", "x_pos", "y_pos"):
            ctx.put(k, g[k])
        if g.get("index") is not None:
            ctx.put("legacy_index", g["index"])
        ev = ["read id matches pre-CASAVA-1.8 <instrument>:<lane>:<tile>:<x>:<y>[#index][/mate] "
              "(community-documented)"]
        conf = "medium" if (g.get("index") is not None or g.get("mate")) else "low"
        return _Cand("illumina", conf, "illumina_legacy", ev)
    if cm:
        put_comment()
        first_field = base_id.split(":", 1)[0]
        if ":" in base_id and first_field.upper().endswith("_AVITI"):
            # e.g. Element cell-screening ids (11 colon fields), documented by Element, not Illumina
            ctx.put("instrument", first_field)
            ctx.put("vendor_hint", "element_biosciences")
            return _Cand("unknown", "medium", "element_bases2fastq_other_layout",
                         ["comment matches <read>:<Y/N>:<control>:<index>; instrument field ends with _AVITI "
                          "(Element bases2fastq <instrument>_<model>); layout not decoded"])
        return _Cand("illumina", "low", "illumina_comment_only",
                     ["only the comment matches <read>:<Y/N>:<control>:<index>; read id is not Illumina-shaped"])
    return None


_ONT_KV_CHECKS = {
    "runid": RE_RUN_ID,
    "start_time": RE_RFC3339,
    "flow_cell_id": RE_ONT_FLOWCELL,
    "barcode": RE_ONT_BARCODE,
    "parent_read_id": RE_UUID,
    "basecall_model_version_id": RE_ONT_MODEL,
}


def _put_ont_kv(key: str, value: str, sub: _Ctx) -> None:
    rx = _ONT_KV_CHECKS.get(key)
    if rx is not None and value and not rx.match(value):
        sub.warn(f"value_outside_spec_regex:{key}")
    if key in ("ch", "read") and not (value.isascii() and value.isdigit()):
        sub.warn(f"value_outside_spec_regex:{key}")
        return
    sub.put(ONT_KV_MAP[key], value)


def _detect_ont(read_id: str, tokens: list[str], ctx: _Ctx, skip: set[int] | None = None) -> _Cand | None:
    # Scratch context, merged only on a match, so generic key=value tokens ('read=5') stay uninterpreted.
    sub = _Ctx()
    skip = skip or set()
    kv_keys: list[str] = []
    tags: dict[str, tuple[int, str, str]] = {}
    for i, tok in enumerate(tokens):
        if i in skip:
            continue
        sm = RE_SAMTAG.match(tok)
        if sm:
            if sm.group("tag") in ONT_TAG_MAP and sm.group("tag") not in tags:
                tags[sm.group("tag")] = (i, sm.group("type"), sm.group("value"))
            continue
        km = RE_KV.match(tok)
        if km and km.group("key") in ONT_KV_MAP:
            kv_keys.append(km.group("key"))
            sub.consumed.add(i)
            _put_ont_kv(km.group("key"), km.group("value"), sub)
    uuid_id = bool(RE_UUID.match(read_id))
    if uuid_id:
        sub.put("read_uuid", read_id)

    hts_cand = None
    rg_ok = False
    if "RG" in tags:
        i, _typ, rg = tags["RG"]
        sub.consumed.add(i)
        mrg = RE_ONT_RG.match(rg)
        sub.put("read_group", rg)
        if mrg:
            rg_ok = True
            sub.put("run_id", mrg.group("run_id"))
            rest = mrg.group("rest")
            mm = RE_ONT_MODEL_IN_RG.match(rest)
            if mm:
                sub.put("basecall_model", mm.group("model"))
                if mm.group("barcode"):
                    sub.put("barcode_arrangement", mm.group("barcode"))
            elif rest == "unknown" or rest.startswith("unknown_"):
                # ONT bam/spec.yaml: a missing model_version_id is written as "unknown"
                sub.warn("read_group_model_unknown")
                if rest.startswith("unknown_"):
                    sub.put("barcode_arrangement", rest[len("unknown_"):])
            else:
                sub.warn("read_group_model_boundary_ambiguous")
                sub.put("read_group_model_and_suffix", rest)
    for t, (i, _typ, val) in tags.items():
        if t == "RG":
            continue
        sub.consumed.add(i)
        if t == "DS":
            # header-spec-hts.yaml: DS:Z:gpu:<names>, several GPU types separated by '|'
            if val.lower().startswith("gpu:"):
                sub.put("basecall_gpu", val[4:])
            else:
                sub.put("read_group_description", val)
            continue
        if t in ("st", "DT") and not RE_RFC3339.match(val):
            sub.warn(f"value_outside_spec_regex:{t}")
        if t == "PU" and not RE_ONT_FLOWCELL.match(val):
            sub.warn("value_outside_spec_regex:PU")
        sub.put(ONT_TAG_MAP[t], val)
    if tags:
        strong = sum(1 for t in ("st", "ch", "PU", "DT", "pi", "rn", "mx") if t in tags)
        ev = [f"HTS-style SAM tags in header: {','.join(sorted(tags))}"]
        if rg_ok:
            ev.append("RG:Z value matches <runid>_<basecall model>[_<barcode>] (Dorado read group id)")
            hts_cand = _Cand("nanopore", "high", "ont_dorado_hts", ev)
        elif strong >= 3 or (strong >= 2 and uuid_id):
            hts_cand = _Cand("nanopore", "high" if strong >= 3 and uuid_id else "medium", "ont_dorado_hts", ev)
        elif strong >= 1 and uuid_id:
            hts_cand = _Cand("nanopore", "low", "ont_dorado_hts", ev)

    kv_cand = None
    if kv_keys:
        distinctive = {k for k in kv_keys if k in ONT_KV_DISTINCTIVE}
        ev = [f"MinKNOW-style key=value attributes: {','.join(sorted(set(kv_keys)))}"]
        runid_ok = bool(sub.fields.get("run_id") and RE_RUN_ID.match(str(sub.fields.get("run_id"))))
        violations = sum(1 for w in sub.warnings if w.startswith("value_outside_spec_regex:"))
        if violations:
            ev.append(f"{violations} attribute value(s) do not match the ONT specification regex")
        if ((len(distinctive) >= 2 and (runid_ok or uuid_id)) or len(distinctive) >= 3) and violations < 2:
            kv_cand = _Cand("nanopore", "high", "ont_minknow_kv", ev)
        elif distinctive:
            kv_cand = _Cand("nanopore", "medium", "ont_minknow_kv", ev)
        elif uuid_id:
            kv_cand = _Cand("nanopore", "low", "ont_minknow_kv",
                            [*ev, "only non-distinctive keys (read/ch/barcode/sample_id)"])
    best = max((c for c in (hts_cand, kv_cand) if c), key=lambda c: _CONF[c.conf], default=None)
    if best is None and uuid_id:
        best = _Cand("nanopore", "low", "uuid_read_id",
                     ["read id is a lowercase UUID (ONT read ids are UUIDs; UUIDs are not exclusive to ONT)"])
    if best is not None:
        ctx.merge(sub)
    return best


def _detect_sra(read_id: str, tokens: list[str], ctx: _Ctx) -> tuple[_Cand, dict[str, Any] | None] | None:
    m = RE_SRA_ID.match(read_id)
    if not m:
        return None
    ctx.put("accession", m.group("accession"))
    ctx.put("spot_id", m.group("spot_id"))
    if m.group("read_in_spot"):
        ctx.put("read_in_spot", m.group("read_in_spot"))
        ctx.put("read_in_spot_separator", m.group("sep"))
    length = RE_SRA_LENGTH.match(tokens[-1]) if tokens else None
    if length:
        ctx.put("length", length.group("length"))
        ctx.consumed.add(len(tokens) - 1)
    nested = None
    if tokens and (len(tokens) > 1 or not length):
        spot_name = tokens[0]
        ctx.consumed.add(0)
        ctx.put("spot_name", spot_name)
        if not spot_name.isdigit():
            nested = _parse(spot_name, depth=1)
    fmt = "sra_default_defline" if length else "sra_accession_id"
    ev = [f"read id is an INSDC run accession + spot id ({m.group('accession')}.{m.group('spot_id')})"]
    if length:
        ev.append("comment ends with length=<n> (sra-tools default '$ac.$si $sn length=$rl')")
    ev.append("SRA usually replaces original read names with serial numbers (sra-tools wiki Read-Names)")
    return _Cand("unknown", "high" if length else "medium", fmt, ev), nested


def _empty_result(fmt: str, ctx: _Ctx) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "platform_hint": "unknown",
        "confidence": "none",
        "header_format": fmt,
        "format_confidence": "none",
        "record_type": None,
        "read_id": None,
        "base_name": None,
        "mate": None,
        "mate_source": None,
        "fields": {},
        "extra": {},
        "evidence": [],
        "warnings": ctx.warnings,
    }


def _parse(line: Any, depth: int = 0) -> dict[str, Any]:
    ctx = _Ctx()
    text = _sanitise(line, ctx)
    if text is None:
        return _empty_result("invalid", ctx)
    if text == "":
        ctx.warn("empty_header")
        return _empty_result("empty", ctx)
    record_type = None
    if depth == 0:
        if text[0] == "@":
            record_type, text = "fastq", text[1:]
        elif text[0] == ">":
            record_type, text = "fasta", text[1:]
        else:
            ctx.warn("missing_record_prefix")
    parts = re.split(r"[ \t]", text, maxsplit=1)
    read_id = parts[0]
    comment = parts[1] if len(parts) > 1 else ""
    if not read_id:
        ctx.warn("empty_read_id")
        res = _empty_result("invalid", ctx)
        res["record_type"] = record_type
        return res
    if len(read_id) > MAX_TOKEN_CHARS:
        ctx.warn("oversized_read_id")
        read_id = read_id[:MAX_TOKEN_CHARS]
    tokens = _tokenise_comment(comment, ctx) if comment else []

    nested = None
    cands: list[_Cand] = []
    base_name, mate, mate_source = read_id, None, None

    sra = _detect_sra(read_id, tokens, ctx) if depth == 0 else None
    if sra:
        cand, nested = sra
        m = RE_SRA_ID.match(read_id)
        if m and m.group("sep") == "/" and m.group("read_in_spot") in ("1", "2"):
            mate, mate_source = int(m.group("read_in_spot")), "sra_split_read_id"
            base_name = read_id.rsplit("/", 1)[0]
        # Platform cues surviving inside an SRA defline are capped at medium.
        inner: list[tuple[str, str, str]] = []
        if nested and nested["platform_hint"] != "unknown":
            inner.append((nested["platform_hint"], nested["confidence"],
                          f"SRA spot name preserved the original read name: {nested['header_format']}"))
            if mate is None and nested.get("mate"):
                mate, mate_source = nested["mate"], "sra_spot_name:" + str(nested.get("mate_source"))
        ont = _detect_ont("", tokens, ctx, skip=set(ctx.consumed))
        if ont:
            inner.append(("nanopore", ont.conf, "ONT attributes kept in the SRA comment: " + "; ".join(ont.evidence)))
        plats = {p for p, _, _ in inner}
        if len(plats) == 1:
            top = max(_CONF[c] for _, c, _ in inner)
            cand = _Cand(inner[0][0], _cap(_CONF_NAMES[top], "medium"), cand.fmt,
                         cand.evidence + [e for _, _, e in inner] + ["(confidence capped at medium inside SRA deflines)"])
        elif len(plats) > 1:
            ctx.warn("conflicting_platform_signals:" + ",".join(sorted(plats)))
            cand.evidence += [e for _, _, e in inner]
        cands.append(cand)
    else:
        pb = _detect_pacbio(read_id, ctx)
        if pb:
            cands.append(pb)
            for i, t in enumerate(tokens):  # samtools fastq -T on a PacBio BAM
                sm = RE_SAMTAG.match(t)
                if sm and sm.group("tag") in PACBIO_TAG_MAP:
                    ctx.consumed.add(i)
                    ctx.put(PACBIO_TAG_MAP[sm.group("tag")], sm.group("value"))
        else:
            mm = RE_MATE_SUFFIX.match(read_id)
            if mm:
                base_name, mate, mate_source = mm.group("base"), int(mm.group("mate")), "slash_suffix"
            il = _detect_illumina(base_name, read_id, tokens, ctx)
            if il:
                cands.append(il)
                rn = ctx.fields.get("read_number")
                if il.fmt in ("illumina_casava18", "element_bases2fastq", "element_bases2fastq_other_layout",
                              "illumina_comment_only", "casava18_like_nonnumeric_run") and rn in (1, 2):
                    if mate is not None and mate != rn:
                        ctx.warn("mate_conflict_slash_suffix_vs_comment")
                    mate, mate_source = rn, "illumina_comment_read_field"
            ont = _detect_ont(read_id, tokens, ctx)
            if ont:
                cands.append(ont)

    for i, tok in enumerate(tokens):
        if i in ctx.consumed:
            continue
        sm = RE_SAMTAG.match(tok)
        if sm:
            ctx.put_extra(sm.group("tag"), sm.group("value"))
            continue
        km = RE_KV.match(tok)
        if km:
            ctx.put_extra(km.group("key"), km.group("value"))
            continue
        ctx.put_extra(f"token_{i}", tok)

    # An SRA defline or an Element header is a recognised format that says nothing about an ARVA platform.
    platform, conf, fmt, fmt_conf, evidence = "unknown", "none", "unrecognised", "none", []
    if cands:
        top = max(_CONF[c.conf] for c in cands)
        best = [c for c in cands if _CONF[c.conf] == top]
        plats = {c.platform for c in best}
        evidence = [e for c in cands for e in c.evidence]
        if len(plats) > 1:
            ctx.warn("conflicting_platform_signals:" + ",".join(sorted(plats)))
            fmt, fmt_conf = "+".join(sorted(c.fmt for c in best)), "low"
        else:
            platform, fmt, fmt_conf = best[0].platform, best[0].fmt, best[0].conf
            conf = fmt_conf if platform != "unknown" else "none"
            if sra and platform != "unknown":
                fmt_conf = "high" if fmt == "sra_default_defline" else "medium"
    elif mate is not None:
        fmt, fmt_conf = "generic_slash_mate", "low"
        evidence = ["read id ends with /1 or /2 (generic mate convention; not platform-specific)"]

    result = {
        "schema": SCHEMA,
        "platform_hint": platform,
        "confidence": conf,
        "header_format": fmt,
        "format_confidence": fmt_conf,
        "record_type": record_type,
        "read_id": ctx.clip(read_id, "read_id"),
        "base_name": ctx.clip(base_name, "base_name"),
        "mate": mate,
        "mate_source": mate_source,
        "fields": ctx.fields,
        "extra": ctx.extra,
        "evidence": evidence,
        "warnings": ctx.warnings,
    }
    if nested is not None:
        result["original_name"] = nested
    return result


def parse_header(line: str | bytes) -> dict[str, Any]:
    """Parse one FASTQ ('@') or FASTA ('>') header line into platform hint, fields and evidence; never raises."""
    try:
        return _parse(line)
    except Exception as exc:  # pragma: no cover - the parser must never break an import
        ctx = _Ctx()
        ctx.warn(f"internal_error:{type(exc).__name__}")
        return _empty_result("invalid", ctx)


def sources_for(header_format: str) -> list[str]:
    """Documentation behind a header_format (each part of a conflicting 'a+b' format)."""
    out: list[str] = []
    for part in header_format.split("+"):
        for prefix, key in _SOURCE_KEYS:
            if part.startswith(prefix):
                out += [s for s in SOURCES[key] if s not in out]
                break
    return out


_SUMMARY_KEYS = (
    "instrument", "run_number", "run_name", "flowcell_id", "lane", "run_id", "sample_id", "protocol_group_id",
    "basecall_model", "basecall_gpu", "barcode", "barcode_alias", "barcode_arrangement", "index_sequence",
    "sample_number", "umi_present", "movie_name", "movie_instrument_id", "read_type", "strand", "accession",
    "experiment_start_time",
)


def summarise(
    headers: Iterable[str | bytes],
    max_headers: int = 1000,
    max_distinct: int = 20,
    fingerprint_size: int = FINGERPRINT_SIZE,
) -> dict[str, Any]:
    """Aggregate the first ``max_headers`` headers of one file; never raises. ``mate_fingerprint`` keeps the
    base names and mates of the first ``fingerprint_size`` headers for compare_fingerprints()."""
    platform_counts: Counter[str] = Counter()
    conf_by_platform: dict[str, Counter[str]] = {}
    format_counts: Counter[str] = Counter()
    mates: Counter[str] = Counter()
    read_numbers: Counter[str] = Counter()
    filtered: Counter[str] = Counter()
    warn_counts: Counter[str] = Counter()
    distinct: dict[str, Counter[str]] = {k: Counter() for k in _SUMMARY_KEYS}
    evidence: dict[str, list[str]] = {}
    fp_names: list[str | None] = []
    fp_mates: list[int | None] = []
    n = n_usable = 0
    try:
        max_headers = max(0, int(max_headers))
        max_distinct = max(1, int(max_distinct))
        fingerprint_size = max(0, int(fingerprint_size))
    except (TypeError, ValueError):
        max_headers, max_distinct, fingerprint_size = 1000, 20, FINGERPRINT_SIZE
        warn_counts["invalid_limits_defaulted"] += 1
    try:
        it = iter(headers) if headers is not None else iter(())
    except TypeError:
        it = iter(())
        warn_counts["headers_not_iterable"] += 1
    try:
        for h in it:
            if n >= max_headers:
                break
            n += 1
            r = parse_header(h)
            if len(fp_names) < fingerprint_size:
                fp_names.append(r["base_name"])
                fp_mates.append(r["mate"])
            for w in r["warnings"]:
                warn_counts[w.split(":", 1)[0]] += 1
            fmt = r["header_format"]
            if fmt in ("empty", "invalid"):
                format_counts[fmt] += 1
                continue
            n_usable += 1
            p = r["platform_hint"]
            platform_counts[p] += 1
            conf_by_platform.setdefault(p, Counter())[r["confidence"]] += 1
            format_counts[fmt] += 1
            evidence.setdefault(fmt, r["evidence"][:8])
            mates[str(r["mate"]) if r["mate"] else "none"] += 1
            f = r["fields"]
            if "read_number" in f:
                read_numbers[str(f["read_number"])] += 1
            if "is_filtered" in f:
                filtered[str(f["is_filtered"])] += 1
            for k in _SUMMARY_KEYS:
                if k == "umi_present":
                    if "umi" in f:
                        distinct[k]["yes"] += 1
                    continue
                if k in f:
                    distinct[k][str(f[k])[:MAX_VALUE_CHARS]] += 1
    except Exception as exc:  # e.g. a generator that raises (I/O error): keep what was read
        warn_counts[f"iteration_error:{type(exc).__name__}"] += 1

    distinct_out = {
        k: {"values": [v for v, _ in c.most_common(max_distinct)], "n_distinct": len(c), "truncated": len(c) > max_distinct}
        for k, c in distinct.items()
        if c
    }
    if mates.get("1") and mates.get("2"):
        mate_layout = "mixed_1_and_2"  # interleaved or concatenated R1+R2
    elif mates.get("1"):
        mate_layout = "mate_1_only" if not mates.get("none") else "mate_1_partial"
    elif mates.get("2"):
        mate_layout = "mate_2_only" if not mates.get("none") else "mate_2_partial"
    else:
        mate_layout = "no_mate_markers"
    return {
        "schema": SCHEMA,
        "n_headers_read": n,
        "n_usable": n_usable,
        "platform_counts": dict(platform_counts),
        "confidence_by_platform": {k: dict(v) for k, v in conf_by_platform.items()},
        "format_counts": dict(format_counts),
        "mates": dict(mates),
        "mate_layout": mate_layout,
        "illumina_read_numbers": dict(read_numbers),
        "illumina_is_filtered": dict(filtered),
        "distinct": distinct_out,
        "warning_counts": dict(warn_counts),
        "evidence": evidence,
        "sources": {fmt: sources_for(fmt) for fmt in evidence},
        "suggested_technology": _suggest(platform_counts, conf_by_platform, n_usable),
        "mate_fingerprint": {"base_names": fp_names, "mates": fp_mates},
    }


def _suggest(platform_counts: Counter[str], conf_by_platform: dict[str, Counter[str]], n_usable: int) -> dict[str, Any]:
    base = {"overrides_user_metadata": False, "source": "read headers only"}
    known = {p: c for p, c in platform_counts.items() if p != "unknown"}
    if not n_usable or not known:
        return {**base, "value": None, "confidence": "none", "agreement": 0.0, "conflicting_headers": 0,
                "reason": "no platform-specific header grammar matched"}
    top, n_top = max(known.items(), key=lambda kv: (kv[1], kv[0]))
    conflicting = sum(c for p, c in known.items() if p != top)
    cb = conf_by_platform.get(top, Counter())
    n_high = cb.get("high", 0)
    n_med_plus = n_high + cb.get("medium", 0)
    if conflicting == 0 and n_high / n_usable >= 0.9:
        conf = "high"
    elif conflicting / n_usable <= 0.05 and n_med_plus / n_usable >= 0.8:
        conf = "medium"
    else:
        conf = "low"
    return {**base, "value": top, "confidence": conf, "agreement": round(n_top / n_usable, 4),
            "conflicting_headers": conflicting,
            "reason": f"{n_top}/{n_usable} headers point to {top} ({n_high} high-confidence)"}


def _compare_pairs(pairs: Iterable[tuple[tuple[Any, Any], tuple[Any, Any]]]) -> dict[str, Any]:
    n = same = 0
    m1: Counter[str] = Counter()
    m2: Counter[str] = Counter()
    for (name1, mate1), (name2, mate2) in pairs:
        n += 1
        m1[str(mate1)] += 1
        m2[str(mate2)] += 1
        if name1 is not None and name1 == name2:
            same += 1
    frac = same / n if n else 0.0
    return {
        "pairs_compared": n,
        "base_name_matches": same,
        "match_fraction": round(frac, 4),
        "r1_mates": dict(m1),
        "r2_mates": dict(m2),
        "looks_like_pair": bool(n) and frac >= 0.99 and m1.get("2", 0) == 0 and m2.get("1", 0) == 0,
    }


def compare_mates(r1_headers: Iterable[str | bytes], r2_headers: Iterable[str | bytes], max_pairs: int = 1000) -> dict[str, Any]:
    """Do two files look like mates (same base read names in the same order)? Never raises."""
    pairs = []
    try:
        for a, b in zip(r1_headers, r2_headers, strict=False):
            if len(pairs) >= max_pairs:
                break
            pa, pb = parse_header(a), parse_header(b)
            pairs.append(((pa["base_name"], pa["mate"]), (pb["base_name"], pb["mate"])))
    except Exception as exc:
        return {"pairs_compared": len(pairs), "error": type(exc).__name__, "looks_like_pair": False}
    return _compare_pairs(pairs)


def compare_fingerprints(r1: Any, r2: Any) -> dict[str, Any]:
    """compare_mates() on two stored ``mate_fingerprint`` dicts from summarise(). Never raises."""
    try:
        first = list(zip(r1["base_names"], r1["mates"], strict=True))
        second = list(zip(r2["base_names"], r2["mates"], strict=True))
    except (KeyError, TypeError, ValueError):
        return {"pairs_compared": 0, "error": "invalid_fingerprint", "looks_like_pair": False}
    return _compare_pairs(zip(first, second, strict=False))


def combine_suggestions(suggestions: list[Any]) -> dict[str, Any]:
    """Sample-level suggestion from per-file ``suggested_technology`` dicts (short + long reads is 'hybrid');
    confidence is the weakest contributing file, capped at medium when some files carry no evidence."""
    known = [s for s in suggestions if isinstance(s, dict) and s.get("value") in PLATFORMS]
    base = {"overrides_user_metadata": False, "files_considered": len(suggestions), "files_with_evidence": len(known)}
    platforms = sorted({s["value"] for s in known})
    if not known:
        return {**base, "value": None, "confidence": "none", "basis": "no_evidence", "platforms": []}
    if len(platforms) == 1:
        value, basis = platforms[0], "single_platform"
    elif "illumina" in platforms:
        value, basis = "hybrid", "short_and_long_reads"
    else:
        return {**base, "value": None, "confidence": "none", "basis": "conflicting_platforms", "platforms": platforms}
    conf = _CONF_NAMES[min(_CONF.get(s.get("confidence"), 0) for s in known)]
    if len(known) < len(suggestions):
        conf = _cap(conf, "medium")
    return {**base, "value": value, "confidence": conf, "basis": basis, "platforms": platforms}
