import type { TranslationKey } from "@/i18n";
import { MEDAKA_JOB, PILON_JOB, RACON_JOB } from "./polishing";
import { QUAST_JOB } from "./quast";
import { SPADES_JOB, UNICYCLER_JOB } from "./shortReads";
import type { AnalysisJobDetail, FlyeContigRow, FlyeMemory, FlyeParams, FlyePlan, FlyeReadType, GenomeSizeBasis, JobStatus, RawFile } from "./types";

export const FLYE_JOB = "flye_assembly";
/** Jobs shown in the Assembly tab: assemblers, assembly evaluation and polishing. */
export const IMPORT_ASSEMBLY_JOB = "assembly_import";
export const ASSEMBLY_JOBS = new Set([FLYE_JOB, SPADES_JOB, UNICYCLER_JOB, QUAST_JOB, RACON_JOB, MEDAKA_JOB, PILON_JOB, IMPORT_ASSEMBLY_JOB]);

/** Flye's read-type options with Flye's own descriptions (flye --help). */
export const READ_TYPES: { value: FlyeReadType; label: TranslationKey }[] = [
  { value: "nano-hq", label: "flye.rt.nano-hq" },
  { value: "nano-raw", label: "flye.rt.nano-raw" },
  { value: "nano-corr", label: "flye.rt.nano-corr" },
  { value: "pacbio-hifi", label: "flye.rt.pacbio-hifi" },
  { value: "pacbio-raw", label: "flye.rt.pacbio-raw" },
  { value: "pacbio-corr", label: "flye.rt.pacbio-corr" },
];
/** Flye accepts --read-error only with these read types (flye/main.py). */
export const READ_ERROR_TYPES = new Set<FlyeReadType>(["nano-corr", "nano-hq", "pacbio-corr", "pacbio-hifi"]);
/** Flye's argument ranges (flye/main.py). */
export const LIMITS = { iterations: [0, 10], minOverlap: [1000, 10000], genomeMin: 1000, genomeMax: 10_000_000_000 } as const;

/** FASTQ files Flye can take: valid, and not one mate of a read pair (short reads). */
export const flyeCandidates = (files: RawFile[]) =>
  files.filter((f) => (f.file_format === "fastq" || f.file_format === "fastq_gz") && f.is_valid && !f.read_mate);

/** Preselected files: for each imported long-read file, its most recent filtered copy (a derived file, by when it was
 * written, then the deepest in its lineage) when there is one, else the file itself; so no run is selected twice (as
 * original and filtered copy). */
export function defaultFlyeSelection(files: RawFile[]): string[] {
  const candidates = flyeCandidates(files);
  const byId = new Map(files.map((f) => [f.id, f]));
  const lineage = (f: RawFile) => {
    const chain = [f];
    for (let p = f.parent_file_id ? byId.get(f.parent_file_id) : undefined; p && !chain.includes(p); p = p.parent_file_id ? byId.get(p.parent_file_id) : undefined) chain.push(p);
    return chain;
  };
  const better = (a: RawFile, b: RawFile) => {
    if ((a.origin === "derived") !== (b.origin === "derived")) return a.origin === "derived";
    const [ta, tb] = [a.uploaded_at ?? "", b.uploaded_at ?? ""];
    return ta !== tb ? ta > tb : lineage(a).length > lineage(b).length;
  };
  const best = new Map<string, RawFile>();
  for (const f of candidates) {
    const root = lineage(f).at(-1)!.id;
    const current = best.get(root);
    if (!current || better(f, current)) best.set(root, f);
  }
  const chosen = new Set([...best.values()].map((f) => f.id));
  return candidates.filter((f) => chosen.has(f.id)).map((f) => f.id);
}

/** Selected derived files whose parent (or an earlier ancestor) is selected too: their reads would be used twice. */
export function selectedTwice(files: RawFile[], selected: Set<string>): RawFile[] {
  const byId = new Map(files.map((f) => [f.id, f]));
  return files.filter((f) => {
    if (!selected.has(f.id)) return false;
    for (let p = f.parent_file_id ? byId.get(f.parent_file_id) : undefined; p; p = p.parent_file_id ? byId.get(p.parent_file_id) : undefined) {
      if (selected.has(p.id)) return true;
    }
    return false;
  });
}

export type GenomeChoice = "none" | "expected" | "depth" | "entered";

