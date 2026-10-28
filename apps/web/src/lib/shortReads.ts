import type { TranslationKey } from "@/i18n";
import { fmtNum } from "./format";
import type {
  Assembly,
  AssemblyModeName,
  CoverageKind,
  RawFile,
  ReadRole,
  SequencingTechnology,
  ShortReadPlan,
  SpadesMode,
  SpadesRequest,
  UnicyclerBridging,
  UnicyclerPlan,
  UnicyclerRequest,
} from "./types";

export const SPADES_JOB = "spades_assembly";
export const UNICYCLER_JOB = "unicycler_assembly";

export type Assembler = "flye" | "spades" | "unicycler";
export const ASSEMBLERS: Assembler[] = ["flye", "spades", "unicycler"];

/** File ids by role; "" when the role is not used. */
export type Roles = Record<ReadRole, string>;
export const NO_ROLES: Roles = { r1: "", r2: "", unpaired: "", long: "" };

const isFastq = (f: RawFile) => (f.file_format === "fastq" || f.file_format === "fastq_gz") && f.is_valid;

/** The platform a file's read headers point to, when they do so with high or medium confidence. */
function headerPlatform(f: RawFile) {
  const s = f.header_metadata?.suggested_technology;
  return s && (s.confidence === "high" || s.confidence === "medium") ? s.value : null;
}

/** FASTQ files that can be short reads: their headers do not identify a long-read platform. */
export const shortCandidates = (files: RawFile[]) =>
  files.filter((f) => isFastq(f) && headerPlatform(f) !== "nanopore" && headerPlatform(f) !== "pacbio");

/** FASTQ files that can be long reads: not one mate of a pair, headers not Illumina. */
export const longCandidates = (files: RawFile[]) => files.filter((f) => isFastq(f) && !f.read_mate && headerPlatform(f) !== "illumina");

/** Which reads the sample has, from its technology, the files' mate markers and their read headers (evidence that
 * guides the choice of assembler; the server checks the files again). */
export function availableData(files: RawFile[], technology: SequencingTechnology): { short: boolean; long: boolean } {
  const fq = files.filter(isFastq);
  const pairs = fq.some((f) => f.read_mate === "R1") && fq.some((f) => f.read_mate === "R2");
  const shortHeaders = fq.some((f) => headerPlatform(f) === "illumina");
  const longHeaders = fq.some((f) => !f.read_mate && (headerPlatform(f) === "nanopore" || headerPlatform(f) === "pacbio"));
  const unpairedNonIllumina = fq.some((f) => !f.read_mate && headerPlatform(f) !== "illumina");
  const short = pairs || shortHeaders || (technology === "illumina" && fq.length > 0);
  const long = longHeaders || ((technology === "nanopore" || technology === "pacbio" || technology === "hybrid") && unpairedNonIllumina);
  return { short, long };
}

/** The assemblers that fit the reads: long → Flye; short → SPAdes or Unicycler; both → Unicycler (hybrid). */
export function recommendedAssemblers(data: { short: boolean; long: boolean }): Assembler[] {
  if (data.short && data.long) return ["unicycler"];
  if (data.short) return ["spades", "unicycler"];
  if (data.long) return ["flye"];
  return [];
}

export const defaultAssembler = (data: { short: boolean; long: boolean }): Assembler => recommendedAssemblers(data)[0] ?? "flye";

/** Preselected roles: the first imported R1/R2 pair (matched by name), and with `withLong` an imported long-read file. */
export function defaultRoles(files: RawFile[], withLong: boolean): Roles {
  const imported = (list: RawFile[]) => list.filter((f) => f.origin === "imported");
  const short = imported(shortCandidates(files));
  const r1 = short.find((f) => f.read_mate === "R1");
  const r2 =
    (r1 && short.find((f) => f.read_mate === "R2" && f.original_filename === r1.original_filename.replace(/R1(?!.*R1)/, "R2"))) ??
    short.find((f) => f.read_mate === "R2");
  const longs = imported(longCandidates(files));
  const long = withLong ? (longs.find((f) => headerPlatform(f) === "nanopore" || headerPlatform(f) === "pacbio") ?? longs.find((f) => f.id !== r1?.id && f.id !== r2?.id)) : undefined;
  return { r1: r1 && r2 ? r1.id : "", r2: r1 && r2 ? r2.id : "", unpaired: "", long: long?.id ?? "" };
}

