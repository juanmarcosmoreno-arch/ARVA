import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthGate } from "@/components/platform/Accounts";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { api, csrfHeaders } from "@/lib/api";
import {
  discoverParams,
  fmtP,
  network,
  orderedMatrix,
  platformApi,
  projectReportUrl,
  withCi,
  type CooccurrenceResult,
  type HeatmapResult,
} from "@/lib/platform";
import { DiscoverPage } from "@/pages/DiscoverPage";
import { useSettings } from "@/store/settings";

function renderWith(ui: ReactElement, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("platform helpers", () => {
  it("formats effects with their intervals and p-values in the interface locale", () => {
    expect(withCi(0.5, [0.1, 0.9])).toBe("0.5 (0.1–0.9)");
    expect(withCi(null, null)).toBe("–");
    expect(fmtP(0.0004)).toBe("< 0.001");
    expect(fmtP(0.012345)).toBe("0.0123");
    useSettings.setState({ language: "es" });
    expect(withCi(0.25, [0.1, 0.5])).toBe("0,25 (0,1–0,5)");
  });

  it("builds the query string with repeated sources and the report URL with the language", () => {
    const q = discoverParams({ analysis: "associations", sources: ["amr", "vf"], one_hot: ["st"], group: "host",
      min_group: 2, min_with: 1, alpha: 0.05 });
    expect(q).toContain("sources=amr&sources=vf");
    expect(q).toContain("one_hot=st");
    expect(q).toContain("group=host");
    expect(q).not.toContain("lineage");
    expect(projectReportUrl("p1", "pdf", "es")).toBe("/api/v1/projects/p1/report?format=pdf&lang=es");
  });

  it("orders the heatmap by the clustering and keeps only significant pairs in the network", () => {
    const h = { samples: ["a", "b"], features: ["x", "y"], matrix: [[1, 0], [0, 1]], sample_order: [1, 0],
      feature_order: [1, 0] } as unknown as HeatmapResult;
    const m = orderedMatrix(h);
    expect(m.samples).toEqual(["b", "a"]);
    expect(m.features).toEqual(["y", "x"]);
    expect(m.cells).toContainEqual([0, 0, 1]);
    const r = { alpha: 0.05, nodes: ["x", "y"], rows: [
      { feature_1: "x", feature_2: "y", q: 0.01, odds_ratio: 0.2, phi: -0.8 },
      { feature_1: "x", feature_2: "z", q: 0.4, odds_ratio: 3, phi: 0.1 },
    ] } as unknown as CooccurrenceResult;
    const net = network(r);
    expect(net.edges).toEqual([{ source: "x", target: "y", positive: false, q: 0.01, phi: -0.8 }]);
  });

  it("sends the session's CSRF token from its cookie", () => {
    document.cookie = "arva_csrf=tok%2B1; path=/";
    expect(csrfHeaders()).toEqual({ "X-CSRF-Token": "tok+1" });
    document.cookie = "arva_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });

  it("has guide entries in both languages for the new modules", () => {
    for (const id of ["discover_stats", "project_report", "accounts_access", "assist"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.title).not.toBe(GUIDE_BY_ID[id].en.title);
    }
  });
});

describe("AuthGate", () => {
  it("shows the interface unchanged when accounts are off", async () => {
    vi.spyOn(platformApi, "authStatus").mockResolvedValue({ enabled: false, setup_required: false, user: null });
    renderWith(<AuthGate><p>inside</p></AuthGate>);
    expect(await screen.findByText("inside")).toBeInTheDocument();
  });

  it("asks to sign in when accounts are on and nobody is signed in", async () => {
    vi.spyOn(platformApi, "authStatus").mockResolvedValue({ enabled: true, setup_required: false, user: null });
    renderWith(<AuthGate><p>inside</p></AuthGate>);
    expect(await screen.findAllByText("Sign in")).not.toHaveLength(0);
    expect(screen.queryByText("inside")).toBeNull();
  });

  it("asks for the setup token before the first administrator exists", async () => {
    vi.spyOn(platformApi, "authStatus").mockResolvedValue({ enabled: true, setup_required: true,
      setup_token_file: "/data/secrets/auth-setup-token", user: null });
    renderWith(<AuthGate><p>inside</p></AuthGate>);
    expect(await screen.findByText(/\/data\/secrets\/auth-setup-token/)).toBeInTheDocument();
  });
});

describe("Discover page", () => {
  it("labels results exploratory and shows the caveats, effect sizes and the lineage-stratified result", async () => {
    vi.spyOn(api, "projects").mockResolvedValue([{ id: "p1", name: "Proj" }] as never);
    vi.spyOn(platformApi, "discoverSummary").mockResolvedValue({
      project_id: "p1", samples: 8, label: "exploratory, not confirmatory",
      caveats: ["not_causal", "phylogenetic_dependence", "multiple_testing", "not_searched_excluded"],
      fields: [{ name: "host", known: 8, values: ["cattle", "human"] }, { name: "st", known: 8, values: ["S:8"] }],
      features: [{ name: "amr:blaZ", source: "amr", with: 5, searched: 7 }],
      provenance: { amr: { searched: 7, versions: ["AMRFinderPlus 4.0.23"] }, vf: { searched: 0, versions: [] }, rep: { searched: 0, versions: [] } },
      mixed_assemblies: [],
    });
    vi.spyOn(platformApi, "discover").mockResolvedValue({
      analysis: "associations", label: "exploratory, not confirmatory", samples_total: 8, features_used: 1,
      caveats: [], mixed_assemblies: [], sample_codes: {}, samples_with_value: 8, samples_without_value: 0, tests: 1,
      tested_groups: [], skipped_groups: [], stratified_by_lineage: true, method: "Fisher",
      rows: [{ group: "cattle", feature: "amr:blaZ", samples: 7, table: [4, 0, 1, 2], share_1: 1, share_1_ci: [0.51, 1],
        share_2: 0.33, share_2_ci: [0.06, 0.79], difference: 0.67, difference_ci: [0.1, 0.94], odds_ratio: 21,
        odds_ratio_ci: [0.6, 700], haldane_corrected: true, p: 0.142, q: 0.142,
        stratified: { samples: 7, informative_strata: 0, cmh_statistic: null, p: null, odds_ratio: null, odds_ratio_ci: null } }],
    } as never);
    renderWith(<Routes><Route path="/discover/:projectId" element={<DiscoverPage />} /></Routes>, "/discover/p1");
    expect((await screen.findAllByText("Exploratory, not confirmatory")).length).toBeGreaterThan(0);
    expect(screen.getByText(/Related genomes are not independent/)).toBeInTheDocument();
    expect(await screen.findByText("not testable: group and lineage coincide")).toBeInTheDocument();
    expect(screen.getByText("0.67 (0.1–0.94)")).toBeInTheDocument();
    expect(screen.getByText(/Only 8 samples/)).toBeInTheDocument();
  });
});