export interface FlyeForm {
  readType: FlyeReadType | "";
  genomeChoice: GenomeChoice;
  depthX: string;
  enteredMbp: string;
  iterations: string;
  minOverlap: string;
  asmCoverage: string;
  readError: string;
  meta: boolean;
  keepHaplotypes: boolean;
  noAltContigs: boolean;
  scaffold: boolean;
  threads: string;
}

export const FLYE_FORM_DEFAULTS: FlyeForm = {
  readType: "",
  genomeChoice: "none",
  depthX: "",
  enteredMbp: "",
  iterations: "1",
  minOverlap: "",
  asmCoverage: "",
  readError: "",
  meta: false,
  keepHaplotypes: false,
  noAltContigs: false,
  scaffold: false,
  threads: "",
};

const num = (s: string) => (s.trim() === "" ? null : Number(s));
const isInt = (n: number | null): n is number => n !== null && Number.isInteger(n);

/** The genome size the form would send, with its basis; `pending` while the depth estimate is being fetched. */
export function chosenGenomeSize(form: FlyeForm, plan: FlyePlan | undefined): { bp: number | null; basis: GenomeSizeBasis | null; depth: number | null; pending: boolean } {
  const none = { bp: null, basis: null, depth: null, pending: false };
  if (form.genomeChoice === "expected") {
    const bp = plan?.genome_size.expected.status === "given" ? plan.genome_size.expected.bp : null;
    return { ...none, bp, basis: bp ? "expected_genome_size" : null };
  }
  if (form.genomeChoice === "depth") {
    const depth = num(form.depthX);
    const estimate = plan?.genome_size.from_depth;
    const current = estimate && depth !== null && estimate.depth_x === depth;
    return { bp: current ? estimate.bp : null, basis: current ? "reads_over_depth" : null, depth, pending: !current && depth !== null && depth > 0 };
  }
  if (form.genomeChoice === "entered") {
    const mbp = num(form.enteredMbp);
    const bp = mbp !== null && Number.isFinite(mbp) ? Math.round(mbp * 1e6) : null;
    return { ...none, bp, basis: bp ? "entered" : null };
  }
  return none;
}

/** Problems that keep the form from being sent (each an i18n key); the server checks everything again. */
export function flyeProblems(form: FlyeForm, plan: FlyePlan | undefined, fileCount: number, confirmed: boolean): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (!fileCount) out.push("flye.problem.files");
  if (!form.readType) out.push("flye.problem.readType");
  const genome = chosenGenomeSize(form, plan);
  if (form.genomeChoice === "depth") {
    const d = num(form.depthX);
    if (d === null || !(d > 0)) out.push("flye.problem.depth");
    else if (genome.pending) out.push("flye.problem.depthPending");
  }
  if (form.genomeChoice === "entered" || form.genomeChoice === "expected") {
    if (genome.bp === null || genome.bp < LIMITS.genomeMin || genome.bp > LIMITS.genomeMax) out.push("flye.problem.genome");
  }
  const it = num(form.iterations);
  if (!isInt(it) || it < LIMITS.iterations[0] || it > LIMITS.iterations[1]) out.push("flye.problem.iterations");
  const ovl = num(form.minOverlap);
  if (ovl !== null && (!isInt(ovl) || ovl < LIMITS.minOverlap[0] || ovl > LIMITS.minOverlap[1])) out.push("flye.problem.minOverlap");
  const asm = num(form.asmCoverage);
  if (asm !== null && (!isInt(asm) || asm < 1 || genome.bp === null || form.meta)) out.push("flye.problem.asmCoverage");
  const err = num(form.readError);
  if (err !== null && (!(err > 0 && err < 1) || !form.readType || !READ_ERROR_TYPES.has(form.readType))) out.push("flye.problem.readError");
  const th = num(form.threads);
  const max = plan?.tool.max_threads ?? 1;
  if (th !== null && (!isInt(th) || th < 1 || th > max)) out.push("flye.problem.threads");
  if (plan?.long_reads_confirmation_required && !confirmed) out.push("flye.problem.confirm");
  return out;
}

/** The --asm-coverage Flye's manual gives as typically enough (docs/USAGE.md of 2.9.6: "Typically, 40x longest reads
 * is enough"); the same as arva_tools.flye.SUGGESTED_ASM_COVERAGE. */
