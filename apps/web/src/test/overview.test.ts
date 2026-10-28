import { describe, expect, it } from "vitest";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import { escapeHtml } from "@/lib/format";
import { filterQcRows, missingStatsReason, qcSortValue, sequencingOverview, sortQcRows, technologiesIn } from "@/lib/overview";
import type { AnalysisJobDetail, QcOverviewRow, RawFile, SequenceStats } from "@/lib/types";

const file = (id: string, extra: Partial<RawFile> = {}): RawFile => ({
  id,
  sample_id: "s",
  original_filename: `${id}.fastq.gz`,
  file_format: "fastq_gz",
  read_mate: null,
  size_bytes: 1,
  checksum_sha256: null,
  is_valid: true,
  validation_message: null,
  uploaded_at: "2026-01-01T00:00:00Z",
  origin: "imported",
  parent_file_id: null,
  produced_by_job_id: null,
  description: null,
  header_metadata: null,
  ...extra,
});

const metrics = (total_bases: number) => ({ total_bases, read_count: total_bases / 100 }) as SequenceStats;

const job = (id: string, type: string, inputs: string[], status: AnalysisJobDetail["status"], extra: Partial<AnalysisJobDetail> = {}) =>
  ({
    id,
    job_type: type,
    tool_name: type === "fastp" ? "fastp" : "arva-core.seqstats",
    tool_version: type === "fastp" ? "0.23.4" : "0.2.0",
    input_raw_file_ids: inputs,
    status,
    qc_results: [],
    result_summary: null,
    ...extra,
  }) as unknown as AnalysisJobDetail;

const statsJob = (id: string, fileId: string, bases: number) =>
  job(id, "sequence_stats", [fileId], "completed", {
    qc_results: [{ raw_file_id: fileId, metrics: metrics(bases) }] as AnalysisJobDetail["qc_results"],
  });

describe("sequencingOverview", () => {
  const r1 = file("r1", { read_mate: "R1" });
  const r2 = file("r2", { read_mate: "R2" });
  const kept = file("k1", { origin: "derived", parent_file_id: "r1", produced_by_job_id: "fp" });
  const pod5 = file("sig", { file_format: "pod5", original_filename: "run.pod5" });
  const other = file("x", { file_format: "unknown", original_filename: "notes.txt" });
  // Newest first, as the API returns them.
  const jobs = [
    statsJob("st-k1", "k1", 900),
    job("st-r2-new", "sequence_stats", ["r2"], "running"),
    job("fp", "fastp", ["r1"], "completed"),
    statsJob("st-r1", "r1", 1000),
    job("st-r2-old", "sequence_stats", ["r2"], "failed"),
    job("p5", "pod5_summary", ["sig"], "completed", { result_summary: { reads: { count: 12, total_signal_duration_s: 7200 } } }),
  ];
  const rows = sequencingOverview([r1, r2, pod5, other, kept], jobs);

  it("lists derived files right after their parent, with the producing tool", () => {
    expect(rows.map((r) => [r.file.id, r.depth])).toEqual([["r1", 0], ["k1", 1], ["r2", 0], ["sig", 0], ["x", 0]]);
    const derived = rows[1];
    expect(derived.parent?.id).toBe("r1");
    expect(derived.producer).toBe("fastp 0.23.4");
    expect(derived.shareOfParent).toBeCloseTo(90);
  });

  it("takes values only from completed jobs and says why others have none", () => {
    expect(rows[0].stats?.total_bases).toBe(1000);
    expect(rows[0].statsVersion).toBe("0.2.0");
    expect([rows[2].stats, rows[2].state]).toEqual([null, "running"]);
    expect(sequencingOverview([r2], jobs.slice(2))[0].state).toBe("failed");
    expect(sequencingOverview([r2], [])[0].state).toBe("not_run");
  });

  it("reads POD5 reads and signal duration from the pod5 job, and leaves unknown files alone", () => {
    expect(rows[3]).toMatchObject({ kind: "signal", state: "done", signal: { reads: 12, durationS: 7200 }, stats: null });
    expect(sequencingOverview([pod5], [])[0]).toMatchObject({ kind: "signal", state: "not_run", signal: null });
    expect(rows[4]).toMatchObject({ kind: "other", state: "not_applicable", stats: null });
  });
});

