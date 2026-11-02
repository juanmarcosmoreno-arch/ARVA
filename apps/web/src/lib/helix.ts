/**
 * The double-helix view: B-DNA geometry for a schematic drawing, base facts and the lookups that place a position
 * of a sequence in its context. Kept free of React so it can be tested.
 *
 * The drawing is schematic: every base pair gets the same rise and twist (real DNA varies with the sequence and its
 * surroundings), the backbones are drawn as two sine curves and the bases as straight rungs. The constants and their
 * sources are in the guide entry "double_helix":
 *
 * - helical repeat in solution: 10.4 ± 0.1 bp per turn (Wang 1979, PNAS 76:200) and 10.6 ± 0.1 (Rhodes & Klug 1980,
 *   Nature 286:573); 10.5 in the B-DNA column of the structural table of Rich, Nordheim & Wang (1984, Annu Rev Biochem
 *   53:791). ARVA uses 10.5.
 * - rise: one residue every 3.4 Å along the axis, and the phosphorus atoms 10 Å from the axis (Watson & Crick 1953,
 *   Nature 171:737), so a diameter of about 2 nm.
 * - groove widths: major 22 Å and minor 12 Å (Wing et al. 1980, Nature 287:755, the first crystal structure of a full
 *   turn of B-DNA). Widths depend on how they are measured; ARVA uses them only for the ratio of the drawing.
 */
import type { CoverageTrack, HelixChange, HelixCodon, HelixFeature } from "./types";

export const BP_PER_TURN = 10.5;
export const RISE_NM = 0.34;
export const DIAMETER_NM = 2.0;
export const MAJOR_GROOVE_NM = 2.2;
export const MINOR_GROOVE_NM = 1.2;
/** Twist per base pair: 360° / 10.5 ≈ 34.3°. */
export const TWIST_DEG = 360 / BP_PER_TURN;
/** Height of one turn: 10.5 × 0.34 nm ≈ 3.57 nm. */
export const PITCH_NM = BP_PER_TURN * RISE_NM;
/** How far round the axis the second backbone is drawn from the first: the minor groove takes the share of a turn
 * that the minor groove takes of both groove widths (12 / 34 of 360° ≈ 127°). A drawing convention, not a measurement. */
export const STRAND_OFFSET_DEG = (360 * MINOR_GROOVE_NM) / (MAJOR_GROOVE_NM + MINOR_GROOVE_NM);
/** Bases fetched per request: the view asks for whole blocks so that moving the reading head reuses them. */
export const BLOCK = 500;

export type Base = "A" | "C" | "G" | "T";
export type BaseKind = { kind: "base"; base: Base; purine: boolean; rings: 1 | 2 } | { kind: "gap" } | { kind: "ambiguous"; code: string; means: Base[] } | { kind: "other"; code: string };

const COMPLEMENT: Record<string, string> = { A: "T", C: "G", G: "C", T: "A", N: "N", R: "Y", Y: "R", K: "M", M: "K", S: "S", W: "W", B: "V", V: "B", D: "H", H: "D" };
/** IUPAC nucleotide codes (Cornish-Bowden 1985, the NC-IUB recommendations) other than A, C, G, T and N. */
export const IUPAC: Record<string, Base[]> = {
  R: ["A", "G"], Y: ["C", "T"], K: ["G", "T"], M: ["A", "C"], S: ["C", "G"], W: ["A", "T"],
  B: ["C", "G", "T"], D: ["A", "G", "T"], H: ["A", "C", "T"], V: ["A", "C", "G"],
};

/** What a character of the sequence file is: one of the four bases, N (no base known: an assembly gap or an
 * undetermined base), another IUPAC code (one of several bases) or anything else. Case is ignored (soft-masking). */
export function baseKind(ch: string): BaseKind {
  const b = ch.toUpperCase();
  if (b === "A" || b === "G") return { kind: "base", base: b, purine: true, rings: 2 };
  if (b === "C" || b === "T") return { kind: "base", base: b, purine: false, rings: 1 };
  if (b === "N") return { kind: "gap" };
  if (IUPAC[b]) return { kind: "ambiguous", code: b, means: IUPAC[b] };
  return { kind: "other", code: b };
}

/** The base on the other strand: the complement, by construction of an assembly (one strand is stored). IUPAC codes
 * complement to the code of the complementary set (R↔Y, K↔M, B↔V, D↔H; S, W and N stay). */
export const complement = (ch: string) => COMPLEMENT[ch.toUpperCase()] ?? ch.toUpperCase();

/** Hydrogen bonds of a Watson–Crick pair: A·T 2, G·C 3 (Pauling & Corey 1956); none for a base that is not known. */
export function hydrogenBonds(ch: string): 2 | 3 | null {
  const k = baseKind(ch);
  if (k.kind !== "base") return null;
  return k.base === "G" || k.base === "C" ? 3 : 2;
}

