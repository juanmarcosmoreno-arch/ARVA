"""Medaka models that the medaka package does not ship: the ones medaka 2.1.1 knows and can load, where it publishes
them, their checksums, what they were trained for, and how ARVA checks that a file is a medaka model archive.

Verified against medaka 2.1.1 (ARVA's Bioconda lock docker/conda-locks/medaka; its sources medaka/options.py,
medaka/models.py, medaka/datastore.py, medaka/medaka.py and bin/medaka_consensus) and the medaka repository at its tag
v2.1.1 (commit 7354d9d564693ea08998577a21aa72f02117107e, whose medaka/options.py is byte-identical to the installed
one), read on 2026-11-07:

* Names. options.py lists `current_models` (the four files the package ships in medaka/data: the R10.4.1 E8.2 400 bps
  hac/sup v5.2.0 consensus and v5.0.0 variant models), `archived_models` ("not included in packages but can be
  downloaded on the fly") plus the models of `basecaller_models`, and `deprecated_models` (the old TensorFlow models,
  r941_min_high_g360 among them: resolve_model raises "Model '...' is deprecated in medaka v2.0. Please use medaka
  version 1.x."). `allowed_models` = known minus deprecated; `medaka_consensus -h` lists them after "Choices:" (it
  filters out variant/snp models). `medaka tools list_models` prints them as "Available: ...".
* Files. A model name resolves to `<name>_model_pt.tar.gz` (models.model_suffixes) looked up in medaka/data inside the
  package and in ~/.medaka/data. A missing known model is downloaded by resolve_model, and by
  `medaka tools download_models --models <name> ...` (default: every allowed model), from
  options.model_url_template = https://github.com/nanoporetech/medaka/raw/master/medaka/data/<file> (the master branch,
  so not pinned to the installed version), with requests.get, no checksum; medaka only checks that the archive opens
  and that its meta has 'model_function', then writes it into the first model store it can write.
* The repository stores the model files with Git LFS (.gitattributes: medaka/data/*model_pt.tar.gz filter=lfs), so the
  git tree holds LFS pointers that state each file's SHA-256 (oid) and size. GitHub serves the content of an LFS file
  from media.githubusercontent.com/media/<owner>/<repo>/<ref>/<path>. ARVA downloads from that address at the tag of
  the installed medaka (v2.1.1), not from master, and checks the SHA-256 and size against the LFS pointer of the same
  tag (PUBLISHED below, copied from `git show v2.1.1:medaka/data/<file>`). Test on 2026-11-07:
  r941_min_hac_g507_model_pt.tar.gz from https://media.githubusercontent.com/media/nanoporetech/medaka/v2.1.1/medaka/
  data/r941_min_hac_g507_model_pt.tar.gz, 1,502,971 bytes, SHA-256 6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb26
  8ef07ac7680ac26 (the server's ETag is the same hash), loaded by medaka_consensus 2.1.1 with -m <that file> on the
  synthetic genome (log: "Using model: <file>"; consensus with 0 SNPs and 0 indels against the reference).
* Archive. A .tar.gz with model/meta.pkl (a Python pickle: functools.partial of medaka.models.build_model_torch, a
  medaka.labels label scheme and a medaka.features feature encoder) and model/weights.pt (a PyTorch zip whose
  weights/data.pkl rebuilds tensors: collections.OrderedDict, torch.FloatStorage, torch._utils._rebuild_tensor_v2).
  medaka unpickles both when it loads the model (datastore.ModelStoreTGZ), so a model file is code. ARVA checks a
  file without running it: the tar members, then every global the two pickles would import (pickletools, which only
  reads opcodes) against what medaka's own files use. Only then may medaka open it.
* Using a file. resolve_model returns any existing path unchanged ("model is path to model file"), so
  `medaka_consensus -m <path>` uses that file (bin/medaka_consensus: MODEL=$(medaka tools resolve_model --model
  $OPTARG); its -h: "Alternatively a .tar.gz/.hdf file from 'medaka train'").
* Licence. medaka is distributed under the Oxford Nanopore Technologies PLC. Public License Version 1.0 (README
  "Licence and Copyright"; the LICENSE file of the repository and of the package's dist-info); the model files are
  part of that repository and state no other licence.
* What a model is for. medaka names models <pore>[_<kit or device>]_<accuracy>_<basecaller version>: CHANGELOG
  "New models for MinION/GridION and PromethION" (min, prom), "Models for Guppy version 5.0.7" (g507), "R10.4 E8.1
  consensus models for Guppy version 5.0.15" (r104_e81_*_g5015), "New models for R10.4.1 E8.2 400bps/260bps"; the
  vX.Y.Z suffix is the Dorado basecaller model version (options.basecaller_models: dna_r10.4.1_e8.2_400bps_hac@v4.1.0
  -> r1041_e82_400bps_hac_v4.1.0; dna_r9.4.1_e8_hac@v3.3 -> r941_min_hac_g507).
"""
from __future__ import annotations

