import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "test" || e.name === "i18n" ? [] : sourceFiles(p);
    return /\.tsx?$/.test(e.name) ? [p] : [];
  });
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Whether the sources can reach a key: as a literal ("nav.samples"), through a template literal key
 * (`annotation.type.${type}`), or under a dotted prefix handed to a helper (messageText(t, "job.error", …)). */
export function keyUsage(srcRoot: string): (key: string) => boolean {
  const literals = new Set<string>();
  const patterns: RegExp[] = [];
  for (const file of sourceFiles(srcRoot)) {
    const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const visit = (node: ts.Node) => {
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) literals.add(node.text);
      else if (ts.isTemplateExpression(node) && /^[a-z][\w]*\./.test(node.head.text)) {
        const parts = [node.head.text, ...node.templateSpans.map((s) => s.literal.text)];
        patterns.push(new RegExp(`^${parts.map(escape).join(".+")}$`));
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  const prefixes = [...literals].filter((l) => /^[a-z][\w]*(\.[\w-]+)*\.?$/.test(l) && l.includes(".")).map((l) => (l.endsWith(".") ? l : `${l}.`));
  return (key) => literals.has(key) || patterns.some((p) => p.test(key)) || prefixes.some((p) => key.startsWith(p));
}
