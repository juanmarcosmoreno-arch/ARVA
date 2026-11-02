"""app.services.image_platform: the image architecture from the launcher's variables and this process's machine.
The variables are CONSTRUCTED as scripts/start.sh writes them (tests/test_start_script.py checks the script)."""
from app.services import image_platform
from app.services.host import Fact, HostFacts

APPLE = HostFacts(platform=Fact("macos", "launcher"), arch=Fact("arm64", "launcher"))
LAUNCHER = {"ARVA_HOST_IMAGE_PLATFORM": "linux/amd64", "ARVA_HOST_IMAGE_REASON": "rosetta_on",
            "ARVA_HOST_DOCKER_ROSETTA": "on", "ARVA_HOST_IMAGE_SOURCE": "published"}


def test_amd64_image_on_apple_silicon_is_translated_by_rosetta():
    info = image_platform.describe(APPLE, LAUNCHER, machine="x86_64", with_tools=False)
    assert info == {"running": "linux/amd64", "chosen": "linux/amd64", "reason": "rosetta_on", "rosetta": "on",
                    "source": "published", "host_arch": "arm64", "emulated": True, "mismatch": False,
                    "unavailable_tools": []}
    assert "translated: an amd64 image on an arm64 computer, through Rosetta" in image_platform.text_lines(info)[0]
    off = image_platform.describe(APPLE, {**LAUNCHER, "ARVA_HOST_DOCKER_ROSETTA": "off"}, "x86_64", False)
    assert "QEMU (Rosetta está desactivado)" in image_platform.text_lines(off, "es")[0]


def test_native_arm64_lists_the_tools_without_an_arm64_build(monkeypatch):
    monkeypatch.setattr(image_platform, "unavailable_tools", lambda running: ["bakta", "mobsuite"])
    info = image_platform.describe(APPLE, {**LAUNCHER, "ARVA_HOST_IMAGE_PLATFORM": "linux/arm64",
                                           "ARVA_HOST_IMAGE_REASON": "rosetta_off"}, machine="aarch64")
    assert (info["running"], info["emulated"], info["mismatch"]) == ("linux/arm64", False, False)
    assert image_platform.text_lines(info)[-1] == "  Not available on this architecture: bakta, mobsuite"


def test_unknown_or_malformed_values_are_dropped_and_a_mismatch_is_reported():
    info = image_platform.describe(HostFacts(), {"ARVA_HOST_IMAGE_PLATFORM": "linux/arm64",
                                                 "ARVA_HOST_IMAGE_REASON": "$(reboot)", "ARVA_HOST_IMAGE_SOURCE": "x"},
                                   machine="x86_64", with_tools=False)
    assert (info["reason"], info["source"], info["emulated"], info["mismatch"]) == (None, None, None, True)
    assert "chose linux/arm64, but the containers run linux/amd64" in image_platform.text_lines(info)[1]


def test_unavailable_tools_comes_from_detection(monkeypatch):
    from arva_tools.base import DetectedTool, ToolStatus
    from arva_tools.registry import ADAPTERS

    def fake(tool_id, refresh=False):
        info = ADAPTERS[tool_id].info
        if tool_id in ("mobsuite", "prokka"):
            return DetectedTool(info, ToolStatus.not_installed,
                                reason="no_conda_platform" if tool_id == "mobsuite" else "not_found")
        return DetectedTool(info, ToolStatus.available, "/x", "1")

    monkeypatch.setattr("arva_tools.registry.detect", fake)
    assert image_platform.unavailable_tools("linux/arm64") == ["prokka", "mobsuite"]
    assert image_platform.unavailable_tools("linux/amd64") == ["mobsuite"]