import hashlib
import io
import pickletools
import re
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arva_tools.medaka import MODEL_SUFFIX

MEDAKA_VERSION = "2.1.1"
MEDAKA_TAG = "v2.1.1"
MEDAKA_COMMIT = "7354d9d564693ea08998577a21aa72f02117107e"
# medaka/options.py model_url_template (what medaka itself downloads, from master).
MEDAKA_URL_TEMPLATE = "https://github.com/nanoporetech/medaka/raw/master/medaka/data/{fname}"
# Where GitHub serves the LFS content, at the tag of the installed medaka (what ARVA downloads).
DOWNLOAD_URL_TEMPLATE = "https://media.githubusercontent.com/media/nanoporetech/medaka/{tag}/medaka/data/{fname}"
POINTER_URL_TEMPLATE = "https://github.com/nanoporetech/medaka/blob/{tag}/medaka/data/{fname}"
LICENCE = "Oxford Nanopore Technologies PLC. Public License Version 1.0"
LICENCE_URL = "https://github.com/nanoporetech/medaka/blob/v2.1.1/LICENSE"
CITATION = ("Oxford Nanopore Technologies. Medaka: sequence correction provided by ONT Research. "
            "https://github.com/nanoporetech/medaka")

# The consensus models medaka_consensus 2.1.1 offers (its -h "Choices:") that the package does not ship, with the SHA-256
# and size of the LFS pointer at the tag v2.1.1. Left out: the read-level models (*_rl_lstm384_*: need dwell times,
# not selected automatically, "significantly more computationally intensive"), the APK joint-polishing model and the
# bacterial methylation model (ARVA does not offer --bacteria).
PUBLISHED: dict[str, tuple[str, int]] = {
    "r103_fast_g507": ("18ff794be16b1a0abc1d22c1e85ea2999e051d52c4a6451e8cf83a588bc95132", 1505376),
    "r103_hac_g507": ("fd493514c719258fba727c2437771b6bcbfe114ab1958e7f8c6f239359004576", 1502138),
    "r103_sup_g507": ("f73cce05e2c83b3677d21e98f20e37118213b76bbea8e71a61552cf01850fefd", 1505434),
    "r1041_e82_260bps_fast_g632": ("149dfdc9727f9ff9f4204621e1de9113f7b49940940381b2166a2ff932f0fa38", 1504372),
    "r1041_e82_260bps_hac_g632": ("b7f2a707890e4575df9f5779e9dbb7bd9229b843d6bc7e456f98f852dde2ff5b", 1504614),
    "r1041_e82_260bps_hac_v4.0.0": ("5f879c271d87d18ae482281dcb2ab7658e1f97dc0148ddec3b3da8ea0ade4e2a", 1504740),
    "r1041_e82_260bps_hac_v4.1.0": ("0d14d9e7677f94dd333e2dcf83712d3bb7d5f059cca72e994bc3f62c3c60589e", 1502277),
    "r1041_e82_260bps_sup_g632": ("feae43649b039c29edaaa4a51cbf5d76cf00e525f0ec755d0e148b89db168dd9", 1505084),
    "r1041_e82_260bps_sup_v4.0.0": ("0d6c5719a8223cf299258b12851d81e0e6f72146549def7b58736d65e8ff2630", 1502156),
    "r1041_e82_260bps_sup_v4.1.0": ("483297f4f5ea627d61018ed54452ca09629799a2d4e599dce02dadd0ebf74e36", 1503369),
    "r1041_e82_400bps_fast_g615": ("4b33f2843d755a4f74bb6b6604eea4a50a72a5c2bffb0fe2947108f8a88b5a96", 1505206),
    "r1041_e82_400bps_fast_g632": ("c902579f4f99c09b258711e1e94e72aff0003d371ac1d65722463100f24b2016", 1505191),
    "r1041_e82_400bps_hac_g615": ("7ce3cdc3dd9cd26d86ccd2568ef90c17edccd70adeec77aabbff6370c05dbdf6", 1504217),
    "r1041_e82_400bps_hac_g632": ("36b65e9a5890e7cf28ec2fd5ef555ee90fb7443aa8db868e37a8b1dae6081c44", 1502502),
    "r1041_e82_400bps_hac_v4.0.0": ("acf8833abd9c4e591c2ca20ef0ff117eb43fbc89e483d32523e010dee9e78d33", 1505112),
    "r1041_e82_400bps_hac_v4.1.0": ("889d87663c999b1890901a66a182c935e03d99d376c8e6b8053a4b9c5ddd6174", 1504386),
    "r1041_e82_400bps_hac_v4.2.0": ("fff47bad6d918aeb022ce147cf82a9ec68ab0ba0d461ce72d3e3c278a7439224", 1503890),
    "r1041_e82_400bps_hac_v4.3.0": ("b4c9d946f6a845421a6581c33ee49558556ac3979019bb68e33706f3bd3fadd7", 1505394),
    "r1041_e82_400bps_hac_v5.0.0": ("8ca91baf9861f6a6270fefd3c7dc31efa9a55fa9e25c5e7e31a10e1bee8ded6f", 1504290),
    "r1041_e82_400bps_sup_g615": ("2f11c058706f8d1c0f0795a96a7c0094ca25060deba8bd4d8b38b2a9f7bb8d9a", 1502297),
    "r1041_e82_400bps_sup_v4.0.0": ("7df3b429563470a54e401411ade41428857454c99c0a393dec0b36fa788944ca", 1504632),
    "r1041_e82_400bps_sup_v4.1.0": ("3b812570a9e02d2de5cca5fa17a65d1698aa0be693d3fe27017dccf732d8c085", 1502543),
    "r1041_e82_400bps_sup_v4.2.0": ("7bc135954d98abbc8e26d75c5a1afe0a1e0e2a332bc496b360aade256f54221c", 1502313),
    "r1041_e82_400bps_sup_v4.3.0": ("7006f79fc0f49462215860030a9c34cb148619cabb70397277ff481ecf568963", 1503329),
    "r1041_e82_400bps_sup_v5.0.0": ("4e5769848bed7b4e490c111fd8ddf4dad674500db72771a7ec15d4df727afc85", 1501952),
    "r104_e81_fast_g5015": ("9e8ca0b7fd2d091a3944dff3db38e3ce908828577591558df4b620165a22dec2", 1505026),
    "r104_e81_hac_g5015": ("f29e88fcefbd67bd91566182af2d9bada831497451c66e90110b9332e94307ee", 1501879),
    "r104_e81_sup_g5015": ("6f05f870ef3c605f252ff298c77a7032aff2adcfecfa17cc6ee360a718fc0708", 1501998),
    "r104_e81_sup_g610": ("7944626b1b3853162a7226981c2c4278b20fc4406b4c9cce4248eb746d044770", 1503741),
    "r941_e81_fast_g514": ("bf9213155f95920028ad8ce9ce9aaee03cb1a9f973470050819b87f0e70000a7", 1505548),
    "r941_e81_hac_g514": ("e1d443900f4c968d8f5e4a7441d4134544801afc1e7baf80aadfb0ce79305cf1", 1504967),
    "r941_e81_sup_g514": ("cff71650f9ac364c8ae293e630c2d019f02ff3ef0f61057c8577a19b4d887850", 1504563),
    "r941_min_fast_g507": ("ed67b9313009f43cc64f9de9182fd835752414810352bed661d99ef85d713f9a", 1505525),
    "r941_min_hac_g507": ("6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb268ef07ac7680ac26", 1502971),
    "r941_min_sup_g507": ("6c4415c4c589c75bf48703f4ad351012e87e3b5c499953623d412776620a02d4", 1502018),
    "r941_prom_fast_g507": ("3820e593116be76489473b5991087eb7ac1cca2c368af993e983458816b472f8", 1503550),
    "r941_prom_hac_g507": ("b9e99a823f041cb1c0d5fc600da2de7b31e2de0603d1bc789005a11a6e59c3c5", 1503466),
    "r941_prom_sup_g507": ("03e93d967e100e0f172b1263f1f72e199cfe82b93377c79c02db8c273c562cde", 1503109),
    "r941_sup_plant_g610": ("9bfaf8391ffdebff17473b0d06b27719364aa355fe4bc8a8ffd019397e98e9d7", 1505121),
}

