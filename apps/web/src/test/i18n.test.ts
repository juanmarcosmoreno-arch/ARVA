import path from "node:path";
import { describe, expect, it } from "vitest";
import { dictionaries, interpolate } from "@/i18n";
import { hasUntranslatedWord, scanSource, scanTree, TECHNICAL_WORDS, type Finding } from "./hardcodedText";
import { keyUsage } from "./i18nUsage";

const SRC = path.resolve(__dirname, "..");
const en = dictionaries.en as Record<string, string>;
const es = dictionaries.es as Record<string, string>;

/** Literals that stay as they are, reviewed one by one. */
const ALLOWED: { file: string; text: string; why: string }[] = [
  { file: "components/assembly/ShortReadPanels.tsx", text: "off (", why: "SPAdes --cov-cutoff value" },
  { file: "components/assembly/ShortReadPanels.tsx", text: "auto", why: "SPAdes --cov-cutoff value" },
  { file: "components/assembly/ShortReadPanels.tsx", text: "label: conservative", why: "Unicycler --mode value" },
  { file: "components/assembly/ShortReadPanels.tsx", text: "label: normal", why: "Unicycler --mode value" },
  { file: "components/assembly/ShortReadPanels.tsx", text: "label: bold", why: "Unicycler --mode value" },
  { file: "components/annotation/FeatureDetail.tsx", text: "unit=bp", why: "selects the unit; shown through fmtBp" },
  ...["# contigs (>= 0 bp)", "Total length (>= 0 bp)", "# N's per 100 kbp", "# mismatches per 100 kbp", "# indels per 100 kbp"].map(
    (text) => ({ file: "lib/quast.ts", text, why: "QUAST's own report field names, shown as QUAST writes them" }),
  ),
];

/** Words written the same in Spanish (or names) that may make a Spanish text identical to the English one. */
const SAME_IN_SPANISH = new Set([
  "Software", "bytes", "Megabases", "Contigs", "Bases", "bases", "Base", "Total", "Genes", "genes", "Contig", "Circular", "circular",
  "no", "original", "error", "Pseudogenes", "Chip", "Desktop", "Locus", "tag", "tags", "pass", "warn", "fail",
  "Illumina", "CASAVA", "bcl2fastq", "BCL", "Convert", "Element", "Biosciences", "bases2fastq", "pod5", "lib_pod5",
  "Oxford", "Excel", "xlsx", "openpyxl", "CLR", "SNP", "oriC", "oriV", "oriT", "Mycoplasma", "Spiroplasma", "Debian",
  "Ubuntu", "Compatible", "Incompatible",
]);

const describeFinding = (f: Finding) => `${f.file}:${f.line} [${f.kind}] ${f.text}`;
/** The placeholder and plural variable names of a text; inside `{n, plural, one {…} other {…}}` only the branch
 * bodies are read, so "one {record}" is not taken for a placeholder. */
