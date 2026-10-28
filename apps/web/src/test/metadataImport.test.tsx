import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CustomMetadataList, MetadataImportDialog } from "@/components/domain/MetadataImport";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { api, metadataForm } from "@/lib/api";
import { messageText } from "@/lib/messages";
import {
  METADATA_FIELDS,
  applyCustomEdits,
  applyPlan,
  currentMapping,
  customDraft,
  customEditsChange,
  customEntries,
  delimiterName,
  duplicateTargets,
  filterRows,
  shortSha,
  showDateOrder,
  summariseMapping,
} from "@/lib/metadataImport";
import type { MetadataApplyResult, MetadataColumn, MetadataPreview, MetadataRowPreview, Sample } from "@/lib/types";
import { useSettings } from "@/store/settings";

const SHA = "a".repeat(64);
const EMPTY_CODE = { code: "sample_code_empty", params: {}, text: "sample_code is empty" };

const row = (overrides: Partial<MetadataRowPreview> = {}): MetadataRowPreview => ({
  row: 2,
  sample_code: "S1",
  action: "create",
  sample_id: null,
  matched_sample_code: null,
  matched_by: null,
  changes: [{ field: "sample_code", key: null, old: null, new: "S1" }],
  errors: [],
  warnings: [],
  ...overrides,
});

const columns: MetadataColumn[] = [
  { header: "Sample ID", field: "sample_code", suggested_field: "sample_code" },
  { header: "Hospedador", field: "host", suggested_field: "host" },
  { header: "MLST", field: "custom", suggested_field: "custom" },
];

const preview = (overrides: Partial<MetadataPreview> = {}): MetadataPreview => ({
  file: { name: "meta.csv", sha256: SHA, kind: "csv", encoding: "utf-8", delimiter: ";", sheet: null, sheets: [], header_row: 1 },
  columns,
  fields: [...METADATA_FIELDS, "custom", "ignore"],
  rows: [
    row(),
    row({
      row: 3, sample_code: "s2", action: "update", sample_id: "id2", matched_sample_code: "S2", matched_by: "case_insensitive",
      changes: [{ field: "host", key: null, old: "Gallus gallus", new: "Bos taurus" }, { field: "custom_metadata", key: "MLST", old: null, new: "ST131" }],
    }),
    row({ row: 4, sample_code: null, action: "error", changes: [], errors: [EMPTY_CODE] }),
  ],
  warnings: [{ code: "csv_cp1252", params: {}, text: "The file is not valid UTF-8, so it was read as Windows-1252." }],
  errors: [],
  counts: { rows: 3, create: 1, update: 1, unchanged: 0, error: 1 },
  date_order: null,
  date_order_source: null,
  ambiguous_dates: 0,
  ...overrides,
});

