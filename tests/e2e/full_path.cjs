/**
 * ARVA end-to-end full path on real public data (Playwright).
 *
 * Requires the full stack running (API, worker, web) with the analysis tools installed — see docs/installation.md.
 *   ARVA_WEB_URL=http://localhost:5173 ARVA_E2E_READS=/path/to/reads node tests/e2e/full_path.cjs
 *
 * ARVA_E2E_READS holds subsets of S. aureus JKD6159 runs from ENA (SRR21386012 ONT, SRR21386014 Illumina pair):
 *   SRR21386012_subset_35k.fastq.gz, SRR21386014_subset_350k_1.fastq.gz, SRR21386014_subset_350k_2.fastq.gz
 * (the first 35,000 / 350,000 reads of each run; see the SHA256SUMS file written next to them).
 *
 * ARVA_E2E_DATABASES: comma-separated existing database folders to register (Bakta, AMRFinderPlus, MOB-suite, a
 * reference genome collection); they must lie in ARVA_EXTERNAL_DB_ROOTS. ARVA_E2E_GENOMES: folder with the RefSeq FASTA
 * files GCF_000144955.2.fna (JKD6159, the truth for this run) and the comparison genomes listed in REFERENCES below.
 *
 * Every stage is driven through the interface. A stage whose result already exists in the project named by
 * ARVA_E2E_PROJECT is skipped, so an interrupted run can be resumed. The numbers asserted are smoke checks of
 * plausibility for this organism, not a validation of the tools.
 */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const BASE = process.env.ARVA_WEB_URL ?? "http://localhost:5173";
const READS = process.env.ARVA_E2E_READS;
const PROJECT = process.env.ARVA_E2E_PROJECT ?? "JKD6159 full path";
const SAMPLE = "JKD6159-subset";
const ONT = "SRR21386012_subset_35k.fastq.gz";
const R1 = "SRR21386014_subset_350k_1.fastq.gz";
const R2 = "SRR21386014_subset_350k_2.fastq.gz";
const STAGES = (process.env.ARVA_E2E_STAGES ?? "").split(",").filter(Boolean);
const HOUR = 3_600_000;
const GENOMES = process.env.ARVA_E2E_GENOMES;
const DATABASES = (process.env.ARVA_E2E_DATABASES ?? "").split(",").filter(Boolean);
const TRUTH = { code: "JKD6159-RefSeq", file: "GCF_000144955.2.fna", source: "NCBI RefSeq GCF_000144955.2", strain: "JKD6159", tag: "JKDREF" };
const REFERENCES = [
  TRUTH,
  { code: "USA300_FPR3757-RefSeq", file: "GCF_000013465.1.fna", source: "NCBI RefSeq GCF_000013465.1", strain: "USA300_FPR3757", tag: "USA300" },
  { code: "N315-RefSeq", file: "GCF_000009645.1.fna", source: "NCBI RefSeq GCF_000009645.1", strain: "N315", tag: "N315" },
  { code: "MW2-RefSeq", file: "GCF_000011265.1.fna", source: "NCBI RefSeq GCF_000011265.1", strain: "MW2", tag: "MWTWO" },
];

const api = (page) => ({
  get: async (p) => {
    const r = await page.request.get(`${BASE}/api/v1${p}`);
    assert.ok(r.ok(), `GET ${p} → ${r.status()}`);
    return r.json();
  },
});

async function waitFor(fn, { timeout = HOUR, every = 5000, what = "condition" } = {}) {
  const end = Date.now() + timeout;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, every));
  }
}

let stageStart = new Date(0).toISOString();
async function jobsDone(page, sampleId, type, n = 1) {
  return waitFor(async () => {
    const jobs = await api(page).get(`/samples/${sampleId}/jobs`);
    const failed = jobs.filter((j) => j.job_type === type && j.status === "failed" && j.created_at > stageStart);
    if (failed.length) throw new Error(`${type} failed: ${failed[0].error_message ?? failed[0].error ?? ""}`);
    const done = jobs.filter((j) => j.job_type === type && j.status === "completed");
    return done.length >= n ? done : null;
  }, { what: type });
}

