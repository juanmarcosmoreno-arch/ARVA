import { describe, expect, it } from "vitest";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries } from "@/i18n";
import {
  FLYE_FORM_DEFAULTS,
  READ_TYPES,
  chosenGenomeSize,
  defaultFlyeSelection,
  flyeCandidates,
  flyeFormFromJob,
  flyeMemory,
  flyeProblems,
  flyeRequestParams,
  initialFlyeChoices,
  memoryFailure,
  rememberFlyeChoices,
  selectedTwice,
  stageStates,
  type FlyeForm,
} from "@/lib/flye";
import { jobLabel } from "@/lib/results";
import type { FlyeMemory, FlyePlan, RawFile } from "@/lib/types";

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

  it("offers valid long-read FASTQ files only and preselects the most recent filtered copy of each run", () => {
    expect(flyeCandidates(files).map((f) => f.id)).toEqual(["ont", "ont_filtered", "ont_filtered_again"]);
    // Same time: the deepest in the lineage.
    expect(defaultFlyeSelection(files)).toEqual(["ont_filtered_again"]);
    // The most recent filtered file wins; a second run without a filtered copy keeps its original.
    const timed = [
      file("ont", { uploaded_at: "2026-10-01T10:00:00Z" }),
      file("a", { origin: "derived", parent_file_id: "ont", uploaded_at: "2026-10-03T10:00:00Z" }),
      file("b", { origin: "derived", parent_file_id: "ont", uploaded_at: "2026-10-02T10:00:00Z" }),
      file("run2", { uploaded_at: "2026-10-01T11:00:00Z" }),
    ];
    expect(defaultFlyeSelection(timed)).toEqual(["a", "run2"]);
    // Without filtered files, the imported ones.
    expect(defaultFlyeSelection([file("ont"), file("run2")])).toEqual(["ont", "run2"]);
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

describe("Flye choices kept and retried", () => {
  const files = [file("ont"), file("ont_filtered", { origin: "derived", parent_file_id: "ont" })];

  it("keeps what the user chose for the sample while its files stay the same", () => {
    expect(initialFlyeChoices("s1", files)).toMatchObject({ selected: ["ont_filtered"], form: FLYE_FORM_DEFAULTS, confirmed: false });
    const chosen = { ...FLYE_FORM_DEFAULTS, readType: "nano-raw" as const, asmCoverage: "40" };
    rememberFlyeChoices("s1", { selected: ["ont"], candidates: ["ont", "ont_filtered"], form: chosen, confirmed: true });
    expect(initialFlyeChoices("s1", files)).toMatchObject({ selected: ["ont"], form: chosen, confirmed: true });
    // Another sample starts from ARVA's preselection.
    expect(initialFlyeChoices("s2", files).form.readType).toBe("");
    // A new filtered file brings the preselection back for the files; the options are kept.
    const more = [...files, file("ont_filtered_2", { origin: "derived", parent_file_id: "ont", uploaded_at: "2026-11-01T00:00:00Z" })];
    expect(initialFlyeChoices("s1", more)).toMatchObject({ selected: ["ont_filtered_2"], form: chosen });
  });

  it("fills the form from a failed run's recorded settings to retry it", () => {
    const parameters = { read_type: "nano-raw", genome_size_bp: 2_800_000, genome_size_basis: "entered", assumed_depth_x: null, iterations: 1, min_overlap: null, asm_coverage: 40, read_error: null, meta: false, keep_haplotypes: false, no_alt_contigs: false, scaffold: false, threads: 4, long_reads_confirmed: false };
    const form = flyeFormFromJob(parameters);
    expect(form).toMatchObject({ readType: "nano-raw", genomeChoice: "entered", enteredMbp: "2.8", asmCoverage: "40", iterations: "1", threads: "4", meta: false });
    expect(flyeRequestParams(form, undefined)).toMatchObject({ read_type: "nano-raw", genome_size_bp: 2_800_000, genome_size_basis: "entered", asm_coverage: 40 });
    expect(flyeFormFromJob({ ...parameters, genome_size_basis: "expected_genome_size" }).genomeChoice).toBe("expected");
    expect(flyeFormFromJob({ ...parameters, genome_size_basis: "reads_over_depth", assumed_depth_x: 50 })).toMatchObject({ genomeChoice: "depth", depthX: "50" });
    expect(flyeFormFromJob({ ...parameters, genome_size_bp: null, genome_size_basis: null, asm_coverage: null })).toMatchObject({ genomeChoice: "none", asmCoverage: "" });
    // The retried run's own files, never a remembered choice.
    rememberFlyeChoices("s1", { selected: ["ont_filtered"], candidates: ["ont", "ont_filtered"], form: FLYE_FORM_DEFAULTS, confirmed: false });
    expect(initialFlyeChoices("s1", files, { parameters, input_raw_file_ids: ["ont", "gone"] })).toMatchObject({ selected: ["ont"], form: { readType: "nano-raw", asmCoverage: "40" } });
    expect(memoryFailure({ error_detail: { code: "flye_out_of_memory", params: {} } })).toBe(true);
    expect(memoryFailure({ error_detail: { code: "out_of_memory", params: { tool: "Flye" } } })).toBe(true);
    expect(memoryFailure({ error_detail: { code: "flye_no_long_reads", params: {} } })).toBe(false);
  });
});

describe("Flye memory estimate", () => {
  const memory: FlyeMemory = { reference: { source: "Flye docs", url: "", genome: "E. coli", data: "PB 50x", genome_size_bp: 4_600_000, coverage_x: 50, ram_gb: 2 }, reference_bases: 230_000_000, available_gb: 3, read_bases: 413_000_000, estimate_gb: 3.59, verdict: "may_not_fit", expected_genome_size_bp: 2_800_000 };
  const withMemory = (m: Partial<FlyeMemory> = {}): FlyePlan => ({ ...plan({ expected: { bp: 2_800_000, status: "given", source: "read_statistics" } }), memory: { ...memory, ...m } });

  it("matches the server's figures and suggests Flye's documented --asm-coverage with the expected size", () => {
    const m = flyeMemory(FLYE_FORM_DEFAULTS, withMemory());
    expect(m).toEqual({ verdict: "may_not_fit", estimateGb: 3.59, availableGb: 3, floorGb: 0, suggestion: { asmCoverage: 40, genomeBp: 2_800_000, estimateGb: 0.97 } });
  });

  it("never estimates below Flye's fixed k-mer table, and offers no --asm-coverage when the container is below it", () => {
    // The user's Mac: 413 Mb of reads, 5.9 GB in the Docker container; Flye 2.9.6 needs 8 GiB for its k-mer table.
    const mac = withMemory({ floor_gb: 8.6, available_gb: 5.9 });
    expect(flyeMemory(FLYE_FORM_DEFAULTS, mac)).toEqual({ verdict: "below_floor", estimateGb: 8.6, availableGb: 5.9, floorGb: 8.6, suggestion: null });
    const asm: FlyeForm = { ...FLYE_FORM_DEFAULTS, genomeChoice: "expected", asmCoverage: "40" };
    expect(flyeMemory(asm, mac)).toMatchObject({ verdict: "below_floor", estimateGb: 8.6, suggestion: null });
    // Known before any read statistics: the floor does not depend on the reads.
    expect(flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ floor_gb: 8.6, available_gb: 5.9, read_bases: null }))?.verdict).toBe("below_floor");
    // Enough memory: the floor is the estimate for small reads; large reads may still not fit, and then
    // --asm-coverage is offered with an estimate that does not go below the floor.
    expect(flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ floor_gb: 8.6, available_gb: 15.7 }))).toMatchObject({ verdict: "fits", estimateGb: 8.6 });
    const big = flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ floor_gb: 8.6, available_gb: 15.7, read_bases: 2_300_000_000 }));
    expect(big).toMatchObject({ verdict: "may_not_fit", estimateGb: 20, suggestion: { asmCoverage: 40, estimateGb: 8.6 } });
    // The container's memory could not be read: no verdict.
    expect(flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ floor_gb: 8.6, available_gb: null }))?.verdict).toBe("unknown");
  });

  it("suggests no --asm-coverage when 40x of the genome size is more than the reads hold", () => {
    const m = flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ expected_genome_size_bp: 12_000_000 }));
    expect(m).toMatchObject({ verdict: "may_not_fit", suggestion: null });
  });

  it("follows the form: --asm-coverage with a genome size fits, --meta gets no suggestion, no statistics no estimate", () => {
    const form: FlyeForm = { ...FLYE_FORM_DEFAULTS, genomeChoice: "expected", asmCoverage: "50" };
    expect(flyeMemory(form, withMemory())).toMatchObject({ verdict: "fits", estimateGb: 1.22, suggestion: null });
    expect(flyeMemory({ ...FLYE_FORM_DEFAULTS, meta: true }, withMemory())?.suggestion).toBeNull();
    expect(flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ read_bases: null }))?.verdict).toBe("unknown");
    expect(flyeMemory(FLYE_FORM_DEFAULTS, withMemory({ expected_genome_size_bp: null }))?.suggestion?.genomeBp).toBeNull();
    expect(flyeMemory(FLYE_FORM_DEFAULTS, plan())).toBeNull();
  });
});
