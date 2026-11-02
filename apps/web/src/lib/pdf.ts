/** A one-page vector PDF of a figure (lib/regions.ts primitives): polygons, lines and text in the standard Helvetica
 * fonts, so the file needs no embedded font and opens in any PDF reader. Text outside Latin-1 is written as "?"
 * (PDF's standard fonts use WinAnsi encoding), except ≥, ≤ and minus signs, written as >=, <= and -. One figure pixel is one PDF point. */
import type { Figure } from "./regions";

function rgb(color: string): string {
  const hex = color.replace("#", "");
  const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex.slice(0, 6);
  const n = Number.parseInt(full, 16);
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return "0 0 0";
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => (v / 255).toFixed(3)).join(" ");
}

function pdfString(text: string): string {
  let out = "";
  for (const ch of text) {
    const c = ch.charCodeAt(0);
    if (ch === "(" || ch === ")" || ch === "\\") out += `\\${ch}`;
    else if (c >= 32 && c <= 126) out += ch;
    else if (c === 0x2212 || c === 0x2013) out += "-";
    else if (c === 0x2265) out += ">=";
    else if (c === 0x2264) out += "<=";
    else if (c >= 160 && c <= 255) out += `\\${c.toString(8).padStart(3, "0")}`;
    else out += "?";
  }
  return `(${out})`;
}

const n = (v: number) => (Math.round(v * 100) / 100).toString();

/** The PDF file's bytes. `background` fills the page first (the on-screen surface colour). */
export function figurePdf(fig: Figure, background: string, measure: (text: string, size: number) => number): Uint8Array {
  const H = fig.height;
  const alphas = new Map<number, string>();
  const ops: string[] = [`${rgb(background)} rg 0 0 ${n(fig.width)} ${n(H)} re f`];
  for (const p of fig.prims) {
    if (p.kind === "poly") {
      const a = p.opacity ?? 1;
      if (a < 1) {
        if (!alphas.has(a)) alphas.set(a, `GS${alphas.size}`);
        ops.push("q", `/${alphas.get(a)} gs`);
      }
      const path = p.points.map(([x, y], i) => `${n(x)} ${n(H - y)} ${i ? "l" : "m"}`).join(" ");
      ops.push(`${rgb(p.fill)} rg`);
      if (p.stroke && (p.width ?? 0) > 0) ops.push(`${rgb(p.stroke)} RG ${n(p.width!)} w ${path} h B`);
      else ops.push(`${path} h f`);
      if (a < 1) ops.push("Q");
    } else if (p.kind === "line") {
      ops.push(`${rgb(p.stroke)} RG ${n(p.width)} w ${p.dash ? "[3 2] 0 d" : "[] 0 d"} ${n(p.x1)} ${n(H - p.y1)} m ${n(p.x2)} ${n(H - p.y2)} l S`);
    } else {
      const font = p.bold ? "F2" : p.italic ? "F3" : "F1";
      const w = measure(p.text, p.size);
      const off = p.anchor === "middle" ? w / 2 : p.anchor === "end" ? w : 0;
      if (p.rotate) {
        // SVG rotates clockwise with y pointing down; in PDF space (y up) that is the opposite angle.
        const th = (-p.rotate * Math.PI) / 180;
        const c = Math.cos(th);
        const s = Math.sin(th);
        ops.push(`BT /${font} ${n(p.size)} Tf ${rgb(p.fill)} rg ${n(c)} ${n(s)} ${n(-s)} ${n(c)} ${n(p.x - off * c)} ${n(H - p.y - off * s)} Tm ${pdfString(p.text)} Tj ET`);
      } else {
        ops.push(`BT /${font} ${n(p.size)} Tf ${rgb(p.fill)} rg ${n(p.x - off)} ${n(H - p.y)} Td ${pdfString(p.text)} Tj ET`);
      }
    }
  }
  const content = ops.join("\n");
  const gs = [...alphas.entries()].map(([a, name]) => `/${name} << /Type /ExtGState /ca ${a} /CA ${a} >>`).join(" ");
  const fonts = ["Helvetica", "Helvetica-Bold", "Helvetica-Oblique"]
    .map((f, i) => `/F${i + 1} << /Type /Font /Subtype /Type1 /BaseFont /${f} /Encoding /WinAnsiEncoding >>`).join(" ");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${n(fig.width)} ${n(H)}] /Contents 4 0 R /Resources << /Font << ${fonts} >> /ExtGState << ${gs} >> >> >>`,
    `<< /Length ${new TextEncoder().encode(content).length} >>\nstream\n${content}\nendstream`,
    "<< /Producer (ARVA) >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((o, i) => {
    offsets.push(new TextEncoder().encode(body).length);
    body += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = new TextEncoder().encode(body).length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(body);
}