function placeholders(text: string): string[] {
  const names = new Set<string>();
  const read = (s: string) => {
    for (let i = 0; i < s.length; i++) {
      if (s[i] !== "{") continue;
      const m = /^\{(\w+)(\}|, plural,)/.exec(s.slice(i));
      if (!m) continue;
      names.add(m[1]);
      if (m[2] === "}") continue;
      let depth = 0;
      let j = i;
      for (; j < s.length; j++) if (s[j] === "{") depth++; else if (s[j] === "}" && --depth === 0) break;
      for (const b of s.slice(i + m[0].length, j).matchAll(/(?:zero|one|two|few|many|other|=\d+)\s*\{/g)) {
        let d = 0;
        let k = b.index! + b[0].length - 1;
        const body = s.slice(i + m[0].length);
        const start = k + 1;
        for (; k < body.length; k++) if (body[k] === "{") d++; else if (body[k] === "}" && --d === 0) break;
        read(body.slice(start, k));
      }
      i = j;
    }
  };
  read(text);
  return [...names].sort();
}

describe("interface text", () => {
  const findings = scanTree(SRC);
  const allowed = (f: Finding) => ALLOWED.some((a) => a.file === f.file && a.text === f.text);

  it("is written through t() everywhere in the sources", () => {
    expect(findings.filter((f) => !allowed(f)).map(describeFinding)).toEqual([]);
  });

  it("needs every allowlist entry it keeps", () => {
    expect(ALLOWED.filter((a) => !findings.some((f) => f.file === a.file && f.text === a.text))).toEqual([]);
  });

  it("is found by the scanner in each place it looks (constructed snippet)", () => {
    const snippet = `
      const OPTIONS = [{ label: "Organism" }, { label: "metadata.field.host" }];
      const chart = { title: { text: "Reads per sample" }, series: [{ name: "Mean quality", type: "line" }] };
      export function X({ n }: { n: number }) {
        return (
          <div className="flex gap-2" title="Read length" aria-labelledby="x-id">
            Uploading files
            <input placeholder={n ? "Search samples" : t("common.search")} />
            {n > 1 && "Several samples"}
            <span>{fmtInt(n)} bp</span>
            <span>{\`\${fmtInt(n)} bp\`}</span>
            <code>--nano-hq ARVA_TOOL_THREADS=4 assembly.fasta</code>
            {t("nav.samples")}
          </div>
        );
      }`;
    const kinds = scanSource("constructed.tsx", snippet).map((f) => `${f.kind}: ${f.text}`);
    expect(kinds).toEqual([
      "property: label: Organism",
      "property: text: Reads per sample",
      "property: name: Mean quality",
      "attribute: title=Read length",
      "jsx-text: Uploading files",
      "attribute: placeholder=Search samples",
      "jsx-expression: Several samples",
      "jsx-text: bp",
      "jsx-expression: bp",
      "unit: ${} bp",
    ]);
  });

  it("treats tool names, units and code as technical, and English words as untranslated", () => {
    expect(hasUntranslatedWord("N50 · GC · FASTQ.gz · Flye --nano-hq · ARVA_TOOL_THREADS")).toBe(false);
    expect(hasUntranslatedWord("Reads")).toBe(true);
    expect(hasUntranslatedWord("12 kbp")).toBe(false);
    expect(hasUntranslatedWord("12 bp")).toBe(true);
  });
});

describe("dictionaries", () => {
  it("have the same keys in English and Spanish, none empty", () => {
    expect(Object.keys(es).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(en).filter((k) => !en[k].trim() || !es[k].trim())).toEqual([]);
  });

  it("use the same placeholders and plural variables in both languages", () => {
    const differing = Object.keys(en).filter((k) => placeholders(en[k]).join() !== placeholders(es[k]).join());
    expect(differing.map((k) => `${k}: ${placeholders(en[k])} / ${placeholders(es[k])}`)).toEqual([]);
  });

  it("give every plural an `other` branch and leave nothing unexpanded for 0, 1, 2 and 1000", () => {
    for (const [lang, dict] of [["en", en], ["es", es]] as const) {
      for (const [key, text] of Object.entries(dict)) {
        if (!text.includes(", plural,")) continue;
        for (const block of text.matchAll(/\{(\w+), plural,/g)) expect(text.slice(block.index), `${lang} ${key}`).toMatch(/^\{\w+, plural,[^]*other \{/);
        for (const n of [0, 1, 2, 1000]) {
          const vars = Object.fromEntries(placeholders(text).map((p) => [p, n]));
          const out = interpolate(text, vars, lang);
          expect(out, `${lang} ${key} n=${n}`).not.toMatch(/\{\w+[,}]|#/);
        }
      }
    }
  });

  it("choose the Spanish plural by count", () => {
    const text = es["import.uploading"];
    expect(interpolate(text, { count: 1, size: "1 MB" }, "es")).toBe("Subiendo 1 archivo (1 MB)");
    expect(interpolate(text, { count: 1000, size: "1 GB" }, "es")).toBe("Subiendo 1000 archivos (1 GB)");
    expect(interpolate(text, { count: 12000, size: "1 GB" }, "es")).toBe("Subiendo 12.000 archivos (1 GB)");
  });

  it("have no key that the sources cannot reach", () => {
    const used = keyUsage(SRC);
    expect(Object.keys(en).filter((k) => !used(k))).toEqual([]);
  });

  it("translate every Spanish text that has a word a Spanish reader would not use", () => {
    const words = (s: string) => s.replace(/\{[^{}]*\}/g, " ").match(/[\p{L}][\p{L}\p{N}_]*/gu) ?? [];
    const same = Object.keys(en).filter((k) => es[k] === en[k] && hasUntranslatedWord(en[k].replace(/\{[^{}]*\}/g, " ")));
    const untranslated = same.filter((k) => words(en[k]).some((w) => w.length > 1 && !TECHNICAL_WORDS.has(w) && !SAME_IN_SPANISH.has(w)));
    expect(untranslated.map((k) => `${k}: ${en[k]}`)).toEqual([]);
  });
});