# The members of a medaka 2 model archive (datastore.ModelStoreTGZ: top_level_dir 'model', meta.pkl; weights.pt is
# loaded with torch.load), and the globals medaka's own files reference (every shipped and published file checked).
ARCHIVE_DIR = "model"
ARCHIVE_FILES = ("model/meta.pkl", "model/weights.pt")
META_LIMIT = 1 << 16
WEIGHTS_LIMIT = 256 << 20
ARCHIVE_LIMIT = 256 << 20
META_GLOBALS = re.compile(r"functools\.partial|medaka\.models\.build_model_torch|medaka\.labels\.[A-Za-z]+LabelScheme"
                          r"|medaka\.features\.[A-Za-z]+FeatureEncoder")
WEIGHTS_GLOBALS = re.compile(r"collections\.OrderedDict|torch\.[A-Za-z]*Storage|torch\._utils\._rebuild_tensor_v2")
_NAME = re.compile(r"[a-z0-9][a-z0-9_.]{2,100}")
_STRING_OPS = {"SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8", "UNICODE", "SHORT_BINSTRING", "BINSTRING", "STRING"}

_PORES = {"r941": "R9.4.1", "r103": "R10.3", "r104": "R10.4", "r1041": "R10.4.1"}
_ACCURACY = {"fast": "fast", "hac": "high accuracy (hac)", "sup": "super accuracy (sup)"}


