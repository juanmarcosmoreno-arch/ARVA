import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VfdbDialog } from "@/components/databases/VfdbDialog";
import { VirulenceCard, VirulenceDialog } from "@/components/genomic/Virulence";
import { ParamPanel } from "@/components/workflows/ParamPanel";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { api } from "@/lib/api";
import type { AnalysisJob, Assembly, VfdbPlan, VirulenceDatabase, VirulencePlan, VirulenceRun, VirulenceSample } from "@/lib/types";
import type { NodeKind } from "@/lib/workflows";
import { useSettings } from "@/store/settings";

// VFDB's full set B as the virulence screen's optional database. The values are those of VFDB's server on 2026-11-06
// (VFDB_setB_nt.fas.gz: 10,685,329 bytes, Last-Modified Fri, 06 Nov 2026 11:30:33 GMT) and of ABRicate 1.4.0's
// bundled core set A (index date 2026-04-03).
function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const assembly = {
  id: "asm-00001", sample_id: "s", job_id: "job-flye", kind: "assembly", parent_assembly_id: null, assembler: "Flye", assembler_version: "2.9.3",
  mode: "long", read_type: "nano-hq", input_file_ids: [], created_at: "2026-10-28T13:00:00Z",
  stats: { contig_count: 1, total_length: 2_821_361, circularity: { contigs_with_circularity: 1, circular_contigs: 1 } }, warnings: [],
} as unknown as Assembly;

const db = (over: Partial<VirulenceDatabase>): VirulenceDatabase => ({
  id: "db-a", key: "abricate-vfdb", kind: "vfdb", name: "VFDB core set A (bundled with ABRicate 1.4.0)", version: "2026-04-03", version_source: "file",
  checksum: "sha256:aa", path: "/env/db/vfdb", host_path: "/env/db/vfdb", is_default: true, status: "registered", available: true, unavailable_reason: null,
  bundled: true, licence: "CC BY-NC 4.0", licence_url: "https://creativecommons.org/licenses/by-nc/4.0/", citation: "Zhou S.Y. et al. (2025) VFDB 2025", unconfirmed: [],
  compatibility: { status: "compatible", code: "bundled_with_tool", params: { tool: "ABRicate" } },
  vfdb_set: "A", dataset: "core", vfdb: { set: "A", dataset: "core", version: "2026-04-03" }, ...over,
}) as VirulenceDatabase;

const setA = db({});
const setB = db({ id: "db-b", key: "vfdb-setB", name: "VFDB full (set B)", version: "2026-11-06", is_default: false, bundled: false, path: "/db/vfdb-setB/2026-11-06/vfdb_setB",
  host_path: "/db/vfdb-setB/2026-11-06/vfdb_setB", vfdb_set: "B", dataset: "full", vfdb: { set: "B", dataset: "full", version: "2026-11-06" } });

const plan = (database: VirulenceDatabase): VirulencePlan => ({
  tool: { status: "available", version: "1.4.0", version_validated: true, message: "", reason: null, path: "/env/bin/abricate", license: "GPL-2.0",
    citation: "Seemann T. ABRicate", citation_url: "https://github.com/tseemann/abricate", max_threads: 4, default_threads: 4 } as VirulencePlan["tool"],
  database, databases: [setA, setB], defaults: { database: "vfdb", minid: "80", mincov: "80" }, tool_defaults: { minid: "80", mincov: "80" }, defaults_match: true,
  assembly: { assembly_id: "asm-00001", kind: "assembly", assembler: "Flye", assembler_version: "2.9.3", parent_assembly_id: null, contigs: 1, total_length: 2_821_361, synthetic_evidence: [] },
  problems: [],
});