/** The turn (from 1) a base pair falls in, counting 10.5 bp per turn from the first base of the sequence, and its
 * place in that turn (from 1). Turn k holds the pairs whose index (position − 1) lies in [(k−1)·10.5, k·10.5). */
export function turnOf(pos: number): { turn: number; pairInTurn: number } {
  const i = pos - 1;
  const turn = Math.floor(i / BP_PER_TURN) + 1;
  return { turn, pairInTurn: i - Math.ceil((turn - 1) * BP_PER_TURN) + 1 };
}

/** Distance along the axis from the first base pair of the sequence to this one, in nm. */
export const distanceNm = (pos: number) => (pos - 1) * RISE_NM;

/** A position moved onto the sequence: wrapped on a circular sequence, null outside a linear (or unknown) one. */
export function wrapPosition(pos: number, length: number, circular: boolean | null): number | null {
  if (pos >= 1 && pos <= length) return pos;
  if (!circular) return null;
  return ((((pos - 1) % length) + length) % length) + 1;
}

/** The angle (degrees) of each backbone at a (possibly fractional) base-pair index. */
export const strandAngles = (pos: number): [number, number] => {
  const a = (pos - 1) * TWIST_DEG;
  return [a, a + STRAND_OFFSET_DEG];
};

/** Where on the axis (base-pair index) the grooves face the viewer nearest `near`: the minor groove midway between
 * the second backbone's and the first's front crossing, the major groove in the other gap. */
export function grooveCentres(near: number): { minor: number; major: number } {
  const at = (deg: number) => {
    const turnBp = (deg / 360) * BP_PER_TURN;
    const k = Math.round((near - 1 - turnBp) / BP_PER_TURN);
    return 1 + turnBp + k * BP_PER_TURN;
  };
  return { minor: at(-STRAND_OFFSET_DEG / 2), major: at(180 - STRAND_OFFSET_DEG / 2) };
}

/** Where the rung of a pair is split between its two bases: a purine (two rings) is drawn longer than a pyrimidine
 * (one ring), 3:2; two unknown halves split in the middle. Returns the first base's share of the rung. */
export function rungShare(first: string, second: string): number {
  const a = baseKind(first);
  const b = baseKind(second);
  if (a.kind !== "base" || b.kind !== "base") return 0.5;
  return a.rings === b.rings ? 0.5 : a.rings === 2 ? 0.6 : 0.4;
}

/** Block starts (1-based) needed to hold positions lo..hi of a sequence (both already on the sequence). */
export function blocksFor(positions: number[]): number[] {
  return [...new Set(positions.map((p) => Math.floor((p - 1) / BLOCK) * BLOCK + 1))].sort((x, y) => x - y);
}

/** Whether `pos` lies in start..end, where start > end on a circular sequence means across the origin. */
export function inRange(pos: number, start: number, end: number): boolean {
  return start <= end ? pos >= start && pos <= end : pos >= start || pos <= end;
}

export interface CodonHere {
  feature: HelixFeature;
  codon: HelixCodon | null;
  /** 1, 2 or 3: the place of the position in its codon. */
  place: number | null;
}

/** The features that cover `pos`, each with the codon that reads it (when the feature has a reading frame there). */
export function codonsAt(features: HelixFeature[], pos: number): CodonHere[] {
  return features
    .filter((f) => inRange(pos, f.start, f.end))
    .map((f) => {
      const codon = f.reading.codons.find((c) => c.positions.includes(pos)) ?? null;
      return { feature: f, codon, place: codon ? codon.positions.indexOf(pos) + 1 : null };
    });
}

export const changesAt = (changes: HelixChange[], pos: number) => changes.filter((c) => pos >= c.start && pos <= c.end);

/** The mean depth of the depth-profile bin that holds `pos`, with the bin's extent. */
export function depthAt(coverage: CoverageTrack, pos: number): { mean: number | null; start: number; end: number } | null {
  if (!coverage.available) return null;
  const i = coverage.start.findIndex((s, k) => pos >= s && pos <= coverage.end[k]);
  return i < 0 ? null : { mean: coverage.mean[i], start: coverage.start[i], end: coverage.end[i] };
}

/** Parse a position typed by the user (digits, with optional thousands separators). */
export function parsePosition(text: string, length: number): number | null {
  const digits = text.replace(/[\s,._]/g, "");
  if (!/^\d+$/.test(digits)) return null;
  const n = Number(digits);
  return n >= 1 && n <= length ? n : null;
}

/** One-letter amino-acid codes that ARVA names (the 20 standard amino acids and the stop). */
export const AMINO_ACIDS = ["A", "R", "N", "D", "C", "Q", "E", "G", "H", "I", "L", "K", "M", "F", "P", "S", "T", "W", "Y", "V", "*"] as const;
export type AminoAcid = (typeof AMINO_ACIDS)[number];
export const isAminoAcid = (x: string): x is AminoAcid => (AMINO_ACIDS as readonly string[]).includes(x);

export const SPEEDS = [1, 2, 5, 10] as const;
