"""Host detection parsers and the profile table.

Every sysctl, system_profiler, sw_vers and cgroup input below is CONSTRUCTED for these tests from the formats
documented by Apple, the Linux kernel and the open-source code cited in app/services/host.py; none is output copied
from a real machine, and none of this has run on a Mac.
"""
import json
from pathlib import Path

import pytest

from app.services import host as h
from app.services import performance as perf

GIB = 1024**3


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def facts(**values) -> h.HostFacts:
    return h.HostFacts(**{k: h.Fact(v, "launcher") for k, v in values.items()})


def container(cpus=8, memory_gb=16.0, in_container=True) -> h.ContainerFacts:
    return h.ContainerFacts(usable_cpus=cpus, cpus_source="affinity", memory_bytes=int(memory_gb * GIB),
                            memory_source="meminfo", in_container=in_container,
                            container_marker="docker" if in_container else None)


# --- cgroup and /proc parsers -----------------------------------------------------------------------------------

def test_cgroup_v2_quota_and_memory_limit(tmp_path):
    write(tmp_path, "proc/self/cgroup", "0::/\n")
    write(tmp_path, "sys/fs/cgroup/cpu.max", "250000 100000\n")
    write(tmp_path, "sys/fs/cgroup/memory.max", f"{6 * GIB}\n")
    write(tmp_path, "proc/meminfo", "MemTotal:       16384000 kB\nMemFree:  1 kB\n")
    write(tmp_path, ".dockerenv", "")
    c = h.read_container(tmp_path, {}, affinity=lambda: (8, "affinity"))
    assert (c.usable_cpus, c.cpus_source) == (3, "cgroup_v2")  # 2.5 CPUs of quota round up to 3
    assert (c.memory_bytes, c.memory_source) == (6 * GIB, "cgroup_v2")
    assert (c.in_container, c.container_marker) == (True, "docker")


def test_cgroup_v2_without_limits_uses_affinity_and_meminfo(tmp_path):
    write(tmp_path, "proc/self/cgroup", "0::/\n")
    write(tmp_path, "sys/fs/cgroup/cpu.max", "max 100000\n")
    write(tmp_path, "sys/fs/cgroup/memory.max", "max\n")
    write(tmp_path, "proc/meminfo", "MemTotal:       8000000 kB\n")
    c = h.read_container(tmp_path, {}, affinity=lambda: (4, "affinity"))
    assert (c.usable_cpus, c.cpus_source, c.memory_bytes, c.memory_source) == (4, "affinity", 8000000 * 1024, "meminfo")
    assert c.in_container is False


def test_cgroup_v2_nested_path_takes_the_tightest_ancestor(tmp_path):
    write(tmp_path, "proc/self/cgroup", "0::/user.slice/job\n")
    write(tmp_path, "sys/fs/cgroup/user.slice/job/cpu.max", "max 100000\n")
    write(tmp_path, "sys/fs/cgroup/user.slice/cpu.max", "100000 100000\n")
    write(tmp_path, "sys/fs/cgroup/user.slice/job/memory.max", f"{3 * GIB}\n")
    write(tmp_path, "sys/fs/cgroup/user.slice/memory.max", f"{5 * GIB}\n")
    c = h.read_container(tmp_path, {}, affinity=lambda: (16, "affinity"))
    assert (c.usable_cpus, c.memory_bytes) == (1, 3 * GIB)


def test_cgroup_v1_quota_and_limit(tmp_path):
    write(tmp_path, "proc/self/cgroup", "4:memory:/docker/abc\n2:cpu,cpuacct:/docker/abc\n0::/\n")
    # Inside the container's namespace the controllers are mounted at their own cgroup.
    write(tmp_path, "sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us", "200000\n")
    write(tmp_path, "sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us", "100000\n")
    write(tmp_path, "sys/fs/cgroup/memory/memory.limit_in_bytes", f"{2 * GIB}\n")
    write(tmp_path, "proc/meminfo", "MemTotal:       16000000 kB\n")
    c = h.read_container(tmp_path, {"container": "podman"}, affinity=lambda: (8, "affinity"))
    assert (c.usable_cpus, c.cpus_source, c.memory_bytes, c.memory_source) == (2, "cgroup_v1", 2 * GIB, "cgroup_v1")
    assert c.container_marker == "podman"


