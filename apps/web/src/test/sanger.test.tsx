import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Ncbi16sDialog } from "@/components/databases/Ncbi16sDialog";
import { Chromatogram } from "@/components/sanger/Chromatogram";
import { ConsensusView } from "@/components/sanger/ConsensusView";
import { Interpretation16sCard, OnlineBlast, RankedTable, SuspectedCard } from "@/components/sanger/SangerResults";
import { SangerReads } from "@/components/sanger/SangerReads";
import { SearchDialog } from "@/components/sanger/SearchDialog";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import {
  clampWindow,
  codedKey,
  consensusBlocks,
  cutDecimals,
  defaultPair,
  hitName,
  moveWindow,
  pairSignature,
  scanOfBase,
  suspicionRequest,
  tracePaths,
  trimmedRanges,
  trimRequest,
  type ConsensusResult,
  type IdentificationBrief,
  type IdentificationResults,
  type Interpretation16s,
  type SangerOverview,
  type SangerReadView,
  type SearchPlan,
  type SuspectedComparison,
  type TraceView,
} from "@/lib/sanger";
import { useSettings } from "@/store/settings";
// Built by fixtures/sanger/build_fixture.py from Biopython 1.88's public 3100.ab1 (Biopython License Agreement) and
// the real blastn output of its trimmed read against NCBI's 16S database; no user read.
import fixture from "./fixtures/sanger/sanger-3100.json";

const overview = fixture.overview as unknown as TraceView;
const windowView = fixture.window as unknown as TraceView;
const consensus = fixture.consensus as unknown as ConsensusResult;
const results = fixture.results as unknown as {
  ranked: IdentificationResults["ranked"];
  ranked_count: number;
  tied_with_best: number;
  interpretation_16s: Interpretation16s;
  suspected_species: SuspectedComparison;
  suspected_genus: SuspectedComparison;
  suspected_other: SuspectedComparison;
  suspected_abbreviated: SuspectedComparison;
  suspected_16s_gene: SuspectedComparison;
};

