import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReadHeadersCard, TechnologySuggestion } from "@/components/domain/ReadHeaders";
import { dictionaries } from "@/i18n";
import { api } from "@/lib/api";
import { DISTINCT_FIELDS, codeKey, distinctRows, documentationLinks, dominantFormat, suggestionState } from "@/lib/headers";
import type { HeaderConfidence, HeaderMetadata, HeaderSummary, RawFile, Sample, SequencingTechnology } from "@/lib/types";
import { useSettings } from "@/store/settings";

function meta(overrides: Partial<HeaderMetadata> = {}): HeaderMetadata {
  return {
    schema: "arva.header_meta/1",
    n_headers_read: 1000,
    n_usable: 1000,
    platform_counts: { unknown: 1000 },
    confidence_by_platform: { unknown: { none: 1000 } },
    format_counts: { generic_slash_mate: 1000 },
    mates: { "1": 1000 },
    mate_layout: "mate_1_only",
    illumina_read_numbers: {},
    illumina_is_filtered: {},
    distinct: {},
    warning_counts: {},
    evidence: { generic_slash_mate: ["read id ends with /1 or /2 (generic mate convention; not platform-specific)"] },
    sources: { generic_slash_mate: [] },
    suggested_technology: {
      value: null, confidence: "none", agreement: 0, conflicting_headers: 0,
      reason: "no platform-specific header grammar matched", overrides_user_metadata: false,
    },
    ...overrides,
  };
}

const file = (id: string, name: string, header_metadata: HeaderMetadata | null, read_mate: string | null = null) =>
  ({ id, original_filename: name, file_format: "fastq_gz", read_mate, origin: "imported", is_valid: true, header_metadata }) as RawFile;

const sample = (technology: Sample["sequencing_technology"]) => ({ id: "s1", sample_code: "S1", sequencing_technology: technology }) as Sample;

function summary(overrides: Partial<HeaderSummary["suggested_technology"]> = {}, rest: Partial<HeaderSummary> = {}): HeaderSummary {
  return {
    suggested_technology: {
      value: "nanopore", confidence: "high", basis: "single_platform", platforms: ["nanopore"],
      files_considered: 1, files_with_evidence: 1, ...overrides,
    },
    per_file: [],
    mate_check: [],
    user_technology: "unknown",
    agrees: null,
    ...rest,
  };
}

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("header helpers", () => {
  it("picks the most frequent usable format, ties by name as the server does", () => {
    expect(dominantFormat(meta({ format_counts: { empty: 5, ont_minknow_kv: 3, uuid_read_id: 1 } }))).toBe("ont_minknow_kv");
    expect(dominantFormat(meta({ format_counts: { a_fmt: 2, b_fmt: 2 } }))).toBe("b_fmt");
    expect(dominantFormat(meta({ format_counts: { invalid: 3 } }))).toBeNull();
    expect(dominantFormat(null)).toBeNull();
  });

  it("lists distinct values in a fixed order and skips empty ones", () => {
    const rows = distinctRows(
      meta({
        distinct: {
          lane: { values: ["1", "2"], n_distinct: 2, truncated: false },
          instrument: { values: ["A00123"], n_distinct: 1, truncated: false },
          barcode: { values: [], n_distinct: 0, truncated: false },
        },
      }),
    );
    expect(rows.map((r) => r.key)).toEqual(["instrument", "lane"]);
  });

  it("has a label for every distinct field, format and mate layout in both languages", () => {
    for (const key of DISTINCT_FIELDS) expect(codeKey("headers.field", key)).not.toBeNull();
    for (const fmt of ["ont_dorado_hts", "pacbio_ccs_bystrand_segmented", "sra_default_defline", "generic_slash_mate", "unrecognised"]) {
      const key = codeKey("headers.format", fmt)!;
      expect(dictionaries.en[key]).toBeTruthy();
      expect(dictionaries.es[key]).toBeTruthy();
    }
    expect(codeKey("headers.mateLayout", "no_mate_markers")).toBe("headers.mateLayout.no_mate_markers");
    expect(codeKey("headers.format", "some_future_format")).toBeNull();
  });

  it("offers one-click adoption only for an unset technology, medium or high confidence and evidence in every file", () => {
    const s = (value: SequencingTechnology | null, confidence: HeaderConfidence, withEvidence = 2, considered = 2) =>
      ({ value, confidence, files_with_evidence: withEvidence, files_considered: considered });
    expect(suggestionState("unknown", s("nanopore", "high"))).toBe("offer");
    expect(suggestionState("unknown", s("illumina", "medium"))).toBe("offer");
    expect(suggestionState("unknown", s("nanopore", "low"))).toBe("hint");
    expect(suggestionState("unknown", s("nanopore", "medium", 1, 2))).toBe("hint");
    expect(suggestionState("nanopore", s("nanopore", "high"))).toBe("agrees");
    expect(suggestionState("illumina", s("hybrid", "high"))).toBe("mismatch");
    expect(suggestionState("hybrid", s("nanopore", "medium", 1, 2))).toBe("undecided");
    expect(suggestionState("illumina", s("nanopore", "medium", 1, 2))).toBe("mismatch");
    expect(suggestionState("hybrid", s("nanopore", "high"))).toBe("mismatch");
    expect(suggestionState("unknown", s(null, "none"))).toBe("none");
    expect(suggestionState("unknown", null)).toBe("none");
  });

  it("links only plain https sources", () => {
    const links = documentationLinks({
      a: ["https://en.wikipedia.org/wiki/FASTQ_format (community source)", "bcl2fastq2 v2.20 Software Guide"],
      b: ["javascript:alert(1)", "https://en.wikipedia.org/wiki/FASTQ_format (community source)"],
    });
    expect(links).toEqual([
      { text: "https://en.wikipedia.org/wiki/FASTQ_format (community source)", href: "https://en.wikipedia.org/wiki/FASTQ_format" },
      { text: "bcl2fastq2 v2.20 Software Guide", href: null },
      { text: "javascript:alert(1)", href: null },
    ]);
  });
});

