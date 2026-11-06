import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StaphSummaryCard, StaphTypingDialog, TypingSection } from "@/components/genomic/StaphTyping";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import type { Assembly } from "@/lib/types";
import { defaultSteps, genesText, noCassette, settingsProblems, type StaphSummary, stepList, type TypingPlan, type TypingRequirement, type TypingResult, type TypingSample, typingBody, typingWarningText } from "@/lib/typing";
import { useSettings } from "@/store/settings";

// The calls are the real outputs of sccmec 1.2.0, spaTyper 0.3.3 and AgrVATE 1.0.2 on S. aureus USA300_FPR3757, and
// AMRFinderPlus 4.2.7's on the same genome (workflows/tool-adapters/tests/fixtures/*/README.md).
const src = (tool: string, version: string) => ({ tool, version, job_id: "job-12345678" });
const usa300: StaphSummary = {
  assembly_id: "asm-00001",
  applicability: { module: "staphylococcus_aureus", status: "applicable", checks: [{ source: "species", value: "Staphylococcus aureus", matches: true }], override_required: false },
  mlst: { scheme: "saureus", st: "8", status: "PERFECT", clonal_complex: null, source: src("mlst", "2.35.0") },
  sccmec: { status: "typed", call: "IVa", details: { mecA: true, ccr_complexes: ["ccr Type 2"], mec_classes: ["mec Class B"] }, warnings: [], source: src("sccmec", "1.2.0") },
  spa: { status: "typed", call: "t008", details: { repeats: "11-19-12-21-17-34-24-34-22-25" }, warnings: [], source: src("spaTyper", "0.3.3") },
  agr: { status: "typed", call: "I", details: { match_score: 13 }, warnings: [], source: src("AgrVATE", "1.0.2") },
  amr: {
    source: { ...src("AMRFinderPlus", "4.2.7"), plus: true },
    mecA: [{ symbol: "mecA", name: null, method: "EXACTX", method_kind: "complete", identity: 100, coverage: 100, contig: "NC_007793.1" }],
    mecC: [],
    pvl: [
      { symbol: "lukF-PV", name: null, method: "BLASTX", method_kind: "complete", identity: 98.77, coverage: 100, contig: "NC_007793.1" },
      { symbol: "lukS-PV", name: null, method: "BLASTX", method_kind: "complete", identity: 99.68, coverage: 100, contig: "NC_007793.1" },
    ],
    tst: [],
    enterotoxins: [{ symbol: "sek", name: null, method: "BLASTX", method_kind: "complete", identity: 97.11, coverage: 100, contig: "NC_007793.1" }],
    exfoliative_toxins: [],
  },
  mec_crosscheck: { sccmec: true, amrfinderplus: true, status: "agree" },
  shorthand: "ST8-MRSA-IVa, t008, agr I, PVL+",
  uncertain: [],
  not_determined: [],
};

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("S. aureus typing", () => {
  it("has a text in both languages for every code the API sends and bilingual Guide entries", () => {
    const warnings = ["applicability_overridden", "tool_not_validated", "synthetic_input", "uppercased_input", "sccmec_mecA_includes_mecC", "sccmec_type_only",
      "sccmec_mec_without_type", "sccmec_multiple", "spa_new_repeat_succession", "spa_unknown_repeat", "spa_multiple", "spa_not_found", "spa_files_version",
      "agr_mummer_mode", "agr_operon_partial", "agr_low_confidence", "agr_multiple", "agr_multiple_majority", "agr_multiple_unresolved", "agr_untypeable", "agr_non_canonical_agrD", "agr_frameshifts_not_determined",
      "agr_exit_status", "agr_snippy_threads"];
    const statuses = ["typed", "type_only", "multiple", "mec_without_type", "not_typeable", "new_repeat_succession", "unknown_repeat", "not_found", "low_confidence", "untypeable"];
    const keys = [...warnings.map((c) => `typing.warning.${c}`), ...statuses.map((c) => `typing.status.${c}`),
      ...["typing_unknown_module", "typing_confirm", "typing_blocked", "typing_settings_invalid", "typing_not_applicable"].map((c) => `api.error.${c}`),
      ...["tool_unavailable", "help_unreadable", "no_ridom_files", "bundled_data_missing"].map((c) => `typing.planProblem.${c}`)];
    for (const key of keys) {
      expect(dictionaries.en).toHaveProperty(key);
      expect(dictionaries.es).toHaveProperty(key);
    }
    expect(typingWarningText(((k: string) => k) as never, { code: "something_new" })).toBe("something_new");
    for (const id of ["sccmec", "spa_typing", "agr", "staph_typing_summary"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.title).not.toBe(GUIDE_BY_ID[id].en.title);
    }
  });

  it("keeps 'not searched' apart from 'none found' and validates sccmec's thresholds", () => {
    const t = ((k: string) => k) as never;
    expect(genesText(t, null, true)).toBe("typing.notSearched");
    expect(genesText(t, [], false)).toBe("typing.notSearched");
    expect(genesText(t, [], true)).toBe("typing.noneFound");
    expect(genesText(t, [{ symbol: "sen", name: null, method: "INTERNAL_STOP", method_kind: "internal_stop", identity: null, coverage: null, contig: null }], true)).toBe("sen (typing.kind.internal_stop)");
    expect(settingsProblems("sccmec", { min_targets_pident: "0" })).toEqual(["typing.problem.threshold"]);
    expect(settingsProblems("spa", { anything: "x" })).toEqual([]);
    expect(typingBody("sccmec", { min_targets_pident: "95", min_regions_coverage: "" }, "", true)).toEqual({
      method: "sccmec", settings: { min_targets_pident: 95 }, database_id: null, override_applicability: true, confirmed: true });
    expect(typingBody("spa", { x: "1" }, "db-1", false).settings).toEqual({});
  });

  it("shows the shorthand with every part's source, in Spanish too", () => {
    renderWith(<StaphSummaryCard summary={usa300} />);
    expect(screen.getByText("ST8-MRSA-IVa, t008, agr I, PVL+")).toBeInTheDocument();
    expect(screen.getByText("IVa (typed)")).toBeInTheDocument();
    expect(screen.getAllByText("sccmec 1.2.0 · job job-1234").length).toBeGreaterThan(0);
    expect(screen.getByText("lukF-PV, lukS-PV")).toBeInTheDocument();
    expect(screen.getAllByText("none found").length).toBe(2);
    useSettings.setState({ language: "es" });
    renderWith(<StaphSummaryCard summary={{ ...usa300, amr: null, uncertain: [{ part: "st", reason: "mlst_status", params: { status: "NOVEL" } }] }} />);
    expect(screen.getByText("ST: el estado de mlst es NOVEL, no PERFECT")).toBeInTheDocument();
    expect(screen.getAllByText("no buscado").length).toBeGreaterThan(3);
  });

  it("says in words that there is no SCCmec cassette instead of a row of dashes", () => {
    // sccmec 1.2.0 on the SYNTHETIC genome (workflows/tool-adapters/tests/fixtures/sccmec/synthetic.tsv): type "-",
    // mecA "-", no targets; and an MSSA summary as the Mac test showed it.
    const none = { mecA: false, ccr_complexes: [], mec_classes: [], targets: [] };
    expect(noCassette(none)).toBe(true);
    expect(noCassette({ ...none, targets: ["IS431"] })).toBe(true);
    expect(noCassette({ ...none, targets: ["ccrA2"] })).toBe(false);
    expect(noCassette({ ...none, mecA: true })).toBe(false);
    expect(noCassette({ ...none, ccr_complexes: ["ccr Type 2"] })).toBe(false);
    expect(noCassette({})).toBe(false);
    const mssa: StaphSummary = { ...usa300, sccmec: { status: "not_typeable", call: null, details: none, warnings: [], source: src("sccmec", "1.2.0") } };
    renderWith(<StaphSummaryCard summary={mssa} />);
    expect(screen.getByText("No SCCmec cassette: neither mecA/mecC nor ccr genes found")).toBeInTheDocument();
    expect(screen.queryByText(/- · - · mecA -/)).toBeNull();
    useSettings.setState({ language: "es" });
    renderWith(<StaphSummaryCard summary={mssa} />);
    expect(screen.getAllByText("Sin casete SCCmec: no se encontraron mecA/mecC ni genes ccr")).toHaveLength(2);
    // A cassette with ccr genes but no mec class: the missing part reads "none found", not "-".
    useSettings.setState({ language: "en" });
    renderWith(<StaphSummaryCard summary={{ ...mssa, sccmec: { ...mssa.sccmec!, details: { ...none, ccr_complexes: ["ccr Type 2"] } } }} />);
    expect(screen.getByText("ccr Type 2 · none found · mecA -")).toBeInTheDocument();
  });

  it("lists what is missing and where to get the Ridom files, and why the module is not offered", async () => {
    const view: TypingSample = {
      modules: [{
        key: "staphylococcus_aureus", name: "Staphylococcus aureus typing", species: ["Staphylococcus aureus"], mlst_schemes: ["saureus"], guide: [],
        requirements: [{
          key: "spa", name: "spa typing", missing: ["database"], ready: false, guide: "spa_typing",
          tool: { id: "spatyper", name: "spaTyper", status: "available", version: "0.3.3", version_validated: true, message: "", reason: null, reason_params: {}, path: "/env/bin/spaTyper",
            license: "LGPL-3.0", citation: "", citation_url: "", install: {}, platforms: ["linux-64", "linux-aarch64"] },
          database: { kind: "spa_types", name: "spa types (Ridom SpaServer)", registered: [], source_url: "https://spa.ridom.de/", licence: "",
            licence_url: "https://spa.ridom.de/policy.shtml", download_note: "", user_provided_only: true },
        }],
      }],
      assemblies: [{ assembly_id: "asm-00001", assembler: "Flye", assembler_version: "2.9.3", kind: "assembly", created_at: "2026-11-02T00:00:00Z", summary: null,
        applicability: { staphylococcus_aureus: { module: "staphylococcus_aureus", status: "not_applicable", checks: [{ source: "species", value: "Escherichia coli", matches: false }], override_required: true } } }],
      results: [],
    };
    vi.spyOn(api, "typingSample").mockResolvedValue(view);
    renderWith(<TypingSection sampleId="s" jobs={[]} onStart={() => undefined} />);
    await waitFor(() => expect(screen.getByText(/No Ridom SpaServer files are registered/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "spatypes.txt" })).toHaveAttribute("href", "https://spa.ridom.de/dynamic/spatypes.txt");
    expect(screen.getByText(/names another taxon.*species identification: Escherichia coli/)).toBeInTheDocument();
  });

  // The Mac test's case: SCCmec already run on the assembly, agr not yet, no Ridom files registered.
  const tool = (id: string, name: string, version: string) => ({ id, name, status: "available", version, version_validated: true, message: "", reason: null, reason_params: {}, path: `/env/bin/${id}`,
    license: "GPL-3.0", citation: "", citation_url: "https://example.org/cite", install: {}, platforms: ["linux-64"] });
  const requirement = (key: "sccmec" | "spa" | "agr", ready: boolean, t: ReturnType<typeof tool>): TypingRequirement => ({ key, name: key, tool: t, database: null, missing: ready ? [] : ["database"], ready, guide: "" });
  const requirements = [requirement("sccmec", true, tool("sccmec", "sccmec", "1.2.0")), requirement("spa", false, tool("spatyper", "spaTyper", "0.3.3")), requirement("agr", true, tool("agrvate", "AgrVATE", "1.0.2"))];
  const sccmecResult = { id: "r1", job_id: "job-sccmec", sample_id: "s", assembly_id: "asm-00001", module: "staphylococcus_aureus", method: "sccmec", tool: "sccmec", tool_version: "1.2.0",
    database_kind: null, database_name: null, database_version: null, database_checksum: null, parameters: {}, status: "not_typeable", call: null,
    details: { mecA: false, ccr_complexes: [], mec_classes: [], targets: [] }, applicability: {}, warnings: [], files: {}, created_at: "2026-11-03T10:00:00Z" } as TypingResult;

  it("checks by default the steps not yet run whose tool and data are ready, and names them on the button", () => {
    expect(defaultSteps("asm-00001", [sccmecResult], requirements)).toEqual(["agr"]);
    expect(defaultSteps("asm-00002", [sccmecResult], requirements)).toEqual(["sccmec", "agr"]);
    expect(defaultSteps("asm-00001", [], requirements.map((r) => ({ ...r, ready: true })))).toEqual(["sccmec", "spa", "agr"]);
    const t = (k: string, v?: Record<string, string>) => (k === "typing.listAnd" ? `${v?.first} and ${v?.last}` : k.replace("typing.stepName.", ""));
    expect(stepList(t as never, ["agr"])).toBe("agr");
    expect(stepList(t as never, ["sccmec", "agr"])).toBe("sccmec and agr");
    expect(stepList(t as never, ["sccmec", "spa", "agr"])).toBe("sccmec, spa and agr");
  });

  it("reads an SCCmec result without a cassette as a sentence", async () => {
    vi.spyOn(api, "typingSample").mockResolvedValue({ modules: [], assemblies: [], results: [sccmecResult, { ...sccmecResult, id: "r2", details: { ...sccmecResult.details, targets: ["IS431"] } }] });
    renderWith(<TypingSection sampleId="s" jobs={[]} onStart={() => undefined} />);
    expect(await screen.findByText("No SCCmec cassette: neither mecA/mecC nor ccr genes found")).toBeInTheDocument();
    expect(screen.getByText("No SCCmec cassette: neither mecA/mecC nor ccr genes found (other targets: IS431)")).toBeInTheDocument();
    expect(screen.queryByText(/Type -, subtype -/)).toBeNull();
  });

  it("runs every checked step as its own job, in Spanish too", async () => {
    const view: TypingSample = {
      modules: [{ key: "staphylococcus_aureus", name: "Staphylococcus aureus typing", species: ["Staphylococcus aureus"], mlst_schemes: ["saureus"], guide: [], requirements }],
      assemblies: [], results: [sccmecResult],
    };
    vi.spyOn(api, "typingSample").mockResolvedValue(view);
    const plan = (method: "sccmec" | "spa" | "agr"): TypingPlan => ({
      module: "staphylococcus_aureus", method, tool: { ...requirements.find((r) => r.key === method)!.tool, max_threads: 4, default_threads: 2 }, database: null, databases: [], bundled: null,
      defaults: method === "sccmec" ? { min_targets_pident: "90" } : {}, tool_defaults: {}, defaults_match: true, assembly: { synthetic_evidence: [] },
      applicability: { module: "staphylococcus_aureus", status: "applicable", checks: [], override_required: false }, problems: [],
    });
    vi.spyOn(api, "typingPreview").mockImplementation(async (_a, _m, method) => plan(method));
    const runTyping = vi.spyOn(api, "runTyping").mockResolvedValue({ id: "job" } as never);
    const assembly = { id: "asm-00001", assembler: "Flye", assembler_version: "2.9.6", kind: "assembly", parent_assembly_id: null, created_at: "2026-11-02T00:00:00Z", stats: { contig_count: 2, total_length: 2_800_000 } } as unknown as Assembly;
    useSettings.setState({ language: "es" });
    renderWith(<StaphTypingDialog open onOpenChange={() => undefined} sampleId="s" assemblies={[assembly]} />);
    expect(await screen.findByRole("button", { name: "Ejecutar agr" })).toBeDisabled();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.slice(0, 3).map((b) => (b as HTMLInputElement).checked)).toEqual([false, false, true]);
    expect(screen.getByText(/ya ejecutado en este ensamblaje/)).toBeInTheDocument();
    fireEvent.click(boxes[0]);
    expect(await screen.findByRole("button", { name: "Ejecutar SCCmec y agr" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Tipado de SCCmec" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tipado agr" })).toBeInTheDocument();
    expect(screen.getByLabelText("--min-targets-pident")).toHaveValue(90);
    fireEvent.click(screen.getByLabelText(/He revisado los pasos/));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ejecutar SCCmec y agr" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar SCCmec y agr" }));
    await waitFor(() => expect(runTyping).toHaveBeenCalledTimes(2));
    expect(runTyping.mock.calls.map((c) => [c[0], c[2].method])).toEqual([["asm-00001", "sccmec"], ["asm-00001", "agr"]]);
    expect(runTyping.mock.calls[0][2].settings).toEqual({});
  });
});
