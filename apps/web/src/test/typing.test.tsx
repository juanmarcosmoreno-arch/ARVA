import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StaphSummaryCard, TypingSection } from "@/components/genomic/StaphTyping";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import { genesText, settingsProblems, type StaphSummary, type TypingSample, typingBody, typingWarningText } from "@/lib/typing";
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
      "agr_mummer_mode", "agr_operon_partial", "agr_low_confidence", "agr_multiple", "agr_untypeable", "agr_non_canonical_agrD", "agr_frameshifts_not_determined",
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
});