@dataclass(frozen=True)
class ModelInfo:
    name: str
    file: str
    pore: str
    chemistry: str
    device: str | None
    accuracy: str
    basecaller: str
    sha256: str
    bytes: int
    url: str
    pointer_url: str
    medaka_url: str
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def model_file_name(name: str) -> str:
    return f"{name}{MODEL_SUFFIX}"


def describe(name: str) -> dict[str, Any]:
    """What a model's name says it was trained for (medaka's naming; see the module notes)."""
    parts = name.split("_")
    out: dict[str, Any] = {"pore": _PORES.get(parts[0], parts[0]), "chemistry": _chemistry(name), "device": None,
                           "accuracy": None, "basecaller": None, "notes": []}
    rest = parts[1:]
    if rest and rest[0] in ("min", "prom"):
        out["device"] = {"min": "MinION/GridION", "prom": "PromethION"}[rest.pop(0)]
    out["accuracy"] = next((p for p in rest if p in _ACCURACY), None)
    if "plant" in rest:
        out["notes"].append("plant")
    tag = rest[-1] if rest else ""
    if m := re.fullmatch(r"g(\d)(\d)(\d+)", tag):
        out["basecaller"] = f"Guppy {m.group(1)}.{m.group(2)}.{m.group(3)}"
    elif re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        out["basecaller"] = f"Dorado basecaller model {tag}"
    if out["accuracy"] == "fast":
        out["notes"].append("fast")
    return out


def _chemistry(name: str) -> str:
    """R9.4.1 / R9.4.1 E8.1 / R10.3 / R10.4 E8.1 / R10.4.1 E8.2 400 bps from the name's leading parts."""
    parts = name.split("_")
    text = _PORES.get(parts[0], parts[0])
    for p in parts[1:3]:
        if m := re.fullmatch(r"e(\d)(\d)", p):
            text += f" E{m.group(1)}.{m.group(2)}"
        elif m := re.fullmatch(r"(\d+)bps", p):
            text += f" {m.group(1)} bps"
    return text


def info(name: str, tag: str = MEDAKA_TAG) -> ModelInfo:
    if name not in PUBLISHED:
        raise KeyError(name)
    sha, size = PUBLISHED[name]
    d = describe(name)
    fname = model_file_name(name)
    return ModelInfo(name=name, file=fname, pore=d["pore"], chemistry=_chemistry(name), device=d["device"],
                     accuracy=d["accuracy"] or "?", basecaller=d["basecaller"] or "?", sha256=sha, bytes=size,
                     url=DOWNLOAD_URL_TEMPLATE.format(tag=tag, fname=fname),
                     pointer_url=POINTER_URL_TEMPLATE.format(tag=tag, fname=fname),
                     medaka_url=MEDAKA_URL_TEMPLATE.format(fname=fname), notes=tuple(d["notes"]))


