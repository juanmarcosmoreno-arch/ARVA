import { dictionaries, LOCALE, translator, type TranslationKey } from "@/i18n";
import { useSettings } from "@/store/settings";

/** The interface language at call time; components re-render on a change because they read it through useT. */
const lang = () => useSettings.getState().language;
export const locale = () => LOCALE[lang()];

const formats = new Map<string, Intl.NumberFormat>();
function numberFormat(options: Intl.NumberFormatOptions = {}) {
  const key = `${locale()}|${JSON.stringify(options)}`;
  let f = formats.get(key);
  if (!f) formats.set(key, (f = new Intl.NumberFormat(locale(), options)));
  return f;
}

export const fmtInt = (n: number) => numberFormat().format(Math.round(n));

export function fmtNum(n: number, digits = 1) {
  return numberFormat({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** A percentage (0–100) as the locale writes it: 45.2% in English, 45,2 % in Spanish. */
export function fmtPct(percent: number, digits = 1) {
  return numberFormat({ style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(percent / 100);
}

/** A number as the locale writes it, with up to `digits` decimals (none added). */
export function fmtMax(n: number, digits = 3) {
  return numberFormat({ maximumFractionDigits: digits }).format(n);
}

export function fmtBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${fmtNum(v, v < 10 ? 2 : 1)} ${units[i]}`;
}

const BP_UNITS: Record<"en" | "es", [string, string, string, string]> = { en: ["bp", "kbp", "Mbp", "Gbp"], es: ["pb", "kpb", "Mpb", "Gpb"] };

/** The base-pair unit symbol of the interface language: bp, kbp, Mbp, Gbp (Spanish pb, kpb, Mpb, Gpb). */
export const bpUnit = (scale: 0 | 1 | 2 | 3 = 0) => BP_UNITS[lang()][scale];

/** Compact base-pair counts: 1.2 Gbp, 34.3 Mbp, 950 bp. */
export function fmtBases(bp: number) {
  if (bp >= 1e9) return `${fmtNum(bp / 1e9, 2)} ${bpUnit(3)}`;
  if (bp >= 1e6) return `${fmtNum(bp / 1e6, 2)} ${bpUnit(2)}`;
  if (bp >= 1e3) return `${fmtNum(bp / 1e3, 1)} ${bpUnit(1)}`;
  return `${fmtInt(bp)} ${bpUnit()}`;
}

/** An exact base-pair count: 2,814,816 bp. */
export const fmtBp = (bp: number) => `${fmtInt(bp)} ${bpUnit()}`;

export function fmtCompact(n: number) {
  return numberFormat({ notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" });
}

export function fmtDuration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${fmtNum(seconds, 1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds % 60)} s`;
}

const FORMAT_LABEL: Record<string, string> = {
  fastq: "FASTQ",
  fastq_gz: "FASTQ.gz",
  fasta: "FASTA",
  fasta_gz: "FASTA.gz",
  pod5: "POD5",
};

export const formatLabel = (format: string) => FORMAT_LABEL[format] ?? translator(lang())("format.unknown");

export const TECHNOLOGIES = ["illumina", "nanopore", "pacbio", "hybrid", "unknown"] as const;

export function technologyLabel(technology: string) {
  const key = `technology.${technology}`;
  return key in dictionaries.en ? translator(lang())(key as TranslationKey) : technology;
}

/** An argument vector as a POSIX shell line, quoting only what needs it (for display and copy). */
export function shellJoin(argv: string[]) {
  return argv.map((a) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replace(/'/g, `'"'"'`)}'`)).join(" ");
}

const HTML_ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** For user-supplied text inside HTML strings such as chart tooltips (React escapes everything else). */
export function escapeHtml(text: string) {
  return text.replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}