export function inputsOf(roles: Roles) {
  return {
    r1_file_id: roles.r1 || null,
    r2_file_id: roles.r2 || null,
    unpaired_file_id: roles.unpaired || null,
    long_file_id: roles.long || null,
  };
}

export const hasShort = (roles: Roles) => !!(roles.r1 || roles.r2 || roles.unpaired);

/** The Unicycler mode the chosen roles imply. */
export function unicyclerMode(roles: Roles): AssemblyModeName | null {
  const short = hasShort(roles);
  if (short && roles.long) return "hybrid";
  return short ? "short" : roles.long ? "long" : null;
}

/** "21,33,55" → [21, 33, 55]; "" → null (the assembler chooses); "invalid" unless odd, within [min, max], ascending. */
export function parseKmers(text: string, min: number, max: number): number[] | null | "invalid" {
  if (!text.trim()) return null;
  const parts = text.split(/[\s,]+/).filter(Boolean);
  const ks = parts.map(Number);
  const ok = ks.every((k) => Number.isInteger(k) && k % 2 === 1 && k >= min && k <= max) && ks.every((k, i) => i === 0 || k > ks[i - 1]);
  return ok ? ks : "invalid";
}

const num = (s: string) => (s.trim() === "" ? null : Number(s));
const isInt = (n: number | null): n is number => n !== null && Number.isInteger(n);

function commonProblems(roles: Roles, plan: ShortReadPlan | undefined, confirmed: boolean, threads: string, memory: string | null): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (!hasShort(roles) && !roles.long) out.push("shortReads.problem.reads");
  if (!!roles.r1 !== !!roles.r2) out.push("shortReads.problem.pair");
  const th = num(threads);
  if (th !== null && (!isInt(th) || th < 1 || th > (plan?.tool.max_threads ?? 1))) out.push("flye.problem.threads");
  const mem = memory === null ? null : num(memory);
  if (mem !== null && (!isInt(mem) || mem < 1 || mem > (plan?.tool.max_memory_gb ?? 1))) out.push("shortReads.problem.memory");
  if (plan?.problem) out.push("shortReads.problem.server");
  if (plan?.confirmation_required && !confirmed) out.push("shortReads.problem.confirm");
  return out;
}

export interface SpadesForm {
  mode: SpadesMode;
  output: "contigs" | "scaffolds";
  k: string;
  covCutoff: "off" | "auto" | "value";
  covValue: string;
  memory: string;
  threads: string;
}

export const SPADES_FORM_DEFAULTS: SpadesForm = { mode: "isolate", output: "contigs", k: "", covCutoff: "off", covValue: "", memory: "", threads: "" };
/** SPAdes' -k range (spades.py --help: odd and less than 128). */
export const SPADES_K = [1, 127] as const;

export function spadesProblems(form: SpadesForm, roles: Roles, plan: ShortReadPlan | undefined, confirmed: boolean): TranslationKey[] {
  const out = commonProblems({ ...roles, long: "" }, plan, confirmed, form.threads, form.memory);
  if (parseKmers(form.k, ...SPADES_K) === "invalid") out.push("spades.problem.k");
  const cov = num(form.covValue);
  if (form.covCutoff === "value" && (cov === null || !(cov > 0))) out.push("spades.problem.cov");
  return out;
}

export function spadesRequest(form: SpadesForm, roles: Roles, confirmed: boolean): SpadesRequest {
  const k = parseKmers(form.k, ...SPADES_K);
  const { long_file_id: _, ...inputs } = inputsOf(roles);
  return {
    inputs,
    params: {
      mode: form.mode,
      k: k === "invalid" ? null : k,
      cov_cutoff: form.covCutoff === "value" ? Number(form.covValue) : form.covCutoff,
      memory_gb: num(form.memory),
      threads: num(form.threads),
      output: form.output,
    },
    reads_confirmed: confirmed,
  };
}