function renderWith(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const read = (over: Partial<SangerReadView> = {}): SangerReadView => ({
  id: "read-f",
  sample_id: "s1",
  name: "16S_S2_1387-F",
  original_filename: "16S_S2_1387-F.ab1",
  file_format: "abi",
  record_index: 0,
  sha256: "a".repeat(64),
  size_bytes: 209224,
  direction: "forward",
  direction_source: "name",
  pair_key: "16S_S2",
  primer: "1387",
  length: 795,
  has_qualities: true,
  has_trace: true,
  summary: { mean_quality: 46.8, q20_percent: 85.8, instrument: { model: "3100" }, warnings: [], default_trim: { limit: 0.05, start: 19, end: 697, length: 679, mean_quality: 53, q20_percent: 97.8 } },
  created_at: "2026-11-03T10:00:00Z",
  used_by: 0,
  ...over,
});

beforeEach(() => useSettings.setState({ language: "en" }));
afterEach(() => vi.restoreAllMocks());

describe("Sanger helpers", () => {
  it("cut identities instead of rounding them, so a value below a threshold never reads as the threshold", () => {
    expect(cutDecimals((100 * 593) / 599)).toBe(98.99);
    expect(cutDecimals(99.2)).toBe(99.2);
    expect(cutDecimals(99.85272459499264)).toBe(99.85);
    expect(cutDecimals(100)).toBe(100);
  });

  it("propose the Macrogen pair and fall back to the first reads", () => {
    const f = read();
    const r = read({ id: "read-r", name: "S12_1401-R", direction: "reverse" });
    expect(defaultPair({ reads: [f, r], pairs: [{ pair_key: "S12", status: "proposed", forward_read_id: "read-f", reverse_read_id: "read-r" }] })).toEqual({ forward: "read-f", reverse: "read-r" });
    expect(defaultPair({ reads: [r], pairs: [] })).toEqual({ forward: null, reverse: "read-r" });
    expect(defaultPair({ reads: [read({ direction: "unknown" })], pairs: [] })).toEqual({ forward: "read-f", reverse: null });
    // A text copy without qualities (Macrogen's .txt) is not chosen before its chromatogram.
    const txt = read({ id: "read-txt", has_qualities: false, has_trace: false, file_format: "fasta" });
    expect(defaultPair({ reads: [txt, f], pairs: [] }).forward).toBe("read-f");
  });

  it("propose the reads again when a direction or a pair key is corrected", () => {
    const a = read({ id: "a", direction: "unknown", pair_key: null });
    const b = read({ id: "b", direction: "unknown", pair_key: null });
    const before = pairSignature([a, b]);
    expect(pairSignature([a, b])).toBe(before);
    expect(pairSignature([{ ...a, direction: "forward" }, b])).not.toBe(before);
    expect(pairSignature([a, { ...b, pair_key: "27" }])).not.toBe(before);
  });

  it("build trim and suspicion requests from the form", () => {
    expect(trimRequest(0.05, "", "")).toEqual({ limit: 0.05 });
    expect(trimRequest(0.05, "23", "582")).toEqual({ limit: 0.05, manual_start: 23, manual_end: 582 });
    expect(trimRequest(0.01, "23", "")).toEqual({ limit: 0.01 });
    expect(suspicionRequest("species", "  Staphylococcus   aureus ")).toEqual({ kind: "species", value: "Staphylococcus aureus" });
    expect(suspicionRequest("gene", "   ")).toBeNull();
  });

  it("name a hit from whichever source named it", () => {
    expect(hitName({ gene: "arcC", allele: "3" })).toBe("arcC_3");
    expect(hitName({ gene: "hly/hla", product: "Alpha-hemolysin" })).toBe("hly/hla");
    expect(hitName({ species: "Staphylococcus epidermidis", strain: "Fussel" })).toBe("Staphylococcus epidermidis Fussel");
    expect(hitName({ product: "16S ribosomal RNA" })).toBe("16S ribosomal RNA");
    expect(hitName({})).toBeNull();
  });

  it("keep the chromatogram window inside the trace while scrolling and zooming", () => {
    const scans = overview.scans;
    expect(scans).toBe(10303);
    expect(clampWindow(-50, 1200, scans)).toEqual({ start: 0, width: 1200 });
    expect(clampWindow(10000, 1200, scans)).toEqual({ start: scans - 1200, width: 1200 });
    expect(moveWindow({ start: 0, width: 1200 }, scans, "right")).toEqual({ start: 300, width: 1200 });
    expect(moveWindow({ start: 1200, width: 1200 }, scans, "zoomIn")).toEqual({ start: 1500, width: 600 });
    expect(moveWindow({ start: 1200, width: 1200 }, scans, "zoomOut")).toEqual({ start: 600, width: 2400 });
    expect(moveWindow({ start: 1200, width: 1200 }, scans, "end")).toEqual({ start: scans - 1200, width: 1200 });
    expect(moveWindow({ start: 0, width: 200 }, scans, "zoomIn").width).toBe(120);
  });

  it("draw every channel of a real trace on one scale and find each base's peak", () => {
    const { paths, max } = tracePaths(windowView, 1000, 150);
    expect(max).toBe(Math.max(...(["A", "C", "G", "T"] as const).flatMap((c) => windowView.channels[c])));
    for (const c of ["A", "C", "G", "T"] as const) expect(paths[c].split(" ")).toHaveLength(windowView.channels[c].length);
    expect(scanOfBase(overview.markers, 166)).toBe(2011);
    expect(trimmedRanges(795, { start: 19, end: 697 })).toEqual([[1, 18], [698, 795]]);
    expect(trimmedRanges(795, null)).toEqual([[1, 795]]);
  });

  it("split the consensus into blocks of ten with each base's status", () => {
    const blocks = consensusBlocks([
      { column: 1, position: 1, base: "A", status: "forward_only", kind: null, rule: null, forward: null, reverse: null },
      { column: 2, position: null, base: "", status: "resolved", kind: "gap", rule: "higher_quality", forward: null, reverse: null },
      ...Array.from({ length: 10 }, (_, i) => ({ column: i + 3, position: i + 2, base: "C", status: "agree" as const, kind: null, rule: null, forward: null, reverse: null })),
    ]);
    expect(blocks.map((b) => b.start)).toEqual([1, 11]);
    expect(blocks[0].bases[0]).toEqual({ base: "A", status: "forward_only", column: 1 });
    expect(blocks[1].bases).toHaveLength(1);
  });

  it("write decimals of coded messages in the interface's locale and keep counts as numbers", () => {
    useSettings.setState({ language: "es" });
    expect(codedKey("sanger.s16.reason", { code: "species_not_separated", params: { species: 25, minimum: 0.8, separation: 0 } })).toEqual(["sanger.s16.reason.species_not_separated", { species: 25, minimum: "0,8", separation: 0 }]);
    expect(codedKey("sanger.s16.reason", { code: "genera_not_separated", params: { genera: ["Mammaliicoccus", "Staphylococcus"] } })[1]).toEqual({ genera: "Mammaliicoccus, Staphylococcus" });
  });

  it("have a text for every code the API sends and bilingual guide entries", () => {
    const codes = {
      "sanger.warning": ["no_qualities", "peaks_mismatch", "peaks_outside_trace", "no_trace", "not_trimmed_no_qualities", "nothing_kept", "orientation_suspect", "no_overlap", "unresolved_conflicts", "conflicts_without_qualities", "single_read", "genomes_unannotated"],
      "sanger.s16.reason": ["low_query_coverage", "short_alignment", "below_genus_identity", "species_not_separated", "below_species_identity", "genera_not_separated"],
      "sanger.s16.caveat": ["criteria_quoted", "not_first_500", "staphylococcus_16s_limit", "closest_type_strain"],
      "sanger.suspectReason": ["not_found", "below_coverage", "better_hit_other_name", "below_thresholds", "tied_with_other_names"],
      "sanger.problem": ["tool_missing", "tool_options_missing", "no_database", "no_genomes", "collection_too_large"],
      "api.error": ["sanger_file_empty", "sanger_unknown_format", "sanger_unreadable", "sanger_duplicate", "sanger_no_overlap", "sanger_query_length", "sanger_search_blocked", "ncbi16s_confirm"],
    };
    for (const [prefix, list] of Object.entries(codes)) {
      for (const code of list) {
        const key = `${prefix}.${code}` as keyof typeof dictionaries.en;
        expect(dictionaries.en[key], key).toBeTruthy();
        expect(dictionaries.es[key], key).toBeTruthy();
      }
    }
    for (const id of ["sanger_reads", "sanger_trimming", "sanger_mixed_peaks", "sanger_consensus", "sanger_conflicts", "sanger_sources", "sanger_ranking", "sanger_16s", "sanger_suspected"] as const) {
      expect(GUIDE_BY_ID[id].en.title).toBeTruthy();
      expect(GUIDE_BY_ID[id].es.title).toBeTruthy();
    }
  });
});

describe("Chromatogram", () => {
  const traceSpy = () =>
    vi.spyOn(api, "sangerTrace").mockImplementation(async (_id, start, end) => (start === 0 && end === null ? overview : { ...windowView, scan_start: start, scan_end: end ?? overview.scans }));

  it("shows the four traces, the bases of the window and scrolls with the keyboard", async () => {
    const spy = traceSpy();
    renderWith(<Chromatogram readId="read-f" name="16S_S2_1387-F" length={795} trim={{ start: 19, end: 697 }} review={[166]} conflicts={[167]} />);
    await waitFor(() => expect(screen.getByRole("img", { name: /Chromatogram of 16S_S2_1387-F: four traces/ })).toBeInTheDocument());
    expect(screen.getByText(/Bases 166–\d+ of 795/)).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Chromatogram of 16S_S2_1387-F" });
    expect(group).toHaveAttribute("tabindex", "0");
    const calls = spy.mock.calls.length;
    fireEvent.keyDown(group, { key: "ArrowRight" });
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThan(calls));
    const [, start, end] = spy.mock.calls[spy.mock.calls.length - 1];
    expect(end! - start).toBe(1200);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await waitFor(() => {
      const last = spy.mock.calls[spy.mock.calls.length - 1];
      expect(last[2]! - last[1]).toBe(600);
    });
    expect(screen.getByText(/Keyboard \(after focusing the chromatogram\)/)).toBeInTheDocument();
  });
});