describe("TechnologySuggestion", () => {
  beforeEach(() => useSettings.setState({ language: "en" }));
  afterEach(() => vi.restoreAllMocks());

  it("changes the sample only after 'Use this' is clicked", async () => {
    const update = vi.spyOn(api, "updateSample").mockResolvedValue({ ...sample("nanopore") });
    wrap(<TechnologySuggestion sample={sample("unknown")} summary={summary()} />);
    expect(screen.getByText("Suggested from read headers: Oxford Nanopore (high)")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Use this" });
    expect(button).toHaveAccessibleDescription(/Sets the sample's sequencing technology to Oxford Nanopore/);
    expect(update).not.toHaveBeenCalled();
    await userEvent.click(button);
    expect(update).toHaveBeenCalledWith("s1", { sequencing_technology: "nanopore" });
  });

  it("shows a low-confidence suggestion as a hint without a button", () => {
    wrap(<TechnologySuggestion sample={sample("unknown")} summary={summary({ confidence: "low" })} />);
    expect(screen.getByText("Suggested from read headers: Oxford Nanopore (low)")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/too weak or incomplete to offer it as a one-click choice/)).toBeInTheDocument();
  });

  it("says how many files carry evidence and does not call a partial match a mismatch for hybrid samples", () => {
    wrap(
      <TechnologySuggestion
        sample={sample("hybrid")}
        summary={summary({ confidence: "medium", files_considered: 2, files_with_evidence: 1 })}
      />,
    );
    expect(screen.getByText("Only 1 of 2 files carry platform information.")).toBeInTheDocument();
    expect(screen.getByText(/neither confirms nor contradicts Hybrid/)).toBeInTheDocument();
    expect(screen.queryByText(/but the sample records/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a neutral notice instead of a button when the user value differs", () => {
    wrap(<TechnologySuggestion sample={sample("illumina")} summary={summary()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/the sample records Illumina.*ARVA keeps your value/)).toBeInTheDocument();
  });

  it("renders nothing without a suggestion", () => {
    const { container } = wrap(<TechnologySuggestion sample={sample("unknown")} summary={summary({ value: null, basis: "no_evidence" })} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ReadHeadersCard", () => {
  beforeEach(() => useSettings.setState({ language: "en" }));

  it("says honestly that synthetic headers are not inferable", () => {
    const files = [file("r1", "SYNTHETIC_illumina_R1_001.fastq.gz", meta(), "R1"), file("old", "old.fastq.gz", null)];
    wrap(
      <ReadHeadersCard
        files={files}
        summary={summary(
          { value: null, confidence: "none", basis: "no_evidence", platforms: [], files_with_evidence: 0 },
          { mate_check: [{ r1_file_id: "r1", r2_file_id: "r2", looks_like_pair: false, matched: 3, compared: 200, note: "different_read_names" }] },
        )}
      />,
    );
    expect(screen.getByText(/No file's headers reveal the sequencing platform/)).toBeInTheDocument();
    const row = screen.getByText("SYNTHETIC_illumina_R1_001.fastq.gz").closest("li")!;
    expect(within(row).getByText("Not inferable", { selector: "span" })).toBeInTheDocument();
    expect(within(row).getAllByText("Generic /1 /2 mate suffix (no platform information)").length).toBeGreaterThan(0);
    expect(screen.getByText("Not summarised")).toBeInTheDocument();
    expect(screen.getByText(/could not be summarised for this file\. ARVA tries again/)).toBeInTheDocument();
    expect(screen.getByText(/do not look like the same reads: 3 of 200 read names match/)).toBeInTheDocument();
  });

  it("renders header values as text, never as HTML", () => {
    const evil = "<img src=x onerror=alert(1)>";
    const m = meta({
      format_counts: { ont_minknow_kv: 5 },
      platform_counts: { nanopore: 5 },
      distinct: { sample_id: { values: [evil], n_distinct: 30, truncated: true } },
      suggested_technology: { ...meta().suggested_technology, value: "nanopore", confidence: "high" },
      sources: { ont_minknow_kv: ["https://software-docs.nanoporetech.com/output-specifications/latest/read_formats/fastq/"] },
    });
    const { container } = wrap(<ReadHeadersCard files={[file("f", "ont.fastq", m)]} summary={summary()} />);
    expect(screen.getByText(evil)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/30 distinct · only the 1 most frequent are listed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /software-docs\.nanoporetech\.com/ })).toHaveAttribute("rel", "noreferrer noopener");
  });
});
