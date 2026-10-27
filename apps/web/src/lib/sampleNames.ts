/** Propose sample IDs from sequencing file names (bulk import). Pure functions, no I/O. */

export type Mate = "R1" | "R2" | null;

export interface GroupedFile {
  name: string;
  mate: Mate;
}

export interface SampleGroup {
  sampleName: string;
  files: GroupedFile[];
  warnings: string[];
}

const MAX_SAMPLE_ID = 255;
const EXTENSION = /\.(?:(?:fastq|fq|fasta|fa|fna|fas)(?:\.gz)?|pod5)$/i;
const SEQUENCE_FILE = /\.(?:fastq|fq|fasta|fa|fna|fas)(?:\.gz)?$/i;
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

export const isSequenceFile = (name: string) => SEQUENCE_FILE.test(basename(name));

/** `x_1`/`x_2` are mates only if they are not part of a numbered series such as ONT chunks `x_0`, `x_3`… */
function isNumberedSeries(prefix: string, stems: Set<string>) {
  for (const s of stems) {
    const rest = s.slice(prefix.length);
    if (s.startsWith(prefix) && /^\d+$/.test(rest) && rest !== "1" && rest !== "2") return true;
  }
  return false;
}

function parse(filename: string, stems: Set<string>): Parsed {
  const base = stem(filename);
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
    if (rest && stems.has(partner) && !isNumberedSeries(prefix + sep, stems)) {
      return { sampleName: rest.slice(0, MAX_SAMPLE_ID), mate: `R${num}` as Mate, pairKey: `${prefix}${sep}#` };
    }
  }
  return { sampleName: base.slice(0, MAX_SAMPLE_ID), mate: null, pairKey: null };
}

const stemSet = (names: string[]) => new Set(names.map(stem));

export function inferSampleName(filename: string, allFilenames: string[]): string {
  return parse(filename, stemSet([...allFilenames, filename])).sampleName;
}

function warningsFor(files: (GroupedFile & { pairKey: string | null })[]): string[] {
  const mates = new Map<string, Set<Mate>>();
  for (const f of files) if (f.pairKey) mates.set(f.pairKey, (mates.get(f.pairKey) ?? new Set()).add(f.mate));
  const unpaired = (mate: Mate, other: Mate) =>
    files.filter((f) => f.mate === mate && f.pairKey && !mates.get(f.pairKey)?.has(other)).map((f) => f.name);
  const out: string[] = [];
  const r1Alone = unpaired("R1", "R2");
  const r2Alone = unpaired("R2", "R1");
  if (r1Alone.length) out.push(`R1 without its R2 file: ${r1Alone.join(", ")}`);
  if (r2Alone.length) out.push(`R2 without its R1 file: ${r2Alone.join(", ")}`);
  for (const mate of ["R1", "R2"] as const) {
    const count = files.filter((f) => f.mate === mate).length;
    if (count > 2) out.push(`${count} ${mate} files in one sample: check that they belong together (e.g. several lanes or runs)`);
  }
  return out;
}

const MATE_ORDER: Record<string, number> = { R1: 0, R2: 1, none: 2 };

export function groupFilesBySample(names: string[]): SampleGroup[] {
  const stems = stemSet(names);
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
