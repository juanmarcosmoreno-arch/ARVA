/**
 * Shared by check_multiqc_report.cjs and check_nanoplot_report.cjs: opens a tool report in headless
 * Chromium as ARVA serves it and records what renders, script errors, requests to other hosts, CSP
 * violations of probe requests, and what a script inside the report could reach on ARVA's origin.
 */
const fs = require("node:fs");
const http = require("node:http");
const { chromium } = require("playwright");

// Like ARVA's UI and API, this same-origin URL is served without a CSP.
const SAME_ORIGIN_PROBE = "/api/v1/projects";

function serve(file, headers) {
  const body = fs.readFileSync(file);
  const server = http.createServer((req, res) => {
    if (req.url === "/report.html") {
      res.writeHead(200, headers);
      return res.end(body);
    }
    if (req.url === SAME_ORIGIN_PROBE) {
      res.writeHead(200, { "content-type": "application/json" });
      return res.end('[{"name": "a project"}]');
    }
    return res.writeHead(404).end();
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

// A script in the report opens a same-origin window: it must not be able to script it, and the window
// must inherit the report's opaque origin (an unsandboxed report could drive ARVA's API through it).
async function sameOriginEscape(context, page) {
  const popupEvent = context.waitForEvent("page", { timeout: 10000 }).catch(() => null);
  const opened = await page.evaluate((path) => {
    window.__probe = window.open(path);
    return Boolean(window.__probe);
  }, SAME_ORIGIN_PROBE);
  const popup = await popupEvent;
  if (!opened || !popup) return { opened: false };
  await popup.waitForLoadState("load").catch(() => {});
  const access = await page.evaluate(() => {
    try {
      return { scriptable: true, text: window.__probe.document.body.innerText.slice(0, 80) };
    } catch (e) {
      return { scriptable: false, error: e.name };
    }
  });
  const popupOrigin = await popup.evaluate(() => window.origin).catch((e) => `error: ${e.message}`);
  await popup.close();
  return { opened: true, ...access, popupOrigin };
}

async function inspect(url, { renderSelector, measure, probeFetch, probeImage }) {
  const origin = new URL(url).origin;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const external = [];
    await context.route("**/*", (route) => {
      const target = route.request().url();
      if (new URL(target).origin === origin) return route.continue();
      external.push(target);
      return route.abort();
    });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    const response = await page.goto(url, { waitUntil: "load" });
    await page.evaluate(() => {
      window.__violations = [];
      document.addEventListener("securitypolicyviolation", (e) => window.__violations.push(`${e.violatedDirective} ${e.blockedURI}`));
    });
    await page.waitForSelector(renderSelector, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const rendered = await page.evaluate(measure);
    const documentOrigin = await page.evaluate(() => window.origin);
    const violations = await page.evaluate(
      async ([fetchUrl, imageUrl]) => {
        await fetch(fetchUrl).catch(() => {});
        const img = new Image();
        img.src = imageUrl;
        await new Promise((r) => setTimeout(r, 500));
        return window.__violations;
      },
      [probeFetch, probeImage],
    );
    const escape = await sameOriginEscape(context, page);
    return { status: response?.status(), headers: response?.headers() ?? {}, rendered, documentOrigin, external, pageErrors, violations, escape };
  } finally {
    await browser.close();
  }
}

/** Failures shared by every report: response headers, isolation from ARVA's origin and from the network. */
function commonFailures(r) {
  const csp = r.headers["content-security-policy"] ?? "";
  const failures = [];
  if (r.status !== 200) failures.push(`HTTP status ${r.status}`);
  if (!/(^|;\s*)sandbox\b/.test(csp) || csp.includes("allow-same-origin") || !csp.includes("default-src 'none'")) {
    failures.push(`CSP is not a sandbox without allow-same-origin and with default-src 'none': ${csp}`);
  }
  if (r.headers["x-content-type-options"] !== "nosniff") failures.push("missing X-Content-Type-Options: nosniff");
  if (r.headers["referrer-policy"] !== "no-referrer") failures.push("missing Referrer-Policy: no-referrer");
  if (r.documentOrigin !== "null") failures.push(`the report runs in origin ${r.documentOrigin}, not an opaque one`);
  if (!r.escape.opened) failures.push("the same-origin window probe could not open a window");
  else if (r.escape.scriptable || r.escape.popupOrigin !== "null") {
    failures.push(`a script in the report can reach ARVA's origin through a new window: ${JSON.stringify(r.escape)}`);
  }
  if (r.external.length) failures.push(`requests to other hosts: ${r.external.join(", ")}`);
  if (r.pageErrors.length) failures.push(`script errors: ${r.pageErrors.join(" | ")}`);
  if (r.violations.filter((v) => v.startsWith("connect-src") || v.startsWith("img-src")).length < 2) {
    failures.push(`probe requests were not blocked by the CSP: ${r.violations}`);
  }
  return failures;
}

/** CLI: `<url>` or `<report.html> <headers.json>`; prints a JSON summary and exits 1 on any failure. */
async function main(name, options, extraFailures) {
  const [target, headersFile] = process.argv.slice(2);
  if (!target) {
    console.error(`usage: ${name} <url> | <report.html> <headers.json>`);
    process.exit(2);
  }
  let server;
  let url = target;
  if (!/^https?:\/\//.test(target)) {
    server = await serve(target, JSON.parse(fs.readFileSync(headersFile, "utf8")));
    url = `http://127.0.0.1:${server.address().port}/report.html`;
  }
  const r = await inspect(url, options);
  server?.close();
  const failures = [...commonFailures(r), ...extraFailures(r)];
  const { rendered, documentOrigin, escape, external, pageErrors, violations } = r;
  console.log(JSON.stringify({ url, rendered, documentOrigin, escape, external, pageErrors, cspViolations: violations, failures }, null, 1));
  process.exit(failures.length ? 1 : 0);
}

module.exports = { main };
