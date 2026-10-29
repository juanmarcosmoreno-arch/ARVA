import type { TranslationKey } from "@/i18n";
import { fmtMax } from "./format";
import { basename } from "./results";
import type { AnalysisJobDetail, QuastPlan, QuastRequest, QuastSummary, QuastValue, RawFile } from "./types";

export const QUAST_JOB = "quast_evaluation";
/** ARVA's limits (QUAST's --min-contig has none; more than 10 assemblies make the comparison unreadable). */
export const QUAST_LIMITS = { minContig: [0, 1_000_000], maxAssemblies: 10 } as const;
export const QUAST_DEFAULT_MIN_CONTIG = 500;

/** Sample files QUAST can take as the reference genome: valid FASTA (imported or derived). */
export const referenceCandidates = (files: RawFile[]) =>
  files.filter((f) => (f.file_format === "fasta" || f.file_format === "fasta_gz") && f.is_valid);

export interface QuastForm {
  selected: string[];
  referenceId: string;
  minContig: string;
  threads: string;
}

const num = (s: string) => (s.trim() === "" ? null : Number(s));
const isInt = (n: number | null): n is number => n !== null && Number.isInteger(n);

/** Problems that keep the form from being sent (each an i18n key); the server checks everything again. */
export function quastProblems(form: QuastForm, plan: QuastPlan | undefined): TranslationKey[] {
  const out: TranslationKey[] = [];
  if (!form.selected.length) out.push("quast.problem.assemblies");
  if (form.selected.length > QUAST_LIMITS.maxAssemblies) out.push("quast.problem.tooMany");
  const m = num(form.minContig);
  if (!isInt(m) || m < QUAST_LIMITS.minContig[0] || m > QUAST_LIMITS.minContig[1]) out.push("quast.problem.minContig");
  const th = num(form.threads);
  if (th !== null && (!isInt(th) || th < 1 || th > (plan?.tool.max_threads ?? 1))) out.push("quast.problem.threads");
  if (plan?.assemblies.some((a) => a.contigs_kept === 0)) out.push("quast.problem.nothingKept");
  if (form.referenceId && plan?.tool.aligner?.provided_by === "missing") out.push("quast.problem.aligner");
  return out;
}

export function quastRequest(form: QuastForm): QuastRequest {
  return {
    assembly_ids: form.selected,
    reference_file_id: form.referenceId || null,
    min_contig: Number(form.minContig),
    threads: num(form.threads),
  };
}

/** An output's path below the job's folder (e.g. quast/icarus_viewers/contig_size_viewer.html): QUAST's pages link to
 * each other by such relative paths, which keep working when the page is opened at that address. */
export function jobRelativePath(jobId: string, path: string): string {
  const marker = `/${jobId}/`;
  const i = path.indexOf(marker);
  return i >= 0 ? path.slice(i + marker.length) : basename(path);
}

/** The relative path of the job's registered output ending in `name` (e.g. "icarus.html"), or null. */
export function quastOutput(job: Pick<AnalysisJobDetail, "id" | "output_paths">, name: string): string | null {
  const p = (job.output_paths ?? []).find((o) => o.endsWith(`/${name}`));
  return p ? jobRelativePath(job.id, p) : null;
}

export function quastSummary(job: AnalysisJobDetail): QuastSummary | null {
  const s = job.result_summary as QuastSummary | null;
  return s && Array.isArray(s.report?.labels) ? s : null;
}

/** QUAST's own field names shown by default, in QUAST's order; the rest are one click away. */
export const KEY_FIELDS = new Set([
  "# contigs (>= 0 bp)", "Total length (>= 0 bp)", "# contigs", "Largest contig", "Total length", "GC (%)", "N50", "N90", "auN",
  "L50", "L90", "# N's per 100 kbp", "Reference length", "Reference GC (%)", "NG50", "LG50", "Genome fraction (%)",
  "Duplication ratio", "# misassemblies", "# misassembled contigs", "Misassembled contigs length", "# local misassemblies",
  "# unaligned contigs", "Unaligned length", "# mismatches per 100 kbp", "# indels per 100 kbp", "Largest alignment",
  "Total aligned length", "NGA50", "LGA50",
]);

/** Explanations of QUAST fields (i18n keys), from QUAST's manual. */
export const FIELD_HELP: Record<string, TranslationKey> = {
  "# contigs (>= 0 bp)": "quast.field.contigsAll",
  "Total length (>= 0 bp)": "quast.field.totalAll",
  "# contigs": "quast.field.contigs",
  "Largest contig": "quast.field.largest",
  "Total length": "quast.field.total",
  "GC (%)": "quast.field.gc",
  N50: "quast.field.n50",
  N90: "quast.field.n90",
  auN: "quast.field.auN",
  L50: "quast.field.l50",
  "# N's per 100 kbp": "quast.field.ns",
  NG50: "quast.field.ng50",
  "Genome fraction (%)": "quast.field.genomeFraction",
  "Duplication ratio": "quast.field.duplication",
  "# misassemblies": "quast.field.misassemblies",
  "# local misassemblies": "quast.field.localMisassemblies",
  "# unaligned contigs": "quast.field.unaligned",
  "# mismatches per 100 kbp": "quast.field.mismatches",
  "# indels per 100 kbp": "quast.field.indels",
  NGA50: "quast.field.nga50",
};

export function reportRows(summary: QuastSummary, all: boolean) {
  return all ? summary.report.rows : summary.report.rows.filter((r) => KEY_FIELDS.has(r.field));
}

/** A QUAST value as QUAST reported it, numbers in the interface's format ("1 + 0 part" for unaligned contigs, "—" where
 * QUAST wrote "-"). */
export function formatQuastValue(v: QuastValue | undefined, partLabel: string): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return fmtMax(v, 3);
  if (typeof v === "string") return v;
  return `${v.full} + ${v.partial} ${partLabel}`;
}
