import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { dictionaries } from "@/i18n";

/** Interface text written as a literal in the source rather than through t(). */
export interface Finding {
  file: string;
  line: number;
  kind: "jsx-text" | "attribute" | "jsx-expression" | "property" | "unit";
  text: string;
}

// Attributes whose text the user reads (or hears, for aria-*), whatever it looks like.
const VISIBLE_ATTRIBUTES = new Set([
  "title", "aria-label", "aria-description", "aria-valuetext", "aria-roledescription", "placeholder", "alt",
  "label", "hint", "description", "caption", "subtitle", "heading", "emptyText", "empty", "tooltip", "unit",
  "legend", "text", "confirmLabel", "message", "note", "help",
]);

// Attributes that are never interface text (identifiers, styling, file names, commands to copy).
const TECHNICAL_ATTRIBUTES = new Set([
  "className", "style", "id", "key", "type", "role", "href", "to", "src", "rel", "target", "name", "value",
  "defaultValue", "htmlFor", "method", "accept", "autoComplete", "inputMode", "pattern", "variant", "size", "tone",
  "d", "fill", "stroke", "viewBox", "transform", "textAnchor", "dominantBaseline", "strokeLinecap", "strokeLinejoin",
  "fontFamily", "fontWeight", "xmlns", "download", "lang", "dir", "spellCheck", "wrap", "preserveAspectRatio",
  "clipPath", "mask", "filter", "markerEnd", "markerStart", "strokeDasharray", "metric", "icon", "kind", "mode",
  "status", "sandbox", "referrerPolicy", "loading", "encType", "form", "list", "step", "min", "max", "explain",
  "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "filePrefix", "fileStem", "poster",
  "installHint", "command",
]);

// Object properties that hold interface text: labels, titles, column headers, ECharts titles and series names.
const TEXT_PROPERTIES = new Set([
  "label", "title", "header", "heading", "placeholder", "description", "hint", "caption", "tooltip", "emptyText",
  "subtitle", "message", "sub", "detail",
]);
// Also often internal names (series ids, CSS), so only flagged when they read like a phrase.
const PHRASE_PROPERTIES = new Set(["name", "text", "subtext", "formatter"]);

/** Words that stay as they are in Spanish: tool, format and database names, metric symbols, unit symbols the
 * glossary keeps. Reviewed: add a word only when it is a proper name or a technical token, never an English word. */
export const TECHNICAL_WORDS = new Set([
  "ARVA", "N50", "N90", "L50", "L90", "NG50", "LG50", "NGA50", "auN", "GC", "AT", "Q20", "Q30", "Phred", "FASTQ",
  "FASTA", "POD5", "GFA", "BAM", "CRAM", "SAM", "GFF3", "GTF", "GBFF", "GenBank", "EMBL", "VCF", "BED", "Newick",
  "TSV", "CSV", "JSON", "HTML", "SVG", "PNG", "PDF", "XLSX", "gz", "Flye", "SPAdes", "Unicycler", "QUAST", "Racon",
  "Pilon", "Bakta", "Prokka", "fastp", "Filtlong", "FastQC", "MultiQC", "NanoPlot", "SeqKit", "samtools", "minimap2",
  "BWA", "dnadiff", "MUMmer", "Dorado", "Docker", "macOS", "Linux", "Mac", "Illumina", "Nanopore", "PacBio", "ONT",
  "HiFi", "CDS", "sORF", "tRNA", "rRNA", "tmRNA", "ncRNA", "CRISPR", "ORF", "COG", "UniProt", "NCBI", "RefSeq", "KEGG",
  "Pfam", "Zenodo", "MD5", "SHA", "sha256", "SHA256", "ID", "IDs", "UTF", "CPU", "GB", "MB", "KB", "TB", "aa", "kbp",
  "Mbp", "Gbp", "pb", "kpb", "Mpb", "Gpb", "contig", "contigs", "English", "Español", "DEMO", "TXT", "EC", "GO", "doi",
  "VFDB", "mlst", "MLST", "PubMLST", "ST", "BLAST", "FastANI", "skani", "Mash", "sylph", "GTDB", "Tk", "ANI",
]);

const LETTER = /\p{L}/u;
const PHRASE = /\p{L}{2,}\s+\p{L}{2,}/u;
const ENTITIES: Record<string, string> = { "&gt;": ">", "&lt;": "<", "&amp;": "&", "&nbsp;": " ", "&quot;": '"', "&apos;": "'" };
const I18N_KEY = /^[a-z][\w]*(\.[\w-]+)+$/;
// A base-pair unit after a number or a ${…} value: Spanish writes pb, so it must come from fmtBp/fmtBases/bpUnit.
const BP_AFTER_VALUE = /(\d|\$\{\})\s*[kMG]?bp\b/;

/** Tokens a reader sees as code rather than words: --flags, ENV_VARS, paths, file and module names, key=value. */
const isCodeToken = (token: string) =>
  /^-/.test(token) || /^[A-Z0-9_<>]*_[A-Z0-9_<>=]*$/.test(token) || token.includes("/") || token.includes("=") ||
  /^_/.test(token) || /^[\w-]+\.[\w.-]*\w$/.test(token);