def catalogue(allowed: list[str] | None = None, shipped: list[str] | None = None) -> list[ModelInfo]:
    """The published models ARVA can download, limited to those the installed medaka allows (options.allowed_models)
    and does not ship, when its lists are given."""
    names = sorted(PUBLISHED)
    if allowed is not None:
        names = [n for n in names if n in set(allowed)]
    if shipped:
        names = [n for n in names if n not in set(shipped)]
    return [info(n) for n in names]


def name_from_file(filename: str) -> str | None:
    """<name>_model_pt.tar.gz -> name (medaka/models.py model_suffixes)."""
    if not filename.endswith(MODEL_SUFFIX):
        return None
    name = filename[: -len(MODEL_SUFFIX)]
    return name if _NAME.fullmatch(name) else None


# --- Checking a file without running it -------------------------------------------------------------------------

class NotAModel(ValueError):
    """The file is not a medaka 2 model archive ARVA accepts; `code` names why."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def pickle_globals(data: bytes) -> list[str]:
    """Every module.name a pickle would import (GLOBAL, STACK_GLOBAL, INST), read with pickletools: nothing is
    unpickled. A STACK_GLOBAL whose two strings are not the two pushed just before it is refused (it could be built
    from memo lookups this reading cannot follow)."""
    found: list[str] = []
    recent: list[tuple[str, Any]] = []
    try:
        for op, arg, _pos in pickletools.genops(data):
            if op.name in ("GLOBAL", "INST"):
                found.append(str(arg).replace(" ", "."))
            elif op.name == "STACK_GLOBAL":
                strings = [a for kind, a in recent[-2:] if kind == "str"]
                if len(recent) < 2 or len(strings) != 2:
                    raise NotAModel("pickle_unreadable", "a pickled global is built in a way ARVA does not read")
                found.append(f"{strings[0]}.{strings[1]}")
            if op.name in _STRING_OPS:
                recent.append(("str", arg))
            elif op.name not in ("MEMOIZE", "BINPUT", "LONG_BINPUT", "PUT", "FRAME"):
                recent.append(("op", op.name))
    except NotAModel:
        raise
    except Exception as exc:  # pickletools raises ValueError and others on a malformed stream
        raise NotAModel("pickle_unreadable", f"the pickle could not be read: {exc}") from exc
    return found


def _check_globals(where: str, names: list[str], allowed: re.Pattern[str]) -> None:
    bad = sorted({n for n in names if not allowed.fullmatch(n)})
    if bad:
        raise NotAModel("unexpected_code", f"{where} would import {', '.join(bad[:5])}, which medaka's own model "
                                           "files never do")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(path: Path) -> dict[str, Any]:
    """Whether `path` is a medaka 2 model archive, read without running anything: a gzip tar holding only model/,
    model/meta.pkl and model/weights.pt (regular files, sizes within limits), a meta pickle with 'model_function' that
    imports only what medaka's own models import, and a PyTorch weights file (zip with weights/data.pkl) that rebuilds
    tensors only. Raises NotAModel."""
    size = path.stat().st_size
    if size > ARCHIVE_LIMIT:
        raise NotAModel("too_large", f"{size:,} bytes; medaka's model files are about 1.5 MB")
    try:
        with tarfile.open(path, "r:gz") as tar:
            members = tar.getmembers()
            names = sorted(m.name.rstrip("/") for m in members)
            if names not in ([ARCHIVE_DIR, *ARCHIVE_FILES], list(ARCHIVE_FILES)):
                raise NotAModel("wrong_members", "the archive holds " + ", ".join(names[:6]) + "; a medaka model holds "
                                "model/meta.pkl and model/weights.pt")
            by_name = {m.name.rstrip("/"): m for m in members}
            if ARCHIVE_DIR in by_name and not by_name[ARCHIVE_DIR].isdir():
                raise NotAModel("wrong_members", "model is not a folder")
            for name, limit in zip(ARCHIVE_FILES, (META_LIMIT, WEIGHTS_LIMIT), strict=True):
                m = by_name[name]
                if not m.isfile() or m.size > limit:
                    raise NotAModel("wrong_members", f"{name} is not a regular file within {limit:,} bytes")
            meta = tar.extractfile(by_name["model/meta.pkl"]).read()  # type: ignore[union-attr]
            weights = tar.extractfile(by_name["model/weights.pt"]).read()  # type: ignore[union-attr]
    except NotAModel:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise NotAModel("not_tar_gz", f"not a gzip-compressed tar archive: {exc}") from exc
    meta_globals = pickle_globals(meta)
    _check_globals("model/meta.pkl", meta_globals, META_GLOBALS)
    if b"model_function" not in meta:
        raise NotAModel("no_model_function", "model/meta.pkl has no 'model_function' (medaka checks it when loading)")
    try:
        with zipfile.ZipFile(io.BytesIO(weights)) as z:
            entries = z.namelist()
            data_pkl = [n for n in entries if n.endswith("/data.pkl")]
            if len(data_pkl) != 1 or any(n.startswith("/") or ".." in n.split("/") for n in entries):
                raise NotAModel("weights_unreadable", "model/weights.pt is not a PyTorch weights file")
            weights_globals = pickle_globals(z.read(data_pkl[0]))
    except NotAModel:
        raise
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        raise NotAModel("weights_unreadable", f"model/weights.pt is not a PyTorch zip: {exc}") from exc
    _check_globals("model/weights.pt", weights_globals, WEIGHTS_GLOBALS)
    return {"bytes": size, "members": list(ARCHIVE_FILES), "meta_globals": sorted(set(meta_globals)),
            "weights_globals": sorted(set(weights_globals)), "weights_entries": len(entries)}


def check_file(path: Path, name: str | None = None) -> dict[str, Any]:
    """A model file ARVA may use: its name is one medaka 2.1.1 publishes (PUBLISHED), the archive passes
    inspect_archive, and its SHA-256 and size are those of medaka's published file. Returns the facts; raises
    NotAModel."""
    name = name or name_from_file(path.name)
    if name is None:
        raise NotAModel("bad_name", f"{path.name} is not named <model>{MODEL_SUFFIX} as medaka names its models")
    if name not in PUBLISHED:
        raise NotAModel("unknown_model", f"{name} is not one of the consensus models medaka {MEDAKA_VERSION} "
                                         "publishes that ARVA offers")
    facts = inspect_archive(path)
    sha = sha256_of(path)
    expected, size = PUBLISHED[name]
    if sha != expected or facts["bytes"] != size:
        raise NotAModel("checksum_mismatch", f"SHA-256 {sha} ({facts['bytes']:,} bytes) is not that of medaka "
                                             f"{MEDAKA_TAG}'s {model_file_name(name)} ({expected}, {size:,} bytes)")
    return {**facts, "name": name, "sha256": sha, "published_sha256": expected, "published_bytes": size,
            "info": info(name).as_dict()}


# Run in medaka's own environment (python -I) after check_file: what resolve_model does with a downloaded file
# (models.open_model(...).get_meta('model_function')), plus resolve_model on the path, which must return it unchanged.
LOAD_CHECK_CODE = """
import json, sys
import medaka.models as m
path = sys.argv[1]
resolved = m.resolve_model(path)
with m.open_model(path) as store:
    fn = store.get_meta('model_function')
print(json.dumps({"resolved": resolved, "model_function": repr(fn)[:300]}))
"""


def load_check(executable: str, path: Path, timeout: int = 300) -> dict[str, Any]:
    """medaka's own loading of a model file that passed check_file, in its environment's Python: resolve_model must
    return the path unchanged and open_model must read 'model_function', as medaka does with a model it downloads.
    Raises RuntimeError with medaka's message."""
    import json
    import os
    import subprocess

    from arva_tools.medaka import _python, env_for
    from arva_tools.runner import isolated_home, tool_environment

    py = _python(executable)
    with isolated_home() as home:
        proc = subprocess.run([str(py), "-I", "-c", LOAD_CHECK_CODE, str(path)], capture_output=True, text=True,
                              errors="replace", timeout=timeout, env={**tool_environment(home), **env_for(executable)},
                              cwd=home, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"medaka could not load {path.name}: {proc.stderr.strip()[-300:]}")
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"medaka's load check of {path.name} printed no result") from exc
    if os.path.realpath(out.get("resolved") or "") != os.path.realpath(path):
        raise RuntimeError(f"medaka resolved {path.name} to {out.get('resolved')}, not to the file itself")
    return out