export const SUGGESTED_ASM_COVERAGE = 40;

export interface FlyeMemoryView {
  verdict: FlyeMemory["verdict"];
  estimateGb: number | null;
  availableGb: number | null;
  /** Flye's fixed k-mer counter floor: no run uses less, whatever the reads or --asm-coverage. */
  floorGb: number;
  /** What Flye documents to use less memory, when the run may not fit, does not use it already and it would help;
   * never when the container is below the floor, which --asm-coverage does not lower. */
  suggestion: { asmCoverage: number; genomeBp: number | null; estimateGb: number | null } | null;
}

const round2 = (v: number) => Math.round(v * 100) / 100;
const scaled = (m: FlyeMemory, bases: number) => round2((m.reference.ram_gb * bases) / m.reference_bases);

/** The server's estimate (arva_tools.flye.memory_estimate) for what the form would send now: the larger of Flye's
 * fixed k-mer counter floor and its documented figure scaled to the bases the first stage reads. */
export function flyeMemory(form: FlyeForm, plan: FlyePlan | undefined): FlyeMemoryView | null {
  const m = plan?.memory;
  if (!m) return null;
  const floor = m.floor_gb ?? 0;
  const available = m.available_gb;
  const below = available !== null && floor > available;
  const view: FlyeMemoryView = { verdict: below ? "below_floor" : "unknown", estimateGb: null, availableGb: available, floorGb: floor, suggestion: null };
  if (!m.read_bases) return view;
  const genome = chosenGenomeSize(form, plan).bp;
  const asm = num(form.asmCoverage);
  const used = asm && genome ? Math.min(m.read_bases, asm * genome) : m.read_bases;
  view.estimateGb = round2(Math.max(scaled(m, used), floor));
  if (below || available === null) return view;
  view.verdict = view.estimateGb <= available ? "fits" : "may_not_fit";
  if (view.verdict === "may_not_fit" && !asm && !form.meta) {
    const size = genome ?? m.expected_genome_size_bp;
    // With a known size, only when it would use fewer bases than the reads hold (as the server decides).
    if (!size || SUGGESTED_ASM_COVERAGE * size < m.read_bases) {
      view.suggestion = { asmCoverage: SUGGESTED_ASM_COVERAGE, genomeBp: size, estimateGb: size ? round2(Math.max(scaled(m, SUGGESTED_ASM_COVERAGE * size), floor)) : null };
    }
  }
  return view;
}

/** The form a finished (or failed) Flye job's recorded parameters give, to run it again with the same settings. */
export function flyeFormFromJob(parameters: Record<string, unknown> | null | undefined): FlyeForm {
  const p = (parameters ?? {}) as Partial<FlyeParams>;
  const text = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  const known = READ_TYPES.some((r) => r.value === p.read_type);
  const basis = p.genome_size_basis;
  const genomeChoice: GenomeChoice =
    p.genome_size_bp == null ? "none" : basis === "expected_genome_size" ? "expected" : basis === "reads_over_depth" ? "depth" : "entered";
  return {
    ...FLYE_FORM_DEFAULTS,
    readType: known ? (p.read_type as FlyeReadType) : "",
    genomeChoice,
    depthX: genomeChoice === "depth" ? text(p.assumed_depth_x) : "",
    enteredMbp: genomeChoice === "entered" && p.genome_size_bp ? String(p.genome_size_bp / 1e6) : "",
    iterations: text(p.iterations ?? FLYE_FORM_DEFAULTS.iterations),
    minOverlap: text(p.min_overlap),
    asmCoverage: text(p.asm_coverage),
    readError: text(p.read_error),
    meta: !!p.meta,
    keepHaplotypes: !!p.keep_haplotypes,
    noAltContigs: !!p.no_alt_contigs,
    scaffold: !!p.scaffold,
    threads: text(p.threads),
  };
}

/** Whether a failed job stopped for lack of memory (Flye's own report, or the operating system's SIGKILL). */
export const memoryFailure = (job: Pick<AnalysisJobDetail, "error_detail"> | null | undefined) =>
  job?.error_detail?.code === "flye_out_of_memory" || job?.error_detail?.code === "out_of_memory";

