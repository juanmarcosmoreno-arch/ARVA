import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobResources } from "@/components/domain/JobResources";
import { PerformanceSection } from "@/components/settings/PerformanceSection";
import { api } from "@/lib/api";
import { profileRequest, resourcesLine } from "@/lib/performance";
import type { AnalysisJob, HostFact, HostFactKey, PerformanceOverview } from "@/lib/types";
import { useSettings } from "@/store/settings";
import { dictionaries, interpolate, type TranslationKey } from "@/i18n";

const GIB = 1024 ** 3;
const launcher = (value: string | number | null): HostFact => ({ value, source: value === null ? null : "launcher" });

// A CONSTRUCTED MacBook Pro whose Docker Desktop gives ARVA 4 CPUs and 7.7 GB (the API computes these values).
const mac: PerformanceOverview = {
  host: {
    platform: launcher("macos"), model_name: launcher("MacBook Pro"), model_id: launcher("MacBookPro18,3"), chip: launcher("Apple M1 Pro"),
    performance_cores: launcher(8), efficiency_cores: launcher(2), physical_cores: launcher(10), logical_cpus: launcher(10),
    memory_bytes: launcher(32 * GIB), os_version: launcher("14.5"), arch: launcher("arm64"), docker_cpus: launcher(4),
    docker_memory_bytes: launcher(8 * GIB),
  },
  mac_class: "macbook_pro",
  container: { usable_cpus: 4, cpus_source: "affinity", memory_bytes: 7.7 * GIB, memory_source: "meminfo", in_container: true, container_marker: "docker" },
  automatic: { profile: "balanced", reason: "macbook_pro", core_basis: "performance_cores", cores: 8 },
  choice: { profile: "auto", threads: null, memory_gb: null, updated_at: null },
  effective: {
    profile: "balanced", choice: "auto", threads: 4, max_threads: 4, memory_gb: 5, max_memory_gb: 7, nice: 10, usable_cpus: 4,
    usable_memory_gb: 7.7, requested_threads: 6, requested_memory_gb: 5, exceeds: ["threads"], admin_threads: null,
    admin_memory_gb: null, host: "MacBook Pro (MacBookPro18,3) · Apple M1 Pro · 8 performance + 2 efficiency cores · 32 GB · macOS 14.5",
  },
  profiles: [
    { profile: "light", threads: 4, memory_gb: 3, nice: 15 },
    { profile: "balanced", threads: 4, memory_gb: 5, nice: 10 },
    { profile: "maximum", threads: 4, memory_gb: 6, nice: 5 },
  ],
  docker: {
    status: "adjust",
    cpus: { current: 4, recommended: 7, status: "increase" },
    memory: { current_bytes: 8 * GIB, recommended_gb: 19, most_gb: 24, status: "increase" },
  },
};