async function hasJob(page, sampleId, type) {
  const jobs = await api(page).get(`/samples/${sampleId}/jobs`);
  return jobs.some((j) => j.job_type === type && ["queued", "running", "completed"].includes(j.status));
}

const want = (stage) => STAGES.length === 0 || STAGES.includes(stage);

(async () => {
  assert.ok(READS && fs.existsSync(path.join(READS, ONT)), "set ARVA_E2E_READS to the folder with the read subsets");
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.setDefaultTimeout(60_000);
  const log = (s) => {
    stageStart = new Date().toISOString();
    console.log(`[${stageStart.slice(11, 19)}] ${s}`);
  };

  await page.goto(BASE);
  const splash = page.getByRole("dialog", { name: "ARVA is starting" });
  if (await splash.isVisible().catch(() => false)) await splash.getByRole("button", { name: "Skip" }).click();

  // Project and sample
  let project = (await api(page).get("/projects")).find((p) => p.name === PROJECT);
  if (!project) {
    log("create project");
    await page.getByRole("button", { name: "New project" }).first().click();
    await page.getByRole("dialog").getByRole("textbox").first().fill(PROJECT);
    await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
    await page.waitForURL(/\/projects\/[0-9a-f-]+$/);
    project = (await api(page).get("/projects")).find((p) => p.name === PROJECT);
  }
  let sample = (await api(page).get(`/projects/${project.id}/samples`)).find((s) => s.sample_code === SAMPLE);
  if (!sample) {
    log("create sample");
    await page.goto(`${BASE}/projects/${project.id}`);
    await page.getByRole("button", { name: "New sample" }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByPlaceholder("e.g. SA-2024-001").fill(SAMPLE);
    await dlg.locator("select").first().selectOption("hybrid");
    await dlg.getByPlaceholder("e.g. Staphylococcus aureus").fill("Staphylococcus aureus");
    await dlg.locator("textarea").first().fill(
      "Subset of SRR21386012 (ONT MinION, first 35,000 reads) and subset of SRR21386014 (Illumina NextSeq 500, "
      + "first 350,000 read pairs), S. aureus JKD6159 (BioSample SAMN02604217). Reference genome GCF_000144955.2.");
    await dlg.getByRole("button", { name: "Create" }).click();
    await page.waitForURL(/\/samples\/[0-9a-f-]+/);
    sample = (await api(page).get(`/projects/${project.id}/samples`)).find((s) => s.sample_code === SAMPLE);
  }
  const sid = sample.id;
  const samplePage = () => page.goto(`${BASE}/samples/${sid}`);

  // Import and read statistics
  if (want("import") && (await api(page).get(`/samples/${sid}/files`)).length === 0) {
    log("upload reads");
    await samplePage();
    await page.locator('input[type="file"]').setInputFiles([ONT, R1, R2].map((f) => path.join(READS, f)));
    await page.getByText("structure verified").first().waitFor({ timeout: 10 * 60_000 });
    await page.getByRole("button", { name: /Analyse 3 files/ }).click();
    await jobsDone(page, sid, "sequence_stats", 3);
  }
  const files = async () => api(page).get(`/samples/${sid}/files`);
  const raw = Object.fromEntries((await files()).filter((f) => [ONT, R1, R2].includes(f.original_filename)).map((f) => [f.original_filename, f]));

  if (want("qc")) {
    await waitFor(async () => !(await api(page).get(`/samples/${sid}/jobs`))
      .some((j) => j.job_type === "fastqc" && ["pending", "queued", "running"].includes(j.status)), { what: "FastQC queue" });
    const done = new Set((await api(page).get(`/samples/${sid}/jobs`))
      .filter((j) => j.job_type === "fastqc" && j.status === "completed").flatMap((j) => j.input_raw_file_ids));
    const missing = Object.values(raw).filter((f) => !done.has(f.id));
    if (missing.length) {
      log(`FastQC on ${missing.map((f) => f.original_filename).join(", ")}`);
      await samplePage();
      for (const f of await files()) {
        if (!missing.includes(f)) {
          const box = page.getByRole("checkbox", { name: `Include ${f.original_filename}` });
          if (await box.count()) await box.uncheck();
        }
      }
      await page.getByText("FastQC report").first().waitFor();
      await page.getByRole("button", { name: "Run", exact: true }).nth(1).click();
      await jobsDone(page, sid, "fastqc", 3);
    }
  }

  if (want("filter") && !(await hasJob(page, sid, "fastp"))) {
    log("fastp on the Illumina pair (NextSeq: poly-G trimming forced, SRA headers hide the instrument)");
    await samplePage();
    await page.getByRole("checkbox", { name: `Include ${ONT}` }).uncheck();
    await page.getByRole("button", { name: "Filter reads…" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("combobox", { name: "Read 1 (or single-end reads)" }).selectOption({ label: R1 });
    await dlg.getByRole("combobox", { name: "Read 2 (paired-end, optional)" }).selectOption({ label: R2 });
    await dlg.getByRole("combobox", { name: "Poly-G tail trimming" }).selectOption({ label: "Always trim poly-G tails" });
    await dlg.getByText("I have reviewed these settings").click();
    await dlg.getByRole("button", { name: "Run fastp" }).click();
    await jobsDone(page, sid, "fastp");
  }
  if (want("filter") && !(await hasJob(page, sid, "filtlong"))) {
    log("Filtlong on the ONT reads (min 1 kb, keep best 90 % of bases)");
    await samplePage();
    await page.getByRole("button", { name: "Filter reads…" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("radio", { name: /Filtlong/ }).click();
    await dlg.getByRole("combobox", { name: "Long-read file" }).selectOption({ label: ONT });
    await dlg.getByText("I have reviewed these settings").click();
    await dlg.getByRole("button", { name: "Run Filtlong" }).click();
    await jobsDone(page, sid, "filtlong");
  }
  const derived = (await files()).filter((f) => f.origin === "derived");
  log(`derived files: ${derived.map((f) => f.original_filename).join(", ")}`);
  assert.ok(raw[ONT] && raw[R1] && raw[R2], "three raw files");
  const ontFiltered = derived.find((f) => f.original_filename.endsWith(".filtlong.fastq.gz"));
  const assemblies = async () => api(page).get(`/samples/${sid}/assemblies`);

  if (want("assembly") && !(await hasJob(page, sid, "flye_assembly"))) {
    log("Flye on the Filtlong-filtered ONT reads");
    await samplePage();
    await page.getByRole("tab", { name: "Assembly" }).click();
    await page.getByRole("button", { name: /New assembly/ }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("radio", { name: /^Flye/ }).click();
    const reads = dlg.getByRole("list", { name: "Reads to assemble" });
    // The dialog preselects the imported long-read file once it has opened.
    await waitFor(() => reads.getByRole("checkbox", { name: ONT, exact: true }).isChecked(), { every: 200, timeout: 10_000 });
    await reads.getByRole("checkbox", { name: ONT, exact: true }).uncheck();
    await reads.getByRole("checkbox", { name: ontFiltered.original_filename }).check();
    await dlg.getByRole("combobox", { name: "Read type" }).selectOption({ index: 1 });
    await dlg.getByRole("spinbutton", { name: /^Threads/ }).fill("4");
    await dlg.getByText("I have reviewed what this run will do").click();
    await dlg.getByRole("button", { name: "Start assembly" }).click();
    await jobsDone(page, sid, "flye_assembly");
  }
  const flyeBrief = (await assemblies()).find((a) => a.assembler === "Flye");
  assert.ok(flyeBrief, "Flye registered an assembly");
  const flye = await api(page).get(`/assemblies/${flyeBrief.id}`);
  const plasmid = flye.contigs.find((c) => c.circular && c.length > 15_000 && c.length < 30_000);
  log(`Flye: ${flye.stats.contig_count} contigs, ${flye.stats.total_length} bp, N50 ${flye.stats.n50}; circular contigs `
    + flye.contigs.filter((c) => c.circular).map((c) => c.length).join(", "));
  assert.ok(flye.stats.total_length > 2_700_000 && flye.stats.total_length < 3_000_000, "assembly length plausible for S. aureus");
  assert.ok(plasmid, "a circular contig of plasmid size (JKD6159 carries the 20.7 kb pSaa6159)");

  const fastp = derived.filter((f) => f.original_filename.includes(".fastp."));
  if (want("polishing") && !(await hasJob(page, sid, "pilon_polish"))) {
    log("Hybrid polishing: Racon (ONT, map-ont) then Pilon (Illumina, fastp output)");
    await samplePage();
    await page.getByRole("tab", { name: "Assembly" }).click();
    await page.getByRole("button", { name: "Polish", exact: true }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("radio", { name: /^Hybrid: Racon, then Pilon/ }).check();
    await dlg.getByRole("combobox", { name: "Long reads" }).selectOption({ label: `${ontFiltered.original_filename} (filtered)` });
    const r1 = fastp.find((f) => f.original_filename.includes("_1.")), r2 = fastp.find((f) => f.original_filename.includes("_2."));
    await dlg.getByRole("combobox", { name: "R1 (forward reads of the pairs)" }).selectOption({ label: `${r1.original_filename} (filtered)` });
    await dlg.getByRole("combobox", { name: "R2 (reverse reads of the pairs)" }).selectOption({ label: `${r2.original_filename} (filtered)` });
    await dlg.getByRole("combobox", { name: "Long-read type (minimap2 preset)" }).selectOption("map-ont");
    await dlg.getByRole("spinbutton", { name: /^Threads/ }).fill("4");
    await dlg.getByRole("button", { name: "Polish", exact: true }).click();
    await jobsDone(page, sid, "racon_polish");
    await jobsDone(page, sid, "pilon_polish");
  }
  const polished = (await assemblies()).find((a) => a.assembler === "Pilon");
  assert.ok(polished, "Pilon registered a polished assembly");
  log(`polished: ${polished.stats.contig_count} contigs, ${polished.stats.total_length} bp`);

  if (want("databases") && DATABASES.length) {
    const have = (await api(page).get("/databases")).map((d) => d.path);
    for (const dir of DATABASES.filter((d) => !have.includes(d))) {
      log(`register database ${dir}`);
      await page.goto(`${BASE}/tools`);
      await page.getByRole("button", { name: "Register existing folder…" }).first().click();
      const dlg = page.getByRole("dialog");
      await dlg.getByRole("textbox", { name: "Absolute path of the database folder or file" }).fill(dir);
      await dlg.getByRole("button", { name: "Detect", exact: true }).click();
      const date = dlg.getByRole("textbox", { name: /^Date of the collection/ });
      // An NCBI Datasets package records no download date: ARVA asks for it (README of the test package: 2026-11-02).
      await dlg.getByRole("button", { name: "Register", exact: true }).waitFor();
      if (await date.isVisible()) await date.fill(process.env.ARVA_E2E_COLLECTION_DATE ?? "2026-11-02");
      await dlg.getByRole("button", { name: "Register", exact: true }).click();
      await dlg.waitFor({ state: "detached" });
    }
  }

  // Public genomes, each in its own sample, registered as imported assemblies.
  const refSamples = {};
  for (const g of REFERENCES) {
    const s = (await api(page).get(`/projects/${project.id}/samples`)).find((x) => x.sample_code === g.code);
    if (s) refSamples[g.code] = s;
  }
  if (want("references") && GENOMES) {
    for (const g of REFERENCES) {
      let s = refSamples[g.code];
      if (!s) {
        log(`sample ${g.code}`);
        await page.goto(`${BASE}/projects/${project.id}`);
        await page.getByRole("button", { name: "New sample" }).first().click();
        const dlg = page.getByRole("dialog");
        await dlg.getByPlaceholder("e.g. SA-2024-001").fill(g.code);
        await dlg.getByPlaceholder("e.g. Staphylococcus aureus").fill("Staphylococcus aureus");
        await dlg.locator("textarea").first().fill(`${g.source}, downloaded from NCBI; registered as an imported genome.`);
        await dlg.getByRole("button", { name: "Create" }).click();
        await page.waitForURL(/\/samples\/[0-9a-f-]+/);
        s = (await api(page).get(`/projects/${project.id}/samples`)).find((x) => x.sample_code === g.code);
      }
      refSamples[g.code] = s;
      if ((await api(page).get(`/samples/${s.id}/assemblies`)).length) continue;
      if (!(await api(page).get(`/samples/${s.id}/files`)).length) {
        await page.goto(`${BASE}/samples/${s.id}`);
        await page.locator('input[type="file"]').setInputFiles(path.join(GENOMES, g.file));
        await page.getByText("structure verified").first().waitFor({ timeout: 120_000 });
      }
      log(`register ${g.file} as an imported genome (${g.source})`);
      await page.goto(`${BASE}/samples/${s.id}?tab=assembly`);
      await page.getByRole("button", { name: "Register a genome FASTA…" }).click();
      const dlg = page.getByRole("dialog");
      await dlg.getByRole("textbox", { name: "Source" }).fill(g.source);
      await dlg.getByRole("checkbox").check();
      await dlg.getByRole("button", { name: "Register", exact: true }).click();
      await dlg.waitFor({ state: "detached" });
      await jobsDone(page, s.id, "assembly_import");
    }
  }

  // QUAST against the truth genome, uploaded to the sample as its reference
  if (want("quast") && GENOMES && !(await hasJob(page, sid, "quast_evaluation"))) {
    if (!(await files()).some((f) => f.original_filename === TRUTH.file)) {
      log("upload the truth genome to the sample as a QUAST reference");
      await samplePage();
      await page.locator('input[type="file"]').setInputFiles(path.join(GENOMES, TRUTH.file));
      await page.getByText("structure verified").first().waitFor({ timeout: 120_000 });
    }
    log("QUAST: Flye, Racon and Pilon against GCF_000144955.2");
    await page.goto(`${BASE}/samples/${sid}?tab=assembly`);
    await page.getByRole("button", { name: "Evaluate with QUAST…" }).click();
    const dlg = page.getByRole("dialog");
    const ref = dlg.getByRole("combobox", { name: "Reference genome (optional)" });
    await ref.selectOption(await ref.locator("option", { hasText: TRUTH.file }).getAttribute("value"));
    await dlg.getByRole("button", { name: "Start the evaluation" }).click();
    const [q] = await jobsDone(page, sid, "quast_evaluation");
    log(`QUAST: ${JSON.stringify(q.result_summary).slice(0, 600)}`);
  }

  // Bakta (the registered database) on the polished assembly and on every imported genome, the same way for all,
  // so the pangenome compares like with like.
  const genomes = [{ sampleId: sid, assemblyId: polished.id, strain: "JKD6159", tag: "JKDSUB", keepHeaders: false },
    ...REFERENCES.filter((g) => refSamples[g.code]).map((g) => ({ sampleId: refSamples[g.code].id, strain: g.strain, tag: g.tag, keepHeaders: true }))];
  if (want("annotation")) {
    for (const g of genomes) {
      if (await hasJob(page, g.sampleId, "bakta_annotation")) continue;
      log(`Bakta on ${g.strain}`);
      await page.goto(`${BASE}/samples/${g.sampleId}?tab=annotation`);
      await page.getByRole("button", { name: "New annotation…" }).click();
      const dlg = page.getByRole("dialog");
      if (g.assemblyId) await dlg.getByRole("combobox", { name: "Assembly" }).selectOption(g.assemblyId);
      await dlg.getByRole("radio", { name: /^Bakta/ }).check();
      await dlg.getByRole("textbox", { name: /^Locus-tag prefix/ }).fill(g.tag);
      await dlg.getByRole("textbox", { name: /^Genus/ }).fill("Staphylococcus");
      await dlg.getByRole("textbox", { name: /^Species/ }).fill("aureus");
      await dlg.getByRole("textbox", { name: /^Strain/ }).fill(g.strain);
      await dlg.getByRole("spinbutton", { name: /^Threads/ }).fill("4");
      if (g.keepHeaders) await dlg.getByRole("checkbox", { name: /^Keep the assembly's contig names/ }).check();
      await dlg.getByRole("checkbox", { name: /^I have read what this run will and will not search/ }).check();
      await dlg.getByRole("button", { name: "Annotate", exact: true }).click();
      await dlg.waitFor({ state: "detached" });
    }
    for (const g of genomes) await jobsDone(page, g.sampleId, "bakta_annotation");
  }

  // Genomic analysis of the polished assembly, each step from its dialog on the Genomic analysis tab.
  const genomic = async (button, type, fill, n = 1) => {
    const done = (await api(page).get(`/samples/${sid}/jobs`)).filter((j) => j.job_type === type && j.status === "completed");
    if (done.length >= n) return done;
    log(`${button}`);
    await page.goto(`${BASE}/samples/${sid}?tab=genomic`);
    await page.getByRole("button", { name: button, exact: true }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("combobox", { name: "Assembly" }).selectOption(polished.id);
    await fill(dlg);
    await dlg.waitFor({ state: "detached" });
    return jobsDone(page, sid, type, n);
  };
  const confirmAndRun = async (dlg, confirm, run) => {
    await dlg.getByRole("checkbox", { name: confirm }).check();
    await dlg.getByRole("button", { name: run, exact: true }).click();
  };
  if (want("genomic")) {
    await genomic("Identify species", "species_identification", async (dlg) => {
      await dlg.getByRole("radio", { name: /^FastANI/ }).check();
      await dlg.getByRole("spinbutton", { name: /^Threads/ }).fill("4");
      await confirmAndRun(dlg, /^I have checked the method and the database/, "Identify");
    });
    await genomic("Run MLST", "mlst_typing", async (dlg) => {
      await confirmAndRun(dlg, /^I have read the summary and want to run mlst/, "Run mlst");
    });
    await genomic("Search AMR genes", "amr_detection", async (dlg) => {
      await dlg.getByRole("radio", { name: /combined search/i }).check();
      const ann = dlg.getByRole("combobox", { name: "Annotation" });
      await ann.selectOption(await ann.locator("option", { hasText: "Bakta" }).first().getAttribute("value"));
      const org = dlg.getByRole("combobox", { name: "Organism (--organism)" });
      await org.selectOption({ label: "Staphylococcus aureus" });
      await confirmAndRun(dlg, /^I have checked the database, the organism and the options/, "Run AMRFinderPlus");
    });
    await genomic("Search plasmids and mobile elements", "mobile_elements", async (dlg) => {
      await dlg.getByRole("radio", { name: /^Plasmid reconstruction \(MOB-suite/ }).check();
      await confirmAndRun(dlg, /^I have checked the method, the database and the settings/, "Run search");
    });
    await genomic("Search plasmids and mobile elements", "mobile_elements", async (dlg) => {
      await dlg.getByRole("radio", { name: /^Plasmid replicons \(PlasmidFinder/ }).check();
      await confirmAndRun(dlg, /^I have checked the method, the database and the settings/, "Run search");
    }, 2);
    for (const [step, n] of [[/^SCCmec typing/, 1], [/^agr typing/, 2]]) {
      await genomic("S. aureus typing", "species_typing", async (dlg) => {
        await dlg.getByRole("radio", { name: step }).check();
        await confirmAndRun(dlg, /^I checked the step, the data it reads and the settings/, "Run step");
      }, n);
    }
    const [mlst] = await api(page).get(`/samples/${sid}/mlst`);
    const [species] = await api(page).get(`/samples/${sid}/species`);
    const typing = (await api(page).get(`/samples/${sid}/typing`)).results;
    log(`MLST ${mlst.scheme} ST${mlst.st} (${mlst.status}); species ${species.interpretation?.species ?? JSON.stringify(species.interpretation).slice(0, 120)}; `
      + typing.map((r) => `${r.method} ${r.status} ${r.call}`).join("; "));
    assert.equal(mlst.scheme, "saureus", "mlst detects the S. aureus scheme");
    // Smoke check against the published genome: the same tool on GCF_000144955.2 must give the same ST.
    const truth = refSamples[TRUTH.code];
    if (truth && !(await api(page).get(`/samples/${truth.id}/mlst`)).length) {
      log("MLST on the imported JKD6159 RefSeq genome");
      await page.goto(`${BASE}/samples/${truth.id}?tab=genomic`);
      await page.getByRole("button", { name: "Run MLST", exact: true }).first().click();
      const dlg = page.getByRole("dialog");
      await confirmAndRun(dlg, /^I have read the summary and want to run mlst/, "Run mlst");
      await dlg.waitFor({ state: "detached" });
      await jobsDone(page, truth.id, "mlst_typing");
    }
    if (truth) {
      const [ref] = await api(page).get(`/samples/${truth.id}/mlst`);
      log(`MLST of GCF_000144955.2: ST${ref.st} (${ref.status})`);
      assert.equal(mlst.st, ref.st, "the subset assembly has the ST of the published genome");
    }
  }

  // Comparison set: the truth genome first (the default reference), the polished assembly, three other RefSeq genomes.
  const SET = "JKD6159 subset vs RefSeq";
  let cset = (await api(page).get("/comparisons")).find((c) => c.name === SET);
  if (want("comparison") && !cset) {
    log("comparison set");
    await page.goto(`${BASE}/comparative`);
    await page.getByRole("button", { name: "New comparison set" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("textbox", { name: "Name" }).fill(SET);
    const proj = dlg.getByRole("combobox", { name: /^Kept in project/ });
    await proj.selectOption({ label: PROJECT });
    const pick = (re) => dlg.getByRole("checkbox", { name: re }).check();
    await pick(/^JKD6159-RefSeq · /);
    await pick(/^JKD6159-subset · .* Pilon /);
    await pick(/^USA300_FPR3757-RefSeq · /);
    await pick(/^N315-RefSeq · /);
    await pick(/^MW2-RefSeq · /);
    await dlg.getByRole("button", { name: "Save set" }).click();
    await dlg.waitFor({ state: "detached" });
    cset = (await api(page).get("/comparisons")).find((c) => c.name === SET);
  }

  const projectJobsDone = async (type, n = 1) => waitFor(async () => {
    const jobs = (await api(page).get(`/projects/${project.id}/jobs`)).filter((j) => j.job_type === type);
    const failed = jobs.filter((j) => j.status === "failed" && j.created_at > stageStart);
    if (failed.length) throw new Error(`${type} failed: ${failed[0].error_message ?? ""}`);
    return jobs.filter((j) => j.status === "completed").length >= n ? jobs : null;
  }, { what: type });
  const hasProjectJob = async (type) => (await api(page).get(`/projects/${project.id}/jobs`))
    .some((j) => j.job_type === type && ["pending", "queued", "running", "completed"].includes(j.status));
  const setAction = async (button, type, fill, submit) => {
    if (await hasProjectJob(type)) return projectJobsDone(type);
    log(button);
    await page.goto(`${BASE}/comparative/${cset.id}`);
    await page.getByRole("button", { name: button, exact: true }).click();
    const dlg = page.getByRole("dialog");
    await fill(dlg);
    await dlg.getByRole("checkbox", { name: "I checked the genomes, the tool and its settings." }).check();
    await dlg.getByRole("button", { name: submit, exact: true }).click();
    await dlg.waitFor({ state: "detached" });
    return projectJobsDone(type);
  };
  if (want("comparison") && cset) {
    await setAction("Run ANI", "comparative_ani", async (dlg) => {
      await dlg.getByRole("radio", { name: /^skani triangle/ }).check();
      await dlg.getByRole("spinbutton", { name: /^Threads/ }).fill("4");
    }, "Run ANI");
    await setAction("Align genomes", "comparative_alignment", async (dlg) => {
      await dlg.getByRole("radio", { name: /^MUMmer NUCmer/ }).check();
      await dlg.getByRole("checkbox", { name: /^Structural differences with dnadiff/ }).check();
    }, "Align genomes");
    await setAction("Pangenome", "pangenome", async (dlg) => {
      await dlg.getByRole("radio", { name: /^Panaroo/ }).check();
      await dlg.getByRole("combobox", { name: /^Gene alignments/ }).selectOption({ label: "Core families" });
    }, "Build the pangenome");
    await setAction("Phylogeny", "phylogeny", async (dlg) => {
      const source = dlg.getByRole("combobox", { name: /^Source/ });
      await source.selectOption(await source.locator("option", { hasText: "Core-genome SNPs" }).first().getAttribute("value"));
      await dlg.getByRole("spinbutton", { name: /^Threads/ }).fill("4");
      // The plan (sequences and file of the chosen source) loads before the run can be confirmed.
      await dlg.getByText(/sequences · file/).waitFor();
    }, "Build tree");
  }

  // Workflow Builder: the predefined "Virulence screening" workflow (ABRicate VFDB) over every sample of the project.
  if (want("workflow") && !(await api(page).get("/batches")).length) {
    let wf = (await api(page).get("/workflows")).find((w) => w.name === "Virulence screening");
    if (!wf) {
      log("workflow from the predefined Virulence screening");
      await page.goto(`${BASE}/workflows`);
      await page.locator("li, div").filter({ has: page.getByText("Virulence screening", { exact: true }) })
        .getByRole("button", { name: "Use" }).last().click();
      await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
      await page.waitForURL(/\/workflows\/[0-9a-f-]+$/);
      wf = (await api(page).get("/workflows")).find((w) => w.name === "Virulence screening");
    }
    log("run the workflow on the project's samples");
    await page.goto(`${BASE}/workflows/${wf.id}`);
    await page.getByRole("button", { name: "Run", exact: true }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByRole("combobox", { name: "Project" }).selectOption({ label: PROJECT });
    await dlg.getByRole("checkbox", { name: "I have checked this summary; run it." }).check();
    await dlg.getByRole("button", { name: "Start run" }).click();
    await page.waitForURL(/\/workflows\/runs\/[0-9a-f-]+/);
  }
  if (want("workflow")) {
    const run = await waitFor(async () => {
      const [r] = await api(page).get("/batches");
      return r && !["queued", "running", "pending"].includes(r.status) ? r : null;
    }, { what: "workflow run" });
    log(`workflow run: ${run.status} ${JSON.stringify(run.counts ?? run.summary ?? {})}`);
    assert.equal(run.status, "completed", "workflow run completed");
  }

  // Reports: the sample report in every format and the project report in both languages, from the interface.
  if (want("reports")) {
    log("reports");
    for (const fmt of ["html", "json", "csv"]) {
      const res = await page.request.get(`${BASE}/api/v1/samples/${sid}/report?format=${fmt}`);
      assert.equal(res.status(), 200, `sample report ${fmt}`);
    }
    for (const lang of ["en", "es"]) {
      const res = await page.request.get(`${BASE}/api/v1/projects/${project.id}/report?format=html&lang=${lang}`);
      assert.equal(res.status(), 200, `project report ${lang}`);
      const html = await res.text();
      assert.ok(html.includes("JKD6159-subset") && html.includes("GCF_000144955.2"), "project report names the sample and the truth genome");
    }
    if (cset) {
      assert.equal((await page.request.get(`${BASE}/api/v1/comparisons/${cset.id}/report.html`)).status(), 200, "comparative report");
    }
    // The project page offers the full report in each format, in the interface's language.
    await page.goto(`${BASE}/projects/${project.id}`);
    await page.getByRole("heading", { name: "Full project report" }).waitFor();
    const links = page.locator(`a[href*="/projects/${project.id}/report?format="]`);
    assert.ok((await links.count()) >= 3, "project report links");
    for (const href of await links.evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
      if (href.includes("format=pdf")) continue;
      assert.equal((await page.request.get(new URL(href, BASE).toString())).status(), 200, href);
    }
  }

  assert.deepEqual(errors, [], "no browser console errors");
  await browser.close();
  log("E2E full path passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
