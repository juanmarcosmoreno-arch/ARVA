/** Tables the interface builds from data it already has, written as TSV or CSV for a spreadsheet. Headers stay
 * English, like the API's CSV files; numbers are written as the data has them (a dot as decimal separator). */

export type TableFormat = "tsv" | "csv";
export type Cell = string | number | null | undefined;

const FORMULA = /^[=+\-@\t\r\n＝＋－＠]/;
const PLAIN_NUMBER = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;

/** OWASP CSV-injection mitigation, as the API's sanitize_spreadsheet_cell: text starting with = + - @ (or a tab or
 * line break) gets a leading ' so a spreadsheet does not run it. Plain numbers and a bare strand sign stay as they are. */
export function safeCell(value: Cell): string {
  if (value == null) return "";
  const s = String(value);
  if (s === "+" || s === "-" || PLAIN_NUMBER.test(s)) return s;
  return FORMULA.test(s.replace(/^'+/, "")) ? `'${s}` : s;
}

function csvCell(s: string) {
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** The table as text: TSV (tabs and line breaks inside a cell become spaces) or CSV (RFC 4180 quoting). CSV starts with
 * a UTF-8 byte-order mark so that Excel reads accented text right. */
export function delimitedText(columns: string[], rows: Cell[][], format: TableFormat): string {
  const lines = [columns, ...rows].map((row) =>
    row.map((v) => (format === "tsv" ? safeCell(v).replace(/[\t\r\n]+/g, " ") : csvCell(safeCell(v)))).join(format === "tsv" ? "\t" : ","),
  );
  return (format === "csv" ? "﻿" : "") + lines.join("\n") + "\n";
}

/** Saves text as a file through the browser (nothing leaves the computer). */
export function saveText(text: string, filename: string, format: TableFormat) {
  const blob = new Blob([text], { type: format === "tsv" ? "text/tab-separated-values;charset=utf-8" : "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