def test_cgroup_v1_unlimited(tmp_path):
    write(tmp_path, "proc/self/cgroup", "3:memory:/\n2:cpu,cpuacct:/\n")
    write(tmp_path, "sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us", "-1\n")
    write(tmp_path, "sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us", "100000\n")
    write(tmp_path, "sys/fs/cgroup/memory/memory.limit_in_bytes", "9223372036854771712\n")
    write(tmp_path, "proc/meminfo", "MemTotal:       4000000 kB\n")
    c = h.read_container(tmp_path, {}, affinity=lambda: (2, "affinity"))
    assert (c.usable_cpus, c.memory_bytes, c.memory_source) == (2, 4000000 * 1024, "meminfo")


@pytest.mark.parametrize(("text", "cpus"), [("max 100000", None), ("50000 100000", 0.5), ("x y", None), ("", None),
                                            ("0 100000", None), ("100000", None)])
def test_parse_cpu_max(text, cpus):
    assert h.parse_cpu_max(text) == cpus


def test_parse_memory_limit_and_meminfo():
    assert h.parse_memory_limit("max") is None and h.parse_memory_limit("abc") is None
    assert h.parse_memory_limit(" 1048576\n") == 1048576
    assert h.parse_meminfo("Foo: 1 kB\n") is None
    assert h.parse_meminfo("MemTotal: 2 kB") == 2048


# --- Launcher variables (untrusted) -----------------------------------------------------------------------------

def test_launcher_values_are_validated_and_bounded():
    env = {
        "ARVA_HOST_PLATFORM": "macos", "ARVA_HOST_MODEL_NAME": "MacBook\x1b[31m Air" + "x" * 200,
        "ARVA_HOST_MODEL_ID": "Mac14,2", "ARVA_HOST_CHIP": "Apple M2", "ARVA_HOST_PERF_CORES": "4",
        "ARVA_HOST_EFF_CORES": "4", "ARVA_HOST_PHYSICAL_CORES": "8", "ARVA_HOST_LOGICAL_CPUS": "8",
        "ARVA_HOST_MEMORY_BYTES": str(16 * GIB), "ARVA_HOST_OS_VERSION": "14.5", "ARVA_HOST_ARCH": "arm64",
        "ARVA_HOST_DOCKER_CPUS": "8", "ARVA_HOST_DOCKER_MEMORY_BYTES": str(8 * GIB),
    }
    f = h.read_launcher(env)
    assert f.is_mac and f.model_name.source == "launcher"
    assert f.model_name.value.startswith("MacBook [31m Air") and len(f.model_name.value) == h.MAX_TEXT
    assert (f.performance_cores.value, f.efficiency_cores.value, f.memory_bytes.value) == (4, 4, 16 * GIB)
    bad = h.read_launcher({"ARVA_HOST_PLATFORM": "windows", "ARVA_HOST_PERF_CORES": "-4", "ARVA_HOST_EFF_CORES": "4x",
                           "ARVA_HOST_MEMORY_BYTES": "1" * 30, "ARVA_HOST_OS_VERSION": "14.5; rm -rf /",
                           "ARVA_HOST_ARCH": "ppc", "ARVA_HOST_LOGICAL_CPUS": "100000", "ARVA_HOST_MODEL_NAME": " \t"})
    assert not any(fact.known for fact in vars(bad).values())
    assert not any(fact.known for fact in vars(h.read_launcher({k: "" for k in env})).values())


# --- Native macOS (constructed sysctl / system_profiler / sw_vers outputs) ---------------------------------------

def fake_mac(values: dict[str, str], profiler: dict | None, version: str | None = "14.5", noise: str = ""):
    def run(argv):
        if argv[0] == h.SYSCTL:
            return values.get(argv[2])
        if argv[0] == h.SYSTEM_PROFILER:
            return None if profiler is None else noise + json.dumps({"SPHardwareDataType": [profiler]}, indent=2)
        if argv[0] == h.SW_VERS:
            return version
        raise AssertionError(argv)
    return run