const row = (code: string, extra: Partial<QcOverviewRow> = {}): QcOverviewRow => ({
  sample_id: code,
  sample_code: code,
  sequencing_technology: "illumina",
  imported_files: 2,
  derived_files: 0,
  imported_read_files: 2,
  imported_read_files_with_stats: 2,
  stats_tool_versions: ["0.2.0"],
  total_reads: 100,
  total_bases: 1000,
  largest_file: null,
  n50: 150,
  mean_read_quality: 30,
  q30_percent: 90,
  gc_percent: 50,
  expected_genome_size_bp: null,
  genome_size_status: "not_given",
  estimated_depth: null,
  filtering: null,
  fastqc: { files: 0, files_total: 2, pass_count: 0, warn_count: 0, fail_count: 0 },
  seqkit: { status: "not_run", files_checked: 0, files_total: 2, differing_metrics: [] },
  ...extra,
});

describe("project QC overview helpers", () => {
  const rows = [
    row("S10", { total_bases: 5000, sequencing_technology: "nanopore", seqkit: { status: "agree", files_checked: 2, files_total: 2, differing_metrics: [] } }),
    row("S2", { total_bases: null, imported_read_files_with_stats: 1 }),
    row("S1", { total_bases: 2000, seqkit: { status: "disagree", files_checked: 2, files_total: 2, differing_metrics: ["N50"] } }),
  ];

  it("sorts sample IDs naturally and numbers numerically", () => {
    expect(sortQcRows(rows, "sample", "asc").map((r) => r.sample_code)).toEqual(["S1", "S2", "S10"]);
    expect(sortQcRows(rows, "sample", "desc").map((r) => r.sample_code)).toEqual(["S10", "S2", "S1"]);
    expect(sortQcRows(rows, "bases", "asc").map((r) => r.sample_code)).toEqual(["S1", "S10", "S2"]);
  });

  it("puts samples without a value last in both directions", () => {
    expect(sortQcRows(rows, "bases", "desc").map((r) => r.sample_code)).toEqual(["S10", "S1", "S2"]);
    expect(sortQcRows(rows, "seqkit", "asc").map((r) => r.sample_code)).toEqual(["S1", "S10", "S2"]);
    expect(sortQcRows(rows, "seqkit", "desc").map((r) => r.sample_code)).toEqual(["S10", "S1", "S2"]);
  });

  it("sorts FastQC by FAIL count only where FastQC ran, and filtering by bases kept", () => {
    expect(qcSortValue(row("a"), "fastqc")).toBeNull();
    expect(qcSortValue(row("a", { fastqc: { files: 1, files_total: 2, pass_count: 8, warn_count: 2, fail_count: 1 } }), "fastqc")).toBe(1);
    expect(qcSortValue(row("a"), "kept")).toBeNull();
  });

  it("filters by technology and lists the technologies present in a fixed order", () => {
    expect(filterQcRows(rows, "nanopore").map((r) => r.sample_code)).toEqual(["S10"]);
    expect(filterQcRows(rows, "all")).toHaveLength(3);
    expect(technologiesIn(rows)).toEqual(["illumina", "nanopore"]);
  });

  it("explains why totals are missing", () => {
    expect(missingStatsReason(row("a"))).toBeNull();
    expect(missingStatsReason(row("a", { imported_read_files_with_stats: 1 }))).toBe("incomplete");
    expect(missingStatsReason(row("a", { imported_read_files: 0, imported_files: 1 }))).toBe("no_read_files");
    expect(missingStatsReason(row("a", { imported_read_files: 0, imported_files: 0 }))).toBe("no_files");
  });
});

describe("overview text", () => {
  it("escapes user-supplied names placed in chart tooltips", () => {
    expect(escapeHtml(`<img src=x onerror="alert('1')">&`)).toBe("&lt;img src=x onerror=&quot;alert(&#39;1&#39;)&quot;&gt;&amp;");
  });

  it("has every overview string in English and Spanish and a Guide entry", () => {
    const keys = Object.keys(dictionaries.en).filter((k) => k.startsWith("overview.") || k.startsWith("qcOverview."));
    expect(keys.length).toBeGreaterThan(50);
    for (const k of keys) expect((dictionaries.es as Record<string, string>)[k], k).toBeTruthy();
    expect(GUIDE_BY_ID.qc_overview.es.title).toMatch(/QC/);
  });

  it("explains the SeqKit check statuses as the server assigns them", () => {
    // qc_overview._seqkit: any differing metric of any checked file is 'disagree'; 'partial' means some files unchecked.
    const { en, es } = GUIDE_BY_ID.qc_overview;
    expect(en.how).toContain("'differs' when at least one metric of at least one checked file differs");
    expect(en.how).toContain("'agrees (n of m files)' when only some files were checked and those agree");
    expect(es.how).toContain("«difiere» cuando al menos una métrica de al menos un archivo verificado difiere");
    expect(`${en.how} ${es.how}`).not.toMatch(/on none \(differs\)|en ninguno \(difiere\)/);
  });
});