const unknownHost = Object.fromEntries(Object.keys(mac.host).map((k) => [k, { value: null, source: null }])) as Record<HostFactKey, HostFact>;

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PerformanceSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("Performance section", () => {
  it("shows the detected Mac with sources, the automatic profile and the Docker Desktop recommendation", async () => {
    vi.spyOn(api, "performance").mockResolvedValue(mac);
    renderSection();
    expect(await screen.findByText("MacBook Pro (MacBookPro18,3)")).toBeInTheDocument();
    expect(screen.getByText("8 performance + 2 efficiency")).toBeInTheDocument();
    expect(screen.getAllByText("from the launcher (scripts/start.sh)").length).toBeGreaterThan(3);
    expect(screen.getByText(/CPUs this process may use; memory the system reports · in a container \(docker\)/)).toBeInTheDocument();
    expect(screen.getByText(/MacBook Pro: a laptop with a fan/)).toBeInTheDocument();
    expect(screen.getByText("ARVA heuristic")).toBeInTheDocument();
    expect(screen.getByText("Threads are counted from its 8 performance cores.")).toBeInTheDocument();
    expect(screen.getByText("ARVA's choice for this computer: Balanced.")).toBeInTheDocument();
    const alerts = screen.getAllByRole("alert");
    expect(within(alerts[0]).getByText(/asks for more than ARVA can use here \(6 threads, 4 CPUs\)/)).toBeInTheDocument();
    expect(within(alerts[1]).getByText("CPU limit: now 4; set it to 7.")).toBeInTheDocument();
    expect(within(alerts[1]).getByText("Memory limit: now 8.00 GB; set it to 19 GB.")).toBeInTheDocument();
    expect(within(alerts[1]).getByText(/Settings → Resources → Advanced/)).toBeInTheDocument();
    expect(screen.getByText(/Flye, Racon, minimap2, BWA, QUAST, Bakta, Prokka/)).toBeInTheDocument();
  });

  it("saves a custom profile only within what ARVA can use", async () => {
    vi.spyOn(api, "performance").mockResolvedValue(mac);
    const save = vi.spyOn(api, "setPerformance").mockResolvedValue({ ...mac, choice: { profile: "custom", threads: 2, memory_gb: 3, updated_at: "now" } });
    renderSection();
    fireEvent.click(await screen.findByRole("radio", { name: /Custom/ }));
    const threads = screen.getByRole("spinbutton", { name: /Threads per tool/ });
    const memory = screen.getByRole("spinbutton", { name: /Memory per job/ });
    expect(threads).toHaveAttribute("max", "4");
    expect(memory).toHaveAttribute("max", "7");
    fireEvent.change(threads, { target: { value: "9" } });
    expect(screen.getByText("Threads: a whole number from 1 to 4.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(threads, { target: { value: "2" } });
    fireEvent.change(memory, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ profile: "custom", threads: 2, memory_gb: 3 }));
  });

  it("speaks Spanish and explains an unknown computer", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "performance").mockResolvedValue({
      ...mac, host: unknownHost, mac_class: null,
      container: { ...mac.container, in_container: false, container_marker: null, cpus_source: "cgroup_v2", memory_source: "cgroup_v2" },
      automatic: { profile: "light", reason: "few_resources", core_basis: "usable_cpus", cores: 4 },
      effective: { ...mac.effective, profile: "light", exceeds: [] },
      docker: { status: "not_container" },
    });
    renderSection();
    expect(await screen.findByText(/El equipo es desconocido: ARVA no se inició con scripts\/start.sh/)).toBeInTheDocument();
    expect(screen.getByText(/cuota de CPU del contenedor; límite de memoria del contenedor/)).toBeInTheDocument();
    expect(screen.getByText(/4 núcleos o menos, o menos de 8 GB de memoria/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^Ligero/ })).toBeInTheDocument();
    expect(screen.getByText("ARVA se ejecuta directamente en este equipo, no en Docker.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Job resources", () => {
  const t = (key: TranslationKey, vars?: Record<string, string | number>) => interpolate(dictionaries.en[key], vars);
  const resources = {
    profile: "light", choice: "auto", threads: 2, memory_gb: 3, memory_limit_gb: 3, memory_option: "-m", nice: 15,
    nice_executable: "/usr/bin/nice", usable_cpus: 8, usable_memory_gb: 7.7, in_container: true, host: "MacBook Air · Apple M2",
  } as const;

  it("describes what a job was given", () => {
    expect(resourcesLine(t, resources)).toBe(
      "Light profile (automatic) · 2 threads · memory limit 3 GB (-m) · CPU priority nice 15 · ARVA could use 8 CPUs and 7.7 GB · computer: MacBook Air · Apple M2",
    );
    expect(resourcesLine(t, { ...resources, nice_executable: null, memory_limit_gb: null, host: "unknown computer" })).toContain(
      "CPU priority not lowered (nice 15 asked; the nice program was not found) · ARVA could use 8 CPUs and 7.7 GB · computer: unknown",
    );
  });

  it("shows nothing for jobs ARVA ran in its own process", () => {
    useSettings.setState({ language: "es" });
    const { container, rerender } = render(<JobResources job={{ resources: null } as AnalysisJob} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<JobResources job={{ resources } as unknown as AnalysisJob} />);
    expect(screen.getByText("Recursos")).toBeInTheDocument();
    expect(screen.getByText(/perfil Ligero \(automático\) · 2 hilos/)).toBeInTheDocument();
  });

  it("validates a custom request at the boundary", () => {
    expect(profileRequest({ profile: "maximum", threads: "x", memory: "" }, mac)).toEqual({ body: { profile: "maximum" }, problems: [] });
    expect(profileRequest({ profile: "custom", threads: "2.5", memory: "8" }, mac).problems).toEqual(["perf.problem.threads", "perf.problem.memory"]);
  });
});
