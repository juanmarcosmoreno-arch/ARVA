"""Medaka models outside the medaka package (arva_tools.medaka_models): the published list, what a model's name says
it was trained for, the archive check that reads the pickles without running them, the published-checksum check,
the -m <file> argument, and (with the real medaka 2.1.1 and a real downloaded model) a polishing run with the file.

The archives built here are CONSTRUCTED: a meta.pkl and a weights.pt with the same layout and pickled globals as
medaka's own files (made with stand-in modules, so medaka is not needed), plus variants that break one rule each.
The real-model test runs only when ARVA_MEDAKA_TEST_MODEL names a downloaded r941_min_hac_g507_model_pt.tar.gz.
"""
from __future__ import annotations

import functools
import hashlib
import io
import os
import pickle
import sys
import tarfile
import types
import zipfile
from collections import OrderedDict
from pathlib import Path

import pytest

from arva_tools import medaka_models as mm
from arva_tools.medaka import MedakaAdapter, MedakaParams, unsafe_for_consensus

HELP = (Path(__file__).parent / "fixtures" / "medaka" / "medaka_consensus_help_2.1.1.txt").read_text()
R941 = "r941_min_hac_g507"


def _stand_ins() -> dict[str, types.ModuleType]:
    mods = {}
    for name in ("medaka", "medaka.models", "medaka.labels", "medaka.features"):
        mods[name] = types.ModuleType(name)

    def build_model_torch(*args, **kwargs):  # pragma: no cover - never called
        return None

    build_model_torch.__module__, build_model_torch.__qualname__ = "medaka.models", "build_model_torch"
    mods["medaka.models"].build_model_torch = build_model_torch

    class HaploidLabelScheme:
        pass

    class CountsFeatureEncoder:
        pass

    HaploidLabelScheme.__module__, HaploidLabelScheme.__qualname__ = "medaka.labels", "HaploidLabelScheme"
    CountsFeatureEncoder.__module__, CountsFeatureEncoder.__qualname__ = "medaka.features", "CountsFeatureEncoder"
    mods["medaka.labels"].HaploidLabelScheme = HaploidLabelScheme
    mods["medaka.features"].CountsFeatureEncoder = CountsFeatureEncoder
    return mods


def meta_pickle(evil: bool = False) -> bytes:
    """medaka's meta.pkl layout: model_function (functools.partial of build_model_torch), label_scheme,
    feature_encoder; `evil` adds a global medaka's files never import."""
    mods = _stand_ins()
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        meta = {"model_function": functools.partial(mods["medaka.models"].build_model_torch, 10, 5, gru_size=128),
                "label_scheme": mods["medaka.labels"].HaploidLabelScheme(),
                "feature_encoder": mods["medaka.features"].CountsFeatureEncoder()}
        if evil:
            meta["x"] = os.system
        return pickle.dumps(meta, protocol=4)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def weights_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("weights/data.pkl", pickle.dumps(OrderedDict(), protocol=2))
        z.writestr("weights/version", "3\n")
    return buf.getvalue()


