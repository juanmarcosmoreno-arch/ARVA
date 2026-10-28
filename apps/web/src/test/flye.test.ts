import { describe, expect, it } from "vitest";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import {
  FLYE_FORM_DEFAULTS,
  READ_TYPES,
  chosenGenomeSize,
  defaultFlyeSelection,
  flyeCandidates,
  flyeProblems,
  flyeRequestParams,
  selectedTwice,
  stageStates,
  type FlyeForm,
} from "@/lib/flye";
import { jobLabel } from "@/lib/results";
import type { FlyePlan, RawFile } from "@/lib/types";

const file = (id: string, extra: Partial<RawFile> = {}): RawFile =>
  ({ id, original_filename: `${id}.fastq.gz`, file_format: "fastq_gz", is_valid: true, read_mate: null, origin: "imported", parent_file_id: null, ...extra }) as RawFile;

const plan = (over: Partial<FlyePlan["genome_size"]> = {}, tool: Partial<FlyePlan["tool"]> = {}): FlyePlan =>
  ({
    tool: { status: "available", version: "2.9.3", version_validated: true, message: "", reason: null, options: ["--meta"], max_threads: 4, ...tool },
    files: [],
    read_type_suggestion: {} as FlyePlan["read_type_suggestion"],
    genome_size: { expected: { bp: 300_000, status: "given", source: "read_statistics" }, total_read_bases: 9_869_520, files_without_stats: [], from_depth: { depth_x: 30, total_read_bases: 9_869_520, bp: 328_984 }, ...over },
    sample_technology: "nanopore",
    long_reads_confirmation_required: false,
  }) as FlyePlan;

const form = (over: Partial<FlyeForm> = {}): FlyeForm => ({ ...FLYE_FORM_DEFAULTS, readType: "nano-hq", ...over });

describe("Flye inputs", () => {
  const files = [
    file("ont"),
    file("ont_filtered", { origin: "derived", parent_file_id: "ont" }),
    file("ont_filtered_again", { origin: "derived", parent_file_id: "ont_filtered" }),
    file("r1", { read_mate: "R1" }),
    file("pod5", { file_format: "pod5" }),
    file("bad", { is_valid: false }),
    file("contigs", { file_format: "fasta" }),
  ];

  it("offers valid long-read FASTQ files only and preselects the imported ones", () => {
    expect(flyeCandidates(files).map((f) => f.id)).toEqual(["ont", "ont_filtered", "ont_filtered_again"]);
    expect(defaultFlyeSelection(files)).toEqual(["ont"]);
  });

  it("flags a filtered file selected together with any file it was filtered from", () => {
    expect(selectedTwice(files, new Set(["ont", "ont_filtered_again"])).map((f) => f.id)).toEqual(["ont_filtered_again"]);
    expect(selectedTwice(files, new Set(["ont_filtered"]))).toEqual([]);
  });
});

