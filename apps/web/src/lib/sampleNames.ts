/** Propose sample IDs from sequencing file names (bulk import). Pure functions, no I/O. */

export type Mate = "R1" | "R2" | null;

export interface GroupedFile {
  name: string;
  mate: Mate;
}

export type PairingWarning =
  | { kind: "unpaired"; mate: "R1" | "R2"; files: string[] }
  | { kind: "tooMany"; mate: "R1" | "R2"; count: number };

export interface SampleGroup {
  sampleName: string;
  files: GroupedFile[];
  warnings: PairingWarning[];
}

const MAX_SAMPLE_ID = 255;
const EXTENSION = /\.(?:(?:fastq|fq|fasta|fa|fna|fas)(?:\.gz)?|pod5)$/i;
const SEQUENCE_FILE = /\.(?:fastq|fq|fasta|fa|fna|fas)(?:\.gz)?$/i;
const POD5_FILE = /\.pod5$/i;
// Only reads come in R1/R2 pairs; strain_1.fna and strain_2.fna are two assemblies.
const FASTQ_FILE = /\.(?:fastq|fq)(?:\.gz)?$/i;
// Most specific first: bcl2fastq / BCL Convert names, then shorter variants.
const MATE_SUFFIXES = [
  /_S\d+_L\d{3}_R([12])_\d{3}$/i,
  /_S\d+_R([12])_\d{3}$/i,
  /_L\d{3}_R([12])_\d{3}$/i,
  /_R([12])_\d{3}$/i,
  /[._-]R([12])$/i,
];
const BARE_MATE = /^(.+)([._-])([12])$/;
const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

interface Parsed {
  sampleName: string;
  mate: Mate;
  /** Same for the R1 and R2 file of one pair. */
  pairKey: string | null;
}

const basename = (name: string) => name.split(/[\\/]/).pop() ?? name;
const trimSeparators = (s: string) => s.replace(/[._-]+$/, "");
const stem = (name: string) => basename(name).replace(EXTENSION, "") || basename(name);
const isFastq = (name: string) => FASTQ_FILE.test(basename(name));

export const isSequenceFile = (name: string) => SEQUENCE_FILE.test(basename(name));
/** What bulk import accepts: reads plus POD5 raw signal (the server recognises POD5 by content). */
export const isImportableFile = (name: string) => isSequenceFile(name) || POD5_FILE.test(basename(name));

/** `x_1`/`x_2` are mates only if they are not part of a numbered series such as ONT chunks `x_0`, `x_3`… */
function isNumberedSeries(prefix: string, stems: Set<string>) {
  for (const s of stems) {
    const rest = s.slice(prefix.length);
    if (s.startsWith(prefix) && /^\d+$/.test(rest) && rest !== "1" && rest !== "2") return true;
  }
  return false;
}

/** `fastqStems`: stems of the FASTQ files in the selection (mate partners must be FASTQ too). */
function parse(filename: string, fastqStems: Set<string>): Parsed {
  const base = stem(filename);
  const whole = { sampleName: base.slice(0, MAX_SAMPLE_ID), mate: null, pairKey: null };
  if (!isFastq(filename)) return whole;
  for (const rx of MATE_SUFFIXES) {
    const m = rx.exec(base);
    if (!m) continue;
    const rest = trimSeparators(base.slice(0, m.index));
    if (!rest) continue;
    const pairKey = base.slice(0, m.index) + m[0].replace(/R[12]/i, "R#");
    return { sampleName: rest.slice(0, MAX_SAMPLE_ID), mate: `R${m[1]}` as Mate, pairKey };
  }
  const bare = BARE_MATE.exec(base);
  if (bare) {
    const [, prefix, sep, num] = bare;
    const rest = trimSeparators(prefix);
    const partner = `${prefix}${sep}${num === "1" ? "2" : "1"}`;
    if (rest && fastqStems.has(partner) && !isNumberedSeries(prefix + sep, fastqStems)) {
      return { sampleName: rest.slice(0, MAX_SAMPLE_ID), mate: `R${num}` as Mate, pairKey: `${prefix}${sep}#` };
    }
  }
  return whole;
}

const fastqStemSet = (names: string[]) => new Set(names.filter(isFastq).map(stem));

export function inferSampleName(filename: string, allFilenames: string[]): string {
  return parse(filename, fastqStemSet([...allFilenames, filename])).sampleName;
}

function warningsFor(files: (GroupedFile & { pairKey: string | null })[]): PairingWarning[] {
  const mates = new Map<string, Set<Mate>>();
  for (const f of files) if (f.pairKey) mates.set(f.pairKey, (mates.get(f.pairKey) ?? new Set()).add(f.mate));
  const out: PairingWarning[] = [];
  for (const [mate, other] of [["R1", "R2"], ["R2", "R1"]] as const) {
    const alone = files.filter((f) => f.mate === mate && f.pairKey && !mates.get(f.pairKey)?.has(other)).map((f) => f.name);
    if (alone.length) out.push({ kind: "unpaired", mate, files: alone });
  }
  for (const mate of ["R1", "R2"] as const) {
    const count = files.filter((f) => f.mate === mate).length;
    if (count > 2) out.push({ kind: "tooMany", mate, count });
  }
  return out;
}

const MATE_ORDER: Record<string, number> = { R1: 0, R2: 1, none: 2 };

export function groupFilesBySample(names: string[]): SampleGroup[] {
  const stems = fastqStemSet(names);
  const groups = new Map<string, (GroupedFile & { pairKey: string | null })[]>();
  for (const name of names) {
    const { sampleName, mate, pairKey } = parse(name, stems);
    const list = groups.get(sampleName) ?? [];
    list.push({ name, mate, pairKey });
    groups.set(sampleName, list);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => collator.compare(a, b))
    .map(([sampleName, files]) => ({
      sampleName,
      files: [...files]
        .sort((a, b) => MATE_ORDER[a.mate ?? "none"] - MATE_ORDER[b.mate ?? "none"] || collator.compare(a.name, b.name))
        .map(({ name, mate }) => ({ name, mate })),
      warnings: warningsFor(files),
    }));
}

export interface SampleMatch<T> {
  sample: T | null;
  /** Several samples differ from the code only by case and none matches exactly: the user must choose. */
  ambiguous: T[];
}

/** Sample codes are unique per project but case-sensitive: an exact match wins, case-insensitive only if unique. */
export function matchExistingSample<T extends { sample_code: string }>(code: string, samples: T[]): SampleMatch<T> {
  const wanted = code.trim();
  if (!wanted) return { sample: null, ambiguous: [] };
  const exact = samples.find((s) => s.sample_code === wanted);
  if (exact) return { sample: exact, ambiguous: [] };
  const folded = samples.filter((s) => s.sample_code.trim().toLowerCase() === wanted.toLowerCase());
  return folded.length === 1 ? { sample: folded[0], ambiguous: [] } : { sample: null, ambiguous: folded };
}