export interface UnicyclerForm {
  mode: UnicyclerBridging;
  keep: "0" | "1";
  kmers: string;
  depthFilter: string;
  minFastaLength: string;
  linearSeqs: string;
  memory: string;
  threads: string;
}

export const UNICYCLER_FORM_DEFAULTS: UnicyclerForm = {
  mode: "normal",
  keep: "1",
  kmers: "",
  depthFilter: "0.25",
  minFastaLength: "100",
  linearSeqs: "0",
  memory: "",
  threads: "",
};
/** Unicycler's --kmers range (unicycler.py: odd, 11 to 127). */
export const UNICYCLER_K = [11, 127] as const;

export function unicyclerProblems(form: UnicyclerForm, roles: Roles, plan: UnicyclerPlan | undefined, confirmed: boolean): TranslationKey[] {
  const short = hasShort(roles);
  const out = commonProblems(roles, plan, confirmed, form.threads, short ? form.memory : null);
  const mode = unicyclerMode(roles);
  if (mode && plan && plan.tool.status === "available" && !plan.tool.modes.includes(mode)) out.push("unicycler.problem.helpers");
  if (short && parseKmers(form.kmers, ...UNICYCLER_K) === "invalid") out.push("unicycler.problem.kmers");
  const depth = num(form.depthFilter);
  if (short && (depth === null || !(depth >= 0 && depth <= 1))) out.push("unicycler.problem.depthFilter");
  const minLen = num(form.minFastaLength);
  if (!isInt(minLen) || minLen < 1) out.push("unicycler.problem.minFastaLength");
  const linear = num(form.linearSeqs);
  if (!isInt(linear) || linear < 0) out.push("unicycler.problem.linearSeqs");
  return out;
}

export function unicyclerRequest(form: UnicyclerForm, roles: Roles, confirmed: boolean): UnicyclerRequest {
  const short = hasShort(roles);
  const kmers = short ? parseKmers(form.kmers, ...UNICYCLER_K) : null;
  return {
    inputs: inputsOf(roles),
    params: {
      mode: form.mode,
      keep: form.keep === "0" ? 0 : 1,
      kmers: kmers === "invalid" ? null : kmers,
      depth_filter: Number(form.depthFilter),
      min_fasta_length: Number(form.minFastaLength),
      linear_seqs: Number(form.linearSeqs),
      threads: num(form.threads),
      spades_memory_gb: short ? num(form.memory) : null,
    },
    reads_confirmed: confirmed,
  };
}

// --- Coverage, which each assembler defines differently ------------------------------------------------------

const KIND_BY_ASSEMBLER: Record<string, CoverageKind> = { Flye: "read_depth", SPAdes: "kmer_coverage", Unicycler: "relative_depth" };

export const coverageKind = (a: Pick<Assembly, "assembler" | "coverage_kind">): CoverageKind | null => a.coverage_kind ?? KIND_BY_ASSEMBLER[a.assembler] ?? null;

export const COVERAGE_LABEL: Record<CoverageKind, TranslationKey> = {
  read_depth: "coverage.kind.read_depth",
  kmer_coverage: "coverage.kind.kmer_coverage",
  relative_depth: "coverage.kind.relative_depth",
  mapped_read_depth: "coverage.kind.mapped_read_depth",
};

/** A coverage value in its assembler's own terms: read depth "31×", k-mer coverage "13.4", relative depth "2.04×". */
export function fmtCoverage(value: number | null, kind: CoverageKind | null): string {
  if (value === null) return "—";
  if (kind === "kmer_coverage") return fmtNum(value, 1);
  if (kind === "relative_depth") return `${fmtNum(value, 2)}×`;
  return `${fmtNum(value, 0)}×`;
}