describe("metadata import helpers", () => {
  it("shows the user's choices over the server mapping and finds fields chosen twice", () => {
    const mapping = currentMapping(columns, { MLST: "ignore" });
    expect(mapping).toEqual({ "Sample ID": "sample_code", Hospedador: "host", MLST: "ignore" });
    expect(duplicateTargets(mapping)).toEqual([]);
    expect(duplicateTargets({ a: "host", b: "host", c: "custom", d: "custom", e: "ignore", f: "ignore" })).toEqual(["host"]);
  });

  it("filters rows by action and computes what Apply writes per mode", () => {
    const p = preview();
    expect(filterRows(p.rows, "all")).toHaveLength(3);
    expect(filterRows(p.rows, "update").map((r) => r.row)).toEqual([3]);
    expect(applyPlan(p.counts, "create_and_update")).toEqual({ create: 1, update: 1, skipped: 1 });
    expect(applyPlan(p.counts, "create_only")).toEqual({ create: 1, update: 0, skipped: 2 });
  });

  it("offers a date order only when ambiguous dates exist or an order applies", () => {
    expect(showDateOrder(preview())).toBe(false);
    expect(showDateOrder(preview({ ambiguous_dates: 2 }))).toBe(true);
    expect(showDateOrder(preview({ date_order: "DMY", date_order_source: "header" }))).toBe(true);
  });

  it("summarises a stored mapping and formats custom metadata and delimiters", () => {
    expect(summariseMapping({ "Sample ID": "sample_code", MLST: "custom", x: "ignore", y: "custom" })).toEqual({
      fields: [["Sample ID", "sample_code"]], custom: ["MLST", "y"], ignored: ["x"],
    });
    expect(customEntries({ MLST: "ST131", depth: 35, tags: ["a"] })).toEqual([["MLST", "ST131"], ["depth", "35"], ["tags", '["a"]']]);
    expect(customEntries(null)).toEqual([]);
    expect([",", ";", "\t", "|", ":"].map(delimiterName)).toEqual(["comma", "semicolon", "tab", "pipe", null]);
    expect(shortSha(SHA)).toHaveLength(12);
  });

  it("edits custom metadata: removed or cleared fields go, untouched values keep their type", () => {
    const original = { Hots: "cow", depth: 35, MLST: "ST131" };
    const draft = customDraft(original);
    expect(customEditsChange(original, draft)).toBe(false);
    expect(applyCustomEdits(original, draft)).toEqual(original);
    draft[0].removed = true;
    draft[2].text = " ST22 ";
    expect(applyCustomEdits(original, draft)).toEqual({ depth: 35, MLST: "ST22" });
    expect(customEditsChange(original, draft)).toBe(true);
    draft[1].text = "";
    draft[2].text = "";
    expect(applyCustomEdits(original, draft)).toBeNull();
  });

  it("sends only the choices that were made", () => {
    const file = new File(["sample\nS1\n"], "m.csv");
    const empty = metadataForm(file, {});
    expect([...empty.keys()]).toEqual(["file"]);
    const full = metadataForm(file, { sheet: "Datos", headerRow: 3, delimiter: "\t", dateOrder: "DMY", mapping: { a: "host" } }, { mode: "create_only" });
    expect(Object.fromEntries([...full.entries()].filter(([k]) => k !== "file"))).toEqual({
      sheet: "Datos", header_row: "3", delimiter: "\t", date_order: "DMY", mapping: '{"a":"host"}', mode: "create_only",
    });
  });

  it("translates server messages by code and falls back to the English text", () => {
    const es = (k: keyof typeof dictionaries.en, vars?: Record<string, string | number>) =>
      dictionaries.es[k].replace(/\{(\w+)\}/g, (_, v: string) => String(vars?.[v] ?? ""));
    expect(messageText(es, "metadata.msg", { code: "date_ambiguous", params: { value: "'03/05/2024'" }, text: "x" })).toBe(
      "'03/05/2024' es ambigua (día/mes o mes/día); usa AAAA-MM-DD o elige el orden de las fechas",
    );
    expect(messageText(es, "metadata.msg", { code: "from_a_newer_server", params: {}, text: "English text" })).toBe("English text");
    expect(messageText(es, "metadata.msg", { code: null, params: {}, text: "free text" })).toBe("free text");
    expect(messageText(es, "pod5.msg", "stored before codes")).toBe("stored before codes");
    expect(messageText(es, "pod5.msg", { code: "no_reads", params: {}, text: "The file contains no reads." })).toBe("El archivo no contiene lecturas.");
  });

  it("has every metadata string in English and Spanish and a guide entry", () => {
    const keys = Object.keys(dictionaries.en).filter((k) => k.startsWith("metadata."));
    expect(keys.length).toBeGreaterThan(50);
    for (const key of keys) expect(dictionaries.es[key as keyof typeof dictionaries.es], key).toBeTruthy();
    for (const f of METADATA_FIELDS) expect(dictionaries.es[`metadata.field.${f}`]).toBeTruthy();
    const entry = GUIDE_BY_ID.metadata_import;
    expect(entry.en.limitations).toContain(".xls");
    expect(entry.es.advanced).toContain("OWASP");
    expect(entry.references.some((r) => r.url.includes("owasp.org"))).toBe(true);
  });
});

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