APPLE_SILICON = {"hw.model": "Mac14,2", "machdep.cpu.brand_string": "Apple M2", "hw.nperflevels": "2",
                 "hw.perflevel0.physicalcpu": "4", "hw.perflevel1.physicalcpu": "4", "hw.physicalcpu": "8",
                 "hw.logicalcpu": "8", "hw.memsize": str(16 * GIB), "sysctl.proc_translated": "0"}
PROFILER_AIR = {"_name": "hardware_overview", "machine_name": "MacBook Air", "machine_model": "Mac14,2",
                "chip_type": "Apple M2", "number_processors": "proc 8:4:4", "serial_number": "NOT-READ"}


def test_macos_apple_silicon():
    f = h.read_macos(fake_mac(APPLE_SILICON, PROFILER_AIR, noise="2026-03-25 11:28:17 system_profiler[1:2] note\n"))
    assert (f.model_name.value, f.model_id.value, f.chip.value) == ("MacBook Air", "Mac14,2", "Apple M2")
    assert (f.performance_cores.value, f.efficiency_cores.value, f.physical_cores.value) == (4, 4, 8)
    assert (f.memory_bytes.value, f.os_version.value, f.model_name.source) == (16 * GIB, "14.5", "macos")
    assert "NOT-READ" not in repr(f)


def test_macos_older_apple_silicon_falls_back_to_system_profiler_cores():
    values = {k: v for k, v in APPLE_SILICON.items() if "perflevel" not in k}
    f = h.read_macos(fake_mac(values, {**PROFILER_AIR, "number_processors": "proc 10:8:2"}, version="11.7.10"))
    assert (f.performance_cores.value, f.efficiency_cores.value, f.os_version.value) == (8, 2, "11.7.10")


def test_macos_intel_and_rosetta():
    intel = {"hw.model": "MacBookPro16,1", "machdep.cpu.brand_string": "Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz",
             "hw.physicalcpu": "6", "hw.logicalcpu": "12", "hw.memsize": str(16 * GIB)}
    f = h.read_macos(fake_mac(intel, {"machine_name": "MacBook Pro", "number_processors": 6}))
    assert (f.performance_cores.known, f.efficiency_cores.known, f.physical_cores.value) == (False, False, 6)
    assert f.chip.value.startswith("Intel(R) Core(TM)") and f.model_name.value == "MacBook Pro"
    assert h.read_macos(fake_mac({"sysctl.proc_translated": "1"}, None)).arch.value == "arm64"


def test_macos_with_nothing_readable():
    f = h.read_macos(fake_mac({}, None, version=None))
    assert f.is_mac and [n for n, x in vars(f).items() if x.known and n != "arch"] == ["platform"]
    assert h.parse_system_profiler("not json") == {} and h.parse_system_profiler('{"SPHardwareDataType": []}') == {}


def test_native_macos_reading_wins_over_the_launcher(tmp_path):
    env = {"ARVA_HOST_PLATFORM": "macos", "ARVA_HOST_MODEL_NAME": "Mac Studio", "ARVA_HOST_DOCKER_CPUS": "6"}
    d = h.detect(tmp_path, env, platform="darwin", run=fake_mac(APPLE_SILICON, PROFILER_AIR),
                 affinity=lambda: (8, "cpu_count"))
    assert (d.host.model_name.value, d.host.model_name.source) == ("MacBook Air", "macos")
    assert (d.host.docker_cpus.value, d.host.docker_cpus.source) == (6, "launcher")
    assert (d.container.memory_bytes, d.container.memory_source, d.container.in_container) == (16 * GIB, "macos", False)


# --- Profiles (ARVA's heuristics) -------------------------------------------------------------------------------

@pytest.mark.parametrize(("name", "model_id", "profile"), [
    ("MacBook Air", "Mac14,2", "light"),
    (None, "MacBookAir10,1", "light"),
    ("MacBook", "MacBook10,1", "light"),
    ("MacBook Pro", "Mac14,7", "balanced"),
    ("Mac mini", None, "balanced"),
    (None, "iMacPro1,1", "balanced"),
    ("iMac", "iMac21,1", "balanced"),
    ("Mac Studio", "Mac13,1", "maximum"),
    (None, "MacPro7,1", "maximum"),
])
def test_automatic_profile_by_mac_family(name, model_id, profile):
    values = {"platform": "macos", **({"model_name": name} if name else {}), **({"model_id": model_id} if model_id else {})}
    assert perf.automatic_profile(facts(**values), container())[0] == profile