def model_archive(path: Path, members: dict[str, bytes] | None = None, top_dir: bool = True) -> Path:
    members = members if members is not None else {"model/meta.pkl": meta_pickle(), "model/weights.pt": weights_zip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        if top_dir:
            d = tarfile.TarInfo("model")
            d.type = tarfile.DIRTYPE
            tar.addfile(d)
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def published_as(monkeypatch, name: str, path: Path) -> None:
    """Make `path` the published file of `name` (the constructed archive stands in for medaka's)."""
    monkeypatch.setitem(mm.PUBLISHED, name, (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size))


def test_the_published_list_is_medakas_r941_r103_r104_and_older_r1041_models():
    names = set(mm.PUBLISHED)
    for acc in ("fast", "hac", "sup"):
        assert {f"r941_min_{acc}_g507", f"r941_prom_{acc}_g507", f"r941_e81_{acc}_g514", f"r103_{acc}_g507",
                f"r104_e81_{acc}_g5015"} <= names
    # The deprecated TensorFlow models and the shipped v5.2.0 models are not offered.
    assert "r941_min_high_g360" not in names and "r1041_e82_400bps_sup_v5.2.0" not in names
    assert mm.PUBLISHED[R941] == ("6e87607808bfe7884fc701ded596931afeeb8a59e69bdcb268ef07ac7680ac26", 1502971)
    i = mm.info(R941)
    assert (i.chemistry, i.device, i.accuracy, i.basecaller) == ("R9.4.1", "MinION/GridION", "hac", "Guppy 5.0.7")
    assert i.url == ("https://media.githubusercontent.com/media/nanoporetech/medaka/v2.1.1/medaka/data/"
                     "r941_min_hac_g507_model_pt.tar.gz")
    assert i.medaka_url.startswith("https://github.com/nanoporetech/medaka/raw/master/")
    assert mm.info("r104_e81_sup_g5015").basecaller == "Guppy 5.0.15"
    assert mm.info("r941_e81_hac_g514").chemistry == "R9.4.1 E8.1"
    assert mm.info("r1041_e82_260bps_hac_v4.1.0").chemistry == "R10.4.1 E8.2 260 bps"
    assert mm.info("r1041_e82_260bps_hac_v4.1.0").basecaller == "Dorado basecaller model v4.1.0"
    assert "fast" in mm.info("r103_fast_g507").notes and "plant" in mm.info("r941_sup_plant_g610").notes
    allowed = ["r941_min_hac_g507", "r1041_e82_400bps_sup_v5.2.0"]
    assert [m.name for m in mm.catalogue(allowed, ["r1041_e82_400bps_sup_v5.2.0"])] == ["r941_min_hac_g507"]
    assert mm.LICENCE == "Oxford Nanopore Technologies PLC. Public License Version 1.0"


def test_a_model_archive_is_checked_without_running_it(tmp_path, monkeypatch):
    good = model_archive(tmp_path / "good" / f"{R941}_model_pt.tar.gz")
    facts = mm.inspect_archive(good)
    assert facts["meta_globals"] == ["functools.partial", "medaka.features.CountsFeatureEncoder",
                                     "medaka.labels.HaploidLabelScheme", "medaka.models.build_model_torch"]
    assert facts["weights_globals"] == ["collections.OrderedDict"]
    cases = {
        "unexpected_code": {"model/meta.pkl": meta_pickle(evil=True), "model/weights.pt": weights_zip()},
        "wrong_members": {"model/meta.pkl": meta_pickle(), "model/weights.pt": weights_zip(), "model/x.py": b"1"},
        "no_model_function": {"model/meta.pkl": pickle.dumps({"other": 1}), "model/weights.pt": weights_zip()},
        "weights_unreadable": {"model/meta.pkl": meta_pickle(), "model/weights.pt": b"not a zip"},
    }
    for code, members in cases.items():
        bad = model_archive(tmp_path / code / f"{R941}_model_pt.tar.gz", members)
        with pytest.raises(mm.NotAModel) as exc:
            mm.inspect_archive(bad)
        assert exc.value.code == code, (code, exc.value.detail)
    traversal = model_archive(tmp_path / "trav" / f"{R941}_model_pt.tar.gz",
                              {"../model/meta.pkl": meta_pickle(), "model/weights.pt": weights_zip()})
    with pytest.raises(mm.NotAModel):
        mm.inspect_archive(traversal)
    plain = tmp_path / "plain" / f"{R941}_model_pt.tar.gz"
    plain.parent.mkdir()
    plain.write_bytes(b"<html>a web page</html>")
    with pytest.raises(mm.NotAModel) as exc:
        mm.inspect_archive(plain)
    assert exc.value.code == "not_tar_gz"
    # The published checksum decides: the constructed file is not medaka's, until it stands in for it.
    with pytest.raises(mm.NotAModel) as exc:
        mm.check_file(good)
    assert exc.value.code == "checksum_mismatch"
    published_as(monkeypatch, R941, good)
    assert mm.check_file(good)["name"] == R941
    with pytest.raises(mm.NotAModel) as exc:
        mm.check_file(good.rename(good.with_name("r941_min_high_g360_model_pt.tar.gz")))
    assert exc.value.code == "unknown_model"


def test_a_registered_model_is_passed_to_m_as_its_file(tmp_path):
    reads, draft = tmp_path / "reads.fastq.gz", tmp_path / "draft.fasta"
    reads.write_bytes(b"")
    draft.write_text(">c\nACGT\n")
    f = model_archive(tmp_path / "models" / f"{R941}_model_pt.tar.gz")
    shipped = ["r1041_e82_400bps_hac_v5.2.0", "r1041_e82_400bps_sup_v5.2.0"]
    argv = MedakaAdapter.argv("/env/bin/medaka", MedakaParams(R941, model_file=str(f)), reads, draft, HELP, shipped)
    assert argv[argv.index("-m") + 1] == str(f)
    argv = MedakaAdapter.argv("/env/bin/medaka", MedakaParams(shipped[1]), reads, draft, HELP, shipped)
    assert argv[argv.index("-m") + 1] == shipped[1]
    with pytest.raises(ValueError, match="not one of the models"):
        MedakaAdapter.argv("/env/bin/medaka", MedakaParams(R941), reads, draft, HELP, shipped)
    with pytest.raises(ValueError, match="model_file must be"):
        MedakaParams(R941, model_file="relative.tar.gz").validate()
    with pytest.raises(ValueError, match="model_file must be"):
        MedakaParams(R941, model_file=str(f.with_name("r941_min_sup_g507_model_pt.tar.gz"))).validate()
    # medaka_consensus expands -m unquoted: a path with a space or glob characters is refused, not split or expanded.
    # medaka_consensus expands -m unquoted: a path with a space or glob characters would be split or expanded (the
    # polishing task passes a copy in the job's work folder instead, and refuses one such path there).
    for folder in ("my models", "m*dels", "m?dels", "[m]odels", "tab\tmodels"):
        assert unsafe_for_consensus(f"/data/{folder}/{f.name}")
    assert not unsafe_for_consensus(str(f))
    with pytest.raises(ValueError, match="ships"):
        MedakaAdapter.argv("/env/bin/medaka", MedakaParams(shipped[1], model_file=str(
            f.with_name(f"{shipped[1]}_model_pt.tar.gz"))), reads, draft, HELP, shipped)
    # The deprecated g360 model is not in medaka 2.1.1's choices.
    assert "r941_min_high_g360" not in HELP and R941 in HELP


REAL_MODEL = os.environ.get("ARVA_MEDAKA_TEST_MODEL")
MEDAKA = Path.home() / ".arva-tools" / "conda" / "medaka" / "bin" / "medaka"


@pytest.mark.skipif(not (REAL_MODEL and Path(REAL_MODEL).is_file() and MEDAKA.is_file()),
                    reason="needs medaka 2.1.1 and ARVA_MEDAKA_TEST_MODEL (a downloaded r941_min_hac_g507 file)")
def test_the_downloaded_r941_model_passes_the_checks_and_medaka_loads_it():
    path = Path(REAL_MODEL)
    facts = mm.check_file(path)
    assert facts["sha256"] == mm.PUBLISHED[R941][0] and facts["weights_globals"] == [
        "collections.OrderedDict", "torch.FloatStorage", "torch._utils._rebuild_tensor_v2"]
    loaded = mm.load_check(str(MEDAKA), path)
    assert loaded["resolved"] == str(path) and "build_model_torch" in loaded["model_function"]