describe("Consensus and results", () => {
  it("lists every conflict of a real consensus with both reads' bases and qualities", () => {
    renderWith(<ConsensusView result={{ ...consensus, columns: [] }} reads={{ forward: read(), reverse: read({ id: "read-r", has_trace: false, direction: "reverse" }) }} />);
    expect(screen.getByText("2 conflicts to review")).toBeInTheDocument();
    // Two rows and the legend of the sequence.
    expect(screen.getAllByText("unresolved (IUPAC code or N)")).toHaveLength(3);
    expect(screen.getAllByText("qualities too close to choose")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Show base 300 in the chromatogram of 16S_S2_1387-F" })).toBeInTheDocument();
  });

  it("reads the public 16S read as genus Staphylococcus, with the species not separated and the caveats", () => {
    renderWith(<Interpretation16sCard interpretation={results.interpretation_16s} />);
    expect(screen.getByText("Genus")).toBeInTheDocument();
    expect(screen.getByText("Genus Staphylococcus; the species is not resolved by this sequence.")).toBeInTheDocument();
    expect(screen.getByText(/Closest type strain: Staphylococcus epidermidis/)).toBeInTheDocument();
    expect(screen.getByText(/In Staphylococcus, 16S often does not separate species/)).toBeInTheDocument();
    expect(screen.getByText(/rpoB, sodA, tuf, gap/)).toBeInTheDocument();
  });

  it("says ambiguous for the suspected species and lists the tied species, never hiding them", () => {
    renderWith(<SuspectedCard comparison={results.suspected_species} />);
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
    expect(results.suspected_species.tied_other_count).toBeGreaterThan(0);
    expect(screen.getByText(new RegExp(`${results.suspected_species.tied_other_count} hits? with other names? (are|is) as good`))).toBeInTheDocument();
  });

  it("says match for the genus and no match for a species without hits", () => {
    renderWith(
      <>
        <SuspectedCard comparison={results.suspected_genus} />
        <SuspectedCard comparison={results.suspected_other} />
      </>,
    );
    expect(screen.getByText("Matches")).toBeInTheDocument();
    expect(screen.getByText("Does not match")).toBeInTheDocument();
    expect(screen.getByText(/No hit of the searched sources has that name\. Check the spelling/)).toBeInTheDocument();
  });

  it("reads an abbreviated genus as the species and the 16S gene by its usual names", () => {
    renderWith(
      <>
        <SuspectedCard comparison={results.suspected_abbreviated} />
        <SuspectedCard comparison={results.suspected_16s_gene} />
      </>,
    );
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
    expect(screen.getByText("Read as: Staphylococcus epidermidis")).toBeInTheDocument();
    expect(screen.getByText("Matches")).toBeInTheDocument();
  });

  it("shows no outcome before any search, and a provisional one while searches run", () => {
    const waiting: SuspectedComparison = { suspected: "Staphylococcus aureus", kind: "species", outcome: "not_searched", pending: 0, searched: [], reasons: [], caveats: [] };
    const { unmount } = renderWith(<SuspectedCard comparison={waiting} />);
    expect(screen.getByText("Not searched yet")).toBeInTheDocument();
    expect(screen.queryByText("Does not match")).toBeNull();
    expect(screen.getByText("Search the local sources to compare.")).toBeInTheDocument();
    unmount();
    renderWith(<SuspectedCard comparison={{ ...results.suspected_other, pending: 2, caveats: [{ code: "own_genome_excluded", params: { count: 3 } }] }} />);
    expect(screen.getByText(/2 searches are still queued or running: this outcome is provisional/)).toBeInTheDocument();
    expect(screen.getByText(/3 hits on this sample's own genome are left out/)).toBeInTheDocument();
  });

  it("says when NCBI's 16S database was not searched", () => {
    renderWith(<Interpretation16sCard interpretation={null} notSearched />);
    expect(screen.getByText(/NCBI's 16S rRNA database \(type strains\) was not searched/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download or register it in Tools, Reference databases" })).toHaveAttribute("href", "/tools");
  });

  it("ranks the hits with cut percentages and the database version", () => {
    const r = { identification: { searched: ["ncbi_16s"] }, ranked: results.ranked, ranked_count: results.ranked_count, tied_with_best: results.tied_with_best } as unknown as IdentificationResults;
    renderWith(<RankedTable results={r} />);
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Staphylococcus epidermidis");
    expect(rows[1]).toHaveTextContent("99.85%");
    expect(rows[1]).toHaveTextContent("NCBI 16S ribosomal RNA (type strains) 2026-10-29");
    expect(screen.getByText(/97 hits \(12 shown\)/)).toBeInTheDocument();
  });

  it("shows the results in Spanish", () => {
    useSettings.setState({ language: "es" });
    renderWith(<Interpretation16sCard interpretation={results.interpretation_16s} />);
    expect(screen.getByText("Género")).toBeInTheDocument();
    expect(screen.getByText("Género Staphylococcus; esta secuencia no resuelve la especie.")).toBeInTheDocument();
  });
});

describe("Online BLAST is manual and opt-in", () => {
  it("sends nothing and offers the link only after the acknowledgement", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderWith(<OnlineBlast sequence="ACGT" />);
    expect(screen.queryByRole("link", { name: "Open NCBI BLAST" })).toBeNull();
    expect(screen.getByRole("button", { name: "Copy the sequence" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("link", { name: "Open NCBI BLAST" })).toHaveAttribute("href", "https://blast.ncbi.nlm.nih.gov/");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows the sequence to copy by hand when the browser does not allow copying", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    renderWith(<OnlineBlast sequence="ACGTTGCA" />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Copy the sequence" }));
    expect(await screen.findByText(/The browser did not allow copying/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("ACGTTGCA");
  });
});

describe("Search dialog", () => {
  const ident: IdentificationBrief = {
    id: "ident-1", sample_id: "s1", label: "S12", mode: "pair", forward_read_id: "read-f", reverse_read_id: "read-r", length: 599, sha256: "b".repeat(64),
    suspected: null, created_at: "2026-11-03T10:00:00Z", searched: [], running: 0, best: null, best_tied: 0, best_tied_names: 0, reading_16s: null, conflicts: 0, unresolved: 0,
  };
  const tool = { id: "blast", name: "BLAST+", status: "available", version: "2.12.0", message: "", reason: null };
  const plan: SearchPlan = {
    identification_id: "ident-1",
    query: { length: 599, sha256: "b".repeat(64), mode: "pair" },
    sources: [
      { source: "ncbi_16s", kind: "ncbi_16s", tool, database: null, database_options: [], genomes: [], settings: { task: "megablast", evalue: 1e-10, max_target_seqs: 500 }, problems: [{ code: "no_database", params: { kind: "ncbi_16s" }, message: "No usable ncbi_16s database" }] },
      {
        source: "vfdb", kind: "vfdb", tool, settings: { task: "blastn", evalue: 1e-5, max_target_seqs: 500 }, problems: [], genomes: [],
        database: { id: "db-vfdb", key: "abricate-vfdb", kind: "vfdb", name: "VFDB (ABRicate)", version: "2026-Apr-3", version_source: "file", checksum: "sha256:abc", host_path: "/x", is_default: true, bundled: true, available: true, licence: null, citation: null },
        database_options: [],
      },
    ],
    runnable: ["vfdb"],
    blocked: ["ncbi_16s"],
    notes: ["local_only", "one_job_per_source"],
  };

  it("shows what blocks a source, and starts only the runnable ones after confirmation", async () => {
    vi.spyOn(api, "sangerSearchPlan").mockResolvedValue(plan);
    vi.spyOn(api, "sangerGenomes").mockResolvedValue([]);
    const start = vi.spyOn(api, "startSangerSearch").mockResolvedValue([]);
    const onStarted = vi.fn();
    renderWith(<SearchDialog identification={ident} onClose={() => {}} onStarted={onStarted} />);
    expect(await screen.findByText(/No usable database of this kind is registered or installed/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is sent to NCBI or anywhere else/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Start 1 search" });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I checked the summary/ }));
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(start.mock.calls[0][0]).toBe("ident-1");
    expect(start.mock.calls[0][1]).toMatchObject({ only_runnable: true, sources: ["ncbi_16s", "vfdb", "mlst", "amrfinderplus", "spa", "reference_genomes", "genomes"] });
  });
});

describe("Sanger reads", () => {
  it("uploads dropped files and shows each skipped file's reason in the interface language", async () => {
    useSettings.setState({ language: "es" });
    const upload = vi.spyOn(api, "importSangerReads").mockResolvedValue({
      imported: [read()],
      skipped: [{ file: "fake.ab1", code: "sanger_unreadable", params: { file: "fake.ab1", detail: "not a readable ABIF (.ab1) file" }, detail: "fake.ab1 cannot be read: not a readable ABIF (.ab1) file" }],
      pairs: [],
    });
    const o: SangerOverview = { sample_id: "s1", reads: [read()], pairs: [], identifications: [], genomes: [] };
    const { container } = renderWith(<SangerReads sampleId="s1" overview={o} />);
    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    expect(input.accept).toContain(".ab1");
    fireEvent.change(input, { target: { files: [new File(["ABIF"], "16S_S2_1387-F.ab1")] } });
    await waitFor(() => expect(upload).toHaveBeenCalled());
    expect(await screen.findByText("fake.ab1 no se puede leer: not a readable ABIF (.ab1) file")).toBeInTheDocument();
    expect(screen.getByText(/1 lectura importada/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Dirección de 16S_S2_1387-F" })).toHaveValue("forward");
    expect(screen.getByText("19–697")).toBeInTheDocument();
  });
});

describe("NCBI 16S download", () => {
  it("downloads only the build and size shown, after the confirmation", async () => {
    vi.spyOn(api, "ncbi16sPlan").mockResolvedValue({
      version: "2026-10-29", archive_bytes: 72729050, database_bytes: 18413401, description: "16S ribosomal RNA (Bacteria and Archaea type strains)", sequences: 27646, letters: 40048476,
      url: "https://ftp.ncbi.nlm.nih.gov/blast/db/16S_ribosomal_RNA.tar.gz", md5: "050f4b623a7e1d745143084095dd96b9", taxonomy: false, kept_files: ["16S_ribosomal_RNA.nsq"],
      required_bytes: 91142451, host_target_path: "/db/ncbi-16s/2026-10-29", folder: "ncbi-16s/2026-10-29", available_bytes: 10e9, enough: true, blocked_by: null, blocked_code: null,
      licence: "NCBI places no restrictions", licence_url: null, only_current: true,
    });
    const download = vi.spyOn(api, "ncbi16sDownload").mockResolvedValue({} as never);
    renderWith(<Ncbi16sDialog onClose={() => {}} />);
    expect(await screen.findByText(/Build 2026-10-29: archive of/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Download" });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Download build 2026-10-29/ }));
    fireEvent.click(button);
    await waitFor(() => expect(download).toHaveBeenCalledWith({ taxonomy: false, confirm_version: "2026-10-29", confirm_bytes: 72729050, accept_terms: true }));
  });
});
