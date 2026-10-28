const nf = new Intl.NumberFormat("en-US");

export const fmtInt = (n: number) => nf.format(Math.round(n));

export function fmtNum(n: number, digits = 1) {
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
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
  return `${v.toFixed(v < 10 ? 2 : 1)} ${units[i]}`;
}

/** Compact base-pair counts: 1.2 Gbp, 34.3 Mbp, 950 bp. */
export function fmtBases(bp: number) {
  if (bp >= 1e9) return `${(bp / 1e9).toFixed(2)} Gbp`;
  if (bp >= 1e6) return `${(bp / 1e6).toFixed(2)} Mbp`;
  if (bp >= 1e3) return `${(bp / 1e3).toFixed(1)} kbp`;
  return `${bp} bp`;
}

export function fmtCompact(n: number) {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function fmtDuration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds % 60)} s`;
}

export const formatLabel: Record<string, string> = {
  fastq: "FASTQ",
  fastq_gz: "FASTQ.gz",
  fasta: "FASTA",
  fasta_gz: "FASTA.gz",
  pod5: "POD5",
  unknown: "Unrecognised",
};

export const technologyLabel: Record<string, string> = {
  illumina: "Illumina",
  nanopore: "Oxford Nanopore",
  pacbio: "PacBio",
  hybrid: "Hybrid",
  unknown: "Not specified",
};