@pytest.mark.parametrize(("cpus", "memory", "profile", "reason"), [
    (4, 64, "light", "few_resources"), (8, 6, "light", "few_resources"), (8, 16, "balanced", "default"),
    (16, 64, "maximum", "many_resources"), (16, 16, "balanced", "default"),
])
def test_automatic_profile_of_unknown_computers(cpus, memory, profile, reason):
    assert perf.automatic_profile(h.HostFacts(), container(cpus, memory)) == (profile, reason)
    # A Mac whose family is unknown ("Mac14,2" without a model name) is judged the same way.
    assert perf.automatic_profile(facts(platform="macos", model_id="Mac14,2"), container(cpus, memory))[0] == profile


@pytest.mark.parametrize(("profile", "cores", "eff", "threads"), [
    ("light", 4, 4, 2), ("light", 1, 0, 1), ("light", 8, 2, 4),
    ("balanced", 8, 2, 6), ("balanced", 4, 0, 3), ("balanced", 1, 0, 1), ("balanced", 12, 4, 9),
    ("maximum", 8, 2, 8), ("maximum", 6, 0, 5), ("maximum", 1, 0, 1), ("maximum", 16, 8, 16),
])
def test_profile_threads(profile, cores, eff, threads):
    assert perf.profile_threads(profile, cores, eff) == threads


def table_row(host: h.HostFacts, c: h.ContainerFacts, choice=None, **caps):
    r = perf.compute(h.Detection(host, c), choice or {"profile": "auto"}, **caps)
    return r.profile, r.threads, r.max_threads, r.memory_gb, r.max_memory_gb, r.nice


M2_AIR = facts(platform="macos", model_name="MacBook Air", performance_cores=4, efficiency_cores=4,
               logical_cpus=8, memory_bytes=16 * GIB)
M1_PRO = facts(platform="macos", model_name="MacBook Pro", performance_cores=8, efficiency_cores=2,
               logical_cpus=10, memory_bytes=32 * GIB)
STUDIO = facts(platform="macos", model_name="Mac Studio", performance_cores=16, efficiency_cores=8,
               logical_cpus=24, memory_bytes=128 * GIB)
INTEL = facts(platform="macos", model_name="iMac", physical_cores=6, logical_cpus=12, memory_bytes=32 * GIB)


@pytest.mark.parametrize(("host", "c", "row"), [
    (M2_AIR, container(8, 7.7), ("light", 2, 8, 3, 7, 15)),
    (M1_PRO, container(10, 15.6), ("balanced", 6, 10, 10, 15, 10)),
    (M1_PRO, container(4, 15.6), ("balanced", 4, 4, 10, 15, 10)),  # Docker Desktop gives fewer CPUs: capped
    (STUDIO, container(24, 96), ("maximum", 16, 24, 81, 96, 5)),
    (INTEL, container(12, 16), ("balanced", 5, 12, 11, 16, 10)),
    (h.HostFacts(), container(8, 16, in_container=False), ("balanced", 6, 8, 11, 16, 10)),
])
def test_profile_table(host, c, row):
    assert table_row(host, c) == row


def test_explicit_custom_and_admin_caps():
    c = container(8, 16)
    assert table_row(M2_AIR, c, {"profile": "maximum"}) == ("maximum", 4, 8, 13, 16, 5)
    r = perf.compute(h.Detection(M2_AIR, c), {"profile": "custom", "threads": 12, "memory_gb": 20})
    assert (r.threads, r.memory_gb, r.exceeds, r.nice) == (8, 16, ["threads", "memory_gb"], 10)
    assert table_row(M2_AIR, c, {"profile": "maximum"}, admin_threads=2, admin_memory_gb=4) == (
        "maximum", 2, 2, 4, 4, 5)
    assert perf.compute(h.Detection(M2_AIR, c), {"profile": "auto"}).cap_threads(99) == 8