/** True when the text has a word a Spanish reader would see as untranslated. */
export function hasUntranslatedWord(text: string) {
  const tokens = text.replace(/&\w+;|&#\d+;/g, (e) => ENTITIES[e] ?? " ").split(/\s+/).filter((x) => x && !isCodeToken(x));
  const words = tokens.join(" ").match(/[\p{L}\p{N}][\p{L}\p{N}_']*/gu) ?? [];
  return words.some((w) => LETTER.test(w) && w.length > 1 && !TECHNICAL_WORDS.has(w) && !/^\p{N}/u.test(w));
}

/** The literal parts of an expression that would be rendered as text: string and template literals, also inside
 * conditionals and `a && "b"`, but not arguments of calls (t("key"), fmtBp(n)) or comparisons. */
function literalTexts(node: ts.Expression): string[] {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return [node.text];
  if (ts.isTemplateExpression(node)) return [[node.head.text, ...node.templateSpans.map((s) => s.literal.text)].join(" ")];
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)) return literalTexts(node.expression);
  if (ts.isConditionalExpression(node)) return [...literalTexts(node.whenTrue), ...literalTexts(node.whenFalse)];
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind;
    if (op === ts.SyntaxKind.AmpersandAmpersandToken) return literalTexts(node.right);
    if (op === ts.SyntaxKind.BarBarToken || op === ts.SyntaxKind.QuestionQuestionToken || op === ts.SyntaxKind.PlusToken)
      return [...literalTexts(node.left), ...literalTexts(node.right)];
  }
  return [];
}

const isKey = (text: string) => I18N_KEY.test(text) || text in dictionaries.en;

function attributeName(attr: ts.JsxAttribute) {
  return ts.isIdentifier(attr.name) ? attr.name.text : `${attr.name.namespace.text}:${attr.name.name.text}`;
}

export function scanSource(file: string, source: string): Finding[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: Finding[] = [];
  const add = (node: ts.Node, kind: Finding["kind"], text: string) =>
    out.push({ file, line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1, kind, text: text.trim() });

  const visit = (node: ts.Node) => {
    const literal = ts.isTemplateExpression(node)
      ? [node.head.text, ...node.templateSpans.map((s) => s.literal.text)].join("${}")
      : ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : null;
    if (literal !== null && BP_AFTER_VALUE.test(literal)) add(node, "unit", literal);
    if (ts.isJsxText(node)) {
      if (BP_AFTER_VALUE.test(node.getText(sf))) add(node, "unit", node.getText(sf).trim());
      const text = node.getText(sf).replace(/\s+/g, " ").trim();
      if (text && hasUntranslatedWord(text)) add(node, "jsx-text", text);
    } else if (ts.isJsxAttribute(node) && node.initializer) {
      const name = attributeName(node);
      const init = node.initializer;
      const texts = ts.isStringLiteral(init) ? [init.text] : ts.isJsxExpression(init) && init.expression ? literalTexts(init.expression) : [];
      const visible = VISIBLE_ATTRIBUTES.has(name);
      if (visible || (!TECHNICAL_ATTRIBUTES.has(name) && !name.startsWith("data-") && !/^on[A-Z]/.test(name))) {
        for (const text of texts)
          if (!isKey(text) && hasUntranslatedWord(text) && (visible || PHRASE.test(text))) add(node, "attribute", `${name}=${text}`);
      }
    } else if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
      for (const text of literalTexts(node.expression)) if (hasUntranslatedWord(text)) add(node, "jsx-expression", text);
    } else if (ts.isPropertyAssignment(node) && (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name))) {
      const key = node.name.text;
      const phrase = PHRASE_PROPERTIES.has(key);
      if (TEXT_PROPERTIES.has(key) || phrase) {
        for (const text of literalTexts(node.initializer))
          if (!isKey(text) && hasUntranslatedWord(text) && (!phrase || PHRASE.test(text))) add(node, "property", `${key}: ${text}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

// The guide's articles are written in English and Spanish side by side (their parity is tested in guide.test.ts);
// the dictionaries are the translations themselves.
const SKIPPED = new Set(["test", "i18n"]);
const SKIPPED_FILES = new Set(["guide/metrics.ts", "vite-env.d.ts"]);

function sourceFiles(dir: string, root: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return SKIPPED.has(e.name) ? [] : sourceFiles(p, root);
    return /\.tsx?$/.test(e.name) && !SKIPPED_FILES.has(path.relative(root, p)) ? [p] : [];
  });
}

/** Every finding in src (tests, dictionaries and the bilingual guide excluded), with paths relative to src. */
export function scanTree(srcRoot: string): Finding[] {
  return sourceFiles(srcRoot, srcRoot).flatMap((f) => scanSource(path.relative(srcRoot, f), readFileSync(f, "utf8")));
}
