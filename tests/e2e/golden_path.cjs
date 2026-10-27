/**
 * ARVA end-to-end golden path (Playwright).
 *
 * Requires the full stack running (API, worker, web) — see docs/installation.md.
 *   ARVA_WEB_URL=http://localhost:5173 node tests/e2e/golden_path.cjs
 *
 * Creates a project and sample, uploads the synthetic paired Illumina reads,
 * runs read statistics in the background worker, checks the results, the
 * guide dialog, history/provenance and all report formats.
 */
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const BASE = process.env.ARVA_WEB_URL ?? "http://localhost:5173";
const DATA = path.resolve(__dirname, "../../examples/synthetic");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  const stamp = Date.now();

  await page.goto(BASE);
  await page.getByRole("heading", { name: "Welcome to ARVA" }).waitFor();

  await page.getByRole("button", { name: "New project" }).first().click();
  await page.getByRole("dialog").getByRole("textbox").first().fill(`E2E project ${stamp}`);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+$/);

  await page.getByRole("button", { name: "New sample" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByPlaceholder("e.g. SA-2024-001").fill(`E2E-${stamp}`);
  await dlg.locator("select").first().selectOption("illumina");
  await dlg.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/samples\/[0-9a-f-]+/);

  await page.locator('input[type="file"]').setInputFiles([
    path.join(DATA, "SYNTHETIC_illumina_R1_001.fastq.gz"),
    path.join(DATA, "SYNTHETIC_illumina_R2_001.fastq.gz"),
  ]);
  await page.getByText("structure verified").first().waitFor({ timeout: 60_000 });
  assert.equal(await page.getByText("R1", { exact: true }).count() > 0, true, "R1 mate detected");

  await page.getByRole("button", { name: /Analyse 2 files/ }).click();
  await page.getByText("Mean read quality").first().waitFor({ timeout: 60_000 });
  await page.getByText("2,000", { exact: true }).first().waitFor();
  assert.ok((await page.locator(".echarts-for-react svg").count()) >= 5, "charts rendered");

  await page.getByRole("button", { name: /What does this mean\? — N50/ }).click();
  await page.getByRole("dialog").getByText("N50 is the length L").waitFor();
  await page.keyboard.press("Escape");

  await page.getByRole("tab", { name: /Analysis history \(2\)/ }).click();
  await page.locator("button[aria-expanded]").filter({ hasText: "Read statistics" }).first().click();
  await page.getByText("sha256:").first().waitFor();

  const sampleId = page.url().split("/samples/")[1].split("?")[0];
  for (const fmt of ["html", "csv", "json"]) {
    const res = await page.request.get(`${BASE}/api/v1/samples/${sampleId}/report?format=${fmt}`);
    assert.equal(res.status(), 200, `report ${fmt}`);
  }
  const csv = await (await page.request.get(`${BASE}/api/v1/samples/${sampleId}/report?format=csv`)).text();
  assert.equal(csv.trim().split("\n").length, 3, "CSV has header + 2 files");

  assert.deepEqual(errors, [], "no browser console errors");
  await browser.close();
  console.log("E2E golden path passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