describe("Flye form", () => {
  it("sends the genome size with its basis, and only the estimate made for the depth typed", () => {
    expect(chosenGenomeSize(form(), plan())).toEqual({ bp: null, basis: null, depth: null, pending: false });
    expect(chosenGenomeSize(form({ genomeChoice: "expected" }), plan())).toMatchObject({ bp: 300_000, basis: "expected_genome_size" });
    expect(chosenGenomeSize(form({ genomeChoice: "depth", depthX: "30" }), plan())).toMatchObject({ bp: 328_984, basis: "reads_over_depth", depth: 30 });
    expect(chosenGenomeSize(form({ genomeChoice: "depth", depthX: "40" }), plan())).toMatchObject({ bp: null, pending: true });
    expect(chosenGenomeSize(form({ genomeChoice: "entered", enteredMbp: "2.8" }), plan())).toMatchObject({ bp: 2_800_000, basis: "entered" });
    const params = flyeRequestParams(form({ genomeChoice: "depth", depthX: "30", minOverlap: "3000", threads: "2" }), plan());
    expect(params).toMatchObject({ read_type: "nano-hq", genome_size_bp: 328_984, genome_size_basis: "reads_over_depth", assumed_depth_x: 30, iterations: 1, min_overlap: 3000, asm_coverage: null, read_error: null, threads: 2 });
    expect(flyeRequestParams(form(), plan())).toMatchObject({ genome_size_bp: null, assumed_depth_x: null, min_overlap: null, threads: null });
  });

  it("lists every problem before anything is sent", () => {
    expect(flyeProblems(form(), plan(), 1, false)).toEqual([]);
    expect(flyeProblems(form({ readType: "" }), plan(), 0, false)).toEqual(["flye.problem.files", "flye.problem.readType"]);
    expect(flyeProblems(form({ iterations: "11", minOverlap: "999", threads: "5" }), plan(), 1, false)).toEqual([
      "flye.problem.iterations", "flye.problem.minOverlap", "flye.problem.threads"]);
    expect(flyeProblems(form({ asmCoverage: "40" }), plan(), 1, false)).toEqual(["flye.problem.asmCoverage"]);
    expect(flyeProblems(form({ asmCoverage: "40", genomeChoice: "entered", enteredMbp: "5", meta: true }), plan(), 1, false)).toEqual(["flye.problem.asmCoverage"]);
    expect(flyeProblems(form({ readType: "nano-raw", readError: "0.03" }), plan(), 1, false)).toEqual(["flye.problem.readError"]);
    expect(flyeProblems(form({ genomeChoice: "entered", enteredMbp: "0.0001" }), plan(), 1, false)).toEqual(["flye.problem.genome"]);
    expect(flyeProblems(form({ genomeChoice: "depth", depthX: "" }), plan(), 1, false)).toEqual(["flye.problem.depth"]);
    expect(flyeProblems(form({ genomeChoice: "depth", depthX: "45" }), plan(), 1, false)).toEqual(["flye.problem.depthPending"]);
    const unknownTech = { ...plan(), long_reads_confirmation_required: true };
    expect(flyeProblems(form(), unknownTech, 1, false)).toEqual(["flye.problem.confirm"]);
    expect(flyeProblems(form(), unknownTech, 1, true)).toEqual([]);
  });
});

describe("Flye progress", () => {
  const progress = {
    tool: "Flye", stage: "repeat", stage_index: 4, stages_total: 7, started_at: null, stage_started_at: null, updated_at: null,
    elapsed_seconds: 12, finished: false, stages: ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"],
  };

  it("marks stages done, current, failed and waiting", () => {
    const running = stageStates({ status: "running", progress });
    expect(running.map((s) => s.state)).toEqual(["done", "done", "done", "current", "waiting", "waiting", "waiting"]);
    expect(stageStates({ status: "failed", progress })[3].state).toBe("failed");
    expect(stageStates({ status: "completed", progress: { ...progress, stage: "finalize" } }).every((s) => s.state === "done")).toBe(true);
    expect(stageStates({ status: "pending", progress: null })).toEqual([]);
  });
});

describe("Flye texts", () => {
  it("has every Flye and assembly string in English and Spanish", () => {
    const keys = Object.keys(dictionaries.en).filter((k) => k.startsWith("flye.") || k.startsWith("assembly."));
    expect(keys.length).toBeGreaterThan(100);
    for (const k of keys) expect((dictionaries.es as Record<string, string>)[k], k).toBeTruthy();
    for (const r of READ_TYPES) expect(dictionaries.en[r.label]).toContain(`--${r.value}`);
    for (const code of ["many_contigs", "genome_size_mismatch", "low_coverage_contigs", "high_coverage_contigs", "chromosome_not_circular", "gc_outlier_contigs"]) {
      expect(dictionaries.en, code).toHaveProperty(`assembly.warning.${code}`);
    }
    for (const stage of progressStages) expect(dictionaries.es, stage).toHaveProperty(`assembly.stage.${stage}`);
    expect(jobLabel("flye_assembly", (k) => dictionaries.es[k])).toBe("Ensamblaje (Flye)");
    expect(GUIDE_BY_ID.flye.references.some((r) => r.url === "https://doi.org/10.1038/s41587-019-0072-8")).toBe(true);
  });
});

const progressStages = ["configure", "assembly", "consensus", "repeat", "contigger", "polishing", "finalize"];