/** What the user chose in the Flye panel, kept per sample for this browser session so that closing and reopening
 * "New assembly" does not lose it. The files chosen are kept only while the sample's long-read files stay the same:
 * a new filtered file brings back the preselection. */
export interface FlyeChoices {
  selected: string[];
  candidates: string[];
  form: FlyeForm;
  confirmed: boolean;
}

const remembered = new Map<string, FlyeChoices>();

export const rememberFlyeChoices = (sampleId: string, choices: FlyeChoices) => remembered.set(sampleId, choices);

/** Forget every remembered choice (tests). */
export const forgetFlyeChoices = () => remembered.clear();

/** The panel's state when "New assembly" opens: a failed run's settings to retry it, else what the user chose last
 * time for this sample, else ARVA's preselection and Flye's defaults. */
export function initialFlyeChoices(sampleId: string, files: RawFile[], retry?: Pick<AnalysisJobDetail, "parameters" | "input_raw_file_ids"> | null): FlyeChoices {
  const candidates = flyeCandidates(files).map((f) => f.id);
  if (retry) {
    const selected = (retry.input_raw_file_ids ?? []).filter((id) => candidates.includes(id));
    return { selected, candidates, form: flyeFormFromJob(retry.parameters), confirmed: !!retry.parameters?.long_reads_confirmed };
  }
  const last = remembered.get(sampleId);
  const sameFiles = last && last.candidates.length === candidates.length && last.candidates.every((id) => candidates.includes(id));
  return {
    selected: sameFiles ? last.selected : defaultFlyeSelection(files),
    candidates,
    form: last?.form ?? FLYE_FORM_DEFAULTS,
    confirmed: last?.confirmed ?? false,
  };
}

export function flyeRequestParams(form: FlyeForm, plan: FlyePlan | undefined): FlyeParams {
  const genome = chosenGenomeSize(form, plan);
  return {
    read_type: form.readType as FlyeReadType,
    genome_size_bp: genome.bp,
    genome_size_basis: genome.basis,
    assumed_depth_x: genome.basis === "reads_over_depth" ? genome.depth : null,
    iterations: Number(form.iterations),
    min_overlap: num(form.minOverlap),
    asm_coverage: num(form.asmCoverage),
    read_error: num(form.readError),
    meta: form.meta,
    keep_haplotypes: form.keepHaplotypes,
    no_alt_contigs: form.noAltContigs,
    scaffold: form.scaffold,
    threads: num(form.threads),
  };
}

/** The advanced options the form sets, as Flye receives them ("--meta", "--min-overlap 3000"); empty means Flye's defaults. */
export function advancedFlags(form: FlyeForm): string[] {
  const out: string[] = [];
  for (const [flag, value] of [["--min-overlap", form.minOverlap], ["--asm-coverage", form.asmCoverage], ["--read-error", form.readError]] as const) {
    if (value.trim() !== "") out.push(`${flag} ${value.trim()}`);
  }
  for (const [flag, on] of [["--meta", form.meta], ["--keep-haplotypes", form.keepHaplotypes], ["--no-alt-contigs", form.noAltContigs], ["--scaffold", form.scaffold]] as const) {
    if (on) out.push(flag);
  }
  return out;
}

export type StageState = "done" | "current" | "failed" | "waiting";

/** Flye's expected stages with their state, from the job's progress and status. */
export function stageStates(job: Pick<AnalysisJobDetail, "progress"> & { status: JobStatus }): { name: string; state: StageState }[] {
  const p = job.progress;
  if (!p) return [];
  // SPAdes can announce a stage name twice (its read error correction): the index says which one is current.
  const at = (p.stage_index ?? 0) - 1;
  const current = p.stage ? (p.stages[at] === p.stage ? at : p.stages.lastIndexOf(p.stage)) : -1;
  return p.stages.map((name, i) => {
    if (job.status === "completed") return { name, state: "done" };
    if (i < current) return { name, state: "done" };
    if (i === current) return { name, state: job.status === "failed" || job.status === "cancelled" ? "failed" : "current" };
    return { name, state: "waiting" };
  });
}

/** Flye's own per-contig columns from the job's result summary, by contig name. */
export function flyeContigRows(job: AnalysisJobDetail | undefined): Map<string, FlyeContigRow> {
  const rows = (job?.result_summary?.contigs ?? []) as FlyeContigRow[];
  return new Map(rows.map((r) => [r.name, r]));
}
