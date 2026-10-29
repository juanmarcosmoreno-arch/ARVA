import { writeFileSync } from "node:fs";
import path from "node:path";
import { it } from "vitest";
import { scanTree } from "./hardcodedText";

it("dump", () => {
  const f = scanTree(path.resolve(__dirname, ".."));
  writeFileSync("/tmp/claude-0/-home-user-ARVA/a0079f7f-7f60-54c5-bf8b-5f8483664aed/scratchpad/findings.txt", f.map((x) => `${x.file}:${x.line} [${x.kind}] ${x.text}`).join("\n"));
});