async function chooseFile() {
  const input = screen.getByLabelText("Choose CSV or Excel file", { selector: "input" });
  const file = new File(["Sample ID;Hospedador;MLST\nS1;cow;ST1\n"], "meta.csv", { type: "text/csv" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

describe("MetadataImportDialog", () => {
  beforeEach(() => useSettings.setState({ language: "en" }));
  afterEach(() => vi.restoreAllMocks());

  it("previews without writing, and applies only after confirmation", async () => {
    const previewSpy = vi.spyOn(api, "previewMetadata").mockResolvedValue(preview());
    const result: MetadataApplyResult = {
      record: {
        id: "imp1", project_id: "p1", filename: "meta.csv", sha256: SHA, kind: "csv", sheet: null, encoding: "utf-8", delimiter: ";",
        header_row: 1, mapping: {}, date_order: null, mode: "create_and_update", created_count: 1, updated_count: 1,
        unchanged_count: 0, skipped_count: 1, created_at: "2026-10-28T00:00:00Z",
      },
      skipped: [{ row: 4, sample_code: null, reasons: [EMPTY_CODE] }],
    };
    const applySpy = vi.spyOn(api, "applyMetadata").mockResolvedValue(result);
    wrap(<MetadataImportDialog open onOpenChange={() => {}} projectId="p1" />);
    const file = await chooseFile();

    expect(await screen.findByText("3 row(s): 1 new, 1 to update, 0 unchanged, 1 with errors")).toBeInTheDocument();
    expect(previewSpy).toHaveBeenCalledWith("p1", file, {});
    expect(screen.getByText("matches the existing sample S2 (letter case differs)")).toBeInTheDocument();
    expect(screen.getByText("Gallus gallus")).toBeInTheDocument();
    expect(screen.getByText("custom: MLST")).toBeInTheDocument();
    expect(screen.getByText(/^The file is not valid UTF-8, so it was read as Windows-1252 \(typical/)).toBeInTheDocument();
    expect(screen.queryByText("Order of ambiguous dates")).not.toBeInTheDocument();

    const applyButton = screen.getByRole("button", { name: "Apply import" });
    expect(applyButton).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /create 1 sample\(s\), update 1 and skip 1 row\(s\)/ }));
    expect(applyButton).toBeEnabled();
    expect(applySpy).not.toHaveBeenCalled();

    await userEvent.click(applyButton);
    expect(await screen.findByText("Import applied: 1 created, 1 updated, 0 unchanged, 1 skipped.")).toBeInTheDocument();
    expect(applySpy).toHaveBeenCalledWith(
      "p1", file,
      { sheet: null, headerRow: 1, delimiter: ";", dateOrder: null, mapping: { "Sample ID": "sample_code", Hospedador: "host", MLST: "custom" } },
      SHA, "create_and_update",
    );
    expect(screen.getByText(/sample_code is empty/)).toBeInTheDocument();
  });

  it("re-previews with the new mapping and blocks a field chosen twice", async () => {
    const previewSpy = vi.spyOn(api, "previewMetadata").mockResolvedValue(preview());
    wrap(<MetadataImportDialog open onOpenChange={() => {}} projectId="p1" />);
    await chooseFile();
    const select = await screen.findByRole("combobox", { name: "Columns: MLST" });
    expect(within(select).getByRole("option", { name: "Custom metadata (suggested)" })).toBeInTheDocument();

    await userEvent.selectOptions(select, "ignore");
    await waitFor(() => expect(previewSpy).toHaveBeenCalledTimes(2));
    expect(previewSpy.mock.calls[1][2]).toMatchObject({ mapping: { "Sample ID": "sample_code", Hospedador: "host", MLST: "ignore" } });

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Columns: MLST" }), "host");
    expect(await screen.findByText("Host: map each ARVA field to only one column.")).toBeInTheDocument();
    expect(previewSpy).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("checkbox", { name: /I have reviewed/ })).toBeDisabled();
  });

  it("asks for a date order when dates are ambiguous", async () => {
    const previewSpy = vi.spyOn(api, "previewMetadata").mockResolvedValue(preview({ ambiguous_dates: 2 }));
    wrap(<MetadataImportDialog open onOpenChange={() => {}} projectId="p1" />);
    await chooseFile();
    expect(await screen.findByText("Order of ambiguous dates")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Day/Month/Year" }));
    await waitFor(() => expect(previewSpy.mock.calls.at(-1)?.[2]).toMatchObject({ dateOrder: "DMY" }));
  });

  it("shows the server's refusal of a file", async () => {
    vi.spyOn(api, "previewMetadata").mockRejectedValue(new Error("Legacy Excel 97-2003 .xls files are not supported"));
    wrap(<MetadataImportDialog open onOpenChange={() => {}} projectId="p1" />);
    await chooseFile();
    expect(await screen.findByRole("alert")).toHaveTextContent(".xls files are not supported");
    expect(screen.queryByRole("button", { name: "Apply import" })).not.toBeInTheDocument();
  });
});

describe("CustomMetadataList", () => {
  beforeEach(() => useSettings.setState({ language: "en" }));
  afterEach(() => vi.restoreAllMocks());

  it("removes a misspelt imported field only after Save", async () => {
    const sample = { id: "s1", sample_code: "S1", custom_metadata: { Hots: "cow", MLST: "ST131" } } as unknown as Sample;
    const update = vi.spyOn(api, "updateSample").mockResolvedValue({ ...sample, custom_metadata: { MLST: "ST131" } });
    wrap(<CustomMetadataList sample={sample} />);
    expect(screen.getByText("Hots")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit custom fields" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove Hots" }));
    expect(update).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(update).toHaveBeenCalledWith("s1", { custom_metadata: { MLST: "ST131" } });
  });
});
