/**
 * Checks a MultiQC project report as ARVA serves it, in headless Chromium: under the sandboxed CSP (with
 * ARVA's in-memory localStorage stand-in) the interactive plots and the general-statistics table render
 * without script errors; the page runs in an opaque origin, cannot script a same-origin window, and sends
 * no request to any other host, not even when its own scripts try (a probe fetch and image must be blocked).
 *
 *   node scripts/check_multiqc_report.cjs <URL of /jobs/{id}/outputs/arva_multiqc_report.html>
 *   node scripts/check_multiqc_report.cjs <report.html> <headers.json>
 *
 * The second form serves the saved report with the saved response headers (see the API test
 * test_multiqc_report_in_chromium). Prints a JSON summary; exits 1 if a check fails.
 */
const { main } = require("./report_browser_check.cjs");

main(
  "check_multiqc_report.cjs",
  {
    renderSelector: ".js-plotly-plot .main-svg",
    measure: () => ({
      plots: document.querySelectorAll(".js-plotly-plot").length,
      plotsWithSvg: [...document.querySelectorAll(".js-plotly-plot")].filter((p) => p.querySelector(".main-svg")).length,
      generalStatsRows: document.querySelectorAll("#general_stats_table_table tbody tr").length,
    }),
    // The report bundles code that can contact crossref, AI services and CDNs; the CSP must stop all of it.
    probeFetch: "https://api.crossref.org/works/10.1093/bioinformatics/btw354",
    probeImage: "https://assets-cdn.github.com/images/icons/emoji/octocat.png",
  },
  (r) => {
    const failures = [];
    const csp = r.headers["content-security-policy"] ?? "";
    if (!csp.includes("connect-src 'none'")) failures.push(`CSP lacks connect-src 'none': ${csp}`);
    if (r.rendered.plots === 0 || r.rendered.plotsWithSvg !== r.rendered.plots) failures.push(`plots not rendered: ${JSON.stringify(r.rendered)}`);
    if (r.rendered.generalStatsRows === 0) failures.push("general statistics table is empty");
    return failures;
  },
);