beforeEach(() => {
  useSettings.setState({ language: "en" });
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("virulence dialog", () => {
  it("defaults to the bundled core set A, offers a registered full set B and runs the one chosen", async () => {
    const preview = vi.spyOn(api, "virulencePreview").mockImplementation(async (_a, id) => plan(id === "db-b" ? setB : setA));
    const run = vi.spyOn(api, "runVirulence").mockResolvedValue({ id: "job-vf" } as AnalysisJob);
    renderWith(<VirulenceDialog open onOpenChange={() => {}} sampleId="s" assemblies={[assembly]} />);
    await waitFor(() => expect(preview).toHaveBeenCalledWith("asm-00001", null));
    expect(await screen.findByText(/VFDB core dataset \(set A, 2026-04-03\): genes of experimentally verified virulence factors only/)).toBeInTheDocument();
    const select = screen.getByRole("combobox", { name: "VFDB database" });
    expect(screen.getByRole("option", { name: "VFDB core (set A) 2026-04-03 · bundled with ABRicate · Default" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "VFDB full (set B) 2026-11-06" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "db-b" } });
    await waitFor(() => expect(preview).toHaveBeenLastCalledWith("asm-00001", "db-b"));
    expect(await screen.findByText(/also genes of predicted virulence factors, so it finds more genes than the core set A, and more that are not true virulence factors/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /I have checked the database/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run ABRicate" }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0]).toEqual(["asm-00001", { settings: { minid: 80, mincov: 80 }, database_id: "db-b", threads: null, confirmed: true }]);
  });

  it("explains core and full in Spanish", async () => {
    useSettings.setState({ language: "es" });
    vi.spyOn(api, "virulencePreview").mockResolvedValue({ ...plan(setA), databases: [setA] });
    renderWith(<VirulenceDialog open onOpenChange={() => {}} sampleId="s" assemblies={[assembly]} />);
    expect(await screen.findByText(/Conjunto básico de VFDB \(set A, 2026-04-03\): solo genes de factores de virulencia verificados experimentalmente/)).toBeInTheDocument();
    expect(screen.getByText(/El set B completo de VFDB \(también factores de virulencia predichos\)/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Base de datos VFDB" })).toBeNull();
  });
});

describe("virulence result", () => {
  it("names the VFDB set each run searched", () => {
    const view: VirulenceSample["assemblies"][number] = {
      assembly_id: "asm-00001",
      sources: {
        vfdb: { status: "searched", job_id: "job-vf", tool: "ABRicate", tool_version: "1.4.0", database_version: "2026-11-06", vfdb_set: "B", dataset: "full", hits: 1 },
        amrfinderplus: { status: "not_searched", job_id: null, tool_version: null, database_version: null, hits: 0 },
      },
      rows: [],
    };
    const run = { job_id: "job-vf", tool_version: "1.4.0", database_version: "2026-11-06", parameters: { minid: 80, mincov: 80 }, database_terms: {},
      vfdb: { set: "B", dataset: "full", version: "2026-11-06" }, warnings: [{ code: "vfdb_full", params: { name: "VFDB full (set B)", version: "2026-11-06" } }], files: {} } as unknown as VirulenceRun;
    renderWith(<VirulenceCard view={view} runs={[run]} />);
    expect(screen.getByText("VFDB (ABRicate): 1 genes (1.4.0, database VFDB full (set B) 2026-11-06)")).toBeInTheDocument();
    expect(screen.getByText(/Searched VFDB full \(set B\) 2026-11-06: VFDB's full dataset \(set B\)/)).toBeInTheDocument();
  });
});

const vfdbPlan: VfdbPlan = {
  set: "B", dataset: "full", name: "VFDB full (set B)", key: "vfdb-setB", version: "2026-11-06", bytes: 10_685_329, file: "VFDB_setB_nt.fas.gz",
  url: "https://www.mgc.ac.cn/VFs/Down/VFDB_setB_nt.fas.gz", last_modified: "Fri, 06 Nov 2026 11:30:33 GMT", etag: '"a30b91-65f99f0b62ec9"',
  db_dir: "/db", destinations: [], target_path: "/db/vfdb-setB/2026-11-06/vfdb_setB", host_target_path: "/Volumes/ARVA/db/vfdb-setB/2026-11-06/vfdb_setB", abricate_db: "vfdb_setB",
  licence: "CC BY-NC 4.0 (VFDB terms of use: non-commercial research or academic use; commercial use only with VFDB's permission)",
  licence_url: "https://creativecommons.org/licenses/by-nc/4.0/", citation: "Zhou S.Y., Liu B., Zheng D.D., Chen L.H., Yang J. (2025) VFDB 2025: an integrated resource for exploring anti-virulence compounds.",
  terms_url: "https://www.mgc.ac.cn/VFs/main.htm#termofuse", source_page: "https://www.mgc.ac.cn/VFs/download.htm", no_checksum: true, only_current: true,
  required_bytes: 85_482_632, available_bytes: 50e9, enough: true, blocked_by: null, blocked_code: null,
};

describe("VFDB full (set B) in the Database Manager", () => {
  it("shows the file, size, date, source, licence and citation, and downloads only after the confirmation", async () => {
    vi.spyOn(api, "vfdbPlan").mockResolvedValue(vfdbPlan);
    const download = vi.spyOn(api, "vfdbDownload").mockResolvedValue({} as never);
    renderWith(<VfdbDialog mode="download" onClose={() => {}} />);
    expect(await screen.findByText("VFDB_setB_nt.fas.gz")).toBeInTheDocument();
    expect(screen.getByText(/the day VFDB rebuilt it: Last-Modified Fri, 06 Nov 2026 11:30:33 GMT/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://www.mgc.ac.cn/VFs/Down/VFDB_setB_nt.fas.gz" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /CC BY-NC 4.0/ })).toHaveAttribute("href", "https://creativecommons.org/licenses/by-nc/4.0/");
    expect(screen.getByRole("link", { name: "VFDB's terms of use" })).toHaveAttribute("href", "https://www.mgc.ac.cn/VFs/main.htm#termofuse");
    expect(screen.getByText(/VFDB 2025: an integrated resource/)).toBeInTheDocument();
    expect(screen.getByText(/VFDB publishes none: ARVA records the SHA-256/)).toBeInTheDocument();
    expect(screen.getByText("/Volumes/ARVA/db/vfdb-setB/2026-11-06/vfdb_setB")).toBeInTheDocument();
    const start = screen.getByRole("button", { name: /Download and build/ });
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I confirm VFDB_setB_nt.fas.gz of 2026-11-06/ }));
    fireEvent.click(start);
    await waitFor(() => expect(download).toHaveBeenCalledWith({ destination: null, folder: null, confirm_version: "2026-11-06", confirm_bytes: 10_685_329, accept_terms: true }));
  });

  it("builds from a file the user has, asking for the set and date the file does not state", async () => {
    const buildPlan = vi.spyOn(api, "vfdbBuildPlan").mockResolvedValue({ ...vfdbPlan, source: "/data/vfdb/setB.fasta", host_source: "/Users/me/vfdb/setB.fasta", version: "2026-10-01", version_source: "declared", bytes: 55_304_914 });
    const build = vi.spyOn(api, "vfdbBuild").mockResolvedValue({} as never);
    useSettings.setState({ language: "es" });
    renderWith(<VfdbDialog mode="build" initialPath="/data/vfdb/setB.fasta" onClose={() => {}} />);
    expect(await screen.findByText("/Users/me/vfdb/setB.fasta")).toBeInTheDocument();
    expect(buildPlan).toHaveBeenCalledWith({ path: "/data/vfdb/setB.fasta", vfdb_set: null, declared_version: null, destination: null, folder: null });
    fireEvent.change(screen.getByRole("combobox", { name: "Conjunto de VFDB" }), { target: { value: "B" } });
    fireEvent.change(screen.getByPlaceholderText("AAAA-MM-DD"), { target: { value: "2026-10-01" } });
    await waitFor(() => expect(buildPlan).toHaveBeenLastCalledWith({ path: "/data/vfdb/setB.fasta", vfdb_set: "B", declared_version: "2026-10-01", destination: null, folder: null }));
    expect(await screen.findByText("(declarada por ti)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Confirmo este archivo/ }));
    fireEvent.click(screen.getByRole("button", { name: /Construir la base de datos/ }));
    await waitFor(() => expect(build).toHaveBeenCalledWith(expect.objectContaining({ path: "/data/vfdb/setB.fasta", vfdb_set: "B", declared_version: "2026-10-01", confirm_bytes: 55_304_914, accept_terms: true })));
  });
});

describe("workflow virulence node", () => {
  const record = (id: string, name: string, version: string, extra: Record<string, unknown> = {}) => ({
    id, key: id, kind: "vfdb", name, version, version_source: null, path: null, source_url: null, licence: null, size_bytes: null, checksum: null,
    archive_checksum: null, status: "installed", origin: "download", is_default: false, verification_level: null, installed_at: null,
    verified_at: null, notes: null, error_message: null, progress: null, cancel_requested_at: null, created_at: "", updated_at: "",
    version_json: null, version_file: null, variant: null, collection: null, files: null, published_md5_checked: null, amrfinderplus_db: null,
    archive: null, catalogue_version: null, compatibility: null, jobs_using: 0, available: true, vfdb: null, ...extra,
  }) as Awaited<ReturnType<typeof api.databases>>[number];

  it("offers only the VFDB databases ABRicate can search", async () => {
    vi.spyOn(api, "databases").mockResolvedValue([
      record("db-a", "VFDB core set A (bundled with ABRicate 1.4.0)", "2026-04-03", { is_default: true, origin: "bundled", vfdb: { set: "A", dataset: "core", version: "2026-04-03" } }),
      record("db-b", "VFDB full (set B)", "2026-11-06", { vfdb: { set: "B", dataset: "full", version: "2026-11-06" } }),
      record("db-fasta", "VFDB", "2026-10-01"),
    ]);
    const onChange = vi.fn();
    const schema = { properties: { database_id: { anyOf: [{ type: "string", maxLength: 36 }, { type: "null" }], default: null } } };
    const kind = { kind: "virulence", label: "Virulence", category: "typing", source: false, internal: false, tool_param: null, tools: {}, inputs: [], outputs: [],
      params_schema: schema, defaults: {}, database_kinds: { "": "vfdb" } } as unknown as NodeKind;
    renderWith(<ParamPanel kind={kind} params={{ database_id: null }} problems={[]} onChange={onChange} />);
    await screen.findByRole("option", { name: "VFDB full (set B) · 2026-11-06" });
    expect(screen.getByRole("option", { name: "VFDB core set A (bundled with ABRicate 1.4.0) · 2026-04-03 · default" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /2026-10-01/ })).toBeNull();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "db-b" } });
    expect(onChange).toHaveBeenLastCalledWith({ database_id: "db-b" });
  });
});

it("the guide explains VFDB's core and full sets in both languages", () => {
  const g = GUIDE_BY_ID.vfdb;
  expect(g.en.what).toMatch(/core dataset \(set A\) holds only the genes of experimentally verified virulence factors/);
  expect(g.en.interpret).toMatch(/more that are not true virulence factors/);
  expect(g.es.what).toMatch(/conjunto básico \(set A\) contiene solo los genes de factores de virulencia verificados experimentalmente/);
  expect(g.es.interpret).toMatch(/más que no son verdaderos factores de virulencia/);
});