@pytest.mark.parametrize("value", [None, {}, {"profile": "turbo"}, {"profile": "custom"},
                                   {"profile": "custom", "threads": 0, "memory_gb": 4},
                                   {"profile": "custom", "threads": 2, "memory_gb": 5000},
                                   {"profile": "custom", "threads": True, "memory_gb": 4},
                                   {"profile": "custom", "threads": "2", "memory_gb": 4}])
def test_invalid_choices(value):
    with pytest.raises(ValueError):
        perf.validate_choice(value)


def test_validate_choice_keeps_only_what_the_profile_uses():
    assert perf.validate_choice({"profile": "light", "threads": 3}) == {"profile": "light"}
    assert perf.validate_choice({"profile": "custom", "threads": 3, "memory_gb": 6, "x": 1}) == {
        "profile": "custom", "threads": 3, "memory_gb": 6}


# --- Docker Desktop recommendation -------------------------------------------------------------------------------

def advice(host, c, choice=None):
    det = h.Detection(host, c)
    return perf.docker_advice(det, perf.compute(det, choice or {"profile": "auto"}))


def test_docker_advice_for_a_mac():
    air = advice(M2_AIR, container(8, 7.7))
    assert air["status"] == "ok" and air["cpus"] == {"current": 8, "recommended": 3, "status": "ok"}
    assert air["memory"]["recommended_gb"] == 8 and air["memory"]["status"] == "ok"
    pro = advice(M1_PRO, container(2, 4))
    assert pro["status"] == "adjust"
    assert (pro["cpus"]["recommended"], pro["cpus"]["status"]) == (7, "increase")
    assert (pro["memory"]["recommended_gb"], pro["memory"]["status"]) == (19, "increase")
    greedy = advice(M1_PRO, container(10, 30))
    assert greedy["memory"]["status"] == "decrease" and greedy["memory"]["most_gb"] == 24
    # Docker Desktop's own figures, when the launcher passed them, take precedence over the container's view.
    with_docker = facts(**{k: v.value for k, v in vars(M1_PRO).items() if v.known}, docker_cpus=8,
                        docker_memory_bytes=20 * GIB)
    assert advice(with_docker, container(2, 4))["status"] == "ok"


def test_docker_advice_without_host_facts_or_container():
    assert advice(h.HostFacts(), container())["status"] == "host_unknown"
    assert advice(M2_AIR, container(in_container=False))["status"] == "not_container"


def test_text_report_in_both_languages():
    det = h.Detection(M1_PRO, container(2, 4))
    res = perf.compute(det, {"profile": "auto"})
    en = perf.text_report(det, res, "en")
    assert "MacBook Pro · 8 performance + 2 efficiency cores · 32 GB" in en
    assert "In use: Balanced (automatic) → 2 threads per tool" in en
    assert "CPU limit: now 2; set it to 7" in en and "Memory limit: now 4.0 GB; set it to 19 GB" in en
    es = perf.text_report(det, res, "es")
    assert "En uso: Equilibrado (automático)" in es and "Memory limit: ahora 4,0 GB; ponlo en 19 GB" in es
    unknown = perf.text_report(h.Detection(h.HostFacts(), container()), perf.compute(
        h.Detection(h.HostFacts(), container()), {"profile": "auto"}), "en")
    assert "Computer: unknown" in unknown and "Recommendation" not in unknown


def test_out_of_memory_reason():
    record = perf.compute(h.Detection(M2_AIR, container(8, 7.7)), {"profile": "auto"}).record(2, 3, "-m")
    text = perf.out_of_memory_reason("SPAdes", record)
    assert text.startswith("SPAdes was stopped by the operating system with SIGKILL")
    assert "ARVA could use 7.7 GB of memory here (the container's limit); this job ran with 2 thread(s), a memory " \
           "limit of 3 GB (light profile)" in text
    assert "lighter performance profile or fewer threads" in text and "Docker Desktop more memory" in text
    native = perf.out_of_memory_reason("Flye", {**record, "in_container": False, "memory_limit_gb": None})
    assert "Docker" not in native and "memory limit" not in native.split("SIGKILL")[1].split("Choose")[0]
